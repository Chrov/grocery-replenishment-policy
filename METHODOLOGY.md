# Metodología / Methodology

## Decisión / Decision

Evaluar si el pronóstico está listo para apoyar reposición por SKU. La conclusión es un piloto en sombra: el error por SKU sigue alto. / Evaluate readiness for SKU replenishment. The conclusion is a shadow pilot because item-level error remains high.

## Validación temporal / Temporal validation

`src/complete_evaluation.py` completa el calendario bajo el contrato sintético, separa 4 ventanas de validación de 15 días y reserva una quinta. LightGBM Tweedie: 150 árboles, 15 hojas, learning_rate=0.05, min_child_samples=40, seed=42. Features: tienda, producto, perecible, calendario, lags 7/14/28, medias 7/28. Cada pronóstico multihorizonte utiliza predicciones previas, nunca observaciones futuras. Se excluyen petróleo y promociones futuros.

Fixed-origin recursive forecasts never consume observations inside the forecast window. Validation selects by mean SKU-store WMAPE; the final fold does not influence selection. The baselines are a repeated last week and the prior eight-week weekday mean. Lags and rolling means are confined to each SKU-store series. No claimed exhaustive hyperparameter optimization.

## Resultado / Result

Holdout macro WMAPE: LightGBM 115.56%, weekday mean 119.01%, seasonal naive 142.76%. Secondary BEVERAGES/store 1: 30.28%, 32.79%, 44.89%. Aggregation hides intermittent item-level errors; do not report the smaller percentage as catalog accuracy. Previous 15.9% / 65% improvement claims were withdrawn for temporal leakage and are superseded by the complete outputs.

## Política / Policy

No existe inventario, lead time observado, vida útil ni costo de faltante validado para convertir error en pedidos o ahorro. La política histórica de 13 artículos es ilustrativa. `docs/PILOT_PLAN.md` define datos y puertas de decisión. No se fabrican órdenes para completar un dashboard.

Inventory position, observed lead time, shelf life and stockout costs are not validated. Historical policy outputs remain illustrative. A prospective pilot must measure service, waste and inventory before any deployment claim.
