"""Local command provider using a deliberately narrow JSON stdin/stdout protocol."""

from __future__ import annotations

import asyncio
import json
from typing import cast

from worktree_review.core.errors import ProviderError
from worktree_review.core.provider import (
    DEFAULT_MAX_OUTPUT_TOKENS_PER_CALL,
    UsageKind,
    UsageRecord,
    estimate_input_tokens_for_model,
)


class LocalCliProvider:
    """Call a user-selected local review command without invoking a shell.

    The command receives one JSON request on stdin with ``system``, ``user``,
    ``response_schema``, ``dimension_id``, and ``max_output_tokens`` fields. It
    must write one JSON findings object to stdout and exit successfully.
    """

    def __init__(
        self,
        *,
        command: tuple[str, ...],
        model: str | None = None,
        timeout_seconds: float = 600.0,
    ) -> None:
        if not command:
            raise ValueError("local CLI provider command must not be empty")
        self.provider_name = "local-cli"
        self.model = model or command[0]
        self._command = command
        self._timeout_seconds = timeout_seconds

    def estimate_input_tokens(self, text: str) -> UsageRecord:
        tokens, note = estimate_input_tokens_for_model(text, self.model)
        return UsageRecord(
            kind=UsageKind.ESTIMATED,
            input_tokens=tokens,
            provider=self.provider_name,
            model=self.model,
            note=note,
        )

    async def complete_structured(
        self,
        *,
        system: str,
        user: str,
        response_schema: dict[str, object],
        dimension_id: str,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS_PER_CALL,
    ) -> tuple[dict[str, object], UsageRecord]:
        request_payload = json.dumps(
            {
                "system": system,
                "user": user,
                "response_schema": response_schema,
                "dimension_id": dimension_id,
                "max_output_tokens": max_output_tokens,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            process = await asyncio.create_subprocess_exec(
                *self._command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, _stderr = await asyncio.wait_for(
                    process.communicate(request_payload),
                    timeout=self._timeout_seconds,
                )
            except TimeoutError as exc:
                process.kill()
                await process.wait()
                raise ProviderError(
                    f"local CLI provider timed out for dimension {dimension_id}"
                ) from exc
        except ProviderError:
            raise
        except OSError as exc:
            raise ProviderError(
                f"local CLI provider could not start for dimension {dimension_id}"
            ) from exc

        if process.returncode != 0:
            raise ProviderError(
                f"local CLI provider exited with status {process.returncode} "
                f"for dimension {dimension_id}"
            )
        try:
            decoded_payload = json.loads(stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderError(
                f"local CLI provider returned invalid JSON for dimension {dimension_id}"
            ) from exc
        if not isinstance(decoded_payload, dict):
            raise ProviderError(
                f"local CLI provider returned a non-object for dimension {dimension_id}"
            )
        return cast(dict[str, object], decoded_payload), UsageRecord(
            kind=UsageKind.DECLARED,
            provider=self.provider_name,
            model=self.model,
            note="local CLI provider did not report token usage",
        )
