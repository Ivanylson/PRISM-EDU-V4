# -*- coding: utf-8 -*-
"""
Módulo compartilhado: estimação do DINA (CDM restrito) por EM.

Usado por:
  - fase6_lca_para_cdm_restrito.py (matriz-Q do INEP, pipeline exploratório)
  - fase6_consumir_matriz_q_validada.py (matriz-Q VALIDADA pelo especialista)

DINA — Deterministic Inputs, Noisy "And" (de la Torre, 2009).
Parâmetros por item: guess g, slip s. Prevalência de domínio por atributo: pi.
Perfil latente por aluno: probabilidade de domínio de cada atributo (alpha).
"""
import numpy as np
from itertools import product

MAX_ITER_EM = 100
TOL_EM = 1e-4
TAM_LOTE = 4000


def estimar_dina(X, Q):
    """DINA por EM (prior independente por atributo). X: (N,J) binário; Q: (J,K) binário.

    Retorna (g, s, pi, perfis_mastery, p_eta1, ll_total):
      g, s        -> (J,) guess e slip por item (restritos a [1e-4, 0.5])
      pi          -> (K,) prevalência de domínio por atributo
      perfis_mastery -> (N,K) probabilidade posterior de domínio por aluno
      p_eta1      -> (J,) proporção que domina todos os atributos exigidos pelo item
      ll_total    -> log-verossimilhança no melhor ponto do EM
    """
    N, J = X.shape
    K = Q.shape[1]

    padroes = np.array(list(product([0, 1], repeat=K)), dtype=np.int8)  # (P,K)
    P = padroes.shape[0]
    padroes_float = padroes.astype(np.float64)

    eta = (padroes_float[:, None, :] >= Q[None, :, :].astype(np.float64)).prod(axis=2)  # (P,J)
    nao_eta = 1.0 - eta

    g = np.full(J, 0.2, dtype=np.float64)
    s = np.full(J, 0.2, dtype=np.float64)
    pi = np.full(K, 0.5, dtype=np.float64)

    X = X.astype(np.float64)
    X_batches = np.array_split(X, max(1, int(np.ceil(N / TAM_LOTE))))

    ll_anterior = -np.inf
    melhor_ll = -np.inf
    melhor_params = (g.copy(), s.copy(), pi.copy())

    for it in range(MAX_ITER_EM):
        logit = np.log(pi) - np.log1p(-pi)
        log_prior = padroes_float @ logit

        g_ = np.clip(g, 1e-4, 1 - 1e-4)
        s_ = np.clip(s, 1e-4, 1 - 1e-4)
        logP_mais = eta * np.log1p(-s_) + nao_eta * np.log(g_)
        logP_menos = eta * np.log(s_) + nao_eta * np.log1p(-g_)
        base = logP_menos.sum(axis=1)
        dif = logP_mais - logP_menos

        n_master_corretos = np.zeros(J, dtype=np.float64)
        n_master_total = np.zeros(J, dtype=np.float64)
        n_nao_master_corretos = np.zeros(J, dtype=np.float64)
        n_nao_master_total = np.zeros(J, dtype=np.float64)
        mastery_acum = np.zeros(K, dtype=np.float64)
        ll_total = 0.0

        for Xb in X_batches:
            B = Xb.shape[0]
            loglik = base[:, None] + dif @ Xb.T
            log_post = log_prior[:, None] + loglik
            mx = log_post.max(axis=0)
            post = np.exp(log_post - mx[None, :])
            post = post / post.sum(axis=0, keepdims=True)

            ll_total += np.log(np.exp(log_prior[:, None] + loglik - mx[None, :]).sum(axis=0)).sum() + mx.sum()

            soma_post_p = post.sum(axis=1)
            M = post @ Xb
            n_master_corretos += (eta * M).sum(axis=0)
            n_nao_master_corretos += (nao_eta * M).sum(axis=0)
            n_master_total += (eta * soma_post_p[:, None]).sum(axis=0)
            n_nao_master_total += (nao_eta * soma_post_p[:, None]).sum(axis=0)
            mastery_acum += (padroes_float.T @ post).sum(axis=1)

        n_master_total = n_master_total + 5.0
        n_nao_master_total = n_nao_master_total + 5.0
        n_master_corretos = n_master_corretos + 2.5
        n_nao_master_corretos = n_nao_master_corretos + 2.5
        s_novo = (n_master_total - n_master_corretos) / np.maximum(n_master_total, 1e-9)
        g_novo = n_nao_master_corretos / np.maximum(n_nao_master_total, 1e-9)
        pi_novo = mastery_acum / N

        s = np.clip(s_novo, 1e-4, 0.5).astype(np.float64)
        g = np.clip(g_novo, 1e-4, 0.5).astype(np.float64)
        pi = np.clip(pi_novo, 1e-4, 1 - 1e-4).astype(np.float64)

        mudanca = 0.0
        if it > 0:
            mudanca = max(float(np.abs(s - s_ant).max()), float(np.abs(g - g_ant).max()))
        s_ant = s.copy()
        g_ant = g.copy()

        if it == 0:
            ll_anterior = ll_total
        melhoria = (ll_total - ll_anterior) / max(abs(ll_anterior), 1.0)
        ll_anterior = ll_total
        if ll_total > melhor_ll:
            melhor_ll = ll_total
            melhor_params = (g.copy(), s.copy(), pi.copy())
        elif ll_total < melhor_ll - 1e-3 * max(abs(melhor_ll), 1.0):
            break
        if it > 0 and (mudanca < TOL_EM or (melhoria < 1e-6 and melhoria > 0)):
            break

    g, s, pi = melhor_params
    ll_total = melhor_ll

    perfis_mastery = np.zeros((N, K), dtype=np.float64)
    logit = np.log(pi) - np.log1p(-pi)
    log_prior = padroes_float @ logit
    g_, s_ = np.clip(g, 1e-4, 1 - 1e-4), np.clip(s, 1e-4, 1 - 1e-4)
    logP_mais = eta * np.log1p(-s_) + nao_eta * np.log(g_)
    logP_menos = eta * np.log(s_) + nao_eta * np.log1p(-g_)
    base = logP_menos.sum(axis=1)
    dif = logP_mais - logP_menos
    inicio = 0
    for Xb in X_batches:
        B = Xb.shape[0]
        loglik = base[:, None] + dif @ Xb.T
        log_post = log_prior[:, None] + loglik
        mx = log_post.max(axis=0)
        post = np.exp(log_post - mx[None, :])
        post = post / post.sum(axis=0, keepdims=True)
        perfis_mastery[inicio:inicio + B, :] = (padroes_float.T @ post).T
        inicio += B

    logit = np.log(pi) - np.log1p(-pi)
    log_prior = padroes_float @ logit
    p_eta1 = np.zeros(J)
    for Xb in X_batches:
        B = Xb.shape[0]
        loglik = base[:, None] + dif @ Xb.T
        log_post = log_prior[:, None] + loglik
        mx = log_post.max(axis=0)
        post = np.exp(log_post - mx[None, :])
        post = post / post.sum(axis=0, keepdims=True)
        soma_post_p = post.sum(axis=1)
        p_eta1 += (eta * soma_post_p[:, None]).sum(axis=0)
    p_eta1 /= N

    return g, s, pi, perfis_mastery, p_eta1, ll_total
