# ==============================================================================
# DOOMSDAY BOT V5 - alleanza.py
# Raccolta ricompense dalla sezione Alleanza -> Dono
#
# Flusso (dalla schermata home):
# 1. Tap pulsante Alleanza (menu in basso)
# 2. Tap icona Dono -> apre direttamente su "Ricompense del negozio"
# 3. Tab "Ricompense del negozio" -> Tap "Rivendica" finché il pulsante sparisce (max 20)
# 4. Tab "Ricompense attività" -> Tap "Raccogli tutto"
# 5. Back x3 -> torna in home
#
# Schedulazione:
# Eseguito al massimo ogni SCHEDULE_ORE_ALLEANZA ore per istanza (default 12h).
# Stato persistito in: istanza_stato_{nome}_{porta}.json (sezione schedule).
# ==============================================================================
import time
import adb
import config
import scheduler

# ------------------------------------------------------------------------------
# Coordinate (risoluzione 960x540)
# ------------------------------------------------------------------------------
COORD_ALLEANZA = (760, 505)      # Pulsante Alleanza nel menu in basso
COORD_DONO = (877, 458)          # Icona Dono nel menu Alleanza
COORD_TAB_ATTIVITA = (600, 75)   # Tab "Ricompense attività"
COORD_TAB_NEGOZIO = (810, 75)    # Tab "Ricompense del negozio"
COORD_RACCOGLI_TUTTO = (856, 505)# Pulsante "Raccogli tutto" (Attività)
COORD_RIVENDICA = (856, 240)     # Pulsante "Rivendica" (Negozio)

# Limite massimo tap (stop anticipato se il pulsante sparisce)
MAX_RIVENDICA_CLICK = 20

# ------------------------------------------------------------------------------
# Utils: verifica presenza pulsante "Rivendica" (heuristica su ROI)
# ------------------------------------------------------------------------------
_RIV_ROI_HALF_W = 130
_RIV_ROI_HALF_H = 28


def _crop_roi(img_path: str, center_xy, half_w=_RIV_ROI_HALF_W, half_h=_RIV_ROI_HALF_H):
    """Ritorna array RGB della ROI attorno al punto (o None se fallisce)."""
    try:
        import numpy as np
        from PIL import Image
        x, y = center_xy
        img = Image.open(img_path)
        w, h = img.size
        x1 = max(0, int(x - half_w))
        y1 = max(0, int(y - half_h))
        x2 = min(w, int(x + half_w))
        y2 = min(h, int(y + half_h))
        roi = img.crop((x1, y1, x2, y2))
        return np.array(roi)[:, :, :3]
    except Exception:
        return None


def _rivendica_presente(screen_path: str) -> bool:
    """True se il pulsante Rivendica sembra presente.

    Quando il pulsante sparisce (claim finiti) l'area diventa simile allo sfondo.
    Fail-safe: se non possiamo verificare, ritorna True.
    """
    arr = _crop_roi(screen_path, COORD_RIVENDICA)
    if arr is None:
        return True
    try:
        import numpy as np
        r = arr[:, :, 0].astype(int)
        g = arr[:, :, 1].astype(int)
        b = arr[:, :, 2].astype(int)
        mx = np.maximum(np.maximum(r, g), b)
        mn = np.minimum(np.minimum(r, g), b)
        sat = (mx - mn)
        bright = mx
        # area "bottone" tipicamente molto più satura/luminosa rispetto allo sfondo
        mask = (sat > 35) & (bright > 120)
        ratio = float(mask.sum()) / float(mask.size)
        return ratio > 0.10
    except Exception:
        return True


def _roi_hash(screen_path: str) -> str:
    """Hash della ROI del bottone per fallback no-change."""
    try:
        import hashlib
        arr = _crop_roi(screen_path, COORD_RIVENDICA)
        if arr is None:
            return ''
        h = hashlib.md5()
        h.update(arr.tobytes())
        return h.hexdigest()
    except Exception:
        return ''


# ------------------------------------------------------------------------------
# Raccolta ricompense Alleanza
# ------------------------------------------------------------------------------

def raccolta_alleanza(porta: str, nome: str, logger=None, ist=None) -> bool:
    """Raccoglie le ricompense dalla sezione Alleanza -> Dono."""

    def log(msg: str):
        if logger:
            logger(nome, msg)

    # Verifica schedulazione
    if not scheduler.deve_eseguire(nome, porta, "alleanza", logger):
        return True

    # Coordinate pulsante Alleanza: dipende dal layout barra dell'istanza
    coord_alleanza = config.get_coord_alleanza(ist) if ist else COORD_ALLEANZA
    layout = ist.get("layout", 1) if isinstance(ist, dict) else 1
    log(f"Alleanza: layout barra {layout} → tap {coord_alleanza}")

    try:
        log("Inizio raccolta ricompense Alleanza")

        # Porta in home se necessario
        import stato as _stato
        s_ora, _ = _stato.rileva(porta)
        if s_ora != "home":
            log(f"Alleanza: stato '{s_ora}' — porto in home prima di procedere")
            if not _stato.vai_in_home(porta, nome, logger, conferme=2):
                log("Alleanza: impossibile tornare in home — skip")
                return False
            time.sleep(1.0)

        # 1) Apri menu Alleanza
        log("Alleanza: tap pulsante Alleanza")
        adb.tap(porta, coord_alleanza)
        time.sleep(2.0)

        # 2) Apri sezione Dono
        log("Alleanza: tap Dono")
        adb.tap(porta, COORD_DONO)
        time.sleep(2.0)

        # 3) Ricompense Negozio -> Rivendica finché sparisce (max 20)
        log(f"Alleanza: Ricompense Negozio -> Rivendica fino a {MAX_RIVENDICA_CLICK} (stop se sparisce)")
        adb.tap(porta, COORD_TAB_NEGOZIO)
        time.sleep(0.8)

        no_change_streak = 0
        for i in range(MAX_RIVENDICA_CLICK):
            scr = adb.screenshot(porta)
            if not _rivendica_presente(scr):
                log(f"Alleanza: Rivendica non più visibile — stop a {i}/{MAX_RIVENDICA_CLICK}")
                break

            h_before = _roi_hash(scr)
            adb.tap(porta, COORD_RIVENDICA)
            time.sleep(0.55)

            scr2 = adb.screenshot(porta)
            h_after = _roi_hash(scr2)
            if h_before and h_after and h_before == h_after:
                no_change_streak += 1
            else:
                no_change_streak = 0

            if not _rivendica_presente(scr2):
                log(f"Alleanza: Rivendica sparito dopo tap — stop a {i+1}/{MAX_RIVENDICA_CLICK}")
                break

            if no_change_streak >= 2:
                log(f"Alleanza: nessun cambiamento su Rivendica (streak={no_change_streak}) — stop a {i+1}/{MAX_RIVENDICA_CLICK}")
                break

        # 4) Tab Ricompense Attività -> Raccogli tutto
        log("Alleanza: tab Ricompense Attività -> Raccogli tutto")
        adb.tap(porta, COORD_TAB_ATTIVITA)
        time.sleep(0.8)
        adb.tap(porta, COORD_RACCOGLI_TUTTO)
        time.sleep(1.0)

        # 5) Back x3
        log("Alleanza: chiusura (back x3)")
        adb.keyevent(porta, "KEYCODE_BACK")
        time.sleep(0.8)
        adb.keyevent(porta, "KEYCODE_BACK")
        time.sleep(1.5)
        adb.keyevent(porta, "KEYCODE_BACK")
        time.sleep(1.0)

        log("Raccolta ricompense Alleanza completata")
        scheduler.registra_esecuzione(nome, porta, "alleanza")
        return True

    except Exception as e:
        log(f"Errore raccolta Alleanza: {e}")
        try:
            adb.keyevent(porta, "KEYCODE_BACK")
            time.sleep(0.5)
            adb.keyevent(porta, "KEYCODE_BACK")
            time.sleep(0.5)
        except Exception:
            pass
        return False
