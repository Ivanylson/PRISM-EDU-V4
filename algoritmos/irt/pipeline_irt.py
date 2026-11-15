"""
Pipeline IRT (Teoria de Resposta ao Item) -- PRISM-EDU
=====================================================

Motivo: os artefatos em ``modelos/irt/`` estavam vazios, a ontologia
declarava um metodo IRT e o dashboard exibia uma secao "IRT" com dados
simulados (``np.random``). Este modulo substitui a simulacao por um ajuste
real de modelos dicotomicos de 1 e 2 parametros sobre os microdados.

Metodo
------
* Variavel latente padronizada: theta ~ N(0, 1) (identificacao por escala).
* Marginal Maximum Likelihood (MML) com quadratura de Gauss-Hermite.
* 1PL/Rasch: P(x=1|theta) = 1 / (1 + exp(-(theta - b_j)))
* 2PL:       P(x=1|theta) = 1 / (1 + exp(-a_j (theta - b_j)))
* Escolha entre 1PL e 2PL por BIC (menor e melhor).
* Proficiencia por aluno: EAP e SE (posterior), confiabilidade marginal.
* Ajuste de itens: infit/outfit MNSQ (Wright & Masters).
* Funcao de informacao do teste (TIF) e erro condicional.
* DIF por Mantel-Haenszel (reusa ``algoritmos.estatistica.dif``).
* Consistencia interna: alpha de Cronbach e omega de McDonald
  (reusa ``algoritmos.estatistica.fidedignidade``).

Uso
---
    python algoritmos/irt/pipeline_irt.py --edicao enade_2023
    python algoritmos/irt/pipeline_irt.py --edicao enade_2023 --limite-grupos 3
    # ou via orquestrador:
    python executar_por_edicao.py --edicoes enade_2023 --motores irt

Saidas (``modelos/irt/<edicao>/``):
    irt_itens_<curso>.csv        a, b, SE, infit/outfit, proporcao de acerto
    irt_abilidades_<curso>.csv   theta EAP/SE por aluno
    irt_tif_<curso>.csv          informacao e erro condicional por theta
    irt_residuos_<curso>.csv     pares de itens com correlacao residual alta
    irt_dif_<curso>.csv          DIF por sexo (quando a base permite)
    irt_resumo_geral.csv         uma linha por curso/edicao
    irt_manifesto.json           parametros, versoes, contagens e avisos
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# Permite executar o motor diretamente (python algoritmos/irt/pipeline_irt.py).
_RAIZ = Path(__file__).resolve().parent.parent.parent
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

VERSAO_IRT = "1.0.0"
SEP = ";"
DEC = ","
ENC = "utf-8-sig"


# ---------------------------------------------------------------------------
# Utilitarios numericos
# ---------------------------------------------------------------------------
def _sigmoide(z):
    """Sigmoide estavel numericamente."""
    z = np.asarray(z, dtype=float)
    return np.exp(-np.logaddexp(0.0, -z))


def _quadratura(n_nos=21):
    """Nos e pesos de Gauss-Hermite para a normal padrao."""
    x, w = np.polynomial.hermite.hermgauss(n_nos)
    return x * np.sqrt(2.0), w / np.sqrt(np.pi)


def _e_step(X, a, b, theta, pesos):
    """E-step: posteriores por aluno (R), probabilidades item x no (P) e log-verossimilhanca."""
    eta = (theta[:, None] - b[None, :]) * a[None, :]
    P = np.clip(_sigmoide(eta), 1e-10, 1.0 - 1e-10)
    logP = np.log(P)
    logQ = np.log1p(-P)
    ll = X @ logP.T + (1.0 - X) @ logQ.T + np.log(pesos)[None, :]
    m = ll.max(axis=1, keepdims=True)
    expo = np.exp(ll - m)
    s = expo.sum(axis=1, keepdims=True)
    R = expo / s
    loglik = float((m[:, 0] + np.log(s[:, 0])).sum())
    return R, P, loglik


def _gradiente(X, R, P, theta, a, b, modelo):
    """Gradiente analitico da log-verossimilhanca marginal."""
    theta_bar = R @ theta
    resid = X - R @ P                      # (N, J): E[x - P]
    g_b = -a * resid.sum(axis=0)           # d eta / d b = -a
    if modelo == "1PL":
        return g_b
    # parametrizacao log(a) para manter a > 0
    g_loga = a * (resid * (theta_bar[:, None] - b[None, :])).sum(axis=0)
    return np.concatenate([g_loga, g_b])


def _objetivo(params, X, theta, pesos, modelo):
    J = X.shape[1]
    if modelo == "1PL":
        b = params
        a = np.ones(J)
    else:
        # log(a) limitado evita overflow numerico durante a busca do otimizador
        a = np.exp(np.clip(params[:J], -10.0, 10.0))
        b = params[J:]
    R, P, loglik = _e_step(X, a, b, theta, pesos)
    grad = _gradiente(X, R, P, theta, a, b, modelo)
    return -loglik, -grad


def ajustar_modelo_irt(X, modelo="2PL", n_nos=21, max_iter=400):
    """Ajusta 1PL/2PL por MML. Retorna dict com parametros e diagnostico.

    X: matriz binaria (N x J) sem NaN (casos completos).
    """
    from scipy.optimize import minimize

    X = np.asarray(X, dtype=float)
    if X.ndim != 2:
        raise ValueError("X precisa ser uma matriz 2D.")
    N, J = X.shape
    if J < 2 or N < 50:
        raise ValueError(f"Base insuficiente para IRT (N={N}, J={J}).")

    theta, pesos = _quadratura(n_nos)
    p = np.clip(X.mean(axis=0), 0.02, 0.98)
    b0 = -np.log(p / (1.0 - p))
    if modelo == "1PL":
        x0 = np.clip(b0, -4.0, 4.0)
    else:
        x0 = np.concatenate([np.zeros(J), np.clip(b0, -4.0, 4.0)])

    res = minimize(
        _objetivo,
        x0,
        args=(X, theta, pesos, modelo),
        jac=True,
        method="L-BFGS-B",
        options={"maxiter": max_iter, "ftol": 1e-10, "gtol": 1e-7, "maxls": 60},
    )

    # Nunca aceitar parametros nao finitos: recupera a inicializacao
    params = res.x if np.all(np.isfinite(res.x)) else x0
    if modelo == "1PL":
        b = params
        a = np.ones(J)
    else:
        # log(a) limitado evita overflow numerico durante a busca do otimizador
        a = np.exp(np.clip(params[:J], -10.0, 10.0))
        b = params[J:]

    R, P, loglik = _e_step(X, a, b, theta, pesos)
    theta_bar = R @ theta
    var_bar = np.maximum(R @ (theta ** 2.0) - theta_bar ** 2.0, 0.0)
    theta_se = np.sqrt(var_bar)

    # Ajuste de itens na proficiencia EAP
    eta = (theta_bar[:, None] - b[None, :]) * a[None, :]
    P_eap = np.clip(_sigmoide(eta), 1e-10, 1.0 - 1e-10)
    w = P_eap * (1.0 - P_eap)
    z = (X - P_eap) / np.sqrt(w)
    outfit = (z ** 2).mean(axis=0)
    infit = ((X - P_eap) ** 2).sum(axis=0) / np.maximum(w.sum(axis=0), 1e-12)

    # Erros-padrao aproximados por item (informacao observada condicional)
    se_a = np.full(J, np.nan)
    se_b = np.full(J, np.nan)
    for j in range(J):
        if modelo == "1PL":
            i22 = float(np.sum(w[:, j]))
            if i22 > 0:
                se_b[j] = 1.0 / np.sqrt(i22)
        else:
            i11 = float(np.sum(w[:, j] * (theta_bar - b[j]) ** 2))
            i12 = float(-np.sum(w[:, j] * a[j] * (theta_bar - b[j])))
            i22 = float(np.sum(w[:, j] * a[j] ** 2))
            det = i11 * i22 - i12 ** 2
            if det > 0:
                se_a[j] = np.sqrt(i22 / det)
                se_b[j] = np.sqrt(i11 / det)

    var_eap = float(np.var(theta_bar, ddof=1)) if N > 1 else np.nan
    confiabilidade = 1.0 - float(np.mean(theta_se ** 2)) / var_eap if var_eap > 0 else np.nan
    if np.isfinite(confiabilidade):
        confiabilidade = float(min(1.0, max(0.0, confiabilidade)))

    n_params = J if modelo == "1PL" else 2 * J
    aic = 2.0 * n_params - 2.0 * loglik
    bic = np.log(N) * n_params - 2.0 * loglik

    # Correlacao residual (independencia local): pares com |r| mais alto
    Zres = (X - P_eap) / np.sqrt(np.maximum(w, 1e-12))
    if J >= 2:
        corr = np.corrcoef(Zres, rowvar=False)
        corr = np.nan_to_num(corr, nan=0.0, posinf=0.0, neginf=0.0)
        iu = np.triu_indices(J, k=1)
        r_pares = corr[iu]
        n_pares_altos = int(np.sum(np.abs(r_pares) > 0.30))
        max_abs = float(np.max(np.abs(r_pares))) if r_pares.size else 0.0
    else:
        corr = np.zeros((J, J))
        r_pares = np.array([])
        n_pares_altos = 0
        max_abs = 0.0

    return {
        "modelo": modelo,
        "a": a,
        "b": b,
        "a_se_aprox": se_a,
        "b_se_aprox": se_b,
        "outfit": outfit,
        "infit": infit,
        "prop_acerto": X.mean(axis=0),
        "theta_eap": theta_bar,
        "theta_se": theta_se,
        "loglik": loglik,
        "aic": aic,
        "bic": bic,
        "n_params": n_params,
        "N": N,
        "J": J,
        "confiabilidade_marginal": confiabilidade,
        "theta_medio": float(np.mean(theta_bar)),
        "theta_dp": float(np.std(theta_bar, ddof=1)) if N > 1 else np.nan,
        "outfit_medio": float(np.mean(outfit)),
        "n_itens_outfit_ruim": int(np.sum((outfit < 0.5) | (outfit > 1.5))),
        "n_pares_resid_alta": n_pares_altos,
        "max_corr_residual": max_abs,
        "corr_residual": corr,
        "convergiu": bool(getattr(res, "success", False)),
        "mensagem_otimizador": str(getattr(res, "message", "")),
        "n_iter": int(getattr(res, "nit", 0)),
        "P_eap": P_eap,
    }


def funcao_informacao(a, b, grade=None):
    """TIF e erro condicional do teste em uma grade de theta."""
    if grade is None:
        grade = np.linspace(-4.0, 4.0, 161)
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    P = np.clip(_sigmoide((grade[:, None] - b[None, :]) * a[None, :]), 1e-10, 1 - 1e-10)
    info = (a[None, :] ** 2 * P * (1.0 - P)).sum(axis=1)
    se = 1.0 / np.sqrt(np.maximum(info, 1e-12))
    return pd.DataFrame({"theta": grade, "informacao": info, "erro_padrao": se})


# ---------------------------------------------------------------------------
# Preparacao da matriz de respostas
# ---------------------------------------------------------------------------
def _colunas_questao(df):
    cols = [c for c in df.columns if isinstance(c, str) and re.fullmatch(r"Q\d{1,3}", c)]
    return sorted(cols, key=lambda c: int(c[1:]))


def preparar_matriz_respostas(df_curso, max_itens=60, n_min_classe=10,
                              cobertura_min=0.80, max_alunos=6000, seed=42):
    """Seleciona itens dicotomicos utilizaveis e retorna X + DataFrame alinhado.

    Regras (documentadas para auditoria):
      * item mantido se >= ``cobertura_min`` das linhas tem 0/1 e as duas
        categorias aparecem >= ``n_min_classe`` vezes;
      * se houver mais de ``max_itens`` itens, mantem os de maior variancia
        (p*(1-p)), que sao os mais informativos, e devolve em ordem original;
      * casos completos apenas (IRT dicotomico implementado sem imputacao);
      * se N > ``max_alunos``, amostra deterministica (seed fixa) para o ajuste.
    """
    qcols = _colunas_questao(df_curso)
    if not qcols:
        raise ValueError("Nenhuma coluna Q* encontrada no recorte.")

    M = df_curso[qcols].apply(pd.to_numeric, errors="coerce")
    M = M.where(M.isin([0, 1]))

    cobertura = M.notna().mean()
    n1 = (M == 1).sum()
    n0 = (M == 0).sum()
    validos = [
        c for c in qcols
        if cobertura.get(c, 0) >= cobertura_min
        and n1.get(c, 0) >= n_min_classe
        and n0.get(c, 0) >= n_min_classe
    ]
    if len(validos) < 2:
        raise ValueError(
            f"Itens dicotomicos insuficientes (validos={len(validos)}, "
            f"encontrados={len(qcols)})."
        )

    if len(validos) > max_itens:
        var = M[validos].mean().mul(1 - M[validos].mean())
        escolhidos = set(var.sort_values(ascending=False).head(max_itens).index)
        validos = [c for c in validos if c in escolhidos]

    meta_cols = [c for c in
                 ["ALUNO", "CO_IES", "CO_GRUPO", "CO_CURSO", "NU_ANO",
                  "TP_SEXO", "NT_GER", "NT_DIS_CE", "CO_REGIAO_CURSO"]
                 if c in df_curso.columns]
    base = df_curso[validos + meta_cols].copy()
    base[validos] = base[validos].apply(pd.to_numeric, errors="coerce")
    base = base.dropna(subset=validos)
    base[validos] = base[validos].astype(int)

    n_descartados = int(len(df_curso) - len(base))
    if len(base) > max_alunos:
        base = base.sample(n=max_alunos, random_state=seed).reset_index(drop=True)

    if len(base) < 50:
        raise ValueError(f"Casos completos insuficientes apos filtro (N={len(base)}).")

    X = base[validos].to_numpy(dtype=float)
    return X, base, validos, n_descartados


# ---------------------------------------------------------------------------
# Estimacao por curso
# ---------------------------------------------------------------------------
def _correlacoes(serie_theta, base, coluna):
    if coluna not in base.columns:
        return None, None, 0
    y = pd.to_numeric(base[coluna], errors="coerce").to_numpy(dtype=float)
    x = np.asarray(serie_theta, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < 20:
        return None, None, int(mask.sum())
    from scipy.stats import pearsonr, spearmanr
    try:
        r = float(pearsonr(x[mask], y[mask]).statistic)
    except Exception:
        r = None
    try:
        rho = float(spearmanr(x[mask], y[mask]).statistic)
    except Exception:
        rho = None
    return r, rho, int(mask.sum())


def _calcular_dif(base, itens, grupo_col="TP_SEXO"):
    """DIF por Mantel-Haenszel entre sexos (focal = masculino)."""
    if grupo_col not in base.columns:
        return None
    grupos = base[grupo_col].astype(str).str.strip().str.upper().str[0]
    mask = grupos.isin(["M", "F"])
    if int(mask.sum()) < 100 or grupos[mask].nunique() < 2:
        return None
    sub = base.loc[mask, itens + [grupo_col]].copy()
    sub["_grupo_focal"] = (grupos[mask].values == "M").astype(int)
    try:
        from algoritmos.estatistica.dif import manter_haenszel_dif
        out = manter_haenszel_dif(
            sub, itens, "_grupo_focal", col_escore=None, n_estratos=5
        )
        if out is None or out.empty:
            return None
        out.insert(0, "grupo", "sexo (ref=F, focal=M)")
        return out
    except Exception:
        return None


def estimar_irt_curso(df_curso, nome_curso="", edicao="", max_alunos=6000,
                      max_itens=60, n_nos=21, com_dif=True, seed=42):
    """Estima IRT de um curso e devolve artefatos em memoria.

    Retorna dict com DataFrames ``itens``, ``habilidades``, ``tif``,
    ``dif``, ``residuos`` e o dicionario ``resumo``.
    """
    t0 = time.time()
    X, base, itens, n_descartados = preparar_matriz_respostas(
        df_curso, max_itens=max_itens, max_alunos=max_alunos, seed=seed
    )

    ajustes = {}
    for modelo in ("1PL", "2PL"):
        try:
            ajustes[modelo] = ajustar_modelo_irt(X, modelo=modelo, n_nos=n_nos)
        except Exception as exc:  # pragma: no cover - robustez operacional
            ajustes[modelo] = {"erro": str(exc)}

    candidatos = {k: v for k, v in ajustes.items() if "erro" not in v}
    if not candidatos:
        erros = "; ".join(f"{k}: {v['erro']}" for k, v in ajustes.items())
        raise RuntimeError(f"Falha no ajuste IRT: {erros}")

    escolhido = min(candidatos, key=lambda k: candidatos[k]["bic"])
    fit = candidatos[escolhido]

    # Itens
    df_itens = pd.DataFrame({
        "item": itens,
        "a_discriminacao": np.round(fit["a"], 4),
        "b_dificuldade": np.round(fit["b"], 4),
        "a_se_aprox": np.round(fit["a_se_aprox"], 4),
        "b_se_aprox": np.round(fit["b_se_aprox"], 4),
        "prop_acerto": np.round(fit["prop_acerto"], 4),
        "outfit_mnsq": np.round(fit["outfit"], 4),
        "infit_mnsq": np.round(fit["infit"], 4),
    })
    df_itens["ajuste_outfit"] = np.where(
        df_itens["outfit_mnsq"] < 0.5, "superajuste",
        np.where(df_itens["outfit_mnsq"] > 1.5, "ruim", "aceitavel"))

    # Habilidades
    df_hab = base.copy().reset_index(drop=True)
    df_hab["theta_eap"] = np.round(fit["theta_eap"], 5)
    df_hab["theta_se"] = np.round(fit["theta_se"], 5)
    df_hab["escore_bruto"] = X.sum(axis=1).astype(int)
    df_hab["n_itens"] = len(itens)
    # percentil e tercil para leitura pedagogica
    df_hab["percentil_theta"] = (df_hab["theta_eap"].rank(pct=True) * 100).round(1)

    # TIF
    df_tif = funcao_informacao(fit["a"], fit["b"])

    # Residuos (independencia local)
    corr = fit.get("corr_residual")
    linhas_res = []
    if corr is not None and len(itens) >= 2:
        for i in range(len(itens)):
            for j in range(i + 1, len(itens)):
                linhas_res.append({
                    "item_1": itens[i], "item_2": itens[j],
                    "corr_residual": round(float(corr[i, j]), 4),
                })
        df_res = pd.DataFrame(linhas_res)
        df_res["abs_corr"] = df_res["corr_residual"].abs()
        df_res = df_res.sort_values("abs_corr", ascending=False).head(40)
    else:
        df_res = pd.DataFrame(columns=["item_1", "item_2", "corr_residual", "abs_corr"])

    # DIF
    df_dif = _calcular_dif(base, itens) if com_dif else None

    # Fidedignidade
    from algoritmos.estatistica.fidedignidade import relatorio_fidedignidade
    try:
        fid = relatorio_fidedignidade(X)
    except Exception:
        fid = {"alpha_cronbach": None, "omega_mcdonald": None}

    r_ger, rho_ger, n_ger = _correlacoes(df_hab["theta_eap"], df_hab, "NT_GER")
    r_disc, rho_disc, n_disc = _correlacoes(df_hab["theta_eap"], df_hab, "NT_DIS_CE")

    resumo = {
        "edicao": edicao,
        "curso": nome_curso or "curso",
        "n_alunos": int(fit["N"]),
        "n_itens": int(fit["J"]),
        "n_descartados_por_falta": int(n_descartados),
        "modelo_escolhido": escolhido,
        "criterio_escolha": "menor BIC entre 1PL e 2PL",
        "bic_1pl": round(float(candidatos["1PL"]["bic"]), 4) if "1PL" in candidatos else None,
        "bic_2pl": round(float(candidatos["2PL"]["bic"]), 4) if "2PL" in candidatos else None,
        "loglik": round(float(fit["loglik"]), 4),
        "aic": round(float(fit["aic"]), 4),
        "bic": round(float(fit["bic"]), 4),
        "confiabilidade_marginal": round(float(fit["confiabilidade_marginal"]), 4)
        if fit["confiabilidade_marginal"] == fit["confiabilidade_marginal"] else None,
        "theta_medio": round(float(fit["theta_medio"]), 4),
        "theta_dp": round(float(fit["theta_dp"]), 4),
        "alpha_cronbach": fid.get("alpha_cronbach"),
        "omega_mcdonald": fid.get("omega_mcdonald"),
        "outfit_medio": round(float(fit["outfit_medio"]), 4),
        "n_itens_outfit_ruim": int(fit["n_itens_outfit_ruim"]),
        "max_corr_residual": round(float(fit["max_corr_residual"]), 4),
        "n_pares_resid_alta": int(fit["n_pares_resid_alta"]),
        "corr_theta_ntger": round(r_ger, 4) if r_ger is not None else None,
        "spearman_theta_ntger": round(rho_ger, 4) if rho_ger is not None else None,
        "n_corr_ntger": n_ger,
        "corr_theta_ntdisce": round(r_disc, 4) if r_disc is not None else None,
        "n_corr_ntdisce": n_disc,
        "dif_por_sexo": bool(df_dif is not None and not df_dif.empty),
        "convergiu": bool(fit["convergiu"]),
        "n_iter": int(fit["n_iter"]),
        "tempo_seg": round(time.time() - t0, 2),
        "versao_irt": VERSAO_IRT,
    }

    return {
        "itens": df_itens,
        "habilidades": df_hab,
        "tif": df_tif,
        "dif": df_dif,
        "residuos": df_res,
        "resumo": resumo,
        "ajustes": {k: {kk: vv for kk, vv in v.items()
                        if kk not in ("P_eap", "corr_residual")}
                    for k, v in candidatos.items()},
    }


# ---------------------------------------------------------------------------
# Persistencia
# ---------------------------------------------------------------------------
def _slug(nome):
    from config import formatar_nome_curso
    return formatar_nome_curso(str(nome))


def salvar_artefatos_curso(resultado, pasta: Path, slug: str):
    pasta.mkdir(parents=True, exist_ok=True)
    resultado["itens"].to_csv(pasta / f"irt_itens_{slug}.csv", index=False,
                              sep=SEP, decimal=DEC, encoding=ENC)
    resultado["habilidades"].to_csv(pasta / f"irt_abilidades_{slug}.csv", index=False,
                                    sep=SEP, decimal=DEC, encoding=ENC)
    resultado["tif"].to_csv(pasta / f"irt_tif_{slug}.csv", index=False,
                            sep=SEP, decimal=DEC, encoding=ENC)
    if resultado["residuos"] is not None and not resultado["residuos"].empty:
        resultado["residuos"].to_csv(pasta / f"irt_residuos_{slug}.csv", index=False,
                                     sep=SEP, decimal=DEC, encoding=ENC)
    if resultado["dif"] is not None and not resultado["dif"].empty:
        resultado["dif"].to_csv(pasta / f"irt_dif_{slug}.csv", index=False,
                                sep=SEP, decimal=DEC, encoding=ENC)


def _resolver_caminho_edicao(edicao, caminho_csv=None):
    if caminho_csv:
        return Path(caminho_csv)
    from config import caminho_arquivo_edicao
    caminho = caminho_arquivo_edicao(edicao) if edicao else None
    return Path(caminho) if caminho else None


def executar_irt_edicao(caminho_csv=None, df=None, edicao=None, limite_grupos=None,
                        max_alunos=6000, max_itens=60, n_nos=21, seed=42):
    """Executa o motor IRT em uma edicao inteira e grava os artefatos.

    Assinatura compativel com ``executar_por_edicao.py``:
    ``executar_irt_edicao(caminho_csv=None, df=df)``.
    """
    from config import (nome_grupo_ano, normalizar_coluna_grupo,
                        pasta_saida_edicao, SEPARADOR, ENCODING)

    edicao = edicao or os.environ.get("PRISM_EDICAO", "") or "sem_edicao"
    if df is None:
        caminho = _resolver_caminho_edicao(edicao, caminho_csv)
        if caminho is None or not Path(caminho).exists():
            print(f"  [IRT] Sem arquivo de microdados para {edicao}.")
            return None
        print(f"  [IRT] Carregando {Path(caminho).name} ...")
        df = pd.read_csv(caminho, sep=SEPARADOR, encoding=ENCODING, low_memory=False)

    df = normalizar_coluna_grupo(df)
    ano = None
    try:
        ano = int(str(edicao).split("_")[-1])
    except (ValueError, IndexError):
        pass

    pasta = pasta_saida_edicao("irt", edicao)
    grupos = sorted(pd.to_numeric(df["CO_GRUPO"], errors="coerce").dropna().unique())
    if limite_grupos:
        grupos = grupos[:int(limite_grupos)]

    print(f"\n  === IRT ({edicao}) - {len(grupos)} curso(s) ===")
    resumos = []
    for grupo in grupos:
        sub = df[pd.to_numeric(df["CO_GRUPO"], errors="coerce") == grupo]
        nome = nome_grupo_ano(grupo, ano)
        slug = _slug(nome)
        try:
            resultado = estimar_irt_curso(
                sub, nome_curso=nome, edicao=edicao,
                max_alunos=max_alunos, max_itens=max_itens, n_nos=n_nos, seed=seed,
            )
            salvar_artefatos_curso(resultado, pasta, slug)
            res = resultado["resumo"]
            res["slug"] = slug
            resumos.append(res)
            print(f"    {nome}: N={res['n_alunos']}, J={res['n_itens']}, "
                  f"modelo={res['modelo_escolhido']}, "
                  f"conf={res['confiabilidade_marginal']}, "
                  f"{res['tempo_seg']}s")
        except Exception as exc:
            print(f"    [AVISO] {nome}: {exc}")

    manifesto = {
        "versao": VERSAO_IRT,
        "edicao": edicao,
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "parametros": {
            "max_alunos_por_curso": max_alunos,
            "max_itens": max_itens,
            "nos_quadratura": n_nos,
            "seed": seed,
            "criterio_modelo": "BIC (1PL vs 2PL)",
            "identificacao": "theta ~ N(0,1)",
        },
        "ambiente": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
        },
        "n_cursos": len(resumos),
        "cursos": [r["curso"] for r in resumos],
        "avisos": [
            "IRT dicotomico com casos completos; itens sem cobertura minima foram excluidos.",
            "Erros-padrao de itens sao aproximados (informacao condicional por item).",
            "DIF por Mantel-Haenszel usa sexo como grupo focal (M) vs referencia (F).",
            "A escala theta e padronizada por edicao; comparacoes entre edicoes exigem ancora comum.",
        ],
    }
    (pasta / "irt_manifesto.json").write_text(
        json.dumps(manifesto, ensure_ascii=False, indent=2), encoding="utf-8")

    if resumos:
        df_res = pd.DataFrame(resumos)
        df_res.to_csv(pasta / "irt_resumo_geral.csv", index=False,
                      sep=SEPARADOR, decimal=",", encoding=ENCODING)
        print(f"  [IRT] Resumo: {pasta / 'irt_resumo_geral.csv'}")
    return df_res if resumos else None


def main():
    ap = argparse.ArgumentParser(description="PRISM-EDU: motor IRT real (1PL/2PL).")
    ap.add_argument("--edicao", default=os.environ.get("PRISM_EDICAO", "enade_2023"),
                    help="Edicao (ex.: enade_2023, enamed_2025, licenciaturas_2025).")
    ap.add_argument("--limite-grupos", type=int, default=None,
                    help="Limita o numero de cursos processados.")
    ap.add_argument("--max-alunos", type=int, default=6000,
                    help="Maximo de alunos por curso no ajuste (default 6000).")
    ap.add_argument("--max-itens", type=int, default=60,
                    help="Maximo de itens por curso (default 60).")
    ap.add_argument("--nos", type=int, default=21,
                    help="Nos de quadratura Gauss-Hermite (default 21).")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    executar_irt_edicao(
        edicao=args.edicao, limite_grupos=args.limite_grupos,
        max_alunos=args.max_alunos, max_itens=args.max_itens,
        n_nos=args.nos, seed=args.seed,
    )


if __name__ == "__main__":
    main()
