"""``worktree-review`` CLI surface (PRD §21.3; TECH-DESIGN D10)."""

from __future__ import annotations

import asyncio
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from worktree_review import __version__
from worktree_review.core.errors import InvalidInvocationError, WorktreeReviewError
from worktree_review.core.pipeline import ReviewRequest, run_review_pipeline
from worktree_review.core.report import ReviewReport
from worktree_review.observability import configure_logging
from worktree_review.platform.cli.exit_codes import CliExitCode, exit_code_for_gate_state
from worktree_review.platform.cli.invocation import (
    prepare_cli_review,
    provider_transmission_disclosure,
    require_remote_transmission_permit,
)
from worktree_review.platform.cli.result import cli_result_document
from worktree_review.platform.cli.terminal import render_call_plan, render_text_report
from worktree_review.prompts import (
    PROMPT_SET_VERSION,
    load_prompt_layers,
)

app = typer.Typer(
    name="worktree-review",
    help="Review the worktree, not just the diff.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
    pretty_exceptions_show_locals=False,
)


class OutputFormat(StrEnum):
    TEXT = "text"
    JSON = "json"


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit(CliExitCode.PASSED)


@app.callback()
def _root(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Print the package version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Worktree Review local CLI."""


@app.command("prompts")
def show_prompts(
    dimension: Annotated[
        str,
        typer.Option(
            "--dimension",
            help="Dimension whose effective built-in prompt layers should be shown.",
        ),
    ] = "correctness",
) -> None:
    """Show the trusted, product-owned prompt hierarchy used by review dimensions."""

    typer.echo(f"Built-in prompt set: {PROMPT_SET_VERSION}")
    typer.echo(f"Dimension: {dimension}")
    for prompt_layer in load_prompt_layers(dimension):
        typer.echo(f"\nPrompt layer {prompt_layer.sequence}: {prompt_layer.resource_path}")
        typer.echo(prompt_layer.content)


@app.command()
def review(
    target: Annotated[
        str | None,
        typer.Option(
            "--target",
            help="Target ref to merge the current worktree into. Defaults to HEAD.",
        ),
    ] = None,
    commits: Annotated[
        int | None,
        typer.Option(
            "--commits",
            help=(
                "Review the last N commits plus current worktree changes "
                "(equivalent to --target HEAD~N)."
            ),
        ),
    ] = None,
    proposed: Annotated[
        str | None,
        typer.Option(
            "--proposed",
            help="Explicit committed proposed ref. Defaults to the current worktree snapshot.",
        ),
    ] = None,
    policy: Annotated[
        Path | None,
        typer.Option(
            "--policy",
            help="Optional Review Policy YAML. Defaults to the built-in policy.",
            exists=False,
            dir_okay=False,
        ),
    ] = None,
    compute_policy: Annotated[
        Path | None,
        typer.Option(
            "--compute-policy",
            help="Advanced Compute Policy YAML. Must sit outside the reviewed worktree.",
            exists=False,
            dir_okay=False,
        ),
    ] = None,
    config: Annotated[
        Path | None,
        typer.Option(
            "--config",
            help=(
                "Minimal provider configuration (URL/key or local CLI). "
                "Defaults to ~/.config/worktree-review/config.yaml."
            ),
            exists=False,
            dir_okay=False,
        ),
    ] = None,
    output_format: Annotated[
        OutputFormat,
        typer.Option("--format", help="text (default) or json (worktree-review.cli.result/v1)."),
    ] = OutputFormat.TEXT,
    repository: Annotated[
        Path,
        typer.Option("--repository", help="Git worktree to review. Defaults to cwd."),
    ] = Path("."),
) -> None:
    """Review current worktree changes or an explicitly selected Git commit."""

    configure_logging(json_output=output_format is OutputFormat.JSON)

    async def _run() -> ReviewReport:
        prepared = await prepare_cli_review(
            repository=repository,
            target_ref=target,
            recent_commit_count=commits,
            proposed_ref=proposed,
            policy_path=policy,
            compute_policy_path=compute_policy,
            config_path=config,
        )
        require_remote_transmission_permit(prepared.compute_policy)
        typer.secho(provider_transmission_disclosure(prepared.compute_policy), err=True)
        return await run_review_pipeline(
            ReviewRequest(
                resolved=prepared.resolved,
                review_policy=prepared.review_policy,
                review_policy_version=prepared.review_policy_version,
                compute_policy=prepared.compute_policy,
                compute_policy_version=prepared.compute_policy_version,
                surface="cli",
                provider_configuration=prepared.provider_configuration,
            ),
            on_call_plan_ready=lambda call_plan: typer.secho(
                render_call_plan(call_plan), err=True, nl=False
            ),
        )

    try:
        report = asyncio.run(_run())
    except InvalidInvocationError as exc:
        typer.secho(str(exc), err=True)
        raise typer.Exit(CliExitCode.INVALID_INVOCATION) from exc
    except WorktreeReviewError as exc:
        typer.secho(str(exc), err=True)
        raise typer.Exit(CliExitCode.ERROR) from exc

    if output_format is OutputFormat.JSON:
        document = cli_result_document(report)
        typer.echo(document.model_dump_json(by_alias=True, indent=2))
    else:
        typer.echo(render_text_report(report), nl=False)

    raise typer.Exit(int(exit_code_for_gate_state(report.gate_state)))


def main() -> int:
    """Map usage errors to exit 3 so bad flags are not confused with review Error.

    Typer vendors Click exception classes under ``typer._click``, so this matches
    on the public exception shape rather than import paths.
    """

    try:
        result = app(standalone_mode=False)
        return int(result) if isinstance(result, int) else 0
    except SystemExit:
        raise
    except Exception as exc:
        if type(exc).__name__ == "Exit":
            raise SystemExit(getattr(exc, "exit_code", 1)) from exc
        if type(exc).__name__ == "Abort":
            raise SystemExit(CliExitCode.INVALID_INVOCATION) from exc
        show = getattr(exc, "show", None)
        if callable(show):
            show()
            raise SystemExit(CliExitCode.INVALID_INVOCATION) from exc
        raise
