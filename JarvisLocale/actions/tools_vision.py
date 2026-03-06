"""
tools_vision.py — Visione con webcam per IDIS.
Scatta una foto dalla webcam e la manda a Qwen3.5 (multimodale) per l'analisi.
Non è un tool LangChain — viene gestito direttamente in logica_chat.py
prima di passare all'LLM, aggiungendo l'immagine come contenuto del messaggio.
"""

import cv2
import base64
import datetime
import os
import tempfile


def scatta_foto(indice_camera: int = 0) -> str | None:
    """
    Apre la webcam, scatta un frame e lo salva come JPEG temporaneo.
    Ritorna il path del file, o None se fallisce.
    """
    cap = cv2.VideoCapture(indice_camera)
    if not cap.isOpened():
        # Prova indice 1 se 0 fallisce (es. webcam esterna)
        cap = cv2.VideoCapture(1)
        if not cap.isOpened():
            return None

    # Aspetta 2 frame per dare tempo all'auto-esposizione di stabilizzarsi
    for _ in range(3):
        ret, frame = cap.read()

    cap.release()

    if not ret or frame is None:
        return None

    # Salva in file temporaneo
    path = os.path.join(tempfile.gettempdir(), f"idis_vision_{datetime.datetime.now().strftime('%H%M%S')}.jpg")
    cv2.imwrite(path, frame)
    return path


def immagine_a_base64(path: str) -> str:
    """Converte un file immagine in stringa base64."""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def analizza_con_ollama(domanda: str, model_local: str, base64_img: str) -> str:
    """
    Chiama Ollama direttamente via HTTP con l'immagine base64.
    Usa /api/chat con il campo 'images' — supportato da Qwen3.5 e LLaVA.
    """
    import requests

    payload = {
        "model": model_local,
        "stream": False,
        "think": False,
        "messages": [
            {
                "role": "user",
                "content": domanda,
                "images": [base64_img]
            }
        ],
        "options": {
            "num_predict": 300,
            "temperature": 0.2
        }
    }

    try:
        resp = requests.post(
            "http://localhost:11434/api/chat",
            json=payload,
            timeout=60
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("message", {}).get("content", "Nessuna risposta dal modello.")
    except requests.exceptions.Timeout:
        return "Timeout: il modello ha impiegato troppo tempo ad analizzare l'immagine."
    except Exception as e:
        return f"Errore durante l'analisi visiva: {str(e)}"


def esegui_visione(domanda: str, model_local: str) -> str:
    """
    Funzione principale chiamata da logica_chat.py.
    Scatta, converte e analizza in un unico passaggio.
    Ritorna la risposta testuale di Qwen3.5.
    """
    path = scatta_foto()
    if path is None:
        return "Nessuna webcam trovata o accessibile. Controlla che la fotocamera sia collegata e non occupata da un'altra app."

    try:
        b64 = immagine_a_base64(path)
        risposta = analizza_con_ollama(domanda, model_local, b64)
        return risposta
    finally:
        # Rimuovi il file temporaneo
        try:
            os.remove(path)
        except Exception:
            pass