-- One row per lead (contact). No usable country is shown as 'unknown'.
select
    lead_id,
    company_id,
    crm_contact_id,
    normalised_email,
    coalesce(business_country_code, 'unknown') as country_code,
    relationship_type,
    first_contact_at,
    created_at,
    {{ madrid_date('created_at') }}           as created_date
from {{ source('leadflow', 'leads') }}
