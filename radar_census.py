# ==============================================================================
#  DOOMSDAY BOT V5 - radar_census.py
#  Censimento icone mappa Radar Station
#
#  SCOPO:
#    Raccogliere campioni visivi di tutte le icone presenti nella mappa
#    Radar Station per costruire un database di training per la classificazione.
#    NON esegue azioni sul gioco — solo osservazione e salvataggio.
#
#  FLUSSO (chiamato da radar_show.py dopo il loop pallini):
#    1. Screenshot completo mappa Radar Station (salvato come map_full.png)
#    2. Trova tutte le componenti nella zona mappa tramite maschera pixel scuri
#    3. Per ogni componente: crop 80x80, pre-label v6, salva su disco
#    4. Salva JSON con metadati completi + feature spaziali per analisi ML
#
#  CLASSIFICATORE v6 (regole derivate da dataset FAU_00-FAU_05, 34 campioni):
#
#    Ordine applicazione: camion → zombie → mostro → avatar → paracadute → ignore
#
#    CAMION     : w≤28 AND h≤22 AND sat<52  AND 1.25≤R/G<1.36 AND lum>100
#    ZOMBIE     : w≤28 AND h≤20 AND sat≥50  AND R/G≥1.38 AND R≥120
#                 (solo casi certi piccoli — zombie grandi ancora ambigui con avatar)
#    MOSTRO     : R≥153 AND lum≥118 AND R/G≥1.30 AND h≤35
#    AVATAR     : h≥24 AND R/G<1.36 AND w≤56  (non se sat<42 AND R/G<1.20 AND h≤38)
#    PARACADUTE : sat<50 AND R/G<1.22 AND w≥28 AND lum≥100 AND h≤40
#    SCONOSCIUTO: tutto il resto
#
#  FEATURE SPAZIALI (v2 — per training ML secondo giro):
#    g_top_ratio   : G_media(metà sup) / G_media(intera)  → zombie verde in alto
#    r_top_ratio   : R_media(metà sup) / R_media(intera)   → mostri rossi in alto
#    hue_dominante : angolo hue HSV dominante (gradi)      → verde=120, rosso=0/360
#    edge_density  : densità bordi Sobel normalizzata      → icone > foto
#
#  OUTPUT:
#    debug/radar_census/YYYYMMDD_HHMMSS_{nome}/
#      map_full.png                           — screenshot completo mappa
#      NNN_{pre_label}_cx{x}_cy{y}.png        — crop 80x80 per ogni oggetto
#      census.json                            — metadati + feature spaziali
#
#  ABILITAZIONE:
#    config.RADAR_CENSUS_ABILITATO = True  (default False)
#
#  NOTE PROBLEMI APERTI (da risolvere con dataset FAU_06-09 + ML):
#    - zombie grandi (w>28 OR h>20) non separabili da avatar con sole feature RGB
#    - camion (1 solo campione finora) — regola provvisoria
#    - secondo giro: Random Forest con scikit-learn su feature spaziali
# ==============================================================================

import os
import json
import shutil
from datetime import datetime
from collections import deque

import numpy as np
from PIL import Image

import adb
import config

# ------------------------------------------------------------------------------
# Parametri zona mappa (stessa di radar_show.py)
# Esclude: barra titolo (y<60), pannello dx LV/Complete (x>860)
# ------------------------------------------------------------------------------
ZONA_MAPPA = (0, 60, 860, 530)

# Dimensione half-crop salvato per ogni oggetto → crop finale 80x80
CROP_HW = 40

# Filtri dimensione componente
NPX_MIN = 40      # pixel minimi nella maschera scura
W_MIN   = 18      # larghezza minima bounding box
H_MIN   = 18      # altezza minima
W_MAX   = 140     # larghezza massima
H_MAX   = 140     # altezza massima
AR_MAX  = 3.0     # aspect ratio massimo (oltre = linea/rumore)

# Soglia luminosità per maschera pixel scuri (bordi oggetti)
LUM_SOGLIA = 60

# Soglia pallino rosso (esclusi dal censimento — già gestiti da radar_show.py)
PALLINO_R_MIN  = 150
PALLINO_G_MAX  = 80
PALLINO_B_MAX  = 80
PALLINO_PX_MIN = 8


# ------------------------------------------------------------------------------
# Connected components BFS numpy puro (stessa impl di radar_show.py)
# ------------------------------------------------------------------------------
def _label_components(maschera: np.ndarray):
    h, w = maschera.shape
    labeled = np.zeros((h, w), dtype=np.int32)
    current = 0
    for y in range(h):
        for x in range(w):
            if maschera[y, x] and labeled[y, x] == 0:
                current += 1
                q = deque([(y, x)])
                labeled[y, x] = current
                while q:
                    cy, cx = q.popleft()
                    for ny, nx in ((cy-1,cx),(cy+1,cx),(cy,cx-1),(cy,cx+1)):
                        if 0<=ny<h and 0<=nx<w and maschera[ny,nx] and labeled[ny,nx]==0:
                            labeled[ny,nx] = current
                            q.append((ny, nx))
    return labeled, current


# ------------------------------------------------------------------------------
# Feature spaziali (calcolate sul crop 80x80, solo numpy)
# ------------------------------------------------------------------------------
def _calcola_feature_spaziali(crop: np.ndarray) -> dict:
    """
    Calcola feature spaziali aggiuntive sul crop 80x80.
    Richiede solo numpy — nessuna dipendenza esterna.

    g_top_ratio:
      G_media(metà superiore) / G_media(intera)
      > 1.1 → verde concentrato in alto (zombie: soldatino verde in cima al pin)
      ~ 1.0 → distribuzione uniforme (avatar: foto intera)

    r_top_ratio:
      R_media(metà superiore) / R_media(intera)
      Analogo per il canale rosso.

    hue_dominante:
      Angolo hue HSV dominante in gradi (0-360).
      0/360=rosso, 60=giallo, 120=verde, 240=blu.
      Zombie: atteso ~90-120 (verde soldatino)
      Mostro: atteso ~0-30 (rosso teschio)
      Avatar: distribuito (dipende dalla foto)

    edge_density:
      Densità bordi approssimata via differenze finite (Sobel semplificato).
      0.0-1.0 normalizzato su 255.
      Alto → icona stilizzata con contorni netti
      Basso → foto realistica con gradienti morbidi
    """
    if crop.size == 0:
        return {"g_top_ratio": 1.0, "r_top_ratio": 1.0,
                "hue_dominante": 0.0, "edge_density": 0.0}

    arr  = crop.astype(float)
    h, w = arr.shape[:2]
    mid  = h // 2

    r = arr[:,:,0]; g = arr[:,:,1]; b = arr[:,:,2]

    # g_top_ratio e r_top_ratio
    g_mean = float(g.mean()) or 1.0
    r_mean = float(r.mean()) or 1.0
    g_top_ratio = float(arr[:mid,:,1].mean()) / g_mean
    r_top_ratio = float(arr[:mid,:,0].mean()) / r_mean

    # hue_dominante
    try:
        r_n = r / 255.0; g_n = g / 255.0; b_n = b / 255.0
        cmax  = np.maximum(np.maximum(r_n, g_n), b_n)
        cmin  = np.minimum(np.minimum(r_n, g_n), b_n)
        delta = cmax - cmin + 1e-8

        hue = np.zeros_like(cmax)
        mr  = (cmax == r_n) & (delta > 1e-7)
        mg  = (cmax == g_n) & (delta > 1e-7)
        mb  = (cmax == b_n) & (delta > 1e-7)
        hue[mr] = (60 * ((g_n[mr] - b_n[mr]) / delta[mr])) % 360
        hue[mg] = (60 * ((b_n[mg] - r_n[mg]) / delta[mg]) + 120) % 360
        hue[mb] = (60 * ((r_n[mb] - g_n[mb]) / delta[mb]) + 240) % 360

        bins    = np.histogram(hue.flatten(), bins=12, range=(0, 360))[0]
        hue_dom = float(np.argmax(bins) * 30 + 15)
    except Exception:
        hue_dom = 0.0

    # edge_density via differenze finite (Sobel approssimato)
    try:
        gray  = 0.299*r + 0.587*g + 0.114*b
        gx    = np.abs(gray[:, 2:] - gray[:, :-2])
        gy    = np.abs(gray[2:, :] - gray[:-2, :])
        edge  = (gx[1:-1, :] + gy[:, 1:-1]) / 2.0
        edge_density = float(edge.mean()) / 255.0
    except Exception:
        edge_density = 0.0

    return {
        "g_top_ratio":   round(g_top_ratio,  3),
        "r_top_ratio":   round(r_top_ratio,  3),
        "hue_dominante": round(hue_dom,      1),
        "edge_density":  round(edge_density, 4),
    }


# ------------------------------------------------------------------------------
# Classificatore v6
# ------------------------------------------------------------------------------
def _classifica_v6(w: int, h: int, sat: float, r: float, g: float,
                   b: float, lum: float) -> tuple:
    """
    Classifica l'oggetto in base a feature aggregate (R,G,B,sat,lum,w,h).
    Regole derivate da dataset FAU_00-FAU_05 (34 campioni verificati manualmente).
    Ritorna (label, confidenza 0.0-1.0).

    Labels: camion | zombie | mostro | avatar | paracadute | sconosciuto
    """
    rg = r / g if g > 0 else 0.0

    # CAMION — icona veicolo, piccolo, R/G specifico
    if w <= 28 and h <= 22 and sat < 52 and 1.25 <= rg < 1.36 and lum > 100:
        return ("camion", 0.7)

    # ZOMBIE — soldatino verde su pin, solo casi piccoli certi
    # Zombie grandi (w>28 OR h>20) ambigui con avatar → classificati avatar
    if w <= 28 and h <= 20 and sat >= 50 and rg >= 1.38 and r >= 120:
        return ("zombie", 0.9)

    # MOSTRO — teschio su rombo/esagono rosso
    if r >= 153 and lum >= 118 and rg >= 1.30 and h <= 35:
        return ("mostro", 0.85)

    # AVATAR — ritratto giocatore
    # Esclude paracadute (sat bassa + R/G basso + h basso)
    if h >= 24 and rg < 1.36 and w <= 56:
        if not (sat < 42 and rg < 1.20 and h <= 38):
            return ("avatar", 0.8)

    # PARACADUTE — pin evento/rifornimento verde
    if sat < 50 and rg < 1.22 and w >= 28 and lum >= 100 and h <= 40:
        return ("paracadute", 0.75)

    return ("sconosciuto", 0.0)


# ------------------------------------------------------------------------------
# Trova oggetti nella zona mappa
# ------------------------------------------------------------------------------
def _trova_oggetti(screen_path: str) -> list:
    """
    Trova tutte le componenti nella zona mappa tramite maschera pixel scuri.
    Esclude automaticamente i pallini rossi (già gestiti da radar_show.py).
    Ritorna lista di dict con coordinate, dimensioni, crop numpy e feature.
    """
    try:
        img = Image.open(screen_path)
        arr = np.array(img)
        x1, y1, x2, y2 = ZONA_MAPPA
        zona = arr[y1:y2, x1:x2, :3]

        lum_zona = zona.mean(axis=2)
        maschera = lum_zona < LUM_SOGLIA

        labeled, n_comp = _label_components(maschera)

        oggetti = []
        for i in range(1, n_comp + 1):
            ys, xs = np.where(labeled == i)
            npx = len(xs)
            if npx < NPX_MIN:
                continue

            bb_w = int(xs.max() - xs.min() + 1)
            bb_h = int(ys.max() - ys.min() + 1)

            if bb_w < W_MIN or bb_h < H_MIN:
                continue
            if bb_w > W_MAX or bb_h > H_MAX:
                continue
            if bb_w / bb_h > AR_MAX or bb_h / bb_w > AR_MAX:
                continue

            cx_abs = int(xs.mean()) + x1
            cy_abs = int(ys.mean()) + y1

            # Crop 80x80 centrato sull'oggetto
            cx1c = max(0, cx_abs - CROP_HW)
            cy1c = max(0, cy_abs - CROP_HW)
            cx2c = min(arr.shape[1], cx_abs + CROP_HW)
            cy2c = min(arr.shape[0], cy_abs + CROP_HW)
            crop = arr[cy1c:cy2c, cx1c:cx2c, :3]

            # Escludi pallini rossi puri (piccoli e rosso dominante)
            if crop.size > 0 and bb_w <= 25 and bb_h <= 25:
                cr = crop[:,:,0].astype(float)
                cg = crop[:,:,1].astype(float)
                cb = crop[:,:,2].astype(float)
                rossi = ((cr > PALLINO_R_MIN) & (cg < PALLINO_G_MAX) & (cb < PALLINO_B_MAX))
                if int(rossi.sum()) >= PALLINO_PX_MIN:
                    continue

            # Feature aggregate
            crop_f   = crop.astype(float)
            varianza = float(crop.std())
            lum_med  = float(crop_f.mean())
            r_med    = float(crop_f[:,:,0].mean())
            g_med    = float(crop_f[:,:,1].mean())
            b_med    = float(crop_f[:,:,2].mean())
            sat      = float((
                np.maximum(np.maximum(crop_f[:,:,0], crop_f[:,:,1]), crop_f[:,:,2]) -
                np.minimum(np.minimum(crop_f[:,:,0], crop_f[:,:,1]), crop_f[:,:,2])
            ).mean())

            # Feature spaziali
            feat_spaz = _calcola_feature_spaziali(crop)

            # Classificazione v6
            label, conf = _classifica_v6(bb_w, bb_h, sat, r_med, g_med, b_med, lum_med)

            oggetti.append({
                "cx": cx_abs, "cy": cy_abs,
                "w": bb_w, "h": bb_h,
                "npx_scuri":   npx,
                "varianza":    round(varianza, 1),
                "lum_media":   round(lum_med,  1),
                "r_med":       round(r_med,    1),
                "g_med":       round(g_med,    1),
                "b_med":       round(b_med,    1),
                "saturazione": round(sat,      1),
                # Feature spaziali per secondo giro ML
                "g_top_ratio":   feat_spaz["g_top_ratio"],
                "r_top_ratio":   feat_spaz["r_top_ratio"],
                "hue_dominante": feat_spaz["hue_dominante"],
                "edge_density":  feat_spaz["edge_density"],
                # Classificazione
                "pre_label":  label,
                "confidenza": conf,
                "crop":       crop,
            })

        return oggetti

    except Exception as e:
        print(f"[CENSUS] Errore trova_oggetti: {e}")
        return []


# ------------------------------------------------------------------------------
# Entry point principale
# ------------------------------------------------------------------------------
def esegui_censimento(porta: str, nome: str, logger=None) -> int:
    """
    Esegue il censimento della mappa Radar Station attualmente aperta.
    Deve essere chiamato mentre la mappa Radar è visibile sullo schermo.

    Salva nella cartella debug/radar_census/YYYYMMDD_HHMMSS_{nome}/:
      - map_full.png          : screenshot completo della mappa
      - NNN_label_cxX_cyY.png : crop 80x80 per ogni oggetto trovato
      - census.json           : metadati completi + feature spaziali

    Ritorna il numero di oggetti salvati (0 se censimento disabilitato).
    """
    def log(msg):
        if logger: logger(nome, msg)

    if not getattr(config, "RADAR_CENSUS_ABILITATO", False):
        return 0

    log("[CENSUS] Avvio censimento icone mappa radar")

    # Screenshot mappa corrente
    screen = adb.screenshot(porta)
    if not screen:
        log("[CENSUS] Screenshot fallito — skip censimento")
        return 0

    # Trova oggetti
    oggetti = _trova_oggetti(screen)
    if not oggetti:
        log("[CENSUS] Nessun oggetto trovato")
        return 0

    log(f"[CENSUS] Trovati {len(oggetti)} oggetti — salvo in debug/radar_census/")

    # Crea cartella output
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    cartella = os.path.join(
        getattr(config, "BOT_DIR", "."),
        "debug", "radar_census",
        f"{ts}_{nome}"
    )
    os.makedirs(cartella, exist_ok=True)

    # Salva screenshot completo mappa
    try:
        shutil.copy2(screen, os.path.join(cartella, "map_full.png"))
        log("[CENSUS] Screenshot mappa salvato: map_full.png")
    except Exception as e:
        log(f"[CENSUS] Avviso: impossibile salvare map_full.png: {e}")

    # Salva crop + metadati
    metadati = []
    for idx, obj in enumerate(oggetti):
        crop = obj.pop("crop")

        fname = f"{idx:03d}_{obj['pre_label']}_cx{obj['cx']}_cy{obj['cy']}.png"
        fpath = os.path.join(cartella, fname)
        try:
            Image.fromarray(crop.astype(np.uint8)).save(fpath)
        except Exception as e:
            log(f"[CENSUS] Errore salvataggio {fname}: {e}")
            continue

        obj["file"]      = fname
        obj["porta"]     = int(porta) if str(porta).isdigit() else porta
        obj["nome"]      = nome
        obj["timestamp"] = ts
        metadati.append(obj)

        log(
            f"[CENSUS]   {fname}"
            f"  var={obj['varianza']}"
            f"  sat={obj['saturazione']}"
            f"  conf={obj['confidenza']}"
            f"  hue={obj['hue_dominante']}"
            f"  edge={obj['edge_density']}"
        )

    # Salva JSON metadati
    json_path = os.path.join(cartella, "census.json")
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(metadati, f, ensure_ascii=False, indent=2)
        log(f"[CENSUS] Metadati salvati: {json_path}")
    except Exception as e:
        log(f"[CENSUS] Errore salvataggio JSON: {e}")

    log(f"[CENSUS] Completato — {len(metadati)} oggetti salvati in {cartella}")
    return len(metadati)
