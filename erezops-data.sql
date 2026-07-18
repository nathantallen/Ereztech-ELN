--
-- PostgreSQL database dump
--

\restrict DbulTAF5na2uTH9EVHa3hkGQGPOb3JkFqjn0KtZrYlVpJtGGF7YtWbrrSf2r9EC

-- Dumped from database version 16.14
-- Dumped by pg_dump version 16.14

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

ALTER TABLE IF EXISTS ONLY public.stage_links DROP CONSTRAINT IF EXISTS stage_links_stage_id_fkey;
ALTER TABLE IF EXISTS ONLY public.stage_approvals DROP CONSTRAINT IF EXISTS stage_approvals_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.stage_approvals DROP CONSTRAINT IF EXISTS stage_approvals_stage_id_fkey;
ALTER TABLE IF EXISTS ONLY public.run_stages DROP CONSTRAINT IF EXISTS run_stages_run_id_fkey;
ALTER TABLE IF EXISTS ONLY public.reactor_attributes DROP CONSTRAINT IF EXISTS reactor_attributes_reactor_id_fkey;
ALTER TABLE IF EXISTS ONLY public.rd_projects DROP CONSTRAINT IF EXISTS rd_projects_researcher_id_fkey;
ALTER TABLE IF EXISTS ONLY public.project_approvals DROP CONSTRAINT IF EXISTS project_approvals_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.project_approvals DROP CONSTRAINT IF EXISTS project_approvals_project_id_fkey;
ALTER TABLE IF EXISTS ONLY public.production_runs DROP CONSTRAINT IF EXISTS production_runs_reactor_id_fkey;
ALTER TABLE IF EXISTS ONLY public.production_runs DROP CONSTRAINT IF EXISTS production_runs_intermediate_for_id_fkey;
ALTER TABLE IF EXISTS ONLY public.deliverables DROP CONSTRAINT IF EXISTS deliverables_project_id_fkey;
ALTER TABLE IF EXISTS ONLY public.users DROP CONSTRAINT IF EXISTS users_username_key;
ALTER TABLE IF EXISTS ONLY public.users DROP CONSTRAINT IF EXISTS users_pkey;
ALTER TABLE IF EXISTS ONLY public.stage_links DROP CONSTRAINT IF EXISTS stage_links_pkey;
ALTER TABLE IF EXISTS ONLY public.stage_approvals DROP CONSTRAINT IF EXISTS stage_approvals_pkey;
ALTER TABLE IF EXISTS ONLY public.run_statuses DROP CONSTRAINT IF EXISTS run_statuses_pkey;
ALTER TABLE IF EXISTS ONLY public.run_statuses DROP CONSTRAINT IF EXISTS run_statuses_name_key;
ALTER TABLE IF EXISTS ONLY public.run_stages DROP CONSTRAINT IF EXISTS run_stages_pkey;
ALTER TABLE IF EXISTS ONLY public.roles DROP CONSTRAINT IF EXISTS roles_pkey;
ALTER TABLE IF EXISTS ONLY public.roles DROP CONSTRAINT IF EXISTS roles_name_key;
ALTER TABLE IF EXISTS ONLY public.reactors DROP CONSTRAINT IF EXISTS reactors_pkey;
ALTER TABLE IF EXISTS ONLY public.reactors DROP CONSTRAINT IF EXISTS reactors_name_key;
ALTER TABLE IF EXISTS ONLY public.reactor_attributes DROP CONSTRAINT IF EXISTS reactor_attributes_pkey;
ALTER TABLE IF EXISTS ONLY public.rd_projects DROP CONSTRAINT IF EXISTS rd_projects_pkey;
ALTER TABLE IF EXISTS ONLY public.project_approvals DROP CONSTRAINT IF EXISTS project_approvals_pkey;
ALTER TABLE IF EXISTS ONLY public.production_runs DROP CONSTRAINT IF EXISTS production_runs_pkey;
ALTER TABLE IF EXISTS ONLY public.document_roots DROP CONSTRAINT IF EXISTS document_roots_pkey;
ALTER TABLE IF EXISTS ONLY public.document_roots DROP CONSTRAINT IF EXISTS document_roots_name_key;
ALTER TABLE IF EXISTS ONLY public.deliverables DROP CONSTRAINT IF EXISTS deliverables_pkey;
ALTER TABLE IF EXISTS public.users ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS public.stage_links ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS public.stage_approvals ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS public.run_statuses ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS public.run_stages ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS public.roles ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS public.reactors ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS public.reactor_attributes ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS public.rd_projects ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS public.project_approvals ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS public.production_runs ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS public.document_roots ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS public.deliverables ALTER COLUMN id DROP DEFAULT;
DROP SEQUENCE IF EXISTS public.users_id_seq;
DROP TABLE IF EXISTS public.users;
DROP SEQUENCE IF EXISTS public.stage_links_id_seq;
DROP TABLE IF EXISTS public.stage_links;
DROP SEQUENCE IF EXISTS public.stage_approvals_id_seq;
DROP TABLE IF EXISTS public.stage_approvals;
DROP SEQUENCE IF EXISTS public.run_statuses_id_seq;
DROP TABLE IF EXISTS public.run_statuses;
DROP SEQUENCE IF EXISTS public.run_stages_id_seq;
DROP TABLE IF EXISTS public.run_stages;
DROP SEQUENCE IF EXISTS public.roles_id_seq;
DROP TABLE IF EXISTS public.roles;
DROP SEQUENCE IF EXISTS public.reactors_id_seq;
DROP TABLE IF EXISTS public.reactors;
DROP SEQUENCE IF EXISTS public.reactor_attributes_id_seq;
DROP TABLE IF EXISTS public.reactor_attributes;
DROP SEQUENCE IF EXISTS public.rd_projects_id_seq;
DROP TABLE IF EXISTS public.rd_projects;
DROP SEQUENCE IF EXISTS public.project_approvals_id_seq;
DROP TABLE IF EXISTS public.project_approvals;
DROP SEQUENCE IF EXISTS public.production_runs_id_seq;
DROP TABLE IF EXISTS public.production_runs;
DROP SEQUENCE IF EXISTS public.document_roots_id_seq;
DROP TABLE IF EXISTS public.document_roots;
DROP SEQUENCE IF EXISTS public.deliverables_id_seq;
DROP TABLE IF EXISTS public.deliverables;
SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: deliverables; Type: TABLE; Schema: public; Owner: erezops
--

CREATE TABLE public.deliverables (
    id integer NOT NULL,
    project_id integer NOT NULL,
    name character varying(200) NOT NULL,
    status character varying(30) NOT NULL,
    due_date date,
    link_url text
);


ALTER TABLE public.deliverables OWNER TO erezops;

--
-- Name: deliverables_id_seq; Type: SEQUENCE; Schema: public; Owner: erezops
--

CREATE SEQUENCE public.deliverables_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.deliverables_id_seq OWNER TO erezops;

--
-- Name: deliverables_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: erezops
--

ALTER SEQUENCE public.deliverables_id_seq OWNED BY public.deliverables.id;


--
-- Name: document_roots; Type: TABLE; Schema: public; Owner: erezops
--

CREATE TABLE public.document_roots (
    id integer NOT NULL,
    name character varying(120) NOT NULL,
    container_path text NOT NULL,
    link_prefix text
);


ALTER TABLE public.document_roots OWNER TO erezops;

--
-- Name: document_roots_id_seq; Type: SEQUENCE; Schema: public; Owner: erezops
--

CREATE SEQUENCE public.document_roots_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.document_roots_id_seq OWNER TO erezops;

--
-- Name: document_roots_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: erezops
--

ALTER SEQUENCE public.document_roots_id_seq OWNED BY public.document_roots.id;


--
-- Name: production_runs; Type: TABLE; Schema: public; Owner: erezops
--

CREATE TABLE public.production_runs (
    id integer NOT NULL,
    product character varying(160) NOT NULL,
    batch_number character varying(80),
    reactor_id integer NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    status character varying(60) NOT NULL,
    notes text,
    intermediate_for_id integer
);


ALTER TABLE public.production_runs OWNER TO erezops;

--
-- Name: production_runs_id_seq; Type: SEQUENCE; Schema: public; Owner: erezops
--

CREATE SEQUENCE public.production_runs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.production_runs_id_seq OWNER TO erezops;

--
-- Name: production_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: erezops
--

ALTER SEQUENCE public.production_runs_id_seq OWNED BY public.production_runs.id;


--
-- Name: project_approvals; Type: TABLE; Schema: public; Owner: erezops
--

CREATE TABLE public.project_approvals (
    id integer NOT NULL,
    project_id integer NOT NULL,
    aspect character varying(60) NOT NULL,
    user_id integer NOT NULL,
    role character varying(40) NOT NULL,
    status character varying(20) NOT NULL,
    comment text,
    created_at timestamp without time zone NOT NULL
);


ALTER TABLE public.project_approvals OWNER TO erezops;

--
-- Name: project_approvals_id_seq; Type: SEQUENCE; Schema: public; Owner: erezops
--

CREATE SEQUENCE public.project_approvals_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.project_approvals_id_seq OWNER TO erezops;

--
-- Name: project_approvals_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: erezops
--

ALTER SEQUENCE public.project_approvals_id_seq OWNED BY public.project_approvals.id;


--
-- Name: rd_projects; Type: TABLE; Schema: public; Owner: erezops
--

CREATE TABLE public.rd_projects (
    id integer NOT NULL,
    name character varying(160) NOT NULL,
    customer character varying(160),
    researcher_id integer,
    status character varying(30) NOT NULL,
    description text,
    start_date date,
    due_date date,
    folder_url text,
    final_procedure_url text,
    final_qc_url text
);


ALTER TABLE public.rd_projects OWNER TO erezops;

--
-- Name: rd_projects_id_seq; Type: SEQUENCE; Schema: public; Owner: erezops
--

CREATE SEQUENCE public.rd_projects_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.rd_projects_id_seq OWNER TO erezops;

--
-- Name: rd_projects_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: erezops
--

ALTER SEQUENCE public.rd_projects_id_seq OWNED BY public.rd_projects.id;


--
-- Name: reactor_attributes; Type: TABLE; Schema: public; Owner: erezops
--

CREATE TABLE public.reactor_attributes (
    id integer NOT NULL,
    reactor_id integer NOT NULL,
    name character varying(80) NOT NULL,
    value character varying(200) NOT NULL
);


ALTER TABLE public.reactor_attributes OWNER TO erezops;

--
-- Name: reactor_attributes_id_seq; Type: SEQUENCE; Schema: public; Owner: erezops
--

CREATE SEQUENCE public.reactor_attributes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.reactor_attributes_id_seq OWNER TO erezops;

--
-- Name: reactor_attributes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: erezops
--

ALTER SEQUENCE public.reactor_attributes_id_seq OWNED BY public.reactor_attributes.id;


--
-- Name: reactors; Type: TABLE; Schema: public; Owner: erezops
--

CREATE TABLE public.reactors (
    id integer NOT NULL,
    name character varying(80) NOT NULL,
    description text,
    color character varying(9),
    is_active boolean NOT NULL
);


ALTER TABLE public.reactors OWNER TO erezops;

--
-- Name: reactors_id_seq; Type: SEQUENCE; Schema: public; Owner: erezops
--

CREATE SEQUENCE public.reactors_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.reactors_id_seq OWNER TO erezops;

--
-- Name: reactors_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: erezops
--

ALTER SEQUENCE public.reactors_id_seq OWNED BY public.reactors.id;


--
-- Name: roles; Type: TABLE; Schema: public; Owner: erezops
--

CREATE TABLE public.roles (
    id integer NOT NULL,
    name character varying(60) NOT NULL,
    color character varying(9) NOT NULL,
    "position" integer,
    manage_users boolean NOT NULL,
    edit_production boolean NOT NULL,
    edit_rd_all boolean NOT NULL,
    edit_rd_own boolean NOT NULL
);


ALTER TABLE public.roles OWNER TO erezops;

--
-- Name: roles_id_seq; Type: SEQUENCE; Schema: public; Owner: erezops
--

CREATE SEQUENCE public.roles_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.roles_id_seq OWNER TO erezops;

--
-- Name: roles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: erezops
--

ALTER SEQUENCE public.roles_id_seq OWNED BY public.roles.id;


--
-- Name: run_stages; Type: TABLE; Schema: public; Owner: erezops
--

CREATE TABLE public.run_stages (
    id integer NOT NULL,
    run_id integer NOT NULL,
    key character varying(40) NOT NULL,
    name character varying(120) NOT NULL,
    "position" integer,
    notes text
);


ALTER TABLE public.run_stages OWNER TO erezops;

--
-- Name: run_stages_id_seq; Type: SEQUENCE; Schema: public; Owner: erezops
--

CREATE SEQUENCE public.run_stages_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.run_stages_id_seq OWNER TO erezops;

--
-- Name: run_stages_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: erezops
--

ALTER SEQUENCE public.run_stages_id_seq OWNED BY public.run_stages.id;


--
-- Name: run_statuses; Type: TABLE; Schema: public; Owner: erezops
--

CREATE TABLE public.run_statuses (
    id integer NOT NULL,
    name character varying(60) NOT NULL,
    color character varying(9) NOT NULL,
    "position" integer
);


ALTER TABLE public.run_statuses OWNER TO erezops;

--
-- Name: run_statuses_id_seq; Type: SEQUENCE; Schema: public; Owner: erezops
--

CREATE SEQUENCE public.run_statuses_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.run_statuses_id_seq OWNER TO erezops;

--
-- Name: run_statuses_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: erezops
--

ALTER SEQUENCE public.run_statuses_id_seq OWNED BY public.run_statuses.id;


--
-- Name: stage_approvals; Type: TABLE; Schema: public; Owner: erezops
--

CREATE TABLE public.stage_approvals (
    id integer NOT NULL,
    stage_id integer NOT NULL,
    user_id integer NOT NULL,
    role character varying(40) NOT NULL,
    status character varying(20) NOT NULL,
    comment text,
    created_at timestamp without time zone NOT NULL
);


ALTER TABLE public.stage_approvals OWNER TO erezops;

--
-- Name: stage_approvals_id_seq; Type: SEQUENCE; Schema: public; Owner: erezops
--

CREATE SEQUENCE public.stage_approvals_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.stage_approvals_id_seq OWNER TO erezops;

--
-- Name: stage_approvals_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: erezops
--

ALTER SEQUENCE public.stage_approvals_id_seq OWNED BY public.stage_approvals.id;


--
-- Name: stage_links; Type: TABLE; Schema: public; Owner: erezops
--

CREATE TABLE public.stage_links (
    id integer NOT NULL,
    stage_id integer NOT NULL,
    label character varying(160) NOT NULL,
    url text NOT NULL
);


ALTER TABLE public.stage_links OWNER TO erezops;

--
-- Name: stage_links_id_seq; Type: SEQUENCE; Schema: public; Owner: erezops
--

CREATE SEQUENCE public.stage_links_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.stage_links_id_seq OWNER TO erezops;

--
-- Name: stage_links_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: erezops
--

ALTER SEQUENCE public.stage_links_id_seq OWNED BY public.stage_links.id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: erezops
--

CREATE TABLE public.users (
    id integer NOT NULL,
    username character varying(80) NOT NULL,
    full_name character varying(120) NOT NULL,
    role character varying(40) NOT NULL,
    password_hash character varying(256) NOT NULL,
    is_active_user boolean NOT NULL
);


ALTER TABLE public.users OWNER TO erezops;

--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: erezops
--

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.users_id_seq OWNER TO erezops;

--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: erezops
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: deliverables id; Type: DEFAULT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.deliverables ALTER COLUMN id SET DEFAULT nextval('public.deliverables_id_seq'::regclass);


--
-- Name: document_roots id; Type: DEFAULT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.document_roots ALTER COLUMN id SET DEFAULT nextval('public.document_roots_id_seq'::regclass);


--
-- Name: production_runs id; Type: DEFAULT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.production_runs ALTER COLUMN id SET DEFAULT nextval('public.production_runs_id_seq'::regclass);


--
-- Name: project_approvals id; Type: DEFAULT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.project_approvals ALTER COLUMN id SET DEFAULT nextval('public.project_approvals_id_seq'::regclass);


--
-- Name: rd_projects id; Type: DEFAULT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.rd_projects ALTER COLUMN id SET DEFAULT nextval('public.rd_projects_id_seq'::regclass);


--
-- Name: reactor_attributes id; Type: DEFAULT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.reactor_attributes ALTER COLUMN id SET DEFAULT nextval('public.reactor_attributes_id_seq'::regclass);


--
-- Name: reactors id; Type: DEFAULT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.reactors ALTER COLUMN id SET DEFAULT nextval('public.reactors_id_seq'::regclass);


--
-- Name: roles id; Type: DEFAULT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.roles ALTER COLUMN id SET DEFAULT nextval('public.roles_id_seq'::regclass);


--
-- Name: run_stages id; Type: DEFAULT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.run_stages ALTER COLUMN id SET DEFAULT nextval('public.run_stages_id_seq'::regclass);


--
-- Name: run_statuses id; Type: DEFAULT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.run_statuses ALTER COLUMN id SET DEFAULT nextval('public.run_statuses_id_seq'::regclass);


--
-- Name: stage_approvals id; Type: DEFAULT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.stage_approvals ALTER COLUMN id SET DEFAULT nextval('public.stage_approvals_id_seq'::regclass);


--
-- Name: stage_links id; Type: DEFAULT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.stage_links ALTER COLUMN id SET DEFAULT nextval('public.stage_links_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Data for Name: deliverables; Type: TABLE DATA; Schema: public; Owner: erezops
--

COPY public.deliverables (id, project_id, name, status, due_date, link_url) FROM stdin;
1	1	Feasibility report	Delivered	2026-06-29	https://ereztech.sharepoint.com/sites/RD/Projects/Zr-ALD/feasibility.docx
2	1	100 g sample lot	In Progress	2026-07-29	
\.


--
-- Data for Name: document_roots; Type: TABLE DATA; Schema: public; Owner: erezops
--

COPY public.document_roots (id, name, container_path, link_prefix) FROM stdin;
1	Shares	/shares	
\.


--
-- Data for Name: production_runs; Type: TABLE DATA; Schema: public; Owner: erezops
--

COPY public.production_runs (id, product, batch_number, reactor_id, start_date, end_date, status, notes, intermediate_for_id) FROM stdin;
2	TDMAT — Tetrakis(dimethylamido)titanium	B-2607-02	2	2026-07-05	2026-07-10	In Progress		\N
3	TEB — Triethylborane	B-2607-03	3	2026-07-08	2026-07-11	Planned		\N
4	DEZ — Diethylzinc	B-2607-04	1	2026-07-13	2026-07-18	Planned		\N
1	Lithium Dimethylamide	B-2607-01	1	2026-06-29	2026-07-03	Complete		\N
\.


--
-- Data for Name: project_approvals; Type: TABLE DATA; Schema: public; Owner: erezops
--

COPY public.project_approvals (id, project_id, aspect, user_id, role, status, comment, created_at) FROM stdin;
\.


--
-- Data for Name: rd_projects; Type: TABLE DATA; Schema: public; Owner: erezops
--

COPY public.rd_projects (id, name, customer, researcher_id, status, description, start_date, due_date, folder_url, final_procedure_url, final_qc_url) FROM stdin;
1	Novel Zr precursor for ALD	Acme Semiconductor	5	Active	Route scouting and scale-up of a zirconium amide precursor.	2026-06-09	2026-09-07	https://ereztech.sharepoint.com/sites/RD/Projects/Zr-ALD		
\.


--
-- Data for Name: reactor_attributes; Type: TABLE DATA; Schema: public; Owner: erezops
--

COPY public.reactor_attributes (id, reactor_id, name, value) FROM stdin;
1	1	Capacity	500 L
2	1	Material	Glass-lined steel
3	1	Max Temp	200 °C
4	2	Capacity	1000 L
5	2	Material	Hastelloy C-276
6	2	Max Pressure	6 bar
7	3	Capacity	100 L
8	3	Material	316L SS
9	3	Jacket	-20 to 180 °C
\.


--
-- Data for Name: reactors; Type: TABLE DATA; Schema: public; Owner: erezops
--

COPY public.reactors (id, name, description, color, is_active) FROM stdin;
1	R-101	Glass-lined batch reactor	#7a00df	t
2	R-102	Hastelloy C-276 reactor with distillation head	#F7941E	t
3	R-201	Stainless kilo-lab reactor	#0693e3	t
\.


--
-- Data for Name: roles; Type: TABLE DATA; Schema: public; Owner: erezops
--

COPY public.roles (id, name, color, "position", manage_users, edit_production, edit_rd_all, edit_rd_own) FROM stdin;
1	Admin	#0F0037	0	t	t	t	f
2	Production Manager	#F7941E	1	f	t	f	f
3	QC Manager	#0693e3	2	f	f	f	f
4	R&D Director	#7a00df	3	f	f	t	f
5	Researcher	#BD6FD5	4	f	f	f	t
6	Operator	#8a8797	5	f	f	f	f
9	Owner	#7a00df	8	t	t	t	t
10	Procurement	#669c35	9	f	t	t	t
11	Commercial	#77bb41	10	f	f	f	f
12	Finance	#77bb41	11	f	f	f	f
8	Plant Engineer	#e32400	7	f	t	t	t
7	Engineering Manager	#e32400	6	f	t	f	f
13	Facilities	#0056d6	12	t	t	t	t
\.


--
-- Data for Name: run_stages; Type: TABLE DATA; Schema: public; Owner: erezops
--

COPY public.run_stages (id, run_id, key, name, "position", notes) FROM stdin;
1	1	raw_materials	Raw Materials — Ordering & Incoming QC	0	
2	1	procedure	Procedure (R&D)	1	
3	1	process_data	Process Data & Run Results	2	
4	1	qc	QC Results	3	
5	1	inventory	Final Material → Inventory	4	
6	2	raw_materials	Raw Materials — Ordering & Incoming QC	0	
7	2	procedure	Procedure (R&D)	1	
8	2	process_data	Process Data & Run Results	2	
9	2	qc	QC Results	3	
10	2	inventory	Final Material → Inventory	4	
11	3	raw_materials	Raw Materials — Ordering & Incoming QC	0	
12	3	procedure	Procedure (R&D)	1	
13	3	process_data	Process Data & Run Results	2	
14	3	qc	QC Results	3	
15	3	inventory	Final Material → Inventory	4	
16	4	raw_materials	Raw Materials — Ordering & Incoming QC	0	
17	4	procedure	Procedure (R&D)	1	
18	4	process_data	Process Data & Run Results	2	
19	4	qc	QC Results	3	
20	4	inventory	Final Material → Inventory	4	
\.


--
-- Data for Name: run_statuses; Type: TABLE DATA; Schema: public; Owner: erezops
--

COPY public.run_statuses (id, name, color, "position") FROM stdin;
1	Planned	#7a00df	0
2	In Progress	#F7941E	1
3	Complete	#0aa574	2
4	On Hold	#8a8797	3
5	Cancelled	#cf2e2e	4
\.


--
-- Data for Name: stage_approvals; Type: TABLE DATA; Schema: public; Owner: erezops
--

COPY public.stage_approvals (id, stage_id, user_id, role, status, comment, created_at) FROM stdin;
\.


--
-- Data for Name: stage_links; Type: TABLE DATA; Schema: public; Owner: erezops
--

COPY public.stage_links (id, stage_id, label, url) FROM stdin;
1	1	Example: SharePoint folder	https://ereztech.sharepoint.com/sites/Production/Shared%20Documents
2	2	Example: SharePoint folder	https://ereztech.sharepoint.com/sites/Production/Shared%20Documents
\.


--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: erezops
--

COPY public.users (id, username, full_name, role, password_hash, is_active_user) FROM stdin;
1	admin	Site Administrator	Admin	scrypt:32768:8:1$U9WGfHGjTbZb3ztd$cb73c2618973feff3f0382ee6652c97f4d030da485951cd2bf911c4db2ed2bb08c752a06c76bb945d0c222bc52965fbd5d8ab21e8ea564b2b1492f1b972e2d19	t
4	hima	Hima Lingam	R&D Director	scrypt:32768:8:1$YRw0qTTl8PmMWWLw$faa0ad7c23fd09cc765148b65ea1de8faa103bd196953be234ec883965246c5963ab8aa8d6738e234bd594cc3c992a31d708b18efbcc64b07cf5aa8bd8e49065	t
2	tim.gilligan	Tim Gilligan	Engineering Manager	scrypt:32768:8:1$In5DQWlVIeN09IX9$bf684be2a0cbc8e62436a4e704116e6f582eb2de5a38825e871b3ba1e0a99df0133129bee54be2bb0b9d4df92500dacf283dfaab03f6b65de1e2d19d211dd2a4	t
3	ellie	Ellie Soto	QC Manager	scrypt:32768:8:1$tNRWxA4HuZ9bbwF8$a9de0e6d1ef35b2434d89f372726ca9e8854ff3df3b4fd5e8029bc1bc6db586372dd69f9251ffe16ced061d61585fd33bd93e15ef3d86f6a70c22f55ddcfdbd3	t
5	anu	Anu Archchige	Researcher	scrypt:32768:8:1$5XuuhrKyr1qDWPY5$6da74166ea3ee6d7cbd3821c3fff504b303872f3208595cd290e85dd2209f563f6bbb14d75d9a16056281d1c5ba696492456a9542000808ccbbb4f5333600538	t
6	lucas	Lucas Lisiecki	Procurement	scrypt:32768:8:1$Zd9GXuh9fw8AwaMy$b66c229d4e6345b21bb5c21131df851f649510d3b142458b14b23a86310fd1225884bcb32efc2f6e673b3ded1baca625634bc706bb816306f2d4849ffbbd19cc	t
7	nate	Nathan Allen	Admin	scrypt:32768:8:1$BIxH4sXB54ecfM17$6cb648233720835f90ba1bed3ea8d1b9ed521f01b7e9eaef26273d48a74e3ff6d081741c222a244f86a381f1a320d7dde63109dc0c3499015b37ed0e8bd95aba	t
8	ivan	Ivan Chumakov	Plant Engineer	scrypt:32768:8:1$h4njxHW3tjZ6emuJ$02cc10e5c201949ef45e9b8de866efea615c311f27799f8f0882e8fc6db2447a6f9834bb40f5ed6eb6f86b3dd5c933ed427a8a85c04eb3d60d8d8c55e7092bb4	t
9	don.morrison	Don Morrison	Commercial	scrypt:32768:8:1$N7XfVR9QOfpBPeht$bf54648f1fd14f098931aeb19827a7233a858b057c753cd9be35db140d32954571196f60d0c7d38b7fe6091b40a52faabe7b38eb79b74639195f7c6c13db7f23	t
10	christina	Christina Mattiolli	Finance	scrypt:32768:8:1$Bz4zLgDsaSHIBvl4$be8c3c16e13a42d84aa8725f2561d4ef4615fbc489145d38326b0bcbe7f8521d4f9d30b0526e8b90c8768048772daffc12e7281e84d59a4d2dcb57f6c978a8c2	t
11	shem	Shem Sapeta	Facilities	scrypt:32768:8:1$pnP0LV1RFFPcXs43$7f9e6553652e0eb2244b526d14f914e9fc694854f82d952aa0b8726ca63a50fb8cdaaeb81dfcc520e61397e037a0b40a2d5f81c62bae896bff7758d09038bb07	t
\.


--
-- Name: deliverables_id_seq; Type: SEQUENCE SET; Schema: public; Owner: erezops
--

SELECT pg_catalog.setval('public.deliverables_id_seq', 2, true);


--
-- Name: document_roots_id_seq; Type: SEQUENCE SET; Schema: public; Owner: erezops
--

SELECT pg_catalog.setval('public.document_roots_id_seq', 1, true);


--
-- Name: production_runs_id_seq; Type: SEQUENCE SET; Schema: public; Owner: erezops
--

SELECT pg_catalog.setval('public.production_runs_id_seq', 4, true);


--
-- Name: project_approvals_id_seq; Type: SEQUENCE SET; Schema: public; Owner: erezops
--

SELECT pg_catalog.setval('public.project_approvals_id_seq', 1, false);


--
-- Name: rd_projects_id_seq; Type: SEQUENCE SET; Schema: public; Owner: erezops
--

SELECT pg_catalog.setval('public.rd_projects_id_seq', 1, true);


--
-- Name: reactor_attributes_id_seq; Type: SEQUENCE SET; Schema: public; Owner: erezops
--

SELECT pg_catalog.setval('public.reactor_attributes_id_seq', 9, true);


--
-- Name: reactors_id_seq; Type: SEQUENCE SET; Schema: public; Owner: erezops
--

SELECT pg_catalog.setval('public.reactors_id_seq', 3, true);


--
-- Name: roles_id_seq; Type: SEQUENCE SET; Schema: public; Owner: erezops
--

SELECT pg_catalog.setval('public.roles_id_seq', 13, true);


--
-- Name: run_stages_id_seq; Type: SEQUENCE SET; Schema: public; Owner: erezops
--

SELECT pg_catalog.setval('public.run_stages_id_seq', 20, true);


--
-- Name: run_statuses_id_seq; Type: SEQUENCE SET; Schema: public; Owner: erezops
--

SELECT pg_catalog.setval('public.run_statuses_id_seq', 5, true);


--
-- Name: stage_approvals_id_seq; Type: SEQUENCE SET; Schema: public; Owner: erezops
--

SELECT pg_catalog.setval('public.stage_approvals_id_seq', 1, false);


--
-- Name: stage_links_id_seq; Type: SEQUENCE SET; Schema: public; Owner: erezops
--

SELECT pg_catalog.setval('public.stage_links_id_seq', 2, true);


--
-- Name: users_id_seq; Type: SEQUENCE SET; Schema: public; Owner: erezops
--

SELECT pg_catalog.setval('public.users_id_seq', 11, true);


--
-- Name: deliverables deliverables_pkey; Type: CONSTRAINT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.deliverables
    ADD CONSTRAINT deliverables_pkey PRIMARY KEY (id);


--
-- Name: document_roots document_roots_name_key; Type: CONSTRAINT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.document_roots
    ADD CONSTRAINT document_roots_name_key UNIQUE (name);


--
-- Name: document_roots document_roots_pkey; Type: CONSTRAINT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.document_roots
    ADD CONSTRAINT document_roots_pkey PRIMARY KEY (id);


--
-- Name: production_runs production_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.production_runs
    ADD CONSTRAINT production_runs_pkey PRIMARY KEY (id);


--
-- Name: project_approvals project_approvals_pkey; Type: CONSTRAINT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.project_approvals
    ADD CONSTRAINT project_approvals_pkey PRIMARY KEY (id);


--
-- Name: rd_projects rd_projects_pkey; Type: CONSTRAINT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.rd_projects
    ADD CONSTRAINT rd_projects_pkey PRIMARY KEY (id);


--
-- Name: reactor_attributes reactor_attributes_pkey; Type: CONSTRAINT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.reactor_attributes
    ADD CONSTRAINT reactor_attributes_pkey PRIMARY KEY (id);


--
-- Name: reactors reactors_name_key; Type: CONSTRAINT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.reactors
    ADD CONSTRAINT reactors_name_key UNIQUE (name);


--
-- Name: reactors reactors_pkey; Type: CONSTRAINT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.reactors
    ADD CONSTRAINT reactors_pkey PRIMARY KEY (id);


--
-- Name: roles roles_name_key; Type: CONSTRAINT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_name_key UNIQUE (name);


--
-- Name: roles roles_pkey; Type: CONSTRAINT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_pkey PRIMARY KEY (id);


--
-- Name: run_stages run_stages_pkey; Type: CONSTRAINT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.run_stages
    ADD CONSTRAINT run_stages_pkey PRIMARY KEY (id);


--
-- Name: run_statuses run_statuses_name_key; Type: CONSTRAINT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.run_statuses
    ADD CONSTRAINT run_statuses_name_key UNIQUE (name);


--
-- Name: run_statuses run_statuses_pkey; Type: CONSTRAINT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.run_statuses
    ADD CONSTRAINT run_statuses_pkey PRIMARY KEY (id);


--
-- Name: stage_approvals stage_approvals_pkey; Type: CONSTRAINT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.stage_approvals
    ADD CONSTRAINT stage_approvals_pkey PRIMARY KEY (id);


--
-- Name: stage_links stage_links_pkey; Type: CONSTRAINT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.stage_links
    ADD CONSTRAINT stage_links_pkey PRIMARY KEY (id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: users users_username_key; Type: CONSTRAINT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_username_key UNIQUE (username);


--
-- Name: deliverables deliverables_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.deliverables
    ADD CONSTRAINT deliverables_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.rd_projects(id);


--
-- Name: production_runs production_runs_intermediate_for_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.production_runs
    ADD CONSTRAINT production_runs_intermediate_for_id_fkey FOREIGN KEY (intermediate_for_id) REFERENCES public.production_runs(id) ON DELETE SET NULL;


--
-- Name: production_runs production_runs_reactor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.production_runs
    ADD CONSTRAINT production_runs_reactor_id_fkey FOREIGN KEY (reactor_id) REFERENCES public.reactors(id);


--
-- Name: project_approvals project_approvals_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.project_approvals
    ADD CONSTRAINT project_approvals_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.rd_projects(id);


--
-- Name: project_approvals project_approvals_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.project_approvals
    ADD CONSTRAINT project_approvals_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: rd_projects rd_projects_researcher_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.rd_projects
    ADD CONSTRAINT rd_projects_researcher_id_fkey FOREIGN KEY (researcher_id) REFERENCES public.users(id);


--
-- Name: reactor_attributes reactor_attributes_reactor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.reactor_attributes
    ADD CONSTRAINT reactor_attributes_reactor_id_fkey FOREIGN KEY (reactor_id) REFERENCES public.reactors(id);


--
-- Name: run_stages run_stages_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.run_stages
    ADD CONSTRAINT run_stages_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.production_runs(id);


--
-- Name: stage_approvals stage_approvals_stage_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.stage_approvals
    ADD CONSTRAINT stage_approvals_stage_id_fkey FOREIGN KEY (stage_id) REFERENCES public.run_stages(id);


--
-- Name: stage_approvals stage_approvals_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.stage_approvals
    ADD CONSTRAINT stage_approvals_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: stage_links stage_links_stage_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: erezops
--

ALTER TABLE ONLY public.stage_links
    ADD CONSTRAINT stage_links_stage_id_fkey FOREIGN KEY (stage_id) REFERENCES public.run_stages(id);


--
-- PostgreSQL database dump complete
--

\unrestrict DbulTAF5na2uTH9EVHa3hkGQGPOb3JkFqjn0KtZrYlVpJtGGF7YtWbrrSf2r9EC

