import os
import shutil
import ctypes
from ctypes import wintypes
from langchain_core.tools import tool

# GUIDs per le cartelle note di Windows
FOLDERID_Desktop = ctypes.c_buffer(
    b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00', 16)
ctypes.windll.ole32.IIDFromString(
    ctypes.c_wchar_p("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}"), FOLDERID_Desktop)

FOLDERID_Downloads = ctypes.c_buffer(
    b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00', 16)
ctypes.windll.ole32.IIDFromString(
    ctypes.c_wchar_p("{374DE290-123F-4565-9164-39C4925E467B}"), FOLDERID_Downloads)

FOLDERID_Documents = ctypes.c_buffer(
    b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00', 16)
ctypes.windll.ole32.IIDFromString(
    ctypes.c_wchar_p("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}"), FOLDERID_Documents)


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", wintypes.BYTE * 8)
    ]

def get_known_folder_path(folder_id):
    path_ptr = ctypes.c_wchar_p()
    # 0 = KF_FLAG_DEFAULT
    result = ctypes.windll.shell32.SHGetKnownFolderPath(
        ctypes.byref(folder_id), 0, None, ctypes.byref(path_ptr))
    if result == 0:
        path = path_ptr.value
        ctypes.windll.ole32.CoTaskMemFree(path_ptr)
        return path
    return ""

def get_guid_from_bytes(byte_buffer):
    guid = GUID()
    ctypes.memmove(ctypes.byref(guid), byte_buffer, ctypes.sizeof(GUID))
    return guid

def risolvi_percorso(nome_luogo: str) -> str:
    """Converte nomi comuni nei percorsi assoluti di Windows dell'utente attuale, tenendo conto di OneDrive."""
    nome_luogo_clean = nome_luogo.lower().strip()
    home = os.path.expanduser("~")
    
    # Se chiede di cercare ovunque, attiviamo una modalità speciale per evitare AppData
    if nome_luogo_clean in ["ovunque", "tutto il pc", "pc", "computer", "tutto", ""]:
        return "OVUNQUE_SAFE"
        
    luoghi = {
        "desktop": get_known_folder_path(get_guid_from_bytes(FOLDERID_Desktop)),
        "download": get_known_folder_path(get_guid_from_bytes(FOLDERID_Downloads)),
        "documenti": get_known_folder_path(get_guid_from_bytes(FOLDERID_Documents))
    }
    
    path = luoghi.get(nome_luogo_clean, "")
    if path and os.path.exists(path):
         return path
         
    # Fallback legacy nel caso le API Windows falliscano
    home = os.path.expanduser("~")
    luoghi_fallback = {
        "desktop": os.path.join(home, "Desktop"),
        "download": os.path.join(home, "Downloads"),
        "documenti": os.path.join(home, "Documents")
    }
    
    if not os.path.exists(luoghi_fallback["download"]):
        luoghi_fallback["download"] = os.path.join(home, "Download")

    return luoghi_fallback.get(nome_luogo.lower(), os.path.join(home, "Desktop"))

@tool
def crea_cartella(nome_cartella: str, posizione: str = "desktop") -> str:
    """
    Usa questo strumento per creare una nuova cartella.
    'nome_cartella' è il nome della cartella (es. 'Progetto X').
    'posizione' deve essere "desktop", "download" o "documenti".
    """
    base_path = risolvi_percorso(posizione)
    full_path = os.path.join(base_path, nome_cartella)
    try:
        os.makedirs(full_path, exist_ok=True)
        return f"Cartella '{nome_cartella}' creata con successo in {posizione}."
    except Exception as e:
        return f"Errore: {str(e)}"

def genera_nome_univoco(cartella_dest, nome_file):
    """Genera un nome file univoco se ne esiste già uno con lo stesso nome."""
    base, ext = os.path.splitext(nome_file)
    contatore = 1
    nuovo_nome = nome_file
    while os.path.exists(os.path.join(cartella_dest, nuovo_nome)):
        nuovo_nome = f"{base}_{contatore}{ext}"
        contatore += 1
    return nuovo_nome

# Variabile globale per memorizzare l'operazione in sospeso
bozza_spostamento = {}

@tool
def prepara_spostamento_file(estensione: str, da_posizione: str, cartella_destinazione: str, posizione_destinazione: str = "desktop") -> str:
    """
    Usa questo strumento QUANDO L'UTENTE TI CHIEDE DI SPOSTARE O ORGANIZZARE FILE.
    Questo strumento NON sposta i file fisicamente, li conta solo e prepara l'operazione in sicurezza.
    """
    global bozza_spostamento
    if not estensione.startswith("."):
        estensione = "." + estensione

    source_dir = risolvi_percorso(da_posizione)
    dest_base = risolvi_percorso(posizione_destinazione)
    dest_dir = os.path.join(dest_base, cartella_destinazione)

    # Contiamo quanti file corrispondono al criterio
    file_trovati = []
    if os.path.exists(source_dir):
        for file in os.listdir(source_dir):
            if file.lower().endswith(estensione.lower()):
                file_trovati.append(file)

    numero_file = len(file_trovati)

    if numero_file == 0:
        return f"Non ho trovato nessun file con estensione {estensione} nella posizione '{da_posizione}'. Avvisa l'utente."

    # Salviamo i dati per la conferma successiva
    bozza_spostamento = {
        "estensione": estensione,
        "source_dir": source_dir,
        "dest_dir": dest_dir,
        "file_trovati": file_trovati
    }

    return f"'Ho trovato {numero_file} file {estensione} in {da_posizione}. Procedo a spostarli nella cartella {cartella_destinazione}?'"

@tool 
def conferma_spostamento_file() -> str:
    """
    Usa questo strumento SOLO E SOLTANTO QUANDO l'utente ti risponde "sì", "ok", "procedi", "vai" dopo che gli hai chiesto conferma per spostare i file.
    """
    global bozza_spostamento
    if not bozza_spostamento:
        return "Errore: Nessuna operazione di spostamento in sospeso."

    source_dir = bozza_spostamento["source_dir"]
    dest_dir = bozza_spostamento["dest_dir"]
    file_trovati = bozza_spostamento["file_trovati"]
    estensione = bozza_spostamento["estensione"]

    if not os.path.exists(dest_dir):
        os.makedirs(dest_dir, exist_ok=True)

    spostati = 0
    try:
        for file in file_trovati:
            src_file = os.path.join(source_dir, file)
            dst_file = os.path.join(dest_dir, file)
            if os.path.exists(src_file):
                shutil.move(src_file, dst_file)
                spostati += 1

        # Svuota la memoria dopo l'uso
        bozza_spostamento = {}
        return f"Operazione confermata e completata: {spostati} file {estensione} spostati con successo in {dest_dir}."
    except Exception as e:
        return f"Errore durante lo spostamento: {str(e)}"

@tool
def rinomina_elemento(nome_attuale: str, nuovo_nome: str, posizione: str = "desktop") -> str:
    """
    Usa questo strumento per rinominare fisicamente un file o una cartella sul computer dell'utente (Windows).
    NON USARE QUESTO STRUMENTO PER MODIFICARE LA TUA MEMORIA O I TUOI RICORDI.
    'nome_attuale': il nome attuale del file o della cartella da rinominare (inclusa estensione se file).
    'nuovo_nome': il nuovo nome che vuoi dare (inclusa estensione se file).
    'posizione': la cartella in cui si trova ("desktop", "download", "documenti").
    """
    base_path = risolvi_percorso(posizione)
    
    vecchio_percorso = os.path.join(base_path, nome_attuale)
    nuovo_percorso = os.path.join(base_path, nuovo_nome)
    
    if not os.path.exists(vecchio_percorso):
        return f"Errore: Non ho trovato nessun file o cartella chiamato '{nome_attuale}' in {posizione}."
        
    if os.path.exists(nuovo_percorso):
        return f"Errore: Esiste già un elemento chiamato '{nuovo_nome}' in {posizione}. Scegli un altro nome."
        
    try:
        os.rename(vecchio_percorso, nuovo_percorso)
        return f"Successo: Ho rinominato '{nome_attuale}' in '{nuovo_nome}'."
    except Exception as e:
        return f"Errore durante la rinomina: {str(e)}"

