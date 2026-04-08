# ==============================================================================
#  DOOMSDAY BOT V5 - ocr.py
#  OCR con Tesseract per lettura contatore squadre X/4
# ==============================================================================

import pytesseract
from PIL import Image, ImageFilter, ImageEnhance, ImageOps
import re
import threading
import time
import config

# Imposta path Tesseract
pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_EXE

# Lock globale per serializzare le chiamate a Tesseract (thread-safe)
_tesseract_lock = threading.Lock()

# ------------------------------------------------------------------------------
# Preprocessa immagine per migliorare OCR contatore
# ------------------------------------------------------------------------------
def _preprocessa(img: Image.Image) -> Image.Image:
    """Prepara immagine per OCR: taglia icona sx, ingrandisce, soglia."""
    w, h = img.size
    # Taglia ~35% a sinistra per escludere l'icona ▲▼
    taglio = int(w * 0.35)
    img = img.crop((taglio, 0, w, h))
    w, h = img.size
    # Scala di grigi (testo chiaro su sfondo scuro - NON invertire)
    img = img.convert("L")
    # Ingrandisci 4x per Tesseract
    img = img.resize((w * 4, h * 4), Image.LANCZOS)
    # Soglia: testo bianco puro, sfondo nero
    img = img.point(lambda p: 255 if p > 150 else 0)
    return img


# ------------------------------------------------------------------------------
# Leggi testo generico da immagine PIL
# ------------------------------------------------------------------------------
def leggi_testo(img: Image.Image) -> str:
    """Legge testo generico da un crop PIL. Ritorna stringa o '' se fallisce."""
    try:
        w, h = img.size
        img2 = img.resize((w * 3, h * 3), Image.LANCZOS)
        img2 = img2.convert("L")
        img2 = img2.point(lambda p: 255 if p > 100 else 0)
        with _tesseract_lock:
            testo = pytesseract.image_to_string(
                img2,
                config="--psm 6"
            ).strip()
        return testo
    except:
        return ""

# ------------------------------------------------------------------------------
# Leggi contatore squadre da crop immagine
# Ritorna (attive, totale) es. (2, 4) oppure (-1, -1) se fallisce
# ------------------------------------------------------------------------------
def leggi_contatore(crop: Image.Image) -> tuple:
    """Legge il testo X/Y dal crop del contatore squadre."""
    try:
        img = _preprocessa(crop)
        config_tess = "--psm 7 -c tessedit_char_whitelist=0123456789/"
        with _tesseract_lock:
            testo = pytesseract.image_to_string(img, config=config_tess).strip()
        match = re.search(r'(\d+)/(\d+)', testo)
        if match:
            return (int(match.group(1)), int(match.group(2)))
        return (-1, -1)
    except Exception as e:
        return (-1, -1)

# ------------------------------------------------------------------------------
# Leggi contatore squadre dalla zona barra slot (coordinate reali 960x540)
# Zona ricerca frecce ▲▼ : (850, 110, 960, 150) — matchTemplate score 0.989 home+mappa
# Zona testo X/Y intera  : (890, 117, 946, 141) — psm=7 primo tentativo
# Zona cifra sinistra    : (890, 117, 919, 141) — attive, psm=10 fallback
# Zona cifra destra      : (922, 117, 946, 141) — totale, psm=8 fallback
# ------------------------------------------------------------------------------
# ------------------------------------------------------------------------------
# Conta squadre libere (backward compat — usa leggi_contatore su crop)
# ------------------------------------------------------------------------------
def squadre_libere(crop: Image.Image) -> int:
    """Ritorna il numero di squadre libere (totale - attive)."""
    attive, totale = leggi_contatore(crop)
    if attive == -1:
        return -1
    return max(0, totale - attive)


_ZONA_FRECCE_SLOT  = (850, 110, 960, 150)  # zona ricerca frecce ▲▼ — score 0.989 home+mappa
_ZONA_TESTO_SLOT   = (890, 117, 946, 141)  # testo X/Y intero
_ZONA_CIFRA_SX     = (890, 117, 919, 141)  # cifra attive (sinistra slash)
_ZONA_CIFRA_DX     = (922, 117, 946, 141)  # cifra totale (destra slash)
_SOGLIA_FRECCE_TM  = 0.65                  # soglia template matching pin_frecce.png
_tmpl_frecce_cv    = None                  # cache cv2 (lazy)


def _carica_tmpl_frecce() -> bool:
    """Carica pin_frecce.png in memoria (lazy). Ritorna True se ok."""
    global _tmpl_frecce_cv
    if _tmpl_frecce_cv is not None:
        return True
    try:
        import cv2
        import os
        path = os.path.join(config.BOT_DIR, "templates", "pin_frecce.png")
        t = cv2.imread(path)
        if t is None:
            return False
        _tmpl_frecce_cv = t
        return True
    except Exception:
        return False


def _ocr_zona_intera(crop: Image.Image) -> tuple:
    """
    Legge X/Y dalla zona testo intera con psm=7.
    Ritorna (attive, totale) oppure (-1, -1).
    """
    try:
        w, h = crop.size
        crop4x = crop.resize((w * 4, h * 4), Image.LANCZOS)
        mask = _maschera_bianca(crop4x, taglio_sx=0)
        cfg = "--psm 7 -c tessedit_char_whitelist=0123456789/"
        with _tesseract_lock:
            testo = pytesseract.image_to_string(mask, config=cfg).strip()
        m = re.search(r'(\d+)/(\d+)', testo)
        if m:
            return (int(m.group(1)), int(m.group(2)))
        return (-1, -1)
    except Exception:
        return (-1, -1)


def _ocr_cifra_singola(crop: Image.Image, psm: int = 10) -> int:
    """
    Legge una singola cifra con padding 5px + upscale 8x + OTSU.
    Ritorna intero oppure -1.
    """
    import cv2
    import numpy as np
    try:
        w, h = crop.size
        pad = Image.new('RGB', (w + 10, h + 10), (0, 0, 0))
        pad.paste(crop, (5, 5))
        c8 = pad.resize(((w + 10) * 8, (h + 10) * 8), Image.LANCZOS)
        arr = np.array(c8)
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        cfg = f'--psm {psm} -c tessedit_char_whitelist=0123456789'
        with _tesseract_lock:
            testo = pytesseract.image_to_string(Image.fromarray(th), config=cfg).strip()
        m = re.search(r'(\d+)', testo)
        return int(m.group(1)) if m else -1
    except Exception:
        return -1


def leggi_contatore_da_zona(pil_img, totale_noto: int = -1) -> tuple:
    """
    Legge il contatore squadre X/Y dalla pil_img già in memoria.
    Zone calibrate su screen reali 960x540.

    Pipeline:
      1. Template matching pin_frecce.png → se assenti: (0, totale_noto)
      2. OCR zona intera (890,117,946,141) psm=7 → pattern X/Y
      3. Fallback cifre separate: sx psm=10, dx psm=8
      4. Se totale ancora -1 ma totale_noto noto: usa totale_noto

    Debug visivo: DEBUG_ABILITATO=True e DEBUG_SQUADRE=True in config.py
    Output in DEBUG_DIR/squadre/

    Ritorna (attive, totale) oppure (-1, -1) se fallisce.
    """
    import cv2
    import numpy as np
    import os
    from datetime import datetime

    if pil_img is None:
        return (-1, -1)

    debug = config._debug_abilitato(config.DEBUG_SQUADRE)
    debug_dir = None
    ts = None
    if debug:
        debug_dir = os.path.join(config.DEBUG_DIR, "squadre")
        os.makedirs(debug_dir, exist_ok=True)
        ts = datetime.now().strftime("%H%M%S%f")[:9]

    try:
        # --- 1. Pre-check frecce via template matching ---
        frecce_presenti = False
        score_tm = -1.0

        crop_frecce = pil_img.crop(_ZONA_FRECCE_SLOT)

        if _carica_tmpl_frecce():
            arr_f = np.array(crop_frecce)
            bgr_f = cv2.cvtColor(arr_f, cv2.COLOR_RGB2BGR)
            res   = cv2.matchTemplate(bgr_f, _tmpl_frecce_cv, cv2.TM_CCOEFF_NORMED)
            _, score_tm, _, _ = cv2.minMaxLoc(res)
            frecce_presenti = score_tm >= _SOGLIA_FRECCE_TM
        else:
            arr_f2 = np.array(crop_frecce).astype(int)
            px_w   = int(np.sum(
                (arr_f2[:, :, 0] > 140) &
                (arr_f2[:, :, 1] > 140) &
                (arr_f2[:, :, 2] > 140)
            ))
            frecce_presenti = px_w >= 15
            score_tm = float(px_w)

        if debug and debug_dir:
            label_f = "SI" if frecce_presenti else "NO"
            pil_img.crop((850, 100, 960, 155)).save(
                os.path.join(debug_dir, f"{ts}_0_ctx.png"))
            crop_frecce.save(
                os.path.join(debug_dir, f"{ts}_1_frecce_{label_f}_score{score_tm:.3f}.png"))

        if not frecce_presenti:
            if debug and debug_dir:
                with open(os.path.join(debug_dir, f"{ts}_risultato.txt"), 'w') as f:
                    f.write(f"frecce: NO (score={score_tm:.3f})\nrisultato: (0, {totale_noto})\n")
            return (0, totale_noto)

        # --- 2. OCR cifre separate (psm=10/8 — più affidabili su singola cifra) ---
        crop_testo = pil_img.crop(_ZONA_TESTO_SLOT)
        crop_sx    = pil_img.crop(_ZONA_CIFRA_SX)
        crop_dx    = pil_img.crop(_ZONA_CIFRA_DX)

        if debug and debug_dir:
            crop_testo.save(os.path.join(debug_dir, f"{ts}_2_testo_raw.png"))
            crop_sx.save(os.path.join(debug_dir, f"{ts}_3_cifra_sx_raw.png"))
            crop_dx.save(os.path.join(debug_dir, f"{ts}_4_cifra_dx_raw.png"))

        attive = _ocr_cifra_singola(crop_sx, psm=10)
        totale = _ocr_cifra_singola(crop_dx, psm=8)

        # --- 3. Fallback zona intera psm=7 se cifre separate falliscono ---
        if attive == -1 or totale == -1:
            attive_z, totale_z = _ocr_zona_intera(crop_testo)
            if attive == -1:
                attive = attive_z
            if totale == -1:
                totale = totale_z

        # --- 4. Fallback totale_noto se totale ancora -1 ---
        if totale == -1 and totale_noto > 0:
            totale = totale_noto

        # Risultato finale
        if attive == -1 or totale == -1:
            if debug and debug_dir:
                with open(os.path.join(debug_dir, f"{ts}_risultato.txt"), 'w') as f:
                    f.write(f"frecce: SI (score={score_tm:.3f})\nattive={attive} totale={totale}\nrisultato: FALLITO\n")
            return (-1, -1)

        if debug and debug_dir:
            with open(os.path.join(debug_dir, f"{ts}_risultato.txt"), 'w') as f:
                f.write(f"frecce: SI (score={score_tm:.3f})\nattive={attive} totale={totale}\nrisultato: ({attive}, {totale})\n")

        return (attive, totale)

    except Exception as e:
        if debug:
            try:
                d = os.path.join(config.DEBUG_DIR, "squadre")
                os.makedirs(d, exist_ok=True)
                ts2 = datetime.now().strftime("%H%M%S%f")[:9]
                with open(os.path.join(d, f"{ts2}_eccezione.txt"), 'w') as f:
                    f.write(f"eccezione: {e}\n")
            except Exception:
                pass
        return (-1, -1)



# ------------------------------------------------------------------------------
# Leggi ETA (tempo di arrivo) dalla maschera "Marcia"
# Ritorna (secondi, testo_ocr). Se non leggibile: (None, testo_ocr)
# ------------------------------------------------------------------------------
_eta_re = re.compile(r"(?:(\d+)\s*:\s*(\d{2})\s*:\s*(\d{2}))|(?:(\d{1,2})\s*:\s*(\d{2}))")


def _parse_eta_to_seconds(testo: str):
    """Parsa 'H:MM:SS' oppure 'MM:SS' e ritorna secondi (int) o None."""
    if not testo:
        return None
    t = testo.strip().replace(' ', '')
    t = t.replace('O', '0').replace('o', '0')
    m = _eta_re.search(t)
    if not m:
        return None
    if m.group(1) is not None:
        h = int(m.group(1)); mm = int(m.group(2)); ss = int(m.group(3))
        return h * 3600 + mm * 60 + ss
    mm = int(m.group(4)); ss = int(m.group(5))
    return mm * 60 + ss


def _preprocessa_eta(img: Image.Image) -> Image.Image:
    """Preprocessa crop ETA: scala grigi, aumenta contrasto, filtra rumore, upscale, soglia."""
    w, h = img.size
    img2 = img.convert('L')
    img2 = ImageEnhance.Contrast(img2).enhance(2.3)
    img2 = img2.filter(ImageFilter.MedianFilter(size=3))
    img2 = img2.resize((w * 4, h * 4), Image.LANCZOS)
    img2 = img2.point(lambda p: 255 if p > 140 else 0)
    return img2


def _scala_zona(zona, w, h):
    """Scala zona (x1,y1,x2,y2) dalla base (OCR_MARCIA_ETA_BASE_W/H) alle dimensioni reali."""
    base_w = getattr(config, 'OCR_MARCIA_ETA_BASE_W', 960)
    base_h = getattr(config, 'OCR_MARCIA_ETA_BASE_H', 540)
    sx = float(w) / float(base_w)
    sy = float(h) / float(base_h)
    x1, y1, x2, y2 = zona
    return (int(x1 * sx), int(y1 * sy), int(x2 * sx), int(y2 * sy))


def leggi_eta_marcia_da_crop(crop: Image.Image):
    """OCR robusto ETA su crop. Ritorna (sec, raw)."""
    def _ocr_img(img: Image.Image):
        cfg = "--psm 6 -c tessedit_char_whitelist=0123456789:"
        with _tesseract_lock:
            return pytesseract.image_to_string(img, config=cfg).strip()
    try:
        img1 = _preprocessa_eta(crop)
        t1 = _ocr_img(img1)
        sec = _parse_eta_to_seconds(t1)
        if sec is not None:
            return sec, t1

        inv = ImageOps.invert(img1.convert('L'))
        inv = inv.point(lambda p: 255 if p > 140 else 0)
        t2 = _ocr_img(inv)
        sec2 = _parse_eta_to_seconds(t2)
        if sec2 is not None:
            return sec2, t2

        return None, (t1 or t2)
    except Exception:
        return None, ''


def leggi_eta_marcia(screen_path: str):
    """Legge ETA dalla maschera 'Marcia' a partire dallo screenshot su disco."""
    try:
        img = Image.open(screen_path)
        return _leggi_eta_marcia_da_img(img)
    except Exception:
        return None, ''


def leggi_eta_marcia_mem(pil_img) -> tuple:
    """
    Variante in-memoria di leggi_eta_marcia (pipeline v5.24).
    pil_img: PIL.Image già decodificata.
    Ritorna (sec, raw).
    """
    if pil_img is None:
        return None, ''
    return _leggi_eta_marcia_da_img(pil_img)


def _leggi_eta_marcia_da_img(img) -> tuple:
    """Logica comune per leggi_eta_marcia e leggi_eta_marcia_mem."""
    try:
        zona = getattr(config, 'OCR_MARCIA_ETA_ZONA', None)
        if not zona:
            return None, ''
        w, h = img.size
        zona2 = _scala_zona(zona, w, h)
        crop = img.crop(zona2)
        sec, raw = leggi_eta_marcia_da_crop(crop)

        try:
            if sec is None and config._debug_abilitato(config.DEBUG_ETA):
                import os
                from datetime import datetime
                d = os.path.join(config.DEBUG_DIR, 'eta')
                os.makedirs(d, exist_ok=True)
                ts = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                crop.save(os.path.join(d, f'eta_fail_{ts}.png'))
        except Exception:
            pass

        return sec, raw
    except Exception:
        return None, ''
# ==============================================================================
# LETTURA RISORSE dalla barra in alto
# ==============================================================================

# Zone calibrate su screenshot reali 960x540 — misurate su screen reali 04/04/2026.
# Barra completa: (425,4,948,28) — usata per open unico in leggi_risorse().
# Le singole zone sono coordinate assolute; leggi_risorse() calcola gli offset
# relativi alla barra internamente.
_ZONA_BARRA_COMPLETA = (425, 4, 948, 28)
_BARRA_X0 = 425
_BARRA_Y0 = 4

ZONE_RISORSE = {
    "pomodoro": {"zona": (455, 4, 520, 28), "taglio": 0},
    "legno":    {"zona": (555, 4, 622, 28), "taglio": 0},
    "acciaio":  {"zona": (655, 4, 720, 28), "taglio": 0},
    "petrolio": {"zona": (755, 4, 820, 28), "taglio": 0},
    "diamanti": {"zona": (855, 4, 920, 28), "taglio": 0},
}

def _parse_valore(testo: str) -> float:
    """Converte testo OCR in float. Gestisce: 25.6M, 64.9M4, 45M, 649M"""
    testo = testo.strip()
    m = re.search(r'(\d+\.\d+)\s*([MKB])', testo, re.IGNORECASE)
    if m:
        val = float(m.group(1))
        mult = m.group(2).upper()
    else:
        m = re.search(r'(\d+)\s*([MKB])', testo, re.IGNORECASE)
        if not m:
            return -1
        cifre = m.group(1)
        mult = m.group(2).upper()
        if mult == 'M':
            if len(cifre) == 3:
                val = float(cifre[:-1] + '.' + cifre[-1])
            elif len(cifre) == 2:
                val = float(cifre[0] + '.' + cifre[1])
            else:
                val = float(cifre)
        else:
            val = float(cifre)

    if mult == 'M':   val *= 1_000_000
    elif mult == 'K': val *= 1_000
    elif mult == 'B': val *= 1_000_000_000
    return val

def _maschera_bianca(img: Image.Image, taglio_sx: int = 0) -> Image.Image:
    """Estrae solo i pixel bianchi (testo) come maschera con padding."""
    import numpy as np
    arr = np.array(img).astype(int)
    h, w = arr.shape[:2]
    pad = 20
    mask = np.zeros((h + pad*2, w + pad*2), dtype=np.uint8)
    for y in range(h):
        for x in range(taglio_sx, w):
            if arr[y,x,0]>140 and arr[y,x,1]>140 and arr[y,x,2]>140:
                mask[y+pad, x-taglio_sx+pad] = 255
    return Image.fromarray(mask)

def leggi_risorsa(crop: Image.Image, taglio_sx: int = 0, debug: bool = False) -> float:
    """Legge il valore di una risorsa da un crop 4x della barra. Ritorna float o -1."""
    try:
        mask = _maschera_bianca(crop, taglio_sx)
        cfg = "--psm 7 -c tessedit_char_whitelist=0123456789.MKB"
        with _tesseract_lock:
            testo = pytesseract.image_to_string(mask, config=cfg).strip()
        val = _parse_valore(testo)
        if debug:
            print(f"  [OCR] raw='{testo}' → {val}")
        return val
    except Exception as e:
        if debug:
            print(f"  [OCR] errore: {e}")
        return -1

def _parse_diamanti(testo: str) -> int:
    """
    Converte testo OCR diamanti in intero.
    Gestisce formati: "26,548"  "26548"  "26.548"
    Ritorna intero >= 0 oppure -1 se non leggibile.
    """
    testo = testo.strip().replace(',', '').replace('.', '').replace(' ', '')
    nums = re.findall(r'\d+', testo)
    if nums:
        val = int(''.join(nums))
        # Sanity check: diamanti tipicamente < 10M
        return val if val < 10_000_000 else -1
    return -1


def leggi_risorse(screen_path: str = '', pil_img=None) -> dict:
    """
    Legge tutte le risorse dalla barra in alto.
    Ritorna dict con valori in unità assolute:
      pomodoro, legno, acciaio, petrolio: float (es. 46900000.0) o -1
      diamanti: int (es. 26548) o -1

    Parametri (almeno uno obbligatorio):
      screen_path : path file screenshot — se pil_img è None, apre il file
      pil_img     : PIL.Image già in memoria — elimina qualsiasi I/O disco

    Ottimizzazione v5.24: un solo Image.open() + un solo crop della barra
    completa (425,4,948,28), poi 5 sub-crop in memoria — nessun accesso
    aggiuntivo al disco rispetto alla versione precedente (5 open separati).
    """
    _fallback = {n: -1 for n in ZONE_RISORSE}

    # Carica immagine una sola volta
    try:
        if pil_img is None:
            if not screen_path:
                return _fallback
            pil_img = Image.open(screen_path)
        barra = pil_img.crop(_ZONA_BARRA_COMPLETA)
    except Exception:
        return _fallback

    risultati = {}
    for nome, info in ZONE_RISORSE.items():
        try:
            x1, y1, x2, y2 = info["zona"]
            # Coordinate relative alla barra
            crop = barra.crop((x1 - _BARRA_X0, y1 - _BARRA_Y0,
                               x2 - _BARRA_X0, y2 - _BARRA_Y0))
            w, h = crop.size
            crop4x = crop.resize((w * 4, h * 4), Image.LANCZOS)

            if nome == "diamanti":
                mask = _maschera_bianca(crop4x, info["taglio"])
                cfg = "--psm 7 -c tessedit_char_whitelist=0123456789,."
                with _tesseract_lock:
                    testo = pytesseract.image_to_string(mask, config=cfg).strip()
                risultati[nome] = _parse_diamanti(testo)
            else:
                val = leggi_risorsa(crop4x, info["taglio"])
                risultati[nome] = val
        except Exception:
            risultati[nome] = -1

    return risultati


# ==============================================================================
#  Lettura coordinate nodo dal popup lente
#  Tap su icona lente piccola (380, 18) apre popup con tre box:
#  "# 673"  |  "X:716"  |  "Y:531"
#  Zona box X: (430, 125, 530, 155)
#  Zona box Y: (535, 125, 635, 155)
# ==============================================================================

# Zone popup coordinate (risoluzione 960x540) — usate anche da debug.salva_crop_coord
OCR_COORD_ZONA   = (430, 125, 530, 155)   # box X
OCR_COORD_ZONA_Y = (535, 125, 635, 155)   # box Y

def _ocr_box(img_pil, zona):
    """Legge un box coordinate dal popup. Ritorna intero o None."""
    import io
    import cv2
    import numpy as np
    crop = img_pil.crop(zona)
    arr  = np.array(crop)
    bgr  = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    big  = cv2.resize(bgr, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    with _tesseract_lock:
        testo = pytesseract.image_to_string(
            Image.fromarray(thresh),
            config="--psm 7 -c tessedit_char_whitelist=0123456789XY:#. "
        ).strip()
    numeri = re.findall(r'\d{3,4}', testo)
    return int(numeri[0]) if numeri else None

def leggi_coordinate_nodo(screen_path):
    """
    Legge le coordinate X,Y dal popup lente.
    screen_path: path file screenshot (stringa)
    Ritorna (x, y) come interi, oppure None se non riesce.
    """
    try:
        img = Image.open(screen_path)
        return _leggi_coordinate_nodo_da_img(img)
    except Exception:
        return None


def leggi_coordinate_nodo_mem(pil_img, porta: str = ''):
    """
    Variante in-memoria di leggi_coordinate_nodo.
    pil_img: PIL.Image già decodificata (pipeline v5.24).
    Ritorna (x, y) come interi, oppure None se non riesce.
    """
    if pil_img is None:
        return None
    return _leggi_coordinate_nodo_da_img(pil_img, porta=porta)


def _leggi_coordinate_nodo_da_img(img, porta: str = ''):
    """Logica comune per leggi_coordinate_nodo e leggi_coordinate_nodo_mem."""
    try:
        cx = _ocr_box(img, OCR_COORD_ZONA)
        cy = _ocr_box(img, OCR_COORD_ZONA_Y)

        # Fix cx=None: rileggi dopo 600ms se necessario
        if cx is None or cy is None:
            time.sleep(0.6)
            import adb as _adb
            png = _adb.screenshot_bytes(porta) if porta else None
            if png:
                from io import BytesIO
                img2 = Image.open(BytesIO(png))
                img2.load()
            else:
                img2 = img  # riusa stessa immagine se porta non disponibile
            if cx is None:
                cx = _ocr_box(img2, OCR_COORD_ZONA)
            if cy is None:
                cy = _ocr_box(img2, OCR_COORD_ZONA_Y)

        # Fallback cx
        if cx is None and cy is not None:
            cx = 690

        import log as _log_mod
        try:
            _log_mod.logger("OCR", f"coord_popup: cx={cx} cy={cy}")
        except Exception:
            pass

        if cx is not None and cy is not None:
            return (cx, cy)
        return None
    except Exception:
        return None


# ==============================================================================
#  leggi_numero_zona / leggi_testo_zona
#  Funzioni di supporto per rifornimento.py
#  Lettura OCR da zona arbitraria dello screenshot (path file)
# ==============================================================================

def leggi_numero_zona(screen_path: str, zona: tuple) -> float:
    """
    Legge un valore numerico da una zona dello screenshot.
    zona: (x1, y1, x2, y2) — risoluzione 960x540
    Ritorna float (unità assolute, es. 20000000.0) oppure -1 se OCR fallisce.
    Gestisce formati: "20,000,000"  "20.5M"  "20M"
    Usata da rifornimento.py per leggere il residuo giornaliero.
    """
    try:
        img  = Image.open(screen_path)
        crop = img.crop(zona)
        w, h = crop.size
        # Upscale 4x + binarizzazione
        crop4x = crop.resize((w * 4, h * 4), Image.LANCZOS)
        gray   = crop4x.convert("L")
        bw     = gray.point(lambda p: 255 if p > 120 else 0)

        cfg = "--psm 7 -c tessedit_char_whitelist=0123456789,.MKB"
        with _tesseract_lock:
            testo = pytesseract.image_to_string(bw, config=cfg).strip()

        if not testo:
            return -1

        # Prova con _parse_valore (gestisce M/K/B)
        val = _parse_valore(testo)
        if val > 0:
            return val

        # Fallback: numero puro con separatori migliaia (es. "20,000,000")
        testo_clean = re.sub(r'[,.]', '', testo)
        if testo_clean.isdigit():
            return float(testo_clean)

        return -1
    except Exception:
        return -1


def leggi_testo_zona(screen_path: str, zona: tuple) -> str:
    """
    Legge testo grezzo da una zona dello screenshot.
    zona: (x1, y1, x2, y2) — risoluzione 960x540
    Ritorna stringa (es. "00:00:54") oppure "" se OCR fallisce.
    Usata da rifornimento.py per leggere il tempo di percorrenza.
    """
    try:
        img  = Image.open(screen_path)
        crop = img.crop(zona)
        w, h = crop.size
        crop4x = crop.resize((w * 4, h * 4), Image.LANCZOS)
        gray   = crop4x.convert("L")
        bw     = gray.point(lambda p: 255 if p > 120 else 0)

        cfg = "--psm 7 -c tessedit_char_whitelist=0123456789:. "
        with _tesseract_lock:
            testo = pytesseract.image_to_string(bw, config=cfg).strip()

        return testo
    except Exception:
        return ""
