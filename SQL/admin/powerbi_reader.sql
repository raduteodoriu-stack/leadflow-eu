-- LeadFlow EU (LF-012): read-only login for Power BI.
--
-- Power BI reads ONLY the reporting schema (dims, facts, kpi_summary), never the
-- engine tables in public or the dbt staging views. Run once per PostgreSQL server,
-- as postgres, connected to the database Power BI reads:
--
--   psql -U postgres -d leadflow_eu_test -f SQL/admin/powerbi_reader.sql
--
-- No password is stored here. Set it afterwards, interactively (it is not echoed):
--
--   psql -U postgres -d leadflow_eu_test -c "\password powerbi_reader"
--
-- dbt rebuilds the reporting tables on every run (as postgres). The default privileges
-- below give powerbi_reader SELECT on each new table automatically.
-- Safe to run again.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'powerbi_reader') THEN
        CREATE ROLE powerbi_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
            CONNECTION LIMIT 20;
    END IF;
END $$;

-- Power BI refreshes several tables at once, one connection each: 5 was too few (the
-- refresh of all 15 tables was cancelled). 20 leaves room while still capping the login.
ALTER ROLE powerbi_reader CONNECTION LIMIT 20;

COMMENT ON ROLE powerbi_reader IS 'LF-012: Power BI Desktop, read-only access to schema reporting';

CREATE SCHEMA IF NOT EXISTS reporting;

REVOKE ALL ON DATABASE leadflow_eu_test FROM powerbi_reader;
GRANT CONNECT ON DATABASE leadflow_eu_test TO powerbi_reader;
REVOKE ALL ON SCHEMA public FROM powerbi_reader;
GRANT USAGE ON SCHEMA reporting TO powerbi_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA reporting TO powerbi_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA reporting
    GRANT SELECT ON TABLES TO powerbi_reader;

-- Never allowed to change anything, even by mistake.
ALTER ROLE powerbi_reader SET default_transaction_read_only = on;

DO $$
BEGIN
    IF has_schema_privilege('powerbi_reader', 'public', 'USAGE')
       AND has_table_privilege('powerbi_reader', 'public.leads', 'SELECT') THEN
        RAISE EXCEPTION 'powerbi_reader can read the engine tables: check grants on public';
    END IF;
    RAISE NOTICE 'powerbi_reader ready in %: SELECT on reporting only.', current_database();
END $$;
