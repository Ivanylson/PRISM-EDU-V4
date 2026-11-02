"""
Pipeline de Drift Temporal entre Edicoes (proficiencia por OC + notas)
======================================================================
O drift entre edições NÃO pode comparar colunas Q* cruas (o rótulo "Q1" de
2011 é outro item em 2019) nem anos-calendário consecutivos: o ENADE avalia
áreas diferentes a cada ano. A comparação correta é *dentro do mesmo curso*,
entre as edições em que aquele curso foi avaliado (ciclo trienal).

Unidades medidas por edição:
  * proficiencia por OC (0-100), derivada dos itens mapeados na própria edição
    (dados/processados/analise_por_questao_ies_<edicao>.csv);
  * notas publicadas (NT_GER / NT_DIS_CE).

Modos (PRISM_DRIFT_MODO):
  consecutivas_tendencia (default): cada edição do curso vs. a edição anterior
                                    em que o MESMO curso foi avaliado + matriz
                                    OC x par de edições;
  consecutivas:                    idem, sem matriz de tendência;
  baseline:                        cada edição do curso vs. uma referência fixa
                                   (PRISM_DRIFT_BASELINE, default 2019), quando
                                   o curso também foi avaliado nela.

Variáveis de ambiente: PRISM_EDICAO, PRISM_DRIFT_MODO, PRISM_DRIFT_BASELINE,
PRISM_DRIFT_MAX_ALUNOS (default 20000).
"""
import json
import os
import re
import time
import unicodedata
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from config import (
    CURSOS_MAP_POR_ANO,
    ENCODING,
    PASTA_DADOS_PROCESSADOS,
    PASTA_MODELOS,
    SEED_ALEATORIA,
    SEPARADOR,
    caminho_arquivo_edicao,
    caminho_saida_algoritmo,
    derivar_colunas_questoes,
    listar_edicoes_disponiveis,
    nome_grupo_ano,
)
from algoritmos.drift.detectar_drift import (
    drift_pca_multivariado,
    drift_univariado,
)

MODOS = ("consecutivas_tendencia", "consecutivas", "baseline")
MODO_PADRAO = "consecutivas_tendencia"
NOTAS_COMPARADAS = ("NT_GER", "NT_DIS_CE")
COLUNAS_EXTRAS = ("ALUNO", "CO_IES", "CO_CURSO", "CO_GRUPO", "NU_ANO") + NOTAS_COMPARADAS
MIN_ALUNOS_CURSO = 30
MIN_ITENS_OC = 1
MAX_ALUNOS_PADRAO = 20000


# ---------------------------------------------------------------------------
# Normalização (mesma regra do dashboard: sem acentos, minúsculas, sem pontuação)
# ---------------------------------------------------------------------------
def normalizar_texto(texto):
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"\W", " ", t)).strip().lower()


def remover_prefixo_oc(texto):
    """Remove prefixos tipo 'IV - ' ou 'V. ' de rótulos de OC.

    Exige separador (traço/ponto/dois-pontos) ou espaço depois do algarismo
    romano, para não cortar palavras comuns que começam com I/V/X (ex.:
    'INFORMACAO' permanece intacto).
    """
    t = str(texto).strip()
    if re.match(r"^OUTRAS_COMPETENCIAS\s*$", t, re.IGNORECASE):
        return "outras_competencias"
    m = re.match(r"^([IVXLCDM]{1,6})(?:\s*[-.:]\s*|\s+)(.+)$", t)
    if m and m.group(2).strip():
        return m.group(2).strip().strip(";").strip()
    return t.strip(";").strip()


def chave_oc(rotulo):
    """Chave estável de OC (prefixo romano removido + normalização)."""
    return normalizar_texto(remover_prefixo_oc(rotulo))


def ano_de_edicao(edicao):
    m = re.search(r"(\d{4})$", str(edicao or ""))
    return int(m.group(1)) if m else None


def _edicao_familia(edicao):
    if str(edicao).startswith("enade_"):
        return "enade"
    return str(edicao).rsplit("_", 1)[0]


def edicoes_enade():
    return [e for e in listar_edicoes_disponiveis() if _edicao_familia(e) == "enade"]


# ---------------------------------------------------------------------------
# Calendário de avaliação por curso (qual curso foi avaliado em qual ano)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def ano_para_cursos():
    """dict {ano: {curso_key: grupo_do_ano}} a partir de CURSOS_MAP_POR_ANO."""
    mapa = {}
    for ano_str, grupos in CURSOS_MAP_POR_ANO.items():
        try:
            ano = int(ano_str)
        except (TypeError, ValueError):
            continue
        mapa[ano] = {normalizar_texto(nome): int(cod) for cod, nome in grupos.items()}
    return mapa


@lru_cache(maxsize=1)
def curso_para_anos():
    """dict {curso_key: [anos em que o curso foi avaliado]} (ordenado)."""
    inverso = {}
    for ano, cursos in ano_para_cursos().items():
        for curso_key in cursos:
            inverso.setdefault(curso_key, []).append(ano)
    return {k: sorted(v) for k, v in inverso.items()}


def edicao_anterior_do_curso(edicao, curso_key):
    """Edição do ENADE imediatamente anterior em que o MESMO curso foi avaliado."""
    ano = ano_de_edicao(edicao)
    if ano is None:
        return None
    anteriores = [a for a in curso_para_anos().get(curso_key, []) if a < ano]
    if not anteriores:
        return None
    ref = f"enade_{anteriores[-1]}"
    return ref if caminho_arquivo_edicao(ref) is not None else None


def edicao_baseline(curso_key, baseline=None):
    """Edição de referência fixa do modo baseline, se o curso foi avaliado nela."""
    ano_base = int(baseline or os.environ.get("PRISM_DRIFT_BASELINE", "2019") or 2019)
    if ano_base not in curso_para_anos().get(curso_key, []):
        return None
    ref = f"enade_{ano_base}"
    return ref if caminho_arquivo_edicao(ref) is not None else None


def referencia_do_curso(edicao, curso_key, modo=MODO_PADRAO, baseline=None):
    if modo == "baseline":
        ref = edicao_baseline(curso_key, baseline)
        return ref if ref and ref != edicao else None
    ref = edicao_anterior_do_curso(edicao, curso_key)
    return ref if ref and ref != edicao else None


# ---------------------------------------------------------------------------
# Mapa item -> OC da edição (fonte: análise por questão/IES do INEP)
# ---------------------------------------------------------------------------
def caminho_mapa_oc(edicao):
    caminho = PASTA_DADOS_PROCESSADOS / f"analise_por_questao_ies_{edicao}.csv"
    return caminho if caminho.exists() else None


def carregar_mapa_oc(edicao, caminho=None):
    """Tabela bruta QUESTAO/OC1/OC2/OC3 da edição (None se não existir)."""
    caminho = caminho or caminho_mapa_oc(edicao)
    if caminho is None:
        return None
    return pd.read_csv(caminho, sep=SEPARADOR, encoding="utf-8-sig", low_memory=False)


def mapa_para_grupo(tabela, co_grupo=None):
    """dict {Qn: [(chave_oc, rotulo_original)]} para um CO_GRUPO da edição."""
    if tabela is None or tabela.empty:
        return {}
    tab = tabela
    if co_grupo is not None and "CO_GRUPO" in tab.columns:
        tab = tab[pd.to_numeric(tab["CO_GRUPO"], errors="coerce") == co_grupo]
    mapa = {}
    for _, linha in tab.iterrows():
        q = str(linha.get("QUESTAO", "")).strip().upper()
        if not re.fullmatch(r"Q\d{1,3}", q):
            continue
        pares = mapa.setdefault(q, [])
        vistos = {k for k, _ in pares}
        for col in ("OC1", "OC2", "OC3"):
            rotulo = linha.get(col)
            if pd.isna(rotulo) or not str(rotulo).strip():
                continue
            chave = chave_oc(rotulo)
            if not chave or chave in vistos:
                continue
            vistos.add(chave)
            pares.append((chave, str(rotulo).strip()))
    return mapa


def _agrupar_por_chave(mapa):
    """dict {chave: [Qn, ...]} a partir do mapa {Qn: [(chave, rotulo)]}."""
    agrupado = {}
    for q, pares in mapa.items():
        for chave, _ in pares:
            agrupado.setdefault(chave, []).append(q)
    return agrupado


def _rotulo_de(mapa, chave):
    for pares in mapa.values():
        for c, rotulo in pares:
            if c == chave:
                return rotulo
    return chave


# ---------------------------------------------------------------------------
# Microdados e proficiência por OC
# ---------------------------------------------------------------------------
def carregar_microdados(edicao, max_alunos=None, colunas=None):
    """Carrega Q* + extras da edição (leve), com amostragem opcional."""
    caminho = caminho_arquivo_edicao(edicao)
    if caminho is None:
        return None
    header = pd.read_csv(caminho, sep=SEPARADOR, encoding=ENCODING, nrows=0).columns.tolist()
    if colunas is None:
        usecols = [c for c in header
                   if (isinstance(c, str) and re.fullmatch(r"Q\d{1,3}", c)) or c in COLUNAS_EXTRAS]
    else:
        usecols = [c for c in colunas if c in header]
    df = pd.read_csv(caminho, sep=SEPARADOR, encoding=ENCODING,
                     usecols=usecols, low_memory=False)
    if max_alunos and len(df) > max_alunos:
        df = df.sample(max_alunos, random_state=SEED_ALEATORIA)
    return df


def proficiencia_oc(df, tabela_mapa, min_itens=MIN_ITENS_OC, edicao=None):
    """Proficiência 0-100 por aluno/OC, calculada com os itens da própria edição.

    Retorna (DataFrame, info):
      DataFrame: colunas de OC (chave) + CO_GRUPO, NOME_CURSO, CURSO_KEY e
                 NT_GER/NT_DIS_CE (se existirem). Uma OC por curso (linhas de
                 outros cursos ficam com NaN naquela coluna).
      info: {chave: {"rotulo": ..., "n_itens": ..., "grupo": ...}}.
    """
    if df is None or df.empty or tabela_mapa is None:
        return pd.DataFrame(), {}
    df = df.copy()
    if "CO_GRUPO" not in df.columns:
        df["CO_GRUPO"] = 0
    df["CO_GRUPO"] = pd.to_numeric(df["CO_GRUPO"], errors="coerce").fillna(0).astype(int)
    ano = ano_de_edicao(edicao)
    df["NOME_CURSO"] = df["CO_GRUPO"].map(lambda g: nome_grupo_ano(g, ano))
    df["CURSO_KEY"] = df["NOME_CURSO"].map(normalizar_texto)

    questoes_disponiveis = set(derivar_colunas_questoes(df)) if len(df) else set()
    base = {
        "CO_GRUPO": df["CO_GRUPO"],
        "NOME_CURSO": df["NOME_CURSO"],
        "CURSO_KEY": df["CURSO_KEY"],
    }
    for c in NOTAS_COMPARADAS:
        if c in df.columns:
            base[c] = pd.to_numeric(df[c], errors="coerce")

    info = {}
    colunas_oc = {}
    for g in sorted(df["CO_GRUPO"].unique()):
        mapa_g = mapa_para_grupo(tabela_mapa, co_grupo=g)
        mascara = df["CO_GRUPO"] == g
        if not mascara.any() or not mapa_g:
            continue
        for chave, itens in _agrupar_por_chave(mapa_g).items():
            itens_presentes = [q for q in itens if q in questoes_disponiveis]
            if len(itens_presentes) < max(1, min_itens):
                continue
            valores = df.loc[mascara, itens_presentes].apply(pd.to_numeric, errors="coerce").mean(axis=1) * 100.0
            colunas_oc.setdefault(chave, pd.Series(np.nan, index=df.index))
            colunas_oc[chave].loc[mascara] = valores
            info[chave] = {
                "rotulo": _rotulo_de(mapa_g, chave),
                "n_itens": len(itens_presentes),
                "grupo": int(g),
            }
    if colunas_oc:
        base.update(colunas_oc)
    return pd.DataFrame(base), info


# ---------------------------------------------------------------------------
# Comparação entre edições, curso a curso
# ---------------------------------------------------------------------------
def _comparar_um_curso(a, b, oc_a, oc_b, info_ref, info_prod, notas):
    oc_comuns = [c for c in oc_a if c in oc_b]
    colunas = oc_comuns + [c for c in notas if c in a.columns and c in b.columns]
    if not colunas:
        return None, None
    uni = drift_univariado(a[colunas], b[colunas], colunas)
    if uni is None or uni.empty:
        return None, None
    uni = uni.rename(columns={"Coluna": "Variavel"})
    uni.insert(0, "Curso", a["NOME_CURSO"].iloc[0])
    uni.insert(1, "CO_GRUPO_ref", int(a["CO_GRUPO"].iloc[0]))
    uni.insert(2, "CO_GRUPO_prod", int(b["CO_GRUPO"].iloc[0]))
    uni["Rotulo"] = uni["Variavel"].map(
        lambda v: info_ref.get(v, info_prod.get(v, {})).get("rotulo", v))
    pca = None
    if len(oc_comuns) >= 3:
        pca = drift_pca_multivariado(a[oc_comuns], b[oc_comuns], oc_comuns)
        if pca:
            pca = dict(pca)
            principais = pca.pop("principais", None)
            if principais is not None:
                pca["principais"] = principais.to_dict(orient="records")
    return uni, pca


def comparar_edicao_prod(edicao_prod, modo=MODO_PADRAO, baseline=None, max_alunos=None,
                         min_alunos_curso=MIN_ALUNOS_CURSO, df_prod=None, min_itens=MIN_ITENS_OC):
    """Compara cada curso avaliado em edicao_prod com a referência do MESMO curso.

    Retorna {'univariado': DataFrame (com coluna Referencia),
             'pca': {curso_key: {...,'referencia': ed_ref}},
             'meta': {...}, 'referencias_usadas': {ed_ref: {...}}}.
    """
    t0 = time.time()
    meta = {
        "edicao_ref": "", "edicao_prod": edicao_prod, "modo": modo,
        "n_alunos_ref": 0, "n_alunos_prod": 0, "n_cursos_comuns": 0,
        "n_cursos_nao_comuns": 0, "n_oc_comuns": 0, "n_comparacoes": 0,
        "n_drift": 0, "erro": None,
    }
    if df_prod is None:
        df_prod = carregar_microdados(edicao_prod, max_alunos=max_alunos)
    elif max_alunos and len(df_prod) > max_alunos:
        df_prod = df_prod.sample(max_alunos, random_state=SEED_ALEATORIA)
    if df_prod is None or df_prod.empty:
        meta["erro"] = "microdados_prod_ausentes"
        return {"univariado": pd.DataFrame(), "pca": {}, "meta": meta, "referencias_usadas": {}}

    tabela_prod = carregar_mapa_oc(edicao_prod)
    if tabela_prod is None:
        meta["erro"] = "mapa_item_oc_prod_ausente"
        return {"univariado": pd.DataFrame(), "pca": {}, "meta": meta, "referencias_usadas": {}}

    prof_prod, info_prod = proficiencia_oc(df_prod, tabela_prod, min_itens=min_itens, edicao=edicao_prod)
    meta["n_alunos_prod"] = int(len(prof_prod))
    if prof_prod.empty:
        meta["erro"] = "proficiencia_prod_vazia"
        return {"univariado": pd.DataFrame(), "pca": {}, "meta": meta, "referencias_usadas": {}}

    # curso -> referência do próprio curso
    por_ref = {}
    cursos_sem_ref = 0
    for curso_key, grupo in prof_prod.groupby("CURSO_KEY"):
        if len(grupo) < min_alunos_curso:
            continue
        ref = referencia_do_curso(edicao_prod, curso_key, modo, baseline)
        if ref is None:
            cursos_sem_ref += 1
            continue
        por_ref.setdefault(ref, []).append(curso_key)
    meta["n_cursos_nao_comuns"] = cursos_sem_ref

    linhas, pcas, refs_meta, oc_por_curso = [], {}, {}, {}
    for ed_ref, curso_keys in sorted(por_ref.items()):
        tabela_ref = carregar_mapa_oc(ed_ref)
        df_ref = carregar_microdados(ed_ref, max_alunos=max_alunos)
        if tabela_ref is None or df_ref is None or df_ref.empty:
            continue
        prof_ref, info_ref = proficiencia_oc(df_ref, tabela_ref, min_itens=min_itens, edicao=ed_ref)
        refs_meta[ed_ref] = {"n_alunos": int(len(prof_ref)), "cursos": sorted(curso_keys)}
        meta["n_alunos_ref"] += int(len(prof_ref))
        for curso_key in curso_keys:
            a = prof_ref[prof_ref["CURSO_KEY"] == curso_key]
            b = prof_prod[prof_prod["CURSO_KEY"] == curso_key]
            if len(a) < min_alunos_curso or len(b) < min_alunos_curso:
                continue
            oc_a = [c for c in a.columns if c in info_ref and a[c].notna().any()]
            oc_b = [c for c in b.columns if c in info_prod and b[c].notna().any()]
            uni, pca = _comparar_um_curso(a, b, oc_a, oc_b, info_ref, info_prod, NOTAS_COMPARADAS)
            oc_por_curso[curso_key] = len([c for c in oc_a if c in oc_b])
            if uni is not None:
                uni.insert(0, "Referencia", ed_ref)
                linhas.append(uni)
            if pca is not None:
                pca["referencia"] = ed_ref
                pcas[curso_key] = pca

    univariado = pd.concat(linhas, ignore_index=True) if linhas else pd.DataFrame()
    if not univariado.empty:
        meta["n_comparacoes"] = int(len(univariado))
        meta["n_drift"] = int(univariado["Status"].astype(str).str.startswith("Drift").sum())
        meta["n_oc_comuns"] = int(sum(oc_por_curso.values()))
        meta["n_cursos_comuns"] = int(univariado["Curso"].nunique())
    meta["tempo_s"] = round(time.time() - t0, 1)
    meta["referencias"] = sorted(refs_meta)
    meta["oc_comuns_por_curso"] = oc_por_curso
    return {"univariado": univariado, "pca": pcas, "meta": meta, "referencias_usadas": refs_meta}


# ---------------------------------------------------------------------------
# Persistência
# ---------------------------------------------------------------------------
def _pasta_global(pasta_drift=None):
    pasta = Path(pasta_drift) if pasta_drift else (PASTA_MODELOS / "drift")
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def _pasta_par(prod, pasta_drift=None):
    pasta = _pasta_global(pasta_drift) / prod
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def salvar_por_referencia(edicao_prod, resultado, pasta_drift=None):
    """Grava um CSV por referência (todas as colunas) e um JSON de PCA/meta.

    Retorna lista de (referencia, caminho_csv)."""
    pasta = _pasta_par(edicao_prod, pasta_drift)
    gravados = []
    univariado = resultado["univariado"]
    if not univariado.empty:
        for ref, grupo in univariado.groupby("Referencia"):
            caminho = pasta / f"drift_univariado_{ref}.csv"
            grupo.drop(columns=["Referencia"]).to_csv(caminho, index=False, encoding="utf-8")
            gravados.append((ref, caminho))
    with open(pasta / "drift_pca.json", "w", encoding="utf-8") as f:
        json.dump({"pca": resultado["pca"], "meta": resultado["meta"],
                   "referencias": resultado["referencias_usadas"]},
                  f, ensure_ascii=False, indent=2, default=str)
    return gravados


def atualizar_resumo(linhas, pasta_drift=None):
    """Acrescenta/atualiza linhas (edicao, referencia) em resumo_temporal.csv."""
    caminho = _pasta_global(pasta_drift) / "resumo_temporal.csv"
    registro = pd.DataFrame(linhas)
    if caminho.exists():
        atual = pd.read_csv(caminho, encoding="utf-8")
        chave = set(zip(registro["edicao"], registro["referencia"]))
        atual = atual[~atual.apply(lambda r: (r["edicao"], r["referencia"]) in chave, axis=1)]
        registro = pd.concat([atual, registro], ignore_index=True)
    registro = registro.sort_values(["edicao", "referencia"]).reset_index(drop=True)
    registro.to_csv(caminho, index=False, encoding="utf-8")
    return caminho


def carregar_resumo(pasta_drift=None):
    caminho = _pasta_global(pasta_drift) / "resumo_temporal.csv"
    if not caminho.exists():
        return pd.DataFrame()
    return pd.read_csv(caminho, encoding="utf-8")


# ---------------------------------------------------------------------------
# Tendência (matriz OC x par de edições)
# ---------------------------------------------------------------------------
def montar_tendencia(modo=MODO_PADRAO, baseline=None, pasta_drift=None):
    """Monta as matrizes de tendência a partir dos CSVs já calculados.

    Varre modelos/drift/<edicao_prod>/drift_univariado_<ref>.csv (a referência
    depende do ciclo de cada curso), então cada 'Par' é '<prod> vs <ref>'."""
    global_pasta = _pasta_global(pasta_drift)
    registros = []
    for pasta_prod in sorted(global_pasta.iterdir()):
        if not pasta_prod.is_dir():
            continue
        prod = pasta_prod.name
        for arquivo in sorted(pasta_prod.glob("drift_univariado_*.csv")):
            ref = arquivo.stem.replace("drift_univariado_", "")
            if not ref:
                continue
            if arquivo.stat().st_size == 0:
                continue
            try:
                df = pd.read_csv(arquivo, encoding="utf-8")
            except pd.errors.EmptyDataError:
                continue
            if df.empty or "Variavel" not in df.columns:
                continue
            df = df.copy()
            df["Edicao"] = prod
            df["Referencia"] = ref
            df["Par"] = f"{prod} vs {ref}"
            df["Tipo_variavel"] = np.where(
                df["Variavel"].astype(str).str.startswith(NOTAS_COMPARADAS), "nota", "oc")
            registros.append(df)
    if not registros:
        return {}
    longo = pd.concat(registros, ignore_index=True)
    caminho_longo = global_pasta / "tendencia_long.csv"
    longo.to_csv(caminho_longo, index=False, encoding="utf-8")
    gravados = {"tendencia_long": caminho_longo}

    def _pivot(coluna_valor, mascara, nome):
        sub = longo[mascara]
        if sub.empty:
            return
        piv = sub.pivot_table(index=["Curso", "Variavel"], columns="Par",
                              values=coluna_valor, aggfunc="first")
        caminho = global_pasta / nome
        piv.reset_index().to_csv(caminho, index=False, encoding="utf-8")
        gravados[nome.rsplit(".", 1)[0]] = caminho

    mascara_oc = longo["Tipo_variavel"] == "oc"
    _pivot("Status", mascara_oc, "tendencia_status_oc.csv")
    _pivot("KS_p", mascara_oc, "tendencia_pvalor_oc.csv")
    _pivot("Status", ~mascara_oc, "tendencia_status_notas.csv")
    _pivot("KS_p", ~mascara_oc, "tendencia_pvalor_notas.csv")
    return gravados


def gerar_tendencia(modo=MODO_PADRAO, baseline=None, recarregar=False,
                    max_alunos=None, pasta_drift=None):
    """Calcula as edições ainda sem artefatos no modo e monta as matrizes."""
    edicoes = edicoes_enade()
    ano_base = int(baseline or os.environ.get("PRISM_DRIFT_BASELINE", "2019") or 2019)
    if modo == "baseline":
        alvos = [e for e in edicoes if e != f"enade_{ano_base}"]
    else:
        primeira = min(edicoes, key=lambda e: ano_de_edicao(e) or 0)
        alvos = [e for e in edicoes if e != primeira]
    calculados = []
    for ed in alvos:
        pasta = _pasta_par(ed, pasta_drift)
        tem_csv = any(p.stat().st_size > 0 for p in pasta.glob("drift_univariado_*.csv"))
        if tem_csv and not recarregar:
            continue
        resultado = comparar_edicao_prod(ed, modo=modo, baseline=baseline, max_alunos=max_alunos)
        gravados = salvar_por_referencia(ed, resultado, pasta_drift)
        _registrar_resumo(ed, modo, resultado, gravados, pasta_drift)
        calculados.append(ed)
    gravados = montar_tendencia(modo, baseline, pasta_drift)
    return {"edicoes_calculadas": calculados, "arquivos": gravados}


def _registrar_resumo(edicao, modo, resultado, gravados, pasta_drift=None):
    meta = resultado["meta"]
    univariado = resultado["univariado"]
    linhas = []
    if univariado.empty:
        linhas.append({
            "edicao": edicao, "referencia": "", "modo": modo,
            "status": meta.get("erro") or "sem_curso_comum",
            "n_alunos_ref": meta["n_alunos_ref"], "n_alunos_prod": meta["n_alunos_prod"],
            "n_cursos_comuns": 0, "n_oc_comuns": 0, "n_comparacoes": 0, "n_drift": 0,
            "pca_status": "", "pca_ratio": np.nan, "tempo_s": meta.get("tempo_s", 0.0),
        })
    else:
        for ref, grupo in univariado.groupby("Referencia"):
            pca_status, pca_ratio = "", np.nan
            for pca in resultado["pca"].values():
                if pca.get("referencia") == ref:
                    pca_status = pca.get("status", "")
                    pca_ratio = pca.get("ratio") if pca.get("ratio") is not None else np.nan
                    break
            linhas.append({
                "edicao": edicao, "referencia": ref, "modo": modo, "status": "ok",
                "n_alunos_ref": resultado["referencias_usadas"].get(ref, {}).get("n_alunos", 0),
                "n_alunos_prod": meta["n_alunos_prod"],
                "n_cursos_comuns": int(grupo["Curso"].nunique()),
                "n_oc_comuns": int(grupo[~grupo["Variavel"].astype(str).str.startswith(NOTAS_COMPARADAS)].shape[0]),
                "n_comparacoes": int(len(grupo)),
                "n_drift": int(grupo["Status"].astype(str).str.startswith("Drift").sum()),
                "pca_status": pca_status, "pca_ratio": pca_ratio,
                "tempo_s": meta.get("tempo_s", 0.0),
            })
    atualizar_resumo(linhas, pasta_drift=pasta_drift)


# ---------------------------------------------------------------------------
# Motor registrado em executar_por_edicao.py (assinatura padrão dos motores)
# ---------------------------------------------------------------------------
def executar_drift_edicao(caminho_csv=None, df=None):
    """Motor de drift temporal por edição (MOTORES de executar_por_edicao.py).

    Compara cada curso da edição corrente (PRISM_EDICAO) com a edição anterior
    em que o MESMO curso foi avaliado (ou com a baseline, no modo baseline) e,
    nos modos de tendência, atualiza as matrizes em modelos/drift/.
    """
    edicao = (os.environ.get("PRISM_EDICAO", "") or "").strip()
    modo = (os.environ.get("PRISM_DRIFT_MODO", "") or MODO_PADRAO).strip()
    if modo not in MODOS:
        print(f"  [drift] Modo desconhecido '{modo}', usando '{MODO_PADRAO}'.")
        modo = MODO_PADRAO
    baseline = os.environ.get("PRISM_DRIFT_BASELINE", "").strip() or None
    max_alunos = int(os.environ.get("PRISM_DRIFT_MAX_ALUNOS", str(MAX_ALUNOS_PADRAO)) or MAX_ALUNOS_PADRAO)
    pasta_global = caminho_saida_algoritmo("drift", "resumo_temporal.csv").parent

    if not edicao:
        print("  [drift] PRISM_EDICAO não definida; gerando apenas a tendência (se houver pares).")
        if modo in ("consecutivas_tendencia", "baseline"):
            gerar_tendencia(modo=modo, baseline=baseline, max_alunos=max_alunos, pasta_drift=pasta_global)
        return pasta_global / "resumo_temporal.csv"

    print(f"\n  === DRIFT TEMPORAL ({modo}) — {edicao} ===")
    resultado = comparar_edicao_prod(edicao, modo=modo, baseline=baseline,
                                     max_alunos=max_alunos, df_prod=df)
    gravados = salvar_por_referencia(edicao, resultado, pasta_drift=pasta_global)
    _registrar_resumo(edicao, modo, resultado, gravados, pasta_drift=pasta_global)
    meta = resultado["meta"]
    if meta.get("erro"):
        print(f"  [drift] Atenção: {meta['erro']}")
    print(f"  [drift] {meta['n_comparacoes']} variáveis em {meta['n_cursos_comuns']} cursos; "
          f"{meta['n_drift']} com drift; referências: {meta.get('referencias') or '—'}")
    for ref, caminho in gravados:
        print(f"          {caminho.name} (ref {ref})")

    if modo in ("consecutivas_tendencia", "baseline"):
        montar_tendencia(modo=modo, baseline=baseline, pasta_drift=pasta_global)
    return gravados[0][1] if gravados else pasta_global / "resumo_temporal.csv"


if __name__ == "__main__":
    if not os.environ.get("PRISM_EDICAO"):
        os.environ["PRISM_EDICAO"] = "enade_2019"
    executar_drift_edicao()
