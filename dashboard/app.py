"""
PRISM-EDU Dashboard v4 -- Painel de IA Educacional
4 fontes: ENADE (2004-2023), Referencia ENADE 2023, Licenciaturas 2025, ENAMED 2025
21 abas: 20 historicas + "Qualidade, Proveniencia e Metodos" (governanca do dado).
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path
import sys
import unicodedata
import re
import time
import json
import subprocess
import os
import logging
import threading
import requests
import base64
import atexit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import (
    RAIZ_PROJETO, PASTA_DADOS_PROCESSADOS, PASTA_DADOS_EXTERNOS,
    PASTA_RESULTADOS_ENADE, PASTA_RESULTADOS_LICENCIATURAS, PASTA_RESULTADOS_ENAMED,
    PASTA_SERIE_MICRODADOS,
    PASTA_INTERNACIONAIS, PASTA_MODELOS, CURSOS_MAP, CURSOS_REVERSO,
    CURSOS_MAP_POR_ANO,
    EXAMES_INTERNACIONAIS, MODELOS_OPENCODE, SEPARADOR, ENCODING,
    ANOS_ENADE, ABAS_DASHBOARD,
    listar_edicoes_disponiveis, pasta_saida_edicao,
)

st.set_page_config(page_title="PRISM-EDU v4", layout="wide", page_icon="🎓")

PASTA_REF = RAIZ_PROJETO.parent / "modeloprojetoENADE2023" / "arquivosgerados"
PASTA_ENADE_EXT = PASTA_DADOS_EXTERNOS / "enade"
if not PASTA_ENADE_EXT.exists():
    PASTA_ENADE_EXT = PASTA_DADOS_PROCESSADOS / "por_ano"
PASTA_LIC = PASTA_DADOS_PROCESSADOS / "enadeLicenciaturas"
PASTA_ENAMED = PASTA_DADOS_PROCESSADOS / "enamed"
PASTA_MOD = RAIZ_PROJETO / "modelos"
PASTA_EDA = PASTA_DADOS_PROCESSADOS
# Artefatos CDM/DINA e da ponte LCA->CDM gerados pelo proprio PRISM-EDU.
PASTA_CDM_XLSX = PASTA_MOD / "cdm"
PASTA_LCA_CDM = PASTA_MOD / "cdm"
# Referência legado (modeloprojetoENADE2023) para compatibilidade com artefatos antigos
PASTA_REF_ARQ = RAIZ_PROJETO.parent / "modeloprojetoENADE2023" / "arquivosgerados"
PASTA_REF_EXPL = PASTA_REF_ARQ / "EXPLICACOES_OPENCODE"
PASTA_REF_CDM_XLSX = PASTA_REF_ARQ / "RESULTADOS_FASE6_CDM_XLSX"
PASTA_REF_LCA_CDM = PASTA_REF_ARQ / "RESULTADOS_FASE6_LCA_CDM"
PASTA_REF_LCA = PASTA_REF_ARQ / "RESULTADOS_LCA"


def _subpastas_cdm():
    """Subpastas de modelos/cdm (uma por edicao), mais recentes primeiro."""
    if not PASTA_CDM_XLSX.exists():
        return []
    pastas = [p for p in PASTA_CDM_XLSX.iterdir() if p.is_dir()]
    return sorted(pastas, key=lambda p: p.name, reverse=True)


def _pasta_cdm(edicao=""):
    """Pasta dos artefatos CDM/DINA (perfil, dicionario, validador, ponte).

    Prioriza modelos/cdm/<edicao>; sem edicao selecionada, usa a subpasta de
    edicao mais recente que contenha artefatos CDM. Nunca aponta para a pasta
    de referencia externa.
    """
    if edicao:
        local = PASTA_CDM_XLSX / edicao
        if local.exists() and any(local.iterdir()):
            return local
    for local in _subpastas_cdm():
        if (any(local.glob("diagnostico_cognitivo_*.xlsx"))
                or (local / "comparacao_lca_vs_dina.csv").exists()):
            return local
    return PASTA_CDM_XLSX


def _pasta_cdm_com(padrao, edicao=""):
    """Primeira pasta CDM (edicao selecionada primeiro) que contenha `padrao`."""
    candidatos = []
    if edicao:
        candidatos.append(PASTA_CDM_XLSX / edicao)
    candidatos += _subpastas_cdm()
    candidatos.append(PASTA_CDM_XLSX)
    for pasta in candidatos:
        if pasta.exists() and any(pasta.glob(padrao)):
            return pasta
    return _pasta_cdm(edicao)

EDICAO_MOTORES = ""


def _pasta_edicao_leitura(motor, edicao):
    """Pasta de leitura de um motor, sem criar diretorios.

    Corrige um efeito colateral: ``pasta_saida_edicao`` sempre faz ``mkdir`` e,
    como o dashboard a chamava durante a navegacao, criava pastas de edicao
    vazias que depois "sombreavam" a pasta raiz populada.
    """
    if edicao:
        p = PASTA_MOD / motor / edicao
        try:
            if p.is_dir() and any(p.iterdir()):
                return p
        except OSError:
            pass
    return PASTA_MOD / motor


def _pasta_motor(motor):
    """Pasta de resultados de um motor de IA, respeitando a edicao selecionada."""
    return _pasta_edicao_leitura(motor, EDICAO_MOTORES)


# ===========================================================================
# OPENCODE SERVER MANAGEMENT
# ===========================================================================
OPENCODE_SERVER_URL = "http://localhost:4096"
OPENCODE_USERNAME = "opencode"


def _get_logger():
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


def _senha_efetiva():
    return st.session_state.get("senha_opencode", "").strip()


def _auth_headers():
    senha = _senha_efetiva()
    if senha:
        credentials = f"{OPENCODE_USERNAME}:{senha}"
        encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
        return {"Authorization": f"Basic {encoded}"}
    return {}


def servidor_opencode_ativo():
    try:
        resp = requests.get(f"{OPENCODE_SERVER_URL}/global/health", timeout=3)
        if resp.status_code == 200:
            return True
    except Exception:
        pass
    headers = _auth_headers()
    if headers:
        try:
            resp = requests.get(f"{OPENCODE_SERVER_URL}/global/health", headers=headers, timeout=3)
            return resp.status_code == 200
        except Exception:
            pass
    return False


def _check_zen_rate_limit():
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
                        return {"limited": True, "message": msg, "reset_at": reset_time, "next_timestamp": next_ts}
        return {"limited": False}
    except Exception:
        return {"limited": False}


def procurar_opencode():
    try:
        result = subprocess.run(["opencode", "--version"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return "opencode"
    except Exception:
        pass
    for name in ["opencode-cli.exe", "opencode.exe", "opencode.cmd"]:
        try:
            result = subprocess.run(["where", name], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                return result.stdout.strip().split("\n")[0].strip()
        except Exception:
            pass
    localappdata = os.environ.get("LOCALAPPDATA", "")
    candidatos = [
        Path(localappdata) / "opencode" / "opencode-cli.exe",
        Path(localappdata) / "opencode" / "opencode.exe",
        RAIZ_PROJETO / "opencode.exe",
    ]
    for c in candidatos:
        if c.exists():
            return str(c)
    return None


def iniciar_servidor_opencode():
    if servidor_opencode_ativo():
        return True
    exe = procurar_opencode()
    if not exe:
        return False
    try:
        cmd = [exe, "serve", "--port", "4096"]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(RAIZ_PROJETO))
        st.session_state.opencode_server_proc = proc
        for _ in range(15):
            if servidor_opencode_ativo():
                return True
            time.sleep(1)
        proc.kill()
        return False
    except Exception as e:
        logger.error(f"Erro ao iniciar servidor OpenCode: {e}")
        return False


def _parar_servidor_opencode():
    proc = st.session_state.get("opencode_server_proc")
    if proc and proc.poll() is None:
        try:
            proc.kill()
        except Exception:
            pass


atexit.register(_parar_servidor_opencode)


def enviar_prompt_opencode(prompt, model_id="big-pickle", timeout=300):
    if not servidor_opencode_ativo():
        return {"success": False, "response": "", "error": "Servidor OpenCode nao esta ativo.", "model": model_id}
    url = f"{OPENCODE_SERVER_URL}/session"
    headers = _auth_headers()
    headers["Content-Type"] = "application/json"
    try:
        session_resp = requests.post(url, json={"message": "Analise de dados ENADE"}, headers=headers, timeout=15)
        if session_resp.status_code != 200:
            return {"success": False, "response": "", "error": f"Falha ao criar sessao: HTTP {session_resp.status_code}", "model": model_id}
        session_data = session_resp.json()
        session_id = session_data.get("id")
        if not session_id:
            return {"success": False, "response": "", "error": "Sessao criada sem ID valido.", "model": model_id}
        msg_url = f"{OPENCODE_SERVER_URL}/session/{session_id}/prompt_async"
        msg_body = {"parts": [{"type": "text", "text": prompt}], "model": {"providerID": "opencode", "modelID": model_id}}
        async_resp = requests.post(msg_url, json=msg_body, headers=headers, timeout=30)
        if async_resp.status_code != 204:
            return {"success": False, "response": "", "error": f"Falha ao enviar mensagem: HTTP {async_resp.status_code}", "model": model_id}
        start_time = time.time()
        while time.time() - start_time < timeout:
            time.sleep(3)
            status_resp = requests.get(f"{OPENCODE_SERVER_URL}/session/status", headers=headers, timeout=10)
            if status_resp.status_code == 200:
                status_data = status_resp.json()
                current_status = status_data.get(session_id, {})
                if current_status.get("type") == "retry":
                    error_msg = current_status.get("message", "")
                    if "Free usage exceeded" in error_msg or "rate limit" in error_msg.lower():
                        next_ts = current_status.get("next", 0)
                        reset_time = time.strftime("%H:%M:%S", time.localtime(next_ts / 1000)) if next_ts else "desconhecido"
                        return {"success": False, "response": "", "error": f"Limite de uso gratuito excedido. Reset as {reset_time}.", "model": model_id, "rate_limit_info": {"limited": True, "reset_at": reset_time}}
            msg_list_resp = requests.get(f"{OPENCODE_SERVER_URL}/session/{session_id}/message?limit=5", headers=headers, timeout=10)
            if msg_list_resp.status_code != 200:
                continue
            messages = msg_list_resp.json()
            if not isinstance(messages, list):
                continue
            for msg in messages:
                info = msg.get("info", {})
                if info.get("role") == "assistant":
                    for part in msg.get("parts", []):
                        if part.get("type") == "text":
                            text = part.get("text", "")
                            if text and len(text.strip()) > 10:
                                elapsed = int(time.time() - start_time)
                                return {"success": True, "response": text, "error": "", "model": model_id, "elapsed": elapsed}
        return {"success": False, "response": "", "error": f"Timeout apos {timeout}s.", "model": model_id}
    except requests.exceptions.ConnectionError as e:
        return {"success": False, "response": "", "error": f"Erro de conexao: {str(e)}", "model": model_id}
    except Exception as e:
        return {"success": False, "response": "", "error": f"Erro: {str(e)}", "model": model_id}



# ===========================================================================
# FUNCOES AUXILIARES
# ===========================================================================
def _norm(s):
    s = unicodedata.normalize("NFKD", str(s))
    return "".join(c for c in s if not unicodedata.combining(c)).lower().replace(" ", "_")


def _ler(caminho):
    if caminho and caminho.exists():
        return pd.read_csv(caminho, sep=SEPARADOR, encoding=ENCODING, low_memory=False)
    return None


def _rotular_codigos(serie, mapa, prefixo):
    """Mapeia codigos para rotulos legiveis; desconhecidos viram '<prefixo> <codigo>'."""
    num = pd.to_numeric(serie, errors="coerce")
    out = num.map(mapa)
    mask = out.isna() & num.notna()
    if mask.any():
        out = out.copy()
        out.loc[mask] = prefixo + " " + num[mask].astype(int).astype(str)
    return out


def _buscar(prefixo, pasta, chave):
    if not chave or not pasta or not pasta.exists():
        return None
    alvo = pasta / f"{prefixo}_{chave}.csv"
    if alvo.exists():
        return alvo
    for p in pasta.glob(f"{prefixo}_*.csv"):
        if chave in p.name:
            return p
    # ENAMED: chave e 'enamed_<CO_CURSO>'; os motores gravam '<prefixo>_curso_<CO_CURSO>.csv'.
    if chave.startswith("enamed_"):
        cod = chave.split("_", 1)[1]
        cand = pasta / f"{prefixo}_curso_{cod}.csv"
        if cand.exists():
            return cand
        for p in pasta.glob(f"{prefixo}_curso_*.csv"):
            if p.stem.split("_")[-1] == cod:
                return p
    return None


@st.cache_data(show_spinner=False)
def _carregar_enade(ano):
    return _ler(PASTA_ENADE_EXT / f"relatorio_final_enade_{ano}.csv")


@st.cache_data(show_spinner=False)
def _carregar_lic():
    return _ler(PASTA_LIC / "relatorio_final_enade_licenciaturas_2025.csv")


@st.cache_data(show_spinner=False)
def _carregar_enamed():
    return _ler(PASTA_ENAMED / "relatorio_final_enamed_2025.csv")


@st.cache_data(show_spinner=False)
def _carregar_ref():
    return _ler(PASTA_REF / "relatorio_final_enade_2023.csv")


def _nome_grupo(g, ano=None):
    try:
        cod = int(g)
    except (ValueError, TypeError):
        return f"Grupo {g}"
    if ano is not None:
        grupos_ano = CURSOS_MAP_POR_ANO.get(str(ano), {})
        nome = grupos_ano.get(str(cod))
        if nome:
            return _titulo(nome)
    return CURSOS_MAP.get(cod, f"Grupo {cod}")


def _titulo(nome):
    if not isinstance(nome, str):
        return nome
    palavras = nome.split()
    out = []
    for p in palavras:
        if p.isupper() and len(p) > 1 and not p.isdigit():
            out.append(p[0] + p[1:].lower())
        else:
            out.append(p.capitalize())
    return " ".join(out)


def _tem_colunas(df, *cols):
    return df is not None and all(c in df.columns for c in cols)


def _coerce_numerico(df, colunas):
    for c in colunas:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')
    return df


def _curto(texto, n=46):
    t = str(texto)
    return t if len(t) <= n else t[:n - 1] + "..."


def _norm_oc(texto):
    t = unicodedata.normalize('NFKD', str(texto))
    t = ''.join(c for c in t if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', re.sub(r'\W', ' ', t)).strip().lower()


def _oc_sem_prefixo(texto):
    t = str(texto).strip()
    if re.match(r'^OUTRAS_COMPETENCIAS\s*$', t, re.IGNORECASE):
        return 'outras_competencias'
    m = re.match(r'^([IVXLCDM]{1,6})\s*[-.:]?\s*(.*)$', t)
    if m and m.group(2).strip():
        return m.group(2).strip().strip(';').strip()
    return t.strip(';').strip()


PASTA_ANALISE_IES = PASTA_DADOS_PROCESSADOS / "analise_por_ies_curso_enade.csv"
PASTA_ANALISE_LIC = PASTA_DADOS_PROCESSADOS / "analise_por_questao_ies_licenciaturas_2025.csv"
PASTA_ANALISE_ENAMED = PASTA_DADOS_PROCESSADOS / "analise_por_questao_ies_enamed_2025.csv"
PASTA_QUESTOES_XLSX = Path(__file__).resolve().parent.parent.parent / "seriesTemporais_questoes" / "resultados"


def _extrair_ano_filtro(sel_tipo, sel_id):
    try:
        if sel_tipo == "enade" and sel_id and str(sel_id).startswith("enade_"):
            return int(str(sel_id).split("_")[-1])
        if sel_tipo in ("lic", "enamed"):
            return 2025
    except (ValueError, IndexError):
        pass
    return 2023


@st.cache_data(show_spinner=False)
def _carregar_analise_ies(ano=None, tipo=None):
    ano = ano or 2023
    partes = []
    if tipo in ("lic", "enamed"):
        caminho = PASTA_ANALISE_LIC if tipo == "lic" else PASTA_ANALISE_ENAMED
        if caminho.exists():
            partes.append(pd.read_csv(caminho, sep=";", encoding="utf-8-sig", low_memory=False))
    elif ano == 2025:
        if PASTA_ANALISE_LIC.exists():
            partes.append(pd.read_csv(PASTA_ANALISE_LIC, sep=";", encoding="utf-8-sig", low_memory=False))
        if PASTA_ANALISE_ENAMED.exists():
            partes.append(pd.read_csv(PASTA_ANALISE_ENAMED, sep=";", encoding="utf-8-sig", low_memory=False))
    else:
        caminho_enade = PASTA_DADOS_PROCESSADOS / f"analise_por_questao_ies_enade_{ano}.csv"
        if caminho_enade.exists():
            partes.append(pd.read_csv(caminho_enade, sep=";", encoding="utf-8-sig", low_memory=False))
    if not partes:
        return None
    df_all = pd.concat(partes, ignore_index=True)
    comp_cols = [c for c in df_all.columns if "COMPET" in c.upper()]
    if len(comp_cols) > 1:
        df_all["COMPETENCIAS"] = df_all[comp_cols].apply(
            lambda row: next((str(v) for v in row if pd.notna(v) and str(v).strip() not in ["", "nan"]), ""), axis=1
        )
        for c in comp_cols:
            if c != "COMPETENCIAS":
                df_all.drop(columns=[c], inplace=True, errors="ignore")
    elif len(comp_cols) == 1 and comp_cols[0] != "COMPETENCIAS":
        df_all.rename(columns={comp_cols[0]: "COMPETENCIAS"}, inplace=True)
    for c in ["CO_IES", "CO_CURSO", "CO_GRUPO", "CO_UF_CURSO", "CO_REGIAO_CURSO", "NU_ANO"]:
        if c in df_all.columns:
            df_all[c] = pd.to_numeric(df_all[c], errors="coerce")
    if "TAXA_DEFICIENCIA_%" not in df_all.columns and "QTD_ACERTOS" in df_all.columns and "QTD_ERROS" in df_all.columns:
        total = df_all["QTD_ACERTOS"] + df_all["QTD_ERROS"]
        df_all["TAXA_DEFICIENCIA_%"] = (df_all["QTD_ERROS"] / total.replace(0, np.nan) * 100).fillna(0)
    return df_all


def _filtrar_analise(df_a, ies=None, grupo=None, ano=None):
    if df_a is None or df_a.empty:
        return pd.DataFrame()
    mask = pd.Series(True, index=df_a.index)
    if ies is not None and "CO_IES" in df_a.columns:
        mask &= df_a["CO_IES"] == ies
    if grupo is not None and "CO_GRUPO" in df_a.columns:
        mask &= df_a["CO_GRUPO"] == grupo
    if ano is not None and "NU_ANO" in df_a.columns:
        mask &= df_a["NU_ANO"] == ano
    return df_a[mask].copy()


@st.cache_data(show_spinner=False)
def _carregar_questoes_xlsx(curso_nome, ano=2023, fonte="enade"):
    base = PASTA_QUESTOES_XLSX / fonte / str(ano)
    if not base.exists():
        return None
    nome_lower = curso_nome.lower().strip()
    for xlsx in base.glob("*.xlsx"):
        if xlsx.stem.lower() == nome_lower:
            try:
                return pd.read_excel(xlsx, sheet_name="Table 1")
            except Exception:
                try:
                    return pd.read_excel(xlsx)
                except Exception:
                    return None
    return None


def _medias_por_questao_analise(df_a):
    if df_a is None or df_a.empty or "QUESTAO" not in df_a.columns:
        return pd.DataFrame()
    agg = {}
    for c in df_a.columns:
        if c.startswith("OC"):
            agg[c] = "first"
        elif "PERFIL" in c.upper():
            agg[c] = "first"
        elif "COMPET" in c.upper():
            agg[c] = "first"
        elif "TAXA_DEFICIENCIA" in c.upper():
            agg[c] = "mean"
        elif c == "TOTAL_ALUNOS":
            agg[c] = "sum"
        elif c == "QTD_ERROS":
            agg[c] = "sum"
    agg["QUESTAO"] = "first"
    resultado = df_a.groupby("QUESTAO", as_index=False).agg(agg)
    if "TAXA_DEFICIENCIA_%" in resultado.columns:
        resultado = resultado.sort_values("TAXA_DEFICIENCIA_%", ascending=False)
    return resultado


def limitar_lista_texto(texto, separador, limite):
    """Limita uma lista separada por um separador (ex.: ' | ') a 'limite' itens."""
    if pd.isna(texto) or str(texto).strip() == "" or str(texto).lower() == "nan":
        return "Nenhum dado ou nao aplicavel"
    itens = [i.strip() for i in str(texto).split(separador) if i.strip()]
    return f" {separador} ".join(itens[:limite])


@st.cache_data(show_spinner=False)
def carregar_dados_resumidos():
    p = PASTA_EDA / "analise_por_ies_curso_enade.csv"
    if not p.exists():
        return None
    return pd.read_csv(p, sep=";", encoding=ENCODING, low_memory=False)


@st.cache_data(show_spinner=False)
def carregar_lca_geral(edicao=""):
    path = _pasta_edicao_leitura("lca", edicao) / "01_relatorio_geral_por_ies.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, sep=";", decimal=",", dtype={"ies": str}, low_memory=False)
    if "ies" in df.columns:
        df["ies"] = df["ies"].str.strip()
    return df


@st.cache_data(show_spinner=False)
def carregar_lca_classes(edicao=""):
    path = _pasta_edicao_leitura("lca", edicao) / "02_caracterizacao_das_classes.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, sep=";", decimal=",", dtype={"ies": str}, low_memory=False)
    if "ies" in df.columns:
        df["ies"] = df["ies"].str.strip()
    return df


@st.cache_data(show_spinner=False)
def carregar_lca_criterios(edicao=""):
    path = _pasta_edicao_leitura("lca", edicao) / "03_criterios_de_selecao_k.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, sep=";", decimal=",", dtype={"ies": str}, low_memory=False)
    if "ies" in df.columns:
        df["ies"] = df["ies"].str.strip()
    return df


@st.cache_data(show_spinner=False)
def carregar_dados_diagnostico(nome_curso, edicao=""):
    """Carrega o diagnostico cognitivo por curso (media aluno x OC).
    Procura apenas em modelos/cdm (raiz, subpastas por edicao e dados/processados
    legados) por diagnostico_cognitivo_<curso>.xlsx."""
    if not nome_curso:
        return None
    nome_base = _norm(nome_curso)
    pasta_cdm = _pasta_cdm(edicao)
    candidatos = [pasta_cdm, PASTA_CDM_XLSX] + _subpastas_cdm()
    candidatos += [PASTA_DADOS_PROCESSADOS,
                   PASTA_DADOS_PROCESSADOS / "diagnostico_cognitivo"]
    vistos = set()
    for pasta in candidatos:
        if pasta in vistos or not pasta.exists():
            continue
        vistos.add(pasta)
        alvo = pasta / f"diagnostico_cognitivo_{nome_base}.xlsx"
        if alvo.exists():
            try:
                return pd.read_excel(alvo, engine="openpyxl")
            except Exception:
                return None
        for xlsx in pasta.glob("diagnostico_cognitivo_*.xlsx"):
            if nome_base in _norm(xlsx.stem):
                try:
                    return pd.read_excel(xlsx, engine="openpyxl")
                except Exception:
                    continue
    # Ultimo recurso: varredura recursiva em modelos/cdm
    if PASTA_CDM_XLSX.exists():
        for xlsx in PASTA_CDM_XLSX.rglob("diagnostico_cognitivo_*.xlsx"):
            if nome_base in _norm(xlsx.stem):
                try:
                    return pd.read_excel(xlsx, engine="openpyxl")
                except Exception:
                    continue
    return None


def _candidatos_lca(nome_arquivo, edicao=""):
    cands = []
    if edicao:
        cands.append(_pasta_edicao_leitura("lca", edicao) / nome_arquivo)
    cands.append((PASTA_MOD / "lca") / nome_arquivo)
    cands.append(PASTA_DADOS_PROCESSADOS / nome_arquivo)
    cands.append(PASTA_DADOS_PROCESSADOS / "RESULTADOS_LCA" / nome_arquivo)
    cands.append(PASTA_REF_LCA / nome_arquivo)
    if (PASTA_MOD / "lca").exists():
        cands.extend(sorted((PASTA_MOD / "lca").rglob(nome_arquivo)))
    return cands


def _ler_csv_lca(path, **kwargs):
    for sep, dec in [(";", ","), (",", "."), (";", ".")]:
        try:
            return pd.read_csv(path, sep=sep, decimal=dec, low_memory=False, **kwargs)
        except Exception:
            continue
    return pd.read_csv(path, low_memory=False, **kwargs)


@st.cache_data(show_spinner=False)
def carregar_reanalise_resumo(edicao=""):
    for path in _candidatos_lca("reanalise_resumo.csv", edicao):
        if path.exists():
            return _ler_csv_lca(path)
    return None


@st.cache_data(show_spinner=False)
def carregar_reanalise_por_ies(edicao=""):
    for path in _candidatos_lca("reanalise_por_ies.csv", edicao):
        if path.exists():
            return _ler_csv_lca(path, dtype={"ies": str})
    return None


@st.cache_data(show_spinner=False)
def carregar_robustez_item(edicao=""):
    for path in _candidatos_lca("robustez_brancos_por_item.csv", edicao):
        if path.exists():
            return _ler_csv_lca(path)
    return None


@st.cache_data(show_spinner=False)
def carregar_robustez_oc(edicao=""):
    for path in _candidatos_lca("robustez_brancos_por_oc.csv", edicao):
        if path.exists():
            return _ler_csv_lca(path)
    return None


def _norm_compacto(texto):
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\W", "", t).lower()


def _curto(texto, n=46):
    t = str(texto)
    return t if len(t) <= n else t[: n - 1] + "..."


def _norm_oc(texto):
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"\W", " ", t)).strip().lower()


@st.cache_data(show_spinner=False)
def _ler_perfis_dina(caminho_str):
    return pd.read_csv(caminho_str, sep=";", decimal=",", encoding="utf-8-sig")


def _render_diagnostico_aluno(nome_curso, ies_sel):
    st.markdown("---")
    st.subheader("Diagnostico Cognitivo por Aluno (Fase 6)")
    df_diag = carregar_dados_diagnostico(nome_curso, EDICAO_MOTORES)
    if df_diag is None or df_diag.empty or df_diag.shape[1] < 6:
        st.info(
            f"O perfil psicometrico individual de **{nome_curso}** ainda nao esta disponivel "
            f"(esperado em modelos/cdm/enade_2023/diagnostico_cognitivo_<curso>.xlsx)."
        )
        return
    # filtro IES quando houver coluna compatível; caso contrário, nota honesta
    cols_norm_d = {str(c).strip().upper(): c for c in df_diag.columns}
    c_ies_d = next((cols_norm_d[k] for k in ["CO_IES", "COD_IES", "IES", "CODIGO_IES", "CO_IES_CURSO"] if k in cols_norm_d), None)
    if ies_sel and c_ies_d:
        ies_s = str(ies_sel).strip().replace(".0", "")
        m = df_diag[c_ies_d].astype(str).str.strip().str.replace(r"\.0$", "", regex=True) == ies_s
        if m.any():
            df_diag = df_diag[m].copy()
        else:
            st.warning(f"Filtro IES={ies_sel} ativo, mas sem correspondência na coluna `{c_ies_d}` deste diagnóstico; exibindo dados do curso.")
    elif ies_sel:
        st.caption(f"Filtro IES={ies_sel} ativo na sidebar: o diagnóstico individual (`diagnostico_cognitivo_*.xlsx`) é agregado por curso e não contém coluna IES; a investigação por aluno abaixo corresponde ao curso selecionado.")

    # colunas de disciplina/OC: entre metadados iniciais e colunas finais de resumo
    colunas_disciplinas = [c for c in df_diag.columns if c not in {"ALUNO", "CO_GRUPO", "CO_CURSO", "NOME_CURSO", "Conhecimentos Gerais", "MAIOR_DOMINIO_DISCIPLINA", "PIOR_DEFICIENCIA_DISCIPLINA"} and not str(c).upper().startswith("CO_IES")]
    if len(colunas_disciplinas) < 2 and df_diag.shape[1] >= 6:
        colunas_disciplinas = df_diag.columns[3:-2].tolist()
    if not colunas_disciplinas:
        st.info("Não foi possível identificar colunas de OC/disciplina neste diagnóstico.")
        return

    st.markdown(f"**Raio-X da Turma - {nome_curso}**" + (f" (IES {ies_sel})" if ies_sel and c_ies_d else " (visão por curso)" if ies_sel else ""))
    c1, c2 = st.columns(2)
    with c1:
        deficiencias = df_diag["PIOR_DEFICIENCIA_DISCIPLINA"].value_counts().reset_index()
        deficiencias.columns = ["Disciplina", "Qtd Alunos"]
        fig_def = px.bar(
            deficiencias, x="Qtd Alunos", y="Disciplina", orientation="h",
            title="Materias Mais Criticas (Maior Deficiencia)",
            color_discrete_sequence=["#ef4444"])
        fig_def.update_layout(yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(fig_def, use_container_width=True)
    with c2:
        dominios = df_diag["MAIOR_DOMINIO_DISCIPLINA"].value_counts().reset_index()
        dominios.columns = ["Disciplina", "Qtd Alunos"]
        fig_dom = px.bar(
            dominios, x="Qtd Alunos", y="Disciplina", orientation="h",
            title="Materias de Maior Dominio",
            color_discrete_sequence=["#22c55e"])
        fig_dom.update_layout(yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(fig_dom, use_container_width=True)

    st.markdown("### Perfil Medio de Dominio do Curso")
    for c in colunas_disciplinas:
        df_diag[c] = pd.to_numeric(df_diag[c], errors="coerce")
    medias_turma = df_diag[colunas_disciplinas].mean().reset_index()
    medias_turma.columns = ["Disciplina", "Dominio Medio (%)"]
    fig_radar_turma = go.Figure()
    fig_radar_turma.add_trace(go.Scatterpolar(
        r=medias_turma["Dominio Medio (%)"], theta=medias_turma["Disciplina"],
        fill="toself", name="Media da Turma", line_color="#3b82f6"))
    fig_radar_turma.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
        showlegend=False, margin=dict(t=20, b=20))
    st.plotly_chart(fig_radar_turma, use_container_width=True)

    st.subheader("Investigacao Individual por Aluno")
    ids = df_diag["ALUNO"].astype(str).unique().tolist() if "ALUNO" in df_diag.columns else []
    if not ids:
        st.info("Nenhum identificador de aluno disponível neste diagnóstico.")
        return
    aluno_sel_ui = st.selectbox(
        "Selecione o ID do Aluno para ver o perfil psicometrico exato:",
        ids, key=f"mq_aluno_{_norm_compacto(nome_curso)}_{ies_sel or 'all'}")
    if aluno_sel_ui:
        dados_aluno = df_diag[df_diag["ALUNO"].astype(str) == str(aluno_sel_ui)].iloc[0]
        ca, cb, cc = st.columns(3)
        ca.metric("Maior Facilidade", dados_aluno.get("MAIOR_DOMINIO_DISCIPLINA", "-"))
        cb.metric("Maior Dificuldade", dados_aluno.get("PIOR_DEFICIENCIA_DISCIPLINA", "-"))
        cc.metric("Conhecimentos Gerais", f"{pd.to_numeric(dados_aluno.get('Conhecimentos Gerais', 0), errors='coerce') or 0:.1f}%")
        fig_radar_aluno = go.Figure()
        fig_radar_aluno.add_trace(go.Scatterpolar(
            r=medias_turma["Dominio Medio (%)"], theta=medias_turma["Disciplina"],
            fill=None, mode="lines", name="Media do Curso",
            line_color="rgba(169,169,169,0.5)"))
        fig_radar_aluno.add_trace(go.Scatterpolar(
            r=[pd.to_numeric(dados_aluno.get(c), errors="coerce") for c in colunas_disciplinas], theta=colunas_disciplinas,
            fill="toself", name=f"Aluno: {aluno_sel_ui}", line_color="#8b5cf6"))
        fig_radar_aluno.update_layout(
            polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
            showlegend=True, title=f"Perfil Psicometrico: {aluno_sel_ui} vs Turma",
            margin=dict(t=40, b=20))
        st.plotly_chart(fig_radar_aluno, use_container_width=True)


def _render_ponte_lca_cdm(nome_curso, ies_sel):
    st.markdown("---")
    st.subheader("Ponte LCA -> CDM restrito (DINA) - validacao especialista")
    st.markdown("""
    O pipeline `algoritmos/cdm/ponte_lca_cdm.py` monta a matriz item-OC do INEP (Anexo IX),
    estima o **DINA por EM** (guess *g*, slip *s*, prevalencia *pi* e perfis de dominio por aluno)
    e compara item a item com a LCA exploratoria. Cada curso gera um **workbook de validacao
    especialista** (`validador_matriz_q_<curso>.xlsx`) para conferencia das OC mapeadas.
    """)
    pasta = _pasta_cdm_com("comparacao_lca_vs_dina.csv", EDICAO_MOTORES)
    caminho_comp = pasta / "comparacao_lca_vs_dina.csv"
    if caminho_comp.exists():
        df_comp = pd.read_csv(caminho_comp, sep=";", decimal=",")
        st.markdown("**Concordancia item a item entre LCA e DINA:**")
        cols_comp = [c for c in ["curso", "n_alunos", "n_atributos_dina",
                                 "corr_pearson_item_lca_dina", "r2_item_lca_dina",
                                 "corr_classe_lca_media", "bic_dina"] if c in df_comp.columns]
        if "corr_pearson_item_lca_dina" in df_comp.columns:
            df_comp = df_comp.sort_values("corr_pearson_item_lca_dina", ascending=False)
        st.dataframe(df_comp[cols_comp].reset_index(drop=True), use_container_width=True)

    if not pasta.exists() or not nome_curso:
        st.info("Artefatos da validacao LCA -> CDM nao encontrados. Execute `algoritmos/cdm/ponte_lca_cdm.py`.")
        return

    nome_base = _norm_compacto(nome_curso)
    caminho_dic = pasta / f"dicionario_ocs_{nome_base}.csv"
    caminho_val = pasta / f"validador_matriz_q_{nome_base}.xlsx"

    if caminho_dic.exists():
        st.markdown(f"**Dicionario de OCs - {nome_curso}** (atributos do DINA):")
        try:
            df_dic = pd.read_csv(caminho_dic, sep=";", decimal=",", encoding="utf-8-sig")
            st.dataframe(df_dic, use_container_width=True)
        except Exception:
            st.info("Nao foi possivel ler o dicionario de OCs.")

    if caminho_val.exists():
        st.markdown(f"**Workbook de validacao - {nome_curso}**")
        abas_val = ["Matriz_Q_Item_x_OC", "Resumo_Cobertura", "Concordancia_Empirica_LCA"]
        try:
            abas_val = pd.ExcelFile(caminho_val, engine="openpyxl").sheet_names or abas_val
        except Exception:
            pass
        aba_val = st.selectbox("Aba do validador:", abas_val, key=f"aba_val_{nome_base}")
        try:
            df_val = pd.read_excel(caminho_val, sheet_name=aba_val, engine="openpyxl")
            st.dataframe(df_val, use_container_width=True)
        except Exception:
            st.info("Nao foi possivel ler o workbook de validacao.")
        st.caption("Altere a coluna STATUS/OC_* para registrar a validacao do especialista (arquivo original fica intacto).")
    else:
        st.info("Workbook de validacao nao encontrado para este curso.")

    st.divider()
    st.subheader("Analise Estrategica - Dominio por Competencia (OC)")
    st.caption("Diagnostico prescritivo a partir dos perfis DINA: onde estao as lacunas, "
               "como o curso se compara a media nacional e quais alunos estao em risco.")

    dics = sorted(pasta.glob("dicionario_ocs_*.csv"))
    linhas_dic = []
    for f in dics:
        curso_arquivo = f.stem.replace("dicionario_ocs_", "")
        try:
            dfd = pd.read_csv(f, sep=";", decimal=",", encoding="utf-8-sig")
        except Exception:
            continue
        dfd.columns = [str(c).strip() for c in dfd.columns]
        for _, r in dfd.iterrows():
            linhas_dic.append({
                "curso_arquivo": curso_arquivo,
                "rotulo": str(r.get("rotulo", "")),
                "oc_principal": str(r.get("oc_principal", "")),
                "oc_exibicao": _oc_sem_prefixo(str(r.get("oc_principal", ""))),
                "n_itens": pd.to_numeric(r.get("n_itens_medidos"), errors="coerce"),
                "prevalencia": pd.to_numeric(r.get("prevalencia_dominio_dina"), errors="coerce"),
            })
    df_dic_todos = pd.DataFrame(linhas_dic)
    if df_dic_todos.empty:
        st.info("Nenhum dicionario de OCs encontrado para a analise estrategica.")
        return
    df_dic_todos["oc_norm"] = df_dic_todos["oc_principal"].apply(lambda s: _norm_oc(_oc_sem_prefixo(s)))

    with st.expander("Heatmap - dominio medio por OC transversal x curso (lacunas sistemicas)", expanded=True):
        cont = df_dic_todos.groupby("oc_norm")["curso_arquivo"].nunique()
        ocs_comp = cont[cont >= 5].index.tolist()
        if ocs_comp:
            _dfp = df_dic_todos[df_dic_todos["oc_norm"].isin(ocs_comp)].copy()
            _dfp["oc_exib"] = _dfp.groupby("oc_norm")["oc_exibicao"].transform("first")
            _exib = _dfp.drop_duplicates("oc_norm").set_index("oc_norm")["oc_exib"]
            piv = _dfp.pivot_table(index="oc_norm", columns="curso_arquivo",
                                   values="prevalencia", aggfunc="first")
            piv = piv.loc[[o for o in ocs_comp if o in piv.index]]
            piv = piv.loc[piv.notna().sum(axis=1).sort_values(ascending=False).index]
            ordem_cols = sorted(piv.columns, key=lambda c: 0 if c == nome_base else 1)
            piv = piv[ordem_cols]
            fig_heat_oc = px.imshow(
                piv, zmin=0, zmax=1, color_continuous_scale="RdYlGn",
                labels=dict(x="Curso", y="Competencia (OC)", color="Dominio medio"),
                aspect="auto")
            fig_heat_oc.update_yaxes(
                ticktext=[_curto(_exib.get(i, i)) for i in piv.index],
                tickvals=list(range(len(piv.index))))
            st.plotly_chart(fig_heat_oc, use_container_width=True)
            st.caption("Somente competencias transversais presentes em >=5 cursos sao comparaveis entre cursos; "
                       "cada curso tem um conjunto proprio de OC na matriz-Q do INEP (celulas vazias = OC inexistente).")
        else:
            st.info("Nenhuma competencia transversal comum a >=5 cursos foi encontrada.")

    caminho_resumo = pasta / "00_resumo_geral.csv"
    if caminho_resumo.exists():
        with st.expander("Matriz de saude psicometrica - curso x indicador", expanded=False):
            try:
                df_res = pd.read_csv(caminho_resumo, sep=";", decimal=",")
                df_res.columns = [str(c).strip() for c in df_res.columns]
                prev_media = df_dic_todos.groupby("curso_arquivo")["prevalencia"].mean()
                fracas = df_dic_todos[df_dic_todos["n_itens"] < 2].groupby("curso_arquivo").size()
                df_res["dominio_medio"] = df_res["curso"].apply(_norm_compacto).map(prev_media)
                df_res["n_oc_frageis"] = df_res["curso"].apply(_norm_compacto).map(fracas).fillna(0).astype(int)
                df_res["disc_medio"] = (1 - df_res["slip_medio"] - df_res["guess_medio"]).clip(0, 1)
                df_res = df_res.sort_values("dominio_medio")
                cols_ind = [c for c in ["dominio_medio", "n_oc_frageis", "disc_medio", "taxa_acerto_media",
                                        "guess_medio", "slip_medio"] if c in df_res.columns]
                _z = pd.DataFrame(index=df_res.index, columns=cols_ind, dtype=float)
                for _c in cols_ind:
                    _mn, _mx = df_res[_c].min(), df_res[_c].max()
                    _esc = (df_res[_c] - _mn) / (_mx - _mn + 1e-9)
                    if _c in ["n_oc_frageis", "guess_medio", "slip_medio"]:
                        _esc = 1 - _esc
                    _z[_c] = _esc
                _txt = []
                for _, _rr in df_res[cols_ind].iterrows():
                    _txt.append([str(int(v)) if _c == "n_oc_frageis" else f"{v:.2f}"
                                 for _c, v in _rr.items()])
                fig_heat_saude = go.Figure(go.Heatmap(
                    z=_z.values,
                    x=[_curto(c, 18) for c in cols_ind],
                    y=[_curto(c, 26) for c in df_res["curso"]],
                    text=np.array(_txt, dtype=object),
                    texttemplate="%{text}",
                    hovertemplate="%{y}<br>%{x}: %{text}<extra></extra>",
                    colorscale="RdYlGn", zmin=0, zmax=1))
                fig_heat_saude.update_layout(margin=dict(t=10, b=10), height=460)
                st.plotly_chart(fig_heat_saude, use_container_width=True)
                st.caption("Cor = posicao relativa do curso (verde = melhor; para 'n_oc_frageis', verde = poucas fragilidades). "
                           "Valores exatos sao exibidos em cada celula.")
            except Exception:
                st.info("Nao foi possivel montar a matriz de saude psicometrica.")

    df_sel = df_dic_todos[df_dic_todos["curso_arquivo"] == nome_base].copy()
    if df_sel.empty:
        st.info(f"Sem dicionario de OCs para **{nome_curso}** na validacao LCA -> CDM.")
        return

    st.markdown(f"**Dominio das OCs - {nome_curso} vs media nacional**")
    bench = (df_dic_todos[df_dic_todos["curso_arquivo"] != nome_base]
             .groupby("oc_norm")["prevalencia"].mean())
    df_sel["bench_nacional"] = df_sel["oc_norm"].map(bench)
    df_sel = df_sel.sort_values("prevalencia")
    curso_v = df_sel["prevalencia"].to_numpy(dtype=float)
    bench_v = df_sel["bench_nacional"].to_numpy(dtype=float)
    ypos = np.arange(len(df_sel))
    cores = ["#16a34a" if (pd.notna(b) and c >= b) else "#dc2626"
             for c, b in zip(curso_v, bench_v)]
    fig_loll = go.Figure()
    for i, (cb, cc) in enumerate(zip(bench_v, curso_v)):
        if pd.notna(cb):
            fig_loll.add_trace(go.Scatter(
                x=[cb, cc], y=[i, i], mode="lines",
                line=dict(color="rgba(100,116,139,0.35)", width=1.5),
                showlegend=False, hoverinfo="skip"))
    fig_loll.add_trace(go.Scatter(
        x=bench_v, y=ypos, mode="markers", name="Media nacional (cursos com a mesma OC)",
        marker=dict(symbol="diamond-open", size=9, color="#64748b")))
    fig_loll.add_trace(go.Scatter(
        x=curso_v, y=ypos, mode="markers", name="Este curso",
        marker=dict(size=11, color=cores, line=dict(width=1, color="#1e293b"))))
    fig_loll.update_layout(
        height=max(380, 42 * len(df_sel)),
        yaxis=dict(tickmode="array", tickvals=ypos,
                   ticktext=[_curto(l, 54) for l in df_sel["oc_exibicao"]],
                   autorange="reversed"),
        xaxis_title="Probabilidade media de dominio (DINA)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(t=30, b=10))
    st.plotly_chart(fig_loll, use_container_width=True)
    st.caption("Verde = curso acima da media nacional para a mesma OC; vermelho = abaixo. "
               "OCs sem benchmark nacional exibem apenas o valor do curso.")

    caminho_perfis = pasta / f"dina_perfis_alunos_{nome_base}.csv"
    if caminho_perfis.exists():
        try:
            df_perf = _ler_perfis_dina(str(caminho_perfis))
        except Exception:
            df_perf = None
        if df_perf is not None and not df_perf.empty:
            st.markdown(f"**Distribuicao de alunos por n de OCs dominadas - {nome_curso}**")
            n_ocs = int(df_sel.shape[0])
            meio = n_ocs / 2.0
            fig_hist = px.histogram(df_perf, x="n_ocs_dominadas", nbins=max(n_ocs, 2),
                                    color_discrete_sequence=["#3b82f6"])
            fig_hist.update_layout(bargap=0.08, xaxis_title="N de OCs dominadas",
                                   yaxis_title="N de alunos", margin=dict(t=20, b=10))
            fig_hist.add_vline(x=meio, line_dash="dash", line_color="#ef4444",
                               annotation_text="metade das OCs", annotation_position="top")
            st.plotly_chart(fig_hist, use_container_width=True)
            pct_abaixo = float((df_perf["n_ocs_dominadas"] < meio).mean() * 100)
            st.caption(f"{pct_abaixo:.1f}% dos alunos dominam menos da metade das {n_ocs} OCs do curso.")

            st.markdown("**Alunos em risco por OC (top decil de fraqueza)**")
            oc_escolhida = st.selectbox(
                "Selecione a OC para investigar:", df_sel["rotulo"].tolist(),
                format_func=lambda r: _curto(
                    df_sel.loc[df_sel["rotulo"] == r, "oc_exibicao"].iloc[0], 60),
                key=f"oc_risco_{nome_base}")
            col_mastery = f"mastery_{oc_escolhida}"
            col_alpha = f"alpha_{oc_escolhida}"
            if col_mastery in df_perf.columns:
                desc_oc = df_sel.loc[df_sel["rotulo"] == oc_escolhida, "oc_principal"].iloc[0]
                st.markdown(f"OC **{oc_escolhida}** - {desc_oc}")
                try:
                    cod_ies = int(ies_sel) if ies_sel is not None else None
                except Exception:
                    cod_ies = None
                df_risco = df_perf.copy()
                if cod_ies is not None and "CO_IES" in df_risco.columns:
                    df_risco = df_risco[df_risco["CO_IES"] == cod_ies]
                df_risco = df_risco[df_risco[col_alpha] == 0]
                n_risco_total = len(df_risco)
                if n_risco_total == 0:
                    st.info("Nenhum aluno desta IES deixou de dominar essa OC no perfil DINA.")
                else:
                    top = max(1, int(np.ceil(n_risco_total * 0.10)))
                    df_risco = df_risco.nsmallest(top, col_mastery)
                    cols_risco = [c for c in ["ALUNO", "CO_IES", "NT_DIS_CE",
                                              col_mastery, col_alpha, "n_ocs_dominadas"]
                                  if c in df_risco.columns]
                    df_risco = df_risco[cols_risco].sort_values(col_mastery)
                    df_risco.columns = ["ALUNO", "CO_IES", "NT_DIS_CE", "P(domina)",
                                        "Decisao DINA", "N OCs dominadas"][:len(cols_risco)]
                    st.dataframe(df_risco.reset_index(drop=True), use_container_width=True)
                    st.caption(f"{n_risco_total} alunos da IES {cod_ies} nao dominam a OC - "
                               f"exibidos os {len(df_risco)} com menor P(domina) (top decil).")


def _render_relacao_perfil_oc(df_questoes_mat):
    if df_questoes_mat is None or df_questoes_mat.empty:
        return
    if "TAXA_DEFICIENCIA_%" not in df_questoes_mat.columns:
        return
    dfq = df_questoes_mat.copy()
    dfq["TAXA_DEFICIENCIA_%"] = pd.to_numeric(dfq["TAXA_DEFICIENCIA_%"], errors="coerce")
    dfq = dfq.dropna(subset=["TAXA_DEFICIENCIA_%"])
    if dfq.empty:
        return
    st.markdown("---")
    st.subheader("Relacao Perfil / Competencia / Objeto de Conhecimento")
    st.markdown("""
    Cruza a taxa media de deficiencia das questoes com os mapeamentos oficiais do INEP
    (**Perfil** profissional e **Competencias**), alem dos **Objetos de Conhecimento (OC)**.
    Permite identificar qual perfil de egresso e qual competencia concentram as maiores lacunas.
    """)
    colunas_perfil = [c for c in dfq.columns if "PERFIL" in c.upper()]
    colunas_comp = [c for c in dfq.columns if "COMPET" in c.upper()]

    def _agrega(colunas):
        registros = []
        for c in colunas:
            for valor, grp in dfq.groupby(dfq[c].astype(str).str.strip()):
                valor = valor.strip()
                if not valor or valor.lower() == "nan":
                    continue
                registros.append({
                    "Rotulo": valor,
                    "Taxa_Deficiencia_%": round(grp["TAXA_DEFICIENCIA_%"].mean(), 1),
                    "N_Questoes": len(grp),
                })
        return pd.DataFrame(registros)

    for titulo, colunas, cor in [
        ("Perfil profissional", colunas_perfil, "#6366f1"),
        ("Competencia", colunas_comp, "#0ea5e9"),
    ]:
        df_ag = _agrega(colunas)
        if df_ag.empty:
            continue
        df_ag = df_ag.groupby("Rotulo", as_index=False).agg(
            {"Taxa_Deficiencia_%": "mean", "N_Questoes": "sum"})
        df_ag["Taxa_Deficiencia_%"] = df_ag["Taxa_Deficiencia_%"].round(1)
        df_ag = df_ag.sort_values("Taxa_Deficiencia_%", ascending=False)
        st.markdown(f"**{titulo} x Taxa de Deficiencia**")
        fig = px.bar(
            df_ag.head(15), x="Taxa_Deficiencia_%", y="Rotulo", orientation="h",
            color="Taxa_Deficiencia_%", color_continuous_scale="RdYlGn_r",
            text="Taxa_Deficiencia_%", hover_data=["N_Questoes"],
            title=f"{titulo}: questoes com maior taxa media de erro")
        fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
        fig.update_layout(height=max(320, 32 * min(len(df_ag), 15)),
                          yaxis={"categoryorder": "total ascending"}, xaxis_tickangle=0)
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(df_ag, use_container_width=True)


def _obter_filtro_analise(df_a):
    ies_f = ies_sel if ies_sel else None
    grupo_f = curso_codigo if curso_codigo else None
    ano_f = _extrair_ano_filtro(sel_tipo, sel_id)
    # Garante que df_a traga a edicao correta (por ano, memoria leve).
    tem_ano = (
        df_a is not None and not df_a.empty
        and "NU_ANO" in df_a.columns and (df_a["NU_ANO"] == ano_f).any()
    )
    if not tem_ano:
        df_a = _carregar_analise_ies(ano_f)
    if df_a is None or df_a.empty:
        return pd.DataFrame()
    df_f = _filtrar_analise(df_a, ies=ies_f, grupo=grupo_f, ano=ano_f)
    if df_f.empty and grupo_f is not None:
        df_f = _filtrar_analise(df_a, grupo=grupo_f, ano=ano_f)
    if df_f.empty and sel_tipo == "enamed":
        df_f = _filtrar_analise(df_a, grupo=0, ano=2025)
    if df_f.empty:
        df_f = _filtrar_analise(df_a, ano=ano_f)
    return df_f


# ===========================================================================
# RANKING IA POR IES (K-MEANS) -- portado de fase5/analiseIE.py
# ===========================================================================
def _num_q(texto):
    m = re.search(r"Q(\d{1,3})\s*$", str(texto).strip())
    return int(m.group(1)) if m else None


def _mapa_questoes_curso(grupo, ano, tipo=None):
    if grupo is None:
        return {}
    df_a = _carregar_analise_ies(ano, tipo)
    if df_a is None:
        return {}
    df_m = _filtrar_analise(df_a, grupo=grupo, ano=ano)
    if df_m.empty:
        return {}
    oc_cols = [c for c in df_m.columns if str(c).startswith("OC")]
    comp_col = next((c for c in df_m.columns if "COMPET" in c.upper()), None)
    mapa = {}
    for _, row in df_m.iterrows():
        qn = _num_q(row.get("QUESTAO"))
        if qn is None:
            continue
        ocs = " + ".join(
            str(row.get(c)).strip() for c in oc_cols
            if pd.notna(row.get(c)) and str(row.get(c)).strip() and str(row.get(c)).lower() != "nan"
        )
        comp = str(row.get(comp_col)).strip() if comp_col else ""
        if comp.lower() == "nan":
            comp = ""
        mapa.setdefault(qn, {"ocs": ocs or "Nao especificado", "comp": comp or "Nao especificada"})
    return mapa


def _kmeans_perfis(df_ies, q_cols, mapa_q):
    from sklearn.cluster import KMeans
    num_perfis = 3 if len(df_ies) >= 10 else 2
    X = df_ies[q_cols].astype(str).apply(lambda s: s.str.strip().eq("1").astype(float)).to_numpy(dtype=float)
    kmeans = KMeans(n_clusters=num_perfis, random_state=42, n_init=10)
    rotulos = kmeans.fit_predict(X)
    media_geral = X.mean()
    titulos = ["Alto Desempenho", "Intermediario", "Risco Critico"]

    notas = {}
    for pid in range(num_perfis):
        sub = X[rotulos == pid]
        if len(sub):
            notas[pid] = sub.sum(axis=1).mean()
    ordem = sorted(notas, key=notas.get, reverse=True)

    perfis = []
    for rank, pid in enumerate(ordem):
        sub = X[rotulos == pid]
        taxa_acertos_grupo = sub.mean(axis=0)
        diferenca_para_media = taxa_acertos_grupo - media_geral
        piores = diferenca_para_media.argsort()[:2]
        detalhes = []
        for qi in piores:
            numq = _num_q(q_cols[qi])
            hin = mapa_q.get(numq, {})
            detalhes.append({
                "questao": f"Q{numq}",
                "erro": round((1 - taxa_acertos_grupo[qi]) * 100, 1),
                "gap": round(diferenca_para_media[qi] * 100, 1),
                "ocs": hin.get("ocs", "Nao especificado"),
                "comp": hin.get("comp", "Nao especificada"),
            })
        perfis.append({
            "nome": titulos[rank] if rank < 3 else f"Grupo {rank}",
            "qtd": int(len(sub)),
            "media": float(notas[pid]),
            "detalhes": detalhes,
        })
    return perfis


def _perfis_para_df(perfis, ies=None):
    linhas = []
    for p in perfis:
        for d in p["detalhes"]:
            linhas.append({
                "IES": "" if ies is None else ies,
                "Perfil_IA": p["nome"],
                "Qtd_Alunos": p["qtd"],
                "Media_Acertos": round(p["media"], 2),
                "Questao": d["questao"],
                "Erro_%": d["erro"],
                "GAP_%": d["gap"],
                "OCs": d["ocs"],
                "Competencia": d["comp"],
            })
    return pd.DataFrame(linhas)


def _ranking_html(df_rank, titulo):
    cabeçalho = "".join(f"<th>{c}</th>" for c in df_rank.columns)
    linhas = ""
    for _, r in df_rank.iterrows():
        linhas += "<tr>" + "".join(f"<td>{r[c]}</td>" for c in df_rank.columns) + "</tr>"
    return f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<title>{titulo}</title><style>
body{{font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;line-height:1.6;margin:40px;color:#333;background-color:#f4f7f6;}}
.container{{background-color:#fff;padding:30px;border-radius:8px;box-shadow:0 4px 8px rgba(0,0,0,0.1);}}
h1{{color:#2980b9;border-bottom:2px solid #3498db;padding-bottom:10px;}}
table{{width:100%;border-collapse:collapse;margin-top:20px;font-size:14px;}}
th,td{{padding:12px 15px;border:1px solid #ddd;text-align:left;}}
th{{background-color:#2c3e50;color:#fff;text-transform:uppercase;font-size:12px;position:sticky;top:0;}}
tr:hover{{background-color:#f1f5f8;}}
.footer{{margin-top:40px;font-size:13px;color:#7f8c8d;text-align:center;}}
</style></head><body><div class="container">
<h1>{titulo}</h1><table><thead><tr>{cabeçalho}</tr></thead><tbody>{linhas}</tbody></table>
<div class="footer">Relatorio de Prescricao Educacional gerado por motor de IA (K-Means) -- portado de analiseIE.py.</div>
</div></body></html>"""


# ===========================================================================
# SIDEBAR
# ===========================================================================
with st.sidebar:
    st.title("🎓 PRISM-EDU")
    st.caption("IA Educacional v4")
    st.divider()

    st.header("Fontes de Dados")
    chk_enade = st.checkbox("ENADE (2004-2023)", value=True, key="c_enade")
    chk_ref = st.checkbox("Referencia ENADE 2023", value=True, key="c_ref")
    chk_lic = st.checkbox("ENADE Licenciaturas 2025", value=True, key="c_lic")
    chk_enamed = st.checkbox("ENAMED 2025", value=True, key="c_enamed")
    st.divider()

    st.header("Selecao de Exame")
    opcoes = []
    if chk_ref:
        arq_ref = PASTA_REF / "relatorio_final_enade_2023.csv"
        if arq_ref.exists():
            opcoes.append(("Referencia ENADE 2023", "ref_2023", "ref"))
    if chk_enade and PASTA_ENADE_EXT.exists():
        for p in sorted(PASTA_ENADE_EXT.glob("relatorio_final_enade_*.csv")):
            try:
                ano = int(p.stem.split("_")[-1])
                opcoes.append((f"ENADE {ano}", f"enade_{ano}", "enade"))
            except (ValueError, IndexError):
                pass
    if chk_lic:
        if PASTA_LIC.exists() and any(PASTA_LIC.glob("*.csv")):
            opcoes.append(("ENADE Licenciaturas 2025", "lic_2025", "lic"))
    if chk_enamed:
        if PASTA_ENAMED.exists() and any(PASTA_ENAMED.glob("*.csv")):
            opcoes.append(("ENAMED 2025", "enamed_2025", "enamed"))
    if not opcoes:
        st.warning("Selecione ao menos uma fonte.")
        st.stop()
    labels = [o[0] for o in opcoes]
    sel_label = st.selectbox("Exame:", labels, index=len(labels) - 1)
    idx = labels.index(sel_label)
    sel_id = opcoes[idx][1]
    sel_tipo = opcoes[idx][2]
    st.divider()

    st.header("Edicao dos Motores IA")
    st.caption("Resultados dos motores (clustering, LCA, preditivos, SHAP, XAI, CDM, SOM, NLP).")
    ed_opts = ["(Padrao - raiz modelos/)"] + sorted(listar_edicoes_disponiveis())
    ed_sel = st.selectbox("Edicao:", ed_opts, key="sb_edicao_motores")
    EDICAO_MOTORES = "" if ed_sel.startswith("(") else ed_sel
    st.divider()

    df = None
    if sel_tipo == "ref":
        df = _carregar_ref()
    elif sel_tipo == "enade":
        ano = int(sel_id.split("_")[1])
        df = _carregar_enade(ano)
    elif sel_tipo == "lic":
        df = _carregar_lic()
    elif sel_tipo == "enamed":
        df = _carregar_enamed()

    tem_ies = _tem_colunas(df, "CO_IES") and df["CO_IES"].notna().any()
    tem_grupo = _tem_colunas(df, "CO_GRUPO") and df["CO_GRUPO"].notna().any()
    ies_sel = None
    sel_grupo = None
    curso_codigo = None
    nome_curso = None
    chave_curso = None
    df_curso = None
    df_nacional = None
    ano_fil = _extrair_ano_filtro(sel_tipo, sel_id)

    if df is not None and tem_ies and tem_grupo:
        st.header("Filtros")
        ies_opts = sorted(df["CO_IES"].dropna().unique())
        ies_sel = st.selectbox("IES:", ies_opts, key="sb_ies")
        df_ies = df[df["CO_IES"] == ies_sel]
        grupos = sorted(df_ies["CO_GRUPO"].dropna().unique())
        if grupos:
            sel_grupo = st.selectbox(
                "Curso:", grupos,
                format_func=lambda g: _nome_grupo(g, ano_fil), key="sb_grupo")
            curso_codigo = sel_grupo
            nome_curso = _nome_grupo(sel_grupo, ano_fil)
            chave_curso = _norm(nome_curso)
            df_curso = df_ies[df_ies["CO_GRUPO"] == sel_grupo].copy()
            df_nacional = df[df["CO_GRUPO"] == sel_grupo].copy()
        else:
            st.info("Nenhum curso encontrado para esta IES.")
    elif df is not None and not tem_ies:
        if sel_tipo == "enamed":
            st.info("ENAMED: selecione por CO_CURSO (sem IES/Grupo)")
            if "CO_CURSO" in df.columns:
                cursos_enamed = sorted(df["CO_CURSO"].dropna().unique())
                sel_curso_enamed = st.selectbox("CO_CURSO:", cursos_enamed, key="sb_enamed_curso")
                df_curso = df[df["CO_CURSO"] == sel_curso_enamed].copy()
                df_nacional = df.copy()
                nome_curso = f"ENAMED CO_CURSO {sel_curso_enamed}"
                chave_curso = f"enamed_{sel_curso_enamed}"

    st.divider()
    st.markdown("### OpenCode")
    senha_opencode = st.text_input(
        "Senha (opcional):", type="password", key="senha_opencode",
        help="Senha para conexao com servidor OpenCode remoto."
    )
    n_reg = len(df) if df is not None else 0
    st.metric("Registros", f"{n_reg:,}")
    if nome_curso:
        st.caption(f"Curso: {nome_curso}")
    st.divider()
    if st.button("Sair e Fechar", use_container_width=True, key="btn_sair"):
        st.success("A encerrar... Feche a janela ou volte ao menu principal.")
        os._exit(0)


# ===========================================================================
# HEADER
# ===========================================================================
st.title("PRISM-EDU -- Painel de IA Educacional")
st.markdown("**K-Means + LCA + OpenCode** -- Analise de Perfis de Aprendizagem com Explicacao em Linguagem Natural")
st.caption(f"Exame ativo: **{sel_label}** | {n_reg:,} registros")
st.divider()


# ===========================================================================
# ABAS - 21 TABS (20 historicas + Qualidade/Proveniencia/Metodos)
# ===========================================================================
ABAS = ABAS_DASHBOARD
aba = st.radio("Menu:", ABAS, index=0, horizontal=True, label_visibility="collapsed")



# --- TAB 0: DIAGNOSTICO E PRESCRICAO ---
if aba == ABAS[0]:
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
        df_filtrado = _obter_filtro_analise(df_a)
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

                # --- Panorama Nacional (fase 5): top 5 questoes mais dificeis do curso em todo o Brasil ---
                if sel_grupo is not None and "CO_GRUPO" in df_a.columns:
                    df_grupo_nac = _filtrar_analise(df_a, grupo=sel_grupo, ano=ano_fil)
                    if not df_grupo_nac.empty:
                        df_nac_questoes = _medias_por_questao_analise(df_grupo_nac)
                        if not df_nac_questoes.empty and "TAXA_DEFICIENCIA_%" in df_nac_questoes.columns:
                            st.markdown("---")
                            st.subheader("Panorama Nacional -- Top 5 Questoes com Maior Deficiencia no Brasil")
                            df_top_nac = df_nac_questoes.head(5).copy()
                            colunas_oc_nac = [c for c in df_top_nac.columns if c.startswith("OC")]

                            def _unir_ocs_nac(row):
                                lista = [str(row.get(c)).strip() for c in colunas_oc_nac
                                         if pd.notna(row.get(c)) and str(row.get(c)).strip()
                                         and str(row.get(c)).lower() != "nan"]
                                return " + ".join(lista) if lista else "Nao especificado"

                            c_graf_nac, c_tab_nac = st.columns([1, 1.8])
                            with c_graf_nac:
                                fig_nac = px.bar(df_top_nac, x="QUESTAO", y="TAXA_DEFICIENCIA_%",
                                                 text="TAXA_DEFICIENCIA_%", color="TAXA_DEFICIENCIA_%",
                                                 color_continuous_scale="Oranges")
                                fig_nac.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
                                fig_nac.update_layout(yaxis_range=[0, 115])
                                st.plotly_chart(fig_nac, use_container_width=True)
                            with c_tab_nac:
                                df_top_nac["MATERIAS (OCs)"] = df_top_nac.apply(_unir_ocs_nac, axis=1)
                                cols_tn = ["QUESTAO", "TAXA_DEFICIENCIA_%", "MATERIAS (OCs)"]
                                comp_col_nac = next((c for c in df_top_nac.columns if "COMPET" in c.upper()), None)
                                if comp_col_nac:
                                    cols_tn.append(comp_col_nac)
                                st.dataframe(
                                    df_top_nac[cols_tn].rename(
                                        columns={"TAXA_DEFICIENCIA_%": "ERRO NACIONAL (%)"}).reset_index(drop=True),
                                    use_container_width=True)
                            st.caption("O panorama nacional compara as questoes com maior erro do curso em todo o Brasil, "
                                       "permitindo distinguir deficiencias proprias da IES das que sao nacionais.")
        else:
            st.info("Nenhum dado de analise por questao disponivel para o curso/IES selecionado.")


# --- TAB 1: FATORES DE SUCESSO (PREDITIVO) ---
elif aba == ABAS[1]:
    st.header("Fatores de Sucesso (Preditivo)")
    st.markdown("""
    **Metodologia:** O motor preditivo identifica quais variaveis (questoes, caracteristicas socioeconomicas)
    mais contribuem para o sucesso ou fracasso do aluno. Utiliza **Random Forest** e **SHAP (TreeExplainer)**
    para explicabilidade honesta (sem simulacao). As importancias sao calculadas com validacao cruzada.
    """)
    if chave_curso:
        arq = _buscar("importancia", _pasta_motor("shap"), chave_curso)
        if not arq:
            arq = _buscar("importancia_variaveis", _pasta_motor("preditivos"), chave_curso)
        if arq:
            dfp = _ler(arq)
            cols_n = dfp.select_dtypes(include=[np.number]).columns.tolist()
            cols_s = dfp.select_dtypes(include=["object"]).columns.tolist()
            if cols_n and cols_s:
                dfp_graf = dfp.head(10).copy()
                if dfp_graf[cols_s[0]].dtype == object:
                    dfp_graf[cols_s[0]] = dfp_graf[cols_s[0]].astype(str).str.wrap(50)
                st.plotly_chart(
                    px.bar(dfp_graf, x=cols_n[0], y=cols_s[0], orientation="h",
                           color=cols_n[0], color_continuous_scale="Greens",
                           title=f"Top 10 Variaveis Mais Importantes -- {nome_curso}"),
                    use_container_width=True)
                st.info("**Interpretacao:** Variaveis com maior barra sao os fatores mais determinantes para o desempenho. "
                        "Variaveis socioeconomicas frequentemente superam variaveis academicas.")
            else:
                st.dataframe(dfp, use_container_width=True)
            arq_m = _buscar("metricas", _pasta_motor("shap"), chave_curso)
            if not arq_m:
                arq_m = _buscar("metricas_modelos", _pasta_motor("preditivos"), chave_curso)
            if arq_m:
                st.subheader("Metricas do Modelo")
                st.dataframe(_ler(arq_m), use_container_width=True)
                st.caption("Acuracia, F1-Score e AUC-ROC indicam a qualidade da predicao. Valores acima de 0.7 sao considerados bons.")
        else:
            st.warning("Nenhum resultado preditivo encontrado. Execute o Motor Preditivo.")
            if sel_tipo == "enade":
                st.info("Os arquivos de importancia devem estar na pasta modelos/shap/ ou modelos/preditivos/. "
                        "Execute o algoritmo preditivo para o curso selecionado.")
            else:
                st.info("Resultados preditivos ainda nao disponiveis para este tipo de exame. "
                        "O motor preditivo foi executado apenas para ENADE 2023.")
    else:
        st.info("Selecione um curso no painel lateral.")


# --- TAB 2: VALIDACAO + CLUSTERING ---
elif aba == ABAS[2]:
    st.header("Validacao + Clustering")
    st.markdown("""
    **Metodologia:** O algoritmo **K-Means** agrupa alunos por similaridade de respostas nas 38 questoes objetivas.
    A validacao utiliza as metricas de **Silhueta** (coesao interna), **Calinski-Harabasz** (separacao entre clusters)
    e **Davies-Bouldin** (compacidade). O numero otimo de clusters e determinado pelo metodo do cotovelo e pela
    maximizacao da silhueta.
    """)
    if chave_curso:
        arq = _buscar("metricas", _pasta_motor("clustering"), chave_curso)
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
            som = _pasta_motor("psicometria") / f"som_{chave_curso}.png"
            if som.exists():
                st.subheader("SOM - Self-Organizing Map")
                st.image(str(som), use_container_width=True)
                st.caption("O SOM projeta o espaco multidimensional em uma grelha 2D, preservando topologia. Areas de mesma cor indicam perfis cognitivos semelhantes.")
            val_plot = _pasta_motor("clustering") / f"graficos_validacao_{chave_curso}.png"
            if not val_plot.exists():
                for p in PASTA_MOD.rglob("graficos_validacao_*.png"):
                    if chave_curso in p.name:
                        val_plot = p
                        break
            if val_plot.exists():
                st.subheader("Validacao dos Clusters (K-Means)")
                st.image(str(val_plot), use_container_width=True)
                st.caption("Grafico de validacao do agrupamento: silhueta por cluster e distribuicao dos pontos nos eixos principais.")
        else:
            st.warning("Execute o Motor de Clustering.")
            st.info("Os resultados devem estar na pasta modelos/clustering/metricas_*.csv.")
    else:
        st.info("Selecione um curso no painel lateral.")


# --- TAB 3: PLANO DE ACAO POR PERFIL ---
elif aba == ABAS[3]:
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
            cores_perfis = {"Genero": "#8b5cf6", "Idade": "#f59e0b", "Desempenho": "#3b82f6"}
            if "TP_SEXO" in df_curso.columns:
                sm2 = {"M": "Masculino", "F": "Feminino", "m": "Masculino", "f": "Feminino",
                       "1": "Masculino", "2": "Feminino", 1: "Masculino", 2: "Feminino"}
                df_curso_gen = df_curso.copy()
                df_curso_gen["Genero"] = df_curso_gen["TP_SEXO"].map(sm2)
                for genero in ["Masculino", "Feminino"]:
                    sub = df_curso_gen[df_curso_gen["Genero"] == genero]
                    if not sub.empty:
                        cor = "#3b82f6" if genero == "Masculino" else "#ec4899"
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
                            cor_grupo = "#ef4444" if "Critico" in nome_grupo_d else "#f59e0b" if "Insuficiente" in nome_grupo_d else "#3b82f6" if "Adequado" in nome_grupo_d else "#22c55e"
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
            df_filtrado = _obter_filtro_analise(df_a)
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



# --- TAB 4: LCA - CLASSES LATENTES ---
elif aba == ABAS[4]:
    st.header("Analise de Classes Latentes (LCA)")
    st.markdown("""
    Identificacao de perfis de aprendizagem via **Latent Class Analysis** -- abordagem estatistica robusta para dados
    categoricos binarios. A LCA determina quantos subgrupos (classes latentes) existem entre os alunos, baseando-se
    no padrao de acertos e erros nas questoes. O numero otimo de classes (k) e selecionado pelo **BIC**
    e pela **entropia normalizada** (quanto mais proxima de 1, melhor a separacao).
    """)
    csv_geral = _pasta_motor("lca") / "01_relatorio_geral_por_ies.csv"
    csv_cls = _pasta_motor("lca") / "02_caracterizacao_das_classes.csv"
    csv_crit = _pasta_motor("lca") / "03_criterios_de_selecao_k.csv"
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
                            prob_cols = sorted([c for c in sub.columns if c.startswith("PROB_Q")],
                                                key=lambda c: int(c.replace("PROB_Q", "")))
                            gap_cols = sorted([c for c in sub.columns if c.startswith("GAP_Q")],
                                              key=lambda c: int(c.replace("GAP_Q", "")))
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

                # ------------------------------------------------------------------
                # FASE 5: REANALISE DE HORIZONTALIDADE E ROBUSTEZ (BRANCOS)
                # ------------------------------------------------------------------
                st.markdown("---")
                st.subheader("Reanalise de Horizontalidade e Robustez (Brancos)")
                df_reanalise_resumo = carregar_reanalise_resumo(EDICAO_MOTORES)
                df_reanalise_ies = carregar_reanalise_por_ies(EDICAO_MOTORES)
                df_robustez_item = carregar_robustez_item(EDICAO_MOTORES)
                df_robustez_oc = carregar_robustez_oc(EDICAO_MOTORES)
                tab_reanalise, tab_robustez_item_t, tab_robustez_oc_t = st.tabs(
                    ["Resumo Horizontalidade", "Robustez por Item", "Robustez por OC"])
                with tab_reanalise:
                    if df_reanalise_resumo is not None:
                        st.dataframe(df_reanalise_resumo, use_container_width=True)
                    else:
                        st.info("Arquivo reanalise_resumo.csv nao encontrado em modelos/lca/.")
                    if df_reanalise_ies is not None:
                        st.markdown("**Detalhamento por IES:**")
                        df_reanalise_filtrado = df_reanalise_ies[
                            df_reanalise_ies["ies"].astype(str) == str(il)]
                        if not df_reanalise_filtrado.empty:
                            st.dataframe(df_reanalise_filtrado, use_container_width=True)
                        else:
                            st.warning("Sem dados de reanalise para esta IES especifica.")
                with tab_robustez_item_t:
                    if df_robustez_item is not None:
                        st.dataframe(df_robustez_item, use_container_width=True)
                    else:
                        st.info("Arquivo robustez_brancos_por_item.csv nao encontrado em modelos/lca/.")
                with tab_robustez_oc_t:
                    if df_robustez_oc is not None:
                        st.dataframe(df_robustez_oc, use_container_width=True)
                    else:
                        st.info("Arquivo robustez_brancos_por_oc.csv nao encontrado em modelos/lca/.")

                pasta_lca_figuras = _pasta_motor("lca") / "figuras"
                if not pasta_lca_figuras.exists():
                    pasta_lca_figuras = RAIZ_PROJETO / "figuras"
                caminho_figura5 = pasta_lca_figuras / "figura5_corrigida.jpg"
                if caminho_figura5.exists():
                    st.markdown("#### Impacto Grafico da Reanalise")
                    st.image(str(caminho_figura5), use_container_width=True,
                             caption="Figura 5 - Correcao de Horizontalidade")

                st.markdown("---")
                st.subheader("Figuras da Analise (Artigo SBIE)")
                st.caption("Figuras referentes aos cursos de **Medicina**, **Engenharia Civil** e **Enfermagem** -- artigos publicados no SBIE.")
                cursos_artigo = ["medicina", "engenharia_civil", "enfermagem"]
                figuras_exibidas = 0
                if pasta_lca_figuras.exists():
                    for curso_artigo in cursos_artigo:
                        fig_paths = list(pasta_lca_figuras.glob(f"*{curso_artigo}*.png"))
                        for fp in fig_paths:
                            st.image(str(fp), use_container_width=True, caption=fp.stem.replace("_", " ").title())
                            figuras_exibidas += 1
                    if figuras_exibidas == 0:
                        imagens = list(pasta_lca_figuras.glob("fig*.png"))
                        if imagens:
                            st.info("Nenhuma figura especifica encontrada. Exibindo figuras gerais:")
                            cols_img = st.columns(3)
                            for i, img_p in enumerate(imagens[:6]):
                                with cols_img[i % 3]:
                                    st.image(str(img_p), use_container_width=True, caption=img_p.stem)
                        else:
                            st.info("Figuras nao encontradas em: " + str(pasta_lca_figuras))
        else:
            st.info("Nenhum curso encontrado no LCA.")
    else:
        st.warning("Execute o pipeline LCA primeiro.")
        st.info("Os resultados devem estar em modelos/lca/ com arquivos 01_relatorio_geral_por_ies.csv, 02_caracterizacao_das_classes.csv e 03_criterios_de_selecao_k.csv.")


# --- TAB 5: OPENCODE + IA EXPLICATIVA ---
elif aba == ABAS[5]:
    st.header("OpenCode + IA Explicativa")
    st.markdown("""
    Selecione um arquivo CSV de resultados para gerar uma **explicacao em linguagem natural**,
    acessivel para nao-especialistas. O dashboard chama o **OpenCode.ai** via API HTTP
    para analisar os dados e produzir um texto explicativo com interpretacoes e recomendacoes.

    **Cobertura de artefatos (auditável, conforme disponibilidade):** ENADE (edições 2004–2023),
    ENAMED e ENADE Licenciaturas — microdados processados, resultados por motor/edição,
    análises por IES/questão/OC e relatórios `.md`/explicações correlatas.
    """)
    server_online = servidor_opencode_ativo()
    status_color = "🟢" if server_online else "🔴"
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

    # --- escopo por exame/edição (complementa EDICAO_MOTORES da sidebar) ---
    def _inferir_escopo_artefato(p):
        s = str(p).lower()
        ano_m = re.search(r'(?:enade[_\-]?|relatorio_final_enade[_\-]?)(20\d{2})', s)
        if 'enamed' in s:
            return f"ENAMED {ano_m.group(1)}" if ano_m else "ENAMED"
        if 'licenciatura' in s:
            return f"Licenciaturas {ano_m.group(1)}" if ano_m else "Licenciaturas"
        if ano_m:
            return f"ENADE {ano_m.group(1)}"
        ed_m = re.search(r'\\enade_(20\d{2})\\|/enade_(20\d{2})/', s)
        if ed_m:
            a = ed_m.group(1) or ed_m.group(2)
            return f"ENADE {a}"
        return "Geral"

    def _escopo_compativel(escopo_item, escopo_sel):
        if not escopo_sel or escopo_sel.startswith("(Todos"):
            return True
        ei = (escopo_item or "").lower()
        es = escopo_sel.lower()
        if es.startswith("enade (2004-2023)") or es == "enade (todas edições)":
            return "enade" in ei and "enamed" not in ei and "licenciatura" not in ei
        if es.startswith("enamed"):
            return "enamed" in ei
        if es.startswith("licenciatura"):
            return "licenciatura" in ei
        # edição específica
        ano_m = re.search(r'(20\d{2})', escopo_sel)
        if ano_m:
            return ano_m.group(1) in ei
        return True

    eds_disp = []
    try:
        eds_disp = listar_edicoes_disponiveis()
    except Exception:
        eds_disp = []
    escopo_opts = ["(Todos os exames e edições — ENADE 2004–2023, ENAMED, Licenciaturas)",
                   "ENADE (2004–2023 / todas edições)", "ENAMED", "Licenciaturas"]
    escopo_opts += [e for e in eds_disp if e]
    escopo_sel = st.selectbox(
        "Escopo de exame/edição (descoberta de artefatos):", escopo_opts, key="oc_escopo_exame",
        help="Complementa a edição de motores da sidebar. Use 'Todos' para buscar artefatos de ENADE 2004–2023, ENAMED e Licenciaturas."
    )

    filtros_ativos = []
    if 'EDICAO_MOTORES' in globals() and EDICAO_MOTORES:
        filtros_ativos.append(f"edicao_motores={EDICAO_MOTORES}")
    if escopo_sel and not escopo_sel.startswith("(Todos"):
        filtros_ativos.append(f"escopo={escopo_sel}")
    if 'nome_curso' in locals() and nome_curso:
        filtros_ativos.append(f"curso={nome_curso}")
    if 'ies_sel' in locals() and ies_sel:
        filtros_ativos.append(f"IES={ies_sel}")
    if filtros_ativos:
        st.caption("Filtros ativos: " + " | ".join(filtros_ativos) + ". Quando o CSV tiver colunas compatíveis (CO_IES/NO_IES/CO_GRUPO/curso), a prévia e o prompt são filtrados.")

    def _filtrar_csv_por_contexto(df_in):
        d = df_in.copy()
        try:
            if ies_sel:
                cols_n = {str(c).strip().upper(): c for c in d.columns}
                c_ies = next((cols_n[k] for k in ["CO_IES", "COD_IES", "IES", "CODIGO_IES", "CO_IES_CURSO"] if k in cols_n), None)
                c_noies = next((cols_n[k] for k in ["NO_IES", "NOME_IES"] if k in cols_n), None)
                if c_ies is not None:
                    m = d[c_ies].astype(str).str.strip().str.replace(r"\.0$", "", regex=True) == str(ies_sel).strip()
                    if m.any():
                        d = d[m]
                elif c_noies is not None:
                    m = d[c_noies].astype(str).str.contains(str(ies_sel), case=False, na=False)
                    if m.any():
                        d = d[m]
            if nome_curso:
                cols_n = {str(c).strip().upper(): c for c in d.columns}
                c_grp = next((cols_n[k] for k in ["CO_GRUPO", "CODIGO_CURSO", "COD_CURSO"] if k in cols_n), None)
                c_nocurso = next((cols_n[k] for k in ["NO_CURSO", "NOME_CURSO", "CURSO"] if k in cols_n), None)
                if c_grp is not None and 'sel_grupo' in locals() and sel_grupo is not None:
                    try:
                        m = pd.to_numeric(d[c_grp], errors="coerce") == int(sel_grupo)
                        if m.any():
                            d = d[m]
                    except Exception:
                        pass
                elif c_nocurso is not None:
                    m = d[c_nocurso].astype(str).str.contains(str(nome_curso), case=False, na=False)
                    if m.any():
                        d = d[m]
        except Exception:
            return df_in
        return d

    @st.cache_data(show_spinner=False, ttl=120)
    def _descobrir_csvs_opencode(edicao_motores, escopo):
        """Descobre CSVs em todas as fontes relevantes (ENADE 2004-2023, ENAMED, Licenciaturas)."""
        seen, out = set(), []
        modulos = ["clustering", "shap", "cdm", "psicometria", "lca", "preditivos", "irt", "analises_tese", "drift"]
        bases = []
        # 1) motores por edição/escopo
        eds = []
        if edicao_motores:
            eds = [edicao_motores]
        elif escopo and not str(escopo).startswith("(Todos") and not str(escopo).startswith("ENADE (2004"):
            if re.match(r'enade_\d{4}|enamed|licenciatura', str(escopo), re.I):
                eds = [escopo]
        if not eds:
            try:
                eds = listar_edicoes_disponiveis()
            except Exception:
                eds = []
        for ed in eds:
            for m in modulos:
                try:
                    bases.append(_pasta_edicao_leitura(m, ed))
                except Exception:
                    pass
        for m in modulos:
            bases.append(PASTA_MOD / m)
        # 2) dados processados / exames
        bases += [PASTA_EDA, PASTA_MOD, PASTA_DADOS_PROCESSADOS,
                  PASTA_DADOS_PROCESSADOS / "enade", PASTA_DADOS_PROCESSADOS / "enamed",
                  PASTA_DADOS_PROCESSADOS / "enadeLicenciaturas", PASTA_DADOS_PROCESSADOS / "por_ano",
                  PASTA_RESULTADOS_ENADE, PASTA_RESULTADOS_LICENCIATURAS, PASTA_RESULTADOS_ENAMED]
        # 3) séries temporais e legados
        st_roots = [PASTA_SERIE_MICRODADOS / "resultados"]
        try:
            st_roots.append(RAIZ_PROJETO.parent / "seriesTemporais_microdados" / "resultados")
        except Exception:
            pass
        for sr in st_roots:
            bases += [sr, sr / "enade", sr / "enamed", sr / "enadeLicenciaturas"]
        bases.append(RAIZ_PROJETO.parent / "modeloprojetoENADE2023" / "arquivosgerados")
        bases.append(RAIZ_PROJETO / "relatorios")
        for base in bases:
            try:
                if not base or not base.exists():
                    continue
                # modelos/ e dados/processados podem ter subpastas por edição; limitar profundidade implícita pelo rglob é ok, mas evitar pastas enormes sem csv
                it = base.rglob("*.csv") if base in (PASTA_MOD, PASTA_DADOS_PROCESSADOS, RAIZ_PROJETO / "relatorios") or "resultados" in str(base).lower() or "arquivosgerados" in str(base).lower() else base.glob("*.csv")
                # para bases de exames/motores, rglob captura edições
                if base not in (PASTA_MOD, PASTA_DADOS_PROCESSADOS) and ("modelos" in str(base).lower() or "enade" in str(base).lower() or "enamed" in str(base).lower() or "licenciatura" in str(base).lower() or "resultados" in str(base).lower() or "arquivosgerados" in str(base).lower()):
                    it = base.rglob("*.csv")
                for p in it:
                    try:
                        rp = p.resolve()
                        if rp in seen:
                            continue
                        if p.stat().st_size > 50 * 1024 * 1024:
                            continue
                        seen.add(rp)
                        out.append(p)
                    except Exception:
                        pass
            except Exception:
                pass
        return out

    st.subheader("1. Selecione o CSV para analise")
    ed_m = EDICAO_MOTORES if 'EDICAO_MOTORES' in globals() else ""
    with st.spinner("Buscando artefatos CSV (ENADE 2004–2023, ENAMED, Licenciaturas)..."):
        csvs_validos = _descobrir_csvs_opencode(ed_m, escopo_sel)
    # filtrar por escopo
    csvs_validos = [p for p in csvs_validos if _escopo_compativel(_inferir_escopo_artefato(p), escopo_sel)]
    st.caption(f"CSVs descobertos no escopo: **{len(csvs_validos)}** (limite 50 MB/arquivo; fontes: modelos por edição, dados/processados, seriesTemporais_microdados/resultados, legados/arquivosgerados).")

    if not csvs_validos:
        st.error("Nenhum arquivo CSV encontrado para o escopo selecionado.")
        st.info("Verifique se existem artefatos em `modelos/*/<edição>`, `dados/processados/enade|enamed|enadeLicenciaturas`, `seriesTemporais_microdados/resultados/*` ou pastas legadas. Ajuste o escopo ou a edição de motores na sidebar.")
    else:
        csvs_filtrados = csvs_validos
        # prioridade por edição de motores / escopo específico no nome/caminho
        if ed_m:
            pref_ed = [p for p in csvs_filtrados if ed_m in str(p).lower()]
            if pref_ed:
                csvs_filtrados = pref_ed + [p for p in csvs_filtrados if p not in pref_ed]
        if chave_curso:
            curso_lower = chave_curso.lower()
            pref = [p for p in csvs_filtrados if curso_lower in p.stem.lower() or (nome_curso and _norm(nome_curso) in _norm(p.stem))]
            if pref:
                csvs_filtrados = pref
        if ies_sel:
            ies_s = str(ies_sel).strip()
            pref_ies = [p for p in csvs_filtrados if ies_s in p.stem or ies_s in str(p.parent)]
            if pref_ies:
                csvs_filtrados = pref_ies + [p for p in csvs_filtrados if p not in pref_ies]
        # labels auditáveis: [escopo] caminho relativo quando possível
        def _label_csv(p):
            esc = _inferir_escopo_artefato(p)
            try:
                rel = str(p.relative_to(RAIZ_PROJETO.parent))
            except Exception:
                try:
                    rel = str(p.relative_to(RAIZ_PROJETO))
                except Exception:
                    rel = p.name
            return f"[{esc}] {rel}"
        pares = sorted({(_label_csv(p), p.resolve()): p for p in csvs_filtrados}.values(), key=lambda x: (0 if ed_m and ed_m in str(x).lower() else 1, str(x).lower()))
        csv_labels = {_label_csv(p): p for p in pares}
        labels_ordenados = list(csv_labels.keys())
        csv_selecionado = st.selectbox("Arquivo CSV:", labels_ordenados, key="csv_selector")
        caminho_csv = csv_labels[csv_selecionado]
        st.caption(f"Origem inferida: **{_inferir_escopo_artefato(caminho_csv)}** | `{caminho_csv}`")

        def _ler_csv_robusto(path, nrows=None):
            """Leitura tolerante a CSVs com aspas/quebras malformadas, encoding/separador variados."""
            import csv as _csv
            erros = []
            tentativas = [
                dict(sep=SEPARADOR, encoding="utf-8-sig"),
                dict(sep=SEPARADOR, encoding="utf-8"),
                dict(sep=SEPARADOR, encoding="latin-1"),
                dict(sep=None, encoding="utf-8-sig"),
                dict(sep=None, encoding="latin-1"),
                dict(sep=",", encoding="utf-8-sig"),
                dict(sep=",", encoding="latin-1"),
            ]
            for kw in tentativas:
                try:
                    df_t = pd.read_csv(
                        path, nrows=nrows, engine="python",
                        on_bad_lines="skip", quoting=_csv.QUOTE_MINIMAL,
                        **kw,
                    )
                    if df_t is not None and len(df_t.columns) > 0:
                        modo = f"sep={kw['sep']!r}, encoding={kw['encoding']}, engine=python, on_bad_lines=skip"
                        return df_t, modo
                except Exception as ex:
                    erros.append(f"{kw}: {ex}")
            # última tentativa C engine padrão com skip
            try:
                df_t = pd.read_csv(path, sep=SEPARADOR, encoding="utf-8-sig", nrows=nrows, on_bad_lines="skip", low_memory=False)
                return df_t, "engine=default, on_bad_lines=skip"
            except Exception as ex:
                erros.append(f"default: {ex}")
            raise ValueError("Falha ao ler CSV após tentativas tolerantes. " + " | ".join(erros[-3:]))

        st.subheader("2. Previa dos Dados")
        try:
            df_csv_full_preview, modo_leitura = _ler_csv_robusto(caminho_csv, nrows=5000)
            df_csv_preview = _filtrar_csv_por_contexto(df_csv_full_preview)
            st.dataframe(df_csv_preview.head(10), use_container_width=True)
            n_linhas = len(df_csv_full_preview)
            n_cols = len(df_csv_full_preview.columns)
            filtro_msg = f" | apos filtros: {len(df_csv_preview)} linhas" if len(df_csv_preview) != n_linhas else ""
            st.caption(f"Mostrando 10 de ~{n_linhas} linhas (amostra lida){filtro_msg} | {n_cols} colunas | {caminho_csv.name} | leitura: {modo_leitura}")
            st.session_state["_oc_modo_leitura_csv"] = modo_leitura
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
        foco = st.text_area("Foco adicional (opcional):", placeholder="Ex: 'Destaque deficiências por OC/competência' ou 'Compare padrões do ENAMED/Licenciaturas com cautela'", key="foco_ia")

        st.subheader("4. Gerar Explicacao")
        gerar = st.button("Gerar Explicacao com OpenCode", type="primary", use_container_width=True, disabled=not server_online)

        if gerar:
            try:
                df_full_raw, modo_leitura_full = _ler_csv_robusto(caminho_csv, nrows=None)
            except Exception:
                df_full_raw = pd.read_csv(caminho_csv, sep=SEPARADOR, encoding="utf-8-sig", on_bad_lines="skip", low_memory=False)
                modo_leitura_full = "default"
            df_full = _filtrar_csv_por_contexto(df_full_raw) if '_filtrar_csv_por_contexto' in locals() else df_full_raw
            ctx_filtros = []
            if 'ies_sel' in locals() and ies_sel:
                ctx_filtros.append(f"IES={ies_sel}")
            if 'nome_curso' in locals() and nome_curso:
                ctx_filtros.append(f"curso={nome_curso}")
            if ed_m:
                ctx_filtros.append(f"edicao_motores={ed_m}")
            if escopo_sel and not escopo_sel.startswith("(Todos"):
                ctx_filtros.append(f"escopo={escopo_sel}")
            if len(df_full) != len(df_full_raw):
                st.info(f"Análise filtrada por contexto: {len(df_full)} de {len(df_full_raw)} linhas ({', '.join(ctx_filtros) or 'filtros'}).")
            elif ctx_filtros:
                st.caption(f"Filtros ativos ({', '.join(ctx_filtros)}): CSV sem colunas compatíveis para recorte; análise usa o arquivo completo.")
            resumo = {"arquivo": caminho_csv.name, "linhas_arquivo": len(df_full_raw), "linhas_analisadas": len(df_full), "colunas": list(df_full.columns),
                      "colunas_numericas": [c for c in df_full.columns if pd.api.types.is_numeric_dtype(df_full[c])],
                      "resumo_estatistico": {}}
            for c in resumo["colunas_numericas"][:10]:
                s = pd.to_numeric(df_full[c], errors="coerce")
                if s.notna().any():
                    resumo["resumo_estatistico"][c] = {"media": round(float(s.mean()), 2), "min": round(float(s.min()), 2), "max": round(float(s.max()), 2)}
            amostra = df_full.head(5).to_string()
            exame_inf = _inferir_escopo_artefato(caminho_csv)
            contexto_exame = f"{exame_inf}. Cobertura PRISM-EDU: ENADE (edições 2004–2023), ENAMED e ENADE Licenciaturas, conforme artefatos disponíveis."
            prompt = f"""Analise o seguinte conjunto de dados educacionais ({exame_inf}) e gere uma explicacao em linguagem natural.

ARQUIVO: {caminho_csv.name}
EXAME/EDIÇÃO (inferido do caminho/nome, auditável): {exame_inf}
CONTEXTO DO PROJETO: {contexto_exame}
TOM: {tom}
FILTROS DE CONTEXTO: {', '.join(ctx_filtros) if ctx_filtros else 'nenhum'}
{'FOCO ADICIONAL: ' + foco if foco else ''}

RESUMO DOS DADOS:
- {resumo['linhas_analisadas']} linhas analisadas (de {resumo['linhas_arquivo']} no arquivo), {len(resumo['colunas'])} colunas
- Colunas: {', '.join(resumo['colunas'][:15])}{'...' if len(resumo['colunas']) > 15 else ''}
- Colunas numericas: {', '.join(resumo['colunas_numericas'][:8])}

ESTATISTICAS BASICAS:
{json.dumps(resumo['resumo_estatistico'], indent=2, ensure_ascii=False)}

AMOSTRA (primeiras 5 linhas, apos filtros quando aplicaveis):
{amostra}

Com base nestes dados, produza uma explicacao que:
1. Contextualize o que sao estes dados (exame/edição, unidade de análise, limitações de comparabilidade quando aplicável)
2. Destaque os principais achados e padroes
3. Aponte anomalias ou lacunas (com cautela)
4. Conclua com recomendacoes praticas
5. Seja acessivel para publico nao-especialista e evite generalizações indevidas entre exames/edições
"""
            prompt_preview = prompt[:75] + "..." if len(prompt) > 75 else prompt
            st.info(f"Modelo: **{MODELOS_OPENCODE[modelo_id]}** | Exame/edição: **{exame_inf}** | Prompt: `{prompt_preview}`")
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
                        st.markdown(f"### Explicacao Gerada -- {MODELOS_OPENCODE[modelo_id]} ({exame_inf})")
                        st.markdown("---")
                        st.markdown(resultado["response"])
                        st.download_button(label="Download da Explicacao (.md)", data=resultado["response"].encode("utf-8"), file_name=f"explicacao_opencode_{exame_inf.replace(' ','_')}_{caminho_csv.stem}.md", mime="text/markdown", use_container_width=True)
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
                        st.markdown(f"**Arquivo:** `{caminho_csv.name}` | **Exame/edição:** {exame_inf}")
                        st.markdown(f"**Dimensoes:** {resumo.get('linhas_analisadas', resumo.get('linhas','?'))} linhas analisadas x {len(resumo['colunas'])} colunas")
                        st.markdown("---")
                        st.markdown("**Colunas numericas analisadas:**")
                        for col, stats in resumo["resumo_estatistico"].items():
                            st.markdown(f"- **{col}**: media={stats['media']}, min={stats['min']}, max={stats['max']}")
            except Exception as e:
                timer.stop()
                timer_container.empty()
                st.error(f"Erro ao gerar explicacao: {e}")

    st.markdown("---")
    st.subheader("5. Relatorios .md / Explicacoes Geradas (todas edições e exames)")
    pastas_md = [
        RAIZ_PROJETO / "relatorios",
        RAIZ_PROJETO / "EXPLICACOES_OPENCODE",
        PASTA_DADOS_PROCESSADOS,
        PASTA_DADOS_PROCESSADOS / "EXPLICACOES_OPENCODE",
        PASTA_DADOS_PROCESSADOS / "enade",
        PASTA_DADOS_PROCESSADOS / "enamed",
        PASTA_DADOS_PROCESSADOS / "enadeLicenciaturas",
        PASTA_MOD,
        RAIZ_PROJETO.parent / "modeloprojetoENADE2023" / "arquivosgerados",
        RAIZ_PROJETO.parent / "modeloprojetoENADE2023" / "arquivosgerados" / "EXPLICACOES_OPENCODE",
        PASTA_SERIE_MICRODADOS / "resultados",
    ]
    try:
        pastas_md.append(RAIZ_PROJETO.parent / "seriesTemporais_microdados" / "resultados")
    except Exception:
        pass
    seen_md, mds = set(), []
    for pasta_md in pastas_md:
        try:
            if pasta_md.exists():
                for m in pasta_md.rglob("*.md"):
                    try:
                        rp = m.resolve()
                        if rp not in seen_md and m.stat().st_size <= 5 * 1024 * 1024:
                            # priorizar explicações/relatórios relevantes, mas incluir demais .md encontrados nessas raízes
                            seen_md.add(rp); mds.append(m)
                    except Exception:
                        pass
        except Exception:
            pass
    mds = [m for m in mds if _escopo_compativel(_inferir_escopo_artefato(m), escopo_sel)]
    # priorizar arquivos que parecem explicações/opencode
    def _prio_md(m):
        s = m.name.lower() + " " + str(m.parent).lower()
        pr = 0
        if "opencode" in s or "explic" in s or "relatorio" in s: pr -= 2
        if ed_m and ed_m in s: pr -= 1
        return (pr, str(m).lower())
    mds = sorted(mds, key=_prio_md)
    if chave_curso:
        mds_curso = [m for m in mds if chave_curso in m.stem or _norm(chave_curso) in _norm(m.stem)]
        if mds_curso:
            mds = mds_curso
    st.caption(f"Relatórios `.md` no escopo: **{len(mds)}** (raízes: relatorios, EXPLICACOES_OPENCODE, dados/processados, modelos, seriesTemporais_microdados/resultados, legados ENADE 2023).")
    if mds:
        nomes_md = []
        for m in mds:
            esc = _inferir_escopo_artefato(m)
            try:
                rel = str(m.relative_to(RAIZ_PROJETO.parent))
            except Exception:
                try:
                    rel = str(m.relative_to(RAIZ_PROJETO))
                except Exception:
                    rel = m.name
            nomes_md.append(f"[{esc}] {rel}")
        md_selecionado = st.selectbox("Selecione um relatorio:", nomes_md, key="md_selector")
        caminho_md = mds[nomes_md.index(md_selecionado)]
        st.caption(f"Origem inferida: **{_inferir_escopo_artefato(caminho_md)}** | `{caminho_md}`")
        try:
            conteudo_md = caminho_md.read_text(encoding="utf-8")
            st.markdown("---")
            st.markdown(conteudo_md)
        except Exception as e:
            st.error(f"Erro ao ler o arquivo .md: {e}")
    else:
        st.info("Nenhum relatorio .md encontrado no escopo selecionado. Gere uma explicação (seção 4), ajuste o escopo/exame, ou verifique pastas `relatorios/`, `EXPLICACOES_OPENCODE/`, `modelos/*/<edição>/`, `dados/processados/*` e `seriesTemporais_microdados/resultados/*`.")



# --- TAB 6: MATRIZ-Q ---
elif aba == ABAS[6]:
    st.header("Diagnostico Cognitivo Avancado (Matriz-Q)")
    st.markdown("""
    Esta secao utiliza **Modelos de Diagnostico Cognitivo (CDM)** para avaliar a probabilidade exata
    de dominio de cada aluno nas materias especificas do curso, prescidindo de notas genericas para
    fornecer orientacoes pedagogicas precisas. Apresenta a **Matriz-Q** (q_matrix.csv) e os parametros
    **DINA** (slip/guess) dos arquivos dina_*.csv na pasta modelos/cdm/.
    """)
    if df_curso is None or (hasattr(df_curso, 'empty') and df_curso.empty):
        st.warning("Selecione uma IES e Curso no filtro lateral.")
    else:
        _render_diagnostico_aluno(nome_curso, ies_sel)
        st.markdown("---")
        q_matrix_path = _pasta_motor("cdm") / "q_matrix.csv"
        if q_matrix_path.exists():
            st.subheader("Matriz-Q (Itens x Atributos)")
            df_q = pd.read_csv(q_matrix_path, sep=SEPARADOR, encoding=ENCODING, low_memory=False)
            st.dataframe(df_q, use_container_width=True)
            st.caption("A Matriz-Q mapeia quais questoes (linhas) medem quais atributos/competencias (colunas A1-A6). "
                       "Valores 1 indicam que a questao mede o atributo; 0 indica que nao mede.")
            if "Unnamed: 0" in df_q.columns:
                q_cols = [c for c in df_q.columns if c.startswith("A")]
                if q_cols:
                    df_q_counts = df_q[q_cols].sum().reset_index()
                    df_q_counts.columns = ["Atributo", "N_Itens"]
                    st.plotly_chart(px.bar(df_q_counts, x="Atributo", y="N_Itens", color="N_Itens",
                                           color_continuous_scale="Blues", title="Numero de Itens por Atributo (Matriz-Q)"),
                                   use_container_width=True)
                    st.caption("Distribuicao do numero de questoes que medem cada atributo/competencia.")
        else:
            st.info("Matriz-Q (q_matrix.csv) nao encontrada em modelos/cdm/.")

        st.markdown("---")
        st.subheader("Parametros DINA (Slip & Guess)")
        st.markdown("""
        O modelo **DINA (Deterministic Input, Noisy \"And\" Gate)** estima dois parametros por item:
        - **Slip (s):** probabilidade de um aluno que domina o atributo errar o item
        - **Guess (g):** probabilidade de um aluno que nao domina acertar por chute
        """)
        pasta_cdm_atual = _pasta_motor("cdm")
        dina_files = sorted(pasta_cdm_atual.glob("dina_*.csv")) if pasta_cdm_atual.exists() else []
        dina_files = [f for f in dina_files if "q_matrix" not in f.name]
        if dina_files:
            for dina_file in dina_files:
                st.markdown(f"**{dina_file.stem}**")
                df_dina = _ler(dina_file)
                ok = False
                if df_dina is not None and not df_dina.empty:
                    cols_norm = {str(c).strip().lower(): c for c in df_dina.columns}
                    c_q = cols_norm.get("questao") or cols_norm.get("item") or cols_norm.get("q")
                    c_slip = cols_norm.get("slip_s") or cols_norm.get("slip")
                    c_guess = cols_norm.get("guess_g") or cols_norm.get("guess")
                    if c_q and c_slip and c_guess:
                        fig_dina = go.Figure()
                        fig_dina.add_trace(go.Bar(x=df_dina[c_q], y=pd.to_numeric(df_dina[c_slip], errors="coerce"), name="Slip (s)", marker_color="#ef4444"))
                        fig_dina.add_trace(go.Bar(x=df_dina[c_q], y=pd.to_numeric(df_dina[c_guess], errors="coerce"), name="Guess (g)", marker_color="#3b82f6"))
                        fig_dina.update_layout(barmode="group", title=f"Parametros DINA -- {dina_file.stem}",
                                               xaxis_title="Questao", yaxis_title="Probabilidade", height=400)
                        st.plotly_chart(fig_dina, use_container_width=True)
                        st.caption("Slip alto indica questao onde alunos dominantes erram (confusa/difícil). "
                                   "Guess alto indica questao onde nao-dominantes acertam por sorte (baixa discriminacao).")
                        st.dataframe(df_dina, use_container_width=True)
                        ok = True
                if not ok:
                    cols_info = list(df_dina.columns)[:8] if df_dina is not None else []
                    st.warning(f"Arquivo {dina_file.name} nao contem colunas questao/slip/guess (ou slip_s/guess_g)." + (f" Colunas: {cols_info}" if cols_info else ""))
        else:
            st.info("Nenhum arquivo dina_*.csv encontrado em modelos/cdm/.")

        st.markdown("---")
        st.subheader("Comparacao LCA vs DINA")
        st.info("""
        A ponte LCA -> CDM restrito (DINA) compara item a item a classificacao latente da LCA com os perfis
        de dominio estimados pelo DINA. A concordancia e medida pela correlacao de Pearson entre as taxas de
        acerto da LCA e as probabilidades de dominio do DINA.
        """)

        st.markdown("---")
        st.subheader("Matriz de Saude Psicometrica (curso x indicador)")
        st.caption("Indicadores DINA agregados por curso a partir de modelos/cdm/00_resumo_dina.csv. "
                   "disc_medio = 1 - guess - slip (qualidade dos itens).")
        caminho_resumo = _pasta_motor("cdm") / "00_resumo_dina.csv"
        if caminho_resumo.exists():
            try:
                df_res = _ler(caminho_resumo)
            except Exception:
                df_res = None
            if df_res is not None and not df_res.empty:
                df_res = df_res.copy()
                df_res.columns = [str(c).strip() for c in df_res.columns]
                if "slip_medio" in df_res.columns and "guess_medio" in df_res.columns:
                    df_res["disc_medio"] = (1 - pd.to_numeric(df_res["slip_medio"], errors="coerce")
                                            - pd.to_numeric(df_res["guess_medio"], errors="coerce")).clip(0, 1)
                cols_saude = [c for c in ["disc_medio", "n_atributos", "n_itens", "n_alunos", "guess_medio", "slip_medio"]
                              if c in df_res.columns]
                if len(cols_saude) >= 2:
                    ordem_saude = "disc_medio" if "disc_medio" in df_res.columns else cols_saude[0]
                    df_res = df_res.sort_values(ordem_saude)
                    _z = pd.DataFrame(index=df_res.index, columns=cols_saude, dtype=float)
                    for _c in cols_saude:
                        _s = pd.to_numeric(df_res[_c], errors="coerce")
                        if _s.isna().all():
                            continue
                        _s = _s.fillna(_s.median())
                        _mn, _mx = _s.min(), _s.max()
                        _esc = (_s - _mn) / (_mx - _mn + 1e-9)
                        if _c in ["guess_medio", "slip_medio", "n_atributos"]:
                            _esc = 1 - _esc
                        _z[_c] = _esc
                    _txt = []
                    for _, _rr in df_res[cols_saude].iterrows():
                        _txt.append([f"{float(_rr.get(_c, float('nan'))):.2f}" for _c in cols_saude])
                    fig_heat_saude = go.Figure(go.Heatmap(
                        z=_z[cols_saude].values,
                        x=[c.replace("_", " ") for c in cols_saude],
                        y=[str(c) for c in df_res["curso"]],
                        text=np.array(_txt, dtype=object),
                        texttemplate="%{text}",
                        hovertemplate="%{y}<br>%{x}: %{text}<extra></extra>",
                        colorscale="RdYlGn", zmin=0, zmax=1))
                    fig_heat_saude.update_layout(margin=dict(t=20, b=10), height=max(300, 38 * len(df_res)))
                    st.plotly_chart(fig_heat_saude, use_container_width=True)
                    st.caption("Cor = posicao relativa do curso (verde = melhor). Para guess/slip, verde indica valores baixos "
                               "(itens com menos chute/erro). Valores exatos sao exibidos em cada celula.")
                    st.dataframe(df_res, use_container_width=True)
                else:
                    st.info("00_resumo_dina.csv nao possui colunas suficientes (esperadas: curso, guess_medio, slip_medio, ...).")
            else:
                st.info("00_resumo_dina.csv vazio ou nao legivel.")
        else:
            st.info("00_resumo_dina.csv nao encontrado em modelos/cdm/.")

        st.markdown("---")
        st.subheader("Mapeamento de Itens: OCs, Perfil e Competencias")
        st.markdown("""
        Cada questao do ENADE esta vinculada a **Objetos de Conhecimento (OCs)**, um **Perfil** profissional
        e **Competencias** especificas. Esta secao cruza a Matriz-Q e os parametros DINA com os mapeamentos
        oficiais para identificar quais OCs estao associadas aos itens com maior slip (itens dificeis)
        ou maior guess (itens com baixa discriminacao).
        """)
        df_a = _carregar_analise_ies(_extrair_ano_filtro(sel_tipo, sel_id))
        if df_a is not None and not df_a.empty:
            df_filtrado = _obter_filtro_analise(df_a)
            if not df_filtrado.empty:
                df_questoes_mat = _medias_por_questao_analise(df_filtrado)
                _render_relacao_perfil_oc(df_questoes_mat)
                if not df_questoes_mat.empty and "QUESTAO" in df_questoes_mat.columns:
                    colunas_oc_mat = [c for c in df_questoes_mat.columns if c.startswith("OC")]
                    if colunas_oc_mat:
                        st.subheader("OCs por Questao (Tabela de Referencia)")
                        cols_mostrar_mat = ["QUESTAO"]
                        for c in df_questoes_mat.columns:
                            if c.startswith("OC") or "PERFIL" in c.upper() or "COMPET" in c.upper():
                                cols_mostrar_mat.append(c)
                        cols_existentes_mat = [c for c in cols_mostrar_mat if c in df_questoes_mat.columns]
                        if cols_existentes_mat:
                            st.dataframe(df_questoes_mat[cols_existentes_mat], use_container_width=True, height=350)
                            st.caption("Mapeamento oficial de cada questao do ENADE para Objetos de Conhecimento, Perfil e Competencias.")
                        if "TAXA_DEFICIENCIA_%" in df_questoes_mat.columns:
                            oc_deficiencia = {}
                            for _, row in df_questoes_mat.iterrows():
                                taxa = row.get("TAXA_DEFICIENCIA_%", 0)
                                for col in colunas_oc_mat:
                                    val = str(row.get(col, "")).strip()
                                    if val and val != "nan":
                                        nome_oc = _oc_sem_prefixo(val)
                                        if nome_oc not in oc_deficiencia:
                                            oc_deficiencia[nome_oc] = {"soma_erro": 0, "count": 0}
                                        oc_deficiencia[nome_oc]["soma_erro"] += taxa
                                        oc_deficiencia[nome_oc]["count"] += 1
                            if oc_deficiencia:
                                dados_oc = []
                                for oc, info in oc_deficiencia.items():
                                    media_erro = info["soma_erro"] / info["count"] if info["count"] > 0 else 0
                                    dados_oc.append({"OC": oc, "Media_Erro_%": round(media_erro, 1), "N_Questoes": info["count"]})
                                df_oc_def = pd.DataFrame(dados_oc).sort_values("Media_Erro_%", ascending=False)
                                st.subheader("OCs por Taxa Media de Erro (DINA + Dados ENADE)")
                                fig_oc_def = px.bar(
                                    df_oc_def.head(15), x="OC", y="Media_Erro_%",
                                    color="Media_Erro_%", color_continuous_scale="RdYlGn_r",
                                    text="Media_Erro_%",
                                    title="Objetos de Conhecimento Ordenados por Taxa Media de Erro",
                                    hover_data=["N_Questoes"])
                                fig_oc_def.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
                                fig_oc_def.update_layout(height=450, xaxis_tickangle=-45)
                                st.plotly_chart(fig_oc_def, use_container_width=True)
                                st.caption("OCs com maior taxa media de erro indicam areas do conhecimento onde os alunos "
                                           "apresentam maior dificuldade. Combine com o parametros DINA (slip) para "
                                           "identificar se o problema e na compreensao do item ou na falta de dominio do atributo.")
                                st.dataframe(df_oc_def, use_container_width=True)

                                df_ies_all = df_filtrado.copy()

                                if ies_sel and _tem_colunas(df_a, "CO_IES"):
                                    st.markdown("---")
                                    st.subheader("Benchmark: IES vs Nacional por OC (Lollipop)")
                                    st.markdown("""
                                    Compara a taxa media de erro da **IES selecionada** com a **media nacional** para cada Objeto de Conhecimento.
                                    Barras vermelhas indicam OCs onde a IES performa pior que a media; verdes indicam desempenho superior.
                                    """)
                                    df_nac_all = df_a.copy()
                                    if _tem_colunas(df_nac_all, "CO_GRUPO") and sel_grupo:
                                        df_nac_all = df_nac_all[df_nac_all["CO_GRUPO"].astype(str).str.strip() == str(sel_grupo).strip()]
                                    df_ies_all = df_filtrado.copy()
                                    def _calc_oc_media(sub_df, colunas_oc_local):
                                        oc_map = {}
                                        for _, r in sub_df.iterrows():
                                            tx = r.get("TAXA_DEFICIENCIA_%", 0)
                                            for col in colunas_oc_local:
                                                val = str(r.get(col, "")).strip()
                                                if val and val != "nan":
                                                    nome = _oc_sem_prefixo(val)
                                                    if nome not in oc_map:
                                                        oc_map[nome] = []
                                                    oc_map[nome].append(tx)
                                        return {k: round(np.mean(v), 1) for k, v in oc_map.items() if v}
                                    oc_ies = _calc_oc_media(df_ies_all, colunas_oc_mat)
                                    oc_nac = _calc_oc_media(df_nac_all, colunas_oc_mat) if not df_nac_all.empty else {}
                                    if oc_ies and oc_nac:
                                        todos_ocs = sorted(set(list(oc_ies.keys()) + list(oc_nac.keys())))
                                        dados_lolli = []
                                        for oc in todos_ocs:
                                            dados_lolli.append({
                                                "OC": oc, "IES": oc_ies.get(oc, 0), "Nacional": oc_nac.get(oc, 0),
                                                "Delta": round(oc_ies.get(oc, 0) - oc_nac.get(oc, 0), 1)
                                            })
                                        df_lolli = pd.DataFrame(dados_lolli).sort_values("Delta", ascending=False)
                                        cores_lolli = ["#ef4444" if d > 0 else "#22c55e" for d in df_lolli["Delta"]]
                                        fig_lolli = go.Figure()
                                        fig_lolli.add_trace(go.Bar(y=df_lolli["OC"], x=df_lolli["Nacional"], name="Nacional", orientation="h", marker_color="#94a3b8", opacity=0.6))
                                        fig_lolli.add_trace(go.Bar(y=df_lolli["OC"], x=df_lolli["IES"], name="IES", orientation="h", marker_color=cores_lolli, opacity=0.85))
                                        fig_lolli.update_layout(barmode="group", title="Deficiencia por OC: IES vs Media Nacional",
                                                               xaxis_title="Taxa Media de Deficiencia (%)", yaxis=dict(autorange="reversed"), height=max(350, len(todos_ocs) * 28))
                                        st.plotly_chart(fig_lolli, use_container_width=True)
                                        n_piores = sum(1 for d in df_lolli["Delta"] if d > 0)
                                        n_melhores = sum(1 for d in df_lolli["Delta"] if d < 0)
                                        st.caption(f"OCs onde a IES esta acima da media nacional (vermelho): {n_piores}. "
                                                   f"OCs abaixo (verde): {n_melhores}. Priorize intervencoes nos OCs vermelhos.")
                                        st.dataframe(df_lolli, use_container_width=True)

                                st.markdown("---")
                                st.subheader("Distribuicao de Dominio de OCs por Aluno")
                                st.markdown("""
                                Conta quantos OCs cada aluno domina (taxa de erro < 50% nas questoes associadas).
                                Permite avaliar a saude institucional: quantos alunos possuem dominio amplo vs. fragil.
                                """)
                                oc_alfa = [c for c in colunas_oc_mat if c.startswith("OC")]
                                if oc_alfa and "TAXA_DEFICIENCIA_%" not in df_questoes_mat.columns:
                                    st.info("Coluna TAXA_DEFICIENCIA_% necessaria para esta analise.")
                                elif oc_alfa:
                                    df_aluno_dom = df_ies_all.copy() if not df_ies_all.empty else df_filtrado.copy()
                                    oc_count_aluno = []
                                    for _, r in df_aluno_dom.iterrows():
                                        n_dom = 0
                                        for col in oc_alfa:
                                            val = str(r.get(col, "")).strip()
                                            if val and val != "nan":
                                                tx_questao = r.get("TAXA_DEFICIENCIA_%", 50)
                                                if pd.notna(tx_questao) and tx_questao < 50:
                                                    n_dom += 1
                                        oc_count_aluno.append(n_dom)
                                    if oc_count_aluno:
                                        df_dom_hist = pd.DataFrame({"OCs_Dominados": oc_count_aluno})
                                        total_alunos_dom = len(df_dom_hist)
                                        media_dom = df_dom_hist["OCs_Dominados"].mean()
                                        pct_abaixo_50 = (df_dom_hist["OCs_Dominados"] <= len(oc_alfa) // 2).mean() * 100
                                        m_h1, m_h2, m_h3 = st.columns(3)
                                        m_h1.metric("Media de OCs Dominados", f"{media_dom:.1f} / {len(oc_alfa)}")
                                        m_h2.metric("Alunos com < 50% dos OCs", f"{pct_abaixo_50:.1f}%")
                                        m_h3.metric("Total de Alunos", f"{total_alunos_dom:,}")
                                        fig_hist_dom = px.histogram(df_dom_hist, x="OCs_Dominados", nbins=len(oc_alfa) + 1,
                                                                     color_discrete_sequence=["#3b82f6"],
                                                                     title="Distribuicao do Numero de OCs Dominados por Aluno")
                                        fig_hist_dom.update_layout(xaxis_title="N de OCs Dominados", yaxis_title="N de Alunos", height=380)
                                        fig_hist_dom.add_vline(x=media_dom, line_dash="dash", line_color="red",
                                                               annotation_text=f"Media: {media_dom:.1f}")
                                        st.plotly_chart(fig_hist_dom, use_container_width=True)
                                        if pct_abaixo_50 > 30:
                                            st.warning(f"**{pct_abaixo_50:.1f}% dos alunos dominam menos da metade dos OCs.** "
                                                       "Isso indica fragilidade institucional significativa que requer intervencao curricular.")
                                        else:
                                            st.info(f"Distribuicao saudavel: {100 - pct_abaixo_50:.1f}% dos alunos dominam mais da metade dos OCs.")
                                        st.caption("Alunos a esquerda da linha vermelha (media) possuem dominio fragil. "
                                                   "Deslocar a distribuicao para a direita e o objetivo pedagogico.")
                    else:
                        st.info("Dados de OCs nao disponiveis para este curso.")
                else:
                    st.info("Nenhuma questao encontrada na analise para este curso.")
            else:
                st.info("Nenhum dado de analise por questao disponivel para o curso/IES selecionado.")
        else:
            st.info("Arquivo analise_por_ies_curso_enade.csv nao encontrado. "
                    "Disponivel apenas para ENADE 2023.")

        _render_ponte_lca_cdm(nome_curso, ies_sel)


# --- TAB 7: ML AVANCADO ---
elif aba == ABAS[7]:
    st.header("Machine Learning Avancado")
    st.markdown("""
    Esta secao apresenta os resultados obtidos atraves de um pipeline de modelagem preditiva avancada:
    1. **Filtro de Anomalias (Isolation Forest):** Remocao de padroes de chute ou abandono.
    2. **Reducao de Dimensionalidade (PCA):** Concentracao das 38 questoes em componentes principais.
    3. **Tratamento de Desbalanceamento (SMOTE):** Geracao artificial para equilibrar classes.
    Apresenta metricas de **SHAP** e **clustering** para comparacao de algoritmos.
    """)

    st.subheader("Metricas SHAP")
    arq_shap_m = None
    if chave_curso:
        arq_shap_m = _buscar("metricas", _pasta_motor("shap"), chave_curso)
    if arq_shap_m:
        st.dataframe(_ler(arq_shap_m), use_container_width=True)
        st.caption("Metricas de qualidade do modelo preditivo SHAP. Acuracia, F1 e AUC-ROC indicam desempenho geral.")
    else:
        st.info("Metricas SHAP nao encontradas para este curso.")

    st.subheader("Metricas de Clustering")
    arq_clust = None
    if chave_curso:
        arq_clust = _buscar("metricas", _pasta_motor("clustering"), chave_curso)
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

    st.markdown("---")
    st.subheader("Batalha de Classificadores (modelos/preditivos)")
    st.markdown("""
    Previsao binaria dos extremos de desempenho (**Alto Desempenho [Top 30%]** / **Risco Critico [Bottom 30%]**)
    a partir das respostas as 38 questoes, apos filtro de anomalias (Isolation Forest), reducao de
    dimensionalidade (PCA) e balanceamento (SMOTE). **Acuracia** e **F1** comparam os modelos por curso.
    """)
    arq_clf = None
    if chave_curso:
        arq_clf = _buscar("metricas_modelos", _pasta_motor("preditivos"), chave_curso)
    if arq_clf:
        df_clf = _ler(arq_clf)
        if df_clf is not None and not df_clf.empty:
            df_num_clf = df_clf.copy()
            for c in df_num_clf.columns[1:]:
                df_num_clf[c] = pd.to_numeric(df_num_clf[c], errors="coerce")
            melhor_col = "Acuracia" if "Acuracia" in df_num_clf.columns else df_num_clf.select_dtypes(include=[np.number]).columns[0]
            col_m, col_t = st.columns([1, 2])
            with col_m:
                melhor_row = df_num_clf.loc[df_num_clf[melhor_col].idxmax()]
                st.metric("Melhor Classificador", str(melhor_row.iloc[0]),
                          delta=f"{float(melhor_row[melhor_col]):.2%} {melhor_col}")
                st.info("LightGBM/XGBoost tendem a capturar melhor as correlacoes nao-lineares das respostas cognitivas.")
            with col_t:
                st.dataframe(df_clf, use_container_width=True)
            fig_clf = px.bar(df_num_clf, x=melhor_col, y=df_num_clf.columns[0], orientation="h",
                             color=melhor_col, color_continuous_scale="Viridis",
                             title="Comparativo de Acuracia entre Modelos")
            fig_clf.update_layout(yaxis={"categoryorder": "total ascending"}, showlegend=False, height=320)
            st.plotly_chart(fig_clf, use_container_width=True)
            st.caption("Fonte: metricas_modelos_*.csv em modelos/preditivos/. Modelo com maior acuracia nem sempre e o mais generalizavel; "
                       "considere tambem F1 e validacao cruzada.")
        else:
            st.info("Arquivo de metricas de classificacao vazio.")
    else:
        st.info("Metricas de classificacao (metricas_modelos_*.csv) nao encontradas em modelos/preditivos/ para este curso.")

    st.markdown("---")
    st.subheader("Batalha de Classificadores Classicos (K-NN, DT, RF, SVM, MLP)")
    st.markdown("""
    **Benchmark em tempo real** entre os cinco classificadores classicos, com alvo **externo**
    (`NT_DIS_CE` > `NT_CE_D1` > `NT_GER`), para evitar alvo circular a partir dos proprios itens.
    O alvo e binario (nota externa >= mediana) e a avaliacao usa **validacao cruzada estratificada (5 dobras)**:
    Acuracia, F1 e AUC-ROC comparam a capacidade de cada modelo em separar os extremos de desempenho.
    """)
    from algoritmos.preditivos.batalha_classificadores import executar_batalha, preparar_colunas
    if df_curso is not None and not df_curso.empty:
        colunas_q_live = preparar_colunas(df_curso)
        if len(colunas_q_live) < 3:
            st.info("Base do curso sem colunas de itens (Q*) suficientes para a batalha em tempo real.")
        else:
            with st.spinner(f"Treinando K-NN, Arvore de Decisao, Random Forest, SVM e MLP em "
                            f"{len(colunas_q_live)} itens de {nome_curso or 'curso'} (CV 5x)..."):
                df_clf_live = executar_batalha(df_curso, colunas_q_live)
            if df_clf_live is not None and not df_clf_live.empty:
                melhor_live = df_clf_live.loc[df_clf_live["Acuracia"].idxmax()]
                c_b, c_t = st.columns([1, 2])
                with c_b:
                    st.metric("Melhor Classificador (tempo real)",
                              str(melhor_live["Modelo"]),
                              delta=f"{float(melhor_live['Acuracia']) * 100:.1f}% acuracia (CV)")
                    st.info("O Alvo e a nota **discursiva** (externo); modelos que capturam relacoes nao-lineares "
                            "das respostas cognitivas (RF/SVM/MLP) costumam se destacar quando ha sinal real.")
                with c_t:
                    st.dataframe(df_clf_live, use_container_width=True)
                fig_clf_live = px.bar(df_clf_live, x="Acuracia", y="Modelo", orientation="h",
                                      color="Acuracia", color_continuous_scale="Viridis",
                                      title="K-NN vs DT vs RF vs SVM vs MLP (Acuracia em validacao cruzada)")
                fig_clf_live.update_layout(yaxis={"categoryorder": "total ascending"},
                                           height=320, showlegend=False)
                st.plotly_chart(fig_clf_live, use_container_width=True)
                st.caption("Acuracia perto do baseline (proporcao da classe majoritaria) indica que o desempenho "
                           "externo e pouco previsivel a partir dos acertos item a item.")
            else:
                st.info("Amostra insuficiente (<100 alunos com nota externa valida) para a batalha em tempo real.")
    else:
        st.info("Selecione um curso para executar a batalha de classificadores classicos em tempo real.")

    st.markdown("---")
    st.subheader("Detecao de Drift (Univariado e Multivariado)")
    st.markdown("""
    Avalia se a distribuicao das respostas dos alunos do curso/IES (**producao**) se desviou da
    distribuicao de referencia do curso em nivel nacional (**treinamento**).

    **Univariate Drift (variavel a variavel):**
    - *Kolmogorov-Smirnov (K-S test)* e *Wasserstein (Earth Mover's Distance)* — distribucoes continuas;
    - *Cramer's V* e *Population Stability Index (PSI)* — distribucoes discretas/categoricas.

    **Multivariate Drift (distribuicao conjunta):**
    - *PCA reconstruction error* (estilo NannyML): compacta o conjunto de referencia com um PCA e mede o
      erro de reconstrucao ao descompactar. Se o erro do conjunto em producao supera a linha de base
      (erro do proprio conjunto de referencia em validacao cruzada), ha indice forte de drift multivariado.
    """)
    from algoritmos.drift.detectar_drift import drift_univariado, drift_pca_multivariado
    if df_curso is not None and len(df_curso) >= 20 and df_nacional is not None and len(df_nacional) >= 20:
        ref_d = df_nacional.sample(n=min(8000, len(df_nacional)), random_state=42) if len(df_nacional) > 8000 else df_nacional
        prod_d = df_curso.sample(n=min(8000, len(df_curso)), random_state=42) if len(df_curso) > 8000 else df_curso
        colunas_q_drift = preparar_colunas(df_nacional)
        colunas_q_comuns = [c for c in colunas_q_drift if c in df_curso.columns]
        extras_cont = [c for c in ("NT_GER", "NT_DIS_CE") if c in df_nacional.columns and c in df_curso.columns]
        colunas_uni = colunas_q_comuns[:40] + extras_cont

        st.subheader("Drift Univariado")
        df_u = drift_univariado(ref_d, prod_d, colunas_uni)
        if df_u.empty:
            st.info("Colunas em comum insuficientes para a analise univariada.")
        else:
            n_drift = int(df_u["Status"].str.startswith("Drift").sum())
            m_du_1, m_du_2, m_du_3, m_du_4 = st.columns(4)
            m_du_1.metric("Variaveis Auditadas", len(df_u))
            m_du_2.metric("Com Drift (KS/PSI)", n_drift)
            m_du_3.metric("Drift Forte (PSI>=0.25)", int(df_u["Status"].eq("Drift forte").sum()))
            m_du_4.metric("Moderado (0.1-0.25)", int(df_u["Status"].eq("Drift moderado").sum()))
            df_u_show = df_u.drop(columns=["Tipo"]).copy() if "Tipo" in df_u.columns else df_u
            st.dataframe(df_u_show, use_container_width=True)
            st.caption("**PSI**: <0.1 sem drift; 0.1-0.25 moderado; >=0.25 forte. **KS**: p<0.05 indica mudanca de distribuicao. "
                       "**Cramer's V / Wasserstein** complementam a magnitude da mudanca.")

        st.subheader("Drift Multivariado (PCA Reconstruction - NannyML)")
        if len(colunas_q_comuns) >= 3:
            res_pca = drift_pca_multivariado(ref_d, prod_d, colunas_q_comuns)
            if res_pca is None:
                st.info("Dados insuficientes (<20 linhas validas ou <3 itens em comum) para o PCA.")
            else:
                cor = "#d62728" if res_pca["status"].startswith("Drift") else "#2ca02c"
                m_du_5, m_du_6, m_du_7, m_du_8 = st.columns(4)
                m_du_5.metric("Erro Reconstrucao (Referencia)", f"{res_pca['mse_baseline']:.4f}")
                m_du_6.metric("Erro Reconstrucao (Producao)", f"{res_pca['mse_prod']:.4f}")
                m_du_7.metric("Razao Prod/Base", f"{res_pca['ratio']:.2f}" if res_pca["ratio"] is not None else "-")
                m_du_8.metric("Variancia Explicada", f"{res_pca['variancia_explicada'] * 100:.1f}%")
                if res_pca["status"].startswith("Sem"):
                    st.success(res_pca["status"])
                else:
                    st.error(res_pca["status"])
                fig_pca = go.Figure(go.Bar(
                    x=["Referencia (baseline CV)", "Producao (curso/IES)"],
                    y=[res_pca["mse_baseline"], res_pca["mse_prod"]],
                    marker_color=["#1f77b4", "#d62728" if res_pca["status"].startswith("Drift") else "#2ca02c"],
                    text=[f"{res_pca['mse_baseline']:.4f}", f"{res_pca['mse_prod']:.4f}"], textposition="auto"))
                fig_pca.update_layout(title=f"Erro de Reconstrucao do PCA ({res_pca['n_componentes']} componentes)",
                                      yaxis_title="Erro medio quadratico",
                                      height=360)
                st.plotly_chart(fig_pca, use_container_width=True)
                st.caption("Se o erro de reconstrucao do conjunto em producao excede 1.25x a linha de base da "
                           "referencia, o modelo PCA 'nao reconhece' a distribuicao atual -> drift multivariado.")
                st.markdown("**Variaveis de maior contribuicao para o eixo de maior variancia:**")
                st.dataframe(res_pca["principais"], use_container_width=True)
        else:
            st.info("Menos de 3 itens em comum para o drift multivariado (PCA).")
    else:
        st.info("Selecione um curso/IES para comparar a distribuicao de producao com a referencia nacional.")

    st.markdown("---")

    st.markdown("---")
    st.subheader("Explicacoes (IA Explicativa -- SHAP / Permutacao)")
    st.markdown("""
    Modelos de Redes Neurais e Boosting sao frequentemente criticados por serem 'Caixas Pretas'.
    Para solucionar isso, o pipeline usa **SHAP real** e **importancia por permutacao**, revelando
    quais questoes do ENADE foram determinantes para a decisao do algoritmo. (Sem SHAP simulado.)
    """)
    arq_xai = None
    if chave_curso:
        arq_xai = _buscar("atribuicao", _pasta_motor("xai"), chave_curso)
        if not arq_xai:
            arq_xai = _buscar("importancia", _pasta_motor("shap"), chave_curso)
        if not arq_xai:
            arq_xai = _buscar("importancia_variaveis", _pasta_motor("preditivos"), chave_curso)
    if arq_xai:
        df_xai = _ler(arq_xai)
        if df_xai is not None and not df_xai.empty:
            df_xai = df_xai.copy()
            f_col = "feature" if "feature" in df_xai.columns else df_xai.columns[0]
            i_cols = [c for c in df_xai.columns if c != f_col and c.lower() not in ("peso_pct", "importance_pct")]
            if i_cols:
                v_col = i_cols[0]
                df_xai[v_col] = pd.to_numeric(df_xai[v_col], errors="coerce")
                df_xai = df_xai.dropna(subset=[v_col])
                if not df_xai.empty:
                    df_xai = df_xai.sort_values(v_col, ascending=True)
                    fig_xai = px.bar(df_xai, x=v_col, y=f_col, orientation="h", color=v_col,
                                     color_continuous_scale="OrRd",
                                     title="Importancia das Variaveis na Predicao (SHAP/permutacao)")
                    fig_xai.update_layout(yaxis={"categoryorder": "total ascending"}, height=max(380, 22 * len(df_xai)))
                    col_g, col_s = st.columns([2, 1])
                    with col_g:
                        st.plotly_chart(fig_xai, use_container_width=True)
                    with col_s:
                        st.write("### Diagnostico XAI")
                        top = df_xai.iloc[-1][f_col]
                        st.warning(f"O **{top}** e o fator com maior peso discriminatorio para prever o sucesso ou falha do aluno.")
                        st.info("A interpretacao deve considerar tambem a importancia por permutacao (mudanca no erro "
                                "quando a variavel e embaralhada).")
                else:
                    st.info("Coluna de importancia vazia ou invalida.")
            else:
                st.info("Arquivo XAI sem coluna de importancia detectada.")
        else:
            st.info("Arquivo de importancia vazio.")
    else:
        st.info("Arquivos de importancia XAI nao encontrados para este curso "
                "(tentados: modelos/xai/atribuicao_*.csv, modelos/shap/importancia_*.csv, modelos/preditivos/importancia_variaveis_*.csv).")

    st.subheader("Tabela Comparativa de Algoritmos")
    st.markdown("""
    | Algoritmo | Tipo | Descricao | Indicador Ideal |
    |-----------|------|-----------|-----------------|
    | K-Means / GMM / Hierarquico | Clustering | Agrupamento de perfis | Silhueta > 0.5, BIC baixo, DB baixo |
    | k-NN (k=5) | Classificacao | Vizinhos mais proximos | Acuracia/F1 altos na CV |
    | Arvore de Decisao (DT) | Classificacao | Particionamento por regras | Acuracia/F1 altos |
    | Random Forest (RF) | Classificacao | Floresta de arvores | Acuracia/F1 altos, robusto |
    | SVM (RBF) | Classificacao | Maquina de vetores de suporte | Acuracia/F1 altos na CV |
    | MLP (Redes Neurais) | Classificacao | Perceptron multicamadas | Acuracia/F1 altos na CV |
    | K-S Test + Wasserstein | Drift Univariado | Igualdade de distribuicoes (continuas) | p >= 0.05 (sem drift) |
    | Cramer's V + PSI | Drift Univariado | Mudanca de distribuicao (discretas) | PSI < 0.1 (sem drift) |
    | PCA Reconstruction | Drift Multivariado | Erro de compressao/descompressao | Razao prod/base <= 1.25 |
    """)
    st.caption("Tabela de referencia para interpretar os resultados de clustering, classificacao e deteccao de drift.")

    st.markdown("---")
    st.subheader("ANOVA Regional: A Regiao Explica o Desempenho?")
    st.markdown("""
    Analise de variancia (ANOVA/Kruskal-Wallis robusto) testa se ha diferencas estatisticamente significativas no desempenho
    entre as regioes brasileiras. O **Eta²** mede o tamanho do efeito (proporcao da variancia explicada pela regiao).
    """)
    _df_anova_src = df_nacional if df_nacional is not None else (df_curso if 'df_curso' in locals() else None)
    if _df_anova_src is not None and not _df_anova_src.empty:
        cols_norm_an = {str(c).strip().upper(): c for c in _df_anova_src.columns}
        c_reg = next((cols_norm_an[k] for k in ["CO_REGIAO_CURSO", "CO_REGIAO", "REGIAO_CURSO", "COD_REGIAO_CURSO"] if k in cols_norm_an), None)
        c_nt = next((cols_norm_an[k] for k in ["NT_GER", "NT_OBJ_CE", "NOTA_GERAL", "MEDIA_GLOBAL"] if k in cols_norm_an), None)
    else:
        c_reg = c_nt = None
    if _df_anova_src is not None and c_reg and c_nt:
        rmapANOVA = {1: "Norte", 2: "Nordeste", 3: "Sudeste", 4: "Sul", 5: "Centro-Oeste",
                     "1": "Norte", "2": "Nordeste", "3": "Sudeste", "4": "Sul", "5": "Centro-Oeste"}
        df_anova = _df_anova_src[[c_reg, c_nt]].copy()
        df_anova[c_nt] = pd.to_numeric(df_anova[c_nt], errors="coerce")
        reg_raw = df_anova[c_reg]
        df_anova["Regiao"] = reg_raw.map(rmapANOVA)
        if df_anova["Regiao"].isna().all():
            df_anova["Regiao"] = reg_raw.astype(str).str.strip()
        df_anova = df_anova.dropna(subset=["Regiao", c_nt])
        df_anova = df_anova[df_anova["Regiao"].astype(str).str.lower() != "nan"]
        if df_anova["Regiao"].nunique() >= 2:
            grupos = [g[c_nt].values for _, g in df_anova.groupby("Regiao") if len(g) >= 2]
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
                m_a3.metric("Eta² (Efeito)", f"{eta2:.4f}")
                m_a4.metric("Variancia Explicada", f"{eta2 * 100:.2f}%")
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
                        st.info(f"**Resultado:** Diferenca estatistica significativa (p={p_val:.4f}), mas o efeito e **minusculo** (Eta²={eta2:.4f}). "
                                "A regiao explica menos de 1% da variancia. Outros fatores (qualidade do ensino, socioeconomicos) sao muito mais relevantes.")
                    elif eta2 < 0.06:
                        st.warning(f"**Resultado:** Diferenca significativa (p={p_val:.4f}) com efeito **pequeno** (Eta²={eta2:.4f}). "
                                   "A regiao tem influencia limitada sobre o desempenho.")
                    else:
                        st.error(f"**Resultado:** Diferenca significativa (p={p_val:.4f}) com efeito **moderado/grande** (Eta²={eta2:.4f}). "
                                 "A regiao e um fator relevante de desigualdade.")
                else:
                    st.success(f"**Resultado:** Nao ha diferenca significativa entre regioes (p={p_val:.4f}). "
                               "A regiao nao e um fator explicativo relevante para este curso.")
                media_reg = df_anova.groupby("Regiao")[c_nt].agg(["mean", "count", "std"]).reset_index()
                media_reg.columns = ["Regiao", "Media_Nota", "N_Alunos", "Desvio"]
                media_reg = media_reg.sort_values("Media_Nota", ascending=False)
                fig_anova = px.bar(media_reg, x="Regiao", y="Media_Nota", color="Media_Nota",
                                   color_continuous_scale="RdYlGn", text="Media_Nota",
                                   title=f"Media de {c_nt} por Regiao (ANOVA)")
                fig_anova.update_traces(texttemplate="%{text:.2f}", textposition="outside")
                fig_anova.update_layout(height=400)
                st.plotly_chart(fig_anova, use_container_width=True)
                st.dataframe(media_reg, use_container_width=True)
                st.caption(f"Fonte/colunas usadas: regiao=`{c_reg}`, nota=`{c_nt}`. Diagnostico pedagogico: intervencoes devem considerar "
                           "qualidade do ensino e contexto socioeconomico, nao apenas recortes regionais genericos.")
            else:
                st.info("Menos de 2 regioes com dados suficientes para ANOVA.")
        else:
            st.info("Menos de 2 regioes presentes nos dados.")
    else:
        cols_disp = list(_df_anova_src.columns)[:12] if _df_anova_src is not None else []
        st.info("Colunas de regiao/nota nao disponiveis para ANOVA regional (buscadas: CO_REGIAO_CURSO/CO_REGIAO e NT_GER/NT_OBJ_CE)."
                + (f" Colunas detectadas (amostra): {cols_disp}" if cols_disp else ""))
    



# --- TAB 8: PSICOMETRIA COMPUTACIONAL ---
elif aba == ABAS[8]:
    st.header("Psicometria Computacional & IA Educacional")
    st.markdown("""
    Esta aba apresenta a fronteira cientifica da Mineracao de Dados Educacionais (EDM).
    O pipeline combina metricas classicas dos testes (TCT), redes neurais nao-lineares e modelos de dependencia de itens
    para decodificar o comportamento cognitivo dos estudantes -- com avaliacao honesta (treino/teste ou validacao cruzada).
    """)

    sub_tab_som, sub_tab_dina, sub_tab_clust = st.tabs(["SOM (Self-Organizing Map)", "Resultados DINA", "Metricas de Clustering"])

    with sub_tab_som:
        st.subheader("Topologia Cognitiva via SOM (Redes de Kohonen)")
        st.markdown("""
        O algoritmo **Self-Organizing Maps (SOM)** projeta a matriz multidimensional de respostas numa grelha
        neural competitiva nao-supervisionada. O grafico abaixo indica a topologia cognitiva dos estudantes,
        revelando padroes de agrupamento por perfil de desempenho.
        """)
        som_files = sorted(_pasta_motor("psicometria").glob("som_*.png")) if _pasta_motor("psicometria").exists() else []
        if som_files:
            for som_file in som_files:
                st.image(str(som_file), use_container_width=True)
                st.caption(f"SOM -- {som_file.stem}. Areas de mesma cor indicam alunos com perfis cognitivos semelhantes.")
        else:
            st.info("Nenhuma imagem SOM encontrada em modelos/psicometria/.")
            st.warning("Execute o pipeline de psicometria para gerar os mapas auto-organizaveis.")

    with sub_tab_dina:
        st.subheader("Resultados DINA (Slip & Guess)")
        st.markdown("""
        Parametros estimados pelo modelo **DINA** (Deterministic Input, Noisy "And" Gate).
        O **slip** mede a probabilidade de erro do dominante; o **guess** mede acerto por sorte.
        Valores de slip > 0.3 e guess > 0.3 indicam itens problematicos que precisam de revisao.
        """)
        pasta_cdm_atual = _pasta_motor("cdm")
        dina_files = sorted(pasta_cdm_atual.glob("dina_*.csv")) if pasta_cdm_atual.exists() else []
        dina_files = [f for f in dina_files if "q_matrix" not in f.name]
        if dina_files:
            for dina_file in dina_files:
                st.markdown(f"**{dina_file.stem}**")
                df_dina = _ler(dina_file)
                ok = False
                if df_dina is not None and not df_dina.empty:
                    cols_norm = {str(c).strip().lower(): c for c in df_dina.columns}
                    c_q = cols_norm.get("questao") or cols_norm.get("item") or cols_norm.get("q")
                    c_slip = cols_norm.get("slip_s") or cols_norm.get("slip")
                    c_guess = cols_norm.get("guess_g") or cols_norm.get("guess")
                    if c_q and c_slip and c_guess:
                        fig_dina = go.Figure()
                        fig_dina.add_trace(go.Scatter(x=pd.to_numeric(df_dina[c_slip], errors="coerce"),
                                                      y=pd.to_numeric(df_dina[c_guess], errors="coerce"),
                                                      mode="markers+text",
                                                      text=df_dina[c_q], textposition="top center",
                                                      marker=dict(size=10, color="#8b5cf6")))
                        fig_dina.add_hline(y=0.3, line_dash="dash", line_color="red", opacity=0.5, annotation_text="Limiar Guess")
                        fig_dina.add_vline(x=0.3, line_dash="dash", line_color="red", opacity=0.5, annotation_text="Limiar Slip")
                        fig_dina.update_layout(title=f"Dispersao Slip vs Guess -- {dina_file.stem}",
                                               xaxis_title="Slip (s)", yaxis_title="Guess (g)", height=450)
                        st.plotly_chart(fig_dina, use_container_width=True)
                        st.caption("Itens no canto superior direito (alto slip e guess) sao os mais problematicos e devem ser revisados.")
                        st.dataframe(df_dina, use_container_width=True)
                        ok = True
                if not ok:
                    cols_info = list(df_dina.columns)[:8] if df_dina is not None else []
                    st.warning(f"Arquivo {dina_file.name} nao contem colunas questao/slip/guess (ou slip_s/guess_g)." + (f" Colunas: {cols_info}" if cols_info else ""))
        else:
            st.info("Nenhum arquivo dina_*.csv encontrado em modelos/cdm/.")

    with sub_tab_clust:
        st.subheader("Metricas de Clustering")
        st.markdown("Metricas de qualidade para determinar o numero ideal de clusters.")
        if chave_curso:
            arq = _buscar("metricas", _pasta_motor("clustering"), chave_curso)
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
    df_a_psico = _carregar_analise_ies(_extrair_ano_filtro(sel_tipo, sel_id))
    if df_a_psico is not None and not df_a_psico.empty and "TAXA_DEFICIENCIA_%" in df_a_psico.columns:
        if _tem_colunas(df_a_psico, "CO_GRUPO"):
            df_heat = df_a_psico.copy()
            if _tem_colunas(df_heat, "CO_GRUPO"):
                df_heat["Curso"] = df_heat["CO_GRUPO"].map(
                    lambda x: _nome_grupo(x, ano_fil) if pd.notna(x) else str(x))
            ind_data = []
            for curso_nome, grp in df_heat.groupby("Curso"):
                if len(grp) < 3:
                    continue
                media_def = grp["TAXA_DEFICIENCIA_%"].mean()
                oc_cols_h = [c for c in grp.columns if c.startswith("OC")]
                n_questoes = grp["QUESTAO"].nunique() if "QUESTAO" in grp.columns else 0
                ind_data.append({
                    "Curso": _curto(curso_nome, 30),
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


# --- TAB 9: AUDITORIA DE COMPETENCIAS SECULO XXI ---
elif aba == ABAS[9]:
    st.header("Auditoria de Competencias do Seculo XXI")
    st.markdown("""
    Baseado na framework do *Journal of Learning Analytics (2026)*, este modulo audita a matriz formativa avaliada no ENADE.
    Identificamos se a instituicao esta formando profissionais apenas com vies tecnico ou com
    **Responsabilidade Social e Tecnologica integral**. Apresenta um radar chart com hard/soft skills scatter.
    """)

    df_a = _carregar_analise_ies(ano_fil, sel_tipo)
    if df_a is None or df_a.empty:
        st.info("Nenhum dado de analise por questao disponivel para esta edicao.")
    else:
        df_f = _obter_filtro_analise(df_a)
        if df_f.empty and curso_codigo and "CO_GRUPO" in df_a.columns:
            df_f = df_a[df_a["CO_GRUPO"] == curso_codigo].copy()

        if sel_tipo == "enamed":
            cod_enamed = None
            if chave_curso and str(chave_curso).startswith("enamed_"):
                cod_enamed = pd.to_numeric(str(chave_curso).split("_", 1)[1], errors="coerce")
            if pd.notna(cod_enamed) and "CO_CURSO" in df_a.columns:
                sub_env = df_a[df_a["CO_CURSO"] == cod_enamed]
                if not sub_env.empty:
                    df_f = sub_env.copy()

        if df_f.empty:
            st.info("Selecione um curso/IES para auditar. Dados de analise por questao indisponiveis.")
        else:
            oc_cols = [c for c in df_f.columns if c.startswith("OC")]
            if not oc_cols:
                st.info("Os dados de analise por questao desta edicao nao possuem colunas de OC.")
            else:
                # --- Mapeamento questao -> OCs do curso/edicao selecionados ---
                mapa_q_oc = {}
                for _, row in df_f.iterrows():
                    q = str(row.get("QUESTAO", "")).strip()
                    if not q or q.lower() == "nan":
                        continue
                    ocs_q = []
                    for c in oc_cols:
                        val = str(row.get(c, "")).strip()
                        if val and val != "nan" and val != "":
                            nome_oc = _oc_sem_prefixo(val)
                            if nome_oc and nome_oc != "outras_competencias":
                                ocs_q.append(nome_oc)
                    if ocs_q:
                        mapa_q_oc.setdefault(q, ocs_q)

                if not mapa_q_oc:
                    st.info("Nenhum Objeto de Conhecimento encontrado nas questoes deste curso.")
                else:
                    # ---- Proficiencia de cada aluno em cada OC (a partir das respostas Q*) ----
                    q_cols_resp = [c for c in df_curso.columns if c.startswith("Q") and c[1:].isdigit()] if df_curso is not None else []
                    todos_ocs = []
                    for ocs_q in mapa_q_oc.values():
                        for o in ocs_q:
                            if o not in todos_ocs:
                                todos_ocs.append(o)

                    df_aluno_oc = None
                    if df_curso is not None and q_cols_resp:
                        regs = []
                        for _, al in df_curso.iterrows():
                            linha = {"ALUNO": str(al.get("ALUNO", ""))}
                            for oc in todos_ocs:
                                acertos = []
                                for q, ocs_q in mapa_q_oc.items():
                                    if oc not in ocs_q:
                                        continue
                                    nome_col = q if q in df_curso.columns else ("Q" + q.lstrip("Q"))
                                    val = al.get(nome_col, None)
                                    if pd.notna(val) and str(val).strip() not in ("", ".", "nan"):
                                        acertos.append(1.0 if str(val).strip() == "1" else 0.0)
                                linha[oc] = (sum(acertos) / len(acertos) * 100) if acertos else np.nan
                            regs.append(linha)
                        df_aluno_oc = pd.DataFrame(regs) if regs else None
                        if df_aluno_oc is not None:
                            st.caption(f"Proficiencia por OC calculada para {len(df_aluno_oc)} alunos a partir das respostas item a item de {len(q_cols_resp)} questoes.")

                    # ---- Tabela de OCs do curso/edicao (agregacao por OC) ----
                    oc_melt = []
                    for _, row in df_f.iterrows():
                        taxa = row.get("TAXA_DEFICIENCIA_%", 0)
                        if pd.isna(taxa):
                            taxa = 0
                        for c in oc_cols:
                            val = str(row.get(c, "")).strip()
                            if val and val != "nan" and val != "":
                                nome_oc = _oc_sem_prefixo(val)
                                if nome_oc and nome_oc != "outras_competencias":
                                    oc_melt.append({"OC": nome_oc, "TAXA_DEFICIENCIA_%": taxa})

                    df_oc = pd.DataFrame(oc_melt) if oc_melt else pd.DataFrame(columns=["OC", "TAXA_DEFICIENCIA_%"])
                    if not df_oc.empty:
                        df_oc = df_oc.groupby("OC").agg(
                            Media_Erro=("TAXA_DEFICIENCIA_%", "mean"),
                            N_Questoes=("TAXA_DEFICIENCIA_%", "count")
                        ).reset_index().sort_values("Media_Erro", ascending=False)

                    SOFT_KEYWORDS = [
                        "etica", "cidadania", "sustentabilidade", "bioetica",
                        "educacao ambiental", "respeito", "diversidade",
                        "responsabilidade social", "legislacao", "politicas publicas",
                        "inclusao", "genero", "igualdade", "justica social",
                        "meio ambiente", "etica profissional", "valores humanos",
                        "compromisso social", "cidadao", "dignidade", "tolerancia",
                        "solidariedade", "saude publica", "seguranca do trabalho"
                    ]

                    def _classificar_oc(nome):
                        n = _norm_oc(nome)
                        for kw in SOFT_KEYWORDS:
                            if kw in n:
                                return "Soft Skills (Etica/Cidadania)"
                        return "Hard Skills (Tecnico)"

                    df_oc["Classificacao"] = df_oc["OC"].apply(_classificar_oc)

                    st.success(f"{len(df_oc)} Objetos de Conhecimento das questoes de {nome_curso or 'Curso'} ({sel_label}) identificados. "
                               f"{int((df_oc['Classificacao'].str.startswith('Hard')).sum())} tecnicos e "
                               f"{int((df_oc['Classificacao'].str.startswith('Soft')).sum())} de cidadania/etica.")

                    with st.expander("Reclassificar Objetos de Conhecimento (Hard vs Soft)", expanded=True):
                        st.caption("O sistema classificou automaticamente. Voce pode reclassificar manualmente.")
                        c1, c2 = st.columns(2)
                        with c1:
                            hard_ocs = st.multiselect(
                                "Hard Skills (Tecnico):",
                                df_oc["OC"].tolist(),
                                default=df_oc[df_oc["Classificacao"].str.startswith("Hard")]["OC"].tolist(),
                                key="aud_hard_ocs")
                        with c2:
                            soft_ocs = st.multiselect(
                                "Soft Skills (Etica/Cidadania):",
                                df_oc["OC"].tolist(),
                                default=df_oc[df_oc["Classificacao"].str.startswith("Soft")]["OC"].tolist(),
                                key="aud_soft_ocs")
                        df_oc["Classificacao"] = df_oc["OC"].apply(
                            lambda x: "Hard Skills (Tecnico)" if x in hard_ocs
                            else "Soft Skills (Etica/Cidadania)")

                    hard_ocs_final = df_oc[df_oc["Classificacao"].str.startswith("Hard")]["OC"].tolist()
                    soft_ocs_final = df_oc[df_oc["Classificacao"].str.startswith("Soft")]["OC"].tolist()

                    if not hard_ocs_final or not soft_ocs_final:
                        st.info("Selecione ao menos um OC tecnico (Hard) e um de cidadania/etica (Soft) para gerar o Radar de Competencias.")
                    elif df_aluno_oc is None or df_aluno_oc.empty:
                        st.info("Sem respostas item a item (Q*) na base selecionada; impossivel calcular proficiencia por aluno/OC.")
                    else:
                        # ---- Medias Hard/Soft por aluno (mesmo padrao do dashboard_completo.py) ----
                        df_comp = df_aluno_oc.copy()
                        df_comp["Media_Hard_Skills"] = df_comp[hard_ocs_final].mean(axis=1, skipna=True)
                        df_comp["Media_Soft_Skills"] = df_comp[soft_ocs_final].mean(axis=1, skipna=True)

                        condicoes = [
                            (df_comp["Media_Hard_Skills"] >= 50) & (df_comp["Media_Soft_Skills"] >= 50),
                            (df_comp["Media_Hard_Skills"] >= 50) & (df_comp["Media_Soft_Skills"] < 50),
                            (df_comp["Media_Hard_Skills"] < 50) & (df_comp["Media_Soft_Skills"] >= 50),
                            (df_comp["Media_Hard_Skills"] < 50) & (df_comp["Media_Soft_Skills"] < 50)
                        ]
                        categorias = [
                            'Lider do Sec. XXI (Alta Tecnica e Etica)',
                            'Risco Etico/Social (Foco Tecnico)',
                            'Perfil Humanista (Deficiencia Tecnica)',
                            'Risco Critico (Deficiencia Dupla)'
                        ]
                        df_comp["Perfil_Seculo21"] = np.select(condicoes, categorias, default='Indefinido')
                        cores = {
                            'Lider do Sec. XXI (Alta Tecnica e Etica)': '#2ca02c',
                            'Risco Etico/Social (Foco Tecnico)': '#ff7f0e',
                            'Perfil Humanista (Deficiencia Tecnica)': '#1f77b4',
                            'Risco Critico (Deficiencia Dupla)': '#d62728'
                        }

                        fig = go.Figure()
                        for categoria, cor in cores.items():
                            df_cat = df_comp[df_comp["Perfil_Seculo21"] == categoria]
                            fig.add_trace(go.Scatter(
                                x=df_cat["Media_Hard_Skills"], y=df_cat["Media_Soft_Skills"],
                                mode="markers", name=categoria,
                                marker=dict(color=cor, size=9, opacity=0.75, line=dict(width=1, color="black")),
                                text=df_cat.get("ALUNO", df_cat.index),
                                hovertemplate="Aluno: %{text}<br>Media Tecnica: %{x:.1f}<br>Media Cidadania: %{y:.1f}<extra></extra>"))
                        fig.add_hline(y=50, line_dash="dash", line_color="black", annotation_text="Limiar Cidadania")
                        fig.add_vline(x=50, line_dash="dash", line_color="black", annotation_text="Limiar Tecnico")
                        fig.update_layout(
                            title=f"Dispersao de Competencias -- {nome_curso or 'Curso'} ({sel_label})",
                            xaxis_title="Proficiencia Tecnica - Hard Skills (0 a 100)",
                            yaxis_title="Proficiencia Cidada/Etica - Soft Skills (0 a 100)",
                            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                            plot_bgcolor='rgba(245, 245, 245, 1)', height=550)
                        st.plotly_chart(fig, use_container_width=True)
                        st.caption("Cada ponto e um aluno. Verde = Lider (ideal); Vermelho = Risco Critico. "
                                   "O cruzamento revela se o curso forma profissionais completos.")

                        st.subheader("Diagnostico Pedagogico Automatico")
                        total = len(df_comp)
                        perc_lider = (len(df_comp[df_comp["Perfil_Seculo21"] == categorias[0]]) / total) * 100 if total > 0 else 0
                        perc_risco = (len(df_comp[df_comp["Perfil_Seculo21"] == categorias[1]]) / total) * 100 if total > 0 else 0
                        m1, m2, m3 = st.columns(3)
                        m1.metric("Total de Alunos", f"{total}")
                        m2.metric("Formacao Ideal (Lideres)", f"{perc_lider:.1f}%")
                        m3.metric("Risco Etico/Tecnologico", f"{perc_risco:.1f}%", delta="Alerta Curricular", delta_color="inverse")
                        st.info(f"**Auditoria Retroativa de {nome_curso or 'Curso'}:** {perc_risco:.1f}% dos alunos possuem foco exclusivamente tecnico. "
                                "Recomenda-se aos NDE a integracao de projetos interdisciplinares.")

                    # ---- Tabela completa de OCs do curso/edicao (abaixo dos graficos) ----
                    st.subheader("Objetos de Conhecimento do Curso nesta Edicao")
                    st.markdown("Lista completa dos OCs mapeados para as questoes deste curso nesta edicao, "
                                "com eixo (Hard/Soft), taxa media de deficiencia e numero de questoes associadas.")
                    cols_mostra = [c for c in ["OC", "Classificacao", "Media_Erro", "N_Questoes"] if c in df_oc.columns]
                    st.dataframe(df_oc[cols_mostra], use_container_width=True)

                    fig_bar = go.Figure()
                    fig_bar.add_trace(go.Bar(
                        x=["Hard Skills (Tecnico)", "Soft Skills (Etica/Cidadania)"],
                        y=[df_oc.loc[df_oc["Classificacao"].str.startswith("Hard"), "Media_Erro"].mean() if (df_oc["Classificacao"].str.startswith("Hard")).any() else 0,
                           df_oc.loc[df_oc["Classificacao"].str.startswith("Soft"), "Media_Erro"].mean() if (df_oc["Classificacao"].str.startswith("Soft")).any() else 0],
                        marker_color=["#1f77b4", "#2ca02c"],
                        text=[round(df_oc.loc[df_oc["Classificacao"].str.startswith("Hard"), "Media_Erro"].mean(), 1) if (df_oc["Classificacao"].str.startswith("Hard")).any() else 0,
                              round(df_oc.loc[df_oc["Classificacao"].str.startswith("Soft"), "Media_Erro"].mean(), 1) if (df_oc["Classificacao"].str.startswith("Soft")).any() else 0],
                        textposition="auto"))
                    fig_bar.update_layout(
                        title="Taxa Media de Deficiencia por Eixo de Competencia (OCs da edicao)",
                        yaxis_title="Taxa Media de Deficiencia (%)", yaxis=dict(range=[0, 100]), height=380)
                    st.plotly_chart(fig_bar, use_container_width=True)


# --- TAB 10: SIMULADOR CONTRAFACTUAL ---
elif aba == ABAS[10]:
    st.header("Simulador Contrafactual Curricular (What-If Analytics)")
    st.markdown("""
    Esta funcionalidade simula **Politicas de Intervencao Pedagogica**.
    Usa um modelo monotônico no **escore composto dos itens selecionados** para estimar o impacto
    de intervenções em itens/disciplinas sobre a **Taxa de Excelência** do curso, calibrado no alvo
    externo disponível (ex.: `NT_DIS_CE`). A simulação é exploratória e **não estabelece causalidade**.
    NOTA: itens 0/1 são normalizados para 0-100; o deslocamento no composto é a média dos deltas dos itens selecionados.
    """)
    if df_curso is None or (hasattr(df_curso, 'empty') and df_curso.empty):
        st.warning("Selecione uma IES e Curso no filtro lateral.")
    else:
        cols_ignoradas = ['ALUNO', 'CO_CURSO', 'NOME_CURSO', 'CO_IES', 'CO_GRUPO', 'CO_REGIAO_CURSO',
                          'TP_SEXO', 'NU_IDADE', 'NT_GER', 'NT_CE', 'NT_DIS_CE', 'NT_FG', 'NT_BASE']
        # Itens do exame (Q*). Metadados administrativos NAO entram como "disciplinas".
        itens_exame = [c for c in df_curso.columns if re.fullmatch(r"Q\d{1,3}", str(c).strip(), re.I)]
        if len(itens_exame) < 2:
            itens_exame = [c for c in df_curso.columns if re.search(r"(^|_)(ITEM|QUESTAO)\d*", str(c), re.I)]
        if len(itens_exame) < 2:
            meta_prefixos = ("CO_", "NU_", "TP_", "IN_", "PESO", "EXAME", "ALUNO", "NOME_", "NT_", "COD_", "ID_", "ANO")
            itens_exame = [c for c in df_curso.columns
                           if c not in cols_ignoradas and not str(c).upper().startswith(meta_prefixos)]
        itens_num = []
        for d in itens_exame:
            s = pd.to_numeric(df_curso[d], errors="coerce")
            if s.notna().sum() > 10 and s.nunique(dropna=True) >= 2:
                df_curso[d] = s
                itens_num.append(d)

        if not itens_num:
            st.error("Nenhum item/disciplina numérica com variabilidade encontrada para simulação. "
                     "Verifique se o arquivo do exame contém colunas Q* (itens) preenchidas.")
        else:
            # Escala dos itens: ENADE/ENAMED/Licenciaturas costumam vir 0/1 (acerto).
            # Converte para 0-100 para que o slider em "pontos" tenha efeito interpretável.
            df_itens = df_curso[itens_num].apply(pd.to_numeric, errors="coerce").copy()
            escalas = {}
            for c in itens_num:
                mx = df_itens[c].max()
                if pd.notna(mx) and mx <= 1.5:
                    df_itens[c] = df_itens[c] * 100.0
                    escalas[c] = "0-1 -> 0-100"
                elif pd.notna(mx) and 1.5 < mx <= 10:
                    df_itens[c] = df_itens[c] / mx * 100.0
                    escalas[c] = f"0-{mx:g} -> 0-100"
                else:
                    df_itens[c] = df_itens[c].clip(0, 100)
                    escalas[c] = "0-100 (clip)"

            # Alvo EXTERNO (nao derivado das features): nota externa disponivel.
            alvo_col = None
            for candidato in ("NT_DIS_CE", "NT_CE_D1", "NT_GER"):
                if candidato in df_curso.columns:
                    serie = pd.to_numeric(df_curso[candidato], errors='coerce')
                    if serie.notna().sum() > 10 and serie.dropna().nunique() >= 2:
                        alvo_col = candidato
                        break

            if alvo_col is not None:
                alvo_serie = pd.to_numeric(df_curso[alvo_col], errors='coerce')
                corte = 60.0
                alvo_bin = (alvo_serie >= corte).astype(float)
                if alvo_bin.dropna().nunique() < 2:
                    corte = float(alvo_serie.dropna().median())
                    alvo_bin = (alvo_serie >= corte).astype(float)
                taxa_atual = float(alvo_bin.dropna().mean() * 100)
            else:
                alvo_serie = None
                score_base = df_itens[itens_num].mean(axis=1)
                taxa_atual = float((score_base >= 60).mean() * 100)

            st.caption(f"Taxa de Excelência definida pelo alvo externo: "
                       f"**{alvo_col or 'média dos itens (sem alvo externo disponível)'}** ≥ {corte if alvo_col else 60:.0f}.")

            st.subheader("Painel de Intervencao Curricular")
            st.caption("Selecione os itens/disciplinas e ajuste o impacto pedagógico estimado "
                       "(em pontos percentuais de domínio do item). Itens são normalizados para 0-100 quando necessário.")
            # Critério auditável: itens mais críticos = baixa média e alta cobertura.
            stats_itens = df_itens[itens_num].agg(["mean", "count"]).T
            max_count = max(float(stats_itens["count"].max()), 1.0)
            stats_itens["criticidade"] = (100.0 - stats_itens["mean"].clip(0, 100)) * (stats_itens["count"] / max_count)
            itens_prioritarios = stats_itens.sort_values("criticidade", ascending=False).index.tolist()
            default_itens = itens_prioritarios[:5]
            itens_sel = st.multiselect(
                "Itens/disciplinas para simular (padrão: 5 mais críticos):",
                itens_prioritarios, default=default_itens, key="sim_itens_sel",
                help="A lista é ordenada por criticidade = (100 - média) × cobertura. A simulação usa apenas os itens selecionados."
            )
            if not itens_sel:
                st.warning("Selecione ao menos um item/disciplina para simular. Usando os 5 mais críticos como padrão.")
                itens_sel = default_itens
            st.caption("Escalas detectadas: " + "; ".join(f"{_curto(k, 18)}: {v}" for k, v in escalas.items() if k in itens_sel))

            alteracoes_simuladas = {}
            cols_sliders = st.columns(min(len(itens_sel), 5))
            for i, disc in enumerate(itens_sel):
                with cols_sliders[i % len(cols_sliders)]:
                    delta = st.slider(f"Acao em:\n{_curto(disc, 18)}", min_value=-20, max_value=20, value=0, step=1,
                                      key=f"sim_{_norm_compacto(disc)}_{i}")
                    alteracoes_simuladas[disc] = int(delta)

            mudancas = {k: v for k, v in alteracoes_simuladas.items() if v != 0}
            if mudancas:
                st.caption("Intervenções aplicadas (pontos percentuais): " + ", ".join(f"{_curto(k,24)}={v:+d}" for k, v in mudancas.items()))
            else:
                st.caption("Nenhuma intervenção aplicada ainda: mova os cursores para simular.")

            df_sim_base = df_itens[itens_sel].copy()
            cols_sim = list(df_sim_base.columns)
            # imputa para evitar NaN quebrar o simulador
            for c in cols_sim:
                med = df_sim_base[c].median()
                df_sim_base[c] = df_sim_base[c].fillna(med if pd.notna(med) else 0)
            if alvo_col is None:
                # sem alvo externo, a linha de base é o próprio composto dos itens selecionados
                taxa_atual = float((df_sim_base.mean(axis=1) >= 60).mean() * 100)

            # Simulação principal: modelo monotônico no escore composto (S).
            # Árvores (XGBoost) são insensíveis a pequenos deslocamentos dentro das folhas;
            # por isso usamos regressão linear com sinal restrito, calibrada no alvo externo.
            S_base = df_sim_base.mean(axis=1)
            if alvo_col is not None:
                y_sim = pd.to_numeric(alvo_bin, errors="coerce")
                mask_y = y_sim.notna()
                S_fit = S_base[mask_y]
                y_fit = y_sim[mask_y].astype(int)
            else:
                S_fit = S_base
                y_fit = (S_base >= 60).astype(int)
            nova_taxa = None
            metodo = None
            if len(S_fit) >= 30 and y_fit.nunique() >= 2:
                try:
                    from sklearn.linear_model import LinearRegression
                    modelo_sim = LinearRegression(positive=True)
                    modelo_sim.fit(S_fit.values.reshape(-1, 1), y_fit.values)
                    coef = float(np.ravel(modelo_sim.coef_)[0])
                    intercepto = float(modelo_sim.intercept_)
                    if coef <= 1e-9:
                        # relação não positiva/plana: cai no fallback aritmético, que sempre responde ao slider
                        raise ValueError("coeficiente não positivo")
                    # deslocamento do escore composto: média dos deltas dos itens selecionados
                    shift = float(sum(alteracoes_simuladas.get(c, 0) for c in itens_sel) / max(len(itens_sel), 1))
                    S_sim = S_base + shift
                    prob_base = np.clip(intercepto + coef * S_base, 0, 1)
                    prob_sim = np.clip(intercepto + coef * S_sim, 0, 1)
                    # calibra a linha de base na taxa observada do recorte (delta=0 => taxa_atual)
                    nova_taxa = float(np.clip(taxa_atual + (prob_sim.mean() - prob_base.mean()) * 100, 0, 100))
                    metodo = (f"regressão linear monotônica no escore composto dos itens selecionados, "
                              f"calibrada na taxa observada (coef={coef:.4f}; deslocamento={shift:+.1f} pontos no composto)")
                except Exception:
                    nova_taxa = None
            if nova_taxa is None or (isinstance(nova_taxa, float) and np.isnan(nova_taxa)):
                # fallback aritmético transparente
                shift = float(sum(alteracoes_simuladas.get(c, 0) for c in itens_sel) / max(len(itens_sel), 1))
                S_sim = S_base + shift
                if alvo_col is not None:
                    nova_taxa = float(np.clip(taxa_atual + shift, 0, 100))
                else:
                    nova_taxa = float((S_sim >= 60).mean() * 100)
                metodo = "estimativa aritmética transparente (fallback)"
            diferenca = float(nova_taxa - taxa_atual)

            st.markdown("---")
            m1, m2, m3 = st.columns(3)
            m1.metric("Cenario Atual (Taxa de Excelencia)", f"{taxa_atual:.1f}%")
            status_cor = "normal" if diferenca >= 0 else "inverse"
            m2.metric("Cenario Simulado", f"{nova_taxa:.1f}%", f"{diferenca:+.1f}% de variacao", delta_color=status_cor)
            if diferenca > 0:
                m3.success(f"**Ganho Estimado:** Focar em disciplinas criticas pode expandir excelencia em **{diferenca:+.1f}%**.")
            elif diferenca < 0:
                m3.error(f"**Alerta de Risco:** Reducao de desempenho pode retrair excelencia em **{abs(diferenca):.1f}%**.")
            else:
                m3.info("Mova os cursores acima para rodar simulacoes contrafactuais sob demanda.")

            fig_sim = go.Figure()
            fig_sim.add_trace(go.Bar(x=['Cenario Atual', 'Cenario Simulado'], y=[taxa_atual, nova_taxa],
                                     marker_color=['#1f77b4', '#2ca02c' if diferenca >= 0 else '#d62728'],
                                     text=[f"{taxa_atual:.1f}%", f"{nova_taxa:.1f}%"], textposition='auto'))
            fig_sim.update_layout(title=f"Simulacao Contrafactual -- {nome_curso}",
                                  yaxis_title="Taxa de Excelencia (%)", yaxis=dict(range=[0, 100]), height=380)
            st.plotly_chart(fig_sim, use_container_width=True)
            st.caption(f"Grafico comparativo entre cenario real e simulado apos intervencoes curriculares. Método: {metodo}. "
                       f"Itens usados: {', '.join(itens_sel)}. A simulação é exploratória e não estabelece causalidade.")

            # ==============================================================
            # Variáveis contextuais (não curriculares)
            # ==============================================================
            st.markdown("---")
            st.subheader("Variáveis Contextuais (não curriculares)")
            st.markdown(
                "As variáveis abaixo **não são alavancas curriculares** e **não entram** no escore de intervenção. "
                "Elas descrevem **associações estruturais** (UF, região, categoria administrativa, organização "
                "acadêmica, modalidade, sexo e faixa etária) com a taxa de excelência. "
                "**Associação não implica causalidade.**"
            )

            # Recorte: mesmo curso em todas as IES (quando disponível), pois dentro de
            # uma única IES essas variáveis costumam ser constantes.
            base_ctx = df_curso
            if sel_grupo is not None and "CO_GRUPO" in df.columns:
                base_ctx = df[df["CO_GRUPO"] == sel_grupo].copy()
            if base_ctx is not df_curso and len(base_ctx) > len(df_curso):
                st.caption(f"Recorte: **nacional do mesmo curso** ({len(base_ctx):,} registros, todas as IES). "
                           "Esse recorte é necessário porque, dentro de uma única IES, várias dessas variáveis são constantes.")
            else:
                st.caption("Recorte: IES/curso selecionados. Dimensões constantes neste recorte não são exibidas.")

            # Alvo contextual (mesma regra do simulador, recalculada no recorte).
            if alvo_col is not None and alvo_col in base_ctx.columns:
                s_ctx = pd.to_numeric(base_ctx[alvo_col], errors="coerce")
                y_ctx = (s_ctx >= corte).astype(float)
                y_ctx[s_ctx.isna()] = np.nan
            else:
                cols_itens_ctx = [c for c in itens_num if c in base_ctx.columns]
                comp_ctx = base_ctx[cols_itens_ctx].apply(pd.to_numeric, errors="coerce").copy()
                for c in cols_itens_ctx:
                    mx = comp_ctx[c].max()
                    if pd.notna(mx) and mx <= 1.5:
                        comp_ctx[c] = comp_ctx[c] * 100.0
                comp_ctx = comp_ctx.mean(axis=1)
                y_ctx = (comp_ctx >= 60).astype(float)
                y_ctx[comp_ctx.isna()] = np.nan

            # Dimensões contextuais candidatas (rótulos auditáveis, código entre parênteses quando desconhecido).
            dims_ctx, rotulos_ctx, ctx_novas = [], {}, {}
            if "CO_UF_CURSO" in base_ctx.columns:
                uf_map = {11: "RO", 12: "AC", 13: "AM", 14: "RR", 15: "PA", 16: "AP", 17: "TO",
                          21: "MA", 22: "PI", 23: "CE", 24: "RN", 25: "PB", 26: "PE", 27: "AL", 28: "SE", 29: "BA",
                          31: "MG", 32: "ES", 33: "RJ", 35: "SP", 41: "PR", 42: "SC", 43: "RS",
                          50: "MS", 51: "MT", 52: "GO", 53: "DF"}
                ctx_novas["_CTX_UF"] = _rotular_codigos(base_ctx["CO_UF_CURSO"], uf_map, "UF")
                dims_ctx.append("_CTX_UF"); rotulos_ctx["_CTX_UF"] = "UF do curso"
            if "CO_REGIAO_CURSO" in base_ctx.columns:
                reg_map = {1: "Norte", 2: "Nordeste", 3: "Sudeste", 4: "Sul", 5: "Centro-Oeste"}
                ctx_novas["_CTX_REGIAO"] = _rotular_codigos(base_ctx["CO_REGIAO_CURSO"], reg_map, "Região")
                dims_ctx.append("_CTX_REGIAO"); rotulos_ctx["_CTX_REGIAO"] = "Região do curso"
            if "CO_CATEGAD" in base_ctx.columns:
                cat_map = {1: "Pública Federal", 2: "Pública Estadual", 3: "Pública Municipal",
                           4: "Privada com fins lucrativos", 5: "Privada sem fins lucrativos", 6: "Especial"}
                ctx_novas["_CTX_CATEG"] = _rotular_codigos(base_ctx["CO_CATEGAD"], cat_map, "Categoria")
                dims_ctx.append("_CTX_CATEG"); rotulos_ctx["_CTX_CATEG"] = "Categoria administrativa"
            if "CO_ORGACAD" in base_ctx.columns:
                org_map = {1: "Universidade", 2: "Centro Universitário", 3: "Faculdade",
                           4: "Instituto Federal/CEFET"}
                ctx_novas["_CTX_ORG"] = _rotular_codigos(base_ctx["CO_ORGACAD"], org_map, "Organização")
                dims_ctx.append("_CTX_ORG"); rotulos_ctx["_CTX_ORG"] = "Organização acadêmica"
            if "CO_MODALIDADE" in base_ctx.columns:
                mod_map = {1: "Presencial", 2: "EAD"}
                ctx_novas["_CTX_MOD"] = _rotular_codigos(base_ctx["CO_MODALIDADE"], mod_map, "Modalidade")
                dims_ctx.append("_CTX_MOD"); rotulos_ctx["_CTX_MOD"] = "Modalidade de ensino"
            if "TP_SEXO" in base_ctx.columns:
                sexo_map = {1: "Masculino", 2: "Feminino", "M": "Masculino", "F": "Feminino",
                            "m": "Masculino", "f": "Feminino", "1": "Masculino", "2": "Feminino"}
                ctx_novas["_CTX_SEXO"] = base_ctx["TP_SEXO"].map(sexo_map)
                dims_ctx.append("_CTX_SEXO"); rotulos_ctx["_CTX_SEXO"] = "Sexo"
            if "NU_IDADE" in base_ctx.columns:
                idade = pd.to_numeric(base_ctx["NU_IDADE"], errors="coerce")
                ctx_novas["_CTX_IDADE"] = pd.cut(
                    idade, bins=[0, 24, 29, 39, 49, 200],
                    labels=["Até 24", "25-29", "30-39", "40-49", "50+"])
                dims_ctx.append("_CTX_IDADE"); rotulos_ctx["_CTX_IDADE"] = "Faixa etária"
            if ctx_novas:
                # concatena uma única vez (evita DataFrame fragmentado)
                base_ctx = pd.concat([base_ctx, pd.DataFrame(ctx_novas, index=base_ctx.index)], axis=1)

            dims_ok = [c for c in dims_ctx
                       if base_ctx[c].notna().sum() >= 30 and base_ctx[c].nunique(dropna=True) >= 2]

            if not dims_ok:
                st.info("Nenhuma variável contextual com variabilidade suficiente neste recorte. "
                        "Isso é esperado quando a análise está restrita a uma única IES/curso.")
            else:
                dim_sel = st.selectbox(
                    "Dimensão contextual:", dims_ok,
                    format_func=lambda c: rotulos_ctx.get(c, c), key="sim_ctx_dim")
                col_dim = rotulos_ctx.get(dim_sel, dim_sel)

                sub_ctx = base_ctx[[dim_sel]].copy()
                sub_ctx["_y"] = y_ctx.values
                sub_ctx = sub_ctx.dropna(subset=[dim_sel, "_y"])
                # Só categorias com n >= 30 para evitar taxas instáveis.
                contagens = sub_ctx[dim_sel].value_counts()
                validas = contagens[contagens >= 30].index
                sub_ctx = sub_ctx[sub_ctx[dim_sel].isin(validas)]

                if len(sub_ctx) < 30 or sub_ctx["_y"].nunique() < 2:
                    st.info("Amostra insuficiente por categoria (mínimo de 30 alunos por categoria) para esta dimensão.")
                else:
                    taxa_global_ctx = float(sub_ctx["_y"].mean() * 100)
                    grp_ctx = sub_ctx.groupby(dim_sel, observed=True)["_y"].agg(n="count", taxa="mean")
                    grp_ctx["taxa_%"] = grp_ctx["taxa"] * 100.0
                    grp_ctx["delta_p.p."] = grp_ctx["taxa_%"] - taxa_global_ctx
                    grp_ctx = grp_ctx.drop(columns=["taxa"]).sort_values("taxa_%", ascending=False)
                    ref_cat = grp_ctx["n"].idxmax()

                    # Modelo logístico com a dimensão selecionada (g-computation por categoria).
                    ajustado = {}
                    try:
                        from sklearn.linear_model import LogisticRegression
                        from sklearn.pipeline import Pipeline
                        from sklearn.preprocessing import OneHotEncoder
                        pipe_ctx = Pipeline([
                            ("oh", OneHotEncoder(handle_unknown="ignore", sparse_output=False,
                                                 drop=[str(ref_cat)])),
                            ("lr", LogisticRegression(max_iter=5000, C=1e6)),
                        ])
                        pipe_ctx.fit(sub_ctx[[dim_sel]].astype(str), sub_ctx["_y"].astype(int))
                        for cat in grp_ctx.index:
                            Xc = pd.DataFrame({dim_sel: [str(cat)]})
                            ajustado[str(cat)] = float(pipe_ctx.predict_proba(Xc)[0, 1] * 100)
                    except Exception:
                        ajustado = {}

                    tab_ctx = grp_ctx.reset_index().rename(columns={dim_sel: col_dim})
                    if ajustado:
                        tab_ctx["ajustado_%"] = [ajustado.get(str(c), np.nan) for c in grp_ctx.index]
                        ref_aj = ajustado.get(str(ref_cat), np.nan)
                        tab_ctx["delta_ajustado_p.p."] = tab_ctx["ajustado_%"] - ref_aj
                    for c in ["taxa_%", "delta_p.p.", "ajustado_%", "delta_ajustado_p.p."]:
                        if c in tab_ctx.columns:
                            tab_ctx[c] = tab_ctx[c].round(1)

                    st.dataframe(tab_ctx, use_container_width=True, hide_index=True)

                    fig_ctx = px.bar(
                        tab_ctx, x=col_dim, y="taxa_%", text="taxa_%",
                        color="delta_p.p.", color_continuous_scale="RdYlGn",
                        title=f"Taxa de excelência por {col_dim.lower()}")
                    fig_ctx.add_hline(y=taxa_global_ctx, line_dash="dash",
                                      annotation_text=f"Média do recorte: {taxa_global_ctx:.1f}%")
                    fig_ctx.update_layout(
                        yaxis_title="Taxa de excelência (%)", yaxis=dict(range=[0, 100]), height=400,
                        coloraxis_colorbar=dict(title="Δ p.p."))
                    st.plotly_chart(fig_ctx, use_container_width=True)

                    if ajustado:
                        st.caption(
                            f"Taxa global do recorte: **{taxa_global_ctx:.1f}%**. Categoria de referência do modelo: "
                            f"**{ref_cat}** (maior n). A coluna 'ajustado' vem de regressão logística saturada nesta "
                            "dimensão; ela reproduz a taxa observada (com leve suavização) e serve como conferência — "
                            "leia como descrição, não como efeito causal.")
                    else:
                        st.caption(f"Taxa global do recorte: **{taxa_global_ctx:.1f}%**.")
                    st.info("Estas variáveis **não** são somadas ao escore de intervenção curricular. "
                            "Elas contextualizam o cenário e ajudam a priorizar políticas de equidade.")



# --- TAB 11: ESTUDO DE CASO (O PARADOXO) ---
elif aba == ABAS[11]:
    st.header("Estudo de Caso: O Paradoxo das Medias")
    st.markdown("""
    Este modulo demonstra como a **Media Global (Visao Tradicional)** pode mascarar perfis de
    proficiencia latente completamente antagonicos revelados pela **Matriz-Q (Visao Nova)**.
    Dados do EDA benchmark ou do curso selecionado.
    """)

    eda_bench = PASTA_EDA / "eda_3_benchmark_cursos.csv"
    if eda_bench.exists():
        df_bench = _ler(eda_bench)
        if df_bench is not None:
            st.subheader("Benchmark de Cursos (Dados EDA)")
            st.dataframe(df_bench.head(20), use_container_width=True)
            st.caption(f"Fonte: {eda_bench.name} | {len(df_bench)} registros.")
    elif df_curso is not None and not df_curso.empty:
        st.subheader(f"Dados do Curso: {nome_curso}")
        st.dataframe(df_curso.head(20), use_container_width=True)
        st.caption(f"Total: {len(df_curso)} registros.")
    else:
        st.info("Nenhum dado de benchmark disponivel. Selecione um curso no painel lateral.")

    if df_curso is not None and not df_curso.empty and "NT_GER" in df_curso.columns:
        st.markdown("---")
        st.subheader("Demonstracao do Paradoxo")
        st.markdown("Selecione dois alunos com medias proximas e compare seus perfis.")
        colunas_ignoradas = ['ALUNO', 'CO_CURSO', 'NOME_CURSO', 'CO_IES', 'CO_GRUPO', 'CO_REGIAO_CURSO',
                             'TP_SEXO', 'NU_IDADE', 'NT_CE', 'NT_DIS_CE', 'NT_FG', 'NT_BASE']
        habilidades = [c for c in df_curso.columns if c not in colunas_ignoradas and c != "NT_GER"]

        if len(habilidades) >= 3 and len(df_curso) >= 2:
            c_sel1, c_sel2 = st.columns(2)
            indices_disponiveis = list(range(min(len(df_curso), 100)))
            with c_sel1:
                idx1 = st.selectbox("Aluno 1 (indice):", indices_disponiveis, index=0, key="ec1")
            with c_sel2:
                idx2 = st.selectbox("Aluno 2 (indice):", indices_disponiveis, index=min(1, len(indices_disponiveis)-1), key="ec2")

            d1 = df_curso.iloc[idx1]
            d2 = df_curso.iloc[idx2]
            nota1 = float(d1.get("NT_GER", 0) or 0)
            nota2 = float(d2.get("NT_GER", 0) or 0)

            c_a, c_b = st.columns(2)
            with c_a:
                st.metric(f"Aluno 1 (idx {idx1})", f"{nota1:.2f}")
            with c_b:
                st.metric(f"Aluno 2 (idx {idx2})", f"{nota2:.2f}")

            st.info(f"Diferenca de media: **{abs(nota1 - nota2):.2f}** pontos. Porem, seus perfis de dominio podem ser completamente opostos.")

            hab_num = [h for h in habilidades if pd.to_numeric(d1.get(h), errors='coerce') is not np.nan or pd.to_numeric(d2.get(h), errors='coerce') is not np.nan][:8]
            if hab_num:
                vals1 = [float(pd.to_numeric(d1.get(h, 0), errors='coerce') or 0) for h in hab_num]
                vals2 = [float(pd.to_numeric(d2.get(h, 0), errors='coerce') or 0) for h in hab_num]
                theta = hab_num + [hab_num[0]]
                fig_radar = go.Figure()
                fig_radar.add_trace(go.Scatterpolar(r=vals1 + [vals1[0]], theta=theta, fill='toself', name=f'Aluno {idx1}', line_color='#1f77b4'))
                fig_radar.add_trace(go.Scatterpolar(r=vals2 + [vals2[0]], theta=theta, fill='toself', name=f'Aluno {idx2}', line_color='#ff7f0e'))
                fig_radar.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 100])), showlegend=True, height=450)
                st.plotly_chart(fig_radar, use_container_width=True)
                st.caption("Radar comparativo. Apesar de medias proximas, os perfis de dominio por disciplina podem ser radicalmente diferentes -- eis o paradoxo.")

                pior1 = hab_num[np.argmin(vals1)]
                pior2 = hab_num[np.argmin(vals2)]
                st.warning(f"**Gargalo Aluno 1:** {pior1} ({min(vals1):.1f} pts). "
                           f"**Gargalo Aluno 2:** {pior2} ({min(vals2):.1f} pts). "
                           f"Intervencoes genericas seriam ineficazes -- cada aluno precisa de uma trilha personalizada.")
        else:
            st.info("Dados insuficientes para demonstracao do paradoxo.")
    else:
        st.info("Selecione um curso com nota geral (NT_GER) para demonstrar o paradoxo.")

    if df_curso is not None and not df_curso.empty and "NT_GER" in df_curso.columns:
        st.markdown("---")
        st.subheader("Cenario Aritmetico de Intervencao (nao e projecao de modelo)")
        st.markdown("""
        **Correcao metodologica (15/11/2026):** este bloco antes se chamava
        "Impacto XGBoost" e aplicava um ganho fixo de 16 pontos percentuais, sem
        modelo que sustentasse esse numero. Nao existe modelo treinado que ligue
        "fases de Sensemaking" a nota. O que se segue e um **exercicio aritmetico
        declarado**: o usuario escolhe quantos pontos percentuais deseja supor e o
        painel apenas soma esse valor a taxa observada.
        """)
        taxa_excelencia_base = round((df_curso["NT_GER"].dropna() >= 60).mean() * 100, 1)
        melhoria = st.slider("Hipotese de ganho na taxa de sucesso do curso (p.p.):", 0, 100, 20, format="%d%%", key="slider_sensemaking")
        ganho_hipotetico = float(melhoria)
        nova_taxa = min(100.0, taxa_excelencia_base + ganho_hipotetico)
        m1, m2 = st.columns(2)
        m1.metric("Taxa Atual de Excelencia (observada)", f"{taxa_excelencia_base}%")
        m2.metric("Cenario (taxa observada + hipotese)", f"{nova_taxa:.1f}%",
                  f"+{ganho_hipotetico:.1f} p.p. (hipotese do usuario)")
        st.caption("Sem modelo causal ou preditivo: o numero da direita e apenas a taxa observada "
                   "somada a hipotese declarada no controle acima. Para estimativa real seria "
                   "necessario desenho quase-experimental com grupo de comparacao.")


# --- TAB 12: SUPORTE A DECISAO PEDAGOGICA ---
elif aba == ABAS[12]:
    st.header("Suporte a Tomada de Decisao Pedagogica")
    st.markdown("""
    Motor de **prescricao automatizada via IA** e **consulta livre** do coordenador.
    Selecione uma questao critica e gere diretrizes de acao com o OpenCode, ou faca perguntas
    livres com contexto dos dados do curso.
    """)

    server_online = servidor_opencode_ativo()
    status_color = "🟢" if server_online else "🔴"
    status_text = "Online" if server_online else "Offline"
    rate_info = _check_zen_rate_limit() if server_online else {"limited": False}
    if rate_info.get("limited"):
        reset_at = rate_info.get("reset_at", "desconhecido")
        st.error(f"**Limite de uso gratuito Zen excedido** -- Reset para **{reset_at}**.")
        status_text += " (limite excedido)"
    st.caption(f"{status_color} Servidor OpenCode: {status_text} -- {OPENCODE_SERVER_URL}")

    if df_curso is None or (hasattr(df_curso, 'empty') and df_curso.empty):
        st.warning("Selecione uma IES e Curso no filtro lateral.")
    else:
        st.subheader("1. Selecao Cirurgica de Itens Criticos")
        st.markdown("Mergulho analitico na nuance do erro por questao, com prescricao automatizada via IA.")
        df_a_sup = _carregar_analise_ies(_extrair_ano_filtro(sel_tipo, sel_id))
        df_drill_down = pd.DataFrame()
        if df_a_sup is not None and not df_a_sup.empty:
            df_filt_sup = _obter_filtro_analise(df_a_sup)
            if not df_filt_sup.empty:
                df_drill_down = _medias_por_questao_analise(df_filt_sup)
            else:
                st.info("Nenhum dado de analise por questao disponivel para o curso/IES selecionado.")
        if not df_drill_down.empty and "QUESTAO" in df_drill_down.columns and "TAXA_DEFICIENCIA_%" in df_drill_down.columns:
            colunas_oc_sup = [c for c in df_drill_down.columns if c.startswith("OC")]

            def _unir_ocs_sup(row):
                ocs = []
                for col in colunas_oc_sup:
                    valor = row.get(col)
                    if valor is not None and str(valor).strip().lower() not in ("nan", "", "none"):
                        texto = _oc_sem_prefixo(valor)
                        if texto and texto not in ocs:
                            ocs.append(texto)
                return ", ".join(ocs) if ocs else "Nenhuma OC vinculada"

            df_drill_down["MATERIAS_OCS"] = df_drill_down.apply(_unir_ocs_sup, axis=1)
            questoes_ordenadas = df_drill_down.sort_values("TAXA_DEFICIENCIA_%", ascending=False)["QUESTAO"].tolist()
            questao_foco = st.selectbox("Selecione a Questao-Alvo para Intervencao:", questoes_ordenadas, key="sb_questao_foco")
            dados_questao = df_drill_down[df_drill_down["QUESTAO"] == questao_foco].iloc[0]
            erro_foco = dados_questao["TAXA_DEFICIENCIA_%"]
            ocs_foco = dados_questao["MATERIAS_OCS"]
            competencias_foco = dados_questao.get("COMPETENCIAS", "Nao parametrizada nesta matriz")
            st.info(f"""
            **Raio-X Diagnostico -- Questao {questao_foco}**
            * **Indice de Deficiencia (Erro da Turma):** {erro_foco:.1f}%
            * **Objetos de Conhecimento Vinculados:** {ocs_foco}
            * **Matriz de Competencias Requeridas:** {competencias_foco}
            """)

            st.subheader("2. Motor de Prescricao Pedagogica Ativa (por Questao)")
            modelo_prescricao_q = st.selectbox("Escolha o Motor Cognitivo:", options=list(MODELOS_OPENCODE.keys()),
                                               format_func=lambda x: MODELOS_OPENCODE[x], index=0, key="sb_modelo_prescricao_q")
            if st.button(f"Gerar Diretriz de Acao para Questao {questao_foco}", type="primary", use_container_width=True):
                if not server_online:
                    st.warning("Servidor OpenCode nao esta ativo. Inicie-o no topo desta pagina.")
                else:
                    prompt_estrito = f"""
                    Aja estritamente como um Consultor Pedagogico de Ensino Superior especialista na matriz de avaliacao do ENADE.
                    CONTEXTO: IES: {ies_sel} | Curso: {nome_curso} | Exame: {sel_label}
                    QUESTAO: {questao_foco} | Erro Turma: {erro_foco:.1f}% | OCs: {ocs_foco} | Competencias: {competencias_foco}
                    TAREFA: Forneca EXATAMENTE UMA (1) acao pedagogica concreta e imediata para o Coordenador adotar com os professores.
                    Ignore introducoes. Va direto para a recomendacao em Markdown.
                    """
                    with st.spinner("Processando evidencias com OpenCode..."):
                        resposta_servidor = enviar_prompt_opencode(prompt_estrito, model_id=modelo_prescricao_q, timeout=120)
                        if resposta_servidor["success"]:
                            texto_acao = resposta_servidor["response"]
                            st.success("Plano de Intervencao Concluido!")
                            st.markdown("---")
                            st.markdown(texto_acao)
                            st.markdown("---")
                            st.download_button(label="Exportar Plano de Acao para o NDE (TXT)",
                                               data=f"PLANO DE ACAO - IES: {ies_sel} | CURSO: {nome_curso}\nQUESTAO: {questao_foco}\n\n{texto_acao}",
                                               file_name=f"Plano_Acao_Q{questao_foco}_{_norm(nome_curso)}.txt",
                                               mime="text/plain", use_container_width=True)
                        else:
                            st.error(f"Falha na comunicacao com o motor OpenCode: {resposta_servidor.get('error', '')}")
            st.markdown("---")
        else:
            st.info("Dados de analise por questao indisponiveis para o curso/IES selecionado. "
                    "Disponivel quando houver arquivos analise_por_questao_ies_*.csv em dados/processados/.")

        st.subheader("3. Prescricao Pedagogica para Questoes Criticas (prompt livre do curso)")
        st.markdown("Selecione uma questao e gere diretrizes de acao para o NDE.")
        modelo_prescricao = st.selectbox("Modelo IA:", options=list(MODELOS_OPENCODE.keys()),
                                          format_func=lambda x: MODELOS_OPENCODE[x], index=0, key="sb_modelo_prescricao")

        if not server_online:
            if st.button("Iniciar Servidor OpenCode", key="btn_start_prescricao"):
                with st.spinner("Iniciando servidor..."):
                    if iniciar_servidor_opencode():
                        st.success("Servidor iniciado!")
                        st.rerun()
                    else:
                        st.error("Falha ao iniciar.")

        prompt_livre = st.text_area("Prompt personalizado para o curso:",
                                     placeholder=f"Ex: Quais sao as principais deficiencias do curso {nome_curso} e como melhora-las?",
                                     key="prompt_prescricao")

        if st.button("Gerar Prescricao com IA", type="primary", use_container_width=True, disabled=not server_online):
            if prompt_livre.strip():
                prompt_completo = f"""Voce e um consultor pedagogico especialista no ENADE.
CONTEXTO: Curso: {nome_curso} | IES: {ies_sel or 'N/A'} | Exame: {sel_label}
Dados: {len(df_curso)} alunos no curso selecionado.
TAREFA: Responda de forma clara, estruturada e didatica.
PERGUNTA: {prompt_livre}"""
                with st.spinner("Processando com OpenCode..."):
                    resultado = enviar_prompt_opencode(prompt_completo, model_id=modelo_prescricao, timeout=300)
                    if resultado["success"]:
                        st.success("Prescricao gerada!")
                        st.markdown("---")
                        st.markdown(resultado["response"])
                        st.download_button(label="Exportar Prescricao (.txt)",
                                           data=resultado["response"].encode("utf-8"),
                                           file_name=f"prescricao_{nome_curso}.txt",
                                           mime="text/plain", use_container_width=True)
                    else:
                        error_msg = resultado.get("error", "Erro desconhecido")
                        st.error(f"Erro: {error_msg}")
                        st.markdown("### Analise Manual (fallback)")
                        st.markdown(f"**Curso:** {nome_curso}")
                        if "NT_GER" in df_curso.columns:
                            st.markdown(f"- Media Nacional: {df_nacional['NT_GER'].mean():.2f}" if df_nacional is not None and 'NT_GER' in df_nacional.columns else "")
                            st.markdown(f"- Media IES: {df_curso['NT_GER'].mean():.2f}")
            else:
                st.warning("Digite uma pergunta ou instrucao antes de enviar.")

        st.markdown("---")
        st.subheader("4. Consulta Livre do Coordenador")
        st.markdown("Monte o contexto e faca qualquer pergunta sobre os dados do curso.")
        col1, col2, col3 = st.columns(3)
        with col1:
            incluir_ies = st.checkbox("Dados Gerais do Curso", value=True, key="ctx_ies")
        with col2:
            incluir_nacional = st.checkbox("Comparativo Nacional", value=False, key="ctx_nac")
        with col3:
            incluir_fg = st.checkbox("Questoes FG vs CE", value=False, key="ctx_fg")

        pergunta_livre = st.text_area("Digite sua pergunta:", placeholder="Ex: Em quais questoes estamos com desempenho critico?", key="txt_pergunta_livre")

        if st.button("Enviar Pergunta", key="btn_livre"):
            if not pergunta_livre.strip():
                st.warning("Digite uma pergunta antes de enviar.")
            else:
                with st.spinner("Construindo contexto..."):
                    contexto = ""
                    if incluir_ies and "NT_GER" in df_curso.columns:
                        media_ies_val = df_curso["NT_GER"].mean()
                        contexto += f"\n[DADOS DA IES] Media geral do curso: {media_ies_val:.2f}\n"
                    if incluir_nacional and df_nacional is not None and "NT_GER" in df_nacional.columns:
                        media_nac_val = df_nacional["NT_GER"].mean()
                        contexto += f"[DADOS NACIONAIS] Media nacional do curso: {media_nac_val:.2f}\n"
                    if incluir_fg:
                        fg_cols = [c for c in df_curso.columns if "FG" in c.upper()]
                        ce_cols = [c for c in df_curso.columns if "CE" in c.upper()]
                        if fg_cols:
                            fg_media = df_curso[fg_cols].mean().mean()
                            contexto += f"[FG] Media Formacao Geral: {fg_media:.2f}\n"
                        if ce_cols:
                            ce_media = df_curso[ce_cols].mean().mean()
                            contexto += f"[CE] Media Formacao Especifica: {ce_media:.2f}\n"
                    if not contexto:
                        contexto = "\n[AVISO] Nenhum contexto selecionado. Responda apenas com base na pergunta.\n"

                    prompt_final = f"""Voce e um consultor academico especialista em dados educacionais.
CONTEXTO SELECIONADO: {contexto}
PERGUNTA: {pergunta_livre}
Responda de forma clara e estruturada."""

                    resposta = enviar_prompt_opencode(prompt_final, model_id=modelo_prescricao, timeout=120)
                    if resposta["success"]:
                        st.info("**Resposta da IA:**")
                        st.markdown(resposta["response"])
                    else:
                        st.error(f"Erro: {resposta.get('error', 'Erro desconhecido')}")

        st.markdown("---")
        st.markdown("### 5. Analise de Esforco vs. Competencia (IRT / Padrao de Resposta)")
        st.info("""
        **Atendendo a recomendacao metodologica:** diferenciamos a verdadeira lacuna de aprendizado do
        comportamento de baixo engajamento (ex.: respostas muito rapidas ou padrao de "chute").
        """)
        # CORRECAO (15/11/2026): esta secao exibia um grafico gerado com np.random
        # ("dados simulados ilustrativos"). Passou a ler o ajuste IRT real do curso.
        from dashboard.abas.aba_qualidade import render_irt
        render_irt(EDICAO_MOTORES, globals().get("chave_curso"))
        st.markdown("""
        **Interpretacao dos Quadrantes:**
        * **Alto Esforco / Baixa Competencia:** foco prioritario de tutoria. O aluno tenta, mas possui deficiencias reais.
        * **Baixo Esforco / Baixa Competencia:** risco de evasao ou desengajamento. A nota baixa nao reflete necessariamente o limite cognitivo.
        """)

        st.markdown("### 6. Metrica de Lacunas Corrigida (Evitando Efeito Zero-Sum)")
        st.markdown("""
        Para evitar que superavits em certas competencias mascarem deficits em outras (efeito *zero-sum*),
        a metrica de *Gap* Pedagogico foi reescrita utilizando o Valor Absoluto e a penalizacao quadratica
        para desvios extremos.
        """)
        st.latex(r"Gap_{corrigido} = \sqrt{\frac{1}{N} \sum_{i=1}^{N} \max(0, Meta_i - Desempenho_i)^2}")
        st.code("""
        # Correcao do Gap (Python)
        # Evita que um aluno com +20 numa area anule -20 de outra area na media da turma
        def calcular_gap_corrigido(desempenho, meta):
            # Considera apenas o gap negativo (onde o desempenho e menor que a meta)
            deficits = np.maximum(0, meta - desempenho)
            # Aplica RMSE apenas sobre os deficits
            return np.sqrt(np.mean(deficits ** 2))
        """, language="python")

        st.markdown("### 7. Criterios de Selecao de Classes Latentes (LCA)")
        st.warning("""
        **Nota de correcao:** a tabela que constava aqui era **ilustrativa** (valores digitados a mao,
        nao provenientes de um ajuste real) e foi removida. Abaixo, os **criterios reais de selecao de `k`**
        lidos do arquivo `03_criterios_de_selecao_k.csv` gerado pelo motor LCA.
        """)
        _cands_lca = [
            PASTA_MODELOS / "lca" / "03_criterios_de_selecao_k.csv",
            RAIZ_PROJETO / "modelos" / "lca" / "03_criterios_de_selecao_k.csv",
            RAIZ_PROJETO.parent / "modelos" / "lca" / "03_criterios_de_selecao_k.csv",
        ]
        _caminho_lca = next((p for p in _cands_lca if p.exists()), None)
        if _caminho_lca is None:
            st.info("Arquivo `03_criterios_de_selecao_k.csv` nao encontrado. Nenhuma tabela e exibida "
                    "para evitar valores nao verificaveis.")
        else:
            _df_lca = pd.read_csv(_caminho_lca, sep=";", encoding="utf-8-sig")
            for _c in ("k", "bic", "aic", "entropia", "menor_classe_pct"):
                if _c in _df_lca.columns:
                    _df_lca[_c] = pd.to_numeric(_df_lca[_c], errors="coerce")
            _df_lca = _df_lca.dropna(subset=["k", "bic"])
            _df_lca["k"] = _df_lca["k"].astype(int)
            _aggs = {
                "n_modelos": ("bic", "size"),
                "bic_medio": ("bic", "mean"),
                "bic_minimo": ("bic", "min"),
                "entropia_media": ("entropia", "mean"),
                "menor_classe_media": ("menor_classe_pct", "mean"),
            }
            if "aic" in _df_lca.columns:
                _aggs["aic_medio"] = ("aic", "mean")
            _agregado = _df_lca.groupby("k").agg(**_aggs).reset_index()
            _cols_exib = [c for c in ["k", "n_modelos", "bic_medio", "bic_minimo", "aic_medio",
                                      "entropia_media", "menor_classe_media"] if c in _agregado.columns]
            _sub_min = [c for c in ["bic_medio", "bic_minimo", "aic_medio"] if c in _agregado.columns]
            _sub_max = [c for c in ["entropia_media"] if c in _agregado.columns]
            st.dataframe(
                _agregado[_cols_exib].set_index("k").round(4)
                    .style.highlight_min(subset=_sub_min, color="lightgreen")
                    .highlight_max(subset=_sub_max, color="lightblue"),
                use_container_width=True)
            _k_bic = int(_agregado.loc[_agregado["bic_medio"].idxmin(), "k"])
            _k_ent = int(_agregado.loc[_agregado["entropia_media"].idxmax(), "k"])
            st.markdown(
                f"> **Leitura dos dados reais:** menor BIC medio em **k = {_k_bic}**; maior entropia media em "
                f"**k = {_k_ent}** ({len(_df_lca)} ajustes). O `k` otimo **varia por curso e IES** — "
                "nao ha um valor unico imposto para toda a base.")
            st.caption(f"Fonte: `{_caminho_lca.name}` (dados reais do motor LCA). "
                       "A tabela anterior era ilustrativa e foi removida.")

        st.markdown("### 8. Transparencia da IA: configuracao real do stack")
        st.markdown("""
        Configuracao **efetiva** do stack de IA explicativa do PRISM-EDU, lida de `config.py`:
        servidor **OpenCode local** com modelos remotos. Nada de pseudo-codigo ilustrativo -- apenas
        o que o projeto realmente executa.
        """)
        from algoritmos.opencode.config_ia import resumo_config, status_servidor
        _cfg_ia = resumo_config()
        _st_ia = status_servidor()
        _cor = "🟢" if _st_ia["ativo"] else "🔴"
        st.caption(f"{_cor} Servidor: **{_st_ia['url']}** ({_st_ia['detalhe']}) | "
                   f"Auth: usuario `{_cfg_ia['usuario_auth']}`")
        st.markdown("**Modelos disponiveis no projeto:**")
        st.dataframe(
            pd.DataFrame(_cfg_ia["modelos"], columns=["ID do modelo", "Rotulo"]),
            use_container_width=True)
        with st.expander("Politica de grounding aplicada pelos prompts", expanded=False):
            for _regra in _cfg_ia["politica_grounding"]:
                st.markdown(f"- {_regra}")
        st.caption("Fonte: `config.py` (MODELOS_OPENCODE, OPENCODE_SERVER_URL) e "
                   "`algoritmos/opencode/config_ia.py`. Consulte a aba 'OpenCode + IA Explicativa' "
                   "para executar inferencias.")


# --- TAB 13: SERIES TEMPORAIS (2004-2023) ---
elif aba == ABAS[13]:
    st.header("Series Temporais ENADE (2004-2023)")
    st.markdown("""
    **Analise longitudinal** da evolucao do ENADE ao longo dos anos. Permite observar tendencias de crescimento
    do numero de alunos, IES participantes e evolucao das medias por curso e regiao. Dados de 2004 a 2023
    (excluindo 2020, ano sem aplicacao do ENADE devido a pandemia).
    """)
    if not PASTA_ENADE_EXT.exists():
        st.info("Pasta ENADE nao encontrada.")
    else:
        anos = []
        for p in sorted(PASTA_ENADE_EXT.glob("relatorio_final_enade_*.csv")):
            try:
                anos.append(int(p.stem.split("_")[-1]))
            except (ValueError, IndexError):
                pass
        if not anos:
            st.info("Nenhum arquivo ENADE encontrado.")
        else:
            regs = []
            for a in sorted(anos):
                da = _carregar_enade(a)
                if da is not None:
                    regs.append({
                        "Ano": a, "Alunos": len(da),
                        "IES": da["CO_IES"].nunique() if "CO_IES" in da.columns else 0,
                        "Cursos": da["CO_GRUPO"].nunique() if "CO_GRUPO" in da.columns else 0,
                    })
            dft = pd.DataFrame(regs)
            c1, c2 = st.columns(2)
            with c1:
                st.plotly_chart(
                    px.line(dft, x="Ano", y="Alunos", markers=True,
                            title="Evolucao do Numero de Alunos Participantes").update_traces(line_width=3),
                    use_container_width=True)
                st.caption("O pico de participantes reflete a expansao do ensino superior brasileiro. "
                           "A queda em 2021-2022 pode estar associada a sequencia da pandemia.")
            with c2:
                st.plotly_chart(
                    px.line(dft, x="Ano", y="IES", markers=True,
                            title="Evolucao do Numero de IES Participantes"),
                    use_container_width=True)
                st.caption("O numero de IES reflete a abrangencia da avaliacao. "
                           "Um aumento indica maior representatividade da amostra.")
            st.subheader("Top 10 Cursos ao Longo dos Anos")
            dc = []
            for a in sorted(anos):
                da = _carregar_enade(a)
                if da is not None and "CO_GRUPO" in da.columns:
                    for cg, cnt in da["CO_GRUPO"].value_counts().items():
                        nm = _nome_grupo(cg, a)
                        dc.append({"Ano": a, "Curso": nm, "N": cnt})
            if dc:
                dfc = pd.DataFrame(dc)
                top10 = dfc.groupby("Curso")["N"].sum().nlargest(10).index
                st.plotly_chart(
                    px.line(dfc[dfc["Curso"].isin(top10)], x="Ano", y="N", color="Curso",
                            title="Evolucao dos 10 Cursos com Mais Participantes"),
                    use_container_width=True)
                st.caption("Cursos com mais participantes dominam a composicao da amostra.")
            st.subheader("Distribuicao por Regiao ao Longo dos Anos")
            dr = []
            rmap = {1: "Norte", 2: "Nordeste", 3: "Sudeste", 4: "Sul", 5: "Centro-Oeste"}
            for a in sorted(anos):
                da = _carregar_enade(a)
                if da is not None and "CO_REGIAO_CURSO" in da.columns:
                    for r, cnt in da["CO_REGIAO_CURSO"].value_counts().items():
                        dr.append({"Ano": a, "Regiao": rmap.get(int(r), str(r)), "N": cnt})
            if dr:
                dfr = pd.DataFrame(dr)
                st.plotly_chart(
                    px.area(dfr, x="Ano", y="N", color="Regiao",
                            title="Evolucao Regional dos Participantes"),
                    use_container_width=True)
                st.caption("A regiao Sudeste historicamente concentra o maior numero de participantes.")

            st.subheader("Serie por Disciplina: Taxa de Deficiencia por Questao")
            st.markdown("""
            **Analise por disciplina** usando os mesmos indicadores da aba Diagnostico (taxa de deficiencia media
            das questoes) para todas as edicoes ENADE 2004-2023 ja processadas. Permite comparar a evolucao da
            qualidade do ensino por area do conhecimento.
            """)
            disp_cols = {"Ano": [], "Disciplina": [], "Taxa_Deficiencia_%": [], "N_Questoes": [], "N_Registros": []}
            anos_disp = []
            for p in sorted(PASTA_EDA.glob("analise_por_questao_ies_enade_*.csv")):
                try:
                    anos_disp.append(int(p.stem.split("_")[-1]))
                except (ValueError, IndexError):
                    pass
            for a in sorted(anos_disp):
                daq = _carregar_analise_ies(a)
                if daq is None or daq.empty or "CO_GRUPO" not in daq.columns:
                    continue
                for cg, grp in daq.groupby("CO_GRUPO"):
                    disp_cols["Ano"].append(a)
                    disp_cols["Disciplina"].append(_nome_grupo(cg, a))
                    disp_cols["Taxa_Deficiencia_%"].append(round(grp["TAXA_DEFICIENCIA_%"].mean(), 2) if "TAXA_DEFICIENCIA_%" in grp.columns else np.nan)
                    disp_cols["N_Questoes"].append(grp["QUESTAO"].nunique() if "QUESTAO" in grp.columns else 0)
                    disp_cols["N_Registros"].append(len(grp))
            if disp_cols["Ano"]:
                df_disp = pd.DataFrame(disp_cols)
                disp_opts = sorted(df_disp["Disciplina"].unique())

                st.markdown("**Matriz de Cobertura - Disciplina x Ano**")
                st.markdown(
                    "Indica em quais edicoes ENADE cada disciplina tem analise de questoes processada "
                    "(regiao ativa). Permite identificar lacunas longitudinais por area.")
                cov_pivot = df_disp.pivot_table(
                    index="Disciplina", columns="Ano", values="Taxa_Deficiencia_%",
                    aggfunc="first")
                cov = cov_pivot.notna()
                fig_cov = px.imshow(
                    cov.astype(int),
                    color_continuous_scale=["#f0f0f0", "#2563eb"],
                    zmin=0, zmax=1,
                    title="Cobertura de Analise por Disciplina e Ano",
                    aspect="auto")
                fig_cov.update_coloraxes(showscale=False)
                fig_cov.update_layout(height=650)
                st.plotly_chart(fig_cov, use_container_width=True)

                sel_disp = st.multiselect(
                    "Disciplinas (max 6):", disp_opts,
                    default=disp_opts[:3], max_selections=6, key="sel_disp")
                if sel_disp:
                    df_disp_f = df_disp[df_disp["Disciplina"].isin(sel_disp)]
                    st.plotly_chart(
                        px.line(df_disp_f, x="Ano", y="Taxa_Deficiencia_%", color="Disciplina",
                                markers=True,
                                title="Evolucao da Taxa de Deficiencia por Disciplina"),
                        use_container_width=True)
                    st.caption("Queda da taxa indica melhora do desempenho nas questoes da area.")
                    st.dataframe(
                        df_disp_f.pivot_table(index="Disciplina", columns="Ano",
                                              values="Taxa_Deficiencia_%", aggfunc="first"),
                        use_container_width=True)
                    if "N_Questoes" in df_disp_f.columns:
                        st.markdown("**Numero de questoes por Disciplina e Ano**")
                        st.caption("Cada edicao/curso tem um conjunto proprio de questoes; "
                                   "compare curvas de taxa somente dentro de cada disciplina.")
                        st.plotly_chart(
                            px.line(df_disp_f, x="Ano", y="N_Questoes", color="Disciplina",
                                    markers=True,
                                    title="Numero de Questoes Analisadas por Disciplina"),
                            use_container_width=True)
            else:
                st.info("Nenhum arquivo analise_por_questao_ies_enade_*.csv disponivel em dados/processados/.")

        st.markdown("---")
        st.subheader("Heatmap OC x Ano: mudanca do perfil de lacunas ao longo do tempo")
        st.markdown("""
        Distribuicao da **taxa de deficiencia media** (erros %) por Objeto de Conhecimento e por edicao.
        Apenas OCs presentes em **2 ou mais anos** sao exibidos (bases de conhecimento divergentes entre
        areas/edicoes sao omitidas). Quanto mais escura a celula, maior a lacuna naquele OC naquele ano.
        """)
        oc_regs = []
        for a in sorted(anos_disp):
            daq = _carregar_analise_ies(a)
            if daq is None or daq.empty or "TAXA_DEFICIENCIA_%" not in daq.columns:
                continue
            oc_col = next((c for c in daq.columns if str(c).startswith("OC")), None)
            if oc_col is None:
                continue
            sub = daq[["NU_ANO", oc_col, "TAXA_DEFICIENCIA_%"]].dropna(subset=[oc_col, "TAXA_DEFICIENCIA_%"])
            if sub.empty:
                continue
            sub = sub.copy()
            sub["Num_Ano"] = a
            sub["OC_norm"] = sub[oc_col].map(_norm_oc)
            sub["OC_label"] = sub[oc_col].map(lambda v: _curto(str(v), 52))
            sub = sub[["Num_Ano", "OC_norm", "OC_label", "TAXA_DEFICIENCIA_%"]]
            sub = sub[sub["OC_norm"] != ""]
            oc_regs.append(sub)
        if oc_regs:
            df_oc = pd.concat(oc_regs, ignore_index=True)
            coberta = df_oc.groupby("OC_norm")["Num_Ano"].nunique()
            ocs_validas = coberta[coberta >= 2].index
            df_oc_f = df_oc[df_oc["OC_norm"].isin(ocs_validas)].copy()
            df_oc_f["Ano_label"] = df_oc_f["Num_Ano"].astype(int)
            agg_oc = df_oc_f.groupby(["OC_label", "Ano_label"])["TAXA_DEFICIENCIA_%"].mean().reset_index()
            pivot_oc = agg_oc.pivot(index="OC_label", columns="Ano_label", values="TAXA_DEFICIENCIA_%")
            if not pivot_oc.empty:
                fig_oc_ano = go.Figure(go.Heatmap(
                    z=pivot_oc.values, x=[str(c) for c in pivot_oc.columns],
                    y=pivot_oc.index.tolist(),
                    colorscale="YlOrRd", zmin=0, zmax=100,
                    hovertemplate="OC: %{y}<br>Ano: %{x}<br>Deficiencia media: %{z:.1f}%<extra></extra>"))
                fig_oc_ano.update_layout(
                    title="Taxa de Deficiencia Media por OC e Ano",
                    height=max(420, 18 * len(pivot_oc)),
                    yaxis_title="Objeto de Conhecimento",
                    xaxis_title="Ano")
                st.plotly_chart(fig_oc_ano, use_container_width=True)
                st.caption("Subida do tom (escuridao) indica piora naquele OC ao longo dos ciclos.")
            else:
                st.info("Nenhum OC comum a 2 ou mais edicoes para o heatmap OC x Ano.")
        else:
            st.info("Sem dados de OC/taxa de deficiencia para o heatmap OC x Ano.")

        st.markdown("---")
        st.subheader("Comparativo ENADE 2023 x ENADE Licenciaturas 2025 por OC")
        st.markdown("""
        Taxa de deficiencia media dos Objetos de Conhecimento (mapeamento OC do INEP) nas duas fontes.
        Como cada instrumento tem seu proprio conjunto de OCs, o grafico exibe lado a lado os **top-15 OCs
        com maior lacuna** de cada aplicacao, permitindo ver onde a formacao docente (2025, baseline) mais
        precisa de reforco em relacao ao padrao ENADE 2023.
        """)
        df_e23 = _carregar_analise_ies(2023)
        df_l25 = _carregar_analise_ies(2025, "lic")
        if df_e23 is None or df_l25 is None:
            st.info("Fontes de OC (ENADE 2023 / Licenciaturas 2025) indisponiveis.")
        else:
            oc_cols23 = [c for c in df_e23.columns if str(c).startswith("OC")] or None
            oc_cols25 = [c for c in df_l25.columns if str(c).startswith("OC")] or None
            if not oc_cols23 or not oc_cols25:
                st.info("Colunas OC indisponiveis nas fontes.")
            else:
                linhas_oc = []
                for _, r23 in df_e23.iterrows():
                    oc23 = _norm_oc(str(r23.get(oc_cols23[0]) or ""))
                    if oc23:
                        linhas_oc.append({"OC_norm": oc23, "OC_label": _curto(str(r23.get(oc_cols23[0])), 52),
                                          "Fonte": "ENADE 2023",
                                          "Taxa": float(r23.get("TAXA_DEFICIENCIA_%") or 0)})
                for _, r25 in df_l25.iterrows():
                    oc25 = _norm_oc(str(r25.get(oc_cols25[0]) or ""))
                    if oc25:
                        linhas_oc.append({"OC_norm": oc25, "OC_label": _curto(str(r25.get(oc_cols25[0])), 52),
                                          "Fonte": "Licenciaturas 2025",
                                          "Taxa": float(r25.get("TAXA_DEFICIENCIA_%") or 0)})
                if linhas_oc:
                    df_oc2 = pd.DataFrame(linhas_oc)
                    top_por_fonte = (df_oc2.groupby(["Fonte", "OC_label"])["Taxa"].mean()
                                     .reset_index().sort_values("Taxa", ascending=False)
                                     .groupby("Fonte").head(15))
                    fig_c23 = go.Figure()
                    for fonte, cor in [("ENADE 2023", "#2980b9"), ("Licenciaturas 2025", "#e67e22")]:
                        sub = top_por_fonte[top_por_fonte["Fonte"] == fonte].sort_values("Taxa")
                        fig_c23.add_trace(go.Bar(
                            x=sub["Taxa"], y=sub["OC_label"], orientation="h",
                            name=fonte, marker_color=cor))
                    fig_c23.update_layout(barmode="group", height=max(420, 16 * 15),
                                          title="Top-15 OCs com Maior Lacuna por Fonte",
                                          yaxis_title="OC", xaxis_title="Erros %")
                    st.plotly_chart(fig_c23, use_container_width=True)
                    st.dataframe(
                        top_por_fonte.pivot_table(index="OC_label", columns="Fonte",
                                                  values="Taxa", aggfunc="mean")
                        .sort_values("ENADE 2023", ascending=False),
                        use_container_width=True)
                    st.caption("As bases de OC sao especificas de cada instrumento; "
                               "nao ha par 2023-2025 para o mesmo texto de OC.")
                else:
                    st.info("Sem dados de OC para o comparativo 2023 x 2025.")

        st.markdown("---")
        st.subheader("Series ENAMED e ENADE Licenciaturas (2025)")
        st.markdown("""
        Edicoes mais recentes dos exames complementares. Por enquanto ha apenas a aplicacao de **2025**,
        mas os mesmos indicadores das series ENADE (alunos, IES, cursos) sao apresentados abaixo para
        acompanhamento a partir da proxima edicao.
        """)
        linhas_extras = []
        for rotulo, fonte_path in [
            ("ENAMED 2025", PASTA_DADOS_PROCESSADOS / "enamed" / "relatorio_final_enamed_2025.csv"),
            ("ENADE Licenciaturas 2025", PASTA_DADOS_PROCESSADOS / "enadeLicenciaturas" / "relatorio_final_enade_licenciaturas_2025.csv"),
        ]:
            if fonte_path.exists():
                dx = pd.read_csv(fonte_path, sep=";", encoding="utf-8-sig", low_memory=False)
                ano_ex = int(dx["NU_ANO"].iloc[0]) if "NU_ANO" in dx.columns and dx["NU_ANO"].notna().any() else 2025
                linhas_extras.append({
                    "Fonte": rotulo, "Ano": ano_ex, "Alunos": len(dx),
                    "IES": dx["CO_IES"].nunique() if "CO_IES" in dx.columns else 0,
                    "Cursos": dx["CO_GRUPO"].nunique() if "CO_GRUPO" in dx.columns else 0,
                })
        if linhas_extras:
            df_extras = pd.DataFrame(linhas_extras)
            cols_extra = [c for c in ["Fonte", "Ano", "Alunos", "IES", "Cursos"] if c in df_extras.columns]
            st.dataframe(df_extras[cols_extra], use_container_width=True)
            if "IES" in df_extras.columns and len(df_extras) > 1:
                fig_extra = px.bar(df_extras, x="Fonte", y="Alunos", color="Fonte", text="Alunos",
                                   title="Participantes por Exame Complementar")
                fig_extra.update_traces(textposition="outside")
                fig_extra.update_layout(showlegend=False, height=320)
                st.plotly_chart(fig_extra, use_container_width=True)
        else:
            st.info("Arquivos de ENAMED / ENADE Licenciaturas nao encontrados em dados/processados/.")

        # ------------------------------------------------------------------
        # DRIFT TEMPORAL (artefatos gerados pelo motor 'drift'/CLI)
        # ------------------------------------------------------------------
        st.markdown("---")
        st.subheader("Drift Temporal por Objeto de Conhecimento (ciclo trienal)")
        st.markdown("""
        Comparacao da **proficiencia por OC** e das **notas** entre a edicao e a edicao anterior
        em que o **mesmo curso** foi avaliado (o ENADE avalia areas diferentes a cada ano, entao o
        par e sempre dentro do curso). Nunca compara colunas Q* cruas. Os resultados sao gerados por:
        `python executar_por_edicao.py --motores drift` ou
        `python processamento/analise_drift_temporal.py --modo consecutivas_tendencia`.
        """)
        pasta_drift = PASTA_MODELOS / "drift"
        caminho_resumo = pasta_drift / "resumo_temporal.csv"
        if not caminho_resumo.exists():
            st.info("Nenhum artefato de drift encontrado em modelos/drift/. Rode o motor 'drift' para gerar.")
        else:
            st.markdown("**Resumo por edicao/referencia**")
            st.dataframe(pd.read_csv(caminho_resumo, encoding="utf-8"), use_container_width=True)
            caminho_tend_oc = pasta_drift / "tendencia_status_oc.csv"
            caminho_tend_notas = pasta_drift / "tendencia_status_notas.csv"
            for caminho_t, rotulo_t, titulo_t in [
                (caminho_tend_oc, "OC", "Drift por OC nas edicoes (Status)"),
                (caminho_tend_notas, "notas", "Drift das notas (Status)"),
            ]:
                if not caminho_t.exists():
                    continue
                df_t = pd.read_csv(caminho_t, encoding="utf-8")
                st.markdown(f"**{titulo_t}**")
                st.dataframe(df_t, use_container_width=True)
                cols_par = [c for c in df_t.columns if " vs enade_" in c]
                if cols_par and len(df_t) > 0:
                    valores = df_t[cols_par].apply(
                        lambda col: col.astype(str).str.startswith("Drift").astype(int))
                    fig_drift = go.Figure(go.Heatmap(
                        z=valores.values, x=cols_par,
                        y=(df_t["Curso"].astype(str) + " | " + df_t["Variavel"].astype(str)).tolist(),
                        colorscale=[[0, "#2ca02c"], [1, "#d62728"]], zmin=0, zmax=1, showscale=False,
                        hovertemplate="%{y}<br>%{x}<br>Drift: %{z}<extra></extra>"))
                    fig_drift.update_layout(
                        height=max(380, 16 * len(df_t)), title=f"Mapa de drift ({rotulo_t}) — vermelho = drift",
                        xaxis_title="Par de edicoes", yaxis_title=f"{rotulo_t}")
                    st.plotly_chart(fig_drift, use_container_width=True)
            st.caption("Vermelho = deslocamento detectado (KS significativo / PSI). "
                       "A leitura e descritiva: indica mudanca de distribuicao entre edicoes, nao causalidade.")


# --- TAB 14: EXAMES INTERNACIONAIS ---
elif aba == ABAS[14]:
    st.header("Exames Internacionais")
    st.markdown("""
    Comparacao do ENADE com exames internacionais equivalentes. Cada aba apresenta o exame, seu pais de origem,
    as colunas esperadas nos dados e o status de integracao. **Dados reais** baixados das fontes oficiais ficam em
    `dados/internacionais/<sigla>/reais/`; os placeholders simulados permanecem e sao exibidos separadamente.
    Consulte `ORIGEM_DADOS.md` para a procedencia, links e citacoes.
    """)
    tabs_int = st.tabs([f"{v['sigla']} - {v['pais']}" for v in EXAMES_INTERNACIONAIS.values()])
    for i, (chave, info) in enumerate(EXAMES_INTERNACIONAIS.items()):
        with tabs_int[i]:
            c1, c2 = st.columns([1, 3])
            with c1:
                st.markdown(f"### {info['sigla']}")
                st.markdown(f"**{info['pais']}**")
                st.markdown(f"Status: `{info['status']}`")
                st.markdown(f"**Orgao:** {info.get('orgao', 'n/d')}")
                st.markdown(f"**Tipo de fonte:** {info.get('tipo_fonte', 'n/d')}")
            with c2:
                st.markdown(f"#### {info['nome']}")
                st.code(", ".join(info["colunas_esperadas"]))
                pasta_ex = PASTA_INTERNACIONAIS / info["sigla"].lower()
                pasta_reais = pasta_ex / "reais"
                csvs_reais = sorted(pasta_reais.glob("*.csv")) if pasta_reais.exists() else []
                docs_reais = sorted((pasta_reais / "documentos").glob("*")) if (pasta_reais / "documentos").exists() else []

                st.markdown("**Fontes oficiais**")
                for fonte in info.get("fontes", []):
                    st.markdown(f"- [{fonte['nome']}]({fonte['url']})")

                if csvs_reais:
                    st.success(f"DADOS REAIS - {len(csvs_reais)} arquivo(s) em `reais/`")
                    for cr in csvs_reais:
                        st.caption(f"`{cr.name}` ({cr.stat().st_size/1024:.0f} KB)")
                        df_real = _ler(cr)
                        if df_real is not None:
                            st.dataframe(df_real.head(10), use_container_width=True)
                            for col_ctx in ["COUNTRY", "YEAR", "DOMAIN"]:
                                if col_ctx in df_real.columns:
                                    st.caption(f"Distribuicao [{col_ctx}]: "
                                               f"{df_real[col_ctx].value_counts().head(8).to_dict()}")
                elif docs_reais:
                    st.success(f"Documentos oficiais baixados em `reais/documentos/` ({len(docs_reais)})")
                    for d in docs_reais:
                        st.markdown(f"- `{d.name}` ({d.stat().st_size/1024:.0f} KB)")
                    st.info("Este exame nao publica microdados abertos; apenas relatorios agregados oficiais "
                            "(PDF). Para microdados, faca a solicitacao institucional ao orgao.")
                else:
                    st.info("Aguardando dados reais (execute `processamento/baixar_dados_internacionais.py`).")

                st.markdown("---")
                pl_csvs = [p for p in (pasta_ex.glob("*.csv") if pasta_ex.exists() else []) if p.name.startswith("placeholder")]
                if pl_csvs:
                    st.warning("**Dados SIMULADOS (placeholders)** - nao usar em analises oficiais.")
                    st.caption(f"{len(pl_csvs)} arquivo(s) de exemplo gerados por `gerar_placeholders.py`.")
                    st.dataframe(_ler(pl_csvs[0]).head(10), use_container_width=True)
                else:
                    st.caption("Sem placeholders simulados neste exame.")
                if info.get("citacao"):
                    st.caption(f"Citacao sugerida: {info['citacao']}")


# --- TAB 15: SHAP & XAI DASHBOARD ---
elif aba == ABAS[15]:
    st.header("SHAP & XAI Dashboard")
    st.markdown("""
    **Explicabilidade de IA (XAI):** Esta aba utiliza **SHAP (SHapley Additive exPlanations)** para
    revelar quais variaveis (questoes, OCs, atributos socioeconomicos) mais contribuem para as predicoes
    do modelo. O SHAP fornece explicacoes teoricamente fundamentadas em teoria dos jogos, garantindo
    que a importancia de cada variavel seja justa e consistente. Combina visualizacoes SHAP, SOM e DINA.
    """)

    if chave_curso:
        st.subheader("1. SHAP Feature Importance")
        arq = _buscar("importancia", _pasta_motor("shap"), chave_curso)
        if arq:
            dfs = _ler(arq)
            ci = [c for c in dfs.columns if "importance" in c.lower() or "importancia" in c.lower()]
            cf = [c for c in dfs.columns if "feature" in c.lower() or "variavel" in c.lower() or "questao" in c.lower()]
            if ci and cf:
                st.plotly_chart(
                    px.bar(dfs.head(15), x=ci[0], y=cf[0], orientation="h",
                           color=ci[0], color_continuous_scale="Viridis",
                           title=f"SHAP -- Importancia das Variaveis -- {nome_curso}"),
                    use_container_width=True)
                st.info("**Interpretacao:** Variaveis com maior valor SHAP sao as mais determinantes para a predicao.")
            else:
                st.dataframe(dfs, use_container_width=True)
        else:
            st.info("Execute SHAP para gerar os resultados.")

        arq_m = _buscar("metricas", _pasta_motor("shap"), chave_curso)
        if arq_m:
            st.subheader("Metricas do Modelo SHAP")
            st.dataframe(_ler(arq_m), use_container_width=True)
            st.caption("Metricas de acuracia e qualidade do modelo preditivo.")

        st.markdown("---")
        st.subheader("2. SOM - Self-Organizing Map")
        som = _pasta_motor("psicometria") / f"som_{chave_curso}.png"
        if som.exists():
            st.image(str(som), use_container_width=True)
            st.caption("O SOM projeta o espaco multidimensional de respostas em uma grelha 2D. "
                       "Areas de mesma cor indicam alunos com perfis cognitivos semelhantes.")
        else:
            st.info("Imagem SOM nao encontrada para este curso.")

        st.markdown("---")
        st.subheader("3. DINA (Slip & Guess)")
        st.markdown("""
        O modelo **DINA (Deterministic Input, Noisy "And" Gate)** estima dois parametros por item:
        - **Slip (s):** probabilidade de um aluno que domina o atributo errar o item
        - **Guess (g):** probabilidade de um aluno que nao domina acertar por chute
        """)
        pasta_cdm_atual = _pasta_motor("cdm")
        dina_files = sorted(pasta_cdm_atual.glob("dina_*.csv")) if pasta_cdm_atual.exists() else []
        dina_files = [f for f in dina_files if "q_matrix" not in f.name]
        if dina_files:
            for dina_file in dina_files:
                df_dina = _ler(dina_file)
                if df_dina is not None and "questao" in df_dina.columns and ("slip" in df_dina.columns or "slip_s" in df_dina.columns):
                    df_show = df_dina.rename(columns={"slip_s": "slip", "guess_g": "guess"}).copy()
                    st.markdown(f"**{dina_file.stem}**")
                    st.dataframe(df_show.head(30), use_container_width=True)
        else:
            st.info("Nenhum arquivo dina_*.csv encontrado.")
    else:
        st.info("Selecione um curso no painel lateral.")


# ===========================================================================
# TAB 16: RANKING IA POR IES (K-MEANS) -- portado de fase5/analiseIE.py
# ===========================================================================
elif aba == ABAS[16]:
    st.header("Ranking de Deficiencias por Grupos de IA (K-Means por IES)")
    st.markdown("""
    **Motor portado de `fase5_visualizacao/analiseIE.py`.** O K-Means agrupa os alunos de cada IES
    em perfis de desempenho (3 perfis se houver >= 10 alunos, senao 2). Para cada perfil sao
    extraidos os **2 maiores GAPs** (questoes onde o grupo esta mais aquem da media da propria IES),
    com o erro absoluto (%) e os Objetos de Conhecimento (OCs) e Competencias de cada questao.
    """)
    if df is None:
        st.info("Selecione um exame no painel lateral.")
    elif not _tem_colunas(df, "CO_IES") or not _tem_colunas(df, "CO_GRUPO") or df_nacional is None or df_nacional.empty:
        st.info("Este exame nao possui CO_IES/CO_GRUPO com dados para gerar o ranking por IES.")
    else:
        mapa_q = _mapa_questoes_curso(curso_codigo, ano_fil, sel_tipo)
        q_cols = [f"Q{n}" for n in sorted(mapa_q) if f"Q{n}" in df_nacional.columns]
        if len(q_cols) < 5:
            q_cols = [f"Q{i}" for i in range(1, 39) if f"Q{i}" in df_nacional.columns]
        if len(q_cols) < 5:
            st.warning("Colunas de questoes nao encontradas na base selecionada.")
        else:
            curso_label = nome_curso or f"Grupo {curso_codigo}"
            st.subheader(f"Curso: {curso_label}")
            try:
                df_nac_num = df_nacional.copy()
                ies_opts = sorted(pd.to_numeric(df_nac_num["CO_IES"], errors="coerce").dropna().unique().tolist())
            except Exception:
                ies_opts = []
            if not ies_opts:
                st.warning("Nenhuma IES com dados para este curso.")
            else:
                default_idx = 0
                if ies_sel is not None:
                    try:
                        default_idx = ies_opts.index(int(ies_sel))
                    except (ValueError, IndexError):
                        default_idx = 0
                ies_escolhida = st.selectbox(
                    "IES (processamento por IES):", ies_opts,
                    index=default_idx,
                    format_func=lambda x: f"IES {x}", key="ies_ranking")
                df_ies = df_nac_num[df_nac_num["CO_IES"] == ies_escolhida]
                tam_ies = len(df_ies)
                if tam_ies < 5:
                    st.info(f"IES {ies_escolhida} tem menos de 5 alunos ({tam_ies}). Seleciona outra IES.")
                else:
                    with st.spinner("A executar K-Means por perfil..."):
                        perfis = _kmeans_perfis(df_ies, q_cols, mapa_q)
                    st.caption(f"Total de alunos analisados na IES {ies_escolhida}: **{tam_ies}**")
                    if not perfis:
                        st.info("Nenhum perfil gerado para esta IES.")
                    else:
                        cols_cab = st.columns(len(perfis))
                        for col, p in zip(cols_cab, perfis):
                            col.metric(f"{p['nome']}", f"{p['qtd']} alunos", f"Media: {p['media']:.2f}")
                        st.markdown("---")
                        for p in perfis:
                            with st.expander(f"{p['nome']} -- {p['qtd']} alunos | Media de acertos: {p['media']:.2f}", expanded=True):
                                for d in p["detalhes"]:
                                    cor_gap = "red" if d["gap"] < 0 else "green"
                                    st.markdown(
                                        f"- **{d['questao']}** -- Erro: **{d['erro']}%** | GAP: :{cor_gap}[{d['gap']:+.1f}pp]")
                                    c_oc, c_comp = st.columns(2)
                                    c_oc.caption(f"**OCs:** {_curto(d['ocs'], 140)}")
                                    c_comp.caption(f"**Competencia:** {_curto(d['comp'], 140)}")
                        st.markdown("---")
                        df_rank = _perfis_para_df(perfis, ies=int(ies_escolhida))
                        st.subheader("Tabela do Ranking (2 maiores GAPs por perfil)")
                        st.dataframe(df_rank, use_container_width=True)
                        html_titulo = f"Ranking K-Means - {curso_label} - IES {ies_escolhida}"
                        st.download_button(
                            "Baixar Ranking (HTML)", _ranking_html(df_rank, html_titulo),
                            file_name=f"ranking_kmeans_{_norm(curso_label)}_ies{ies_escolhida}.html",
                            mime="text/html")

                st.markdown("---")
                st.subheader("Ranking para TODAS as IES do curso (processamento completo)")
                st.markdown("""
                Processa o K-Means para **cada IES** do curso e gera o ranking completo
                (equivalente ao HTML gerado pelo script `analiseIE.py` da fase 5).
                """)
                top_n = st.slider("Numero de IES a processar (ordenadas por numero de alunos):", 1, min(len(ies_opts), 60), min(len(ies_opts), 20), key="top_ies_ranking")
                if st.button("Gerar Ranking Completo", key="btn_ranking_completo"):
                    with st.spinner("A processar K-Means para todas as IES selecionadas..."):
                        count_ies = df_nac_num["CO_IES"].value_counts()
                        ies_maiores = count_ies.head(top_n).index.tolist()
                        frames = []
                        for ies in ies_maiores:
                            df_i = df_nac_num[df_nac_num["CO_IES"] == ies]
                            if len(df_i) < 5:
                                continue
                            p_i = _kmeans_perfis(df_i, q_cols, mapa_q)
                            if p_i:
                                frames.append(_perfis_para_df(p_i, ies=ies))
                        if frames:
                            df_all = pd.concat(frames, ignore_index=True)
                            st.success(f"Ranking gerado: {len(df_all)} linhas em {len(ies_maiores)} IES.")
                            st.dataframe(df_all, use_container_width=True, height=450)
                            html_titulo_all = f"Ranking K-Means por Grupos de IA - {curso_label}"
                            st.download_button(
                                "Baixar Ranking Completo (HTML)",
                                _ranking_html(df_all, html_titulo_all),
                                file_name=f"ranking_kmeans_completo_{_norm(curso_label)}.html",
                                mime="text/html")
                        else:
                            st.info("Nenhum perfil gerado para as IES selecionadas.")


# --- TAB 17: ANALISES DE TESE (E1-E9) ---
elif aba == ABAS[17]:
    st.header("Analises de Tese (E1-E9)")
    st.markdown("""
    **Analises adicionais** sobre os microdados reais do ENADE.
    Cada resultado declara honestamente **"Dados insuficientes"** quando a informacao
    nao existe na base, em vez de estimar ou inventar valores. Todos os numeros sao
    rastreaveis ao artefato `modelos/analises_tese/analises_tese_<ano>.json`.
    """)

    pasta_tese = PASTA_MODELOS / "analises_tese"
    arquivos = sorted(pasta_tese.glob("analises_tese_*.json")) if pasta_tese.exists() else []
    if not arquivos:
        st.info("Nenhuma analise encontrada. Rode: `python processamento/analises_tese.py` "
                "(ou o menu 16 > opcao 5).")
    else:
        opcoes = sorted({a.stem.replace("analises_tese_", "").replace("edicao_", "")
                         for a in arquivos})
        ano_sel = st.selectbox("Edicao analisada:", opcoes, index=len(opcoes) - 1)
        candidatos = [a for a in arquivos if ano_sel in a.stem]
        if candidatos:
            try:
                dados = json.loads(candidatos[-1].read_text(encoding="utf-8"))
            except Exception as exc:
                st.warning(f"Nao foi possivel ler o artefato: {exc}")
                dados = {}

            _titulos = {
                "E1_equidade": "E1 - Equidade (regiao, categoria, sexo, modalidade)",
                "E2_valor_agregado": "E2 - Valor Agregado (residuo vs. perfil socioeconomico)",
                "E3_invariancia": "E3 - Invariancia da estrutura entre edicoes",
                "E4_trienal": "E4 - Tendencia por ciclo trienal",
                "E5_formacao": "E5 - Formacao (modalidade e tempo de curso)",
                "E6_eficiencia": "E6 - Eficiencia (fronteira DEA simples)",
                "E7_cluster_ies": "E7 - Perfis de IES (K-Means)",
                "E8_distal": "E8 - Desfechos distais (QE_I*)",
                "E9_sensibilidade": "E9 - Sensibilidade (peso amostral e limiar)",
            }
            for chave, titulo in _titulos.items():
                if chave not in dados:
                    continue
                res = dados[chave]
                with st.expander(titulo, expanded=(chave in ("E1_equidade", "E2_valor_agregado"))):
                    if not isinstance(res, dict):
                        st.json(res)
                        continue
                    if res.get("status") == "insuficiente":
                        st.warning(f"Dados insuficientes: {res.get('motivo', 'motivo nao informado')}")
                        continue
                    if chave == "E1_equidade":
                        for dim in ("regiao", "categoria", "sexo", "modalidade"):
                            if dim in res and res[dim]:
                                st.markdown(f"**Por {dim}** — gap de "
                                            f"**{res[dim]['gap']:.2f}** pontos")
                                st.dataframe(pd.DataFrame(res[dim]["tabela"]),
                                             use_container_width=True)
                    elif chave == "E2_valor_agregado":
                        st.caption(f"R² do controle socioeconomico: {res['r2_controle']:.3f} | "
                                   f"{res['n_ies']} IES com amostra suficiente")
                        c1, c2 = st.columns(2)
                        c1.markdown("**Top 10 IES (maior valor agregado)**")
                        c1.dataframe(pd.DataFrame(res["top_ies"]), use_container_width=True)
                        c2.markdown("**Bottom 10 IES**")
                        c2.dataframe(pd.DataFrame(res["bottom_ies"]), use_container_width=True)
                    elif chave == "E3_invariancia":
                        st.dataframe(pd.DataFrame(res["comparacoes"]).T,
                                     use_container_width=True)
                    elif chave == "E4_trienal":
                        for curso, serie in res.items():
                            if isinstance(serie, dict) and serie.get("status") == "ok":
                                st.markdown(f"**{curso}** — tendencia/edicao: "
                                            f"{serie['tendencia_por_edicao']:+.2f}")
                                st.dataframe(pd.DataFrame(serie["serie"]),
                                             use_container_width=True)
                    elif chave == "E5_formacao":
                        for dim in ("por_modalidade", "por_ano_curso"):
                            if dim in res:
                                st.markdown(f"**{dim.replace('_', ' ')}**")
                                st.dataframe(pd.DataFrame(res[dim]).T, use_container_width=True)
                    elif chave == "E6_eficiencia":
                        st.dataframe(pd.DataFrame(res["top_ies"]), use_container_width=True)
                    elif chave == "E7_cluster_ies":
                        st.caption(f"{res['n_clusters']} perfis | {res['n_ies']} IES")
                        st.dataframe(pd.DataFrame(res["perfis"]).T, use_container_width=True)
                    elif chave == "E8_distal":
                        for var in ("QE_I01", "QE_I02", "QE_I03"):
                            if var in res:
                                st.markdown(f"**{var}** (distribuicao por tercil)")
                                st.dataframe(pd.DataFrame(res[var]).T, use_container_width=True)
                    elif chave == "E9_sensibilidade":
                        st.caption(f"Tau de Kendall (peso vs. simples): "
                                   f"{res['tau_kendall_peso']:.3f} | Limiar: "
                                   f"{res['limiar_excelencia']:.1f}")
                        st.dataframe(pd.DataFrame(res["tabela"]).T, use_container_width=True)




# --- TAB 18: ANALISES GLOBAIS (ENADE 2004-2023, ENAMED, LICENCIATURAS) ---
elif aba == ABAS[18]:
    st.header("Análises Globais — ENADE (2004-2023), ENAMED e Licenciaturas")
    st.markdown("""
    **Síntese auditável** do que os dados e artefatos do PRISM-EDU permitem afirmar sobre os três exames.
    A análise é **direta e sem generalização indevida**: toda métrica indica fonte/coluna, cobertura e limitações.
    Quando a informação não existe no artefato/base carregada, o painel declara **"dado insuficiente"**.
    """)

    @st.cache_data(show_spinner=False)
    def _carregar_agg_enade_ano(caminho_str):
        """Agrega microdado ENADE por CO_GRUPO com colunas mínimas (eficiente)."""
        path = caminho_str
        cols_use = ["CO_GRUPO", "CO_IES", "CO_REGIAO_CURSO", "NT_GER", "NT_OBJ_CE", "NT_OBJ_FG"]
        try:
            head = pd.read_csv(path, sep=";", encoding="utf-8-sig", nrows=0)
            cols = [c for c in cols_use if c in head.columns]
            if "CO_GRUPO" not in cols:
                return None
            df = pd.read_csv(path, sep=";", encoding="utf-8-sig", usecols=cols, low_memory=False)
        except Exception:
            try:
                df = pd.read_csv(path, sep=",", encoding="utf-8-sig", low_memory=False)
            except Exception:
                return None
        for c in ["NT_GER", "NT_OBJ_CE", "NT_OBJ_FG"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        if "CO_IES" in df.columns:
            df["CO_IES"] = pd.to_numeric(df["CO_IES"], errors="coerce")
        g = df.groupby("CO_GRUPO", dropna=False)
        out = g.agg(
            N=("CO_GRUPO", "size"),
            IES=("CO_IES", "nunique") if "CO_IES" in df.columns else ("CO_GRUPO", "size"),
            NT_GER_media=("NT_GER", "mean") if "NT_GER" in df.columns else ("CO_GRUPO", "size"),
            NT_OBJ_CE_media=("NT_OBJ_CE", "mean") if "NT_OBJ_CE" in df.columns else ("CO_GRUPO", "size"),
        ).reset_index()
        if "NT_GER" not in df.columns:
            out["NT_GER_media"] = np.nan
        if "NT_OBJ_CE" not in df.columns:
            out["NT_OBJ_CE_media"] = np.nan
        return out

    def _macro_area_enade(nome_curso, co_grupo=None):
        n = _norm(nome_curso)
        saude_bio = ["medicina", "enferm", "odontolog", "farmac", "fisioterap", "nutri", "veterinar", "biomed",
                     "fonoaudiolog", "terapiaocup", "agronom", "zootec", "biolog", "cienciasbiolog", "educacaofisica"]
        if any(k in n for k in saude_bio):
            return "Saúde e Biológicas"
        if "psicolog" in n:
            return "Psicologia"
        if "engenhar" in n:
            return "Engenharias"
        ti = ["estatistic", "computac", "cienciadacomput", "sistemasdeinform", "engenhariadecomput", "engenhariadacomput",
              "analiseedesenvolvimentodesistemas", "redesdecomput", "gestaodatecnologiadainform", "tecnologiadainform"]
        if any(k in n for k in ti):
            return "Estatística e TI"
        return "Outras áreas"

    macro_foco = ["Saúde e Biológicas", "Psicologia", "Engenharias", "Estatística e TI"]

    tab_g1, tab_g2, tab_g3, tab_g4 = st.tabs([
        "ENADE 2004-2023 (5 áreas)", "ENAMED", "ENADE Licenciaturas", "Análises adicionais"
    ])

    with tab_g1:
        st.subheader("ENADE 2004-2023 — 5 macro-áreas prioritárias")
        st.markdown("""
        **Áreas foco (definição operacional/auditável por nome do curso/CO_GRUPO no mapeamento):**
        1) Saúde e Biológicas (inclui Medicina e afins) · 2) Psicologia · 3) Engenharias · 4) Estatística e TI (Computação, SI, CC etc.).
        Demais cursos aparecem como "Outras áreas" para completude, sem serem o foco comparativo principal.
        **Limitação:** o ENADE é trienal por área; ausência de 2020 e mudanças de matriz/itens impedem comparação causal simples.
        """)
        arquivos_enade = []
        for base in [PASTA_RESULTADOS_ENADE, PASTA_DADOS_PROCESSADOS, PASTA_DADOS_PROCESSADOS / "enade"]:
            if base.exists():
                arquivos_enade.extend(list(base.glob("relatorio_final_enade_*.csv")))
        try:
            ext = RAIZ_PROJETO.parent / "seriesTemporais_microdados" / "resultados" / "enade"
            if ext.exists():
                arquivos_enade.extend(list(ext.glob("relatorio_final_enade_*.csv")))
        except Exception:
            pass
        seen = set(); uniq = []
        for f in sorted(arquivos_enade):
            if str(f) not in seen:
                seen.add(str(f)); uniq.append(f)
        if not uniq:
            st.info("Nenhum microdado consolidado ENADE (`relatorio_final_enade_*.csv`) encontrado nas pastas configuradas. Exiba esta aba após disponibilizar os arquivos em `seriesTemporais_microdados/resultados/enade/` ou `dados/processados/enade/`.")
        else:
            anos_disp_g = []
            for p in uniq:
                m = re.findall(r"(20\d\d)", p.name)
                if m:
                    anos_disp_g.append(int(m[0]))
            anos_disp_g = sorted(set(anos_disp_g))
            anos_sel = st.multiselect("Edições ENADE:", anos_disp_g,
                                      default=anos_disp_g[-6:] if len(anos_disp_g) > 6 else anos_disp_g,
                                      key="glob_anos")
            rows = []
            prog = st.progress(0.0, text="Agregando edições...")
            use_files = [p for p in uniq if any(str(a) in p.name for a in anos_sel)]
            for i, fp in enumerate(use_files):
                m = re.findall(r"(20\d\d)", fp.name); ano = int(m[0]) if m else 0
                agg = _carregar_agg_enade_ano(str(fp))
                prog.progress((i+1)/max(1,len(use_files)), text=f"Agregando {fp.name}...")
                if agg is None or agg.empty:
                    continue
                for _, r in agg.iterrows():
                    cg = r.get("CO_GRUPO")
                    try:
                        cg_i = int(float(cg))
                    except Exception:
                        cg_i = None
                    nome = CURSOS_MAP.get(cg_i, f"CO_GRUPO {cg}")
                    macro = _macro_area_enade(nome, cg_i)
                    rows.append({"Ano": ano, "CO_GRUPO": cg_i, "Curso": nome, "Macroárea": macro,
                                 "N": int(r.get("N", 0) or 0), "IES": int(r.get("IES", 0) or 0),
                                 "NT_GER_media": pd.to_numeric(r.get("NT_GER_media"), errors="coerce"),
                                 "NT_OBJ_CE_media": pd.to_numeric(r.get("NT_OBJ_CE_media"), errors="coerce")})
            prog.empty()
            if not rows:
                st.info("Não foi possível agregar as edições selecionadas (verifique colunas CO_GRUPO/NT_GER nos CSVs).")
            else:
                dfg = pd.DataFrame(rows)
                foco = dfg[dfg["Macroárea"].isin(macro_foco)].copy()
                cov = foco.groupby(["Macroárea", "Ano"])["N"].sum().reset_index()
                fig_cov = px.bar(cov, x="Ano", y="N", color="Macroárea", barmode="group",
                                 title="Cobertura (N de participantes) — 5 macro-áreas ENADE")
                st.plotly_chart(fig_cov, use_container_width=True)
                st.caption("Fonte: microdados consolidados `relatorio_final_enade_*.csv` (agregação por CO_GRUPO/ano). Valores dependem da presença de NT_GER/CO_IES.")
                if foco["NT_GER_media"].notna().any():
                    trend = foco.dropna(subset=["NT_GER_media"])
                    trend = trend.assign(peso=trend["N"].fillna(1))
                    t = trend.groupby(["Macroárea", "Ano"]).apply(
                        lambda g: np.average(g["NT_GER_media"], weights=g["peso"]) if g["peso"].sum()>0 else g["NT_GER_media"].mean(),
                        include_groups=False).reset_index(name="NT_GER_ponderada")
                    fig_t = px.line(t, x="Ano", y="NT_GER_ponderada", color="Macroárea", markers=True,
                                    title="Tendência de NT_GER (média ponderada por N) — 5 macro-áreas")
                    st.plotly_chart(fig_t, use_container_width=True)
                    st.caption("Leitura cautelosa: oscilações podem refletir mudança de cursos avaliados no ciclo trienal, composição de IES/estudantes e matriz da prova — não interpretar como causalidade.")
                else:
                    st.info("NT_GER indisponível nas edições agregadas; exibida apenas cobertura por N/IES.")
                st.markdown("**Resumo auditável por macro-área (edições selecionadas)**")
                with st.expander("Como as métricas são calculadas (fórmulas e unidades)", expanded=False):
                    st.markdown(r"""
**Fonte (microdado agregado por CO_GRUPO/ano, `relatorio_final_enade_*.csv`):**
- $N$ = contagem de participantes no grupo (`groupby(CO_GRUPO).size()`).
- $IES$ = número de IES distintas (`nunique(CO_IES)`).
- $NT\_GER\_media_{grupo,ano}$ = média simples de `NT_GER` no grupo/ano (quando disponível).
- $NT\_GER\_ponderada_{macro,ano}$ = $\frac{\sum_g NT\_GER\_media_{g,ano}\cdot N_{g,ano}}{\sum_g N_{g,ano}}$ (ponderação por $N$ dos cursos/grupos na macro-área).
- No resumo por macro-área: `edicoes`=nunique(Ano), `cursos`=nunique(Curso), `N_total`=soma($N$), `IES_media`=média($IES$ por grupo/ano), `NT_GER_media`=média simples das médias de grupo (descritiva; ver ponderada no gráfico).

**Fonte (itens processados, `analise_por_questao_ies_enade_*.csv`):** cada registro representa tipicamente **IES × curso × questão** (com OCs associados).
- $TAXA\_DEFICIENCIA\_\%$ (no arquivo) = $\frac{QTD\_ERROS}{QTD\_ACERTOS + QTD\_ERROS}\times 100$ (por registro IES×questão).
- $Taxa\_ponderada$ (recomendada, quando há contagens) = $\frac{\sum QTD\_ERROS}{\sum (QTD\_ACERTOS+QTD\_ERROS)}\times 100$, somando sobre os registros do recorte (ano/macro-área/OC/questão).
- $Taxa\_media\_simples$ = média aritmética de `TAXA_DEFICIENCIA_%` nos registros do recorte (cada registro IES×questão pesa igual). **As duas podem diferir** quando o número de respondentes varia entre IES/questões; o painel mostra ambas quando possível.
- **OC (Objeto de Conhecimento):** `OC1`, `OC2`, `OC3` do arquivo processado; **questão:** `QUESTAO`; contexto adicional: `PERFIL`, `COMPETENCIAS`.
- **Limitação:** a macro-área é classificação operacional por nome/CO_GRUPO; itens/OCs são comparáveis dentro de edições/condições do exame, respeitando o ciclo trienal.
                    """)
                resumo = foco.groupby("Macroárea").agg(
                    edicoes=("Ano", "nunique"), cursos=("Curso", "nunique"), N_total=("N", "sum"), IES_media=("IES", "mean"),
                    NT_GER_media=("NT_GER_media", "mean")).reset_index()
                st.dataframe(resumo.round(2), use_container_width=True)
                st.caption("Resumo descritivo por macro-área (agregação de grupos CO_GRUPO/ano). Para itens/OCs com problema, use os detalhamentos abaixo.")

                st.markdown("**Itens e Objetos de Conhecimento (OC) com maior deficiência — processados**")
                qdet_rows = []
                for a in sorted(set(foco["Ano"].tolist())):
                    daq = _carregar_analise_ies(a) if '_carregar_analise_ies' in globals() else None
                    if daq is None or daq.empty or "CO_GRUPO" not in daq.columns:
                        continue
                    tmp = daq.copy(); tmp["Ano"] = a
                    def _nome_do_codigo(cg):
                        try:
                            return CURSOS_MAP.get(int(cg), str(cg))
                        except (TypeError, ValueError):
                            return str(cg)
                    tmp["Macroárea"] = tmp["CO_GRUPO"].map(lambda cg: _macro_area_enade(_nome_do_codigo(cg) if pd.notna(cg) else "", cg))
                    tmp = tmp[tmp["Macroárea"].isin(macro_foco)]
                    if not tmp.empty:
                        qdet_rows.append(tmp)
                if not qdet_rows:
                    st.info("Sem arquivos `analise_por_questao_ies_enade_*.csv` compatíveis para as edições/áreas selecionadas.")
                else:
                    qdet = pd.concat(qdet_rows, ignore_index=True)
                    for c in ["QTD_ACERTOS", "QTD_ERROS", "TAXA_DEFICIENCIA_%", "CO_IES", "CO_GRUPO"]:
                        if c in qdet.columns:
                            qdet[c] = pd.to_numeric(qdet[c], errors="coerce")
                    qdet["TOTAL_RESP"] = (pd.to_numeric(qdet.get("QTD_ACERTOS"), errors="coerce").fillna(0)
                                          + pd.to_numeric(qdet.get("QTD_ERROS"), errors="coerce").fillna(0))
                    if "CURSO" not in qdet.columns and "NOME_CURSO" in qdet.columns:
                        qdet["CURSO"] = qdet["NOME_CURSO"]
                    elif "CURSO" not in qdet.columns:
                        qdet["CURSO"] = qdet.get("CO_GRUPO", "").astype(str)

                    fc1, fc2 = st.columns(2)
                    with fc1:
                        macro_sel_det = st.multiselect("Macro-área (detalhe):", macro_foco, default=macro_foco, key="glob_macro_det")
                    with fc2:
                        anos_det = sorted(qdet["Ano"].dropna().unique().tolist()) if "Ano" in qdet.columns else []
                        ano_sel_det = st.multiselect("Ano (detalhe):", anos_det, default=anos_det, key="glob_ano_det")
                    qf = qdet[qdet["Macroárea"].isin(macro_sel_det)].copy()
                    if ano_sel_det:
                        qf = qf[qf["Ano"].isin(ano_sel_det)]

                    # tendência por macro-área (mostra simples e ponderada)
                    tr_rows = []
                    for (mac, ano), g in qf.groupby(["Macroárea", "Ano"]):
                        tot = g["TOTAL_RESP"].sum()
                        pond = (g["QTD_ERROS"].sum() / tot * 100) if tot > 0 else np.nan
                        simp = g["TAXA_DEFICIENCIA_%"].mean() if "TAXA_DEFICIENCIA_%" in g.columns else np.nan
                        tr_rows.append({"Macroárea": mac, "Ano": ano, "Taxa_ponderada_%": pond, "Taxa_media_simples_%": simp, "Registros_IESxQuestao": len(g), "Total_respostas": tot})
                    if tr_rows:
                        dq = pd.DataFrame(tr_rows)
                        fig_d = px.line(dq, x="Ano", y="Taxa_ponderada_%", color="Macroárea", markers=True,
                                        title="Taxa de deficiência ponderada por respondentes — 5 macro-áreas (itens processados)")
                        st.plotly_chart(fig_d, use_container_width=True)
                        st.caption("`Taxa_ponderada_% = ΣQTD_ERROS / Σ(QTD_ACERTOS+QTD_ERROS) × 100` nos registros filtrados. Fonte: `analise_por_questao_ies_enade_*.csv`.")
                        st.dataframe(dq.round(2).sort_values(["Macroárea", "Ano"]), use_container_width=True)

                    # OC com problema
                    st.markdown("**Objetos de Conhecimento (OC1/OC2/OC3) com maior deficiência**")
                    oc_rows = []
                    for oc_col in ["OC1", "OC2", "OC3"]:
                        if oc_col not in qf.columns:
                            continue
                        tmp_oc = qf[["Ano","Macroárea","CURSO","QUESTAO","TAXA_DEFICIENCIA_%","QTD_ACERTOS","QTD_ERROS","TOTAL_RESP", oc_col]].copy()
                        tmp_oc = tmp_oc.rename(columns={oc_col: "OC"})
                        tmp_oc["Origem_OC"] = oc_col
                        tmp_oc["OC"] = tmp_oc["OC"].astype(str).str.strip()
                        tmp_oc = tmp_oc[tmp_oc["OC"].notna() & (tmp_oc["OC"] != "") & (tmp_oc["OC"].str.lower() != "nan")]
                        oc_rows.append(tmp_oc)
                    if oc_rows:
                        ocd = pd.concat(oc_rows, ignore_index=True)
                        oc_agg = ocd.groupby(["Macroárea", "OC"], dropna=False).agg(
                            Questoes_distintas=("QUESTAO", "nunique") if "QUESTAO" in ocd.columns else ("OC","size"),
                            Registros=("OC", "size"),
                            Total_respostas=("TOTAL_RESP", "sum"),
                            Soma_erros=("QTD_ERROS", "sum"),
                            Soma_acertos=("QTD_ACERTOS", "sum"),
                            Taxa_media_simples_pct=("TAXA_DEFICIENCIA_%", "mean"),
                        ).reset_index()
                        oc_agg["Taxa_ponderada_pct"] = np.where(oc_agg["Total_respostas"] > 0,
                                                                oc_agg["Soma_erros"] / oc_agg["Total_respostas"] * 100, np.nan)
                        oc_agg = oc_agg.sort_values(["Macroárea", "Taxa_ponderada_pct"], ascending=[True, False])
                        st.dataframe(oc_agg.round(2), use_container_width=True, height=320)
                        st.caption("Cada linha é um OC no recorte filtrado. `Taxa_ponderada_pct` usa Σerros/Σrespostas nos registros ligados ao OC (inclui registros onde o OC aparece como OC1/OC2/OC3).")
                        # top N por macroárea
                        topn = st.slider("Top OCs por macro-área (gráfico):", 3, 20, 8, key="glob_oc_topn")
                        oc_top = oc_agg.groupby("Macroárea", group_keys=False).head(topn)
                        fig_oc = px.bar(oc_top, x="Taxa_ponderada_pct", y="OC", color="Macroárea", orientation="h",
                                        facet_col="Macroárea", facet_col_wrap=2, height=220*max(1, (len(macro_sel_det)+1)//2),
                                        title="Top OCs por taxa de deficiência ponderada (recorte filtrado)")
                        fig_oc.update_yaxes(matches=None, showticklabels=True)
                        st.plotly_chart(fig_oc, use_container_width=True)
                    else:
                        st.info("Colunas OC1/OC2/OC3 não encontradas nos arquivos processados para o recorte.")

                    # Questões com problema
                    st.markdown("**Questões (itens) com maior deficiência**")
                    if "QUESTAO" in qf.columns:
                        q_agg = qf.groupby(["Macroárea", "Ano", "CURSO", "QUESTAO"], dropna=False).agg(
                            OC1=("OC1", "first") if "OC1" in qf.columns else ("QUESTAO","first"),
                            OC2=("OC2", "first") if "OC2" in qf.columns else ("QUESTAO","first"),
                            OC3=("OC3", "first") if "OC3" in qf.columns else ("QUESTAO","first"),
                            Registros_IES=("QUESTAO", "size"),
                            Total_respostas=("TOTAL_RESP", "sum"),
                            Soma_erros=("QTD_ERROS", "sum"),
                            Taxa_media_simples_pct=("TAXA_DEFICIENCIA_%", "mean"),
                        ).reset_index()
                        q_agg["Taxa_ponderada_pct"] = np.where(q_agg["Total_respostas"] > 0,
                                                               q_agg["Soma_erros"] / q_agg["Total_respostas"] * 100, np.nan)
                        q_agg = q_agg.sort_values("Taxa_ponderada_pct", ascending=False)
                        n_show = st.slider("Quantidade de questões a exibir:", 10, 200, 30, key="glob_q_n")
                        st.dataframe(q_agg.head(n_show).round(2), use_container_width=True, height=360)
                        st.caption("Questões ordenadas por `Taxa_ponderada_pct` no recorte (agregadas sobre IES; mesma questão pode aparecer em cursos/anos distintos — o ENADE é trienal e itens mudam por edição).")
                        # detalhe de uma questão
                        questoes_opts = q_agg["QUESTAO"].astype(str).unique().tolist()[:500]
                        if questoes_opts:
                            q_pick = st.selectbox("Inspecionar questão (detalhe por IES/registros):", ["(nenhuma)"] + questoes_opts, key="glob_q_pick")
                            if q_pick and q_pick != "(nenhuma)":
                                qd = qf[qf["QUESTAO"].astype(str) == str(q_pick)].copy()
                                cols_show = [c for c in ["Ano","Macroárea","CURSO","CO_IES","QUESTAO","OC1","OC2","OC3","PERFIL","COMPETENCIAS","QTD_ACERTOS","QTD_ERROS","TAXA_DEFICIENCIA_%","TOTAL_RESP"] if c in qd.columns]
                                st.dataframe(qd[cols_show].sort_values("TAXA_DEFICIENCIA_%", ascending=False).head(200), use_container_width=True)
                                if "PERFIL" in qd.columns or "COMPETENCIAS" in qd.columns:
                                    ex = qd.iloc[0]
                                    if pd.notna(ex.get("PERFIL")):
                                        st.markdown(f"**Perfil (exemplo):** {ex.get('PERFIL')}")
                                    if pd.notna(ex.get("COMPETENCIAS")):
                                        st.markdown(f"**Competências (exemplo):** {ex.get('COMPETENCIAS')}")
                    else:
                        st.info("Coluna `QUESTAO` não encontrada no arquivo processado.")

    with tab_g2:
        st.subheader("ENAMED — o que é interessante (análise direta)")
        st.markdown("""
        **Contexto (auditável no projeto):** ENAMED é tratado como avaliação distinta (instrumento com conjunto próprio de itens; `CO_GRUPO` pode ser nulo e o agrupamento pode derivar de `CO_CURSO`/grupo 0 conforme normalização do pipeline).
        **Interesse analítico:** foco em Medicina/formação em saúde; potencial para diagnóstico por competências/domínios (LCA/DINA) quando há matriz de itens/OC; comparação com ENADE deve ser condicionada ao desenho.
        **Limitações:** comparabilidade direta com ENADE clássico é limitada por desenho, população, blueprint e ano.
        """)
        cands = [PASTA_DADOS_PROCESSADOS / "analise_por_questao_ies_enamed_2025.csv",
                 PASTA_DADOS_PROCESSADOS / "enamed" / "analise_por_questao_ies_enamed_2025.csv"]
        try:
            extm = RAIZ_PROJETO.parent / "seriesTemporais_microdados" / "resultados" / "enamed"
            if extm.exists():
                cands.extend(list(extm.rglob("analise_por_questao_ies*enamed*.csv")))
                cands.extend(list(extm.rglob("relatorio_final*enamed*.csv")))
        except Exception:
            pass
        found = [p for p in cands if p.exists()]
        if not found:
            st.info("Nenhum artefato ENAMED encontrado. Gere/importe os dados para habilitar métricas por item/curso.")
        else:
            st.success(f"Artefatos ENAMED detectados: {len(found)} arquivo(s). Exibindo o primeiro compatível.")
            fp = found[0]
            try:
                de = pd.read_csv(fp, sep=";", encoding="utf-8-sig", nrows=50000, low_memory=False)
            except Exception:
                de = pd.read_csv(fp, encoding="utf-8-sig", nrows=50000, low_memory=False)
            st.caption(f"Fonte: `{fp}` (linhas lidas: {len(de)})")
            st.dataframe(de.head(20), use_container_width=True)
            for c in ["QTD_ACERTOS","QTD_ERROS","TAXA_DEFICIENCIA_%"]:
                if c in de.columns: de[c] = pd.to_numeric(de[c], errors="coerce")
            de["_tot"] = de.get("QTD_ACERTOS", 0).fillna(0) + de.get("QTD_ERROS", 0).fillna(0) if "QTD_ACERTOS" in de.columns else np.nan
            m1,m2,m3 = st.columns(3)
            if "TAXA_DEFICIENCIA_%" in de.columns:
                media_s = pd.to_numeric(de['TAXA_DEFICIENCIA_%'], errors='coerce').mean()
                pond = (de["QTD_ERROS"].sum()/de["_tot"].sum()*100) if de["_tot"].fillna(0).sum()>0 and "QTD_ERROS" in de.columns else np.nan
                m1.metric("Taxa média simples (%)", f"{media_s:.2f}%")
                if pd.notna(pond): m2.metric("Taxa ponderada (%)", f"{pond:.2f}%")
            if "QUESTAO" in de.columns:
                m3.metric("Questões distintas", int(de["QUESTAO"].nunique()))
            with st.expander("Fórmula da taxa de deficiência (ENAMED)", expanded=False):
                st.markdown(r"- Por registro (IES×questão): $TAXA\_DEFICIENCIA\_\% = \frac{QTD\_ERROS}{QTD\_ACERTOS+QTD\_ERROS}\times 100$.  "
                            r"- **Média simples**: média aritmética dos registros (cada IES×questão pesa igual).  "
                            r"- **Ponderada**: $\frac{\sum QTD\_ERROS}{\sum(QTD\_ACERTOS+QTD\_ERROS)}\times 100$ (recomendada quando respondentes variam).")
            # OC/questões com problema
            if "QUESTAO" in de.columns:
                grp_q = ["QUESTAO"] + [c for c in ["OC1","OC2","OC3","NOME_CURSO","CO_GRUPO"] if c in de.columns]
                qag = de.groupby(grp_q, dropna=False).agg(Registros=("QUESTAO","size"), Soma_erros=("QTD_ERROS","sum"), Total_respostas=("_tot","sum"), Taxa_media_simples_pct=("TAXA_DEFICIENCIA_%","mean")).reset_index()
                qag["Taxa_ponderada_pct"] = np.where(qag["Total_respostas"]>0, qag["Soma_erros"]/qag["Total_respostas"]*100, np.nan)
                st.markdown("**Questões/OCs com maior deficiência (ENAMED, amostra carregada)**")
                st.dataframe(qag.sort_values("Taxa_ponderada_pct", ascending=False).head(40).round(2), use_container_width=True)
            st.markdown("**Achados potenciais (com artefatos completos):** deficiência por domínio/competência, itens com parâmetros DINA informativos (guess/slip), lacunas prioritárias para currículo/práticas clínicas — com validação por matriz-Q e evidência empírica.")

    with tab_g3:
        st.subheader("ENADE Licenciaturas — o que é interessante (análise direta)")
        st.markdown("""
        **Contexto (auditável no projeto):** Licenciaturas como edição/exame específico (conjunto próprio de itens). 
        **Interesse analítico:** formação docente; domínios de conhecimento específico/pedagógico (conforme OCs); integração com LCA/CDM/DINA e séries temporais **apenas quando comparabilidade é defensável**.
        **Limitações:** heterogeneidade entre licenciaturas, mudanças de prova e escala impedem generalização; reportar por curso/área e edição.
        """)
        cands = [PASTA_DADOS_PROCESSADOS / "analise_por_questao_ies_licenciaturas_2025.csv",
                 PASTA_DADOS_PROCESSADOS / "enadeLicenciaturas" / "analise_por_questao_ies_licenciaturas_2025.csv"]
        try:
            extl = RAIZ_PROJETO.parent / "seriesTemporais_microdados" / "resultados" / "enadeLicenciaturas"
            if extl.exists():
                cands.extend(list(extl.rglob("analise_por_questao_ies*licenciatura*.csv")))
                cands.extend(list(extl.rglob("relatorio_final*licenciatura*.csv")))
        except Exception:
            pass
        found = [p for p in cands if p.exists()]
        if not found:
            st.info("Nenhum artefato de Licenciaturas encontrado. Gere/importe os dados para habilitar métricas.")
        else:
            st.success(f"Artefatos Licenciaturas detectados: {len(found)} arquivo(s). Exibindo o primeiro compatível.")
            fp = found[0]
            try:
                dl = pd.read_csv(fp, sep=";", encoding="utf-8-sig", nrows=50000, low_memory=False)
            except Exception:
                dl = pd.read_csv(fp, encoding="utf-8-sig", nrows=50000, low_memory=False)
            st.caption(f"Fonte: `{fp}` (linhas lidas: {len(dl)})")
            st.dataframe(dl.head(20), use_container_width=True)
            for c in ["QTD_ACERTOS","QTD_ERROS","TAXA_DEFICIENCIA_%"]:
                if c in dl.columns: dl[c] = pd.to_numeric(dl[c], errors="coerce")
            dl["_tot"] = dl.get("QTD_ACERTOS", 0).fillna(0) + dl.get("QTD_ERROS", 0).fillna(0) if "QTD_ACERTOS" in dl.columns else np.nan
            m1,m2,m3 = st.columns(3)
            if "TAXA_DEFICIENCIA_%" in dl.columns:
                media_s = pd.to_numeric(dl['TAXA_DEFICIENCIA_%'], errors='coerce').mean()
                pond = (dl["QTD_ERROS"].sum()/dl["_tot"].sum()*100) if dl["_tot"].fillna(0).sum()>0 and "QTD_ERROS" in dl.columns else np.nan
                m1.metric("Taxa média simples (%)", f"{media_s:.2f}%")
                if pd.notna(pond): m2.metric("Taxa ponderada (%)", f"{pond:.2f}%")
            if "QUESTAO" in dl.columns:
                m3.metric("Questões distintas", int(dl["QUESTAO"].nunique()))
            with st.expander("Fórmula da taxa de deficiência (Licenciaturas)", expanded=False):
                st.markdown(r"- Por registro (IES×questão): $TAXA\_DEFICIENCIA\_\% = \frac{QTD\_ERROS}{QTD\_ACERTOS+QTD\_ERROS}\times 100$.  "
                            r"- **Média simples**: média aritmética dos registros.  "
                            r"- **Ponderada**: $\frac{\sum QTD\_ERROS}{\sum(QTD\_ACERTOS+QTD\_ERROS)}\times 100$ (recomendada quando respondentes variam).")
            if "QUESTAO" in dl.columns:
                grp_q = ["QUESTAO"] + [c for c in ["OC1","OC2","OC3","NOME_CURSO","CO_GRUPO"] if c in dl.columns]
                qag = dl.groupby(grp_q, dropna=False).agg(Registros=("QUESTAO","size"), Soma_erros=("QTD_ERROS","sum"), Total_respostas=("_tot","sum"), Taxa_media_simples_pct=("TAXA_DEFICIENCIA_%","mean")).reset_index()
                qag["Taxa_ponderada_pct"] = np.where(qag["Total_respostas"]>0, qag["Soma_erros"]/qag["Total_respostas"]*100, np.nan)
                st.markdown("**Questões/OCs com maior deficiência (Licenciaturas, amostra carregada)**")
                st.dataframe(qag.sort_values("Taxa_ponderada_pct", ascending=False).head(40).round(2), use_container_width=True)
            st.markdown("**Achados potenciais (com artefatos completos):** lacunas por área de licenciatura, comparação longitudinal apenas em condições comparáveis, e priorização curricular por OC/itens com evidência — sem inferência causal.")

    with tab_g4:
        st.subheader("O que há de diferente/novo")
        st.markdown("""
        **Contribuições observáveis no PRISM-EDU (ancoradas no que foi implementado/gerado):**
        - **Auditoria metodológica explícita:** separação entre evidência descritiva (taxa observada por OC), modelos latentes (LCA, DINA/EM com `guess_g/slip_s` e restrições) e camadas preditivas/explicativas (SHAP/XAI), reduzindo *overclaim*.
        - **Longitudinalidade defensável:** drift/séries por **proficiência em OC + notas**, comparação **trienal dentro do mesmo curso**; **não compara `Q*` cru entre edições**.
        - **Integração multi-exame com cautela:** ENADE 2004–2023, ENAMED e Licenciaturas tratados como fontes com desenhos distintos; cobertura, limitações e comparabilidade declaradas.
        - **Rastreabilidade e integridade:** matrizes-Q, dicionários OC, critérios LCA (`03_criterios_de_selecao_k.csv`), artefatos de drift, filtros de IES/curso na análise explicativa quando aplicável, e testes de regressão (83 OK).
        - **Honestidade operacional:** remoção/ausência de tabelas LCA fabricadas; diagnósticos individuais rotulados como descritivos (não CDM/DINA).

        **Diferencial para pesquisa (sem generalização):**
        - **1:** protocolo aplicado e replicável para diagnóstico educacional em larga escala com controles de integridade (vazamento, rotulagem honesta, comparabilidade temporal).
        - **2:** agenda para modelagem longitudinal de domínio (LCA↔DINA↔drift), invariância de construto entre edições, e avaliação de intervenções por OC com desenho quase-experimental quando houver dados adequados.

        **Posicionamento temático — verificação em bases indexadas (nota de honestidade):**
        A verificação automática na internet **não esteve disponível nesta execução**. Para fundamentação bibliográfica sem fabricar referências, buscar e registrar DOIs/citações em: **SciELO, ERIC, Scopus, Web of Science, Google Scholar**; periódicos/veículos a verificar: *Ensaio: Avaliação e Políticas Públicas em Educação*, *Estudos em Avaliação Educacional*, *RBIE*, *Computers & Education*, *Educational Assessment*, *Journal of Educational Measurement*, *Applied Measurement in Education*, *Psychometrika*, anais **EDM/LAK/AIED**.
        **Strings de busca sugeridas:** `"ENADE longitudinal learning analytics Brazil"`, `"cognitive diagnostic model DINA higher education large-scale assessment"`, `"latent class analysis item response drift invariance"`, `"ENAMED medical education assessment Brazil"`, `"teacher licensure assessment Enade Licenciaturas Brazil"`.
        Classificar cada referência como (a) converge, (b) diverge/limita, (c) lacuna abordada pelo PRISM-EDU — com rastreabilidade.
        """)
        st.info("Painel deliberadamente direto e auditável: prioriza evidência do pipeline, declara limitações e evita extrapolações causais.")

elif aba == ABAS[19]:
    st.header("Ontologia Educacional — OWL 2 DL (Protégé-ready)")
    st.markdown("""
    **Camada semântica auditável** do PRISM-EDU: ontologia **OWL 2 DL** gerada a partir de dados
    reais do projeto (TBox formal + ABox do ENADE 2023), serializada em `.owl` (RDF/XML), `.ttl`,
    `.jsonld` e `.nt`, com formas **SHACL**, consultas **SPARQL** e manifesto com hashes SHA-256.
    A ontologia descreve *o que os artefatos significam*; as tabelas-fato em CSV continuam sendo a
    fonte do desempenho item × IES × curso.
    """)

    pasta_onto = PASTA_MODELOS / "ontologia"
    caminho_manifesto = pasta_onto / "prism_edu_manifest.json"
    caminho_owl = pasta_onto / "prism_edu.owl"
    pasta_queries = pasta_onto / "queries"

    if not caminho_manifesto.exists():
        st.info("Ontologia ainda não gerada. Rode `python processamento/gerar_ontologia.py` "
                "(ou menu **IA Avançada → 1**).")
    else:
        try:
            manifesto = json.loads(caminho_manifesto.read_text(encoding="utf-8"))
        except Exception as exc:
            manifesto = None
            st.error(f"Manifesto ilegível: {exc}")

        if manifesto:
            resumo = manifesto.get("resumo", {})
            est = resumo.get("estatisticas", {})
            por_classe = resumo.get("por_classe", {})
            individuos = sum(v for k, v in por_classe.items() if k != "ContextualDimension")
            individuos += por_classe.get("ContextualDimension", 0)

            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Triplas RDF", f"{resumo.get('triplas', 0):,}".replace(",", "."))
            m2.metric("Classes", est.get("classes", 0))
            m3.metric(
                "Propriedades",
                est.get("object_properties", 0) + est.get("data_properties", 0),
                help=(f"{est.get('object_properties', 0)} object properties + "
                      f"{est.get('data_properties', 0)} data properties declaradas. "
                      "As inversas materializadas elevam o total de owl:ObjectProperty no grafo."),
            )
            m4.metric("Itens (ABox)", est.get("itens", 0))
            m5.metric("Indivíduos", f"{individuos:,}".replace(",", "."))
            st.caption(f"Versão `{manifesto.get('versao')}` · edições: "
                       f"{', '.join(manifesto.get('edicoes', []))} · "
                       f"gerado em {manifesto.get('gerado_em', '?')}")

            tab_o1, tab_o2, tab_o3, tab_o4 = st.tabs(
                ["Visão geral", "Classes e propriedades", "Consultas SPARQL", "Proveniência e arquivos"])

            with tab_o1:
                st.subheader("Contagens por classe (ABox real)")
                if por_classe:
                    df_classes = pd.DataFrame(
                        sorted(por_classe.items(), key=lambda kv: -kv[1]),
                        columns=["Classe", "Indivíduos"])
                    st.dataframe(df_classes, use_container_width=True, hide_index=True)
                st.subheader("Como usar")
                st.markdown("""
                1. Abra `modelos/ontologia/prism_edu.owl` no **Protégé 5.6+** (`File > Open`).
                2. Raciocínio: use **HermiT** ou **Pellet** (requer Java). A TBox foi checada como consistente.
                3. Valide a integridade com `python processamento/validar_ontologia.py`.
                4. Para consultas programáticas, use `rdflib` (obrigatório) e, opcionalmente,
                   `owlready2`, `OWLAPY` e `OAK` — a matriz da stack aparece em **Proveniência e arquivos**.
                """)
                st.info("**Limite declarado:** a ontologia não substitui a tabela-fato. Ela guarda "
                        "agregados nacionais por item, por IES e por IES × área — não o cruzamento "
                        "item × IES × curso, que permanece nos CSV.")

            with tab_o2:
                st.subheader("TBox — classes, propriedades e restrições")
                try:
                    from algoritmos.ontologia.ontologia_owl import (
                        CLASSES, DATA_PROPERTIES, OBJECT_PROPERTIES, SCHEMES)
                    df_cls = pd.DataFrame(
                        [{"Classe": c, "Superclasse": p or "—", "Rótulo": r, "Comentário": d}
                         for c, p, r, d in CLASSES])
                    st.dataframe(df_cls, use_container_width=True, hide_index=True)
                    st.markdown(f"**{len(OBJECT_PROPERTIES)} object properties** e "
                                f"**{len(DATA_PROPERTIES)} data properties**, além de "
                                f"**{sum(len(v[1]) for v in SCHEMES.values())} conceitos SKOS** "
                                f"em {len(SCHEMES)} esquemas contextuais.")
                    with st.expander("Object properties (domínio → range)"):
                        st.dataframe(pd.DataFrame(
                            [{"Propriedade": p, "Domínio": d or "—", "Range": r or "—",
                              "Inversa": i or "—"} for p, d, r, i, _c, _l in OBJECT_PROPERTIES]),
                            use_container_width=True, hide_index=True)
                    with st.expander("Data properties (domínio → range)"):
                        st.dataframe(pd.DataFrame(
                            [{"Propriedade": p, "Domínio": d or "—", "Range": str(r).split("#")[-1]}
                             for p, d, r, _l in DATA_PROPERTIES]),
                            use_container_width=True, hide_index=True)
                except Exception as exc:
                    st.warning(f"Não foi possível ler o módulo da ontologia: {exc}")

            with tab_o3:
                st.subheader("Consultas SPARQL de exemplo")
                consultas = sorted(pasta_queries.glob("*.rq")) if pasta_queries.exists() else []
                if not consultas or not caminho_owl.exists():
                    st.info("Gere a ontologia para habilitar as consultas.")
                else:
                    @st.cache_resource(show_spinner="Carregando grafo OWL (uma vez por sessão)...")
                    def _grafo_owl(caminho_str, mtime):
                        # ``mtime`` sem underscore entra na chave do cache: se o
                        # .owl for regenerado, o grafo e recarregado.
                        from rdflib import Graph
                        grafo = Graph()
                        grafo.parse(caminho_str, format="xml")
                        return grafo

                    @st.cache_data(show_spinner=False)
                    def _rodar_consulta(caminho_str, mtime, texto):
                        from rdflib import Graph
                        grafo = _grafo_owl(caminho_str, mtime)
                        resultado = grafo.query(texto)
                        colunas = [str(v) for v in resultado.vars] if resultado.vars else []
                        linhas = [[None if v is None else str(v) for v in linha]
                                  for linha in resultado]
                        return colunas, linhas

                    nomes = [q.name for q in consultas]
                    escolha = st.selectbox("Consulta:", nomes, key="onto_query")
                    arquivo = consultas[nomes.index(escolha)]
                    texto = arquivo.read_text(encoding="utf-8")
                    with st.expander("Ver o SPARQL", expanded=False):
                        st.code(texto, language="sparql")
                    if st.button("Executar consulta", key="onto_run"):
                        try:
                            mtime = caminho_owl.stat().st_mtime
                            colunas, linhas = _rodar_consulta(str(caminho_owl), mtime, texto)
                            st.success(f"{len(linhas)} linha(s) · colunas: {', '.join(colunas)}")
                            st.dataframe(pd.DataFrame(linhas, columns=colunas),
                                         use_container_width=True, hide_index=True)
                        except Exception as exc:
                            st.error(f"Falha na consulta: {type(exc).__name__}: {exc}")

            with tab_o4:
                st.subheader("Proveniência, integridade e arquivos")
                st.markdown("**Fontes declaradas no manifesto** (hash SHA-256 de cada uma):")
                st.dataframe(pd.DataFrame({"Fonte": manifesto.get("fontes", [])}),
                             use_container_width=True, hide_index=True)
                st.markdown("**Artefatos gerados:**")
                arquivos = manifesto.get("arquivos", {})
                if arquivos:
                    df_arq = pd.DataFrame([
                        {"Formato": k, "Arquivo": v.get("nome"), "Bytes": v.get("bytes"),
                         "SHA-256": (v.get("sha256") or "")[:16] + "…"}
                        for k, v in arquivos.items()])
                    st.dataframe(df_arq, use_container_width=True, hide_index=True)

                st.markdown("**Stack ontológica**")
                @st.cache_data(show_spinner=False, ttl=600)
                def _stack_onto():
                    from algoritmos.ontologia.adaptadores import status_stack
                    return status_stack()

                try:
                    df_stack = pd.DataFrame([
                        {"Biblioteca": i["nome"],
                         "Obrigatória": "sim" if i["obrigatoria"] else "não",
                         "Disponível": "OK" if i["instalado"] else "ausente",
                         "Versão": i["versao"] or "—",
                         "Observação": i["observacao"] or ""}
                        for i in _stack_onto()])
                    st.dataframe(df_stack, use_container_width=True, hide_index=True)
                except Exception as exc:
                    st.warning(f"Stack não inspecionada: {exc}")
                st.caption("OAK é opcional e, quando instalado em venv isolado, é detectado via "
                           "`PRISM_OAK_PYTHON` ou `.venv-oak/`.")

elif aba == ABAS[20]:
    from dashboard.abas import aba_qualidade
    aba_qualidade.render({
        "edicao": EDICAO_MOTORES,
        "chave_curso": globals().get("chave_curso"),
    })

# ===========================================================================
# RODAPE
# ===========================================================================
st.divider()
st.caption(f"PRISM-EDU v4.0 | {sel_label} | Registros: {n_reg:,} | Aba: {aba}")
