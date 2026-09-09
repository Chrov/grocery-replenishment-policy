# Reproducir / Reproduce

Crear un entorno Python aislado. / Use an isolated Python environment.

```bash
pip install -r requirements-reviewed.txt
python data/generate_synthetic_favorita.py --scale mvp
python src/complete_evaluation.py
python -m unittest discover -s tests
cd dbt
dbt run-operation load_raw_sources --profiles-dir .
dbt build --profiles-dir .
```

Semilla 42. `complete_summary.json` registra hash y selección; `complete_backtest.csv` contiene los 15 resultados. La evaluación usa directamente los CSV limpios en memoria y no depende de dbt; el warehouse es una capa SQL adicional con 11 modelos y 21 pruebas. Ver `dbt/README.md`. El comando requiere varios minutos y escribe outputs. La política histórica y los notebooks antiguos no son el flujo vigente.

Seed 42. The complete evaluation is the canonical modeling entry point; dbt is a separately verified warehouse layer. Five 15-day origins compare three models; only four origins select the winner. Published Tableau contains the reviewed snapshot; open the .twbx locally. Updating source CSVs does not automatically rebuild the packaged extracts. The reviewed dashboard is published on Tableau Public; see the link in README.md. Publishing later revisions requires the owner account.
