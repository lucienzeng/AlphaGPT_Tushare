"""SQLite 业务/任务数据；Parquet 保存冻结快照/实验，JSONL 保存完整事件日志。"""

from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import sqlite3
import threading
import uuid
import numpy as np
import pandas as pd
from .config import ROOT, SECRET_NAMES


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean(value):
    if isinstance(value, dict):
        return {
            str(k): clean(v)
            for k, v in value.items()
            if str(k).lower() not in {"api_key", "token", "authorization"}
        }
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (np.integer, np.floating)):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime, Path)):
        return str(value)
    if isinstance(value, str):
        for name in SECRET_NAMES:
            secret = os.environ.get(name)
            if secret and len(secret) > 6:
                value = value.replace(secret, "[REDACTED]")
    return value


def dumps(value) -> str:
    return json.dumps(clean(value), ensure_ascii=False, sort_keys=True, allow_nan=False)


def identifier(prefix: str) -> str:
    return prefix + "_" + datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]


class Store:
    def __init__(self, root: Path | str | None = None):
        self.root = Path(root or os.getenv("ALPHAGPT_RUNTIME", str(ROOT / "runtime"))).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS objects(kind TEXT,id TEXT,created TEXT,payload TEXT,PRIMARY KEY(kind,id));
            CREATE TABLE IF NOT EXISTS coverage(dataset TEXT,symbol TEXT,day TEXT,version TEXT,PRIMARY KEY(dataset,symbol,day));
            CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,kind TEXT,status TEXT,created TEXT,updated TEXT,
                fingerprint TEXT,params TEXT,payload TEXT,cancel INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,task TEXT,time TEXT,event TEXT,payload TEXT);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / "research.sqlite", timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA journal_mode=WAL")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def put(self, kind: str, key: str, payload: dict) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO objects VALUES(?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload",
                (kind, key, now(), dumps(payload)),
            )

    def get(self, kind: str, key: str) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT payload FROM objects WHERE kind=? AND id=?", (kind, key)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, kind: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT id,payload FROM objects WHERE kind=? ORDER BY created DESC", (kind,)
            ).fetchall()
        return [{"id": row["id"], **json.loads(row["payload"])} for row in rows]

    def frame(self, relative: str, frame: pd.DataFrame) -> str:
        if Path(relative).parts[0] == "cache":
            raise ValueError("原始数据已迁入 SQLite，请通过 MarketData.write 写入，避免双份缓存")
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock:
            temp = path.with_name(path.name + ".tmp")
            frame.to_parquet(temp, index=False)
            temp.replace(path)
        return relative

    def read(self, relative: str) -> pd.DataFrame:
        # 兼容旧脚本的缓存逻辑路径，始终从新主库读取，不能退回过期 Parquet。
        parts = Path(relative).parts
        if len(parts) == 3 and parts[0] == "cache" and parts[2].endswith(".parquet"):
            from alphagpt.data.sqlite import MarketData

            market = MarketData(self)
            return market.read(parts[1], parts[2][:-8])
        path = self.root / relative
        return pd.read_parquet(path) if path.exists() else pd.DataFrame()

    def event(self, task_id: str, event: str, **payload) -> None:
        record = {"time": now(), "task_id": task_id, "event": event, **clean(payload)}
        with self.lock:
            with self.connect() as db:
                db.execute(
                    "INSERT INTO events(task,time,event,payload) VALUES(?,?,?,?)",
                    (task_id, record["time"], event, dumps(payload)),
                )
            directory = self.root / "logs"
            directory.mkdir(exist_ok=True)
            with (directory / (task_id + ".jsonl")).open("a", encoding="utf-8") as f:
                f.write(dumps(record) + "\n")

    def events(self, task: str, limit: int = 200) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT time,event,payload FROM events WHERE task=? ORDER BY seq DESC LIMIT ?",
                (task, limit),
            ).fetchall()
        return [
            {"time": r["time"], "event": r["event"], **json.loads(r["payload"])}
            for r in reversed(rows)
        ]

    def task(self, key: str) -> dict:
        with self.connect() as db:
            row = dict(db.execute("SELECT * FROM tasks WHERE id=?", (key,)).fetchone())
        row["params"], row["payload"] = json.loads(row["params"]), json.loads(row["payload"])
        return row

    def tasks(self) -> list[dict]:
        with self.connect() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM tasks ORDER BY created DESC")]
        return [self.task(key) for key in ids]

    def update_task(self, key: str, status: str | None = None, **payload):
        with self.lock:
            current = self.task(key)
            if status in ("queued", "running", "succeeded"):
                current["payload"].pop("error", None)
            if "stage" in payload and payload["stage"] != current["payload"].get("stage"):
                for field in ("completed", "total", "wait_seconds"):
                    if field not in payload:
                        current["payload"].pop(field, None)
            current["payload"].update(payload)
            with self.connect() as db:
                db.execute(
                    "UPDATE tasks SET status=?,payload=?,updated=? WHERE id=?",
                    (status or current["status"], dumps(current["payload"]), now(), key),
                )

    def covered(self, dataset: str, symbol: str) -> set[str]:
        with self.connect() as db:
            return {
                r[0]
                for r in db.execute(
                    "SELECT day FROM coverage WHERE dataset=? AND symbol=?", (dataset, symbol)
                )
            }

    def cover(self, dataset: str, symbol: str, days: list[str]):
        with self.connect() as db:
            db.executemany(
                "INSERT OR REPLACE INTO coverage VALUES(?,?,?,?)",
                [(dataset, symbol, day, "raw-v1") for day in days],
            )


def digest_frame(df: pd.DataFrame) -> bytes:
    return (
        pd.util.hash_pandas_object(df, index=False).values.tobytes()
        + dumps(list(df.columns)).encode()
    )
