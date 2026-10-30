-- One row per calendar day. Working day = Monday to Friday (no public holidays until LF-014).
select
    d::date                                         as date_day,
    to_char(d, 'IYYY-"W"IW')                        as iso_week,
    date_trunc('week', d)::date                     as week_start,
    to_char(d, 'YYYY-MM')                           as year_month,
    extract(isodow from d)::int                     as iso_weekday,
    to_char(d, 'Dy')                                as weekday_name,
    extract(isodow from d) < 6                      as is_working_day
from generate_series('{{ var("calendar_start") }}'::date::timestamp,
                     '{{ var("calendar_end") }}'::date::timestamp,
                     interval '1 day') as d
