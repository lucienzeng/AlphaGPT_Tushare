"""研究计划、区间暴露和候选预算：更换快照不能恢复已经观察的时间段。"""
from dataclasses import asdict
import hashlib
import pandas as pd
from alphagpt.research.storage import dumps, now


def next_day(day):
    return (pd.Timestamp(day) + pd.Timedelta(days=1)).date().isoformat()


def overlap(a, b, c, d):
    return a <= d and c <= b


def exposure_status(store, start, end, task):
    matches = []
    # 沪铜当前为单品种；按日期而不是快照ID识别复用，兼容旧实验记录。
    for run in store.list('runs'):
        cfg = run.get('config', {})
        if run['id'] != task and cfg.get('train_start') and overlap(start,end,cfg['train_start'],cfg['valid_end']):
            matches.append(run['id'])
    for item in store.list('test_access'):
        cfg = item.get('config', {})
        if cfg.get('valid_end') and overlap(start,end,next_day(cfg['valid_end']),cfg['test_end']):
            matches.append(item['id'])
    for item in store.list('holdout_access'):
        if item.get('task') != task and overlap(start,end,item['start'],item['end']):
            matches.append(item['id'])
    return dict(independent=not matches, prior_exposures=sorted(set(matches)),
                note='本系统未记录先前暴露；不证明系统外从未观察' if not matches else '已观察区间重测，不能称为新的独立检验')


def register_plan(store, cfg, task):
    frozen = asdict(cfg)
    key = 'plan_' + hashlib.sha256(dumps(frozen).encode()).hexdigest()[:20]
    if not store.get('research_plans', key):
        store.put('research_plans',key,dict(config=frozen, created=now(),
            feedback_scope='仅训练开发区；独立验证与最终测试不进入模型',
            availability=dict(policy='conservative-t2-v1', published_at=None,
                status='保守假设，历史发布时间未核实', lag=cfg.backtest.decision_lag,
                night_session='日线开盘所属交易时段待来源审计；不宣称09:00成交'),
            selection_rule='开发净收益>0且Rank IC与预期方向一致；独立区另行检验，不保证显著性'))
    return key


def reserve_trial(store, plan, factor, task, budget, expression):
    with store.lock:
        key = factor
        existing = store.get('trial_registry', key)
        if existing:
            return
        trials = [x for x in store.list('trial_registry') if x['plan'] == plan]
        if len(trials) >= budget:
            raise ValueError('研究计划累计候选预算已用完；恢复/克隆任务不会重置预算')
        store.put('trial_registry', key, dict(plan=plan, task=task, expression=expression,
                  status='reserved', created=now()))


def record_access(store, task, phase, start, end):
    state = exposure_status(store,start,end,task)
    key = f'{task}:{phase}:{start}:{end}'
    existing = store.get('holdout_access',key)
    if existing:
        return existing
    record = dict(task=task, phase=phase, start=start, end=end, commodity='CU',
                  viewed_at=now(), **state)
    store.put('holdout_access',key,record)
    return record


def availability_check(data, lag):
    """显式来源给出更晚可用日期时必须拒绝；未给出时只承认保守假设。"""
    days = sorted(data['mapping'].trade_date.unique())
    positions = {day:i for i,day in enumerate(days)}
    for name in ('bars','mapping','limits'):
        if name not in data:
            continue
        frame = data[name]
        for row in frame.to_dict('records'):
            day=row['trade_date'];i=positions.get(day)
            if i is None or i+lag >= len(days):
                continue
            if 'available_trade_date' in row and (pd.isna(row['available_trade_date']) or str(row['available_trade_date']) > days[i+lag]):
                raise ValueError(f'{name} {day} 在计划执行日尚不可用；拒绝访问未来发布数据')
            for col in ('available_at','published_at'):
                if col not in row:
                    continue
                if pd.isna(row[col]):
                    raise ValueError(f'{name} 显式{col}缺失，不能假装发布时间已核实')
                available=pd.Timestamp(row[col])
                if available.tzinfo is None:
                    raise ValueError('发布时间必须有时区')
                # 采用执行交易日前一个交易日20:55作为保守提交截止，不声称夜盘实际存在。
                # 节假日可能使实际开盘更晚，此处只会更严格，不会把晚发布的信息提前放行。
                deadline=pd.Timestamp(days[i+lag-1]+' 20:55:00',tz='Asia/Shanghai')
                if available > deadline:
                    raise ValueError(f'{name} {day} 在保守提交截止后发布，拒绝未来信息')
    return dict(policy='conservative-t2-v1', lag=lag, status='保守假设；精确发布时间与夜盘开盘仍待核实')
