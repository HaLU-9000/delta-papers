#!/usr/bin/env python3
"""Fetch recent bioRxiv/medRxiv papers using only the Python 3 stdlib.

Outputs a JSON array of paper records to stdout.
"""

import argparse
import datetime as _dt
import json
import sys
import time
import urllib.error
import urllib.request

USER_AGENT = "Mozilla/5.0 (compatible; delta-papers-digest/1.0)"
API_BASE = "https://api.biorxiv.org/details"
PAGE_SIZE = 100  # bioRxiv API returns up to 100 per request
REQUEST_TIMEOUT = 120  # bioRxiv API can be slow; was 60, often times out
MAX_RETRIES = 4
BACKOFF_BASE = 2.0  # seconds; doubled each retry (2, 4, 8, 16)


def _err(msg):
    sys.stderr.write(str(msg).rstrip() + "\n")


def _fetch_page(server, from_date, to_date, cursor):
    url = "{base}/{server}/{frm}/{to}/{cur}".format(
        base=API_BASE, server=server, frm=from_date, to=to_date, cur=cursor
    )
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                data = resp.read()
            return json.loads(data.decode("utf-8", errors="replace"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
            last_err = e
            if attempt + 1 < MAX_RETRIES:
                wait = BACKOFF_BASE * (2 ** attempt)
                _err("bioRxiv fetch failed (attempt {}/{}): {} — retrying in {:.0f}s".format(
                    attempt + 1, MAX_RETRIES, e, wait))
                time.sleep(wait)
            else:
                _err("bioRxiv fetch failed after {} attempts: {}".format(MAX_RETRIES, e))
    raise last_err


def _parse_authors(raw):
    if not raw:
        return []
    # bioRxiv returns "Last F; Last2 G"
    return [a.strip() for a in raw.split(";") if a.strip()]


def _normalize(entry, server):
    doi = (entry.get("doi") or "").strip()
    version = str(entry.get("version") or "1").strip() or "1"
    host = "biorxiv.org" if server == "biorxiv" else "medrxiv.org"
    if doi:
        url = "https://www.{h}/content/{doi}v{v}".format(h=host, doi=doi, v=version)
        pdf_url = url + ".full.pdf"
    else:
        url = ""
        pdf_url = ""
    category = (entry.get("category") or "").strip().lower()
    return {
        "id": doi,
        "title": (entry.get("title") or "").strip(),
        "authors": _parse_authors(entry.get("authors") or ""),
        "abstract": (entry.get("abstract") or "").strip(),
        "url": url,
        "pdf_url": pdf_url,
        "published": (entry.get("date") or "").strip(),
        "primary_category": category,
        "categories": [category] if category else [],
        "source": server,
    }


def _match_keywords(paper, needle):
    if not needle:
        return True
    n = needle.lower()
    return n in paper["title"].lower() or n in paper["abstract"].lower()


def _match_authors(paper, needle):
    if not needle:
        return True
    n = needle.lower()
    return any(n in a.lower() for a in paper["authors"])


def main(argv=None):
    p = argparse.ArgumentParser(description="Fetch recent bioRxiv/medRxiv papers.")
    p.add_argument("--server", choices=["biorxiv", "medrxiv"], default="biorxiv")
    p.add_argument("--categories", default="",
                   help="Comma-separated category slugs (lowercase). Empty = no filter.")
    p.add_argument("--lookback-days", type=int, default=3)
    p.add_argument("--max-results", type=int, default=50)
    p.add_argument("--keywords", default="",
                   help="Optional substring filter in title or abstract.")
    p.add_argument("--authors", default="",
                   help="Optional substring filter in author list.")
    args = p.parse_args(argv)

    today = _dt.datetime.utcnow().date()
    from_date = (today - _dt.timedelta(days=max(0, args.lookback_days))).isoformat()
    to_date = today.isoformat()

    cats = [c.strip().lower() for c in args.categories.split(",") if c.strip()]
    cat_set = set(cats)

    results = []
    seen = set()
    cursor = 0
    total = None
    # Safety cap: up to 20 pages (2000 records) to avoid runaway loops.
    max_pages = 20
    pages = 0

    try:
        while pages < max_pages:
            payload = _fetch_page(args.server, from_date, to_date, cursor)
            pages += 1
            collection = payload.get("collection") or []
            messages = payload.get("messages") or []
            if messages and total is None:
                try:
                    total = int(messages[0].get("total") or 0)
                except (TypeError, ValueError):
                    total = 0
            if not collection:
                break
            for entry in collection:
                paper = _normalize(entry, args.server)
                if cat_set and paper["primary_category"] not in cat_set:
                    continue
                if not _match_keywords(paper, args.keywords):
                    continue
                if not _match_authors(paper, args.authors):
                    continue
                key = (paper["id"], paper["published"])
                if key in seen:
                    continue
                seen.add(key)
                results.append(paper)
            cursor += len(collection)
            if total is not None and cursor >= total:
                break
            # Stop paging early if we already have many more than requested.
            # We need enough to sort by date and trim, so collect a generous
            # buffer before stopping.
            if len(results) >= args.max_results * 4 and len(results) >= args.max_results:
                break
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        _err("Network error: {} (returning {} partial results)".format(e, len(results)))
        # Fall through to emit whatever we collected so far.
    except json.JSONDecodeError as e:
        _err("Failed to decode API response: {} (returning {} partial results)".format(e, len(results)))

    # Sort by published date descending (ISO date strings sort lexically).
    results.sort(key=lambda r: r.get("published") or "", reverse=True)
    if args.max_results >= 0:
        results = results[: args.max_results]

    sys.stdout.write(json.dumps(results, ensure_ascii=False, indent=2))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
