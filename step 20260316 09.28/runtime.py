# ==============================================================================
#  DOOMSDAY BOT V5 - runtime.py
#  Configurazione modificabile a runtime senza riavviare il bot.
#
#  Il file runtime.json viene riletto all'inizio di ogni ciclo in main.py.
#  Le modifiche sono operative dal ciclo successivo.
#
#  API pubblica:
#    carica()                          → dict con tutti i parametri
#    applica(rt)                       → sovrascrive config.* in memoria
#    istanze_attive(rt, emulatore)     → lista istanze abilitate nel formato config
#    salva(dati)                       → scrive runtime.json (chiamato da dashboard)
#    inizializza_se_mancante()         → crea runtime.json da config.py se non esiste
# ==============================================================================

import json
import os
import threading
import config

_lock      = threading.Lock()
_PATH      = os.path.join(config.BOT_DIR, "runtime.json")

# ------------------------------------------------------------------------------
# Struttura default — specchia config.py come punto di partenza
# ------------------------------------------------------------------------------
def _default() -> dict:
    """Costruisce la struttura runtime di default leggendo config.py."""

    def _ist_bs(ist: list) -> dict:
        return {
            "nome":        ist[0],
            "interno":     ist[1],
            "porta":       ist[2],
            "abilitata":   True,
            "truppe":      ist[3] if len(ist) > 3 else 12000,
            "max_squadre": ist[4] if len(ist) > 4 else 4,
            "layout":      ist[5] if len(ist) > 5 else 1,
        }

    def _ist_mumu(ist: list) -> dict:
        # ISTANZE_MUMU: [nome, indice, porta]
        # truppe/max_squadre/layout: stessi default di BS per coerenza
        nome = ist[0]
        # Cerca i parametri di gioco dall'istanza BS corrispondente (stesso nome)
        ist_bs = next((i for i in config.ISTANZE if i[0] == nome), None)
        return {
            "nome":        nome,
            "indice":      ist[1],
            "porta":       ist[2],
            "abilitata":   True,
            "truppe":      ist_bs[3] if ist_bs and len(ist_bs) > 3 else 12000,
            "max_squadre": ist_bs[4] if ist_bs and len(ist_bs) > 4 else 4,
            "layout":      ist_bs[5] if ist_bs and len(ist_bs) > 5 else 1,
        }

    return {
        "_nota": "Modificabile a runtime — riletto ogni ciclo senza riavviare il bot",
        "globali": {
            "ISTANZE_BLOCCO":               getattr(config, "ISTANZE_BLOCCO", 1),
            "WAIT_MINUTI":                  getattr(config, "WAIT_MINUTI", 1),
            "RIFORNIMENTO_ABILITATO":       getattr(config, "RIFORNIMENTO_ABILITATO", True),
            "RIFORNIMENTO_SOGLIA_M":        getattr(config, "RIFORNIMENTO_SOGLIA_M", 5.0),
            "RIFORNIMENTO_SOGLIA_PETROLIO_M": getattr(config, "RIFORNIMENTO_SOGLIA_PETROLIO_M", 2.5),
            "ALLOCATION_RATIO": {
                "campo":    0.3750,
                "segheria": 0.3750,
                "petrolio": 0.1875,
                "acciaio":  0.0625,
            },
        },
        "istanze_bs":   [_ist_bs(i)   for i in getattr(config, "ISTANZE",      [])],
        "istanze_mumu": [_ist_mumu(i) for i in getattr(config, "ISTANZE_MUMU", [])],
    }


# ------------------------------------------------------------------------------
# Inizializza runtime.json se non esiste
# ------------------------------------------------------------------------------
def inizializza_se_mancante():
    """
    Crea runtime.json da config.py se il file non esiste ancora.
    Chiamare una volta all'avvio in main.py.
    """
    with _lock:
        if not os.path.exists(_PATH):
            _scrivi_raw(_default())
            print(f"[RUNTIME] runtime.json creato da config.py → {_PATH}")
        else:
            # Aggiunge eventuali chiavi mancanti (upgrade versione)
            try:
                with open(_PATH, "r", encoding="utf-8") as f:
                    esistente = json.load(f)
                default = _default()
                aggiornato = _merge(default, esistente)
                if aggiornato != esistente:
                    _scrivi_raw(aggiornato)
                    print(f"[RUNTIME] runtime.json aggiornato con nuove chiavi")
            except Exception as e:
                print(f"[RUNTIME] WARN: errore lettura runtime.json, uso default: {e}")


def _merge(default: dict, esistente: dict) -> dict:
    """Merge ricorsivo: mantiene i valori esistenti, aggiunge chiavi mancanti dal default."""
    result = dict(default)
    for k, v in esistente.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _merge(result[k], v)
        else:
            result[k] = v
    return result


# ------------------------------------------------------------------------------
# Carica runtime.json
# ------------------------------------------------------------------------------
def carica() -> dict:
    """
    Legge runtime.json e ritorna il dict.
    In caso di errore ritorna il default (non blocca il ciclo).
    """
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
# Applica parametri runtime a config.* in memoria
# ------------------------------------------------------------------------------
def applica(rt: dict):
    """
    Sovrascrive i parametri di config.* in memoria con i valori di runtime.json.
    Chiamare all'inizio di ogni ciclo in main.py.
    Non tocca le coordinate ADB né i percorsi — quelli rimangono da config.py.
    """
    g = rt.get("globali", {})

    # Parametri ciclo
    if "ISTANZE_BLOCCO" in g:
        config.ISTANZE_BLOCCO = int(g["ISTANZE_BLOCCO"])
    if "WAIT_MINUTI" in g:
        config.WAIT_MINUTI = int(g["WAIT_MINUTI"])

    # Rifornimento
    if "RIFORNIMENTO_ABILITATO" in g:
        config.RIFORNIMENTO_ABILITATO = bool(g["RIFORNIMENTO_ABILITATO"])
    if "RIFORNIMENTO_SOGLIA_M" in g:
        config.RIFORNIMENTO_SOGLIA_M = float(g["RIFORNIMENTO_SOGLIA_M"])
    if "RIFORNIMENTO_SOGLIA_PETROLIO_M" in g:
        config.RIFORNIMENTO_SOGLIA_PETROLIO_M = float(g["RIFORNIMENTO_SOGLIA_PETROLIO_M"])

    # Allocation ratio — aggiorna il modulo allocation direttamente
    if "ALLOCATION_RATIO" in g:
        try:
            import allocation
            ratio = g["ALLOCATION_RATIO"]
            # Normalizza a 1.0 per sicurezza
            totale = sum(ratio.values())
            if totale > 0:
                allocation.RATIO_TARGET = {k: v / totale for k, v in ratio.items()}
        except Exception as e:
            print(f"[RUNTIME] WARN applica ALLOCATION_RATIO: {e}")


# ------------------------------------------------------------------------------
# Costruisce lista istanze attive nel formato atteso da main.py
# ------------------------------------------------------------------------------
def istanze_attive(rt: dict, emulatore: str) -> list:
    """
    Ritorna la lista di istanze abilitate nel formato lista usato da main.py:
      BS:   [nome, interno, porta, truppe, max_squadre, layout]
      MuMu: [nome, indice,  porta, truppe, max_squadre, layout]

    emulatore: "BlueStacks" | "MuMuPlayer 12"
    """
    chiave = "istanze_bs" if "BlueStacks" in emulatore else "istanze_mumu"
    lista  = rt.get(chiave, [])

    risultato = []
    for ist in lista:
        if not ist.get("abilitata", True):
            continue
        nome        = ist.get("nome", "")
        truppe      = int(ist.get("truppe", 12000))
        max_squadre = int(ist.get("max_squadre", 4))
        layout      = int(ist.get("layout", 1))

        if "BlueStacks" in emulatore:
            interno = ist.get("interno", "")
            porta   = str(ist.get("porta", ""))
            risultato.append([nome, interno, porta, truppe, max_squadre, layout])
        else:
            indice = str(ist.get("indice", "0"))
            porta  = int(ist.get("porta", 16384))
            risultato.append([nome, indice, porta, truppe, max_squadre, layout])

    return risultato


# ------------------------------------------------------------------------------
# Salva runtime.json (chiamato da dashboard_server via POST)
# ------------------------------------------------------------------------------
def salva(dati: dict) -> bool:
    """
    Scrive runtime.json in modo atomico.
    Ritorna True se ok, False se errore.
    """
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


# ------------------------------------------------------------------------------
# Legge solo i parametri globali (per dashboard senza caricare tutto)
# ------------------------------------------------------------------------------
def leggi_globali() -> dict:
    return carica().get("globali", {})
