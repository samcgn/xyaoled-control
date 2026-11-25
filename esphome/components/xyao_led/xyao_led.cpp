#include "xyao_led.h"
#include "esp_heap_caps.h"
#ifdef USE_ESP32
#include "esphome/core/log.h"
#include "esphome/core/hal.h"
#include "xyao_font.h"
#include <algorithm>
#include <functional>
#include <cstring>
#include <unordered_map>
#include "esphome/core/helpers.h"
#include "esphome/core/application.h"

namespace esphome {
namespace xyao_led {

static const char *const TAG = "xyao_led";
static const uint16_t SERVICE_AE00 = 0xAE00;
static const uint16_t CHAR_AE01 = 0xAE01;
static const uint16_t CHAR_AE02 = 0xAE02;
static const int PANEL_H = 16;
static const int MAX_FRAMES = 77;  // one 0x0207 frame is capped at 10000 bytes

// Several panels can hang off one ESP32: each gets an index (config order) for its own saved message and a
// staggered resend after (re)connecting, so they never all transfer a GIF at the same moment.
static uint8_t g_instances = 0;

void XyaoLED::setup() {
  this->index_ = g_instances++;
  this->pref_ = global_preferences->make_preference<Saved>(
      this->index_ == 0 ? fnv1_hash("xyao_led_last") : fnv1_hash(str_sprintf("xyao_led_last_%u", this->index_)));
  Saved s{};
  if (this->pref_.load(&s) && s.valid == 1) {
    s.text[sizeof(s.text) - 1] = s.font[sizeof(s.font) - 1] = s.effect[sizeof(s.effect) - 1] = 0;
    this->last_.valid = true;
    this->last_.text = s.text;
    this->last_.font = s.font;
    this->last_.effect = s.effect;
    this->last_.r = s.r;
    this->last_.g = s.g;
    this->last_.b = s.b;
    this->last_.mode = s.mode;
    this->last_.speed = s.speed;
    ESP_LOGI(TAG, "restored last message '%s'", s.text);
  }
}

// Planned restarts (OTA, reboot button): drop the BLE link cleanly. If the ESP32 just vanishes, the panel keeps
// the dead connection and stops advertising, so nothing can reconnect until the panel is power-cycled.
void XyaoLED::on_shutdown() {
  if (this->node_state == espbt::ClientState::ESTABLISHED) {
    ESP_LOGI(TAG, "disconnecting from the panel before restart");
    esp_ble_gattc_close((esp_gatt_if_t) this->parent()->get_gattc_if(), this->parent()->get_conn_id());
    esp_ble_gap_disconnect(this->parent()->get_remote_bda());
    delay(300);
  }
}

void XyaoLED::dump_config() {
  ESP_LOGCONFIG(TAG, "XYAO LED panel:");
  ESP_LOGCONFIG(TAG, "  Width: %d", this->width_);
}

void XyaoLED::enable_notify_(esp_gatt_if_t gattc_if) {
  esp_err_t err = esp_ble_gattc_register_for_notify(gattc_if, this->parent()->get_remote_bda(), this->ae02_handle_);
  if (err != ESP_OK)
    ESP_LOGW(TAG, "register_for_notify failed: %s", esp_err_to_name(err));
  auto *cccd = this->parent()->get_config_descriptor(this->ae02_handle_);
  if (cccd == nullptr) {
    ESP_LOGW(TAG, "AE02 CCCD not found; sending init without notify");
    this->init_pending_ = true;
    this->init_at_ = millis() + 300;
    return;
  }
  uint16_t en = 0x0001;
  esp_ble_gattc_write_char_descr(gattc_if, this->parent()->get_conn_id(), cccd->handle, sizeof(en), (uint8_t *) &en,
                                 ESP_GATT_WRITE_TYPE_RSP, ESP_GATT_AUTH_REQ_NONE);
}

void XyaoLED::dump_gatt_(esp_gatt_if_t gattc_if, uint16_t conn_id) {
  // lists every service and characteristic, so an unknown panel can be identified from the log
  esp_gattc_service_elem_t svc[16];
  uint16_t ns = 16;
  if (esp_ble_gattc_get_service(gattc_if, conn_id, nullptr, svc, &ns, 0) != ESP_GATT_OK) return;
  for (uint16_t i = 0; i < ns; i++) {
    std::string su = espbt::ESPBTUUID::from_uuid(svc[i].uuid).to_string();
    ESP_LOGI(TAG, "service %s handles 0x%04X-0x%04X", su.c_str(), svc[i].start_handle, svc[i].end_handle);
    esp_gattc_char_elem_t ch[16];
    uint16_t nc = 16;
    if (esp_ble_gattc_get_all_char(gattc_if, conn_id, svc[i].start_handle, svc[i].end_handle, ch, &nc, 0) != ESP_GATT_OK)
      continue;
    for (uint16_t j = 0; j < nc; j++) {
      std::string cu = espbt::ESPBTUUID::from_uuid(ch[j].uuid).to_string();
      ESP_LOGI(TAG, "  char %s handle 0x%04X props 0x%02X%s%s%s%s", cu.c_str(), ch[j].char_handle, ch[j].properties,
               (ch[j].properties & ESP_GATT_CHAR_PROP_BIT_READ) ? " read" : "",
               (ch[j].properties & ESP_GATT_CHAR_PROP_BIT_WRITE) ? " write" : "",
               (ch[j].properties & ESP_GATT_CHAR_PROP_BIT_WRITE_NR) ? " write-nr" : "",
               (ch[j].properties & ESP_GATT_CHAR_PROP_BIT_NOTIFY) ? " notify" : "");
    }
  }
}

void XyaoLED::gattc_event_handler(esp_gattc_cb_event_t event, esp_gatt_if_t gattc_if,
                                  esp_ble_gattc_cb_param_t *param) {
  switch (event) {
    case ESP_GATTC_SEARCH_CMPL_EVT: {
      if (this->ipixel_) {
        // iPixel Color: write FA02, notify FA03 (whatever service they sit in); no handshake
        auto find = [&](uint16_t u) -> uint16_t {
          esp_gattc_char_elem_t el;
          uint16_t cnt = 1;
          esp_bt_uuid_t uuid = espbt::ESPBTUUID::from_uint16(u).get_uuid();
          if (esp_ble_gattc_get_char_by_uuid(gattc_if, param->search_cmpl.conn_id, 0x0001, 0xFFFF, uuid, &el, &cnt) ==
                  ESP_GATT_OK && cnt > 0)
            return el.char_handle;
          return 0;
        };
        this->ae01_handle_ = find(0xFA02);
        this->ae02_handle_ = find(0xFA03);
        if (this->ae01_handle_ == 0) {
          ESP_LOGE(TAG, "FA02 not found - is this an iPixel panel? GATT table follows:");
          this->dump_gatt_(gattc_if, param->search_cmpl.conn_id);
          break;
        }
        if (this->ae02_handle_ != 0) {
          this->enable_notify_(gattc_if);
        } else {
          this->init_pending_ = true;
          this->init_at_ = millis() + 300;
        }
        this->node_state = espbt::ClientState::ESTABLISHED;
        ESP_LOGI(TAG, "connected, iPixel (FA02=0x%04X FA03=0x%04X)", this->ae01_handle_, this->ae02_handle_);
        break;
      }
      auto *c1 = this->parent()->get_characteristic(SERVICE_AE00, CHAR_AE01);
      auto *c2 = this->parent()->get_characteristic(SERVICE_AE00, CHAR_AE02);
      if (c1 == nullptr) {
        ESP_LOGE(TAG, "AE01 not found - is this an XYAO panel? GATT table follows:");
        this->dump_gatt_(gattc_if, param->search_cmpl.conn_id);
        break;
      }
      this->ae01_handle_ = c1->handle;
      if (c2 != nullptr) {
        this->ae02_handle_ = c2->handle;
        this->enable_notify_(gattc_if);
      } else {
        this->init_pending_ = true;
        this->init_at_ = millis() + 300;
      }
      this->node_state = espbt::ClientState::ESTABLISHED;
      ESP_LOGI(TAG, "connected (AE01=0x%04X AE02=0x%04X)", this->ae01_handle_, this->ae02_handle_);
      break;
    }
    case ESP_GATTC_CFG_MTU_EVT:
      this->mtu_ = param->cfg_mtu.mtu;
      break;
    case ESP_GATTC_WRITE_DESCR_EVT:
      // CCCD written - the panel is listening, send the handshake shortly
      this->init_pending_ = true;
      this->init_at_ = millis() + 300;
      break;
    case ESP_GATTC_NOTIFY_EVT: {
      auto &n = param->notify;
      if (n.handle == this->ae02_handle_)
        ESP_LOGD(TAG, "[%u] notify %s", this->index_, format_hex_pretty(n.value, std::min<uint16_t>(n.value_len, 40)).c_str());
      if (n.handle != this->ae02_handle_ || n.value_len < 12)
        break;
      const uint8_t *v = n.value;
      // Status frame: 88 FF 00 [03|05] .. .. W(u16) H(u16) 04 POWER ...
      // (00 03 seen on 32x16 firmware with power 01/00, 00 05 on 64x16 firmware with power 01/02)
      if (v[0] == 0x88 && v[1] == 0xFF && v[2] == 0x00 && (v[3] == 0x03 || v[3] == 0x05)) {
        this->reported_width_ = v[6] | (v[7] << 8);
        this->reported_height_ = v[8] | (v[9] << 8);
        bool on = v[11] == 0x01;
        if (!this->have_state_ || on != this->power_state_)
          ESP_LOGI(TAG, "status: %dx%d power=%s", this->reported_width_, this->reported_height_, on ? "ON" : "OFF");
        if (!this->have_state_ && this->reported_width_ != 0 && this->reported_width_ != this->width_)
          ESP_LOGW(TAG, "panel reports width %d but width is configured as %d", this->reported_width_, this->width_);
        this->power_state_ = on;
        this->have_state_ = true;
      }
      break;
    }
    case ESP_GATTC_WRITE_CHAR_EVT: {
      if (!this->ipixel_ || !this->tx_pending_ || param->write.handle != this->ae01_handle_)
        break;
      this->tx_pending_ = false;
      if (param->write.status != ESP_GATT_OK)
        ESP_LOGW(TAG, "[%u] write status %d", this->index_, param->write.status);
      if (this->txq_.empty())
        break;
      auto &msg = this->txq_.front();
      size_t chunk = std::min<size_t>(this->mtu_ > 3 ? this->mtu_ - 3 : 20, 244);
      this->tx_pos_ += std::min(chunk, msg.data.size() - this->tx_pos_);
      if (this->tx_pos_ >= msg.data.size()) {
        this->tx_next_at_ = millis() + msg.gap_after_ms;
        this->txq_.pop_front();
        this->tx_pos_ = 0;
      }
      break;
    }
    case ESP_GATTC_DISCONNECT_EVT:
      this->txq_.clear();
      this->tx_pos_ = 0;
      this->tx_pending_ = false;
      this->ae01_handle_ = 0;
      this->ae02_handle_ = 0;
      this->have_state_ = false;
      this->init_done_ = false;
      this->init_pending_ = false;
      this->seq_ = 1;
      break;
    default:
      break;
  }
}

void XyaoLED::loop() {
  if (this->ipixel_)
    this->tx_pump_();
  if (this->init_pending_ && (int32_t) (millis() - this->init_at_) >= 0 && this->ae01_handle_ != 0) {
    this->init_pending_ = false;
    if (!this->ipixel_) {
      ESP_LOGD(TAG, "sending init handshake");
      this->send_frames_hex(this->init_hex_);
    } else {
      // the iPixel app (and pypixelcolor) reads the device info first; some boards accept images only after it
      // [08 00 01 80 hh mm ss lang] - the clock values only set the panel's own clock
      ESP_LOGD(TAG, "[%u] requesting iPixel device info", this->index_);
      this->write_raw_({0x08, 0x00, 0x01, 0x80, 12, 0, 0, 0x00});
    }
    this->init_done_ = true;
    this->seq_ = 2;
    this->resend_pending_ = this->last_.valid;
    this->init_at_ = millis() + 1500 + this->index_ * 6000;
    return;
  }
  if (this->resend_pending_ && this->is_ready() && (int32_t) (millis() - this->init_at_) >= 0) {
    this->resend_pending_ = false;
    ESP_LOGI(TAG, "reconnected: re-sending the last message");
    auto l = this->last_;
    this->display_text(l.text, l.r, l.g, l.b, l.mode, l.speed, l.font, l.effect);
  }
}

void XyaoLED::write_raw_(const std::vector<uint8_t> &data) {
  if (this->node_state != espbt::ClientState::ESTABLISHED || this->ae01_handle_ == 0) {
    ESP_LOGW(TAG, "not connected; dropping %u bytes", (unsigned) data.size());
    return;
  }

  size_t chunk = std::min<size_t>(this->mtu_ > 3 ? this->mtu_ - 3 : 20, this->ipixel_ ? 244 : 512);
  for (size_t i = 0; i < data.size(); i += chunk) {
    size_t n = std::min(chunk, data.size() - i);
    esp_err_t err = ESP_FAIL;
    // write-without-response has no flow control: if the BLE stack's queue is full, wait and retry
    for (int attempt = 0; attempt < 8; attempt++) {
      if (this->node_state != espbt::ClientState::ESTABLISHED || this->ae01_handle_ == 0) {
        ESP_LOGW(TAG, "connection lost during transfer (%u of %u bytes sent)", (unsigned) i, (unsigned) data.size());
        return;
      }
      err = esp_ble_gattc_write_char((esp_gatt_if_t) this->parent()->get_gattc_if(), this->parent()->get_conn_id(),
                                     this->ae01_handle_, n, (uint8_t *) data.data() + i,
                                     // iPixel firmware (like its app) wants acknowledged writes; some boards drop
                                     // the link on unacknowledged ones
                                     this->ipixel_ ? ESP_GATT_WRITE_TYPE_RSP : ESP_GATT_WRITE_TYPE_NO_RSP,
                                     ESP_GATT_AUTH_REQ_NONE);
      if (err == ESP_OK)
        break;
      App.feed_wdt();
      delay(60 * (attempt + 1));
    }
    if (err != ESP_OK) {
      ESP_LOGW(TAG, "write failed at %u: %s - giving up", (unsigned) i, esp_err_to_name(err));
      return;
    }
    App.feed_wdt();
    if (i + n < data.size())
      delay(this->ipixel_ ? 80 : 45);  // pace the transfer; the panel reassembles by the frame's length field
  }
}

void XyaoLED::send_frames_hex(const std::string &hex) {
  std::string cur;
  auto flush = [&]() {
    std::vector<uint8_t> frame;
    for (size_t i = 0; i + 1 < cur.size(); i += 2)
      frame.push_back((uint8_t) strtol(cur.substr(i, 2).c_str(), nullptr, 16));
    if (!frame.empty()) {
      this->write_raw_(frame);
      delay(150);
    }
    cur.clear();
  };
  for (char ch : hex) {
    if (ch == '|')
      flush();
    else if (isxdigit((unsigned char) ch))
      cur += ch;
  }
  flush();
}

std::vector<uint8_t> XyaoLED::make_frame_(uint16_t type, const std::vector<uint8_t> &params) {
  // 99 AA 00 2E FF 88 | len(u16 LE, whole frame) | type(u16 LE) | seq | params
  std::vector<uint8_t> f = {0x99, 0xAA, 0x00, 0x2E, 0xFF, 0x88, 0, 0, (uint8_t) (type & 0xFF), (uint8_t) (type >> 8),
                            this->seq_};
  f.insert(f.end(), params.begin(), params.end());
  f[6] = f.size() & 0xFF;
  f[7] = (f.size() >> 8) & 0xFF;
  return f;
}

void XyaoLED::set_power(bool on) {
  if (this->ipixel_) {
    this->write_raw_({0x05, 0x00, 0x07, 0x01, (uint8_t) (on ? 1 : 0)});
    this->power_state_ = on;
    this->have_state_ = true;
    return;
  }
  this->write_raw_(this->make_frame_(0x0011, {(uint8_t) (on ? 0x01 : 0x02), 0x01, 0x01}));
  this->seq_++;
}

void XyaoLED::set_brightness(int level) {
  level = std::max(0, std::min(100, level));
  if (this->ipixel_) {
    this->write_raw_({0x05, 0x00, 0x04, 0x80, (uint8_t) level});
    return;
  }
  this->write_raw_(this->make_frame_(0x0012, {0x01, (uint8_t) level}));
  this->seq_++;
}

void XyaoLED::clear() {
  if (this->ipixel_)
    return;  // a new iPixel image replaces the screen; its own "clear" wipes the panel's memory
  this->write_raw_(this->make_frame_(0x0005, {0x01, 0x01, 0x00, 0x00, 0x00, 0x00}));
  delay(300);  // clear sends no completion notify
}

void XyaoLED::send_mono_(const std::vector<uint16_t> &cols, int n, uint8_t r, uint8_t g, uint8_t b, bool scroll,
                         int dur) {
  const int W = this->width_;
  const int bpr = W / 8;
  const int fb = PANEL_H * bpr;
  // 1-bit image payload: header(16) + RGB + mid(6) + n bitmaps (16 rows x W/8 bytes, LSB = leftmost pixel)
  std::vector<uint8_t> p = {0, 0, 0x00, 0x02, 0x00, 0x02, 0x01, 0x00, 0x00, 0x01, 0x00, 0x03, 0x00, 0x00, 0x00, 0x00};
  int sub = 12 + n * fb;
  p[0] = sub & 0xFF;
  p[1] = (sub >> 8) & 0xFF;
  p[9] = (uint8_t) n;
  p[11] = scroll ? 0x00 : 0x03;
  p.insert(p.end(), {r, g, b, 0x00, 0x00, 0xFF, (uint8_t) (scroll ? 1 : 0), (uint8_t) dur, 0x00});
  size_t base = p.size();
  p.resize(base + (size_t) n * fb, 0);
  for (int f = 0; f < n; f++)
    for (int row = 0; row < PANEL_H; row++)
      for (int c = 0; c < W; c++) {
        size_t col = (size_t) f * W + c;
        if (col < cols.size() && ((cols[col] >> row) & 1))
          p[base + f * fb + row * bpr + c / 8] |= 1 << (c % 8);
      }
  this->write_raw_(this->make_frame_(0x0204, {0xFF, 0x00}));
  delay(150);
  this->write_raw_(this->make_frame_(0x0207, p));
  delay(150);
  this->seq_++;
}

static const XyaoFont *find_font(const std::string &name) {
  for (int i = 0; i < XYAO_FONT_COUNT; i++)
    if (name == XYAO_FONTS[i].name)
      return &XYAO_FONTS[i];
  return &XYAO_FONTS[0];
}

static const XyaoIcon *find_icon(const std::string &name) {
  for (int i = 0; i < XYAO_ICON_COUNT; i++)
    if (name == XYAO_ICONS[i].name)
      return &XYAO_ICONS[i];
  return nullptr;
}

struct Rgb {
  uint8_t r, g, b;
  bool operator==(const Rgb &o) const { return r == o.r && g == o.g && b == o.b; }
};

// "[green]" / "[#00ff00]" at text[p]: returns the length of the tag (0 if none) and sets *out.
static size_t parse_colour_tag(const std::string &text, size_t p, Rgb *out) {
  if (text[p] != '[')
    return 0;
  size_t q = text.find(']', p);
  if (q == std::string::npos || q - p > 9)
    return 0;
  std::string name = text.substr(p + 1, q - p - 1);
  for (auto &ch : name)
    ch = tolower(ch);
  static const struct {
    const char *name;
    Rgb c;
  } COLOURS[] = {{"red", {255, 0, 0}},     {"green", {0, 255, 0}},     {"blue", {0, 0, 255}},
                 {"yellow", {255, 200, 0}}, {"white", {255, 255, 255}}, {"cyan", {0, 255, 255}},
                 {"magenta", {255, 0, 255}}, {"orange", {255, 100, 0}}};
  if (name.size() == 7 && name[0] == '#') {
    uint32_t v = strtoul(name.c_str() + 1, nullptr, 16);
    *out = {(uint8_t) (v >> 16), (uint8_t) ((v >> 8) & 0xFF), (uint8_t) (v & 0xFF)};
    return q - p + 1;
  }
  for (auto &c : COLOURS)
    if (name == c.name) {
      *out = c.c;
      return q - p + 1;
    }
  return 0;
}

// One rendered column: lit rows, plus the colour of the top (rows 0-7) and bottom (rows 8-15) halves.
struct Col {
  uint16_t bits;
  Rgb top, bot;
};

// Renders one line. ":name:" inserts an icon; ":name!:" blinks it (in the "off" phase it is drawn as
// "<name>_off" if that icon exists, otherwise blank). "[colour]" changes the colour from there on.
static Rgb rgb_of(uint32_t v) { return {(uint8_t) (v >> 16), (uint8_t) ((v >> 8) & 0xFF), (uint8_t) (v & 0xFF)}; }

// Renders one line. ":name:" inserts an icon; ":name!:" blinks it (in odd phases it is drawn as "<name>_off" if
// that icon exists, otherwise blank); if only "<name>_1", "<name>_2", ... exist the icon is animated (frame =
// phase). "[colour]" changes the colour from there on. Icons with fixed colours keep them.
static std::vector<Col> render_line(const std::string &text, const XyaoFont *fnt, bool allow_icons, int text_shift,
                                    int phase, int *anim_len, Rgb *colour, bool *has_colour) {
  std::vector<Col> out;
  bool after_icon = false;  // icons end with a blank column: skip the next glyph's leading blank one
  bool blink_text = false;  // inside "{...}": text blinks (blank in odd phases)
  for (size_t p = 0; p < text.size(); p++) {
    if (text[p] == '{' || text[p] == '}') {
      blink_text = text[p] == '{';
      if (blink_text)
        *anim_len = std::max(*anim_len, 2);
      continue;
    }
    size_t tag = parse_colour_tag(text, p, colour);
    if (tag) {
      *has_colour = true;
      p += tag - 1;
      continue;
    }
    if (allow_icons && text[p] == ':') {
      size_t q = text.find(':', p + 1);
      if (q != std::string::npos && q - p > 1 && q - p <= 20) {
        std::string name = text.substr(p + 1, q - p - 1);
        bool blink = !name.empty() && name.back() == '!';
        if (blink)
          name.pop_back();
        const XyaoIcon *icon = find_icon(name);
        const XyaoIcon *draw = icon;
        if (icon == nullptr && (icon = find_icon(name + "_1")) != nullptr) {
          int n = 1;
          while (n < 16 && find_icon(name + "_" + std::to_string(n + 1)) != nullptr)
            n++;
          *anim_len = std::max(*anim_len, n);
          draw = find_icon(name + "_" + std::to_string(phase % n + 1));
        }
        if (icon != nullptr) {
          if (blink) {
            *anim_len = std::max(*anim_len, 2);
            if (phase % 2)
              draw = find_icon(name + "_off");
          }
          Rgb top = icon->top ? rgb_of(icon->top) : *colour, bot = icon->bottom ? rgb_of(icon->bottom) : *colour;
          if (icon->top || icon->bottom)
            *has_colour = true;
          for (int k = 0; k < icon->width; k++)
            out.push_back({(uint16_t) (draw != nullptr && k < draw->width ? XYAO_ICON_COLS[draw->offset + k] : 0), top,
                           bot});
          after_icon = true;
          p = q;
          continue;
        }
      }
    }
    unsigned char ch = text[p];
    if (ch < 32 || ch > 126)
      ch = '?';
    int i = ch - 32;
    int k0 = (after_icon && ch != ' ' && fnt->widths[i] > 1 && fnt->columns[fnt->offsets[i]] == 0) ? 1 : 0;
    after_icon = false;
    bool hide = blink_text && (phase % 2);
    for (int k = k0; k < fnt->widths[i]; k++)
      out.push_back({(uint16_t) (hide ? 0 : fnt->columns[fnt->offsets[i] + k] << text_shift), *colour, *colour});
  }
  return out;
}

// Renders one page: one line, or two lines ('|' / newline) in the 8-row "small" font.
static std::vector<Col> render_page(const std::string &text, const XyaoFont *base, Rgb colour, const char **used,
                                    int phase, int *anim_len, bool *has_colour, bool trim = true) {
  std::vector<std::string> lines(1);
  for (char ch : text) {
    if ((ch == '|' || ch == '\n') && lines.size() < 2)
      lines.emplace_back();
    else if (ch != '\r')
      lines.back() += ch;
  }
  bool two = lines.size() == 2;
  const XyaoFont *fnt = two ? find_font("small") : base;
  bool small = std::string(fnt->name) == "small";
  *used = fnt->name;
  std::vector<std::vector<Col>> rendered;
  size_t w = 0;
  for (size_t li = 0; li < lines.size(); li++) {
    // icons are 16 rows tall, so they only appear on single-line pages; small text is centred vertically
    // small glyphs use rows 0-6 (1-row descenders), so line 1 = rows 0-6, row 7 blank, line 2 = rows 8-14
    int shift = two ? (li == 0 ? 0 : 8) : (small ? 4 : 0);
    auto cols = render_line(lines[li], fnt, !two, shift, phase, anim_len, &colour, has_colour);
    w = std::max(w, cols.size());
    rendered.push_back(cols);
  }
  std::vector<Col> page(w, Col{0, {0, 0, 0}, {0, 0, 0}});  // overlay the lines, each centred
  for (size_t li = 0; li < rendered.size(); li++) {
    auto &line = rendered[li];
    size_t pad = (w - line.size()) / 2;
    for (size_t k = 0; k < line.size(); k++) {
      Col &d = page[pad + k];
      d.bits |= line[k].bits;
      if (!two || li == 0)
        d.top = line[k].top;
      if (!two || li == 1)
        d.bot = line[k].bot;
    }
  }
  // trim blank columns at the edges (glyph spacing) so fit checks and centring use the visible width
  if (!trim)
    return page;
  while (!page.empty() && page.back().bits == 0)
    page.pop_back();
  size_t lead = 0;
  while (lead < page.size() && page[lead].bits == 0)
    lead++;
  page.erase(page.begin(), page.begin() + lead);
  return page;
}

static std::vector<uint16_t> bits_of(const std::vector<Col> &cols) {
  std::vector<uint16_t> out;
  for (auto &c : cols)
    out.push_back(c.bits);
  return out;
}

// ---- minimal GIF89a encoder (8-colour palette, "uncompressed" LZW) ----
class GifWriter {
 public:
  // compact: full LZW compression and per-frame changed-area rectangles (iPixel panels). Otherwise the simple
  // form the XYAO panels are known to accept: whole frames, 4-bit codes with a clear every 5 pixels.
  GifWriter(int w, int h, const std::vector<Rgb> &palette, bool compact = false) : w_(w), h_(h), compact_(compact) {
    const char *sig = "GIF89a";
    out.insert(out.end(), sig, sig + 6);
    put16(w);
    put16(h);
    out.push_back(0xF2);  // global colour table, 3 bits/colour channel res, 8 entries
    out.push_back(0);
    out.push_back(0);
    for (int i = 0; i < 8; i++) {
      Rgb c = i < (int) palette.size() ? palette[i] : Rgb{0, 0, 0};
      out.push_back(c.r);
      out.push_back(c.g);
      out.push_back(c.b);
    }
    const uint8_t loop[] = {0x21, 0xFF, 0x0B, 'N', 'E', 'T', 'S', 'C', 'A', 'P', 'E', '2', '.', '0',
                            0x03, 0x01, 0x00, 0x00, 0x00};
    out.insert(out.end(), loop, loop + sizeof(loop));
  }
  void frame(const std::vector<uint8_t> &px, int delay_cs) {
    // disposal 1 (leave in place): a later frame only needs to cover what changed
    const uint8_t gce[] = {0x21, 0xF9, 0x04, 0x04, (uint8_t) (delay_cs & 0xFF), (uint8_t) (delay_cs >> 8), 0x00, 0x00};
    out.insert(out.end(), gce, gce + sizeof(gce));
    int x0 = 0, y0 = 0, x1 = w_ - 1, y1 = h_ - 1;
    if (this->compact_ && !this->prev_.empty()) {
      x0 = w_;
      y0 = h_;
      x1 = -1;
      y1 = -1;
      for (int y = 0; y < h_; y++)
        for (int x = 0; x < w_; x++)
          if (px[y * w_ + x] != this->prev_[y * w_ + x]) {
            x0 = std::min(x0, x);
            x1 = std::max(x1, x);
            y0 = std::min(y0, y);
            y1 = std::max(y1, y);
          }
      if (x1 < 0)
        x0 = x1 = y0 = y1 = 0;  // nothing changed: a 1-pixel frame just carries the delay
    }
    if (this->compact_)
      this->prev_ = px;
    int fw = x1 - x0 + 1, fh = y1 - y0 + 1;
    std::vector<uint8_t> sub;
    sub.reserve((size_t) fw * fh);
    for (int y = y0; y <= y1; y++)
      for (int x = x0; x <= x1; x++)
        sub.push_back(px[y * w_ + x] & 7);
    out.push_back(0x2C);
    put16(x0);
    put16(y0);
    put16(fw);
    put16(fh);
    out.push_back(0x00);
    out.push_back(3);  // LZW minimum code size
    std::vector<uint8_t> data = this->compact_ ? lzw_(sub) : simple_(sub);
    for (size_t i = 0; i < data.size(); i += 255) {
      size_t n = std::min<size_t>(255, data.size() - i);
      out.push_back((uint8_t) n);
      out.insert(out.end(), data.begin() + i, data.begin() + i + n);
    }
    out.push_back(0x00);
  }
  std::vector<uint8_t> finish() {
    out.push_back(0x3B);
    return out;
  }
  std::vector<uint8_t> out;

 private:
  struct Bits {
    std::vector<uint8_t> data;
    uint32_t acc{0};
    int nbits{0};
    void put(uint32_t code, int size) {
      acc |= code << nbits;
      nbits += size;
      while (nbits >= 8) {
        data.push_back(acc & 0xFF);
        acc >>= 8;
        nbits -= 8;
      }
    }
    std::vector<uint8_t> done() {
      if (nbits > 0)
        data.push_back(acc & 0xFF);
      return data;
    }
  };
  static std::vector<uint8_t> simple_(const std::vector<uint8_t> &px) {
    // 4-bit codes: clear(8), end(9); a clear before the table would grow past 15
    Bits b;
    int since_clear = 0;
    b.put(8, 4);
    for (uint8_t p : px) {
      if (since_clear == 5) {
        b.put(8, 4);
        since_clear = 0;
      }
      b.put(p, 4);
      since_clear++;
    }
    b.put(9, 4);
    return b.done();
  }
  static std::vector<uint8_t> lzw_(const std::vector<uint8_t> &px) {
    // standard GIF LZW (as in gif.h): min code size 3, codes up to 12 bits, clear when the table is full
    const int min = 3, clear = 1 << min, eoi = clear + 1;
    std::unordered_map<uint32_t, uint16_t> next;  // (code << 3 | pixel) -> extended code
    Bits b;
    int size = min + 1, max_code = eoi;
    b.put(clear, size);
    int cur = -1;
    for (uint8_t p : px) {
      if (cur < 0) {
        cur = p;
        continue;
      }
      auto it = next.find((uint32_t) cur << 3 | p);
      if (it != next.end()) {
        cur = it->second;
        continue;
      }
      b.put(cur, size);
      next[(uint32_t) cur << 3 | p] = (uint16_t) ++max_code;
      if (max_code >= (1 << size))
        size++;
      if (max_code == 4095) {
        b.put(clear, size);
        next.clear();
        size = min + 1;
        max_code = eoi;
      }
      cur = p;
    }
    if (cur >= 0)
      b.put(cur, size);
    b.put(eoi, size);
    return b.done();
  }
  void put16(int v) {
    out.push_back(v & 0xFF);
    out.push_back((v >> 8) & 0xFF);
  }
  int w_, h_;
  bool compact_;
  std::vector<uint8_t> prev_;
};

void XyaoLED::send_part_(uint16_t type, const std::vector<uint8_t> &hdr, const uint8_t *data, size_t n) {
  // one allocation per frame: 11-byte frame header + params header + a slice of the payload
  std::vector<uint8_t> f;
  f.reserve(11 + hdr.size() + n);
  f.insert(f.end(), {0x99, 0xAA, 0x00, 0x2E, 0xFF, 0x88, 0, 0, (uint8_t) (type & 0xFF), (uint8_t) (type >> 8), this->seq_});
  f.insert(f.end(), hdr.begin(), hdr.end());
  f.insert(f.end(), data, data + n);
  f[6] = f.size() & 0xFF;
  f[7] = (f.size() >> 8) & 0xFF;
  this->write_raw_(f);
}

static uint32_t crc32_ieee(const uint8_t *d, size_t n) {
  uint32_t c = 0xFFFFFFFF;
  for (size_t i = 0; i < n; i++) {
    c ^= d[i];
    for (int k = 0; k < 8; k++)
      c = (c >> 1) ^ (0xEDB88320 & (0 - (c & 1)));
  }
  return ~c;
}

// iPixel Color image upload (see lucagoc/pypixelcolor send_image): the file in 12 KB windows, each
// [len u16 = 2 + rest] [03 gif | 02 png] 00 [00 first | 02 next] [file size u32] [crc32 u32] [02 gif | 00] [slot 0] data
void XyaoLED::send_ipixel_file_(const std::vector<uint8_t> &file, bool gif) {
  const size_t WIN = 12 * 1024;
  uint32_t size = file.size(), crc = crc32_ieee(file.data(), file.size());
  ESP_LOGD(TAG, "[%u] iPixel upload %u bytes, crc %08X", this->index_, (unsigned) size, (unsigned) crc);
  // a new image replaces whatever is still waiting to go out (but not a window already half sent)
  while (this->txq_.size() > (this->tx_pos_ > 0 ? 1u : 0u))
    this->txq_.pop_back();
  for (size_t pos = 0, w = 0; pos < file.size(); pos += WIN, w++) {
    size_t n = std::min(WIN, file.size() - pos);
    std::vector<uint8_t> m;
    m.reserve(15 + n);
    size_t len = 2 + 13 + n;
    m.insert(m.end(), {(uint8_t) (len & 0xFF), (uint8_t) (len >> 8), (uint8_t) (gif ? 0x03 : 0x02), 0x00,
                       (uint8_t) (w == 0 ? 0x00 : 0x02)});
    for (int k = 0; k < 4; k++)
      m.push_back((size >> (8 * k)) & 0xFF);
    for (int k = 0; k < 4; k++)
      m.push_back((crc >> (8 * k)) & 0xFF);
    m.insert(m.end(), {(uint8_t) (gif ? 0x02 : 0x00), 0x00});
    m.insert(m.end(), file.begin() + pos, file.begin() + pos + n);
    // compact GIFs are ~1 KB, so a direct (blocking) send of acknowledged 244-byte chunks is short; this is the
    // pacing both iPixel boards accepted reliably
    this->write_raw_(m);
    if (pos + n < file.size()) {
      for (int t = 0; t < 15; t++) {  // the panel acks each 12 KB window on FA03; give it time
        App.feed_wdt();
        delay(100);
      }
    }
  }
}

void XyaoLED::tx_pump_() {
  if (this->txq_.empty())
    return;
  if (this->node_state != espbt::ClientState::ESTABLISHED || this->ae01_handle_ == 0) {
    this->txq_.clear();
    this->tx_pos_ = 0;
    this->tx_pending_ = false;
    return;
  }
  uint32_t now = millis();
  if (this->tx_pending_) {
    if (now - this->tx_sent_at_ < 3000)
      return;
    ESP_LOGW(TAG, "[%u] write not acknowledged; dropping the message", this->index_);
    this->txq_.pop_front();
    this->tx_pos_ = 0;
    this->tx_pending_ = false;
    return;
  }
  if ((int32_t) (now - this->tx_next_at_) < 0)
    return;
  auto &msg = this->txq_.front();
  size_t chunk = std::min<size_t>(this->mtu_ > 3 ? this->mtu_ - 3 : 20, 244);
  size_t n = std::min(chunk, msg.data.size() - this->tx_pos_);
  esp_err_t err = esp_ble_gattc_write_char((esp_gatt_if_t) this->parent()->get_gattc_if(), this->parent()->get_conn_id(),
                                           this->ae01_handle_, n, msg.data.data() + this->tx_pos_,
                                           ESP_GATT_WRITE_TYPE_RSP, ESP_GATT_AUTH_REQ_NONE);
  if (err != ESP_OK) {
    this->tx_next_at_ = now + 50;  // stack busy: try again shortly
    return;
  }
  this->tx_pending_ = true;
  this->tx_sent_at_ = now;
}

void XyaoLED::send_gif_(const std::vector<uint8_t> &gif, int frames) {
  if (this->ipixel_) {
    this->send_ipixel_file_(gif, true);
    return;
  }
  // small parts keep the peak heap use low (BLE + Wi-Fi leave little contiguous RAM)
  const size_t PART = 4000;
  ESP_LOGD(TAG, "send gif %u bytes, free heap %u, largest block %u", (unsigned) gif.size(),
           (unsigned) heap_caps_get_free_size(MALLOC_CAP_8BIT), (unsigned) heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));
  this->write_raw_(this->make_frame_(0x0204, {0xFF, 0x00}));
  delay(150);
  std::vector<uint8_t> hdr = {(uint8_t) (gif.size() & 0xFF), (uint8_t) (gif.size() >> 8)};
  if (frames <= 1 && gif.size() <= PART) {
    hdr.insert(hdr.end(), {0x00, 0x02, 0x00, 0x01, 0x01, 0x00, 0x00, 0x01, 0x00, 0x08, 0x00});
    this->send_part_(0x0207, hdr, gif.data(), gif.size());
  } else {
    // animations are always split across 0x0207 + at least one 0x0209
    size_t split = std::min(PART, std::max<size_t>(1, gif.size() / 2));
    if (frames <= 1)
      hdr.insert(hdr.end(), {0x00, 0x02, 0x00, 0x01, 0x01, 0x00, 0x00, 0x01, 0x00, 0x08, 0x00});
    else
      hdr.insert(hdr.end(), {0x00, 0x03, 0x00, 0x00, 0x00, 0x00, 0x00, (uint8_t) frames, 0x00, 0x03, 0x00});
    this->send_part_(0x0207, hdr, gif.data(), split);
    for (size_t i = split; i < gif.size(); i += PART) {
      size_t n = std::min(PART, gif.size() - i);
      delay(150);
      this->send_part_(0x0209, {(uint8_t) (n & 0xFF), (uint8_t) (n >> 8), 0x00, 0x02, 0x00}, gif.data() + i, n);
    }
  }
  delay(150);
  this->seq_++;
}

void XyaoLED::display_text(const std::string &text, uint8_t r, uint8_t g, uint8_t b, int mode, int speed,
                           const std::string &font, const std::string &effect) {
  if (!this->is_ready()) {
    ESP_LOGW(TAG, "display_text: panel not connected");
    return;
  }
  // Several panels share one ESP32 (no PSRAM): building and sending a GIF needs ~25 KB. If another panel's
  // transfer still holds that memory, wait and retry rather than starve the Bluetooth stack.
  // largest free block matters, not the total: the heap fragments with three BLE links and Wi-Fi
  if ((heap_caps_get_free_size(MALLOC_CAP_8BIT) < 40000 || heap_caps_get_largest_free_block(MALLOC_CAP_8BIT) < 26000 ||
       !this->txq_.empty()) &&
      this->busy_retries_ < 20) {
    this->busy_retries_++;
    this->set_timeout("busy_retry", 1500, [this, text, r, g, b, mode, speed, font, effect]() {
      this->display_text(text, r, g, b, mode, speed, font, effect);
    });
    return;
  }
  this->busy_retries_ = 0;
  this->last_.valid = true;
  this->last_.text = text;
  this->last_.font = font;
  this->last_.effect = effect;
  this->last_.r = r;
  this->last_.g = g;
  this->last_.b = b;
  this->last_.mode = mode;
  this->last_.speed = speed;
  {
    Saved s{};
    strncpy(s.text, text.c_str(), sizeof(s.text) - 1);
    strncpy(s.font, font.c_str(), sizeof(s.font) - 1);
    strncpy(s.effect, effect.c_str(), sizeof(s.effect) - 1);
    s.r = r;
    s.g = g;
    s.b = b;
    s.valid = 1;
    s.mode = mode;
    s.speed = speed;
    this->pref_.save(&s);
  }
  const int W = this->width_;
  const Rgb base_colour{r, g, b};
  const XyaoFont *base = find_font(font.empty() ? this->default_font_ : font);
  struct Page {
    std::string text;
    const XyaoFont *fnt;
    std::vector<Col> on;
    int anim;  // animation length in steps: 0 = static, 2 = blinking, n = n-frame icon
  };
  // '~' splits the message into pages the panel shows in turn
  std::vector<std::string> parts(1);
  for (char ch : text) {
    if (ch == '~')
      parts.emplace_back();
    else
      parts.back() += ch;
  }
  const char *used = base->name;
  std::vector<Page> pages;
  bool any_blink = false, any_colour = false;
  for (auto &part : parts) {
    Page pg{part, base, {}, 0};
    pg.on = render_page(part, base, base_colour, &used, 0, &pg.anim, &any_colour);
    // auto-fit: if a page is wider than the panel, try narrower fonts before clipping / scrolling
    if ((int) pg.on.size() > W && mode != 2) {
      // take the first narrower font that fits; if none does, the narrowest result (least clipping)
      std::vector<Col> best = pg.on;
      const XyaoFont *best_fnt = base;
      const char *best_used = used;
      for (const char *alt : {"narrow", "tall", "slim", "small"}) {
        const char *u2 = used;
        int bl = 0;
        bool co = false;
        auto p2 = render_page(part, find_font(alt), base_colour, &u2, 0, &bl, &co);
        if (p2.size() < best.size()) {
          best = p2;
          best_fnt = find_font(alt);
          best_used = u2;
        }
        if ((int) p2.size() <= W)
          break;
      }
      // a single animated page can't scroll, and pages never scroll: use the narrowest rendering
      if ((int) best.size() <= W || pg.anim || parts.size() > 1 || this->ipixel_) {
        pg.on = best;
        pg.fnt = best_fnt;
        used = best_used;
      }
    }
    if (pg.anim)
      any_blink = true;
    pages.push_back(pg);
  }
  bool flash = effect == "flash";
  bool multi = pages.size() > 1;
  // iPixel panels only take image files, so everything goes out as a GIF (no native scrolling yet)
  bool scroll = !this->ipixel_ && !multi && !any_blink && (mode == 2 || (mode == 0 && (int) pages[0].on.size() > W));
  this->clear();  // otherwise each image is appended to the panel's looping playlist

  if (scroll) {
    // a wide strip the panel scrolls itself (one colour): 2px lead + text + one screen of blank trail
    std::vector<uint16_t> cols(2, 0);
    auto bits = bits_of(pages[0].on);
    cols.insert(cols.end(), bits.begin(), bits.end());
    int n = std::min(MAX_FRAMES, ((int) cols.size() + W + W - 1) / W);
    cols.resize((size_t) n * W, 0);
    std::vector<uint16_t> black(W, 0);
    this->send_mono_(black, 1, 0, 0, 0, false, 0x05);  // hides the previous screen scrolling out
    this->send_mono_(cols, n, r, g, b, true, speed > 0 ? std::min(speed, 255) : 0x3C);
  } else if (any_blink || any_colour || this->ipixel_) {
    // full-colour GIF: per-pixel colour and exact timing (centiseconds)
    std::vector<Rgb> palette = {{0, 0, 0}};
    auto idx = [&](const Rgb &c) -> uint8_t {
      for (size_t i = 0; i < palette.size(); i++)
        if (palette[i] == c)
          return i;
      if (palette.size() < 8) {
        palette.push_back(c);
        return palette.size() - 1;
      }
      return 1;
    };
    auto raster = [&](const std::vector<Col> &pg) {
      std::vector<uint8_t> px((size_t) W * PANEL_H, 0);
      int pad = (int) pg.size() < W ? (W - (int) pg.size()) / 2 : 0;
      for (size_t k = 0; k < pg.size() && pad + (int) k < W; k++)
        for (int y = 0; y < PANEL_H; y++)
          if ((pg[k].bits >> y) & 1)
            px[y * W + pad + k] = idx(y < 8 ? pg[k].top : pg[k].bot);
      return px;
    };
    // Frames are generated twice instead of being stored (a long animation would need ~60 KB): pass 1 only
    // completes the palette (raster() adds colours), pass 2 writes each frame straight into the GIF.
    const int page_cs = speed > 0 ? speed * 10 : 250;  // page time; speed is in tenths of a second
    const int blink_cs = 25;                           // 2 blinks per second
    std::vector<uint8_t> blank((size_t) W * PANEL_H, 0);
    // per animated page: steps, and one trim for all its steps so moving icons (e.g. the sleigh) keep their place
    struct Geo {
      int steps;
      size_t len, lead, trail;
    };
    std::vector<Geo> geo(pages.size(), Geo{0, 0, 0, 0});
    auto step_cols = [&](const Page &pg, int k) {
      int d1 = 0;
      bool d2 = false;
      const char *u3 = used;
      return render_page(pg.text, pg.fnt, base_colour, &u3, k, &d1, &d2, false);
    };
    for (size_t pi = 0; pi < pages.size(); pi++) {
      auto &pg = pages[pi];
      if (!pg.anim)
        continue;
      Geo g{std::max(pg.anim, page_cs / blink_cs), 0, 0, 0};
      g.steps = std::min(120, ((g.steps + pg.anim - 1) / pg.anim) * pg.anim);
      for (int k = 0; k < g.steps; k++)
        g.len = std::max(g.len, step_cols(pg, k).size());
      g.lead = g.trail = g.len;
      for (int k = 0; k < g.steps; k++) {
        auto fr = step_cols(pg, k);
        fr.resize(g.len, Col{0, {0, 0, 0}, {0, 0, 0}});
        size_t x = 0, y = 0;
        while (x < g.len && fr[x].bits == 0)
          x++;
        while (y < g.len && fr[g.len - 1 - y].bits == 0)
          y++;
        g.lead = std::min(g.lead, x);
        g.trail = std::min(g.trail, y);
      }
      geo[pi] = g;
    }
    auto generate = [&](const std::function<void(const std::vector<uint8_t> &, int)> &emit) {
      for (size_t pi = 0; pi < pages.size(); pi++) {
        auto &pg = pages[pi];
        if (pg.anim) {
          const Geo &g = geo[pi];
          size_t lead = std::min(g.lead, g.len), trail = std::min(g.trail, g.len - lead);
          for (int k = 0; k < g.steps; k++) {
            auto fr = step_cols(pg, k);
            fr.resize(g.len, Col{0, {0, 0, 0}, {0, 0, 0}});
            std::vector<Col> cut(fr.begin() + lead, fr.end() - trail);
            emit(raster(cut), blink_cs);
          }
        } else if (flash) {
          emit(raster(pg.on), 50);
          emit(blank, 50);
        } else {
          emit(raster(pg.on), page_cs);
        }
      }
    };
    const int max_frames = this->ipixel_ ? 254 : 253;  // XYAO: room for the sacrificial frame
    int nframes = 0;
    generate([&](const std::vector<uint8_t> &, int) { nframes++; });  // pass 1: palette + frame count
    nframes = std::min(nframes, max_frames);
    // the XYAO panel does not show the final frame of an animation: a 10 ms copy of it is added as a sacrificial frame
    bool sacrificial = nframes > 1 && !this->ipixel_;
    GifWriter gw(W, PANEL_H, palette, this->ipixel_);
    int written = 0;
    std::vector<uint8_t> last;
    generate([&](const std::vector<uint8_t> &px, int cs) {  // pass 2: write
      if (written >= nframes)
        return;
      gw.frame(px, cs);
      if (sacrificial && ++written == nframes)
        last = px;
      else if (!sacrificial)
        written++;
    });
    if (sacrificial)
      gw.frame(last, 1);
    int total = nframes + (sacrificial ? 1 : 0);
    auto gif = gw.finish();
    if (gif.size() > 0xFFFF) {
      ESP_LOGW(TAG, "GIF too large (%u bytes)", (unsigned) gif.size());
      return;
    }
    this->send_gif_(gif, total);
    ESP_LOGD(TAG, "gif %u bytes, %d frames, %u colours", (unsigned) gif.size(), total, (unsigned) palette.size());
  } else {
    // one colour: 1-bit image, one frame per page (+ a blank frame after each when flashing)
    int per = flash ? 2 : 1;
    int n = std::min(MAX_FRAMES, (int) pages.size() * per);
    std::vector<uint16_t> cols((size_t) n * W, 0);
    for (size_t pi = 0; pi < pages.size() && (int) (pi * per) < n; pi++) {
      auto bits = bits_of(pages[pi].on);
      int pad = (int) bits.size() < W ? (W - (int) bits.size()) / 2 : 0;
      for (size_t k = 0; k < bits.size() && pad + (int) k < W; k++)
        cols[pi * per * W + pad + k] = bits[k];
    }
    int dur = speed > 0 ? std::min(speed, 255) : (flash && !multi ? 0x14 : 0x3C);
    this->send_mono_(cols, n, r, g, b, false, dur);
  }
  ESP_LOGI(TAG, "text '%s' (%s, %d page%s, %s%s%s)", text.c_str(), used, (int) pages.size(), multi ? "s" : "",
           scroll ? "scroll" : "static", any_blink ? ", blink" : "", any_colour ? ", colour" : "");
}

}  // namespace xyao_led
}  // namespace esphome
#endif
