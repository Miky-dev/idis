import subprocess
import requests
from langchain_core.tools import tool

# Cache globale per la UI e il prompt
posizione_cache = "Sconosciuta"

@tool
def ottieni_posizione() -> str:
    """
    Rileva e restituisce l'attuale posizione geografica dell'utente via GPS.
    Usa questa funzione quando l'utente chiede dove si trova o per ottenere coordinate più precise per il meteo.
    """
    global posizione_cache
    try:
        # Prendi posizione via GPS (Servizi di Localizzazione Windows)
        ps_script = """
Add-Type -AssemblyName System.Device
$w = New-Object System.Device.Location.GeoCoordinateWatcher
$w.Start()
for ($i=0; $i -lt 50; $i++) {
    if ($w.Status -eq 'Ready' -or $w.Permission -eq 'Denied') { break }
    Start-Sleep -Milliseconds 100
}
if ($w.Permission -eq 'Denied') { Write-Output "Denied" }
elseif ($w.Status -eq 'Ready') { Write-Output "$($w.Position.Location.Latitude),$($w.Position.Location.Longitude)" }
else { Write-Output "NotReady" }
$w.Stop()
"""
        result = subprocess.run(["powershell", "-Command", ps_script], capture_output=True, text=True, timeout=10)
        gps_output = result.stdout.strip()
        
        if "," in gps_output:
            lat, lon = gps_output.split(",")
            # Reverse geocoding tramite Nominatim (OpenStreetMap)
            try:
                url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}"
                headers = {'User-Agent': 'IDIS-Assistant/1.0'}
                r_geo = requests.get(url, headers=headers, timeout=5).json()
                address = r_geo.get("address", {})
                
                # Cerca il nome del luogo più accurato (città, paese, villaggio, comune)
                citta = (address.get("city") or address.get("town") or 
                         address.get("village") or address.get("municipality") or 
                         address.get("county"))
                
                paese = address.get("country", "")
                
                if citta:
                    posizione_cache = f"{citta}, {paese}".strip(", ")
                    print(f"📍 Posizione rilevata via GPS (Geocodificata): {posizione_cache}")
                    return f"Posizione rilevata (GPS): {posizione_cache}"
                else:
                    # Fallback alle coordinate se non trova il nome
                    posizione_cache = gps_output
                    print(f"📍 Posizione rilevata via GPS (Coordinate): {posizione_cache}")
                    return f"Posizione rilevata (GPS - Coordinate): {posizione_cache}"
            except Exception as e:
                print(f"⚠️ Errore reverse geocoding: {e}")
                posizione_cache = gps_output
                return f"Posizione rilevata (GPS): {posizione_cache}"
    except Exception as e:
        print(f"⚠️ Errore acquisizione GPS: {e}")

    # Fallback IP
    try:
        risposta_ip = requests.get("http://ip-api.com/json/", timeout=3).json()
        posizione_cache = f"{risposta_ip.get('city')}, {risposta_ip.get('country')}"
        print(f"📍 Posizione rilevata (IP Fallback): {posizione_cache}")
        return f"Posizione rilevata (IP): {posizione_cache}"
    except Exception as e:
        posizione_cache = "Sconosciuta (Offline)"
        return "Impossibile rilevare la posizione (Offline)."

