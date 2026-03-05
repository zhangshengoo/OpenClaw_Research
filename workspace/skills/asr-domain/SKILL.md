---
name: asr-domain
description: "ASR domain knowledge: evaluation metrics, ArXiv search terms, recommended baselines for hotword recall"
user-invocable: false
---

# ASR Domain Knowledge

## Target Metrics

| Metric | Target | Description |
|--------|--------|-------------|
| CER | ≤ 0.08 | Character Error Rate |
| Latency P95 | ≤ 50ms | 95th percentile inference latency |
| Recall@10 | ≥ 0.90 | Hotword recall at top-10 candidates |
| Vocabulary | 10k+ | Hotword vocabulary size |

## Recommended Baselines

- **DualEncoder**: Audio-text alignment via dual-encoder architecture + FAISS retrieval
- **CIF-biasing**: Continuous Integrate-and-Fire with hotword biasing
- **TCPGen**: Tree Constrained Pointer Generator for contextual biasing

## ArXiv Search Terms

Use these terms for literature search:

- `contextual biasing ASR`
- `hotword detection speech recognition`
- `end-to-end ASR biasing`
- `dual encoder audio text alignment`
- `FAISS speech retrieval`
- `CIF continuous integrate fire`
- `tree constrained pointer generator`
- `personalized speech recognition`

## Key Technical Directions

- AudioEncoder + LLM fusion
- FAISS-based audio-text retrieval
- Hotword recall and contextual biasing
- Streaming ASR with low-latency biasing

## Evaluation Protocol

- Test on standard benchmarks (LibriSpeech, AISHELL, internal hotword sets)
- Report CER on both general and hotword-heavy test sets
- Measure latency under realistic vocabulary sizes (10k+)
- Use random seed for reproducibility
