# Legal AI Chatbot


## Quick start

1. (Optional) Create python virtual environment

```bash
python -m venv .venv
```


2. Install the following dependencies

```bash
pip install uv ## pip written in rust
uv pip install chromadb FlagEmbedding elasticsearch python-docx openai neo4j python-dotenv flask werkzeug requests crawl4ai
```

3. Start the Flask API

```bash
.\.venv\Scripts\python.exe backend/app.py
```

4. Start the React admin UI

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server proxies `/api` to `http://127.0.0.1:5000`.

5. Run backend tests

```bash
.\.venv\Scripts\python.exe -m pytest
```

## DOCX import metadata

Admin DOCX upload can be submitted with only a file. The backend stores the
original DOCX under `data/raw/<import_batch_id>/`, parses text for deterministic
hints, then calls DeepSeek with an OpenAI-compatible client when
`DEEPSEEK_API_KEY` is available:

```env
DEEPSEEK_API_KEY=replace-with-your-deepseek-key
DEEPSEEK_MODEL_METADATA=deepseek-v4-flash
VBPL_CRAWL_ENABLED=true
CRAWL4_AI_BASE_DIRECTORY=.crawl4ai
PLAYWRIGHT_BROWSERS_PATH=.playwright-browsers
```

When the upload checkbox `Van ban phap luat` is enabled, VBPL enrichment is
best-effort. Missing fields are imported anyway and marked for admin review.

## Local Elasticsearch config

For Milestone 3 BM25 indexing with a local Elasticsearch quickstart cluster,
set these values in `.env` without committing real secrets:

```env
BM25_PROVIDER=elasticsearch
ELASTICSEARCH_URL=http://localhost:9200
ELASTICSEARCH_INDEX=legal_chunks_bm25

# Prefer API key auth for the local quickstart output.
ELASTICSEARCH_API_KEY=replace-with-your-local-api-key

# Alternative basic auth if you do not use API keys.
ELASTICSEARCH_USERNAME=elastic
ELASTICSEARCH_PASSWORD=replace-with-your-local-password
```

Publish also writes to Neo4j and Chroma. For a real publish run, configure
`NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `CHROMA_PATH`, and
`CHROMA_COLLECTION` in `.env`.

For Neo4j Aura/cloud, use the database-specific values from the Aura console:

```env
NEO4J_URI=neo4j+s://your-instance.databases.neo4j.io
NEO4J_USERNAME=your-database-username
NEO4J_PASSWORD=replace-with-your-neo4j-password
NEO4J_DATABASE=your-database-name
```
