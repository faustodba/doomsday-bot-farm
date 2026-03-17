# ==============================================================================
#  DOOMSDAY BOT V5 - config.py
#  Parametri globali di configurazione
#
#  SEZIONI:
#    1. Percorsi eseguibili  (BlueStacks, MuMuPlayer, Tesseract, ADB)
#    2. Verifica percorsi    (_verifica_percorsi — chiamata subito dopo)
#    3. Istanze              (ISTANZE per BS, ISTANZE_MUMU per MuMu)
#    4. Parametri ciclo      (ISTANZE_BLOCCO, WAIT_MINUTI, raccolta)
#    5. Coordinate UI        (tap, OCR, layout barra)
#    6. Rilevamento stato    (pixel check home/mappa)
#    7. Timing               (delay, timeout)
#    8. Task periodici       (messaggi, alleanza, rifornimento)
# ==============================================================================

import os as _os

# ==============================================================================
# 1. PERCORSI ESEGUIBILI
# ==============================================================================

BOT_DIR = _os.path.dirname(_os.path.abspath(__file__))

def _trova_exe(*candidati):
    for p in candidati:
        if _os.path.isfile(p):
            return p
    return ""

# --- BlueStacks ---
BS_EXE = _trova_exe(
    r"C:\Program Files\BlueStacks_nxt\HD-Player.exe",
    r"C:\Program Files (x86)\BlueStacks_nxt\HD-Player.exe",
    r"D:\Program Files\BlueStacks_nxt\HD-Player.exe",
    r"E:\Program Files\BlueStacks_nxt\HD-Player.exe",
)
BS_MIM_EXE = _trova_exe(
    r"C:\Program Files\BlueStacks_nxt\HD-MultiInstanceManager.exe",
    r"C:\Program Files (x86)\BlueStacks_nxt\HD-MultiInstanceManager.exe",
    r"D:\Program Files\BlueStacks_nxt\HD-MultiInstanceManager.exe",
    r"E:\Program Files\BlueStacks_nxt\HD-MultiInstanceManager.exe",
    r"C:\Program Files\BlueStacks_nxt\BlueStacksMultiInstanceManager.exe",
    r"C:\Program Files (x86)\BlueStacks_nxt\BlueStacksMultiInstanceManager.exe",
    r"D:\Program Files\BlueStacks_nxt\BlueStacksMultiInstanceManager.exe",
    r"E:\Program Files\BlueStacks_nxt\BlueStacksMultiInstanceManager.exe",
)
BS_ADB = _trova_exe(
    r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe",
    r"C:\Program Files (x86)\BlueStacks_nxt\HD-Adb.exe",
    r"D:\Program Files\BlueStacks_nxt\HD-Adb.exe",
    r"E:\Program Files\BlueStacks_nxt\HD-Adb.exe",
)
BS_HIDE_WINDOW = False  # True = nasconde finestra HD-Player (richiede pywin32)

# --- MuMuPlayer ---
MUMU_ADB = _trova_exe(
    r"C:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe",
    r"C:\Program Files (x86)\Netease\MuMuPlayer\nx_main\adb.exe",
    r"D:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe",
)
MUMU_MANAGER = _trova_exe(
    r"C:\Program Files\Netease\MuMuPlayer\nx_main\MuMuManager.exe",
    r"C:\Program Files (x86)\Netease\MuMuPlayer\nx_main\MuMuManager.exe",
    r"D:\Program Files\Netease\MuMuPlayer\nx_main\MuMuManager.exe",
)

# --- Comune ---
# ADB_EXE: default BS, main.py lo sovrascrive a runtime in base all'emulatore scelto
ADB_EXE = BS_ADB

TESSERACT_EXE = _trova_exe(
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    r"D:\Program Files\Tesseract-OCR\tesseract.exe",
)

GAME_ACTIVITY = "com.igg.android.doomsdaylastsurvivors/com.gpc.sdk.unity.GPCSDKMainActivity"

# ==============================================================================
# 2. VERIFICA PERCORSI ALL'AVVIO
# BS e MuMu sono entrambi opzionali: serve solo quello dell'emulatore scelto.
# ==============================================================================
def _verifica_percorsi():
    print(f"[CONFIG] BOT_DIR      = {BOT_DIR}")
    comuni = {"TESSERACT_EXE": TESSERACT_EXE}
    bs     = {"BS_EXE": BS_EXE, "BS_ADB": BS_ADB, "BS_MIM_EXE": BS_MIM_EXE}
    mumu   = {"MUMU_ADB": MUMU_ADB, "MUMU_MANAGER": MUMU_MANAGER}
    for nome, val in comuni.items():
        if val:
            print(f"[CONFIG] {nome:<16} = {val}")
        else:
            print(f"[CONFIG] *** ATTENZIONE: {nome} non trovato — OCR non disponibile")
    for nome, val in bs.items():
        stato = val if val else "(non trovato — necessario solo per BlueStacks)"
        print(f"[CONFIG] {nome:<16} = {stato}")
    for nome, val in mumu.items():
        stato = val if val else "(non trovato — necessario solo per MuMuPlayer)"
        print(f"[CONFIG] {nome:<16} = {stato}")

_verifica_percorsi()

# ==============================================================================
# 3. ISTANZE
#
# Struttura comune (6 campi):
#   [nome, interno, porta_adb, truppe_raccolta, max_squadre, layout_barra]
#
#   nome           : identificatore istanza (es. FAU_00)
#   interno        : nome interno BS (es. "Pie64") OPPURE indice MuMu (es. "0")
#   porta_adb      : porta TCP ADB (BS: fissa; MuMu: aggiornata a runtime)
#   truppe_raccolta: truppe per squadra (0 = MAX, None = usa TRUPPE_RACCOLTA globale)
#   max_squadre    : max raccoglitori da inviare (1-5, 0 = tutte le libere)
#   layout_barra   : 1 = standard 5 icone | 2 = compatto 4 icone (no Bestia)
# ==============================================================================

# --- BlueStacks ---
ISTANZE = [
    #["FAU_00", "Pie64_13", "5685", 0,     5, 1],
    #["FAU_01", "Pie64_6",  "5615", 12000, 4, 1],
    #["FAU_02", "Pie64",    "5555", 12000, 4, 1],
    #["FAU_03", "Pie64_7",  "5625", 12000, 4, 1],
    #["FAU_04", "Pie64_8",  "5635", 12000, 4, 1],
    #["FAU_05", "Pie64_9",  "5645", 12000, 4, 1],
    #["FAU_06", "Pie64_11", "5665", 12000, 4, 1],
    #["FAU_07", "Pie64_10", "5655", 12000, 4, 1],
    ["FAU_08", "Pie64_12", "5675", 12000, 4, 1],
    ["FAU_09", "Pie64_14", "5695", 12000, 4, 2],  # layout 2: 4 icone, no Bestia
]

# --- MuMuPlayer ---
# Struttura (7 campi):
# [nome, indice_mumu, porta_adb, truppe_raccolta, max_squadre, layout_barra, lingua]
#
#   lingua: "it" = italiano (default) | "en" = inglese
#           Usato per selezionare il template corretto del pulsante rifornimento
ISTANZE_MUMU = [
    ["FAU_00", "0", 16384, 0,     5, 1, "en"],
    ["FAU_01", "1", 16384, 12000, 4, 1, "en"],  # gioco in inglese
    ["FAU_02", "2", 16384, 12000, 4, 1, "en"],  # gioco in inglese
    ["FAU_03", "3", 16384, 12000, 4, 1, "en"],  # gioco in inglese
    ["FAU_04", "4", 16384, 12000, 4, 1, "en"],  # gioco in inglese
    ["FAU_05", "5", 16384, 12000, 4, 1, "en"],  # gioco in inglese
    ["FAU_06", "6", 16384, 12000, 4, 1, "en"],  # gioco in inglese
    ["FAU_07", "7", 16384, 12000, 4, 1, "en"],  # gioco in inglese    
    ["FAU_08", "8", 16384, 12000, 4, 1, "en"],  # gioco in inglese
    ["FAU_09", "9", 16384, 12000, 4, 2, "en"],  # gioco in italiano, layout 2
]

# ==============================================================================
# 4. PARAMETRI CICLO
# ==============================================================================

ISTANZE_BLOCCO         = 2      # istanze attive contemporaneamente (semaforo)
WAIT_MINUTI            = 1      # minuti di attesa tra un ciclo e l'altro

# --- Raccolta risorse ---
TRUPPE_RACCOLTA        = 10000  # truppe per squadra globale (0 = MAX)
MAX_TENTATIVI_RACCOLTA = 2      # tentativi massimi per singola squadra

# ==============================================================================
# 5. COORDINATE UI  (risoluzione 960x540)
# ==============================================================================

# --- Layout barra inferiore ---
COORD_ALLEANZA_LAYOUT = {
    1: (760, 505),   # standard — 5 icone (Campagna/Zaino/Alleanza/Bestia/Eroe)
    2: (800, 505),   # compatto — 4 icone (Campagna/Zaino/Alleanza/Eroe) — no Bestia
}

def get_coord_alleanza(ist: list) -> tuple:
    """Ritorna coordinate pulsante Alleanza per l'istanza data."""
    layout = ist[5] if len(ist) > 5 else 1
    return COORD_ALLEANZA_LAYOUT.get(layout, COORD_ALLEANZA_LAYOUT[1])

# --- Tap principali ---
TAP_LENTE             = (38,  325)
TAP_LENTE_COORD       = (380,  18)   # lente piccola → popup coordinate
TAP_CAMPO             = (410, 450)
TAP_SEGHERIA          = (535, 450)
TAP_CERCA_CAMPO       = (410, 350)
TAP_CERCA_SEGHERIA    = (536, 351)
TAP_ACCIAIERIA        = (672, 490)
TAP_CERCA_ACCIAIERIA  = (672, 350)
TAP_RAFFINERIA        = (820, 490)
TAP_CERCA_RAFFINERIA  = (820, 350)
TAP_NODO              = (480, 280)
TAP_RACCOGLI          = (230, 390)
TAP_SQUADRA           = (700, 185)
TAP_MARCIA            = (727, 476)
TAP_TOGGLE_HOME_MAPPA = (38,  505)   # rifugio <-> mappa
TAP_CANCELLA          = (527, 469)
TAP_CAMPO_TESTO       = (748,  75)
TAP_OK_TASTIERA       = (879, 487)
TAP_LIVELLO_PIU       = (650, 286)
TAP_LIVELLO_MENO      = (430, 288)
LIVELLO_RACCOLTA      = 6

# --- OCR contatore squadre ---
OCR_ZONA = (855, 115, 945, 145)   # crop screenshot per OCR "X/4"

# --- OCR ETA Marcia ---
OCR_MARCIA_ETA_ZONA       = (650, 440, 790, 465)
OCR_MARCIA_ETA_BASE_W     = 960
OCR_MARCIA_ETA_BASE_H     = 540
OCR_MARCIA_ETA_DEBUG_SAVE = False  # True = salva crop falliti in debug_eta/
OCR_MARCIA_ETA_MARGINE_S  = 5     # secondi extra dopo ETA reale
OCR_MARCIA_ETA_MIN_S      = 8     # attesa minima anche se ETA molto bassa

# --- Coordinate Messaggi ---
MSG_ICONA_X        = 928
MSG_ICONA_Y        = 430
MSG_TAB_ALLEANZA_X = 320
MSG_TAB_ALLEANZA_Y = 28
MSG_TAB_SISTEMA_X  = 455
MSG_TAB_SISTEMA_Y  = 28
MSG_LEGGI_X        = 95
MSG_LEGGI_Y        = 510

# ==============================================================================
# 6. RILEVAMENTO STATO  (pixel check home/mappa/banner)
# ==============================================================================

STATO_CHECK_X  = 40
STATO_CHECK_Y  = 505
STATO_SOGLIA_R = 160   # R<160=home, R>160=mappa, RGB<30=banner

STATO_CHECK_OFFSETS = [
    (0, 0), (-2, 0), (2, 0), (0, -2), (0, 2), (-2, -2), (2, 2)
]
STATO_MIN_MAPPA_RGB_SUM = 20

# --- Popup "Uscire dal gioco?" ---
POPUP_CHECK_X   = 480
POPUP_CHECK_Y   = 270
POPUP_ANNULLA_X = 370
POPUP_ANNULLA_Y = 383
POPUP_OK_X      = 590
POPUP_OK_Y      = 367

# Colore beige (pixel centrale popup)
BEIGE_R_MIN = 140;  BEIGE_R_MAX = 220
BEIGE_G_MIN = 130;  BEIGE_G_MAX = 210
BEIGE_B_MIN = 110;  BEIGE_B_MAX = 190

# Colore giallo (pulsante OK popup)
POPUP_OK_R_MIN = 190;  POPUP_OK_R_MAX = 255
POPUP_OK_G_MIN = 130;  POPUP_OK_G_MAX = 200
POPUP_OK_B_MIN = 40;   POPUP_OK_B_MAX = 100

# ==============================================================================
# 7. TIMING
# ==============================================================================

DELAY_AVVIO       = 5000   # ms pausa tra avvio istanze BS
TIMEOUT_BS        = 60     # secondi attesa finestra BS
TIMEOUT_ADB       = 120    # secondi attesa connessione ADB
TIMEOUT_CARICA    = 180    # secondi attesa caricamento gioco
DELAY_CARICA_INIZ = 45     # secondi attesa iniziale caricamento
DELAY_GIRO        = 2      # secondi pausa tra giri di polling
POLL_MS           = 1000   # ms intervallo polling
DELAY_CERCA       = 5000   # ms attesa dopo CERCA
DELAY_MARCIA      = 4000   # ms attesa dopo MARCIA

# ==============================================================================
# 8. TASK PERIODICI
# ==============================================================================

# --- Schedulazione ---
SCHEDULE_ORE_MESSAGGI = 12   # ore minime tra esecuzioni raccolta messaggi
SCHEDULE_ORE_ALLEANZA = 12   # ore minime tra esecuzioni raccolta alleanza

# --- Rifornimento alleanza ---
RIFORNIMENTO_ABILITATO         = True
DOOMS_ACCOUNT                  = "FauMorfeus"
DOOMS_AVATAR                   = "templates/avatar_faumorfeus.png"
RIFORNIMENTO_BTN_TEMPLATE      = "templates/btn_risorse_approv.png"       # IT
RIFORNIMENTO_BTN_TEMPLATE_EN   = "templates/btn_supply_resources.png"     # EN
RIFORNIMENTO_SOGLIA_M          = 5.0
RIFORNIMENTO_SOGLIA_PETROLIO_M = 2.5
RIFORNIMENTO_QTA_POMODORO      = 999_000_000
RIFORNIMENTO_QTA_LEGNO         = 999_000_000
RIFORNIMENTO_QTA_ACCIAIO       = 0
RIFORNIMENTO_QTA_PETROLIO      = 999_000_000

def get_lingua(ist: list) -> str:
    """Ritorna la lingua dell'istanza ('it' o 'en'). Default 'it'."""
    return ist[6] if len(ist) > 6 else "it"

def get_btn_rifornimento_template(ist: list) -> str:
    """Ritorna il path del template pulsante rifornimento per la lingua dell'istanza."""
    if get_lingua(ist) == "en":
        return RIFORNIMENTO_BTN_TEMPLATE_EN
    return RIFORNIMENTO_BTN_TEMPLATE
