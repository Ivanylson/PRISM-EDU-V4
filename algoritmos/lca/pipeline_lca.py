"""
Pipeline de Analise de Classes Latentes (LCA) - PRISM-EDU
Mistura de Bernoulli estimada por EM (Dempster, Laird & Rubin, 1977).

Versao com o rigor metodologico da implementacao em fases restaurado:
  - convergencia REAL do EM (nao mais fixada em True);
  - selecao de k por regra de decisao declarada a priori (BIC + entropia +
    tamanho minimo de classe), com aBIC de Sclove (1987) reportado;
  - estabilidade por bootstrap com Jaccard MAXIMO (resolve troca de rotulos)
    e intervalo de confianca de 95%;
  - analise de sensibilidade por MCA de verdade (Analise de Correspondencia
    Multipla sobre a matriz indicadora), nao PCA rotulado como MCA.

Referencias:
  - Collins & Lanza (2010), Latent Class and Latent Transition Analysis.
  - Nylund, Asparouhov & Muthen (2007), SEM 14(4), 535-569.
  - Celeux & Soromenho (1996), Journal of Classification 13, 195-212.
  - Hennig (2007), Comput. Stat. & Data Anal. 52(1), 258-271.
  - Greenacre (2017), Correspondence Analysis in Practice, CRC Press.
"""
import pandas as pd
import numpy as np
from scipy.special import logsumexp
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score
from dataclasses import dataclass
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config import (
    SEPARADOR, ENCODING, SEED_ALEATORIA, MIN_ALUNOS_POR_IES,
    K_MIN, K_MAX, N_BOOTSTRAP, ENTROPIA_MINIMA,
    CURSOS_MAP, formatar_nome_curso, caminho_saida_algoritmo,
    pasta_saida_edicao, derivar_colunas_questoes,
)


@dataclass
class ConfiguracaoLCA:
    k_min: int = K_MIN
    k_max: int = K_MAX
    n_init: int = 20
    n_bootstrap: int = N_BOOTSTRAP
    seed: int = SEED_ALEATORIA
    entropia_minima: float = ENTROPIA_MINIMA
    min_alunos_ies: int = MIN_ALUNOS_POR_IES
    min_n_classe: int = 10
    min_pct_classe: float = 0.05
    smoothing: float = 1e-3
    max_iter: int = 500
    tol: float = 1e-6


class ModeloLCA:
    """LCA de itens binarios via EM, com multiplas inicializacoes."""

    def __init__(self, config: ConfiguracaoLCA = None, k: int = None):
        self.config = config or ConfiguracaoLCA()
        self.k = k if k is not None else self.config.k_min
        self.probs = None          # (k, J) prob. de acerto por item/classe
        self.pesos = None          # (k,) proporcoes de mistura
        self.log_likelihood = None
        self.n_params = None
        self.convergiu = False     # <- agora reflete o EM de verdade
        self.n_iter = 0

    # ---- nucleo EM ----
    def _log_conjunta(self, X, pesos, probs):
        """log P(y_i, classe k) para cada (i, k)."""
        log_p = np.log(np.clip(probs, 1e-12, 1 - 1e-12))
        log_1mp = np.log(np.clip(1 - probs, 1e-12, 1 - 1e-12))
        return X @ log_p.T + (1 - X) @ log_1mp.T + np.log(np.clip(pesos, 1e-12, 1))

    def _ajustar_uma_vez(self, X, rng):
        n, J = X.shape
        pesos = np.full(self.k, 1 / self.k)
        media = X.mean(axis=0)
        probs = np.clip(media + rng.normal(0, 0.15, size=(self.k, J)), 0.05, 0.95)

        ll_ant = -np.inf
        convergiu = False
        it = 0
        for it in range(self.config.max_iter):
            log_conj = self._log_conjunta(X, pesos, probs)
            ll = logsumexp(log_conj, axis=1).sum()
            if abs(ll - ll_ant) < self.config.tol:
                convergiu = True
                break
            ll_ant = ll
            # E-step
            post = np.exp(log_conj - logsumexp(log_conj, axis=1, keepdims=True))
            # M-step com suavizacao leve
            n_k = post.sum(axis=0)
            pesos = n_k / n
            probs = (post.T @ X + self.config.smoothing) / (n_k[:, None] + 2 * self.config.smoothing)
        return ll, pesos, probs, convergiu, it + 1

    def ajustar(self, X):
        rng = np.random.default_rng(self.config.seed)
        melhor = None
        melhor_ll = -np.inf
        for _ in range(self.config.n_init):
            ll, pesos, probs, conv, n_iter = self._ajustar_uma_vez(X, rng)
            if ll > melhor_ll:
                melhor_ll = ll
                melhor = (pesos, probs, conv, n_iter)
        self.pesos, self.probs, self.convergiu, self.n_iter = melhor
        self.log_likelihood = melhor_ll
        self.n_params = (self.k - 1) + self.k * X.shape[1]
        return self

    # ---- inferencia ----
    def posterior(self, X):
        log_conj = self._log_conjunta(X, self.pesos, self.probs)
        return np.exp(log_conj - logsumexp(log_conj, axis=1, keepdims=True))

    def prever(self, X):
        return self.posterior(X)

    def rotulos(self, X):
        return self.posterior(X).argmax(axis=1)

    # ---- criterios ----
    def calcular_bic(self, X):
        n = len(X)
        return -2 * self.log_likelihood + self.n_params * np.log(n)

    def calcular_aic(self, X):
        return -2 * self.log_likelihood + 2 * self.n_params

    def calcular_abic(self, X):
        """BIC ajustado ao tamanho da amostra (Sclove, 1987)."""
        n = len(X)
        return -2 * self.log_likelihood + self.n_params * np.log((n + 2) / 24)

    def entropia_normalizada(self, X):
        post = np.clip(self.posterior(X), 1e-12, 1)
        n = len(X)
        H = -np.sum(post * np.log(post))
        H_max = n * np.log(self.k)
        return 1 - H / H_max if H_max > 0 else 0.0


def _coluna_curso(df):
    """Coluna que identifica o curso/area do ENADE para agrupar e nomear.

    Usa ``CO_GRUPO`` (chave de ``CURSOS_MAP`` e codigo da area de prova) quando
    disponivel. ``CO_CURSO`` e o codigo do curso na IES e nao mapeia para um
    nome em ``CURSOS_MAP``, por isso so e usado como fallback.
    """
    return "CO_GRUPO" if "CO_GRUPO" in df.columns else "CO_CURSO"


def filtrar_ies_validas(df, colunas_questoes, min_ies=MIN_ALUNOS_POR_IES):
    col_curso = _coluna_curso(df)
    contagem = df.groupby(["CO_IES", col_curso]).size().reset_index(name="n")
    ies_validas = contagem[contagem["n"] >= min_ies][["CO_IES", col_curso]]
    return df.merge(ies_validas, on=["CO_IES", col_curso], how="inner")


def codificar_respostas(df, colunas_questoes):
    """1 = acerto; 0 = erro/branco/anulada (mesma convencao do INEP na nota)."""
    df_resp = df[colunas_questoes].copy()
    for col in colunas_questoes:
        df_resp[col] = (df_resp[col].astype(str) == "1").astype(int)
    return df_resp.values.astype(int)


def _remover_itens_constantes(X):
    """Remove itens sem variancia (ex.: posicoes de padding '*'->0).
    Constantes nao informam classes e inflam o numero de parametros no BIC."""
    variam = X.std(axis=0) > 0
    return X[:, variam], variam


def estimar_k(X, config):
    """Ajusta k = k_min..k_max e escolhe por regra declarada A PRIORI.

    1. mantem modelos cuja menor classe >= max(min_n_classe/n, min_pct_classe);
    2. entre esses, mantem os com entropia >= entropia_minima;
    3. escolhe o de menor BIC entre os sobreviventes;
    4. se nenhum atinge a entropia, cai para o menor BIC do passo 1, com ressalva.
    """
    n = len(X)
    resultados = []
    for k in range(config.k_min, config.k_max + 1):
        modelo = ModeloLCA(config, k=k).ajustar(X)
        rotulos = modelo.rotulos(X)
        pcts = np.bincount(rotulos, minlength=k) / n
        resultados.append({
            "k": k,
            "modelo": modelo,
            "bic": modelo.calcular_bic(X),
            "aic": modelo.calcular_aic(X),
            "abic": modelo.calcular_abic(X),
            "entropia": modelo.entropia_normalizada(X),
            "menor_classe_pct": float(pcts.min()),
            "convergiu": modelo.convergiu,
        })

    minimo_pct = max(config.min_n_classe / n, config.min_pct_classe)
    candidatos = [r for r in resultados if r["menor_classe_pct"] >= minimo_pct]
    if not candidatos:
        r = min(resultados, key=lambda x: x["k"])
        return r["k"], r["modelo"], resultados, "FALLBACK: nenhum modelo com classes nao-espurias"

    com_entropia = [r for r in candidatos if r["entropia"] >= config.entropia_minima]
    if com_entropia:
        escolhido = min(com_entropia, key=lambda r: r["bic"])
        just = (f"Menor BIC ({escolhido['bic']:.1f}) entre modelos com entropia "
                f">= {config.entropia_minima} e classes nao-espurias")
    else:
        escolhido = min(candidatos, key=lambda r: r["bic"])
        just = (f"RESSALVA: nenhum modelo atingiu entropia >= {config.entropia_minima}; "
                f"escolhido por menor BIC ({escolhido['bic']:.1f}). "
                f"Entropia obtida: {escolhido['entropia']:.3f}")
    return escolhido["k"], escolhido["modelo"], resultados, just


def _jaccard_max(labels_a, labels_b, k):
    """Media do Jaccard maximo entre classes de A e de B (resolve label switching)."""
    jaccards = []
    for a in range(k):
        sa = labels_a == a
        if not sa.any():
            continue
        melhor = 0.0
        for b in range(k):
            sb = labels_b == b
            uniao = (sa | sb).sum()
            if uniao > 0:
                j = (sa & sb).sum() / uniao
                if j > melhor:
                    melhor = j
        jaccards.append(melhor)
    return float(np.mean(jaccards)) if jaccards else 0.0


def estabilidade_bootstrap(X, modelo_base, config):
    """Estabilidade por bootstrap nao-parametrico (Hennig, 2007).
    Retorna dict com media e IC 95% do Jaccard maximo.
      > 0.85 altamente estavel | 0.75-0.85 estavel |
      0.60-0.75 moderada | < 0.60 instavel (nao interpretar)."""
    rng = np.random.default_rng(config.seed)
    n = len(X)
    k = modelo_base.k
    labels_ref = modelo_base.rotulos(X)

    jaccards = []
    for b in range(config.n_bootstrap):
        idx = rng.integers(0, n, size=n)
        try:
            cfg_b = ConfiguracaoLCA(seed=config.seed + b + 1, n_init=5,
                                    smoothing=config.smoothing, max_iter=config.max_iter,
                                    tol=config.tol)
            mod_b = ModeloLCA(cfg_b, k=k).ajustar(X[idx])
            labels_b = mod_b.rotulos(X)
            jaccards.append(_jaccard_max(labels_ref, labels_b, k))
        except Exception:
            continue

    if not jaccards:
        return {"jaccard_medio": 0.0, "ic_inf": 0.0, "ic_sup": 0.0, "n_validas": 0}
    arr = np.array(jaccards)
    return {
        "jaccard_medio": float(arr.mean()),
        "ic_inf": float(np.percentile(arr, 2.5)),
        "ic_sup": float(np.percentile(arr, 97.5)),
        "n_validas": len(jaccards),
    }


def coordenadas_mca(X, var_alvo=0.70, n_comp_max=10):
    """Analise de Correspondencia Multipla (MCA) sobre a matriz indicadora.

    Para itens binarios, cada item vira duas colunas indicadoras [1-x, x] e
    aplica-se Analise de Correspondencia (metrica qui-quadrado ponderada pelas
    massas marginais) - diferente de PCA, que padroniza por z-score.
    Retorna as coordenadas principais das linhas (alunos).
    """
    n, J = X.shape
    Z = np.empty((n, 2 * J), dtype=float)
    Z[:, 0::2] = 1 - X
    Z[:, 1::2] = X
    total = Z.sum()
    if total <= 0:
        return np.zeros((n, 1))
    P = Z / total
    r = P.sum(axis=1)                       # massas de linha (uniformes = 1/n)
    c = P.sum(axis=0)                        # massas de coluna
    manter = c > 0                           # descarta categorias vazias
    P = P[:, manter]
    c = c[manter]
    r_isqrt = 1.0 / np.sqrt(np.clip(r, 1e-12, None))
    c_isqrt = 1.0 / np.sqrt(np.clip(c, 1e-12, None))
    # residuos padronizados de correspondencia (dimensao trivial ja removida)
    S = (P - np.outer(r, c)) * r_isqrt[:, None] * c_isqrt[None, :]
    U, sigma, _ = np.linalg.svd(S, full_matrices=False)
    inercia = sigma ** 2
    if inercia.sum() <= 0:
        return np.zeros((n, 1))
    var_acum = np.cumsum(inercia / inercia.sum())
    n_comp = max(2, int(np.searchsorted(var_acum, var_alvo) + 1))
    n_comp = min(n_comp, len(sigma), n_comp_max)
    return r_isqrt[:, None] * U[:, :n_comp] * sigma[:n_comp]


def kmeans_sobre_mca(X, k, seed=SEED_ALEATORIA):
    """Sensibilidade: K-Means sobre as coordenadas de MCA (Greenacre, 2017)."""
    coords = coordenadas_mca(X)
    km = KMeans(n_clusters=k, random_state=seed, n_init=10)
    return km.fit_predict(coords)


def caracterizar_classes(X, labels, k):
    media_global = X.mean(axis=0)
    carac = []
    for c in range(k):
        mask = labels == c
        n_c = int(mask.sum())
        if n_c == 0:
            continue
        media_c = X[mask].mean(axis=0)
        gap = media_c - media_global
        fortes = [f"Q{j+1}({gap[j]:+.2f})" for j in np.argsort(-gap)[:5] if gap[j] > 0.10]
        fracos = [f"Q{j+1}({gap[j]:+.2f})" for j in np.argsort(gap)[:5] if gap[j] < -0.10]
        linha = {
            "classe_id": c + 1,
            "n_alunos": n_c,
            "pct_alunos": round(n_c / len(X) * 100, 1),
            "taxa_acerto_media": round(float(media_c.mean()), 4),
            "taxa_acerto_media_ies": round(float(media_global.mean()), 4),
            "itens_diferencialmente_fortes": " | ".join(fortes),
            "itens_diferencialmente_fracos": " | ".join(fracos),
        }
        for j in range(X.shape[1]):
            linha[f"PROB_Q{j+1}"] = round(float(media_c[j]), 4)
        for j in range(X.shape[1]):
            linha[f"GAP_Q{j+1}"] = round(float(gap[j]), 4)
        carac.append(linha)
    return pd.DataFrame(carac)


def executar_pipeline_ies(df_ies, colunas_questoes, config, curso_nome, ies_codigo):
    X_full = codificar_respostas(df_ies, colunas_questoes)
    if len(X_full) < config.min_alunos_ies:
        return None

    # itens constantes (padding) sao removidos antes do ajuste
    X, _ = _remover_itens_constantes(X_full)
    if X.shape[1] < 2:
        return None

    t0 = time.time()
    k, modelo, criterios, justificativa = estimar_k(X, config)
    labels = modelo.rotulos(X)
    entropia = modelo.entropia_normalizada(X)
    estab = estabilidade_bootstrap(X, modelo, config)

    labels_km = kmeans_sobre_mca(X, k, config.seed)
    ari = adjusted_rand_score(labels, labels_km)

    caracterizacao = caracterizar_classes(X_full, labels, k)

    resultado = {
        "curso": curso_nome,
        "ies": str(ies_codigo),
        "k_escolhido": k,
        "n_alunos": len(X),
        "n_itens_uteis": int(X.shape[1]),
        "entropia_normalizada": round(entropia, 4),
        "jaccard_medio_bootstrap": round(estab["jaccard_medio"], 4),
        "jaccard_ic_inf": round(estab["ic_inf"], 4),
        "jaccard_ic_sup": round(estab["ic_sup"], 4),
        "ari_lca_vs_kmeans_mca": round(float(ari), 4),
        "log_lik": round(modelo.log_likelihood, 2),
        "convergiu": bool(modelo.convergiu),
        "n_iter": modelo.n_iter,
        "justificativa_k": justificativa,
    }
    df_criterios = pd.DataFrame([
        {"k": r["k"], "bic": round(r["bic"], 2), "aic": round(r["aic"], 2),
         "abic": round(r["abic"], 2), "entropia": round(r["entropia"], 4),
         "menor_classe_pct": round(r["menor_classe_pct"], 4), "convergiu": r["convergiu"]}
        for r in criterios
    ])
    return {"resultado": resultado, "caracterizacao": caracterizacao,
            "criterios": df_criterios, "elapsed": time.time() - t0}


def executar_pipeline_completo(caminho_csv=None, df=None):
    print("=" * 60)
    print("  PRISM-EDU: Pipeline LCA (Classes Latentes)")
    print("=" * 60)

    if df is None:
        if caminho_csv is None:
            caminho_csv = Path(sys.argv[1]) if len(sys.argv) > 1 else None
        if caminho_csv is not None and Path(caminho_csv).exists():
            print(f"  Carregando: {caminho_csv}")
            df = pd.read_csv(caminho_csv, sep=SEPARADOR, encoding=ENCODING, low_memory=False)
        else:
            print("  Processando TODAS as edicoes (memoria leve, uma por vez)...")
            from config import iterar_edicoes_dados
            for edicao, df_ed in iterar_edicoes_dados():
                print(f"\n  --- EDICAO: {edicao.upper()} ---")
                executar_pipeline_completo(df=df_ed)
            print("\n  Pipeline LCA concluido em todas as edicoes.")
            return
        if df is None or df.empty:
            print("  ERRO: dados nao encontrados. Rode o pre-processamento primeiro.")
            return
    print(f"  Registros: {len(df)}")

    colunas_q = derivar_colunas_questoes(df)
    if not colunas_q:
        print("  ERRO: nenhuma coluna de questoes encontrada.")
        return

    config = ConfiguracaoLCA()
    col_curso = _coluna_curso(df)
    df_valido = filtrar_ies_validas(df, colunas_q, config.min_alunos_ies)
    grupos = df_valido.groupby(["CO_IES", col_curso])
    total = len(grupos)
    print(f"  Processando {total} combinacoes IES/Curso...")

    todos, todas_carac, todos_crit = [], [], []
    for idx, ((ies, curso), df_g) in enumerate(grupos):
        nome = CURSOS_MAP.get(int(curso), f"Curso_{curso}")
        colunas_q_curso = derivar_colunas_questoes(df_g)
        if not colunas_q_curso:
            print(f"    [{idx+1}/{total}] {nome} / IES {ies}... pulado (sem questoes)")
            continue
        print(f"    [{idx+1}/{total}] {nome} / IES {ies}...", end=" ")
        res = executar_pipeline_ies(df_g, colunas_q_curso, config, nome, ies)
        if res is None:
            print("pulado (poucos alunos)")
            continue
        todos.append(res["resultado"])
        todas_carac.append(res["caracterizacao"].assign(curso=nome, ies=str(ies)))
        todos_crit.append(res["criterios"].assign(curso=nome, ies=str(ies)))
        marca = "ok" if res["resultado"]["convergiu"] else "SEM CONVERGENCIA"
        print(f"k={res['resultado']['k_escolhido']} [{marca}] ({res['elapsed']:.1f}s)")

    if not todos:
        print("\n  Nenhum resultado gerado.")
        return

    pasta = pasta_saida_edicao("lca")
    pasta.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(todos).to_csv(pasta / "01_relatorio_geral_por_ies.csv",
                               index=False, sep=SEPARADOR, encoding=ENCODING)
    pd.concat(todas_carac, ignore_index=True).to_csv(pasta / "02_caracterizacao_das_classes.csv",
                                                     index=False, sep=SEPARADOR, encoding=ENCODING)
    pd.concat(todos_crit, ignore_index=True).to_csv(pasta / "03_criterios_de_selecao_k.csv",
                                                    index=False, sep=SEPARADOR, encoding=ENCODING)
    print(f"\n  RESULTADOS em: {pasta}")


if __name__ == "__main__":
    executar_pipeline_completo()
