# Docparse MinerU 3.4 使用文档

基于 MinerU **3.4**（`pipeline` 后端）的文档解析 HTTP 服务。默认部署端口 **18012**，与旧版 `docparse-service`（18011）隔离并行。

- 引擎：仅 MinerU，无 Docling
- 鉴权：当前 trial 环境**不要求** API Key
- 交互模型：上传创建异步任务 → 轮询状态 → 拉取结果

服务地址示例（按实际部署替换）：

```text
http://172.16.0.106:18012
```

下文用 `{BASE}` 表示该地址。

---

## 1. 支持的文件类型

| 类型 | 扩展名 |
| --- | --- |
| PDF | `.pdf` |
| 图片 | `.png` `.jpg` `.jpeg` `.tif` `.tiff` `.bmp` `.webp` |
| Office | `.docx` `.pptx` `.xlsx` |

其他类型返回 `400 UNSUPPORTED_FILE_TYPE`。默认单文件大小上限 **200 MB**（可用环境变量 `DOCPARSE_MAX_FILE_SIZE_MB` 调整）。

---

## 2. 典型调用流程

```text
1. POST /v1/files/parse     → 得到 task_id（HTTP 202）
2. GET  /v1/tasks/{task_id} → 轮询直到 status=succeeded / failed
3. GET  /v1/tasks/{task_id}/result | /markdown | /content-list | /middle | /assets/...
```

### 端到端示例（curl）

```bash
BASE=http://127.0.0.1:18012

# 1. 提交解析
RESP=$(curl -s -X POST "$BASE/v1/files/parse" \
  -F "file=@./sample.pdf" \
  -F "ocr=auto")
echo "$RESP"
# {"task_id":"...","file_id":"...","status":"queued"}

TASK_ID=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['task_id'])")

# 2. 轮询状态
while true; do
  ST=$(curl -s "$BASE/v1/tasks/$TASK_ID")
  echo "$ST"
  echo "$ST" | grep -q '"status":"succeeded"' && break
  echo "$ST" | grep -q '"status":"failed"' && break
  sleep 2
done

# 3. 取结果
curl -s "$BASE/v1/tasks/$TASK_ID/result" | python3 -m json.tool
curl -s "$BASE/v1/tasks/$TASK_ID/markdown" -o result.md
curl -s "$BASE/v1/tasks/$TASK_ID/content-list" -o content_list.json
curl -s "$BASE/v1/tasks/$TASK_ID/middle" -o middle.json
# 若有图：curl -s "$BASE/v1/tasks/$TASK_ID/assets/xxx.png" -o xxx.png
```

项目自带冒烟脚本：

```bash
./scripts/api_smoke_remote.sh
# 默认 BASE=http://127.0.0.1:18012
```

---

## 3. 接口一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/v1/health` | 健康检查 |
| POST | `/v1/files/parse` | 上传文件并创建解析任务 |
| GET | `/v1/tasks/{task_id}` | 查询任务状态 |
| GET | `/v1/tasks/{task_id}/result` | 任务包装 JSON（含产物路径） |
| GET | `/v1/tasks/{task_id}/markdown` | Markdown 正文 |
| GET | `/v1/tasks/{task_id}/content-list` | MinerU `content_list.json` |
| GET | `/v1/tasks/{task_id}/middle` | MinerU `middle.json` |
| GET | `/v1/tasks/{task_id}/assets/{path}` | 读取 `images/` 下文件 |

也可在服务启动后打开 Swagger：`{BASE}/docs`（FastAPI 自动生成）。

---

## 4. 接口详情

### 4.1 健康检查

```http
GET /v1/health
```

**响应示例：**

```json
{
  "status": "ok",
  "storage": "local"
}
```

`storage` 为 `local` 或 `minio`。

---

### 4.2 创建解析任务

```http
POST /v1/files/parse
Content-Type: multipart/form-data
```

| 字段 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- |
| `file` | 是 | file | 待解析文件 |
| `ocr` | 否 | string | `auto`（默认）/ `force` / `disable`，映射 MinerU `-m auto\|ocr\|txt` |
| `device` | 否 | string | `auto` / `npu` / `cpu`；省略则用服务配置 `DOCPARSE_MINERU_DEVICE` |

**成功响应：** `202 Accepted`

```json
{
  "task_id": "ea16b0aac2d24d77b6a3c6a98fdbb029",
  "file_id": "28fd791afc4442e4be739b28bdc3158e",
  "status": "queued"
}
```

说明：默认异步执行时，202 体里的 `status` 多为创建时的 `queued`；请以 `GET /v1/tasks/{task_id}` 为准。

**curl：**

```bash
curl -X POST "$BASE/v1/files/parse" \
  -F "file=@./sample.pdf" \
  -F "ocr=auto" \
  -F "device=auto"
```

**常见错误：**

| HTTP | code | 含义 |
| --- | --- | --- |
| 400 | `UNSUPPORTED_FILE_TYPE` | 不支持的类型 |
| 400 | `INVALID_FILENAME` | 文件名非法 |
| 413 | `FILE_TOO_LARGE` | 超过大小限制 |

---

### 4.3 查询任务状态

```http
GET /v1/tasks/{task_id}
```

**成功示例：**

```json
{
  "task_id": "...",
  "file_id": "...",
  "file_name": "sample.pdf",
  "file_type": "pdf",
  "engine": "mineru",
  "status": "succeeded",
  "error": null
}
```

失败时：

```json
{
  "task_id": "...",
  "status": "failed",
  "error": {
    "code": "ENGINE_FAILED",
    "message": "..."
  }
}
```

**状态枚举：** `queued` → `running` → `succeeded` / `failed`

**常见 error.code：**

| code | 含义 |
| --- | --- |
| `ENGINE_FAILED` | MinerU CLI / 解析失败 |
| `NPU_UNAVAILABLE` | 请求了 `device=npu` 但本机无可用 Ascend |

`404 TASK_NOT_FOUND`：任务不存在。

---

### 4.4 获取结果包装 JSON

```http
GET /v1/tasks/{task_id}/result
```

**成功示例：**

```json
{
  "schema_version": "2.0",
  "task_id": "...",
  "file_id": "...",
  "file_name": "sample.pdf",
  "file_type": "pdf",
  "engine": "mineru",
  "engine_version": "3.4",
  "status": "succeeded",
  "metadata": {
    "mineru_device": "cpu",
    "mineru_backend": "pipeline"
  },
  "artifacts": {
    "markdown": "tasks/{task_id}/result/result.md",
    "content_list": "tasks/{task_id}/result/content_list.json",
    "middle": "tasks/{task_id}/result/middle.json",
    "images_dir": "tasks/{task_id}/result/images/"
  },
  "warnings": []
}
```

说明：

- `artifacts.*` 为**对象存储完整 key**（不是相对路径）。HTTP 取内容请用下面各专用接口，不必自己拼存储路径。
- `metadata.mineru_device` 为实际使用的 `npu` / `cpu`；若 NPU 失败回退 CPU，可能另有 `mineru_npu_fallback_reason`。
- `warnings`：例如缺少 `content_list` / `middle` / `images` 时任务仍可成功，但会带警告。

未完成或无结果：`404 RESULT_NOT_FOUND`。

---

### 4.5 获取 Markdown

```http
GET /v1/tasks/{task_id}/markdown
```

- `Content-Type: text/markdown`
- 正文为解析后的 Markdown（图片引用一般为 `images/xxx.png`）

```bash
curl -s "$BASE/v1/tasks/$TASK_ID/markdown" -o result.md
```

---

### 4.6 获取 content_list

```http
GET /v1/tasks/{task_id}/content-list
```

- `Content-Type: application/json`
- MinerU 按阅读顺序整理的内容块列表（原生结构）

```bash
curl -s "$BASE/v1/tasks/$TASK_ID/content-list" | python3 -m json.tool
```

若解析时未产出该文件：`404 RESULT_NOT_FOUND`（同时可在 `/result` 的 `warnings` 中看到缺失提示）。

---

### 4.7 获取 middle.json

```http
GET /v1/tasks/{task_id}/middle
```

- `Content-Type: application/json`
- MinerU 中间结构（含页、块、bbox 等，便于二次开发）

```bash
curl -s "$BASE/v1/tasks/$TASK_ID/middle" -o middle.json
```

---

### 4.8 获取图片资源

```http
GET /v1/tasks/{task_id}/assets/{path}
```

- `{path}` 为 `images/` **之下**的相对路径，例如 `fig1.png`、`page_0_image_1.png`
- 禁止 `..` 与绝对路径（防目录穿越）
- 无图或路径错误：`400 INVALID_ASSET_PATH` / `404 RESULT_NOT_FOUND`

```bash
# 先从 markdown 或 content_list 得知文件名，再下载
curl -s "$BASE/v1/tasks/$TASK_ID/assets/fig1.png" -o fig1.png
```

---

## 5. 产物落盘（服务端）

默认本地存储根目录：`./data/objects`（Compose 下对应容器 `/app/data/objects`）。

```text
tasks/{task_id}/
  input/{filename}                 # 上传原文
  result/
    result.json                    # 任务包装（与 /result 一致）
    result.md
    content_list.json              # 可能缺失
    middle.json                    # 可能缺失
    images/                        # 可能缺失或为空
      *.png / *.jpg ...
```

若配置 MinIO，key 布局相同，落在配置的 bucket 中。

---

## 6. 错误体格式

统一结构：

```json
{
  "error": {
    "code": "ENGINE_FAILED",
    "message": "人类可读说明",
    "retryable": false
  }
}
```

---

## 7. 参数与设备说明

| 概念 | 取值 | 行为 |
| --- | --- | --- |
| `ocr=auto` | 默认 | MinerU `-m auto` |
| `ocr=force` | | `-m ocr` |
| `ocr=disable` | | `-m txt` |
| `device=auto` | 默认配置 | 有 Ascend 则 NPU，失败可回退 CPU |
| `device=npu` | | 强制 NPU；不可用则任务失败 `NPU_UNAVAILABLE` |
| `device=cpu` | | 强制 CPU |

服务侧固定附加：`-b pipeline --source local`（或等价短参），**不使用** MinerU 4.x 的 `mineru parse` / `mineru-kit`。

---

## 8. 部署与运维（摘要）

详细步骤见 [README.md](README.md) 与 [verification_log.md](verification_log.md)。

最短路径（基座镜像 `mineru:npu-vllm-3.4` 已存在时）：

```bash
cd 项目目录

./scripts/render_npu_compose_override.sh

DOCKER_BUILDKIT=0 docker-compose -f docker-compose.runtime.yml -f docker-compose.npu.override.yml up -d --build --pull=false （第一次启动不要--pull=false）
```

---

## 9. 与旧服务差异（迁移注意）

| 项 | 旧 docparse-service (18011) | 本服务 (18012) |
| --- | --- | --- |
| 引擎 | MinerU 2.x + Docling | 仅 MinerU 3.4 |
| 创建参数 | `engine` / `mode` / `ocr` / `fallback` | 仅 `ocr` / 可选 `device` |
| 结果 | 自定义 `pages[].blocks[]` 为主 | MinerU 原生 md / content_list / middle / images |
| 图片 | 默认不持久化 | 持久化到 `result/images/` |
| 存储 key | `default/tasks/...` | `tasks/...` |

