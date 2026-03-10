"""
automations/profilo_uscita.py — Profilo uscita/rientro automatico per IDIS.

Trigger uscita:
  - Keyword nel messaggio utente ("vado a", "esco", "sono fuori", ...)
  - Evento calendario con titolo che implica uscita
  - Orario routine appreso (uscita abituale)

Al trigger uscita:
  1. Briefing vocale (meteo + mail urgenti + prossimi eventi)
  2. Spegni LED + pausa Spotify
  3. Registra orario uscita nel learning engine
  4. Avvia timer rientro se specificato

Al rientro ("sono tornato", "rientro", timer scaduto):
  1. Riaccendi LED + riprendi Spotify
  2. Mostra mail arrivate durante assenza
  3. Recap agenda resto giornata
"""

import threading
import time
import datetime
import re

# ══════════════════════════════════════════════════════════════
# LOGGING STRUTTURATO
# ══════════════════════════════════════════════════════════════

def _log(tag: str, msg: str, t0: float = None):
    """
    Stampa log colorato nel terminale con timestamp e timer opzionale.
    Tag: USCITA | RIENTRO | BRIEFING | LED | SPOTIFY | MAIL | AGENDA | LEARNING | TIMER
    """
    adesso   = datetime.datetime.now().strftime("%H:%M:%S")
    elapsed  = f"  [{time.time()-t0:.2f}s]" if t0 is not None else ""

    # Colori ANSI per terminale
    COLORI = {
        "USCITA":    "\033[96m",   # cyan
        "RIENTRO":   "\033[92m",   # verde
        "BRIEFING":  "\033[93m",   # giallo
        "LED":       "\033[95m",   # magenta
        "SPOTIFY":   "\033[94m",   # blu
        "MAIL":      "\033[96m",   # cyan
        "AGENDA":    "\033[93m",   # giallo
        "LEARNING":  "\033[90m",   # grigio
        "TIMER":     "\033[91m",   # rosso
        "OK":        "\033[92m",   # verde
        "ERR":       "\033[91m",   # rosso
    }
    RESET = "\033[0m"
    colore = COLORI.get(tag, "\033[97m")
    print(f"{RESET}[{adesso}] {colore}[{tag}]{RESET} {msg}{elapsed}")


# ══════════════════════════════════════════════════════════════
# STATO
# ══════════════════════════════════════════════════════════════

_stato = {
    "fuori":            False,       # True = utente è fuori casa
    "ora_uscita":       None,        # datetime uscita
    "ora_rientro_prev": None,        # datetime rientro previsto (se specificato)
    "timer_rientro":    None,        # threading.Timer attivo
    "mail_ids_pre":     set(),       # ID mail al momento dell'uscita (per diff al rientro)
    "spotify_era_attivo": False,     # True se Spotify suonava prima dell'uscita
    "led_era_acceso":   False,       # True se LED era acceso prima dell'uscita
}

# Referenze iniettate da logica_chat
_llm_ref             = None
_ui_notify           = None   # fn(mittente, testo)
_tts_parla           = None   # fn(testo)
_js_callback         = None   # fn(func, payload)


# ══════════════════════════════════════════════════════════════
# KEYWORD DETECTION
# ══════════════════════════════════════════════════════════════

_KW_USCITA = [
    "vado a ", "esco", "sono fuori", "vado fuori", "sto uscendo",
    "vado in palestra", "vado al lavoro", "vado a fare", "vado a prendere",
    "vado in giro", "vado a cena", "vado a pranzo", "torno tra",
    "sarò fuori", "mi assento", "vado via", "esco di casa",
]

_KW_RIENTRO = [
    "sono tornato", "sono a casa", "sono rientrato", "rientro",
    "eccomi", "sono qui", "sono di ritorno", "torno ora",
]

# Pattern per estrarre durata: "torno tra 2 ore", "torno tra 30 minuti"
_RE_DURATA = re.compile(
    r"torno tra (\d+)\s*(ore?|minuti?|h\b|min\b)", re.IGNORECASE
)

# Pattern per orario esplicito: "torno alle 18", "torno alle 18:30"
_RE_ORARIO = re.compile(
    r"torno alle (\d{1,2})(?::(\d{2}))?", re.IGNORECASE
)


def rileva_intenzione(testo: str) -> str | None:
    """
    Analizza il testo e ritorna:
      'uscita'  — utente sta uscendo
      'rientro' — utente sta rientrando
      None      — nessuna intenzione rilevata
    """
    t = testo.lower().strip()
    if any(k in t for k in _KW_RIENTRO):
        return "rientro"
    if any(k in t for k in _KW_USCITA):
        return "uscita"
    return None


def _estrai_durata_minuti(testo: str) -> int | None:
    """Estrae durata in minuti da frasi tipo 'torno tra 2 ore'."""
    m = _RE_DURATA.search(testo.lower())
    if not m:
        return None
    valore = int(m.group(1))
    unita  = m.group(2).lower()
    if unita.startswith("or") or unita == "h":
        return valore * 60
    return valore   # minuti


def _estrai_orario_rientro(testo: str) -> datetime.datetime | None:
    """Estrae orario assoluto da 'torno alle 18:30'."""
    m = _RE_ORARIO.search(testo.lower())
    if not m:
        return None
    ora  = int(m.group(1))
    mins = int(m.group(2)) if m.group(2) else 0
    adesso = datetime.datetime.now()
    rientro = adesso.replace(hour=ora, minute=mins, second=0, microsecond=0)
    if rientro < adesso:
        rientro += datetime.timedelta(days=1)
    return rientro


# ══════════════════════════════════════════════════════════════
# PROFILO USCITA
# ══════════════════════════════════════════════════════════════

def esegui_profilo_uscita(testo: str):
    """
    Eseguito in thread quando viene rilevata un'uscita.
    testo: messaggio originale dell'utente (per estrarre durata/orario).
    """
    if _stato["fuori"]:
        _log("USCITA", "Già fuori — trigger ignorato.")
        return

    t0 = time.time()
    _log("USCITA", "━━━ PROFILO USCITA AVVIATO ━━━")
    _stato["fuori"]      = True
    _stato["ora_uscita"] = datetime.datetime.now()

    # Snapshot mail attuali per diff al rientro
    try:
        from automations.tools_mail import _ids_visti
        _stato["mail_ids_pre"] = set(_ids_visti)
        _log("USCITA", f"Snapshot mail: {len(_stato['mail_ids_pre'])} ID salvati.")
    except Exception:
        _stato["mail_ids_pre"] = set()

    _log("USCITA", "Avvio step paralleli: briefing + dispositivi + learning...")
    threading.Thread(target=_uscita_step_briefing,    daemon=True).start()
    threading.Thread(target=_uscita_step_dispositivi, daemon=True).start()
    threading.Thread(target=_uscita_step_learning,    daemon=True).start()

    # Timer rientro
    minuti = _estrai_durata_minuti(testo)
    if minuti:
        _stato["ora_rientro_prev"] = datetime.datetime.now() + datetime.timedelta(minutes=minuti)
        _log("TIMER", f"Rientro previsto tra {minuti} minuti ({_stato['ora_rientro_prev'].strftime('%H:%M')}).")
        _avvia_timer_rientro(minuti * 60)
    else:
        orario = _estrai_orario_rientro(testo)
        if orario:
            _stato["ora_rientro_prev"] = orario
            secondi = (orario - datetime.datetime.now()).total_seconds()
            if secondi > 0:
                _log("TIMER", f"Rientro previsto alle {orario.strftime('%H:%M')} ({int(secondi//60)} min).")
                _avvia_timer_rientro(int(secondi))

    _log("USCITA", "Trigger completato.", t0)


def _uscita_step_briefing():
    t0 = time.time()
    _log("BRIEFING", "Raccolta dati pre-uscita...")
    try:
        parti = []

        # 1. Meteo
        try:
            t1 = time.time()
            from actions.weather_report import mostra_meteo
            meteo = mostra_meteo.invoke({})
            if meteo and "Errore" not in meteo:
                prima_riga = meteo.split("\n")[0].strip()
                parti.append(prima_riga)
                _log("BRIEFING", f"Meteo: '{prima_riga}'", t1)
            else:
                _log("BRIEFING", "Meteo: nessun dato.")
        except Exception as e:
            _log("ERR", f"Meteo: {e}")

        # 2. Prossimi eventi calendario
        try:
            t1 = time.time()
            from actions.tools_calendar import leggi_calendario
            eventi = leggi_calendario.invoke({})
            _NESSUN_EVENTO = ["nessun evento", "no event", "non ci sono eventi",
                              "nessun appuntamento", "non ho trovato", "periodo richiesto"]
            ha_eventi = eventi and not any(k in eventi.lower() for k in _NESSUN_EVENTO)
            if ha_eventi:
                righe = [r.strip() for r in eventi.split("\n")
                         if r.strip() and not r.strip().startswith("Oggi") and len(r.strip()) > 5]
                if righe:
                    parti.append(f"Hai in agenda: {righe[0]}")
                    _log("BRIEFING", f"Calendario: '{righe[0]}'", t1)
            else:
                _log("BRIEFING", "Calendario: giornata libera.", t1)
        except Exception as e:
            _log("ERR", f"Calendario: {e}")

        # Costruisci messaggio naturale
        if parti:
            briefing = "Prima di uscire: " + ". ".join(parti) + "."
        else:
            briefing = "Buona uscita! Ci vediamo al rientro."

        if _stato.get("ora_rientro_prev"):
            ora_str = _stato["ora_rientro_prev"].strftime("%H:%M")
            briefing += f" Ti aspetto per le {ora_str}."

        _log("BRIEFING", f"→ '{briefing}'")
        _parla(briefing)
        _notifica("🚪 USCITA", briefing)
        _log("BRIEFING", "Completato.", t0)

    except Exception as e:
        _log("ERR", f"Briefing: {e}")


def _uscita_step_dispositivi():
    time.sleep(1)
    try:
        t1 = time.time()
        from actions.tools_arduino import get_stato_led, controlla_led
        stato_led = get_stato_led()
        _stato["led_era_acceso"] = stato_led not in ("off", "spento", "SPENTO", "", None)
        if _stato["led_era_acceso"]:
            controlla_led.invoke({"comando": "off"})
            _log("LED", f"Spento (era: {stato_led}).", t1)
        else:
            _log("LED", f"Già spento — nessuna azione.")
    except Exception as e:
        _log("ERR", f"LED uscita: {e}")

    try:
        t1 = time.time()
        from actions.tools_spotify import controlla_spotify, cosa_sta_suonando
        info = cosa_sta_suonando.invoke({})
        _stato["spotify_era_attivo"] = bool(info and "niente" not in info.lower() and "errore" not in info.lower())
        if _stato["spotify_era_attivo"]:
            controlla_spotify.invoke({"azione": "pausa"})
            _log("SPOTIFY", "Messo in pausa.", t1)
        else:
            _log("SPOTIFY", "Non era attivo — nessuna azione.")
    except Exception as e:
        _log("ERR", f"Spotify uscita: {e}")


def _uscita_step_learning():
    t1 = time.time()
    try:
        from automations.tools_routine_learning import rileva_e_registra
        rileva_e_registra("sto uscendo")
        _log("LEARNING", "Orario uscita registrato.", t1)
    except Exception as e:
        _log("ERR", f"Learning uscita: {e}")


# ══════════════════════════════════════════════════════════════
# TIMER RIENTRO
# ══════════════════════════════════════════════════════════════

def _avvia_timer_rientro(secondi: int):
    """Avvia un timer che scatta al rientro previsto."""
    if _stato["timer_rientro"]:
        _stato["timer_rientro"].cancel()

    _log("TIMER", f"Rientro atteso tra {secondi//60} min.")
    t = threading.Timer(secondi, _timer_rientro_scaduto)
    t.daemon = True
    t.start()
    _stato["timer_rientro"] = t


def _timer_rientro_scaduto():
    """Chiamato quando scade il timer rientro stimato."""
    if not _stato["fuori"]:
        _log("TIMER", "Timer scaduto ma già rientrato — ignorato.")
        return
    _log("TIMER", "Timer rientro scaduto — invio promemoria.")
    _parla("Sei rientrato? Quando sei pronto, dimmi che sei a casa.")
    _notifica("⏰ TIMER RIENTRO", "È l'ora del rientro prevista. Di' 'sono tornato' quando sei a casa.")


# ══════════════════════════════════════════════════════════════
# PROFILO RIENTRO
# ══════════════════════════════════════════════════════════════

def esegui_profilo_rientro():
    """
    Eseguito in thread quando viene rilevato un rientro.
    """
    if not _stato["fuori"]:
        return  # non era uscito

    # Cancella eventuale timer pendente
    if _stato["timer_rientro"]:
        _stato["timer_rientro"].cancel()
        _stato["timer_rientro"] = None

    _stato["fuori"] = False
    ora_rientro     = datetime.datetime.now()

    # Calcola durata assenza
    durata_str = ""
    if _stato["ora_uscita"]:
        delta   = ora_rientro - _stato["ora_uscita"]
        minuti  = int(delta.total_seconds() // 60)
        if minuti >= 60:
            durata_str = f"{minuti//60}h {minuti%60}min"
        else:
            durata_str = f"{minuti} minuti"

    threading.Thread(target=_rientro_step_benvenuto,   args=(durata_str,), daemon=True).start()
    threading.Thread(target=_rientro_step_dispositivi, daemon=True).start()
    threading.Thread(target=_rientro_step_mail,        daemon=True).start()
    threading.Thread(target=_rientro_step_agenda,      daemon=True).start()
    threading.Thread(target=_rientro_step_learning,    daemon=True).start()


def _rientro_step_benvenuto(durata_str: str):
    t1 = time.time()
    try:
        if durata_str:
            msg = f"Bentornato! Sei stato fuori {durata_str}."
        else:
            msg = "Bentornato a casa!"
        _log("RIENTRO", f"→ '{msg}'")
        _parla(msg)
        _notifica("🏠 RIENTRO", msg)
        _log("RIENTRO", "Benvenuto completato.", t1)
    except Exception as e:
        _log("ERR", f"Benvenuto: {e}")


def _rientro_step_dispositivi():
    time.sleep(2)
    try:
        t1 = time.time()
        from actions.tools_arduino import controlla_led
        if _stato["led_era_acceso"]:
            controlla_led.invoke({"comando": "on"})
            _log("LED", "Riacceso.", t1)
        else:
            _log("LED", "Era spento prima dell'uscita — nessuna azione.")
    except Exception as e:
        _log("ERR", f"LED rientro: {e}")

    try:
        t1 = time.time()
        from actions.tools_spotify import controlla_spotify
        if _stato["spotify_era_attivo"]:
            controlla_spotify.invoke({"azione": "play"})
            _log("SPOTIFY", "Ripreso.", t1)
        else:
            _log("SPOTIFY", "Non era attivo prima dell'uscita — nessuna azione.")
    except Exception as e:
        _log("ERR", f"Spotify rientro: {e}")


def _rientro_step_mail():
    """Mostra mail arrivate durante l'assenza."""
    time.sleep(3)
    try:
        from automations.tools_mail import ottieni_servizio_gmail, _filtro_locale, _decodifica_body, classifica_mail_con_llm
        service = ottieni_servizio_gmail()

        risultati = service.users().messages().list(
            userId='me', labelIds=['INBOX', 'UNREAD'], maxResults=20
        ).execute()
        messaggi = risultati.get('messages', [])
        ids_nuovi = {m['id'] for m in messaggi} - _stato["mail_ids_pre"]

        if not ids_nuovi:
            _log("MAIL", "Nessuna nuova mail durante l'assenza.")
            return

        # Fetch e filtra
        mail_nuove = []
        for msg_id in ids_nuovi:
            try:
                meta    = service.users().messages().get(
                    userId='me', id=msg_id, format='metadata',
                    metadataHeaders=['From', 'Subject', 'Date']
                ).execute()
                headers = {h['name']: h['value'] for h in meta.get('payload', {}).get('headers', [])}
                oggetto = headers.get('Subject', '')
                mittente= headers.get('From', '')
                if _filtro_locale(oggetto, mittente) == 'spam':
                    continue
                det   = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
                corpo = _decodifica_body(det['payload'])
                mail_nuove.append({
                    'id': msg_id, 'mittente': mittente,
                    'oggetto': oggetto, 'data': headers.get('Date', ''),
                    'corpo': corpo, 'pre_rilevante': True,
                })
            except Exception:
                pass

        if not mail_nuove:
            return

        classificate = classifica_mail_con_llm(mail_nuove, _llm_ref) if _llm_ref else []
        if not classificate:
            return

        righe = [f"{m.get('emoji','📧')} {m['riassunto']}" for m in classificate]
        msg   = f"Durante la tua assenza sono arrivate {len(classificate)} mail importanti:\n" + "\n".join(righe)
        _notifica("📬 MAIL ASSENZA", msg)
        _parla(f"Hai ricevuto {len(classificate)} mail importanti mentre eri fuori.")

        # Aggiorna dashboard
        if _js_callback:
            payload = [
                {"emoji": m.get("emoji","📧"), "oggetto": m.get("oggetto",""),
                 "riassunto": m.get("riassunto",""), "isNew": True}
                for m in classificate
            ]
            _js_callback("aggiornaMail", payload)

    except Exception as e:
        _log("ERR", f"Rientro mail: {e}")


def _rientro_step_agenda():
    """Recap agenda per il resto della giornata."""
    time.sleep(4)
    try:
        from actions.tools_calendar import leggi_calendario
        eventi = leggi_calendario.invoke({})
        if not eventi or "nessun evento" in eventi.lower():
            return

        adesso = datetime.datetime.now()
        # Filtra solo eventi futuri
        righe_future = []
        for riga in eventi.split("\n"):
            m = re.search(r'(\d{1,2}):(\d{2})', riga)
            if m:
                h, mins = int(m.group(1)), int(m.group(2))
                if h > adesso.hour or (h == adesso.hour and mins > adesso.minute):
                    righe_future.append(riga.strip())

        if righe_future:
            msg = "Per il resto della giornata hai: " + "; ".join(righe_future[:3])
            _notifica("📅 AGENDA", msg)
            _parla(f"Oggi hai ancora {len(righe_future)} impegni.")
    except Exception as e:
        _log("ERR", f"Agenda: {e}")


def _rientro_step_learning():
    """Registra orario rientro nel learning engine."""
    try:
        from automations.tools_routine_learning import rileva_e_registra
        rileva_e_registra("sono tornato a casa")
        _log("LEARNING", "Orario rientro registrato.")
    except Exception as e:
        _log("ERR", f"Learning rientro: {e}")


# ══════════════════════════════════════════════════════════════
# RILEVAMENTO DA CALENDARIO
# ══════════════════════════════════════════════════════════════

# Parole negli eventi calendario che indicano uscita
_KW_EVENTI_USCITA = [
    "palestra", "gym", "lavoro", "ufficio", "scuola", "università",
    "appuntamento", "visita", "medico", "dentista", "cena fuori",
    "pranzo fuori", "spesa", "supermercato", "uscita", "viaggio",
]

def controlla_calendario_uscita(eventi_testo: str) -> bool:
    """
    Analizza il testo degli eventi calendario e ritorna True
    se c'è un evento imminente (entro 15 min) che implica uscita.
    """
    if not eventi_testo:
        return False
    t_lower = eventi_testo.lower()
    if not any(k in t_lower for k in _KW_EVENTI_USCITA):
        return False

    adesso = datetime.datetime.now()
    for riga in eventi_testo.split("\n"):
        m = re.search(r'(\d{1,2}):(\d{2})', riga)
        if not m:
            continue
        h, mins = int(m.group(1)), int(m.group(2))
        evento_dt = adesso.replace(hour=h, minute=mins, second=0)
        delta_min = (evento_dt - adesso).total_seconds() / 60
        # Evento tra 0 e 15 minuti con keyword uscita
        if 0 <= delta_min <= 15:
            if any(k in riga.lower() for k in _KW_EVENTI_USCITA):
                return True
    return False


# ══════════════════════════════════════════════════════════════
# API PUBBLICA
# ══════════════════════════════════════════════════════════════

def inizializza(llm, ui_notify, tts_parla, js_callback=None):
    """
    Chiamato da logica_chat all'avvio.
    llm:        istanza ChatOllama
    ui_notify:  fn(mittente, testo) — aggiungi_messaggio in chat
    tts_parla:  fn(testo) — tools_tts.parla
    js_callback fn(func, payload) — chiama JS in dashboard
    """
    global _llm_ref, _ui_notify, _tts_parla, _js_callback
    _llm_ref    = llm
    _ui_notify  = ui_notify
    _tts_parla  = tts_parla
    _js_callback = js_callback
    _log("OK", "Profilo uscita inizializzato.")


def gestisci_messaggio(testo: str) -> bool:
    """
    Chiamato da elabora_risposta() per ogni messaggio utente.
    Ritorna True se ha gestito un'uscita/rientro (così logica_chat può
    decidere se aggiungere un commento o ignorare).
    """
    intenzione = rileva_intenzione(testo)
    if intenzione == "uscita":
        _log("USCITA", f"Keyword rilevata: '{testo[:50]}'")
        threading.Thread(target=esegui_profilo_uscita, args=(testo,), daemon=True).start()
        return True
    elif intenzione == "rientro":
        _log("RIENTRO", f"Keyword rilevata: '{testo[:50]}'")
        threading.Thread(target=esegui_profilo_rientro, daemon=True).start()
        return True
    return False


def stato_corrente() -> dict:
    """Ritorna lo stato attuale (per debug o dashboard)."""
    return {
        "fuori":            _stato["fuori"],
        "ora_uscita":       _stato["ora_uscita"].isoformat() if _stato["ora_uscita"] else None,
        "ora_rientro_prev": _stato["ora_rientro_prev"].isoformat() if _stato["ora_rientro_prev"] else None,
    }


# ══════════════════════════════════════════════════════════════
# HELPER INTERNI
# ══════════════════════════════════════════════════════════════

def _parla(testo: str):
    if _tts_parla:
        try: _tts_parla(testo)
        except Exception as e: _log("ERR", f"TTS: {e}")

def _notifica(mittente: str, testo: str):
    if _ui_notify:
        try: _ui_notify(mittente, testo)
        except Exception as e: _log("ERR", f"Notify: {e}")