from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from docparse_service.app import create_app
from docparse_service.config import Settings
from docparse_service.engines import MinerUEngine
from docparse_service.schemas import FileKind, MinerUArtifacts, OcrMode


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        storage_backend="local",
        local_storage_dir=str(tmp_path / "objects"),
        run_tasks_inline=True,
        disable_npu_probe=True,
    )

    def fake_parse(
        self: MinerUEngine,
        task_id: str,
        input_path: Path,
        ocr: OcrMode,
        file_kind: FileKind | None = None,
    ) -> MinerUArtifacts:
        _ = (self, task_id, ocr, file_kind)
        images_dir = input_path.parent / "fake_images"
        images_dir.mkdir(parents=True, exist_ok=True)
        fig = images_dir / "fig1.png"
        fig.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        return MinerUArtifacts(
            markdown="# API\n\n![fig](images/fig1.png)\n",
            content_list_bytes=b'[{"type":"text"}]',
            middle_bytes=b'{"pdf_info":[]}',
            image_files=[("fig1.png", fig)],
            warnings=[],
            metadata={"mineru_device": "cpu", "mineru_backend": "pipeline"},
        )

    monkeypatch.setattr(MinerUEngine, "parse", fake_parse)
    return TestClient(create_app(settings))


def test_health(client: TestClient) -> None:
    response = client.get("/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["storage"] == "local"


def test_parse_flow_exposes_artifacts(client: TestClient) -> None:
    created = client.post(
        "/v1/files/parse",
        files={"file": ("sample.pdf", b"%PDF-1.4 sample", "application/pdf")},
        data={"ocr": "auto"},
    )
    assert created.status_code == 202
    payload = created.json()
    assert payload["status"] == "queued"
    task_id = payload["task_id"]
    assert payload["file_id"]

    status = client.get(f"/v1/tasks/{task_id}")
    assert status.status_code == 200
    assert status.json()["status"] == "succeeded"
    assert status.json()["engine"] == "mineru"

    result = client.get(f"/v1/tasks/{task_id}/result")
    assert result.status_code == 200
    body = result.json()
    assert body["schema_version"] == "2.0"
    assert body["status"] == "succeeded"
    assert body["artifacts"]["markdown"].endswith("/result.md")

    markdown = client.get(f"/v1/tasks/{task_id}/markdown")
    assert markdown.status_code == 200
    assert markdown.headers["content-type"].startswith("text/markdown")
    assert markdown.text.startswith("# API")

    content_list = client.get(f"/v1/tasks/{task_id}/content-list")
    assert content_list.status_code == 200
    assert content_list.headers["content-type"].startswith("application/json")
    assert content_list.json() == [{"type": "text"}]

    middle = client.get(f"/v1/tasks/{task_id}/middle")
    assert middle.status_code == 200
    assert middle.headers["content-type"].startswith("application/json")
    assert middle.json() == {"pdf_info": []}

    asset = client.get(f"/v1/tasks/{task_id}/assets/fig1.png")
    assert asset.status_code == 200
    assert asset.content.startswith(b"\x89PNG")


def test_unsupported_file_type_returns_400(client: TestClient) -> None:
    response = client.post(
        "/v1/files/parse",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


def test_asset_path_traversal_returns_400(client: TestClient) -> None:
    created = client.post(
        "/v1/files/parse",
        files={"file": ("sample.pdf", b"%PDF-1.4 sample", "application/pdf")},
    )
    task_id = created.json()["task_id"]

    # Percent-encode ".." so it reaches the handler (Starlette collapses raw ../ in URLs).
    response = client.get(f"/v1/tasks/{task_id}/assets/%2e%2e/result.md")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ASSET_PATH"
