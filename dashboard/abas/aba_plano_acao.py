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
    curso_codigo = ctx["curso_codigo"]

    st.header("Plano de Acao por Perfil")
    st.markdown("""
    **Metodologia:** Esta aba cruza as dimensoes **genero**, **idade** e **notas** para construir
    um plano de acao diferenciado por perfil de aluno. Utiliza histogramas e tabelas de intervencao
    para orientar o NDE sobre prioridades pedagogicas direcionadas a cada subgrupo identificado.
    Tambem apresenta o diagnostico por questao com Objetos de Conhecimento (OCs), Perfil e Competencias.
    """)
    if df is None:
        st.info("Selecione um exame no painel lateral.")
    else:
        if df_curso is not None and not df_curso.empty:
            st.subheader("1. Perfil de Genero")
            if "TP_SEXO" in df_curso.columns:
                sm = {1: "Masculino", 2: "Feminino", "M": "Masculino", "F": "Feminino",
                      "m": "Masculino", "f": "Feminino", "1": "Masculino", "2": "Feminino"}
                tmp = df_curso["TP_SEXO"].map(sm).dropna().value_counts().reset_index()
                tmp.columns = ["Sexo", "N"]
                if not tmp.empty:
                    st.plotly_chart(px.pie(tmp, names="Sexo", values="N", title="Composicao por genero"),
                                   use_container_width=True)
                    st.caption("A composicao por genero indica se ha equidade na representatividade do curso.")
            st.subheader("2. Perfil Etario")
            if "NU_IDADE" in df_curso.columns:
                tmp_idade = df_curso["NU_IDADE"].dropna()
                if not tmp_idade.empty:
                    st.plotly_chart(px.histogram(tmp_idade, x="NU_IDADE", nbins=20,
                                                 color_discrete_sequence=["#3b82f6"],
                                                 title="Distribuicao etaria dos alunos"),
                                   use_container_width=True)
                    st.caption("Faixa etaria predominante indica se o curso atende estudantes tradicionais ou pos-graduandos.")
            st.subheader("3. Notas por Perfil")
            if "NT_GER" in df_curso.columns:
                df_tmp = df_curso.copy()
                if "TP_SEXO" in df_tmp.columns:
                    df_tmp["Genero"] = df_tmp["TP_SEXO"].map({1: "Masculino", 2: "Feminino", "M": "Masculino", "F": "Feminino",
                                                              "m": "Masculino", "f": "Feminino", "1": "Masculino", "2": "Feminino"})
                    st.plotly_chart(px.box(df_tmp, x="Genero", y="NT_GER", color="Genero",
                                           title="Distribuicao de Notas por Genero"),
                                   use_container_width=True)
                    st.caption("Comparacao da distribuicao de notas entre generos. Diferencas indicam necessidade de politicas de equidade.")
            st.subheader("4. Plano de Acao Sugerido")
            planos = []
            media_nac = df_nacional['NT_GER'].mean() if df_nacional is not None and "NT_GER" in df_nacional.columns else 0
            media_ies_val = df_curso['NT_GER'].mean() if "NT_GER" in df_curso.columns else 0
            if media_ies_val < media_nac * 0.9:
                planos.append(("Notas abaixo da media nacional", "Implementar programa de nivelamento com reforco nas disciplinas criticas."))
            if "TP_SEXO" in df_curso.columns:
                masculino_mask = df_curso["TP_SEXO"].isin([1, "M", "m", "1"])
                pct_masc = masculino_mask.sum() / len(df_curso) * 100
                if pct_masc < 30 or pct_masc > 70:
                    planos.append(("Desbalanco de genero", "Promover programas de inclusao e diversidade para equilibrar a representatividade."))
            if "NU_IDADE" in df_curso.columns:
                idade_med = df_curso["NU_IDADE"].mean()
                if pd.notna(idade_med) and idade_med > 28:
                    planos.append(("Perfil etario maduro", "Ofertar materiais flexiveis e horarios adaptados a vida profissional ativa."))
            if not planos:
                planos.append(("Perfil equilibrado", "Manter as acoes atuais e monitorar indicadores semestralmente."))
            df_planos = pd.DataFrame(planos, columns=["Diagnostico", "Acao Sugerida"])
            st.dataframe(df_planos, use_container_width=True)
            st.caption("Tabela de acoes prescritas com base nos indicadores do curso e comparacao nacional.")

            st.markdown("---")
            st.subheader("5. Acoes por Perfil de Aluno (Expanders)")
            st.markdown("Acoes diferenciadas por subgrupo identificado. Cada perfil recebe recomendacoes especificas.")
            if "TP_SEXO" in df_curso.columns:
                sm2 = {"M": "Masculino", "F": "Feminino", "m": "Masculino", "f": "Feminino",
                       "1": "Masculino", "2": "Feminino", 1: "Masculino", 2: "Feminino"}
                df_curso_gen = df_curso.copy()
                df_curso_gen["Genero"] = df_curso_gen["TP_SEXO"].map(sm2)
                for genero in ["Masculino", "Feminino"]:
                    sub = df_curso_gen[df_curso_gen["Genero"] == genero]
                    if not sub.empty:
                        with st.expander(f"Perfil: {genero} ({len(sub)} alunos)", expanded=False):
                            if "NT_GER" in sub.columns:
                                media_g = sub["NT_GER"].mean()
                                media_nac_g = media_nac if media_nac > 0 else media_g
                                delta_g = media_g - media_nac_g
                                ic1, ic2 = st.columns(2)
                                ic1.metric(f"Media {genero}", f"{media_g:.2f}")
                                ic2.metric("vs Nacional", f"{delta_g:+.2f}",
                                          delta="acima" if delta_g >= 0 else "abaixo",
                                          delta_color="normal" if delta_g >= 0 else "inverse")
                            st.caption(f"Perfil {genero}: programa de intervencao diferenciado para este subgrupo.")
            if "NU_IDADE" in df_curso.columns:
                faixas = {"18-25": (18, 25), "26-35": (26, 35), "36+": (36, 100)}
                for faixa_nome, (idade_min, idade_max) in faixas.items():
                    sub_id = df_curso[(df_curso["NU_IDADE"] >= idade_min) & (df_curso["NU_IDADE"] <= idade_max)]
                    if not sub_id.empty:
                        with st.expander(f"Perfil Etario: {faixa_nome} ({len(sub_id)} alunos)", expanded=False):
                            if "NT_GER" in sub_id.columns:
                                media_f = sub_id["NT_GER"].mean()
                                ic1, ic2 = st.columns(2)
                                ic1.metric(f"Media {faixa_nome}", f"{media_f:.2f}")
                                ic2.metric("N Alunos", f"{len(sub_id)}")
                            st.caption(f"Alunos na faixa {faixa_nome}: adaptar metodologias e horarios conforme perfil etario.")
            if "NT_GER" in df_curso.columns:
                media_geral = df_curso["NT_GER"].mean()
                if pd.notna(media_geral):
                    desempenho_grupos = {
                        "Critico (NT_GER < 40)": df_curso[df_curso["NT_GER"] < 40],
                        "Insuficiente (40-60)": df_curso[(df_curso["NT_GER"] >= 40) & (df_curso["NT_GER"] < 60)],
                        "Adequado (60-80)": df_curso[(df_curso["NT_GER"] >= 60) & (df_curso["NT_GER"] < 80)],
                        "Excelente (>=80)": df_curso[df_curso["NT_GER"] >= 80],
                    }
                    for nome_grupo_d, sub_d in desempenho_grupos.items():
                        if not sub_d.empty:
                            pct = len(sub_d) / len(df_curso) * 100
                            with st.expander(f"Nivel {nome_grupo_d} ({len(sub_d)} alunos, {pct:.1f}%)", expanded=False):
                                ic1, ic2, ic3 = st.columns(3)
                                ic1.metric("N Alunos", f"{len(sub_d)}")
                                ic2.metric("Percentual", f"{pct:.1f}%")
                                ic3.metric("Media NT_GER", f"{sub_d['NT_GER'].mean():.2f}")
                                if "Critico" in nome_grupo_d:
                                    st.warning("**Intervencao urgente:** Programa de reforco pedagogico com acompanhamento individualizado.")
                                elif "Insuficiente" in nome_grupo_d:
                                    st.info("**Intervencao preventiva:** Tutoria em grupo e pratica orientada nas areas criticas.")
                                elif "Excelente" in nome_grupo_d:
                                    st.success("**Manutencao:** Estudantes excelentes podem servir como monitores para os colegas.")
        else:
            st.info("Selecione uma IES e um curso no painel lateral para ver o perfil de genero, idade e notas.")

        st.markdown("---")
        st.subheader("Diagnostico por Questao: OCs, Perfil e Competencias")
        st.markdown("""
        **Nesta secao, o plano de acao e direcionado por questao.** Cada questao com alta taxa de erro
        e associada aos seus Objetos de Conhecimento (OCs), Perfil profissional e Competencias,
        permitindo que o NDE elabore intervencoes pedagogicas especificas para cada area do conhecimento.
        """)
        df_a = _carregar_analise_ies(_extrair_ano_filtro(sel_tipo, sel_id))
        if df_a is not None and not df_a.empty:
            df_filtrado = obter_filtro_analise(df_a, ies_sel, curso_codigo, sel_tipo, sel_id)
            if not df_filtrado.empty:
                df_questoes_plan = _medias_por_questao_analise(df_filtrado)
                if not df_questoes_plan.empty and "TAXA_DEFICIENCIA_%" in df_questoes_plan.columns:
                    questoes_criticas = df_questoes_plan[df_questoes_plan["TAXA_DEFICIENCIA_%"] >= 50].copy()
                    if not questoes_criticas.empty:
                        st.markdown(f"**{len(questoes_criticas)} questoes com deficiencia >= 50%** identificadas.")
                        for _, row in questoes_criticas.iterrows():
                            q_name = row.get("QUESTAO", "?")
                            taxa = row.get("TAXA_DEFICIENCIA_%", 0)
                            ocs = []
                            for c in questoes_criticas.columns:
                                if c.startswith("OC"):
                                    val = str(row.get(c, "")).strip()
                                    if val and val != "nan":
                                        ocs.append(val)
                            perfil_val = ""
                            for c in questoes_criticas.columns:
                                if "PERFIL" in c.upper():
                                    perfil_val = str(row.get(c, "")).strip()
                                    break
                            comp_val = ""
                            for c in questoes_criticas.columns:
                                if "COMPET" in c.upper():
                                    comp_val = str(row.get(c, "")).strip()
                                    break
                            cor = "red" if taxa >= 70 else "orange" if taxa >= 60 else "blue"
                            with st.container():
                                st.markdown(f"**{q_name}** -- Erro: :{cor}[{taxa:.1f}%]")
                                c1, c2 = st.columns(2)
                                with c1:
                                    if ocs:
                                        st.caption(f"**Objetos de Conhecimento:** {'; '.join(ocs)}")
                                    if perfil_val and perfil_val != "nan":
                                        st.caption(f"**Perfil:** {_curto(perfil_val, 100)}")
                                with c2:
                                    if comp_val and comp_val != "nan":
                                        st.caption(f"**Competencia:** {_curto(comp_val, 100)}")
                                acao_sugerida = f"Reforcar conteudo relacionado a(s) OC(s): {'; '.join(_oc_sem_prefixo(o) for o in ocs)}" if ocs else f"Revisar conteudo da questao {q_name}"
                                st.caption(f"Acao sugerida: **{acao_sugerida}**")
                    else:
                        st.info("Nenhuma questao com deficiencia >= 50% para este curso/IES.")
                    st.subheader("Mapa de OCs x Deficiencia")
                    colunas_oc_plan = [c for c in df_questoes_plan.columns if c.startswith("OC")]
                    if colunas_oc_plan:
                        oc_def_map = {}
                        for _, row in df_questoes_plan.iterrows():
                            taxa = row.get("TAXA_DEFICIENCIA_%", 0)
                            for col in colunas_oc_plan:
                                val = str(row.get(col, "")).strip()
                                if val and val != "nan":
                                    nome_oc = _oc_sem_prefixo(val)
                                    if nome_oc not in oc_def_map:
                                        oc_def_map[nome_oc] = []
                                    oc_def_map[nome_oc].append(taxa)
                        if oc_def_map:
                            dados_map = []
                            for oc, taxas in oc_def_map.items():
                                dados_map.append({
                                    "OC": oc, "Media_Erro_%": round(np.mean(taxas), 1),
                                    "Max_Erro_%": round(max(taxas), 1), "N_Itens": len(taxas)
                                })
                            df_map = pd.DataFrame(dados_map).sort_values("Media_Erro_%", ascending=False)
                            fig_map = px.bar(
                                df_map.head(12), x="OC", y="Media_Erro_%",
                                color="Media_Erro_%", color_continuous_scale="RdYlGn_r",
                                text="Media_Erro_%",
                                title="OCs com Maior Media de Erro -- Base para Plano de Acao por Questao",
                                hover_data=["Max_Erro_%", "N_Itens"])
                            fig_map.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
                            fig_map.update_layout(height=420, xaxis_tickangle=-45)
                            st.plotly_chart(fig_map, use_container_width=True)
                            st.caption("Cada barra representa um Objeto de Conhecimento e sua media de erro. "
                                       "OCs com barras altas devem ser priorizados no plano de acao do NDE.")
                            st.dataframe(df_map, use_container_width=True)
            else:
                st.info("Dados de analise por questao nao disponiveis para este curso/IES.")
