# ==============================================================================
#  DOOMSDAY BOT V5 - log.py
#  Logging su file + console - si resetta ad ogni avvio
#
#  V5.1 - Aggiornamenti diagnostici:
#    - Log separato per istanza: debug/ciclo_NNN/FAU_XX.log
#    - Raccolta eventi strutturati per report HTML a fine ciclo
#    - logger_istanza(nome, msg) scrive su bot.log + FAU_XX.log del ciclo
#    - registra_evento() accumula statistiche per report
# ==============================================================================

import os
import threading
from datetime import datetime
import config

_lock      = threading.Lock()
_log_path  = os.path.join(config.BOT_DIR, "bot.log")

# --- Log separati per istanza: { nome: file_handle } ---
_istanza_logs  = {}
_istanza_lock  = threading.Lock()

# --- Raccolta eventi strutturati per report ---
# Lista di dict: { ciclo, nome, evento, squadra, tentativo, ts, dettaglio }
_eventi        = []
_eventi_lock   = threading.Lock()

# ------------------------------------------------------------------------------
# Init: cancella bot.log, chiude log istanze precedenti, svuota eventi
# ------------------------------------------------------------------------------
def init():
    """Cancella il log principale e resetta strutture diagnostiche. Chiamato una volta all'avvio."""
    global _istanza_logs, _eventi
    with _lock:
        with open(_log_path, "w", encoding="utf-8") as f:
            f.write(f"{'='*55}\n")
            f.write(f"  DOOMSDAY BOT V5 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"{'='*55}\n")
    with _istanza_lock:
        for fh in _istanza_logs.values():
            try: fh.close()
            except: pass
        _istanza_logs = {}
    with _eventi_lock:
        _eventi = []

# ------------------------------------------------------------------------------
# Init ciclo: apre log istanza per ogni istanza del ciclo
# Chiamato da main.py all'inizio di ogni ciclo, dopo debug.init_ciclo()
# ------------------------------------------------------------------------------
def init_ciclo(ciclo_dir: str, nomi_istanze: list):
    """Apre/ricrea i file .log per istanza nella cartella del ciclo."""
    with _istanza_lock:
        # Chiudi log del ciclo precedente
        for fh in _istanza_logs.values():
            try: fh.close()
            except: pass
        _istanza_logs.clear()

        if not ciclo_dir:
            return

        for nome in nomi_istanze:
            path = os.path.join(ciclo_dir, f"{nome}.log")
            try:
                fh = open(path, "w", encoding="utf-8")
                fh.write(f"{'='*50}\n")
                fh.write(f"  {nome} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                fh.write(f"{'='*50}\n")
                fh.flush()
                _istanza_logs[nome] = fh
            except Exception:
                pass

# ------------------------------------------------------------------------------
# Logger principale (bot.log + console + log istanza se disponibile)
# ------------------------------------------------------------------------------
def logger(nome: str, msg: str):
    """Stampa a video, scrive su bot.log e (se aperto) sul log dell'istanza."""
    ts   = datetime.now().strftime("%H:%M:%S")
    riga = f"[{ts}] [{nome}] {msg}"
    print(riga)

    with _lock:
        try:
            with open(_log_path, "a", encoding="utf-8") as f:
                f.write(riga + "\n")
        except Exception:
            pass

    # Scrivi anche sul log istanza (se aperto per questo ciclo)
    with _istanza_lock:
        fh = _istanza_logs.get(nome)
        if fh:
            try:
                fh.write(riga + "\n")
                fh.flush()
            except Exception:
                pass

# ------------------------------------------------------------------------------
# Registra evento strutturato per il report HTML
#
# evento:    "ocr_fail" | "cnt_errato" | "squadra_ok" | "squadra_abbandonata" |
#            "reset" | "timeout" | "completata"
# dettaglio: stringa libera (es. "atteso=3 letto=1", "inviate=3/4")
# ------------------------------------------------------------------------------
def registra_evento(ciclo: int, nome: str, evento: str,
                    squadra: int = 0, tentativo: int = 0, dettaglio: str = ""):
    ts = datetime.now().strftime("%H:%M:%S")
    with _eventi_lock:
        _eventi.append({
            "ciclo":     ciclo,
            "nome":      nome,
            "evento":    evento,
            "squadra":   squadra,
            "tentativo": tentativo,
            "ts":        ts,
            "dettaglio": dettaglio,
        })

# ------------------------------------------------------------------------------
# Restituisce copia degli eventi (per report)
# ------------------------------------------------------------------------------
def get_eventi(ciclo: int = None) -> list:
    with _eventi_lock:
        if ciclo is None:
            return list(_eventi)
        return [e for e in _eventi if e["ciclo"] == ciclo]

# ------------------------------------------------------------------------------
# Chiudi log istanze a fine ciclo
# ------------------------------------------------------------------------------
def chiudi_ciclo():
    with _istanza_lock:
        for fh in _istanza_logs.values():
            try: fh.close()
            except: pass
        _istanza_logs.clear()