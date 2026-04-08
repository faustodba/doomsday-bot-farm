# ==============================================================================
#  DOOMSDAY BOT V5 - adb.py
#  Motore ADB - tutti i comandi verso le istanze MuMuPlayer
#
#  v5.24 — Aggiunta pipeline screenshot in-memoria (exec-out)
#          per eliminare I/O disco nel rilevamento stato.
#          Funzioni originali (screenshot, leggi_pixel, crop_zona) intatte
#          per backward compatibility con arena, messaggi, raccolta, ecc.
#  v5.25 — Lock screencap da globale a per-porta: istanze su porte diverse
#          girano in parallelo senza bloccarsi a vicenda.
# ==============================================================================

import subprocess
import os
import time
import threading
from io import BytesIO
from PIL import Image
import config

# ------------------------------------------------------------------------------
# Lock screencap — un lock PER PORTA invece di uno globale.
#
# Motivazione: due istanze MuMu su porte diverse (16384, 16394, ...) sono
# processi Android completamente separati — non si contendono nulla a livello
# di device. Il lock globale serializzava inutilmente tutte le istanze parallele
# rendendo il guadagno del parallelismo quasi nullo.
#
# Il lock per-porta garantisce ancora che due thread non facciano screencap
# simultaneamente SULLA STESSA PORTA (caso raro ma possibile se un modulo
# chiama screenshot() mentre stato.py chiama screenshot_bytes() sulla stessa
# istanza nello stesso istante).
#
# Timeout di sicurezza: 30s — se un thread non rilascia entro questo tempo
# (crash), il lock viene forzatamente ignorato per non paralizzare le altre.
# ------------------------------------------------------------------------------
_screencap_locks      = {}                # porta -> threading.Lock()
_screencap_locks_meta = threading.Lock() # protegge il dict durante creazione
_SCREENCAP_TIMEOUT    = 30               # secondi massimi di attesa per il lock


def _get_screencap_lock(porta: str) -> threading.Lock:
    """Ritorna il lock dedicato alla porta specificata (lazy, thread-safe)."""
    with _screencap_locks_meta:
        if porta not in _screencap_locks:
            _screencap_locks[porta] = threading.Lock()
        return _screencap_locks[porta]

# ------------------------------------------------------------------------------
# Esegui comando ADB generico
# ------------------------------------------------------------------------------
def adb_cmd(porta: str, *args) -> str:
    """Esegue un comando adb -s 127.0.0.1:PORTA e restituisce stdout."""
    cmd = [config.ADB_EXE, "-s", f"127.0.0.1:{porta}"] + list(args)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return ""
    except Exception as e:
        return ""

# ------------------------------------------------------------------------------
# Esegui comando shell Android via ADB
# ------------------------------------------------------------------------------
def adb_shell(porta: str, comando: str) -> str:
    """Esegue adb shell <comando> e restituisce stdout."""
    return adb_cmd(porta, "shell", comando)

# ------------------------------------------------------------------------------
# Connetti ADB a una istanza
# ------------------------------------------------------------------------------
def connetti(porta: str) -> bool:
    """Connette ADB all'istanza sulla porta specificata. Ritorna True se OK."""
    cmd = [config.ADB_EXE, "connect", f"127.0.0.1:{porta}"]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except:
        return False

    # Verifica connessione
    for _ in range(config.TIMEOUT_ADB):
        risposta = adb_shell(porta, "echo ok")
        if "ok" in risposta:
            return True
        time.sleep(1)
    return False

# ------------------------------------------------------------------------------
# Avvia server ADB
# ------------------------------------------------------------------------------
def start_server():
    """Avvia il server ADB."""
    try:
        subprocess.run([config.ADB_EXE, "start-server"],
                       capture_output=True, timeout=15)
    except:
        pass

# ------------------------------------------------------------------------------
# Tap su coordinate (x, y)
# ------------------------------------------------------------------------------
def tap(porta: str, xy: tuple, delay_ms: int = 300):
    """Invia tap ADB alle coordinate (x, y) con delay opzionale."""
    x, y = xy
    adb_shell(porta, f"input tap {x} {y}")
    if delay_ms > 0:
        time.sleep(delay_ms / 1000)

# ------------------------------------------------------------------------------
# Inserisci testo via ADB
# ------------------------------------------------------------------------------
def input_text(porta: str, testo: str):
    """Invia testo via ADB input text."""
    adb_shell(porta, f"input text {testo}")

# ------------------------------------------------------------------------------
# Invia keyevent
# ------------------------------------------------------------------------------
def keyevent(porta: str, keycode: str):
    """Invia keyevent via ADB."""
    adb_shell(porta, f"input keyevent {keycode}")

# ------------------------------------------------------------------------------
# Screenshot via ADB -> salva in BOT_DIR e restituisce path
# (ORIGINALE — usato da arena_of_glory, messaggi, raccolta, verifica_ui, ecc.)
# ------------------------------------------------------------------------------
def screenshot(porta: str) -> str:
    """
    Scatta screenshot dell'istanza e lo salva localmente. Ritorna il path.
    Serializzato con lock PER PORTA per evitare frame corrotti sulla stessa
    istanza. Istanze diverse su porte diverse non si bloccano a vicenda.
    Timeout di 30s per evitare deadlock in caso di crash di un thread.
    """
    remote_path = f"/sdcard/ahk_screen_{porta}.png"
    screen_dir  = os.path.join(config.DEBUG_DIR, "screen")
    os.makedirs(screen_dir, exist_ok=True)
    local_path  = os.path.join(screen_dir, f"screen_{porta}.png")

    lock     = _get_screencap_lock(porta)
    acquired = lock.acquire(timeout=_SCREENCAP_TIMEOUT)
    if not acquired:
        print(f"[ADB] WARN screenshot({porta}): lock timeout {_SCREENCAP_TIMEOUT}s — procedo senza lock")
        acquired = False

    try:
        adb_shell(porta, f"screencap -p {remote_path}")
        result = subprocess.run(
            [config.ADB_EXE, "-s", f"127.0.0.1:{porta}", "pull", remote_path, local_path],
            capture_output=True, timeout=15
        )
        if result.returncode == 0 and os.path.exists(local_path):
            return local_path
        return ""
    finally:
        if acquired:
            lock.release()

# ------------------------------------------------------------------------------
# Leggi pixel da screenshot (file su disco)
# Ritorna (r, g, b) oppure (-1, -1, -1) se fallisce
# (ORIGINALE — usato da altri moduli che passano screen_path)
# ------------------------------------------------------------------------------
def leggi_pixel(screen_path: str, x: int, y: int) -> tuple:
    """Legge il colore di un pixel da uno screenshot salvato."""
    try:
        img = Image.open(screen_path)
        r, g, b = img.getpixel((x, y))[:3]
        return (r, g, b)
    except:
        return (-1, -1, -1)

# ------------------------------------------------------------------------------
# Leggi pixel da immagine PIL già in memoria
# (NUOVA — usata da stato.py per il rilevamento in-memoria)
# ------------------------------------------------------------------------------
def leggi_pixel_img(pil_img, x: int, y: int) -> tuple:
    """
    Legge pixel da un'immagine PIL già in memoria.
    Stessa interfaccia di leggi_pixel() ma senza I/O disco.
    Ritorna (r, g, b) oppure (-1, -1, -1).
    """
    if pil_img is None:
        return (-1, -1, -1)
    try:
        r, g, b = pil_img.getpixel((x, y))[:3]
        return (r, g, b)
    except Exception:
        return (-1, -1, -1)

# ------------------------------------------------------------------------------
# Crop zona da screenshot -> restituisce immagine PIL
# ------------------------------------------------------------------------------
def crop_zona(screen_path: str, zona: tuple) -> Image.Image | None:
    """Ritaglia una zona dallo screenshot. zona=(x1,y1,x2,y2)"""
    try:
        img = Image.open(screen_path)
        return img.crop(zona)
    except:
        return None

# ==============================================================================
# PIPELINE SCREENSHOT IN-MEMORIA (exec-out)
#
# Usata da stato.py per il rilevamento stato — il modulo chiamato più spesso.
# Elimina: file su device, adb pull, doppio load (PIL + cv2).
# Risparmio stimato: 150-300ms per chiamata.
#
# Se exec-out non funziona (MuMu vecchio, ADB incompatibile), il chiamante
# cade automaticamente su screenshot() tradizionale.
# ==============================================================================

def screenshot_bytes(porta: str) -> bytes:
    """
    Screenshot via exec-out — nessun file su device, nessun pull.
    Ritorna i bytes PNG grezzi, oppure b'' se fallisce.

    Lock PER PORTA: istanze su porte diverse girano completamente in parallelo.
    Solo due chiamate sulla stessa porta si serializzano (caso raro).

    VANTAGGI rispetto a screenshot():
      - Elimina write su /sdcard/ del device    (~50ms)
      - Elimina adb pull                        (~100-200ms)
      - Elimina write su disco locale           (~10ms)
    """
    lock     = _get_screencap_lock(porta)
    acquired = lock.acquire(timeout=_SCREENCAP_TIMEOUT)
    if not acquired:
        print(f"[ADB] WARN screenshot_bytes({porta}): lock timeout — procedo senza lock")
        acquired = False

    try:
        cmd = [
            config.ADB_EXE, "-s", f"127.0.0.1:{porta}",
            "exec-out", "screencap", "-p"
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=15)

        if result.returncode != 0 or not result.stdout:
            return b''

        # Sanity check: un PNG valido inizia con \x89PNG
        if len(result.stdout) < 100 or result.stdout[:4] != b'\x89PNG':
            return b''

        return result.stdout

    except subprocess.TimeoutExpired:
        return b''
    except Exception:
        return b''
    finally:
        if acquired:
            lock.release()


def decodifica_screenshot(png_bytes: bytes):
    """
    Decodifica PNG bytes in (pil_img, cv_img) — un solo decode per entrambi.
    Ritorna (None, None) se fallisce.

    pil_img : PIL.Image — per pixel check
    cv_img  : numpy ndarray BGR — per template matching (None se cv2 assente)
    """
    if not png_bytes:
        return (None, None)

    # PIL Image (per pixel check)
    try:
        pil_img = Image.open(BytesIO(png_bytes))
        pil_img.load()  # forza decode completo (PIL è lazy)
    except Exception:
        return (None, None)

    # cv2 Image (per template matching)
    cv_img = None
    try:
        import numpy as np
        import cv2
        arr = np.frombuffer(png_bytes, dtype=np.uint8)
        cv_img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except ImportError:
        pass  # cv2 non disponibile — stato.py userà fallback pixel check
    except Exception:
        pass

    return (pil_img, cv_img)


def salva_screenshot(png_bytes: bytes, porta: str) -> str:
    """
    Salva i PNG bytes su disco in debug/screen/screen_{porta}.png.
    Ritorna il path locale, oppure '' se fallisce.

    Chiamare SOLO quando serve il file su disco — per il rilevamento stato
    in-memoria non è necessario.
    Il file viene sovrascritto ad ogni chiamata — non si accumula su disco.
    """
    if not png_bytes:
        return ''

    screen_dir = os.path.join(config.DEBUG_DIR, "screen")
    os.makedirs(screen_dir, exist_ok=True)
    local_path = os.path.join(screen_dir, f"screen_{porta}.png")
    try:
        with open(local_path, 'wb') as f:
            f.write(png_bytes)
        return local_path
    except Exception:
        return ''

# ==============================================================================
# FINE PIPELINE IN-MEMORIA
# ==============================================================================

# ------------------------------------------------------------------------------
# Avvia gioco con retry e verifica
# ------------------------------------------------------------------------------
def avvia_gioco(porta: str, tentativi: int = 5, attesa: int = 10) -> bool:
    """Avvia Doomsday con retry. Verifica che il processo sia effettivamente partito."""
    for i in range(tentativi):
        ris = adb_shell(porta, f"am start -n {config.GAME_ACTIVITY}")
        if "Error" not in ris:
            time.sleep(3)
            procs = adb_shell(porta, "pidof com.igg.android.doomsdaylastsurvivors")
            if procs.strip():
                return True
        time.sleep(attesa)
    return False

# ------------------------------------------------------------------------------
# Scroll (swipe verticale)
# ------------------------------------------------------------------------------
def scroll(porta: str, x: int, y_start: int, y_end: int, durata_ms: int = 600):
    """
    Esegue uno scroll verticale via ADB input swipe.
    y_start > y_end = scroll verso l'alto (avanza nella lista)
    y_start < y_end = scroll verso il basso (torna indietro)
    """
    adb_shell(porta, f"input swipe {x} {y_start} {x} {y_end} {durata_ms}")
    time.sleep(0.5)

# ------------------------------------------------------------------------------
# Ferma gioco
# ------------------------------------------------------------------------------
def ferma_gioco(porta: str):
    """Forza la chiusura del gioco via ADB."""
    adb_shell(porta, "am force-stop com.igg.android.doomsdaylastsurvivors")
