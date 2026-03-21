# 🤖 Doomsday Bot V5
Bot Python per l'automazione della raccolta risorse nel gioco **Doomsday: Last Survivors** su emulatori Android.

---
## ⚠️ Disclaimer
Questo progetto nasce come **studio personale** sulle tecnologie di automazione (Python, ADB, OCR con Tesseract, computer vision con OpenCV) applicato a un contesto di gioco.
- **Nessun fine di lucro**
- **Solo uso personale**
- **Fair use** su istanze emulate di proprietà dell’utente
- **Nessuna garanzia**

---
## ✅ Versione v5.18 (selezione livello nodo + produzione oraria dashboard)

### Selezione livello nodo (`raccolta.py`)
- **Livello nodo configurabile per istanza** (5/6/7) con default 6, modificabile dalla dashboard senza riavvio
- Reset garantito: 6 tap su `—` portano sempre a Lv.1 indipendentemente dal livello dell'ultima ricerca
- Coordinate assolute misurate su screenshot reali 960x540 per tutti i tipi — necessario perché il popup del petrolio è clamped al bordo destro dello schermo
- OCR livello dal titolo popup nodo per scartare nodi sotto-livello (pattern IT/EN)
- OCR risorse inizio ciclo: retry con backoff crescente 2s → 3s → 4s (era singolo retry fisso)

### Livello per istanza (`config.py`)
- Campo `"livello": 6` aggiunto a tutte le istanze BlueStacks e MuMuPlayer
- Sovrascrivibile da `runtime.json` via dashboard senza modificare `config.py`

### Dashboard produzione oraria (`dashboard.html`)
- Nuovo pannello **Produzione oraria** in sidebar: M/h ciclo corrente + media storica ultimi 10 cicli
- Produzione oraria visibile nella card di ogni istanza (tutte e 4 le risorse + totale M/h)
- Nuova colonna M/h nello storico cicli
- Colonna **Lv.** nella tabella runtime istanze con select 5/6/7

### Backend (`dashboard_server.py`, `runtime.py`)
- `config_istanze.json` espone il campo `livello` per BS e MuMu
- `istanze_attive()` applica l'override `livello` da `runtime.json`

---
## ✅ Versione v5.17 (fix raccolta + robustezza)

### Bug fix raccolta (`raccolta.py`)
- **BUG1** — Attesa nodo blacklist ora avviene in mappa pulita (BACK prima del `sleep`) invece che con UI aperta, eliminando tap fuori contesto al CERCA successivo
- **BUG3** — Uscita immediata dal loop quando tutti i tipi pianificati sono bloccati; il bot prova automaticamente i tipi alternativi (`campo/segheria/petrolio/acciaio`) prima di arrendersi
- **BUG4** — Recovery post-marcia fallita usa `back_rapidi_e_stato(n=4)` invece di 1 solo BACK, garantendo UI pulita tra un tentativo e il successivo
- **Contatore reale** — A fine ciclo viene riletto il contatore reale dal gioco; se ci sono slot liberi (OCR iniziale impreciso) il bot riprende la raccolta con sequenza fresca
- **OCR risorse** — Retry se anche una sola risorsa principale è `-1` (prima solo se pomodoro+legno entrambi assenti)
- **Stabilizzazione contatore** — `sleep(2s)` dopo `vai_in_mappa` per dare tempo al widget squadre di renderizzarsi

### Fix navigazione (`stato.py`)
- `vai_in_mappa` tenta 2 BACK per chiudere banner/popup che coprono il pulsante mappa prima del secondo tentativo tap

### Fix alleanza (`alleanza.py`)
- Verifica stato home prima di iniziare la sequenza tap (messaggi poteva lasciare UI aperta)
- Fix bug `ist[5]` su dict — usava indice lista invece di `ist.get("layout")`
- Timing tap Alleanza e Dono aumentato da 1.5s a 2.0s

### Cleanup processi (`mumu.py`)
- Cleanup fine ciclo ora killa anche `MuMuVMM.exe` (frontend VM headless che rimaneva in memoria)

### Log (`log.py`)
- Rotazione `bot.log` per ciclo: il log del ciclo precedente viene archiviato in `debug/ciclo_NNN/bot.log` e `bot.log` viene resettato a ogni nuovo ciclo

### Sviluppo in sospeso — Bridge pubblico (`claude_bridge.py`)
Sviluppato ma **non funzionante** nell'attuale configurazione. Obiettivo: esporre la dashboard e il log via URL pubblico per accesso remoto (telefono, browser esterno) e analisi in tempo reale da Claude.

Tentativi effettuati:
- **ngrok** — tunnel attivo ma dominio `*.ngrok-free.dev` non raggiungibile da Claude (non in allowlist)
- **localhost.run** — tunnel SSH attivo (`*.lhr.life`) ma stesso problema di allowlist
- **Cloudflare Tunnel** — dominio `*.trycloudflare.com` ancora bloccato
- **Proxy locale con token auth** — implementato correttamente, il problema è a monte nel tunnel

Il file `claude_bridge.py` è incluso nel repo come base per sviluppi futuri. La dashboard locale su `http://localhost:8080/dashboard.html` funziona correttamente senza bridge.

### Note repository
- I file JSON runtime/stato **non sono versionati**
- I PNG sono versionati **solo** in `templates/`
- Log, debug e output runtime esclusi tramite `.gitignore`

---
## 📄 Licenza
MIT License
