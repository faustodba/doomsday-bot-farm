# ==============================================================================
#  DOOMSDAY BOT V5 - allocation.py
#  Sistema decisionale allocazione slot raccolta risorse
#
#  LOGICA:
#    Ad ogni ciclo, dato il deposito corrente (OCR) e gli slot liberi,
#    calcola la sequenza ottimale di tipi di nodo da raccogliere per
#    mantenere il deposito bilanciato rispetto al rapporto target.
#
#  RAPPORTO TARGET (basato su quantità nodo livello 6):
#    campo    (pomodoro) → 37.50%   (1.200.000 / nodo)
#    segheria (legno)    → 37.50%   (1.200.000 / nodo)
#    petrolio            → 18.75%   (  600.000 / nodo — invertito rispetto base)
#    acciaio             →  6.25%   (  240.000 / nodo — invertito rispetto base)
#
#  ALGORITMO GAP:
#    1. Leggi percentuale attuale di ogni risorsa nel deposito
#    2. Calcola gap = target% - attuale% per ogni tipo
#    3. Ordina per gap decrescente (più in ritardo = più priorità)
#    4. Distribuisci gli slot seguendo la priorità con cap per tipo
#
#  DESIGN:
#    - Zero stato persistente: il deposito OCR è la fonte di verità
#    - Fail-safe: se OCR fallisce → sequenza bilanciata di default
#    - Cap per tipo: evita che tutti gli slot vadano su un solo nodo
# ==============================================================================

import math

# ------------------------------------------------------------------------------
# Rapporto target nel deposito
# Basato su quantità nodo livello 6, con acciaio/petrolio invertiti
# rispetto alla produzione base per rispecchiare il consumo reale:
#   pomodoro/legno: risorse principali
#   petrolio: seconda priorità (consumo elevato, produzione bassa)
#   acciaio:  risorsa marginale
# ------------------------------------------------------------------------------
RATIO_TARGET = {
    "campo":     0.3750,   # pomodoro — 37.50%
    "segheria":  0.3750,   # legno    — 37.50%
    "petrolio":  0.1875,   #          — 18.75%
    "acciaio":   0.0625,   #          —  6.25%
}

# Mappa tipo nodo → chiave deposito OCR
TIPO_TO_RISORSA = {
    "campo":     "pomodoro",
    "segheria":  "legno",
    "petrolio":  "petrolio",
    "acciaio":   "acciaio",
}

# Cap massimo slot per tipo per ciclo: evita di mandare tutto su un solo nodo.
# Formula: max(1, floor(slot_liberi / 2))
# Con 4 slot → max 2 per tipo. Con 5 slot → max 2 per tipo.
# Con 1-2 slot → max 1 per tipo (garantisce varietà minima).
CAP_DIVISORE = 2

# Soglia minima deposito per considerare una risorsa "presente" nell'OCR.
# Sotto questa soglia il dato OCR è probabilmente un artefatto.
SOGLIA_OCR_MIN_M = 0.1   # 100K


def calcola_sequenza(slot_liberi: int, deposito: dict) -> list:
    """
    Calcola la sequenza ottimale di tipi nodo da raccogliere.

    Args:
        slot_liberi: numero di slot raccoglitori disponibili (1-5)
        deposito:    dict con chiavi "pomodoro","legno","petrolio","acciaio"
                     valori in unità assolute (come ritorna ocr.leggi_risorse)
                     -1 = dato non disponibile

    Returns:
        Lista di stringhe tipo ["campo","segheria","petrolio","campo",...]
        Lunghezza = slot_liberi.
        In caso di errore → sequenza di default bilanciata.
    """
    if slot_liberi <= 0:
        return []

    # --- Leggi deposito e filtra valori validi ---
    valori = {}
    for tipo, risorsa in TIPO_TO_RISORSA.items():
        v = deposito.get(risorsa, -1)
        if v is not None and v >= 0 and (v / 1_000_000) >= SOGLIA_OCR_MIN_M:
            valori[tipo] = float(v)
        else:
            valori[tipo] = 0.0

    totale = sum(valori.values())

    # --- Fallback: deposito non leggibile → sequenza bilanciata di default ---
    if totale < 1_000:
        return _sequenza_default(slot_liberi)

    # --- Calcola percentuale attuale per ogni tipo ---
    perc_attuale = {tipo: valori[tipo] / totale for tipo in RATIO_TARGET}

    # --- Calcola gap: target - attuale ---
    # Gap positivo = risorsa sotto-rappresentata → alta priorità
    # Gap negativo = risorsa in eccesso → bassa priorità
    gap = {tipo: RATIO_TARGET[tipo] - perc_attuale[tipo] for tipo in RATIO_TARGET}

    # --- Ordina per gap decrescente ---
    tipi_ordinati = sorted(gap.keys(), key=lambda t: gap[t], reverse=True)

    # --- Cap per tipo ---
    cap = max(1, math.floor(slot_liberi / CAP_DIVISORE))

    # --- Distribuisci gli slot ---
    # Strategia: riempi in ordine di priorità rispettando il cap.
    # Se un tipo ha gap negativo e ci sono ancora slot da riempire,
    # viene comunque incluso (meglio raccogliere qualcosa che stare fermi).
    contatori = {tipo: 0 for tipo in RATIO_TARGET}
    sequenza  = []

    # Prima passata: tipi con gap positivo in ordine di priorità
    for tipo in tipi_ordinati:
        if len(sequenza) >= slot_liberi:
            break
        if gap[tipo] > 0:
            n = min(cap, slot_liberi - len(sequenza))
            # Quanti slot assegnare proporzionalmente al gap
            # (almeno 1, al massimo cap)
            peso_relativo = gap[tipo] / max(sum(g for g in gap.values() if g > 0), 0.001)
            n_prop = max(1, round(peso_relativo * slot_liberi))
            n = min(n, n_prop, cap)
            for _ in range(n):
                if len(sequenza) < slot_liberi:
                    sequenza.append(tipo)
                    contatori[tipo] += 1

    # Seconda passata: riempi eventuali slot residui con i tipi a priorità
    # più alta (anche con gap negativo) rispettando il cap
    idx = 0
    while len(sequenza) < slot_liberi:
        tipo = tipi_ordinati[idx % len(tipi_ordinati)]
        if contatori[tipo] < cap:
            sequenza.append(tipo)
            contatori[tipo] += 1
        idx += 1
        # Safety: se dopo un giro completo non si riesce a riempire → break
        if idx > len(tipi_ordinati) * slot_liberi * 2:
            # Rilassa il cap e riprova
            cap = slot_liberi
            idx = 0

    return sequenza[:slot_liberi]


def _sequenza_default(slot_liberi: int) -> list:
    """
    Sequenza di default quando il deposito OCR non è disponibile.
    Rispetta i pesi target con distribuzione uniforme:
      campo, segheria, petrolio, campo, segheria → per 5 slot
    """
    base = ["campo", "segheria", "petrolio", "campo", "segheria",
            "campo", "segheria", "petrolio", "acciaio", "campo"]
    return base[:slot_liberi]


def log_decisione(slot_liberi: int, deposito: dict,
                  sequenza: list, logger=None, nome: str = "ALLOC"):
    """
    Logga il processo decisionale per debug/monitoraggio.
    Chiamare dopo calcola_sequenza() se si vuole visibilità sulla logica.
    """
    def log(msg):
        if logger:
            logger(nome, f"[ALLOC] {msg}")
        else:
            print(f"[ALLOC] {msg}")

    valori = {}
    for tipo, risorsa in TIPO_TO_RISORSA.items():
        v = deposito.get(risorsa, -1)
        valori[tipo] = float(v) if (v is not None and v >= 0) else 0.0
    totale = sum(valori.values())

    if totale < 1_000:
        log(f"OCR deposito non disponibile → sequenza default: {sequenza}")
        return

    log(f"Slot: {slot_liberi} | Deposito totale: {totale/1e6:.1f}M")
    for tipo in RATIO_TARGET:
        risorsa  = TIPO_TO_RISORSA[tipo]
        perc_att = valori[tipo] / totale * 100
        perc_tgt = RATIO_TARGET[tipo] * 100
        gap_val  = perc_tgt - perc_att
        cnt      = sequenza.count(tipo)
        log(f"  {tipo:10s} ({risorsa:9s}): "
            f"att={perc_att:5.1f}% tgt={perc_tgt:5.1f}% "
            f"gap={gap_val:+5.1f}% → {cnt} slot")
    log(f"Sequenza: {sequenza}")
