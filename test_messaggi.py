# test_messaggi.py
import sys
sys.path.insert(0, r"E:\Bot-raccolta\V5")

import config
config.ADB_EXE = config.BS_ADB

import adb
import messaggi

def log(nome, msg):
    print(f"[{nome}] {msg}")

# Connetti ADB prima di tutto
adb.connetti("5555")

# Testa raccolta messaggi
messaggi.raccolta_messaggi("5555", "FAU_02", log)