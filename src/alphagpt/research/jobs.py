"""单执行器防止重复任务；后台只写持久化状态，不调用 Streamlit。"""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import threading
import time
import traceback
import fcntl
from .storage import Store, dumps, identifier, now


class Cancelled(Exception):
    pass


class Context:
    def __init__(self, store: Store, task_id: str):
        self.store, self.id = store, task_id

    def check(self):
        if self.store.task(self.id)["cancel"]:
            raise Cancelled("用户已停止；已完成分段和因子保留，可从边界恢复")

    def log(self, event: str, **data):
        self.store.event(self.id, event, **data)

    def progress(self, stage: str, **data):
        self.store.update_task(self.id, stage=stage, **data)
        self.log("progress", stage=stage, **data)

    def sleep(self, seconds: float):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.check()
            time.sleep(min(0.25, max(0, deadline - time.monotonic())))


class Manager:
    def __init__(self, store: Store):
        self.store = store
        self.owner_file = (store.root / "worker.lock").open("a+")
        try:
            # 一个 runtime 仅允许一个执行器；避免 CLI 与 UI 各自发请求突破共享预算。
            fcntl.flock(self.owner_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            self.owner_file.close()
            raise RuntimeError(
                "该运行目录已有研究执行器，请使用现有界面或先关闭它再运行 CLI"
            ) from e
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cu-worker")
        self.lock = threading.Lock()
        with store.connect() as db:
            db.execute(
                "UPDATE tasks SET status='interrupted',updated=? WHERE status IN ('running','queued')",
                (now(),),
            )

    def submit(self, kind: str, params: dict, resume: str | None = None) -> str:
        fingerprint = hashlib.sha256((kind + dumps(params)).encode()).hexdigest()
        with self.lock:
            with self.store.connect() as db:
                active = db.execute(
                    "SELECT id FROM tasks WHERE fingerprint=? AND status IN ('queued','running')",
                    (fingerprint,),
                ).fetchone()
                if active:
                    return active[0]
                key = resume or identifier(kind)
                if resume:
                    old = self.store.task(resume)
                    if (
                        old["kind"] != kind
                        or old["params"] != params
                        or old["status"] in ("queued", "running", "succeeded")
                    ):
                        raise ValueError("只能恢复参数一致的失败、停止或中断任务")
                    db.execute(
                        "UPDATE tasks SET status='queued',cancel=0,updated=? WHERE id=?",
                        (now(), key),
                    )
                else:
                    db.execute(
                        "INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,0)",
                        (key, kind, "queued", now(), now(), fingerprint, dumps(params), "{}"),
                    )
            self.store.event(key, "task_submitted", kind=kind, params=params, resumed=bool(resume))
            self.executor.submit(self._run, key)
        return key

    def _run(self, key: str):
        from .workflow import execute

        ctx = Context(self.store, key)
        try:
            ctx.check()
            self.store.update_task(key, "running", stage="任务开始")
            task = self.store.task(key)
            result = execute(task["kind"], task["params"], ctx)
            self.store.update_task(key, "succeeded", stage="完成", result=result)
            ctx.log("task_succeeded", result=result)
        except Cancelled as e:
            self.store.update_task(key, "stopped", stage=str(e))
            ctx.log("task_stopped", message=str(e))
        except Exception as e:
            self.store.update_task(key, "failed", stage="执行失败", error=str(e))
            ctx.log("task_failed", error=str(e), traceback=traceback.format_exc())

    def stop(self, key: str):
        with self.store.connect() as db:
            db.execute("UPDATE tasks SET cancel=1 WHERE id=?", (key,))
        self.store.event(key, "stop_requested")

    def close(self):
        self.executor.shutdown(wait=True)
        fcntl.flock(self.owner_file.fileno(), fcntl.LOCK_UN)
        self.owner_file.close()
