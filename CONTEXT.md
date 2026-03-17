# Doomsday Bot V5 — CONTEXT FILE
> Aggiorna questo file a fine di ogni sessione produttiva e fai `git push`.
> Claude legge questo file all'inizio di ogni sessione tramite web_fetch.

---

## Repository
- **URL:** https://github.com/faustodba/doomsday-bot-farm
- **Branch principale:** main
- **Percorso locale:** `C:\Bot-farm`

---

## Panoramica progetto

Bot Python per l'automazione del gioco **Doomsday: Last Survivors** su emulatori Android (BlueStacks e MuMuPlayer 12). Supporta multi-istanza con esecuzione parallela controllata da semaforo.

---

## Architettura V5.16

### Emulatori supportati
- **BlueStacks** — avviato e stoppato per ogni ciclo
- **MuMuPlayer 12** — integrato con contratto interfaccia unificato
- Modulo condiviso: `emulatore_base.py`
- Selezione a runtime: `python main.py` → menu [1] BS / [2] MuMu

### Contratto interfaccia emulatori (V5.16)
Ogni modulo emulatore (`bluestacks.py`, `mumu.py`) espone:
```python
NOME                              # str — "BlueStacks" | "MuMuPlayer 12"
assicura_avvio_manager(logger)    # bool — avvia MIM (BS) o verifica MuMu attivo
avvia_istanza(ist, logger)        # bool
avvia_blocco(blocco_ist, logger)  # list
attendi_e_raccogli_istanza(...)   # void
chiudi_istanza(ist, logger)       # void
chiudi_blocco(blocco_ist, logger) # void
cleanup_istanze_appese(pids, log) # void
_pids_istanze                     # dict
_pids_lock                        # Lock
```
`main.py` è completamente disaccoppiato — usa solo `emulatore.NOME` e `emulatore.assicura_avvio_manager()`.

### Struttura istanze (V5.16)
```python
# BlueStacks — 6 campi (lingua default "it")
ISTANZE = [
    [nome, interno_bs, porta_adb, truppe, max_squadre, layout],
    ...
]

# MuMuPlayer — 7 campi
ISTANZE_MUMU = [
    [nome, indice_mumu, porta_adb, truppe, max_squadre, layout, lingua],
    ...
]
# lingua: "it" | "en" — seleziona template pulsante rifornimento corretto
```

### Coordinate UI per istanza — UICoords (V5.16)
```python
# coords.py — dataclass frozen, unica fonte di verità
from coords import UICoords
coords = UICoords.da_ist(ist)   # costruita dall'elemento ISTANZE/ISTANZE_MUMU
coords.alleanza                 # risolve layout (760,505) o (800,505)
coords.btn_rifornimento_template # risolve lingua IT/EN
coords.per_tipo("campo")        # → (tap_icona, tap_cerca)
```

### Runtime configurazione (V5.16) — architettura overrides
```json
{
  "globali": { "ISTANZE_BLOCCO": 1, "WAIT_MINUTI": 1, ... },
  "overrides": {
    "FAU_09": { "abilitata": false, "max_squadre": 3 }
  }
}
```
- `runtime.json` NON contiene liste istanze — quelle stanno SEMPRE in `config.py`
- Le istanze vengono lette **fresh** da `config.py` ad ogni ciclo
- `overrides` contiene solo i delta rispetto al default (campo `abilitata`, `truppe`, `max_squadre`, `layout`)
- Migrazione automatica da struttura vecchia (con `istanze_bs`/`istanze_mumu`) alla nuova
- Aggiungere/rimuovere istanze in `config.py` è immediatamente visibile senza toccare il json

---

## Moduli principali

| Modulo | Descrizione |
|--------|-------------|
| `main.py` | Entry point, argomenti `--istanze` / `--emulatore` |
| `coords.py` | **NUOVO V5.16** — dataclass UICoords per-istanza (layout + lingua) |
| `raccolta.py` | Flusso principale raccolta risorse |
| `alleanza.py` | Automazione menu Alleanza/Dono — schedulata ogni 12h |
| `messaggi.py` | Gestione messaggi in-game — schedulata ogni 12h |
| `rifornimento.py` | Invio rifornimenti — supporto IT/EN, strategia doppia match EN |
| `allocation.py` | Sistema decisionale allocazione slot raccolta (gap proporzionale) |
| `runtime.py` | Configurazione runtime — architettura overrides (V5.16) |
| `bluestacks.py` | Gestione ciclo vita BlueStacks — contratto V5.16 |
| `mumu.py` | Gestione ciclo vita MuMuPlayer 12 — contratto V5.16 |
| `emulatore_base.py` | Modulo base condiviso tra emulatori |
| `adb.py` | Comandi ADB (tap, screenshot, keycode) |
| `ocr.py` | Lettura testo da screenshot (Tesseract) |
| `stato.py` | Macchina a stati per ogni istanza |
| `config.py` | Configurazione centralizzata — 8 sezioni numerate |
| `timing.py` | EWMA adaptive timing |
| `log.py` | Logging centralizzato |
| `debug.py` | Utilities debug |
| `status.py` | Scrittura `status.json` per dashboard — con persistenza riavvii |
| `report.py` | Generazione report sessione |
| `launcher.py` | GUI tkinter |
| `dashboard.html` | Dashboard web real-time (fetch ogni 3s) |
| `dashboard_server.py` | HTTP server porta 8080 — GET /config_istanze.json + POST /runtime.json |

### Templates
```
templates/
  avatar_faumorfeus.png         ← avatar destinatario rifornimento
  btn_risorse_approv.png        ← pulsante rifornimento IT
  btn_supply_resources.png      ← pulsante rifornimento EN (nuovo V5.16)
  arrow_up.png / arrow_down.png ← toggle lista membri
  badge_R1..R4.png              ← badge rango lista membri
```

---

## Flusso raccolta_istanza (ordine esecuzione)

```
messaggi (se >12h) → alleanza (se >12h) → rifornimento (HOME) → vai_in_mappa → raccolta risorse
```

---

## Coordinate principali (960x540)

### Layout barra inferiore
| Campo | Indice | Valori |
|-------|--------|--------|
| layout_barra | [5] | 1 = standard 5 icone, Alleanza x=760 (default) |
| | | 2 = compatto 4 icone (no Bestia), Alleanza x=800 |

```python
COORD_ALLEANZA_LAYOUT = { 1: (760, 505), 2: (800, 505) }
config.get_coord_alleanza(ist)         # coordinata corretta per layout
config.get_lingua(ist)                 # "it" | "en"
config.get_btn_rifornimento_template(ist)  # path template corretto per lingua
```

### alleanza.py
| Costante | Valore |
|----------|--------|
| `COORD_ALLEANZA` | (760, 505) layout 1 |
| `COORD_DONO` | (877, 458) |
| `COORD_TAB_NEGOZIO` | (810, 75) |
| `COORD_TAB_ATTIVITA` | (600, 75) |
| `COORD_RIVENDICA` | (856, 240) |
| `COORD_RACCOGLI_TUTTO` | (856, 505) |
| `RIVENDICA_CLICK` | 10 |

### OCR risorse deposito
| Risorsa | Zona (x1,y1,x2,y2) |
|---------|---------------------|
| Pomodoro | (463, 2, 525, 24) |
| Legno | (562, 2, 625, 24) |
| Acciaio | (658, 2, 715, 24) |
| Petrolio | (753, 2, 822, 24) |
| Diamanti | (857, 2, 925, 24) |

### OCR ETA Marcia
| Chiave | Valore |
|--------|--------|
| `OCR_MARCIA_ETA_ZONA` | (650, 440, 790, 465) |
| `OCR_MARCIA_ETA_MARGINE_S` | 5 |
| `OCR_MARCIA_ETA_MIN_S` | 8 |

---

## Rifornimento — supporto multilingua (V5.16)

```python
# config.py
ISTANZE_MUMU = [
    ["FAU_08", "8", 16384, 12000, 4, 1, "en"],  # template EN
    ["FAU_09", "9", 16672, 12000, 4, 2, "it"],  # template IT
]
RIFORNIMENTO_BTN_TEMPLATE    = "templates/btn_risorse_approv.png"    # IT
RIFORNIMENTO_BTN_TEMPLATE_EN = "templates/btn_supply_resources.png"  # EN
```

### Strategia doppia match pulsante EN
1. **Strategia 1:** template matching standard (soglia 0.75)
2. **Strategia 2** (solo EN, se S1 fallisce): soglia 0.85, deduplica cluster 20px, seleziona match con **Y massima** nella metà destra → Resource Supply è sempre bottom-right nel popup 2×2

---

## Sistema decisionale allocazione (allocation.py)

```python
RATIO_TARGET = {
    "campo":    0.3750,   # pomodoro — 37.5%
    "segheria": 0.3750,   # legno    — 37.5%
    "petrolio": 0.1875,   #          — 18.75%
    "acciaio":  0.0625,   #          —  6.25%
}
```

---

## Tipi nodo raccolta

| Tipo | TAP icona | TAP CERCA |
|------|-----------|-----------|
| campo (pomodoro) | (410, 450) | (410, 350) |
| segheria (legno) | (535, 450) | (536, 351) |
| acciaio | (672, 490) | (672, 350) |
| petrolio | (820, 490) | (820, 350) |

### Verifica territorio
- Zona pixel verde: `(250, 340, 420, 370)` — riga "Buff territorio +30%"
- Soglia: 20 pixel verdi → IN territorio

---

## Dashboard (V5.16)

### Endpoint server
| Endpoint | Metodo | Descrizione |
|----------|--------|-------------|
| `/dashboard.html` | GET | Dashboard principale |
| `/status.json` | GET | Stato bot real-time |
| `/runtime.json` | GET | Parametri runtime correnti |
| `/runtime.json` | POST | Salva parametri (dalla dashboard) — scrittura atomica diretta |
| `/config_istanze.json` | GET | **NUOVO** — istanze fresche da config.py (BS + MuMu) |

### Runtime panel
- Carica istanze fresche da `/config_istanze.json` (non dal json)
- Mostra lingua istanza (IT/EN) come badge
- Salva solo i **delta** (overrides) rispetto al default di config.py
- Selezione BS/MuMu mostra le istanze corrette per emulatore

---

## Problemi aperti / Da risolvere
- [ ] **Launcher** non funzionante
- [ ] **cx=None** occasionale nella blacklist nodi (aumentare delay TAP_LENTE)
- [ ] **ISTANZE_MUMU** indici da verificare con `MuMuManager info -v all` prima del deploy completo
- [ ] **Rifornimento EN** — zone OCR maschera (OCR_PROVVISTE, OCR_NOME_DEST) non calibrate per EN, VAI risulta disabilitato

---

## Decisioni architetturali (non ridiscutere)
- Provider Pattern per ADB exe (`config.ADB_EXE`)
- `emulatore_base.py` condiviso tra BlueStacks e MuMu
- Contratto interfaccia unificato BS/MuMu con `NOME` e `assicura_avvio_manager()`
- `coords.py` dataclass frozen — unica fonte di verità coordinate UI
- `runtime.json` con soli overrides — istanze sempre fresche da config.py
- Dashboard legge istanze da `/config_istanze.json`, non dal json
- EWMA adaptive timing
- Screenshot PRIMA del tap nodo per OCR affidabile
- Loop while per raccolta (non range fisso)
- Lettura reale contatore post-MARCIA
- 3 fallimenti consecutivi come soglia abbandono
- Quantità rifornimento alta in config (il gioco applica il cap)
- Tassa rifornimento letta OCR dalla maschera
- Quota giornaliera su file per istanza (reset 01:00 UTC)
- Produzione inter-ciclo (inizio_N+1 - inizio_N + inviato_N)
- Schedulazione 12h messaggi/alleanza su file stato separato
- ETA marcia OCR per attesa dinamica blacklist
- Persistenza dati storici — status.json caricato all'import

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
| V5.15 | allocation.py gap decisionale 4 risorse, 4 tipi nodo + verifica territorio, soglie rifornimento per risorsa, runtime.json config live, pannello Runtime dashboard, repo pulito |
| V5.16 | Contratto interfaccia BS/MuMu unificato (NOME + assicura_avvio_manager), coords.py UICoords dataclass, lingua per istanza (IT/EN) in ISTANZE_MUMU[6], template btn_supply_resources.png, strategia doppia match EN (max-Y), runtime.json architettura overrides (no liste istanze), migrazione automatica struttura vecchia, dashboard GET /config_istanze.json + POST diretto su file, config.py 8 sezioni numerate, mumu.py fix log "MUMU" + dead code rimosso |

---

## Come usare questo file a inizio sessione
Dire a Claude: **"leggi il contesto"**
Claude eseguirà:
```
web_fetch → https://raw.githubusercontent.com/faustodba/doomsday-bot-farm/main/CONTEXT.md
```

---

*Ultimo aggiornamento: 2026-03-16 (sessione V5.16 — MuMu support completo)*
