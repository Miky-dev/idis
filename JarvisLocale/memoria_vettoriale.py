import chromadb
import requests
import uuid
import time

# --- CONFIGURAZIONE ---
OLLAMA_EMBEDDING_URL = "http://localhost:11434/api/embeddings"
MODELLO_EMBEDDING = "nomic-embed-text" # Il traduttore in numeri

# Inizializziamo il database vettoriale locale (creerà una cartella 'chroma_db')
chroma_client = chromadb.PersistentClient(path="./chroma_db")

# Creiamo (o carichiamo se esiste già) la "scatola dei ricordi"
collezione_memoria = chroma_client.get_or_create_collection(
    name="memoria_jarvis",
    metadata={"hnsw:space": "cosine"} # Usiamo la similarità del coseno, migliore per gli embeddings testuali
)

def _calcola_vettore(testo):
    """Funzione interna: chiede a Ollama di trasformare le parole in coordinate matematiche"""
    payload = {
        "model": MODELLO_EMBEDDING,
        "prompt": testo
    }
    try:
        risposta = requests.post(OLLAMA_EMBEDDING_URL, json=payload)
        risposta.raise_for_status()
        return risposta.json()["embedding"]
    except Exception as e:
        print(f"⚠️ Errore di connessione a Ollama per l'embedding: {e}")
        return None

def salva_ricordo(testo_ricordo):
    """
    Usa questa funzione per salvare un dato importante.
    Es: salva_ricordo("L'utente ama il caffè amaro")
    """
    vettore = _calcola_vettore(f"search_document: {testo_ricordo}")
    if vettore:
        id_ricordo = str(uuid.uuid4()) # Genera un ID univoco casuale
        timestamp = str(time.time())   # Segna l'ora del ricordo
        
        collezione_memoria.add(
            ids=[id_ricordo],
            embeddings=[vettore],
            documents=[testo_ricordo],
            metadatas=[{"data_creazione": timestamp}]
        )
        print(f"💾 [MEMORIA VETTORIALE] Salvato: '{testo_ricordo}'")

def estrai_ricordi_pertinenti(domanda_utente, max_risultati=4, soglia_distanza=0.5):
    """
    Cerca i ricordi matematicamente più vicini e li filtra per rilevanza.
    """
    if collezione_memoria.count() == 0:
        return []
        
    vettore_domanda = _calcola_vettore(f"search_query: {domanda_utente}")
    if vettore_domanda:
        risultati = collezione_memoria.query(
            query_embeddings=[vettore_domanda],
            n_results=min(max_risultati, collezione_memoria.count())
        )
        
        ricordi_trovati = risultati.get('documents', [[]])[0]
        distanze_trovate = risultati.get('distances', [[]])[0]
        
        # Filtriamo i ricordi in base alla distanza (più piccola = più pertinente)
        ricordi_filtrati = []
        for i in range(len(ricordi_trovati)):
            if distanze_trovate[i] < soglia_distanza:
                ricordi_filtrati.append(ricordi_trovati[i])
        
        if ricordi_filtrati:
            print(f"🧠 [MEMORIA VETTORIALE] Ricordi pertinenti (<{soglia_distanza}): {ricordi_filtrati}")
            return ricordi_filtrati
        else:
            print(f"⚠️ [MEMORIA VETTORIALE] Nessun ricordo abbastanza pertinente trovato (min dist: {min(distanze_trovate) if distanze_trovate else 'N/A'})")
            
    return []

# --- TEST DEL MODULO ---
if __name__ == "__main__":
    print("Avvio test memoria vettoriale...\n")
    
    # 1. Salviamo due ricordi finti
    salva_ricordo("Mi chiamo Michele e sto studiando Python.")
    salva_ricordo("Il mio cibo preferito è la pizza margherita.")
    salva_ricordo("La mia password del wifi è '04804208'")
    
    print("\n--- Test di Recupero ---")
    
    # 2. Facciamo una domanda trabocchetto
    domanda = "Cosa potrei mangiare stasera?"
    print(f"Domanda: {domanda}")
    
    ricordi = estrai_ricordi_pertinenti(domanda, max_risultati=1)
    print(f"JARVIS ha recuperato in automatico: {ricordi}")
    
    # Noterai che alla domanda sul cibo, tirerà fuori il ricordo della pizza 
    # e ignorerà completamente la password del wifi o lo studio di Python!