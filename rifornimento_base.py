# ==============================================================================
#  DOOMSDAY BOT V5 - rifornimento_base.py
#  Modulo base condiviso tra rifornimento.py e rifornimento_mappa.py
#
#  Responsabilità:
#    - Gestione quota giornaliera (stato, reset, controllo)
#    - Lettura slot liberi raccoglitori
#    - OCR maschera "Risorse di Approvvigionamento" (provviste, tassa, ETA, VAI)
#    - Compilazione campi e invio VAI (_compila_e_invia)
#    - Costanti condivise (QTA_DEFAULT, coordinate maschera)
#
#  NON contiene:
#    - Navigazione lista Membri/avatar/toggle  → rifornimento.py
#    - Navigazione coordinate mappa            → rifornimento_mappa.py
# ==============================================================================

import time
import json
import re
import os
from datetime import datetime, timezone, timedelta

import cv2
import numpy as np
from PIL import Image

import adb
import stato
import config

# ------------------------------------------------------------------------------
# Costanti coordinate maschera invio (960x540)
# ------------------------------------------------------------------------------

# Coordinate campi quantità risorsa nella maschera
COORD_CAMPO = {
    "pomodoro": (757, 224),
    "legno":    (757, 274),
    "acciaio":  (757, 325),
    "petrolio": (757, 375),
}

COORD_VAI = (480, 448)   # pulsante VAI

# Zone OCR maschera
OCR_NOME_DEST    = (265,  90, 620, 138)   # nome destinatario
OCR_PROVVISTE    = (155, 230, 360, 262)   # provviste rimanenti oggi
OCR_RESIDUO_OGGI = OCR_PROVVISTE          # alias per compatibilità
OCR_TASSA        = (155, 272, 310, 298)   # "Tasse: 23.0%"
OCR_CAMION       = (155, 340, 395, 385)   # "0/1,200,000"
OCR_TEMPO        = (350, 398, 620, 438)   # ETA viaggio "00:00:54"
VAI_ZONA         = (270, 420, 690, 480)   # zona pulsante VAI

# Soglia pixel gialli per VAI abilitato
VAI_SOGLIA_GIALLI = 100

# Tassa default (24%)
TASSA_DEFAULT = 0.24

# Quantità default per singolo invio (unità assolute)
QTA_DEFAULT = {
    "pomodoro": 1_000_000,
    "legno":    1_000_000,
    "acciaio":  0,
    "petrolio": 0,
}


# ==============================================================================
# Gestione stato giornaliero quota
# ==============================================================================

def _safe_stato_id(val: str) -> str:
    """Normalizza porta/serial ADB per uso in filename."""
    s = re.sub(r'[^A-Za-z0-9_-]+', '_', str(val)).strip('_')
    return s or 'noid'


def _path_stato(nome: str, porta: str = "") -> str:
    """Path file stato giornaliero (legacy — usato solo per migrazione)."""
    suff = _safe_stato_id(porta) if porta else 'noporta'
    return os.path.join(config.BOT_DIR, f"rifornimento_stato_{nome}_{suff}.json")


def _reset_slot_corrente() -> datetime:
    """
    Ritorna il datetime del reset-slot in vigore (01:00 UTC di oggi o ieri).
    """
    now = datetime.now(timezone.utc)
    reset_oggi = now.replace(hour=1, minute=0, second=0, microsecond=0)
    return reset_oggi if now >= reset_oggi else reset_oggi - timedelta(days=1)


def _carica_stato(nome: str, porta: str = "") -> dict:
    """
    Legge la sezione rifornimento dallo stato unificato per istanza.
    Migra automaticamente dal vecchio file rifornimento_stato_*.json se presente.
    """
    import scheduler as _sched
    default = {"quota_esaurita": False, "ultimo_reset_utc": ""}

    sezione = _sched.carica_sezione(nome, porta, "rifornimento")
    if sezione:
        return {**default, **sezione}

    # Migrazione dal vecchio file separato
    path_vecchio = _path_stato(nome, porta)
    try:
        with open(path_vecchio, 'r', encoding='utf-8') as f:
            dati = json.load(f)
        dati_migrati = {**default, **dati}
        _sched.salva_sezione(nome, porta, "rifornimento", dati_migrati)
        print(f"[RIF] Migrato {os.path.basename(path_vecchio)} → stato unificato")
        try:
            os.remove(path_vecchio)
        except Exception:
            pass
        return dati_migrati
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[RIF] WARN migrazione stato: {e}")

    return default


def _salva_stato(nome: str, porta: str, quota_esaurita: bool) -> None:
    """Salva la sezione rifornimento nello stato unificato per istanza."""
    import scheduler as _sched
    _sched.salva_sezione(nome, porta, "rifornimento", {
        "quota_esaurita": quota_esaurita,
        "ultimo_reset_utc": _reset_slot_corrente().isoformat(),
    })


def _controlla_reset(nome: str, porta: str = "", logger=None) -> bool:
    """
    Controlla se il rifornimento può essere eseguito oggi.

    Ritorna:
        False → procedi (quota disponibile o appena resettata)
        True  → salta (quota già esaurita per oggi)
    """
    def log(msg):
        if logger:
            logger(nome, f"[RIF] {msg}")

    stato_rif      = _carica_stato(nome, porta)
    reset_corrente = _reset_slot_corrente()

    if not stato_rif.get("quota_esaurita"):
        return False

    raw_ts = stato_rif.get("ultimo_reset_utc", "")
    if not raw_ts:
        log("quota_esaurita=True ma ultimo_reset_utc mancante — resetto per sicurezza")
        _salva_stato(nome, porta, False)
        return False

    try:
        ultimo = datetime.fromisoformat(raw_ts)
    except Exception:
        log(f"ultimo_reset_utc non parsabile ('{raw_ts}') — resetto per sicurezza")
        _salva_stato(nome, porta, False)
        return False

    if reset_corrente > ultimo:
        log(f"Nuovo reset giornaliero rilevato "
            f"({reset_corrente.strftime('%Y-%m-%d %H:%M UTC')}) — quota ripristinata")
        _salva_stato(nome, porta, False)
        return False

    prossimo = reset_corrente + timedelta(days=1)
    manca_min = int((prossimo - datetime.now(timezone.utc)).total_seconds() / 60)
    log(f"Quota giornaliera esaurita — prossimo reset tra {manca_min} min "
        f"({prossimo.strftime('%H:%M UTC')})")
    return True


# ==============================================================================
# Lettura slot liberi raccoglitori
# ==============================================================================

def _slot_liberi(porta: str, n_volo: int = 0) -> int:
    """
    Legge contatore raccoglitori. Ritorna slot liberi.
    Lookup max_squadre da config.ISTANZE_MUMU per porta corrispondente.

    n_volo: numero di spedizioni rifornimento attualmente in volo.
    Il gioco le conta come squadre attive, quindi vanno sottratte
    da attive per ottenere i soli raccoglitori e calcolare correttamente
    gli slot liberi per nuove spedizioni.
    """
    n_squadre = -1
    try:
        porta_int = int(porta)
        for ist in getattr(config, "ISTANZE_MUMU", []):
            if int(ist.get("porta", -1)) == porta_int:
                ms = ist.get("max_squadre", -1)
                if ms and ms > 0:
                    n_squadre = int(ms)
                break
    except Exception:
        pass

    attive, totale, libere = stato.conta_squadre(porta, n_letture=3, n_squadre=n_squadre)
    if attive == -1 or totale == -1:
        return 4  # fallback ottimistico

    # Sottrai le spedizioni in volo: il gioco le conta come squadre attive
    # ma non occupano slot raccoglitori — vanno escluse dal calcolo.
    if n_volo > 0:
        attive = max(0, attive - n_volo)
        libere = max(0, totale - attive)

    return libere


# ==============================================================================
# OCR maschera "Risorse di Approvvigionamento"
# ==============================================================================

def _ocr_otsu(img_path: str, box: tuple, whitelist: str = "", psm: int = 7) -> str:
    """OCR con OTSU thresholding — per testi bianchi/chiari su sfondo scuro."""
    try:
        import pytesseract
        img = Image.open(img_path)
        crop = img.crop(box)
        c4x = crop.resize((crop.width * 4, crop.height * 4), Image.LANCZOS)
        gray = np.array(c4x.convert("L"))
        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        cfg = f"--psm {psm}"
        if whitelist:
            cfg += f" -c tessedit_char_whitelist={whitelist}"
        return pytesseract.image_to_string(Image.fromarray(bw), config=cfg).strip()
    except Exception:
        return ""


def _ocr_crema(img_path: str, box: tuple, whitelist: str = "", psm: int = 7) -> str:
    """OCR con filtro colore crema/avorio — per testi colorati su sfondo scuro."""
    try:
        import pytesseract
        img = Image.open(img_path)
        crop = img.crop(box)
        arr = np.array(crop)
        mask = (arr[:, :, 0] >= 220) & (arr[:, :, 1] >= 200) & (arr[:, :, 2] >= 180)
        result = np.ones_like(arr[:, :, 0]) * 255
        result[mask] = 0
        bw = Image.fromarray(result)
        c4x = bw.resize((bw.width * 4, bw.height * 4), Image.LANCZOS)
        cfg = f"--psm {psm}"
        if whitelist:
            cfg += f" -c tessedit_char_whitelist={whitelist}"
        return pytesseract.image_to_string(c4x, config=cfg).strip()
    except Exception:
        return ""


def _vai_abilitato(screen_path: str) -> bool:
    """True se il pulsante VAI è giallo (abilitato), False se grigio."""
    try:
        img = Image.open(screen_path)
        arr = np.array(img)
        vai = arr[VAI_ZONA[1]:VAI_ZONA[3], VAI_ZONA[0]:VAI_ZONA[2]]
        yellow = (vai[:, :, 0] > 160) & (vai[:, :, 1] > 120) & (vai[:, :, 2] < 90)
        return int(yellow.sum()) > VAI_SOGLIA_GIALLI
    except Exception:
        return False


def _leggi_provviste(screen_path: str) -> int:
    """
    Legge 'Provviste rimanenti di oggi' dalla maschera.
    Ritorna intero, -1 se OCR fallisce, 0 se campo è zero.
    """
    testo = _ocr_otsu(screen_path, OCR_PROVVISTE, whitelist="0123456789,. ")
    testo = testo.replace(",", "").replace(".", "").replace(" ", "").strip()
    try:
        return int(testo)
    except ValueError:
        return -1


def _leggi_tassa(screen_path: str) -> float:
    """Legge percentuale tassa dalla maschera (es. 'Tasse: 23.0%' → 0.23)."""
    testo = _ocr_otsu(screen_path, OCR_TASSA, psm=7)
    m = re.search(r'([0-9]+\.?[0-9]*)\s*%', testo)
    if m:
        try:
            return float(m.group(1)) / 100.0
        except ValueError:
            pass
    return TASSA_DEFAULT


def _leggi_eta(screen_path: str) -> int:
    """Legge ETA viaggio dalla maschera (es. '00:00:54'). Ritorna secondi totali."""
    testo = _ocr_otsu(screen_path, OCR_TEMPO, whitelist="0123456789:")
    parti = testo.replace(".", ":").split(":")
    try:
        if len(parti) == 3:
            return int(parti[0]) * 3600 + int(parti[1]) * 60 + int(parti[2])
        if len(parti) == 2:
            return int(parti[0]) * 60 + int(parti[1])
    except (ValueError, IndexError):
        pass
    return 0


def _leggi_capacita_camion(screen_path: str) -> int:
    """Legge capacità massima camion dalla maschera (es. '0/1,200,000' → 1200000)."""
    testo = _ocr_crema(screen_path, OCR_CAMION, whitelist="0123456789,./")
    if "/" in testo:
        testo = testo.split("/")[-1]
    testo = testo.replace(",", "").replace(".", "").replace(" ", "").strip()
    try:
        return int(testo)
    except ValueError:
        return 0


def _verifica_nome_destinatario(screen_path: str, nome_atteso: str):
    """
    Verifica che il nome nella maschera corrisponda al destinatario atteso.
    Ritorna (ok: bool, testo_ocr_pulito: str).
    """
    testo = _ocr_otsu(screen_path, OCR_NOME_DEST, psm=7)
    testo = testo.replace('|', '').replace('_', '').replace('=', '').strip()
    ok = nome_atteso.lower() in testo.lower()
    return ok, testo


# ==============================================================================
# Compilazione campi e invio VAI
# ==============================================================================

def _compila_e_invia(porta: str, quantita: dict, nome_dest: str,
                     logger=None, nome: str = ""):
    """
    Legge la maschera aperta, verifica destinatario, compila le risorse e preme VAI.

    Ritorna:
        (ok, eta_sec, quota_esaurita, qta_inviata, mismatch_nome)

        ok=True            → spedizione inviata, eta_sec valido
        ok=False           → errore generico (VAI disabilitato, OCR fallito, ecc.)
        quota_esaurita     → provviste = 0, non rientrare nel ciclo oggi
        mismatch_nome      → destinatario OCR non corrisponde all'atteso
        qta_inviata        → quantità compilata (0 se non inviata)

    Nota: quando ok=False e quota_esaurita=False il chiamante deve
    decidere se marcare la quota come esaurita. Se il VAI resta grigio
    pur con provviste > 0, le provviste residue sono troppo basse per
    la quantità richiesta: il chiamante dovrebbe salvare lo stato esaurito
    con _salva_stato() per evitare tentativi inutili nei cicli successivi.
    """
    def log(msg):
        if logger: logger(nome, f"[RIF] {msg}")

    mismatch_nome = False

    screen = adb.screenshot(porta)
    if not screen:
        return False, 0, False, 0, mismatch_nome

    # Verifica nome destinatario
    if nome_dest:
        ok_nome, testo_ocr = _verifica_nome_destinatario(screen, nome_dest)
        if not ok_nome:
            mismatch_nome = True
            log(f"DEST MISMATCH: destinatario OCR='{testo_ocr}' atteso='{nome_dest}' — ABORT")
            adb.keyevent(porta, "KEYCODE_BACK")
            time.sleep(0.8)
            try:
                stato.vai_in_home(porta, nome, logger)
            except Exception:
                pass
            return False, 0, False, 0, mismatch_nome

    tassa_reale = _leggi_tassa(screen)
    log(f"Tassa: {tassa_reale*100:.1f}%")

    provviste = _leggi_provviste(screen)
    if provviste >= 0:
        log(f"Provviste rimanenti: {provviste:,}")
    else:
        log("Provviste rimanenti: OCR fallito - procedo")

    if provviste == 0:
        log("Provviste giornaliere esaurite - stop ciclo")
        adb.keyevent(porta, "KEYCODE_BACK")
        time.sleep(0.8)
        return False, 0, True, 0, mismatch_nome

    eta_sec = _leggi_eta(screen)
    cap_max = _leggi_capacita_camion(screen)
    log(f"ETA viaggio: {eta_sec}s")

    # Seleziona una sola risorsa per viaggio
    risorsa_scelta = None
    qta_scelta     = 0
    for risorsa, qta in quantita.items():
        if qta <= 0:
            continue
        if not COORD_CAMPO.get(risorsa):
            continue
        risorsa_scelta = risorsa
        qta_scelta     = qta
        break

    if not risorsa_scelta:
        log("Nessuna risorsa da compilare")
        return False, 0, False, 0, mismatch_nome

    log(f"Compila {risorsa_scelta}: {qta_scelta:,}")
    coord = COORD_CAMPO[risorsa_scelta]
    adb.tap(porta, coord, delay_ms=300)
    adb.tap(porta, coord, delay_ms=300)
    adb.tap(porta, coord, delay_ms=600)
    for _ in range(12):
        adb.keyevent(porta, "KEYCODE_DEL")
    time.sleep(0.3)
    adb.input_text(porta, str(qta_scelta))
    time.sleep(0.5)
    adb.tap(porta, config.TAP_OK_TASTIERA, delay_ms=500)

    # Verifica VAI abilitato
    screen2 = adb.screenshot(porta)
    if screen2 and not _vai_abilitato(screen2):
        log("VAI non abilitato dopo compilazione — controllo provviste")
        provviste2 = _leggi_provviste(screen2)
        if provviste2 == 0:
            log("Provviste esaurite dopo compilazione")
            adb.keyevent(porta, "KEYCODE_BACK")
            time.sleep(0.8)
            return False, 0, True, 0, mismatch_nome
        # Provviste > 0 ma VAI grigio: quantità richiesta supera il residuo disponibile.
        # Ritorna ok=False, quota_esaurita=False — il chiamante decide se salvare stato.
        log("VAI disabilitato per motivo sconosciuto - annullo")
        adb.keyevent(porta, "KEYCODE_BACK")
        return False, 0, False, 0, mismatch_nome

    log("Tap VAI")
    adb.tap(porta, COORD_VAI, delay_ms=2500)
    return True, eta_sec, False, qta_scelta, mismatch_nome
