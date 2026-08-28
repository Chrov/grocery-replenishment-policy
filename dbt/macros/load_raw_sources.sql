{#
  Bootstrap macro: registers the CSVs in data/raw as views in DuckDB's `raw`
  schema, so the dbt sources (source('raw', ...)) resolve.

  Invoked with `dbt run-operation load_raw_sources`.

  In BigQuery this is NOT needed: the raw_* tables already exist as tables
  loaded from GCS, and source() points to them directly.
#}
{% macro load_raw_sources(raw_dir='../data/raw') %}
  {% set tables = ['train', 'stores', 'items', 'transactions', 'oil', 'holidays_events'] %}

  {% set create_schema %}
    create schema if not exists raw;
  {% endset %}
  {% do run_query(create_schema) %}

  {% for t in tables %}
    {% set sql %}
      create or replace view raw.{{ t }} as
      select * from read_csv_auto('{{ raw_dir }}/{{ t }}.csv', header=true, sample_size=-1);
    {% endset %}
    {% do run_query(sql) %}
    {{ log("Registered view raw." ~ t, info=true) }}
  {% endfor %}
{% endmacro %}
