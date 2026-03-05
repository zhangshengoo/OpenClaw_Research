#!/usr/bin/env python3
"""Embed papers into ChromaDB using Voyage AI voyage-3.5.

Usage:
    python embed_papers.py --papers state/papers.json --db-path data/chroma
"""

import argparse
import json
import logging
from pathlib import Path

import chromadb
import voyageai

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

BATCH_SIZE = 64
MAX_TEXT_LEN = 2000
COLLECTION_NAME = "papers"


def embed_and_store(papers: list[dict], db_path: Path) -> int:
    """Embed paper abstracts and upsert into ChromaDB.

    Args:
        papers: List of paper dicts with arxiv_id, title, abstract, etc.
        db_path: Path to ChromaDB persistent storage.

    Returns:
        Number of papers successfully embedded.
    """
    if not papers:
        log.warning("No papers to embed")
        return 0

    vo = voyageai.Client()
    chroma = chromadb.PersistentClient(path=str(db_path))
    coll = chroma.get_or_create_collection(COLLECTION_NAME)

    total = 0
    for i in range(0, len(papers), BATCH_SIZE):
        batch = papers[i:i + BATCH_SIZE]

        texts = [
            f"{p['title']}\n\n{p['abstract'][:MAX_TEXT_LEN]}"
            for p in batch
        ]
        ids = [f"arxiv_{p['arxiv_id']}" for p in batch]
        metadatas = [
            {
                "title": p["title"],
                "authors": p.get("authors", ""),
                "arxiv_id": p["arxiv_id"],
                "published": p.get("published", ""),
                "relevance": p.get("relevance_score", 0),
                "method": p.get("method", ""),
                "dataset": p.get("dataset", ""),
            }
            for p in batch
        ]

        log.info("Embedding batch %d-%d (%d papers)", i, i + len(batch), len(batch))
        result = vo.embed(texts, model="voyage-3.5", input_type="document")
        embeddings = result.embeddings

        coll.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas,
        )
        total += len(batch)

    log.info("Embedded %d papers into ChromaDB at %s", total, db_path)
    return total


def main() -> None:
    """Entry point: load papers and embed into ChromaDB."""
    parser = argparse.ArgumentParser(description="Embed papers into ChromaDB")
    parser.add_argument("--papers", type=Path, required=True, help="Path to papers.json")
    parser.add_argument("--db-path", type=Path, required=True, help="ChromaDB storage path")
    args = parser.parse_args()

    papers_path = args.papers.expanduser()
    db_path = args.db_path.expanduser()
    db_path.mkdir(parents=True, exist_ok=True)

    papers = json.loads(papers_path.read_text())
    log.info("Loaded %d papers from %s", len(papers), papers_path)

    count = embed_and_store(papers, db_path)
    log.info("Done: %d papers embedded", count)


if __name__ == "__main__":
    main()
