"""六类期货原始数据统一存 SQLite；Parquet 只用于冻结快照与实验。

表名及主键固定，供应商新增字段作为普通列保留。catalog 记录原始列顺序/类型，
确保 SQL 往返不会改变现有 DataFrame 的计算口径与快照内容哈希。
"""

from pathlib import Path
import hashlib
import json
import re
import shutil
import sqlite3
import pandas as pd
from alphagpt.research.storage import Store, dumps, now, identifier, digest_frame

# endpoint -> 业务表、主键、日期列。月份行情与主连映射始终分表。
TABLES = {
    "fut_basic": ("contracts", ("ts_code",), None),
    "fut_trade_cal": ("trade_calendar", ("exchange", "cal_date"), "cal_date"),
    "fut_daily": ("daily_bars", ("ts_code", "trade_date"), "trade_date"),
    "fut_mapping": ("main_mapping", ("ts_code", "trade_date"), "trade_date"),
    "ft_limit": ("price_limits", ("ts_code", "trade_date"), "trade_date"),
    "fut_settle": ("settlement_params", ("ts_code", "trade_date"), "trade_date"),
}
FIELDS = {
    "contracts": {
        **dict.fromkeys(
            "ts_code symbol exchange name fut_code trade_unit quote_unit quote_unit_desc d_mode_desc list_date delist_date d_month last_ddate trade_time_desc".split(),
            "TEXT",
        ),
        "multiplier": "REAL",
        "per_unit": "REAL",
    },
    "trade_calendar": {
        "exchange": "TEXT",
        "cal_date": "TEXT",
        "is_open": "INTEGER",
        "pretrade_date": "TEXT",
    },
    "daily_bars": {
        "ts_code": "TEXT",
        "trade_date": "TEXT",
        **dict.fromkeys(
            "pre_close pre_settle open high low close settle change1 change2 vol amount oi oi_chg delv_settle".split(),
            "REAL",
        ),
    },
    "main_mapping": {"ts_code": "TEXT", "trade_date": "TEXT", "mapping_ts_code": "TEXT"},
    "price_limits": {
        "ts_code": "TEXT",
        "trade_date": "TEXT",
        "name": "TEXT",
        "up_limit": "REAL",
        "down_limit": "REAL",
        "m_ratio": "REAL",
        "cont": "TEXT",
        "exchange": "TEXT",
    },
    "settlement_params": {
        "ts_code": "TEXT",
        "trade_date": "TEXT",
        "exchange": "TEXT",
        **dict.fromkeys(
            "settle trading_fee_rate trading_fee delivery_fee b_hedging_margin_rate s_hedging_margin_rate long_margin_rate short_margin_rate offset_today_fee".split(),
            "REAL",
        ),
    },
}
LABELS = {
    "fut_basic": "合约信息",
    "fut_trade_cal": "交易日历",
    "fut_daily": "月份合约日线",
    "fut_mapping": "主连映射",
    "ft_limit": "涨跌停与保证金",
    "fut_settle": "结算参数",
}
MIGRATION = "parquet_cache_to_sqlite_v1"


def quoted(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
        raise ValueError(f"供应商列名不符合约定：{name}")
    return '"' + name + '"'


def put_object(db, kind: str, key: str, payload: dict) -> None:
    db.execute(
        "INSERT INTO objects VALUES(?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload",
        (kind, key, now(), dumps(payload)),
    )


class MarketData:
    def __init__(self, store: Store):
        self.store = store
        with store.lock, store.connect() as db:
            for table, keys, day in TABLES.values():
                columns = [
                    f"{quoted(k)} {typ}" + (" NOT NULL" if k in keys else "")
                    for k, typ in FIELDS[table].items()
                ]
                columns += [
                    "_scope TEXT NOT NULL",
                    "_updated_at TEXT NOT NULL",
                    "_source_task TEXT",
                    "PRIMARY KEY (" + ",".join(quoted(k) for k in keys) + ")",
                ]
                db.execute(f"CREATE TABLE IF NOT EXISTS {table} (" + ",".join(columns) + ")")
                db.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_scope ON {table}(_scope)")
                if day:
                    db.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_date ON {table}({day})")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS data_gaps(
                    dataset TEXT NOT NULL, symbol TEXT NOT NULL, day TEXT NOT NULL,
                    reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
                    first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 1, source_task TEXT,
                    resolved_at TEXT, PRIMARY KEY(dataset,symbol,day));
                CREATE VIEW IF NOT EXISTS "期货_下载缺口记录" AS
                    SELECT dataset AS 数据接口,symbol AS 合约代码,day AS 缺失日期,
                    reason AS 原因,status AS 状态,attempts AS 检查次数,
                    first_seen AS 首次发现,last_seen AS 最近发现,
                    source_task AS 最近任务,resolved_at AS 补齐时间 FROM data_gaps;
                CREATE TABLE IF NOT EXISTS market_catalog(
                    dataset TEXT NOT NULL, symbol TEXT NOT NULL, schema_json TEXT NOT NULL,
                    row_count INTEGER NOT NULL, updated_at TEXT NOT NULL, source_task TEXT,
                    PRIMARY KEY(dataset,symbol));
                CREATE TABLE IF NOT EXISTS market_migrations(
                    name TEXT PRIMARY KEY, completed_at TEXT NOT NULL, report_json TEXT NOT NULL);
                CREATE VIEW IF NOT EXISTS "期货_合约信息" AS
                    SELECT ts_code AS 合约代码,name AS 合约名称,fut_code AS 品种,exchange AS 交易所,
                    per_unit AS 每手数量,trade_unit AS 交易单位,list_date AS 上市日期,
                    delist_date AS 最后交易日,last_ddate AS 最后交割日,_updated_at AS 本地入库时间
                    FROM contracts;
                CREATE VIEW IF NOT EXISTS "期货_交易日历" AS
                    SELECT exchange AS 交易所,cal_date AS 日历日期,
                    is_open AS 是否交易日,pretrade_date AS 前交易日 FROM trade_calendar;
                CREATE VIEW IF NOT EXISTS "期货_同步清单" AS
                    SELECT dataset AS 数据接口,symbol AS 合约或交易所,
                    day AS 已覆盖日期,version AS 数据口径版本 FROM coverage;
                CREATE VIEW IF NOT EXISTS "沪铜_月份合约行情" AS
                    SELECT b.ts_code AS 合约代码,c.name AS 合约名称,b.trade_date AS 交易日,
                    b.open AS 开盘价,b.high AS 最高价,b.low AS 最低价,b.close AS 收盘价,
                    b.settle AS 结算价,b.vol AS 成交量_手,b.oi AS 持仓量_手,b.amount AS 成交额_万元,
                    c.per_unit AS 每手吨数,c.delist_date AS 最后交易日,b._updated_at AS 本地入库时间
                    FROM daily_bars b LEFT JOIN contracts c ON b.ts_code=c.ts_code;
                CREATE VIEW IF NOT EXISTS "沪铜_主力映射" AS
                    SELECT ts_code AS 主连代码,trade_date AS 交易日,mapping_ts_code AS 实际月份合约,
                    _updated_at AS 本地入库时间 FROM main_mapping;
                CREATE VIEW IF NOT EXISTS "沪铜_主连未复权行情" AS
                    SELECT m.ts_code AS 主连代码,m.trade_date AS 交易日,m.mapping_ts_code AS 实际月份合约,
                    b.open AS 开盘价,b.close AS 收盘价,b.settle AS 结算价,b.vol AS 成交量_手,
                    '原始主力拼接，未复权；不用于直接计算换月收益' AS 价格口径,
                    CASE WHEN b.ts_code IS NULL THEN '缺少月份行情' ELSE '已匹配' END AS 匹配状态
                    FROM main_mapping m LEFT JOIN daily_bars b
                    ON b.ts_code=m.mapping_ts_code AND b.trade_date=m.trade_date;
                CREATE VIEW IF NOT EXISTS "期货_涨跌停与保证金" AS
                    SELECT ts_code AS 合约代码,trade_date AS 交易日,up_limit AS 涨停价,
                    down_limit AS 跌停价,m_ratio AS 最低保证金率_百分数 FROM price_limits;
                CREATE VIEW IF NOT EXISTS "期货_结算参数" AS
                    SELECT ts_code AS 合约代码,trade_date AS 交易日,settle AS 结算价,
                    trading_fee_rate AS 交易手续费率,trading_fee AS 交易手续费,
                    offset_today_fee AS 平今仓手续费参数,long_margin_rate AS 买投机保证金参数,
                    short_margin_rate AS 卖投机保证金参数 FROM settlement_params;
                CREATE VIEW IF NOT EXISTS "期货_数据缺口" AS
                    SELECT 'fut_daily' AS 数据接口,m.mapping_ts_code AS 合约代码,
                    m.trade_date AS 交易日,'主力映射缺少对应月份日线' AS 原因
                    FROM main_mapping m LEFT JOIN daily_bars b
                    ON b.ts_code=m.mapping_ts_code AND b.trade_date=m.trade_date
                    WHERE b.ts_code IS NULL
                    UNION ALL
                    SELECT 'ft_limit',b.ts_code,b.trade_date,'月份日线缺少涨跌停参数'
                    FROM daily_bars b LEFT JOIN price_limits p
                    ON p.ts_code=b.ts_code AND p.trade_date=b.trade_date WHERE p.ts_code IS NULL
                    UNION ALL
                    SELECT 'fut_settle',b.ts_code,b.trade_date,'月份日线缺少结算参数'
                    FROM daily_bars b LEFT JOIN settlement_params p
                    ON p.ts_code=b.ts_code AND p.trade_date=b.trade_date WHERE p.ts_code IS NULL;
            """)
            parts = []
            for endpoint, (table, keys, day) in TABLES.items():
                date_sql = f"min({day}),max({day})" if day else "NULL,NULL"
                parts.append(
                    f"SELECT '{endpoint}' AS 数据接口,'{LABELS[endpoint]}' AS 数据类别,_scope AS 合约或交易所,count(*) AS 行数,{date_sql},max(_updated_at) AS 最后入库时间 FROM {table} GROUP BY _scope"
                )
            db.execute(
                'CREATE VIEW IF NOT EXISTS "期货_数据覆盖" (数据接口,数据类别,合约或交易所,行数,起始日期,结束日期,最后入库时间) AS '
                + " UNION ALL ".join(parts)
            )

    def record_gaps(self, endpoint, symbol, days, task):
        """逐日保留缺口审计；绝不写 coverage，后续普通同步仍会补缺。"""
        stamp = now()
        with self.store.lock, self.store.connect() as db:
            db.executemany(
                """INSERT INTO data_gaps VALUES(?,?,?,?,?,?,?,?,?,NULL)
                ON CONFLICT(dataset,symbol,day) DO UPDATE SET
                    reason=excluded.reason,status='open',last_seen=excluded.last_seen,
                    attempts=data_gaps.attempts+1,source_task=excluded.source_task,
                    resolved_at=NULL""",
                [(endpoint, symbol, day, "接口正常响应但未返回该日结算参数；未填值、未标记覆盖",
                  "open", stamp, stamp, 1, task) for day in sorted(days)],
            )

    def read(
        self, endpoint: str, symbol: str, start: str | None = None, end: str | None = None
    ) -> pd.DataFrame:
        with self.store.connect() as db:
            return self._read(db, endpoint, symbol, start, end)

    @staticmethod
    def _read(db, endpoint, symbol, start=None, end=None):
        table, keys, day = TABLES[endpoint]
        catalog = db.execute(
            "SELECT schema_json FROM market_catalog WHERE dataset=? AND symbol=?",
            (endpoint, symbol),
        ).fetchone()
        if not catalog:
            return pd.DataFrame()
        schema = json.loads(catalog[0])
        where, params = ["_scope=?"], [symbol]
        if day and start:
            where.append(f"{day}>=?")
            params.append(start)
        if day and end:
            where.append(f"{day}<=?")
            params.append(end)
        order = ([day] if day else []) + [k for k in keys if k != day]
        sql = (
            "SELECT "
            + ",".join(quoted(c) for c in schema["columns"])
            + f" FROM {table} WHERE "
            + " AND ".join(where)
            + " ORDER BY "
            + ",".join(quoted(c) for c in order)
        )
        frame = pd.read_sql_query(sql, db, params=params, coerce_float=False)
        for col, dtype in schema["dtypes"].items():
            frame[col] = frame[col].astype(dtype)
        return frame

    def write(
        self,
        endpoint: str,
        symbol: str,
        frame: pd.DataFrame,
        *,
        covered_days=(),
        task: str | None = None,
        repair=None,
        cache_info=None,
        schema_frame=None,
        replace=False,
    ) -> None:
        # 行情、覆盖、修复检查点共用一个 SQLite 事务；失败或断电不会只留下覆盖标志。
        with self.store.lock, self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._write(db, endpoint, symbol, frame, task, schema_frame, replace)
            # 数据补齐与缺口关闭同事务，包含未来从其他来源经本写入入口补充的记录。
            if "trade_date" in frame:
                db.executemany(
                    "UPDATE data_gaps SET status='resolved',resolved_at=? "
                    "WHERE dataset=? AND symbol=? AND day=? AND status='open'",
                    [(now(), endpoint, symbol, day) for day in frame.trade_date.dropna().unique()],
                )
            db.executemany(
                "INSERT OR REPLACE INTO coverage VALUES(?,?,?,?)",
                [(endpoint, symbol, d, "raw-v1") for d in covered_days],
            )
            if repair:
                put_object(db, "repair_coverage", repair[0], {"days": sorted(repair[1])})
            if cache_info:
                put_object(db, "cache", endpoint, cache_info)

    @staticmethod
    def _write(db, endpoint, symbol, frame, task=None, schema_frame=None, replace=False):
        table, keys, day = TABLES[endpoint]
        if frame.empty or any(k not in frame for k in keys) or frame[list(keys)].isna().any().any():
            raise ValueError(f"{endpoint} 为空或主键缺失，拒绝写入及标记覆盖")
        scope_field = (
            "fut_code"
            if endpoint == "fut_basic"
            else "exchange" if endpoint == "fut_trade_cal" else "ts_code"
        )
        if scope_field in frame and not frame[scope_field].eq(symbol).all():
            raise ValueError(f"{endpoint} 返回的数据不属于请求范围 {symbol}，拒绝错误入库和覆盖")
        for col in frame:
            quoted(col)
        frame = frame.drop_duplicates(list(keys), keep="last")
        if schema_frame is None:
            # 部分字段更新时仍保留此前列定义；新列在历史行缺失时采用 pandas 合并类型。
            previous = MarketData._read(db, endpoint, symbol)
            schema_frame = (
                pd.concat([previous, frame], ignore_index=True)
                if not previous.empty and not replace
                else frame
            )
        existing = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
        for col in frame:
            if col not in existing:
                dtype = frame[col].dtype
                kind = (
                    "INTEGER"
                    if pd.api.types.is_integer_dtype(dtype)
                    else "REAL" if pd.api.types.is_numeric_dtype(dtype) else "TEXT"
                )
                db.execute(f"ALTER TABLE {table} ADD COLUMN {quoted(col)} {kind}")
        if replace:
            db.execute(f"DELETE FROM {table} WHERE _scope=?", (symbol,))
        columns = list(frame.columns)
        stamp = now()
        values = [
            tuple(None if pd.isna(v) else v.item() if hasattr(v, "item") else v for v in row)
            + (symbol, stamp, task)
            for row in frame.itertuples(index=False, name=None)
        ]
        names = ",".join(quoted(c) for c in columns) + ",_scope,_updated_at,_source_task"
        updates = ",".join(f"{quoted(c)}=excluded.{quoted(c)}" for c in columns if c not in keys)
        updates += (
            ("," if updates else "")
            + "_scope=excluded._scope,_updated_at=excluded._updated_at,_source_task=excluded._source_task"
        )
        db.executemany(
            f"INSERT INTO {table} ({names}) VALUES ("
            + ",".join("?" for _ in range(len(columns) + 3))
            + ") ON CONFLICT ("
            + ",".join(quoted(k) for k in keys)
            + ") DO UPDATE SET "
            + updates,
            values,
        )
        count = db.execute(f"SELECT count(*) FROM {table} WHERE _scope=?", (symbol,)).fetchone()[0]
        schema = {
            "columns": list(schema_frame.columns),
            "dtypes": {c: str(t) for c, t in schema_frame.dtypes.items()},
        }
        db.execute(
            "INSERT INTO market_catalog VALUES(?,?,?,?,?,?) ON CONFLICT(dataset,symbol) DO UPDATE SET schema_json=excluded.schema_json,row_count=excluded.row_count,updated_at=excluded.updated_at,source_task=excluded.source_task",
            (endpoint, symbol, dumps(schema), count, stamp, task),
        )

    def summary(self) -> pd.DataFrame:
        with self.store.connect() as db:
            return pd.read_sql_query(
                'SELECT * FROM "期货_数据覆盖" ORDER BY 数据接口,合约或交易所', db
            )

    def migrate_legacy(self) -> dict:
        """一次性、可重试的本地迁移。保留旧文件并先做 SQLite 在线备份，无外部请求。"""
        with self.store.lock:
            with self.store.connect() as db:
                row = db.execute(
                    "SELECT report_json FROM market_migrations WHERE name=?", (MIGRATION,)
                ).fetchone()
            if row:
                return json.loads(row[0])
            files = sorted(
                p
                for p in (self.store.root / "cache").glob("*/*.parquet")
                if p.parent.name in TABLES
            )
            run = identifier("sqlite_migration")
            report = {"id": run, "started": now(), "status": "running", "files": [], "requests": 0}
            if files:
                directory = self.store.root / "backups" / run
                directory.mkdir(parents=True)
                with (
                    self.store.connect() as source,
                    sqlite3.connect(directory / "research.sqlite") as target,
                ):
                    source.backup(target)
                shutil.copytree(self.store.root / "cache", directory / "cache")
                report["backup"] = str(directory)
            try:
                with self.store.connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    for path in files:
                        endpoint, symbol = path.parent.name, path.name[:-8]
                        frame = pd.read_parquet(path)
                        self._write(db, endpoint, symbol, frame, task=run, replace=True)
                        actual = self._read(db, endpoint, symbol)
                        keys = TABLES[endpoint][1]
                        expected = frame.sort_values(list(keys)).reset_index(drop=True)
                        pd.testing.assert_frame_equal(
                            expected, actual.sort_values(list(keys)).reset_index(drop=True)
                        )
                        day = TABLES[endpoint][2]
                        if day:
                            # 只承认数据库里真实存在的日期；迁移不会沿用悬空的旧覆盖标志。
                            db.execute(
                                f"DELETE FROM coverage WHERE dataset=? AND symbol=? AND day NOT IN (SELECT {day} FROM {TABLES[endpoint][0]} WHERE _scope=?)",
                                (endpoint, symbol, symbol),
                            )
                            db.executemany(
                                "INSERT OR REPLACE INTO coverage VALUES(?,?,?,?)",
                                [
                                    (endpoint, symbol, d, "raw-v1")
                                    for d in actual[day].dropna().unique()
                                ],
                            )
                        report["files"].append(
                            {
                                "source": str(path.relative_to(self.store.root)),
                                "table": TABLES[endpoint][0],
                                "symbol": symbol,
                                "rows": len(actual),
                                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                "roundtrip": "exact",
                            }
                        )
                    # 缺少对应原始文件的旧清单不再代表已入库，后续同步会补缺口。
                    for endpoint, (table, keys, day) in TABLES.items():
                        if day:
                            db.execute(
                                f"DELETE FROM coverage WHERE dataset=? AND NOT EXISTS (SELECT 1 FROM {table} t WHERE t._scope=coverage.symbol AND t.{day}=coverage.day)",
                                (endpoint,),
                            )
                    report.update(
                        status="succeeded",
                        finished=now(),
                        rows=sum(x["rows"] for x in report["files"]),
                    )
                    db.execute(
                        "INSERT INTO market_migrations VALUES(?,?,?)",
                        (MIGRATION, now(), dumps(report)),
                    )
                self.store.event(run, "sqlite_migration_succeeded", report=report)
            except Exception as e:
                report.update(status="failed", error=str(e), finished=now())
                self.store.event(run, "sqlite_migration_failed", report=report)
                raise
            finally:
                directory = self.store.root / "verification"
                directory.mkdir(exist_ok=True)
                (directory / (run + ".json")).write_text(dumps(report), encoding="utf-8")
            return report
