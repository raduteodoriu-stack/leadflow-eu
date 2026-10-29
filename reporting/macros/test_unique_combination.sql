{#
  Generic test: no two rows share the same values in `columns` (nulls compared as equal).
  Written here so the project needs no packages.
#}
{% test unique_combination(model, columns) %}
select {{ columns | join(', ') }}, count(*) as n
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1
{% endtest %}
