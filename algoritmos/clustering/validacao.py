"""
Motor de Clustering Triplo - K-Means, GMM, Hierarquico
Validacao com silhouette, Davies-Bouldin, elbow, e geracao de prescricoes pedagogicas.
"""
import pandas as pd
import numpy as np
from sklearn.cluster import KMeans, AgglomerativeClustering
from sklearn.mixture import GaussianMixture
from sklearn.metrics import silhouette_score, davies_bouldin_score
from sklearn.decomposition import PCA
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config import (
    SEPARADOR, ENCODING, SEED_ALEATORIA, CURSOS_MAP,
    formatar_nome_curso, caminho_saida_algoritmo,
    pasta_saida_edicao, derivar_colunas_questoes, normalizar_coluna_grupo,
)


MAPA_CURRICULAR = {
    "Engenharia de Computacao": {
        "Q1": "Algoritmos", "Q2": "Estruturas de Dados", "Q3": "Calculo",
        "Q4": "Algebra Linear", "Q5": "Fisica", "Q6": "Probabilidade",
        "Q7": "Engenharia de Software", "Q8": "Sistemas Embarcados",
    },
}


def preparar_features(df, colunas_questoes):
    X = df[colunas_questoes].copy()
    for col in colunas_questoes:
        X[col] = pd.to_numeric(X[col], errors="coerce").fillna(0).astype(int)
    return X.values


def validar_clustering(X, k_range=range(2, 7), seed=SEED_ALEATORIA):
    resultados = []
    inercia_kmeans = []

    for k in k_range:
        kmeans = KMeans(n_clusters=k, random_state=seed, n_init=10)
        labels_km = kmeans.fit_predict(X)
        sil_km = silhouette_score(X, labels_km)
        db_km = davies_bouldin_score(X, labels_km)
        inercia_kmeans.append(kmeans.inertia_)

        gmm = GaussianMixture(n_components=k, random_state=seed)
        labels_gmm = gmm.fit_predict(X)
        sil_gmm = silhouette_score(X, labels_gmm)
        db_gmm = davies_bouldin_score(X, labels_gmm)

        hier = AgglomerativeClustering(n_clusters=k, linkage="ward")
        labels_hier = hier.fit_predict(X)
        sil_hier = silhouette_score(X, labels_hier)
        db_hier = davies_bouldin_score(X, labels_hier)

        resultados.append({
            "K_Grupos": k,
            "KMeans_Silhueta": round(sil_km, 4),
            "KMeans_Davies": round(db_km, 4),
            "KMeans_Inercia": round(kmeans.inertia_, 2),
            "GMM_Silhueta": round(sil_gmm, 4),
            "GMM_Davies": round(db_gmm, 4),
            "Hierarquico_Silhueta": round(sil_hier, 4),
            "Hierarquico_Davies": round(db_hier, 4),
        })

    df_resultados = pd.DataFrame(resultados)
    melhor_k_sil = df_resultados.loc[df_resultados["KMeans_Silhueta"].idxmax(), "K_Grupos"]
    melhor_k_db = df_resultados.loc[df_resultados["KMeans_Davies"].idxmin(), "K_Grupos"]

    return df_resultados, int(melhor_k_sil), int(melhor_k_db), inercia_kmeans


def graficos_validacao(df_resultados, inercia_kmeans, nome_curso, pasta_saida):
    k_range = df_resultados["K_Grupos"].values

    fig, axes = plt.subplots(1, 3, figsize=(18, 5))

    axes[0].plot(k_range, inercia_kmeans, "bo-", linewidth=2)
    axes[0].set_title("K-Means: Metodo do Cotovelo")
    axes[0].set_xlabel("K")
    axes[0].set_ylabel("Inercia")
    axes[0].grid(True, linestyle="--", alpha=0.7)

    axes[1].plot(k_range, df_resultados["KMeans_Silhueta"], "bo-", label="K-Means", linewidth=2)
    axes[1].plot(k_range, df_resultados["GMM_Silhueta"], "rs-", label="GMM", linewidth=2)
    axes[1].plot(k_range, df_resultados["Hierarquico_Silhueta"], "g^-", label="Hierarquico", linewidth=2)
    axes[1].set_title("Silhueta (maior = melhor)")
    axes[1].set_xlabel("K")
    axes[1].set_ylabel("Silhouette Score")
    axes[1].legend()
    axes[1].grid(True, linestyle="--", alpha=0.7)

    axes[2].plot(k_range, df_resultados["KMeans_Davies"], "bo-", label="K-Means", linewidth=2)
    axes[2].plot(k_range, df_resultados["GMM_Davies"], "rs-", label="GMM", linewidth=2)
    axes[2].plot(k_range, df_resultados["Hierarquico_Davies"], "g^-", label="Hierarquico", linewidth=2)
    axes[2].set_title("Davies-Bouldin (menor = melhor)")
    axes[2].set_xlabel("K")
    axes[2].set_ylabel("Davies-Bouldin")
    axes[2].legend()
    axes[2].grid(True, linestyle="--", alpha=0.7)

    plt.suptitle(f"Validacao de Clustering - {nome_curso}", fontsize=14, fontweight="bold")
    plt.tight_layout()

    caminho_img = pasta_saida / f"graficos_validacao_{formatar_nome_curso(nome_curso)}.png"
    plt.savefig(caminho_img, dpi=300, bbox_inches="tight")
    plt.close()
    return caminho_img


def agrupar_prescricao(X, labels, colunas_questoes, nome_grupo_idx):
    df_grupo = pd.DataFrame(X, columns=colunas_questoes)
    media_questao = df_grupo.mean()
    media_global = pd.DataFrame(X).mean().mean()

    gap = media_questao - media_global
    questoes_fracas = gap.nsmallest(5)
    questoes_fortes = gap.nlargest(3)

    return {
        "grupo": nome_grupo_idx,
        "n_alunos": len(X),
        "media_geral": round(df_grupo.mean().mean(), 4),
        "questoes_fracas": " | ".join([f"{q}({v:+.3f})" for q, v in questoes_fracas.items()]),
        "questoes_fortes": " | ".join([f"{q}({v:+.3f})" for q, v in questoes_fortes.items()]),
    }


def executar_clustering_curso(df_curso, colunas_questoes, nome_curso):
    X = preparar_features(df_curso, colunas_questoes)
    if len(X) < 50:
        return None

    n_amostra = min(len(X), 2500)
    idx_amostra = np.random.RandomState(SEED_ALEATORIA).choice(len(X), n_amostra, replace=False)
    X_amostra = X[idx_amostra]

    df_metricas, melhor_k, _, inercia = validar_clustering(X_amostra)
    pasta_metricas = pasta_saida_edicao("clustering")
    pasta_metricas.mkdir(parents=True, exist_ok=True)

    csv_metricas = pasta_metricas / f"metricas_agrupamento_{formatar_nome_curso(nome_curso)}.csv"
    df_metricas.to_csv(csv_metricas, index=False, sep=SEPARADOR, encoding=ENCODING)

    img = graficos_validacao(df_metricas, inercia, nome_curso, pasta_metricas)

    kmeans_final = KMeans(n_clusters=melhor_k, random_state=SEED_ALEATORIA, n_init=10)
    labels_finais = kmeans_final.fit_predict(X)

    prescricoes = []
    for g in range(melhor_k):
        mask = labels_finais == g
        presc = agrupar_prescricao(X[mask], g, colunas_questoes, g)
        prescricoes.append(presc)

    return {
        "metricas": df_metricas,
        "melhor_k": melhor_k,
        "prescricoes": pd.DataFrame(prescricoes),
        "grafico": img,
    }


def executar_pipeline(caminho_csv=None, df=None):
    print("=" * 60)
    print("  PRISM-EDU: Motor de Clustering (K-Means + GMM + Hierarquico)")
    print("=" * 60)

    if df is None:
        if caminho_csv is not None:
            print(f"  Carregando: {caminho_csv}")
            df = pd.read_csv(caminho_csv, sep=SEPARADOR, encoding=ENCODING, low_memory=False)
        else:
            print("  Processando TODAS as edicoes (memoria leve, uma por vez)...")
            from config import iterar_edicoes_dados
            for edicao, df_ed in iterar_edicoes_dados():
                print(f"\n  --- EDICAO: {edicao.upper()} ---")
                executar_pipeline(df=df_ed)
            print("\n  Motor de Clustering concluido em todas as edicoes.")
            return
        if df is None or df.empty:
            print(f"  ERRO: Dados nao encontrados.")
            return

    import os as _os
    limite_amb = _os.environ.get("PRISM_LIMITE_GRUPOS")
    limite_grupos = int(limite_amb) if limite_amb else None

    df = normalizar_coluna_grupo(df)
    grupos = df.groupby("CO_GRUPO")
    for idx, (co_grupo, df_grupo) in enumerate(grupos):
        if limite_grupos and idx >= limite_grupos:
            break
        nome_curso = CURSOS_MAP.get(int(co_grupo), f"Curso_{int(co_grupo)}")
        colunas_existentes = derivar_colunas_questoes(df_grupo)
        if not colunas_existentes:
            print(f"\n  Pulando: {nome_curso} (sem questoes)" )
            continue
        print(f"\n  Processando: {nome_curso} ({len(df_grupo)} alunos)...")
        resultado = executar_clustering_curso(df_grupo, colunas_existentes, nome_curso)
        if resultado:
            print(f"    Melhor k={resultado['melhor_k']}")
        else:
            print(f"    Pulado (poucos alunos)")

    print(f"\n  Pipeline de clustering finalizado!")


if __name__ == "__main__":
    executar_pipeline()
