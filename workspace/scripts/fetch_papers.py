#!/usr/bin/env python3
"""Fetch papers from ArXiv with Haiku query generation and Sonnet extraction.

Usage:
    python fetch_papers.py --task state/current_task.json --output state/papers.json
"""

import argparse
import json
import logging
import time
from pathlib import Path

import arxiv
from anthropic import Anthropic

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

client = Anthropic()

# ── Domain search terms (fallback if Haiku unavailable) ──────────
DEFAULT_QUERIES = [
    "contextual biasing ASR",
    "hotword detection speech recognition",
    "end-to-end ASR biasing dual encoder",
    "FAISS audio text retrieval",
    "CIF continuous integrate fire biasing",
]


def generate_queries(task: dict, n: int = 5) -> list[str]:
    """Generate ArXiv search queries using Haiku.

    Args:
        task: Task definition with query and tech_direction.
        n: Number of queries to generate.

    Returns:
        List of search query strings.
    """
    prompt = (
        f"Generate {n} ArXiv search queries for this research topic.\n"
        f"Topic: {task['query']}\n"
        f"Direction: {task['tech_direction']}\n\n"
        f"Return a JSON array of strings, nothing else."
    )
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system="Return only a JSON array of search query strings.",
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        queries = json.loads(text)
        if isinstance(queries, list) and all(isinstance(q, str) for q in queries):
            log.info("Generated %d queries via Haiku", len(queries))
            return queries
    except Exception as e:
        log.warning("Haiku query generation failed: %s. Using defaults.", e)
    return DEFAULT_QUERIES[:n]


def search_arxiv(queries: list[str], max_per_query: int = 10) -> list[dict]:
    """Search ArXiv for papers matching the queries.

    Args:
        queries: List of search query strings.
        max_per_query: Maximum results per query.

    Returns:
        Deduplicated list of paper dicts.
    """
    seen_ids: set[str] = set()
    papers: list[dict] = []

    arxiv_client = arxiv.Client()

    for query in queries:
        log.info("Searching ArXiv: %s", query)
        search = arxiv.Search(
            query=query,
            max_results=max_per_query,
            sort_by=arxiv.SortCriterion.Relevance,
        )
        try:
            for result in arxiv_client.results(search):
                paper_id = result.entry_id.split("/")[-1]
                if paper_id in seen_ids:
                    continue
                seen_ids.add(paper_id)
                papers.append({
                    "arxiv_id": paper_id,
                    "title": result.title,
                    "abstract": result.summary[:2000],
                    "authors": ", ".join(a.name for a in result.authors[:5]),
                    "published": result.published.strftime("%Y-%m-%d"),
                    "url": result.entry_id,
                })
        except Exception as e:
            log.warning("ArXiv search failed for '%s': %s", query, e)
        time.sleep(1)  # Rate limit courtesy

    log.info("Fetched %d unique papers", len(papers))
    return papers


def score_relevance(papers: list[dict], task: dict) -> list[dict]:
    """Score paper relevance using Sonnet. Filter by threshold.

    Args:
        papers: List of paper dicts with abstract.
        task: Task definition for context.

    Returns:
        Papers with relevance_score >= 6, sorted by score descending.
    """
    if not papers:
        return []

    # Build batch prompt (process in chunks to stay within context)
    chunk_size = 10
    scored: list[dict] = []

    for i in range(0, len(papers), chunk_size):
        chunk = papers[i:i + chunk_size]
        paper_list = "\n\n".join(
            f"[{j}] {p['title']}\n{p['abstract'][:500]}"
            for j, p in enumerate(chunk)
        )
        prompt = (
            f"Research topic: {task['query']}\n"
            f"Direction: {task['tech_direction']}\n\n"
            f"Rate each paper's relevance (0-10) to this research.\n\n"
            f"{paper_list}\n\n"
            f"Return JSON array: [{{\"index\": 0, \"score\": 8, "
            f"\"method\": \"...\", \"dataset\": \"...\", \"key_metric\": \"...\"}}]"
        )
        try:
            resp = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2000,
                system="Return only valid JSON array. No markdown fences.",
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            scores = json.loads(text)
            for s in scores:
                idx = s.get("index", -1)
                if 0 <= idx < len(chunk):
                    paper = chunk[idx].copy()
                    paper["relevance_score"] = s.get("score", 0)
                    paper["method"] = s.get("method", "")
                    paper["dataset"] = s.get("dataset", "")
                    paper["key_metric"] = s.get("key_metric", "")
                    scored.append(paper)
        except Exception as e:
            log.warning("Sonnet scoring failed for chunk %d: %s", i, e)
            for p in chunk:
                p["relevance_score"] = 5
                scored.append(p)

    # Filter and sort
    filtered = [p for p in scored if p.get("relevance_score", 0) >= 6]
    filtered.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
    log.info("Scored %d papers, %d above threshold", len(scored), len(filtered))
    return filtered


def main() -> None:
    """Entry point: fetch, score, and save papers."""
    parser = argparse.ArgumentParser(description="Fetch papers from ArXiv")
    parser.add_argument("--task", type=Path, required=True, help="Path to current_task.json")
    parser.add_argument("--output", type=Path, required=True, help="Output path for papers.json")
    parser.add_argument("--max-results", type=int, default=30, help="Max papers to fetch")
    args = parser.parse_args()

    task = json.loads(args.task.expanduser().read_text())
    log.info("Task: %s | Direction: %s", task["query"], task["tech_direction"])

    queries = generate_queries(task)
    max_per_query = max(5, args.max_results // len(queries))
    papers = search_arxiv(queries, max_per_query=max_per_query)
    scored = score_relevance(papers, task)

    output_path = args.output.expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(scored, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("Saved %d papers to %s", len(scored), output_path)


if __name__ == "__main__":
    main()
