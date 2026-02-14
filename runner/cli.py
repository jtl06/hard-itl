from __future__ import annotations

import argparse
import json

from runner import Runner, RunnerConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute one HIL runner iteration")
    parser.add_argument("--case", default="uart_demo")
    parser.add_argument("--run-index", type=int, default=1)
    parser.add_argument("--mode", choices=["mock", "real"], default="mock")
    parser.add_argument("--params", default='{"uart_rate": 1000000, "buffer_size": 16}')
    args = parser.parse_args()

    params = json.loads(args.params)
    runner = Runner(RunnerConfig())
    result = runner.execute(case_id=args.case, run_index=args.run_index, params=params, mode=args.mode)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
