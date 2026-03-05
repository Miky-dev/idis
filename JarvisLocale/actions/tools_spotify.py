import os
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from langchain_core.tools import tool
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURAZIONE ---
SPOTIFY_SCOPES = " ".join([
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "playlist-read-private",
    "playlist-read-collaborative",
    "streaming"
])

# Cache del client — autenticato una sola volta
_spotify_client = None

def ottieni_client() -> spotipy.Spotify:
    """Restituisce il client Spotify autenticato, creandolo una sola volta."""
    global _spotify_client
    if _spotify_client is not None:
        return _spotify_client

    auth_manager = SpotifyOAuth(
        client_id=os.getenv("SPOTIFY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
        redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback"),
        scope=SPOTIFY_SCOPES,
        cache_path=".spotify_cache",   # salva il token su disco — non richiede login ad ogni avvio
        open_browser=True
    )

    _spotify_client = spotipy.Spotify(auth_manager=auth_manager)
    return _spotify_client


def ottieni_dispositivo_attivo() -> str | None:
    """Restituisce l'ID del primo dispositivo Spotify attivo trovato."""
    sp = ottieni_client()
    dispositivi = sp.devices()
    lista = dispositivi.get("devices", [])
    if not lista:
        return None
    # Preferisce il dispositivo già attivo, altrimenti prende il primo disponibile
    for d in lista:
        if d["is_active"]:
            return d["id"]
    return lista[0]["id"]


# ─────────────────────────────────────────────────────────────
# TOOL — Riproduci canzone
# ─────────────────────────────────────────────────────────────
@tool
def riproduci_canzone(titolo: str, artista: str = "") -> str:
    """
    Cerca e riproduce una canzone su Spotify.
    - 'titolo': titolo della canzone (es. "Bohemian Rhapsody")
    - 'artista': nome dell'artista (opzionale, migliora la ricerca, es. "Queen")
    """
    try:
        sp = ottieni_client()
        dispositivo = ottieni_dispositivo_attivo()
        if not dispositivo:
            return "Nessun dispositivo Spotify attivo trovato. Apri Spotify sul PC o sul telefono."

        query = f"track:{titolo}"
        if artista:
            query += f" artist:{artista}"

        risultati = sp.search(q=query, type="track", limit=1)
        tracce = risultati.get("tracks", {}).get("items", [])

        if not tracce:
            return f"Canzone '{titolo}' non trovata su Spotify."

        traccia = tracce[0]
        uri = traccia["uri"]
        nome = traccia["name"]
        artista_trovato = traccia["artists"][0]["name"]

        sp.start_playback(device_id=dispositivo, uris=[uri])
        return f"In riproduzione: {nome} — {artista_trovato}"

    except spotipy.exceptions.SpotifyException as e:
        if "Premium" in str(e) or "403" in str(e):
            return "Errore: il controllo della riproduzione richiede Spotify Premium."
        return f"Errore Spotify: {str(e)}"
    except Exception as e:
        return f"Errore: {str(e)}"


# ─────────────────────────────────────────────────────────────
# TOOL — Riproduci playlist
# ─────────────────────────────────────────────────────────────
@tool
def riproduci_playlist(nome_playlist: str) -> str:
    """
    Cerca e riproduce una playlist Spotify (tra le tue playlist o quelle pubbliche).
    - 'nome_playlist': nome della playlist (es. "Chill vibes", "Workout", "Liked Songs")
    """
    try:
        sp = ottieni_client()
        dispositivo = ottieni_dispositivo_attivo()
        if not dispositivo:
            return "Nessun dispositivo Spotify attivo trovato. Apri Spotify sul PC o sul telefono."

        # Cerca prima tra le playlist dell'utente
        playlists_utente = sp.current_user_playlists(limit=50)
        nome_lower = nome_playlist.lower()

        playlist_trovata = None
        for pl in playlists_utente.get("items", []):
            if pl and nome_lower in pl["name"].lower():
                playlist_trovata = pl
                break

        # Se non trovata tra le proprie, cerca globalmente
        if not playlist_trovata:
            risultati = sp.search(q=nome_playlist, type="playlist", limit=1)
            playlists = risultati.get("playlists", {}).get("items", [])
            if playlists:
                playlist_trovata = playlists[0]

        if not playlist_trovata:
            return f"Playlist '{nome_playlist}' non trovata."

        uri = playlist_trovata["uri"]
        nome = playlist_trovata["name"]

        sp.start_playback(device_id=dispositivo, context_uri=uri)
        return f"In riproduzione playlist: {nome}"

    except spotipy.exceptions.SpotifyException as e:
        if "Premium" in str(e) or "403" in str(e):
            return "Errore: il controllo della riproduzione richiede Spotify Premium."
        return f"Errore Spotify: {str(e)}"
    except Exception as e:
        return f"Errore: {str(e)}"


# ─────────────────────────────────────────────────────────────
# TOOL — Controlli base (pausa, riprendi, skip, volume)
# ─────────────────────────────────────────────────────────────
@tool
def controlla_spotify(azione: str, valore: int = 0) -> str:
    """
    Controlla la riproduzione Spotify in corso.
    - 'azione': una tra — 'pausa', 'riprendi', 'avanti', 'indietro', 'volume'
    - 'valore': usato solo con 'volume' — numero da 0 a 100 (es. 50)

    Esempi:
    - Metti in pausa → azione='pausa'
    - Canzone successiva → azione='avanti'
    - Alza il volume a 80 → azione='volume', valore=80
    """
    try:
        sp = ottieni_client()
        dispositivo = ottieni_dispositivo_attivo()
        if not dispositivo:
            return "Nessun dispositivo Spotify attivo trovato."

        azione = azione.lower().strip()

        if azione in ["pausa", "stop", "ferma"]:
            sp.pause_playback(device_id=dispositivo)
            return "Riproduzione messa in pausa."

        elif azione in ["riprendi", "play", "continua"]:
            sp.start_playback(device_id=dispositivo)
            return "Riproduzione ripresa."

        elif azione in ["avanti", "skip", "prossima", "next"]:
            sp.next_track(device_id=dispositivo)
            return "Canzone successiva."

        elif azione in ["indietro", "precedente", "back"]:
            sp.previous_track(device_id=dispositivo)
            return "Canzone precedente."

        elif azione in ["volume"]:
            vol = max(0, min(100, valore))
            sp.volume(vol, device_id=dispositivo)
            return f"Volume impostato a {vol}%."

        else:
            return f"Azione '{azione}' non riconosciuta. Usa: pausa, riprendi, avanti, indietro, volume."

    except spotipy.exceptions.SpotifyException as e:
        if "Premium" in str(e) or "403" in str(e):
            return "Errore: il controllo della riproduzione richiede Spotify Premium."
        return f"Errore Spotify: {str(e)}"
    except Exception as e:
        return f"Errore: {str(e)}"


# ─────────────────────────────────────────────────────────────
# TOOL — Cosa sta suonando
# ─────────────────────────────────────────────────────────────
@tool
def cosa_sta_suonando() -> str:
    """
    Restituisce il titolo e l'artista della canzone attualmente in riproduzione su Spotify.
    Usalo quando l'utente chiede 'cosa sta suonando?', 'che canzone è?', 'chi canta questa?'
    """
    try:
        sp = ottieni_client()
        corrente = sp.current_playback()

        if not corrente or not corrente.get("is_playing"):
            return "Spotify non sta riproducendo nulla al momento."

        item = corrente.get("item")
        if not item:
            return "Impossibile ottenere informazioni sulla canzone corrente."

        nome = item["name"]
        artisti = ", ".join([a["name"] for a in item["artists"]])
        album = item["album"]["name"]
        return f"In riproduzione: {nome} — {artisti} (Album: {album})"

    except Exception as e:
        return f"Errore: {str(e)}"


@tool
def lista_dispositivi_spotify() -> str:
    """Mostra tutti i dispositivi Spotify disponibili. Usalo per diagnosticare problemi."""
    try:
        sp = ottieni_client()
        dispositivi = sp.devices()
        lista = dispositivi.get("devices", [])
        if not lista:
            return "Nessun dispositivo trovato. Apri Spotify e riproduci qualcosa manualmente."
        risultato = "Dispositivi trovati:\n"
        for d in lista:
            risultato += f"- {d['name']} ({d['type']}) — attivo: {d['is_active']} — id: {d['id']}\n"
        return risultato
    except Exception as e:
        return f"Errore: {str(e)}"