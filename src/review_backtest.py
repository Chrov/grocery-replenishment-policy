"""Fixed-origin benchmarks from the provided synthetic aggregate extract."""
from pathlib import Path
import json
import numpy as np
import pandas as pd

root=Path(__file__).resolve().parents[1]
d=pd.read_csv(root/'dashboard/data/demand_daily.csv',parse_dates=['date'])
s=d[(d.family=='BEVERAGES') & (d.store_nbr==1)].sort_values('date').set_index('date').units_sold
assert s.index.is_unique
assert s.index.equals(pd.date_range(s.index.min(),s.index.max(),freq='D'))
metrics=[]; predictions=[]
for fold in range(5):
    end=len(s)-15*(4-fold); start=end-15
    train=s.iloc[:start]; test=s.iloc[start:end]
    models={'seasonal_naive':np.resize(train.iloc[-7:].to_numpy(),len(test)),
            'weekday_mean_8w':np.array([train.iloc[-56:][train.iloc[-56:].index.dayofweek==t.dayofweek].mean() for t in test.index])}
    for model,pred in models.items():
        metrics.append({'fold':fold+1,'split':'holdout' if fold==4 else 'validation','origin':str(train.index.max().date()),'model':model,'n':len(test),'wmape':float(np.abs(test.to_numpy()-pred).sum()/test.sum())})
        predictions.extend({'date':str(t.date()),'fold':fold+1,'model':model,'actual':float(a),'prediction':float(v)} for t,a,v in zip(test.index,test,pred))
pd.DataFrame(metrics).to_csv(root/'outputs/review_backtest.csv',index=False)
pd.DataFrame(predictions).to_csv(root/'outputs/review_predictions.csv',index=False)
scores=pd.DataFrame(metrics)
winner=scores[scores.split=='validation'].groupby('model').wmape.mean().idxmin()
print(json.dumps({'validation_selected':winner,'holdout':scores[scores.split=='holdout'].to_dict('records')},indent=2))
