"""server.storage — where generated memos live and how clients fetch them.

LocalStorage (self-host): files on disk, served by the download route.
S3Storage (S3/R2): files in an S3-compatible bucket, handed to clients as
short-lived presigned URLs so the private backend is never exposed.
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
    def __init__(
        self,
        bucket: str,
        region: str,
        prefix: str,
        ttl: int,
        endpoint_url: str = "",
        access_key_id: str = "",
        secret_access_key: str = "",
    ) -> None:
        import boto3

        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.ttl = ttl
        # endpoint_url + explicit keys target an S3-compatible store (Cloudflare R2,
        # MinIO). Left empty, boto3 hits AWS S3 with the default credential chain.
        client_kwargs: dict = {"region_name": region}
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
        if access_key_id and secret_access_key:
            client_kwargs["aws_access_key_id"] = access_key_id
            client_kwargs["aws_secret_access_key"] = secret_access_key
        self._s3 = boto3.client("s3", **client_kwargs)

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
        return S3Storage(
            s.s3_bucket,
            s.s3_region,
            s.s3_prefix,
            s.signed_url_ttl,
            s.s3_endpoint_url,
            s.s3_access_key_id,
            s.s3_secret_access_key,
        )
    return LocalStorage(s.storage_dir)
