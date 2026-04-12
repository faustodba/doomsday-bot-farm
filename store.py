# ==============================================================================
# DOOMSDAY BOT V5 - store.py
# Acquisto automatico Mysterious Merchant Store.
#
# Flusso per istanza:
#   1. Verifica home (vai_in_home) — abort se non in home
#   2. Collassa banner eventi (libera viewport)
#   3. Scan griglia spirale 5x5 → trova edificio Store
#   4. Tap Store → verifica label / mercante diretto → tap carrello
#   5. Acquista tutti i pulsanti gialli (pin_legno/pomodoro/acciaio)
#   6. Swipe → pagina 2 → pagina 3
#   7. Free Refresh (una sola volta) se disponibile
#   8. Ripete acquisti dopo refresh
#   9. BACK → chiude negozio
#  10. Verifica home finale
#
# Schedulazione: ogni 4h (SCHEDULE_ORE_STORE), chiave "store"
# Feature flag:  STORE_ABILITATO in config.py / runtime.json
# Nessun retry, nessuno stato aggiunto.
#
# Chiamare da daily_tasks.py:
#   from store import esegui_store_guarded
#   esegui_store_guarded(porta, nome, logger)
#
# FIX v5.24.1:
#   - _screenshot() ora usa adb.screenshot_bytes() (ritorna bytes PNG)
#     invece di adb.screenshot() che ritorna un path stringa.
#     Il vecchio codice passava una str a decodifica_screenshot() che
#     si aspetta bytes → (None, None) su tutte le 25 posizioni →
#     best_score mai aggiornato → "Store NON trovato (best score=-1.000)".
# ==============================================================================

import os
import time
import numpy as np
from io import BytesIO
from PIL import Image, ImageDraw

import adb
import config
import scheduler
import stato as _stato

# ---------------------------------------------------------------------------
# Costanti — lette da config con fallback
# ---------------------------------------------------------------------------
def _c(name, default):
    return getattr(config, name, default)

SOGLIA_STORE        = lambda: _c("STORE_SOGLIA_STORE",        0.80)
SOGLIA_BANNER       = lambda: _c("STORE_SOGLIA_BANNER",       0.85)
SOGLIA_STORE_ATTIVO = lambda: _c("STORE_SOGLIA_STORE_ATTIVO", 0.80)
SOGLIA_CARRELLO     = lambda: _c("STORE_SOGLIA_CARRELLO",      0.75)
SOGLIA_MERCHANT     = lambda: _c("STORE_SOGLIA_MERCHANT",      0.75)
SOGLIA_MERCANTE     = lambda: _c("STORE_SOGLIA_MERCANTE",      0.80)
SOGLIA_ACQUISTO     = lambda: _c("STORE_SOGLIA_ACQUISTO",      0.80)
SOGLIA_FREE_REFRESH = lambda: _c("STORE_SOGLIA_FREE_REFRESH",  0.80)
SOGLIA_NO_REFRESH   = lambda: _c("STORE_SOGLIA_NO_REFRESH",    0.80)
PASSO_SCAN          = lambda: _c("STORE_PASSO_SCAN",           300)
MAX_PAGINE          = lambda: _c("STORE_MAX_PAGINE",           3)

# ROI fisse (coordinate 960x540)
ROI_HOME_BANNER_APERTO = (0, 115, 960, 470)
ROI_HOME_BANNER_CHIUSO = (0,  70, 960, 470)
ROI_BANNER_PIN         = (330, 40, 365, 90)
ROI_NEGOZIO            = (100, 100, 870, 455)
ROI_FOOTER             = (100, 450, 870, 540)

BANNER_TAP_X = 345
BANNER_TAP_Y = 63

SWIPE_CX  = 480
SWIPE_CY  = 300
SWIPE_DUR = 600

MERCHANT_SWIPE_DY  = 180
MERCHANT_SWIPE_DUR = 500

NMS_DIST = 40

# Pin pulsanti acquisto — escluso €0.99 che non ha nessuno di questi pin
PIN_ACQUISTO = ["pin_legno.png", "pin_pomodoro.png", "pin_acciaio.png"]

# Griglia spirale 5x5
GRIGLIA = [
    (   0,    0),
    (+300,    0), (   0, -300), (-300,    0), (-300,    0),
    (   0, +300), (   0, +300), (+300,    0), (+300,    0),
    (+300,    0), (   0, -300), (   0, -300), (   0, -300),
    (-300,    0), (-300,    0), (-300,    0), (-300,    0),
    (   0, +300), (   0, +300), (   0, +300), (   0, +300),
    (+300,    0), (+300,    0), (+300,    0), (+300,    0),
]

# ---------------------------------------------------------------------------
# Template matching
# ---------------------------------------------------------------------------
_tmpl_cache = {}

def _carica_tmpl(nome, log):
    if nome not in _tmpl_cache:
        import cv2
        path = os.path.join(_c("TEMPLATES_DIR", r"C:\Bot-farm\templates"), nome)
        t = cv2.imread(path) if os.path.exists(path) else None
        if t is None:
            log(f"[STORE] WARN template mancante: {path}")
        _tmpl_cache[nome] = t
    return _tmpl_cache[nome]


def _match(cv_img, tmpl_file, log, roi=None):
    """Miglior match singolo. Ritorna (score, cx, cy)."""
    import cv2
    tmpl = _carica_tmpl(tmpl_file, log)
    if tmpl is None or cv_img is None:
        return -1.0, -1, -1
    img = cv_img
    ox = oy = 0
    if roi:
        x1, y1, x2, y2 = roi
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(cv_img.shape[1], x2), min(cv_img.shape[0], y2)
        img = cv_img[y1:y2, x1:x2]
        ox, oy = x1, y1
    th, tw = tmpl.shape[:2]
    if img.shape[0] < th or img.shape[1] < tw:
        return -1.0, -1, -1
    try:
        res = cv2.matchTemplate(img, tmpl, cv2.TM_CCOEFF_NORMED)
        _, mv, _, ml = cv2.minMaxLoc(res)
        return float(mv), ox + ml[0] + tw // 2, oy + ml[1] + th // 2
    except Exception:
        return -1.0, -1, -1


def _match_tutti(cv_img, tmpl_file, soglia, log, roi=None, nms_dist=40):
    """Tutte le occorrenze con NMS. Ritorna lista (score, cx, cy)."""
    import cv2
    tmpl = _carica_tmpl(tmpl_file, log)
    if tmpl is None or cv_img is None:
        return []
    img = cv_img
    ox = oy = 0
    if roi:
        x1, y1, x2, y2 = roi
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(cv_img.shape[1], x2), min(cv_img.shape[0], y2)
        img = cv_img[y1:y2, x1:x2]
        ox, oy = x1, y1
    th, tw = tmpl.shape[:2]
    if img.shape[0] < th or img.shape[1] < tw:
        return []
    try:
        res = cv2.matchTemplate(img, tmpl, cv2.TM_CCOEFF_NORMED)
        locs = np.where(res >= soglia)
        punti = sorted(
            [(float(res[y, x]), ox + x + tw // 2, oy + y + th // 2)
             for y, x in zip(*locs)],
            reverse=True
        )
        selezionati = []
        for s, cx, cy in punti:
            if not any(abs(cx - px) < nms_dist and abs(cy - py) < nms_dist
                       for _, px, py in selezionati):
                selezionati.append((s, cx, cy))
        return selezionati
    except Exception:
        return []

# ---------------------------------------------------------------------------
# Screenshot in-memory
# ---------------------------------------------------------------------------

def _screenshot(porta, log):
    """
    Ritorna (pil, cv_img) via pipeline in-memoria.

    USA adb.screenshot_bytes() che ritorna bytes PNG grezzi.
    NON usa adb.screenshot() che ritorna un path stringa — incompatibile
    con adb.decodifica_screenshot() che si aspetta bytes.
    """
    try:
        raw = adb.screenshot_bytes(porta)          # <-- FIX: bytes, non path
        if not raw or len(raw) < 100:
            log(f"[STORE] WARN screenshot_bytes vuoto (porta={porta})")
            return None, None
        pil, cv_img = adb.decodifica_screenshot(raw)
        if cv_img is None:
            log(f"[STORE] WARN decodifica fallita (porta={porta})")
        return pil, cv_img
    except Exception as e:
        log(f"[STORE] WARN screenshot: {e}")
        return None, None

# ---------------------------------------------------------------------------
# ADB helpers
# ---------------------------------------------------------------------------

def _tap(porta, x, y):
    adb.tap(porta, (x, y))
    time.sleep(0.8)


def _back(porta):
    adb.keyevent(porta, "KEYCODE_BACK")
    time.sleep(0.8)


def _swipe_mappa(porta, dx, dy):
    if dx == 0 and dy == 0:
        return
    import subprocess
    adb_exe = _c("MUMU_ADB", "") or _c("ADB_EXE", "")
    x2 = max(10, min(950, SWIPE_CX - dx))
    y2 = max(130, min(450, SWIPE_CY - dy))
    subprocess.run(
        [adb_exe, "-s", f"127.0.0.1:{porta}", "shell", "input", "swipe",
         str(SWIPE_CX), str(SWIPE_CY), str(x2), str(y2), str(SWIPE_DUR)],
        capture_output=True, timeout=15
    )
    time.sleep(0.7)


def _swipe_merchant(porta, verso_basso=True):
    import subprocess
    adb_exe = _c("MUMU_ADB", "") or _c("ADB_EXE", "")
    sy = 300
    ey = (300 - MERCHANT_SWIPE_DY) if verso_basso else (300 + MERCHANT_SWIPE_DY)
    ey = max(120, min(440, ey))
    subprocess.run(
        [adb_exe, "-s", f"127.0.0.1:{porta}", "shell", "input", "swipe",
         "480", str(sy), "480", str(ey), str(MERCHANT_SWIPE_DUR)],
        capture_output=True, timeout=15
    )
    time.sleep(0.8)

# ---------------------------------------------------------------------------
# Gestione banner
# ---------------------------------------------------------------------------

def _rileva_banner(cv_img, log):
    s_ap, _, _ = _match(cv_img, "pin_banner_aperto.png", log, roi=ROI_BANNER_PIN)
    s_ch, _, _ = _match(cv_img, "pin_banner_chiuso.png", log, roi=ROI_BANNER_PIN)
    if s_ap >= SOGLIA_BANNER() and s_ap > s_ch:
        return "aperto"
    if s_ch >= SOGLIA_BANNER() and s_ch > s_ap:
        return "chiuso"
    return "sconosciuto"


def _comprimi_banner(porta, log):
    """Collassa il banner eventi. Ritorna stato originale."""
    _, cv_img = _screenshot(porta, log)
    if cv_img is None:
        return "sconosciuto"
    stato = _rileva_banner(cv_img, log)
    if stato == "aperto":
        log(f"[STORE] Banner: collasso → tap ({BANNER_TAP_X},{BANNER_TAP_Y})")
        _tap(porta, BANNER_TAP_X, BANNER_TAP_Y)
        time.sleep(0.5)
        _, cv2_ = _screenshot(porta, log)
        if cv2_ is not None and _rileva_banner(cv2_, log) == "chiuso":
            log("[STORE] Banner collassato ✓")
        else:
            log("[STORE] Banner collasso non confermato — procedo")
    elif stato == "chiuso":
        log("[STORE] Banner già collassato")
    else:
        log("[STORE] Banner sconosciuto — procedo")
    return stato


def _ripristina_banner(porta, stato_orig, log):
    if stato_orig != "aperto":
        return
    log(f"[STORE] Banner: ripristino → tap ({BANNER_TAP_X},{BANNER_TAP_Y})")
    _tap(porta, BANNER_TAP_X, BANNER_TAP_Y)
    time.sleep(0.5)

# ---------------------------------------------------------------------------
# Logica negozio
# ---------------------------------------------------------------------------

def _conta_pulsanti(cv_img, log):
    """Ritorna lista (cy, cx, score, pin_file) dei pulsanti acquistabili."""
    candidati = []
    for pin_file in PIN_ACQUISTO:
        for s, cx, cy in _match_tutti(cv_img, pin_file, SOGLIA_ACQUISTO(),
                                      log, roi=ROI_NEGOZIO, nms_dist=NMS_DIST):
            candidati.append((cy, cx, s, pin_file))
    candidati.sort()
    return candidati


def _acquista_pagina(porta, pagina_n, log):
    """Acquista tutti i pulsanti gialli visibili. Ritorna n acquisti."""
    _, cv_img = _screenshot(porta, log)
    if cv_img is None:
        log(f"[STORE] Pagina {pagina_n}: screenshot fallito")
        return 0

    candidati = _conta_pulsanti(cv_img, log)
    log(f"[STORE] Pagina {pagina_n}: {len(candidati)} pulsanti trovati")

    if not candidati:
        return 0

    for i, (cy, cx, s, pin_file) in enumerate(candidati):
        log(f"[STORE] Acquisto #{i}: tap ({cx},{cy}) [{pin_file} {s:.3f}]")
        _tap(porta, cx, cy)

    # Verifica finale: nessun pulsante rimasto
    time.sleep(0.5)
    _, cv_after = _screenshot(porta, log)
    if cv_after is not None:
        rimasti = _conta_pulsanti(cv_after, log)
        if rimasti:
            log(f"[STORE] ATTENZIONE: {len(rimasti)} pulsanti ancora presenti dopo acquisto")
        else:
            log(f"[STORE] Pagina {pagina_n}: tutti acquistati ({len(candidati)}/{len(candidati)}) ✓")

    return len(candidati)


def _gestisci_negozio(porta, nome, cx_store, cy_store, log):
    """
    Flusso completo negozio dopo aver trovato lo store.
    Ritorna dict con esito, acquistati, refresh.
    """
    log(f"[STORE] Tap edificio ({cx_store},{cy_store})")

    # Controlla mercante visibile sull'edificio prima del tap
    _, cv_pre = _screenshot(porta, log)
    mercante_diretto = False
    if cv_pre is not None:
        s_merc, _, _ = _match(cv_pre, "pin_mercante.png", log, roi=ROI_NEGOZIO)
        log(f"[STORE] Pre-tap mercante: score={s_merc:.3f} (soglia={SOGLIA_MERCANTE():.2f})")
        if s_merc >= SOGLIA_MERCANTE():
            mercante_diretto = True
            log(f"[STORE] Mercante visibile — apertura diretta (skip carrello)")

    _tap(porta, cx_store, cy_store)

    _, cv_img = _screenshot(porta, log)
    if cv_img is None:
        return {"esito": "errore_screenshot", "acquistati": 0, "refresh": False}

    if not mercante_diretto:
        # Flusso standard: verifica label → tap carrello
        s_label, _, _ = _match(cv_img, "pin_store_attivo.png", log)
        log(f"[STORE] Label: score={s_label:.3f} (soglia={SOGLIA_STORE_ATTIVO():.2f})")
        if s_label < SOGLIA_STORE_ATTIVO():
            log("[STORE] Label non trovata — abort")
            _back(porta)
            return {"esito": "label_non_trovata", "acquistati": 0, "refresh": False}

        s_carr, cx_carr, cy_carr = _match(cv_img, "pin_carrello.png", log)
        log(f"[STORE] Carrello: score={s_carr:.3f} (soglia={SOGLIA_CARRELLO():.2f})")
        if s_carr < SOGLIA_CARRELLO():
            log("[STORE] Carrello non trovato — abort")
            _back(porta)
            return {"esito": "carrello_non_trovato", "acquistati": 0, "refresh": False}

        log(f"[STORE] Tap carrello ({cx_carr},{cy_carr})")
        _tap(porta, cx_carr, cy_carr)
        time.sleep(1.0)

    # Verifica merchant aperto
    _, cv_img = _screenshot(porta, log)
    s_merch, _, _ = _match(cv_img, "pin_merchant.png", log) if cv_img is not None else (-1.0, -1, -1)
    log(f"[STORE] Merchant aperto: score={s_merch:.3f} (soglia={SOGLIA_MERCHANT():.2f})")
    if cv_img is None or s_merch < SOGLIA_MERCHANT():
        log("[STORE] Merchant non confermato — abort")
        _back(porta)
        return {"esito": "merchant_non_aperto", "acquistati": 0, "refresh": False}

    totale    = 0
    refreshed = False

    for ciclo in range(2):
        if ciclo == 1 and not refreshed:
            break

        log(f"[STORE] Ciclo acquisti {ciclo + 1}")

        for pagina in range(MAX_PAGINE()):
            totale += _acquista_pagina(porta, pagina_n=ciclo * 10 + pagina + 1, log=log)
            if pagina < MAX_PAGINE() - 1:
                log(f"[STORE] Swipe ↓ pagina {pagina + 1} → {pagina + 2}")
                _swipe_merchant(porta, verso_basso=True)

        # Torna in cima
        for _ in range(MAX_PAGINE() - 1):
            _swipe_merchant(porta, verso_basso=False)
        time.sleep(0.5)

        if ciclo == 1:
            break

        # Controlla refresh
        _, cv_img = _screenshot(porta, log)
        if cv_img is None:
            break

        s_noref, _, _ = _match(cv_img, "pin_no_refresh.png", log, roi=ROI_FOOTER)
        if s_noref >= SOGLIA_NO_REFRESH():
            log(f"[STORE] Refresh a pagamento (score={s_noref:.3f}) — skip")
            break

        s_free, cx_free, cy_free = _match(cv_img, "pin_free_refresh.png", log, roi=ROI_FOOTER)
        log(f"[STORE] Free Refresh: score={s_free:.3f} (soglia={SOGLIA_FREE_REFRESH():.2f})")
        if s_free < SOGLIA_FREE_REFRESH():
            log("[STORE] Free Refresh non disponibile")
            break

        log(f"[STORE] Tap Free Refresh ({cx_free},{cy_free})")
        _tap(porta, cx_free, cy_free)
        time.sleep(1.5)
        refreshed = True
        log("[STORE] Free Refresh eseguito ✓")

    # Chiudi negozio
    log("[STORE] Chiusura → BACK")
    _back(porta)
    time.sleep(0.5)

    log(f"[STORE] Completato — acquistati: {totale}  refresh: {refreshed}")
    return {"esito": "completato", "acquistati": totale, "refresh": refreshed}

# ---------------------------------------------------------------------------
# Entry point principale
# ---------------------------------------------------------------------------

def run_store(porta: str, nome: str, logger=None) -> dict:
    """
    Esegue il flusso completo store per una istanza.

    Parametri:
        logger: callable(nome, msg) — stesso pattern di tutti i moduli V5.
    Ritorna dict: esito, acquistati, refresh, errore.
    """
    # Closure log a 1 arg — compatibile con tutte le funzioni interne
    def log(msg):
        if logger:
            logger(nome, msg)

    # vai_in_home riceve logger raw (nome, msg) — corretto
    if not _stato.vai_in_home(porta, nome, logger):
        log("[STORE] Non in home — abort")
        return {"esito": "non_in_home", "acquistati": 0, "refresh": False, "errore": "non_in_home"}

    stato_banner = _comprimi_banner(porta, log)
    banner_chiuso = (stato_banner in ("aperto", "chiuso"))
    roi_corrente  = ROI_HOME_BANNER_CHIUSO if banner_chiuso else ROI_HOME_BANNER_APERTO

    trovato    = False
    cx_fin     = cy_fin = -1
    best_score = -1.0
    esito_neg  = {"esito": "non_tentato", "acquistati": 0, "refresh": False}

    log(f"[STORE] Scan griglia {len(GRIGLIA)} posizioni  passo={PASSO_SCAN()}px")

    for n, (dx, dy) in enumerate(GRIGLIA):
        if dx != 0 or dy != 0:
            _swipe_mappa(porta, dx, dy)

        _, cv_img = _screenshot(porta, log)
        if cv_img is None:
            log(f"[STORE] passo {n:02d} → screenshot None — skip")
            continue

        score, cx, cy = _match(cv_img, "pin_store.png", log, roi=roi_corrente)
        ok = score >= SOGLIA_STORE()
        log(f"[STORE] passo {n:02d} → score={score:.3f} ({cx},{cy})"
            + ("  *** TROVATO ***" if ok else ""))

        if score > best_score:
            best_score = score

        if ok:
            trovato    = True
            cx_fin, cy_fin = cx, cy
            break

    if trovato:
        # Negozio mentre la camera è ancora sulla posizione corretta
        esito_neg = _gestisci_negozio(porta, nome, cx_fin, cy_fin, log)
    else:
        log(f"[STORE] Store NON trovato dopo {len(GRIGLIA)} posizioni"
            f" (best score={best_score:.3f})")

    # Torna in home prima di ripristinare il banner:
    # dopo la scan la camera è spostata e (345,63) non colpisce il banner.
    _stato.vai_in_home(porta, nome, logger)

    # Ripristina banner
    _ripristina_banner(porta, stato_banner, log)

    # Verifica home finale — logger raw
    if not _stato.vai_in_home(porta, nome, logger):
        log("[STORE] WARN: non in home dopo store — tentativo BACK")
        _back(porta)

    return {
        "esito":     esito_neg["esito"] if trovato else "store_non_trovato",
        "acquistati": esito_neg["acquistati"],
        "refresh":   esito_neg["refresh"],
        "errore":    None if trovato else "store_non_trovato",
    }

# ---------------------------------------------------------------------------
# Funzione guarded per daily_tasks.py
# ---------------------------------------------------------------------------

def esegui_store_guarded(porta: str, nome: str, logger=None) -> bool:
    """
    Esegue il task Store se abilitato e schedulato.
    Chiamare da daily_tasks.py wrappato in _run_guarded.
    Schedulazione: SCHEDULE_ORE_STORE (default 4h), chiave "store".
    """
    def log(msg):
        if logger:
            logger(nome, msg)

    if not getattr(config, "STORE_ABILITATO", False):
        log("[STORE] Disabilitato — skip")
        return True

    if not scheduler.deve_eseguire(nome, porta, "store", logger):
        return True  # già eseguito nelle ultime 4h

    # Passa logger raw — run_store costruisce internamente la closure log(msg)
    res = run_store(porta=porta, nome=nome, logger=logger)

    # Registra sempre — anche acquistati=0 significa "visitato, niente da comprare"
    scheduler.registra_esecuzione(nome, porta, "store")
    log(f"[STORE] acquistati={res['acquistati']}  refresh={res['refresh']}"
        + (f"  errore={res['errore']}" if res.get("errore") else ""))

    return res.get("errore") is None
