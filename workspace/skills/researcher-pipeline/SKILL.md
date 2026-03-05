---
name: researcher-pipeline
description: "ASR literature survey pipeline: ArXiv fetch, Voyage embedding, ChromaDB storage, RAG survey generation"
user-invocable: false
---

# Research Pipeline

Execute the full literature survey pipeline. Read the task definition, fetch
papers from ArXiv, embed them with Voyage AI, store in ChromaDB, and generate
a comprehensive survey document.

## Step 1: Read task definition

```bash
cat ~/.openclaw/workspace/state/current_task.json
```

Extract `query` and `tech_direction` for search.

## Step 2: Fetch papers from ArXiv

```bash
cd ~/.openclaw/workspace
python scripts/fetch_papers.py \
  --task state/current_task.json \
  --output state/papers.json \
  --max-results 30
```

Expected output: `state/papers.json` with an array of paper objects
(title, abstract, authors, arxiv_id, relevance_score).

## Step 3: Embed papers into ChromaDB

```bash
cd ~/.openclaw/workspace
python scripts/embed_papers.py \
  --papers state/papers.json \
  --db-path data/chroma
```

Expected output: papers stored in ChromaDB at `data/chroma/`.

## Step 4: Generate survey via RAG

```bash
cd ~/.openclaw/workspace
python scripts/generate_survey.py \
  --task state/current_task.json \
  --db-path data/chroma \
  --output state/survey.md \
  --top-k 12
```

Expected output: `state/survey.md` — a ~3000-word survey covering methods,
datasets, metrics, baselines, and recommendations.

## Completion

After all steps succeed, reply: `ANNOUNCE_SKIP`

If any step fails, write the error to `state/error.json` and reply: `ANNOUNCE_SKIP`
