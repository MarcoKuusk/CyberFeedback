import os
import re

from openai import OpenAI


DEFAULT_OPENAI_MODEL = "gpt-5.5"
DEFAULT_OPENAI_REASONING_EFFORT = "medium"

# A whole team can be answering at once, and report generation is synchronous.
# Without a deadline one stalled upstream call holds a worker thread until the
# SDK's own (very long) default expires, which in a room of 30 people reads as
# "the tool is broken" rather than "one request was slow".
DEFAULT_TIMEOUT_SECONDS = 120.0
# The SDK retries connection errors, 408/409/429 and 5xx with exponential
# backoff. Three attempts absorbs a rate-limit blip without letting a genuinely
# failing call sit for six minutes.
DEFAULT_MAX_RETRIES = 3


def _positive_float(name: str, fallback: float) -> float:
    """Environment overrides must never make the deadline weaker by accident:
    an unparseable or non-positive value falls back to the default."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return fallback
    try:
        value = float(raw)
    except ValueError:
        return fallback
    return value if value > 0 else fallback


def request_timeout() -> float:
    return _positive_float("OPENAI_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)


def max_retries() -> int:
    return int(_positive_float("OPENAI_MAX_RETRIES", DEFAULT_MAX_RETRIES))


def load_api_key() -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY environment variable. Set it before generating reports.")
    return api_key


def current_model() -> str:
    return os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL).strip() or DEFAULT_OPENAI_MODEL


def _supports_reasoning(model: str) -> bool:
    return model.startswith("gpt-5") or re.match(r"^o\d", model) is not None


def generate_report_text(api_key: str, prompt: str) -> str:
    model = current_model()
    client = OpenAI(api_key=api_key, timeout=request_timeout(), max_retries=max_retries())
    request_args = {
        "model": model,
        "instructions": "You create concise, executive-ready cybersecurity reports grounded only in the supplied assessment data.",
        "input": prompt,
    }

    if _supports_reasoning(model):
        request_args["reasoning"] = {"effort": os.getenv("OPENAI_REASONING_EFFORT", DEFAULT_OPENAI_REASONING_EFFORT)}

    response = client.responses.create(**request_args)
    return response.output_text
