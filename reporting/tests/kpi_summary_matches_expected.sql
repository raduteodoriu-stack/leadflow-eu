-- Every KPI the reporting layer computes for LF-005 equals the answer key
-- (seeds/expected_kpis.csv, from tools/expected_kpis.py). Returns the rows that differ:
-- a value that differs, a value missing on either side, or an extra member in a
-- breakdown the answer key covers. Skipped when var check_expected_kpis is false.
{{ config(severity = 'error') }}

{% if var('check_expected_kpis') %}
with expected as (
    select kpi_id, breakdown, member, numerator, denominator from {{ ref('expected_kpis') }}
),
actual as (
    select s.kpi_id, s.breakdown, s.member, s.numerator, s.denominator
    from {{ ref('kpi_summary') }} as s
    where (s.kpi_id, s.breakdown) in (select distinct kpi_id, breakdown from expected)
)
select
    coalesce(e.kpi_id, a.kpi_id)        as kpi_id,
    coalesce(e.breakdown, a.breakdown)  as breakdown,
    coalesce(e.member, a.member)        as member,
    e.numerator   as expected_numerator,   a.numerator   as actual_numerator,
    e.denominator as expected_denominator, a.denominator as actual_denominator
from expected as e
full outer join actual as a
  on a.kpi_id = e.kpi_id and a.breakdown = e.breakdown and a.member = e.member
where e.kpi_id is null
   or a.kpi_id is null
   or e.numerator is distinct from a.numerator
   or e.denominator is distinct from a.denominator
{% else %}
select 1 as skipped where false
{% endif %}
