from __future__ import annotations

from schemas.types import AnalysisResult, TriageResult


class PlannerAgent:
    def initial_request(self) -> dict[str, int]:
        # Deliberately unstable start to exercise fail -> diagnose -> pass loop.
        return {"uart_rate": 1000000, "buffer_size": 16}

    def next_request(
        self,
        previous_params: dict[str, int],
        analysis: AnalysisResult,
        triage: TriageResult,
    ) -> dict[str, int]:
        if analysis.pass_fail == "pass":
            return previous_params

        if triage.next_experiments:
            # Pick the first triage candidate and keep deterministic progression.
            return {
                "uart_rate": int(triage.next_experiments[0].get("uart_rate", previous_params["uart_rate"])),
                "buffer_size": int(triage.next_experiments[0].get("buffer_size", previous_params["buffer_size"])),
            }

        uart_rate = max(115200, int(previous_params.get("uart_rate", 1000000)) // 2)
        buffer_size = min(256, max(64, int(previous_params.get("buffer_size", 16)) * 2))
        return {"uart_rate": uart_rate, "buffer_size": buffer_size}
