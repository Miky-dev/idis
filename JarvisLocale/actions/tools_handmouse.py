"""
tools_handmouse.py — Wrapper IDIS per hand_mouse_script.py
Avvia/ferma il controller a comando vocale interagendo con un processo separato Python 3.12.
"""

import subprocess
import os
from langchain_core.tools import tool

_processo = None

@tool
def attiva_controllo_mano() -> str:
    """
    Attiva il controllo del mouse con i gesti della mano tramite webcam.
    Usalo quando l'utente dice 'attiva controllo mano', 'usa la mano per il mouse',
    'controlla il mouse con la mano', 'attiva hand mouse', 'hand mouse on'.
    """
    global _processo
    if _processo is not None and _processo.poll() is None:
        return "Il controllo mano e gia attivo. Guarda la finestra HandMouse."
    
    # Costruisci i percorsi relativi alla cartella di IDIS
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    python_exe = os.path.join(base_dir, "actions", "handmouse", "venv", "Scripts", "python.exe")
    script_path = os.path.join(base_dir, "actions", "handmouse", "hand_mouse_script.py")
    
    if not os.path.exists(python_exe):
        return f"Errore: Ambiente virtuale HandMouse non trovato in {python_exe}. Assicurati di aver eseguito il setup con Python 3.12."
    
    try:
        _processo = subprocess.Popen([python_exe, script_path])
        return (
            "Controllo mano attivato in un processo separato. Si aprira la finestra webcam.\n"
            "Gesti: indice alzato = muovi | pollice+indice vicini = click SX | "
            "indice+medio = click DX | mano aperta = scroll | pugno = drag.\n"
            "Premi Q nella finestra oppure di 'disattiva controllo mano' per fermare."
        )
    except Exception as e:
        return f"Errore durante l'avvio del controllo mano: {e}"

@tool
def disattiva_controllo_mano() -> str:
    """
    Disattiva il controllo del mouse con i gesti della mano.
    Usalo quando l'utente dice 'disattiva controllo mano', 'ferma hand mouse',
    'torna al mouse normale', 'hand mouse off'.
    """
    global _processo
    if _processo is None or _processo.poll() is not None:
        return "Il controllo mano non era attivo."
    
    try:
        _processo.terminate()
        _processo = None
        return "Controllo mano disattivato. Mouse torna al controllo normale."
    except Exception as e:
        return f"Errore durante la chiusura del controllo mano: {e}"