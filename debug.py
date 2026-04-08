# ==============================================================================
#  DOOMSDAY BOT V5 - debug.py
#  Screenshot diagnostici e struttura cartelle per analisi post-ciclo
#
#  v5.24 — Struttura unificata sotto config.DEBUG_DIR:
#    debug/
#      ciclo/
#        ciclo_NNN/
#          {istanza}/
#            {fase}_{sq}_{tentativo}_{ts}.png
#      stato/    ← screen rilevamento stato
#      squadre/  ← crop contatore squadre
#      eta/      ← crop OCR ETA marcia falliti
#      screen/   ← screen_{porta}.png temporanei
#
#  Master switch: config.DEBUG_ABILITATO=False → zero I/O debug su disco.
#  config.DEBUG_RACCOLTA=False → salva_screen() è no-op anche se abilitato.
#
#  EVENTI REGISTRATI:
#    pre_marcia          screenshot prima del tap MARCIA
#    pre_marcia_retry    screenshot al retry pre-marcia
#    post_marcia         screenshot dopo DELAY_MARCIA
#    fase3_popup_*       screenshot popup nodo (fase 3 OCR coord)
#    fase3_ocr_coord     crop zona coordinate OCR
#    fase3_ocr_coord_fail
#    fase3_blacklist     screenshot nodo in blacklist
#    fase4_popup_raccogli
#    fase4_livello_basso
#    fase4_fuori_territorio
#    reset               screenshot al momento del reset stato
# ==============================================================================

import os
import shutil
import threading
from datetime import datetime
from PIL import Image
import config

_lock       = threading.Lock()
_ciclo_dir  = ""
_ciclo_num  = 0


def _root_ciclo() -> str:
    return os.path.join(config.DEBUG_DIR, "ciclo")


def pulisci_debug():
    """
    Elimina tutta la cartella debug/ all'avvio del bot.
    Chiamare una volta sola in main.py prima del loop principale.
    """
    with _lock:
        try:
            if os.path.isdir(config.DEBUG_DIR):
                shutil.rmtree(config.DEBUG_DIR)
            os.makedirs(config.DEBUG_DIR, exist_ok=True)
            print(f"[DEBUG] Cartella debug pulita → {config.DEBUG_DIR}")
        except Exception as e:
            print(f"[DEBUG] WARN pulisci_debug: {e}")


def init_ciclo(num_ciclo: int):
    """Crea cartella debug/ciclo/ciclo_NNN/ e aggiorna riferimento globale."""
    global _ciclo_dir, _ciclo_num
    with _lock:
        _ciclo_num = num_ciclo
        _ciclo_dir = os.path.join(_root_ciclo(), f"ciclo_{num_ciclo:03d}")
        os.makedirs(_ciclo_dir, exist_ok=True)


def _cartella_istanza(nome: str) -> str:
    """Ritorna (e crea) la sottocartella per l'istanza nel ciclo corrente."""
    if not _ciclo_dir:
        return ""
    d = os.path.join(_ciclo_dir, nome)
    os.makedirs(d, exist_ok=True)
    return d


def salva_screen(screen_path: str, nome: str, evento: str,
                 squadra: int = 0, tentativo: int = 0, extra: str = "") -> str:
    """
    Salva screenshot diagnostico in debug/ciclo/ciclo_NNN/{nome}/.
    No-op se DEBUG_ABILITATO=False o DEBUG_RACCOLTA=False.
    """
    if not config._debug_abilitato(config.DEBUG_RACCOLTA):
        return ""
    if not screen_path or not os.path.exists(screen_path):
        return ""

    dest_dir = _cartella_istanza(nome)
    if not dest_dir:
        return ""

    ts = datetime.now().strftime("%H%M%S")
    parti = [evento]
    if squadra > 0:
        parti.append(f"sq{squadra}")
    if tentativo > 0:
        parti.append(f"t{tentativo}")
    if extra:
        parti.append(extra.replace(" ", "_").replace("/", "-").replace(":", ""))
    parti.append(ts)

    nome_file = "_".join(parti) + ".png"
    dest = os.path.join(dest_dir, nome_file)

    with _lock:
        try:
            shutil.copy2(screen_path, dest)
            return dest
        except Exception:
            return ""


def salva_crop_ocr(screen_path: str, nome: str, evento: str,
                   squadra: int = 0, tentativo: int = 0, extra: str = "") -> str:
    """Salva crop zona OCR contatore ingrandita 4x."""
    if not config._debug_abilitato(config.DEBUG_RACCOLTA):
        return ""
    if not screen_path or not os.path.exists(screen_path):
        return ""

    dest_dir = _cartella_istanza(nome)
    if not dest_dir:
        return ""

    ts = datetime.now().strftime("%H%M%S")
    parti = [evento + "_crop"]
    if squadra > 0:
        parti.append(f"sq{squadra}")
    if tentativo > 0:
        parti.append(f"t{tentativo}")
    if extra:
        parti.append(extra.replace(" ", "_").replace("/", "-").replace(":", ""))
    parti.append(ts)

    nome_file = "_".join(parti) + ".png"
    dest = os.path.join(dest_dir, nome_file)

    with _lock:
        try:
            img    = Image.open(screen_path)
            crop   = img.crop(config.OCR_ZONA)
            w, h   = crop.size
            crop4x = crop.resize((w * 4, h * 4), Image.NEAREST)
            crop4x.save(dest)
            return dest
        except Exception:
            return ""


def salva_crop_coord(screen_path: str, nome: str, evento: str,
                     squadra: int = 0, tentativo: int = 0, extra: str = "") -> str:
    """Salva crop zona coordinate nodo ingrandita 6x."""
    if not config._debug_abilitato(config.DEBUG_RACCOLTA):
        return ""
    if not screen_path or not os.path.exists(screen_path):
        return ""

    dest_dir = _cartella_istanza(nome)
    if not dest_dir:
        return ""

    ts = datetime.now().strftime("%H%M%S")
    parti = [evento + "_crop"]
    if squadra > 0:
        parti.append(f"sq{squadra}")
    if tentativo > 0:
        parti.append(f"t{tentativo}")
    if extra:
        parti.append(extra.replace(" ", "_").replace("/", "-").replace(":", ""))
    parti.append(ts)

    nome_file = "_".join(parti) + ".png"
    dest = os.path.join(dest_dir, nome_file)

    with _lock:
        try:
            import ocr as _ocr
            img        = Image.open(screen_path)
            x1,y1,x2,y2 = _ocr.OCR_COORD_ZONA
            crop       = img.crop((x1, y1, x2, y2))
            w, h       = crop.size
            crop6x     = crop.resize((w * 6, h * 6), Image.NEAREST)
            crop6x.save(dest)
            return dest
        except Exception:
            return ""


def ciclo_dir() -> str:
    return _ciclo_dir


def ciclo_num() -> int:
    return _ciclo_num
