# 🔬 Researcher

A fast, sourced suggestion engine that keeps AI coding assistants from hallucinating (and going full-derp) during research. Not a deep-research tool — think "senior engineer consult in 15 seconds."

## Why?

Cursor, Copilot, Claude, and friends are great at writing code — but when you ask them to research, things get weird:

- 🤥 **Hallucination** — models "remember" APIs, docs, and packages that never existed (or died years ago).
- 📅 **Stale sources** — training cutoffs mean they recommend versions of libraries that are 3 majors outdated.
- 🔁 **Looping** — the assistant re-reads the same 5 blog posts and calls it research.
- 🐌 **Slow** — deep-research pipelines crawl hundreds of URLs and take minutes for what you needed seconds ago.

Researcher answers the *right way*: real search results, from real sources, in seconds — so the model (or you) stops guessing and starts reading.

## Features

- ⚡ **Parallel search** — all sources queried concurrently; ~4x faster than the sequential pipeline.
- 🎯 **Confidence scoring** — every result is rated 🟢 (fresh, authoritative), 🟡 (okay, worth a look), or 🔴 (old, thin, or unreliable).
- 🔎 **Multi-source search** — DuckDuckGo first, StackExchange for technical gotchas, Wikipedia for concepts, Tavily as an optional fallback.
- 📦 **Stack auto-detection** — reads `package.json` / `requirements.txt` and biases results toward your actual toolchain.
- 📖 **Jina Reader content extraction** — gets clean Markdown from each result, no scraping setup needed.
- 🧠 **Smart cache** — repeat queries hit the local cache and return instantly.
- 🔑 **No API keys required** — works out of the box. Tavily key is purely optional.
- 🧯 **Salaklaşma koruması (hallucination shield)** — every claim is backed by a real, current URL before the assistant says anything.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Optional — copy `.env.example` to `.env` to enable the Tavily fallback or raise the StackExchange rate limit:

```
TAVILY_API_KEY=your_tavily_key
STACKEXCHANGE_KEY=your_se_key   # optional, raises the SO rate limit
```

> Get a free Tavily key at [app.tavily.com](https://app.tavily.com).

## Usage

```bash
# default: balanced — parallel search, 6 results
python smart_suggest.py 'Next.js rate limiting'

# --fast: skip Jina content, snippet-only, fewer results
python smart_suggest.py --fast 'React 19 server actions'

# --deep: more results per source, full content read
python smart_suggest.py --deep 'postgres connection pool tuning'

# --json: machine-readable output (great for piping into Cursor/Copilot)
python smart_suggest.py --json 'httpx async vs requests'

# --limit N: cap total results (1-12)
python smart_suggest.py --limit 3 'python type hints best practices'

# combine flags freely
python smart_suggest.py --fast --limit 4 --json 'stripe webhooks idempotency'
```

| Flag | Effect |
|------|--------|
| `--fast` | Skip Jina content reading, use snippet-only summaries |
| `--deep` | More results per source + full content extraction |
| `--json` | Output structured JSON instead of pretty-print |
| `--limit N` | Cap total results (default 6, max 12) |

Each result includes its source tag, confidence score, title, URL, and the first 500 characters of clean content:

```
1. 🟢 [DDG] Next.js Rate Limiting Setup 2026 (confidence: 85%)
   URL: https://nextjslaunchpad.com/article/nextjs-rate-limiting-api-routes-server-actions-ai-endpoints
   Summary: Every Next.js app that exposes API routes or server actions to the internet...

2. 🟡 [SO] Make Python wait for rate limit Twitter API using requests library (confidence: 60%)
   URL: https://stackoverflow.com/questions/77921886/...
   Summary: Content unavailable...

3. 🟢 [Wiki] Rate limiter (confidence: 90%)
   URL: https://en.wikipedia.org/wiki/Rate_limiter
   Summary: | Rate limiter | ...
```

Up to **2 results per source, 6 total** (tunable with `--deep` / `--limit`). If one source fails, it's skipped silently and the next one takes over.

## Roadmap

- [x] **CLI MVP** — multi-source search + content extraction
- [x] **Parallel search** — concurrent queries for ~4x speedup
- [x] **Confidence scoring** — 🟢🟡🔴 source & freshness ratings
- [x] **Cache** — repeat queries served from local disk
- [ ] **Context enrichment** — feed results directly into your agent's context window
- [ ] **MCP Server** — expose as a Model Context Protocol tool
- [ ] **IDE plugin** — inline research for Cursor / Copilot chat

## Contributing

Contributions are welcome, bugs are welcome too (unironically).

**Found a bug or missing feature?**
1. Check if the issue already exists.
2. [Open an issue](https://github.com/NebulaDev7/researcher/issues/new) with: what you searched, what happened, what you expected.
3. Bonus points for full command lines and output snippets.

**Want to ship code?**
1. Fork the repo and create a branch: `git checkout -b fe/your-feature`
2. Keep it simple and readable — no over-engineering.
3. Test with a real query: `python smart_suggest.py 'something you actually need'`
4. Open a PR. Explain what changed and why.

## License

This project is licensed under the [Apache License 2.0](LICENSE).