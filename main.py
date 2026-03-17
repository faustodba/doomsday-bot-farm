# ==============================================================================
#  DOOMSDAY BOT V5 - main.py
#  Loop principale - pool continuo con semaforo, chiusura immediata per istanza
#
#  ARCHITETTURA:
#  - Niente più blocchi sequenziali fissi: tutte le istanze vengono schedulate
#    in un pool controllato da un Semaphore(ISTANZE_BLOCCO)
#  - Ogni istanza acquisisce uno slot all'avvio e lo rilascia appena termina
#  - Non appena si libera uno slot, l'istanza successiva in coda parte subito
#  - Ogni istanza chiude SOLO la propria finestra dell'emulatore (chiusura selettiva)
#  - L'attesa iniziale DELAY_CARICA_INIZ è per-istanza (non blocca le altre)
#
#  Uso: python main.py
# ==============================================================================

import os
import time
import threading
from datetime import datetime
import raccolta
import log
import debug
import timing
import status
import report
import config
import runtime
import dashboard_server

# ------------------------------------------------------------------------------
# Selezione emulatore all'avvio
# Imposta il modulo emulatore attivo (bluestacks o mumu) e le istanze da usare.
# Tutto il resto del codice usa `emulatore` come alias neutro.
# ------------------------------------------------------------------------------
def _scegli_emulatore():
    import argparse
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--istanze",   default=None,
                        help="Nomi istanze separati da virgola (es. FAU_00,FAU_01)")
    parser.add_argument("--emulatore", default=None, choices=["1", "2"],
                        help="1=BlueStacks, 2=MuMuPlayer")
    args, _ = parser.parse_known_args()

    # Selezione emulatore
    if args.emulatore:
        scelta = args.emulatore
    else:
        print("\n" + "=" * 55)
        print("  Seleziona emulatore:")
        print("    [1] BlueStacks  (default)")
        print("    [2] MuMuPlayer 12")
        print("=" * 55)
        scelta = input("  Scelta [1/2]: ").strip()

    if scelta == "2":
        import mumu as _emu
        istanze_base = config.ISTANZE_MUMU
        config.ADB_EXE = config.MUMU_ADB
    else:
        import bluestacks as _emu
        istanze_base = config.ISTANZE
        config.ADB_EXE = config.BS_ADB

    nome_emu = _emu.NOME

    # Filtro istanze se passato da launcher (--istanze FAU_00,FAU_01,...)
    if args.istanze:
        nomi_sel = set(args.istanze.split(","))
        istanze = [i for i in istanze_base if i.get("nome") in nomi_sel]
        if not istanze:
            print(f"  ATTENZIONE: nessuna istanza trovata per: {args.istanze}")
            istanze = istanze_base
    else:
        istanze = istanze_base

    return _emu, istanze, nome_emu

emulatore, ISTANZE_ATTIVE, NOME_EMULATORE = _scegli_emulatore()

# Verifica e avvio automatico del manager dell'emulatore selezionato
emulatore.assicura_avvio_manager(logger=log.logger)

# Inizializza runtime.json da config.py se non esiste ancora
runtime.inizializza_se_mancante()

# ------------------------------------------------------------------------------
# Scelta configurazione di partenza
# Se runtime.json esiste già, chiede se usarlo o ripartire da config.py.
# Bypassa la domanda se --config è passato da launcher.
# ------------------------------------------------------------------------------
def _scegli_configurazione():
    import argparse, os
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config", default=None, choices=["runtime", "default"],
                        help="runtime=usa runtime.json, default=ripristina da config.py")
    args, _ = parser.parse_known_args()

    path_rt = os.path.join(config.BOT_DIR, "runtime.json")
    if not os.path.exists(path_rt):
        return  # nessun file → niente da chiedere, _default() già applicato

    if args.config == "runtime":
        scelta = "1"
    elif args.config == "default":
        scelta = "2"
    else:
        # Mostra riepilogo valori attuali in runtime.json
        rt_corrente = runtime.carica()
        g = rt_corrente.get("globali", {})
        print("\n" + "=" * 55)
        print("  Configurazione runtime.json attuale:")
        print(f"    Istanze parallele : {g.get('ISTANZE_BLOCCO', '?')}")
        print(f"    Attesa cicli      : {g.get('WAIT_MINUTI', '?')} min")
        print(f"    Alleanza          : {'ON' if g.get('ALLEANZA_ABILITATA', True) else 'OFF'}")
        print(f"    Messaggi          : {'ON' if g.get('MESSAGGI_ABILITATI', True) else 'OFF'}")
        print(f"    Rifornimento      : {'ON' if g.get('RIFORNIMENTO_ABILITATO', True) else 'OFF'}")
        ovr = rt_corrente.get("overrides", {})
        if ovr:
            print(f"    Overrides istanze : {list(ovr.keys())}")
        print("=" * 55)
        print("  Usa questa configurazione o ripristina config.py?")
        print("    [1] Usa runtime.json  (default)")
        print("    [2] Ripristina da config.py (sovrascrive runtime.json)")
        print("=" * 55)
        scelta = input("  Scelta [1/2]: ").strip()

    if scelta == "2":
        runtime.ripristina_da_config()
        print("  [RUNTIME] Configurazione ripristinata da config.py")
    else:
        print("  [RUNTIME] Uso configurazione da runtime.json")

_scegli_configurazione()

# ------------------------------------------------------------------------------
# Pulizia istanze appese all'avvio
# Killa tutti i processi emulatore rimasti da sessioni precedenti.
# Usa set() vuoto → cleanup aggressivo: killa tutto quello che trova.
# ------------------------------------------------------------------------------
def _pulizia_avvio():
    print("\n" + "=" * 55)
    print("  Pulizia istanze appese da sessioni precedenti...")
    emulatore.cleanup_istanze_appese(set(), logger=log.logger)
    print("=" * 55)

_pulizia_avvio()

# Fallback: se runtime.json non ha istanze abilitate, usa quelle originali di config.py
_istanze_originali = list(ISTANZE_ATTIVE)

# ------------------------------------------------------------------------------
# Scheduler pool con Semaphore
#
# Gestisce il lancio di tutte le istanze limitando quelle attive
# contemporaneamente a ISTANZE_BLOCCO. Appena un'istanza termina e rilascia
# il semaforo, quella successiva in coda viene avviata automaticamente.
# ------------------------------------------------------------------------------
def esegui_ciclo_pool(istanze: list, ciclo: int) -> tuple:
    """
    Lancia tutte le istanze in un pool controllato da Semaphore(ISTANZE_BLOCCO).
    Ogni istanza:
      1. Acquisisce uno slot (semaforo)
      2. Avvia BS + ADB + gioco
      3. Attende il proprio caricamento (DELAY_CARICA_INIZ + polling popup)
      4. Esegue la raccolta
      5. Chiude la propria istanza
      6. Rilascia lo slot → la prossima istanza in coda può partire

    Ritorna (totale_inviate, totale_errori).
    """
    # Avvia server ADB una volta sola per tutto il ciclo
    import adb as _adb
    _adb.start_server()

    semaforo   = threading.Semaphore(config.ISTANZE_BLOCCO)
    risultati  = {}
    threads    = []

    _ciclo_corrente = ciclo

    # Blacklist nodi condivisa tra tutti i thread del ciclo
    # chiave: "X_Y"  (es. "712_535")  — valore: timestamp prenotazione
    _blacklist_nodi      = {}
    _blacklist_nodi_lock = threading.Lock()

    # Snapshot PID: popolato subito dopo avvia_blocco(), prima che chiudi_istanza()
    # rimuova i PID dal registro. Garantisce che cleanup_istanze_appese() conosca
    # tutti i PID avviati nel ciclo, anche quelli già chiusi correttamente.
    _pids_snapshot      = set()
    _pids_snapshot_lock = threading.Lock()

    def fn_raccolta(ist):
        nome   = ist["nome"]
        porta  = ist["porta"]
        truppe = ist.get("truppe")
        max_sq = ist.get("max_squadre", 0)
        return raccolta.raccolta_istanza(porta, nome, truppe, max_sq, log.logger,
                                         ciclo=_ciclo_corrente,
                                         blacklist=_blacklist_nodi,
                                         blacklist_lock=_blacklist_nodi_lock,
                                         ist=ist)

    def worker(ist):
        nome    = ist["nome"]
        interno = ist.get("interno") or ist.get("indice", "")

        # Acquisisce slot: se ISTANZE_BLOCCO già attive, aspetta qui
        semaforo.acquire()
        log.logger(nome, "Slot acquisito - avvio istanza")

        try:
            avviate = emulatore.avvia_blocco([ist], log.logger)

            if not avviate:
                log.logger(nome, "Avvio fallito - salto")
                risultati[nome] = -1
                return

            # Snapshot PID subito dopo avvio, prima che chiudi_istanza() lo rimuova
            with emulatore._pids_lock:
                pid = emulatore._pids_istanze.get(interno, 0)
            if pid:
                with _pids_snapshot_lock:
                    _pids_snapshot.add(pid)            # Attesa iniziale caricamento (per-istanza, non blocca le altre)
            log.logger(NOME_EMULATORE, f"[{nome}] Attesa iniziale {config.DELAY_CARICA_INIZ}s caricamento...")
            time.sleep(config.DELAY_CARICA_INIZ)

            # Verifica caricamento + raccolta + chiusura immediata
            emulatore.attendi_e_raccogli_istanza(
                ist, fn_raccolta, risultati,
                on_completata=None,   # il rilascio semaforo è nel finally
                logger=log.logger
            )

        finally:
            # Rilascia slot SEMPRE (anche in caso di eccezione)
            semaforo.release()
            log.logger(nome, "Slot rilasciato")

    # Lancia un thread per ogni istanza; il semaforo controlla quante partono
    for ist in istanze:
        t = threading.Thread(target=worker, args=(ist,), name=ist["nome"])
        t.start()
        threads.append(t)
        # Piccola pausa tra i lanci per non sovraccaricare il semaforo in burst
        time.sleep(0.5)

    # Attendi completamento di tutti i thread
    for t in threads:
        t.join()

    # Cleanup finale: usa lo snapshot PID costruito durante il ciclo.
    # A questo punto _pids_istanze è già svuotato da chiudi_istanza(),
    # quindi lo snapshot è l'unica fonte affidabile dei PID gestiti.
    emulatore.cleanup_istanze_appese(_pids_snapshot, log.logger)

    totale_inviate = sum(v for v in risultati.values() if v >= 0)
    totale_errori  = sum(1 for v in risultati.values() if v == -1)
    totale_timeout = sum(1 for v in risultati.values() if v == -2)
    totale_watchdog = sum(1 for v in risultati.values() if v == -3)
    return totale_inviate, totale_errori, totale_timeout, totale_watchdog, risultati

# ------------------------------------------------------------------------------
# Loop principale
# ------------------------------------------------------------------------------
def main():
    global ISTANZE_ATTIVE
    log.init()             # resetta bot.log ad ogni avvio
    debug.pulisci_debug()  # elimina cartella debug/ dei cicli precedenti
    dashboard_server.avvia()  # avvia server HTTP dashboard in background (porta 8080)

    print("=" * 55)
    print("  DOOMSDAY BOT V5 - Raccolta automatica MULTITHREAD")
    print(f"  Emulatore: {NOME_EMULATORE}")
    print(f"  Istanze: {len(ISTANZE_ATTIVE)} | Slot paralleli: {config.ISTANZE_BLOCCO} | Attesa: {config.WAIT_MINUTI} min")
    print(f"  Log: {os.path.join(config.BOT_DIR, 'bot.log')}")
    print("=" * 55)

    ciclo = 0

    # Imposta emulatore nel file di status
    status._stato["emulatore"] = NOME_EMULATORE

    while True:
        ciclo += 1

        # --- Rileggi parametri runtime (effetto dal ciclo corrente) ---
        rt = runtime.carica()
        runtime.applica(rt)
        ISTANZE_ATTIVE = runtime.istanze_attive(rt, NOME_EMULATORE)
        if not ISTANZE_ATTIVE:
            log.logger("MAIN", "WARN: nessuna istanza abilitata in runtime.json — uso config.py")
            ISTANZE_ATTIVE = _istanze_originali

        debug.init_ciclo(ciclo)
        log.init_ciclo(debug.ciclo_dir(), [i["nome"] for i in ISTANZE_ATTIVE])
        log.logger("MAIN", f"=== CICLO {ciclo} === ({datetime.now().strftime('%H:%M:%S')})")
        log.logger("MAIN", f"Pool: {len(ISTANZE_ATTIVE)} istanze, max {config.ISTANZE_BLOCCO} parallele")
        if ciclo > 1:
            timing.riepilogo(log.logger)

        # Inizializza status per il ciclo corrente
        status.init_ciclo(ciclo, [i["nome"] for i in ISTANZE_ATTIVE])

        t_inizio = time.time()
        totale_inviate, totale_errori, totale_timeout, totale_watchdog, risultati = esegui_ciclo_pool(ISTANZE_ATTIVE, ciclo)
        report.genera_report(ciclo, risultati)
        durata_s = int(time.time() - t_inizio)

        log.logger("MAIN", f"Ciclo {ciclo} completato - "
                           f"squadre: {totale_inviate} | "
                           f"errori: {totale_errori} | "
                           f"timeout: {totale_timeout} | "
                           f"watchdog: {totale_watchdog}")

        # Aggiorna storico cicli nel status
        status.ciclo_completato(ciclo, totale_inviate, durata_s)

        minuti = config.WAIT_MINUTI
        log.logger("MAIN", f"Prossimo ciclo tra {minuti} min...")
        for s in range(minuti * 60, 0, -1):
            status.set_countdown(s)
            if s % 60 == 0:
                print(f"\r  [{datetime.now().strftime('%H:%M:%S')}] Prossimo ciclo tra {s//60:2d} min...",
                      end="", flush=True)
            time.sleep(1)
        print()
        status.set_stato("running")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nBot fermato dall'utente.")
