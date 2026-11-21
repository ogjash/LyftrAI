# 1. Live URLs

- Frontend: https://lyftr-ai-chat.vercel.app
- Backend: https://lyftrai.onrender.com

# 2. Run locally: with Docker and without

## Docker

```bash
cp .env.example .env
make up
```

Open http://localhost:3000. The backend is at http://localhost:8000.

```bash
make down
```

## Without Docker

Backend:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
LLM_API_KEYS=key_1,key_2 DATABASE_URL=sqlite:///./app.db ENABLE_FAILURE_SIMULATION=true uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev -- --port 3000
```

# 3. Design decisions: key fallback, caching, SQLite session storage

The backend reads ordered API keys and assigns stable IDs in the form `key_1`, `key_2`, and so on. Each key is attempted once, and provider 429, quota, and 5xx failures advance to the next key. LiteLLM is enabled with local caching and the application also stores exact model-plus-message cache entries in SQLite, so cache hits retain their usage values and remain identical across sessions.

SQLite is the only datastore. Messages are stored by `session_id` and returned oldest first. The `/chat` endpoint sends the system prompt, stored history, and the new message to the model, preserving multi-turn context. Failed and validation requests do not write chat history.

# 4. Verification: how to see failover, cache hits and per-message token usage

Start the app, send "What is the capital of France?" once, then send it in a second browser session or after a page reload. The second response should show `LLM_CACHE` and use about the same input token count.

Test failover:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-Simulate-Failure: key_1=429" \
  -d '{"session_id":"verify-failover","message":"Say hello"}'
```

Test a full provider failure:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-Simulate-Failure: *=429" \
  -d '{"session_id":"verify-all-down","message":"Say hello"}'
```

View history:

```bash
curl http://localhost:8000/sessions/verify-failover/messages
```

# 5. Setup Used: your editor and AI tools

- VS Code
- Copilot SDK
- Docker Compose
- React, Vite, FastAPI, LiteLLM, and SQLite

# 6. Bonus features (if any): what you added beyond the requirements and why

- Responsive chat workspace with a collapsible system prompt.
- Shadcn-style reusable React UI primitives.
- Persistent response cache in SQLite.
