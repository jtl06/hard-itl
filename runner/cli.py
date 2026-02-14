from __future__ import annotations

import argparse

from runner import Runner, RunConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="Run UART HIL test and capture artifacts")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--baud-rate", required=True, type=int)
    parser.add_argument("--mode", default="mock", choices=["mock", "real"])
    parser.add_argument("--ssh-host", default="")
    parser.add_argument("--ssh-user", default="pi")
    parser.add_argument("--remote-cmd", default="python3 /opt/hil/run_uart_test.py")
    args = parser.parse_args()

    run_dir = Runner("runs").execute(
        RunConfig(
            run_id=args.run_id,
            baud_rate=args.baud_rate,
            mode=args.mode,
            ssh_host=args.ssh_host,
            ssh_user=args.ssh_user,
            remote_cmd=args.remote_cmd,
        )
    )
    print(run_dir)


if __name__ == "__main__":
    main()
