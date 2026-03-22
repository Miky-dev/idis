"""
iphone_bridge.py — Server FastAPI per integrazione iPhone ↔ IDIS.

Espone endpoint HTTP raggiungibili dall'iPhone sulla rete locale (o via Tailscale).
L'iPhone manda GPS, attività, eventi via Shortcuts.
IDIS manda notifiche push via ntfy.sh.

Avvio: python iphone_bridge.py  (porta 8765)
"""

import threading
import datetime
import time
import math
import json
import os
import requests
from fastapi import FastAPI, HTTPException, Header, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn

app = FastAPI(title="IDIS iPhone Bridge", version="1.0")

# ══════════════════════════════════════════════════════════════
# CONFIGURAZIONE
# ══════════════════════════════════════════════════════════════

NTFY_TOPIC    = os.getenv("NTFY_TOPIC", "idis-gino")      # scegli un nome unico
NTFY_SERVER   = os.getenv("NTFY_SERVER", "https://ntfy.sh")
PORTA         = int(os.getenv("IPHONE_BRIDGE_PORT", "8765"))

# Sicurezza — API key condivisa con l'iPhone via header x-idis-key
# Impostala nel .env: IDIS_IPHONE_KEY=Miky_Segreto_2026!
IPHONE_API_KEY = os.getenv("IDIS_IPHONE_KEY", "")

# Bind — "127.0.0.1" per test locale, "0.0.0.0" con Tailscale/rete
BIND_HOST     = os.getenv("IPHONE_BIND_HOST", "0.0.0.0")

# Geofence casa — hardcoda le coordinate o usa /imposta_casa endpoint
CASA_LAT      = float(os.getenv("CASA_LAT", "0")) or None
CASA_LON      = float(os.getenv("CASA_LON", "0")) or None
CASA_RAGGIO_M = 150   # metri — considera "a casa" entro questo raggio

# GPS throttling — ignora aggiornamento se spostamento < soglia (risparmio batteria)
GPS_MIN_DISTANZA_M  = 80    # non aggiornare se < 80m dall'ultimo punto
GPS_MIN_INTERVALLO_S = 120  # non aggiornare se < 2 min dall'ultimo update

# ══════════════════════════════════════════════════════════════
# STATO CONDIVISO
# ══════════════════════════════════════════════════════════════

stato_iphone = {
    "gps": {
        "lat": None, "lon": None,
        "accuracy_m": None,
        "timestamp": None,
        "indirizzo": None,
    },
    "attivita": {
        "tipo": None,          # stationary | walking | running | automotive | cycling
        "confidenza": None,    # low | medium | high
        "timestamp": None,
    },
    "posizione_logica": None,  # "casa" | "fuori" | "università" | "palestra" | ...
    "ultima_ricezione": None,
    "geofences": {},           # nome → {lat, lon, raggio_m, dentro: bool}
}

_callbacks = {
    "on_uscita":       None,   # fn() — utente uscito di casa
    "on_rientro":      None,   # fn() — utente rientrato
    "on_attivita":     None,   # fn(tipo, confidenza)
    "on_gps":          None,   # fn(lat, lon)
}

# Throttling GPS — ultimo punto ricevuto
_ultimo_gps = {"lat": None, "lon": None, "ts": 0.0}


# ── Autenticazione ────────────────────────────────────────────

def _verifica_chiave(x_idis_key: str = Header(None)):
    """
    Dependency FastAPI — blocca richieste senza la chiave corretta.
    Se IPHONE_API_KEY è vuota (sviluppo), accetta tutto.
    """
    if IPHONE_API_KEY and x_idis_key != IPHONE_API_KEY:
        raise HTTPException(status_code=403, detail="Accesso negato: chiave non valida")

# ══════════════════════════════════════════════════════════════
# MODELLI REQUEST
# ══════════════════════════════════════════════════════════════

class GPSPayload(BaseModel):
    lat: float
    lon: float
    accuracy_m: float | None = None
    indirizzo: str | None = None

class AttivitaPayload(BaseModel):
    tipo: str          # stationary | walking | running | automotive | cycling
    confidenza: str = "medium"

class EventoCalendarioPayload(BaseModel):
    titolo: str
    data: str          # ISO8601: "2026-03-10T15:00:00"
    luogo: str | None = None
    note: str | None = None

class GeofencePayload(BaseModel):
    nome: str
    lat: float
    lon: float
    raggio_m: float = 200

class ComandoPayload(BaseModel):
    testo: str

# ══════════════════════════════════════════════════════════════
# UTILS GEOGRAFICI
# ══════════════════════════════════════════════════════════════

def _distanza_m(lat1, lon1, lat2, lon2) -> float:
    """Haversine — distanza in metri tra due coordinate."""
    R = 6371000
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    Δφ = math.radians(lat2 - lat1)
    Δλ = math.radians(lon2 - lon1)
    a  = math.sin(Δφ/2)**2 + math.cos(φ1)*math.cos(φ2)*math.sin(Δλ/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


def _aggiorna_geofences(lat: float, lon: float):
    """Controlla tutti i geofence e lancia callback se lo stato cambia."""
    global stato_iphone

    # Geofence casa automatico
    if CASA_LAT and CASA_LON:
        dist_casa = _distanza_m(lat, lon, CASA_LAT, CASA_LON)
        era_casa  = stato_iphone["posizione_logica"] == "casa"
        ora_casa  = dist_casa <= CASA_RAGGIO_M

        if not era_casa and ora_casa:
            stato_iphone["posizione_logica"] = "casa"
            print(f"[IPHONE] 🏠 Rientrato a casa (distanza: {dist_casa:.0f}m)")
            if _callbacks["on_rientro"]:
                threading.Thread(target=_callbacks["on_rientro"], daemon=True).start()

        elif era_casa and not ora_casa:
            stato_iphone["posizione_logica"] = "fuori"
            print(f"[IPHONE] 🚪 Uscito di casa (distanza: {dist_casa:.0f}m)")
            if _callbacks["on_uscita"]:
                threading.Thread(target=_callbacks["on_uscita"], daemon=True).start()

    # Geofence personalizzati
    for nome, gf in stato_iphone["geofences"].items():
        dist   = _distanza_m(lat, lon, gf["lat"], gf["lon"])
        dentro = dist <= gf["raggio_m"]
        if dentro != gf.get("dentro", False):
            gf["dentro"] = dentro
            azione = "entrato in" if dentro else "uscito da"
            print(f"[IPHONE] 📍 {azione} geofence '{nome}' (distanza: {dist:.0f}m)")
            invia_notifica(
                titolo = f"📍 {nome}",
                corpo  = f"Sei {azione} '{nome}'",
                tag    = "round_pushpin",
                priorita = "default"
            )

# ══════════════════════════════════════════════════════════════
# ENDPOINT — iPhone → IDIS
# ══════════════════════════════════════════════════════════════

@app.post("/gps")
def ricevi_gps(payload: GPSPayload, _: None = Depends(_verifica_chiave)):
    """
    Shortcuts chiama questo endpoint quando la posizione cambia significativamente.
    Throttling: ignora se < GPS_MIN_DISTANZA_M o < GPS_MIN_INTERVALLO_S.
    """
    global stato_iphone, _ultimo_gps
    adesso_ts = time.time()
    adesso    = datetime.datetime.now().isoformat()

    # ── Throttling — salta aggiornamenti inutili (risparmio batteria) ────
    intervallo = adesso_ts - _ultimo_gps["ts"]
    if _ultimo_gps["lat"] is not None:
        dist_da_ultimo = _distanza_m(payload.lat, payload.lon,
                                     _ultimo_gps["lat"], _ultimo_gps["lon"])
        if dist_da_ultimo < GPS_MIN_DISTANZA_M and intervallo < GPS_MIN_INTERVALLO_S:
            return {"ok": True, "skipped": True,
                    "motivo": f"spostamento {dist_da_ultimo:.0f}m < soglia {GPS_MIN_DISTANZA_M}m"}

    _ultimo_gps = {"lat": payload.lat, "lon": payload.lon, "ts": adesso_ts}

    stato_iphone["gps"] = {
        "lat":        payload.lat,
        "lon":        payload.lon,
        "accuracy_m": payload.accuracy_m,
        "timestamp":  adesso,
        "indirizzo":  payload.indirizzo,
    }
    stato_iphone["ultima_ricezione"] = adesso

    # Prima ricezione — inizializza posizione_logica senza triggerare callback
    if stato_iphone["posizione_logica"] is None and CASA_LAT and CASA_LON:
        dist = _distanza_m(payload.lat, payload.lon, CASA_LAT, CASA_LON)
        stato_iphone["posizione_logica"] = "casa" if dist <= CASA_RAGGIO_M else "fuori"
        print(f"[IPHONE] Posizione iniziale: {stato_iphone['posizione_logica']} (distanza da casa: {dist:.0f}m)")

    _aggiorna_geofences(payload.lat, payload.lon)

    if _callbacks["on_gps"]:
        threading.Thread(
            target=_callbacks["on_gps"],
            args=(payload.lat, payload.lon),
            daemon=True
        ).start()

    # Aggiorna anche il cache posizione di IDIS
    try:
        import actions.tools_location as tl
        if payload.indirizzo:
            tl.posizione_cache = payload.indirizzo
    except Exception:
        pass

    print(f"[IPHONE] 📡 GPS: {payload.lat:.5f}, {payload.lon:.5f} | {payload.indirizzo or ''}")
    return {"ok": True, "posizione_logica": stato_iphone["posizione_logica"]}


@app.post("/attivita")
def ricevi_attivita(payload: AttivitaPayload, _: None = Depends(_verifica_chiave)):
    """
    Shortcuts chiama questo endpoint quando l'attività cambia.
    tipo: stationary | walking | running | automotive | cycling
    """
    global stato_iphone
    vecchia = stato_iphone["attivita"]["tipo"]
    stato_iphone["attivita"] = {
        "tipo":       payload.tipo,
        "confidenza": payload.confidenza,
        "timestamp":  datetime.datetime.now().isoformat(),
    }

    emoji = {"stationary":"🧍","walking":"🚶","running":"🏃",
             "automotive":"🚗","cycling":"🚴"}.get(payload.tipo, "❓")
    print(f"[IPHONE] {emoji} Attività: {vecchia} → {payload.tipo} ({payload.confidenza})")

    # Aggiorna il routine learning con l'attività rilevata
    if payload.tipo != vecchia and payload.confidenza in ("medium", "high"):
        try:
            from automations.tools_routine_learning import rileva_e_registra
            mappa = {
                "walking":    "sto camminando",
                "running":    "sto correndo",
                "automotive": "sono in macchina",
                "cycling":    "sto andando in bici",
                "stationary": "sono fermo",
            }
            testo = mappa.get(payload.tipo, payload.tipo)
            rileva_e_registra(testo)
        except Exception as e:
            print(f"[IPHONE] Learning attività: {e}")

    # Automotive → trigger profilo uscita (equivale a "sto uscendo")
    if payload.tipo == "automotive" and payload.confidenza in ("medium", "high"):
        if not stato_iphone.get("fuori_per_auto"):
            stato_iphone["fuori_per_auto"] = True
            print("[IPHONE] 🚗 Automotive rilevato → profilo_uscita()")
            if _callbacks["on_uscita"]:
                threading.Thread(target=_callbacks["on_uscita"], daemon=True).start()
    elif payload.tipo == "stationary":
        # Reset flag quando torna fermo — pronto per prossima uscita
        stato_iphone["fuori_per_auto"] = False

    if _callbacks["on_attivita"]:
        threading.Thread(
            target=_callbacks["on_attivita"],
            args=(payload.tipo, payload.confidenza),
            daemon=True
        ).start()

    return {"ok": True}


@app.post("/calendario")
def ricevi_evento_calendario(payload: EventoCalendarioPayload, _: None = Depends(_verifica_chiave)):
    """
    Shortcuts manda gli eventi del calendario iOS — eventi non presenti su Google Calendar.
    IDIS li aggiunge al contesto e può mandare notifica navigatore.
    """
    print(f"[IPHONE] 📅 Evento da calendario iOS: '{payload.titolo}' — {payload.data}")

    # Controlla se l'evento è imminente (entro 30 min)
    try:
        dt_evento = datetime.datetime.fromisoformat(payload.data)
        minuti    = (dt_evento - datetime.datetime.now()).total_seconds() / 60

        if 0 < minuti <= 30 and payload.luogo:
            # Manda notifica con deep link al navigatore
            luogo_enc = payload.luogo.replace(" ", "+")
            maps_url  = f"maps://?daddr={luogo_enc}&dirflg=d"
            invia_notifica(
                titolo   = f"📍 {payload.titolo} tra {int(minuti)} min",
                corpo    = f"Luogo: {payload.luogo}. Tocca per aprire Maps.",
                url      = maps_url,
                tag      = "calendar",
                priorita = "high"
            )
            print(f"[IPHONE] Notifica navigatore inviata per '{payload.titolo}'")

    except Exception as e:
        print(f"[IPHONE] Parsing evento: {e}")

    return {"ok": True}


@app.post("/geofence/aggiungi")
def aggiungi_geofence(payload: GeofencePayload, _: None = Depends(_verifica_chiave)):
    """Aggiunge un geofence personalizzato (università, palestra, lavoro...)."""
    stato_iphone["geofences"][payload.nome] = {
        "lat": payload.lat, "lon": payload.lon,
        "raggio_m": payload.raggio_m, "dentro": False
    }
    print(f"[IPHONE] 📍 Geofence aggiunto: '{payload.nome}' ({payload.raggio_m}m)")
    return {"ok": True}


@app.get("/stato")
def get_stato():
    """Dashboard — restituisce lo stato corrente dell'iPhone."""
    return JSONResponse(stato_iphone)


@app.post("/imposta_casa")
def endpoint_imposta_casa(payload: GeofencePayload, _: None = Depends(_verifica_chiave)):
    """Imposta le coordinate di casa via HTTP (usa l'app ntfy o Shortcut)."""
    imposta_casa(payload.lat, payload.lon)
    return {"ok": True, "lat": payload.lat, "lon": payload.lon}


@app.post("/comando")
def esegui_comando(payload: ComandoPayload, _: None = Depends(_verifica_chiave)):
    """
    Riceve un comando testuale (es. da iOS Shortcut / Dettatura),
    lo passa a logica_chat.elabora_risposta e restituisce il risultato finale testuale.
    Intercetta i callback UI per mostrarlo nella dashboard su PC se aperta.
    """
    import logica_chat
    import threading
    
    risultato = {"testo": ""}
    evento_fine = threading.Event()

    # Callback di base per raccogliere il testo
    def _aggiorna_testo_API(nuovo_testo):
        risultato["testo"] = nuovo_testo
        
    def _set_stato_API(stato):
        if stato == "idle":
            evento_fine.set()

    # Prendi i callback correnti (quelli della UI desktop, se già iniettati)
    cb_originali = logica_chat._ui_callbacks_globali
    
    if cb_originali:
        def _aggiungi(m, t, c=None):
            cb_originali["aggiungi_messaggio"](m, t, c)
            
        def _aggiorna(nuovo_testo):
            cb_originali["aggiorna_testo"](nuovo_testo)
            _aggiorna_testo_API(nuovo_testo)
            
        def _reset_label():
            cb_originali["reset_label"]()
            
        def _set_stato(stato):
            cb_originali["set_stato"](stato)
            _set_stato_API(stato)
                
        # Mostra il comando sulla dashboard PC
        cb_originali["aggiungi_messaggio"]("📱 iPhone", payload.testo, "lightgreen")
        
        cb_ibridi = {
            "aggiungi_messaggio": _aggiungi,
            "aggiorna_testo": _aggiorna,
            "reset_label": _reset_label,
            "set_stato": _set_stato,
            "_js_callback": cb_originali.get("_js_callback", lambda f, *a: None)
        }
    else:
        # Nessuna UI Desktop aperta
        cb_ibridi = {
            "aggiungi_messaggio": lambda m,t,c=None: None,
            "aggiorna_testo": _aggiorna_testo_API,
            "reset_label": lambda: None,
            "set_stato": _set_stato_API
        }

    print(f"[IPHONE] 📱 Ricevuto comando remoto: '{payload.testo}'")
    
    def worker():
        try:
            logica_chat.elabora_risposta(payload.testo, cb_ibridi)
        finally:
            evento_fine.set()
            
    threading.Thread(target=worker, daemon=True).start()
    
    # Aspetta che l'LLM finisca (timeout di sicurezza di 60 sec)
    completato = evento_fine.wait(timeout=60.0)
    
    if not completato:
        print("[IPHONE] ⚠️ Timeout elaborazione comando remoto.")
        
    print(f"[IPHONE] 📱 Risposta inviata: '{risultato['testo']}'")
    return {"ok": True, "risposta": risultato["testo"]}


@app.get("/ping")
def ping():
    """Health check — testa connettività Tailscale/rete."""
    return {
        "ok":   True,
        "ts":   datetime.datetime.now().isoformat(),
        "auth": "abilitata" if IPHONE_API_KEY else "disabilitata (sviluppo)",
        "host": BIND_HOST,
        "porta": PORTA,
    }


# ══════════════════════════════════════════════════════════════
# NOTIFICHE PUSH — IDIS → iPhone via ntfy.sh
# ══════════════════════════════════════════════════════════════

def invia_notifica(
    titolo:   str,
    corpo:    str,
    url:      str | None = None,   # deep link (es. maps://)
    tag:      str = "bell",        # emoji/tag ntfy
    priorita: str = "default",     # min | low | default | high | urgent
    azioni:   list | None = None,  # bottoni azione notifica
):
    """
    Manda una notifica push all'iPhone via ntfy.sh.
    L'app ntfy deve essere installata sull'iPhone e iscritta al topic.

    Esempio notifica con pulsante navigatore:
        invia_notifica(
            titolo   = "Università tra 20 min",
            corpo    = "Via Branze 38, Brescia",
            url      = "maps://?daddr=Via+Branze+38+Brescia&dirflg=d",
            tag      = "school",
            priorita = "high"
        )
    """
    if not NTFY_TOPIC:
        print("[NTFY] Topic non configurato — notifica non inviata.")
        return False

    headers = {
        "Title":    titolo,
        "Priority": priorita,
        "Tags":     tag,
    }
    if url:
        headers["Click"] = url    # apre l'URL quando si tocca la notifica

    if azioni:
        # Formato: "view, Apri Maps, maps://...; ..."
        headers["Actions"] = "; ".join(
            f"view, {a['label']}, {a['url']}" for a in azioni
        )

    try:
        r = requests.post(
            f"{NTFY_SERVER}/{NTFY_TOPIC}",
            data    = corpo.encode("utf-8"),
            headers = headers,
            timeout = 5
        )
        ok = r.status_code == 200
        print(f"[NTFY] {'✓' if ok else '✗'} '{titolo}' → {r.status_code}")
        return ok
    except Exception as e:
        print(f"[NTFY] Errore: {e}")
        return False


def invia_notifica_navigatore(titolo: str, luogo: str, minuti: int | None = None):
    """Shortcut per notifica con deep link Apple Maps."""
    luogo_enc = luogo.replace(" ", "+")
    corpo     = f"Luogo: {luogo}"
    if minuti:
        corpo += f" · tra {minuti} min"
    invia_notifica(
        titolo   = titolo,
        corpo    = corpo,
        url      = f"maps://?daddr={luogo_enc}&dirflg=d",
        tag      = "round_pushpin,car",
        priorita = "high"
    )


# ══════════════════════════════════════════════════════════════
# MONITOR CALENDARIO — controlla eventi imminenti ogni minuto
# ══════════════════════════════════════════════════════════════

_notifiche_inviate: set = set()   # evita duplicati

def _monitor_calendario():
    """Thread che controlla ogni minuto se ci sono eventi imminenti con luogo."""
    time.sleep(60)   # attendi avvio completo
    while True:
        try:
            from actions.tools_calendar import ottieni_eventi_precaricati
            import logica_chat as lc
            eventi_testo = lc.eventi_precaricati

            adesso = datetime.datetime.now()
            for riga in eventi_testo.split("\n"):
                # Formato: "- GG/MM/YYYY alle HH:MM: Titolo (Luogo)"
                import re
                m = re.match(
                    r"-\s*(\d{2}/\d{2}/\d{4}) alle (\d{2}:\d{2}):\s*(.+?)(?:\s*\((.+)\))?$",
                    riga.strip()
                )
                if not m:
                    continue
                data_str, ora_str, titolo, luogo = m.groups()
                if not luogo:
                    continue

                try:
                    dt = datetime.datetime.strptime(
                        f"{data_str} {ora_str}", "%d/%m/%Y %H:%M"
                    )
                except Exception:
                    continue

                minuti = (dt - adesso).total_seconds() / 60
                chiave = f"{titolo}_{data_str}_{ora_str}"

                # Notifica 30 min prima
                if 28 <= minuti <= 32 and chiave not in _notifiche_inviate:
                    _notifiche_inviate.add(chiave)
                    invia_notifica_navigatore(
                        titolo = f"📅 {titolo} tra 30 min",
                        luogo  = luogo,
                        minuti = 30
                    )
                    print(f"[IPHONE] Notifica 30min per: {titolo} @ {luogo}")

                # Notifica 10 min prima
                elif 8 <= minuti <= 12 and f"{chiave}_10" not in _notifiche_inviate:
                    _notifiche_inviate.add(f"{chiave}_10")
                    invia_notifica_navigatore(
                        titolo = f"⚠️ {titolo} tra 10 min!",
                        luogo  = luogo,
                        minuti = 10
                    )
                    print(f"[IPHONE] Notifica 10min per: {titolo} @ {luogo}")

        except Exception as e:
            print(f"[IPHONE] Monitor calendario: {e}")

        time.sleep(60)


# ══════════════════════════════════════════════════════════════
# INTEGRAZIONE CON IDIS
# ══════════════════════════════════════════════════════════════

def inizializza_callbacks():
    """
    Collega i trigger iPhone al profilo uscita/rientro di IDIS.
    Chiamato da avvia_background() in logica_chat.py.
    """
    try:
        from automations.profilo_uscita import esegui_profilo_uscita, esegui_profilo_rientro

        def _on_uscita_gps():
            print("[IPHONE] GPS o Automotive: trigger uscita → profilo_uscita")
            esegui_profilo_uscita("uscito di casa tramite iphone (GPS/Automotive)")

        def _on_rientro_gps():
            print("[IPHONE] GPS: trigger rientro → profilo_rientro")
            esegui_profilo_rientro()

        _callbacks["on_uscita"]  = _on_uscita_gps
        _callbacks["on_rientro"] = _on_rientro_gps
        print("[IPHONE] Callbacks IDIS collegati.")
    except Exception as e:
        print(f"[IPHONE] inizializza_callbacks: {e}")


def imposta_casa(lat: float, lon: float):
    """Imposta le coordinate di casa manualmente."""
    global CASA_LAT, CASA_LON
    CASA_LAT, CASA_LON = lat, lon
    print(f"[IPHONE] 🏠 Coordinate casa impostate: {lat:.5f}, {lon:.5f}")


def avvia_server():
    """Avvia il server FastAPI in background. Chiamato da avvia_background()."""
    def _run():
        print(f"[IPHONE] Server avviato su http://{BIND_HOST}:{PORTA}")
        auth_stato = "con autenticazione" if IPHONE_API_KEY else "SENZA autenticazione (imposta IDIS_IPHONE_KEY)"
        print(f"[IPHONE] {auth_stato} — ntfy topic: {NTFY_TOPIC}")
        uvicorn.run(app, host=BIND_HOST, port=PORTA, log_level="warning")

    threading.Thread(target=_run, daemon=True, name="iPhoneBridge").start()
    threading.Thread(target=_monitor_calendario, daemon=True, name="iPhoneCalMon").start()
    inizializza_callbacks()


# ══════════════════════════════════════════════════════════════
# AVVIO STANDALONE
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print(f"IDIS iPhone Bridge — porta {PORTA}")
    print(f"ntfy topic: {NTFY_TOPIC}")
    avvia_server()
    # Tieni vivo
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Server fermato.")