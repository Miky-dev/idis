"""
supervisore_routine.py — Supervisore proattivo di IDIS (ottimizzato).

Miglioramenti rispetto alla versione precedente:
  - Loop temporizzato preciso (sleep adattivo, no deriva)
  - Cache routine in memoria con invalidazione su modifica file
  - Correzione datetime UTC per Google Calendar API
  - Timeout su thread LLM (max 15s) — evita accumulo thread
  - Guard eccezioni granulari con log strutturato
  - Stato mail: pausa post-messaggio, pausa avvio, no run paralleli
  - Token refresh sicuro nel thread background
  - winsound asincrono (SND_ASYNC) — non blocca il loop
"""

import datetime
import threading
import time
import json
import os

try:
    import winsound
    _HAS_WINSOUND = True
except ImportError:
    _HAS_WINSOUND = False

# ── Logging interno leggero ───────────────────────────────────
def _log(tag: str, msg: str):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}][SUP/{tag}] {msg}")


# ══════════════════════════════════════════════════════════════
# STATO INTERNO
# ══════════════════════════════════════════════════════════════

_routine_gia_notificate = set()
_eventi_gia_notificati  = set()

_ui_callbacks = None
_llm           = None

# Cache routine — ricaricata solo se il file cambia
_routine_cache       = None
_routine_cache_mtime = 0.0

# Stato mail / Inattività
_ultimo_messaggio_utente = time.time()
_avvio_app               = time.time()
_ultimo_check_mail       = 0.0
_mail_in_attesa_conferma  = []
_check_mail_in_corso      = False
_learning_in_attesa       = {}   # chiave → messaggio proposta routine learning

INTERVALLO_MAIL = 3600   # 1 ora
PAUSA_DOPO_MSG  = 300    # 5 min di silenzio dopo l'ultimo messaggio
PAUSA_AVVIO     = 60    # 1 min dopo avvio prima del primo check
#PAUSA_AVVIO     = 600    # 10 min dopo avvio prima del primo check
LLM_TIMEOUT     = 15     # secondi max per risposta LLM consiglio evento


# ══════════════════════════════════════════════════════════════
# API PUBBLICA
# ══════════════════════════════════════════════════════════════

def inizializza(ui_callbacks: dict, llm, js_callback=None):
    """Chiamato da logica_chat.avvia_background()."""
    global _ui_callbacks, _llm, _js_callback
    _ui_callbacks = ui_callbacks
    _llm          = llm
    _js_callback  = js_callback


def aggiorna_ultimo_messaggio():
    """Chiamato da logica_chat.elabora_risposta() ad ogni messaggio utente."""
    global _ultimo_messaggio_utente
    _ultimo_messaggio_utente = time.time()


def gestisci_conferma_learning(testo_lower: str) -> bool:
    """
    Intercetta sì/no per aggiunta routine imparata al routine_config.json.
    Chiamato da logica_chat prima di passare all'LLM.
    """
    global _learning_in_attesa
    if not _learning_in_attesa:
        return False

    si = testo_lower.strip() in ("sì","si","yes","ok","aggiungi","confermo","certo","vai")
    no = testo_lower.strip() in ("no","annulla","non aggiungere","skip","lascia perdere")
    if not si and not no:
        return False

    if si:
        try:
            from automations.tools_routine_learning import conferma_aggiunta_routine
            for chiave in list(_learning_in_attesa.keys()):
                conferma_aggiunta_routine(chiave)
            _notifica("Routine aggiunta con successo.")
        except Exception as e:
            _notifica(f"Errore aggiunta routine: {e}")
    else:
        _notifica("Ok, continuerò solo ad osservare.")

    _learning_in_attesa = {}
    return True


def gestisci_conferma_mail(testo_lower: str) -> bool:
    """
    Intercetta sì/no per aggiunta eventi al calendario da mail.
    Ritorna True se gestito qui (logica_chat non deve passare all'LLM).
    """
    global _mail_in_attesa_conferma
    if not _mail_in_attesa_conferma:
        return False

    si = testo_lower.strip() in ("sì","si","yes","ok","aggiungi","confermo","certo","vai")
    no = testo_lower.strip() in ("no","annulla","non aggiungere","skip","lascia perdere")

    if not si and not no:
        return False

    if si:
        _aggiungi_eventi_calendario(_mail_in_attesa_conferma)
    else:
        _notifica("Ok, non aggiungo nulla al calendario.")

    _mail_in_attesa_conferma = []
    return True


# ══════════════════════════════════════════════════════════════
# NOTIFICA
# ══════════════════════════════════════════════════════════════

def _notifica(testo: str):
    """Manda un messaggio in chat e beep asincrono (non blocca il loop)."""
    if _HAS_WINSOUND:
        try:
            winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
        except Exception:
            pass
    if _ui_callbacks and "aggiungi_messaggio" in _ui_callbacks:
        try:
            _ui_callbacks["aggiungi_messaggio"]("🔔 IDIS", testo)
        except Exception as e:
            _log("NOTIFICA", f"Errore callback UI: {e}")


# ══════════════════════════════════════════════════════════════
# CACHE ROUTINE
# ══════════════════════════════════════════════════════════════

def _get_routine() -> list:
    """Lista routine dalla cache — ricarica da disco solo se il file è cambiato."""
    global _routine_cache, _routine_cache_mtime
    try:
        from tools_routine import ROUTINE_PATH, _carica_routine
        mtime = os.path.getmtime(ROUTINE_PATH) if os.path.exists(ROUTINE_PATH) else 0.0
        if _routine_cache is None or mtime != _routine_cache_mtime:
            _routine_cache       = _carica_routine().get("routine", [])
            _routine_cache_mtime = mtime
            _log("ROUTINE", f"Cache aggiornata — {len(_routine_cache)} voci.")
    except Exception as e:
        _log("ROUTINE", f"Errore caricamento: {e}")
        if _routine_cache is None:
            _routine_cache = []
    return _routine_cache


# ══════════════════════════════════════════════════════════════
# CONTROLLO ROUTINE
# ══════════════════════════════════════════════════════════════

def _controlla_routine():
    adesso      = datetime.datetime.now()
    ora_attuale = adesso.strftime("%H:%M")
    giorno      = adesso.weekday()

    for r in _get_routine():
        if r.get("orario") != ora_attuale:
            continue
        giorni = r.get("giorni", "tutti").lower()
        if giorni == "lun-ven" and giorno >= 5:
            continue
        if giorni == "weekend" and giorno < 5:
            continue
        chiave = f"{ora_attuale}|{r['task']}"
        if chiave in _routine_gia_notificate:
            continue
        _routine_gia_notificate.add(chiave)
        _notifica(f"Routine — {r['task']}")
        _log("ROUTINE", f"Notificato: {r['task']}")

    vecchie = {c for c in _routine_gia_notificate if not c.startswith(ora_attuale)}
    _routine_gia_notificate.difference_update(vecchie)


# ══════════════════════════════════════════════════════════════
# CONTROLLO CALENDARIO
# ══════════════════════════════════════════════════════════════

def _genera_consiglio_llm(titolo_evento: str) -> str:
    """Consiglio LLM con timeout — non blocca mai il supervisore."""
    if _llm is None:
        return ""

    risultato = [None]

    def _chiedi():
        try:
            from langchain_core.messages import SystemMessage, HumanMessage
            prompt = [
                SystemMessage(content="/no_think\nSei IDIS. Rispondi in UNA sola frase breve in italiano. Niente emoji."),
                HumanMessage(content=f"L'utente ha '{titolo_evento}' tra 15 minuti. Dai un consiglio pratico brevissimo.")
            ]
            risposta = _llm.invoke(prompt)
            testo = risposta.content
            if isinstance(testo, list):
                testo = "".join(p.get("text","") if isinstance(p,dict) else str(p) for p in testo)
            risultato[0] = testo.strip()
        except Exception as e:
            _log("CALENDARIO", f"Errore LLM: {e}")

    t = threading.Thread(target=_chiedi, daemon=True)
    t.start()
    t.join(timeout=LLM_TIMEOUT)
    if t.is_alive():
        _log("CALENDARIO", f"Timeout LLM per '{titolo_evento}'")
        return ""
    return risultato[0] or ""


def _controlla_calendario():
    """Avviso 15 min prima di un evento e 30 min prima se richiede uscita. Usa UTC corretto per Google API."""
    try:
        from actions.tools_calendar import ottieni_servizio_calendario
        from automations.profilo_uscita import _KW_EVENTI_USCITA, _parla
        import urllib.parse
        import requests

        adesso_utc = datetime.datetime.utcnow()
        
        # Finestra 15 minuti standard
        tra_14     = adesso_utc + datetime.timedelta(minutes=14)
        tra_16     = adesso_utc + datetime.timedelta(minutes=16)

        # Finestra 30 minuti (pre-uscita abbigliamento)
        tra_29     = adesso_utc + datetime.timedelta(minutes=29)
        tra_31     = adesso_utc + datetime.timedelta(minutes=31)

        service = ottieni_servizio_calendario()
        
        # Controlliamo eventi tra 14 e 31 minuti da ora per prendere entrambe le finestre
        result  = service.events().list(
            calendarId   = "primary",
            timeMin      = tra_14.isoformat() + "Z",
            timeMax      = tra_31.isoformat() + "Z",
            singleEvents = True,
            orderBy      = "startTime"
        ).execute()

        for event in result.get("items", []):
            titolo = event.get("summary", "Evento senza titolo")
            inizio_str = event.get("start", {}).get("dateTime")
            if not inizio_str:
                 continue
                 
            # Calcolo esatto minuti mancanti
            inizio_dt = datetime.datetime.fromisoformat(inizio_str.replace('Z', '+00:00'))
            minuti_mancanti = int((inizio_dt - datetime.datetime.now(datetime.timezone.utc)).total_seconds() / 60)

            # --- AVVISO 15 MINUTI STANDARD ---
            if 14 <= minuti_mancanti <= 16:
                if titolo not in _eventi_gia_notificati:
                    _eventi_gia_notificati.add(titolo)
                    def _invia(t=titolo):
                        consiglio = _genera_consiglio_llm(t)
                        msg = f"Tra 15 minuti: {t}."
                        if consiglio:
                            msg += f"\n{consiglio}"
                        _notifica(msg)
                        _log("CALENDARIO", f"Avviso 15m: {t}")
                    threading.Thread(target=_invia, daemon=True).start()

            # --- AVVISO 30 MINUTI PRE-USCITA (METEO & ABBIGLIAMENTO) ---
            elif 29 <= minuti_mancanti <= 31:
                chiave_30 = f"{titolo}_30m"
                if chiave_30 not in _eventi_gia_notificati:
                    _eventi_gia_notificati.add(chiave_30)
                    
                    # Controlla se è un evento che richiede l'uscita
                    t_lower = titolo.lower()
                    if any(k in t_lower for k in _KW_EVENTI_USCITA):
                        def _invia_30m(t=titolo):
                            _log("CALENDARIO", f"Avviso 30m uscita rilevato: {t}")
                            try:
                                import actions.tools_location as tl
                                city = tl.posizione_cache.split(',')[0].strip() if "," in tl.posizione_cache else tl.posizione_cache.strip()
                                city_param = urllib.parse.quote(city) if city and "Sconosciuta" not in city else ""
                                res = requests.get(f"http://wttr.in/{city_param}?format=j1", timeout=5).json()
                                curr = res['current_condition'][0]
                                desc = curr['lang_it'][0]['value'] if 'lang_it' in curr else curr['weatherDesc'][0]['value']
                                temp = curr['temp_C']
                                meteo_str = f"{temp}°C e {desc}"
                                
                                prompt = (
                                    f"Tra mezz'ora l'utente stringerà un impegno chiamato '{t}'. "
                                    f"Fuori ci sono {meteo_str}. "
                                    "Formula una sola frase di avviso cordiale. Digli che è ora di prepararsi, riassumi il meteo e "*
                                    "suggerisci cosa indossare in base alla temperatura."
                                )
                                from langchain_core.messages import SystemMessage, HumanMessage
                                msg_vocale = f"Tra mezz'ora hai l'impegno: {t}. Fuori ci sono {meteo_str}."
                                
                                if _llm:
                                    risposta = _llm.invoke([
                                        SystemMessage(content="/no_think\nSei IDIS. Rispondi con UNA frase in italiano naturale e parlata. Niente emoji, asterischi o formattazioni. Parla all'utente."),
                                        HumanMessage(content=prompt)
                                    ])
                                    if risposta and risposta.content:
                                        testo = risposta.content
                                        msg_vocale = "".join(p.get("text","") if isinstance(p,dict) else str(p) for p in testo) if isinstance(testo, list) else str(testo)
                                        
                                _notifica(f"👔 Suggerimento pre-uscita per: {t}")
                                _parla(msg_vocale)
                            except Exception as e:
                                _log("CALENDARIO", f"Errore 30m: {e}")
                                
                        threading.Thread(target=_invia_30m, daemon=True).start()

    except Exception as e:
        _log("CALENDARIO", f"Errore: {e}")


# ══════════════════════════════════════════════════════════════
# CONTROLLO MAIL
# ══════════════════════════════════════════════════════════════

def _controlla_mail():
    """Controlla inbox ogni ora con tutte le guard di timing."""
    global _ultimo_check_mail, _check_mail_in_corso, _mail_in_attesa_conferma

    if _llm is None or _ui_callbacks is None:
        return

    adesso = time.time()
    if _check_mail_in_corso:                               return
    if adesso - _avvio_app < PAUSA_AVVIO:                  return
    if adesso - _ultimo_messaggio_utente < PAUSA_DOPO_MSG: return
    if adesso - _ultimo_check_mail < INTERVALLO_MAIL:      return

    _check_mail_in_corso = True
    _ultimo_check_mail   = adesso

    def _esegui():
        global _check_mail_in_corso, _mail_in_attesa_conferma
        try:
            from automations.tools_mail import fetch_mail_recenti, classifica_mail_con_llm, segna_come_lette
            _log("MAIL", "Avvio controllo inbox...")

            mail_list = fetch_mail_recenti(max_mail=10)
            if not mail_list:
                _log("MAIL", "Nessuna mail non letta.")
                return

            # Thinking attivo — NO /no_think per qualità classificazione
            classificate = classifica_mail_con_llm(mail_list, _llm)

            if not classificate:
                _log("MAIL", f"{len(mail_list)} mail — nessuna rilevante.")
                segna_come_lette([m["id"] for m in mail_list])
                return

            righe           = []
            eventi_con_data = []
            for m in classificate:
                righe.append(f"{m.get('emoji','📧')} {m['riassunto']}")
                if m.get("ha_data") and m.get("titolo_evento") and m.get("data_estratta"):
                    eventi_con_data.append(m)

            msg = f"Ho controllato la tua inbox — {len(classificate)} mail importanti:\n"
            msg += "\n".join(righe)

            if eventi_con_data:
                _mail_in_attesa_conferma = eventi_con_data
                titoli = ", ".join(
                    f"'{e['titolo_evento']}' ({e['data_estratta']})"
                    for e in eventi_con_data
                )
                msg += f"\n\nVuoi che aggiunga al calendario: {titoli}? Rispondi sì o no."

            # Update dashboard via JS
            if _js_callback:
                payload = [
                    {
                        "emoji":    m.get("emoji","📧"),
                        "oggetto":  m.get("oggetto",""),
                        "riassunto": m.get("riassunto",""),
                        "isNew":    True
                    }
                    for m in classificate
                ]
                try:
                    _js_callback("aggiornaMail", payload)
                except Exception as e:
                    _log("MAIL", f"Errore JS callback info mail: {e}")

            _notifica(msg)
            segna_come_lette([m["mail_id"] for m in classificate])
            _log("MAIL", f"Notificate {len(classificate)}, eventi con data: {len(eventi_con_data)}.")

        except Exception as e:
            _log("MAIL", f"Errore: {e}")
        finally:
            _check_mail_in_corso = False

    threading.Thread(target=_esegui, daemon=True, name="MailCheck").start()


def _aggiungi_eventi_calendario(eventi: list):
    """Aggiunge al Google Calendar gli eventi estratti dalle mail."""
    try:
        from actions.tools_calendar import ottieni_servizio_calendario
        import dateparser as dp

        service  = ottieni_servizio_calendario()
        aggiunti = []

        for evento in eventi:
            try:
                data = dp.parse(
                    evento["data_estratta"],
                    languages=["it"],
                    settings={"PREFER_DATES_FROM": "future"}
                )
                if not data:
                    _log("MAIL", f"Data non parsabile: {evento['data_estratta']}")
                    continue
                data_fine = data + datetime.timedelta(hours=1)
                ev = {
                    "summary": evento["titolo_evento"],
                    "start": {"dateTime": data.isoformat(), "timeZone": "Europe/Rome"},
                    "end":   {"dateTime": data_fine.isoformat(), "timeZone": "Europe/Rome"},
                }
                service.events().insert(calendarId="primary", body=ev).execute()
                aggiunti.append(evento["titolo_evento"])
                _log("MAIL", f"Evento aggiunto: {evento['titolo_evento']}")
            except Exception as e:
                _log("MAIL", f"Errore evento '{evento.get('titolo_evento')}': {e}")

        msg = f"Aggiunto al calendario: {', '.join(aggiunti)}." if aggiunti else "Nessun evento aggiunto (date non riconosciute)."
        _notifica(msg)

    except Exception as e:
        _notifica(f"Errore aggiunta calendario: {e}")
        _log("MAIL", f"Errore _aggiungi_eventi_calendario: {e}")


# ══════════════════════════════════════════════════════════════
# CONTROLLO ROUTINE LEARNING
# ══════════════════════════════════════════════════════════════

def _controlla_learning():
    """
    Chiamato ogni ora dal loop. Verifica se ci sono attività che hanno
    raggiunto confidenza >= 80% e propone aggiornamento routine_config.json.
    """
    global _learning_in_attesa
    if _ui_callbacks is None:
        return
    try:
        from automations.tools_routine_learning import controlla_stabilizzazioni

        def _notifica_learning(msg: str, chiave: str):
            global _learning_in_attesa
            _learning_in_attesa[chiave] = msg
            _notifica(msg)
            _log("LEARNING", f"Proposta: {chiave}")

        controlla_stabilizzazioni(notifica_fn=_notifica_learning)
    except Exception as e:
        _log("LEARNING", f"Errore: {e}")


# ══════════════════════════════════════════════════════════════
# LOOP PRINCIPALE — sleep adattivo, no deriva temporale
# ══════════════════════════════════════════════════════════════

def _loop():
    """
    Loop preciso con sleep adattivo.
    Misura il tempo di esecuzione dei check e dorme
    solo il tempo rimanente fino al prossimo tick da 60s.
    Questo evita la deriva che si accumula con un semplice time.sleep(60)
    quando i check stessi impiegano qualche millisecondo.
    """
    time.sleep(10)   # Attesa warmup iniziale
    _log("LOOP", "Supervisore avviato.")

    while True:
        tick_start = time.time()

        try:    _controlla_routine()
        except Exception as e: _log("LOOP", f"Eccezione routine: {e}")

        try:    _controlla_calendario()
        except Exception as e: _log("LOOP", f"Eccezione calendario: {e}")

        try:    _controlla_mail()
        except Exception as e: _log("LOOP", f"Eccezione mail: {e}")

        # Se l'utente è inattivo da 5 min, possiamo loggarlo ma non forziamo l'uscita
        if (time.time() - _ultimo_messaggio_utente) > 300:
            _log("LOOP", "Inattività > 5 min. Il sistema rimane in idle (check background attivi).")

        try:    _controlla_learning()
        except Exception as e: _log("LOOP", f"Eccezione learning: {e}")

        # Dorme il tempo residuo fino al prossimo minuto
        elapsed  = time.time() - tick_start
        to_sleep = max(0.5, 60.0 - elapsed)
        time.sleep(to_sleep)


def avvia():
    """Avvia il supervisore in un thread daemon. Chiamato da logica_chat.avvia_background()."""
    threading.Thread(target=_loop, daemon=True, name="SupervisoreRoutine").start()
    _log("AVVIO", "Thread supervisore avviato.")