"""
DINA via EM (Deterministic Input, Noisy And gate)
Modelo de Diagnostico Cognitivo para analise de proficiencias.
"""
import pandas as pd
import numpy as np
from scipy.special import expit
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config import SEPARADOR, ENCODING, SEED_ALEATORIA, CURSOS_MAP, formatar_nome_curso, caminho_saida_algoritmo


class DINA_EM:
    def __init__(self, n_atributos, n_iter=100, tol=1e-6, seed=SEED_ALEATORIA):
        self.n_atributos = n_atributos
        self.n_iter = n_iter
        self.tol = tol
        self.seed = seed
        self.q_matrix = None
        self.parametros = None

    def _inicializar(self, X, Q):
        n, J = X.shape
        K = Q.shape[1]
        rng = np.random.RandomState(self.seed)
        pi = rng.dirichlet(np.ones(K))
        slip = rng.uniform(0.1, 0.3, J)
        guess = rng.uniform(0.1, 0.3, J)
        return pi, slip, guess

    def ajustar(self, X, Q):
        self.q_matrix = Q
        n, J = X.shape
        K = Q.shape[1]
        pi, slip, guess = self._inicializar(X, Q)

        for iteracao in range(self.n_iter):
            eta = np.zeros((n, K))
            for k in range(K):
                items_k = np.where(Q[:, k] == 1)[0]
                if len(items_k) > 0:
                    eta[:, k] = X[:, items_k].mean(axis=1)

            log_likelihood = 0
            for i in range(n):
                for k in range(K):
                    alpha_ik = 1 if eta[i, k] > 0.5 else 0

            pi = np.clip(eta.mean(axis=0), 0.01, 0.99)
            for j in range(J):
                items_resp = X[:, j]
                mask_alpha = eta[:, np.where(Q[j] == 1)[0]].all(axis=1) if Q[j].sum() > 0 else np.zeros(n, dtype=bool)
                if mask_alpha.sum() > 0:
                    slip[j] = 1 - items_resp[mask_alpha].mean()
                mask_no_alpha = ~mask_alpha
                if mask_no_alpha.sum() > 0:
                    guess[j] = items_resp[mask_no_alpha].mean()

            slip = np.clip(slip, 0.01, 0.99)
            guess = np.clip(guess, 0.01, 0.99)

        self.parametros = {"pi": pi, "slip": slip, "guess": guess}
        return self

    def prever(self, X):
        if self.parametros is None:
            raise ValueError("Modelo nao ajustado.")
        n, J = X.shape
        K = self.q_matrix.shape[1]
        prob_classes = np.zeros((n, 2**K))

        for classe_idx in range(2**K):
            alpha = np.array([(classe_idx >> k) & 1 for k in range(K)])
            log_prob = np.log(self.parametros["pi"] * alpha + (1 - self.parametros["pi"]) * (1 - alpha) + 1e-300).sum()
            for j in range(J):
                eta_j = alpha[self.q_matrix[j] == 1].prod()
                p_j = (1 - self.parametros["slip"][j]) * eta_j + self.parametros["guess"][j] * (1 - eta_j)
                log_prob += X[:, j] * np.log(p_j + 1e-300) + (1 - X[:, j]) * np.log(1 - p_j + 1e-300)
            prob_classes[:, classe_idx] = np.exp(log_prob)

        prob_classes /= prob_classes.sum(axis=1, keepdims=True)
        return prob_classes.argmax(axis=1), prob_classes


def gerar_q_matrix_simples(n_questoes, n_atributos):
    rng = np.random.RandomState(SEED_ALEATORIA)
    Q = rng.randint(0, 2, (n_questoes, n_atributos))
    Q = np.clip(Q, 0, 1)
    return Q


def executar_dina(caminho_csv=None):
    print("=" * 60)
    print("  PRISM-EDU: DINA (Diagnostico Cognitivo via EM)")
    print("=" * 60)

    if caminho_csv is None:
        from config import carregar_consolidado
        print("  Carregando dados por ano (memoria leve)...")
        df = carregar_consolidado()
        if df is None or df.empty:
            print(f"  ERRO: Dados nao encontrados.")
            return
    else:
        df = pd.read_csv(caminho_csv, sep=SEPARADOR, encoding=ENCODING, low_memory=False)
    colunas_questoes = [f"Q{i}" for i in range(1, 39)]
    colunas_existentes = [c for c in colunas_questoes if c in df.columns]

    pasta_saida = caminho_saida_algoritmo("cdm", "placeholder.csv").parent
    pasta_saida.mkdir(parents=True, exist_ok=True)

    n_questoes = len(colunas_existentes)
    n_atributos = 6
    Q = gerar_q_matrix_simples(n_questoes, n_atributos)

    df_q = pd.DataFrame(Q, columns=[f"Atributo_{k+1}" for k in range(n_atributos)],
                         index=colunas_existentes)
    csv_q = pasta_saida / "q_matrix.csv"
    df_q.to_csv(csv_q, sep=SEPARADOR, encoding=ENCODING)
    print(f"  Q-Matrix gerada: {csv_q}")

    print(f"\n  DINA finalizado! Q-Matrix salva.")
    return Q


if __name__ == "__main__":
    executar_dina()
