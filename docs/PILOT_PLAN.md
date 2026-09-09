# Piloto de reposición / Replenishment pilot

**Decisión actual / Current decision:** mantener revisión humana y correr LightGBM en sombra. / Retain human review and run LightGBM in shadow mode.

| Etapa / Stage | Evidencia requerida / Required evidence | Responsable propuesto / Proposed owner |
|---|---|---|
| Captura / Capture | SKU, unidad, fecha, ventas, devoluciones, faltantes, stock, pedidos pendientes, vencimiento | Operaciones / Operations |
| Proveedor / Supplier | Lead time observado, MOQ, múltiplos de compra, variabilidad | Compras / Purchasing |
| Sombra / Shadow | 4 semanas, error y sesgo por SKU; comparar baseline sin emitir pedidos automáticos | Analista / Analyst |
| Evaluación / Evaluation | Servicio, merma al costo, inventario medio, segmentación por intermitencia | Analista + operaciones |
| Avance / Gate | Cero fugas temporales, datos completos; mejora consistente sin deteriorar servicio o merma, umbrales acordados antes del piloto | Dueño del proceso / Process owner |

Las 4 semanas son un diseño propuesto, no un piloto ejecutado. Acordar umbrales y costos antes de observar resultados. Estratificar por SKU y condiciones comparables; no atribuir causalidad a un antes/después sin controlar estacionalidad. La fórmula stock objetivo menos posición de inventario solo se aplica después de validar lead time, vida útil y restricciones.

Four weeks is a proposed design, not a completed experiment. Pre-register thresholds and costs; use comparable SKU groups and account for seasonality. Any inventory formula is conditional on validated operational inputs. No measured inventory savings are available.
