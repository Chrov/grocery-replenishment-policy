# Reposición con evidencia / Replenishment evidence

## ES

**Decisión que apoya:** escoger un pronóstico de demanda para un piloto de reposición, con nivel de servicio y costos explícitos. El conjunto es sintético y no permite atribuir resultados a Corporación Favorita.

La revisión detectó fuga temporal en LightGBM: las variables de rezago se calculaban sobre todo el período antes del corte, usando ventas del período futuro. Además, una media móvil podía cruzar límites de producto. El 15,9% WMAPE y la mejora del 65% se retiran como evidencia válida de un pronóstico fijo a 15 días. Las variables de petróleo futuro tampoco están disponibles al emitir el pronóstico. La nueva función recursiva descarta todos los objetivos futuros, usa predicciones propias y mantiene las ventanas dentro de cada SKU. El notebook necesita ejecutarse nuevamente con la base de datos reconstruida; sus resultados anteriores fueron eliminados para evitar confusión.

**Evaluación ejecutada:** con el extracto diario disponible se compararon dos alternativas sobre BEVERAGES, tienda 1. Cuatro cortes temporales de validación eligieron la media del mismo día de semana de las últimas ocho semanas. En los 15 días finales reservados, su WMAPE fue 32,79%, frente a 44,89% de repetir la última semana: mejora relativa de 26,96%. Los modelos reciben exclusivamente historia anterior al corte. Se verificó que no hay fechas faltantes ni repetidas. `outputs/review_backtest.csv` y `review_predictions.csv` permiten revisar cada resultado. Este nivel de agregación no certifica desempeño por SKU.

**Acción:** usar la referencia seleccionada para un piloto en sombra y comparar decisiones con la política vigente, sin emitir compras automáticas. Calibrar errores por SKU y tienda, medir sesgo, cubrir todo el catálogo y validar faltantes y desperdicio. Las políticas anteriores cubren 13 de 60 artículos y están etiquetadas como no validadas; no extrapolar las 233 unidades de buffer al catálogo completo.

La clasificación ABC de este conjunto está basada en unidades, no en ingresos ni margen. El stock de seguridad normal presupone errores sin sesgo y la estructura de dependencia apropiada; el nivel de servicio objetivo no es una tasa de cumplimiento observada. La curva de costos usa supuestos ilustrativos y no prueba un óptimo económico. Para ordenar se requiere posición de inventario (disponible + tránsito − compromisos), vida útil y tamaño mínimo de pedido. Faltan estos insumos para generar órdenes confiables.

## EN

**Decision:** select a demand forecast for a replenishment pilot. All data are synthetic. The legacy LightGBM 15.9% WMAPE / 65% improvement is withdrawn as fixed-origin evidence: future actual sales entered its lag features, a rolling window crossed product boundaries, and future oil values were not known at the origin. The corrected recursive function drops future targets and feeds back predictions within each product. Notebook outputs were cleared and require rerunning after the missing source database is rebuilt.

A completed benchmark uses the available BEVERAGES/store 1 daily extract. Four validation origins select an eight-week weekday mean. On the untouched final 15 days it scores 32.79% WMAPE versus 44.89% for seasonal naive, a 26.96% relative reduction. Predictions and fold metrics are exported. Aggregate performance does not prove SKU performance or savings.

Use this benchmark in a shadow pilot. Measure SKU-store forecast error, bias, stockouts and waste before order automation. The prior policy covers 13/60 items and is explicitly marked unvalidated. ABC measures units, not revenue. Service targets and economic curves are assumptions, not achieved outcomes. Orders require inventory position, shelf life and supplier constraints, which are absent.
