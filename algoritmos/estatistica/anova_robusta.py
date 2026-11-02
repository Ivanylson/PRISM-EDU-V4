"""
ANOVA robusta para dados educacionais (sem dependencias novas).
Testa pressupostos (Shapiro amostrado + Levene), fornece F e Kruskal-Wallis,
eta-quadrado/omega-quadrado com IC bootstrap, e post-hoc com correcao Holm.
"""
import numpy as np
import scipy.stats as stats

MAX_SHAPIRO_N = 5000


def formatar_p(p):
    """Formato APA: p < 0.001 senao 4 casas decimais."""
    if p is None or not np.isfinite(p):
        return "N/A"
    return "< 0.001" if p < 0.001 else f"{p:.4f}"


def _limpar_grupos(grupos, nomes):
    """Remove grupos vazios e valores nao-finitos."""
    grupos_limpos, nomes_limpos = [], []
    for i, g in enumerate(grupos):
        g = np.asarray(g, dtype=float)
        g = g[np.isfinite(g)]
        if len(g) > 0:
            grupos_limpos.append(g)
            nomes_limpos.append(nomes[i] if nomes else f"G{i + 1}")
    return grupos_limpos, nomes_limpos


def checar_normalidade(grupos, n_max=MAX_SHAPIRO_N, semente=42):
    """Shapiro-Wilk amostrado (mximo n_max por grupo) para N grande."""
    rng = np.random.default_rng(semente)
    resultado = []
    for g in grupos:
        if len(g) >= 3:
            amostra = g if len(g) <= n_max else rng.choice(g, size=n_max, replace=False)
            w, p = stats.shapiro(amostra)
            resultado.append({"W": float(w), "p": float(p), "n_testado": int(len(amostra))})
        else:
            resultado.append({"W": np.nan, "p": np.nan, "n_testado": int(len(g))})
    return resultado


def _eta_quadrado(f, k, n_total):
    if not np.isfinite(f) or f < 0:
        return np.nan
    df_entre = k - 1
    df_dentro = n_total - k
    return (f * df_entre) / ((f * df_entre) + df_dentro)


def _omega_quadrado(f, k, n_total):
    if not np.isfinite(f):
        return np.nan
    df_entre = k - 1
    numer = df_entre * (f - 1)
    denom = numer + n_total
    return numer / denom if denom > 0 else np.nan


def ic_bootstrap_eta(grupos, n_boot=1000, semente=42):
    """IC 95% bootstrap para eta-quadrado (percentile)."""
    rng = np.random.default_rng(semente)
    k = len(grupos)
    n_total = sum(len(g) for g in grupos)
    valores = []
    for _ in range(n_boot):
        amostras = [rng.choice(g, size=len(g), replace=True) for g in grupos]
        f_boot, _ = stats.f_oneway(*amostras)
        eta = _eta_quadrado(f_boot, k, n_total)
        if np.isfinite(eta):
            valores.append(eta)
    if not valores:
        return (np.nan, np.nan)
    return tuple(round(float(x), 4) for x in np.percentile(valores, [2.5, 97.5]))


def _holm_bonferroni(pvalues):
    """Correcao Holm-Bonferroni (mais poderosa que Bonferroni simples)."""
    p = np.asarray(pvalues, dtype=float)
    ordem = np.argsort(p)
    ajustados = np.empty_like(p)
    acumulado = 1.0
    m = len(p)
    for i, idx in enumerate(ordem):
        acumulado = min(acumulado, p[idx] * (m - i))
        ajustados[idx] = min(1.0, acumulado)
    return ajustados


def post_hoc(grupos, nomes, parametrico):
    """Post-hoc: Tukey HSD (parametrico) ou Mann-Whitney + Holm (nao parametrico)."""
    linhas = []
    k = len(grupos)
    if parametrico and k > 2:
        try:
            res = stats.tukey_hsd(*grupos)
            pmatriz = np.asarray(res.pvalue)
            for i in range(k):
                for j in range(i + 1, k):
                    if np.isfinite(pmatriz[i, j]):
                        mi = float(np.mean(grupos[i]))
                        mj = float(np.mean(grupos[j]))
                        linhas.append({
                            "Comparacao": f"{nomes[i]} vs {nomes[j]}",
                            "Diferenca_Medias": round(mi - mj, 4),
                            "p_ajustado": round(float(pmatriz[i, j]), 4),
                            "Metodo": "Tukey HSD",
                        })
        except Exception:
            parametrico = False
    if not parametrico:
        pares, ps = [], []
        for i in range(k):
            for j in range(i + 1, k):
                _, p = stats.mannwhitneyu(grupos[i], grupos[j], alternative="two-sided")
                pares.append((i, j))
                ps.append(float(p))
        ajustados = _holm_bonferroni(ps)
        for (i, j), p_adj in zip(pares, ajustados):
            mi = float(np.mean(grupos[i]))
            mj = float(np.mean(grupos[j]))
            linhas.append({
                "Comparacao": f"{nomes[i]} vs {nomes[j]}",
                "Diferenca_Medias": round(mi - mj, 4),
                "p_ajustado": round(float(p_adj), 4),
                "Metodo": "Mann-Whitney + Holm",
            })
    return linhas


def anova_robusta(grupos, nomes=None, n_boot_eta=1000, semente=42,
                  max_shapiro=MAX_SHAPIRO_N):
    """ANOVA com correcao metodologica para dados educacionais.

    Testa pressupostos (Shapiro amostrado para N grande + Levene),
    executa F parametrico e Kruskal-Wallis, calcula eta² e omega² com
    IC bootstrap, e realiza post-hoc (Tukey ou Mann-Whitney + Holm).

    Retorna dict com campos validos (verificacao: resultado['valido']).
    """
    grupos, nomes = _limpar_grupos(grupos, nomes)
    k = len(grupos)
    n_total = sum(len(g) for g in grupos)
    resultado = {"valido": k >= 2 and n_total >= 2}

    if not resultado["valido"]:
        resultado.update({"F": np.nan, "p_anova": np.nan, "eta2": np.nan, "omega2": np.nan})
        return resultado

    f, p_anova = stats.f_oneway(*grupos)
    h_kw, p_kw = stats.kruskal(*grupos)
    _, p_levene = stats.levene(*grupos)
    normalidades = checar_normalidade(grupos, max_shapiro, semente)
    normal_ok = all(nd["p"] > 0.05 or nd["n_testado"] < 3 for nd in normalidades)
    homocedastico = p_levene > 0.05
    parametrico = normal_ok and homocedastico

    resultado.update({
        "grupos": nomes,
        "n_por_grupo": [int(len(g)) for g in grupos],
        "media_por_grupo": [round(float(np.mean(g)), 4) for g in grupos],
        "desvio_por_grupo": [round(float(np.std(g, ddof=1)), 4) for g in grupos],
        "F": round(float(f), 4),
        "p_anova": float(p_anova),
        "eta2": round(_eta_quadrado(f, k, n_total), 4),
        "omega2": round(_omega_quadrado(f, k, n_total), 4),
        "IC95_eta2": ic_bootstrap_eta(grupos, n_boot_eta, semente),
        "shapiro": normalidades,
        "normalidade_ok": bool(normal_ok),
        "p_levene": round(float(p_levene), 4),
        "homocedastico": bool(homocedastico),
        "H_kruskal": round(float(h_kw), 4),
        "p_kruskal": float(p_kw),
        "escolha": "parametrica" if parametrico else "nao_parametrica",
        "post_hoc": post_hoc(grupos, nomes, parametrico),
    })
    return resultado
