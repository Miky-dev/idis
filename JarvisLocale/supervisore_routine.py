"""
supervisore_routine.py — Supervisore proattivo di IDIS.
Gira in background ogni 60 secondi e:
  1. Controlla le routine in routine_config.json — avvisa se un task coincide con l'orario attuale
  2. Controlla il calendario — avvisa 15 minuti prima di un evento con un consiglio generato dall'LLM
"""

import datetime
import threading
import time
import json
import winsound
import os

# ── Stato interno ─────────────────────────────────────────────
_routine_gia_notificate = set()   # "HH:MM|task" — evita doppie notifiche nella stessa ora
_eventi_gia_notificati  = set()   # titolo evento — evita doppio avviso per lo stesso evento

# ── Riferimento ai callback UI e all'LLM (impostati da logica_chat.py) ───
_ui_callbacks = None
_llm           = None


def inizializza(ui_callbacks: dict, llm):
    """
    Chiamato da logica_chat.avvia_background() per passare i riferimenti
    alla UI e al modello LLM.
    """
    global _ui_callbacks, _llm
    _ui_callbacks = ui_callbacks
    _llm          = llm


# ══════════════════════════════════════════════════════════════
# NOTIFICA
# ══════════════════════════════════════════════════════════════

def _notifica(testo: str):
    """Manda un messaggio nella chat di IDIS e suona un beep."""
    try:
        winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS)
    except Exception:
        pass
    if _ui_callbacks and "aggiungi_messaggio" in _ui_callbacks:
        _ui_callbacks["aggiungi_messaggio"]("🔔 IDIS", testo, "lightyellow")


# ══════════════════════════════════════════════════════════════
# CONTROLLO ROUTINE
# ══════════════════════════════════════════════════════════════

def _controlla_routine():
    """Controlla se l'orario attuale corrisponde a una routine configurata."""
    from tools_routine import _carica_routine

    adesso = datetime.datetime.now()
    ora_attuale = adesso.strftime("%H:%M")
    giorno = adesso.weekday()  # 0=lun … 6=dom

    data = _carica_routine()
    for r in data.get("routine", []):
        if r.get("orario") != ora_attuale:
            continue

        # Controlla giorni
        giorni = r.get("giorni", "tutti").lower()
        if giorni not in ("tutti", "every day"):
            if giorni == "lun-ven" and giorno >= 5:
                continue
            if giorni == "weekend" and giorno < 5:
                continue

        chiave = f"{ora_attuale}|{r['task']}"
        if chiave in _routine_gia_notificate:
            continue

        _routine_gia_notificate.add(chiave)
        _notifica(f"Routine — {r['task']}")

    # Pulizia chiavi vecchie (ora diversa)
    da_rimuovere = {c for c in _routine_gia_notificate if not c.startswith(ora_attuale)}
    _routine_gia_notificate.difference_update(da_rimuovere)


# ══════════════════════════════════════════════════════════════
# CONTROLLO CALENDARIO
# ══════════════════════════════════════════════════════════════

def _genera_consiglio_llm(titolo_evento: str) -> str:
    """
    Chiede all'LLM un brevissimo consiglio su come prepararsi all'evento.
    Usa invoke() diretto — niente streaming, niente tool call.
    """
    if _llm is None:
        return ""
    try:
        from langchain_core.messages import SystemMessage, HumanMessage
        prompt = [
            SystemMessage(content="/no_think\nSei IDIS. Rispondi in UNA sola frase breve in italiano. Niente emoji."),
            HumanMessage(content=f"L'utente ha '{titolo_evento}' tra 15 minuti. Dai un consiglio pratico brevissimo su cosa preparare.")
        ]
        risposta = _llm.invoke(prompt)
        testo = risposta.content
        if isinstance(testo, list):
            testo = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in testo)
        return testo.strip()
    except Exception as e:
        return ""


def _controlla_calendario():
    """Controlla se c'è un evento che inizia tra ~15 minuti e invia un avviso con consiglio LLM."""
    try:
        from tools_calendar import ottieni_servizio_calendario
        import datetime

        adesso = datetime.datetime.now()
        tra_14 = adesso + datetime.timedelta(minutes=14)
        tra_16 = adesso + datetime.timedelta(minutes=16)

        service = ottieni_servizio_calendario()
        result = service.events().list(
            calendarId="primary",
            timeMin=tra_14.isoformat() + "Z",
            timeMax=tra_16.isoformat() + "Z",
            singleEvents=True,
            orderBy="startTime"
        ).execute()

        for event in result.get("items", []):
            titolo = event.get("summary", "Evento senza titolo")
            if titolo in _eventi_gia_notificati:
                continue

            _eventi_gia_notificati.add(titolo)

            # Genera consiglio in thread separato per non bloccare il supervisore
            def _invia_avviso(t=titolo):
                consiglio = _genera_consiglio_llm(t)
                msg = f"Tra 15 minuti: {t}."
                if consiglio:
                    msg += f"\n{consiglio}"
                _notifica(msg)

            threading.Thread(target=_invia_avviso, daemon=True).start()

    except Exception:
        pass  # Calendario non disponibile (offline, token scaduto, ecc.)


# ══════════════════════════════════════════════════════════════
# LOOP PRINCIPALE
# ══════════════════════════════════════════════════════════════

def _loop():
    """Loop infinito — gira ogni 60 secondi."""
    # Aspetta 10s dopo l'avvio per dare tempo al warmup
    time.sleep(10)
    while True:
        try:
            _controlla_routine()
            _controlla_calendario()
        except Exception:
            pass
        time.sleep(60)


def avvia():
    """Avvia il supervisore in un thread daemon. Chiamato da logica_chat.avvia_background()."""
    threading.Thread(target=_loop, daemon=True, name="SupervisoreRoutine").start()
    print("👁️  Supervisore routine avviato.")