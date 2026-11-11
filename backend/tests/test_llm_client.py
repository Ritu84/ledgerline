import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from ledgerline.llm.openai_compat import OpenAICompatClient


class _Trickle(BaseHTTPRequestHandler):
    """A provider that answers 200 and then sends one byte a second, forever."""

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        try:
            while True:
                self.wfile.write(b" ")
                self.wfile.flush()
                time.sleep(0.2)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *args):
        pass


class _Busy(_Trickle):
    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        self.send_response(503)
        self.send_header("Content-Length", "0")
        self.end_headers()


class _Silent(_Trickle):
    """Accepts the connection and never answers (like a connect that hangs)."""

    def do_POST(self):
        time.sleep(30)


@pytest.mark.parametrize("handler", [_Trickle, _Busy, _Silent])
def test_a_slow_or_busy_provider_cannot_hold_a_call_past_the_deadline(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    client = OpenAICompatClient(f"http://127.0.0.1:{server.server_port}", "k", "m", timeout=30, deadline=1.5)
    started = time.monotonic()
    with pytest.raises(httpx.HTTPError):
        client.complete("system", "prompt")
    assert time.monotonic() - started < 4
    server.shutdown()
    server.server_close()


class _Gemini(_Trickle):
    """Answers like Gemini's OpenAI-compatible endpoint: gzip-compressed JSON, thinking tokens in total_tokens."""

    def do_POST(self):
        import gzip
        import json

        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert request["messages"][0]["role"] == "system"
        body = gzip.compress(json.dumps({
            "choices": [{"message": {"content": '```json\n{"total": "1,000.00"}\n```'}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 200},
        }).encode())
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_a_normal_compressed_reply_is_read_correctly():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Gemini)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    client = OpenAICompatClient(f"http://127.0.0.1:{server.server_port}", "k", "gemini-x")
    reply = client.complete("system", "prompt")
    assert reply.text == '```json\n{"total": "1,000.00"}\n```'
    assert (reply.input_tokens, reply.output_tokens, reply.model) == (120, 80, "gemini-x")
    assert reply.latency_ms < 5000
    server.shutdown()
    server.server_close()
