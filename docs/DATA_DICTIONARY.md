# Diccionario / Data dictionary

| Archivo / File | Grano / Grain | Clave / Key |
|---|---|---|
| data/raw/train.csv | Día, tienda, producto / day, store, item | date, store_nbr, item_nbr |
| complete_backtest.csv | Corte y modelo / origin and model | fold, model |
| complete_sku_errors.csv | Corte, modelo, tienda, SKU | fold, model, store_nbr, item_nbr |
| complete_predictions.csv | Fecha, corte, modelo; BEVERAGES tienda 1 | date, fold, model |

Datos sintéticos: 110,624 filas, 60 productos, 6 tiendas, 593 días. El generador omite ventas cero; solo por ese contrato se completa el calendario a 213,480 observaciones. 553 retornos negativos se conservan en origen y se recortan a cero para el objetivo. 17,656 promociones faltantes no se imputan como certezas: no se usan en el modelo revisado.

Synthetic generator contract: omitted rows are zero sales for the complete assortment. This does not justify treating missing real observations as zero. Returns are clipped only for the nonnegative sales proxy, which is not unconstrained demand. Promotion and oil features are excluded.

WMAPE = sum(abs(actual-prediction))/sum(actual). `macro_sku_wmape`: promedio por pareja SKU-tienda con denominador positivo; `scored_pairs` muestra cobertura (359 o 360). No sumar unidades incompatibles entre familias. `beverages_store1_wmape` es una métrica agregada secundaria. En los CSV, 1.1556 significa 115.56%; Tableau guarda porcentajes ×100.

`bias`: mean(prediction-actual), positive means overforecasting. `sigma_error`: sample standard deviation of daily errors in a 15-day fold; not a validated lead-time safety-stock parameter. Actual values repeat across model rows: filter one model or average per date when plotting actuals. Folds 1–4 select the model; fold 5 is final holdout.
