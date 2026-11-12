"""Language-model backends: the built-in offline model (llama.cpp) and an optional
OpenAI-compatible cloud API (Gemini, OpenAI, Groq, a local llama-server, ...)."""

from __future__ import annotations

import json
import re
import threading
from typing import Callable

TokenCallback = Callable[[str], None]

LOCAL_CONTEXT = 10240  # tokens: an 8-page document plus the conversation


class Cancelled(Exception):
    pass


_THINK_RE = re.compile(r"<think>.*?(</think>|$)", re.S)


def strip_thinking(text: str) -> str:
    """Remove <think> sections that reasoning models (e.g. Qwen3) may emit."""
    return _THINK_RE.sub("", text).lstrip()


class Backend:
    name = "backend"
    context_tokens = 8192

    def count_tokens(self, text: str) -> int:
        return int(len(text.split()) * 1.4) + 1

    def generate(
        self,
        messages: list[dict],
        max_tokens: int = 700,
        temperature: float = 0.3,
        on_token: TokenCallback | None = None,
        cancel: threading.Event | None = None,
        json_schema: dict | None = None,
        seed: int | None = None,
    ) -> str:
        raise NotImplementedError

    def close(self) -> None:
        pass


class LocalBackend(Backend):
    """Runs a GGUF model inside the app with llama-cpp-python. No internet needed."""

    def __init__(self, model_path: str, threads: int = 0, n_ctx: int = LOCAL_CONTEXT):
        from llama_cpp import Llama

        from .models import physical_cores

        self.model_path = model_path
        self.name = model_path.replace("\\", "/").rsplit("/", 1)[-1].replace(".gguf", "")
        self.llm = Llama(
            model_path=model_path,
            n_ctx=n_ctx,
            n_threads=threads or physical_cores(),
            n_batch=512,
            verbose=False,
        )
        self.context_tokens = n_ctx
        self._lock = threading.Lock()

    def count_tokens(self, text: str) -> int:
        return len(self.llm.tokenize(text.encode("utf-8"), add_bos=False, special=True))

    def generate(self, messages, max_tokens=700, temperature=0.3, on_token=None, cancel=None, json_schema=None,
                 seed=None):
        kwargs = dict(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=0.9,
            repeat_penalty=1.08,
            stream=True,
        )
        if json_schema is not None:
            kwargs["response_format"] = {"type": "json_object", "schema": json_schema}
        if seed is not None:
            kwargs["seed"] = seed
        out: list[str] = []
        with self._lock:
            stream = self.llm.create_chat_completion(**kwargs)
            try:
                for chunk in stream:
                    if cancel is not None and cancel.is_set():
                        raise Cancelled()
                    delta = chunk["choices"][0].get("delta", {}).get("content") or ""
                    if delta:
                        out.append(delta)
                        if on_token:
                            on_token(delta)
            finally:
                close = getattr(stream, "close", None)
                if close:
                    close()
        return strip_thinking("".join(out))

    def close(self) -> None:
        try:
            self.llm.close()
        except Exception:
            pass


class CloudBackend(Backend):
    """Any OpenAI-compatible chat-completions API. The student brings their own key."""

    def __init__(self, base_url: str, model: str, api_key: str):
        if not api_key:
            raise ValueError("Add your API key in Settings to use the cloud option.")
        self.base_url = base_url.rstrip("/") + "/"
        self.model = model
        self.api_key = api_key
        self.name = f"Cloud · {model}"
        self.context_tokens = 32000

    def generate(self, messages, max_tokens=700, temperature=0.3, on_token=None, cancel=None, json_schema=None,
                 seed=None):
        import requests

        body = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if json_schema is not None:
            body["response_format"] = {"type": "json_object"}
            messages = list(messages)
            messages[-1] = dict(messages[-1])
            messages[-1]["content"] += "\n\nReturn JSON matching this schema:\n" + json.dumps(json_schema)
            body["messages"] = messages
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        out: list[str] = []
        try:
            r = requests.post(self.base_url + "chat/completions", json=body, headers=headers, stream=True, timeout=120)
        except requests.RequestException as e:
            raise ConnectionError("Could not reach the cloud service. Check your internet connection.") from e
        with r:
            if r.status_code >= 400:
                detail = r.text[:300]
                if r.status_code in (401, 403):
                    raise PermissionError(f"The cloud service rejected the API key ({r.status_code}).")
                if r.status_code == 429:
                    raise ConnectionError("The cloud service's rate limit was reached. Wait a minute and retry.")
                raise ConnectionError(f"Cloud service error {r.status_code}: {detail}")
            for line in r.iter_lines(decode_unicode=True):
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    delta = json.loads(data)["choices"][0].get("delta", {}).get("content") or ""
                except (ValueError, KeyError, IndexError):
                    continue
                if delta:
                    out.append(delta)
                    if on_token:
                        on_token(delta)
        return strip_thinking("".join(out))
