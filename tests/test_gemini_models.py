"""Guardrail: every configured Gemini model must still exist.

A deprecated model returns 404 only at call time, and each caller falls back to
a degraded path (regex question parsing, skipped extraction). That failure mode
is invisible in aggregate metrics, so it is asserted explicitly here.

Requires GEMINI_API_KEY and network access; skipped otherwise.
"""

from __future__ import annotations

import pytest

from layerten import config

pytestmark = pytest.mark.skipif(
    not config.GEMINI_API_KEY, reason="GEMINI_API_KEY not configured"
)

CONFIGURED_MODELS = [
    ("GEMINI_MODEL", config.GEMINI_MODEL),
    ("GEMINI_MODEL_EXTRACTION", config.GEMINI_MODEL_EXTRACTION),
    ("GEMINI_MODEL_RAG", config.GEMINI_MODEL_RAG),
    ("GEMINI_MODEL_PARSER", config.GEMINI_MODEL_PARSER),
]


@pytest.fixture(scope="module")
def available_models() -> set[str]:
    from google import genai

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    names = set()
    for model in client.models.list():
        if "generateContent" in (model.supported_actions or []):
            names.add(model.name.removeprefix("models/"))
    return names


@pytest.mark.parametrize("setting,model", CONFIGURED_MODELS, ids=lambda v: str(v))
def test_configured_model_is_available(setting, model, available_models):
    assert model, f"{setting} is empty"
    assert model in available_models, (
        f"{setting}={model!r} is not available for generateContent. "
        f"Update it to a supported model."
    )


def test_startup_probe_reports_all_models_ok():
    """The API's boot-time probe is what surfaces this in production."""
    from layerten.api.main import check_gemini_models

    results = check_gemini_models()
    assert results, "probe returned no results despite an API key being set"
    failed = [label for label, ok in results.items() if not ok]
    assert not failed, f"startup probe reported unavailable models: {failed}"
