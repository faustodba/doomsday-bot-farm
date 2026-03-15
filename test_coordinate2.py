"""
Test standalone coordinate nodo — non dipende da ocr.py
Esegui: python test_coordinate2.py
Usa test_nodo.png nella stessa cartella
"""
import re
import io
import sys
import numpy as np

def leggi_coordinate_nodo(screen_bytes):
    try:
        import cv2
        import pytesseract
        from PIL import Image

        img = Image.open(io.BytesIO(screen_bytes))
        arr = np.array(img)

        # Crop zona coordinate — x da 270 a 550, y da 8 a 30
        x1, y1, x2, y2 = 270, 8, 550, 30
        crop = arr[y1:y2, x1:x2]

        # Salva crop per debug
        Image.fromarray(crop).save("debug_crop2.png")
        print("Salvato debug_crop2.png")

        # Ingrandisci 3x
        crop_bgr = cv2.cvtColor(crop, cv2.COLOR_RGB2BGR)
        crop_big = cv2.resize(crop_bgr, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)

        # Soglia
        gray = cv2.cvtColor(crop_big, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 140, 255, cv2.THRESH_BINARY)
        Image.fromarray(thresh).save("debug_thresh.png")
        print("Salvato debug_thresh.png")

        testo = pytesseract.image_to_string(
            thresh,
            config="--psm 7 -c tessedit_char_whitelist=0123456789XY:#. "
        ).strip()
        print(f"Testo OCR: '{testo}'")

        # Pattern principale
        m = re.search(r'X[:\s]*(\d+)\s+Y[:\s]*(\d+)', testo)
        if m:
            return int(m.group(1)), int(m.group(2))

        # Fallback: prende i primi due numeri di 3+ cifre
        numeri = re.findall(r'\d{3,4}', testo)
        print(f"Numeri trovati: {numeri}")
        if len(numeri) >= 2:
            return int(numeri[0]), int(numeri[1])

        return None

    except Exception as e:
        print(f"Eccezione: {e}")
        return None

# --- main ---
with open("test_nodo.png", "rb") as f:
    screen_bytes = f.read()

coord = leggi_coordinate_nodo(screen_bytes)
if coord:
    print(f"\nOK — coordinate lette: X={coord[0]}, Y={coord[1]}")
else:
    print("\nFAIL — coordinate non lette")