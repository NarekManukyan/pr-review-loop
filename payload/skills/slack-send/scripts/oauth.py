#!/usr/bin/env python3
"""Browser OAuth for the CC File Sender app — captures the authorization code.

Opens the Slack authorize page, runs a one-shot localhost listener to catch the
redirect, and prints the raw authorization `code` to stdout. install.sh then
exchanges it for a token using curl (macOS system SSL — avoids Python's missing
CA-certs problem). All human-facing text goes to stderr.

Env:
  CC_CLIENT_ID   (required — install.sh passes it)
  CC_PORT        (default 53682; must match a registered redirect URL)
"""
import http.server
import os
import socketserver
import sys
import urllib.parse
import webbrowser

CLIENT_ID = os.environ.get("CC_CLIENT_ID", "")
PORT = int(os.environ.get("CC_PORT", "53682"))
REDIRECT = f"http://localhost:{PORT}/callback"
USER_SCOPES = "files:write,chat:write,channels:read,groups:read,im:write,users:read"

AUTHORIZE = "https://slack.com/oauth/v2/authorize?" + urllib.parse.urlencode(
    {"client_id": CLIENT_ID, "user_scope": USER_SCOPES, "redirect_uri": REDIRECT}
)

result = {}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        q = urllib.parse.parse_qs(parsed.query)
        result["code"] = q.get("code", [None])[0]
        result["error"] = q.get("error", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        msg = "✅ slack-send connected — you can close this tab." if result.get("code") \
            else "❌ Authorization failed — check your terminal."
        self.wfile.write(f"<html><body style='font:16px sans-serif;padding:3rem'>{msg}</body></html>".encode())

    def log_message(self, *a):
        pass


def die(m):
    print("ERR: " + m)          # stdout (parsed by install.sh)
    print("ERR: " + m, file=sys.stderr)  # stderr (always visible to the user)
    sys.exit(1)


def main():
    if not CLIENT_ID:
        die("missing CC_CLIENT_ID")
    socketserver.TCPServer.allow_reuse_address = True
    try:
        httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    except OSError as e:
        die(f"cannot bind localhost:{PORT} ({e}); set CC_PORT to a free port that's also a registered redirect URL")
    print("Opening your browser to authorize slack-send...", file=sys.stderr)
    print("If it doesn't open, paste this URL into a browser logged into Slack:\n" + AUTHORIZE + "\n", file=sys.stderr)
    webbrowser.open(AUTHORIZE)
    while "code" not in result and "error" not in result:
        httpd.handle_request()
    httpd.server_close()
    if result.get("error"):
        die("Slack returned: " + result["error"])
    code = result.get("code")
    if not code:
        die("no authorization code received")
    print(code)  # stdout: just the authorization code; install.sh exchanges it via curl


if __name__ == "__main__":
    main()
