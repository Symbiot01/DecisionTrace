import logging
import threading
import time

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BACKOFF_BASE = 2
MAX_RETRIES = 5
RATE_LIMIT_BUFFER = 100
RESET_PADDING_SECONDS = 5

_rate_lock = threading.Lock()


def check_rate_limit(response: httpx.Response) -> None:
    """Sleep if we're close to exhausting the rate limit (thread-safe)."""
    remaining = response.headers.get("X-RateLimit-Remaining")
    reset_at = response.headers.get("X-RateLimit-Reset")

    if remaining is None or reset_at is None:
        return

    remaining_i = int(remaining)
    reset_at_i = int(reset_at)

    if remaining_i >= RATE_LIMIT_BUFFER:
        return

    with _rate_lock:
        # Re-check under lock so concurrent workers don't all sleep/stack
        now = int(time.time())
        sleep_seconds = max(reset_at_i - now, 1) + RESET_PADDING_SECONDS
        logger.warning(
            "Rate limit low (%d remaining). Sleeping %ds until reset.",
            remaining_i,
            sleep_seconds,
        )
        time.sleep(sleep_seconds)


def handle_rate_limit_error(response: httpx.Response, attempt: int) -> None:
    """Handle 403/429 rate limit responses with exponential backoff (thread-safe)."""
    reset_at = response.headers.get("X-RateLimit-Reset")
    retry_after = response.headers.get("Retry-After")

    if retry_after:
        sleep_seconds = int(retry_after) + RESET_PADDING_SECONDS
    elif reset_at:
        sleep_seconds = max(int(reset_at) - int(time.time()), 1) + RESET_PADDING_SECONDS
    else:
        sleep_seconds = DEFAULT_BACKOFF_BASE ** attempt

    with _rate_lock:
        logger.warning(
            "Rate limited (HTTP %d, attempt %d). Sleeping %ds.",
            response.status_code,
            attempt + 1,
            sleep_seconds,
        )
        time.sleep(sleep_seconds)


def is_rate_limited(response: httpx.Response) -> bool:
    if response.status_code == 429:
        return True
    if response.status_code == 403 and "rate limit" in response.text.lower():
        return True
    return False
