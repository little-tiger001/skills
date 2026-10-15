#!/usr/bin/env python3
"""
Tavily Search v1.0 - AI-powered web search platform with 5 modes.
Author: Leo 🦁
Created: 2026-02-07

Commands:
- search: General web search with optional LLM answer
- news: News-optimized search (topic=news)
- finance: Finance-optimized search (topic=finance)
- extract: Extract content from URLs
- crawl: Crawl a website
- map: Discover sitemap URLs
- research: Deep AI research with citations

Environment Variables:
- TAVILY_API_KEYS: Optional. Comma-separated list of API keys (multi-key rotation).
- TAVILY_API_KEY: Optional. Single API key (backward compatible).

Key sources, merged in this order (duplicates removed):
1. lib/keys.txt next to this script — one key per line, '#' starts a comment
2. TAVILY_API_KEYS environment variable (comma-separated)
3. TAVILY_API_KEY environment variable (single)
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from typing import Any, Optional

# ─── Configuration ───────────────────────────────────────────────────────────

SCRIPT_DIR: str = os.path.dirname(os.path.abspath(__file__))
KEYS_FILE: str = os.path.join(SCRIPT_DIR, "keys.txt")
CURSOR_FILE: str = os.path.join(SCRIPT_DIR, ".key_cursor")
BASE_URL: str = "https://api.tavily.com"
REQUEST_TIMEOUT: int = 30
RESEARCH_TIMEOUT: int = 120  # Research can take longer


class _ApiKeyError(Exception):
    """Key rejected by the API (401 invalid / 429 rate-limited) — retry with another key."""


def _load_keys() -> list[str]:
    """Collect API keys from keys.txt, TAVILY_API_KEYS and TAVILY_API_KEY, in that order."""
    raw: list[str] = []

    if os.path.isfile(KEYS_FILE):
        with open(KEYS_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    raw.append(line)

    for k in os.environ.get("TAVILY_API_KEYS", "").split(","):
        if k.strip():
            raw.append(k.strip())

    single = os.environ.get("TAVILY_API_KEY", "").strip()
    if single:
        raw.append(single)

    seen: set[str] = set()
    keys: list[str] = []
    for k in raw:
        if k not in seen:
            seen.add(k)
            keys.append(k)
    return keys


def _mask_key(key: str) -> str:
    """Show just enough of a key to tell the keys apart."""
    return f"{key[:12]}…" if len(key) > 12 else key


def _load_cursor() -> int:
    """Index of the next key to try, persisted so separate CLI calls alternate keys."""
    try:
        with open(CURSOR_FILE, encoding="utf-8") as f:
            return max(0, int(f.read().strip()))
    except (OSError, ValueError):
        return 0


def _save_cursor(idx: int) -> None:
    """Best-effort persistence; a read-only or missing directory must never break a call."""
    try:
        with open(CURSOR_FILE, "w", encoding="utf-8") as f:
            f.write(str(idx))
    except OSError:
        pass


def _pin_key(selector: str) -> None:
    """Pin one key by 1-based index, exact value, or unique prefix (--key)."""
    global _pinned_key
    sel = selector.strip()

    if sel.isdigit():
        idx = int(sel)
        if 1 <= idx <= len(API_KEYS):
            _pinned_key = API_KEYS[idx - 1]
            return
        print(f"Error: --key {idx} is out of range (1-{len(API_KEYS)}).", file=sys.stderr)
        sys.exit(1)

    if sel in API_KEYS:
        _pinned_key = sel
        return

    for k in API_KEYS:
        if k.startswith(sel):
            _pinned_key = k
            return

    print(f"Error: --key '{sel}' does not match any configured key.", file=sys.stderr)
    sys.exit(1)


API_KEYS: list[str] = _load_keys()
API_KEY: str = API_KEYS[0] if API_KEYS else ""  # kept for backward compatibility
_pinned_key: Optional[str] = None


# ─── HTTP Helper ─────────────────────────────────────────────────────────────

def _api_request_once(
    endpoint: str,
    payload: dict[str, Any],
    api_key: str,
    timeout: int = REQUEST_TIMEOUT,
) -> dict[str, Any]:
    """
    Make a single POST request to the Tavily API with one specific key.

    Raises:
        _ApiKeyError: On 401 (invalid key) or 429 (rate-limited) — the caller may
            retry with a different key.
        SystemExit: On any other API error.
    """
    url = f"{BASE_URL}{endpoint}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        if e.code in (401, 429):
            reason = "invalid key" if e.code == 401 else "rate limited"
            raise _ApiKeyError(f"{_mask_key(api_key)} {reason} ({e.code})")
        if e.code == 400:
            # Try to extract error message from JSON response
            try:
                err_data = json.loads(body)
                msg = err_data.get("detail", err_data.get("message", body))
                print(f"Error: Bad request - {msg}", file=sys.stderr)
            except (json.JSONDecodeError, KeyError):
                print(f"Error: Bad request - {body}", file=sys.stderr)
        else:
            print(f"Error: Tavily API returned {e.code} (key {_mask_key(api_key)}): {body}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Error: Network error - {e.reason}", file=sys.stderr)
        sys.exit(1)
    except TimeoutError:
        print(f"Error: Request timed out after {timeout}s", file=sys.stderr)
        sys.exit(1)


def _api_request(
    endpoint: str,
    payload: dict[str, Any],
    timeout: int = REQUEST_TIMEOUT,
) -> dict[str, Any]:
    """
    POST to the Tavily API with automatic multi-key rotation.

    Every configured key is tried once, starting from the persisted cursor.
    Keys rejected with 401 (invalid) or 429 (rate-limited) are skipped and the
    next key is used; non-key errors (400, network, timeout) fail immediately.
    """
    keys = [_pinned_key] if _pinned_key else API_KEYS
    if not keys:
        print("Error: no Tavily API keys configured.", file=sys.stderr)
        print("Add keys to lib/keys.txt (one per line), or set TAVILY_API_KEYS / TAVILY_API_KEY.", file=sys.stderr)
        sys.exit(1)

    total = len(keys)
    start = _load_cursor() % total if total > 1 else 0
    failures: list[str] = []

    for attempt in range(total):
        idx = (start + attempt) % total
        try:
            result = _api_request_once(endpoint, payload, keys[idx], timeout)
            if total > 1:
                _save_cursor((idx + 1) % total)
            return result
        except _ApiKeyError as e:
            failures.append(str(e))

    print(f"Error: all {total} configured API key(s) failed:", file=sys.stderr)
    for failure in failures:
        print(f"  - {failure}", file=sys.stderr)
    sys.exit(1)


# ─── Output Formatting ──────────────────────────────────────────────────────

def _format_search_results(data: dict[str, Any], as_json: bool = False) -> str:
    """Format search/news/finance results for display."""
    if as_json:
        return json.dumps(data, ensure_ascii=False, indent=2)

    lines: list[str] = []

    # LLM answer
    answer = data.get("answer")
    if answer:
        lines.append(f"Answer: {answer}")
        lines.append("")

    # Images
    images = data.get("images")
    if images:
        lines.append("Images:")
        for img in images:
            if isinstance(img, dict):
                lines.append(f"  - {img.get('url', img)}")
            else:
                lines.append(f"  - {img}")
        lines.append("")

    # Results
    results = data.get("results", [])
    if results:
        lines.append("Results:")
        for i, r in enumerate(results, 1):
            title = r.get("title", "Untitled")
            url = r.get("url", "")
            content = r.get("content", "")
            score = r.get("score")
            published = r.get("published_date", "")

            lines.append(f"  {i}. {title}")
            lines.append(f"     {url}")
            if published:
                lines.append(f"     Published: {published}")
            if score is not None:
                lines.append(f"     Score: {score:.4f}")
            if content:
                # Truncate long content to keep output readable
                snippet = content[:500].strip()
                if len(content) > 500:
                    snippet += "..."
                lines.append(f"     {snippet}")

            # Raw content (if requested)
            raw = r.get("raw_content")
            if raw:
                lines.append(f"     --- Raw Content ---")
                raw_snippet = raw[:1000].strip()
                if len(raw) > 1000:
                    raw_snippet += f"... [{len(raw)} chars total]"
                lines.append(f"     {raw_snippet}")

            lines.append("")
    elif not answer:
        lines.append("No results found.")

    return "\n".join(lines).rstrip()


def _format_extract_results(data: dict[str, Any], as_json: bool = False) -> str:
    """Format extract results for display."""
    if as_json:
        return json.dumps(data, ensure_ascii=False, indent=2)

    lines: list[str] = []
    results = data.get("results", [])

    if not results:
        return "No content extracted."

    for r in results:
        url = r.get("url", "Unknown URL")
        content = r.get("raw_content", "")
        lines.append(f"URL: {url}")
        lines.append("─" * 50)
        if content:
            lines.append(content.strip())
        else:
            lines.append("(No content extracted)")
        lines.append("")

    # Failed URLs
    failed = data.get("failed_results", [])
    if failed:
        lines.append("Failed URLs:")
        for f in failed:
            url = f.get("url", "Unknown")
            error = f.get("error", "Unknown error")
            lines.append(f"  ✗ {url}: {error}")

    return "\n".join(lines).rstrip()


def _format_crawl_results(data: dict[str, Any], as_json: bool = False) -> str:
    """Format crawl results for display."""
    if as_json:
        return json.dumps(data, ensure_ascii=False, indent=2)

    lines: list[str] = []
    results = data.get("results", [])
    base_url = data.get("base_url", "")

    lines.append(f"Crawled {len(results)} pages from {base_url}")
    lines.append("")

    for i, r in enumerate(results, 1):
        url = r.get("url", "Unknown URL")
        content = r.get("raw_content", "")
        lines.append(f"Page {i}: {url}")
        lines.append("─" * 50)
        if content:
            # Truncate very long pages
            snippet = content[:2000].strip()
            if len(content) > 2000:
                snippet += f"\n... [{len(content)} chars total]"
            lines.append(snippet)
        else:
            lines.append("(No content)")
        lines.append("")

    # Failed
    failed = data.get("failed_results", [])
    if failed:
        lines.append("Failed URLs:")
        for f in failed:
            url = f.get("url", "Unknown")
            error = f.get("error", "Unknown error")
            lines.append(f"  ✗ {url}: {error}")

    return "\n".join(lines).rstrip()


def _format_map_results(data: dict[str, Any], url: str, as_json: bool = False) -> str:
    """Format map/sitemap results for display."""
    if as_json:
        return json.dumps(data, ensure_ascii=False, indent=2)

    urls = data.get("results", [])
    lines: list[str] = []
    lines.append(f"Sitemap for {url} ({len(urls)} URLs found):")
    lines.append("")

    for i, u in enumerate(urls, 1):
        if isinstance(u, dict):
            lines.append(f"  {i}. {u.get('url', u)}")
        else:
            lines.append(f"  {i}. {u}")

    if not urls:
        lines.append("  No URLs discovered.")

    return "\n".join(lines).rstrip()


def _format_research_results(data: dict[str, Any], as_json: bool = False) -> str:
    """Format research results for display."""
    if as_json:
        return json.dumps(data, ensure_ascii=False, indent=2)

    lines: list[str] = []

    # Topic
    topic = data.get("topic") or data.get("query", "")
    if topic:
        lines.append(f"Research: {topic}")
        lines.append("")

    # Main content
    content = data.get("content") or data.get("output") or data.get("report", "")
    if content:
        lines.append(content.strip())
    else:
        lines.append("No research output returned.")

    # Sources
    sources = data.get("sources", [])
    if sources:
        lines.append("")
        lines.append("Sources:")
        for i, src in enumerate(sources, 1):
            if isinstance(src, dict):
                url = src.get("url", src.get("link", str(src)))
                title = src.get("title", "")
                if title:
                    lines.append(f"  [{i}] {title}")
                    lines.append(f"      {url}")
                else:
                    lines.append(f"  [{i}] {url}")
            else:
                lines.append(f"  [{i}] {src}")

    return "\n".join(lines).rstrip()


# ─── Commands ────────────────────────────────────────────────────────────────

def cmd_search(args: argparse.Namespace) -> str:
    """Execute search/news/finance command."""
    topic_map = {
        "search": "general",
        "news": "news",
        "finance": "finance",
    }

    payload: dict[str, Any] = {
        "query": args.query,
        "topic": topic_map.get(args.command, "general"),
        "search_depth": args.depth,
        "max_results": args.n,
    }

    if args.answer:
        payload["include_answer"] = True
    if args.raw:
        payload["include_raw_content"] = "markdown"
    if args.images:
        payload["include_images"] = True
    if args.time:
        payload["time_range"] = args.time
    if args.include_domains:
        payload["include_domains"] = [d.strip() for d in args.include_domains.split(",")]
    if args.exclude_domains:
        payload["exclude_domains"] = [d.strip() for d in args.exclude_domains.split(",")]
    if args.country:
        payload["country"] = args.country

    data = _api_request("/search", payload)
    return _format_search_results(data, as_json=args.as_json)


def cmd_extract(args: argparse.Namespace) -> str:
    """Execute extract command."""
    urls = args.urls
    if not urls:
        print("Error: At least one URL is required for extract.", file=sys.stderr)
        sys.exit(1)

    payload: dict[str, Any] = {
        "urls": urls if len(urls) > 1 else urls[0],
    }

    if args.depth and args.depth != "basic":
        payload["extract_depth"] = args.depth
    if hasattr(args, "format_type") and args.format_type:
        payload["format"] = args.format_type
    if hasattr(args, "query") and args.query:
        payload["query"] = args.query

    data = _api_request("/extract", payload)
    return _format_extract_results(data, as_json=args.as_json)


def cmd_crawl(args: argparse.Namespace) -> str:
    """Execute crawl command."""
    payload: dict[str, Any] = {
        "url": args.url,
    }

    if args.max_depth is not None:
        payload["max_depth"] = args.max_depth
    if args.max_breadth is not None:
        payload["max_breadth"] = args.max_breadth
    if args.limit is not None:
        payload["limit"] = args.limit
    if hasattr(args, "instructions") and args.instructions:
        payload["instructions"] = args.instructions
    if hasattr(args, "select_paths") and args.select_paths:
        payload["select_paths"] = [p.strip() for p in args.select_paths.split(",")]
    if hasattr(args, "exclude_paths") and args.exclude_paths:
        payload["exclude_paths"] = [p.strip() for p in args.exclude_paths.split(",")]
    if hasattr(args, "format_type") and args.format_type:
        payload["format"] = args.format_type

    data = _api_request("/crawl", payload, timeout=60)
    return _format_crawl_results(data, as_json=args.as_json)


def cmd_map(args: argparse.Namespace) -> str:
    """Execute map/sitemap command."""
    payload: dict[str, Any] = {
        "url": args.url,
    }

    if args.max_depth is not None:
        payload["max_depth"] = args.max_depth
    if args.max_breadth is not None:
        payload["max_breadth"] = args.max_breadth
    if args.limit is not None:
        payload["limit"] = args.limit

    data = _api_request("/map", payload)
    return _format_map_results(data, args.url, as_json=args.as_json)


def cmd_research(args: argparse.Namespace) -> str:
    """Execute research command."""
    payload: dict[str, Any] = {
        "input": args.query,
    }

    if args.model:
        payload["model"] = args.model

    data = _api_request("/research", payload, timeout=RESEARCH_TIMEOUT)
    return _format_research_results(data, as_json=args.as_json)


def cmd_keys(args: argparse.Namespace) -> str:
    """List the configured API keys (masked) — makes no API call."""
    if not API_KEYS:
        return "No API keys configured."

    lines: list[str] = [f"Configured API keys ({len(API_KEYS)}):"]
    for i, k in enumerate(API_KEYS, 1):
        lines.append(f"  {i}. {_mask_key(k)}  ({len(k)} chars)")
    lines.append(f"Source: {KEYS_FILE}")
    return "\n".join(lines)


# ─── CLI ─────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        description="Tavily Search v1.0 - AI-powered web search platform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s search "latest AI news" --answer
  %(prog)s news "tech industry" --time week
  %(prog)s finance "NVIDIA stock" --depth advanced
  %(prog)s extract "https://example.com/article"
  %(prog)s crawl "https://docs.example.com" --limit 20
  %(prog)s map "https://example.com"
  %(prog)s research "Impact of AI on healthcare"
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # ── Common search options ──
    def add_search_options(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("query", help="Search query")
        sub.add_argument("--depth", choices=["basic", "advanced"], default="basic",
                         help="Search depth (default: basic; advanced = 2 credits)")
        sub.add_argument("--time", choices=["day", "week", "month", "year", "d", "w", "m", "y"],
                         default=None, help="Time range filter")
        sub.add_argument("-n", type=int, default=5, help="Max results 0-20 (default: 5)")
        sub.add_argument("--answer", action="store_true", help="Include LLM-synthesized answer")
        sub.add_argument("--raw", action="store_true", help="Include raw page content")
        sub.add_argument("--images", action="store_true", help="Include image URLs")
        sub.add_argument("--include-domains", default=None,
                         help="Comma-separated domains to include")
        sub.add_argument("--exclude-domains", default=None,
                         help="Comma-separated domains to exclude")
        sub.add_argument("--country", default=None, help="Country code to boost (e.g., US, IL)")
        sub.add_argument("--json", action="store_true", dest="as_json", help="JSON output")

    # search
    p_search = subparsers.add_parser("search", help="Web search (general)")
    add_search_options(p_search)

    # news
    p_news = subparsers.add_parser("news", help="News search")
    add_search_options(p_news)

    # finance
    p_finance = subparsers.add_parser("finance", help="Finance search")
    add_search_options(p_finance)

    # extract
    p_extract = subparsers.add_parser("extract", help="Extract content from URLs")
    p_extract.add_argument("urls", nargs="+", help="URLs to extract content from")
    p_extract.add_argument("--depth", choices=["basic", "advanced"], default="basic",
                           help="Extraction depth")
    p_extract.add_argument("--format", dest="format_type", choices=["markdown", "text"],
                           default=None, help="Output format (default: markdown)")
    p_extract.add_argument("--query", default=None,
                           help="Query for relevance reranking of chunks")
    p_extract.add_argument("--json", action="store_true", dest="as_json", help="JSON output")

    # crawl
    p_crawl = subparsers.add_parser("crawl", help="Crawl a website")
    p_crawl.add_argument("url", help="Root URL to crawl")
    p_crawl.add_argument("--depth", choices=["basic", "advanced"], default=None,
                         help="Crawl depth")
    p_crawl.add_argument("--max-depth", type=int, default=None, help="Max link depth (default: 2)")
    p_crawl.add_argument("--max-breadth", type=int, default=None,
                         help="Max pages per level (default: 10)")
    p_crawl.add_argument("--limit", type=int, default=None, help="Max total pages (default: 10)")
    p_crawl.add_argument("--instructions", default=None,
                         help="Natural language crawl instructions")
    p_crawl.add_argument("--select-paths", default=None,
                         help="Comma-separated path patterns to include")
    p_crawl.add_argument("--exclude-paths", default=None,
                         help="Comma-separated path patterns to exclude")
    p_crawl.add_argument("--format", dest="format_type", choices=["markdown", "text"],
                         default=None, help="Output format")
    p_crawl.add_argument("--json", action="store_true", dest="as_json", help="JSON output")

    # map
    p_map = subparsers.add_parser("map", help="Discover sitemap URLs")
    p_map.add_argument("url", help="Root URL to map")
    p_map.add_argument("--max-depth", type=int, default=None, help="Max depth (default: 2)")
    p_map.add_argument("--max-breadth", type=int, default=None,
                       help="Max breadth per level (default: 20)")
    p_map.add_argument("--limit", type=int, default=None, help="Max URLs (default: 50)")
    p_map.add_argument("--json", action="store_true", dest="as_json", help="JSON output")

    # research
    p_research = subparsers.add_parser("research", help="Deep AI research")
    p_research.add_argument("query", help="Research question")
    p_research.add_argument("--model", choices=["mini", "pro", "auto"], default=None,
                            help="Research model (default: auto)")
    p_research.add_argument("--json", action="store_true", dest="as_json", help="JSON output")

    # keys
    p_keys = subparsers.add_parser("keys", help="List configured API keys (masked)")
    p_keys.add_argument("--json", action="store_true", dest="as_json", help="JSON output")

    # Key selection is accepted by every subcommand.
    for sub in subparsers.choices.values():
        sub.add_argument("--key", default=None, metavar="KEY",
                         help="Pin one API key by 1-based index, exact value, or unique prefix")

    return parser


def main() -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if not API_KEYS:
        print("Error: no Tavily API keys configured.", file=sys.stderr)
        print("Add keys to lib/keys.txt (one per line), or set TAVILY_API_KEYS / TAVILY_API_KEY.", file=sys.stderr)
        sys.exit(1)

    if getattr(args, "key", None):
        _pin_key(args.key)

    try:
        if args.command in ("search", "news", "finance"):
            result = cmd_search(args)
        elif args.command == "extract":
            result = cmd_extract(args)
        elif args.command == "crawl":
            result = cmd_crawl(args)
        elif args.command == "map":
            result = cmd_map(args)
        elif args.command == "research":
            result = cmd_research(args)
        elif args.command == "keys":
            result = cmd_keys(args)
        else:
            parser.print_help()
            sys.exit(1)

        print(result)
    except SystemExit:
        raise
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
