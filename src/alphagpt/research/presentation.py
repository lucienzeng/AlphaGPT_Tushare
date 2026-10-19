"""研究列表展示：只读取已保存结果，不触发模型或回测。"""

TASK_STATES = {"queued": "等待执行", "running": "运行中", "succeeded": "成功", "failed": "失败", "stopped": "已停止", "interrupted": "程序中断"}
FACTOR_STATES = {"accepted": "可计算", "rejected": "已淘汰"}
RESEARCH_STAGES = {'computable':'可计算','development_passed':'开发筛选通过','independent_check_passed':'独立检验初筛通过'}


def factor_state(factor):
    return '已淘汰' if factor.get('status') == 'rejected' else RESEARCH_STAGES.get(factor.get('research_stage'),'可计算（历史结果未分层）')


def factor_rows(factors, tasks, runs, experiments, calls):
    """批量关联任务与开发实验；不读取最终测试指标，保留淘汰候选和人工基线。"""
    tasks = {x['id']: x for x in tasks}
    runs = {x['id']: x for x in runs}
    experiments = {x['id']: x for x in experiments}
    usage = {}
    for call in calls:
        entry = usage.setdefault(call.get('task'), [0, 0])
        entry[0] += 1
        entry[1] += call.get('total_tokens') or 0
    rows = []
    for f in factors:
        task_id = f.get('task', '')
        task = tasks.get(task_id, {})
        run = runs.get(task_id, {})
        config = task.get('params') or run.get('config') or {}
        model = config.get('model') or {}
        raw = f.get('raw') if isinstance(f.get('raw'), dict) else {}
        experiment = experiments.get(f.get('experiment'), {})
        # 仅展示验证区，不能在此暴露已封存的测试指标。
        metrics = f.get('valid_metrics') or experiment.get('segments', {}).get('valid', {}).get('metrics', {})
        used_calls, tokens = usage.get(task_id, [0, 0])
        rows.append({
            '因子名称': f.get('name_zh') or raw.get('name_zh') or '无效候选',
            '因子状态': factor_state(f),
            '研究计划': f.get('plan') or run.get('plan',''),
            '独立验证': '未记录先前暴露' if f.get('validation_independent') else '已观察或未核实',
            '任务编号': task_id,
            '因子来源': f.get('source', ''),
            '挖掘轮次（轮）': f.get('round', 0),
            '任务状态': TASK_STATES.get(task.get('status'), '任务记录缺失'),
            '研究曲线': config.get('curve', 'CU.SHF'),
            '价格处理': {'causal_ratio':'因果比例复权','raw':'原始价格'}.get(config.get('price_mode','causal_ratio'),'未知'),
            '特征版本': f.get('feature_version') or config.get('feature_version','legacy-v1'),
            '曲线版本编号': f.get('curve_id') or run.get('curve_id',''),
            '模型供应商': model.get('provider', f.get('source', '')),
            '模型名称': f.get('model') or model.get('model', ''),
            '验证夏普': metrics.get('sharpe'),
            '验证收益（%）': 100 * metrics['total_return'] if metrics.get('total_return') is not None else None,
            '验证回撤（%）': 100 * metrics['max_drawdown'] if metrics.get('max_drawdown') is not None else None,
            '淘汰原因': f.get('reason', ''),
            '因子表达式': f.get('expression') or raw.get('expression', ''),
            '中文逻辑': f.get('logic_zh') or raw.get('logic_zh', ''),
            '任务创建时间（UTC）': task.get('created') or run.get('created', ''),
            '任务调用次数（次）': used_calls,
            '任务已用 Token（个）': tokens,
            '任务计划轮数（轮）': config.get('rounds'),
            '每轮计划因子数（个）': config.get('count'),
            '数据快照': config.get('snapshot') or run.get('snapshot', ''),
            '因子编号': f['id'],
            '开发实验编号': f.get('experiment', ''),
        })
    return rows
