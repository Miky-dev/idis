import time
import os
from dotenv import load_dotenv
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage

# Carica le variabili d'ambiente
load_dotenv()

model_local = os.getenv("MODEL_LOCAL", "gpt-oss:20b")
THINKING_BUDGET_MAP = {"low": 1024, "medium": 8192, "high": 32768}

domanda = "C'è un cesto con 5 mele. Come fai a dividere le mele tra 5 bambini in modo che ognuno ne riceva una, ma una mela rimanga nel cesto? Prima di dare la risposta, elabora un ragionamento estremamente lungo, logico e dettagliato."

print(f"============================================================")
print(f"Test in esecuzione sul modello: {model_local}")
print(f"Domanda: {domanda}")
print(f"============================================================\n")

for budget_name, budget_tokens in THINKING_BUDGET_MAP.items():
    print(f"\n🚀 Esecuzione con thinking budget: {budget_name.upper()} ({budget_tokens} tokens)")
    print(f"Inizializzazione llm...")
    
    llm = ChatOllama(
        model=model_local,
        temperature=0.1,
        num_ctx=8192,
        extra_body={"think": True, "thinking_budget": budget_tokens},
    )
    
    start_time = time.time()
    try:
        print("\n--- INIZIO RISPOSTA ---")
        full_response = ""
        for chunk in llm.stream([HumanMessage(content=domanda)]):
            print(chunk.content, end="", flush=True)
            full_response += chunk.content
            
        end_time = time.time()
        
        print("\n--- FINE RISPOSTA ---")
        print(f"⏱️ Tempo impiegato: {end_time - start_time:.2f} secondi")
        print(f"Lunghezza della risposta: {len(full_response)} caratteri")
    except Exception as e:
        print(f"\n⚠️ Errore durante l'esecuzione con budget {budget_name}: {e}")
