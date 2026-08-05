r"""
Researcher v0.3 - AI-native fast research engine

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
python smart_suggest.py "rate limiting" --fast
python smart_suggest.py "rate limiting" --ai
python smart_suggest.py "rate limiting" --json
python smart_suggest.py "react state" --sources github,npm,so
python smart_suggest.py "auth" --expand --deep --limit 4
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
MAX_PER_SOURCE = 2
DEFAULT_LIMIT = 6
CACHE_TTL = 300
JINA_TIMEOUT = 8
SEARCH_TIMEOUT = 8
MAX_JINA_RESULTS = 3
CACHE_FILE = Path.home() / ".researcher_cache.json"

_cache = {}

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
    """Proje stack'ini otomatik algila"""
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
    """Sorguyu teknik terimlerle zenginlestir"""
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

# ==================== SEARCH SOURCES ====================

def search_ddg(query):
    try:
        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=MAX_PER_SOURCE))
            return [{
                "source": "DDG", "title": r.get("title", ""),
                "url": r.get("href", ""), "summary": r.get("body", ""),
                "weight": 0.6
            } for r in raw if r.get("title") and r.get("href")]
    except Exception:
        return []

def search_stackexchange(query):
    try:
        params = {"site": "stackoverflow", "order": "desc", "sort": "relevance",
                  "q": query, "pagesize": MAX_PER_SOURCE}
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

def search_wikipedia(query):
    try:
        params = {"action": "query", "list": "search", "format": "json",
                  "srsearch": query, "srlimit": MAX_PER_SOURCE}
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

def search_tavily(query):
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return []
    try:
        resp = requests.post("https://api.tavily.com/search",
                             json={"api_key": api_key, "query": query,
                                   "max_results": MAX_PER_SOURCE},
                             timeout=SEARCH_TIMEOUT)
        resp.raise_for_status()
        return [{
            "source": "Tavily", "title": r.get("title", ""),
            "url": r.get("url", ""), "summary": r.get("content", ""),
            "weight": 0.8
        } for r in resp.json().get("results", []) if r.get("title")]
    except Exception:
        return []

def search_github(query):
    try:
        params = {"q": query, "sort": "stars", "order": "desc", "per_page": MAX_PER_SOURCE}
        resp = requests.get("https://api.github.com/search/repositories",
                            params=params, timeout=SEARCH_TIMEOUT,
                            headers={"Accept": "application/vnd.github.v3+json",
                                     "User-Agent": "researcher-cli"})
        resp.raise_for_status()
        return [{
            "source": "GitHub", "title": item.get("full_name", ""),
            "url": item.get("html_url", ""),
            "summary": item.get("description", "") or "",
            "weight": 0.85, "stars": item.get("stargazers_count", 0)
        } for item in resp.json().get("items", []) if item.get("full_name")]
    except Exception:
        return []

def search_npm(query):
    try:
        params = {"text": query, "size": MAX_PER_SOURCE}
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

def search_mdn(query):
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
        } for doc in documents[:MAX_PER_SOURCE] if doc.get("title")]
    except Exception:
        return []

def search_hn(query):
    try:
        params = {"query": query, "tags": "story", "hitsPerPage": MAX_PER_SOURCE}
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

# ==================== SOURCE MAP ====================

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

# ==================== HELPERS ====================

def fetch_jina_content(url):
    try:
        resp = requests.get(f"https://r.jina.ai/{url}", timeout=JINA_TIMEOUT)
        resp.raise_for_status()
        return resp.text[:1000]
    except Exception:
        return None

def calculate_confidence(result, all_results):
    score = result.get("weight", 0.5) * 50
    similar = len(all_results) - 1
    score += min(similar * 5, 20)
    if result.get("source") == "SO" and result.get("answered"):
        score += 15
    if result.get("source") == "GitHub" and result.get("stars", 0) > 1000:
        score += 10
    if result.get("source") == "MDN":
        score += 10
    if result.get("summary") and len(result.get("summary", "")) > 100:
        score += 10
    year = datetime.now().year
    title = result.get("title", "")
    if str(year) in title or str(year - 1) in title:
        score += 5
    return min(int(score), 100)

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

def print_results_text(results, stack=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if stack:
        print(f"🔍 Detected stack: {', '.join(stack)}\n")
    for i, r in enumerate(results, 1):
        conf = r.get("confidence", 0)
        icon = "🟢" if conf >= 70 else "🟡" if conf >= 40 else "🔴"
        extra = ""
        if r.get("stars"):
            extra = f" ⭐{r['stars']}"
        print(f"{i}. {icon} [{r['source']}] {r.get('title', 'N/A')}{extra} (confidence: {conf}%)")
        print(f"   URL: {r.get('url', 'N/A')}")
        content = r.get("content") or r.get("summary") or "No content"
        print(f"   Summary: {content[:300]}...")
        print()

def print_results_ai(results, stack=None, query=""):
    """AI context window icin optimize edilmis markdown"""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"## Research Results for \"{query}\"")
    if stack:
        print(f"Stack: {', '.join(stack)}")
    print()
    for i, r in enumerate(results, 1):
        conf = r.get("confidence", 0)
        print(f"### {i}. [{r['source']}] {r.get('title', 'N/A')}")
        print(f"URL: {r.get('url', 'N/A')}")
        print(f"Confidence: {conf}%")
        if r.get("stars"):
            print(f"Stars: {r['stars']}")
        content = r.get("content") or r.get("summary") or ""
        if content:
            print(f"Summary: {content[:400]}")
        print()

def main():
    parser = argparse.ArgumentParser(description="AI-native fast research engine")
    parser.add_argument("query", nargs="+", help="Search query")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--ai", action="store_true", help="AI-friendly markdown output")
    parser.add_argument("--fast", action="store_true", help="Skip content extraction")
    parser.add_argument("--deep", action="store_true", help="Fetch content for all results")
    parser.add_argument("--expand", action="store_true", help="Expand query with tech terms")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Max results")
    parser.add_argument("--sources", type=str, default="all",
                        help="Comma-separated sources: ddg,so,wiki,tavily,github,npm,mdn,hn")
    args = parser.parse_args()

    query = " ".join(args.query)
    if args.expand:
        query = expand_query(query)

    stack = detect_stack()

    global MAX_PER_SOURCE
    MAX_PER_SOURCE = 4 if args.deep else 2

    # Source filtering
    if args.sources == "all":
        selected_sources = list(SOURCE_MAP.keys())
    else:
        selected_sources = [s.strip().lower() for s in args.sources.split(",") if s.strip().lower() in SOURCE_MAP]

    cache_key = f"{query}:{args.fast}:{args.deep}:{','.join(sorted(selected_sources))}:{','.join(stack)}"
    cached = get_cache(cache_key)
    if cached:
        if args.json:
            print(json.dumps(cached, ensure_ascii=False, indent=2))
        elif args.ai:
            print_results_ai(cached, stack, query)
        else:
            print_results_text(cached, stack)
        return

    enriched = f"{query} {' '.join(stack[:3])}" if stack else query

    # Build search tasks with appropriate query per source
    searches = []
    for src in selected_sources:
        func = SOURCE_MAP[src]
        # Wikipedia ve Tavily saf sorguyla, digerleri stack-enriched
        if src in ("wiki", "tavily"):
            searches.append((func, query))
        else:
            searches.append((func, enriched))

    all_results = []
    with ThreadPoolExecutor(max_workers=len(searches)) as ex:
        futures = [ex.submit(f, q) for f, q in searches]
        try:
            for future in as_completed(futures, timeout=SEARCH_TIMEOUT + 5):
                try:
                    all_results.extend(future.result())
                except Exception:
                    continue
        except Exception:
            pass

    results = deduplicate(all_results)[:args.limit]
    if not results:
        msg = {"error": "No results found", "query": query}
        if args.json:
            print(json.dumps(msg))
        elif args.ai:
            print(f"## Research Results for \"{query}\"\n\nNo results found.")
        else:
            print("No results found.")
        return

    for r in results:
        r["confidence"] = calculate_confidence(r, results)
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

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    elif args.ai:
        print_results_ai(results, stack, query)
    else:
        print_results_text(results, stack)

if __name__ == "__main__":
    main()