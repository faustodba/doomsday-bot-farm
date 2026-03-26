@echo off
chcp 65001 >nul
title Doomsday Bot Farm — Avvio Pulito

set BOT_DIR=E:\Bot-farm

echo ===============================================================
echo   DOOMSDAY BOT FARM — Avvio Pulito
echo ===============================================================
echo.

:: --- Pulizia bot.log ---
echo [1/3] Pulizia bot.log...
if exist "%BOT_DIR%\bot.log" (
    del /f /q "%BOT_DIR%\bot.log"
    echo       bot.log eliminato.
) else (
    echo       bot.log non trovato — skip.
)

:: --- Pulizia cartella debug\ ---
echo [2/3] Pulizia cartella debug\...
if exist "%BOT_DIR%\debug\" (
    rmdir /s /q "%BOT_DIR%\debug"
    mkdir "%BOT_DIR%\debug"
    echo       debug\ svuotata e ricreata.
) else (
    mkdir "%BOT_DIR%\debug"
    echo       debug\ non trovata — creata.
)

:: --- Pulizia __pycache__ (ricorsiva) ---
echo [3/3] Pulizia __pycache__...
for /d /r "%BOT_DIR%" %%d in (__pycache__) do (
    if exist "%%d" (
        rmdir /s /q "%%d"
        echo       Eliminata: %%d
    )
)
echo       __pycache__ rimossi.

echo.
echo ---------------------------------------------------------------
echo   Pulizia completata. Avvio bot in 3 secondi...
echo ---------------------------------------------------------------
timeout /t 3 /nobreak >nul

:: --- Avvio bot ---
cd /d "%BOT_DIR%"
python main.py

:: --- Pausa finale se il bot termina/crasha ---
echo.
echo ===============================================================
echo   Bot terminato. Premi un tasto per chiudere.
echo ===============================================================
pause >nul
