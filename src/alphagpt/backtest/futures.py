"""真实合约逐日账本：先结算旧持仓隔夜变化，再撮合开盘，最后结算当日持仓。"""

from dataclasses import asdict
import math
import numpy as np
import pandas as pd
from alphagpt.research.config import BacktestConfig


def signal_positions(factor: pd.Series, cfg: BacktestConfig, direction: int = 1) -> pd.Series:
    mean = factor.rolling(cfg.signal_window, min_periods=20).mean().shift(1)
    std = factor.rolling(cfg.signal_window, min_periods=20).std().shift(1).replace(0, np.nan)
    z = ((factor - mean) / std) * direction
    return pd.Series(
        np.where(z > cfg.threshold, 1, np.where(z < -cfg.threshold, -1, 0)), index=factor.index
    ).where(z.notna(), 0)


def metrics(daily: pd.DataFrame, trades: pd.DataFrame) -> dict:
    if daily.empty:
        return {"days": 0, "sharpe": None}
    r = daily.net_return
    nav = (1 + r).cumprod()
    drawdown = nav / np.maximum.accumulate(np.r_[1.0, nav.to_numpy()])[1:] - 1
    annual = float(nav.iloc[-1] ** (252 / len(r)) - 1) if nav.iloc[-1] > 0 else -1.0
    volatility = float(r.std(ddof=1) * np.sqrt(252)) if len(r) > 1 else 0.0
    maxdd = float(drawdown.min())
    return {
        "days": len(r),
        "total_return": float(nav.iloc[-1] - 1),
        "annual_return": annual,
        "annual_volatility": volatility,
        "sharpe": (
            float(r.mean() / r.std(ddof=1) * np.sqrt(252))
            if len(r) > 1 and r.std(ddof=1) > 1e-12
            else None
        ),
        "max_drawdown": maxdd,
        "calmar": annual / abs(maxdd) if maxdd < 0 else None,
        "win_rate": (
            float((daily.loc[daily.gross_pnl.ne(0), "net_pnl"] > 0).mean())
            if daily.gross_pnl.ne(0).any()
            else None
        ),
        "trade_count": int(len(trades)),
        "fees": float(daily.fee.sum()),
        "slippage_cost": float(daily.slippage_cost.sum()),
        "turnover": float(daily.turnover.sum()),
        "max_margin_ratio": float(daily.margin_ratio.max()),
        "gross_total_return": float((1 + daily.gross_return).prod() - 1),
        "win_rate_definition": "非零毛盈亏交易日的净盈利占比，非完整交易胜率",
    }


def backtest(
    data: dict[str, pd.DataFrame],
    factor: pd.Series,
    cfg: BacktestConfig,
    start: str,
    end: str,
    direction: int = 1,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    cfg.validate()
    from alphagpt.research.protocol import availability_check
    availability_check({
        name: frame.loc[frame.trade_date.le(end)] if "trade_date" in frame else frame
        for name, frame in data.items()
    }, cfg.decision_lag)
    mapping = data["mapping"].sort_values("trade_date").set_index("trade_date")
    dates = mapping.index.tolist()
    bars = data["bars"].set_index(["trade_date", "ts_code"])
    limits = data["limits"].set_index(["trade_date", "ts_code"])
    fee_table = data["fees"].set_index(["trade_date", "ts_code"])
    contracts = data["contracts"].set_index("ts_code")
    signals = signal_positions(factor.reindex(dates), cfg, direction)
    equity, holding, qty, last_settle = cfg.capital, None, 0, 0.0
    pending_liquidation = False
    equity_history: dict[str, float] = {}
    rows, trades = [], []

    def bar(day, symbol):
        try:
            return bars.loc[(day, symbol)]
        except KeyError:
            return None

    for i, day in enumerate(dates):
        if day < start or day > end:
            continue
        before = equity
        fee = slip_cost = turnover = gross = 0.0
        reason = []
        existing = bar(day, holding) if holding else None
        if holding and existing is None:
            raise ValueError(f"持仓合约 {holding} 在 {day} 缺行情，不能跳过其盈亏")
        if holding:
            size = float(contracts.loc[holding, "per_unit"])
            gross += qty * (float(existing.open) - last_settle) * size
        prior_i = i - cfg.decision_lag
        target, wanted = None, 0
        if prior_i >= 0:
            decision_day = dates[prior_i]
            target = str(mapping.loc[decision_day, "mapping_ts_code"])
            # 禁止交割月临近持仓；保守日历天缓冲，实际截止日期来自合约元数据。
            expiry = str(contracts.loc[target, "delist_date"])
            if (
                pd.Timestamp(expiry) - pd.Timestamp(day)
            ).days <= cfg.delivery_buffer_days or pd.Timestamp(expiry).strftime("%Y-%m") == day[:7]:
                target = None
                reason.append("交割保护：目标合约退出")
            if target:
                decision_bar = bar(decision_day, target)
                if decision_bar is None:
                    raise ValueError("决策日目标合约缺少价格")
                size = float(contracts.loc[target, "per_unit"])
                if not np.isfinite(size) or size <= 0:
                    raise ValueError("商品期货 per_unit 无效")
                # 下单手数在决策日冻结：不能先看到执行日开盘价，再按该价调仓并成交。
                known_equity = max(0, equity_history.get(decision_day, cfg.capital))
                reference = float(decision_bar.close) * size
                if not np.isfinite(reference) or reference <= 0:
                    raise ValueError("决策日参考价格无效")
                if (decision_day, target) not in limits.index:
                    raise ValueError(f"{decision_day} {target} 缺决策日保证金参数")
                known_limit = limits.loc[(decision_day, target)]
                margin = float(known_limit.m_ratio) / 100 if pd.notna(known_limit.m_ratio) else cfg.fallback_margin
                if not np.isfinite(margin) or margin <= 0:
                    raise ValueError("决策日保证金比例无效")
                nominal_cap = math.floor(known_equity * cfg.exposure / reference)
                margin_cap = math.floor(known_equity * cfg.margin_cap / (reference * margin))
                wanted = int(signals.iloc[prior_i]) * min(nominal_cap, margin_cap)
        planned_target, planned_quantity = target, wanted
        # 强平指令只来自已完成的上一交易日账本，不用当日开盘浮盈亏倒推开盘订单。
        if pending_liquidation or equity <= 0:
            target, wanted = None, 0
            reason.append("保证金保护：下一可成交时点减仓")

        def transact(symbol, change, label):
            nonlocal fee, slip_cost, turnover
            if change == 0:
                return 0
            # 当日总成交量直到盘后才知道，不能用 b.vol 决定当日开盘是否成交。
            b = bar(day, symbol)
            if b is None or not np.isfinite(b.open) or b.open <= 0:
                reason.append(f"{symbol} 无可用开盘报价，订单未成交")
                return 0
            lim = limits.loc[(day, symbol)] if (day, symbol) in limits.index else None
            if lim is None:
                raise ValueError(f"{day} {symbol} 缺涨跌停数据，无法校验成交")
            if any(not np.isfinite(float(lim[k])) or float(lim[k]) <= 0 for k in ['up_limit','down_limit']):
                raise ValueError(f'{day} {symbol} 涨跌停价无效；拒绝用NaN绕过成交约束')
            price = float(b.open)
            if (change > 0 and price >= float(lim.up_limit)) or (
                change < 0 and price <= float(lim.down_limit)
            ):
                reason.append(f"{symbol} 开盘在交易方向涨跌停，保守不成交")
                return 0
            tick_slip = cfg.slippage_ticks * cfg.tick_size
            fill = price + np.sign(change) * tick_slip
            if not float(lim.down_limit) <= fill <= float(lim.up_limit):
                reason.append("滑点后价格越界，未成交")
                return 0
            unit = float(contracts.loc[symbol, "per_unit"])
            order_fee = abs(change) * (fill * unit * cfg.fee if cfg.fee_mode == "rate" else cfg.fee)
            if cfg.fee_mode == "historical":
                if (day, symbol) not in fee_table.index:
                    raise ValueError("缺少历史手续费，拒绝填0")
                row = fee_table.loc[(day, symbol)]
                rate, fixed = row.get("trading_fee_rate"), row.get("trading_fee")
                if pd.notna(rate) and float(rate) > 0 and (pd.isna(fixed) or float(fixed) == 0):
                    order_fee = abs(change) * fill * unit * float(rate)
                elif pd.notna(fixed) and float(fixed) > 0 and (pd.isna(rate) or float(rate) == 0):
                    order_fee = abs(change) * float(fixed)
                else:
                    raise ValueError(
                        "历史费率含义缺失或同时出现两种非零口径，请使用明确的固定成本配置"
                    )
            order_fee += abs(change) * cfg.broker_fee_per_lot
            fee += order_fee
            cost = abs(change) * unit * tick_slip
            slip_cost += cost
            turnover += abs(change) * price * unit / max(before, 1)
            trades.append(
                {
                    "trade_date": day,
                    "symbol": symbol,
                    "change": change,
                    "reference_open": price,
                    "fill_price": fill,
                    "fee": order_fee,
                    "slippage_cost": cost,
                    "reason": label,
                    "decision_date": dates[prior_i] if prior_i >= 0 else None,
                }
            )
            return change

        if holding and target != holding:
            changed = transact(holding, -qty, "换月平仓" if target else "退出持仓")
            qty += changed
            if qty == 0:
                holding = None
            else:
                target, wanted = holding, qty  # 平旧约失败不能直接再开新约，避免隐藏双持仓。
        if target:
            b = bar(day, target)
            if b is not None:
                lim = limits.loc[(day, target)] if (day, target) in limits.index else None
                if lim is None:
                    raise ValueError(f"目标合约 {target} 缺保证金约束")
                current = qty if holding == target else 0
                # 反手分两笔，持有到下次开盘才退出，不产生平今费率歧义。
                if current * wanted < 0:
                    qty += transact(target, -current, "反手平仓")
                    current = qty
                    if current:
                        wanted = current
                changed = transact(
                    target, wanted - current, "开仓/调仓" if holding == target else "换月/首次开仓"
                )
                qty = current + changed
                holding = target if qty else None
        if holding:
            b = bar(day, holding)
            unit = float(contracts.loc[holding, "per_unit"])
            gross += qty * (float(b.settle) - float(b.open)) * unit
            last_settle = float(b.settle)
            lim = limits.loc[(day, holding)]
            margin_rate = float(lim.m_ratio) / 100 if pd.notna(lim.m_ratio) else cfg.fallback_margin
            margin_used = abs(qty) * last_settle * unit * margin_rate
        else:
            margin_used = 0.0
        net = gross - fee - slip_cost
        equity += net
        equity_history[day] = equity
        pending_liquidation = equity <= 0 or margin_used > max(equity, 0) * cfg.margin_cap
        rows.append(
            {
                "trade_date": day,
                "decision_date": dates[prior_i] if prior_i >= 0 else None,
                "planned_symbol": planned_target or "",
                "planned_quantity": planned_quantity,
                "equity": equity,
                "net_pnl": net,
                "gross_pnl": gross,
                "net_return": net / before if before > 0 else 0,
                "gross_return": gross / before if before > 0 else 0,
                "fee": fee,
                "slippage_cost": slip_cost,
                "turnover": turnover,
                "symbol": holding or "",
                "quantity": qty,
                "margin_used": margin_used,
                "margin_ratio": margin_used / max(equity, 1),
                "notes": "；".join(reason),
            }
        )
        if equity <= 0:
            break  # 破产停止，不允许负权益继续复利。
    daily, trade_frame = pd.DataFrame(rows), pd.DataFrame(trades)
    return daily, trade_frame, metrics(daily, trade_frame)


def executable_labels(data: dict, lag: int) -> pd.Series:
    """决策 t 的预测标签为 t+lag 开盘到再下一开盘的同一月合约收益，跨月不直接拼价。"""
    m = data["mapping"].sort_values("trade_date")
    b = data["bars"].set_index(["trade_date", "ts_code"])
    out = pd.Series(np.nan, index=pd.Index(m.trade_date, name="trade_date"))
    for i in range(len(m) - lag - 1):
        symbol = m.iloc[i].mapping_ts_code
        try:
            out.iloc[i] = (
                b.loc[(m.iloc[i + lag + 1].trade_date, symbol), "open"]
                / b.loc[(m.iloc[i + lag].trade_date, symbol), "open"]
                - 1
            )
        except KeyError:
            pass
    return out
