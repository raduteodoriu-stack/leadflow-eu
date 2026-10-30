-- Reconciliation runs (tools/reconcile.py). The latest one is the dashboard's trust badge:
-- were the numbers balanced against the source when they were produced?
select
    r.*,
    r.run_at = max(r.run_at) over () as is_latest
from {{ ref('stg_reconciliation_runs') }} as r
