-- 산업 스냅샷: agent_reports 는 공용 테이블이라 스코프 DELETE 만 한다.
DELETE FROM public.agent_reports WHERE agent_type = 'industry';
TRUNCATE public.industry_reports;

--
-- PostgreSQL database dump
--

\restrict KE1qt3bzQjJTBhy8lrHwhBhNsRE1hraE2alykzDYyhDEnMnOYTOXyYIsditiNnA

-- Dumped from database version 16.14 (Debian 16.14-1.pgdg12+1)
-- Dumped by pg_dump version 16.14 (Debian 16.14-1.pgdg12+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Data for Name: industry_reports; Type: TABLE DATA; Schema: public; Owner: verith
--

COPY public.industry_reports (id, request_id, client_session_id, question, answer_text, data_status, trace_id, as_of, created_at, input_payload, output_payload, report_id, question_type, status, payload, schema_version, error_message, updated_at) FROM stdin;
\.


--
-- PostgreSQL database dump complete
--

\unrestrict KE1qt3bzQjJTBhy8lrHwhBhNsRE1hraE2alykzDYyhDEnMnOYTOXyYIsditiNnA


COPY public.agent_reports (id, agent_type, agent_report_id, request_id, client_session_id, owner_user_id, owner_session_id, stock_code, stock_name, question, answer_text, data_status, trace_id, as_of, created_at, summary) FROM stdin;
\.
