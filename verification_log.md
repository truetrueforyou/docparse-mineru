# MinerU 3.4 Ascend Server Verification Log

**Target host:** Atlas 800T A2 (`172.16.0.106`)  
**Project:** `docparse-mineru34` (port **18012**; legacy `docparse-service` on **18011**)  
**Prepared:** 2026-09-29  
**Operator:** _TBD_

> **Agent note:** This checklist was authored without SSH access to the Ascend host. Every step below is **PENDING** until an operator runs the commands on `172.16.0.106` and records results. Do not mark PASS without live evidence.

## Summary

| Step | Description | Status |
| --- | --- | --- |
| 1 | Build base + runtime images | **PENDING** |
| 2 | MinerU version gate (3.4.x) | **PENDING** |
| 3 | Start stack + health check | **PENDING** |
| 4 | In-container manual CLI (`pipeline`, npu/cpu) | **PENDING** |
| 5 | HTTP smoke + legacy 18011 unchanged | **PENDING** |
| 6 | Commit filled results | **PENDING** |

---

## Step 1: Build base and runtime images

**Status:** **PENDING**

Suggested `DOCKER_BUILDKIT=0` for compose build.

```bash
docker build --network=host -t mineru:npu-vllm-3.4 -f docker/npu.Dockerfile .
DOCKER_BUILDKIT=0 docker-compose -f docker-compose.runtime.yml build --pull=false
```

**Operator record:**

- [ ] Base image `mineru:npu-vllm-3.4` built successfully
- [ ] Runtime image `docparse-mineru34:runtime` built successfully
- Build log excerpt / errors:

```
(paste here)
```

---

## Step 2: Version gate

**Status:** **PENDING**

```bash
docker run --rm mineru:npu-vllm-3.4 mineru --version
# expect 3.4.x
```

**Operator record:**

- [ ] Output is `3.4.x` (not 4.x)
- Actual version:

```
(paste here)
```

---

## Step 3: Start stack

**Status:** **PENDING**

```bash
./scripts/render_npu_compose_override.sh
docker-compose -f docker-compose.runtime.yml -f docker-compose.npu.override.yml up -d
curl http://127.0.0.1:18012/v1/health
```

**Operator record:**

- [ ] Override file generated (`docker-compose.npu.override.yml`)
- [ ] Container `docparse-mineru34` running
- [ ] Health endpoint returns OK
- Health response:

```
(paste here)
```

---

## Step 4: In-container manual CLI

**Status:** **PENDING**

Confirm `-b pipeline -d npu|cpu` produces `md`, `content_list`, `middle`, and `images` (when figures exist).

Example (adjust sample PDF path as needed):

```bash
docker exec -it docparse-mineru34 bash -lc '
  set -e
  WORK=/tmp/mineru-cli-verify
  rm -rf "$WORK" && mkdir -p "$WORK/in" "$WORK/out"
  # use any small PDF on host or copy one into the container
  mineru -p "$WORK/in/sample.pdf" -o "$WORK/out" -m auto -b pipeline -d npu --source local
  find "$WORK/out" -type f | sort
  ls -la "$WORK/out"/*/* 2>/dev/null || true
'
# optional CPU fallback check:
# mineru -p ... -b pipeline -d cpu --source local
```

**Operator record:**

- [ ] NPU (`-d npu`) run completed
- [ ] CPU (`-d cpu`) run completed or NPU-only documented
- [ ] `*.md` present
- [ ] `*_content_list.json` present
- [ ] `*_middle.json` present
- [ ] `images/` present (or N/A with reason)
- Artifact listing:

```
(paste find/ls output)
```

---

## Step 5: HTTP smoke + legacy port check

**Status:** **PENDING**

```bash
./scripts/api_smoke_remote.sh
# optional: DOCPARSE_SMOKE_DOCX=0 ./scripts/api_smoke_remote.sh
```

Confirm legacy **18011** container still present and unchanged:

```bash
curl -sS http://127.0.0.1:18011/v1/health
docker ps --format 'table {{.Names}}\t{{.Ports}}\t{{.Status}}' | grep -E '18011|docparse'
```

**Operator record:**

- [ ] Smoke script ends with `SMOKE_OK`
- [ ] PDF task succeeded; markdown / content-list / middle reachable
- [ ] Legacy `18011` service still healthy and not replaced by this stack
- Smoke output excerpt:

```
(paste here)
```

---

## Step 6: Commit results

**Status:** **PENDING**

After filling this log on the Ascend host:

```bash
git add verification_log.md
git commit -m "docs: record MinerU 3.4 Ascend verification results"
```

**Operator record:**

- [ ] Commit hash:

```
(paste here)
```
