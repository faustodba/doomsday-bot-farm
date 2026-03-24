# ==============================================================================
#  DOOMSDAY BOT V5 - emulatore_base.py
#  Logica comune condivisa da bluestacks.py e mumu.py
#
#  Contiene:
#    - attendi_e_raccogli_istanza()  polling popup + raccolta + chiusura
#    - _verifica_popup()             rilevamento popup via pixel color
#
#  Ogni modulo emulatore (bluestacks.py, mumu.py) implementa solo:
#    - avvia_istanza()
#    - avvia_blocco()
#    - chiudi_istanza()
#    - chiudi_blocco()
#    - cleanup_istanze_appese()
#    - _pids_istanze, _pids_lock
# ==============================================================================

import time
import adb
import config
import timing
import status as _status

# Attesa minima garantita prima del polling popup.
# Il gioco non può caricare in meno di questo tempo.
ATTESA_MINIMA_CARICA = 30  # secondi

# BACK da inviare dopo le 3 conferme popup per chiudere banner/overlay
# che il gioco apre automaticamente al primo avvio (eventi, notifiche, ecc.)
N_BACK_PULIZIA     = 5    # numero di BACK
DELAY_BACK_PULIZIA = 0.5  # secondi tra un BACK e il successivo

# ------------------------------------------------------------------------------
# Polling popup + raccolta + chiusura istanza
#
# Parametri:
#   ist           : [nome, interno, porta, ...]
#   fn_raccolta   : callable(ist) → int (squadre inviate)
#   risultati     : dict condiviso {nome: n}
#   fn_chiudi     : callable(ist, logger) — chiudi_istanza del modulo emulatore
#   on_completata : callback opzionale (rilascio semaforo)
#   logger        : callable(nome, msg)
# ------------------------------------------------------------------------------
def attendi_e_raccogli_istanza(ist: list, fn_raccolta, risultati: dict,
                                fn_chiudi, on_completata=None, logger=None):
    """
    Flusso per singola istanza (eseguito in thread separato):
      1. Attesa minima 30s (il gioco non carica prima)
      2. Polling popup immediato → 3 conferme consecutive (o timeout)
      3. Raccolta risorse
      4. Chiusura immediata della propria istanza
      5. Callback on_completata()

    risultati[nome]:
       n >= 0  squadre inviate con successo
       -1      errore durante raccolta
       -2      timeout caricamento
       -3      watchdog (gioco non risponde)
    """
    nome    = ist["nome"]
    interno = ist.get("interno") or ist.get("indice", "")
    porta   = ist["porta"]

    def log(msg):
        if logger: logger(nome, msg)

    # --- Fase 1: attesa minima + log stima storica ---
    attesa_stimata = timing.attesa_ottimale(nome)
    log(f"[TIMING] Attesa minima: {ATTESA_MINIMA_CARICA}s | Stima storica: {attesa_stimata}s → polling dal secondo {ATTESA_MINIMA_CARICA}")
    time.sleep(ATTESA_MINIMA_CARICA)

    # --- Fase 2: polling popup ---
    conferme             = 0
    CONFERME_RICHIESTE   = 3
    attesa               = 0
    caricata             = False
    t_start              = time.time()
    screenshot_falliti   = 0
    MAX_SCREENSHOT_FAIL  = 10
    popup_no_consecutivi = 0
    MAX_POPUP_NO         = 20
    attesa_popup_aperto  = False

    while attesa < config.TIMEOUT_CARICA:

        if attesa_popup_aperto:
            adb.keyevent(porta, "KEYCODE_BACK")
            time.sleep(0.6)
            screen = adb.screenshot(porta)
            if screen and not _verifica_popup(screen):
                attesa_popup_aperto = False
            time.sleep(config.DELAY_GIRO)
            attesa += config.DELAY_GIRO
            continue

        adb.keyevent(porta, "KEYCODE_BACK")
        time.sleep(0.6)

        screen = adb.screenshot(porta)
        if not screen:
            screenshot_falliti += 1
            log(f"Screenshot fallito ({screenshot_falliti}/{MAX_SCREENSHOT_FAIL})")

            if screenshot_falliti >= MAX_SCREENSHOT_FAIL:
                log("Watchdog: troppi screenshot falliti → gioco non risponde")
                log("Tentativo riavvio gioco...")
                if adb.avvia_gioco(porta, tentativi=2, attesa=5):
                    log("Gioco riavviato - attesa 30s caricamento...")
                    time.sleep(30)
                    screenshot_falliti = 0
                    conferme = 0
                    attesa_popup_aperto = False
                else:
                    log("Riavvio gioco fallito - abbandono istanza")
                    risultati[nome] = -3
                    fn_chiudi(ist, logger)
                    if on_completata: on_completata()
                    return

            time.sleep(config.DELAY_GIRO)
            attesa += config.DELAY_GIRO
            continue

        screenshot_falliti = 0
        is_popup = _verifica_popup(screen)
        log(f"Popup: {'SI' if is_popup else 'NO'} | Conferme: {conferme}/{CONFERME_RICHIESTE}")

        if is_popup:
            popup_no_consecutivi = 0
            conferme += 1
            attesa_popup_aperto = True

            if conferme >= CONFERME_RICHIESTE:
                # Chiudi il popup corrente e tutti gli eventuali overlay/banner
                # che il gioco apre al primo avvio (eventi, notifiche, ecc.)
                # Un singolo BACK non e' sufficiente: serve una sequenza piu' robusta.
                for _ in range(N_BACK_PULIZIA):
                    adb.keyevent(porta, "KEYCODE_BACK")
                    time.sleep(DELAY_BACK_PULIZIA)

                # Verifica che lo stato sia davvero home prima di procedere
                import stato as _stato
                s_post, _ = _stato.rileva(porta)
                if s_post not in ("home", "mappa"):
                    # Ancora overlay: altro giro di BACK
                    log(f"Overlay residuo dopo pulizia (stato={s_post}) - altro giro BACK")
                    for _ in range(N_BACK_PULIZIA):
                        adb.keyevent(porta, "KEYCODE_BACK")
                        time.sleep(DELAY_BACK_PULIZIA)
                    s_post, _ = _stato.rileva(porta)

                log(f"Gioco pronto! -> avvio raccolta immediata (stato={s_post})")
                try: _status.istanza_gioco_pronto(nome)
                except Exception: pass
                caricata = True
                t_totale = ATTESA_MINIMA_CARICA + (time.time() - t_start)
                timing.registra(nome, t_totale, logger)
                break
        else:
            if conferme > 0:
                log(f"Popup perso - reset conferme (era {conferme})")
            conferme = 0
            attesa_popup_aperto = False
            popup_no_consecutivi += 1

            if popup_no_consecutivi >= MAX_POPUP_NO:
                popup_no_consecutivi = 0
                procs = adb.adb_shell(porta, "pidof com.igg.android.doomsdaylastsurvivors")
                if not procs.strip():
                    log(f"Watchdog popup: gioco non in esecuzione dopo {MAX_POPUP_NO} NO consecutivi")
                    log("Tentativo riavvio gioco...")
                    if adb.avvia_gioco(porta, tentativi=2, attesa=5):
                        log("Gioco riavviato - attesa 30s caricamento...")
                        time.sleep(30)
                        conferme = 0
                        attesa_popup_aperto = False
                    else:
                        log("Riavvio gioco fallito - abbandono istanza")
                        risultati[nome] = -3
                        fn_chiudi(ist, logger)
                        if on_completata: on_completata()
                        return
                else:
                    log(f"Watchdog popup: gioco in esecuzione (PID={procs.strip()}) - continuo attesa")

        time.sleep(config.DELAY_GIRO)
        attesa += config.DELAY_GIRO

    if not caricata:
        log(f"Timeout caricamento dopo {config.TIMEOUT_CARICA}s - abbandono istanza")
        risultati[nome] = -2
        fn_chiudi(ist, logger)
        if on_completata: on_completata()
        return

    # --- Fase 3: raccolta ---
    try:
        inviate = fn_raccolta(ist)
        log(f"Completata - {inviate} squadre inviate")
        risultati[nome] = inviate
        try: _status.istanza_completata(nome, inviate)
        except Exception: pass
    except Exception as e:
        log(f"ERRORE raccolta: {e}")
        risultati[nome] = -1
        try: _status.istanza_errore(nome, "errore")
        except Exception: pass

    # --- Fase 4: chiusura immediata ---
    fn_chiudi(ist, logger)

    if on_completata:
        on_completata()


# ------------------------------------------------------------------------------
# Rilevamento popup "Uscire dal gioco?" via pixel color
# Condiviso da tutti gli emulatori (le coordinate sono in config)
# ------------------------------------------------------------------------------
def _verifica_popup(screen_path: str) -> bool:
    """
    Ritorna True se lo screenshot mostra il popup di uscita dal gioco.
    Verifica due pixel: centro popup (beige) + pulsante OK (giallo).
    """
    try:
        from PIL import Image
        img = Image.open(screen_path)

        r, g, b = img.getpixel((config.POPUP_CHECK_X, config.POPUP_CHECK_Y))[:3]
        beige = (config.BEIGE_R_MIN <= r <= config.BEIGE_R_MAX and
                 config.BEIGE_G_MIN <= g <= config.BEIGE_G_MAX and
                 config.BEIGE_B_MIN <= b <= config.BEIGE_B_MAX)
        if not beige:
            return False

        r2, g2, b2 = img.getpixel((config.POPUP_OK_X, config.POPUP_OK_Y))[:3]
        giallo = (config.POPUP_OK_R_MIN <= r2 <= config.POPUP_OK_R_MAX and
                  config.POPUP_OK_G_MIN <= g2 <= config.POPUP_OK_G_MAX and
                  config.POPUP_OK_B_MIN <= b2 <= config.POPUP_OK_B_MAX)
        return giallo
    except:
        return False
