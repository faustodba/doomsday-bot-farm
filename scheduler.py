# ==============================================================================
#  DOOMSDAY BOT V5 - scheduler.py
#  Gestione esecuzione schedulata per task periodici per istanza
#
#  Gestisce:
#    - messaggi : raccolta ricompense messaggi (ogni SCHEDULE_ORE_MESSAGGI ore)
#    - alleanza : raccolta ricompense alleanza (ogni SCHEDULE_ORE_ALLEANZA ore)
#
#  Logica:
#    - Ogni istanza ha un file stato separato: schedule_stato_{nome}_{porta}.json
#    - Per ogni task: confronta datetime.now() con ultimo_ts + intervallo_ore
#    - Se file non esiste (prima esecuzione): esegue sempre
#    - Se già eseguito meno di N ore fa: salta e logga tempo rimanente
#
#  API pubblica:
#    deve_eseguire(nome, porta, task, logger)  → bool
#    registra_esecuzione(nome, porta, task)    → None
#
#  Task supportati: "messaggi", "alleanza"
#  Intervalli configurabili in config.py:
#    SCHEDULE_ORE_MESSAGGI = 12
#    SCHEDULE_ORE_ALLEANZA = 12
# ==============================================================================

import json
import os
import re
from datetime import datetime, timedelta
import config

# Intervalli default se non presenti in config
_DEFAULT_ORE = {
    "messaggi": 12,
    "alleanza":  12,
}

# Formato timestamp nel file stato
_TS_FMT = "%Y-%m-%dT%H:%M:%S"


# ------------------------------------------------------------------------------
# Helpers interni
# ------------------------------------------------------------------------------

def _safe_id(val: str) -> str:
    """Normalizza stringa per uso in filename."""
    s = re.sub(r'[^A-Za-z0-9_-]+', '_', str(val)).strip('_')
    return s or 'noid'


def _path_stato(nome: str, porta: str) -> str:
    """Path file stato schedulazione per istanza."""
    return os.path.join(
        config.BOT_DIR,
        f"schedule_stato_{_safe_id(nome)}_{_safe_id(porta)}.json"
    )


def _ore_intervallo(task: str) -> float:
    """Ritorna l'intervallo in ore per il task dal config, con fallback al default."""
    chiave = f"SCHEDULE_ORE_{task.upper()}"
    return float(getattr(config, chiave, _DEFAULT_ORE.get(task, 12)))


def _carica_stato(nome: str, porta: str) -> dict:
    """Legge il file stato. Se non esiste o corrotto ritorna dict vuoto."""
    path = _path_stato(nome, porta)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"[SCHEDULER] WARN _carica_stato {nome}: {e} — uso default")
        return {}


def _salva_stato(nome: str, porta: str, stato: dict) -> None:
    """Scrive il file stato in modo atomico."""
    path = _path_stato(nome, porta)
    tmp  = path + ".tmp"
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(stato, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        print(f"[SCHEDULER] ERRORE _salva_stato {nome}: {e}")


# ------------------------------------------------------------------------------
# API pubblica
# ------------------------------------------------------------------------------

def deve_eseguire(nome: str, porta: str, task: str, logger=None) -> bool:
    """
    Verifica se il task deve essere eseguito per questa istanza.

    Ritorna True se:
      - File stato non esiste (prima esecuzione assoluta)
      - Task non presente nel file (mai eseguito)
      - Sono trascorse >= N ore dall'ultima esecuzione

    Ritorna False se il task è stato eseguito meno di N ore fa.
    In questo caso logga il tempo rimanente alla prossima esecuzione.
    """
    def log(msg):
        if logger: logger(nome, msg)

    ore = _ore_intervallo(task)
    stato = _carica_stato(nome, porta)

    ultimo_ts_str = stato.get(task, {}).get("ultimo_ts", "")
    if not ultimo_ts_str:
        # Mai eseguito — procedi sempre
        log(f"[SCHED] {task}: prima esecuzione — procedo")
        return True

    try:
        ultimo_ts = datetime.strptime(ultimo_ts_str, _TS_FMT)
    except ValueError:
        log(f"[SCHED] {task}: timestamp corrotto '{ultimo_ts_str}' — procedo per sicurezza")
        return True

    prossima = ultimo_ts + timedelta(hours=ore)
    ora_corrente = datetime.now()

    if ora_corrente >= prossima:
        log(f"[SCHED] {task}: intervallo {ore}h scaduto (ultima: {ultimo_ts_str}) — procedo")
        return True
    else:
        manca = prossima - ora_corrente
        ore_manca  = int(manca.total_seconds() // 3600)
        min_manca  = int((manca.total_seconds() % 3600) // 60)
        log(f"[SCHED] {task}: già eseguito — skip (prossima tra {ore_manca}h {min_manca:02d}m)")
        return False


def registra_esecuzione(nome: str, porta: str, task: str) -> None:
    """
    Registra il timestamp dell'esecuzione appena completata per il task.
    Chiamare subito dopo l'esecuzione riuscita del task.
    """
    stato = _carica_stato(nome, porta)
    if task not in stato:
        stato[task] = {}
    stato[task]["ultimo_ts"] = datetime.now().strftime(_TS_FMT)
    _salva_stato(nome, porta, stato)


def ore_alla_prossima(nome: str, porta: str, task: str) -> float:
    """
    Ritorna le ore mancanti alla prossima esecuzione del task.
    Ritorna 0.0 se il task deve già essere eseguito.
    Utile per logging e dashboard futura.
    """
    ore = _ore_intervallo(task)
    stato = _carica_stato(nome, porta)
    ultimo_ts_str = stato.get(task, {}).get("ultimo_ts", "")
    if not ultimo_ts_str:
        return 0.0
    try:
        ultimo_ts = datetime.strptime(ultimo_ts_str, _TS_FMT)
        prossima  = ultimo_ts + timedelta(hours=ore)
        manca     = (prossima - datetime.now()).total_seconds()
        return max(0.0, manca / 3600)
    except ValueError:
        return 0.0