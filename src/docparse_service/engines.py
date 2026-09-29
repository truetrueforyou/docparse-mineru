import os
import shlex
import shutil
import subprocess
from pathlib import Path

from docparse_service.schemas import FileKind, MinerUArtifacts, OcrMode, WarningItem

_OCR_METHOD = {
    OcrMode.AUTO: "auto",
    OcrMode.FORCE: "ocr",
    OcrMode.DISABLE: "txt",
}


def is_npu_available(disable_probe: bool = False) -> bool:
    if disable_probe or os.environ.get("DOCPARSE_DISABLE_NPU_PROBE", "").lower() in {
        "1",
        "true",
        "yes",
    }:
        return False
    required_paths = [
        Path("/dev/davinci_manager"),
        Path("/dev/devmm_svm"),
        Path("/dev/hisi_hdc"),
        Path("/usr/local/Ascend/driver/lib64/driver/libascend_hal.so"),
    ]
    if not all(path.exists() for path in required_paths):
        return False
    dev_root = Path("/dev")
    if not dev_root.exists():
        return False
    return any(dev_root.glob("davinci[0-9]*"))


def run_engine_command(command: list[str], env_overrides: dict[str, str] | None = None) -> None:
    command_env = os.environ.copy()
    if env_overrides:
        command_env.update(env_overrides)
    process = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        env=command_env,
    )
    if process.returncode != 0:
        stderr = (process.stderr or "").strip()
        stdout = (process.stdout or "").strip()
        detail = stderr or stdout or "no stderr/stdout"
        raise RuntimeError(
            f"Engine command failed with exit code {process.returncode}: "
            f"{shlex.join(command)}\n{detail[-4000:]}"
        )


class NpuUnavailableError(RuntimeError):
    """Raised when device=npu is forced but Ascend NPU runtime is unavailable."""

    error_code = "NPU_UNAVAILABLE"


def collect_mineru_artifacts(
    output_dir: Path,
    *,
    stem: str,
    method: str,
    device: str,
) -> MinerUArtifacts:
    preferred = output_dir / stem / method
    if preferred.is_dir() and any(preferred.glob("*.md")):
        work_dir = preferred
    else:
        md_files = sorted(output_dir.rglob("*.md"))
        if not md_files:
            raise RuntimeError(f"MinerU produced no Markdown output under {output_dir}")
        work_dir = md_files[0].parent

    md_path = _select_markdown_path(work_dir, stem)
    markdown = md_path.read_text(encoding="utf-8")
    if not markdown.strip():
        raise RuntimeError(f"MinerU produced empty Markdown output in {work_dir}")

    warnings: list[WarningItem] = []
    content_list_bytes = _read_first_bytes(work_dir, "*_content_list.json")
    if content_list_bytes is None:
        warnings.append(
            WarningItem(
                code="missing_content_list",
                message=f"content_list.json not found under {work_dir}",
            )
        )

    middle_bytes = _read_first_bytes(work_dir, "*_middle.json")
    if middle_bytes is None:
        warnings.append(
            WarningItem(
                code="missing_middle",
                message=f"middle.json not found under {work_dir}",
            )
        )

    image_files: list[tuple[str, Path]] = []
    images_dir = work_dir / "images"
    if images_dir.is_dir():
        for image_path in sorted(p for p in images_dir.iterdir() if p.is_file()):
            image_files.append((image_path.name, image_path))
    if not images_dir.is_dir() or not image_files:
        warnings.append(
            WarningItem(
                code="missing_images",
                message=f"images/ directory missing or empty under {work_dir}",
            )
        )

    return MinerUArtifacts(
        markdown=markdown,
        content_list_bytes=content_list_bytes,
        middle_bytes=middle_bytes,
        image_files=image_files,
        warnings=warnings,
        metadata={
            "mineru_device": device,
            "mineru_backend": "pipeline",
        },
    )


def _select_markdown_path(work_dir: Path, stem: str) -> Path:
    md_candidates = sorted(p for p in work_dir.glob("*.md") if p.is_file())
    if not md_candidates:
        raise RuntimeError(f"MinerU produced no Markdown output in {work_dir}")
    exact = work_dir / f"{stem}.md"
    if exact.is_file():
        return exact
    by_stem = [p for p in md_candidates if p.stem == stem]
    if by_stem:
        return by_stem[0]

    def closeness(path: Path) -> tuple[int, str]:
        common = len(os.path.commonprefix([path.stem, stem]))
        return (-common, path.name)

    return sorted(md_candidates, key=closeness)[0]


def _read_first_bytes(directory: Path, pattern: str) -> bytes | None:
    for path in sorted(directory.glob(pattern)):
        if path.is_file():
            return path.read_bytes()
    return None


class MinerUEngine:
    def __init__(
        self,
        command: str = "mineru",
        extra_args: str = "",
        device: str = "auto",
        cpu_extra_args: str = "-b pipeline -d cpu --source local",
        npu_extra_args: str = "-b pipeline -d npu --source local",
        disable_npu_probe: bool = False,
    ) -> None:
        self.command = command
        self.extra_args = extra_args
        self.device = device
        self.cpu_extra_args = cpu_extra_args
        self.npu_extra_args = npu_extra_args
        self.disable_npu_probe = disable_npu_probe

    def parse(
        self,
        task_id: str,
        input_path: Path,
        ocr: OcrMode,
        file_kind: FileKind | None = None,
        device: str | None = None,
    ) -> MinerUArtifacts:
        _ = file_kind  # reserved for callers; unused by MinerU CLI adapter
        self._ensure_command_available()
        method = _OCR_METHOD[ocr]
        configured = (device if device is not None else self.device).strip().lower()
        selected = self._select_device(device)
        try:
            return self._parse_once(input_path, task_id, selected, method)
        except NpuUnavailableError:
            raise
        except RuntimeError as exc:
            if selected != "npu" or configured != "auto":
                raise
            arts = self._parse_once(input_path, task_id, "cpu", method)
            arts.metadata["mineru_device"] = "cpu"
            arts.metadata["mineru_npu_fallback_reason"] = str(exc)[-1000:]
            return arts

    def _parse_once(
        self,
        input_path: Path,
        task_id: str,
        device: str,
        method: str,
    ) -> MinerUArtifacts:
        output_dir = input_path.parent / f"{task_id}_mineru_{device}"
        output_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            *self._command_parts(),
            "-p",
            str(input_path),
            "-o",
            str(output_dir),
            "-m",
            method,
        ]
        cmd.extend(self._split_args(self._extra_args_for_device(device)))
        cmd.extend(self._split_args(self.extra_args))
        env = {"TORCH_DEVICE_BACKEND_AUTOLOAD": "0"} if device == "cpu" else {}
        run_engine_command(cmd, env_overrides=env)
        return collect_mineru_artifacts(
            output_dir,
            stem=input_path.stem,
            method=method,
            device=device,
        )

    def _select_device(self, device_override: str | None = None) -> str:
        configured = (device_override if device_override is not None else self.device).lower().strip()
        if configured == "cpu":
            return "cpu"
        if configured == "npu":
            if not is_npu_available(disable_probe=self.disable_npu_probe):
                raise NpuUnavailableError(
                    "MinerU NPU was requested but Ascend NPU runtime is not available"
                )
            return "npu"
        if configured == "auto":
            return "npu" if is_npu_available(disable_probe=self.disable_npu_probe) else "cpu"
        raise RuntimeError(f"Unsupported MinerU device setting: {configured}")

    def _extra_args_for_device(self, device: str) -> str:
        if device == "npu":
            return self.npu_extra_args
        return self.cpu_extra_args

    def _command_parts(self) -> list[str]:
        parts = self._split_args(self.command)
        if not parts:
            raise RuntimeError(f"MinerU command not found: {self.command}")
        return parts

    def _ensure_command_available(self) -> None:
        parts = self._command_parts()
        executable = parts[0]
        if Path(executable).exists():
            return
        if shutil.which(executable):
            return
        raise RuntimeError(f"MinerU command not found: {self.command}")

    @staticmethod
    def _split_args(value: str) -> list[str]:
        if not value or not value.strip():
            return []
        return shlex.split(value, posix=(os.name != "nt"))
