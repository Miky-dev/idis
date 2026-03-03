

#             .\venv\Scripts\python.exe gestisci_memoria.py


import chromadb

# Connessione al database (stesso percorso usato dall'app)
chroma_client = chromadb.PersistentClient(path="./chroma_db")
collezione = chroma_client.get_collection(name="memoria_jarvis")

def mostra_menu():
    print("\n--- GESTIONE MEMORIA JARVIS ---")
    print("1. Elimina ricordi (modalità loop)")
    print("2. Svuota tutta la memoria")
    print("3. Esci")
    return input("\nScegli un'opzione (1/2/3): ")

def gestisci_eliminazione_singola():
    while True:
        # Ricarichiamo i dati a ogni giro per avere gli indici corretti
        risultati = collezione.get()
        ids = risultati.get('ids', [])
        documenti = risultati.get('documents', [])
        
        if not ids:
            print("\nLa memoria è vuota.")
            break
            
        print("\n--- ELENCO RICORDI ---")
        for i, doc in enumerate(documenti):
            print(f"[{i}] {doc}")
            
        valore = input("\nInserisci il numero [X] da eliminare o '999' per uscire: ")
        
        if valore == '999':
            break
            
        try:
            indice = int(valore)
            if 0 <= indice < len(ids):
                id_da_eliminare = ids[indice]
                collezione.delete(ids=[id_da_eliminare])
                print(f"✅ Record eliminato.")
            else:
                print("❌ Indice non valido.")
        except ValueError:
            print("❌ Inserisci un numero valido.")

# --- MAIN ---
while True:
    scelta = mostra_menu()
    
    if scelta == '1':
        gestisci_eliminazione_singola()
    elif scelta == '2':
        conferma = input("\nSei SICURO di voler cancellare TUTTA la memoria? (s/n): ")
        if conferma.lower() == 's':
            collezione.delete(where={})
            print("✅ Memoria svuotata.")
    elif scelta == '3':
        print("Uscita.")
        break
    else:
        print("Opzione non valida.")
