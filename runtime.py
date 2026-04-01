# ==============================================================================
# DOOMSDAY BOT V5 - runtime.py
# Configurazione modificabile a runtime senza riavviare il bot.
# ==============================================================================

import json
import os
import threading
from datetime import datetime
import config

_lock = threading.Lock()
_PATH = os.path.join(config.BOT_DIR, "runtime.json")

# ------------------------------------------------------------------------------
# Utility fascia oraria
# ------------------------------------------------------------------------------
def _in_fascia(fascia: str) -> bool:
    """
    True se ora corrente è dentro la fascia "HH:MM-HH:MM".
    Fail-safe: fascia assente/malformata -> True (H24).
    """
    if not fascia or not isinstance(fascia, str):
        return True
    try:
        parti = fascia.strip().split("-")
        if len(parti) != 2:
            return True
        start, end = parti[0].strip(), parti[1].strip()
        now = datetime.now().strftime("%H:%M")
        if start < end:
            return start <= now < end
        return now >= start or now < end
    except Exception:
        return True

# ------------------------------------------------------------------------------
# Struttura default runtime.json
# ------------------------------------------------------------------------------
def _default() -> dict:
    return {
        "_nota": "Modificabile a runtime — riletto ogni ciclo. Le istanze vengono sempre lette da config.py.",
        "globali": {
            "ISTANZE_BLOCCO": getattr(config, "ISTANZE_BLOCCO", 1),
            "WAIT_MINUTI": getattr(config, "WAIT_MINUTI", 1),
            "ALLEANZA_ABILITATA": getattr(config, "ALLEANZA_ABILITATA", True),
            "MESSAGGI_ABILITATI": getattr(config, "MESSAGGI_ABILITATI", True),
            "DAILY_VIP_ABILITATO": getattr(config, "DAILY_VIP_ABILITATO", True),
            "DAILY_RADAR_ABILITATO": getattr(config, "DAILY_RADAR_ABILITATO", True),
            "RADAR_CENSUS_ABILITATO": getattr(config, "RADAR_CENSUS_ABILITATO", False),
            "ZAINO_ABILITATO": getattr(config, "ZAINO_ABILITATO", False),
            "ZAINO_USA_POMODORO": getattr(config, "ZAINO_USA_POMODORO", True),
            "ZAINO_USA_LEGNO":    getattr(config, "ZAINO_USA_LEGNO",    True),
            "ZAINO_USA_ACCIAIO":  getattr(config, "ZAINO_USA_ACCIAIO",  False),
            "ZAINO_USA_PETROLIO": getattr(config, "ZAINO_USA_PETROLIO", True),
            "ZAINO_SOGLIA_POMODORO_M": getattr(config, "ZAINO_SOGLIA_POMODORO_M", 10.0),
            "ZAINO_SOGLIA_LEGNO_M":    getattr(config, "ZAINO_SOGLIA_LEGNO_M",    10.0),
            "ZAINO_SOGLIA_ACCIAIO_M":  getattr(config, "ZAINO_SOGLIA_ACCIAIO_M",   7.0),
            "ZAINO_SOGLIA_PETROLIO_M": getattr(config, "ZAINO_SOGLIA_PETROLIO_M",  5.0),
            "ARENA_OF_GLORY_ABILITATO": getattr(config, "ARENA_OF_GLORY_ABILITATO", False),
            "ARENA_MERCATO_ABILITATO":  getattr(config, "ARENA_MERCATO_ABILITATO",  False),
            "RIFORNIMENTO_ABILITATO": getattr(config, "RIFORNIMENTO_ABILITATO", True),
            "RIFORNIMENTO_MAPPA_ABILITATO": getattr(config, "RIFORNIMENTO_MAPPA_ABILITATO", False),
            "RIFORNIMENTO_MAX_SPEDIZIONI_CICLO": getattr(config, "RIFORNIMENTO_MAX_SPEDIZIONI_CICLO", 5),
            "RIFORNIMENTO_SOGLIA_CAMPO_M": getattr(config, "RIFORNIMENTO_SOGLIA_CAMPO_M", 5.0),
            "RIFORNIMENTO_SOGLIA_LEGNO_M": getattr(config, "RIFORNIMENTO_SOGLIA_LEGNO_M", 5.0),
            "RIFORNIMENTO_SOGLIA_PETROLIO_M": getattr(config, "RIFORNIMENTO_SOGLIA_PETROLIO_M", 2.5),
            "RIFORNIMENTO_SOGLIA_ACCIAIO_M": getattr(config, "RIFORNIMENTO_SOGLIA_ACCIAIO_M", 3.5),
            "RIFORNIMENTO_CAMPO_ABILITATO":    getattr(config, "RIFORNIMENTO_CAMPO_ABILITATO",    True),
            "RIFORNIMENTO_LEGNO_ABILITATO":    getattr(config, "RIFORNIMENTO_LEGNO_ABILITATO",    True),
            "RIFORNIMENTO_PETROLIO_ABILITATO": getattr(config, "RIFORNIMENTO_PETROLIO_ABILITATO", True),
            "RIFORNIMENTO_ACCIAIO_ABILITATO":  getattr(config, "RIFORNIMENTO_ACCIAIO_ABILITATO",  False),
            "ALLOCATION_RATIO": {
                "campo": 0.3750,
                "segheria": 0.3750,
                "petrolio": 0.1875,
                "acciaio": 0.0625,
            },
        },
        "overrides": {"bs": {}, "mumu": {}},
    }

# ------------------------------------------------------------------------------
# Inizializza / migra runtime.json
# ------------------------------------------------------------------------------
def inizializza_se_mancante():
    with _lock:
        if not os.path.exists(_PATH):
            _scrivi_raw(_default())
            print(f"[RUNTIME] runtime.json creato → {_PATH}")
            return
        try:
            with open(_PATH, "r", encoding="utf-8") as f:
                esistente = json.load(f)
        except Exception as e:
            print(f"[RUNTIME] WARN: errore lettura, ricreo da zero: {e}")
            _scrivi_raw(_default())
            return

        # Migrazione vecchia struttura (istanze_bs/istanze_mumu)
        if "istanze_bs" in esistente or "istanze_mumu" in esistente:
            print("[RUNTIME] Struttura vecchia rilevata — migrazione...")
            nuovo = _default()
            for k, v in esistente.get("globali", {}).items():
                if k in nuovo["globali"]:
                    nuovo["globali"][k] = v
            _scrivi_raw(nuovo)
            print("[RUNTIME] Migrazione completata.")
            return

        # Struttura nuova: aggiungi chiavi globali mancanti
        default = _default()
        aggiornato = False
        for k, v in default["globali"].items():
            if k not in esistente.get("globali", {}):
                esistente.setdefault("globali", {})[k] = v
                aggiornato = True
        ovr = esistente.setdefault("overrides", {})
        if "bs" not in ovr:
            ovr["bs"] = {}
            aggiornato = True
        if "mumu" not in ovr:
            ovr["mumu"] = {}
            aggiornato = True
        if aggiornato:
            _scrivi_raw(esistente)
            print("[RUNTIME] runtime.json aggiornato con nuove chiavi")

# ------------------------------------------------------------------------------
# Carica runtime.json
# ------------------------------------------------------------------------------
def carica() -> dict:
    with _lock:
        try:
            with open(_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            d = _default()
            _scrivi_raw(d)
            return d
        except Exception as e:
            print(f"[RUNTIME] WARN carica(): {e} — uso default")
            return _default()

# ------------------------------------------------------------------------------
# Applica globali su config.*
# ------------------------------------------------------------------------------
def applica(rt: dict):
    g = rt.get("globali", {})
    if "ISTANZE_BLOCCO" in g:
        config.ISTANZE_BLOCCO = int(g["ISTANZE_BLOCCO"])
    if "WAIT_MINUTI" in g:
        config.WAIT_MINUTI = int(g["WAIT_MINUTI"])
    if "ALLEANZA_ABILITATA" in g:
        config.ALLEANZA_ABILITATA = bool(g["ALLEANZA_ABILITATA"])
    if "MESSAGGI_ABILITATI" in g:
        config.MESSAGGI_ABILITATI = bool(g["MESSAGGI_ABILITATI"])
    if "DAILY_VIP_ABILITATO" in g:
        config.DAILY_VIP_ABILITATO = bool(g["DAILY_VIP_ABILITATO"])
    if "DAILY_RADAR_ABILITATO" in g:
        config.DAILY_RADAR_ABILITATO = bool(g["DAILY_RADAR_ABILITATO"])
    if "RADAR_CENSUS_ABILITATO" in g:
        config.RADAR_CENSUS_ABILITATO = bool(g["RADAR_CENSUS_ABILITATO"])
    if "ZAINO_ABILITATO" in g:
        config.ZAINO_ABILITATO = bool(g["ZAINO_ABILITATO"])
    if "ZAINO_USA_POMODORO" in g:
        config.ZAINO_USA_POMODORO = bool(g["ZAINO_USA_POMODORO"])
    if "ZAINO_USA_LEGNO" in g:
        config.ZAINO_USA_LEGNO = bool(g["ZAINO_USA_LEGNO"])
    if "ZAINO_USA_ACCIAIO" in g:
        config.ZAINO_USA_ACCIAIO = bool(g["ZAINO_USA_ACCIAIO"])
    if "ZAINO_USA_PETROLIO" in g:
        config.ZAINO_USA_PETROLIO = bool(g["ZAINO_USA_PETROLIO"])
    if "ZAINO_SOGLIA_POMODORO_M" in g:
        config.ZAINO_SOGLIA_POMODORO_M = float(g["ZAINO_SOGLIA_POMODORO_M"])
    if "ZAINO_SOGLIA_LEGNO_M" in g:
        config.ZAINO_SOGLIA_LEGNO_M = float(g["ZAINO_SOGLIA_LEGNO_M"])
    if "ZAINO_SOGLIA_ACCIAIO_M" in g:
        config.ZAINO_SOGLIA_ACCIAIO_M = float(g["ZAINO_SOGLIA_ACCIAIO_M"])
    if "ZAINO_SOGLIA_PETROLIO_M" in g:
        config.ZAINO_SOGLIA_PETROLIO_M = float(g["ZAINO_SOGLIA_PETROLIO_M"])
    if "ARENA_OF_GLORY_ABILITATO" in g:
        config.ARENA_OF_GLORY_ABILITATO = bool(g["ARENA_OF_GLORY_ABILITATO"])
    if "ARENA_MERCATO_ABILITATO" in g:
        config.ARENA_MERCATO_ABILITATO = bool(g["ARENA_MERCATO_ABILITATO"])
    if "RIFORNIMENTO_ABILITATO" in g:
        config.RIFORNIMENTO_ABILITATO = bool(g["RIFORNIMENTO_ABILITATO"])
    if "RIFORNIMENTO_MAPPA_ABILITATO" in g:
        config.RIFORNIMENTO_MAPPA_ABILITATO = bool(g["RIFORNIMENTO_MAPPA_ABILITATO"])
    if "RIFORNIMENTO_MAX_SPEDIZIONI_CICLO" in g:
        try:
            v = int(g["RIFORNIMENTO_MAX_SPEDIZIONI_CICLO"])
        except Exception:
            v = int(getattr(config, "RIFORNIMENTO_MAX_SPEDIZIONI_CICLO", 5))
        if v < 0: v = 0
        if v > 50: v = 50
        config.RIFORNIMENTO_MAX_SPEDIZIONI_CICLO = v
    if "RIFORNIMENTO_SOGLIA_CAMPO_M" in g:
        config.RIFORNIMENTO_SOGLIA_CAMPO_M = float(g["RIFORNIMENTO_SOGLIA_CAMPO_M"])
    if "RIFORNIMENTO_SOGLIA_LEGNO_M" in g:
        config.RIFORNIMENTO_SOGLIA_LEGNO_M = float(g["RIFORNIMENTO_SOGLIA_LEGNO_M"])
    if "RIFORNIMENTO_SOGLIA_PETROLIO_M" in g:
        config.RIFORNIMENTO_SOGLIA_PETROLIO_M = float(g["RIFORNIMENTO_SOGLIA_PETROLIO_M"])
    if "RIFORNIMENTO_SOGLIA_ACCIAIO_M" in g:
        config.RIFORNIMENTO_SOGLIA_ACCIAIO_M = float(g["RIFORNIMENTO_SOGLIA_ACCIAIO_M"])
    if "RIFORNIMENTO_CAMPO_ABILITATO" in g:
        config.RIFORNIMENTO_CAMPO_ABILITATO    = bool(g["RIFORNIMENTO_CAMPO_ABILITATO"])
    if "RIFORNIMENTO_LEGNO_ABILITATO" in g:
        config.RIFORNIMENTO_LEGNO_ABILITATO    = bool(g["RIFORNIMENTO_LEGNO_ABILITATO"])
    if "RIFORNIMENTO_PETROLIO_ABILITATO" in g:
        config.RIFORNIMENTO_PETROLIO_ABILITATO = bool(g["RIFORNIMENTO_PETROLIO_ABILITATO"])
    if "RIFORNIMENTO_ACCIAIO_ABILITATO" in g:
        config.RIFORNIMENTO_ACCIAIO_ABILITATO  = bool(g["RIFORNIMENTO_ACCIAIO_ABILITATO"])
    if "ALLOCATION_RATIO" in g:
        try:
            import allocation
            ratio = g["ALLOCATION_RATIO"]
            totale = sum(ratio.values())
            if totale > 0:
                allocation.RATIO_TARGET = {k: v / totale for k, v in ratio.items()}
        except Exception as e:
            print(f"[RUNTIME] WARN applica ALLOCATION_RATIO: {e}")

# ------------------------------------------------------------------------------
# Istanze attive da config + overrides
# ------------------------------------------------------------------------------
def istanze_attive(rt: dict, emulatore: str) -> list:
    if "BlueStacks" in emulatore:
        lista_config = getattr(config, "ISTANZE", [])
        ns = "bs"
    else:
        lista_config = getattr(config, "ISTANZE_MUMU", [])
        ns = "mumu"
    ovr_root = rt.get("overrides", {})
    overrides = ovr_root.get(ns, ovr_root if ("bs" not in ovr_root and "mumu" not in ovr_root) else {})
    risultato = []
    for ist in lista_config:
        nome = ist.get("nome", "")
        ovr = overrides.get(nome, {})
        abilitata = ovr.get("abilitata", ist.get("abilitata", True))
        if not abilitata:
            continue
        ist_out = dict(ist)
        for k in ("truppe", "max_squadre", "layout", "livello"):
            if k in ovr:
                ist_out[k] = int(ovr[k])
        for k in ("lingua", "fascia_oraria", "profilo"):
            if k in ovr:
                ist_out[k] = str(ovr[k])
        if "profilo" not in ist_out:
            ist_out["profilo"] = str(ist.get("profilo", "full"))
        fascia = ist_out.get("fascia_oraria", "")
        if fascia and not _in_fascia(fascia):
            continue
        if "BlueStacks" in emulatore:
            ist_out["porta"] = str(ist_out.get("porta", ""))
        else:
            ist_out["porta"] = int(ist_out.get("porta", 16384))
        risultato.append(ist_out)
    return risultato

# ------------------------------------------------------------------------------
# Salva runtime.json
# ------------------------------------------------------------------------------
def salva(dati: dict) -> bool:
    with _lock:
        return _scrivi_raw(dati)

def _scrivi_raw(dati: dict) -> bool:
    tmp = _PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dati, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _PATH)
        return True
    except Exception as e:
        print(f"[RUNTIME] ERRORE scrittura: {e}")
        return False

def ripristina_da_config() -> bool:
    esistente = carica()
    nuovo = _default()
    nuovo["overrides"] = esistente.get("overrides", {})
    ok = _scrivi_raw(nuovo)
    if ok:
        print("[RUNTIME] runtime.json ripristinato da config.py")
    return ok
