"""
Ponte LCA -> CDM restrito (DINA) - PRISM-EDU
============================================

Porta, de forma reproduzivel e honesta, o pipeline que liga a Analise de
Classes Latentes (LCA) exploratoria ao Modelo de Diagnostico Cognitivo (DINA)
restrito, para os cursos avaliados no ENADE 2023.

Fonte da matriz item-OC (matriz-Q):
    dados/mestre_questao_oc.csv  (matriz item x OC do INEP / Anexo IX, ja
    consolidada). O DINA NAO usa matriz-Q aleatoria: sem ela o pipeline falha
    explicitamente a inventar um mapeamento item-competencia.

Artefatos gerados por curso (em modelos/cdm/<edicao>/):
    - dina_estimativas_<curso>.csv      (guess g, slip s, P(domina), status)
    - dina_perfis_alunos_<curso>.csv    (perfil latente alpha por aluno)
    - matriz_q_<curso>.csv              (item x OC binaria)
    - dicionario_ocs_<curso>.csv        (rotulo, OC, n_itens, prevalencia)
    - validador_matriz_q_<curso>.xlsx   (workbook de validacao especialista)

Artefatos consolidados (mesma pasta):
    - 00_resumo_geral.csv
    - comparacao_lca_vs_dina.csv
    - concordancia_lca_dina.csv

Integridade:
    - O target externo (nota) NAO entra na estimacao do DINA. NT_DIS_CE aparece
      apenas como coluna descritiva nos perfis de aluno.
    - Nenhum aluno e removido arbitrariamente.
"""
import unicodedata
import re
import os
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config import SEPARADOR, ENCODING, CURSOS_MAP, pasta_saida_edicao
from algoritmos.cdm.dina_em import DINA_EM, localizar_mestre_oc

try:
    from scipy.stats import pearsonr, spearmanr
except ImportError:  # pragma: no cover
    pearsonr = spearmanr = None

warnings.filterwarnings("ignore")

COLUNAS_Q = [f"Q{i}" for i in range(1, 39)]
MAX_ATRIBUTOS_DINA = 12
ROTULO_OC = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def normalizar(texto):
    """Remove acentos e nao-alfanumericos (para casar nomes de arquivo)."""
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\W", "", t).lower()


def rotulo_oc(indice):
    return f"OC_{ROTULO_OC[indice]}"


def localizar_microdados_edicao(edicao):
    """Localiza o CSV de microdados de uma edicao (ex.: 'enade_2023')."""
    from config import PASTA_DADOS_PROCESSADOS, caminho_arquivo_edicao
    ano = str(edicao).split("_")[-1]
    local = PASTA_DADOS_PROCESSADOS / "por_ano" / f"relatorio_final_enade_{ano}.csv"
    if edicao.startswith("enade_") and local.exists():
        return local
    try:
        caminho = caminho_arquivo_edicao(edicao)
        if caminho and Path(caminho).exists():
            return Path(caminho)
    except Exception:
        pass
    ano = str(edicao).split("_")[-1]
    candidatos = [
        PASTA_DADOS_PROCESSADOS / "por_ano" / f"relatorio_final_enade_{ano}.csv",
        Path(__file__).resolve().parent.parent.parent / "dados" / "processados"
        / "por_ano" / f"relatorio_final_enade_{ano}.csv",
    ]
    for c in candidatos:
        if c.exists():
            return c
    raise FileNotFoundError(f"Microdados de {edicao} nao encontrados. Tentou: {candidatos}")


def construir_q_matrix_curso(sub_mestre):
    """Monta a matriz-Q (J itens x K atributos) a partir das OCs principais."""
    df = sub_mestre.sort_values("posicao").reset_index(drop=True)
    freq = df["oc_principal"].value_counts()
    if len(freq) > MAX_ATRIBUTOS_DINA:
        ocs = freq.index[: MAX_ATRIBUTOS_DINA - 1].tolist() + ["OUTRAS_COMPETENCIAS"]
    else:
        ocs = freq.index.tolist()
    K = len(ocs)

    def atributo(oc):
        return oc if oc in ocs else "OUTRAS_COMPETENCIAS"

    df = df.copy()
    df["atributo_dina"] = df["oc_principal"].map(atributo)
    Q = np.zeros((len(df), K), dtype=int)
    for i, attr in enumerate(df["atributo_dina"]):
        Q[i, ocs.index(attr)] = 1
    return Q, ocs, df


def _carregar_lca(edicao):
    """Carrega os artefatos LCA (03_criterios, 02_classes, 01_geral) da edicao."""
    pasta_lca = pasta_saida_edicao("lca", edicao)
    arqs = {}
    for nome, chave in [
        ("01_relatorio_geral_por_ies.csv", "geral"),
        ("02_caracterizacao_das_classes.csv", "classes"),
        ("03_criterios_de_selecao_k.csv", "criterios"),
    ]:
        p = pasta_lca / nome
        arqs[chave] = pd.read_csv(p, sep=SEPARADOR, encoding=ENCODING, low_memory=False) if p.exists() else None
    return arqs


def _microdados_curso(df, cod):
    if "CO_GRUPO" in df.columns:
        sub = df[df["CO_GRUPO"] == cod]
    elif "CO_CURSO" in df.columns:
        sub = df[df["CO_CURSO"] == cod]
    else:
        sub = pd.DataFrame()
    return sub


def _questao_do_item(item):
    """Coluna Q* de um item da matriz-Q (prefere 'questao' a 'posicao')."""
    q = str(item.get("questao", "")).strip()
    if re.fullmatch(r"Q\d+", q):
        return q
    try:
        return f"Q{int(item['posicao'])}"
    except (TypeError, ValueError):
        return ""


def _alinhar_itens(df_curso, df_itens, Q):
    """Alinha Q, df_itens e as colunas Q* pelos rotulos reais dos itens.

    O mestre do INEP nao garante que os itens sejam exatamente as J primeiras
    colunas Q do microdado. Aqui a correspondencia e feita por 'questao'
    (fallback: 'posicao'), descartando itens sem coluna no microdado e
    mantendo Q e df_itens na mesma ordem. Retorna (df_itens, Q, colunas).
    """
    df_itens = df_itens.reset_index(drop=True)
    linhas, colunas = [], []
    for i, item in df_itens.iterrows():
        q = _questao_do_item(item)
        if q and q in df_curso.columns:
            linhas.append(i)
            colunas.append(q)
    if not linhas:
        return df_itens.iloc[0:0].reset_index(drop=True), Q[0:0, :], []
    return (df_itens.iloc[linhas].reset_index(drop=True),
            Q[linhas, :], colunas)


def _preparar_microdados(df_micro):
    """Normaliza (binariza questões, trata nota discursiva) o micro DINA."""
    df_micro = df_micro.copy()
    if "TP_PR_GER" in df_micro.columns:
        df_micro = df_micro[df_micro["TP_PR_GER"] > 0].copy()
    for col in COLUNAS_Q:
        if col in df_micro.columns:
            df_micro[col] = pd.to_numeric(df_micro[col], errors="coerce").apply(
                lambda x: 1 if x == 1 else 0)
    if "NT_DIS_CE" in df_micro.columns:
        df_micro["NT_DIS_CE"] = pd.to_numeric(
            df_micro["NT_DIS_CE"].astype(str).str.replace(",", "."), errors="coerce")
    return df_micro


def _mapa_nomes_curso(df_micro):
    """Compatibilidade com artefatos LCA LEGADOS (gerados antes da correcao).

    Versoes antigas do ``pipeline_lca.py`` agrupavam por ``CO_CURSO`` e rotulavam
    via ``CURSOS_MAP`` (indexado por ``CO_GRUPO``), produzindo ``Curso_<codigo>``.
    A LCA atual ja agrupa por ``CO_GRUPO`` e grava o nome correto; este mapa
    existe apenas para ler resultados antigos sem re-executar. Reconstroi
    ``CO_CURSO -> CO_GRUPO -> nome`` a partir dos proprios microdados.
    """
    mapa = {}
    if not {"CO_CURSO", "CO_GRUPO"}.issubset(df_micro.columns):
        return mapa
    pares = df_micro[["CO_CURSO", "CO_GRUPO"]].dropna().drop_duplicates()
    for cod_curso, grupo in pares.itertuples(index=False):
        try:
            cod_curso = int(float(cod_curso))
            grupo = int(float(grupo))
        except (TypeError, ValueError):
            continue
        nome = CURSOS_MAP.get(grupo)
        if nome:
            mapa[f"Curso_{cod_curso}"] = nome
            mapa[str(cod_curso)] = nome
    return mapa


def _relabel_lca(lca, mapa):
    """Reaplica nomes de curso nas colunas 'curso' dos artefatos LCA legados.

    No-op para artefatos gerados pela versao corrigida do pipeline (nomes ja
    corretos); util apenas para leitura de saidas antigas.
    """
    if not mapa:
        return lca
    for chave in ("geral", "classes", "criterios"):
        df = lca.get(chave)
        if df is not None and "curso" in df.columns:
            lca[chave] = df.assign(curso=df["curso"].map(lambda c: mapa.get(str(c), c)))
    return lca


def processar_edicao(edicao="enade_2023", limite_cursos=None, df=None,
                     mestre=None, pasta_saida=None):
    """Executa a ponte LCA->CDM para todos os cursos da edicao.

    Se ``df`` for fornecido (motores por edicao), ele e usado em vez de reler
    o CSV de microdados. ``mestre`` e ``pasta_saida`` permitem injetar a
    matriz-Q e o destino em testes de regressao.
    """
    print("=" * 72)
    print(f"  PRISM-EDU: Ponte LCA -> CDM restrito (DINA) - {edicao}")
    print("=" * 72)

    if mestre is None:
        mestre = pd.read_csv(localizar_mestre_oc(), sep=SEPARADOR, encoding="utf-8-sig")
    else:
        mestre = mestre.copy()
    for col in ["oc_principal", "oc_secundario", "area_prova", "perfil_egresso", "competencia"]:
        if col in mestre.columns:
            mestre[col] = mestre[col].fillna("").astype(str).str.strip()
    mestre["_curso_norm"] = mestre["curso"].map(normalizar)
    print(f"  Matriz item-OC (Anexo IX): {len(mestre)} linhas, {mestre['curso'].nunique()} cursos")

    lca = _carregar_lca(edicao)
    probs_cols = [f"PROB_{q}" for q in COLUNAS_Q]
    gaps_cols = [f"GAP_{q}" for q in COLUNAS_Q]

    if df is not None:
        df_micro = _preparar_microdados(df)
        print(f"  Microdados: DataFrame em memoria ({len(df_micro)} linhas)")
    else:
        caminho_micro = localizar_microdados_edicao(edicao)
        print(f"  Microdados: {caminho_micro.name}")
        usecols = ["ALUNO", "CO_GRUPO", "CO_CURSO", "CO_IES", "TP_PR_GER", "NT_DIS_CE"] + COLUNAS_Q
        cabecalho = pd.read_csv(caminho_micro, sep=SEPARADOR, encoding=ENCODING, nrows=0).columns
        usecols = [c for c in usecols if c in cabecalho]
        df_micro = _preparar_microdados(
            pd.read_csv(caminho_micro, sep=SEPARADOR, encoding=ENCODING,
                        usecols=usecols, low_memory=False))

    lca = _relabel_lca(lca, _mapa_nomes_curso(df_micro))

    pasta = Path(pasta_saida) if pasta_saida is not None \
        else pasta_saida_edicao("cdm", edicao)
    pasta.mkdir(parents=True, exist_ok=True)

    resumo_geral, comparacao, concordancia_itens = [], [], []
    cursos = list(CURSOS_MAP.items())
    if limite_cursos:
        cursos = cursos[:limite_cursos]

    for cod, nome in cursos:
        nome_norm = normalizar(nome)
        sub_mestre = mestre[mestre["_curso_norm"] == nome_norm]
        if sub_mestre.empty:
            continue
        df_curso = _microdados_curso(df_micro, cod)
        if len(df_curso) < 50:
            continue

        Q, ocs, df_itens = construir_q_matrix_curso(sub_mestre)
        J = Q.shape[0]
        df_itens, Q, cols_curso = _alinhar_itens(df_curso, df_itens, Q)
        J = len(cols_curso)
        if J == 0:
            continue
        X = df_curso[cols_curso].to_numpy(dtype=int)

        modelo = DINA_EM().ajustar(X, Q)
        taxa_acerto = X.mean(axis=0)
        p_item = (1 - modelo.s) * modelo.p_eta1 + modelo.g * (1 - modelo.p_eta1)
        pi = modelo.pi

        base = normalizar(nome)

        # ---- Perfis de dominio por aluno ----
        cols_perfil = [c for c in ["ALUNO", "CO_IES", "NT_DIS_CE"] if c in df_curso.columns]
        df_perfis = df_curso[cols_perfil].copy().reset_index(drop=True)
        for k in range(Q.shape[1]):
            df_perfis[f"mastery_{rotulo_oc(k)}"] = modelo.perfis_mastery[:, k]
            df_perfis[f"alpha_{rotulo_oc(k)}"] = (modelo.perfis_mastery[:, k] >= 0.5).astype(int)
        df_perfis["n_ocs_dominadas"] = df_perfis[
            [f"alpha_{rotulo_oc(k)}" for k in range(Q.shape[1])]].sum(axis=1)
        df_perfis.to_csv(pasta / f"dina_perfis_alunos_{base}.csv",
                         index=False, sep=SEPARADOR, decimal=",", encoding="utf-8-sig")

        # ---- Estimativas por item ----
        status_item = []
        for j in range(J):
            if modelo.s[j] + modelo.g[j] >= 0.999 - 1e-6:
                status_item.append("POUCO_DISCRIMINATIVO_LIMITE")
            elif (1 - modelo.s[j]) - modelo.g[j] < 0.1:
                status_item.append("POUCO_DISCRIMINATIVO")
            else:
                status_item.append("OK")
        pd.DataFrame({
            "Questao": cols_curso,
            "area_prova": df_itens["area_prova"].values[:J] if "area_prova" in df_itens.columns else "",
            "atributos_requeridos": df_itens["oc_principal"].values[:J],
            "taxa_acerto_real": taxa_acerto,
            "guess_g": modelo.g,
            "slip_s": modelo.s,
            "p_domina_atributos": modelo.p_eta1,
            "p_acerto_dina": p_item,
            "status": status_item,
        }).to_csv(pasta / f"dina_estimativas_{base}.csv",
                  index=False, sep=SEPARADOR, decimal=",", encoding="utf-8-sig")

        # ---- Matriz-Q ----
        df_mq = df_itens[["questao", "posicao", "area_prova", "oc_principal"]].copy() \
            if "area_prova" in df_itens.columns else df_itens[["questao", "posicao", "oc_principal"]].copy()
        df_mq = df_mq.rename(columns={"questao": "Questao"})
        for k in range(Q.shape[1]):
            df_mq[rotulo_oc(k)] = Q[:, k]
        df_mq.to_csv(pasta / f"matriz_q_{base}.csv",
                     index=False, sep=SEPARADOR, encoding="utf-8-sig")

        # ---- Dicionario de OCs ----
        df_dict = pd.DataFrame({
            "rotulo": [rotulo_oc(k) for k in range(len(ocs))],
            "oc_principal": ocs,
            "n_itens_medidos": [int((df_itens["atributo_dina"] == oc).sum()) for oc in ocs],
            "prevalencia_dominio_dina": pi,
        })
        df_dict.to_csv(pasta / f"dicionario_ocs_{base}.csv",
                       index=False, sep=SEPARADOR, decimal=",", encoding="utf-8-sig")

        # ---- Comparacao com a LCA exploratoria ----
        p_lca = np.full(J, np.nan)
        gap_lca = np.full(J, np.nan)
        gap_lca_max = np.full(J, np.nan)
        corr_classes = []
        if lca["classes"] is not None and "curso" in lca["classes"].columns:
            sub_cls = lca["classes"][lca["classes"]["curso"] == nome]
            if not sub_cls.empty:
                pesos = sub_cls["n_alunos"].to_numpy(dtype=float) \
                    if "n_alunos" in sub_cls.columns else np.ones(len(sub_cls))
                for j, col in enumerate(probs_cols):
                    if col in sub_cls.columns and j < J:
                        p_lca[j] = np.average(sub_cls[col].to_numpy(dtype=float), weights=pesos)
                for j, col in enumerate(gaps_cols):
                    if col in sub_cls.columns and j < J:
                        vals = sub_cls[col].to_numpy(dtype=float)
                        gap_lca[j] = np.average(vals, weights=pesos)
                        gap_lca_max[j] = np.abs(vals).max()
                if pearsonr is not None:
                    for _, row in sub_cls.iterrows():
                        perfil = row[[c for c in probs_cols if c in sub_cls.columns]].to_numpy(dtype=float)
                        if not np.all(np.isnan(perfil)):
                            try:
                                corr_classes.append(pearsonr(perfil, p_item)[0])
                            except Exception:
                                pass

        r_pearson = r_spearman = r2_item = np.nan
        mask = ~np.isnan(p_lca)
        if pearsonr is not None and mask.sum() > 1:
            r_pearson = pearsonr(p_lca[mask], p_item[mask])[0]
            r_spearman = spearmanr(p_lca[mask], p_item[mask])[0]
            r2_item = r_pearson ** 2

        bic_dina = modelo.bic(len(df_curso))
        aic_dina = modelo.aic()
        sub_crit = None
        if lca["criterios"] is not None and "curso" in lca["criterios"].columns:
            sub_crit = lca["criterios"][lca["criterios"]["curso"] == nome]
        bic_lca = aic_lca = ll_lca = ent = np.nan
        n_ies = 0
        if sub_crit is not None and not sub_crit.empty:
            bic_lca = float(sub_crit["bic"].median()) if "bic" in sub_crit.columns else np.nan
            aic_lca = float(sub_crit["aic"].median()) if "aic" in sub_crit.columns else np.nan
            ent = float(sub_crit["entropia"].mean()) if "entropia" in sub_crit.columns else np.nan
            n_ies = int(sub_crit["ies"].nunique()) if "ies" in sub_crit.columns else 0
            if lca["geral"] is not None and "log_lik" in lca["geral"].columns:
                sub_ger = lca["geral"][lca["geral"]["curso"] == nome]
                if not sub_ger.empty:
                    ll_lca = float(sub_ger["log_lik"].median())

        comparacao.append({
            "curso": nome, "n_alunos": len(df_curso), "n_ies_lca": n_ies,
            "n_atributos_dina": Q.shape[1], "n_param_dina": modelo.n_params,
            "ll_dina": round(float(modelo.log_likelihood), 2),
            "bic_dina": round(float(bic_dina), 2), "aic_dina": round(float(aic_dina), 2),
            "ll_lca_mediana_ies": round(ll_lca, 2) if not np.isnan(ll_lca) else np.nan,
            "bic_lca_mediana_ies": round(bic_lca, 2) if not np.isnan(bic_lca) else np.nan,
            "aic_lca_mediana_ies": round(aic_lca, 2) if not np.isnan(aic_lca) else np.nan,
            "entropia_lca_media": round(ent, 4) if not np.isnan(ent) else np.nan,
            "corr_pearson_item_lca_dina": round(r_pearson, 4) if not np.isnan(r_pearson) else np.nan,
            "corr_spearman_item_lca_dina": round(r_spearman, 4) if not np.isnan(r_spearman) else np.nan,
            "r2_item_lca_dina": round(r2_item, 4) if not np.isnan(r2_item) else np.nan,
            "corr_classe_lca_media": round(float(np.mean(corr_classes)), 4) if corr_classes else np.nan,
            "delta_bic_dina_menos_lca": round(float(bic_dina - bic_lca), 2) if not np.isnan(bic_lca) else np.nan,
            "nota_bic": ("DINA estimado a nivel NACIONAL do curso; LCA ajustada POR IES "
                         "(mediana). BIC/AIC nao compartilham escala: interpretar apenas a "
                         "concordancia item a item e as correlacoes classe-LCA x DINA."),
        })

        for j in range(J):
            concordancia_itens.append({
                "curso": nome, "Questao": cols_curso[j],
                "area_prova": df_itens["area_prova"].values[j] if "area_prova" in df_itens.columns else "",
                "oc_principal": df_itens["oc_principal"].values[j],
                "taxa_acerto_real": round(float(taxa_acerto[j]), 4),
                "p_item_lca": round(float(p_lca[j]), 4) if not np.isnan(p_lca[j]) else np.nan,
                "p_item_dina": round(float(p_item[j]), 4),
                "diff_p_lca_dina": round(float(p_lca[j] - p_item[j]), 4) if not np.isnan(p_lca[j]) else np.nan,
                "gap_lca_medio": round(float(gap_lca[j]), 4) if not np.isnan(gap_lca[j]) else np.nan,
                "gap_lca_max_abs": round(float(gap_lca_max[j]), 4) if not np.isnan(gap_lca_max[j]) else np.nan,
                "status_validacao": "PENDENTE_VALIDACAO",
            })

        # ---- Workbook de validacao especialista ----
        _gravar_validador(pasta / f"validador_matriz_q_{base}.xlsx",
                          df_itens, cols_curso, ocs, df_dict, Q,
                          taxa_acerto, p_item, p_lca, gap_lca, gap_lca_max, status_item)

        resumo_geral.append({
            "curso": nome, "n_alunos": len(df_curso), "n_ocs_dina": Q.shape[1],
            "guess_medio": round(float(modelo.g.mean()), 4),
            "slip_medio": round(float(modelo.s.mean()), 4),
            "taxa_acerto_media": round(float(taxa_acerto.mean()), 4),
            "corr_item_lca_dina": round(r_pearson, 4) if not np.isnan(r_pearson) else np.nan,
            "status_validacao": "PENDENTE_VALIDACAO",
        })
        print(f"  {nome}: {J} itens x {Q.shape[1]} OCs | g={modelo.g.mean():.3f} "
              f"s={modelo.s.mean():.3f} | r(LCA,DINA)={r_pearson:.3f}")

    if resumo_geral:
        pd.DataFrame(resumo_geral).to_csv(pasta / "00_resumo_geral.csv",
                                          index=False, sep=SEPARADOR, decimal=",", encoding="utf-8-sig")
        pd.DataFrame(comparacao).to_csv(pasta / "comparacao_lca_vs_dina.csv",
                                        index=False, sep=SEPARADOR, decimal=",", encoding="utf-8-sig")
        pd.DataFrame(concordancia_itens).to_csv(pasta / "concordancia_lca_dina.csv",
                                                index=False, sep=SEPARADOR, decimal=",", encoding="utf-8-sig")
        print(f"\n  Ponte LCA->CDM concluida para {len(resumo_geral)} cursos. Saida: {pasta}")
    else:
        print("  Nenhum curso processado (sem matriz-Q, LCA ou alunos suficientes).")
    return pd.DataFrame(resumo_geral)


def _gravar_validador(destino, df_itens, cols_curso, ocs, df_dict, Q,
                      taxa_acerto, p_item, p_lca, gap_lca, gap_lca_max, status_item):
    """Escreve o workbook de validacao especialista (3 abas)."""
    J = len(cols_curso)
    linhas = df_itens.sort_values("posicao").reset_index(drop=True)
    cols_base = [c for c in ["questao", "posicao", "area_prova", "perfil_egresso",
                             "competencia", "oc_principal", "oc_secundario"] if c in linhas.columns]
    planilha = linhas[cols_base].copy().rename(columns={"questao": "Questao"})
    for k, oc in enumerate(ocs):
        planilha[rotulo_oc(k)] = (linhas["atributo_dina"] == oc).astype(int)
    planilha["STATUS"] = "PENDENTE_VALIDACAO"
    planilha["OBSERVACOES"] = ""

    cobertura = df_dict.rename(columns={"oc_principal": "OC", "n_itens_medidos": "n_itens"}).copy()
    cobertura["itens"] = [", ".join(linhas.loc[linhas["atributo_dina"] == oc, "questao"])
                          for oc in ocs]
    cobertura["status"] = np.where(cobertura["n_itens"] < 2, "REVISAR_POUCOS_ITENS", "OK_COBERTURA")

    conc = pd.DataFrame({
        "Questao": cols_curso,
        "area_prova": linhas["area_prova"].values[:J] if "area_prova" in linhas.columns else "",
        "oc_principal": linhas["oc_principal"].values[:J],
        "taxa_acerto_real": taxa_acerto,
        "p_item_lca": p_lca,
        "p_item_dina": p_item,
        "gap_lca_medio": gap_lca,
        "gap_lca_max_abs": gap_lca_max,
        "status_dina": status_item,
        "sugestao": ["REVISAR: gap LCA alto e OC mapeada"
                     if (not np.isnan(gap_lca_max[j]) and gap_lca_max[j] > 0.35)
                     else "OK: sem sinal forte de divergencia" for j in range(J)],
    })

    with pd.ExcelWriter(destino, engine="openpyxl") as writer:
        planilha.to_excel(writer, sheet_name="Matriz_Q_Item_x_OC", index=False)
        cobertura.to_excel(writer, sheet_name="Resumo_Cobertura", index=False)
        conc.to_excel(writer, sheet_name="Concordancia_Empirica_LCA", index=False)


def gerar_mestre_template():
    """Documenta de onde vem o mestre_questao_oc.csv (matriz item-OC do INEP)."""
    return localizar_mestre_oc()


def executar_ponte_edicao(caminho_csv=None, df=None):
    """Motor por edicao (interface executar_por_edicao): ponte LCA -> CDM/DINA."""
    edicao = os.environ.get("PRISM_EDICAO", "")
    if not edicao:
        edicao = "enade_2023"
    return processar_edicao(edicao=edicao, df=df)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Ponte LCA -> CDM restrito (DINA)")
    ap.add_argument("--edicao", default="enade_2023")
    ap.add_argument("--limite-cursos", type=int, default=None)
    args = ap.parse_args()
    processar_edicao(edicao=args.edicao, limite_cursos=args.limite_cursos)
