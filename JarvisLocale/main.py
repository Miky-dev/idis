from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from tools_os import apri_applicazione
from tools_web import cerca_su_internet
from actions.tools_arduino import imposta_animazione_pensiero
import datetime
import time
import locale
import requests

# Configurazione del modello
llm = ChatOllama(model="llama3.1:latest")

print("=" * 50)
print("🤖 JARVIS Locale — Assistente con Tool Calling")
print("Digita 'esci' per terminare.")
print("=" * 50)

while True:
    input_utente = input("\n👤 Tu: ")
    if input_utente.lower() in ["esci", "quit", "exit"]:
        break
        
    if not input_utente.strip():
        continue

    # Calcolo contesto dinamico
    ora_corrente = datetime.datetime.now().strftime("%H:%M:%S")
    data_odierna = datetime.datetime.now().strftime("%d/%m/%Y")
    
    # Try to set locale to Italian to get the day of the week in Italian (if supported)
    try:
        locale.setlocale(locale.LC_TIME, 'it_IT.UTF-8')
    except:
        pass
    
    giorno_settimana = datetime.datetime.now().strftime("%A")
    fuso_orario = time.tzname[time.localtime().tm_isdst]
    
    # Tentativo leggero di prendere la posizione (Ignora se offline)
    posizione = "Sconosciuta (Offline)"
    try:
        # Timeout brevissimo per non bloccare l'esecuzione
        risposta_ip = requests.get("http://ip-api.com/json/", timeout=1).json()
        posizione = f"{risposta_ip.get('city')}, {risposta_ip.get('country')}"
    except:
        pass
        
    # Costruzione del prompt di sistema dinamico
    system_prompt_dinamico = f"""Sei IDIS, un assistente IA. 
CONTESTO ATTUALE:

Data: {giorno_settimana} {data_odierna}

Ora: {ora_corrente}

Fuso Orario: {fuso_orario}

Posizione rilevata: {posizione}

REGOLE:
Il tuo compito è conversare con l'utente in modo naturale. Usa queste informazioni di contesto se ti viene chiesto che ore sono, che giorno è o dove ti trovi.
NON usare strumenti per aprire app a meno che non sia strettamente richiesto dall'utente. Se l'utente fa domande generiche, rispondi semplicemente a parole."""

    # Messaggi strutturati con forte System Prompt
    messaggi = [
        SystemMessage(content=system_prompt_dinamico),
        HumanMessage(content=input_utente)
    ]
    
    print("⏳ Sto pensando...")
    imposta_animazione_pensiero(True)
    
    # Parole chiave che indicano l'intenzione di usare app di sistema
    trigger_app = ["apri", "avvia", "lancia", "mostrami", "aprimi", "fammi vedere", "start"]
    
    # Controlla se almeno una parola chiave è nella frase dell'utente
    richiede_app = any(parola in input_utente.lower() for parola in trigger_app)
    
    # Seleziona il modello da usare per questo turno
    if richiede_app:
        # Passiamo il modello con gli strumenti per le app
        llm_attivo = llm.bind_tools([apri_applicazione])
    else:
        # Per tutte le altre domande, forniamo il tool web per ricerche
        llm_attivo = llm.bind_tools([cerca_su_internet])
        
    # Invia tutto al modello scelto
    risposta = llm_attivo.invoke(messaggi)
    
    # Analizza se il modello ha deciso di chiamare uno strumento
    if hasattr(risposta, 'tool_calls') and risposta.tool_calls:
        print(f"🔧 Jarvis ha deciso di usare uno strumento: {risposta.tool_calls[0]['name']}")
        
        # Mappa degli strumenti disponibili
        mappa_strumenti = {
            "apri_applicazione": apri_applicazione,
            "cerca_su_internet": cerca_su_internet
        }
        
        # Eseguiamo gli strumenti richiesti
        for tool_call in risposta.tool_calls:
            nome_tool = tool_call["name"]
            argomenti = tool_call["args"]
            tool_id = tool_call["id"]
            
            # Qui eseguiamo fisicamente Python tramite la mappa
            if nome_tool in mappa_strumenti:
                strumento = mappa_strumenti[nome_tool]
                risultato_tool = strumento.invoke(argomenti)
                print(f"⚙️  Esecuzione strumento completata: {risultato_tool}")
                
                # Aggiungiamo la chiamata e il risultato allo storico
                messaggi.append(risposta) # il messaggio di intent
                messaggi.append(ToolMessage(
                    tool_call_id=tool_id,
                    name=nome_tool,
                    content=str(risultato_tool)
                ))
                
                # Chiediamo al modello di generare la risposta finale riassuntiva
                print("⏳ Elaborazione della risposta finale...")
                risposta_finale = llm_attivo.invoke(messaggi)
                messaggi.append(risposta_finale)
                imposta_animazione_pensiero(False)
                print(f"\n🤖 Jarvis: {risposta_finale.content}")
            else:
                imposta_animazione_pensiero(False)
                print(f"⚠️  Strumento '{nome_tool}' non riconosciuto.")
                
    else:
        # Nessun tool selezionato, risposta testuale standard
        messaggi.append(risposta)
        imposta_animazione_pensiero(False)
        print(f"\n🤖 Jarvis: {risposta.content}")

print("\n✅ Sessione terminata.")
