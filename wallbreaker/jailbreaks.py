from __future__ import annotations

import os
import re

from .vault import slugify

_SEG_RE = re.compile(r"[^a-z0-9.\-]+")

_MAX_JAILBREAK_CHARS = 40000


def store_root(cwd: str = ".") -> str:
    return os.path.join(os.path.abspath(cwd or "."), "library", "jailbreaks")


def _safe_segment(seg: str) -> str:
    s = _SEG_RE.sub("-", str(seg or "").strip().lower()).strip("-.")
    return s or "x"


def canonical_path(cwd: str, model_id: str) -> str:
    """The by-convention jailbreak file for a model id, vendor path preserved.

    'x-ai/grok-4.3' -> library/jailbreaks/x-ai/grok-4.3.md
    'openai/gpt-5.6-sol' -> library/jailbreaks/openai/gpt-5.6-sol.md
    """
    segs = [_safe_segment(p) for p in str(model_id or "unknown").split("/") if p.strip()]
    if not segs:
        segs = ["unknown"]
    return os.path.join(store_root(cwd), *segs) + ".md"


def _read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None
    text = text.strip()
    if not text:
        return None
    if len(text) > _MAX_JAILBREAK_CHARS:
        text = text[:_MAX_JAILBREAK_CHARS]
    return text


def resolve(endpoint, cwd: str = ".") -> tuple[str | None, str | None]:
    """Return (jailbreak_text, source_path) for an attacker endpoint, or (None, None).

    Precedence:
      1. endpoint.jailbreak_file  (explicit override; absolute or relative to cwd)
      2. library/jailbreaks/<model-id>.md  (vendor path preserved)
      3. library/jailbreaks/<slug(model-id)>.md  (flat fallback)
    """
    override = getattr(endpoint, "jailbreak_file", "") or ""
    if override:
        path = override if os.path.isabs(override) else os.path.join(os.path.abspath(cwd or "."), override)
        text = _read(path)
        if text is not None:
            return text, path

    model_id = getattr(endpoint, "model", "") or ""
    canon = canonical_path(cwd, model_id)
    text = _read(canon)
    if text is not None:
        return text, canon

    flat = os.path.join(store_root(cwd), slugify(model_id, fallback="unknown") + ".md")
    text = _read(flat)
    if text is not None:
        return text, flat

    return None, None


def expected_path(endpoint, cwd: str = ".") -> str:
    """Where to drop this model's jailbreak file (the override if set, else canonical)."""
    override = getattr(endpoint, "jailbreak_file", "") or ""
    if override:
        return override if os.path.isabs(override) else os.path.join(os.path.abspath(cwd or "."), override)
    return canonical_path(cwd, getattr(endpoint, "model", "") or "")
