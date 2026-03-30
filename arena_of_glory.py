# arena_of_glory.py
"""
Modulo standalone — Arena of Glory (Arena of Doom).
Task giornaliero: esegue MAX_SFIDE sfide con verifica visiva pin a ogni step.

PIN (tutti in C:\\Bot-farm\\templates\\):
  pin_arena_01_lista.png      ROI=(387,0,565,43)     soglia=0.80
  pin_arena_02_challenge.png  ROI=(610,434,857,486)  soglia=0.80
  pin_arena_03_victory.png    ROI=(407,89,557,156)   soglia=0.80
  pin_arena_04_failure.png    ROI=(414,94,544,146)   soglia=0.80
  pin_arena_05_continue.png   ROI=(410,443,547,487)  soglia=0.80
  pin_arena_06_purchase.png   ROI=(334,143,586,185)  soglia=0.80
"""

import os, time, subprocess
import cv2, numpy as np
import config

TAP_CAMPAIGN        = config.ARENA_TAP_CAMPAIGN
TAP_ARENA_OF_DOOM   = config.ARENA_TAP_ARENA_OF_DOOM
TAP_ULTIMA_SFIDA    = config.ARENA_TAP_ULTIMA_SFIDA
TAP_START_CHALLENGE = config.ARENA_TAP_START_CHALLENGE
TAP_ESAURITE_CANCEL = config.ARENA_TAP_ESAURITE_CANCEL
TAP_CONGRATULATIONS = config.ARENA_TAP_CONGRATULATIONS
MAX_SFIDE           = config.ARENA_MAX_SFIDE
SCREEN_TMP          = os.path.join(config.BOT_DIR, config.ARENA_SCREEN_TMP)
TAP_CONTINUE        = (478, 465)

_CONGRATS_CHECK_XY  = config.ARENA_CONGRATS_CHECK_XY
_CONGRATS_BGR_LOW   = np.array(config.ARENA_CONGRATS_BGR_LOW,  dtype=np.uint8)
_CONGRATS_BGR_HIGH  = np.array(config.ARENA_CONGRATS_BGR_HIGH, dtype=np.uint8)

_ARENA_PIN = {
    "lista":     ("pin_arena_01_lista.png",     (387,  0,  565,  43), 0.80),
    "challenge": ("pin_arena_02_challenge.png", (610, 434, 857, 486), 0.80),
    "victory":   ("pin_arena_03_victory.png",   (407,  89, 557, 156), 0.80),
    "failure":   ("pin_arena_04_failure.png",   (414,  94, 544, 146), 0.80),
    "continue":  ("pin_arena_05_continue.png",  (410, 443, 547, 487), 0.80),
    "purchase":  ("pin_arena_06_purchase.png",  (334, 143, 586, 185), 0.80),
}

_tmpl_cache = {}
_TMPL_DIR   = os.path.join(config.BOT_DIR, "templates")

def _tmpl(nome):
    if nome not in _tmpl_cache:
        _tmpl_cache[nome] = cv2.imread(os.path.join(_TMPL_DIR, nome))
    return _tmpl_cache[nome]

def _match_pin(screen_path, key):
    try:
        tmpl_file, roi, _ = _ARENA_PIN[key]
        tmpl = _tmpl(tmpl_file)
        if tmpl is None: return -1.0
        img = cv2.imread(screen_path)
        if img is None: return -1.0
        x1,y1,x2,y2 = roi
        h_img,w_img = img.shape[:2]
        if w_img != 960 or h_img != 540:
            sx,sy = w_img/960.0, h_img/540.0
            x1,y1,x2,y2 = int(x1*sx),int(y1*sy),int(x2*sx),int(y2*sy)
        roi_img = img[y1:y2, x1:x2]
        if roi_img.size == 0: return -1.0
        res = cv2.matchTemplate(roi_img, tmpl, cv2.TM_CCOEFF_NORMED)
        _, mv, _, _ = cv2.minMaxLoc(res)
        return float(mv)
    except Exception:
        return -1.0

def _check(screen_path, key, log_fn=None):
    _, _, soglia = _ARENA_PIN[key]
    score = _match_pin(screen_path, key)
    ok = score >= soglia
    if log_fn:
        log_fn(f"[ARENA-PIN] {key}: score={score:.3f} → {'OK' if ok else 'NON trovato'}")
    return ok

def _adb(adb_exe, porta, *args):
    return subprocess.run([adb_exe, "-s", f"127.0.0.1:{porta}"] + list(args), capture_output=True)

def _tap(adb_exe, porta, coord, label="", log_fn=None):
    x,y = coord
    if log_fn: log_fn(f"[ARENA] tap ({x},{y})" + (f" [{label}]" if label else ""))
    _adb(adb_exe, porta, "shell", "input", "tap", str(x), str(y))

def _back(adb_exe, porta):
    _adb(adb_exe, porta, "shell", "input", "keyevent", "4")

def _screenshot(adb_exe, porta):
    _adb(adb_exe, porta, "shell", "screencap", "-p", "/sdcard/screen_arena.png")
    r = _adb(adb_exe, porta, "pull", "/sdcard/screen_arena.png", SCREEN_TMP)
    if r.returncode != 0: return ""
    return SCREEN_TMP if os.path.exists(SCREEN_TMP) else ""

def _screen_check(adb_exe, porta, key, log_fn=None, retry=1, retry_s=1.5):
    for tentativo in range(retry + 1):
        screen = _screenshot(adb_exe, porta)
        if not screen:
            if log_fn: log_fn(f"[ARENA-PIN] {key}: screenshot fallito (t={tentativo+1})")
            time.sleep(retry_s)
            continue
        ok = _check(screen, key, log_fn)
        if ok or tentativo == retry:
            return ok, screen
        time.sleep(retry_s)
    return False, ""

def _gestisci_popup_congratulations(adb_exe, porta, log_fn=None):
    screen = _screenshot(adb_exe, porta)
    if not screen: return False
    img = cv2.imread(screen)
    if img is None: return False
    px,py = _CONGRATS_CHECK_XY
    pixel = img[py, px]
    if np.all(pixel >= _CONGRATS_BGR_LOW) and np.all(pixel <= _CONGRATS_BGR_HIGH):
        if log_fn: log_fn("[ARENA] popup Congratulations rilevato — tap Continue")
        _tap(adb_exe, porta, TAP_CONGRATULATIONS, "Continue", log_fn)
        time.sleep(2.0)
        return True
    return False

def _naviga_a_arena(adb_exe, porta, log_fn=None):
    if log_fn: log_fn("[ARENA] HOME → Campaign")
    _tap(adb_exe, porta, TAP_CAMPAIGN, "Campaign", log_fn)
    time.sleep(3.0)
    if log_fn: log_fn("[ARENA] Campaign → Arena of Doom")
    _tap(adb_exe, porta, TAP_ARENA_OF_DOOM, "Arena of Doom", log_fn)
    time.sleep(3.5)
    _gestisci_popup_congratulations(adb_exe, porta, log_fn)
    ok, _ = _screen_check(adb_exe, porta, "lista", log_fn, retry=2, retry_s=2.0)
    if ok:
        if log_fn: log_fn("[ARENA] [PRE-LISTA] pin_arena_01 visibile — lista aperta OK")
    else:
        if log_fn: log_fn("[ARENA] [PRE-LISTA] ANOMALIA: lista non rilevata")
    return ok

def _vai_in_home_arena(adb_exe, porta, log_fn=None) -> bool:
    """
    Porta l'istanza in home usando BACK ripetuti e verifica toggle.
    Ritorna True se home confermata.
    """
    import stato as _stato_mod
    for ciclo in range(3):
        for _ in range(5):
            _back(adb_exe, porta)
            time.sleep(0.4)
        time.sleep(0.8)
        screen = _screenshot(adb_exe, porta)
        if screen:
            s = _stato_mod.rileva_screen(screen)
            if s == 'home':
                if log_fn: log_fn(f"[ARENA] home confermata (ciclo {ciclo+1})")
                return True
            if log_fn: log_fn(f"[ARENA] stato '{s}' dopo BACK (ciclo {ciclo+1}) — riprovo")
    if log_fn: log_fn("[ARENA] ANOMALIA: impossibile confermare home")
    return False


def _torna_home(adb_exe, porta, log_fn=None):
    """
    Torna in home dopo le sfide.
    Prima verifica se siamo sulla schermata risultato (Victory/Failure):
    il BACK non funziona su quella schermata — serve tap su 'Tap to Continue'.
    """
    if log_fn: log_fn("[ARENA] ritorno HOME")

    # Se siamo sulla schermata risultato, il BACK non funziona.
    # Verifica pin_arena_05_continue e tappa se visibile.
    screen = _screenshot(adb_exe, porta)
    if screen and _check(screen, "continue", log_fn):
        if log_fn: log_fn("[ARENA] schermata risultato ancora aperta — tap Tap to Continue")
        _tap(adb_exe, porta, TAP_CONTINUE, "Tap to Continue (torna_home)", log_fn)
        time.sleep(2.5)
        # Riverifica dopo il tap
        screen = _screenshot(adb_exe, porta)
        if screen and _check(screen, "continue", log_fn=None):
            if log_fn: log_fn("[ARENA] ANOMALIA: ancora sulla schermata risultato — retry tap")
            _tap(adb_exe, porta, TAP_CONTINUE, "Tap to Continue retry", log_fn)
            time.sleep(2.5)

    # Ora usa BACK per tornare in home dalla lista sfide
    for _ in range(4):
        _back(adb_exe, porta)
        time.sleep(0.8)

def _esegui_sfida(adb_exe, porta, n, log_fn=None):
    if log_fn: log_fn(f"[ARENA] sfida {n}/{MAX_SFIDE}")

    # [PRE-SFIDA] lista visibile prima del tap
    ok_lista, _ = _screen_check(adb_exe, porta, "lista", log_fn, retry=1, retry_s=1.5)
    if not ok_lista:
        if log_fn: log_fn("[ARENA] [PRE-SFIDA] ANOMALIA: lista non visibile — abort")
        return "errore"

    _tap(adb_exe, porta, TAP_ULTIMA_SFIDA, "ultima sfida", log_fn)
    time.sleep(3.0)

    # [CHECK-PURCHASE] sfide esaurite?
    ok_purch, _ = _screen_check(adb_exe, porta, "purchase", log_fn, retry=1, retry_s=1.0)
    if ok_purch:
        if log_fn: log_fn("[ARENA] [CHECK-PURCHASE] pin_arena_06 visibile — esaurite → Cancel")
        _tap(adb_exe, porta, TAP_ESAURITE_CANCEL, "Cancel", log_fn)
        time.sleep(1.5)
        return "esaurite"

    # [PRE-CHALLENGE] START CHALLENGE visibile?
    ok_ch, _ = _screen_check(adb_exe, porta, "challenge", log_fn, retry=2, retry_s=1.5)
    if not ok_ch:
        if log_fn: log_fn("[ARENA] [PRE-CHALLENGE] ANOMALIA: START CHALLENGE non visibile — abort")
        _back(adb_exe, porta)
        time.sleep(1.5)
        return "errore"
    if log_fn: log_fn("[ARENA] [PRE-CHALLENGE] pin_arena_02 visibile — tap START CHALLENGE")
    _tap(adb_exe, porta, TAP_START_CHALLENGE, "START CHALLENGE", log_fn)

    # Attesa battaglia
    time.sleep(12.0)

    # [POST-BATTAGLIA] victory o failure?
    screen = _screenshot(adb_exe, porta)
    victory = _check(screen, "victory", log_fn) if screen else False
    failure = _check(screen, "failure", log_fn) if screen else False

    if victory:
        if log_fn: log_fn("[ARENA] [POST-BATTAGLIA] pin_arena_03 — Victory ✓")
    elif failure:
        if log_fn: log_fn("[ARENA] [POST-BATTAGLIA] pin_arena_04 — Failure")
    else:
        if log_fn: log_fn("[ARENA] [POST-BATTAGLIA] ANOMALIA: né Victory né Failure — attendo 5s")
        time.sleep(5.0)
        screen = _screenshot(adb_exe, porta)
        victory = _check(screen, "victory", log_fn) if screen else False
        failure = _check(screen, "failure", log_fn) if screen else False
        if not victory and not failure:
            if log_fn: log_fn("[ARENA] [POST-BATTAGLIA] ANOMALIA persistente — tento Continue")

    # [PRE-CONTINUE] Tap to Continue visibile?
    ok_cont, _ = _screen_check(adb_exe, porta, "continue", log_fn, retry=2, retry_s=1.5)
    if ok_cont:
        if log_fn: log_fn("[ARENA] [PRE-CONTINUE] pin_arena_05 visibile — tap Tap to Continue")
    else:
        if log_fn: log_fn("[ARENA] [PRE-CONTINUE] ANOMALIA: Tap to Continue non visibile — tap fallback")
    _tap(adb_exe, porta, TAP_CONTINUE, "Tap to Continue", log_fn)
    time.sleep(2.5)

    # [POST-CONTINUE] lista tornata?
    ok_lista_post, _ = _screen_check(adb_exe, porta, "lista", log_fn, retry=2, retry_s=1.5)
    if ok_lista_post:
        if log_fn: log_fn("[ARENA] [POST-CONTINUE] pin_arena_01 visibile — lista OK")
    else:
        if log_fn: log_fn("[ARENA] [POST-CONTINUE] ANOMALIA: lista non tornata — procedo")

    return "ok"

def run_arena_of_glory(adb_exe, porta, log_fn=None):
    """
    Entry point — chiamabile dal bot (daily_tasks.py).
    Firma retrocompatibile: run_arena_of_glory(adb_exe, porta, log_fn=None)

    Logica a 3 tentativi:
      Per ogni tentativo:
        1. vai_in_home (toggle confermato)
        2. naviga verso Arena of Glory
           [PRE-LISTA] pin_arena_01_lista visibile?
             NO → 4x BACK + vai_in_home → prossimo tentativo
             SI → procedi
        3. loop sfide
        4. successo = almeno 1 sfida eseguita o esaurite rilevato
           Registra_esecuzione solo a successo confermato.
    """
    porta = str(porta)
    risultato = {"sfide_eseguite": 0, "esaurite": False, "errore": None}
    MAX_TENTATIVI = 3

    def log(msg):
        if log_fn: log_fn(msg)
        else: print(msg)

    log(f"[ARENA] Avvio Arena of Glory (max {MAX_SFIDE} sfide)")

    for tentativo in range(1, MAX_TENTATIVI + 1):
        log(f"[ARENA] tentativo {tentativo}/{MAX_TENTATIVI}")

        # STEP 1: verifica home con toggle
        if not _vai_in_home_arena(adb_exe, porta, log):
            log(f"[ARENA] impossibile confermare home (t={tentativo}) — prossimo tentativo")
            continue

        # STEP 2: naviga verso Arena of Glory
        if not _naviga_a_arena(adb_exe, porta, log):
            log(f"[ARENA] [PRE-LISTA] lista non raggiunta — 4x BACK + prossimo tentativo")
            _torna_home(adb_exe, porta, log)
            continue

        # STEP 3: loop sfide
        errore_loop = None
        try:
            for i in range(1, MAX_SFIDE + 1):
                esito = _esegui_sfida(adb_exe, porta, i, log)
                if esito == "esaurite":
                    risultato["esaurite"] = True
                    break
                if esito == "ok":
                    risultato["sfide_eseguite"] += 1
                    log(f"[ARENA] Progresso: {risultato['sfide_eseguite']}/{MAX_SFIDE}")
                    continue
                # errore singola sfida
                errore_loop = f"errore sfida {i}"
                break
        except Exception as e:
            errore_loop = str(e)
            log(f"[ARENA] Eccezione nel loop: {e}")

        # STEP 4: verifica successo
        successo = risultato["sfide_eseguite"] > 0 or risultato["esaurite"]

        log(f"[ARENA] tentativo {tentativo}: sfide={risultato['sfide_eseguite']} "
            f"esaurite={risultato['esaurite']} successo={successo}")

        _torna_home(adb_exe, porta, log)

        if successo:
            log(f"[ARENA] completato ✓ — {risultato['sfide_eseguite']} sfide"
                + (" (esaurite)" if risultato["esaurite"] else ""))
            return risultato

        log(f"[ARENA] tentativo {tentativo} senza sfide eseguite — "
            + ("altro tentativo" if tentativo < MAX_TENTATIVI else "fallito"))
        if errore_loop:
            risultato["errore"] = errore_loop

    if not (risultato["sfide_eseguite"] > 0 or risultato["esaurite"]):
        log(f"[ARENA] fallito dopo {MAX_TENTATIVI} tentativi")
        if not risultato["errore"]:
            risultato["errore"] = "nessuna sfida eseguita dopo tutti i tentativi"

    return risultato
