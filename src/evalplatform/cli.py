"""CLI for the LLM Eval Platform.

Commands:
  evalplatform run <config.yaml> [--wait]
  evalplatform status <run_id>
  evalplatform results <run_id> [--format json|table]
  evalplatform compare <run_id_1> <run_id_2>
  evalplatform list [--status completed] [--limit 10]
"""

from __future__ import annotations

import json
import os
import time
from enum import Enum
from pathlib import Path
from typing import Annotated

import httpx
import typer
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

app = typer.Typer(
    name="evalplatform",
    help="LLM Eval Platform CLI",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()


def _base_url() -> str:
    return os.environ.get("EVALPLATFORM_API_URL", "http://localhost:8000")


def _client() -> httpx.Client:
    return httpx.Client(base_url=_base_url(), timeout=30.0)


def _api_get(path: str, **params: object) -> dict:
    with _client() as client:
        resp = client.get(path, params={k: v for k, v in params.items() if v is not None})
    if resp.status_code == 404:
        rprint(f"[red]Not found:[/red] {resp.json().get('detail', path)}")
        raise typer.Exit(1)
    if not resp.is_success:
        rprint(f"[red]API error {resp.status_code}:[/red] {resp.text}")
        raise typer.Exit(1)
    return resp.json()  # type: ignore[return-value]


def _status_color(status: str) -> str:
    colors = {
        "pending": "yellow",
        "running": "cyan",
        "completed": "green",
        "failed": "red",
    }
    return colors.get(status, "white")


def _fmt_ts(ts: str | None) -> str:
    if ts is None:
        return "—"
    return ts.replace("T", " ").split(".")[0]


# ── run ───────────────────────────────────────────────────────────────


@app.command()
def run(
    config: Annotated[Path, typer.Argument(help="Path to eval YAML config file")],
    wait: Annotated[
        bool, typer.Option("--wait", help="Poll until complete, then show results")
    ] = False,
) -> None:
    """Submit an eval run from a YAML config file."""
    if not config.exists():
        rprint(f"[red]Config file not found:[/red] {config}")
        raise typer.Exit(1)

    yaml_content = config.read_text()

    with _client() as client:
        resp = client.post(
            "/api/v1/evals",
            content=yaml_content,
            headers={"Content-Type": "text/yaml"},
        )
    if not resp.is_success:
        rprint(f"[red]Failed to submit eval ({resp.status_code}):[/red] {resp.text}")
        raise typer.Exit(1)

    data = resp.json()
    run_id: str = data["run_id"]
    rprint(f"[green]Submitted eval run[/green] [bold]{run_id}[/bold]")

    if not wait:
        return

    # Poll with progress bar until complete or failed
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Running eval…", total=None)
        while True:
            time.sleep(2)
            detail = _api_get(f"/api/v1/evals/{run_id}")
            status: str = detail["status"]
            total: int | None = detail.get("total_samples")
            completed: int = detail.get("completed_samples", 0)

            if total:
                progress.update(task, total=total, completed=completed)
            else:
                progress.update(task, description=f"Running eval… [{status}]")

            if status in ("completed", "failed"):
                break

    if detail["status"] == "failed":
        rprint(f"[red]Eval failed:[/red] {detail.get('error_message', 'unknown error')}")
        raise typer.Exit(1)

    # Show results table after completion
    rprint(f"\n[green]Eval completed[/green] (run_id: {run_id})\n")
    _print_results_table(run_id)


# ── status ────────────────────────────────────────────────────────────


@app.command()
def status(
    run_id: Annotated[str, typer.Argument(help="Run UUID")],
) -> None:
    """Show run details with status, progress, and timestamps."""
    detail = _api_get(f"/api/v1/evals/{run_id}")

    s = detail["status"]
    color = _status_color(s)
    total = detail.get("total_samples") or "—"
    completed = detail.get("completed_samples", 0)
    progress_str = f"{completed}/{total}"

    content = (
        f"[bold]Name:[/bold]       {detail['name']}\n"
        f"[bold]Status:[/bold]     [{color}]{s}[/{color}]\n"
        f"[bold]Provider:[/bold]   {detail['provider']}\n"
        f"[bold]Model:[/bold]      {detail['model']}\n"
        f"[bold]Progress:[/bold]   {progress_str}\n"
        f"[bold]Created:[/bold]    {_fmt_ts(detail.get('created_at'))}\n"
        f"[bold]Started:[/bold]    {_fmt_ts(detail.get('started_at'))}\n"
        f"[bold]Completed:[/bold]  {_fmt_ts(detail.get('completed_at'))}\n"
    )

    if detail.get("error_message"):
        content += f"[bold]Error:[/bold]      [red]{detail['error_message']}[/red]\n"

    if detail.get("aggregate_scores"):
        scores_lines = "\n".join(f"  {k}: {v}" for k, v in detail["aggregate_scores"].items())
        content += f"[bold]Scores:[/bold]\n{scores_lines}\n"

    panel = Panel(
        content,
        title=f"[bold]Run {run_id}[/bold]",
        border_style=color,
        expand=False,
    )
    console.print(panel)


# ── results ───────────────────────────────────────────────────────────


class ResultFormat(str, Enum):
    json = "json"
    table = "table"


def _print_results_table(run_id: str) -> None:
    data = _api_get(f"/api/v1/evals/{run_id}/results")
    results = data.get("results", [])

    if not results:
        rprint("[yellow]No results found.[/yellow]")
        return

    # Collect all judge keys present in the results
    judge_keys: list[str] = []
    for r in results:
        for k in r.get("judge_scores", {}):
            if k not in judge_keys:
                judge_keys.append(k)

    table = Table(title=f"Results — {run_id}", show_lines=False)
    table.add_column("#", justify="right", style="dim")
    table.add_column("Status", style="bold")
    table.add_column("Tokens", justify="right")
    table.add_column("Latency (ms)", justify="right")
    for jk in judge_keys:
        table.add_column(jk, justify="right")

    for r in results:
        status_val = r.get("status", "")
        color = _status_color(status_val)
        judge_cells = []
        for jk in judge_keys:
            score_data = r.get("judge_scores", {}).get(jk)
            if isinstance(score_data, dict) and score_data.get("score") is not None:
                judge_cells.append(f"{score_data['score']:.2f}")
            else:
                judge_cells.append("—")

        table.add_row(
            str(r.get("sample_index", "")),
            f"[{color}]{status_val}[/{color}]",
            str(r.get("tokens_used", 0)),
            f"{r.get('latency_ms', 0.0):.1f}",
            *judge_cells,
        )

    console.print(table)


@app.command()
def results(
    run_id: Annotated[str, typer.Argument(help="Run UUID")],
    format: Annotated[
        ResultFormat, typer.Option("--format", help="Output format")
    ] = ResultFormat.table,
) -> None:
    """Show per-sample results for an eval run."""
    data = _api_get(f"/api/v1/evals/{run_id}/results")

    if format == ResultFormat.json:
        print(json.dumps(data, indent=2))
        return

    _print_results_table(run_id)


# ── compare ───────────────────────────────────────────────────────────


@app.command()
def compare(
    run_id_1: Annotated[str, typer.Argument(help="First run UUID (A)")],
    run_id_2: Annotated[str, typer.Argument(help="Second run UUID (B)")],
) -> None:
    """Compare two eval runs side by side."""
    data = _api_get("/api/v1/evals/compare", run_ids=f"{run_id_1},{run_id_2}")

    run_a = data["run_a"]
    run_b = data["run_b"]
    judge_summaries = data.get("judge_summaries", [])

    rprint(
        f"\n[bold]Comparing[/bold]  "
        f"[cyan]A: {run_a['name']}[/cyan] ({run_id_1[:8]}…)  "
        f"vs  "
        f"[magenta]B: {run_b['name']}[/magenta] ({run_id_2[:8]}…)\n"
    )

    table = Table(title="Judge Score Comparison", show_lines=True)
    table.add_column("Evaluator", style="bold")
    table.add_column("Score A", justify="right", style="cyan")
    table.add_column("Score B", justify="right", style="magenta")
    table.add_column("Delta", justify="right")

    for js in judge_summaries:
        mean_a = js.get("mean_a")
        mean_b = js.get("mean_b")
        delta = js.get("delta")

        a_str = f"{mean_a:.3f}" if mean_a is not None else "—"
        b_str = f"{mean_b:.3f}" if mean_b is not None else "—"

        if delta is None:
            delta_str = "—"
        elif delta > 0:
            delta_str = f"[green]+{delta:.3f}[/green]"
        elif delta < 0:
            delta_str = f"[red]{delta:.3f}[/red]"
        else:
            delta_str = "0.000"

        table.add_row(js["judge_key"], a_str, b_str, delta_str)

    console.print(table)


# ── list ──────────────────────────────────────────────────────────────


@app.command(name="list")
def list_runs(
    status: Annotated[str | None, typer.Option("--status", help="Filter by status")] = None,
    limit: Annotated[int, typer.Option("--limit", help="Max number of runs to show")] = 10,
) -> None:
    """List recent eval runs."""
    runs = _api_get("/api/v1/evals", status=status, limit=limit)

    if not runs:
        rprint("[yellow]No eval runs found.[/yellow]")
        return

    table = Table(title="Eval Runs", show_lines=False)
    table.add_column("Run ID", style="dim")
    table.add_column("Name", style="bold")
    table.add_column("Status")
    table.add_column("Provider")
    table.add_column("Model")
    table.add_column("Progress", justify="right")
    table.add_column("Created", justify="right")

    for r in runs:
        s = r.get("status", "")
        color = _status_color(s)
        total = r.get("total_samples") or "?"
        completed = r.get("completed_samples", 0)
        run_id_str = str(r.get("run_id", ""))

        table.add_row(
            run_id_str[:8] + "…",
            r.get("name", ""),
            f"[{color}]{s}[/{color}]",
            r.get("provider", ""),
            r.get("model", ""),
            f"{completed}/{total}",
            _fmt_ts(r.get("created_at")),
        )

    console.print(table)


if __name__ == "__main__":
    app()
