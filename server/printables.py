"""Printables.com: search models, read their license and file list, download a model file.

Printables gives this data without an account, through the GraphQL API its own website uses.
The other model sites do not: MakerWorld asks to log in before a download and Thingiverse
blocks automated requests, so for them the customer gets links only.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

API = "https://api.printables.com/graphql/"
MEDIA = "https://media.printables.com/"
USER_AGENT = "print-quote/0.1"
TIMEOUT = 20
MODEL_EXT = {"stl", "3mf", "obj"}

# Licenses that allow selling prints without asking the author.
COMMERCIAL_OK = {"CC0", "CC-BY", "CC-BY-SA", "GNU-GPL", "GNU-LGPL"}

MODEL_URL_RE = re.compile(r"https?://(?:www\.)?printables\.com/(?:[a-z]{2}/)?model/(\d+)", re.I)

_FIELDS = ("id name slug summary tags { name } category { path { name } } "
           "license { abbreviation name } image { filePath } stls { id name fileSize }")
# Used only to judge how well a model fits a request; not sent to the page.
PRIVATE_KEYS = ("summary", "tags", "category")
_SEARCH = "query($q: String!, $n: Int!){ searchPrints2(query: $q, limit: $n){ items { %s } } }" % _FIELDS
_MODEL = "query($id: ID!){ print(id: $id){ %s } }" % _FIELDS
_LINK = ("mutation($id: ID!, $printId: ID!){ getDownloadLink(id: $id, printId: $printId, fileType: stl, "
         "source: model_detail){ ok errors { messages } output { link } } }")

_cache: dict[str, tuple[float, dict | None]] = {}
_cache_lock = threading.Lock()
CACHE_TTL = 600


class PrintablesError(Exception):
    """Printables did not answer or answered with an error."""


def _post(query: str, variables: dict) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(API, data=body, headers={
        "Content-Type": "application/json", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise PrintablesError(f"request failed: {e}") from e
    if data.get("errors"):
        raise PrintablesError(str(data["errors"])[:300])
    return data.get("data") or {}


def _thumb(file_path: str | None) -> str | None:
    """320x240 preview of a model photo (Printables keeps thumbs next to the original)."""
    if not file_path:
        return None
    folder, _, name = file_path.rpartition("/")
    stem, dot, ext = name.rpartition(".")
    if not dot:
        return MEDIA + file_path
    return f"{MEDIA}{folder}/thumbs/inside/320x240/{ext.lower()}/{stem}.webp"


def _shape(item: dict) -> dict:
    lic = item.get("license") or {}
    abbr = lic.get("abbreviation") or ""
    files = []
    for f in item.get("stls") or []:
        name = f.get("name") or ""
        if name.rsplit(".", 1)[-1].lower() in MODEL_EXT:
            files.append({"id": str(f["id"]), "name": name, "size": int(f.get("fileSize") or 0)})
    slug = item.get("slug") or ""
    return {
        "source": "Printables",
        "id": str(item["id"]),
        "name": item.get("name") or "",
        "url": f"https://www.printables.com/model/{item['id']}" + (f"-{slug}" if slug else ""),
        "license": abbr or "без ліцензії",
        "license_ok": abbr in COMMERCIAL_OK,
        "image": _thumb((item.get("image") or {}).get("filePath")),
        "files": files,
        "summary": (item.get("summary") or "")[:400],
        "tags": [t["name"] for t in item.get("tags") or [] if t and t.get("name")],
        "category": [p["name"] for p in ((item.get("category") or {}).get("path") or []) if p and p.get("name")],
    }


def public(m: dict) -> dict:
    """A model without the fields used only for ranking."""
    return {k: v for k, v in m.items() if k not in PRIVATE_KEYS}


def search(query: str, limit: int = 6) -> list[dict]:
    """Models matching the query that have at least one STL, 3MF or OBJ file."""
    data = _post(_SEARCH, {"q": query[:200], "n": min(limit + 4, 30)})
    items = ((data.get("searchPrints2") or {}).get("items")) or []
    models = [_shape(i) for i in items if i]
    found = [m for m in models if m["files"]][:limit]
    with _cache_lock:
        for m in found:
            _cache[m["id"]] = (time.time(), m)
    return found


def model(model_id: str) -> dict | None:
    """One model by its number from the URL; None if it does not exist."""
    model_id = str(model_id)
    if not model_id.isdigit():
        return None
    with _cache_lock:
        hit = _cache.get(model_id)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    item = _post(_MODEL, {"id": model_id}).get("print")
    m = _shape(item) if item else None
    with _cache_lock:
        _cache[model_id] = (time.time(), m)
    return m


def model_ids_in(text: str) -> list[str]:
    """Printables model numbers from links in the text, in order, without repeats."""
    seen = []
    for mid in MODEL_URL_RE.findall(text or ""):
        if mid not in seen:
            seen.append(mid)
    return seen


def download(model_id: str, file_id: str, max_bytes: int) -> bytes:
    """Bytes of one model file. Only Printables' own file hosts are contacted."""
    out = _post(_LINK, {"id": str(file_id), "printId": str(model_id)}).get("getDownloadLink") or {}
    link = ((out.get("output") or {}).get("link")) or ""
    host = urlparse(link).hostname or ""
    if not out.get("ok") or urlparse(link).scheme != "https" or not (
            host == "printables.com" or host.endswith(".printables.com")):
        raise PrintablesError(f"no download link: {out.get('errors')}")
    req = urllib.request.Request(link, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read(max_bytes + 1)
    except (urllib.error.URLError, OSError) as e:
        raise PrintablesError(f"download failed: {e}") from e
    if len(body) > max_bytes:
        raise PrintablesError("file too large")
    return body
