#!/usr/bin/env bash
set -euo pipefail

CHAT_URL="${NIM_CHAT_URL:-http://localhost:8000/v1/chat/completions}"
MODEL="${NIM_MODEL:-nvidia/nemotron-nano-9b-v2}"

call_agent() {
  local role="$1"
  local sys="$2"
  local usr="$3"

  curl -sS "$CHAT_URL" \
    -H 'Content-Type: application/json' \
    -d "$(cat <<JSON
{
  \"model\": \"$MODEL\",
  \"messages\": [
    {\"role\": \"system\", \"content\": \"$sys\"},
    {\"role\": \"user\", \"content\": \"$usr\"}
  ],
  \"temperature\": 0.2
}
JSON
)" > "/tmp/${role}_nim_response.json"
}

PROMPT="RP2350 UART HIL run failed; evidence in uart.log and analysis.json. Runner is the only hardware-touching module."

call_agent planner "You are planner; propose next UART experiments only." "$PROMPT" &
call_agent coder "You are coder; suggest minimal instrumentation patches only." "$PROMPT" &
call_agent critic "You are critic; review risks and feasibility." "$PROMPT" &

wait

echo "planner response: /tmp/planner_nim_response.json"
echo "coder response:   /tmp/coder_nim_response.json"
echo "critic response:  /tmp/critic_nim_response.json"
echo "concurrency smoke test complete"
