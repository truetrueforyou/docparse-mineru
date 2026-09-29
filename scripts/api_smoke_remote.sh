#!/usr/bin/env bash
set -eu

BASE_URL="${DOCPARSE_SMOKE_BASE_URL:-http://127.0.0.1:18012}"
export BASE_URL
WORK=/tmp/docparse-mineru34-smoke
INCLUDE_DOCX="${DOCPARSE_SMOKE_DOCX:-1}"

rm -rf "$WORK"
mkdir -p "$WORK"

python3 - <<'PY'
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

work = Path("/tmp/docparse-mineru34-smoke")
files = {
    "[Content_Types].xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>""",
    "_rels/.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>""",
    "word/document.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Docparse MinerU34 DOCX smoke</w:t></w:r></w:p><w:sectPr/></w:body></w:document>""",
}
with ZipFile(work / "sample.docx", "w", ZIP_DEFLATED) as zf:
    for name, data in files.items():
        zf.writestr(name, data)

stream = b"BT /F1 24 Tf 72 720 Td (Docparse MinerU34 NPU smoke PDF) Tj ET"
objects = [
    b"<< /Type /Catalog /Pages 2 0 R >>",
    b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
    b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
]
out = bytearray(b"%PDF-1.4\n")
offsets = [0]
for idx, obj in enumerate(objects, 1):
    offsets.append(len(out))
    out.extend(f"{idx} 0 obj\n".encode())
    out.extend(obj + b"\nendobj\n")
xref = len(out)
out.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
for off in offsets[1:]:
    out.extend(f"{off:010d} 00000 n \n".encode())
out.extend(f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
(work / "sample.pdf").write_bytes(out)
PY

submit() {
  curl -sS \
    -F "ocr=auto" \
    -F "file=@$1" \
    "$BASE_URL/v1/files/parse"
}

PDF_RESP=$(submit "$WORK/sample.pdf")
export PDF_RESP
echo "PDF_SUBMIT $(python3 -c 'import json,os; d=json.loads(os.environ["PDF_RESP"]); print(d["status"], d["task_id"])')"

if [ "$INCLUDE_DOCX" = "1" ]; then
  DOCX_RESP=$(submit "$WORK/sample.docx")
  export DOCX_RESP
  echo "DOCX_SUBMIT $(python3 -c 'import json,os; d=json.loads(os.environ["DOCX_RESP"]); print(d["status"], d["task_id"])')"
fi

wait_task() {
  id=$1
  for _ in $(seq 1 90); do
    status=$(curl -sS "$BASE_URL/v1/tasks/$id")
    state=$(python3 -c 'import json, sys; print(json.load(sys.stdin)["status"])' <<EOF
$status
EOF
)
    if [ "$state" = "succeeded" ] || [ "$state" = "failed" ]; then
      echo "$status"
      return 0
    fi
    sleep 2
  done
  echo "TIMEOUT $id" >&2
  return 1
}

PDF_ID=$(python3 -c 'import json, os; print(json.loads(os.environ["PDF_RESP"])["task_id"])')
PDF_STATUS=$(wait_task "$PDF_ID")
export PDF_STATUS PDF_ID
echo "PDF_STATUS $(python3 -c 'import json,os; d=json.loads(os.environ["PDF_STATUS"]); print(d["status"], d.get("error"))')"

if [ "$(python3 -c 'import json,os; print(json.loads(os.environ["PDF_STATUS"])["status"])')" != "succeeded" ]; then
  echo "PDF task did not succeed" >&2
  exit 1
fi

curl -sS "$BASE_URL/v1/tasks/$PDF_ID/markdown" | head -c 200
echo
curl -sS "$BASE_URL/v1/tasks/$PDF_ID/content-list" | head -c 200
echo
curl -sS "$BASE_URL/v1/tasks/$PDF_ID/middle" | head -c 200
echo

PDF_RESULT=$(curl -sS "$BASE_URL/v1/tasks/$PDF_ID/result")
export PDF_RESULT
python3 - <<'PY'
import json
import os
import urllib.request

base = os.environ["BASE_URL"]
task_id = os.environ["PDF_ID"]
data = json.loads(os.environ["PDF_RESULT"])
arts = data.get("artifacts") or {}
print("PDF_RESULT engine=", data.get("engine"), "version=", data.get("engine_version"))
print("PDF_RESULT artifacts=", arts)
images_dir = arts.get("images_dir")
if not images_dir:
    print("ASSET_NONE no images_dir")
    raise SystemExit(0)
try:
    with urllib.request.urlopen(f"{base}/v1/tasks/{task_id}/content-list", timeout=30) as resp:
        cl = json.loads(resp.read().decode("utf-8"))
except Exception as exc:
    print("ASSET_SKIP content-list", exc)
    raise SystemExit(0)
names = []
if isinstance(cl, list):
    for item in cl:
        if not isinstance(item, dict):
            continue
        for key in ("img_path", "image_path", "path"):
            val = item.get(key)
            if isinstance(val, str) and val:
                names.append(val.split("/")[-1])
                break
if names:
    name = names[0]
    url = f"{base}/v1/tasks/{task_id}/assets/{name}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        body = resp.read()
    print("ASSET_OK", name, "bytes=", len(body))
else:
    print("ASSET_NONE listed in content-list")
PY

if [ "$INCLUDE_DOCX" = "1" ]; then
  DOCX_ID=$(python3 -c 'import json, os; print(json.loads(os.environ["DOCX_RESP"])["task_id"])')
  DOCX_STATUS=$(wait_task "$DOCX_ID")
  export DOCX_STATUS DOCX_ID
  echo "DOCX_STATUS $(python3 -c 'import json,os; d=json.loads(os.environ["DOCX_STATUS"]); print(d["status"], d.get("error"))')"
  if [ "$(python3 -c 'import json,os; print(json.loads(os.environ["DOCX_STATUS"])["status"])')" = "succeeded" ]; then
    curl -sS "$BASE_URL/v1/tasks/$DOCX_ID/markdown" | head -c 200
    echo
  fi
fi

echo "SMOKE_OK"
