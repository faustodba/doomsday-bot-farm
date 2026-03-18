# ==============================================================================
#  DOOMSDAY BOT V5 - dashboard_server.py
#  Mini server HTTP per servire dashboard.html + status.json
#
#  Avvio manuale:   python dashboard_server.py
#  Avvio da main:   import dashboard_server (si avvia da solo in thread daemon)
#
#  URL dashboard:   http://localhost:8080/dashboard.html
#
#  Endpoints:
#    GET  /dashboard.html        → dashboard
#    GET  /status.json           → stato bot (aggiornato da status.py)
#    GET  /runtime.json          → parametri runtime correnti
#    POST /runtime.json          → salva parametri runtime (dalla dashboard)
#    GET  /config_istanze.json   → istanze fresche da config.py (BS + MuMu)
# ==============================================================================

import http.server
import threading
import os
import json
import time

PORT = 8080
LOG_TAIL_LINES = 300  # righe massime restituite da /log


def _importa_modulo(nome, cartella):
    """Importa un modulo Python dalla cartella del bot, con cache in sys.modules."""
    import sys, importlib.util
    if nome not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            nome, os.path.join(cartella, f"{nome}.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        sys.modules[nome] = mod
    return sys.modules[nome]


def _run():
    cartella = os.path.dirname(os.path.abspath(__file__))
    os.chdir(cartella)

    class Handler(http.server.SimpleHTTPRequestHandler):

        def log_message(self, format, *args):
            pass  # Silenzia i log HTTP

        # ------------------------------------------------------------------
        # CORS — aggiunto a ogni risposta
        # ------------------------------------------------------------------
        def end_headers(self):
            self.send_header("Access-Control-Allow-Origin",  "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            # Header richiesto da ngrok per bypassare la pagina interstitial
            # (necessario per accesso programmatico via Claude/curl/script)
            self.send_header("ngrok-skip-browser-warning", "true")
            super().end_headers()

        def do_OPTIONS(self):
            """CORS preflight."""
            self.send_response(200)
            self.end_headers()

        # ------------------------------------------------------------------
        # GET
        # ------------------------------------------------------------------
        def do_GET(self):
            if self.path.startswith("/config_istanze.json"):
                self._serve_config_istanze()
                return
            if self.path.startswith("/log"):
                self._serve_log()
                return
            if self.path.startswith("/ping"):
                self._json_ok({"ok": True, "ts": time.time(), "version": "ngrok-header-v2"})
                return
            if self.path.startswith("/robots.txt"):
                body = b"User-agent: *\nAllow: /\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            # Tutti gli altri GET → file statici (dashboard.html, status.json, ...)
            super().do_GET()

        def _serve_log(self):
            """Restituisce le ultime LOG_TAIL_LINES righe di bot.log come JSON.
            Parametri querystring:
              ?n=100    → ultime 100 righe (default LOG_TAIL_LINES)
              ?since=09:15:00  → solo righe con timestamp >= HH:MM:SS
              ?filter=FAU_01   → solo righe che contengono il testo
            """
            try:
                from urllib.parse import urlparse, parse_qs
                qs = parse_qs(urlparse(self.path).query)
                n       = int(qs.get("n",      [LOG_TAIL_LINES])[0])
                since   = qs.get("since",  [None])[0]
                filtro  = qs.get("filter", [None])[0]

                log_path = os.path.join(cartella, "bot.log")
                if not os.path.exists(log_path):
                    self._json_ok({"righe": [], "totale": 0})
                    return

                with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                    righe = f.readlines()

                # Applica filtro testo
                if filtro:
                    righe = [r for r in righe if filtro in r]

                # Applica filtro timestamp (since=HH:MM:SS)
                if since:
                    def _ts(riga):
                        # formato: [HH:MM:SS]
                        try: return riga[1:9]
                        except: return ""
                    righe = [r for r in righe if _ts(r) >= since]

                # Prendi ultime n righe
                righe = righe[-n:]

                payload = {
                    "righe":  [r.rstrip("\n") for r in righe],
                    "totale": len(righe),
                    "ts":     time.time(),
                }
                self._json_ok(payload)
            except Exception as e:
                self._json_err(str(e))

        def _serve_config_istanze(self):
            """Restituisce le istanze fresche da config.py come JSON."""
            try:
                cfg = _importa_modulo("config", cartella)

                def _bs(ist):
                    return {
                        "nome":        ist.get("nome", ""),
                        "interno":     ist.get("interno", ""),
                        "porta":       ist.get("porta", ""),
                        "truppe":      ist.get("truppe", 12000),
                        "max_squadre": ist.get("max_squadre", 4),
                        "layout":      ist.get("layout", 1),
                        "lingua":      ist.get("lingua", "it"),
                        "abilitata":   ist.get("abilitata", True),
                    }

                def _mumu(ist):
                    return {
                        "nome":        ist.get("nome", ""),
                        "indice":      ist.get("indice", ""),
                        "porta":       ist.get("porta", 16384),
                        "truppe":      ist.get("truppe", 12000),
                        "max_squadre": ist.get("max_squadre", 4),
                        "layout":      ist.get("layout", 1),
                        "lingua":      ist.get("lingua", "en"),
                        "abilitata":   ist.get("abilitata", True),
                    }

                payload = {
                    "istanze_bs":   [_bs(i)   for i in getattr(cfg, "ISTANZE",      [])],
                    "istanze_mumu": [_mumu(i) for i in getattr(cfg, "ISTANZE_MUMU", [])],
                }
                self._json_ok(payload)
            except Exception as e:
                self._json_err(str(e))

        # ------------------------------------------------------------------
        # POST
        # ------------------------------------------------------------------
        def do_POST(self):
            if self.path != "/runtime.json":
                self.send_response(404)
                self.end_headers()
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                body   = self.rfile.read(length)
                dati   = json.loads(body.decode("utf-8"))

                # Scrivi direttamente su runtime.json nella cartella del bot
                # Scrittura atomica: tmp → replace
                path_json = os.path.join(cartella, "runtime.json")
                path_tmp  = path_json + ".tmp"
                with open(path_tmp, "w", encoding="utf-8") as f:
                    json.dump(dati, f, ensure_ascii=False, indent=2)
                os.replace(path_tmp, path_json)

                self._json_ok({"ok": True})
            except Exception as e:
                self._json_err(str(e))

        # ------------------------------------------------------------------
        # Utility
        # ------------------------------------------------------------------
        def _json_ok(self, payload, status=200):
            body = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json_err(self, msg, status=500):
            body = json.dumps({"ok": False, "error": msg}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = http.server.HTTPServer(("", PORT), Handler)
    print(f"[dashboard] Server avviato → http://localhost:{PORT}/dashboard.html")
    server.serve_forever()


def avvia():
    """Avvia il server in background (thread daemon). Chiamare da main.py."""
    t = threading.Thread(target=_run, daemon=True)
    t.start()


if __name__ == "__main__":
    print(f"[dashboard] Avvio server su porta {PORT}...")
    print(f"[dashboard] Apri → http://localhost:{PORT}/dashboard.html")
    print(f"[dashboard] Ctrl+C per fermare")
    _run()
