import config
import adb
import rifornimento

# Parametri test
PORTA = "5555"   # porta FAU_02
NOME  = "FAU_02"

def log(nome, msg):
    print(f"[{nome}] {msg}")

# Avvia server ADB
adb.start_server()
adb.connetti(PORTA)

# Esegui rifornimento
# Passiamo valori fittizi: 57.9M pomodoro, 62.7M legno (dal tuo screenshot)
risultato = rifornimento.esegui_rifornimento(
    porta      = PORTA,
    nome       = NOME,
    pomodoro_m = 57.9,
    legno_m    = 62.7,
    logger     = log
)

print(f"\nSpedizioni effettuate: {risultato}")