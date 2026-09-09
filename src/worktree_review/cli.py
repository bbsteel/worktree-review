"""``worktree-review`` CLI surface (PRD §21.3; TECH-DESIGN D10)."""

from __future__ import annotations

import asyncio
import os
import shlex
import shutil
import sys
import time
from enum import StrEnum
from pathlib import Path
from typing import Annotated, NoReturn

import typer
import yaml

from worktree_review import __version__
from worktree_review.application.review_service import ReviewApplicationService
from worktree_review.core.config import (
    DEFAULT_REMOTE_MODELS,
    DEFAULT_USER_CONFIG_VERSION,
    USER_CONFIG_DOCUMENT_ID,
    LocalCliAdapterName,
    UserConfiguration,
)
from worktree_review.core.errors import InvalidInvocationError, WorktreeReviewError
from worktree_review.core.pipeline import ReviewRequest
from worktree_review.core.report import ReviewProgressEvent, ReviewReport
from worktree_review.observability import configure_logging
from worktree_review.platform.cli.exit_codes import CliExitCode, exit_code_for_gate_state
from worktree_review.platform.cli.invocation import (
    USER_CONFIG_FILENAME,
    default_config_dir,
    prepare_cli_review,
    provider_transmission_disclosure,
    require_provider_transmission_permit,
)
from worktree_review.platform.cli.result import cli_result_document
from worktree_review.platform.cli.terminal import (
    render_call_plan,
    render_progress,
    render_text_report,
)
from worktree_review.prompts import (
    PROMPT_SET_VERSION,
    load_prompt_layers,
)

app = typer.Typer(
    name="worktree-review",
    help="Review the worktree, not just the diff.",
    no_args_is_help=False,
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


@app.callback(invoke_without_command=True)
def _root(
    context: typer.Context,
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

    if context.invoked_subcommand is None:
        context.invoke(review)


_LOCAL_CLI_ADAPTERS: tuple[LocalCliAdapterName, ...] = (
    "worktree-json",
    "prompt-json",
    "prompt-text-json",
)


def _write_progress(progress_event: ReviewProgressEvent) -> None:
    typer.secho(render_progress(progress_event), err=True, nl=False)


def _init_failure(message: str) -> NoReturn:
    typer.secho(message, err=True)
    raise typer.Exit(CliExitCode.INVALID_INVOCATION)


def _resolved_local_executable(command: tuple[str, ...]) -> str | None:
    executable = command[0]
    if "/" in executable:
        executable_path = Path(executable).expanduser()
        if executable_path.is_file() and os.access(executable_path, os.X_OK):
            return str(executable_path)
        return None
    return shutil.which(executable)


@app.command("init")
def initialize_configuration(
    provider: Annotated[
        str | None,
        typer.Option("--provider", help="anthropic, openai, or local-cli."),
    ] = None,
    key: Annotated[
        str | None,
        typer.Option("--key", help="Remote API key or an exact ${ENV_VAR} reference."),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", help="Optional provider model identifier."),
    ] = None,
    url: Annotated[
        str | None,
        typer.Option("--url", help="Optional remote API URL."),
    ] = None,
    command: Annotated[
        str | None,
        typer.Option(
            "--command",
            help="Local command in shell-like argv form; it is stored without shell execution.",
        ),
    ] = None,
    adapter: Annotated[
        str,
        typer.Option(
            "--adapter",
            help="Local adapter: worktree-json, prompt-json, or prompt-text-json.",
        ),
    ] = "worktree-json",
    data_destination: Annotated[
        str | None,
        typer.Option("--data-destination", help="Optional local-command destination disclosure."),
    ] = None,
    known_retention: Annotated[
        str | None,
        typer.Option("--known-retention", help="Optional local-command retention disclosure."),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Config path. Defaults to the user config directory."),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Replace an existing configuration file."),
    ] = False,
) -> None:
    """Interactively create and validate the trusted default provider configuration."""

    provider_name = provider or typer.prompt(
        "Provider (anthropic, openai, or local-cli)", default="anthropic"
    )
    if provider_name not in ("anthropic", "openai", "local-cli"):
        _init_failure(f"unsupported provider: {provider_name}")

    configuration_document: dict[str, object] = {
        "schema": USER_CONFIG_DOCUMENT_ID,
        "version": DEFAULT_USER_CONFIG_VERSION,
        "provider": provider_name,
    }
    if provider_name in ("anthropic", "openai"):
        provider_environment_name = (
            "ANTHROPIC_API_KEY" if provider_name == "anthropic" else "OPENAI_API_KEY"
        )
        default_key_reference = (
            f"${{{provider_environment_name}}}"
            if os.environ.get(provider_environment_name)
            else None
        )
        resolved_key = key
        if resolved_key is None:
            resolved_key = typer.prompt(
                f"{provider_name} API key (or ${{ENV_VAR}})",
                default=default_key_reference,
                hide_input=True,
            )
        if not resolved_key.strip():
            _init_failure("remote provider key must not be empty")
        configuration_document["key"] = resolved_key
        selected_model = model or typer.prompt(
            "Model", default=DEFAULT_REMOTE_MODELS[provider_name]
        )
        configuration_document["model"] = selected_model
        selected_url = url
        if selected_url is None:
            selected_url = typer.prompt("API URL (blank for the standard endpoint)", default="")
        if selected_url.strip():
            configuration_document["url"] = selected_url.strip()
        display_target = selected_url.strip() or "provider standard endpoint"
        verification_message = (
            f"Key recorded for {provider_name}; no network request was made. Destination: "
            f"{display_target}."
        )
    else:
        local_command_text = command or typer.prompt(
            "Local command (shell-like argv, for example: claude --print)"
        )
        try:
            local_command = tuple(shlex.split(local_command_text))
        except ValueError as exc:
            _init_failure(f"local command could not be parsed: {exc}")
        if not local_command:
            _init_failure("local command must not be empty")
        if adapter not in _LOCAL_CLI_ADAPTERS:
            _init_failure(f"unsupported local CLI adapter: {adapter}")
        executable_path = _resolved_local_executable(local_command)
        if executable_path is None:
            _init_failure(
                f"local command executable was not found or is not executable: {local_command[0]}"
            )
        configuration_document["command"] = list(local_command)
        configuration_document["adapter"] = adapter
        if model is not None:
            configuration_document["model"] = model
        if data_destination is not None:
            configuration_document["data_destination"] = data_destination
        if known_retention is not None:
            configuration_document["known_retention"] = known_retention
        verification_message = (
            f"Found local command executable {executable_path}; it was not run. "
            "Review content will be handed to this command."
        )

    try:
        UserConfiguration.model_validate(configuration_document)
    except Exception as exc:
        _init_failure(f"generated configuration is invalid: {exc}")

    configuration_path = (output or (default_config_dir() / USER_CONFIG_FILENAME)).expanduser()
    if configuration_path.exists() and not force:
        _init_failure(
            f"configuration already exists: {configuration_path}; pass --force to replace it"
        )
    if configuration_path.is_symlink():
        _init_failure(f"refusing to write through symbolic link: {configuration_path}")
    try:
        configuration_path.parent.mkdir(parents=True, exist_ok=True)
        configuration_path.write_text(
            yaml.safe_dump(configuration_document, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        configuration_path.chmod(0o600)
    except OSError as exc:
        _init_failure(f"cannot write configuration {configuration_path}: {exc}")
    typer.echo(f"Wrote {configuration_path}")
    typer.echo(f"Provider: {provider_name}")
    typer.echo(verification_message)


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
        preparation_started_at = time.monotonic()
        _write_progress(
            ReviewProgressEvent(
                phase="stage",
                name="prepare-review-inputs",
                status="started",
                elapsed_seconds=0,
            )
        )
        try:
            prepared = await prepare_cli_review(
                repository=repository,
                target_ref=target,
                recent_commit_count=commits,
                proposed_ref=proposed,
                policy_path=policy,
                compute_policy_path=compute_policy,
                config_path=config,
            )
        except Exception:
            _write_progress(
                ReviewProgressEvent(
                    phase="stage",
                    name="prepare-review-inputs",
                    status="failed",
                    elapsed_seconds=max(0.0, time.monotonic() - preparation_started_at),
                )
            )
            raise
        _write_progress(
            ReviewProgressEvent(
                phase="stage",
                name="prepare-review-inputs",
                status="completed",
                elapsed_seconds=max(0.0, time.monotonic() - preparation_started_at),
            )
        )
        require_provider_transmission_permit(prepared.compute_policy)
        typer.secho(provider_transmission_disclosure(prepared.compute_policy), err=True)
        return await ReviewApplicationService().execute(
            ReviewRequest(
                resolved=prepared.resolved,
                review_policy=prepared.review_policy,
                review_policy_version=prepared.review_policy_version,
                compute_policy=prepared.compute_policy,
                compute_policy_version=prepared.compute_policy_version,
                surface="cli",
                provider_configuration=prepared.provider_configuration,
            ),
            repository_path=prepared.repository_path,
            on_call_plan_ready=lambda call_plan: typer.secho(
                render_call_plan(call_plan), err=True, nl=False
            ),
            on_progress=_write_progress,
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

    command_arguments = sys.argv[1:]
    known_root_argument = command_arguments and command_arguments[0] in {
        "review",
        "init",
        "prompts",
        "--help",
        "-h",
        "--version",
    }
    if known_root_argument:
        resolved_arguments = command_arguments
    elif command_arguments:
        resolved_arguments = ["review", *command_arguments]
    else:
        resolved_arguments = ["review"]
    try:
        result = app(args=resolved_arguments, standalone_mode=False)
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
