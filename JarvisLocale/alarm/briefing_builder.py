import asyncio
import time
from datetime import datetime
import httpx
import ollama

NEWS_API_KEY = "TUA_KEY"
LAT, LON = 44.14, 12.24  # Cesena

# ── Timer ──────────────────────────────────────────────────────
class StepTimer:
    def __init__(self, label: str):
        self.label = label

    def __enter__(self):
        self.start = time.perf_counter()
        print(f"\033[36m[TIMER] ▶ {self.label}...\033[0m")
        return self

    def __exit__(self, *_):
        elapsed = time.perf_counter() - self.start
        color = "\033[32m" if elapsed < 5 else "\033[33m" if elapsed < 30 else "\033[31m"
        print(f"{color}[TIMER] ✓ {self.label} → {elapsed:.2f}s\033[0m")

# ── Fetch paralleli ────────────────────────────────────────────
async def _fetch_weather() -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": LAT, "longitude": LON,
                "hourly": "temperature_2m,precipitation_probability,weathercode",
                "daily": "temperature_2m_max,temperature_2m_min",
                "timezone": "Europe/Rome", "forecast_days": 1
            }
        )
        return r.json()

async def _fetch_news() -> list[str]:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://newsapi.org/v2/top-headlines",
            params={"country": "it", "pageSize": 5, "apiKey": NEWS_API_KEY}
        )
        return [a["title"] for a in r.json().get("articles", [])]

async def _fetch_calendar() -> str:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_authorized_user_file("token.json")
    service = build("calendar", "v3", credentials=creds)
    today = datetime.now().date()
    t_min = datetime.combine(today, datetime.min.time()).isoformat() + "Z"
    t_max = datetime.combine(today, datetime.max.time()).isoformat() + "Z"

    events = service.events().list(
        calendarId="primary", timeMin=t_min, timeMax=t_max,
        singleEvents=True, orderBy="startTime"
    ).execute().get("items", [])

    if not events:
        return ""
    return "; ".join(
        f"{e['summary']} alle {datetime.fromisoformat(e['start']['dateTime']).strftime('%H:%M')}"
        for e in events if "dateTime" in e["start"]
    )

# ── Entry point ────────────────────────────────────────────────
async def generate_briefing(wake_time: datetime, sensor_data: dict) -> str:
    total_start = time.perf_counter()
    print(f"\033[35m[BRIEFING] Inizio preparazione — {datetime.now().strftime('%H:%M:%S')}\033[0m")

    with StepTimer("Fetch meteo + news + calendario (parallelo)"):
        weather, headlines, agenda = await asyncio.gather(
            _fetch_weather(),
            _fetch_news(),
            _fetch_calendar()
        )

    with StepTimer("Lettura sensori ESP32"):
        hour     = datetime.now().hour
        temp_now = sensor_data.get("temp") or weather["hourly"]["temperature_2m"][hour]
        humidity = sensor_data.get("humidity", "N/A")
        co2      = sensor_data.get("co2", "N/A")

    temp_max    = weather["daily"]["temperature_2m_max"][0]
    temp_min    = weather["daily"]["temperature_2m_min"][0]
    rain_chance = max(weather["hourly"]["precipitation_probability"][:12])

    prompt = f"""Sei JARVIS, l'assistente AI di Tony Stark. Genera il briefing mattutino in italiano, stile Iron Man 1.
Diretto, intelligente, leggermente ironico ma sempre efficiente. NON usare elenchi puntati: testo fluido e naturale.

DATI:
- Ora sveglia: {wake_time.strftime('%H:%M')}
- Indoor: {temp_now:.1f}°C | Umidità: {humidity}% | CO2: {co2} ppm
- Meteo: max {temp_max}°C, min {temp_min}°C, probabilità pioggia {rain_chance}%
- Agenda: {agenda if agenda else 'nessun impegno'}
- News: {'; '.join(headlines)}

Struttura fluida: saluto con ora → indoor → meteo + consiglio outfit → agenda → news.
Tra 150 e 200 parole. Prenditi tutto il tempo necessario."""

    with StepTimer("Generazione LLM (qwen3:8b)"):
        response = ollama.chat(
            model="qwen3:8b",
            messages=[{"role": "user", "content": prompt}],
            options={"num_predict": 450, "temperature": 0.8}
        )
        text = response["message"]["content"]

    total = time.perf_counter() - total_start
    print(f"\033[32m[BRIEFING] ✅ Fatto in {total:.2f}s — {len(text.split())} parole\033[0m")
    print(f"\033[90m[BRIEFING] Preview: {text[:80]}...\033[0m")

    return text