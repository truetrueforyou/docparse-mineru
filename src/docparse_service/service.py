import json
import mimetypes
import tempfile
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from docparse_service.config import Settings
from docparse_service.db import ParseTask
from docparse_service.engines import MinerUEngine
from docparse_service.file_types import detect_file_kind, is_supported
from docparse_service.schemas import (
    ArtifactPaths,
    DeviceMode,
    FileKind,
    OcrMode,
    TaskResult,
    TaskStatus,
)
from docparse_service.storage import ObjectStorage, make_storage


def _guess_mime(name: str) -> str:
    mime, _ = mimetypes.guess_type(name)
    return mime or "application/octet-stream"


class ParseService:
    def __init__(self, settings: Settings, session_factory: sessionmaker[Session]) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.storage: ObjectStorage = make_storage(settings)
        self.engine = MinerUEngine(
            command=settings.mineru_command,
            extra_args=settings.mineru_extra_args,
            device=settings.mineru_device,
            cpu_extra_args=settings.mineru_cpu_extra_args,
            npu_extra_args=settings.mineru_npu_extra_args,
            disable_npu_probe=settings.disable_npu_probe,
        )

    def create_task(
        self,
        filename: str,
        content_type: str | None,
        content: bytes,
    ) -> ParseTask:
        file_kind = detect_file_kind(filename, content_type)
        if not is_supported(file_kind):
            raise ValueError("UNSUPPORTED_FILE_TYPE")
        if len(content) > self.settings.max_file_size_mb * 1024 * 1024:
            raise ValueError("FILE_TOO_LARGE")

        task_id = uuid4().hex
        file_id = uuid4().hex
        input_key = f"tasks/{task_id}/input/{filename}"
        self.storage.put_bytes(input_key, content, content_type or "application/octet-stream")

        with self.session_factory() as session:
            task = ParseTask(
                task_id=task_id,
                file_id=file_id,
                file_name=filename,
                file_type=file_kind.value,
                engine="mineru",
                status=TaskStatus.QUEUED.value,
                input_key=input_key,
            )
            session.add(task)
            session.commit()
            session.refresh(task)
            return task

    def run_task(
        self,
        task_id: str,
        ocr: OcrMode,
        device_override: DeviceMode | None = None,
    ) -> None:
        with self.session_factory() as session:
            task = session.get(ParseTask, task_id)
            if task is None:
                return
            task.status = TaskStatus.RUNNING.value
            session.commit()
            try:
                content = self.storage.get_bytes(task.input_key)
                result = self._parse_and_persist(task, content, ocr, device_override)
                prefix = f"tasks/{task.task_id}/result"
                task.status = TaskStatus.SUCCEEDED.value
                task.result_key = f"{prefix}/result.json"
                task.markdown_key = result.artifacts.markdown
                task.content_list_key = result.artifacts.content_list
                task.middle_key = result.artifacts.middle
                task.images_prefix = result.artifacts.images_dir
                task.error_code = None
                task.error_message = None
            except Exception as exc:  # noqa: BLE001 - store operational failure as task failure
                task.status = TaskStatus.FAILED.value
                task.error_code = "ENGINE_FAILED"
                task.error_message = str(exc)
            finally:
                session.commit()

    def get_task(self, task_id: str) -> ParseTask | None:
        with self.session_factory() as session:
            return session.get(ParseTask, task_id)

    def get_result(self, task_id: str) -> dict:
        task = self.get_task(task_id)
        if task is None or task.result_key is None:
            raise KeyError(task_id)
        return json.loads(self.storage.get_bytes(task.result_key).decode("utf-8"))

    def get_markdown(self, task_id: str) -> str:
        task = self.get_task(task_id)
        if task is None or task.markdown_key is None:
            raise KeyError(task_id)
        return self.storage.get_bytes(task.markdown_key).decode("utf-8")

    def get_content_list(self, task_id: str) -> bytes:
        task = self.get_task(task_id)
        if task is None or task.content_list_key is None:
            raise KeyError(task_id)
        return self.storage.get_bytes(task.content_list_key)

    def get_middle(self, task_id: str) -> bytes:
        task = self.get_task(task_id)
        if task is None or task.middle_key is None:
            raise KeyError(task_id)
        return self.storage.get_bytes(task.middle_key)

    def get_asset(self, task_id: str, relative_path: str) -> bytes:
        task = self.get_task(task_id)
        if task is None or task.images_prefix is None:
            raise KeyError(task_id)
        if ".." in Path(relative_path).parts:
            raise ValueError("INVALID_ASSET_PATH")
        key = f"{task.images_prefix.rstrip('/')}/{relative_path.lstrip('/')}"
        prefix = task.images_prefix if task.images_prefix.endswith("/") else f"{task.images_prefix}/"
        if not key.startswith(prefix):
            raise ValueError("INVALID_ASSET_PATH")
        return self.storage.get_bytes(key)

    def _parse_and_persist(
        self,
        task: ParseTask,
        content: bytes,
        ocr: OcrMode,
        device_override: DeviceMode | None,
    ) -> TaskResult:
        prefix = f"tasks/{task.task_id}/result"
        previous_device = self.engine.device
        if device_override is not None:
            self.engine.device = device_override.value
        try:
            with tempfile.TemporaryDirectory(prefix="docparse-") as tmp:
                input_path = Path(tmp) / task.file_name
                input_path.write_bytes(content)
                arts = self.engine.parse(
                    task_id=task.task_id,
                    input_path=input_path,
                    ocr=ocr,
                    file_kind=FileKind(task.file_type),
                )
                # Upload while TemporaryDirectory is still alive (image Paths stay valid).
                self.storage.put_bytes(
                    f"{prefix}/result.md",
                    arts.markdown.encode("utf-8"),
                    "text/markdown",
                )
                markdown_key = f"{prefix}/result.md"
                content_list_key = None
                middle_key = None
                images_dir = None
                if arts.content_list_bytes:
                    content_list_key = f"{prefix}/content_list.json"
                    self.storage.put_bytes(
                        content_list_key,
                        arts.content_list_bytes,
                        "application/json",
                    )
                if arts.middle_bytes:
                    middle_key = f"{prefix}/middle.json"
                    self.storage.put_bytes(middle_key, arts.middle_bytes, "application/json")
                if arts.image_files:
                    images_dir = f"{prefix}/images/"
                    for name, path in arts.image_files:
                        self.storage.put_bytes(
                            f"{prefix}/images/{name}",
                            path.read_bytes(),
                            _guess_mime(name),
                        )
                task_result = TaskResult(
                    task_id=task.task_id,
                    file_id=task.file_id,
                    file_name=task.file_name,
                    file_type=task.file_type,
                    status=TaskStatus.SUCCEEDED,
                    metadata=arts.metadata,
                    artifacts=ArtifactPaths(
                        markdown=markdown_key,
                        content_list=content_list_key,
                        middle=middle_key,
                        images_dir=images_dir,
                    ),
                    warnings=arts.warnings,
                )
                self.storage.put_bytes(
                    f"{prefix}/result.json",
                    task_result.model_dump_json(indent=2).encode("utf-8"),
                    "application/json",
                )
                return task_result
        finally:
            self.engine.device = previous_device
