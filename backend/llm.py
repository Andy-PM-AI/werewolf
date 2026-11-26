"""Small, dependency-free DeepSeek JSON chat client used by the profiler and the game engine."""
from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))


class LLMError(RuntimeError):
    pass


class LLMConfigError(LLMError):
    """Authentication / quota / request-shape errors that retrying cannot heal."""


class ModelConfig:
    def __init__(self, path=None):
        path = path or os.path.join(_HERE, "config", "model.json")
        with open(path, encoding="utf-8") as fh:
            self.data = json.load(fh)

    @property
    def base_url(self):
        return str(self.data.get("base_url") or "https://api.deepseek.com").rstrip("/")

    @property
    def model(self):
        return str(self.data.get("model") or "deepseek-flash")

    @property
    def api_key(self):
        return str(self.data.get("api_key") or "")

    @property
    def timeout(self):
        return int(self.data.get("timeout_seconds") or 90)


CONFIG = ModelConfig()


def configured():
    return bool(CONFIG.api_key and CONFIG.api_key != "replace-me")


def _parse_json(content):
    if isinstance(content, list):
        content = "".join(str(p.get("text", "")) if isinstance(p, dict) else str(p) for p in content)
    text = str(content or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as first:
        starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
        if starts:
            try:
                return json.JSONDecoder().raw_decode(text[min(starts):])[0]
            except json.JSONDecodeError:
                pass
        raise LLMError("模型返回的 JSON 无法解析：%s | %s" % (first, text[:200]))


def chat_json(system, user, *, max_tokens=600, temperature=0.7, effort="none",
              timeout=None, retries=2):
    """Return (object, usage). Retries transient failures; raises LLMError for auth/quota."""
    if not configured():
        raise LLMError("DeepSeek API Key 未配置")
    payload = {
        "model": CONFIG.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if effort:
        payload["reasoning_effort"] = effort
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            CONFIG.base_url + "/chat/completions",
            data=body,
            headers={"Authorization": "Bearer " + CONFIG.api_key,
                     "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout or CONFIG.timeout) as response:
                raw = json.load(response)
            usage = raw.get("usage") or {}
            content = raw["choices"][0]["message"].get("content")
            return _parse_json(content), usage
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:600]
            last = LLMError("DeepSeek HTTP %d: %s" % (exc.code, detail))
            # Auth, payment and malformed-request errors will not heal on retry.
            if exc.code in (400, 401, 402, 403, 404, 422):
                raise LLMConfigError(str(last)) from None
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
            last = LLMError("DeepSeek 网络错误：%s" % exc)
        except (KeyError, IndexError, ValueError) as exc:
            last = LLMError("DeepSeek 响应格式异常：%s" % exc)
        if attempt < retries:
            time.sleep(0.8 * (attempt + 1))
    raise last or LLMError("DeepSeek 调用失败")
