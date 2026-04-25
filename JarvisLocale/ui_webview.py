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
from agents.logica_chat import (
    elabora_risposta,
    gestisci_conferma_whatsapp,
    avvia_background,
    cronologia_chat,
    eventi_precaricati,
    posizione_cache,
)
import psutil

from tools_memory import leggi_memoria
from tools_routine import ottieni_sveglie_attive
import esp32_bridge
import agents.tools_mail as tools_mail


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
            return

        # Callbacks UI → chiamano JS
        callbacks = {
            "aggiungi_messaggio": lambda mit, txt, col=None: self._js("aggiungiMessaggio", mit, txt),
            "aggiorna_testo":     lambda txt: self._js("aggiornaUltimoMessaggio", txt),
            "reset_label":        lambda: self._js("resetLabel"),
            "set_stato":          lambda s: self._set_stato_sfera(s),
            "_js_callback":       self._js,
        }

        threading.Thread(
            target=elabora_risposta,
            args=(testo, callbacks),
            daemon=True
        ).start()

    # ── Dati dashboard (chiamati da JS all'avvio o su refresh) ─

    def get_dati_dashboard(self) -> dict:
        """Restituisce tutti i dati necessari alla dashboard in un colpo solo."""
        from agents.logica_chat import eventi_precaricati as ev
        import actions.tools_location as tl
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
            "posizione": tl.posizione_cache,
            "sveglie": sveglie,
            "stato_led": "N/C",
        }

    def get_stato_led(self) -> str:
        return "N/C"

    def get_important_mails(self) -> list:
        """
        Recupera le mail importanti usando il modulo tools_mail.
        Chiamata da JS quando l'utente apre il pannello mail o preme refresh.
        """
        try:
            print("[API] Recupero mail importanti...")
            # 1. Fetch mail recenti non lette (max 15 per velocità UI)
            mail_raw = tools_mail.fetch_mail_recenti(max_mail=15)
            if not mail_raw:
                return []

            # 2. Classificazione LLM
            from agents.logica_chat import llm as _llm
            classificate = tools_mail.classifica_mail_con_llm(mail_raw, _llm)
            
            if not classificate:
                return []

            # 3. Arricchisci con il corpo completo (per la visualizzazione dettaglio)
            # e formatta per la dashboard
            finali = []
            for c in classificate:
                # Trova la mail originale per recuperare il corpo completo (corpo)
                orig = next((m for m in mail_raw if m['id'] == c['mail_id']), None)
                body_full = orig['corpo'] if orig else "Contenuto non disponibile."
                
                finali.append({
                    "id":        c['mail_id'],
                    "oggetto":   c.get('oggetto', 'Senza oggetto'),
                    "mittente":  c.get('mittente', 'Sconosciuto'),
                    "data":      c.get('data_estratta') or orig.get('data', 'N/D') if orig else 'N/D',
                    "riassunto": c.get('riassunto', ''),
                    "body":      body_full,
                    "priorita":  c.get('priorita', 'bassa'),
                    "categoria": c.get('categoria', 'Altro'),
                    "emoji":     c.get('emoji', '📧'),
                    "letta":     False
                })
            
            print(f"[API] Restituisco {len(finali)} mail classificate.")
            return finali

        except Exception as e:
            print(f"[API] Errore get_important_mails: {e}")
            return []

    def reset_chat(self) -> None:
        """Azzera la cronologia chat."""
        from agents.logica_chat import cronologia_chat
        cronologia_chat.clear()

    def apri_meteo_browser(self) -> None:
        """Apre il browser con il meteo per la posizione attuale GPS."""
        import webbrowser
        import actions.tools_location as tl
        import urllib.parse
        city = tl.posizione_cache.split(',')[0].strip() if "," in tl.posizione_cache else tl.posizione_cache.strip()
        if not city or "Sconosciuta" in city:
            query = "meteo oggi"
        else:
            query = f"meteo {city}"
        url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
        webbrowser.open(url)

    # ── Controllo sfera ───────────────────────────────────────

    def _set_stato_sfera(self, stato: str):
        """Aggiorna lo stato della sfera plasma nella UI."""
        self._stato_sfera = stato
        self._js("setStatoSfera", stato)
        # L'aggiornamento dell'ESP32 per gli stati 'speaking' e 'idle' è ora gestito dal modulo TTS
        # per allinearsi precisamente con la durata dell'audio, perciò non invochiamo esp32_bridge qui
        # per non accavallare i comandi temporali. Solo thinking viene gestito qui tramite eccezione dal main.
        if stato in ["sleep", "thinking"]:
            esp32_bridge.set_ai_state(stato)

    def get_stato_sfera(self) -> str:
        return self._stato_sfera

    def _monitor_sistema(self):
        """Thread che invia CPU, RAM, VRAM e stato Arduino/LED a JS ogni 3 secondi."""
        # Inizializza pynvml una volta sola
        _nvml_ok = False
        try:
            import pynvml
            pynvml.nvmlInit()
            _nvml_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            _nvml_info   = pynvml.nvmlDeviceGetMemoryInfo(_nvml_handle)
            _vram_total  = _nvml_info.total / (1024 ** 3)
            _nvml_ok     = True
            print(f"[MONITOR] VRAM totale GPU0: {_vram_total:.1f} GB")
        except Exception as e:
            print(f"[MONITOR] pynvml non disponibile: {e} — installa con: pip install pynvml")

        _ultimo_led_stato = None   # per aggiornare solo quando cambia

        while self._window is not None:
            try:
                # ── CPU ──────────────────────────────────────────────
                cpu = psutil.cpu_percent(interval=1)

                # ── RAM ──────────────────────────────────────────────
                ram        = psutil.virtual_memory()
                ram_used   = ram.used  / (1024 ** 3)
                ram_total  = ram.total / (1024 ** 3)

                # ── VRAM ─────────────────────────────────────────────
                vram_pct = None
                vram_txt = "N/D"
                if _nvml_ok:
                    try:
                        mem_info  = pynvml.nvmlDeviceGetMemoryInfo(_nvml_handle)
                        vram_used = mem_info.used  / (1024 ** 3)
                        vram_tot  = mem_info.total / (1024 ** 3)
                        vram_pct  = (mem_info.used / mem_info.total) * 100
                        vram_txt  = f"{vram_used:.1f} / {vram_tot:.0f} GB"
                    except Exception:
                        pass

                stats = {
                    "cpu_pct":  cpu,
                    "ram_pct":  ram.percent,
                    "ram_txt":  f"{ram_used:.1f} / {ram_total:.0f} GB",
                    "vram_pct": vram_pct,
                    "vram_txt": vram_txt,
                }
                self._js("aggiornaStatsSistema", stats)

                # ── LED / Arduino rimosso ──────────

            except Exception as e:
                print(f"[MONITOR] Errore: {e}")
            time.sleep(3)

    def _monitor_meteo(self):
        """Thread che aggiorna il meteo ogni ora."""
        
        tentativi_attesa = 0
        while self._window is not None:
            try:
                # Usa la posizione rilevata (es: "Milan, Italy")
                import actions.tools_location as tl
                import urllib.parse
                
                # Attendi un po' se la posizione è ancora Sconosciuta all'avvio (max 20 sec)
                if tl.posizione_cache == "Sconosciuta" and tentativi_attesa < 10:
                    time.sleep(2)
                    tentativi_attesa += 1
                    continue
                    
                city = tl.posizione_cache.split(',')[0].strip() if "," in tl.posizione_cache else tl.posizione_cache.strip()
                if not city or "Sconosciuta" in city:
                    city_param = "" # Lascia decidere a wttr.in in base all'IP
                else:
                    city_param = urllib.parse.quote(city)

                resp = requests.get(f"http://wttr.in/{city_param}?format=j1", timeout=10).json()
                # wttr.in j1 format wraps everything in a 'data' key
                data_res = resp.get('data', {})
                if 'current_condition' in data_res and data_res['current_condition']:
                    curr = data_res['current_condition'][0]
                    
                    # Mapping icone base
                    code = curr.get('weatherCode', '0')
                    # https://www.worldweatheronline.com/feed/wwo-codes.txt
                    icon = "☀️" # clear
                    if code in ["116"]: icon = "⛅" # partly cloudy
                    elif code in ["119", "122"]: icon = "☁️" # cloudy/overcast
                    elif code in ["143", "248", "260"]: icon = "🌫️" # fog
                    elif code in ["176", "263", "266", "293", "296", "299", "302", "305", "308"]: icon = "🌧️" # rain
                    elif code in ["200", "386", "389"]: icon = "⛈️" # thunder
                    elif code in ["227", "230", "323", "326", "329", "332", "335", "338"]: icon = "❄️" # snow

                    data = {
                        "temp": curr.get('temp_C', '??'),
                        "desc": curr['lang_it'][0]['value'] if 'lang_it' in curr and curr['lang_it'] else (curr['weatherDesc'][0]['value'] if 'weatherDesc' in curr and curr['weatherDesc'] else "N/D"),
                        "icon": icon,
                        "hum": curr.get('humidity', '??') + "%",
                        "wind": curr.get('windspeedKmph', '??') + " km/h",
                        "feels": curr.get('FeelsLikeC', '??'),
                        "uv": curr.get('uvIndex', '??'),
                        "city": city
                    }
                    self._js("aggiornaMeteo", data)
                    print(f"☁️ Meteo aggiornato per {city or 'tua posizione'}: {data['temp']}°C, {data['desc']}")
                else:
                    print(f"☁️ Meteo per {city or 'tua posizione'}: dati non trovati nel JSON.")
            except Exception as e:
                print(f"Error weather monitor: {e}")
            
            # Reset dei tentativi per i cicli futuri
            tentativi_attesa = 10
            
            # Aspetta 1 ora (3600 secondi)
            time.sleep(3600)

    def _monitor_calendario(self):
        """Thread che aggiorna il calendario nella UI quando cambia in background."""
        import time
        _ultimo_ev = None
        while self._window is not None:
            try:
                from agents.logica_chat import eventi_precaricati as ev
                if ev != _ultimo_ev and "Non sono ancora" not in ev and "Caricamento" not in ev:
                    self._js("aggiornaCalendario", ev)
                    print("📅 Calendario precaricato inviato alla Dashboard.")
                    _ultimo_ev = ev
            except Exception as e:
                pass
            time.sleep(2)


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

    esp32_bridge.inizializza()
    api = IDISApi()

    # Percorso assoluto all'HTML della dashboard
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "idis_dashboard.html")

    window = webview.create_window(
        title="IDIS",
        url=html_path,
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
        api._set_stato_sfera("idle")
        # Avvia monitoraggio sistema e meteo
        threading.Thread(target=api._monitor_sistema, daemon=True).start()
        threading.Thread(target=api._monitor_meteo, daemon=True).start()
        threading.Thread(target=api._monitor_calendario, daemon=True).start()

    window.events.loaded += on_loaded
    
    def on_closing():
        print("[IDIS] Chiusura applicazione... Mando in sleep l'ESP32.")
        esp32_bridge.set_ai_state("sleep")
        import time
        time.sleep(0.5) # Diamo il tempo alla seriale di inviare il comando
        esp32_bridge.ferma()
        
    window.events.closing += on_closing

    # Avvia PyWebView (bloccante)
    webview.start(debug=False)