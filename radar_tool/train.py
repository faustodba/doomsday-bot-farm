"""\
train.py
Addestra il Random Forest sul dataset etichettato dal labeler.
Uso:
  python train.py
"""\

from pathlib import Path
import sys

HERE = Path(__file__).parent
DATASET_DIR = HERE / "dataset"


def main():
    labels_path = DATASET_DIR / "labels.json"
    if not labels_path.exists():
        print(f"ERRORE: {labels_path} non trovato")
        print(" Etichetta prima con: python labeler.py detections.json <mappa>")
        sys.exit(1)

    from classifier import Classifier

    print(f"Dataset: {labels_path}")
    clf = Classifier()

    try:
        m = clf.train(labels_path, DATASET_DIR / "crops")
    except ValueError as e:
        print(f"ERRORE: {e}")
        sys.exit(1)

    print("\nRisultati:")
    print(f"  Campioni  : {m['n_samples']}")
    print(f"  Classi    : {', '.join(m['classes'])}")

    if m.get('cv_acc') is None:
        print(f"  CV acc    : n/a (min_per_class={m.get('min_per_class')})")
    else:
        print(f"  CV acc    : {m['cv_acc']:.1%} ± {m['cv_std']:.1%}")

    if m.get('skipped'):
        print(f"  Saltati   : {m['skipped']} (crop mancanti)")

    out = DATASET_DIR / "classifier.pkl"
    clf.save(out)
    print(f"\nModello salvato: {out}")


if __name__ == "__main__":
    main()
