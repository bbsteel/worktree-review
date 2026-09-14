"""Explicit local PostgreSQL for GitHub Gate integration tests.

Prefers ``WORKTREE_REVIEW_TEST_DATABASE_URL``, then testcontainers, then a
bundled PostgreSQL 16 binary extracted under ``~/tmp``. Data directories are
always created beneath ``~/tmp`` and only those paths are deleted.
"""

from __future__ import annotations

import io
import os
import socket
import subprocess
import tarfile
import tempfile
import time
import zipfile
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse, urlunparse

ZONKY_VERSION = "16.10.0"
ZONKY_JAR = (
    "https://repo1.maven.org/maven2/io/zonky/test/postgres/"
    f"embedded-postgres-binaries-linux-amd64/{ZONKY_VERSION}/"
    f"embedded-postgres-binaries-linux-amd64-{ZONKY_VERSION}.jar"
)
ZONKY_ROOT = Path.home() / "tmp" / "worktree-review-zonky-pg16"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _ensure_zonky_postgres() -> Path:
    postgres = ZONKY_ROOT / "bin" / "postgres"
    if postgres.is_file():
        return ZONKY_ROOT
    ZONKY_ROOT.mkdir(parents=True, exist_ok=True)
    jar_path = Path.home() / "tmp" / f"embedded-postgres-binaries-linux-amd64-{ZONKY_VERSION}.jar"
    if not jar_path.is_file():
        subprocess.run(
            ["curl", "-fsSL", "-o", str(jar_path), ZONKY_JAR],
            check=True,
            capture_output=True,
        )
    with zipfile.ZipFile(jar_path) as archive:
        member = next(name for name in archive.namelist() if name.endswith(".txz"))
        payload = archive.read(member)
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:xz") as tar:
        tar.extractall(ZONKY_ROOT, filter="data")
    if not postgres.is_file():
        raise RuntimeError(f"zonky postgres binary missing at {postgres}")
    return ZONKY_ROOT


def _postgres_env(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    lib_dir = root / "lib"
    current = env.get("LD_LIBRARY_PATH", "")
    env["LD_LIBRARY_PATH"] = f"{lib_dir}:{current}" if current else str(lib_dir)
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    return env


def start_embedded_postgres() -> tuple[str, subprocess.Popen[bytes], Path]:
    root = _ensure_zonky_postgres()
    env = _postgres_env(root)
    scratch_root = Path.home() / "tmp"
    scratch_root.mkdir(parents=True, exist_ok=True)
    data_dir = Path(tempfile.mkdtemp(prefix="wr-pg-data-", dir=scratch_root))
    if not str(data_dir).startswith(str(scratch_root)):
        raise RuntimeError(f"refusing to use non-tmp postgres data dir {data_dir}")
    initdb = root / "bin" / "initdb"
    postgres = root / "bin" / "postgres"
    subprocess.run(
        [
            str(initdb),
            "-D",
            str(data_dir),
            "-A",
            "trust",
            "-U",
            "postgres",
            "--encoding=UTF8",
            "--locale=C",
            "--no-sync",
        ],
        check=True,
        capture_output=True,
        env=env,
    )
    port = _free_port()
    process = subprocess.Popen(
        [
            str(postgres),
            "-D",
            str(data_dir),
            "-p",
            str(port),
            "-h",
            "127.0.0.1",
            "-c",
            "listen_addresses=127.0.0.1",
            "-c",
            "unix_socket_directories=",
            "-c",
            "fsync=off",
            "-c",
            "full_page_writes=off",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 15
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"embedded postgres exited with {process.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                url = f"postgresql://postgres@127.0.0.1:{port}/postgres"
                return url, process, data_dir
        except OSError:
            time.sleep(0.1)
    process.terminate()
    raise RuntimeError("embedded postgres did not become ready")


def stop_embedded_postgres(process: subprocess.Popen[bytes], data_dir: Path) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    # Delete only a verified scratch postgres data dir under ~/tmp, never
    # anything else: the parent, name prefix, and PG_VERSION must all match.
    scratch_root = (Path.home() / "tmp").resolve()
    resolved_dir = data_dir.resolve()
    if (
        resolved_dir.parent == scratch_root
        and resolved_dir.name.startswith("wr-pg-data-")
        and (resolved_dir / "PG_VERSION").is_file()
    ):
        subprocess.run(["rm", "-rf", "--", str(resolved_dir)], check=False)


def _try_testcontainers() -> tuple[str, object] | None:
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        return None
    # No Docker daemon: skip before constructing a container — start() would
    # leak the Docker client's unix socket and explode later as an
    # unraisable ResourceWarning under strict warnings.
    if not os.environ.get("DOCKER_HOST") and not Path("/var/run/docker.sock").exists():
        return None
    try:
        container = PostgresContainer("postgres:16-alpine")
        container.start()
        url = container.get_connection_url()
        if url.startswith("postgresql+psycopg2://"):
            url = "postgresql://" + url.removeprefix("postgresql+psycopg2://")
        return url, container
    except Exception:
        return None


def open_postgres_url() -> Iterator[str]:
    env_url = os.environ.get("WORKTREE_REVIEW_TEST_DATABASE_URL") or os.environ.get(
        "WORKTREE_REVIEW_DATABASE_URL"
    )
    if env_url:
        yield env_url
        return
    containers = _try_testcontainers()
    if containers is not None:
        url, container = containers
        try:
            yield url
        finally:
            container.stop()
        return
    url, process, data_dir = start_embedded_postgres()
    try:
        yield url
    finally:
        stop_embedded_postgres(process, data_dir)


def database_url_for_name(base_url: str, database: str) -> str:
    parsed = urlparse(base_url)
    return urlunparse(parsed._replace(path=f"/{database}"))
