// ============================================================
// FIRMWARE UNIFICATO — Sveglia + IR LED + Radar LD2410C
// ============================================================

#include <WiFi.h>
#include <WebServer.h>
#include <time.h>
#include <SPI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_GC9A01A.h>
#include <DHT.h>
#include <IRremoteESP8266.h>
#include <IRsend.h>

// --- DATI WI-FI ---
const char* ssid     = "TP-Link_56C8";
const char* password = "28081807";

// --- CONFIGURAZIONE ORA ---
const char* ntpServer          = "pool.ntp.org";
const long  gmtOffset_sec      = 3600;
const int   daylightOffset_sec = 3600;

// --- SVEGLIA PROGRAMMATA ---
bool svegliaEseguita     = false;
bool spegnimentoEseguito = false;
int  svegliaOra          = 9;
int  svegliaMinuto       = 0;
int  spegnimentoOra      = 9;
int  spegnimentoMinuto   = 45;
bool svegliaAbilitata    = true;

// --- CONFIGURAZIONE HARDWARE ---
#define LDR_PIN         34
#define TFT_CS           5
#define TFT_DC          15
#define TFT_RST          2
#define DHTPIN           4
#define DHTTYPE        DHT11
#define BUTTON_PIN      14
#define BUZZER_PIN      27

// --- CONFIGURAZIONE RADAR LD2410C ---
// OUT pin: HIGH=presenza, LOW=assenza (risposta immediata, usato per feature 1 e 3)
// Serial2: parsing UART per stato dettagliato mov/stat (usato per feature 2)
#define RADAR_OUT_PIN   35
#define RADAR_RX        16   // ESP32 RX2 <- TX del LD2410C
#define RADAR_TX        17   // ESP32 TX2 -> RX del LD2410C

// --- CONFIGURAZIONE IR ---
const uint16_t PIN_TRASMETTITORE = 12;

Adafruit_GC9A01A tft(&SPI, TFT_DC, TFT_CS, TFT_RST);
DHT dht(DHTPIN, DHTTYPE);
IRsend irsend(PIN_TRASMETTITORE);
WebServer server(80);

// ============================================================
// DATABASE IR
// ============================================================
const uint32_t LUCE_ON       = 0xFF02FD;
const uint32_t LUCE_OFF      = 0xFF02FD;
const uint32_t LUCE_ROSSA    = 0xFF1AE5;
const uint32_t LUCE_BIANCA   = 0xFF22DD;
const uint32_t LUCE_VERDE    = 0xFF8A75;
const uint32_t LUCE_VIOLA    = 0xFFB24D;
const uint32_t LUCE_DIM_MENO = 0xFFBA45;
const uint32_t LUCE_DIM_PIU  = 0xFF3AC5;


// --- IR STATE MACHINE ---
const unsigned long IR_STEP_MS = 160;

enum ComandoIR {
  IR_NESSUNO = 0,
  IR_ROSSO, IR_OFF, IR_LAVORO, IR_CYBERPUNK,
  IR_MATRIX, IR_LUM_MAX, IR_LUM_MEDIA, IR_LUM_BASSA, IR_NOTTE_LIGHT
};

struct PassoIR { uint32_t codice; };

ComandoIR     irComandoAttivo = IR_NESSUNO;
int           irStepCorrente  = 0;
unsigned long irUltimoStep    = 0;
bool          irInCorso       = false;
PassoIR       irSequenza[25];
int           irSequenzaLen   = 0;

// ============================================================
// STATO SISTEMA
// ============================================================
bool statoLuci     = false;

// Stato display: 0=spento, 1=always-on (grigio), 2=pieno (attivo)
uint8_t statoDisplay  = 2;
bool    displayAcceso = true; // true se display NON è in sleep hardware
bool          displayInWake    = false;
unsigned long displayWakeStart = 0;
const unsigned long DISPLAY_WAKE_MS = 120;

// --- Radar ---
// statoRadar: 0=nessuno, 1=movimento, 2=stazionario, 3=entrambi
uint8_t statoRadar           = 0;
uint8_t statoPrecedenteRadar = 0;
bool    presenzaRilevata     = false;

// --- LDR / Night Mode ---
const int SOGLIA_BUIO_ENTRA = 1700; // scende sotto → notte
const int SOGLIA_BUIO_ESCI  = 1900; // sale sopra  → giorno
bool isInNightMode    = false;

// --- Colori GIORNO ---
#define COLOR_DAY_BORDER      GC9A01A_CYAN
#define COLOR_DAY_TEXT_MAIN   GC9A01A_WHITE
#define COLOR_DAY_TEXT_TEMP   GC9A01A_ORANGE
#define COLOR_DAY_TEXT_UMID   GC9A01A_CYAN
#define COLOR_DAY_LABELS      GC9A01A_LIGHTGREY

// --- Colori NOTTE ---
#define COLOR_NIGHT_BORDER       0x8000
#define COLOR_NIGHT_TEXT_MAIN    0xF800
#define COLOR_NIGHT_TEXT_SENSOR  0xBC00
#define COLOR_NIGHT_LABELS       0x5000


uint16_t activeColor_Border;
uint16_t activeColor_TextMain;
uint16_t activeColor_TextTemp;
uint16_t activeColor_TextUmid;
uint16_t activeColor_Labels;

// --- Timers / Stato pulsante ---
unsigned long tempoPrecedenteDHT      = 0;
unsigned long tempoOrologio  = 0;
const long    intervalloOrologio = 500;
const long    intervalloDHT           = 5000;
float         ultimaTemp              = 0.0;
float         ultimaUmid              = 0.0;
int           statoPrecedentePulsante = HIGH;

// ============================================================
// FORWARD DECLARATIONS
// ============================================================
void impostaColoriInterfaccia(bool notte);
void disegnaInterfacciaBase();
void aggiornaOrologioUI();
void aggiornaSensoriUI();
void leggiRadar();
void gestisciDisplay(unsigned long adesso);
void accendiNotteLight();

void avviaComandoIR(ComandoIR cmd);
void eseguiStepIR();





void avviaComandoIR(ComandoIR cmd) {
  if (irInCorso) return;
  irSequenzaLen  = 0;
  irStepCorrente = 0;
  irInCorso      = true;
  irComandoAttivo = cmd;
  irUltimoStep   = millis();

  auto push = [&](uint32_t c) { irSequenza[irSequenzaLen++] = {c}; };

  switch (cmd) {
    case IR_ROSSO:
      if (!statoLuci) { push(LUCE_ON); statoLuci = true; }
      push(LUCE_ROSSA);
      push(LUCE_DIM_MENO); push(LUCE_DIM_MENO); push(LUCE_DIM_MENO);
      break;
    case IR_OFF:
      if (statoLuci) { push(LUCE_OFF); statoLuci = false; }
      else { irInCorso = false; irComandoAttivo = IR_NESSUNO; }
      break;
    case IR_LAVORO:
      if (!statoLuci) { push(LUCE_ON); statoLuci = true; }
      push(LUCE_BIANCA);
      for (int i=0;i<5;i++) push(LUCE_DIM_PIU);
      break;
    case IR_CYBERPUNK:
      if (!statoLuci) { push(LUCE_ON); statoLuci = true; }
      push(LUCE_VIOLA);
      break;
    case IR_MATRIX:
      if (!statoLuci) { push(LUCE_ON); statoLuci = true; }
      push(LUCE_VERDE);
      break;
    case IR_LUM_MAX:
      if (!statoLuci) { push(LUCE_ON); statoLuci = true; }
      for (int i=0;i<10;i++) push(LUCE_DIM_MENO);
      for (int i=0;i<10;i++) push(LUCE_DIM_PIU);
      break;
    case IR_LUM_MEDIA:
      if (!statoLuci) { push(LUCE_ON); statoLuci = true; }
      for (int i=0;i<10;i++) push(LUCE_DIM_MENO);
      for (int i=0;i<5;i++)  push(LUCE_DIM_PIU);
      break;
    case IR_LUM_BASSA:
      if (!statoLuci) { push(LUCE_ON); statoLuci = true; }
      for (int i=0;i<10;i++) push(LUCE_DIM_MENO);
      break;
    case IR_NOTTE_LIGHT:
      if (!statoLuci) { push(LUCE_ON); statoLuci = true; }
      push(LUCE_BIANCA);
      for (int i=0;i<10;i++) push(LUCE_DIM_MENO);
      break;
    default:
      irInCorso = false;
      break;
  }
}

void eseguiStepIR() {
  if (!irInCorso) return;
  if (millis() - irUltimoStep < IR_STEP_MS) return;
  if (irStepCorrente >= irSequenzaLen) {
    irInCorso       = false;
    irComandoAttivo = IR_NESSUNO;
    Serial.println("[IR] Sequenza completata.");
    return;
  }
  irsend.sendNEC(irSequenza[irStepCorrente].codice, 32);
  Serial.printf("[IR] Step %d/%d → 0x%08X\n",
                irStepCorrente + 1, irSequenzaLen,
                irSequenza[irStepCorrente].codice);
  irStepCorrente++;
  irUltimoStep = millis();
}


// ============================================================
// SETUP
// ============================================================
void setup() {
  Serial.begin(115200);

  // Serial2 per il radar LD2410C (256000 baud come da datasheet)
  Serial2.begin(256000, SERIAL_8N1, RADAR_RX, RADAR_TX);

  pinMode(LDR_PIN,       INPUT);
  pinMode(BUTTON_PIN,    INPUT_PULLUP);
  pinMode(BUZZER_PIN,    OUTPUT);
  pinMode(RADAR_OUT_PIN, INPUT);

  irsend.begin();
  Serial.println("[IR] Modulo IR Inizializzato.");
  Serial.println("[RADAR] LD2410C Serial2 avviato a 256000 baud.");

  impostaColoriInterfaccia(false);
  dht.begin();
  tft.begin();
  tft.setRotation(0);
  tft.fillScreen(GC9A01A_BLACK);

  tft.setTextColor(GC9A01A_CYAN);
  tft.setTextSize(2);
  tft.setCursor(50, 110);
  tft.print("Wi-Fi...");

  Serial.print("Connessione a "); Serial.println(ssid);
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }

  Serial.println("\nWi-Fi connesso!");
  Serial.print("IP: "); Serial.println(WiFi.localIP());

  configTime(gmtOffset_sec, daylightOffset_sec, ntpServer);
  tft.fillScreen(GC9A01A_BLACK);
  disegnaInterfacciaBase();

  // ============================================================
  // ENDPOINT IR
  // ============================================================

  server.on("/rosso",    []() { avviaComandoIR(IR_ROSSO);    server.send(200, "text/plain", "Protocollo Alba Rossa avviato"); });
  server.on("/off",      []() { avviaComandoIR(IR_OFF);      server.send(200, "text/plain", "Luci in spegnimento"); });
  server.on("/lavoro",   []() { avviaComandoIR(IR_LAVORO);   server.send(200, "text/plain", "Modalita' lavoro avviata"); });
  server.on("/cyberpunk",[]() { avviaComandoIR(IR_CYBERPUNK);server.send(200, "text/plain", "Atmosfera Cyberpunk avviata"); });
  server.on("/matrix",   []() { avviaComandoIR(IR_MATRIX);   server.send(200, "text/plain", "Modalita' Matrix avviata"); });
  server.on("/lum_max",  []() { avviaComandoIR(IR_LUM_MAX);  server.send(200, "text/plain", "Luminosita' massima in corso"); });
  server.on("/lum_media",[]() { avviaComandoIR(IR_LUM_MEDIA);server.send(200, "text/plain", "Luminosita' media in corso"); });
  server.on("/lum_bassa",[]() { avviaComandoIR(IR_LUM_BASSA);server.send(200, "text/plain", "Luminosita' bassa in corso"); });

  // Formato: /sveglia_set?ora=8&minuto=30&stop_ora=9&stop_minuto=15
  server.on("/sveglia_set", []() {
    if (server.hasArg("ora"))          svegliaOra          = server.arg("ora").toInt();
    if (server.hasArg("minuto"))       svegliaMinuto       = server.arg("minuto").toInt();
    if (server.hasArg("stop_ora"))     spegnimentoOra      = server.arg("stop_ora").toInt();
    if (server.hasArg("stop_minuto"))  spegnimentoMinuto   = server.arg("stop_minuto").toInt();
    if (server.hasArg("abilitata"))    svegliaAbilitata    = server.arg("abilitata") == "1";
    svegliaEseguita     = false;
    spegnimentoEseguito = false;
    char risposta[128];
    snprintf(risposta, sizeof(risposta),
      "Sveglia impostata: %02d:%02d | Stop: %02d:%02d | Abilitata: %s",
      svegliaOra, svegliaMinuto, spegnimentoOra, spegnimentoMinuto,
      svegliaAbilitata ? "SI" : "NO");
    Serial.printf("[SVEGLIA] %s\n", risposta);
    server.send(200, "text/plain", risposta);
  });


  server.begin();
  Serial.println("[SERVER] HTTP avviato. Sistema pronto.");
}

// ============================================================
// LOOP
// ============================================================
void loop() {
  server.handleClient();
  eseguiStepIR();

  // Legge il radar (OUT pin + parsing UART)
  leggiRadar();

  int valoreLuce    = analogRead(LDR_PIN);
  int statoPulsante = digitalRead(BUTTON_PIN);
  unsigned long adesso = millis();

  // -------------------------------------------------------
  // FEATURE 3: Risparmio Energetico Display
  // Se nessuno e' in stanza il display entra in sleep hardware.
  // Appena si rileva presenza si risveglia istantaneamente.
  // -------------------------------------------------------
  gestisciDisplay(adesso);

  // -------------------------------------------------------
  // LDR Night Mode (solo se display attivo)
  // -------------------------------------------------------
  if (displayAcceso) {
    if (valoreLuce < SOGLIA_BUIO_ENTRA && !isInNightMode) {
      Serial.println("[LDR] BUIO: modalita' NOTTE");
      isInNightMode = true;
      impostaColoriInterfaccia(true);
      tft.fillScreen(GC9A01A_BLACK);
      disegnaInterfacciaBase();
    } else if (valoreLuce > SOGLIA_BUIO_ESCI && isInNightMode) {
      Serial.println("[LDR] LUCE: modalita' GIORNO");
      isInNightMode = false;
      impostaColoriInterfaccia(false);
      tft.fillScreen(GC9A01A_BLACK);
      disegnaInterfacciaBase();
    }
  }

  // -------------------------------------------------------
  // FEATURE 2: Night-Light Dinamica
  // Condizione: e' notte, luci spente, radar passa da
  // "stazionario" (sdraiato) a "movimento" (si siede/alza).
  // Accende bianco al minimo per non accecare.
  // -------------------------------------------------------
  if (isInNightMode && !statoLuci &&
      statoPrecedenteRadar == 2 && statoRadar == 1) {
    Serial.println("[RADAR] Movimento notturno: accendo night-light");
    avviaComandoIR(IR_NOTTE_LIGHT);
  }

  if (statoPulsante == LOW && statoPrecedentePulsante == HIGH) {
    if (statoLuci) avviaComandoIR(IR_OFF);
    else           avviaComandoIR(IR_LAVORO);
    statoPrecedentePulsante = LOW;
  }
  if (statoPulsante == HIGH && statoPrecedentePulsante == LOW) {
    statoPrecedentePulsante = HIGH;
  }


  // Aggiornamenti UI (solo se non allarme e display non spento)
  if (displayAcceso) {
    if (adesso - tempoPrecedenteDHT >= intervalloDHT) {
      tempoPrecedenteDHT = adesso;
      ultimaTemp = dht.readTemperature();
      ultimaUmid = dht.readHumidity();
      aggiornaSensoriUI();
    }
    if (adesso - tempoOrologio >= intervalloOrologio) {
      tempoOrologio = adesso;
      aggiornaOrologioUI();
    }
  }


  // --- SVEGLIA 9:00 / SPEGNIMENTO 9:45 ---
  struct tm timeinfo;
  if (getLocalTime(&timeinfo)) {
    int ora     = timeinfo.tm_hour;
    int minuto  = timeinfo.tm_min;

    // Reset flag a mezzanotte
    if (ora == 0 && minuto == 0) {
      svegliaEseguita    = false;
      spegnimentoEseguito = false;
    }

    // Attiva alba rossa alle 9:00
    if (svegliaAbilitata && ora == svegliaOra && minuto == svegliaMinuto && !svegliaEseguita) {
      svegliaEseguita = true;
      avviaComandoIR(IR_ROSSO);
      Serial.println("[SVEGLIA] Alba rossa attivata");
    }

    // Spegni alle 9:45
    if (svegliaAbilitata && ora == spegnimentoOra && minuto == spegnimentoMinuto && !spegnimentoEseguito) {
      spegnimentoEseguito = true;
      noTone(BUZZER_PIN);
      avviaComandoIR(IR_OFF);
      tft.fillScreen(GC9A01A_BLACK);
      disegnaInterfacciaBase();
      Serial.println("[SVEGLIA] Spegnimento automatico");
    }
  }

}

// ============================================================
// FUNZIONI RADAR
// ============================================================

/*
 * leggiRadar()
 * Usa due canali in parallelo:
 *   1) OUT pin (digitale) -> presenzaRilevata  — lettura istantanea
 *   2) UART Serial2       -> statoRadar        — parsing frame LD2410C
 *
 * Struttura frame LD2410C (23 byte totali):
 *   [0-3]   Header:  F4 F3 F2 F1
 *   [4-5]   Length:  0D 00
 *   [6]     Type:    02
 *   [7]     Head:    AA
 *   [8]     Stato:   00=nessuno 01=movimento 02=stazionario 03=entrambi
 *   [9-10]  Dist mov (LE)
 *   [11]    Energia mov
 *   [12-13] Dist stat (LE)
 *   [14]    Energia stat
 *   [15-16] Dist rilevamento (LE)
 *   [17-18] Tail: 55 00
 *   [19-22] End:  F8 F7 F6 F5
 */
void leggiRadar() {
  // OUT pin -> presenza immediata (feature 1 e 3)
  presenzaRilevata = (digitalRead(RADAR_OUT_PIN) == HIGH);

  // UART -> stato dettagliato (feature 2)
  static uint8_t buf[23];
  static uint8_t idx = 0;

  while (Serial2.available()) {
    uint8_t b = (uint8_t)Serial2.read();

    // Sincronizzazione: scartiamo tutto finche' non troviamo 0xF4
    if (idx == 0 && b != 0xF4) continue;

    buf[idx++] = b;

    if (idx < 23) continue; // Frame non ancora completo

    // Verifica header + footer completi
    if (buf[0]  == 0xF4 && buf[1]  == 0xF3 &&
        buf[2]  == 0xF2 && buf[3]  == 0xF1 &&
        buf[17] == 0x55 && buf[18] == 0x00 &&
        buf[19] == 0xF8 && buf[20] == 0xF7 &&
        buf[21] == 0xF6 && buf[22] == 0xF5) {

      statoPrecedenteRadar = statoRadar;
      statoRadar           = buf[8];

      Serial.printf("[RADAR] Stato UART: %d | OUT: %s\n",
                    statoRadar, presenzaRilevata ? "SI" : "NO");
    }
    idx = 0; // Reset per il prossimo frame
  }
}

// ============================================================
// FEATURE 3 — Gestione 3 stati display
// ============================================================
/*
 * STATO 0 — SPENTO (nessuna presenza)
 *   Display in sleep hardware: 0x28 DISPOFF + 0x10 SLPIN
 *
 * STATO 1 — ALWAYS-ON (presenza stazionaria)
 *   Display acceso ma con palette grigia tenue.
 *   Mostra orologio e sensori in bassa intensità.
 *
 * STATO 2 — PIENO (movimento rilevato)
 *   Display completamente attivo con colori normali (giorno/notte).
 *
 * Comandi GC9A01A:
 *   0x28 DISPOFF, 0x10 SLPIN, 0x11 SLPOUT (+120ms), 0x29 DISPON
 */
void gestisciDisplay(unsigned long adesso) {
  if (displayInWake) {
    if (adesso - displayWakeStart < DISPLAY_WAKE_MS) return;
    tft.sendCommand(0x29); // Display On
    displayAcceso = true;
    displayInWake = false;
    statoDisplay  = 255;   // forza ridisegno immediato
    // fall-through
  }

  uint8_t target;
  if (!presenzaRilevata)                                    target = 0;
  else if (isInNightMode && statoRadar == 2)                target = 0;
  else                                                      target = 2;

  if (target == statoDisplay) return;

  uint8_t prev = statoDisplay;
  statoDisplay  = target;

  if (target == 0) {
    tft.sendCommand(0x28);
    tft.sendCommand(0x10);
    displayAcceso = false;
    Serial.println("[DISPLAY] → SPENTO");
    return;
  }

  if (prev == 0) {
    tft.sendCommand(0x11); // Sleep Out (richiede 120ms)
    displayWakeStart = adesso;
    displayInWake    = true;
    Serial.println("[DISPLAY] → Wake in corso...");
    return;
  }

  if (target == 2) {
    impostaColoriInterfaccia(isInNightMode);
    tft.fillScreen(GC9A01A_BLACK);
    disegnaInterfacciaBase();
    Serial.println("[DISPLAY] → PIENO");
  }
}

// ============================================================
// FEATURE 2 — Night-Light (bianco al minimo)
// ============================================================
void accendiNotteLight() {
  irsend.sendNEC(LUCE_ON,     32); delay(200);
  statoLuci = true;
  irsend.sendNEC(LUCE_BIANCA, 32); delay(200);
  // Porta al minimo assoluto (10 step DIM-)
  for(int i=0; i<10; i++) { irsend.sendNEC(LUCE_DIM_MENO, 32); delay(150); }
}

// ============================================================
// FUNZIONI GRAFICHE
// ============================================================

void impostaColoriInterfaccia(bool notte) {
  if (notte) {
    activeColor_Border   = COLOR_NIGHT_BORDER;
    activeColor_TextMain = COLOR_NIGHT_TEXT_MAIN;
    activeColor_TextTemp = COLOR_NIGHT_TEXT_SENSOR;
    activeColor_TextUmid = COLOR_NIGHT_TEXT_SENSOR;
    activeColor_Labels   = COLOR_NIGHT_LABELS;
  } else {
    activeColor_Border   = COLOR_DAY_BORDER;
    activeColor_TextMain = COLOR_DAY_TEXT_MAIN;
    activeColor_TextTemp = COLOR_DAY_TEXT_TEMP;
    activeColor_TextUmid = COLOR_DAY_TEXT_UMID;
    activeColor_Labels   = COLOR_DAY_LABELS;
  }
}

void disegnaInterfacciaBase() {
  tft.drawCircle(120, 120, 118, activeColor_Border);
  tft.drawCircle(120, 120, 117, activeColor_Border);
  tft.drawLine(30, 120, 210, 120, GC9A01A_DARKGREY);
  tft.setTextSize(1);
  tft.setTextColor(activeColor_Labels);
  tft.setCursor(55, 135);  tft.print("TEMP");
  tft.setCursor(155, 135); tft.print("UMID");
}

void aggiornaOrologioUI() {
  struct tm timeinfo;
  if (!getLocalTime(&timeinfo)) return;
  char orario[9];
  sprintf(orario, "%02d:%02d:%02d", timeinfo.tm_hour, timeinfo.tm_min, timeinfo.tm_sec);
  tft.setTextSize(4);
  tft.setTextColor(activeColor_TextMain, GC9A01A_BLACK);
  tft.setCursor(25, 60);
  tft.print(orario);
}

void aggiornaSensoriUI() {
  if (!isnan(ultimaTemp) && !isnan(ultimaUmid)) {
    tft.setTextSize(2);
    tft.setTextColor(activeColor_TextTemp, GC9A01A_BLACK);
    tft.setCursor(45, 155);
    tft.print(ultimaTemp, 1); tft.print("C");
    tft.setTextColor(activeColor_TextUmid, GC9A01A_BLACK);
    tft.setCursor(145, 155);
    tft.print(ultimaUmid, 1); tft.print("%");
  }
}
