// ==========================================
// 1. VARIABILI ANIMAZIONE "SUPERCAR" (Pensiero)
// ==========================================
const int numLeds = 3;
int ledPins[numLeds] = {5, 6, 7};
bool isThinking = false;
unsigned long tempoPrecedente = 0;
const long velocitaAnimazione = 150; 
int ledCorrente = 0;
int direzione = 1; 

// ==========================================
// 2. VARIABILI LED SINGOLO (Pin 12)
// ==========================================
const int pinLed = 12;

void setup() {
  Serial.begin(9600); // Apriamo le orecchie una volta sola
  
  // Prepariamo i pin per l'animazione Supercar
  for(int i = 0; i < numLeds; i++) {
    pinMode(ledPins[i], OUTPUT);
    digitalWrite(ledPins[i], LOW);
  }

  // Prepariamo il pin per il LED singolo
  pinMode(pinLed, OUTPUT);
  digitalWrite(pinLed, LOW);

  Serial.println("Sistema JARVIS online...");
  Serial.setTimeout(50); // Evita che la lettura blocchi il loop se manca il \n
}

void loop() {
  // ---------------------------------------------------
  // FASE 1: ASCOLTIAMO LA PORTA SERIALE (Il "Cervello")
  // ---------------------------------------------------
  if (Serial.available() > 0) {
    String comando = Serial.readStringUntil('\n');
    comando.trim();

    // Procediamo solo se il comando non è vuoto
    if (comando.length() > 0) {
      // -- Controlli Animazione --
      if (comando.startsWith("THINK_ON")) {
        isThinking = true;
        Serial.println("Animazione JARVIS attivata");
      } 
      if (comando.startsWith("THINK_OFF")) {
        isThinking = false;
        // Spegniamo tutto immediatamente
        for(int i = 0; i < numLeds; i++) {
          digitalWrite(ledPins[i], LOW);
        }
        Serial.println("Animazione JARVIS disattivata");
      }
      
      // -- Controlli LED 12 --
      if (comando.startsWith("LED_ON")) {
        digitalWrite(pinLed, HIGH);     
        Serial.println("Ricevuto: accendo il Pin 12!"); 
      } 
      if (comando.startsWith("LED_OFF")) {
        digitalWrite(pinLed, LOW);      
        Serial.println("Ricevuto: spengo il Pin 12!"); 
      }
    }
  }

  // ---------------------------------------------------
  // FASE 2: MOTORE GRAFICO (Gira in background da solo)
  // ---------------------------------------------------
  if (isThinking) {
    unsigned long tempoAttuale = millis();
    
    if (tempoAttuale - tempoPrecedente >= velocitaAnimazione) {
      tempoPrecedente = tempoAttuale;

      // Spegniamo tutti i LED della supercar
      for(int i = 0; i < numLeds; i++) {
        digitalWrite(ledPins[i], LOW);
      }

      // Accendiamo solo il LED corrente
      digitalWrite(ledPins[ledCorrente], HIGH);

      // Calcoliamo il prossimo LED
      ledCorrente = ledCorrente + direzione;

      // Se arriviamo ai bordi, invertiamo la marcia
      if (ledCorrente >= numLeds - 1 || ledCorrente <= 0) {
        direzione = -direzione;
      }
    }
  }
}
