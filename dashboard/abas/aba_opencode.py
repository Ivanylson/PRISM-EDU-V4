import json
import time
import threading
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
from dashboard.componentes.opencode import (
    servidor_opencode_ativo, _check_zen_rate_limit, iniciar_servidor_opencode,
    enviar_prompt_opencode, OPENCODE_SERVER_URL,
)
from config import MODELOS_OPENCODE, RAIZ_PROJETO, SEPARADOR


def render(ctx):
    chave_curso = ctx["chave_curso"]
    nome_curso = ctx["nome_curso"]

    st.header("OpenCode + IA Explicativa")
    st.markdown("""
    Selecione um arquivo CSV de resultados para gerar uma **explicacao em linguagem natural**,
    acessivel para nao-especialistas. O dashboard chama o **OpenCode.ai** via API HTTP
    para analisar os dados e produzir um texto explicativo com interpretacoes e recomendacoes.
    """)
    server_online = servidor_opencode_ativo()
    status_color = "\U0001f7e2" if server_online else "\U0001f534"
    status_text = "Online" if server_online else "Offline"
    rate_info = _check_zen_rate_limit() if server_online else {"limited": False}
    if rate_info.get("limited"):
        reset_at = rate_info.get("reset_at", "desconhecido")
        st.error(f"**Limite de uso gratuito Zen excedido** -- Reset previsto para **{reset_at}**.")
        status_text += " (limite excedido)"
    st.caption(f"{status_color} Servidor OpenCode: {status_text} -- {OPENCODE_SERVER_URL}")
    if not server_online:
        st.warning("Servidor OpenCode nao esta ativo.")
        if st.button("Iniciar Servidor OpenCode", use_container_width=True):
            with st.spinner("Iniciando servidor OpenCode..."):
                if iniciar_servidor_opencode():
                    st.success("Servidor iniciado!")
                    st.rerun()
                else:
                    st.error("Falha ao iniciar. Verifique se o OpenCode esta instalado.")

    st.subheader("1. Selecione o CSV para analise")
    edicao = selecionar_edicao_motor("opencode", "openc")
    csvs_disponiveis = []
    for motor in ["clustering", "shap", "cdm", "psicometria", "lca"]:
        pasta_resultado = pasta_motor(motor, edicao)
        if pasta_resultado.exists():
            csvs_disponiveis.extend(list(pasta_resultado.glob("*.csv")))
    if PASTA_EDA.exists():
        csvs_disponiveis.extend(list(PASTA_EDA.glob("*.csv")))
    csvs_validos = [p for p in csvs_disponiveis if p.stat().st_size <= 50 * 1024 * 1024]
    if not csvs_validos:
        st.error("Nenhum arquivo CSV encontrado nas pastas de resultados.")
    else:
        if chave_curso:
            curso_lower = chave_curso.lower()
            csvs_filtrados = [p for p in csvs_validos if curso_lower in p.stem.lower()]
            if not csvs_filtrados:
                csvs_filtrados = csvs_validos
        else:
            csvs_filtrados = csvs_validos
        csv_labels = {str(p.relative_to(p.parents[2]) if len(p.parents) > 2 else p.name): p for p in sorted(set(csvs_filtrados))}
        labels_ordenados = sorted(csv_labels.keys())
        csv_selecionado = st.selectbox("Arquivo CSV:", labels_ordenados, key="csv_selector")
        caminho_csv = csv_labels[csv_selecionado]

        st.subheader("2. Previa dos Dados")
        try:
            df_csv_preview = pd.read_csv(caminho_csv, sep=SEPARADOR, nrows=10, encoding="utf-8-sig", on_bad_lines="skip")
            st.dataframe(df_csv_preview, use_container_width=True)
            n_linhas = sum(1 for _ in open(caminho_csv, "r", encoding="utf-8-sig")) - 1
            n_cols = len(df_csv_preview.columns)
            st.caption(f"Mostrando 10 de ~{n_linhas} linhas | {n_cols} colunas | {caminho_csv.name}")
        except Exception as e:
            st.error(f"Erro ao ler CSV: {e}")
            st.stop()

        st.subheader("3. Personalize a Analise")
        col_model, col_tom = st.columns([1, 1])
        with col_model:
            modelo_id = st.selectbox("Modelo IA:", options=list(MODELOS_OPENCODE.keys()),
                                     format_func=lambda x: MODELOS_OPENCODE[x], index=0, key="modelo_opencode")
        with col_tom:
            tom = st.selectbox("Tom da explicacao:", ["Didatico e acessivel (para leigos)", "Tecnico e detalhado (para coordenadores)", "Resumo executivo (para diretores)", "Critico e propositivo (para melhoria)"], key="tom_ia")
        foco = st.text_area("Foco adicional (opcional):", placeholder="Ex: 'Destaque as principais deficiencias em Matematica'", key="foco_ia")

        st.subheader("4. Gerar Explicacao")
        gerar = st.button("Gerar Explicacao com OpenCode", type="primary", use_container_width=True, disabled=not server_online)

        if gerar:
            df_full = pd.read_csv(caminho_csv, sep=SEPARADOR, encoding="utf-8-sig", on_bad_lines="skip")
            resumo = {"arquivo": caminho_csv.name, "linhas": len(df_full), "colunas": list(df_full.columns),
                      "colunas_numericas": [c for c in df_full.columns if pd.api.types.is_numeric_dtype(df_full[c])],
                      "resumo_estatistico": {}}
            for c in resumo["colunas_numericas"][:10]:
                resumo["resumo_estatistico"][c] = {"media": round(float(df_full[c].mean()), 2), "min": round(float(df_full[c].min()), 2), "max": round(float(df_full[c].max()), 2)}
            amostra = df_full.head(5).to_string()
            prompt = f"""Analise o seguinte conjunto de dados educacionais do ENADE e gere uma explicacao em linguagem natural.

ARQUIVO: {caminho_csv.name}
TOM: {tom}
{'FOCO ADICIONAL: ' + foco if foco else ''}

RESUMO DOS DADOS:
- {resumo['linhas']} linhas, {len(resumo['colunas'])} colunas
- Colunas: {', '.join(resumo['colunas'][:15])}{'...' if len(resumo['colunas']) > 15 else ''}
- Colunas numericas: {', '.join(resumo['colunas_numericas'][:8])}

ESTATISTICAS BASICAS:
{json.dumps(resumo['resumo_estatistico'], indent=2, ensure_ascii=False)}

AMOSTRA (primeiras 5 linhas):
{amostra}

Com base nestes dados, produza uma explicacao que:
1. Contextualize o que sao estes dados
2. Destaque os principais achados e padroes
3. Aponte anomalias
4. Conclua com recomendacoes praticas
5. Seja acessivel para publico nao-especialista
"""
            prompt_preview = prompt[:75] + "..." if len(prompt) > 75 else prompt
            st.info(f"Modelo: **{MODELOS_OPENCODE[modelo_id]}** | Prompt: `{prompt_preview}`")
            response_container = st.empty()
            timer_container = st.empty()

            class TimerThread(threading.Thread):
                def __init__(self):
                    super().__init__(daemon=True)
                    self.running = True
                    self.elapsed = 0
                def run(self):
                    while self.running:
                        time.sleep(1)
                        self.elapsed += 1
                def stop(self):
                    self.running = False

            timer = TimerThread()
            timer.start()
            try:
                with st.status("Enviando prompt para OpenCode...", expanded=True) as status:
                    status.update(label=f"Processando com {MODELOS_OPENCODE[modelo_id]}... 0s", state="running")
                    def update_timer():
                        while timer.running:
                            timer_container.caption(f"Tempo decorrido: {timer.elapsed}s")
                            time.sleep(1)
                    timer_thread = threading.Thread(target=update_timer, daemon=True)
                    timer_thread.start()
                    resultado = enviar_prompt_opencode(prompt, model_id=modelo_id, timeout=300)
                    timer.stop()
                    timer_container.empty()
                    if resultado["success"]:
                        elapsed = resultado.get("elapsed", timer.elapsed)
                        status.update(label=f"Explicacao gerada em {elapsed}s!", state="complete")
                        st.markdown(f"### Explicacao Gerada -- {MODELOS_OPENCODE[modelo_id]}")
                        st.markdown("---")
                        st.markdown(resultado["response"])
                        st.download_button(label="Download da Explicacao (.md)", data=resultado["response"].encode("utf-8"), file_name=f"explicacao_opencode_{caminho_csv.stem}.md", mime="text/markdown", use_container_width=True)
                    else:
                        error_msg = resultado.get("error", "Erro desconhecido")
                        is_rate_limit = "limite" in error_msg.lower() or "excedido" in error_msg.lower()
                        if is_rate_limit:
                            status.update(label="Limite de uso Zen excedido", state="error")
                            reset_at = resultado.get("rate_limit_info", {}).get("reset_at", "desconhecido")
                            st.error("**Limite de uso gratuito do OpenCode Zen excedido.**")
                            st.info(f"Reset previsto para **{reset_at}**.")
                        else:
                            status.update(label=f"{error_msg[:50]}...", state="error")
                            st.warning(f"**Erro OpenCode:** {error_msg}")
                        st.markdown("### Analise Estatistica Automatica (fallback)")
                        st.markdown("---")
                        st.markdown(f"**Arquivo:** `{caminho_csv.name}`")
                        st.markdown(f"**Dimensoes:** {resumo['linhas']} linhas x {len(resumo['colunas'])} colunas")
                        st.markdown("---")
                        st.markdown("**Colunas numericas analisadas:**")
                        for col, stats in resumo["resumo_estatistico"].items():
                            st.markdown(f"- **{col}**: media={stats['media']}, min={stats['min']}, max={stats['max']}")
            except Exception as e:
                timer.stop()
                timer_container.empty()
                st.error(f"Erro ao gerar explicacao: {e}")

    st.markdown("---")
    st.subheader("5. Relatorios .md Gerados")
    pasta_md = RAIZ_PROJETO / "relatorios"
    mds = sorted(list(pasta_md.glob("*.md"))) if pasta_md.exists() else []
    if mds:
        nomes_md = [m.name for m in mds]
        md_selecionado = st.selectbox("Selecione um relatorio:", nomes_md, key="md_selector")
        caminho_md = next(m for m in mds if m.name == md_selecionado)
        try:
            conteudo_md = caminho_md.read_text(encoding="utf-8")
            st.markdown("---")
            st.markdown(conteudo_md)
        except Exception as e:
            st.error(f"Erro ao ler o arquivo .md: {e}")
    else:
        st.info("Nenhum relatorio .md encontrado na pasta de relatorios.")
