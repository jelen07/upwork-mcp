"""Security helpers: URL allowlist and write-action gating.

Two concerns this module addresses:

1. Indirect prompt injection. Tool inputs that look like URLs (job_url,
   proposal_url, room_id, contract_url) flow through ``page.goto()`` in an
   authenticated browser. Without validation, an attacker who can influence
   the LLM's tool inputs (e.g. by planting instructions in a job description)
   can navigate the authenticated session to arbitrary origins. Every URL
   parameter must therefore pass through ``validate_upwork_url``.

2. Connects-spending and message-sending actions are unsafe by default. They
   are gated behind ``UPWORK_MCP_ALLOW_WRITES=true`` so a fresh install cannot
   submit proposals or send messages until the user explicitly opts in.
"""

import os
from urllib.parse import urlparse

ALLOWED_HOSTS = ("upwork.com",)


class WriteActionDisabledError(RuntimeError):
    """Raised when a write tool is invoked without UPWORK_MCP_ALLOW_WRITES=true."""


class UrlNotAllowedError(ValueError):
    """Raised when a URL parameter does not point to an allowed host."""


def validate_upwork_url(url: str, allow_path_id: bool = False) -> str:
    """Return a normalised https://www.upwork.com/... URL or raise.

    Args:
        url: Either an absolute URL (must be https on an upwork.com host) or,
            if ``allow_path_id`` is true, a bare ID/path that will be appended
            to ``https://www.upwork.com/``.
        allow_path_id: When true, non-URL strings (e.g. a room ID like
            ``"abc123"``) are accepted and resolved against the Upwork base.
            The string still cannot contain a scheme or an authority.

    Raises:
        UrlNotAllowedError: If the URL is malformed, uses a non-https scheme,
            or points outside the upwork.com domain.
    """
    if not isinstance(url, str) or not url:
        raise UrlNotAllowedError("URL must be a non-empty string.")

    if allow_path_id and "://" not in url and not url.startswith("//"):
        # Treat as an opaque ID/path. Strip leading slashes to avoid escaping
        # the base, and reject anything that looks like an authority.
        if url.startswith("/"):
            url = url.lstrip("/")
        if "@" in url or url.startswith(".."):
            raise UrlNotAllowedError("Path identifier contains disallowed characters.")
        url = f"https://www.upwork.com/{url}"

    parsed = urlparse(url)

    if parsed.scheme != "https":
        raise UrlNotAllowedError(
            f"Only https URLs are allowed (got scheme '{parsed.scheme}')."
        )

    host = (parsed.hostname or "").lower()
    if not host:
        raise UrlNotAllowedError("URL has no host.")

    if host != "upwork.com" and not any(host.endswith(f".{h}") for h in ALLOWED_HOSTS):
        raise UrlNotAllowedError(
            f"URL host '{host}' is not on the upwork.com allowlist."
        )

    return parsed.geturl()


def writes_enabled() -> bool:
    """Return true when UPWORK_MCP_ALLOW_WRITES is set to a truthy value."""

    return os.getenv("UPWORK_MCP_ALLOW_WRITES", "").lower() in ("1", "true", "yes")


def require_writes_enabled(action: str) -> None:
    """Raise unless write actions are explicitly enabled.

    Tools that send messages, submit proposals, or withdraw proposals call
    this before performing the action. The default-off posture protects
    against prompt-injection-driven misuse and accidental Connects spend.
    """

    if not writes_enabled():
        raise WriteActionDisabledError(
            f"Write action '{action}' is disabled. Set environment variable "
            "UPWORK_MCP_ALLOW_WRITES=true to enable. This action can spend "
            "Connects or send messages on your behalf; only enable it if you "
            "understand the prompt-injection risk from scraped Upwork content."
        )
