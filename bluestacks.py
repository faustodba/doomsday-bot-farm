# ==============================================================================
#  DOOMSDAY BOT V5 - bluestacks.py
#  Avvio parallelo, polling ADB, caricamento e chiusura istanze BlueStacks
#
#  CONTRATTO INTERFACCIA (comune con mumu.py):
#    NOME                              → str identificativo emulatore
#    assicura_avvio_manager(logger)    → bool
#    avvia_istanza(ist, logger)        → bool
#    avvia_blocco(blocco_ist, logger)  → list
#    attendi_e_raccogli_istanza(...)   → void
#    chiudi_istanza(ist, logger)       → void
#    chiudi_blocco(blocco_ist, logger) → void
#    cleanup_istanze_appese(pids, log) → void
#    _pids_istanze                     → dict
#    _pids_lock                        → Lock
# ==============================================================================

# Identificatore emulatore — usato da main.py per log e selezione
NOME = "BlueStacks"

import subprocess
import threading
import time
import adb
import config
import timing

# Nomi processo Multi Instance Manager (varianti secondo versione BlueStacks)
_MIM_PROCESSES = [
    "HD-MultiInstanceManager.exe",
    "BlueStacksMultiInstanceManager.exe",
]
# Attesa avvio MIM prima di procedere con le istanze
_MIM_ATTESA_AVVIO = 8   # secondi


def _mim_attivo() -> bool:
    """Ritorna True se almeno uno dei processi MIM è in esecuzione."""
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10
        )
        output = result.stdout.lower()
        return any(p.lower() in output for p in _MIM_PROCESSES)
    except Exception:
        return False


# ------------------------------------------------------------------------------
# Verifica e avvio automatico BlueStacks Multi Instance Manager
#
# Su Windows 11 il MIM deve essere in esecuzione PRIMA di avviare le istanze.
# Se non è attivo viene avviato automaticamente e si attende l'inizializzazione.
# Chiamare da main.py subito dopo la selezione emulatore BlueStacks.
# ------------------------------------------------------------------------------
def assicura_avvio_manager(logger=None) -> bool:
    """
    Verifica che BlueStacks Multi Instance Manager sia in esecuzione.
    Se non è attivo lo avvia automaticamente e attende l'inizializzazione.

    Ritorna True se MIM è operativo, False se non è stato possibile avviarlo.
    """
    def log(msg):
        if logger: logger("BS", msg)

    # Verifica se il processo è già in esecuzione
    if _mim_attivo():
        log("BlueStacks Multi Instance Manager già in esecuzione ✓")
        return True

    # Non è in esecuzione — avvialo
    mim_exe = getattr(config, "BS_MIM_EXE", "")
    if not mim_exe:
        log("ERRORE: BS_MIM_EXE non trovato in config.py — avvia manualmente il Multi Instance Manager")
        return False

    log(f"BlueStacks Multi Instance Manager non attivo — avvio automatico...")
    try:
        subprocess.Popen([mim_exe])
        log(f"MIM avviato — attendo {_MIM_ATTESA_AVVIO}s inizializzazione...")
        time.sleep(_MIM_ATTESA_AVVIO)

        if _mim_attivo():
            log("BlueStacks Multi Instance Manager avviato con successo ✓")
            return True
        else:
            log("WARN: MIM avviato ma processo non ancora visibile — procedo comunque")
            return True

    except Exception as e:
        log(f"ERRORE avvio MIM: {e}")
        return False

# Alias retrocompatibilità (usato da versioni precedenti di main.py)
assicura_multi_instance_manager = assicura_avvio_manager

# ------------------------------------------------------------------------------
# Hide finestra HD-Player per PID (pywin32)
# Cerca la finestra principale del processo e la nasconde con SW_HIDE.
# ADB continua a funzionare normalmente perché usa TCP, non la GUI.
# ------------------------------------------------------------------------------
try:
    import win32gui
    import win32process
    import win32con
    _WIN32_OK = True
except ImportError:
    _WIN32_OK = False

def _nascondi_finestra_pid(pid: int, logger=None, nome: str = "BS"):
    """
    Nasconde la finestra HD-Player associata al PID dato.
    Ritenta per max 10 secondi (la finestra appare qualche secondo dopo il processo).
    """
    if not _WIN32_OK or not config.BS_HIDE_WINDOW:
        return

    def log(msg):
        if logger: logger(nome, msg)

    def _trova_e_nascondi():
        trovata = []

        def callback(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return
            try:
                _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
                if found_pid == pid:
                    trovata.append(hwnd)
            except Exception:
                pass

        win32gui.EnumWindows(callback, None)

        if trovata:
            win32gui.ShowWindow(trovata[0], win32con.SW_HIDE)
            return True
        return False

    # Retry per 10s: la finestra appare qualche secondo dopo il Popen
    for _ in range(20):
        time.sleep(0.5)
        if _trova_e_nascondi():
            log(f"Finestra nascosta (PID={pid})")
            return

    log(f"WARN: finestra PID={pid} non trovata dopo 10s - non nascosta")

# Registro PID per istanza: { nome_interno: pid }
# Popolato da avvia_istanza() al momento del Popen, usato da chiudi_istanza()
# per garantire chiusura selettiva senza dipendere dal titolo della finestra.
_pids_istanze: dict = {}
_pids_lock = threading.Lock()

# ------------------------------------------------------------------------------
# Avvia una singola istanza BlueStacks
# ------------------------------------------------------------------------------
def avvia_istanza(ist: dict, logger=None) -> bool:
    nome    = ist["nome"]
    interno = ist["interno"]
    porta   = ist["porta"]

    def log(msg):
        if logger: logger(nome, msg)

    log(f"Avvio BlueStacks --instance {interno}...")
    try:
        proc = subprocess.Popen([config.BS_EXE, "--instance", interno])
        # Salva PID subito al Popen — usato da chiudi_istanza() per chiusura selettiva
        with _pids_lock:
            _pids_istanze[interno] = proc.pid
        log(f"BlueStacks avviato (PID={proc.pid})")
        # Nascondi finestra in background (non blocca l'avvio)
        threading.Thread(
            target=_nascondi_finestra_pid,
            args=(proc.pid, logger, nome),
            daemon=True
        ).start()
        return True
    except Exception as e:
        log(f"Errore avvio BS: {e}")
        return False

# ------------------------------------------------------------------------------
# Avvia un gruppo di istanze in parallelo + polling ADB + avvio gioco
# ------------------------------------------------------------------------------
def avvia_blocco(blocco_ist: list, logger=None) -> list:
    """
    1. Avvia tutte le istanze BS in parallelo
    2. Polling ADB ogni 5s fino a connessione (max TIMEOUT_ADB sec)
    3. Avvia gioco su quelle connesse
    """
    def log(msg):
        if logger: logger("BS", msg)

    log(f"Avvio blocco: {[i['nome'] for i in blocco_ist]}")

    # FASE 1 - Avvio parallelo BS
    threads = [threading.Thread(target=avvia_istanza, args=(ist, logger))
               for ist in blocco_ist]
    for t in threads: t.start()
    for t in threads: t.join()

    # FASE 2 - Polling ADB (ogni 5s, max TIMEOUT_ADB sec)
    log("Attesa connessione ADB (polling ogni 5s)...")
    avviate  = []
    connesse = set()
    scadenza = time.time() + config.TIMEOUT_ADB
    poll_n   = 0

    while time.time() < scadenza:
        poll_n += 1
        rimasto = int(scadenza - time.time())
        log(f"[POLL #{poll_n}] Tempo rimasto: {rimasto}s | Connesse: {list(connesse)} | In attesa: {[i['nome'] for i in blocco_ist if i['porta'] not in connesse]}")

        for ist in blocco_ist:
            nome  = ist["nome"]
            porta = ist["porta"]
            if porta in connesse:
                continue
            if logger: logger(nome, f"[POLL #{poll_n}] Tentativo connect 127.0.0.1:{porta}...")
            t0 = time.time()
            # connect
            import subprocess as _sp
            res_conn = _sp.run([config.ADB_EXE, "connect", f"127.0.0.1:{porta}"],
                               capture_output=True, text=True, timeout=10)
            if logger: logger(nome, f"[POLL #{poll_n}] connect → '{res_conn.stdout.strip()}' ({time.time()-t0:.1f}s)")
            # echo ok
            t1 = time.time()
            echo = adb.adb_shell(porta, "echo ok")
            if logger: logger(nome, f"[POLL #{poll_n}] echo ok → '{echo}' ({time.time()-t1:.1f}s)")
            if "ok" in echo:
                if logger: logger(nome, "ADB connesso")
                connesse.add(porta)
                if adb.avvia_gioco(porta):
                    if logger: logger(nome, "Gioco avviato")
                else:
                    if logger: logger(nome, "Errore avvio gioco")
                avviate.append(ist)
            else:
                if logger: logger(nome, f"[POLL #{poll_n}] echo fallito - riprovo al prossimo poll")

        if len(connesse) == len(blocco_ist):
            break
        time.sleep(5)

    mancanti = [i["nome"] for i in blocco_ist if i["porta"] not in connesse]
    if mancanti:
        log(f"ADB non connesso su: {mancanti}")
        # Killa i processi BS che non hanno risposto via ADB
        for ist in blocco_ist:
            if ist["porta"] not in connesse:
                nome_ist    = ist["nome"]
                interno_ist = ist["interno"]
                with _pids_lock:
                    pid_appeso = _pids_istanze.get(interno_ist, 0)
                if pid_appeso:
                    if logger: logger(nome_ist, f"ADB fallito - kill processo avviato (PID={pid_appeso})")
                    try:
                        subprocess.run(["taskkill", "/F", "/PID", str(pid_appeso)],
                                       capture_output=True, timeout=10)
                        with _pids_lock:
                            _pids_istanze.pop(interno_ist, None)
                    except Exception as e:
                        if logger: logger(nome_ist, f"Errore kill PID={pid_appeso}: {e}")

    log(f"Pronte per caricamento: {[i['nome'] for i in avviate]}")
    return avviate

# ------------------------------------------------------------------------------
# Attendi caricamento + raccolta per singola istanza (thread individuale)
# Delegato a emulatore_base.attendi_e_raccogli_istanza con fn_chiudi=chiudi_istanza
# ------------------------------------------------------------------------------
def attendi_e_raccogli_istanza(ist: list, fn_raccolta, risultati: dict,
                                on_completata=None, logger=None):
    import emulatore_base
    emulatore_base.attendi_e_raccogli_istanza(
        ist, fn_raccolta, risultati, chiudi_istanza, on_completata, logger
    )

# ------------------------------------------------------------------------------
# Chiudi una singola istanza BlueStacks
#
# Identifica il processo tramite il titolo della finestra (nome interno BS)
# in modo da NON toccare le altre istanze attive in parallelo.
# Metodo identico alla V2 AHK: WinGetPID(nome) → taskkill /F /PID
# ------------------------------------------------------------------------------
def chiudi_istanza(ist: dict, logger=None):
    nome    = ist["nome"]
    interno = ist["interno"]
    porta   = ist["porta"]

    def log(msg):
        if logger: logger(nome, msg)

    # 1. Ferma gioco via ADB
    try:
        adb.ferma_gioco(porta)
        log("Gioco fermato")
    except Exception as e:
        log(f"Errore ferma gioco: {e}")
    time.sleep(0.5)

    # 2. Disconnetti ADB dalla porta (evita socket zombie)
    try:
        subprocess.run([config.BS_ADB, "disconnect", f"127.0.0.1:{porta}"],
                       capture_output=True, timeout=5)
    except Exception:
        pass

    # 3. Trova PID dal registro (salvato al Popen) con fallback a WINDOWTITLE
    with _pids_lock:
        pid = _pids_istanze.get(interno, 0)

    if not pid:
        # Fallback: cerca per titolo finestra (meno affidabile ma utile se
        # il registro non è popolato, es. istanza già aperta prima del bot)
        pid = _get_pid_istanza(interno)

    if pid:
        try:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True, timeout=10)
            log(f"HD-Player chiuso (PID={pid})")
            # Rimuove dal registro
            with _pids_lock:
                _pids_istanze.pop(interno, None)
        except Exception as e:
            log(f"Errore chiusura PID={pid}: {e}")

        # 4. Verifica finale: controlla che il PID sia effettivamente sparito
        time.sleep(1.5)
        pids_attivi = _get_all_pids()
        if pid in pids_attivi:
            log(f"WARN: PID={pid} ancora presente dopo taskkill - secondo tentativo")
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                               capture_output=True, timeout=10)
                time.sleep(1)
                if pid in _get_all_pids():
                    log(f"WARN: PID={pid} ancora vivo dopo secondo tentativo")
                else:
                    log(f"HD-Player rimosso (secondo tentativo, PID={pid})")
            except Exception as e:
                log(f"Errore secondo tentativo kill PID={pid}: {e}")
    else:
        log(f"PID non trovato per istanza '{interno}' - già chiusa?")
        time.sleep(1)

# ------------------------------------------------------------------------------
# Chiudi blocco (cleanup emergenza / errore avvio)
# Chiude selettivamente solo le istanze del blocco passato, poi kill-server ADB.
# ------------------------------------------------------------------------------
def chiudi_blocco(blocco_ist: list, logger=None):
    def log(msg):
        if logger: logger("BS", msg)

    log(f"Chiusura blocco: {[i['nome'] for i in blocco_ist]}")
    for ist in blocco_ist:
        chiudi_istanza(ist, logger)

    try:
        subprocess.run([config.BS_ADB, "kill-server"],
                       capture_output=True, timeout=10)
    except:
        pass
    log("ADB server fermato - blocco chiuso")

# ------------------------------------------------------------------------------
# Utility interna: trova PID di una specifica istanza BlueStacks tramite
# titolo finestra. WINDOWTITLE eq <nome_interno> garantisce che venga
# identificata solo quell'istanza e non le altre in esecuzione.
# ------------------------------------------------------------------------------
def _get_pid_istanza(nome_interno: str) -> int:
    """
    Ritorna il PID del processo HD-Player.exe la cui finestra ha titolo
    uguale a nome_interno (es. 'Pie64_7'). Ritorna 0 se non trovato.
    """
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"WINDOWTITLE eq {nome_interno}",
             "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or "INFO:" in line:
                continue
            parts = line.split(",")
            if len(parts) >= 2:
                try:
                    return int(parts[1].strip('"'))
                except:
                    continue
    except:
        pass
    return 0

def _get_all_pids() -> list:
    """Ritorna tutti i PID di processi HD-Player.exe in esecuzione (utility debug)."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq HD-Player.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10
        )
        pids = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) >= 2:
                try:
                    pids.append(int(parts[1].strip('"')))
                except:
                    continue
        return pids
    except:
        return []

# ------------------------------------------------------------------------------
# Cleanup fine ciclo: elimina processi HD-Player.exe rimasti appesi
#
# Da chiamare in main.py dopo esegui_ciclo_pool(), prima del countdown.
# Confronta i PID ancora attivi con quelli gestiti nel ciclo:
#   - PID gestiti ancora vivi  → non si sono chiusi correttamente → kill
#   - PID NON gestiti attivi   → residui di cicli precedenti     → kill
# ------------------------------------------------------------------------------
def cleanup_istanze_appese(pids_gestiti: set, logger=None):
    """
    Controlla e killa tutti i processi HD-Player.exe rimasti attivi dopo
    la fine del ciclo.

    pids_gestiti: set di int con i PID avviati durante il ciclo corrente
                  (costruito in esegui_ciclo_pool tramite _pids_istanze snapshot)
    """
    def log(msg):
        if logger: logger("CLEANUP", msg)

    log("=== Controllo istanze appese a fine ciclo ===")
    pids_attivi = _get_all_pids()

    if not pids_attivi:
        log("Nessun HD-Player.exe attivo \u2713")
        return

    killati = []
    for pid in pids_attivi:
        if pid in pids_gestiti:
            log(f"PID={pid} era gestito ma ancora attivo \u2192 kill")
        else:
            log(f"PID={pid} NON gestito in questo ciclo (residuo) \u2192 kill")
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, timeout=10)
            killati.append(pid)
        except Exception as e:
            log(f"Errore kill PID={pid}: {e}")

    time.sleep(1)
    pids_ancora = _get_all_pids()
    superstiti  = [p for p in killati if p in pids_ancora]
    if superstiti:
        log(f"WARN: {len(superstiti)} processo/i ancora attivi dopo cleanup: {superstiti}")
    else:
        log(f"Cleanup completato - {len(killati)} processo/i terminati \u2713")
