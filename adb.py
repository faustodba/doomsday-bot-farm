# ==============================================================================
#  DOOMSDAY BOT V5 - adb.py
#  Motore ADB - tutti i comandi verso le istanze BlueStacks
# ==============================================================================

import subprocess
import os
import time
import threading
from PIL import Image
import config

# ------------------------------------------------------------------------------
# Lock screencap — serializza solo l'operazione screenshot tra thread paralleli.
# Evita frame corrotti quando due istanze fanno screencap simultaneamente.
# Timeout di sicurezza: se un thread non rilascia entro 30s (crash), il lock
# viene forzatamente sbloccato per non paralizzare le altre istanze.
# ------------------------------------------------------------------------------
_screencap_lock    = threading.Lock()
_SCREENCAP_TIMEOUT = 30  # secondi massimi di attesa per acquisire il lock

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
# ------------------------------------------------------------------------------
def screenshot(porta: str) -> str:
    """
    Scatta screenshot dell'istanza e lo salva localmente. Ritorna il path.
    Serializzato con lock per evitare frame corrotti con istanze parallele.
    Timeout di 30s per evitare deadlock in caso di crash di un thread.
    """
    remote_path = f"/sdcard/ahk_screen_{porta}.png"
    local_path  = os.path.join(config.BOT_DIR, f"screen_{porta}.png")

    acquired = _screencap_lock.acquire(timeout=_SCREENCAP_TIMEOUT)
    if not acquired:
        # Timeout: il lock non è stato rilasciato entro 30s.
        # Procedi comunque — meglio un frame potenzialmente corrotto
        # che bloccare l'istanza indefinitamente.
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
            _screencap_lock.release()

# ------------------------------------------------------------------------------
# Leggi pixel da screenshot
# Ritorna (r, g, b) oppure (-1, -1, -1) se fallisce
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
# Crop zona da screenshot -> restituisce immagine PIL
# ------------------------------------------------------------------------------
def crop_zona(screen_path: str, zona: tuple) -> Image.Image | None:
    """Ritaglia una zona dallo screenshot. zona=(x1,y1,x2,y2)"""
    try:
        img = Image.open(screen_path)
        return img.crop(zona)
    except:
        return None

# ------------------------------------------------------------------------------
# Avvia gioco con retry e verifica
# ------------------------------------------------------------------------------
def avvia_gioco(porta: str, tentativi: int = 5, attesa: int = 10) -> bool:
    """Avvia Doomsday con retry. Verifica che il processo sia effettivamente partito."""
    for i in range(tentativi):
        ris = adb_shell(porta, f"am start -n {config.GAME_ACTIVITY}")
        if "Error" not in ris:
            # Verifica che il processo gioco sia attivo
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