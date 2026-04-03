"""\
classifier.py
Estrae feature dai crop 64×64 e addestra/usa un Random Forest.

Feature (43 totali):
- Istogramma HSV normalizzato (H:16 + S:8 + V:8 = 32)
- Media e std per canale RGB (3×2 = 6)
- Luminosità media zone 2×2 (4)
- Edge density Canny (1)

Patch (Mar 2026):
- CV robusta: n_splits non supera la numerosità minima per classe.
- Se una classe ha <2 campioni, la cross-validation viene saltata (cv_acc=None).
"""\

import cv2
import numpy as np
import json
import pickle
from pathlib import Path


def extract_features(crop_bgr: np.ndarray) -> np.ndarray:
    crop = cv2.resize(crop_bgr, (64, 64))
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

    feat = []

    # istogramma HSV
    for ch, bins, rng in [(0, 16, (0, 180)), (1, 8, (0, 256)), (2, 8, (0, 256))]:
        h = cv2.calcHist([hsv], [ch], None, [bins], rng).flatten()
        feat.extend((h / (h.sum() + 1e-6)).tolist())

    # stat RGB
    for ch in range(3):
        c = crop[:, :, ch].astype(np.float32)
        feat += [c.mean() / 255.0, c.std() / 128.0]

    # zone 2×2
    for zone in [gray[:32, :32], gray[:32, 32:], gray[32:, :32], gray[32:, 32:]]:
        feat.append(zone.mean() / 255.0)

    # edge density
    feat.append(cv2.Canny(gray, 50, 150).mean() / 255.0)

    return np.array(feat, dtype=np.float32)


def print_feature_importance(clf: "Classifier", top_n: int = 10) -> None:
    """Stampa le feature più importanti del RandomForest (se disponibili)."""
    try:
        importances = getattr(clf.rf, "feature_importances_", None)
        if importances is None:
            return
        idx = np.argsort(-importances)[:max(1, int(top_n))]
        print("\nTop feature importance:")
        for i in idx:
            print(f"  f{int(i):02d} {float(importances[int(i)]):.4f}")
    except Exception:
        return


class Classifier:
    def __init__(self, n_estimators: int = 200):
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.preprocessing import LabelEncoder

        self.rf = RandomForestClassifier(
            n_estimators=n_estimators,
            random_state=42,
            n_jobs=-1,
        )
        self.le = LabelEncoder()
        self.trained = False
        self.classes_: list[str] = []

    def train(self, labels_json: Path, crops_dir: Path) -> dict:
        from sklearn.model_selection import cross_val_score

        with open(labels_json, encoding="utf-8") as f:
            recs = [r for r in json.load(f) if r.get("label") and r["label"] != "scarta"]

        if len(recs) < 5:
            raise ValueError(f"Troppo pochi campioni: {len(recs)}")

        X, y, skip = [], [], 0
        for r in recs:
            p = crops_dir / r["crop_file"]
            if not p.exists():
                skip += 1
                continue
            img = cv2.imread(str(p))
            if img is None:
                skip += 1
                continue
            X.append(extract_features(img))
            y.append(r["label"])

        X = np.array(X)
        # distribuzione classi
        counts = {}
        for lbl in y:
            counts[lbl] = counts.get(lbl, 0) + 1
        min_per_class = min(counts.values()) if counts else 0

        ye = self.le.fit_transform(y)
        self.classes_ = list(self.le.classes_)

        cv_acc = None
        cv_std = None

        # Cross-validation solo se ogni classe ha almeno 2 campioni
        # e comunque n_splits <= min_per_class
        if min_per_class >= 2 and len(X) >= 4:
            n_splits = min(5, len(X) // 2, min_per_class)
            # n_splits minimo 2
            if n_splits >= 2:
                cv = cross_val_score(self.rf, X, ye, cv=n_splits)
                cv_acc = float(cv.mean())
                cv_std = float(cv.std())

        self.rf.fit(X, ye)
        self.trained = True

        return {
            "n_samples": int(len(X)),
            "classes": self.classes_,
            "cv_acc": cv_acc,
            "cv_std": cv_std,
            "skipped": int(skip),
            "min_per_class": int(min_per_class),
            "class_counts": counts,
        }

    def predict(self, crop_bgr: np.ndarray) -> tuple[str, float]:
        if not self.trained:
            return "sconosciuto", 0.0
        p = self.rf.predict_proba(extract_features(crop_bgr).reshape(1, -1))[0]
        i = int(p.argmax())
        return self.classes_[i], float(p[i])

    def predict_top3(self, crop_bgr: np.ndarray) -> list[tuple[str, float]]:
        if not self.trained:
            return [("sconosciuto", 0.0)]
        p = self.rf.predict_proba(extract_features(crop_bgr).reshape(1, -1))[0]
        return [(self.classes_[i], float(p[i])) for i in np.argsort(p)[::-1][:3]]

    def save(self, path: Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({"rf": self.rf, "le": self.le, "classes": self.classes_, "trained": self.trained}, f)

    def load(self, path: Path):
        with open(path, "rb") as f:
            d = pickle.load(f)
        self.rf = d["rf"]
        self.le = d["le"]
        self.classes_ = d["classes"]
        self.trained = d["trained"]
