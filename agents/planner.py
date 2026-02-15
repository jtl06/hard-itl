from __future__ import annotations

from schemas.types import AnalysisResult, TriageResult


class PlannerAgent:
    # Symmetric probe sequence around target for demo visibility:
    # below, above, tighter below, tighter above, then settle.
    _BAUD_PROBE_OFFSETS = [-38400, 38400, -19200, 19200, -9600, 9600, 0]

    def initial_request(self) -> dict[str, int]:
        # Default initial search point for baud-hunt demos.
        return {"guess_baud": 115200, "target_baud": 115200, "baud_probe_idx": 0}

    def next_request(
        self,
        previous_params: dict[str, int],
        analysis: AnalysisResult,
        triage: TriageResult,
    ) -> dict[str, int]:
        if analysis.pass_fail == "pass":
            return previous_params

        # Baud-hunt mode: guided search around prior guess.
        if "guess_baud" in previous_params:
            target = int(previous_params.get("target_baud", 115200))
            idx = int(previous_params.get("baud_probe_idx", 0))
            if idx >= len(self._BAUD_PROBE_OFFSETS):
                idx = len(self._BAUD_PROBE_OFFSETS) - 1
            offset = self._BAUD_PROBE_OFFSETS[idx]
            next_guess = max(1200, int(target + offset))
            return {
                "guess_baud": next_guess,
                "target_baud": target,
                "baud_probe_idx": idx + 1,
            }
        if "guess_frame" in previous_params:
            if triage.next_experiments:
                nxt = triage.next_experiments[0]
                return {
                    "guess_frame": str(nxt.get("guess_frame", previous_params["guess_frame"])),
                    "target_frame": str(nxt.get("target_frame", previous_params.get("target_frame", "8N1"))),
                }
            return previous_params
        if "guess_parity" in previous_params:
            if triage.next_experiments:
                nxt = triage.next_experiments[0]
                return {
                    "guess_parity": str(nxt.get("guess_parity", previous_params["guess_parity"])),
                    "target_parity": str(nxt.get("target_parity", previous_params.get("target_parity", "none"))),
                }
            return previous_params
        if "guess_magic" in previous_params:
            if triage.next_experiments:
                nxt = triage.next_experiments[0]
                return {
                    "guess_magic": int(nxt.get("guess_magic", previous_params["guess_magic"])),
                    "target_magic": int(nxt.get("target_magic", previous_params.get("target_magic", 0xC0FFEE42))),
                }
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
