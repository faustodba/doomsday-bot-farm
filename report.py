# ==============================================================================
#  DOOMSDAY BOT V5 - report.py
#  Genera report HTML a fine ciclo con statistiche per istanza
#
#  Output: debug/ciclo_NNN/report_ciclo_NNN.html
#
#  Sezioni:
#    1. Riepilogo ciclo (squadre inviate, errori, timing)
#    2. Dettaglio per istanza (tabella eventi cronologica)
#    3. Statistiche OCR (fail, contatori errati, backoff usati)
#    4. Link agli screenshot diagnostici (thumbnail cliccabili)
# ==============================================================================

import os
from datetime import datetime
import log as _log
import debug as _debug


# Colori per tipo evento
_COLORI = {
    "ocr_fail":            "#fff3cd",   # giallo chiaro
    "cnt_errato":          "#f8d7da",   # rosso chiaro
    "reset":               "#fde8d8",   # arancio chiaro
    "squadra_ok":          "#d4edda",   # verde chiaro
    "squadra_abbandonata": "#f5c6cb",   # rosso medio
    "completata":          "#cce5ff",   # blu chiaro
    "errore_mappa":        "#e2e3e5",   # grigio
}

_ICONE = {
    "ocr_fail":            "⚠️",
    "cnt_errato":          "❌",
    "reset":               "🔄",
    "squadra_ok":          "✅",
    "squadra_abbandonata": "🚫",
    "completata":          "🏁",
    "errore_mappa":        "🗺️",
}


def _badge(evento: str) -> str:
    colore = _COLORI.get(evento, "#e9ecef")
    icona  = _ICONE.get(evento, "•")
    return (f'<span style="background:{colore};padding:2px 7px;border-radius:10px;'
            f'font-size:0.85em;white-space:nowrap">{icona} {evento}</span>')


def _thumb(path: str, ciclo_dir: str) -> str:
    """Ritorna tag <img> con path relativo se il file esiste."""
    if not path or not os.path.exists(path):
        return ""
    rel = os.path.relpath(path, ciclo_dir)
    return (f'<a href="{rel}" target="_blank">'
            f'<img src="{rel}" style="height:48px;border:1px solid #ccc;'
            f'border-radius:3px;margin:1px" title="{os.path.basename(path)}"></a>')


def genera_report(ciclo: int, risultati: dict) -> str:
    """
    Genera il report HTML per il ciclo specificato.

    risultati: { nome: n_squadre_inviate } (n < 0 = errore)

    Ritorna path del file generato.
    """
    ciclo_dir = _debug.ciclo_dir()
    if not ciclo_dir:
        return ""

    eventi = _log.get_eventi(ciclo)
    ts_gen = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # --- Statistiche aggregate per istanza ---
    stats = {}
    for ist in risultati:
        ev_ist = [e for e in eventi if e["nome"] == ist]
        stats[ist] = {
            "inviate":     risultati[ist] if risultati[ist] >= 0 else 0,
            "esito_codice": risultati[ist],
            "ocr_fail":    sum(1 for e in ev_ist if e["evento"] == "ocr_fail"),
            "cnt_errati":  sum(1 for e in ev_ist if e["evento"] == "cnt_errato"),
            "reset":       sum(1 for e in ev_ist if e["evento"] == "reset"),
            "abbandonate": sum(1 for e in ev_ist if e["evento"] == "squadra_abbandonata"),
            "eventi":      ev_ist,
        }

    totale_squadre = sum(s["inviate"] for s in stats.values())
    totale_ocr_fail = sum(s["ocr_fail"] for s in stats.values())
    totale_cnt_err  = sum(s["cnt_errati"] for s in stats.values())

    # --- Screenshot disponibili per ciclo ---
    screens = {}
    if ciclo_dir and os.path.isdir(ciclo_dir):
        for f in sorted(os.listdir(ciclo_dir)):
            if not f.endswith(".png"):
                continue
            parts = f.split("_")
            nome_ist = parts[0] if parts else ""
            if nome_ist not in screens:
                screens[nome_ist] = []
            screens[nome_ist].append(os.path.join(ciclo_dir, f))

    # =========================================================================
    # HTML
    # =========================================================================
    html_lines = [
        "<!DOCTYPE html>",
        '<html lang="it">',
        "<head>",
        '<meta charset="utf-8">',
        f'<title>Doomsday Bot V5 - Ciclo {ciclo:03d}</title>',
        "<style>",
        "  body { font-family: 'Segoe UI', sans-serif; margin: 20px; background: #f8f9fa; color: #212529; }",
        "  h1   { color: #343a40; }",
        "  h2   { color: #495057; border-bottom: 2px solid #dee2e6; padding-bottom: 4px; margin-top: 30px; }",
        "  h3   { color: #6c757d; margin-top: 20px; }",
        "  table { border-collapse: collapse; width: 100%; margin-bottom: 20px; background: #fff; border-radius: 6px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.1); }",
        "  th   { background: #343a40; color: #fff; padding: 8px 12px; text-align: left; font-size: 0.9em; }",
        "  td   { padding: 6px 12px; border-bottom: 1px solid #e9ecef; font-size: 0.88em; vertical-align: middle; }",
        "  tr:last-child td { border-bottom: none; }",
        "  tr:hover td { background: #f1f3f5; }",
        "  .ok    { color: #155724; font-weight: bold; }",
        "  .err   { color: #721c24; font-weight: bold; }",
        "  .warn  { color: #856404; font-weight: bold; }",
        "  .num   { text-align: right; font-family: monospace; }",
        "  .card  { background: #fff; border-radius: 8px; padding: 16px 20px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,.1); }",
        "  .kpi   { display: inline-block; min-width: 120px; margin: 6px 10px; padding: 10px 16px; border-radius: 6px; background: #e9ecef; text-align: center; }",
        "  .kpi .val { font-size: 1.8em; font-weight: bold; line-height: 1.1; }",
        "  .kpi .lbl { font-size: 0.78em; color: #6c757d; }",
        "  .screens { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 8px; }",
        "  details summary { cursor: pointer; color: #0d6efd; font-size: 0.9em; }",
        "  details { margin-top: 6px; }",
        "</style>",
        "</head>",
        "<body>",
        f'<h1>🤖 Doomsday Bot V5 — Ciclo {ciclo:03d}</h1>',
        f'<p style="color:#6c757d;font-size:0.9em">Generato: {ts_gen} | Cartella: {ciclo_dir}</p>',
    ]

    # -------------------------------------------------------------------------
    # 1. KPI riepilogo
    # -------------------------------------------------------------------------
    html_lines += [
        '<h2>📊 Riepilogo ciclo</h2>',
        '<div class="card">',
    ]
    for nome, s in stats.items():
        esito = s["esito_codice"]
        if esito >= 0:
            colore_kpi = "#d4edda"
        elif esito == -2:
            colore_kpi = "#fff3cd"
        else:
            colore_kpi = "#f8d7da"

        html_lines.append(
            f'<div class="kpi" style="background:{colore_kpi}">'
            f'<div class="val">{s["inviate"]}</div>'
            f'<div class="lbl">{nome}</div>'
            f'</div>'
        )

    html_lines += [
        '<br><br>',
        f'<div class="kpi" style="background:#cce5ff"><div class="val">{totale_squadre}</div><div class="lbl">Squadre totali</div></div>',
        f'<div class="kpi" style="background:#fff3cd"><div class="val">{totale_ocr_fail}</div><div class="lbl">OCR fail</div></div>',
        f'<div class="kpi" style="background:#f8d7da"><div class="val">{totale_cnt_err}</div><div class="lbl">Contatori errati</div></div>',
        '</div>',
    ]

    # -------------------------------------------------------------------------
    # 2. Tabella riepilogo per istanza
    # -------------------------------------------------------------------------
    html_lines += [
        '<h2>📋 Dettaglio istanze</h2>',
        '<table>',
        '<tr><th>Istanza</th><th>Squadre</th><th>OCR fail</th>'
        '<th>Cnt errati</th><th>Reset</th><th>Abbandonate</th><th>Esito</th></tr>',
    ]
    for nome, s in stats.items():
        esito_cod = s["esito_codice"]
        if esito_cod >= 0:
            esito_txt = f'<span class="ok">OK ({esito_cod})</span>'
        elif esito_cod == -2:
            esito_txt = '<span class="warn">TIMEOUT</span>'
        elif esito_cod == -3:
            esito_txt = '<span class="err">WATCHDOG</span>'
        else:
            esito_txt = '<span class="err">ERRORE</span>'

        def _cl(v, soglia_warn=1, soglia_err=3):
            if v == 0: return ""
            if v < soglia_err: return ' class="warn"'
            return ' class="err"'

        html_lines.append(
            f"<tr>"
            f"<td><strong>{nome}</strong></td>"
            f'<td class="num">{s["inviate"]}</td>'
            f'<td class="num"{_cl(s["ocr_fail"])}>{s["ocr_fail"]}</td>'
            f'<td class="num"{_cl(s["cnt_errati"])}>{s["cnt_errati"]}</td>'
            f'<td class="num"{_cl(s["reset"])}>{s["reset"]}</td>'
            f'<td class="num"{_cl(s["abbandonate"],1,2)}>{s["abbandonate"]}</td>'
            f"<td>{esito_txt}</td>"
            f"</tr>"
        )
    html_lines.append("</table>")

    # -------------------------------------------------------------------------
    # 3. Dettaglio eventi per istanza + screenshot
    # -------------------------------------------------------------------------
    html_lines.append('<h2>🔍 Log eventi per istanza</h2>')

    for nome, s in stats.items():
        html_lines += [
            f'<h3>{nome}</h3>',
            '<div class="card">',
        ]

        if s["eventi"]:
            html_lines += [
                "<table>",
                "<tr><th>Ora</th><th>Evento</th><th>Squadra</th><th>Tentativo</th><th>Dettaglio</th></tr>",
            ]
            for ev in s["eventi"]:
                html_lines.append(
                    f'<tr style="background:{_COLORI.get(ev["evento"],"#fff")}">'
                    f'<td style="font-family:monospace">{ev["ts"]}</td>'
                    f'<td>{_badge(ev["evento"])}</td>'
                    f'<td class="num">{ev["squadra"] if ev["squadra"] else ""}</td>'
                    f'<td class="num">{ev["tentativo"] if ev["tentativo"] else ""}</td>'
                    f'<td>{ev["dettaglio"]}</td>'
                    f'</tr>'
                )
            html_lines.append("</table>")
        else:
            html_lines.append('<p style="color:#6c757d;font-style:italic">Nessun evento registrato.</p>')

        # Screenshot per questa istanza
        ist_screens = screens.get(nome, [])
        if ist_screens:
            html_lines.append(
                f'<details><summary>📸 Screenshot ({len(ist_screens)})</summary>'
                '<div class="screens">'
            )
            for sp in ist_screens:
                html_lines.append(_thumb(sp, ciclo_dir))
            html_lines.append("</div></details>")

        html_lines.append("</div>")  # card

    # -------------------------------------------------------------------------
    # Footer
    # -------------------------------------------------------------------------
    html_lines += [
        '<p style="color:#adb5bd;font-size:0.8em;margin-top:40px">'
        f'Doomsday Bot V5 · Ciclo {ciclo:03d} · {ts_gen}</p>',
        "</body>",
        "</html>",
    ]

    # Scrivi file
    out_path = os.path.join(ciclo_dir, f"report_ciclo_{ciclo:03d}.html")
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(html_lines))
        return out_path
    except Exception as e:
        return ""