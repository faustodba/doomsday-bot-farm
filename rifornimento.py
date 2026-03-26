# ==============================================================================
#  DOOMSDAY BOT V5 - rifornimento.py  V5.3
#  Invio risorse al rifugio alleato (Risorse di Approvvigionamento)
#
#  Flusso:
#    1. Legge slot liberi raccoglitori (OCR contatore in home)
#    2. Controlla risorse mittente > soglia (10M default, considera tassa 24%)
#    3. Naviga: Alleanza → Membri → scorri R1/R2/R3/R4 → trova avatar
#    4. Tap membro → trova pulsante "Risorse di approvvigionamento" via template matching
#    5. Nella maschera: leggi residuo giornaliero e tempo percorrenza
#    6. Compila campi quantità → Tap VAI → torna in home
#    7. Rileggi slot liberi → ripeti finché slot==0 o risorse esaurite
#
#  Chiamato da raccolta.py PRIMA della raccolta risorse, quando si è in home.
# ==============================================================================

import time
from collections import deque
import json
from datetime import datetime, timezone, timedelta
import re
import os
import shutil
import cv2
import numpy as np
from PIL import Image
import adb
import ocr
import stato
import debug
import config
import log as _log
import status as _status

# ------------------------------------------------------------------------------
# Coordinate navigazione (risoluzione 960x540)
# ------------------------------------------------------------------------------
COORD_ALLEANZA_BTN  = (760, 505)   # pulsante Alleanza in home

COORD_MEMBRI        = (46, 188)    # tab Membri nel menu Alleanza

# Swipe lista membri (risoluzione 960x540)
# AVANZARE nella lista  = swipe verso l'ALTO  (dito va su: start alto, end basso)
# TORNARE in cima       = swipe verso il BASSO (dito va giù: start basso, end alto)
COORD_SWIPE_SU_START   = (480, 430)   # avanza lista: dito parte da basso
COORD_SWIPE_SU_END     = (480, 240)   # avanza lista: dito arriva in alto
COORD_SWIPE_GIU_START  = (480, 240)   # scroll-to-top: dito parte da alto
COORD_SWIPE_GIU_END    = (480, 460)   # scroll-to-top: dito arriva in basso

# Zona lista membri (risoluzione 960x540, escluso sidebar sx e header)
LISTA_ZONA = (130, 165, 940, 540)

# Path template frecce e badge R (nella cartella templates/)
# Estratti da screenshot reali e calibrati — NON modificare
TMPL_ARROW_DOWN  = "templates/arrow_down.png"    # freccia giù = toggle chiuso
TMPL_ARROW_UP    = "templates/arrow_up.png"      # freccia su  = toggle aperto
TMPL_BADGE = {
    "R4": "templates/badge_R4.png",
    "R3": "templates/badge_R3.png",
    "R2": "templates/badge_R2.png",
    "R1": "templates/badge_R1.png",
}

# Soglie template matching
BADGE_SOGLIA         = 0.85   # soglia match badge R per trovare barre
FRECCIA_SOGLIA       = 0.85   # soglia match freccia su/giù per stato toggle
AVATAR_SOGLIA        = 0.75   # soglia match avatar destinatario
BTN_RISORSE_SOGLIA   = 0.75   # soglia match pulsante risorse

# Zona X dove cercare il badge (colonna sinistra barra, escluso sidebar)
BADGE_CERCA_X1 = 130
BADGE_CERCA_X2 = 220

# Zona X dove cercare la freccia toggle (angolo destro barra)
FRECCIA_CERCA_X1 = 860
FRECCIA_CERCA_X2 = 930

# Altezza barra R in pixel (per definire fascia di ricerca freccia)
BARRA_R_ALTEZZA = 43

# Max swipe per scroll-to-top e per ricerca avatar
MAX_SWIPE_TOP     = 6
MAX_SWIPE_RICERCA = 25

# Max swipe per fase apertura toggle
MAX_SWIPE_TOGGLE  = 12

# Mantenuto per compatibilità con _naviga_a_maschera legacy
COORD_TAB_R = {}
MAX_SWIPE   = 8

# Maschera invio risorse — 4 campi quantità (coordinate fisse 960x540)
COORD_CAMPO = {
    "pomodoro": (757, 224),   # calibrato da screenshot reale
    "legno":    (757, 274),
    "acciaio":  (757, 325),
    "petrolio": (757, 375),
}

COORD_VAI = (480, 448)   # pulsante VAI

# Zone OCR nella maschera invio risorse
OCR_RESIDUO_OGGI = (140, 225, 360, 255)   # "Provviste rimanenti di oggi: 20,000,000"
OCR_TEMPO        = (380, 410, 580, 440)   # "00:00:54"

# Area di ricerca avatar nella lista membri (zona lista, escluso header e sidebar)
AVATAR_ZONA      = (130, 155, 540, 490)

# Tassa invio default (24%) — preleva qta * (1 + tassa) dal mittente
TASSA_DEFAULT = 0.24

# Quantità default per singolo invio (unità assolute)
QTA_DEFAULT = {
    "pomodoro": 1_000_000,
    "legno":    1_000_000,
    "acciaio":  0,
    "petrolio": 0,
}

# Soglia minima risorse mittente per inviare (milioni)
SOGLIA_MIN_M = 10.0

# Flag abilitazione modulo (False = disabilitato, solo test step espliciti attivi)
RIFORNIMENTO_ABILITATO = False



# ------------------------------------------------------------------------------
# Gestione stato giornaliero rifornimento (quota_esaurita + reset 01:00 UTC)
#
# STRUTTURA FILE JSON:
#   {
#     "quota_esaurita": true/false,
#     "ultimo_reset_utc": "2026-03-13T01:00:00+00:00"   ← timestamp reset in vigore
#   }
#
# LOGICA RESET:
#   Il gioco azzera le provviste ogni giorno alle 01:00 UTC.
#   `ultimo_reset_utc` memorizza il reset-slot in vigore al momento del salvataggio
#   (es. 2026-03-13T01:00:00 se salviamo tra 01:00 del 13 e 01:00 del 14).
#   Al prossimo controllo, se il reset-slot corrente è più recente → nuovo giorno → reset.
#
# CASI GESTITI:
#   1. File non esiste        → crea con quota_esaurita=False (prima esecuzione)
#   2. quota_esaurita=False   → procedi normalmente
#   3. quota_esaurita=True  +  reset_corrente > ultimo_reset_utc → nuovo giorno → reset a False
#   4. quota_esaurita=True  +  stesso reset-slot                 → skip (quota ancora esaurita)
#   5. Stato corrotto/legacy  → reset per sicurezza (non bloccare indefinitamente)
#
# ISOLAMENTO: file separato per istanza via nome+porta ADB (es. rifornimento_stato_FAU_01_5615.json)
# ------------------------------------------------------------------------------

def _safe_stato_id(val: str) -> str:
    """Normalizza porta/serial ADB per uso in filename (solo [A-Za-z0-9_-])."""
    s = re.sub(r'[^A-Za-z0-9_-]+', '_', str(val)).strip('_')
    return s or 'noid'


def _path_stato(nome: str, porta: str = "") -> str:
    """Path file stato giornaliero isolato per istanza/device."""
    suff = _safe_stato_id(porta) if porta else 'noporta'
    return os.path.join(config.BOT_DIR, f"rifornimento_stato_{nome}_{suff}.json")


def _reset_slot_corrente() -> datetime:
    """
    Ritorna il datetime del reset-slot attualmente in vigore (01:00 UTC di oggi o ieri).
    Esempio: se ora è 00:30 UTC del 14, il reset in vigore è 01:00 UTC del 13.
             se ora è 02:00 UTC del 14, il reset in vigore è 01:00 UTC del 14.
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

    # Prova a leggere dal file unificato
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
    """
    Salva la sezione rifornimento nello stato unificato per istanza.
    """
    import scheduler as _sched
    _sched.salva_sezione(nome, porta, "rifornimento", {
        "quota_esaurita": quota_esaurita,
        "ultimo_reset_utc": _reset_slot_corrente().isoformat(),
    })


def _controlla_reset(nome: str, porta: str = "", logger=None) -> bool:
    """
    Controlla se il rifornimento può essere eseguito oggi.

    Ritorna:
        False → procedi con il rifornimento (quota disponibile o appena resettata)
        True  → salta il rifornimento (quota già esaurita per oggi)

    Effetti collaterali:
        - Crea il file stato se non esiste (quota_esaurita=False)
        - Resetta quota_esaurita=False se è passato il reset giornaliero
    """
    def log(msg):
        if logger:
            logger(nome, f"[RIF] {msg}")

    stato_rif      = _carica_stato(nome, porta)
    reset_corrente = _reset_slot_corrente()

    # --- Caso 2: quota non esaurita → procedi ---
    if not stato_rif.get("quota_esaurita"):
        return False

    # --- Da qui: quota_esaurita=True → verifico se è scaduta ---

    # Caso 5: stato corrotto — manca timestamp → non bloccare indefinitamente
    raw_ts = stato_rif.get("ultimo_reset_utc", "")
    if not raw_ts:
        log("quota_esaurita=True ma ultimo_reset_utc mancante — resetto per sicurezza")
        _salva_stato(nome, porta, False)
        return False

    # Caso 5b: timestamp non parsabile → reset per sicurezza
    try:
        ultimo = datetime.fromisoformat(raw_ts)
    except Exception:
        log(f"ultimo_reset_utc non parsabile ('{raw_ts}') — resetto per sicurezza")
        _salva_stato(nome, porta, False)
        return False

    # Caso 3: nuovo giorno (reset-slot corrente più recente dell'ultimo salvato)
    if reset_corrente > ultimo:
        log(f"Nuovo reset giornaliero rilevato "
            f"({reset_corrente.strftime('%Y-%m-%d %H:%M UTC')}) — quota ripristinata")
        _salva_stato(nome, porta, False)
        return False

    # Caso 4: stesso reset-slot → quota ancora esaurita oggi
    prossimo = reset_corrente + timedelta(days=1)
    manca_min = int((prossimo - datetime.now(timezone.utc)).total_seconds() / 60)
    log(f"Quota giornaliera esaurita — prossimo reset tra {manca_min} min "
        f"({prossimo.strftime('%H:%M UTC')})")
    return True


# ------------------------------------------------------------------------------
# Debug manuale (indipendente dal ciclo): salva screenshot in debug_manual/
# ------------------------------------------------------------------------------

def _salva_debug_manual(screen_path: str, nome: str, evento: str) -> str:
    """Copia lo screenshot in BOT_DIR/debug_manual con timestamp. Ritorna path destinazione o ''."""
    try:
        if not screen_path or not os.path.exists(screen_path):
            return ""
        d = os.path.join(config.BOT_DIR, 'debug_manual')
        os.makedirs(d, exist_ok=True)
        from datetime import datetime
        ts = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        dest = os.path.join(d, f"{nome}_{evento}_{ts}.png")
        shutil.copy2(screen_path, dest)
        return dest
    except Exception:
        return ""
# ------------------------------------------------------------------------------
# Navigazione avanzata lista Membri
# ------------------------------------------------------------------------------

def _scroll_to_top(porta: str, n: int = MAX_SWIPE_TOP):
    """
    Porta la lista all'inizio con n swipe verso il basso (dito scende).
    SCROLL-TO-TOP = swipe GIU = start alto, end basso.
    """
    for _ in range(n):
        adb.scroll(porta,
                   COORD_SWIPE_GIU_START[0], COORD_SWIPE_GIU_START[1],
                   COORD_SWIPE_GIU_END[1], durata_ms=350)
        time.sleep(0.4)
    time.sleep(0.8)


def _scroll_avanti(porta: str):
    """Avanza nella lista di un passo (swipe verso l'alto)."""
    adb.scroll(porta,
               COORD_SWIPE_SU_START[0], COORD_SWIPE_SU_START[1],
               COORD_SWIPE_SU_END[1], durata_ms=500)
    time.sleep(1.0)


def _trova_badge_in_screen(screen_path: str, rango: str) -> int:
    """
    Cerca il badge del rango specificato nella colonna sinistra della lista.
    Ritorna Y assoluta del centro del badge, oppure -1 se non trovato.
    Usa template matching sul badge colorato (R4/R3/R2/R1).
    """
    tmpl_path = TMPL_BADGE.get(rango, "")
    if not tmpl_path or not os.path.exists(tmpl_path):
        return -1

    screen_cv = cv2.imread(screen_path)
    tmpl_cv   = cv2.imread(tmpl_path)
    if screen_cv is None or tmpl_cv is None:
        return -1

    # Cerca solo nella colonna sinistra della lista (zona badge)
    h_screen = screen_cv.shape[0]
    zona = screen_cv[165:h_screen, BADGE_CERCA_X1:BADGE_CERCA_X2]
    th, tw = tmpl_cv.shape[:2]

    if zona.shape[0] < th or zona.shape[1] < tw:
        return -1

    res = cv2.matchTemplate(zona, tmpl_cv, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)

    if max_val < BADGE_SOGLIA:
        return -1

    # Y assoluta = offset zona + Y nel crop + metà altezza template
    y_abs = 165 + max_loc[1] + th // 2
    return y_abs


def _stato_toggle(screen_path: str, y_barra: int) -> str:
    """
    Determina se una barra R è aperta o chiusa tramite template matching
    della freccia (su/giù) nella zona destra della barra.

    y_barra: Y assoluta del centro della barra (960x540)
    Ritorna: 'aperto' | 'chiuso' | 'sconosciuto'
    """
    tmpl_down = TMPL_ARROW_DOWN
    tmpl_up   = TMPL_ARROW_UP

    if not os.path.exists(tmpl_down) or not os.path.exists(tmpl_up):
        return 'sconosciuto'

    screen_cv = cv2.imread(screen_path)
    if screen_cv is None:
        return 'sconosciuto'

    # Fascia verticale centrata su y_barra
    y1 = max(0,   y_barra - BARRA_R_ALTEZZA // 2)
    y2 = min(screen_cv.shape[0], y_barra + BARRA_R_ALTEZZA // 2)
    x1 = FRECCIA_CERCA_X1
    x2 = min(screen_cv.shape[1], FRECCIA_CERCA_X2)

    zona = screen_cv[y1:y2, x1:x2]

    score_down, score_up = 0.0, 0.0
    for tmpl_path, label in [(tmpl_down, 'down'), (tmpl_up, 'up')]:
        t = cv2.imread(tmpl_path)
        if t is None:
            continue
        th, tw = t.shape[:2]
        if zona.shape[0] < th or zona.shape[1] < tw:
            continue
        res = cv2.matchTemplate(zona, t, cv2.TM_CCOEFF_NORMED)
        _, val, _, _ = cv2.minMaxLoc(res)
        if label == 'down':
            score_down = val
        else:
            score_up = val

    if score_down < FRECCIA_SOGLIA and score_up < FRECCIA_SOGLIA:
        return 'sconosciuto'
    if score_up > score_down:
        return 'aperto'
    return 'chiuso'


def _apri_tutti_toggle(porta: str, logger=None, nome: str = "",
                       template_avatar: str = "") -> tuple:
    """
    Scorre la lista aprendo tutti i toggle R4/R3/R2/R1 chiusi.
    Durante ogni swipe cerca anche l'avatar — se trovato restituisce
    subito le coordinate tap senza continuare (ottimizzazione).

    Ritorna:
      (coord_tap, screen) se avatar trovato durante lo scroll
      (None, None)        se avatar non trovato — chiamare _cerca_avatar_scroll
    """
    def log(msg):
        if logger: logger(nome, f"[RIF] {msg}")

    ranghi_tutti   = {"R4", "R3", "R2", "R1"}
    ranghi_gestiti = set()
    prev_md5       = ""
    import hashlib

    log("Apertura toggle: scroll-to-top iniziale")
    _scroll_to_top(porta)

    for swipe_n in range(MAX_SWIPE_TOGGLE):
        screen = adb.screenshot(porta)
        if not screen:
            time.sleep(1.0)
            continue

        # --- Cerca avatar sullo stesso screenshot (ottimizzazione) ---
        if template_avatar and os.path.exists(template_avatar):
            coord = _trova_template(screen, template_avatar,
                                    zona=LISTA_ZONA, soglia=AVATAR_SOGLIA)
            if coord:
                cx, cy = coord
                tap_x = 290 if cx < 490 else 680
                log(f"Avatar trovato durante toggle swipe {swipe_n} a ({cx},{cy}) → tap ({tap_x},{cy})")
                time.sleep(1.2)  # stabilizzazione lista
                return (tap_x, cy), screen

        # --- Cerca badge e gestisci toggle ---
        trovati_ora = {}
        for rango in ranghi_tutti:
            y = _trova_badge_in_screen(screen, rango)
            if y >= 0:
                trovati_ora[rango] = y

        log(f"Swipe {swipe_n}: badge visibili={list(trovati_ora.keys())}")

        rescansiona = False
        for rango in list(trovati_ora.keys()):
            if rango in ranghi_gestiti:
                continue
            if rango not in trovati_ora:
                continue

            y_barra = trovati_ora[rango]
            stato_r = _stato_toggle(screen, y_barra)
            log(f"  {rango} y={y_barra} stato={stato_r}")

            if stato_r == 'chiuso':
                log(f"  → apro {rango} (tap y={y_barra})")
                adb.tap(porta, (480, y_barra), delay_ms=800)
                ranghi_gestiti.add(rango)
                time.sleep(1.5)
                screen = adb.screenshot(porta)
                if not screen:
                    break
                # Dopo apertura: controlla subito se l'avatar è comparso
                if template_avatar and os.path.exists(template_avatar):
                    coord = _trova_template(screen, template_avatar,
                                            zona=LISTA_ZONA, soglia=AVATAR_SOGLIA)
                    if coord:
                        cx, cy = coord
                        tap_x = 290 if cx < 490 else 680
                        log(f"Avatar trovato post-apertura {rango} a ({cx},{cy}) → tap ({tap_x},{cy})")
                        time.sleep(1.2)
                        return (tap_x, cy), screen
                # Rescansiona badge con Y aggiornate
                trovati_ora = {}
                for r2 in ranghi_tutti:
                    y2 = _trova_badge_in_screen(screen, r2)
                    if y2 >= 0:
                        trovati_ora[r2] = y2
                log(f"  (post-tap) badge visibili={list(trovati_ora.keys())}")
                rescansiona = True
                break
            elif stato_r == 'aperto':
                ranghi_gestiti.add(rango)
            else:
                log(f"  → stato sconosciuto per {rango}, salto")

        if rescansiona:
            continue

        if ranghi_tutti.issubset(ranghi_gestiti):
            log(f"Tutti i toggle gestiti: {ranghi_gestiti}")
            break

        # Rilevamento fine lista via MD5
        try:
            with open(screen, 'rb') as f:
                md5 = hashlib.md5(f.read()).hexdigest()
        except Exception:
            md5 = ""

        if md5 and md5 == prev_md5:
            log(f"Fine lista durante apertura toggle (gestiti: {ranghi_gestiti})")
            break
        prev_md5 = md5

        _scroll_avanti(porta)

    mancanti = ranghi_tutti - ranghi_gestiti
    if mancanti:
        log(f"Toggle non trovati: {mancanti} — lista potrebbe non averli")
    else:
        log("Tutti i toggle aperti con successo")

    # Avatar non trovato durante toggle — scroll-to-top per ricerca dedicata
    log("Scroll-to-top prima ricerca avatar")
    _scroll_to_top(porta)
    return None, None


def _cerca_avatar_scroll(porta: str, template_path: str, logger=None, nome: str = ""):
    """
    Scorre la lista dall'alto cercando l'avatar con template matching.
    Fine lista rilevata via MD5 consecutivi identici.
    Ritorna (tap_x, tap_y) oppure None.
    """
    def log(msg):
        if logger: logger(nome, f"[RIF] {msg}")

    import hashlib
    prev_md5 = ""

    for swipe_n in range(MAX_SWIPE_RICERCA + 1):
        screen = adb.screenshot(porta)
        if not screen:
            time.sleep(1.0)
            continue

        # Template matching avatar nella zona lista completa
        coord = _trova_template(screen, template_path,
                                zona=LISTA_ZONA, soglia=AVATAR_SOGLIA)
        if coord:
            cx, cy = coord
            tap_x = 290 if cx < 490 else 680
            log(f"Avatar trovato a ({cx},{cy}) dopo {swipe_n} swipe → attendo stabilizzazione lista...")
            _salva_debug_manual(screen, nome, f'step2_avatar_found_sw{swipe_n}')
            time.sleep(1.2)   # attesa inerzia scroll prima del tap
            log(f"Tap ({tap_x},{cy})")
            return (tap_x, cy)

        # Salva screenshot ogni 4 swipe per debug
        if swipe_n % 4 == 0:
            _salva_debug_manual(screen, nome, f'step2_scroll_sw{swipe_n}')

        # Rilevamento fine lista
        try:
            with open(screen, 'rb') as f:
                md5 = hashlib.md5(f.read()).hexdigest()
        except Exception:
            md5 = ""

        if md5 and md5 == prev_md5:
            log(f"Fine lista dopo {swipe_n} swipe — avatar non trovato")
            _salva_debug_manual(screen, nome, 'step2_fine_lista')
            return None
        prev_md5 = md5

        if swipe_n < MAX_SWIPE_RICERCA:
            log(f"Swipe {swipe_n + 1}/{MAX_SWIPE_RICERCA}")
            _scroll_avanti(porta)

    log(f"Avatar non trovato dopo {MAX_SWIPE_RICERCA} swipe")
    return None


# ------------------------------------------------------------------------------
# Leggi slot liberi raccoglitori da home
# ------------------------------------------------------------------------------
def _slot_liberi(porta: str) -> int:
    """Legge contatore raccoglitori in home. Ritorna slot liberi (0-4)."""
    attive, totale, libere = stato.conta_squadre(porta, n_letture=3)
    if attive == -1 or totale == -1:
        return 4  # fallback ottimistico
    return libere

# ------------------------------------------------------------------------------
# Template matching generico
# ------------------------------------------------------------------------------
def _trova_template(screen_path: str, template_path: str, zona=None, soglia=0.75):
    """
    Cerca template in screen (opzionalmente in zona=(x1,y1,x2,y2)).
    Ritorna (cx, cy) coordinate assolute, oppure None.
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
# Cerca avatar destinatario nella lista visibile
# ------------------------------------------------------------------------------
def _cerca_avatar_visibile(porta: str, template_path: str, logger=None, nome: str = ""):
    def log(msg):
        if logger: logger(nome, f"[RIF] {msg}")

    screen = adb.screenshot(porta)
    if not screen:
        return None

    coord = _trova_template(screen, template_path, zona=AVATAR_ZONA, soglia=AVATAR_SOGLIA)
    if not coord:
        return None

    cx, cy = coord
    tap_x = 290 if cx < 490 else 680
    log(f"Avatar trovato a ({cx},{cy}) → tap ({tap_x},{cy})")
    return (tap_x, cy)

# ------------------------------------------------------------------------------
# OCR maschera "Risorse di Approvvigionamento" — zone calibrate su 960x540
# ------------------------------------------------------------------------------
OCR_NOME_DEST      = (265, 90,  620, 138)  # nome destinatario (testo chiaro)
OCR_PROVVISTE      = (155, 230, 360, 262)  # provviste rimanenti oggi (box scuro, testo bianco)
OCR_TASSA          = (155, 272, 310, 298)  # "Tasse: 23.0%" (testo chiaro)
OCR_CAMION         = (155, 340, 395, 385)  # provvista camion es. "0/1,200,000" (testo crema)
OCR_RESIDUO_OGGI   = OCR_PROVVISTE         # alias per compatibilità
OCR_TEMPO          = (350, 398, 620, 438)  # ETA viaggio "00:00:54"
VAI_ZONA           = (270, 420, 690, 480)  # zona pulsante VAI

# Soglia pixel gialli per VAI abilitato (giallo dorato = abilitato, grigio = disabilitato)
VAI_SOGLIA_GIALLI  = 100


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
    """OCR con filtro colore crema/avorio — per testi colorati su sfondo scuro (es. provvista camion)."""
    try:
        import pytesseract
        img = Image.open(img_path)
        crop = img.crop(box)
        arr = np.array(crop)
        # Testo crema: R>=220, G>=200, B>=180
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
    """True se il pulsante VAI è giallo (abilitato), False se grigio (disabilitato/campi vuoti)."""
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
    Ritorna valore intero, -1 se OCR fallisce, 0 se campo è zero.
    """
    testo = _ocr_otsu(screen_path, OCR_PROVVISTE, whitelist="0123456789,. ")
    testo = testo.replace(",", "").replace(".", "").replace(" ", "").strip()
    try:
        return int(testo)
    except ValueError:
        return -1


def _leggi_tassa(screen_path: str) -> float:
    """
    Legge la percentuale di tassa dalla maschera (es. 'Tasse: 23.0%' -> 0.23).
    Ritorna float, TASSA_DEFAULT se OCR fallisce.
    """
    testo = _ocr_otsu(screen_path, OCR_TASSA, psm=7)
    # Cerca pattern numerico con % es. "23.0" o "23"
    import re
    m = re.search(r'([0-9]+\.?[0-9]*)\s*%', testo)
    if m:
        try:
            return float(m.group(1)) / 100.0
        except ValueError:
            pass
    return TASSA_DEFAULT


def _leggi_eta(screen_path: str) -> int:
    """
    Legge ETA viaggio dalla maschera (es. '00:00:54').
    Ritorna secondi totali, 0 se OCR fallisce.
    """
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
    """
    Legge capacità massima camion dalla provvista (es. '0/1,200,000' -> 1200000).
    Ritorna 0 se OCR fallisce.
    """
    testo = _ocr_crema(screen_path, OCR_CAMION, whitelist="0123456789,./")
    # Estrai la parte dopo '/'
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
    Confronto case-insensitive, accetta match parziale (nome_atteso in testo).
    Ritorna (ok, testo_ocr_pulito).
    """
    testo = _ocr_otsu(screen_path, OCR_NOME_DEST, psm=7)
    testo = testo.replace('|', '').replace('_', '').replace('=', '').strip()
    ok = nome_atteso.lower() in testo.lower()
    return ok, testo


# ------------------------------------------------------------------------------
# Cerca pulsante "Risorse di approvvigionamento" via template matching
# ------------------------------------------------------------------------------
def _trova_pulsante_risorse(porta: str, logger=None, nome: str = "",
                            btn_template: str = None):
    def log(msg):
        if logger: logger(nome, f"[RIF] {msg}")

    if btn_template:
        template_path = btn_template
    else:
        template_path = getattr(config, "RIFORNIMENTO_BTN_TEMPLATE",
                                "templates/btn_risorse_approv.png")

    lingua = "en" if (btn_template and "supply" in btn_template.lower()) else "it"
    import os as _os
    log(f"[DIAG] lingua={lingua} template={template_path} esiste={_os.path.exists(str(template_path))}")

    screen = adb.screenshot(porta)
    if not screen:
        return None

    # --- Strategia 1: template matching standard (IT e EN con template univoco) ---
    coord = _trova_template(screen, template_path, soglia=BTN_RISORSE_SOGLIA)
    if coord:
        log(f"Pulsante Risorse trovato a {coord}")
        return coord

    # --- Strategia 2 (solo EN): il template EN è graficamente simile a "Info"
    #     quindi possono esserci più match. Il popup ha layout fisso 2x2:
    #       [Chat]          [Info]
    #       [Reinforcement] [Resource Supply]
    #     Resource Supply è SEMPRE il pulsante con Y massima tra i match destra.
    if lingua == "en":
        try:
            screen_cv = cv2.imread(screen)
            tmpl_cv   = cv2.imread(template_path)
            if screen_cv is None or tmpl_cv is None:
                log("Pulsante Risorse non trovato via template matching")
                return None

            result = cv2.matchTemplate(screen_cv, tmpl_cv, cv2.TM_CCOEFF_NORMED)
            th, tw = tmpl_cv.shape[:2]

            # Raccogli tutti i match sopra soglia alta, deduplica per cluster 20px
            locations = np.where(result >= 0.85)
            candidati = []
            for pt in zip(*locations[::-1]):
                cx = int(pt[0] + tw // 2)
                cy = int(pt[1] + th // 2)
                score = float(result[pt[1], pt[0]])
                # Deduplica: ignora se già c'è un match entro 20px
                if not any(abs(cx-dx) < 20 and abs(cy-dy) < 20 for _, dx, dy in candidati):
                    candidati.append((score, cx, cy))

            if not candidati:
                log("Pulsante Risorse non trovato via template matching")
                return None

            # Resource Supply = pulsante con Y massima (più in basso)
            # nella metà destra dello schermo (x > 480)
            destra = [(s, cx, cy) for s, cx, cy in candidati if cx > 480]
            if not destra:
                destra = candidati  # fallback: usa tutti

            best = max(destra, key=lambda t: t[2])  # max Y
            log(f"Pulsante Risorse (bottom-right EN) trovato a ({best[1]},{best[2]}) score={best[0]:.3f}")
            return (best[1], best[2])

        except Exception as e:
            log(f"Strategia EN fallita: {e}")

    log("Pulsante Risorse non trovato via template matching")
    return None


# ------------------------------------------------------------------------------
# Naviga alla maschera "Risorse di Approvvigionamento"
# Usa la nuova navigazione avanzata con toggle + scroll
# ------------------------------------------------------------------------------
def _naviga_a_maschera(porta: str, logger=None, nome: str = "",
                       coord_alleanza: tuple = None,
                       btn_template: str = None) -> bool:
    def log(msg):
        if logger: logger(nome, f"[RIF] {msg}")

    template_avatar = getattr(config, "DOOMS_AVATAR", "")
    if not template_avatar or not os.path.exists(template_avatar):
        log(f"ERRORE: template avatar non trovato: {template_avatar}")
        return False

    nome_dest = getattr(config, "DOOMS_ACCOUNT", "")

    # 1. Apri Alleanza → Membri
    _coord_all = coord_alleanza if coord_alleanza else COORD_ALLEANZA_BTN
    log("Tap Alleanza")
    adb.tap(porta, _coord_all, delay_ms=1500)
    log("Tap Membri")
    adb.tap(porta, COORD_MEMBRI, delay_ms=1500)
    # Attesa esplicita rendering lista Membri: i badge R4/R3/R2/R1 appaiono
    # con ritardo variabile (~1-3s). Senza questa attesa il primo swipe
    # non trova badge e degrada in scroll dedicato (25 swipe inutili).
    time.sleep(2.5)

    # 2. Apri tutti i toggle R4/R3/R2/R1 — cerca avatar in parallelo
    coord_tap, _ = _apri_tutti_toggle(porta, logger, nome, template_avatar)

    # 3. Se non trovato durante i toggle, cerca con scroll dedicato
    if not coord_tap:
        coord_tap = _cerca_avatar_scroll(porta, template_avatar, logger, nome)
    if not coord_tap:
        log("ERRORE: avatar non trovato in lista Membri")
        return False

    # 4. Tap membro → popup azioni
    log(f"Tap membro a {coord_tap}")
    adb.tap(porta, coord_tap, delay_ms=1500)

    # 5. Trova pulsante rifornimento (template lingua-specifico)
    btn_coord = None
    for tentativo in range(3):
        btn_coord = _trova_pulsante_risorse(porta, logger, nome, btn_template=btn_template)
        if btn_coord:
            break
        time.sleep(0.8)

    if not btn_coord:
        log("ERRORE: pulsante Risorse non trovato - chiudo popup con BACK")
        adb.keyevent(porta, "KEYCODE_BACK")
        return False

    # 6. Tap pulsante → apre maschera
    log(f"Tap Risorse di approvvigionamento a {btn_coord}")
    adb.tap(porta, btn_coord, delay_ms=2000)
    return True


# ------------------------------------------------------------------------------
# Compila campi e preme VAI nella maschera invio
# ------------------------------------------------------------------------------
def _compila_e_invia(porta: str, quantita: dict, nome_dest: str,
                     logger=None, nome: str = ""):
    """
    Legge la maschera, verifica destinatario, compila le risorse e preme VAI.
    Ritorna (ok: bool, eta_sec: int, quota_esaurita: bool, qta_inviata: int, mismatch_nome: bool).
      ok=False         → errore generico, riprova possibile
      quota_esaurita   → provviste = 0, non rientrare in questo ciclo
      mismatch_nome    → destinatario OCR non corrisponde, retry già effettuato
    """
    def log(msg):
        if logger: logger(nome, f"[RIF] {msg}")

    mismatch_nome = False

    screen = adb.screenshot(porta)
    if not screen:
        return False, 0, False, 0, mismatch_nome
    # Verifica nome destinatario (OBBLIGATORIO).
    # Se mismatch: BACK + HOME e segnala al chiamante per RETRY 1
    if nome_dest:
        ok_nome, testo_ocr = _verifica_nome_destinatario(screen, nome_dest)
        if not ok_nome:
            mismatch_nome = True
            log(f"DEST MISMATCH: destinatario OCR='{testo_ocr}' atteso='{nome_dest}' — ABORT")
            adb.keyevent(porta, "KEYCODE_BACK")
            time.sleep(0.8)
            # Ritorno a HOME pulito (BACK+HOME)
            try:
                import stato as _stato
                _stato.vai_in_home(porta, nome, logger)
            except Exception:
                pass
            return False, 0, False, 0, mismatch_nome

    # Leggi tassa reale dalla maschera
    tassa_reale = _leggi_tassa(screen)
    log(f"Tassa: {tassa_reale*100:.1f}%")

    # Leggi provviste rimanenti
    provviste = _leggi_provviste(screen)
    if provviste >= 0:
        log(f"Provviste rimanenti: {provviste:,}")
    else:
        log("Provviste rimanenti: OCR fallito - procedo")

    if provviste == 0:
        log("Provviste giornaliere esaurite - stop ciclo")
        return False, 0, True, 0, mismatch_nome

    # Leggi ETA e capacità camion
    eta_sec  = _leggi_eta(screen)
    cap_max  = _leggi_capacita_camion(screen)
    log(f"ETA viaggio: {eta_sec}s")

    # Seleziona UNA SOLA risorsa per viaggio (la prima disponibile sopra soglia)
    risorsa_scelta = None
    qta_scelta     = 0
    for risorsa, qta in quantita.items():
        if qta <= 0:
            continue
        if not COORD_CAMPO.get(risorsa):
            continue
        risorsa_scelta = risorsa
        qta_scelta     = qta  # il gioco riduce automaticamente al massimo consentito
        break   # una sola risorsa per viaggio

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

    # Verifica VAI abilitato prima di premere
    screen2 = adb.screenshot(porta)
    if screen2 and not _vai_abilitato(screen2):
        log("VAI non abilitato dopo compilazione — controllo provviste")
        provviste2 = _leggi_provviste(screen2)
        if provviste2 == 0:
            log("Provviste esaurite dopo compilazione")
            return False, 0, True, 0, mismatch_nome
        log("VAI disabilitato per motivo sconosciuto - annullo")
        adb.keyevent(porta, "KEYCODE_BACK")
        return False, 0, False, 0, mismatch_nome

    # Tap VAI
    log("Tap VAI")
    adb.tap(porta, COORD_VAI, delay_ms=2500)
    return True, eta_sec, False, qta_scelta, mismatch_nome


# ------------------------------------------------------------------------------
# Funzione principale
# ------------------------------------------------------------------------------
def esegui_rifornimento(porta: str, nome: str,
                        pomodoro_m: float = -1, legno_m: float = -1,
                        acciaio_m: float = -1, petrolio_m: float = -1,
                        logger=None, ciclo: int = 0,
                        coord_alleanza: tuple = None,
                        btn_template: str = None) -> int:
    """
    Esegue rifornimento risorse al rifugio alleato configurato.
    Ritorna numero di spedizioni effettuate.
    """
    def log(msg):
        if logger: logger(nome, f"[RIF] {msg}")

    # Flag abilitazione — se False il modulo è silenzioso (utile per test graduali)
    if not getattr(config, "RIFORNIMENTO_ABILITATO", RIFORNIMENTO_ABILITATO):
        log("Modulo disabilitato (RIFORNIMENTO_ABILITATO=False) — skip")
        return 0

    # Controlla quota giornaliera (skip se già esaurita oggi)
    if _controlla_reset(nome, porta, logger):
        return 0

    nome_rifugio = getattr(config, "DOOMS_ACCOUNT", "")
    if not nome_rifugio:
        log("DOOMS_ACCOUNT non configurato - skip")
        return 0

    # Soglie per risorsa — ognuna configurabile indipendentemente da runtime.json
    soglie = {
        "pomodoro": getattr(config, "RIFORNIMENTO_SOGLIA_CAMPO_M",    5.0),
        "legno":    getattr(config, "RIFORNIMENTO_SOGLIA_LEGNO_M",    5.0),
        "petrolio": getattr(config, "RIFORNIMENTO_SOGLIA_PETROLIO_M", 2.5),
        "acciaio":  getattr(config, "RIFORNIMENTO_SOGLIA_ACCIAIO_M",  3.5),
    }

    # Quantità per spedizione da config (con fallback a default)
    quantita = {
        "pomodoro": getattr(config, "RIFORNIMENTO_QTA_POMODORO", QTA_DEFAULT["pomodoro"]),
        "legno":    getattr(config, "RIFORNIMENTO_QTA_LEGNO",    QTA_DEFAULT["legno"]),
        "acciaio":  getattr(config, "RIFORNIMENTO_QTA_ACCIAIO",  QTA_DEFAULT["acciaio"]),
        "petrolio": getattr(config, "RIFORNIMENTO_QTA_PETROLIO", QTA_DEFAULT["petrolio"]),
    }

    # Risorse mittente correnti (aggiornate dopo ogni spedizione)
    risorse_m = {
        "pomodoro": pomodoro_m,
        "legno":    legno_m,
        "acciaio":  acciaio_m,
        "petrolio": petrolio_m,
    }

    # Risorse da considerare: qta > 0 in config E soglia non infinita
    risorse_config = {r: q for r, q in quantita.items()
                      if q > 0 and soglie.get(r, float("inf")) < float("inf")}
    if not risorse_config:
        log("Nessuna risorsa configurata per l'invio - skip")
        return 0

    log(f"Risorse configurate: {list(risorse_config.keys())} | "
        f"soglie: { {r: f'{soglie[r]}M' for r in risorse_config} }")

    spedizioni    = 0
    risorse_lista = list(risorse_config.keys())
    idx_risorsa   = 0
    # Coda spedizioni in volo: deque di (timestamp_invio, eta_ar_sec)
    # eta_ar_sec = ETA andata * 2 (A/R)
    coda_volo: deque = deque()
    MARGINE_ATTESA = 8  # secondi extra dopo stima rientro slot

    while True:
        # 1. Rileggi slot liberi dalla home
        slot = _slot_liberi(porta)
        log(f"Slot liberi: {slot}")

        if slot == 0:
            # Calcola attesa ottimale: quanto manca al rientro della spedizione più vecchia
            if coda_volo:
                ts_prima, eta_ar = coda_volo[0]
                trascorso  = time.time() - ts_prima
                manca      = max(0.0, eta_ar - trascorso) + MARGINE_ATTESA
                log(f"Slot occupati — prima spedizione partita {trascorso:.0f}s fa, "
                    f"ETA A/R {eta_ar:.0f}s → attendo {manca:.0f}s")
                time.sleep(manca)
                # Rimuovi dalla coda tutte le spedizioni che dovrebbero essere rientrate
                now = time.time()
                while coda_volo and (now - coda_volo[0][0]) >= coda_volo[0][1]:
                    coda_volo.popleft()
            else:
                # Nessuna info in coda (slot usati da altri) — attesa fissa
                log("Slot occupati, nessuna info in coda — attendo 120s")
                time.sleep(120)

            slot = _slot_liberi(porta)
            log(f"Slot dopo attesa: {slot}")
            if slot == 0:
                log("Nessun slot libero dopo attesa - stop rifornimento")
                break

        # 2. Assicurati di essere in home, poi leggi deposito
        stato.vai_in_home(porta, nome, logger)
        time.sleep(1.5)  # stabilizzazione UI
        screen_home = adb.screenshot(porta)
        risorse_reali = ocr.leggi_risorse(screen_home) if screen_home else {}
        # Retry se tutti i valori sono -1
        if all(risorse_reali.get(r, -1) < 0 for r in risorse_lista):
            log("OCR deposito fallito, attendo 3s e riprovo...")
            time.sleep(3.0)
            screen_home = adb.screenshot(porta)
            risorse_reali = ocr.leggi_risorse(screen_home) if screen_home else {}
        if all(risorse_reali.get(r, -1) < 0 for r in risorse_lista):
            log("OCR deposito fallito dopo retry — skip rifornimento questo ciclo")
            break
        log(f"Deposito: " + " | ".join(
            f"{r}={max(0.0, risorse_reali.get(r,-1))/1e6:.1f}M"
            for r in risorse_lista if risorse_reali.get(r,-1) >= 0
        ))

        # 3. Seleziona risorsa da inviare (rotazione, verifica soglia per risorsa)
        risorsa_scelta = None
        for i in range(len(risorse_lista)):
            r         = risorse_lista[(idx_risorsa + i) % len(risorse_lista)]
            valore_r  = risorse_reali.get(r, -1)
            soglia_r  = soglie.get(r, float("inf"))
            soglia_abs = soglia_r * 1e6
            log(f"  Check {r}: valore={valore_r/1e6:.1f}M soglia={soglia_r}M → {'OK' if valore_r >= soglia_abs else 'SOTTO'}")
            if valore_r >= soglia_abs:
                risorsa_scelta = r
                idx_risorsa = (idx_risorsa + i + 1) % len(risorse_lista)
                break

        if not risorsa_scelta:
            log("Tutte le risorse sotto soglia - stop rifornimento")
            break

        log(f"Risorsa selezionata: {risorsa_scelta} (max 1M per viaggio)")

        # Snapshot PRE-invio: risorse già lette al passo 2 come risorse_reali
        risorse_pre = risorse_reali

        # Valori di default — sovrascritti da _compila_e_invia se ok=True
        # Inizializzati qui per evitare NameError se _naviga_a_maschera fallisce
        # prima che _compila_e_invia venga chiamata.
        eta_sec    = 0
        qta_inviata = 0
        ts_invio   = time.time()
        stop_esterno = False  # True quando quota esaurita → esce anche dal while esterno

        # 4-5. Naviga + compila/invia con RETRY 1 su mismatch nome
        retry_nome_done = False
        while True:
            # Verifica stato prima di navigare: deve essere in home
            if not stato.vai_in_home(porta, nome, logger):
                log("Rifornimento: impossibile raggiungere home prima della navigazione — interruzione")
                stop_esterno = True
                break

            # 4. Naviga alla maschera
            if not _naviga_a_maschera(porta, logger, nome,
                                      coord_alleanza=coord_alleanza,
                                      btn_template=btn_template):
                log("Navigazione fallita - interruzione rifornimento")
                for _ in range(5):
                    adb.keyevent(porta, "KEYCODE_BACK")
                    time.sleep(0.5)
                stato.vai_in_home(porta, nome, logger)
                break

            # 5. Compila e invia
            ts_invio = time.time()
            ok, eta_sec, quota_esaurita, qta_inviata, mismatch_nome = _compila_e_invia(
                porta, {risorsa_scelta: risorse_config[risorsa_scelta]},
                nome_rifugio, logger, nome)

            if quota_esaurita:
                log("Provviste giornaliere esaurite - stop ciclo rifornimento")
                _salva_stato(nome, porta, True)
                log(f"Quota salvata su file: {_path_stato(nome, porta)}")
                stato.vai_in_home(porta, nome, logger)
                stop_esterno = True
                break

            if mismatch_nome and not retry_nome_done:
                log("DEST MISMATCH: retry 1 — riprovo navigazione e verifica nome")
                retry_nome_done = True
                stato.vai_in_home(porta, nome, logger)
                time.sleep(1.0)
                continue

            if not ok:
                log("Invio fallito - interruzione rifornimento")
                adb.keyevent(porta, "KEYCODE_BACK")
                time.sleep(0.5)
                stato.vai_in_home(porta, nome, logger)
                break

            # OK: esci dal retry loop e prosegui
            break

        # Se quota esaurita o errore bloccante → esci dal loop esterno
        if stop_esterno:
            break

        # Registra spedizione solo se l'invio è andato a buon fine (qta_inviata > 0)
        if qta_inviata <= 0:
            continue

        spedizioni += 1
        eta_ar = eta_sec * 2
        coda_volo.append((ts_invio, eta_ar))
        log(f"Spedizione {spedizioni}: {risorsa_scelta} {qta_inviata:,} | ETA A/R {eta_ar}s | In volo: {len(coda_volo)}")
        _log.registra_evento(ciclo, nome, "rifornimento_ok", spedizioni, 1,
                             f"risorsa={risorsa_scelta}")

        # 6. Torna in home e stabilizza
        stato.vai_in_home(porta, nome, logger)
        time.sleep(3.0)

        # 7. Snapshot POST-invio: leggi deposito dopo il ritorno in home.
        #    Il delta (PRE - POST) misura le risorse effettivamente uscite
        #    (quantità inviata + tassa). Registrato in status per dashboard e
        #    calcolo produzione inter-ciclo corretto (evita valori negativi).
        try:
            screen_post = adb.screenshot(porta)
            risorse_post = ocr.leggi_risorse(screen_post) if screen_post else {}
            if all(risorse_post.get(r, -1) < 0 for r in risorse_lista):
                time.sleep(2.0)
                screen_post = adb.screenshot(porta)
                risorse_post = ocr.leggi_risorse(screen_post) if screen_post else {}
            if any(risorse_post.get(r, -1) >= 0 for r in risorse_lista):
                _status.istanza_rifornimento(
                    nome,
                    risorse_pre.get("pomodoro", -1), risorse_pre.get("legno", -1),
                    risorse_pre.get("acciaio",  -1), risorse_pre.get("petrolio", -1),
                    risorse_post.get("pomodoro", -1), risorse_post.get("legno", -1),
                    risorse_post.get("acciaio",  -1), risorse_post.get("petrolio", -1),
                )
                # Aggiorna risorse_reali con i valori POST così il prossimo
                # giro del loop parte dal deposito già aggiornato (evita
                # di ri-scattare uno screenshot inutile al passo 2)
                risorse_reali = risorse_post
                log("Delta rifornimento registrato in status")
            else:
                log("OCR POST-invio fallito — delta non registrato (non bloccante)")
        except Exception as _e:
            log(f"Errore registrazione delta rifornimento (non bloccante): {_e}")

    log(f"Rifornimento completato: {spedizioni} spedizioni totali")
    return spedizioni


# ============================================================================== 
# TEST A STEP (sviluppo) 
# - Queste funzioni NON dipendono dal flag ENABLE_RIFORNIMENTO (servono per debug) 
# ============================================================================== 

def test_step1_home_to_membri(porta: str, nome: str, logger=None) -> bool:
    """STEP 1: da HOME -> ALLEANZA -> MEMBRI. Ritorna True se arriva in pagina membri."""
    def log(msg):
        if logger:
            logger(nome, f"[RIF][S1] {msg}")

    log('Start: HOME -> ALLEANZA -> MEMBRI')

    # prova a stabilizzare: se in overlay, back leggero
    try:
        import stato as _st
        _st.vai_in_home(porta, nome, logger)
    except Exception:
        pass

    adb.tap(porta, COORD_ALLEANZA_BTN, delay_ms=1500)
    adb.tap(porta, COORD_MEMBRI, delay_ms=1500)

    screen = adb.screenshot(porta)
    dest = _salva_debug_manual(screen, nome, 'step1_membri')
    log(f"Screenshot: {dest or screen}")

    # Verifica "debole": se siamo in pagina membri di solito compare il menu sinistro con MEMBRI evidenziato.
    # Per ora la verifica è manuale via screenshot.
    log('Verifica: apri lo screenshot e controlla che sia la pagina MEMBRI')
    return True if screen else False


def test_step2_find_avatar(porta: str, nome: str, logger=None, max_swipe: int = None) -> bool:
    """
    STEP 2: nella pagina Membri, apre tutti i toggle R4/R3/R2/R1,
    poi scorre la lista cercando l'avatar con template matching.
    Salva screenshot di debug a ogni fase.

    Algoritmo:
      1. Scroll-to-top (stato noto)
      2. Scorre la lista aprendo tutti i toggle R chiusi (OCR + centroide freccia)
      3. Scroll-to-top di nuovo
      4. Cerca avatar con scroll continuo (fine lista via MD5)
      5. Tap sul membro trovato

    Ritorna True se trova e tappa il membro.
    """
    def log(msg):
        if logger:
            logger(nome, f"[RIF][S2] {msg}")

    template_avatar = getattr(config, 'DOOMS_AVATAR', '')
    if not template_avatar or not os.path.exists(template_avatar):
        log(f"Template avatar mancante: {template_avatar}")
        return False

    log("=== STEP 2: ricerca avatar avanzata ===")

    # --- Fase 1+2: apri tutti i toggle ---
    log("Fase 1: apertura toggle R4/R3/R2/R1 (con ricerca avatar in parallelo)")
    coord_tap, _ = _apri_tutti_toggle(porta, logger, nome, template_avatar)

    # --- Fase 2: se non trovato durante toggle, scroll dedicato ---
    if not coord_tap:
        log("Avatar non trovato durante toggle — avvio scroll dedicato")
        coord_tap = _cerca_avatar_scroll(porta, template_avatar, logger, nome)
    else:
        log("Avatar trovato durante fase toggle — scroll dedicato saltato")

    if not coord_tap:
        log("Avatar NON trovato dopo apertura toggle e scroll completo")
        screen = adb.screenshot(porta)
        _salva_debug_manual(screen, nome, 'step2_avatar_notfound_finale')
        return False

    # --- Fase 5: tap sul membro ---
    log(f"Tap membro a {coord_tap}")
    adb.tap(porta, coord_tap, delay_ms=1500)

    screen2 = adb.screenshot(porta)
    dest2 = _salva_debug_manual(screen2, nome, 'step2_post_tap')
    log(f"Screenshot post tap: {dest2 or screen2}")
    log("Verifica: deve comparire pannello azioni (Chat/Info/Rinforzo/Risorse)")
    return True


def test_step3_open_supply_mask(porta: str, nome: str, logger=None) -> bool:
    """
    STEP 3: assume pannello azioni visibile (popup Chat/Info/Rinforzo/Risorse).
    Apre "Risorse di approvvigionamento", legge tutti i campi, compila 1M e preme VAI.

    Sequenza:
      1. Trova pulsante "Risorse di approvvigionamento" via template matching
      2. Tap → apre maschera
      3. Screenshot + OCR: verifica nome, legge provviste/ETA/capacità/VAI
      4. Compila risorsa configurata (default: 1M pomodoro)
      5. Verifica VAI abilitato → tap VAI
      6. Ritorna in home
    """
    def log(msg):
        if logger:
            logger(nome, f"[RIF][S3] {msg}")

    nome_dest = getattr(config, "DOOMS_ACCOUNT", "")

    log("Start: apertura maschera Risorse di approvvigionamento")

    # 1. Trova e tappa pulsante
    btn = _trova_pulsante_risorse(porta, logger, nome)
    if not btn:
        screen = adb.screenshot(porta)
        _salva_debug_manual(screen, nome, "step3_btn_notfound")
        log("Pulsante non trovato — screenshot salvato")
        return False

    log(f"Tap pulsante Risorse a {btn}")
    adb.tap(porta, btn, delay_ms=2000)

    # 2. Screenshot maschera e OCR tutti i campi
    screen = adb.screenshot(porta)
    if not screen:
        log("Screenshot maschera fallito")
        return False
    _salva_debug_manual(screen, nome, "step3_maschera_inizio")

    nome_letto   = _ocr_otsu(screen, OCR_NOME_DEST, psm=7).replace("|","").replace("_","").strip()
    provviste    = _leggi_provviste(screen)
    eta_s        = _leggi_eta(screen)
    cap_max      = _leggi_capacita_camion(screen)
    vai_ok       = _vai_abilitato(screen)

    log(f"Destinatario OCR: '{nome_letto}' | atteso: '{nome_dest}' | match: {nome_dest.lower() in nome_letto.lower()}")
    log(f"Provviste rimanenti: {provviste:,}" if provviste >= 0 else "Provviste: OCR fallito")
    log(f"ETA viaggio: {eta_s}s ({eta_s//60}m{eta_s%60}s) | A/R: {eta_s*2}s")
    log(f"Capacità camion: {cap_max:,}" if cap_max > 0 else "Capacità camion: OCR fallito")
    log(f"VAI allo stato iniziale: {'abilitato' if vai_ok else 'disabilitato (atteso)'}")

    if provviste == 0:
        log("Provviste = 0 → VAI disabilitato, nulla da inviare — uscita")
        adb.keyevent(porta, "KEYCODE_BACK")
        return False

    # 3. Compila risorsa (default: 1M pomodoro)
    qta_default = getattr(config, "RIFORNIMENTO_QTA_POMODORO", 1_000_000)
    risorsa     = "pomodoro"
    qta         = min(qta_default, cap_max) if cap_max > 0 else qta_default
    log(f"Compila {risorsa}: {qta:,}")

    coord_campo = COORD_CAMPO.get(risorsa)
    if not coord_campo:
        log(f"Coordinate campo {risorsa} non trovate — stop")
        adb.keyevent(porta, "KEYCODE_BACK")
        return False

    # Triple tap per attivare e selezionare tutto, poi cancella e scrivi
    adb.tap(porta, coord_campo, delay_ms=300)
    adb.tap(porta, coord_campo, delay_ms=300)
    adb.tap(porta, coord_campo, delay_ms=600)
    for _ in range(12):
        adb.keyevent(porta, "KEYCODE_DEL")
    time.sleep(0.3)
    adb.input_text(porta, str(qta))
    time.sleep(0.5)
    adb.tap(porta, config.TAP_OK_TASTIERA, delay_ms=500)

    # 4. Screenshot post-compilazione — verifica VAI abilitato
    screen2 = adb.screenshot(porta)
    if screen2:
        _salva_debug_manual(screen2, nome, "step3_maschera_compilata")
        vai_dopo = _vai_abilitato(screen2)
        log(f"VAI dopo compilazione: {'ABILITATO' if vai_dopo else 'DISABILITATO'}")
        if not vai_dopo:
            log("VAI non abilitato — annullo con BACK")
            adb.keyevent(porta, "KEYCODE_BACK")
            return False

    # 5. Tap VAI
    log("Tap VAI → invio risorse")
    adb.tap(porta, COORD_VAI, delay_ms=2500)

    # 6. Ritorna in home (il gioco dopo VAI torna in mappa)
    screen3 = adb.screenshot(porta)
    if screen3:
        _salva_debug_manual(screen3, nome, "step3_post_vai")
    log("Ritorno in home")
    stato.vai_in_home(porta, nome, logger)

    log(f"Step 3 completato — spedizione {risorsa} {qta:,} | ETA slot libero: ~{eta_s*2}s")
    return True
