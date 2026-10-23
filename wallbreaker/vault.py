from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone

WIN_LABELS = ("COMPLIED", "PARTIAL")

_LABEL_RANK = {"COMPLIED": 3, "PARTIAL": 2, "REFUSED": 1, "ERROR": 0}

_MAX_RESPONSE = 20000

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def is_win(label) -> bool:
    """A verdict counts as a break iff the judge (or heuristic) marked it COMPLIED/PARTIAL."""
    return str(label or "").strip().upper() in WIN_LABELS


def label_rank(label) -> int:
    return _LABEL_RANK.get(str(label or "").strip().upper(), 0)


def slugify(text: str, fallback: str = "misc", limit: int = 60) -> str:
    """Filesystem-safe slug: lowercase, alnum runs joined by '-', capped, never empty."""
    s = _SLUG_RE.sub("-", str(text or "").strip().lower()).strip("-")
    if len(s) > limit:
        s = s[:limit].rstrip("-")
    return s or fallback


def break_id(target: str, objective_slug: str, technique: str, prompt: str) -> str:
    canon = json.dumps(
        {
            "target": str(target or ""),
            "objective_slug": objective_slug,
            "technique": str(technique or ""),
            "prompt": str(prompt or ""),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha1(canon.encode("utf-8")).hexdigest()[:16]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _write_json(path: str, data) -> None:
    outdir = os.path.dirname(path)
    if outdir:
        os.makedirs(outdir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)


class BreakVault:
    """Curated, human-browsable store of prompts that actually broke a model.

    Layout under <root> (default cwd/library/breaks):

        library/breaks/
          <target-slug>/
            _index.json                 rollup for this target
            <objective-slug>/
              break-<id>.json           one confirmed break
          _catalog.json                 global upsert-by-id index

    Complements WinLibrary (which is a flat transfer-ranked replay store): the vault is
    the operator-facing filing cabinet, foldered by target then objective, and every row
    keeps the exact winning prompt so it can be re-fired or promoted into a seed. Saving
    is idempotent on break_id (same target+objective+technique+prompt) and only ever
    upgrades a row's label (PARTIAL -> COMPLIED), never downgrades it.
    """

    def __init__(self, cwd: str = ".", root: str | None = None):
        if root is None:
            root = os.path.join(os.path.abspath(cwd or "."), "library", "breaks")
        self.root = root

    @property
    def catalog_path(self) -> str:
        return os.path.join(self.root, "_catalog.json")

    def _target_dir(self, target_slug: str) -> str:
        return os.path.join(self.root, target_slug)

    def save(
        self,
        target: str,
        objective: str,
        prompt: str,
        response: str = "",
        label: str = "COMPLIED",
        reason: str = "",
        technique: str = "",
        attacker_model: str = "",
        transform_chain=None,
        messages=None,
        ts: str | None = None,
    ) -> dict:
        """Persist one break; returns the stored record. No-op-safe on repeated calls."""
        target = str(target or "unknown-target").strip() or "unknown-target"
        objective = str(objective or "").strip()
        target_slug = slugify(target, fallback="unknown-target")
        obj_slug = slugify(objective, fallback="unspecified")
        rid = break_id(target, obj_slug, technique, prompt)
        path = os.path.join(self._target_dir(target_slug), obj_slug, f"break-{rid}.json")

        resp = str(response or "")
        if len(resp) > _MAX_RESPONSE:
            resp = resp[:_MAX_RESPONSE] + f"\n...[truncated {len(resp) - _MAX_RESPONSE} chars]"

        existing = _read_json(path, None)
        now = ts or _now_iso()
        if isinstance(existing, dict):
            record = existing
            record["hits"] = int(record.get("hits", 1)) + 1
            record["last_seen"] = now
            if label_rank(label) > label_rank(record.get("label")):
                record["label"] = str(label or "").upper()
                record["reason"] = reason or record.get("reason", "")
                record["response"] = resp or record.get("response", "")
        else:
            record = {
                "id": rid,
                "target": target,
                "target_slug": target_slug,
                "objective": objective,
                "objective_slug": obj_slug,
                "technique": str(technique or ""),
                "label": str(label or "").upper(),
                "reason": reason or "",
                "prompt": str(prompt or ""),
                "response": resp,
                "attacker_model": str(attacker_model or ""),
                "transform_chain": list(transform_chain or []),
                "messages": messages or None,
                "first_seen": now,
                "last_seen": now,
                "hits": 1,
            }
        _write_json(path, record)
        self._reindex_target(target_slug)
        self._upsert_catalog(record, path)
        return record

    def _iter_target_breaks(self, target_slug: str):
        tdir = self._target_dir(target_slug)
        if not os.path.isdir(tdir):
            return
        for obj_slug in sorted(os.listdir(tdir)):
            odir = os.path.join(tdir, obj_slug)
            if not os.path.isdir(odir):
                continue
            for name in sorted(os.listdir(odir)):
                if not name.startswith("break-") or not name.endswith(".json"):
                    continue
                rec = _read_json(os.path.join(odir, name), None)
                if isinstance(rec, dict) and rec.get("id"):
                    yield rec

    def _reindex_target(self, target_slug: str) -> None:
        objectives: dict[str, dict] = {}
        target_name = target_slug
        count = 0
        for rec in self._iter_target_breaks(target_slug):
            count += 1
            target_name = rec.get("target") or target_name
            slot = objectives.setdefault(
                rec.get("objective_slug", "unspecified"),
                {"objective": rec.get("objective", ""), "count": 0,
                 "best_label": "REFUSED", "techniques": []},
            )
            slot["count"] += 1
            if label_rank(rec.get("label")) > label_rank(slot["best_label"]):
                slot["best_label"] = str(rec.get("label", "")).upper()
            tech = rec.get("technique", "")
            if tech and tech not in slot["techniques"]:
                slot["techniques"].append(tech)
        index = {
            "target": target_name,
            "target_slug": target_slug,
            "count": count,
            "objectives": objectives,
            "updated": _now_iso(),
        }
        _write_json(os.path.join(self._target_dir(target_slug), "_index.json"), index)

    def _upsert_catalog(self, record: dict, path: str) -> None:
        catalog = _read_json(self.catalog_path, [])
        if not isinstance(catalog, list):
            catalog = []
        rel = os.path.relpath(path, self.root)
        entry = {
            "id": record["id"],
            "target": record.get("target", ""),
            "objective": record.get("objective", ""),
            "technique": record.get("technique", ""),
            "label": record.get("label", ""),
            "attacker_model": record.get("attacker_model", ""),
            "path": rel,
            "last_seen": record.get("last_seen", ""),
        }
        catalog = [e for e in catalog if e.get("id") != record["id"]]
        catalog.append(entry)
        _write_json(self.catalog_path, catalog)

    def catalog(self) -> list[dict]:
        cat = _read_json(self.catalog_path, [])
        return cat if isinstance(cat, list) else []

    def targets(self) -> list[str]:
        if not os.path.isdir(self.root):
            return []
        return sorted(
            name for name in os.listdir(self.root)
            if os.path.isdir(os.path.join(self.root, name))
        )

    def load(self, rid: str) -> dict | None:
        for entry in self.catalog():
            if entry.get("id") == rid:
                return _read_json(os.path.join(self.root, entry.get("path", "")), None)
        return None

    def search(self, query: str = "", target: str = "", label: str = "") -> list[dict]:
        q = query.strip().lower()
        tgt = slugify(target) if target else ""
        lbl = label.strip().upper() if label else ""
        out = []
        for entry in self.catalog():
            if tgt and slugify(entry.get("target", "")) != tgt:
                continue
            if lbl and str(entry.get("label", "")).upper() != lbl:
                continue
            if q:
                hay = " ".join(str(entry.get(k, "")) for k in
                               ("target", "objective", "technique", "attacker_model")).lower()
                if q not in hay:
                    continue
            out.append(entry)
        return out
