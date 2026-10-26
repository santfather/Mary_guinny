# Project Instructions for Claude

## Knowledge Base

This workspace has a curated knowledge base of **656 AI/LLM repositories** in `AI_Tools_Analysis.md`.

**When starting any new project or suggesting tools:**
1. Check `AI_Tools_Analysis.md` first
2. Prefer tools listed in the "🚀 Рекомендации по интеграции" section
3. Justify your choice with the star count and description from the file

---

## Quick Reference — Best Tools by Task

### Web Scraping / Crawling
- **firecrawl** (⭐136k) — search, scrape, interact with web at scale. API-first.
- **Scrapling** (⭐65k) — adaptive scraping framework, has MCP server
- **browser-use** (⭐100k) — browser automation for AI agents

### Memory & Persistence
- **mem0** (⭐59k) — universal memory layer for AI agents
- **claude-mem** (⭐83k) — persistent context across sessions
- **mempalace** (⭐56k) — best-benchmarked open-source AI memory

### Context & Token Optimization
- **headroom** (⭐46k) — compress context 60-95% before sending to LLM
- **context7** (⭐57k) — up-to-date docs for LLMs via MCP server

### LLM Gateway / API
- **litellm** (⭐51k) — unified gateway for 100+ LLM APIs, cost tracking

### Agent Frameworks
- **langchain** (⭐139k) — industry standard, chains + agents + RAG
- **crewAI** (⭐54k) — role-playing multi-agent orchestration
- **agno** (⭐40k) — build, run, manage agent platforms
- **autogen** (⭐59k) — Microsoft's agentic AI framework

### Document Processing
- **markitdown** (⭐157k) — convert any file/doc to Markdown (Microsoft)
- **MinerU** (⭐68k) — PDF/Office to LLM-ready markdown/JSON

### RAG
- **ragflow** (⭐83k) — RAG engine with agent capabilities
- **llama_index** (⭐50k) — document agents and OCR platform

### MCP Servers
- **context7** — docs as MCP server
- **Scrapling** — scraping as MCP server
- **chrome-devtools-mcp** (⭐44k) — Chrome DevTools for coding agents

---

## Project Structure (Current)

```
agent-workspace/
├── github-crawler/          # GitHub Stars Crawler (Python, async httpx)
│   ├── crawler/
│   │   ├── github_client.py
│   │   ├── search.py
│   │   ├── repository_filter.py
│   │   └── formatter.py
│   ├── tests/
│   ├── main.py
│   └── requirements.txt
└── AI_Tools_Analysis.md     # Knowledge base (656 repos, 12 categories)
```

---

## Coding Standards

- Python: async/await, type hints, handle None values defensively
- Always add `os.makedirs('dir', exist_ok=True)` before writing files
- Use `python-dotenv` for env vars, never hardcode tokens
- Tests: use `pytest-asyncio` for async tests, patch with `unittest.mock.AsyncMock`
- Dependencies: pin major versions in requirements.txt

---

## Before Suggesting Any Library

Ask yourself:
1. Is it in `AI_Tools_Analysis.md`? → prefer it over unknown alternatives
2. Stars > 10k? → safe choice
3. Last updated < 6 months? → actively maintained
