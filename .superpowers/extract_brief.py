from pathlib import Path
import re
import sys

plan_path = Path(sys.argv[1])
task_n = int(sys.argv[2])
out_path = Path(sys.argv[3])

plan = plan_path.read_text(encoding="utf-8")
lines = plan.splitlines(keepends=True)
out = []
intask = False
fence = False
heading = re.compile(r"^#+[ \t]+Task[ \t]+(\d+)")
for line in lines:
    if line.startswith("```"):
        fence = not fence
    if not fence:
        m = heading.match(line)
        if m:
            intask = int(m.group(1)) == task_n
    if intask:
        out.append(line)

if not out:
    raise SystemExit(f"task {task_n} not found")
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text("".join(out), encoding="utf-8")
print(f"wrote {out_path}: {len(out)} lines")
