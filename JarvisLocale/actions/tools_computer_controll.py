# actions/computer_control.py
#
# Funzioni atomiche di controllo del computer tramite PyAutoGUI + keyboard + clipboard.
# Usate dall'agente quando nessun altro file di azioni copre il compito.
#
# Funzionalità:
#   - Scrivere testo ovunque (finestra attiva, form, campi)
#   - Click, doppio click, click destro, trascinamento con il mouse
#   - Scorciatoie da tastiera e combinazioni di tasti
#   - Scorrimento (su/giù/sinistra/destra)
#   - Gestione finestre (minimizza, massimizza, chiudi, porta in primo piano)
#   - Appunti (copia, incolla, leggi contenuto)
#   - Screenshot + individua elemento sullo schermo
#   - Attesa / attesa intelligente fino alla comparsa di un elemento
#   - Generazione dati casuali (nome, email, username, password, telefono, indirizzo)
#   - Sequenze di scorciatoie
#   - Trova e clicca immagine/elemento sullo schermo

import json
import sys
import time
import random
import string
import subprocess
from pathlib import Path

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE    = 0.05
    _PYAUTOGUI = True
except ImportError:
    _PYAUTOGUI = False

try:
    import pyperclip
    _PYPERCLIP = True
except ImportError:
    _PYPERCLIP = False


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


def _carica_profilo_utente() -> dict:
    """Carica il profilo utente dalla memoria ufficiale di IDIS."""
    try:
        import sys
        from pathlib import Path
        sys.path.append(str(Path(__file__).resolve().parent.parent))
        from tools_memory import leggi_memoria
        
        mem = leggi_memoria()
        return {
            "name":  mem.get("nome", mem.get("nome_utente", "")),
            "age":   mem.get("eta", mem.get("età", "")),
            "city":  mem.get("citta", mem.get("città", mem.get("luogo", ""))),
            "email": mem.get("email", mem.get("mail", "")),
        }
    except Exception as e:
        print(f"[ControlloComputer] ⚠️ Errore lettura memoria IDIS: {e}")
    return {}


def _verifica_pyautogui():
    if not _PYAUTOGUI:
        raise RuntimeError(
            "PyAutoGUI non è installato. Esegui: pip install pyautogui"
        )


_NOMI = [
    "Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Drew", "Quinn",
    "Avery", "Blake", "Cameron", "Dakota", "Emerson", "Finley", "Harper"
]
_COGNOMI = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Wilson", "Moore", "Taylor", "Anderson", "Thomas", "Jackson"
]
_DOMINI = ["gmail.com", "yahoo.com", "outlook.com", "proton.me", "mail.com"]


def genera_dato_casuale(tipo_dato: str) -> str:
    """
    Genera dati casuali realistici per la compilazione di form.

    Tipi: name | first_name | last_name | email | username |
          password | phone | birthday | address | zip_code
    """
    dt = tipo_dato.lower().strip()

    if dt == "first_name":
        return random.choice(_NOMI)

    elif dt == "last_name":
        return random.choice(_COGNOMI)

    elif dt == "name":
        return f"{random.choice(_NOMI)} {random.choice(_COGNOMI)}"

    elif dt == "email":
        nome    = random.choice(_NOMI).lower()
        cognome = random.choice(_COGNOMI).lower()
        num     = random.randint(10, 999)
        return f"{nome}.{cognome}{num}@{random.choice(_DOMINI)}"

    elif dt == "username":
        nome = random.choice(_NOMI).lower()
        num  = random.randint(100, 9999)
        return f"{nome}{num}"

    elif dt == "password":
        chars = string.ascii_letters + string.digits + "!@#$%"
        pwd   = (
            random.choice(string.ascii_uppercase) +
            random.choice(string.digits) +
            random.choice("!@#$%") +
            "".join(random.choices(chars, k=9))
        )
        return "".join(random.sample(pwd, len(pwd)))

    elif dt == "phone":
        return f"+39{random.randint(300,399)}{random.randint(1000000,9999999)}"

    elif dt == "birthday":
        anno  = random.randint(1980, 2000)
        mese  = random.randint(1, 12)
        giorno = random.randint(1, 28)
        return f"{giorno:02d}/{mese:02d}/{anno}"

    elif dt == "address":
        num  = random.randint(1, 200)
        via  = random.choice(["Via Roma", "Via Garibaldi", "Corso Italia", "Via Mazzini", "Via Dante"])
        return f"{via}, {num}"

    elif dt == "zip_code":
        return str(random.randint(10000, 99999))

    elif dt == "city":
        return random.choice(["Milano", "Roma", "Torino", "Napoli", "Bologna"])

    return f"casuale_{tipo_dato}_{random.randint(1000,9999)}"


def _scrivi_testo(testo: str, intervallo: float = 0.03) -> str:
    """Scrive il testo nella posizione corrente del cursore."""
    _verifica_pyautogui()
    time.sleep(0.3)
    pyautogui.typewrite(testo, interval=intervallo)
    return f"Scritto: {testo[:50]}{'...' if len(testo) > 50 else ''}"


def _click(x: int = None, y: int = None, pulsante: str = "left",
           clicks: int = 1, immagine: str = None) -> str:
    """
    Clicca alle coordinate indicate o su un'immagine sullo schermo.
    Se viene fornito il percorso di un'immagine, la individua sullo schermo e ci clicca sopra.
    """
    _verifica_pyautogui()

    if immagine:
        try:
            loc = pyautogui.locateCenterOnScreen(immagine, confidence=0.8)
            if loc:
                pyautogui.click(loc.x, loc.y, button=pulsante, clicks=clicks)
                return f"Click sull'immagine: {immagine}"
            return f"Immagine non trovata sullo schermo: {immagine}"
        except Exception as e:
            return f"Click immagine fallito: {e}"

    if x is not None and y is not None:
        pyautogui.click(x, y, button=pulsante, clicks=clicks)
        return f"Click in ({x}, {y}) con il pulsante {pulsante}"

    pyautogui.click(button=pulsante, clicks=clicks)
    return "Click nella posizione corrente"


def _scorciatoia(*tasti) -> str:
    """Preme una combinazione di tasti. Es. scorciatoia('ctrl', 'c')"""
    _verifica_pyautogui()
    pyautogui.hotkey(*tasti)
    return f"Scorciatoia: {'+'.join(tasti)}"


def _premi(tasto: str) -> str:
    """Preme un singolo tasto."""
    _verifica_pyautogui()
    pyautogui.press(tasto)
    return f"Tasto premuto: {tasto}"


def _scorri(direzione: str = "down", quantita: int = 3) -> str:
    """Scorre nella direzione specificata."""
    _verifica_pyautogui()
    clicks = quantita if direzione in ("up", "right") else -quantita
    if direzione in ("up", "down"):
        pyautogui.scroll(clicks)
    else:
        pyautogui.hscroll(clicks)
    return f"Scorso {direzione} di {quantita}"


def _muovi_mouse(x: int, y: int, durata: float = 0.3) -> str:
    """Sposta il mouse alle coordinate indicate."""
    _verifica_pyautogui()
    pyautogui.moveTo(x, y, duration=durata)
    return f"Mouse spostato in ({x}, {y})"


def _trascina(x1: int, y1: int, x2: int, y2: int, durata: float = 0.5) -> str:
    """Trascina da (x1,y1) a (x2,y2)."""
    _verifica_pyautogui()
    pyautogui.drag(x1 - pyautogui.position()[0], y1 - pyautogui.position()[1])
    pyautogui.dragTo(x2, y2, duration=durata)
    return f"Trascinato da ({x1},{y1}) a ({x2},{y2})"


def _leggi_appunti() -> str:
    """Legge il contenuto corrente degli appunti."""
    if _PYPERCLIP:
        return pyperclip.paste()
    _scorciatoia("ctrl", "c")
    time.sleep(0.2)
    return "Copiato negli appunti"


def _imposta_appunti(testo: str) -> str:
    """Imposta il contenuto degli appunti e lo incolla."""
    if _PYPERCLIP:
        pyperclip.copy(testo)
        time.sleep(0.1)
        _scorciatoia("ctrl", "v")
        return f"Incollato: {testo[:50]}"
    return "pyperclip non disponibile"


def _screenshot(percorso: str = None) -> str:
    """Scatta uno screenshot."""
    _verifica_pyautogui()
    if not percorso:
        percorso = str(Path.home() / "Desktop" / "screenshot.png")
    img = pyautogui.screenshot()
    img.save(percorso)
    return f"Screenshot salvato: {percorso}"


def _attendi(secondi: float) -> str:
    """Attende per il numero di secondi specificato."""
    time.sleep(secondi)
    return f"Atteso {secondi}s"


def _attendi_immagine(percorso_immagine: str, timeout: int = 10) -> str:
    """Attende finché un'immagine appare sullo schermo (fino al timeout in secondi)."""
    _verifica_pyautogui()
    inizio = time.time()
    while time.time() - inizio < timeout:
        try:
            loc = pyautogui.locateCenterOnScreen(percorso_immagine, confidence=0.8)
            if loc:
                return f"Immagine trovata in ({loc.x}, {loc.y})"
        except Exception:
            pass
        time.sleep(0.5)
    return f"Immagine non trovata entro {timeout}s: {percorso_immagine}"


def _dimensioni_schermo() -> str:
    """Restituisce la risoluzione corrente dello schermo."""
    _verifica_pyautogui()
    w, h = pyautogui.size()
    return f"{w}x{h}"


def _porta_in_primo_piano(titolo: str) -> str:
    """Porta in primo piano una finestra tramite il titolo (solo Windows)."""
    try:
        script = f'(New-Object -ComObject WScript.Shell).AppActivate("{titolo}")'
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, timeout=5
        )
        time.sleep(0.3)
        return f"Finestra portata in primo piano: {titolo}"
    except Exception as e:
        return f"Impossibile portare in primo piano la finestra: {e}"


def _seleziona_tutto() -> str:
    return _scorciatoia("ctrl", "a")


def _cancella_campo() -> str:
    """Seleziona tutto ed elimina — svuota un campo di input."""
    _scorciatoia("ctrl", "a")
    time.sleep(0.1)
    _premi("delete")
    return "Campo svuotato"


def _scrivi_smart(testo: str, cancella_prima: bool = True) -> str:
    """
    Scrive il testo nel campo attualmente in focus.
    Opzionalmente svuota il campo prima.
    Usa gli appunti per testi lunghi (più veloce e affidabile).
    """
    _verifica_pyautogui()

    if cancella_prima:
        _cancella_campo()
        time.sleep(0.1)

    if len(testo) > 20 and _PYPERCLIP:
        pyperclip.copy(testo)
        time.sleep(0.1)
        pyautogui.hotkey("ctrl", "v")
        return f"Scritto smart (appunti): {testo[:50]}"
    else:
        pyautogui.typewrite(testo, interval=0.04)
        return f"Scritto smart: {testo[:50]}"


def _analizza_schermo_per_elemento(descrizione: str) -> tuple[int, int] | None:
    """
    Scatta uno screenshot e chiede a Ollama di trovare le coordinate
    di un elemento descritto sullo schermo. Restituisce (x, y) o None.
    Richiede un modello multimodale in MODEL_LOCAL.
    """
    try:
        import io
        import base64
        import json
        import requests
        import os
        from dotenv import load_dotenv

        load_dotenv(BASE_DIR / ".env")
        model_name = os.getenv("MODEL_LOCAL", "qwen2.5:4b")

        _verifica_pyautogui()
        w, h  = pyautogui.size()
        img   = pyautogui.screenshot()
        buf   = io.BytesIO()
        img.save(buf, format="JPEG")
        b64_image = base64.b64encode(buf.getvalue()).decode("utf-8")

        prompt = (
            f"Questo è uno screenshot di uno schermo ({w}x{h} pixel). "
            f"Trova l'elemento: '{descrizione}'. "
            f"Devi restituire SOLO: x,y (le coordinate intere del centro dell'elemento, es. 500,300). "
            f"Se non riesci a trovarlo con sicurezza, restituisci: NOT_FOUND"
        )

        payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [b64_image]
                }
            ],
            "stream": False
        }

        resp = requests.post("http://localhost:11434/api/chat", json=payload, timeout=90)
        resp.raise_for_status()
        testo = resp.json().get("message", {}).get("content", "").strip()

        if "NOT_FOUND" in testo:
            return None

        import re
        match = re.search(r"(\d+)\s*,\s*(\d+)", testo)
        if match:
            return int(match.group(1)), int(match.group(2))

    except Exception as e:
        print(f"[ControlloComputer] ⚠️ Analisi schermo fallita via Ollama: {e}")

    return None



def computer_control(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """
    Azione universale di controllo del computer.

    Azioni:
      type          : Scrive testo nella posizione corrente del cursore
      smart_type    : Svuota il campo + scrive (usa appunti per testi lunghi)
      click         : Click alle coordinate o su un'immagine
      double_click  : Doppio click
      right_click   : Click destro
      hotkey        : Combinazione di tasti (es. ctrl+c)
      press         : Pressione di un singolo tasto
      scroll        : Scorrimento su/giù/sinistra/destra
      move          : Sposta il mouse alle coordinate
      drag          : Trascina da un punto a un altro
      copy          : Legge il contenuto degli appunti
      paste         : Imposta e incolla il contenuto degli appunti
      screenshot    : Scatta uno screenshot
      wait          : Attende N secondi
      wait_image    : Attende che un'immagine appaia sullo schermo
      clear_field   : Seleziona tutto + elimina nel campo corrente
      focus_window  : Porta la finestra in primo piano
      screen_find   : Trova un elemento con AI — restituisce le coordinate
      screen_click  : Trova un elemento con AI + click
      random_data   : Genera dati casuali per i form
      user_data     : Recupera i dati reali dell'utente dalla memoria
    """
    azione = (parameters or {}).get("action", "").lower().strip()

    if not azione:
        return "Specifica un'azione per computer_control, signore."

    if player:
        player.write_log(f"[Computer] {azione}")

    print(f"[ControlloComputer] ▶️ Azione: {azione}  Parametri: {parameters}")

    try:
        if azione == "type":
            testo = parameters.get("text", "")
            return _scrivi_testo(testo)

        elif azione == "smart_type":
            testo          = parameters.get("text", "")
            cancella_prima = parameters.get("clear_first", True)
            return _scrivi_smart(testo, cancella_prima=cancella_prima)

        elif azione in ("click", "left_click"):
            return _click(
                x=parameters.get("x"),
                y=parameters.get("y"),
                pulsante="left",
                clicks=1,
                immagine=parameters.get("image")
            )

        elif azione == "double_click":
            return _click(
                x=parameters.get("x"),
                y=parameters.get("y"),
                pulsante="left",
                clicks=2,
                immagine=parameters.get("image")
            )

        elif azione == "right_click":
            return _click(
                x=parameters.get("x"),
                y=parameters.get("y"),
                pulsante="right",
                clicks=1
            )

        elif azione == "move":
            return _muovi_mouse(
                x=int(parameters.get("x", 0)),
                y=int(parameters.get("y", 0)),
                durata=float(parameters.get("duration", 0.3))
            )

        elif azione == "drag":
            return _trascina(
                x1=int(parameters.get("x1", 0)),
                y1=int(parameters.get("y1", 0)),
                x2=int(parameters.get("x2", 0)),
                y2=int(parameters.get("y2", 0))
            )

        elif azione == "hotkey":
            tasti = parameters.get("keys", "")
            if isinstance(tasti, str):
                tasti = [t.strip() for t in tasti.split("+")]
            return _scorciatoia(*tasti)

        elif azione == "press":
            return _premi(parameters.get("key", "enter"))

        elif azione == "scroll":
            return _scorri(
                direzione=parameters.get("direction", "down"),
                quantita=int(parameters.get("amount", 3))
            )

        elif azione == "copy":
            return _leggi_appunti()

        elif azione == "paste":
            return _imposta_appunti(parameters.get("text", ""))

        elif azione == "screenshot":
            return _screenshot(parameters.get("path"))

        elif azione == "wait":
            return _attendi(float(parameters.get("seconds", 1.0)))

        elif azione == "wait_image":
            return _attendi_immagine(
                parameters.get("image", ""),
                timeout=int(parameters.get("timeout", 10))
            )

        elif azione == "clear_field":
            return _cancella_campo()

        elif azione == "focus_window":
            return _porta_in_primo_piano(parameters.get("title", ""))

        elif azione == "screen_size":
            return _dimensioni_schermo()

        elif azione == "screen_find":
            descrizione = parameters.get("description", "")
            coords = _analizza_schermo_per_elemento(descrizione)
            if coords:
                return f"{coords[0]},{coords[1]}"
            return "NOT_FOUND"

        elif azione == "screen_click":
            descrizione = parameters.get("description", "")
            coords = _analizza_schermo_per_elemento(descrizione)
            if coords:
                time.sleep(0.2)
                _click(x=coords[0], y=coords[1])
                return f"Trovato e cliccato: {descrizione} in {coords}"
            return f"Impossibile trovare sullo schermo: {descrizione}"

        elif azione == "random_data":
            tipo_dato = parameters.get("type", "name")
            risultato = genera_dato_casuale(tipo_dato)
            print(f"[ControlloComputer] 🎲 Casuale {tipo_dato}: {risultato}")
            return risultato

        elif azione == "user_data":
            campo   = parameters.get("field", "name")
            profilo = _carica_profilo_utente()
            valore  = profilo.get(campo, "")
            if not valore:
                valore = genera_dato_casuale(campo)
                print(f"[ControlloComputer] ⚠️ Nessun dato '{campo}' in memoria, uso casuale: {valore}")
            return valore

        else:
            return f"Azione computer_control sconosciuta: '{azione}'"

    except Exception as e:
        print(f"[ControlloComputer] ❌ Errore: {e}")
        return f"computer_control fallito: {e}"

from langchain_core.tools import tool

@tool
def controllo_avanzato_computer(azione: str, parametri_json: str) -> str:
    """
    Usa questo tool per controlli avanzati del computer (mouse, tastiera, schermo).
    Azioni ('azione'): 'type', 'smart_type', 'click', 'double_click', 'right_click', 'hotkey', 'press', 'scroll', 'move', 'drag', 'copy', 'paste', 'screenshot', 'clear_field', 'focus_window', 'screen_find', 'screen_click', 'random_data', 'user_data'.
    - 'parametri_json' deve essere una stringa JSON valida con i parametri dell'azione:
      - 'type', 'smart_type', 'paste': {"text": "testo da scrivere"}
      - 'hotkey': {"keys": "ctrl+c"} (oppure "ctrl+alt+canc")
      - 'press': {"key": "enter"} (oppure "escape", "f5")
      - 'click', 'move': {"x": 100, "y": 200}
      - 'scroll': {"direction": "down", "amount": 3}
      - 'focus_window': {"title": "TitoloFinestra"}
      - 'screen_click' o 'screen_find': {"description": "descrizione visiva di cosa cliccare/trovare sullo schermo"}
      - 'random_data': {"type": "name"} (oppure email, password, username, phone, address, city)
      - 'user_data': {"field": "name"} (legge dai dati utente di IDIS)
    """
    try:
        params = json.loads(parametri_json)
    except Exception as e:
        return f"Errore parsing JSON: {e}"
    params['action'] = azione
    return computer_control(params)