import sqlite3
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import sqlite

from app.api.routes import catalog


class SQLiteSession:
    def __init__(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.execute("CREATE TABLE image_tasks (id INTEGER PRIMARY KEY, status TEXT, failure_message TEXT, finished_at TEXT, worker_started_at TEXT, worker_heartbeat_at TEXT, deadline_at TEXT, timeout_seconds INTEGER)")

    def run(self, statement):
        compiled = statement.compile(dialect=sqlite.dialect(), compile_kwargs={"render_postcompile": True})
        values = [compiled.params[name] for name in compiled.positiontup]
        values = [value.isoformat() if hasattr(value, "isoformat") else value for value in values]
        return self.connection.execute(str(compiled), values)

    async def scalar(self, statement):
        return self.run(statement).fetchone()[0]

    async def execute(self, statement):
        row = self.run(statement).fetchone()
        return SimpleNamespace(first=lambda: row)

    async def commit(self):
        self.connection.commit()


@pytest.mark.asyncio
async def test_retry_preserves_original_start_and_deadline():
    db = SQLiteSession()
    db.connection.execute("INSERT INTO image_tasks(id,status,timeout_seconds) VALUES(1,'queued',120)")
    assert await catalog.mark_image_task_status(db, 1, "running", expected_statuses=("queued",))
    first = db.connection.execute("SELECT worker_started_at,deadline_at FROM image_tasks WHERE id=1").fetchone()
    assert first[0] is not None and first[1] is not None
    assert await catalog.mark_image_task_status(db, 1, "running", "retry", expected_statuses=("running",))
    second = db.connection.execute("SELECT worker_started_at,deadline_at FROM image_tasks WHERE id=1").fetchone()
    assert second == first
    db.connection.close()
