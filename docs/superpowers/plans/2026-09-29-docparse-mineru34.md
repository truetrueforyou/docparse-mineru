# Docparse MinerU 3.4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `c:\Users\LH\Desktop\docparse-mineru34` 落地独立 HTTP 文档解析服务：仅 MinerU 3.4 CLI、强制 `pipeline`、持久化 md/images/content_list/middle，端口 18012，兼容 Atlas 800T A2 部署。

**Architecture:** FastAPI 常驻；任务异步执行；`subprocess` 调用基座镜像内 `mineru`；在 `TemporaryDirectory` 退出前将产物写入 Local/MinIO；NPU `auto` 失败回退 CPU。无 Docling。

**Tech Stack:** Python 3.11+、FastAPI、SQLAlchemy、boto3、Docker（官方 Ascend `npu.Dockerfile` pin `mineru[core]>=3.4.0,<4`）、pytest。

**Spec:** `docs/superpowers/specs/2026-09-29-docparse-mineru34-design.md`

## Global Constraints

- 项目根：`c:\Users\LH\Desktop\docparse-mineru34`
- 仅 MinerU 3.4 经典 CLI：`mineru -p -o -m ...`；禁止 4.x `mineru parse` / `mineru-kit`
- 强制 `-b pipeline`（或等价 `--backend pipeline`）
- 端口 `18012:8000`；容器名 `docparse-mineru34`；镜像 `docparse-mineru34:runtime`；基座 `mineru:npu-vllm-3.4`
- 落盘：`tasks/{task_id}/result/{result.json,result.md,content_list.json,middle.json,images/}`
- markdown 硬依赖；content_list/middle/images 缺失记 `warnings`，不整任务失败
- 无 Docling、无 placeholder 假成功、默认不 privileged
- 参考原项目可复制逻辑：`c:\Users\LH\Desktop\docparse-service\`（只借鉴，不修改原项目）

## File Map

| 路径 | 职责 |
| --- | --- |
| `src/docparse_service/config.py` | `DOCPARSE_*` 设置 |
| `src/docparse_service/schemas.py` | OCR/设备/任务状态/结果包装模型 |
| `src/docparse_service/file_types.py` | 扩展名 → FileKind；支持集 |
| `src/docparse_service/errors.py` | `api_error` |
| `src/docparse_service/storage.py` | Local/MinIO `put_bytes`/`get_bytes` |
| `src/docparse_service/db.py` | `ParseTask` 表 |
| `src/docparse_service/engines.py` | MinerU CLI + 产物收集 + NPU 探测/回退 |
| `src/docparse_service/service.py` | 创建任务、解析、持久化 |
| `src/docparse_service/app.py` | HTTP 路由 |
| `docker/npu.Dockerfile` | 基座 pin 3.4 |
| `Dockerfile.runtime` | 业务镜像 |
| `docker-compose.runtime.yml` | 18012 + Ascend 卷 |
| `scripts/render_npu_compose_override.sh` | 动态 devices |
| `tests/` | 契约与引擎假 CLI 测试 |

---

### Task 1: 脚手架与配置

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`, `src/docparse_service/__init__.py`, `src/docparse_service/__main__.py`, `src/docparse_service/config.py`, `src/docparse_service/errors.py`, `tests/test_config.py`

**Interfaces:**
- Produces: `Settings`（`get_settings()`）；`api_error(status, code, message, retryable=False)`

- [ ] **Step 1: 初始化 git 与基础忽略**

```bash
cd /c/Users/LH/Desktop/docparse-mineru34
git init
```

`.gitignore`:

```gitignore
.venv/
__pycache__/
.pytest_cache/
.ruff_cache/
data/
.env
docker-compose.npu.override.yml
*.pyc
*.egg-info/
```

- [ ] **Step 2: 写 `pyproject.toml`**

```toml
[project]
name = "docparse-mineru34"
version = "0.1.0"
description = "HTTP document parsing service powered by MinerU 3.4 (pipeline) for Ascend NPU."
requires-python = ">=3.11"
dependencies = [
  "boto3>=1.34.0",
  "fastapi>=0.115.0",
  "pydantic>=2.8.0",
  "pydantic-settings>=2.4.0",
  "python-multipart>=0.0.9",
  "sqlalchemy>=2.0.0",
  "uvicorn[standard]>=0.30.0",
]

[project.optional-dependencies]
dev = [
  "httpx>=0.27.0",
  "pytest>=8.3.0",
  "ruff>=0.6.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]

[tool.ruff]
line-length = 100
src = ["src", "tests"]
```

- [ ] **Step 3: 写失败测试 `tests/test_config.py`**

```python
from docparse_service.config import Settings


def test_default_mineru_extra_args_force_pipeline():
    s = Settings()
    assert "-b pipeline" in s.mineru_cpu_extra_args or "--backend pipeline" in s.mineru_cpu_extra_args
    assert "cpu" in s.mineru_cpu_extra_args
    assert "npu" in s.mineru_npu_extra_args
```

- [ ] **Step 4: 运行确认失败**

Run: `python -m venv .venv && .venv/Scripts/pip install -e ".[dev]" && .venv/Scripts/pytest tests/test_config.py -v`  
（Linux/mac 用 `.venv/bin/pip` / `.venv/bin/pytest`）  
Expected: FAIL（模块不存在）

- [ ] **Step 5: 实现 `config.py` / `errors.py` / 包入口**

`errors.py` 从原项目复制 `api_error`。

`config.py`:

```python
from functools import lru_cache
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOCPARSE_", env_file=".env", extra="ignore")

    database_url: str = Field(default="sqlite:///./data/docparse.db")
    storage_backend: str = Field(default="local")
    local_storage_dir: str = Field(default="./data/objects")
    minio_endpoint_url: str | None = None
    minio_access_key: str | None = None
    minio_secret_key: str | None = None
    minio_bucket: str = Field(default="docparse-mineru34")
    minio_secure: bool = Field(default=False)
    max_file_size_mb: int = Field(default=200)
    run_tasks_inline: bool = Field(default=False)
    mineru_command: str = Field(default="mineru")
    mineru_extra_args: str = Field(default="")
    mineru_device: str = Field(default="auto")
    mineru_cpu_extra_args: str = Field(default="-b pipeline -d cpu --source local")
    mineru_npu_extra_args: str = Field(default="-b pipeline -d npu --source local")
    disable_npu_probe: bool = Field(default=False)

    @property
    def local_storage_path(self) -> Path:
        return Path(self.local_storage_dir)


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

`.env.example` 写入同名键；`__main__.py`：`uvicorn docparse_service.app:app --host 0.0.0.0 --port 8000`（app 可先空壳，Task 5 补全前可用占位）。

- [ ] **Step 6: 再跑测试**

Run: `.venv/Scripts/pytest tests/test_config.py -v`  
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .gitignore .env.example src/docparse_service tests/test_config.py
git commit -m "chore: scaffold docparse-mineru34 config and package"
```

---

### Task 2: 存储与数据库

**Files:**
- Create: `src/docparse_service/storage.py`, `src/docparse_service/db.py`, `tests/test_storage.py`

**Interfaces:**
- Produces: `ObjectStorage.put_bytes/get_bytes`；`LocalObjectStorage`；`MinioObjectStorage`；`make_storage(settings)`；`ParseTask` ORM；`make_session_factory(url)`

- [ ] **Step 1: 写存储测试**

```python
from pathlib import Path
from docparse_service.storage import LocalObjectStorage


def test_local_put_and_get(tmp_path: Path):
    store = LocalObjectStorage(tmp_path)
    uri = store.put_bytes("tasks/t1/result/result.md", b"hello", "text/markdown")
    assert uri.startswith("local://")
    assert store.get_bytes("tasks/t1/result/result.md") == b"hello"
```

- [ ] **Step 2: 跑测确认失败 → 实现 storage**

从原项目拷贝并微调 `LocalObjectStorage` / `MinioObjectStorage` / `ObjectStorage`。增加：

```python
def make_storage(settings):
    if settings.storage_backend == "minio":
        return MinioObjectStorage(...)
    return LocalObjectStorage(settings.local_storage_path)
```

- [ ] **Step 3: 实现 `db.py`**

`ParseTask` 字段：

- `task_id`, `file_id`, `file_name`, `file_type`, `status`, `input_key`
- `result_key`, `markdown_key`, `content_list_key`, `middle_key`, `images_prefix`
- `error_code`, `error_message`, `created_at`, `updated_at`
- 去掉原 `engine` 列，或固定写死 `"mineru"`（推荐保留列恒为 `mineru` 便于排查）

`make_session_factory` 同原项目（sqlite 建父目录）。

- [ ] **Step 4: Commit**

```bash
git add src/docparse_service/storage.py src/docparse_service/db.py tests/test_storage.py
git commit -m "feat: add object storage and task database"
```

---

### Task 3: Schema 与文件类型

**Files:**
- Create: `src/docparse_service/schemas.py`, `src/docparse_service/file_types.py`, `tests/test_file_types.py`

**Interfaces:**
- Produces: `OcrMode`, `DeviceMode`, `TaskStatus`, `FileKind`, `WarningItem`, `TaskResult`（含 `artifacts`）；`detect_file_kind(name, content_type) -> FileKind`；`is_supported(kind) -> bool`

- [ ] **Step 1: 失败测试**

```python
from docparse_service.file_types import FileKind, detect_file_kind, is_supported


def test_pdf_and_docx_supported():
    assert is_supported(detect_file_kind("a.pdf", "application/pdf"))
    assert is_supported(detect_file_kind("a.docx", None))


def test_epub_unsupported():
    assert not is_supported(detect_file_kind("a.epub", None))
```

- [ ] **Step 2: 实现 schemas**

```python
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
```

另定义引擎内部用 `MinerUArtifacts` dataclass（不强制 pydantic）：

```python
@dataclass
class MinerUArtifacts:
    markdown: str
    content_list_bytes: bytes | None
    middle_bytes: bytes | None
    image_files: list[tuple[str, Path]]  # (relative_name, path)
    warnings: list[WarningItem]
    metadata: dict
```

- [ ] **Step 3: 实现 file_types**

支持后缀集合：`.pdf`；图片 `.png/.jpg/.jpeg/.tif/.tiff/.bmp/.webp`；`.docx/.pptx/.xlsx`。其余 → `UNSUPPORTED`。

- [ ] **Step 4: pytest PASS → Commit**

```bash
git commit -m "feat: add schemas and MinerU-supported file types"
```

---

### Task 4: MinerU 引擎（产物收集 + NPU 回退）

**Files:**
- Create: `src/docparse_service/engines.py`, `tests/test_engines.py`

**Interfaces:**
- Consumes: `Settings` 中的 command/device/extra_args；`OcrMode`；`MinerUArtifacts`
- Produces: `MinerUEngine.parse(...) -> MinerUArtifacts`；`is_npu_available() -> bool`

- [ ] **Step 1: 写假 mineru 脚本测试（TDD）**

在测试里写可执行 shell/bat 假命令：读 argv 的 `-o` 目录，创建：

```text
{out}/demo/auto/demo.md
{out}/demo/auto/demo_content_list.json
{out}/demo/auto/demo_middle.json
{out}/demo/auto/images/fig1.png
```

断言 `parse` 返回 markdown 文本、两份 json bytes、一张图、`metadata["mineru_backend"]=="pipeline"`。

另测：NPU 第一次失败、`device=auto` 时回退 CPU（假命令根据输出目录名含 `_npu` 失败）。

- [ ] **Step 2: 跑测确认失败**

Run: `pytest tests/test_engines.py -v`  
Expected: FAIL

- [ ] **Step 3: 实现核心逻辑**

要点（完整实现写在 `engines.py`）：

```python
def is_npu_available(disable_probe: bool = False) -> bool:
    if disable_probe or os.environ.get("DOCPARSE_DISABLE_NPU_PROBE", "").lower() in {"1","true","yes"}:
        return False
    # 检查 /dev/davinci* + /usr/local/Ascend/driver/lib64/driver/libascend_hal.so
    ...

class MinerUEngine:
    def parse(...) -> MinerUArtifacts:
        method = {OcrMode.AUTO: "auto", OcrMode.FORCE: "ocr", OcrMode.DISABLE: "txt"}[ocr]
        selected = self._select_device()
        try:
            return self._parse_once(input_path, task_id, selected, method)
        except RuntimeError as exc:
            if selected != "npu" or self.device.strip().lower() != "auto":
                raise
            arts = self._parse_once(input_path, task_id, "cpu", method)
            arts.metadata["mineru_device"] = "cpu"
            arts.metadata["mineru_npu_fallback_reason"] = str(exc)[-1000:]
            return arts

    def _parse_once(...) -> MinerUArtifacts:
        output_dir = input_path.parent / f"{task_id}_mineru_{device}"
        cmd = [self.command, "-p", str(input_path), "-o", str(output_dir), "-m", method]
        cmd.extend(shlex.split(self._extra_args_for_device(device)))
        cmd.extend(shlex.split(self.extra_args))
        env = {"TORCH_DEVICE_BACKEND_AUTOLOAD": "0"} if device == "cpu" else {}
        run_engine_command(cmd, env_overrides=env)
        return collect_mineru_artifacts(output_dir, stem=input_path.stem, method=method, device=device)
```

`collect_mineru_artifacts`：

1. 优先 `output_dir / stem / method`
2. 否则 `rglob("*.md")` 取父目录
3. 读 md（必须）
4. 找 `*_content_list.json`、`*_middle.json`（可缺 → warning）
5. 若存在 `images/`，枚举文件为 `(name, path)` 列表
6. `metadata` 含 `mineru_device`、`mineru_backend: pipeline`

`run_engine_command`：`subprocess.run(..., check=True, capture_output=True, text=True)`，失败 raise `RuntimeError` 含 stderr 尾部。

缺 `mineru` 命令：直接 `RuntimeError`（无 placeholder）。

- [ ] **Step 4: pytest PASS → Commit**

```bash
git commit -m "feat: MinerU 3.4 CLI adapter with artifact collection and NPU fallback"
```

---

### Task 5: Service 持久化（临时目录内上传）

**Files:**
- Create: `src/docparse_service/service.py`, `tests/test_service_persist.py`

**Interfaces:**
- Consumes: `MinerUEngine.parse -> MinerUArtifacts`；`ObjectStorage`；`ParseTask`
- Produces: `ParseService.create_task` / `run_task` / `get_*`

- [ ] **Step 1: 写持久化测试**

使用假引擎（monkeypatch `MinerUEngine.parse` 返回带一张图的 `MinerUArtifacts`），`run_tasks_inline` + 本地 storage，断言：

```text
tasks/{id}/result/result.md
tasks/{id}/result/content_list.json
tasks/{id}/result/middle.json
tasks/{id}/result/images/fig1.png
tasks/{id}/result/result.json
```

均存在；且临时目录清理后文件仍在 storage。

- [ ] **Step 2: 实现 `ParseService`**

关键顺序：

```python
def run_task(self, task_id: str, ocr: OcrMode, device_override: DeviceMode | None = None) -> None:
    # status=running
    content = self.storage.get_bytes(task.input_key)
    try:
        result = self._parse_and_persist(task, content, ocr, device_override)
        # status=succeeded; set keys
    except Exception as exc:
        # status=failed; ENGINE_FAILED
```

```python
def _parse_and_persist(...):
    prefix = f"tasks/{task.task_id}/result"
    with tempfile.TemporaryDirectory(prefix="docparse-") as tmp:
        input_path = Path(tmp) / task.file_name
        input_path.write_bytes(content)
        arts = self.engine.parse(...)
        # 仍在 with 内上传：
        self.storage.put_bytes(f"{prefix}/result.md", arts.markdown.encode(), "text/markdown")
        if arts.content_list_bytes:
            self.storage.put_bytes(f"{prefix}/content_list.json", arts.content_list_bytes, "application/json")
        if arts.middle_bytes:
            self.storage.put_bytes(f"{prefix}/middle.json", arts.middle_bytes, "application/json")
        for name, path in arts.image_files:
            self.storage.put_bytes(f"{prefix}/images/{name}", path.read_bytes(), _guess_mime(name))
        task_result = TaskResult(... artifacts=ArtifactPaths(
            markdown=f"{prefix}/result.md" if ... else None,
            ...
            images_dir=f"{prefix}/images/" if arts.image_files else None,
        ), warnings=arts.warnings, metadata=arts.metadata)
        self.storage.put_bytes(f"{prefix}/result.json", task_result.model_dump_json(indent=2).encode(), "application/json")
        return task_result
```

`create_task`：校验类型与大小；`input_key = f"tasks/{task_id}/input/{filename}"`。

- [ ] **Step 3: pytest PASS → Commit**

```bash
git commit -m "feat: persist MinerU artifacts beside result.json before temp cleanup"
```

---

### Task 6: HTTP API

**Files:**
- Create: `src/docparse_service/app.py`, `tests/test_api.py`
- Modify: `src/docparse_service/__main__.py`（若需）

**Interfaces:**
- Produces: FastAPI routes per spec §8

- [ ] **Step 1: API 测试（httpx + TestClient，inline 任务）**

覆盖：

- `GET /v1/health`
- 上传假 pdf（引擎 monkeypatch）→ 202 → result / markdown / content-list / middle / assets/fig1.png
- 不支持类型 400
- assets 含 `..` → 400

- [ ] **Step 2: 实现 `app.py`**

路由：

- `POST /v1/files/parse`：Form `file`, `ocr`, `device`（可选）
- `GET /v1/tasks/{id}`
- `GET /v1/tasks/{id}/result`
- `GET /v1/tasks/{id}/markdown`
- `GET /v1/tasks/{id}/content-list`
- `GET /v1/tasks/{id}/middle`
- `GET /v1/tasks/{id}/assets/{path:path}`：规范化后必须落在 `tasks/{id}/result/images/` 下

错误处理复制原项目 `api_error` handler 模式。

- [ ] **Step 3: pytest 全量**

Run: `pytest -q`  
Expected: 全部 PASS

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: expose MinerU 3.4 parse HTTP API on async tasks"
```

---

### Task 7: Docker / Ascend 部署资产

**Files:**
- Create: `docker/npu.Dockerfile`, `Dockerfile.runtime`, `docker-compose.runtime.yml`, `scripts/render_npu_compose_override.sh`, `scripts/api_smoke_remote.sh`, `README.md`, `.dockerignore`

**Interfaces:**
- Produces: 可在 Atlas 上构建/启动的 compose 栈（端口 18012）

- [ ] **Step 1: `docker/npu.Dockerfile`**

基于官方中国区脚本（当前上游已 pin 3.4）：

```dockerfile
FROM quay.m.daocloud.io/ascend/vllm-ascend:v0.11.0

RUN apt-get update && \
    apt-get install -y fonts-noto-core fonts-noto-cjk fontconfig libgl1 libglib2.0-0 && \
    fc-cache -fv && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install -U pip -i https://mirrors.aliyun.com/pypi/simple && \
    python3 -m pip install 'mineru[core]>=3.4.0,<4' \
      numpy==1.26.4 opencv-python==4.11.0.86 \
      -i https://mirrors.aliyun.com/pypi/simple && \
    python3 -m pip cache purge

RUN TORCH_DEVICE_BACKEND_AUTOLOAD=0 /bin/bash -c "mineru-models-download -s modelscope -m all"

ENTRYPOINT ["/bin/bash", "-c", "export MINERU_MODEL_SOURCE=local && exec \"$@\"", "--"]
```

构建：`docker build -t mineru:npu-vllm-3.4 -f docker/npu.Dockerfile .`

- [ ] **Step 2: `Dockerfile.runtime`**

```dockerfile
FROM mineru:npu-vllm-3.4

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MINERU_MODEL_SOURCE=local \
    MINERU_LMDEPLOY_DEVICE=ascend \
    DOCPARSE_MINERU_DEVICE=auto \
    DOCPARSE_MINERU_CPU_EXTRA_ARGS="-b pipeline -d cpu --source local" \
    DOCPARSE_MINERU_NPU_EXTRA_ARGS="-b pipeline -d npu --source local" \
    VIRTUAL_ENV=/opt/docparse-venv \
    PATH="/opt/docparse-venv/bin:$PATH"

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src

RUN python3 -m venv /opt/docparse-venv \
 && /opt/docparse-venv/bin/pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple .

EXPOSE 8000
ENTRYPOINT []
CMD ["/opt/docparse-venv/bin/python", "-m", "uvicorn", "docparse_service.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

若 venv 找不到系统 site 中的依赖导致运行异常，再改为 `--system-site-packages`（实现时实测）。

- [ ] **Step 3: `docker-compose.runtime.yml`**

- 服务名/容器名：`docparse-mineru34`
- `image: docparse-mineru34:runtime`
- `ports: ["18012:8000"]`
- volumes：`./data:/app/data`，`/usr/local/Ascend:/usr/local/Ascend:ro`
- `security_opt: [no-new-privileges:true]`
- env：`MINERU_MODEL_SOURCE=local`，`MINERU_LMDEPLOY_DEVICE=ascend`，设备 extra args
- healthcheck：请求 `http://127.0.0.1:8000/v1/health`

- [ ] **Step 4: NPU override 脚本**

从原项目复制 `render_npu_compose_override.sh`，把服务名改为 `docparse-mineru34`。

- [ ] **Step 5: `api_smoke_remote.sh`**

对 `http://127.0.0.1:18012`：上传 PDF（及可选 DOCX），轮询至 succeeded，curl markdown / content-list / middle，并检查 assets（若有图）。

- [ ] **Step 6: README**

写清：与旧服务端口隔离、3.4/pipeline、构建顺序（先基座后 runtime）、Ascend 启动命令、产物路径、禁止 4.x CLI。

- [ ] **Step 7: Commit**

```bash
git commit -m "chore: add Ascend Docker runtime for MinerU 3.4 on port 18012"
```

---

### Task 8: 服务器验收清单（人工）

不改代码；在 Atlas 800T A2 上执行并记录结果到 `verification_log.md`。

- [ ] **Step 1: 构建基座与业务镜像**（建议 `DOCKER_BUILDKIT=0`）

```bash
docker build --network=host -t mineru:npu-vllm-3.4 -f docker/npu.Dockerfile .
DOCKER_BUILDKIT=0 docker-compose -f docker-compose.runtime.yml build --pull=false
```

- [ ] **Step 2: 版本门禁**

```bash
docker run --rm mineru:npu-vllm-3.4 mineru --version
# 期望 3.4.x
```

- [ ] **Step 3: 启动**

```bash
./scripts/render_npu_compose_override.sh
docker-compose -f docker-compose.runtime.yml -f docker-compose.npu.override.yml up -d
curl http://127.0.0.1:18012/v1/health
```

- [ ] **Step 4: 容器内手工 CLI**

确认 `-b pipeline -d npu|cpu` 产出 md/content_list/middle/images。

- [ ] **Step 5: HTTP 冒烟**

跑 `scripts/api_smoke_remote.sh`；确认 `18011` 旧容器仍在且未改动。

- [ ] **Step 6: 记录 `verification_log.md` 并 commit**

```bash
git commit -m "docs: record MinerU 3.4 Ascend verification results"
```

---

## Spec Coverage Check

| Spec 要求 | Task |
| --- | --- |
| 独立项目路径 / 包 | 1 |
| Local/MinIO + DB | 2 |
| 文件类型仅 MinerU | 3 |
| 3.4 CLI pipeline + 产物收集 + NPU 回退 | 4 |
| 临时目录内落盘 md/images/content_list/middle | 5 |
| HTTP API + assets | 6 |
| Ascend 镜像/compose/18012 | 7 |
| 服务器验收 | 8 |
| 无 Docling / 无 4.x CLI / 无假成功 | 4–6 约束 |

## Placeholder Scan

无 TBD；torch 精确小版本跟随官方基座镜像（Task 7 Dockerfile 已用上游 pin），不在业务代码写死 2.4.0。
