# test_ocr.py — OCR popup coordinate (lente)
import os, cv2, re
import numpy as np
from PIL import Image
import pytesseract
import config

pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_EXE

screen_path = os.path.join(config.BOT_DIR, "screen_popup.png")
print(f"Screen: {screen_path}")
img = Image.open(screen_path)

def ocr_zona(zona, label):
    x1, y1, x2, y2 = zona
    crop = img.crop((x1, y1, x2, y2))
    arr = np.array(crop)
    bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    big = cv2.resize(bgr, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    crop.save(os.path.join(config.BOT_DIR, f"debug_{label}_crop.png"))
    for psm in [7, 8, 13]:
        t = pytesseract.image_to_string(
            Image.fromarray(thresh),
            config=f"--psm {psm} -c tessedit_char_whitelist=0123456789XY:#. "
        ).strip()
        numeri = re.findall(r'\d{3,4}', t)
        ok = f" >>> {numeri[0]}" if numeri else ""
        print(f"  {label} psm{psm}: '{t}'{ok}")

print("\n--- Box X ---")
ocr_zona((430, 125, 530, 155), "X")

print("\n--- Box Y ---")
ocr_zona((535, 125, 635, 155), "Y")

print("\n--- Box X+Y insieme ---")
ocr_zona((415, 120, 650, 158), "XY")