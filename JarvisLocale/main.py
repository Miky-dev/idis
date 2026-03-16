import datetime
import time
import locale
import threading
import requests
import uvicorn
from fastapi import FastAPI
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage

from tools_os import apri_applicazione
from tools_web import cerca_su_internet
from actions.tools_arduino import imposta_animazione_pensiero
import esp32_bridge
from alarm.alarm_service import router as alarm_router, scheduler, start_scheduler
from esp32_bridge import router as esp32_router

# ══════════════════════════════════════════════════════════════
# FASTAPI — Hub centrale IDIS
# ══════════════════════════════════════════════════════════════
app = FastAPI(title="IDIS Hub", version="2.0")
app.include_router(alarm_router)
app.include_router(esp32_router)

def avvia_server():
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")

threading.Thread(target=avvia_server, daemon=True, name="IDISServer").start()
print("🌐 Server IDIS avviato su 0.0.0.0:8000")

# ══════════════════════════════════════════════════════════════
# SCHEDULER SVEGLIA
# ══════════════════════════════════════════════════════════════
esp32_bridge.inizializza()
start_scheduler()

# ══════════════════════════════════════════════════════════════
# CHAT LOOP
# ══════════════════════════════════════════════════════════════
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

    # Contesto dinamico
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

    system_prompt_dinamico = f"""Sei IDIS, un assistente IA.
CONTESTO ATTUALE:

Data: {giorno_settimana} {data_odierna}
Ora: {ora_corrente}
Fuso Orario: {fuso_orario}
Posizione rilevata: {posizione}

REGOLE:
Il tuo compito è conversare con l'utente in modo naturale. Usa queste informazioni di contesto se ti viene chiesto che ore sono, che giorno è o dove ti trovi.
NON usare strumenti per aprire app a meno che non sia strettamente richiesto dall'utente. Se l'utente fa domande generiche, rispondi semplicemente a parole."""

    messaggi = [
        SystemMessage(content=system_prompt_dinamico),
        HumanMessage(content=input_utente)
    ]

    print("⏳ Sto pensando...")
    imposta_animazione_pensiero(True)
    esp32_bridge.set_ai_state("thinking")

    trigger_app = ["apri", "avvia", "lancia", "mostrami", "aprimi", "fammi vedere", "start"]
    richiede_app = any(parola in input_utente.lower() for parola in trigger_app)

    llm_attivo = llm.bind_tools([apri_applicazione]) if richiede_app else llm.bind_tools([cerca_su_internet])
    risposta = llm_attivo.invoke(messaggi)

    if hasattr(risposta, 'tool_calls') and risposta.tool_calls:
        print(f"🔧 Jarvis ha deciso di usare uno strumento: {risposta.tool_calls[0]['name']}")

        mappa_strumenti = {
            "apri_applicazione": apri_applicazione,
            "cerca_su_internet": cerca_su_internet
        }

        for tool_call in risposta.tool_calls:
            nome_tool = tool_call["name"]
            argomenti  = tool_call["args"]
            tool_id    = tool_call["id"]

            if nome_tool in mappa_strumenti:
                strumento = mappa_strumenti[nome_tool]
                risultato_tool = strumento.invoke(argomenti)
                print(f"⚙️  Esecuzione strumento completata: {risultato_tool}")

                messaggi.append(risposta)
                messaggi.append(ToolMessage(
                    tool_call_id=tool_id,
                    name=nome_tool,
                    content=str(risultato_tool)
                ))

                print("⏳ Elaborazione della risposta finale...")
                risposta_finale = llm_attivo.invoke(messaggi)
                messaggi.append(risposta_finale)
                imposta_animazione_pensiero(False)
                print(f"\n🤖 Jarvis: {risposta_finale.content}")
            else:
                imposta_animazione_pensiero(False)
                print(f"⚠️  Strumento '{nome_tool}' non riconosciuto.")
    else:
        messaggi.append(risposta)
        imposta_animazione_pensiero(False)
        print(f"\n🤖 Jarvis: {risposta.content}")

    esp32_bridge.set_ai_state("idle")

# ══════════════════════════════════════════════════════════════
# CHIUSURA
# ══════════════════════════════════════════════════════════════
print("\n✅ Sessione terminata.")
esp32_bridge.set_ai_state("sleep")
time.sleep(0.5)
esp32_bridge.ferma()
