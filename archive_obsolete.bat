@echo off
:: ==============================================================================
::  Doomsday Bot V5 — Archivia file obsoleti e rimuovi patch superate
::  Eseguire dalla cartella C:\Bot-raccolta\V5
:: ==============================================================================

set BOT_DIR=C:\Bot-raccolta\V5
set ARCH_DIR=%BOT_DIR%\archive

echo.
echo ============================================================
echo   Doomsday Bot V5 - Archiviazione file obsoleti
echo   Destinazione: %ARCH_DIR%
echo ============================================================
echo.

:: Crea cartella archive\ se non esiste
if not exist "%ARCH_DIR%" (
    mkdir "%ARCH_DIR%"
    echo [OK] Cartella archive\ creata
) else (
    echo [OK] Cartella archive\ gia' esistente
)

echo.

:: --- Sposta versioni archiviate in archive\ ---
echo Spostamento versioni archiviate...
move "%BOT_DIR%\raccolta_v5132.py" "%ARCH_DIR%\" && echo [OK] raccolta_v5132.py spostato  || echo [SKIP] raccolta_v5132.py non trovato
move "%BOT_DIR%\ocr_v5132.py"      "%ARCH_DIR%\" && echo [OK] ocr_v5132.py spostato        || echo [SKIP] ocr_v5132.py non trovato

echo.

:: --- Elimina main_patch_blacklist.py (gia' integrato in main.py) ---
echo Rimozione patch superate...
if exist "%BOT_DIR%\main_patch_blacklist.py" (
    del /Q "%BOT_DIR%\main_patch_blacklist.py"
    echo [OK] main_patch_blacklist.py eliminato
) else (
    echo [SKIP] main_patch_blacklist.py non trovato
)

echo.
echo ============================================================
echo   Completato.
echo   Verifica archive\: dir "%ARCH_DIR%"
echo ============================================================
echo.
pause
