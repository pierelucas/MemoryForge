"""Personality for a scope. Separate from facts so dreaming cannot rewrite it."""

from __future__ import annotations

import re

from memoryforge.safety import redact

SLOTS = ("identity", "soul")
LIMITS = {"identity": 400, "soul": 2000}
_FIELD = re.compile(r"^(name|vibe|emoji)\s*:\s*(.*)$", re.IGNORECASE)


class PersonaError(ValueError):
    def __init__(self, key: str, german: str) -> None:
        self.key = key
        self.params: dict = {}
        super().__init__(german)


def normalize_slot(slot: str | None) -> str:
    text = (slot or "").strip().lower()
    if text not in SLOTS:
        raise PersonaError("error.persona_slot", "Slot muss identity oder soul sein.")
    return text


def clean_persona(slot: str, text: str) -> str:
    chosen = normalize_slot(slot)
    cleaned = redact(text or "")
    if not cleaned:
        return ""
    limit = LIMITS[chosen]
    if len(cleaned) > limit:
        raise PersonaError("error.persona_limit", f"Höchstens {limit} Zeichen.")
    return cleaned


def format_identity(name: str = "", vibe: str = "", emoji: str = "") -> str:
    lines = []
    if name.strip():
        lines.append(f"name: {name.strip()}")
    if vibe.strip():
        lines.append(f"vibe: {vibe.strip()}")
    if emoji.strip():
        lines.append(f"emoji: {emoji.strip()}")
    return "\n".join(lines)


def parse_identity(text: str) -> dict[str, str]:
    fields = {"name": "", "vibe": "", "emoji": "", "extra": ""}
    extra: list[str] = []
    for line in (text or "").splitlines():
        match = _FIELD.match(line.strip())
        if match and not fields[match.group(1).lower()]:
            fields[match.group(1).lower()] = match.group(2).strip()
        elif line.strip():
            extra.append(line.strip())
    fields["extra"] = "\n".join(extra)
    return fields


def identity_line(text: str) -> str:
    fields = parse_identity(text)
    parts = [fields["name"], fields["vibe"], fields["emoji"]]
    shown = " · ".join(part for part in parts if part)
    if shown:
        return shown
    return (text or "").strip().splitlines()[0][:80] if text.strip() else ""


def context_card(
    *,
    scope: str,
    persona: dict,
    directives: list[dict],
    standing: list[dict],
    durable: list[dict],
    daily: list[dict],
) -> str:
    """The text an agent should read first. Short on purpose."""
    lines = [
        "# Session card",
        f"Scope: {scope or 'all'}",
        "Project voice wins if it conflicts with global. Do not invent facts.",
        "",
    ]
    lines.extend(_persona_block("Identity", persona, "identity"))
    lines.extend(_persona_block("Voice", persona, "soul"))
    lines.extend(_fact_block("Directives", directives, empty="No standing preferences."))
    lines.extend(_fact_block("Standing", standing, empty="Nothing pinned."))
    lines.extend(_fact_block("Durable", durable, empty="No other durable facts in this card."))
    lines.extend(_fact_block("Recent notes", daily, empty="No notes from today or yesterday."))
    return "\n".join(lines).rstrip() + "\n"


def _persona_block(title: str, persona: dict, slot: str) -> list[str]:
    lines = [f"## {title}", ""]
    for label in ("global", "project"):
        block = persona.get(label) or {}
        text = (block.get(slot) or "").strip()
        if not text:
            lines.append(f"{label}: unset")
            continue
        if slot == "identity":
            lines.append(f"{label}: {identity_line(text)}")
        else:
            lines.append(f"{label}:")
            lines.extend(text.splitlines())
    lines.append("")
    return lines


def _fact_block(title: str, rows: list[dict], *, empty: str) -> list[str]:
    lines = [f"## {title}", ""]
    if not rows:
        lines.append(empty)
        lines.append("")
        return lines
    for row in rows[:4]:
        scope = row.get("scope") or ""
        prefix = "global" if scope == "global" else "project"
        text = " ".join((row.get("text") or "").split())
        if len(text) > 180:
            text = text[:177].rstrip() + "..."
        lines.append(f"- ({prefix}) {text}")
    lines.append("")
    return lines
