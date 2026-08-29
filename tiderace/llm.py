"""Pluggable extraction backends.

Ollama is the default, and that keeps the whole project dependency-free: the
Ollama backend is plain `urllib` against a local HTTP server, so `pip install`
is never required to use any part of tiderace. The Anthropic backend stays
available for anyone who would rather spend money than VRAM.

One hard-won detail drives the design of every prompt in `extract.py`:

    **Ollama's structured output constrains grammar, not meaning.** The JSON
    schema you pass in `format` is compiled to a grammar so the output always
    parses and enums are always respected -- but the `description` fields never
    reach the model. Semantic guidance placed there is silently ignored.

Measured on a bait-abundance task with the scale defined in the schema
description versus in the prompt body:

    qwen2.5:7b    schema 1/4   prompt 4/4
    qwen3.6:27b   schema 1/4   prompt 4/4

Both sizes went from useless to perfect on the same model and the same schema.
So every backend here takes semantic guidance as *prompt text*, and schemas
carry structure only. That also happens to be portable: it works on Anthropic
too, which does read descriptions.

Model size, measured rather than assumed
----------------------------------------
Once the prompt was fixed, most of the task stopped depending on size. What
still does is one semantic distinction that matters a great deal here:
telling forage present in the water apart from bait an angler is fishing with.
"A good scup bite on squid" describes tackle; recording it as a squid sighting
would tell the forecast there is forage in an area when there is none.

    qwen2.5:7b     2/3   (~1s per call)   misses forage-vs-tackle
    qwen3.6:27b    3/3   (~7s per call)

So the default is the 27B. It is 17.8 GB at Q4 and a weekly scrape takes
seconds, which is a poor reason to accept a wrong answer. Drop to a 7B with
`--llm-model` if the GPU is busy; the abundance scale survives the downgrade,
the tackle distinction does not.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

DEFAULT_OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_OLLAMA_MODEL = "qwen3.6:27b"
DEFAULT_ANTHROPIC_MODEL = "claude-opus-5"


class BackendUnavailable(RuntimeError):
    pass


class Backend:
    name = "none"

    def complete(self, system: str, user: str, schema: dict) -> dict:
        raise NotImplementedError

    def describe(self) -> str:
        return self.name


# ------------------------------------------------------------------- ollama

class Ollama(Backend):
    name = "ollama"

    def __init__(self, model: str = DEFAULT_OLLAMA_MODEL,
                 host: str = DEFAULT_OLLAMA_HOST, timeout: float = 600):
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout

    def describe(self) -> str:
        return f"ollama/{self.model}"

    def available(self) -> bool:
        try:
            self.models()
            return True
        except BackendUnavailable:
            return False

    def models(self) -> list[dict]:
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=10) as r:
                return json.loads(r.read()).get("models", [])
        except Exception as e:                                    # noqa: BLE001
            raise BackendUnavailable(
                f"no Ollama at {self.host} ({type(e).__name__}). "
                "Start it with `ollama serve`.") from e

    def complete(self, system: str, user: str, schema: dict) -> dict:
        body = {
            "model": self.model,
            # Guidance lives in the prompt, never in schema descriptions --
            # see the module docstring.
            "prompt": f"{system}\n\n{user}",
            "format": schema,
            "stream": False,
            "options": {"temperature": 0, "num_ctx": 16384},
        }
        # Qwen3-family models think by default, which triples latency for a
        # task that is pure extraction.
        if self.model.startswith(("qwen3", "qwen3.6")):
            body["think"] = False

        req = urllib.request.Request(
            f"{self.host}/api/generate",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                payload = json.loads(r.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:200]
            raise BackendUnavailable(f"ollama {e.code}: {detail}") from e
        except Exception as e:                                    # noqa: BLE001
            raise BackendUnavailable(
                f"ollama request failed ({type(e).__name__}): {e}") from e

        text = payload.get("response", "")
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise BackendUnavailable(
                f"model returned non-JSON despite the schema: {text[:200]}") from e


# ---------------------------------------------------------------- anthropic

class Anthropic(Backend):
    name = "anthropic"

    def __init__(self, model: str = DEFAULT_ANTHROPIC_MODEL):
        self.model = model

    def describe(self) -> str:
        return f"anthropic/{self.model}"

    def complete(self, system: str, user: str, schema: dict) -> dict:
        try:
            import anthropic
        except ImportError as e:
            raise BackendUnavailable(
                "the anthropic backend needs `pip install anthropic`; "
                "the ollama backend needs nothing") from e
        try:
            client = anthropic.Anthropic()
        except Exception as e:                                    # noqa: BLE001
            raise BackendUnavailable(f"no Anthropic credentials: {e}") from e

        with client.messages.stream(
            model=self.model,
            max_tokens=16000,
            system=system,
            thinking={"type": "adaptive"},
            output_config={"format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": user}],
        ) as stream:
            msg = stream.get_final_message()

        if msg.stop_reason == "refusal":
            raise BackendUnavailable(
                f"model declined: {getattr(msg.stop_details, 'category', 'unknown')}")
        text = "".join(b.text for b in msg.content if b.type == "text")
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise BackendUnavailable(f"non-JSON response: {text[:200]}") from e


# ------------------------------------------------------------------ factory

def get_backend(cfg: dict | None = None) -> Backend:
    from . import config as cfgmod
    cfg = cfg or cfgmod.load()
    kind = cfg.get("llm_backend", "ollama")

    if kind == "anthropic":
        return Anthropic(cfg.get("llm_model") or DEFAULT_ANTHROPIC_MODEL)
    if kind == "none":
        raise BackendUnavailable(
            "extraction is disabled — set one with: "
            "python3 -m tiderace config --llm ollama")
    return Ollama(cfg.get("llm_model") or DEFAULT_OLLAMA_MODEL,
                  cfg.get("ollama_host") or DEFAULT_OLLAMA_HOST)


def probe(cfg: dict | None = None) -> dict:
    """What is actually usable on this machine right now."""
    from . import config as cfgmod
    cfg = cfg or cfgmod.load()
    out = {"configured": cfg.get("llm_backend", "ollama"),
           "model": cfg.get("llm_model") or DEFAULT_OLLAMA_MODEL}

    o = Ollama(out["model"], cfg.get("ollama_host") or DEFAULT_OLLAMA_HOST)
    try:
        models = o.models()
        out["ollama"] = True
        out["ollama_models"] = sorted(
            ({"name": m["name"], "gb": round(m.get("size", 0) / 1e9, 1)}
             for m in models), key=lambda m: m["gb"])
        out["model_present"] = any(m["name"] == out["model"] for m in models)
    except BackendUnavailable as e:
        out["ollama"] = False
        out["ollama_error"] = str(e)

    try:
        import anthropic  # noqa: F401
        out["anthropic_sdk"] = True
    except ImportError:
        out["anthropic_sdk"] = False
    out["anthropic_key"] = bool(os.environ.get("ANTHROPIC_API_KEY"))
    return out
