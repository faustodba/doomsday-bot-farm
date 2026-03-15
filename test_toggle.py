python -c "
import adb, config
config.ADB_EXE = config.BS_ADB
adb.start_server()
adb.connetti('5675')
screen = adb.screenshot('5675')
import shutil
shutil.copy(screen, r'E:\Bot-raccolta\V5\debug_manual\membri_toggle.png')
print('Salvato:', screen)
"