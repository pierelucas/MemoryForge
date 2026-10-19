from __future__ import annotations

import json
import re
from typing import Any

import httpx

from memoryforge.config import Config, KINDS

EXTRACT_SYSTEM = """You extract durable memories about a developer and their projects.
Return JSON only, no markdown:
{"actions":[
  {"op":"add","text":"...","kind":"preference|decision|convention|fact|debug"},
  {"op":"supersede","replaces":["<id>"],"text":"...","kind":"fact"},
  {"op":"noop","replaces":["<id>"]}
]}
Rules:
- One sentence per memory, in the language of the source text.
- Keep only facts that will still matter in a later session.
- Drop secrets, credentials, one-off tasks, and raw code dumps.
- If a listed memory already says this, use noop.
- If a listed memory is contradicted, supersede it.
- At most 8 actions.
- Never invent facts that are not in the source.
"""

DREAM_SYSTEM = """You consolidate a personal memory file.
You receive JSON memories with id and text.
Return JSON only:
{"actions":[{"op":"supersede","replaces":["<id>","<id>"],"text":"<merged fact>","kind":"fact"}]}
Only when two or more memories state the same fact, or one is outdated by another.
If nothing should change, return {"actions":[]}.
Never invent facts that are not supported by the input.
At most 8 actions.
"""


class LLMError(RuntimeError):
    pass


class ChatLLM:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    def extract(self, text: str, scope: str, neighbors: list[dict]) -> list[dict]:
        payload = {
            "scope": scope,
            "source": text,
            "existing": [{"id": item["id"], "text": item["text"]} for item in neighbors],
        }
        raw = self.complete(EXTRACT_SYSTEM, json.dumps(payload, ensure_ascii=False))
        return parse_actions(raw)

    def dream(self, scope: str, memories: list[dict]) -> list[dict]:
        payload = {
            "scope": scope or "all",
            "memories": [{"id": item["id"], "text": item["text"], "kind": item.get("kind")} for item in memories],
        }
        raw = self.complete(DREAM_SYSTEM, json.dumps(payload, ensure_ascii=False))
        return parse_actions(raw)

    def ping(self) -> dict[str, Any]:
        raw = self.complete(
            "Reply with JSON only.",
            '{"ping": true}',
            force_user="Return {\"ok\": true, \"model\": \"<your model id>\"}",
        )
        try:
            data = json.loads(_strip_fence(raw))
        except json.JSONDecodeError:
            data = {"ok": True, "raw": raw[:240]}
        data["model"] = self.cfg.llm.model
        return data

    def complete(self, system: str, user: str, force_user: str | None = None) -> str:
        key = self.cfg.llm.api_key.strip()
        if not key:
            raise LLMError("Kein API-Key hinterlegt.")
        base = self.cfg.llm.base_url.rstrip("/")
        url = f"{base}/chat/completions"
        body: dict[str, Any] = {
            "model": self.cfg.llm.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": force_user or user},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        if not self.cfg.llm.thinking:
            body["thinking"] = {"type": "disabled"}
        response = self._post(url, key, body)
        if response.status_code >= 400 and ("thinking" in body or "response_format" in body):
            body.pop("thinking", None)
            body.pop("response_format", None)
            response = self._post(url, key, body)
        if response.status_code >= 400:
            detail = response.text[:300].replace(key, "[redacted]")
            raise LLMError(f"API {response.status_code}: {detail}")
        data = response.json()
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("Die API hat keine Textantwort geliefert.") from exc

    def _post(self, url: str, key: str, body: dict) -> httpx.Response:
        try:
            return httpx.post(
                url,
                json=body,
                headers={"Authorization": f"Bearer {key}"},
                timeout=60,
            )
        except httpx.HTTPError as exc:
            raise LLMError(f"API nicht erreichbar: {exc.__class__.__name__}") from exc


def parse_actions(raw: str) -> list[dict]:
    data = json.loads(_strip_fence(raw))
    actions = data.get("actions") if isinstance(data, dict) else data
    if not isinstance(actions, list):
        raise LLMError("Die API hat keine actions-Liste geliefert.")
    cleaned: list[dict] = []
    for item in actions[:8]:
        if not isinstance(item, dict):
            continue
        op = str(item.get("op") or "").lower()
        if op not in {"add", "supersede", "noop", "update"}:
            continue
        kind = str(item.get("kind") or "fact")
        if kind not in KINDS:
            kind = "fact"
        replaces = item.get("replaces", item.get("id"))
        if isinstance(replaces, str):
            replaces = [replaces] if replaces else []
        elif isinstance(replaces, list):
            replaces = [str(value) for value in replaces if value]
        else:
            replaces = []
        cleaned.append(
            {
                "op": "supersede" if op == "update" else op,
                "text": str(item.get("text") or "").strip(),
                "kind": kind,
                "replaces": replaces,
            }
        )
    return cleaned


def _strip_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL).strip()
    return text
