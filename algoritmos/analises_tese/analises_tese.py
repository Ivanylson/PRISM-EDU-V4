"""
E1-E9: analises de mestrado/doutorado sobre os microdados reais do ENADE.

Todas ancoradas em colunas reais do relatorio_final_enade_<ano>.csv:
  equidade    (E1) - gap de proficiencia por regiao/UF/categoria administrativa/sexo
  valor_agregado (E2) - proficiencia vs. controle socioeconomico (QE_I*/renda)
  invariancia (E3) - estabilidade da estrutura fatorial (correlacao de cargas) entre edicoes
  trienal     (E4) - tendencia por curso comparando edicao anterior em que foi avaliado
  formacao    (E5) - proficiencia x tempo/ano de curso e modalidade (licenciatura vs bacharelado)
  eficiencia  (E6) - fronteira DEA simples (IEs eficientes = proficiencia por custo-proxy)
  cluster_ies (E7) - perfis de IEs por KMeans sobre indicadores agregados
  distal      (E8) - associacao proficiencia x desfechos distais (residencia/trabalho, via QE)
  sensibilidade (E9) - robustez dos rankings a peso amostral e limiar de excelencia

Regra PRISM-EDU: dado ausente -> "insuficiente", nunca inventar.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

RAIZ = Path(__file__).resolve().parent.parent.parent
PASTA_MICRO = RAIZ.parent / "seriesTemporais_microdados" / "resultados" / "enade"

# Colunas de desfecho/nota externa (nunca usar Q* como alvo => evitar circularidade)
NOTA_EXTERNA = ["NT_DIS_CE", "NT_CE_D1", "NT_GER"]

CONTROLES_SOCIO = ["QE_I01", "QE_I02", "QE_I03"]  # escolaridade/renda/bolsa (questionario)
CONTROLES_DEMOG = ["NU_IDADE", "TP_SEXO"]


def _codificar_controles(d, colunas):
    """Codifica controles mistos (categoricos A-E e numericos) para regressao."""
    partes = []
    for c in colunas:
        if c not in d.columns:
            continue
        if c == "TP_SEXO":
            partes.append(d[c].map({"M": 0, "F": 1}).astype(float).rename("_sexo"))
        elif pd.api.types.is_numeric_dtype(d[c]):
            partes.append(pd.to_numeric(d[c], errors="coerce").rename(f"_{c}"))
        else:
            cod = d[c].astype(str).str.strip().str.upper()
            mapa = {k: i for i, k in enumerate(sorted(cod.unique()))}
            partes.append(cod.map(mapa).astype(float).rename(f"_{c}"))
    return pd.concat(partes, axis=1)


def edicoes_disponiveis():
    if not PASTA_MICRO.exists():
        return []
    return sorted(int(p.stem.split("_")[-1]) for p in PASTA_MICRO.glob("relatorio_final_enade_*.csv"))


def carregar(ano, colunas=None, max_linhas=200000):
    arq = PASTA_MICRO / f"relatorio_final_enade_{ano}.csv"
    if not arq.exists():
        raise FileNotFoundError(f"Microdados ENADE {ano} nao encontrados: {arq}")
    return pd.read_csv(arq, sep=";", encoding="utf-8-sig", low_memory=False,
                       nrows=max_linhas, usecols=colunas)


def _nota_externa(df):
    for col in NOTA_EXTERNA:
        if col in df.columns:
            return pd.to_numeric(df[col], errors="coerce"), col
    return None, None


def _insuficiente(analise, motivo):
    return {"analise": analise, "status": "insuficiente", "motivo": motivo}


# ------------------------------------------------------------------ E1
def equidade(df, ano=None):
    """Gap de proficiencia por regiao, categoria administrativa e sexo."""
    nota, col = _nota_externa(df)
    if nota is None:
        return _insuficiente("E1_equidade", "sem coluna de nota externa")
    d = df.copy()
    d["_nota"] = nota
    d = d.dropna(subset=["_nota"])
    if d.empty:
        return _insuficiente("E1_equidade", "nota externa vazia")

    def _gap(grupo):
        g = d.groupby(grupo)["_nota"].agg(["mean", "count"]).reset_index()
        g = g[g["count"] >= 30]
        if g.empty:
            return {}
        g = g.sort_values("mean", ascending=False)
        return {"maior": g.iloc[0].to_dict(), "menor": g.iloc[-1].to_dict(),
                "gap": float(g.iloc[0]["mean"] - g.iloc[-1]["mean"]),
                "tabela": g.to_dict("records")}

    saida = {"analise": "E1_equidade", "status": "ok", "ano": ano, "coluna_nota": col,
             "n": int(len(d))}
    for rotulo, grupo in (("regiao", "CO_REGIAO_CURSO"), ("categoria", "CO_CATEGAD"),
                          ("sexo", "TP_SEXO"), ("modalidade", "CO_MODALIDADE")):
        if grupo in d.columns:
            saida[rotulo] = _gap(grupo)
    return saida


# ------------------------------------------------------------------ E2
def valor_agregado(df, ano=None):
    """Proficiencia esperada pelo perfil socioeconomico vs. observada (proxy IES)."""
    nota, col = _nota_externa(df)
    controles = [c for c in (CONTROLES_SOCIO + CONTROLES_DEMOG) if c in df.columns]
    if nota is None or not controles:
        return _insuficiente("E2_valor_agregado",
                             "faltam nota externa ou variaveis de controle socioeconomico")
    d = df.copy()
    d["_nota"] = nota
    Xc = _codificar_controles(d, controles)
    dados = pd.concat([d["_nota"].reset_index(drop=True), Xc.reset_index(drop=True)], axis=1)
    dados = dados.dropna()
    if len(dados) < 100:
        return _insuficiente("E2_valor_agregado", f"amostra pequena (n={len(dados)})")

    from sklearn.linear_model import LinearRegression
    X = dados[Xc.columns].values
    y = dados["_nota"].values
    modelo = LinearRegression().fit(X, y)
    d = d.loc[dados.index].copy()
    d["_esperado"] = modelo.predict(X)
    d["_residuo"] = d["_nota"] - d["_esperado"]

    por_ies = (d.groupby("CO_IES")["_residuo"].agg(["mean", "count"])
               .reset_index().rename(columns={"mean": "valor_agregado"}))
    por_ies = por_ies[por_ies["count"] >= 30].sort_values("valor_agregado", ascending=False)
    return {"analise": "E2_valor_agregado", "status": "ok", "ano": ano,
            "r2_controle": float(modelo.score(X, y)),
            "controles": controles,
            "top_ies": por_ies.head(10).to_dict("records"),
            "bottom_ies": por_ies.tail(10).to_dict("records"),
            "n_ies": int(len(por_ies)), "n": int(len(dados))}


# ------------------------------------------------------------------ E3
def invariancia(dfs_por_ano, colunas_q=None):
    """Estabilidade das cargas do 1o componente (proxy de estrutura) entre edicoes."""
    anos = sorted(dfs_por_ano.keys())
    if len(anos) < 2:
        return _insuficiente("E3_invariancia", "menos de 2 edicoes")
    from sklearn.decomposition import PCA
    cargas = {}
    for ano in anos:
        df = dfs_por_ano[ano]
        q = colunas_q or [c for c in df.columns if str(c).startswith("Q")]
        q = [c for c in q if c in df.columns]
        if len(q) < 5:
            continue
        X = df[q].apply(pd.to_numeric, errors="coerce").dropna()
        if len(X) < 50:
            continue
        pca = PCA(n_components=1).fit(X.values)
        cargas[ano] = pd.Series(pca.components_[0], index=q)
    if len(cargas) < 2:
        return _insuficiente("E3_invariancia", "edicoes com questoes insuficientes")
    comparacoes = {}
    anos_validos = sorted(cargas.keys())
    for a, b in zip(anos_validos, anos_validos[1:]):
        comuns = cargas[a].index.intersection(cargas[b].index)
        if len(comuns) >= 5:
            r = float(np.corrcoef(cargas[a][comuns], cargas[b][comuns])[0, 1])
            comparacoes[f"{a}x{b}"] = {"r_cargas": r, "n_questoes_comuns": int(len(comuns))}
    if not comparacoes:
        return _insuficiente("E3_invariancia", "sem questoes comuns entre edicoes")
    return {"analise": "E3_invariancia", "status": "ok", "comparacoes": comparacoes}


# ------------------------------------------------------------------ E4
def trienal(dfs_por_curso_ano, curso_key):
    """Tendencia por curso comparando apenas edicoes em que ele foi avaliado."""
    if curso_key not in dfs_por_curso_ano:
        return _insuficiente("E4_trienal", f"curso {curso_key} sem dados")
    serie = []
    for ano in sorted(dfs_por_curso_ano[curso_key].keys()):
        df = dfs_por_curso_ano[curso_key][ano]
        nota, _ = _nota_externa(df)
        if nota is None:
            continue
        v = nota.dropna()
        if len(v) >= 30:
            serie.append({"ano": ano, "media": float(v.mean()), "n": int(len(v))})
    if len(serie) < 2:
        return _insuficiente("E4_trienal", "curso com menos de 2 edicoes validas")
    valores = [p["media"] for p in serie]
    tendencia = float(np.polyfit(range(len(valores)), valores, 1)[0])
    return {"analise": "E4_trienal", "status": "ok", "curso": str(curso_key),
            "serie": serie, "tendencia_por_edicao": tendencia}


# ------------------------------------------------------------------ E5
def formacao(df, ano=None):
    """Proficiencia por modalidade, categoria e tempo de curso."""
    nota, col = _nota_externa(df)
    if nota is None:
        return _insuficiente("E5_formacao", "sem nota externa")
    d = df.copy()
    d["_nota"] = nota
    d = d.dropna(subset=["_nota"])
    saida = {"analise": "E5_formacao", "status": "ok", "ano": ano, "n": int(len(d))}
    if "CO_MODALIDADE" in d.columns:
        g = d.groupby("CO_MODALIDADE")["_nota"].agg(["mean", "count"])
        saida["por_modalidade"] = g[g["count"] >= 30].to_dict("index")
    if "NU_ANO_CURSO" in d.columns:
        d["_ano_curso"] = pd.to_numeric(d["NU_ANO_CURSO"], errors="coerce")
        g = d.dropna(subset=["_ano_curso"]).groupby("_ano_curso")["_nota"].agg(["mean", "count"])
        saida["por_ano_curso"] = g[g["count"] >= 30].to_dict("index")
    return saida


# ------------------------------------------------------------------ E6
def eficiencia(df, ano=None):
    """Fronteira DEA simples: eficiencia = nota media / contrapartida de escala."""
    nota, col = _nota_externa(df)
    if nota is None:
        return _insuficiente("E6_eficiencia", "sem nota externa")
    d = df.copy()
    d["_nota"] = nota
    d = d.dropna(subset=["_nota"])
    if "CO_IES" not in d.columns:
        return _insuficiente("E6_eficiencia", "sem CO_IES")
    g = d.groupby("CO_IES")["_nota"].agg(["mean", "count", "size"]).reset_index()
    g = g[g["count"] >= 30].copy()
    if g.empty:
        return _insuficiente("E6_eficiencia", "IEs com amostra insuficiente")
    escala = g["size"].astype(float)
    g["eficiencia"] = g["mean"] / (escala / escala.max())
    g = g.sort_values("eficiencia", ascending=False)
    return {"analise": "E6_eficiencia", "status": "ok", "ano": ano,
            "top_ies": g.head(10).to_dict("records"), "n_ies": int(len(g))}


# ------------------------------------------------------------------ E7
def cluster_ies(df, ano=None, n_clusters=3):
    """Perfis de IEs via KMeans sobre indicadores agregados."""
    nota, col = _nota_externa(df)
    if nota is None or "CO_IES" not in df.columns:
        return _insuficiente("E7_cluster_ies", "faltam nota externa ou CO_IES")
    d = df.copy()
    d["_nota"] = nota
    d = d.dropna(subset=["_nota"])
    agre = d.groupby("CO_IES")["_nota"].agg(["mean", "std", "count"]).reset_index()
    agre = agre[agre["count"] >= 30].fillna(0)
    if len(agre) < n_clusters * 3:
        return _insuficiente("E7_cluster_ies", f"poucas IEs (n={len(agre)})")
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler
    X = StandardScaler().fit_transform(agre[["mean", "std"]].values)
    km = KMeans(n_clusters=n_clusters, n_init=10, random_state=42).fit(X)
    agre["cluster"] = km.labels_
    perfis = agre.groupby("cluster")[["mean", "std", "count"]].mean().to_dict("index")
    return {"analise": "E7_cluster_ies", "status": "ok", "ano": ano,
            "n_clusters": n_clusters, "perfis": perfis, "n_ies": int(len(agre))}


# ------------------------------------------------------------------ E8
def distal(df, ano=None):
    """Associacao entre proficiencia (tercil) e desfechos distais do questionario."""
    nota, col = _nota_externa(df)
    if nota is None:
        return _insuficiente("E8_distal", "sem nota externa")
    candidatos = [c for c in ["QE_I01", "QE_I02", "QE_I03"] if c in df.columns]
    if not candidatos:
        return _insuficiente("E8_distal", "sem variaveis distais (QE_I*)")
    d = df.copy()
    d["_nota"] = nota
    d = d.dropna(subset=["_nota"])
    d["_tercil"] = pd.qcut(d["_nota"], 3, labels=["baixo", "medio", "alto"], duplicates="drop")
    saida = {"analise": "E8_distal", "status": "ok", "ano": ano, "n": int(len(d))}
    for var in candidatos:
        tab = pd.crosstab(d["_tercil"], d[var], normalize="index")
        saida[var] = tab.round(3).to_dict("index")
    return saida


# ------------------------------------------------------------------ E9
def sensibilidade(df, ano=None):
    """Robustez do ranking de cursos a peso amostral e limiar de excelencia."""
    nota, col = _nota_externa(df)
    if nota is None or "CO_GRUPO" not in df.columns:
        return _insuficiente("E9_sensibilidade", "faltam nota externa ou CO_GRUPO")
    d = df.copy()
    d["_nota"] = nota
    d = d.dropna(subset=["_nota"])
    peso = pd.to_numeric(d["PESO_AMOSTRA"], errors="coerce") if "PESO_AMOSTRA" in d.columns else None
    simples = d.groupby("CO_GRUPO")["_nota"].mean()
    if peso is not None and peso.notna().sum() > 0:
        d["_peso"] = peso.fillna(peso.median())
        ponderada = d.groupby("CO_GRUPO").apply(
            lambda g: np.average(g["_nota"], weights=g["_peso"]), include_groups=False)
    else:
        ponderada = simples
    limiar = float(d["_nota"].quantile(0.75))
    taxa_exc = d.assign(_exc=d["_nota"] >= limiar).groupby("CO_GRUPO")["_exc"].mean()
    comp = pd.DataFrame({"simples": simples, "ponderada": ponderada, "taxa_excelencia": taxa_exc})
    comp = comp.dropna()
    if len(comp) < 3:
        return _insuficiente("E9_sensibilidade", "poucos cursos")
    rank_s = comp["simples"].rank(ascending=False)
    rank_p = comp["ponderada"].rank(ascending=False)
    tau = float(rank_s.corr(rank_p, method="kendall"))
    return {"analise": "E9_sensibilidade", "status": "ok", "ano": ano,
            "tau_kendall_peso": tau, "limiar_excelencia": limiar,
            "tabela": comp.round(3).to_dict("index"), "n_cursos": int(len(comp))}


def executar_trienal_edicao(caminho_csv=None, df=None, **kwargs):
    """Motor por edicao (interface executar_por_edicao): roda E1/E2/E5/E6/E9 no df."""
    import json
    from config import PASTA_MODELOS
    if df is None:
        if caminho_csv is None:
            print("  [trienal] sem dados; ignorando.")
            return None
        df = pd.read_csv(caminho_csv, sep=";", encoding="utf-8-sig", low_memory=False)
    ano = None
    if "NU_ANO" in df.columns and len(df):
        try:
            ano = int(pd.to_numeric(df["NU_ANO"], errors="coerce").dropna().iloc[0])
        except Exception:
            ano = None
    resultados = {
        "E1_equidade": equidade(df, ano),
        "E2_valor_agregado": valor_agregado(df, ano),
        "E5_formacao": formacao(df, ano),
        "E6_eficiencia": eficiencia(df, ano),
        "E9_sensibilidade": sensibilidade(df, ano),
    }
    pasta = PASTA_MODELOS / "analises_tese"
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"analises_tese_edicao_{ano or 'desconhecida'}.json"
    destino.write_text(json.dumps(resultados, ensure_ascii=False, indent=2, default=str),
                       encoding="utf-8")
    print(f"  [trienal] gravado: {destino.name}")
    return resultados
