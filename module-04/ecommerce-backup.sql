--
-- PostgreSQL database dump
--

-- Dumped from database version 16.3 (Debian 16.3-1.pgdg120+1)
-- Dumped by pg_dump version 16.3 (Debian 16.3-1.pgdg120+1)

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

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: products; Type: TABLE; Schema: public; Owner: appuser
--

CREATE TABLE public.products (
    id integer NOT NULL,
    name character varying(100),
    price numeric(10,2)
);


ALTER TABLE public.products OWNER TO appuser;

--
-- Name: products_id_seq; Type: SEQUENCE; Schema: public; Owner: appuser
--

CREATE SEQUENCE public.products_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.products_id_seq OWNER TO appuser;

--
-- Name: products_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: appuser
--

ALTER SEQUENCE public.products_id_seq OWNED BY public.products.id;


--
-- Name: products id; Type: DEFAULT; Schema: public; Owner: appuser
--

ALTER TABLE ONLY public.products ALTER COLUMN id SET DEFAULT nextval('public.products_id_seq'::regclass);


--
-- Data for Name: products; Type: TABLE DATA; Schema: public; Owner: appuser
--

COPY public.products (id, name, price) FROM stdin;
1	Widget A	9.99
2	Widget B	19.99
3	Widget C	29.99
\.


--
-- Name: products_id_seq; Type: SEQUENCE SET; Schema: public; Owner: appuser
--

SELECT pg_catalog.setval('public.products_id_seq', 3, true);


--
-- Name: products products_pkey; Type: CONSTRAINT; Schema: public; Owner: appuser
--

ALTER TABLE ONLY public.products
    ADD CONSTRAINT products_pkey PRIMARY KEY (id);


--
-- PostgreSQL database dump complete
--

