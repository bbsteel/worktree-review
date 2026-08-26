"""``mergegate-server`` GitHub App process: webhook HTTP + embedded workers (D8, D12)."""

from __future__ import annotations


def main() -> None:
    """Console entry point. Requires the ``mergegate[server]`` extra."""

    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit(
            "mergegate-server requires the server extra: pip install 'mergegate[server]'"
        ) from exc

    uvicorn.run(
        "mergegate.server.app:app",
        host="0.0.0.0",
        port=8000,
        factory=False,
    )
