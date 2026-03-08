"""
tools_mail.py — Lettura e classificazione mail Gmail per IDIS.
Riusa credentials.json / token.json già presenti per Google Calendar.
Aggiunge lo scope gmail.readonly al token esistente.
"""

import os
import json
import base64
import datetime
from langchain_core.tools import tool

# ── Scope Gmail aggiunto a quelli Calendar già presenti ──────
SCOPES = [
    'https://www.googleapis.com/auth/calendar.events',
    'https://www.googleapis.com/auth/gmail.readonly',
]

_servizio_gmail_cache = None


def ottieni_servizio_gmail():
    global _servizio_gmail_cache
    if _servizio_gmail_cache is not None:
        return _servizio_gmail_cache

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    token_path = 'token.json' if os.path.exists('token.json') else os.path.join('..', 'token.json')
    creds_path = 'credentials.json' if os.path.exists('credentials.json') else os.path.join('..', 'credentials.json')

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Prima volta o scope cambiato — ri-autenticazione
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, 'w') as f:
            f.write(creds.to_json())

    _servizio_gmail_cache = build('gmail', 'v1', credentials=creds)
    return _servizio_gmail_cache


def _decodifica_body(payload) -> str:
    """Estrae il testo della mail dal payload Gmail (testo puro o HTML)."""
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
                    import re
                    html = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                    body = re.sub(r'<[^>]+>', ' ', html)
    else:
        data = payload.get('body', {}).get('data', '')
        if data:
            body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
    return body[:2000]  # Tronca per non saturare il prompt


def fetch_mail_recenti(max_mail: int = 20) -> list[dict]:
    """
    Recupera le ultime N mail non lette dalla inbox.
    Ritorna lista di dict con: id, mittente, oggetto, data, corpo.
    """
    try:
        service = ottieni_servizio_gmail()
        risultati = service.users().messages().list(
            userId='me',
            labelIds=['INBOX', 'UNREAD'],
            maxResults=max_mail
        ).execute()

        messaggi = risultati.get('messages', [])
        mail_list = []

        for msg in messaggi:
            dettaglio = service.users().messages().get(
                userId='me',
                id=msg['id'],
                format='full'
            ).execute()

            headers = {h['name']: h['value'] for h in dettaglio['payload'].get('headers', [])}
            corpo = _decodifica_body(dettaglio['payload'])

            mail_list.append({
                'id':       msg['id'],
                'mittente': headers.get('From', 'Sconosciuto'),
                'oggetto':  headers.get('Subject', '(nessun oggetto)'),
                'data':     headers.get('Date', ''),
                'corpo':    corpo,
            })

        return mail_list
    except Exception as e:
        print(f"[MAIL] Errore fetch: {e}")
        return []


def classifica_mail_con_llm(mail_list: list[dict], llm) -> list[dict]:
    """
    Passa ogni mail a Qwen3.5 (con thinking attivo) per classificarla.
    Ritorna solo le mail rilevanti con categoria, riassunto e dati estratti.
    """
    if not llm or not mail_list:
        return []

    from langchain_core.messages import SystemMessage, HumanMessage

    SYSTEM = """Sei un assistente che classifica email in italiano.
Analizza la mail e rispondi SOLO con un JSON valido, nessun testo prima o dopo.
Formato richiesto:
{
  "rilevante": true/false,
  "categoria": "ordine|spedizione|abbonamento|appuntamento|pagamento|fattura|prenotazione|scadenza|altro",
  "priorita": "alta|media|bassa",
  "riassunto": "frase breve in italiano max 20 parole",
  "ha_data": true/false,
  "data_estratta": "GG/MM/YYYY o null",
  "titolo_evento": "titolo breve per calendario o null",
  "emoji": "emoji rappresentativa"
}
Considera NON rilevante (rilevante: false): newsletter, offerte lavoro, promozioni, marketing, spam.
Considera RILEVANTE: ordini, spedizioni, abbonamenti, appuntamenti, pagamenti, fatture, prenotazioni, scadenze."""

    classificate = []

    for mail in mail_list:
        try:
            prompt_mail = f"""Mittente: {mail['mittente']}
Oggetto: {mail['oggetto']}
Data: {mail['data']}
Corpo: {mail['corpo'][:800]}"""

            risposta = llm.invoke([
                SystemMessage(content=SYSTEM),
                HumanMessage(content=prompt_mail)
            ])

            testo = risposta.content
            if isinstance(testo, list):
                testo = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in testo)

            # Pulizia JSON
            import re
            match = re.search(r'\{[\s\S]*\}', testo)
            if not match:
                continue

            dati = json.loads(match.group())
            if not dati.get('rilevante', False):
                continue

            dati['mail_id']  = mail['id']
            dati['mittente'] = mail['mittente']
            dati['oggetto']  = mail['oggetto']
            classificate.append(dati)

        except Exception as e:
            print(f"[MAIL] Errore classificazione: {e}")
            continue

    return classificate


def segna_come_lette(mail_ids: list[str]):
    """Rimuove il label UNREAD dalle mail processate."""
    try:
        service = ottieni_servizio_gmail()
        for mid in mail_ids:
            service.users().messages().modify(
                userId='me',
                id=mid,
                body={'removeLabelIds': ['UNREAD']}
            ).execute()
    except Exception:
        pass


# ── Tool LangChain — chiamato dall'utente esplicitamente ─────

@tool
def leggi_mail_importanti() -> str:
    """
    Legge le mail non lette e restituisce un resoconto delle più importanti.
    Usa questo tool quando l'utente chiede 'controlla le mail', 'ho mail?',
    'cosa mi è arrivato per email', 'aggiornamenti email'.
    """
    try:
        mail_list = fetch_mail_recenti(max_mail=15)
        if not mail_list:
            return "Nessuna mail non letta nella inbox."

        # Import llm da logica_chat per non creare dipendenza circolare
        from logica_chat import llm as _llm
        classificate = classifica_mail_con_llm(mail_list, _llm)

        if not classificate:
            return f"Ho controllato {len(mail_list)} mail — nessuna rilevante trovata (spam e promozioni esclusi)."

        righe = []
        for m in classificate:
            emoji = m.get('emoji', '📧')
            righe.append(f"{emoji} {m['riassunto']}")

        return f"Ho trovato {len(classificate)} mail importanti:\n" + "\n".join(righe)
    except Exception as e:
        return f"Errore lettura mail: {str(e)}"