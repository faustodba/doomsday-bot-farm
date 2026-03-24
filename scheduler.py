# ==============================================================================
#  DOOMSDAY BOT V5 - scheduler.py
#  Gestione esecuzione schedulata per task periodici per istanza
#
#  V5.17.1: File stato unificato per istanza
#    File: istanza_stato_{nome}_{porta}.json
#    Struttura:
#      {
#        "schedule": {
#          "messaggi": {"ultimo_ts": "2026-03-18T12:00:00"},
#          "alleanza":  {"ultimo_ts": "2026-03-18T12:00:00"},
#          "vip":       {"ultimo_ts": "2026-03-18T12:00:00"}
#        },
#        "rifornimento": {
#          "quota_esaurita": false,
#          "ultimo_reset_utc": "..."
#        },
#        "daily_tasks": {
#          "vip_claimed": false,
#          "ultimo_reset_utc": "..."
#        }
#      }
#
#  Retrocompatibilità: se esiste il vecchio schedule_stato_*.json lo migra
#  automaticamente nel nuovo file unificato e rimuove il vecchio.
#
#  API pubblica (invariata):
#    deve_eseguire(nome, porta, task, logger)  → bool
#    registra_esecuzione(nome, porta, task)    → None
#    ore_alla_prossima(nome, porta, task)      → float
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
    "vip":       24,
    "radar":     12,
    "zaino":    168,  # 7 giorni — settimanale
}

_TS_FMT = "%Y-%m-%dT%H:%M:%S"


# ------------------------------------------------------------------------------
# Path file stato unificato
# ------------------------------------------------------------------------------

def _safe_id(val: str) -> str:
    s = re.sub(r'[^A-Za-z0-9_-]+', '_', str(val)).strip('_')
    return s or 'noid'


def path_stato_istanza(nome: str, porta: str) -> str:
    """Path file stato unificato per istanza."""
    return os.path.join(
        config.BOT_DIR,
        f"istanza_stato_{_safe_id(nome)}_{_safe_id(porta)}.json"
    )


def _path_vecchio_schedule(nome: str, porta: str) -> str:
    return os.path.join(
        config.BOT_DIR,
        f"schedule_stato_{_safe_id(nome)}_{_safe_id(porta)}.json"
    )


# ------------------------------------------------------------------------------
# Carica / salva stato unificato
# ------------------------------------------------------------------------------

def _carica_stato(nome: str, porta: str) -> dict:
    """
    Carica il file stato unificato.
    Se non esiste prova a migrare dal vecchio schedule_stato_*.json.
    """
    path = path_stato_istanza(nome, porta)

    # Prova a caricare il file unificato
    try:
        with open(path, 'r', encoding='utf-8') as f:
            dati = json.load(f)
        # Garantisce struttura minima
        dati.setdefault("schedule", {})
        dati.setdefault("rifornimento", {})
        dati.setdefault("daily_tasks", {})
        return dati
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[SCHEDULER] WARN carica_stato {nome}: {e} — uso default")

    # Migrazione dal vecchio file schedule_stato_*.json
    stato = {"schedule": {}, "rifornimento": {}, "daily_tasks": {}}
    path_vecchio = _path_vecchio_schedule(nome, porta)
    try:
        with open(path_vecchio, 'r', encoding='utf-8') as f:
            vecchio = json.load(f)
        stato["schedule"] = vecchio
        print(f"[SCHEDULER] Migrato {os.path.basename(path_vecchio)} → {os.path.basename(path)}")
        _salva_stato(nome, porta, stato)
        # Rimuovi vecchio file
        try:
            os.remove(path_vecchio)
        except Exception:
            pass
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[SCHEDULER] WARN migrazione {nome}: {e}")

    return stato


def _salva_stato(nome: str, porta: str, stato: dict) -> None:
    path = path_stato_istanza(nome, porta)
    tmp  = path + ".tmp"
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(stato, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        print(f"[SCHEDULER] ERRORE salva_stato {nome}: {e}")


# ------------------------------------------------------------------------------
# API pubblica — schedulazione task periodici
# ------------------------------------------------------------------------------

def _ore_intervallo(task: str) -> float:
    chiave = f"SCHEDULE_ORE_{task.upper()}"
    return float(getattr(config, chiave, _DEFAULT_ORE.get(task, 12)))


def deve_eseguire(nome: str, porta: str, task: str, logger=None) -> bool:
    """
    Verifica se il task deve essere eseguito per questa istanza.
    Ritorna True se mai eseguito o se l'intervallo è scaduto.
    """
    def log(msg):
        if logger: logger(nome, msg)

    ore   = _ore_intervallo(task)
    stato = _carica_stato(nome, porta)
    ultimo_ts_str = stato.get("schedule", {}).get(task, {}).get("ultimo_ts", "")

    if not ultimo_ts_str:
        log(f"[SCHED] {task}: prima esecuzione — procedo")
        return True

    try:
        ultimo_ts = datetime.strptime(ultimo_ts_str, _TS_FMT)
    except ValueError:
        log(f"[SCHED] {task}: timestamp corrotto '{ultimo_ts_str}' — procedo per sicurezza")
        return True

    prossima     = ultimo_ts + timedelta(hours=ore)
    ora_corrente = datetime.now()

    if ora_corrente >= prossima:
        log(f"[SCHED] {task}: intervallo {ore}h scaduto (ultima: {ultimo_ts_str}) — procedo")
        return True
    else:
        manca     = prossima - ora_corrente
        ore_manca = int(manca.total_seconds() // 3600)
        min_manca = int((manca.total_seconds() % 3600) // 60)
        log(f"[SCHED] {task}: già eseguito — skip (prossima tra {ore_manca}h {min_manca:02d}m)")
        return False


def registra_esecuzione(nome: str, porta: str, task: str) -> None:
    """Registra il timestamp dell'esecuzione appena completata."""
    stato = _carica_stato(nome, porta)
    stato.setdefault("schedule", {})
    stato["schedule"].setdefault(task, {})
    stato["schedule"][task]["ultimo_ts"] = datetime.now().strftime(_TS_FMT)
    _salva_stato(nome, porta, stato)


def ore_alla_prossima(nome: str, porta: str, task: str) -> float:
    """Ritorna le ore mancanti alla prossima esecuzione. 0.0 se già scaduto."""
    ore   = _ore_intervallo(task)
    stato = _carica_stato(nome, porta)
    ultimo_ts_str = stato.get("schedule", {}).get(task, {}).get("ultimo_ts", "")
    if not ultimo_ts_str:
        return 0.0
    try:
        ultimo_ts = datetime.strptime(ultimo_ts_str, _TS_FMT)
        prossima  = ultimo_ts + timedelta(hours=ore)
        manca     = (prossima - datetime.now()).total_seconds()
        return max(0.0, manca / 3600)
    except ValueError:
        return 0.0


# ------------------------------------------------------------------------------
# API pubblica — sezione rifornimento (usata da rifornimento.py)
# ------------------------------------------------------------------------------

def carica_sezione(nome: str, porta: str, sezione: str) -> dict:
    """Ritorna la sezione specificata dallo stato unificato."""
    stato = _carica_stato(nome, porta)
    return stato.get(sezione, {})


def salva_sezione(nome: str, porta: str, sezione: str, dati: dict) -> None:
    """Aggiorna una sezione dello stato unificato senza toccare le altre."""
    stato = _carica_stato(nome, porta)
    stato[sezione] = dati
    _salva_stato(nome, porta, stato)
