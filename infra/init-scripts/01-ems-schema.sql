-- EMS Database Schema
-- This script initializes the ems database with required tables and functions

-- Create IIF function (SQL equivalent of IF/THEN/ELSE)
CREATE OR REPLACE FUNCTION IIF(
    condition boolean,       -- IF condition
    true_result anyelement,  -- THEN
    false_result anyelement  -- ELSE
) RETURNS anyelement AS $f$
  SELECT CASE WHEN condition THEN true_result ELSE false_result END
$f$ LANGUAGE SQL IMMUTABLE;

-- Create main_stream table
CREATE TABLE IF NOT EXISTS public.main_stream
(
    datetime timestamp without time zone NOT NULL,
    service smallint,
    unit smallint NOT NULL,
    unit_category smallint,
    unit_parking_station smallint,
    status smallint,
    availability smallint,
    latitude1 numeric(9,7),
    longitude1 numeric(9,7),
    latitude2 numeric(9,7),
    longitude2 numeric(9,7),
    intervention integer,
    intervention_category smallint
);

-- Create index on datetime for efficient time-based queries
CREATE INDEX IF NOT EXISTS idx_main_stream_datetime
    ON public.main_stream(datetime);
