from __future__ import annotations

import json
import os
from urllib import error, request


class LLMClient:
    def __init__(self) -> None:
        base = os.getenv("NIM_BASE_URL")
        if base:
            self.base_url = base
        else:
            dgx_host = os.getenv("DGX_HOST", "127.0.0.1")
            self.base_url = f"http://{dgx_host}:8000/v1"
        self.model = os.getenv("NIM_MODEL", "meta/llama-3.1-8b-instruct")

    def chat(self, user_prompt: str, system_prompt: str, timeout_s: int = 8) -> str | None:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
        }

        try:
            req = request.Request(
                f"{self.base_url}/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with request.urlopen(req, timeout=timeout_s) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()
        except (error.URLError, TimeoutError, KeyError, json.JSONDecodeError):
            return None
