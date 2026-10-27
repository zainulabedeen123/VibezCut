"""FilmCraft connection: one client, two transports.

* ``Headless`` - spawns ``filmcraft-cli mcp [--project p]`` and talks MCP over stdio.
  Used to build a project file while FilmCraft is closed (or has another project open).
* ``Live`` - connects straight to the running app's JSON-lines control channel
  (``filmcraft --control PORT`` with ``FILMCRAFT_CONTROL_TOKEN``). Every edit lands in the
  user's open window as a normal, undoable FilmCraft step.

Both expose the same surface: ``run(cmd, params)``, ``batch(steps)``, ``sequence()``,
``project()``, ``render_frame(seconds, path)``.
"""
from __future__ import annotations

import base64
import itertools
import json
import os
import socket
import subprocess
from pathlib import Path

from . import config

TICKS = 254_016_000_000  # FilmCraft ticks per second


class FilmCraftError(RuntimeError):
    pass


def ticks(seconds: float, fps: int = 60) -> int:
    """seconds -> ticks, snapped to the frame grid (exact integer math)."""
    per_frame = TICKS // fps
    return int(round(seconds * fps)) * per_frame


def seconds(t: int) -> float:
    return t / TICKS


# ----------------------------------------------------------------------------- headless
class Headless:
    """In-process engine session via ``filmcraft-cli mcp`` (stdio MCP)."""

    def __init__(self, project: str | None = None):
        args = [str(config.cli()), "mcp"]
        if project:
            args[1:1] = ["--project", str(project)]
        self._p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
        self._ids = itertools.count(1)
        self._rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                 "clientInfo": {"name": "filmcraft-studio", "version": "1"}})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    mode = "headless"

    def _send(self, obj):
        if self._p.stdin is None:
            raise FilmCraftError("filmcraft-cli is not running")
        self._p.stdin.write(json.dumps(obj) + "\n")
        self._p.stdin.flush()

    def _rpc(self, method, params):
        i = next(self._ids)
        self._send({"jsonrpc": "2.0", "id": i, "method": method, "params": params})
        while True:
            line = self._p.stdout.readline() if self._p.stdout else ""
            if not line:
                raise FilmCraftError("filmcraft-cli closed the connection")
            msg = json.loads(line)
            if msg.get("id") == i:
                if "error" in msg:
                    raise FilmCraftError(msg["error"].get("message", str(msg["error"])))
                return msg["result"]

    def _tool(self, name, args):
        res = self._rpc("tools/call", {"name": name, "arguments": args})
        content = res.get("content", [])
        if res.get("isError"):
            text = content[0].get("text", "") if content else ""
            raise FilmCraftError(text or f"{name} failed")
        return content

    @staticmethod
    def _json(content):
        text = content[0].get("text", "") if content else ""
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text

    def run(self, cmd, params=None):
        return self._json(self._tool("command_run", {"id": cmd, "params": params}))

    def batch(self, steps, stop_on_error=True):
        return self._json(self._tool("command_batch", {"steps": steps, "stop_on_error": stop_on_error}))

    def sequence(self):
        return self._json(self._tool("sequence_inspect", {}))

    def project(self):
        return self._json(self._tool("project_inspect", {}))

    def render_frame(self, secs, path, max_side=960):
        content = self._tool("render_frame", {"seconds": secs, "max_side": max_side})
        for c in content:
            if c.get("type") == "image":
                Path(path).write_bytes(base64.b64decode(c["data"]))
                return str(path)
        raise FilmCraftError("no image returned")

    def close(self):
        try:
            if self._p.stdin:
                self._p.stdin.close()
            self._p.wait(timeout=10)
        except Exception:
            self._p.kill()


# ----------------------------------------------------------------------------- live
class Live:
    """The running FilmCraft window, over its token-protected control channel."""

    mode = "live"

    def __init__(self, port: int | None = None, token: str | None = None):
        self.port = port or config.control_port()
        self.token = token or config.control_token()
        if not self.token:
            raise FilmCraftError("No control token. Start FilmCraft with 'Start FilmCraft (Claude control).bat'.")
        self._ids = itertools.count(1)
        self._sock = None
        self._buf = b""

    def _connect(self):
        s = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        s.settimeout(180)
        self._sock, self._buf = s, b""

    def _call(self, method, params=None):
        for attempt in (1, 2):  # the server closes idle / errored connections: reconnect once
            try:
                if self._sock is None:
                    self._connect()
                i = next(self._ids)
                req = {"id": i, "token": self.token, "method": method}
                if params is not None:
                    req["params"] = params
                self._sock.sendall((json.dumps(req) + "\n").encode())
                while b"\n" not in self._buf:
                    chunk = self._sock.recv(1 << 20)
                    if not chunk:
                        raise ConnectionError("closed")
                    self._buf += chunk
                line, self._buf = self._buf.split(b"\n", 1)
                reply = json.loads(line)
                if not reply.get("ok", False):
                    raise FilmCraftError(reply.get("error", "control request failed"))
                return reply.get("result")
            except (ConnectionError, OSError):
                self._sock = None
                if attempt == 2:
                    raise FilmCraftError(f"Cannot reach FilmCraft on 127.0.0.1:{self.port}. Is it running with control on?")

    def run(self, cmd, params=None):
        return self._call("engine.execute", {"command": cmd, "params": params or {}})

    def batch(self, steps, stop_on_error=True):
        out = []
        for s in steps:
            try:
                out.append(self.run(s["id"], s.get("params")))
            except FilmCraftError as e:
                out.append({"error": str(e)})
                if stop_on_error:
                    break
        return {"results": out}

    def sequence(self):
        return self.run("sequence.inspect", {})

    def project(self):
        return self.run("project.inspect", {})

    def render_frame(self, secs, path, max_side=960):
        """Screenshot of the Program monitor at ``secs`` (moves the playhead there)."""
        self.run("playhead.set", {"seconds": secs})
        try:
            self._call("ui.screenshot", {"path": str(Path(path).resolve()), "panel": "Program"})
        except FilmCraftError:
            # window minimized / display asleep: screenshots time out. Render the same state
            # headless from a temporary copy (the user's project file is not touched).
            import tempfile
            cp = Path(tempfile.gettempdir()) / "fc_live_copy.fcproj"
            self.run("file.saveCopy", {"path": str(cp)})
            h = Headless(str(cp))
            try:
                h.render_frame(secs, path, max_side)
            finally:
                h.close()
        return str(path)

    def close(self):
        if self._sock:
            self._sock.close()
            self._sock = None


def connect(prefer: str = "auto", project: str | None = None):
    """``live`` if the app is reachable (auto), else a headless session on ``project``."""
    if prefer in ("auto", "live"):
        try:
            lv = Live()
            lv._call("ui.inspect")
            return lv
        except FilmCraftError:
            if prefer == "live":
                raise
    return Headless(project)
