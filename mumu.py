# ==============================================================================
#  DOOMSDAY BOT V5 - mumu.py
#  Avvio, polling ADB, caricamento e chiusura istanze MuMuPlayer 12
#
#  Interfaccia identica a bluestacks.py — main.py e raccolta.py non cambiano.
#
#  MuMuPlayer 12 usa MuMuManager.exe (in nx_main\) come tool di controllo:
#    MuMuManager.exe control -v [index] launch    → avvia istanza
#    MuMuManager.exe control -v [index] shutdown  → chiude istanza
#    MuMuManager.exe adb -v [index] -c connect    → connette ADB (MuMu gestisce porta)
#    MuMuManager.exe adb -v [index] -c disconnect → disconnette ADB
#    MuMuManager.exe info -v [index]              → info istanza (include porta ADB)
#
#  Processo per singola istanza: MuMuNxDevice.exe
#  (MuMuNxMain.exe è solo il launcher GUI, non va killato per istanza)
#
#  CONTRATTO INTERFACCIA (comune con bluestacks.py):
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
NOME = "MuMuPlayer 12"

import subprocess
import threading
import time
import adb
import config

# Registro PID per istanza: { nome_interno: pid }
# MuMu non espone un PID diretto via Popen (lancia tramite MuMuManager),
# quindi usiamo il PID del processo MuMuNxDevice.exe trovato dopo l'avvio.
_pids_istanze: dict = {}
_pids_lock = threading.Lock()

# Nomi processo MuMuPlayer (varianti secondo versione)
_MUMU_PROCESSES = [
    "MuMuPlayer.exe",
    "MuMuNxMain.exe",
]

# ------------------------------------------------------------------------------
# Verifica e avvio automatico MuMuPlayer
#
# Contratto comune con bluestacks.assicura_avvio_manager():
#   - ritorna True  se MuMu è operativo (già attivo o appena avviato)
#   - ritorna False se non è stato possibile avviarlo
# Chiamare da main.py subito dopo la selezione emulatore MuMuPlayer.
# ------------------------------------------------------------------------------
def assicura_avvio_manager(logger=None) -> bool:
    """
    Verifica che MuMuPlayer sia in esecuzione e che MuMuManager.exe sia
    raggiungibile. Se MuMuPlayer non è attivo tenta di avviarlo tramite
    MuMuManager launch.

    Ritorna True se l'ambiente MuMu è operativo, False altrimenti.
    """
    def log(msg):
        if logger: logger("MUMU", msg)

    # 1. Verifica che MuMuManager.exe sia configurato
    if not config.MUMU_MANAGER:
        log("ERRORE: MUMU_MANAGER non trovato in config.py — verifica il percorso di installazione")
        return False

    # 2. Verifica se MuMuPlayer è già in esecuzione
    if _mumu_player_attivo():
        log("MuMuPlayer già in esecuzione ✓")
        return True

    # 3. Non è in esecuzione — prova ad avviare la prima istanza disponibile
    # (MuMuPlayer non ha un manager separato: basta avviare una qualsiasi istanza
    #  perché il processo principale MuMuNxMain.exe parta automaticamente)
    log("MuMuPlayer non attivo — tentativo avvio tramite MuMuManager...")
    try:
        result = subprocess.run(
            [config.MUMU_MANAGER, "control", "-v", "0", "launch"],
            capture_output=True, text=True, timeout=20
        )
        log(f"MuMuManager launch → {result.stdout.strip() or 'OK'}")

        # Attendi che il processo principale sia visibile
        for _ in range(10):
            time.sleep(2)
            if _mumu_player_attivo():
                log("MuMuPlayer avviato con successo ✓")
                return True

        log("WARN: MuMuPlayer avviato ma processo non ancora visibile — procedo comunque")
        return True

    except Exception as e:
        log(f"ERRORE avvio MuMuPlayer: {e}")
        return False


def _mumu_player_attivo() -> bool:
    """Ritorna True se almeno uno dei processi MuMuPlayer è in esecuzione."""
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10
        )
        output = result.stdout.lower()
        return any(p.lower() in output for p in _MUMU_PROCESSES)
    except Exception:
        return False

# ------------------------------------------------------------------------------
# Avvia una singola istanza MuMuPlayer
# ------------------------------------------------------------------------------
def avvia_istanza(ist: dict, logger=None) -> bool:
    nome   = ist["nome"]
    indice = _indice_da_interno(ist["indice"])

    def log(msg):
        if logger: logger(nome, msg)

    log(f"Avvio MuMuPlayer index={indice} ({nome})...")
    try:
        result = subprocess.run(
            [config.MUMU_MANAGER, "control", "-v", str(indice), "launch"],
            capture_output=True, text=True, timeout=20
        )
        log(f"MuMuManager launch → {result.stdout.strip() or 'OK'}")

        # Polling is_process_started per registrare il PID appena disponibile
        for _ in range(10):
            time.sleep(2)
            info = _mumu_info(indice)
            if info.get("is_process_started"):
                pid = info.get("pid", 0)
                if pid:
                    with _pids_lock:
                        _pids_istanze[ist["indice"]] = pid
                    log(f"Processo avviato (PID={pid})")
                    return True
        log("WARN: processo non rilevato entro 20s - continuo comunque")
        return True
    except Exception as e:
        log(f"Errore avvio MuMu: {e}")
        return False

# ------------------------------------------------------------------------------
# Avvia un gruppo di istanze in parallelo + polling ADB + avvio gioco
# ------------------------------------------------------------------------------
def avvia_blocco(blocco_ist: list, logger=None) -> list:
    """
    1. Avvia tutte le istanze MuMu in parallelo via MuMuManager
    2. Polling ADB ogni 5s: usa MuMuManager adb -c connect (MuMu gestisce la porta)
       Poi ricava la porta reale da 'info' per le chiamate ADB successive
    3. Avvia gioco su quelle connesse
    """
    def log(msg):
        if logger: logger("MUMU", msg)

    log(f"Avvio blocco: {[i['nome'] for i in blocco_ist]}")

    # FASE 1 - Avvio parallelo
    threads = [threading.Thread(target=avvia_istanza, args=(ist, logger))
               for ist in blocco_ist]
    for t in threads: t.start()
    for t in threads: t.join()

    # FASE 2 - Polling ADB (ogni 5s, max TIMEOUT_ADB sec)
    # Prima aspetta is_android_started=True via info (leggero),
    # poi tenta adb connect solo quando Android è pronto.
    log("Attesa connessione ADB (polling ogni 5s)...")
    avviate  = []
    connesse = set()   # set di indici (non porte) già connessi
    scadenza = time.time() + config.TIMEOUT_ADB

    while time.time() < scadenza:
        for ist in blocco_ist:
            nome   = ist["nome"]
            indice = _indice_da_interno(ist["indice"])
            if indice in connesse:
                continue

            # Check leggero: Android pronto?
            info = _mumu_info(indice)
            if not info.get("is_android_started", False):
                stato = info.get("player_state", "?")
                if logger: logger(nome, f"Android non ancora pronto ({stato}) - attendo...")
                continue

            # Android pronto → tenta connessione ADB
            ok, porta_reale = _mumu_adb_connect(indice)
            if ok and porta_reale:
                ist["porta"] = porta_reale
                if logger: logger(nome, f"ADB connesso (porta={porta_reale})")
                connesse.add(indice)
                if adb.avvia_gioco(porta_reale):
                    if logger: logger(nome, "Gioco avviato")
                else:
                    if logger: logger(nome, "Errore avvio gioco")
                avviate.append(ist)

        if len(connesse) == len(blocco_ist):
            break
        time.sleep(5)

    mancanti = [i["nome"] for i in blocco_ist if _indice_da_interno(i["indice"]) not in connesse]
    if mancanti:
        log(f"ADB non connesso su: {mancanti}")
        for ist in blocco_ist:
            if _indice_da_interno(ist["indice"]) not in connesse:
                nome_ist    = ist["nome"]
                interno_ist = ist["indice"]
                indice_ist  = _indice_da_interno(interno_ist)
                if logger: logger(nome_ist, f"ADB fallito - shutdown istanza (index={indice_ist})")
                try:
                    subprocess.run(
                        [config.MUMU_MANAGER, "control", "-v", str(indice_ist), "shutdown"],
                        capture_output=True, timeout=15
                    )
                    with _pids_lock:
                        _pids_istanze.pop(interno_ist, None)
                except Exception as e:
                    if logger: logger(nome_ist, f"Errore shutdown MuMu: {e}")

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
# Chiudi una singola istanza MuMuPlayer
# ------------------------------------------------------------------------------
def chiudi_istanza(ist: dict, logger=None):
    nome   = ist["nome"]
    indice = _indice_da_interno(ist["indice"])
    porta  = ist["porta"]

    def log(msg):
        if logger: logger(nome, msg)

    # 1. Ferma gioco via ADB
    try:
        adb.ferma_gioco(porta)
        log("Gioco fermato")
    except Exception as e:
        log(f"Errore ferma gioco: {e}")
    time.sleep(0.5)

    # 2. Disconnetti ADB direttamente
    try:
        subprocess.run(
            [config.ADB_EXE, "disconnect", f"127.0.0.1:{porta}"],
            capture_output=True, timeout=5
        )
    except Exception:
        pass

    # 3. Chiudi via MuMuManager
    try:
        result = subprocess.run(
            [config.MUMU_MANAGER, "control", "-v", str(indice), "shutdown"],
            capture_output=True, text=True, timeout=20
        )
        log(f"MuMuPlayer shutdown (index={indice}) → {result.stdout.strip() or 'OK'}")
        with _pids_lock:
            _pids_istanze.pop(ist["indice"], None)
    except Exception as e:
        log(f"Errore chiusura MuMu (index={indice}): {e}")

    # 4. Verifica finale: se l'istanza è ancora attiva dopo 2s → kill diretto sul PID
    time.sleep(2)
    if _istanza_attiva(indice):
        # Recupera PID aggiornato dal registro o da info
        with _pids_lock:
            pid = _pids_istanze.get(ist["indice"], 0)
        if not pid:
            pid = _get_pid_istanza_mumu(indice)
        if pid:
            log(f"WARN: istanza ancora attiva dopo shutdown (PID={pid}) - kill forzato")
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                               capture_output=True, timeout=10)
                time.sleep(1)
                if _istanza_attiva(indice):
                    log(f"WARN: istanza ancora viva dopo kill forzato")
                else:
                    log(f"PID={pid} terminato (kill forzato)")
            except Exception as e:
                log(f"Errore kill forzato PID={pid}: {e}")
        else:
            log("WARN: istanza ancora attiva ma PID non trovato")

# ------------------------------------------------------------------------------
# Chiudi blocco (cleanup emergenza)
# ------------------------------------------------------------------------------
def chiudi_blocco(blocco_ist: list, logger=None):
    def log(msg):
        if logger: logger("MUMU", msg)

    log(f"Chiusura blocco: {[i['nome'] for i in blocco_ist]}")
    for ist in blocco_ist:
        chiudi_istanza(ist, logger)

    try:
        subprocess.run([config.MUMU_ADB, "kill-server"],
                       capture_output=True, timeout=10)
    except:
        pass
    log("ADB server fermato - blocco chiuso")

# ------------------------------------------------------------------------------
# Cleanup fine ciclo: elimina processi MuMuNxDevice.exe rimasti appesi
# ------------------------------------------------------------------------------
def cleanup_istanze_appese(pids_gestiti: set, logger=None):
    def log(msg):
        if logger: logger("CLEANUP", msg)

    log("=== Controllo istanze appese a fine ciclo ===")
    pids_attivi = _get_all_pids()

    if not pids_attivi:
        log("Nessun MuMuNxDevice.exe attivo ✓")
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

# ------------------------------------------------------------------------------
# ------------------------------------------------------------------------------
# Utility: connette ADB tramite MuMuManager e ritorna (ok, porta_reale)
# MuMuManager gestisce la porta internamente; la porta reale viene poi letta
# da 'info' per le chiamate ADB successive (screenshot, keyevent, ecc.)
# ------------------------------------------------------------------------------
def _mumu_adb_connect(indice: int) -> tuple:
    """
    Connette ADB tramite MuMuManager e ritorna (True, porta) se ok.
    Output JSON: {"adb_host": "127.0.0.1", "adb_port": 16384, "cmd_output": "connected to ..."}
    """
    try:
        result = subprocess.run(
            [config.MUMU_MANAGER, "adb", "-v", str(indice), "-c", "connect"],
            capture_output=True, text=True, timeout=15
        )
        import json
        data = json.loads(result.stdout.strip())
        porta = data.get("adb_port", 0)
        cmd_out = data.get("cmd_output", "")
        if porta and ("connected" in cmd_out.lower() or "already connected" in cmd_out.lower()):
            return (True, porta)
        # Fallback: porta presente anche se cmd_output anomalo
        if porta:
            return (True, porta)
    except Exception:
        pass
    return (False, 0)

# ------------------------------------------------------------------------------
# Utility: ricava la porta ADB reale di un'istanza tramite 'info'
# Output di 'info' contiene una riga tipo: "adb_host_port: 16384"
# ------------------------------------------------------------------------------
def _get_porta_istanza(indice: int) -> int:
    """Legge adb_port dal JSON di MuMuManager info -v <indice>."""
    info = _mumu_info(indice)
    return info.get("adb_port", 0)

# ------------------------------------------------------------------------------
# Utility: ricava l'indice numerico MuMu dall'identificatore interno
# L'identificatore interno in config.ISTANZE per MuMu è la stringa dell'indice:
#   "0" → FAU_02, "1" → FAU_07, "2" → FAU_03, "3" → FAU_04
# ------------------------------------------------------------------------------
# ------------------------------------------------------------------------------
# Utility: ricava l'indice numerico MuMu dall'identificatore interno
# L'identificatore interno in ISTANZE_MUMU è la stringa dell'indice:
#   "0" → FAU_02, "1" → FAU_07, "2" → FAU_03, "3" → FAU_04
# ------------------------------------------------------------------------------
def _indice_da_interno(interno: str) -> int:
    try:
        return int(interno)
    except ValueError:
        return 0

def _mumu_info(indice: int) -> dict:
    """
    Chiama MuMuManager info -v <indice> e ritorna il JSON parsato.
    Ritorna dict vuoto in caso di errore.
    """
    try:
        result = subprocess.run(
            [config.MUMU_MANAGER, "info", "-v", str(indice)],
            capture_output=True, text=True, timeout=10
        )
        import json
        return json.loads(result.stdout.strip())
    except Exception:
        return {}

def _mumu_info_all() -> list:
    """
    Chiama MuMuManager info -v all e ritorna lista di dict.
    Output reale: {"0": {...}, "1": {...}, ...} — dict con chiavi stringa numeriche.
    """
    try:
        result = subprocess.run(
            [config.MUMU_MANAGER, "info", "-v", "all"],
            capture_output=True, text=True, timeout=15
        )
        import json
        data = json.loads(result.stdout.strip())
        if isinstance(data, dict):
            # Chiavi "0","1","2"... → estrai i valori ordinati per indice
            return [v for k, v in sorted(data.items(), key=lambda x: int(x[0]))]
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []

# ------------------------------------------------------------------------------
# Utility: trova PID del processo MuMuNxDevice.exe per un dato indice istanza.
# MuMu lancia un processo per istanza con argomento "-v <indice>" nella cmdline.
# ------------------------------------------------------------------------------
def _get_pid_istanza_mumu(indice: int) -> int:
    """Legge il PID del processo istanza dal JSON di MuMuManager info."""
    info = _mumu_info(indice)
    return info.get("pid", 0)

# ------------------------------------------------------------------------------
# Utility: verifica se un PID è ancora attivo
# ------------------------------------------------------------------------------
def _pid_attivo(pid: int) -> bool:
    """Verifica se un PID è ancora attivo tramite tasklist."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=5
        )
        return str(pid) in result.stdout
    except:
        return False

def _istanza_attiva(indice: int) -> bool:
    """Verifica se un'istanza MuMu è ancora in esecuzione tramite info JSON."""
    info = _mumu_info(indice)
    return info.get("is_process_started", False)

# ------------------------------------------------------------------------------
# Utility: tutti i PID MuMuNxDevice.exe attivi
# ------------------------------------------------------------------------------
def _get_all_pids() -> list:
    """
    Ritorna tutti i PID di istanze MuMu in esecuzione.
    Usa MuMuManager info -v all per leggere pid dal JSON.
    Fallback a tasklist MuMuNxDevice.exe se info all fallisce.
    """
    pids = []
    try:
        istanze = _mumu_info_all()
        for ist in istanze:
            if ist.get("is_process_started", False):
                pid = ist.get("pid", 0)
                if pid:
                    pids.append(pid)
        if pids:
            return pids
    except Exception:
        pass

    # Fallback: tasklist
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq MuMuNxDevice.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10
        )
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
    except Exception:
        pass
    return pids