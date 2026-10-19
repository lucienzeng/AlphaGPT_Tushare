"""固定随机对照和时间稳定性诊断；不使用最终测试挑选参数。"""
import numpy as np
import pandas as pd


def random_templates(count, names):
    rng = np.random.default_rng(20261019)
    eligible = sorted(n for n in names if n not in {'is_roll','days_to_last_trade','days_since_roll'})
    if len(eligible)<2:
        return []
    result = []
    for i in range(count):
        a,b = rng.choice(eligible,2,replace=False)
        result.append(dict(name_zh=f'随机合法对照{i+1}',expression=f'tanh({a}) + 0.3 * tanh({b})',
            logic_zh=f'使用固定随机种子抽取{a}和{b}，经有界函数组合形成合法表达式。此对照没有预先提出的经济优势，只用于检验模型搜索是否超过同等复杂度的机械组合，不应因为某段表现好就解释成稳定规律。',
            expected_direction=1,market_regime='无事前行情假设',failure_risks='随机搜索偶然拟合',random_control=True))
    return result


def temporal_diagnostics(values,labels,direction):
    aligned = pd.concat([values.rename('f'),labels.rename('y')],axis=1).dropna()
    windows = []
    for chunk in np.array_split(np.arange(len(aligned)),3):
        part = aligned.iloc[chunk]
        if len(part)<10:
            continue
        rank = part.f.corr(part.y,method='spearman') if part.f.std()>1e-12 and part.y.std()>1e-12 else None
        windows.append(dict(start=part.index.min(),end=part.index.max(),samples=len(part),rank_ic=rank))
    # 区块自助法示例：给出预测协动统计的不确定性；不是盈利概率或显著性担保。
    interval = None
    if len(aligned)>=40 and aligned.f.std()>1e-12 and aligned.y.std()>1e-12:
        score = ((aligned.f-aligned.f.mean())/aligned.f.std() * (aligned.y-aligned.y.mean())/aligned.y.std()).to_numpy()*direction
        rng=np.random.default_rng(20261019)
        length=5
        statistics=[]
        for _ in range(200):
            starts=rng.integers(0,len(score),size=int(np.ceil(len(score)/length)))
            ix=np.concatenate([(s+np.arange(length))%len(score) for s in starts])[:len(score)]
            statistics.append(float(score[ix].mean()))
        interval=dict(block_days=length,replicates=200,confidence=0.95,
                      lower=float(np.quantile(statistics,.025)),upper=float(np.quantile(statistics,.975)),
                      note='方向调整的标准化协动均值区间；未作多重试验校正，非盈利置信度')
    return dict(windows=windows,directional_consistency=sum(x['rank_ic']*direction>0 for x in windows if x['rank_ic'] is not None)/len(windows) if windows else None,
                covariance_interval=interval)


def classify(experiment):
    train=experiment['segments']['train']['metrics']
    valid=experiment['segments']['valid']['metrics']
    direction=experiment['factor'].get('expected_direction',1)
    passed=lambda m:m.get('total_return',-1)>0 and m.get('rank_ic') is not None and m['rank_ic']*direction>0
    stage='computable'
    if passed(train):
        stage='development_passed'
        if experiment.get('research_protocol') == 'isolated-v1' and passed(valid) and experiment['segments']['valid'].get('exposure',{}).get('independent'):
            stage='independent_check_passed'
    return dict(research_stage=stage,stage_rule='净收益>0且方向调整Rank IC>0；初筛而非统计显著性或实盘准入',
                validation_independent=experiment['segments']['valid'].get('exposure',{}).get('independent',False))
