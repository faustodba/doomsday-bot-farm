"""
detector.py
Rileva icone/pin sulla mappa tramite template matching multi-template + NMS.
"""

import cv2
import numpy as np
from pathlib import Path

ROI          = (75, 115, 870, 485)   # x1,y1,x2,y2 zona mappa (esclude UI bordi)
THRESHOLD    = 0.65
NMS_DIST     = 30
CROP_SIZE    = 64


def load_templates(templates_dir: Path) -> list[dict]:
    templates = []
    for p in sorted(templates_dir.glob("*.png")):
        img = cv2.imread(str(p))
        if img is None:
            continue
        parts = p.stem.split("_", 1)
        tipo  = parts[1] if len(parts) > 1 else p.stem
        templates.append({"name": p.stem, "tipo": tipo,
                          "img": img, "h": img.shape[0], "w": img.shape[1]})
    return templates


def detect(map_img: np.ndarray, templates: list[dict],
           threshold: float = THRESHOLD) -> list[dict]:
    roi_x1, roi_y1, roi_x2, roi_y2 = ROI
    all_matches = []
    for t in templates:
        result = cv2.matchTemplate(map_img, t["img"], cv2.TM_CCOEFF_NORMED)
        locs   = np.where(result >= threshold)
        for py, px in zip(locs[0], locs[1]):
            cx, cy = px + t["w"] // 2, py + t["h"] // 2
            if not (roi_x1 < cx < roi_x2 and roi_y1 < cy < roi_y2):
                continue
            all_matches.append({
                "cx": int(cx), "cy": int(cy),
                "x":  int(px), "y":  int(py),
                "w":  int(t["w"]), "h": int(t["h"]),
                "conf":     float(result[py, px]),
                "template": t["name"],
                "tipo":     t["tipo"],
            })
    return _nms(all_matches, NMS_DIST)


def _nms(matches: list[dict], dist: int) -> list[dict]:
    if not matches:
        return []
    ms = sorted(matches, key=lambda m: -m["conf"])
    kept, suppressed = [], set()
    for i, m in enumerate(ms):
        if i in suppressed:
            continue
        kept.append(m)
        for j, q in enumerate(ms):
            if j <= i or j in suppressed:
                continue
            if abs(m["cx"] - q["cx"]) < dist and abs(m["cy"] - q["cy"]) < dist:
                suppressed.add(j)
    return kept


def extract_crop(map_img: np.ndarray, cx: int, cy: int,
                 size: int = CROP_SIZE) -> np.ndarray:
    half = size // 2
    h, w = map_img.shape[:2]
    x1, y1 = max(0, cx - half), max(0, cy - half)
    x2, y2 = min(w, cx + half), min(h, cy + half)
    crop = map_img[y1:y2, x1:x2]
    if crop.shape[0] != size or crop.shape[1] != size:
        out = np.zeros((size, size, 3), dtype=np.uint8)
        out[:crop.shape[0], :crop.shape[1]] = crop
        return out
    return crop


def draw_debug(map_img: np.ndarray, matches: list[dict]) -> np.ndarray:
    debug = map_img.copy()
    colors = {"viola": (255, 0, 220), "rosso": (0, 0, 220), "gold": (0, 165, 255)}
    for m in matches:
        col = next((v for k, v in colors.items() if k in m["tipo"]), (0, 255, 0))
        cv2.rectangle(debug, (m["x"], m["y"]),
                      (m["x"] + m["w"], m["y"] + m["h"]), col, 2)
        cv2.circle(debug, (m["cx"], m["cy"]), 4, (255, 255, 255), -1)
        cv2.putText(debug, f"{m['tipo']} {m['conf']:.2f}",
                    (m["x"], m["y"] - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.36, col, 1, cv2.LINE_AA)
    return debug
