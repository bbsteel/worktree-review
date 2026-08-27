"""OpenAI structured-output client."""

from __future__ import annotations

from typing import cast

from mergegate.core.errors import ProviderError
from mergegate.core.provider import (
    UsageKind,
    UsageRecord,
    estimate_input_tokens_for_model,
)


class OpenAIProvider:
    def __init__(self, *, model: str, api_key: str) -> None:
        self.provider_name = "openai"
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
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise ProviderError("the openai package is not installed") from exc

        client = AsyncOpenAI(api_key=self._api_key)
        usage_record: UsageRecord | None = None
        try:
            response = await client.chat.completions.create(
                model=self.model,
                max_tokens=8192,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "dimension_findings",
                        "strict": True,
                        "schema": response_schema,
                    },
                },
            )
            usage = response.usage
            usage_record = UsageRecord(
                kind=UsageKind.MEASURED,
                input_tokens=usage.prompt_tokens if usage is not None else None,
                output_tokens=usage.completion_tokens if usage is not None else None,
                provider=self.provider_name,
                model=self.model,
                note="openai chat.completions usage",
            )
            if not response.choices:
                raise ProviderError(
                    f"openai returned no choices for dimension {dimension_id}",
                    usage=usage_record,
                )
            content = response.choices[0].message.content
            if not content:
                raise ProviderError(
                    f"openai returned empty content for dimension {dimension_id}",
                    usage=usage_record,
                )
            import json

            payload = json.loads(content)
            if not isinstance(payload, dict):
                raise ProviderError(
                    f"openai JSON payload is not an object for {dimension_id}",
                    usage=usage_record,
                )
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(
                f"openai structured completion failed for {dimension_id}: {exc}",
                usage=usage_record,
            ) from exc
        return cast(dict[str, object], payload), usage_record
