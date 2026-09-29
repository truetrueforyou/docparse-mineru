from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class OcrMode(StrEnum):
    AUTO = "auto"
    FORCE = "force"
    DISABLE = "disable"


class DeviceMode(StrEnum):
    AUTO = "auto"
    NPU = "npu"
    CPU = "cpu"


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class FileKind(StrEnum):
    PDF = "pdf"
    IMAGE = "image"
    DOCX = "docx"
    PPTX = "pptx"
    XLSX = "xlsx"
    UNSUPPORTED = "unsupported"


class WarningItem(BaseModel):
    code: str
    message: str


class ArtifactPaths(BaseModel):
    markdown: str | None = None
    content_list: str | None = None
    middle: str | None = None
    images_dir: str | None = None


class TaskResult(BaseModel):
    schema_version: str = "2.0"
    task_id: str
    file_id: str
    file_name: str
    file_type: str
    engine: str = "mineru"
    engine_version: str = "3.4"
    status: TaskStatus = TaskStatus.SUCCEEDED
    metadata: dict = Field(default_factory=dict)
    artifacts: ArtifactPaths = Field(default_factory=ArtifactPaths)
    warnings: list[WarningItem] = Field(default_factory=list)


@dataclass
class MinerUArtifacts:
    markdown: str
    content_list_bytes: bytes | None
    middle_bytes: bytes | None
    image_files: list[tuple[str, Path]]
    warnings: list[WarningItem]
    metadata: dict
