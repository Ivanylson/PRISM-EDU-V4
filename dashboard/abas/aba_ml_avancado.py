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
    df_nacional = ctx["df_nacional"]
    chave_curso = ctx["chave_curso"]
    nome_curso = ctx["nome_curso"]

    st.header("Machine Learning Avancado")
    st.markdown("""
    Esta secao apresenta os resultados obtidos atraves de um pipeline de modelagem preditiva avancada:
    1. **Filtro de Anomalias (Isolation Forest):** Remocao de padroes de chute ou abandono.
    2. **Reducao de Dimensionalidade (PCA):** Concentracao das questoes em componentes principais.
    3. **Tratamento de Desbalanceamento (SMOTE):** Geracao artificial para equilibrar classes.
    Apresenta metricas de **SHAP** e **clustering** para comparacao de algoritmos.
    """)
    edicao = selecionar_edicao_motor("shap", "mlav")
    pasta_shap = pasta_motor("shap", edicao)
    pasta_clust = pasta_motor("clustering", edicao)

    st.subheader("Metricas SHAP")
    arq_shap_m = None
    if chave_curso:
        arq_shap_m = _buscar("metricas", pasta_shap, chave_curso)
    if arq_shap_m:
        st.dataframe(_ler(arq_shap_m), use_container_width=True)
        st.caption("Metricas de qualidade do modelo preditivo SHAP. Acuracia, F1 e AUC-ROC indicam desempenho geral.")
    else:
        st.info("Metricas SHAP nao encontradas para este curso.")

    st.subheader("Metricas de Clustering")
    arq_clust = None
    if chave_curso:
        arq_clust = _buscar("metricas", pasta_clust, chave_curso)
    if arq_clust:
        df_clust = _ler(arq_clust)
        st.dataframe(df_clust, use_container_width=True)
        st.caption("Comparacao de algoritmos de clustering (KMeans, GMM, Hierarquico) por metricas de qualidade.")
        nums = df_clust.select_dtypes(include=[np.number]).columns.tolist()
        if len(nums) > 1:
            fig_comp = go.Figure()
            x_col = df_clust.columns[0]
            for col in nums[:3]:
                if col != x_col:
                    fig_comp.add_trace(go.Scatter(x=df_clust[x_col], y=df_clust[col], mode="lines+markers", name=col, marker=dict(size=6)))
            fig_comp.update_layout(title="Comparacao de Algoritmos de Clustering", xaxis_title=str(x_col), yaxis_title="Metrica", height=350)
            st.plotly_chart(fig_comp, use_container_width=True)
            st.caption("Grafico comparativo das metricas de clustering conforme K varia.")
    else:
        st.info("Metricas de clustering nao encontradas para este curso.")

    st.subheader("Tabela Comparativa de Algoritmos")
    st.markdown("""
    | Algoritmo | Descricao | Indicador Ideal |
    |-----------|-----------|-----------------|
    | K-Means | Agrupamento por centroides | Silhueta > 0.5 |
    | GMM | Modelos de mistura gaussiana | BIC baixo |
    | Hierarquico | Agrupamento aglomerativo | Davies-Bouldin baixo |
    """)
    st.caption("Tabela de referencia para interpretar os resultados de clustering.")
    st.info("**Interpretacao:** O melhor algoritmo e aquele que maximiza silhueta e minimiza Davies-Bouldin. "
            "Na pratica, K-Means e robusto para dados educacionais com clusters esfericos.")

    st.markdown("---")
    st.subheader("ANOVA Regional: A Regiao Explica o Desempenho?")
    st.markdown("""
    Analise de variancia (ANOVA) testa se ha diferencas estatisticamente significativas no desempenho
    entre as regioes brasileiras. O **Eta squared** mede o tamanho do efeito (proporcao da variancia explicada pela regiao).
    """)
    if df_nacional is not None and "CO_REGIAO_CURSO" in df_nacional.columns and "NT_GER" in df_nacional.columns:
        rmapANOVA = {1: "Norte", 2: "Nordeste", 3: "Sudeste", 4: "Sul", 5: "Centro-Oeste"}
        df_anova = df_nacional[["CO_REGIAO_CURSO", "NT_GER"]].dropna().copy()
        df_anova["Regiao"] = df_anova["CO_REGIAO_CURSO"].map(rmapANOVA)
        df_anova = df_anova.dropna(subset=["Regiao"])
        if df_anova["Regiao"].nunique() >= 2:
            grupos = [g["NT_GER"].values for _, g in df_anova.groupby("Regiao") if len(g) >= 2]
            if len(grupos) >= 2:
                from algoritmos.estatistica.anova_robusta import anova_robusta, formatar_p
                nomes_regiao = [reg for reg, g in df_anova.groupby("Regiao") if len(g) >= 2]
                res_anova = anova_robusta(grupos, nomes=nomes_regiao)
                f_stat = res_anova["F"]
                p_val = res_anova["p_anova"]
                eta2 = res_anova["eta2"]
                m_a1, m_a2, m_a3, m_a4 = st.columns(4)
                m_a1.metric("F-Estatistica", f"{f_stat:.2f}")
                m_a2.metric("p-valor", formatar_p(p_val))
                m_a3.metric("Eta2 (Efeito)", f"{eta2:.4f}")
                pct_var = eta2 * 100
                m_a4.metric("Variancia Explicada", f"{pct_var:.2f}%")
                if res_anova["escolha"] == "parametrica":
                    st.caption("Pressupostos validados: Shapiro-Wilk OK, Levene OK → ANOVA parametrica.")
                else:
                    st.caption(
                        f"Pressupostos nao validados; resultado primario: Kruskal-Wallis "
                        f"(H={res_anova['H_kruskal']:.2f}, p={formatar_p(res_anova['p_kruskal'])}). "
                        f"F e eta² reportados como referencia complementar."
                    )
                if p_val < 0.05:
                    if eta2 < 0.01:
                        st.info(f"**Resultado:** Diferenca estatistica significativa (p={p_val:.4f}), mas o efeito e **minusculo** (Eta2={eta2:.4f}). "
                                "A regiao explica menos de 1% da variancia. Outros fatores (qualidade do ensino, socioeconomicos) sao muito mais relevantes.")
                    elif eta2 < 0.06:
                        st.warning(f"**Resultado:** Diferenca significativa (p={p_val:.4f}) com efeito **pequeno** (Eta2={eta2:.4f}). "
                                   "A regiao tem influencia limitada sobre o desempenho.")
                    else:
                        st.error(f"**Resultado:** Diferenca significativa (p={p_val:.4f}) com efeito **moderado/grande** (Eta2={eta2:.4f}). "
                                 "A regiao e um fator relevante de desigualdade.")
                else:
                    st.success(f"**Resultado:** Nao ha diferenca significativa entre regioes (p={p_val:.4f}). "
                               "A regiao nao e um fator explicativo relevante para este curso.")
                media_reg = df_anova.groupby("Regiao")["NT_GER"].agg(["mean", "count", "std"]).reset_index()
                media_reg.columns = ["Regiao", "Media_NT_GER", "N_Alunos", "Desvio"]
                media_reg = media_reg.sort_values("Media_NT_GER", ascending=False)
                fig_anova = px.bar(media_reg, x="Regiao", y="Media_NT_GER", color="Media_NT_GER",
                                   color_continuous_scale="RdYlGn", text="Media_NT_GER",
                                   title="Media de Nota Geral por Regiao (ANOVA)")
                fig_anova.update_traces(texttemplate="%{text:.2f}", textposition="outside")
                fig_anova.update_layout(height=400)
                st.plotly_chart(fig_anova, use_container_width=True)
                st.dataframe(media_reg, use_container_width=True)
                st.caption("Diagnostico pedagogico: Se a regiao nao explica o desempenho, as intervencoes devem ser "
                           "focalizadas na qualidade do ensino e nao em ajustes regionais genericos.")
            else:
                st.info("Menos de 2 regioes com dados suficientes para ANOVA.")
        else:
            st.info("Menos de 2 regioes presentes nos dados.")
    else:
        st.info("Colunas CO_REGIAO_CURSO ou NT_GER nao disponiveis para ANOVA regional.")
