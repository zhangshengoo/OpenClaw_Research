#!/usr/bin/env python3
"""Generate a literature survey via RAG retrieval from ChromaDB + Sonnet.

Usage:
    python generate_survey.py --task state/current_task.json --db-path data/chroma \
        --output state/survey.md --top-k 12
"""

import argparse
import json
import logging
from pathlib import Path

import chromadb
import voyageai
from anthropic import Anthropic

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

COLLECTION_NAME = "papers"

client = Anthropic()


def retrieve_papers(
    task: dict,
    db_path: Path,
    top_k: int = 12,
) -> list[dict]:
    """Retrieve most relevant papers from ChromaDB via query embedding.

    Args:
        task: Task definition with query and tech_direction.
        db_path: Path to ChromaDB storage.
        top_k: Number of papers to retrieve.

    Returns:
        List of retrieved paper dicts with document text and metadata.
    """
    vo = voyageai.Client()
    chroma = chromadb.PersistentClient(path=str(db_path))
    coll = chroma.get_or_create_collection(COLLECTION_NAME)

    query_text = f"{task['query']} {task['tech_direction']}"
    log.info("Generating query embedding for: %s", query_text[:80])

    result = vo.embed([query_text], model="voyage-3.5", input_type="query")
    query_embedding = result.embeddings[0]

    results = coll.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["documents", "metadatas"],
    )

    papers = []
    if results["documents"] and results["documents"][0]:
        for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
            papers.append({
                "text": doc,
                "title": meta.get("title", ""),
                "authors": meta.get("authors", ""),
                "arxiv_id": meta.get("arxiv_id", ""),
                "relevance": meta.get("relevance", 0),
                "method": meta.get("method", ""),
            })

    log.info("Retrieved %d papers from ChromaDB", len(papers))
    return papers


def generate_survey(task: dict, papers: list[dict]) -> str:
    """Generate a comprehensive survey using Sonnet.

    Args:
        task: Task definition for context.
        papers: Retrieved papers with text and metadata.

    Returns:
        Survey text in Markdown format.
    """
    paper_context = "\n\n---\n\n".join(
        f"**[{p['arxiv_id']}] {p['title']}** ({p['authors']})\n"
        f"Method: {p.get('method', 'N/A')}\n\n{p['text'][:1500]}"
        for p in papers
    )

    target = task.get("target_metrics", {})
    prompt = (
        f"Write a comprehensive literature survey (~3000 words) for:\n\n"
        f"**Research Question:** {task['query']}\n"
        f"**Technical Direction:** {task['tech_direction']}\n"
        f"**Target Metrics:** CER ≤ {target.get('cer', 'N/A')}, "
        f"Latency P95 ≤ {target.get('latency_p95_ms', 'N/A')}ms, "
        f"Recall@10 ≥ {target.get('recall_10', 'N/A')}\n\n"
        f"## Retrieved Papers\n\n{paper_context}\n\n"
        f"## Requirements\n\n"
        f"1. Compare methods, datasets, and reported metrics\n"
        f"2. Identify the most promising approaches for our targets\n"
        f"3. Highlight key baselines: DualEncoder, CIF-biasing, TCPGen\n"
        f"4. Recommend a concrete experimental strategy\n"
        f"5. Use Markdown with tables for metric comparisons\n"
        f"6. Cite papers by their ArXiv ID"
    )

    log.info("Generating survey with Sonnet (context: %d chars)", len(prompt))
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        system=(
            "You are an ASR research expert. Write a rigorous academic survey "
            "in Markdown. Be specific about methods, metrics, and comparisons. "
            "Always cite papers by ArXiv ID."
        ),
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text


def main() -> None:
    """Entry point: retrieve papers and generate survey."""
    parser = argparse.ArgumentParser(description="Generate RAG literature survey")
    parser.add_argument("--task", type=Path, required=True, help="Path to current_task.json")
    parser.add_argument("--db-path", type=Path, required=True, help="ChromaDB storage path")
    parser.add_argument("--output", type=Path, required=True, help="Output survey path")
    parser.add_argument("--top-k", type=int, default=12, help="Number of papers to retrieve")
    args = parser.parse_args()

    task = json.loads(args.task.expanduser().read_text())
    papers = retrieve_papers(task, args.db_path.expanduser(), top_k=args.top_k)

    if not papers:
        log.error("No papers retrieved — cannot generate survey")
        raise SystemExit(1)

    survey = generate_survey(task, papers)

    output_path = args.output.expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(survey, encoding="utf-8")
    log.info("Survey saved to %s (%d chars)", output_path, len(survey))


if __name__ == "__main__":
    main()
