# ==============================================================================
#  test_mumu.py  —  Test isolato mumu.py (step 2)
#  Eseguire dalla cartella V4: python test_mumu.py
#  Non richiede BlueStacks. Non avvia raccolta né gioco.
# ==============================================================================

import time
import sys

def log(nome, msg):
    from datetime import datetime
    print(f"[{datetime.now().strftime('%H:%M:%S')}][{nome}] {msg}")

# ------------------------------------------------------------------------------
print("\n" + "="*55)
print("  TEST MUMU.PY — Step 2")
print("="*55)

# Controlla import
try:
    import config
    import mumu
    print("[OK] Import config e mumu")
except ImportError as e:
    print(f"[ERRORE] Import fallito: {e}")
    sys.exit(1)

# Verifica MUMU_MANAGER configurato
print(f"[OK] MUMU_MANAGER = {config.MUMU_MANAGER}")
print(f"[OK] ISTANZE_MUMU = {config.ISTANZE_MUMU}")

# Istanza di test: FAU_02 (index=0)
ist = list(config.ISTANZE_MUMU[0])  # copia mutabile
nome_ist = ist[0]

# ------------------------------------------------------------------------------
print(f"\n--- 1. Info istanza {nome_ist} (spenta) ---")
info = mumu._mumu_info(0)
print(f"  is_process_started : {info.get('is_process_started')}")
print(f"  is_android_started : {info.get('is_android_started')}")
print(f"  pid                : {info.get('pid', 'N/A')}")

# ------------------------------------------------------------------------------
print(f"\n--- 2. Avvio istanza {nome_ist} ---")
ok = mumu.avvia_istanza(ist, log)
print(f"  avvia_istanza → {ok}")

# ------------------------------------------------------------------------------
print(f"\n--- 3. Info istanza dopo avvio ---")
info = mumu._mumu_info(0)
print(f"  is_process_started : {info.get('is_process_started')}")
print(f"  is_android_started : {info.get('is_android_started')}")
print(f"  adb_port           : {info.get('adb_port', 'N/A')}")
print(f"  pid                : {info.get('pid', 'N/A')}")
print(f"  player_state       : {info.get('player_state', 'N/A')}")

# ------------------------------------------------------------------------------
print(f"\n--- 4. Connessione ADB ---")
ok_adb, porta = mumu._mumu_adb_connect(0)
print(f"  ok={ok_adb}, porta={porta}")
if ok_adb:
    ist[2] = porta  # aggiorna porta reale
    print(f"  [OK] ADB connesso su porta {porta}")
else:
    print(f"  [WARN] ADB non connesso - verificare manualmente")

# ------------------------------------------------------------------------------
print(f"\n--- 5. info -v all ---")
tutte = mumu._mumu_info_all()
print(f"  Istanze trovate: {len(tutte)}")
for i in tutte:
    stato = "ATTIVA" if i.get("is_process_started") else "spenta"
    print(f"    [{i.get('index')}] {i.get('name')} — {stato}"
          + (f" pid={i.get('pid')} adb={i.get('adb_port')}" if i.get("is_process_started") else ""))

# ------------------------------------------------------------------------------
print(f"\n--- 6. _get_all_pids() ---")
pids = mumu._get_all_pids()
print(f"  PID istanze attive: {pids}")

# ------------------------------------------------------------------------------
print(f"\n--- 7. Chiusura istanza {nome_ist} (diagnostica dettagliata) ---")
print(f"  ist = {ist}")

indice = int(ist[1])
porta  = ist[2]

# Passo 1: ferma gioco
print("  [1] ferma_gioco...")
try:
    import adb as _adb
    _adb.ferma_gioco(porta)
    print("  [1] OK")
except Exception as e:
    print(f"  [1] ECCEZIONE: {e}")

# Passo 2: disconnect ADB diretto
print("  [2] adb disconnect...")
import subprocess
try:
    r = subprocess.run(
        [config.BS_ADB, "disconnect", f"127.0.0.1:{porta}"],
        capture_output=True, text=True, timeout=5
    )
    print(f"  [2] OK → {r.stdout.strip()}")
except Exception as e:
    print(f"  [2] ECCEZIONE: {e}")

# Passo 3: shutdown
print("  [3] control shutdown...")
try:
    r = subprocess.run(
        [config.MUMU_MANAGER, "control", "-v", str(indice), "shutdown"],
        capture_output=True, text=True, timeout=20
    )
    print(f"  [3] OK → {r.stdout.strip()}")
except Exception as e:
    print(f"  [3] ECCEZIONE: {e}")

import time
time.sleep(3)
info = mumu._mumu_info(0)
print(f"  is_process_started dopo shutdown: {info.get('is_process_started')}")
print(f"  player_state: {info.get('player_state', 'N/A')}")

# ------------------------------------------------------------------------------
print("\n" + "="*55)
print("  TEST COMPLETATO")
print("="*55)
print("Se tutti i passaggi mostrano valori attesi, mumu.py è pronto.")
print("Prossimo step: avviare main.py con [2] MuMuPlayer su 1 sola istanza.")