import adb
import ocr

porta = "5555"
adb.start_server()
screen = adb.screenshot(porta)

with open(screen, "rb") as f:
    screen_bytes = f.read()

risultato = ocr.leggi_coordinate_nodo(screen_bytes)
print(f"Coordinate lette: {risultato}")