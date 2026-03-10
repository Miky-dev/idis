"""
tools_mail.py — Lettura e classificazione mail Gmail per IDIS.
v3: cronometri dettagliati su ogni step per diagnosticare lentezza.
"""

import os
import json
import base64
import re
import time
import datetime
import threading
from langchain_core.tools import tool

SCOPES = [
    'https://www.googleapis.com/auth/calendar.events',
    'https://www.googleapis.com/auth/gmail.readonly',
]

_servizio_gmail_cache = None

# ══════════════════════════════════════════════════════════════
# TIMER HELPER
# ══════════════════════════════════════════════════════════════

def _t(label: str, start: float):
    elapsed = time.time() - start
    print(f"[MAIL-TIMER] {label}: {elapsed:.2f}s")
    return elapsed


# ══════════════════════════════════════════════════════════════
# FILTRO LOCALE
# ══════════════════════════════════════════════════════════════

_OGGETTO_SPAM = [
    "unsubscribe", "newsletter", "offerta", "sconto", "promo", "coupon",
    "% off", "black friday", "cyber monday", "saldi", "liquidazione",
    "offerte di lavoro", "job offer", "recruiting", "candidatura",
    "opportunità lavorativa", "posizione aperta", "hiring",
    "marketing", "pubblicità", "advertising", "sponsored",
    "verify your email", "conferma iscrizione", "welcome to",
    "hai vinto", "congratulazioni", "winner", "premio",
    "survey", "sondaggio", "feedback richiesto",
    "digest", "weekly", "monthly update", "round-up",
]

_MITTENTE_SPAM = [
    "noreply@", "no-reply@", "donotreply@",
    "newsletter@", "marketing@", "promo@", "news@",
    "notifications@linkedin", "jobs@", "careers@",
    "info@groupon", "offerte@", "deals@",
]

_OGGETTO_RILEVANTE = [
    "ordine", "order", "spedizione", "tracking", "consegna", "delivery",
    "fattura", "invoice", "ricevuta", "receipt", "pagamento", "payment",
    "abbonamento", "subscription", "rinnovo", "renewal", "scadenza",
    "appuntamento", "prenotazione", "booking", "reservation", "conferma",
    "biglietto", "ticket", "volo", "hotel", "rimborso", "refund",
    "codice otp", "codice di verifica", "password", "accesso",
    "spese", "estratto conto", "bonifico", "addebito",
]


def _filtro_locale(oggetto: str, mittente: str) -> str:
    obj_l = oggetto.lower()
    mit_l = mittente.lower()
    if any(k in obj_l for k in _OGGETTO_RILEVANTE):
        return "rilevante"
    if any(k in mit_l for k in _MITTENTE_SPAM):
        return "spam"
    if any(k in obj_l for k in _OGGETTO_SPAM):
        return "spam"
    return "incerto"


# ══════════════════════════════════════════════════════════════
# AUTENTICAZIONE
# ══════════════════════════════════════════════════════════════

def ottieni_servizio_gmail():
    global _servizio_gmail_cache
    if _servizio_gmail_cache is not None:
        return _servizio_gmail_cache

    t0 = time.time()
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    token_path = 'token_mail.json' if os.path.exists('token_mail.json') else os.path.join('..', 'token_mail.json')
    creds_path = 'credentials.json' if os.path.exists('credentials.json') else os.path.join('..', 'credentials.json')

    if os.path.exists(token_path):
        with open(token_path, "r", encoding="utf-8") as f:
            token_data = json.load(f)
        token_scopes = token_data.get("scopes", [])
        if not any("gmail" in s for s in token_scopes):
            print("[MAIL] Token senza scope Gmail — ri-autorizzazione...")
            try: os.remove(token_path)
            except: pass
            creds = None
        else:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, 'w') as f:
            f.write(creds.to_json())

    _servizio_gmail_cache = build('gmail', 'v1', credentials=creds)
    _t("ottieni_servizio_gmail", t0)
    return _servizio_gmail_cache


# ══════════════════════════════════════════════════════════════
# FETCH MAIL
# ══════════════════════════════════════════════════════════════

def _decodifica_body(payload) -> str:
    body = ""
    if 'parts' in payload:
        for part in payload['parts']:
            if part.get('mimeType') == 'text/plain':
                data = part.get('body', {}).get('data', '')
                if data:
                    body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                    break
            elif part.get('mimeType') == 'text/html' and not body:
                data = part.get('body', {}).get('data', '')
                if data:
                    html = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                    body = re.sub(r'<[^>]+>', ' ', html)
    else:
        data = payload.get('body', {}).get('data', '')
        if data:
            body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
    return body[:1500]


def fetch_mail_recenti(max_mail: int = 20) -> list[dict]:
    t_totale = time.time()
    print(f"\n[MAIL-TIMER] ══ INIZIO fetch_mail_recenti (max={max_mail}) ══")

    try:
        # Step 1: connessione Gmail
        t0 = time.time()
        service = ottieni_servizio_gmail()
        _t("connessione Gmail API", t0)

        # Step 2: lista messaggi non letti
        t0 = time.time()
        risultati = service.users().messages().list(
            userId    = 'me',
            labelIds  = ['INBOX', 'UNREAD'],
            maxResults= max_mail
        ).execute()
        messaggi = risultati.get('messages', [])
        _t(f"list() — trovate {len(messaggi)} mail non lette", t0)

        if not messaggi:
            return []

        mail_list  = []
        spam_count = 0

        for i, msg in enumerate(messaggi):
            t_msg = time.time()

            # Step 3a: fetch solo headers (leggero)
            t0 = time.time()
            meta = service.users().messages().get(
                userId          = 'me',
                id              = msg['id'],
                format          = 'metadata',
                metadataHeaders = ['From', 'Subject', 'Date']
            ).execute()
            t_header = _t(f"  [{i+1}] fetch headers", t0)

            headers  = {h['name']: h['value'] for h in meta.get('payload', {}).get('headers', [])}
            oggetto  = headers.get('Subject', '')
            mittente = headers.get('From', '')
            data_h   = headers.get('Date', '')

            # Step 3b: filtro locale — zero latenza
            esito = _filtro_locale(oggetto, mittente)
            print(f"[MAIL-TIMER]   [{i+1}] filtro locale → {esito} | '{oggetto[:50]}'")

            if esito == 'spam':
                spam_count += 1
                continue

            # Step 3c: fetch corpo completo solo se non spam
            t0 = time.time()
            dettaglio = service.users().messages().get(
                userId = 'me',
                id     = msg['id'],
                format = 'full'
            ).execute()
            _t(f"  [{i+1}] fetch corpo completo", t0)

            corpo = _decodifica_body(dettaglio['payload'])
            mail_list.append({
                'id':            msg['id'],
                'mittente':      mittente,
                'oggetto':       oggetto,
                'data':          data_h,
                'corpo':         corpo,
                'pre_rilevante': esito == 'rilevante',
            })
            _t(f"  [{i+1}] TOTALE messaggio", t_msg)

        print(f"[MAIL-TIMER] Filtro: {spam_count} spam scartate, {len(mail_list)} da analizzare.")
        _t("══ fetch_mail_recenti TOTALE", t_totale)
        return mail_list

    except Exception as e:
        print(f"[MAIL] Errore fetch: {e}")
        return []


# ══════════════════════════════════════════════════════════════
# CLASSIFICAZIONE BATCH
# ══════════════════════════════════════════════════════════════

def classifica_mail_con_llm(mail_list: list[dict], llm) -> list[dict]:
    if not llm or not mail_list:
        return []

    t_totale = time.time()
    print(f"\n[MAIL-TIMER] ══ INIZIO classifica_mail_con_llm ({len(mail_list)} mail) ══")

    from langchain_core.messages import SystemMessage, HumanMessage

    # Prompt batch — tutte le mail in una chiamata
    mail_testi = []
    for i, mail in enumerate(mail_list):
        hint = " [PRE-RILEVANTE]" if mail.get('pre_rilevante') else ""
        mail_testi.append(
            f"=== MAIL {i+1}{hint} ===\n"
            f"Mittente: {mail['mittente']}\n"
            f"Oggetto: {mail['oggetto']}\n"
            f"Corpo: {mail['corpo'][:400]}\n"  # 400 chars — sufficiente per classificare
        )

    SYSTEM = f"""/no_think
Sei un assistente che classifica email. Rispondi SOLO con un array JSON, nessun testo.
Analizza {len(mail_list)} mail e restituisci un array con {len(mail_list)} oggetti.

Formato:
[{{"indice":1,"rilevante":true/false,"categoria":"ordine|spedizione|abbonamento|appuntamento|pagamento|fattura|prenotazione|scadenza|altro","priorita":"alta|media|bassa","riassunto":"max 12 parole","ha_data":true/false,"data_estratta":"GG/MM/YYYY o null","titolo_evento":"titolo breve o null","emoji":"emoji"}}]

NON rilevante: newsletter, promo, marketing, lavoro, spam, benvenuto.
RILEVANTE: ordini, spedizioni, abbonamenti, appuntamenti, pagamenti, fatture, scadenze, OTP."""

    # Misura dimensione prompt
    prompt_completo = "\n\n".join(mail_testi)
    print(f"[MAIL-TIMER] Dimensione prompt: {len(prompt_completo)} chars, ~{len(prompt_completo)//4} token")

    # Chiamata LLM — IL PUNTO CRITICO
    t0 = time.time()
    print(f"[MAIL-TIMER] Invio batch all'LLM...")
    try:
        risposta = llm.invoke([
            SystemMessage(content=SYSTEM),
            HumanMessage(content=prompt_completo)
        ])
        t_llm = _t("LLM invoke (batch)", t0)

        testo = risposta.content
        if isinstance(testo, list):
            testo = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in testo)

        print(f"[MAIL-TIMER] Lunghezza risposta LLM: {len(testo)} chars")
        print(f"[MAIL-TIMER] Risposta raw (primi 300 chars): {testo[:300]}")

        # Parsing JSON
        t0 = time.time()
        testo_clean = re.sub(r'```json\s*', '', testo)
        testo_clean = re.sub(r'```\s*', '', testo_clean).strip()
        match = re.search(r'\[[\s\S]*\]', testo_clean)
        if not match:
            print(f"[MAIL-TIMER] ERRORE: nessun array JSON trovato nella risposta")
            return []

        risultati = json.loads(match.group())
        _t("parsing JSON", t0)

        classificate = []
        for r in risultati:
            idx = r.get("indice", 0) - 1
            if not r.get("rilevante", False):
                continue
            if idx < 0 or idx >= len(mail_list):
                continue
            mail_orig = mail_list[idx]
            r["mail_id"]  = mail_orig["id"]
            r["mittente"] = mail_orig["mittente"]
            r["oggetto"]  = mail_orig["oggetto"]
            classificate.append(r)

        print(f"[MAIL-TIMER] Risultato: {len(classificate)}/{len(mail_list)} rilevanti")
        _t("══ classifica_mail_con_llm TOTALE", t_totale)
        return classificate

    except Exception as e:
        print(f"[MAIL] Errore classificazione: {e}")
        _t("══ classifica_mail_con_llm TOTALE (con errore)", t_totale)
        return []


# ══════════════════════════════════════════════════════════════
# SEGNA COME LETTE
# ══════════════════════════════════════════════════════════════

def segna_come_lette(mail_ids: list[str]):
    try:
        t0 = time.time()
        service = ottieni_servizio_gmail()
        for mid in mail_ids:
            service.users().messages().modify(
                userId = 'me',
                id     = mid,
                body   = {'removeLabelIds': ['UNREAD']}
            ).execute()
        _t(f"segna_come_lette ({len(mail_ids)} mail)", t0)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════
# TOOL LANGCHAIN
# ══════════════════════════════════════════════════════════════

@tool
def leggi_mail_importanti() -> str:
    """
    Legge le mail non lette e restituisce un resoconto delle più importanti.
    Usa questo tool quando l'utente chiede 'controlla le mail', 'ho mail?',
    'cosa mi è arrivato per email', 'aggiornamenti email'.
    """
    try:
        t0 = time.time()
        mail_list = fetch_mail_recenti(max_mail=20)
        if not mail_list:
            return "Nessuna mail non letta (o tutte spam)."

        from logica_chat import llm as _llm
        classificate = classifica_mail_con_llm(mail_list, _llm)
        _t("leggi_mail_importanti TOTALE", t0)

        if not classificate:
            return "Ho controllato le mail — nessuna rilevante trovata."

        righe = [f"{m.get('emoji','📧')} {m['riassunto']}" for m in classificate]
        return f"Ho trovato {len(classificate)} mail importanti:\n" + "\n".join(righe)
    except Exception as e:
        return f"Errore lettura mail: {str(e)}"

# ══════════════════════════════════════════════════════════════
# MONITOR REAL-TIME — polling ogni 60s
# ══════════════════════════════════════════════════════════════

import time as _time

_monitor_attivo      = False
_monitor_thread      = None
_js_callback         = None    # fn(js_func, *args) — impostato da ui_webview.py
_ui_notify_callback  = None    # fn(mittente, testo) — aggiungi_messaggio in chat
_llm_ref             = None
_ultimo_silenzio     = 0.0     # timestamp ultimo messaggio utente
SILENZIO_SOGLIA      = 300     # 5 minuti

_IDS_FILE = "ids_mail_visti.json"
_ids_visti = set()

def _carica_ids_visti():
    global _ids_visti
    try:
        if os.path.exists(_IDS_FILE):
            with open(_IDS_FILE, "r") as f:
                _ids_visti = set(json.load(f))
    except Exception as e:
        print(f"[MAIL] Errore caricamento ids: {e}")

def _salva_ids_visti(ids_set):
    try:
        with open(_IDS_FILE, "w") as f:
            json.dump(list(ids_set), f)
    except Exception as e:
        print(f"[MAIL] Errore salvataggio ids: {e}")

_carica_ids_visti()


def inizializza_monitor(js_callback, ui_notify_callback, llm):
    """
    Chiamato da ui_webview.py dopo che PyWebView è pronto.
    js_callback(func_name, *args) → esegue JS nella dashboard.
    ui_notify_callback(mittente, testo) → aggiunge messaggio in chat.
    """
    global _js_callback, _ui_notify_callback, _llm_ref
    _js_callback        = js_callback
    _ui_notify_callback = ui_notify_callback
    _llm_ref            = llm


def aggiorna_silenzio():
    """Chiamato da logica_chat ad ogni messaggio utente."""
    global _ultimo_silenzio
    _ultimo_silenzio = _time.time()


def _call_js(func, *args):
    if _js_callback:
        try: _js_callback(func, *args)
        except Exception as e:
            print(f"[MAIL-JS] Errore callback JS: {e}")


def _controlla_nuove_mail():
    """
    Fetch leggero: recupera solo gli ID non letti.
    Se ci sono ID non ancora visti → fetch completo + classificazione.
    """
    global _ids_visti
    try:
        service   = ottieni_servizio_gmail()
        risultati = service.users().messages().list(
            userId    = 'me',
            labelIds  = ['INBOX', 'UNREAD'],
            maxResults= 20
        ).execute()

        messaggi   = risultati.get('messages', [])
        ids_attuali = {m['id'] for m in messaggi}
        ids_nuovi   = ids_attuali - _ids_visti

        if not ids_nuovi:
            return  # niente di nuovo

        print(f"[MAIL-MON] {len(ids_nuovi)} nuove mail rilevate.")
        _call_js("setMailScanning", True)

        # Fetch solo le mail nuove
        mail_nuove = []
        for msg_id in ids_nuovi:
            try:
                meta = service.users().messages().get(
                    userId          = 'me',
                    id              = msg_id,
                    format          = 'metadata',
                    metadataHeaders = ['From', 'Subject', 'Date']
                ).execute()
                headers  = {h['name']: h['value'] for h in meta.get('payload',{}).get('headers',[])}
                oggetto  = headers.get('Subject','')
                mittente = headers.get('From','')
                esito    = _filtro_locale(oggetto, mittente)

                if esito == 'spam':
                    _ids_visti.add(msg_id)
                    continue

                # Fetch corpo solo se non spam
                det   = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
                corpo = _decodifica_body(det['payload'])
                mail_nuove.append({
                    'id':            msg_id,
                    'mittente':      mittente,
                    'oggetto':       oggetto,
                    'data':          headers.get('Date',''),
                    'corpo':         corpo,
                    'pre_rilevante': esito == 'rilevante',
                })
            except Exception as e:
                print(f"[MAIL-MON] Errore fetch mail {msg_id}: {e}")

        if not mail_nuove:
            _ids_visti.update(ids_nuovi)
            _call_js("setMailScanning", False)
            return

        # Classificazione batch
        if _llm_ref:
            classificate = classifica_mail_con_llm(mail_nuove, _llm_ref)
        else:
            classificate = []

        # Aggiorna dashboard
        if classificate:
            payload = [
                {
                    "emoji":    m.get("emoji","📧"),
                    "oggetto":  m.get("oggetto",""),
                    "riassunto": m.get("riassunto",""),
                    "isNew":    True
                }
                for m in classificate
            ]
            _call_js("aggiornaMail", payload)

            # Notifica in chat solo se silenzio > 5 min
            in_silenzio = (_time.time() - _ultimo_silenzio) >= SILENZIO_SOGLIA
            if in_silenzio and _ui_notify_callback:
                righe = [f"{m.get('emoji','📧')} {m['riassunto']}" for m in classificate]
                msg   = f"Nuove mail importanti ({len(classificate)}):\n" + "\n".join(righe)
                _ui_notify_callback("🔔 IDIS", msg)

        # Segna tutti come visti
        _ids_visti.update(ids_nuovi)

    except Exception as e:
        print(f"[MAIL-MON] Errore: {e}")
    finally:
        # Salva SEMPRE su disco — anche se c'è stato un errore o un continue
        # Così al riavvio non rianalizza mai mail già viste
        _salva_ids_visti(_ids_visti)
        _call_js("setMailScanning", False)


def _loop_monitor():
    _time.sleep(30)   # Attesa iniziale dopo avvio
    while _monitor_attivo:
        _controlla_nuove_mail()
        _time.sleep(60)   # Polling ogni 60 secondi


def avvia_monitor():
    """Avvia il thread di monitoraggio mail. Chiamato da avvia_background()."""
    global _monitor_attivo, _monitor_thread
    if _monitor_attivo:
        return
    _monitor_attivo = True
    _monitor_thread = threading.Thread(target=_loop_monitor, daemon=True, name="MailMonitor")
    _monitor_thread.start()
    print("[MAIL-MON] Monitor avviato — polling ogni 60s.")


def ferma_monitor():
    global _monitor_attivo
    _monitor_attivo = False