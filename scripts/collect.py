#!/usr/bin/env python3
"""
Nepal flood/landslide news collector.

Fetches RSS feeds from Nepali local sources and Korean sources, filters by
keywords relevant to the Rasuwa / Bhotekoshi flood and Korean / Doosan Enerbility
workers, and writes a normalized data.json for the dashboard front-end.

Uses only the Python standard library so it runs anywhere (local + GitHub Actions)
with no pip install step.
"""

import json
import re
import ssl
import sys
import time
import html
import urllib.request
import urllib.error
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET
from pathlib import Path

# Build an SSL context. Prefer certifi's CA bundle when available (fixes the
# common macOS "unable to get local issuer certificate" problem); otherwise
# fall back to the system default.
try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:  # noqa
    SSL_CTX = ssl.create_default_context()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SOURCES = [
    # --- Nepali local sources ---
    {"name": "The Kathmandu Post", "flag": "\U0001F1F3\U0001F1F5", "country": "NP",
     "url": "https://kathmandupost.com/rss"},
    {"name": "Online Khabar (EN)", "flag": "\U0001F1F3\U0001F1F5", "country": "NP",
     "url": "https://english.onlinekhabar.com/feed"},
    {"name": "The Rising Nepal", "flag": "\U0001F1F3\U0001F1F5", "country": "NP",
     "url": "https://risingnepaldaily.com/rss"},
    {"name": "Nepal News", "flag": "\U0001F1F3\U0001F1F5", "country": "NP",
     "url": "https://nepalnews.com/feed"},

    # --- Korean sources ---
    {"name": "Yonhap (EN)", "flag": "\U0001F1F0\U0001F1F7", "country": "KR",
     "url": "https://en.yna.co.kr/RSS/news.xml"},
    {"name": "Yonhap \uc5f0\ud569\ub274\uc2a4", "flag": "\U0001F1F0\U0001F1F7", "country": "KR",
     "url": "https://www.yna.co.kr/rss/news.xml"},
    {"name": "Korea Herald", "flag": "\U0001F1F0\U0001F1F7", "country": "KR",
     "url": "https://www.koreaherald.com/rss/newsAll.xml"},

    # --- International wire (context) ---
    {"name": "Al Jazeera", "flag": "\U0001F310", "country": "INTL",
     "url": "https://www.aljazeera.com/xml/rss/all.xml"},
]

CORE_KEYWORDS = [
    "rasuwa", "bhotekoshi", "bhote koshi", "bhote-koshi",
    "trishuli", "trisuli", "\ub77c\uc218\uc640", "\ubcf4\ud14c\ucf54\uc2dc", "\ub124\ud314",
    "nepal flood", "nepal flash flood", "nepal landslide", "nepal avalanche",
]
HIGHLIGHT_KEYWORDS = [
    "doosan", "\ub450\uc0b0", "\ub450\uc0b0\uc5d0\ub108\ube4c\ub9ac\ud2f0", "doosan enerbility",
    "korea south-east", "korean", "\ud55c\uad6d\uc778", "south korean",
    "korea southeast power", "\ud55c\uad6d\ub0a8\ub3d9\ubc1c\uc804", "upper trishuli",
]
FLOOD_TERMS = ["flood", "flash flood", "landslide", "avalanche", "\ud64d\uc218", "\uc0b0\uc0ac\ud0dc",
               "rescue", "missing", "\uc2e4\uc885", "\uad6c\uc870"]

OUT_PATH = Path(__file__).resolve().parent.parent / "docs" / "data" / "data.json"
USER_AGENT = "Mozilla/5.0 (compatible; NepalFloodDashboard/1.0; +https://github.com)"
TIMEOUT = 20
MAX_ITEMS = 120


def log(*a):
    print("[collect]", *a, file=sys.stderr)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=SSL_CTX) as resp:
        return resp.read()


def clean_text(s):
    if not s:
        return ""
    s = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", s, flags=re.DOTALL)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def parse_date(s):
    if not s:
        return None
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return None


def _tag(el):
    return el.tag.split("}")[-1] if "}" in el.tag else el.tag


def _extract_feed_xml(raw):
    """Return a clean XML byte string containing just the rss/feed element.

    Handles BOM, leading/trailing junk ("junk after document element"), and
    detects HTML pages returned instead of a feed.
    """
    if isinstance(raw, bytes):
        # strip UTF-8 BOM
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        text = raw.decode("utf-8", errors="replace")
    else:
        text = raw
    text = text.lstrip()

    low = text.lower()
    # If it's an HTML page (feed blocked/misconfigured), bail out.
    if low.startswith("<!doctype html") or low.startswith("<html"):
        raise ValueError("HTML page returned instead of RSS/Atom feed")

    # Slice to the outermost feed element to drop trailing junk.
    for open_tag, close_tag in (("<rss", "</rss>"), ("<feed", "</feed>")):
        start = low.find(open_tag)
        end = low.rfind(close_tag)
        if start != -1 and end != -1:
            end += len(close_tag)
            return text[start:end].encode("utf-8")

    # No wrapper found; return as-is (let the XML parser try).
    return text.encode("utf-8")


def parse_feed(raw):
    items = []
    try:
        xml_bytes = _extract_feed_xml(raw)
    except ValueError as e:
        log("feed skipped:", e)
        return items

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        log("XML parse error:", e)
        return items

    nodes = []
    for el in root.iter():
        if _tag(el) in ("item", "entry"):
            nodes.append(el)

    for node in nodes:
        title = link = summary = pub = ""
        for child in node:
            t = _tag(child)
            if t == "title":
                title = clean_text(child.text or "")
            elif t == "link":
                href = child.get("href")
                link = href if href else (child.text or "")
                link = link.strip()
            elif t in ("description", "summary", "content"):
                if not summary:
                    summary = clean_text(child.text or "")
            elif t in ("pubDate", "published", "updated", "date"):
                if not pub:
                    pub = (child.text or "").strip()
        if title or link:
            items.append({
                "title": title,
                "link": link,
                "summary": summary[:400],
                "published_raw": pub,
            })
    return items


def matches(text):
    low = text.lower()
    core = any(k in low for k in CORE_KEYWORDS)
    flood = any(k in low for k in FLOOD_TERMS)
    highlight = any(k in low for k in HIGHLIGHT_KEYWORDS)
    keep = core or (flood and highlight)
    return keep, highlight


def main():
    collected = []
    seen_links = set()
    source_status = []

    for src in SOURCES:
        status = {"name": src["name"], "ok": False, "count": 0, "error": None}
        try:
            raw = fetch(src["url"])
            feed_items = parse_feed(raw)
            kept = 0
            for it in feed_items:
                blob = f"{it['title']} {it['summary']}"
                keep, highlight = matches(blob)
                if not keep:
                    continue
                link = it["link"]
                if not link or link in seen_links:
                    continue
                seen_links.add(link)
                dt = parse_date(it["published_raw"])
                collected.append({
                    "title": it["title"],
                    "link": link,
                    "summary": it["summary"],
                    "source": src["name"],
                    "flag": src["flag"],
                    "country": src["country"],
                    "highlight": highlight,
                    "published": dt.isoformat() if dt else None,
                    "published_ts": dt.timestamp() if dt else 0,
                })
                kept += 1
            status["ok"] = True
            status["count"] = kept
            log(f"{src['name']}: {kept} relevant / {len(feed_items)} total")
        except urllib.error.URLError as e:
            status["error"] = str(e.reason)
            log(f"{src['name']}: ERROR {e.reason}")
        except Exception as e:  # noqa
            status["error"] = str(e)
            log(f"{src['name']}: ERROR {e}")
        source_status.append(status)
        time.sleep(0.3)

    collected.sort(key=lambda x: x["published_ts"], reverse=True)
    collected = collected[:MAX_ITEMS]

    data = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(collected),
        "highlight_count": sum(1 for c in collected if c["highlight"]),
        "sources": source_status,
        "items": collected,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"wrote {OUT_PATH} ({len(collected)} items, {data['highlight_count']} highlighted)")


if __name__ == "__main__":
    main()
