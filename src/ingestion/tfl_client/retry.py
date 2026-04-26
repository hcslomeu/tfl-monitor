"""Hand-rolled retry helper for the TfL HTTP client.

Kept intentionally small (~30 lines of logic) to avoid pulling in a
dedicated retry dependency for a single consumer (CLAUDE.md §1, rule 4).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import httpx

RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

# RFC 9110 §10.2.3 / §15.5.4: ``Retry-After`` MAY accompany ``429``
# (rate limit) and ``503`` (Service Unavailable). We honour both;
# other 5xx responses use exponential backoff.
_RETRY_AFTER_STATUS_CODES: frozenset[int] = frozenset({429, 503})

_BASE_BACKOFF_SECONDS = 0.5
_MAX_BACKOFF_SECONDS = 10.0


class TflClientError(RuntimeError):
    """Raised when the TfL client cannot complete a request."""


def _exponential_backoff(attempt: int) -> float:
    """Return the exponential backoff delay (seconds) for a given attempt index."""
    delay: float = _BASE_BACKOFF_SECONDS * (2**attempt)
    return min(delay, _MAX_BACKOFF_SECONDS)


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Parse a ``Retry-After`` header as positive integer seconds.

    Returns ``None`` when the header is missing, malformed, or expressed
    in the HTTP-date form (RFC 9110 allows both forms; we fall back to
    exponential backoff in that case rather than raising).
    """
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        seconds = int(raw.strip())
    except (TypeError, ValueError):
        return None
    return float(seconds) if seconds > 0 else None


async def with_retry(
    call: Callable[[], Awaitable[httpx.Response]],
    *,
    max_attempts: int,
) -> httpx.Response:
    """Invoke ``call`` with bounded retry on transient TfL failures.

    Retries on ``httpx.TimeoutException``, ``httpx.TransportError``, and
    HTTP responses whose status code is in :data:`RETRYABLE_STATUS_CODES`.
    Honours ``Retry-After`` for 429 and 503 responses (the codes in
    :data:`_RETRY_AFTER_STATUS_CODES`) when the header is a positive
    integer; otherwise — and for the other 5xx codes — applies
    exponential backoff capped at 10 seconds.

    Args:
        call: Coroutine factory returning a fresh ``httpx.Response``.
        max_attempts: Total attempts including the first call (>= 1).

    Returns:
        The first ``httpx.Response`` whose status code is not retryable.

    Raises:
        TflClientError: If every attempt fails.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    last_exception: Exception | None = None
    last_response: httpx.Response | None = None

    for attempt in range(max_attempts):
        try:
            response = await call()
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exception = exc
            last_response = None
            if attempt == max_attempts - 1:
                break
            await asyncio.sleep(_exponential_backoff(attempt))
            continue

        if response.status_code not in RETRYABLE_STATUS_CODES:
            return response

        last_exception = None
        last_response = response
        if attempt == max_attempts - 1:
            break

        delay = (
            _retry_after_seconds(response)
            if response.status_code in _RETRY_AFTER_STATUS_CODES
            else None
        )
        if delay is None:
            delay = _exponential_backoff(attempt)
        await asyncio.sleep(delay)

    if last_response is not None:
        raise TflClientError(
            f"TfL request failed after {max_attempts} attempts: HTTP {last_response.status_code}"
        )
    raise TflClientError(f"TfL request failed after {max_attempts} attempts: {last_exception!r}")
