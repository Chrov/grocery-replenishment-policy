## Español

### Pronóstico para un piloto de reposición

LightGBM recursivo fue seleccionado mediante validación temporal. Usarlo en un piloto en sombra: el desempeño agregado mejora, pero la demanda intermitente mantiene un error alto por SKU y tienda.

Datos sintéticos con semilla 42. 110.624 registros originales, 60 productos, seis tiendas y 360 series. El calendario completo contiene 213.480 filas entre enero de 2015 y agosto de 2016.

### Método / Method

Cuatro cortes de 15 días seleccionan el modelo por promedio de WMAPE por SKU y tienda. Se reservan los últimos 15 días para evaluación final. Las predicciones recursivas utilizan sus propias salidas y excluyen petróleo y promociones futuros. Las 21 pruebas dbt pasaron.

### Acción propuesta / Proposed action

Comparar en sombra sesgo, faltantes y merma por SKU. Separar demanda intermitente y validar vida útil, posición de inventario y restricciones del proveedor antes de emitir pedidos. Conservar el baseline sencillo como referencia operativa.

### Límites / Limitations

La mejora predictiva no es ahorro de inventario. WMAPE puede superar 100% cuando la demanda es baja e intermitente. Los ceros se reconstruyen solo por el contrato del generador; retornos negativos se tratan como cero para este objetivo. No extrapolar esta regla a datos reales.

## English

### Forecasting for a replenishment pilot

Recursive LightGBM was selected through temporal validation. Use it in a shadow pilot: aggregate performance improves, but intermittent demand leaves substantial SKU-store error.

Synthetic data, seed 42. 110,624 source records, 60 products, six stores and 360 series. The completed calendar contains 213,480 rows from January 2015 to August 2016.

### Método / Method

Four 15-day origins select the model by mean SKU-store WMAPE. The final 15 days remain reserved. Recursive forecasts feed back predictions and exclude future oil and promotion values. All 21 dbt tests passed.

### Acción propuesta / Proposed action

Compare bias, stockouts and waste by SKU in shadow operation. Address intermittent demand and validate shelf life, inventory position and supplier constraints before issuing orders. Keep the simple baseline as an operational reference.

### Límites / Limitations

Forecast improvement is not inventory savings. WMAPE can exceed 100% for low, intermittent demand. Zeros are reconstructed only under the generator contract; negative returns become zero for this target. Do not apply this rule to real data without validation.
