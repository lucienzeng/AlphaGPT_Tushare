"""真实数据/模型全流程验收；仅使用已观察的2024区间，不宣称新的样本外收益。"""
from dataclasses import asdict
from pathlib import Path
import hashlib
import json
import zipfile
import io
import traceback
import pandas as pd
from alphagpt.research.config import load_credentials, DownloadConfig, ExperimentConfig
from alphagpt.research.storage import Store, dumps, now, identifier
from alphagpt.research.jobs import Manager, Context
from alphagpt.research.cli import wait
from alphagpt.data.futures import TushareSource, load_snapshot
from alphagpt.data.quality import validate_dataset, audit
from alphagpt.factor.research import features
from alphagpt.data.curves import build_curve_frame
from alphagpt.research.workflow import export_experiment, version_info


def run():
    load_credentials()
    store=Store()
    key=identifier('improvement_acceptance')
    folder=store.root/'verification'/key
    folder.mkdir(parents=True)
    report=dict(id=key,started=now(),purpose='已观察2024数据的工程验收；不提供新的独立盈利证据',tasks=[],
                limitations=['官方对账导入功能已测试，但本次没有真实官方历史文件，未宣称完成独立来源对账',
                             '历史发布时间与夜盘开盘时段仍需来源确认，使用保守t+2假设',
                             '更早历史、完整期限曲线及库存接入按方案后续阶段处理'])
    old_files=[p for category in ['snapshots','experiments','curves'] for p in (store.root/category).glob('**/*') if p.is_file()]
    original={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in old_files}
    manager=None
    try:
        manager=Manager(store)
        snapshots=store.list('snapshots')
        snap=next(s for s in snapshots if s['start'].startswith('2024') and s['end']=='2024-12-31')
        data=load_snapshot(store,snap['id'])
        report['snapshot']=snap['id']
        report['quality']=validate_dataset(data)
        report['quality_check']=audit(store,snap['id'],report['quality'])
        for position in [150,len(data['mapping'])-30]:
            cutoff=data['mapping'].trade_date.iloc[position]
            prefix={k:v.loc[v.trade_date.le(cutoff)].copy() if 'trade_date' in v else v.copy() for k,v in data.items()}
            full_features,_=features(data,version='futures-v2')
            short_features,_=features(prefix,version='futures-v2')
            pd.testing.assert_frame_equal(full_features.loc[:cutoff],short_features)
            pd.testing.assert_frame_equal(build_curve_frame(data).iloc[:position+1].reset_index(drop=True),build_curve_frame(prefix))
        report['real_prefix_checks']=2
        sync=manager.submit('sync',asdict(DownloadConfig(snap['start'],snap['end'],metadata_ttl_hours=720)))
        report['tasks'].append(sync)
        report['sync']=wait(store,sync)
        assert report['sync']['requests']==0,'完整历史应复用现有覆盖，不重复下载'
        # 单次小范围来源复核，显式记日志；不覆盖旧快照或伪称独立数据源。
        context=Context(store,sync)
        probe=data['bars'].loc[data['bars'].trade_date.between('2024-06-03','2024-06-07')].copy()
        symbol=probe.ts_code.iloc[0]
        probe=probe.loc[probe.ts_code.eq(symbol)]
        source=TushareSource(DownloadConfig(),context)
        from alphagpt.data.futures import normalize
        refreshed=normalize(source.request('fut_daily',ts_code=symbol,start_date='20240603',end_date='20240607'))
        joined=probe.merge(refreshed,on=['ts_code','trade_date'],suffixes=('_old','_new'),how='outer',indicator=True)
        assert joined._merge.eq('both').all(),'来源复核返回日期不一致'
        diffs=[]
        for field in ['open','high','low','close','settle','vol','oi']:
            if not joined[field+'_old'].equals(joined[field+'_new']):
                bad=joined[field+'_old'].ne(joined[field+'_new'])
                if bad.any():diffs.append(field)
        report['tushare_probe']=dict(symbol=symbol,rows=len(refreshed),requests=source.calls,different_fields=diffs,
                                     note='同源修订复查，不是官方独立对账')
        assert not diffs,'来源与冻结快照出现差异，需人工核对'
        old=next(x['config'] for x in reversed(store.list('runs')) if x['config']['snapshot']==snap['id'])
        cfg=ExperimentConfig.from_dict(old)
        cfg.feature_version='futures-v2';cfg.research_protocol='isolated-v1';cfg.use_templates=True
        cfg.rounds=2;cfg.count=2;cfg.max_calls=5;cfg.token_budget=500000
        cfg.random_controls=3;cfg.candidate_budget=30
        cfg.validate()
        mine=manager.submit('mine',asdict(cfg));report['tasks'].append(mine)
        print('真实挖掘任务：'+mine,flush=True)
        report['mining']=wait(store,mine)
        factors=[x for x in store.list('factors') if x.get('task')==mine]
        report['factors']=[{k:x.get(k) for k in ['id','name_zh','source','status','research_stage','reason','validation_independent']} for x in factors]
        calls=[x for x in store.list('calls') if x['task']==mine]
        assert len(calls)>=2 and all('valid_metrics' not in x['prompt'] for x in calls)
        report['model_usage']=dict(calls=len(calls),tokens=sum(x.get('total_tokens',0) or 0 for x in calls),
                                   actual_models=sorted(set(x.get('actual_model','unknown') for x in calls)))
        chosen=next(x for x in factors if x.get('round',0)>0 and x.get('experiment')) if any(x.get('round',0)>0 and x.get('experiment') for x in factors) else next(x for x in factors if x.get('experiment'))
        experiment=chosen['experiment']
        bt=asdict(cfg.backtest);bt['fee']*=2
        retest=manager.submit('retest',dict(experiment=experiment,backtest=bt));report['tasks'].append(retest)
        report['retest']=wait(store,retest)
        final=manager.submit('final_test',dict(experiment=experiment));report['tasks'].append(final)
        report['final_test']=wait(store,final)
        access=store.get('test_access',final)
        assert not access['independent'],'旧2024测试区必须识别为已观察重测'
        report['holdout_reuse_detected']=True
        payload=export_experiment(store,experiment)
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            assert {'manifest.json','研究计划.json','task_log.jsonl'}.issubset(z.namelist())
        (folder/'完整实验.zip').write_bytes(payload)
        report['old_artifacts_unchanged']=all(p.exists() and hashlib.sha256(p.read_bytes()).hexdigest()==original[str(p)] for p in old_files)
        assert report['old_artifacts_unchanged']
        with store.connect() as db:report['sqlite_check']=db.execute('PRAGMA quick_check').fetchone()[0]
        assert report['sqlite_check']=='ok'
        report['source_version']=version_info()
        report['status']='passed'
    except Exception as e:
        report.update(status='failed',error=str(e),traceback=traceback.format_exc())
        raise
    finally:
        if manager:manager.close()
        report['finished']=now()
        (folder/'report.json').write_text(dumps(report)+'\n',encoding='utf-8')
        (store.root/'verification/improvements_latest.json').write_text(dumps(report)+'\n',encoding='utf-8')
        print(dumps(report),flush=True)
    return folder


if __name__=='__main__':
    print('验收目录：'+str(run()),flush=True)
