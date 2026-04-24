"""
desktop_app.py — Entry point IDIS con PyWebView.
Avvia la logica backend e la finestra dashboard HTML.
"""

import threading
from agents.logica_chat import avvia_background
from ui_webview import avvia_ui

'''llm = ChatOllama(
    model=model_local,
    num_ctx=4096,           # limita il context window
    extra_body={"thinking": False}  # disabilita thinking mode
)'''

if __name__ == "__main__":
    # Avvia warmup Ollama, calendario, posizione GPS in background
    avvia_background()

    # Avvia la finestra PyWebView (bloccante — deve stare nel main thread)
    avvia_ui()