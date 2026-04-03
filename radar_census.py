# ==============================================================================
# DOOMSDAY BOT V5 - radar_census.py
# Radar Census (TRAINING):
# - Detection = stesso motore di radar_tool (template matching + NMS)
# - Catalogazione = label ufficiali (come labeler.py) + confidenza + flag ready
# - Output PERSISTENTE in radar_archive (non viene cancellato ai restart)
#
# Richiede:
# - radar_tool/templates/  (template .png)
# Opzionale:
# - radar_tool/dataset/classifier.pkl  (RandomForest addestrato da train.py)
#
# Output (PERSISTENTE):
# BOT_DIR/radar_archive/census/YYYYMMDD_HHMMSS_{nome}/
#   map_full.png
#   map_annotated.png
#   crops/...
#   census.json
# ==============================================================================

import os
import json
import shutil
from datetime import datetime
import re

import cv2

import adb
import config


# ------------------------------------------------------------------------------
# Label ufficiali (allineate a radar_tool/labeler.py)
# ------------------------------------------------------------------------------
OFFICIAL_LABELS = {
    "pedone", "auto", "camion", "skull",
    "avatar", "numero", "card", "paracadute",
    "fiamma", "bottiglia", "soldati", "sconosciuto"
}

# Whitelist: categorie che consideriamo "agganciabili" ai processi.
# Per ora ampia (azione fittizia), poi potrai restringere.
ACTION_LABELS = {
    "pedone", "auto", "camion", "skull",
    "avatar", "numero", "card", "paracadute",
    "fiamma", "bottiglia", "soldati"
}


# ------------------------------------------------------------------------------
# Path interni
# ------------------------------------------------------------------------------
BOT_DIR = getattr(config, "BOT_DIR", ".")
RADAR_TOOL_DIR = os.path.join(BOT_DIR, "radar_tool")
TEMPLATES_DIR = os.path.join(RADAR_TOOL_DIR, "templates")
RF_MODEL_PATH = os.path.join(RADAR_TOOL_DIR, "dataset", "classifier.pkl")

# OUTPUT PERSISTENTE (NON in debug/)
ARCHIVE_ROOT = os.path.join(BOT_DIR, "radar_archive", "census")


# ------------------------------------------------------------------------------
# Soglie catalogazione
# ------------------------------------------------------------------------------
DEFAULT_THRESHOLD_TMPL = 0.65
TMPL_READY_MIN = 0.80   # template conf >= 0.80 => pronto (se mappabile)
TMPL_WARN_MIN = 0.70    # template conf >= 0.70 => candidato ma non pronto

RF_READY_MIN = 0.70     # rf_conf >= 0.70 => pronto
RF_WARN_MIN = 0.60      # rf_conf >= 0.60 => candidato ma non pronto


# ------------------------------------------------------------------------------
# Annotazione mappa
# ------------------------------------------------------------------------------
ANNOTATE_BOX = 64
FONT_SIZE = 14

# Colori per categoria — BGR (cv2)
LABEL_COLORS = {
    "pedone":      (243, 150,  33),
    "auto":        (  0, 152, 255),
    "camion":      ( 72,  85, 121),
    "skull":       ( 54,  67, 244),
    "avatar":      (  7, 193, 255),
    "numero":      (158, 158, 158),
    "card":        ( 59, 235, 255),
    "paracadute":  ( 80, 175,  76),
    "fiamma":      ( 34,  87, 255),
    "bottiglia":   (244, 169,   3),
    "soldati":     (176,  39, 156),
    "sconosciuto": (120, 120, 120),
}


def _semaforo(conf):
    """Colore semaforo basato su confidenza (0..1). Ritorna BGR per cv2."""
    if conf is None:
        return (120, 120, 120)
    try:
        c = float(conf)
    except Exception:
        return (120, 120, 120)
    if c >= RF_READY_MIN:
        return (80, 175, 76)    # verde  BGR
    if c >= RF_WARN_MIN:
        return (7, 193, 255)    # giallo BGR
    return (54, 67, 244)        # rosso  BGR


def _safe_token(s):
    s = (s or "").strip().replace(" ", "_")
    s = re.sub(r"[^0-9A-Za-z_\-]+", "", s)
    return s or "x"


# ------------------------------------------------------------------------------
# Import motore radar_tool (detector + classifier)
# ------------------------------------------------------------------------------
def _carica_detector(logger=None, nome=""):
    def log(msg):
        if logger:
            logger(nome, msg)
    try:
        from radar_tool.detector import load_templates, detect, extract_crop
        return load_templates, detect, extract_crop
    except Exception as e:
        log(f"[CENSUS] ERRORE import radar_tool.detector: {e}")
        return None, None, None


def _carica_rf(logger=None, nome=""):
    def log(msg):
        if logger:
            logger(nome, msg)
    try:
        from radar_tool.classifier import Classifier
    except Exception as e:
        log(f"[CENSUS] RF: modulo radar_tool.classifier non disponibile: {e}")
        return None

    if not os.path.exists(RF_MODEL_PATH):
        log(f"[CENSUS] RF: modello non trovato (opzionale): {RF_MODEL_PATH}")
        return None

    try:
        clf = Classifier()
        clf.load(RF_MODEL_PATH)
        if getattr(clf, "trained", False):
            log("[CENSUS] RF: modello caricato")
        else:
            log("[CENSUS] RF: modello caricato ma non risulta trained")
        return clf
    except Exception as e:
        log(f"[CENSUS] RF: errore caricamento modello: {e}")
        return None


# ------------------------------------------------------------------------------
# Mapping template/tipo -> categoria ufficiale (fallback quando RF non c'è o è incerto)
# ------------------------------------------------------------------------------
def _categoria_da_template(template_name, tipo):
    """Heuristica robusta: normalizza verso OFFICIAL_LABELS."""
    s = f"{template_name or ''} {tipo or ''}".lower()

    if "skull" in s:
        return "skull"
    if "sold" in s or "troop" in s:
        return "soldati"
    if "ped" in s or "pawn" in s:
        return "pedone"
    if "camion" in s or "truck" in s:
        return "camion"
    if "auto" in s or ("car" in s and "card" not in s):
        return "auto"
    if "para" in s or "parach" in s:
        return "paracadute"
    if "card" in s:
        return "card"
    if "bott" in s or "bottle" in s:
        return "bottiglia"
    if "fiam" in s or "flame" in s or "fire" in s:
        return "fiamma"
    if "num" in s or "digit" in s:
        return "numero"
    if "avatar" in s or re.search(r"\bav\d+\b", s):
        return "avatar"

    return "sconosciuto"


# ------------------------------------------------------------------------------
# Catalogazione finale (pronta per processi)
# ------------------------------------------------------------------------------
def _catalogo_finale(rec):
    """Ritorna: categoria, categoria_source, categoria_conf, ready, reason."""
    rf_label = rec.get("rf_label")
    rf_conf = rec.get("rf_conf")
    conf_tmpl = rec.get("conf_tmpl")
    tmpl = rec.get("template")
    tipo = rec.get("tipo")

    if rf_label in OFFICIAL_LABELS and rf_conf is not None:
        if rf_conf >= RF_READY_MIN:
            cat = rf_label
            src = "rf"
            cconf = float(rf_conf)
            ready = cat in ACTION_LABELS
            reason = "" if ready else "not_in_action_labels"
            return cat, src, round(cconf, 3), ready, reason
        if rf_conf >= RF_WARN_MIN:
            cat = rf_label
            src = "rf_low"
            cconf = float(rf_conf)
            return cat, src, round(cconf, 3), False, "low_conf"

    cat_t = _categoria_da_template(tmpl, tipo)
    if cat_t != "sconosciuto" and conf_tmpl is not None:
        if conf_tmpl >= TMPL_READY_MIN:
            ready = cat_t in ACTION_LABELS
            reason = "" if ready else "not_in_action_labels"
            return cat_t, "template", round(float(conf_tmpl), 3), ready, reason
        if conf_tmpl >= TMPL_WARN_MIN:
            return cat_t, "template_low", round(float(conf_tmpl), 3), False, "low_conf"

    return "sconosciuto", "none", 0.0, False, "unknown"


# ------------------------------------------------------------------------------
# Annotazione mappa
# ------------------------------------------------------------------------------
def _annota_mappa(map_full_path, out_path, records, logger=None, nome=""):
    """
    Genera map_annotated.png con bbox colorati per label + score.
    Usa cv2 puro — nessuna dipendenza da font esterni.
    Colore bbox: semaforo confidenza (verde/giallo/rosso BGR).
    Colore testo: palette LABEL_COLORS per categoria.
    """
    def log(msg):
        if logger:
            logger(nome, msg)

    try:
        img = cv2.imread(map_full_path)
        if img is None:
            log("[CENSUS] Annotazione: impossibile aprire map_full.png")
            return False

        H, W = img.shape[:2]
        font  = cv2.FONT_HERSHEY_SIMPLEX
        scale = 0.38
        thick = 1

        for r in records:
            cx   = int(r.get("cx", 0))
            cy   = int(r.get("cy", 0))
            cat  = r.get("categoria", "sconosciuto")
            cconf = r.get("categoria_conf")
            ready = bool(r.get("ready", False))

            sem_bgr = _semaforo(cconf)
            lbl_bgr = LABEL_COLORS.get(cat, (120, 120, 120))

            x1 = max(0, cx - ANNOTATE_BOX // 2)
            y1 = max(0, cy - ANNOTATE_BOX // 2)
            x2 = min(W - 1, x1 + ANNOTATE_BOX)
            y2 = min(H - 1, y1 + ANNOTATE_BOX)

            # Bbox + punto centrale
            cv2.rectangle(img, (x1, y1), (x2, y2), sem_bgr, 2)
            cv2.circle(img, (cx, cy), 3, (255, 255, 255), -1)

            # Testo: "categoria XX% OK/?"
            pct = int(float(cconf) * 100) if cconf is not None else 0
            tag = "OK" if ready else "??"
            txt = f"{cat} {pct}% {tag}"

            (tw, th), baseline = cv2.getTextSize(txt, font, scale, thick)
            tx = x1
            ty = max(th + baseline + 4, y1 - 2)

            # Sfondo nero testo
            cv2.rectangle(img,
                          (tx, ty - th - baseline - 2),
                          (tx + tw + 6, ty + 2),
                          (0, 0, 0), -1)
            cv2.putText(img, txt, (tx + 3, ty - baseline),
                        font, scale, lbl_bgr, thick, cv2.LINE_AA)

        cv2.imwrite(out_path, img)
        log("[CENSUS] Mappa annotata salvata: map_annotated.png")
        return True
    except Exception as e:
        log(f"[CENSUS] Annotazione: errore: {e}")
        return False


# ------------------------------------------------------------------------------
# Entry point principale
# ------------------------------------------------------------------------------
def esegui_censimento(porta, nome, logger=None):
    def log(msg):
        if logger:
            logger(nome, msg)

    if not getattr(config, "RADAR_CENSUS_ABILITATO", False):
        return 0

    if not os.path.isdir(TEMPLATES_DIR):
        log(f"[CENSUS] templates/ non trovato: {TEMPLATES_DIR}")
        return 0

    load_templates, detect, extract_crop = _carica_detector(logger, nome)
    if not load_templates or not detect or not extract_crop:
        return 0

    try:
        from pathlib import Path
        templates = load_templates(Path(TEMPLATES_DIR))
    except Exception as e:
        log(f"[CENSUS] ERRORE load_templates: {e}")
        return 0

    if not templates:
        log(f"[CENSUS] Nessun template in: {TEMPLATES_DIR}")
        return 0

    rf = _carica_rf(logger, nome)

    screen_path = adb.screenshot(porta)
    if not screen_path:
        log("[CENSUS] Screenshot fallito")
        return 0

    map_img = cv2.imread(screen_path)
    if map_img is None:
        log("[CENSUS] Impossibile leggere screenshot con cv2")
        return 0

    threshold = float(getattr(config, "RADAR_TOOL_THRESHOLD", DEFAULT_THRESHOLD_TMPL))
    matches = detect(map_img, templates, threshold=threshold)
    if not matches:
        log("[CENSUS] Nessuna icona rilevata dal detector")
        return 0

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(ARCHIVE_ROOT, f"{ts}_{nome}")
    crops_dir = os.path.join(out_dir, "crops")
    os.makedirs(crops_dir, exist_ok=True)

    # salva map_full
    try:
        shutil.copy2(screen_path, os.path.join(out_dir, "map_full.png"))
    except Exception:
        pass

    records = []
    for i, m in enumerate(sorted(matches, key=lambda x: x.get("cy", 0)), 1):
        cx = int(m.get("cx", 0))
        cy = int(m.get("cy", 0))
        tipo = str(m.get("tipo", ""))
        tmpl = str(m.get("template", ""))
        conf_tmpl = float(m.get("conf", 0.0))

        crop = extract_crop(map_img, cx, cy, 64)
        crop_name = f"crop_{cx:04d}_{cy:04d}_{_safe_token(tipo)}_{_safe_token(tmpl)}.png"
        crop_path = os.path.join(crops_dir, crop_name)
        try:
            cv2.imwrite(crop_path, crop)
        except Exception:
            pass

        rf_label, rf_conf = None, None
        if rf is not None:
            try:
                rf_label, rf_conf = rf.predict(crop)
                rf_conf = float(rf_conf)
            except Exception:
                rf_label, rf_conf = None, None

        rec = {
            "n": i,
            "cx": cx,
            "cy": cy,
            "tipo": tipo,
            "template": tmpl,
            "conf_tmpl": round(conf_tmpl, 3),
            "crop_file": os.path.join("crops", crop_name),
            "rf_label": rf_label,
            "rf_conf": round(rf_conf, 3) if rf_conf is not None else None,
            "porta": int(porta) if str(porta).isdigit() else porta,
            "nome": nome,
            "timestamp": ts,
        }

        cat, src, cconf, ready, reason = _catalogo_finale(rec)
        rec["categoria"] = cat
        rec["categoria_source"] = src
        rec["categoria_conf"] = cconf
        rec["ready"] = bool(ready)
        rec["reason"] = reason

        records.append(rec)

    # salva JSON
    json_path = os.path.join(out_dir, "census.json")
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"[CENSUS] Errore salvataggio JSON: {e}")

    # mappa annotata
    try:
        _annota_mappa(
            os.path.join(out_dir, "map_full.png"),
            os.path.join(out_dir, "map_annotated.png"),
            records,
            logger=logger,
            nome=nome,
        )
    except Exception:
        pass

    # riepilogo
    counts = {}
    ready_count = 0
    for r in records:
        k = r.get("categoria", "sconosciuto")
        counts[k] = counts.get(k, 0) + 1
        if r.get("ready"):
            ready_count += 1

    top = ", ".join(f"{k}={v}" for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:10])
    log(f"[CENSUS] Catalogazione: {top}")
    log(f"[CENSUS] Ready: {ready_count}/{len(records)}")
    log(f"[CENSUS] Output persistente: {out_dir}")

    log(f"[CENSUS] Completato — {len(records)} icone rilevate")
    return len(records)
