# ==============================================================================
#  DOOMSDAY BOT V5 - rifornimento_mappa.py
#  Invio risorse al rifugio alleato via coordinate mappa (alternativo a rifornimento.py)
#
#  Differenza rispetto a rifornimento.py:
#    La navigazione avviene tramite coordinate mappa invece della lista Membri.
#    Il loop multi-spedizione resta in mappa tra una spedizione e l'altra,
#    eliminando i cicli home↔mappa ripetuti (più veloce e meno transizioni UI).
#
#  Flusso ottimizzato:
#    HOME → Mappa (una sola volta)
#    Loop spedizioni:
#      → centra mappa sul rifugio → tap castello → RESOURCE SUPPLY → VAI
#      → slot/risorse lette dalla mappa (senza tornare in home)
#      → se slot==0: attendi in mappa → riprendi
#    Fine loop → torna in HOME
#    Fallback HOME solo in caso di errore
#
#  Flag abilitazione: RIFORNIMENTO_MAPPA_ABILITATO in config.py / runtime.json
#  Coordinate rifugio: RIFUGIO_X, RIFUGIO_Y (hardcoded — TODO: esternalizzare)
# ==============================================================================

import time
from collections import deque
import os

import cv2
import numpy as np

import adb
import ocr
import stato
import config
import log as _log
import status as _status

# Riusa da rifornimento.py tutte le funzioni invariate
from rifornimento import (
    _controlla_reset,
    _salva_stato,
    _slot_liberi,
    _compila_e_invia,
    QTA_DEFAULT,
)

# ── Coordinate rifugio destinatario (hardcoded — TODO: esternalizzare) ─────────
RIFUGIO_X = 684
RIFUGIO_Y = 532

# ── Coordinate UI 960x540 — navigazione mappa ──────────────────────────────────
TAP_LENTE_MAPPA     = (334,  13)   # lente coordinate sulla mappa
TAP_CAMPO_X         = (484, 135)   # campo X nella lente
TAP_CAMPO_Y         = (601, 135)   # campo Y nella lente
TAP_CONFERMA_LENTE  = (670, 135)   # conferma → centra mappa
TAP_CASTELLO_CENTER = (480, 270)   # centro schermo dopo centratura

# ── Template RESOURCE SUPPLY ───────────────────────────────────────────────────
TEMPLATE_RESOURCE_SUPPLY = os.path.join(
    config.BOT_DIR, "templates", "btn_resource_supply_map.png"
)
TEMPLATE_SOGLIA = 0.75

# ── Flag abilitazione ──────────────────────────────────────────────────────────
RIFORNIMENTO_MAPPA_ABILITATO = False

# ── Margine attesa slot (secondi extra dopo ETA A/R stimata) ───────────────────
MARGINE_ATTESA = 8


# ------------------------------------------------------------------------------
# Navigazione mappa — centra e apre maschera RESOURCE SUPPLY
# ------------------------------------------------------------------------------

def _centra_e_apri_maschera(porta: str, logger=None, nome: str = "",
                             x: int = None, y: int = None) -> bool:
    """
    Dalla mappa (già aperta): centra sul rifugio, tappa il castello,
    trova RESOURCE SUPPLY via template e lo tappa.

    Precondizione: gioco già in mappa.
    Ritorna True se la maschera invio è aperta, False altrimenti.
    """
    def log(msg):
        if logger: logger(nome, f"[RIFMAP] {msg}")

    rx = x if x is not None else RIFUGIO_X
    ry = y if y is not None else RIFUGIO_Y

    # 1. Centra mappa sul rifugio
    log(f"Centratura mappa su rifugio X:{rx} Y:{ry}")
    adb.tap(porta, TAP_LENTE_MAPPA)
    time.sleep(1.5)

    adb.tap(porta, TAP_CAMPO_X)
    time.sleep(0.4)
    for _ in range(6):
        adb.keyevent(porta, "KEYCODE_DEL")
    time.sleep(0.2)
    adb.input_text(porta, str(rx))
    time.sleep(0.4)

    adb.tap(porta, TAP_CAMPO_Y)
    time.sleep(0.4)
    for _ in range(6):
        adb.keyevent(porta, "KEYCODE_DEL")
    time.sleep(0.2)
    adb.input_text(porta, str(ry))
    time.sleep(0.4)

    adb.tap(porta, TAP_CONFERMA_LENTE)
    time.sleep(2.5)
    log("Mappa centrata sul rifugio")

    # 2. Tap castello
    log(f"Tap castello a {TAP_CASTELLO_CENTER}")
    adb.tap(porta, TAP_CASTELLO_CENTER)
    time.sleep(2.0)

    # 3. Template matching RESOURCE SUPPLY
    screen = adb.screenshot(porta)
    if not screen:
        log("Screenshot fallito dopo tap castello")
        return False

    if not os.path.exists(TEMPLATE_RESOURCE_SUPPLY):
        log(f"Template non trovato: {TEMPLATE_RESOURCE_SUPPLY}")
        return False

    img  = cv2.imread(screen)
    tmpl = cv2.imread(TEMPLATE_RESOURCE_SUPPLY)
    if img is None or tmpl is None:
        log("Errore lettura immagine/template")
        return False

    result = cv2.matchTemplate(img, tmpl, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    log(f"Template RESOURCE SUPPLY score={max_val:.3f} (soglia={TEMPLATE_SOGLIA})")

    if max_val < TEMPLATE_SOGLIA:
        log("Pulsante RESOURCE SUPPLY non trovato nel popup")
        return False

    th, tw = tmpl.shape[:2]
    cx = max_loc[0] + tw // 2
    cy = max_loc[1] + th // 2
    log(f"Pulsante RESOURCE SUPPLY trovato a ({cx},{cy}) → tap")
    adb.tap(porta, (cx, cy))
    time.sleep(2.5)

    log("Maschera RESOURCE SUPPLY aperta")
    return True


def _leggi_risorse_mappa(porta: str, risorse_lista: list,
                          logger=None, nome: str = "") -> dict:
    """
    Legge il deposito risorse dalla mappa (barra in alto visibile anche in mappa).
    Ritorna dict {risorsa: valore} o {} se OCR fallisce.
    """
    def log(msg):
        if logger: logger(nome, f"[RIFMAP] {msg}")

    screen = adb.screenshot(porta)
    risorse = ocr.leggi_risorse(screen) if screen else {}

    if all(risorse.get(r, -1) < 0 for r in risorse_lista):
        log("OCR deposito fallito, attendo 3s e riprovo...")
        time.sleep(3.0)
        screen = adb.screenshot(porta)
        risorse = ocr.leggi_risorse(screen) if screen else {}

    return risorse


# ------------------------------------------------------------------------------
# Funzione principale — loop ottimizzato in mappa
# ------------------------------------------------------------------------------

def esegui_rifornimento_mappa(porta: str, nome: str,
                               pomodoro_m: float = -1, legno_m: float = -1,
                               acciaio_m: float = -1, petrolio_m: float = -1,
                               logger=None, ciclo: int = 0) -> int:
    """
    Esegue rifornimento risorse al rifugio alleato tramite navigazione mappa.

    Loop ottimizzato: resta in mappa tra una spedizione e l'altra.
    Torna in HOME solo a fine loop o in caso di errore.

    Ritorna numero di spedizioni effettuate.
    """
    def log(msg):
        if logger: logger(nome, f"[RIFMAP] {msg}")

    # Assicura ADB MuMu
    if getattr(config, "MUMU_ADB", ""):
        config.ADB_EXE = config.MUMU_ADB

    # Flag abilitazione
    if not getattr(config, "RIFORNIMENTO_MAPPA_ABILITATO", RIFORNIMENTO_MAPPA_ABILITATO):
        log("Modulo disabilitato (RIFORNIMENTO_MAPPA_ABILITATO=False) — skip")
        return 0

    # Controlla quota giornaliera
    if _controlla_reset(nome, porta, logger):
        return 0

    nome_rifugio = getattr(config, "DOOMS_ACCOUNT", "")
    if not nome_rifugio:
        log("DOOMS_ACCOUNT non configurato - skip")
        return 0

    # Soglie per risorsa
    soglie = {
        "pomodoro": getattr(config, "RIFORNIMENTO_SOGLIA_CAMPO_M",    5.0),
        "legno":    getattr(config, "RIFORNIMENTO_SOGLIA_LEGNO_M",    5.0),
        "petrolio": getattr(config, "RIFORNIMENTO_SOGLIA_PETROLIO_M", 2.5),
        "acciaio":  getattr(config, "RIFORNIMENTO_SOGLIA_ACCIAIO_M",  3.5),
    }

    # Flag abilitazione per-risorsa (False = salta sempre, indipendentemente dalla soglia)
    abilitati = {
        "pomodoro": getattr(config, "RIFORNIMENTO_CAMPO_ABILITATO",    True),
        "legno":    getattr(config, "RIFORNIMENTO_LEGNO_ABILITATO",    True),
        "petrolio": getattr(config, "RIFORNIMENTO_PETROLIO_ABILITATO", True),
        "acciaio":  getattr(config, "RIFORNIMENTO_ACCIAIO_ABILITATO",  False),
    }
    disabilitati = [r for r, v in abilitati.items() if not v]
    if disabilitati:
        log(f"Risorse disabilitate (flag): {disabilitati}")

    # Quantità per spedizione
    quantita = {
        "pomodoro": getattr(config, "RIFORNIMENTO_QTA_POMODORO", QTA_DEFAULT["pomodoro"]),
        "legno":    getattr(config, "RIFORNIMENTO_QTA_LEGNO",    QTA_DEFAULT["legno"]),
        "acciaio":  getattr(config, "RIFORNIMENTO_QTA_ACCIAIO",  QTA_DEFAULT["acciaio"]),
        "petrolio": getattr(config, "RIFORNIMENTO_QTA_PETROLIO", QTA_DEFAULT["petrolio"]),
    }

    risorse_config = {r: q for r, q in quantita.items()
                      if q > 0
                      and soglie.get(r, float("inf")) < float("inf")
                      and abilitati.get(r, True)}
    if not risorse_config:
        log("Nessuna risorsa configurata per l'invio - skip")
        return 0

    log(f"Risorse configurate: {list(risorse_config.keys())} | "
        f"soglie: { {r: f'{soglie[r]}M' for r in risorse_config} }")

    max_sped = int(getattr(config, "RIFORNIMENTO_MAX_SPEDIZIONI_CICLO", 5) or 0)
    if max_sped > 0:
        log(f"Limite spedizioni ciclo: {max_sped}")
    else:
        max_sped = None

    spedizioni    = 0
    risorse_lista = list(risorse_config.keys())
    idx_risorsa   = 0
    coda_volo: deque = deque()
    in_mappa      = False   # traccia se siamo già in mappa

    try:
        while True:
            # Stop se raggiunto il limite
            if max_sped is not None and spedizioni >= max_sped:
                log(f"Limite massimo spedizioni raggiunto ({spedizioni}/{max_sped})")
                break

            # ── 1. Controlla slot liberi ────────────────────────────────────────
            # Il contatore squadre è visibile sia in home che in mappa
            slot = _slot_liberi(porta)
            log(f"Slot liberi: {slot}")

            if slot == 0:
                if coda_volo:
                    ts_prima, eta_ar = coda_volo[0]
                    trascorso = time.time() - ts_prima
                    manca     = max(0.0, eta_ar - trascorso) + MARGINE_ATTESA
                    log(f"Slot occupati — ETA A/R {eta_ar:.0f}s → attendo {manca:.0f}s")
                    time.sleep(manca)
                    now = time.time()
                    while coda_volo and (now - coda_volo[0][0]) >= coda_volo[0][1]:
                        coda_volo.popleft()
                else:
                    log("Slot occupati, nessuna info in coda — attendo 120s")
                    time.sleep(120)

                slot = _slot_liberi(porta)
                log(f"Slot dopo attesa: {slot}")
                if slot == 0:
                    log("Nessun slot libero dopo attesa - stop")
                    break

            # ── 2. Leggi deposito risorse ───────────────────────────────────────
            # Prima spedizione: vai in mappa; spedizioni successive: già in mappa
            if not in_mappa:
                if not stato.vai_in_mappa(porta, nome, logger):
                    log("Impossibile andare in mappa — stop")
                    break
                in_mappa = True
                time.sleep(1.5)

            risorse_reali = _leggi_risorse_mappa(porta, risorse_lista, logger, nome)
            if all(risorse_reali.get(r, -1) < 0 for r in risorse_lista):
                log("OCR deposito fallito dopo retry — stop")
                break

            log("Deposito: " + " | ".join(
                f"{r}={max(0.0, risorse_reali.get(r,-1))/1e6:.1f}M"
                for r in risorse_lista if risorse_reali.get(r,-1) >= 0
            ))

            # ── 3. Seleziona risorsa ────────────────────────────────────────────
            risorsa_scelta = None
            for i in range(len(risorse_lista)):
                r          = risorse_lista[(idx_risorsa + i) % len(risorse_lista)]
                valore_r   = risorse_reali.get(r, -1)
                soglia_abs = soglie.get(r, float("inf")) * 1e6
                log(f"  Check {r}: {valore_r/1e6:.1f}M soglia={soglie[r]}M → "
                    f"{'OK' if valore_r >= soglia_abs else 'SOTTO'}")
                if valore_r >= soglia_abs:
                    risorsa_scelta = r
                    idx_risorsa = (idx_risorsa + i + 1) % len(risorse_lista)
                    break

            if not risorsa_scelta:
                log("Tutte le risorse sotto soglia - stop")
                break

            log(f"Risorsa selezionata: {risorsa_scelta}")
            risorse_pre = risorse_reali

            # ── 4. Centra mappa e apri maschera ────────────────────────────────
            # (già in mappa — nessuna transizione home↔mappa)
            retry_nome_done = False
            stop_esterno    = False
            eta_sec         = 0
            qta_inviata     = 0
            ts_invio        = time.time()

            while True:
                if not _centra_e_apri_maschera(porta, logger, nome):
                    log("Navigazione mappa fallita — fallback HOME e stop")
                    # Fallback: torna in home in caso di errore
                    for _ in range(5):
                        adb.keyevent(porta, "KEYCODE_BACK")
                        time.sleep(0.5)
                    stato.vai_in_home(porta, nome, logger)
                    in_mappa = False
                    stop_esterno = True
                    break

                # ── 5. Compila e invia ──────────────────────────────────────────
                ts_invio = time.time()
                ok, eta_sec, quota_esaurita, qta_inviata, mismatch_nome = _compila_e_invia(
                    porta, {risorsa_scelta: risorse_config[risorsa_scelta]},
                    nome_rifugio, logger, nome
                )

                if quota_esaurita:
                    log("Provviste giornaliere esaurite - stop")
                    # Chiudi la maschera prima di procedere
                    adb.keyevent(porta, "KEYCODE_BACK")
                    time.sleep(1.0)
                    _salva_stato(nome, str(porta), True)
                    log("Quota giornaliera salvata nello stato istanza")
                    stop_esterno = True
                    break

                if mismatch_nome and not retry_nome_done:
                    log("DEST MISMATCH: retry 1")
                    retry_nome_done = True
                    # Il gioco ha fatto BACK → siamo ancora in mappa
                    time.sleep(1.0)
                    continue

                if not ok:
                    log("Invio fallito — tentativo BACK e stop spedizione")
                    adb.keyevent(porta, "KEYCODE_BACK")
                    time.sleep(0.5)
                    # Restiamo in mappa, interrompiamo questa spedizione
                    break

                break  # OK

            if stop_esterno:
                break

            if qta_inviata <= 0:
                # Spedizione fallita ma non errore bloccante — riprova dal prossimo giro
                continue

            # ── 6. Post-spedizione: siamo in mappa, aggiorna stato ─────────────
            spedizioni += 1
            eta_ar = eta_sec * 2
            coda_volo.append((ts_invio, eta_ar))
            log(f"Spedizione {spedizioni}: {risorsa_scelta} {qta_inviata:,} | "
                f"ETA A/R {eta_ar}s | In volo: {len(coda_volo)}")
            _log.registra_evento(ciclo, nome, "rifornimento_mappa_ok", spedizioni, 1,
                                 f"risorsa={risorsa_scelta}")

            # Breve attesa stabilizzazione UI dopo VAI (siamo in mappa)
            time.sleep(2.0)

            # ── 7. Snapshot POST-invio dalla mappa ─────────────────────────────
            try:
                risorse_post = _leggi_risorse_mappa(porta, risorse_lista, logger, nome)
                if any(risorse_post.get(r, -1) >= 0 for r in risorse_lista):
                    _status.istanza_rifornimento(
                        nome,
                        risorse_pre.get("pomodoro", -1),  risorse_pre.get("legno", -1),
                        risorse_pre.get("acciaio",  -1),  risorse_pre.get("petrolio", -1),
                        risorse_post.get("pomodoro", -1), risorse_post.get("legno", -1),
                        risorse_post.get("acciaio",  -1), risorse_post.get("petrolio", -1),
                    )
                    log("Delta rifornimento registrato in status")
                else:
                    log("OCR POST-invio fallito — delta non registrato (non bloccante)")
            except Exception as _e:
                log(f"Errore registrazione delta (non bloccante): {_e}")

    finally:
        # Torna sempre in HOME a fine loop (successo o errore)
        stato.vai_in_home(porta, nome, logger)

    log(f"Rifornimento mappa completato: {spedizioni} spedizioni totali")
    return spedizioni
