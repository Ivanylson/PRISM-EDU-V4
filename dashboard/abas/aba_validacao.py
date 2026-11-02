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

    st.header("Validacao + Clustering")
    st.markdown("""
    **Metodologia:** O algoritmo **K-Means** agrupa alunos por similaridade de respostas nas questoes objetivas.
    A validacao utiliza as metricas de **Silhueta** (coesao interna), **Calinski-Harabasz** (separacao entre clusters)
    e **Davies-Bouldin** (compacidade). O numero otimo de clusters e determinado pelo metodo do cotovelo e pela
    maximizacao da silhueta.
    """)
    edicao = selecionar_edicao_motor("clustering", "valid")
    pasta_clust = pasta_motor("clustering", edicao)
    if chave_curso:
        arq = _buscar("metricas", pasta_clust, chave_curso)
        if arq:
            dfm = _ler(arq)
            st.subheader("Metricas de Clustering por K")
            st.dataframe(dfm, use_container_width=True)
            st.caption("Tabela de metricas para diferentes valores de K (numero de clusters). Busque silhueta alta e Davies-Bouldin baixo.")
            nums = dfm.select_dtypes(include=[np.number]).columns.tolist()
            if len(nums) > 1:
                x = dfm.columns[0]
                for col in nums[:4]:
                    if col != x:
                        st.plotly_chart(
                            px.line(dfm, x=x, y=col, markers=True,
                                    title=f"Evolucao de {col} por numero de clusters"),
                            use_container_width=True)
                        st.caption(f"Evolucao da metrica {col} conforme K varia. Valores de silhueta > 0.5 indicam clusters bem formados.")
                st.info("**Interpretacao:** O numero ideal de clusters e aquele onde a silhueta e maximizada e o Davies-Bouldin e minimizado.")
            som = pasta_motor("psicometria", edicao) / f"som_{chave_curso}.png"
            if som.exists():
                st.subheader("SOM - Self-Organizing Map")
                st.image(str(som), use_container_width=True)
                st.caption("O SOM projeta o espaco multidimensional em uma grelha 2D, preservando topologia. Areas de mesma cor indicam perfis cognitivos semelhantes.")
        else:
            st.warning("Execute o Motor de Clustering.")
            st.info(f"Os resultados devem estar na pasta {pasta_clust / 'metricas_*.csv'}.")
    else:
        st.info("Selecione um curso no painel lateral.")
