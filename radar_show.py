# ==============================================================================
#  DOOMSDAY BOT V5 - radar_show.py
#  Task Radar Station — raccolta ricompense dalla mappa dinamica
#
#  FLUSSO (da home):
#    1. Verifica badge rosso sull'icona Radar Station (coords.tap_radar_icona)
#       Se assente → skip immediato (nulla da raccogliere)
#    2. Tap icona → attendi apertura mappa (2.5s) + notifiche (10s)
#    3. Loop raccolta:
#       a. Screenshot
#       b. Cerca pallini rossi (connected components numpy, filtro forma circolare)
#       c. Se trovati → tap su ognuno → attendi → ripeti scan
#       d. Se 2 scan consecutivi vuoti → exit
#    4. BACK → torna in home
#
#  RICONOSCIMENTO PALLINI:
#    Algoritmo connected components su maschera pixel rossi (numpy puro, no scipy).
#    Filtro: compattezza > RADAR_COMP_MIN, aspect_ratio > RADAR_ASPECT_MIN,
#            dimensione RADAR_W/H_MIN..MAX, pixel minimi RADAR_PX_MIN.
#    Calibrato su dataset 9 screen reali (FAU_00..FAU_09).
#
#  PATTERN ARCHITETTURALE:
#    - coords.tap_radar_icona : coordinata icona (da UICoords, fallback config)
#    - config.RADAR_*         : tutti i parametri algoritmo (sezione 5)
#    - Schedulazione          : daily_tasks.py task "radar", intervallo 12h
#    - Flag abilitazione      : config.DAILY_RADAR_ABILITATO (runtime.json)
# ==============================================================================

import time
import numpy as np
from PIL import Image

import adb
import config


# ------------------------------------------------------------------------------
# Connected components con numpy puro (senza scipy)
# Implementazione BFS su maschera booleana 2D.
# ------------------------------------------------------------------------------

def _label_components(maschera: np.ndarray):
    """
    Etichetta le componenti connesse di una maschera booleana 2D.
    Connettività 4 (su/giù/sx/dx).
    Ritorna array labeled (int32) e numero di componenti.
    Equivalente a scipy.ndimage.label() senza dipendenze esterne.
    """
    h, w = maschera.shape
    labeled = np.zeros((h, w), dtype=np.int32)
    current = 0
    for y in range(h):
        for x in range(w):
            if maschera[y, x] and labeled[y, x] == 0:
                current += 1
                queue = [(y, x)]
                labeled[y, x] = current
                while queue:
                    cy, cx = queue.pop()
                    for ny, nx in ((cy-1,cx),(cy+1,cx),(cy,cx-1),(cy,cx+1)):
                        if 0 <= ny < h and 0 <= nx < w:
                            if maschera[ny, nx] and labeled[ny, nx] == 0:
                                labeled[ny, nx] = current
                                queue.append((ny, nx))
    return labeled, current


# ------------------------------------------------------------------------------
# Rilevamento badge rosso sull'icona in home
# ------------------------------------------------------------------------------

def _ha_badge_radar(screen_path: str, tap_icona: tuple) -> bool:
    """
    Controlla se l'icona Radar Station ha il badge rosso attivo.
    Cerca pixel rossi in un'area estesa attorno a tap_icona.
    Ritorna True se badge presente, False altrimenti.
    Fail-safe: True in caso di errore (meglio tentare che saltare).
    """
    try:
        img = Image.open(screen_path)
        arr = np.array(img)
        cx, cy = tap_icona
        # Area estesa attorno all'icona — calibrata su screenshot reali 960x540
        # Il badge si trova a destra e leggermente sotto il centro icona
        zona = arr[cy-25:cy+20, cx-10:cx+35, :3]
        r = zona[:,:,0].astype(int)
        g = zona[:,:,1].astype(int)
        b = zona[:,:,2].astype(int)
        rossi = ((r > config.RADAR_BADGE_R_MIN) &
                 (g < config.RADAR_BADGE_G_MAX) &
                 (b < config.RADAR_BADGE_B_MAX))
        return int(rossi.sum()) >= 5
    except Exception:
        return True  # fail-safe: meglio tentare che saltare


# ------------------------------------------------------------------------------
# Ricerca pallini rossi nella mappa
# ------------------------------------------------------------------------------

def _trova_pallini(screen_path: str) -> list:
    """
    Trova tutti i pallini rossi cliccabili nella mappa Radar Station.

    Algoritmo:
      1. Maschera pixel rossi nella zona mappa (RADAR_MAPPA_ZONA)
      2. Connected components (BFS numpy puro)
      3. Filtro per forma circolare: compattezza + aspect ratio + dimensione

    Ritorna lista di (cx, cy) coordinate assolute 960x540.
    Lista vuota se nessun pallino trovato o errore.
    """
    try:
        img = Image.open(screen_path)
        arr = np.array(img)
        x1, y1, x2, y2 = config.RADAR_MAPPA_ZONA
        zona = arr[y1:y2, x1:x2, :3]

        r = zona[:,:,0].astype(int)
        g = zona[:,:,1].astype(int)
        b = zona[:,:,2].astype(int)

        maschera = ((r > config.RADAR_BADGE_R_MIN) &
                    (g < config.RADAR_BADGE_G_MAX) &
                    (b < config.RADAR_BADGE_B_MAX))

        labeled, num = _label_components(maschera)
        pallini = []

        for i in range(1, num + 1):
            comp = np.where(labeled == i)
            ys_c, xs_c = comp
            npx = len(xs_c)
            if npx < config.RADAR_PX_MIN:
                continue

            w = int(xs_c.max() - xs_c.min() + 1)
            h = int(ys_c.max() - ys_c.min() + 1)
            if not (config.RADAR_W_MIN <= w <= config.RADAR_W_MAX):
                continue
            if not (config.RADAR_H_MIN <= h <= config.RADAR_H_MAX):
                continue

            area       = w * h
            comp_ratio = npx / area if area > 0 else 0
            aspect     = min(w, h) / max(w, h) if max(w, h) > 0 else 0

            if comp_ratio < config.RADAR_COMP_MIN:
                continue
            if aspect < config.RADAR_ASPECT_MIN:
                continue

            cx_abs = int(xs_c.mean()) + x1
            cy_abs = int(ys_c.mean()) + y1
            pallini.append((cx_abs, cy_abs))

        return pallini

    except Exception:
        return []


# ------------------------------------------------------------------------------
# Task principale Radar Show
# ------------------------------------------------------------------------------

def esegui_radar_show(porta: str, nome: str, coords=None, logger=None) -> bool:
    """
    Esegue il task Radar Station dalla home.

    Flusso:
      1. Screenshot → verifica badge sull'icona
      2. Se assente → return True (skip pulito, nulla da fare)
      3. Tap icona → attendi apertura mappa + scomparsa notifiche
      4. Loop: scan pallini → tap → scan → ... fino a 0 pallini o timeout
      5. BACK → torna in home

    Parametri:
      coords : UICoords istanza — usa coords.tap_radar_icona se disponibile
               Fallback su config.TAP_RADAR_ICONA se None

    Ritorna True se completato (anche con 0 pallini), False se errore bloccante.
    """
    def log(msg):
        if logger: logger(nome, msg)

    tap_icona = coords.tap_radar_icona if coords else config.TAP_RADAR_ICONA

    try:
        # --- Verifica badge in home ---
        screen = adb.screenshot(porta)
        if not screen:
            log("RADAR: screenshot fallito — skip")
            return False

        if not _ha_badge_radar(screen, tap_icona):
            log("RADAR: nessun badge sull'icona — skip")
            return True

        # --- Apri Radar Station ---
        log("RADAR: tap icona Radar Station")
        adb.tap(porta, tap_icona)
        time.sleep(2.5)  # attesa apertura mappa dinamica

        # Attesa extra per notifiche che scorrono all'apertura
        # 10s per coprire lag di rete e notifiche lente
        log("RADAR: attesa scomparsa notifiche...")
        time.sleep(10.0)

        # --- Loop raccolta pallini ---
        t_inizio    = time.time()
        tot_tappati = 0
        scan_vuoti  = 0

        while True:
            if time.time() - t_inizio > config.RADAR_TIMEOUT_S:
                log(f"RADAR: timeout {config.RADAR_TIMEOUT_S}s — esco")
                break

            screen = adb.screenshot(porta)
            if not screen:
                log("RADAR: screenshot fallito nel loop — esco")
                break

            pallini = _trova_pallini(screen)

            if not pallini:
                scan_vuoti += 1
                if scan_vuoti >= 2:
                    log(f"RADAR: nessun pallino per {scan_vuoti} scan consecutivi — completato")
                    break
                log(f"RADAR: nessun pallino (scan {scan_vuoti}/2) — riprovo tra {config.RADAR_SCAN_DELAY_S}s")
                time.sleep(config.RADAR_SCAN_DELAY_S)
                continue

            scan_vuoti = 0
            log(f"RADAR: trovati {len(pallini)} pallini → tap")

            for cx, cy in pallini:
                adb.tap(porta, (cx, cy))
                tot_tappati += 1
                time.sleep(config.RADAR_TAP_DELAY_S)

            time.sleep(config.RADAR_SCAN_DELAY_S)

        log(f"RADAR: completato — {tot_tappati} pallini tappati")

        # --- Chiudi e torna in home ---
        adb.keyevent(porta, "KEYCODE_BACK")
        time.sleep(1.0)
        return True

    except Exception as e:
        log(f"RADAR: errore: {e}")
        try:
            adb.keyevent(porta, "KEYCODE_BACK")
            time.sleep(0.5)
        except Exception:
            pass
        return False
