---
name: critic-analyzer
description: "Experiment critic: convergence judgment, gap analysis, improvement suggestions with JSON schema"
user-invocable: false
---

# Critic Analyzer

## Input

Read all experiment results and the task definition:

```bash
cat ~/.openclaw/workspace/state/current_task.json
ls ~/.openclaw/workspace/state/results_*.json
```

## Analysis Framework

1. Compare current metrics against `target_metrics` in current_task.json.
2. Compute delta from previous iteration (if available).
3. Check convergence: delta < `min_delta` for 2 consecutive rounds, OR targets met.
4. If not converged, propose concrete improvements.

## Output Schema

Write to `state/critic_N.json`:

```json
{
  "converged": false,
  "gap_analysis": "CER is 0.12, target is 0.08. Gap: 0.04. Main bottleneck: ...",
  "improvements": [
    {
      "type": "hyperparameter",
      "change": "learning_rate: 1e-3 → 5e-4",
      "expected_gain": 0.01
    },
    {
      "type": "architecture",
      "change": "Add attention pooling layer before classifier",
      "expected_gain": 0.02
    }
  ],
  "best_metrics": {"cer": 0.12, "latency_p95_ms": 38, "recall_10": 0.85},
  "iteration": 2
}
```

## Convergence Criteria

- `converged: true` when ALL target metrics are met, OR
- `converged: true` when improvement delta < `min_delta` for 2 consecutive rounds
- Always set `converged: false` on the first iteration

## Completion

Reply: `ANNOUNCE_SKIP`
