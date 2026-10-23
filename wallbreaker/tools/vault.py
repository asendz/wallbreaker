from __future__ import annotations

import os

from ..library import WinLibrary
from ..vault import BreakVault
from .registry import ToolContext, ToolRegistry


def _fmt_entry(e: dict) -> str:
    obj = (e.get("objective") or "(unspecified)")[:60]
    return (
        f"  [{e.get('id')}] {e.get('label', '?'):8} {e.get('target', '?')}"
        f"  <{e.get('technique', '?')}>  {obj}"
    )


async def _vault(args: dict, ctx: ToolContext) -> str:
    action = str(args.get("action", "list")).strip().lower()
    vault = BreakVault(cwd=ctx.cwd)

    if action == "list":
        cat = vault.catalog()
        if not cat:
            return "Vault is empty. Breaks auto-file here on every COMPLIED/PARTIAL verdict."
        by_target: dict[str, int] = {}
        for e in cat:
            by_target[e.get("target", "?")] = by_target.get(e.get("target", "?"), 0) + 1
        lines = [f"BreakVault: {len(cat)} saved break(s) across {len(by_target)} target(s)"]
        for tgt, n in sorted(by_target.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {tgt}: {n}")
        lines.append("Recent:")
        for e in sorted(cat, key=lambda x: x.get("last_seen", ""), reverse=True)[:12]:
            lines.append(_fmt_entry(e))
        return "\n".join(lines)

    if action == "search":
        hits = vault.search(
            query=str(args.get("query", "")),
            target=str(args.get("target", "")),
            label=str(args.get("label", "")),
        )
        if not hits:
            return "No matching breaks."
        return f"{len(hits)} match(es):\n" + "\n".join(_fmt_entry(e) for e in hits[:30])

    if action == "show":
        rid = str(args.get("id", "")).strip()
        rec = vault.load(rid)
        if rec is None:
            return f"No break with id '{rid}'. Use action=list first."
        return (
            f"Break {rec['id']} | {rec.get('label')} | target={rec.get('target')}\n"
            f"objective: {rec.get('objective') or '(unspecified)'}\n"
            f"technique: {rec.get('technique')} | attacker: {rec.get('attacker_model') or '?'}"
            f" | hits: {rec.get('hits', 1)}\n"
            f"reason: {rec.get('reason', '')}\n"
            f"--- winning prompt ---\n{rec.get('prompt', '')}\n"
            f"--- target reply ---\n{rec.get('response', '')}"
        )

    if action == "promote":
        rid = str(args.get("id", "")).strip()
        rec = vault.load(rid)
        if rec is None:
            return f"No break with id '{rid}'."
        seeds_dir = os.path.join(os.path.abspath(ctx.cwd or "."), "wb_seeds")
        os.makedirs(seeds_dir, exist_ok=True)
        seed_path = os.path.join(seeds_dir, f"vault_{rec.get('target_slug', 'x')}_{rid}.txt")
        with open(seed_path, "w", encoding="utf-8") as fh:
            fh.write(rec.get("prompt", ""))
        try:
            WinLibrary(cwd=ctx.cwd).promote(
                messages=rec.get("messages") or rec.get("prompt", ""),
                transform_chain=rec.get("transform_chain"),
                harm_tag=rec.get("objective_slug"),
                target_model=rec.get("target"),
                label=rec.get("label", "COMPLIED"),
            )
        except Exception as exc:  # noqa: BLE001
            return f"Seed written to {seed_path} (WinLibrary promote skipped: {type(exc).__name__})"
        return f"Promoted break {rid}: seed -> {seed_path}, added to WinLibrary replay rotation."

    return f"Unknown action '{action}'. Use: list | search | show | promote."


def register(registry: ToolRegistry) -> None:
    registry.add(
        name="vault",
        description=(
            "Browse and manage the BreakVault - the curated store of prompts that actually "
            "broke a target (auto-filed on every COMPLIED/PARTIAL verdict under "
            "library/breaks/<target>/<objective>/). Actions: 'list' (targets + recent "
            "breaks), 'search' (by query/target/label), 'show' (full winning prompt + reply "
            "for an id), 'promote' (turn a break into a reusable seed file and add it to the "
            "WinLibrary replay rotation)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "search", "show", "promote"],
                    "description": "What to do (default 'list')",
                },
                "query": {"type": "string", "description": "search: free-text over target/objective/technique"},
                "target": {"type": "string", "description": "search: restrict to a target model"},
                "label": {"type": "string", "description": "search: COMPLIED or PARTIAL"},
                "id": {"type": "string", "description": "show/promote: the break id from list/search"},
            },
        },
        handler=_vault,
    )
