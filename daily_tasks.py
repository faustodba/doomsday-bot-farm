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
#    TAP_VIP_DISMISS_CASS    = (481, 381)  — tap testo popup cassaforte (chiude popup)
#    TAP_VIP_DISMISS_FREE    = (483, 391)  — tap testo popup Claim Free (chiude popup)
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
from verifica_ui import VerificaUI, _match

# ==============================================================================
# COORDINATE E COSTANTI VIP
# ==============================================================================

# --- Tap principali ---
TAP_VIP_BADGE            = (85,  52)   # badge VIP in home → apre maschera
TAP_VIP_CLAIM_CASSAFORTE = (830, 160)  # Claim cassaforte (in alto a destra)
TAP_VIP_CLAIM_FREE       = (526, 444)  # centro card "Claim Free Daily"

# Dismiss popup ricompense: tap direttamente sul testo identificativo del popup.
# Il testo è sia il pin di rilevamento che il punto di chiusura.
#   popup cassaforte: "The more consecutive days..." → centro (481,381)
#   popup free:       "You received the Daily VIP Reward!" → centro (483,391)
TAP_VIP_DISMISS_CASS = (481, 381)
TAP_VIP_DISMISS_FREE = (483, 391)

# ==============================================================================
# PIN VIP — template matching per verifica precondizioni
#
#  pin_vip_01_store.png      ROI=(118,109,287,158)  soglia=0.80
#    → maschera VIP aperta — testo "Today's VIP Points: 200" visibile
#      (più stabile di "VIP Store": non viene coperto dai banner laterali)
#
#  pin_vip_02_cass_chiusa.png ROI=(778,98,866,203)  soglia=0.80
#    → cassaforte disponibile (icona chiusa + pulsante Claim)
#
#  pin_vip_03_cass_aperta.png ROI=(799,89,866,172)  soglia=0.75
#    → cassaforte già ritirata (icona aperta + timer countdown)
#
#  pin_vip_04_free_chiuso.png ROI=(465,423,674,483) soglia=0.80
#    → Claim Free disponibile (pulsante CLAIM verde visibile)
#
#  pin_vip_05_free_aperto.png ROI=(540,298,605,368) soglia=0.80
#    → Claim Free già ritirato (card con checkmark dorato)
#
#  pin_vip_06_popup_cass.png  ROI=(308,345,654,417) soglia=0.80
#    → popup ricompense cassaforte aperto (testo "The more consecutive...")
#
#  pin_vip_07_popup_free.png  ROI=(308,345,654,417) soglia=0.80
#    → popup ricompense Claim Free aperto (testo "You received the Daily VIP Reward!")
#
# Tutti i pin vanno in: C:\Bot-farm\templates\
# ==============================================================================

_VIP_PIN = {
    "store":       ("pin_vip_01_store.png",       (118, 109, 287, 158), 0.80),
    "cass_chiusa": ("pin_vip_02_cass_chiusa.png",  (778, 98,  866, 203), 0.80),
    "cass_aperta": ("pin_vip_03_cass_aperta.png",  (799, 89,  866, 172), 0.75),
    "free_chiuso": ("pin_vip_04_free_chiuso.png",  (465, 423, 674, 483), 0.80),
    "free_aperto": ("pin_vip_05_free_aperto.png",  (540, 298, 605, 368), 0.80),
    "popup_cass":  ("pin_vip_06_popup_cass.png",   (308, 345, 654, 417), 0.80),
    "popup_free":  ("pin_vip_07_popup_free.png",   (308, 345, 654, 417), 0.80),
}


def _vip_check(screen: str, key: str, log_fn=None) -> bool:
    """
    Verifica un pin VIP su uno screen già scattato.
    Ritorna True se il pin è visibile, False altrimenti.
    Logga sempre il risultato con score.
    """
    tmpl, roi, soglia = _VIP_PIN[key]
    score = _match(screen, tmpl, roi)
    ok = score >= soglia
    if log_fn:
        stato_str = "OK" if ok else "NON trovato"
        log_fn(f"[VIP-PIN] {key}: score={score:.3f} soglia={soglia} → {stato_str}")
    return ok


def _vip_screen_check(porta: str, key: str, log_fn=None, retry: int = 1,
                      retry_s: float = 1.0) -> tuple:
    """
    Scatta screenshot e verifica pin VIP. Con retry opzionale.
    Ritorna (ok: bool, screen: str).
    """
    for tentativo in range(retry + 1):
        screen = adb.screenshot(porta)
        if not screen:
            if log_fn:
                log_fn(f"[VIP-PIN] {key}: screenshot fallito (tentativo {tentativo+1})")
            time.sleep(retry_s)
            continue
        ok = _vip_check(screen, key, log_fn)
        if ok or tentativo == retry:
            return ok, screen
        time.sleep(retry_s)
    return False, ""


# ==============================================================================
# PULIZIA BANNER HOME
# La logica è centralizzata in stato.py (home_pulita / pulisci_banner_home).
# daily_tasks.py usa direttamente _stato.pulisci_banner_home().
# ==============================================================================


# ------------------------------------------------------------------------------
# Task VIP — ritira ricompense giornaliere con precondizioni pin
# ------------------------------------------------------------------------------

def _esegui_vip(porta: str, nome: str, logger=None) -> bool:
    """
    Ritira le ricompense VIP giornaliere.

    Logica a tentativi (max 3):
      Per ogni tentativo:
        1. vai_in_home
        2. tap badge VIP
           [PRE-VIP] pin_vip_01_store visibile?
             NO → 3x BACK + vai_in_home → prossimo tentativo
             SI → procedi

        3. CASSAFORTE
           [CHECK] pin_vip_02_cass_chiusa → disponibile
                   pin_vip_03_cass_aperta → già ritirata → cass_ok=True
           se disponibile:
             tap Claim cassaforte
             [PRE-POPUP-C]  pin_vip_06_popup_cass visibile?
             tap dismiss
             [GATE-C]       pin_vip_01_store tornato visibile?
             [POST-C]       pin_vip_03_cass_aperta visibile? → cass_ok=True

        4. CLAIM FREE
           [CHECK] pin_vip_04_free_chiuso → disponibile
                   pin_vip_05_free_aperto → già ritirato → free_ok=True
           se disponibile:
             tap Claim Free
             [PRE-POPUP-F]  pin_vip_07_popup_free visibile?
             tap dismiss
             [GATE-F]       pin_vip_01_store tornato visibile?
             [POST-F]       pin_vip_05_free_aperto visibile? → free_ok=True

        5. STEP 5 — successo solo se cass_ok AND free_ok
             SI → BACK + vai_in_home → return True
             NO → BACK + vai_in_home → prossimo tentativo

    Ritorna True solo a ricompense entrambe confermate.
    False → verrà riprovato al prossimo ciclo (registra_esecuzione NON chiamato).
    """
    def log(msg):
        if logger: logger(nome, msg)

    MAX_TENTATIVI = 3

    for tentativo in range(1, MAX_TENTATIVI + 1):
        log(f"VIP: tentativo {tentativo}/{MAX_TENTATIVI}")

        # ── STEP 1: home pulita ───────────────────────────────────────────
        if not _stato.vai_in_home(porta, nome, logger):
            log(f"VIP: impossibile raggiungere home (t={tentativo}) — prossimo tentativo")
            continue

        # ── STEP 2: tap badge VIP + [PRE-VIP] ────────────────────────────
        log("VIP: tap badge VIP → apertura maschera")
        adb.tap(porta, TAP_VIP_BADGE)
        time.sleep(2.0)

        ok_store, _ = _vip_screen_check(porta, "store", log, retry=1, retry_s=1.5)
        if not ok_store:
            log("VIP: [PRE-VIP] maschera non aperta — banner? → 3x BACK + vai_in_home")
            for _ in range(3):
                adb.keyevent(porta, "KEYCODE_BACK")
                time.sleep(0.4)
            _stato.vai_in_home(porta, nome, logger)
            continue
        log("VIP: [PRE-VIP] pin_vip_01_store visibile — maschera aperta OK")

        # ── STEP 3: CASSAFORTE ───────────────────────────────────────────
        log("VIP: [1] verifica stato cassaforte")
        screen = adb.screenshot(porta)
        cass_chiusa = _vip_check(screen, "cass_chiusa", log)  # pin_vip_02
        cass_aperta = _vip_check(screen, "cass_aperta", log)  # pin_vip_03

        # cass_ok: True se già ritirata o confermata dopo claim
        cass_ok = cass_aperta  # path "già ritirata" → già True

        if cass_chiusa:
            log("VIP: [1] pin_vip_02 visibile — cassaforte disponibile → tap Claim")
            adb.tap(porta, TAP_VIP_CLAIM_CASSAFORTE)
            time.sleep(2.5)

            # [PRE-POPUP-C] pin_vip_06_popup_cass
            ok_popup_c, _ = _vip_screen_check(porta, "popup_cass", log, retry=1, retry_s=1.0)
            if ok_popup_c:
                log("VIP: [PRE-POPUP-C] pin_vip_06 visibile — popup aperto OK")
            else:
                log("VIP: [PRE-POPUP-C] ANOMALIA: popup_cass non visibile — tento dismiss")

            adb.tap(porta, TAP_VIP_DISMISS_CASS)

            # [GATE-C] pin_vip_01_store tornato visibile (max 5s)
            gate_c = False
            for _t in range(5):
                time.sleep(1.0)
                gate_c, _ = _vip_screen_check(porta, "store", log_fn=None, retry=0)
                if gate_c:
                    log(f"VIP: [GATE-C] pin_vip_01 tornato ({_t+1}s) — maschera VIP OK")
                    break
            if not gate_c:
                log("VIP: [GATE-C] ANOMALIA: maschera non tornata — retry dismiss")
                adb.tap(porta, TAP_VIP_DISMISS_CASS)
                # Secondo gate dopo retry dismiss (altri 5s)
                for _t in range(5):
                    time.sleep(1.0)
                    gate_c, _ = _vip_screen_check(porta, "store", log_fn=None, retry=0)
                    if gate_c:
                        log(f"VIP: [GATE-C] pin_vip_01 tornato al retry ({_t+1}s) — OK")
                        break
                if not gate_c:
                    log("VIP: [GATE-C] ANOMALIA: maschera ancora non tornata — procedo")

            # [POST-C] pin_vip_03_cass_aperta → conferma ritiro
            cass_ok, _ = _vip_screen_check(porta, "cass_aperta", log, retry=1, retry_s=1.0)
            if cass_ok:
                log("VIP: [POST-C] pin_vip_03 visibile — cassaforte ritirata confermata OK")
            else:
                log("VIP: [POST-C] ANOMALIA: pin_vip_03 non visibile — cassaforte non confermata")

        elif cass_aperta:
            log("VIP: [1] pin_vip_03 visibile — cassaforte già ritirata oggi → skip")
            # cass_ok già True
        else:
            log("VIP: [1] ANOMALIA: nessun pin cassaforte rilevato — skip")
            # cass_ok rimane False

        # ── STEP 4: CLAIM FREE DAILY ─────────────────────────────────────
        log("VIP: [2] verifica stato Claim Free Daily")
        screen = adb.screenshot(porta)
        free_chiuso = _vip_check(screen, "free_chiuso", log)  # pin_vip_04
        free_aperto = _vip_check(screen, "free_aperto", log)  # pin_vip_05

        # free_ok: True se già ritirato o confermato dopo claim
        free_ok = free_aperto  # path "già ritirato" → già True

        if free_chiuso:
            log(f"VIP: [2] pin_vip_04 visibile — Claim Free disponibile → tap {TAP_VIP_CLAIM_FREE}")
            adb.tap(porta, TAP_VIP_CLAIM_FREE)
            time.sleep(2.0)

            # [PRE-POPUP-F] pin_vip_07_popup_free
            ok_popup_f, _ = _vip_screen_check(porta, "popup_free", log, retry=1, retry_s=1.0)
            if ok_popup_f:
                log("VIP: [PRE-POPUP-F] pin_vip_07 visibile — popup aperto OK")
            else:
                log("VIP: [PRE-POPUP-F] ANOMALIA: popup_free non visibile — tento dismiss")

            adb.tap(porta, TAP_VIP_DISMISS_FREE)

            # [GATE-F] Attende che il popup si chiuda e la maschera VIP torni visibile.
            # Il popup free è più lento a chiudersi rispetto al popup cassaforte.
            # Polling su pin_vip_01_store con finestra più ampia (8s invece di 5s).
            gate_f = False
            for _t in range(8):
                time.sleep(1.0)
                gate_f, _ = _vip_screen_check(porta, "store", log_fn=None, retry=0)
                if gate_f:
                    log(f"VIP: [GATE-F] pin_vip_01 tornato ({_t+1}s) — maschera VIP OK")
                    break
            if not gate_f:
                log("VIP: [GATE-F] ANOMALIA: maschera non tornata — retry dismiss")
                adb.tap(porta, TAP_VIP_DISMISS_FREE)
                for _t in range(8):
                    time.sleep(1.0)
                    gate_f, _ = _vip_screen_check(porta, "store", log_fn=None, retry=0)
                    if gate_f:
                        log(f"VIP: [GATE-F] pin_vip_01 tornato al retry ({_t+1}s) — OK")
                        break
                if not gate_f:
                    log("VIP: [GATE-F] ANOMALIA: maschera ancora non tornata — procedo")

            # [POST-F] pin_vip_05_free_aperto → conferma ritiro
            free_ok, _ = _vip_screen_check(porta, "free_aperto", log, retry=2, retry_s=1.0)
            if free_ok:
                log("VIP: [POST-F] pin_vip_05 visibile — Claim Free ritirato confermato OK")
            else:
                log("VIP: [POST-F] ANOMALIA: pin_vip_05 non visibile — Claim Free non confermato")

        elif free_aperto:
            log("VIP: [2] pin_vip_05 visibile — Claim Free già ritirato oggi → skip")
            # free_ok già True
        else:
            log("VIP: [2] ANOMALIA: nessun pin Claim Free rilevato — skip")
            # free_ok rimane False

        # ── STEP 5: verifica successo completo ───────────────────────────
        log(f"VIP: stato finale → cass={'OK' if cass_ok else 'KO'} "
            f"free={'OK' if free_ok else 'KO'}")

        # Chiudi maschera prima di tornare in home.
        # IMPORTANTE: vai_in_home() usa pixel check su (40,505) che può dare
        # falso positivo se si è ancora sulla maschera VIP (pixel scuro in quella zona).
        # I BACK espliciti svuotano lo stack UI prima che vai_in_home verifichi.
        for _ in range(3):
            adb.keyevent(porta, "KEYCODE_BACK")
            time.sleep(0.5)
        time.sleep(0.5)
        _stato.vai_in_home(porta, nome, logger)

        if cass_ok and free_ok:
            log("VIP: entrambe le ricompense confermate — completato ✓")
            return True

        log(f"VIP: tentativo {tentativo} incompleto — "
            f"{'altro tentativo' if tentativo < MAX_TENTATIVI else 'fallito dopo tutti i tentativi'}")

    log(f"VIP: fallito dopo {MAX_TENTATIVI} tentativi — verrà riprovato al prossimo ciclo")
    return False


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
    # BACK espliciti per svuotare lo stack UI prima che vai_in_home verifichi
    # con pixel check (che potrebbe dare falso positivo se ancora su overlay VIP).
    for _ in range(3):
        adb.keyevent(porta, "KEYCODE_BACK")
        time.sleep(0.5)
    time.sleep(0.5)
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


def esegui_arena_guarded(porta: str, nome: str, logger=None) -> bool:
    """
    Esegue solo il task Arena of Glory se schedulato e abilitato.
    Chiamare da raccolta.py wrappato in _run_guarded("Arena", ...).
    Schedulazione: 24h (SCHEDULE_ORE_ARENA), chiave "arena" in istanza_stato.
    """
    def log(msg):
        if logger: logger(nome, msg)

    if not getattr(config, "ARENA_OF_GLORY_ABILITATO", False):
        log("[DAILY] Arena disabilitata — skip")
        return True

    if not scheduler.deve_eseguire(nome, porta, "arena", logger):
        return True  # già eseguita oggi, non è un errore

    import arena_of_glory as _arena
    adb_exe = getattr(config, "MUMU_ADB", "") or getattr(config, "ADB_EXE", "")
    res = _arena.run_arena_of_glory(adb_exe=adb_exe, porta=porta)

    eseguita = res.get("sfide_eseguite", 0) > 0 or res.get("esaurite", False)
    if eseguita:
        scheduler.registra_esecuzione(nome, porta, "arena")
        log(f"[DAILY] Arena: {res['sfide_eseguite']} sfide"
            + (" (esaurite)" if res["esaurite"] else ""))
    else:
        log("[DAILY] Arena: nessuna sfida eseguita — ts non aggiornato")

    return res.get("errore") is None


def esegui_mercato_arena_guarded(porta: str, nome: str, logger=None) -> bool:
    """
    Esegue solo il task Mercato Arena se schedulato e abilitato.
    Chiamare da raccolta.py wrappato in _run_guarded("Arena Mercato", ...).
    Schedulazione: SCHEDULE_ORE_ARENA_MERCATO (default 4h), chiave "arena_mercato".
    """
    def log(msg):
        if logger: logger(nome, msg)

    if not getattr(config, "ARENA_MERCATO_ABILITATO", False):
        log("[DAILY] Arena Mercato disabilitato — skip")
        return True

    if not scheduler.deve_eseguire(nome, porta, "arena_mercato", logger):
        return True  # già eseguito nelle ultime 4h

    import arena_of_glory as _arena
    adb_exe = getattr(config, "MUMU_ADB", "") or getattr(config, "ADB_EXE", "")
    res = _arena.run_mercato_arena(
        adb_exe=adb_exe,
        porta=porta,
        log_fn=lambda m: logger(nome, m) if logger else None,
    )

    # Registra sempre — anche acquisti=0 significa "visitato, niente da comprare"
    scheduler.registra_esecuzione(nome, porta, "arena_mercato")
    log(f"[DAILY] Arena Mercato: {res.get('acquisti', 0)} cicli acquisto"
        + (f" — errore: {res['errore']}" if res.get("errore") else ""))

    return res.get("errore") is None
