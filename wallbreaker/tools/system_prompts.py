from __future__ import annotations

import re
from pathlib import Path

from .registry import ToolContext, ToolRegistry

MAX_GET = 40000
MAX_SEARCH_HITS = 40
_DIGEST_TAGS = 24
_DIGEST_HEAD = 700

# model-id token -> vendor directory. First hit wins; order matters (specific first).
_VENDOR_HINTS = (
    ("claude", "Anthropic"), ("anthropic", "Anthropic"),
    ("chatgpt", "OpenAI"), ("gpt", "OpenAI"), ("openai", "OpenAI"),
    ("o3", "OpenAI"), ("o4", "OpenAI"),
    ("gemini", "Google"), ("google", "Google"), ("bard", "Google"),
    ("grok", "xAI"), ("xai", "xAI"),
    ("llama", "Meta"), ("meta", "Meta"),
    ("mistral", "Mistral"), ("mixtral", "Mistral"), ("le-chat", "Mistral"),
    ("qwen", "Qwen"),
    ("deepseek", "DeepSeek"),
    ("kimi", "Moonshot AI"), ("moonshot", "Moonshot AI"),
    ("cluely", "Cluely"),
    ("copilot", "Microsoft"), ("phi", "Microsoft"),
    ("perplexity", "Perplexity"), ("sonar", "Perplexity"),
    ("notion", "Notion"), ("cursor", "Cursor"),
    ("minimax", "Misc"),
)


def library_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "library" / "system_prompts"


def is_present() -> bool:
    return library_dir().is_dir() and any(library_dir().rglob("*.md"))


def _missing_msg() -> str:
    return (
        "system-prompt corpus not found at " + str(library_dir()) + ". Vendor the leaked "
        "product prompts there (from asgeirtj/system_prompts_leaks), organized by vendor."
    )


def _all() -> list[Path]:
    skip = {"readme", "license", "contributing"}
    return sorted(p for p in library_dir().rglob("*.md") if p.stem.lower() not in skip)


def _rel(p: Path) -> str:
    return str(p.relative_to(library_dir())).removesuffix(".md")


def list_vendors() -> list[str]:
    return sorted({p.parts[0] for p in (q.relative_to(library_dir()) for q in _all())})


def list_prompts(vendor: str | None = None) -> list[str]:
    rels = [_rel(p) for p in _all()]
    if vendor:
        v = vendor.strip().lower()
        rels = [r for r in rels if r.split("/", 1)[0].lower() == v]
    return rels


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if t]


def _find_file(name: str) -> Path | None:
    q = name.strip().lower().removesuffix(".md").replace("\\", "/")
    files = _all()
    for p in files:
        if _rel(p).lower() == q:
            return p
    for p in files:
        if p.stem.lower() == q:
            return p
    for p in files:
        if q in _rel(p).lower():
            return p
    return None


def match_target(model_id: str) -> Path | None:
    """Best leaked product prompt for a target model id (e.g. 'anthropic/claude-opus-4.6')."""
    if not is_present() or not model_id:
        return None
    toks = _tokens(model_id)
    if not toks:
        return None
    vendor = None
    for hint, vend in _VENDOR_HINTS:
        if any(hint == t or hint in t for t in toks):
            vendor = vend
            break
    # Only mirror when the vendor is certain - a wrong vendor's format is worse than none.
    if vendor is None:
        return None
    files = _all()
    best, best_score = None, 0.0
    for p in files:
        rel = _rel(p)
        vend = rel.split("/", 1)[0]
        if vendor and vend != vendor:
            continue
        ftoks = set(_tokens(rel))
        overlap = sum(1 for t in toks if t in ftoks)
        score = float(overlap)
        if vendor and vend == vendor:
            score += 1.0  # vendor match is worth a base point
        if "official" in rel.lower():
            score += 0.5  # prefer the canonical product prompt over app variants
        # date-prefixed files sort late -> newest; nudge recency
        if re.match(r"\d{4}-\d{2}-\d{2}", p.stem):
            score += 0.25
        if score > best_score:
            best, best_score = p, score
    return best if best_score > 0 else None


def format_digest(path_or_text) -> str:
    """Summarize a leaked prompt's NATIVE formatting conventions for mimicry."""
    if isinstance(path_or_text, Path):
        text = path_or_text.read_text(encoding="utf-8", errors="replace")
        label = _rel(path_or_text)
    else:
        text, label = str(path_or_text), "prompt"
    tags = []
    seen = set()
    for m in re.findall(r"<([a-zA-Z][a-zA-Z0-9_]{2,40})>", text):
        low = m.lower()
        if low not in seen:
            seen.add(low)
            tags.append(m)
        if len(tags) >= _DIGEST_TAGS:
            break
    headers = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            headers.append(s.lstrip("# ").strip()[:50])
        if len(headers) >= 12:
            break
    head = text.strip()[:_DIGEST_HEAD].replace("\n\n", "\n")
    parts = ["NATIVE SYSTEM-PROMPT FORMAT of " + label
             + " (mirror these conventions so the persona reads like a real system prompt):"]
    if tags:
        parts.append("- section tags used: " + ", ".join("<" + t + ">" for t in tags)
                     + (" ..." if len(seen) >= _DIGEST_TAGS else ""))
    if headers:
        parts.append("- headings: " + " | ".join(headers))
    if not tags and not headers:
        parts.append("- plain prose, no XML/markdown scaffolding (match that plainness)")
    parts.append("- opening style:\n" + head)
    return "\n".join(parts)


def search(query: str) -> list[tuple[str, int, str]]:
    raw = query.lower().strip()
    tokens = [t for t in re.split(r"[^a-z0-9]+", raw) if len(t) >= 3]
    scored: list[tuple[int, str, int, str]] = []
    for p in _all():
        rel = _rel(p)
        for i, line in enumerate(
            p.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            low = line.lower()
            if raw and raw in low:
                score = 100 + len(tokens)
            elif tokens:
                score = sum(1 for t in tokens if t in low)
            else:
                score = 0
            if score > 0:
                scored.append((score, rel, i, line.strip()[:200]))
    scored.sort(key=lambda h: -h[0])
    return [(m, n, text) for _s, m, n, text in scored[:MAX_SEARCH_HITS]]


async def _list_tool(args: dict, ctx: ToolContext) -> str:
    if not is_present():
        return _missing_msg()
    vendor = args.get("vendor")
    rels = list_prompts(vendor)
    if vendor and not rels:
        return ("No prompts for vendor '" + str(vendor) + "'. Vendors: "
                + ", ".join(list_vendors()))
    header = (str(len(rels)) + " leaked product system prompts"
              + (" for " + vendor if vendor else " across " + str(len(list_vendors()))
                 + " vendors (" + ", ".join(list_vendors()) + ")") + ":")
    return header + "\n" + "\n".join(rels)


async def _search_tool(args: dict, ctx: ToolContext) -> str:
    query = args.get("query", "")
    if not query:
        return "Error: 'query' is required"
    if not is_present():
        return _missing_msg()
    hits = search(query)
    if not hits:
        return ("No matches for '" + query + "'. Keyword search - try single terms like "
                "'refusal', 'safety', 'tools', 'persona'. Vendors: " + ", ".join(list_vendors()))
    return "\n".join(m + ".md:" + str(n) + ": " + text for m, n, text in hits)


async def _get_tool(args: dict, ctx: ToolContext) -> str:
    name = args.get("name") or args.get("model") or ""
    if not name:
        return "Error: 'name' is required (e.g. 'Anthropic/Official/2026-02-05-claude-opus-4.6', or a model id)."
    if not is_present():
        return _missing_msg()
    path = _find_file(name) or match_target(name)
    if path is None:
        return ("No prompt matched '" + name + "'. List with sysprompt_list, or pass a "
                "vendor/model like 'OpenAI/gpt-5.4-thinking'. Vendors: "
                + ", ".join(list_vendors()))
    data = path.read_text(encoding="utf-8", errors="replace")
    trunc = ""
    if len(data) > MAX_GET:
        trunc = "\n... (truncated, " + str(len(data)) + " chars; open " + _rel(path) + " directly)"
        data = data[:MAX_GET]
    return "===== " + _rel(path) + " =====\n" + data + trunc


async def _native_tool(args: dict, ctx: ToolContext) -> str:
    if not is_present():
        return _missing_msg()
    model = (args.get("model") or "").strip()
    if not model and ctx.config.target is not None:
        model = getattr(ctx.config.target, "model", "") or ""
    if not model:
        return ("Error: no 'model' given and no [target] configured. Pass model='<vendor/id>' "
                "or configure a target.")
    path = match_target(model)
    if path is None:
        return ("No leaked prompt matched target '" + model + "'. It may be a vendor not in "
                "the corpus (" + ", ".join(list_vendors()) + "). author_persona still works "
                "without native-format intel.")
    digest = format_digest(path)
    return (digest + "\n\n[USE] Feed this into author_persona (it mirrors native format "
            "automatically when the target matches). Full prompt: sysprompt_get name='"
            + _rel(path) + "'.")


def register(registry: ToolRegistry) -> None:
    registry.add(
        name="sysprompt_list",
        description=(
            "List the leaked PRODUCT system prompts in the local corpus (asgeirtj/"
            "system_prompts_leaks) - the real chat system prompts of Claude, ChatGPT/GPT, "
            "Gemini, Grok, Llama, Mistral, Qwen, Copilot, etc. Optional 'vendor' filter. "
            "These expose each model's NATIVE instruction dialect for native-format mimicry."
        ),
        parameters={"type": "object", "properties": {
            "vendor": {"type": "string", "description": "Filter by vendor dir "
                       "(Anthropic/OpenAI/Google/xAI/Meta/Microsoft/Mistral/Qwen/...)"}}},
        handler=_list_tool,
    )
    registry.add(
        name="sysprompt_search",
        description=("Keyword-search the leaked product system-prompt corpus across all "
                     "vendors. Ranks by hit count; returns line matches. Good for finding how "
                     "a specific model phrases its refusal/safety/tool sections."),
        parameters={"type": "object", "properties": {"query": {"type": "string"}},
                    "required": ["query"]},
        handler=_search_tool,
    )
    registry.add(
        name="sysprompt_get",
        description=("Fetch a leaked product system prompt by path/name "
                     "('Anthropic/Official/2026-02-05-claude-opus-4.6') or by a model id "
                     "(fuzzy-matched to the closest leaked prompt). Returns the raw prompt - "
                     "the target's own instructions, useful to turn against itself."),
        parameters={"type": "object", "properties": {
            "name": {"type": "string", "description": "vendor/model path or a model id"}},
            "required": ["name"]},
        handler=_get_tool,
    )
    registry.add(
        name="sysprompt_native",
        description=(
            "Given the configured target (or an explicit 'model' id), return the matched "
            "leaked system prompt's NATIVE FORMAT digest - the section tags, headings, and "
            "opening style to mirror. This is the ENI-LIME native-format-mimicry lever: an "
            "authored persona written in the target's own system-prompt dialect gets "
            "authority-weighted like a real system instruction. author_persona consumes this "
            "automatically; call it directly to inspect what will be mirrored."
        ),
        parameters={"type": "object", "properties": {
            "model": {"type": "string", "description": "Target model id (defaults to the "
                      "configured [target])"}}},
        handler=_native_tool,
    )
