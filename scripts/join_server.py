"""Self-contained "open a link, you're in" join server for the Bard fabric.

The minimal web slice of device onboarding (the Flutter deep-link version is
the P1 follow-up). An iPhone on the tailnet opens
``http://<this-host>:5180/join?invite=<token>`` in mobile Safari, types a
device name, and taps Join. This server proxies the redemption to the live
control-plane Registry **server-side** so the browser never makes a
cross-origin request (no CORS to configure) and the manager JWT never leaves
the host.

Flow per request:

1. ``GET /join?invite=<token>`` -> a tiny mobile-friendly HTML page with a
   device-name field (default "iPhone") and a Join button.
2. The page POSTs ``{token, deviceId, label}`` same-origin to
   ``POST /join/redeem`` on THIS server.
3. This server forwards to the Registry ``POST /invites/{token}/redeem`` with
   ``{deviceId, label}`` (no manager bearer -- the invite token IS the
   authorization, per invite.schema.json). On success it ALSO calls
   ``POST /devices/{deviceId}/workgroup {"name": <workgroup>}`` with the
   manager JWT so the new device lands in the ``home`` workgroup.
4. Returns a friendly "You're connected as <name>" page. The one-time
   ``deviceSecret`` from the redeem response is NOT shown and NOT stored
   anywhere -- the server keeps nothing.

Configuration (all via env -- CLAUDE.md config-over-hardcoding; the JWT is
read from the env-pointed file at runtime, never embedded):

* ``BARDPRO_REGISTRY_BASE``      -- Registry base URL
                                    (default ``http://edwards-macbook-pro:8081``).
* ``BARDPRO_MANAGER_JWT_FILE``   -- path to the manager JWT file
                                    (default ``/tmp/bardpro-fabric/manager.jwt``;
                                    resolved with ``tempfile.gettempdir()`` so it
                                    is portable, not a hardcoded ``/tmp``).
* ``BARDPRO_JOIN_WORKGROUP``     -- workgroup the device is assigned to on
                                    success (default ``home``).
* ``BARDPRO_JOIN_PORT``          -- TCP port to bind (default ``5180``).
* ``BARDPRO_JOIN_BIND``          -- bind host (default ``0.0.0.0`` so the
                                    tailnet/LAN can reach it).

Python stdlib only (http.server) -- no new dependencies, native on every arch.

Run::

    BARDPRO_REGISTRY_BASE=http://edwards-macbook-pro:8081 \
    BARDPRO_MANAGER_JWT_FILE=/tmp/bardpro-fabric/manager.jwt \
        python3 scripts/join_server.py
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

LOG = logging.getLogger("join_server")

# --- Config (config-over-hardcoding; defaults let it run with no setup) ------
DEFAULT_REGISTRY_BASE = "http://edwards-macbook-pro:8081"
DEFAULT_WORKGROUP = "home"
DEFAULT_PORT = 5180
DEFAULT_BIND = "0.0.0.0"
# Portable default for the JWT file: <tempdir>/bardpro-fabric/manager.jwt --
# never a hardcoded "/tmp" (CLAUDE.md cross-platform rule).
DEFAULT_JWT_FILE = str(Path(tempfile.gettempdir()) / "bardpro-fabric" / "manager.jwt")

_HTTP_TIMEOUT_S = 15.0
_SLUG_MAX_LEN = 48


class Config:
    """Process configuration, read once from the environment at startup.

    Validated eagerly (fail fast, CLAUDE.md §11): an unreadable JWT file is a
    startup crash, not a per-request surprise.
    """

    def __init__(self) -> None:
        self.registry_base = os.environ.get("BARDPRO_REGISTRY_BASE", DEFAULT_REGISTRY_BASE).rstrip(
            "/"
        )
        self.jwt_file = Path(os.environ.get("BARDPRO_MANAGER_JWT_FILE", DEFAULT_JWT_FILE))
        self.workgroup = os.environ.get("BARDPRO_JOIN_WORKGROUP", DEFAULT_WORKGROUP)
        self.port = int(os.environ.get("BARDPRO_JOIN_PORT", str(DEFAULT_PORT)))
        self.bind = os.environ.get("BARDPRO_JOIN_BIND", DEFAULT_BIND)

    def validate(self) -> None:
        if not self.jwt_file.is_file():
            raise SystemExit(
                f"manager JWT file not found: {self.jwt_file} (set BARDPRO_MANAGER_JWT_FILE)"
            )
        # Read once to confirm it is non-empty; we re-read per request so a
        # rotated token is picked up without a restart.
        if not self.jwt_file.read_text(encoding="utf-8").strip():
            raise SystemExit(f"manager JWT file is empty: {self.jwt_file}")

    def read_jwt(self) -> str:
        """Read the manager JWT fresh (picks up rotation without restart)."""
        return self.jwt_file.read_text(encoding="utf-8").strip()


def slugify(label: str, fallback: str = "device") -> str:
    """Derive a stable, URL/identifier-safe deviceId from a human label.

    Lowercases, replaces runs of non-alphanumerics with a single hyphen, and
    trims. Empty result falls back to ``fallback``.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", label.strip().lower()).strip("-")
    slug = slug[:_SLUG_MAX_LEN].strip("-")
    return slug or fallback


# --- HTML rendering (inline; no template engine, no static assets) -----------
def _page(title: str, body: str) -> bytes:
    """Wrap body in a minimal, mobile-first HTML document.

    Large touch targets, system font, single column -- built for mobile
    Safari with no external CSS/JS (works offline of any CDN).
    """
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{title}</title>
<style>
  :root {{ color-scheme: light dark; }}
  * {{ box-sizing: border-box; }}
  body {{
    font: 17px/1.5 -apple-system, system-ui, sans-serif;
    margin: 0; padding: 24px;
    max-width: 480px; margin-inline: auto;
    background: #0b0c10; color: #f5f6f8;
  }}
  h1 {{ font-size: 1.6rem; margin: 0 0 0.25em; }}
  p.sub {{ color: #9aa3ad; margin-top: 0; }}
  label {{ display: block; font-weight: 600; margin: 1.4em 0 0.5em; }}
  input[type=text] {{
    width: 100%; padding: 16px; font-size: 1.1rem;
    border: 1px solid #2a2e36; border-radius: 12px;
    background: #15171c; color: #f5f6f8;
  }}
  button {{
    width: 100%; padding: 18px; margin-top: 1.6em;
    font-size: 1.2rem; font-weight: 700;
    border: 0; border-radius: 14px;
    background: #3b82f6; color: #fff;
    -webkit-tap-highlight-color: transparent;
  }}
  button:active {{ background: #2563eb; }}
  .ok {{ color: #4ade80; font-size: 3rem; line-height: 1; margin-bottom: 0.2em; }}
  .err {{ color: #f87171; }}
  .card {{
    background: #15171c; border: 1px solid #2a2e36;
    border-radius: 16px; padding: 20px; margin-top: 1.4em;
  }}
  code {{ background: #15171c; padding: 2px 6px; border-radius: 6px; }}
</style>
</head>
<body>
{body}
</body>
</html>"""
    return html.encode("utf-8")


def _join_form(token: str) -> bytes:
    safe_token = json.dumps(token)  # safely embed in the JS string literal
    body = f"""
<h1>Join the Bard fabric</h1>
<p class="sub">Name this device, then tap Join. It will be added to your
home group automatically.</p>
<form id="f" onsubmit="return false;">
  <label for="label">Device name</label>
  <input type="text" id="label" name="label" value="iPhone"
         autocomplete="off" autocapitalize="words">
  <button id="go" type="submit">Join</button>
</form>
<p id="msg"></p>
<script>
const token = {safe_token};
const go = document.getElementById('go');
const msg = document.getElementById('msg');
document.getElementById('f').addEventListener('submit', async () => {{
  const label = document.getElementById('label').value.trim() || 'iPhone';
  go.disabled = true; go.textContent = 'Joining\\u2026'; msg.textContent = '';
  try {{
    const r = await fetch('/join/redeem', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ token, label }})
    }});
    const data = await r.json();
    if (r.ok && data.ok) {{
      document.open();
      document.write(data.html);
      document.close();
    }} else {{
      go.disabled = false; go.textContent = 'Join';
      msg.className = 'err';
      msg.textContent = data.message || 'Could not join. Please ask for a new link.';
    }}
  }} catch (e) {{
    go.disabled = false; go.textContent = 'Join';
    msg.className = 'err';
    msg.textContent = 'Network error. Are you on the tailnet?';
  }}
}});
</script>
"""
    return _page("Join the Bard fabric", body)


def _success_html(label: str, device_id: str, workgroup: str) -> str:
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Connected</title>
<style>
  body {{ font: 17px/1.5 -apple-system, system-ui, sans-serif;
    margin:0; padding:24px; max-width:480px; margin-inline:auto;
    background:#0b0c10; color:#f5f6f8; text-align:center; }}
  .ok {{ color:#4ade80; font-size:3.4rem; }}
  h1 {{ font-size:1.6rem; }}
  .card {{ background:#15171c; border:1px solid #2a2e36; border-radius:16px;
    padding:20px; margin-top:1.4em; text-align:left; }}
  .sub {{ color:#9aa3ad; }}
</style></head><body>
<div class="ok">&#10004;</div>
<h1>You&rsquo;re connected as {label}</h1>
<p class="sub">This device joined the Bard fabric and was added to the
<b>{workgroup}</b> group. You can close this page.</p>
<div class="card">
  <div class="sub">Device id</div>
  <div><b>{device_id}</b></div>
</div>
</body></html>"""


def _error_page(message: str) -> bytes:
    body = f"""
<h1 class="err">Couldn&rsquo;t join</h1>
<div class="card"><p>{message}</p></div>
<p class="sub">Ask whoever sent the link for a fresh one &mdash; each link
works only once.</p>
"""
    return _page("Couldn't join", body)


# --- Registry client (server-side, so no browser CORS) -----------------------
class RegistryError(Exception):
    """A Registry call failed; ``message`` is safe to show the user."""

    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _registry_post(url: str, payload: dict, bearer: str | None) -> dict:
    """POST JSON to the Registry and return the parsed JSON response.

    Raises RegistryError with a user-friendly message on any failure. We map
    the Registry's 401/404/409 redeem errors to a plain-language explanation
    (expired / used / unknown invite) rather than leaking status codes.
    """
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        status = exc.code
        try:
            detail = json.loads(exc.read().decode("utf-8"))
        except (ValueError, OSError):
            detail = {}
        LOG.warning("registry POST %s -> %s %s", url, status, detail)
        if status in (401, 404):
            raise RegistryError(
                "This invite link has already been used, has expired, or is "
                "not valid. Please ask for a new link.",
                status=400,
            ) from exc
        if status == 409:
            raise RegistryError(
                "This device name is already taken on the fabric. Try a different name.",
                status=409,
            ) from exc
        raise RegistryError(
            "The fabric registry rejected the request. Please try again.",
            status=502,
        ) from exc
    except urllib.error.URLError as exc:
        LOG.warning("registry POST %s unreachable: %s", url, exc)
        raise RegistryError(
            "Couldn't reach the fabric registry. Check you're on the tailnet.",
            status=502,
        ) from exc


class JoinService:
    """Orchestrates redeem-then-assign-workgroup against the Registry."""

    def __init__(self, config: Config) -> None:
        self._config = config

    def join(self, token: str, label: str, device_id: str | None) -> dict:
        """Redeem the invite and place the device in the configured workgroup.

        Returns a dict with the success HTML. Raises RegistryError on failure.
        The one-time deviceSecret is read from the redeem response but
        deliberately discarded -- never returned, never stored.
        """
        label = (label or "iPhone").strip() or "iPhone"
        device_id = (device_id or "").strip() or slugify(label, fallback="iphone")

        base = self._config.registry_base
        redeem = _registry_post(
            f"{base}/invites/{token}/redeem",
            {"deviceId": device_id, "label": label},
            bearer=None,
        )
        # The active device id the Registry recorded (authoritative).
        record = redeem.get("device") or {}
        active_id = record.get("deviceId") or device_id
        # deviceSecret is present here; we intentionally do not read or keep it.

        # Place the new device in the home workgroup (manager-authed).
        _registry_post(
            f"{base}/devices/{active_id}/workgroup",
            {"name": self._config.workgroup},
            bearer=self._config.read_jwt(),
        )
        LOG.info("device %r joined and assigned to workgroup %r", active_id, self._config.workgroup)
        return {
            "ok": True,
            "html": _success_html(label, active_id, self._config.workgroup),
        }


# --- HTTP handler ------------------------------------------------------------
class JoinHandler(BaseHTTPRequestHandler):
    server_version = "BardJoin/1.0"

    # Injected by the server factory below.
    service: JoinService

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status: int, body: bytes) -> None:
        self._send(status, body, "text/html; charset=utf-8")

    def _send_json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload).encode("utf-8"), "application/json")

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003 - stdlib hook name
        LOG.info("%s - %s", self.address_string(), fmt % args)

    def do_GET(self) -> None:  # noqa: N802 - stdlib hook name
        parts = urlsplit(self.path)
        if parts.path == "/join":
            params = parse_qs(parts.query)
            token = (params.get("invite") or [""])[0].strip()
            if not token:
                self._send_html(400, _error_page("This link is missing its invite code."))
                return
            self._send_html(200, _join_form(token))
            return
        if parts.path in ("/healthz", "/health"):
            self._send_json(200, {"status": "ok"})
            return
        self._send_html(404, _error_page("Page not found."))

    def do_POST(self) -> None:  # noqa: N802 - stdlib hook name
        parts = urlsplit(self.path)
        if parts.path != "/join/redeem":
            self._send_json(404, {"ok": False, "message": "Not found."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            self._send_json(400, {"ok": False, "message": "Malformed request."})
            return
        token = str(payload.get("token", "")).strip()
        if not token:
            self._send_json(400, {"ok": False, "message": "Missing invite code."})
            return
        label = str(payload.get("label", "")).strip()
        device_id = str(payload.get("deviceId", "")).strip()
        try:
            result = self.service.join(token, label, device_id)
        except RegistryError as exc:
            self._send_json(exc.status, {"ok": False, "message": exc.message})
            return
        self._send_json(200, result)


def build_server(config: Config) -> ThreadingHTTPServer:
    """Construct the HTTP server with the JoinService bound to the handler."""
    service = JoinService(config)

    class _Handler(JoinHandler):
        pass

    _Handler.service = service
    return ThreadingHTTPServer((config.bind, config.port), _Handler)


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("BARDPRO_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config = Config()
    config.validate()  # fail fast on missing/empty JWT
    httpd = build_server(config)
    LOG.info(
        "join server listening on http://%s:%s -> registry %s (workgroup %r)",
        config.bind,
        config.port,
        config.registry_base,
        config.workgroup,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        LOG.info("shutting down")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
