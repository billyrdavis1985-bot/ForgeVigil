"""Local stand-in for Meta's OpenAI-compatible chat completions endpoint.

Serves scripted replies over real HTTP on 127.0.0.1 and records every request,
so the live adapter runs end to end with no key, no network and no spend.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def completion(
    message: dict, prompt_tokens: int | None = 1000, completion_tokens: int = 100, finish_reason: str = "stop"
) -> dict:
    response = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
    }
    if prompt_tokens is not None:
        response["usage"] = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
    return response


def answer(
    threat_finding: str = "none",
    reason_code: str = "NO_THREAT_INDICATORS",
    evidence_refs=("request:message",),
    quotes=(),
    prompt_tokens: int = 1000,
    completion_tokens: int = 100,
) -> dict:
    content = json.dumps(
        {
            "threat_finding": threat_finding,
            "reason_code": reason_code,
            "evidence_refs": list(evidence_refs),
            "quotes": list(quotes),
        }
    )
    return completion({"role": "assistant", "content": content}, prompt_tokens, completion_tokens)


def tool_calls(*calls, prompt_tokens: int = 800, completion_tokens: int = 40) -> dict:
    """Each call is (name, arguments); dict arguments are JSON-encoded, strings are sent as-is."""
    message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": f"call_{index}",
                "type": "function",
                "function": {"name": name, "arguments": args if isinstance(args, str) else json.dumps(args)},
            }
            for index, (name, args) in enumerate(calls, 1)
        ],
    }
    return completion(message, prompt_tokens, completion_tokens)


class Reply:
    def __init__(self, payload=None, *, status: int = 200, raw: bytes | None = None, delay: float = 0.0,
                 headers: dict | None = None) -> None:
        self.payload = payload
        self.status = status
        self.raw = raw
        self.delay = delay
        self.headers = headers or {}


class FakeMuseAPI:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self._script: list[Reply] = []
        self._lock = threading.Lock()
        api = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                return self._handle()

            def do_GET(self):
                return self._handle()

            def _handle(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                with api._lock:
                    api.requests.append(
                        {
                            "method": self.command,
                            "path": self.path,
                            "headers": {name.lower(): value for name, value in self.headers.items()},
                            "body": json.loads(body) if body else None,
                        }
                    )
                    reply = api._script.pop(0) if api._script else Reply({"error": "no scripted reply"}, status=500)
                if reply.delay:
                    time.sleep(reply.delay)
                data = reply.raw if reply.raw is not None else json.dumps(reply.payload).encode()
                try:
                    self.send_response(reply.status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    for name, value in reply.headers.items():
                        self.send_header(name, value)
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    pass  # the client already gave up (timeout tests)

            def log_message(self, *args):
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}/v1"

    def script(self, *replies) -> None:
        with self._lock:
            self._script.extend(reply if isinstance(reply, Reply) else Reply(reply) for reply in replies)

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
