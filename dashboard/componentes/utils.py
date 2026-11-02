"""
PRISM-EDU Dashboard -- Funcoes auxiliares e de cache de dados.
Extraido de app.py para modularizacao.
"""
import streamlit as st
import pandas as pd
import numpy as np
import unicodedata
import re
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config import (
    RAIZ_PROJETO, PASTA_DADOS_PROCESSADOS, PASTA_DADOS_EXTERNOS,
    PASTA_INTERNACIONAIS, PASTA_MODELOS, CURSOS_MAP, CURSOS_REVERSO,
    CURSOS_MAP_POR_ANO, SEPARADOR, ENCODING,
    pasta_saida_edicao,
)

# ---------------------------------------------------------------------------
# CONSTANTES DE CAMINHOS
# ---------------------------------------------------------------------------
PASTA_REF = RAIZ_PROJETO.parent / "modeloprojetoENADE2023" / "arquivosgerados"
PASTA_ENADE_EXT = PASTA_DADOS_EXTERNOS / "enade"
if not PASTA_ENADE_EXT.exists():
    PASTA_ENADE_EXT = PASTA_DADOS_PROCESSADOS / "por_ano"
PASTA_LIC = PASTA_DADOS_PROCESSADOS / "enadeLicenciaturas"
PASTA_ENAMED = PASTA_DADOS_PROCESSADOS / "enamed"
PASTA_MOD = RAIZ_PROJETO / "modelos"
PASTA_EDA = PASTA_DADOS_PROCESSADOS
# Artefatos CDM/DINA e da ponte LCA->CDM do PRISM-EDU (nao usar a referencia externa).
PASTA_CDM_XLSX = PASTA_MOD / "cdm"
PASTA_LCA_CDM = PASTA_MOD / "cdm"


def _subpastas_cdm():
    """Subpastas de modelos/cdm (uma por edicao), mais recentes primeiro."""
    if not PASTA_CDM_XLSX.exists():
        return []
    return sorted([p for p in PASTA_CDM_XLSX.iterdir() if p.is_dir()],
                  key=lambda p: p.name, reverse=True)


def _pasta_cdm(edicao=""):
    """Pasta de artefatos CDM/DINA, priorizando modelos/cdm/<edicao>."""
    if edicao:
        local = PASTA_CDM_XLSX / edicao
        if local.exists() and any(local.iterdir()):
            return local
    for local in _subpastas_cdm():
        if (any(local.glob("diagnostico_cognitivo_*.xlsx"))
                or (local / "comparacao_lca_vs_dina.csv").exists()):
            return local
    return PASTA_CDM_XLSX

PASTA_ANALISE_IES = PASTA_DADOS_PROCESSADOS / "analise_por_ies_curso_enade.csv"
PASTA_ANALISE_LIC = PASTA_DADOS_PROCESSADOS / "analise_por_questao_ies_licenciaturas_2025.csv"
PASTA_ANALISE_ENAMED = PASTA_DADOS_PROCESSADOS / "analise_por_questao_ies_enamed_2025.csv"
PASTA_QUESTOES_XLSX = Path(__file__).resolve().parent.parent.parent.parent / "seriesTemporais_questoes" / "resultados"


# ---------------------------------------------------------------------------
# FUNCOES AUXILIARES PURAS
# ---------------------------------------------------------------------------
def _norm(s):
    s = unicodedata.normalize("NFKD", str(s))
    return "".join(c for c in s if not unicodedata.combining(c)).lower().replace(" ", "_")


def _ler(caminho):
    if caminho and caminho.exists():
        return pd.read_csv(caminho, sep=SEPARADOR, encoding=ENCODING, low_memory=False)
    return None


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


def limitar_lista_texto(texto, separador, limite):
    """Limita uma lista separada por um separador (ex.: ' | ') a 'limite' itens."""
    if pd.isna(texto) or str(texto).strip() == "" or str(texto).lower() == "nan":
        return "Nenhum dado ou nao aplicavel"
    itens = [i.strip() for i in str(texto).split(separador) if i.strip()]
    return f" {separador} ".join(itens[:limite])


# ---------------------------------------------------------------------------
# MOTORES: EDICAO / ANO DOS RESULTADOS (modelos/<motor>/<edicao>)
# ---------------------------------------------------------------------------
def listar_edicoes_motor(motor):
    """Edicoes com resultados gravados em modelos/<motor>/. Lista vazia se o
    motor ainda nao tem saida por edicao (layout legado 'flat')."""
    pasta = PASTA_MOD / motor
    if not pasta.exists():
        return []
    return sorted(p.name for p in pasta.iterdir() if p.is_dir())


def selecionar_edicao_motor(motor, chave, label="Edicao/Ano dos resultados:"):
    """Combo de selecao de edicao para os resultados de um motor.
    Retorna '' (raiz / mais recente) ou o nome da edicao (ex.: 'enade_2019')."""
    edicoes = listar_edicoes_motor(motor)
    if not edicoes:
        return ""
    opcoes = ["<mais recente>"] + edicoes
    sel = st.selectbox(label, opcoes, key=f"{chave}_edicao_{motor}")
    return "" if sel.startswith("<") else sel


def pasta_motor(motor, edicao=""):
    """Pasta de resultados do motor: modelos/<motor>/<edicao>/ quando ha
    resultados por edicao; modelos/<motor>/ caso contrario (compatibilidade)."""
    return PASTA_MOD / motor if not edicao else PASTA_MOD / motor / edicao


# ---------------------------------------------------------------------------
# FUNCOES CACHEADAS DE CARREGAMENTO
# ---------------------------------------------------------------------------
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


@st.cache_data(show_spinner=False)
def carregar_dados_resumidos():
    """Carrega o CSV consolidado de analise por IES/curso (fase 5)."""
    if PASTA_ANALISE_IES is None or not PASTA_ANALISE_IES.exists():
        return None
    return pd.read_csv(PASTA_ANALISE_IES, sep=SEPARADOR, encoding=ENCODING, low_memory=False)


@st.cache_data(show_spinner=False)
def carregar_lca_geral(edicao=""):
    """Relatorio geral de IES da LCA (modelos/lca/01_* ou edicao)."""
    path = (pasta_saida_edicao("lca", edicao) if edicao else PASTA_MOD / "lca") / "01_relatorio_geral_por_ies.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, sep=";", decimal=",", dtype={"ies": str}, low_memory=False)
    if "ies" in df.columns:
        df["ies"] = df["ies"].str.strip()
    return df


@st.cache_data(show_spinner=False)
def carregar_lca_classes(edicao=""):
    """Caracterizacao das classes latentes (modelos/lca/02_* ou edicao)."""
    path = (pasta_saida_edicao("lca", edicao) if edicao else PASTA_MOD / "lca") / "02_caracterizacao_das_classes.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, sep=";", decimal=",", dtype={"ies": str}, low_memory=False)
    if "ies" in df.columns:
        df["ies"] = df["ies"].str.strip()
    return df


@st.cache_data(show_spinner=False)
def carregar_lca_criterios(edicao=""):
    """Criterios de selecao de K da LCA (modelos/lca/03_* ou edicao)."""
    path = (pasta_saida_edicao("lca", edicao) if edicao else PASTA_MOD / "lca") / "03_criterios_de_selecao_k.csv"
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
    candidatos = [_pasta_cdm(edicao), PASTA_CDM_XLSX] + _subpastas_cdm()
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
    if PASTA_CDM_XLSX.exists():
        for xlsx in PASTA_CDM_XLSX.rglob("diagnostico_cognitivo_*.xlsx"):
            if nome_base in _norm(xlsx.stem):
                try:
                    return pd.read_excel(xlsx, engine="openpyxl")
                except Exception:
                    continue
    return None


@st.cache_data(show_spinner=False)
def carregar_reanalise_resumo(edicao=""):
    path = (pasta_saida_edicao("lca", edicao) if edicao else PASTA_MOD / "lca") / "reanalise_resumo.csv"
    if not path.exists():
        return None
    return pd.read_csv(path, sep=";", decimal=",", low_memory=False)


@st.cache_data(show_spinner=False)
def carregar_reanalise_por_ies(edicao=""):
    path = (pasta_saida_edicao("lca", edicao) if edicao else PASTA_MOD / "lca") / "reanalise_por_ies.csv"
    if not path.exists():
        return None
    return pd.read_csv(path, sep=";", decimal=",", dtype={"ies": str}, low_memory=False)


@st.cache_data(show_spinner=False)
def carregar_robustez_item(edicao=""):
    path = (pasta_saida_edicao("lca", edicao) if edicao else PASTA_MOD / "lca") / "robustez_brancos_por_item.csv"
    if not path.exists():
        return None
    return pd.read_csv(path, sep=";", decimal=",", low_memory=False)


@st.cache_data(show_spinner=False)
def carregar_robustez_oc(edicao=""):
    path = (pasta_saida_edicao("lca", edicao) if edicao else PASTA_MOD / "lca") / "robustez_brancos_por_oc.csv"
    if not path.exists():
        return None
    return pd.read_csv(path, sep=";", decimal=",", low_memory=False)


@st.cache_data(show_spinner=False)
def _carregar_analise_ies(ano=None):
    """Carrega a analise por questao da edicao (ano) selecionada.
    Usa os CSVs por ano (memoria leve) em vez do CSV consolidado de 4GB.
    """
    ano = ano or 2023
    partes = []

    # ENADE: arquivo por ano (contem as questoes reais da edicao).
    caminho_enade = PASTA_DADOS_PROCESSADOS / f"analise_por_questao_ies_enade_{ano}.csv"
    if caminho_enade.exists():
        partes.append(pd.read_csv(caminho_enade, sep=";", encoding="utf-8-sig", low_memory=False))

    # Licenciaturas/ENAMED existem apenas na edicao 2025.
    if ano == 2025:
        if PASTA_ANALISE_LIC.exists():
            partes.append(pd.read_csv(PASTA_ANALISE_LIC, sep=";", encoding="utf-8-sig", low_memory=False))
        if PASTA_ANALISE_ENAMED.exists():
            partes.append(pd.read_csv(PASTA_ANALISE_ENAMED, sep=";", encoding="utf-8-sig", low_memory=False))

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


def _extrair_ano_filtro(sel_tipo, sel_id):
    """Extrai o ano/edicao do exame a partir do contexto de selecao."""
    try:
        if sel_tipo == "enade" and sel_id and str(sel_id).startswith("enade_"):
            return int(str(sel_id).split("_")[-1])
        if sel_tipo in ("lic", "enamed"):
            return 2025
    except (ValueError, IndexError):
        pass
    return 2023


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


def obter_filtro_analise(df_a, ies_sel, curso_codigo, sel_tipo, sel_id):
    """Determina o filtro de analise com base no contexto global.
    Garante que os dados carregados correspondam a edicao (ano) selecionada."""
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
