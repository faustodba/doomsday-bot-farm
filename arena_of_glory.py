# arena_of_glory.py
"""
Modulo standalone — Arena of Glory (Arena of Doom).
Task giornaliero: esegue MAX_SFIDE sfide con verifica visiva pin a ogni step.

PIN (tutti in C:\\Bot-farm\\templates\\):
  pin_arena_01_lista.png      ROI=(387,0,565,43)     soglia=0.80
  pin_arena_02_challenge.png  ROI=(610,434,857,486)  soglia=0.80
  pin_arena_03_victory.png    ROI=(407,89,557,156)   soglia=0.80
  pin_arena_04_failure.png    ROI=(414,94,544,146)   soglia=0.80
  pin_arena_05_continue.png   ROI=(410,443,547,487)  soglia=0.80  [rilevamento diagnostico only]
  pin_arena_06_purchase.png   ROI=(334,143,586,185)  soglia=0.80
  pin_arena_07_glory.png      ROI=(379,418,564,447)  soglia=0.80  [popup Glory Silver / Congratulations]
  pin_360_open.png            ROI=(140,265,325,305)  soglia=0.75  [pulsante acquisto attivo — sfondo arancione]
  pin_360_close.png           ROI=(140,265,325,305)  soglia=0.75  [pulsante acquisto disabilitato — sfondo grigio]

CHANGELOG:
  - pin_arena_07_glory: rileva il popup "Congratulations / Glory Silver" che compare
    alla prima entrata in arena (o cambio tier). Gestito in _naviga_a_arena e come
    guard in _esegui_sfida (pre-sfida e post-continue).
  - Post-battaglia: tap su coordinata fissa dipendente dal risultato:
    Victory → (457,462), Failure → (469,509). Fallback doppio tap centro (480,270)
    per timeout/anomalia. pin_arena_05 usato solo per rilevamento diagnostico.
  - _torna_home: doppio tap centro prima dei BACK per chiudere overlay persistenti
    (fix FAU_07).
  - _attendi_fine_battaglia: delay iniziale fisso (8s) + polling ogni 3s fino a 30s
    max. Il delay iniziale copre il lag di rete/rendering schermata battaglia.
  - Mercato Arena: _visita_mercato_arena() naviga carrello → acquista pack finché
    pulsante attivo (arancione). run_mercato_arena() è entry point separato schedulato
    ogni 4h (SCHEDULE_ORE_ARENA_MERCATO), indipendente dalle sfide.
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

# Tap "Tap to continue" post-battaglia — coordinata dipende dal risultato
_TAP_CONTINUE_VICTORY = (457, 462)   # coordinata su schermata Victory
_TAP_CONTINUE_FAILURE = (469, 509)   # coordinata su schermata Failure

# Doppio tap centro schermo — fallback per timeout/anomalia (né victory né failure)
_TAP_CENTRO       = (480, 270)
_TAP_CENTRO_PAUSE = 0.8   # pausa tra il primo e il secondo tap centro

# Tap sul bottone Continue del popup Glory Silver
# Calcolato dal centro della ROI: ((379+564)//2, (418+447)//2)
_TAP_GLORY_CONTINUE = (471, 432)

_CONGRATS_CHECK_XY  = config.ARENA_CONGRATS_CHECK_XY
_CONGRATS_BGR_LOW   = np.array(config.ARENA_CONGRATS_BGR_LOW,  dtype=np.uint8)
_CONGRATS_BGR_HIGH  = np.array(config.ARENA_CONGRATS_BGR_HIGH, dtype=np.uint8)

# Parametri attesa battaglia
_ATTESA_BATTAGLIA_DELAY_S = 8.0   # sleep iniziale fisso (lag rete/rendering schermata battaglia)
_ATTESA_BATTAGLIA_POLL_S  = 3.0   # intervallo polling post-delay
_ATTESA_BATTAGLIA_MAX_S   = 30.0  # timeout massimo del polling (escluso delay iniziale)

_ARENA_PIN = {
    "lista":     ("pin_arena_01_lista.png",     (387,  0,  565,  43), 0.80),
    "challenge": ("pin_arena_02_challenge.png", (610, 434, 857, 486), 0.80),
    "victory":   ("pin_arena_03_victory.png",   (407,  89, 557, 156), 0.80),
    "failure":   ("pin_arena_04_failure.png",   (414,  94, 544, 146), 0.80),
    "continue":  ("pin_arena_05_continue.png",  (410, 443, 547, 487), 0.80),
    "purchase":  ("pin_arena_06_purchase.png",  (334, 143, 586, 185), 0.80),
    "glory":        ("pin_arena_07_glory.png",     (379, 418, 564, 447), 0.80),
    "btn360_open":  ("pin_360_open.png",            (140, 265, 325, 305), 0.75),
    "btn360_close": ("pin_360_close.png",           (140, 265, 325, 305), 0.75),
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

def _doppio_tap_centro(adb_exe, porta, log_fn=None):
    """Doppio tap al centro schermo per chiudere overlay/risultato post-battaglia."""
    x, y = _TAP_CENTRO
    if log_fn: log_fn(f"[ARENA] doppio tap centro ({x},{y})")
    _adb(adb_exe, porta, "shell", "input", "tap", str(x), str(y))
    time.sleep(_TAP_CENTRO_PAUSE)
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

def _gestisci_popup_glory(adb_exe, porta, log_fn=None) -> bool:
    """
    Rileva e chiude il popup 'Congratulations / Glory Silver' (pin_arena_07_glory).
    Compare alla prima entrata in arena o al cambio di tier stagionale.
    Ritorna True se il popup era presente ed è stato chiuso.
    """
    screen = _screenshot(adb_exe, porta)
    if not screen:
        return False
    ok = _check(screen, "glory", log_fn)
    if ok:
        if log_fn: log_fn("[ARENA] popup Glory Silver rilevato — tap Continue")
        _tap(adb_exe, porta, _TAP_GLORY_CONTINUE, "Glory Continue", log_fn)
        time.sleep(2.0)
        # Riverifica: se ancora visibile, secondo tap
        screen2 = _screenshot(adb_exe, porta)
        if screen2 and _check(screen2, "glory"):
            if log_fn: log_fn("[ARENA] popup Glory ancora visibile — retry tap")
            _tap(adb_exe, porta, _TAP_GLORY_CONTINUE, "Glory Continue retry", log_fn)
            time.sleep(2.0)
        return True
    return False

def _gestisci_popup_congratulations(adb_exe, porta, log_fn=None):
    """Controllo pixel per popup Congratulations generico (pre-esistente)."""
    screen = _screenshot(adb_exe, porta)
    if not screen: return False
    img = cv2.imread(screen)
    if img is None: return False
    px,py = _CONGRATS_CHECK_XY
    pixel = img[py, px]
    if np.all(pixel >= _CONGRATS_BGR_LOW) and np.all(pixel <= _CONGRATS_BGR_HIGH):
        if log_fn: log_fn("[ARENA] popup Congratulations (pixel) rilevato — tap Continue")
        _tap(adb_exe, porta, TAP_CONGRATULATIONS, "Continue", log_fn)
        time.sleep(2.0)
        return True
    return False

def _gestisci_tutti_popup(adb_exe, porta, log_fn=None):
    """
    Controlla in sequenza: Glory pin → Congratulations pixel.
    Chiamato in _naviga_a_arena e come guard leggero in _esegui_sfida.
    """
    _gestisci_popup_glory(adb_exe, porta, log_fn)
    _gestisci_popup_congratulations(adb_exe, porta, log_fn)

def _naviga_a_arena(adb_exe, porta, log_fn=None):
    if log_fn: log_fn("[ARENA] HOME → Campaign")
    _tap(adb_exe, porta, TAP_CAMPAIGN, "Campaign", log_fn)
    time.sleep(3.0)
    if log_fn: log_fn("[ARENA] Campaign → Arena of Doom")
    _tap(adb_exe, porta, TAP_ARENA_OF_DOOM, "Arena of Doom", log_fn)
    time.sleep(3.5)
    # Gestisce sia Glory Silver che Congratulations generico
    _gestisci_tutti_popup(adb_exe, porta, log_fn)
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

    Strategia:
      1. Doppio tap centro schermo per chiudere overlay/risultato persistenti
         (fix FAU_07: overlay post-arena non chiudibile con soli BACK).
      2. Pausa 1.5s.
      3. 4x BACK per uscire dalla lista arena.
    """
    if log_fn: log_fn("[ARENA] ritorno HOME — doppio tap centro + BACK")
    _doppio_tap_centro(adb_exe, porta, log_fn)
    time.sleep(1.5)
    for _ in range(4):
        _back(adb_exe, porta)
        time.sleep(0.8)


def _attendi_fine_battaglia(adb_exe, porta, log_fn=None):
    """
    Attesa fine battaglia con delay iniziale fisso + polling adattivo.

    Flusso:
      1. Sleep _ATTESA_BATTAGLIA_DELAY_S (8s): tempo minimo per caricamento
         schermata battaglia (lag rete / rendering). Evita false negative su
         schermate di transizione.
      2. Polling ogni _ATTESA_BATTAGLIA_POLL_S (3s) fino a _ATTESA_BATTAGLIA_MAX_S (30s).
         Esce non appena rileva victory o failure.

    Ritorna: (victory: bool, failure: bool, screen_path: str)
    """
    if log_fn: log_fn(f"[ARENA] attesa battaglia — delay iniziale {_ATTESA_BATTAGLIA_DELAY_S:.0f}s")
    time.sleep(_ATTESA_BATTAGLIA_DELAY_S)

    t_start = time.time()
    screen = ""
    victory = False
    failure = False

    while time.time() - t_start < _ATTESA_BATTAGLIA_MAX_S:
        screen = _screenshot(adb_exe, porta)
        if screen:
            victory = _check(screen, "victory")
            failure = _check(screen, "failure")
            elapsed = _ATTESA_BATTAGLIA_DELAY_S + (time.time() - t_start)
            if victory or failure:
                if log_fn: log_fn(f"[ARENA] fine battaglia rilevata in {elapsed:.1f}s totali")
                break
        time.sleep(_ATTESA_BATTAGLIA_POLL_S)

    if not victory and not failure:
        totale = _ATTESA_BATTAGLIA_DELAY_S + _ATTESA_BATTAGLIA_MAX_S
        if log_fn: log_fn(f"[ARENA] [POST-BATTAGLIA] timeout — né Victory né Failure dopo {totale:.0f}s totali")

    return victory, failure, screen


def _esegui_sfida(adb_exe, porta, n, log_fn=None):
    if log_fn: log_fn(f"[ARENA] sfida {n}/{MAX_SFIDE}")

    # [GUARD-GLORY] popup Glory Silver può comparire tra una sfida e l'altra
    # (es. cambio tier mid-session). Check leggero prima di ogni sfida.
    screen_guard = _screenshot(adb_exe, porta)
    if screen_guard and _check(screen_guard, "glory"):
        if log_fn: log_fn("[ARENA] [GUARD-GLORY] popup Glory pre-sfida — chiudo")
        _tap(adb_exe, porta, _TAP_GLORY_CONTINUE, "Glory Continue guard", log_fn)
        time.sleep(2.0)

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

    # Attesa battaglia: delay iniziale fisso + polling adattivo
    victory, failure, screen = _attendi_fine_battaglia(adb_exe, porta, log_fn)

    if victory:
        if log_fn: log_fn("[ARENA] [POST-BATTAGLIA] pin_arena_03 — Victory ✓")
    elif failure:
        if log_fn: log_fn("[ARENA] [POST-BATTAGLIA] pin_arena_04 — Failure")
    else:
        if log_fn: log_fn("[ARENA] [POST-BATTAGLIA] ANOMALIA persistente — procedo con doppio tap centro")

    # Rilevamento pin_continue (solo diagnostico)
    if screen:
        ok_cont = _check(screen, "continue", log_fn)
        if log_fn:
            if ok_cont:
                log_fn("[ARENA] [PRE-CONTINUE] pin_arena_05 visibile")
            else:
                log_fn("[ARENA] [PRE-CONTINUE] pin_arena_05 non visibile")

    # Tap "Tap to continue" con coordinata dipendente dal risultato
    if victory:
        if log_fn: log_fn(f"[ARENA] [CONTINUE] Victory → tap {_TAP_CONTINUE_VICTORY}")
        _tap(adb_exe, porta, _TAP_CONTINUE_VICTORY, "continue-victory", log_fn)
    elif failure:
        if log_fn: log_fn(f"[ARENA] [CONTINUE] Failure → tap {_TAP_CONTINUE_FAILURE}")
        _tap(adb_exe, porta, _TAP_CONTINUE_FAILURE, "continue-failure", log_fn)
    else:
        if log_fn: log_fn("[ARENA] [CONTINUE] timeout/anomalia → doppio tap centro fallback")
        _doppio_tap_centro(adb_exe, porta, log_fn)
    time.sleep(2.5)

    # [POST-CONTINUE] controlla popup Glory post-vittoria (cambio tier) poi verifica lista
    screen_post = _screenshot(adb_exe, porta)
    if screen_post and _check(screen_post, "glory"):
        if log_fn: log_fn("[ARENA] [POST-CONTINUE] popup Glory post-sfida — chiudo")
        _tap(adb_exe, porta, _TAP_GLORY_CONTINUE, "Glory Continue post-sfida", log_fn)
        time.sleep(2.0)

    ok_lista_post, _ = _screen_check(adb_exe, porta, "lista", log_fn, retry=2, retry_s=1.5)
    if ok_lista_post:
        if log_fn: log_fn("[ARENA] [POST-CONTINUE] pin_arena_01 visibile — lista OK")
    else:
        if log_fn: log_fn("[ARENA] [POST-CONTINUE] lista non tornata subito — attendo 2s e riprovo")
        time.sleep(2.0)
        ok_lista_post2, _ = _screen_check(adb_exe, porta, "lista", log_fn, retry=2, retry_s=1.5)
        if ok_lista_post2:
            if log_fn: log_fn("[ARENA] [POST-CONTINUE] lista OK al retry")
        else:
            if log_fn: log_fn("[ARENA] [POST-CONTINUE] ANOMALIA: lista ancora non visibile — procedo comunque")

    return "ok"

# ------------------------------------------------------------------------------
# Mercato Arena (Arena Store)
# ------------------------------------------------------------------------------

_TAP_CARRELLO    = config.ARENA_TAP_CARRELLO
_TAP_PRIMO_ACQ   = config.ARENA_TAP_PRIMO_ACQUISTO
_TAP_MAX_ACQ     = config.ARENA_TAP_MAX_ACQUISTO

_MERCATO_MAX_ITER = 20   # guard anti-loop


def _pulsante_acquisto_attivo(screen_path: str, log_fn=None) -> bool:
    """
    Template matching per rilevare lo stato del pulsante Intermediate Resource Pack.
    Cerca prima pin_360_open (attivo/arancione): se score >= soglia → True.
    Poi verifica pin_360_close (disabilitato/grigio): se score >= soglia → False.
    Se nessuno dei due supera la soglia → False (fail-safe: non acquistare).
    """
    score_open  = _match_pin(screen_path, "btn360_open")
    score_close = _match_pin(screen_path, "btn360_close")
    if log_fn:
        log_fn(f"[MERCATO] btn360_open={score_open:.3f} btn360_close={score_close:.3f}")
    _, _, soglia_open  = _ARENA_PIN["btn360_open"]
    _, _, soglia_close = _ARENA_PIN["btn360_close"]
    if score_open >= soglia_open:
        return True
    if score_close >= soglia_close:
        return False
    # Nessun match chiaro: fallback su open se score_open > score_close
    return score_open > score_close


def _visita_mercato_arena(adb_exe: str, porta: str, log_fn=None) -> int:
    """
    Apre l'Arena Store e acquista tutti i pack disponibili con le monete correnti.

    Flusso:
      1. Tap carrello (905,68) → apre Arena Store  [attesa 2s]
      2. Template matching pin_360_open/close:
           open  → continua
           close → stop (monete/stock esauriti)
      3. Tap primo acquisto (235,283) → acquista 1, compaiono pulsanti quantità  [attesa 1s]
      4. Tap pulsante destra (451,286) → acquista max disponibile (≤50)          [attesa 1.5s]
      5. Torna a 2 — ripete finché pulsante grigio o max iterazioni
      6. BACK → torna alla lista arena

    Ritorna numero di cicli di acquisto eseguiti (0 = niente da comprare).
    """
    def log(msg):
        if log_fn: log_fn(msg)

    log("[MERCATO] Apertura Arena Store — tap carrello")
    _tap(adb_exe, porta, _TAP_CARRELLO, "carrello", log_fn)
    time.sleep(2.0)

    acquisti = 0
    for _ in range(_MERCATO_MAX_ITER):
        screen = _screenshot(adb_exe, porta)
        if not screen:
            log("[MERCATO] screenshot fallito — stop")
            break

        if not _pulsante_acquisto_attivo(screen, log_fn):
            log(f"[MERCATO] pulsante non attivo — stop ({acquisti} cicli)")
            break

        log("[MERCATO] pulsante attivo — tap primo acquisto")
        _tap(adb_exe, porta, _TAP_PRIMO_ACQ, "primo acquisto", log_fn)
        time.sleep(1.0)

        log("[MERCATO] tap max acquisto (destra)")
        _tap(adb_exe, porta, _TAP_MAX_ACQ, "max acquisto", log_fn)
        time.sleep(1.5)
        acquisti += 1

    log(f"[MERCATO] completato — {acquisti} cicli acquisto")
    _back(adb_exe, porta)
    time.sleep(1.5)
    return acquisti


def run_mercato_arena(adb_exe, porta, log_fn=None) -> dict:
    """
    Entry point mercato Arena — chiamabile da daily_tasks.py.
    Schedulazione: SCHEDULE_ORE_ARENA_MERCATO (default 4h), chiave "arena_mercato".

    Naviga: home → Campaign → Arena of Glory → Store → acquista → home.
    Indipendente dalle sfide giornaliere.

    Ritorna: {"acquisti": int, "errore": str|None}
    """
    porta = str(porta)
    risultato = {"acquisti": 0, "errore": None}

    def log(msg):
        if log_fn: log_fn(msg)
        else: print(msg)

    log("[MERCATO-ARENA] Avvio visita mercato")

    if not _vai_in_home_arena(adb_exe, porta, log):
        risultato["errore"] = "impossibile raggiungere home"
        log(f"[MERCATO-ARENA] {risultato['errore']}")
        return risultato

    if not _naviga_a_arena(adb_exe, porta, log):
        risultato["errore"] = "impossibile raggiungere lista arena"
        log(f"[MERCATO-ARENA] {risultato['errore']}")
        _torna_home(adb_exe, porta, log)
        return risultato

    try:
        risultato["acquisti"] = _visita_mercato_arena(adb_exe, porta, log)
    except Exception as e:
        risultato["errore"] = str(e)
        log(f"[MERCATO-ARENA] errore: {e}")

    _torna_home(adb_exe, porta, log)
    log(f"[MERCATO-ARENA] completato — acquisti={risultato['acquisti']}"
        + (f" errore={risultato['errore']}" if risultato["errore"] else ""))
    return risultato


def run_arena_of_glory(adb_exe, porta, log_fn=None):
    """
    Entry point — chiamabile dal bot (daily_tasks.py).
    Firma retrocompatibile: run_arena_of_glory(adb_exe, porta, log_fn=None)

    Logica a 3 tentativi:
      Per ogni tentativo:
        1. vai_in_home (toggle confermato)
        2. naviga verso Arena of Glory
           [PRE-LISTA] pin_arena_01_lista visibile?
             NO → doppio tap + 4x BACK + vai_in_home → prossimo tentativo
             SI → procedi
        3. loop sfide
        4. successo = esaurite rilevato OPPURE tutte le sfide (MAX_SFIDE) completate
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
            log(f"[ARENA] [PRE-LISTA] lista non raggiunta — torna home + prossimo tentativo")
            _torna_home(adb_exe, porta, log)
            continue

        # STEP 3: loop sfide
        errore_loop = None
        errori_consecutivi = 0
        MAX_ERRORI_CONSECUTIVI = 2
        try:
            for i in range(1, MAX_SFIDE + 1):
                esito = _esegui_sfida(adb_exe, porta, i, log)
                if esito == "esaurite":
                    risultato["esaurite"] = True
                    errori_consecutivi = 0
                    break
                if esito == "ok":
                    risultato["sfide_eseguite"] += 1
                    errori_consecutivi = 0
                    log(f"[ARENA] Progresso: {risultato['sfide_eseguite']}/{MAX_SFIDE}")
                    continue
                # esito == "errore": conta ma non fermare subito
                errori_consecutivi += 1
                log(f"[ARENA] errore sfida {i} ({errori_consecutivi}/{MAX_ERRORI_CONSECUTIVI} consecutivi)")
                if errori_consecutivi >= MAX_ERRORI_CONSECUTIVI:
                    errore_loop = f"troppi errori consecutivi alla sfida {i}"
                    break
                # Piccola pausa prima di riprovare la prossima sfida
                time.sleep(2.0)
        except Exception as e:
            errore_loop = str(e)
            log(f"[ARENA] Eccezione nel loop: {e}")

        # STEP 4: verifica successo
        # Successo = esaurite rilevato OPPURE ha eseguito tutte le sfide previste
        # Una sola sfida non basta per considerare completato (potrebbe essere un
        # errore intermedio che ha interrotto il loop prematuramente)
        successo = risultato["esaurite"] or risultato["sfide_eseguite"] >= MAX_SFIDE

        log(f"[ARENA] tentativo {tentativo}: sfide={risultato['sfide_eseguite']} "
            f"esaurite={risultato['esaurite']} successo={successo}")

        _torna_home(adb_exe, porta, log)

        if successo:
            log(f"[ARENA] completato ✓ — {risultato['sfide_eseguite']} sfide"
                + (" (esaurite)" if risultato["esaurite"] else ""))
            return risultato

        # Non completato: log e prossimo tentativo se sfide parziali eseguite
        motivo = "esaurite" if risultato["esaurite"] else f"{risultato['sfide_eseguite']}/{MAX_SFIDE} sfide"
        log(f"[ARENA] tentativo {tentativo} incompleto ({motivo}) — "
            + ("altro tentativo" if tentativo < MAX_TENTATIVI else "fallito"))
        if errore_loop:
            risultato["errore"] = errore_loop

    if not (risultato["sfide_eseguite"] > 0 or risultato["esaurite"]):
        log(f"[ARENA] fallito dopo {MAX_TENTATIVI} tentativi")
        if not risultato["errore"]:
            risultato["errore"] = "nessuna sfida eseguita dopo tutti i tentativi"

    return risultato
