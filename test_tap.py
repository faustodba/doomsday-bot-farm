pythonimport adb
import time

porta = "5555"
adb.start_server()

for x in [540, 560, 580, 600, 620]:
    print(f"Tap su ({x}, 55)...")
    adb.tap(porta, (x, 55), delay_ms=500)
    time.sleep(2)
    input(f"Premi INVIO (x={x}), tab cambiato su Attività?...")