import os
import subprocess
import sys
from pathlib import Path

import pytest

from docparse_service.engines import MinerUEngine, collect_mineru_artifacts, is_npu_available
from docparse_service.schemas import OcrMode, WarningItem


FAKE_MINERU_SOURCE = r'''
import sys
from pathlib import Path


def _parse_argv(argv: list[str]) -> tuple[Path | None, Path | None, str]:
    inp = None
    out = None
    method = "auto"
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "-p" and i + 1 < len(argv):
            inp = Path(argv[i + 1])
            i += 2
            continue
        if arg == "-o" and i + 1 < len(argv):
            out = Path(argv[i + 1])
            i += 2
            continue
        if arg == "-m" and i + 1 < len(argv):
            method = argv[i + 1]
            i += 2
            continue
        i += 1
    return inp, out, method


def main() -> int:
    inp, out, method = _parse_argv(sys.argv[1:])
    if out is None:
        print("missing -o", file=sys.stderr)
        return 2
    if "_npu" in out.name:
        print("simulated npu failure", file=sys.stderr)
        return 1
    stem = inp.stem if inp is not None else "demo"
    target = out / stem / method
    images = target / "images"
    images.mkdir(parents=True, exist_ok=True)
    (target / f"{stem}.md").write_text("# Demo markdown\n", encoding="utf-8")
    (target / f"{stem}_content_list.json").write_bytes(b'[{"type":"text"}]')
    (target / f"{stem}_middle.json").write_bytes(b'{"pdf_info":[]}')
    (images / "fig1.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _fake_mineru_command(tmp_path: Path) -> str:
    script = tmp_path / "fake_mineru.py"
    script.write_text(FAKE_MINERU_SOURCE, encoding="utf-8")
    if os.name == "nt":
        return subprocess.list2cmdline([sys.executable, str(script)])
    return f"{sys.executable!s} {script!s}"


def test_parse_collects_markdown_json_and_images(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DOCPARSE_DISABLE_NPU_PROBE", "1")
    command = _fake_mineru_command(tmp_path)
    input_path = tmp_path / "demo.pdf"
    input_path.write_bytes(b"%PDF-1.4")

    engine = MinerUEngine(command=command, device="cpu")
    artifacts = engine.parse(task_id="task1", input_path=input_path, ocr=OcrMode.AUTO)

    assert "Demo markdown" in artifacts.markdown
    assert artifacts.content_list_bytes == b'[{"type":"text"}]'
    assert artifacts.middle_bytes == b'{"pdf_info":[]}'
    assert len(artifacts.image_files) == 1
    assert artifacts.image_files[0][0] == "fig1.png"
    assert artifacts.image_files[0][1].is_file()
    assert artifacts.metadata["mineru_backend"] == "pipeline"
    assert artifacts.metadata["mineru_device"] == "cpu"


def test_auto_device_falls_back_from_npu_to_cpu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "docparse_service.engines.is_npu_available",
        lambda disable_probe=False: True,
    )
    command = _fake_mineru_command(tmp_path)
    input_path = tmp_path / "demo.pdf"
    input_path.write_bytes(b"%PDF-1.4")

    engine = MinerUEngine(command=command, device="auto")
    artifacts = engine.parse(task_id="task2", input_path=input_path, ocr=OcrMode.AUTO)

    assert "Demo markdown" in artifacts.markdown
    assert artifacts.metadata["mineru_device"] == "cpu"
    assert "mineru_npu_fallback_reason" in artifacts.metadata
    assert "simulated npu failure" in artifacts.metadata["mineru_npu_fallback_reason"]


def test_missing_command_raises_without_placeholder(tmp_path: Path):
    input_path = tmp_path / "demo.pdf"
    input_path.write_bytes(b"%PDF-1.4")
    engine = MinerUEngine(command="mineru-not-installed-xyz-9f3a", device="cpu")
    with pytest.raises(RuntimeError, match="not found"):
        engine.parse(task_id="task3", input_path=input_path, ocr=OcrMode.AUTO)


def test_collect_mineru_artifacts_warns_when_json_missing(tmp_path: Path):
    stem = "demo"
    method = "auto"
    work = tmp_path / stem / method
    work.mkdir(parents=True)
    (work / f"{stem}.md").write_text("# only md\n", encoding="utf-8")

    artifacts = collect_mineru_artifacts(tmp_path, stem=stem, method=method, device="cpu")
    assert artifacts.markdown == "# only md\n"
    assert artifacts.content_list_bytes is None
    assert artifacts.middle_bytes is None
    codes = {w.code for w in artifacts.warnings}
    assert "missing_content_list" in codes
    assert "missing_middle" in codes
    assert all(isinstance(w, WarningItem) for w in artifacts.warnings)


def test_is_npu_available_respects_disable_probe(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DOCPARSE_DISABLE_NPU_PROBE", raising=False)
    assert is_npu_available(disable_probe=True) is False
    monkeypatch.setenv("DOCPARSE_DISABLE_NPU_PROBE", "1")
    assert is_npu_available(disable_probe=False) is False
