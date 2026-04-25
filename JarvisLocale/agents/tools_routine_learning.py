"""
tools_routine_learning.py — IDIS Routine Learning Engine.

Impara la routine dell'utente da 4 sorgenti:
  1. Keyword nei messaggi (segnale esplicito, peso alto)
  2. Gap di silenzio tra messaggi (inferenza, peso medio)
  3. Eventi Google Calendar (fonte esterna verificata, peso alto)
  4. Stato schermo PC (contesto, peso basso)

Notifica solo quando confidenza >= 80% e >= 5 osservazioni.
Propone aggiornamento routine_config.json quando un orario si stabilizza.
"""

import datetime
import json
import math
import os
import threading
import time

# ── Path dati ────────────────────────────────────────────────
_BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
LEARNING_PATH = os.path.join(_BASE_DIR, "routine_learning.json")

# ── Lock per accesso file concorrente ────────────────────────
_lock = threading.Lock()

# ── Soglie ───────────────────────────────────────────────────
MIN_OSSERVAZIONI   = 5      # osservazioni minime per considerare affidabile
CONFIDENZA_SOGLIA  = 80.0   # % minima per notificare / proporre aggiornamento
STD_BONUS_10       = 10     # minuti: deviazione sotto cui dare bonus +20%
STD_BONUS_20       = 20     # minuti: deviazione sotto cui dare bonus +10%
GIORNI_FINESTRA    = 30     # osservazioni oltre 30gg vengono ignorate nel calcolo

# ── Pesi per fonte ───────────────────────────────────────────
PESI = {
    "keyword":         1.0,
    "calendario":      0.9,
    "gap+calendario":  0.85,
    "gap+schermo":     0.6,
    "gap":             0.4,
}

# ── Giorni settimana ─────────────────────────────────────────
GIORNI = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]

# ── Mappa keyword → attività ─────────────────────────────────
KEYWORD_MAP = {
    "sveglia": [
        "buongiorno", "good morning", "mi sono svegliato", "sono sveglio",
        "mi sono alzato", "svegliato", "appena alzato", "eccomi"
    ],
    "colazione": [
        "colazione", "ho fatto colazione", "sto facendo colazione",
        "ho mangiato stamattina", "caffè", "cappuccino", "cornetto"
    ],
    "pranzo": [
        "pranzo", "ho pranzato", "sto pranzando", "a pranzo",
        "mangiato a mezzogiorno", "pausa pranzo"
    ],
    "cena": [
        "cena", "ho cenato", "sto cenando", "a cena",
        "mangiato stasera", "finito di cenare"
    ],
    "uscita": [
        "esco", "sto uscendo", "sono uscito", "vado fuori",
        "esco di casa", "parto", "vado via", "ci vediamo"
    ],
    "rientro": [
        "sono rientrato", "sono a casa", "sono tornato",
        "rientrato", "tornato a casa", "eccomi qua"
    ],
    "palestra": [
        "palestra", "allenamento", "vado ad allenarmi", "ho fatto sport",
        "finito di allenarmi", "workout", "ho corso", "corsa", "nuoto"
    ],
    "studio": [
        "studio", "sto studiando", "inizio a studiare", "università",
        "lezione", "esame", "mi metto a studiare", "appunti"
    ],
    "sonno": [
        "vado a dormire", "buonanotte", "a letto", "notte",
        "dormo", "vado a letto", "ci vediamo domani", "good night"
    ],
}

# ── Tabella inferenza gap (orario_inizio, durata_min_min, durata_min_max) → attività
# Ordinata per priorità — la prima che matcha vince
GAP_INFERENCE_TABLE = [
    # (ora_inizio_min, ora_inizio_max, gap_min_min, gap_min_max, attività, label)
    (0,   7*60,   3*60, 12*60, "sonno",     "gap"),   # notte lunga
    (22*60, 24*60, 60,  10*60, "sonno",     "gap"),   # va a letto tardi
    (6*60,  9*60,  20,  90,   "sveglia",   "gap"),   # mattina, gap breve → sveglia/colazione
    (6*60,  9*60,  90,  180,  "colazione", "gap"),
    (11*60, 14*60, 30,  180,  "pranzo",    "gap"),
    (16*60, 20*60, 60,  180,  "palestra",  "gap"),
    (17*60, 20*60, 30,  90,   "uscita",    "gap"),
    (19*60, 23*60, 45,  180,  "cena",      "gap"),
]

# ── Keyword calendario → attività ────────────────────────────
CALENDARIO_MAP = {
    "sveglia":  ["sveglia", "wake"],
    "palestra": ["palestra", "gym", "allenamento", "workout", "corsa", "nuoto", "sport"],
    "studio":   ["studio", "lezione", "università", "esame", "corso", "lecture"],
    "uscita":   ["uscita", "partenza", "viaggio", "treno", "aereo", "appuntamento"],
    "pranzo":   ["pranzo", "lunch", "pausa pranzo"],
    "cena":     ["cena", "dinner", "cena con"],
    "sonno":    ["dormire", "riposo", "notte"],
}


# ══════════════════════════════════════════════════════════════
# I/O JSON
# ══════════════════════════════════════════════════════════════

def _carica() -> dict:
    try:
        if os.path.exists(LEARNING_PATH):
            with open(LEARNING_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {
        "osservazioni": {},
        "ultimo_messaggio": None,
        "stabilizzazioni_notificate": []
    }


def _salva(data: dict):
    with open(LEARNING_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ══════════════════════════════════════════════════════════════
# REGISTRAZIONE OSSERVAZIONE
# ══════════════════════════════════════════════════════════════

def _registra(attivita: str, ora: str, giorno: str, fonte: str):
    """
    Salva una singola osservazione.
    ora: "HH:MM", giorno: "lun"…"dom", fonte: da PESI
    """
    with _lock:
        data = _carica()
        obs  = data.setdefault("osservazioni", {})
        att  = obs.setdefault(attivita, {})
        gg   = att.setdefault(giorno, [])

        oggi = datetime.date.today().isoformat()

        # Evita duplicato stesso giorno stessa fonte
        for o in gg:
            if o.get("data") == oggi and o.get("fonte") == fonte:
                # Aggiorna l'orario se stessa fonte stesso giorno
                o["ora"] = ora
                _salva(data)
                return

        gg.append({"ora": ora, "fonte": fonte, "data": oggi})
        # Tieni solo le ultime 60 osservazioni per giorno
        if len(gg) > 60:
            att[giorno] = gg[-60:]

        _salva(data)


# ══════════════════════════════════════════════════════════════
# SORGENTE 1 — KEYWORD
# ══════════════════════════════════════════════════════════════

def rileva_e_registra(testo: str):
    """
    Chiamato da logica_chat.elabora_risposta() — zero latenza.
    Cerca keyword nel messaggio e registra l'attività rilevata.
    Aggiorna anche il timestamp ultimo messaggio per il calcolo gap.
    """
    adesso = datetime.datetime.now()
    ora    = adesso.strftime("%H:%M")
    giorno = GIORNI[adesso.weekday()]
    testo_l = testo.lower()

    # Keyword matching
    for attivita, keywords in KEYWORD_MAP.items():
        if any(k in testo_l for k in keywords):
            threading.Thread(
                target=_registra,
                args=(attivita, ora, giorno, "keyword"),
                daemon=True
            ).start()
            break  # una attività per messaggio

    # Calcola e registra gap rispetto al messaggio precedente
    threading.Thread(
        target=_processa_gap,
        args=(adesso,),
        daemon=True
    ).start()

    # Aggiorna timestamp ultimo messaggio
    with _lock:
        data = _carica()
        data["ultimo_messaggio"] = adesso.isoformat()
        _salva(data)


# ══════════════════════════════════════════════════════════════
# SORGENTE 2 — GAP SILENZIO
# ══════════════════════════════════════════════════════════════

def _get_stato_schermo() -> bool:
    """True se lo schermo è attivo. Usa ctypes su Windows."""
    try:
        import ctypes
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_ulong)]
        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
        idle_ms   = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
        idle_min  = idle_ms / 60000
        # Schermo "spento" se idle > 10 minuti
        return idle_min < 10
    except Exception:
        return True  # fallback: assume attivo


def _processa_gap(adesso: datetime.datetime):
    """
    Calcola il gap dall'ultimo messaggio e inferisce l'attività.
    Incrocia con calendario se disponibile.
    """
    with _lock:
        data = _carica()
        ultimo_str = data.get("ultimo_messaggio")
    if not ultimo_str:
        return

    try:
        ultimo = datetime.datetime.fromisoformat(ultimo_str)
    except Exception:
        return

    gap_min = (adesso - ultimo).total_seconds() / 60
    if gap_min < 15:
        return  # gap troppo corto — non inferire nulla

    ora_inizio_min = ultimo.hour * 60 + ultimo.minute
    giorno         = GIORNI[ultimo.weekday()]
    ora_str        = ultimo.strftime("%H:%M")

    # Prova prima con calendario
    attivita_cal = _inferisci_da_calendario(ultimo, adesso)
    if attivita_cal:
        stato_schermo = _get_stato_schermo()
        fonte = "gap+calendario+schermo" if stato_schermo else "gap+calendario"
        _registra(attivita_cal, ora_str, giorno, fonte)
        return

    # Fallback: tabella probabilistica
    stato_schermo = _get_stato_schermo()
    for (ora_min, ora_max, gap_min_min, gap_min_max, attivita, _) in GAP_INFERENCE_TABLE:
        if (ora_min <= ora_inizio_min < ora_max and
                gap_min_min <= gap_min <= gap_min_max):
            fonte = "gap+schermo" if stato_schermo else "gap"
            _registra(attivita, ora_str, giorno, fonte)
            return


# ══════════════════════════════════════════════════════════════
# SORGENTE 3 — CALENDARIO
# ══════════════════════════════════════════════════════════════

def _inferisci_da_calendario(inizio: datetime.datetime, fine: datetime.datetime) -> str | None:
    """
    Cerca nel calendario Google se c'era un evento nell'intervallo del gap.
    Ritorna il nome attività riconosciuta o None.
    """
    try:
        from actions.tools_calendar import ottieni_servizio_calendario
        service = ottieni_servizio_calendario()

        result = service.events().list(
            calendarId   = "primary",
            timeMin      = inizio.astimezone(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
            timeMax      = fine.astimezone(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
            singleEvents = True,
            orderBy      = "startTime"
        ).execute()

        for event in result.get("items", []):
            titolo = event.get("summary", "").lower()
            for attivita, keywords in CALENDARIO_MAP.items():
                if any(k in titolo for k in keywords):
                    return attivita
    except Exception:
        pass
    return None


def registra_da_calendario(eventi: list):
    """
    Chiamato dal supervisore dopo il precaricamento calendario.
    Estrae attività dagli eventi del giorno e le registra.
    """
    adesso = datetime.datetime.now()
    oggi   = adesso.date()

    for event in eventi:
        try:
            start_str = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
            if not start_str:
                continue
            if "T" not in start_str:
                continue  # evento tutto il giorno — skip

            start_dt = datetime.datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            start_local = start_dt.astimezone().replace(tzinfo=None)

            if start_local.date() != oggi:
                continue

            titolo  = event.get("summary", "").lower()
            giorno  = GIORNI[start_local.weekday()]
            ora_str = start_local.strftime("%H:%M")

            for attivita, keywords in CALENDARIO_MAP.items():
                if any(k in titolo for k in keywords):
                    threading.Thread(
                        target=_registra,
                        args=(attivita, ora_str, giorno, "calendario"),
                        daemon=True
                    ).start()
                    break
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════
# CALCOLO CONFIDENZA
# ══════════════════════════════════════════════════════════════

def _ora_a_minuti(ora: str) -> int:
    """'07:15' → 435"""
    try:
        h, m = ora.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return 0


def _media_circolare_minuti(minuti: list[int]) -> float:
    """
    Media circolare per orari (gestisce il wrap 23:59 → 00:00).
    Usa la media degli angoli sul cerchio delle 24h.
    """
    if not minuti:
        return 0.0
    angoli = [m / (24 * 60) * 2 * math.pi for m in minuti]
    sin_m  = sum(math.sin(a) for a in angoli) / len(angoli)
    cos_m  = sum(math.cos(a) for a in angoli) / len(angoli)
    media  = math.atan2(sin_m, cos_m)
    if media < 0:
        media += 2 * math.pi
    return media / (2 * math.pi) * 24 * 60


def _std_minuti(minuti: list[int], media: float) -> float:
    """Deviazione standard in minuti (con correzione circolare)."""
    if len(minuti) < 2:
        return 0.0
    diffs = []
    for m in minuti:
        d = m - media
        # Corregge wrap: se diff > 12h considera il percorso inverso
        if d > 720:  d -= 1440
        if d < -720: d += 1440
        diffs.append(d ** 2)
    return math.sqrt(sum(diffs) / len(diffs))


def calcola_confidenza(attivita: str, giorno: str) -> dict:
    """
    Calcola confidenza per attività/giorno.
    Ritorna dict con: media_ora, std_min, confidenza, n_osservazioni.
    """
    data = _carica()
    obs  = data.get("osservazioni", {}).get(attivita, {}).get(giorno, [])

    # Filtra osservazioni negli ultimi GIORNI_FINESTRA giorni
    cutoff = (datetime.date.today() - datetime.timedelta(days=GIORNI_FINESTRA)).isoformat()
    obs    = [o for o in obs if o.get("data", "0000") >= cutoff]

    if not obs:
        return {"media_ora": None, "std_min": None, "confidenza": 0.0, "n_osservazioni": 0}

    minuti = [_ora_a_minuti(o["ora"]) for o in obs]
    pesi_v = [PESI.get(o.get("fonte", "gap"), 0.4) for o in obs]

    media   = _media_circolare_minuti(minuti)
    std     = _std_minuti(minuti, media)
    score   = sum(pesi_v)

    # Bonus regolarità
    if std < STD_BONUS_10:   score *= 1.20
    elif std < STD_BONUS_20: score *= 1.10

    # Normalizza: soglia_massima = MIN_OSSERVAZIONI osservazioni keyword perfette
    soglia_max  = MIN_OSSERVAZIONI * PESI["keyword"] * 1.20
    confidenza  = min(100.0, score / soglia_max * 100.0)

    # Converte media in HH:MM
    media_int   = int(round(media))
    media_ora   = f"{media_int // 60:02d}:{media_int % 60:02d}"

    return {
        "media_ora":      media_ora,
        "std_min":        round(std, 1),
        "confidenza":     round(confidenza, 1),
        "n_osservazioni": len(obs),
    }


def get_profilo_giornaliero(giorno: str) -> dict:
    """
    Ritorna il profilo completo per un giorno con confidenza per ogni attività.
    """
    data      = _carica()
    attivita  = list(data.get("osservazioni", {}).keys())
    profilo   = {}
    for att in attivita:
        r = calcola_confidenza(att, giorno)
        if r["n_osservazioni"] > 0:
            profilo[att] = r
    return dict(sorted(
        profilo.items(),
        key=lambda x: _ora_a_minuti(x[1]["media_ora"] or "00:00")
    ))


# ══════════════════════════════════════════════════════════════
# PROPOSTA AGGIORNAMENTO ROUTINE
# ══════════════════════════════════════════════════════════════

def controlla_stabilizzazioni(notifica_fn=None) -> list[dict]:
    """
    Chiamato dal supervisore ogni ora.
    Ritorna lista di attività che hanno raggiunto confidenza >= 80%
    e non sono ancora state notificate.
    Se notifica_fn è passata, invia direttamente la notifica.
    """
    with _lock:
        data    = _carica()
        obs_all = data.get("osservazioni", {})
        gia_not = set(data.get("stabilizzazioni_notificate", []))

    nuove = []
    for attivita, giorni_data in obs_all.items():
        for giorno in GIORNI:
            if giorno not in giorni_data:
                continue
            chiave = f"{attivita}|{giorno}"
            if chiave in gia_not:
                continue
            r = calcola_confidenza(attivita, giorno)
            if r["confidenza"] >= CONFIDENZA_SOGLIA and r["n_osservazioni"] >= MIN_OSSERVAZIONI:
                nuove.append({
                    "attivita": attivita,
                    "giorno":   giorno,
                    "ora":      r["media_ora"],
                    "std":      r["std_min"],
                    "confidenza": r["confidenza"],
                    "chiave":   chiave,
                })

    if not nuove:
        return []

    if notifica_fn:
        for n in nuove:
            giorno_it = {
                "lun":"lunedì","mar":"martedì","mer":"mercoledì",
                "gio":"giovedì","ven":"venerdì","sab":"sabato","dom":"domenica"
            }.get(n["giorno"], n["giorno"])
            msg = (
                f"🧠 Ho imparato che il {giorno_it} fai '{n['attivita']}' "
                f"mediamente alle {n['ora']} (±{n['std']} min, "
                f"{n['confidenza']:.0f}% confidenza). "
                f"Vuoi che aggiunga questa routine alla lista? Rispondi sì o no."
            )
            notifica_fn(msg, n["chiave"])

    return nuove


def conferma_aggiunta_routine(chiave: str):
    """
    Chiamato quando l'utente conferma l'aggiunta.
    Aggiunge alla routine_config.json e segna come notificata.
    """
    try:
        attivita, giorno = chiave.split("|")
        r = calcola_confidenza(attivita, giorno)
        if not r["media_ora"]:
            return

        from tools_routine import _carica_routine, _salva_routine, ROUTINE_PATH
        routine_data = _carica_routine()
        gg_it = {
            "lun":"lun-ven","mar":"lun-ven","mer":"lun-ven",
            "gio":"lun-ven","ven":"lun-ven",
            "sab":"weekend","dom":"weekend"
        }.get(giorno, "tutti")

        # Evita duplicati
        for r_item in routine_data["routine"]:
            if r_item["orario"] == r["media_ora"] and attivita.lower() in r_item["task"].lower():
                return

        routine_data["routine"].append({
            "orario": r["media_ora"],
            "task":   attivita.capitalize(),
            "giorni": gg_it
        })
        routine_data["routine"].sort(key=lambda x: x["orario"])
        _salva_routine(routine_data)

        # Segna come notificata
        with _lock:
            data = _carica()
            notificate = data.setdefault("stabilizzazioni_notificate", [])
            if chiave not in notificate:
                notificate.append(chiave)
            _salva(data)

    except Exception as e:
        print(f"[LEARNING] Errore conferma_aggiunta_routine: {e}")


# ══════════════════════════════════════════════════════════════
# TOOL LANGCHAIN — consultazione profilo
# ══════════════════════════════════════════════════════════════

try:
    from langchain_core.tools import tool
except ImportError:
    # Fallback per ambienti senza langchain_core
    def tool(f):
        return f

@tool
def mostra_profilo_routine(giorno: str = "oggi") -> str:
    """
    Mostra il profilo comportamentale appreso per un giorno.
    Usalo quando l'utente chiede 'cosa faccio di solito il lunedì',
    'qual è la mia routine', 'cosa hai imparato di me', 'mostra profilo'.
    giorno: 'oggi', 'lun', 'mar', 'mer', 'gio', 'ven', 'sab', 'dom'.
    """
    if giorno == "oggi":
        giorno = GIORNI[datetime.datetime.now().weekday()]

    profilo = get_profilo_giornaliero(giorno)
    if not profilo:
        return f"Non ho ancora abbastanza dati per il {giorno}. Continua ad usarmi e imparerò la tua routine."

    giorno_it = {
        "lun":"Lunedì","mar":"Martedì","mer":"Mercoledì",
        "gio":"Giovedì","ven":"Venerdì","sab":"Sabato","dom":"Domenica"
    }.get(giorno, giorno)

    righe = [f"📊 Profilo {giorno_it} appreso:"]
    for att, r in profilo.items():
        barra = "█" * int(r["confidenza"] / 10) + "░" * (10 - int(r["confidenza"] / 10))
        righe.append(
            f"  {att:12s} {r['media_ora']} ±{r['std_min']:.0f}min  "
            f"[{barra}] {r['confidenza']:.0f}%  ({r['n_osservazioni']} obs)"
        )
    return "\n".join(righe)
