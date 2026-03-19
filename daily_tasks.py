# ==============================================================================
#  DOOMSDAY BOT V5 - daily_tasks.py
#  Task giornalieri per istanza (schedulazione 24h)
#
#  Task disponibili:
#    - vip : ritira ricompense VIP giornaliere (cassaforte + claim free daily)
#
#  Flusso VIP (da home):
#    1. Tap sul badge VIP in alto a sinistra (apre maschera VIP)
#    2. Tap Claim cassaforte (in alto a destra nella maschera)
#    3. Tap CLAIM verde (free daily, sezione centrale)
#    4. BACK per chiudere
#
#  Schedulazione: integrata in scheduler.py (task "vip", intervallo 24h)
#  Stato: sezione "schedule" del file istanza_stato_{nome}_{porta}.json
#
#  Coordinate (960x540):
#    TAP_VIP_BADGE   = (85, 25)   — badge VIP in home
#    TAP_VIP_CLAIM_CASSAFORTE = (830, 160) — cassaforte Claim (badge rosso)
#    TAP_VIP_CLAIM_FREE       = (558, 440) — CLAIM verde (free daily)
# ==============================================================================

import time
import adb
import scheduler
import config

# --- Coordinate maschera VIP ---
TAP_VIP_BADGE            = (85,  52)   # centro scritta "VIP 7" in home → apre maschera
TAP_VIP_CLAIM_CASSAFORTE = (830, 160)  # Claim cassaforte (in alto a destra)
TAP_VIP_CLAIM_FREE       = (580, 454)  # CLAIM verde (free daily, centrale)


# ------------------------------------------------------------------------------
# Task VIP — ritira ricompense giornaliere
# ------------------------------------------------------------------------------

def _esegui_vip(porta: str, nome: str, logger=None) -> bool:
    """
    Ritira le ricompense VIP giornaliere dalla home.

    Flusso:
      1. Tap badge VIP → apre maschera
      2. Tap cassaforte Claim
      3. Tap CLAIM verde (free daily)
      4. BACK → torna in home

    Ritorna True se completato senza errori.
    """
    def log(msg):
        if logger: logger(nome, msg)

    try:
        log("VIP: tap badge VIP")
        adb.tap(porta, TAP_VIP_BADGE)
        time.sleep(2.0)  # attesa apertura maschera

        log("VIP: tap Claim cassaforte")
        adb.tap(porta, TAP_VIP_CLAIM_CASSAFORTE)
        time.sleep(1.5)  # attesa animazione ricompensa

        log("VIP: tap CLAIM free daily")
        adb.tap(porta, TAP_VIP_CLAIM_FREE)
        time.sleep(1.5)  # attesa animazione ricompensa

        # Chiudi maschera con BACK
        adb.keyevent(porta, "KEYCODE_BACK")
        time.sleep(1.0)

        log("VIP: ricompense giornaliere ritirate")
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

def esegui_daily_tasks(porta: str, nome: str, logger=None) -> dict:
    """
    Esegue tutti i daily task abilitati per l'istanza, rispettando la schedulazione.

    Chiamare da raccolta_istanza() prima di vai_in_mappa, mentre si è in home.

    Ritorna dict con esito per ogni task:
      {"vip": True/False/None}
      None = saltato (già eseguito oggi)
    """
    def log(msg):
        if logger: logger(nome, msg)

    esiti = {}

    # --- Task VIP ---
    if getattr(config, "DAILY_VIP_ABILITATO", True):
        if scheduler.deve_eseguire(nome, porta, "vip", logger):
            ok = _esegui_vip(porta, nome, logger)
            esiti["vip"] = ok
            if ok:
                scheduler.registra_esecuzione(nome, porta, "vip")
        else:
            esiti["vip"] = None  # saltato
    else:
        log("[DAILY] VIP disabilitato (DAILY_VIP_ABILITATO=False) — skip")
        esiti["vip"] = None

    return esiti
