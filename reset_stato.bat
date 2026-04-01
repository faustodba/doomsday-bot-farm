@echo off
chcp 437 >nul
cd /d "%~dp0"

echo.
echo ============================================================
echo   DOOMSDAY BOT V5 - Reset stato completo
echo ============================================================
echo.
echo   Cartella: %CD%
echo.
echo   Verranno eliminati:
echo     - status.json
echo     - istanza_stato_*.json
echo     - timing.json
echo     - rifornimento_stato_*.json (legacy)
echo.
echo   Verra riscritto:
echo     - runtime.json
echo.
echo   NON vengono toccati: bot.log, config.py, *.py, templates\
echo.

set /p CONFERMA="   Confermi? [s/N]: "
if /i not "%CONFERMA%"=="s" (
    echo.
    echo   Annullato.
    pause
    exit /b 0
)

echo.
echo   Pulizia in corso...
echo.

if exist "status.json" (
    del /f /q "status.json"
    echo   [OK] Eliminato: status.json
) else (
    echo   [--] Non trovato: status.json
)

set COUNT=0
for %%f in (istanza_stato_*.json) do (
    del /f /q "%%f"
    echo   [OK] Eliminato: %%f
    set /a COUNT+=1
)
if %COUNT%==0 echo   [--] Nessun istanza_stato_*.json trovato

if exist "timing.json" (
    del /f /q "timing.json"
    echo   [OK] Eliminato: timing.json
) else (
    echo   [--] Non trovato: timing.json
)

set COUNT2=0
for %%f in (rifornimento_stato_*.json) do (
    del /f /q "%%f"
    echo   [OK] Eliminato legacy: %%f
    set /a COUNT2+=1
)
if %COUNT2%==0 echo   [--] Nessun rifornimento_stato_*.json trovato

echo.
echo   Scrittura runtime.json...

> runtime.json (
echo {
echo   "_nota": "Riletto ogni ciclo. Istanze sempre da config.py.",
echo   "globali": {
echo     "ISTANZE_BLOCCO": 1,
echo     "WAIT_MINUTI": 1,
echo     "ALLEANZA_ABILITATA": true,
echo     "MESSAGGI_ABILITATI": true,
echo     "DAILY_VIP_ABILITATO": true,
echo     "DAILY_RADAR_ABILITATO": true,
echo     "RADAR_CENSUS_ABILITATO": false,
echo     "ZAINO_ABILITATO": false,
echo     "ARENA_OF_GLORY_ABILITATO": true,
echo     "RIFORNIMENTO_ABILITATO": false,
echo     "RIFORNIMENTO_MAPPA_ABILITATO": false,
echo     "RIFORNIMENTO_MAX_SPEDIZIONI_CICLO": 5,
echo     "RIFORNIMENTO_SOGLIA_CAMPO_M": 5.0,
echo     "RIFORNIMENTO_SOGLIA_LEGNO_M": 5.0,
echo     "RIFORNIMENTO_SOGLIA_PETROLIO_M": 2.5,
echo     "RIFORNIMENTO_SOGLIA_ACCIAIO_M": 3.5,
echo     "RIFORNIMENTO_CAMPO_ABILITATO": true,
echo     "RIFORNIMENTO_LEGNO_ABILITATO": true,
echo     "RIFORNIMENTO_PETROLIO_ABILITATO": true,
echo     "RIFORNIMENTO_ACCIAIO_ABILITATO": false,
echo     "ALLOCATION_RATIO": {
echo       "campo": 0.375,
echo       "segheria": 0.375,
echo       "petrolio": 0.1875,
echo       "acciaio": 0.0625
echo     }
echo   },
echo   "overrides": {
echo     "bs": {},
echo     "mumu": {}
echo   }
echo }
)

echo   [OK] Scritto: runtime.json
echo.
echo ============================================================
echo   Reset completato. Avvia il bot e scegli [1] runtime.json
echo ============================================================
echo.
pause
