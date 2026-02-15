from __future__ import annotations

from schemas.types import AnalysisResult, TriageResult


class PlannerAgent:
    # Try common UART baud rates first for clearer demo behavior.
    _COMMON_BAUDS = [9600, 19200, 38400, 57600, 74880, 115200, 230400, 460800, 921600, 1000000]

    def initial_request(self) -> dict[str, int]:
        # Default initial search point for baud-hunt demos.
        return {"guess_baud": 115200, "baud_probe_idx": 0}

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
            common = self._ordered_common_bauds(guess)
            last_direction = str(previous_params.get("last_baud_direction", "unknown")).lower()
            last_guess = int(previous_params.get("last_baud_guess", guess))

            if direction in {"higher", "lower"}:
                # If direction flips, we have a bracket; refine via midpoint (can be non-standard).
                if last_direction in {"higher", "lower"} and last_direction != direction and last_guess != guess:
                    lo = min(last_guess, guess)
                    hi = max(last_guess, guess)
                    next_guess = max(1200, (lo + hi) // 2)
                else:
                    next_guess = self._directional_step(common, guess=guess, direction=direction)
            else:
                # No hint yet: explore common rates around current guess.
                if idx < len(common):
                    prev_guess = int(previous_params.get("guess_baud", 0))
                    while idx < len(common) - 1 and common[idx] == prev_guess:
                        idx += 1
                    next_guess = common[idx]
                else:
                    next_guess = common[min(len(common) - 1, idx % len(common))]
            return {
                "guess_baud": next_guess,
                "baud_probe_idx": idx + 1,
                "last_baud_direction": direction,
                "last_baud_guess": guess,
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

    def _directional_step(self, common: list[int], guess: int, direction: str) -> int:
        ordered = sorted(common)
        # Snap to nearest common bucket, with direction-aware tie-break.
        min_abs = min(abs(v - guess) for v in ordered)
        nearest_candidates = [v for v in ordered if abs(v - guess) == min_abs]
        if direction == "lower":
            nearest = max(nearest_candidates)
        else:
            nearest = min(nearest_candidates)
        nearest_idx = ordered.index(nearest)
        if direction == "higher":
            if guess < nearest:
                return nearest
            return ordered[min(len(ordered) - 1, nearest_idx + 1)]
        if guess > nearest:
            return nearest
        return ordered[max(0, nearest_idx - 1)]
