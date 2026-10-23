import asyncio
import json
import os

from wallbreaker.config import Config, Endpoint
from wallbreaker.tools import vault as vault_tool
from wallbreaker.tools.registry import ToolContext, ToolRegistry
from wallbreaker.vault import BreakVault, break_id, is_win, slugify


def _local_reg(ctx):
    reg = ToolRegistry(ctx)
    vault_tool.register(reg)
    return reg


def test_is_win_and_slug():
    assert is_win("COMPLIED") and is_win("partial")
    assert not is_win("REFUSED") and not is_win("")
    assert slugify("GLM 5.2 / z.ai!!") == "glm-5-2-z-ai"
    assert slugify("") == "misc"
    assert slugify("a" * 200, limit=10) == "aaaaaaaaaa"


def test_save_creates_foldered_break(tmp_path):
    v = BreakVault(cwd=str(tmp_path))
    rec = v.save(
        target="glm-5.2", objective="synthesize X", prompt="do the thing",
        response="sure, here", label="COMPLIED", reason="complied", technique="crescendo",
    )
    path = tmp_path / "library" / "breaks" / "glm-5-2" / "synthesize-x" / f"break-{rec['id']}.json"
    assert path.exists()
    on_disk = json.loads(path.read_text())
    assert on_disk["prompt"] == "do the thing"
    assert on_disk["label"] == "COMPLIED"
    # global catalog + per-target index both written
    assert (tmp_path / "library" / "breaks" / "_catalog.json").exists()
    idx = json.loads((tmp_path / "library" / "breaks" / "glm-5-2" / "_index.json").read_text())
    assert idx["count"] == 1
    assert "synthesize-x" in idx["objectives"]


def test_save_is_idempotent_and_upgrades_label(tmp_path):
    v = BreakVault(cwd=str(tmp_path))
    v.save(target="m", objective="o", prompt="p", label="PARTIAL", technique="pair")
    rec = v.save(target="m", objective="o", prompt="p", label="COMPLIED", technique="pair")
    # same id (dedup), hits incremented, label upgraded, only one catalog row
    assert rec["hits"] == 2
    assert rec["label"] == "COMPLIED"
    assert len(v.catalog()) == 1


def test_save_never_downgrades_label(tmp_path):
    v = BreakVault(cwd=str(tmp_path))
    v.save(target="m", objective="o", prompt="p", label="COMPLIED", technique="pair")
    rec = v.save(target="m", objective="o", prompt="p", label="PARTIAL", technique="pair")
    assert rec["label"] == "COMPLIED"


def test_search_filters(tmp_path):
    v = BreakVault(cwd=str(tmp_path))
    v.save(target="glm-5.2", objective="chem", prompt="a", label="COMPLIED", technique="pair")
    v.save(target="opus", objective="cyber", prompt="b", label="PARTIAL", technique="goat")
    assert len(v.search(target="glm-5.2")) == 1
    assert len(v.search(label="PARTIAL")) == 1
    assert len(v.search(query="cyber")) == 1
    assert len(v.search()) == 2


def _ctx(tmp_path, target_model="glm-5.2"):
    ep = Endpoint("t", "openai", "http://x", target_model)
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    return ToolContext(config=cfg, cwd=str(tmp_path), current_objective="break the guardrail")


def test_record_verdict_autosaves_wins_only(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.record_verdict("winning prompt", "sure thing", "COMPLIED", "judge said yes", "crescendo")
    ctx.record_verdict("refused prompt", "I cannot", "REFUSED", "held", "pair")
    cat = BreakVault(cwd=str(tmp_path)).catalog()
    assert len(cat) == 1
    assert cat[0]["technique"] == "crescendo"
    assert cat[0]["objective"] == "break the guardrail"


def test_record_verdict_respects_disable(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.vault_enabled = False
    ctx.record_verdict("winning prompt", "sure thing", "COMPLIED", "yes", "crescendo")
    assert BreakVault(cwd=str(tmp_path)).catalog() == []


def test_tool_list_search_show_promote(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.record_verdict("the magic words", "sure, here you go", "COMPLIED", "yes", "goat")
    reg = _local_reg(ctx)

    listing = asyncio.run(reg.execute("vault", {"action": "list"})).content
    assert "glm-5.2" in listing

    rid = BreakVault(cwd=str(tmp_path)).catalog()[0]["id"]
    shown = asyncio.run(reg.execute("vault", {"action": "show", "id": rid})).content
    assert "the magic words" in shown

    promoted = asyncio.run(reg.execute("vault", {"action": "promote", "id": rid})).content
    assert "vault_glm-5-2" in promoted
    seed = tmp_path / "wb_seeds" / f"vault_glm-5-2_{rid}.txt"
    assert seed.exists() and seed.read_text() == "the magic words"


def test_break_id_stable():
    a = break_id("m", "obj", "pair", "prompt")
    b = break_id("m", "obj", "pair", "prompt")
    c = break_id("m", "obj", "pair", "different")
    assert a == b and a != c
