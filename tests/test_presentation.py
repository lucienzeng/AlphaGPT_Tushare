from alphagpt.research.presentation import factor_rows
from alphagpt.research.config import ExperimentConfig


def test_factor_listing_includes_all_states_tasks_and_validation_only():
    factors = [dict(id='a', task='task1', round=1, status='accepted', experiment='exp1', name_zh='动量'),
               dict(id='b', task='task1', round=2, status='rejected', reason='表达式无效', raw=dict(name_zh='无效动量', expression='bad()')),
               dict(id='c', task='missing', round=0, status='accepted', source='人工基线')]
    tasks = [dict(id='task1', status='failed', created='2026-01-01', params=dict(snapshot='snapshot1', model=dict(provider='deepseek',model='deepseek-chat'),rounds=2,count=10))]
    experiments = [dict(id='exp1', segments=dict(valid=dict(metrics=dict(total_return=0.12, max_drawdown=-0.04,sharpe=1.2)), test=dict(metrics=dict(total_return=999))))]
    rows = factor_rows(factors, tasks, [], experiments, [dict(task='task1',total_tokens=300),dict(task='task1',total_tokens=None)])
    assert len(rows)==3
    assert rows[0]['任务状态']=='失败'
    assert rows[0]['验证收益（%）']==12
    assert rows[0]['验证回撤（%）']==-4
    assert rows[0]['任务调用次数（次）']==2
    assert rows[0]['任务已用 Token（个）']==300
    assert rows[0]['模型名称']=='deepseek-chat'
    assert rows[1]['因子状态']=='已淘汰' and rows[1]['因子名称']=='无效动量'
    assert rows[1]['任务编号']=='task1'
    assert rows[2]['任务状态']=='任务记录缺失'
    assert 999 not in rows[0].values()


def test_listing_can_use_run_metadata_and_new_task_budget_default():
    rows=factor_rows([dict(id='f',task='t')],[],[dict(id='t',config=dict(snapshot='s',model=dict(model='kimi')))],[],[])
    assert rows[0]['数据快照']=='s' and rows[0]['模型名称']=='kimi'
    assert ExperimentConfig('s','2020-01-01','2023-12-31','2024-12-31','2025-12-31').token_budget==500000
