import customtkinter as ctk
import threading
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_ollama import ChatOllama
import datetime
import time
import locale
import requests
import os
from dotenv import load_dotenv

load_dotenv()

# ✅ P2: locale impostato UNA VOLTA all'avvio (non è thread-safe)
try:
    locale.setlocale(locale.LC_TIME, 'it_IT.UTF-8')
except:
    pass

from actions.tools_os import apri_applicazione
from actions.tools_web import cerca_su_internet, apri_sito_web, digita_nel_browser
from actions.weather_report import mostra_meteo
from actions.tools_spotify import riproduci_canzone, riproduci_playlist, controlla_spotify, cosa_sta_suonando
from memoria_vettoriale import salva_ricordo, estrai_ricordi_pertinenti
from tools_whatsapp import prepara_messaggio_whatsapp, conferma_invio_whatsapp, annulla_messaggio_whatsapp
from tools_files import crea_cartella, prepara_spostamento_file, conferma_spostamento_file, rinomina_elemento
from tools_calendar import leggi_calendario, ottieni_eventi_precaricati, aggiungi_evento_calendario, elimina_evento_calendario
from tools_routine import imposta_sveglia, ottieni_sveglie_attive
from tools_arduino import controlla_led, ottieni_stato_led, imposta_animazione_pensiero, get_stato_led
from tools_memory import leggi_memoria, ricorda_informazione
from langchain_google_genai import ChatGoogleGenerativeAI

# --- CONFIGURAZIONE LLM ---
llm_provider = os.getenv("LLM_PROVIDER", "ollama").lower()
model_local = os.getenv("MODEL_LOCAL", "qwen3:8b")
model_remote = os.getenv("MODEL_REMOTE", "gemini-2.0-flash-lite")

if llm_provider == "ollama":
    print(f"⚡ Avvio JARVIS con modello LOCALE: {model_local}")
    llm = ChatOllama(model=model_local)
else:
    print(f"🚀 Avvio JARVIS con modello REMOTO (Google): {model_remote}")
    llm = ChatGoogleGenerativeAI(model=model_remote)

cronologia_chat = []
eventi_precaricati = "Non sono ancora stati caricati gli eventi di oggi."

# ✅ P1: Pre-bind dei tool di default una sola volta all'avvio
TOOL_DEFAULT = [cerca_su_internet, ricorda_informazione]
llm_default = llm.bind_tools(TOOL_DEFAULT)

# ✅ FIX: posizione caricata UNA VOLTA all'avvio, non ad ogni messaggio
posizione_cache = "Sconosciuta"
def _carica_posizione():
    global posizione_cache
    try:
        risposta_ip = requests.get("http://ip-api.com/json/", timeout=3).json()
        posizione_cache = f"{risposta_ip.get('city')}, {risposta_ip.get('country')}"
        print(f"📍 Posizione rilevata: {posizione_cache}")
    except:
        posizione_cache = "Sconosciuta (Offline)"
threading.Thread(target=_carica_posizione, daemon=True).start()

# ✅ P4: Warmup del modello — forza il caricamento in VRAM prima del primo messaggio
def _warmup_ollama():
    try:
        requests.post("http://localhost:11434/api/generate", json={
            "model": model_local,
            "prompt": "ciao",
            "stream": False,
            "options": {"num_predict": 1}
        }, timeout=30)
        print("🔥 Warmup completato — modello in VRAM")
    except Exception as e:
        print(f"⚠️ Warmup fallito: {e}")

if llm_provider == "ollama":
    threading.Thread(target=_warmup_ollama, daemon=True).start()

# --- UI ---
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

app = ctk.CTk()
app.geometry("1100x700")
app.title("🧠 IDIS")

main_frame = ctk.CTkFrame(app, fg_color="transparent")
main_frame.pack(fill="both", expand=True, padx=10, pady=10)

left_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
left_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))

chat_frame = ctk.CTkScrollableFrame(left_frame)
chat_frame.pack(pady=10, padx=10, fill="both", expand=True)

input_frame = ctk.CTkFrame(left_frame)
input_frame.pack(pady=10, padx=10, fill="x", side="bottom")

entry_testo = ctk.CTkEntry(input_frame, placeholder_text="Scrivi a IDIS...")
entry_testo.pack(side="left", padx=10, pady=10, expand=True, fill="x")

right_frame = ctk.CTkFrame(main_frame, width=300)
right_frame.pack(side="right", fill="y", padx=10, pady=10)
right_frame.pack_propagate(False)

lbl_titolo_sveglie = ctk.CTkLabel(right_frame, text="⏰ Sveglie Attive", font=("Arial", 16, "bold"))
lbl_titolo_sveglie.pack(pady=(15, 5))

sveglie_frame = ctk.CTkScrollableFrame(right_frame, fg_color="transparent")
sveglie_frame.pack(fill="both", expand=True, padx=10, pady=10)

label_corrente = None

def aggiungi_messaggio_ui(mittente, testo, colore="white"):
    global label_corrente
    msg_box = ctk.CTkFrame(chat_frame, fg_color="transparent")
    msg_box.pack(anchor="w", pady=5, padx=5, fill="x")

    lbl_mittente = ctk.CTkLabel(msg_box, text=f"{mittente}:", text_color="gray", font=("Arial", 12, "bold"))
    lbl_mittente.pack(side="left", anchor="nw", padx=(0, 10))

    lbl_testo = ctk.CTkLabel(msg_box, text=testo, text_color=colore, justify="left", wraplength=750)
    lbl_testo.pack(side="left", anchor="nw")

    chat_frame._parent_canvas.yview_moveto(1.0)

    if mittente == "🤖 IDIS":
        label_corrente = lbl_testo

def aggiorna_testo_ui(nuovo_testo):
    global label_corrente
    if label_corrente:
        testo_attuale = label_corrente.cget("text")
        label_corrente.configure(text=testo_attuale + nuovo_testo)
        chat_frame._parent_canvas.yview_moveto(1.0)


# --- LOGICA PRINCIPALE ---
def elabora_risposta(testo_utente):
    import time
    global cronologia_chat, label_corrente

    if testo_utente.strip().lower() in ["/reset", "cancella chat", "dimentica tutto"]:
        cronologia_chat = []
        app.after(0, aggiungi_messaggio_ui, "Sistema", "Cronologia azzerata.", "yellow")
        return

    imposta_animazione_pensiero(True)

    # Contesto temporale — solo calcoli locali, niente HTTP
    ora_corrente     = datetime.datetime.now().strftime("%H:%M:%S")
    data_odierna     = datetime.datetime.now().strftime("%d/%m/%Y")
    giorno_settimana = datetime.datetime.now().strftime("%A")

    # Memoria vettoriale (veloce, solo matematica locale)
    # ✅ Ottimizzazione: salta l'embedding se il messaggio è molto corto (es. "ciao", "ok")
    if len(testo_utente.split()) > 8:
        ricordi_ripescati = estrai_ricordi_pertinenti(testo_utente, max_risultati=2)
    else:
        ricordi_ripescati = []
    testo_ricordi = "\n".join([f"- {r}" for r in ricordi_ripescati]) if ricordi_ripescati else "Nessuna informazione salvata."

    stato_luce = get_stato_led()
    memoria_strutturata = leggi_memoria()
    testo_memoria_json = "\n".join([f"- {k}: {v}" for k, v in memoria_strutturata.items()]) if memoria_strutturata else "Nessun dato personale salvato."

    system_prompt_dinamico = f"""Sei IDIS, un assistente IA avanzato.
Oggi è {giorno_settimana}, {data_odierna}. Ora attuale: {ora_corrente}.
Posizione: {posizione_cache}

=== STATO HARDWARE ===
- Luce/LED scrivania: {stato_luce}

=== DATI PERSONALI ===
{testo_memoria_json}

=== RICORDI PERTINENTI ===
{testo_ricordi}

=== CALENDARIO ===
{eventi_precaricati}

REGOLE:
NON USARE EMOJI O CARATTERI SPECIALI nelle risposte.
1. Usa i tool ogni volta che l'utente chiede un'azione concreta.
2. METEO: usa SEMPRE 'mostra_meteo' per previsioni.
3. MEMORIA: usa 'ricorda_informazione' se l'utente ti chiede di ricordare qualcosa.
4. Sii naturale e conciso.
"""

    messaggi_lc = [SystemMessage(content=system_prompt_dinamico)]
    for msg in cronologia_chat[-6:]:
        messaggi_lc.append(msg)

    messaggio_utente_obj = HumanMessage(content=testo_utente)
    messaggi_lc.append(messaggio_utente_obj)
    cronologia_chat.append(messaggio_utente_obj)

    # --- ROUTER TOOL ---
    testo_lower = testo_utente.lower()
    tutti_i_tool = [cerca_su_internet, ricorda_informazione]

    if any(k in testo_lower for k in ["meteo", "tempo", "piove", "pioggia", "sole", "temperatura",
                                       "previsioni", "ombrello", "caldo", "freddo", "neve", "vento"]):
        tutti_i_tool.append(mostra_meteo)

    if any(k in testo_lower for k in ["whatsapp", "messaggio", "scrivi a", "manda a", "invia a",
                                   "avvisa", "di' a", "contatta"]):
        tutti_i_tool.extend([prepara_messaggio_whatsapp, conferma_invio_whatsapp, annulla_messaggio_whatsapp])

    # Aggiunta trigger per conferme/annullamenti WhatsApp e File
    if any(k in testo_lower for k in ["sì", "no", "conferma", "annulla", "ok", "procedi", "va bene"]):
        tutti_i_tool.extend([conferma_invio_whatsapp, annulla_messaggio_whatsapp, conferma_spostamento_file])

    if any(k in testo_lower for k in ["calendario", "appuntamento", "evento", "impegno", "riunione",
                                       "incontro", "quando ho", "cosa ho", "agenda", "oggi ho",
                                       "domani ho", "aggiungi al", "elimina dal", "cancella evento"]):
        tutti_i_tool.extend([leggi_calendario, aggiungi_evento_calendario, elimina_evento_calendario])

    if any(k in testo_lower for k in ["sveglia", "timer", "promemoria", "ricordami", "avvisami",
                                       "tra", "alle ", "minuti", "ore"]):
        tutti_i_tool.append(imposta_sveglia)

    if any(k in testo_lower for k in ["luce", "led", "accendi", "spegni", "illumina", "lampada",
                                       "scrivania", "luci", "luminosità", "stato luce"]):
        tutti_i_tool.extend([controlla_led, ottieni_stato_led])

    if any(k in testo_lower for k in ["spotify", "musica", "canzone", "playlist", "suona",
                                   "metti", "pausa", "volume", "skip", "avanti", "cosa sta"]):
        tutti_i_tool.extend([riproduci_canzone, riproduci_playlist, controlla_spotify, cosa_sta_suonando])

    if any(k in testo_lower for k in ["sito", "apri", "vai su", "naviga", "browser", "pagina",
                                       "youtube", "google", "netflix", "amazon", "instagram", "web"]):
        tutti_i_tool.append(apri_sito_web)

    if any(k in testo_lower for k in ["app", "programma", "avvia", "lancia", "start", "spotify",
                                       "discord", "notepad", "task manager", "armoury",
                                       "calcolatrice", "blocco note", "esplora"]):
        tutti_i_tool.append(apri_applicazione)

    if any(k in testo_lower for k in ["cartella", "file", "sposta", "rinomina", "organizza",
                                       "nuova cartella", "sposta i file"]):
        tutti_i_tool.extend([crea_cartella, prepara_spostamento_file,
                              conferma_spostamento_file, rinomina_elemento])

    if any(k in testo_lower for k in ["word", "documento", "report", "relazione", "scrivi un file",
                                       "crea un file", "salva in", "metti tutto in", "fai un report",
                                       "crea un documento", "genera un file"]):
        from tools_files import crea_file_word
        tutti_i_tool.append(crea_file_word)

    if any(k in testo_lower for k in ["digita", "cerca su", "scrivi nel browser",
                                       "cerca in google", "cerca su youtube", "metti nella barra"]):
        tutti_i_tool.append(digita_nel_browser)

    # Rimuovi duplicati
    strumenti_visti = set()
    tutti_i_tool_unici = []
    for t in tutti_i_tool:
        t_name = getattr(t, 'name', getattr(t, '__name__', str(t)))
        if t_name not in strumenti_visti:
            strumenti_visti.add(t_name)
            tutti_i_tool_unici.append(t)
    tutti_i_tool = tutti_i_tool_unici

    # ✅ P1: Se solo i tool di default, usa il pre-bindato
    if len(tutti_i_tool) == 2 and tutti_i_tool == TOOL_DEFAULT:
        llm_attivo = llm_default
    else:
        llm_attivo = llm.bind_tools(tutti_i_tool)

    # --- STREAMING ---
    try:
        # ✅ Reset label_corrente prima di ogni nuova risposta
        label_corrente = None
        app.after(0, aggiungi_messaggio_ui, "🤖 IDIS", "", "lightblue")
        testo_finale = ""

        for _ in range(3):
            messaggio_corrente = None

            for chunk in llm_attivo.stream(messaggi_lc):

                if messaggio_corrente is None:
                    messaggio_corrente = chunk
                else:
                    messaggio_corrente += chunk

                if chunk.content:
                    app.after(0, aggiorna_testo_ui, chunk.content)

            risposta = messaggio_corrente

            if hasattr(risposta, 'tool_calls') and len(risposta.tool_calls) > 0:
                messaggi_lc.append(risposta)

                for tool_call in risposta.tool_calls:
                    nome_tool = tool_call['name']
                    args_tool = tool_call['args']
                    tool_obj = next((t for t in tutti_i_tool if getattr(t, 'name', getattr(t, '__name__', str(t))) == nome_tool), None)

                    if tool_obj:
                        print(f"🛠️ Eseguo: {nome_tool} → {args_tool}")
                        risultato = tool_obj.invoke(args_tool)
                        
                        # ✅ P5: Mostra il risultato del tool direttamente e termina
                        # Questo evita la seconda chiamata all'LLM per la "conferma"
                        app.after(0, aggiorna_testo_ui, str(risultato))
                        
                        messaggi_lc.append(ToolMessage(
                            content=str(risultato),
                            tool_call_id=tool_call['id']
                        ))
                        
                        # Salviamo nella cronologia e chiudiamo tutto
                        imposta_animazione_pensiero(False)
                        cronologia_chat.append(AIMessage(content=str(risultato)))
                        return
                    else:
                        print(f"⚠️ Tool '{nome_tool}' non trovato.")

                # ✅ Nuova bolla per la risposta finale dopo i tool
                label_corrente = None
                app.after(0, aggiungi_messaggio_ui, "🤖 IDIS", "", "lightblue")

            else:
                if isinstance(risposta.content, list):
                    testo_finale = "".join([
                        part['text'] if isinstance(part, dict) and 'text' in part else str(part)
                        for part in risposta.content
                    ])
                else:
                    testo_finale = risposta.content
                break

        if not testo_finale:
            testo_finale = "Azione completata."
            app.after(0, aggiorna_testo_ui, testo_finale)

        imposta_animazione_pensiero(False)
        cronologia_chat.append(AIMessage(content=testo_finale))

        # ✅ RIMOSSO: valuta_memoria_background — causa doppia chiamata LLM
        # La memoria viene gestita dal tool ricorda_informazione nel flusso principale

    except Exception as e:
        imposta_animazione_pensiero(False)
        app.after(0, aggiungi_messaggio_ui, "Errore", f"Errore: {str(e)}", "red")


CONFERMA_WHATSAPP = {"sì", "si", "invialo", "manda", "confermo", "ok", "vai", "yes"}
ANNULLA_WHATSAPP  = {"no", "annulla", "cancella", "stop", "modificalo", "cambia"}

def invia_click(event=None):
    testo = entry_testo.get()
    if not testo.strip():
        return
    entry_testo.delete(0, 'end')

    testo_lower = testo.strip().lower()

    from tools_whatsapp import _messaggio_in_attesa, conferma_invio_whatsapp, annulla_messaggio_whatsapp

    if _messaggio_in_attesa["contatto"] is not None:
        if testo_lower in CONFERMA_WHATSAPP:
            aggiungi_messaggio_ui("👤 Tu", testo, colore="white")
            risultato = conferma_invio_whatsapp.invoke({})
            aggiungi_messaggio_ui("🤖 IDIS", risultato, colore="lightblue")
            return
        elif testo_lower in ANNULLA_WHATSAPP:
            aggiungi_messaggio_ui("👤 Tu", testo, colore="white")
            risultato = annulla_messaggio_whatsapp.invoke({})
            aggiungi_messaggio_ui("🤖 IDIS", risultato, colore="lightblue")
            return

    aggiungi_messaggio_ui("👤 Tu", testo, colore="white")
    threading.Thread(target=elabora_risposta, args=(testo,), daemon=True).start()


btn_invia = ctk.CTkButton(input_frame, text="Invia", command=invia_click)
btn_invia.pack(side="right", padx=10, pady=10)
app.bind('<Return>', invia_click)

aggiungi_messaggio_ui("🤖 IDIS", "Sistemi online.", colore="lightblue")


def aggiorna_ui_sveglie():
    for widget in sveglie_frame.winfo_children():
        widget.destroy()
    attive = ottieni_sveglie_attive()
    if not attive:
        ctk.CTkLabel(sveglie_frame, text="Nessuna sveglia attiva", text_color="gray").pack(pady=20)
    else:
        for id_sv, info in attive.items():
            box = ctk.CTkFrame(sveglie_frame)
            box.pack(fill="x", pady=5, padx=5)
            ctk.CTkLabel(box, text=info['orario'], font=("Arial", 14, "bold"), text_color="#00a8ff").pack(anchor="w", padx=10, pady=(5, 0))
            ctk.CTkLabel(box, text=info['messaggio'], wraplength=200, justify="left").pack(anchor="w", padx=10, pady=(0, 5))
    app.after(5000, aggiorna_ui_sveglie)


def carica_calendario_background():
    global eventi_precaricati
    try:
        eventi_precaricati = ottieni_eventi_precaricati()
    except Exception as e:
        eventi_precaricati = f"Errore calendario: {str(e)}"


if __name__ == "__main__":
    threading.Thread(target=carica_calendario_background, daemon=True).start()
    aggiorna_ui_sveglie()
    app.mainloop()