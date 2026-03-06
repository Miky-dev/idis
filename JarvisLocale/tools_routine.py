import datetime
import threading
import time
import json
import os
import uuid
import winsound
from langchain_core.tools import tool
import dateparser

# ══════════════════════════════════════════════════════════════
# SVEGLIE
# ══════════════════════════════════════════════════════════════

sveglie_attive = {}

def esegui_allarme(id_sveglia: str, secondi_attesa: int, messaggio: str):
    try:
        time.sleep(secondi_attesa)
        try:
            winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS)
        except:
            pass
        import tkinter as tk
        import tkinter.messagebox
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        tkinter.messagebox.showinfo("IDIS — Promemoria", messaggio, parent=root)
        root.destroy()
    finally:
        sveglie_attive.pop(id_sveglia, None)

def ottieni_sveglie_attive():
    return dict(sveglie_attive)

@tool
def imposta_sveglia(orario: str, messaggio: str = "Promemoria") -> str:
    """
    Imposta una sveglia o promemoria sul computer.
    - 'orario': orario esatto ("15:30") o delta ("tra 10 minuti", "tra 1 ora").
    - 'messaggio': testo mostrato quando suona.
    """
    try:
        adesso = datetime.datetime.now()
        data_sveglia = dateparser.parse(orario, languages=['it'], settings={'PREFER_DATES_FROM': 'future'})
        if not data_sveglia:
            return f"Non ho capito l'orario '{orario}'. Usa 'tra 15 minuti' o 'alle 18:00'."
        if data_sveglia < adesso:
            data_sveglia += datetime.timedelta(days=1)
        secondi_attesa = int((data_sveglia - adesso).total_seconds())
        if secondi_attesa <= 0:
            return "L'orario specificato e gia passato."
        id_sveglia = uuid.uuid4().hex[:8]
        sveglie_attive[id_sveglia] = {"orario": data_sveglia.strftime('%H:%M'), "messaggio": messaggio}
        threading.Thread(target=esegui_allarme, args=(id_sveglia, secondi_attesa, messaggio), daemon=True).start()
        return f"Sveglia impostata per le {data_sveglia.strftime('%d/%m alle %H:%M')} — '{messaggio}'"
    except Exception as e:
        return f"Errore sveglia: {str(e)}"

# ══════════════════════════════════════════════════════════════
# ROUTINE
# ══════════════════════════════════════════════════════════════

ROUTINE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "routine_config.json")

def _carica_routine() -> dict:
    try:
        if os.path.exists(ROUTINE_PATH):
            with open(ROUTINE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"routine": []}

def _salva_routine(data: dict):
    with open(ROUTINE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@tool
def leggi_routine() -> str:
    """
    Mostra tutte le routine quotidiane configurate.
    Usalo quando l'utente chiede quali abitudini o routine ha impostato.
    """
    data = _carica_routine()
    routine = data.get("routine", [])
    if not routine:
        return "Non hai ancora nessuna routine impostata."
    righe = [f"- {r['orario']} -> {r['task']} ({r.get('giorni', 'tutti i giorni')})" for r in routine]
    return "Routine quotidiane:\n" + "\n".join(righe)

@tool
def aggiungi_alla_routine(orario: str, task: str, giorni: str = "tutti") -> str:
    """
    Aggiunge una nuova attivita ricorrente alla routine quotidiana.
    - 'orario': formato HH:MM (es. "08:00", "14:30").
    - 'task': descrizione (es. "Bevi un bicchiere d acqua").
    - 'giorni': "tutti", "lun-ven", "weekend". Default: "tutti".
    """
    try:
        orario_pulito = orario.strip().replace("alle ", "").replace("alle", "").strip()
        if ":" not in orario_pulito:
            orario_pulito = orario_pulito.zfill(2) + ":00"
        datetime.datetime.strptime(orario_pulito, "%H:%M")
        data = _carica_routine()
        for r in data["routine"]:
            if r["orario"] == orario_pulito and r["task"].lower() == task.lower():
                return f"La routine '{task}' alle {orario_pulito} esiste gia."
        data["routine"].append({"orario": orario_pulito, "task": task, "giorni": giorni})
        data["routine"].sort(key=lambda x: x["orario"])
        _salva_routine(data)
        return f"Routine aggiunta: alle {orario_pulito} -> '{task}' ({giorni})."
    except ValueError:
        return f"Orario non valido '{orario}'. Usa formato HH:MM."
    except Exception as e:
        return f"Errore: {str(e)}"

@tool
def rimuovi_dalla_routine(orario: str, task: str = "") -> str:
    """
    Rimuove una routine esistente.
    - 'orario': orario della routine da rimuovere (HH:MM).
    - 'task': opzionale, parola chiave per disambiguare se ci sono piu routine allo stesso orario.
    """
    try:
        data = _carica_routine()
        n = len(data["routine"])
        data["routine"] = [
            r for r in data["routine"]
            if not (r["orario"] == orario and (not task or task.lower() in r["task"].lower()))
        ]
        if len(data["routine"]) < n:
            _salva_routine(data)
            return f"Routine delle {orario} rimossa."
        return f"Nessuna routine trovata per le {orario}."
    except Exception as e:
        return f"Errore: {str(e)}"