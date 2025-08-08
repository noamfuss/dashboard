import os
import re
import threading
from typing import List, Optional

import requests
from queue import Queue

# Directory to cache icons
ICONS_DIR = os.path.join(os.path.dirname(__file__), "icons")
_LOCK = threading.Lock()

# Remote icon repository base (raw content)
REPO_BASE = "https://raw.githubusercontent.com/homarr-labs/dashboard-icons/main"
# Folders and matching extensions in the repo
ICON_SOURCES = [
    ("svg", "svg"),
    ("png", "png"),
    ("webp", "webp"),
]

# Placeholder filename (created on demand)
PLACEHOLDER_NAME = "placeholder.svg"

# Async fetch queue and state
_FETCH_QUEUE: "Queue[dict]" = Queue()
_PENDING_KEYS = set()
_PENDING_LOCK = threading.Lock()


def get_icons_dir() -> str:
    """Return the absolute path to the local icons cache directory and ensure it exists."""
    os.makedirs(ICONS_DIR, exist_ok=True)
    return ICONS_DIR


def _ensure_placeholder() -> str:
    """Ensure a placeholder SVG exists and return its filename."""
    get_icons_dir()
    placeholder_path = os.path.join(ICONS_DIR, PLACEHOLDER_NAME)
    if not os.path.exists(placeholder_path):
        # Simple neutral placeholder SVG (48x48)
        svg = (
            """
            <svg xmlns=\"http://www.w3.org/2000/svg\" width=\"96\" height=\"96\" viewBox=\"0 0 96 96\" role=\"img\" aria-label=\"Placeholder icon\">
              <defs>
                <linearGradient id=\"g\" x1=\"0\" x2=\"1\" y1=\"0\" y2=\"1\">
                  <stop offset=\"0%\" stop-color=\"#d1d5db\"/>
                  <stop offset=\"100%\" stop-color=\"#9ca3af\"/>
                </linearGradient>
              </defs>
              <rect x=\"8\" y=\"8\" width=\"80\" height=\"80\" rx=\"16\" fill=\"url(#g)\"/>
              <path d=\"M48 26a22 22 0 1 0 0 44 22 22 0 0 0 0-44zm0 8a14 14 0 1 1 0 28 14 14 0 0 1 0-28z\" fill=\"#374151\" fill-opacity=\"0.35\"/>
              <path d=\"M44 38h8v8h-8zM44 50h8v8h-8z\" fill=\"#374151\" fill-opacity=\"0.5\"/>
            </svg>
            """
        ).strip()
        with open(placeholder_path, "w", encoding="utf-8") as f:
            f.write(svg)
    return PLACEHOLDER_NAME


def _slugify(name: str) -> str:
    """Create a filesystem and URL friendly base name for icon lookup."""
    name = name.strip().lower()
    # Remove common provider suffixes
    name = re.sub(r"@.*$", "", name)
    # Replace separators with hyphen
    name = re.sub(r"[\s_]+", "-", name)
    # Drop anything not alphanumeric or hyphen
    name = re.sub(r"[^a-z0-9-]", "", name)
    # Collapse multiple hyphens
    name = re.sub(r"-+", "-", name).strip("-")
    return name


def _extract_hosts_from_rule(rule: str) -> List[str]:
    """Extract hostnames from a Traefik rule like Host(`a.example.com`,`b.example.com`)."""
    if not rule:
        return []
    hosts = []
    # Match Host(`...`) possibly multiple times
    for host_group in re.findall(r"Host\s*\(([^)]*)\)", rule):
        for h in re.findall(r"`([^`]+)`", host_group):
            hosts.append(h)
    return hosts


def _candidate_names(instance: dict) -> List[str]:
    """Build a list of candidate names to look up icons by."""
    cands: List[str] = []
    service = (instance.get("service") or "").strip()
    name = (instance.get("name") or "").strip()
    rule = (instance.get("rule") or "").strip()

    # From service (strip provider suffix)
    if service:
        base = re.sub(r"@.*$", "", service)
        cands.append(base)
        # Often services are like 'app-service', try first chunk
        cands.append(base.split("-")[0])

    # From router name
    if name:
        cands.append(name)
        cands.append(name.split("-")[0])

    # From rule hosts
    for host in _extract_hosts_from_rule(rule):
        cands.append(host)
        # Left-most label (subdomain)
        left = host.split(".")[0]
        if left and left != host:
            cands.append(left)
        # Drop common www
        if left == "www" and len(host.split(".")) > 1:
            cands.append(host.split(".")[1])

    # Slugify and de-duplicate while preserving order
    seen = set()
    out: List[str] = []
    for cand in cands:
        s = _slugify(cand)
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _cached_icon_filename(basename: str) -> Optional[str]:
    """Return cached icon filename if already downloaded for a given basename."""
    d = get_icons_dir()
    for ext in ("svg", "png", "webp"):
        fn = f"{basename}.{ext}"
        if os.path.exists(os.path.join(d, fn)):
            return fn
    return None


def _download_icon(basename: str) -> Optional[str]:
    """Try to download icon for basename from repo in the preferred order, cache it, and return filename."""
    # Try repo folders in this order: svg, png, webp
    for folder, ext in ICON_SOURCES:
        url = f"{REPO_BASE}/{folder}/{basename}.{ext}"
        try:
            resp = requests.get(url, timeout=6)
            if resp.status_code == 200 and resp.content:
                # Cache it
                with _LOCK:
                    d = get_icons_dir()
                    target = os.path.join(d, f"{basename}.{ext}")
                    # Write binary for all formats (SVG included to keep encoding)
                    with open(target, "wb") as f:
                        f.write(resp.content)
                return os.path.basename(target)
        except requests.RequestException:
            # Ignore and try next
            continue
    return None


def get_icon_filename_for_instance(instance: dict) -> str:
    """Return local cached filename for the instance icon, downloading if needed.

    Falls back to a placeholder if nothing is found.
    """
    # Try candidates
    for cand in _candidate_names(instance):
        cached = _cached_icon_filename(cand)
        if cached:
            return cached
        downloaded = _download_icon(cand)
        if downloaded:
            return downloaded
    # Fallback placeholder
    return _ensure_placeholder()


def _job_key(instance: dict) -> str:
    """Unique-ish key for a fetch job to avoid duplicates."""
    cands = _candidate_names(instance)
    return "|".join(cands) or (instance.get("service") or instance.get("name") or "?")


def _enqueue_fetch(instance: dict) -> None:
    """Enqueue an async fetch for this instance if not already queued."""
    key = _job_key(instance)
    with _PENDING_LOCK:
        if key in _PENDING_KEYS:
            return
        _PENDING_KEYS.add(key)
        _FETCH_QUEUE.put((key, instance))


def _icon_worker() -> None:
    """Background worker that resolves and downloads icons for queued instances."""
    while True:
        key, inst = _FETCH_QUEUE.get()
        try:
            # This will download and cache if needed
            get_icon_filename_for_instance(inst)
        except Exception:
            # Swallow to keep worker alive
            pass
        finally:
            with _PENDING_LOCK:
                _PENDING_KEYS.discard(key)
            _FETCH_QUEUE.task_done()


# Start a single daemon worker
_worker_thread = threading.Thread(target=_icon_worker, daemon=True)
_worker_thread.start()


def get_icon_url_for_instance(instance: dict) -> str:
    """Return a fast icon URL.

    - If a cached icon exists for any candidate, return it.
    - Otherwise, enqueue an async fetch and return the placeholder immediately.
    """
    # Fast path: return first cached candidate if any
    for cand in _candidate_names(instance):
        cached = _cached_icon_filename(cand)
        if cached:
            return f"/icons/{cached}"

    # Not cached yet: enqueue async fetch and return placeholder
    _enqueue_fetch(instance)
    return f"/icons/{_ensure_placeholder()}"
