--
-- PostgreSQL database dump
--

-- Dumped from database version 18.4 (Debian 18.4-1.pgdg12+1)
-- Dumped by pg_dump version 18.4 (Debian 18.4-1.pgdg12+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;



SET default_table_access_method = heap;

--
-- Name: behavior_tree; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.behavior_tree (
    id bigint NOT NULL,
    name character varying(100) NOT NULL,
    description text,
    tree_definition jsonb NOT NULL
);


--
-- Name: behavior_tree_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.behavior_tree ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.behavior_tree_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: block_policy; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.block_policy (
    id bigint NOT NULL,
    policy_id character varying(50) NOT NULL,
    show_name character varying(100) NOT NULL,
    policy_type character varying(20) NOT NULL,
    category character varying(50) NOT NULL,
    risk_level integer NOT NULL,
    warning_prompt text,
    alert_enabled boolean DEFAULT false,
    CONSTRAINT chk_block_policy_category CHECK (((category)::text = ANY (ARRAY[('political'::character varying)::text, ('sexual'::character varying)::text, ('violence'::character varying)::text, ('suicide'::character varying)::text, ('custom'::character varying)::text]))),
    CONSTRAINT chk_block_policy_risk_level CHECK ((risk_level = ANY (ARRAY[1, 2, 3]))),
    CONSTRAINT chk_block_policy_type CHECK (((policy_type)::text = ANY ((ARRAY['report_only'::character varying, 'warning_prompt'::character varying, 'block'::character varying, 'force_block'::character varying])::text[])))
);


--
-- Name: block_policy_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.block_policy ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.block_policy_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: conversation_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.conversation_logs (
    id bigint NOT NULL,
    npc_role_id bigint,
    player_uuid uuid,
    session_uuid uuid,
    player_input text NOT NULL,
    npc_response text NOT NULL,
    model_config jsonb NOT NULL,
    latency_ms integer,
    success boolean DEFAULT true,
    error_message text,
    flagged boolean DEFAULT false,
    flagged_category character varying(50),
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    alert_required boolean DEFAULT false,
    exec_step jsonb DEFAULT '[]'::jsonb
);


--
-- Name: conversation_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.conversation_logs ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.conversation_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: llm_providers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.llm_providers (
    id bigint NOT NULL,
    provider_id character varying(50) NOT NULL,
    show_name character varying(100) NOT NULL,
    api_key character varying(255),
    base_url character varying(255) NOT NULL,
    models jsonb DEFAULT '[]'::jsonb
);


--
-- Name: llm_providers_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.llm_providers ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.llm_providers_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: mcp; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.mcp (
    id bigint NOT NULL,
    name character varying(100) NOT NULL,
    type character varying(20) NOT NULL,
    url character varying(500) NOT NULL,
    headers jsonb DEFAULT '{}'::jsonb,
    timeout integer DEFAULT 30,
    CONSTRAINT mcp_type_check CHECK (((type)::text = ANY ((ARRAY['sse'::character varying, 'streamable-http'::character varying])::text[])))
);


--
-- Name: mcp_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.mcp ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.mcp_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: npc_behavior_relations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.npc_behavior_relations (
    id bigint NOT NULL,
    npc_id bigint NOT NULL,
    behavior_tree_id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: npc_behavior_relations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.npc_behavior_relations ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.npc_behavior_relations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: npc_mcp_relations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.npc_mcp_relations (
    id bigint NOT NULL,
    npc_id bigint NOT NULL,
    mcp_id bigint NOT NULL
);


--
-- Name: npc_mcp_relations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.npc_mcp_relations ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.npc_mcp_relations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: npcs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.npcs (
    id bigint NOT NULL,
    name character varying(100) NOT NULL,
    model_config jsonb NOT NULL,
    character_prompt text NOT NULL,
    related_world bigint NOT NULL,
    is_enabled boolean DEFAULT false NOT NULL,
    owner bigint NOT NULL
);


--
-- Name: npcs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.npcs ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.npcs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id bigint NOT NULL,
    username character varying(50) NOT NULL,
    password_hash character varying(255) NOT NULL,
    is_enabled boolean DEFAULT false NOT NULL,
    is_admin boolean DEFAULT false NOT NULL,
    attmpts smallint DEFAULT 0 NOT NULL,
    last_failed_attempt timestamp with time zone
);


--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.users ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.users_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: word_list; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.word_list (
    id bigint NOT NULL,
    word character varying(100) NOT NULL,
    list_type character varying(20) NOT NULL,
    category character varying(50),
    risk_level integer DEFAULT 1,
    CONSTRAINT chk_risk_level CHECK ((risk_level = ANY (ARRAY[1, 2, 3]))),
    CONSTRAINT word_list_category_check CHECK (((category IS NULL) OR ((category)::text = ANY ((ARRAY['political'::character varying, 'sexual'::character varying, 'violence'::character varying, 'suicide'::character varying, 'custom'::character varying])::text[])))),
    CONSTRAINT word_list_type_check CHECK (((list_type)::text = ANY ((ARRAY['blacklist'::character varying, 'whitelist'::character varying])::text[])))
);


--
-- Name: word_list_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.word_list ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.word_list_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: worlds; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.worlds (
    id bigint NOT NULL,
    name character varying(100) NOT NULL,
    description text,
    world_prompt text NOT NULL,
    kb_api_url character varying(500),
    kb_api_headers jsonb DEFAULT '{}'::jsonb,
    kb_api_timeout integer DEFAULT 30,
    kb_api_data jsonb DEFAULT '{}'::jsonb
);


--
-- Name: worlds_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.worlds ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.worlds_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: behavior_tree behavior_tree_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.behavior_tree
    ADD CONSTRAINT behavior_tree_name_key UNIQUE (name);


--
-- Name: behavior_tree behavior_tree_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.behavior_tree
    ADD CONSTRAINT behavior_tree_pkey PRIMARY KEY (id);


--
-- Name: block_policy block_policy_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.block_policy
    ADD CONSTRAINT block_policy_pkey PRIMARY KEY (id);


--
-- Name: block_policy block_policy_policy_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.block_policy
    ADD CONSTRAINT block_policy_policy_id_key UNIQUE (policy_id);


--
-- Name: conversation_logs conversation_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_logs
    ADD CONSTRAINT conversation_logs_pkey PRIMARY KEY (id);


--
-- Name: llm_providers llm_providers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_providers
    ADD CONSTRAINT llm_providers_pkey PRIMARY KEY (id);


--
-- Name: llm_providers llm_providers_provider_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_providers
    ADD CONSTRAINT llm_providers_provider_id_key UNIQUE (provider_id);


--
-- Name: mcp mcp_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mcp
    ADD CONSTRAINT mcp_name_key UNIQUE (name);


--
-- Name: mcp mcp_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mcp
    ADD CONSTRAINT mcp_pkey PRIMARY KEY (id);


--
-- Name: npc_behavior_relations npc_behavior_relations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.npc_behavior_relations
    ADD CONSTRAINT npc_behavior_relations_pkey PRIMARY KEY (id);


--
-- Name: npc_mcp_relations npc_mcp_relations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.npc_mcp_relations
    ADD CONSTRAINT npc_mcp_relations_pkey PRIMARY KEY (id);


--
-- Name: npcs npcs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.npcs
    ADD CONSTRAINT npcs_pkey PRIMARY KEY (id);


--
-- Name: block_policy uk_block_policy_category_risk; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.block_policy
    ADD CONSTRAINT uk_block_policy_category_risk UNIQUE (category, risk_level);


--
-- Name: npc_behavior_relations uk_npc_behavior_relations_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.npc_behavior_relations
    ADD CONSTRAINT uk_npc_behavior_relations_unique UNIQUE (npc_id, behavior_tree_id);


--
-- Name: npc_mcp_relations uk_npc_mcp_relations_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.npc_mcp_relations
    ADD CONSTRAINT uk_npc_mcp_relations_unique UNIQUE (npc_id, mcp_id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: users users_username_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_username_key UNIQUE (username);


--
-- Name: word_list word_list_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.word_list
    ADD CONSTRAINT word_list_pkey PRIMARY KEY (id);


--
-- Name: word_list word_list_word_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.word_list
    ADD CONSTRAINT word_list_word_key UNIQUE (word);


--
-- Name: worlds worlds_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.worlds
    ADD CONSTRAINT worlds_name_key UNIQUE (name);


--
-- Name: worlds worlds_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.worlds
    ADD CONSTRAINT worlds_pkey PRIMARY KEY (id);


--
-- Name: idx_block_policy_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_block_policy_category ON public.block_policy USING btree (category);


--
-- Name: idx_block_policy_risk_level; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_block_policy_risk_level ON public.block_policy USING btree (risk_level);


--
-- Name: idx_block_policy_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_block_policy_type ON public.block_policy USING btree (policy_type);


--
-- Name: idx_conv_logs_npc_role_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_conv_logs_npc_role_id ON public.conversation_logs USING btree (npc_role_id);


--
-- Name: idx_conversation_logs_alert_required; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_conversation_logs_alert_required ON public.conversation_logs USING btree (alert_required) WHERE (alert_required = true);


--
-- Name: idx_npc_behavior_relations_bt_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_npc_behavior_relations_bt_id ON public.npc_behavior_relations USING btree (behavior_tree_id);


--
-- Name: idx_npc_behavior_relations_npc_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_npc_behavior_relations_npc_id ON public.npc_behavior_relations USING btree (npc_id);


--
-- Name: idx_npc_mcp_relations_mcp_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_npc_mcp_relations_mcp_id ON public.npc_mcp_relations USING btree (mcp_id);


--
-- Name: idx_npc_mcp_relations_npc_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_npc_mcp_relations_npc_id ON public.npc_mcp_relations USING btree (npc_id);


--
-- Name: idx_npcs_owner; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_npcs_owner ON public.npcs USING btree (owner);


--
-- Name: idx_word_list_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_word_list_category ON public.word_list USING btree (category);


--
-- Name: idx_word_list_list_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_word_list_list_type ON public.word_list USING btree (list_type);


--
-- Name: idx_word_list_risk_level; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_word_list_risk_level ON public.word_list USING btree (risk_level);


--
-- Name: conversation_logs conversation_logs_npc_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_logs
    ADD CONSTRAINT conversation_logs_npc_role_id_fkey FOREIGN KEY (npc_role_id) REFERENCES public.npcs(id) ON DELETE CASCADE;


--
-- Name: npcs fk_npcs_owner; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.npcs
    ADD CONSTRAINT fk_npcs_owner FOREIGN KEY (owner) REFERENCES public.users(id) ON DELETE RESTRICT;


--
-- Name: npc_behavior_relations npc_behavior_relations_behavior_tree_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.npc_behavior_relations
    ADD CONSTRAINT npc_behavior_relations_behavior_tree_id_fkey FOREIGN KEY (behavior_tree_id) REFERENCES public.behavior_tree(id) ON DELETE CASCADE;


--
-- Name: npc_behavior_relations npc_behavior_relations_npc_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.npc_behavior_relations
    ADD CONSTRAINT npc_behavior_relations_npc_id_fkey FOREIGN KEY (npc_id) REFERENCES public.npcs(id) ON DELETE CASCADE;


--
-- Name: npc_mcp_relations npc_mcp_relations_mcp_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.npc_mcp_relations
    ADD CONSTRAINT npc_mcp_relations_mcp_id_fkey FOREIGN KEY (mcp_id) REFERENCES public.mcp(id) ON DELETE CASCADE;


--
-- Name: npc_mcp_relations npc_mcp_relations_npc_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.npc_mcp_relations
    ADD CONSTRAINT npc_mcp_relations_npc_id_fkey FOREIGN KEY (npc_id) REFERENCES public.npcs(id) ON DELETE CASCADE;


--
-- Name: npcs npcs_related_world_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.npcs
    ADD CONSTRAINT npcs_related_world_fkey FOREIGN KEY (related_world) REFERENCES public.worlds(id) ON DELETE RESTRICT;


--
-- PostgreSQL database dump complete
--

