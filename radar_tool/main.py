"""
radar_tool — main.py
Strumento standalone per censimento e classificazione icone sulla mappa radar.

Uso rapido:
  python main.py scan map_full.png         # rileva pin → detections.json
  python main.py label map_full.png        # GUI labeling
  python main.py train                     # addestra/ri-addestra RF
  python main.py run map_full.png          # scan + classificazione completa
  python main.py add-template map_full.png # GUI per aggiungere nuovi template

Migliorie (Mar 2026):
- Nomi crop deterministici (cx,cy,tipo,template)
- Detector più veloce (ROI + peak picking + NMS migliorata) via detector.py
"""

import sys
import json
import argparse
import cv2
import re
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
DATASET_DIR = BASE_DIR / "dataset"
OUTPUT_DIR = BASE_DIR / "output"


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


def cmd_scan(map_path: str, threshold: float = 0.65, debug: bool = False, out_json: str = "detections.json") -> list[dict]:
    from detector import load_templates, detect, extract_crop, draw_debug

    print("\n── SCAN ─────────────────────────────────────────")
    print(f"Mappa:      {map_path}")
    print(f"Template:   {TEMPLATES_DIR}")
    print(f"Threshold:  {threshold}")

    map_img = cv2.imread(map_path)
    if map_img is None:
        print(f"ERRORE: impossibile aprire {map_path}")
        sys.exit(1)

    templates = load_templates(TEMPLATES_DIR)
    if not templates:
        print(f"ERRORE: nessun template in {TEMPLATES_DIR}")
        print("  Aggiungi template con: python main.py add-template <mappa>")
        sys.exit(1)

    print(f"Template caricati: {len(templates)}")
    matches = detect(map_img, templates, threshold=threshold)
    print(f"Pin rilevati:      {len(matches)}")

    crops_dir = DATASET_DIR / "crops"
    crops_dir.mkdir(parents=True, exist_ok=True)

    for m in matches:
        cf = _crop_filename(m)
        m["crop_file"] = cf
        crop = extract_crop(map_img, m["cx"], m["cy"], 64)
        cv2.imwrite(str(crops_dir / cf), crop)

    print(f"\n{'N':>2} {'cx':>4} {'cy':>4} {'conf':>5} {'tipo':<20} crop")
    print("─" * 90)
    for i, m in enumerate(sorted(matches, key=lambda x: x["cy"]), 1):
        print(f"{i:2d} {m['cx']:4d} {m['cy']:4d} {m['conf']:.3f} {m['tipo']:<20} {m['crop_file']}")

    out_data = [{k: v for k, v in m.items() if k not in ("x", "y")} for m in matches]
    out_path = Path(out_json)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out_data, f, indent=2)

    print(f"\nDetections salvate: {out_path}")

    if debug:
        debug_img = draw_debug(map_img, matches)
        debug_path = str(Path(map_path).with_suffix("")) + "_detected.png"
        cv2.imwrite(debug_path, debug_img)
        print(f"Debug image: {debug_path}")

    return matches


def cmd_label(map_path: str, detections_json: str = "detections.json") -> None:
    if not Path(detections_json).exists():
        print(f"File non trovato: {detections_json}")
        print(f"Esegui prima: python main.py scan {map_path}")
        sys.exit(1)

    print("\n── LABELER GUI ──────────────────────────────────")
    print(f"Detections: {detections_json}")
    print(f"Dataset:    {DATASET_DIR}")
    print("Apertura GUI...\n")

    from labeler import run
    run(detections_json, map_path, str(DATASET_DIR))


def cmd_train():
    labels_path = DATASET_DIR / "labels.json"
    if not labels_path.exists():
        print(f"Dataset non trovato: {labels_path}")
        print("Etichetta prima i pin con: python main.py label <mappa>")
        sys.exit(1)

    print("\n── TRAIN ────────────────────────────────────────")
    print(f"Dataset: {labels_path}")

    from classifier import Classifier, print_feature_importance

    clf = Classifier()
    metrics = clf.train(labels_path, DATASET_DIR / "crops")

    clf_path = DATASET_DIR / "classifier.pkl"
    clf.save(str(clf_path))

    print("\nRisultati:")
    print(f" Campioni : {metrics['n_samples']}")
    print(f" Classi   : {', '.join(metrics['classes'])}")
    print(f" CV acc   : {metrics['cv_acc']:.1%} ± {metrics['cv_std']:.1%}")
    if metrics.get('skipped'):
        print(f" Saltati  : {metrics['skipped']} (crop mancanti)")

    print_feature_importance(clf, top_n=8)
    print(f"\nModello salvato: {clf_path}")

    return clf


def cmd_run(map_path: str, threshold: float = 0.65, debug: bool = False):
    matches = cmd_scan(map_path, threshold=threshold, debug=debug)

    clf_path = DATASET_DIR / "classifier.pkl"
    clf = None
    if clf_path.exists():
        from classifier import Classifier
        clf = Classifier()
        clf.load(str(clf_path))
        print(f"\nClassificatore caricato: {clf.classes_}")
    else:
        print(f"\nATTENZIONE: nessun classificatore in {clf_path}")
        print(" Usa 'python main.py label + train' per addestrare il modello.")

    map_img = cv2.imread(map_path)
    crops_dir = DATASET_DIR / "crops"
    from detector import extract_crop

    results = []
    for m in matches:
        crop_path = crops_dir / m.get("crop_file", "")
        if crop_path.exists():
            crop = cv2.imread(str(crop_path))
        else:
            crop = extract_crop(map_img, m["cx"], m["cy"], 64)

        rf_label, rf_conf = (None, 0.0)
        if clf:
            rf_label, rf_conf = clf.predict(crop)

        r = {
            "cx": m["cx"],
            "cy": m["cy"],
            "tipo_tmpl": m["tipo"],
            "conf_tmpl": round(m["conf"], 3),
            "crop_file": m.get("crop_file", ""),
        }
        if clf:
            r["label_rf"] = rf_label
            r["conf_rf"] = round(rf_conf, 3)
        results.append(r)

    print("\n── RISULTATI CLASSIFICAZIONE ─────────────────────")
    for r in sorted(results, key=lambda x: x["cy"]):
        rf_str = ""
        if "label_rf" in r:
            rf_str = f" RF={r['label_rf']}({r['conf_rf']:.0%})"
        print(f" ({r['cx']:4d},{r['cy']:4d}) tmpl={r['tipo_tmpl']:<18}{rf_str}")

    OUTPUT_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = OUTPUT_DIR / f"{ts}_result.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nOutput salvato: {out}")
    return results


def cmd_add_template(map_path: str) -> None:
    print("\n── TEMPLATE BUILDER ─────────────────────────────")
    print(" Click+drag per selezionare un pin sulla mappa.")
    print(" Scroll = zoom | Tasto R = reset zoom")
    print(" Bottone 'Test detection' per verificare i template.\n")
    from template_builder import run
    run(map_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="radar_tool",
        description="Censimento e classificazione icone mappa radar",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="Rileva pin sulla mappa")
    p_scan.add_argument("map_path")
    p_scan.add_argument("--threshold", type=float, default=0.65)
    p_scan.add_argument("--debug", action="store_true")
    p_scan.add_argument("--out", default="detections.json")

    p_label = sub.add_parser("label", help="GUI per etichettare i pin")
    p_label.add_argument("map_path")
    p_label.add_argument("--detections", default="detections.json")

    sub.add_parser("train", help="Addestra Random Forest sul dataset")

    p_run = sub.add_parser("run", help="Scan + classificazione completa")
    p_run.add_argument("map_path")
    p_run.add_argument("--threshold", type=float, default=0.65)
    p_run.add_argument("--debug", action="store_true")

    p_tmpl = sub.add_parser("add-template", help="GUI per aggiungere template")
    p_tmpl.add_argument("map_path")

    args = parser.parse_args()

    if args.cmd == "scan":
        cmd_scan(args.map_path, args.threshold, args.debug, args.out)
    elif args.cmd == "label":
        cmd_label(args.map_path, args.detections)
    elif args.cmd == "train":
        cmd_train()
    elif args.cmd == "run":
        cmd_run(args.map_path, args.threshold, args.debug)
    elif args.cmd == "add-template":
        cmd_add_template(args.map_path)


if __name__ == "__main__":
    main()
