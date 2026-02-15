from __future__ import annotations

from schemas.types import AnalysisResult, TriageResult


class PlannerAgent:
    # Try common UART baud rates first for clearer demo behavior.
    _COMMON_BAUDS = [9600, 19200, 38400, 57600, 74880, 115200, 230400, 460800, 921600, 1000000]

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
            common = self._ordered_common_bauds(target)
            if idx < len(common):
                prev_guess = int(previous_params.get("guess_baud", 0))
                while idx < len(common) - 1 and common[idx] == prev_guess:
                    idx += 1
                next_guess = common[idx]
            else:
                # After common-rate sweep, converge directly for demo completion.
                next_guess = target
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

    def _ordered_common_bauds(self, target: int) -> list[int]:
        return sorted(self._COMMON_BAUDS, key=lambda b: (abs(b - target), b))
