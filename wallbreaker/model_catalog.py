from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

CATALOG_FILENAME = ".wallbreaker_models.sqlite3"
_SOURCES = {"configured", "remote", "manual", "inference"}


def catalog_path_for(config) -> Path:
    base = config.path.parent if getattr(config, "path", None) else Path.cwd()
    return base / CATALOG_FILENAME


class ModelCatalog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS models (
                    provider_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    available INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (provider_id, model_id)
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS catalog_refreshes (
                    provider_id TEXT PRIMARY KEY,
                    refreshed_at TEXT NOT NULL
                )
            """)

    def upsert(self, provider_id: str, model_id: str, source: str = "manual") -> None:
        provider_id = str(provider_id or "").strip()
        model_id = str(model_id or "").strip()
        if not provider_id or not model_id:
            return
        if source not in _SOURCES:
            source = "manual"
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self._connect() as db:
            db.execute("""
                INSERT INTO models(provider_id, model_id, source, first_seen, last_seen, available)
                VALUES (?, ?, ?, ?, ?, 1)
                ON CONFLICT(provider_id, model_id) DO UPDATE SET
                    source = CASE
                        WHEN models.source = 'configured' THEN models.source
                        WHEN excluded.source = 'inference' THEN excluded.source
                        ELSE models.source
                    END,
                    last_seen = excluded.last_seen,
                    available = 1
            """, (provider_id, model_id, source, now, now))

    def sync(self, provider_id: str, model_ids: list[str], source: str = "remote") -> None:
        for model_id in model_ids:
            self.upsert(provider_id, model_id, source)

    def list(self, provider_id: str) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT provider_id, model_id, source, first_seen, last_seen, available "
                "FROM models WHERE provider_id = ? ORDER BY model_id COLLATE NOCASE",
                (provider_id,),
            ).fetchall()
        return [dict(row) | {"available": bool(row["available"])} for row in rows]

    def mark_refreshed(self, provider_id: str) -> str:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self._connect() as db:
            db.execute("""
                INSERT INTO catalog_refreshes(provider_id, refreshed_at) VALUES (?, ?)
                ON CONFLICT(provider_id) DO UPDATE SET refreshed_at = excluded.refreshed_at
            """, (provider_id, now))
        return now

    def last_refreshed(self, provider_id: str) -> str:
        with self._connect() as db:
            row = db.execute(
                "SELECT refreshed_at FROM catalog_refreshes WHERE provider_id = ?", (provider_id,),
            ).fetchone()
        return str(row["refreshed_at"]) if row else ""


def attach_catalog(endpoint, path: str | Path, provider_id: str | None = None) -> None:
    if endpoint is None:
        return
    endpoint._catalog_path = str(path)
    endpoint._provider_id = provider_id or getattr(endpoint, "name", "")


def record_model_success(endpoint) -> None:
    path = getattr(endpoint, "_catalog_path", "")
    provider_id = getattr(endpoint, "_provider_id", "") or getattr(endpoint, "name", "")
    model_id = getattr(endpoint, "model", "")
    if not path or not provider_id or not model_id:
        return
    try:
        ModelCatalog(path).upsert(provider_id, model_id, "inference")
    except (OSError, sqlite3.Error):
        pass
