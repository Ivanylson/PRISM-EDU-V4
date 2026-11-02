"""
Self-Organizing Maps (SOM) para visualizacao de perfis de aprendizagem.
Mapeia respostas dos alunos em uma grade 2D preservando topologia.
"""
import numpy as np
import pandas as pd
from pathlib import Path
import sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config import SEPARADOR, ENCODING, SEED_ALEATORIA, CURSOS_MAP, formatar_nome_curso, caminho_saida_algoritmo, pasta_saida_edicao, derivar_colunas_questoes, normalizar_coluna_grupo


class SOM:
    def __init__(self, grid_x=10, grid_y=10, n_iter=200, learning_rate=0.5, sigma=None, seed=SEED_ALEATORIA):
        self.grid_x = grid_x
        self.grid_y = grid_y
        self.n_iter = n_iter
        self.lr0 = learning_rate
        self.sigma0 = sigma if sigma else max(grid_x, grid_y) / 2
        self.seed = seed

    def _inicializar_pesos(self, X):
        rng = np.random.RandomState(self.seed)
        n_features = X.shape[1]
        pesos = rng.randn(self.grid_x, self.grid_y, n_features) * 0.1
        for i in range(self.grid_x):
            for j in range(self.grid_y):
                pesos[i, j] = X[rng.randint(len(X))]
        return pesos

    def _coordenadas_grid(self):
        coords = np.zeros((self.grid_x, self.grid_y, 2))
        for i in range(self.grid_x):
            for j in range(self.grid_y):
                coords[i, j] = [i, j]
        return coords

    def ajustar(self, X):
        pesos = self._inicializar_pesos(X)
        coords = self._coordenadas_grid()
        rng = np.random.RandomState(self.seed)

        for t in range(self.n_iter):
            lr = self.lr0 * (1 - t / self.n_iter)
            sigma = self.sigma0 * (1 - t / self.n_iter)

            idx = rng.randint(len(X))
            x = X[idx]

            distancias = np.zeros((self.grid_x, self.grid_y))
            for i in range(self.grid_x):
                for j in range(self.grid_y):
                    distancias[i, j] = np.linalg.norm(x - pesos[i, j])

            bmu = np.unravel_index(np.argmin(distancias), distancias.shape)

            for i in range(self.grid_x):
                for j in range(self.grid_y):
                    d_grid = np.linalg.norm(np.array([i, j]) - np.array(bmu))
                    h = np.exp(-d_grid**2 / (2 * sigma**2 + 1e-10))
                    pesos[i, j] += lr * h * (x - pesos[i, j])

        self.pesos = pesos
        return self

    def mapear(self, X):
        saida = np.zeros((len(X), 2), dtype=int)
        for idx, x in enumerate(X):
            distancias = np.zeros((self.grid_x, self.grid_y))
            for i in range(self.grid_x):
                for j in range(self.grid_y):
                    distancias[i, j] = np.linalg.norm(x - self.pesos[i, j])
            saida[idx] = np.unravel_index(np.argmin(distancias), distancias.shape)
        return saida

    def calcular_umatrix(self):
        umatrix = np.zeros((self.grid_x, self.grid_y))
        for i in range(self.grid_x):
            for j in range(self.grid_y):
                vizinhos = []
                for di in [-1, 0, 1]:
                    for dj in [-1, 0, 1]:
                        if di == 0 and dj == 0:
                            continue
                        ni, nj = i + di, j + dj
                        if 0 <= ni < self.grid_x and 0 <= nj < self.grid_y:
                            vizinhos.append(np.linalg.norm(self.pesos[i, j] - self.pesos[ni, nj]))
                umatrix[i, j] = np.mean(vizinhos) if vizinhos else 0
        return umatrix


def executar_som(caminho_csv=None, df=None):
    print("=" * 60)
    print("  PRISM-EDU: SOM (Self-Organizing Maps)")
    print("=" * 60)

    if df is None:
        if caminho_csv is None:
            print("  Processando TODAS as edicoes (memoria leve, uma por vez)...")
            from config import iterar_edicoes_dados
            for edicao, df_ed in iterar_edicoes_dados():
                print(f"\n  --- EDICAO: {edicao.upper()} ---")
                executar_som(df=df_ed)
            print("\n  Motor SOM concluido em todas as edicoes.")
            return
        else:
            df = pd.read_csv(caminho_csv, sep=SEPARADOR, encoding=ENCODING, low_memory=False)
        if df is None or df.empty:
            print(f"  ERRO: Dados nao encontrados.")
            return
    colunas_questoes = derivar_colunas_questoes(df)
    colunas_existentes = [c for c in colunas_questoes if c in df.columns]

    pasta_saida = pasta_saida_edicao("psicometria")
    pasta_saida.mkdir(parents=True, exist_ok=True)

    df = normalizar_coluna_grupo(df)

    import os as _os
    limite_amb = _os.environ.get("PRISM_LIMITE_GRUPOS")
    limite_grupos = int(limite_amb) if limite_amb else None

    for idx, (co_grupo, df_grupo) in enumerate(df.groupby("CO_GRUPO")):
        if limite_grupos and idx >= limite_grupos:
            break
        nome_curso = CURSOS_MAP.get(int(co_grupo), f"Curso_{int(co_grupo)}")
        if len(df_grupo) < 100:
            continue
        colunas_existentes = derivar_colunas_questoes(df_grupo)
        if not colunas_existentes:
            continue

        print(f"\n  {nome_curso} ({len(df_grupo)} alunos)...")

        n_amostra = min(len(df_grupo), 2000)
        df_amostra = df_grupo.sample(n_amostra, random_state=SEED_ALEATORIA)
        X = df_amostra[colunas_existentes].apply(pd.to_numeric, errors="coerce").fillna(0).values.astype(float)

        som = SOM(grid_x=8, grid_y=8, n_iter=100, learning_rate=0.5)
        som.ajustar(X)
        mapeamento = som.mapear(X)
        umatrix = som.calcular_umatrix()

        fig, axes = plt.subplots(1, 2, figsize=(14, 6))

        im1 = axes[0].imshow(umatrix.T, cmap="YlOrRd", origin="lower")
        axes[0].set_title(f"U-Matrix - {nome_curso}")
        axes[0].set_xlabel("X")
        axes[0].set_ylabel("Y")
        plt.colorbar(im1, ax=axes[0])

        contagem = np.zeros((som.grid_x, som.grid_y))
        for x, y in mapeamento:
            contagem[x, y] += 1
        im2 = axes[1].imshow(contagem.T, cmap="Blues", origin="lower")
        axes[1].set_title(f"Mapa de Distribuicao - {nome_curso}")
        axes[1].set_xlabel("X")
        axes[1].set_ylabel("Y")
        plt.colorbar(im2, ax=axes[1])

        plt.tight_layout()
        caminho_img = pasta_saida / f"som_{formatar_nome_curso(nome_curso)}.png"
        plt.savefig(caminho_img, dpi=200, bbox_inches="tight")
        plt.close()
        print(f"    SOM salvo: {caminho_img.name}")

    print(f"\n  SOM finalizado!")


if __name__ == "__main__":
    executar_som()
