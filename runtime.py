# ==============================================================================
#  DOOMSDAY BOT V5 - runtime.py
#  Configurazione modificabile a runtime senza riavviare il bot.
#
#  ARCHITETTURA:
#    runtime.json NON contiene liste di istanze — quelle stanno in config.py.
#    Contiene solo:
#      - globali:   parametri ciclo modificabili (ISTANZE_BLOCCO, WAIT_MINUTI, ...)
#      - overrides: delta per-istanza (solo ciò che l'utente ha modificato)
#
#    Struttura runtime.json:
#    {
#      "globali": { "ISTANZE_BLOCCO": 1, "WAIT_MINUTI": 1, ... },
#      "overrides": {
#        "FAU_09": { "abilitata": false, "max_squadre": 3 }
#      }
#    }
#
#  FLUSSO ogni ciclo:
#    1. carica()             → legge runtime.json (globali + overrides)
#    2. applica(rt)          → sovrascrive config.* in memoria
#    3. istanze_attive(...)  → legge FRESH da config.py, applica overrides
#
#  VANTAGGI:
#    - Aggiungere/rimuovere istanze in config.py è immediatamente visibile
#    - Il json non contiene BS quando si usa MuMu e viceversa
#    - Nessun merge complesso, nessuna desincronizzazione
#    - Il json è piccolo e leggibile
#
#  API pubblica:
#    carica()                      -> dict
#    applica(rt)                   -> None
#    istanze_attive(rt, emulatore) -> list
#    salva(dati)                   -> bool
#    inizializza_se_mancante()     -> None
# ==============================================================================

import json
import os
import threading
import config

_lock = threading.Lock()
_PATH = os.path.join(config.BOT_DIR, "runtime.json")


# ==============================================================================
# Struttura default
# ==============================================================================
def _default() -> dict:
    return {
        "_nota": (
            "Modificabile a runtime — riletto ogni ciclo. "
            "Le istanze vengono sempre lette da config.py. "
            "Usa 'overrides' per modificare singole istanze "
            "(es. {\"FAU_09\": {\"abilitata\": false, \"max_squadre\": 2}})."
        ),
        "globali": {
            "ISTANZE_BLOCCO":                 getattr(config, "ISTANZE_BLOCCO", 1),
            "WAIT_MINUTI":                    getattr(config, "WAIT_MINUTI", 1),
            "RIFORNIMENTO_ABILITATO":         getattr(config, "RIFORNIMENTO_ABILITATO", True),
            "RIFORNIMENTO_SOGLIA_M":          getattr(config, "RIFORNIMENTO_SOGLIA_M", 5.0),
            "RIFORNIMENTO_SOGLIA_PETROLIO_M": getattr(config, "RIFORNIMENTO_SOGLIA_PETROLIO_M", 2.5),
            "ALLOCATION_RATIO": {
                "campo":    0.3750,
                "segheria": 0.3750,
                "petrolio": 0.1875,
                "acciaio":  0.0625,
            },
        },
        "overrides": {},
    }


# ==============================================================================
# Inizializza / migra runtime.json
# ==============================================================================
def inizializza_se_mancante():
    """
    - Se runtime.json non esiste: lo crea con la struttura nuova.
    - Se esiste con struttura VECCHIA (istanze_bs/istanze_mumu): migra
      automaticamente estraendo gli overrides significativi.
    - Se esiste con struttura nuova: aggiunge solo chiavi globali mancanti.
    """
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

        # --- Migrazione struttura vecchia ---
        if "istanze_bs" in esistente or "istanze_mumu" in esistente:
            print("[RUNTIME] Struttura vecchia rilevata — migrazione a formato overrides...")
            nuovo = _default()

            # Conserva i globali esistenti
            for k, v in esistente.get("globali", {}).items():
                if k in nuovo["globali"]:
                    nuovo["globali"][k] = v

            # Estrai overrides: solo delta rispetto ai default di config.py
            overrides = {}
            nomi_processati = set()
            for chiave_lista in ("istanze_bs", "istanze_mumu"):
                for ist in esistente.get(chiave_lista, []):
                    nome = ist.get("nome", "")
                    if not nome or nome in nomi_processati:
                        continue
                    nomi_processati.add(nome)
                    delta = {}
                    if not ist.get("abilitata", True):
                        delta["abilitata"] = False
                    ist_cfg = _trova_in_config(nome)
                    if ist_cfg:
                        cfg_truppe      = ist_cfg[3] if len(ist_cfg) > 3 else 12000
                        cfg_max_squadre = ist_cfg[4] if len(ist_cfg) > 4 else 4
                        if ist.get("truppe") not in (None, cfg_truppe):
                            delta["truppe"] = ist["truppe"]
                        if ist.get("max_squadre") not in (None, cfg_max_squadre):
                            delta["max_squadre"] = ist["max_squadre"]
                    if delta:
                        overrides[nome] = delta

            nuovo["overrides"] = overrides
            _scrivi_raw(nuovo)
            nomi = list(overrides.keys())
            print(f"[RUNTIME] Migrazione completata. Overrides: {nomi if nomi else 'nessuno'}")
            return

        # --- Struttura nuova: aggiungi chiavi globali mancanti ---
        default = _default()
        aggiornato = False
        for k, v in default["globali"].items():
            if k not in esistente.get("globali", {}):
                esistente.setdefault("globali", {})[k] = v
                aggiornato = True
        if "overrides" not in esistente:
            esistente["overrides"] = {}
            aggiornato = True
        if aggiornato:
            _scrivi_raw(esistente)
            print("[RUNTIME] runtime.json aggiornato con nuove chiavi")


def _trova_in_config(nome: str) -> list:
    """Cerca istanza per nome in config.ISTANZE e config.ISTANZE_MUMU."""
    for lst in (getattr(config, "ISTANZE", []), getattr(config, "ISTANZE_MUMU", [])):
        for ist in lst:
            if ist[0] == nome:
                return ist
    return None


# ==============================================================================
# Carica runtime.json
# ==============================================================================
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


# ==============================================================================
# Applica parametri globali a config.* in memoria
# ==============================================================================
def applica(rt: dict):
    """Sovrascrive config.* in memoria con i valori di runtime.json globali."""
    g = rt.get("globali", {})

    if "ISTANZE_BLOCCO" in g:
        config.ISTANZE_BLOCCO = int(g["ISTANZE_BLOCCO"])
    if "WAIT_MINUTI" in g:
        config.WAIT_MINUTI = int(g["WAIT_MINUTI"])
    if "RIFORNIMENTO_ABILITATO" in g:
        config.RIFORNIMENTO_ABILITATO = bool(g["RIFORNIMENTO_ABILITATO"])
    if "RIFORNIMENTO_SOGLIA_M" in g:
        config.RIFORNIMENTO_SOGLIA_M = float(g["RIFORNIMENTO_SOGLIA_M"])
    if "RIFORNIMENTO_SOGLIA_PETROLIO_M" in g:
        config.RIFORNIMENTO_SOGLIA_PETROLIO_M = float(g["RIFORNIMENTO_SOGLIA_PETROLIO_M"])

    if "ALLOCATION_RATIO" in g:
        try:
            import allocation
            ratio  = g["ALLOCATION_RATIO"]
            totale = sum(ratio.values())
            if totale > 0:
                allocation.RATIO_TARGET = {k: v / totale for k, v in ratio.items()}
        except Exception as e:
            print(f"[RUNTIME] WARN applica ALLOCATION_RATIO: {e}")


# ==============================================================================
# Lista istanze attive — SEMPRE fresca da config.py + overrides
# ==============================================================================
def istanze_attive(rt: dict, emulatore: str) -> list:
    """
    Legge le istanze FRESH da config.py (mai dal json),
    applica gli overrides e ritorna la lista filtrata.

    Formato elemento: [nome, interno/indice, porta, truppe, max_squadre, layout]
    emulatore: "BlueStacks" | "MuMuPlayer 12"
    """
    if "BlueStacks" in emulatore:
        lista_config = getattr(config, "ISTANZE", [])
    else:
        lista_config = getattr(config, "ISTANZE_MUMU", [])

    overrides = rt.get("overrides", {})
    risultato = []

    for ist in lista_config:
        nome = ist[0]
        ovr  = overrides.get(nome, {})

        # Istanza disabilitata via override
        if not ovr.get("abilitata", True):
            continue

        # Valori base da config.py
        truppe      = ist[3] if len(ist) > 3 else config.TRUPPE_RACCOLTA
        max_squadre = ist[4] if len(ist) > 4 else 4
        layout      = ist[5] if len(ist) > 5 else 1
        lingua      = ist[6] if len(ist) > 6 else "it"

        # Applica overrides numerici
        if "truppe"      in ovr: truppe      = int(ovr["truppe"])
        if "max_squadre" in ovr: max_squadre = int(ovr["max_squadre"])
        if "layout"      in ovr: layout      = int(ovr["layout"])
        if "lingua"      in ovr: lingua      = str(ovr["lingua"])

        if "BlueStacks" in emulatore:
            risultato.append([nome, str(ist[1]), str(ist[2]), truppe, max_squadre, layout, lingua])
        else:
            risultato.append([nome, str(ist[1]), int(ist[2]), truppe, max_squadre, layout, lingua])

    return risultato


# ==============================================================================
# Salva / utility
# ==============================================================================
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


def leggi_globali() -> dict:
    return carica().get("globali", {})
