# Docparse MinerU 3.4

HTTP document parsing service for Ascend NPU, pinned to **MinerU 3.4** (`pipeline` backend only).

This repo is isolated from the legacy `docparse-service` (port **18011**). This stack listens on **18012**.

## Scope

| Item | Value |
| --- | --- |
| MinerU | `mineru[core]>=3.4.0,<4` — do **not** install 4.x CLI |
| Backend | `pipeline` only (`-b pipeline`) |
| Host port | `18012` → container `8000` |
| Container | `docparse-mineru34` |

## Local development

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'   # or Windows: .venv\Scripts\pip install -e ".[dev]"
.venv/bin/pytest -q
.venv/bin/uvicorn docparse_service.app:app --reload
```

## Docker build order (Atlas / Ascend)

1. Build the MinerU 3.4 NPU base image (models downloaded at build time):

```bash
docker build -t mineru:npu-vllm-3.4 -f docker/npu.Dockerfile .
```

2. Build the runtime image (venv + uvicorn app):

```bash
docker build -t docparse-mineru34:runtime -f Dockerfile.runtime .
```

Or let compose build the runtime layer after the base tag exists.

## Ascend start (no privileged by default)

Generate a host-local NPU device override (not committed), then start.
Default **auto-picks an idle host card** (via `npu-smi`: no processes, lowest HBM), maps it to container `/dev/davinci0`, and sets `ASCEND_RT_VISIBLE_DEVICES=0`:

```bash
./scripts/render_npu_compose_override.sh      # auto
./scripts/render_npu_compose_override.sh 3    # force card 3
docker-compose -f docker-compose.runtime.yml -f docker-compose.npu.override.yml up -d --build
curl http://127.0.0.1:18012/v1/health
```

Legacy passthrough of all host cards: `ALL=1 ./scripts/render_npu_compose_override.sh`.

The compose file mounts **only** `/usr/local/Ascend/driver` (for `libascend_hal.so`) and uses `security_opt: no-new-privileges:true`. Do **not** bind-mount the entire `/usr/local/Ascend` tree over the image toolkit. It does **not** set `privileged: true`.

## Smoke

```bash
./scripts/api_smoke_remote.sh
# optional: DOCPARSE_SMOKE_DOCX=0 ./scripts/api_smoke_remote.sh
```

## Ascend server acceptance (manual)

On Atlas 800T A2, run the steps in [`verification_log.md`](verification_log.md), record outputs, and commit the filled checklist. All steps start as **PENDING** until verified on the NPU host.

## Artifact paths

Local storage default: `./data/objects` (compose mounts `./data` → `/app/data`).

Per task under `tasks/{task_id}/`:

- `result.json`
- `result.md`
- `content_list.json`
- `middle.json`
- `images/` (when MinerU emits figures)

## API

完整接口说明与端到端示例见 **[docs/USAGE.md](docs/USAGE.md)**。

独立可视化测试页（不挂载到服务，浏览器直接打开）：**[tools/test-console.html](tools/test-console.html)**。

```bash
curl -X POST http://127.0.0.1:18012/v1/files/parse \
  -F "file=@sample.pdf" \
  -F "ocr=auto"
```
## Notes

- Device selection: `DOCPARSE_MINERU_DEVICE=auto|npu|cpu` with pipeline extra args for CPU/NPU.
- If the runtime venv cannot see base-image MinerU site packages when importing is required, rebuild `Dockerfile.runtime` with `python3 -m venv --system-site-packages`.
- Never upgrade the base image to MinerU 4.x; keep the pin `<4`.
