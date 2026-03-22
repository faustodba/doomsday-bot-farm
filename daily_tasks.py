# ==============================================================================
#  DOOMSDAY BOT V5 - daily_tasks.py
#  Task giornalieri per istanza (schedulazione 24h)
#
#  Task disponibili:
#    - vip   : ritira ricompense VIP giornaliere (cassaforte + claim free daily)
#    - radar : raccoglie ricompense Radar Station (pallini rossi sulla mappa)
#
#  Flusso VIP (da home) — macchina a 2 stati:
#    STATO 1 — CASSAFORTE (coordinate fisse):
#      1. Tap badge VIP → apre maschera
#      2. Tap Claim cassaforte (830, 160)
#      3. Tap centro popup (480, 270) per dismissare report ricompense
#
#    STATO 2 — CLAIM FREE (template matching):
#      1. Screenshot + cerca template da config.get_btn_claim_free_template(ist)
#         nella zona CLAIM_FREE_ZONA
#      2. Se trovato → tap → attendi → BACK → return True
#      3. Se non trovato (già ritirato) → BACK → return True
#      4. Max 2 retry con attesa 1s tra un tentativo e l'altro
#
#  Template configurati in config.py:
#    VIP_CLAIM_FREE_TEMPLATE     = "templates/btn_claim_free_it.png"  ⚠️ MANCANTE
#    VIP_CLAIM_FREE_TEMPLATE_EN  = "templates/btn_claim_free_en.png"
#
#  Schedulazione: integrata in scheduler.py (task "vip", intervallo 24h)
#  Stato: sezione "schedule" del file istanza_stato_{nome}_{porta}.json
#
#  Coordinate (960x540):
#    TAP_VIP_BADGE            = (85,  52)   — badge VIP in home
#    TAP_VIP_CLAIM_CASSAFORTE = (830, 160)  — Claim cassaforte (badge rosso)
#    TAP_VIP_POPUP_DISMISS    = (480, 270)  — centro popup report ricompense
#    CLAIM_FREE_ZONA          = (500, 425, 625, 465) — zona ricerca template CLAIM verde
# ==============================================================================

import os
import time
import cv2
import adb
import scheduler
import config
import radar_show as _radar

# --- Coordinate maschera VIP ---
TAP_VIP_BADGE            = (85,  52)   # centro scritta "VIP N" in home → apre maschera
TAP_VIP_CLAIM_CASSAFORTE = (830, 160)  # Claim cassaforte (in alto a destra)
TAP_VIP_POPUP_DISMISS    = (480, 270)  # centro popup report ricompense → dismissione

# --- Template matching CLAIM verde ---
CLAIM_FREE_ZONA   = (500, 425, 625, 465)  # zona di ricerca 960x540
CLAIM_FREE_SOGLIA = 0.80                  # soglia match

CLAIM_FREE_RETRY    = 2     # tentativi di ricerca template
CLAIM_FREE_RETRY_MS = 1000  # attesa tra retry (ms)


# ------------------------------------------------------------------------------
# Utility template matching — stesso pattern di rifornimento.py
# ------------------------------------------------------------------------------

def _trova_template(screen_path: str, template_path: str,
                    zona=None, soglia: float = 0.75):
    """
    Cerca template_path in screen_path (opzionalmente limitato a zona=(x1,y1,x2,y2)).
    Ritorna (cx, cy) coordinate assolute del centro del match, oppure None.
    """
    if not screen_path or not os.path.exists(screen_path):
        return None
    if not template_path or not os.path.exists(template_path):
        return None

    img  = cv2.imread(screen_path)
    tmpl = cv2.imread(template_path)
    if img is None or tmpl is None:
        return None

    offset_x, offset_y = 0, 0
    if zona:
        x1, y1, x2, y2 = zona
        img = img[y1:y2, x1:x2]
        offset_x, offset_y = x1, y1

    result = cv2.matchTemplate(img, tmpl, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    if max_val < soglia:
        return None

    th, tw = tmpl.shape[:2]
    cx = max_loc[0] + tw // 2 + offset_x
    cy = max_loc[1] + th // 2 + offset_y
    return (cx, cy)


# ------------------------------------------------------------------------------
# Task VIP — ritira ricompense giornaliere (macchina a 2 stati)
# ------------------------------------------------------------------------------

def _esegui_vip(porta: str, nome: str, template_path: str, logger=None) -> bool:
    """
    Ritira le ricompense VIP giornaliere dalla home.

    Flusso a 2 stati:
      STATO 1 — CASSAFORTE: tap fissi + dismissione popup report
      STATO 2 — CLAIM FREE: template matching con path da config

    Ritorna True se completato senza errori bloccanti.
    """
    def log(msg):
        if logger: logger(nome, msg)

    if not os.path.exists(template_path):
        log(f"VIP: template '{template_path}' mancante — skip task")
        return False

    try:
        # ------------------------------------------------------------------
        # STATO 1 — CASSAFORTE
        # ------------------------------------------------------------------
        log("VIP: [1/2] tap badge VIP")
        adb.tap(porta, TAP_VIP_BADGE)
        time.sleep(2.0)  # attesa apertura maschera

        log("VIP: [1/2] tap Claim cassaforte")
        adb.tap(porta, TAP_VIP_CLAIM_CASSAFORTE)
        time.sleep(1.5)  # attesa animazione ricompensa

        log("VIP: [1/2] dismiss popup report ricompense")
        adb.tap(porta, TAP_VIP_POPUP_DISMISS)
        time.sleep(1.0)  # attesa chiusura popup

        # ------------------------------------------------------------------
        # STATO 2 — CLAIM FREE (template matching con retry)
        # ------------------------------------------------------------------
        claim_trovato = False
        for tentativo in range(1, CLAIM_FREE_RETRY + 1):
            screen = adb.screenshot(porta)
            if not screen:
                log(f"VIP: [2/2] screenshot fallito (tentativo {tentativo}/{CLAIM_FREE_RETRY})")
                time.sleep(CLAIM_FREE_RETRY_MS / 1000)
                continue

            coord = _trova_template(screen, template_path,
                                    zona=CLAIM_FREE_ZONA, soglia=CLAIM_FREE_SOGLIA)
            if coord:
                log(f"VIP: [2/2] CLAIM free trovato a {coord} — tap")
                adb.tap(porta, coord)
                time.sleep(1.5)  # attesa animazione ricompensa
                claim_trovato = True
                break
            else:
                log(f"VIP: [2/2] CLAIM free non trovato (tentativo {tentativo}/{CLAIM_FREE_RETRY})"
                    + (" — già ritirato oggi" if tentativo == CLAIM_FREE_RETRY else " — riprovo"))
                time.sleep(CLAIM_FREE_RETRY_MS / 1000)

        if not claim_trovato:
            log("VIP: [2/2] CLAIM free assente — cassaforte OK, free già ritirato o non disponibile")

        # Chiudi maschera con BACK
        adb.keyevent(porta, "KEYCODE_BACK")
        time.sleep(1.0)

        log("VIP: ricompense giornaliere completate")
        return True

    except Exception as e:
        log(f"VIP: errore durante esecuzione: {e}")
        try:
            adb.keyevent(porta, "KEYCODE_BACK")
            time.sleep(0.5)
        except Exception:
            pass
        return False


# ------------------------------------------------------------------------------
# Entry point — esegui tutti i daily task schedulati
# ------------------------------------------------------------------------------

def esegui_daily_tasks(porta: str, nome: str, logger=None, coords=None) -> dict:
    """
    Esegue tutti i daily task abilitati per l'istanza, rispettando la schedulazione.

    Chiamare da raccolta_istanza() prima di vai_in_mappa, mentre si è in home.

    Parametri:
      coords: UICoords dell'istanza — usato per selezionare i template
              lingua-dipendenti tramite coords.btn_claim_free_template

    Ritorna dict con esito per ogni task:
      {"vip": True/False/None}
      None = saltato (già eseguito oggi o disabilitato)
    """
    def log(msg):
        if logger: logger(nome, msg)

    esiti = {}

    # --- Task VIP ---
    if getattr(config, "DAILY_VIP_ABILITATO", True):
        if scheduler.deve_eseguire(nome, porta, "vip", logger):
            template_path = coords.btn_claim_free_template if coords else config.VIP_CLAIM_FREE_TEMPLATE_EN
            ok = _esegui_vip(porta, nome, template_path=template_path, logger=logger)
            esiti["vip"] = ok
            if ok:
                scheduler.registra_esecuzione(nome, porta, "vip")
        else:
            esiti["vip"] = None  # saltato — già eseguito oggi
    else:
        log("[DAILY] VIP disabilitato (DAILY_VIP_ABILITATO=False) — skip")
        esiti["vip"] = None

    # --- Task Radar Show ---
    if getattr(config, "DAILY_RADAR_ABILITATO", True):
        if scheduler.deve_eseguire(nome, porta, "radar", logger):
            ok = _radar.esegui_radar_show(porta, nome, coords=coords, logger=logger)
            esiti["radar"] = ok
            if ok:
                scheduler.registra_esecuzione(nome, porta, "radar")
        else:
            esiti["radar"] = None  # saltato — già eseguito nelle ultime 12h
    else:
        log("[DAILY] Radar disabilitato (DAILY_RADAR_ABILITATO=False) — skip")
        esiti["radar"] = None

    return esiti
