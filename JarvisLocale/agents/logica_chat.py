"""
logica_chat.py — Logica LLM, tool routing e streaming per IDIS.
Separata dalla UI per mantenere il codice modulare.
"""

import threading
import datetime
import time
import locale
import requests
import os
from dotenv import load_dotenv

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_ollama import ChatOllama
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq

from . import supervisore_routine

from .tools_routine_learning import rileva_e_registra, mostra_profilo_routine
from actions.tools_os import apri_applicazione
from actions.tools_web import cerca_su_internet, apri_sito_web, digita_nel_browser
from actions.weather_report import mostra_meteo
from actions.tools_spotify import riproduci_canzone, riproduci_playlist, controlla_spotify, cosa_sta_suonando
from memoria_vettoriale import salva_ricordo, estrai_ricordi_pertinenti
from actions.tools_whatsapp import prepara_messaggio_whatsapp, conferma_invio_whatsapp, annulla_messaggio_whatsapp, _messaggio_in_attesa
from actions.tools_files import crea_cartella, prepara_spostamento_file, conferma_spostamento_file, rinomina_elemento
from actions.tools_calendar import leggi_calendario, ottieni_eventi_precaricati, aggiungi_evento_calendario, elimina_evento_calendario
from tools_routine import imposta_sveglia, ottieni_sveglie_attive, leggi_routine, aggiungi_alla_routine, rimuovi_dalla_routine
from tools_memory import leggi_memoria, ricorda_informazione
from actions.tools_vision import esegui_visione
from actions.tools_location import ottieni_posizione, posizione_cache
from actions import tools_tts
from actions import tools_sounds
from actions.tools_handmouse import attiva_controllo_mano, disattiva_controllo_mano
from actions.tools_computer_set import esegui_azione_computer
from actions.tools_computer_controll import controllo_avanzato_computer
import esp32_bridge
from .tools_mail import leggi_mail_importanti 
from actions.tools_esp32_sveglia import invia_comando_sveglia, leggi_sensori_stanza, imposta_sveglia as imposta_sveglia_stark

load_dotenv()

try:
    locale.setlocale(locale.LC_TIME, 'it_IT.UTF-8')
except:
    pass


# ══════════════════════════════════════════════════════════════
# CONFIGURAZIONE LLM
# ══════════════════════════════════════════════════════════════

llm_provider = os.getenv("LLM_PROVIDER", "ollama").lower()
model_local = os.getenv("MODEL_LOCAL", "qwen3:8b")
model_remote = os.getenv("MODEL_REMOTE", "gemini-2.0-flash-lite")
model_groq = os.getenv("MODEL_GROQ", "llama-3.3-70b-versatile")

THINKING_BUDGET_MAP = {"low": 1024, "medium": 8192, "high": 32768}
thinking_budget_key = os.getenv("OLLAMA_THINKING_BUDGET", "low")
thinking_budget = THINKING_BUDGET_MAP.get(thinking_budget_key, 1024)

if llm_provider == "ollama":
    print(f"⚡ Avvio IDIS con modello LOCALE: {model_local} [think budget: {thinking_budget_key}]")
    llm = ChatOllama(
        model=model_local,
        temperature=0.1,
        num_ctx=4096,
        extra_body={"think": True, "thinking_budget": thinking_budget},
    )
elif llm_provider == "groq":
    print(f"⚡ Avvio IDIS con modello GROQ: {model_groq}")
    llm = ChatGroq(
        model=model_groq,
        temperature=0.1,
        api_key=os.getenv("GROQ_API_KEY"),
    )
else:
    print(f"🚀 Avvio IDIS con modello REMOTO (Google): {model_remote}")
    llm = ChatGoogleGenerativeAI(model=model_remote)

# ✅ [OPT] llm_veloce ora punta alla stessa istanza per evitare switch di contesto Ollama inutili.
llm_veloce = llm

# Pre-bind dei tool di default
#TOOL_DEFAULT = [cerca_su_internet, ricorda_informazione]
TOOL_DEFAULT = [ricorda_informazione]
llm_default = llm.bind_tools(TOOL_DEFAULT)

# ✅ Cache dei bind_tools — evita ricalcolo dello schema ad ogni messaggio
_bind_cache = {}
_bind_cache_default_key = frozenset(getattr(t, 'name', '') for t in TOOL_DEFAULT)
_bind_cache[_bind_cache_default_key] = llm_default

# ✅ [OPT] Prompt Statico per favorire il KV Caching di Ollama
# Il grosso del prompt (regole e identità) deve rimanere INVARIATO tra le sessioni.
SYSTEM_PROMPT_STATICO = """Ti chiami IDIS, un assistente IA avanzato.
REGOLE CRITICHE ASSOLUTE:
1. VELOCITÀ: Rispondi il più velocemente possibile, non perdere tempo a pensare.
2. NON USARE EMOJI O CARATTERI SPECIALI.
3. Usa i tool ogni volta che l'utente chiede un'azione concreta.
4. Se decidi di usare un tool, NON RAGIONARE nel testo, emetti SOLO la chiamata al tool.
5. RICERCA ONLINE: genera risposte estremamente brevi, coese e sintetiche (massimo 1-2 frasi), poiché l'utente approfondirà autonomamente sui siti aperti.
6. METEO: usa 'mostra_meteo'. MEMORIA: usa 'ricorda_informazione'. Sii naturale e conciso."""

def pre_cache_bindings():
    """Compila e pre-cacha FISICAMENTE i binding per le combinazioni di tool più comuni."""
    if llm_provider != "ollama": return
    
    print("⏳ Avvio pre-caching sequenziale dei tool binding...")
    comuni = [
        [mostra_meteo, cerca_su_internet, ricorda_informazione], 
        [riproduci_canzone, riproduci_playlist, controlla_spotify, cosa_sta_suonando, cerca_su_internet, ricorda_informazione], 
        [leggi_calendario, aggiungi_evento_calendario, elimina_evento_calendario, cerca_su_internet, ricorda_informazione]
    ]
    
    # Eseguiamo il pre-cache uno alla volta per non saturare la GPU/CPU all'avvio
    for tools in comuni:
        key = frozenset(getattr(t, 'name', '') for t in tools)
        if key not in _bind_cache:
            bound = llm.bind_tools(tools)
            _bind_cache[key] = bound
            # "Scalda" la cache con un mini-messaggio che include il system prompt
            try:
                bound.invoke([SystemMessage(content=SYSTEM_PROMPT_STATICO), HumanMessage(content="---")])
                time.sleep(0.5) # Piccolo respiro tra un warmup e l'altro
            except: pass
            
    print("⚡ Pre-caching dei tool completato.")

# Stato condiviso
cronologia_chat = []
eventi_precaricati = "Non sono ancora stati caricati gli eventi di oggi."
_ui_callbacks_globali = None  # impostato al primo elabora_risposta

CONFERMA_WHATSAPP = {"sì", "si", "invialo", "manda", "confermo", "ok", "vai", "yes"}
ANNULLA_WHATSAPP  = {"no", "annulla", "cancella", "stop", "modificalo", "cambia"}


# ══════════════════════════════════════════════════════════════
# INIT BACKGROUND
# ══════════════════════════════════════════════════════════════

import subprocess

def _warmup_ollama():

    """Carica il modello in VRAM con una richiesta chat minima ma reale."""
    try:
        # Usa l'istanza LangChain per essere coerente con il template di chat
        llm.invoke([SystemMessage(content=SYSTEM_PROMPT_STATICO), HumanMessage(content="Warmup")])
        print("🔥 Warmup completato — prompt prefix in VRAM")
    except Exception as e:
        print(f"⚠️ Warmup fallito: {e}")


def carica_calendario_background():
    global eventi_precaricati
    from .profilo_uscita import controlla_calendario_uscita, esegui_profilo_uscita
    if controlla_calendario_uscita(eventi_precaricati):
        threading.Thread(target=esegui_profilo_uscita, args=("",), daemon=True).start()
    try:
        eventi_precaricati = ottieni_eventi_precaricati()
    except Exception as e:
        eventi_precaricati = f"Errore calendario: {str(e)}"


def avvia_background():
    """Avvia tutti i thread di background nell'ordine corretto."""
    def _avvia_sequenza():
        # 1. Posizione (veloce, rete/GPS)
        ottieni_posizione.invoke({})
        
        # 2. Calendario (rete)
        carica_calendario_background()
        
        # 3. Warmup Ollama (pesante, GPU)
        if llm_provider == "ollama":
            _warmup_ollama()
            # 4. Pre-caching tool (pesante, GPU)
            pre_cache_bindings()
            
        # 5. Supervisore (leggero)
        supervisore_routine.inizializza({}, llm, js_callback=lambda f, *a: _ui_callbacks_globali.get("_js_callback")(f, *a) if _ui_callbacks_globali and "_js_callback" in _ui_callbacks_globali else None)
        supervisore_routine.avvia()

        from .profilo_uscita import inizializza as init_uscita
        init_uscita(
            llm         = llm,
            ui_notify   = lambda m, t: _ui_callbacks_globali["aggiungi_messaggio"](m, t, "cyan") if _ui_callbacks_globali else None,
            tts_parla   = tools_tts.parla,
            js_callback = None  # opzionale, collegalo a ui_webview se vuoi aggiornare la dashboard
        )
        
        # 6. Carica Kokoro TTS (bloccante per questo thread, ma già in background)
        tools_tts._carica_kokoro()
        tools_sounds.avvia_precaricamento()
        
        # 7. (Mail monitor è ora gestito dall'inattività nel supervisore)
        from iphone_bridge import avvia_server as avvia_iphone
        avvia_iphone()

        # 8. Avvia scheduler sveglia + server alarm
        from alarm.alarm_service import start_scheduler, router as alarm_router
        from fastapi import FastAPI
        import uvicorn
        start_scheduler()
        
        from actions.tools_esp32_sveglia import verifica_connessione_sveglia
        threading.Thread(target=verifica_connessione_sveglia, daemon=True).start()
        
        _alarm_app = FastAPI()
        _alarm_app.include_router(alarm_router)
        threading.Thread(
            target=lambda: uvicorn.run(_alarm_app, host="0.0.0.0", port=8000, log_level="warning"),
            daemon=True,
            name="AlarmServer"
        ).start()
        print("🌐 Alarm server avviato su porta 8000")

        # 9. Boot completato — porta l'ESP32 in modalità IDLE (ascolto)
        esp32_bridge.set_ai_state("idle")

        

    threading.Thread(target=_avvia_sequenza, daemon=True).start()


# ══════════════════════════════════════════════════════════════
# TOOL ROUTER
# ══════════════════════════════════════════════════════════════

def _seleziona_tool(testo_lower: str) -> list:
    """Determina quali tool rendere disponibili in base al testo utente."""
    #prima di llama3.1    tutti_i_tool = [cerca_su_internet, ricorda_informazione, ottieni_posizione]
    tutti_i_tool = [ricorda_informazione, ottieni_posizione]

    if any(k in testo_lower for k in ["cerca", "trova", "chi", "cosa significa", "quant", "perché", "notizie", "internet", "online", "significato", "spiega"]):
        tutti_i_tool.append(cerca_su_internet)
    #aggiunta dopo
    if any(k in testo_lower for k in ["meteo", "tempo", "piove", "pioggia", "sole", "temperatura",
                                       "previsioni", "ombrello", "caldo", "freddo", "neve", "vento"]):
        tutti_i_tool.append(mostra_meteo)

    if any(k in testo_lower for k in ["whatsapp", "messaggio", "scrivi a", "manda a", "invia a",
                                   "avvisa", "di' a", "contatta"]):
        tutti_i_tool.extend([prepara_messaggio_whatsapp, conferma_invio_whatsapp, annulla_messaggio_whatsapp])

    # Trigger per conferme/annullamenti WhatsApp e File
    if any(k in testo_lower for k in ["sì", "no", "conferma", "annulla", "ok", "procedi", "va bene"]):
        tutti_i_tool.extend([conferma_invio_whatsapp, annulla_messaggio_whatsapp, conferma_spostamento_file])

    if any(k in testo_lower for k in ["calendario", "appuntamento", "evento", "impegno", "riunione",
                                       "incontro", "quando ho", "cosa ho", "agenda", "oggi ho",
                                       "domani ho", "aggiungi al", "elimina dal", "cancella evento"]):
        tutti_i_tool.extend([leggi_calendario, aggiungi_evento_calendario, elimina_evento_calendario])

    if any(k in testo_lower for k in ["sveglia", "timer", "promemoria", "ricordami", "avvisami",
                                       "tra", "alle ", "minuti", "ore", "spegnila"]):
        tutti_i_tool.extend([imposta_sveglia, imposta_sveglia_stark])

    if any(k in testo_lower for k in ["routine", "abitudine", "ogni giorno", "quotidiano",
                                       "aggiungi alla routine", "rimuovi dalla routine",
                                       "le mie routine", "cosa ho di routine"]):
        tutti_i_tool.extend([leggi_routine, aggiungi_alla_routine, rimuovi_dalla_routine, mostra_profilo_routine])

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

    if any(k in testo_lower for k in ["mail", "email", "posta", "inbox", "messaggi email"]):
        tutti_i_tool.append(leggi_mail_importanti)

    if any(k in testo_lower for k in ["routine", "profilo", "cosa faccio di solito", "abitudini", "hai imparato"]):
        if mostra_profilo_routine not in tutti_i_tool:
            tutti_i_tool.append(mostra_profilo_routine)

    if any(k in testo_lower for k in ["controllo mano", "controllo remoto", "hand mouse", "handmouse",
                                       "attiva controllo remoto", "disattiva controllo remoto", "mouse con la mano",
                                       "usa la mano", "gesti mano", "attiva mano", "disattiva mano", "dammi poteri", "poteri", "togli poteri"]):
        tutti_i_tool.extend([attiva_controllo_mano, disattiva_controllo_mano]) 

    if any(k in testo_lower for k in ["volume", "luminosità", "luminosita", "chiudi app", "schermo intero", "finestra", "scrivi", "spegni schermo", "abbassa", "alza", "schermo", "minimizza", "massimizza", "ricarica", "scheda", "zoom"]):
        tutti_i_tool.append(esegui_azione_computer)

    if any(k in testo_lower for k in ["clicca", "click", "mouse", "scorciatoia", "tasto", "incolla", "copia", "screenshot", "schermata", "trova sullo", "muovi il mouse", "trascina", "seleziona tutto", "premi invio", "premi f5"]):
        tutti_i_tool.append(controllo_avanzato_computer)

    if any(k in testo_lower for k in [ "accendi", "spegni", "cyberpunk", "letto","luce letto", "luci letto", "luci comodino", "modalità", "modalita", "protocollo", "alba rossa", "stark station", "spegni tutto", "letto", "comodino", "luminosità", "luminosita", "intensità", "intensita", "luce al massimo", "luce media", "luce bassa", "viola", "bianco", "verde", "rosso"]):
        tutti_i_tool.append(invia_comando_sveglia)

    if any(k in testo_lower for k in ["stanza", "temperatura", "umidità", "umidita", "camera", "presenza", "c'è qualcuno", "c è qualcuno", "chi c'è", "stark station"]):
        if leggi_sensori_stanza not in tutti_i_tool:
            tutti_i_tool.append(leggi_sensori_stanza)

    # Rimuovi duplicati
    visti = set()
    unici = []
    for t in tutti_i_tool:
        nome = getattr(t, 'name', getattr(t, '__name__', str(t)))
        if nome not in visti:
            visti.add(nome)
            unici.append(t)
    return unici


# ══════════════════════════════════════════════════════════════
# ELABORAZIONE RISPOSTA (con callback UI)
# ══════════════════════════════════════════════════════════════

def elabora_risposta(testo_utente: str, ui_callbacks: dict):
    """
    Elabora il messaggio dell'utente: costruisce il prompt, chiama l'LLM con streaming,
    gestisce i tool calls. Comunica con la UI tramite i callback.

    ui_callbacks attesi:
        - aggiungi_messaggio(mittente, testo, colore)
        - aggiorna_testo(nuovo_testo)
        - reset_label()
        - set_stato(stato)   — "idle", "thinking", "speaking"
    """
    global cronologia_chat

    # ── Aggiornamenti background (pre-LLM, zero latenza) ─────
    from .tools_mail import aggiorna_silenzio
    aggiorna_silenzio()
    from . import supervisore_routine
    rileva_e_registra(testo_utente)
    supervisore_routine.aggiorna_ultimo_messaggio()

    # ── Intercetta conferme pendenti (learning, mail, uscita) ─
    if supervisore_routine.gestisci_conferma_learning(testo_utente.lower()): return
    if supervisore_routine.gestisci_conferma_mail(testo_utente.lower()): return
    from .profilo_uscita import gestisci_messaggio as gestisci_uscita
    gestisci_uscita(testo_utente)

    # ✅ Interrompi subito la voce se IDIS stava parlando
    tools_tts.ferma()

    global _ui_callbacks_globali
    aggiungi = ui_callbacks["aggiungi_messaggio"]
    aggiorna = ui_callbacks["aggiorna_testo"]
    reset_label = ui_callbacks["reset_label"]
    set_stato = ui_callbacks["set_stato"]
    # Passa i callbacks al supervisore la prima volta
    if _ui_callbacks_globali is None:
        _ui_callbacks_globali = ui_callbacks
        supervisore_routine.inizializza(ui_callbacks, llm, js_callback=ui_callbacks.get("_js_callback"))

    if testo_utente.strip().lower() in ["/reset", "cancella chat", "dimentica tutto"]:
        cronologia_chat = []
        aggiungi("Sistema", "Cronologia azzerata.", "yellow")
        return

    # ── Intercetta comandi visione — bypass LLM, chiamata diretta multimodale ──
    TRIGGER_VISIONE = ["cosa vedi", "cosa c'e", "cosa c è", "guarda", "descrivi cosa",
                       "dimmi cosa vedi", "analizza quello", "cosa noti", "osserva",
                       "che cosa vedi", "telecamera", "webcam", "fotocamera"]
    testo_lower_check = testo_utente.strip().lower()
    if any(k in testo_lower_check for k in TRIGGER_VISIONE):
        set_stato("thinking")
        aggiungi("🤖 IDIS", "", "lightblue")
        # Scatta e analizza in thread (bloccante ~2-5s)
        domanda_visione = testo_utente if len(testo_utente.split()) > 3 else "Descrivi in dettaglio cosa vedi nell'immagine in italiano."
        risposta_visione = esegui_visione(domanda_visione, model_local)
        aggiorna(risposta_visione)
        set_stato("speaking")
        tools_tts.parla(risposta_visione)
        cronologia_chat.append(HumanMessage(content=testo_utente))
        cronologia_chat.append(AIMessage(content=risposta_visione))
        def _torna_idle_v():
            time.sleep(3)
            set_stato("idle")
        threading.Thread(target=_torna_idle_v, daemon=True).start()
        return

    set_stato("thinking")
    tools_sounds.thinking()

    # ✅ [OPT] Contesto dinamico (ora, posizione, stato) messo in un messaggio a parte.
    # Usiamo solo HH:MM per non invalidare la cache ogni secondo.
    ora_minuto = datetime.datetime.now().strftime("%H:%M") 
    data_odierna     = datetime.datetime.now().strftime("%d/%m/%Y")
    giorno_settimana = datetime.datetime.now().strftime("%A")

    # Memoria vettoriale
    if len(testo_utente.split()) > 8:
        ricordi_ripescati = estrai_ricordi_pertinenti(testo_utente, max_risultati=2)
    else:
        ricordi_ripescati = []
    testo_ricordi = "\n".join([f"- {r}" for r in ricordi_ripescati]) if ricordi_ripescati else "Nessun ricordo pertinente."

    memoria_strutturata = leggi_memoria()
    testo_memoria_json = ", ".join([f"{k}: {v}" for k, v in memoria_strutturata.items()]) if memoria_strutturata else "Nessun dato personale."

    import actions.tools_location as tl
    import esp32_bridge
    stark_info = ""
    if esp32_bridge.stark_station_data.get("temperatura") is not None:
        stark_info = f" | Casa: {esp32_bridge.stark_station_data['temperatura']}°C, {esp32_bridge.stark_station_data['umidita']}% Umidità"
        if esp32_bridge.stark_station_data.get("presenza"):
            stark_info += " (Presenza rilevata)"

    testo_contesto = f"""Oggi: {giorno_settimana} {data_odierna}. Ora: {ora_minuto}. Posizione: {tl.posizione_cache}{stark_info}
MEM: {testo_memoria_json}.
RICORDI: {testo_ricordi}
CALENDARIO: {eventi_precaricati[:500]}""" # tronca per evitare prompt troppo lunghi

    # Costruzione messaggi: Sistema (statico) -> Storia -> Contesto (dinamico) -> Utente
    messaggi_lc = [SystemMessage(content=SYSTEM_PROMPT_STATICO)]
    
    for msg in cronologia_chat[-6:]:
        messaggi_lc.append(msg)

    # Inseriamo il contesto dinamico come SystemMessage prima della domanda utente
    # Essendo alla fine della catena di prefix, minimizza il ricalcolo.
    messaggi_lc.append(SystemMessage(content=f"CONTESTO ATTUALE:\n{testo_contesto}"))
    
    messaggio_utente_obj = HumanMessage(content=testo_utente)
    messaggi_lc.append(messaggio_utente_obj)
    cronologia_chat.append(messaggio_utente_obj)

    # Tool selection
    testo_lower = testo_utente.lower()
    tutti_i_tool = _seleziona_tool(testo_lower)

    # ✅ [OPT] bind_tools con cache. Se usiamo tool specifici, usiamo llm_veloce (no CoT lungo)
    tool_key = frozenset(getattr(t, 'name', '') for t in tutti_i_tool)
    if tool_key not in _bind_cache:
        llm_da_usare = llm if tool_key == _bind_cache_default_key else llm_veloce
        _bind_cache[tool_key] = llm_da_usare.bind_tools(tutti_i_tool)
    
    llm_attivo = _bind_cache[tool_key]

    # Streaming
    try:
        reset_label()
        aggiungi("🤖 IDIS", "", "lightblue")
        testo_finale = ""

        for _ in range(3):
            messaggio_corrente = None
            _primo_testo_ricevuto = False

            _t_stream = time.perf_counter()
            _chunk_n  = 0
            _tts_avviato = False   # avvio lazy: solo al primo chunk di testo reale

            for chunk in llm_attivo.stream(messaggi_lc):
                    if _chunk_n == 0:
                        print(f"[TIMER] primo chunk: {time.perf_counter()-_t_stream:.3f}s")
                    if _chunk_n < 5:
                        print(f"[DEBUG] chunk {_chunk_n}: {repr(chunk.content)}")
                    _chunk_n += 1

                    if chunk.content:
                        # Avvia TTS solo al primo token di testo reale — salta i chunk vuoti del thinking
                        if not _tts_avviato:
                            tools_tts.avvia_sessione_streaming()
                            _tts_avviato = True
                            set_stato("speaking")
                            tools_sounds.speaking()
                            _primo_testo_ricevuto = True
                        aggiorna(chunk.content)
                        tools_tts.alimenta_chunk(chunk.content)

                    if messaggio_corrente is None:
                        messaggio_corrente = chunk
                    else:
                        messaggio_corrente += chunk

            print(f"[TIMER] stream completo: {time.perf_counter()-_t_stream:.3f}s — {_chunk_n} chunks")
            
            risposta = messaggio_corrente

            if hasattr(risposta, 'tool_calls') and len(risposta.tool_calls) > 0:
                # Se c'è un tool call, ferma il TTS (non c'è testo da leggere)
                tools_tts.ferma()
                messaggi_lc.append(risposta)

                for tool_call in risposta.tool_calls:
                    nome_tool = tool_call['name']
                    args_tool = tool_call['args']
                    tool_obj = next((t for t in tutti_i_tool if getattr(t, 'name', getattr(t, '__name__', str(t))) == nome_tool), None)

                    if tool_obj:
                        print(f"🛠️ Eseguo: {nome_tool} → {args_tool}")
                        risultato = tool_obj.invoke(args_tool)
                        aggiorna(str(risultato))

                        messaggi_lc.append(ToolMessage(
                            content=str(risultato),
                            tool_call_id=tool_call['id']
                        ))

                        set_stato("idle")
                        cronologia_chat.append(AIMessage(content=str(risultato)))
                        return
                    else:
                        print(f"⚠️ Tool '{nome_tool}' non trovato.")

                reset_label()
                aggiungi("🤖 IDIS", "", "lightblue")

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
            aggiorna(testo_finale)

        cronologia_chat.append(AIMessage(content=testo_finale))

        # Chiude lo stream TTS (non bloccante) e torna idle subito
        tools_tts.chiudi_sessione_streaming()
        tools_sounds.idle()
        set_stato("idle")

    except Exception as e:
        tools_sounds.error()
        set_stato("idle")
        aggiungi("Errore", f"Errore: {str(e)}", "red")


def gestisci_conferma_whatsapp(testo: str) -> str | None:
    """Se c'è un messaggio WhatsApp in attesa, gestisce conferma/annullamento.
    Ritorna il risultato se gestito, None se non pertinente."""
    testo_lower = testo.strip().lower()
    if _messaggio_in_attesa["contatto"] is None:
        return None
    if testo_lower in CONFERMA_WHATSAPP:
        return conferma_invio_whatsapp.invoke({})
    elif testo_lower in ANNULLA_WHATSAPP:
        return annulla_messaggio_whatsapp.invoke({})
    return None