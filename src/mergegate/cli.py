"""``mergegate`` CLI surface (PRD §21.3; TECH-DESIGN D10)."""

from __future__ import annotations

import asyncio
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from mergegate import __version__
from mergegate.core.errors import InvalidInvocationError, MergeGateError
from mergegate.core.pipeline import ReviewRequest, run_review_pipeline
from mergegate.core.report import ReviewReport
from mergegate.observability import configure_logging
from mergegate.platform.cli.exit_codes import CliExitCode, exit_code_for_gate_state
from mergegate.platform.cli.invocation import prepare_cli_review
from mergegate.platform.cli.result import cli_result_document
from mergegate.platform.cli.terminal import render_text_report

app = typer.Typer(
    name="mergegate",
    help="Identity-bound merge-candidate review gate.",
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
    """MergeGate local CLI."""


@app.command()
def review(
    target: Annotated[
        str,
        typer.Option("--target", help="Target ref to merge the proposed head into."),
    ],
    proposed: Annotated[
        str,
        typer.Option(
            "--proposed",
            help="Committed proposed head. Defaults to HEAD.",
        ),
    ] = "HEAD",
    policy: Annotated[
        Path | None,
        typer.Option(
            "--policy",
            help="Review Policy YAML. Must sit outside the reviewed worktree.",
            exists=False,
            dir_okay=False,
        ),
    ] = None,
    compute_policy: Annotated[
        Path | None,
        typer.Option(
            "--compute-policy",
            help="Compute Policy YAML. Must sit outside the reviewed worktree.",
            exists=False,
            dir_okay=False,
        ),
    ] = None,
    output_format: Annotated[
        OutputFormat,
        typer.Option("--format", help="text (default) or json (mergegate.cli.result/v1)."),
    ] = OutputFormat.TEXT,
    repository: Annotated[
        Path,
        typer.Option("--repository", help="Git worktree to review. Defaults to cwd."),
    ] = Path("."),
) -> None:
    """Review a committed local head against an explicit target ref."""

    configure_logging(json_output=output_format is OutputFormat.JSON)

    async def _run() -> ReviewReport:
        prepared = await prepare_cli_review(
            repository=repository,
            target_ref=target,
            proposed_ref=proposed,
            policy_path=policy,
            compute_policy_path=compute_policy,
        )
        return await run_review_pipeline(
            ReviewRequest(
                resolved=prepared.resolved,
                review_policy=prepared.review_policy,
                review_policy_version=prepared.review_policy_version,
                compute_policy=prepared.compute_policy,
                compute_policy_version=prepared.compute_policy_version,
                surface="cli",
            )
        )

    try:
        report = asyncio.run(_run())
    except InvalidInvocationError as exc:
        typer.secho(str(exc), err=True)
        raise typer.Exit(CliExitCode.INVALID_INVOCATION) from exc
    except MergeGateError as exc:
        typer.secho(str(exc), err=True)
        raise typer.Exit(CliExitCode.ERROR) from exc

    if output_format is OutputFormat.JSON:
        document = cli_result_document(report)
        typer.echo(document.model_dump_json(by_alias=True, indent=2))
    else:
        typer.echo(render_text_report(report), nl=False)

    raise typer.Exit(int(exit_code_for_gate_state(report.gate_state)))


def main() -> None:
    """Map usage errors to exit 3 so bad flags are not confused with review Error.

    Typer vendors Click exception classes under ``typer._click``, so this matches
    on the public exception shape rather than import paths.
    """

    try:
        app(standalone_mode=False)
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
