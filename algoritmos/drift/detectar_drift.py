"""
Detecao de Drift Distributivo
=============================
Detecta quando a distribuicao das respostas/indicadores de um conjunto em
'producao' difere de um conjunto de 'referencia' (treinamento).

1. UNIVARIADO (avalia cada variavel isoladamente):
   - Kolmogorov-Smirnov (K-S test) -> continuas/binary (localizacao e forma)
   - Wasserstein metric  (Earth Mover's Distance) -> continuas/binary
   - Cramer's V          -> discretas/categoricas
   - PSI (Population Stability Index) -> discretas/categoricas

2. MULTIVARIADO (avalia o conjunto na sua distribuicao conjunta):
   - PCA reconstruction error estilo NannyML: ajusta um PCA no conjunto de
     referencia e mede o erro de reconstrucao (compressao + descompressao).
     Se o erro do conjunto em producao supera a linha de base (erro do proprio
     conjunto de referencia em validacao), ha indice forte de drift.
"""
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

EPS = 1e-4

# ---------------------------------------------------------------------------
# Medidas univariadas
# ---------------------------------------------------------------------------

def ks_wasserstein(ref, prod):
    """Two-sample K-S test + distancia de Wasserstein."""
    r = np.asarray(ref, dtype=float)
    p = np.asarray(prod, dtype=float)
    r = r[np.isfinite(r)]
    p = p[np.isfinite(p)]
    if len(r) < 3 or len(p) < 3:
        return np.nan, np.nan, np.nan
    d, p_val = stats.ks_2samp(r, p)
    w = float(stats.wasserstein_distance(r, p))
    return float(d), float(p_val), w


def cramers_v(a, b):
    """Cramer's V entre duas distribuicoes discretas (tamanhos de amostra podem diferir).

    Constroi a tabela de contingencia 2 x k a partir das frequencias relativas de
    cada categoria em cada amostra - compara distribuicoes, nao pares observados."""
    a = np.asarray(a, dtype=float)[np.isfinite(np.asarray(a, dtype=float))]
    b = np.asarray(b, dtype=float)[np.isfinite(np.asarray(b, dtype=float))]
    if len(a) < 3 or len(b) < 3:
        return np.nan
    cats = np.unique(np.concatenate([a, b]))
    if len(cats) < 2:
        return 0.0
    freqs_a = np.array([np.mean(a == c) for c in cats], dtype=float)
    freqs_b = np.array([np.mean(b == c) for c in cats], dtype=float)
    na, nb = len(a), len(b)
    contig = np.vstack([freqs_a * na, freqs_b * nb])
    chi2, p_val, dof, exp = stats.chi2_contingency(contig, correction=False)
    denom = (na + nb) * (min(contig.shape) - 1)
    return float(np.sqrt(chi2 / denom)) if denom > 0 else np.nan


def psi(ref, prod, n_bins=10):
    """Population Stability Index entre duas distribuicoes."""
    r = np.asarray(ref, dtype=float)
    p = np.asarray(prod, dtype=float)
    r = r[np.isfinite(r)]
    p = p[np.isfinite(p)]
    if len(r) < 2 or len(p) < 2:
        return np.nan
    if len(np.unique(r)) <= 10:
        cats = np.unique(np.concatenate([r, p]))
        pe = np.array([np.mean(r == c) for c in cats])
        pa = np.array([np.mean(p == c) for c in cats])
    else:
        edges = np.unique(np.quantile(r, np.linspace(0.0, 1.0, n_bins + 1)))
        if len(edges) < 2:
            return 0.0
        pe, _ = np.histogram(r, bins=edges)
        pa, _ = np.histogram(p, bins=edges)
        pe = pe / pe.sum() if pe.sum() > 0 else pe
        pa = pa / pa.sum() if pa.sum() > 0 else pa
    pe = np.clip(pe, EPS, 1.0)
    pa = np.clip(pa, EPS, 1.0)
    return float(np.sum((pa - pe) * np.log(pa / pe)))


def _classificar_tipo(valores):
    """'binario' (2 valores), 'discreto' (<=10 valores) ou 'continuo'."""
    vals = pd.to_numeric(pd.Series(valores), errors="coerce").dropna().unique()
    if len(vals) <= 2:
        return "binario"
    if len(vals) <= 10:
        return "discreto"
    return "continuo"


def _status_ps(psi_valor):
    """Regra convencional do PSI: <0.1 sem drift; 0.1-0.25 moderado; >=0.25 forte."""
    if np.isnan(psi_valor):
        return "-"
    if psi_valor < 0.1:
        return "Sem drift"
    if psi_valor < 0.25:
        return "Drift moderado"
    return "Drift forte"


def drift_univariado(df_ref, df_prod, colunas):
    """Tabela univariada de drift para cada coluna (ref = treinamento, prod = producao).

    Retorna DataFrame [Coluna, Tipo, KS_D, KS_p, Wasserstein, Cramer_V, PSI, Status]."""
    registros = []
    for col in colunas:
        if col not in df_ref.columns or col not in df_prod.columns:
            continue
        r = pd.to_numeric(df_ref[col], errors="coerce").dropna()
        p = pd.to_numeric(df_prod[col], errors="coerce").dropna()
        if len(r) < 3 or len(p) < 3:
            continue
        tipo = _classificar_tipo(r)
        d_ks, p_ks, w = ks_wasserstein(r, p)
        cv = np.nan
        ps = np.nan
        if tipo in ("binario", "discreto"):
            cv = cramers_v(r, p)
            ps = psi(r, p)
        registros.append({
            "Coluna": col,
            "Tipo": tipo,
            "KS_D": round(d_ks, 4) if not np.isnan(d_ks) else np.nan,
            "KS_p": round(p_ks, 4) if not np.isnan(p_ks) else np.nan,
            "Wasserstein": round(w, 4) if not np.isnan(w) else np.nan,
            "Cramer_V": round(cv, 4) if not np.isnan(cv) else np.nan,
            "PSI": round(ps, 4) if not np.isnan(ps) else np.nan,
        })
    df_u = pd.DataFrame(registros)
    if df_u.empty:
        return df_u
    df_u["Status"] = df_u.apply(_status_linha, axis=1)
    return df_u


def _status_linha(linha):
    tipo = linha["Tipo"]
    if tipo in ("binario", "discreto"):
        st_ps = _status_ps(linha["PSI"])
        if st_ps.startswith("Drift"):
            return st_ps
        if not np.isnan(linha["KS_p"]) and linha["KS_p"] < 0.05:
            return "Drift (KS significativo)"
        return st_ps
    if not np.isnan(linha["KS_p"]) and linha["KS_p"] < 0.05:
        return "Drift (KS significativo)"
    return "Sem drift"


# ---------------------------------------------------------------------------
# Drift multivariado (PCA reconstruction, estilo NannyML)
# ---------------------------------------------------------------------------

def _erro_reconstrucao(pca, scaler, X):
    """MSE entre X padronizado e sua reconstrucao via PCA (compressao/descompressao)."""
    Z = scaler.transform(X)
    return float(np.mean((Z - pca.inverse_transform(pca.transform(Z))) ** 2))


def drift_pca_multivariado(df_ref, df_prod, colunas, explicar=0.8, n_splits=3):
    """Detecta drift multivariado pelo erro de reconstrucao do PCA (NannyML).

    Referencia: ajusta PCA sobre o conjunto de referencia; a linha de base e o
    erro medio de reconstrucao obtido em validacao cruzada sobre a propria
    referencia. Producao: erro de reconstrucao ao compactar/descompactar o
    conjunto em producao com o mesmo PCA. Se erro_prod > 1.25 * baseline -> drift.

    Retorna dict com metricas e DataFrame das variaveis de maior contribuicao."""
    cols = [c for c in colunas if c in df_ref.columns and c in df_prod.columns]
    if len(cols) < 3:
        return None

    X_ref = df_ref[cols].apply(pd.to_numeric, errors="coerce")
    X_prod = df_prod[cols].apply(pd.to_numeric, errors="coerce")
    # Remove linhas totalmente vazias
    X_ref = X_ref.dropna(how="all")
    X_prod = X_prod.dropna(how="all")
    if len(X_ref) < 20 or len(X_prod) < 20:
        return None
    X_ref = X_ref.fillna(0.0).to_numpy(dtype=float)
    X_prod = X_prod.fillna(0.0).to_numpy(dtype=float)

    scaler = StandardScaler().fit(X_ref)
    Zm = scaler.transform(X_ref)
    n_comp = max(2, min(10, len(cols)))
    explicado = 0.0
    pca = PCA(n_components=n_comp, random_state=42).fit(Zm)
    if hasattr(pca, "explained_variance_ratio_"):
        explicado = float(pca.explained_variance_ratio_.sum())

    # Linha de base honesta: erro de reconstrucao sobre a propria referencia (CV)
    from sklearn.model_selection import KFold
    validacao = KFold(n_splits=n_splits, shuffle=True, random_state=42)
    erros_base = []
    for idx_tr, idx_va in validacao.split(X_ref):
        sc = StandardScaler().fit(X_ref[idx_tr])
        p = PCA(n_components=n_comp, random_state=42).fit(sc.transform(X_ref[idx_tr]))
        Zva = sc.transform(X_ref[idx_va])
        erros_base.append(float(np.mean((Zva - p.inverse_transform(p.transform(Zva))) ** 2)))
    baseline = float(np.mean(erros_base))

    erro_prod = _erro_reconstrucao(pca, scaler, X_prod)
    ratio = erro_prod / baseline if baseline > 1e-9 else np.nan
    status = "Drift multivariado detectado" if (not np.isnan(ratio) and ratio > 1.25) else "Sem drift multivariado significativo"

    cargas = pd.DataFrame(pca.components_, columns=cols)
    contrib = cargas.pow(2).mean(axis=0).sort_values(ascending=False).head(5).reset_index()
    contrib.columns = ["Variavel", "Contribuicao (var explicada media)"]

    return {
        "mse_baseline": baseline,
        "mse_prod": erro_prod,
        "ratio": ratio if not np.isnan(ratio) else None,
        "status": status,
        "n_componentes": n_comp,
        "variancia_explicada": explicado,
        "n_ref": len(X_ref),
        "n_prod": len(X_prod),
        "principais": contrib,
    }


if __name__ == "__main__":
    rng = np.random.default_rng(42)
    df_ref = pd.DataFrame({f"Q{i}": (rng.random(3000) > 0.6).astype(int) for i in range(1, 26)}, )
    df_prod = pd.DataFrame({f"Q{i}": ((rng.random(3000) + (0.15 if i <= 8 else 0.0)) > 0.6).astype(int) for i in range(1, 26)})
    df_prod["NT_GER"] = rng.normal(45, 12, 3000)
    df_ref["NT_GER"] = rng.normal(55, 12, 3000)

    cols = [f"Q{i}" for i in range(1, 26)] + ["NT_GER"]
    uni = drift_univariado(df_ref, df_prod, cols)
    print("UNIVARIADO")
    print(uni.sort_values("PSI", ascending=False).head(8).to_string(index=False))
    mult = drift_pca_multivariado(df_ref, df_prod, cols)
    print("MULTIVARIADO")
    print(mult)