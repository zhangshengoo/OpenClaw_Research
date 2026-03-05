---
name: experiment-runner
description: "Local CPU experiment execution with venv isolation, MLflow tracking, and error handling"
user-invocable: false
---

# Experiment Runner

Execute a single experiment iteration with full isolation and tracking.

## Step 1: Read iteration config

```bash
ITER=$(python3 -c "import json; print(json.load(open('$HOME/.openclaw/workspace/state/iteration.json'))['current'])")
echo "Running iteration: $ITER"
ls ~/.openclaw/workspace/experiments/iter_${ITER}/
```

## Step 2: Run experiment via run_experiment.py

```bash
cd ~/.openclaw/workspace
timeout 3600 python scripts/run_experiment.py \
  --config state/experiment_plan.yaml \
  --iter "$ITER" \
  --output "state/results_${ITER}.json"
```

## Step 3: Verify output

```bash
cat ~/.openclaw/workspace/state/results_${ITER}.json
```

Expected keys: `cer`, `latency_p95_ms`, `recall_10`, `status`.

## Failure Handling

- If run_experiment.py exits non-zero, the stderr is automatically summarized
  by Haiku and written to `state/error.json`.
- Partial metrics (if any) are still saved to `state/results_${ITER}.json`
  with `"status": "failed"`.

## MLflow

All experiments are tracked in MLflow at `data/mlflow/`.
View via: `mlflow ui --backend-store-uri ~/.openclaw/workspace/data/mlflow --port 5000`
