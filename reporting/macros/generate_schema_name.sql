{#
  Schema names: the target schema (`reporting`) for the marts, and `reporting_<name>`
  for the rest (`reporting_staging`, `reporting_reference`). This is dbt's default
  behaviour, written out so the naming is explicit and stable.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ target.schema }}_{{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
