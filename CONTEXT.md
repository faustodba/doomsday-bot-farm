# Doomsday Bot V5 — CONTEXT FILE

## 2026-03-18 — V5.17 (fix raccolta + robustezza)

### raccolta.py
- BUG1: attesa nodo blacklist ora in mappa pulita (BACK prima del sleep, poi CERCA r3 da stato pulito)
- BUG3: uscita immediata loop quando tutti i tipi pianificati bloccati; fallback automatico su tipi alternativi (campo/segheria/petrolio/acciaio)
- BUG4: recovery post-marcia fallita con back_rapidi_e_stato(n=4) + gestione home/overlay
- Contatore reale a fine ciclo: rilegge dal gioco, riprende raccolta se slot liberi con sequenza fresca
- OCR risorse: retry se almeno una risorsa principale è -1
- sleep(2s) dopo vai_in_mappa per stabilizzazione widget contatore squadre
- _leggi_attive_con_retry: rimosso BACK pericoloso nei retry, aggiunta verifica stato prima di OCR
- UICoords fallback corretto da lista a dict: `{"nome": nome, "layout": 1, "lingua": "it"}`

### stato.py
- vai_in_mappa: 2 BACK per chiudere banner dopo primo tap fallito

### alleanza.py
- Verifica stato home prima dei tap
- Fix bug ist[5] su dict → ist.get("layout", 1)
- Timing tap Alleanza/Dono: 1.5s → 2.0s

### mumu.py
- cleanup_istanze_appese: aggiunto kill MuMuVMM.exe (residuo VM headless)
- Aggiunta funzione _get_pids_per_processo(nome_exe)

### log.py
- init_ciclo: archivia bot.log in debug/ciclo_NNN/bot.log e resetta bot.log a ogni ciclo

### dashboard_server.py
- Aggiunti endpoint: /log (ultime N righe bot.log con filtri), /ping, /robots.txt

### claude_bridge.py (nuovo — in sospeso)
- Obiettivo: esporre dashboard e log via URL pubblico per accesso remoto e analisi da Claude
- Proxy locale porta 8082 con autenticazione token implementata correttamente
- Tunnel testati: ngrok (*.ngrok-free.dev), localhost.run (*.lhr.life), Cloudflare (*.trycloudflare.com)
- Tutti i tunnel bloccati dalla allowlist del sistema web_fetch di Claude
- File incluso nel repo come base per sviluppi futuri — NON usare in produzione
- dashboard.html: token injection automatico su tutte le fetch (funzionale per uso futuro)

## 2026-03 — V5.16a (consolidamento)
- Hardening MuMuPlayer: ADB stabile e cleanup affidabile
- Migliorata robustezza runtime e flusso principale
- Fix dashboard runtime e gestione overrides
- Chiarita policy repository (png solo in templates, json esclusi)

## 2026-03-21 — V5.18 (selezione livello nodo + produzione oraria dashboard)

### raccolta.py
- `_cerca_nodo`: selezione livello nodo via popup UI — reset con 6 tap su `—` (porta sempre a Lv.1 indipendentemente dal livello precedente), poi `(livello-1)` tap su `+`
- Coordinate assolute per `—`, `+`, SEARCH misurate su screenshot reali 960x540 per tutti i tipi (campo/segheria/acciaio/petrolio) — necessario perché il popup del petrolio è clamped al bordo destro dello schermo
- Aggiunto parametro `livello_target` a `_cerca_nodo` e `_tap_invia_squadra`, propagato fino a `raccolta_istanza`
- `raccolta_istanza`: legge `livello` dall'istanza (`ist.get("livello", config.LIVELLO_RACCOLTA)`)
- OCR risorse inizio ciclo: retry multiplo con backoff 2s → 3s → 4s (era singolo retry fisso a 2s); ogni retry aggiorna solo le risorse ancora mancanti, preserva quelle già lette
- `_leggi_livello_nodo`: funzione OCR per leggere livello dal titolo popup nodo (pattern IT "Lv.N" e EN "Level: N") — usata per scartare nodi sotto-livello

### config.py
- Aggiunto campo `"livello": 6` a tutte le istanze `ISTANZE` (BlueStacks) e `ISTANZE_MUMU` (MuMuPlayer)
- Aggiornato commento campi comuni con descrizione campo `livello`

### dashboard.html
- Aggiunta colonna **Lv.** nella tabella runtime istanze con `<select>` opzioni 5/6/7
- Salvataggio `livello` come override esattamente come truppe/squadre/layout
- Nuovo pannello **Produzione oraria** in sidebar: M/h ciclo corrente + media storica ultimi 10 cicli per tutte e 4 le risorse + totale aggregato
- Produzione oraria visibile anche nella card di ogni istanza
- Nuova colonna M/h nello storico cicli

### dashboard_server.py
- Esposto campo `livello` in `/config_istanze.json` per entrambi BS e MuMu

### runtime.py
- `istanze_attive()`: aggiunto supporto override `livello` per-istanza
