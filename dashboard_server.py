# ==============================================================================
# DOOMSDAY BOT V5 - dashboard_server.py (profilo + robustezza)
# ==============================================================================

import http.server
import threading
import os
import json
import time

PORT = 8080
LOG_TAIL_LINES = 300


def _importa_modulo(nome, cartella):
    import sys
    import importlib.util
    if nome not in sys.modules:
        spec = importlib.util.spec_from_file_location(nome, os.path.join(cartella, f"{nome}.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        sys.modules[nome] = mod
    return sys.modules[nome]


def _safe_write(wfile, data: bytes):
    try:
        wfile.write(data)
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        return


def _run():
    cartella = os.path.dirname(os.path.abspath(__file__))
    os.chdir(cartella)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def end_headers(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("ngrok-skip-browser-warning", "true")
            super().end_headers()

        def do_OPTIONS(self):
            self.send_response(200)
            self.end_headers()

        def do_GET(self):
            if self.path.startswith("/config_istanze.json"):
                return self._serve_config_istanze()
            if self.path.startswith("/log"):
                return self._serve_log()
            if self.path.startswith("/ping"):
                return self._json_ok({"ok": True, "ts": time.time(), "version": "profilo-fix"})
            if self.path.startswith("/robots.txt"):
                body = b"User-agent: *\nAllow: /\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                _safe_write(self.wfile, body)
                return
            try:
                super().do_GET()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return

        def _serve_log(self):
            try:
                from urllib.parse import urlparse, parse_qs
                qs = parse_qs(urlparse(self.path).query)
                n = int(qs.get("n", [LOG_TAIL_LINES])[0])
                since = qs.get("since", [None])[0]
                filtro = qs.get("filter", [None])[0]

                log_path = os.path.join(cartella, "bot.log")
                if not os.path.exists(log_path):
                    return self._json_ok({"righe": [], "totale": 0})

                with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                    righe = f.readlines()

                if filtro:
                    righe = [r for r in righe if filtro in r]

                if since:
                    def _ts(riga):
                        try:
                            return riga[1:9]
                        except Exception:
                            return ""
                    righe = [r for r in righe if _ts(r) >= since]

                righe = righe[-n:]
                return self._json_ok({"righe": [r.rstrip("\n") for r in righe], "totale": len(righe), "ts": time.time()})
            except Exception as e:
                return self._json_err(str(e))

        def _serve_config_istanze(self):
            try:
                cfg = _importa_modulo("config", cartella)

                def _bs(ist):
                    return {
                        "nome": ist.get("nome", ""),
                        "interno": ist.get("interno", ""),
                        "porta": ist.get("porta", ""),
                        "truppe": ist.get("truppe", 12000),
                        "max_squadre": ist.get("max_squadre", 4),
                        "layout": ist.get("layout", 1),
                        "lingua": ist.get("lingua", "it"),
                        "abilitata": ist.get("abilitata", True),
                        "livello": ist.get("livello", 6),
                        "profilo": ist.get("profilo", "full"),
                    }

                def _mumu(ist):
                    return {
                        "nome": ist.get("nome", ""),
                        "indice": ist.get("indice", ""),
                        "porta": ist.get("porta", 16384),
                        "truppe": ist.get("truppe", 12000),
                        "max_squadre": ist.get("max_squadre", 4),
                        "layout": ist.get("layout", 1),
                        "lingua": ist.get("lingua", "en"),
                        "abilitata": ist.get("abilitata", True),
                        "livello": ist.get("livello", 6),
                        "profilo": ist.get("profilo", "full"),
                    }

                payload = {
                    "istanze_bs": [_bs(i) for i in getattr(cfg, "ISTANZE", [])],
                    "istanze_mumu": [_mumu(i) for i in getattr(cfg, "ISTANZE_MUMU", [])],
                }
                return self._json_ok(payload)
            except Exception as e:
                return self._json_err(str(e))

        def do_POST(self):
            if self.path != "/runtime.json":
                self.send_response(404)
                self.end_headers()
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                dati = json.loads(body.decode("utf-8"))
                path_json = os.path.join(cartella, "runtime.json")
                path_tmp = path_json + ".tmp"
                with open(path_tmp, "w", encoding="utf-8") as f:
                    json.dump(dati, f, ensure_ascii=False, indent=2)
                os.replace(path_tmp, path_json)
                return self._json_ok({"ok": True})
            except Exception as e:
                return self._json_err(str(e))

        def _json_ok(self, payload, status=200):
            body = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            _safe_write(self.wfile, body)

        def _json_err(self, msg, status=500):
            body = json.dumps({"ok": False, "error": msg}, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            _safe_write(self.wfile, body)

    server = http.server.HTTPServer(("", PORT), Handler)
    print(f"[dashboard] Server avviato → http://localhost:{PORT}/dashboard.html")
    server.serve_forever()


def avvia():
    t = threading.Thread(target=_run, daemon=True)
    t.start()


if __name__ == "__main__":
    _run()
