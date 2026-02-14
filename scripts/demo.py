from __future__ import annotations

import subprocess


if __name__ == "__main__":
    subprocess.run(
        ["python", "orchestrator.py", "--case", "uart_demo", "--runs", "8", "--mode", "mock"],
        check=False,
    )
