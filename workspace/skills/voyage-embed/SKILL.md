---
name: voyage-embed
description: "Voyage AI embedding conventions: batch limits, input_type distinction, ChromaDB schema"
user-invocable: false
---

# Voyage Embedding Conventions

## API Usage

- Model: `voyage-3.5`
- Batch size: ≤ 64 texts per call
- Text truncation: ≤ 2000 characters

## Input Type Distinction

- **Storage** (embedding papers for indexing): `input_type="document"`
- **Retrieval** (embedding queries for search): `input_type="query"`

## ChromaDB Schema

Collection name: `papers`

```python
coll.upsert(
    ids=["arxiv_2401.12345", ...],
    embeddings=[...],
    documents=["abstract text...", ...],
    metadatas=[{
        "title": "Paper Title",
        "authors": "Author1, Author2",
        "arxiv_id": "2401.12345",
        "year": 2024,
        "relevance": 8,
    }, ...],
)
```

## Environment

Requires `VOYAGE_API_KEY` environment variable.
