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
    sel_grupo = ctx["sel_grupo"]

    st.header("Psicometria Computacional & IA Educacional")
    st.markdown("""
    Esta aba apresenta a fronteira cientifica da Mineracao de Dados Educacionais (EDM).
    O pipeline combina metricas classicas dos testes (TCT), redes neurais nao-lineares e modelos de dependencia de itens
    para decodificar o comportamento cognitivo dos estudantes -- com avaliacao honesta (treino/teste ou validacao cruzada).
    """)
    edicao = selecionar_edicao_motor("psicometria", "psicom")
    pasta_psico = pasta_motor("psicometria", edicao)
    pasta_cdm = pasta_motor("cdm", edicao)
    pasta_clust = pasta_motor("clustering", edicao)

    sub_tab_som, sub_tab_dina, sub_tab_clust = st.tabs(["SOM (Self-Organizing Map)", "Resultados DINA", "Metricas de Clustering"])

    with sub_tab_som:
        st.subheader("Topologia Cognitiva via SOM (Redes de Kohonen)")
        st.markdown("""
        O algoritmo **Self-Organizing Maps (SOM)** projeta a matriz multidimensional de respostas numa grelha
        neural competitiva nao-supervisionada. O grafico abaixo indica a topologia cognitiva dos estudantes,
        revelando padroes de agrupamento por perfil de desempenho.
        """)
        som_files = sorted(pasta_psico.glob("som_*.png")) if pasta_psico.exists() else []
        if som_files:
            for som_file in som_files:
                st.image(str(som_file), use_container_width=True)
                st.caption(f"SOM -- {som_file.stem}. Areas de mesma cor indicam alunos com perfis cognitivos semelhantes.")
        else:
            st.info(f"Nenhuma imagem SOM encontrada em {pasta_psico}/.")
            st.warning("Execute o pipeline de psicometria para gerar os mapas auto-organizaveis.")

    with sub_tab_dina:
        st.subheader("Resultados DINA (Slip & Guess)")
        st.markdown("""
        Parametros estimados pelo modelo **DINA** (Deterministic Input, Noisy "And" Gate).
        O **slip** mede a probabilidade de erro do dominante; o **guess** mede acerto por sorte.
        Valores de slip > 0.3 e guess > 0.3 indicam itens problematicos que precisam de revisao.
        """)
        dina_files = sorted(pasta_cdm.glob("dina_*.csv")) if pasta_cdm.exists() else []
        dina_files = [f for f in dina_files if "q_matrix" not in f.name]
        if dina_files:
            for dina_file in dina_files:
                st.markdown(f"**{dina_file.stem}**")
                df_dina = _ler(dina_file)
                if df_dina is not None and all(c in df_dina.columns for c in ["questao", "slip", "guess"]):
                    fig_dina = go.Figure()
                    fig_dina.add_trace(go.Scatter(x=df_dina["slip"], y=df_dina["guess"], mode="markers+text",
                                                  text=df_dina["questao"], textposition="top center",
                                                  marker=dict(size=10, color="#8b5cf6")))
                    fig_dina.add_hline(y=0.3, line_dash="dash", line_color="red", opacity=0.5, annotation_text="Limiar Guess")
                    fig_dina.add_vline(x=0.3, line_dash="dash", line_color="red", opacity=0.5, annotation_text="Limiar Slip")
                    fig_dina.update_layout(title=f"Dispersao Slip vs Guess -- {dina_file.stem}",
                                           xaxis_title="Slip (s)", yaxis_title="Guess (g)", height=450)
                    st.plotly_chart(fig_dina, use_container_width=True)
                    st.caption("Itens no canto superior direito (alto slip e guess) sao os mais problematicos e devem ser revisados.")
                    st.dataframe(df_dina, use_container_width=True)
                else:
                    st.warning(f"Arquivo {dina_file.name} nao contem colunas questao/slip/guess.")
        else:
            st.info("Nenhum arquivo dina_*.csv encontrado em modelos/cdm/.")

    with sub_tab_clust:
        st.subheader("Metricas de Clustering")
        st.markdown("Metricas de qualidade para determinar o numero ideal de clusters.")
        if chave_curso:
            arq = _buscar("metricas", pasta_clust, chave_curso)
            if arq:
                dfm = _ler(arq)
                st.dataframe(dfm, use_container_width=True)
                nums = dfm.select_dtypes(include=[np.number]).columns.tolist()
                if len(nums) > 1:
                    x = dfm.columns[0]
                    fig_m = go.Figure()
                    for col in nums[:4]:
                        if col != x:
                            fig_m.add_trace(go.Scatter(x=dfm[x], y=dfm[col], mode="lines+markers", name=col))
                    fig_m.update_layout(title="Metricas de Clustering por K", xaxis_title=str(x), yaxis_title="Valor", height=350)
                    st.plotly_chart(fig_m, use_container_width=True)
                    st.caption("Interpretacao: Silhueta > 0.5 e Davies-Bouldin < 1.0 indicam clusters bem formados.")
            else:
                st.info("Metricas de clustering nao encontradas.")
        else:
            st.info("Selecione um curso no painel lateral.")

    st.markdown("---")
    st.subheader("Matriz de Saude Psicometrica (Heatmap)")
    st.markdown("""
    Cruza indicadores psicometricos por curso (quando multiplos cursos estao disponiveis),
    revelando a **saude psicometrica** de cada area do conhecimento.
    Indicadores: dominio medio, OCs fragil (>50% erro), discriminacao, slip medio, guess medio.
    """)
    df_a_psico = _carregar_analise_ies()
    if df_a_psico is not None and not df_a_psico.empty and "TAXA_DEFICIENCIA_%" in df_a_psico.columns:
        if _tem_colunas(df_a_psico, "CO_GRUPO"):
            df_heat = df_a_psico.copy()
            if _tem_colunas(df_heat, "CO_GRUPO"):
                df_heat["Curso"] = df_heat["CO_GRUPO"].map(lambda x: _nome_grupo(x) if pd.notna(x) else str(x))
            ind_data = []
            for curso_nome_h, grp in df_heat.groupby("Curso"):
                if len(grp) < 3:
                    continue
                media_def = grp["TAXA_DEFICIENCIA_%"].mean()
                n_questoes = grp["QUESTAO"].nunique() if "QUESTAO" in grp.columns else 0
                ind_data.append({
                    "Curso": _curto(curso_nome_h, 30),
                    "Deficiencia_Media_%": round(media_def, 1),
                    "N_Questoes": n_questoes,
                    "N_Registros": len(grp),
                })
            if ind_data:
                df_ind = pd.DataFrame(ind_data).set_index("Curso")
                cols_heat = [c for c in df_ind.columns if df_ind[c].dtype in ["float64", "int64", "int32"]]
                if cols_heat:
                    fig_heat = px.imshow(
                        df_ind[cols_heat], text_auto=".1f",
                        color_continuous_scale="RdYlGn_r",
                        title="Matriz de Saude Psicometrica por Curso")
                    fig_heat.update_layout(height=max(300, len(df_ind) * 35 + 100))
                    st.plotly_chart(fig_heat, use_container_width=True)
                    st.caption("Valores altos de deficiencia (vermelho) indicam cursos que requerem intervencao prioritaria.")
                    st.dataframe(df_ind.reset_index(), use_container_width=True)
    else:
        st.info("Dados de analise por questao necessarios para a matriz psicometrica.")
