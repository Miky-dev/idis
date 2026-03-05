import time
import threading
from logica_chat import elabora_risposta, _carica_posizione, cronologia_chat

# Prepara ambiente base
print("⏳ Preparazione ambiente...")
t = threading.Thread(target=_carica_posizione, daemon=True)
t.start()
t.join(timeout=2.0)

# Finto callback per misurare TTFT e Tool Call
class DummyUI:
    def __init__(self):
        self.t_start = time.perf_counter()
        self.t_first_token = None
        self.t_tool_call = None
        
    def aggiungi_messaggio(self, mit, txt, col=None):
        if "Sistema" in mit or "IDIS" in mit:
            pass

    def aggiorna_testo(self, txt):
        if self.t_first_token is None and txt.strip():
            self.t_first_token = time.perf_counter()
            print(f"⏱️ Primo token ricevuto a: {(self.t_first_token - self.t_start):.2f}s")
            
        print(txt, end="", flush=True)

    def reset_label(self):
        pass

    def set_stato(self, stato):
        if stato == "idle" and self.t_first_token:
            print("\n✅ Fine risposta")

callbacks = {
    "aggiungi_messaggio": DummyUI().aggiungi_messaggio,
    "aggiorna_testo": DummyUI().aggiorna_testo,
    "reset_label": DummyUI().reset_label,
    "set_stato": DummyUI().set_stato
}

print("\n" + "="*50)
print("TEST 1: Domanda semplice (Senza Tool - CoT completo)")
print("="*50)
ui1 = DummyUI()
callbacks["aggiorna_testo"] = ui1.aggiorna_testo
callbacks["set_stato"] = ui1.set_stato
cronologia_chat.clear()
elabora_risposta("Ciao, chi sei?", callbacks)
print(f"⏱️ Tempo totale: {(time.perf_counter() - ui1.t_start):.2f}s")

print("\n" + "="*50)
print("TEST 2: Richiesta Tool (Accendi il LED - CoT disabilitato)")
print("="*50)
ui2 = DummyUI()
callbacks["aggiorna_testo"] = ui2.aggiorna_testo
callbacks["set_stato"] = ui2.set_stato
cronologia_chat.clear()
elabora_risposta("Accendi la luce della scrivania", callbacks)
print(f"⏱️ Tempo totale elaborazione: {(time.perf_counter() - ui2.t_start):.2f}s")

print("\n" + "="*50)
print("TEST 3: Richiesta Tool 2 (Che tempo fa a Milano? - CoT disabilitato)")
print("="*50)
ui3 = DummyUI()
callbacks["aggiorna_testo"] = ui3.aggiorna_testo
callbacks["set_stato"] = ui3.set_stato
cronologia_chat.clear()
elabora_risposta("Che tempo fa a Milano?", callbacks)
print(f"⏱️ Tempo totale elaborazione: {(time.perf_counter() - ui3.t_start):.2f}s")
