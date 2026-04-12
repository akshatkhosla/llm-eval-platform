"""Run an eval and print results with Rich tables."""

from __future__ import annotations

import asyncio
import os
import textwrap
from pathlib import Path


def _load_dotenv(env_file: Path) -> None:
    """
    Load environment variables from a .env file before importing modules that need them.
    Only sets variables that aren't already in os.environ (won't override existing).
    Skips empty lines and comments (lines starting with #).
    """
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


# Load .env from project root before importing providers (which read env vars)
_load_dotenv(Path(__file__).parent.parent / ".env")

import typer
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text

from evalplatform.core.config_loader import load_config
from evalplatform.core.runner import run_eval
from evalplatform.core.schemas import EvalRunResult, JudgeResultStatus, SampleStatus

console = Console()

_JUDGE_LABELS: dict[str, str] = {
    "llm": "LLM (faithfulness)",
    "contains_keyword": "Keyword",
    "regex_match": "Regex",
}


def _truncate(text: str, width: int = 60) -> str:
    """Shorten text to fit table columns. Adds … if truncated to indicate overflow."""
    return textwrap.shorten(text, width=width, placeholder="…")


def _status_style(status: SampleStatus) -> str:
    """Map sample evaluation status to Rich color: green (pass), yellow (partial), red (error)."""
    return {
        SampleStatus.passed: "green",
        SampleStatus.partial: "yellow",
        SampleStatus.error: "red",
    }.get(status, "white")


def _score_style(score: int | None) -> str:
    """
    Color code judge scores: dim (no score), green (≥8), yellow (5-7), red (<5).
    Helps visually identify strong vs weak judge assessments.
    """
    if score is None:
        return "dim"
    if score >= 8:
        return "green"
    if score >= 5:
        return "yellow"
    return "red"


def _build_results_table(result: EvalRunResult, judge_labels: list[str]) -> Table:
    """
    Build a detailed results table showing each sample: prompt, response, status, and judge scores.
    Each judge gets a column showing score/10, reasoning, or error details if evaluation failed.
    """
    table = Table(
        title="Sample Results",
        show_lines=True,
        header_style="bold cyan",
        expand=True,
    )
    table.add_column("#", style="dim", width=3)
    table.add_column("Prompt", min_width=30, max_width=55, no_wrap=False)
    table.add_column("Response", min_width=30, max_width=55, no_wrap=False)
    table.add_column("Status", width=9)
    for label in judge_labels:
        table.add_column(label, width=18)

    for sample in result.sample_results:
        judge_cells: list[Text] = []
        for jr in sample.judge_results:
            if jr.status == JudgeResultStatus.error:
                cell = Text("ERR", style="red")
                if jr.error:
                    cell.append(f"\n{_truncate(jr.error, 30)}", style="dim red")
            else:
                score_str = str(jr.score) if jr.score is not None else "—"
                style = _score_style(jr.score)
                cell = Text(f"{score_str}/10", style=style)
                if jr.reasoning:
                    cell.append(f"\n{_truncate(jr.reasoning, 40)}", style="dim")
            judge_cells.append(cell)

        status_text = Text(
            sample.status.upper(),
            style=_status_style(sample.status),
        )
        if sample.error:
            status_text.append(f"\n{_truncate(sample.error, 40)}", style="dim red")

        row_cells: list[str | Text] = [
            str(sample.row_index),
            _truncate(sample.prompt, 120),
            _truncate(sample.response or sample.error or "—", 120),
            status_text,
            *judge_cells,
        ]
        table.add_row(*row_cells)

    return table


def _build_aggregates_table(result: EvalRunResult, judge_labels: list[str]) -> Table:
    """
    Build summary statistics per judge: mean, min, max scores, count of evaluations,
    and pass rate (% of samples scored ≥7). Useful for comparing judge severity/agreement.
    """
    table = Table(
        title="Aggregate Scores per Judge",
        header_style="bold cyan",
        show_lines=True,
    )
    table.add_column("Judge", style="bold")
    table.add_column("Mean", justify="right")
    table.add_column("Min", justify="right")
    table.add_column("Max", justify="right")
    table.add_column("Count", justify="right")
    table.add_column("Pass rate (≥7)", justify="right")

    for idx, label in enumerate(judge_labels):
        agg = result.aggregate_scores.get(idx)
        if agg is None:
            table.add_row(label, "—", "—", "—", "—", "—")
            continue

        mean_style = _score_style(round(agg.mean))
        # Compute pass rate: samples where this judge scored >= 7
        passing = sum(
            1
            for s in result.sample_results
            for jr in s.judge_results
            if jr.judge_index == idx
            and jr.status == JudgeResultStatus.ok
            and jr.score is not None
            and jr.score >= 7
        )
        pass_rate = f"{passing}/{agg.count} ({100 * passing // agg.count}%)"

        table.add_row(
            label,
            Text(f"{agg.mean:.1f}", style=mean_style),
            Text(str(agg.min_score), style=_score_style(agg.min_score)),
            Text(str(agg.max_score), style=_score_style(agg.max_score)),
            str(agg.count),
            pass_rate,
        )

    return table


def _build_summary_panel(result: EvalRunResult) -> Panel:
    """
    Build a high-level summary panel showing total rows, completed, errors, partial passes, and full passes.
    Provides at-a-glance overview of eval run health.
    """
    lines = [
        f"[bold]Total rows:[/bold]     {result.total_rows}",
        f"[bold]Completed:[/bold]      {result.completed_rows}",
        f"[bold]Errors:[/bold]         {result.error_rows}",
        "[bold]Partial:[/bold]        "
        + str(sum(1 for s in result.sample_results if s.status == SampleStatus.partial)),
        "[bold]Passed:[/bold]         "
        + str(sum(1 for s in result.sample_results if s.status == SampleStatus.passed)),
    ]
    return Panel("\n".join(lines), title="Run Summary", border_style="cyan", expand=False)


async def _run(config_path: Path) -> None:
    """
    Core orchestration: load config, resolve paths, run eval with progress tracking,
    and display results in formatted tables. Entry point for the async eval pipeline.
    """
    config = load_config(config_path)

    # Resolve dataset path relative to the config file's directory
    dataset_path = Path(config.dataset)
    if not dataset_path.is_absolute():
        dataset_path = (config_path.parent / dataset_path).resolve()
    config.dataset = str(dataset_path)

    # Derive judge labels from config
    judge_labels: list[str] = []
    for jcfg in config.judges:
        raw_type = jcfg.type  # type: ignore[attr-defined]
        judge_labels.append(_JUDGE_LABELS.get(raw_type, raw_type))

    console.print()
    console.print(
        Panel(
            f"[bold]Model:[/bold]    {config.model}\n"
            f"[bold]Dataset:[/bold]  {config.dataset}\n"
            f"[bold]Judges:[/bold]   {', '.join(judge_labels)}\n"
            f"[bold]Concurrency:[/bold] {config.max_concurrency}",
            title="Eval Config",
            border_style="blue",
            expand=False,
        )
    )
    console.print()

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=console,
    )
    task_id = progress.add_task("Running eval…", total=None)

    result: EvalRunResult | None = None

    async def on_progress(completed: int, total: int) -> None:
        progress.update(task_id, completed=completed, total=total)

    with Live(progress, console=console, refresh_per_second=10):
        result = await run_eval(config, status_callback=on_progress)

    assert result is not None

    console.print()
    console.print(_build_summary_panel(result))
    console.print()
    console.print(_build_results_table(result, judge_labels))
    console.print()
    console.print(_build_aggregates_table(result, judge_labels))
    console.print()


app = typer.Typer(add_completion=False)


@app.command()
def main(
    config: Path = typer.Argument(  # noqa: B008
        Path(__file__).parent.parent / "examples" / "sample_config.yaml",
        help="Path to eval YAML config file.",
        exists=True,
        dir_okay=False,
    ),
) -> None:
    """
    CLI entry point (Typer). Accepts a path to eval YAML config file.
    Runs the async evaluation pipeline and displays formatted results.
    """
    asyncio.run(_run(config))


if __name__ == "__main__":
    app()
