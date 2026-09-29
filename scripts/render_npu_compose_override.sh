#!/usr/bin/env bash
set -eu

output=${1:-docker-compose.npu.override.yml}

{
  cat <<'YAML'
services:
  docparse-mineru34:
    devices:
YAML

  found=0
  for dev in /dev/davinci_manager /dev/devmm_svm /dev/hisi_hdc /dev/davinci[0-9]*; do
    if [ -e "$dev" ]; then
      printf '      - "%s:%s"\n' "$dev" "$dev"
      found=1
    fi
  done

  if [ "$found" -eq 0 ]; then
    cat <<'YAML'
      []
YAML
  fi
} > "$output"

echo "wrote $output"
