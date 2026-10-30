-- Every KPI in the catalogue has at least one value in kpi_summary.
select k.kpi_id, k.kpi_name
from {{ ref('kpi_catalog') }} as k
where not exists (select 1 from {{ ref('kpi_summary') }} as s where s.kpi_id = k.kpi_id)
