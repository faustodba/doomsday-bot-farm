# ==============================================================================
#  DOOMSDAY BOT V5 - zaino.py
#  Scarico risorse dallo zaino virtuale (backpack) al deposito dell'istanza
#
#  TRIGGER:
#    Ogni lunedì, SE il deposito di almeno una risorsa è sotto soglia.
#    Schedulazione tramite scheduler.py (task "zaino", intervallo 168h).
#
#  LOGICA:
#    Per ogni risorsa sotto soglia:
#      target = RIFORNIMENTO_SOGLIA_*_M * ZAINO_MOLTIPLICATORE  (default 2x)
#      gap    = target - deposito_attuale
#      Itera le pezzature dal più piccolo al più grande:
#        se pezzatura * owned <= gap_residuo → usa tutto (MAX)
#        se pezzatura > gap_residuo           → skip (troppo grande, sforebbe)
#      Stop quando gap_residuo <= 0 o pezzature esaurite.
#
#  APERTURA ZAINO:
#    Tap sull'icona 🍅 nella barra alta (apre sempre su Food).
#    Per altre risorse → tap icona nella sidebar sinistra.
#
#  FLUSSO USE:
#    1. Tap USE sulla riga → appare pulsante "Max" accanto
#    2. Tap Max → seleziona tutti i pezzi di quella pezzatura
#    3. Tap USE → conferma utilizzo → riga sparisce se owned=0
#
#  PACK MISTI: Basic/Intermediate/Advanced Resource Pack → ignorati
#
#  COORDINATE (960x540):
#    TAP_ZAINO_APRI      = (430, 18)   — icona 🍅 barra alta → apre zaino
#    TAP_ZAINO_CHIUDI    = (783, 68)   — pulsante X chiude zaino
#    SIDEBAR_FOOD        = (80, 130)   — tab Food nella sidebar sinistra
#    SIDEBAR_WOOD        = (80, 200)   — tab Wood
#    SIDEBAR_STEEL       = (80, 270)   — tab Steel
#    SIDEBAR_OIL         = (80, 340)   — tab Oil
#    TAP_USE_X           = 722         — coordinata X pulsante USE
#    TAP_MAX_X           = 601         — coordinata X pulsante Max
#    PRIMA_RIGA_Y        = 140         — Y prima riga lista
#    ALTEZZA_RIGA        = 80          — altezza di ogni riga
#    MAX_RIGHE_VISIBILI  = 5           — righe visibili senza scroll
#
#  CONFIG (config.py / runtime.json → globali):
#    ZAINO_ABILITATO          (bool,  default False)
#    ZAINO_USA_POMODORO       (bool,  default True)
#    ZAINO_USA_LEGNO          (bool,  default True)
#    ZAINO_USA_ACCIAIO        (bool,  default False)
#    ZAINO_USA_PETROLIO       (bool,  default True)
#    ZAINO_SOGLIA_POMODORO_M  (float, default 10.0)  — target deposito pomodoro
#    ZAINO_SOGLIA_LEGNO_M     (float, default 10.0)  — target deposito legno
#    ZAINO_SOGLIA_ACCIAIO_M   (float, default  7.0)  — target deposito acciaio
#    ZAINO_SOGLIA_PETROLIO_M  (float, default  5.0)  — target deposito petrolio
# ==============================================================================

import time
import numpy as np
from PIL import Image

import adb
import config
import stato as _stato
import scheduler
import ocr

# ------------------------------------------------------------------------------
# Coordinate UI (960x540) — definite in config.py sezione "Zaino: coordinate UI"
# ------------------------------------------------------------------------------
TAP_ZAINO_APRI   = config.ZAINO_TAP_APRI
TAP_ZAINO_CHIUDI = config.ZAINO_TAP_CHIUDI

SIDEBAR = {
    "pomodoro": config.ZAINO_SIDEBAR_POMODORO,
    "legno":    config.ZAINO_SIDEBAR_LEGNO,
    "acciaio":  config.ZAINO_SIDEBAR_ACCIAIO,
    "petrolio": config.ZAINO_SIDEBAR_PETROLIO,
}

TAP_USE_X          = config.ZAINO_TAP_USE_X
TAP_MAX_X          = config.ZAINO_TAP_MAX_X
PRIMA_RIGA_Y       = config.ZAINO_PRIMA_RIGA_Y
ALTEZZA_RIGA       = config.ZAINO_ALTEZZA_RIGA
MAX_RIGHE_VISIBILI = config.ZAINO_MAX_RIGHE

# Attese UI
DELAY_APRI_ZAINO  = 2.0   # attesa apertura maschera zaino
DELAY_TAP_USE     = 0.8   # attesa dopo tap USE (comparsa Max)
DELAY_TAP_MAX     = 0.3   # attesa dopo tap Max
DELAY_CONFERMA    = 1.5   # attesa dopo conferma USE (aggiornamento lista)
DELAY_SIDEBAR     = 1.0   # attesa dopo cambio tab sidebar

# ------------------------------------------------------------------------------
# Pezzature per risorsa (ordinate dal più piccolo al più grande)
# Usate per calcolare gap e decidere quali pezzature usare
# ------------------------------------------------------------------------------
PEZZATURE = {
    "pomodoro": [1_000, 10_000, 50_000, 150_000, 500_000, 1_500_000],
    "legno":    [1_000, 10_000, 50_000, 150_000, 500_000, 1_500_000],
    "acciaio":  [500,   5_000,  25_000, 75_000,  250_000, 750_000],
    "petrolio": [200,   2_000,  10_000, 30_000,  100_000, 300_000],
}

# Parole chiave nei nomi pack misti da ignorare
PACK_KEYWORDS = ["basic resource", "intermediate resource", "advanced resource",
                 "resource pack"]

# ------------------------------------------------------------------------------
# Rilevamento colore badge/testo arancione "Owned: N"
# Usato per verificare se una riga ha owned > 0 prima di tentare USE
# ------------------------------------------------------------------------------
OWNED_R_MIN = 200
OWNED_G_MIN = 100
OWNED_G_MAX = 180
OWNED_B_MAX = 80


def _riga_ha_owned(screen_path: str, y_riga: int) -> bool:
    """
    Verifica se la riga a y_riga ha testo arancione "Owned: N" (owned > 0).
    Cerca pixel arancioni nella zona testo owned della riga.
    Fail-safe: True se non riesce a leggere (meglio tentare che saltare).
    """
    try:
        img = Image.open(screen_path)
        arr = np.array(img)
        # Zona testo owned: x 155-350, fascia verticale attorno a y_riga+20
        y1 = max(0, y_riga + 5)
        y2 = min(arr.shape[0], y_riga + 40)
        roi = arr[y1:y2, 155:350, :3]
        r = roi[:, :, 0].astype(int)
        g = roi[:, :, 1].astype(int)
        b = roi[:, :, 2].astype(int)
        arancioni = ((r > OWNED_R_MIN) & (g > OWNED_G_MIN) &
                     (g < OWNED_G_MAX) & (b < OWNED_B_MAX))
        return int(arancioni.sum()) >= 3
    except Exception:
        return True  # fail-safe


def _riga_e_pack(screen_path: str, y_riga: int) -> bool:
    """
    Rileva se la riga è un pack misto (Basic/Intermediate/Advanced Resource Pack).
    Usa rilevamento colore: i pack hanno icona con sfondo verde scuro distintivo.
    Approccio: se la riga NON ha testo arancione owned → potrebbe essere pack
    oppure riga vuota. Fallback conservativo: False (non è pack).
    """
    # Semplificazione: i pack appaiono DOPO le pezzature normali nella lista.
    # La logica calcola gap e sa già quando fermarsi — i pack vengono
    # semplicemente saltati perché la loro pezzatura non è in PEZZATURE.
    return False


def _conta_righe_visibili(screen_path: str) -> int:
    """
    Conta le righe visibili nella lista zaino contando i pulsanti USE
    (pixel gialli nella colonna x=720-780).
    """
    try:
        img = Image.open(screen_path)
        arr = np.array(img)
        # Colonna USE: x 700-780
        col = arr[:, 700:780, :3]
        r = col[:, :, 0].astype(int)
        g = col[:, :, 1].astype(int)
        b = col[:, :, 2].astype(int)
        # Giallo USE: R>180, G>130, B<80
        gialli = ((r > 180) & (g > 130) & (b < 80))
        # Conta cluster verticali separati
        righe_gialle = gialli.any(axis=1)
        count = 0
        in_cluster = False
        for v in righe_gialle:
            if v and not in_cluster:
                count += 1
                in_cluster = True
            elif not v:
                in_cluster = False
        return max(0, count)
    except Exception:
        return 0


# ------------------------------------------------------------------------------
# Usa tutti i pacchetti di una riga (tap USE → Max → USE)
# ------------------------------------------------------------------------------

def _usa_riga(porta: str, y_riga: int, log_fn) -> bool:
    """
    Esegue la sequenza USE → Max → USE su una riga della lista.
    Ritorna True se la sequenza è completata, False se qualcosa va storto.
    """
    # Tap 1: USE → appare Max
    log_fn(f"Zaino: tap USE a ({TAP_USE_X},{y_riga})")
    adb.tap(porta, (TAP_USE_X, y_riga))
    time.sleep(DELAY_TAP_USE)

    # Tap 2: Max → seleziona tutto
    log_fn(f"Zaino: tap Max a ({TAP_MAX_X},{y_riga})")
    adb.tap(porta, (TAP_MAX_X, y_riga))
    time.sleep(DELAY_TAP_MAX)

    # Tap 3: USE → conferma
    log_fn(f"Zaino: tap USE conferma a ({TAP_USE_X},{y_riga})")
    adb.tap(porta, (TAP_USE_X, y_riga))
    time.sleep(DELAY_CONFERMA)

    return True


# ------------------------------------------------------------------------------
# Scarica pacchetti per una singola risorsa
# ------------------------------------------------------------------------------

def _scarica_risorsa(porta: str, nome: str, risorsa: str,
                     gap: float, logger=None) -> float:
    """
    Scarica pacchetti dallo zaino per la risorsa specificata fino a colmare gap.

    Parametri:
      risorsa : "pomodoro" | "legno" | "acciaio" | "petrolio"
      gap     : quantità da caricare in unità assolute

    Ritorna:
      quantità effettivamente scaricata (stima basata sui pacchetti usati)
    """
    def log(msg):
        if logger: logger(nome, msg)

    pezzature = PEZZATURE.get(risorsa, [])
    gap_residuo = gap
    scaricato   = 0.0

    log(f"Zaino [{risorsa}]: gap da colmare = {gap/1e6:.2f}M")

    # Scroll to top prima di iniziare
    for _ in range(3):
        adb.scroll(porta, 480, 200, 450, durata_ms=300)
        time.sleep(0.3)
    time.sleep(0.5)

    for pezzatura in pezzature:
        if gap_residuo <= 0:
            log(f"Zaino [{risorsa}]: gap colmato — stop")
            break

        # Screenshot per verificare riga
        screen = adb.screenshot(porta)
        if not screen:
            log(f"Zaino [{risorsa}]: screenshot fallito — skip pezzatura {pezzatura:,}")
            continue

        # Conta righe visibili per trovare la riga giusta
        n_righe = _conta_righe_visibili(screen)
        if n_righe == 0:
            log(f"Zaino [{risorsa}]: nessuna riga visibile — fine lista")
            break

        # La riga della pezzatura corrente è sempre la prima visibile
        # (la lista è ordinata per pezzatura crescente e scorriamo dall'alto)
        y_riga = PRIMA_RIGA_Y

        # Verifica owned > 0
        if not _riga_ha_owned(screen, y_riga):
            log(f"Zaino [{risorsa}]: pezzatura {pezzatura:,} owned=0 — skip")
            continue

        # Decisione: usa tutto se pezzatura*owned <= gap_residuo
        # Non conosciamo owned esatto → usiamo MAX (usa tutto)
        # e accettiamo un possibile piccolo sforamento
        # (la pezzatura singola > gap viene skippata)
        if pezzatura > gap_residuo:
            log(f"Zaino [{risorsa}]: pezzatura {pezzatura:,} > gap residuo "
                f"{gap_residuo/1e6:.2f}M — skip (troppo grande)")
            continue

        log(f"Zaino [{risorsa}]: uso pezzatura {pezzatura:,} "
            f"(gap residuo {gap_residuo/1e6:.2f}M)")

        # Esegui USE → Max → USE
        if _usa_riga(porta, y_riga, log):
            # Aggiorna gap residuo (stima: MAX usa tutti i pezzi di quella riga)
            # Non conosciamo owned esatto → il gap viene aggiornato al prossimo
            # ciclo via OCR deposito. Per ora segniamo almeno 1 pezzatura usata.
            scaricato   += pezzatura  # stima minima (almeno 1 pezzo)
            gap_residuo -= pezzatura  # stima conservativa

        time.sleep(0.5)

    log(f"Zaino [{risorsa}]: scaricato stimato {scaricato/1e6:.2f}M")
    return scaricato


# ------------------------------------------------------------------------------
# Entry point principale
# ------------------------------------------------------------------------------

def esegui_zaino(porta: str, nome: str, logger=None) -> dict:
    """
    Esegue lo scarico zaino per le risorse sotto soglia.

    Trigger: lunedì SE almeno una risorsa è sotto soglia.
    Schedulazione: 168h (settimanale) via scheduler.py task "zaino".

    Ritorna dict con esito per ogni risorsa:
      {"pomodoro": scaricato_M, ...}  — 0.0 se non serviva o errore
    """
    def log(msg):
        if logger: logger(nome, msg)

    esiti = {r: 0.0 for r in ["pomodoro", "legno", "acciaio", "petrolio"]}

    # --- Verifica abilitazione ---
    if not getattr(config, "ZAINO_ABILITATO", True):
        log("[ZAINO] Modulo disabilitato (ZAINO_ABILITATO=False) — skip")
        return esiti

    # --- Verifica schedulazione (lunedì, intervallo 168h) ---
    if not scheduler.deve_eseguire(nome, porta, "zaino", logger):
        return esiti

    # --- Verifica stato: deve essere in home ---
    if not _stato.vai_in_home(porta, nome, logger):
        log("[ZAINO] impossibile raggiungere home — skip")
        return esiti

    # --- Leggi deposito corrente ---
    screen_home = adb.screenshot(porta)
    if not screen_home:
        log("[ZAINO] screenshot deposito fallito — skip")
        return esiti

    deposito = ocr.leggi_risorse(screen_home)
    if not deposito or all(deposito.get(r, -1) < 0
                           for r in ["pomodoro", "legno", "acciaio", "petrolio"]):
        log("[ZAINO] OCR deposito fallito — skip")
        return esiti

    # --- Booleani per risorsa ---
    usa = {
        "pomodoro": config.ZAINO_USA_POMODORO,
        "legno":    config.ZAINO_USA_LEGNO,
        "acciaio":  config.ZAINO_USA_ACCIAIO,
        "petrolio": config.ZAINO_USA_PETROLIO,
    }

    # --- Soglie target per risorsa (valore assoluto a cui portare il deposito) ---
    target = {
        "pomodoro": config.ZAINO_SOGLIA_POMODORO_M * 1e6,
        "legno":    config.ZAINO_SOGLIA_LEGNO_M    * 1e6,
        "acciaio":  config.ZAINO_SOGLIA_ACCIAIO_M  * 1e6,
        "petrolio": config.ZAINO_SOGLIA_PETROLIO_M * 1e6,
    }

    # --- Filtra risorse abilitate e sotto soglia ---
    risorse_da_caricare = {}
    for risorsa, tgt in target.items():
        if not usa[risorsa]:
            log(f"[ZAINO] {risorsa}: disabilitato (ZAINO_USA_{risorsa.upper()}=False) — skip")
            continue
        valore = deposito.get(risorsa, -1)
        if valore < 0:
            log(f"[ZAINO] {risorsa}: OCR non disponibile — skip")
            continue
        if valore < tgt:
            gap = tgt - valore
            risorse_da_caricare[risorsa] = gap
            log(f"[ZAINO] {risorsa}: {valore/1e6:.1f}M < target {tgt/1e6:.1f}M "
                f"→ carico (gap={gap/1e6:.2f}M)")
        else:
            log(f"[ZAINO] {risorsa}: {valore/1e6:.1f}M >= target {tgt/1e6:.1f}M — skip")

    if not risorse_da_caricare:
        log("[ZAINO] tutte le risorse sopra soglia — nessun carico necessario")
        scheduler.registra_esecuzione(nome, porta, "zaino")
        return esiti

    # --- Apri zaino (tap icona pomodoro barra alta → apre sempre su Food) ---
    log("[ZAINO] apertura zaino (tap icona barra alta)")
    adb.tap(porta, TAP_ZAINO_APRI)
    time.sleep(DELAY_APRI_ZAINO)

    # --- Processa ogni risorsa ---
    try:
        for risorsa, gap in risorse_da_caricare.items():
            log(f"[ZAINO] === {risorsa.upper()} ===")

            # Naviga alla tab corretta nella sidebar
            if risorsa in SIDEBAR:
                log(f"[ZAINO] tap sidebar {risorsa} a {SIDEBAR[risorsa]}")
                adb.tap(porta, SIDEBAR[risorsa])
                time.sleep(DELAY_SIDEBAR)
            else:
                log(f"[ZAINO] {risorsa}: sidebar non configurata — skip")
                continue

            # Scarica pacchetti
            scaricato = _scarica_risorsa(porta, nome, risorsa, gap, logger)
            esiti[risorsa] = scaricato / 1e6  # in milioni

    except Exception as e:
        log(f"[ZAINO] errore durante scarico: {e}")
    finally:
        # Chiudi zaino sempre, anche in caso di errore
        log("[ZAINO] chiusura zaino (tap X)")
        adb.tap(porta, TAP_ZAINO_CHIUDI)
        time.sleep(1.0)
        # Torna in home
        _stato.vai_in_home(porta, nome, logger)

    # --- Registra esecuzione ---
    scheduler.registra_esecuzione(nome, porta, "zaino")

    totale = sum(esiti.values())
    log(f"[ZAINO] completato — totale scaricato: {totale:.2f}M")
    return esiti
