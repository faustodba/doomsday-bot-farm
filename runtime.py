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
            "Usa 'overrides.bs' o 'overrides.mumu' per modificare singole istanze "
            "(es. {\"bs\": {\"FAU_09\": {\"abilitata\": false}}, "
            "\"mumu\": {\"FAU_01\": {\"truppe\": 13000}}})."
        ),
        "globali": {
            "ISTANZE_BLOCCO":                 getattr(config, "ISTANZE_BLOCCO", 1),
            "WAIT_MINUTI":                    getattr(config, "WAIT_MINUTI", 1),
            "ALLEANZA_ABILITATA":             getattr(config, "ALLEANZA_ABILITATA", True),
            "MESSAGGI_ABILITATI":             getattr(config, "MESSAGGI_ABILITATI", True),
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
        "overrides": {
            "bs":   {},
            "mumu": {},
        },
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

        # --- Migrazione struttura vecchia (istanze_bs/istanze_mumu) ---
        if "istanze_bs" in esistente or "istanze_mumu" in esistente:
            print("[RUNTIME] Struttura vecchia rilevata — migrazione a formato overrides namespace...")
            nuovo = _default()

            # Conserva i globali esistenti
            for k, v in esistente.get("globali", {}).items():
                if k in nuovo["globali"]:
                    nuovo["globali"][k] = v

            # Estrai overrides per namespace
            for ns, chiave_lista in (("bs", "istanze_bs"), ("mumu", "istanze_mumu")):
                for ist in esistente.get(chiave_lista, []):
                    nome = ist.get("nome", "")
                    if not nome:
                        continue
                    delta = {}
                    if not ist.get("abilitata", True):
                        delta["abilitata"] = False
                    ist_cfg = _trova_in_config(nome)
                    if ist_cfg:
                        if ist.get("truppe") not in (None, ist_cfg.get("truppe", 12000)):
                            delta["truppe"] = ist["truppe"]
                        if ist.get("max_squadre") not in (None, ist_cfg.get("max_squadre", 4)):
                            delta["max_squadre"] = ist["max_squadre"]
                    if delta:
                        nuovo["overrides"][ns][nome] = delta

            _scrivi_raw(nuovo)
            print(f"[RUNTIME] Migrazione completata.")
            return

        # --- Migrazione overrides flat → namespace bs/mumu ---
        ovr = esistente.get("overrides", {})
        if ovr and not ("bs" in ovr or "mumu" in ovr):
            print("[RUNTIME] Overrides flat rilevati — migrazione a namespace bs/mumu...")
            nuovo = _default()
            for k, v in esistente.get("globali", {}).items():
                if k in nuovo["globali"]:
                    nuovo["globali"][k] = v
            # Applica gli override flat a entrambi i namespace (comportamento conservativo)
            for nome, delta in ovr.items():
                nuovo["overrides"]["bs"][nome]   = dict(delta)
                nuovo["overrides"]["mumu"][nome] = dict(delta)
            _scrivi_raw(nuovo)
            print("[RUNTIME] Migrazione overrides flat completata — verificare bs/mumu in runtime.json")
            return

        # --- Struttura nuova: aggiungi chiavi globali mancanti e namespace overrides ---
        default = _default()
        aggiornato = False
        for k, v in default["globali"].items():
            if k not in esistente.get("globali", {}):
                esistente.setdefault("globali", {})[k] = v
                aggiornato = True
        # Assicura che overrides abbia entrambi i namespace
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


def _trova_in_config(nome: str) -> dict:
    """Cerca istanza per nome in config.ISTANZE e config.ISTANZE_MUMU."""
    for lst in (getattr(config, "ISTANZE", []), getattr(config, "ISTANZE_MUMU", [])):
        for ist in lst:
            if ist.get("nome") == nome:
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
    if "ALLEANZA_ABILITATA" in g:
        config.ALLEANZA_ABILITATA = bool(g["ALLEANZA_ABILITATA"])
    if "MESSAGGI_ABILITATI" in g:
        config.MESSAGGI_ABILITATI = bool(g["MESSAGGI_ABILITATI"])
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
    applica gli overrides del namespace corretto e ritorna la lista filtrata.

    Namespace overrides: "bs" per BlueStacks, "mumu" per MuMuPlayer.
    Priorità abilitata: runtime.json override > config.py campo abilitata.
    """
    if "BlueStacks" in emulatore:
        lista_config = getattr(config, "ISTANZE", [])
        ns = "bs"
    else:
        lista_config = getattr(config, "ISTANZE_MUMU", [])
        ns = "mumu"

    # Supporta sia struttura nuova {"bs": {...}, "mumu": {...}}
    # che struttura flat legacy {"FAU_00": {...}} — retrocompatibilità
    ovr_root = rt.get("overrides", {})
    if ns in ovr_root:
        overrides = ovr_root[ns]
    elif "bs" not in ovr_root and "mumu" not in ovr_root:
        overrides = ovr_root  # struttura flat legacy
    else:
        overrides = {}

    risultato = []

    for ist in lista_config:
        nome = ist.get("nome", "")
        ovr  = overrides.get(nome, {})

        # abilitata: override runtime ha precedenza su config.py
        abilitata = ovr.get("abilitata", ist.get("abilitata", True))
        if not abilitata:
            continue

        # Costruisci dizionario risultante applicando overrides numerici
        ist_out = dict(ist)
        if "truppe"      in ovr: ist_out["truppe"]      = int(ovr["truppe"])
        if "max_squadre" in ovr: ist_out["max_squadre"] = int(ovr["max_squadre"])
        if "layout"      in ovr: ist_out["layout"]      = int(ovr["layout"])
        if "lingua"      in ovr: ist_out["lingua"]      = str(ovr["lingua"])
        if "livello"     in ovr: ist_out["livello"]     = int(ovr["livello"])

        # Normalizza porta per tipo emulatore
        if "BlueStacks" in emulatore:
            ist_out["porta"] = str(ist_out["porta"])
        else:
            ist_out["porta"] = int(ist_out["porta"])

        risultato.append(ist_out)

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


# ==============================================================================
# Ripristina runtime.json dai valori correnti di config.py
# Conserva gli overrides per-istanza (non li azzera).
# ==============================================================================
def ripristina_da_config() -> bool:
    """
    Sovrascrive la sezione 'globali' di runtime.json con i valori
    attuali di config.py, mantenendo invariati gli overrides per-istanza.
    """
    esistente = carica()
    nuovo = _default()
    # Conserva overrides esistenti (con namespace se presenti)
    ovr_esistente = esistente.get("overrides", {})
    if "bs" in ovr_esistente or "mumu" in ovr_esistente:
        nuovo["overrides"] = ovr_esistente
    else:
        # Struttura flat legacy — conserva com'è
        nuovo["overrides"] = ovr_esistente
    ok = _scrivi_raw(nuovo)
    if ok:
        print("[RUNTIME] runtime.json ripristinato da config.py")
    return ok
