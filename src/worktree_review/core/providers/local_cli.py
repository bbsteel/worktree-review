"""Local command provider with explicit stdin and structured-output adapters."""

from __future__ import annotations

import asyncio
import json
import re
from typing import cast

from worktree_review.core.config import LocalCliAdapterName
from worktree_review.core.errors import ProviderError
from worktree_review.core.provider import (
    DEFAULT_MAX_OUTPUT_TOKENS_PER_CALL,
    UsageKind,
    UsageRecord,
    estimate_input_tokens_for_model,
)

_LOCAL_CLI_DIAGNOSTIC_LIMIT = 4096
_JSON_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


class LocalCliProvider:
    """Call a user-selected command without invoking a shell.

    ``worktree-json`` is the strict adapter used for backwards compatibility:
    the command receives one JSON request on stdin and writes one JSON findings
    object to stdout. ``prompt-json`` sends a rendered prompt on stdin and
    expects one JSON object. ``prompt-text-json`` accepts a JSON object either
    directly or inside a Markdown fence, which covers CLIs that add light
    presentation around structured output.
    """

    def __init__(
        self,
        *,
        command: tuple[str, ...],
        model: str | None = None,
        adapter: LocalCliAdapterName = "worktree-json",
        timeout_seconds: float = 600.0,
    ) -> None:
        if not command:
            raise ValueError("local CLI provider command must not be empty")
        self.provider_name = "local-cli"
        self.model = model or command[0]
        self._command = command
        self._adapter = adapter
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
        request_payload = self._request_payload(
            system=system,
            user=user,
            response_schema=response_schema,
            dimension_id=dimension_id,
            max_output_tokens=max_output_tokens,
        )
        try:
            process = await asyncio.create_subprocess_exec(
                *self._command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            communication_task = asyncio.create_task(process.communicate(request_payload))
            try:
                stdout, stderr = await asyncio.wait_for(
                    asyncio.shield(communication_task), timeout=self._timeout_seconds
                )
            except TimeoutError as exc:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                stdout, stderr = await communication_task
                raise ProviderError(
                    f"local CLI provider timed out for dimension {dimension_id}; "
                    f"stderr: {_safe_diagnostic(stderr)}; stdout: {_safe_diagnostic(stdout)}"
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
                f"for dimension {dimension_id}; stderr: {_safe_diagnostic(stderr)}"
                + (f"; stdout: {_safe_diagnostic(stdout)}" if stdout.strip() else "")
            )
        try:
            stdout_text = stdout.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProviderError(
                f"local CLI provider returned non-UTF-8 output for dimension {dimension_id}; "
                f"stderr: {_safe_diagnostic(stderr)}; stdout: {_safe_diagnostic(stdout)}"
            ) from exc
        try:
            decoded_payload = self._parse_output(stdout_text)
        except ValueError as exc:
            raise ProviderError(
                f"local CLI provider returned invalid JSON for dimension {dimension_id}; "
                f"stderr: {_safe_diagnostic(stderr)}; stdout: {_safe_diagnostic(stdout)}"
            ) from exc
        if not isinstance(decoded_payload, dict):
            raise ProviderError(
                f"local CLI provider returned a non-object for dimension {dimension_id}; "
                f"stderr: {_safe_diagnostic(stderr)}; stdout: {_safe_diagnostic(stdout)}"
            )
        return cast(dict[str, object], decoded_payload), UsageRecord(
            kind=UsageKind.DECLARED,
            provider=self.provider_name,
            model=self.model,
            note=f"local CLI adapter {self._adapter} did not report token usage",
        )

    def _request_payload(
        self,
        *,
        system: str,
        user: str,
        response_schema: dict[str, object],
        dimension_id: str,
        max_output_tokens: int,
    ) -> bytes:
        if self._adapter == "worktree-json":
            return json.dumps(
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
        return (
            f"Review dimension: {dimension_id}\n"
            f"Maximum output tokens: {max_output_tokens}\n"
            "Return only one JSON object matching this response schema.\n"
            f"Response schema:\n{json.dumps(response_schema, ensure_ascii=False, indent=2)}\n\n"
            f"System instructions:\n{system}\n\n"
            f"Review request:\n{user}"
        ).encode()

    def _parse_output(self, stdout_text: str) -> object:
        if self._adapter != "prompt-text-json":
            return json.loads(stdout_text)

        candidate_payloads = [match.group(1) for match in _JSON_FENCE_PATTERN.finditer(stdout_text)]
        candidate_payloads.append(stdout_text)
        decoder = json.JSONDecoder()
        for candidate_payload in candidate_payloads:
            try:
                return json.loads(candidate_payload)
            except json.JSONDecodeError:
                pass
            for character_index, character in enumerate(candidate_payload):
                if character != "{":
                    continue
                try:
                    parsed_payload, _end_index = decoder.raw_decode(
                        candidate_payload[character_index:]
                    )
                except json.JSONDecodeError:
                    continue
                return parsed_payload
        raise ValueError("no JSON object found")


def _safe_diagnostic(raw_output: bytes) -> str:
    """Bound and escape child-process output before it enters an error message."""

    decoded_output = raw_output.decode("utf-8", errors="replace")
    escaped_output = "".join(
        character
        if character == "\t" or (0x20 <= ord(character) <= 0x7E) or ord(character) >= 0xA0
        else "\\n"
        if character == "\n"
        else f"\\x{ord(character):02x}"
        for character in decoded_output
    )
    if not escaped_output:
        return "<empty>"
    if len(escaped_output) > _LOCAL_CLI_DIAGNOSTIC_LIMIT:
        return escaped_output[:_LOCAL_CLI_DIAGNOSTIC_LIMIT] + "…"
    return escaped_output
