import datetime
import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from langchain_core.tools import tool
import dateparser
from dateparser.search import search_dates
import re

# Permessi completi per lettura, scrittura ed eliminazione eventi
SCOPES = ['https://www.googleapis.com/auth/calendar.events']

# ✅ Cache globale del servizio — costruito una sola volta, evita discovery HTTP ad ogni chiamata
_servizio_cache = None

def ottieni_servizio_calendario():
    global _servizio_cache

    # Restituisce il servizio gia costruito — evita discovery HTTP ad ogni chiamata
    if _servizio_cache is not None:
        return _servizio_cache

    creds = None
    token_path = os.path.join('..', 'token_calendar.json')
    creds_path = os.path.join('..', 'credentials.json')

    if os.path.exists('token_calendar.json'):
        token_path = 'token_calendar.json'
    if os.path.exists('credentials.json'):
        creds_path = 'credentials.json'

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, 'w') as token:
            token.write(creds.to_json())

    # Salva in cache — le chiamate successive non rifanno il discovery
    _servizio_cache = build('calendar', 'v3', credentials=creds)
    return _servizio_cache

@tool
def leggi_calendario(periodo_richiesto: str = "oggi") -> str:
    """
    Usa questo strumento per controllare gli impegni, il programma o gli eventi su Google Calendar in base a date specifiche.
    
    Argomenti:
    - 'periodo_richiesto': passa ESATTAMENTE le parole temporali usate dall'utente. 
      L'argomento accetta stringhe libere come: "oggi", "domani", "dopodomani", "lunedì", "martedì prossimo", "settimana prossima", "dal 10 al 15", "questo weekend".
      
    Esempi pratici:
    - Utente chiede "Cosa devo fare domani?": passa "domani".
    - Utente chiede "Impegni di questo venerdì?": passa "venerdì".
    - Utente chiede "Programma della prossima settimana": passa "prossima settimana".
    """
    try:
        service = ottieni_servizio_calendario()

        # Usiamo dateparser per capire cosa vuole l'utente
        adesso = datetime.datetime.now()
        inizio_dt = adesso.replace(hour=0, minute=0, second=0, microsecond=0)
        fine_dt = inizio_dt + datetime.timedelta(days=1)

        testo = periodo_richiesto.lower().strip()
        
        # Gestione range comuni e semplici
        if "settimana prossima" in testo or "prossima settimana" in testo:
            giorni_a_lunedi = 7 - inizio_dt.weekday()
            inizio_dt = inizio_dt + datetime.timedelta(days=giorni_a_lunedi)
            fine_dt = inizio_dt + datetime.timedelta(days=7)
        elif "questa settimana" in testo:
            # Da oggi a domenica
            giorni_a_domenica = 6 - inizio_dt.weekday()
            fine_dt = inizio_dt + datetime.timedelta(days=giorni_a_domenica + 1)
        elif "weekend" in testo:
            giorni_a_sabato = 5 - inizio_dt.weekday()
            if giorni_a_sabato < 0: giorni_a_sabato = 6
            inizio_dt = inizio_dt + datetime.timedelta(days=giorni_a_sabato)
            fine_dt = inizio_dt + datetime.timedelta(days=2)
        else:
            # Fallback a dateparser per singoli giorni (es. "lunedì", "domani", "25 ottobre")
            data_analizzata = dateparser.parse(periodo_richiesto, languages=['it'], settings={'TIMEZONE': 'Europe/Rome', 'PREFER_DATES_FROM': 'future'})
            if data_analizzata:
                inizio_dt = data_analizzata.replace(hour=0, minute=0, second=0, microsecond=0)
                fine_dt = data_analizzata.replace(hour=23, minute=59, second=59, microsecond=999)
        
        time_min = inizio_dt.isoformat() + 'Z'
        time_max = fine_dt.isoformat() + 'Z'
        
        events_result = service.events().list(calendarId='primary', timeMin=time_min,
                                              timeMax=time_max, singleEvents=True,
                                              orderBy='startTime').execute()
        events = events_result.get('items', [])
        
        if not events:
            return f"Non ci sono eventi in programma nel periodo richiesto (da {inizio_dt.strftime('%d/%m/%Y')} a {fine_dt.strftime('%d/%m/%Y')})."
            
        risultato = "Ecco gli eventi trovati:\n"
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            # Estraiamo data e orario
            if 'T' in start:
                data_evento = start.split('T')[0]
                orario = start.split('T')[1][:5]
                data_formattata = datetime.datetime.strptime(data_evento, "%Y-%m-%d").strftime("%d/%m/%Y")
                risultato += f"- {data_formattata} alle {orario}: {event['summary']}\n"
            else:
                data_formattata = datetime.datetime.strptime(start, "%Y-%m-%d").strftime("%d/%m/%Y")
                risultato += f"- {data_formattata} (Tutto il giorno): {event['summary']}\n"
            
        return risultato
    except Exception as e:
        return f"Errore nella lettura del calendario: {str(e)}"

@tool
def aggiungi_evento_calendario(sommario: str, data_ora_inizio: str, durata_minuti: int = 60) -> str:
    """
    Usa questo strumento per creare o aggiungere un nuovo evento/impegno nel Google Calendar dell'utente.
    Se l'utente omette l'ora esatta, inventane una ragionevole in base all'evento oppure metti le 09:00 del mattino.

    Argomenti:
    - 'sommario': Il titolo o la descrizione dell'evento (es. "Riunione con Marco", "Dentista", "Partita di calcetto").
    - 'data_ora_inizio': passa ESATTAMENTE le parole temporali usate dall'utente. NON TRADURRE E NON INVENTARE NIENTE.
      L'argomento accetta stringhe libere (preferibile includere un orario) come: "domani alle 15:00", "5 marzo 2026 alle 17", "il 25 ottobre alle 18:30". 
    - 'durata_minuti': (opzionale) quanto dura l'evento, di default 60 minuti.
    """
    try:
        service = ottieni_servizio_calendario()

        adesso_mezzanotte = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        impostazioni = {'TIMEZONE': 'Europe/Rome', 'PREFER_DATES_FROM': 'future', 'RELATIVE_BASE': adesso_mezzanotte}

        # Usiamo dateparser per decodificare data/ora naturali
        data_analizzata = dateparser.parse(data_ora_inizio, languages=['it'], settings=impostazioni)
        
        if not data_analizzata:
            # Fallback a search_dates se la stringa contiene troppo "rumore"
            date_trovate = search_dates(data_ora_inizio, languages=['it'], settings=impostazioni)
            if date_trovate and len(date_trovate) > 0:
                data_analizzata = date_trovate[0][1] # Prende il datetime della prima data trovata
            else:
                return f"Impossibile comprendere la data e l'ora specificate: '{data_ora_inizio}'. Sii più specifico."

        # Controllo di Sicurezza con Regex: Dateparser spesso ignora l'ora se scritta in formato testuale ("alle 19") 
        # e sovrascrive erroneamente l'ora attuale se la data è relativa ("domani").
        # Proviamo ad estrarla manualmente.
        orario_inventato = False
        import re
        match_ora = re.search(r"alle\s*(\d{1,2})(?::(\d{2}))?", data_ora_inizio.lower())
        if match_ora:
            ora_estratta = int(match_ora.group(1))
            minuti_estratti = int(match_ora.group(2)) if match_ora.group(2) else 0
            data_analizzata = data_analizzata.replace(hour=ora_estratta, minute=minuti_estratti, second=0, microsecond=0)
        else:
            # Se non ha trovato "alle XX", controlliamo se dateparser ha trovato un'ora vuota
            if data_analizzata.hour == 0 and data_analizzata.minute == 0:
                data_analizzata = data_analizzata.replace(hour=9, minute=0, second=0, microsecond=0)
                orario_inventato = True

        data_fine = data_analizzata + datetime.timedelta(minutes=durata_minuti)

        # L'utente ha richiesto di segnare gli eventi 10 minuti prima dell'orario effettivo
        # Applichiamo questo offset SOLO se l'orario era stato specificato (non inventato alle 09:00)
        if not orario_inventato:
            data_analizzata = data_analizzata - datetime.timedelta(minutes=10)
            data_fine = data_fine - datetime.timedelta(minutes=10)

        # Formatto in ISO RFC3339 come richiesto da Google
        evento = {
          'summary': sommario,
          'start': {
            'dateTime': data_analizzata.isoformat(),
            'timeZone': 'Europe/Rome',
          },
          'end': {
            'dateTime': data_fine.isoformat(),
            'timeZone': 'Europe/Rome',
          }
        }

        evento_creato = service.events().insert(calendarId='primary', body=evento).execute()
        
        # ISTRUZIONE STRINGENTE PER IL MODELLO (Catena Proattiva)
        return f"L'evento '{sommario}' aggiunto con successo per il {data_analizzata.strftime('%d/%m/%Y alle %H:%M')}. 'Ho aggiunto l'evento al calendario! Vuoi che imposti anche una sveglia sul PC per ricordartelo prima che inizi? Se sì, a che ora?'"
    except Exception as e:
        return f"Errore durante l'aggiunta dell'evento al calendario: {str(e)}"

@tool
def elimina_evento_calendario(nome_evento: str, periodo_riferimento: str = "tutte") -> str:
    """
    Usa questo strumento per cancellare o eliminare un evento/impegno dal Google Calendar.
    
    Argomenti:
    - 'nome_evento': inserisci una parola chiave o il titolo parziale dell'evento da eliminare (es. "Dentista", "Riunione"). Sii conciso.
    - 'periodo_riferimento': un riferimento testuale a quando si svolgerà l'evento. Se non fornito, cerca tra impegni futuri generici. 
      Esempi: "domani", "prossima settimana", "giovedì".
    """
    try:
        service = ottieni_servizio_calendario()

        adesso_utc = datetime.datetime.utcnow()
        inizio_dt = adesso_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        
        if "tutte" not in periodo_riferimento.lower():
            testo = periodo_riferimento.lower().strip()
            # Gestione range
            if "settimana prossima" in testo or "prossima settimana" in testo:
                giorni_a_lunedi = 7 - inizio_dt.weekday()
                inizio_dt = inizio_dt + datetime.timedelta(days=giorni_a_lunedi)
                fine_dt = inizio_dt + datetime.timedelta(days=7)
            else:
                data_analizzata = dateparser.parse(periodo_riferimento, languages=['it'], settings={'TIMEZONE': 'Europe/Rome', 'PREFER_DATES_FROM': 'future'})
                if data_analizzata:
                    inizio_dt = data_analizzata.replace(hour=0, minute=0, second=0, microsecond=0)
                    fine_dt = data_analizzata.replace(hour=23, minute=59, second=59)
                else:
                    fine_dt = inizio_dt + datetime.timedelta(days=365) # Un anno nel futuro
        else:
            fine_dt = inizio_dt + datetime.timedelta(days=365) # Un anno nel futuro

        time_min = inizio_dt.isoformat() + 'Z'
        time_max = fine_dt.isoformat() + 'Z'
        
        # Cerchiamo l'evento da cancellare nel periodo stabilito
        events_result = service.events().list(calendarId='primary', timeMin=time_min,
                                              timeMax=time_max, singleEvents=True,
                                              orderBy='startTime').execute()
        events = events_result.get('items', [])

        if not events:
            return f"Non ho trovato nessun evento da eliminare nel periodo specificato."

        eventi_cancellati = 0
        per_nome = nome_evento.lower()
        for event in events:
            # Controllo se la parola chiave è contenuta nel sommario dell'evento
            if 'summary' in event and per_nome in event['summary'].lower():
                # Eseguiamo la cancellazione passando l'ID dell'evento
                service.events().delete(calendarId='primary', eventId=event['id']).execute()
                eventi_cancellati += 1
                nome_cancellato = event['summary']

        if eventi_cancellati > 0:
            return f"Eliminato l'evento '{nome_cancellato}' dal calendario! ({eventi_cancellati} match trovato)"
        else:
            return f"Non sono riuscito a trovare nessun evento che contenga '{nome_evento}' per poterlo eliminare."
    except Exception as e:
        return f"Errore durante l'eliminazione dell'evento: {str(e)}"

def ottieni_eventi_precaricati() -> str:
    """
    Funzione non esposta come tool, usata dall'app per il precaricamento all'avvio.
    Recupera gli eventi da oggi fino alla fine della prossima settimana.
    """
    try:
        service = ottieni_servizio_calendario()

        adesso_utc = datetime.datetime.utcnow()
        inizio_dt = adesso_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Calcoliamo la fine della prossima settimana
        giorni_a_domenica_prossima = (6 - inizio_dt.weekday()) + 7
        fine_dt = inizio_dt + datetime.timedelta(days=giorni_a_domenica_prossima)
        fine_dt = fine_dt.replace(hour=23, minute=59, second=59)
        
        # Filtra gli eventi che sono terminati da più di 1 ora
        limite_passato = adesso_utc - datetime.timedelta(hours=1)
        time_min = limite_passato.isoformat() + 'Z'
        time_max = fine_dt.isoformat() + 'Z'
        
        events_result = service.events().list(calendarId='primary', timeMin=time_min,
                                              timeMax=time_max, singleEvents=True,
                                              orderBy='startTime').execute()
        events = events_result.get('items', [])
        
        if not events:
            return "Nessun evento in programma da oggi fino alla fine della prossima settimana."
            
        risultato = ""
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            if 'T' in start:
                data_evento = start.split('T')[0]
                orario = start.split('T')[1][:5]
                data_formattata = datetime.datetime.strptime(data_evento, "%Y-%m-%d").strftime("%d/%m/%Y")
                risultato += f"- {data_formattata} alle {orario}: {event['summary']}\n"
            else:
                data_formattata = datetime.datetime.strptime(start, "%Y-%m-%d").strftime("%d/%m/%Y")
                risultato += f"- {data_formattata} (Tutto il giorno): {event['summary']}\n"
            
        return risultato
    except Exception as e:
        return f"Impossibile leggere il calendario (es: non loggato): {str(e)}"