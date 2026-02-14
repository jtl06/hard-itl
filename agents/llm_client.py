from __future__ import annotations

import json
import os
from urllib import error, request


class LLMClient:
    def __init__(self) -> None:
        chat_url = os.getenv("NIM_CHAT_URL")
        if chat_url:
            self.chat_url = chat_url
        else:
            base = os.getenv("NIM_BASE_URL")
            if base:
                self.chat_url = f"{base.rstrip('/')}/chat/completions"
            else:
                self.chat_url = "http://localhost:8000/v1/chat/completions"
        self.model = os.getenv("NIM_MODEL", "nvidia/nemotron-nano-9b-v2")

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
                self.chat_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with request.urlopen(req, timeout=timeout_s) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()
        except (error.URLError, TimeoutError, KeyError, json.JSONDecodeError):
            return None
