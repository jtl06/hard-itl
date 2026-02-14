from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import dataclass

try:
    import aiohttp
except Exception:  # pragma: no cover - optional at runtime
    aiohttp = None


@dataclass
class AgentOutput:
    role: str
    text: str


class NIMOrchestrator:
    """Async fan-out/fan-in orchestrator over a single NIM endpoint."""

    def __init__(self) -> None:
        self.chat_url = os.getenv("NIM_CHAT_URL", "http://localhost:8000/v1/chat/completions")
        self.model = os.getenv("NIM_MODEL", "nvidia/nemotron-nano-9b-v2")
        self.timeout_s = float(os.getenv("NIM_TIMEOUT_S", "3.0"))
        self.last_fanout: list[AgentOutput] = []

    async def run(self, user_prompt: str) -> str:
        if aiohttp is None:
            self.last_fanout = [
                AgentOutput("planner", "Fallback: run uart_rate=230400,buffer_size=64 then 115200/128."),
                AgentOutput("coder", "Fallback: ensure timestamped UART lines and explicit ERROR codes."),
                AgentOutput("critic", "Fallback: keep hardware access constrained to runner module."),
            ]
            return self._fallback_summary("aiohttp missing", user_prompt)

        planner_prompt = (
            "You are planner agent. Propose next 3-5 UART HIL experiments. "
            "Respect: only runner can touch hardware. Cite uart.log and analysis.json evidence."
        )
        coder_prompt = (
            "You are coder agent. Propose minimal instrumentation and robustness patch ideas only. "
            "No hardware access outside runner."
        )
        critic_prompt = (
            "You are critic agent. Review feasibility and risk. "
            "Enforce runner-only hardware access and UART-only truth layer assumptions."
        )
        summarizer_prompt = (
            "You are summarizer agent. Merge planner/coder/critic outputs into one actionable runbook. "
            "Sections: next_experiments, instrumentation, risks, demo_guidance."
        )

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout_s)) as session:
            tasks = [
                self._call_agent(session, "planner", planner_prompt, user_prompt),
                self._call_agent(session, "coder", coder_prompt, user_prompt),
                self._call_agent(session, "critic", critic_prompt, user_prompt),
            ]
            fanout_results = await asyncio.gather(*tasks, return_exceptions=True)

            normalized: list[AgentOutput] = []
            for role, item in zip(["planner", "coder", "critic"], fanout_results):
                if isinstance(item, Exception):
                    normalized.append(AgentOutput(role=role, text=f"{role} unavailable: {item}"))
                else:
                    normalized.append(item)
            self.last_fanout = normalized

            merged_input = "\n\n".join([f"[{x.role}]\n{x.text}" for x in normalized])
            summary = await self._call_agent(session, "summarizer", summarizer_prompt, merged_input)
            return summary.text

    async def _call_agent(self, session: aiohttp.ClientSession, role: str, system_prompt: str, user_prompt: str) -> AgentOutput:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }
        async with session.post(self.chat_url, json=payload) as resp:
            if resp.status >= 400:
                body = await resp.text()
                raise RuntimeError(f"http {resp.status}: {body[:200]}")
            data = await resp.json()
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        if not text:
            text = f"{role} produced empty output"
        return AgentOutput(role=role, text=text)

    def _fallback_summary(self, reason: str, prompt: str) -> str:
        return (
            "## next_experiments\n"
            "- {'uart_rate': 230400, 'buffer_size': 64}\n"
            "- {'uart_rate': 115200, 'buffer_size': 128}\n\n"
            "## instrumentation\n"
            "- Ensure every uart.log line is timestamped and includes RUN_START/RUN_END markers.\n"
            "- Add explicit ERROR codes to improve last_error_code extraction.\n\n"
            "## risks\n"
            f"- NIM unavailable ({reason}); using deterministic fallback.\n\n"
            "## demo_guidance\n"
            "- Keep runner as the only hardware-touching module and iterate until pass.\n"
            f"- Context digest: {prompt[:160]}"
        )


def parse_next_experiments(summary_text: str) -> list[dict[str, int]]:
    experiments: list[dict[str, int]] = []
    for line in summary_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("-"):
            continue
        body = stripped.lstrip("- ").strip()
        if "uart_rate" not in body or "buffer_size" not in body:
            continue
        try:
            item = json.loads(body.replace("'", '"'))
            experiments.append({"uart_rate": int(item["uart_rate"]), "buffer_size": int(item["buffer_size"])})
        except Exception:
            continue
    return experiments


async def _amain(prompt: str) -> str:
    orch = NIMOrchestrator()
    try:
        return await orch.run(prompt)
    except Exception as exc:
        return orch._fallback_summary(str(exc), prompt)


def main() -> None:
    parser = argparse.ArgumentParser(description="4-agent async NIM orchestrator")
    parser.add_argument("--prompt", required=True)
    args = parser.parse_args()

    final_answer = asyncio.run(_amain(args.prompt))
    print(final_answer)


if __name__ == "__main__":
    main()
