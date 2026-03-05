#!/usr/bin/env python3
"""Analyze experiment results: convergence check, gap analysis, improvement suggestions.

Used by the Critic agent (PHASE 7) to evaluate whether experiments have converged
and propose next-iteration improvements.

Usage:
    python analyze_results.py --task state/current_task.json \
        --results-dir state/ --iteration 0 --output state/critic_0.json
"""

import argparse
import glob
import json
import logging
from pathlib import Path

from anthropic import Anthropic

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

client = Anthropic()

TARGET_KEYS = ["cer", "latency_p95_ms", "recall_10"]


def load_all_results(results_dir: Path) -> list[dict]:
    """Load all results_N.json files sorted by iteration number.

    Args:
        results_dir: Directory containing results_N.json files.

    Returns:
        Sorted list of result dicts with iteration number.
    """
    pattern = str(results_dir / "results_*.json")
    files = sorted(glob.glob(pattern))
    results = []
    for f in files:
        try:
            data = json.loads(Path(f).read_text())
            results.append(data)
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Failed to load %s: %s", f, e)
    results.sort(key=lambda x: x.get("iteration", 0))
    log.info("Loaded %d result files from %s", len(results), results_dir)
    return results


def compute_gaps(current: dict, targets: dict) -> dict:
    """Compute metric gaps between current results and targets.

    Args:
        current: Current iteration metrics.
        targets: Target metrics from task definition.

    Returns:
        Dict with gap values (negative = better than target).
    """
    gaps = {}
    for key in TARGET_KEYS:
        if key in current and key in targets:
            actual = current[key]
            target = targets[key]
            if key == "recall_10":
                # Higher is better
                gaps[key] = target - actual
            else:
                # Lower is better (cer, latency)
                gaps[key] = actual - target
    return gaps


def check_convergence(
    results: list[dict],
    targets: dict,
    min_delta: float,
    current_iter: int,
) -> tuple[bool, str]:
    """Determine if experiments have converged.

    Convergence conditions:
    1. All target metrics are met.
    2. Improvement delta < min_delta for 2 consecutive rounds.

    Args:
        results: All result dicts sorted by iteration.
        targets: Target metrics.
        min_delta: Minimum improvement threshold.
        current_iter: Current iteration number.

    Returns:
        Tuple of (converged: bool, reason: str).
    """
    if current_iter == 0:
        return False, "First iteration — convergence check skipped"

    # Check if all targets met
    if results:
        latest = results[-1]
        gaps = compute_gaps(latest, targets)
        all_met = all(v <= 0 for v in gaps.values()) and len(gaps) == len(TARGET_KEYS)
        if all_met:
            return True, "All target metrics achieved"

    # Check consecutive small deltas
    if len(results) >= 3:
        cer_values = [r.get("cer") for r in results[-3:] if r.get("cer") is not None]
        if len(cer_values) >= 3:
            delta_1 = abs(cer_values[-2] - cer_values[-3])
            delta_2 = abs(cer_values[-1] - cer_values[-2])
            if delta_1 < min_delta and delta_2 < min_delta:
                return True, (
                    f"CER improvement stalled: deltas {delta_1:.4f}, "
                    f"{delta_2:.4f} < {min_delta}"
                )

    return False, "Not converged — continuing iterations"


def generate_improvements(
    task: dict,
    results: list[dict],
    gaps: dict,
    current_iter: int,
) -> list[dict]:
    """Generate improvement suggestions using Sonnet.

    Args:
        task: Task definition with research context.
        results: All result dicts.
        gaps: Current metric gaps.
        current_iter: Current iteration number.

    Returns:
        List of improvement suggestion dicts.
    """
    results_summary = "\n".join(
        f"Iter {r.get('iteration', '?')}: CER={r.get('cer', 'N/A')}, "
        f"Latency={r.get('latency_p95_ms', 'N/A')}ms, "
        f"Recall@10={r.get('recall_10', 'N/A')}, "
        f"Status={r.get('status', 'unknown')}"
        for r in results
    )

    gap_text = ", ".join(f"{k}: gap={v:+.4f}" for k, v in gaps.items())

    prompt = (
        f"Research task: {task['query']}\n"
        f"Direction: {task['tech_direction']}\n\n"
        f"Experiment results so far:\n{results_summary}\n\n"
        f"Current gaps from targets: {gap_text}\n\n"
        f"Targets: CER ≤ {task['target_metrics'].get('cer', 'N/A')}, "
        f"Latency P95 ≤ {task['target_metrics'].get('latency_p95_ms', 'N/A')}ms, "
        f"Recall@10 ≥ {task['target_metrics'].get('recall_10', 'N/A')}\n\n"
        f"Current iteration: {current_iter}\n\n"
        f"Propose 2-4 concrete improvements for the next iteration. "
        f"Return a JSON array: "
        f'[{{"type": "hyperparameter|architecture|data|training", '
        f'"change": "description", "expected_gain": 0.01}}]'
    )

    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            system=(
                "You are an ASR experiment critic. Propose specific, actionable "
                "improvements based on experiment results. Return only valid JSON."
            ),
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        improvements = json.loads(text)
        if isinstance(improvements, list):
            return improvements
    except Exception as e:
        log.warning("Sonnet improvement generation failed: %s", e)

    return [{"type": "unknown", "change": "Manual review needed", "expected_gain": 0}]


def generate_gap_analysis(task: dict, results: list[dict], gaps: dict) -> str:
    """Generate a concise gap analysis string using Haiku.

    Args:
        task: Task definition.
        results: All results.
        gaps: Current metric gaps.

    Returns:
        Gap analysis text.
    """
    latest = results[-1] if results else {}
    gap_text = ", ".join(
        f"{k}={latest.get(k, 'N/A')} (target: {task['target_metrics'].get(k, 'N/A')}, gap: {v:+.4f})"
        for k, v in gaps.items()
    )

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            system="Write a 2-3 sentence gap analysis for ASR experiment metrics.",
            messages=[{"role": "user", "content": f"Metrics: {gap_text}"}],
        )
        return resp.content[0].text.strip()
    except Exception:
        return f"Gap analysis: {gap_text}"


def main() -> None:
    """Entry point: analyze results and write critic verdict."""
    parser = argparse.ArgumentParser(description="Analyze experiment results")
    parser.add_argument(
        "--task", type=Path, required=True, help="Path to current_task.json"
    )
    parser.add_argument(
        "--results-dir", type=Path, required=True, help="Directory with results_N.json"
    )
    parser.add_argument(
        "--iteration", type=int, required=True, help="Current iteration number"
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="Output critic_N.json path"
    )
    args = parser.parse_args()

    task = json.loads(args.task.expanduser().read_text())
    results = load_all_results(args.results_dir.expanduser())
    targets = task.get("target_metrics", {})
    min_delta = task.get("min_delta", 0.005)
    iteration = args.iteration

    # Compute gaps from latest result
    latest = results[-1] if results else {}
    gaps = compute_gaps(latest, targets)

    # Convergence check
    converged, reason = check_convergence(results, targets, min_delta, iteration)
    log.info("Convergence: %s (%s)", converged, reason)

    # Gap analysis
    gap_analysis = generate_gap_analysis(task, results, gaps) if results else "No results yet"

    # Improvement suggestions (only if not converged)
    improvements = []
    if not converged:
        improvements = generate_improvements(task, results, gaps, iteration)

    # Best metrics across all iterations
    best_metrics = {}
    for key in TARGET_KEYS:
        values = [r.get(key) for r in results if r.get(key) is not None]
        if values:
            if key == "recall_10":
                best_metrics[key] = max(values)
            else:
                best_metrics[key] = min(values)

    verdict = {
        "converged": converged,
        "convergence_reason": reason,
        "gap_analysis": gap_analysis,
        "improvements": improvements,
        "best_metrics": best_metrics,
        "iteration": iteration,
    }

    output_path = args.output.expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(verdict, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("Critic verdict saved to %s (converged=%s)", output_path, converged)


if __name__ == "__main__":
    main()
