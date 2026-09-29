from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from docparse_service.config import Settings


class ObjectStorage:
    def put_bytes(self, key: str, data: bytes, content_type: str) -> str:
        raise NotImplementedError

    def get_bytes(self, key: str) -> bytes:
        raise NotImplementedError


class LocalObjectStorage(ObjectStorage):
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, key: str, data: bytes, content_type: str) -> str:
        _ = content_type
        target = self._resolve_under_root(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return f"local://{key}"

    def get_bytes(self, key: str) -> bytes:
        return self._resolve_under_root(key).read_bytes()

    def _resolve_under_root(self, key: str) -> Path:
        key_path = Path(key)
        if key_path.is_absolute() or ".." in key_path.parts:
            raise ValueError("INVALID_STORAGE_KEY")
        root = self.root.resolve()
        target = (root / key).resolve()
        if not target.is_relative_to(root):
            raise ValueError("INVALID_STORAGE_KEY")
        return target


class MinioObjectStorage(ObjectStorage):
    def __init__(
        self,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool = False,
    ) -> None:
        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            use_ssl=secure,
        )
        self._ensure_bucket()

    def put_bytes(self, key: str, data: bytes, content_type: str) -> str:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
        return f"minio://{self.bucket}/{key}"

    def get_bytes(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()

    def _ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self.client.create_bucket(Bucket=self.bucket)


def make_storage(settings: Settings) -> ObjectStorage:
    if settings.storage_backend == "minio":
        return MinioObjectStorage(
            endpoint_url=settings.minio_endpoint_url,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            bucket=settings.minio_bucket,
            secure=settings.minio_secure,
        )
    return LocalObjectStorage(settings.local_storage_path)
