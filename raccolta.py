# ==============================================================================
# DOOMSDAY BOT V5 - raccolta.py
# ==============================================================================
#
# Refactoring V5.24: raccolta_istanza suddivisa in funzioni di modulo:
#   _esegui_task_periodici()   — messaggi, alleanza, VIP, radar, zaino, arena, rifornimento
#   _leggi_risorse_deposito()  — OCR risorse con retry/backoff
#   _loop_invio_marce()        — loop principale invio squadre
#
# Logica invariata rispetto a V5.16.1.
# ==============================================================================

import hashlib
import time
from PIL import Image as _PIL_Image
import pytesseract
import re as _re
import threading as _threading
import numpy as np

import adb
import stato
import ocr
import debug
import log as _log
import status as _status
import config
import rifornimento
import allocation
from verifica_ui import VerificaUI

# Post-marcia: attesa base (ms->s) con limite
DELAY_POSTMARCIA_BASE = config.DELAY_MARCIA / 1000
MAX_DELAY_POSTMARCIA = 6.0

# ==============================================================================
# Utility
# ==============================================================================

def _md5_file(path: str) -> str:
    """Ritorna md5 del file (stringa esadecimale) o '' se fallisce."""
    try:
        h = hashlib.md5()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _screenshot_cv(porta: str):
    """
    Screenshot in-memoria via pipeline v5.24.
    Ritorna (path, pil_img, cv_img):
      - path    : file su disco (per debug, ocr legacy, stato.rileva_screen)
      - pil_img : PIL.Image (per OCR in-memoria, pixel check)
      - cv_img  : numpy array BGR (per VerificaUI template matching)
    Se exec-out fallisce, cade su adb.screenshot() tradizionale.
    """
    png_bytes = adb.screenshot_bytes(porta)
    if png_bytes:
        pil_img, cv_img = adb.decodifica_screenshot(png_bytes)
        path = adb.salva_screenshot(png_bytes, porta)
        return path, pil_img, cv_img
    # Fallback tradizionale
    path = adb.screenshot(porta) or ''
    return path, None, None


def _reset_stato(porta, nome, screen_path="", squadra=0, tentativo=0, ciclo=0, logger=None):
    def log(msg):
        if logger:
            logger(nome, msg)

    log("Reset stato - BACK rapidi e torno in home")
    if screen_path:
        debug.salva_screen(screen_path, nome, "reset", squadra, tentativo)
    _log.registra_evento(ciclo, nome, "reset", squadra, tentativo)

    stato.back_rapidi_e_stato(porta, logger=logger, nome=nome)
    stato.vai_in_home(porta, nome, logger, conferme=3)
    time.sleep(1.0)


# ==============================================================================
# Blacklist transazionale (RESERVED / COMMITTED)
# ==============================================================================

BLACKLIST_COMMITTED_TTL = 120  # secondi — TTL nodo occupato dopo conferma marcia (stima percorrenza)
BLACKLIST_RESERVED_TTL  = 45   # secondi — TTL prenotazione temporanea durante transazione UI
# Retrocompatibilità: BLACKLIST_TTL era usato come unico TTL. Ora equivale al TTL COMMITTED.
BLACKLIST_TTL        = BLACKLIST_COMMITTED_TTL
BLACKLIST_ATTESA_NODO = BLACKLIST_COMMITTED_TTL  # attesa massima quando il gioco ripropone nodo COMMITTED


def _blacklist_pulisci_e_verifica(blacklist, blacklist_lock, chiave_nodo) -> bool:
    """Pulisce nodi scaduti e verifica se chiave_nodo è in blacklist.

    Formato (V5.12+):
      - chiave: "X_Y" (es. "712_535")
      - valore: dict {"ts": float, "state": "RESERVED"|"COMMITTED"}

    Retrocompatibilità:
      - valore float/int → COMMITTED (ts=valore)

    Ritorna True se chiave_nodo è presente (non scaduto).
    """
    if blacklist is None or blacklist_lock is None or not chiave_nodo:
        return False

    with blacklist_lock:
        ora = time.time()
        scadute = []

        for k, v in list(blacklist.items()):
            if isinstance(v, (int, float)):
                state = "COMMITTED"
                ts = float(v)
            elif isinstance(v, dict):
                state = v.get("state", "COMMITTED")
                ts = float(v.get("ts", 0))
            else:
                scadute.append(k)
                continue

            ttl = BLACKLIST_COMMITTED_TTL if state == "COMMITTED" else BLACKLIST_RESERVED_TTL
            if ora - ts > ttl:
                scadute.append(k)

        for k in scadute:
            blacklist.pop(k, None)

        return chiave_nodo in blacklist


def _blacklist_reserve(blacklist, blacklist_lock, chiave_nodo):
    """Prenota un nodo in stato RESERVED (TTL breve)."""
    if blacklist is None or blacklist_lock is None or not chiave_nodo:
        return
    with blacklist_lock:
        blacklist[chiave_nodo] = {"ts": time.time(), "state": "RESERVED"}


def _blacklist_commit(blacklist, blacklist_lock, chiave_nodo, eta_s=None):
    """Conferma un nodo in stato COMMITTED. Salva eta_s (secondi) se disponibile,
    per permettere attesa dinamica invece del TTL fisso."""
    if blacklist is None or blacklist_lock is None or not chiave_nodo:
        return
    with blacklist_lock:
        blacklist[chiave_nodo] = {"ts": time.time(), "state": "COMMITTED", "eta_s": eta_s}


def _blacklist_get_eta(blacklist, blacklist_lock, chiave_nodo):
    """Ritorna eta_s (secondi) se presente per un nodo COMMITTED, altrimenti None."""
    if blacklist is None or blacklist_lock is None or not chiave_nodo:
        return None
    with blacklist_lock:
        v = blacklist.get(chiave_nodo)
    if isinstance(v, dict):
        return v.get("eta_s")
    return None


def _blacklist_rollback(blacklist, blacklist_lock, chiave_nodo):
    """Rilascia un nodo dalla blacklist (rollback immediato)."""
    if blacklist is None or blacklist_lock is None or not chiave_nodo:
        return
    with blacklist_lock:
        blacklist.pop(chiave_nodo, None)


def _blacklist_get_state(blacklist, blacklist_lock, chiave_nodo):
    """Ritorna lo stato del nodo in blacklist: RESERVED/COMMITTED oppure None."""
    if blacklist is None or blacklist_lock is None or not chiave_nodo:
        return None
    with blacklist_lock:
        v = blacklist.get(chiave_nodo)
    if isinstance(v, dict):
        return v.get("state")
    if isinstance(v, (int, float)):
        return "COMMITTED"
    return None


# ==============================================================================
# Verifica territorio alleanza
#
# Dopo il tap sul nodo il popup mostra la riga "Buff territorio  VEL di raccolta +30%"
# SOLO se il nodo è nel territorio dell'alleanza. Fuori territorio la riga non compare.
#
# Metodo: conta pixel verdi nella zona della riga buff (x:250-420, y:340-370).
# Calibrato su screenshot reali 960x540:
#   IN territorio:   185 pixel verdi
#   FUORI territorio:  0 pixel verdi
# Soglia conservativa: 20 pixel.
# ==============================================================================

TERRITORIO_BUFF_ZONA = (250, 340, 420, 370)  # (x1,y1,x2,y2) — riga "+30%"
TERRITORIO_SOGLIA_PX = 20                     # pixel verdi minimi per IN territorio

# Zona titolo popup nodo (es. "Campo Lv.6") — riga in alto della maschera
# Calibrata su 960x540: il titolo appare centrato, y≈155-180
NODO_TITOLO_ZONA  = (250, 150, 720, 185)
# Livello minimo accettabile — nodi sotto questa soglia vengono scartati
NODO_LIVELLO_MIN  = getattr(config, 'LIVELLO_RACCOLTA', 6)


def _leggi_livello_nodo(screen_path: str) -> int:
    """Legge il livello del nodo dal popup (backward compat — usa file su disco)."""
    try:
        img = _PIL_Image.open(screen_path)
        return _leggi_livello_nodo_da_img(img)
    except Exception:
        return -1


def _leggi_livello_nodo_mem(pil_img) -> int:
    """Variante in-memoria di _leggi_livello_nodo (pipeline v5.24)."""
    if pil_img is None:
        return -1
    return _leggi_livello_nodo_da_img(pil_img)


def _leggi_livello_nodo_da_img(img) -> int:
    """
    Legge il livello del nodo dal titolo del popup (es. "Campo Lv.6" → 6).

    Ritorna:
        int >= 1  se il livello è leggibile
        -1        se OCR fallisce (fail-safe: non scartare per dubbio)
    """
    try:
        crop = img.crop(NODO_TITOLO_ZONA)
        w, h = crop.size
        # Upscale 4x + scala grigi + soglia
        big  = crop.resize((w * 4, h * 4), _PIL_Image.LANCZOS)
        bw   = big.convert("L").point(lambda p: 255 if p > 130 else 0)

        cfg = "--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789. "
        # Usa il lock Tesseract di ocr.py se disponibile
        try:
            lock = ocr._tesseract_lock
        except Exception:
            lock = _threading.Lock()

        with lock:
            testo = pytesseract.image_to_string(bw, config=cfg).strip()

        m = _re.search(r'[Ll][Vv]\.?\s*(\d+)', testo)
        return int(m.group(1)) if m else -1
    except Exception:
        return -1


def _nodo_in_territorio(screen_path: str) -> bool:
    """Ritorna True se il popup mostra il buff territorio (backward compat)."""
    try:
        img = _PIL_Image.open(screen_path)
        return _nodo_in_territorio_da_img(img)
    except Exception:
        return True


def _nodo_in_territorio_mem(pil_img) -> bool:
    """Variante in-memoria di _nodo_in_territorio (pipeline v5.24)."""
    if pil_img is None:
        return True  # fail-safe
    return _nodo_in_territorio_da_img(pil_img)


def _nodo_in_territorio_da_img(img) -> bool:
    """
    Ritorna True se il popup del nodo mostra il buff territorio (riga verde "+30%").
    Ritorna True in caso di errore (fail-safe: non scartare per dubbio).
    """
    try:
        arr  = np.array(img)
        x1, y1, x2, y2 = TERRITORIO_BUFF_ZONA
        zona = arr[y1:y2, x1:x2, :3].astype(int)
        r, g, b = zona[:, :, 0], zona[:, :, 1], zona[:, :, 2]
        verdi = (g > 140) & (g > r * 1.4) & (g > b * 1.3) & ((g - r) > 40)
        return int(verdi.sum()) >= TERRITORIO_SOGLIA_PX
    except Exception:
        return True  # fail-safe: in caso di errore non scartare


# ==============================================================================
# Raccolta: ricerca nodo + OCR coordinate
# ==============================================================================

# Coordinate assolute UI (960x540) per selezione livello nel pannello CERCA.
# Calibrate su screenshot reali — aggiornare se la UI del gioco cambia.
_COORD_LIVELLO = {
    "campo":    {"meno": (294, 295), "piu": (519, 293), "search": (413, 352)},
    "segheria": {"meno": (419, 295), "piu": (644, 293), "search": (538, 352)},
    "acciaio":  {"meno": (556, 295), "piu": (781, 293), "search": (675, 352)},
    "petrolio": {"meno": (701, 295), "piu": (890, 293), "search": (791, 352)},
}


def _cerca_nodo(porta, tipo, coords=None, livello_target=None, nome='', logger=None):
    """Esegue LENTE → selezione tipo × 2 → imposta livello target → CERCA.

    Il popup livello e' sempre ancorato all'icona del tipo selezionato (960x540).
    Offset misurati su screenshot reali:
      — : icona_x - 116  y=295   (pulsante sinistro)
      + : icona_x + 109  y=293   (pulsante destro)
      SEARCH: icona_x + 3  y=352

    Reset: sempre 6 tap su — (porta a Lv.1 da qualsiasi livello, max=7)
    Sale:  (livello_target - 1) tap su +

    Tipi supportati: campo, segheria, acciaio, petrolio.
    coords: UICoords — se None usa config direttamente (retrocompatibilita').
    livello_target: livello nodo da cercare (1-7). Default: config.LIVELLO_RACCOLTA.
    nome, logger: per logging checkpoint (opzionali, retrocompatibili).
    """
    def log(msg):
        if logger:
            logger(nome, msg)

    if coords is not None:
        tap_icona, tap_cerca = coords.per_tipo(tipo)
        _tap_lente = coords.lente
    else:
        _TAP_MAPPA = {
            "campo":    (config.TAP_CAMPO,      config.TAP_CERCA_CAMPO),
            "segheria": (config.TAP_SEGHERIA,   config.TAP_CERCA_SEGHERIA),
            "acciaio":  (config.TAP_ACCIAIERIA, config.TAP_CERCA_ACCIAIERIA),
            "petrolio": (config.TAP_RAFFINERIA, config.TAP_CERCA_RAFFINERIA),
        }
        tap_icona, tap_cerca = _TAP_MAPPA.get(tipo, _TAP_MAPPA["campo"])
        _tap_lente = config.TAP_LENTE

    _v = VerificaUI(porta, nome, logger)

    # ------------------------------------------------------------------
    # PRE tap LENTE: verifica lente_visibile (pin_lente)
    # La lente è visibile SOLO in mappa. Se non visibile dopo retry:
    # - verifica toggle: se in home → vai_in_mappa e riprova
    # - se in overlay → procedi comunque (logga anomalia)
    # ------------------------------------------------------------------
    _, _pre_lente_pil, _pre_lente_screen = _screenshot_cv(porta)
    if not _v.lente_visibile(_pre_lente_screen):
        log("[PRE-LENTE] lente NON visibile — attendo 1s e riverifica")
        time.sleep(1.0)
        _, _pre_lente_pil, _pre_lente_screen = _screenshot_cv(porta)
        if not _v.lente_visibile(_pre_lente_screen):
            _s_lente = stato.rileva_screen_mem(_pre_lente_pil, _pre_lente_screen)
            if _s_lente == 'home':
                log("[PRE-LENTE] siamo in home — eseguo vai_in_mappa")
                if stato.vai_in_mappa(porta, nome, logger):
                    time.sleep(1.0)
                    _, _pre_lente_pil, _pre_lente_screen = _screenshot_cv(porta)
                    if _v.lente_visibile(_pre_lente_screen):
                        log("[PRE-LENTE] lente visibile dopo vai_in_mappa — OK")
                    else:
                        log("[PRE-LENTE] ANOMALIA: lente non visibile anche dopo vai_in_mappa — procedo")
                else:
                    log("[PRE-LENTE] ANOMALIA: vai_in_mappa fallito — procedo comunque")
            else:
                log(f"[PRE-LENTE] ANOMALIA: lente non visibile, toggle='{_s_lente}' — procedo comunque")
        else:
            log("[PRE-LENTE] lente visibile al retry — OK")
    else:
        log("[PRE-LENTE] lente visibile — OK")

    adb.tap(porta, _tap_lente)

    adb.tap(porta, tap_icona)
    adb.tap(porta, tap_icona)
    time.sleep(1.2)  # attesa apertura popup livello

    if not _v.tipo_selezionato(tipo):
        log(f"[PRE-SEARCH] tipo '{tipo}' NON selezionato — retry doppio tap")
        adb.tap(porta, tap_icona)
        time.sleep(1.5)
        if not _v.tipo_selezionato(tipo):
            # Pannello lente non ancora inizializzato (tipico al primo accesso mappa).
            # Chiude il pannello con BACK, attende rendering, riapre lente e riseleziona.
            log(f"[PRE-SEARCH] tipo '{tipo}' ancora non selezionato — reset pannello e retry")
            adb.keyevent(porta, "KEYCODE_BACK")
            time.sleep(2.0)
            adb.tap(porta, _tap_lente)
            time.sleep(0.8)
            adb.tap(porta, tap_icona)
            adb.tap(porta, tap_icona)
            time.sleep(1.5)
            if not _v.tipo_selezionato(tipo):
                log(f"[PRE-SEARCH] ANOMALIA: tipo '{tipo}' non selezionato dopo reset pannello — procedo comunque")
            else:
                log(f"[PRE-SEARCH] tipo '{tipo}' selezionato dopo reset pannello — OK")
        else:
            log(f"[PRE-SEARCH] tipo '{tipo}' selezionato al retry — OK")
    else:
        log(f"[PRE-SEARCH] tipo '{tipo}' selezionato — OK")

    coords_lv  = _COORD_LIVELLO.get(tipo, _COORD_LIVELLO["campo"])
    tap_meno   = coords_lv["meno"]
    tap_piu    = coords_lv["piu"]
    tap_search = coords_lv["search"]

    _lv = int(livello_target) if livello_target and int(livello_target) > 0 else config.LIVELLO_RACCOLTA
    _lv = max(1, min(7, _lv))

    try:
        _log.logger("CERCA", f"[LV] {tipo} Lv.{_lv} reset -6@{tap_meno} poi +{_lv-1}@{tap_piu}")
    except Exception:
        pass

    for _ in range(6):
        adb.tap(porta, tap_meno, delay_ms=120)
    for _ in range(_lv - 1):
        adb.tap(porta, tap_piu, delay_ms=150)

    adb.tap(porta, tap_search, delay_ms=config.DELAY_CERCA)


def _leggi_coord_nodo(porta, nome, tipo, squadra, tentativo, retry_n, logger):
    """Tap lente coord + screenshot + OCR coordinate. Ritorna (chiave, cx, cy, screen)."""
    def log(msg):
        if logger:
            logger(nome, msg)

    _v_coord = VerificaUI(porta, nome, logger)

    time.sleep(1.5)

    # PRE tap LENTE_COORD: tap e poi verifica pin_enter (popup coordinate aperto)
    # Se non si apre al primo tap → retry 1x con attesa extra
    adb.tap(porta, config.TAP_LENTE_COORD, delay_ms=1300)
    _pre_enter_screen = _screenshot_cv(porta)[2]
    if not _v_coord.enter_coordinates_visibile(_pre_enter_screen):
        log("[PRE-COORD] pin_enter NON visibile dopo tap — retry tap lente coord")
        adb.tap(porta, config.TAP_LENTE_COORD, delay_ms=0)
        time.sleep(1.3)
        _pre_enter_screen = _screenshot_cv(porta)[2]
        if not _v_coord.enter_coordinates_visibile(_pre_enter_screen):
            log("[PRE-COORD] ANOMALIA: pin_enter ancora non visibile — OCR potrebbe fallire")
        else:
            log("[PRE-COORD] pin_enter visibile al retry — OK")
    else:
        log("[PRE-COORD] pin_enter visibile — OK")

    screen_nodo, _pil_nodo, _ = _screenshot_cv(porta)
    debug.salva_screen(screen_nodo, nome, f"fase3_popup_{tipo}", squadra, tentativo, f"r{retry_n}")
    debug.salva_crop_coord(screen_nodo, nome, "fase3_ocr_coord", squadra, tentativo, f"r{retry_n}")

    coord = ocr.leggi_coordinate_nodo_mem(_pil_nodo, porta=porta)
    log(f"[FASE3] OCR coordinate: {coord} (retry {retry_n})")

    if coord is None:
        return None, None, None, screen_nodo

    cx, cy = coord
    return f"{cx}_{cy}", cx, cy, screen_nodo


# ==============================================================================
# Conferma contatore post-MARCIA (robusto)
# ==============================================================================

def _leggi_attive_con_retry(porta, nome, logger=None, n_letture=3, retry=3, sleep_s=1.5, n_squadre=-1):
    """Legge attive con retry quando OCR non disponibile (-1). Ritorna attive o -1.

    NON invia BACK durante i retry: se il bot è già in mappa un BACK lo porterebbe
    in home rendendo il contatore non visibile. Aspetta che la UI si stabilizzi
    dopo la transizione post-marcia, verificando lo stato prima di ogni lettura.
    """
    def log(msg):
        if logger:
            logger(nome, msg)

    for i in range(retry):
        s_ora, _ = stato.rileva(porta)
        if s_ora not in ("mappa",):
            log(f"OCR contatore: stato '{s_ora}' (non mappa) - attendo {sleep_s:.1f}s stabilizzazione")
            time.sleep(sleep_s)
            continue

        attive, _, _ = stato.conta_squadre(porta, n_letture=n_letture, n_squadre=n_squadre)
        if attive != -1:
            return attive
        log(f"OCR contatore non disponibile (tentativo {i+1}/{retry}) - attendo {sleep_s:.1f}s")
        time.sleep(sleep_s)
    return -1


# ==============================================================================
# Sequenza UI: RACCOGLI → SQUADRA → (truppe) → MARCIA
# ==============================================================================

def _esegui_marcia(porta, nome, n_truppe, squadra, tentativo, logger=None, coords=None):
    """Esegue la sequenza UI: RACCOGLI → SQUADRA → (truppe) → MARCIA.

    Ritorna (ok, eta_s):
      - ok:    True se la marcia è partita (schermata cambiata dopo MARCIA)
      - eta_s: ETA percorrenza in secondi letto dalla maschera pre-marcia, o None
    """
    def log(msg):
        if logger:
            logger(nome, msg)

    eta_s = None

    _raccogli    = coords.raccogli    if coords else config.TAP_RACCOGLI
    _squadra     = coords.squadra     if coords else config.TAP_SQUADRA
    _marcia      = coords.marcia      if coords else config.TAP_MARCIA
    _cancella    = coords.cancella    if coords else config.TAP_CANCELLA
    _campo_testo = coords.campo_testo if coords else config.TAP_CAMPO_TESTO
    _ok_tastiera = coords.ok_tastiera if coords else config.TAP_OK_TASTIERA

    _v = VerificaUI(porta, nome, logger)

    # ------------------------------------------------------------------
    # 1) PRE RACCOGLI — pin_gather deve essere visibile
    # ------------------------------------------------------------------
    _s_pre_raccogli = _screenshot_cv(porta)[2]
    if not _v.gather_visibile(_s_pre_raccogli):
        log("[PRE-RACCOGLI] ANOMALIA: GATHER non visibile prima di tap RACCOGLI")
    else:
        log("[PRE-RACCOGLI] GATHER visibile — OK")

    adb.tap(porta, _raccogli)
    time.sleep(0.5)

    # ------------------------------------------------------------------
    # 2) PRE SQUADRA — dopo RACCOGLI la maschera squadra deve aprirsi.
    # ------------------------------------------------------------------
    adb.tap(porta, _squadra)
    time.sleep(1.4)

    screen_pre, _pil_screen_pre, _cv_screen_pre = _screenshot_cv(porta)
    debug.salva_screen(screen_pre, nome, "pre_marcia", squadra, tentativo)

    if not _v.maschera_invio_aperta(_cv_screen_pre):
        log("[PRE-SQUADRA] maschera invio NON aperta dopo tap SQUADRA — retry")
        adb.tap(porta, _squadra)
        time.sleep(1.8)
        screen_pre, _pil_screen_pre, _cv_screen_pre = _screenshot_cv(porta)
        debug.salva_screen(screen_pre, nome, "pre_marcia_retry", squadra, tentativo)
        if not _v.maschera_invio_aperta(_cv_screen_pre):
            log("[PRE-SQUADRA] ANOMALIA: maschera ancora non aperta — invio FALLITO")
            return False, None
        else:
            log("[PRE-SQUADRA] maschera aperta al retry — OK")
    else:
        log("[PRE-SQUADRA] maschera invio aperta — OK")

    # Lettura ETA marcia dalla maschera
    try:
        eta_s, raw = ocr.leggi_eta_marcia_mem(_pil_screen_pre)
    except Exception:
        eta_s, raw = None, ""

    if eta_s is not None and eta_s > 600:
        log(f"ETA marcia: {eta_s}s — valore anomalo (misread OCR), ignorato")
        eta_s = None

    if eta_s is not None:
        log(f"ETA marcia: {eta_s}s ({eta_s//60}m{eta_s%60:02d}s)")
    elif tentativo == 1:
        log("ETA marcia non leggibile")
        if raw:
            log(f"ETA OCR raw: '{raw[:40]}'")

    # ------------------------------------------------------------------
    # 3) Imposta truppe se richiesto
    # ------------------------------------------------------------------
    if n_truppe and n_truppe > 0:
        adb.tap(porta, _cancella)
        time.sleep(0.4)
        adb.tap(porta, _campo_testo)
        time.sleep(0.4)
        adb.keyevent(porta, "KEYCODE_CTRL_A")
        time.sleep(0.15)
        adb.keyevent(porta, "KEYCODE_DEL")
        time.sleep(0.15)
        adb.input_text(porta, str(n_truppe))
        time.sleep(0.25)
        adb.tap(porta, _ok_tastiera)
        time.sleep(0.25)

    # ------------------------------------------------------------------
    # 4) PRE MARCIA — verifica maschera ancora aperta prima del tap MARCIA.
    # ------------------------------------------------------------------
    screen_pre_marcia, _pil_screen_pre_marcia, _cv_screen_pre_marcia = _screenshot_cv(porta)
    if not _v.maschera_invio_aperta(_cv_screen_pre_marcia):
        log("[PRE-MARCIA] ANOMALIA: maschera chiusa prima del tap MARCIA — invio FALLITO")
        return False, eta_s
    else:
        log("[PRE-MARCIA] maschera aperta — tap MARCIA")

    adb.tap(porta, _marcia)
    time.sleep(0.8)

    # ------------------------------------------------------------------
    # 5) POST MARCIA — verifica che la maschera si sia chiusa (marcia partita).
    # ------------------------------------------------------------------
    screen_post, _pil_screen_post, _cv_screen_post = _screenshot_cv(porta)
    if _v.maschera_invio_ancora_aperta(_cv_screen_post):
        log("[POST-MARCIA] ANOMALIA: maschera ancora visibile dopo MARCIA — retry tap MARCIA")
        adb.tap(porta, _marcia)
        time.sleep(1.0)
        screen_post, _pil_screen_post, _cv_screen_post = _screenshot_cv(porta)
        if _v.maschera_invio_ancora_aperta(_cv_screen_post):
            log("[POST-MARCIA] ANOMALIA: maschera ancora aperta dopo retry — invio FALLITO")
            return False, eta_s
        else:
            log("[POST-MARCIA] maschera chiusa al retry — OK")

    return True, eta_s


# ==============================================================================
# Invio squadra: cerca nodo + gestisci blacklist + invio
# ==============================================================================

def _tap_invia_squadra(porta, tipo, n_truppe, nome, squadra, tentativo, ciclo,
                       logger=None, blacklist=None, blacklist_lock=None,
                       coords=None, cooldown_map=None, livello_target=None):
    """Ritorna (chiave_nodo, nodo_bloccato, marcia_tentata, eta_s, fuori_territorio, cooldown_s)."""
    def log(msg):
        if logger:
            logger(nome, msg)

    _nodo_coord = coords.nodo if coords else config.TAP_NODO

    _cerca_nodo(porta, tipo, coords, livello_target=livello_target, nome=nome, logger=logger)

    chiave_nodo, cx, cy, screen_nodo = _leggi_coord_nodo(porta, nome, tipo, squadra, tentativo, 1, logger)

    if chiave_nodo is None:
        log("Coordinate nodo non leggibili - procedo senza blacklist")
        debug.salva_screen(screen_nodo, nome, "fase3_ocr_coord_fail", squadra, tentativo, "r1")
        adb.keyevent(porta, "KEYCODE_BACK")
        time.sleep(0.4)

        # [CHECK-2] dopo KEYCODE_BACK nel path OCR=None: verifica dove siamo
        _c2_screen, _, _cv_c2 = _screenshot_cv(porta)
        _c2_stato = stato.rileva_screen(_c2_screen) if _c2_screen else 'sconosciuto'
        log(f"[CHECK-2] post-BACK (path OCR=None) toggle='{_c2_stato}' (atteso: mappa)")
        if _c2_stato == 'home':
            log("[CHECK-2] ANOMALIA: siamo in home dopo BACK — eseguo vai_in_mappa prima del tap nodo")
            if not stato.vai_in_mappa(porta, nome, logger):
                log("[CHECK-2] vai_in_mappa fallito — abbandono")
                return None, False, False, None, False, 0
            time.sleep(0.5)
        elif _c2_stato not in ('mappa', 'sconosciuto'):
            log(f"[CHECK-2] stato '{_c2_stato}' inatteso — tento BACK aggiuntivo")
            adb.keyevent(porta, "KEYCODE_BACK")
            time.sleep(0.5)

        adb.tap(porta, _nodo_coord)
        time.sleep(0.8)

        # [CHECK-3] path OCR=None: verifica gather_visibile dopo tap nodo
        _c3_screen = _screenshot_cv(porta)[2]
        _v_ocrnone = VerificaUI(porta, nome, logger)
        if not _v_ocrnone.gather_visibile(_c3_screen):
            log("[CHECK-3] GATHER non visibile nel path OCR=None — retry tap nodo")
            adb.tap(porta, _nodo_coord)
            time.sleep(1.0)
            _c3_screen2 = _screenshot_cv(porta)[2]
            if not _v_ocrnone.gather_visibile(_c3_screen2):
                log("[CHECK-3] GATHER ancora non visibile — abbandono path OCR=None")
                adb.keyevent(porta, "KEYCODE_BACK")
                time.sleep(0.4)
                return None, False, False, None, False, 0
            log("[CHECK-3] GATHER visibile al retry — procedo")
        else:
            log("[CHECK-3] GATHER visibile — popup nodo aperto correttamente")

        ok, eta_s = _esegui_marcia(porta, nome, n_truppe, squadra, tentativo, logger, coords)

        # [CHECK-4] dopo _esegui_marcia nel path OCR=None: diagnostica toggle se fallita
        if not ok:
            _c4_screen, _, _ = _screenshot_cv(porta)
            _c4_stato = stato.rileva_screen(_c4_screen) if _c4_screen else 'sconosciuto'
            log(f"[CHECK-4] marcia fallita — toggle='{_c4_stato}'")

        return None, False, ok, eta_s, False, 0

    if _blacklist_pulisci_e_verifica(blacklist, blacklist_lock, chiave_nodo):
        log(f"Nodo ({cx},{cy}) in blacklist - riprovo CERCA")
        debug.salva_screen(screen_nodo, nome, "fase3_blacklist", squadra, tentativo, f"{cx}_{cy}_r1")

        chiave_primo = chiave_nodo
        _cerca_nodo(porta, tipo, coords, livello_target=livello_target, nome=nome, logger=logger)
        chiave_nodo, cx, cy, screen_nodo = _leggi_coord_nodo(porta, nome, tipo, squadra, tentativo, 2, logger)

        if chiave_nodo == chiave_primo or chiave_nodo is None:
            # Il gioco continua a proporre lo stesso nodo occupato.
            # Mette il tipo in cooldown e prosegue con altri tipi.
            attesa = 3
            if _blacklist_get_state(blacklist, blacklist_lock, chiave_primo) == "COMMITTED":
                eta_prev = _blacklist_get_eta(blacklist, blacklist_lock, chiave_primo)
                if isinstance(eta_prev, (int, float)) and eta_prev > 0:
                    marg    = getattr(config, "OCR_MARCIA_ETA_MARGINE_S", 5)
                    att_min = getattr(config, "OCR_MARCIA_ETA_MIN_S", 8)
                    attesa  = int(min(BLACKLIST_ATTESA_NODO, max(att_min, eta_prev + marg)))
                    log(f"Cooldown tipo '{tipo}': {attesa}s (ETA={int(eta_prev)}s + margine={int(marg)}s)")
                else:
                    attesa = BLACKLIST_ATTESA_NODO
                    log(f"Cooldown tipo '{tipo}': {attesa}s (ETA nodo non disponibile - TTL fisso)")
            if isinstance(cooldown_map, dict):
                cooldown_map[tipo] = time.time() + attesa
            adb.keyevent(porta, "KEYCODE_BACK")
            time.sleep(0.4)
            return None, False, False, None, False, attesa

        if chiave_nodo and _blacklist_pulisci_e_verifica(blacklist, blacklist_lock, chiave_nodo):
            log(f"Anche il nuovo nodo ({cx},{cy}) è in blacklist - abbandono")
            adb.keyevent(porta, "KEYCODE_BACK")
            time.sleep(0.4)
            return None, True, False, None, False, 0

    log(f"[FASE4] Nodo ({cx},{cy}) libero - tap nodo")
    adb.tap(porta, _nodo_coord)
    time.sleep(0.7)

    screen_popup, _pil_screen_popup, _cv_screen_popup = _screenshot_cv(porta)
    debug.salva_screen(screen_popup, nome, "fase4_popup_raccogli", squadra, tentativo, f"{cx}_{cy}")

    # Verifica che il popup nodo si sia aperto (GATHER visibile)
    _v_nodo = VerificaUI(porta, nome, logger)
    if not _v_nodo.gather_visibile(_cv_screen_popup):
        log(f"Nodo ({cx},{cy}) — GATHER non visibile dopo tap (popup non aperto)")
        adb.tap(porta, _nodo_coord)
        time.sleep(1.0)
        screen_popup, _pil_screen_popup, _cv_screen_popup = _screenshot_cv(porta)
        if not _v_nodo.gather_visibile(_cv_screen_popup):
            log(f"Nodo ({cx},{cy}) — GATHER ancora non visibile — rollback")
            adb.keyevent(porta, "KEYCODE_BACK")
            time.sleep(0.4)
            _blacklist_rollback(blacklist, blacklist_lock, chiave_nodo)
            return chiave_nodo, False, False, None, False, 0

    # --- Controllo livello nodo ---
    if screen_popup:
        _livello = _leggi_livello_nodo_mem(_pil_screen_popup)
        if _livello != -1 and _livello < NODO_LIVELLO_MIN:
            log(f"Nodo ({cx},{cy}) livello {_livello} < {NODO_LIVELLO_MIN} — scarto")
            debug.salva_screen(screen_popup, nome, "fase4_livello_basso", squadra, tentativo, f"{cx}_{cy}_lv{_livello}")
            adb.keyevent(porta, "KEYCODE_BACK")
            time.sleep(0.4)
            _blacklist_commit(blacklist, blacklist_lock, chiave_nodo, eta_s=None)
            log(f"Nodo ({cx},{cy}) aggiunto a blacklist (livello basso Lv.{_livello})")
            return chiave_nodo, True, False, None, True, 0
        elif _livello != -1:
            log(f"Nodo ({cx},{cy}) livello Lv.{_livello} ✓")

    if _pil_screen_popup is not None and not _nodo_in_territorio_mem(_pil_screen_popup):
        log(f"Nodo ({cx},{cy}) FUORI territorio alleanza — scarto e cerco altro")
        debug.salva_screen(screen_popup, nome, "fase4_fuori_territorio", squadra, tentativo, f"{cx}_{cy}")
        adb.keyevent(porta, "KEYCODE_BACK")
        time.sleep(0.4)
        _blacklist_commit(blacklist, blacklist_lock, chiave_nodo, eta_s=None)
        log(f"Nodo ({cx},{cy}) aggiunto a blacklist (fuori territorio)")
        return chiave_nodo, True, False, None, True, 0

    _blacklist_reserve(blacklist, blacklist_lock, chiave_nodo)
    log(f"Nodo ({cx},{cy}) prenotato in blacklist (RESERVED)")

    # PRE _esegui_marcia: verifica GATHER visibile prima di procedere
    _v_pre_marcia = VerificaUI(porta, nome, logger)
    _pre_marcia_screen = _screenshot_cv(porta)[2]
    if not _v_pre_marcia.gather_visibile(_pre_marcia_screen):
        log(f"[PRE-MARCIA] GATHER non visibile prima di _esegui_marcia — retry tap nodo")
        adb.tap(porta, _nodo_coord)
        time.sleep(1.0)
        _pre_marcia_screen = _screenshot_cv(porta)[2]
        if not _v_pre_marcia.gather_visibile(_pre_marcia_screen):
            log(f"[PRE-MARCIA] ANOMALIA: GATHER ancora non visibile — rollback nodo")
            adb.keyevent(porta, "KEYCODE_BACK")
            time.sleep(0.4)
            _blacklist_rollback(blacklist, blacklist_lock, chiave_nodo)
            return chiave_nodo, False, False, None, False, 0
        else:
            log(f"[PRE-MARCIA] GATHER visibile al retry — OK")
    else:
        log(f"[PRE-MARCIA] GATHER visibile — OK")

    for t in range(1, config.MAX_TENTATIVI_RACCOLTA + 1):
        ok, eta_s = _esegui_marcia(porta, nome, n_truppe, squadra, t, logger, coords)
        if ok:
            return chiave_nodo, False, True, eta_s, False, 0

        log(f"MARCIA fallita (tentativo {t}/{config.MAX_TENTATIVI_RACCOLTA}) - recovery UI")

        _c4_screen, _, _ = _screenshot_cv(porta)
        _c4_stato = stato.rileva_screen(_c4_screen) if _c4_screen else 'sconosciuto'
        log(f"[CHECK-4] marcia fallita (t={t}) — toggle='{_c4_stato}'")

        # Recovery: i BACK chiudono il popup nodo — serve ritappare il nodo
        # prima del prossimo tentativo per riaprirlo.
        s_rec, _ = stato.back_rapidi_e_stato(porta, n=4, logger=logger, nome=nome)
        if s_rec == "home":
            log("Recovery: in home - riporto in mappa prima del prossimo tentativo")
            if not stato.vai_in_mappa(porta, nome, logger):
                log("Recovery: impossibile tornare in mappa - abbandono")
                return chiave_nodo, False, False, None, False, 0
        elif s_rec not in ("mappa", "home"):
            log(f"Recovery: stato '{s_rec}' - reset completo")
            _reset_stato(porta, nome, "", squadra, t, 0, logger)

        # Solo se ci sono altri tentativi: riapre il popup nodo (chiuso dai BACK)
        if t < config.MAX_TENTATIVI_RACCOLTA:
            log(f"[RECOVERY] retry {t+1}: riapro popup nodo ({cx},{cy})")
            adb.tap(porta, _nodo_coord)
            time.sleep(1.0)
            _rec_cv = _screenshot_cv(porta)[2]
            _v_rec = VerificaUI(porta, nome, logger)
            if not _v_rec.gather_visibile(_rec_cv):
                log(f"[RECOVERY] GATHER non visibile dopo retry tap nodo — abbandono")
                _blacklist_rollback(blacklist, blacklist_lock, chiave_nodo)
                return chiave_nodo, False, False, None, False, 0
            log(f"[RECOVERY] GATHER visibile — popup riaperto OK")

    return chiave_nodo, False, False, None, False, 0


# ==============================================================================
# Task periodici — estratto da raccolta_istanza
# ==============================================================================

def _esegui_task_periodici(porta, nome, logger, coords, ciclo, ist,
                           ensure_home_fn, run_guarded_fn):
    """Esegue in sequenza: messaggi, alleanza, VIP, radar, zaino, arena, rifornimento.

    Parametri:
        ensure_home_fn  — callable(context) -> bool   (da raccolta_istanza)
        run_guarded_fn  — callable(label, fn) -> Any  (da raccolta_istanza)
    """
    def log(msg):
        if logger:
            logger(nome, msg)

    import daily_tasks as _daily

    # Boost Gathering Speed — ogni ciclo, prima di tutto il resto
    # Nessuna schedulazione, nessuno stato persistente.
    # Non bloccante: un errore non interrompe il resto del ciclo.
    import boost as _boost
    try:
        esito_boost = _boost.esegui_boost(porta, nome, logger)
        log(f"Boost: {esito_boost}")
    except Exception as _e_boost:
        log(f"Boost: errore non bloccante — {_e_boost}")

    if getattr(config, "STORE_ABILITATO", False):
        run_guarded_fn("Store", lambda: _daily.esegui_store_guarded(porta, nome, logger))
    else:
        log("Store disabilitato (STORE_ABILITATO=False) - skip")

    import messaggi as _msg
    if getattr(config, "MESSAGGI_ABILITATI", True):
        run_guarded_fn("Messaggi", lambda: _msg.raccolta_messaggi(porta, nome, logger))
    else:
        log("Messaggi disabilitati (MESSAGGI_ABILITATI=False) - skip")

    import alleanza as _all
    if getattr(config, "ALLEANZA_ABILITATA", True):
        run_guarded_fn("Alleanza", lambda: _all.raccolta_alleanza(porta, nome, logger, ist=ist))
    else:
        log("Alleanza disabilitata (ALLEANZA_ABILITATA=False) - skip")

    run_guarded_fn("VIP", lambda: _daily.esegui_vip_guarded(porta, nome, logger))
    if getattr(config, "DAILY_RADAR_ABILITATO", True):
        run_guarded_fn("Radar", lambda: _daily.esegui_radar_guarded(porta, nome, logger, coords))
    else:
        log("Radar disabilitato (DAILY_RADAR_ABILITATO=False) - skip")

    import zaino as _zaino
    if getattr(config, "ZAINO_ABILITATO", True):
        def _do_zaino():
            try:
                return _zaino.esegui_zaino(porta, nome, logger=logger)
            except Exception as _e:
                log(f"Zaino: errore non bloccante: {_e}")
                return None
        esiti_zaino = run_guarded_fn("Zaino", _do_zaino)
        if esiti_zaino and isinstance(esiti_zaino, dict):
            totale_zaino = sum(esiti_zaino.values())
            if totale_zaino > 0:
                log(f"Zaino: scaricato totale {totale_zaino:.2f}M")
    else:
        log("Zaino disabilitato (ZAINO_ABILITATO=False) - skip")

    if getattr(config, "ARENA_OF_GLORY_ABILITATO", False):
        run_guarded_fn("Arena", lambda: _daily.esegui_arena_guarded(porta, nome, logger, coords=coords))
    else:
        log("Arena disabilitata (ARENA_OF_GLORY_ABILITATO=False) - skip")

    if getattr(config, "ARENA_MERCATO_ABILITATO", False):
        run_guarded_fn("Arena Mercato", lambda: _daily.esegui_mercato_arena_guarded(porta, nome, logger, coords=coords))
    else:
        log("Arena Mercato disabilitato (ARENA_MERCATO_ABILITATO=False) - skip")

    def _do_rifornimento():
        try:
            if getattr(config, "RIFORNIMENTO_MAPPA_ABILITATO", False):
                import rifornimento_mappa as _rifmap
                return _rifmap.esegui_rifornimento_mappa(porta, nome, logger=logger, ciclo=ciclo)
            else:
                return rifornimento.esegui_rifornimento(
                    porta, nome,
                    logger=logger,
                    ciclo=ciclo,
                    coord_alleanza=coords.alleanza,
                    btn_template=coords.btn_rifornimento_template,
                )
        except Exception as _e:
            log(f"Rifornimento: errore non bloccante: {_e}")
            return None

    if getattr(config, "RIFORNIMENTO_ABILITATO", True):
        sped = run_guarded_fn("Rifornimento", _do_rifornimento)
        if sped and isinstance(sped, int) and sped > 0:
            log(f"Rifornimento: {sped} spedizione/i effettuata/e")
    else:
        log("Rifornimento disabilitato (RIFORNIMENTO_ABILITATO=False) - skip")


# ==============================================================================
# Lettura risorse deposito con retry/backoff — estratto da raccolta_istanza
# ==============================================================================

_RISORSE_PRINCIPALI = ("pomodoro", "legno", "acciaio", "petrolio")
_RETRY_DELAYS       = (2.0, 3.0, 4.0)


def _leggi_risorse_deposito(porta, nome, logger):
    """Legge le risorse deposito da screenshot con retry/backoff.

    Ritorna dict con chiavi pomodoro/legno/acciaio/petrolio/diamanti (-1 se non letta).
    Logga le risorse ancora mancanti dopo i retry ma non solleva eccezioni.
    """
    def log(msg):
        if logger:
            logger(nome, msg)

    _, _pil_dep, _ = _screenshot_cv(porta)
    risorse = ocr.leggi_risorse(pil_img=_pil_dep)
    fallite = [r for r in _RISORSE_PRINCIPALI if risorse.get(r, -1) < 0]

    for retry_i, delay in enumerate(_RETRY_DELAYS):
        if not fallite:
            break
        log(f"OCR risorse: {', '.join(fallite)} non lette - riprovo tra {delay:.0f}s "
            f"(tentativo {retry_i + 1}/{len(_RETRY_DELAYS)})...")
        time.sleep(delay)
        _, _pil_dep2, _ = _screenshot_cv(porta)
        nuove   = ocr.leggi_risorse(pil_img=_pil_dep2)
        # Aggiorna solo le risorse ancora mancanti, preserva quelle già lette
        for r in list(fallite):
            if nuove.get(r, -1) >= 0:
                risorse[r] = nuove[r]
        fallite = [r for r in _RISORSE_PRINCIPALI if risorse.get(r, -1) < 0]

    if fallite:
        log(f"OCR risorse: {', '.join(fallite)} ancora non lette dopo "
            f"{len(_RETRY_DELAYS)} retry — procedo con dati parziali")

    return risorse


# ==============================================================================
# Loop principale invio marce — estratto da raccolta_istanza
# ==============================================================================

def _loop_invio_marce(porta, nome, n_truppe, obiettivo, attive_inizio, libere,
                      risorse, coords, logger, blacklist, blacklist_lock,
                      ciclo, ist):
    """Loop invio squadre fino a slot pieni o MAX_FALLIMENTI.

    Ritorna il numero di squadre effettivamente inviate.
    Presuppone che il bot sia già in mappa all'ingresso.
    Lascia il bot in HOME all'uscita.
    """
    def log(msg):
        if logger:
            logger(nome, msg)

    _livello_ist = int(ist.get("livello", config.LIVELLO_RACCOLTA)) if ist else config.LIVELLO_RACCOLTA

    sequenza_base = allocation.calcola_sequenza(libere, risorse)
    allocation.log_decisione(libere, risorse, sequenza_base, logger, nome)

    max_iter    = obiettivo * max(2, config.MAX_TENTATIVI_RACCOLTA) + 5
    sequenza    = (sequenza_base * (max_iter // max(len(sequenza_base), 1) + 1))[:max_iter]

    inviate         = 0
    fallimenti_cons = 0
    MAX_FALLIMENTI  = 3
    tipi_bloccati   = set()
    cooldown_tipo_fino = {}

    attive_correnti = attive_inizio
    idx_seq         = 0
    iter_n          = 0

    _tutti_i_tipi    = ["campo", "segheria", "petrolio", "acciaio"]
    _tipi_in_sequenza = list(dict.fromkeys(sequenza_base))

    while attive_correnti < obiettivo and iter_n < max_iter:
        iter_n += 1

        # Step2A: se tutti i tipi disponibili sono in cooldown, attendi fino al primo che scade
        tipi_disponibili = [t for t in _tutti_i_tipi if t not in tipi_bloccati]
        if tipi_disponibili:
            now   = time.time()
            pronti = [t for t in tipi_disponibili if cooldown_tipo_fino.get(t, 0) <= now]
            if not pronti:
                t_min  = min(cooldown_tipo_fino.get(t, now + BLACKLIST_ATTESA_NODO) for t in tipi_disponibili)
                wait_s = int(max(1, min(BLACKLIST_ATTESA_NODO, t_min - now)))
                log(f"Tutti i tipi disponibili in cooldown — attendo {wait_s}s")
                stato.back_rapidi_e_stato(porta, n=3, logger=logger, nome=nome)
                time.sleep(wait_s)
                continue

        # Se tutti i tipi pianificati sono bloccati, prova i tipi non pianificati
        if _tipi_in_sequenza and all(t in tipi_bloccati for t in _tipi_in_sequenza):
            tipi_extra = [t for t in _tutti_i_tipi if t not in tipi_bloccati]
            if tipi_extra:
                log(f"Tipi pianificati bloccati — provo tipi alternativi: {tipi_extra}")
                sequenza          = tipi_extra * (obiettivo + 2)
                idx_seq           = 0
                _tipi_in_sequenza = tipi_extra
                continue
            else:
                log(f"Tutti i tipi bloccati {sorted(tipi_bloccati)} — abbandono raccolta")
                break

        tipo = sequenza[idx_seq % len(sequenza)]
        idx_seq += 1

        fino = cooldown_tipo_fino.get(tipo)
        if fino and time.time() < fino:
            continue
        if tipo in tipi_bloccati:
            continue
        if fallimenti_cons >= MAX_FALLIMENTI:
            log(f"Troppi fallimenti consecutivi ({fallimenti_cons}) - abbandono raccolta")
            break

        squadra_n = attive_correnti + 1
        log(f"Invio squadra (attive={attive_correnti}/{obiettivo}) -> {tipo} "
            f"(fallimenti cons: {fallimenti_cons}/{MAX_FALLIMENTI})")

        chiave_nodo, nodo_bloccato, marcia_tentata, eta_s, fuori_territorio, cooldown_s = _tap_invia_squadra(
            porta, tipo, n_truppe, nome, squadra_n, 1, ciclo,
            logger=logger, blacklist=blacklist, blacklist_lock=blacklist_lock,
            coords=coords, cooldown_map=cooldown_tipo_fino, livello_target=_livello_ist,
        )

        if cooldown_s and cooldown_s > 0:
            continue

        if nodo_bloccato:
            if fuori_territorio:
                log(f"Nodo fuori territorio — tipo '{tipo}' bloccato per questo ciclo")
            else:
                log(f"Tipo '{tipo}' bloccato da blacklist - squadre successive dello stesso tipo saltate")
                fallimenti_cons += 1
            tipi_bloccati.add(tipo)
            continue

        if not marcia_tentata:
            if chiave_nodo:
                log(f"Marcia NON partita - rollback blacklist nodo {chiave_nodo}")
                _blacklist_rollback(blacklist, blacklist_lock, chiave_nodo)
            fallimenti_cons += 1

            _c5_screen, _, _ = _screenshot_cv(porta)
            _c5_stato  = stato.rileva_screen(_c5_screen) if _c5_screen else 'sconosciuto'
            log(f"[CHECK-5] post-fallimento toggle='{_c5_stato}' (atteso: mappa)")
            if _c5_stato == 'home':
                log("[CHECK-5] in home — eseguo vai_in_mappa prima del prossimo invio")
                stato.vai_in_mappa(porta, nome, logger)
            elif _c5_stato not in ('mappa', 'sconosciuto'):
                log(f"[CHECK-5] stato '{_c5_stato}' — eseguo back_rapidi_e_stato")
                stato.back_rapidi_e_stato(porta, n=3, logger=logger, nome=nome)
            continue

        delay = min(DELAY_POSTMARCIA_BASE, MAX_DELAY_POSTMARCIA)
        time.sleep(delay)

        s_post, _ = stato.back_rapidi_e_stato(porta, n=3, logger=logger, nome=nome)
        if s_post == "home":
            log("Post-BACK: in home - torno in mappa")
            if not stato.vai_in_mappa(porta, nome, logger):
                log("Impossibile tornare in mappa - abbandono istanza")
                stato.vai_in_home(porta, nome, logger)
                return inviate
            time.sleep(2.0)
        elif s_post not in ("mappa", "home"):
            log(f"Post-BACK: stato '{s_post}' inatteso - reset")
            _reset_stato(porta, nome, "", squadra_n, 1, ciclo, logger)

        time.sleep(1.5)
        attive_dopo = _leggi_attive_con_retry(porta, nome, logger=logger, retry=3, sleep_s=1.5, n_squadre=obiettivo)

        if attive_dopo == -1:
            log("OCR post-MARCIA ancora non disponibile - considero fallimento prudenziale")
            if chiave_nodo:
                _blacklist_rollback(blacklist, blacklist_lock, chiave_nodo)
            fallimenti_cons += 1
            continue

        if attive_dopo > attive_correnti:
            log(f"Squadra confermata ({attive_correnti} -> {attive_dopo})")
            if chiave_nodo:
                _blacklist_commit(blacklist, blacklist_lock, chiave_nodo, eta_s=eta_s)
                ttl_log = f"ETA={eta_s}s" if eta_s else f"TTL={BLACKLIST_COMMITTED_TTL}s"
                log(f"Nodo {chiave_nodo} -> COMMITTED ({ttl_log})")
            attive_correnti = attive_dopo
            inviate        += 1
            fallimenti_cons = 0
            if attive_correnti >= obiettivo:
                log("Slot pieni — uscita immediata dal loop (no rientro in mappa)")
                break
            continue

        log(f"Contatore invariato dopo MARCIA: attive={attive_dopo} (era {attive_correnti}) - rileggo tra 3s")
        time.sleep(3.0)
        attive_dopo2 = _leggi_attive_con_retry(porta, nome, logger=logger, retry=2, sleep_s=1.0, n_squadre=obiettivo)

        if attive_dopo2 != -1 and attive_dopo2 > attive_correnti:
            log(f"Squadra confermata dopo retry ({attive_correnti} -> {attive_dopo2})")
            if chiave_nodo:
                _blacklist_commit(blacklist, blacklist_lock, chiave_nodo, eta_s=eta_s)
                ttl_log = f"ETA={eta_s}s" if eta_s else f"TTL={BLACKLIST_COMMITTED_TTL}s"
                log(f"Nodo {chiave_nodo} -> COMMITTED ({ttl_log})")
            attive_correnti = attive_dopo2
            inviate        += 1
            fallimenti_cons = 0
            if attive_correnti >= obiettivo:
                log("Slot pieni (retry) — uscita immediata dal loop (no rientro in mappa)")
                break
            continue

        # Contatore invariato o diminuito: potrebbe essere una squadra rientrata
        # durante l'invio (ETA breve). Se stavamo riempiendo l'ultimo slot e il
        # contatore è diminuito, la marcia è partita ma una squadra è tornata nello
        # stesso momento → slot effettivamente pieni. Commit e esci.
        if attive_dopo2 != -1 and attive_dopo2 < attive_correnti and attive_correnti >= obiettivo - 1:
            log(f"Contatore diminuito ({attive_correnti}->{attive_dopo2}): squadra rientrata durante invio "
                f"— marcia OK, slot occupati {attive_dopo2 + 1}/{obiettivo}")
            if chiave_nodo:
                _blacklist_commit(blacklist, blacklist_lock, chiave_nodo, eta_s=eta_s)
                ttl_log = f"ETA={eta_s}s" if eta_s else f"TTL={BLACKLIST_COMMITTED_TTL}s"
                log(f"Nodo {chiave_nodo} -> COMMITTED ({ttl_log})")
            attive_correnti = obiettivo
            inviate        += 1
            fallimenti_cons = 0
            log("Slot pieni (rientro simultaneo) — uscita dal loop")
            break

        log("Squadra respinta o marcia non partita - rollback nodo")
        if chiave_nodo:
            _blacklist_rollback(blacklist, blacklist_lock, chiave_nodo)
        fallimenti_cons += 1

    # -----------------------------------------------------------------
    # Post-loop: verifica contatore reale e recupero slot liberi
    # -----------------------------------------------------------------
    stato.vai_in_home(porta, nome, logger)

    early_exit_slot_pieni = (attive_correnti >= obiettivo)
    attive_reali          = attive_correnti

    if fallimenti_cons < MAX_FALLIMENTI:
        try:
            if stato.vai_in_mappa(porta, nome, logger):
                time.sleep(1.5)
                attive_lette, _, libere_lette = stato.conta_squadre(porta, n_letture=3, n_squadre=obiettivo)
                if attive_lette != -1:
                    attive_reali = attive_lette
                    if libere_lette > 0:
                        log(f"Contatore reale: {attive_reali}/{obiettivo} — {libere_lette} slot liberi, riprendo")
                        attive_correnti   = attive_reali
                        tipi_recupero     = [t for t in _tutti_i_tipi if t not in tipi_bloccati]
                        if not tipi_recupero:
                            tipi_recupero = list(_tutti_i_tipi)
                        seq_recupero = (tipi_recupero * (libere_lette + 3))[:libere_lette * 3 + 3]
                        idx_rec = 0
                        while attive_correnti < obiettivo and idx_rec < len(seq_recupero):
                            tipi_rec = [t for t in seq_recupero[idx_rec:] if t not in tipi_bloccati]
                            if tipi_rec:
                                now    = time.time()
                                pronti = [t for t in tipi_rec if cooldown_tipo_fino.get(t, 0) <= now]
                                if not pronti:
                                    t_min  = min(cooldown_tipo_fino.get(t, now + BLACKLIST_ATTESA_NODO) for t in tipi_rec)
                                    wait_s = int(max(1, min(BLACKLIST_ATTESA_NODO, t_min - now)))
                                    log(f"Recupero: tutti i tipi in cooldown — attendo {wait_s}s")
                                    stato.back_rapidi_e_stato(porta, n=3, logger=logger, nome=nome)
                                    time.sleep(wait_s)
                                    continue
                            tipo = seq_recupero[idx_rec]
                            idx_rec += 1
                            fino = cooldown_tipo_fino.get(tipo)
                            if fino and time.time() < fino:
                                continue
                            if tipo in tipi_bloccati:
                                continue
                            if fallimenti_cons >= MAX_FALLIMENTI:
                                break
                            squadra_n = attive_correnti + 1
                            log(f"Invio squadra (attive={attive_correnti}/{obiettivo}) -> {tipo} (recupero)")
                            chiave_nodo, nodo_bloccato, marcia_tentata, eta_s, fuori_territorio, cooldown_s = _tap_invia_squadra(
                                porta, tipo, n_truppe, nome, squadra_n, 1, ciclo,
                                logger=logger, blacklist=blacklist, blacklist_lock=blacklist_lock,
                                coords=coords, cooldown_map=cooldown_tipo_fino, livello_target=_livello_ist,
                            )
                            if cooldown_s and cooldown_s > 0:
                                continue
                            if nodo_bloccato:
                                tipi_bloccati.add(tipo)
                                if not fuori_territorio:
                                    fallimenti_cons += 1
                                continue
                            if not marcia_tentata:
                                if chiave_nodo:
                                    _blacklist_rollback(blacklist, blacklist_lock, chiave_nodo)
                                fallimenti_cons += 1
                                continue
                            time.sleep(min(DELAY_POSTMARCIA_BASE, MAX_DELAY_POSTMARCIA))
                            s_post, _ = stato.back_rapidi_e_stato(porta, n=3, logger=logger, nome=nome)
                            if s_post == "home":
                                if not stato.vai_in_mappa(porta, nome, logger):
                                    break
                            time.sleep(1.5)
                            attive_dopo = _leggi_attive_con_retry(porta, nome, logger=logger, retry=3, sleep_s=1.5, n_squadre=obiettivo)
                            if attive_dopo != -1 and attive_dopo > attive_correnti:
                                log(f"Squadra confermata nel recupero ({attive_correnti} -> {attive_dopo})")
                                if chiave_nodo:
                                    _blacklist_commit(blacklist, blacklist_lock, chiave_nodo, eta_s=eta_s)
                                attive_correnti = attive_dopo
                                inviate        += 1
                                fallimenti_cons = 0
                            else:
                                if chiave_nodo:
                                    _blacklist_rollback(blacklist, blacklist_lock, chiave_nodo)
                                fallimenti_cons += 1
                        stato.vai_in_home(porta, nome, logger)
                    else:
                        log(f"Contatore reale: {attive_reali}/{obiettivo} — slot pieni")
                        early_exit_slot_pieni = True
                        attive_correnti       = attive_reali
        except Exception as ex:
            log(f"Verifica contatore reale fallita (non bloccante): {ex}")

    if not early_exit_slot_pieni:
        try:
            if stato.vai_in_mappa(porta, nome, logger):
                time.sleep(1.5)
                attive_lette2, _, _ = stato.conta_squadre(porta, n_letture=3, n_squadre=obiettivo)
                if attive_lette2 != -1:
                    attive_reali = attive_lette2
                stato.vai_in_home(porta, nome, logger)
        except Exception:
            pass

    log(f"Raccolta completata - {inviate}/{obiettivo - attive_inizio} squadre inviate "
        f"(attive finali={attive_reali}/{obiettivo})")
    _log.registra_evento(ciclo, nome, "completata",
                         dettaglio=f"inviate={inviate} attive_finali={attive_reali}/{obiettivo}")

    return inviate


# ==============================================================================
# Entry point: raccolta istanza
# ==============================================================================

def raccolta_istanza(porta, nome, truppe=None, max_squadre=0, logger=None, ciclo=0,
                     blacklist=None, blacklist_lock=None, ist=None):
    def log(msg):
        if logger:
            logger(nome, msg)

    n_truppe = truppe if truppe is not None else config.TRUPPE_RACCOLTA

    from coords import UICoords
    coords       = UICoords.da_ist(ist) if ist is not None else UICoords.da_ist({"nome": nome, "layout": 1, "lingua": "it"})
    _livello_ist = int(ist.get("livello", config.LIVELLO_RACCOLTA)) if ist else config.LIVELLO_RACCOLTA

    log("Inizio raccolta risorse")
    _status.istanza_raccolta(nome)

    # ------------------------------------------------------------------
    # Guardie PRE/POST home — condivise tra task periodici e loop raccolta
    # ------------------------------------------------------------------
    def _ensure_home(context: str) -> bool:
        try:
            ok = stato.vai_in_home(porta, nome, logger)
            if not ok:
                log(f"[GUARD] {context}: impossibile confermare HOME")
            return ok
        except Exception as e:
            log(f"[GUARD] {context}: eccezione ensure_home: {e}")
            return False

    def _run_guarded(label: str, fn):
        if not _ensure_home(f"PRE {label}"):
            log(f"[GUARD] PRE {label}: skip (HOME non raggiunta)")
            return None
        try:
            return fn()
        except Exception as e:
            log(f"[GUARD] {label}: errore non bloccante: {e}")
            return None
        finally:
            _ensure_home(f"POST {label}")

    # ------------------------------------------------------------------
    # Profilo istanza
    # ------------------------------------------------------------------
    profilo       = ist.get("profilo", "full") if isinstance(ist, dict) else "full"
    solo_raccolta = (profilo == "raccolta_only")

    if solo_raccolta:
        log("[PROFILO] raccolta_only → skip task periodici e rifornimento")
    else:
        _esegui_task_periodici(
            porta, nome, logger, coords, ciclo, ist,
            ensure_home_fn=_ensure_home,
            run_guarded_fn=_run_guarded,
        )

    # ------------------------------------------------------------------
    # Attesa spedizioni rifornimento ancora in volo
    # ------------------------------------------------------------------
    # Il contatore squadre del gioco include anche le spedizioni di
    # rifornimento_mappa in volo. Se vengono lette subito, conta_squadre
    # può restituire attive > totale (es. 7/4), causando il salto della raccolta
    # o report errato. Aspettiamo il rientro basandoci sull'ETA registrato.
    try:
        eta_rifmap = _status.istanza_get(nome, "rifmap_eta_residua") or 0.0
        if eta_rifmap > 0:
            attesa_rif = min(float(eta_rifmap), 90.0)  # cap 90s per sicurezza
            log(f"[RIFMAP] Attesa rientro spedizioni ({attesa_rif:.0f}s) prima di conta_squadre")
            time.sleep(attesa_rif)
            _status.istanza_set(nome, "rifmap_eta_residua", 0.0)
    except Exception:
        pass  # non bloccante

    # ------------------------------------------------------------------
    # Contatore squadre in HOME
    # ------------------------------------------------------------------
    _n_sq = max_squadre if max_squadre and max_squadre > 0 else -1
    attive_inizio, totale, libere = stato.conta_squadre(porta, n_letture=3, n_squadre=_n_sq)
    if attive_inizio == -1:
        log("Contatore non visibile in home - attendo 2s e riprovo...")
        time.sleep(2.0)
        attive_inizio, totale, libere = stato.conta_squadre(porta, n_letture=3, n_squadre=_n_sq)

    fallback_totale = max_squadre if max_squadre and max_squadre > 0 else 4
    if attive_inizio == -1:
        log(f"Contatore non visibile in home — assumo 0/{fallback_totale} (procedo)")
        attive_inizio, totale, libere = 0, fallback_totale, fallback_totale
    else:
        log(f"Squadre: {attive_inizio}/{totale} attive, {libere} libere")
        if libere == 0:
            log("Nessuna squadra libera - salto raccolta")
            return 0

    # ------------------------------------------------------------------
    # Vai in mappa
    # ------------------------------------------------------------------
    gia_in_mappa = stato.rileva(porta)[0] == "mappa"
    if not stato.vai_in_mappa(porta, nome, logger):
        log("Impossibile andare in mappa - salto")
        _log.registra_evento(ciclo, nome, "errore_mappa", dettaglio="vai_in_mappa fallito")
        return 0

    if gia_in_mappa:
        log("Attesa rendering mappa (già in mappa al caricamento)...")
    time.sleep(2.0)

    # ------------------------------------------------------------------
    # Lettura risorse deposito
    # ------------------------------------------------------------------
    risorse  = _leggi_risorse_deposito(porta, nome, logger)

    pomodoro = risorse.get("pomodoro", -1)
    legno    = risorse.get("legno",    -1)
    acciaio  = risorse.get("acciaio",  -1)
    petrolio = risorse.get("petrolio", -1)
    diamanti = risorse.get("diamanti", -1)

    _status.istanza_risorse_inizio(nome, pomodoro, legno, acciaio, petrolio)
    if diamanti >= 0:
        _status.istanza_diamanti(nome, diamanti)

    def _fmt(v):
        return f"{v/1_000_000:.1f}M" if v >= 0 else "—"
    ris_log = (f"🍅 {_fmt(pomodoro)}  🪵 {_fmt(legno)}"
               + (f"  ⚙ {_fmt(acciaio)}"  if acciaio  >= 0 else "")
               + (f"  🛢 {_fmt(petrolio)}" if petrolio >= 0 else "")
               + (f"  💎 {int(diamanti)}"  if diamanti >= 0 else ""))
    log(f"Deposito: {ris_log}")

    # Rilettura contatore in mappa se la lettura in home era fallback
    if totale == fallback_totale and attive_inizio == 0:
        _att, _tot, _lib = stato.conta_squadre(porta, n_letture=3, n_squadre=_n_sq)
        if _att != -1:
            attive_inizio, totale, libere = _att, _tot, _lib
            log(f"Squadre (rilettura mappa): {attive_inizio}/{totale} attive, {libere} libere")
            if libere == 0:
                log("Nessuna squadra libera (confermato in mappa) - salto raccolta")
                stato.vai_in_home(porta, nome, logger)
                return 0

    obiettivo = totale
    log(f"Obiettivo: {obiettivo}/{totale} (slot da riempire fino a pieno)")

    # ------------------------------------------------------------------
    # Loop invio marce
    # ------------------------------------------------------------------
    inviate = _loop_invio_marce(
        porta, nome, n_truppe, obiettivo, attive_inizio, libere,
        risorse, coords, logger, blacklist, blacklist_lock, ciclo, ist,
    )

    # ------------------------------------------------------------------
    # Snapshot risorse fine ciclo
    # ------------------------------------------------------------------
    try:
        _, _pil_fine, _ = _screenshot_cv(porta)
        risorse_fine = ocr.leggi_risorse(pil_img=_pil_fine) if _pil_fine is not None else {}
        if all(risorse_fine.get(r, -1) < 0 for r in ("pomodoro", "legno")):
            time.sleep(2.0)
            _, _pil_fine, _ = _screenshot_cv(porta)
            risorse_fine = ocr.leggi_risorse(pil_img=_pil_fine) if _pil_fine is not None else {}
        pom_f = risorse_fine.get("pomodoro", -1)
        leg_f = risorse_fine.get("legno",    -1)
        acc_f = risorse_fine.get("acciaio",  -1)
        pet_f = risorse_fine.get("petrolio", -1)
        dia_f = risorse_fine.get("diamanti", -1)
        _status.istanza_risorse_fine(nome, pom_f, leg_f, acc_f, pet_f)
        if dia_f >= 0:
            _status.istanza_diamanti(nome, dia_f)
        def _fmt2(v):
            return f"{v/1_000_000:.1f}M" if v >= 0 else "—"
        fin_log = (f"🍅 {_fmt2(pom_f)}  🪵 {_fmt2(leg_f)}"
                   + (f"  ⚙ {_fmt2(acc_f)}"  if acc_f >= 0 else "")
                   + (f"  🛢 {_fmt2(pet_f)}" if pet_f >= 0 else "")
                   + (f"  💎 {int(dia_f)}"   if dia_f >= 0 else ""))
        log(f"Deposito fine ciclo: {fin_log}")
    except Exception as e:
        log(f"Snapshot risorse fine ciclo fallito (non bloccante): {e}")

    return inviate
