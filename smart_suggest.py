r"""
Researcher v0.4 - Smart, secure, AI-native research engine

Kurulum:
python -m venv .venv
.venv\Scripts\activate        (Windows)
source .venv/bin/activate     (Mac/Linux)
pip install python-dotenv requests ddgs

.env (opsiyonel):
TAVILY_API_KEY=xxx
STACKEXCHANGE_KEY=xxx

Kullanim:
python smart_suggest.py "Next.js rate limiting"
python smart_suggest.py "rate limiting" --summary
python smart_suggest.py "rate limiting" --ai --safe
python smart_suggest.py "auth" --report --output research.md
python smart_suggest.py "react state" --json --limit 4
"""
import os
import sys
import time
import json
import argparse
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
import requests
from ddgs import DDGS
from dotenv import load_dotenv

load_dotenv()

# Config
DEFAULT_LIMIT = 6
CACHE_TTL = 300
JINA_TIMEOUT = 8
SEARCH_TIMEOUT = 8
MAX_JINA_RESULTS = 3
CACHE_FILE = Path.home() / ".researcher_cache.json"
BLOCKLIST_FILE = Path.home() / ".researcher_blocklist.txt"

_cache = {}

DEFAULT_BLOCKLIST = {
    "malware.com",
    "phishing.example",
    "spam-domain.xyz",
    "fake-docs.io",
    "virus-site.net",
}

TRUSTED_DOMAINS = {
    "developer.mozilla.org": 1.0,
    "stackoverflow.com": 0.95,
    "github.com": 0.90,
    "npmjs.com": 0.85,
    "en.wikipedia.org": 0.80,
    "news.ycombinator.com": 0.75,
}

def load_blocklist():
    blocked = set(DEFAULT_BLOCKLIST)
    if BLOCKLIST_FILE.exists():
        try:
            for line in BLOCKLIST_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip().lower()
                if line and not line.startswith("#"):
                    blocked.add(line)
        except Exception:
            pass
    return blocked

BLOCKLIST = load_blocklist()

def _load_cache():
    try:
        if CACHE_FILE.exists():
            raw = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            for key, (ts, data) in raw.items():
                _cache[key] = (datetime.fromisoformat(ts), data)
    except Exception:
        pass

def _save_cache():
    try:
        payload = {k: (ts.isoformat(), data) for k, (ts, data) in _cache.items()}
        CACHE_FILE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

def get_cache(key):
    if key in _cache:
        ts, data = _cache[key]
        if datetime.now() - ts < timedelta(seconds=CACHE_TTL):
            return data
        del _cache[key]
    return None

def set_cache(key, data):
    _cache[key] = (datetime.now(), data)
    _save_cache()

_load_cache()

def detect_stack():
    stack = []
    try:
        pkg = Path("package.json")
        if pkg.exists():
            with open(pkg, encoding="utf-8-sig") as f:
                data = json.load(f)
            deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            frameworks = {
                "next": "Next.js", "react": "React", "vue": "Vue",
                "express": "Express", "fastify": "Fastify",
                "nuxt": "Nuxt", "svelte": "Svelte", "angular": "Angular"
            }
            for dep, name in frameworks.items():
                if dep in deps:
                    stack.append(name)
    except Exception:
        pass
    try:
        req = Path("requirements.txt")
        if req.exists():
            content = req.read_text().lower()
            for fw in ["django", "flask", "fastapi"]:
                if fw in content:
                    stack.append(fw.capitalize())
    except Exception:
        pass
    return list(set(stack))[:5]

def expand_query(query):
    expansions = {
        "rate limit": ["throttling", "api quota"],
        "auth": ["authentication", "jwt", "oauth"],
        "database": ["sql", "nosql", "orm"],
        "deploy": ["docker", "ci/cd", "kubernetes"],
        "state": ["redux", "zustand", "context"],
        "api": ["rest", "graphql", "endpoints"],
        "cache": ["redis", "caching", "memoization"]
    }
    q_lower = query.lower()
    extra = []
    for key, terms in expansions.items():
        if key in q_lower:
            extra.extend(terms)
    if extra:
        return f"{query} {' '.join(extra[:2])}"
    return query

# ==================== SECURITY ====================

def analyze_security(url):
    warnings = []
    penalty = 0
    if not url:
        return warnings, penalty
    if not url.startswith("https://"):
        warnings.append("Non-HTTPS connection")
        penalty += 30
    try:
        host = url.split("/")[2].lower()
    except Exception:
        host = ""
    if re.match(r"^\d+\.\d+\.\d+\.\d+$", host):
        warnings.append("Direct IP address URL")
        penalty += 25
    for shortener in ["bit.ly", "tinyurl.com", "t.co", "goo.gl"]:
        if shortener in host:
            warnings.append("URL shortener detected")
            penalty += 15
            break
    for blocked in BLOCKLIST:
        if blocked in host:
            warnings.append("BLOCKED domain")
            penalty += 100
            break
    lower_url = url.lower()
    for ext in [".exe", ".zip", ".bat", ".scr", ".msi"]:
        if ext in lower_url:
            warnings.append("Executable file link")
            penalty += 40
            break
    return warnings, penalty

def get_domain_trust(url):
    try:
        host = url.split("/")[2].lower()
    except Exception:
        return 0.5
    for domain, trust in TRUSTED_DOMAINS.items():
        if domain in host:
            return trust
    return 0.6

# ==================== SEARCH SOURCES ====================

def search_ddg(query, limit=2):
    try:
        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=limit))
            return [{
                "source": "DDG", "title": r.get("title", ""),
                "url": r.get("href", ""), "summary": r.get("body", ""),
                "weight": 0.6
            } for r in raw if r.get("title") and r.get("href")]
    except Exception:
        return []

def search_stackexchange(query, limit=2):
    try:
        params = {"site": "stackoverflow", "order": "desc", "sort": "relevance",
                  "q": query, "pagesize": limit}
        key = os.getenv("STACKEXCHANGE_KEY")
        if key:
            params["key"] = key
        resp = requests.get("https://api.stackexchange.com/2.3/search/advanced",
                            params=params, timeout=SEARCH_TIMEOUT)
        resp.raise_for_status()
        return [{
            "source": "SO", "title": item.get("title", ""),
            "url": item.get("link", ""), "summary": "",
            "weight": 0.9, "answered": item.get("is_answered", False)
        } for item in resp.json().get("items", []) if item.get("title")]
    except Exception:
        return []

def search_wikipedia(query, limit=2):
    try:
        params = {"action": "query", "list": "search", "format": "json",
                  "srsearch": query, "srlimit": limit}
        resp = requests.get("https://en.wikipedia.org/w/api.php", params=params,
                            headers={"User-Agent": "researcher-cli/1.0"},
                            timeout=SEARCH_TIMEOUT)
        resp.raise_for_status()
        results = resp.json().get("query", {}).get("search", [])
        return [{
            "source": "Wiki", "title": item.get("title", ""),
            "url": "https://en.wikipedia.org/wiki/" + requests.utils.quote(item.get("title", "").replace(" ", "_")),
            "summary": re.sub(r"<[^>]+>", "", item.get("snippet", "")),
            "weight": 0.7
        } for item in results if item.get("title")]
    except Exception:
        return []

def search_tavily(query, limit=2):
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return []
    try:
        resp = requests.post("https://api.tavily.com/search",
                             json={"api_key": api_key, "query": query,
                                   "max_results": limit},
                             timeout=SEARCH_TIMEOUT)
        resp.raise_for_status()
        return [{
            "source": "Tavily", "title": r.get("title", ""),
            "url": r.get("url", ""), "summary": r.get("content", ""),
            "weight": 0.8
        } for r in resp.json().get("results", []) if r.get("title")]
    except Exception:
        return []

def search_github(query, limit=2):
    try:
        params = {"q": query, "sort": "stars", "order": "desc", "per_page": limit}
        resp = requests.get("https://api.github.com/search/repositories",
                            params=params, timeout=SEARCH_TIMEOUT,
                            headers={"Accept": "application/vnd.github.v3+json",
                                     "User-Agent": "researcher-cli"})
        resp.raise_for_status()
        return [{
            "source": "GitHub", "title": item.get("full_name", ""),
            "url": item.get("html_url", ""),
            "summary": item.get("description", "") or "",
            "weight": 0.85, "stars": item.get("stargazers_count", 0),
            "updated": item.get("pushed_at", "")
        } for item in resp.json().get("items", []) if item.get("full_name")]
    except Exception:
        return []

def search_npm(query, limit=2):
    try:
        params = {"text": query, "size": limit}
        resp = requests.get("https://registry.npmjs.org/-/v1/search",
                            params=params, timeout=SEARCH_TIMEOUT)
        resp.raise_for_status()
        objects = resp.json().get("objects", [])
        return [{
            "source": "npm", "title": obj.get("package", {}).get("name", ""),
            "url": obj.get("package", {}).get("links", {}).get("npm", ""),
            "summary": obj.get("package", {}).get("description", ""),
            "weight": 0.8
        } for obj in objects if obj.get("package", {}).get("name")]
    except Exception:
        return []

def search_mdn(query, limit=2):
    try:
        params = {"q": query, "locale": "en-US"}
        resp = requests.get("https://developer.mozilla.org/api/v1/search",
                            params=params, timeout=SEARCH_TIMEOUT,
                            headers={"User-Agent": "researcher-cli"})
        resp.raise_for_status()
        documents = resp.json().get("documents", [])
        return [{
            "source": "MDN", "title": doc.get("title", ""),
            "url": "https://developer.mozilla.org" + doc.get("mdn_url", ""),
            "summary": doc.get("summary", ""),
            "weight": 0.95
        } for doc in documents[:limit] if doc.get("title")]
    except Exception:
        return []

def search_hn(query, limit=2):
    try:
        params = {"query": query, "tags": "story", "hitsPerPage": limit}
        resp = requests.get("https://hn.algolia.com/api/v1/search",
                            params=params, timeout=SEARCH_TIMEOUT)
        resp.raise_for_status()
        hits = resp.json().get("hits", [])
        return [{
            "source": "HN", "title": hit.get("title", ""),
            "url": hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
            "summary": f"Points: {hit.get('points', 0)}, Comments: {hit.get('num_comments', 0)}",
            "weight": 0.75
        } for hit in hits if hit.get("title")]
    except Exception:
        return []

SOURCE_MAP = {
    "ddg": search_ddg,
    "so": search_stackexchange,
    "wiki": search_wikipedia,
    "tavily": search_tavily,
    "github": search_github,
    "npm": search_npm,
    "mdn": search_mdn,
    "hn": search_hn,
}

# ==================== SCORING ====================

def calculate_relevance(result, query):
    title = (result.get("title") or "").lower()
    summary = (result.get("summary") or "").lower()
    terms = [t for t in query.lower().split() if len(t) > 2]
    if not terms:
        return 0.5
    hits = sum(1 for t in terms if t in title or t in summary)
    return min(hits / len(terms), 1.0)

def calculate_freshness(result):
    year = datetime.now().year
    text = f"{result.get('title', '')} {result.get('summary', '')}".lower()
    if str(year) in text:
        return 1.0
    if str(year - 1) in text:
        return 0.8
    if str(year - 2) in text:
        return 0.6
    if result.get("updated"):
        try:
            updated_year = int(result["updated"][:4])
            if updated_year >= year - 1:
                return 0.9
        except Exception:
            pass
    return 0.4

def calculate_confidence(result, all_results, query):
    base = result.get("weight", 0.5) * 40
    relevance = calculate_relevance(result, query) * 20
    freshness = calculate_freshness(result) * 15
    agreement = min((len(all_results) - 1) * 3, 15)
    security_penalty = result.get("security_penalty", 0)
    score = base + relevance + freshness + agreement - security_penalty
    if result.get("source") == "SO" and result.get("answered"):
        score += 5
    if result.get("source") == "GitHub" and result.get("stars", 0) > 1000:
        score += 5
    if result.get("source") == "MDN":
        score += 5
    if result.get("summary") and len(result.get("summary", "")) > 150:
        score += 3
    return max(0, min(int(score), 100))

def deduplicate(results):
    seen_urls, seen_titles, unique = set(), set(), []
    for r in results:
        url = r.get("url", "").lower().rstrip("/")
        title = r.get("title", "").lower().strip()
        if url in seen_urls or title in seen_titles:
            continue
        seen_urls.add(url)
        seen_titles.add(title)
        unique.append(r)
    return unique

def fetch_jina_content(url):
    try:
        resp = requests.get(f"https://r.jina.ai/{url}", timeout=JINA_TIMEOUT)
        resp.raise_for_status()
        return resp.text[:1000]
    except Exception:
        return None

# ==================== OUTPUT GENERATORS ====================

def generate_text_output(results, stack=None):
    lines = []
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if stack:
        lines.append(f"🔍 Detected stack: {', '.join(stack)}\n")
    for i, r in enumerate(results, 1):
        conf = r.get("confidence", 0)
        trust = r.get("trust_score", 100)
        icon = "🟢" if conf >= 70 else "🟡" if conf >= 40 else "🔴"
        extra = ""
        if r.get("stars"):
            extra = f" ⭐{r['stars']}"
        lines.append(f"{i}. {icon} [{r['source']}] {r.get('title', 'N/A')}{extra} (confidence: {conf}%, trust: {trust}%)")
        lines.append(f"   URL: {r.get('url', 'N/A')}")
        if r.get("warnings"):
            lines.append(f"   ⚠️  Warnings: {'; '.join(r['warnings'])}")
        content = r.get("content") or r.get("summary") or "No content"
        lines.append(f"   Summary: {content[:300]}...")
        lines.append("")
    return "\n".join(lines)

def generate_ai_output(results, stack=None, query=""):
    lines = []
    lines.append(f'## Research Results for "{query}"')
    if stack:
        lines.append(f"Stack: {', '.join(stack)}")
    lines.append("")
    for i, r in enumerate(results, 1):
        conf = r.get("confidence", 0)
        trust = r.get("trust_score", 100)
        lines.append(f"### {i}. [{r['source']}] {r.get('title', 'N/A')}")
        lines.append(f"URL: {r.get('url', 'N/A')}")
        lines.append(f"Confidence: {conf}% | Trust: {trust}%")
        if r.get("stars"):
            lines.append(f"Stars: {r['stars']}")
        if r.get("warnings"):
            lines.append(f"Warnings: {'; '.join(r['warnings'])}")
        content = r.get("content") or r.get("summary") or ""
        if content:
            lines.append(f"Summary: {content[:400]}")
        lines.append("")
    return "\n".join(lines)

def generate_summary(results, query, stack=None):
    top = results[:3]
    lines = []
    lines.append(f"## Quick Recommendation: {query}")
    if stack:
        lines.append(f"Context: {', '.join(stack)}")
    lines.append("")
    if not top:
        lines.append("No reliable sources found.")
        return "\n".join(lines)
    best = top[0]
    lines.append(f"**Primary suggestion:** {best.get('title')}")
    lines.append(f"Source: {best.get('source')} | Confidence: {best.get('confidence')}% | Trust: {best.get('trust_score', 100)}%")
    lines.append(f"URL: {best.get('url')}")
    if best.get("warnings"):
        lines.append(f"⚠️ Warnings: {'; '.join(best['warnings'])}")
    lines.append("")
    if len(top) > 1:
        lines.append("**Alternatives:**")
        for r in top[1:]:
            warn = " ⚠️" if r.get("warnings") else ""
            lines.append(f"- {r.get('title')} [{r.get('source')}] ({r.get('confidence')}%){warn}")
    lines.append("")
    avg_conf = sum(r.get("confidence", 0) for r in top) // len(top)
    if avg_conf >= 70:
        lines.append("Verdict: High confidence — safe to proceed.")
    elif avg_conf >= 40:
        lines.append("Verdict: Moderate confidence — verify before implementing.")
    else:
        lines.append("Verdict: Low confidence — do more research or ask human.")
    return "\n".join(lines)

def generate_report(results, query, stack=None, safe_mode=False):
    lines = []
    lines.append(f"# Research Report: {query}")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    if stack:
        lines.append(f"Stack: {', '.join(stack)}")
    lines.append(f"Total results: {len(results)}")
    lines.append(f"Safe mode: {'ON' if safe_mode else 'OFF'}")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append(generate_summary(results, query, stack))
    lines.append("")
    lines.append("## Detailed Results")
    for i, r in enumerate(results, 1):
        lines.append(f"### {i}. {r.get('title', 'N/A')}")
        lines.append(f"- Source: {r.get('source')}")
        lines.append(f"- URL: {r.get('url')}")
        lines.append(f"- Confidence: {r.get('confidence')}%")
        lines.append(f"- Trust Score: {r.get('trust_score', 100)}%")
        lines.append(f"- Relevance: {int(calculate_relevance(r, query) * 100)}%")
        lines.append(f"- Freshness: {int(calculate_freshness(r) * 100)}%")
        if r.get("stars"):
            lines.append(f"- Stars: {r['stars']}")
        if r.get("warnings"):
            lines.append(f"- ⚠️ Warnings: {'; '.join(r['warnings'])}")
        content = r.get("content") or r.get("summary") or "No content"
        lines.append(f"- Content: {content[:500]}")
        lines.append("")
    return "\n".join(lines)

def write_output(content, path):
    try:
        Path(path).write_text(content, encoding="utf-8")
        print(f"Saved to {path}")
    except Exception as e:
        print(f"Failed to save: {e}")

# ==================== MAIN ====================

def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Smart, secure, AI-native research engine")
    parser.add_argument("query", nargs="+", help="Search query")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--ai", action="store_true", help="AI-friendly markdown output")
    parser.add_argument("--summary", action="store_true", help="Executive summary for AI decisions")
    parser.add_argument("--report", action="store_true", help="Full markdown report")
    parser.add_argument("--output", type=str, help="Save output to file")
    parser.add_argument("--fast", action="store_true", help="Skip content extraction")
    parser.add_argument("--deep", action="store_true", help="Fetch content for all results")
    parser.add_argument("--expand", action="store_true", help="Expand query with tech terms")
    parser.add_argument("--safe", action="store_true", help="Filter low-trust results")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Max results")
    parser.add_argument("--sources", type=str, default="all",
                        help="Comma-separated sources: ddg,so,wiki,tavily,github,npm,mdn,hn")
    args = parser.parse_args()

    query = " ".join(args.query)
    if args.expand:
        query = expand_query(query)

    stack = detect_stack()
    limit_per_source = 4 if args.deep else 2

    if args.sources == "all":
        selected_sources = list(SOURCE_MAP.keys())
    else:
        selected_sources = [s.strip().lower() for s in args.sources.split(",") if s.strip().lower() in SOURCE_MAP]

    cache_key = f"{query}:{args.fast}:{args.deep}:{args.safe}:{','.join(sorted(selected_sources))}:{','.join(stack)}"
    cached = get_cache(cache_key)
    if cached:
        results = cached
    else:
        enriched = f"{query} {' '.join(stack[:3])}" if stack else query
        searches = []
        for src in selected_sources:
            func = SOURCE_MAP[src]
            if src in ("wiki", "tavily"):
                searches.append((func, query))
            else:
                searches.append((func, enriched))

        if not searches:
            print("No valid sources selected.")
            sys.exit(1)

        all_results = []
        with ThreadPoolExecutor(max_workers=len(searches)) as ex:
            futures = [ex.submit(f, q, limit_per_source) for f, q in searches]
            try:
                for future in as_completed(futures, timeout=SEARCH_TIMEOUT + 5):
                    try:
                        all_results.extend(future.result())
                    except Exception:
                        continue
            except Exception:
                pass

        results = deduplicate(all_results)

        # Security analysis
        for r in results:
            warnings, penalty = analyze_security(r.get("url", ""))
            r["warnings"] = warnings
            r["security_penalty"] = penalty
            r["trust_score"] = max(0, 100 - penalty)

        # Safe mode filter
        if args.safe:
            results = [r for r in results if r.get("trust_score", 0) >= 40
                       and not any("BLOCKED" in w for w in r.get("warnings", []))]

        results = results[:args.limit]

        if not results:
            msg = {"error": "No results found", "query": query}
            if args.json:
                print(json.dumps(msg))
            elif args.output:
                write_output("No results found.", args.output)
            else:
                print("No results found.")
            return

        for r in results:
            r["confidence"] = calculate_confidence(r, results, query)
        results.sort(key=lambda x: x["confidence"], reverse=True)

        if not args.fast:
            max_jina = len(results) if args.deep else MAX_JINA_RESULTS
            for r in results[:max_jina]:
                content = fetch_jina_content(r["url"])
                if content:
                    r["content"] = content[:500]
                elif r.get("summary"):
                    r["content"] = r["summary"][:500]
                else:
                    r["content"] = "Content unavailable"
                time.sleep(1)

        set_cache(cache_key, results)

    # Generate output
    if args.summary:
        output_text = generate_summary(results, query, stack)
    elif args.report:
        output_text = generate_report(results, query, stack, args.safe)
    elif args.ai:
        output_text = generate_ai_output(results, stack, query)
    elif args.json:
        output_text = json.dumps(results, ensure_ascii=False, indent=2)
    else:
        output_text = generate_text_output(results, stack)

    if args.output:
        write_output(output_text, args.output)
    else:
        print(output_text)

if __name__ == "__main__":
    main()