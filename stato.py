# ==============================================================================
# DOOMSDAY BOT V5 - stato.py
# Rilevamento stato istanza: home / mappa / overlay / sconosciuto
#
# v5.24 — Pipeline in-memoria: rileva() usa exec-out + decode unico.
#         Funzioni originali (rileva_screen, _match_toggle_template, ecc.)
#         intatte per backward compatibility.
#
# POTENZIAMENTO:
# - Secondo sensore basato sul bottone toggle basso-sinistra (OCR Region/Shelter).
# - Log diagnostico opzionale quando il sensore toggle override la decisione base.
# - Contatore override PER ISTANZA (nome+porta) thread-safe.
# ==============================================================================

import os
import time
import threading
from collections import defaultdict
import adb
import config

# --- Parametri BACK rapidi ---
N_BACK = 5
DELAY_BACK = 0.3
DELAY_POST_BACK = 0.5

# --- Massimo cicli di BACK per uscire da overlay persistente ---
MAX_CICLI_BACK = 4

# --- Massimo tentativi tap per vai_in_mappa ---
MAX_TENTATIVI_MAPPA = 3

# --- Contatore override del sensore toggle (per istanza) ---
_TOGGLE_OVERRIDE_LOCK = threading.Lock()
_TOGGLE_OVERRIDE_COUNT = defaultdict(int)  # key: (nome, porta_str) -> int


def _key_istanza(nome=None, porta=None):
    return (str(nome or ''), str(porta or ''))


def get_toggle_override_count(nome=None, porta=None) -> int:
    """Ritorna il numero di override.

    - Se nome+porta forniti: contatore per quella istanza.
    - Se non forniti: somma totale di tutte le istanze.
    """
    with _TOGGLE_OVERRIDE_LOCK:
        if nome is None and porta is None:
            return int(sum(_TOGGLE_OVERRIDE_COUNT.values()))
        return int(_TOGGLE_OVERRIDE_COUNT.get(_key_istanza(nome, porta), 0))


def reset_toggle_override_count(nome=None, porta=None) -> None:
    """Reset contatore override.

    - Se nome+porta forniti: reset solo per quella istanza.
    - Se non forniti: reset totale.
    """
    with _TOGGLE_OVERRIDE_LOCK:
        if nome is None and porta is None:
            _TOGGLE_OVERRIDE_COUNT.clear()
        else:
            _TOGGLE_OVERRIDE_COUNT[_key_istanza(nome, porta)] = 0


# ------------------------------------------------------------------------------
# Helpers toggle basso-sinistra (secondo sensore)
# Dual-mode: template matching (priorità) + OCR (fallback)
# Controllato da config.py:
#   STATO_TOGGLE_TEMPLATE_ABILITATO = True  → usa template matching
#   STATO_TOGGLE_OCR_ABILITATO      = True  → usa OCR come fallback
# ------------------------------------------------------------------------------

# Cache template cv2 (lazy)
_tmpl_region_cv  = None
_tmpl_shelter_cv = None


def _carica_toggle_templates() -> bool:
    """Carica pin_region.png e pin_shelter.png in memoria.
    Ritorna True se ok."""
    global _tmpl_region_cv, _tmpl_shelter_cv
    try:
        import cv2
        import os
        tdir = os.path.join(config.BOT_DIR, "templates")
        if _tmpl_region_cv is None:
            t = cv2.imread(os.path.join(tdir, "pin_region.png"))
            if t is None:
                return False
            _tmpl_region_cv = t
        if _tmpl_shelter_cv is None:
            t = cv2.imread(os.path.join(tdir, "pin_shelter.png"))
            if t is None:
                return False
            _tmpl_shelter_cv = t
        return True
    except Exception:
        return False


# --- Template matching su file (ORIGINALE — backward compat) ---

def _match_toggle_template(screen_path: str) -> tuple:
    """
    Template matching su ROI basso-sinistra (0,450,120,540).
    Ritorna (stato, descrizione) oppure ('', msg_errore).
    Soglia validata su dati reali: match=0.993, cross=0.30 → soglia=0.80.
    """
    import cv2
    soglia  = getattr(config, 'STATO_TOGGLE_TEMPLATE_SOGLIA', 0.80)
    x1, y1, x2, y2 = getattr(config, 'STATO_TOGGLE_ROI', (0, 450, 120, 540))

    if not _carica_toggle_templates():
        return ('', 'template non caricati')

    img = cv2.imread(screen_path)
    if img is None:
        return ('', 'screenshot non leggibile')

    h_img, w_img = img.shape[:2]
    if w_img != 960 or h_img != 540:
        sx = w_img / 960.0; sy = h_img / 540.0
        x1, y1 = int(x1*sx), int(y1*sy)
        x2, y2 = int(x2*sx), int(y2*sy)

    roi = img[y1:y2, x1:x2]
    if roi.size == 0:
        return ('', 'ROI vuota')

    _, sr, _, _ = cv2.minMaxLoc(cv2.matchTemplate(roi, _tmpl_region_cv,  cv2.TM_CCOEFF_NORMED))
    _, ss, _, _ = cv2.minMaxLoc(cv2.matchTemplate(roi, _tmpl_shelter_cv, cv2.TM_CCOEFF_NORMED))

    if sr >= soglia and sr >= ss:
        return ('home',  f'region={sr:.3f}')
    if ss >= soglia and ss > sr:
        return ('mappa', f'shelter={ss:.3f}')
    return ('overlay', f'sotto soglia: region={sr:.3f} shelter={ss:.3f}')


# --- Template matching IN MEMORIA (NUOVA — usata da rileva()) ---

def _match_toggle_template_mem(cv_img) -> tuple:
    """
    Come _match_toggle_template() ma riceve l'immagine cv2 già decodificata.
    Elimina cv2.imread() — il costo maggiore dopo lo screencap.
    Ritorna (stato, descrizione) oppure ('', msg_errore).
    """
    import cv2

    if cv_img is None:
        return ('', 'cv_img None')

    soglia = getattr(config, 'STATO_TOGGLE_TEMPLATE_SOGLIA', 0.80)
    x1, y1, x2, y2 = getattr(config, 'STATO_TOGGLE_ROI', (0, 450, 120, 540))

    if not _carica_toggle_templates():
        return ('', 'template non caricati')

    h_img, w_img = cv_img.shape[:2]
    if w_img != 960 or h_img != 540:
        sx = w_img / 960.0
        sy = h_img / 540.0
        x1, y1 = int(x1 * sx), int(y1 * sy)
        x2, y2 = int(x2 * sx), int(y2 * sy)

    roi = cv_img[y1:y2, x1:x2]
    if roi.size == 0:
        return ('', 'ROI vuota')

    _, sr, _, _ = cv2.minMaxLoc(
        cv2.matchTemplate(roi, _tmpl_region_cv, cv2.TM_CCOEFF_NORMED)
    )
    _, ss, _, _ = cv2.minMaxLoc(
        cv2.matchTemplate(roi, _tmpl_shelter_cv, cv2.TM_CCOEFF_NORMED)
    )

    if sr >= soglia and sr >= ss:
        return ('home', f'region={sr:.3f}')
    if ss >= soglia and ss > sr:
        return ('mappa', f'shelter={ss:.3f}')
    return ('overlay', f'sotto soglia: region={sr:.3f} shelter={ss:.3f}')


def _scale_box(box, w, h, base_w=960, base_h=540):
    x1, y1, x2, y2 = box
    sx = w / float(base_w)
    sy = h / float(base_h)
    return (int(x1*sx), int(y1*sy), int(x2*sx), int(y2*sy))


def _ocr_testo_toggle(screen_path: str) -> str:
    """OCR normalizzato della label toggle basso-sinistra (fallback)."""
    if not getattr(config, 'STATO_TOGGLE_OCR_ABILITATO', True):
        return ''
    try:
        from PIL import Image, ImageOps
        import pytesseract

        if getattr(config, 'TESSERACT_EXE', ''):
            pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_EXE

        img = Image.open(screen_path)
        W, H = img.size
        box = getattr(config, 'STATO_TOGGLE_LABEL_ZONA', (0, 396, 228, 540))
        x1, y1, x2, y2 = _scale_box(box, W, H)
        x1 = max(0, min(W-1, x1)); x2 = max(1, min(W, x2))
        y1 = max(0, min(H-1, y1)); y2 = max(1, min(H, y2))
        roi = img.crop((x1, y1, x2, y2))

        gray = ImageOps.grayscale(roi)
        gray = ImageOps.autocontrast(gray)
        bw = gray.point(lambda p: 255 if p > 160 else 0)

        psm = int(getattr(config, 'STATO_TOGGLE_OCR_PSM', 7))
        tcfg = f"--psm {psm} -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
        text = pytesseract.image_to_string(bw, config=tcfg) or ''
        return ''.join(ch for ch in text.upper() if ch.isalpha())
    except Exception:
        return ''


# --- Sensore toggle su file (ORIGINALE — backward compat) ---

def _sensore_toggle(screen_path: str) -> tuple:
    """
    Deduce stato home/mappa dal pulsante toggle basso-sinistra.
    Dual-mode: template matching (priorità) → OCR (fallback).
    Ritorna (stato, descrizione).
    """
    use_template = getattr(config, 'STATO_TOGGLE_TEMPLATE_ABILITATO', True)
    use_ocr      = getattr(config, 'STATO_TOGGLE_OCR_ABILITATO',      True)
    debug        = config._debug_abilitato(config.DEBUG_STATO)

    # ── 1. Template matching ──
    if use_template:
        stato_t, desc_t = _match_toggle_template(screen_path)
        if stato_t in ('home', 'mappa'):
            if debug:
                try: print(f"[STATO][TOGGLE][TMPL] {stato_t} ({desc_t})")
                except Exception: pass
            return (stato_t, desc_t)
        if debug:
            try: print(f"[STATO][TOGGLE][TMPL] nessun match ({desc_t})")
            except Exception: pass

    # ── 2. OCR fallback ──
    if use_ocr:
        txt = _ocr_testo_toggle(screen_path)
        if txt:
            key_home = getattr(config, 'STATO_TOGGLE_KEY_HOME',  ['REGION',  'REGIONE'])
            key_map  = getattr(config, 'STATO_TOGGLE_KEY_MAPPA', ['SHELTER', 'RIFUGIO'])
            for k in key_home:
                if k and k.upper().replace(' ', '') in txt:
                    if debug:
                        try: print(f"[STATO][TOGGLE][OCR] home (ocr='{txt}')")
                        except Exception: pass
                    return ('home', txt)
            for k in key_map:
                if k and k.upper().replace(' ', '') in txt:
                    if debug:
                        try: print(f"[STATO][TOGGLE][OCR] mappa (ocr='{txt}')")
                        except Exception: pass
                    return ('mappa', txt)

    return ('', '')


# --- Sensore toggle IN MEMORIA (NUOVA — usata da rileva()) ---

def _sensore_toggle_mem(pil_img, cv_img) -> tuple:
    """
    Come _sensore_toggle() ma lavora interamente in memoria.
    Ordine: template matching (cv_img) → OCR fallback (pil_img, salva temp).
    """
    use_template = getattr(config, 'STATO_TOGGLE_TEMPLATE_ABILITATO', True)
    use_ocr = getattr(config, 'STATO_TOGGLE_OCR_ABILITATO', True)
    debug = config._debug_abilitato(config.DEBUG_STATO)

    # ── 1. Template matching in memoria ──
    if use_template and cv_img is not None:
        stato_t, desc_t = _match_toggle_template_mem(cv_img)
        if stato_t in ('home', 'mappa'):
            if debug:
                try: print(f"[STATO][TOGGLE][TMPL-MEM] {stato_t} ({desc_t})")
                except Exception: pass
            return (stato_t, desc_t)
        if stato_t == 'overlay':
            return (stato_t, desc_t)
        if debug:
            try: print(f"[STATO][TOGGLE][TMPL-MEM] nessun match ({desc_t})")
            except Exception: pass

    # ── 2. OCR fallback — Tesseract richiede file su disco ──
    # Salviamo temp SOLO se template matching ha fallito per errore tecnico
    # (cv_img None, template non caricati). Se 'overlay' (sotto soglia)
    # l'OCR non aggiunge valore — l'icona toggle non è visibile.
    if use_ocr and pil_img is not None:
        try:
            temp_dir  = os.path.join(config.DEBUG_DIR, "screen")
            os.makedirs(temp_dir, exist_ok=True)
            temp_path = os.path.join(temp_dir, "_stato_ocr_tmp.png")
            pil_img.save(temp_path)
            txt = _ocr_testo_toggle(temp_path)
            if txt:
                key_home = getattr(config, 'STATO_TOGGLE_KEY_HOME', ['REGION', 'REGIONE'])
                key_map = getattr(config, 'STATO_TOGGLE_KEY_MAPPA', ['SHELTER', 'RIFUGIO'])
                for k in key_home:
                    if k and k.upper().replace(' ', '') in txt:
                        return ('home', txt)
                for k in key_map:
                    if k and k.upper().replace(' ', '') in txt:
                        return ('mappa', txt)
        except Exception:
            pass

    return ('', '')


# ------------------------------------------------------------------------------
# Rileva stato da screen già scattato (file su disco)
# (ORIGINALE — usato da chi passa screen_path: raccolta, emulatore_base, ecc.)
# ------------------------------------------------------------------------------

def rileva_screen(screen: str, porta=None, nome=None) -> str:
    """Rileva stato da screen già scattato.

    Parametri opzionali (per diagnostica/contatori):
    - porta: porta adb dell'istanza
    - nome: nome istanza

    Stati possibili:
    - 'home'
    - 'mappa'
    - 'overlay'
    - 'sconosciuto'
    """
    if not screen:
        return 'sconosciuto'

    def _px(x: int, y: int):
        return adb.leggi_pixel(screen, x, y)

    # 1) Popup "Uscire dal gioco?" (overlay)
    r0, g0, b0 = _px(config.POPUP_CHECK_X, config.POPUP_CHECK_Y)
    if r0 != -1:
        is_beige = (
            config.BEIGE_R_MIN <= r0 <= config.BEIGE_R_MAX and
            config.BEIGE_G_MIN <= g0 <= config.BEIGE_G_MAX and
            config.BEIGE_B_MIN <= b0 <= config.BEIGE_B_MAX
        )
        rok, gok, bok = _px(config.POPUP_OK_X, config.POPUP_OK_Y)
        is_ok_yellow = (
            rok != -1 and
            config.POPUP_OK_R_MIN <= rok <= config.POPUP_OK_R_MAX and
            config.POPUP_OK_G_MIN <= gok <= config.POPUP_OK_G_MAX and
            config.POPUP_OK_B_MIN <= bok <= config.POPUP_OK_B_MAX
        )
        if is_beige and is_ok_yellow:
            return 'overlay'

    # 2) Template matching (sensore primario)
    s_tmpl, desc_tmpl = _sensore_toggle(screen)

    if s_tmpl in ('home', 'mappa'):
        if config._debug_abilitato(config.DEBUG_STATO):
            try:
                print(f"[STATO][TOGGLE] {nome or '?'}:{porta or '?'} → {s_tmpl} ({desc_tmpl})")
            except Exception:
                pass
        return s_tmpl

    if s_tmpl == 'overlay':
        return 'overlay'

    # 3) Fallback pixel check (solo se cv2/template non disponibili)
    offsets = getattr(config, 'STATO_CHECK_OFFSETS', [(0, 0)])
    soglia_r = config.STATO_SOGLIA_R
    min_sum = getattr(config, 'STATO_MIN_MAPPA_RGB_SUM', 20)

    home_votes = 0
    mappa_votes = 0
    valid = 0

    for dx, dy in offsets:
        r, g, b = _px(config.STATO_CHECK_X + dx, config.STATO_CHECK_Y + dy)
        if r == -1:
            continue
        valid += 1
        if (r + g + b) < min_sum:
            continue
        if r < soglia_r:
            home_votes += 1
        else:
            mappa_votes += 1

    if valid == 0:
        return 'sconosciuto'
    if home_votes > mappa_votes and home_votes > 0:
        return 'home'
    if mappa_votes >= home_votes and mappa_votes > 0:
        return 'mappa'
    return 'overlay'


# ------------------------------------------------------------------------------
# Rileva stato da immagini IN MEMORIA
# (NUOVA — usata internamente da rileva())
# ------------------------------------------------------------------------------

def rileva_screen_mem(pil_img, cv_img, porta=None, nome=None) -> str:
    """
    Rileva stato da immagini già decodificate in memoria.
    Stessa logica di rileva_screen() ma senza I/O disco.

    Parametri:
      pil_img : PIL.Image — per pixel check (popup, fallback stato)
      cv_img  : numpy array cv2 — per template matching (può essere None)
    """
    if pil_img is None:
        return 'sconosciuto'

    def _px(x, y):
        return adb.leggi_pixel_img(pil_img, x, y)

    # 1) Popup "Uscire dal gioco?" (overlay)
    r0, g0, b0 = _px(config.POPUP_CHECK_X, config.POPUP_CHECK_Y)
    if r0 != -1:
        is_beige = (
            config.BEIGE_R_MIN <= r0 <= config.BEIGE_R_MAX and
            config.BEIGE_G_MIN <= g0 <= config.BEIGE_G_MAX and
            config.BEIGE_B_MIN <= b0 <= config.BEIGE_B_MAX
        )
        rok, gok, bok = _px(config.POPUP_OK_X, config.POPUP_OK_Y)
        is_ok_yellow = (
            rok != -1 and
            config.POPUP_OK_R_MIN <= rok <= config.POPUP_OK_R_MAX and
            config.POPUP_OK_G_MIN <= gok <= config.POPUP_OK_G_MAX and
            config.POPUP_OK_B_MIN <= bok <= config.POPUP_OK_B_MAX
        )
        if is_beige and is_ok_yellow:
            return 'overlay'

    # 2) Template matching in memoria (sensore primario)
    s_tmpl, desc_tmpl = _sensore_toggle_mem(pil_img, cv_img)

    if s_tmpl in ('home', 'mappa'):
        if config._debug_abilitato(config.DEBUG_STATO):
            try:
                print(f"[STATO][TOGGLE-MEM] {nome or '?'}:{porta or '?'} → {s_tmpl} ({desc_tmpl})")
            except Exception:
                pass
        return s_tmpl

    if s_tmpl == 'overlay':
        return 'overlay'

    # 3) Fallback pixel check
    offsets = getattr(config, 'STATO_CHECK_OFFSETS', [(0, 0)])
    soglia_r = config.STATO_SOGLIA_R
    min_sum = getattr(config, 'STATO_MIN_MAPPA_RGB_SUM', 20)

    home_votes = 0
    mappa_votes = 0
    valid = 0

    for dx, dy in offsets:
        r, g, b = _px(config.STATO_CHECK_X + dx, config.STATO_CHECK_Y + dy)
        if r == -1:
            continue
        valid += 1
        if (r + g + b) < min_sum:
            continue
        if r < soglia_r:
            home_votes += 1
        else:
            mappa_votes += 1

    if valid == 0:
        return 'sconosciuto'
    if home_votes > mappa_votes and home_votes > 0:
        return 'home'
    if mappa_votes >= home_votes and mappa_votes > 0:
        return 'mappa'
    return 'overlay'


# ------------------------------------------------------------------------------
# Debug screenshot
# ------------------------------------------------------------------------------

def _salva_debug_stato(screen_path: str, stato: str, porta=None, nome=None):
    """
    Se DEBUG_ABILITATO=True e DEBUG_STATO=True, copia lo screenshot in
    debug/stato/ con nome {HHMMSSmmm}_{nome}_{porta}_{stato}.png
    """
    if not config._debug_abilitato(config.DEBUG_STATO):
        return
    if not screen_path or not os.path.exists(screen_path):
        return
    try:
        import shutil
        from datetime import datetime
        debug_dir = os.path.join(config.DEBUG_DIR, "stato")
        os.makedirs(debug_dir, exist_ok=True)
        ts = datetime.now().strftime("%H%M%S%f")[:9]
        label = f"{nome or 'x'}_{porta or 'x'}"
        dest = os.path.join(debug_dir, f"{ts}_{label}_{stato}.png")
        shutil.copy2(screen_path, dest)
    except Exception:
        pass


# ------------------------------------------------------------------------------
# Rileva stato — VERSIONE OTTIMIZZATA (exec-out + decode unico)
#
# Pipeline:
#   exec-out screencap → bytes RAM → decode unico (PIL+cv2) → rilevamento
#   in-memoria → salva su disco solo per screen_path di ritorno
#
# Fallback automatico: se exec-out fallisce, usa screenshot() tradizionale.
# Retrocompatibilità: ritorna (stato, screen_path) come l'originale.
# ------------------------------------------------------------------------------

def rileva(porta: str, nome: str = None) -> tuple:
    """Scatta screenshot e rileva stato. Ritorna (stato, screen_path)."""

    # ── 1. Screenshot in memoria via exec-out ──
    png_bytes = adb.screenshot_bytes(porta)

    if not png_bytes:
        # Fallback: metodo tradizionale (file) se exec-out fallisce
        screen = adb.screenshot(porta)
        if not screen:
            return ('sconosciuto', '')
        s = rileva_screen(screen, porta=porta, nome=nome)
        _salva_debug_stato(screen, s, porta=porta, nome=nome)
        return (s, screen)

    # ── 2. Decode unico (PIL + cv2 dallo stesso buffer) ──
    pil_img, cv_img = adb.decodifica_screenshot(png_bytes)

    if pil_img is None:
        return ('sconosciuto', '')

    # ── 3. Rilevamento in memoria (zero I/O disco) ──
    s = rileva_screen_mem(pil_img, cv_img, porta=porta, nome=nome)

    # ── 4. Salva su disco per screen_path di ritorno ──
    # Serve a: home_pulita(), verifica_ui, debug, e chiunque usi il path
    screen_path = adb.salva_screenshot(png_bytes, porta)

    # ── 5. Debug screenshot ──
    _salva_debug_stato(screen_path, s, porta=porta, nome=nome)

    return (s, screen_path)


# ------------------------------------------------------------------------------
# Invia N BACK rapidi e legge lo stato risultante
# ------------------------------------------------------------------------------

def back_rapidi_e_stato(porta: str, n: int = N_BACK, logger=None, nome: str = '') -> tuple:
    """Invia n BACK a intervalli DELAY_BACK, poi legge lo stato."""

    def log(msg):
        if logger:
            logger(nome, msg)

    for _ in range(n):
        adb.keyevent(porta, 'KEYCODE_BACK')
        time.sleep(DELAY_BACK)

    time.sleep(DELAY_POST_BACK)
    s, screen = rileva(porta, nome=nome)

    if s == 'overlay':
        adb.keyevent(porta, 'KEYCODE_BACK')
        time.sleep(0.8)
        s2, screen2 = rileva(porta, nome=nome)
        if s2 in ('home', 'mappa'):
            s, screen = s2, screen2

    log(f"Stato dopo {n} BACK: {s}")
    return (s, screen)


def _pulisci_overlay(porta: str, nome: str, logger=None) -> str:
    """Cicli di BACK finché stato è home o mappa."""

    def log(msg):
        if logger:
            logger(nome, msg)

    for ciclo in range(MAX_CICLI_BACK):
        s, _ = back_rapidi_e_stato(porta, N_BACK, logger, nome)
        if s in ('home', 'mappa'):
            return s
        log(f"Overlay persistente (ciclo {ciclo+1}/{MAX_CICLI_BACK}) - altro ciclo BACK")

    log(f"Impossibile uscire da overlay dopo {MAX_CICLI_BACK} cicli")
    return 'fallito'


# ------------------------------------------------------------------------------
# Rilevamento e pulizia banner home
# ------------------------------------------------------------------------------

_BANNER_TOGGLE_ZONA = (0, 450, 120, 540)
_BANNER_LUM_SOGLIA  = 40
_BANNER_MAX_BACK    = 5
_BANNER_MAX_CICLI   = 3


def home_pulita(screen_path: str) -> bool:
    """
    Verifica se la home è priva di banner controllando la luminosità
    della zona toggle basso-sinistra.
    Ritorna True se home pulita, False se banner presente.
    In caso di errore ritorna True (fail-safe).
    """
    try:
        import numpy as np
        from PIL import Image
        img = Image.open(screen_path)
        arr = np.array(img)
        x1, y1, x2, y2 = _BANNER_TOGGLE_ZONA
        zona = arr[y1:y2, x1:x2].astype(float)
        return float(zona.mean()) >= _BANNER_LUM_SOGLIA
    except Exception:
        return True  # fail-safe


def pulisci_banner_home(porta: str, nome: str, logger=None) -> bool:
    """
    Chiude eventuali banner/overlay di evento sulla home inviando BACK ripetuti.
    Verifica dopo ogni ciclo la luminosità della zona toggle.
    Ritorna True se home pulita raggiunta, False se banner persistente.
    """
    def log(msg):
        if logger:
            logger(nome, msg)

    screen = adb.screenshot(porta)
    if not screen:
        return True  # fail-safe

    if home_pulita(screen):
        return True

    log("[BANNER] banner/overlay rilevato — avvio pulizia con BACK")

    for ciclo in range(1, _BANNER_MAX_CICLI + 1):
        for _ in range(_BANNER_MAX_BACK):
            adb.keyevent(porta, 'KEYCODE_BACK')
            time.sleep(0.4)

        time.sleep(0.8)
        screen = adb.screenshot(porta)
        if not screen:
            continue

        if home_pulita(screen):
            log(f"[BANNER] home pulita dopo ciclo {ciclo} — OK")
            return True

        log(f"[BANNER] banner ancora presente (ciclo {ciclo}/{_BANNER_MAX_CICLI}) — altro ciclo")

    log(f"[BANNER] ANOMALIA: banner persistente dopo {_BANNER_MAX_CICLI} cicli")
    return False


# ------------------------------------------------------------------------------
# Navigazione: vai in mappa / vai in home
# ------------------------------------------------------------------------------

def vai_in_mappa(porta: str, nome: str, logger=None) -> bool:
    """Porta l'istanza in mappa. Prima pulisce overlay e banner, poi naviga."""

    def log(msg):
        if logger:
            logger(nome, msg)

    s, screen = rileva(porta, nome=nome)
    log(f"Stato attuale: {s}")

    if s not in ('home', 'mappa'):
        s = _pulisci_overlay(porta, nome, logger)
        if s == 'fallito':
            log('Impossibile raggiungere stato pulito - abbandono')
            return False

    if s == 'mappa':
        log('Già in mappa')
        time.sleep(1.5)
        return True

    # Pulizia banner prima dei tap
    if screen and not home_pulita(screen):
        log("Stato attuale: home con banner — pulizia banner prima dei tap")
        pulisci_banner_home(porta, nome, logger)

    delays_post_tap = [3.0, 4.0, 5.0]
    tap_falliti_consecutivi = 0

    for tentativo in range(MAX_TENTATIVI_MAPPA):
        delay = delays_post_tap[min(tentativo, len(delays_post_tap) - 1)]
        label = 'primo' if tentativo == 0 else f"tentativo {tentativo+1}"
        log(f"Tap mappa ({label}, attesa {delay:.0f}s)...")
        adb.tap(porta, getattr(config, 'TAP_TOGGLE_HOME_MAPPA', (38, 505)), delay_ms=0)
        time.sleep(delay)
        s_dopo, screen_dopo = rileva(porta, nome=nome)
        log(f"Stato dopo tap: {s_dopo}")

        if s_dopo == 'mappa':
            time.sleep(1.5)
            return True

        if s_dopo not in ('home', 'mappa'):
            log(f"Overlay '{s_dopo}' dopo tap - pulisco")
            s_dopo = _pulisci_overlay(porta, nome, logger)
            if s_dopo == 'fallito':
                log('Overlay persistente dopo tap - abbandono')
                return False
            if s_dopo == 'mappa':
                time.sleep(1.5)
                return True

        tap_falliti_consecutivi += 1
        if tap_falliti_consecutivi >= 2 and tentativo < MAX_TENTATIVI_MAPPA - 1:
            log("[BANNER] tap mappa non efficaci — possibile banner, avvio pulizia")
            if screen_dopo and not home_pulita(screen_dopo):
                pulisci_banner_home(porta, nome, logger)
                tap_falliti_consecutivi = 0
            else:
                log("[BANNER] home luminosa — banner non rilevato, continuo")

        if tentativo < MAX_TENTATIVI_MAPPA - 1:
            log(f"Ancora in home - riprovo (tentativo {tentativo+2}/{MAX_TENTATIVI_MAPPA})")

    log(f"Impossibile raggiungere mappa dopo {MAX_TENTATIVI_MAPPA} tap - abbandono")
    return False


def vai_in_home(porta: str, nome: str, logger=None, conferme: int = 3) -> bool:
    """Porta l'istanza in home. Pulisce overlay e verifica N conferme consecutive."""

    def log(msg):
        if logger:
            logger(nome, msg)

    s, _ = rileva(porta, nome=nome)
    log(f"Stato attuale: {s}")

    if s not in ('home', 'mappa'):
        s = _pulisci_overlay(porta, nome, logger)
        if s == 'fallito':
            log('Impossibile uscire da overlay')
            return False

    if s != 'home':
        if s == 'mappa':
            adb.tap(porta, getattr(config, 'TAP_TOGGLE_HOME_MAPPA', (38, 505)), delay_ms=0)
            time.sleep(3.0)
        else:
            adb.keyevent(porta, 'KEYCODE_BACK')
            time.sleep(2.0)

    consecutive = 0
    for _ in range(conferme * 4):
        s, _ = rileva(porta, nome=nome)
        if s == 'home':
            consecutive += 1
            if consecutive >= conferme:
                log(f"In home confermato ({conferme}x)")
                return True
            time.sleep(0.5)
        elif s in ('mappa',):
            consecutive = 0
            log(f"Stato {s} - toggle verso home")
            adb.tap(porta, getattr(config, 'TAP_TOGGLE_HOME_MAPPA', (38, 505)), delay_ms=0)
            time.sleep(3.0)
        else:
            consecutive = 0
            log(f"Overlay '{s}' - pulisco")
            s = _pulisci_overlay(porta, nome, logger)
            if s == 'fallito':
                log('Overlay persistente - abbandono')
                return False

    log('Impossibile confermare home')
    return False


def conta_squadre(porta: str, n_letture: int = 3, n_squadre: int = -1) -> tuple:
    """
    Legge contatore squadre X/Y via OCR. Valore più frequente, fallback (-1,-1,-1).

    v5.24 — pipeline in-memoria: screenshot_bytes() + decodifica_screenshot() +
    leggi_contatore_da_zona() — zero scritture disco, zero crop_zona() su file.

    Logica frecce:
      - frecce visibili   → squadre attive → leggi X/Y
      - frecce assenti    → (0, totale_noto) — tutti gli slot liberi
      - totale_noto usato come fallback se totale non leggibile dall'OCR

    Parametri:
      porta      : porta ADB istanza
      n_letture  : numero letture per votazione maggioritaria (default 3)
      n_squadre  : totale slot noto a priori (da config, es. 5) —
                   usato come totale_noto iniziale così (0,-1) diventa (0,5)
    """
    import ocr
    from collections import Counter

    risultati = []
    # Inizializza totale_noto con n_squadre se fornito
    totale_noto = n_squadre if n_squadre > 0 else -1

    for _ in range(n_letture):
        png_bytes = adb.screenshot_bytes(porta)
        if not png_bytes:
            time.sleep(0.3)
            continue

        pil_img, _ = adb.decodifica_screenshot(png_bytes)
        if pil_img is None:
            time.sleep(0.3)
            continue

        attive, totale = ocr.leggi_contatore_da_zona(pil_img, totale_noto=totale_noto)

        if totale > 0:
            totale_noto = totale   # aggiorna per le letture successive

        # Accetta il risultato solo se totale è noto (>0)
        # Scarta (0,-1): frecce assenti ma totale sconosciuto
        if attive != -1 and totale > 0:
            risultati.append((attive, totale))

        time.sleep(0.3)

    if not risultati:
        # Se totale_noto è noto ma tutte le letture avevano frecce assenti
        # → tutti gli slot liberi
        if totale_noto > 0:
            return (0, totale_noto, totale_noto)
        return (-1, -1, -1)

    piu_comune = Counter(risultati).most_common(1)[0][0]
    attive, totale = piu_comune
    libere = max(0, totale - attive)
    return (attive, totale, libere)
