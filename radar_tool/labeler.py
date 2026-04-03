"""
labeler.py
GUI tkinter per etichettare i crop rilevati dal detector.

Tasti rapidi:
  1-9 / 0  → seleziona label
  Invio    → conferma + prossimo
  D        → scarta
  ←/→      → naviga senza salvare
"""

import tkinter as tk
from tkinter import ttk, messagebox
import cv2
import numpy as np
from PIL import Image, ImageTk
import json
import threading
from pathlib import Path

HERE        = Path(__file__).parent
DATASET_DIR = HERE / "dataset"

LABELS = ["pedone","auto","camion","skull",
          "avatar","numero","card","paracadute","fiamma","bottiglia","soldati","sconosciuto"]

LABEL_KEYS = {str(i+1): l for i,l in enumerate(LABELS[:9])}
LABEL_KEYS["0"] = "sconosciuto"

COLORS = {
    "pedone":      "#b2dfdb",
    "auto":        "#e1bee7",
    "camion":      "#ffe0b2",
    "skull":       "#f8bbd0",
    "avatar":      "#bbdefb",
    "numero":      "#cfd8dc",
    "paracadute":  "#c8e6c9", 
    "card":        "#fff9c4",
    "fiamma":      "#ffccbc",
    "bottiglia":   "#b3e5fc",
    "soldati":     "#dce775",
    "sconosciuto": "#eeeeee",
    "scarta":      "#ef9a9a",
}

ZOOM    = 5
CTX_PAD = 55


class LabelerApp:

    def __init__(self, root: tk.Tk, detections_json: Path,
                 map_path: str, dataset_dir: Path = DATASET_DIR):
        self.root        = root
        self.dataset_dir = dataset_dir
        self.crops_dir   = dataset_dir / "crops"
        self.labels_path = dataset_dir / "labels.json"
        self._clf        = None

        self.map_img = cv2.imread(map_path)
        if self.map_img is None:
            messagebox.showerror("Errore", f"Mappa non trovata:\n{map_path}")
            root.destroy(); return

        with open(detections_json) as f:
            self.detections: list[dict] = json.load(f)

        self.labels: dict[str,str] = {}
        if self.labels_path.exists():
            with open(self.labels_path) as f:
                for r in json.load(f):
                    self.labels[r["crop_file"]] = r["label"]

        self.idx     = 0
        self.changes = 0
        self._photo_crop = None
        self._photo_ctx  = None

        self._build_ui()
        self._load_item(0)
        root.bind("<Key>", self._on_key)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.root.title("Radar Labeler")
        self.root.configure(bg="#f5f5f5")
        self.root.resizable(False, False)

        # sinistra: lista
        left = tk.Frame(self.root, bg="#f5f5f5", width=195)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(8,0), pady=8)
        left.pack_propagate(False)

        tk.Label(left, text="Coda", bg="#f5f5f5",
                 font=("Segoe UI",9,"bold")).pack(anchor="w")
        self._prog_var = tk.StringVar()
        tk.Label(left, textvariable=self._prog_var, bg="#f5f5f5",
                 font=("Segoe UI",8), fg="#888").pack(anchor="w")
        self._pbar = ttk.Progressbar(left, length=180, mode="determinate")
        self._pbar.pack(fill=tk.X, pady=(2,6))

        fr = tk.Frame(left, bg="white", relief=tk.SOLID, bd=1)
        fr.pack(fill=tk.BOTH, expand=True)
        self._listbox = tk.Listbox(fr, width=22, font=("Consolas",8),
                                   bg="white", selectbackground="#1565c0",
                                   selectforeground="white",
                                   activestyle="none", relief=tk.FLAT)
        sb = ttk.Scrollbar(fr, command=self._listbox.yview)
        self._listbox.config(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._listbox.pack(fill=tk.BOTH, expand=True)
        self._listbox.bind("<<ListboxSelect>>", self._on_list_sel)

        for i, det in enumerate(self.detections):
            cf  = det.get("crop_file", f"crop_{i:03d}.png")
            lbl = self.labels.get(cf, "")
            self._listbox.insert(tk.END, f"{i+1:2d}. {cf[:16]}")
            if lbl:
                self._listbox.itemconfig(i, fg="#c62828" if lbl=="scarta" else "#2e7d32")

        # centro: visualizzazione
        center = tk.Frame(self.root, bg="#f5f5f5")
        center.pack(side=tk.LEFT, padx=8, pady=8)

        tk.Label(center, text="Icona (5×)", bg="#f5f5f5",
                 font=("Segoe UI",8), fg="#999").pack(anchor="w")
        self._cv_crop = tk.Canvas(center, width=64*ZOOM, height=64*ZOOM,
                                  bg="#ddd", relief=tk.SOLID, bd=1)
        self._cv_crop.pack()

        tk.Label(center, text="Contesto mappa", bg="#f5f5f5",
                 font=("Segoe UI",8), fg="#999").pack(anchor="w", pady=(6,0))
        self._cv_ctx = tk.Canvas(center, width=(CTX_PAD*2)*2, height=(CTX_PAD*2)*2,
                                 bg="#222", relief=tk.SOLID, bd=1)
        self._cv_ctx.pack()

        self._info_var = tk.StringVar()
        tk.Label(center, textvariable=self._info_var, bg="#f5f5f5",
                 font=("Consolas",8), fg="#555", justify=tk.LEFT).pack(anchor="w", pady=(4,0))

        self._pred_var = tk.StringVar(value="RF: —")
        tk.Label(center, textvariable=self._pred_var, bg="#f5f5f5",
                 font=("Segoe UI",9,"italic"), fg="#1565c0").pack(anchor="w")

        # destra: label + azioni
        right = tk.Frame(self.root, bg="#f5f5f5")
        right.pack(side=tk.LEFT, padx=(0,8), pady=8, anchor="n")

        tk.Label(right, text="Label  (tasti 1-9, 0)", bg="#f5f5f5",
                 font=("Segoe UI",9,"bold")).pack(anchor="w")

        self._btn_lbls: dict[str,tk.Button] = {}
        fr_lbl = tk.Frame(right, bg="#f5f5f5")
        fr_lbl.pack(pady=(4,0))
        for i, lbl in enumerate(LABELS):
            key = str(i+1) if i < 9 else "0"
            col = COLORS.get(lbl, "#eee")
            btn = tk.Button(fr_lbl, text=f"[{key}] {lbl}", width=13,
                            relief=tk.FLAT, bd=1, bg=col, activebackground=col,
                            font=("Segoe UI",9),
                            command=lambda l=lbl: self._sel_label(l))
            btn.grid(row=i//2, column=i%2, padx=2, pady=2, sticky="ew")
            self._btn_lbls[lbl] = btn

        # label selezionata
        fr_sel = tk.Frame(right, bg="#e8eaf6", relief=tk.SOLID, bd=1)
        fr_sel.pack(fill=tk.X, pady=(8,4))
        tk.Label(fr_sel, text="Selezionata:", bg="#e8eaf6",
                 font=("Segoe UI",8)).pack(side=tk.LEFT, padx=6, pady=3)
        self._sel_var = tk.StringVar(value="—")
        tk.Label(fr_sel, textvariable=self._sel_var, bg="#e8eaf6",
                 font=("Segoe UI",11,"bold"), fg="#1a237e").pack(side=tk.LEFT)

        # navigazione
        fr_nav = tk.Frame(right, bg="#f5f5f5")
        fr_nav.pack(fill=tk.X, pady=2)
        tk.Button(fr_nav, text="← Prec", command=self._prev,
                  font=("Segoe UI",8)).pack(side=tk.LEFT, padx=2)
        tk.Button(fr_nav, text="→ Next", command=self._next_no_save,
                  font=("Segoe UI",8)).pack(side=tk.LEFT, padx=2)

        tk.Button(right, text="[D] Scarta", bg="#ef9a9a",
                  relief=tk.FLAT, font=("Segoe UI",9),
                  command=self._scarta).pack(fill=tk.X, pady=2)

        tk.Button(right, text="✔ Conferma + Next  [Invio]",
                  bg="#a5d6a7", relief=tk.FLAT,
                  font=("Segoe UI",10,"bold"),
                  command=self._confirm).pack(fill=tk.X, pady=(4,10))

        ttk.Separator(right).pack(fill=tk.X, pady=4)

        self._btn_train = tk.Button(right, text="⚙ Ri-addestra RF",
                                    bg="#90caf9", relief=tk.FLAT,
                                    font=("Segoe UI",9),
                                    command=self._retrain)
        self._btn_train.pack(fill=tk.X, pady=2)

        self._train_var = tk.StringVar()
        tk.Label(right, textvariable=self._train_var, bg="#f5f5f5",
                 font=("Segoe UI",8), fg="#555", wraplength=180,
                 justify=tk.LEFT).pack(anchor="w")

        ttk.Separator(right).pack(fill=tk.X, pady=6)
        self._stats_var = tk.StringVar()
        tk.Label(right, textvariable=self._stats_var, bg="#f5f5f5",
                 font=("Consolas",8), fg="#666", justify=tk.LEFT).pack(anchor="w")

    # ── Carica item ───────────────────────────────────────────────────────────

    def _load_item(self, idx: int):
        if not (0 <= idx < len(self.detections)):
            return
        self.idx = idx
        det = self.detections[idx]
        cx, cy = det["cx"], det["cy"]
        cf = det.get("crop_file", f"crop_{idx:03d}.png")
        det["crop_file"] = cf

        # crop
        crop_path = self.crops_dir / cf
        if crop_path.exists():
            crop = cv2.imread(str(crop_path))
        else:
            from detector import extract_crop
            crop = extract_crop(self.map_img, cx, cy, 64)
            self.crops_dir.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(crop_path), crop)

        # mostra crop 5×
        big = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB),
                         (64*ZOOM, 64*ZOOM), interpolation=cv2.INTER_NEAREST)
        self._photo_crop = ImageTk.PhotoImage(Image.fromarray(big))
        self._cv_crop.create_image(0, 0, anchor=tk.NW, image=self._photo_crop)

        # contesto mappa
        p = CTX_PAD
        x1,y1 = max(0,cx-p), max(0,cy-p)
        x2,y2 = min(self.map_img.shape[1],cx+p), min(self.map_img.shape[0],cy+p)
        ctx = self.map_img[y1:y2,x1:x2].copy()
        cv2.circle(ctx, (cx-x1, cy-y1), 6, (0,255,80), 2)
        cv2.circle(ctx, (cx-x1, cy-y1), 2, (255,255,255), -1)
        ctx_big = cv2.resize(cv2.cvtColor(ctx, cv2.COLOR_BGR2RGB),
                             (p*4, p*4), interpolation=cv2.INTER_LINEAR)
        self._photo_ctx = ImageTk.PhotoImage(Image.fromarray(ctx_big))
        self._cv_ctx.create_image(0, 0, anchor=tk.NW, image=self._photo_ctx)

        # info
        self._info_var.set(
            f"File:  {cf}\n"
            f"Pos:   cx={cx}  cy={cy}\n"
            f"Conf:  {det.get('conf',0):.3f}  tipo={det.get('tipo','?')}"
        )

        # label corrente
        cur = self.labels.get(cf, "")
        self._highlight(cur)
        self._sel_var.set(cur or "—")

        # RF predizione
        self._update_pred(crop)

        # lista
        self._listbox.selection_clear(0, tk.END)
        self._listbox.selection_set(idx)
        self._listbox.see(idx)

        # stats
        val = sum(1 for v in self.labels.values() if v and v != "scarta")
        sca = sum(1 for v in self.labels.values() if v == "scarta")
        tot = len(self.detections)
        self._prog_var.set(f"{len(self.labels)}/{tot} etichettati")
        self._pbar["value"] = len(self.labels)/max(tot,1)*100
        self._stats_var.set(f"Validi: {val}\nScartati: {sca}\nRimasti: {tot-len(self.labels)}")

    def _highlight(self, lbl: str):
        for l, btn in self._btn_lbls.items():
            btn.config(relief=tk.SOLID if l==lbl else tk.FLAT,
                       bd=2 if l==lbl else 1)

    def _update_pred(self, crop):
        try:
            clf_path = self.dataset_dir / "classifier.pkl"
            if clf_path.exists() and self._clf is None:
                from classifier import Classifier
                self._clf = Classifier()
                self._clf.load(clf_path)
            if self._clf and self._clf.trained:
                top = self._clf.predict_top3(crop)
                self._pred_var.set("RF: " + "  ".join(f"{l}({c:.0%})" for l,c in top))
                return
        except Exception:
            pass
        self._pred_var.set("RF: —")

    # ── Azioni ───────────────────────────────────────────────────────────────

    def _sel_label(self, lbl: str):
        self._highlight(lbl)
        self._sel_var.set(lbl)

    def _confirm(self):
        lbl = self._sel_var.get()
        if not lbl or lbl == "—":
            messagebox.showwarning("Nessuna label", "Seleziona una label prima.")
            return
        cf = self.detections[self.idx].get("crop_file","")
        self.labels[cf] = lbl
        self.changes += 1
        self._listbox.itemconfig(self.idx,
            fg="#c62828" if lbl=="scarta" else "#2e7d32")
        self._save_labels()
        self._next()

    def _scarta(self):
        self._sel_label("scarta")
        self._confirm()

    def _next(self):
        if self.idx < len(self.detections)-1:
            self._load_item(self.idx+1)
        else:
            messagebox.showinfo("Fine","Tutte le icone sono state etichettate!")

    def _next_no_save(self):
        if self.idx < len(self.detections)-1:
            self._load_item(self.idx+1)

    def _prev(self):
        if self.idx > 0:
            self._load_item(self.idx-1)

    def _on_list_sel(self, _):
        sel = self._listbox.curselection()
        if sel:
            self._load_item(sel[0])

    def _on_key(self, event):
        k = event.keysym.lower()
        if k in ("return","kp_enter"): self._confirm()
        elif k == "d":                 self._scarta()
        elif k == "left":              self._prev()
        elif k == "right":             self._next_no_save()
        elif event.char in LABEL_KEYS: self._sel_label(LABEL_KEYS[event.char])

    # ── Salva / train ────────────────────────────────────────────────────────

    def _save_labels(self):
        self.labels_path.parent.mkdir(parents=True, exist_ok=True)
        records = []
        for det in self.detections:
            cf = det.get("crop_file","")
            if cf in self.labels:
                records.append({"crop_file":cf, "label":self.labels[cf],
                                 "cx":det["cx"], "cy":det["cy"],
                                 "conf":det.get("conf",0),
                                 "tipo":det.get("tipo",""),
                                 "template":det.get("template","")})
        with open(self.labels_path,"w") as f:
            json.dump(records, f, indent=2)

    def _retrain(self):
        val = sum(1 for v in self.labels.values() if v and v != "scarta")
        if val < 5:
            messagebox.showwarning("Troppo pochi", f"Solo {val} campioni validi (min 5).")
            return
        self._btn_train.config(state=tk.DISABLED)
        self._train_var.set("Addestramento...")

        def _t():
            try:
                from classifier import Classifier
                clf = Classifier()
                m   = clf.train(self.labels_path, self.crops_dir)
                clf.save(self.dataset_dir/"classifier.pkl")
                self._clf = clf
                msg = (f"CV acc: {m['cv_acc']:.1%} ± {m['cv_std']:.1%}\n"
                       f"Classi: {', '.join(m['classes'])}\n"
                       f"Campioni: {m['n_samples']}")
                self.root.after(0, lambda: self._train_var.set(msg))
                self.root.after(0, lambda: self._load_item(self.idx))
            except Exception as e:
                err = str(e)
                self.root.after(0, lambda: self._train_var.set(f"Errore: {err}"))
            finally:
                self.root.after(0, lambda: self._btn_train.config(state=tk.NORMAL))

        threading.Thread(target=_t, daemon=True).start()

    def _on_close(self):
        if self.changes:
            self._save_labels()
        self.root.destroy()


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Uso: python labeler.py <detections.json> <map_full.png>")
        sys.exit(1)
    root = tk.Tk()
    LabelerApp(root, Path(sys.argv[1]), sys.argv[2])
    root.mainloop()
