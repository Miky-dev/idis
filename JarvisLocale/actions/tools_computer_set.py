# actions/computer_settings.py
#
# Quando l'utente dà comandi come "alza il volume", "chiudi l'app",
# "schermo intero", "scrivi questo", questo file entra in gioco.
#
# - Rilevamento intento: tramite Gemini (multilingua, nessuna keyword hardcoded)
# - Solo Windows
# - pyautogui + API specifiche di Windows

import time
import subprocess
import sys
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

def _get_api_key() -> str:
    return "" # Deprecato: si usa Ollama locale




def volume_up():
    for _ in range(5):
        pyautogui.press("volumeup")

def volume_down():
    for _ in range(5):
        pyautogui.press("volumedown")

def volume_mute():
    pyautogui.press("volumemute")

def volume_set(value: int):
    value = max(0, min(100, value))
    try:
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        import math
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        vol = cast(interface, POINTER(IAudioEndpointVolume))
        vol_db = -65.25 if value == 0 else max(-65.25, 20 * math.log10(value / 100))
        vol.SetMasterVolumeLevel(vol_db, None)
        print(f"[Impostazioni] 🔊 Volume → {value}%")
        return
    except Exception as e:
        print(f"[Impostazioni] ⚠️ pycaw non riuscito: {e}")

def brightness_up():
    pyautogui.hotkey("win", "a")
    time.sleep(0.3)

def brightness_down():
    pyautogui.hotkey("win", "a")
    time.sleep(0.3)


def close_app():
    pyautogui.hotkey("alt", "f4")

def close_window():
    pyautogui.hotkey("ctrl", "w")

def full_screen():
    pyautogui.press("f11")

def minimize_window():
    pyautogui.hotkey("win", "down")

def maximize_window():
    pyautogui.hotkey("win", "up")

def snap_left():
    pyautogui.hotkey("win", "left")

def snap_right():
    pyautogui.hotkey("win", "right")

def switch_window():
    pyautogui.hotkey("alt", "tab")

def show_desktop():
    pyautogui.hotkey("win", "d")

def open_task_manager():
    pyautogui.hotkey("ctrl", "shift", "esc")

def open_task_view():
    pyautogui.hotkey("win", "tab")


def focus_search():
    pyautogui.hotkey("ctrl", "l")

def pause_video():      pyautogui.press("space")
def refresh_page():
    pyautogui.press("f5")

def close_tab():
    pyautogui.hotkey("ctrl", "w")

def new_tab():
    pyautogui.hotkey("ctrl", "t")

def next_tab():
    pyautogui.hotkey("ctrl", "tab")

def prev_tab():
    pyautogui.hotkey("ctrl", "shift", "tab")

def go_back():
    pyautogui.hotkey("alt", "left")

def go_forward():
    pyautogui.hotkey("alt", "right")

def zoom_in():
    pyautogui.hotkey("ctrl", "equal")

def zoom_out():
    pyautogui.hotkey("ctrl", "minus")

def zoom_reset():
    pyautogui.hotkey("ctrl", "0")

def find_on_page():
    pyautogui.hotkey("ctrl", "f")

def reload_page_n(n: int):
    for _ in range(n):
        refresh_page()
        time.sleep(0.8)


def scroll_up(amount: int = 500):   pyautogui.scroll(amount)
def scroll_down(amount: int = 500): pyautogui.scroll(-amount)
def scroll_top():    pyautogui.hotkey("ctrl", "home")
def scroll_bottom(): pyautogui.hotkey("ctrl", "end")
def page_up():       pyautogui.press("pageup")
def page_down():     pyautogui.press("pagedown")


def copy():
    pyautogui.hotkey("ctrl", "c")

def paste():
    pyautogui.hotkey("ctrl", "v")

def cut():
    pyautogui.hotkey("ctrl", "x")

def undo():
    pyautogui.hotkey("ctrl", "z")

def redo():
    pyautogui.hotkey("ctrl", "y")

def select_all():
    pyautogui.hotkey("ctrl", "a")

def save_file():
    pyautogui.hotkey("ctrl", "s")

def press_enter():  pyautogui.press("enter")
def press_escape(): pyautogui.press("escape")
def press_key(key: str): pyautogui.press(key)

def type_text(text: str, press_enter_after: bool = False):
    if not text:
        return
    if _PYPERCLIP:
        pyperclip.copy(text)
        time.sleep(0.1)
        paste()
    else:
        pyautogui.write(str(text), interval=0.03)
    if press_enter_after:
        time.sleep(0.1)
        pyautogui.press("enter")

def write_on_screen(text: str):
    type_text(text)

def take_screenshot():
    pyautogui.hotkey("win", "shift", "s")

def lock_screen():
    pyautogui.hotkey("win", "l")

def open_system_settings():
    pyautogui.hotkey("win", "i")

def open_file_explorer():
    pyautogui.hotkey("win", "e")

def open_run():
    pyautogui.hotkey("win", "r")

def sleep_display():
    try:
        import ctypes
        ctypes.windll.user32.SendMessageW(0xFFFF, 0x0112, 0xF170, 2)
    except Exception:
        pass

def restart_computer():
    subprocess.run(["shutdown", "/r", "/t", "5"])


def shutdown_computer():
    subprocess.run(["shutdown", "/s", "/t", "5"])


def dark_mode():
    pyautogui.hotkey("win", "a")
    time.sleep(0.3)


def toggle_wifi():
    pyautogui.hotkey("win", "a")
    time.sleep(0.3)

ACTION_MAP = {
    "volume_up":               volume_up,
    "volume_down":             volume_down,
    "mute":                    volume_mute,
    "unmute":                  volume_mute,
    "volume_increase":         volume_up,
    "volume_decrease":         volume_down,
    "increase_volume":         volume_up,
    "decrease_volume":         volume_down,
    "turn_up_volume":          volume_up,
    "turn_down_volume":        volume_down,
    "louder":                  volume_up,
    "quieter":                 volume_down,
    "silence":                 volume_mute,
    "toggle_mute":             volume_mute,
    "brightness_up":           brightness_up,
    "brightness_down":         brightness_down,
    "increase_brightness":     brightness_up,
    "decrease_brightness":     brightness_down,
    "brighter":                brightness_up,
    "dimmer":                  brightness_down,
    "dim_screen":              brightness_down,
    "brighten_screen":         brightness_up,
    "sleep_display":           sleep_display,
    "turn_off_screen":         sleep_display,
    "screen_off":              sleep_display,
    "display_off":             sleep_display,
    "change_screen":           sleep_display,
    "screen_sleep":            sleep_display,
    "monitor_off":             sleep_display,
    "turn_off_monitor":        sleep_display,
    "pause_video":             pause_video,
    "play_video":              pause_video,
    "pause":                   pause_video,
    "play":                    pause_video,
    "toggle_play":             pause_video,
    "stop_video":              pause_video,
    "resume_video":            pause_video,
    "close_app":               close_app,
    "close_window":            close_window,
    "quit_app":                close_app,
    "exit_app":                close_app,
    "kill_app":                close_app,
    "full_screen":             full_screen,
    "fullscreen":              full_screen,
    "toggle_fullscreen":       full_screen,
    "minimize":                minimize_window,
    "minimize_window":         minimize_window,
    "maximize":                maximize_window,
    "maximize_window":         maximize_window,
    "restore_window":          maximize_window,
    "snap_left":               snap_left,
    "snap_right":              snap_right,
    "window_left":             snap_left,
    "window_right":            snap_right,
    "switch_window":           switch_window,
    "alt_tab":                 switch_window,
    "next_window":             switch_window,
    "show_desktop":            show_desktop,
    "desktop":                 show_desktop,
    "hide_windows":            show_desktop,
    "task_manager":            open_task_manager,
    "open_task_manager":       open_task_manager,
    "task_view":               open_task_view,
    "screenshot":              take_screenshot,
    "take_screenshot":         take_screenshot,
    "capture_screen":          take_screenshot,
    "lock_screen":             lock_screen,
    "lock":                    lock_screen,
    "open_settings":           open_system_settings,
    "system_settings":         open_system_settings,
    "settings":                open_system_settings,
    "preferences":             open_system_settings,
    "file_explorer":           open_file_explorer,
    "open_explorer":           open_file_explorer,
    "explorer":                open_file_explorer,
    "open_files":              open_file_explorer,
    "run":                     open_run,
    "open_run":                open_run,
    "restart":                 restart_computer,
    "restart_computer":        restart_computer,
    "reboot":                  restart_computer,
    "reboot_computer":         restart_computer,
    "shutdown":                shutdown_computer,
    "shut_down":               shutdown_computer,
    "power_off":               shutdown_computer,
    "turn_off_computer":       shutdown_computer,
    "dark_mode":               dark_mode,
    "toggle_dark_mode":        dark_mode,
    "night_mode":              dark_mode,
    "toggle_wifi":             toggle_wifi,
    "wifi":                    toggle_wifi,
    "wifi_toggle":             toggle_wifi,
    "focus_search":            focus_search,
    "address_bar":             focus_search,
    "url_bar":                 focus_search,
    "refresh_page":            refresh_page,
    "reload_page":             refresh_page,
    "reload":                  refresh_page,
    "refresh":                 refresh_page,
    "close_tab":               close_tab,
    "new_tab":                 new_tab,
    "open_tab":                new_tab,
    "next_tab":                next_tab,
    "prev_tab":                prev_tab,
    "previous_tab":            prev_tab,
    "go_back":                 go_back,
    "back":                    go_back,
    "go_forward":              go_forward,
    "forward":                 go_forward,
    "zoom_in":                 zoom_in,
    "zoom_out":                zoom_out,
    "zoom_reset":              zoom_reset,
    "reset_zoom":              zoom_reset,
    "find_on_page":            find_on_page,
    "search_page":             find_on_page,
    "scroll_up":               scroll_up,
    "scroll_down":             scroll_down,
    "scroll_top":              scroll_top,
    "scroll_bottom":           scroll_bottom,
    "top_of_page":             scroll_top,
    "bottom_of_page":          scroll_bottom,
    "page_up":                 page_up,
    "page_down":               page_down,
    "copy":                    copy,
    "paste":                   paste,
    "cut":                     cut,
    "undo":                    undo,
    "redo":                    redo,
    "select_all":              select_all,
    "save":                    save_file,
    "save_file":               save_file,
    "enter":                   press_enter,
    "press_enter":             press_enter,
    "escape":                  press_escape,
    "press_escape":            press_escape,
    "cancel":                  press_escape,
}
def _rileva_azione(descrizione: str) -> dict:
    import requests
    import os
    import json
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
    model_name = os.getenv("MODEL_LOCAL", "qwen2.5:4b")


    disponibili = ", ".join(sorted(ACTION_MAP.keys())) + ", volume_set, type_text, write_on_screen, reload_n, press_key"

    prompt = f"""L'utente vuole controllare il computer. Rileva la sua intenzione.

L'utente ha detto (in qualsiasi lingua): "{descrizione}"

Azioni disponibili: {disponibili}

Restituisci SOLO JSON valido:
{{"action": "nome_azione", "value": null_o_valore}}

Esempi:
- "alza il volume" → {{"action": "volume_up", "value": null}}
- "imposta il volume a 60" → {{"action": "volume_set", "value": 60}}
- "volume all'80" → {{"action": "volume_set", "value": 80}}
- "chiudi l'app" → {{"action": "close_app", "value": null}}
- "scrivi ciao mondo" → {{"action": "type_text", "value": "ciao mondo"}}
- "scrivi buongiorno sullo schermo" → {{"action": "write_on_screen", "value": "buongiorno"}}
- "ricarica la pagina 3 volte" → {{"action": "reload_n", "value": 3}}
- "schermo intero" → {{"action": "full_screen", "value": null}}
- "abbassa il volume" → {{"action": "volume_down", "value": null}}
- "alza il volume" → {{"action": "volume_up", "value": null}}
- "silenzia" → {{"action": "mute", "value": null}}
- "monte le son" → {{"action": "volume_up", "value": null}}
- "spegni lo schermo" → {{"action": "sleep_display", "value": null}}
- "spegni il monitor" → {{"action": "sleep_display", "value": null}}
- "turn off screen" → {{"action": "sleep_display", "value": null}}
- "turn off monitor" → {{"action": "sleep_display", "value": null}}
- "riavvia il computer" → {{"action": "restart", "value": null}}
- "restart the computer" → {{"action": "restart", "value": null}}
- "spegni il computer" → {{"action": "shutdown", "value": null}}
- "shut down" → {{"action": "shutdown", "value": null}}
- "blocca lo schermo" → {{"action": "lock_screen", "value": null}}
- "lock the screen" → {{"action": "lock_screen", "value": null}}
- "minimizza" → {{"action": "minimize", "value": null}}
- "minimize the window" → {{"action": "minimize", "value": null}}
- "massimizza" → {{"action": "maximize", "value": null}}
- "aumenta la luminosità" → {{"action": "brightness_up", "value": null}}
- "diminuisci la luminosità" → {{"action": "brightness_down", "value": null}}
- "increase brightness" → {{"action": "brightness_up", "value": null}}
- "attiva/disattiva wifi" → {{"action": "toggle_wifi", "value": null}}
- "toggle wifi" → {{"action": "toggle_wifi", "value": null}}
- "mostra il desktop" → {{"action": "show_desktop", "value": null}}
- "show desktop" → {{"action": "show_desktop", "value": null}}
- "apri nuova scheda" → {{"action": "new_tab", "value": null}}
- "chiudi la scheda" → {{"action": "close_tab", "value": null}}
- "vai indietro" → {{"action": "go_back", "value": null}}
- "vai avanti" → {{"action": "go_forward", "value": null}}
- "aggiorna la pagina" → {{"action": "refresh_page", "value": null}}
- "zoom avanti" → {{"action": "zoom_in", "value": null}}
- "zoom indietro" → {{"action": "zoom_out", "value": null}}
- "salva" → {{"action": "save", "value": null}}
- "annulla" → {{"action": "undo", "value": null}}
- "fai uno screenshot" → {{"action": "screenshot", "value": null}}
- "scorri verso il basso" → {{"action": "scroll_down", "value": null}}
- "scorri verso l'alto" → {{"action": "scroll_up", "value": null}}
- "modalità scura" → {{"action": "dark_mode", "value": null}}
- "premi f5" → {{"action": "press_key", "value": "f5"}}
- "premi invio" → {{"action": "enter", "value": null}}
- "premi escape" → {{"action": "escape", "value": null}}

IMPORTANTE:
- Restituisci sempre una delle azioni disponibili elencate sopra.
- Se l'intento dell'utente è chiaro ma usa parole diverse, mappalo all'azione più vicina.
- Non inventare nomi di azioni non presenti nella lista disponibile.
- Restituisci SOLO l'oggetto JSON, senza spiegazioni né markdown."""

    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "format": "json"
    }

    try:
        resp = requests.post("http://localhost:11434/api/generate", json=payload, timeout=60)
        resp.raise_for_status()
        text = resp.json().get("response", "").strip()
        text = __import__("re").sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
        return json.loads(text)
    except Exception as e:
        print(f"[Impostazioni] ⚠️ Rilevamento intento fallito via Ollama: {e}")
        return {"action": descrizione.lower().replace(" ", "_"), "value": None}


def computer_settings(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """
    Impostazioni computer e controlli UI.

    parameters:
        action      : Nome dell'azione (se non fornito, viene rilevato da description tramite Gemini)
        description : Comando in linguaggio naturale dell'utente (in qualsiasi lingua)
        value       : Valore specifico per l'azione (livello volume, testo da scrivere, numero di ripetizioni, ecc.)
    """
    if not _PYAUTOGUI:
        return "pyautogui non è installato. Esegui: pip install pyautogui"

    params      = parameters or {}
    raw_action  = params.get("action", "").strip()
    description = params.get("description", "").strip()
    value       = params.get("value", None)

    if not raw_action and description:
        rilevato   = _rileva_azione(description)
        raw_action = rilevato.get("action", "")
        if value is None:
            value = rilevato.get("value")

    action = raw_action.lower().strip().replace(" ", "_").replace("-", "_")

    if not action:
        return "Nessuna azione determinabile, signore."

    print(f"[Impostazioni] ⚙️ Azione: {action}  Valore: {value}")


    if action == "volume_set":
        try:
            volume_set(int(value or 50))
            return f"Volume impostato al {value}%."
        except Exception as e:
            return f"Impossibile impostare il volume: {e}"

    if action in ("type_text", "write_on_screen", "type", "write"):
        text = str(value or params.get("text", ""))
        if not text:
            return "Nessun testo fornito da scrivere, signore."
        enter_after = bool(params.get("press_enter", False))
        type_text(text, press_enter_after=enter_after)
        return f"Scritto: {text[:60]}"

    if action == "press_key":
        key = str(value or params.get("key", ""))
        if not key:
            return "Nessun tasto specificato, signore."
        press_key(key)
        return f"Tasto premuto: {key}"

    if action in ("reload_n", "refresh_n", "reload_page_n"):
        try:
            n = int(value or 1)
            reload_page_n(n)
            return f"Pagina ricaricata {n} {'volta' if n == 1 else 'volte'}."
        except Exception as e:
            return f"Impossibile ricaricare: {e}"

    if action in ("scroll_up", "scroll_down"):
        try:
            amount = int(value or 500)
            scroll_up(amount) if action == "scroll_up" else scroll_down(amount)
            return f"Scorso {'su' if action == 'scroll_up' else 'giù'}."
        except Exception as e:
            return f"Scorrimento fallito: {e}"

    func = ACTION_MAP.get(action)
    if not func:
        return f"Azione sconosciuta: '{raw_action}', signore."

    try:
        func()
        return f"Fatto: {action}."
    except Exception as e:
        return f"Azione fallita ({action}): {e}"

from langchain_core.tools import tool

@tool
def esegui_azione_computer(comando: str) -> str:
    """
    Usa questo tool per controllare le impostazioni e l'interfaccia del computer tramite l'API di Windows e PyAutoGUI.
    Azioni possibili: alzare/abbassare il volume, silenziare, modificare luminosità, spegnere lo schermo,
    mettere in pausa video, ricaricare la pagina, gestire le finestre (chiudi, minimizza, massimizza, affianca),
    gestire schede del browser (nuova, chiudi, avanti, indietro), digitare testo e simulare tastiera,
    aprire impostazioni/esplora risorse, o fare azioni di sistema (riavvia, spegni, blocca).
    Esempi: "alza il volume", "chiudi la finestra", "scrivi ciao mondo", "abbassa la luminosità", "premi f5".
    Passa l'intero comando dell'utente nel parametro 'comando'.
    """
    return computer_settings({"description": comando})