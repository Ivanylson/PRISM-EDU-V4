"""
Fidedignidade: alpha de Cronbach e omega de McDonald.
Dependencias: numpy, sklearn (FactorAnalysis — ja presente no projeto).
"""
import numpy as np
from sklearn.decomposition import FactorAnalysis


def _casos_completos(X):
    """Remove linhas com NaN (analise de fidedignidade exige completude)."""
    X = np.asarray(X, dtype=float)
    return X[np.all(np.isfinite(X), axis=1)]


def alpha_cronbach(X):
    """Alpha de Cronbach (1951) — consistencia interna.

    Valores de referencia:
      >= 0.90 excelente | 0.80-0.89 bom | 0.70-0.79 aceitavel |
      0.60-0.69 questionavel | < 0.60 inaceitavel.
    """
    X = _casos_completos(X)
    if X.shape[0] < 2 or X.shape[1] < 2:
        return np.nan
    k = X.shape[1]
    var_itens = X.var(axis=0, ddof=1).sum()
    var_total = X.sum(axis=1).var(ddof=1)
    if var_total <= 0:
        return np.nan
    return float((k / (k - 1)) * (1 - var_itens / var_total))


def omega_mcdonald(X, n_fatores=1, semente=42):
    """Omega total de McDonald (1999) — fidedignidade unidimensional.

    Estima loadings via FactorAnalysis (scikit-learn) sobre itens
    padronizados.  omega = (Σλ)² / [(Σλ)² + Σ(1 − λ²)].

    Valores de referencia: >= 0.80 bom, 0.70-0.79 aceitavel,
    < 0.70 questionavel.  Nota: scikit-learn nao implementa ML-FA
    pura; os loadings sao aproximacoes por maxima verossimilhanca.
    """
    X = _casos_completos(X)
    if X.shape[0] < 2 or X.shape[1] < 2:
        return np.nan
    media = X.mean(axis=0)
    desv = X.std(axis=0, ddof=1)
    desv[desv == 0] = 1.0
    Z = (X - media) / desv
    n_comp = min(n_fatores, X.shape[1])
    fa = FactorAnalysis(n_components=n_comp, random_state=semente, max_iter=500)
    fa.fit(Z)
    lambdas = fa.components_.squeeze()
    soma_lambda = float(np.sum(lambdas))
    resid = 1.0 - lambdas ** 2
    numer = soma_lambda ** 2
    denom = numer + float(np.sum(resid))
    if denom <= 0:
        return np.nan
    return float(numer / denom)


def relatorio_fidedignidade(X, itens_nomes=None):
    """Gera relatorio completo de fidedignidade (alpha + omega) para um bloco
    de itens. X pode ser array ou DataFrame. Retorna dict."""
    X_arr = np.asarray(X, dtype=float)
    alpha = alpha_cronbach(X_arr)
    omega = omega_mcdonald(X_arr)

    def _classificar(alpha, omega):
        a = "excelente" if alpha >= 0.90 else "bom" if alpha >= 0.80 else "aceitavel" if alpha >= 0.70 else "questionavel" if alpha >= 0.60 else "inaceitavel"
        o = "excelente" if omega >= 0.90 else "bom" if omega >= 0.80 else "aceitavel" if omega >= 0.70 else "questionavel"
        return {"alpha_classe": a, "omega_classe": o}

    return {
        "n_itens": int(X_arr.shape[1]),
        "n_observacoes": int(X_arr.shape[0]),
        "alpha_cronbach": round(alpha, 4) if np.isfinite(alpha) else None,
        "omega_mcdonald": round(omega, 4) if np.isfinite(omega) else None,
        **_classificar(alpha, omega),
    }
