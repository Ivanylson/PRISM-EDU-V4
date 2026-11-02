import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from dashboard.componentes.utils import (
    _ler, _buscar, _tem_colunas, _coerce_numerico, _curto, _norm_oc,
    _oc_sem_prefixo, _nome_grupo, _carregar_analise_ies,
    _medias_por_questao_analise, obter_filtro_analise, _extrair_ano_filtro,
    PASTA_MOD, PASTA_EDA,
)


def render(ctx):
    df = ctx["df"]
    df_curso = ctx["df_curso"]
    df_nacional = ctx["df_nacional"]
    nome_curso = ctx["nome_curso"]
    chave_curso = ctx["chave_curso"]
    ies_sel = ctx["ies_sel"]
    sel_grupo = ctx["sel_grupo"]
    sel_tipo = ctx["sel_tipo"]
    sel_id = ctx["sel_id"]
    sel_label = ctx["sel_label"]
    curso_codigo = ctx["curso_codigo"]

    st.header("Diagnostico e Prescricao Pedagogica")
    st.markdown("""
    Esta secao apresenta o **diagnostico prescritivo** para o curso e IES selecionados, comparando-os com a media nacional.
    O diagnostico identifica as principais deficiencias e prescreve acoes pedagogicas direcionadas, servindo como base
    para a elaboracao de planos de melhoria pelo Nucleo Docente Estruturante (NDE).
    """)
    if df is None:
        st.info("Selecione um exame no painel lateral.")
    elif df_curso is not None and not df_curso.empty:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Exame", sel_label)
        c2.metric("Curso", nome_curso or "-")
        c3.metric("Alunos (Curso/IES)", f"{len(df_curso):,}")
        c4.metric("Alunos (Nacional)", f"{len(df_nacional):,}")
        if "NT_GER" in df_curso.columns:
            st.subheader("Nota Geral")
            c1, c2, c3 = st.columns(3)
            media_ies = df_curso['NT_GER'].mean()
            media_nac = df_nacional['NT_GER'].mean()
            c1.metric("Media IES", f"{media_ies:.2f}")
            c2.metric("Media Nacional", f"{media_nac:.2f}")
            c3.metric("Diferenca vs Nacional", f"{(media_ies - media_nac):.2f}",
                       delta="vs media nacional", delta_color="normal" if media_ies >= media_nac else "inverse")
        st.subheader("Top 5 IES com Mais Alunos")
        if "CO_IES" in df_nacional.columns:
            top = df_nacional.groupby("CO_IES").size().reset_index(name="N").nlargest(5, "N")
            if not top.empty:
                top["IES"] = top["CO_IES"].astype(str)
                st.plotly_chart(
                    px.bar(top, x="IES", y="N", color="N", color_continuous_scale="Blues",
                           title="Distribuicao de alunos por IES (Top 5)"),
                    use_container_width=True)
                st.caption("Interpretacao: IES com maior volume de alunos podem ter maior impacto nas metricas nacionais do curso.")
        if "CO_REGIAO_CURSO" in df_nacional.columns:
            st.subheader("Por Regiao")
            rmap = {1: "Norte", 2: "Nordeste", 3: "Sudeste", 4: "Sul", 5: "Centro-Oeste"}
            tmp = df_nacional["CO_REGIAO_CURSO"].map(rmap).dropna().value_counts().reset_index()
            tmp.columns = ["Regiao", "N"]
            st.plotly_chart(px.pie(tmp, names="Regiao", values="N",
                                   title="Distribuicao regional dos alunos do curso"),
                           use_container_width=True)
            st.caption("A distribuicao regional revela a abrangencia do curso e possiveis concentracoes geograficas.")
        if "TP_SEXO" in df_curso.columns:
            st.subheader("Por Sexo")
            sm = {1: "Masculino", 2: "Feminino", "M": "Masculino", "F": "Feminino",
                  "m": "Masculino", "f": "Feminino", "1": "Masculino", "2": "Feminino"}
            tmp = df_curso["TP_SEXO"].map(sm).dropna().value_counts().reset_index()
            tmp.columns = ["Sexo", "N"]
            if not tmp.empty:
                st.plotly_chart(px.pie(tmp, names="Sexo", values="N",
                                       title="Composicao por genero no curso"),
                               use_container_width=True)
                st.caption("O equilibrio de genero e um indicador relevante para politicas de inclusao e equidade.")
        if "NU_IDADE" in df_curso.columns:
            st.subheader("Distribuicao de Idade")
            tmp_idade = df_curso["NU_IDADE"].dropna()
            if not tmp_idade.empty:
                st.plotly_chart(px.histogram(tmp_idade, x="NU_IDADE", nbins=20,
                                             title="Distribuicao de idade dos alunos"),
                               use_container_width=True)
                st.caption("A faixa etaria predominante indica o perfil do estudante (tradicional vs. pos-graduando profissional).")

        st.markdown("---")
        st.subheader("Comparativo de Taxa de Deficiencia: IES vs Nacional")
        df_a_comp = _carregar_analise_ies(_extrair_ano_filtro(sel_tipo, sel_id))
        if df_a_comp is not None and not df_a_comp.empty:
            df_ies_comp = df_a_comp.copy()
            if _tem_colunas(df_ies_comp, "CO_IES") and ies_sel:
                df_ies_comp = df_ies_comp[df_ies_comp["CO_IES"].astype(str).str.strip() == str(ies_sel).strip()]
            if _tem_colunas(df_ies_comp, "CO_GRUPO") and sel_grupo:
                df_ies_comp = df_ies_comp[df_ies_comp["CO_GRUPO"].astype(str).str.strip() == str(sel_grupo).strip()]
            if not df_ies_comp.empty and "TAXA_DEFICIENCIA_%" in df_ies_comp.columns:
                df_nac_comp = df_a_comp.copy()
                if _tem_colunas(df_nac_comp, "CO_GRUPO") and sel_grupo:
                    df_nac_comp = df_nac_comp[df_nac_comp["CO_GRUPO"].astype(str).str.strip() == str(sel_grupo).strip()]
                ies_def_media = df_ies_comp["TAXA_DEFICIENCIA_%"].mean()
                nac_def_media = df_nac_comp["TAXA_DEFICIENCIA_%"].mean() if not df_nac_comp.empty else 0
                delta_def = ies_def_media - nac_def_media
                c_d1, c_d2, c_d3 = st.columns(3)
                c_d1.metric("Deficiencia Media IES", f"{ies_def_media:.1f}%")
                c_d2.metric("Deficiencia Media Nacional", f"{nac_def_media:.1f}%")
                c_d3.metric("Delta IES vs Nacional", f"{delta_def:+.1f}pp",
                           delta="menor deficiencia" if delta_def < 0 else "maior deficiencia",
                           delta_color="normal" if delta_def < 0 else "inverse")
                if ies_sel and "CO_IES" in df_ies_comp.columns:
                    df_ies_q = df_ies_comp.groupby("QUESTAO")["TAXA_DEFICIENCIA_%"].mean().reset_index()
                    df_nac_q = df_nac_comp.groupby("QUESTAO")["TAXA_DEFICIENCIA_%"].mean().reset_index() if "QUESTAO" in df_nac_comp.columns else pd.DataFrame()
                    if not df_ies_q.empty and not df_nac_q.empty:
                        df_merge = df_ies_q.merge(df_nac_q, on="QUESTAO", suffixes=("_IES", "_NAC"))
                        df_merge["Delta"] = df_merge["TAXA_DEFICIENCIA_%_IES"] - df_merge["TAXA_DEFICIENCIA_%_NAC"]
                        df_merge = df_merge.sort_values("Delta", ascending=False)
                        st.subheader("Top 5 Questoes Onde a IES Mais Desvia da Media Nacional")
                        top_delta = df_merge.head(5)
                        if not top_delta.empty:
                            for _, row in top_delta.iterrows():
                                delta_val = row["Delta"]
                                cor = ":red" if delta_val > 0 else ":green"
                                st.markdown(f"- **{row['QUESTAO']}** -- IES: {row['TAXA_DEFICIENCIA_%_IES']:.1f}% vs Nacional: {row['TAXA_DEFICIENCIA_%_NAC']:.1f}% ({cor}[{delta_val:+.1f}pp])")
                            st.caption("Questoes com maior gap positivo indicam areas onde a IES performa pior que a media nacional.")
                        st.subheader("Top 5 Questoes Onde a IES Supera a Nacional")
                        bot_delta = df_merge.tail(5).iloc[::-1]
                        if not bot_delta.empty:
                            for _, row in bot_delta.iterrows():
                                delta_val = row["Delta"]
                                cor = ":red" if delta_val > 0 else ":green"
                                st.markdown(f"- **{row['QUESTAO']}** -- IES: {row['TAXA_DEFICIENCIA_%_IES']:.1f}% vs Nacional: {row['TAXA_DEFICIENCIA_%_NAC']:.1f}% ({cor}[{delta_val:+.1f}pp])")
    else:
        st.info("Selecione uma IES e um curso no painel lateral para ver o diagnostico detalhado.")
        if sel_tipo == "enamed" and df is not None:
            st.header("Dados ENAMED")
            st.markdown("""
            **Sobre o ENAMED:** O Exame Nacional de Medidas Educacionais em Aprendizagem e seus Determinantes
            (ENAMED) e um exame amostral que avalia competencias genericas de graduandos. Diferente do ENADE,
            o ENAMED **nao possui identificadores de IES (CO_IES) nem de grupo de curso (CO_GRUPO)**,
            apenas o codigo do curso (CO_CURSO). Por isso, a analise e feita por curso sem especificidade de IES.
            """)
            st.dataframe(df.head(20), use_container_width=True)
            st.caption(f"Total: {len(df)} registros.")

    df_a = _carregar_analise_ies(_extrair_ano_filtro(sel_tipo, sel_id))
    if df is not None and df_a is not None and not df_a.empty:
        st.markdown("---")
        st.subheader("Analise por Questao: OCs, Perfil e Competencias")
        st.markdown("""
        **Esta secao identifica as questoes com maior taxa de erro (deficiencia) para o curso/IES selecionado
        e exibe os Objetos de Conhecimento (OCs), o Perfil e as Competencias associadas a cada questao,
        permitindo ao NDE identificar exatamente quais topicos curriculares precisam de intervencao.**
        """)
        df_filtrado = obter_filtro_analise(df_a, ies_sel, curso_codigo, sel_tipo, sel_id)
        if not df_filtrado.empty:
            df_questoes = _medias_por_questao_analise(df_filtrado)
            if not df_questoes.empty:
                c1, c2, c3 = st.columns(3)
                media_def = df_questoes["TAXA_DEFICIENCIA_%"].mean() if "TAXA_DEFICIENCIA_%" in df_questoes.columns else 0
                max_def = df_questoes["TAXA_DEFICIENCIA_%"].max() if "TAXA_DEFICIENCIA_%" in df_questoes.columns else 0
                n_questoes = len(df_questoes)
                c1.metric("Media Deficiencia", f"{media_def:.1f}%")
                c2.metric("Pior Questao", f"{max_def:.1f}%")
                c3.metric("Questoes Avaliadas", f"{n_questoes}")
                if "TAXA_DEFICIENCIA_%" in df_questoes.columns:
                    st.subheader("Top 5 Questoes com Maior Deficiencia")
                    top5 = df_questoes.head(5)
                    for _, row in top5.iterrows():
                        q_name = row.get("QUESTAO", "?")
                        tax_err = row.get("TAXA_DEFICIENCIA_%", 0)
                        oc1 = str(row.get("OC1", "")).strip()
                        oc2 = str(row.get("OC2", "")).strip()
                        oc3 = str(row.get("OC3", "")) if "OC3" in row.index else ""
                        oc3 = str(oc3).strip() if pd.notna(oc3) else ""
                        perfil_val = ""
                        for col in df_questoes.columns:
                            if "PERFIL" in col.upper():
                                perfil_val = str(row.get(col, "")).strip()
                                break
                        comp_val = ""
                        for col in df_questoes.columns:
                            if "COMPET" in col.upper():
                                comp_val = str(row.get(col, "")).strip()
                                break
                        cor_barra = "#ef4444" if tax_err >= 70 else "#f59e0b" if tax_err >= 50 else "#3b82f6"
                        with st.container():
                            st.markdown(f"**{q_name}** -- Erro: **{tax_err:.1f}%**")
                            cols_info = st.columns(3)
                            with cols_info[0]:
                                ocs_texto = ", ".join(filter(lambda x: x and x != "nan", [oc1, oc2, oc3]))
                                if ocs_texto:
                                    st.caption(f"OCs: {ocs_texto}")
                            with cols_info[1]:
                                if perfil_val and perfil_val != "nan":
                                    st.caption(f"Perfil: {_curto(perfil_val, 80)}")
                            with cols_info[2]:
                                if comp_val and comp_val != "nan":
                                    st.caption(f"Competencia: {_curto(comp_val, 80)}")
                            st.progress(min(tax_err / 100, 1.0))
                st.markdown("---")
                st.subheader("Distribuicao da Deficiencia por Questao (Grafico)")
                if "TAXA_DEFICIENCIA_%" in df_questoes.columns:
                    fig_def = px.bar(
                        df_questoes.sort_values("TAXA_DEFICIENCIA_%", ascending=False),
                        x="QUESTAO", y="TAXA_DEFICIENCIA_%", color="TAXA_DEFICIENCIA_%",
                        color_continuous_scale="RdYlGn_r",
                        title="Taxa de Deficiencia (%) por Questao -- Media do Curso/IES",
                        text="TAXA_DEFICIENCIA_%",
                    )
                    fig_def.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
                    fig_def.update_layout(height=450)
                    st.plotly_chart(fig_def, use_container_width=True)
                    st.caption("Questoes com taxa acima de 70% indicam deficiencia critica. "
                               "Cada barra esta associada aos Objetos de Conhecimento (OCs) que devem ser reforcados no curriculo.")
                colunas_oc = [c for c in df_questoes.columns if c.startswith("OC")]
                if colunas_oc:
                    st.subheader("Frequencia dos Objetos de Conhecimento (OCs) nas Questoes Criticas")
                    top_n = min(10, len(df_questoes))
                    top_questoes = df_questoes.head(top_n)
                    oc_counter = {}
                    for _, row in top_questoes.iterrows():
                        for col in colunas_oc:
                            val = str(row.get(col, "")).strip()
                            if val and val != "nan":
                                nome_oc = _oc_sem_prefixo(val)
                                oc_counter[nome_oc] = oc_counter.get(nome_oc, 0) + 1
                    if oc_counter:
                        df_oc = pd.DataFrame(list(oc_counter.items()), columns=["OC", "N_Questoes_Criticas"])
                        df_oc = df_oc.sort_values("N_Questoes_Criticas", ascending=False)
                        st.plotly_chart(
                            px.bar(df_oc, x="OC", y="N_Questoes_Criticas", color="N_Questoes_Criticas",
                                   color_continuous_scale="Oranges",
                                   title="OCs Mais Frequentes nas Questoes com Maior Deficiencia"),
                            use_container_width=True)
                        st.caption("OCs que mais aparecem entre as questoes criticas indicam areas do conhecimento "
                                   "que demandam intervencao pedagogica prioritaria.")
                st.subheader("Tabela Completa: Questoes x OCs x Perfil x Competencias")
                cols_mostrar = ["QUESTAO", "TAXA_DEFICIENCIA_%"]
                for c in df_questoes.columns:
                    if c.startswith("OC") or "PERFIL" in c.upper() or "COMPET" in c.upper():
                        cols_mostrar.append(c)
                cols_existentes = [c for c in cols_mostrar if c in df_questoes.columns]
                if cols_existentes:
                    st.dataframe(
                        df_questoes[cols_existentes].style.background_gradient(
                            subset=["TAXA_DEFICIENCIA_%"] if "TAXA_DEFICIENCIA_%" in df_questoes.columns else [],
                            cmap="RdYlGn_r"),
                        use_container_width=True, height=400)
                    st.caption("Tabela com todas as questoes, suas taxas de erro e os mapeamentos de OCs, Perfil e Competencias.")
        else:
            st.info("Nenhum dado de analise por questao disponivel para o curso/IES selecionado.")
