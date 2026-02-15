from __future__ import annotations

import argparse
import asyncio
import ast
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Callable

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
        self.execution_mode = os.getenv("NIM_EXECUTION_MODE", "sequential").strip().lower() or "sequential"
        if self.execution_mode not in {"sequential", "parallel"}:
            self.execution_mode = "sequential"
        self.coordinator_rework_rounds = max(0, int(os.getenv("NIM_COORDINATOR_REWORK_ROUNDS", "0")))
        self.peer_message_rounds = max(0, int(os.getenv("NIM_PEER_MESSAGE_ROUNDS", "1")))
        self.timeout_s = float(os.getenv("NIM_TIMEOUT_S", "3.0"))
        self.max_tokens = max(64, int(os.getenv("NIM_MAX_TOKENS", "512")))
        self.min_visible_running_s = float(os.getenv("NIM_MIN_RUNNING_S", "0.5"))
        self.role_min_visible_s = {
            "planner": float(os.getenv("NIM_MIN_RUNNING_PLANNER_S", "0.5")),
            "coder": float(os.getenv("NIM_MIN_RUNNING_CODER_S", "0.45")),
            "critic": float(os.getenv("NIM_MIN_RUNNING_CRITIC_S", "0.7")),
            "verifier": float(os.getenv("NIM_MIN_RUNNING_VERIFIER_S", "0.7")),
            "summarizer": float(os.getenv("NIM_MIN_RUNNING_SUMMARIZER_S", "0.55")),
        }
        self.last_fanout: list[AgentOutput] = []

    async def run(
        self,
        user_prompt: str,
        status_callback: Callable[[str, str, str], None] | None = None,
    ) -> str:
        if aiohttp is None:
            self.last_fanout = [
                AgentOutput("planner", "Fallback: run uart_rate=230400,buffer_size=64 then 115200/128."),
                AgentOutput("coder", "Fallback: ensure timestamped UART lines and explicit ERROR codes."),
                AgentOutput("critic", "Fallback: keep hardware access constrained to runner module."),
                AgentOutput(
                    "verifier",
                    "Fallback: confidence=0.42; validator flags possible typo/malformed key risks in coder proposal.",
                ),
            ]
            if status_callback is not None:
                status_callback("planner", "running", "Planning next experiments from UART evidence.")
                await asyncio.sleep(0.25)
                status_callback("coder", "running", "Drafting minimal instrumentation improvements.")
                await asyncio.sleep(0.2)
                status_callback("critic", "running", "Reviewing feasibility and runner-only constraints.")
                await asyncio.sleep(0.35)
                status_callback("verifier", "running", "Scoring evidence quality and confidence.")
                await asyncio.sleep(0.2)
                for item in self.last_fanout:
                    status_callback(item.role, "fallback", item.text)
                status_callback("summarizer", "running", "Merging planner/coder/debugger/verifier updates.")
                await asyncio.sleep(0.4)
                status_callback("summarizer", "fallback", "Using deterministic fallback summary.")
            return self._fallback_summary("aiohttp missing", user_prompt)

        planner_prompt = (
            f"Allowed UART baud options: {os.getenv('NIM_BAUD_OPTIONS', '9600,19200,38400,57600,74880,115200,230400,460800,921600,1000000,1500000,2000000')}. "
            "You are planner agent. Propose next 3-5 UART HIL experiments. "
            "Respect: only runner can touch hardware. Cite uart.log and analysis.json evidence. "
            "If case=uart_demo, propose guess_baud values only from allowed options. "
            "If case=framing_hunt use guess_frame. If case=parity_hunt use guess_parity. "
            "If case=signature_check use guess_magic. "
            "Emit proposals as one-line dict bullets, e.g. - {'guess_baud': 230400}"
        )
        coder_prompt = (
            "You are coder agent. Propose minimal instrumentation and robustness patch ideas only. "
            "No hardware access outside runner."
        )
        critic_prompt = (
            "You are critic agent. Review feasibility and risk. "
            "Enforce runner-only hardware access and UART-only truth layer assumptions."
        )
        verifier_prompt = (
            "You are verifier agent (validator). Judge evidence quality and confidence from UART-only data, "
            "and audit coder output for correctness risks: typos, malformed parameter keys, invalid value ranges, "
            "or contradictory patch instructions. "
            "Return concise sections: confidence[0,1], coder_validation, blockers, acceptance_criteria."
        )
        summarizer_prompt = (
            "You are summarizer agent. Merge planner/coder/critic/verifier outputs into one actionable runbook. "
            "Sections: next_experiments, instrumentation, risks, verification, demo_guidance."
        )
        prompt_by_role = {
            "planner": planner_prompt,
            "coder": coder_prompt,
            "critic": critic_prompt,
            "verifier": verifier_prompt,
        }

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout_s)) as session:
            normalized: list[AgentOutput] = []
            if self.execution_mode == "parallel":
                # Dependency-driven pipeline:
                # planner/coder can run together from raw evidence,
                # critic starts after coder output exists,
                # verifier starts after planner/coder/critic are available.
                planner_task = asyncio.create_task(
                    self._call_agent(session, "planner", planner_prompt, user_prompt, status_callback)
                )
                coder_task = asyncio.create_task(
                    self._call_agent(session, "coder", coder_prompt, user_prompt, status_callback)
                )

                planner_out: AgentOutput
                coder_out: AgentOutput
                try:
                    planner_out = await planner_task
                except Exception as exc:
                    planner_out = AgentOutput(role="planner", text=f"planner unavailable: {exc}")
                    if status_callback is not None:
                        status_callback("planner", "error", str(exc))
                try:
                    coder_out = await coder_task
                except Exception as exc:
                    coder_out = AgentOutput(role="coder", text=f"coder unavailable: {exc}")
                    if status_callback is not None:
                        status_callback("coder", "error", str(exc))

                critic_input = (
                    user_prompt
                    + "\n\n[coder_proposal]\n"
                    + coder_out.text
                    + "\n\n[planner_experiments]\n"
                    + planner_out.text
                )
                try:
                    critic_out = await self._call_agent(session, "critic", critic_prompt, critic_input, status_callback)
                except Exception as exc:
                    critic_out = AgentOutput(role="critic", text=f"critic unavailable: {exc}")
                    if status_callback is not None:
                        status_callback("critic", "error", str(exc))

                verifier_input = (
                    user_prompt
                    + "\n\n[planner]\n"
                    + planner_out.text
                    + "\n\n[coder]\n"
                    + coder_out.text
                    + "\n\n[critic]\n"
                    + critic_out.text
                )
                try:
                    verifier_out = await self._call_agent(
                        session, "verifier", verifier_prompt, verifier_input, status_callback
                    )
                except Exception as exc:
                    verifier_out = AgentOutput(role="verifier", text=f"verifier unavailable: {exc}")
                    if status_callback is not None:
                        status_callback("verifier", "error", str(exc))

                normalized = [planner_out, coder_out, critic_out, verifier_out]
            else:
                for role, prompt in (
                    ("planner", planner_prompt),
                    ("coder", coder_prompt),
                    ("critic", critic_prompt),
                    ("verifier", verifier_prompt),
                ):
                    try:
                        item = await self._call_agent(session, role, prompt, user_prompt, status_callback)
                        normalized.append(item)
                    except Exception as exc:
                        normalized.append(AgentOutput(role=role, text=f"{role} unavailable: {exc}"))
                        if status_callback is not None:
                            status_callback(role, "error", str(exc))

            # Optional peer-to-peer follow-up rounds before summarization.
            for round_idx in range(self.peer_message_rounds):
                inbox = self._collect_peer_messages(normalized)
                if not any(inbox.values()):
                    break
                refreshed: list[AgentOutput] = []
                for item in normalized:
                    role = item.role
                    msgs = inbox.get(role, [])
                    if not msgs:
                        refreshed.append(item)
                        continue
                    if status_callback is not None:
                        for msg in msgs[:3]:
                            status_callback(role, "running", f"Peer call {msg} -> {role}")
                    peer_prompt = (
                        "Peer agents requested follow-up specialization. "
                        f"Address these requests for role={role} and refine your output.\n\n"
                        f"[peer_requests_round_{round_idx + 1}]\n"
                        + "\n".join(f"- {m}" for m in msgs)
                        + "\n\n[current_output]\n"
                        + item.text
                        + "\n\n[original_evidence]\n"
                        + user_prompt
                    )
                    try:
                        updated = await self._call_agent(
                            session,
                            role,
                            prompt_by_role[role],
                            peer_prompt,
                            status_callback,
                        )
                    except Exception as exc:
                        updated = AgentOutput(role=role, text=f"{role} unavailable after peer request: {exc}")
                        if status_callback is not None:
                            status_callback(role, "error", str(exc))
                    refreshed.append(updated)
                normalized = refreshed
            self.last_fanout = normalized

            merged_input = "\n\n".join([f"[{x.role}]\n{x.text}" for x in normalized])
            summary = await self._call_agent(session, "summarizer", summarizer_prompt, merged_input, status_callback)

            # Optional coordinator -> coder feedback loop for extra refinement.
            if self.execution_mode == "sequential" and self.coordinator_rework_rounds > 0:
                for round_idx in range(self.coordinator_rework_rounds):
                    feedback_prompt = (
                        "Coordinator requests one focused refinement pass. "
                        "Revise instrumentation/fix guidance only. Keep it minimal and actionable.\n\n"
                        f"[current_summary_round_{round_idx + 1}]\n{summary.text}\n\n"
                        f"[original_evidence]\n{user_prompt}"
                    )
                    coder_rework = await self._call_agent(
                        session,
                        "coder",
                        coder_prompt,
                        feedback_prompt,
                        status_callback,
                    )
                    merged_input = (
                        merged_input
                        + f"\n\n[coder_rework_round_{round_idx + 1}]\n{coder_rework.text}"
                    )
                    summary = await self._call_agent(
                        session,
                        "summarizer",
                        summarizer_prompt,
                        merged_input,
                        status_callback,
                    )
            return summary.text

    @staticmethod
    def _collect_peer_messages(outputs: list[AgentOutput]) -> dict[str, list[str]]:
        inbox: dict[str, list[str]] = {"planner": [], "coder": [], "critic": [], "verifier": []}
        for item in outputs:
            for raw in item.text.splitlines():
                line = raw.strip()
                if not line:
                    continue
                match = re.match(
                    r"^(?:@|CALL\s+)(planner|coder|critic|verifier)\s*:\s*(.+)$",
                    line,
                    flags=re.IGNORECASE,
                )
                if not match:
                    continue
                role = match.group(1).lower()
                msg = match.group(2).strip()
                if msg:
                    inbox[role].append(f"from {item.role}: {msg}")
        return inbox

    async def _call_agent(
        self,
        session: aiohttp.ClientSession,
        role: str,
        system_prompt: str,
        user_prompt: str,
        status_callback: Callable[[str, str, str], None] | None = None,
    ) -> AgentOutput:
        if status_callback is not None:
            status_callback(role, "running", "Working on current evidence bundle.")
        t0 = time.perf_counter()
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "max_tokens": self.max_tokens,
        }
        async with session.post(self.chat_url, json=payload) as resp:
            if resp.status >= 400:
                body = await resp.text()
                raise RuntimeError(f"http {resp.status}: {body[:200]}")
            data = await resp.json()
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        if not text:
            text = f"{role} produced empty output"
        elapsed = time.perf_counter() - t0
        role_min = self.role_min_visible_s.get(role, self.min_visible_running_s)
        if elapsed < role_min:
            await asyncio.sleep(role_min - elapsed)
        if status_callback is not None:
            status_callback(role, "done", text)
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


def parse_next_experiments(summary_text: str) -> list[dict[str, int | str]]:
    experiments: list[dict[str, int | str]] = []
    for line in summary_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("-"):
            continue
        body = stripped.lstrip("- ").strip()
        if "{" not in body or "}" not in body:
            continue
        start = body.find("{")
        end = body.rfind("}")
        if start < 0 or end <= start:
            continue
        body_dict = body[start : end + 1]
        try:
            item = ast.literal_eval(body_dict)
            if not isinstance(item, dict):
                continue
            out: dict[str, int | str] = {}
            for key in (
                "guess_baud",
                "guess_frame",
                "guess_parity",
                "guess_magic",
                "target_baud",
                "target_frame",
                "target_parity",
                "target_magic",
                "uart_rate",
                "buffer_size",
            ):
                if key not in item:
                    continue
                val = item[key]
                if key in {"guess_frame", "guess_parity", "target_frame", "target_parity"}:
                    out[key] = str(val)
                else:
                    out[key] = int(val)
            if out:
                experiments.append(out)
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
    parser = argparse.ArgumentParser(description="5-agent async NIM orchestrator")
    parser.add_argument("--prompt", required=True)
    args = parser.parse_args()

    final_answer = asyncio.run(_amain(args.prompt))
    print(final_answer)


if __name__ == "__main__":
    main()
