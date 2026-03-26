# ==============================================================================
#  DOOMSDAY BOT V5 - messaggi.py
#  Raccolta ricompense dalla sezione Messaggi (tab Alleanza + Sistema)
#
#  Sequenza per ogni istanza (prima della raccolta risorse):
#    1. Tap icona busta messaggi (home)
#    2. Tap tab ALLEANZA → Leggi e richiedi tutto
#    3. Tap tab SISTEMA  → Leggi e richiedi tutto
#    4. BACK
#
#  Schedulazione:
#    Eseguito al massimo ogni SCHEDULE_ORE_MESSAGGI ore per istanza (default 12h).
#    Se già eseguito entro l'intervallo, viene saltato con log del tempo rimanente.
#    Stato persistito in: schedule_stato_{nome}_{porta}.json
# ==============================================================================

import time
import adb
import config
import scheduler
import stato as _stato


def raccolta_messaggi(porta: str, nome: str, logger=None) -> bool:
    """
    Raccoglie le ricompense dalla sezione Messaggi.
    Salta silenziosamente se già eseguito nelle ultime SCHEDULE_ORE_MESSAGGI ore.

    Args:
        porta:   porta ADB dell'istanza (es. "5555")
        nome:    nome istanza per il log (es. "FAU_02")
        logger:  callable(nome, msg) oppure None

    Returns:
        True  se completato senza errori o saltato per schedulazione
        False in caso di eccezione durante l'esecuzione
    """
    def log(msg):
        if logger: logger(nome, msg)

    # Verifica schedulazione — salta se già eseguito entro l'intervallo
    if not scheduler.deve_eseguire(nome, porta, "messaggi", logger):
        return True

    # Verifica stato: deve essere in home prima di procedere
    if not _stato.vai_in_home(porta, nome, logger):
        return False

    try:
        log("Inizio raccolta messaggi")

        # 1. Apri schermata messaggi
        adb.tap(porta, (config.MSG_ICONA_X, config.MSG_ICONA_Y))
        time.sleep(1.5)

        # 2. Tab ALLEANZA → raccogli
        log("Messaggi: tab ALLEANZA -> Leggi e richiedi tutto")
        adb.tap(porta, (config.MSG_TAB_ALLEANZA_X, config.MSG_TAB_ALLEANZA_Y))
        time.sleep(1.0)
        adb.tap(porta, (config.MSG_LEGGI_X, config.MSG_LEGGI_Y))
        time.sleep(1.5)

        # 3. Tab SISTEMA → raccogli
        log("Messaggi: tab SISTEMA -> Leggi e richiedi tutto")
        adb.tap(porta, (config.MSG_TAB_SISTEMA_X, config.MSG_TAB_SISTEMA_Y))
        time.sleep(1.0)
        adb.tap(porta, (config.MSG_LEGGI_X, config.MSG_LEGGI_Y))
        time.sleep(1.5)

        # 4. Chiudi con BACK
        adb.keyevent(porta, "KEYCODE_BACK")
        time.sleep(1.0)

        log("Raccolta messaggi completata")

        # Registra esecuzione riuscita
        scheduler.registra_esecuzione(nome, porta, "messaggi")
        return True

    except Exception as e:
        log(f"Errore raccolta messaggi: {e}")
        # Non registriamo l'esecuzione in caso di errore:
        # al prossimo ciclo verrà ritentata
        return False