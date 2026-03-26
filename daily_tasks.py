# ==============================================================================
#  DOOMSDAY BOT V5 - daily_tasks.py
#  Task giornalieri per istanza (schedulazione 24h)
#
#  Task disponibili:
#    - vip   : ritira ricompense VIP giornaliere (cassaforte + claim free daily)
#    - radar : raccoglie ricompense Radar Station (pallini rossi sulla mappa)
#
#  Flusso VIP (da home) — macchina a 3 stati con riconoscimento pallino rosso:
#
#    STATO 0 — APERTURA MASCHERA:
#      1. Tap badge VIP (85, 52) → apre maschera VIP
#      2. Attendi 2.0s caricamento
#
#    STATO 1 — CASSAFORTE (riconoscimento pallino rosso):
#      1. Screenshot → cerca pallino rosso in CASSAFORTE_BADGE_ZONA (810,130,900,195)
#      2. Se trovato  → tap (830, 160) → attendi → dismiss popup
#      3. Se assente  → skip (già ritirato oggi)
#
#    STATO 2 — CLAIM FREE (riconoscimento pallino rosso):
#      1. Screenshot → cerca pallino rosso in CLAIM_FREE_BADGE_ZONA (650,270,730,320)
#      2. Se trovato  → tap centro zona → attendi → dismiss popup
#      3. Se assente  → skip (già ritirato oggi)
#      4. BACK → torna in home
#
#  Logica pallino rosso:
#    Stessa tecnica usata in radar_show.py:
#    maschera pixel rossi (R > R_MIN, G < G_MAX, B < B_MAX),
#    conta pixel → se >= BADGE_PX_MIN il badge è presente.
#    Zona più piccola = meno falsi positivi rispetto al template matching.
#
#  Configurazione (config.py / runtime.json):
#    DAILY_VIP_ABILITATO      (bool, default True)
#    DAILY_RADAR_ABILITATO    (bool, default True)
#
#  Schedulazione: integrata in scheduler.py (task "vip", intervallo 24h)
#  Stato: sezione "schedule" del file istanza_stato_{nome}_{porta}.json
#
#  Coordinate (960x540):
#    TAP_VIP_BADGE            = (85,  52)   — badge VIP in home → apre maschera
#    TAP_VIP_CLAIM_CASSAFORTE = (830, 160)  — Claim cassaforte
#    TAP_VIP_POPUP_DISMISS    = (480, 270)  — centro popup report ricompense
#    CASSAFORTE_BADGE_ZONA    = (810, 130, 900, 195)  — zona pallino rosso cassaforte
#    CLAIM_FREE_BADGE_ZONA    = (650, 270, 730, 320)  — zona pallino rosso claim free (solo detection)
#    TAP_VIP_CLAIM_FREE       = (575, 380)             — tap centro card Claim Free Daily
#
#  NOTE:
#    - Il pulsante a pagamento (€99.99) NON viene mai toccato.
#      Entrambe le zone riconosciute (cassaforte + claim free) escludono
#      deliberatamente l'area del pulsante premium.
#    - Il bug fix V5.20: aggiunto BACK prima di vai_in_home nel finally.
# ==============================================================================

import os
import time
import numpy as np
from PIL import Image

import adb
import scheduler
import config
import stato as _stato
import radar_show as _radar

# --- Coordinate maschera VIP ---
TAP_VIP_BADGE            = (85,  52)   # badge VIP in home → apre maschera
TAP_VIP_CLAIM_CASSAFORTE = (830, 160)  # Claim cassaforte (in alto a destra)
TAP_VIP_POPUP_DISMISS    = (480, 270)  # centro popup report ricompense → dismissione

# --- Zone riconoscimento pallino rosso ---
# Zona cassaforte: area intorno al cofanetto in alto a destra nella maschera VIP
# Calibrata su vip_7.png (960x540): cofanetto a ~(860,160), badge rosso in alto a dx
CASSAFORTE_BADGE_ZONA = (810, 130, 900, 195)

# Zona claim free: SOLO per rilevare il pallino rosso nell'angolo top-right della card.
# Calibrata su vip_6.png (960x540): badge rosso a ~(700, 295).
# NON usare il centro di questa zona per il tap — usare TAP_VIP_CLAIM_FREE sotto.
CLAIM_FREE_BADGE_ZONA = (650, 270, 730, 320)

# Coordinata tap per attivare "Claim Free Daily" — centro della card viola.
# Separata dalla zona badge: il pallino rosso è in alto a dx della card,
# il pulsante attivo è il centro/corpo della card a ~(575, 380).
TAP_VIP_CLAIM_FREE = (575, 380)

# --- Parametri rilevamento pallino rosso (condivisi con radar_show.py) ---
BADGE_R_MIN  = getattr(config, "RADAR_BADGE_R_MIN",  150)
BADGE_G_MAX  = getattr(config, "RADAR_BADGE_G_MAX",  80)
BADGE_B_MAX  = getattr(config, "RADAR_BADGE_B_MAX",  80)
BADGE_PX_MIN = 5   # pixel rossi minimi per considerare il badge presente

# Retry per lettura badge (in caso di screenshot instabile)
BADGE_RETRY     = 2
BADGE_RETRY_S   = 0.8   # secondi tra retry


# ------------------------------------------------------------------------------
# Rilevamento pallino rosso — nucleo algoritmo
# Stessa logica di radar_show._ha_badge_radar(), generalizzata per zona arbitraria
# ------------------------------------------------------------------------------

def _ha_badge_rosso(screen_path: str, zona: tuple) -> bool:
    """
    Verifica se esiste un pallino rosso (badge notifica) nella zona specificata.

    Parametri:
      screen_path : path screenshot 960x540
      zona        : (x1, y1, x2, y2) — area di ricerca assoluta

    Ritorna:
      True  → badge presente (>=BADGE_PX_MIN pixel rossi trovati)
      False → badge assente
      True  → in caso di errore (fail-safe: meglio tappare che saltare)
    """
    try:
        img = Image.open(screen_path)
        arr = np.array(img)
        x1, y1, x2, y2 = zona
        roi = arr[y1:y2, x1:x2, :3]

        r = roi[:, :, 0].astype(int)
        g = roi[:, :, 1].astype(int)
        b = roi[:, :, 2].astype(int)

        rossi = ((r > BADGE_R_MIN) & (g < BADGE_G_MAX) & (b < BADGE_B_MAX))
        return int(rossi.sum()) >= BADGE_PX_MIN

    except Exception:
        return True  # fail-safe


def _leggi_badge_con_retry(porta: str, zona: tuple, label: str, log_fn) -> bool:
    """
    Scatta screenshot con retry e verifica badge rosso nella zona.
    Ritorna True se badge trovato, False se assente dopo tutti i retry.
    """
    for tentativo in range(1, BADGE_RETRY + 1):
        screen = adb.screenshot(porta)
        if not screen:
            log_fn(f"VIP {label}: screenshot fallito (tentativo {tentativo}/{BADGE_RETRY})")
            time.sleep(BADGE_RETRY_S)
            continue

        trovato = _ha_badge_rosso(screen, zona)
        log_fn(f"VIP {label}: badge {'TROVATO' if trovato else 'assente'} (tentativo {tentativo})")
        return trovato

    # Tutti i retry falliti per screenshot → fail-safe True
    log_fn(f"VIP {label}: tutti gli screenshot falliti — fail-safe True")
    return True


# ------------------------------------------------------------------------------
# Task VIP — ritira ricompense giornaliere (macchina a 3 stati)
# ------------------------------------------------------------------------------

def _esegui_vip(porta: str, nome: str, logger=None) -> bool:
    """
    Ritira le ricompense VIP giornaliere dalla home.

    Flusso a 3 stati:
      STATO 0 — APERTURA:  tap badge VIP → attendi maschera
      STATO 1 — CASSAFORTE: riconoscimento pallino rosso + tap condizionale
      STATO 2 — CLAIM FREE: riconoscimento pallino rosso + tap condizionale
      CHIUSURA: BACK → home

    Il pulsante a pagamento (€99.99) non viene mai toccato.
    Ritorna True se completato senza errori bloccanti.
    """
    def log(msg):
        if logger: logger(nome, msg)

    # Verifica stato: deve essere in home prima di aprire la maschera VIP
    if not _stato.vai_in_home(porta, nome, logger):
        log("VIP: impossibile raggiungere home — skip")
        return False

    try:
        # ------------------------------------------------------------------
        # STATO 0 — APERTURA MASCHERA VIP
        # ------------------------------------------------------------------
        log("VIP: [0/2] tap badge VIP → apertura maschera")
        adb.tap(porta, TAP_VIP_BADGE)
        time.sleep(2.0)   # attesa caricamento maschera

        # ------------------------------------------------------------------
        # STATO 1 — CASSAFORTE
        # ------------------------------------------------------------------
        log("VIP: [1/2] verifica badge rosso cassaforte")
        ha_cassaforte = _leggi_badge_con_retry(
            porta, CASSAFORTE_BADGE_ZONA, "cassaforte", log
        )

        if ha_cassaforte:
            log("VIP: [1/2] badge cassaforte presente → tap Claim")
            adb.tap(porta, TAP_VIP_CLAIM_CASSAFORTE)
            time.sleep(2.5)  # attesa animazione ricompensa (aumentato per popup lenta)
            log("VIP: [1/2] dismiss popup report ricompense")
            adb.tap(porta, TAP_VIP_POPUP_DISMISS)
            time.sleep(0.8)
            # Secondo tap dismiss per sicurezza — se la popup è ancora aperta
            adb.tap(porta, TAP_VIP_POPUP_DISMISS)
            time.sleep(1.2)  # attesa chiusura popup
        else:
            log("VIP: [1/2] badge cassaforte assente → skip (già ritirato)")

        # ------------------------------------------------------------------
        # STATO 2 — CLAIM FREE DAILY
        # ------------------------------------------------------------------
        log("VIP: [2/2] verifica badge rosso Claim Free Daily")
        ha_claim_free = _leggi_badge_con_retry(
            porta, CLAIM_FREE_BADGE_ZONA, "claim_free", log
        )

        if ha_claim_free:
            # Tap sul centro della card "Claim Free Daily" — NON sul badge.
            # Il badge rosso è nell'angolo top-right della card; tapparlo
            # elimina il pallino ma non attiva il pulsante di claim.
            log(f"VIP: [2/2] badge claim free presente → tap {TAP_VIP_CLAIM_FREE}")
            adb.tap(porta, TAP_VIP_CLAIM_FREE)
            time.sleep(1.5)  # attesa animazione ricompensa
            log("VIP: [2/2] dismiss popup report ricompense")
            adb.tap(porta, TAP_VIP_POPUP_DISMISS)
            time.sleep(1.0)
        else:
            log("VIP: [2/2] badge claim free assente → skip (già ritirato oggi)")

        log("VIP: ricompense giornaliere completate")
        return True

    except Exception as e:
        log(f"VIP: errore durante esecuzione: {e}")
        return False
    finally:
        # Chiudi maschera VIP con BACK — sempre, anche in caso di errore
        # Due BACK per chiudere sia eventuali popup interni che la maschera VIP
        try:
            adb.keyevent(porta, "KEYCODE_BACK")
            time.sleep(0.8)
            adb.keyevent(porta, "KEYCODE_BACK")
            time.sleep(1.2)
        except Exception:
            pass


# ------------------------------------------------------------------------------
# Entry point — esegui tutti i daily task schedulati
# ------------------------------------------------------------------------------

def esegui_daily_tasks(porta: str, nome: str, logger=None, coords=None) -> dict:
    """
    Esegue tutti i daily task abilitati per l'istanza, rispettando la schedulazione.

    Chiamare da raccolta_istanza() prima di vai_in_mappa, mentre si è in home.

    Parametri:
      coords: UICoords dell'istanza (usato per radar; non più necessario per VIP
              che ora usa il riconoscimento pallino rosso invece dei template)

    Ritorna dict con esito per ogni task:
      {"vip": True/False/None, "radar": True/False/None}
      None = saltato (già eseguito oggi o disabilitato)
    """
    def log(msg):
        if logger: logger(nome, msg)

    esiti = {}

    # --- Task VIP ---
    if getattr(config, "DAILY_VIP_ABILITATO", True):
        if scheduler.deve_eseguire(nome, porta, "vip", logger):
            ok = _esegui_vip(porta, nome, logger=logger)
            esiti["vip"] = ok
            if ok:
                scheduler.registra_esecuzione(nome, porta, "vip")
        else:
            esiti["vip"] = None  # saltato — già eseguito oggi
    else:
        log("[DAILY] VIP disabilitato (DAILY_VIP_ABILITATO=False) — skip")
        esiti["vip"] = None

    # --- Torna in home tra VIP e Radar ---
    # Il finally del VIP manda KEYCODE_BACK ma potrebbe non essere sufficiente
    # a chiudere completamente la maschera prima che Radar parta.
    # Forziamo vai_in_home esplicito con attesa minima.
    if not _stato.vai_in_home(porta, nome, logger):
        log("[DAILY] Impossibile raggiungere home prima di Radar — skip")
        esiti["radar"] = False
        return esiti

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


# ------------------------------------------------------------------------------
# Entry point separati per raccolta.py — ogni task ha il proprio _run_guarded
# ------------------------------------------------------------------------------

def esegui_vip_guarded(porta: str, nome: str, logger=None) -> bool:
    """
    Esegue solo il task VIP se schedulato e abilitato.
    Chiamare da raccolta.py wrappato in _run_guarded("VIP", ...).
    """
    def log(msg):
        if logger: logger(nome, msg)

    if not getattr(config, "DAILY_VIP_ABILITATO", True):
        log("[DAILY] VIP disabilitato — skip")
        return True

    if not scheduler.deve_eseguire(nome, porta, "vip", logger):
        return True  # già eseguito, non è un errore

    ok = _esegui_vip(porta, nome, logger=logger)
    if ok:
        scheduler.registra_esecuzione(nome, porta, "vip")
    return ok


def esegui_radar_guarded(porta: str, nome: str, logger=None, coords=None) -> bool:
    """
    Esegue solo il task Radar se schedulato e abilitato.
    Chiamare da raccolta.py wrappato in _run_guarded("Radar", ...).
    """
    def log(msg):
        if logger: logger(nome, msg)

    if not getattr(config, "DAILY_RADAR_ABILITATO", True):
        log("[DAILY] Radar disabilitato — skip")
        return True

    if not scheduler.deve_eseguire(nome, porta, "radar", logger):
        return True  # già eseguito, non è un errore

    ok = _radar.esegui_radar_show(porta, nome, coords=coords, logger=logger)
    if ok:
        scheduler.registra_esecuzione(nome, porta, "radar")
    return ok
