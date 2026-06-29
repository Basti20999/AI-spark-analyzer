"""Resolve a spark report from a code, URL, or local file into JSON.

The official JSON endpoint decodes spark's protobuf for us:

    https://spark.lucko.me/<code>?raw=1&full=true

``raw=1`` returns metadata as JSON; ``full=true`` adds the full thread tree.
We use the stdlib so the package has no fetch-time dependencies, and
``urllib`` honours ``HTTP(S)_PROXY`` from the environment automatically.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

VIEWER_BASE = "https://spark.lucko.me"
USER_AGENT = "ai-spark-analyzer/0.1 (+https://spark.lucko.me/docs)"

# spark codes are short URL-safe tokens, e.g. "uksGhFmkWd".
_CODE_RE = re.compile(r"^[A-Za-z0-9]{6,}$")


class FetchError(RuntimeError):
    """Raised when a report cannot be loaded."""


def extract_code(target: str) -> str | None:
    """Pull the spark code out of a full viewer/bytebin URL or a bare code."""
    target = target.strip()
    if target.startswith("http://") or target.startswith("https://"):
        # Last non-empty path segment, minus any query string.
        path = target.split("?", 1)[0].rstrip("/")
        segment = path.rsplit("/", 1)[-1]
        return segment or None
    if _CODE_RE.match(target):
        return target
    return None


def _load_local(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise FetchError(
            f"{path} is not valid JSON. Export the report with "
            f"'?raw=1&full=true' (raw .sparkprofile protobuf is not supported)."
        ) from exc
    except OSError as exc:
        raise FetchError(f"could not read {path}: {exc}") from exc
    return data


def _fetch_url(url: str, timeout: float) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        raise FetchError(f"server returned HTTP {exc.code} for {url}") from exc
    except urllib.error.URLError as exc:
        raise FetchError(f"could not reach {url}: {exc.reason}") from exc
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise FetchError(f"response from {url} was not JSON") from exc


def fetch(target: str, *, timeout: float = 30.0) -> dict:
    """Load a spark report from a local file, a viewer URL, or a bare code."""
    if os.path.exists(target):
        return _load_local(target)

    code = extract_code(target)
    if not code:
        raise FetchError(
            f"'{target}' is not a file, a spark code, or a spark URL. "
            f"Pass a code like 'uksGhFmkWd', a URL like "
            f"'{VIEWER_BASE}/uksGhFmkWd', or a local .json export."
        )

    url = f"{VIEWER_BASE}/{code}?raw=1&full=true"
    return _fetch_url(url, timeout)
