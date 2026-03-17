# ==============================================================================
#  DOOMSDAY BOT V5 - launcher.py
#  GUI di controllo: avvio/stop bot, selezione istanze, log in tempo reale
# ==============================================================================

import tkinter as tk
from tkinter import scrolledtext
import subprocess
import threading
import sys
import os
import signal
import time
import json
from datetime import datetime

# --- Percorso bot ---
BOT_DIR     = r"E:\Bot-raccolta\V5"
PYTHON      = sys.executable
STATUS_FILE = os.path.join(BOT_DIR, "status.json")

# --- Carica istanze da config.py ---
import importlib.util as _ilu, pathlib as _pl

def _carica_istanze_da_config():
    cfg_path = _pl.Path(BOT_DIR) / "config.py"
    spec = _ilu.spec_from_file_location("config_bot", cfg_path)
    cfg  = _ilu.module_from_spec(spec)
    spec.loader.exec_module(cfg)
    bs   = [i[0] for i in getattr(cfg, "ISTANZE",      [])]
    mumu = [i[0] for i in getattr(cfg, "ISTANZE_MUMU", [])]
    return bs, mumu

try:
    _BS_ISTANZE, _MUMU_ISTANZE = _carica_istanze_da_config()
except Exception:
    _BS_ISTANZE   = ["FAU_00","FAU_01","FAU_02","FAU_03","FAU_07","FAU_04","FAU_05","FAU_08"]
    _MUMU_ISTANZE = []

# --- Colori tema ---
BG          = "#0d0f14"
BG_PANEL    = "#13161d"
BG_CARD     = "#1a1e28"
ACCENT      = "#e8a020"
ACCENT2     = "#c06010"
GREEN       = "#2ecc71"
RED         = "#e74c3c"
YELLOW      = "#f1c40f"
BLUE        = "#3498db"
TEXT        = "#dce3f0"
TEXT_DIM    = "#6b7590"
BORDER      = "#252a38"
LOG_BG      = "#0a0c10"
LOG_FG      = "#8fbc6a"
LOG_FG_ERR  = "#e74c3c"
LOG_FG_WARN = "#e8a020"
LOG_FG_INFO = "#5ba3d9"

# Stati istanza
ST_IDLE    = "idle"
ST_AVVIO   = "avvio"
ST_RUNNING = "running"
ST_DONE    = "done"
ST_ERROR   = "error"

ST_COLOR = {
    ST_IDLE:    TEXT_DIM,
    ST_AVVIO:   YELLOW,
    ST_RUNNING: GREEN,
    ST_DONE:    BLUE,
    ST_ERROR:   RED,
}
ST_LABEL = {
    ST_IDLE:    "○ inattiva",
    ST_AVVIO:   "◌ avvio...",
    ST_RUNNING: "● raccolta",
    ST_DONE:    "✓ completata",
    ST_ERROR:   "✗ errore",
}

# ─────────────────────────────────────────────────────────────────────────────

class DoomsdayLauncher(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("DOOMSDAY BOT V5  —  Control Panel")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(860, 620)

        self._bot_process  = None
        self._log_thread   = None
        self._running      = False
        self._chk_vars     = {}
        self._stato_lbl    = {}
        self._emu_var       = tk.StringVar(value="1")   # "1"=BlueStacks, "2"=MuMu
        self._istanze_lista = list(_BS_ISTANZE)          # lista attiva corrente
        self._istanze_stato = {n: ST_IDLE for n in self._istanze_lista}
        self._chk_frame_ref = None   # riferimento al frame checkbox per rebuild

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._scrivi_status()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=BG, pady=10)
        hdr.pack(fill="x", padx=18)
        tk.Label(hdr, text="☣  DOOMSDAY BOT", font=("Courier New", 18, "bold"),
                 bg=BG, fg=ACCENT).pack(side="left")
        tk.Label(hdr, text="V5", font=("Courier New", 11),
                 bg=BG, fg=ACCENT2).pack(side="left", padx=(6, 0), pady=4)
        self._status_lbl = tk.Label(hdr, text="● FERMO",
                                     font=("Courier New", 10, "bold"), bg=BG, fg=RED)
        self._status_lbl.pack(side="right")
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=18, pady=(0, 10))

        # Corpo
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=18, pady=(0, 10))
        body.columnconfigure(0, weight=0, minsize=240)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        # ── Pannello sinistro ──────────────────────────────────────────────
        left = tk.Frame(body, bg=BG_PANEL)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        # Sezione EMULATORE
        tk.Label(left, text="EMULATORE", font=("Courier New", 9, "bold"),
                 bg=BG_PANEL, fg=TEXT_DIM).pack(anchor="w", padx=14, pady=(14, 6))

        emu_frame = tk.Frame(left, bg=BG_CARD)
        emu_frame.pack(fill="x", padx=10, pady=(0, 4))
        for val, label in [("1", "BlueStacks"), ("2", "MuMuPlayer 12")]:
            tk.Radiobutton(emu_frame, text=f"  {label}", variable=self._emu_var,
                           value=val, font=("Courier New", 10),
                           bg=BG_CARD, fg=TEXT, selectcolor=BG_CARD,
                           activebackground=BG_CARD, activeforeground=ACCENT,
                           highlightthickness=0, cursor="hand2",
                           command=self._on_emu_change
                           ).pack(anchor="w", padx=10, pady=4)

        tk.Frame(left, bg=BORDER, height=1).pack(fill="x", padx=10, pady=10)

        # Sezione ISTANZE
        tk.Label(left, text="ISTANZE", font=("Courier New", 9, "bold"),
                 bg=BG_PANEL, fg=TEXT_DIM).pack(anchor="w", padx=14, pady=(0, 6))

        chk_frame = tk.Frame(left, bg=BG_PANEL)
        chk_frame.pack(fill="x", padx=10)
        self._chk_frame_ref = chk_frame

        self._build_chk_frame(chk_frame)

        # Sel tutto / desel
        btn_row = tk.Frame(left, bg=BG_PANEL)
        btn_row.pack(fill="x", padx=10, pady=(6, 0))
        tk.Button(btn_row, text="Tutte", command=self._select_all,
                  bg=BG_CARD, fg=TEXT_DIM, relief="flat",
                  font=("Courier New", 8), cursor="hand2"
                  ).pack(side="left", padx=(0, 4))
        tk.Button(btn_row, text="Nessuna", command=self._deselect_all,
                  bg=BG_CARD, fg=TEXT_DIM, relief="flat",
                  font=("Courier New", 8), cursor="hand2"
                  ).pack(side="left")

        tk.Frame(left, bg=BORDER, height=1).pack(fill="x", padx=10, pady=12)

        # Pulsanti
        self._btn_start = tk.Button(left, text="▶  AVVIA", command=self._avvia,
                                     bg=ACCENT, fg="#000",
                                     font=("Courier New", 11, "bold"),
                                     relief="flat", cursor="hand2", pady=8,
                                     activebackground=ACCENT2, activeforeground="#000")
        self._btn_start.pack(fill="x", padx=10, pady=(0, 6))

        self._btn_stop = tk.Button(left, text="■  FERMA", command=self._ferma,
                                    bg=BG_CARD, fg=TEXT_DIM,
                                    font=("Courier New", 11, "bold"),
                                    relief="flat", cursor="hand2", pady=8,
                                    state="disabled", activebackground=RED,
                                    activeforeground="#fff")
        self._btn_stop.pack(fill="x", padx=10, pady=(0, 14))

        # ── Pannello destro: log ───────────────────────────────────────────
        right = tk.Frame(body, bg=BG_PANEL)
        right.grid(row=0, column=1, sticky="nsew")

        log_hdr = tk.Frame(right, bg=BG_PANEL)
        log_hdr.pack(fill="x", padx=14, pady=(14, 6))
        tk.Label(log_hdr, text="LOG IN TEMPO REALE",
                 font=("Courier New", 9, "bold"),
                 bg=BG_PANEL, fg=TEXT_DIM).pack(side="left")
        tk.Button(log_hdr, text="Pulisci", command=self._clear_log,
                  bg=BG_CARD, fg=TEXT_DIM, relief="flat",
                  font=("Courier New", 8), cursor="hand2").pack(side="right")

        self._log = scrolledtext.ScrolledText(
            right, bg=LOG_BG, fg=LOG_FG,
            font=("Courier New", 9), relief="flat",
            insertbackground=LOG_FG, wrap="word", state="disabled"
        )
        self._log.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._log.tag_config("err",  foreground=LOG_FG_ERR)
        self._log.tag_config("warn", foreground=LOG_FG_WARN)
        self._log.tag_config("info", foreground=LOG_FG_INFO)
        self._log.tag_config("ok",   foreground=GREEN)
        self._log.tag_config("dim",  foreground=TEXT_DIM)

    # ── Lista istanze dinamica ────────────────────────────────────────────────

    def _build_chk_frame(self, frame):
        """Popola il frame delle checkbox con le istanze della lista corrente."""
        for w in frame.winfo_children():
            w.destroy()
        self._chk_vars.clear()
        self._stato_lbl.clear()

        for nome in self._istanze_lista:
            var = tk.BooleanVar(value=True)
            self._chk_vars[nome] = var

            row = tk.Frame(frame, bg=BG_CARD, pady=3)
            row.pack(fill="x", pady=2)
            row.columnconfigure(0, weight=1)
            row.columnconfigure(1, weight=0)

            tk.Checkbutton(row, text=f"  {nome}", variable=var,
                           font=("Courier New", 10),
                           bg=BG_CARD, fg=TEXT, selectcolor=BG_CARD,
                           activebackground=BG_CARD, activeforeground=ACCENT,
                           highlightthickness=0, cursor="hand2"
                           ).grid(row=0, column=0, sticky="w", padx=6)

            lbl = tk.Label(row, text=ST_LABEL[ST_IDLE],
                           font=("Courier New", 8),
                           bg=BG_CARD, fg=ST_COLOR[ST_IDLE])
            lbl.grid(row=0, column=1, sticky="e", padx=6)
            self._stato_lbl[nome] = lbl

    def _on_emu_change(self):
        """Chiamato al cambio radio button: aggiorna lista istanze."""
        if self._running:
            return   # non cambiare durante esecuzione
        emu = self._emu_var.get()
        self._istanze_lista = list(_BS_ISTANZE if emu == "1" else _MUMU_ISTANZE)
        self._istanze_stato = {n: ST_IDLE for n in self._istanze_lista}
        if self._chk_frame_ref:
            self._build_chk_frame(self._chk_frame_ref)
        self._scrivi_status()

    # ── Selezione ─────────────────────────────────────────────────────────────

    def _select_all(self):
        for v in self._chk_vars.values(): v.set(True)

    def _deselect_all(self):
        for v in self._chk_vars.values(): v.set(False)

    def _istanze_selezionate(self):
        return [n for n, v in self._chk_vars.items() if v.get()]

    # ── Avvio ─────────────────────────────────────────────────────────────────

    def _avvia(self):
        selezionate = self._istanze_selezionate()
        if not selezionate:
            self._log_write("⚠  Nessuna istanza selezionata!\n", "warn")
            return

        emu = self._emu_var.get()
        emu_nome = "BlueStacks" if emu == "1" else "MuMuPlayer 12"
        exe_kill = "HD-Player.exe" if emu == "1" else "MuMuPlayer.exe"

        # Reset stati
        for n in self._istanze_lista:
            self._aggiorna_stato(n, ST_AVVIO if n in selezionate else ST_IDLE)

        # Chiudi emulatore residuo
        self._log_write(f"⟳  Chiusura {emu_nome} residuo...\n", "dim")
        try:
            subprocess.run(["taskkill", "/F", "/IM", exe_kill], capture_output=True)
            time.sleep(1.5)
            self._log_write(f"✓  {emu_nome} chiuso\n", "ok")
        except Exception as e:
            self._log_write(f"   (taskkill: {e})\n", "dim")

        istanze_arg = ",".join(selezionate)
        self._log_write(f"▶  Emulatore: {emu_nome} | Istanze: {istanze_arg}\n", "info")

        cmd = [PYTHON, "main.py", "--istanze", istanze_arg, "--emulatore", emu]
        try:
            self._bot_process = subprocess.Popen(
                cmd, cwd=BOT_DIR,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
        except Exception as e:
            self._log_write(f"✗  Errore avvio: {e}\n", "err")
            return

        self._running = True
        self._set_stato_running(True)
        self._log_thread = threading.Thread(target=self._leggi_log, daemon=True)
        self._log_thread.start()

    # ── Stop ──────────────────────────────────────────────────────────────────

    def _ferma(self):
        if self._bot_process and self._bot_process.poll() is None:
            self._log_write("■  Interruzione bot in corso...\n", "warn")
            try:
                if sys.platform == "win32":
                    self._bot_process.send_signal(signal.CTRL_C_EVENT)
                else:
                    self._bot_process.terminate()
                self._bot_process.wait(timeout=8)
            except Exception:
                try: self._bot_process.kill()
                except Exception: pass
            self._log_write("✓  Bot fermato\n", "ok")
        self._running = False
        self._set_stato_running(False)
        for n in self._istanze_lista:
            self._aggiorna_stato(n, ST_IDLE)

    # ── Log reader ────────────────────────────────────────────────────────────

    def _leggi_log(self):
        try:
            for line in self._bot_process.stdout:
                tag = self._tag_per_riga(line)
                self.after(0, self._log_write, line, tag)
                self.after(0, self._parse_stato_da_log, line)
        except Exception:
            pass
        self.after(0, self._bot_terminato)

    def _parse_stato_da_log(self, line: str):
        import re
        m = re.match(r"\[[\d:]+\] \[(FAU_\d+)\] (.+)", line)
        if not m:
            return
        nome, msg = m.group(1), m.group(2).lower()
        if nome not in self._istanze_lista:
            return
        if any(w in msg for w in ["avvio bluestacks", "avvio mumu", "avviato (pid"]):
            self._aggiorna_stato(nome, ST_AVVIO)
        elif "inizio raccolta risorse" in msg:
            self._aggiorna_stato(nome, ST_RUNNING)
        elif "slot rilasciato" in msg:
            self._aggiorna_stato(nome, ST_DONE)
        elif any(w in msg for w in ["errore", "avvio fallito", "watchdog"]):
            self._aggiorna_stato(nome, ST_ERROR)

    def _tag_per_riga(self, line):
        l = line.lower()
        if any(w in l for w in ["errore", "error", "✗", "exception", "traceback"]):
            return "err"
        if any(w in l for w in ["warn", "⚠", "blacklist", "retry", "non leggibili"]):
            return "warn"
        if any(w in l for w in ["avviato", "connesso", "pronto", "completat", "✓"]):
            return "ok"
        if any(w in l for w in ["ciclo", "[main]", "timing", "inizio"]):
            return "info"
        return None

    def _bot_terminato(self):
        self._running = False
        self._set_stato_running(False)
        self._log_write("── Bot terminato ──\n", "dim")
        for n in self._istanze_lista:
            if self._istanze_stato[n] not in (ST_IDLE, ST_DONE, ST_ERROR):
                self._aggiorna_stato(n, ST_IDLE)

    # ── Stato istanze ─────────────────────────────────────────────────────────

    def _aggiorna_stato(self, nome: str, stato: str):
        self._istanze_stato[nome] = stato
        lbl = self._stato_lbl.get(nome)
        if lbl:
            lbl.config(text=ST_LABEL[stato], fg=ST_COLOR[stato])
        self._scrivi_status()

    def _scrivi_status(self):
        try:
            data = {
                "bot_running": self._running,
                "emulatore":   "BlueStacks" if self._emu_var.get() == "1" else "MuMuPlayer 12",
                "aggiornato":  datetime.now().strftime("%H:%M:%S"),
                "istanze": {
                    n: {
                        "stato":  self._istanze_stato[n],
                        "label":  ST_LABEL[self._istanze_stato[n]],
                        "attiva": self._chk_vars[n].get() if n in self._chk_vars else False,
                    }
                    for n in self._istanze_lista
                }
            }
            with open(STATUS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    # ── Helpers UI ────────────────────────────────────────────────────────────

    def _set_stato_running(self, running: bool):
        if running:
            self._status_lbl.config(text="● IN ESECUZIONE", fg=GREEN)
            self._btn_start.config(state="disabled", bg=BG_CARD, fg=TEXT_DIM)
            self._btn_stop.config(state="normal", bg=RED, fg="#fff")
        else:
            self._status_lbl.config(text="● FERMO", fg=RED)
            self._btn_start.config(state="normal", bg=ACCENT, fg="#000")
            self._btn_stop.config(state="disabled", bg=BG_CARD, fg=TEXT_DIM)
        self._scrivi_status()

    def _log_write(self, text: str, tag: str = None):
        self._log.config(state="normal")
        if tag:
            self._log.insert("end", text, tag)
        else:
            self._log.insert("end", text)
        self._log.see("end")
        self._log.config(state="disabled")

    def _clear_log(self):
        self._log.config(state="normal")
        self._log.delete("1.0", "end")
        self._log.config(state="disabled")

    def _on_close(self):
        if self._running:
            self._ferma()
        self.destroy()


if __name__ == "__main__":
    app = DoomsdayLauncher()
    app.mainloop()