# rifornimento_mappa.py
"""
Modulo alternativo rifornimento — navigazione via coordinate mappa.

Bypassa la ricerca avatar nella lista Membri navigando direttamente
alle coordinate del rifugio destinatario sulla mappa.

Flusso completo:
  STEP 1 — Centratura mappa:
    Mappa → lente coordinate → digita X,Y → conferma → mappa centrata
  STEP 2 — Tap rifugio + popup:
    Tap castello → attende popup → trova RESOURCE SUPPLY via template → tap
  STEP 3 — Apertura maschera invio:
    Tap RESOURCE SUPPLY → verifica apertura maschera
  STEP 4 — Invio risorse:
    Riusa _compila_e_invia() da rifornimento.py

Coordinate hardcoded (da esternalizzare in file config dedicato):
    RIFUGIO_X = 684
    RIFUGIO_Y = 532

Test standalone:
  python test_rifornimento_mappa.py --porta 16384 --nome FAU_00 --step 1234
"""

import os
import time
import traceback
import subprocess

import cv2
import numpy as np
import config

# ── Coordinate rifugio destinatario (hardcoded — TODO: esternalizzare) ─────────
RIFUGIO_X = 684
RIFUGIO_Y = 532

# ── Coordinate UI 960x540 ──────────────────────────────────────────────────────
TAP_LENTE_MAPPA     = (334,  13)   # lente coordinate sulla mappa
TAP_CAMPO_X         = (484, 135)   # campo X nella lente
TAP_CAMPO_Y         = (601, 135)   # campo Y nella lente
TAP_CONFERMA_LENTE  = (670, 135)   # tap lente/conferma → centra mappa
TAP_CASTELLO_CENTER = (480, 270)   # centro schermo dopo centratura

# ── Template RESOURCE SUPPLY ───────────────────────────────────────────────────
TEMPLATE_RESOURCE_SUPPLY = os.path.join(config.BOT_DIR, "templates", "btn_resource_supply_map.png")
TEMPLATE_SOGLIA           = 0.75

SCREEN_TMP = os.path.join(config.BOT_DIR, "screen_rifmappa.png")

# ── ADB helpers ────────────────────────────────────────────────────────────────

def _adb(adb_exe, porta, *args):
    cmd = [adb_exe, "-s", f"127.0.0.1:{porta}"] + list(args)
    return subprocess.run(cmd, capture_output=True)

def _tap(adb_exe, porta, x, y, label=""):
    _adb(adb_exe, porta, "shell", "input", "tap", str(x), str(y))
    print(f"  [TAP] ({x},{y})" + (f" — {label}" if label else ""))

def _back(adb_exe, porta):
    _adb(adb_exe, porta, "shell", "input", "keyevent", "4")

def _testo(adb_exe, porta, testo):
    _adb(adb_exe, porta, "shell", "input", "text", str(testo))
    print(f"  [TEXT] '{testo}'")

def _cancella(adb_exe, porta, n=10):
    for _ in range(n):
        _adb(adb_exe, porta, "shell", "input", "keyevent", "67")

def _screenshot(adb_exe, porta):
    """Cattura screenshot e restituisce immagine numpy BGR."""
    _adb(adb_exe, porta, "shell", "screencap", "-p", "/sdcard/screen_rifmappa.png")
    r = _adb(adb_exe, porta, "pull", "/sdcard/screen_rifmappa.png", SCREEN_TMP)
    if r.returncode != 0:
        print("[RIFMAPPA] Screenshot fallito")
        return None
    img = cv2.imread(SCREEN_TMP)
    return img

# ── Template matching ──────────────────────────────────────────────────────────

def _trova_resource_supply(img):
    """
    Cerca il pulsante RESOURCE SUPPLY nell'immagine via template matching.
    Ritorna (cx, cy) coordinate centro pulsante, oppure None se non trovato.
    """
    if img is None:
        return None
    if not os.path.exists(TEMPLATE_RESOURCE_SUPPLY):
        print(f"[RIFMAPPA] Template non trovato: {TEMPLATE_RESOURCE_SUPPLY}")
        return None

    tmpl = cv2.imread(TEMPLATE_RESOURCE_SUPPLY)
    if tmpl is None:
        print("[RIFMAPPA] Errore lettura template")
        return None

    result = cv2.matchTemplate(img, tmpl, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    print(f"  [TEMPLATE] RESOURCE SUPPLY score={max_val:.3f} (soglia={TEMPLATE_SOGLIA})")

    if max_val < TEMPLATE_SOGLIA:
        print("  [TEMPLATE] Pulsante non trovato")
        return None

    th, tw = tmpl.shape[:2]
    cx = max_loc[0] + tw // 2
    cy = max_loc[1] + th // 2
    print(f"  [TEMPLATE] Pulsante trovato a ({cx},{cy})")
    return (cx, cy)

# ── Step 1 — Centratura mappa sul rifugio ─────────────────────────────────────

def centra_mappa_su_rifugio(adb_exe, porta, x=None, y=None):
    """
    Dalla mappa: apre lente coordinate, digita X e Y del rifugio, conferma.
    Ritorna True se completato senza errori.
    """
    rx = x if x is not None else RIFUGIO_X
    ry = y if y is not None else RIFUGIO_Y

    print(f"[RIFMAPPA] Centratura mappa su rifugio X:{rx} Y:{ry}")

    try:
        _tap(adb_exe, porta, *TAP_LENTE_MAPPA, "apre lente coordinate")
        time.sleep(1.5)

        _tap(adb_exe, porta, *TAP_CAMPO_X, "campo X")
        time.sleep(0.4)
        _cancella(adb_exe, porta, n=6)
        time.sleep(0.2)
        _testo(adb_exe, porta, rx)
        time.sleep(0.4)

        _tap(adb_exe, porta, *TAP_CAMPO_Y, "campo Y")
        time.sleep(0.4)
        _cancella(adb_exe, porta, n=6)
        time.sleep(0.2)
        _testo(adb_exe, porta, ry)
        time.sleep(0.4)

        _tap(adb_exe, porta, *TAP_CONFERMA_LENTE, "conferma lente")
        time.sleep(2.5)

        print(f"[RIFMAPPA] Centratura completata")
        return True

    except Exception as e:
        print(f"[RIFMAPPA] Errore centratura: {e}")
        return False

# ── Step 2 — Tap castello + trova RESOURCE SUPPLY ─────────────────────────────

def apri_popup_rifugio(adb_exe, porta, tap_x=None, tap_y=None):
    """
    Tappa il castello al centro schermo, attende il popup e cerca
    il pulsante RESOURCE SUPPLY via template matching.
    Ritorna (cx, cy) del pulsante o None.
    """
    tx = tap_x if tap_x is not None else TAP_CASTELLO_CENTER[0]
    ty = tap_y if tap_y is not None else TAP_CASTELLO_CENTER[1]

    print(f"[RIFMAPPA] Tap castello a ({tx},{ty})")
    _tap(adb_exe, porta, tx, ty, "tap castello")
    time.sleep(2.0)

    print("[RIFMAPPA] Screenshot e ricerca pulsante RESOURCE SUPPLY")
    img = _screenshot(adb_exe, porta)
    coord = _trova_resource_supply(img)

    if coord is None:
        print("[RIFMAPPA] Pulsante RESOURCE SUPPLY non trovato")
        return None

    return coord

# ── Step 3 — Tap RESOURCE SUPPLY → apertura maschera invio ────────────────────

def tap_resource_supply(adb_exe, porta, coord):
    """
    Tappa il pulsante RESOURCE SUPPLY e verifica apertura maschera.
    Ritorna True se la maschera è aperta.
    """
    if coord is None:
        print("[RIFMAPPA] Coordinate pulsante non disponibili")
        return False

    cx, cy = coord
    print(f"[RIFMAPPA] Tap RESOURCE SUPPLY a ({cx},{cy})")
    _tap(adb_exe, porta, cx, cy, "RESOURCE SUPPLY")
    time.sleep(2.5)

    print("[RIFMAPPA] Screenshot verifica apertura maschera")
    img = _screenshot(adb_exe, porta)
    if img is None:
        print("[RIFMAPPA] Screenshot fallito")
        return False

    print("[RIFMAPPA] Maschera aperta — verifica visiva")
    return True

# ── Step 4 — Invio risorse via _compila_e_invia() ─────────────────────────────

def invia_risorse(porta, nome, logger=None):
    """
    Riusa _compila_e_invia() da rifornimento.py per compilare i campi
    e premere VAI/GO nella maschera invio risorse già aperta.

    Precondizione: maschera invio risorse già aperta (Step 3 completato).

    Ritorna (ok, eta_sec, quota_esaurita, qta_inviata, mismatch_nome).
    """
    def log(msg):
        if logger:
            logger(nome, msg)
        else:
            print(f"  [INVIO] {msg}")

    try:
        from rifornimento import _compila_e_invia, _verifica_nome_destinatario, \
                                 _leggi_provviste, _leggi_tassa, _leggi_eta, \
                                 _vai_abilitato
        import adb as _adb_mod
    except Exception as e:
        log(f"Errore import: {e}")
        log(traceback.format_exc())
        return False, 0, False, 0, False

    # Assicura che adb.py usi l'exe MuMu — nel bot questo viene fatto da main.py
    # ma nel test standalone config.ADB_EXE punta ancora a BlueStacks per default
    if getattr(config, "MUMU_ADB", ""):
        config.ADB_EXE = config.MUMU_ADB
        log(f"ADB_EXE impostato a MUMU_ADB: {config.ADB_EXE}")

    nome_dest = getattr(config, "DOOMS_ACCOUNT", "")
    if not nome_dest:
        log("DOOMS_ACCOUNT non configurato")
        return False, 0, False, 0, False

    # ── Diagnostica pre-invio ──────────────────────────────────────────────────
    log("Scatto screenshot diagnostico pre-invio...")
    screen = _adb_mod.screenshot(porta)
    if not screen:
        log("Screenshot fallito — impossibile procedere")
        return False, 0, False, 0, False

    # Verifica nome
    ok_nome, testo_ocr = _verifica_nome_destinatario(screen, nome_dest)
    log(f"Verifica nome: OCR='{testo_ocr}' atteso='{nome_dest}' → {'OK' if ok_nome else 'MISMATCH'}")

    # Leggi provviste
    provviste = _leggi_provviste(screen)
    log(f"Provviste rimanenti: {provviste:,}" if provviste >= 0 else "Provviste: OCR fallito")

    # Leggi tassa
    tassa = _leggi_tassa(screen)
    log(f"Tassa: {tassa*100:.1f}%")

    # Leggi ETA
    eta = _leggi_eta(screen)
    log(f"ETA viaggio: {eta}s")

    # Verifica VAI prima di compilare (deve essere grigio = disabilitato)
    vai_prima = _vai_abilitato(screen)
    log(f"GO/VAI prima compilazione: {'giallo=abilitato (anomalo)' if vai_prima else 'grigio=disabilitato (atteso)'}")

    if provviste == 0:
        log("Provviste = 0 — nulla da inviare")
        return False, 0, True, 0, False

    if not ok_nome:
        log("Nome mismatch — invio annullato")
        return False, 0, False, 0, True

    # ── Chiama _compila_e_invia con una sola risorsa ───────────────────────────
    # Passa solo pomodoro per semplicità del test
    quantita_test = {"pomodoro": getattr(config, "RIFORNIMENTO_QTA_POMODORO", 1_000_000)}
    log(f"Chiamo _compila_e_invia — quantita={quantita_test}")

    def _logger_rif(n, msg):
        log(msg)

    try:
        ok, eta_sec, quota_esaurita, qta_inviata, mismatch_nome = _compila_e_invia(
            porta, quantita_test, nome_dest, _logger_rif, nome
        )
    except Exception as e:
        log(f"Eccezione in _compila_e_invia: {e}")
        log(traceback.format_exc())
        return False, 0, False, 0, False

    if ok:
        log(f"✓ Invio completato: {qta_inviata:,} unità | ETA {eta_sec}s")
    elif quota_esaurita:
        log("Provviste esaurite durante compilazione")
    elif mismatch_nome:
        log("Nome mismatch durante compilazione")
    else:
        log("Invio fallito — VAI non abilitato o errore generico")

    return ok, eta_sec, quota_esaurita, qta_inviata, mismatch_nome
