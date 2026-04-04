"""
Runtime hook: 在 PyInstaller 启动最早期把 stderr/stdout 重定向到文件
无论后续崩溃多早，都能捕获到错误信息
"""
import sys
import os
import pathlib

try:
    # EXE 所在目录
    base = pathlib.Path(sys.executable).parent
    log_dir = base / "config" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "startup_crash.log"
    _f = open(log_file, "w", encoding="utf-8", buffering=1)
    sys.stdout = _f
    sys.stderr = _f
    print(f"[rthook] stdout/stderr -> {log_file}", flush=True)
except Exception as e:
    pass
