# Docparse MinerU 3.4 独立服务设计

**日期：** 2026-09-29  
**状态：** 已确认（2026-09-29）  
**来源：** 基于 `docparse-service`（MinerU 2.7）改造为新独立项目

## 1. 目标

在桌面新建独立项目 `docparse-mineru34`，提供文档解析 HTTP 服务：

- 解析引擎：**仅 MinerU 3.4**（覆盖其支持的全部输入格式）
- 运行环境：华为 **Atlas 800T A2**（Ascend NPU），兼容原项目服务器侧挂载与设备暴露方式
- 与现网 `docparse-service`（端口 18011）**并行隔离**，不替换、不抢端口
- 持久化 MinerU 开发友好产物：`md` + `images/` + `content_list.json` + `middle.json`

非目标（首版不做）：

- Docling / 多引擎路由
- MinerU 4.x（`mineru parse` / `mineru-kit`）
- RAG chunk / embedding
- 强制兼容原项目完整 `pages[].blocks[]` 结果 schema
- 默认 privileged 容器

## 2. 约束与决策摘要

| 项 | 决策 |
| --- | --- |
| 项目路径 | `c:\Users\LH\Desktop\docparse-mineru34` |
| 架构 | FastAPI + subprocess 调用 `mineru` CLI（薄封装） |
| 端口 | `18012 → 容器 8000` |
| API | 允许改契约；异步任务模型保留 |
| 引擎 | 仅 MinerU；无 Docling |
| 默认 backend | **强制 `pipeline`**（Ascend 稳定路径；不依赖 3.4 默认 `hybrid-engine`） |
| 设备策略 | `auto` / `npu` / `cpu`；`auto` 下 NPU 失败回退 CPU |
| 镜像 | 官方 Ascend `npu.Dockerfile` 自建基座，pin `mineru==3.4.x`（`mineru<4`） |
| 落盘 | `result.md`、`content_list.json`、`middle.json`、`images/` 与任务包装 `result.json` 同目录 |

官方 Ascend 参考：[Ascend 加速卡文档](https://opendatalab.github.io/MinerU/zh/usage/acceleration_cards/Ascend/)（注明适用于 MinerU &lt;4）。

## 3. 与原项目 / MinerU 版本关系

### 3.1 相对 `docparse-service`

保留：

- 单容器 HTTP 服务形态
- Local / MinIO 对象存储抽象
- Ascend 卷挂载 + `render_npu_compose_override.sh` 动态设备
- NPU 探测与 CPU 回退 metadata
- 隔离 venv 跑 API，系统/`mineru` 用基座命令

移除：

- Docling 引擎与相关配置
- 引擎路由（`engine=auto|mineru|docling`）
- Placeholder 引擎成功路径（生产不允许假成功）
- 仅抽取 Markdown、丢弃图片的行为

### 3.2 MinerU 2.7 → 3.4 接口差异（服务必须适配）

| 维度 | 2.7（原项目） | 3.4（本项目） |
| --- | --- | --- |
| CLI 主入口 | `mineru -p -o -m ...` | **仍为** `mineru -p -o -m ...`（非 4.x 文档库 CLI） |
| 默认 backend | 项目显式 `pipeline` | 上游默认常为 `hybrid-engine`；本服务**显式 `-b pipeline`** |
| 设备 | `--backend` / `--device` / `--source` | `-b` / `-d` / `--source`（长参等价；实现以镜像内 `--help` 为准） |
| 设备值 | `npu` / `cpu` | 同左（pipeline 路径） |
| 模型源 | `--source local` + `MINERU_MODEL_SOURCE=local` | 同左 |
| 输出消费 | 只读首个 `*.md` | 收集 md、`*_content_list.json`、`*_middle.json`、`images/` |
| Office | Docling | MinerU 原生支持则走同一 CLI |

**禁止**在本项目使用 4.x 文档中的 `mineru parse` / `mineru-kit parse` 作为默认路径。

## 4. 架构

```text
Client
  │  HTTP :18012
  ▼
FastAPI (uvicorn, /opt/docparse-venv)
  │  create task → object storage input/
  │  background / inline run
  ▼
MinerUEngine
  │  tempfile.TemporaryDirectory
  │  subprocess: mineru -p -o -m -b pipeline -d npu|cpu --source local
  │  collect artifacts BEFORE tempdir cleanup
  ▼
ObjectStorage (local | minio)
  tasks/{task_id}/input/...
  tasks/{task_id}/result/{result.json, result.md, content_list.json, middle.json, images/}
```

进程模型：一个容器 `docparse-mineru34`；API 常驻；每次解析按需拉起 `mineru` 子进程，结束后退出。

## 5. 项目结构

```text
docparse-mineru34/
  src/docparse_service/
    app.py
    config.py
    service.py
    engines.py          # 仅 MinerU
    storage.py
    schemas.py
    db.py
    file_types.py
    errors.py
  docker/
    npu.Dockerfile      # 官方 Ascend 脚本基础上 pin mineru==3.4.x
  Dockerfile.runtime    # FROM mineru:npu-vllm-3.4 + 本服务 venv
  docker-compose.runtime.yml
  scripts/
    render_npu_compose_override.sh
    api_smoke_remote.sh
  tests/
  .env.example
  pyproject.toml
  README.md
  docs/superpowers/specs/...
```

部署标识：

| 项 | 值 |
| --- | --- |
| 容器名 | `docparse-mineru34` |
| 业务镜像 | `docparse-mineru34:runtime` |
| 基座镜像 | `mineru:npu-vllm-3.4` |
| 宿主机端口 | `18012` |

## 6. 镜像与部署

### 6.1 基座镜像

- 起点：官方 `docker/china/npu.Dockerfile`（vllm，A2 默认 tag）
- 构建 tag：`mineru:npu-vllm-3.4`
- 安装约束：`mineru==3.4.x` 且 `mineru<4`
- 环境：`MINERU_MODEL_SOURCE=local`、`MINERU_LMDEPLOY_DEVICE=ascend`
- torch / torch_npu 版本以 **MinerU 3.4 Ascend 镜像实际要求**为准，不照搬原项目 2.4.0 写死值；实现阶段在目标机验证后锁定

### 6.2 业务镜像

- `FROM mineru:npu-vllm-3.4`
- `/opt/docparse-venv` 安装本包（`--system-site-packages` 是否启用以实现时冲突实测为准；优先隔离）
- `PATH`：venv bin 优先；`mineru` 仍解析到基座安装
- `CMD`：venv uvicorn → `docparse_service.app:app`，`:8000`

### 6.3 Compose（服务器兼容）

保留原项目兼容面：

- volume：`./data:/app/data`、`/usr/local/Ascend:/usr/local/Ascend:ro`
- devices：由 `render_npu_compose_override.sh` 生成 `docker-compose.npu.override.yml`（扫描 `/dev/davinci*`、`davinci_manager`、`devmm_svm`、`hisi_hdc`）
- `security_opt: no-new-privileges:true`（默认不 privileged）
- 构建建议：`DOCKER_BUILDKIT=0`、`--pull=false`

启动：

```bash
./scripts/render_npu_compose_override.sh
docker-compose -f docker-compose.runtime.yml -f docker-compose.npu.override.yml up -d --build
curl http://localhost:18012/v1/health
```

### 6.4 设备与回退

配置项（环境前缀可用 `DOCPARSE_`，与原项目运维习惯对齐）：

- `DOCPARSE_MINERU_DEVICE=auto|npu|cpu`
- `DOCPARSE_MINERU_CPU_EXTRA_ARGS=-b pipeline -d cpu --source local`
- `DOCPARSE_MINERU_NPU_EXTRA_ARGS=-b pipeline -d npu --source local`

NPU 可用性探测沿用原逻辑思路：设备节点 + Ascend driver 库存在。

`auto` 选 NPU 但 CLI 失败或缺少约定产物时：重试 CPU，并在 metadata 记录 `mineru_npu_fallback_reason`。

CPU 调用注入 `TORCH_DEVICE_BACKEND_AUTOLOAD=0`。

## 7. MinerU CLI 与产物

### 7.1 调用

```bash
# NPU
mineru -p <input> -o <tmpdir> -m auto|ocr|txt -b pipeline -d npu --source local

# CPU
TORCH_DEVICE_BACKEND_AUTOLOAD=0 \
mineru -p <input> -o <tmpdir> -m auto|ocr|txt -b pipeline -d cpu --source local
```

OCR 映射：`auto→auto`，`force→ocr`，`disable→txt`。

实现时以容器内 `mineru --help` 核对短参；若镜像仅接受长参，配置默认值改为 `--backend/--device`。

### 7.2 解析目录定位

优先路径：`{output}/{stem}/{method}/`（pipeline）。  
回退：`rglob("*.md")`，以其父目录为解析根。

从解析根收集：

- `*.md`（取主 markdown；若多个，取与输入 stem 最匹配者）
- `*_content_list.json`
- `*_middle.json`
- `images/` 目录（若存在）

缺少 markdown 视为失败（触发回退或任务失败）。  
`content_list` / `middle` / `images` 缺失时：任务可成功但在 `result.json.warnings` 记录缺失项（避免因调试文件策略变化导致全失败）；**markdown 为硬依赖**。

### 7.3 对象存储布局

```text
tasks/{task_id}/input/{filename}
tasks/{task_id}/result/result.json
tasks/{task_id}/result/result.md
tasks/{task_id}/result/content_list.json
tasks/{task_id}/result/middle.json
tasks/{task_id}/result/images/...
```

相对原项目去掉 `default/` 前缀（契约已允许变更）。若需与旧 MinIO 桶混用，可通过配置加可选 key 前缀。

**持久化时机：** 必须在 `TemporaryDirectory` 退出前完成上传/拷贝。

Markdown 中 `images/...` 相对引用保持不变（与 `result.md` 同级的 `images/`）。

不落盘（首版）：`*_model.json`、`*_layout.pdf`、`*_span.pdf`。

## 8. HTTP API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/v1/health` | `{ "status": "ok", "storage": "local\|minio" }` |
| POST | `/v1/files/parse` | 上传创建任务，`202` |
| GET | `/v1/tasks/{task_id}` | 任务状态 |
| GET | `/v1/tasks/{task_id}/result` | 任务包装 JSON |
| GET | `/v1/tasks/{task_id}/markdown` | `text/markdown` |
| GET | `/v1/tasks/{task_id}/content-list` | `application/json` |
| GET | `/v1/tasks/{task_id}/middle` | `application/json` |
| GET | `/v1/tasks/{task_id}/assets/{path}` | 读取 `images/` 下文件；拒绝 `..` |

### 8.1 创建任务

`multipart/form-data`：

- `file`（必填）
- `ocr`：`auto` \| `force` \| `disable`（默认 `auto`）
- `device`：可选 `auto` \| `npu` \| `cpu`（默认用服务配置）

响应：

```json
{ "task_id": "...", "file_id": "...", "status": "queued" }
```

### 8.2 任务包装 `result.json`

```json
{
  "schema_version": "2.0",
  "task_id": "...",
  "file_id": "...",
  "file_name": "demo.pdf",
  "file_type": "pdf",
  "engine": "mineru",
  "engine_version": "3.4.x",
  "status": "succeeded",
  "metadata": {
    "mineru_device": "npu",
    "mineru_backend": "pipeline"
  },
  "artifacts": {
    "markdown": "result/result.md",
    "content_list": "result/content_list.json",
    "middle": "result/middle.json",
    "images_dir": "result/images/"
  },
  "warnings": []
}
```

首版不以原项目 `pages[].blocks[]` 为必填输出；下游直接消费 MinerU 的 `content_list` / `middle`。

### 8.3 错误

```json
{ "error": { "code": "ENGINE_FAILED", "message": "...", "retryable": false } }
```

常见 code：`UNSUPPORTED_FILE_TYPE`、`FILE_TOO_LARGE`、`TASK_NOT_FOUND`、`ENGINE_FAILED`、`NPU_UNAVAILABLE`。

无 API Key（trial）。

## 9. 文件类型

以 MinerU 3.4 实际支持为准，实现时在镜像内核对。预期至少：

- PDF、常见图片（png/jpg/jpeg/tiff/bmp/webp 等）
- Office：docx / pptx / xlsx（若 3.4 镜像确认支持）

不在支持列表内的类型：创建任务时拒绝。  
不再提供 Docling 分支。

## 10. 配置

沿用 `DOCPARSE_` 前缀（降低运维迁移成本），关键项：

| 变量 | 默认 / 说明 |
| --- | --- |
| `DOCPARSE_DATABASE_URL` | sqlite under `./data` |
| `DOCPARSE_STORAGE_BACKEND` | `local` \| `minio` |
| `DOCPARSE_LOCAL_STORAGE_DIR` | `./data/objects` |
| `DOCPARSE_MINIO_*` | endpoint / key / bucket |
| `DOCPARSE_MAX_FILE_SIZE_MB` | `200` |
| `DOCPARSE_RUN_TASKS_INLINE` | `false` |
| `DOCPARSE_MINERU_COMMAND` | `mineru` |
| `DOCPARSE_MINERU_DEVICE` | `auto` |
| `DOCPARSE_MINERU_CPU_EXTRA_ARGS` | `-b pipeline -d cpu --source local` |
| `DOCPARSE_MINERU_NPU_EXTRA_ARGS` | `-b pipeline -d npu --source local` |
| `DOCPARSE_MINERU_EXTRA_ARGS` | 追加参数 |
| `MINERU_MODEL_SOURCE` | `local` |
| `MINERU_LMDEPLOY_DEVICE` | `ascend` |

## 11. 测试与验收

### 11.1 自动化

- 单元：假 `mineru` 可执行脚本写出 md / content_list / middle / images，断言落盘 key 与 API
- 路由：不支持类型被拒；无 Docling 路径
- NPU 回退：NPU 假失败 → CPU 成功 + metadata

### 11.2 服务器冒烟（18012）

1. 构建 `mineru:npu-vllm-3.4` 与 `docparse-mineru34:runtime`
2. `mineru --version` 显示 3.4.x
3. 容器内手动 CLI 解析样例 PDF，确认产物齐全
4. HTTP：上传 PDF → succeeded → 可取 markdown / content-list / middle / assets
5. 确认 `18011` 现网容器不受影响

## 12. 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| 官方 npu 镜像默认 MinerU 版本不是 3.4 | Dockerfile 显式 pin；构建后 `mineru --version` 门禁 |
| 3.4 默认 hybrid，Ascend 行为与 pipeline 不同 | 服务强制 `-b pipeline` |
| torch_npu 与 3.4 依赖冲突 | 基座按官方栈；API venv 隔离；冲突时调整 site-packages 策略 |
| NPU 出空产物（现网 2.7 曾出现） | 保留 CPU 回退 |
| Office 在 pipeline 下能力差异 | 冒烟覆盖；不支持则文档标明并拒收 |
| 4.x 文档误导 | README 明确本项目锁定 3.4 / 经典 CLI |

## 13. 实施顺序（概要）

1. 脚手架：包结构、配置、存储、DB、健康检查
2. MinerU 3.4 引擎适配 + 产物收集 + 临时目录内持久化
3. HTTP API（含 assets）
4. Docker 基座 pin 3.4 + runtime compose + NPU override 脚本
5. 测试与远程冒烟脚本
6. README / 运维说明

详细任务拆解在本 spec 确认后再写 implementation plan。
