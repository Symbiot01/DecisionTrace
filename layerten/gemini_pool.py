"""
Shared Gemini client with concurrency + RPS rate limiting.

Used by agentic extraction (parallel) and optional API callers.
Never logs API keys.
"""
from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any, Optional

from google import genai
from google.genai import types

from layerten import config

logger = logging.getLogger(__name__)

_client: Optional[genai.Client] = None
_client_lock = threading.Lock()
_sem: Optional[threading.Semaphore] = None
_rate_lock = threading.Lock()
_tokens: float = 0.0
_last_refill: float = 0.0


def get_client() -> genai.Client:
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is None:
            if not config.GEMINI_API_KEY:
                raise RuntimeError("GEMINI_API_KEY is not set")
            # Without an explicit timeout a stalled response blocks its worker
            # thread forever, which deadlocked a whole agentic batch.
            _client = genai.Client(
                api_key=config.GEMINI_API_KEY,
                http_options=types.HttpOptions(
                    timeout=int(config.GEMINI_REQUEST_TIMEOUT_S * 1000)
                ),
            )
        return _client


def _get_sem() -> threading.Semaphore:
    global _sem
    if _sem is None:
        _sem = threading.Semaphore(max(1, int(config.GEMINI_MAX_CONCURRENCY)))
    return _sem


def reset_limits(*, concurrency: Optional[int] = None, rps: Optional[float] = None) -> None:
    global _sem, _tokens, _last_refill
    if concurrency is not None:
        config.GEMINI_MAX_CONCURRENCY = max(1, int(concurrency))
    if rps is not None:
        config.GEMINI_RPS = max(0.1, float(rps))
    _sem = threading.Semaphore(max(1, int(config.GEMINI_MAX_CONCURRENCY)))
    _tokens = 0.0
    _last_refill = 0.0


def acquire_rate_slot() -> None:
    """Block until a rate-limit token is available (token bucket)."""
    global _tokens, _last_refill
    rps = max(0.1, float(config.GEMINI_RPS))
    capacity = rps
    while True:
        with _rate_lock:
            now = time.monotonic()
            if _last_refill == 0.0:
                _last_refill = now
                _tokens = capacity
            elapsed = now - _last_refill
            _tokens = min(capacity, _tokens + elapsed * rps)
            _last_refill = now
            if _tokens >= 1.0:
                _tokens -= 1.0
                return
            wait = (1.0 - _tokens) / rps
        time.sleep(wait)


def generate_content_limited(**kwargs: Any) -> Any:
    """
    Thread-safe Gemini generate_content with concurrency + RPS caps and retries.
    kwargs passed to client.models.generate_content (model, contents, config, ...).
    """
    client = get_client()
    max_retries = max(0, int(config.GEMINI_MAX_RETRIES))
    last_exc: Optional[BaseException] = None

    for attempt in range(max_retries + 1):
        acquire_rate_slot()
        _get_sem().acquire()
        try:
            return client.models.generate_content(**kwargs)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            msg = str(exc).lower()
            retryable = (
                "429" in msg
                or "resource_exhausted" in msg
                or "rate" in msg
                or "timeout" in msg
                or "503" in msg
                or "500" in msg
            )
            if not retryable or attempt >= max_retries:
                break
            backoff = min(60.0, (2**attempt) + random.uniform(0, 0.5))
            logger.warning(
                "gemini retry %s/%s after %s (wait %.1fs)",
                attempt + 1,
                max_retries,
                type(exc).__name__,
                backoff,
            )
            time.sleep(backoff)
        finally:
            _get_sem().release()

    assert last_exc is not None
    raise last_exc
