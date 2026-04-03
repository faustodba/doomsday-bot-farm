"""
scan.py
Rileva i pin sulla mappa e genera detections.json + crop 64×64.

Migliorie (Mar 2026):
- Nomi crop deterministici (cx,cy,tipo,template) per stabilità dataset.
"""

import cv2
import json
import argparse
import sys
import re
from pathlib import Path

HERE = Path(__file__).parent
TEMPLATES_DIR = HERE / "templates"
DATASET_DIR = HERE / "dataset"


def _safe_token(s: str) -> str:
    s = (s or "").strip().replace(" ", "_")
    s = re.sub(r"[^0-9A-Za-z_\-]+", "", s)
    return s or "x"


def _crop_filename(m: dict) -> str:
    cx = int(m.get("cx", 0))
    cy = int(m.get("cy", 0))
    tipo = _safe_token(m.get("tipo", ""))
    tmpl = _safe_token(m.get("template", ""))
    return f"crop_{cx:04d}_{cy:04d}_{tipo}_{tmpl}.png"


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan mappa radar")
    parser.add_argument("map_path", help="Percorso mappa PNG")
    parser.add_argument("--threshold", "-t", type=float, default=0.65)
    parser.add_argument("--debug", "-d", action="store_true", help="Salva immagine con bbox disegnati")
    parser.add_argument("--out", default="detections.json")
    args = parser.parse_args()

    from detector import load_templates, detect, extract_crop, draw_debug

    map_img = cv2.imread(args.map_path)
    if map_img is None:
        print(f"ERRORE: impossibile aprire {args.map_path}")
        sys.exit(1)

    templates = load_templates(TEMPLATES_DIR)
    if not templates:
        print(f"ERRORE: nessun template in {TEMPLATES_DIR}/")
        print("  Lancia prima: python template_builder.py <mappa>")
        sys.exit(1)

    print(f"Template caricati : {len(templates)}")
    matches = detect(map_img, templates, threshold=args.threshold)
    print(f"Pin rilevati      : {len(matches)}")

    crops_dir = DATASET_DIR / "crops"
    crops_dir.mkdir(parents=True, exist_ok=True)

    for m in matches:
        cf = _crop_filename(m)
        m["crop_file"] = cf
        crop = extract_crop(map_img, m["cx"], m["cy"], 64)
        cv2.imwrite(str(crops_dir / cf), crop)

    print(f"\n{'N':>2} {'cx':>4} {'cy':>4} {'conf':>5} tipo")
    print("─" * 42)
    for i, m in enumerate(sorted(matches, key=lambda x: x["cy"]), 1):
        print(f"{i:2d} {m['cx']:4d} {m['cy']:4d} {m['conf']:.3f} {m['tipo']}")

    out_data = [{k: v for k, v in m.items() if k not in ("x", "y")} for m in matches]
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out_data, f, indent=2)

    print(f"\nDetections → {args.out}")
    print(f"Crop       → {crops_dir}/")

    if args.debug:
        debug_img = draw_debug(map_img, matches)
        debug_path = Path(args.map_path).with_name(Path(args.map_path).stem + "_detected.png")
        cv2.imwrite(str(debug_path), debug_img)
        print(f"Debug img  → {debug_path}")


if __name__ == "__main__":
    main()
