"""Lead classification: hot / warm / cold.

Two layers:
1. Rules (always on, free, instant, explainable): weighted keyword signals from
   the niche pack. Handles the obvious cases ("pa-book po bukas" = hot).
2. LLM (optional): only for ambiguous leads (rule score in the warm band), so you
   pay for a model call on maybe 20-30% of conversations, not all of them.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel

PHONE_RE = re.compile(r"(\+?63|0)9\d{2}[\s-]?\d{3}[\s-]?\d{4}")
LEVELS = ["cold", "warm", "hot"]


def _compile(patterns: list[str]) -> re.Pattern:
    return re.compile(r"\b(" + "|".join(re.escape(p) for p in patterns) + r")\b", re.IGNORECASE)


def rule_classify(cfg: dict, inbound_texts: list[str], last_inbound_at: datetime | None, now: datetime) -> dict:
    cls = cfg["classification"]
    text_all = "\n".join(inbound_texts)
    recent = "\n".join(inbound_texts[-3:])

    matched: list[str] = []
    score = 0
    for name, sig in cls["signals"].items():
        # Negative signals only count if they are recent: "mahal" said a week ago
        # and followed by "ok pa-book na" should not keep the lead cold.
        haystack = recent if sig["weight"] < 0 else text_all
        if _compile(sig["patterns"]).search(haystack):
            matched.append(name)
            score += sig["weight"]

    interest, best_hits = None, 0
    for key, it in cfg.get("interests", {}).items():
        hits = len(_compile(it["keywords"]).findall(text_all))
        if hits > best_hits:
            interest, best_hits = key, hits

    th = cls["thresholds"]
    level = 2 if score >= th["hot"] else 1 if score >= th["warm"] else 0
    decayed_by = 0
    if last_inbound_at is not None:
        idle_days = (now - last_inbound_at).total_seconds() / 86400
        decayed_by = int(idle_days // cls.get("decay_days", 3))
        level = max(0, level - decayed_by)

    if "asks_to_book" in matched:
        intent = "ready_to_book"
    elif "asks_availability" in matched:
        intent = "checking_availability"
    elif any(s in matched for s in ("gone_cold", "renter")):
        intent = "lost_interest"
    elif "not_now" in matched:
        intent = "not_now"
    elif matched == ["price_only"]:
        intent = "price_check"
    else:
        intent = "browsing"

    qw = cls.get("qualified_when", {})
    qualified = (interest is not None or not qw.get("require_interest")) and any(s in matched for s in qw.get("any_signal", []))

    return {
        "method": "rules",
        "temperature": LEVELS[level],
        "score": score,
        "signals": matched,
        "interest": interest,
        "intent": intent,
        "qualified": qualified,
        "decayed_levels": decayed_by,
        "ambiguous": th["warm"] <= score < th["hot"] + 10,
    }


# ---------------------------------------------------------------- LLM layer
class LeadLabel(BaseModel):
    temperature: Literal["hot", "warm", "cold"]
    intent: str
    interest: Optional[str]
    budget_mentioned: bool
    timeline: Literal["today", "this_week", "this_month", "later", "unknown"]
    objection: Optional[str]
    next_action: str
    confidence: float


def llm_classify(cfg: dict, transcript: list[tuple[str, str]]) -> dict | None:
    """Ask Claude for a structured label. Returns None when disabled or refused."""
    if os.environ.get("LLM_CLASSIFY") != "1":
        return None
    import anthropic  # imported lazily so the POC runs without the SDK installed

    rules = cfg["classification"]
    lines = [f"{who}: {PHONE_RE.sub('[phone]', text)}" for who, text in transcript[-20:]]
    system = (
        f"You label sales conversations for a {cfg['niche']} business in the Philippines. "
        "Messages may be in English, Filipino or Taglish. "
        "hot = wants a specific date/slot, asks to book, or asks location to visit. "
        "warm = engaged, asks price plus details, compares options, no date yet. "
        "cold = one-word price check, says later/too expensive, or stopped replying. "
        f"Known interests: {', '.join(cfg.get('interests', {}).keys())}. "
        f"Signals the business cares about: {', '.join(rules['signals'].keys())}."
    )
    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=os.environ.get("LLM_MODEL", "claude-opus-5-5"),
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": "Conversation:\n" + "\n".join(lines)}],
        output_format=LeadLabel,
        # Server-side fallback: if a request is declined, the API retries on another model.
        extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
        extra_body={"fallbacks": "default"},
    )
    if response.stop_reason == "refusal" or response.parsed_output is None:
        return None
    label = response.parsed_output.model_dump()
    label["method"] = "llm"
    return label
