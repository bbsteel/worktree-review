"""GitHub webhook receiver mapping. HMAC validation and event dispatch land later."""

from mergegate.core.errors import UnimplementedStageError


async def handle_github_webhook(*, payload: bytes, signature_header: str | None) -> None:
    raise UnimplementedStageError("GitHub webhook handling is not implemented")
