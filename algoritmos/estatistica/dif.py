"""
DIF (Differential Item Functioning) por Mantel-Haenszel + correcao FDR.
Dependencias: numpy, pandas (ja presentes no projeto).
"""
import numpy as np
import pandas as pd


def fdr_bh(pvalues):
    """Correcao Benjamini-Hochberg (1995) para testes multiplos.
    Menos conservativa que Bonferroni; adequada para FDR controlado."""
    p = np.asarray(pvalues, dtype=float)
    m = len(p)
    if m == 0:
        return np.array([])
    ordem = np.argsort(p)
    ajustados = np.empty(m)
    acumulado = 1.0
    for i, idx in enumerate(ordem):
        acumulado = min(acumulado, p[idx] * m / (i + 1))
        ajustados[idx] = min(1.0, acumulado)
    return ajustados


def _classificacao_ets(delta):
    """Classificacao ETS (Equating) do Delta MH:
      A (desprezivel): |Δ| < 1
      B (leve a moderado): 1 <= |Δ| < 1.5
      C (moderado a grande): |Δ| >= 1.5
    """
    ad = abs(delta)
    if ad < 1:
        return "A (desprezivel)"
    if ad < 1.5:
        return "B (leve-moderado)"
    return "C (moderado-grande)"


def _mh_item(respostas_item, grupos, estratos):
    """Mantel-Haenszel para um item dicotomico.

    'respostas_item': array 0/1.
    'grupos': array 0/1 (0=referencia, 1=focal).
    'estratos': array inteiro de estratos de escore total.
    """
    a_total = b_total = c_total = d_total = 0.0
    soma_cent = 0.0
    soma_var = 0.0
    for estrato in np.unique(estratos):
        m = estratos == estrato
        y = respostas_item[m]
        g = grupos[m]
        T = int(m.sum())
        if T < 2:
            continue
        n1 = int(g.sum())
        n0 = T - n1
        m1 = int(y.sum())
        m0 = T - m1
        if n1 == 0 or n0 == 0 or m1 == 0 or m0 == 0:
            continue
        a_s = float(((g == 1) & (y == 1)).sum())
        b_s = float(((g == 1) & (y == 0)).sum())
        c_s = float(((g == 0) & (y == 1)).sum())
        d_s = float(((g == 0) & (y == 0)).sum())
        T_s = a_s + b_s + c_s + d_s
        if T_s == 0:
            continue
        a_total += a_s * d_s / T_s
        b_total += b_s * c_s / T_s
        e_a = n1 * m1 / T_s
        var_a = n1 * n0 * m1 * m0 / (T_s ** 2 * (T_s - 1))
        if var_a > 0:
            soma_cent += (a_s - e_a) / np.sqrt(var_a)
            soma_var += 1.0
    if b_total == 0:
        return None
    or_mh = a_total / b_total
    chi2 = (soma_cent ** 2) / soma_var if soma_var > 0 else 0.0
    delta = -2.35 * np.log(or_mh)
    import scipy.stats as stats
    p_chi = float(stats.chi2.sf(chi2, 1)) if chi2 > 0 else 1.0
    return {
        "OR_MH": round(or_mh, 4),
        "delta_MH": round(delta, 4),
        "qui_quadrado": round(chi2, 4),
        "p_valor": p_chi,
    }


def manter_haenszel_dif(df, colunas_questoes, coluna_grupo,
                        col_escore=None, n_estratos=5):
    """DIF por Mantel-Haenszel (Holland & Thayer, 1988) com classificacao
    ETS e FDR (Benjamini-Hochberg).

    Parâmetros:
      df: DataFrame com colunas de questoes (Q1..Q38), coluna_grupo e
          coluna escore.
      colunas_questoes: lista de nomes das colunas de questoes (Q1..Q38).
      coluna_grupo: nome da coluna binaria (1 = grupo focal, 0 = referencia).
      col_escore: coluna de escore total para estratificacao (default: soma
                  dos itens fornecidos).
      n_estratos: numero de estratos para MH (default=5, quintil).

    Retorna DataFrame com resultado por item.
    """
    colunas = [c for c in colunas_questoes if c in df.columns]
    df = df.copy()
    for c in colunas:
        df[c] = (pd.to_numeric(df[c], errors="coerce").fillna(0) == 1).astype(int)
    if col_escore is None:
        escore = df[colunas].sum(axis=1)
    else:
        escore = pd.to_numeric(df[col_escore], errors="coerce").fillna(0)
    estratos = pd.qcut(
        escore.rank(method="first"),
        q=n_estratos,
        labels=False,
    ).fillna(0).astype(int).values
    g = df[coluna_grupo].astype(int).values
    linhas = []
    for c in colunas:
        mh = _mh_item(df[c].values, g, estratos)
        if mh is None:
            continue
        linha = {"item": c, **mh}
        linha["classificacao_ETS"] = _classificacao_ets(linha["delta_MH"])
        linhas.append(linha)
    if not linhas:
        return pd.DataFrame()
    out = pd.DataFrame(linhas)
    out["p_fdr"] = fdr_bh(out["p_valor"].values)
    out["DIF_significativo"] = out["p_fdr"] < 0.05
    out = out.sort_values("delta_MH", key=lambda s: s.abs(), ascending=False)
    return out.reset_index(drop=True)
