# ==============================================================================
#  DOOMSDAY BOT V5 - alleanza.py
#  Raccolta ricompense dalla sezione Alleanza -> Dono
#
#  Flusso (dalla schermata home):
#    1. Tap pulsante Alleanza (menu in basso)
#    2. Tap icona Dono  → apre direttamente su "Ricompense del negozio"
#    3. Tab "Ricompense del negozio" → Tap "Rivendica" x10  (già attivo)
#    4. Tab "Ricompense attività"    → Tap "Raccogli tutto" (1 click)
#    5. Back x3 → torna in home
#
#  Schedulazione:
#    Eseguito al massimo ogni SCHEDULE_ORE_ALLEANZA ore per istanza (default 12h).
#    Se già eseguito entro l'intervallo, viene saltato con log del tempo rimanente.
#    Stato persistito in: schedule_stato_{nome}_{porta}.json
#
#  Risoluzione ADB: 960x540
# ==============================================================================

import time
import adb
import config
import scheduler


# ------------------------------------------------------------------------------
# Coordinate (risoluzione 960x540)
# ------------------------------------------------------------------------------
COORD_ALLEANZA       = (760, 505)   # Pulsante Alleanza nel menu in basso
COORD_DONO           = (877, 458)   # Icona Dono nel menu Alleanza
COORD_TAB_ATTIVITA   = (600,  75)   # Tab "Ricompense attività"
COORD_TAB_NEGOZIO    = (810,  75)   # Tab "Ricompense del negozio"
COORD_RACCOGLI_TUTTO = (856, 505)   # Pulsante "Raccogli tutto" (Attività)
COORD_RIVENDICA      = (856, 240)   # Pulsante "Rivendica" (Negozio, posizione fissa)

# Numero di click su Rivendica per le Ricompense Negozio
RIVENDICA_CLICK = 10


# ------------------------------------------------------------------------------
# Raccolta ricompense Alleanza
# ------------------------------------------------------------------------------
def raccolta_alleanza(porta: str, nome: str, logger=None, ist: list = None) -> bool:
    """
    Raccoglie le ricompense dalla sezione Alleanza -> Dono.
    Salta silenziosamente se già eseguito nelle ultime SCHEDULE_ORE_ALLEANZA ore.

    Args:
        porta:   porta ADB dell'istanza (es. "5555")
        nome:    nome istanza per il log (es. "FAU_00")
        logger:  callable(nome, msg) oppure None
        ist:     elemento di config.ISTANZE — usato per leggere il layout barra

    Returns:
        True  se completato senza errori o saltato per schedulazione
        False in caso di eccezione durante l'esecuzione
    """
    def log(msg):
        if logger: logger(nome, msg)

    # Verifica schedulazione — salta se già eseguito entro l'intervallo
    if not scheduler.deve_eseguire(nome, porta, "alleanza", logger):
        return True

    # Coordinate pulsante Alleanza: dipende dal layout barra dell'istanza
    # ist è un dict (config.ISTANZE) — usa get() per leggere layout in sicurezza
    layout = ist.get("layout", 1) if isinstance(ist, dict) else 1
    coord_alleanza = config.get_coord_alleanza(ist) if ist else COORD_ALLEANZA
    log(f"Alleanza: layout barra {layout} → tap {coord_alleanza}")

    try:
        log("Inizio raccolta ricompense Alleanza")

        # Verifica stato prima di iniziare: deve essere in home.
        # messaggi.py o il modulo precedente potrebbero aver lasciato
        # la UI in uno stato non pulito.
        import stato as _stato
        s_ora, _ = _stato.rileva(porta)
        if s_ora != "home":
            log(f"Alleanza: stato '{s_ora}' — porto in home prima di procedere")
            if not _stato.vai_in_home(porta, nome, logger, conferme=2):
                log("Alleanza: impossibile tornare in home — skip")
                return False
            time.sleep(1.0)

        # 1. Apri menu Alleanza
        log("Alleanza: tap pulsante Alleanza")
        adb.tap(porta, coord_alleanza)
        time.sleep(2.0)  # aumentato da 1.5: dà tempo all'animazione apertura menu

        # 2. Apri sezione Dono (apre direttamente su Ricompense del negozio)
        log("Alleanza: tap Dono")
        adb.tap(porta, COORD_DONO)
        time.sleep(2.0)  # aumentato da 1.5: attende caricamento sezione Dono

        # 3. Ricompense Negozio → Rivendica x10 (tab già attivo all'apertura)
        log(f"Alleanza: Ricompense Negozio -> Rivendica x{RIVENDICA_CLICK}")
        adb.tap(porta, COORD_TAB_NEGOZIO)
        time.sleep(0.8)
        for i in range(RIVENDICA_CLICK):
            adb.tap(porta, COORD_RIVENDICA)
            time.sleep(0.5)

        # 4. Tab Ricompense Attività → Raccogli tutto
        log("Alleanza: tab Ricompense Attività -> Raccogli tutto")
        adb.tap(porta, COORD_TAB_ATTIVITA)
        time.sleep(0.8)
        adb.tap(porta, COORD_RACCOGLI_TUTTO)
        time.sleep(1.0)

        # 5. Back x3 → torna in home (extra back per stabilizzazione UI)
        log("Alleanza: chiusura (back x3)")
        adb.keyevent(porta, "KEYCODE_BACK")
        time.sleep(0.8)
        adb.keyevent(porta, "KEYCODE_BACK")
        time.sleep(1.5)
        adb.keyevent(porta, "KEYCODE_BACK")
        time.sleep(1.0)

        log("Raccolta ricompense Alleanza completata")

        # Registra esecuzione riuscita
        scheduler.registra_esecuzione(nome, porta, "alleanza")
        return True

    except Exception as e:
        log(f"Errore raccolta Alleanza: {e}")
        # Non registriamo in caso di errore: verrà ritentata al prossimo ciclo
        try:
            adb.keyevent(porta, "KEYCODE_BACK")
            time.sleep(0.5)
            adb.keyevent(porta, "KEYCODE_BACK")
            time.sleep(0.5)
        except Exception:
            pass
        return False