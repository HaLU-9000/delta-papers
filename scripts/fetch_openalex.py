#!/usr/bin/env python3
"""Fetch recent papers from OpenAlex by keyword search.

OpenAlex Works API — free, no auth required, abstracts included (as an
inverted index which we reconstruct). Intended as the "Google Scholar-like"
broad keyword search path for the ΔPapers digest.

Output schema matches fetch_arxiv.py: a JSON array of objects with keys
  id, title, authors, abstract, url, pdf_url, published,
  primary_category, categories

Usage:
  python3 fetch_openalex.py --keywords "alignment,RLHF" --lookback-days 2 \\
      --max-results 50 [--authors "Christiano,Bai"] [--mailto you@example.com]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta


API = "https://api.openalex.org/works"
UA = "delta-papers-digest/1.0 (mailto:anonymous@example.com)"


def _ensure_utf8_std_streams() -> None:
    for s in (sys.stdout, sys.stderr):
        enc = getattr(s, "encoding", None) or ""
        if enc.lower() != "utf-8":
            try:
                s.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
            except Exception:
                pass


def reconstruct_abstract(inv):
    """OpenAlex gives abstracts as {word: [positions...]}. Reconstruct."""
    if not inv or not isinstance(inv, dict):
        return ""
    positions = []
    for word, idxs in inv.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort()
    return " ".join(w for _, w in positions)


def fetch_json(url, mailto):
    headers = {"User-Agent": UA}
    if mailto:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}mailto={urllib.parse.quote(mailto)}"
    req = urllib.request.Request(url, headers=headers)
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 503):
                time.sleep(3 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise last


def search_keyword(keyword, since_iso, per_page, mailto):
    q = {
        "search": keyword,
        "filter": f"from_publication_date:{since_iso}",
        "per-page": str(per_page),
        "sort": "publication_date:desc",
    }
    url = f"{API}?{urllib.parse.urlencode(q)}"
    return fetch_json(url, mailto).get("results", []) or []


def to_paper(w):
    work_id = (w.get("id") or "").rsplit("/", 1)[-1] or w.get("doi", "")
    title = w.get("title") or w.get("display_name") or ""
    abstract = reconstruct_abstract(w.get("abstract_inverted_index"))
    pub = w.get("publication_date") or ""
    authors = []
    for a in w.get("authorships") or []:
        name = ((a.get("author") or {}).get("display_name")) or ""
        if name:
            authors.append(name)
    doi = w.get("doi") or ""
    # Prefer DOI-based landing page, fall back to OpenAlex URL.
    url = doi if doi.startswith("http") else (w.get("id") or "")
    pdf = ""
    oa = w.get("best_oa_location") or w.get("primary_location") or {}
    if isinstance(oa, dict):
        pdf = oa.get("pdf_url") or ""
    concepts = []
    for c in (w.get("concepts") or [])[:5]:
        n = c.get("display_name")
        if n:
            concepts.append(n)
    primary = concepts[0] if concepts else ""
    return {
        "id": f"openalex:{work_id}",
        "title": title.strip(),
        "authors": authors,
        "abstract": abstract.strip(),
        "url": url,
        "pdf_url": pdf,
        "published": pub,
        "primary_category": primary,
        "categories": concepts,
    }


def main():
    _ensure_utf8_std_streams()
    ap = argparse.ArgumentParser(description="Fetch recent papers from OpenAlex by keyword.")
    ap.add_argument("--keywords", required=True,
                    help="Comma-separated keywords/phrases. One query per keyword, results deduped.")
    ap.add_argument("--lookback-days", type=float, default=2.0,
                    help="Only include works published in the last N days (default: 2).")
    ap.add_argument("--max-results", type=int, default=50,
                    help="per-page per keyword (default: 50). Results merged across keywords.")
    ap.add_argument("--authors", default="",
                    help="Comma-separated author substrings; filter to papers with any matching author.")
    ap.add_argument("--mailto", default="",
                    help="Email for OpenAlex polite pool (recommended).")
    args = ap.parse_args()

    kws = [k.strip() for k in args.keywords.split(",") if k.strip()]
    if not kws:
        print("[]")
        return 0

    since = (date.today() - timedelta(days=max(1, int(args.lookback_days)))).isoformat()

    seen = set()
    merged = []
    for kw in kws:
        try:
            works = search_keyword(kw, since, args.max_results, args.mailto)
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"[openalex] keyword {kw!r} failed: {e}\n")
            continue
        for w in works:
            p = to_paper(w)
            if p["id"] in seen or not p["title"]:
                continue
            seen.add(p["id"])
            merged.append(p)

    if args.authors:
        wants = [a.strip().lower() for a in args.authors.split(",") if a.strip()]
        if wants:
            def has_author(p):
                hay = " | ".join(p["authors"]).lower()
                return any(a in hay for a in wants)
            merged = [p for p in merged if has_author(p)]

    json.dump(merged, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
