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

# ==============================================================================
# DEBUG — sezione unica per tutti i flag e le cartelle di debug
#
#  Struttura su disco (tutte sotto DEBUG_DIR):
#    debug/
#      ciclo/ciclo_NNN/{istanza}/   ← screen raccolta per ciclo (debug.py)
#      stato/                        ← screen rilevamento stato
#      squadre/                      ← crop contatore squadre + OCR
#      eta/                          ← crop OCR ETA marcia falliti
#      screen/                       ← screen_{porta}.png temporanei
#
#  Master switch: DEBUG_ABILITATO=False → zero I/O debug su disco.
#  I flag per-modulo sono ignorati se DEBUG_ABILITATO=False.
# ==============================================================================

DEBUG_DIR       = _os.path.join(BOT_DIR, "debug")
DEBUG_ABILITATO = True    # master switch — False = nessun file debug scritto

DEBUG_RACCOLTA  = False   # salva screen fasi raccolta (debug.salva_screen)
DEBUG_STATO     = False   # salva screen rilevamento stato
DEBUG_SQUADRE   = True    # salva crop contatore squadre + risultati OCR
DEBUG_ETA       = False   # salva crop OCR ETA marcia quando fallisce

def _debug_path(*parti) -> str:
    """Ritorna path assoluto dentro DEBUG_DIR. Crea la cartella se necessario."""
    path = _os.path.join(DEBUG_DIR, *parti)
    _os.makedirs(path, exist_ok=True)
    return path

def _screen_dir() -> str:
    """Cartella screen temporanei istanza (screen_{porta}.png)."""
    return _debug_path("screen")

def _debug_modulo(modulo: str) -> str:
    """Ritorna cartella debug per il modulo dato (stato/squadre/eta/...)."""
    return _debug_path(modulo)

def _debug_abilitato(flag: bool) -> bool:
    """Ritorna True solo se DEBUG_ABILITATO=True E il flag specifico=True."""
    return DEBUG_ABILITATO and flag

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
# ADB_EXE: default MuMu, main.py lo sovrascrive a runtime in base all'emulatore scelto
ADB_EXE = MUMU_ADB or BS_ADB

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
# Ogni istanza è un dizionario con i seguenti campi:
#
#   CAMPI COMUNI:
#     nome        : identificatore istanza (es. "FAU_00")
#     porta       : porta TCP ADB
#     truppe      : truppe per squadra (0 = MAX, None = usa TRUPPE_RACCOLTA globale)
#     max_squadre : max raccoglitori da inviare (1-5, 0 = tutte le libere)
#     layout      : 1 = barra standard 5 icone | 2 = compatto 4 icone (no Bestia)
#     livello     : livello nodo da cercare (1-6, default 6) — sovrascrivibile da runtime
#     abilitata   : True = partecipa al ciclo | False = visibile in dashboard ma esclusa
    #     fascia_oraria: fascia di funzionamento "HH:MM-HH:MM" (default assente = H24)
    #                   start < end → fascia diurna (es. "08:00-18:00")
    #                   start > end → fascia notturna span mezzanotte (es. "22:00-05:00")
    #                   assente o "" → funzionamento H24
#
#   SOLO BlueStacks:
#     interno     : nome interno BS (es. "Pie64_12")
#
#   SOLO MuMuPlayer:
#     indice      : indice MuMu (es. "8")
#     lingua      : "it" = italiano | "en" = inglese
#                   Usato per selezionare il template pulsante rifornimento
# ==============================================================================

# --- BlueStacks ---
ISTANZE = [
    {"nome": "FAU_00", "interno": "Pie64_13", "porta": "5685", "truppe": 0,     "max_squadre": 5, "layout": 1, "livello": 6, "abilitata": False},
    {"nome": "FAU_01", "interno": "Pie64_6",  "porta": "5615", "truppe": 12000, "max_squadre": 4, "layout": 1, "livello": 6, "abilitata": False},
    {"nome": "FAU_02", "interno": "Pie64",    "porta": "5555", "truppe": 12000, "max_squadre": 4, "layout": 1, "livello": 6, "profilo": "raccolta_only", "abilitata": False},
    {"nome": "FAU_03", "interno": "Pie64_7",  "porta": "5625", "truppe": 12000, "max_squadre": 4, "layout": 1, "livello": 6, "abilitata": False},
    {"nome": "FAU_04", "interno": "Pie64_8",  "porta": "5635", "truppe": 12000, "max_squadre": 4, "layout": 1, "livello": 6, "abilitata": False},
    {"nome": "FAU_05", "interno": "Pie64_9",  "porta": "5645", "truppe": 12000, "max_squadre": 4, "layout": 1, "livello": 6, "abilitata": False},
    {"nome": "FAU_06", "interno": "Pie64_11", "porta": "5665", "truppe": 12000, "max_squadre": 4, "layout": 1, "livello": 6, "abilitata": False},
    {"nome": "FAU_07", "interno": "Pie64_10", "porta": "5655", "truppe": 12000, "max_squadre": 4, "layout": 1, "livello": 6, "abilitata": False},
    {"nome": "FAU_08", "interno": "Pie64_12", "porta": "5675", "truppe": 12000, "max_squadre": 4, "layout": 1, "livello": 6, "abilitata": True},
    {"nome": "FAU_09", "interno": "Pie64_14", "porta": "5695", "truppe": 12000, "max_squadre": 4, "layout": 2, "livello": 6, "abilitata": True},  # layout 2: 4 icone, no Bestia
]

# --- MuMuPlayer ---
ISTANZE_MUMU = [
    {"nome": "FAU_00", "indice": "0", "porta": 16384, "truppe": 0,     "max_squadre": 5, "layout": 1, "lingua": "en", "livello": 7, "profilo": "full", "abilitata": True},
    {"nome": "FAU_01", "indice": "1", "porta": 16448, "truppe": 50000, "max_squadre": 4, "layout": 1, "lingua": "en", "livello": 6, "profilo": "full", "abilitata": True},
    {"nome": "FAU_02", "indice": "2", "porta": 16480, "truppe": 50000, "max_squadre": 4, "layout": 1, "lingua": "en", "livello": 6, "profilo": "full", "abilitata": True},
    {"nome": "FAU_03", "indice": "3", "porta": 16512, "truppe": 50000, "max_squadre": 4, "layout": 1, "lingua": "en", "livello": 6, "profilo": "full", "abilitata": True},
    {"nome": "FAU_04", "indice": "4", "porta": 16544, "truppe": 50000, "max_squadre": 4, "layout": 1, "lingua": "en", "livello": 6, "profilo": "full", "abilitata": True},
    {"nome": "FAU_05", "indice": "5", "porta": 16576, "truppe": 50000, "max_squadre": 4, "layout": 1, "lingua": "en", "livello": 6, "profilo": "full", "abilitata": True},
    {"nome": "FAU_06", "indice": "6", "porta": 16608, "truppe": 50000, "max_squadre": 4, "layout": 1, "lingua": "en", "livello": 6, "profilo": "full", "abilitata": True},
    {"nome": "FAU_07", "indice": "7", "porta": 16640, "truppe": 50000, "max_squadre": 4, "layout": 1, "lingua": "en", "livello": 6, "profilo": "full", "abilitata": True},
    {"nome": "FAU_08", "indice": "8", "porta": 16672, "truppe": 50000, "max_squadre": 4, "layout": 1, "lingua": "en", "livello": 6, "profilo": "full", "abilitata": True},
    {"nome": "FAU_09", "indice": "9", "porta": 16704, "truppe": 50000, "max_squadre": 4, "layout": 2, "lingua": "en", "livello": 6, "profilo": "full", "abilitata": True},
    {"nome": "FauMorfeus", "indice": "10", "porta": 16736, "truppe": 0,"max_squadre": 5, "layout": 1, "lingua": "en", "livello": 7, "profilo": "raccolta_only", "abilitata": True},
    {"nome": "FAU_10", "indice": "11", "porta": 16768, "truppe": 10000,"max_squadre": 4, "layout": 2, "lingua": "en", "livello": 6, "profilo": "full", "abilitata": True},

]

# ==============================================================================
# 4. PARAMETRI CICLO
# ==============================================================================

ISTANZE_BLOCCO         = 1      # istanze attive contemporaneamente (semaforo)
WAIT_MINUTI            = 1      # minuti di attesa tra un ciclo e l'altro

# --- Raccolta risorse ---
TRUPPE_RACCOLTA        = 40000  # truppe per squadra globale (0 = MAX)
MAX_TENTATIVI_RACCOLTA = 2      # tentativi massimi per singola squadra

# ==============================================================================
# 5. COORDINATE UI  (risoluzione 960x540)
# ==============================================================================

# --- Layout barra inferiore ---
COORD_ALLEANZA_LAYOUT = {
    1: (760, 505),   # standard — 5 icone (Campagna/Zaino/Alleanza/Bestia/Eroe)
    2: (800, 505),   # compatto — 4 icone (Campagna/Zaino/Alleanza/Eroe) — no Bestia
}

def get_coord_alleanza(ist: dict) -> tuple:
    """Ritorna coordinate pulsante Alleanza per l'istanza data."""
    layout = ist.get("layout", 1)
    return COORD_ALLEANZA_LAYOUT.get(layout, COORD_ALLEANZA_LAYOUT[1])

# --- Layout Campaign (barra inferiore, primo pulsante) ---
ARENA_TAP_CAMPAIGN_LAYOUT = {
    1: (584, 486),   # standard — 5 icone (Campagna/Zaino/Alleanza/Bestia/Eroe)
    2: (658, 489),   # compatto — 4 icone (Campagna/Zaino/Alleanza/Eroe) — no Bestia
}

def get_coord_campaign(ist: dict) -> tuple:
    """Ritorna coordinate pulsante Campaign per l'istanza data."""
    layout = ist.get("layout", 1)
    return ARENA_TAP_CAMPAIGN_LAYOUT.get(layout, ARENA_TAP_CAMPAIGN_LAYOUT[1])

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
OCR_MARCIA_ETA_MARGINE_S  = 5     # secondi extra dopo ETA reale
OCR_MARCIA_ETA_MIN_S      = 8     # attesa minima anche se ETA molto bassa

# --- Radar Show ---
TAP_RADAR_ICONA    = (78,  315)  # icona Radar Station in home (badge rosso)
RADAR_MAPPA_ZONA   = (0, 100, 860, 460)  # area mappa Radar Station (960x540)
RADAR_BADGE_R_MIN  = 150   # soglia R minima badge rosso
RADAR_BADGE_G_MAX  = 85    # soglia G massima badge rosso
RADAR_BADGE_B_MAX  = 85    # soglia B massima badge rosso
RADAR_COMP_MIN     = 0.55  # compattezza minima componente (cerchio vs triangolo)
RADAR_ASPECT_MIN   = 0.50  # aspect ratio minima (w/h vicino a 1 = cerchio)
RADAR_W_MIN        = 8     # larghezza minima pallino (px)
RADAR_W_MAX        = 22    # larghezza massima pallino (px)
RADAR_H_MIN        = 8     # altezza minima pallino (px)
RADAR_H_MAX        = 22    # altezza massima pallino (px)
RADAR_PX_MIN       = 15    # pixel rossi minimi per componente valida
RADAR_TIMEOUT_S    = 30    # timeout loop raccolta pallini (secondi)
RADAR_TAP_DELAY_S  = 1.2   # attesa dopo ogni tap pallino (secondi)
RADAR_SCAN_DELAY_S = 1.0   # attesa tra scan successivi (secondi)

# --- Arena of Glory (960x540) ---
ARENA_TAP_CAMPAIGN        = (584, 486)   # Home -> bottom bar "Campaign"
ARENA_TAP_ARENA_OF_DOOM   = (321, 297)   # Campaign -> card "Arena of Doom"
ARENA_TAP_ULTIMA_SFIDA    = (745, 482)   # Arena of Glory -> pulsante "Challenge" ultima riga
ARENA_TAP_START_CHALLENGE = (730, 451)   # Schermata sfida -> "START CHALLENGE"
ARENA_TAP_RISULTATO       = (480, 468)   # Schermata risultato -> "Tap to Continue"
ARENA_TAP_CONGRATULATIONS = (480, 435)   # Popup stagionale "Congratulations" -> "Continue"
ARENA_TAP_ESAURITE_CANCEL = (394, 331)   # Popup "Purchase more attempts?" -> "Cancel"
ARENA_TAP_CARRELLO        = (905,  68)   # Lista Arena -> icona carrello (apre Arena Store)
ARENA_TAP_PRIMO_ACQUISTO  = (235, 283)   # Arena Store -> tap primo acquisto pack 360
ARENA_TAP_MAX_ACQUISTO    = (451, 286)   # Arena Store -> tap pulsante max quantità pack 360 (≤50)
ARENA_MAX_SFIDE           = 5            # sfide giornaliere massime
ARENA_SCREEN_TMP          = "screen_arena.png"  # filename screenshot temporaneo arena (relativo a BOT_DIR)
# Pixel check popup "Congratulations" — pulsante giallo "Continue"
ARENA_CONGRATS_CHECK_XY   = (480, 435)
ARENA_CONGRATS_BGR_LOW    = (10,  130, 170)   # (B, G, R) minimo
ARENA_CONGRATS_BGR_HIGH   = (100, 210, 255)   # (B, G, R) massimo
# Pixel check popup "Purchase more attempts?" — pulsante "Cancel" grigio chiaro
ARENA_ESAURITE_CHECK_XY   = (390, 330)
ARENA_ESAURITE_SOGLIA     = 180   # tutti i canali BGR > soglia = popup presente

# --- Arena Store: pack da 15 monete (Random Resource Pack III) ---
# Attivo solo quando il pack da 360 è esaurito (stock 0).
# Loop infinito fino a monete esaurite (pulsante diventa grigio).
ARENA_TAP_PACK15          = (788, 408)   # Arena Store -> pulsante arancione "15" monete
ARENA_TAP_PACK15_MAX      = (654, 408)   # Arena Store -> pulsante quantità "x34" (max acquistabile)
ARENA_PIN_PACK15_OPEN     = "pin_15_open.png"        # template pulsante 15 attivo (arancione)
ARENA_PIN_PACK15_CLOSE    = "pin_15_close.png"  # template pulsante 15 disabilitato (grigio)
ARENA_PIN_PACK15_SOGLIA   = 0.75                # soglia template matching pack 15

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


# --- Secondo sensore stato (toggle basso-sinistra: testo Region/Shelter) ---
STATO_TOGGLE_OCR_ABILITATO = True
STATO_TOGGLE_LABEL_ZONA = (0, 396, 228, 540)
STATO_TOGGLE_KEY_HOME = ["REGION", "REGIONE"]
STATO_TOGGLE_KEY_MAPPA = ["SHELTER", "RIFUGIO"]
STATO_TOGGLE_OCR_PSM = 7

# --- Sistema dual-mode riconoscimento toggle (template matching + OCR fallback) ---
# TEMPLATE=True  + OCR=True  → template prima, OCR come fallback (consigliato)
# TEMPLATE=True  + OCR=False → solo template (dopo validazione)
# TEMPLATE=False + OCR=True  → solo OCR (comportamento originale pre-patch)
STATO_TOGGLE_TEMPLATE_ABILITATO = True
STATO_TOGGLE_TEMPLATE_SOGLIA    = 0.80   # validata: match=0.993 cross=0.30
STATO_TOGGLE_ROI                = (0, 450, 120, 540)  # x1,y1,x2,y2 in 960x540

# ==============================================================================
# 9. VERIFICA UI  (template matching post-tap per conferma visiva)
# ==============================================================================

# Flag globale — False = ogni check ritorna True immediatamente (nessun overhead)
VERIFICA_UI_ABILITATA = True

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
SCHEDULE_ORE_MESSAGGI  = 4    # ore minime tra esecuzioni raccolta messaggi
SCHEDULE_ORE_ALLEANZA  = 4    # ore minime tra esecuzioni raccolta alleanza
SCHEDULE_ORE_VIP       = 24   # ore minime tra esecuzioni ricompense VIP
SCHEDULE_ORE_RADAR     = 12   # ore minime tra esecuzioni Radar Show
SCHEDULE_ORE_ZAINO     = 168  # ore minime tra esecuzioni zaino (7 giorni = lunedì)
SCHEDULE_ORE_STORE     = 4    # ore minime tra esecuzioni acquisto Store (chiave "store")

# --- Arena of Glory ---
SCHEDULE_ORE_ARENA         = 24   # ore minime tra esecuzioni arena (1 volta al giorno)
SCHEDULE_ORE_ARENA_MERCATO = 12   # ore minime tra esecuzioni mercato arena (chiave "arena_mercato")

# --- Feature flags task periodici (sovrascrivibili da runtime.json → globali) ---
ALLEANZA_ABILITATA     = False   # False = salta raccolta doni alleanza
MESSAGGI_ABILITATI     = False   # False = salta raccolta messaggi sistema/alleanza
DAILY_VIP_ABILITATO    = False   # False = salta ricompense VIP giornaliere
DAILY_RADAR_ABILITATO  = True   # False = salta Radar Show
RADAR_CENSUS_ABILITATO = True  # True = salva crop icone radar per training classifier (attivare da runtime.json)
RADAR_TOOL_THRESHOLD   = 0.65   # soglia template matching radar_tool detector
ZAINO_ABILITATO        = False   # False = salta scarico zaino settimanale
ARENA_OF_GLORY_ABILITATO = False  # False = salta Arena of Glory giornaliera
STORE_ABILITATO          = False  # False = salta acquisto Mysterious Merchant Store

# --- Store / Mysterious Merchant ---
#
# Soglie calibrate per pipeline exec-out (adb.screenshot_bytes):
#   - STORE / STORE_ATTIVO / MERCANTE abbassate a 0.75:
#     il template pin_store.png è stato catturato con il vecchio metodo
#     adb pull → il match via exec-out produce uno scarto sistematico di
#     ~0.03-0.05 punti (FAU_06: best score=0.797 con soglia 0.80 → NON TROVATO).
#     0.75 copre questa varianza mantenendo discriminazione sufficiente.
#   - ACQUISTO resta a 0.80: falsi positivi costerebbero acquisti sbagliati.
#   - BANNER / CARRELLO / MERCHANT / FREE_REFRESH / NO_REFRESH invariati.
#
STORE_SOGLIA_STORE        = 0.75   # pin_store.png — edificio store nella mappa       [era 0.80]
STORE_SOGLIA_BANNER       = 0.85   # pin_banner_aperto/chiuso.png
STORE_SOGLIA_STORE_ATTIVO = 0.75   # pin_store_attivo.png — label Store dopo tap       [era 0.80]
STORE_SOGLIA_CARRELLO     = 0.65   # pin_carrello.png
STORE_SOGLIA_MERCHANT     = 0.75   # pin_merchant.png — merchant aperto
STORE_SOGLIA_MERCANTE     = 0.75   # pin_mercante.png — icona mercante sull'edificio   [era 0.80]
STORE_SOGLIA_ACQUISTO     = 0.80   # pin_legno/pomodoro/acciaio — NON abbassare
STORE_SOGLIA_FREE_REFRESH = 0.80   # pin_free_refresh.png
STORE_SOGLIA_NO_REFRESH   = 0.80   # pin_no_refresh.png (a pagamento — non tappare)
STORE_PASSO_SCAN          = 300    # pixel per swipe nella griglia di ricerca
STORE_MAX_PAGINE          = 3      # pagine max da scorrere nel merchant

# --- Zaino: risorse abilitate ---
ZAINO_USA_POMODORO     = True    # True = scarica pacchetti pomodoro dallo zaino
ZAINO_USA_LEGNO        = True    # True = scarica pacchetti legno dallo zaino
ZAINO_USA_ACCIAIO      = False   # True = scarica pacchetti acciaio dallo zaino
ZAINO_USA_PETROLIO     = True    # True = scarica pacchetti petrolio dallo zaino

# --- Zaino: soglie target (valore assoluto deposito da raggiungere) ---
ZAINO_SOGLIA_POMODORO_M = 10.0   # default = RIFORNIMENTO_SOGLIA_CAMPO_M * 2
ZAINO_SOGLIA_LEGNO_M    = 10.0   # default = RIFORNIMENTO_SOGLIA_LEGNO_M * 2
ZAINO_SOGLIA_ACCIAIO_M  =  7.0   # default = RIFORNIMENTO_SOGLIA_ACCIAIO_M * 2
ZAINO_SOGLIA_PETROLIO_M =  5.0   # default = RIFORNIMENTO_SOGLIA_PETROLIO_M * 2

# --- Zaino: coordinate UI (960x540) ---
ZAINO_TAP_APRI          = (430, 18)    # icona 🍅 barra alta → apre zaino su Food
ZAINO_TAP_CHIUDI        = (783, 68)    # pulsante X chiude zaino
ZAINO_SIDEBAR_POMODORO  = (80, 130)    # tab Food nella sidebar sinistra
ZAINO_SIDEBAR_LEGNO     = (80, 200)    # tab Wood
ZAINO_SIDEBAR_ACCIAIO   = (80, 270)    # tab Steel
ZAINO_SIDEBAR_PETROLIO  = (80, 340)    # tab Oil
ZAINO_TAP_USE_X         = 722          # coordinata X pulsante USE
ZAINO_TAP_MAX_X         = 601          # coordinata X pulsante Max
ZAINO_PRIMA_RIGA_Y      = 140          # Y centro prima riga lista
ZAINO_ALTEZZA_RIGA      = 80           # altezza riga in pixel
ZAINO_MAX_RIGHE         = 5            # righe visibili senza scroll

# --- Rifornimento alleanza ---
RIFORNIMENTO_MAX_SPEDIZIONI_CICLO = 5  # max spedizioni rifornimento per istanza in un singolo ciclo
RIFORNIMENTO_ABILITATO         = False
RIFORNIMENTO_MAPPA_ABILITATO   = False  # True = usa navigazione via coordinate mappa invece di lista Membri
RIFUGIO_X                      = 687    # coordinata X mappa del rifugio destinatario
RIFUGIO_Y                      = 532    # coordinata Y mappa del rifugio destinatario
DOOMS_ACCOUNT                  = "FauMorfeus"
DOOMS_AVATAR                   = "templates/avatar.png"
RIFORNIMENTO_BTN_TEMPLATE      = "templates/btn_risorse_approv.png"       # IT
RIFORNIMENTO_BTN_TEMPLATE_EN   = "templates/btn_supply_resources.png"     # EN
VIP_CLAIM_FREE_TEMPLATE        = "templates/btn_claim_free_it.png"        # IT ⚠️ MANCANTE
VIP_CLAIM_FREE_TEMPLATE_EN     = "templates/btn_claim_free_en.png"        # EN
RIFORNIMENTO_SOGLIA_CAMPO_M    = 5.0
RIFORNIMENTO_SOGLIA_LEGNO_M    = 5.0
RIFORNIMENTO_SOGLIA_PETROLIO_M = 2.5
RIFORNIMENTO_SOGLIA_ACCIAIO_M  = 3.5

# --- Flag abilitazione per-risorsa (True = invia, False = salta sempre) ---
# Permette di escludere una risorsa dall'invio indipendentemente dalla soglia.
RIFORNIMENTO_CAMPO_ABILITATO    = True
RIFORNIMENTO_LEGNO_ABILITATO    = True
RIFORNIMENTO_PETROLIO_ABILITATO = True
RIFORNIMENTO_ACCIAIO_ABILITATO  = False
RIFORNIMENTO_QTA_POMODORO      = 999_000_000
RIFORNIMENTO_QTA_LEGNO         = 999_000_000
RIFORNIMENTO_QTA_ACCIAIO       = 999_000_000
RIFORNIMENTO_QTA_PETROLIO      = 999_000_000

def get_lingua(ist: dict) -> str:
    """Ritorna la lingua dell'istanza ('it' o 'en'). Default 'it'."""
    return ist.get("lingua", "it")

def get_btn_rifornimento_template(ist: dict) -> str:
    """Ritorna il path del template pulsante rifornimento per la lingua dell'istanza."""
    if get_lingua(ist) == "en":
        return RIFORNIMENTO_BTN_TEMPLATE_EN
    return RIFORNIMENTO_BTN_TEMPLATE

def get_btn_claim_free_template(ist: dict) -> str:
    """Ritorna il path del template pulsante CLAIM free VIP per la lingua dell'istanza."""
    if get_lingua(ist) == "en":
        return VIP_CLAIM_FREE_TEMPLATE_EN
    return VIP_CLAIM_FREE_TEMPLATE
