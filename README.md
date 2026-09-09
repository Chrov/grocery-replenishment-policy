# Grocery replenishment policy

**ES:** Análisis de demanda y diseño de un piloto de reposición con datos sintéticos compatibles con el esquema Favorita. SQL/dbt, Python, validación temporal e insumos para Tableau.

**EN:** Demand analysis and replenishment pilot design using synthetic Favorita-schema data. SQL/dbt, Python, temporal validation and Tableau extracts.

## Resultado revisado / Reviewed result

Cuatro cortes de validación seleccionan la media por día de semana de ocho semanas. Holdout de 15 días: **WMAPE 32,79% vs. 44,89%** del baseline estacional, en BEVERAGES/tienda 1. Es evidencia predictiva agregada en simulación, sin ahorro operativo demostrado.

Four validation origins select the eight-week weekday mean. Final 15-day holdout: **32.79% vs 44.89% WMAPE**, BEVERAGES/store 1. Aggregate synthetic forecast evidence; no demonstrated operating savings.

El resultado anterior de LightGBM se retiró por fuga temporal. La política anterior de 13 artículos queda como ilustración no validada. Consulte [la revisión de decisiones](DECISION_REVIEW.md) para metodología, límites y próximos pasos.

## Reproducir / Reproduce

```bash
python src/review_backtest.py
python -m unittest discover -s tests
```

La comparación revisada utiliza `dashboard/data/demand_daily.csv` y no requiere servicios pagos. Los modelos avanzados requieren reconstruir la base siguiendo [dbt/README.md](dbt/README.md), y ejecutar los notebooks en orden. El notebook de LightGBM ya usa predicción recursiva y no conserva métricas antiguas.

The reviewed benchmark runs locally from the supplied daily extract. Advanced models require rebuilding the source database using the dbt instructions and rerunning notebooks. The revised LightGBM notebook uses recursive predictions and has no stale results.

## Archivos / Files

- `src/forecasting_pipeline.py`: funciones de pronóstico y políticas ilustrativas.
- `outputs/review_backtest.csv`: métricas por corte temporal.
- `outputs/review_predictions.csv`: predicciones y observaciones.
- `dbt/`: modelo de datos, validaciones y guía local.
- `notebooks/`: EDA, modelos y políticas.
- `dashboard/data/`: extractos para BI; respetar `review_status` en resultados heredados.
- `DECISION_REVIEW.md`: decisión, límites y diseño del piloto, ES/EN.
