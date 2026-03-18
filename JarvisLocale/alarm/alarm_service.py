import asyncio
import threading
import time
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import APIRouter

from alarm.briefing_builder import generate_briefing
from actions.tools_tts import parla as speak
from esp32_bridge import sensor_data

router    = APIRouter()
scheduler = BackgroundScheduler()

alarm_state     = {"ring": False}
_briefing_cache = {"text": None, "wake_time": None}


def _run_async(coro):
    """Esegue una coroutine asyncio dal BackgroundScheduler (thread sync)."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(coro)
    finally:
        loop.close()


# ── Endpoints ──────────────────────────────────────────────────

@router.post("/sensors")
async def receive_sensors(data: dict):
    sensor_data.update(data)
    return {"ok": True}


@router.get("/alarm/check")
async def check_alarm():
    return {"ring": alarm_state["ring"]}


@router.post("/alarm/test")
async def test_alarm():
    """Triggera la sveglia tra 60 secondi per testare."""
    wake_time = datetime.now() + timedelta(seconds=60)
    _briefing_cache["wake_time"] = wake_time
    scheduler.add_job(
        _run_async, "date",
        run_date=datetime.now() + timedelta(seconds=5),
        id="prep_test", replace_existing=True,
        args=[prepare_briefing()]
    )
    scheduler.add_job(
        _run_async, "date",
        run_date=wake_time,
        id="alarm_test", replace_existing=True,
        args=[trigger_alarm()]
    )
    print(f"\033[35m[ALARM] Test avviato — sveglia alle {wake_time.strftime('%H:%M:%S')}\033[0m")
    return {"ok": True, "sveglia_alle": wake_time.strftime("%H:%M:%S")}


# ── Scheduler notturno (ogni notte 23:00) ─────────────────────

async def schedule_alarm_from_calendar():
    print(f"\033[35m[ALARM] Calcolo sveglia per domani...\033[0m")
    t_start = time.perf_counter()

    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds   = Credentials.from_authorized_user_file(r"C:\MikyDesktop\COSE\progetti\EDITH\idis\token_mail.json")
    service = build("calendar", "v3", credentials=creds)

    tomorrow = (datetime.now() + timedelta(days=1)).date()
    t_min = datetime.combine(tomorrow, datetime.min.time()).isoformat() + "Z"
    t_max = datetime.combine(tomorrow, datetime.strptime("12:00", "%H:%M").time()).isoformat() + "Z"

    events = service.events().list(
        calendarId="primary", timeMin=t_min, timeMax=t_max,
        singleEvents=True, orderBy="startTime"
    ).execute().get("items", [])

    if events:
        first     = datetime.fromisoformat(events[0]["start"]["dateTime"])
        wake_time = first - timedelta(hours=1, minutes=30)
        print(f"\033[35m[ALARM] Primo evento: {events[0]['summary']} alle {first.strftime('%H:%M')}\033[0m")
    else:
        wake_time = datetime.combine(tomorrow, datetime.strptime("09:15", "%H:%M").time())
        print(f"\033[35m[ALARM] Nessun evento → sveglia default alle 09:15\033[0m")

    prep_time = wake_time - timedelta(minutes=20)
    _briefing_cache["wake_time"] = wake_time

    elapsed = time.perf_counter() - t_start
    print(f"\033[32m[ALARM] ✓ Sveglia → {wake_time.strftime('%H:%M')} | Prep → {prep_time.strftime('%H:%M')} ({elapsed:.2f}s)\033[0m")

    scheduler.add_job(
        _run_async, "date", run_date=prep_time,
        id="prep", replace_existing=True,
        args=[prepare_briefing()]
    )
    scheduler.add_job(
        _run_async, "date", run_date=wake_time,
        id="alarm", replace_existing=True,
        args=[trigger_alarm()]
    )


# ── Preparazione briefing (T-20min) ───────────────────────────

async def prepare_briefing():
    wake_time = _briefing_cache.get("wake_time") or datetime.now() + timedelta(minutes=20)
    print(f"\033[35m[BRIEFING] Avvio preparazione — sveglia alle {wake_time.strftime('%H:%M')}\033[0m")
    try:
        text = await generate_briefing(wake_time=wake_time, sensor_data=sensor_data)
        _briefing_cache["text"] = text
        print(f"\033[32m[BRIEFING] ✓ Pronto ({len(text.split())} parole)\033[0m")
    except Exception as e:
        print(f"\033[31m[BRIEFING] ❌ Errore: {e}\033[0m")
        _briefing_cache["text"] = None


# ── Trigger sveglia (T-0) ──────────────────────────────────────

async def trigger_alarm():
    print(f"\033[31m[ALARM] 🔔 SVEGLIA — {datetime.now().strftime('%H:%M:%S')}\033[0m")

    text = _briefing_cache.get("text")
    if not text:
        print(f"\033[33m[ALARM] ⚠ Briefing non pronto, rigenerazione...\033[0m")
        await prepare_briefing()
        text = _briefing_cache.get("text", "Buongiorno. Il briefing non è disponibile.")

    # Suono wake
    try:
        from actions import tools_sounds
        tools_sounds.wake()
        await asyncio.sleep(0.8)
    except Exception:
        pass

    t_start = time.perf_counter()
    print(f"\033[36m[TIMER] ▶ TTS speak...\033[0m")
    speak(text, bloccante=True)
    elapsed = time.perf_counter() - t_start
    print(f"\033[32m[TIMER] ✓ TTS speak → {elapsed:.2f}s\033[0m")

    alarm_state["ring"] = True
    await asyncio.sleep(60)
    alarm_state["ring"] = False
    _briefing_cache["text"] = None
    print(f"\033[35m[ALARM] Sveglia terminata.\033[0m")


# ── Avvio scheduler ────────────────────────────────────────────

def start_scheduler():
    scheduler.add_job(
        _run_async, "cron", hour=23, minute=0,
        args=[schedule_alarm_from_calendar()]
    )
    scheduler.start()
    print(f"\033[32m[ALARM] Scheduler avviato — prossimo calcolo sveglia alle 23:00\033[0m")