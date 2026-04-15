#!/usr/bin/env python3
"""Fetch recent papers from journal RSS/Atom feeds. Stdlib only."""

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

JOURNAL_FEEDS = {
    "nature": ["https://www.nature.com/nature.rss"],
    "science": ["https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science"],
    "cell": [
        "https://www.cell.com/cell/current.rss",
        "https://www.cell.com/cell/inpress.rss",
    ],
    "pnas": ["https://www.pnas.org/action/showFeed?type=etoc&feed=rss&jc=pnas"],
    "bioinformatics": [
        "https://academic.oup.com/rss/site_5127/3091.xml",
        "https://academic.oup.com/rss/site_5127/OpenAccess.xml",
    ],
}

USER_AGENT = "Mozilla/5.0 (compatible; delta-papers-digest/1.0)"
TIMEOUT = 30
RETRY_DELAYS = [3, 6, 9]

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
}

DOI_RE = re.compile(r"10\.\d{4,9}/[A-Za-z0-9._\-]+(?:/[A-Za-z0-9._\-]+)*")
TAG_RE = re.compile(r"<[^>]+>")


def warn(msg):
    print(f"[fetch_rss] WARN: {msg}", file=sys.stderr)


def fetch_url(url):
    """Fetch a URL with retries. Returns bytes or None."""
    last_err = None
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code} {e.reason}"
            if e.code in (429, 503) and attempt < len(RETRY_DELAYS):
                time.sleep(RETRY_DELAYS[attempt])
                continue
            break
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = str(e)
            if attempt < len(RETRY_DELAYS):
                time.sleep(RETRY_DELAYS[attempt])
                continue
            break
    warn(f"fetch failed: {url} ({last_err})")
    return None


def strip_html(text):
    if not text:
        return ""
    text = html.unescape(text)
    text = TAG_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


DATE_FORMATS = [
    "%a, %d %b %Y %H:%M:%S %z",  # RFC822 with tz offset
    "%a, %d %b %Y %H:%M:%S %Z",  # RFC822 with tz name (GMT/UTC)
    "%a, %d %b %Y %H:%M %z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%d",
]


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    # Normalize trailing Z handling is covered; also strip fractional trailing tz forms
    candidates = [s]
    # Some feeds use "+0000" vs "+00:00"; strptime %z in py3.7+ accepts both but try both
    if re.search(r"[+-]\d{2}:\d{2}$", s):
        candidates.append(s[:-3] + s[-2:])
    for fmt in DATE_FORMATS:
        for c in candidates:
            try:
                dt = datetime.strptime(c, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except ValueError:
                continue
    return None


def find_doi(*texts):
    for t in texts:
        if not t:
            continue
        m = DOI_RE.search(t)
        if m:
            doi = m.group(0).rstrip(".,);]\"'")
            # Strip trailing capitalized-word run that got glued on (e.g. "...xIn" -> "...x")
            doi = re.sub(r"(?<=[a-z0-9])([A-Z][a-zA-Z]*)$", "", doi)
            doi = re.sub(r"(?<=[a-z0-9])([A-Z][a-z]+)$", "", doi)
            return doi
    return ""


def local_tag(elem):
    tag = elem.tag
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def parse_feed(xml_bytes, journal_slug):
    """Parse RSS 2.0 or Atom. Returns list of normalized items."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        warn(f"xml parse error for {journal_slug}: {e}")
        return []

    items = []
    rtag = local_tag(root)

    if rtag == "rss":
        channel = root.find("channel")
        if channel is None:
            return []
        entries = channel.findall("item")
        for it in entries:
            items.append(parse_rss_item(it, journal_slug))
    elif rtag == "feed":
        entries = root.findall("atom:entry", NS) or [
            e for e in root if local_tag(e) == "entry"
        ]
        for it in entries:
            items.append(parse_atom_entry(it, journal_slug))
    else:
        # try to autodetect nested
        for it in root.iter():
            if local_tag(it) == "item":
                items.append(parse_rss_item(it, journal_slug))
            elif local_tag(it) == "entry":
                items.append(parse_atom_entry(it, journal_slug))
    return [i for i in items if i]


def child_text(elem, *names):
    """Return text of first matching child (local-name match)."""
    for child in elem:
        lt = local_tag(child)
        if lt in names:
            return (child.text or "").strip()
    return ""


def all_children(elem, *names):
    out = []
    for child in elem:
        if local_tag(child) in names:
            out.append(child)
    return out


def parse_rss_item(item, journal_slug):
    title = strip_html(child_text(item, "title"))
    link = child_text(item, "link")
    guid = child_text(item, "guid")
    description = strip_html(child_text(item, "description"))
    # content:encoded
    content_enc = ""
    for c in item:
        if local_tag(c) == "encoded":
            content_enc = strip_html(c.text or "")
            break
    abstract = description or content_enc

    pub = (
        child_text(item, "pubDate")
        or child_text(item, "date")
        or child_text(item, "published")
        or child_text(item, "updated")
    )
    published_dt = parse_date(pub)

    authors = []
    for c in item:
        lt = local_tag(c)
        if lt == "creator" or lt == "author":
            if c.text:
                # author may contain "email (Name)" or just name
                name = c.text.strip()
                m = re.search(r"\(([^)]+)\)", name)
                if m:
                    name = m.group(1).strip()
                authors.append(name)

    doi = find_doi(guid, link, abstract, title)
    ident = f"doi:{doi}" if doi else (link or guid or title)

    return {
        "id": ident,
        "title": title,
        "authors": authors,
        "abstract": abstract,
        "url": link or guid,
        "pdf_url": "",
        "published": published_dt.strftime("%Y-%m-%dT%H:%M:%SZ") if published_dt else (pub or ""),
        "_published_dt": published_dt,
        "primary_category": journal_slug,
        "categories": [journal_slug],
        "source": "rss",
        "journal": journal_slug,
        "doi": doi,
        "_dedupe_key": (link or guid or ident),
    }


def parse_atom_entry(entry, journal_slug):
    title = strip_html(child_text(entry, "title"))
    # link: prefer rel="alternate" or first href
    link = ""
    for c in entry:
        if local_tag(c) == "link":
            href = c.attrib.get("href", "")
            rel = c.attrib.get("rel", "alternate")
            if rel == "alternate" and href:
                link = href
                break
            if not link and href:
                link = href
    entry_id = child_text(entry, "id")
    summary = strip_html(child_text(entry, "summary") or child_text(entry, "content"))

    pub = (
        child_text(entry, "published")
        or child_text(entry, "updated")
        or child_text(entry, "date")
    )
    published_dt = parse_date(pub)

    authors = []
    for c in entry:
        lt = local_tag(c)
        if lt == "author":
            # author/name
            for sub in c:
                if local_tag(sub) == "name" and sub.text:
                    authors.append(sub.text.strip())
        elif lt == "creator" and c.text:
            authors.append(c.text.strip())

    doi = find_doi(entry_id, link, summary, title)
    ident = f"doi:{doi}" if doi else (link or entry_id or title)

    return {
        "id": ident,
        "title": title,
        "authors": authors,
        "abstract": summary,
        "url": link or entry_id,
        "pdf_url": "",
        "published": published_dt.strftime("%Y-%m-%dT%H:%M:%SZ") if published_dt else (pub or ""),
        "_published_dt": published_dt,
        "primary_category": journal_slug,
        "categories": [journal_slug],
        "source": "rss",
        "journal": journal_slug,
        "doi": doi,
        "_dedupe_key": (link or entry_id or ident),
    }


def _ensure_utf8_std_streams():
    for stream in (sys.stdout, sys.stderr):
        enc = getattr(stream, "encoding", None)
        if enc and enc.lower() != "utf-8":
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass


def main():
    _ensure_utf8_std_streams()
    ap = argparse.ArgumentParser(description="Fetch papers from journal RSS/Atom feeds")
    ap.add_argument("--journals", default="", help="comma-separated journal slugs")
    ap.add_argument("--feed-url", action="append", default=[], help="ad-hoc feed URL (repeatable)")
    ap.add_argument("--lookback-days", type=int, default=7)
    ap.add_argument("--max-results", type=int, default=50)
    ap.add_argument("--keywords", default="", help="comma-separated keywords")
    ap.add_argument("--authors", default="", help="comma-separated author substrings")
    args = ap.parse_args()

    journals = [j.strip() for j in args.journals.split(",") if j.strip()]
    keywords = [k.strip().lower() for k in args.keywords.split(",") if k.strip()]
    authors_filter = [a.strip().lower() for a in args.authors.split(",") if a.strip()]

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.lookback_days)

    all_items = []
    sources_tried = 0
    sources_ok = 0

    # Process registered journals
    for slug in journals:
        if slug not in JOURNAL_FEEDS:
            warn(f"unknown journal slug: {slug}")
            continue
        journal_ok = False
        seen_keys = set()
        for url in JOURNAL_FEEDS[slug]:
            sources_tried += 1
            data = fetch_url(url)
            if not data:
                continue
            parsed = parse_feed(data, slug)
            if parsed:
                journal_ok = True
                sources_ok += 1
                for p in parsed:
                    k = p.get("_dedupe_key")
                    if k in seen_keys:
                        continue
                    seen_keys.add(k)
                    all_items.append(p)
        if not journal_ok:
            warn(f"journal {slug}: no items from any feed")

    # Ad-hoc feed URLs
    for url in args.feed_url:
        sources_tried += 1
        data = fetch_url(url)
        if not data:
            continue
        parsed = parse_feed(data, "custom")
        if parsed:
            sources_ok += 1
            all_items.extend(parsed)

    # Global dedupe across journals by id
    seen = set()
    deduped = []
    for it in all_items:
        key = it["id"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(it)

    # Date filter
    filtered = []
    for it in deduped:
        dt = it.get("_published_dt")
        if dt is None or dt >= cutoff:
            filtered.append(it)

    # Keyword filter
    if keywords:
        def kw_match(it):
            hay = (it["title"] + " " + it["abstract"]).lower()
            return any(k in hay for k in keywords)
        filtered = [i for i in filtered if kw_match(i)]

    # Author filter
    if authors_filter:
        def a_match(it):
            names = " ".join(it["authors"]).lower()
            return any(a in names for a in authors_filter)
        filtered = [i for i in filtered if a_match(i)]

    # Sort by published desc, None last
    def sort_key(it):
        dt = it.get("_published_dt")
        return (0 if dt is None else 1, dt or datetime.min.replace(tzinfo=timezone.utc))
    filtered.sort(key=sort_key, reverse=True)

    # Truncate
    filtered = filtered[: args.max_results]

    # Strip private fields
    for it in filtered:
        it.pop("_published_dt", None)
        it.pop("_dedupe_key", None)

    json.dump(filtered, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")

    if len(filtered) == 0 and sources_ok == 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
