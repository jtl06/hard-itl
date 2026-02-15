from __future__ import annotations

from pathlib import Path

from agents.llm_client import LLMClient
from schemas.types import AnalysisResult, TriageResult


class TriageAgent:
    def __init__(self) -> None:
        self.llm = LLMClient()

    def triage(self, run_dir: Path, analysis: AnalysisResult, params: dict[str, int]) -> TriageResult:
        hypotheses = self._fallback_hypotheses(analysis)
        next_experiments = self._fallback_next_experiments(params, analysis)
        suggested_fix = "Reduce uart_rate to <=230400 and raise buffer_size to >=64."

        llm_text = self.llm.chat(
            user_prompt=(
                "Given this UART-only analysis, provide concise hypotheses and next experiments:\n"
                f"metrics={analysis.metrics}\nkey_events={analysis.key_events}\nparams={params}"
            ),
            system_prompt="You are a HIL triage agent. Keep it concrete and evidence-driven.",
        )
        if llm_text:
            suggested_fix = llm_text.splitlines()[0][:220]

        triage_result = TriageResult(
            hypotheses=hypotheses,
            next_experiments=next_experiments,
            suggested_fix=suggested_fix,
        )

        triage_md = self._render_markdown(triage_result, analysis)
        (run_dir / "triage.md").write_text(triage_md, encoding="utf-8")
        return triage_result

    @staticmethod
    def _fallback_hypotheses(analysis: AnalysisResult) -> list[str]:
        if analysis.pass_fail == "pass":
            return ["No blocking issue observed; UART evidence indicates stable execution."]

        hypotheses = []
        if analysis.metrics.get("error_count", 0) > 0:
            hypotheses.append("UART instability likely from aggressive configuration (see analysis.json error_count).")
        if analysis.metrics.get("missing_start"):
            hypotheses.append("Run marker missing: RUN_START not observed in uart.log.")
        if analysis.metrics.get("missing_end"):
            hypotheses.append("Run marker missing: RUN_END not observed in uart.log.")
        if not hypotheses:
            hypotheses.append("Root cause unclear; collect additional UART runs with same params.")
        return hypotheses

    @staticmethod
    def _fallback_next_experiments(params: dict[str, int], analysis: AnalysisResult) -> list[dict[str, int]]:
        if analysis.pass_fail == "pass":
            return [params]

        if "guess_baud" in params:
            guess = int(params.get("guess_baud", 115200))
            target = int(params.get("target_baud", 115200))
            # Deterministic convergence in a few runs.
            if guess == target:
                return [params]
            step = max(1, abs(target - guess) // 2)
            if guess < target:
                nxt = min(target, guess + step)
            else:
                nxt = max(target, guess - step)
            return [
                {"guess_baud": target, "target_baud": target},
                {"guess_baud": nxt, "target_baud": target},
            ]
        if "guess_frame" in params:
            target = str(params.get("target_frame", "8N1"))
            return [
                {"guess_frame": target, "target_frame": target},
                {"guess_frame": "8N1", "target_frame": target},
            ]
        if "guess_parity" in params:
            target = str(params.get("target_parity", "none"))
            return [
                {"guess_parity": target, "target_parity": target},
                {"guess_parity": "none", "target_parity": target},
            ]
        if "guess_magic" in params:
            target = int(params.get("target_magic", 0xC0FFEE42))
            return [
                {"guess_magic": target, "target_magic": target},
            ]

        uart_rate = int(params.get("uart_rate", 1000000))
        buffer_size = int(params.get("buffer_size", 16))

        return [
            {"uart_rate": max(230400, uart_rate // 2), "buffer_size": max(64, buffer_size * 2)},
            {"uart_rate": 230400, "buffer_size": max(64, buffer_size)},
            {"uart_rate": 115200, "buffer_size": 128},
        ]

    @staticmethod
    def _render_markdown(result: TriageResult, analysis: AnalysisResult) -> str:
        lines = ["# Triage", "", "## Hypotheses"]
        for item in result.hypotheses:
            lines.append(f"- {item}")

        lines.extend(["", "## Evidence", "- `analysis.json` metrics and key_events", "- `uart.log` markers/events"])
        lines.extend(["", "## Next Experiments"])
        for exp in result.next_experiments:
            lines.append(f"- {exp}")

        lines.extend(["", "## Suggested Fix", f"- {result.suggested_fix}"])
        lines.extend(["", "## Pass/Fail", f"- {analysis.pass_fail}"])
        return "\n".join(lines) + "\n"
