import webbrowser
import pyautogui
import time
import os
from langchain_core.tools import tool
from langchain_community.tools import DuckDuckGoSearchRun

# Configura il percorso di Opera (tipicamente in AppData\Local\Programs\Opera\launcher.exe)
try:
    opera_path = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs', 'Opera GX', 'opera.exe')
    webbrowser.register('opera', None, webbrowser.BackgroundBrowser(opera_path))
except Exception:
    pass

# Inizializza lo strumento di base
ricerca_ddg = DuckDuckGoSearchRun()

@tool
def apri_sito_web(nome_sito: str) -> str:
    """
    Usa questo strumento SOLO quando l'utente ti chiede esplicitamente di aprire un sito web specifico (es. YouTube, Netflix, Amazon, Wikipedia, ecc.).
    L'argomento 'nome_sito' deve essere il nome del sito senza spazi (es. 'youtube', 'netflix', 'google').
    """
    nome_sito = nome_sito.lower().strip()
    
    # Costruiamo l'URL. Se l'utente non ha specificato l'estensione, proviamo con .com
    if "." not in nome_sito:
        url = f"https://www.{nome_sito}.com"
    else:
        url = f"https://{nome_sito}"
        if not url.startswith("https://www."):
            url = url.replace("https://", "https://www.")
            
    try:
        try:
            browser = webbrowser.get('opera')
        except webbrowser.Error:
            browser = webbrowser.get() # Fallback al default se Opera non è registrato
            
        browser.open(url)
        return f"Ho aperto {url} nel browser Opera."
    except Exception as e:
        return f"Errore durante l'apertura del sito: {str(e)}"

@tool
def digita_nel_browser(ricerca: str) -> str:
    """
    Usa questo strumento SOLO quando l'utente ti chiede esplicitamente di "scrivere", "cercare", o "digitare" qualcosa DIRETTAMENTE nella barra di ricerca del browser (es. 'cerca gatti divertenti sul browser').
    L'argomento 'ricerca' è la frase esatta che devi digitare.
    """
    try:
        try:
            browser = webbrowser.get('opera')
        except webbrowser.Error:
            browser = webbrowser.get()
            
        # 1. Apre una nuova scheda vuota in Opera
        browser.open_new_tab("about:blank")
        time.sleep(2)  # Attende che il browser si carichi
        
        # 2. Seleziona la barra degli indirizzi/ricerca (scorciatoia universale)
        pyautogui.hotkey('ctrl', 'l')
        time.sleep(0.5)
        
        # 3. Digita il testo come farebbe un umano (con un piccolo intervallo tra le lettere per realismo)
        pyautogui.write(ricerca, interval=0.05)
        time.sleep(0.5)
        
        # 4. Preme Invio per avviare la ricerca
        pyautogui.press('enter')
        
        return f"Ho aperto Opera e cercato: '{ricerca}'."
    except Exception as e:
        return f"Errore durante l'automazione del browser: {str(e)}"

@tool
def cerca_su_internet(query: str) -> str:
    """
    Usa questo strumento SOLO per cercare su internet informazioni in tempo reale, notizie, eventi recenti o risposte a domande di cui non conosci la risposta (es. "chi ha vinto la partita", "notizie di oggi", "meteo", o fatti post-2023).
    L'argomento 'query' deve essere una stringa di ricerca concisa in italiano (es. 'ultime notizie intelligenza artificiale').
    Restituisce un riassunto dei risultati web.
    """
    try:
        risultati = ricerca_ddg.run(query)
        return f"Risultati dal web: {risultati}"
    except Exception as e:
        return f"Errore durante la ricerca web: {str(e)}"
