@echo off
:: ==============================================================================
::  Doomsday Bot V5.15 — Commit Git sessione 15/03/2026
::  Eseguire dalla cartella C:\Bot-raccolta\V5
:: ==============================================================================

set BOT_DIR=C:\Bot-raccolta\V5
cd /d "%BOT_DIR%"

echo.
echo ============================================================
echo   Doomsday Bot V5.15 — Commit Git
echo ============================================================
echo.

:: Verifica che git sia disponibile
git --version >nul 2>&1
if errorlevel 1 (
    echo [ERRORE] Git non trovato nel PATH
    pause
    exit /b 1
)

echo [INFO] Aggiunta file modificati...

:: File nuovi
git add allocation.py
git add runtime.py
git add LICENSE
git add README.md

:: File modificati
git add raccolta.py
git add rifornimento.py
git add ocr.py
git add config.py
git add main.py
git add dashboard_server.py
git add dashboard.html

:: File spostati in tests/
git add tests\test_alleanza.py
git add tests\test_coordinate.py
git add tests\test_coordinate2.py
git add tests\test_messaggi.py
git add tests\test_mumu.py
git add tests\test_ocr.py
git add tests\test_ocr_nodo.py
git add tests\test_rifornimento.py
git add tests\test_rifornimento2.py
git add tests\test_rifornimento_steps.py
git add tests\test_tap.py
git add tests\test_toggle.py

:: Rimozione file obsoleti (se non ancora rimossi)
git rm --cached main_patch_blacklist.py 2>nul
git rm --cached raccolta_v5132.py       2>nul
git rm --cached ocr_v5132.py            2>nul

echo.
echo [INFO] Stato repository:
git status --short

echo.
set MSG=V5.15: allocation.py (gap decisionale 4 risorse), raccolta.py (acciaieria/raffineria + check territorio alleanza), rifornimento.py (soglie per risorsa + delta OCR), runtime.py (config live senza riavvio), dashboard pannello Runtime, LICENSE MIT, README aggiornato

echo [INFO] Messaggio commit:
echo %MSG%
echo.

git commit -m "%MSG%"

if errorlevel 1 (
    echo.
    echo [WARN] Commit fallito o nessuna modifica da committare
) else (
    echo.
    echo [OK] Commit completato con successo
)

echo.
echo [INFO] Push su origin/main...
git push origin main

if errorlevel 1 (
    echo [WARN] Push fallito — verifica connessione o credenziali
) else (
    echo [OK] Push completato
)

echo.
echo ============================================================
echo   Versione V5.15 committata
echo ============================================================
echo.
pause
