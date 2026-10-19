"""KLineChart 行情数据展示页：本地内嵌 UMD 构建产物，不依赖外网 CDN。

数据来源为冻结快照（bars/mapping/contracts parquet）：
- 月合约：直接取该合约日线；
- 主连：按主连映射逐日拼接实际月份合约（未复权，仅展示，不用于换月收益计算）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit.components.v1 import html

from alphagpt.research.config import ROOT

KLINE_JS_PATH = ROOT / "app_assets" / "klinecharts.umd.js"

# name -> (中文名, 分组, 是否主图叠加)。以 KLineChart v10 内置指标为准。
INDICATOR_META: dict[str, dict] = {
    "MA": {"zh": "移动平均线", "group": "均线与主图通道", "main": True},
    "EMA": {"zh": "指数移动平均线", "group": "均线与主图通道", "main": True},
    "SMA": {"zh": "简单移动平均线", "group": "均线与主图通道", "main": True},
    "BOLL": {"zh": "布林带", "group": "均线与主图通道", "main": True},
    "BBI": {"zh": "多空指标", "group": "均线与主图通道", "main": True},
    "AVP": {"zh": "成交均价线", "group": "均线与主图通道", "main": True},
    "SAR": {"zh": "抛物线转向", "group": "均线与主图通道", "main": True},
    "VOL": {"zh": "成交量", "group": "成交量与能量", "main": False},
    "OBV": {"zh": "能量潮", "group": "成交量与能量", "main": False},
    "PVT": {"zh": "价量趋势", "group": "成交量与能量", "main": False},
    "VR": {"zh": "成交量比率", "group": "成交量与能量", "main": False},
    "EMV": {"zh": "简易波动指标", "group": "成交量与能量", "main": False},
    "CR": {"zh": "能量指标", "group": "成交量与能量", "main": False},
    "BRAR": {"zh": "人气意愿指标", "group": "成交量与能量", "main": False},
    "MACD": {"zh": "指数平滑异同平均", "group": "趋势与顺势", "main": False},
    "DMI": {"zh": "趋向指标", "group": "趋势与顺势", "main": False},
    "CCI": {"zh": "顺势指标", "group": "趋势与顺势", "main": False},
    "DMA": {"zh": "平均线差", "group": "趋势与顺势", "main": False},
    "TRIX": {"zh": "三重指数平滑平均", "group": "趋势与顺势", "main": False},
    "KDJ": {"zh": "随机指标", "group": "摆动与动量", "main": False},
    "RSI": {"zh": "相对强弱指标", "group": "摆动与动量", "main": False},
    "WR": {"zh": "威廉指标", "group": "摆动与动量", "main": False},
    "ROC": {"zh": "变动率指标", "group": "摆动与动量", "main": False},
    "MTM": {"zh": "动量指标", "group": "摆动与动量", "main": False},
    "AO": {"zh": "动量震荡指标", "group": "摆动与动量", "main": False},
    "PSY": {"zh": "心理线", "group": "摆动与动量", "main": False},
    "BIAS": {"zh": "乖离率", "group": "摆动与动量", "main": False},
}

DEFAULT_INDICATORS = ["MA", "VOL"]

_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
  html,body{margin:0;padding:0;background:#0e1117;color:#e6e6e6;
    font-family:-apple-system,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;}
  #toolbar{display:flex;align-items:center;gap:10px;padding:8px 12px;position:sticky;top:0;
    background:#0e1117;z-index:30;border-bottom:1px solid #262b38;}
  #toolbar button,#toolbar select{background:#1b2130;color:#e6e6e6;border:1px solid #34405a;
    border-radius:6px;padding:4px 12px;font-size:13px;cursor:pointer;}
  #toolbar button:hover,#toolbar select:hover{border-color:#5b8def;}
  .hint{color:#8b93a7;font-size:12px;margin-left:auto;}
  .chart-box{touch-action:none;user-select:none;}
  .chart-card{border-top:1px solid #262b38;}
  .chart-head{display:flex;align-items:baseline;gap:10px;padding:6px 12px 0;}
  .chart-head .code{font-weight:600;font-size:14px;}
  .chart-head .name{color:#8b93a7;font-size:12px;}
  #mask{position:fixed;inset:0;background:rgba(0,0,0,.55);display:none;z-index:40;}
  #dialog{position:fixed;top:5%;left:50%;transform:translateX(-50%);width:540px;max-width:92vw;
    max-height:82vh;overflow:auto;background:#151a26;border:1px solid #34405a;border-radius:10px;
    z-index:50;display:none;padding:14px;}
  #dialog h3{margin:2px 0 10px;font-size:14px;}
  .search-row{display:flex;gap:8px;margin-bottom:10px;}
  #search{flex:1;background:#0e1117;border:1px solid #34405a;border-radius:6px;color:#e6e6e6;
    padding:6px 10px;font-size:13px;outline:none;}
  #search:focus{border-color:#5b8def;}
  .group{margin-bottom:10px;}
  .group-title{color:#8b93a7;font-size:12px;padding:4px 2px;border-bottom:1px dashed #262b38;}
  .items{display:flex;flex-wrap:wrap;gap:6px 4px;padding:6px 2px;}
  .item{display:flex;align-items:center;gap:6px;background:#1b2130;border:1px solid #262b38;
    border-radius:6px;padding:4px 10px;font-size:13px;cursor:pointer;user-select:none;}
  .item:hover{border-color:#5b8def;}
  .item.on{border-color:#5b8def;background:#1d2a45;}
  .item .tag{color:#5b8def;font-size:11px;}
  .item.checked .tag{color:#22c55e;}
</style>
</head>
<body>
<div id="toolbar">
  <button id="btn-indicator">指标选择</button>
  <select id="chart-type">
    <option value="candle_solid">蜡烛图</option>
    <option value="candle_stroke">空心蜡烛</option>
    <option value="ohlc">美国线</option>
    <option value="area">面积图</option>
  </select>
  <button id="btn-reset">重置缩放</button>
  <span class="hint">滚轮缩放 · 拖拽平移 · 多图联动缩放</span>
</div>
<div id="charts"></div>
<div id="mask"></div>
<div id="dialog">
  <h3>选择指标（勾选即时生效，全部图表同步应用）</h3>
  <div class="search-row">
    <input id="search" placeholder="搜索：中文名 / 代码，如 MACD、布林">
    <button id="btn-close">关闭</button>
  </div>
  <div id="groups"></div>
</div>
<script>__KLINE_JS__</script>
<script>
const DATA = __DATA__;
const META = __META__;

const charts = [];
let syncTimer = null;
let selected = new Set(DATA.defaults);

function darkStyles(type) {
  return {
    grid: {horizontal: {color: '#1d2333'}, vertical: {color: '#1d2333'}},
    candle: {
      type: type || 'candle_solid',
      bar: {
        upColor: '#ef4444', downColor: '#22c55e', noChangeColor: '#888888',
        upBorderColor: '#ef4444', downBorderColor: '#22c55e',
        noChangeBorderColor: '#888888',
        upWickColor: '#ef4444', downWickColor: '#22c55e', noChangeWickColor: '#888888'
      },
      priceMark: {
        high: {color: '#8b93a7'}, low: {color: '#8b93a7'},
        last: {line: {color: '#5b8def'}, text: {color: '#e6e6e6'}}
      },
      tooltip: {title: {template: '{ticker} · 日线', color: '#8b93a7'},
        legend: {color: '#e6e6e6'}}
    },
    indicator: {
      tooltip: {text: {color: '#e6e6e6'}},
      lastValueMark: {text: {color: '#e6e6e6'}}
    },
    xAxis: {axisLine: {color: '#2a3247'}, tickText: {color: '#8b93a7'}, tickLine: {color: '#2a3247'}},
    yAxis: {axisLine: {color: '#2a3247'}, tickText: {color: '#8b93a7'}, tickLine: {color: '#2a3247'}},
    separator: {color: '#262b38', fill: true},
    crosshair: {
      horizontal: {line: {color: '#5b8def'}, text: {backgroundColor: '#5b8def', color: '#ffffff'}},
      vertical: {line: {color: '#5b8def'}, text: {backgroundColor: '#5b8def', color: '#ffffff'}}
    }
  };
}

function orderedSelected() {
  const names = Array.from(selected);
  names.sort((a, b) => (META[a] ? 0 : 1) - (META[b] ? 0 : 1));
  return names;
}

function applyAll() {
  // 按指标 ID 增删，保留未变指标与当前视窗，避免异步计算反复重建。
  for (const item of charts) {
    for (const [name, id] of item.indicators) {
      if (!selected.has(name)) {
        item.chart.removeIndicator({id: id});
        item.indicators.delete(name);
      }
    }
    for (const name of orderedSelected()) {
      if (item.indicators.has(name)) continue;
      const meta = META[name] || {main: false};
      const id = item.chart.createIndicator({
        name: name, paneId: meta.main ? 'candle_pane' : 'indicator_' + name
      }, true);
      if (id !== null) item.indicators.set(name, id);
    }
  }
}

function scheduleSync(src) {
  if (charts.length < 2) return;
  clearTimeout(syncTimer);
  syncTimer = setTimeout(function () { syncCharts(src); }, 16);
}

function syncCharts(src) {
  const srcItem = charts.find(function (c) { return c.chart === src; });
  if (srcItem && srcItem.locked) return;
  const barSpace = src.getBarSpace().bar;
  const list = src.getDataList();
  const vr = src.getVisibleRange();
  const rightIdx = Math.max(0, Math.min(list.length - 1, Math.round(vr.to)));
  const rightTs = list.length ? list[rightIdx].timestamp : null;
  for (const item of charts) {
    if (item.chart === src) continue;
    item.locked = true;
    item.chart.setBarSpace(barSpace);
    if (rightTs !== null) item.chart.scrollToTimestamp(rightTs);
  }
  setTimeout(function () {
    for (const item of charts) item.locked = false;
  }, 60);
}

function createChart(info) {
  const card = document.createElement('div');
  card.className = 'chart-card';
  card.innerHTML =
    '<div class="chart-head"><span class="code">' + info.code + '</span>' +
    '<span class="name">' + (info.label || '') + '</span>' +
    '<span class="name" style="margin-left:auto;">' + info.candles.length + ' 根K线</span></div>' +
    '<div class="chart-box" style="height:' + DATA.chartHeight + 'px;"></div>';
  document.getElementById('charts').appendChild(card);
  const box = card.querySelector('.chart-box');
  const chart = klinecharts.init(box, {styles: darkStyles()});
  // span 对 day 类型表示天数，不能传毫秒；否则超界外推的时间戳溢出，渲染循环静默崩溃。
  chart.setPeriod({type: 'day', span: 1});
  chart.setSymbol({ticker: info.code, name: info.label || info.code, pricePrecision: 1, volumePrecision: 0});
  chart.setTimezone('Asia/Shanghai');
  chart.setScrollEnabled(true);
  chart.setZoomEnabled(true);
  chart.setDataLoader({
    getBars: function (params) {
      if (params.type === 'init') {
        params.callback(info.candles, false);
      } else {
        // 向前/向后翻页与更新：数据全量已在 init 下发，更多历史不存在。
        params.callback([], false);
      }
    }
  });
  const item = {chart: chart, initialBarSpace: chart.getBarSpace().bar, locked: false, indicators: new Map()};
  charts.push(item);
  // 只联动用户滚动/缩放，不把指标布局变化当成滚动；同步期间不再回传。
  for (const action of ['onScroll', 'onZoom']) {
    chart.subscribeAction(action, function () {
      if (item.locked) return;
      scheduleSync(chart);
    });
  }
}

let chartType = 'candle_solid';
DATA.contracts.forEach(createChart);
applyAll();

document.getElementById('chart-type').addEventListener('change', function (e) {
  chartType = e.target.value;
  for (const item of charts) item.chart.setStyles({candle: {type: chartType}});
});

document.getElementById('btn-reset').addEventListener('click', function () {
  for (const item of charts) item.locked = true;
  for (const item of charts) {
    item.chart.setBarSpace(item.initialBarSpace);
    item.chart.scrollToRealTime();
  }
  setTimeout(function () {
    for (const item of charts) item.locked = false;
  }, 60);
});

/* ---- 指标选择弹窗 ---- */
function allIndicators() {
  let names = [];
  try { names = klinecharts.getSupportedIndicators(); } catch (e) { names = []; }
  const known = new Set(names);
  for (const name of Object.keys(META)) if (!known.has(name)) names.push(name);
  return names;
}

function buildGroups(filter) {
  const wrap = document.getElementById('groups');
  wrap.innerHTML = '';
  const groups = {};
  for (const name of allIndicators()) {
    const meta = META[name] || {zh: '', group: '其他', main: false};
    if (filter) {
      const text = (name + ' ' + meta.zh + ' ' + meta.group).toLowerCase();
      if (text.indexOf(filter.toLowerCase()) < 0) continue;
    }
    (groups[meta.group] = groups[meta.group] || []).push([name, meta]);
  }
  for (const g of Object.keys(groups)) {
    const div = document.createElement('div');
    div.className = 'group';
    div.innerHTML = '<div class="group-title">' + g + '</div>';
    const items = document.createElement('div');
    items.className = 'items';
    for (const [name, meta] of groups[g]) {
      const el = document.createElement('span');
      el.className = 'item' + (selected.has(name) ? ' on checked' : '');
      el.innerHTML =
        '<input type="checkbox"' + (selected.has(name) ? ' checked' : '') + '>' +
        '<b>' + name + '</b>' +
        (meta.zh ? '<span style="color:#8b93a7;">' + meta.zh + '</span>' : '') +
        (meta.main ? '<span class="tag">主图</span>' : '');
      el.addEventListener('click', function () {
        if (selected.has(name)) selected.delete(name); else selected.add(name);
        el.classList.toggle('on'); el.classList.toggle('checked');
        el.querySelector('input').checked = selected.has(name);
        applyAll();
      });
      items.appendChild(el);
    }
    div.appendChild(items);
    wrap.appendChild(div);
  }
}

const mask = document.getElementById('mask');
const dialog = document.getElementById('dialog');
function toggleDialog(show) {
  mask.style.display = show ? 'block' : 'none';
  dialog.style.display = show ? 'block' : 'none';
}
document.getElementById('btn-indicator').addEventListener('click', function () {
  buildGroups(document.getElementById('search').value);
  toggleDialog(true);
});
document.getElementById('btn-close').addEventListener('click', function () { toggleDialog(false); });
mask.addEventListener('click', function () { toggleDialog(false); });
document.getElementById('search').addEventListener('input', function (e) {
  buildGroups(e.target.value);
});
buildGroups('');
</script>
</body>
</html>
"""


@st.cache_data(show_spinner=False)
def _load_snapshot(snapshot_dir: str):
    base = Path(snapshot_dir)

    def read(name):
        path = base / name
        return pd.read_parquet(path) if path.exists() else pd.DataFrame()

    return read("bars.parquet"), read("mapping.parquet"), read("contracts.parquet")


def contract_options(bars: pd.DataFrame, mapping: pd.DataFrame, contracts: pd.DataFrame) -> list[dict]:
    """主连排最前，月合约按交割时间倒序。"""
    meta: dict[str, tuple[str, str]] = {}
    if not contracts.empty:
        for row in contracts.itertuples(index=False):
            meta[str(row.ts_code)] = (
                str(getattr(row, "name", "") or ""),
                str(getattr(row, "delist_date", "") or ""),
            )
    options: list[dict] = []
    if not mapping.empty and "ts_code" in mapping:
        for code in sorted(str(c) for c in mapping.ts_code.unique()):
            options.append(
                {"code": code + "::causal_ratio", "label": f"{code} 因果比例复权主连（信号曲线）", "main": True}
            )
            options.append({"code":code, "label":f"{code} 主连（逐日映射拼接，未复权）", "main":False})
    monthly = sorted({str(c) for c in bars.ts_code.unique()}) if not bars.empty else []

    def delivery_key(code: str) -> str:
        delist = meta.get(code, ("", ""))[1]
        if delist:
            return delist
        match = re.search(r"(\d{6})", code)
        return match.group(1) if match else code

    monthly.sort(key=lambda c: (delivery_key(c), c), reverse=True)
    for code in monthly:
        name, delist = meta.get(code, ("", ""))
        label = code + (f" {name}" if name else "")
        if delist:
            label += f" · 交割 {delist}"
        options.append({"code": code, "label": label, "main": False})
    return options


def build_candles(bars: pd.DataFrame, mapping: pd.DataFrame, code: str, contracts=None) -> list[dict]:
    if code.endswith("::causal_ratio"):
        from alphagpt.data.curves import select_curve, build_curve_frame
        # 看板和研究使用同一个复权算法；真实月合约原始数据保持不变。
        original = code.split("::")[0]
        if contracts is None:
            raise ValueError("复权曲线需要真实合约元数据，不能用最后一条行情伪造到期日")
        data = select_curve({"bars":bars,"mapping":mapping,"contracts":contracts},original)
        panel = build_curve_frame(data)
        panel = panel.assign(vol=panel.get("vol", 0), amount=panel.get("amount", 0))
        adjusted = panel[["trade_date","signal_open","signal_high","signal_low","signal_close","vol","amount"]].rename(columns={"signal_open":"open","signal_high":"high","signal_low":"low","signal_close":"close"})
        return build_candles(adjusted.assign(ts_code=original), pd.DataFrame(), original)
    if not mapping.empty and "ts_code" in mapping and code in set(mapping.ts_code.astype(str)):
        joined = mapping[mapping.ts_code.astype(str) == code].merge(
            bars,
            left_on=["trade_date", "mapping_ts_code"],
            right_on=["trade_date", "ts_code"],
            how="inner",
        )
    else:
        joined = bars[bars.ts_code.astype(str) == code]
    joined = joined.sort_values("trade_date")
    candles = []
    for row in joined.itertuples(index=False):
        day = str(row.trade_date)
        try:
            ts = int(pd.Timestamp(day).value // 1_000_000)
        except Exception:
            continue
        open_, high, low, close = (getattr(row, name, None) for name in ("open", "high", "low", "close"))
        if open_ is None or close is None or pd.isna(open_) or pd.isna(close):
            continue
        vol = getattr(row, "vol", 0)
        amount = getattr(row, "amount", 0)
        candles.append(
            {
                "timestamp": ts,
                "open": round(float(open_), 2),
                "high": round(float(high if high is not None and not pd.isna(high) else open_), 2),
                "low": round(float(low if low is not None and not pd.isna(low) else open_), 2),
                "close": round(float(close), 2),
                "volume": 0 if vol is None or pd.isna(vol) else int(vol),
                "turnover": 0 if amount is None or pd.isna(amount) else round(float(amount) * 1e4, 2),
            }
        )
    return candles


def render_data_view(store) -> None:
    st.subheader("行情数据展示（KLineChart）")
    snapshots = store.list("snapshots")
    if not snapshots:
        st.info("还没有真实数据快照。请先在数据同步页面建立快照。")
        return
    if not KLINE_JS_PATH.exists():
        st.error(f"缺少本地图表库文件：{KLINE_JS_PATH}")
        return
    chosen = st.selectbox("数据快照", [s["id"] for s in snapshots], key="kline_snapshot")
    bars, mapping, contracts = _load_snapshot(str(store.root / "snapshots" / chosen))
    if bars.empty:
        st.warning("该快照没有行情数据。")
        return
    options = contract_options(bars, mapping, contracts)
    codes = [o["code"] for o in options]
    labels = {o["code"]: o["label"] for o in options}
    defaults = [o["code"] for o in options if o["main"]][:1] or codes[:1]
    picked = st.multiselect(
        "展示合约（可多选，最多 6 个）",
        codes,
        default=defaults,
        max_selections=6,
        format_func=lambda c: labels.get(c, c),
        key="kline_contracts",
    )
    chart_height = st.slider("单图高度（像素）", 320, 800, 460, step=20, key="kline_height")
    if not picked:
        st.info("请至少选择一个合约。")
        return
    if not mapping.empty:
        st.caption(
            "可选因果比例复权主连、原始未复权主连及真实月份合约；原始主连换月处存在价差跳变。"
            "复权曲线用于信号，回测按真实月份原价成交盯市；成交额已换算为元（AVP均价线为元/手）。"
        )
    payload = {
        "defaults": [c for c in DEFAULT_INDICATORS],
        "chartHeight": chart_height,
        "contracts": [
            {
                "code": code,
                "label": labels.get(code, code),
                "candles": build_candles(bars, mapping, code, contracts=contracts),
            }
            for code in picked
        ],
    }
    kline_js = KLINE_JS_PATH.read_text(encoding="utf-8").replace("</script", "<\\/script")
    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    meta_json = json.dumps(INDICATOR_META, ensure_ascii=False)
    page = (
        _TEMPLATE.replace("__KLINE_JS__", kline_js)
        .replace("__DATA__", data_json)
        .replace("__META__", meta_json)
    )
    total = 56 + len(picked) * (chart_height + 34) + 12
    html(page, height=total, scrolling=False)
