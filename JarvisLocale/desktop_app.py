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

# Carica variabili d'ambiente (.env)
load_dotenv()

# Importa gli strumentis
from actions.tools_os import apri_applicazione
from actions.tools_web import cerca_su_internet, apri_sito_web, digita_nel_browser
from actions.weather_report   import mostra_meteo
# Importa la nuova memoria vettoriale
from memoria_vettoriale import salva_ricordo, estrai_ricordi_pertinenti
from tools_whatsapp import invia_messaggio_whatsapp
from tools_files import crea_cartella, prepara_spostamento_file, conferma_spostamento_file, rinomina_elemento
from tools_calendar import leggi_calendario, ottieni_eventi_precaricati, aggiungi_evento_calendario, elimina_evento_calendario
from tools_routine import imposta_sveglia, ottieni_sveglie_attive
from tools_arduino import controlla_led, ottieni_stato_led, imposta_animazione_pensiero
from tools_memory import leggi_memoria, ricorda_informazione
from langchain_google_genai import ChatGoogleGenerativeAI

# --- CONFIGURAZIONE LLM ---
llm_provider = os.getenv("LLM_PROVIDER", "gemini").lower()
model_local = os.getenv("MODEL_LOCAL", "llama3.1:latest")
model_remote = os.getenv("MODEL_REMOTE", "gemini-2.0-flash-lite")

if llm_provider == "ollama":
    print(f"🤖 Avvio JARVIS con modello LOCALE: {model_local}")
    llm = ChatOllama(model=model_local)
else:
    print(f"🚀 Avvio JARVIS con modello REMOTO (Google): {model_remote}")
    llm = ChatGoogleGenerativeAI(model=model_remote)

# Llama 3.1 locale per i compiti in background e routing veloce
llm_locale = ChatOllama(model=model_local)

cronologia_chat = [] 
eventi_precaricati = "Non sono ancora stati caricati gli eventi di oggi."

# --- CONFIGURAZIONE FINESTRA WINDOWS ---
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

app = ctk.CTk()
app.geometry("1100x700")
app.title("🧠 IDIS")

# --- ELEMENTI DELLA UI ---
# Frame principale per dividere in due colonne
main_frame = ctk.CTkFrame(app, fg_color="transparent")
main_frame.pack(fill="both", expand=True, padx=10, pady=10)

# Colonna Sinistra (Chat)
left_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
left_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))

# Area messaggi scorrevole
chat_frame = ctk.CTkScrollableFrame(left_frame)
chat_frame.pack(pady=10, padx=10, fill="both", expand=True)

# Area di input
input_frame = ctk.CTkFrame(left_frame)
input_frame.pack(pady=10, padx=10, fill="x", side="bottom")

entry_testo = ctk.CTkEntry(input_frame, placeholder_text="Scrivi a Jarvis...")
entry_testo.pack(side="left", padx=10, pady=10, expand=True, fill="x")

# Colonna Destra (Sidebar Sveglie)
right_frame = ctk.CTkFrame(main_frame, width=300)
right_frame.pack(side="right", fill="y", padx=10, pady=10)
right_frame.pack_propagate(False) # Impedisce che si rimpicciolisca

lbl_titolo_sveglie = ctk.CTkLabel(right_frame, text="⏰ Sveglie Attive", font=("Arial", 16, "bold"))
lbl_titolo_sveglie.pack(pady=(15, 5))

sveglie_frame = ctk.CTkScrollableFrame(right_frame, fg_color="transparent")
sveglie_frame.pack(fill="both", expand=True, padx=10, pady=10)

# --- FUNZIONI UI ---
def aggiungi_messaggio_ui(mittente, testo, colore="white"):
    """Crea una riga di chat nel frame scorrevole."""
    msg_box = ctk.CTkFrame(chat_frame, fg_color="transparent")
    msg_box.pack(anchor="w", pady=5, padx=5, fill="x")
    
    lbl_mittente = ctk.CTkLabel(msg_box, text=f"{mittente}:", text_color="gray", font=("Arial", 12, "bold"))
    lbl_mittente.pack(side="left", anchor="nw", padx=(0, 10))
    
    lbl_testo = ctk.CTkLabel(msg_box, text=testo, text_color=colore, justify="left", wraplength=750)
    lbl_testo.pack(side="left", anchor="nw")
    
    chat_frame._parent_canvas.yview_moveto(1.0)


# --- LOGICA DI ELABORAZIONE (in background) ---
def elabora_risposta(testo_utente):
    global cronologia_chat
    
    # Comando di reset rapido
    if testo_utente.strip().lower() in ["/reset", "cancella chat", "dimentica tutto"]:
        cronologia_chat = []
        app.after(0, aggiungi_messaggio_ui, "Sistema", "Cronologia della conversazione azzerata. Jarvis è pronto.", "yellow")
        return

    app.after(0, aggiungi_messaggio_ui, "Sistema", "Sto pensando...", "yellow")
    imposta_animazione_pensiero(True)

    # 1. Calcola il System Prompt Dinamico
    ora_corrente = datetime.datetime.now().strftime("%H:%M:%S")
    data_odierna = datetime.datetime.now().strftime("%d/%m/%Y")
    try:
        locale.setlocale(locale.LC_TIME, 'it_IT.UTF-8')
    except:
        pass
    giorno_settimana = datetime.datetime.now().strftime("%A")
    fuso_orario = time.tzname[time.localtime().tm_isdst]
    
    posizione = "Sconosciuta (Offline)"
    try:
        risposta_ip = requests.get("http://ip-api.com/json/", timeout=1).json()
        posizione = f"{risposta_ip.get('city')}, {risposta_ip.get('country')}"
    except:
        pass

    # Leggi i ricordi salvati tramite memoria vettoriale spaziale (Fase di Retrieval)
    ricordi_ripescati = estrai_ricordi_pertinenti(testo_utente, max_risultati=2)
    testo_ricordi = "\n".join([f"- {r}" for r in ricordi_ripescati]) if ricordi_ripescati else "Nessuna informazione salvata finora."

    # Costruisci il prompt di sistema con regole rigide
    ora_corrente = datetime.datetime.now().strftime("%H:%M:%S")
    
    # Recupera lo stato attuale dell'hardware per fornirlo al modello in tempo reale
    stato_luce = ottieni_stato_led()
    
    # 1.A Recupera la memoria strutturata (JSON)
    memoria_strutturata = leggi_memoria()
    testo_memoria_json = "\n".join([f"- {k}: {v}" for k, v in memoria_strutturata.items()]) if memoria_strutturata else "Nessun dato personale fisso salvato."
    
    system_prompt_dinamico = f"""Sei JARVIS, un assistente IA avanzato. 
Oggi è {giorno_settimana}, {data_odierna}. Ora attuale: {ora_corrente}.

=== STATO DISPOSITIVI HARDWARE ===
- Luce/LED sulla scrivania: {stato_luce}

=== DATI PERSONALI FISSI (Chi sei, dove vivi) ===
{testo_memoria_json}

=== RICORDI PERTINENTI (Esperienze passate) === 
{testo_ricordi}

=== I TUOI IMPEGNI IN CALENDARIO ===
{eventi_precaricati}

REGOLE DI COMPORTAMENTO:
1. SEI UN ESECUTORE EFFICIENTE. Usa gli strumenti (tools) ogni volta che l'utente chiede un'azione.
2. METEO: Per domande sul tempo o previsioni, usa SEMPRE 'mostra_meteo'.
3. MEMORIA: Se l'utente ti dà un'informazione personale da ricordare, usa lo strumento 'ricorda_informazione'.
4. STILE: Sii naturale e conciso. Rispondi sempre nella lingua dell'utente.
"""

    messaggi_lc = [SystemMessage(content=system_prompt_dinamico)]
    
    for msg in cronologia_chat[-5:]:
        messaggi_lc.append(msg)

    messaggio_utente_obj = HumanMessage(content=testo_utente)
    messaggi_lc.append(messaggio_utente_obj)
    cronologia_chat.append(messaggio_utente_obj)

    # --- ROUTER DI STRUMENTI ---
    tutti_i_tool = [
        apri_applicazione, apri_sito_web, digita_nel_browser,
        mostra_meteo, invia_messaggio_whatsapp,
        leggi_calendario, aggiungi_evento_calendario, elimina_evento_calendario,
        imposta_sveglia, controlla_led, cerca_su_internet,
        crea_cartella, prepara_spostamento_file, conferma_spostamento_file, rinomina_elemento,
        ricorda_informazione
    ]
    llm_attivo = llm.bind_tools(tutti_i_tool)

    # 3. Invoca il modello
    try:
        risposta = llm_attivo.invoke(messaggi_lc)
        testo_finale = ""
        
        # Gestione ricorsiva dei tool (massimo 3 passaggi per evitare loop)
        for _ in range(3):
            if hasattr(risposta, 'tool_calls') and len(risposta.tool_calls) > 0:
                messaggi_lc.append(risposta)
                
                for tool_call in risposta.tool_calls:
                    nome_tool = tool_call['name']
                    args_tool = tool_call['args']
                    
                    # Cerca il tool corrispondente
                    tool_obj = next((t for t in tutti_i_tool if t.name == nome_tool), None)
                    
                    if tool_obj:
                        print(f"🛠️ Eseguo tool: {nome_tool} con args: {args_tool}")
                        risultato = tool_obj.invoke(args_tool)
                        
                        messaggio_risultato = ToolMessage(
                            content=str(risultato),
                            tool_call_id=tool_call['id']
                        )
                        messaggi_lc.append(messaggio_risultato)
                    else:
                        print(f"⚠️ Tool {nome_tool} non trovato.")
                
                # Dopo aver eseguito i tool, chiedi al modello di formulare la risposta finale o chiamare altri tool
                risposta = llm_attivo.invoke(messaggi_lc)
            else:
                # Se non ci sono più tool calls, abbiamo la risposta finale
                if isinstance(risposta.content, list):
                    testo_finale = "".join([part['text'] if isinstance(part, dict) and 'text' in part else str(part) for part in risposta.content])
                else:
                    testo_finale = risposta.content
                break
        
        if not testo_finale:
            testo_finale = "Azione completata con successo."
            
        imposta_animazione_pensiero(False)
        cronologia_chat.append(AIMessage(content=testo_finale))
        app.after(0, aggiungi_messaggio_ui, "🤖 JARVIS", testo_finale, "lightblue")
        
    except Exception as e:
        imposta_animazione_pensiero(False)
        app.after(0, aggiungi_messaggio_ui, "Errore", f"Si è verificato un errore: {str(e)}", "red")


def osservatore_silenzioso(testo):
    # Usiamo Llama 3.1 per l'osservazione approfondita
    MODELLO_OSSERVATORE = "llama3.1:latest" 
    
    try:
        # Chiamata diretta a Ollama (senza LangChain per massima velocità)
        import requests
        
        system_prompt = "Sei un estrattore dati ultra-sintetico. Estrai UNO E UN SOLO FATTO oggettivo e brevissimo. Se non ci sono dati personali utili, scrivi ESATTAMENTE E SOLO 'NULLA'. Non aggiungere commenti o spiegazioni."
        user_prompt = f"Frase: '{testo}'"
        
        res = requests.post("http://localhost:11434/api/chat", json={
            "model": MODELLO_OSSERVATORE,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "options": {"temperature": 0}
        })
        
        dato_estratto = res.json()['message']['content'].strip()
        
        if "NULLA" not in dato_estratto.upper() and len(dato_estratto) > 4:
            from memoria_vettoriale import salva_ricordo
            salva_ricordo(dato_estratto)
    except Exception as e:
        print(f"Errore osservatore leggero: {e}")

def invia_click(event=None):
    testo = entry_testo.get()
    if not testo.strip(): 
        return

    entry_testo.delete(0, 'end')
    aggiungi_messaggio_ui("👤 Tu", testo, colore="white")
    
    # Avviamo il thread dell'osservatore per estrarre la memoria in background
    threading.Thread(target=osservatore_silenzioso, args=(testo,), daemon=True).start()
    
    # Avviamo l'elaborazione normale
    threading.Thread(target=elabora_risposta, args=(testo,), daemon=True).start()

btn_invia = ctk.CTkButton(input_frame, text="Invia", command=invia_click)
btn_invia.pack(side="right", padx=10, pady=10)

app.bind('<Return>', invia_click)

aggiungi_messaggio_ui("🤖 JARVIS", "Sistemi online. Come posso assisterti oggi?", colore="lightblue")

def aggiorna_ui_sveglie():
    """Aggiorna la sidebar delle sveglie in tempo reale ogni 5 secondi."""
    # Svuota i vecchi elementi
    for widget in sveglie_frame.winfo_children():
        widget.destroy()
        
    attive = ottieni_sveglie_attive()
    
    if not attive:
        lbl_vuota = ctk.CTkLabel(sveglie_frame, text="Nessuna sveglia attiva", text_color="gray")
        lbl_vuota.pack(pady=20)
    else:
        for id_sv, info in attive.items():
            box = ctk.CTkFrame(sveglie_frame)
            box.pack(fill="x", pady=5, padx=5)
            
            lbl_ora = ctk.CTkLabel(box, text=info['orario'], font=("Arial", 14, "bold"), text_color="#00a8ff")
            lbl_ora.pack(anchor="w", padx=10, pady=(5,0))
            
            lbl_msg = ctk.CTkLabel(box, text=info['messaggio'], wraplength=200, justify="left")
            lbl_msg.pack(anchor="w", padx=10, pady=(0,5))
            
    # Richiama se stessa tra 5 secondi
    app.after(5000, aggiorna_ui_sveglie)

def carica_calendario_background():
    global eventi_precaricati
    try:
        eventi_precaricati = ottieni_eventi_precaricati()
    except Exception as e:
        eventi_precaricati = f"Errore nel precaricamento calendario: {str(e)}"

if __name__ == "__main__":
    # Avvia le logiche in background
    threading.Thread(target=carica_calendario_background, daemon=True).start()
    aggiorna_ui_sveglie() # Avvia il loop UI delle sveglie
    app.mainloop()
