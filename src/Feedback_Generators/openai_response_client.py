import os
import re

from openai import OpenAI


DEFAULT_OPENAI_MODEL = "gpt-5.5"
DEFAULT_OPENAI_REASONING_EFFORT = "medium"


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
    client = OpenAI(api_key=api_key)
    request_args = {
        "model": model,
        "instructions": "You create concise, executive-ready cybersecurity reports grounded only in the supplied assessment data.",
        "input": prompt,
    }

    if _supports_reasoning(model):
        request_args["reasoning"] = {"effort": os.getenv("OPENAI_REASONING_EFFORT", DEFAULT_OPENAI_REASONING_EFFORT)}

    response = client.responses.create(**request_args)
    return response.output_text
