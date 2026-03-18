# ==============================================================================
#  DOOMSDAY BOT V5 - claude_bridge.py
#  Espone dashboard e API bot via tunnel pubblico (localhost.run)
#
#  AVVIO:
#    python claude_bridge.py
#
#  ACCESSO PUBBLICO:
#    Dashboard:  https://xxxx.lhr.life/dashboard.html?token=TOKEN
#    Log:        https://xxxx.lhr.life/log?token=TOKEN
#    Status:     https://xxxx.lhr.life/status.json?token=TOKEN
#    Runtime:    https://xxxx.lhr.life/runtime.json?token=TOKEN
#
#  ACCESSO LOCALE (senza token):
#    http://localhost:8080/dashboard.html
#
#  SICUREZZA:
#    - Ogni richiesta pubblica deve contenere ?token=TOKEN
#    - Senza token: 403 Forbidden
#    - Il token è validato dal proxy, il server locale resta invariato
#    - POST su runtime.json richiede token sia in querystring che nel body JSON
# ==============================================================================

import sys
import os
import time
import subprocess
import threading
import re
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import urlopen, Request
from urllib.parse import urlparse, parse_qs, urlencode
from urllib.error import URLError

BOT_DIR    = os.path.dirname(os.path.abspath(__file__))
BOT_PORT   = 8080
PROXY_PORT = 8082

# ---------------------------------------------------------------------------
# TOKEN DI ACCESSO — cambia con uno tuo o lascia quello generato
# ---------------------------------------------------------------------------
ACCESS_TOKEN = "D1mjLz405StWX_RYugpfDD7ayJXVS6OW"

# ---------------------------------------------------------------------------
# Proxy con autenticazione token
# ---------------------------------------------------------------------------
class ProxyHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        ts = time.strftime("%H:%M:%S")
        status = args[1] if len(args) > 1 else "?"
        print(f"  [{ts}] {status} {self.path[:80]}")

    def _token_valido(self, qs: dict) -> bool:
        token = qs.get("token", [None])[0]
        return token == ACCESS_TOKEN

    def _risposta_403(self):
        body = b'{"error": "Accesso non autorizzato. Aggiungi ?token=TOKEN all\'URL."}'
        self.send_response(403)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        # robots.txt — sempre pubblico (necessario per i crawler)
        if self.path == "/robots.txt":
            body = b"User-agent: *\nDisallow: /\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        parsed = urlparse(self.path)
        qs     = parse_qs(parsed.query)

        # Valida token
        if not self._token_valido(qs):
            self._risposta_403()
            return

        # Rimuovi token dalla querystring prima di girare al server locale
        qs_pulita = {k: v for k, v in qs.items() if k != "token"}
        nuovo_qs  = urlencode(qs_pulita, doseq=True)
        path_locale = parsed.path + (f"?{nuovo_qs}" if nuovo_qs else "")

        # Gira la richiesta al server locale
        target = f"http://localhost:{BOT_PORT}{path_locale}"
        try:
            req = Request(target, headers={"User-Agent": "DoomsdayBridge/1.0"})
            with urlopen(req, timeout=15) as resp:
                body = resp.read()
                self.send_response(resp.status)
                for k, v in resp.headers.items():
                    if k.lower() not in ("transfer-encoding", "connection"):
                        self.send_header(k, v)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
        except URLError as e:
            msg = json.dumps({"error": f"Server bot non raggiungibile: {e}"}).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)

    def do_POST(self):
        parsed = urlparse(self.path)
        qs     = parse_qs(parsed.query)

        # Valida token in querystring
        if not self._token_valido(qs):
            self._risposta_403()
            return

        # Leggi body
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length)

        # Gira la richiesta al server locale
        target = f"http://localhost:{BOT_PORT}{parsed.path}"
        try:
            req = Request(target, data=body, method="POST",
                         headers={"Content-Type": "application/json",
                                  "User-Agent": "DoomsdayBridge/1.0"})
            with urlopen(req, timeout=15) as resp:
                resp_body = resp.read()
                self.send_response(resp.status)
                for k, v in resp.headers.items():
                    if k.lower() not in ("transfer-encoding", "connection"):
                        self.send_header(k, v)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(resp_body)
        except URLError as e:
            msg = json.dumps({"error": f"Server bot non raggiungibile: {e}"}).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)


def _avvia_proxy():
    HTTPServer(("", PROXY_PORT), ProxyHandler).serve_forever()


# ---------------------------------------------------------------------------
# Avvio tunnel localhost.run
# ---------------------------------------------------------------------------
def _avvia_tunnel():
    cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=3",
        "-R", f"80:localhost:{PROXY_PORT}",
        "nokey@localhost.run"
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True, bufsize=1
    )
    url = None
    for line in proc.stdout:
        s = line.strip()
        if s and "lhr.life" not in s and "localhost.run" not in s:
            print(f"  {s}")
        m = re.search(r"https://[a-zA-Z0-9\-]+\.lhr\.life", s)
        if m:
            url = m.group(0)
            break
    return url, proc


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
print()
print("=" * 60)
print("  DOOMSDAY BOT — Bridge pubblico con autenticazione")
print("=" * 60)
print()

# Avvia proxy
threading.Thread(target=_avvia_proxy, daemon=True).start()
print(f"  Proxy locale avviato su porta {PROXY_PORT}")
time.sleep(0.5)

# Apri tunnel
print(f"  Connessione a localhost.run (attendi ~15s)...")
url, proc = _avvia_tunnel()

if not url:
    print("  [ERRORE] URL tunnel non trovato.")
    sys.exit(1)

print()
print("=" * 60)
print("  BRIDGE ATTIVO")
print("=" * 60)
print()
print(f"  Token accesso: {ACCESS_TOKEN}")
print()
print(f"  Dashboard:  {url}/dashboard.html?token={ACCESS_TOKEN}")
print(f"  Log:        {url}/log?token={ACCESS_TOKEN}")
print(f"  Status:     {url}/status.json?token={ACCESS_TOKEN}")
print(f"  Runtime:    {url}/runtime.json?token={ACCESS_TOKEN}")
print()
print(f"  Accesso locale (senza token):")
print(f"    http://localhost:{BOT_PORT}/dashboard.html")
print()
print("  Premi Ctrl+C per chiudere.")
print("=" * 60)
print()

try:
    while True:
        time.sleep(60)
        ts = time.strftime("%H:%M:%S")
        print(f"  [{ts}] Bridge attivo — {url}")
except KeyboardInterrupt:
    print("\n  Chiusura bridge...")
    proc.terminate()
    print("  Bridge chiuso.\n")
