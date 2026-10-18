"""可复现命令行入口；UI 与 CLI 使用完全相同的任务与日志。"""

import argparse
from dataclasses import asdict
import json
import time
from .config import load_credentials, DownloadConfig, ExperimentConfig, ModelProfile, profiles
from .storage import Store, dumps
from .jobs import Manager


def wait(store: Store, task: str) -> dict:
    previous = None
    while True:
        state = store.task(task)
        summary = dumps({"task": task, "status": state["status"], **state["payload"]})
        if summary != previous:
            print(summary, flush=True)
            previous = summary
        if state["status"] not in ("queued", "running"):
            if state["status"] != "succeeded":
                raise RuntimeError(state["payload"].get("error", state["status"]))
            return state["payload"]["result"]
        time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description="沪铜日频因子研究工作台")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    sub.add_parser("status")
    sub.add_parser("smoke")
    sub.add_parser("migrate-data", help="备份并迁移本地原始行情到 SQLite，不调用外部 API")
    sync = sub.add_parser("sync")
    sync.add_argument("--start", required=True)
    sync.add_argument("--end", required=True)
    sync.add_argument("--rpm", type=int, default=30)
    sync.add_argument("--repair", action="store_true")
    mine = sub.add_parser("mine")
    mine.add_argument("--config", required=True)
    resume = sub.add_parser("resume")
    resume.add_argument("task")
    final = sub.add_parser("final-test")
    final.add_argument("experiment")
    args = parser.parse_args()
    presence = load_credentials()
    store = Store()
    if args.command == "doctor":
        print(
            dumps(
                {
                    "credentials": presence,
                    "runtime": str(store.root),
                    "note": "仅检查加载状态，真实请求请通过同步/模型测试",
                }
            )
        )
        return
    if args.command == "status":
        print(dumps({"tasks": store.tasks(), "snapshots": store.list("snapshots")}))
        return
    manager = Manager(store)
    if args.command == "migrate-data":
        from alphagpt.data.sqlite import MarketData

        try:
            print(dumps(MarketData(store).migrate_legacy()), flush=True)
        finally:
            manager.close()
        return
    if args.command == "smoke":
        from .verification import smoke

        try:
            smoke(manager, store, wait)
        finally:
            manager.close()
        return
    if args.command == "sync":
        task = manager.submit(
            "sync", asdict(DownloadConfig(args.start, args.end, rpm=args.rpm, repair=args.repair))
        )
    elif args.command == "mine":
        with open(args.config, encoding="utf-8") as f:
            params = json.load(f)
        ExperimentConfig.from_dict(params).validate()
        task = manager.submit("mine", params)
    elif args.command == "resume":
        old = store.task(args.task)
        task = manager.submit(old["kind"], old["params"], resume=args.task)
    else:
        task = manager.submit("final_test", {"experiment": args.experiment})
    try:
        wait(store, task)
    finally:
        manager.close()


if __name__ == "__main__":
    main()
