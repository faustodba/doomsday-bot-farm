# ============================================================================== 
# DOOMSDAY BOT V5 - stato.py
# Rilevamento stato istanza: home / mappa / overlay / sconosciuto
#
# POTENZIAMENTO:
# - Secondo sensore basato sul bottone toggle basso-sinistra (OCR Region/Shelter).
# - Log diagnostico opzionale quando il sensore toggle override la decisione base.
# - Contatore override PER ISTANZA (nome+porta) thread-safe.
# ============================================================================== 

import time
import threading
from collections import defaultdict
import adb
import config

# --- Parametri BACK rapidi ---
N_BACK = 5
DELAY_BACK = 0.3
DELAY_POST_BACK = 0.5

# --- Massimo cicli di BACK per uscire da overlay persistente ---
MAX_CICLI_BACK = 4

# --- Massimo tentativi tap per vai_in_mappa ---
MAX_TENTATIVI_MAPPA = 3

# --- Contatore override del sensore toggle (per istanza) ---
_TOGGLE_OVERRIDE_LOCK = threading.Lock()
_TOGGLE_OVERRIDE_COUNT = defaultdict(int)  # key: (nome, porta_str) -> int


def _key_istanza(nome=None, porta=None):
    return (str(nome or ''), str(porta or ''))


def get_toggle_override_count(nome=None, porta=None) -> int:
    """Ritorna il numero di override.

    - Se nome+porta forniti: contatore per quella istanza.
    - Se non forniti: somma totale di tutte le istanze.
    """
    with _TOGGLE_OVERRIDE_LOCK:
        if nome is None and porta is None:
            return int(sum(_TOGGLE_OVERRIDE_COUNT.values()))
        return int(_TOGGLE_OVERRIDE_COUNT.get(_key_istanza(nome, porta), 0))


def reset_toggle_override_count(nome=None, porta=None) -> None:
    """Reset contatore override.

    - Se nome+porta forniti: reset solo per quella istanza.
    - Se non forniti: reset totale.
    """
    with _TOGGLE_OVERRIDE_LOCK:
        if nome is None and porta is None:
            _TOGGLE_OVERRIDE_COUNT.clear()
        else:
            _TOGGLE_OVERRIDE_COUNT[_key_istanza(nome, porta)] = 0


# ------------------------------------------------------------------------------
# Helpers OCR toggle basso-sinistra (secondo sensore)
# ------------------------------------------------------------------------------

def _scale_box(box, w, h, base_w=960, base_h=540):
    x1, y1, x2, y2 = box
    sx = w / float(base_w)
    sy = h / float(base_h)
    return (int(x1*sx), int(y1*sy), int(x2*sx), int(y2*sy))


def _ocr_testo_toggle(screen_path: str) -> str:
    """OCR normalizzato (solo lettere) della label sul bottone toggle basso-sinistra."""
    if not getattr(config, 'STATO_TOGGLE_OCR_ABILITATO', True):
        return ''
    try:
        from PIL import Image, ImageOps
        import pytesseract

        if getattr(config, 'TESSERACT_EXE', ''):
            pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_EXE

        img = Image.open(screen_path)
        W, H = img.size
        box = getattr(config, 'STATO_TOGGLE_LABEL_ZONA', (0, 396, 228, 540))
        x1, y1, x2, y2 = _scale_box(box, W, H)
        x1 = max(0, min(W-1, x1)); x2 = max(1, min(W, x2))
        y1 = max(0, min(H-1, y1)); y2 = max(1, min(H, y2))
        roi = img.crop((x1, y1, x2, y2))

        gray = ImageOps.grayscale(roi)
        gray = ImageOps.autocontrast(gray)
        bw = gray.point(lambda p: 255 if p > 160 else 0)

        psm = int(getattr(config, 'STATO_TOGGLE_OCR_PSM', 7))
        tcfg = f"--psm {psm} -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
        text = pytesseract.image_to_string(bw, config=tcfg) or ''
        return ''.join(ch for ch in text.upper() if ch.isalpha())
    except Exception:
        return ''


def _sensore_toggle(screen_path: str) -> tuple:
    """Deduce stato dalla label toggle: ritorna (stato, testo_ocr)."""
    txt = _ocr_testo_toggle(screen_path)
    if not txt:
        return ('', '')

    key_home = getattr(config, 'STATO_TOGGLE_KEY_HOME', ['REGION', 'REGIONE'])
    key_map = getattr(config, 'STATO_TOGGLE_KEY_MAPPA', ['SHELTER', 'RIFUGIO'])

    for k in key_home:
        if k and k.upper().replace(' ', '') in txt:
            return ('home', txt)
    for k in key_map:
        if k and k.upper().replace(' ', '') in txt:
            return ('mappa', txt)

    return ('', txt)


# ------------------------------------------------------------------------------
# Rileva stato corrente (senza screenshot: usa screen già scattato)
# ------------------------------------------------------------------------------

def rileva_screen(screen: str, porta=None, nome=None) -> str:
    """Rileva stato da screen già scattato.

    Parametri opzionali (per diagnostica/contatori):
    - porta: porta adb dell'istanza
    - nome: nome istanza

    Stati possibili:
    - 'home'
    - 'mappa'
    - 'overlay'
    - 'sconosciuto'
    """
    if not screen:
        return 'sconosciuto'

    def _px(x: int, y: int):
        return adb.leggi_pixel(screen, x, y)

    # 1) Popup "Uscire dal gioco?" (overlay)
    r0, g0, b0 = _px(config.POPUP_CHECK_X, config.POPUP_CHECK_Y)
    if r0 != -1:
        is_beige = (
            config.BEIGE_R_MIN <= r0 <= config.BEIGE_R_MAX and
            config.BEIGE_G_MIN <= g0 <= config.BEIGE_G_MAX and
            config.BEIGE_B_MIN <= b0 <= config.BEIGE_B_MAX
        )
        rok, gok, bok = _px(config.POPUP_OK_X, config.POPUP_OK_Y)
        is_ok_yellow = (
            rok != -1 and
            config.POPUP_OK_R_MIN <= rok <= config.POPUP_OK_R_MAX and
            config.POPUP_OK_G_MIN <= gok <= config.POPUP_OK_G_MAX and
            config.POPUP_OK_B_MIN <= bok <= config.POPUP_OK_B_MAX
        )
        if is_beige and is_ok_yellow:
            return 'overlay'

    # 2) Home/Mappa (campionamento multiplo)
    offsets = getattr(config, 'STATO_CHECK_OFFSETS', [(0, 0)])
    soglia_r = config.STATO_SOGLIA_R
    min_sum = getattr(config, 'STATO_MIN_MAPPA_RGB_SUM', 20)

    home_votes = 0
    mappa_votes = 0
    valid = 0

    for dx, dy in offsets:
        r, g, b = _px(config.STATO_CHECK_X + dx, config.STATO_CHECK_Y + dy)
        if r == -1:
            continue
        valid += 1
        if (r + g + b) < min_sum:
            continue
        if r < soglia_r:
            home_votes += 1
        else:
            mappa_votes += 1

    if valid == 0:
        base = 'sconosciuto'
    else:
        if home_votes > mappa_votes and home_votes > 0:
            base = 'home'
        elif mappa_votes >= home_votes and mappa_votes > 0:
            base = 'mappa'
        else:
            base = 'overlay'

    # 3) Secondo sensore solo se incerto
    incerto = (valid < 3) or (abs(home_votes - mappa_votes) <= 1)
    if incerto:
        s2, txt2 = _sensore_toggle(screen)
        if s2 in ('home', 'mappa'):
            override = (s2 != base)
            if override:
                with _TOGGLE_OVERRIDE_LOCK:
                    _TOGGLE_OVERRIDE_COUNT[_key_istanza(nome, porta)] += 1
                    n = int(_TOGGLE_OVERRIDE_COUNT[_key_istanza(nome, porta)])
            else:
                n = get_toggle_override_count(nome, porta)

            if getattr(config, 'STATO_TOGGLE_DEBUG', False) and override:
                try:
                    ident = f"{nome or '?'}:{porta or '?'}"
                    print(
                        f"[STATO][TOGGLE] {ident} override#{n}: base={base} "
                        f"(home_votes={home_votes}, mappa_votes={mappa_votes}, valid={valid}) "
                        f"-> toggle={s2} (ocr='{txt2}')"
                    )
                except Exception:
                    pass
            return s2

    return base


def rileva(porta: str, nome: str = None) -> tuple:
    """Scatta screenshot e rileva stato. Ritorna (stato, screen_path)."""
    screen = adb.screenshot(porta)
    if not screen:
        return ('sconosciuto', '')
    return (rileva_screen(screen, porta=porta, nome=nome), screen)


# ------------------------------------------------------------------------------
# Invia N BACK rapidi e legge lo stato risultante
# ------------------------------------------------------------------------------

def back_rapidi_e_stato(porta: str, n: int = N_BACK, logger=None, nome: str = '') -> tuple:
    """Invia n BACK a intervalli DELAY_BACK, poi legge lo stato."""

    def log(msg):
        if logger:
            logger(nome, msg)

    for _ in range(n):
        adb.keyevent(porta, 'KEYCODE_BACK')
        time.sleep(DELAY_BACK)

    time.sleep(DELAY_POST_BACK)
    s, screen = rileva(porta, nome=nome)

    if s == 'overlay':
        adb.keyevent(porta, 'KEYCODE_BACK')
        time.sleep(0.8)
        s2, screen2 = rileva(porta, nome=nome)
        if s2 in ('home', 'mappa'):
            s, screen = s2, screen2

    log(f"Stato dopo {n} BACK: {s}")
    return (s, screen)


def _pulisci_overlay(porta: str, nome: str, logger=None) -> str:
    """Cicli di BACK finché stato è home o mappa."""

    def log(msg):
        if logger:
            logger(nome, msg)

    for ciclo in range(MAX_CICLI_BACK):
        s, _ = back_rapidi_e_stato(porta, N_BACK, logger, nome)
        if s in ('home', 'mappa'):
            return s
        log(f"Overlay persistente (ciclo {ciclo+1}/{MAX_CICLI_BACK}) - altro ciclo BACK")

    log(f"Impossibile uscire da overlay dopo {MAX_CICLI_BACK} cicli")
    return 'fallito'


def vai_in_mappa(porta: str, nome: str, logger=None) -> bool:
    """Porta l'istanza in mappa. Prima pulisce overlay, poi naviga."""

    def log(msg):
        if logger:
            logger(nome, msg)

    s, _ = rileva(porta, nome=nome)
    log(f"Stato attuale: {s}")

    if s not in ('home', 'mappa'):
        s = _pulisci_overlay(porta, nome, logger)
        if s == 'fallito':
            log('Impossibile raggiungere stato pulito - abbandono')
            return False

    if s == 'mappa':
        log('Già in mappa')
        time.sleep(1.5)
        return True

    delays_post_tap = [3.0, 4.0, 5.0]

    for tentativo in range(MAX_TENTATIVI_MAPPA):
        delay = delays_post_tap[min(tentativo, len(delays_post_tap) - 1)]
        label = 'primo' if tentativo == 0 else f"tentativo {tentativo+1}"
        log(f"Tap mappa ({label}, attesa {delay:.0f}s)...")
        adb.tap(porta, getattr(config, 'TAP_TOGGLE_HOME_MAPPA', (38, 505)), delay_ms=0)
        time.sleep(delay)
        s_dopo, _ = rileva(porta, nome=nome)
        log(f"Stato dopo tap: {s_dopo}")

        if s_dopo == 'mappa':
            time.sleep(1.5)
            return True

        if s_dopo not in ('home', 'mappa'):
            log(f"Overlay '{s_dopo}' dopo tap - pulisco")
            s_dopo = _pulisci_overlay(porta, nome, logger)
            if s_dopo == 'fallito':
                log('Overlay persistente dopo tap - abbandono')
                return False
            if s_dopo == 'mappa':
                time.sleep(1.5)
                return True

        if tentativo < MAX_TENTATIVI_MAPPA - 1:
            log(f"Ancora in home - riprovo (tentativo {tentativo+2}/{MAX_TENTATIVI_MAPPA})")

    log(f"Impossibile raggiungere mappa dopo {MAX_TENTATIVI_MAPPA} tap - abbandono")
    return False


def vai_in_home(porta: str, nome: str, logger=None, conferme: int = 3) -> bool:
    """Porta l'istanza in home. Pulisce overlay e verifica N conferme consecutive."""

    def log(msg):
        if logger:
            logger(nome, msg)

    s, _ = rileva(porta, nome=nome)
    log(f"Stato attuale: {s}")

    if s not in ('home', 'mappa'):
        s = _pulisci_overlay(porta, nome, logger)
        if s == 'fallito':
            log('Impossibile uscire da overlay')
            return False

    if s != 'home':
        if s == 'mappa':
            adb.tap(porta, getattr(config, 'TAP_TOGGLE_HOME_MAPPA', (38, 505)), delay_ms=0)
            time.sleep(3.0)
        else:
            adb.keyevent(porta, 'KEYCODE_BACK')
            time.sleep(2.0)

    consecutive = 0
    for _ in range(conferme * 4):
        s, _ = rileva(porta, nome=nome)
        if s == 'home':
            consecutive += 1
            if consecutive >= conferme:
                log(f"In home confermato ({conferme}x)")
                return True
            time.sleep(0.5)
        elif s in ('mappa',):
            consecutive = 0
            log(f"Stato {s} - toggle verso home")
            adb.tap(porta, getattr(config, 'TAP_TOGGLE_HOME_MAPPA', (38, 505)), delay_ms=0)
            time.sleep(3.0)
        else:
            consecutive = 0
            log(f"Overlay '{s}' - pulisco")
            s = _pulisci_overlay(porta, nome, logger)
            if s == 'fallito':
                log('Overlay persistente - abbandono')
                return False

    log('Impossibile confermare home')
    return False


def conta_squadre(porta: str, n_letture: int = 3) -> tuple:
    """Legge contatore squadre X/Y via OCR. Valore più frequente, fallback (-1,-1,-1)."""
    import ocr
    risultati = []
    for _ in range(n_letture):
        screen = adb.screenshot(porta)
        if not screen:
            continue
        crop = adb.crop_zona(screen, config.OCR_ZONA)
        if not crop:
            continue
        attive, totale = ocr.leggi_contatore(crop)
        if attive != -1:
            risultati.append((attive, totale))
        time.sleep(0.3)

    if not risultati:
        return (-1, -1, -1)

    from collections import Counter
    piu_comune = Counter(risultati).most_common(1)[0][0]
    attive, totale = piu_comune
    libere = max(0, totale - attive)
    return (attive, totale, libere)
