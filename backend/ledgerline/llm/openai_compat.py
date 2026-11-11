"""Client for any OpenAI-compatible /chat/completions endpoint.

Works with OpenAI, Gemini's OpenAI-compatible endpoint, Groq, OpenRouter, vLLM and local
Ollama (OPENAI_BASE_URL=http://localhost:11434/v1, no key needed).
"""
from __future__ import annotations

import threading
import time

import httpx

from .base import LLMResponse

RETRY_STATUSES = {429, 503}
RETRIES = 3
RETRY_WAIT_SECONDS = 10
DEADLINE_SECONDS = 60.0  # the whole call, retries included; httpx's timeout only limits each wait between bytes


class DeadlineExceeded(httpx.TimeoutException):
    """The provider kept the call open past the deadline (slow trickle, or busy replies we kept retrying)."""


class OpenAICompatClient:
    def __init__(self, base_url: str, api_key: str | None, model: str, timeout: float = 30.0,
                 deadline: float = DEADLINE_SECONDS):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.deadline = deadline

    def _post(self, url: str, headers: dict, payload: dict, deadline_at: float) -> httpx.Response:
        """One request that gives up at deadline_at, wherever it is stuck.

        httpx's timeouts apply per step and per address: a host with eight unreachable IPv6 addresses
        costs eight connect timeouts, a DNS lookup has no timeout at all, and a server trickling bytes
        never times out. So the request runs in a worker thread and we stop waiting for it at the deadline.
        """
        remaining = deadline_at - time.monotonic()
        if remaining <= 0:
            raise DeadlineExceeded(f"no reply within {self.deadline:.0f} s")
        outcome: dict = {}

        def run():
            try:
                with httpx.Client(timeout=httpx.Timeout(min(self.timeout, remaining), connect=10.0)) as client:
                    with client.stream("POST", url, headers=headers, json=payload) as response:
                        body = b""
                        for chunk in response.iter_bytes():
                            body += chunk
                            if time.monotonic() > deadline_at:
                                raise DeadlineExceeded(f"no complete reply within {self.deadline:.0f} s")
                        # body is already decompressed, so don't pass Content-Encoding on
                        headers_out = {k: v for k, v in response.headers.items()
                                       if k.lower() not in ("content-encoding", "content-length")}
                        outcome["response"] = httpx.Response(response.status_code, headers=headers_out,
                                                             content=body, request=response.request)
            except Exception as exc:  # noqa: BLE001 - handed to the caller below
                outcome["error"] = exc

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(max(0.0, deadline_at - time.monotonic()))
        if worker.is_alive():
            raise DeadlineExceeded(f"no reply within {self.deadline:.0f} s")
        if "error" in outcome:
            raise outcome["error"]
        return outcome["response"]

    def complete(self, system: str, prompt: str, max_tokens: int = 2000) -> LLMResponse:
        started = time.monotonic()
        deadline_at = started + self.deadline
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        }
        for attempt in range(RETRIES + 1):
            response = self._post(f"{self.base_url}/chat/completions", headers, payload, deadline_at)
            wait = RETRY_WAIT_SECONDS * (attempt + 1)
            if (response.status_code not in RETRY_STATUSES or attempt == RETRIES
                    or time.monotonic() + wait >= deadline_at):
                break
            time.sleep(wait)  # rate limit or a busy model: wait and try again, inside the deadline
        response.raise_for_status()
        body = response.json()
        usage = body.get("usage") or {}
        prompt_tokens = usage.get("prompt_tokens", 0)
        # Some providers (Gemini) bill thinking tokens as output but leave them out of completion_tokens.
        output_tokens = max(usage.get("completion_tokens", 0), usage.get("total_tokens", 0) - prompt_tokens)
        return LLMResponse(
            text=body["choices"][0]["message"]["content"] or "",
            model=self.model,
            input_tokens=prompt_tokens,
            output_tokens=output_tokens,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
