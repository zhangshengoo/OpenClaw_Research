#!/usr/bin/env python3
"""Run a single experiment iteration with venv isolation, MLflow tracking, and error handling.

Usage:
    python run_experiment.py --config state/experiment_plan.yaml --iter 0 \
        --output state/results_0.json
"""

import argparse
import json
import logging
import subprocess
import sys
import venv
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

WORKSPACE = Path.home() / ".openclaw" / "workspace"
MLFLOW_URI = str(WORKSPACE / "data" / "mlflow")
STDERR_TAIL_LEN = 3000


def load_iteration_config(config_path: Path, iteration: int) -> dict:
    """Load the config for a specific iteration from experiment_plan.yaml.

    Args:
        config_path: Path to experiment_plan.yaml.
        iteration: Iteration number.

    Returns:
        Config dict for the requested iteration.
    """
    plan = yaml.safe_load(config_path.read_text())
    iterations = plan.get("iterations", [])
    if iteration >= len(iterations):
        raise ValueError(
            f"Iteration {iteration} not found in plan "
            f"(only {len(iterations)} iterations defined)"
        )
    return iterations[iteration].get("config", {})


def setup_venv(experiment_dir: Path) -> Path:
    """Create an isolated venv and install requirements.

    Args:
        experiment_dir: Path to experiments/iter_N/.

    Returns:
        Path to the venv's Python executable.
    """
    venv_dir = experiment_dir / "venv"
    req_file = experiment_dir / "requirements.txt"

    if not venv_dir.exists():
        log.info("Creating venv at %s", venv_dir)
        venv.create(str(venv_dir), with_pip=True)

    python_bin = venv_dir / "bin" / "python"

    if req_file.exists():
        log.info("Installing requirements from %s", req_file)
        subprocess.run(
            [str(python_bin), "-m", "pip", "install", "-q", "-r", str(req_file)],
            check=True,
            capture_output=True,
            timeout=300,
        )

    return python_bin


def run_script(python_bin: Path, experiment_dir: Path, config: dict) -> dict:
    """Execute run.py in the isolated venv.

    Args:
        python_bin: Path to venv Python.
        experiment_dir: Path to experiments/iter_N/.
        config: Hyperparameter config dict.

    Returns:
        Metrics dict from metrics.json, or error dict.
    """
    run_script_path = experiment_dir / "run.py"
    metrics_path = experiment_dir / "metrics.json"

    if not run_script_path.exists():
        return {"status": "failed", "error": f"run.py not found at {run_script_path}"}

    config_json = json.dumps(config)
    log.info("Executing %s with config: %s", run_script_path, config_json[:200])

    try:
        result = subprocess.run(
            [str(python_bin), str(run_script_path), "--config", config_json],
            cwd=str(experiment_dir),
            capture_output=True,
            text=True,
            timeout=3600,
        )

        if result.returncode != 0:
            error_summary = summarize_error(result.stderr)
            log.error("Experiment failed (exit %d): %s", result.returncode, error_summary)
            return {
                "status": "failed",
                "error": error_summary,
                "exit_code": result.returncode,
            }

        if metrics_path.exists():
            metrics = json.loads(metrics_path.read_text())
            metrics["status"] = "success"
            log.info("Experiment succeeded: %s", metrics)
            return metrics

        log.warning("run.py succeeded but no metrics.json found")
        return {"status": "success", "warning": "no metrics.json output"}

    except subprocess.TimeoutExpired:
        return {"status": "failed", "error": "Experiment timed out (3600s)"}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


def summarize_error(stderr: str) -> str:
    """Summarize stderr using Haiku for concise error diagnosis.

    Args:
        stderr: Raw stderr output from the experiment.

    Returns:
        Concise error summary string.
    """
    if not stderr or not stderr.strip():
        return "No stderr output"

    tail = stderr[-STDERR_TAIL_LEN:]
    try:
        client = Anthropic()
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            system="Summarize this Python error in 1-2 sentences. Focus on root cause.",
            messages=[{"role": "user", "content": tail}],
        )
        return resp.content[0].text.strip()
    except Exception:
        # Fallback: return last 500 chars of stderr
        return tail[-500:]


def track_mlflow(iteration: int, config: dict, metrics: dict) -> None:
    """Log experiment to MLflow.

    Args:
        iteration: Current iteration number.
        config: Hyperparameter config.
        metrics: Result metrics dict.
    """
    try:
        import mlflow

        mlflow.set_tracking_uri(MLFLOW_URI)
        Path(MLFLOW_URI).mkdir(parents=True, exist_ok=True)

        with mlflow.start_run(run_name=f"iter_{iteration}"):
            mlflow.log_params({
                k: str(v) for k, v in config.items()
                if isinstance(v, (str, int, float, bool))
            })
            numeric_metrics = {
                k: v for k, v in metrics.items()
                if isinstance(v, (int, float))
            }
            if numeric_metrics:
                mlflow.log_metrics(numeric_metrics)
            mlflow.log_param("iteration", iteration)
            mlflow.log_param("status", metrics.get("status", "unknown"))
        log.info("MLflow run logged for iter_%d", iteration)
    except Exception as e:
        log.warning("MLflow tracking failed: %s", e)


def main() -> None:
    """Entry point: setup venv, run experiment, track results."""
    parser = argparse.ArgumentParser(description="Run experiment iteration")
    parser.add_argument("--config", type=Path, required=True, help="Path to experiment_plan.yaml")
    parser.add_argument("--iter", type=int, required=True, help="Iteration number")
    parser.add_argument("--output", type=Path, required=True, help="Output results path")
    args = parser.parse_args()

    config_path = args.config.expanduser()
    output_path = args.output.expanduser()
    iteration = args.iter

    experiment_dir = WORKSPACE / "experiments" / f"iter_{iteration}"

    if not experiment_dir.exists():
        log.error("Experiment directory not found: %s", experiment_dir)
        error_result = {
            "status": "failed",
            "error": f"Directory not found: {experiment_dir}",
            "iteration": iteration,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(error_result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        raise SystemExit(1)

    # Load iteration config
    iter_config = load_iteration_config(config_path, iteration)
    log.info("Iteration %d config: %s", iteration, iter_config)

    # Setup venv
    python_bin = setup_venv(experiment_dir)

    # Run experiment
    metrics = run_script(python_bin, experiment_dir, iter_config)
    metrics["iteration"] = iteration
    metrics["timestamp"] = datetime.now(timezone.utc).isoformat()

    # Track in MLflow
    track_mlflow(iteration, iter_config, metrics)

    # Save results
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("Results saved to %s", output_path)

    if metrics.get("status") == "failed":
        # Write error.json for Orchestrator awareness
        error_path = WORKSPACE / "state" / "error.json"
        error_path.write_text(json.dumps({
            "agent": "run_experiment",
            "phase": 6,
            "error": metrics.get("error", "Unknown error"),
            "timestamp": metrics["timestamp"],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
