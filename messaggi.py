# ==============================================================================
#  DOOMSDAY BOT V5 - messaggi.py
#  Raccolta ricompense dalla sezione Messaggi (tab Alliance + Sistema)
#
#  Sequenza per ogni istanza:
#    1. vai_in_home verificato
#    2. Tap icona busta messaggi
#       [PRE-OPEN]     pin_msg_02_alliance visibile? (schermata aperta)
#    3. Tap tab ALLIANCE
#       [PRE-ALLIANCE] pin_msg_02_alliance attivo?
#       [PRE-READ]     pin_msg_04_read visibile? → tap Read and claim all
#    4. Tap tab SYSTEM
#       [PRE-SYSTEM]   pin_msg_03_system attivo?
#       [PRE-READ]     pin_msg_04_read visibile? → tap Read and claim all
#    5. Tap X (chiudi)
#       [POST-CLOSE]   vai_in_home confermato
#
#  PIN (tutti in C:\Bot-farm\templates\):
#    pin_msg_02_alliance.png  ROI=(283,23,367,47)  soglia=0.80  [tab ALLIANCE attivo]
#    pin_msg_03_system.png    ROI=(417,23,490,50)  soglia=0.80  [tab SYSTEM attivo]
#    pin_msg_04_read.png      ROI=(61,499,156,523) soglia=0.85  [bottone Read and claim all]
#
#  Score verificati su screenshot reali 960x540:
#    pin_msg_02_alliance → attivo=1.000  inattivo=0.936  (soglia 0.80 discrimina ✓)
#    pin_msg_03_system   → attivo=0.982  inattivo=0.935  (soglia 0.80 discrimina ✓)
#    pin_msg_04_read     → 0.9925 su entrambi i tab      (bottone sempre uguale ✓)
#
#  Schedulazione:
#    Eseguito al massimo ogni SCHEDULE_ORE_MESSAGGI ore (default 12h).
#    Stato persistito in: schedule_stato_{nome}_{porta}.json
# ==============================================================================

import os, time, subprocess
import cv2, numpy as np
import config
import scheduler
import stato as _stato

# ---------------------------------------------------------------------------
# Coordinate UI  (960x540)
# ---------------------------------------------------------------------------
_TAP_ICONA_MESSAGGI = (config.MSG_ICONA_X, config.MSG_ICONA_Y)
_TAP_TAB_ALLIANCE   = (325, 35)   # centro ROI (283+367)//2, (23+47)//2
_TAP_TAB_SYSTEM     = (453, 36)   # centro ROI (417+490)//2, (23+50)//2
_TAP_READ_ALL       = (108, 511)  # centro ROI (61+156)//2,  (499+523)//2
_TAP_CLOSE          = (930, 36)

# ---------------------------------------------------------------------------
# Pin template
# ---------------------------------------------------------------------------
_MSG_PIN = {
    "alliance": ("pin_msg_02_alliance.png", (283,  23, 367,  47), 0.80),
    "system":   ("pin_msg_03_system.png",   (417,  23, 490,  50), 0.80),
    "read":     ("pin_msg_04_read.png",     ( 61, 499, 156, 523), 0.85),
}

_SCREEN_TMP = os.path.join(config.BOT_DIR, "screen_msg.png")
_TMPL_DIR   = os.path.join(config.BOT_DIR, "templates")
_tmpl_cache = {}

# ---------------------------------------------------------------------------
# Helpers interni
# ---------------------------------------------------------------------------

def _tmpl(nome):
    if nome not in _tmpl_cache:
        _tmpl_cache[nome] = cv2.imread(os.path.join(_TMPL_DIR, nome))
    return _tmpl_cache[nome]

def _adb(porta, *args):
    return subprocess.run(
        [config.ADB_EXE, "-s", f"127.0.0.1:{porta}"] + list(args),
        capture_output=True
    )

def _tap(porta, coord, label="", log_fn=None):
    x, y = coord
    if log_fn: log_fn(f"[MSG] tap ({x},{y})" + (f" [{label}]" if label else ""))
    _adb(porta, "shell", "input", "tap", str(x), str(y))

def _back(porta):
    _adb(porta, "shell", "input", "keyevent", "4")

def _screenshot(porta):
    _adb(porta, "shell", "screencap", "-p", "/sdcard/screen_msg.png")
    r = _adb(porta, "pull", "/sdcard/screen_msg.png", _SCREEN_TMP)
    if r.returncode != 0:
        return ""
    return _SCREEN_TMP if os.path.exists(_SCREEN_TMP) else ""

def _match_pin(screen_path, key):
    try:
        tmpl_file, roi, _ = _MSG_PIN[key]
        tmpl = _tmpl(tmpl_file)
        if tmpl is None: return -1.0
        img = cv2.imread(screen_path)
        if img is None: return -1.0
        x1, y1, x2, y2 = roi
        h_img, w_img = img.shape[:2]
        if w_img != 960 or h_img != 540:
            sx, sy = w_img / 960.0, h_img / 540.0
            x1, y1, x2, y2 = int(x1*sx), int(y1*sy), int(x2*sx), int(y2*sy)
        roi_img = img[y1:y2, x1:x2]
        if roi_img.size == 0: return -1.0
        res = cv2.matchTemplate(roi_img, tmpl, cv2.TM_CCOEFF_NORMED)
        _, mv, _, _ = cv2.minMaxLoc(res)
        return float(mv)
    except Exception:
        return -1.0

def _check(screen_path, key, log_fn=None):
    _, _, soglia = _MSG_PIN[key]
    score = _match_pin(screen_path, key)
    ok = score >= soglia
    if log_fn:
        log_fn(f"[MSG-PIN] {key}: score={score:.3f} → {'OK' if ok else 'NON trovato'}")
    return ok

def _screen_check(porta, key, log_fn=None, retry=1, retry_s=1.5):
    for tentativo in range(retry + 1):
        screen = _screenshot(porta)
        if not screen:
            if log_fn: log_fn(f"[MSG-PIN] {key}: screenshot fallito (t={tentativo+1})")
            time.sleep(retry_s)
            continue
        ok = _check(screen, key, log_fn)
        if ok or tentativo == retry:
            return ok, screen
        time.sleep(retry_s)
    return False, ""

def _gestisci_tab(porta, tab_key, tab_tap, nome_tab, log_fn=None) -> bool:
    """
    Seleziona un tab messaggi e clicca 'Read and claim all'.

    Flusso:
      1. Tap sul tab
      2. [PRE-TAB] verifica tab attivo (retry 2)
         ANOMALIA → log + return False
      3. [PRE-READ] verifica bottone 'Read and claim all'
         OK  → tap + pausa 2s
         NO  → log (nessun messaggio) + procedi senza errore
    """
    if log_fn: log_fn(f"[MSG] tap tab {nome_tab}")
    _tap(porta, tab_tap, nome_tab, log_fn)
    time.sleep(1.0)

    ok_tab, _ = _screen_check(porta, tab_key, log_fn, retry=2, retry_s=1.0)
    if not ok_tab:
        if log_fn: log_fn(f"[MSG] [PRE-{nome_tab.upper()}] ANOMALIA: tab non attivo — skip tab")
        return False
    if log_fn: log_fn(f"[MSG] [PRE-{nome_tab.upper()}] tab attivo — OK")

    ok_read, _ = _screen_check(porta, "read", log_fn, retry=1, retry_s=1.0)
    if ok_read:
        if log_fn: log_fn("[MSG] [PRE-READ] bottone visibile — tap Read and claim all")
        _tap(porta, _TAP_READ_ALL, "Read and claim all", log_fn)
        time.sleep(2.0)
    else:
        if log_fn: log_fn(f"[MSG] [PRE-READ] bottone non visibile — nessun messaggio su {nome_tab}")

    return True

# ---------------------------------------------------------------------------
# Entry point pubblico
# ---------------------------------------------------------------------------

def raccolta_messaggi(porta: str, nome: str, logger=None) -> bool:
    """
    Raccoglie le ricompense dalla sezione Messaggi (tab Alliance + System).
    Salta silenziosamente se già eseguito nelle ultime SCHEDULE_ORE_MESSAGGI ore.

    Returns:
        True  se completato o saltato per schedulazione
        False se home non raggiungibile, schermata non aperta, o eccezione
    """
    def log(msg):
        if logger: logger(nome, msg)

    # Verifica schedulazione
    if not scheduler.deve_eseguire(nome, porta, "messaggi", logger):
        return True

    # Verifica home
    if not _stato.vai_in_home(porta, nome, logger):
        log("Messaggi: impossibile raggiungere home — skip")
        return False

    try:
        log("Inizio raccolta messaggi")

        # STEP 1: apri schermata messaggi
        _tap(porta, _TAP_ICONA_MESSAGGI, "icona messaggi", log)
        time.sleep(2.0)

        # [PRE-OPEN] schermata messaggi aperta?
        ok_open, _ = _screen_check(porta, "alliance", log, retry=2, retry_s=1.5)
        if not ok_open:
            log("[MSG] [PRE-OPEN] ANOMALIA: schermata messaggi non aperta — BACK + abort")
            _back(porta)
            time.sleep(1.0)
            return False
        log("[MSG] [PRE-OPEN] schermata messaggi aperta — OK")

        # STEP 2: tab ALLIANCE
        _gestisci_tab(porta, "alliance", _TAP_TAB_ALLIANCE, "Alliance", log)

        # STEP 3: tab SYSTEM
        _gestisci_tab(porta, "system", _TAP_TAB_SYSTEM, "System", log)

        # STEP 4: chiudi
        # La X chiude i messaggi ma può lasciare aperti overlay sottostanti
        # (es. Alleanza). BACK multipli prima di vai_in_home per svuotare lo stack.
        log("[MSG] chiusura schermata messaggi")
        _tap(porta, _TAP_CLOSE, "Close X", log)
        time.sleep(1.5)
        for _ in range(3):
            _back(porta)
            time.sleep(0.5)
        time.sleep(0.5)

        # [POST-CLOSE] verifica home vera (non solo toggle)
        if not _stato.vai_in_home(porta, nome, logger):
            log("[MSG] [POST-CLOSE] ANOMALIA: home non confermata — recovery forzato")
            for _ in range(5):
                _back(porta)
                time.sleep(0.5)
        else:
            log("[MSG] [POST-CLOSE] home confermata — OK")

        log("Raccolta messaggi completata")
        scheduler.registra_esecuzione(nome, porta, "messaggi")
        return True

    except Exception as e:
        log(f"Errore raccolta messaggi: {e}")
        return False
