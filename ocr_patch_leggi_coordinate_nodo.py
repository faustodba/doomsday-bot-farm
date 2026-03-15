# ==============================================================================
#  PATCH ocr.py — aggiungere in fondo al file
#  Legge le coordinate X,Y del nodo selezionato dal banner superiore
#  Formato atteso: "#673 X:712 Y:535"
#  Crop zona: x=310, y=8, x2=540, y2=30  (risoluzione ADB 960x540)
# ==============================================================================

import re
import io
import numpy as np

OCR_COORD_ZONA = (270, 8, 550, 30)   # (x1, y1, x2, y2)

def leggi_coordinate_nodo(screen_bytes):
    """
    Legge le coordinate X,Y del nodo selezionato dal banner superiore.
    Ritorna (x, y) come interi, oppure None se non riesce.
    Esempio: "#673 X:712 Y:535"  →  (712, 535)
    """
    try:
        import cv2
        import pytesseract
        from PIL import Image

        img = Image.open(io.BytesIO(screen_bytes))
        arr = np.array(img)
        x1, y1, x2, y2 = OCR_COORD_ZONA
        crop = arr[y1:y2, x1:x2]

        # Ingrandisci 3x per OCR più preciso su testo piccolo
        crop_bgr = cv2.cvtColor(crop, cv2.COLOR_RGB2BGR)
        crop_big = cv2.resize(crop_bgr, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)

        # Soglia: isola testo chiaro su sfondo scuro
        gray = cv2.cvtColor(crop_big, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 140, 255, cv2.THRESH_BINARY)

        testo = pytesseract.image_to_string(
            thresh,
            config="--psm 7 -c tessedit_char_whitelist=0123456789XY:#. "
        ).strip()

        # Cerca pattern X:NNN Y:NNN — tollerante a X: parzialmente tagliato
        m = re.search(r'X[:\s]*(\d+)\s+Y[:\s]*(\d+)', testo)
        if not m:
            # Fallback: cerca due sequenze di 3 cifre consecutive (NNN NNN)
            m2 = re.findall(r'\d{3,4}', testo)
            if len(m2) >= 2:
                return int(m2[0]), int(m2[1])
        if m:
            return int(m.group(1)), int(m.group(2))
        return None

    except Exception:
        return None