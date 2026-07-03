# Legal AI Chatbot


## Quick start

1. (Optional) Create python virtual environment

```bash
python -m venv .venv
```


2. Install the following dependencies

```bash
pip install uv ## pip written in rust
uv pip install chromadb FlagEmbedding python-docx openai neo4j python-dotenv flask werkzeug streamlit requests
```

3. Start the Flask API

```bash
python backend/app.py
```

4. Start the Streamlit admin UI

```bash
streamlit run frontend/streamlit_app.py
```

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
