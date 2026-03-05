#!/usr/bin/env python3
"""Generate a comprehensive research report from all experiment artifacts.

Used by the Reporter agent (PHASE 8) to synthesize survey, results, and
critic analyses into a final Markdown report.

Usage:
    python generate_report.py --task state/current_task.json \
        --results-dir state/ --survey state/survey.md \
        --plan state/experiment_plan.yaml --output reports/final_report.md
"""

import argparse
import glob
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import yaml
from anthropic import Anthropic

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

client = Anthropic()


def load_artifacts(results_dir: Path, survey_path: Path, plan_path: Path) -> dict:
    """Load all experiment artifacts for report generation.

    Args:
        results_dir: Directory with results_N.json and critic_N.json.
        survey_path: Path to survey.md.
        plan_path: Path to experiment_plan.yaml.

    Returns:
        Dict with survey, plan, results, and critics.
    """
    artifacts = {"results": [], "critics": []}

    # Load survey
    if survey_path.exists():
        artifacts["survey"] = survey_path.read_text()[:5000]
        log.info("Loaded survey (%d chars)", len(artifacts["survey"]))
    else:
        artifacts["survey"] = "Survey not available."

    # Load experiment plan
    if plan_path.exists():
        artifacts["plan"] = yaml.safe_load(plan_path.read_text())
        log.info("Loaded experiment plan")
    else:
        artifacts["plan"] = {}

    # Load all results
    for f in sorted(glob.glob(str(results_dir / "results_*.json"))):
        try:
            artifacts["results"].append(json.loads(Path(f).read_text()))
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Failed to load %s: %s", f, e)

    # Load all critic analyses
    for f in sorted(glob.glob(str(results_dir / "critic_*.json"))):
        try:
            artifacts["critics"].append(json.loads(Path(f).read_text()))
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Failed to load %s: %s", f, e)

    log.info(
        "Loaded %d results, %d critic analyses",
        len(artifacts["results"]),
        len(artifacts["critics"]),
    )
    return artifacts


def build_results_table(results: list[dict]) -> str:
    """Build a Markdown table from experiment results.

    Args:
        results: List of result dicts.

    Returns:
        Markdown table string.
    """
    if not results:
        return "No experiment results available.\n"

    lines = [
        "| Iteration | CER | Latency P95 (ms) | Recall@10 | Status |",
        "|-----------|-----|-------------------|-----------|--------|",
    ]
    for r in results:
        lines.append(
            f"| {r.get('iteration', '?')} "
            f"| {r.get('cer', 'N/A')} "
            f"| {r.get('latency_p95_ms', 'N/A')} "
            f"| {r.get('recall_10', 'N/A')} "
            f"| {r.get('status', 'unknown')} |"
        )
    return "\n".join(lines) + "\n"


def build_critic_summary(critics: list[dict]) -> str:
    """Build a summary of critic analyses.

    Args:
        critics: List of critic verdict dicts.

    Returns:
        Formatted critic summary string.
    """
    if not critics:
        return "No critic analyses available.\n"

    parts = []
    for c in critics:
        parts.append(
            f"### Iteration {c.get('iteration', '?')}\n\n"
            f"**Converged:** {c.get('converged', 'N/A')}\n\n"
            f"**Gap Analysis:** {c.get('gap_analysis', 'N/A')}\n\n"
        )
        improvements = c.get("improvements", [])
        if improvements:
            parts.append("**Improvements proposed:**\n")
            for imp in improvements:
                parts.append(
                    f"- [{imp.get('type', '?')}] {imp.get('change', '?')} "
                    f"(expected gain: {imp.get('expected_gain', '?')})\n"
                )
        parts.append("\n")
    return "".join(parts)


def generate_report_text(task: dict, artifacts: dict) -> str:
    """Generate the full report using Sonnet.

    Args:
        task: Task definition.
        artifacts: All loaded artifacts.

    Returns:
        Complete report in Markdown.
    """
    results_table = build_results_table(artifacts["results"])
    critic_summary = build_critic_summary(artifacts["critics"])

    # Determine best metrics
    best = {}
    for key in ["cer", "latency_p95_ms", "recall_10"]:
        values = [
            r.get(key) for r in artifacts["results"]
            if r.get(key) is not None and r.get("status") == "success"
        ]
        if values:
            best[key] = min(values) if key != "recall_10" else max(values)

    targets = task.get("target_metrics", {})
    best_text = ", ".join(f"{k}={v}" for k, v in best.items())
    target_text = ", ".join(f"{k}={v}" for k, v in targets.items())

    prompt = (
        f"Write a comprehensive academic research report (~2000 words) in Markdown.\n\n"
        f"## Research Task\n"
        f"**Question:** {task['query']}\n"
        f"**Direction:** {task['tech_direction']}\n"
        f"**Targets:** {target_text}\n"
        f"**Best achieved:** {best_text}\n\n"
        f"## Literature Survey (excerpt)\n"
        f"{artifacts['survey'][:2000]}\n\n"
        f"## Experiment Results\n"
        f"{results_table}\n\n"
        f"## Critic Analyses\n"
        f"{critic_summary}\n\n"
        f"## Requirements\n"
        f"1. Abstract / Introduction / Methodology / Results / Analysis / Conclusion\n"
        f"2. Include the results table\n"
        f"3. Compare against baselines from literature\n"
        f"4. Discuss convergence behavior\n"
        f"5. Propose future work\n"
        f"6. Use Markdown with proper headings and tables"
    )

    log.info("Generating report with Sonnet (%d chars context)", len(prompt))
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        system=(
            "You are an academic research report writer specializing in ASR. "
            "Write a rigorous report with proper structure, data analysis, and citations. "
            "Use Markdown formatting."
        ),
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text


def main() -> None:
    """Entry point: load artifacts and generate final report."""
    parser = argparse.ArgumentParser(description="Generate final research report")
    parser.add_argument(
        "--task", type=Path, required=True, help="Path to current_task.json"
    )
    parser.add_argument(
        "--results-dir", type=Path, required=True, help="Directory with result files"
    )
    parser.add_argument(
        "--survey", type=Path, required=True, help="Path to survey.md"
    )
    parser.add_argument(
        "--plan", type=Path, required=True, help="Path to experiment_plan.yaml"
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="Output report path"
    )
    args = parser.parse_args()

    task = json.loads(args.task.expanduser().read_text())

    artifacts = load_artifacts(
        args.results_dir.expanduser(),
        args.survey.expanduser(),
        args.plan.expanduser(),
    )

    if not artifacts["results"]:
        log.warning("No results found — generating partial report")

    report = generate_report_text(task, artifacts)

    # Add metadata header
    header = (
        f"---\n"
        f"title: \"{task['query']}\"\n"
        f"direction: \"{task['tech_direction']}\"\n"
        f"generated: \"{datetime.now(timezone.utc).isoformat()}\"\n"
        f"iterations: {len(artifacts['results'])}\n"
        f"---\n\n"
    )

    output_path = args.output.expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(header + report, encoding="utf-8")
    log.info("Report saved to %s (%d chars)", output_path, len(report))


if __name__ == "__main__":
    main()
