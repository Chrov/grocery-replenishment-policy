import unittest
import pandas as pd
import numpy as np
from src.forecasting_pipeline import build_features, recursive_predictions

class LagModel:
    def predict(self, frame):return frame['lag_7'].to_numpy()

class ReviewTests(unittest.TestCase):
    def panel(self):
        return pd.DataFrame([{'date':d,'item_nbr':i,'y':float(i*100+j)} for i in [1,2] for j,d in enumerate(pd.date_range('2025-01-01',periods=60))])

    def test_groups_do_not_mix(self):
        result=build_features(self.panel(),('item_nbr',),'y')
        first=result[result.item_nbr==2].iloc[0]
        self.assertTrue(pd.isna(first.roll_mean_7))

    def test_predictions_ignore_future_actuals(self):
        p=self.panel(); h=p[p.date<'2025-02-15'];f=p[p.date>='2025-02-15']
        a=recursive_predictions(LagModel(),h,f,['lag_7'])
        f=f.copy();f['y']=999999
        b=recursive_predictions(LagModel(),h,f,['lag_7'])
        np.testing.assert_array_equal(a.pred,b.pred)

    def test_missing_calendar_rejected(self):
        with self.assertRaises(ValueError):build_features(self.panel().drop(index=5),('item_nbr',),'y')
