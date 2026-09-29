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

Generate a host-local NPU device override (not committed), then start:

```bash
./scripts/render_npu_compose_override.sh
docker-compose -f docker-compose.runtime.yml -f docker-compose.npu.override.yml up -d --build
curl http://127.0.0.1:18012/v1/health
```

The compose file mounts `/usr/local/Ascend` read-only and uses `security_opt: no-new-privileges:true`. It does **not** set `privileged: true`.

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

```bash
curl -X POST http://127.0.0.1:18012/v1/files/parse \
  -F "file=@sample.pdf" \
  -F "ocr=auto"

curl http://127.0.0.1:18012/v1/tasks/{task_id}
curl http://127.0.0.1:18012/v1/tasks/{task_id}/markdown
curl http://127.0.0.1:18012/v1/tasks/{task_id}/content-list
curl http://127.0.0.1:18012/v1/tasks/{task_id}/middle
```

## Notes

- Device selection: `DOCPARSE_MINERU_DEVICE=auto|npu|cpu` with pipeline extra args for CPU/NPU.
- If the runtime venv cannot see base-image MinerU site packages when importing is required, rebuild `Dockerfile.runtime` with `python3 -m venv --system-site-packages`.
- Never upgrade the base image to MinerU 4.x; keep the pin `<4`.
