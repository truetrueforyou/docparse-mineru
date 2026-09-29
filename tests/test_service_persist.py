from pathlib import Path

import pytest

from docparse_service.config import Settings
from docparse_service.db import make_session_factory
from docparse_service.engines import MinerUEngine, NpuUnavailableError
from docparse_service.schemas import DeviceMode, FileKind, MinerUArtifacts, OcrMode, TaskStatus
from docparse_service.service import ParseService, sanitize_upload_filename


def test_run_task_persists_artifacts_before_temp_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        storage_backend="local",
        local_storage_dir=str(tmp_path / "objects"),
        run_tasks_inline=True,
        disable_npu_probe=True,
    )
    session_factory = make_session_factory(settings.database_url)
    service = ParseService(settings, session_factory)

    def fake_parse(
        self: MinerUEngine,
        task_id: str,
        input_path: Path,
        ocr: OcrMode,
        file_kind: FileKind | None = None,
        device: str | None = None,
    ) -> MinerUArtifacts:
        _ = (self, task_id, ocr, file_kind, device)
        images_dir = input_path.parent / "fake_images"
        images_dir.mkdir(parents=True, exist_ok=True)
        fig = images_dir / "fig1.png"
        fig.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        return MinerUArtifacts(
            markdown="# Persisted\n\n![fig](images/fig1.png)\n",
            content_list_bytes=b'[{"type":"text"}]',
            middle_bytes=b'{"pdf_info":[]}',
            image_files=[("fig1.png", fig)],
            warnings=[],
            metadata={"mineru_device": "cpu", "mineru_backend": "pipeline"},
        )

    monkeypatch.setattr(MinerUEngine, "parse", fake_parse)

    task = service.create_task(
        filename="sample.pdf",
        content_type="application/pdf",
        content=b"%PDF-1.4 sample",
    )
    service.run_task(task.task_id, OcrMode.AUTO)

    prefix = f"tasks/{task.task_id}/result"
    expected_keys = [
        f"{prefix}/result.md",
        f"{prefix}/content_list.json",
        f"{prefix}/middle.json",
        f"{prefix}/images/fig1.png",
        f"{prefix}/result.json",
    ]
    for key in expected_keys:
        assert (tmp_path / "objects" / key).is_file(), key
        assert service.storage.get_bytes(key)

    stored = service.get_task(task.task_id)
    assert stored is not None
    assert stored.status == TaskStatus.SUCCEEDED.value
    assert stored.result_key == f"{prefix}/result.json"
    assert stored.markdown_key == f"{prefix}/result.md"
    assert stored.content_list_key == f"{prefix}/content_list.json"
    assert stored.middle_key == f"{prefix}/middle.json"
    assert stored.images_prefix == f"{prefix}/images/"

    result = service.get_result(task.task_id)
    assert result["schema_version"] == "2.0"
    assert result["status"] == "succeeded"
    assert result["artifacts"]["markdown"] == f"{prefix}/result.md"
    assert result["artifacts"]["images_dir"] == f"{prefix}/images/"
    assert service.get_markdown(task.task_id).startswith("# Persisted")


def test_sanitize_upload_filename_rejects_traversal() -> None:
    assert sanitize_upload_filename("../../escape.pdf") == "escape.pdf"
    assert sanitize_upload_filename(r"..\..\escape.pdf") == "escape.pdf"
    assert sanitize_upload_filename("docs/sample.pdf") == "sample.pdf"
    with pytest.raises(ValueError, match="INVALID_FILENAME"):
        sanitize_upload_filename("")
    with pytest.raises(ValueError, match="INVALID_FILENAME"):
        sanitize_upload_filename(".")
    with pytest.raises(ValueError, match="INVALID_FILENAME"):
        sanitize_upload_filename("..")


def test_create_task_stores_basename_only(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        storage_backend="local",
        local_storage_dir=str(tmp_path / "objects"),
        disable_npu_probe=True,
    )
    service = ParseService(settings, make_session_factory(settings.database_url))
    task = service.create_task(
        filename="../../nested/escape.pdf",
        content_type="application/pdf",
        content=b"%PDF-1.4 sample",
    )
    assert task.file_name == "escape.pdf"
    assert task.input_key.endswith("/input/escape.pdf")
    assert ".." not in task.input_key
    assert (tmp_path / "objects" / task.input_key).is_file()
    assert not (tmp_path / "escape.pdf").exists()


def test_device_override_does_not_mutate_shared_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        storage_backend="local",
        local_storage_dir=str(tmp_path / "objects"),
        mineru_device="auto",
        disable_npu_probe=True,
    )
    service = ParseService(settings, make_session_factory(settings.database_url))
    seen: list[str | None] = []

    def fake_parse(
        self: MinerUEngine,
        task_id: str,
        input_path: Path,
        ocr: OcrMode,
        file_kind: FileKind | None = None,
        device: str | None = None,
    ) -> MinerUArtifacts:
        _ = (task_id, input_path, ocr, file_kind)
        seen.append(device)
        assert self.device == "auto"
        return MinerUArtifacts(
            markdown="# ok\n",
            content_list_bytes=None,
            middle_bytes=None,
            image_files=[],
            warnings=[],
            metadata={"mineru_device": device or self.device, "mineru_backend": "pipeline"},
        )

    monkeypatch.setattr(MinerUEngine, "parse", fake_parse)
    task = service.create_task("sample.pdf", "application/pdf", b"%PDF-1.4")
    service.run_task(task.task_id, OcrMode.AUTO, DeviceMode.CPU)
    assert seen == ["cpu"]
    assert service.engine.device == "auto"


def test_forced_npu_unavailable_maps_error_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        storage_backend="local",
        local_storage_dir=str(tmp_path / "objects"),
        disable_npu_probe=True,
    )
    service = ParseService(settings, make_session_factory(settings.database_url))

    def fake_parse(
        self: MinerUEngine,
        task_id: str,
        input_path: Path,
        ocr: OcrMode,
        file_kind: FileKind | None = None,
        device: str | None = None,
    ) -> MinerUArtifacts:
        _ = (self, task_id, input_path, ocr, file_kind)
        if (device or self.device) == "npu":
            raise NpuUnavailableError("Ascend NPU runtime is not available")
        raise AssertionError("unexpected device")

    monkeypatch.setattr(MinerUEngine, "parse", fake_parse)
    task = service.create_task("sample.pdf", "application/pdf", b"%PDF-1.4")
    service.run_task(task.task_id, OcrMode.AUTO, DeviceMode.NPU)
    stored = service.get_task(task.task_id)
    assert stored is not None
    assert stored.status == TaskStatus.FAILED.value
    assert stored.error_code == "NPU_UNAVAILABLE"
