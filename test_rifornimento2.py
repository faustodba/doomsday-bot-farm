import adb, config, time, shutil
from rifornimento import COORD_ALLEANZA_BTN, COORD_MEMBRI, COORD_TAB_R, COORD_SWIPE_SU_START, COORD_SWIPE_SU_END

porta = '5615'

print("Navigazione Alleanza → Membri → R3...")
adb.tap(porta, COORD_ALLEANZA_BTN, delay_ms=1500)
adb.tap(porta, COORD_MEMBRI, delay_ms=1500)
adb.tap(porta, COORD_TAB_R["R3"], delay_ms=1500)

for i in range(5):
    screen = adb.screenshot(porta)
    dest = f"C:\\Bot-raccolta\\V5\\swipe_{i}.png"
    shutil.copy(screen, dest)
    print(f"Screenshot {i} salvato: {dest}")
    adb.scroll(porta, COORD_SWIPE_SU_START[0], COORD_SWIPE_SU_START[1], COORD_SWIPE_SU_END[1], durata_ms=600)
    time.sleep(1.5)

print("Fine - allega i file swipe_0.png ... swipe_4.png")