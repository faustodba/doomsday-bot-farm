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
# Conta squadre libere
# ------------------------------------------------------------------------------
def squadre_libere(crop: Image.Image) -> int:
    """Ritorna il numero di squadre libere (totale - attive)."""
    attive, totale = leggi_contatore(crop)
    if attive == -1:
        return -1
    return max(0, totale - attive)

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
    """Legge ETA dalla maschera 'Marcia' a partire dallo screenshot completo."""
    try:
        zona = getattr(config, 'OCR_MARCIA_ETA_ZONA', None)
        if not zona:
            return None, ''
        img = Image.open(screen_path)
        w, h = img.size
        zona2 = _scala_zona(zona, w, h)
        crop = img.crop(zona2)
        sec, raw = leggi_eta_marcia_da_crop(crop)

        try:
            if sec is None and getattr(config, 'OCR_MARCIA_ETA_DEBUG_SAVE', False):
                import os
                from datetime import datetime
                d = os.path.join(config.BOT_DIR, 'debug_eta')
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

ZONE_RISORSE = {
    "pomodoro": {"zona": (460, 0, 512, 28), "taglio": 0},
    "legno":    {"zona": (530, 0, 618, 28), "taglio": 0},
    "acciaio":  {"zona": (625, 0, 702, 28), "taglio": 20},
    "petrolio": {"zona": (720, 0, 800, 28), "taglio": 0},
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
            if arr[y,x,0]>180 and arr[y,x,1]>180 and arr[y,x,2]>180:
                mask[y+pad, x-taglio_sx+pad] = 255
    return Image.fromarray(mask)

def leggi_risorsa(crop: Image.Image, taglio_sx: int = 0) -> float:
    """Legge il valore di una risorsa da un crop 4x della barra. Ritorna float o -1."""
    try:
        mask = _maschera_bianca(crop, taglio_sx)
        cfg = "--psm 7 -c tessedit_char_whitelist=0123456789.MKB"
        with _tesseract_lock:
            testo = pytesseract.image_to_string(mask, config=cfg).strip()
        return _parse_valore(testo)
    except:
        return -1

def leggi_risorse(screen_path: str) -> dict:
    """
    Legge tutte le risorse dalla barra in alto.
    Ritorna dict: {"pomodoro": 25600000, "legno": 64900000, ...}
    """
    import adb as _adb
    risultati = {}
    for nome, info in ZONE_RISORSE.items():
        crop = _adb.crop_zona(screen_path, info["zona"])
        if crop:
            w, h = crop.size
            crop4x = crop.resize((w*4, h*4), Image.NEAREST)
            val = leggi_risorsa(crop4x, info["taglio"])
            risultati[nome] = val
        else:
            risultati[nome] = -1
    return risultati


# ==============================================================================
#  Lettura coordinate nodo dal popup lente
#  Tap su icona lente piccola (380, 18) apre popup con tre box:
#  "# 673"  |  "X:716"  |  "Y:531"
#  Zona box X: (430, 125, 530, 155)
#  Zona box Y: (535, 125, 635, 155)
# ==============================================================================

import io
import cv2

# Zone popup coordinate (risoluzione 960x540) — usate anche da debug.salva_crop_coord
OCR_COORD_ZONA   = (430, 125, 530, 155)   # box X
OCR_COORD_ZONA_Y = (535, 125, 635, 155)   # box Y

def _ocr_box(img_pil, zona):
    """Legge un box coordinate dal popup. Ritorna intero o None."""
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
        cx = _ocr_box(img, OCR_COORD_ZONA)
        cy = _ocr_box(img, OCR_COORD_ZONA_Y)

        # Fix cx=None: se uno dei due è None, rileggi la stessa immagine dopo 600ms
        # (il popup potrebbe non essere completamente renderizzato al primo scatto)
        if cx is None or cy is None:
            time.sleep(0.6)
            img2 = Image.open(screen_path)
            if cx is None:
                cx = _ocr_box(img2, OCR_COORD_ZONA)
            if cy is None:
                cy = _ocr_box(img2, OCR_COORD_ZONA_Y)

        # Fallback: se cx ancora None ma cy valido, usa centro schermo orizzontale
        if cx is None and cy is not None:
            cx = 690  # centro schermo a 960x540

        # Log grezzo per debug
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
