"""
Perfil cognitivo por aluno x Objeto de Conhecimento (OC) - PRISM-EDU
====================================================================

Gera, por curso, o artefato 'diagnostico_cognitivo_<curso>.xlsx': a taxa de
acerto observada de cada aluno nas questoes que medem cada OC (Anexo IX /
INEP).

INTEGRIDADE (rotulo honesto):
    Este artefato NAO e um modelo de diagnostico cognitivo (CDM/DINA). E a
    taxa de acerto observada por OC, agregada por aluno - um retrato
    DESCRITIVO, nao um modelo latente. O diagnostico cognitivo formal esta em
    'ponte_lca_cdm.py' (DINA por EM). O nome do arquivo e mantido por
    compatibilidade com o dashboard, mas o conteudo e a media de acerto real.

    Cada workbook possui duas abas:
      1. 'Perfil_Aluno_OC'  - os dados (primeira aba, lida pelo dashboard);
      2. 'LEIA-ME'          - metodo, fonte, limitacoes e aviso de que a
                              planilha nao e um CDM/DINA.

Colunas de saida (mesmo layout consumido pelo dashboard):
    ALUNO | CO_GRUPO | NOME_CURSO | Conhecimentos Gerais | <OC1..OCk> |
    MAIOR_DOMINIO_DISCIPLINA | PIOR_DEFICIENCIA_DISCIPLINA

'Conhecimentos Gerais' = media de acerto nas Q1-Q9 (Formacao Geral).
'CO_GRUPO' e o codigo de grupo do curso (chave de CURSOS_MAP), nao o
CO_CURSO da IES; o rotulo anterior 'CO_CURSO' era incorreto.
"""
import unicodedata
import re
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config import SEPARADOR, ENCODING, CURSOS_MAP, pasta_saida_edicao
from algoritmos.cdm.dina_em import localizar_mestre_oc

warnings.filterwarnings("ignore")

COLUNAS_Q = [f"Q{i}" for i in range(1, 39)]
COLUNAS_FG = [f"Q{i}" for i in range(1, 10)]

ROTULO_METODO = "taxa de acerto observada por aluno x OC (descritivo)"
NOTA_INTEGRIDADE = (
    "ESTE ARTEFATO NAO E UM CDM/DINA. As colunas de OC sao a media de acerto "
    "observada nas questoes mapeadas para cada OC (Anexo IX do INEP). Nao ha "
    "estimacao de atributos latentes nem probabilidade de dominio. O "
    "diagnostico cognitivo formal (DINA por EM) esta em ponte_lca_cdm.py."
)


def normalizar(texto):
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\W", "", t).lower()


def formatar_nome_arquivo(nome):
    t = unicodedata.normalize("NFKD", str(nome))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r'[\\/:*?"<>|]+', "", t.lower().replace(" ", "_"))


def _localizar_microdados(edicao):
    from algoritmos.cdm.ponte_lca_cdm import localizar_microdados_edicao
    return localizar_microdados_edicao(edicao)


def _carregar_mestre(mestre=None):
    """Carrega e normaliza a matriz item-OC (ou usa o DataFrame injetado)."""
    if mestre is None:
        mestre = pd.read_csv(localizar_mestre_oc(), sep=SEPARADOR, encoding="utf-8-sig")
    else:
        mestre = mestre.copy()
    mestre["oc_principal"] = mestre["oc_principal"].fillna("").astype(str).str.strip()
    mestre["_curso_norm"] = mestre["curso"].map(normalizar)
    return mestre


def _questao_do_item(item):
    """Retorna a coluna Q* do item, preferindo 'questao' a 'posicao'."""
    questao = str(item.get("questao", "")).strip()
    if re.fullmatch(r"Q\d+", questao):
        return questao
    try:
        return f"Q{int(item['posicao'])}"
    except (TypeError, ValueError):
        return ""


def _preparar_microdados(df):
    """Binariza as questoes (1 = acerto; qualquer outro valor = erro)."""
    df = df.copy()
    if "TP_PR_GER" in df.columns:
        df = df[df["TP_PR_GER"] > 0].copy()
    for col in COLUNAS_Q:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").apply(
                lambda x: 1 if x == 1 else 0)
    return df


def _df_metadata(edicao, nome, cod, n_alunos, ocs, n_itens_por_oc, cols_fg):
    """DataFrame vertical (campo/valor) com o rotulo honesto do artefato."""
    return pd.DataFrame({
        "campo": [
            "ROTULO_DO_ARTEFATO", "METODO", "AVISO_DE_INTEGRIDADE", "EDICAO",
            "CURSO", "CO_GRUPO", "N_ALUNOS", "N_OCS", "N_ITENS_POR_OC",
            "CONHECIMENTOS_GERAIS", "FONTE_MATRIZ_OC", "GERADO_EM",
        ],
        "valor": [
            "diagnostico_cognitivo_<curso>.xlsx",
            ROTULO_METODO,
            NOTA_INTEGRIDADE,
            edicao,
            nome,
            cod,
            n_alunos,
            len(ocs),
            "; ".join(f"{oc}: {n}" for oc, n in n_itens_por_oc.items()),
            f"media de acerto em {', '.join(cols_fg)}" if cols_fg else "indisponivel",
            "mestre_questao_oc.csv (matriz item-OC do INEP / Anexo IX)",
            datetime.now().isoformat(timespec="seconds"),
        ],
    })


def gerar_perfis_edicao(edicao="enade_2023", limite_cursos=None, df=None,
                        mestre=None, pasta_saida=None):
    """Gera diagnostico_cognitivo_<curso>.xlsx (media aluno x OC) por curso.

    Parametros opcionais (df, mestre, pasta_saida) existem para testes de
    regressao e para o orquestrador por edicao; o uso normal e apenas
    ``edicao``.
    """
    print("=" * 72)
    print(f"  PRISM-EDU: Perfil cognitivo por aluno x OC - {edicao}")
    print("=" * 72)

    mestre = _carregar_mestre(mestre)
    if df is None:
        caminho_micro = _localizar_microdados(edicao)
        cabecalho = pd.read_csv(caminho_micro, sep=SEPARADOR, encoding=ENCODING,
                                nrows=0).columns
        usecols = [c for c in ["ALUNO", "CO_GRUPO", "CO_CURSO", "CO_IES", "TP_PR_GER"]
                   + COLUNAS_Q if c in cabecalho]
        df = pd.read_csv(caminho_micro, sep=SEPARADOR, encoding=ENCODING,
                         usecols=usecols, low_memory=False)
    df = _preparar_microdados(df)

    pasta = Path(pasta_saida) if pasta_saida is not None \
        else pasta_saida_edicao("cdm", edicao)
    pasta.mkdir(parents=True, exist_ok=True)

    gerados = []
    cursos = list(CURSOS_MAP.items())
    if limite_cursos:
        cursos = cursos[:limite_cursos]

    for cod, nome in cursos:
        sub_mestre = mestre[mestre["_curso_norm"] == normalizar(nome)]
        if sub_mestre.empty:
            continue
        if "CO_GRUPO" in df.columns:
            df_curso = df[df["CO_GRUPO"] == cod]
        elif "CO_CURSO" in df.columns:
            df_curso = df[df["CO_CURSO"] == cod]
        else:
            df_curso = pd.DataFrame()
        if df_curso.empty:
            continue

        df_curso = df_curso.reset_index(drop=True)
        # questoes por OC principal (usa o rotulo Q* do proprio mestre)
        oc_por_questao = {}
        for _, item in sub_mestre.iterrows():
            oc = item["oc_principal"]
            q = _questao_do_item(item)
            if oc and q:
                oc_por_questao.setdefault(oc, []).append(q)
        ocs = [oc for oc, _ in sorted(oc_por_questao.items(),
                                      key=lambda kv: -len(kv[1]))]

        saida = pd.DataFrame()
        if "ALUNO" in df_curso.columns:
            saida["ALUNO"] = df_curso["ALUNO"].values
        else:
            saida["ALUNO"] = df_curso.index.astype(str)
        saida["CO_GRUPO"] = cod
        saida["NOME_CURSO"] = nome
        cols_fg = [c for c in COLUNAS_FG if c in df_curso.columns]
        if cols_fg:
            saida["Conhecimentos Gerais"] = (
                df_curso[cols_fg].to_numpy(dtype=float).mean(axis=1) * 100).round(2)
        else:
            saida["Conhecimentos Gerais"] = np.nan

        ocs_validas = []
        n_itens_por_oc = {}
        for oc in ocs:
            cols = [c for c in oc_por_questao[oc] if c in df_curso.columns]
            if cols:
                saida[oc] = (df_curso[cols].to_numpy(dtype=float).mean(axis=1) * 100).round(2)
                ocs_validas.append(oc)
                n_itens_por_oc[oc] = len(cols)

        if ocs_validas:
            notas = saida[ocs_validas]
            saida["MAIOR_DOMINIO_DISCIPLINA"] = notas.idxmax(axis=1)
            saida["PIOR_DEFICIENCIA_DISCIPLINA"] = notas.idxmin(axis=1)
        else:
            saida["MAIOR_DOMINIO_DISCIPLINA"] = "SEM_OC"
            saida["PIOR_DEFICIENCIA_DISCIPLINA"] = "SEM_OC"

        meta = _df_metadata(edicao, nome, cod, len(saida), ocs_validas,
                            n_itens_por_oc, cols_fg)

        destino = pasta / f"diagnostico_cognitivo_{formatar_nome_arquivo(nome)}.xlsx"
        with pd.ExcelWriter(destino, engine="openpyxl") as writer:
            saida.to_excel(writer, sheet_name="Perfil_Aluno_OC", index=False)
            meta.to_excel(writer, sheet_name="LEIA-ME", index=False)
        gerados.append(nome)
        print(f"  {nome}: {len(saida)} alunos x {len(ocs_validas)} OCs -> {destino.name}")

    print(f"\n  Perfis gerados para {len(gerados)} cursos em {pasta}")
    return gerados


def executar_perfil_edicao(caminho_csv=None, df=None):
    """Motor por edicao (interface executar_por_edicao): perfil aluno x OC."""
    import os
    edicao = os.environ.get("PRISM_EDICAO", "") or "enade_2023"
    return gerar_perfis_edicao(edicao=edicao, df=df)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Perfil cognitivo por aluno x OC")
    ap.add_argument("--edicao", default="enade_2023")
    ap.add_argument("--limite-cursos", type=int, default=None)
    args = ap.parse_args()
    gerar_perfis_edicao(edicao=args.edicao, limite_cursos=args.limite_cursos)
