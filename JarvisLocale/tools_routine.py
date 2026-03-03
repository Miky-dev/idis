import datetime
import threading
import time
import tkinter.messagebox
import winsound
from langchain_core.tools import tool
import dateparser
import uuid

# Dizionario globale per tenere traccia delle sveglie in esecuzione
sveglie_attive = {}

def esegui_allarme(id_sveglia: str, secondi_attesa: int, messaggio: str):
    """Funzione interna che aspetta in background e fa scattare l'allarme."""
    try:
        time.sleep(secondi_attesa)
        
        # Suono di sistema Windows (asterisk è il popup standard, prova anche winsound.Beep per suoni personalizzati)
        try:
            winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS)
        except:
            pass
            
        # Mostra messaggio asincrono in un popup in cima a tutte le finestre
        import tkinter as tk
        root = tk.Tk()
        root.withdraw() # Nascondiamo la finestra principale, lasciando solo il popup
        root.attributes("-topmost", True)
        tkinter.messagebox.showinfo("⏰ SVEGLIA DI JARVIS", messaggio, parent=root)
        root.destroy()
    finally:
        # Rimuove la sveglia dalla lista globale una volta suonata (o se fallisce)
        sveglie_attive.pop(id_sveglia, None)

def ottieni_sveglie_attive():
    """Restituisce le sveglie correntemente in esecuzione."""
    # Restituiamo una copia per evitare errori di mutazione durante l'iterazione nella UI
    return dict(sveglie_attive)

@tool
def imposta_sveglia(orario: str, messaggio: str = "Promemoria") -> str:
    """
    Usa questo strumento per impostare una sveglia, un timer o un promemoria sul computer.
    
    Argomenti:
    - 'orario': Accetta orari esatti ("15:30") o delta temporali ("tra 10 minuti", "tra 1 ora").
    - 'messaggio': Il contenuto testuale dell'allarme che verrà mostrato a video (es. "Sveglia per la riunione").
    """
    try:
        # Usa dateparser per capire tra quanto dee suonare
        adesso = datetime.datetime.now()
        data_sveglia = dateparser.parse(orario, languages=['it'], settings={'PREFER_DATES_FROM': 'future'})
        
        if not data_sveglia:
            return f"Non sono riuscito a capire l'orario indicato: '{orario}'. Sii più chiaro (es. 'tra 15 minuti' o 'alle 18:00')."
            
        # Se l'orario ricavato è incredibilmente nel passato (es. se dico "alle 15" e sono le 18, dateparser potrebbe dare le 15 di oggi in difetto per colpa di parser bug. Aggiustiamo se necessario).
        if data_sveglia < adesso:
            data_sveglia = data_sveglia + datetime.timedelta(days=1)
            
        differenza = data_sveglia - adesso
        secondi_attesa = int(differenza.total_seconds())
        
        if secondi_attesa <= 0:
             return "L'orario specificato è già passato."
        # Tracciamo la sveglia
        id_sveglia = uuid.uuid4().hex[:8]
        sveglie_attive[id_sveglia] = {
            "orario": data_sveglia.strftime('%H:%M:%S'),
            "messaggio": messaggio
        }
             
        # Lancia il thread
        thread_sveglia = threading.Thread(target=esegui_allarme, args=(id_sveglia, secondi_attesa, messaggio), daemon=True)
        thread_sveglia.start()
        
        return f"Sveglia impostata! Suonerà il {data_sveglia.strftime('%d/%m alle %H:%M:%S')} con il messaggio: '{messaggio}'"
    except Exception as e:
        return f"Errore durante l'impostazione della sveglia: {str(e)}"
