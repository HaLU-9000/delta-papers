#!/usr/bin/env python3
"""Fetch recent arXiv papers using only Python 3 stdlib."""

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

ATOM_NS = "http://www.w3.org/2005/Atom"
ARXIV_NS = "http://arxiv.org/schemas/atom"
NS = {"atom": ATOM_NS, "arxiv": ARXIV_NS}

USER_AGENT = "Mozilla/5.0 (compatible; delta-papers-digest/1.0)"
API_BASE = "https://export.arxiv.org/api/query"


def clean_text(s):
    if s is None:
        return ""
    return re.sub(r"\s+", " ", s).strip()


def parse_dt(s):
    # arXiv uses e.g. 2026-04-14T18:30:00Z
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def extract_arxiv_id(entry_id_url):
    # e.g. http://arxiv.org/abs/2404.12345v1
    m = re.search(r"arxiv\.org/abs/([^/\s]+?)(v\d+)?$", entry_id_url.strip())
    if m:
        return m.group(1)
    # fallback: last path component
    return entry_id_url.rstrip("/").split("/")[-1]


def build_query_url(categories, max_results):
    cat_list = [c.strip() for c in categories.split(",") if c.strip()]
    search_query = "+OR+".join(f"cat:{c}" for c in cat_list)
    url = (
        f"{API_BASE}?search_query={search_query}"
        f"&start=0&max_results={max_results}"
        f"&sortBy=submittedDate&sortOrder=descending"
    )
    return url


def fetch(url):
    import time
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_err = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (429, 503):
                time.sleep(5 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
            time.sleep(3 * (attempt + 1))
            continue
    raise last_err


def parse_feed(xml_bytes):
    root = ET.fromstring(xml_bytes)
    entries = root.findall("atom:entry", NS)
    papers = []
    for e in entries:
        entry_id = (e.findtext("atom:id", default="", namespaces=NS) or "").strip()
        arxiv_id = extract_arxiv_id(entry_id)
        title = clean_text(e.findtext("atom:title", default="", namespaces=NS))
        abstract = clean_text(e.findtext("atom:summary", default="", namespaces=NS))
        published = (e.findtext("atom:published", default="", namespaces=NS) or "").strip()
        updated = (e.findtext("atom:updated", default="", namespaces=NS) or "").strip()

        authors = []
        for a in e.findall("atom:author", NS):
            name = a.findtext("atom:name", default="", namespaces=NS)
            name = clean_text(name)
            if name:
                authors.append(name)

        categories = []
        for c in e.findall("atom:category", NS):
            term = c.get("term")
            if term:
                categories.append(term)

        primary = ""
        pc = e.find("arxiv:primary_category", NS)
        if pc is not None:
            primary = pc.get("term", "") or ""
        if not primary and categories:
            primary = categories[0]

        url_abs = f"https://arxiv.org/abs/{arxiv_id}"
        url_pdf = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

        papers.append({
            "id": arxiv_id,
            "title": title,
            "authors": authors,
            "abstract": abstract,
            "url": url_abs,
            "pdf_url": url_pdf,
            "published": published,
            "updated": updated,
            "primary_category": primary,
            "categories": categories,
        })
    return papers


def filter_papers(papers, lookback_hours, keywords, authors_filter):
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=lookback_hours)

    kw_list = []
    if keywords:
        kw_list = [k.strip().lower() for k in keywords.split(",") if k.strip()]

    auth_list = []
    if authors_filter:
        auth_list = [a.strip().lower() for a in authors_filter.split(",") if a.strip()]

    out = []
    for p in papers:
        pub_dt = parse_dt(p.get("published", ""))
        upd_dt = parse_dt(p.get("updated", ""))
        candidates = [d for d in (pub_dt, upd_dt) if d is not None]
        if not candidates:
            continue
        latest = max(candidates)
        if latest < cutoff:
            continue

        if kw_list:
            haystack = (p["title"] + " " + p["abstract"]).lower()
            if not any(k in haystack for k in kw_list):
                continue

        if auth_list:
            author_hay = " | ".join(p["authors"]).lower()
            if not any(a in author_hay for a in auth_list):
                continue

        # Drop the helper 'updated' field from final output
        out.append({
            "id": p["id"],
            "title": p["title"],
            "authors": p["authors"],
            "abstract": p["abstract"],
            "url": p["url"],
            "pdf_url": p["pdf_url"],
            "published": p["published"],
            "primary_category": p["primary_category"],
            "categories": p["categories"],
        })
    return out


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
    ap = argparse.ArgumentParser(description="Fetch recent arXiv papers.")
    ap.add_argument("--categories", default="cs.AI,cs.CL,cs.LG",
                    help="Comma-separated arXiv categories (default: cs.AI,cs.CL,cs.LG)")
    ap.add_argument("--lookback-hours", type=float, default=30.0,
                    help="Only include papers published/updated within this many hours (default: 30)")
    ap.add_argument("--max-results", type=int, default=50,
                    help="Maximum results to request from arXiv API (default: 50)")
    ap.add_argument("--keywords", default="",
                    help="Comma-separated keywords; filter to papers whose title/abstract contains any (case-insensitive)")
    ap.add_argument("--authors", default="",
                    help="Comma-separated author name substrings; filter to papers with any matching author")
    args = ap.parse_args()

    url = build_query_url(args.categories, args.max_results)

    try:
        raw = fetch(url)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        print(f"Error fetching arXiv API: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        papers = parse_feed(raw)
    except ET.ParseError as e:
        print(f"Error parsing arXiv response: {e}", file=sys.stderr)
        sys.exit(1)

    filtered = filter_papers(papers, args.lookback_hours, args.keywords, args.authors)
    json.dump(filtered, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
