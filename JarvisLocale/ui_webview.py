"""
ui_webview.py — Finestra PyWebView per IDIS Dashboard.
Espone l'API Python al JavaScript della dashboard tramite js_api.
"""

import webview
import threading
import os
import json
import time
import requests
from logica_chat import (
    elabora_risposta,
    gestisci_conferma_whatsapp,
    avvia_background,
    cronologia_chat,
    eventi_precaricati,
    posizione_cache,
)
import psutil
from tools_arduino import get_stato_led
from tools_memory import leggi_memoria
from tools_routine import ottieni_sveglie_attive


# ══════════════════════════════════════════════════════════════
# API BRIDGE — tutti i metodi qui sono chiamabili da JavaScript
# ══════════════════════════════════════════════════════════════

class IDISApi:
    """
    Classe esposta a JavaScript tramite PyWebView js_api.
    Ogni metodo pubblico diventa chiamabile con: window.pywebview.api.nome_metodo()
    """

    def __init__(self):
        self._window = None          # Impostato dopo la creazione della finestra
        self._stato_sfera = "sleep"  # sleep | idle | thinking | speaking
        self._typing_timer = None

    def set_window(self, window):
        self._window = window

    # ── Invio messaggi dalla chat ─────────────────────────────

    def invia_messaggio(self, testo: str) -> None:
        """Chiamato da JS quando l'utente invia un messaggio dalla chat."""
        testo = testo.strip()
        if not testo:
            return

        # Gestisci conferme WhatsApp senza passare dall'LLM
        risultato_wa = gestisci_conferma_whatsapp(testo)
        if risultato_wa is not None:
            self._js("aggiungiMessaggio", "🤖 IDIS", risultato_wa)
            self._set_stato_sfera("sleep")
            return

        # Callbacks UI → chiamano JS
        callbacks = {
            "aggiungi_messaggio": lambda mit, txt, col=None: self._js("aggiungiMessaggio", mit, txt),
            "aggiorna_testo":     lambda txt: self._js("aggiornaUltimoMessaggio", txt),
            "reset_label":        lambda: self._js("resetLabel"),
            "set_stato":          lambda s: self._set_stato_sfera(s),
        }

        threading.Thread(
            target=elabora_risposta,
            args=(testo, callbacks),
            daemon=True
        ).start()

    def notifica_scrittura(self) -> None:
        """Chiamato da JS mentre l'utente digita."""
        if self._stato_sfera == "sleep":
            self._set_stato_sfera("idle")
            
        # Gestione timer per tornare a sleep dopo 5 secondi di inattività
        if self._typing_timer:
            self._typing_timer.cancel()
            
        def _scaduto():
            if self._stato_sfera == "idle":
                self._set_stato_sfera("sleep")
        
        self._typing_timer = threading.Timer(5.0, _scaduto)
        self._typing_timer.start()

    # ── Dati dashboard (chiamati da JS all'avvio o su refresh) ─

    def get_dati_dashboard(self) -> dict:
        """Restituisce tutti i dati necessari alla dashboard in un colpo solo."""
        from logica_chat import eventi_precaricati as ev, posizione_cache as pos
        sveglie = []
        try:
            sveglie_raw = ottieni_sveglie_attive.invoke({})
            sveglie = json.loads(sveglie_raw) if isinstance(sveglie_raw, str) else sveglie_raw
        except Exception:
            sveglie = []

        memoria = {}
        try:
            memoria = leggi_memoria() or {}
        except Exception:
            pass

        return {
            "eventi_calendario": ev,
            "posizione": pos,
            "sveglie": sveglie,
            "memoria": memoria,
            "stato_led": get_stato_led(),
        }

    def get_stato_led(self) -> str:
        return get_stato_led()

    def reset_chat(self) -> None:
        """Azzera la cronologia chat."""
        from logica_chat import cronologia_chat
        cronologia_chat.clear()

    # ── Controllo sfera ───────────────────────────────────────

    def _set_stato_sfera(self, stato: str):
        """Aggiorna lo stato della sfera plasma nella UI."""
        self._stato_sfera = stato
        self._js("setStatoSfera", stato)

    def get_stato_sfera(self) -> str:
        return self._stato_sfera

    def _monitor_sistema(self):
        """Thread che invia statistiche di sistema a JS ogni 3 secondi."""
        while self._window is not None:
            try:
                cpu = psutil.cpu_percent(interval=1)
                ram = psutil.virtual_memory()
                used_gb = ram.used / (1024 ** 3)
                total_gb = ram.total / (1024 ** 3)
                
                stats = {
                    "cpu_pct": cpu,
                    "ram_pct": ram.percent,
                    "ram_txt": f"{used_gb:.1f} / {total_gb:.0f} GB"
                }
                self._js("aggiornaStatsSistema", stats)
            except Exception as e:
                print(f"Error monitor: {e}")
            time.sleep(2)

    def _monitor_meteo(self):
        """Thread che aggiorna il meteo ogni ora."""
        while self._window is not None:
            try:
                # Usa la posizione rilevata (es: "Milan, Italy")
                from logica_chat import posizione_cache
                city = posizione_cache.split(',')[0] if "," in posizione_cache else posizione_cache
                if not city or "Sconosciuta" in city:
                    city = "" # Lascia decidere a wttr.in in base all'IP

                resp = requests.get(f"http://wttr.in/{city}?format=j1", timeout=5).json()
                curr = resp['current_condition'][0]
                
                # Mapping icone base
                code = curr['weatherCode']
                # https://www.worldweatheronline.com/feed/wwo-codes.txt
                icon = "☀️" # clear
                if code in ["116"]: icon = "⛅" # partly cloudy
                elif code in ["119", "122"]: icon = "☁️" # cloudy/overcast
                elif code in ["143", "248", "260"]: icon = "🌫️" # fog
                elif code in ["176", "263", "266", "293", "296", "299", "302", "305", "308"]: icon = "🌧️" # rain
                elif code in ["200", "386", "389"]: icon = "⛈️" # thunder
                elif code in ["227", "230", "323", "326", "329", "332", "335", "338"]: icon = "❄️" # snow

                data = {
                    "temp": curr['temp_C'],
                    "desc": curr['lang_it'][0]['value'] if 'lang_it' in curr else curr['weatherDesc'][0]['value'],
                    "icon": icon,
                    "hum": curr['humidity'] + "%",
                    "wind": curr['windspeedKmph'] + " km/h",
                    "feels": curr['FeelsLikeC'],
                    "uv": curr['uvIndex']
                }
                self._js("aggiornaMeteo", data)
                print(f"☁️ Meteo aggiornato per {city or 'tua posizione'}: {data['temp']}°C, {data['desc']}")
            except Exception as e:
                print(f"Error weather monitor: {e}")
            
            # Aspetta 1 ora (3600 secondi)
            time.sleep(3600)

    # ── Helper JS ─────────────────────────────────────────────

    def _js(self, func: str, *args):
        """Chiama una funzione JavaScript nella finestra."""
        if self._window is None:
            return
        try:
            args_json = ", ".join(json.dumps(a, ensure_ascii=False) for a in args)
            self._window.evaluate_js(f"{func}({args_json})")
        except Exception as e:
            print(f"[JS Error] {func}: {e}")


# ══════════════════════════════════════════════════════════════
# AVVIO FINESTRA
# ══════════════════════════════════════════════════════════════

def avvia_ui():
    """Crea e avvia la finestra PyWebView. Bloccante — va chiamata dal main thread."""

    api = IDISApi()

    # Percorso assoluto all'HTML della dashboard
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "idis_dashboard.html")

    window = webview.create_window(
        title="IDIS",
        url=f"file:///{html_path}".replace("\\", "/"),
        js_api=api,
        width=1200,
        height=800,
        fullscreen=False,
        frameless=False,       # True = niente barra del titolo (stile app moderna)
        easy_drag=True,
        min_size=(1024, 600),
    )

    api.set_window(window)

    # Quando la finestra è pronta, passa i dati iniziali a JS
    def on_loaded():
        import time
        time.sleep(0.5)  # Piccolo delay per sicurezza DOM
        dati = api.get_dati_dashboard()
        api._js("inizializzaDashboard", dati)
        api._set_stato_sfera("sleep")
        # Avvia monitoraggio sistema e meteo
        threading.Thread(target=api._monitor_sistema, daemon=True).start()
        threading.Thread(target=api._monitor_meteo, daemon=True).start()

    window.events.loaded += on_loaded

    # Avvia PyWebView (bloccante)
    webview.start(debug=False)