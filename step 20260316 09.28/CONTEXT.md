# Doomsday Bot V5 — CONTEXT FILE
> Aggiorna questo file a fine di ogni sessione produttiva e fai `git push`.
> Claude legge questo file all'inizio di ogni sessione tramite web_fetch.

---

## Repository
- **URL:** https://github.com/faustodba/doomsday-bot-farm
- **Branch principale:** main
- **Percorso locale:** installabile in qualsiasi cartella

---

## Panoramica progetto

Bot Python per l'automazione del gioco **Doomsday: Last Survivors** su emulatori Android (BlueStacks e MuMuPlayer 12). Supporta multi-istanza con esecuzione parallela controllata da semaforo.

---

## Architettura V5

### Istanze configurate
- **FAU_00, FAU_01, FAU_02, FAU_03, FAU_04, FAU_05, FAU_07, FAU_08** (8 istanze totali)
- Max **1 istanza in parallelo** (semaforo — modificato da 2 a 1 in produzione)
- Cicli da **10 minuti**
- Timeout per istanza: **180 secondi**

### Emulatori supportati
- **BlueStacks** — avviato e stoppato per ogni ciclo
- **MuMuPlayer 12** — integrato con Provider Pattern (`config.ADB_EXE`)
- Modulo condiviso: `emulatore_base.py`

### Risoluzione di riferimento
- **960x540** (coordinate normalizzate su questa risoluzione)

---

## Moduli principali

| Modulo | Descrizione |
|--------|-------------|
| `main.py` | Entry point, argomenti `--istanze` / `--emulatore` |
| `raccolta.py` | Flusso principale raccolta risorse |
| `alleanza.py` | Automazione menu Alleanza/Dono — schedulata ogni 12h |
| `messaggi.py` | Gestione messaggi in-game — schedulata ogni 12h |
| `rifornimento.py` | Invio rifornimenti a FauMorfeus (V5.12) |
| `allocation.py` | Sistema decisionale allocazione slot raccolta (gap proporzionale) |
| `runtime.py` | Configurazione runtime modificabile senza riavvio bot |
| `bluestacks.py` | Gestione ciclo vita BlueStacks |
| `mumu.py` | Gestione ciclo vita MuMuPlayer 12 |
| `emulatore_base.py` | Modulo base condiviso tra emulatori |
| `adb.py` | Comandi ADB (tap, screenshot, keycode) |
| `ocr.py` | Lettura testo da screenshot (Tesseract) |
| `stato.py` | Macchina a stati per ogni istanza |
| `config.py` | Configurazione centralizzata |
| `timing.py` | EWMA adaptive timing |
| `log.py` | Logging centralizzato |
| `debug.py` | Utilities debug |
| `status.py` | Scrittura `status.json` per dashboard — con persistenza riavvii |
| `report.py` | Generazione report sessione |
| `launcher.py` | GUI tkinter |
| `dashboard.html` | Dashboard web real-time (fetch ogni 3s) |
| `dashboard_server.py` | Mini HTTP server porta 8080 |

### File di stato runtime per istanza
```
rifornimento_stato_{nome}_{porta}.json   ← quota giornaliera (reset 01:00 UTC)
schedule_stato_{nome}_{porta}.json       ← timestamp ultima esecuzione messaggi/alleanza
```

---

## Flusso raccolta_istanza (ordine esecuzione)

```
messaggi (se >12h) → alleanza (se >12h) → rifornimento (HOME) → vai_in_mappa → raccolta risorse
```

---

## Coordinate principali (960x540)

### alleanza.py
| Costante | Valore |
|----------|--------|
| `COORD_ALLEANZA` | (760, 505) |
| `COORD_DONO` | (877, 458) |
| `COORD_TAB_NEGOZIO` | (810, 75) |
| `COORD_TAB_ATTIVITA` | (600, 75) |
| `COORD_RIVENDICA` | (856, 240) |
| `COORD_RACCOGLI_TUTTO` | (856, 505) |
| `RIVENDICA_CLICK` | 10 |

### OCR risorse deposito — calibrato 14/03/2026
| Risorsa | Zona (x1,y1,x2,y2) | Note |
|---------|---------------------|------|
| Pomodoro | (463, 2, 525, 24) | Solo testo, icona esclusa |
| Legno | (562, 2, 625, 24) | Solo testo, icona esclusa |
| Acciaio | (658, 2, 715, 24) | Solo testo, icona esclusa |
| Petrolio | (753, 2, 822, 24) | Solo testo, allargata per valori come 732.0K |
| Diamanti | (857, 2, 925, 24) | Intero, parser dedicato `_parse_diamanti()` |

> Tutti taglio_sx=0. Calibrate su screenshot reali 960x540 (4 istanze verificate).

### OCR ETA Marcia — calibrato 14/03/2026
| Chiave config | Valore |
|---------------|--------|
| `OCR_MARCIA_ETA_ZONA` | (650, 440, 790, 465) |
| `OCR_MARCIA_ETA_BASE_W/H` | 960 / 540 |
| `OCR_MARCIA_ETA_MARGINE_S` | 5 |
| `OCR_MARCIA_ETA_MIN_S` | 8 |

> Test su 3 screenshot reali: 78s, 110s, 61s — tutti corretti.

### OCR nodo (blacklist)
| Costante | Valore |
|----------|--------|
| `TAP_LENTE_COORD` | (380, 18) |
| Zona OCR X | (430, 125, 530, 155) |
| Zona OCR Y | (535, 125, 635, 155) |

### Layout barra inferiore
| Campo ISTANZE | Indice | Valori |
|---------------|--------|--------|
| layout_barra  | [5]    | 1 = standard 5 icone (Alleanza x=760) — default |
|               |        | 2 = compatto 4 icone (Alleanza x=800) — FAU_09 |

```python
COORD_ALLEANZA_LAYOUT = { 1: (760, 505), 2: (800, 505) }
config.get_coord_alleanza(ist)  # ritorna coordinata corretta per layout
```
> Per aggiungere un nuovo layout: aggiungere voce in `COORD_ALLEANZA_LAYOUT` e impostare il numero nel campo [5] dell'istanza.

### Account destinatario rifornimento
```python
DOOMS_ACCOUNT = "FauMorfeus"   # era RIFORNIMENTO_DESTINATARIO
DOOMS_AVATAR  = "templates/avatar_faumorfeus.png"  # era RIFORNIMENTO_AVATAR
```
> La dashboard legge `data.dooms_account` dal JSON e aggiorna automaticamente tutte le label.

### rifornimento.py
| Costante | Valore |
|----------|--------|
| `RIFORNIMENTO_DESTINATARIO` | FauMorfeus |
| `RIFORNIMENTO_SOGLIA_M` | 5.0M |
| `RIFORNIMENTO_QTA_*` | 999M (il gioco applica il cap) |
| Reset quota | 01:00 UTC giornaliero |

---

## Logica raccolta risorse (raccolta.py V5.14)

### Lettura risorse
- **Inizio ciclo:** `istanza_risorse_inizio()` — snapshot deposito prima delle squadre
- **Fine ciclo:** `istanza_risorse_fine()` — snapshot dopo `vai_in_home`
- **Diamanti:** letti dalla barra superiore, `istanza_diamanti()`
- **Log visivo:** `🍅 40.5M  🪵 36.8M  ⚙ 8.5M  🛢 5.5M  💎 26548`

### ETA Marcia
- Letta dopo TAP_SQUADRA via `ocr.leggi_eta_marcia(screen_pre)`
- Attesa blacklist dinamica: `min(ETA + margine, BLACKLIST_ATTESA_NODO)`
- Log: `ETA marcia: 78s (1m18s)` → `Nodo 698_541 -> COMMITTED (ETA=78s)`

### Loop invio squadre
- Loop `while attive_correnti < obiettivo`
- Lettura reale contatore post-MARCIA
- Max 3 fallimenti consecutivi
- Blacklist TTL dinamico basato su ETA reale

---

## Calcolo produzione per istanza (status.py V5.14)

### Formula
```
produzione_N = (res_inizio_N+1 - res_inizio_N) + res_inviato_N
```

### Implementazione
- `init_ciclo()` conserva: `res_inizio` → `res_inizio_ciclo_prec`, `res_inviato` → `res_inviato_prec`
- `istanza_risorse_inizio()` calcola produzione del ciclo precedente
- Disponibile dal **2° ciclo** in poi

### Campi status.json per istanza
```json
{
  "res_inizio":            {},
  "res_inizio_ciclo_prec": {},
  "res_fine":              {},
  "res_inviato":           {},
  "res_inviato_prec":      {},
  "produzione":            {},
  "dati_storici":          false,
  "ts_ultimo_ciclo":       "14/03 08:36"
}
```

### Delta rifornimento reale
- `rifornimento.py` legge deposito PRE e POST ogni VAI
- Chiama `status.istanza_rifornimento(nome, pom_pre, leg_pre, ..., pom_post, leg_post, ...)`
- Delta accumulato in `res_inviato` per tutta la durata del ciclo

---

## Sistema decisionale allocazione (allocation.py) — V5.15

```python
RATIO_TARGET = {
    "campo":    0.3750,   # pomodoro — 37.5%
    "segheria": 0.3750,   # legno    — 37.5%
    "petrolio": 0.1875,   #          — 18.75%
    "acciaio":  0.0625,   #          —  6.25%
}
```
- Gap = target% - attuale% calcolato sul deposito OCR corrente
- Slot distribuiti per gap decrescente, cap = max(1, floor(slot/2))
- Fail-safe OCR fallito → sequenza default campo/segheria/petrolio

## Tipi nodo raccolta (raccolta.py) — V5.15

| Tipo | TAP icona | TAP CERCA |
|------|-----------|-----------|
| campo (pomodoro) | (410, 450) | (410, 350) |
| segheria (legno) | (535, 450) | (536, 351) |
| acciaio | (672, 490) | (672, 350) |
| petrolio | (820, 490) | (820, 350) |

### Verifica territorio alleanza
- Zona pixel verde: `(250, 340, 420, 370)` — riga "Buff territorio +30%"
- Soglia: 20 pixel verdi → IN territorio
- Fuori territorio → BACK + blacklist COMMITTED + tipo bloccato ciclo corrente (NO fallimenti_cons)

## Soglie rifornimento per risorsa — V5.15
```python
"pomodoro": 5.0M   # RIFORNIMENTO_SOGLIA_M
"legno":    5.0M
"petrolio": 2.5M   # RIFORNIMENTO_SOGLIA_PETROLIO_M
"acciaio":  inf    # non si invia mai
```
- Delta PRE/POST OCR dopo ogni VAI → chiama status.istanza_rifornimento()

## Runtime configurazione (runtime.py) — V5.15
- File: `runtime.json` nella root del bot
- Creato automaticamente da config.py al primo avvio
- Riletto all'inizio di ogni ciclo (nessun riavvio necessario)
- Modificabile da dashboard web (POST /runtime.json) o manualmente
- Parametri: ISTANZE_BLOCCO, WAIT_MINUTI, RIFORNIMENTO_ABILITATO, soglie, ALLOCATION_RATIO, istanze BS/MuMu (abilitata/truppe/max_squadre/layout)

---

## Schedulazione task periodici (scheduler.py)

| Task | Intervallo | Config key |
|------|-----------|------------|
| messaggi | 12 ore | `SCHEDULE_ORE_MESSAGGI` |
| alleanza | 12 ore | `SCHEDULE_ORE_ALLEANZA` |

- File stato: `schedule_stato_{nome}_{porta}.json`
- Skip log: `[SCHED] messaggi: già eseguito — skip (prossima tra 11h 27m)`
- Registrazione solo dopo esecuzione riuscita
- Rifornimento gestisce stato separatamente (non migrato)

---

## Dashboard (dashboard.html)

### Sezioni
- Riepilogo istanze (running/avvio/done/errori/inattive/squadre)
- Risorse totali aggregate (pomodoro/legno/acciaio/petrolio/diamanti)
- **Inviato FauMorfeus ciclo corrente** — aggregato per risorsa
- Stato istanze (card per istanza)
- Storico cicli (squadre/durata/sq-h/produzione/inviato)

### Card istanza mostra
- Deposito attuale (con diamanti)
- Snapshot inter-ciclo (inizio_prec → inizio_corr)
- Produzione ciclo (verde con segno +)
- Inviato FauMorfeus corrente + precedente (giallo)
- Durata/errori/ts_inizio

### Gestione riavvio bot
- `status.py` carica `status.json` da disco all'import — dati preservati
- Badge **"storico DD/MM HH:MM"** grigio corsivo per istanze non ancora riavviate
- Istanze storiche in fondo alla griglia, opacità 0.75
- `istanza_avvio()` resetta `dati_storici=False`

### Avvio server
```bash
python dashboard_server.py
# http://localhost:8080/dashboard.html
```

---

## Problemi aperti / Da risolvere
- [ ] **Launcher** non funzionante — errore `bluestacks.py` → `emulatore_base.py` → `attendi_e_raccogli_istanza`
- [ ] **cx=None** occasionale nella blacklist nodi (aumentare delay TAP_LENTE)

---

## Decisioni architetturali (non ridiscutere)
- Provider Pattern per ADB exe (`config.ADB_EXE`)
- `emulatore_base.py` condiviso tra BlueStacks e MuMu
- EWMA adaptive timing
- Screenshot PRIMA del tap nodo per OCR affidabile
- Loop while per raccolta (non range fisso)
- Lettura reale contatore post-MARCIA
- 3 fallimenti consecutivi come soglia abbandono
- Quantità rifornimento alta in config (il gioco applica il cap)
- Tassa rifornimento letta OCR dalla maschera
- Quota giornaliera su file per istanza (reset 01:00 UTC)
- **Produzione inter-ciclo** (inizio_N+1 - inizio_N + inviato_N)
- **Schedulazione 12h** messaggi/alleanza su file stato separato
- **ETA marcia OCR** per attesa dinamica blacklist
- **Persistenza dati storici** — status.json caricato all'import

---

## Storico versioni
| Versione | Note |
|----------|------|
| V2 | AutoHotkey — 14 istanze Sandboxie |
| V3 | Python, singolo emulatore |
| V4 | Multithreading, multi-emulatore, MuMu |
| V5 | Alleanza, messaggi, rifornimento, launcher, dashboard |
| V5.5 | Screenshot prima del tap nodo |
| V5.9 | Blacklist rilasciata su errore, lettura reale post-MARCIA |
| V5.10 | Loop while raccolta, OCR retry post-MARCIA |
| V5.11 | rifornimento.py rebuild template matching |
| V5.12 | rifornimento completo: coda volo, quota giornaliera |
| V5.13 | Blacklist transazionale RESERVED/COMMITTED |
| V5.13.1 | Fix SQUADRA hash check |
| V5.13.2 | ETA marcia OCR + attesa dinamica blacklist |
| V5.14 | OCR completo deposito, produzione inter-ciclo, schedulazione 12h, dashboard storico+diamanti+inviato, delta rifornimento OCR reale, layout barra per istanza, DOOMS_ACCOUNT/DOOMS_AVATAR, percorsi automatici BOT_DIR+_trova_exe |
| V5.15 | allocation.py (gap decisionale 4 risorse), raccolta.py (acciaieria/raffineria + check territorio pixel), rifornimento.py (soglie per risorsa + delta OCR), runtime.py (config JSON senza riavvio), dashboard pannello Runtime, repo pulito su faustodba/doomsday-bot-farm |

---

## Come usare questo file a inizio sessione
Dire a Claude: **"leggi il contesto"**
Claude eseguirà:
```
web_fetch → https://raw.githubusercontent.com/faustodba/doomsday-bot-farm/main/CONTEXT.md
```

---

*Ultimo aggiornamento: 2026-03-15 (sessione pulizia repo)*
