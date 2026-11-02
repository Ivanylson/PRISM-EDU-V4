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
    sel_tipo = ctx["sel_tipo"]

    st.header("Fatores de Sucesso (Preditivo)")
    st.markdown("""
    **Metodologia:** O motor preditivo identifica quais variaveis (questoes, caracteristicas socioeconomicas)
    mais contribuem para o sucesso ou fracasso do aluno. Utiliza **Random Forest** e **SHAP (TreeExplainer)**
    para explicabilidade honesta (sem simulacao). As importancias sao calculadas com validacao cruzada.
    """)
    edicao = selecionar_edicao_motor("shap", "fsucesso")
    pasta_shap = pasta_motor("shap", edicao)
    pasta_pred = pasta_motor("preditivos", edicao)
    if chave_curso:
        arq = _buscar("importancia", pasta_shap, chave_curso)
        if not arq:
            arq = _buscar("importancia_variaveis", pasta_pred, chave_curso)
        if arq:
            dfp = _ler(arq)
            cols_n = dfp.select_dtypes(include=[np.number]).columns.tolist()
            cols_s = dfp.select_dtypes(include=["object"]).columns.tolist()
            if cols_n and cols_s:
                st.plotly_chart(
                    px.bar(dfp.head(10), x=cols_n[0], y=cols_s[0], orientation="h",
                           color=cols_n[0], color_continuous_scale="Greens",
                           title=f"Top 10 Variaveis Mais Importantes -- {nome_curso}"),
                    use_container_width=True)
                st.info("**Interpretacao:** Variaveis com maior barra sao os fatores mais determinantes para o desempenho. "
                        "Variaveis socioeconomicas frequentemente superam variaveis academicas.")
            else:
                st.dataframe(dfp, use_container_width=True)
            arq_m = _buscar("metricas", pasta_shap, chave_curso)
            if arq_m:
                st.subheader("Metricas do Modelo")
                st.dataframe(_ler(arq_m), use_container_width=True)
                st.caption("Acuracia, F1-Score e AUC-ROC indicam a qualidade da predicao. Valores acima de 0.7 sao considerados bons.")
        else:
            st.warning("Nenhum resultado preditivo encontrado. Execute o Motor Preditivo.")
            st.info(f"Os arquivos de importancia devem estar na pasta {pasta_shap} ou {pasta_pred}. "
                    "Execute o algoritmo preditivo para a edicao/curso selecionados.")
    else:
        st.info("Selecione um curso no painel lateral.")
