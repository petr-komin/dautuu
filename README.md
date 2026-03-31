# dautuu

Personal AI assistant with long-term memory. Chat with multiple LLM providers, and the assistant remembers context across conversations via RAG (retrieval-augmented generation) and automatic summarization.

## Features

- **Multi-provider chat** — Together.ai, OpenAI, Anthropic, Ollama (local)
- **Long-term memory** — messages and conversation summaries are embedded and retrieved via pgvector
- **Streaming responses** — SSE with live markdown rendering
- **Usage tracking** — token counts and cost per model/day, visible in `/usage`
- **Auth** — JWT-based login, per-user data isolation

## Stack

| Layer | Tech |
|---|---|
| Frontend | React + TypeScript + Vite + Tailwind v4 |
| Backend | FastAPI (async) + SQLAlchemy 2.0 |
| Database | PostgreSQL + pgvector |
| Embeddings | Together.ai `multilingual-e5-large-instruct` |
| Infra | Docker Compose |

## Quick start

**Prerequisites:** Docker, Node.js 20+, PostgreSQL with pgvector extension

```bash
# 1. Clone
git clone https://github.com/petr-komin/dautuu.git
cd dautuu

# 2. Configure
cp .env.example .env
# Edit .env — set SECRET_KEY, TOGETHER_API_KEY (or other provider keys), DATABASE_URL

# 3. Start backend
docker compose -f docker-compose.host-db.yml up -d

# 4. Create DB tables (first run only)
docker exec -it dautuu-backend-1 python -c "import asyncio; from app.db.init_db import init_db; asyncio.run(init_db())"

# 5. Create a user
docker exec -it dautuu-backend-1 python scripts/create_user.py

# 6. Start frontend
cd web && npm install && npm run dev
```

Frontend runs at `http://localhost:5173`, backend at `http://localhost:8001`.

## Environment variables

See [`.env.example`](.env.example) for all options. Minimum required:

```env
SECRET_KEY=<openssl rand -hex 32>
DATABASE_URL=postgresql+asyncpg://user:pass@host/db
TOGETHER_API_KEY=<your key>
```

## Project structure

```
backend/
  app/
    api/v1/endpoints/   # chat, auth, providers, usage
    services/
      llm/router.py     # unified LLM interface (Together/OpenAI/Anthropic/Ollama)
      rag/              # embeddings, memory retrieval, summarization
      usage/            # token logging, pricing
    db/models.py        # User, Conversation, Message, UsageLog
web/src/
  pages/                # ChatPage, SettingsPage, UsagePage
  api/                  # typed API clients
  components/           # layout, UI primitives
```

## License

MIT
