"""server.storage — where generated memos live and how clients fetch them.

LocalStorage (self-host): files on disk, served by the download route.
S3Storage (SaaS): files in S3, handed to clients as short-lived presigned URLs so
the private backend is never exposed.
"""

from __future__ import annotations

import shutil
from functools import lru_cache
from pathlib import Path

from .config import get_settings


class LocalStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root)

    def save(self, job_id: str, artifacts: dict[str, str]) -> dict[str, str]:
        dest_dir = self.root / job_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        keys: dict[str, str] = {}
        for fmt, src in artifacts.items():
            name = Path(src).name
            shutil.copyfile(src, dest_dir / name)
            keys[fmt] = f"{job_id}/{name}"
        return keys

    def resolve_path(self, key: str) -> str | None:
        path = self.root / key
        return str(path) if path.is_file() else None

    def presigned_url(self, key: str) -> str | None:
        return None  # local mode serves via the download route


class S3Storage:
    def __init__(self, bucket: str, region: str, prefix: str, ttl: int) -> None:
        import boto3

        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.ttl = ttl
        self._s3 = boto3.client("s3", region_name=region)

    def _s3_key(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key

    def save(self, job_id: str, artifacts: dict[str, str]) -> dict[str, str]:
        keys: dict[str, str] = {}
        for fmt, src in artifacts.items():
            name = Path(src).name
            key = f"{job_id}/{name}"
            self._s3.upload_file(src, self.bucket, self._s3_key(key))
            keys[fmt] = key
        return keys

    def resolve_path(self, key: str) -> str | None:
        return None  # S3 mode never serves from local disk

    def presigned_url(self, key: str) -> str | None:
        return self._s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": self._s3_key(key)},
            ExpiresIn=self.ttl,
        )


@lru_cache
def get_storage():
    s = get_settings()
    if s.storage_backend == "s3":
        return S3Storage(s.s3_bucket, s.s3_region, s.s3_prefix, s.signed_url_ttl)
    return LocalStorage(s.storage_dir)
