# ==============================================================================
# DOOMSDAY BOT V5 - raccolta.py V5.16.1
# ==============================================================================
#
# V5.13.1: Fix caso "SQUADRA non apre maschera" quando la UI resta in mappa
# - Dopo tap SQUADRA confronta screenshot prima/dopo: se invariato, retry tap SQUADRA con attesa maggiore.
#
# V5.13: Fix logica invio marce + robustezza UI/contatore
# - Loop invio: continua finché gli slot risultano pieni (attive >= obiettivo) o finché fallimenti consecutivi >= soglia.
# - OCR post-MARCIA: retry + recovery leggera (no fallimento immediato al primo -1).
# - Sequenza RACCOGLI→SQUADRA→MARCIA: controllo schermata invariata prima/dopo MARCIA (maschera bloccata).
# - Blacklist transazionale:
#   RESERVED (TTL breve) durante la transazione UI; COMMITTED (TTL 120s) solo dopo conferma contatore.
#   NOTA: per scelta attuale, il nodo COMMITTED NON viene rilasciato subito dopo conferma (resta occupato).
# - Fix bug critico: rollback blacklist corretto (pop), nessuna ricorsione.
#
# IMPORTANT: BLACKLIST_COMMITTED_TTL resta fisso a 120s (stima percorrenza).
# In step successivi potremo leggere il tempo reale dalla maschera "Marcia".
# ==============================================================================

import hashlib
import time

import adb
import stato
import ocr
import debug
import log as _log
import status as _status
import config
import rifornimento
import allocation

# Post-marcia: attesa base (ms->s) con limite
DELAY_POSTMARCIA_BASE = config.DELAY_MARCIA / 1000
MAX_DELAY_POSTMARCIA = 6.0

# ------------------------------------------------------------------------------
# Utility
# ------------------------------------------------------------------------------

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


# ------------------------------------------------------------------------------
# Blacklist transazionale (RESERVED / COMMITTED)
# ------------------------------------------------------------------------------

BLACKLIST_COMMITTED_TTL = 120  # secondi — TTL nodo occupato dopo conferma marcia (stima percorrenza)
BLACKLIST_RESERVED_TTL = 45    # secondi — TTL prenotazione temporanea durante transazione UI
# Retrocompatibilità: BLACKLIST_TTL era usato come unico TTL. Ora equivale al TTL COMMITTED.
BLACKLIST_TTL = BLACKLIST_COMMITTED_TTL
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


# ------------------------------------------------------------------------------
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
# ------------------------------------------------------------------------------

TERRITORIO_BUFF_ZONA = (250, 340, 420, 370)  # (x1,y1,x2,y2) — riga "+30%"
TERRITORIO_SOGLIA_PX = 20                     # pixel verdi minimi per IN territorio

# Zona titolo popup nodo (es. "Campo Lv.6") — riga in alto della maschera
# Calibrata su 960x540: il titolo appare centrato, y≈155-180
NODO_TITOLO_ZONA = (250, 150, 720, 185)
# Livello minimo accettabile — nodi sotto questa soglia vengono scartati
NODO_LIVELLO_MIN = getattr(__import__('config'), 'LIVELLO_RACCOLTA', 6)


def _leggi_livello_nodo(screen_path: str) -> int:
    """
    Legge il livello del nodo dal titolo del popup (es. "Campo Lv.6" → 6).

    Ritorna:
        int >= 1  se il livello è leggibile
        -1        se OCR fallisce (fail-safe: non scartare per dubbio)
    """
    try:
        from PIL import Image as _PIL_Image
        import pytesseract
        import re as _re

        img = _PIL_Image.open(screen_path)
        crop = img.crop(NODO_TITOLO_ZONA)
        w, h = crop.size
        # Upscale 4x + scala grigi + soglia
        big = crop.resize((w * 4, h * 4), _PIL_Image.LANCZOS)
        gray = big.convert("L")
        bw = gray.point(lambda p: 255 if p > 130 else 0)

        cfg = "--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789. "
        import threading as _threading
        # Usa il lock Tesseract di ocr.py se disponibile
        try:
            import ocr as _ocr_mod
            lock = _ocr_mod._tesseract_lock
        except Exception:
            lock = _threading.Lock()

        with lock:
            testo = pytesseract.image_to_string(bw, config=cfg).strip()

        # Cerca pattern "Lv.N" o "Lv N" o "Level N" (EN: "Lv.6")
        m = _re.search(r'[Ll][Vv]\.?\s*(\d+)', testo)
        if m:
            return int(m.group(1))
        return -1
    except Exception:
        return -1

def _nodo_in_territorio(screen_path: str) -> bool:
    """
    Ritorna True se il popup del nodo mostra il buff territorio (riga verde "+30%").
    Ritorna True in caso di errore (fail-safe: non scartare per dubbio).
    """
    try:
        import numpy as np
        from PIL import Image as _Image
        img = _Image.open(screen_path)
        arr = np.array(img)
        x1, y1, x2, y2 = TERRITORIO_BUFF_ZONA
        zona = arr[y1:y2, x1:x2, :3].astype(int)
        r, g, b = zona[:,:,0], zona[:,:,1], zona[:,:,2]
        # Verde dominante: G alto, G > R*1.4, G > B*1.3, G-R > 40
        verdi = (g > 140) & (g > r * 1.4) & (g > b * 1.3) & ((g - r) > 40)
        return int(verdi.sum()) >= TERRITORIO_SOGLIA_PX
    except Exception:
        return True  # fail-safe: in caso di errore non scartare


# ------------------------------------------------------------------------------
# Raccolta: ricerca nodo + OCR coordinate
# ------------------------------------------------------------------------------

def _cerca_nodo(porta, tipo, coords=None, livello_target=None):
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
    """
    if coords is not None:
        tap_icona, tap_cerca = coords.per_tipo(tipo)
        adb.tap(porta, coords.lente)
    else:
        _TAP_MAPPA = {
            "campo":    (config.TAP_CAMPO,       config.TAP_CERCA_CAMPO),
            "segheria": (config.TAP_SEGHERIA,    config.TAP_CERCA_SEGHERIA),
            "acciaio":  (config.TAP_ACCIAIERIA,  config.TAP_CERCA_ACCIAIERIA),
            "petrolio": (config.TAP_RAFFINERIA,  config.TAP_CERCA_RAFFINERIA),
        }
        tap_icona, tap_cerca = _TAP_MAPPA.get(tipo, _TAP_MAPPA["campo"])
        adb.tap(porta, config.TAP_LENTE)

    adb.tap(porta, tap_icona)
    adb.tap(porta, tap_icona)
    time.sleep(1.2)  # attesa apertura popup livello

    # Offset misurati su screenshot reali 960x540 (tipo campo icona_x=410):
    #   — : centro x=294  → offset = 410-294 = 116
    #   + : centro x=519  → offset = 519-410 = 109
    #   SEARCH: centro x=413 → offset = 3
    _OFFSET_MENO_X  = 116
    _OFFSET_PIU_X   = 109
    _OFFSET_CERCA_X =   3
    _MENO_Y         = 295   # y centro pulsante —
    _PIU_Y          = 293   # y centro pulsante +
    _CERCA_Y        = 352   # y centro pulsante SEARCH

    icona_x = tap_icona[0]
    x_meno  = icona_x - _OFFSET_MENO_X
    x_piu   = icona_x + _OFFSET_PIU_X
    x_cerca = icona_x + _OFFSET_CERCA_X

    # Livello target: dall'istanza se disponibile, altrimenti config globale
    _lv = int(livello_target) if livello_target and int(livello_target) > 0 else config.LIVELLO_RACCOLTA
    _lv = max(1, min(7, _lv))  # clamp 1-7

    # Il popup si ancora all'icona ma non può uscire dal bordo destro (960px).
    # Per petrolio (icona_x=820) il popup è clamped a destra → coordinate assolute.
    # Coordinate assolute misurate su screen reali 960x540:
    #   campo:    —(294,295)  +(519,293)  S(413,352)
    #   segheria: —(419,295)  +(644,293)  S(538,352)
    #   acciaio:  —(556,295)  +(781,293)  S(675,352)
    #   petrolio: —(701,295)  +(890,293)  S(791,352)  ← clamped al bordo dx
    _COORD_ASSOLUTE = {
        "campo":    {"meno": (294, 295), "piu": (519, 293), "search": (413, 352)},
        "segheria": {"meno": (419, 295), "piu": (644, 293), "search": (538, 352)},
        "acciaio":  {"meno": (556, 295), "piu": (781, 293), "search": (675, 352)},
        "petrolio": {"meno": (701, 295), "piu": (890, 293), "search": (791, 352)},
    }
    _coords_lv = _COORD_ASSOLUTE.get(tipo, _COORD_ASSOLUTE["campo"])
    _tap_meno   = _coords_lv["meno"]
    _tap_piu    = _coords_lv["piu"]
    _tap_search = _coords_lv["search"]

    # Reset a Lv.1: 6 tap su — (livello max=7, quindi 6 tap garantiscono Lv.1)
    # poi sale a Lv._lv con (_lv - 1) tap su +
    import log as _log_cerca
    try: _log_cerca.logger("CERCA", f"[LV] {tipo} Lv.{_lv} reset -6@{_tap_meno} poi +{_lv-1}@{_tap_piu}")
    except Exception: pass
    for _ in range(6):
        adb.tap(porta, _tap_meno, delay_ms=120)
    for _ in range(_lv - 1):
        adb.tap(porta, _tap_piu, delay_ms=150)

    # SEARCH con coordinate assolute misurate
    adb.tap(porta, _tap_search, delay_ms=config.DELAY_CERCA)


def _leggi_coord_nodo(porta, nome, tipo, squadra, tentativo, retry_n, logger):
    """Tap lente coord + screenshot + OCR coordinate. Ritorna (chiave, cx, cy, screen)."""
    def log(msg):
        if logger:
            logger(nome, msg)

    time.sleep(1.5)
    adb.tap(porta, config.TAP_LENTE_COORD, delay_ms=1300)
    screen_nodo = adb.screenshot(porta)

    debug.salva_screen(screen_nodo, nome, f"fase3_popup_{tipo}", squadra, tentativo, f"r{retry_n}")
    debug.salva_crop_coord(screen_nodo, nome, "fase3_ocr_coord", squadra, tentativo, f"r{retry_n}")

    coord = ocr.leggi_coordinate_nodo(screen_nodo)
    log(f"[FASE3] OCR coordinate: {coord} (retry {retry_n})")

    if coord is None:
        return None, None, None, screen_nodo

    cx, cy = coord
    return f"{cx}_{cy}", cx, cy, screen_nodo


# ------------------------------------------------------------------------------
# Conferma contatore post-MARCIA (robusto)
# ------------------------------------------------------------------------------

def _leggi_attive_con_retry(porta, nome, logger=None, n_letture=3, retry=3, sleep_s=1.5):
    """Legge attive con retry quando OCR non disponibile (-1). Ritorna attive o -1.

    NON invia BACK durante i retry: se il bot è già in mappa un BACK lo porterebbe
    in home rendendo il contatore non visibile. Aspetta che la UI si stabilizzi
    dopo la transizione post-marcia, verificando lo stato prima di ogni lettura.
    """
    def log(msg):
        if logger:
            logger(nome, msg)

    for i in range(retry):
        # Verifica stato: il contatore è visibile solo in mappa
        s_ora, _ = stato.rileva(porta)
        if s_ora not in ("mappa",):
            log(f"OCR contatore: stato '{s_ora}' (non mappa) - attendo {sleep_s:.1f}s stabilizzazione")
            time.sleep(sleep_s)
            continue

        attive, _, _ = stato.conta_squadre(porta, n_letture=n_letture)
        if attive != -1:
            return attive
        log(f"OCR contatore non disponibile (tentativo {i+1}/{retry}) - attendo {sleep_s:.1f}s")
        time.sleep(sleep_s)
    return -1


# ------------------------------------------------------------------------------
# Sequenza UI: RACCOGLI → SQUADRA → (truppe) → MARCIA
# ------------------------------------------------------------------------------

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

    # 1) RACCOGLI
    adb.tap(porta, _raccogli)
    time.sleep(0.5)

    # 2) SQUADRA — confronto hash prima/dopo per rilevare maschera non aperta
    screen_before_squadra = adb.screenshot(porta)
    before_hash = _md5_file(screen_before_squadra)

    adb.tap(porta, _squadra)
    time.sleep(1.4)

    screen_pre = adb.screenshot(porta)
    debug.salva_screen(screen_pre, nome, "pre_marcia", squadra, tentativo)

    # Lettura ETA marcia dalla maschera (dopo apertura SQUADRA)
    try:
        eta_s, raw = ocr.leggi_eta_marcia(screen_pre)
    except Exception:
        eta_s, raw = None, ""

    # Cap ETA: valori superiori a 600s sono misread OCR — scartali
    if eta_s is not None and eta_s > 600:
        log(f"ETA marcia: {eta_s}s — valore anomalo (misread OCR), ignorato")
        eta_s = None

    if eta_s is not None:
        log(f"ETA marcia: {eta_s}s ({eta_s//60}m{eta_s%60:02d}s)")
    elif tentativo == 1:
        log("ETA marcia non leggibile")
        if raw:
            log(f"ETA OCR raw: '{raw[:40]}'")

    pre_hash = _md5_file(screen_pre)

    if before_hash and pre_hash and before_hash == pre_hash:
        log("SQUADRA: schermata invariata (maschera non aperta) - retry tap SQUADRA")
        adb.tap(porta, _squadra)
        time.sleep(1.8)
        screen_pre = adb.screenshot(porta)
        debug.salva_screen(screen_pre, nome, "pre_marcia_retry", squadra, tentativo)

        try:
            eta_s2, raw2 = ocr.leggi_eta_marcia(screen_pre)
            if eta_s2 is not None and eta_s2 > 600:
                log(f"ETA marcia (retry): {eta_s2}s — valore anomalo (misread OCR), ignorato")
                eta_s2 = None
            if eta_s2 is not None:
                eta_s = eta_s2
                log(f"ETA marcia (retry): {eta_s}s ({eta_s//60}m{eta_s%60:02d}s)")
            elif raw2 and tentativo == 1:
                log(f"ETA OCR raw (retry): '{raw2[:40]}'")
        except Exception:
            pass

        pre_hash = _md5_file(screen_pre)
        if before_hash and pre_hash and before_hash == pre_hash:
            log("SQUADRA: ancora schermata invariata dopo retry - considero invio FALLITO")
            return False, eta_s

    # 3) Imposta truppe se richiesto
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

    # 4) MARCIA
    adb.tap(porta, _marcia)
    time.sleep(0.8)

    # 5) Verifica schermata cambiata dopo MARCIA
    screen_post = adb.screenshot(porta)
    post_hash = _md5_file(screen_post)

    if pre_hash and post_hash and pre_hash == post_hash:
        log("MARCIA: schermata invariata (probabile maschera bloccata) - retry tap MARCIA")
        adb.tap(porta, _marcia)
        time.sleep(1.0)
        screen_post2 = adb.screenshot(porta)
        post_hash2 = _md5_file(screen_post2)
        if pre_hash and post_hash2 and pre_hash == post_hash2:
            log("MARCIA: ancora schermata invariata dopo retry - considero invio FALLITO")
            return False, eta_s

    return True, eta_s


# ------------------------------------------------------------------------------
# Invio squadra: cerca nodo + gestisci blacklist + invio
# ------------------------------------------------------------------------------

def _tap_invia_squadra(porta, tipo, n_truppe, nome, squadra, tentativo, ciclo,
                      logger=None, blacklist=None, blacklist_lock=None, coords=None, cooldown_map=None, livello_target=None):
    """Ritorna (chiave_nodo, nodo_bloccato, marcia_tentata, eta_s, fuori_territorio, cooldown_s)."""
    def log(msg):
        if logger:
            logger(nome, msg)

    _nodo_coord = coords.nodo if coords else config.TAP_NODO

    _cerca_nodo(porta, tipo, coords, livello_target=livello_target)
    chiave_nodo, cx, cy, screen_nodo = _leggi_coord_nodo(porta, nome, tipo, squadra, tentativo, 1, logger)

    if chiave_nodo is None:
        log("Coordinate nodo non leggibili - procedo senza blacklist")
        debug.salva_screen(screen_nodo, nome, "fase3_ocr_coord_fail", squadra, tentativo, "r1")
        adb.keyevent(porta, "KEYCODE_BACK")
        time.sleep(0.4)
        adb.tap(porta, _nodo_coord)
        time.sleep(0.6)
        ok, eta_s = _esegui_marcia(porta, nome, n_truppe, squadra, tentativo, logger, coords)
        return None, False, ok, eta_s, False, 0

    if _blacklist_pulisci_e_verifica(blacklist, blacklist_lock, chiave_nodo):
        log(f"Nodo ({cx},{cy}) in blacklist - riprovo CERCA")
        debug.salva_screen(screen_nodo, nome, "fase3_blacklist", squadra, tentativo, f"{cx}_{cy}_r1")

        chiave_primo = chiave_nodo
        _cerca_nodo(porta, tipo, coords, livello_target=livello_target)
        chiave_nodo, cx, cy, screen_nodo = _leggi_coord_nodo(porta, nome, tipo, squadra, tentativo, 2, logger)

        if chiave_nodo == chiave_primo or chiave_nodo is None:
            # Il gioco continua a proporre lo stesso nodo occupato.
            # Step2: invece di attendere qui (bloccante), mettiamo il *tipo* in cooldown e proseguiamo con altri tipi.
            attesa = 3
            if _blacklist_get_state(blacklist, blacklist_lock, chiave_primo) == "COMMITTED":
                eta_prev = _blacklist_get_eta(blacklist, blacklist_lock, chiave_primo)
                if isinstance(eta_prev, (int, float)) and eta_prev > 0:
                    marg = getattr(config, "OCR_MARCIA_ETA_MARGINE_S", 5)
                    att_min = getattr(config, "OCR_MARCIA_ETA_MIN_S", 8)
                    attesa = int(min(BLACKLIST_ATTESA_NODO, max(att_min, eta_prev + marg)))
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

    screen_popup = adb.screenshot(porta)
    debug.salva_screen(screen_popup, nome, "fase4_popup_raccogli", squadra, tentativo, f"{cx}_{cy}")

    # --- Controllo livello nodo ---
    # Scarta nodi con livello < NODO_LIVELLO_MIN (default 6) indipendentemente dal territorio.
    # Un nodo Lv.5 dà meno risorse anche se in territorio — non vale la pena raccoglierlo.
    if screen_popup:
        _livello = _leggi_livello_nodo(screen_popup)
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

    if screen_popup and not _nodo_in_territorio(screen_popup):
        log(f"Nodo ({cx},{cy}) FUORI territorio alleanza — scarto e cerco altro")
        debug.salva_screen(screen_popup, nome, "fase4_fuori_territorio", squadra, tentativo, f"{cx}_{cy}")
        adb.keyevent(porta, "KEYCODE_BACK")
        time.sleep(0.4)
        _blacklist_commit(blacklist, blacklist_lock, chiave_nodo, eta_s=None)
        log(f"Nodo ({cx},{cy}) aggiunto a blacklist (fuori territorio)")
        return chiave_nodo, True, False, None, True, 0

    _blacklist_reserve(blacklist, blacklist_lock, chiave_nodo)
    log(f"Nodo ({cx},{cy}) prenotato in blacklist (RESERVED)")

    for t in range(1, config.MAX_TENTATIVI_RACCOLTA + 1):
        ok, eta_s = _esegui_marcia(porta, nome, n_truppe, squadra, t, logger, coords)
        if ok:
            return chiave_nodo, False, True, eta_s, False, 0

        log(f"MARCIA fallita (tentativo {t}/{config.MAX_TENTATIVI_RACCOLTA}) - recovery UI")
        # Recovery robusta: la maschera truppe/marcia può avere 2-3 livelli aperti.
        # Un singolo BACK non è sufficiente — usa back_rapidi_e_stato per ripristinare
        # uno stato pulito prima del prossimo tentativo o dell'uscita.
        s_rec, _ = stato.back_rapidi_e_stato(porta, n=4, logger=logger, nome=nome)
        if s_rec == "home":
            log("Recovery: in home - riporto in mappa prima del prossimo tentativo")
            if not stato.vai_in_mappa(porta, nome, logger):
                log("Recovery: impossibile tornare in mappa - abbandono")
                return chiave_nodo, False, False, None, False, 0
        elif s_rec not in ("mappa", "home"):
            log(f"Recovery: stato '{s_rec}' - reset completo")
            _reset_stato(porta, nome, "", squadra, t, 0, logger)

    return chiave_nodo, False, False, None, False, 0


# ------------------------------------------------------------------------------
# Entry point: raccolta istanza
# ------------------------------------------------------------------------------

def raccolta_istanza(porta, nome, truppe=None, max_squadre=0, logger=None, ciclo=0,
                    blacklist=None, blacklist_lock=None, ist=None):
    def log(msg):
        if logger:
            logger(nome, msg)

    n_truppe = truppe if truppe is not None else config.TRUPPE_RACCOLTA

    # Costruisce coordinate UI per questa istanza (risolve layout barra)
    from coords import UICoords
    coords = UICoords.da_ist(ist) if ist is not None else UICoords.da_ist({"nome": nome, "layout": 1, "lingua": "it"})
    _livello_ist = int(ist.get("livello", config.LIVELLO_RACCOLTA)) if ist else config.LIVELLO_RACCOLTA

    log("Inizio raccolta risorse")
    _status.istanza_raccolta(nome)

    import messaggi as _msg
    if getattr(config, "MESSAGGI_ABILITATI", True):
        _msg.raccolta_messaggi(porta, nome, logger)
    else:
        log("Messaggi disabilitati (MESSAGGI_ABILITATI=False) - skip")

    import alleanza as _all
    if getattr(config, "ALLEANZA_ABILITATA", True):
        _all.raccolta_alleanza(porta, nome, logger, ist=ist)
    else:
        log("Alleanza disabilitata (ALLEANZA_ABILITATA=False) - skip")

    # --- DAILY TASKS — eseguiti in HOME, schedulazione 24h ---
    import daily_tasks as _daily
    _daily.esegui_daily_tasks(porta, nome, logger)

    # --- INVIO RISORSE — eseguito in HOME prima di andare in mappa ---
    try:
        sped = rifornimento.esegui_rifornimento(
            porta, nome,
            logger=logger,
            ciclo=ciclo,
            coord_alleanza=coords.alleanza,
            btn_template=coords.btn_rifornimento_template,
        )
        if sped and sped > 0:
            log(f"Rifornimento: {sped} spedizione/i effettuata/e")
    except Exception as _e:
        log(f"Rifornimento: errore non bloccante: {_e}")

    # Porta in mappa
    gia_in_mappa = stato.rileva(porta)[0] == "mappa"
    if not stato.vai_in_mappa(porta, nome, logger):
        log("Impossibile andare in mappa - salto")
        _log.registra_evento(ciclo, nome, "errore_mappa", dettaglio="vai_in_mappa fallito")
        return 0

    if gia_in_mappa:
        log("Attesa rendering mappa (già in mappa al caricamento)...")
        time.sleep(2.0)
    else:
        # Attesa extra per il rendering del widget squadre dopo la transizione home→mappa.
        # Il contatore X/Y appare circa 1.5-2s dopo che la mappa è visibile.
        time.sleep(2.0)

    # Leggi risorse deposito — retry con backoff se almeno una risorsa principale
    # non è leggibile. Causa tipica: barra non ancora renderizzata dopo vai_in_mappa,
    # banner evento o animazione di transizione che copre temporaneamente un'icona.
    # Backoff: 2s → 3s → 4s (max 3 retry). Ogni tentativo fa nuovo screenshot.
    _RISORSE_PRINCIPALI = ("pomodoro", "legno", "acciaio", "petrolio")
    _RETRY_DELAYS = (2.0, 3.0, 4.0)
    screen = adb.screenshot(porta)
    risorse = ocr.leggi_risorse(screen)
    _fallite = [r for r in _RISORSE_PRINCIPALI if risorse.get(r, -1) < 0]
    for _retry_i, _delay in enumerate(_RETRY_DELAYS):
        if not _fallite:
            break
        log(f"OCR risorse: {', '.join(_fallite)} non lette - riprovo tra {_delay:.0f}s (tentativo {_retry_i + 1}/{len(_RETRY_DELAYS)})...")
        time.sleep(_delay)
        screen = adb.screenshot(porta)
        _nuove = ocr.leggi_risorse(screen)
        # Aggiorna solo le risorse ancora mancanti, preserva quelle già lette
        for _r in list(_fallite):
            if _nuove.get(_r, -1) >= 0:
                risorse[_r] = _nuove[_r]
        _fallite = [r for r in _RISORSE_PRINCIPALI if risorse.get(r, -1) < 0]
    if _fallite:
        log(f"OCR risorse: {', '.join(_fallite)} ancora non lette dopo {len(_RETRY_DELAYS)} retry — procedo con dati parziali")

    pomodoro = risorse.get("pomodoro", -1)
    legno    = risorse.get("legno",    -1)
    acciaio  = risorse.get("acciaio",  -1)
    petrolio = risorse.get("petrolio", -1)
    diamanti = risorse.get("diamanti", -1)
    # Snapshot inizio ciclo — usato per calcolo produzione netta
    _status.istanza_risorse_inizio(nome, pomodoro, legno, acciaio, petrolio)
    if diamanti >= 0:
        _status.istanza_diamanti(nome, diamanti)

    # Log risorse deposito per verifica visiva
    def _fmt(v): return f"{v/1_000_000:.1f}M" if v >= 0 else "—"
    ris_log = (f"🍅 {_fmt(pomodoro)}  🪵 {_fmt(legno)}"
               + (f"  ⚙ {_fmt(acciaio)}"  if acciaio  >= 0 else "")
               + (f"  🛢 {_fmt(petrolio)}" if petrolio >= 0 else "")
               + (f"  💎 {int(diamanti)}"  if diamanti >= 0 else ""))
    log(f"Deposito: {ris_log}")

    # Leggi contatore squadre (con fallback)
    attive_inizio, totale, libere = stato.conta_squadre(porta, n_letture=3)
    if attive_inizio == -1:
        log("Contatore non visibile - attendo 2.5s e riprovo...")
        time.sleep(2.5)
        attive_inizio, totale, libere = stato.conta_squadre(porta, n_letture=3)

    if attive_inizio == -1:
        fallback_totale = max_squadre if max_squadre and max_squadre > 0 else 4
        log(f"Contatore non visibile dopo retry - assumo 0/{fallback_totale} attive, {fallback_totale} libere")
        attive_inizio, totale, libere = 0, fallback_totale, fallback_totale
    else:
        log(f"Squadre: {attive_inizio}/{totale} attive, {libere} libere")

    if libere == 0:
        log("Nessuna squadra libera - salto raccolta")
        stato.vai_in_home(porta, nome, logger)
        return 0

    obiettivo = totale
    log(f"Obiettivo: {obiettivo}/{totale} (slot da riempire fino a pieno)")

    # --- Sequenza adattiva basata sul deposito corrente ---
    # allocation.calcola_sequenza() usa il gap target/attuale per decidere
    # quanti slot dedicare a ciascun tipo di nodo questo ciclo.
    # La sequenza viene estesa fino a coprire max_iter ripetizioni
    # (il loop la scorre ciclicamente tramite idx_seq % len).
    sequenza_base = allocation.calcola_sequenza(libere, risorse)
    allocation.log_decisione(libere, risorse, sequenza_base, logger, nome)
    # Estendi la sequenza per coprire tutti i potenziali tentativi del loop
    # (max_iter può essere maggiore di libere se ci sono retry/fallimenti)
    _max_iter_seq = obiettivo * max(2, config.MAX_TENTATIVI_RACCOLTA) + 5
    sequenza = (sequenza_base * (_max_iter_seq // max(len(sequenza_base), 1) + 1))[:_max_iter_seq]

    inviate = 0
    fallimenti_cons = 0
    MAX_FALLIMENTI = 3
    tipi_bloccati = set()
    cooldown_tipo_fino = {}  # Step2: cooldown per tipo (evita attese bloccanti su nodo riproposto)

    attive_correnti = attive_inizio
    idx_seq = 0

    # Loop FINCHÉ slot pieni (o fallimenti)
    max_iter = _max_iter_seq
    iter_n = 0

    # Tutti i tipi supportati — usati come fallback se i tipi pianificati sono bloccati
    _tutti_i_tipi = ["campo", "segheria", "petrolio", "acciaio"]
    # Tipi disponibili nella sequenza base (senza duplicati, ordine stabile)
    _tipi_in_sequenza = list(dict.fromkeys(sequenza_base))

    while attive_correnti < obiettivo and iter_n < max_iter:
        iter_n += 1
        # Step2A: se ci sono slot da riempire ma tutti i tipi disponibili sono in cooldown, attendo fino al primo cooldown che scade
        tipi_disponibili = [t for t in _tutti_i_tipi if t not in tipi_bloccati]
        if tipi_disponibili:
            now = time.time()
            pronti = [t for t in tipi_disponibili if cooldown_tipo_fino.get(t, 0) <= now]
            if not pronti:
                t_min = min(cooldown_tipo_fino.get(t, now + BLACKLIST_ATTESA_NODO) for t in tipi_disponibili)
                wait_s = int(max(1, min(BLACKLIST_ATTESA_NODO, t_min - now)))
                log(f"Tutti i tipi disponibili in cooldown — attendo {wait_s}s")
                # torna in mappa pulita prima di attendere, evita overlay persistenti
                stato.back_rapidi_e_stato(porta, n=3, logger=logger, nome=nome)
                time.sleep(wait_s)
                continue

        # Se tutti i tipi pianificati sono bloccati, prova i tipi non pianificati
        # prima di arrendersi — obiettivo è sempre riempire tutti gli slot.
        if _tipi_in_sequenza and all(t in tipi_bloccati for t in _tipi_in_sequenza):
            tipi_extra = [t for t in _tutti_i_tipi if t not in tipi_bloccati]
            if tipi_extra:
                log(f"Tipi pianificati bloccati — provo tipi alternativi: {tipi_extra}")
                # Estendi la sequenza con i tipi extra e continua il loop
                sequenza_extra = tipi_extra * (obiettivo + 2)
                sequenza = sequenza_extra
                idx_seq = 0
                _tipi_in_sequenza = tipi_extra  # aggiorna il check di uscita
                continue
            else:
                log(f"Tutti i tipi bloccati {sorted(tipi_bloccati)} — abbandono raccolta")
                break

        tipo = sequenza[idx_seq % len(sequenza)]
        idx_seq += 1
        # Step2: se il tipo è in cooldown, salto e provo il prossimo
        fino = cooldown_tipo_fino.get(tipo)
        if fino and time.time() < fino:
            continue

        if tipo in tipi_bloccati:
            continue  # skip silenzioso — il log "bloccato" è già stato emesso

        if fallimenti_cons >= MAX_FALLIMENTI:
            log(f"Troppi fallimenti consecutivi ({fallimenti_cons}) - abbandono raccolta")
            break

        squadra_n = attive_correnti + 1
        log(f"Invio squadra (attive={attive_correnti}/{obiettivo}) -> {tipo} (fallimenti cons: {fallimenti_cons}/{MAX_FALLIMENTI})")

        chiave_nodo, nodo_bloccato, marcia_tentata, eta_s, fuori_territorio, cooldown_s = _tap_invia_squadra(
            porta, tipo, n_truppe, nome, squadra_n, 1, ciclo,
            logger=logger, blacklist=blacklist, blacklist_lock=blacklist_lock,
            coords=coords,
            cooldown_map=cooldown_tipo_fino,
            livello_target=_livello_ist,
        )

        # Step2: se è stato impostato un cooldown (nodo riproposto), proseguo senza penalità
        if cooldown_s and cooldown_s > 0:
            continue
        if nodo_bloccato:
            if fuori_territorio:
                # Nodo fuori territorio: il CERCA del gioco ripropone sempre
                # il nodo più vicino al rifugio → ritentare lo stesso tipo
                # porterebbe sempre allo stesso nodo fuori territorio.
                # Blocchiamo il tipo per questo ciclo (blacklist già COMMITTED)
                # e passiamo al tipo successivo. NON incrementa fallimenti_cons.
                log(f"Nodo fuori territorio — tipo '{tipo}' bloccato per questo ciclo")
                tipi_bloccati.add(tipo)
            else:
                # Blacklist da navigazione: tutti i nodi del tipo sono occupati
                log(f"Tipo '{tipo}' bloccato da blacklist - squadre successive dello stesso tipo saltate")
                tipi_bloccati.add(tipo)
                fallimenti_cons += 1
            continue

        if not marcia_tentata:
            if chiave_nodo:
                log(f"Marcia NON partita - rollback blacklist nodo {chiave_nodo}")
                _blacklist_rollback(blacklist, blacklist_lock, chiave_nodo)
            fallimenti_cons += 1
            continue

        delay = min(DELAY_POSTMARCIA_BASE, MAX_DELAY_POSTMARCIA)
        time.sleep(delay)

        # BACK meno aggressivi: 3 back
        s_post, _ = stato.back_rapidi_e_stato(porta, n=3, logger=logger, nome=nome)
        if s_post == "home":
            log("Post-BACK: in home - torno in mappa")
            if not stato.vai_in_mappa(porta, nome, logger):
                log("Impossibile tornare in mappa - abbandono istanza")
                return inviate
        elif s_post not in ("mappa", "home"):
            log(f"Post-BACK: stato '{s_post}' inatteso - reset")
            _reset_stato(porta, nome, "", squadra_n, 1, ciclo, logger)

        # Attesa stabilizzazione UI mappa prima di leggere il contatore.
        # Dopo i BACK la mappa può impiegare 1-2s a renderizzare completamente
        # il widget squadre — senza questo sleep l'OCR legge spesso -1.
        time.sleep(1.5)

        attive_dopo = _leggi_attive_con_retry(porta, nome, logger=logger, retry=3, sleep_s=1.5)

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
            inviate += 1
            fallimenti_cons = 0
            continue

        log(f"Contatore invariato dopo MARCIA: attive={attive_dopo} (era {attive_correnti}) - rileggo tra 3s")
        time.sleep(3.0)
        attive_dopo2 = _leggi_attive_con_retry(porta, nome, logger=logger, retry=2, sleep_s=1.0)

        if attive_dopo2 != -1 and attive_dopo2 > attive_correnti:
            log(f"Squadra confermata dopo retry ({attive_correnti} -> {attive_dopo2})")
            if chiave_nodo:
                _blacklist_commit(blacklist, blacklist_lock, chiave_nodo, eta_s=eta_s)
                ttl_log = f"ETA={eta_s}s" if eta_s else f"TTL={BLACKLIST_COMMITTED_TTL}s"
                log(f"Nodo {chiave_nodo} -> COMMITTED ({ttl_log})")
            attive_correnti = attive_dopo2
            inviate += 1
            fallimenti_cons = 0
            continue

        log("Squadra respinta o marcia non partita - rollback nodo")
        if chiave_nodo:
            _blacklist_rollback(blacklist, blacklist_lock, chiave_nodo)
        fallimenti_cons += 1

    stato.vai_in_home(porta, nome, logger)

    # --- Verifica contatore reale e recupero slot liberi ---
    # Il contatore interno (attive_correnti) può essere impreciso se l'OCR
    # ha fallito ad inizio ciclo (caso "assumo 0/N"). Rileggiamo il valore
    # reale e, se ci sono slot liberi, mandiamo altri raccoglitori.
    # Questo recupero vale anche se tutti i tipi pianificati erano bloccati:
    # nel loop principale abbiamo già provato i tipi alternativi, ma se
    # il contatore era sbagliato potremmo avere slot liberi non sfruttati.
    attive_reali = attive_correnti
    early_exit_slot_pieni = False  # Step1: evita coda home↔mappa quando slot sono già pieni
    if fallimenti_cons < MAX_FALLIMENTI:
        try:
            if stato.vai_in_mappa(porta, nome, logger):
                time.sleep(1.5)
                attive_lette, _, libere_lette = stato.conta_squadre(porta, n_letture=3)
                if attive_lette != -1:
                    attive_reali = attive_lette
                    if libere_lette > 0:
                        log(f"Contatore reale: {attive_reali}/{obiettivo} — {libere_lette} slot liberi, riprendo")
                        attive_correnti = attive_reali
                        # Costruisce sequenza fresca per il recupero con tutti i tipi disponibili
                        # (esclude solo quelli confermati bloccati in questo ciclo)
                        tipi_recupero = [t for t in _tutti_i_tipi if t not in tipi_bloccati]
                        if not tipi_recupero:
                            tipi_recupero = list(_tutti_i_tipi)  # reset totale se tutto bloccato
                        seq_recupero = (tipi_recupero * (libere_lette + 3))[:libere_lette * 3 + 3]
                        idx_rec = 0
                        while attive_correnti < obiettivo and idx_rec < len(seq_recupero):
                            # Step2A: se tutti i tipi di recupero sono in cooldown, attendo fino al primo cooldown che scade
                            tipi_rec = [t for t in seq_recupero[idx_rec:] if t not in tipi_bloccati]
                            if tipi_rec:
                                now = time.time()
                                pronti = [t for t in tipi_rec if cooldown_tipo_fino.get(t, 0) <= now]
                                if not pronti:
                                    t_min = min(cooldown_tipo_fino.get(t, now + BLACKLIST_ATTESA_NODO) for t in tipi_rec)
                                    wait_s = int(max(1, min(BLACKLIST_ATTESA_NODO, t_min - now)))
                                    log(f"Recupero: tutti i tipi in cooldown — attendo {wait_s}s")
                                    stato.back_rapidi_e_stato(porta, n=3, logger=logger, nome=nome)
                                    time.sleep(wait_s)
                                    continue
                            tipo = seq_recupero[idx_rec]
                            idx_rec += 1
                            # Step2: se il tipo è in cooldown, salto e provo il prossimo
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
                                coords=coords,
                                cooldown_map=cooldown_tipo_fino,
                                livello_target=_livello_ist,
                            )
                            # Step2: se è stato impostato un cooldown (nodo riproposto), proseguo senza penalità
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
                            attive_dopo = _leggi_attive_con_retry(porta, nome, logger=logger, retry=3, sleep_s=1.5)
                            if attive_dopo != -1 and attive_dopo > attive_correnti:
                                log(f"Squadra confermata nel recupero ({attive_correnti} -> {attive_dopo})")
                                if chiave_nodo:
                                    _blacklist_commit(blacklist, blacklist_lock, chiave_nodo, eta_s=eta_s)
                                attive_correnti = attive_dopo
                                inviate += 1
                                fallimenti_cons = 0
                            else:
                                if chiave_nodo:
                                    _blacklist_rollback(blacklist, blacklist_lock, chiave_nodo)
                                fallimenti_cons += 1
                        stato.vai_in_home(porta, nome, logger)
                    else:
                        log(f"Contatore reale: {attive_reali}/{obiettivo} — slot pieni")
                        # Step1: slot pieni → evita ulteriori transizioni home↔mappa (risparmio ~30s/istanza)
                        early_exit_slot_pieni = True
                        attive_correnti = attive_reali
        except Exception as _ex:
            log(f"Verifica contatore reale fallita (non bloccante): {_ex}")

    # Step1: se slot pieni già confermati, evita ulteriori transizioni mappa/home
    if not early_exit_slot_pieni:

        # Rileggi contatore per il log finale
        try:
            if stato.vai_in_mappa(porta, nome, logger):
                time.sleep(1.5)
                attive_lette2, _, _ = stato.conta_squadre(porta, n_letture=3)
                if attive_lette2 != -1:
                    attive_reali = attive_lette2
                stato.vai_in_home(porta, nome, logger)
        except Exception:
            pass

    log(f"Raccolta completata - {inviate}/{obiettivo - attive_inizio} squadre inviate (attive finali={attive_reali}/{obiettivo})")
    _log.registra_evento(ciclo, nome, "completata", dettaglio=f"inviate={inviate} attive_finali={attive_reali}/{obiettivo}")

    # Snapshot fine ciclo — necessario per calcolo produzione netta in status.py
    try:
        screen_fine = adb.screenshot(porta)
        risorse_fine = ocr.leggi_risorse(screen_fine) if screen_fine else {}
        if all(risorse_fine.get(r, -1) < 0 for r in ("pomodoro", "legno")):
            time.sleep(2.0)
            screen_fine = adb.screenshot(porta)
            risorse_fine = ocr.leggi_risorse(screen_fine) if screen_fine else {}
        pom_f = risorse_fine.get("pomodoro", -1)
        leg_f = risorse_fine.get("legno",    -1)
        acc_f = risorse_fine.get("acciaio",  -1)
        pet_f = risorse_fine.get("petrolio", -1)
        dia_f = risorse_fine.get("diamanti", -1)
        _status.istanza_risorse_fine(nome, pom_f, leg_f, acc_f, pet_f)
        if dia_f >= 0:
            _status.istanza_diamanti(nome, dia_f)
        def _fmt2(v): return f"{v/1_000_000:.1f}M" if v >= 0 else "—"
        fin_log = (f"🍅 {_fmt2(pom_f)}  🪵 {_fmt2(leg_f)}"
                   + (f"  ⚙ {_fmt2(acc_f)}"  if acc_f >= 0 else "")
                   + (f"  🛢 {_fmt2(pet_f)}" if pet_f >= 0 else "")
                   + (f"  💎 {int(dia_f)}"   if dia_f >= 0 else ""))
        log(f"Deposito fine ciclo: {fin_log}")
    except Exception as _e:
        log(f"Snapshot risorse fine ciclo fallito (non bloccante): {_e}")

    return inviate
