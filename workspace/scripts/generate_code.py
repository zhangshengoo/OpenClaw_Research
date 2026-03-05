#!/usr/bin/env python3
"""Generate experiment code (run.py + requirements.txt) for a single iteration.

Used by the Coder agent (PHASE 5) to create per-iteration experiment scripts
based on the experiment plan and critic feedback.

Usage:
    python generate_code.py --task state/current_task.json \
        --plan state/experiment_plan.yaml --iteration 0 \
        --output-dir experiments/iter_0
"""

import argparse
import json
import logging
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

WORKSPACE = Path.home() / ".openclaw" / "workspace"


def load_context(
    task_path: Path,
    plan_path: Path,
    iteration: int,
) -> dict:
    """Load task, plan iteration config, and optional critic feedback.

    Args:
        task_path: Path to current_task.json.
        plan_path: Path to experiment_plan.yaml.
        iteration: Iteration number.

    Returns:
        Context dict with task, config, and previous feedback.
    """
    task = json.loads(task_path.read_text())
    plan = yaml.safe_load(plan_path.read_text())

    iterations = plan.get("iterations", [])
    if iteration >= len(iterations):
        raise ValueError(
            f"Iteration {iteration} not in plan (has {len(iterations)} iterations)"
        )

    iter_info = iterations[iteration]
    context = {
        "task": task,
        "plan_name": plan.get("experiment_name", "experiment"),
        "base_approach": plan.get("base_approach", ""),
        "iteration_name": iter_info.get("name", f"iter_{iteration}"),
        "iteration_desc": iter_info.get("description", ""),
        "config": iter_info.get("config", {}),
    }

    # Load previous critic feedback if available
    if iteration > 0:
        critic_path = WORKSPACE / "state" / f"critic_{iteration - 1}.json"
        if critic_path.exists():
            context["previous_critic"] = json.loads(critic_path.read_text())
            log.info("Loaded critic feedback from iter %d", iteration - 1)

    # Load previous results for reference
    prev_result_path = WORKSPACE / "state" / f"results_{iteration - 1}.json"
    if iteration > 0 and prev_result_path.exists():
        context["previous_results"] = json.loads(prev_result_path.read_text())

    return context


def generate_run_script(context: dict) -> str:
    """Generate run.py code using Sonnet.

    Args:
        context: Context dict with task, config, and feedback.

    Returns:
        Python source code for run.py.
    """
    config_json = json.dumps(context["config"], indent=2)
    critic_text = ""
    if "previous_critic" in context:
        critic = context["previous_critic"]
        improvements = critic.get("improvements", [])
        critic_text = (
            f"\n## Previous Critic Feedback\n"
            f"Gap analysis: {critic.get('gap_analysis', 'N/A')}\n"
            f"Improvements to apply:\n"
            + "\n".join(
                f"- [{imp.get('type')}] {imp.get('change')}"
                for imp in improvements
            )
        )

    prev_results_text = ""
    if "previous_results" in context:
        pr = context["previous_results"]
        prev_results_text = (
            f"\n## Previous Iteration Results\n"
            f"CER: {pr.get('cer', 'N/A')}, "
            f"Latency: {pr.get('latency_p95_ms', 'N/A')}ms, "
            f"Recall@10: {pr.get('recall_10', 'N/A')}\n"
        )

    prompt = (
        f"Generate a complete Python experiment script (run.py) for:\n\n"
        f"## Task\n"
        f"Research: {context['task']['query']}\n"
        f"Direction: {context['task']['tech_direction']}\n\n"
        f"## Iteration: {context['iteration_name']}\n"
        f"Description: {context['iteration_desc']}\n\n"
        f"## Config\n```json\n{config_json}\n```\n"
        f"{critic_text}"
        f"{prev_results_text}\n"
        f"## Requirements for run.py\n"
        f"1. Accept --config JSON string via argparse\n"
        f"2. Parse config from JSON, use values as hyperparameters\n"
        f"3. Implement the experiment logic (CPU only, no GPU)\n"
        f"4. Write metrics.json to CWD with keys: cer, latency_p95_ms, recall_10\n"
        f"5. Use logging, type hints, Google-style docstrings\n"
        f"6. Handle errors gracefully with informative messages\n"
        f"7. Use standard libraries + torch/numpy if needed\n"
        f"8. Script must be self-contained and runnable\n\n"
        f"Return ONLY the Python code, no markdown fences."
    )

    log.info("Generating run.py with Sonnet (%d chars prompt)", len(prompt))
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        system=(
            "You are an expert ASR engineer. Generate a complete, runnable Python "
            "experiment script. Output only Python code, no markdown. "
            "The script must write metrics.json with cer, latency_p95_ms, recall_10."
        ),
        messages=[{"role": "user", "content": prompt}],
    )
    code = resp.content[0].text.strip()
    # Strip markdown fences if present
    if code.startswith("```"):
        code = code.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return code


def generate_requirements(context: dict) -> str:
    """Generate requirements.txt based on experiment config.

    Args:
        context: Context dict.

    Returns:
        Requirements text content.
    """
    config = context["config"]
    lines = ["numpy>=1.24.0"]

    # Common ASR dependencies based on config
    model_type = config.get("model_type", "")
    if "torch" in model_type or "cif" in model_type:
        lines.append("torch>=2.0.0")
    if config.get("biasing_method") == "dual_encoder_faiss":
        lines.append("faiss-cpu>=1.7.0")
    if config.get("use_biasing"):
        lines.append("scipy>=1.10.0")

    return "\n".join(sorted(set(lines))) + "\n"


def main() -> None:
    """Entry point: generate experiment code for one iteration."""
    parser = argparse.ArgumentParser(description="Generate experiment code")
    parser.add_argument(
        "--task", type=Path, required=True, help="Path to current_task.json"
    )
    parser.add_argument(
        "--plan", type=Path, required=True, help="Path to experiment_plan.yaml"
    )
    parser.add_argument(
        "--iteration", type=int, required=True, help="Iteration number"
    )
    parser.add_argument(
        "--output-dir", type=Path, required=True, help="Output directory for run.py"
    )
    args = parser.parse_args()

    context = load_context(
        args.task.expanduser(),
        args.plan.expanduser(),
        args.iteration,
    )
    log.info(
        "Generating code for iteration %d (%s)",
        args.iteration,
        context["iteration_name"],
    )

    # Generate run.py
    code = generate_run_script(context)
    output_dir = args.output_dir.expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    run_path = output_dir / "run.py"
    run_path.write_text(code, encoding="utf-8")
    log.info("Generated %s (%d chars)", run_path, len(code))

    # Generate requirements.txt
    req_text = generate_requirements(context)
    req_path = output_dir / "requirements.txt"
    req_path.write_text(req_text, encoding="utf-8")
    log.info("Generated %s", req_path)


if __name__ == "__main__":
    main()
