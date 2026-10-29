{# The reporting moment (var as_of) as a timestamptz literal. #}
{% macro as_of() -%}
    '{{ var("as_of") }}'::timestamptz
{%- endmacro %}

{# A timestamptz as a calendar date in Madrid (the business time zone). #}
{% macro madrid_date(column) -%}
    ({{ column }} AT TIME ZONE 'Europe/Madrid')::date
{%- endmacro %}
