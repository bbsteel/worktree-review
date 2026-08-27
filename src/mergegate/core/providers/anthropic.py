"""Anthropic tool-use structured-output client."""

from __future__ import annotations

from typing import Any, cast

from mergegate.core.errors import ProviderError
from mergegate.core.provider import (
    UsageKind,
    UsageRecord,
    estimate_input_tokens_for_model,
)


class AnthropicProvider:
    def __init__(self, *, model: str, api_key: str) -> None:
        self.provider_name = "anthropic"
        self.model = model
        self._api_key = api_key

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
    ) -> tuple[dict[str, object], UsageRecord]:
        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:
            raise ProviderError("the anthropic package is not installed") from exc

        client = AsyncAnthropic(api_key=self._api_key)
        usage_record: UsageRecord | None = None
        try:
            response = await client.messages.create(
                model=self.model,
                max_tokens=8192,
                system=system,
                messages=[{"role": "user", "content": user}],
                tools=[
                    {
                        "name": "record_findings",
                        "description": "Record review findings for this dimension.",
                        "input_schema": response_schema,
                    }
                ],
                tool_choice={"type": "tool", "name": "record_findings"},
            )
            usage = response.usage
            input_tokens = getattr(usage, "input_tokens", None)
            output_tokens = getattr(usage, "output_tokens", None)
            usage_record = UsageRecord(
                kind=UsageKind.MEASURED,
                input_tokens=input_tokens if isinstance(input_tokens, int) else None,
                output_tokens=output_tokens if isinstance(output_tokens, int) else None,
                provider=self.provider_name,
                model=self.model,
                note="anthropic messages usage",
            )
            payload: dict[str, Any] | None = None
            for block in response.content:
                is_findings_tool = (
                    getattr(block, "type", None) == "tool_use"
                    and getattr(block, "name", None) == "record_findings"
                )
                if is_findings_tool:
                    raw = getattr(block, "input", None)
                    if isinstance(raw, dict):
                        payload = raw
                        break
            if payload is None:
                raise ProviderError(
                    f"anthropic returned no record_findings tool use for {dimension_id}",
                    usage=usage_record,
                )
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(
                f"anthropic structured completion failed for {dimension_id}: {exc}",
                usage=usage_record,
            ) from exc
        return cast(dict[str, object], payload), usage_record
