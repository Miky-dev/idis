try:
    import chromadb
except ImportError:
    chromadb = None
import requests
import uuid
import time

# --- CONFIGURAZIONE ---
OLLAMA_EMBEDDING_URL = "http://localhost:11434/api/embeddings"
MODELLO_EMBEDDING = "nomic-embed-text"

chroma_client = chromadb.PersistentClient(path="./chroma_db")

collezione_memoria = chroma_client.get_or_create_collection(
    name="memoria_jarvis",
    metadata={"hnsw:space": "cosine"}
)

def _calcola_vettore(testo):
    """Chiede a Ollama di calcolare l'embedding."""
    try:
        risposta = requests.post(OLLAMA_EMBEDDING_URL, json={
            "model": MODELLO_EMBEDDING,
            "prompt": testo
        }, timeout=30)
        risposta.raise_for_status()
        return risposta.json()["embedding"]
    except Exception as e:
        print(f"⚠️ Errore embedding: {e}")
        return None

def salva_ricordo(testo_ricordo):
    vettore = _calcola_vettore(f"search_document: {testo_ricordo}")
    if vettore:
        collezione_memoria.add(
            ids=[str(uuid.uuid4())],
            embeddings=[vettore],
            documents=[testo_ricordo],
            metadatas=[{"data_creazione": str(time.time())}]
        )
        print(f"💾 [MEMORIA] Salvato: '{testo_ricordo}'")

def estrai_ricordi_pertinenti(domanda_utente, max_risultati=2, soglia_distanza=0.5):
    if collezione_memoria.count() == 0:
        return []

    vettore_domanda = _calcola_vettore(f"search_query: {domanda_utente}")
    if not vettore_domanda:
        return []

    risultati = collezione_memoria.query(
        query_embeddings=[vettore_domanda],
        n_results=min(max_risultati, collezione_memoria.count())
    )

    ricordi_trovati = risultati.get('documents', [[]])[0]
    distanze_trovate = risultati.get('distances', [[]])[0]

    ricordi_filtrati = [
        ricordi_trovati[i] for i in range(len(ricordi_trovati))
        if distanze_trovate[i] < soglia_distanza
    ]

    if ricordi_filtrati:
        print(f"🧠 [MEMORIA] Pertinenti (<{soglia_distanza}): {ricordi_filtrati}")
    return ricordi_filtrati
