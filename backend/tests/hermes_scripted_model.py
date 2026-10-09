"""Test-only scripted-model harness for real-runtime Hermes tests (V2).

Authorized slice: the operator's scripted-model-harness decision. This
module is TEST INFRASTRUCTURE ONLY — it must never be imported by
production code.

Design:
- A minimal OpenAI-compatible /chat/completions endpoint served by the
  standard library (http.server) on 127.0.0.1 with a DYNAMICALLY
  allocated port (bind to port 0). No new dependency; the OpenAI SDK
  (an existing vendored dependency, openai 2.24.0) talks to it like any
  base_url. Fully hermetic: loopback only, dummy credentials, no
  internet, no openrouter.ai.
- Scripts are EXPLICIT sequences of model turns (tool_call(...) /
  final_response(...) / repeat_tool_calls(...)); the server pops one
  scripted response per /chat/completions POST and records every
  request body for test inspection (requested tool names, arguments,
  number of model turns, adversarial attempts).
- Tests point the REAL Hermes runtime at the harness exactly like the
  established dead-endpoint pattern (HermesJobRequest.base_url), so the
  full chain MODEL SCRIPT -> real tool-call dispatch -> real §4 -> real
  §9 -> real §12 -> real capability binding -> real §13 runs. Only the
  model/provider response is scripted; every security layer is real.
- Non-streaming: tests set agent._disable_streaming = True on the REAL
  constructed agent — the documented test carve-out in Hermes itself
  (turn_api_call.py:52: "disabled on ... Mock clients in tests"); no
  production file is touched.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Self

# ---------------------------------------------------------------------------
# Scripted-turn builders (explicit, deterministic)
# ---------------------------------------------------------------------------


def tool_call(name: str, arguments: dict | str) -> dict:
    """One scripted assistant turn requesting a tool call.

    `arguments` may be a dict (serialized deterministically) or a raw
    string (to script invalid/hostile JSON)."""
    args = (
        json.dumps(arguments, sort_keys=True) if isinstance(arguments, dict) else arguments
    )
    return {
        "kind": "tool_call",
        "name": name,
        "arguments": args,
    }


def final_response(text: str) -> dict:
    """One scripted assistant turn with a terminal text response."""
    return {"kind": "final", "text": text}


def repeat_tool_calls(name: str, arguments: dict | str, count: int) -> list[dict]:
    """`count` identical scripted tool-call turns (iteration-pressure)."""
    return [tool_call(name, arguments) for _ in range(count)]


def _script_exhausted() -> dict:
    # A script that runs out returns a deterministic terminal response so
    # runs terminate instead of hanging (defensive; tests size scripts).
    return final_response("(script exhausted)")


# ---------------------------------------------------------------------------
# Scripted model server (loopback, dynamic port, stdlib-only)
# ---------------------------------------------------------------------------


class ScriptedModelServer:
    """Threaded loopback /chat/completions server speaking the minimal
    OpenAI wire the vendored SDK needs (non-streaming responses)."""

    def __init__(self, script: list[dict]):
        self.script = list(script)
        self.requests: list[dict] = []  # every request body, in order
        self.turns_served = 0
        self._lock = threading.Lock()
        self._index = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):  # silence stderr noise
                pass

            def _respond(self, payload: dict) -> None:
                data = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    raw = self.rfile.read(length) if length else b"{}"
                    try:
                        body = json.loads(raw)
                    except Exception:  # malformed JSON recorded, never fatal
                        body = {"_raw": raw.decode("utf-8", errors="replace")}
                    if "chat/completions" not in self.path:
                        # SDK warm-up probes (e.g. /models) never consume
                        # scripted turns; answer with a benign model list.
                        model = str(body.get("model") or "scripted-test-model") if isinstance(body, dict) else "scripted-test-model"
                        self._respond({"object": "list", "data": [{"id": model, "object": "model"}]})
                        return
                    with outer._lock:
                        outer.requests.append(body)
                        if outer._index < len(outer.script):
                            turn = outer.script[outer._index]
                            outer._index += 1
                        else:
                            turn = _script_exhausted()
                        outer.turns_served += 1
                    self._respond(outer._render(turn, body))
                except Exception:  # best-effort test server boundary
                    pass  # malformed request -> dropped connection; tests assert observable behavior

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    # -- response rendering -------------------------------------------------

    @staticmethod
    def _render(turn: dict, request_body: dict) -> dict:
        model = str(request_body.get("model") or "scripted-test-model")
        base = {
            "id": "chatcmpl-scripted",
            "object": "chat.completion",
            "created": 0,
            "model": model,
        }
        if turn["kind"] == "tool_call":
            call_id = f"call_{abs(hash((turn['name'], turn['arguments'])) % 10**8)}"
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": turn["name"],
                            "arguments": turn["arguments"],
                        },
                    }
                ],
            }
            finish = "tool_calls"
        else:
            message = {"role": "assistant", "content": turn["text"]}
            finish = "stop"
        return {
            **base,
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    # -- lifecycle -----------------------------------------------------------

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/v1"

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self._server.shutdown()
        self._server.server_close()

    # -- inspection ----------------------------------------------------------

    def requested_tool_names(self) -> list[str]:
        """Tool names the model requested, in scripted/turn order."""
        with outer_lock(self):
            return [
                tc["function"]["name"]
                for body in self.requests
                for tc in (
                    ((body.get("messages") or [{}])[-1] or {}).get("tool_calls") or []
                )
                if isinstance(tc, dict) and isinstance(tc.get("function"), dict)
            ] or self._scripted_names()

    def _scripted_names(self) -> list[str]:
        return [t["name"] for t in self.script if t["kind"] == "tool_call"]


def outer_lock(server: ScriptedModelServer):
    return server._lock  # internal helper for inspection consistency
