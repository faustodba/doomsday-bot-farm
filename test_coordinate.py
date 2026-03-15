"""
Test OCR coordinate nodo — Doomsday Bot V5
Uso: python test_coordinate.py [percorso_screenshot]
Default: test_nodo.png nella stessa cartella
"""
import sys
import re
import io
import os

# Aggiunge il path di V5 per trovare config.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test(screen_path):
    import cv2
    import numpy as np
    import pytesseract
    from PIL import Image
    import config

    pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_EXE

    print(f"Screenshot: {screen_path}")
    with open(screen_path, "rb") as f:
        screen_bytes = f.read()

    img = Image.open(io.BytesIO(screen_bytes))
    print(f"Dimensione immagine: {img.size}")
    arr = np.array(img)

    x1, y1, x2, y2 = 270, 8, 550, 30
    crop = arr[y1:y2, x1:x2]
    Image.fromarray(crop).save("debug_crop_new.png")
    print(f"Crop ({x1},{y1})-({x2},{y2}) salvato in debug_crop_new.png")

    crop_bgr = cv2.cvtColor(crop, cv2.COLOR_RGB2BGR)
    crop_big = cv2.resize(crop_bgr, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(crop_big, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 140, 255, cv2.THRESH_BINARY)
    Image.fromarray(thresh).save("debug_thresh.png")
    print("Immagine sogliata salvata in debug_thresh.png")

    testo = pytesseract.image_to_string(
        Image.fromarray(thresh),
        config="--psm 7 -c tessedit_char_whitelist=0123456789XY:#. "
    ).strip()
    print(f"Testo OCR grezzo: '{testo}'")

    # Pattern principale
    m = re.search(r'X[:\s]*(\d{3})[^\d]*Y[:\s]*(\d{3})', testo)
    if m:
        print(f"\nOK (pattern X:N Y:N) — X={m.group(1)}, Y={m.group(2)}")
        return

    # Fallback: salta primo numero (#ID mappa), prende i due successivi
    numeri = re.findall(r'\d{3,4}', testo)
    print(f"Numeri 3-4 cifre trovati: {numeri}")
    if len(numeri) >= 3:
        print(f"\nOK (fallback skip #ID) — X={numeri[1]}, Y={numeri[2]}")
        return
    if len(numeri) >= 2:
        print(f"\nOK (fallback numeri) — X={numeri[0]}, Y={numeri[1]}")
        return

    print("\nFAIL — mandare debug_crop_new.png e debug_thresh.png")

# --- main ---
path = sys.argv[1] if len(sys.argv) > 1 else "test_nodo.png"
if not os.path.exists(path):
    print(f"File non trovato: {path}")
    sys.exit(1)
test(path)