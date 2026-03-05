import webbrowser
import pyautogui
import time
import os
import threading
from langchain_core.tools import tool
from langchain_community.tools import DuckDuckGoSearchRun

# Registra Opera GX
try:
    opera_path = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs', 'Opera GX', 'opera.exe')
    webbrowser.register('opera', None, webbrowser.BackgroundBrowser(opera_path))
except Exception:
    pass

ricerca_ddg = DuckDuckGoSearchRun()

def _get_browser():
    try:
        return webbrowser.get('opera')
    except webbrowser.Error:
        return webbrowser.get()

@tool
def apri_sito_web(nome_sito: str) -> str:
    """
    Apre un sito web nel browser. Usa quando l'utente chiede di aprire un sito specifico.
    'nome_sito': nome del sito senza spazi (es. 'youtube', 'netflix', 'google').
    """
    nome_sito = nome_sito.lower().strip()
    url = f"https://www.{nome_sito}.com" if "." not in nome_sito else f"https://www.{nome_sito}"

    try:
        # ✅ open() in thread separato — non blocca il tool in attesa del browser
        threading.Thread(target=_get_browser().open, args=(url,), daemon=True).start()
        return f"Apro {url}."
    except Exception as e:
        return f"Errore: {str(e)}"

@tool
def digita_nel_browser(ricerca: str) -> str:
    """
    Digita e cerca qualcosa direttamente nella barra del browser.
    'ricerca': frase esatta da cercare.
    """
    try:
        threading.Thread(target=_get_browser().open_new_tab, args=("about:blank",), daemon=True).start()
        time.sleep(1.2)  # ✅ ridotto da 2s a 1.2s
        pyautogui.hotkey('ctrl', 'l')
        time.sleep(0.3)  # ✅ ridotto da 0.5s a 0.3s
        pyautogui.write(ricerca, interval=0.03)  # ✅ interval ridotto
        pyautogui.press('enter')
        return f"Cerco '{ricerca}' nel browser."
    except Exception as e:
        return f"Errore: {str(e)}"

@tool
def cerca_su_internet(query: str) -> str:
    """
    Cerca informazioni su internet in tempo reale.
    Usa per notizie, eventi recenti, fatti post-2023.
    NON usare per il meteo (usa 'mostra_meteo').
    """
    try:
        # ✅ Apre il browser in background senza aspettarlo
        from urllib.parse import quote_plus
        url = f"https://duckduckgo.com/?q={quote_plus(query)}"
        threading.Thread(target=_get_browser().open, args=(url,), daemon=True).start()

        # La ricerca DDG è indipendente dal browser — non aspetta che si apra
        risultati = ricerca_ddg.run(query)
        return f"Risultati: {risultati}"
    except Exception as e:
        return f"Errore ricerca: {str(e)}"