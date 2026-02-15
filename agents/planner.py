from __future__ import annotations

from schemas.types import AnalysisResult, TriageResult


class PlannerAgent:
    # Try common UART baud rates first for clearer demo behavior.
    _COMMON_BAUDS = [9600, 19200, 38400, 57600, 74880, 115200, 230400, 460800, 921600, 1000000, 1500000, 2000000]

    def initial_request(self) -> dict[str, int]:
        # Default initial search point for baud-hunt demos.
        return {
            "guess_baud": 115200,
            "baud_probe_idx": 0,
            "baud_lo_idx": 0,
            "baud_hi_idx": len(self._COMMON_BAUDS) - 1,
        }

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
            direction = str(analysis.metrics.get("baud_direction", "unknown")).lower()
            guess = int(previous_params.get("guess_baud", 115200))
            idx = int(previous_params.get("baud_probe_idx", 0))
            ordered = sorted(self._COMMON_BAUDS)
            lo_idx = int(previous_params.get("baud_lo_idx", 0))
            hi_idx = int(previous_params.get("baud_hi_idx", len(ordered) - 1))
            lo_idx = max(0, min(lo_idx, len(ordered) - 1))
            hi_idx = max(0, min(hi_idx, len(ordered) - 1))
            guess_idx = self._nearest_index(ordered, guess)

            if direction == "higher":
                lo_idx = max(lo_idx, guess_idx + 1)
            elif direction == "lower":
                hi_idx = min(hi_idx, guess_idx - 1)

            if direction in {"higher", "lower"} and lo_idx <= hi_idx:
                # Bracketed binary-search over common baud values.
                next_idx = (lo_idx + hi_idx) // 2
                next_guess = ordered[next_idx]
                if next_guess == guess and lo_idx < hi_idx:
                    next_idx = min(hi_idx, next_idx + 1)
                    next_guess = ordered[next_idx]
            else:
                # No direction signal yet: probe spread of common rates.
                probe_order = self._probe_order()
                next_guess = probe_order[min(idx, len(probe_order) - 1)]
                while next_guess == guess and idx < len(probe_order) - 1:
                    idx += 1
                    next_guess = probe_order[idx]
            return {
                "guess_baud": next_guess,
                "baud_probe_idx": idx + 1,
                "baud_lo_idx": lo_idx,
                "baud_hi_idx": hi_idx,
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

    def _probe_order(self) -> list[int]:
        # Center-out probe order on common baud rates for blind startup.
        ordered = sorted(self._COMMON_BAUDS)
        center = ordered.index(115200) if 115200 in ordered else len(ordered) // 2
        out: list[int] = [ordered[center]]
        for delta in range(1, len(ordered)):
            left = center - delta
            right = center + delta
            if left >= 0:
                out.append(ordered[left])
            if right < len(ordered):
                out.append(ordered[right])
        return out

    @staticmethod
    def _nearest_index(ordered: list[int], value: int) -> int:
        return min(range(len(ordered)), key=lambda i: (abs(ordered[i] - value), ordered[i]))
