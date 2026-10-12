#!/usr/bin/env bash
# Generate docker-compose.npu.override.yml for docparse-mineru34.
#
# Default: auto-pick a free host NPU (no processes, lowest HBM use),
# map it into the container as /dev/davinci0, set ASCEND_RT_VISIBLE_DEVICES=0.
#
# Usage:
#   ./scripts/render_npu_compose_override.sh           # auto-pick free card
#   ./scripts/render_npu_compose_override.sh auto      # same
#   ./scripts/render_npu_compose_override.sh 3         # force host card 3
#   ./scripts/render_npu_compose_override.sh 5 out.yml
#   NPU_CARD=3 ./scripts/render_npu_compose_override.sh
#   ALL=1 ./scripts/render_npu_compose_override.sh     # passthrough all davinci*
#
# Then:
#   docker-compose -f docker-compose.runtime.yml -f docker-compose.npu.override.yml up -d

set -eu

SERVICE_NAME=docparse-mineru34
output=docker-compose.npu.override.yml
card="${NPU_CARD:-auto}"

list_host_npu_ids() {
  local d id
  for d in /dev/davinci[0-9]*; do
    [ -e "$d" ] || continue
    id=${d#/dev/davinci}
    [[ "$id" =~ ^[0-9]+$ ]] && printf '%s\n' "$id"
  done | sort -n
}

# Return 0 if NPU has no running compute processes.
npu_is_idle() {
  local id=$1
  local out
  if ! command -v npu-smi >/dev/null 2>&1; then
    return 0
  fi
  out=$(npu-smi info -t proc -i "$id" 2>/dev/null || true)
  if [ -z "$out" ]; then
    # Fallback: scan full info block for this NPU.
    out=$(npu-smi info 2>/dev/null || true)
    if echo "$out" | grep -E "No running processes found in NPU[[:space:]]*${id}([[:space:]]|$)" >/dev/null 2>&1; then
      return 0
    fi
    # If we cannot tell, treat as busy to avoid colliding.
    if echo "$out" | grep -E "NPU[[:space:]]+ID|Process name|Proc name" >/dev/null 2>&1; then
      # Has a process table somewhere; only accept explicit idle line.
      return 1
    fi
    return 0
  fi
  if echo "$out" | grep -qiE 'No running processes'; then
    return 0
  fi
  # Any numeric PID line under process dump => busy
  if echo "$out" | grep -E '\|[[:space:]]*[0-9]+[[:space:]]*\|[[:space:]]*[0-9]+' >/dev/null 2>&1; then
    return 1
  fi
  if echo "$out" | grep -qiE 'python|pytorch|mindspore|vllm|lmdeploy|train|worker'; then
    return 1
  fi
  return 0
}

# Best-effort HBM used (MiB). Unknown => large number so it sorts last among ties.
npu_hbm_used_mib() {
  local id=$1
  local out val
  if ! command -v npu-smi >/dev/null 2>&1; then
    echo 999999999
    return
  fi
  out=$(npu-smi info -t usages -i "$id" 2>/dev/null || true)
  if [ -z "$out" ]; then
    out=$(npu-smi info -t memory -i "$id" 2>/dev/null || true)
  fi
  # Match patterns like "HBM-Usage(MB) : 1234" / "Memory Usage Rate(%) : 12" / "1234 / 65536"
  val=$(printf '%s\n' "$out" | grep -iE 'HBM.*Usage|Memory-Usage|Mem Usage|Used Memory' | head -1 | grep -oE '[0-9]+' | head -1 || true)
  if [[ "${val:-}" =~ ^[0-9]+$ ]]; then
    echo "$val"
  else
    echo 999999999
  fi
}

pick_free_npu() {
  local id used best_id="" best_used=999999999
  local -a ids=()
  local -a idle=()

  while IFS= read -r id; do
    [ -n "$id" ] && ids+=("$id")
  done < <(list_host_npu_ids)

  if [ "${#ids[@]}" -eq 0 ]; then
    echo "no /dev/davinci* devices found on host" >&2
    return 1
  fi

  if ! command -v npu-smi >/dev/null 2>&1; then
    echo "warning: npu-smi not found; falling back to lowest davinci id ${ids[0]}" >&2
    echo "${ids[0]}"
    return 0
  fi

  for id in "${ids[@]}"; do
    if npu_is_idle "$id"; then
      idle+=("$id")
      used=$(npu_hbm_used_mib "$id")
      echo "  candidate NPU ${id}: idle, hbm_used~${used}" >&2
      if [ "$used" -lt "$best_used" ]; then
        best_used=$used
        best_id=$id
      fi
    else
      echo "  skip NPU ${id}: busy (processes present)" >&2
    fi
  done

  if [ -z "$best_id" ]; then
    echo "no idle NPU found among: ${ids[*]}" >&2
    echo "hint: free a card or force one: $0 <card_id>" >&2
    return 1
  fi

  echo "selected NPU ${best_id} (lowest HBM among ${#idle[@]} idle card(s))" >&2
  echo "$best_id"
}

if [ "${1:-}" = "--all" ] || [ "${ALL:-0}" = "1" ]; then
  mode=all
  if [ "${1:-}" = "--all" ]; then
    shift
  fi
  output=${1:-docker-compose.npu.override.yml}
elif [ "${1:-}" = "auto" ] || [ "${1:-}" = "" ]; then
  mode=single
  card=auto
  output=${2:-docker-compose.npu.override.yml}
elif [[ "${1}" =~ ^[0-9]+$ ]]; then
  mode=single
  card=$1
  output=${2:-docker-compose.npu.override.yml}
else
  # Treat first arg as output path; card from NPU_CARD or auto
  mode=single
  output=$1
fi

if [ "$mode" = "all" ]; then
  {
    cat <<YAML
services:
  ${SERVICE_NAME}:
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
      printf '      []\n'
    fi
  } > "$output"
  echo "wrote $output (passthrough all host NPU devices)"
  exit 0
fi

if [ "$card" = "auto" ]; then
  echo "scanning host NPUs for an idle card..." >&2
  card=$(pick_free_npu)
fi

if ! [[ "$card" =~ ^[0-9]+$ ]]; then
  echo "card_id must be an integer or 'auto', got: $card" >&2
  exit 1
fi

host_dev="/dev/davinci${card}"
if [ ! -e "$host_dev" ]; then
  echo "missing host device: $host_dev" >&2
  exit 1
fi

{
  cat <<YAML
services:
  ${SERVICE_NAME}:
    devices:
      - "${host_dev}:/dev/davinci0"
YAML

  for dev in /dev/davinci_manager /dev/devmm_svm /dev/hisi_hdc; do
    if [ -e "$dev" ]; then
      printf '      - "%s:%s"\n' "$dev" "$dev"
    else
      echo "warning: missing $dev" >&2
    fi
  done

  cat <<'YAML'
    environment:
      ASCEND_RT_VISIBLE_DEVICES: "0"
      DOCPARSE_MINERU_DEVICE: npu
YAML
} > "$output"

echo "wrote $output (host ${host_dev} -> container /dev/davinci0, ASCEND_RT_VISIBLE_DEVICES=0)"
