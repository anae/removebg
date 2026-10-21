"""Private, local processing archive."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")


def safe_client_filename(value: str | None) -> str:
    name = Path(value or "image").name.replace("\x00", "")
    name = SAFE_NAME.sub("_", name).strip(" .")
    return (name or "image")[:120]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Archive:
    def __init__(self, root: Path, retention_days: int, save_originals: bool) -> None:
        self.root = root
        self.retention_days = max(0, retention_days)
        self.save_originals = save_originals
        self.root.mkdir(parents=True, exist_ok=True)
        self._last_cleanup = 0.0

    def store(
        self,
        *,
        job_id: str,
        original_png: bytes,
        result_png: bytes,
        metadata: dict[str, Any],
    ) -> Path:
        now = datetime.now(UTC)
        target = self.root / now.strftime("%Y-%m-%d") / job_id
        target.mkdir(parents=True, exist_ok=False)

        if self.save_originals:
            self._atomic_write(target / "original.png", original_png)
        self._atomic_write(target / "removed.png", result_png)

        record = {
            **metadata,
            "job_id": job_id,
            "created_at": now.isoformat(),
            "original_saved": self.save_originals,
            "original_sha256": sha256(original_png),
            "result_sha256": sha256(result_png),
        }
        self._atomic_write(
            target / "metadata.json",
            json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        self.cleanup_if_due()
        return target

    def cleanup_if_due(self) -> None:
        if self.retention_days == 0 or time.monotonic() - self._last_cleanup < 3600:
            return
        self._last_cleanup = time.monotonic()
        cutoff = time.time() - self.retention_days * 86400

        for day_directory in self.root.iterdir():
            if not day_directory.is_dir() or day_directory.is_symlink():
                continue
            for job_directory in day_directory.iterdir():
                if (
                    job_directory.is_dir()
                    and not job_directory.is_symlink()
                    and job_directory.stat().st_mtime < cutoff
                ):
                    shutil.rmtree(job_directory)
            try:
                day_directory.rmdir()
            except OSError:
                pass

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)

