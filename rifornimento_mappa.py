# ==============================================================================
#  DOOMSDAY BOT V5 - rifornimento_mappa.py
#  Invio risorse al rifugio alleato via coordinate mappa (alternativo a rifornimento.py)
#
#  Differenza rispetto a rifornimento.py:
#    La navigazione avviene tramite coordinate mappa invece della lista Membri.
#
#  Dipendenze: rifornimento_base.py (stato quota, slot liberi, OCR maschera, _compila_e_invia).
#    Nessuna dipendenza da rifornimento.py.
#    Il loop multi-spedizione resta in mappa tra una spedizione e l'altra,
#    eliminando i cicli home↔mappa ripetuti (più veloce e meno transizioni UI).
#
#  Flusso corretto (v5.25):
#    HOME → Mappa (una sola volta, dopo la prima lettura slot)
#    Loop spedizioni:
#      1. Leggi slot liberi (lettura reale UI — include spedizioni in volo)
#      2. Se slot == 0: aspetta rientro PRIMA spedizione in coda (quella che
#         torna prima) → rileggi slot → se ancora 0 → stop
#      3. Verifica soglie risorse → seleziona risorsa
#      4. Centra mappa → tap castello → RESOURCE SUPPLY → VAI
#      5. Registra (timestamp_invio, ETA_A/R) in coda_volo
#      6. Ripeti fino a saturazione spedizioni o soglie
#    Fine loop → salva ETA ultima spedizione ancora in volo in status
#    → raccolta_istanza aspetta quella ETA prima di mandare raccoglitori
#
#  Logica coda_volo:
#    coda_volo è ordinata cronologicamente:
#      [0]  = prima spedizione partita = prima che rientra → libera 1 slot
#      [-1] = ultima spedizione partita = ultima che rientra
#    Quando slot==0: aspettiamo coda_volo[0] (minimo per avere 1 slot libero)
#    A fine loop: passiamo coda_volo[-1] alla raccolta (garantisce tutti rientrati)
#
#  Flag abilitazione: RIFORNIMENTO_MAPPA_ABILITATO in config.py / runtime.json
#  Coordinate rifugio: RIFUGIO_X, RIFUGIO_Y in config.py / runtime.json
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

# Importa la logica condivisa da rifornimento_base (modulo autonomo)
from rifornimento_base import (
    _controlla_reset,
    _salva_stato,
    _slot_liberi,
    _compila_e_invia,
    QTA_DEFAULT,
)

# ── Coordinate rifugio destinatario (da config.py / runtime.json) ──────────────
RIFUGIO_X = getattr(config, "RIFUGIO_X", 684)
RIFUGIO_Y = getattr(config, "RIFUGIO_Y", 532)

# ── Coordinate UI 960x540 — navigazione mappa ──────────────────────────────────
TAP_LENTE_MAPPA     = (334,  13)   # lente coordinate sulla mappa
TAP_CAMPO_X         = (484, 135)   # campo X nella lente
TAP_CAMPO_Y         = (601, 135)   # campo Y nella lente
TAP_CONFERMA_LENTE  = (670, 135)   # conferma → centra mappa
TAP_CASTELLO_CENTER = (490, 230)   # castello rifugio dopo centratura mappa

# ── Template RESOURCE SUPPLY ───────────────────────────────────────────────────
TEMPLATE_RESOURCE_SUPPLY = os.path.join(
    config.BOT_DIR, "templates", "btn_resource_supply_map.png"
)
TEMPLATE_SOGLIA = 0.75

# ── Flag abilitazione ──────────────────────────────────────────────────────────
RIFORNIMENTO_MAPPA_ABILITATO = False

# ── Margine attesa slot (secondi extra dopo ETA A/R stimata) ───────────────────
# Aggiunto all'ETA per compensare latenze UI e jitter timing
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

    rx = x if x is not None else getattr(config, "RIFUGIO_X", RIFUGIO_X)
    ry = y if y is not None else getattr(config, "RIFUGIO_Y", RIFUGIO_Y)

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
# Helpers coda_volo
# ------------------------------------------------------------------------------

def _aggiorna_coda(coda_volo: deque) -> None:
    """
    Rimuove dalla testa della coda le spedizioni certamente già rientrate
    (elapsed >= eta_ar). Non usa MARGINE_ATTESA qui — serve solo a pulire
    le voci scadute, non a decidere tempi di attesa.
    """
    now = time.time()
    while coda_volo:
        ts_invio, eta_ar = coda_volo[0]
        if (now - ts_invio) >= eta_ar:
            coda_volo.popleft()
        else:
            break


def _attesa_prima_spedizione(coda_volo: deque) -> float:
    """
    Calcola i secondi da attendere per il rientro della PRIMA spedizione
    in coda (coda_volo[0] = partita prima = ritorna prima → libera 1 slot).
    Include MARGINE_ATTESA per compensare latenze UI.
    Ritorna 0.0 se la coda è vuota o la spedizione è già rientrata.
    """
    if not coda_volo:
        return 0.0
    ts_invio, eta_ar = coda_volo[0]
    residuo = max(0.0, eta_ar - (time.time() - ts_invio)) + MARGINE_ATTESA
    return residuo


def _attesa_ultima_spedizione(coda_volo: deque) -> float:
    """
    Calcola i secondi da attendere per il rientro dell'ULTIMA spedizione
    in coda (coda_volo[-1] = partita per ultima = ritorna per ultima).
    Include MARGINE_ATTESA.
    Usato a fine loop per comunicare alla raccolta quanto aspettare.
    Ritorna 0.0 se la coda è vuota o già rientrata.
    """
    if not coda_volo:
        return 0.0
    ts_invio, eta_ar = coda_volo[-1]
    residuo = max(0.0, eta_ar - (time.time() - ts_invio)) + MARGINE_ATTESA
    return residuo


# ------------------------------------------------------------------------------
# Funzione principale — loop ottimizzato in mappa
# ------------------------------------------------------------------------------

def esegui_rifornimento_mappa(porta: str, nome: str,
                               pomodoro_m: float = -1, legno_m: float = -1,
                               acciaio_m: float = -1, petrolio_m: float = -1,
                               logger=None, ciclo: int = 0) -> int:
    """
    Esegue rifornimento risorse al rifugio alleato tramite navigazione mappa.

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

    # Flag abilitazione per-risorsa
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
    # coda_volo: deque di (timestamp_invio: float, eta_ar: float)
    # Ordine cronologico: [0]=prima partita=prima che rientra, [-1]=ultima
    coda_volo: deque = deque()
    in_mappa = False

    try:
        while True:
            # ── Stop se raggiunto il limite ─────────────────────────────────────
            if max_sped is not None and spedizioni >= max_sped:
                log(f"Limite massimo spedizioni raggiunto ({spedizioni}/{max_sped})")
                break

            # ── 1. Leggi slot liberi (lettura reale UI) ─────────────────────────
            # Il contatore include tutte le squadre fuori dal rifugio:
            # raccoglitori attivi + spedizioni di rifornimento in volo.
            # È corretto: vogliamo sapere quanti slot fisici sono liberi ora.
            _aggiorna_coda(coda_volo)
            slot = _slot_liberi(porta)
            log(f"Slot liberi: {slot}")

            if slot == 0:
                # ── Aspetta il rientro della PRIMA spedizione ───────────────────
                # La prima in coda è quella partita prima → torna prima → libera
                # il primo slot disponibile. Non serve aspettare le successive.
                attesa = _attesa_prima_spedizione(coda_volo)
                if attesa > 0:
                    log(f"Slot occupati — attendo rientro prima spedizione: {attesa:.0f}s")
                    time.sleep(attesa)
                    _aggiorna_coda(coda_volo)
                else:
                    # Coda vuota o scaduta ma slot ancora 0:
                    # spedizioni già rientrate ma UI non ancora aggiornata
                    log("Slot occupati, coda vuota o scaduta — attendo 30s")
                    time.sleep(30)

                slot = _slot_liberi(porta)
                log(f"Slot dopo attesa: {slot}")
                if slot == 0:
                    log("Nessun slot libero dopo attesa - stop")
                    break

            # ── 2. Vai in mappa (solo alla prima spedizione) ────────────────────
            # Le spedizioni successive rimangono in mappa, eliminando transizioni
            if not in_mappa:
                if not stato.vai_in_mappa(porta, nome, logger):
                    log("Impossibile andare in mappa — stop")
                    break
                in_mappa = True
                time.sleep(1.5)

            # ── 3. Leggi deposito risorse ───────────────────────────────────────
            risorse_reali = _leggi_risorse_mappa(porta, risorse_lista, logger, nome)
            if all(risorse_reali.get(r, -1) < 0 for r in risorse_lista):
                log("OCR deposito fallito dopo retry — stop")
                break

            log("Deposito: " + " | ".join(
                f"{r}={max(0.0, risorse_reali.get(r,-1))/1e6:.1f}M"
                for r in risorse_lista if risorse_reali.get(r,-1) >= 0
            ))

            # ── 4. Seleziona risorsa ────────────────────────────────────────────
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

            # ── 5. Centra mappa, apri maschera, invia ──────────────────────────
            retry_nome_done = False
            stop_esterno    = False
            eta_sec         = 0
            qta_inviata     = 0
            ts_invio        = time.time()

            while True:
                if not _centra_e_apri_maschera(porta, logger, nome):
                    log("Navigazione mappa fallita — fallback HOME e stop")
                    for _ in range(5):
                        adb.keyevent(porta, "KEYCODE_BACK")
                        time.sleep(0.5)
                    stato.vai_in_home(porta, nome, logger)
                    in_mappa     = False
                    stop_esterno = True
                    break

                ts_invio = time.time()
                ok, eta_sec, quota_esaurita, qta_inviata, mismatch_nome = _compila_e_invia(
                    porta, {risorsa_scelta: risorse_config[risorsa_scelta]},
                    nome_rifugio, logger, nome
                )

                if quota_esaurita:
                    log("Provviste giornaliere esaurite - stop")
                    adb.keyevent(porta, "KEYCODE_BACK")
                    time.sleep(1.0)
                    _salva_stato(nome, str(porta), True)
                    log("Quota giornaliera salvata nello stato istanza")
                    stop_esterno = True
                    break

                if mismatch_nome and not retry_nome_done:
                    log("DEST MISMATCH: retry 1")
                    retry_nome_done = True
                    time.sleep(1.0)
                    continue

                if not ok:
                    log("Invio fallito — tentativo BACK e stop spedizione")
                    adb.keyevent(porta, "KEYCODE_BACK")
                    time.sleep(0.5)
                    # VAI disabilitato con provviste residue insufficienti:
                    # segna quota come esaurita per evitare tentativi inutili
                    # nei cicli successivi (reset automatico alle 01:00 UTC).
                    _salva_stato(nome, str(porta), True)
                    log("VAI disabilitato → quota segnata come esaurita nello stato istanza")
                    stop_esterno = True
                    break

                break  # OK

            if stop_esterno:
                break

            if qta_inviata <= 0:
                continue

            # ── 6. Post-spedizione: registra in coda ───────────────────────────
            spedizioni += 1
            eta_ar = float(eta_sec * 2)   # A/R = andata × 2
            coda_volo.append((ts_invio, eta_ar))
            log(f"Spedizione {spedizioni}: {risorsa_scelta} {qta_inviata:,} | "
                f"ETA A/R {eta_ar:.0f}s | In volo: {len(coda_volo)}")
            _log.registra_evento(ciclo, nome, "rifornimento_mappa_ok", spedizioni, 1,
                                 f"risorsa={risorsa_scelta}")

            # Breve attesa stabilizzazione UI dopo VAI
            time.sleep(2.0)

            # ── 7. Snapshot POST-invio dalla mappa (dashboard) ─────────────────
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
        stato.vai_in_home(porta, nome, logger)

    log(f"Rifornimento mappa completato: {spedizioni} spedizioni totali")

    # ── Comunica ETA ultima spedizione alla raccolta ────────────────────────────
    # raccolta_istanza attenderà questo tempo prima di leggere gli slot per
    # i raccoglitori, così è certo che nessuna spedizione di rifornimento
    # è ancora in volo e venga contata come slot occupato.
    # Usa coda_volo[-1] = ultima partita = ultima che rientra.
    _aggiorna_coda(coda_volo)
    eta_residua = _attesa_ultima_spedizione(coda_volo)
    try:
        if eta_residua > 0:
            log(f"ETA residua ultima spedizione: {eta_residua:.0f}s — comunicata a raccolta")
        _status.istanza_set(nome, "rifmap_eta_residua", max(0.0, eta_residua))
    except Exception:
        pass

    return spedizioni
