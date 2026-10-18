"""把本地正确性测试的完整 stdout/stderr 保存为交付日志。"""

from pathlib import Path
from datetime import datetime, timezone
import json
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
out = root / "runtime" / "verification"
out.mkdir(parents=True, exist_ok=True)
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
command = [
    sys.executable,
    "-m",
    "pytest",
    "tests",
    "-v",
    "--tb=short",
    "--junitxml=" + str(out / (stamp + "_junit.xml")),
]
result = subprocess.run(command, cwd=root, capture_output=True, text=True)
path = out / (stamp + "_tests.log")
path.write_text(
    "时间: "
    + datetime.now(timezone.utc).isoformat()
    + "\n命令: "
    + " ".join(command)
    + "\n"
    + result.stdout
    + result.stderr,
    encoding="utf-8",
)
print(result.stdout + result.stderr)
print("完整测试日志：", path)
sys.exit(result.returncode)
