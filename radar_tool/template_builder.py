"""
template_builder.py
GUI interattiva per creare e gestire i template dei pin sulla mappa radar.

Lancio:
    python template_builder.py <map_full.png>

Comandi:
    Click + drag    → seleziona pin, preview in tempo reale
    Rilascio        → popup nome → salva in templates/
    Scroll          → zoom centrato sul cursore
    Tasto R         → reset zoom
    Click dx + drag → pan
    Bottone "Test"  → esegue detection e mostra i bbox sulla mappa
    Bottone ✕       → elimina template dalla lista
"""

import sys
import tkinter as tk
from tkinter import simpledialog, messagebox
import cv2
import numpy as np
from PIL import Image, ImageTk
from pathlib import Path

HERE          = Path(__file__).parent
TEMPLATES_DIR = HERE / "templates"


class TemplateBuilder:

    def __init__(self, root: tk.Tk, map_path: str):
        self.root    = root
        self.map_bgr = cv2.imread(map_path)
        if self.map_bgr is None:
            messagebox.showerror("Errore", f"Impossibile aprire:\n{map_path}")
            root.destroy()
            return
        self.map_rgb = cv2.cvtColor(self.map_bgr, cv2.COLOR_BGR2RGB)
        self.map_h, self.map_w = self.map_bgr.shape[:2]

        # zoom / pan
        self.zoom  = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0

        # selezione
        self.sel_start   = None
        self.sel_rect_id = None
        self.drawing     = False
        self._cur_crop   = None   # BGR crop corrente

        # detection overlay ids
        self._det_ids = []

        # photo refs (anti GC)
        self._photo_map     = None
        self._photo_preview = None
        self._tmpl_photos   = []

        self._build_ui()
        self.root.update()
        self.root.after(100, self._init_render)

    def _init_render(self):
        self._fit_zoom()
        self._redraw()
        self._reload_template_list()

        root.bind("<Key>", self._on_key)
        root.protocol("WM_DELETE_WINDOW", root.destroy)

    # ──────────────────────────────────────────── UI

    def _build_ui(self):
        self.root.title("Template Builder — Radar Tool")
        self.root.configure(bg="#1a1a1a")

        # ── canvas (sinistra) ─────────────────────
        frame_left = tk.Frame(self.root, bg="#1a1a1a")
        frame_left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        bar = tk.Frame(frame_left, bg="#252525", height=28)
        bar.pack(fill=tk.X)
        bar.pack_propagate(False)
        tk.Label(bar, text="  Drag per selezionare  |  Scroll=zoom  |  Click dx=pan  |  R=reset",
                 bg="#252525", fg="#888", font=("Segoe UI", 8)).pack(side=tk.LEFT)
        self._zoom_lbl = tk.Label(bar, text="100%", bg="#252525",
                                  fg="#666", font=("Consolas", 8))
        self._zoom_lbl.pack(side=tk.RIGHT, padx=8)

        self.canvas = tk.Canvas(frame_left, bg="#111",
                                cursor="crosshair", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.canvas.bind("<ButtonPress-1>",   self._sel_start)
        self.canvas.bind("<B1-Motion>",       self._sel_drag)
        self.canvas.bind("<ButtonRelease-1>", self._sel_release)
        self.canvas.bind("<ButtonPress-3>",   self._pan_start)
        self.canvas.bind("<B3-Motion>",       self._pan_drag)
        self.canvas.bind("<MouseWheel>",      self._scroll)
        self.canvas.bind("<Button-4>",        self._scroll)
        self.canvas.bind("<Button-5>",        self._scroll)
        self.canvas.bind("<Configure>",       lambda e: self._redraw())

        # ── pannello destra ───────────────────────
        right = tk.Frame(self.root, bg="#222", width=250)
        right.pack(side=tk.RIGHT, fill=tk.Y)
        right.pack_propagate(False)

        # preview
        tk.Label(right, text="Preview", bg="#222",
                 fg="#aaa", font=("Segoe UI", 9, "bold")).pack(pady=(12, 2))
        self._prev_canvas = tk.Canvas(right, width=200, height=200,
                                      bg="#111", highlightthickness=1,
                                      highlightbackground="#444")
        self._prev_canvas.pack()
        self._prev_info = tk.StringVar(value="nessuna selezione")
        tk.Label(right, textvariable=self._prev_info, bg="#222",
                 fg="#666", font=("Consolas", 7)).pack()

        # salva
        self._btn_save = tk.Button(right, text="💾  Salva template",
                                   state=tk.DISABLED,
                                   bg="#163016", fg="#6ec96e",
                                   activebackground="#1e401e",
                                   relief=tk.FLAT,
                                   font=("Segoe UI", 9, "bold"),
                                   command=self._save_template)
        self._btn_save.pack(fill=tk.X, padx=14, pady=(8, 4))

        # test
        tk.Button(right, text="🔍  Test detection",
                  bg="#101830", fg="#6699dd",
                  activebackground="#182040",
                  relief=tk.FLAT, font=("Segoe UI", 9),
                  command=self._run_test).pack(fill=tk.X, padx=14, pady=2)

        self._test_lbl = tk.Label(right, text="", bg="#222",
                                  fg="#6699dd", font=("Consolas", 7),
                                  wraplength=220, justify=tk.LEFT)
        self._test_lbl.pack(anchor="w", padx=14, pady=2)

        tk.Frame(right, bg="#333", height=1).pack(fill=tk.X, padx=8, pady=8)

        # lista template
        tk.Label(right, text="Template salvati", bg="#222",
                 fg="#aaa", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=14)
        self._tmpl_count = tk.Label(right, text="", bg="#222",
                                    fg="#666", font=("Segoe UI", 7))
        self._tmpl_count.pack(anchor="w", padx=14)

        list_frame = tk.Frame(right, bg="#222")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)
        sb = tk.Scrollbar(list_frame, bg="#222")
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._list_canvas = tk.Canvas(list_frame, bg="#222",
                                      yscrollcommand=sb.set,
                                      highlightthickness=0)
        sb.config(command=self._list_canvas.yview)
        self._list_canvas.pack(fill=tk.BOTH, expand=True)
        self._list_inner = tk.Frame(self._list_canvas, bg="#222")
        self._list_canvas.create_window((0, 0), window=self._list_inner, anchor="nw")
        self._list_inner.bind("<Configure>",
            lambda e: self._list_canvas.configure(
                scrollregion=self._list_canvas.bbox("all")))

    # ──────────────────────────────────────────── zoom / pan

    def _fit_zoom(self):
        self.root.update_idletasks()
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw < 10 or ch < 10:
            cw, ch = 800, 550
        self.zoom  = min(cw / self.map_w, ch / self.map_h, 1.5)
        self.pan_x = (cw - self.map_w * self.zoom) / 2
        self.pan_y = (ch - self.map_h * self.zoom) / 2

    def _redraw(self):
        dw = max(1, int(self.map_w * self.zoom))
        dh = max(1, int(self.map_h * self.zoom))
        resized = cv2.resize(self.map_rgb, (dw, dh), interpolation=cv2.INTER_LINEAR)
        self._photo_map = ImageTk.PhotoImage(Image.fromarray(resized))
        self.canvas.delete("map")
        self.canvas.create_image(self.pan_x, self.pan_y,
                                 anchor=tk.NW, image=self._photo_map, tags="map")
        self._zoom_lbl.config(text=f"{self.zoom*100:.0f}%")
        # riposiziona overlay detection
        self._reproject_detections()

    def _scroll(self, event):
        f = 1.12 if (getattr(event, "delta", 0) > 0 or event.num == 4) else 1/1.12
        cx = float(event.x)
        cy = float(event.y)
        self.pan_x = cx - (cx - self.pan_x) * f
        self.pan_y = cy - (cy - self.pan_y) * f
        self.zoom  = max(0.2, min(8.0, self.zoom * f))
        self._redraw()

    def _pan_start(self, event):
        self._pan0 = (event.x, event.y, self.pan_x, self.pan_y)

    def _pan_drag(self, event):
        if not hasattr(self, "_pan0"):
            return
        ox, oy, px, py = self._pan0
        self.pan_x = px + event.x - ox
        self.pan_y = py + event.y - oy
        self._redraw()

    def _on_key(self, event):
        if event.keysym.lower() == "r":
            self._fit_zoom()
            self._redraw()

    # ──────────────────────────────────────────── coord helpers

    def _c2m(self, cx, cy):
        """canvas → mappa originale (clampata)"""
        mx = int((cx - self.pan_x) / self.zoom)
        my = int((cy - self.pan_y) / self.zoom)
        return (max(0, min(self.map_w - 1, mx)),
                max(0, min(self.map_h - 1, my)))

    def _m2c(self, mx, my):
        """mappa originale → canvas"""
        return (mx * self.zoom + self.pan_x,
                my * self.zoom + self.pan_y)

    # ──────────────────────────────────────────── selezione

    def _sel_start(self, event):
        self.drawing   = True
        self.sel_start = (event.x, event.y)
        if self.sel_rect_id:
            self.canvas.delete(self.sel_rect_id)
            self.sel_rect_id = None

    def _sel_drag(self, event):
        if not self.drawing:
            return
        x0, y0 = self.sel_start
        self.canvas.delete("selrect")
        self.sel_rect_id = self.canvas.create_rectangle(
            x0, y0, event.x, event.y,
            outline="#00ff88", width=2, dash=(5, 3), tags="selrect")
        # preview live
        mx0, my0 = self._c2m(x0, y0)
        mx1, my1 = self._c2m(event.x, event.y)
        x1, x2 = sorted([mx0, mx1])
        y1, y2 = sorted([my0, my1])
        if x2 - x1 > 4 and y2 - y1 > 4:
            self._show_preview(x1, y1, x2, y2)

    def _sel_release(self, event):
        if not self.drawing:
            return
        self.drawing = False
        mx0, my0 = self._c2m(*self.sel_start)
        mx1, my1 = self._c2m(event.x, event.y)
        x1, x2 = sorted([mx0, mx1])
        y1, y2 = sorted([my0, my1])

        if x2 - x1 < 8 or y2 - y1 < 8:
            self._btn_save.config(state=tk.DISABLED)
            self._prev_info.set("selezione troppo piccola")
            return

        self._cur_crop = self.map_bgr[y1:y2, x1:x2].copy()
        self._cur_bbox = (x1, y1, x2, y2)
        self._show_preview(x1, y1, x2, y2)
        self._btn_save.config(state=tk.NORMAL)

        # rettangolo finale fisso
        self.canvas.delete("selrect")
        cx0, cy0 = self._m2c(x1, y1)
        cx1, cy1 = self._m2c(x2, y2)
        self.sel_rect_id = self.canvas.create_rectangle(
            cx0, cy0, cx1, cy1,
            outline="#00ff88", width=2, tags="selrect")

    def _show_preview(self, x1, y1, x2, y2):
        crop = self.map_bgr[y1:y2, x1:x2]
        if crop.size == 0:
            return
        h, w = crop.shape[:2]
        s = min(200 / w, 200 / h)
        nw, nh = max(1, int(w * s)), max(1, int(h * s))
        small = cv2.resize(crop, (nw, nh), interpolation=cv2.INTER_NEAREST)
        rgb   = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        bg    = Image.new("RGB", (200, 200), (17, 17, 17))
        bg.paste(Image.fromarray(rgb), ((200 - nw) // 2, (200 - nh) // 2))
        self._photo_preview = ImageTk.PhotoImage(bg)
        self._prev_canvas.create_image(0, 0, anchor=tk.NW, image=self._photo_preview)
        self._prev_info.set(f"{w}×{h} px  |  ({x1},{y1})–({x2},{y2})")

    # ──────────────────────────────────────────── salva template

    def _save_template(self):
        if self._cur_crop is None:
            return
        name = simpledialog.askstring(
            "Nome template",
            "Convenzione:  pin_COLORE_TIPO\n"
            "Esempi: pin_viola_ped  /  pin_rosso_skull  /  pin_gold_truck",
            initialvalue="pin_",
            parent=self.root)
        if not name:
            return
        name = name.strip().replace(" ", "_")
        if not name:
            return

        TEMPLATES_DIR.mkdir(exist_ok=True)
        out = TEMPLATES_DIR / f"{name}.png"
        if out.exists():
            if not messagebox.askyesno("Sovrascrivi?", f"'{name}' esiste già. Sovrascrivi?"):
                return

        cv2.imwrite(str(out), self._cur_crop)
        print(f"Salvato: {out}")

        # flash
        if self.sel_rect_id:
            self.canvas.itemconfig(self.sel_rect_id, outline="#ffffff", width=3)
            self.root.after(300, lambda: self.canvas.itemconfig(
                self.sel_rect_id, outline="#00ff88", width=2)
                if self.sel_rect_id else None)

        self._btn_save.config(state=tk.DISABLED)
        self._cur_crop = None
        self._reload_template_list()

    # ──────────────────────────────────────────── lista template

    def _reload_template_list(self):
        for w in self._list_inner.winfo_children():
            w.destroy()
        self._tmpl_photos.clear()

        files = sorted(TEMPLATES_DIR.glob("*.png")) if TEMPLATES_DIR.exists() else []
        self._tmpl_count.config(text=f"{len(files)} template")

        for p in files:
            img = cv2.imread(str(p))
            if img is None:
                continue
            h, w = img.shape[:2]
            s     = min(44 / w, 44 / h)
            thumb = cv2.resize(img, (max(1, int(w*s)), max(1, int(h*s))),
                               interpolation=cv2.INTER_AREA)
            rgb   = cv2.cvtColor(thumb, cv2.COLOR_BGR2RGB)
            bg    = Image.new("RGB", (44, 44), (34, 34, 34))
            bg.paste(Image.fromarray(rgb),
                     ((44 - thumb.shape[1]) // 2, (44 - thumb.shape[0]) // 2))
            photo = ImageTk.PhotoImage(bg)
            self._tmpl_photos.append(photo)

            row = tk.Frame(self._list_inner, bg="#2a2a2a", pady=2)
            row.pack(fill=tk.X, pady=1, padx=2)
            tk.Label(row, image=photo, bg="#2a2a2a").pack(side=tk.LEFT, padx=4)
            inf = tk.Frame(row, bg="#2a2a2a")
            inf.pack(side=tk.LEFT, fill=tk.X, expand=True)
            tk.Label(inf, text=p.stem, bg="#2a2a2a", fg="#ccc",
                     font=("Segoe UI", 8, "bold"), anchor="w").pack(fill=tk.X)
            tk.Label(inf, text=f"{w}×{h}", bg="#2a2a2a", fg="#666",
                     font=("Consolas", 7), anchor="w").pack(fill=tk.X)
            tk.Button(row, text="✕", bg="#2a2a2a", fg="#c44",
                      activebackground="#4a1010", relief=tk.FLAT,
                      font=("Segoe UI", 9), width=2,
                      command=lambda path=p: self._delete_template(path)
                      ).pack(side=tk.RIGHT, padx=4)

        self._list_inner.update_idletasks()
        self._list_canvas.configure(scrollregion=self._list_canvas.bbox("all"))

    def _delete_template(self, path: Path):
        if messagebox.askyesno("Elimina", f"Eliminare '{path.stem}'?"):
            path.unlink()
            self._reload_template_list()

    # ──────────────────────────────────────────── test detection

    def _run_test(self):
        for rid in self._det_ids:
            self.canvas.delete(rid)
        self._det_ids.clear()
        self._test_lbl.config(text="")

        try:
            from detector import load_templates, detect
        except ImportError:
            self._test_lbl.config(text="ERRORE: detector.py non trovato")
            return

        templates = load_templates(TEMPLATES_DIR)
        if not templates:
            self._test_lbl.config(text="Nessun template")
            return

        matches = detect(self.map_bgr, templates, threshold=0.65)
        self._last_matches = matches   # per _reproject_detections

        colors = {"viola": "#cc44ff", "rosso": "#ff4444", "gold": "#ffaa00"}
        for m in matches:
            col = next((v for k, v in colors.items() if k in m["tipo"]), "#00ff00")
            ox, oy, ow, oh = m["x"], m["y"], m["w"], m["h"]
            cx0, cy0 = self._m2c(ox, oy)
            cx1, cy1 = self._m2c(ox + ow, oy + oh)
            ccx, ccy = self._m2c(m["cx"], m["cy"])
            r1 = self.canvas.create_rectangle(cx0, cy0, cx1, cy1,
                                              outline=col, width=2, tags="det")
            r2 = self.canvas.create_oval(ccx-4, ccy-4, ccx+4, ccy+4,
                                         fill=col, outline="white", tags="det")
            r3 = self.canvas.create_text(cx0 + 2, cy0 - 2, anchor=tk.SW,
                                         text=f"{m['tipo']} {m['conf']:.2f}",
                                         fill=col, font=("Consolas", 7), tags="det")
            self._det_ids.extend([r1, r2, r3])

        lines = [f"Trovati: {len(matches)}"] + \
                [f"  ({m['cx']},{m['cy']}) {m['tipo']}"
                 for m in sorted(matches, key=lambda x: x["cy"])[:10]]
        self._test_lbl.config(text="\n".join(lines))

    def _reproject_detections(self):
        """Riposiziona i bbox detection dopo uno zoom/pan."""
        if not hasattr(self, "_last_matches"):
            return
        self.canvas.delete("det")
        self._det_ids.clear()
        colors = {"viola": "#cc44ff", "rosso": "#ff4444", "gold": "#ffaa00"}
        for m in self._last_matches:
            col = next((v for k, v in colors.items() if k in m["tipo"]), "#00ff00")
            ox, oy, ow, oh = m["x"], m["y"], m["w"], m["h"]
            cx0, cy0 = self._m2c(ox, oy)
            cx1, cy1 = self._m2c(ox + ow, oy + oh)
            ccx, ccy = self._m2c(m["cx"], m["cy"])
            r1 = self.canvas.create_rectangle(cx0, cy0, cx1, cy1,
                                              outline=col, width=2, tags="det")
            r2 = self.canvas.create_oval(ccx-4, ccy-4, ccx+4, ccy+4,
                                         fill=col, outline="white", tags="det")
            r3 = self.canvas.create_text(cx0 + 2, cy0 - 2, anchor=tk.SW,
                                         text=f"{m['tipo']} {m['conf']:.2f}",
                                         fill=col, font=("Consolas", 7), tags="det")
            self._det_ids.extend([r1, r2, r3])


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python template_builder.py <map_full.png>")
        sys.exit(1)
    root = tk.Tk()
    root.geometry("1280x720")
    root.minsize(900, 540)
    TemplateBuilder(root, sys.argv[1])
    root.mainloop()
