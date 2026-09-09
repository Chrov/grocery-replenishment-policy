"""Calendar-complete fixed-origin evaluation on the synthetic catalog.

Missing rows are zero ONLY because generate_synthetic_favorita.py omits zero
sales for an explicitly complete assortment. This rule is not for real data.
"""
from pathlib import Path
import json, hashlib
import numpy as np
import pandas as pd
import lightgbm as lgb

R=Path(__file__).resolve().parents[1];out=R/'outputs';out.mkdir(exist_ok=True)
raw=pd.read_csv(R/'data/raw/train.csv',parse_dates=['date'])
items=pd.read_csv(R/'data/raw/items.csv');stores=pd.read_csv(R/'data/raw/stores.csv')
assert not raw.duplicated(['date','store_nbr','item_nbr']).any()
dates=pd.date_range(raw.date.min(),raw.date.max(),freq='D')
pairs=pd.MultiIndex.from_product([stores.store_nbr,items.item_nbr],names=['store_nbr','item_nbr']).to_frame(index=False)
pairs=pairs.merge(items,on='item_nbr',validate='many_to_one')
wide=raw.assign(y=raw.unit_sales.clip(lower=0)).pivot(index='date',columns=['store_nbr','item_nbr'],values='y')
Y=wide.reindex(index=dates,columns=pd.MultiIndex.from_frame(pairs[['store_nbr','item_nbr']])).fillna(0).to_numpy()
N=len(pairs); features=['store_nbr','item_nbr','perishable','dow','month','payday','lag7','lag14','lag28','mean7','mean28']
def frame(t, history):
    d=dates[t]
    f=pairs[['store_nbr','item_nbr','perishable']].copy()
    f['dow']=d.dayofweek;f['month']=d.month;f['payday']=int(d.day in [15,d.days_in_month])
    for lag in [7,14,28]:f[f'lag{lag}']=history[t-lag]
    for w in [7,28]:f[f'mean{w}']=history[t-w:t].mean(axis=0)
    return f[features]
X=pd.concat([frame(t,Y) for t in range(28,len(dates))],ignore_index=True)
target=Y[28:].ravel()
folds=[];predictions=[];sku=[]
for fold in range(5):
    start=len(dates)-15*(5-fold);end=start+15
    train_count=(start-28)*N
    model=lgb.LGBMRegressor(objective='tweedie',n_estimators=150,num_leaves=15,min_child_samples=40,learning_rate=.05,n_jobs=4,random_state=42,verbosity=-1)
    model.fit(X.iloc[:train_count],target[:train_count],categorical_feature=['store_nbr','item_nbr'])
    history=Y.copy();history[start:]=np.nan
    ml=[]
    for t in range(start,end):
        v=np.maximum(0,model.predict(frame(t,history)))
        history[t]=v;ml.append(v)
    naive=np.array([Y[start-7+(h%7)] for h in range(15)])
    mean=np.array([Y[start-56:start][dates[start-56:start].dayofweek==dates[t].dayofweek].mean(axis=0) for t in range(start,end)])
    for name,p in [('seasonal_naive',naive),('weekday_mean_8w',mean),('lightgbm_recursive',np.array(ml))]:
        actual=Y[start:end];den=actual.sum(axis=0)
        errors=np.divide(np.abs(actual-p).sum(axis=0),den,out=np.full(N,np.nan),where=den>0)
        scope=(pairs.family=='BEVERAGES') & (pairs.store_nbr==1)
        a=actual[:,scope].sum(axis=1);v=p[:,scope].sum(axis=1)
        folds.append(dict(fold=fold+1,split='holdout' if fold==4 else 'validation',origin=str(dates[start-1].date()),model=name,macro_sku_wmape=float(np.nanmean(errors)),beverages_store1_wmape=float(np.abs(a-v).sum()/a.sum()),scored_pairs=int((den>0).sum())))
        for j,row in pairs.iterrows():
            sku.append(dict(fold=fold+1,model=name,store_nbr=int(row.store_nbr),item_nbr=int(row.item_nbr),family=row.family,wmape=float(errors[j]),bias=float((p[:,j]-actual[:,j]).mean()),sigma_error=float((actual[:,j]-p[:,j]).std(ddof=1))))
        for h,t in enumerate(range(start,end)):
            predictions.append(dict(date=str(dates[t].date()),fold=fold+1,model=name,actual=float(a[h]),prediction=float(v[h]),scope='BEVERAGES store 1'))
    print('Fold',fold+1,'completed',flush=True)
f=pd.DataFrame(folds);f.to_csv(out/'complete_backtest.csv',index=False)
pd.DataFrame(predictions).to_csv(out/'complete_predictions.csv',index=False)
pd.DataFrame(sku).to_csv(out/'complete_sku_errors.csv',index=False)
winner=f[f.split=='validation'].groupby('model').macro_sku_wmape.mean().idxmin()
summary={'source':'Synthetic generator seed 42','raw_rows':len(raw),'calendar_rows':int(Y.size),'stores':len(stores),'items':len(items),'series':N,'selected_model':winner,'selection_metric':'mean SKU-store WMAPE across four validation folds; no mixed-unit totals','holdout':f[f.split=='holdout'].to_dict('records'),'raw_sha256':hashlib.sha256((R/'data/raw/train.csv').read_bytes()).hexdigest(),'returns_rows':int((raw.unit_sales<0).sum()),'zero_rule':'Omitted rows are zero only under this synthetic generator contract','model_config':model.get_params()}
(out/'complete_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps(summary,indent=2))
