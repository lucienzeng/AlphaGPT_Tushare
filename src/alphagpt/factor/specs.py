"""唯一特征字典：计算类型、单位和研究角色由提示词、界面及导出共用。"""
FEATURES = {
    "ret5": "连续价格5日收益",
    "ret20": "连续价格20日收益",
    "ret60": "连续价格60日收益",
    "trend20": "收盘价相对20日均线偏离",
    "trend60": "收盘价相对60日均线偏离",
    "reversal": "负的3日收益，较高表示近期下跌",
    "volatility": "20日收益标准差",
    "volatility_ratio": "5日/20日收益波动率比减1",
    "range20": "20日平均日内振幅比例",
    "close_position": "收盘在当日高低区间的位置减0.5",
    "volume_ratio": "当前月合约成交量/该合约过去20日均量减1",
    "oi_change5": "当前月合约5日持仓变化率，不代表单向资金流入",
    "oi_ratio": "当前月合约持仓量/该合约过去20日均量减1",
    "volume_oi": "当前月合约成交/持仓比",
    "price_volume": "1日连续收益乘成交量偏离",
    "price_oi": "5日连续收益乘5日持仓变化率",
    "breakout": "收盘相对过去20日最高价与最低价中点偏离",
    "vol_change": "20日波动率的5日变化",
}


RAW_FEATURES = {
    "ret20_raw": "原始方向：因果连续20日收益（比例），正数才表示实际上涨",
    "ret60_raw": "原始方向：因果连续60日收益（比例）",
    "oi_change5_raw": "原始方向：当前真实合约5日持仓变化率；正数为增仓，不代表单向资金流入",
    "close_location_raw": "原始位置：(收盘-最低)/(最高-最低)-0.5，范围[-0.5,0.5]",
    "same_contract_ret5_raw": "原始方向：当前真实合约自身5日收益，未混入别的合约",
    "same_contract_price_oi_raw": "原始交互：同合约5日收益乘同合约5日持仓变化；双负也为正",
    "days_to_last_trade": "原始生命周期：距离已知最后交易日的日历天数",
    "days_since_roll": "原始生命周期：距离最近已发生映射切换的交易日数；不使用未来切换日",
    "is_roll": "已发生换月标志：当日映射较前日切换为1，否则0",
}
FEATURES.update(RAW_FEATURES)

LIFECYCLE = {'days_to_last_trade', 'days_since_roll', 'is_roll'}
SPECS = {name: dict(description=description,
    kind='标志' if name == 'is_roll' else '天数' if name in LIFECYCLE else '原始值' if name in RAW_FEATURES else '历史标准分',
    unit='0/1' if name == 'is_roll' else '日历天' if name == 'days_to_last_trade' else '交易日' if name == 'days_since_roll' else '无量纲',
    role='过滤/分层' if name in LIFECYCLE else '方向/强度候选',
    history='标准分基准：之前60交易日，至少30个观测' if name not in RAW_FEATURES else '按特征公式历史窗口；不二次标准化输入',
    availability='盘后；默认保守延迟至t+2交易日，历史精确发布时间未核实')
    for name, description in FEATURES.items()}


def describe(name):
    spec = SPECS[name]
    return f"{spec['description']}；类型：{spec['kind']}；单位：{spec['unit']}；用途：{spec['role']}；{spec['history']}；{spec['availability']}"
