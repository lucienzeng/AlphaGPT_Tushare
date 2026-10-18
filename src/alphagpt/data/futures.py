"""沪铜数据：按交易日覆盖增量同步，原始月合约与研究快照分开保存。"""

from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
import hashlib
import logging
import os
import threading
import time
import pandas as pd
import numpy as np
import requests
from tushare.pro.client import DataApi
from alphagpt.research.config import DownloadConfig
from alphagpt.research.storage import Store, digest_frame, dumps, now
from alphagpt.research.jobs import Context
from alphagpt.data.sqlite import MarketData, FIELDS

ROW_LIMITS = {
    "fut_basic": 10000,
    "fut_trade_cal": 10000,
    "fut_daily": 2000,
    "fut_mapping": 2000,
    "ft_limit": 4000,
    "fut_settle": 1600,
}
_LIMIT_LOCK = threading.Lock()
_LAST: dict[tuple, float] = {}


class PersistentDataApi(DataApi):
    """沿用官方 SDK 查询协议，复用 HTTPS 连接并显式检查 HTTP/业务错误。

    SDK 1.4.24 的静态 requests.post 不复用连接，且非2xx会被转为空表；
    这里仅替换传输，不轮换代理/IP，不改变账号权限或数据含义。
    """

    def __init__(self, token: str, timeout: int):
        super().__init__(token, timeout)
        self._credential, self._timeout = token, timeout
        self._session = requests.Session()

    def query(self, api_name, fields="", **kwargs):
        response = self._session.post(
            "https://api.tushare.pro",
            json={
                "api_name": api_name,
                "token": self._credential,
                "params": kwargs,
                "fields": fields,
            },
            timeout=self._timeout,
        )
        response.raise_for_status()
        result = response.json()
        if result.get("code") != 0:
            raise RuntimeError(f"Tushare 业务错误 {result.get('code')}: {result.get('msg')}")
        data = result.get("data")
        if not isinstance(data, dict) or "fields" not in data or "items" not in data:
            raise ValueError("响应缺少 fields/items，不能当作正常空数据")
        return pd.DataFrame(data["items"], columns=data["fields"])


class TushareSource:
    def __init__(self, config: DownloadConfig, ctx: Context, api=None):
        self.config, self.ctx = config, ctx
        self.calls = 0
        token = os.environ.get("TUSHARE_TOKEN", "")
        if api is None:
            if not token:
                raise ValueError("未加载 TUSHARE_TOKEN，请使用项目启动脚本")
            api = PersistentDataApi(token, config.timeout)
        self.api = api
        self.token_id = hashlib.sha256((token or "test").encode()).hexdigest()[:12]

    def request(self, endpoint: str, **params) -> pd.DataFrame:
        for attempt in range(self.config.retries + 1):
            self.ctx.check()
            endpoint_rpm = min(
                self.config.rpm, self.config.endpoint_rpm.get(endpoint, self.config.rpm)
            )
            if endpoint_rpm <= 0:
                raise ValueError("接口频率必须大于 0")
            # 同一 Token 的全局与接口时钟共享，重试也占配额；不会瞬间突发一批请求。
            with _LIMIT_LOCK:
                delay = max(
                    0,
                    _LAST.get((self.token_id, "all"), 0) + 60 / self.config.rpm - time.monotonic(),
                    _LAST.get((self.token_id, endpoint), 0) + 60 / endpoint_rpm - time.monotonic(),
                )
                if delay:
                    self.ctx.progress("限流等待", endpoint=endpoint, wait_seconds=round(delay, 2))
                    self.ctx.sleep(delay)
                _LAST[(self.token_id, "all")] = _LAST[(self.token_id, endpoint)] = time.monotonic()
            start = time.monotonic()
            self.calls += 1
            self.ctx.progress("下载中", endpoint=endpoint, request_count=self.calls, query=params)
            try:
                result = self.api.query(endpoint, **params)
                if result is None:
                    raise RuntimeError("远端返回 None，不能标记覆盖完成")
                self.ctx.log(
                    "api_response",
                    endpoint=endpoint,
                    params=params,
                    rows=len(result),
                    columns=list(result.columns),
                    elapsed_seconds=round(time.monotonic() - start, 3),
                    attempt=attempt + 1,
                )
                return result
            except Exception as e:
                text = str(e)
                self.ctx.log("api_error", endpoint=endpoint, error=text, attempt=attempt + 1)
                permanent = any(
                    x in text.lower()
                    for x in [
                        "token",
                        "权限",
                        "积分",
                        "参数",
                        "无效",
                        "invalid",
                        "unauthorized",
                        "ip数量",
                        "ip 数量",
                    ]
                )
                limited = any(x in text for x in ["每分钟", "每小时", "频次", "限流", "最多访问"])
                if (permanent and not limited) or attempt == self.config.retries:
                    raise RuntimeError(f"{endpoint} 请求失败：{text}") from e
                wait = (65 if limited else 2 ** (attempt + 1)) + np.random.default_rng().uniform(
                    0, 0.5
                )
                self.ctx.progress(
                    "限频冷却" if limited else "失败重试",
                    endpoint=endpoint,
                    wait_seconds=round(wait, 2),
                )
                self.ctx.sleep(wait)
        raise RuntimeError("请求重试结束")


def normalize(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    for col in ["trade_date", "cal_date", "list_date", "delist_date", "last_ddate"]:
        if col in frame:
            frame[col] = pd.to_datetime(frame[col], format="%Y%m%d", errors="coerce").dt.strftime(
                "%Y-%m-%d"
            )
    for col in [
        "open",
        "high",
        "low",
        "close",
        "settle",
        "pre_settle",
        "vol",
        "amount",
        "oi",
        "per_unit",
        "up_limit",
        "down_limit",
        "m_ratio",
        "trading_fee_rate",
        "trading_fee",
        "offset_today_fee",
    ]:
        if col in frame:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
    return frame


class FuturesData:
    def __init__(self, store: Store, source: TushareSource):
        self.store, self.source, self.ctx = store, source, source.ctx
        self.market = MarketData(store)
        self.market.migrate_legacy()
        self.skipped = 0

    def metadata(self) -> pd.DataFrame:
        cached = self.market.read("fut_basic", "CU")
        info = self.store.get("cache", "fut_basic")
        age = (
            (datetime.now(timezone.utc) - datetime.fromisoformat(info["updated"])).total_seconds()
            / 3600
            if info
            else float("inf")
        )
        if info and age < self.source.config.metadata_ttl_hours and not cached.empty:
            return cached
        frame = normalize(self.source.request("fut_basic", exchange="SHFE"))
        if "fut_code" not in frame:
            raise ValueError("合约信息缺少 fut_code")
        cu = frame[frame.fut_code.eq("CU")].copy()
        if cu.empty:
            raise ValueError("未找到沪铜合约，拒绝使用其他品种替代")
        self.market.write(
            "fut_basic",
            "CU",
            cu,
            task=self.ctx.id,
            replace=True,
            cache_info={"updated": now(), "rows": len(cu)},
        )
        return cu

    def _settlement_gaps(self, symbol, days):
        self.market.record_gaps("fut_settle", symbol, days, self.ctx.id)
        message = (f"结算参数缺失：{symbol} {min(days)}～{max(days)}，{len(days)}个交易日；"
                   "已记入 data_gaps，继续同步；未填0、未标记覆盖。历史手续费回测仍严格检查。")
        self.ctx.log("settlement_gap_warning", level="warning", symbol=symbol,
                     endpoint="fut_settle", dates=sorted(days), message=message)
        logging.getLogger(__name__).warning("[%s] %s", self.ctx.id, message)

    def fetch_range(self, endpoint: str, symbol: str, days: list[str], **extra) -> pd.DataFrame:
        old = self.market.read(endpoint, symbol)
        if endpoint == "fut_settle" and old.empty:
            old = old.reindex(columns=list(FIELDS["settlement_params"]))
        date_col = "cal_date" if endpoint == "fut_trade_cal" else "trade_date"
        # 覆盖清单还须对应实际行，外部误删或旧清单悬空时仍能补回。
        covered = self.store.covered(endpoint, symbol) & (
            set(old[date_col]) if date_col in old else set()
        )
        cfg = self.source.config
        repair_key = f"{self.ctx.id}/{endpoint}/{symbol}"
        repaired = set((self.store.get("repair_coverage", repair_key) or {}).get("days", []))
        # 修复任务也记录自己的完成边界，停止恢复后不能重拉已完成修复分段。
        effective_coverage = repaired if cfg.repair else covered
        missing = sorted(set(days) - effective_coverage)
        tail_key = f"{endpoint}/{symbol}"
        tail_info = self.store.get("tail_checks", tail_key)
        tail_due = (
            not tail_info
            or (
                datetime.now(timezone.utc) - datetime.fromisoformat(tail_info["updated"])
            ).total_seconds()
            >= cfg.tail_check_hours * 3600
        )
        if cfg.tail_days and tail_due and days:
            # 只有用户启用且冷却期结束时重查尾部；普通完整历史默认仍为零请求。
            missing = sorted(set(missing) | set(days[-cfg.tail_days :]))
        self.skipped += len(set(days) & covered) if not self.source.config.repair else 0
        self.ctx.log(
            "coverage_plan",
            endpoint=endpoint,
            symbol=symbol,
            required=len(days),
            missing=len(missing),
            cached=len(set(days) & covered),
        )
        # 连续缺口单独分段，不能为了补一天重新拉整个历史区间。
        groups: list[list[str]] = []
        expected_index = {day: i for i, day in enumerate(days)}
        for day in missing:
            chunk_days = 365 if endpoint == "fut_trade_cal" else 120
            if (
                not groups
                or len(groups[-1]) >= chunk_days
                or expected_index[day] != expected_index[groups[-1][-1]] + 1
            ):
                groups.append([])
            groups[-1].append(day)
        for group in groups:
            self.ctx.check()
            chunk = self._bounded(endpoint, group, extra)
            date_col = "cal_date" if endpoint == "fut_trade_cal" else "trade_date"
            if chunk.empty:
                self.ctx.log(
                    "empty_unconfirmed",
                    endpoint=endpoint,
                    symbol=symbol,
                    start=group[0],
                    end=group[-1],
                )
                if endpoint == "fut_settle":
                    self._settlement_gaps(symbol, group)
                    continue
                raise ValueError(
                    f"{endpoint} {symbol} 返回空数据，未标记覆盖；请核实权限、发布时间或选择修复"
                )
            if date_col not in chunk:
                raise ValueError(f"{endpoint} 缺少 {date_col}")
            actual = set(chunk[date_col].dropna())
            missing_actual = set(group) - actual
            if missing_actual:
                if endpoint == "fut_settle":
                    self._settlement_gaps(symbol, missing_actual)
                self.ctx.log(
                    "missing_rows", endpoint=endpoint, symbol=symbol, dates=sorted(missing_actual)
                )
            keys = [date_col] + (["ts_code"] if "ts_code" in chunk else [])
            merged = (
                pd.concat([old, chunk], ignore_index=True)
                .drop_duplicates(keys, keep="last")
                .sort_values(keys)
                .reset_index(drop=True)
            )
            if cfg.repair:
                repaired.update(actual & set(group))
            self.market.write(
                endpoint,
                symbol,
                chunk.reindex(columns=merged.columns),
                schema_frame=merged,
                covered_days=sorted(actual & set(group)),
                task=self.ctx.id,
                repair=(repair_key, repaired) if cfg.repair else None,
            )
            old = merged
            self.ctx.progress(
                "分段保存",
                endpoint=endpoint,
                symbol=symbol,
                rows=len(old),
                skipped_days=self.skipped,
            )
        if cfg.tail_days and tail_due:
            self.store.put("tail_checks", tail_key, {"updated": now()})
        return old

    def _bounded(self, endpoint: str, days: list[str], extra: dict) -> pd.DataFrame:
        frame = self.source.request(
            endpoint,
            start_date=days[0].replace("-", ""),
            end_date=days[-1].replace("-", ""),
            **extra,
        )
        cap = min(
            ROW_LIMITS[endpoint], self.source.config.row_limits.get(endpoint, ROW_LIMITS[endpoint])
        )
        if len(frame) >= cap:
            self.ctx.log("row_limit_split", endpoint=endpoint, returned=len(frame), days=len(days))
            if len(days) == 1:
                raise ValueError(f"{endpoint} 单日已达行数上限，请缩小合约范围，拒绝静默截断")
            mid = len(days) // 2
            return pd.concat(
                [
                    self._bounded(endpoint, days[:mid], extra),
                    self._bounded(endpoint, days[mid:], extra),
                ],
                ignore_index=True,
            )
        return normalize(frame)

    def sync(self) -> dict:
        cfg = self.source.config
        cfg.validate()
        start = (date.fromisoformat(cfg.start) - timedelta(days=cfg.warmup_days)).isoformat()
        all_days = pd.date_range(start, cfg.end).strftime("%Y-%m-%d").tolist()
        self.ctx.log(
            "sync_config",
            config=asdict(cfg),
            effective_start=start,
            semantics="已完成交易日；默认并发1；未知账号额度使用30次/分研发默认，以官方更严格规则为准",
        )
        basic = self.metadata()
        calendar = self.fetch_range("fut_trade_cal", "SHFE", all_days, exchange="SHFE")
        days = (
            calendar.loc[
                calendar.is_open.eq(1) & calendar.cal_date.between(start, cfg.end), "cal_date"
            ]
            .sort_values()
            .tolist()
        )
        if len(days) < 80:
            raise ValueError("下载区间含预热需至少 80 个交易日")
        mapping = self.fetch_range("fut_mapping", "CU.SHF", days, ts_code="CU.SHF")
        mapping = mapping[mapping.trade_date.between(start, cfg.end)].sort_values("trade_date")
        if set(days) - set(mapping.trade_date):
            raise ValueError("主力映射存在缺口；不能前向填充后伪装完整")
        if not set(mapping.mapping_ts_code).issubset(set(basic.ts_code)):
            raise ValueError("主力映射包含未知真实合约")
        contracts = basic[basic.ts_code.isin(mapping.mapping_ts_code.unique())].copy()
        data: dict[str, list[pd.DataFrame]] = {
            k: [] for k in ["fut_daily", "ft_limit", "fut_settle"]
        }
        for index, row in enumerate(contracts.itertuples(), 1):
            eligible = [d for d in days if str(row.list_date) <= d <= str(row.delist_date)]
            for endpoint in data:
                frame = self.fetch_range(endpoint, row.ts_code, eligible, ts_code=row.ts_code)
                data[endpoint].append(
                    frame[frame.trade_date.isin(eligible) & frame.ts_code.eq(row.ts_code)]
                )
            self.ctx.progress("合约同步", completed=index, total=len(contracts), symbol=row.ts_code)
        bars = (
            pd.concat(data["fut_daily"], ignore_index=True)
            .drop_duplicates(["ts_code", "trade_date"])
            .sort_values(["trade_date", "ts_code"])
            .reset_index(drop=True)
        )
        limits = pd.concat(data["ft_limit"], ignore_index=True).drop_duplicates(
            ["ts_code", "trade_date"]
        )
        fees = pd.concat(data["fut_settle"], ignore_index=True).drop_duplicates(
            ["ts_code", "trade_date"]
        )
        quality = validate_bars(bars)
        missing_fees = bars[["ts_code", "trade_date"]].merge(
            fees[["ts_code", "trade_date"]], how="left", on=["ts_code", "trade_date"], indicator=True
        )
        quality["settlement_missing_rows"] = int(missing_fees._merge.eq("left_only").sum())
        quality["settlement_policy"] = "缺失保留并继续；固定成本可回测，历史手续费按实际成交日严格检查"
        # 快照复制实际内容并用内容哈希命名，原始缓存修复不会改写旧实验。
        frames = {
            "bars": bars,
            "mapping": mapping.reset_index(drop=True),
            "contracts": contracts.sort_values("ts_code").reset_index(drop=True),
            "limits": limits.sort_values(["trade_date", "ts_code"]).reset_index(drop=True),
            "fees": fees.sort_values(["trade_date", "ts_code"]).reset_index(drop=True),
        }
        h = hashlib.sha256()
        for name, frame in frames.items():
            h.update(name.encode() + digest_frame(frame))
        h.update(dumps({"start": cfg.start, "end": cfg.end, "version": 1}).encode())
        snapshot = "cu_" + h.hexdigest()[:20]
        if not self.store.get("snapshots", snapshot):
            paths = {
                name: self.store.frame(f"snapshots/{snapshot}/{name}.parquet", frame)
                for name, frame in frames.items()
            }
            self.store.put(
                "snapshots",
                snapshot,
                {
                    "start": cfg.start,
                    "end": cfg.end,
                    "warmup_start": start,
                    "paths": paths,
                    "quality": quality,
                    "created": now(),
                    "source": "Tushare Pro 真实数据",
                    "rows": len(bars),
                    "contracts": len(contracts),
                    "download_task": self.ctx.id,
                },
            )
        result = {
            "snapshot": snapshot,
            "requests": self.source.calls,
            "skipped_days": self.skipped,
            "rows": len(bars),
            "quality": quality,
        }
        self.ctx.log("snapshot_ready", **result)
        return result


def validate_bars(frame: pd.DataFrame) -> dict:
    required = ["ts_code", "trade_date", "open", "high", "low", "close", "settle", "vol", "oi"]
    if any(x not in frame for x in required) or frame.empty:
        raise ValueError("行情为空或缺少必要字段")
    bad = (
        frame[["open", "high", "low", "close", "settle"]].isna().any(axis=1)
        | frame[["open", "high", "low", "close", "settle"]].le(0).any(axis=1)
        | frame.high.lt(frame.low)
        | frame.open.gt(frame.high)
        | frame.open.lt(frame.low)
        | frame.close.gt(frame.high)
        | frame.close.lt(frame.low)
        | frame.vol.lt(0)
        | frame.oi.lt(0)
    )
    if bad.any():
        raise ValueError(
            f"行情有 {bad.sum()} 行关键异常，示例：{frame.loc[bad, ['ts_code','trade_date']].head().to_dict('records')}"
        )
    return {
        "rows": len(frame),
        "invalid": 0,
        "duplicates": int(frame.duplicated(["ts_code", "trade_date"]).sum()),
        "units": "价格元/吨，成交及持仓手，成交额万元；保留供应商原始字段，跨2020特征另行处理",
    }


def load_snapshot(store: Store, key: str) -> dict[str, pd.DataFrame]:
    meta = store.get("snapshots", key)
    if not meta:
        raise ValueError("数据快照不存在，请先同步")
    return {name: store.read(path) for name, path in meta["paths"].items()}
