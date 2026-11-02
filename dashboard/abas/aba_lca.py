import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from dashboard.componentes.utils import (
    _ler, _buscar, _tem_colunas, _coerce_numerico, _curto, _norm_oc,
    _oc_sem_prefixo, _nome_grupo, _carregar_analise_ies,
    _medias_por_questao_analise, obter_filtro_analise,
    PASTA_MOD, PASTA_EDA, selecionar_edicao_motor, pasta_motor,
)


def render(ctx):
    chave_curso = ctx["chave_curso"]
    nome_curso = ctx["nome_curso"]

    st.header("Analise de Classes Latentes (LCA)")
    st.markdown("""
    Identificacao de perfis de aprendizagem via **Latent Class Analysis** -- abordagem estatistica robusta para dados
    categoricos binarios. A LCA determina quantos subgrupos (classes latentes) existem entre os alunos, baseando-se
    no padrao de acertos e erros nas questoes. O numero otimo de classes (k) e selecionado pelo **BIC**
    e pela **entropia normalizada** (quanto mais proxima de 1, melhor a separacao).
    """)
    edicao = selecionar_edicao_motor("lca", "lca")
    pasta_lca = pasta_motor("lca", edicao)
    csv_geral = pasta_lca / "01_relatorio_geral_por_ies.csv"
    csv_cls = pasta_lca / "02_caracterizacao_das_classes.csv"
    csv_crit = pasta_lca / "03_criterios_de_selecao_k.csv"
    if csv_geral.exists():
        dfl = _ler(csv_geral)
        if _tem_colunas(dfl, "ies"):
            dfl["ies"] = dfl["ies"].astype(str).str.strip()
        cursos = sorted(dfl["curso"].dropna().unique()) if "curso" in dfl.columns else []
        if cursos:
            c1, c2 = st.columns(2)
            with c1:
                cr = st.selectbox("Curso (LCA):", cursos, key="lca_c")
            with c2:
                iesl = sorted(dfl[dfl["curso"] == cr]["ies"].unique()) if "ies" in dfl.columns else []
                il = st.selectbox("IES (LCA):", iesl, key="lca_i") if iesl else None
            if il:
                row = dfl[(dfl["curso"] == cr) & (dfl["ies"] == il)]
                if not row.empty:
                    r = row.iloc[0]
                    c1, c2, c3, c4, c5 = st.columns(5)
                    c1.metric("k (classes)", int(r.get("k_escolhido", 0)))
                    c2.metric("Entropia", f"{r.get('entropia_normalizada', 0):.3f}")
                    c3.metric("Estabilidade (Jaccard)", f"{r.get('jaccard_medio_bootstrap', 0):.3f}")
                    c4.metric("ARI (LCA vs K-Means)", f"{r.get('ari_lca_vs_kmeans_mca', 0):.3f}")
                    c5.metric("N alunos", str(int(r.get("n_alunos", 0))))
                    with st.expander("Justificativa da selecao de k"):
                        st.info(r.get("justificativa_k", "N/A"))
                        st.caption(f"Log-verossimilhanca: {r.get('log_lik', 0):.2f} | Convergiu: {r.get('convergiu', 'N/A')}")
                    st.markdown("---")
                    if csv_cls.exists():
                        dfc = _ler(csv_cls)
                        sub = dfc[(dfc["curso"] == cr) & (dfc["ies"].astype(str) == il)]
                        if not sub.empty:
                            st.subheader("Perfis Identificados pela LCA")
                            prob_cols = [f"PROB_Q{i}" for i in range(1, 39) if f"PROB_Q{i}" in sub.columns]
                            gap_cols = [f"GAP_Q{i}" for i in range(1, 39) if f"GAP_Q{i}" in sub.columns]
                            q_labels = [c.replace("PROB_", "") for c in prob_cols]
                            fig = go.Figure()
                            for _, cls in sub.sort_values("taxa_acerto_media", ascending=False).iterrows():
                                probs = [cls.get(c, 0) for c in prob_cols]
                                classe_nome = f"Classe {int(cls.get('classe_id', 0))} ({int(cls.get('n_alunos', 0))} alunos)"
                                fig.add_trace(go.Scatter(x=q_labels, y=probs, mode="lines+markers", name=classe_nome, marker=dict(size=5)))
                            fig.update_layout(title="P(Acerto) por Questao -- Classes LCA", xaxis_title="Questao", yaxis_title="P(Acerto)", yaxis_range=[0, 1.05], hovermode="x unified", height=400)
                            fig.add_vrect(x0=-0.5, x1=7.5, fillcolor="gray", opacity=0.05, layer="below", line_width=0, annotation_text="FG", annotation_position="top left")
                            st.plotly_chart(fig, use_container_width=True)
                            st.caption("Questoes 1-8 (FG) sao de Formacao Geral; as demais sao de Formacao Especifica.")
                            if gap_cols:
                                fig_gap = go.Figure()
                                for _, cls in sub.sort_values("taxa_acerto_media", ascending=False).iterrows():
                                    gaps = [cls.get(c, 0) for c in gap_cols]
                                    fig_gap.add_trace(go.Scatter(x=q_labels, y=gaps, mode="lines+markers", name=f"Classe {int(cls.get('classe_id', 0))}"))
                                fig_gap.update_layout(title="GAP (diferenca para media da IES)", xaxis_title="Questao", yaxis_title="GAP", hovermode="x unified", height=350)
                                fig_gap.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
                                fig_gap.add_vrect(x0=-0.5, x1=7.5, fillcolor="gray", opacity=0.05, layer="below", line_width=0)
                                st.plotly_chart(fig_gap, use_container_width=True)
                                st.caption("GAP positivo = classe acima da media da IES. GAP negativo = abaixo.")
                            cols_show = ['classe_id', 'n_alunos', 'pct_alunos', 'taxa_acerto_media', 'taxa_acerto_media_ies', 'itens_diferencialmente_fortes', 'itens_diferencialmente_fracos']
                            cols_show = [c for c in cols_show if c in sub.columns]
                            st.dataframe(sub[cols_show].rename(columns={'classe_id': 'Classe', 'n_alunos': 'N Alunos', 'pct_alunos': '%', 'taxa_acerto_media': 'Media Acertos', 'taxa_acerto_media_ies': 'Media IES', 'itens_diferencialmente_fortes': 'Itens Fortes', 'itens_diferencialmente_fracos': 'Itens Fracos'}), use_container_width=True)
                    st.markdown("---")
                    st.subheader("Distribuicao de k no Curso (todas as IES)")
                    df_curso_k = dfl[dfl["curso"] == cr]["k_escolhido"].value_counts().sort_index().reset_index()
                    df_curso_k.columns = ["k", "quantidade"]
                    fig_k = px.bar(df_curso_k, x="k", y="quantidade", text="quantidade", color="quantidade", color_continuous_scale="Blues")
                    fig_k.update_traces(textposition="outside")
                    fig_k.update_layout(xaxis=dict(tickmode="linear", dtick=1), height=300)
                    st.plotly_chart(fig_k, use_container_width=True)
                    st.caption("Distribuicao do numero de classes escolhidas por IES para este curso.")
                    if csv_crit.exists():
                        df_crit = _ler(csv_crit)
                        df_crit_ies = df_crit[(df_crit["curso"] == cr) & (df_crit["ies"].astype(str) == il)]
                        if not df_crit_ies.empty:
                            st.subheader("Criterios de Selecao de k")
                            cols_crit = ['k', 'bic', 'aic', 'entropia', 'menor_classe_pct']
                            cols_crit = [c for c in cols_crit if c in df_crit_ies.columns]
                            st.dataframe(df_crit_ies[cols_crit].set_index("k").round(3), use_container_width=True)
                            st.caption("O k com menor BIC e maior entropia e o escolhido.")
        else:
            st.info("Nenhum curso encontrado no LCA.")
    else:
        st.warning("Execute o pipeline LCA primeiro.")
        st.info(f"Os resultados devem estar em {pasta_lca} com arquivos 01_relatorio_geral_por_ies.csv, 02_caracterizacao_das_classes.csv e 03_criterios_de_selecao_k.csv.")
