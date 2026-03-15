# ==============================================================================
#  DOOMSDAY BOT V5 - dashboard_server.py
#  Mini server HTTP per servire dashboard.html + status.json
#
#  Avvio manuale:   python dashboard_server.py
#  Avvio da main:   import dashboard_server (si avvia da solo in thread daemon)
#
#  URL dashboard:   http://localhost:8080/dashboard.html
# ==============================================================================

import http.server
import threading
import os
import sys
import json

PORT = 8080

def _run():
    # Serve i file dalla cartella dove si trova questo script
    cartella = os.path.dirname(os.path.abspath(__file__))
    os.chdir(cartella)

    class Handler(http.server.SimpleHTTPRequestHandler):

        def log_message(self, format, *args):
            pass  # Silenzia i log HTTP per non sporcare la console

        def do_POST(self):
            """Gestisce POST /runtime.json — salva i parametri runtime dal browser."""
            if self.path != "/runtime.json":
                self.send_response(404)
                self.end_headers()
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                body   = self.rfile.read(length)
                dati   = json.loads(body.decode("utf-8"))

                # Importa runtime dal bot dir (già nel sys.path poiché abbiamo fatto os.chdir)
                import importlib, sys as _sys
                if "runtime" not in _sys.modules:
                    import importlib.util
                    spec = importlib.util.spec_from_file_location(
                        "runtime", os.path.join(cartella, "runtime.py"))
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    _sys.modules["runtime"] = mod
                import runtime
                ok = runtime.salva(dati)

                self.send_response(200 if ok else 500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": ok}).encode())
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode())

        def do_OPTIONS(self):
            """CORS preflight."""
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def end_headers(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            super().end_headers()

    server = http.server.HTTPServer(("", PORT), Handler)
    print(f"[dashboard] Server avviato → http://localhost:{PORT}/dashboard.html")
    server.serve_forever()

def avvia():
    """Avvia il server in background (thread daemon). Chiamare da main.py."""
    t = threading.Thread(target=_run, daemon=True)
    t.start()

# Se lanciato direttamente (python dashboard_server.py) gira in foreground
if __name__ == "__main__":
    print(f"[dashboard] Avvio server su porta {PORT}...")
    print(f"[dashboard] Apri → http://localhost:{PORT}/dashboard.html")
    print(f"[dashboard] Ctrl+C per fermare")
    _run()
