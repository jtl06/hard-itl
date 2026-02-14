from __future__ import annotations

import os
import json
from typing import Optional
from urllib import request, error


class NimClient:
    def __init__(self) -> None:
        dgx_host = os.getenv("DGX_HOST", "localhost")
        self.base_url = os.getenv("NIM_BASE_URL", f"http://{dgx_host}:8000/v1")
        self.model = os.getenv("NIM_MODEL", "meta/llama-3.1-8b-instruct")

    def summarize(self, prompt: str, timeout_s: int = 8) -> Optional[str]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a concise UART debugging analyst."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
        }
        try:
            req = request.Request(
                url=f"{self.base_url}/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with request.urlopen(req, timeout=timeout_s) as resp:
                body = resp.read().decode("utf-8")
            data = json.loads(body)
            return data["choices"][0]["message"]["content"].strip()
        except (error.URLError, TimeoutError, KeyError, json.JSONDecodeError):
            return None
