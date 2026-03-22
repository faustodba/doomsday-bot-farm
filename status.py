# ==============================================================================
#  DOOMSDAY BOT V5 - status.py
#  Scrive status.json in tempo reale per la dashboard web
#
#  Il file viene aggiornato ad ogni evento significativo:
#    - avvio/completamento istanza
#    - invio squadra
#    - lettura risorse deposito (inizio e fine ciclo)
#    - rifornimento inviato a account destinatario (delta reale pre/post invio)
#    - countdown prossimo ciclo
#
#  La dashboard.html legge questo file ogni 3s via fetch().
#
#  CALCOLO PRODUZIONE PER CICLO (per istanza):
#    produzione = (res_fine - res_inizio) + totale_inviato_rifornimento
#    Dove totale_inviato_rifornimento = somma dei delta (pre_invio - post_invio)
#    misurati da rifornimento.py dopo ogni VAI.
# ==============================================================================

import json
import os
import threading
from datetime import datetime
import config

_lock = threading.Lock()
_path = os.path.join(config.BOT_DIR, "status.json")

_RES_KEYS = ("pomodoro", "legno", "acciaio", "petrolio")

# Nome account destinatario rifornimento — letto da config e scritto in status.json
# La dashboard lo legge per mostrare il nome corretto nelle label
try:
    _dooms_account = getattr(config, "DOOMS_ACCOUNT", "destinatario")
except Exception:
    _dooms_account = "destinatario"

# Stato in memoria — aggiornato dai vari moduli, scritto su disco atomicamente
# Al primo import: se status.json esiste su disco lo carichiamo per preservare
# i dati dell ultimo ciclo anche dopo un riavvio del bot.
def _carica_stato_iniziale() -> dict:
    default = {
        "ciclo":         0,
        "stato":         "idle",
        "countdown_s":   0,
        "ts_aggiornato": "",
        "istanze":       {},
        "storico_cicli": [],
        "dooms_account": _dooms_account,
    }
    try:
        if os.path.exists(_path):
            with open(_path, "r", encoding="utf-8") as f:
                dati = json.load(f)
            # Marca tutte le istanze come dati storici (bot era fermo)
            for ist in dati.get("istanze", {}).values():
                ist["dati_storici"]         = True
                ist["stato"]                = "attesa"
                if not ist.get("ts_ultimo_ciclo"):
                    ist["ts_ultimo_ciclo"]  = dati.get("ts_aggiornato", "")
            dati["stato"]       = "idle"
            dati["countdown_s"] = 0
            dati["dooms_account"] = _dooms_account  # aggiorna sempre da config
            return {**default, **dati}
    except Exception:
        pass
    return default

_stato = _carica_stato_iniziale()


# ------------------------------------------------------------------------------
# Helpers interni
# ------------------------------------------------------------------------------

def _res_vuote() -> dict:
    return {k: -1.0 for k in _RES_KEYS}


def _timing_default() -> dict:
    """Struttura timing per dashboard (metriche ridotte)."""
    return {
        "ts_avvio_istanza": "",
        "ts_avvio_gioco": "",
        "ts_gioco_pronto": "",
        "ts_fine_raccolta": "",
        "ts_fine_istanza": "",
        "dur_raccolta_s": 0,
        "dur_chiusura_s": 0,
        "dur_totale_s": 0,
    }

def _parse_hms(ts: str):
    """Parsa HH:MM:SS in datetime di oggi (naive)."""
    try:
        t = datetime.strptime(ts, "%H:%M:%S").replace(year=datetime.now().year, month=datetime.now().month, day=datetime.now().day)
        return t
    except Exception:
        return None
def _res_from_raw(pomodoro, legno, acciaio=-1, petrolio=-1) -> dict:
    """Converte valori grezzi (unità intere) in milioni, -1 se assente."""
    def _conv(v):
        return round(v / 1_000_000, 2) if (v is not None and v > 0) else -1.0
    return {
        "pomodoro": _conv(pomodoro),
        "legno":    _conv(legno),
        "acciaio":  _conv(acciaio),
        "petrolio": _conv(petrolio),
    }

def _res_delta(a: dict, b: dict) -> dict:
    """
    Calcola b - a per ogni risorsa.
    Se uno dei due valori è -1 (non rilevato) restituisce -1 per quella risorsa.
    """
    out = {}
    for k in _RES_KEYS:
        va, vb = a.get(k, -1), b.get(k, -1)
        out[k] = round(vb - va, 2) if (va >= 0 and vb >= 0) else -1.0
    return out

def _res_somma(a: dict, b: dict) -> dict:
    """
    Somma a + b per ogni risorsa.
    Se uno dei due è -1, usa l'altro; se entrambi -1 restituisce -1.
    """
    out = {}
    for k in _RES_KEYS:
        va, vb = a.get(k, -1), b.get(k, -1)
        if va >= 0 and vb >= 0:
            out[k] = round(va + vb, 2)
        elif va >= 0:
            out[k] = va
        elif vb >= 0:
            out[k] = vb
        else:
            out[k] = -1.0
    return out

def _calcola_produzione(ist: dict) -> dict:
    """
    Produzione netta inter-ciclo:
      produzione = (res_inizio_corrente - res_inizio_ciclo_prec) + res_inviato_prec

    Calcola anche M/h usando il delta reale tra i timestamp delle due letture.
    Se i timestamp non sono disponibili, M/h rimane -1.

    Ritorna -1 per ogni risorsa dove uno dei due snapshot non e disponibile.
    """
    delta   = _res_delta(ist.get("res_inizio_ciclo_prec", _res_vuote()),
                         ist.get("res_inizio",            _res_vuote()))
    inviato = ist.get("res_inviato_prec", _res_vuote())

    # Calcola ore reali tra le due letture
    ore_reali = -1.0
    ts_prec = ist.get("ts_res_inizio_prec", "")
    ts_curr = ist.get("ts_res_inizio", "")
    if ts_prec and ts_curr:
        try:
            from datetime import datetime as _dt
            fmt = "%Y-%m-%dT%H:%M:%S"
            t0 = _dt.strptime(ts_prec, fmt)
            t1 = _dt.strptime(ts_curr, fmt)
            diff_s = (t1 - t0).total_seconds()
            if diff_s > 60:  # minimo 1 minuto per evitare divisioni su gap anomali
                ore_reali = diff_s / 3600
        except Exception:
            pass

    out = {}
    for k in _RES_KEYS:
        d = delta.get(k, -1)
        i = inviato.get(k, -1)
        if d >= 0:
            out[k] = round(d + (i if i >= 0 else 0), 2)
        else:
            out[k] = -1.0

    # Aggiunge M/h per risorsa se il tempo reale è disponibile
    mh = {}
    for k in _RES_KEYS:
        v = out.get(k, -1)
        mh[k] = round(v / ore_reali, 2) if (v >= 0 and ore_reali > 0) else -1.0

    out["_mh"]       = mh
    out["_ore_reali"] = round(ore_reali, 3) if ore_reali > 0 else -1.0
    return out


def _istanza_default(nome: str) -> dict:
    return {
        "nome":            nome,
        "stato":           "attesa",
        "squadre_inviate": 0,
        "squadre_target":  0,
        # Ultime risorse lette (aggiornate ad ogni lettura OCR — display dashboard)
        "pomodoro":        -1.0,
        "legno":           -1.0,
        "acciaio":         -1.0,
        "petrolio":        -1.0,
        "diamanti":        -1,
        # Snapshot inizio ciclo corrente
        "res_inizio":            _res_vuote(),
        # Timestamp ISO lettura res_inizio ciclo corrente
        "ts_res_inizio":         "",
        # Snapshot inizio ciclo PRECEDENTE — conservato da init_ciclo() per calcolo produzione
        "res_inizio_ciclo_prec": _res_vuote(),
        # Timestamp ISO lettura res_inizio ciclo PRECEDENTE
        "ts_res_inizio_prec":    "",
        # Snapshot fine ciclo (mantenuto per compatibilità)
        "res_fine":              _res_vuote(),
        # Risorse inviate a account destinatario nel ciclo CORRENTE (si accumula durante il ciclo)
        "res_inviato":           _res_vuote(),
        # Risorse inviate a account destinatario nel ciclo PRECEDENTE (conservato da init_ciclo())
        "res_inviato_prec":      _res_vuote(),
        # Produzione netta = (res_inizio_corrente - res_inizio_prec) + res_inviato_prec
        # Calcolata in istanza_risorse_inizio() quando entrambi i punti sono disponibili
        "produzione":            _res_vuote(),
        # Contatori errori
        "ocr_fail":        0,
        "cnt_errati":      0,
        "ts_inizio":       "",
        "durata_s":        0,
    "timing": _timing_default(),
        # Metadati per dashboard — preservati tra riavvii
        "dati_storici":    False,  # True = dati dall ultimo ciclo (bot fermo)
        "ts_ultimo_ciclo": "",     # "14/03 08:36" — quando sono stati aggiornati l ultima volta
    }


# ------------------------------------------------------------------------------
# Scrittura atomica su disco
# ------------------------------------------------------------------------------

def _scrivi():
    _stato["ts_aggiornato"] = datetime.now().strftime("%H:%M:%S")
    tmp = _path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_stato, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _path)
    except Exception:
        pass


# ------------------------------------------------------------------------------
# API pubblica — lifecycle istanza
# ------------------------------------------------------------------------------

def init_ciclo(ciclo: int, nomi_istanze: list):
    """
    Inizializza stato per il nuovo ciclo.

    Per ogni istanza che partecipa al nuovo ciclo:
    - Conserva res_inizio del ciclo appena concluso come res_inizio_ciclo_prec
    - Conserva res_inviato del ciclo appena concluso come res_inviato_prec
    - Azzera res_inizio, res_inviato, produzione per il nuovo ciclo
    Questo permette a _calcola_produzione() di confrontare i due punti di misura.
    """
    with _lock:
        _stato["ciclo"]       = ciclo
        _stato["stato"]       = "running"
        _stato["countdown_s"] = 0
        istanze_precedenti = _stato.get("istanze", {})
        nuove_istanze = {}
        for n in nomi_istanze:
            ist_prec = istanze_precedenti.get(n)
            ist_new  = _istanza_default(n)
            if ist_prec:
                # Conserva snapshot inizio e inviato del ciclo precedente
                ist_new["res_inizio_ciclo_prec"] = ist_prec.get("res_inizio", _res_vuote())
                ist_new["ts_res_inizio_prec"]    = ist_prec.get("ts_res_inizio", "")
                ist_new["res_inviato_prec"]      = ist_prec.get("res_inviato", _res_vuote())
                # Mantieni ultimo valore risorse visibile in dashboard
                for k in ("pomodoro", "legno", "acciaio", "petrolio", "diamanti"):
                    if ist_prec.get(k, -1) != -1:
                        ist_new[k] = ist_prec[k]
            nuove_istanze[n] = ist_new
        # Istanze non in questo ciclo: conserva invariate ma marca come storiche
        for n, ist in istanze_precedenti.items():
            if n not in nuove_istanze:
                ist["dati_storici"]   = True
                ist["ts_ultimo_ciclo"] = ist.get("ts_inizio", "") or _stato.get("ts_aggiornato", "")
                nuove_istanze[n] = ist
        _stato["istanze"] = nuove_istanze
        _scrivi()


def istanza_avvio(nome: str):
    with _lock:
        ist = _stato["istanze"].get(nome, _istanza_default(nome))
        ist["stato"]         = "avvio"
        ist["ts_inizio"]     = datetime.now().strftime("%H:%M:%S")
        ist.setdefault("timing", _timing_default())
        ist["timing"]["ts_avvio_istanza"] = ist["ts_inizio"]
        ist["dati_storici"]  = False   # l'istanza e' live da questo momento
        _stato["istanze"][nome] = ist
        _scrivi()



def istanza_gioco_avviato(nome: str):
    """Marca timestamp avvio gioco (app avviata)."""
    with _lock:
        ist = _stato["istanze"].get(nome, _istanza_default(nome))
        ist.setdefault("timing", _timing_default())
        ist["timing"]["ts_avvio_gioco"] = datetime.now().strftime("%H:%M:%S")
        _stato["istanze"][nome] = ist
        _scrivi()

def istanza_gioco_pronto(nome: str):
    """Marca timestamp gioco pronto (popup confermato)."""
    with _lock:
        ist = _stato["istanze"].get(nome, _istanza_default(nome))
        ist.setdefault("timing", _timing_default())
        ist["timing"]["ts_gioco_pronto"] = datetime.now().strftime("%H:%M:%S")
        _stato["istanze"][nome] = ist
        _scrivi()

def istanza_gioco_fermato(nome: str):
    """Marca timestamp fine raccolta/inizio chiusura (gioco fermato)."""
    with _lock:
        ist = _stato["istanze"].get(nome, _istanza_default(nome))
        ist.setdefault("timing", _timing_default())
        ist["timing"]["ts_fine_raccolta"] = datetime.now().strftime("%H:%M:%S")
        _stato["istanze"][nome] = ist
        _scrivi()

def istanza_slot_rilasciato(nome: str):
    """Marca timestamp fine istanza (slot rilasciato) e calcola durate."""
    with _lock:
        ist = _stato["istanze"].get(nome, _istanza_default(nome))
        ist.setdefault("timing", _timing_default())
        t = ist["timing"]
        t["ts_fine_istanza"] = datetime.now().strftime("%H:%M:%S")
        # durate (best-effort)
        t0 = _parse_hms(t.get("ts_avvio_istanza", "") or ist.get("ts_inizio", ""))
        t_ready = _parse_hms(t.get("ts_gioco_pronto", ""))
        t_stop = _parse_hms(t.get("ts_fine_raccolta", ""))
        t_end = _parse_hms(t.get("ts_fine_istanza", ""))
        if t_ready and t_stop:
            t["dur_raccolta_s"] = int((t_stop - t_ready).total_seconds())
        if t_stop and t_end:
            t["dur_chiusura_s"] = int((t_end - t_stop).total_seconds())
        if t0 and t_end:
            t["dur_totale_s"] = int((t_end - t0).total_seconds())
        _stato["istanze"][nome] = ist
        _scrivi()
def istanza_caricamento(nome: str):
    with _lock:
        ist = _stato["istanze"].get(nome, _istanza_default(nome))
        ist["stato"] = "caricamento"
        _stato["istanze"][nome] = ist
        _scrivi()


def istanza_raccolta(nome: str):
    with _lock:
        ist = _stato["istanze"].get(nome, _istanza_default(nome))
        ist["stato"] = "raccolta"
        _stato["istanze"][nome] = ist
        _scrivi()


def istanza_completata(nome: str, inviate: int):
    with _lock:
        ist = _stato["istanze"].get(nome, _istanza_default(nome))
        ist["stato"]           = "completata"
        ist["squadre_inviate"] = inviate
        ist.setdefault("timing", _timing_default())
        # Best-effort: se non presente, segna fine raccolta al completamento logico
        t = ist["timing"]
        if not t.get("ts_fine_raccolta"):
            t["ts_fine_raccolta"] = datetime.now().strftime("%H:%M:%S")
        t_ready = _parse_hms(t.get("ts_gioco_pronto", ""))
        t_stop = _parse_hms(t.get("ts_fine_raccolta", ""))
        if t_ready and t_stop:
            t["dur_raccolta_s"] = int((t_stop - t_ready).total_seconds())
        try:
            t0 = datetime.strptime(ist["ts_inizio"], "%H:%M:%S").replace(
                year=datetime.now().year,
                month=datetime.now().month,
                day=datetime.now().day)
            ist["durata_s"] = int((datetime.now() - t0).total_seconds())
        except Exception:
            ist["durata_s"] = 0
        ist["ts_ultimo_ciclo"] = datetime.now().strftime("%d/%m %H:%M")
        ist["dati_storici"]    = False
        _stato["istanze"][nome] = ist
        _scrivi()


def istanza_errore(nome: str, tipo: str = "errore"):
    """tipo: 'errore' | 'timeout' | 'watchdog'"""
    with _lock:
        ist = _stato["istanze"].get(nome, _istanza_default(nome))
        ist["stato"]           = tipo
        ist["ts_ultimo_ciclo"] = datetime.now().strftime("%d/%m %H:%M")
        ist["dati_storici"]    = False
        _stato["istanze"][nome] = ist
        _scrivi()


# ------------------------------------------------------------------------------
# API pubblica — risorse deposito
# ------------------------------------------------------------------------------

def istanza_risorse(nome: str, pomodoro: float, legno: float,
                    acciaio: float = -1, petrolio: float = -1, diamanti: float = -1):
    """
    Lettura generica OCR risorse deposito.
    Aggiorna i campi di superficie (pomodoro/legno/...) visibili nella dashboard.
    NON sovrascrive res_inizio/res_fine — usa le funzioni dedicate sotto.
    """
    with _lock:
        ist = _stato["istanze"].get(nome, _istanza_default(nome))
        res = _res_from_raw(pomodoro, legno, acciaio, petrolio)
        ist["pomodoro"] = res["pomodoro"]
        ist["legno"]    = res["legno"]
        ist["acciaio"]  = res["acciaio"]
        ist["petrolio"] = res["petrolio"]
        if diamanti is not None and diamanti >= 0:
            ist["diamanti"] = int(diamanti)
        _stato["istanze"][nome] = ist
        _scrivi()


def istanza_risorse_inizio(nome: str, pomodoro: float, legno: float,
                            acciaio: float = -1, petrolio: float = -1):
    """
    Snapshot risorse all'AVVIO dell'istanza (prima di mandare squadre).
    Chiamare da raccolta.py dopo la prima lettura OCR del ciclo.

    Questo e il momento corretto per calcolare la produzione del ciclo precedente:
    abbiamo sia res_inizio_ciclo_prec (conservato da init_ciclo) che il nuovo res_inizio.
    La produzione viene calcolata e aggiornata immediatamente.
    """
    with _lock:
        ist = _stato["istanze"].get(nome, _istanza_default(nome))
        res = _res_from_raw(pomodoro, legno, acciaio, petrolio)
        ist["res_inizio"] = res
        ist["ts_res_inizio"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        # Aggiorna display superficiale
        ist["pomodoro"] = res["pomodoro"]
        ist["legno"]    = res["legno"]
        ist["acciaio"]  = res["acciaio"]
        ist["petrolio"] = res["petrolio"]
        # Calcola produzione ciclo precedente ora che abbiamo entrambi i punti di misura
        ist["produzione"] = _calcola_produzione(ist)
        _stato["istanze"][nome] = ist
        _scrivi()


def istanza_risorse_fine(nome: str, pomodoro: float, legno: float,
                          acciaio: float = -1, petrolio: float = -1):
    """
    Snapshot risorse a FINE ciclo istanza (dopo il ritorno delle squadre).
    Chiamare da raccolta.py dopo l'ultima lettura OCR del ciclo.
    Ricalcola automaticamente la produzione.
    """
    with _lock:
        ist = _stato["istanze"].get(nome, _istanza_default(nome))
        res = _res_from_raw(pomodoro, legno, acciaio, petrolio)
        ist["res_fine"] = res
        # Aggiorna anche display superficiale
        ist["pomodoro"] = res["pomodoro"]
        ist["legno"]    = res["legno"]
        ist["acciaio"]  = res["acciaio"]
        ist["petrolio"] = res["petrolio"]
        # Ricalcola produzione con i nuovi dati
        ist["produzione"] = _calcola_produzione(ist)
        _stato["istanze"][nome] = ist
        _scrivi()


def istanza_diamanti(nome: str, diamanti: int):
    """Salva il valore diamanti letto dall'OCR."""
    with _lock:
        ist = _stato["istanze"].get(nome, _istanza_default(nome))
        ist["diamanti"] = int(diamanti) if diamanti is not None and diamanti >= 0 else -1
        _stato["istanze"][nome] = ist
        _scrivi()


# ------------------------------------------------------------------------------
# API pubblica — rifornimento
# ------------------------------------------------------------------------------

def istanza_rifornimento(nome: str,
                          pomodoro_pre: float, legno_pre: float,
                          acciaio_pre: float,  petrolio_pre: float,
                          pomodoro_post: float, legno_post: float,
                          acciaio_post: float,  petrolio_post: float):
    """
    Registra le risorse inviate a account destinatario in un singolo invio.
    Chiamare da rifornimento.py dopo aver letto il deposito PRE e POST invio VAI.

    Il delta (pre - post) viene accumulato in res_inviato per il ciclo corrente.
    La produzione viene ricalcolata automaticamente.

    I valori pre/post sono in unità intere (come restituisce l'OCR).
    """
    with _lock:
        ist = _stato["istanze"].get(nome, _istanza_default(nome))

        pre  = _res_from_raw(pomodoro_pre,  legno_pre,  acciaio_pre,  petrolio_pre)
        post = _res_from_raw(pomodoro_post, legno_post, acciaio_post, petrolio_post)

        # delta = quanto è uscito dal deposito in questo invio
        delta = {}
        for k in _RES_KEYS:
            vp, vo = pre.get(k, -1), post.get(k, -1)
            if vp >= 0 and vo >= 0:
                delta[k] = max(0.0, round(vp - vo, 2))
            else:
                delta[k] = -1.0

        # Accumula sul totale inviato del ciclo
        acc = ist.get("res_inviato", _res_vuote())
        for k in _RES_KEYS:
            d = delta.get(k, -1)
            if d >= 0:
                acc[k] = round((acc[k] if acc[k] >= 0 else 0) + d, 2)
        ist["res_inviato"] = acc

        # Aggiorna display superficiale con i valori POST (deposito aggiornato)
        ist["pomodoro"] = post["pomodoro"]
        ist["legno"]    = post["legno"]
        ist["acciaio"]  = post["acciaio"]
        ist["petrolio"] = post["petrolio"]

        # Ricalcola produzione
        ist["produzione"] = _calcola_produzione(ist)
        _stato["istanze"][nome] = ist
        _scrivi()


# ------------------------------------------------------------------------------
# API pubblica — squadre
# ------------------------------------------------------------------------------

def istanza_target(nome: str, target: int):
    with _lock:
        ist = _stato["istanze"].get(nome, _istanza_default(nome))
        ist["squadre_target"] = target
        _stato["istanze"][nome] = ist
        _scrivi()


def istanza_squadra_ok(nome: str):
    with _lock:
        ist = _stato["istanze"].get(nome, _istanza_default(nome))
        ist["squadre_inviate"] += 1
        _stato["istanze"][nome] = ist
        _scrivi()


# ------------------------------------------------------------------------------
# API pubblica — errori OCR
# ------------------------------------------------------------------------------

def istanza_ocr_fail(nome: str):
    with _lock:
        ist = _stato["istanze"].get(nome, _istanza_default(nome))
        ist["ocr_fail"] += 1
        _stato["istanze"][nome] = ist
        _scrivi()


def istanza_cnt_errato(nome: str):
    with _lock:
        ist = _stato["istanze"].get(nome, _istanza_default(nome))
        ist["cnt_errati"] += 1
        _stato["istanze"][nome] = ist
        _scrivi()


# ------------------------------------------------------------------------------
# API pubblica — ciclo globale
# ------------------------------------------------------------------------------

def ciclo_completato(ciclo: int, squadre: int, durata_s: int):
    """
    Aggiunge voce allo storico cicli (max 20).
    Include produzione aggregata e totale inviato a account destinatario per il ciclo.
    """
    with _lock:
        prod_agg    = _res_vuote()
        inviato_agg = _res_vuote()

        for ist in _stato["istanze"].values():
            # Produzione aggregata
            for k in _RES_KEYS:
                v = ist.get("produzione", _res_vuote()).get(k, -1)
                if v >= 0:
                    prod_agg[k] = round((prod_agg[k] if prod_agg[k] >= 0 else 0) + v, 2)
            # Inviato aggregato (ciclo corrente — res_inviato ancora valido qui)
            for k in _RES_KEYS:
                v = ist.get("res_inviato", _res_vuote()).get(k, -1)
                if v >= 0:
                    inviato_agg[k] = round((inviato_agg[k] if inviato_agg[k] >= 0 else 0) + v, 2)

        _stato["storico_cicli"].append({
            "ciclo":      ciclo,
            "squadre":    squadre,
            "durata_m":   round(durata_s / 60, 1),
            "ts":         datetime.now().strftime("%H:%M"),
            "ts_iso":     datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "produzione": prod_agg,
            "inviato":    inviato_agg,
        })
        if len(_stato["storico_cicli"]) > 20:
            _stato["storico_cicli"] = _stato["storico_cicli"][-20:]
        _scrivi()


def set_countdown(secondi: int):
    with _lock:
        _stato["stato"]       = "waiting"
        _stato["countdown_s"] = secondi
        _scrivi()


def set_stato(s: str):
    with _lock:
        _stato["stato"] = s
        # Quando il bot va in idle, marca tutte le istanze come dati storici
        if s == "idle":
            ts = datetime.now().strftime("%d/%m %H:%M")
            for ist in _stato["istanze"].values():
                ist["dati_storici"] = True
                if not ist.get("ts_ultimo_ciclo"):
                    ist["ts_ultimo_ciclo"] = ts
        _scrivi()
