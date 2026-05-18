import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_QEMU = PROJECT_ROOT / "src" / "run_qemu.py"


def main():
    target = os.environ.get("NETOS_TARGET") or os.environ.get("LITAINER_TARGET", "qemu-virt")
    cmd = [
        sys.executable,
        str(RUN_QEMU),
        "--target",
        target,
    ]
    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    sys.exit(main())
