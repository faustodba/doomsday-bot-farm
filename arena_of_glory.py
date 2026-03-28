# arena_of_glory.py
"""
Modulo standalone — Arena of Glory (Arena of Doom).
Task giornaliero: esegue MAX_SFIDE sfide, intercettando il popup
"Purchase more attempts?" per uscire anticipatamente se le sfide sono esaurite.

Flusso:
  HOME → Campaign → Arena of Doom
  → [popup Congratulations/Glory Silver → Continue]  (prima volta a settimana)
  → loop MAX_SFIDE volte:
      tap ultima sfida → [popup esaurite → Cancel → stop] → START CHALLENGE
      → attesa battaglia → tap risultato → continua

Tutte le costanti di coordinate/pixel sono in config.py sezione "Arena of Glory".

Integrazione bot:
  from arena_of_glory import run_arena_of_glory
  result = run_arena_of_glory(adb_exe, porta)

Test standalone:
  python test_arena_of_glory.py --porta 16416 --nome FAU_01
  python test_arena_of_glory.py --porta 16416 --nome FAU_01 --sfide 1
"""

import os
import time
import subprocess

import cv2
import numpy as np
import config

# ── Costanti — tutte lette da config.py sezione "Arena of Glory" ──────────────

TAP_CAMPAIGN        = config.ARENA_TAP_CAMPAIGN
TAP_ARENA_OF_DOOM   = config.ARENA_TAP_ARENA_OF_DOOM
TAP_ULTIMA_SFIDA    = config.ARENA_TAP_ULTIMA_SFIDA
TAP_START_CHALLENGE = config.ARENA_TAP_START_CHALLENGE
TAP_RISULTATO       = config.ARENA_TAP_RISULTATO
TAP_CONGRATULATIONS = config.ARENA_TAP_CONGRATULATIONS
TAP_ESAURITE_CANCEL = config.ARENA_TAP_ESAURITE_CANCEL
MAX_SFIDE           = config.ARENA_MAX_SFIDE
SCREEN_TMP          = os.path.join(config.BOT_DIR, config.ARENA_SCREEN_TMP)

_CONGRATS_CHECK_XY  = config.ARENA_CONGRATS_CHECK_XY
_CONGRATS_BGR_LOW   = np.array(config.ARENA_CONGRATS_BGR_LOW,  dtype=np.uint8)
_CONGRATS_BGR_HIGH  = np.array(config.ARENA_CONGRATS_BGR_HIGH, dtype=np.uint8)
_ESAURITE_CHECK_XY  = config.ARENA_ESAURITE_CHECK_XY
_ESAURITE_SOGLIA    = config.ARENA_ESAURITE_SOGLIA

# ── ADB helpers ────────────────────────────────────────────────────────────────

def _adb(adb_exe, porta, *args):
    cmd = [adb_exe, "-s", f"127.0.0.1:{porta}"] + list(args)
    return subprocess.run(cmd, capture_output=True)

def adb_tap(adb_exe, porta, x, y):
    _adb(adb_exe, porta, "shell", "input", "tap", str(x), str(y))
    print(f"  [TAP] ({x},{y})")

def adb_back(adb_exe, porta):
    _adb(adb_exe, porta, "shell", "input", "keyevent", "4")

def adb_screenshot(adb_exe, porta):
    """Cattura screenshot e restituisce immagine numpy BGR."""
    _adb(adb_exe, porta, "shell", "screencap", "-p", "/sdcard/screen_arena.png")
    r = _adb(adb_exe, porta, "pull", "/sdcard/screen_arena.png", SCREEN_TMP)
    if r.returncode != 0:
        print("[ARENA] screenshot fallito")
        return None
    img = cv2.imread(SCREEN_TMP)
    return img

# ── Popup helpers ──────────────────────────────────────────────────────────────

def _gestisci_popup_congratulations(adb_exe, porta):
    """
    Controlla il popup stagionale "Congratulations / Glory Silver"
    (prima volta a settimana dopo il tap su Arena of Doom).
    Pixel check sul pulsante giallo "Continue".
    Ritorna True se il popup era presente e lo ha chiuso.
    """
    img = adb_screenshot(adb_exe, porta)
    if img is None:
        return False

    px, py = _CONGRATS_CHECK_XY
    pixel = img[py, px]
    match = np.all(pixel >= _CONGRATS_BGR_LOW) and np.all(pixel <= _CONGRATS_BGR_HIGH)

    if match:
        print(f"[ARENA] Popup Congratulations rilevato (pixel {pixel}) — tap Continue")
        adb_tap(adb_exe, porta, *TAP_CONGRATULATIONS)
        time.sleep(2.0)
        return True

    print(f"[ARENA] Nessun popup Congratulations (pixel {pixel})")
    return False


def _gestisci_popup_esaurite(adb_exe, porta):
    """
    Controlla il popup "Purchase more attempts?" (sfide giornaliere esaurite).
    Pixel check sul pulsante "Cancel" grigio chiaro (tutti i canali > soglia).
    Ritorna True se il popup era presente → tap Cancel → segnale di stop.
    """
    img = adb_screenshot(adb_exe, porta)
    if img is None:
        return False

    px, py = _ESAURITE_CHECK_XY
    pixel = img[py, px]
    if np.all(pixel > _ESAURITE_SOGLIA):
        print(f"[ARENA] Popup sfide esaurite rilevato (pixel {pixel}) — tap Cancel")
        adb_tap(adb_exe, porta, *TAP_ESAURITE_CANCEL)
        time.sleep(1.5)
        return True

    return False

# ── Navigazione e sfide ────────────────────────────────────────────────────────

def naviga_a_arena(adb_exe, porta):
    """Da HOME: Campaign → Arena of Doom → gestisce popup Congratulations."""
    print("[ARENA] HOME -> Campaign")
    adb_tap(adb_exe, porta, *TAP_CAMPAIGN)
    time.sleep(3.0)

    print("[ARENA] Campaign -> Arena of Doom")
    adb_tap(adb_exe, porta, *TAP_ARENA_OF_DOOM)
    time.sleep(3.5)

    _gestisci_popup_congratulations(adb_exe, porta)


def esegui_sfida(adb_exe, porta, n):
    """
    Esegue una singola sfida.
    Ritorna: "ok" se completata, "ESAURITE" se popup acquisto rilevato.
    """
    print(f"\n[ARENA] Sfida #{n}")

    print("[ARENA] Tap ultima sfida della lista")
    adb_tap(adb_exe, porta, *TAP_ULTIMA_SFIDA)
    time.sleep(4.0)   # attesa caricamento mappa sfida

    if _gestisci_popup_esaurite(adb_exe, porta):
        print("[ARENA] Sfide giornaliere esaurite — interruzione loop")
        return "ESAURITE"

    print("[ARENA] Tap START CHALLENGE")
    adb_tap(adb_exe, porta, *TAP_START_CHALLENGE)
    time.sleep(12.0)  # attesa fine battaglia

    print("[ARENA] Tap risultato -> ritorno lista")
    adb_tap(adb_exe, porta, *TAP_RISULTATO)
    time.sleep(2.5)

    return "ok"


def torna_in_home(adb_exe, porta):
    print("[ARENA] Ritorno HOME (4x BACK)")
    for _ in range(4):
        adb_back(adb_exe, porta)
        time.sleep(0.8)

# ── Entry point ────────────────────────────────────────────────────────────────

def run_arena_of_glory(adb_exe, porta):
    """
    Entry point principale — chiamabile dal bot (raccolta.py).

    Ritorna:
        {
            "sfide_eseguite": int,
            "esaurite": bool,   # True = popup "sfide esaurite" intercettato
            "errore": str | None,
        }
    """
    risultato = {
        "sfide_eseguite": 0,
        "esaurite": False,
        "errore": None,
    }

    print(f"\n{'='*52}")
    print(f"[ARENA] Avvio Arena of Glory")
    print(f"{'='*52}")

    try:
        naviga_a_arena(adb_exe, porta)

        for i in range(1, MAX_SFIDE + 1):
            esito = esegui_sfida(adb_exe, porta, i)
            if esito == "ESAURITE":
                print("[ARENA] Sfide giornaliere esaurite — uscita anticipata")
                risultato["esaurite"] = True
                break
            risultato["sfide_eseguite"] += 1
            print(f"[ARENA] Progresso: {i}/{MAX_SFIDE}")

        print(f"\n[ARENA] Completato — {risultato['sfide_eseguite']} sfide eseguite")

    except Exception as e:
        risultato["errore"] = str(e)
        print(f"[ARENA] Errore: {e}")
        raise

    finally:
        torna_in_home(adb_exe, porta)

    return risultato
