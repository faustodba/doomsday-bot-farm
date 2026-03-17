# ==============================================================================
#  DOOMSDAY BOT V5 - debug.py
#  Screenshot diagnostici e struttura cartelle per analisi post-ciclo
#
#  STRUTTURA CARTELLE:
#    E:\Bot-raccolta\V5\debug\
#      ciclo_001\
#        FAU_01_premarcia_sq1_073501.png
#        FAU_01_postmarcia_sq1_073523.png
#        FAU_01_ocr_fail_sq1_t2_073545.png
#        FAU_04_contatore_errato_sq3_t1_080012.png
#        ...
#      ciclo_002\
#        ...
#
#  EVENTI REGISTRATI:
#    pre_marcia     screenshot prima del tap MARCIA
#    post_marcia    screenshot dopo DELAY_MARCIA (zona OCR contatore)
#    ocr_fail       OCR non ha restituito valore leggibile
#    cnt_errato     OCR ha letto valore diverso da atteso
#    ocr_ok         OCR ha confermato contatore corretto
#    reset          screenshot al momento del reset stato
# ==============================================================================

import os
import shutil
import threading
from datetime import datetime
from PIL import Image
import config

_lock        = threading.Lock()
_ciclo_dir   = ""          # cartella ciclo corrente
_ciclo_num   = 0
_debug_root  = os.path.join(config.BOT_DIR, "debug")

def pulisci_debug():
    """
    Elimina tutta la cartella debug/ all'avvio del bot.
    Chiamare una volta sola in main.py prima del loop principale.
    Gestisce errori silenziosamente per non bloccare l'avvio.
    """
    with _lock:
        try:
            if os.path.isdir(_debug_root):
                shutil.rmtree(_debug_root)
            os.makedirs(_debug_root, exist_ok=True)
            print(f"[DEBUG] Cartella debug pulita → {_debug_root}")
        except Exception as e:
            print(f"[DEBUG] WARN pulisci_debug: {e}")


# ------------------------------------------------------------------------------
# Inizializza cartella per il ciclo corrente
# Chiamato da main.py all'inizio di ogni ciclo
# ------------------------------------------------------------------------------
def init_ciclo(num_ciclo: int):
    """Crea cartella debug/ciclo_NNN/ e aggiorna il riferimento globale."""
    global _ciclo_dir, _ciclo_num
    with _lock:
        _ciclo_num = num_ciclo
        _ciclo_dir = os.path.join(_debug_root, f"ciclo_{num_ciclo:03d}")
        os.makedirs(_ciclo_dir, exist_ok=True)

# ------------------------------------------------------------------------------
# Salva screenshot con nome strutturato
#
# Parametri:
#   screen_path  : path dello screenshot sorgente (già in BOT_DIR)
#   nome         : nome istanza es. "FAU_01"
#   evento       : "pre_marcia" | "post_marcia" | "ocr_fail" | "cnt_errato" |
#                  "ocr_ok" | "reset"
#   squadra      : indice squadra (1-based) es. 1
#   tentativo    : tentativo corrente es. 2 (opzionale, 0 = non specificato)
#   extra        : testo libero aggiuntivo (opzionale, es. "atteso3_letto1")
#
# Ritorna path del file salvato o "" se fallisce
# ------------------------------------------------------------------------------
def salva_screen(screen_path: str, nome: str, evento: str,
                 squadra: int = 0, tentativo: int = 0, extra: str = "") -> str:
    if not screen_path or not os.path.exists(screen_path):
        return ""
    if not _ciclo_dir:
        return ""

    ts = datetime.now().strftime("%H%M%S")

    parti = [nome, evento]
    if squadra > 0:
        parti.append(f"sq{squadra}")
    if tentativo > 0:
        parti.append(f"t{tentativo}")
    if extra:
        # sanifica per uso come nome file
        extra_safe = extra.replace(" ", "_").replace("/", "-").replace(":", "")
        parti.append(extra_safe)
    parti.append(ts)

    nome_file = "_".join(parti) + ".png"
    dest = os.path.join(_ciclo_dir, nome_file)

    with _lock:
        try:
            shutil.copy2(screen_path, dest)
            return dest
        except Exception:
            return ""

# ------------------------------------------------------------------------------
# Salva crop della zona OCR contatore (per analisi dettagliata)
# Utile per capire cosa vede Tesseract esattamente
# ------------------------------------------------------------------------------
def salva_crop_ocr(screen_path: str, nome: str, evento: str,
                   squadra: int = 0, tentativo: int = 0, extra: str = "") -> str:
    """Come salva_screen ma salva solo il crop della zona OCR_ZONA ingrandita 4x."""
    if not screen_path or not os.path.exists(screen_path):
        return ""
    if not _ciclo_dir:
        return ""

    ts = datetime.now().strftime("%H%M%S")
    parti = [nome, evento + "_crop"]
    if squadra > 0:
        parti.append(f"sq{squadra}")
    if tentativo > 0:
        parti.append(f"t{tentativo}")
    if extra:
        extra_safe = extra.replace(" ", "_").replace("/", "-").replace(":", "")
        parti.append(extra_safe)
    parti.append(ts)

    nome_file = "_".join(parti) + ".png"
    dest = os.path.join(_ciclo_dir, nome_file)

    with _lock:
        try:
            img  = Image.open(screen_path)
            crop = img.crop(config.OCR_ZONA)
            w, h = crop.size
            crop4x = crop.resize((w * 4, h * 4), Image.NEAREST)
            crop4x.save(dest)
            return dest
        except Exception:
            return ""

# ------------------------------------------------------------------------------
# Salva crop della zona OCR coordinate nodo (barra superiore)
# Zona: OCR_COORD_ZONA da ocr.py — es. (240, 12, 380, 25)
# Utile per verificare cosa legge Tesseract per X:NNN Y:NNN
# ------------------------------------------------------------------------------
def salva_crop_coord(screen_path: str, nome: str, evento: str,
                     squadra: int = 0, tentativo: int = 0, extra: str = "") -> str:
    """Salva il crop ingrandito della zona coordinate nodo (barra superiore)."""
    if not screen_path or not os.path.exists(screen_path):
        return ""
    if not _ciclo_dir:
        return ""

    ts = datetime.now().strftime("%H%M%S")
    parti = [nome, evento + "_crop"]
    if squadra > 0:
        parti.append(f"sq{squadra}")
    if tentativo > 0:
        parti.append(f"t{tentativo}")
    if extra:
        extra_safe = extra.replace(" ", "_").replace("/", "-").replace(":", "")
        parti.append(extra_safe)
    parti.append(ts)

    nome_file = "_".join(parti) + ".png"
    dest = os.path.join(_ciclo_dir, nome_file)

    with _lock:
        try:
            import ocr as _ocr
            img  = Image.open(screen_path)
            x1, y1, x2, y2 = _ocr.OCR_COORD_ZONA
            crop = img.crop((x1, y1, x2, y2))
            w, h = crop.size
            # Ingrandisci 6x per leggibilità massima
            crop6x = crop.resize((w * 6, h * 6), Image.NEAREST)
            crop6x.save(dest)
            return dest
        except Exception:
            return ""

# ------------------------------------------------------------------------------
# Ritorna il path della cartella del ciclo corrente (per log/report)
# ------------------------------------------------------------------------------
def ciclo_dir() -> str:
    return _ciclo_dir

# ------------------------------------------------------------------------------
# Ritorna il numero ciclo corrente
# ------------------------------------------------------------------------------
def ciclo_num() -> int:
    return _ciclo_num
