# ==============================================================================
#  DOOMSDAY BOT V4 - timing.py
#  Stima adattativa del tempo di caricamento per istanza
#
#  ALGORITMO:
#  - EWMA (Exponentially Weighted Moving Average) con alpha=0.3
#    → dà peso maggiore alle misurazioni recenti, si adatta ai cambiamenti
#      graduali (BlueStacks più lento nel tempo, carico RAM, ecc.)
#
#  - Rilevamento outlier con z-score
#    → se una misurazione è > OUTLIER_ZSCORE deviazioni standard dalla media,
#      viene registrata ma ha peso ridotto (OUTLIER_ALPHA) nell'aggiornamento
#      EWMA. Evita che un ciclo anomalo (PC sotto carico) distorca la stima.
#
#  - Margine adattativo basato sulla varianza
#    → attesa_prossimo_ciclo = ewma - k × std_dev
#    → se l'istanza è stabile (bassa std_dev) il margine è piccolo
#    → se è erratica (alta std_dev) il margine è conservativo
#    → k = MARGIN_K (default 0.5): bilancia efficienza vs sicurezza
#
#  - Persistenza su JSON
#    → i dati sopravvivono ai riavvii del bot
#    → contiene: ewma, varianza, n_campioni, ultimi_10 (per debug/analisi)
#
#  FORMULA COMPLETA:
#    Se misurazione NON è outlier:
#      ewma_new = alpha × t_misurato + (1-alpha) × ewma_old
#      var_new  = (1-alpha) × (var_old + alpha × (t_misurato - ewma_old)²)
#    Se misurazione È outlier:
#      ewma_new = outlier_alpha × t_misurato + (1-outlier_alpha) × ewma_old
#      (la varianza si aggiorna comunque per tenere traccia della dispersione)
#
#    attesa = max(MIN_ATTESA, ewma - MARGIN_K × sqrt(var))
# ==============================================================================

import json
import math
import os
import threading
import config

# --- Parametri algoritmo ---
ALPHA          = 0.3    # peso misurazioni recenti in EWMA (0=ignora recente, 1=solo recente)
OUTLIER_ALPHA  = 0.05   # peso ridotto per outlier nell'aggiornamento EWMA
OUTLIER_ZSCORE = 2.5    # soglia z-score per classificare outlier
MARGIN_K       = 0.5    # moltiplicatore std_dev per margine adattativo
MIN_ATTESA     = 15     # secondi minimi di attesa (floor di sicurezza)
MAX_STORIA     = 10     # ultimi N campioni da conservare per analisi

_DATA_FILE = os.path.join(config.BOT_DIR, "timing.json")
_lock      = threading.Lock()

# Struttura dati per istanza:
# {
#   "ewma":       float,   stima corrente tempo di caricamento (secondi)
#   "varianza":   float,   varianza EWMA corrente
#   "n_campioni": int,     numero totale di misurazioni registrate
#   "storia":     list,    ultimi MAX_STORIA campioni [secondi]
# }

# ------------------------------------------------------------------------------
# Carica dati dal file JSON (o inizializza struttura vuota)
# ------------------------------------------------------------------------------
def _carica() -> dict:
    try:
        if os.path.exists(_DATA_FILE):
            with open(_DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

# ------------------------------------------------------------------------------
# Salva dati su file JSON
# ------------------------------------------------------------------------------
def _salva(dati: dict):
    try:
        with open(_DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(dati, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

# ------------------------------------------------------------------------------
# Restituisce l'attesa ottimale stimata per un'istanza (in secondi interi)
#
# Se non ci sono dati storici → ritorna config.DELAY_CARICA_INIZ (default)
# Se ci sono dati → ewma - k × std_dev, con floor a MIN_ATTESA
# ------------------------------------------------------------------------------
def attesa_ottimale(nome: str) -> int:
    with _lock:
        dati = _carica()

    if nome not in dati or dati[nome]["n_campioni"] < 2:
        # Nessun dato storico sufficiente → usa default
        return config.DELAY_CARICA_INIZ

    rec     = dati[nome]
    ewma    = rec["ewma"]
    std_dev = math.sqrt(max(0.0, rec["varianza"]))

    # attesa = ewma - margine adattativo
    # Il margine aumenta con la variabilità: istanza stabile → margine piccolo
    attesa = ewma - MARGIN_K * std_dev
    attesa = max(MIN_ATTESA, int(attesa))
    return attesa

# ------------------------------------------------------------------------------
# Registra una nuova misurazione del tempo di caricamento per un'istanza
#
# t_secondi: tempo tra avvio gioco e prima conferma popup (misurato da bluestacks.py)
# logger:    funzione di log opzionale
# ------------------------------------------------------------------------------
def registra(nome: str, t_secondi: float, logger=None):
    def log(msg):
        if logger: logger(nome, msg)

    with _lock:
        dati = _carica()

        if nome not in dati:
            # Prima misurazione: inizializza con il valore misurato
            dati[nome] = {
                "ewma":       t_secondi,
                "varianza":   0.0,
                "n_campioni": 1,
                "storia":     [round(t_secondi, 1)]
            }
            log(f"[TIMING] Prima misura: {t_secondi:.1f}s → ewma={t_secondi:.1f}s")
            _salva(dati)
            return

        rec      = dati[nome]
        ewma_old = rec["ewma"]
        var_old  = rec["varianza"]
        std_old  = math.sqrt(max(0.0, var_old))

        # --- Rilevamento outlier ---
        if std_old > 0:
            z_score = abs(t_secondi - ewma_old) / std_old
            is_outlier = z_score > OUTLIER_ZSCORE
        else:
            is_outlier = False

        # --- Aggiornamento EWMA ---
        alpha_eff = OUTLIER_ALPHA if is_outlier else ALPHA
        ewma_new  = alpha_eff * t_secondi + (1 - alpha_eff) * ewma_old

        # --- Aggiornamento varianza EWMA ---
        # Varianza online: V_new = (1-α) × (V_old + α × (x - ewma_old)²)
        var_new = (1 - ALPHA) * (var_old + ALPHA * (t_secondi - ewma_old) ** 2)

        # --- Aggiornamento storia ---
        storia = rec.get("storia", [])
        storia.append(round(t_secondi, 1))
        if len(storia) > MAX_STORIA:
            storia = storia[-MAX_STORIA:]

        dati[nome] = {
            "ewma":       round(ewma_new, 2),
            "varianza":   round(var_new, 4),
            "n_campioni": rec["n_campioni"] + 1,
            "storia":     storia
        }

        std_new    = math.sqrt(max(0.0, var_new))
        prossima   = max(MIN_ATTESA, int(ewma_new - MARGIN_K * std_new))
        outlier_tag = " [OUTLIER]" if is_outlier else ""

        log(f"[TIMING] t={t_secondi:.1f}s{outlier_tag} | "
            f"ewma={ewma_new:.1f}s | std={std_new:.1f}s | "
            f"prossima_attesa={prossima}s")

        _salva(dati)

# ------------------------------------------------------------------------------
# Stampa riepilogo timing di tutte le istanze (utile per debug/monitoraggio)
# ------------------------------------------------------------------------------
def riepilogo(logger=None):
    def log(msg):
        if logger: logger("TIMING", msg)

    with _lock:
        dati = _carica()

    if not dati:
        log("Nessun dato timing disponibile")
        return

    log("=== Riepilogo tempi di caricamento ===")
    for nome, rec in sorted(dati.items()):
        std    = math.sqrt(max(0.0, rec["varianza"]))
        attesa = max(MIN_ATTESA, int(rec["ewma"] - MARGIN_K * std))
        log(f"  {nome}: ewma={rec['ewma']:.1f}s | std={std:.1f}s | "
            f"campioni={rec['n_campioni']} | prossima_attesa={attesa}s | "
            f"storia={rec['storia']}")