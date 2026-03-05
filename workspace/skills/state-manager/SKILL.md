---
name: state-manager
description: "Unified state file schema, iteration tracking, and history aggregation conventions"
user-invocable: false
---

# State Manager Conventions

All agent communication uses `~/.openclaw/workspace/state/` files.
Never pass large data through LLM context.

## File Registry

| File | Writer | Reader | Format |
|------|--------|--------|--------|
| `progress.json` | Orchestrator | Orchestrator | `{phase, status}` |
| `current_task.json` | Orchestrator | All agents | Task definition |
| `iteration.json` | Orchestrator | All agents | `{current, best_cer, history}` |
| `papers.json` | fetch_papers.py | embed/survey scripts | Paper array |
| `survey.md` | generate_survey.py | Planner, Reporter | Markdown survey |
| `experiment_plan.yaml` | Planner | Coder, run_experiment | YAML plan |
| `results_N.json` | run_experiment.py | Critic, Reporter | Metrics dict |
| `critic_N.json` | Critic | Orchestrator | Convergence verdict |
| `error.json` | Any agent | Orchestrator | Error details |

## JSON Conventions

- Write with `ensure_ascii=False, indent=2`
- Iteration suffix: `_N` (results_0.json, critic_0.json, ...)
- Always read before write to confirm file exists
- Use `yaml.safe_load` / `yaml.safe_dump` for YAML files

## History Aggregation

`iteration.json.history` accumulates per-round summaries:

```json
{
  "current": 3,
  "best_cer": 0.09,
  "history": [
    {"iter": 0, "cer": 0.15, "converged": false},
    {"iter": 1, "cer": 0.11, "converged": false},
    {"iter": 2, "cer": 0.09, "converged": false}
  ]
}
```
