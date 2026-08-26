"""GitHub Checks API publication, including attempt-id fingerprints (D9, D13)."""

from mergegate.core.errors import UnimplementedStageError
from mergegate.core.report import ReviewReport


async def publish_check_run(report: ReviewReport) -> None:
    raise UnimplementedStageError("GitHub check-run publication is not implemented")
