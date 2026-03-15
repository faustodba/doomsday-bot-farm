@echo off
:: ==============================================================================
::  Doomsday Bot V5 — Sposta file di test in sottocartella tests\
::  Eseguire dalla cartella C:\Bot-raccolta\V5
:: ==============================================================================

set BOT_DIR=C:\Bot-raccolta\V5
set TEST_DIR=%BOT_DIR%\tests

echo.
echo ============================================================
echo   Doomsday Bot V5 - Spostamento file di test
echo   Destinazione: %TEST_DIR%
echo ============================================================
echo.

:: Crea cartella tests\ se non esiste
if not exist "%TEST_DIR%" (
    mkdir "%TEST_DIR%"
    echo [OK] Cartella tests\ creata
) else (
    echo [OK] Cartella tests\ gia' esistente
)

echo.
echo Spostamento file in corso...
echo.

move "%BOT_DIR%\test_alleanza.py"           "%TEST_DIR%\" && echo [OK] test_alleanza.py           || echo [ERR] test_alleanza.py
move "%BOT_DIR%\test_coordinate.py"         "%TEST_DIR%\" && echo [OK] test_coordinate.py         || echo [ERR] test_coordinate.py
move "%BOT_DIR%\test_coordinate2.py"        "%TEST_DIR%\" && echo [OK] test_coordinate2.py        || echo [ERR] test_coordinate2.py
move "%BOT_DIR%\test_messaggi.py"           "%TEST_DIR%\" && echo [OK] test_messaggi.py           || echo [ERR] test_messaggi.py
move "%BOT_DIR%\test_mumu.py"               "%TEST_DIR%\" && echo [OK] test_mumu.py               || echo [ERR] test_mumu.py
move "%BOT_DIR%\test_ocr.py"               "%TEST_DIR%\" && echo [OK] test_ocr.py                || echo [ERR] test_ocr.py
move "%BOT_DIR%\test_ocr_nodo.py"           "%TEST_DIR%\" && echo [OK] test_ocr_nodo.py           || echo [ERR] test_ocr_nodo.py
move "%BOT_DIR%\test_rifornimento.py"       "%TEST_DIR%\" && echo [OK] test_rifornimento.py       || echo [ERR] test_rifornimento.py
move "%BOT_DIR%\test_rifornimento2.py"      "%TEST_DIR%\" && echo [OK] test_rifornimento2.py      || echo [ERR] test_rifornimento2.py
move "%BOT_DIR%\test_rifornimento_steps.py" "%TEST_DIR%\" && echo [OK] test_rifornimento_steps.py || echo [ERR] test_rifornimento_steps.py
move "%BOT_DIR%\test_tap.py"               "%TEST_DIR%\" && echo [OK] test_tap.py                || echo [ERR] test_tap.py
move "%BOT_DIR%\test_toggle.py"            "%TEST_DIR%\" && echo [OK] test_toggle.py             || echo [ERR] test_toggle.py

echo.
echo ============================================================
echo   Completato. Verifica con: dir "%TEST_DIR%"
echo ============================================================
echo.
pause
