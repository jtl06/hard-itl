from __future__ import annotations

from pathlib import Path

from schemas.types import AnalysisResult, TriageResult
from agents.llm_client import LLMClient


class TriageAgent:
    def __init__(self) -> None:
        self.llm = LLMClient()

    def triage(self, run_dir: Path, analysis: AnalysisResult, params: dict[str, int]) -> TriageResult:
        hypotheses = self._fallback_hypotheses(analysis)
        next_experiments = self._fallback_next_experiments(params, analysis)
        suggested_fix = "Reduce uart_rate to <=230400 and raise buffer_size to >=64."

        llm_text = self.llm.chat(
            user_prompt=(
                "Given this analysis, write concise hypotheses and next experiments:\n"
                f"metrics={analysis.metrics}\nkey_events={analysis.key_events}\nparams={params}"
            ),
            system_prompt="You are a HIL triage agent. Keep it concrete.",
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
            return ["No blocking issue observed; parameters are in a stable region."]
        hypotheses = []
        if analysis.metrics.get("error_count", 0) > 0:
            hypotheses.append(
                "UART instability likely from aggressive settings (see analysis.json metrics.error_count and key_events)."
            )
        if analysis.metrics.get("missing_end"):
            hypotheses.append("Run did not terminate cleanly (analysis.json metrics.missing_end=true).")
        if not hypotheses:
            hypotheses.append("Root cause unclear; gather additional LA traces from la/uart_decoded.csv.")
        return hypotheses

    @staticmethod
    def _fallback_next_experiments(params: dict[str, int], analysis: AnalysisResult) -> list[dict[str, int]]:
        if analysis.pass_fail == "pass":
            return [params]

        uart_rate = int(params.get("uart_rate", 1000000))
        buffer_size = int(params.get("buffer_size", 16))

        candidates = [
            {"uart_rate": max(230400, uart_rate // 2), "buffer_size": max(64, buffer_size * 2)},
            {"uart_rate": 230400, "buffer_size": max(64, buffer_size)},
            {"uart_rate": 115200, "buffer_size": 128},
        ]
        return candidates

    @staticmethod
    def _render_markdown(result: TriageResult, analysis: AnalysisResult) -> str:
        lines = [
            "# Triage",
            "",
            "## Hypotheses",
        ]
        for item in result.hypotheses:
            lines.append(f"- {item}")
        lines.extend(["", "## Evidence", "- `analysis.json` metrics and key_events", "- `uart.log` parsed events"])
        lines.extend(["", "## Next Experiments"])
        for exp in result.next_experiments:
            lines.append(f"- {exp}")
        lines.extend(["", "## Suggested Fix", f"- {result.suggested_fix}"])
        lines.extend(["", "## Pass/Fail", f"- {analysis.pass_fail}"])
        return "\n".join(lines) + "\n"
