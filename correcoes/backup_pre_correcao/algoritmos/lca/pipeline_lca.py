"""
Pipeline de Analise de Classes Latentes (LCA) - PRISM-EDU
Implementacao completa via algoritmo EM para mistura de Bernoulli.
Adaptado do pipeline original de 706 linhas com melhorias de performance.
"""
import pandas as pd
import numpy as np
from scipy.special import logsumexp
from sklearn.metrics import silhouette_score, adjusted_rand_score
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans
from dataclasses import dataclass, field
import json
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config import (
    SEPARADOR, ENCODING, SEED_ALEATORIA, MIN_ALUNOS_POR_IES,
    K_MIN, K_MAX, N_BOOTSTRAP, ENTROPIA_MINIMA,
    CURSOS_MAP, formatar_nome_curso, caminho_saida_algoritmo,
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
    smoothing: float = 1e-3
    max_iter: int = 500
    tol: float = 1e-6


class ModeloLCA:
    def __init__(self, config: ConfiguracaoLCA = None):
        self.config = config or ConfiguracaoLCA()
        self.k = None
        self.probs = None
        self.pesos = None
        self.log_likelihood = None
        self.convergiu = False
        self.n_iter = 0

    def _inicializar(self, X, rng):
        n, J = X.shape
        pesos = rng.dirichlet(np.ones(self.k))
        probs = np.zeros((self.k, J))
        for j in range(J):
            media_j = X[:, j].mean()
            probs[:, j] = np.clip(
                rng.normal(media_j, 0.2, self.k),
                self.config.smoothing, 1 - self.config.smoothing
            )
        return pesos, probs

    def _calcular_log_verossimilhanca(self, X, pesos, probs):
        n, J = X.shape
        log_p = np.zeros((n, self.k))
        for k_idx in range(self.k):
            p_k = np.clip(probs[k_idx], 1e-10, 1 - 1e-10)
            log_item_vero = X * np.log(p_k) + (1 - X) * np.log(1 - p_k)
            log_p[:, k_idx] = np.log(pesos[k_idx] + 1e-300) + log_item_vero.sum(axis=1)
        return logsumexp(log_p, axis=1).sum()

    def ajustar(self, X):
        n, J = X.shape
        melhor_ll = -np.inf
        melhor_params = None

        for init in range(self.config.n_init):
            rng = np.random.RandomState(self.config.seed + init)
            pesos, probs = self._inicializar(X, rng)

            ll_ant = -np.inf
            for iteracao in range(self.config.max_iter):
                log_p = np.zeros((n, self.k))
                for k_idx in range(self.k):
                    p_k = np.clip(probs[k_idx], 1e-10, 1 - 1e-10)
                    log_item_vero = X * np.log(p_k) + (1 - X) * np.log(1 - p_k)
                    log_p[:, k_idx] = np.log(pesos[k_idx] + 1e-300) + log_item_vero.sum(axis=1)

                log_p_max = log_p.max(axis=1, keepdims=True)
                p_responsabilidade = np.exp(log_p - log_p_max)
                p_responsabilidade /= p_responsabilidade.sum(axis=1, keepdims=True)

                n_k = p_responsabilidade.sum(axis=0)
                pesos = n_k / n
                for k_idx in range(self.k):
                    if n_k[k_idx] > 0:
                        probs[k_idx] = (p_responsabilidade[:, k_idx:k_idx+1].T @ X) / n_k[k_idx]
                    probs[k_idx] = np.clip(probs[k_idx], self.config.smoothing, 1 - self.config.smoothing)

                ll = logsumexp(log_p, axis=1).sum()
                if abs(ll - ll_ant) < self.config.tol:
                    break
                ll_ant = ll

            if ll > melhor_ll:
                melhor_ll = ll
                melhor_params = (pesos.copy(), probs.copy())
                melhor_n_iter = iteracao + 1

        self.pesos, self.probs = melhor_params
        self.log_likelihood = melhor_ll
        self.n_iter = melhor_n_iter
        self.convergiu = True
        return self

    def prever(self, X):
        n, J = X.shape
        log_p = np.zeros((n, self.k))
        for k_idx in range(self.k):
            p_k = np.clip(self.probs[k_idx], 1e-10, 1 - 1e-10)
            log_item_vero = X * np.log(p_k) + (1 - X) * np.log(1 - p_k)
            log_p[:, k_idx] = np.log(self.pesos[k_idx] + 1e-300) + log_item_vero.sum(axis=1)
        p_resp = np.exp(log_p - log_p.max(axis=1, keepdims=True))
        p_resp /= p_resp.sum(axis=1, keepdims=True)
        return p_resp

    def entropia_normalizada(self, X):
        p_resp = self.prever(X)
        n = len(X)
        H = -np.sum(p_resp * np.log(p_resp + 1e-300))
        H_max = n * np.log(self.k)
        return 1 - H / H_max if H_max > 0 else 0

    def calcular_bic(self, X):
        n, J = X.shape
        n_params = self.k * J + (self.k - 1)
        return -2 * self.log_likelihood + n_params * np.log(n)

    def calcular_aic(self, X):
        n_params = self.k * J + (self.k - 1)
        return -2 * self.log_likelihood + 2 * n_params


def filtrar_ies_validas(df, colunas_questoes, min_ies=MIN_ALUNOS_POR_IES):
    contagem = df.groupby(["CO_IES", "CO_CURSO"]).size().reset_index(name="n")
    ies_validas = contagem[contagem["n"] >= min_ies][["CO_IES", "CO_CURSO"]]
    return df.merge(ies_validas, on=["CO_IES", "CO_CURSO"], how="inner")


def codificar_respostas(df, colunas_questoes):
    df_resp = df[colunas_questoes].copy()
    for col in colunas_questoes:
        df_resp[col] = pd.to_numeric(df_resp[col], errors="coerce").fillna(0).astype(int)
    return df_resp.values


def estimar_k(X, config):
    resultados = []
    for k in range(config.k_min, config.k_max + 1):
        modelo = ModeloLCA(ConfiguracaoLCA(k_min=k, k_max=k, n_init=config.n_init,
                                            seed=config.seed, smoothing=config.smoothing))
        modelo.k = k
        modelo.ajustar(X)
        entropia = modelo.entropia_normalizada(X)
        bic = modelo.calcular_bic(X)
        resultados.append({"k": k, "bic": bic, "entropia": entropia, "modelo": modelo})

    for r in resultados:
        classes_modelo = r["modelo"].prever(X).argmax(axis=1)
        tam_min = min(np.bincount(classes_modelo)) / len(X)
        r["menor_classe_pct"] = tam_min
        r["min_tamanho_ok"] = tam_min >= 0.05

    candidatos = [r for r in resultados if r["min_tamanho_ok"] and r["entropia"] >= config.entropia_minima]
    if not candidatos:
        candidatos = resultados
    melhor = min(candidatos, key=lambda x: x["bic"])
    return melhor["k"], melhor["modelo"], resultados


def estabilidade_bootstrap(X, modelo_base, config):
    rng = np.random.RandomState(config.seed)
    n = len(X)
    labels_base = modelo_base.prever(X).argmax(axis=1)
    jaccards = []

    for _ in range(config.n_bootstrap):
        indices = rng.choice(n, size=n, replace=True)
        X_boot = X[indices]
        modelo_boot = ModeloLCA(ConfiguracaoLCA(k_min=modelo_base.k, k_max=modelo_base.k,
                                                 n_init=5, seed=config.seed))
        modelo_boot.k = modelo_base.k
        modelo_boot.ajustar(X_boot)
        labels_boot_full = modelo_boot.prever(X).argmax(axis=1)

        for c in range(modelo_base.k):
            mask_base = labels_base == c
            mask_boot = labels_boot_full == c
            intersecao = (mask_base & mask_boot).sum()
            uniao = (mask_base | mask_boot).sum()
            if uniao > 0:
                jaccards.append(intersecao / uniao)

    return np.mean(jaccards) if jaccards else 0


def kmeans_sobre_mca(X, k, seed=SEED_ALEATORIA):
    n_components = min(X.shape[1], 10)
    pca = PCA(n_components=n_components, random_state=seed)
    X_pca = pca.fit_transform(X)
    kmeans = KMeans(n_clusters=k, random_state=seed, n_init=10)
    return kmeans.fit_predict(X_pca)


def caracterizar_classes(X, labels, probs_classes):
    n_classes = len(np.unique(labels))
    n_questoes = X.shape[1]
    carac = []

    for c in range(n_classes):
        mask = labels == c
        n_alunos = mask.sum()
        if n_alunos == 0:
            continue

        taxa_acerto = X[mask].mean(axis=0)
        taxa_acerto_global = X.mean(axis=0)
        gap = taxa_acerto - taxa_acerto_global

        itens_fortes = []
        itens_fracos = []
        for j in range(n_questoes):
            if gap[j] > 0.10:
                itens_fortes.append(f"Q{j+1}({gap[j]:+.2f})")
            elif gap[j] < -0.10:
                itens_fracos.append(f"Q{j+1}({gap[j]:+.2f})")

        carac.append({
            "classe_id": c + 1,
            "n_alunos": int(n_alunos),
            "pct_alunos": round(n_alunos / len(X) * 100, 1),
            "taxa_acerto_media": round(taxa_acerto.mean(), 4),
            "taxa_acerto_media_ies": round(taxa_acerto_global.mean(), 4),
            "itens_diferencialmente_fortes": " | ".join(itens_fortes[:5]),
            "itens_diferencialmente_fracos": " | ".join(itens_fracos[:5]),
            **{f"PROB_Q{j+1}": round(taxa_acerto[j], 4) for j in range(n_questoes)},
            **{f"GAP_Q{j+1}": round(gap[j], 4) for j in range(n_questoes)},
        })

    return pd.DataFrame(carac)


def executar_pipeline_ies(df_ies, colunas_questoes, config, curso_nome, ies_codigo):
    X = codificar_respostas(df_ies, colunas_questoes)
    if len(X) < config.min_alunos_ies:
        return None

    t0 = time.time()
    k_escolhido, modelo_final, criterios = estimar_k(X, config)

    labels = modelo_final.prever(X).argmax(axis=1)
    entropia = modelo_final.entropia_normalizada(X)
    jaccard = estabilidade_bootstrap(X, modelo_final, config)

    labels_kmeans = kmeans_sobre_mca(X, k_escolhido, config.seed)
    ari = adjusted_rand_score(labels, labels_kmeans)

    caracterizacao = caracterizar_classes(X, labels, modelo_final.probs)

    resultado = {
        "curso": curso_nome,
        "ies": str(ies_codigo),
        "k_escolhido": k_escolhido,
        "n_alunos": len(X),
        "entropia_normalizada": round(entropia, 4),
        "jaccard_medio_bootstrap": round(jaccard, 4),
        "ari_lca_vs_kmeans_mca": round(ari, 4),
        "log_lik": round(modelo_final.log_likelihood, 2),
        "convergiu": modelo_final.convergiu,
        "n_iter": modelo_final.n_iter,
        "justificativa_k": f"k={k_escolhido} selecionado por BIC com entropia={entropia:.3f} >= {config.entropia_minima}",
    }

    df_criterios = pd.DataFrame([
        {"k": r["k"], "bic": round(r["bic"], 2), "entropia": round(r["entropia"], 4),
         "menor_classe_pct": round(r["menor_classe_pct"], 4)}
        for r in criterios
    ])

    elapsed = time.time() - t0
    return {
        "resultado": resultado,
        "caracterizacao": caracterizacao,
        "criterios": df_criterios,
        "elapsed": elapsed,
    }


def executar_pipeline_completo(caminho_csv=None):
    print("=" * 60)
    print("  PRISM-EDU: Pipeline LCA (Classes Latentes)")
    print("=" * 60)

    if caminho_csv is None:
        caminho_csv = Path(sys.argv[1]) if len(sys.argv) > 1 else None

    if caminho_csv is None or not caminho_csv.exists():
        from config import carregar_consolidado
        print("  Carregando dados por ano (memoria leve)...")
        df = carregar_consolidado()
        if df is None or df.empty:
            print(f"  ERRO: Dados nao encontrados. Execute o pre-processamento primeiro.")
            return
    else:
        print(f"  Carregando: {caminho_csv}")
        df = pd.read_csv(caminho_csv, sep=SEPARADOR, encoding=ENCODING, low_memory=False)
    print(f"  Registros: {len(df)}")

    colunas_questoes = [f"Q{i}" for i in range(1, 39)]
    colunas_existentes = [c for c in colunas_questoes if c in df.columns]
    if not colunas_existentes:
        print("  ERRO: Nenhuma coluna Q1-Q38 encontrada.")
        return

    config = ConfiguracaoLCA()
    df_valido = filtrar_ies_validas(df, colunas_existentes, config.min_alunos_ies)
    print(f"  IES validas (>{config.min_alunos_ies} alunos): {df_valido[['CO_IES','CO_CURSO']].drop_duplicates().shape[0]}")

    todos_resultados = []
    todas_caracterizacoes = []
    todos_criterios = []

    import os as _os
    limite_amb = _os.environ.get("PRISM_LIMITE_GRUPOS")
    limite_grupos = int(limite_amb) if limite_amb else None

    grupos = df_valido.groupby(["CO_IES", "CO_CURSO"])
    total_grupos = len(grupos)
    if limite_grupos:
        total_grupos = min(total_grupos, limite_grupos)
    print(f"  Processando {total_grupos} combinacoes IES/Curso...")

    for idx, ((ies, curso), df_grupo) in enumerate(grupos):
        if limite_grupos and idx >= limite_grupos:
            break
        nome_curso = CURSOS_MAP.get(int(curso), f"Curso_{curso}")
        print(f"    [{idx+1}/{total_grupos}] {nome_curso} / IES {ies}...", end=" ")

        resultado = executar_pipeline_ies(df_grupo, colunas_existentes, config, nome_curso, ies)
        if resultado is None:
            print("pulado (poucos alunos)")
            continue

        todos_resultados.append(resultado["resultado"])
        todas_caracterizacoes.append(resultado["caracterizacao"].assign(curso=nome_curso, ies=str(ies)))
        todos_criterios.append(resultado["criterios"].assign(curso=nome_curso, ies=str(ies)))
        print(f"k={resultado['resultado']['k_escolhido']} ({resultado['elapsed']:.1f}s)")

    if not todos_resultados:
        print("\n  Nenhum resultado gerado.")
        return

    df_geral = pd.DataFrame(todos_resultados)
    df_classes = pd.concat(todas_caracterizacoes, ignore_index=True)
    df_crit = pd.concat(todos_criterios, ignore_index=True)

    pasta_saida = caminho_saida_algoritmo("lca", "placeholder.csv").parent
    pasta_saida.mkdir(parents=True, exist_ok=True)

    df_geral.to_csv(pasta_saida / "01_relatorio_geral_por_ies.csv", index=False, sep=SEPARADOR, encoding=ENCODING)
    df_classes.to_csv(pasta_saida / "02_caracterizacao_das_classes.csv", index=False, sep=SEPARADOR, encoding=ENCODING)
    df_crit.to_csv(pasta_saida / "03_criterios_de_selecao_k.csv", index=False, sep=SEPARADOR, encoding=ENCODING)

    print(f"\n  RESULTADOS:")
    print(f"    01_relatorio_geral_por_ies.csv ({len(df_geral)} IES)")
    print(f"    02_caracterizacao_das_classes.csv ({len(df_classes)} classes)")
    print(f"    03_criterios_de_selecao_k.csv ({len(df_crit)} avaliacoes)")
    print(f"    Pasta: {pasta_saida}")


if __name__ == "__main__":
    executar_pipeline_completo()
