#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <DHT.h>

// ══════════════════════════════════════════════════════════════
// CONFIGURAZIONE
// ══════════════════════════════════════════════════════════════
const char* SSID       = "TUO_WIFI";
const char* PASSWORD   = "TUA_PASSWORD";
const char* IDIS_BASE  = "http://192.168.1.X:8000";  // IP del tuo PC

#define DHT_PIN     4    // GPIO4 → DATA del DHT11
#define DHT_TYPE    DHT11
#define BUZZER_PIN  13   // GPIO13 → Buzzer attivo

DHT dht(DHT_PIN, DHT_TYPE);

// ══════════════════════════════════════════════════════════════
// SETUP
// ══════════════════════════════════════════════════════════════
void setup() {
  Serial.begin(115200);
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);

  dht.begin();

  // Connessione WiFi
  Serial.print("[WIFI] Connessione a ");
  Serial.println(SSID);
  WiFi.begin(SSID, PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  Serial.print("[WIFI] Connesso — IP: ");
  Serial.println(WiFi.localIP());
}

// ══════════════════════════════════════════════════════════════
// LOOP
// ══════════════════════════════════════════════════════════════
void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[WIFI] Disconnesso, riconnessione...");
    WiFi.reconnect();
    delay(5000);
    return;
  }

  postSensors();
  checkAlarm();

  delay(30000); // polling ogni 30 secondi
}

// ══════════════════════════════════════════════════════════════
// INVIA SENSORI A IDIS
// ══════════════════════════════════════════════════════════════
void postSensors() {
  float temp = dht.readTemperature();
  float hum  = dht.readHumidity();

  if (isnan(temp) || isnan(hum)) {
    Serial.println("[DHT11] ⚠ Lettura fallita, skip.");
    return;
  }

  Serial.printf("[DHT11] Temp: %.1f°C | Umidità: %.1f%%\n", temp, hum);

  StaticJsonDocument<128> doc;
  doc["temp"]     = temp;
  doc["humidity"] = hum;
  doc["co2"]      = nullptr; // nessun sensore CO2

  String body;
  serializeJson(doc, body);

  HTTPClient http;
  http.begin(String(IDIS_BASE) + "/sensors");
  http.addHeader("Content-Type", "application/json");
  int code = http.POST(body);
  Serial.printf("[HTTP] POST /sensors → %d\n", code);
  http.end();
}

// ══════════════════════════════════════════════════════════════
// CONTROLLA SVEGLIA
// ══════════════════════════════════════════════════════════════
void checkAlarm() {
  HTTPClient http;
  http.begin(String(IDIS_BASE) + "/alarm/check");
  int code = http.GET();

  if (code == 200) {
    String payload = http.getString();
    StaticJsonDocument<64> doc;
    deserializeJson(doc, payload);

    if (doc["ring"] == true) {
      Serial.println("[ALARM] 🔔 SVEGLIA!");
      suonaSveglia();
    } else {
      Serial.println("[ALARM] Nessuna sveglia attiva.");
    }
  } else {
    Serial.printf("[HTTP] GET /alarm/check → %d\n", code);
  }
  http.end();
}

// ══════════════════════════════════════════════════════════════
// PATTERN BUZZER ATTIVO (tipo Jarvis)
// ══════════════════════════════════════════════════════════════
void suonaSveglia() {
  // 3 bip brevi → pausa → 1 bip lungo
  for (int i = 0; i < 3; i++) {
    digitalWrite(BUZZER_PIN, HIGH); delay(200);
    digitalWrite(BUZZER_PIN, LOW);  delay(150);
  }
  delay(400);
  digitalWrite(BUZZER_PIN, HIGH); delay(800);
  digitalWrite(BUZZER_PIN, LOW);  delay(300);

  // Ripeti per 60 secondi (finché ring è true)
  // Il polling successivo a 30s spegnerà tutto
}
```

---

**Librerie da installare in Arduino IDE:**
- `DHT sensor library` — Adafruit
- `ArduinoJson` — Benoit Blanchon
- `HTTPClient` — built-in ESP32

**Pinout:**
```
DHT11   → GPIO4 (DATA), 3.3V, GND
Buzzer  → GPIO13, GND