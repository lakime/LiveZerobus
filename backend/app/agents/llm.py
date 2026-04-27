"""Thin wrapper around the Databricks Foundation Model (FM) API.

The FM API is served behind the same workspace URL as the app and exposes an
OpenAI-compatible `/serving-endpoints/<endpoint>/invocations` path. We use
the Python `openai` client pointed at that base URL, authenticated with a
short-lived OAuth token minted from the app's service-principal identity.

Env vars:
  DATABRICKS_HOST            — https://<workspace>.azuredatabricks.net
  LLM_MODEL                  — serving-endpoint name
                                (default: databricks-meta-llama-3-3-70b-instruct)
  LLM_TEMPERATURE            — default 0.2 for structured tasks
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx
from databricks.sdk import WorkspaceClient


class LLMError(RuntimeError):
    """Any non-retryable LLM failure."""


_TOKEN_LOCK = threading.Lock()
_TOKEN: tuple[str, float] = ("", 0.0)
_REFRESH_MARGIN_S = 60


def _fresh_token() -> str:
    """Mint a workspace-scoped token via the Databricks SDK.

    The app's SP identity is picked up from env (DATABRICKS_HOST + client
    credentials injected by Databricks Apps at runtime).
    """
    global _TOKEN
    with _TOKEN_LOCK:
        tok, exp = _TOKEN
        if tok and exp - time.time() > _REFRESH_MARGIN_S:
            return tok
        w = WorkspaceClient()
        # `config.authenticate()` returns a dict with "Authorization: Bearer ...".
        auth = w.config.authenticate()
        raw = auth.get("Authorization", "")
        if not raw.startswith("Bearer "):
            raise LLMError("Could not obtain workspace bearer token")
        token = raw.split(" ", 1)[1]
        # The SDK doesn't expose expiry cleanly across auth modes; refresh every 10 min.
        _TOKEN = (token, time.time() + 600)
        return token


@dataclass
class LLMResponse:
    text: str
    prompt_tokens: int
    output_tokens: int
    raw: dict[str, Any]


class FoundationModelClient:
    """Minimal FM API client using the OpenAI-compatible chat endpoint."""

    def __init__(
        self,
        model: str | None = None,
        host: str | None = None,
        temperature: float | None = None,
        timeout_s: float = 30.0,
    ):
        # Resolve workspace host robustly:
        #   1. explicit `host` arg wins
        #   2. then DATABRICKS_HOST env (may be bare hostname inside Apps)
        #   3. fall back to the SDK config (always normalized to https://...)
        raw_host = (host or os.environ.get("DATABRICKS_HOST", "")).strip()
        if not raw_host:
            try:
                raw_host = (WorkspaceClient().config.host or "").strip()
            except Exception as e:                          # pragma: no cover
                raise LLMError(f"Could not determine workspace host: {e}") from e
        if not raw_host:
            raise LLMError("DATABRICKS_HOST not set and SDK could not resolve it")
        # Apps may inject a scheme-less host (e.g. "<ws>.azuredatabricks.net").
        # httpx requires the scheme to be explicit, so prepend https:// if missing.
        if not raw_host.startswith(("http://", "https://")):
            raw_host = f"https://{raw_host}"
        self.host = raw_host.rstrip("/")
        self.model = model or os.environ.get(
            "LLM_MODEL", "databricks-meta-llama-3-3-70b-instruct"
        )
        self.temperature = (
            temperature
            if temperature is not None
            else float(os.environ.get("LLM_TEMPERATURE", "0.2"))
        )
        self.timeout_s = timeout_s

    def _url(self) -> str:
        return f"{self.host}/serving-endpoints/{self.model}/invocations"

    def chat(self, system: str, user: str, *, max_tokens: int = 1024) -> LLMResponse:
        payload = {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "temperature": self.temperature,
            "max_tokens": max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {_fresh_token()}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=self.timeout_s) as c:
                r = c.post(self._url(), json=payload, headers=headers)
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPError as e:
            raise LLMError(f"FM API call failed: {e}") from e

        # Databricks FM API returns the OpenAI chat-completions shape.
        choice = (data.get("choices") or [{}])[0]
        msg = (choice.get("message") or {}).get("content", "")
        usage = data.get("usage") or {}
        return LLMResponse(
            text=msg.strip(),
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
            raw=data,
        )

    def chat_json(
        self, system: str, user: str, *, max_tokens: int = 1024
    ) -> tuple[dict[str, Any], LLMResponse]:
        """Same as `chat` but expects the model to return a single JSON object.

        The system prompt should already instruct JSON-only output, but in
        practice the model often:
          * wraps the response in ```json ... ``` markdown fences
          * embeds literal newlines / tabs inside string values
            (technically invalid JSON, but harmless)
        We strip the fences and parse with `strict=False` to tolerate both.
        """
        resp = self.chat(system, user, max_tokens=max_tokens)
        txt = resp.text.strip()

        # Strip a leading ```json / ``` fence and a trailing ``` fence, if present.
        if txt.startswith("```"):
            # remove leading fence (```json or just ```), then any trailing fence
            first_nl = txt.find("\n")
            if first_nl != -1:
                txt = txt[first_nl + 1:]
            if txt.endswith("```"):
                txt = txt[:-3]
            txt = txt.strip()

        start = txt.find("{")
        end = txt.rfind("}")
        if start < 0 or end < 0 or end < start:
            raise LLMError(f"Expected JSON in model output; got: {txt[:200]}")
        candidate = txt[start:end + 1]
        try:
            # strict=False allows literal control chars (\n, \t) inside strings,
            # which Llama frequently produces in body_md fields.
            return json.loads(candidate, strict=False), resp
        except json.JSONDecodeError as e:
            raise LLMError(
                f"Invalid JSON from model: {e}; text={candidate[:200]}"
            ) from e
