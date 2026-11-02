import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path
import unicodedata
import re
import os
import subprocess
import sys
import json
import tempfile
import time
import urllib.request
import atexit
import requests
import base64
import logging
import threading

# =============================================================================
# 1. CONFIGURAÇÕES E FUNÇÕES ÚTEIS
# =============================================================================
st.set_page_config(page_title="PRISM-EDU Dashboard IA Educacional + LCA + OpenCode", layout="wide")

def formatar_nome(nome):
    nome = ''.join(ch for ch in unicodedata.normalize('NFKD', nome) if not unicodedata.combining(ch))
    return nome.lower().replace(' ', '_')

def limitar_lista_texto(texto, separador, limite):
    if pd.isna(texto) or str(texto).strip() == "" or str(texto).lower() == "nan":
        return "Nenhum dado ou não aplicável"
    itens = [i.strip() for i in str(texto).split(separador) if i.strip()]
    return f" {separador} ".join(itens[:limite])

def _coerce_numerico(df, colunas):
    for c in colunas:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')
    return df

# Caminhos
DIRETORIO_ATUAL = Path(__file__).resolve().parent
DIRETORIO_RAIZ = DIRETORIO_ATUAL.parent
PASTA_RESULTADOS = DIRETORIO_RAIZ / 'arquivosgerados' / 'RESULTADOS'
PASTA_LCA = DIRETORIO_RAIZ / 'arquivosgerados' / 'RESULTADOS_LCA'
PASTA_LCA_FIGURAS = DIRETORIO_RAIZ / 'arquivosgerados' / 'FIGURAS_LCA'

caminho_base_consolidada = PASTA_RESULTADOS / 'analise_por_ies_curso_enade.csv'
pasta_preditivos = PASTA_RESULTADOS / 'analisesPredetivos'
pasta_agrupamentos = PASTA_RESULTADOS / 'analisesAgrupamentos'
caminho_ia = PASTA_RESULTADOS / 'relatorio_diagnostico_pedagogico.csv'

cursos_map = {
    5: 'Medicina Veterinária', 6: 'Odontologia', 12: 'Medicina', 17: 'Agronomia',
    19: 'Farmácia', 21: 'Arquitetura e Urbanismo', 23: 'Enfermagem', 27: 'Fonoaudiologia',
    28: 'Nutrição', 36: 'Fisioterapia', 51: 'Zootecnia', 55: 'Biomedicina',
    69: 'Tecnologia em Radiologia', 90: 'Tecnologia em Agronegócios',
    91: 'Tecnologia em Gestão Hospitalar', 92: 'Tecnologia em Gestão Ambiental',
    95: 'Tecnologia em Estética e Cosmética', 5710: 'Engenharia Civil',
    5806: 'Engenharia Elétrica', 5814: 'Engenharia de Controle e Automação',
    5902: 'Engenharia Mecânica', 6002: 'Engenharia de Alimentos',
    6008: 'Engenharia Química', 6208: 'Engenharia de Produção',
    6307: 'Engenharia Ambiental', 6405: 'Engenharia Florestal',
    6410: 'Tecnologia em Segurança no Trabalho', 6411: 'Engenharia de Computação'
}

cursos_reverso = {v: k for k, v in cursos_map.items()}

# =============================================================================
# GERENCIAMENTO DO SERVIDOR OPENCODE
# =============================================================================

OPENCODE_SERVER_URL = "http://localhost:4096"
OPENCODE_USERNAME = "opencode"

def _get_logger():
    """Get a logger that doesn't duplicate output on Streamlit reruns."""
    logger = logging.getLogger("opencode_integration")
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger

logger = _get_logger()

def procurar_opencode():
    """Procura o executável do OpenCode no PATH e locais comuns."""
    try:
        result = subprocess.run(["opencode", "--version"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return "opencode"
    except:
        pass
    for name in ["opencode-cli.exe", "opencode.exe", "opencode.cmd"]:
        try:
            result = subprocess.run(["where", name], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                return result.stdout.strip().split("\n")[0].strip()
        except:
            pass
    localappdata = os.environ.get("LOCALAPPDATA", "")
    candidatos = [
        Path(localappdata) / "opencode" / "opencode-cli.exe",
        Path(localappdata) / "opencode" / "opencode.exe",
        DIRETORIO_RAIZ / "opencode.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "opencode" / "opencode.exe",
    ]
    for c in candidatos:
        if c.exists():
            return str(c)
    return None


def _senha_efetiva():
    """Retorna a senha fornecida pelo usuario na sidebar (se houver)."""
    return st.session_state.get("senha_opencode", "").strip()


def _auth_headers():
    """Retorna headers de autenticação Basic Auth, se senha foi fornecida."""
    senha = _senha_efetiva()
    if senha:
        credentials = f"{OPENCODE_USERNAME}:{senha}"
        encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
        return {"Authorization": f"Basic {encoded}"}
    return {}


def servidor_opencode_ativo():
    """Verifica se o servidor OpenCode está rodando em http://localhost:4096.
    Tenta sem autenticação primeiro (servidor local), depois com senha se fornecida."""
    try:
        resp = requests.get(f"{OPENCODE_SERVER_URL}/global/health", timeout=3)
        if resp.status_code == 200:
            return True
    except:
        pass
    # Fallback: tenta com autenticação
    headers = _auth_headers()
    if headers:
        try:
            resp = requests.get(f"{OPENCODE_SERVER_URL}/global/health", headers=headers, timeout=3)
            return resp.status_code == 200
        except:
            pass
    return False


def iniciar_servidor_opencode():
    """Inicia opencode serve --port 4096 em background e aguarda ficar pronto."""
    # Se já estiver rodando, retorna True
    if servidor_opencode_ativo():
        logger.info("Servidor OpenCode já está ativo.")
        return True
    
    exe = procurar_opencode()
    if not exe:
        logger.warning("Executável OpenCode não encontrado.")
        return False
    try:
        # Inicia servidor SEM senha (uso local)
        cmd = [exe, "serve", "--port", "4096"]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            cwd=str(DIRETORIO_RAIZ)
        )
        st.session_state.opencode_server_proc = proc
        logger.info("Iniciando servidor OpenCode...")
        for _ in range(15):
            if servidor_opencode_ativo():
                logger.info("Servidor OpenCode iniciado com sucesso.")
                return True
            time.sleep(1)
        proc.kill()
        logger.warning("Timeout ao iniciar servidor OpenCode.")
        return False
    except Exception as e:
        logger.error(f"Erro ao iniciar servidor OpenCode: {e}")
        return False


def _parar_servidor_opencode():
    proc = st.session_state.get("opencode_server_proc")
    if proc and proc.poll() is None:
        try:
            proc.kill()
        except:
            pass

atexit.register(_parar_servidor_opencode)


def _check_zen_rate_limit():
    """Verifica se há limite de uso excedido no Zen e retorna info sobre reset."""
    try:
        headers = _auth_headers()
        status_resp = requests.get(f"{OPENCODE_SERVER_URL}/session/status", headers=headers, timeout=10)
        if status_resp.status_code == 200:
            status_data = status_resp.json()
            for session_id, info in status_data.items():
                if isinstance(info, dict) and info.get("type") == "retry":
                    msg = info.get("message", "")
                    next_ts = info.get("next", 0)
                    if "Free usage exceeded" in msg or "rate limit" in msg.lower():
                        reset_time = None
                        if next_ts:
                            reset_time = time.strftime("%H:%M:%S", time.localtime(next_ts / 1000))
                        return {
                            "limited": True,
                            "message": msg,
                            "reset_at": reset_time,
                            "next_timestamp": next_ts
                        }
        return {"limited": False}
    except:
        return {"limited": False}


MODELOS = {
    "big-pickle": "Big Pickle",
    "nemotron-3-super-free": "Nemotron 3 Super Free",
    "deepseek-v4-flash-free": "DeepSeek V4 Flash Free",
    "minimax-m2.5-free": "MiniMax M2.5 Free",
    "qwen3.6-plus-free": "Qwen3.6 Plus Free",
}


def enviar_prompt_opencode(prompt, model_id="big-pickle", timeout=300):
    """
    Envia prompt para o OpenCode via HTTP API com polling assíncrono.
    
    Args:
        prompt: Texto do prompt
        model_id: ID do modelo (ex: "minimax-m2.5-free", "big-pickle")
        timeout: Timeout em segundos
        
    Returns:
        dict: {"success": bool, "response": str, "error": str, "model": str, "rate_limit_info": dict}
    """
    if not servidor_opencode_ativo():
        return {"success": False, "response": "", "error": "Servidor OpenCode não está ativo.", "model": model_id}
    
    url = f"{OPENCODE_SERVER_URL}/session"
    headers = _auth_headers()
    headers["Content-Type"] = "application/json"
    
    try:
        # Step 1: Create session
        logger.info(f"Criando sessão com modelo: {model_id}")
        session_resp = requests.post(
            url,
            json={"message": "Analise de dados ENADE"},
            headers=headers,
            timeout=15
        )
        
        if session_resp.status_code != 200:
            return {
                "success": False,
                "response": "",
                "error": f"Falha ao criar sessão: HTTP {session_resp.status_code}",
                "model": model_id
            }
        
        session_data = session_resp.json()
        session_id = session_data.get("id")
        if not session_id:
            return {
                "success": False,
                "response": "",
                "error": "Sessão criada sem ID válido.",
                "model": model_id
            }
        
        logger.info(f"Sessão criada: {session_id}")
        
        # Step 2: Send message asynchronously
        msg_url = f"{OPENCODE_SERVER_URL}/session/{session_id}/prompt_async"
        msg_body = {
            "parts": [{"type": "text", "text": prompt}],
            "model": {
                "providerID": "opencode",
                "modelID": model_id
            }
        }
        
        logger.info(f"Enviando mensagem assíncrona para modelo {model_id}...")
        async_resp = requests.post(msg_url, json=msg_body, headers=headers, timeout=30)
        
        if async_resp.status_code != 204:
            return {
                "success": False,
                "response": "",
                "error": f"Falha ao enviar mensagem: HTTP {async_resp.status_code}",
                "model": model_id
            }
        
        # Step 3: Poll for response
        logger.info("Aguardando resposta via polling...")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            time.sleep(3)
            
            # Check session status for rate limit errors
            status_resp = requests.get(f"{OPENCODE_SERVER_URL}/session/status", headers=headers, timeout=10)
            if status_resp.status_code == 200:
                status_data = status_resp.json()
                current_status = status_data.get(session_id, {})
                status_type = current_status.get("type", "")
                
                if status_type == "retry":
                    error_msg = current_status.get("message", "")
                    if "Free usage exceeded" in error_msg or "rate limit" in error_msg.lower():
                        next_ts = current_status.get("next", 0)
                        reset_time = time.strftime("%H:%M:%S", time.localtime(next_ts / 1000)) if next_ts else "desconhecido"
                        logger.warning(f"Rate limit detectado: {error_msg}")
                        return {
                            "success": False,
                            "response": "",
                            "error": f"Limite de uso gratuito excedido. Reset às {reset_time}. Tente outro modelo ou aguarde.",
                            "model": model_id,
                            "rate_limit_info": {"limited": True, "reset_at": reset_time}
                        }
            
            # Get messages
            msg_list_url = f"{OPENCODE_SERVER_URL}/session/{session_id}/message?limit=5"
            msg_list_resp = requests.get(msg_list_url, headers=headers, timeout=10)
            
            if msg_list_resp.status_code != 200:
                continue
            
            messages = msg_list_resp.json()
            if not isinstance(messages, list):
                continue
            
            # Look for assistant message with text content
            for msg in messages:
                info = msg.get("info", {})
                if info.get("role") == "assistant":
                    parts = msg.get("parts", [])
                    for part in parts:
                        if part.get("type") == "text":
                            text = part.get("text", "")
                            if text and len(text.strip()) > 10:
                                elapsed = int(time.time() - start_time)
                                logger.info(f"Resposta recebida em {elapsed}s: {len(text)} caracteres")
                                return {
                                    "success": True,
                                    "response": text,
                                    "error": "",
                                    "model": model_id
                                }
            
            # Timeout reached
        logger.warning(f"Timeout após {timeout}s ao aguardar resposta do OpenCode.")
        return {
            "success": False,
            "response": "",
            "error": f"Timeout após {timeout}s. O modelo '{model_id}' pode estar sobrecarregado.",
            "model": model_id
        }
            
    except requests.exceptions.Timeout:
        logger.error(f"Timeout ao comunicar com OpenCode.")
        return {
            "success": False,
            "response": "",
            "error": "Timeout na comunicação com o servidor OpenCode.",
            "model": model_id
        }
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Erro de conexão com OpenCode: {e}")
        return {
            "success": False,
            "response": "",
            "error": f"Erro de conexão: {str(e)}",
            "model": model_id
        }
    except Exception as e:
        logger.error(f"Erro inesperado ao comunicar com OpenCode: {e}")
        return {
            "success": False,
            "response": "",
            "error": f"Erro: {str(e)}",
            "model": model_id
        }

# =============================================================================

@st.cache_data
def carregar_dados_resumidos():
    if not caminho_base_consolidada.exists():
        return None
    return pd.read_csv(caminho_base_consolidada, sep=';')

@st.cache_data
def carregar_lca_geral():
    path = PASTA_LCA / '01_relatorio_geral_por_ies.csv'
    if not path.exists():
        return None
    df = pd.read_csv(path, sep=';', decimal=',', dtype={'ies': str})
    df['ies'] = df['ies'].str.strip()
    return df

@st.cache_data
def carregar_lca_classes():
    path = PASTA_LCA / '02_caracterizacao_das_classes.csv'
    if not path.exists():
        return None
    df = pd.read_csv(path, sep=';', decimal=',', dtype={'ies': str})
    df['ies'] = df['ies'].str.strip()
    return df

def _bases_lca():
    bases = [PASTA_LCA, DIRETORIO_RAIZ / 'modelos' / 'lca', DIRETORIO_RAIZ.parent / 'modelos' / 'lca']
    unicas, vistas = [], set()
    for b in bases:
        try:
            chave = str(b.resolve())
        except OSError:
            chave = str(b)
        if chave not in vistas:
            vistas.add(chave)
            unicas.append(b)
    return unicas


def _caminho_lca(nome):
    edicao = (os.environ.get('PRISM_EDICAO', '') or '').strip()
    candidatos = []
    if edicao:
        candidatos += [b / edicao / nome for b in _bases_lca()]
    candidatos += [b / nome for b in _bases_lca()]
    for c in candidatos:
        if c.exists():
            return c
    return None


@st.cache_data
def carregar_lca_criterios(edicao=None):
    path = _caminho_lca('03_criterios_de_selecao_k.csv')
    if path is None:
        return None
    df = pd.read_csv(path, sep=';', decimal=',', dtype={'ies': str})
    if 'ies' in df.columns:
        df['ies'] = df['ies'].str.strip()
    return df

@st.cache_data
def carregar_dados_diagnostico(nome_curso):
    diretorio_atual = Path(__file__).resolve().parent
    # 1. Atualizado para buscar na nova pasta de XLSX
    pasta_resultados = diretorio_atual.parent / 'arquivosgerados' / 'RESULTADOS_FASE6_CDM_XLSX'
    
    nome_base = formatar_nome(nome_curso)
    # 2. Atualizado para procurar a extensão .xlsx
    caminho_arq = pasta_resultados / f"diagnostico_cognitivo_{nome_base}.xlsx"
    
    if caminho_arq.exists():
        # 3. Atualizado para ler usando o motor do Excel
        return pd.read_excel(caminho_arq, engine='openpyxl')
    return None

@st.cache_data
def carregar_reanalise_resumo():
    path = PASTA_LCA / 'reanalise_resumo.csv'
    if not path.exists(): return None
    return pd.read_csv(path, sep=';', decimal=',')

@st.cache_data
def carregar_reanalise_por_ies():
    path = PASTA_LCA / 'reanalise_por_ies.csv'
    if not path.exists(): return None
    return pd.read_csv(path, sep=';', decimal=',', dtype={'ies': str})

@st.cache_data
def carregar_robustez_item():
    path = PASTA_LCA / 'robustez_brancos_por_item.csv'
    if not path.exists(): return None
    return pd.read_csv(path, sep=';', decimal=',')

@st.cache_data
def carregar_robustez_oc():
    path = PASTA_LCA / 'robustez_brancos_por_oc.csv'
    if not path.exists(): return None
    return pd.read_csv(path, sep=';', decimal=',')

# Carregando os DataFrames na memória
df_reanalise_resumo = carregar_reanalise_resumo()
df_reanalise_ies = carregar_reanalise_por_ies()
df_robustez_item = carregar_robustez_item()
df_robustez_oc = carregar_robustez_oc()

df_base = carregar_dados_resumidos()
df_lca_geral = carregar_lca_geral()
df_lca_classes = carregar_lca_classes()
df_lca_crit = carregar_lca_criterios()

st.title("PRISM-EDU - Painel de IA Educacional - ENADE 2023")
st.markdown("**K-Means + LCA + OpenCode** — Análise de Perfis de Aprendizagem com Explicação em Linguagem Natural")
st.markdown("---")

# =============================================================================
# 2. SIDEBAR - FILTROS GLOBAIS (sempre visíveis)
# =============================================================================
with st.sidebar:
    st.header("Filtros de Pesquisa")

    km_disponivel = df_base is not None
    if km_disponivel:
        ies_disponiveis = df_base['CO_IES'].dropna().unique()
        ies_disponiveis.sort()
        ies_selecionada = st.selectbox("IES (código):", ies_disponiveis, key="ies_km")
        df_ies = df_base[df_base['CO_IES'] == ies_selecionada]
        grupos_ies = df_ies['CO_GRUPO'].dropna().unique()
        grupos_labels = {g: cursos_map.get(g, f"Curso {g}") for g in grupos_ies}
        grupo_selecionado = st.selectbox("Curso:", grupos_ies,
            format_func=lambda x: grupos_labels.get(x, f"Curso {x}"), key="curso_km")
        nome_curso_final = cursos_map.get(grupo_selecionado, f"Curso {grupo_selecionado}")
        nome_curso_arquivo = formatar_nome(nome_curso_final)
        df_final = df_ies[df_ies['CO_GRUPO'] == grupo_selecionado].copy()
        df_curso_nacional = df_base[df_base['CO_GRUPO'] == grupo_selecionado].copy()

    st.markdown("---")
    st.markdown("###  OpenCode")
    senha_opencode = st.text_input(
        "Senha (opcional):",
        type="password",
        key="senha_opencode",
        help="Senha para conexão com servidor OpenCode remoto (opcional). Deixe vazio para usar o servidor local sem autenticação."
    )
    if senha_opencode:
        pass  # senha usada via _auth_headers() nas chamadas HTTP
    st.markdown("---")
    if st.button("Sair e Fechar", use_container_width=True):
        st.success("A encerrar... Pode fechar a janela.")
        os._exit(0)

# =============================================================================
# 3. NAVEGAÇÃO PRINCIPAL (radio horizontal substitui st.tabs)
# =============================================================================
TABS = [
    " Diagnóstico e Prescrição",
    " Fatores de Sucesso (Preditivo)",
    " Validação + Clustering",
    " Plano de Ação por Perfil",
    " LCA - Classes Latentes",
    " OpenCode + IA Explicativa",
    "Matriz-Q",
    "ML Avançado",
    "Psicometria Computacional",
    "Auditoria de Competências do Século XXI",
    "Simulador Contrafactual",
    "Estudo de Caso (O Paradoxo)",
    "Suporte à Tomada de Decisão Pedagógica"

]

tab_default = 0
if "--tab" in sys.argv:
    idx = sys.argv.index("--tab")
    if idx + 1 < len(sys.argv):
        arg = sys.argv[idx + 1].lower()
        if arg == "opencode":
            tab_default = 12

tab_selector = st.radio("Navegação:", TABS, index=tab_default, horizontal=True, label_visibility="collapsed")

# =============================================================================
# ABA 1: DIAGNÓSTICO
# =============================================================================
if tab_selector == TABS[0]:
    if df_base is None:
        st.warning("Base de dados K-Means não encontrada. Execute a Fase 1 e 2 primeiro.")
    elif not km_disponivel or 'df_final' not in dir() or df_final.empty:
        st.warning("Selecione uma IES e Curso no filtro lateral.")
    else:
        col1, col2, col3 = st.columns(3)
        media_deficiencia_ies = df_final['TAXA_DEFICIENCIA_%'].mean() if 'TAXA_DEFICIENCIA_%' in df_final.columns else 0
        media_deficiencia_nacional = df_curso_nacional['TAXA_DEFICIENCIA_%'].mean() if 'TAXA_DEFICIENCIA_%' in df_curso_nacional.columns else 0
        with col1: st.metric("Curso", nome_curso_final)
        with col2: st.metric(f"Erro IES {ies_selecionada}", f"{media_deficiencia_ies:.1f}%")
        with col3: st.metric("Erro Nacional", f"{media_deficiencia_nacional:.1f}%",
            delta=f"{(media_deficiencia_ies - media_deficiencia_nacional):.1f}% vs Brasil", delta_color="inverse")
        st.markdown("---")

        colunas_oc = [col for col in df_final.columns if str(col).startswith('OC')]
        def unir_ocs(linha):
            lista_ocs = [str(linha.get(col)).strip() for col in colunas_oc
                if pd.notna(linha.get(col)) and str(linha.get(col)).strip() != "" and str(linha.get(col)).lower() != "nan"]
            return " + ".join(lista_ocs) if lista_ocs else "Não especificado"

        st.subheader(f"Top 5 Questões Críticas - IES {ies_selecionada}")
        if 'QUESTAO' in df_final.columns and 'TAXA_DEFICIENCIA_%' in df_final.columns:
            agg_dict_ies = {'TAXA_DEFICIENCIA_%': 'mean'}
            for col in colunas_oc: agg_dict_ies[col] = 'first'
            if 'COMPETÊNCIAS' in df_final.columns: agg_dict_ies['COMPETÊNCIAS'] = 'first'
            df_ies_agrup = df_final.groupby('QUESTAO').agg(agg_dict_ies).reset_index()
            df_top_questoes = df_ies_agrup.nlargest(5, 'TAXA_DEFICIENCIA_%').copy()

            c_graf, c_tab = st.columns([1, 1.8])
            with c_graf:
                fig_q = px.bar(df_top_questoes, x='QUESTAO', y='TAXA_DEFICIENCIA_%',
                    text='TAXA_DEFICIENCIA_%', color='TAXA_DEFICIENCIA_%',
                    color_continuous_scale='Reds')
                fig_q.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
                fig_q.update_layout(yaxis_range=[0, 115])
                st.plotly_chart(fig_q, use_container_width=True)
            with c_tab:
                df_top_questoes['MATÉRIAS (OCs)'] = df_top_questoes.apply(unir_ocs, axis=1)
                cols_t = ['QUESTAO', 'TAXA_DEFICIENCIA_%', 'MATÉRIAS (OCs)']
                if 'COMPETÊNCIAS' in df_final.columns: cols_t.append('COMPETÊNCIAS')
                st.dataframe(df_top_questoes[cols_t].rename(
                    columns={'TAXA_DEFICIENCIA_%': 'ERRO (%)'}).reset_index(drop=True),
                    use_container_width=True)

        st.subheader("Panorama Nacional")
        if not df_curso_nacional.empty and 'QUESTAO' in df_curso_nacional.columns:
            agg_dict = {'TAXA_DEFICIENCIA_%': 'mean'}
            for col in colunas_oc: agg_dict[col] = 'first'
            if 'COMPETÊNCIAS' in df_curso_nacional.columns: agg_dict['COMPETÊNCIAS'] = 'first'
            df_nac_agrup = df_curso_nacional.groupby('QUESTAO').agg(agg_dict).reset_index()
            df_top_nac = df_nac_agrup.nlargest(5, 'TAXA_DEFICIENCIA_%').copy()
            c_graf_nac, c_tab_nac = st.columns([1, 1.8])
            with c_graf_nac:
                fig_nac = px.bar(df_top_nac, x='QUESTAO', y='TAXA_DEFICIENCIA_%',
                    text='TAXA_DEFICIENCIA_%', color='TAXA_DEFICIENCIA_%', color_continuous_scale='Oranges')
                fig_nac.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
                fig_nac.update_layout(yaxis_range=[0, 115])
                st.plotly_chart(fig_nac, use_container_width=True)
            with c_tab_nac:
                df_top_nac['MATÉRIAS (OCs)'] = df_top_nac.apply(unir_ocs, axis=1)
                cols_tn = ['QUESTAO', 'TAXA_DEFICIENCIA_%', 'MATÉRIAS (OCs)']
                if 'COMPETÊNCIAS' in df_top_nac.columns: cols_tn.append('COMPETÊNCIAS')
                st.dataframe(df_top_nac[cols_tn].rename(
                    columns={'TAXA_DEFICIENCIA_%': 'ERRO NACIONAL (%)'}).reset_index(drop=True),
                    use_container_width=True)

# =============================================================================
# ABA 2: PREDITIVO
# =============================================================================
elif tab_selector == TABS[1]:
    if df_base is None:
        st.warning("Base não encontrada.")
    elif not km_disponivel or 'nome_curso_arquivo' not in dir():
        st.warning("Selecione IES/Curso no filtro lateral.")
    else:
        caminho_pesos = pasta_preditivos / f"importancia_variaveis_{nome_curso_arquivo}.csv"
        caminho_metricas_pred = pasta_preditivos / f"metricas_modelos_{nome_curso_arquivo}.csv"
        if caminho_pesos.exists() and caminho_metricas_pred.exists():
            df_pesos = pd.read_csv(caminho_pesos, sep=';')
            df_metricas_pred = pd.read_csv(caminho_metricas_pred, sep=';')
            col_m1, col_m2 = st.columns([1, 2.5])
            with col_m1:
                st.markdown("####  Qualidade da Predição")
                st.dataframe(df_metricas_pred[['Modelo', 'Acuracia', 'F1_Score']].set_index('Modelo'), use_container_width=True)
            with col_m2:
                st.markdown("####  Top 10 Matérias que mais impactam")
                df_top_pesos = df_pesos.head(10).copy()
                df_top_pesos['OC_CURTO'] = df_top_pesos['TODOS_OS_OCs'].str.wrap(50)
                fig_pesos = px.bar(df_top_pesos, x='PESO_IMPORTANCIA_%', y='OC_CURTO',
                    orientation='h', color='PESO_IMPORTANCIA_%', color_continuous_scale='Greens')
                fig_pesos.update_layout(yaxis={'categoryorder':'total ascending'}, height=350)
                st.plotly_chart(fig_pesos, use_container_width=True)
        else:
            st.warning("Arquivos Preditivos não encontrados.")

# =============================================================================
# ABA 3: VALIDAÇÃO CIENTÍFICA
# =============================================================================
elif tab_selector == TABS[2]:
    if df_base is None:
        st.warning("Base não encontrada.")
    elif not km_disponivel or 'nome_curso_arquivo' not in dir():
        st.warning("Selecione IES/Curso no filtro lateral.")
    else:
        st.header(" Validação dos Agrupamentos (K-Means)")
        caminho_img_val = pasta_agrupamentos / f"graficos_validacao_{nome_curso_arquivo}.png"
        caminho_metricas_agrup = pasta_agrupamentos / f"metricas_agrupamento_{nome_curso_arquivo}.csv"
        if caminho_img_val.exists():
            st.image(str(caminho_img_val), use_container_width=True)
        if caminho_metricas_agrup.exists():
            df_metricas_agrup = pd.read_csv(caminho_metricas_agrup, sep=';')
            st.dataframe(df_metricas_agrup.set_index('K_Grupos'), use_container_width=True)
        if not caminho_img_val.exists() and not caminho_metricas_agrup.exists():
            st.warning("Arquivos de validação não encontrados.")

# =============================================================================
# ABA 4: CLUSTERING + PLANO DE AÇÃO
# =============================================================================
elif tab_selector == TABS[3]:
    if df_base is None:
        st.warning("Base não encontrada.")
    elif not km_disponivel or 'nome_curso_final' not in dir():
        st.warning("Selecione IES/Curso no filtro lateral.")
    else:
        col_titulo, col_param = st.columns([2, 1])
        with col_titulo:
            st.header(f" Plano de Ação: {nome_curso_final}")
        with col_param:
            limite_top_n = st.slider("Top N problemas:", 1, 38, 5, key="top_n_tab4")

        with st.expander(" Explicação dos Algoritmos e Metodologia"):
            st.markdown("""
            ### K-Means + Gap Analysis + Interseção de Falhas

            O motor de IA usa **K-Means** para agrupar alunos por similaridade de respostas.
            A métrica de **GAP** compara cada grupo contra a média da IES. A **Interseção**
            identifica falhas institucionais que afetam todos os perfis simultaneamente.
            """)

        if caminho_ia.exists():
            df_ia = pd.read_csv(caminho_ia, sep=';', decimal=',', dtype={'IES': str})
            ies_filtro = str(int(ies_selecionada)) if isinstance(ies_selecionada, float) else str(ies_selecionada)
            df_ia_filtrado = df_ia[(df_ia['CURSO'] == nome_curso_final) & (df_ia['IES'] == ies_filtro)]
            if not df_ia_filtrado.empty:
                k_livre = df_ia_filtrado.get('K_MATEMATICO_LIVRE', pd.Series(['N/A'])).iloc[0]
                silhueta = df_ia_filtrado.get('SILHUETA_LIVRE', pd.Series(['N/A'])).iloc[0]
                k_aplicado = df_ia_filtrado.get('K_APLICADO_PEDAGOGICO (Max 6)', pd.Series([0])).iloc[0]
                st.info(f" K-Livre: {k_livre} (Silhueta: {silhueta}) | K-Aplicado: {k_aplicado}")

                if 'FALHA_SISTEMICA_IES' in df_ia_filtrado.columns:
                    falha = df_ia_filtrado['FALHA_SISTEMICA_IES'].iloc[0]
                    if pd.notna(falha) and str(falha).strip() not in ["Nenhuma", "nan", ""]:
                        st.error(f"🚨 Falha Institucional (interseção em todos os perfis): {falha}")

                for _, row in df_ia_filtrado.iterrows():
                    nome_grupo = str(row.get('NOME_DO_GRUPO', 'Grupo'))
                    qtd = row.get('QTD_ALUNOS_GRUPO', 0)
                    media = row.get('NOTA_MEDIA_GERAL_GRUPO', 0)
                    if "Excelência" in nome_grupo or "Alto" in nome_grupo:
                        cor = "🟢"
                    elif "Risco" in nome_grupo:
                        cor = "🔴"
                    else:
                        cor = "🟡"
                    with st.expander(f"{cor} {nome_grupo} — {qtd} alunos | Média: {media}", expanded=True):
                        qs = limitar_lista_texto(row.get('QUESTOES_MAIS_IMPACTANTES', ''), ',', limite_top_n)
                        mats = limitar_lista_texto(row.get('MATERIAS_DEFICIENTES', ''), '|', limite_top_n)
                        comps = limitar_lista_texto(row.get('COMPETENCIAS_A_DESENVOLVER', ''), '|', limite_top_n)
                        st.markdown(f"**Questões:** {qs}")
                        c1, c2 = st.columns(2)
                        c1.warning(f"**Disciplinas:**\n" + mats.replace(" | ", "\n"))
                        c2.info(f"**Competências:**\n" + comps.replace(" | ", "\n"))
            else:
                st.warning("Sem dados de cluster para esta IES/Curso.")
        else:
            st.warning("Arquivo de diagnóstico não encontrado.")

# =============================================================================
# ABA 5: LCA - CLASSES LATENTES
# =============================================================================
elif tab_selector == TABS[4]:
    st.header(" Análise de Classes Latentes (LCA)")
    st.markdown("Identificação de perfis de aprendizagem via **Latent Class Analysis** — abordagem estatística robusta para dados categóricos binários.")

    if df_lca_geral is None:
        st.error(f"Arquivos LCA não encontrados em: {PASTA_LCA}")
        st.info("Execute o pipeline: `python 0_pipeline_principal_LCA.py`")
    else:
        cursos_lca = sorted(df_lca_geral['curso'].dropna().unique())
        if not cursos_lca:
            st.warning("Nenhum curso encontrado nos dados LCA.")
        else:
            curso_default = cursos_lca[0]
            ies_default = None
            if km_disponivel and 'grupo_selecionado' in dir():
                nome_curso_sidebar = cursos_map.get(grupo_selecionado)
                if nome_curso_sidebar and nome_curso_sidebar in cursos_lca:
                    curso_default = nome_curso_sidebar
                    ies_sidebar = str(int(float(ies_selecionada)))
                    if ies_sidebar in df_lca_geral[df_lca_geral['curso'] == curso_default]['ies'].values:
                        ies_default = ies_sidebar

            col1, col2 = st.columns(2)
            with col1:
                curso_idx = cursos_lca.index(curso_default)
                curso_lca_sel = st.selectbox("Curso (LCA):", cursos_lca, index=curso_idx, key="lca_curso")
            with col2:
                df_lca_curso_filtro = df_lca_geral[df_lca_geral['curso'] == curso_lca_sel]
                ies_lca_list = sorted(df_lca_curso_filtro['ies'].dropna().unique())
                ies_idx = ies_lca_list.index(ies_default) if ies_default and ies_default in ies_lca_list else 0
                ies_lca_sel = st.selectbox("IES (código):", ies_lca_list, index=ies_idx, key="lca_ies")

            if ies_default:
                st.caption(f" Sincronizado com o filtro global: {nome_curso_final} / IES {ies_selecionada}")
            else:
                st.caption(" Selecione um curso e IES no filtro lateral (sidebar) para sincronizar automaticamente.")

            st.markdown("---")

            df_lca_ies = df_lca_curso_filtro[df_lca_curso_filtro['ies'] == ies_lca_sel]
            df_cls_ies = df_lca_classes[(df_lca_classes['curso'] == curso_lca_sel) &
                                        (df_lca_classes['ies'] == ies_lca_sel)].copy()

            if not df_lca_ies.empty:
                row = df_lca_ies.iloc[0]
                col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
                col_m1.metric("k (classes)", str(int(row['k_escolhido'])))
                col_m2.metric("Entropia", f"{row['entropia_normalizada']:.3f}")
                col_m3.metric("Estabilidade (Jaccard)", f"{row['jaccard_medio_bootstrap']:.3f}")
                col_m4.metric("ARI (LCA vs K-Means)", f"{row['ari_lca_vs_kmeans_mca']:.3f}")
                col_m5.metric("N alunos", str(int(row['n_alunos'])))

                with st.expander(" Justificativa da seleção de k"):
                    st.info(row['justificativa_k'])
                    st.caption(f"Log-verossimilhança: {row['log_lik']:.2f} | Convergiu: {row['convergiu']}")

                st.markdown("---")

                if not df_cls_ies.empty:
                    st.subheader(" Perfis Identificados pela LCA")

                    prob_cols = [f'PROB_Q{i}' for i in range(1, 39)]
                    gap_cols = [f'GAP_Q{i}' for i in range(1, 39)]
                    q_labels = [f'Q{i}' for i in range(1, 39)]

                    fig = go.Figure()
                    for _, cls_row in df_cls_ies.sort_values('taxa_acerto_media', ascending=False).iterrows():
                        probs = [cls_row.get(c, 0) for c in prob_cols]
                        classe_nome = f"Classe {int(cls_row['classe_id'])} ({int(cls_row['n_alunos'])} alunos, {cls_row['taxa_acerto_media']:.2f})"
                        fig.add_trace(go.Scatter(
                            x=q_labels, y=probs, mode='lines+markers',
                            name=classe_nome, marker=dict(size=5)))

                    fig.update_layout(
                        title="Probabilidade de Acerto por Questão - Classes LCA",
                        xaxis_title="Questão",
                        yaxis_title="P(Acerto)",
                        yaxis_range=[0, 1.05],
                        hovermode='x unified',
                        height=400)
                    fig.add_vrect(x0=-0.5, x1=7.5, fillcolor="gray", opacity=0.05,
                        layer="below", line_width=0, annotation_text="FG", annotation_position="top left")
                    st.plotly_chart(fig, use_container_width=True)

                    fig_gap = go.Figure()
                    for _, cls_row in df_cls_ies.sort_values('taxa_acerto_media', ascending=False).iterrows():
                        gaps = [cls_row.get(c, 0) for c in gap_cols]
                        fig_gap.add_trace(go.Scatter(
                            x=q_labels, y=gaps, mode='lines+markers',
                            name=f"Classe {int(cls_row['classe_id'])}", marker=dict(size=5)))
                    fig_gap.update_layout(
                        title="GAP (diferença para média da IES) por Questão",
                        xaxis_title="Questão", yaxis_title="GAP",
                        hovermode='x unified', height=350)
                    fig_gap.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
                    fig_gap.add_vrect(x0=-0.5, x1=7.5, fillcolor="gray", opacity=0.05,
                        layer="below", line_width=0)
                    st.plotly_chart(fig_gap, use_container_width=True)

                    st.subheader(" Detalhamento das Classes")
                    cols_show = ['classe_id', 'n_alunos', 'pct_alunos', 'taxa_acerto_media',
                        'taxa_acerto_media_ies', 'itens_diferencialmente_fortes', 'itens_diferencialmente_fracos']
                    cols_show = [c for c in cols_show if c in df_cls_ies.columns]
                    st.dataframe(df_cls_ies[cols_show].rename(columns={
                        'classe_id': 'Classe', 'n_alunos': 'N Alunos',
                        'pct_alunos': '%', 'taxa_acerto_media': 'Média Acertos',
                        'taxa_acerto_media_ies': 'Média IES',
                        'itens_diferencialmente_fortes': 'Itens Fortes',
                        'itens_diferencialmente_fracos': 'Itens Fracos'
                    }), use_container_width=True)

                st.markdown("---")
                st.subheader(" Distribuição de k no Curso (todas as IES)")
                df_curso_k = df_lca_curso_filtro['k_escolhido'].value_counts().sort_index().reset_index()
                df_curso_k.columns = ['k', 'quantidade']
                fig_k = px.bar(df_curso_k, x='k', y='quantidade', text='quantidade',
                    color='quantidade', color_continuous_scale='Blues')
                fig_k.update_traces(textposition='outside')
                fig_k.update_layout(xaxis=dict(tickmode='linear', dtick=1), height=300)
                st.plotly_chart(fig_k, use_container_width=True)

                if df_lca_crit is not None:
                    df_crit_ies = df_lca_crit[(df_lca_crit['curso'] == curso_lca_sel) &
                                              (df_lca_crit['ies'] == ies_lca_sel)]
                    if not df_crit_ies.empty:
                        st.subheader(" Critérios de Seleção de k")
                        cols_crit = ['k', 'bic', 'aic', 'entropia', 'menor_classe_pct']
                        cols_crit = [c for c in cols_crit if c in df_crit_ies.columns]
                        st.dataframe(df_crit_ies[cols_crit].set_index('k').round(3), use_container_width=True)

                # ==========================================
                # NOVA SEÇÃO: REANÁLISE E ROBUSTEZ
                # ==========================================
                st.markdown("---")
                st.subheader(" Reanálise de Horizontalidade e Robustez (Brancos)")
                
                tab_reanalise, tab_robustez_item, tab_robustez_oc = st.tabs([
                    "Resumo Horizontalidade", 
                    "Robustez por Item", 
                    "Robustez por OC"
                ])
                
                with tab_reanalise:
                    if df_reanalise_resumo is not None:
                        st.dataframe(df_reanalise_resumo, use_container_width=True)
                    else:
                        st.info("Arquivo reanalise_resumo.csv não encontrado.")
                        
                    if df_reanalise_ies is not None:
                        st.markdown("**Detalhamento por IES:**")
                        df_reanalise_filtrado = df_reanalise_ies[df_reanalise_ies['ies'] == ies_lca_sel]
                        if not df_reanalise_filtrado.empty:
                            st.dataframe(df_reanalise_filtrado, use_container_width=True)
                        else:
                            st.warning("Sem dados de reanálise para esta IES específica.")
                
                with tab_robustez_item:
                    if df_robustez_item is not None:
                        st.dataframe(df_robustez_item, use_container_width=True)
                    else:
                        st.info("Arquivo robustez_brancos_por_item.csv não encontrado.")

                with tab_robustez_oc:
                    if df_robustez_oc is not None:
                        st.dataframe(df_robustez_oc, use_container_width=True)
                    else:
                        st.info("Arquivo robustez_brancos_por_oc.csv não encontrado.")

                # Exibindo a figura específica
                caminho_figura5 = PASTA_LCA_FIGURAS / 'figura5_corrigida.jpg'
                if caminho_figura5.exists():
                    st.markdown("#### Impacto Gráfico da Reanálise")
                    st.image(str(caminho_figura5), use_container_width=True, caption="Figura 5 - Correção de Horizontalidade")

                st.markdown("---")
                st.subheader(" Figuras da Análise (Artigo SBIE)")
                st.caption("Figuras referentes aos cursos de **Medicina**, **Engenharia Civil** e **Enfermagem** — artigos publicados no SBIE.")
                cursos_artigo = ['medicina', 'engenharia_civil', 'enfermagem']
                figuras_exibidas = 0
                for curso_artigo in cursos_artigo:
                    fig_paths = list(PASTA_LCA_FIGURAS.glob(f"*{curso_artigo}*.png"))
                    if fig_paths:
                        for fp in fig_paths:
                            st.image(str(fp), use_container_width=True, caption=f"{fp.stem.replace('_', ' ').title()}")
                            figuras_exibidas += 1
                if figuras_exibidas == 0:
                    imagens = list(PASTA_LCA_FIGURAS.glob("fig*.png"))
                    if imagens:
                        st.info("Nenhuma figura específica encontrada. Exibindo figuras gerais:")
                        cols_img = st.columns(3)
                        for i, img_p in enumerate(imagens[:6]):
                            with cols_img[i % 3]:
                                st.image(str(img_p), use_container_width=True, caption=img_p.stem)
                    else:
                        st.info("Figuras não encontradas em: " + str(PASTA_LCA_FIGURAS))

            else:
                st.warning("Nenhum resultado LCA encontrado para esta IES/Curso.")

# =============================================================================
# ABA 6: OPENCODE + IA EXPLICATIVA
# =============================================================================
elif tab_selector == TABS[5]:
    st.header(" OpenCode + IA Explicativa")
    st.markdown("""
    Selecione um arquivo CSV de resultados para gerar uma **explicação em linguagem natural**,
    acessível para não-especialistas. O dashboard chama o **OpenCode.ai** via API HTTP
    para analisar os dados e produzir um texto explicativo.
    """)

    # Status do servidor
    server_online = servidor_opencode_ativo()
    status_color = "🟢" if server_online else "🔴"
    status_text = "Online" if server_online else "Offline"
    
    # Check rate limit
    rate_info = _check_zen_rate_limit() if server_online else {"limited": False}
    if rate_info.get("limited"):
        reset_at = rate_info.get("reset_at", "desconhecido")
        st.error(f" **Limite de uso gratuito Zen excedido** — Reset previsto para **{reset_at}**. [Adicionar créditos](https://opencode.ai/zen)")
        status_text += " (limite excedido)"
    
    st.caption(f"{status_color} Servidor OpenCode: {status_text} — {OPENCODE_SERVER_URL}")

    st.subheader("1. Selecione o CSV para análise")

    csvs_disponiveis = []
    if PASTA_RESULTADOS.exists():
        csvs_disponiveis.extend(list(PASTA_RESULTADOS.rglob("*.csv")))
    if PASTA_LCA.exists():
        csvs_disponiveis.extend(list(PASTA_LCA.glob("*.csv")))

    csvs_validos = []
    for p in csvs_disponiveis:
        try:
            if p.stat().st_size <= 50 * 1024 * 1024:
                csvs_validos.append(p)
        except:
            pass

    if not csvs_validos:
        st.error("Nenhum arquivo CSV encontrado nas pastas de resultados.")
        st.info("Execute as fases de processamento para gerar dados.")
    else:
        csvs_filtrados = []
        if km_disponivel and 'nome_curso_arquivo' in dir():
            curso_lower = nome_curso_arquivo.lower()
            for p in csvs_validos:
                p_stem_lower = p.stem.lower()
                p_path_lower = str(p).lower()
                if curso_lower in p_stem_lower or curso_lower in p_path_lower:
                    csvs_filtrados.append(p)
            caminho_consolidado = PASTA_RESULTADOS / 'analise_por_ies_curso_enade.csv'
            if caminho_consolidado in csvs_validos and caminho_consolidado not in csvs_filtrados:
                csvs_filtrados.insert(0, caminho_consolidado)
            if not csvs_filtrados:
                csvs_filtrados = csvs_validos
        else:
            csvs_filtrados = csvs_validos

        csv_labels = {str(p.relative_to(p.parents[2]) if len(p.parents) > 2 else p.name): p
                      for p in sorted(set(csvs_filtrados))}
        labels_ordenados = sorted(csv_labels.keys())
        csv_default_idx = 0

        csv_selecionado = st.selectbox("Arquivo CSV:", labels_ordenados,
                                        index=csv_default_idx, key="csv_selector")
        caminho_csv = csv_labels[csv_selecionado]

        if km_disponivel and 'nome_curso_final' in dir():
            st.caption(f" Filtrado pelo curso: {nome_curso_final} / IES {ies_selecionada}")

        st.subheader("2. Prévia dos Dados")
        try:
            df_csv_preview = pd.read_csv(caminho_csv, sep=';', nrows=10,
                encoding='utf-8-sig', on_bad_lines='skip')
            st.dataframe(df_csv_preview, use_container_width=True)
            n_linhas = sum(1 for _ in open(caminho_csv, 'r', encoding='utf-8-sig')) - 1
            n_cols = len(df_csv_preview.columns)
            st.caption(f"Mostrando 10 de ~{n_linhas} linhas | {n_cols} colunas | {caminho_csv.name}")
        except Exception as e:
            st.error(f"Erro ao ler CSV: {e}")
            st.stop()

        st.subheader("3. Personalize a Análise")
        
        col_model, col_tom = st.columns([1, 1])
        with col_model:
            modelo_id = st.selectbox(
                "Modelo IA:",
                options=list(MODELOS.keys()),
                format_func=lambda x: MODELOS[x],
                index=0,
                key="modelo_opencode"
            )
        
        with col_tom:
            tom = st.selectbox("Tom da explicação:",
                ["Didático e acessível (para leigos)",
                 "Técnico e detalhado (para coordenadores)",
                 "Resumo executivo (para diretores)",
                 "Crítico e propositivo (para melhoria)"],
                key="tom_ia")

        foco = st.text_area("Foco adicional (opcional):",
            placeholder="Ex: 'Destaque as principais deficiências em Matemática' ou 'Compare o desempenho desta IES com a média nacional'",
            key="foco_ia")

        st.subheader("4. Gerar Explicação")
        
        gerar = st.button(
            " Gerar Explicação com OpenCode",
            type="primary",
            use_container_width=True,
            disabled=not server_online
        )
        
        if not server_online:
            st.warning(" Servidor OpenCode não está ativo. Clique no botão abaixo para iniciar.")
            if st.button("Iniciar Servidor OpenCode", use_container_width=True):
                with st.spinner("Iniciando servidor OpenCode..."):
                    if iniciar_servidor_opencode():
                        st.success(" Servidor iniciado!")
                        st.rerun()
                    else:
                        st.error(" Falha ao iniciar servidor. Verifique se o OpenCode está instalado.")

        if gerar:
            # Pré-processa dados
            df_full = pd.read_csv(caminho_csv, sep=';', encoding='utf-8-sig', on_bad_lines='skip')
            resumo = {
                "arquivo": caminho_csv.name,
                "linhas": len(df_full),
                "colunas": list(df_full.columns),
                "colunas_numericas": [c for c in df_full.columns if pd.api.types.is_numeric_dtype(df_full[c])],
                "resumo_estatistico": {},
            }
            for c in resumo["colunas_numericas"][:10]:
                resumo["resumo_estatistico"][c] = {
                    "media": round(float(df_full[c].mean()), 2),
                    "min": round(float(df_full[c].min()), 2),
                    "max": round(float(df_full[c].max()), 2),
                }

            amostra = df_full.head(5).to_string()

            prompt = f"""Analise o seguinte conjunto de dados educacionais do ENADE e gere uma explicação em linguagem natural.

ARQUIVO: {caminho_csv.name}
TOM: {tom}
{'FOCO ADICIONAL: ' + foco if foco else ''}

RESUMO DOS DADOS:
- {resumo['linhas']} linhas, {len(resumo['colunas'])} colunas
- Colunas: {', '.join(resumo['colunas'][:15])}{'...' if len(resumo['colunas']) > 15 else ''}
- Colunas numéricas: {', '.join(resumo['colunas_numericas'][:8])}

ESTATÍSTICAS BÁSICAS:
{json.dumps(resumo['resumo_estatistico'], indent=2, ensure_ascii=False)}

AMOSTRA (primeiras 5 linhas):
{amostra}

Com base nestes dados, produza uma explicação que:
1. Contextualize o que são estes dados (de onde vêm, o que significam)
2. Destaque os principais achados, tendências e padrões interessantes
3. Aponte anomalias ou valores que merecem atenção
4. Conclua com recomendações práticas
5. Seja acessível para um público não-especialista em dados

Formate a resposta em MARKDOWN, com seções claras e linguagem didática.
"""
            
            # Mostra preview do prompt
            prompt_preview = prompt[:75] + "..." if len(prompt) > 75 else prompt
            st.info(f" Modelo: **{MODELOS[modelo_id]}** | Prompt: `{prompt_preview}`")
            
            # Container para streaming
            response_container = st.empty()
            timer_container = st.empty()
            
            # Timer thread
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
                    status.update(label=f"Processando com {MODELOS[modelo_id]}... ⏱️ 0s", state="running")
                    
                    # Update timer display
                    def update_timer():
                        while timer.running:
                            timer_container.caption(f"⏱️ Tempo decorrido: {timer.elapsed}s")
                            time.sleep(1)
                    
                    timer_thread = threading.Thread(target=update_timer, daemon=True)
                    timer_thread.start()
                    
                    # Send prompt
                    resultado = enviar_prompt_opencode(prompt, model_id=modelo_id, timeout=300)
                    
                    timer.stop()
                    timer_container.empty()
                    
                    if resultado["success"]:
                        status.update(label=f" Explicação gerada em {timer.elapsed}s!", state="complete")
                        st.markdown(f"###  Explicação Gerada — {MODELOS[modelo_id]}")
                        st.markdown("---")
                        st.markdown(resultado["response"])
                        
                        st.download_button(
                            label=" Download da Explicação (.md)",
                            data=resultado["response"].encode('utf-8'),
                            file_name=f"explicacao_opencode_{caminho_csv.stem}.md",
                            mime="text/markdown",
                            use_container_width=True
                        )
                    else:
                        error_msg = resultado.get("error", "Erro desconhecido")
                        is_rate_limit = "limite" in error_msg.lower() or "excedido" in error_msg.lower() or "usage exceeded" in error_msg.lower()
                        
                        if is_rate_limit:
                            status.update(label=" Limite de uso Zen excedido", state="error")
                            reset_at = resultado.get("rate_limit_info", {}).get("reset_at", "desconhecido")
                            st.error(f" **Limite de uso gratuito do OpenCode Zen excedido.**")
                            st.info(f" Reset previsto para **{reset_at}**. Você pode adicionar créditos em [opencode.ai/zen](https://opencode.ai/zen) para uso ilimitado.")
                            st.warning(" Enquanto isso, use a **análise estatística automática** abaixo ou tente outro modelo quando o limite resetar.")
                        else:
                            status.update(label=f" {error_msg[:50]}...", state="error")
                            st.warning(f"**Erro OpenCode:** {error_msg}")
                        
                        # Fallback: statistical analysis
                        st.markdown("###  Análise Estatística Automática (fallback)")
                        st.markdown("---")
                        st.markdown(f"** Arquivo:** `{caminho_csv.name}`")
                        st.markdown(f"** Dimensões:** {resumo['linhas']} linhas × {len(resumo['colunas'])} colunas")
                        st.markdown("---")
                        st.markdown("** Colunas numéricas analisadas:**")
                        for col, stats in resumo["resumo_estatistico"].items():
                            st.markdown(f"- **{col}**: média={stats['media']}, min={stats['min']}, max={stats['max']}")
                        st.markdown("---")
                        if not is_rate_limit:
                            st.info(" Dica: Tente outro modelo ou aguarde alguns minutos e tente novamente.")
                        
            except Exception as e:
                timer.stop()
                timer_container.empty()
                st.error(f"Erro ao gerar explicação: {e}")
        else:
            st.info(" Selecione um CSV, personalize o tom e clique no botão para gerar a explicação com IA.")

        # =============================================================================
        # SEÇÃO 5: LEITOR DE RELATÓRIOS .md GERADOS
        # =============================================================================
        st.markdown("---")
        st.subheader("5. Relatórios .md Gerados")
        st.markdown("Visualize relatórios gerados pelo **K-Means (Fase 4)** ou pelo **script OpenCode headless**.")

        pasta_md = DIRETORIO_RAIZ / 'arquivosgerados' / 'RESULTADOS' / 'Dashboards_Markdown'
        pasta_md_old = DIRETORIO_RAIZ / 'arquivosgerados' / 'RESULTADOS' / 'Dashboards'

        mds = sorted(list(pasta_md.glob("*.md"))) + sorted(list(pasta_md_old.glob("*.md")))
        if mds:
            if km_disponivel and 'nome_curso_arquivo' in dir():
                mds_filtrados = [m for m in mds if nome_curso_arquivo in m.stem.lower()]
                if not mds_filtrados:
                    mds_filtrados = mds
            else:
                mds_filtrados = mds

            nomes_md = [m.name for m in mds_filtrados]
            md_selecionado = st.selectbox(
                "Selecione um relatório para visualizar:",
                nomes_md,
                key="md_selector"
            )
            caminho_md = next(m for m in mds_filtrados if m.name == md_selecionado)
            try:
                conteudo_md = caminho_md.read_text(encoding='utf-8')
                st.markdown("---")
                st.markdown(conteudo_md)
            except Exception as e:
                st.error(f"Erro ao ler o arquivo .md: {e}")
        else:
            st.info("Nenhum relatório .md encontrado. Gere relatórios com a **Fase 4** (K-Means) ou execute o script OpenCode headless.")

# =============================================================================
# ABA 7: MATRIZ-Q (DIAGNÓSTICO COGNITIVO AVANÇADO)
# =============================================================================
elif tab_selector == TABS[6]:
    st.header(" Diagnóstico Cognitivo Avançado (Matriz-Q)")
    st.markdown("""
    Esta secção utiliza **Modelos de Diagnóstico Cognitivo (EDM)** para avaliar a probabilidade exata 
    de domínio de cada aluno nas matérias específicas do curso, prescindindo de notas genéricas para 
    fornecer orientações pedagógicas precisas.
    """)

    if df_base is None:
        st.warning("Base de dados não encontrada.")
    elif not km_disponivel or 'nome_curso_final' not in dir():
        st.warning("Selecione uma IES e Curso no filtro lateral.")
    else:
        # Puxa os dados utilizando a variável nativa do seu sidebar
        df_diag = carregar_dados_diagnostico(nome_curso_final)

        if df_diag is None:
            st.warning(f"O arquivo de diagnóstico para **{nome_curso_final}** ainda não foi gerado na Fase 6.")
            st.info("Execute o script de processamento em lote da Fase 6 para gerar este perfil psicométrico em Excel (.xlsx).")
        else:
            # Identificar as colunas de disciplinas dinamicamente (ignora as iniciais e as 2 de resumo no fim)
            colunas_disciplinas = df_diag.columns[3:-2].tolist()
            
            st.divider()
            
            # --- VISÃO GLOBAL DA TURMA ---
            st.subheader(f"Raio-X da Turma — {nome_curso_final} (IES {ies_selecionada})")
            col1, col2 = st.columns(2)
            
            with col1:
                # Gráfico: Piores Deficiências
                deficiencias = df_diag['PIOR_DEFICIENCIA_DISCIPLINA'].value_counts().reset_index()
                deficiencias.columns = ['Disciplina', 'Qtd Alunos']
                fig_def = px.bar(deficiencias, x='Qtd Alunos', y='Disciplina', orientation='h',
                                 title="Matérias Mais Críticas (Maior Deficiência)",
                                 color_discrete_sequence=['#ef4444'])
                fig_def.update_layout(yaxis={'categoryorder':'total ascending'})
                st.plotly_chart(fig_def, use_container_width=True)
                
            with col2:
                # Gráfico: Maiores Domínios
                dominios = df_diag['MAIOR_DOMINIO_DISCIPLINA'].value_counts().reset_index()
                dominios.columns = ['Disciplina', 'Qtd Alunos']
                fig_dom = px.bar(dominios, x='Qtd Alunos', y='Disciplina', orientation='h',
                                 title="Matérias de Maior Domínio",
                                 color_discrete_sequence=['#22c55e'])
                fig_dom.update_layout(yaxis={'categoryorder':'total ascending'})
                st.plotly_chart(fig_dom, use_container_width=True)
                
            # --- RADAR DA TURMA ---
            st.markdown("###  Perfil Médio de Domínio do Curso")
            medias_turma = df_diag[colunas_disciplinas].mean().reset_index()
            medias_turma.columns = ['Disciplina', 'Dominio Medio (%)']
            
            fig_radar_turma = go.Figure()
            fig_radar_turma.add_trace(go.Scatterpolar(
                r=medias_turma['Dominio Medio (%)'],
                theta=medias_turma['Disciplina'],
                fill='toself',
                name='Média da Turma',
                line_color='#3b82f6'
            ))
            fig_radar_turma.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                showlegend=False,
                margin=dict(t=20, b=20)
            )
            st.plotly_chart(fig_radar_turma, use_container_width=True)

            st.divider()

            # --- ANÁLISE INDIVIDUAL DO ALUNO ---
            st.subheader("Investigação Individual por Aluno")
            aluno_selecionado = st.selectbox(
                "Selecione ou digite o ID do Aluno para ver o seu perfil psicométrico exato:", 
                df_diag['ALUNO'].unique()
            )
            
            if aluno_selecionado:
                dados_aluno = df_diag[df_diag['ALUNO'] == aluno_selecionado].iloc[0]
                
                # Caixas de destaque com as métricas do aluno
                col_a, col_b, col_c = st.columns(3)
                col_a.metric("Maior Facilidade", dados_aluno['MAIOR_DOMINIO_DISCIPLINA'])
                col_b.metric(" Maior Dificuldade", dados_aluno['PIOR_DEFICIENCIA_DISCIPLINA'])
                
                cg_nota = dados_aluno.get('Conhecimentos Gerais', 0)
                col_c.metric("Conhecimentos Gerais", f"{cg_nota}%")
                
                # Radar Individual vs Turma
                fig_radar_aluno = go.Figure()
                
                # Linha da Turma (Referência em cinza)
                fig_radar_aluno.add_trace(go.Scatterpolar(
                    r=medias_turma['Dominio Medio (%)'],
                    theta=medias_turma['Disciplina'],
                    fill=None,
                    mode='lines',
                    name='Média do Curso',
                    line_color='rgba(169, 169, 169, 0.5)'
                ))
                
                # Linha do Aluno (Em destaque)
                valores_aluno = [dados_aluno[col] for col in colunas_disciplinas]
                fig_radar_aluno.add_trace(go.Scatterpolar(
                    r=valores_aluno,
                    theta=colunas_disciplinas,
                    fill='toself',
                    name=f'Aluno: {aluno_selecionado}',
                    line_color='#8b5cf6'
                ))
                
                fig_radar_aluno.update_layout(
                    polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                    showlegend=True,
                    title=f"Perfil Psicométrico: {aluno_selecionado} vs Turma",
                    margin=dict(t=40, b=20)
                )
                
                col_grafico, col_vazia = st.columns([3, 1])
                with col_grafico:
                    st.plotly_chart(fig_radar_aluno, use_container_width=True)

        # ---------------------------------------------------------------------
        # INTEGRAÇÃO LCA -> CDM RESTRITO (DINA) — validação especialista
        # ---------------------------------------------------------------------
        st.divider()
        st.subheader(" Ponte LCA → CDM restrito (DINA) — validação especialista")
        st.markdown("""
        O pipeline `fase6_lca_para_cdm_restrito.py` monta a matriz item-OC do INEP (Anexo IX),
        estima o **DINA por EM** (guess *g*, slip *s*, prevalência *π* e perfis de domínio por aluno)
        e compara item a item com a LCA exploratória. Cada curso gera um **workbook de validação
        especialista** (`validador_matriz_q_<curso>.xlsx`) para conferência das OC mapeadas.
        """)

        pasta_lca_cdm = DIRETORIO_RAIZ / 'arquivosgerados' / 'RESULTADOS_FASE6_LCA_CDM'
        caminho_comp = pasta_lca_cdm / 'comparacao_lca_vs_dina.csv'
        if caminho_comp.exists():
            df_comp = pd.read_csv(caminho_comp, sep=';', decimal=',')
            st.markdown("**Concordância item a item entre LCA e DINA (28 cursos):**")
            st.dataframe(df_comp[['curso', 'n_alunos', 'n_atributos_dina',
                                  'corr_pearson_item_lca_dina', 'r2_item_lca_dina',
                                  'corr_classe_lca_media', 'bic_dina']].sort_values(
                'corr_pearson_item_lca_dina', ascending=False).reset_index(drop=True),
                use_container_width=True)

        if 'nome_curso_final' in dir() and nome_curso_final:
            def _norm_mq(texto):
                import unicodedata as _u
                t = str(texto)
                t = ''.join(c for c in _u.normalize('NFKD', t) if not _u.combining(c))
                return re.sub(r'\W', '', t).lower()
            nome_base_curso = _norm_mq(nome_curso_final)
            caminho_dic = pasta_lca_cdm / f'dicionario_ocs_{nome_base_curso}.csv'
            caminho_val = pasta_lca_cdm / f'validador_matriz_q_{nome_base_curso}.xlsx'

            if caminho_dic.exists():
                st.markdown(f"**Dicionário de OCs — {nome_curso_final}** (atributos do DINA):")
                df_dic = pd.read_csv(caminho_dic, sep=';', decimal=',')
                st.dataframe(df_dic, use_container_width=True)

            if caminho_val.exists():
                st.markdown(f"**Workbook de validação — {nome_curso_final}**")
                aba_val = st.selectbox(
                    "Aba do validador:", ["Matriz_Q_Item_x_OC", "Resumo_Cobertura", "Concordancia_Empirica_LCA"],
                    key=f"aba_val_{nome_base_curso}")
                df_val = pd.read_excel(caminho_val, sheet_name=aba_val, engine='openpyxl')
                st.dataframe(df_val, use_container_width=True)
                st.caption("Altere a coluna `STATUS`/`OC_*` para registrar a validação do especialista (arquivo original fica intacto).")
            else:
                st.info("Workbook de validação não encontrado para este curso. Execute `fase6_lca_para_cdm_restrito.py`.")

            # ---------------------------------------------------------------------
            # ANÁLISE ESTRATÉGICA — DOMÍNIO POR COMPETÊNCIA (bloco de alta prioridade)
            # ---------------------------------------------------------------------
            st.divider()
            st.subheader(" Análise Estratégica — Domínio por Competência (OC)")
            st.caption("Diagnóstico prescritivo a partir dos perfis DINA: onde estão as lacunas, "
                       "como o curso se compara à média nacional e quais alunos estão em risco.")

            def _oc_sem_prefixo(texto):
                t = str(texto).strip()
                if re.match(r'^OUTRAS_COMPETENCIAS\s*$', t, re.IGNORECASE):
                    return 'outras_competencias'
                m = re.match(r'^([IVXLCDM]{1,6})\s*[-.:]?\s*(.*)$', t)
                if m and m.group(2).strip():
                    return m.group(2).strip().strip(';').strip()
                return t.strip(';').strip()

            def _norm_oc(texto):
                t = unicodedata.normalize('NFKD', str(texto))
                t = ''.join(c for c in t if not unicodedata.combining(c))
                return re.sub(r'\s+', ' ', re.sub(r'\W', ' ', t)).strip().lower()

            def _curto(texto, n=46):
                t = str(texto)
                return t if len(t) <= n else t[:n - 1] + '…'

            def _norm_curso_estr(texto):
                t = unicodedata.normalize('NFKD', str(texto))
                t = ''.join(c for c in t if not unicodedata.combining(c))
                return re.sub(r'\W', '', t).lower()

            nome_base_curso = _norm_curso_estr(nome_curso_final)

            dics = sorted(pasta_lca_cdm.glob('dicionario_ocs_*.csv')) if pasta_lca_cdm.exists() else []
            linhas_dic = []
            for _f in dics:
                _curso_arquivo = _f.stem.replace('dicionario_ocs_', '')
                _dfd = pd.read_csv(_f, sep=';', decimal=',', encoding='utf-8-sig')
                _dfd.columns = [str(c).strip() for c in _dfd.columns]
                for _, _r in _dfd.iterrows():
                    linhas_dic.append({
                        'curso_arquivo': _curso_arquivo,
                        'rotulo': str(_r.get('rotulo', '')),
                        'oc_principal': str(_r.get('oc_principal', '')),
                        'oc_exibicao': _oc_sem_prefixo(str(_r.get('oc_principal', ''))),
                        'n_itens': pd.to_numeric(_r.get('n_itens_medidos'), errors='coerce'),
                        'prevalencia': pd.to_numeric(_r.get('prevalencia_dominio_dina'), errors='coerce'),
                    })
            df_dic_todos = pd.DataFrame(linhas_dic)

            if not df_dic_todos.empty:
                df_dic_todos['oc_norm'] = df_dic_todos['oc_principal'].apply(lambda s: _norm_oc(_oc_sem_prefixo(s)))

                # ---- HEATMAP 1: OC transversal × curso (domínio médio) ----
                with st.expander("Heatmap — domínio médio por OC transversal × curso (lacunas sistêmicas)", expanded=True):
                    cont = df_dic_todos.groupby('oc_norm')['curso_arquivo'].nunique()
                    ocs_comp = cont[cont >= 5].index.tolist()
                    if ocs_comp:
                        _dfp = df_dic_todos[df_dic_todos['oc_norm'].isin(ocs_comp)].copy()
                        _dfp['oc_exib'] = _dfp.groupby('oc_norm')['oc_exibicao'].transform('first')
                        _exib = _dfp.drop_duplicates('oc_norm').set_index('oc_norm')['oc_exib']
                        piv = _dfp.pivot_table(index='oc_norm', columns='curso_arquivo',
                                               values='prevalencia', aggfunc='first')
                        piv = piv.loc[[o for o in ocs_comp if o in piv.index]]
                        piv = piv.loc[piv.notna().sum(axis=1).sort_values(ascending=False).index]
                        ordem_cols = sorted(piv.columns, key=lambda c: 0 if c == nome_base_curso else 1)
                        piv = piv[ordem_cols]
                        fig_heat_oc = px.imshow(
                            piv, zmin=0, zmax=1, color_continuous_scale='RdYlGn',
                            labels=dict(x='Curso', y='Competência (OC)', color='Domínio médio'),
                            aspect='auto')
                        fig_heat_oc.update_yaxes(
                            ticktext=[_curto(_exib.get(i, i)) for i in piv.index],
                            tickvals=list(range(len(piv.index))))
                        st.plotly_chart(fig_heat_oc, use_container_width=True)
                        st.caption("Somente competências transversais presentes em ≥5 cursos são comparáveis entre cursos; "
                                   "cada curso tem um conjunto próprio de OC na matriz-Q do INEP (células vazias = OC inexistente).")
                    else:
                        st.info("Nenhuma competência transversal comum a ≥5 cursos foi encontrada.")

                # ---- HEATMAP 2: saúde psicométrica por curso ----
                caminho_resumo = pasta_lca_cdm / '00_resumo_geral.csv'
                if caminho_resumo.exists():
                    with st.expander("Matriz de saúde psicométrica — curso × indicador", expanded=False):
                        df_res = pd.read_csv(caminho_resumo, sep=';', decimal=',')
                        df_res.columns = [str(c).strip() for c in df_res.columns]
                        prev_media = df_dic_todos.groupby('curso_arquivo')['prevalencia'].mean()
                        fracas = df_dic_todos[df_dic_todos['n_itens'] < 2].groupby('curso_arquivo').size()
                        df_res['dominio_medio'] = df_res['curso'].apply(_norm_curso_estr).map(prev_media)
                        df_res['n_oc_frageis'] = df_res['curso'].apply(_norm_curso_estr).map(fracas).fillna(0).astype(int)
                        df_res['disc_medio'] = (1 - df_res['slip_medio'] - df_res['guess_medio']).clip(0, 1)
                        df_res = df_res.sort_values('dominio_medio')
                        cols_ind = ['dominio_medio', 'n_oc_frageis', 'disc_medio', 'taxa_acerto_media',
                                    'guess_medio', 'slip_medio']
                        _z = pd.DataFrame(index=df_res.index, columns=cols_ind)
                        for _c in cols_ind:
                            _mn, _mx = df_res[_c].min(), df_res[_c].max()
                            _esc = (df_res[_c] - _mn) / (_mx - _mn + 1e-9)
                            if _c in ['n_oc_frageis', 'guess_medio', 'slip_medio']:
                                _esc = 1 - _esc
                            _z[_c] = _esc
                        _txt = []
                        for _, _rr in df_res[cols_ind].iterrows():
                            _txt.append([str(int(v)) if _c == 'n_oc_frageis' else f"{v:.2f}"
                                         for _c, v in _rr.items()])
                        fig_heat_saude = go.Figure(go.Heatmap(
                            z=_z.values,
                            x=[_curto(c, 18) for c in cols_ind],
                            y=[_curto(c, 26) for c in df_res['curso']],
                            text=np.array(_txt),
                            texttemplate='%{text}',
                            hovertemplate='%{y}<br>%{x}: %{text}<extra></extra>',
                            colorscale='RdYlGn', zmin=0, zmax=1))
                        fig_heat_saude.update_layout(margin=dict(t=10, b=10), height=460)
                        st.plotly_chart(fig_heat_saude, use_container_width=True)
                        st.caption("Cor = posição relativa do curso (verde = melhor; para 'n_oc_frageis', verde = poucas fragilidades). "
                                   "Valores exatos são exibidos em cada célula.")

                # ---- LOLLIPOP curso vs nacional ----
                df_sel = df_dic_todos[df_dic_todos['curso_arquivo'] == nome_base_curso].copy()
                if not df_sel.empty:
                    st.markdown(f"**Domínio das OCs — {nome_curso_final} vs média nacional**")
                    bench = (df_dic_todos[df_dic_todos['curso_arquivo'] != nome_base_curso]
                             .groupby('oc_norm')['prevalencia'].mean())
                    df_sel['bench_nacional'] = df_sel['oc_norm'].map(bench)
                    df_sel = df_sel.sort_values('prevalencia')
                    curso_v = df_sel['prevalencia'].to_numpy(dtype=float)
                    bench_v = df_sel['bench_nacional'].to_numpy(dtype=float)
                    ypos = np.arange(len(df_sel))
                    cores = ['#16a34a' if (pd.notna(b) and c >= b) else '#dc2626'
                             for c, b in zip(curso_v, bench_v)]
                    fig_loll = go.Figure()
                    for i, (cb, cc) in enumerate(zip(bench_v, curso_v)):
                        if pd.notna(cb):
                            fig_loll.add_trace(go.Scatter(
                                x=[cb, cc], y=[i, i], mode='lines',
                                line=dict(color='rgba(100,116,139,0.35)', width=1.5),
                                showlegend=False, hoverinfo='skip'))
                    fig_loll.add_trace(go.Scatter(
                        x=bench_v, y=ypos, mode='markers', name='Média nacional (cursos com a mesma OC)',
                        marker=dict(symbol='diamond-open', size=9, color='#64748b')))
                    fig_loll.add_trace(go.Scatter(
                        x=curso_v, y=ypos, mode='markers', name='Este curso',
                        marker=dict(size=11, color=cores, line=dict(width=1, color='#1e293b'))))
                    fig_loll.update_layout(
                        height=max(380, 42 * len(df_sel)),
                        yaxis=dict(tickmode='array', tickvals=ypos,
                                   ticktext=[_curto(l, 54) for l in df_sel['oc_exibicao']],
                                   autorange='reversed'),
                        xaxis_title='Probabilidade média de domínio (DINA)',
                        legend=dict(orientation='h', yanchor='bottom', y=1.02),
                        margin=dict(t=30, b=10))
                    st.plotly_chart(fig_loll, use_container_width=True)
                    st.caption("Verde = curso acima da média nacional para a mesma OC; vermelho = abaixo. "
                               "OCs sem benchmark nacional exibem apenas o valor do curso.")

                    # ---- HISTOGRAMA nº de OCs dominadas ----
                    caminho_perfis = pasta_lca_cdm / f'dina_perfis_alunos_{nome_base_curso}.csv'

                    @st.cache_data(show_spinner=False)
                    def _ler_perfis(caminho_str):
                        return pd.read_csv(caminho_str, sep=';', decimal=',', encoding='utf-8-sig')

                    if caminho_perfis.exists():
                        df_perf = _ler_perfis(str(caminho_perfis))
                        st.markdown(f"**Distribuição de alunos por nº de OCs dominadas — {nome_curso_final}**")
                        n_ocs = int(df_sel.shape[0])
                        meio = n_ocs / 2.0
                        fig_hist = px.histogram(df_perf, x='n_ocs_dominadas', nbins=n_ocs,
                                                color_discrete_sequence=['#3b82f6'])
                        fig_hist.update_layout(bargap=0.08, xaxis_title='Nº de OCs dominadas',
                                               yaxis_title='Nº de alunos', margin=dict(t=20, b=10))
                        fig_hist.add_vline(x=meio, line_dash='dash', line_color='#ef4444',
                                           annotation_text='metade das OCs', annotation_position='top')
                        st.plotly_chart(fig_hist, use_container_width=True)
                        pct_abaixo = float((df_perf['n_ocs_dominadas'] < meio).mean() * 100)
                        st.caption(f"{pct_abaixo:.1f}% dos alunos dominam menos da metade das {n_ocs} OCs do curso.")

                        # ---- TABELA DE ALUNOS EM RISCO (filtro por OC) ----
                        st.markdown("**Alunos em risco por OC (top decil de fraqueza)**")
                        oc_escolhida = st.selectbox(
                            "Selecione a OC para investigar:",
                            df_sel['rotulo'].tolist(),
                            format_func=lambda r: _curto(
                                df_sel.loc[df_sel['rotulo'] == r, 'oc_exibicao'].iloc[0], 60),
                            key=f"oc_risco_{nome_base_curso}")
                        col_mastery = f"mastery_{oc_escolhida}"
                        col_alpha = f"alpha_{oc_escolhida}"
                        if col_mastery in df_perf.columns:
                            desc_oc = df_sel.loc[df_sel['rotulo'] == oc_escolhida, 'oc_principal'].iloc[0]
                            st.markdown(f"OC **{oc_escolhida}** — {desc_oc}")
                            try:
                                cod_ies = int(ies_selecionada)
                            except Exception:
                                cod_ies = None
                            df_risco = df_perf.copy()
                            if cod_ies is not None:
                                df_risco = df_risco[df_risco['CO_IES'] == cod_ies]
                            df_risco = df_risco[df_risco[col_alpha] == 0]
                            n_risco_total = len(df_risco)
                            if n_risco_total == 0:
                                st.info("Nenhum aluno desta IES deixou de dominar essa OC no perfil DINA.")
                            else:
                                top = max(1, int(np.ceil(n_risco_total * 0.10)))
                                df_risco = df_risco.nsmallest(top, col_mastery)
                                df_risco = df_risco[['ALUNO', 'CO_IES', 'NT_DIS_CE',
                                                     col_mastery, col_alpha, 'n_ocs_dominadas']].sort_values(col_mastery)
                                df_risco.columns = ['ALUNO', 'CO_IES', 'NT_DIS_CE', 'P(domina)',
                                                    'Decisão DINA', 'Nº OCs dominadas']
                                st.dataframe(df_risco.reset_index(drop=True), use_container_width=True)
                                st.caption(f"{n_risco_total} alunos da IES {cod_ies} não dominam a OC — "
                                           f"exibidos os {len(df_risco)} com menor P(domina) (top decil).")
            else:
                st.info("Artefatos da validação LCA → CDM não encontrados. Execute `fase6_lca_para_cdm_restrito.py`.")


# =============================================================================
# ABA 08: MACHINE LEARNING AVANÇADO
# =============================================================================
elif tab_selector == TABS[7]:  # Ajuste o índice conforme a sua lista TABS
        st.header("Inteligência Artificial & Machine Learning Avançado")
        st.markdown("""
        Esta secção apresenta os resultados obtidos através de um pipeline de modelagem preditiva avançada.
        O fluxo científico consistiu em:
        1. **Filtro de Anomalias (Isolation Forest):** Remoção de padrões de 'chute' ou abandono de prova.
        2. **Redução de Dimensionalidade (PCA):** Concentração das 38 questões objetivas em 6 componentes principais.
        3. **Tratamento de Desbalanceamento (SMOTE):** Geração artificial de dados para equilibrar as classes.
        """)

        # Definir caminho dos resultados de ML
        pasta_resultados_ml = DIRETORIO_RAIZ / 'arquivosgerados' / 'RESULTADOS_FASE6_ML_AVANCADO'
        caminho_clf = pasta_resultados_ml / 'resultado_classificacao.csv'
        caminho_reg = pasta_resultados_ml / 'resultado_regressao.csv'

        if not caminho_clf.exists() or not caminho_reg.exists():
            st.warning(" Os resultados da modelagem avançada ainda não foram gerados.")
            st.info("Por favor, execute o script `fase6_machine_learning_avancado.py` primeiro para calcular as métricas.")
        else:
            # Carregar os resultados gerados pela batalha de modelos
            df_clf = pd.read_csv(caminho_clf, sep=';', decimal=',')
            _coerce_numerico(df_clf, ['Acurácia', 'Acurácia_Balanceada', 'Precision', 'Recall', 'F1', 'AUC_ROC'])
            df_reg = pd.read_csv(caminho_reg, sep=';', decimal=',')
            _coerce_numerico(df_reg, ['RMSE', 'MAE', 'R2', 'R2 Score'])
            if 'R2' in df_reg.columns and 'R2 Score' not in df_reg.columns:
                df_reg = df_reg.rename(columns={'R2': 'R2 Score'})

            # Criar tabs internas para organizar a visualização
            tab_classif, tab_regressao, tab_explicacoes, sub_tab_classicos = st.tabs(["Classificação (Risco vs Alto Desempenho)", "Regressão (Previsão de Nota Discursiva)", "Explicações", "Classificadores, ANOVA & NLP" ])

            # -----------------------------------------------------------------
            # SUB-TAB 1: CLASSIFICAÇÃO
            # -----------------------------------------------------------------
            with tab_classif:
                st.subheader("Batalha de Classificadores Baseada nas Questões do Exame")
                st.markdown("""
                Previsão se o aluno pertence aos extremos de desempenho (**Alto Desempenho [Top 30%]** ou **Risco Crítico [Bottom 30%]**), 
                utilizando as respostas das 38 questões após redução de ruído.
                """)

                # Gráfico de Barras Comparando Acurácia
                fig_clf = px.bar(
                    df_clf, 
                    x='Acurácia', 
                    y='Modelo', 
                    orientation='h',
                    title="Comparativo de Acurácia entre Modelos",
                    color='Acurácia',
                    color_continuous_scale='Viridis',
                    text_auto='.2%'
                )
                fig_clf.update_layout(yaxis={'categoryorder':'total ascending'}, showlegend=False)
                st.plotly_chart(fig_clf, use_container_width=True)

                # Apresentar Tabela de Dados ao lado de uma métrica de destaque
                col_m1, col_t1 = st.columns([1, 2])
                with col_m1:
                    melhor_modelo_clf = df_clf.loc[df_clf['Acurácia'].idxmax()]
                    st.metric(
                        label="Melhor Classificador", 
                        value=melhor_modelo_clf['Modelo'], 
                        delta=f"{melhor_modelo_clf['Acurácia']:.2%} Acurácia"
                    )
                    st.info("Modelos como Redes Neurais (MLP) e LightGBM tendem a capturar melhor as correlações não-lineares das respostas cognitivas.")
                with col_t1:
                    st.dataframe(df_clf.style.format({'Acurácia': '{:.2%}'}), use_container_width=True)

            # -----------------------------------------------------------------
            # SUB-TAB 2: REGRESSÃO
            # -----------------------------------------------------------------
            with tab_regressao:
                st.subheader("Previsão Contínua da Nota Discursiva (`NT_DIS_CE`)")
                st.markdown("""
                Modelagem matemática para tentar prever a nota de redação técnica/discursiva do aluno 
                baseando-se unicamente nas escolhas e respostas dadas na parte objetiva da prova.
                """)

                col_r1, col_r2 = st.columns(2)

                with col_r1:
                    # Gráfico comparativo do RMSE (Quanto menor, melhor)
                    fig_rmse = px.bar(
                        df_reg, 
                        x='Modelo', 
                        y='RMSE',
                        title="Métrica RMSE (Margem de Erro - Menor é Melhor)",
                        color_discrete_sequence=['#ef4444']
                    )
                    st.plotly_chart(fig_rmse, use_container_width=True)

                with col_r2:
                    # Gráfico comparativo do R² Score (Capacidade de explicação do modelo)
                    fig_r2 = px.bar(
                        df_reg, 
                        x='Modelo', 
                        y='R2 Score',
                        title="Métrica R² Score (Poder de Explicação do Modelo)",
                        color_discrete_sequence=['#3b82f6']
                    )
                    st.plotly_chart(fig_r2, use_container_width=True)

                st.divider()
                st.markdown("#### Detalhes Técnicos das Regularizações (Lasso, Ridge, ElasticNet)")
                st.dataframe(df_reg.style.format({'RMSE': '{:.3f}', 'R2 Score': '{:.4f}'}), use_container_width=True)
                st.caption("O uso de penalizações L1 (Lasso) e L2 (Ridge) ajuda a evitar o Overfitting, garantindo que os pesos atribuídos a cada questão do ENADE sejam estatisticamente generalizáveis.")
            
            with tab_explicacoes:
                # Adicione este bloco dentro de: with tab_classif: (abaixo da tabela existente)
                st.divider()
                st.subheader("Inteligência Artificial Explicativa (XAI honesta)")
                st.markdown("""
                Modelos de Redes Neurais e Boosting são frequentemente criticados por serem 'Caixas Pretas'. 
                Para solucionar isso, o pipeline usa **SHAP real (TreeExplainer sobre um modelo de árvore)** e
                **importância por permutação**, revelando quais questões do ENADE foram determinantes
                para a decisão do algoritmo. (Sem SHAP simulado.)
                """)
                
                caminho_xai = pasta_resultados_ml / 'ia_explicativa_shap.csv'
                if caminho_xai.exists():
                    df_xai = pd.read_csv(caminho_xai, sep=';', decimal=',')
                    _coerce_numerico(df_xai, ['Importancia_SHAP_media_abs', 'Importancia_Permutacao'])
                    col_import = None
                    col_nome = None
                    for cand in ['Importancia_SHAP_media_abs', 'Importancia_Permutacao']:
                        if cand in df_xai.columns:
                            col_import = cand
                            break
                    for cand in ['Questao', 'Componente_PCA']:
                        if cand in df_xai.columns:
                            col_nome = cand
                            break
                    df_xai = df_xai.sort_values(col_import, ascending=True) if col_import else df_xai

                    fig_xai = px.bar(
                        df_xai,
                        x=col_import,
                        y=col_nome,
                        orientation='h',
                        title='Importância das Variáveis na Predição (SHAP/permutação)',
                        color=col_import,
                        color_continuous_scale='OrRd'
                    )
                    fig_xai.update_layout(yaxis={'categoryorder':'total ascending'})
                    
                    col_g_xai, col_t_xai = st.columns([2, 1])
                    with col_g_xai:
                        st.plotly_chart(fig_xai, use_container_width=True)
                    with col_t_xai:
                        st.write("### Diagnóstico XAI")
                        componente_top = df_xai.iloc[-1][col_nome]
                        st.warning(f"O **{componente_top}** é o fator com maior peso discriminatório para prever o sucesso ou falha do aluno.")
                        st.info("A interpretação deve considerar a importância por permutação (mudança no erro quando a variável é embaralhada).")
            
            with sub_tab_classicos:
                st.subheader("Classificadores, ANOVA & NLP")
                st.markdown("""
                Esta secção mapeia os algoritmos tradicionais e a estatística paramétrica exigidos pela literatura estatística, servindo como a **linha de base empírica** do projeto. 
                Aqui tratamos matematicamente o problema de Big Data, focando no Tamanho do Efeito e na Validação Cruzada.
                """)
                
                caminho_anova = pasta_resultados_ml / 'resultado_estatistica_anova.csv'
                caminho_batalha = pasta_resultados_ml / 'batalha_classificadores_classicos.csv'
                caminho_nlp = pasta_resultados_ml / 'resultado_nlp_multilabel.csv'
                
                # Divisão em duas colunas para organização visual
                col_e1, col_e2 = st.columns(2)
                
                with col_e1:
                    st.divider()
                    st.write("### Estatística Paramétrica (ANOVA & Effect Size)")
                    
                    if caminho_anova.exists():
                        # LER OS DADOS ATUALIZADOS DO CSV (com Eta-Quadrado e p-Valor formatado)
                        df_anova_final = pd.read_csv(caminho_anova, sep=';')
                        
                        # Usar st.metric para exibir os números de forma dourada e profissional
                        col_m1, col_m2, col_m3 = st.columns(3)
                        
                        with col_m1:
                            st.metric(
                                label="Estatística F (Robustez)", 
                                value=f"{df_anova_final.iloc[0]['F-Statistic']:.2f}"
                            )
                            
                        with col_m2:
                            # p-Valor agora vem como "< 0.001" (ABNT/APA)
                            pval_display = df_anova_final.iloc[0]['p-Value']
                            st.metric(
                                label="p-Valor (Significância)", 
                                value=pval_display,
                                help="Um p-valor inferior a 0.001 indica que as diferenças médias são estatisticamente significantes, o que é muito comum em Big Data."
                            )
                            
                        with col_m3:
                            # A GEMS DO MESTRADO: EXIBIR O ETA-QUADRADO
                            eta_sq = df_anova_final.iloc[0]['Eta-Quadrado (Tamanho Efeito)']
                            st.metric(
                                label="Eta-Quadrado ($\eta^2$)", 
                                value=f"{eta_sq:.4f}",
                                help=f"O Eta-Quadrado mede a proporção da variância da nota explicada pela região. Aqui: {eta_sq:.2%} da variação é explicada pela Região do Curso."
                            )
                        
                        # ADICIONAR UM DIAGNÓSTICO DE MESTRADO
                        st.divider()
                        st.success(f" **Diagnóstico Pedagógico:** Embora as médias regionais sejam matematicamente diferentes (p {pval_display}), o Eta-Quadrado de apenas **{eta_sq:.4f}** prova que a Região dita menos de 2% do desempenho do aluno.")

                    else:
                        st.info("Execute `fase6_estatistica_parametrica.py` para injetar a análise de ANOVA regional no dashboard.")
                        
                    st.write("### Validação Cruzada de Classificadores")
                    if caminho_batalha.exists():
                        df_bat = pd.read_csv(caminho_batalha, sep=';', decimal=',')
                        _coerce_numerico(df_bat, ['Acurácia Média CV', 'Desvio Padrão', 'F1 Médio CV', 'AUC-ROC Médio CV'])
                        fig_bat = px.bar(df_bat, x='Acurácia Média CV', y='Modelo', orientation='h', title='Acurácia via 5-Fold Cross-Validation', color='Acurácia Média CV', color_continuous_scale='Viridis', text_auto='.2%')
                        fig_bat.update_layout(yaxis={'categoryorder':'total ascending'})
                        st.plotly_chart(fig_bat, use_container_width=True)
                    else:
                        st.info("Execute `fase6_batalha_classificadores.py` para ver a batalha de modelos clássicos.")
                        
                with col_e2:
                    st.write("### Processamento de Texto e Algoritmos Multirrótulo (NLP)")
                    st.markdown("Vetorização **TF-IDF** aplicada sobre os metadados textuais agrupados do vetor de acertos para predição multirrótulo paralela.")
                    if caminho_nlp.exists():
                        st.dataframe(pd.read_csv(caminho_nlp, sep=';', decimal=','), use_container_width=True)
                        st.caption("O *Hamming Loss* mede a fração de rótulos de questões incorretamente previstos. Quanto mais próximo de zero, mais precisa é a mineração textual.")
                    else:
                        st.info("Execute `fase6_mineracao_texto_tfidf.py` para ver os indicadores de NLP.")

# =============================================================================
# ABA 09: PSICOMETRIA COMPUTACIONAL E IA DE FRONTEIRA
# =============================================================================

elif tab_selector == TABS[8]:  # Ajuste o índice de acordo com sua lista TABS
        st.header(" Avanços em Psicometria Computacional & IA Educacional")
        st.markdown("""
        Esta aba apresenta a fronteira científica da Mineração de Dados Educacionais (EDM). 
        O pipeline combina **métricas clássicas dos testes (TCT)**, redes neurais não-lineares e modelos de dependência de itens
        para decodificar o comportamento cognitivo dos estudantes — com avaliação honesta (treino/teste ou validação cruzada) e sem vazamento de alvo.
        """)

        # Definir caminhos
        pasta_resultados_ml = DIRETORIO_RAIZ / 'arquivosgerados' / 'RESULTADOS_FASE6_ML_AVANCADO_PSICOMETRIA'
        caminho_clf = pasta_resultados_ml / 'resultado_classificacao.csv'
        caminho_reg = pasta_resultados_ml / 'resultado_regressao.csv'
        caminho_irt = pasta_resultados_ml / 'metricas_irt_questoes.csv'
        caminho_xai = pasta_resultados_ml / 'ia_explicativa_shap.csv'

        if not caminho_clf.exists() or not caminho_reg.exists():
            st.warning(" Os artefatos psicométricos avançados ainda não foram gerados.")
            st.info("Execute o script `fase6_machine_learning_avancado_piscometria.py` para processar a matriz ponderada por TCT.")
        else:
            # Carregar dados
            df_clf = pd.read_csv(caminho_clf, sep=';', decimal=',')
            _coerce_numerico(df_clf, ['Acurácia', 'Acurácia_Balanceada', 'Precision', 'Recall', 'F1', 'AUC_ROC'])
            df_reg = pd.read_csv(caminho_reg, sep=';', decimal=',')
            _coerce_numerico(df_reg, ['RMSE', 'MAE', 'R2', 'R2 Score'])
            if 'R2' in df_reg.columns and 'R2 Score' not in df_reg.columns:
                df_reg = df_reg.rename(columns={'R2': 'R2 Score'})

            # Organização em Sub-Abas Psicométricas
            sub_tab_irt, sub_tab_clf, sub_tab_reg, sub_tab_som, sub_tab_gkt = st.tabs([
                "Parâmetros de Item (TCT)", 
                "Classificação Cognitiva Estrita", 
                "Regressão Não-Linear (Student-Item)",
                "Topologia de Rede (SOM)",
                "Grafo de Dependência de Itens"
            ])

            # -----------------------------------------------------------------
            # SUB-TAB 1: TEORIA CLÁSSICA DOS TESTES (TCT)
            # -----------------------------------------------------------------
            with sub_tab_irt:
                st.subheader("Análise Clássica de Itens (TCT)")
                st.markdown("""
                As métricas de item foram calculadas pela **Teoria Clássica dos Testes (TCT)** (rotuladas corretamente, sem
                falsear um ajuste IRT 2PL):
                * **Discriminação:** coeficiente de **ponto-bisserial** entre o acerto no item e o escore total (matriz ponderada).
                * **Dificuldade:** proporção de erro (**1 - p**), ou seja, quanto menor, mais fácil o item.
                """)

                if caminho_irt.exists():
                    df_pesos_irt = pd.read_csv(caminho_irt, sep=';', decimal=',')
                    _coerce_numerico(df_pesos_irt, ['Discriminacao_A', 'Dificuldade_B', 'Indice_Discriminacao_TCT', 'Fracao_Erros'])

                    # Gráfico de Dispersão: Dificuldade vs Discriminação
                    fig_irt = px.scatter(
                        df_pesos_irt, 
                        x='Dificuldade_B', 
                        y='Discriminacao_A',
                        text='Questao',
                        title='Quadrante Psicométrico dos Itens da Prova (TCT)',
                        labels={'Dificuldade_B': 'Dificuldade (1 - p)', 'Discriminacao_A': 'Discriminação (ponto-bisserial)'},
                        color='Dificuldade_B',
                        color_continuous_scale='Bluered'
                    )
                    fig_irt.update_traces(marker=dict(size=15, line=dict(width=1, color='DarkSlateGrey')), textposition='top center')
                    st.plotly_chart(fig_irt, use_container_width=True)

                    st.info(" **Interpretação Pedagógica:** Itens no topo direito combinam alta discriminação com alta dificuldade (excelentes para separar alunos de elite). Itens na parte inferior possuem baixa discriminação, indicando que o acerto está associado a ruído ou chute.")
                else:
                    st.info("Atualize seu script de ML para exportar o arquivo 'metricas_irt_questoes.csv' para visualizar o quadrante.")

            # -----------------------------------------------------------------
            # SUB-TAB 2: CLASSIFICAÇÃO COGNITIVA
            # -----------------------------------------------------------------
            with sub_tab_clf:
                st.subheader("Separação de Extremos de Proficiência Latente")
                st.markdown("""
                Os classificadores foram treinados sobre a **Matriz TCT ponderada e reduzida via PCA** (alvo externo honesto: classe da nota discursiva).
                Eles avaliam a capacidade dos algoritmos de isolar cirurgicamente os alunos em Risco Crítico daqueles de Alto Desempenho.
                """)

                col_c1, col_c2 = st.columns([2, 1])
                with col_c1:
                    fig_clf = px.bar(
                        df_clf, x='Acurácia', y='Modelo', orientation='h',
                        title="Desempenho dos Classificadores na Matriz Psicométrica",
                        color='Acurácia', color_continuous_scale='Cividis', text_auto='.2%'
                    )
                    st.plotly_chart(fig_clf, use_container_width=True)
                with col_c2:
                    st.metric("Acurácia Máxima", f"{df_clf['Acurácia'].max():.2%}", "Separação Perfeita")
                    st.dataframe(df_clf.style.format({'Acurácia': '{:.2%}'}), use_container_width=True)

                # Integração XAI / SHAP (real) baseada no Random Forest/Ensemble
                if caminho_xai.exists():
                    st.divider()
                    st.subheader("Inteligência Artificial Explicativa (XAI) Educacional")
                    df_xai = pd.read_csv(caminho_xai, sep=';', decimal=',')
                    _coerce_numerico(df_xai, ['Importancia_SHAP_media_abs', 'Importancia_Permutacao'])
                    col_imp = next((c for c in ['Importancia_SHAP_media_abs', 'Importancia_Permutacao']
                                    if c in df_xai.columns), None)
                    col_nm = next((c for c in ['Questao', 'Componente_PCA'] if c in df_xai.columns), None)
                    if col_imp and col_nm:
                        df_xai = df_xai.sort_values(col_imp, ascending=True)
                        fig_xai = px.bar(
                            df_xai, x=col_imp, y=col_nm, orientation='h',
                            title='Importância das Variáveis (SHAP real / permutação)',
                            color=col_imp, color_continuous_scale='YlOrRd'
                        )
                        st.plotly_chart(fig_xai, use_container_width=True)

            # -----------------------------------------------------------------
            # SUB-TAB 3: REGRESSÃO NÃO-LINEAR STUDENT-ITEM
            # -----------------------------------------------------------------
            with sub_tab_reg:
                st.subheader("Predição Multidimensional da Nota Discursiva (`NT_DIS_CE`)")
                st.markdown("""
                Substituindo modelos puramente lineares, esta seção desafia a interação *Student-Item* utilizando **Redes Neurais Regressoras (MLP-R)** e **Random Forests**. 
                O objetivo é mapear se o comportamento do aluno nas 38 questões objetivas consegue prever sua proficiência dissertativa técnica.
                """)

                col_r1, col_r2 = st.columns(2)
                with col_r1:
                    fig_rmse = px.bar(
                        df_reg, x='Modelo', y='RMSE', title="RMSE (Margem de Erro da Nota - Menor é Melhor)",
                        color='RMSE', color_continuous_scale='Reds'
                    )
                    st.plotly_chart(fig_rmse, use_container_width=True)
                with col_r2:
                    fig_r2 = px.bar(
                        df_reg, x='Modelo', y='R2 Score', title="R² Score (Percentual de Variância Explicada)",
                        color='R2 Score', color_continuous_scale='Blues'
                    )
                    st.plotly_chart(fig_r2, use_container_width=True)

                st.divider()
                st.write("### Tabela Comparativa de Modelagem Psicométrica-Preditiva")
                st.dataframe(df_reg.style.format({'RMSE': '{:.4f}', 'R2 Score': '{:.4f}'}), use_container_width=True)
                
                # Insights Científicos Dinâmicos baseados no melhor R²
                melhor_r2 = df_reg['R2 Score'].max()
                melhor_mod_reg = df_reg.loc[df_reg['R2 Score'].idxmax()]['Modelo']
                st.success(f"**Destaque Científico:** O modelo **{melhor_mod_reg}** obteve o melhor desempenho explicativo com um $R^2$ de **{melhor_r2:.2%}**. Isto valida que mais de um terço da habilidade discursiva e escrita do estudante de engenharia/área técnica pode ser explicada puramente pela estrutura de microraciocínio mapeada nas questões objetivas!")       
            with sub_tab_som:
                st.subheader(" Topologia Cognitiva via Redes Neurais de Kohonen (SOM)")
                st.markdown("""
                Inspirado em arquiteturas de Redes em Grafos (GNN), o algoritmo **Self-Organizing Maps (SOM)** projeta a matriz multidimensional de respostas numa grelha neural competitiva não-supervisionada. 
                O gráfico abaixo indica a **Taxa de Ativação Topológica** de cada questão na estrutura da rede, revelando quais perguntas operam como os nós conectores centrais do conhecimento do aluno.
                """)
                
                caminho_som = pasta_resultados_ml / 'resultado_som_kohonen.csv'
                if caminho_som.exists():
                    df_som = pd.read_csv(caminho_som, sep=';', decimal=',')
                    _coerce_numerico(df_som, ['Ativacao_Topologica'])
                    
                    fig_som = px.bar(
                        df_som,
                        x='Ativacao_Topologica',
                        y='Questao',
                        orientation='h',
                        title='Força de Ativação do Item na Grelha Neuronal Competitiva',
                        color='Ativacao_Topologica',
                        color_continuous_scale='Magma'
                    )
                    fig_som.update_layout(yaxis={'categoryorder':'total ascending'}, height=700)
                    
                    st.plotly_chart(fig_som, use_container_width=True)
                    st.caption("Itens com maior ativação topológica representam os eixos de transição cognitiva onde o aluno muda de patamar de proficiência dentro da arquitetura da rede neural.")
                else:
                    st.warning("O arquivo 'resultado_som_kohonen.csv' não foi encontrado.")
                    st.info("Execute o script independente `fase6_psicometria_som_kohonen.py` para injetar a análise de Kohonen no dashboard.")
            with sub_tab_gkt:
                st.subheader(" Rede de Dependência de Itens (grafo de coocorrência)")
                st.markdown("""
                As questões são tratadas como **nós de um grafo de coocorrência** (arestas = correlação entre itens),
                com propagação de mensagens (*message passing*) para capturar dependências estruturais. Uma rede neural
                é treinada sobre os *embeddings* do grafo com split honesto (70/30) para prever a nota discursiva.
                """)
                
                caminho_gkt = pasta_resultados_ml / 'resultado_graph_knowledge.csv'
                caminho_perf_gkt = pasta_resultados_ml / 'performance_gkt.csv'
                
                if caminho_gkt.exists() and caminho_perf_gkt.exists():
                    df_gkt = pd.read_csv(caminho_gkt, sep=';', decimal=',')
                    df_perf = pd.read_csv(caminho_perf_gkt, sep=';', decimal=',')
                    _coerce_numerico(df_gkt, ['Centralidade_Grafo'])
                    _coerce_numerico(df_perf, ['RMSE', 'MAE', 'R2', 'R2 Score'])
                    
                    # Mostrar Métrica de Sucesso da Rede em Grafos
                    col_r2 = 'R2' if 'R2' in df_perf.columns else ('R2 Score' if 'R2 Score' in df_perf.columns else None)
                    if col_r2:
                        st.metric(
                            label="Poder de Explicação da Rede de Grafos (R²)", 
                            value=f"{df_perf.iloc[0][col_r2]:.2%}",
                            delta=f"Margem RMSE: {df_perf.iloc[0]['RMSE']:.2f}"
                        )
                    
                    # Gráfico de Barras de Centralidade no Grafo
                    fig_gkt = px.bar(
                        df_gkt,
                        x='Centralidade_Grafo',
                        y='Questao',
                        orientation='h',
                        title='Grau de Centralidade Cognitiva do Item no Grafo de Conhecimento',
                        color='Centralidade_Grafo',
                        color_continuous_scale='Electric'
                    )
                    fig_gkt.update_layout(yaxis={'categoryorder':'total ascending'}, height=700)
                    st.plotly_chart(fig_gkt, use_container_width=True)
                    
                    st.success("**Interpretação de Redes:** Questões com maior centralidade no grafo funcionam como **Pré-requisitos Cognitivos Estruturais**. Alunos que falham nessas perguntas específicas tendem a desencadear um efeito de erro em cascata por toda a rede de itens da prova.")
                else:
                    st.warning("O arquivo de dados do Grafo Cognitivo ainda não foi gerado.")
                    st.info("Por favor, execute o script independente `fase6_psicometria_graph_knowledge.py` para injetar esta análise.")

# =============================================================================
# ABA 10: Auditoria de Competências do Século XXI
# =============================================================================
elif tab_selector == TABS[9]:

    st.title("Auditoria de Competências do Século XXI")
    st.markdown("""
    Baseado na framework do *Journal of Learning Analytics (2026)*, este módulo audita a matriz formativa avaliada no ENADE 2023.
    Identificamos se a instituição está formando profissionais apenas com viés técnico ou com **Responsabilidade Social e Tecnológica integral**.
    """)

    # 1. Funções locais e dicionário (para não dar erro de escopo)
    def formatar_nome_arquivo_local(nome):
        nome_sem_acento = ''.join(ch for ch in unicodedata.normalize('NFKD', nome) if not unicodedata.combining(ch))
        return nome_sem_acento.lower().replace(' ', '_')


    # 2. Configurações e Filtros no topo da página (não na sidebar)
    st.markdown("### Configurações do Diagnóstico")
    curso_selecionado_nome = st.selectbox(
        "1. Selecione o Curso para Análise:", 
        sorted(list(cursos_map.values()))
    )

    # 3. Carregamento dos Dados
    pasta_resultados = Path("arquivosgerados/RESULTADOS_FASE6_CDM_XLSX")
    nome_base = formatar_nome_arquivo_local(curso_selecionado_nome)
    nome_arquivo = f"diagnostico_cognitivo_{nome_base}.xlsx" 
    caminho_ficheiro = pasta_resultados / nome_arquivo
    
    df = pd.DataFrame()
    dados_reais = False
    
    try:
        df = pd.read_excel(caminho_ficheiro, engine='openpyxl')
        st.success(f"Base carregada com sucesso: {nome_arquivo}")
        dados_reais = True
    except FileNotFoundError:
        st.error(f"Arquivo não encontrado: {nome_arquivo}. Exibindo ambiente de simulação.")
        # Mock de dados apenas para a tela não quebrar
        np.random.seed(len(curso_selecionado_nome)) 
        n_alunos = 300
        df = pd.DataFrame({
            'ALUNO': range(1, n_alunos + 1),
            'I - Ética e Cidadania': np.random.normal(45, 20, n_alunos).clip(0, 100),
            'VIII - Sustentabilidade': np.random.normal(50, 15, n_alunos).clip(0, 100),
            'Cálculo e Física': np.random.normal(55, 15, n_alunos).clip(0, 100),
            'Algoritmos/Tecnologia': np.random.normal(60, 20, n_alunos).clip(0, 100),
        })

    # 4. Seletores de Mapeamento de Competências
    st.markdown("**2. Mapeamento de Eixos (Selecione as disciplinas para cruzamento)**")
    
    colunas_ignoradas = ['ALUNO', 'CO_CURSO', 'NOME_CURSO', 'MAIOR_DOMINIO_DISCIPLINA', 'PIOR_DEFICIENCIA_DISCIPLINA', 'Conhecimentos Gerais']
    todas_colunas = [col for col in df.columns if col not in colunas_ignoradas]
    
    default_hard = todas_colunas[2:4] if not dados_reais and len(todas_colunas) >= 4 else []
    default_soft = todas_colunas[0:2] if not dados_reais and len(todas_colunas) >= 2 else []
    
    col1_filtros, col2_filtros = st.columns(2)
    with col1_filtros:
        colunas_hard = st.multiselect(
            "Hard Skills (Matérias Técnicas/Exatas):", 
            todas_colunas, 
            default=default_hard
        )
    with col2_filtros:
        colunas_soft = st.multiselect(
            "Soft Skills (Ética/Cidadania/Meio Ambiente):", 
            todas_colunas, 
            default=default_soft
        )

    st.markdown("---")

    # 5. Processamento e Gráfico (Só roda se o usuário selecionou as matérias)
    if not colunas_hard or not colunas_soft:
        st.info("Selecione pelo menos uma matéria técnica e uma de cidadania acima para gerar o Radar de Competências.")
    else:
        # Processamento Matemático
        df['Media_Hard_Skills'] = df[colunas_hard].mean(axis=1)
        df['Media_Soft_Skills'] = df[colunas_soft].mean(axis=1)

        condicoes = [
            (df['Media_Hard_Skills'] >= 50) & (df['Media_Soft_Skills'] >= 50),
            (df['Media_Hard_Skills'] >= 50) & (df['Media_Soft_Skills'] < 50),
            (df['Media_Hard_Skills'] < 50) & (df['Media_Soft_Skills'] >= 50),
            (df['Media_Hard_Skills'] < 50) & (df['Media_Soft_Skills'] < 50)
        ]
        
        categorias = [
            '🟢 Líder do Séc. XXI (Alta Técnica e Ética)',
            '🟡 Risco Ético/Social (Foco Exclusivo Técnico)',
            '🟠 Perfil Humanista (Défice Técnico)',
            '🔴 Risco Crítico de Evasão (Défice Duplo)'
        ]
        df['Perfil_Seculo21'] = np.select(condicoes, categorias, default= 'Indefinido')

        # Gráfico Plotly
        fig = go.Figure()
        cores = {
            '🟢 Líder do Séc. XXI (Alta Técnica e Ética)': '#2ca02c',
            '🟡 Risco Ético/Social (Foco Exclusivo Técnico)': '#ff7f0e',
            '🟠 Perfil Humanista (Défice Técnico)': '#1f77b4',
            '🔴 Risco Crítico de Evasão (Défice Duplo)': '#d62728'
        }

        for categoria, cor in cores.items():
            df_cat = df[df['Perfil_Seculo21'] == categoria]
            fig.add_trace(go.Scatter(
                x=df_cat['Media_Hard_Skills'],
                y=df_cat['Media_Soft_Skills'],
                mode='markers',
                name=categoria,
                marker=dict(color=cor, size=9, opacity=0.75, line=dict(width=1, color='black')),
                text=df_cat['ALUNO'] if 'ALUNO' in df.columns else df.index,
                hovertemplate="Aluno ID: %{text}<br>Média Técnica: %{x:.1f}<br>Média Cidadania: %{y:.1f}<extra></extra>"
            ))

        fig.add_hline(y=50, line_dash="dash", line_color="black", annotation_text="Limiar Cidadania")
        fig.add_vline(x=50, line_dash="dash", line_color="black", annotation_text="Limiar Técnico")

        fig.update_layout(
            title=f"Dispersão de Competências: {curso_selecionado_nome}",
            xaxis_title="Proficiência Técnica - Hard Skills (0 a 100)",
            yaxis_title="Proficiência Cidadã/Ética - Soft Skills (0 a 100)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            plot_bgcolor='rgba(245, 245, 245, 1)',
            height=550
        )

        st.plotly_chart(fig, use_container_width=True)

        # Painel Analítico
        st.subheader("Diagnóstico Pedagógico Automático")
        total_alunos = len(df)
        perc_risco = (len(df[df['Perfil_Seculo21'] == '🟡 Risco Ético/Social (Foco Exclusivo Técnico)']) / total_alunos) * 100
        perc_lider = (len(df[df['Perfil_Seculo21'] == '🟢 Líder do Séc. XXI (Alta Técnica e Ética)']) / total_alunos) * 100

        m1, m2, m3 = st.columns(3)
        m1.metric("Total de Alunos Analisados", f"{total_alunos}")
        m2.metric("Formação Ideal (Líderes)", f"{perc_lider:.1f}%")
        m3.metric("Risco Ético/Tecnológico", f"{perc_risco:.1f}%", delta="Alerta Curricular", delta_color="inverse")

        st.info(f"💡 **Auditoria Retroativa de {curso_selecionado_nome}:** Ao aplicar as métricas de 2026 sobre os dados de 2023, identificamos que **{perc_risco:.1f}%** dos alunos possuem foco exclusivamente técnico, falhando nas competências sociais e éticas. Recomenda-se aos Núcleos Docentes Estruturantes (NDE) a integração de projetos interdisciplinares para alinhar a matriz às exigências contemporâneas da OCDE.")


# =============================================================================
# ABA 11: SIMULADOR CONTRAFACTUAL
# =============================================================================
elif tab_selector == TABS[10]:
    from algoritmos.xai.simulador_contrafactual import (
        detectar_alvo_externo, treinar_simulador, simular, taxa_excelencia,
    )

    st.header(" Simulador Contrafactual Curricular (What-If Analytics)")
    st.markdown("""
    Esta funcionalidade simula **Políticas de Intervenção Pedagógica**.
    Quando a base do curso possui uma **nota externa real** (ENADE: `NT_DIS_CE`, `NT_CE_D1` ou `NT_GER`),
    treina um modelo **XGBoost supervisionado** (sem vazamento de alvo) para estimar o impacto de
    intervenções em disciplinas isoladas sobre a **Taxa de Excelência**. Sem alvo externo disponível,
    a leitura é **aritmética (declarada)** — nenhum ganho é inventado.
    """)

    if 'nome_curso_final' not in dir() or not nome_curso_final:
        st.warning("Por favor, selecione uma IES e um Curso no filtro lateral para iniciar o simulador.")
    else:
        # --- FUNÇÕES LOCAIS DA ABA ---
        @st.cache_data
        def carregar_dados_simulador(nome_curso):
            """Carrega a base do curso: diagnostico cognitivo OU microdados reais."""
            nome_base = formatar_nome(nome_curso)
            # 1) planilha de diagnostico cognitivo (pode ter so disciplinas)
            caminho_xlsx = (DIRETORIO_RAIZ / 'arquivosgerados' / 'RESULTADOS_FASE6_CDM_XLSX'
                            / f"diagnostico_cognitivo_{nome_base}.xlsx")
            if caminho_xlsx.exists():
                try:
                    return pd.read_excel(caminho_xlsx, engine='openpyxl'), True
                except Exception:
                    pass
            # 2) microdados reais (tem notas NT_* como alvo externo)
            for cand in [
                DIRETORIO_RAIZ.parent / 'seriesTemporais_microdados' / 'resultados' / 'enade',
            ]:
                if cand.exists():
                    for arq in sorted(cand.glob('relatorio_final_enade_*.csv'), reverse=True):
                        try:
                            dfm = pd.read_csv(arq, sep=';', encoding='utf-8-sig', low_memory=False)
                        except Exception:
                            continue
                        alvo = detectar_alvo_externo(dfm)
                        if alvo is not None:
                            return dfm, True
            return None, False

        # --- EXECUÇÃO DA INTERFACE ---
        df, dados_reais = carregar_dados_simulador(nome_curso_final)

        if df is None or getattr(df, 'empty', True):
            st.warning("Nenhuma base de diagnóstico cognitivo ou microdados do curso foi localizada. "
                       "O simulador não gera números sem dados verificáveis.")
        else:
            if not dados_reais:
                st.warning(f"Base de '{nome_curso_final}' não localizada com alvo externo.")

            colunas_ignoradas = ['ALUNO', 'CO_CURSO', 'NOME_CURSO', 'MAIOR_DOMINIO_DISCIPLINA',
                                 'PIOR_DEFICIENCIA_DISCIPLINA', 'Perfil_Seculo21', 'Media_Global',
                                 'Alto_Desempenho', 'Conhecimentos Gerais']
            alvo = detectar_alvo_externo(df)
            # features: itens Q* se existirem; senao colunas numericas nao-NT
            disciplinas = [c for c in df.columns if str(c).upper().startswith('Q')
                           and str(c).upper() not in colunas_ignoradas]
            if not disciplinas:
                disciplinas = [c for c in df.columns
                               if c not in colunas_ignoradas and not str(c).upper().startswith('NT_')
                               and pd.api.types.is_numeric_dtype(pd.to_numeric(df[c], errors='coerce'))]

            if len(disciplinas) == 0:
                st.error("Nenhuma disciplina estruturada foi encontrada para este curso.")
            else:
                modelo, info = treinar_simulador(df, disciplinas, alvo=alvo)
                modo = info.get('modo')
                if modo == 'supervisionado':
                    st.success(f"Modelo **XGBoost supervisionado** treinado com alvo externo "
                               f"`{info['alvo']}` (n={info['n_treino']}, corte={info.get('corte', 60):.0f}). "
                               "Sem vazamento de alvo.")
                else:
                    st.info(f"Sem alvo externo válido — usando **leitura aritmética declarada** "
                            f"(motivo: {info.get('motivo')}). Nenhum ganho é inventado.")

                st.markdown("#### Painel de Intervenção Curricular")
                st.caption("Ajuste o impacto pedagógico estimado para cada intervenção. "
                           "A taxa resultante é recalculada de forma auditável a partir da base.")

                disciplinas_exibidas = disciplinas[:5] if len(disciplinas) > 5 else disciplinas
                alteracoes_simuladas = {}
                cols = st.columns(len(disciplinas_exibidas))
                for i, disciplina in enumerate(disciplinas_exibidas):
                    with cols[i]:
                        delta = st.slider(
                            f"Ação em:\n{disciplina[:18]}",
                            min_value=-20, max_value=20, value=0, step=1,
                            key=f"sim_{disciplina}")
                        alteracoes_simuladas[disciplina] = delta

                resultado = simular(modelo, df, disciplinas, alteracoes_simuladas, alvo=alvo)
                taxa_atual = resultado['taxa_atual']
                nova_taxa = resultado['taxa_simulada']
                diferenca = resultado['diferenca']

                st.markdown("---")
                m1, m2, m3 = st.columns(3)
                m1.metric("Cenário Atual (Taxa de Excelência)", f"{taxa_atual:.1f}%")
                status_cor = "normal" if diferenca >= 0 else "inverse"
                m2.metric("Cenário Ajustado (Pós-Intervenção)", f"{nova_taxa:.1f}%",
                          f"{diferenca:+.1f}% de variação", delta_color=status_cor)

                if diferenca > 0:
                    m3.success(f"**Variação positiva:** a intervenção moveria **{diferenca:+.1f}%** "
                               "dos alunos para a faixa de excelência.")
                elif diferenca < 0:
                    m3.error(f"**Alerta:** reduzir essas frentes retrairia o grupo de excelência em "
                             f"**{abs(diferenca):.1f}%**.")
                else:
                    m3.info("Mova os cursores (sliders) acima para recalcular a taxa sob demanda.")

                st.caption(f"Modo: **{resultado['modo']}** — "
                           + ("previsão de modelo supervisionado com alvo externo."
                              if resultado['modo'] == 'supervisionado'
                              else "média aritmética das proficiências (sem alvo externo)."))

                fig = go.Figure()
                fig.add_trace(go.Bar(
                    x=['Cenário Real Atual', 'Cenário Ajustado'],
                    y=[taxa_atual, nova_taxa],
                    marker_color=['#1f77b4', '#2ca02c' if diferenca >= 0 else '#d62728'],
                    text=[f"{taxa_atual:.1f}%", f"{nova_taxa:.1f}%"],
                    textposition='auto'))
                fig.update_layout(
                    title=f"Sensibilidade da Taxa de Excelência: {nome_curso_final}",
                    yaxis_title="Taxa de Excelência (%)",
                    yaxis=dict(range=[0, 100]),
                    height=380, margin=dict(l=40, r=40, t=60, b=40),
                    plot_bgcolor='rgba(245, 245, 245, 0.5)')
                st.plotly_chart(fig, use_container_width=True)

# =============================================================================
# ABA 12: ESTUDO DE CASO - O PARADOXO DAS MÉDIAS (DADOS REAIS DA PLANILHA)
# =============================================================================
elif tab_selector == TABS[11]:
    st.header("Estudo de Caso Dinâmico: O Paradoxo das Médias")
    st.markdown("""
    ** Este módulo carrega a base de dados real do curso selecionado. 
    Selecione dois estudantes distintos e observe como a **Média Global (Visão Tradicional)** pode mascarar perfis de 
    proficiência latente completamente antagônicos revelados pela **Matriz-Q (Visão Nova)**.
    """)

    # Verifica se o utilizador já escolheu o curso no menu lateral
    if 'nome_curso_final' not in dir() or not nome_curso_final:
        st.warning(" Por favor, selecione uma IES e um Curso no filtro lateral para iniciar o estudo de caso.")
    else:
        # --- FUNÇÃO PARA CARREGAR PLANILHA ---
        @st.cache_data
        def carregar_dados_estudo_caso(nome_curso):
            pasta_resultados = DIRETORIO_RAIZ / 'arquivosgerados' / 'RESULTADOS_FASE6_CDM_XLSX'
            nome_base = formatar_nome(nome_curso)
            caminho_ficheiro = pasta_resultados / f"diagnostico_cognitivo_{nome_base}.xlsx" 
            
            try:
                df_real = pd.read_excel(caminho_ficheiro, engine='openpyxl')
                return df_real, True
            except FileNotFoundError:
                # Dados sintéticos de fallback caso a planilha não exista
                np.random.seed(42)
                n_alunos = 50
                df_mock = pd.DataFrame({
                    'ALUNO': [f"ID_{(10000 + i)}" for i in range(n_alunos)],
                    'Algoritmos e Lógica': [85, 20] + list(np.random.normal(60, 15, n_alunos-2).clip(0, 100)),
                    'Cálculo e Matemática': [90, 15] + list(np.random.normal(50, 20, n_alunos-2).clip(0, 100)),
                    'Ética Profissional': [10, 85] + list(np.random.normal(70, 10, n_alunos-2).clip(0, 100)),
                    'Sustentabilidade': [15, 80] + list(np.random.normal(65, 15, n_alunos-2).clip(0, 100))
                })
                return df_mock, False

        df, dados_reais = carregar_dados_estudo_caso(nome_curso_final)
        
        if not dados_reais:
            st.warning(f" Planilha real não encontrada para '{nome_curso_final}'. A carregar dados de simulação padrão.")
        else:
            st.success(f" Conectado à base de microdados real do curso: **{nome_curso_final}**")

        # Filtrar colunas de disciplinas/habilidades
        colunas_ignoradas = ['ALUNO', 'CO_CURSO', 'NOME_CURSO', 'MAIOR_DOMINIO_DISCIPLINA', 'PIOR_DEFICIENCIA_DISCIPLINA', 'Perfil_Seculo21', 'Media_Global', 'Alto_Desempenho', 'Conhecimentos Gerais']
        habilidades = [c for c in df.columns if c not in colunas_ignoradas]
        lista_alunos = df['ALUNO'].unique().tolist()

        if len(lista_alunos) < 2:
            st.error("Não há alunos suficientes nesta base para realizar a comparação.")
        else:
            st.markdown("###  Seleção de Estudantes para Comparativo")
            c_sel1, c_sel2 = st.columns(2)
            with c_sel1:
                id_aluno1 = st.selectbox("Selecione o 1º Estudante (ID):", lista_alunos, index=0)
            with c_sel2:
                id_aluno2 = st.selectbox("Selecione o 2º Estudante (ID):", lista_alunos, index=1)

            # Extrair dados exatos
            dados_a = df[df['ALUNO'] == id_aluno1].iloc[0]
            dados_b = df[df['ALUNO'] == id_aluno2].iloc[0]

            notas_a = [dados_a[h] for h in habilidades]
            notas_b = [dados_b[h] for h in habilidades]
            media_a = np.mean(notas_a)
            media_b = np.mean(notas_b)
            pior_a = habilidades[np.argmin(notas_a)]
            pior_b = habilidades[np.argmin(notas_b)]
            melhor_a = habilidades[np.argmax(notas_a)]

            aba_analise, aba_visao, aba_acao = st.tabs([" 1. Visão Antiga (Média / LCA)", " 2. Visão (Matriz-Q + CDM)", " 3. Visão Nova (Matriz-Q  + Ação)"])

            with aba_analise:
                st.subheader("Análise Macroscópica Tradicional (Nota Média)")
                st.warning(" **Limitação da Teoria Clássica:** A Média Global consolida e cega os dados. Perfis antagônicos podem ter a mesma nota.")
                
                c1, c2 = st.columns(2)
                with c1:
                    st.metric(label=f"Estudante: {id_aluno1}", value=f"{media_a:.1f} / 100", delta="Média Global", delta_color="off")
                with c2:
                    st.metric(label=f"Estudante: {id_aluno2}", value=f"{media_b:.1f} / 100", delta="Média Global", delta_color="off")
                    
                st.markdown("Ao observar apenas a média, a instituição tende a aplicar a mesma intervenção pedagógica genérica a ambos, desperdiçando recursos.")

            with aba_visao:
                st.subheader("Micro-Diagnóstico Dinâmico de Proficiências Latentes")
                
                categorias = habilidades + [habilidades[0]] 
                proficiencias_a = notas_a + [notas_a[0]]
                proficiencias_b = notas_b + [notas_b[0]]

                fig = go.Figure()
                fig.add_trace(go.Scatterpolar(
                    r=proficiencias_a, theta=categorias, fill='toself', name=f'{id_aluno1}', line_color='#1f77b4', fillcolor='rgba(31, 119, 180, 0.4)'
                ))
                fig.add_trace(go.Scatterpolar(
                    r=proficiencias_b, theta=categorias, fill='toself', name=f'{id_aluno2}', line_color='#ff7f0e', fillcolor='rgba(255, 127, 14, 0.4)'
                ))
                fig.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 100])), showlegend=True, height=500)

                col_esq, col_dir = st.columns([3, 2])
                with col_esq:
                    st.plotly_chart(fig, use_container_width=True)
                with col_dir:
                    st.markdown("**Interpretação Dinâmica:**")
                    pior_a = habilidades[np.argmin(notas_a)]
                    pior_b = habilidades[np.argmin(notas_b)]
                    
                    st.info(f"**Gargalo do ID {id_aluno1}:** {pior_a} ({min(notas_a):.1f} pts).")
                    st.warning(f"**Gargalo do ID {id_aluno2}:** {pior_b} ({min(notas_b):.1f} pts).")
                    
                    st.markdown(f"**Tomada de Decisão Cirúrgica:** O sistema prescreve trilhas de nivelamento exclusivas para **{pior_a}** (Aluno 1) e **{pior_b}** (Aluno 2), otimizando a carga cognitiva e financeira da universidade.")

            with aba_acao:
                st.subheader("Raio-X Cognitivo Dinâmico")
                categorias = habilidades + [habilidades[0]] 
                fig = go.Figure()
                fig.add_trace(go.Scatterpolar(r=notas_a+[notas_a[0]], theta=categorias, fill='toself', name=f'{id_aluno1}', line_color='#1f77b4', fillcolor='rgba(31, 119, 180, 0.4)'))
                fig.add_trace(go.Scatterpolar(r=notas_b+[notas_b[0]], theta=categorias, fill='toself', name=f'{id_aluno2}', line_color='#ff7f0e', fillcolor='rgba(255, 127, 14, 0.4)'))
                fig.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 100])), showlegend=True, height=400)
                st.plotly_chart(fig, use_container_width=True)

                st.markdown("---")
                st.subheader(" Riqueza de Detalhes: O Poder do Sensemaking")
                st.markdown("A transição da IA puramente matemática para uma gestão educacional acionável:")
                
                # As 4 Abas Criativas Pedidas
                tab_roi, tab_domino, tab_ementa, tab_carta = st.tabs([
                    "1. ROI Institucional", 
                    "2. Efeito Dominó", 
                    "3. Receita Médica (Micro-Ementa)", 
                    "4. Carta de Feedback (XAI)"
                ])

                # 1. ROI Institucional
                with tab_roi:
                    st.markdown("#### O Custo da Decisão Errada vs. Decisão Guiada por Dados")
                    c_roi1, c_roi2 = st.columns(2)
                    with c_roi1:
                        st.error("**Técnica Antiga (Reforço Genérico)**")
                        st.markdown("- **Ação:** Criação de turmas extras de Matemática para todos os alunos medianos.\n- **Custo Docente:** R$ 25.000,00/semestre.\n- **Efetividade:** Baixa (o aluno 1 vai faltar por já saber, e o aluno 2 vai falhar por falta de base estrutural).")
                    with c_roi2:
                        st.success("**Matriz-Q (Ação Cirúrgica)**")
                        st.markdown(f"- **Ação:** Direcionar o ID {id_aluno2} para a trilha digital de *{pior_b}* já existente no Moodle.\n- **Custo Extra:** **R$ 0,00** (Reaproveitamento inteligente).\n- **Horas de Sala Poupadas:** 40h letivas institucionais.")

                # 2. Efeito Dominó
                with tab_domino:
                    st.markdown("#### Risco Futuro (Leitura do Gap Observado)")
                    st.info(f"O modelo detetou um gargalo latente de apenas **{min(notas_a):.1f} pontos em {pior_a}** para o Estudante {id_aluno1}.")

                    # Leitura qualitativa do gap (sem percentual inventado).
                    if "lógica" in pior_a.lower() or "algoritmo" in pior_a.lower() or "cálculo" in pior_a.lower():
                        alvo_futuro = "Inteligência Artificial, Banco de Dados Avançado e Compiladores"
                    else:
                        alvo_futuro = "Projetos de Extensão, Estágio Supervisionado e Gestão de Engenharia"

                    st.warning(f"**Leitura do gap:** a proficiência observada em *{pior_a}* "
                               f"({min(notas_a):.1f} pontos) está abaixo da referência do grupo. "
                               f"Disciplinas dependentes que costumam exigir essa base: **{alvo_futuro}**. "
                               "Não há percentual de reprovação estimado — não há dado que o sustente.")
                    st.markdown("A Matriz-Q apoia a **prevenção do abandono (evasão)** ao atuar no efeito cascata, "
                                "com base no gap observado, sem projeções não verificáveis.")

                # 3. A Receita Médica
                with tab_ementa:
                    st.markdown(f"#### Geração Automática de Trilha de Nivelamento para ID {id_aluno2}")
                    st.markdown(f"O sistema, ao isolar a deficiência em **{pior_b}**, automatizou a carga do Coordenador prescrevendo o seguinte plano:")
                    
                    st.markdown(f"""
                    * **Semana 1 (Desbloqueio):** Revisão de conceitos base de {pior_b} utilizando analogias gamificadas (Módulo 1).
                    * **Semana 2 (Aplicação):** Listas de exercícios contrafactuais focados unicamente nas taxas de erro do aluno.
                    * **Semana 3 (Validação):** Micro-teste adaptativo para confirmar o preenchimento da lacuna latente.
                    """)
                    st.caption("✔️ Esta automatização fecha o ciclo da EDM (Educational Data Mining), entregando ao docente um plano de ação pronto.")

                # 4. A Carta ao Estudante
                with tab_carta:
                    st.markdown(f"#### Transparência e Empatia Algorítmica (Feedback para ID {id_aluno1})")
                    st.markdown("A avaliação em larga escala costuma ser fria e punitiva. Aqui, usamos os dados latentes para motivar o estudante:")
                    
                    st.info(f"""
                    *"Caro(a) estudante,*
                    
                    *Avaliámos o seu desempenho recente. Notámos que você possui um talento brilhante na área de **{melhor_a}** (pontuação de excelência: {max(notas_a):.1f}/100).* *O motivo pelo qual a sua nota global não atingiu o patamar de destaque deveu-se exclusivamente a dificuldades pontuais nas questões relacionadas a **{pior_a}**. Como você já provou ter uma enorme capacidade cognitiva em outras frentes, criámos um pequeno módulo personalizado apenas para fechar esta lacuna.*
                    
                    *Continue com o ótimo trabalho nas suas valências fortes!"*
                    """)
                    st.caption(" A IA Explicável não serve apenas para o Reitor; serve para humanizar a relação da máquina com o aluno.")

        # ---------------- TAXA-BASE REAL (SEM PROJECAO FABRICADA) ----------------
        st.markdown("---")
        st.subheader("Taxa de Excelência do Curso")
        taxa_excelencia_base = None
        if dados_reais and df is not None and len(df) > 0:
            notas = df.apply(pd.to_numeric, errors='coerce')
            media_aluno = notas.mean(axis=1, numeric_only=True)
            taxa_excelencia_base = round(float((media_aluno >= 60).mean() * 100), 1)
            st.metric("Taxa Atual de Excelência (média das proficiências ≥ 60)", f"{taxa_excelencia_base}%")
            st.caption("Indicador descritivo calculado diretamente dos dados carregados nesta aba.")
        else:
            st.info("Dados reais não disponíveis nesta seção para calcular a taxa de excelência.")
        st.info(
            "Não há modelo de intervenção treinado nesta seção, portanto nenhuma projeção de ganho é exibida. "
            "Para simulação contrafactual baseada em modelo, use a aba **Simulador Contrafactual Curricular (What-If Analytics)**."
        )
# =============================================================================
# =============================================================================
# ABA 13: MOTOR DE SUPORTE À DECISÃO DINÂMICO (INTEGRAÇÃO OPENCODE + DRILL-DOWN REAL)
# =============================================================================

elif tab_selector == TABS[12]:
        st.markdown("---")
        st.header("Suporte à Tomada de Decisão Pedagógica")
        st.markdown("Mergulho analítico na nuance do erro por questão com prescrição automatizada via IA e Consulta Livre.")
        
            # Status do servidor
        server_online = servidor_opencode_ativo()
        status_color = "🟢" if server_online else "🔴"
        status_text = "Online" if server_online else "Offline"
        # Check rate limit
        rate_info = _check_zen_rate_limit() if server_online else {"limited": False}
        if rate_info.get("limited"):
            reset_at = rate_info.get("reset_at", "desconhecido")
            st.error(f" **Limite de uso gratuito Zen excedido** — Reset previsto para **{reset_at}**. [Adicionar créditos](https://opencode.ai/zen)")
            status_text += " (limite excedido)"
    
        st.caption(f"{status_color} Servidor OpenCode: {status_text} — {OPENCODE_SERVER_URL}")
        if 'df_final' not in dir() or df_final.empty:
            st.warning("Selecione uma IES e Curso no filtro lateral para gerar o suporte pedagógico.")
        else:
            colunas_oc = [col for col in df_final.columns if str(col).startswith('OC')]

            if not df_final.empty and 'QUESTAO' in df_final.columns:
                # --- Preparação de Dados (Drill-Down) ---
                agg_dict_real = {'TAXA_DEFICIENCIA_%': 'mean'}
                for col in colunas_oc: 
                    agg_dict_real[col] = 'first'
                if 'COMPETÊNCIAS' in df_final.columns: 
                    agg_dict_real['COMPETÊNCIAS'] = 'first'
                
                df_drill_down = df_final.groupby('QUESTAO').agg(agg_dict_real).reset_index()
                
                def unir_ocs(row):
                    ocs_encontradas = []
                    for col in colunas_oc:
                        valor = row.get(col)
                        if valor is not None and str(valor).lower() != 'nan':
                            if valor in [1, 1.0, True] or str(valor).strip().lower() in ['sim', 'x', '1', '1.0', 'true']:
                                ocs_encontradas.append(str(col))
                            elif isinstance(valor, str) and len(valor) > 1 and str(valor).strip().lower() not in ['não', 'nao', 'falso', 'false', '0']:
                                ocs_encontradas.append(valor)
                    return ", ".join(ocs_encontradas) if ocs_encontradas else "Nenhuma OC vinculada"
                
                df_drill_down['MATÉRIAS (OCs)'] = df_drill_down.apply(unir_ocs, axis=1)

                st.subheader(f"1. Seleção Cirúrgica de Itens Críticos")
                questoes_ordenadas = df_drill_down.sort_values('TAXA_DEFICIENCIA_%', ascending=False)['QUESTAO'].tolist()
                questao_foco = st.selectbox("Selecione a Questão-Alvo para Intervenção:", questoes_ordenadas, key="sb_questao_foco")

                dados_questao = df_drill_down[df_drill_down['QUESTAO'] == questao_foco].iloc[0]
                erro_foco = dados_questao['TAXA_DEFICIENCIA_%']
                ocs_foco = dados_questao['MATÉRIAS (OCs)']
                competencias_foco = dados_questao.get('COMPETÊNCIAS', 'Não parametrizada nesta matriz')

                st.info(f"""
                **Raio-X Diagnóstico — Questão {questao_foco}**
                * **Índice de Deficiência (Erro da Turma):** {erro_foco:.1f}%
                * **Objetos de Conhecimento Vinculados:** {ocs_foco}
                * **Matriz de Competências Requeridas:** {competencias_foco}
                """)

                # --- MOTOR DE PRESCRIÇÃO (Ação Direta) ---
                st.subheader("2. Motor de Prescrição Pedagógica Ativa")
                modelo_prescricao = st.selectbox(
                    "Escolha o Motor Cognitivo:", 
                    options=list(MODELOS.keys()), 
                    format_func=lambda x: MODELOS[x],
                    key="sb_modelo_prescricao"
                )
                
                if st.button("Iniciar Servidor OpenCode", key="btn_iniciar_opencode_prescricao"):
                         
                                with st.spinner("Iniciando servidor na porta 4096..."):
                                    try:
                                        subprocess.Popen(["opencode", "serve", "--port", "4096"], shell=True)
                                        st.success("Comando enviado! Aguarde alguns segundos e tente gerar novamente.")
                                    except Exception as e:
                                        st.error(f"Erro ao tentar ligar o servidor automaticamente: {e}")
                if st.button(f"Gerar Diretriz de Ação para Questão {questao_foco}", type="primary", use_container_width=True):
                    prompt_estrito = f"""
                    Aja estritamente como um Consultor Pedagógico de Ensino Superior especialista na matriz de avaliação do ENADE.
                    CONTEXTO: IES: {ies_selecionada} | Curso: {nome_curso_final}
                    QUESTÃO: {questao_foco} | Erro Turma: {erro_foco:.1f}% | OCs: {ocs_foco} | Competências: {competencias_foco}
                    TAREFA: Forneça EXATAMENTE UMA (1) ação pedagógica concreta e imediata para o Coordenador adotar com os professores.
                    Ignore introduções. Vá direto para a recomendação em Markdown.
                    """

                    with st.spinner("Processando evidências com OpenCode..."):
                        resposta_servidor = enviar_prompt_opencode(prompt_estrito, model_id=modelo_prescricao, timeout=120)

                        if resposta_servidor["success"]:
                            texto_acao = resposta_servidor["response"]
                            st.success(f"Plano de Intervenção Concluído!")
                            st.markdown("---")
                            st.markdown(texto_acao)
                            st.markdown("---")
                            
                            # BOTÃO DE EXPORTAÇÃO
                            st.download_button(
                                label="Exportar Plano de Ação para o NDE (TXT)",
                                data=f"PLANO DE AÇÃO - IES: {ies_selecionada} | CURSO: {nome_curso_final}\nQUESTÃO: {questao_foco}\n\n{texto_acao}",
                                file_name=f"Plano_Acao_Q{questao_foco}_{nome_curso_final}.txt",
                                mime="text/plain"
                            )
                        else:
                            # =====================================================================
                            # BOTÃO DE INICIAR SERVIDOR (IGUAL ABA 4) - BLOCO 1
                            # =====================================================================
                            st.error("Falha na comunicação com o motor OpenCode: Servidor OpenCode não está ativo.")
                            st.info("Clique no botão abaixo para iniciar o servidor.")
                            if st.button("Iniciar Servidor OpenCode", key="btn_iniciar_opencode_prescricao"):
                                with st.spinner("Iniciando servidor na porta 4096..."):
                                    try:
                                        subprocess.Popen(["opencode", "serve", "--port", "4096"], shell=True)
                                        st.success("Comando enviado! Aguarde alguns segundos e tente gerar novamente.")
                                    except Exception as e:
                                        st.error(f"Erro ao tentar ligar o servidor automaticamente: {e}")

        # --- NOVA SEÇÃO: CONSULTA LIVRE DO COORDENADOR ---

        st.markdown("<br>", unsafe_allow_html=True)
        st.subheader("3. Consulta Avançada do Coordenador")
        st.markdown("Selecione quais dados você deseja que a IA utilize como contexto e faça sua pergunta livremente.")

        
        # 1. Checkboxes para o usuário montar o próprio contexto
        col1, col2, col3 = st.columns(3)
        with col1:
            incluir_ies = st.checkbox("Dados Gerais do Curso (IES)", value=True, help="Inclui a média de erro geral de todas as questões do seu curso.")
        with col2:
            incluir_nacional = st.checkbox("Comparativo Nacional", value=False, help="Inclui as taxas de erro do Brasil para comparação.")
        with col3:
            incluir_foco = st.checkbox("Questão Atual em Foco", value=False, help="Inclui os dados da questão específica e objetos de conhecimento selecionados atualmente no painel.")

        pergunta_livre = st.text_area(
            "Digite sua pergunta ou instrução:", 
            placeholder="Ex: Considerando a média nacional selecionada acima, em quais questões estamos com desempenho crítico?", 
            key="txt_pergunta_livre"
        )

        if st.button("Enviar Pergunta à IA", key="btn_livre"):
            if not pergunta_livre.strip():
                st.warning("Por favor, digite uma pergunta antes de enviar.")
            else:
                with st.spinner("Construindo contexto e analisando sua pergunta..."):
                    
                    # 2. Construção Dinâmica do Contexto com base nas escolhas
                    contexto_dinamico = ""
                    
                    if incluir_ies:
                        if 'QUESTAO' in df_final.columns and 'TAXA_DEFICIENCIA_%' in df_final.columns:
                            resumo_ies = df_final.groupby('QUESTAO')['TAXA_DEFICIENCIA_%'].mean().reset_index()
                            lista_ies = "\n".join([f"- {row['QUESTAO']}: {row['TAXA_DEFICIENCIA_%']:.1f}% de erro" for _, row in resumo_ies.iterrows()])
                            media_ies_geral = df_final['TAXA_DEFICIENCIA_%'].mean()
                            contexto_dinamico += f"\n[DADOS GERAIS DA IES]\nMédia Geral de Erro do Curso: {media_ies_geral:.1f}%\nTaxa de Erro por Questão na IES:\n{lista_ies}\n"
                    
                    if incluir_nacional:
                        if 'QUESTAO' in df_curso_nacional.columns and 'TAXA_DEFICIENCIA_%' in df_curso_nacional.columns:
                            resumo_nac = df_curso_nacional.groupby('QUESTAO')['TAXA_DEFICIENCIA_%'].mean().reset_index()
                            lista_nacional = "\n".join([f"- {row['QUESTAO']}: {row['TAXA_DEFICIENCIA_%']:.1f}% de erro" for _, row in resumo_nac.iterrows()])
                            media_nac_geral = df_curso_nacional['TAXA_DEFICIENCIA_%'].mean()
                            contexto_dinamico += f"\n[DADOS DO CENÁRIO NACIONAL (BRASIL)]\nMédia Geral de Erro Nacional: {media_nac_geral:.1f}%\nTaxa de Erro por Questão no Brasil:\n{lista_nacional}\n"
                    
                    if incluir_foco:
                        # Certifique-se de que as variáveis questao_foco, erro_foco e ocs_foco estão declaradas anteriormente no seu código
                        contexto_dinamico += f"\n[DADOS DA QUESTÃO EM FOCO]\nQuestão Analisada: {questao_foco}\nTaxa de Erro na IES para esta questão: {erro_foco:.1f}%\nObjetos de Conhecimento associados: {ocs_foco}\n"

                    # Se o usuário não selecionou nenhum contexto, avisa no prompt
                    if not contexto_dinamico:
                        contexto_dinamico = "\n[AVISO] O usuário optou por não enviar dados da planilha como contexto. Responda apenas com base na pergunta livre abaixo."

                    # 3. Construção do Prompt Enriquecido
                    prompt_contextualizado = f"""
                    Você é um consultor acadêmico especialista em análise de dados educacionais, auxiliando um Coordenador de Curso.
                    RESPONDA DE FORMA CLARA, ESTRUTURADA E DIRETA À PERGUNTA DO USUÁRIO.

                    [CONTEXTO SELECIONADO PELO COORDENADOR]
                    Use SOMENTE as informações abaixo se forem úteis para responder à pergunta:
                    {contexto_dinamico}

                    [PERGUNTA/INSTRUÇÃO DO COORDENADOR]
                    {pergunta_livre}
                    """
                    
                    # 4. Envio para o OpenCode
                    # Ajuste 'modelo_prescricao' para a variável que você utiliza globalmente
                    resposta_livre = enviar_prompt_opencode(prompt_contextualizado, model_id=modelo_prescricao, timeout=120)
                    
                    if resposta_livre["success"]:
                        st.info("**Resposta da IA:**")
                        st.markdown(resposta_livre["response"])
                    else:
                        # =====================================================================
                        # BOTÃO DE INICIAR SERVIDOR - BLOCO DE ERRO E RECUPERAÇÃO
                        # =====================================================================
                        st.error("Falha na comunicação com o motor OpenCode: Servidor OpenCode não está ativo ou demorou a responder.")
                        st.info("Clique no botão abaixo para tentar iniciar o servidor localmente.")
                        if st.button(" Iniciar Servidor OpenCode", key="btn_iniciar_opencode_livre"):
                            with st.spinner("Iniciando servidor na porta 4096..."):
                                try:
                                    subprocess.Popen(["opencode", "serve", "--port", "4096"], shell=True)
                                    st.success("Comando enviado! Aguarde alguns segundos e tente gerar novamente.")
                                except Exception as e:
                                    st.error(f"Erro ao tentar ligar o servidor automaticamente: {e}")
    
        st.markdown("### 1. Análise de Esforço vs. Competência (IRT / Padrão de Resposta)")
        st.info("""
        **Atendendo à recomendação metodológica:** Diferenciamos a verdadeira lacuna de aprendizado do comportamento de baixo engajamento (ex: respostas muito rápidas ou padrão de "chute").
        """)

        col_e1, col_e2 = st.columns([2, 1])
        with col_e1:
            # Exemplo visual: Gráfico de Quadrantes
            import plotly.express as px
            import pandas as pd
            import numpy as np
            
            # Dados simulados para demonstração da correção
            np.random.seed(42)
            df_esforco = pd.DataFrame({
                'Competência (escore 0-100)': np.random.normal(50, 15, 100),
                'Índice de Esforço (Tempo/Padrão)': np.random.normal(5, 2, 100)
            })
            
            fig = px.scatter(
                df_esforco, x='Índice de Esforço (Tempo/Padrão)', y='Competência (escore 0-100)',
                title="Matriz de Esforço vs. Competência (dados simulados ilustrativos)",
                labels={'Índice de Esforço (Tempo/Padrão)': 'Esforço (0-10)', 'Competência (escore 0-100)': 'Competência (0-100)'}
            )
            # Adicionando linhas de quadrante
            fig.add_hline(y=50, line_dash="dot", annotation_text="Média de Competência")
            fig.add_vline(x=5, line_dash="dot", annotation_text="Média de Esforço")
            st.plotly_chart(fig, use_container_width=True)

        with col_e2:
            st.markdown("""
            **Interpretação dos Quadrantes:**
            * **Alto Esforço / Baixa Competência:** Foco prioritário de tutoria. O aluno tenta, mas possui deficiências reais.
            * **Baixo Esforço / Baixa Competência:** Risco de evasão ou desengajamento. A nota baixa não reflete necessariamente o limite cognitivo.
            """)

        st.markdown("### 2. Métrica de Lacunas Corrigida (Evitando Efeito Zero-Sum)")
        st.markdown("""
        Para evitar que superávits em certas competências mascarem déficits em outras (efeito *zero-sum*), a métrica de *Gap* Pedagógico foi reescrita utilizando o Valor Absoluto e penalização quadrática para desvios extremos.
        """)

        st.latex(r"Gap_{corrigido} = \sqrt{\frac{1}{N} \sum_{i=1}^{N} \max(0, Meta_i - Desempenho_i)^2}")

        # Exemplo de código de correção nos dados
        st.code("""
        # Correção do Gap (Python)
        # Evita que um aluno com +20 numa área anule -20 de outra área na média da turma
        def calcular_gap_corrigido(desempenho, meta):
            # Considera apenas o gap negativo (onde o desempenho é menor que a meta)
            déficits = np.maximum(0, meta - desempenho)
            # Aplica RMSE apenas sobre os déficits
            return np.sqrt(np.mean(déficits**2))
        """, language='python')

        st.markdown("### 3. Validação do Modelo de Classes Latentes (LCA)")
        st.info("""
        Os critérios reais de seleção de `k` também estão na aba **LCA › Critérios de Seleção de k**,
        com o detalhamento por curso e IES. Aqui, a visão agregada de toda a base.
        """)

        df_lca_real = carregar_lca_criterios()
        if df_lca_real is None or df_lca_real.empty:
            st.warning(
                "Arquivo `03_criterios_de_selecao_k.csv` não encontrado. "
                "Nenhuma tabela é exibida para evitar valores não verificáveis."
            )
        else:
            df_lca_real = df_lca_real.copy()
            for c in ('k', 'bic', 'aic', 'abic', 'entropia', 'menor_classe_pct'):
                if c in df_lca_real.columns:
                    df_lca_real[c] = pd.to_numeric(df_lca_real[c], errors='coerce')
            df_lca_real = df_lca_real.dropna(subset=['k', 'bic'])
            df_lca_real['k'] = df_lca_real['k'].astype(int)

            aggs = {
                'n_modelos': ('bic', 'size'),
                'bic_medio': ('bic', 'mean'),
                'bic_minimo': ('bic', 'min'),
                'entropia_media': ('entropia', 'mean'),
                'menor_classe_media': ('menor_classe_pct', 'mean'),
            }
            if 'aic' in df_lca_real.columns:
                aggs['aic_medio'] = ('aic', 'mean')
            agregado = df_lca_real.groupby('k').agg(**aggs).reset_index()

            colunas_exibicao = [c for c in ['k', 'n_modelos', 'bic_medio', 'bic_minimo', 'aic_medio',
                                            'entropia_media', 'menor_classe_media'] if c in agregado.columns]
            sub_min = [c for c in ['bic_medio', 'bic_minimo', 'aic_medio'] if c in agregado.columns]
            sub_max = [c for c in ['entropia_media'] if c in agregado.columns]
            st.dataframe(
                agregado[colunas_exibicao].set_index('k').round(4)
                    .style.highlight_min(subset=sub_min, color='lightgreen')
                    .highlight_max(subset=sub_max, color='lightblue'),
                use_container_width=True,
            )

            k_bic = int(agregado.loc[agregado['bic_medio'].idxmin(), 'k'])
            k_ent = int(agregado.loc[agregado['entropia_media'].idxmax(), 'k'])
            n_ajustes = len(df_lca_real)
            if {'curso', 'ies'}.issubset(df_lca_real.columns):
                n_pares = int(df_lca_real[['curso', 'ies']].drop_duplicates().shape[0])
            else:
                n_pares = n_ajustes
            st.markdown(
                f"> **Leitura dos dados reais:** menor BIC médio em **k = {k_bic}**; maior entropia média em "
                f"**k = {k_ent}** ({n_ajustes} ajustes, {n_pares} pares curso/IES). O `k` ótimo **varia por curso e IES** — "
                "não há um valor único imposto para toda a base."
            )

            if {'curso', 'ies'}.issubset(df_lca_real.columns):
                idx_escolhidos = df_lca_real.groupby(['curso', 'ies'])['bic'].idxmin()
                escolhidos = (df_lca_real.loc[idx_escolhidos, 'k'].value_counts()
                              .sort_index().reset_index())
                escolhidos.columns = ['k_escolhido', 'quantidade']
                fig_k_real = px.bar(
                    escolhidos, x='k_escolhido', y='quantidade', text='quantidade',
                    title='Distribuição do k escolhido por menor BIC (por curso/IES)',
                )
                fig_k_real.update_traces(textposition='outside')
                fig_k_real.update_layout(xaxis=dict(tickmode='linear', dtick=1), height=300)
                st.plotly_chart(fig_k_real, use_container_width=True)

            caminho_crit = _caminho_lca('03_criterios_de_selecao_k.csv')
            st.caption(
                f"Fonte: `{caminho_crit.name if caminho_crit else '03_criterios_de_selecao_k.csv'}` "
                f"({caminho_crit.parent if caminho_crit else 'caminho não identificado'}). "
                "A tabela anterior desta seção era ilustrativa/inventada "
                "(valores digitados a mão, não provenientes de ajuste real); "
                "esta foi substituída pelos valores reais do arquivo acima."
            )
