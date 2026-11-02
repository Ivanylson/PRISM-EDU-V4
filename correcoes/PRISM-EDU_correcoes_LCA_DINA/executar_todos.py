"""
Executor de Algoritmos - PRISM-EDU
Processa os dados em amostras para evitar estouro de memoria.
Le um ano como amostra representativa e roda todos os algoritmos.
"""
import pandas as pd
import numpy as np
import sys
import time
import gc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import (
    PASTA_DADOS_EXTERNOS, PASTA_DADOS_PROCESSADOS, PASTA_CONSOLIDADO,
    PASTA_MODELOS, CURSOS_MAP, SEPARADOR, ENCODING, SEED_ALEATORIA,
    formatar_nome_curso,
)


def carregar_amostra(n_alunos_max=100000):
    """Carrega uma amostra representativa dos dados de serie temporal."""
    print("  Carregando amostra de dados...")
    pasta_enade = PASTA_DADOS_EXTERNOS / "enade"

    arquivos = sorted(pasta_enade.glob("relatorio_final_enade_*.csv"))
    if not arquivos:
        print("  ERRO: Nenhum arquivo encontrado.")
        return None

    frames = []
    total = 0
    for arq in arquivos:
        if total >= n_alunos_max:
            break
        try:
            df = pd.read_csv(arq, sep=SEPARADOR, encoding=ENCODING, low_memory=False)
            n_pegar = min(len(df), n_alvos_por_ano(n_alunos_max, len(arquivos)))
            if n_pegar < len(df):
                df = df.sample(n_pegar, random_state=SEED_ALEATORIA)
            frames.append(df)
            total += len(df)
            print(f"    {arq.stem}: {len(df)} registros")
        except Exception as e:
            print(f"    Erro ao ler {arq.name}: {e}")

    if not frames:
        return None

    df = pd.concat(frames, ignore_index=True)
    gc.collect()
    print(f"  Amostra total: {len(df)} registros de {len(frames)} anos")
    return df


def n_alvos_por_ano(n_total, n_arquivos):
    return max(1000, n_total // n_arquivos)


def executar_eda_rapido(df):
    print("\n  === EDA (Analises Exploratorias) ===")
    pasta_saida = PASTA_DADOS_PROCESSADOS
    colunas_questoes = [f"Q{i}" for i in range(1, 39) if f"Q{i}" in df.columns]

    print("  1. Fadiga de Prova...")
    fadiga = []
    total = len(df)
    for i, q_col in enumerate(colunas_questoes, 1):
        brancos = df[q_col].astype(str).isin(["9", "*", "."]).sum()
        taxa = (brancos / total * 100) if total > 0 else 0
        fadiga.append({
            "QUESTAO": q_col,
            "BLOCO": "FG (1-10)" if i <= 10 else "CE (11-38)",
            "QTD_ABANDONO": int(brancos),
            "TAXA_%": round(taxa, 2),
        })
    pd.DataFrame(fadiga).to_csv(pasta_saida / "eda_1_fadiga.csv", index=False, sep=SEPARADOR, encoding=ENCODING)
    print(f"    Fadiga OK ({len(fadiga)} questoes)")

    print("  2. Ranking Nacional por Questao...")
    for col in colunas_questoes:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    taxa_geral = {}
    for q in colunas_questoes:
        taxa_geral[q] = (df[q] == 0).mean() * 100
    df_taxa = pd.DataFrame(list(taxa_geral.items()), columns=["QUESTAO", "TAXA_ERRO_%"])
    df_taxa = df_taxa.sort_values("TAXA_ERRO_%", ascending=False)
    df_taxa.to_csv(pasta_saida / "eda_2_ranking_questoes.csv", index=False, sep=SEPARADOR, encoding=ENCODING)
    print(f"    Ranking OK")

    print("  3. Benchmark por Curso...")
    if "CO_GRUPO" in df.columns:
        stats_curso = []
        for co_grupo, df_g in df.groupby("CO_GRUPO"):
            nome = CURSOS_MAP.get(int(co_grupo), f"Curso_{co_grupo}")
            taxas = []
            for q in colunas_questoes:
                taxas.append((df_g[q] == 0).mean() * 100)
            stats_curso.append({
                "CURSO": nome,
                "N_ALUNOS": len(df_g),
                "MEDIA_ERRO_%": round(np.mean(taxas), 2),
                "ERRO_MAX_%": round(max(taxas), 2),
                "ERRO_MIN_%": round(min(taxas), 2),
            })
        pd.DataFrame(stats_curso).to_csv(pasta_saida / "eda_3_benchmark_cursos.csv", index=False, sep=SEPARADOR, encoding=ENCODING)
        print(f"    Benchmark OK ({len(stats_curso)} cursos)")

    print("  4. FG vs CE...")
    if "CO_GRUPO" in df.columns:
        fg_ce = []
        for co_grupo, df_g in df.groupby("CO_GRUPO"):
            nome = CURSOS_MAP.get(int(co_grupo), f"Curso_{co_grupo}")
            fg_cols = [f"Q{i}" for i in range(1, 11) if f"Q{i}" in df_g.columns]
            ce_cols = [f"Q{i}" for i in range(11, 39) if f"Q{i}" in df_g.columns]
            if fg_cols and ce_cols:
                media_fg = df_g[fg_cols].apply(lambda x: (x == 0).mean()).mean() * 100
                media_ce = df_g[ce_cols].apply(lambda x: (x == 0).mean()).mean() * 100
                fg_ce.append({"CURSO": nome, "FG_ERRO_%": round(media_fg, 2), "CE_ERRO_%": round(media_ce, 2)})
        if fg_ce:
            pd.DataFrame(fg_ce).to_csv(pasta_saida / "eda_4_fg_vs_ce.csv", index=False, sep=SEPARADOR, encoding=ENCODING)
            print(f"    FG vs CE OK")

    print("  EDA finalizado!")


def executar_clustering_rapido(df):
    print("\n  === Clustering (K-Means + GMM + Hierarquico) ===")
    from sklearn.cluster import KMeans, AgglomerativeClustering
    from sklearn.mixture import GaussianMixture
    from sklearn.metrics import silhouette_score, davies_bouldin_score
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pasta_saida = PASTA_MODELOS / "clustering"
    pasta_saida.mkdir(parents=True, exist_ok=True)
    colunas_questoes = [f"Q{i}" for i in range(1, 39) if f"Q{i}" in df.columns]

    for co_grupo, df_g in df.groupby("CO_GRUPO"):
        nome = CURSOS_MAP.get(int(co_grupo), f"Curso_{co_grupo}")
        if len(df_g) < 100:
            continue

        print(f"  {nome} ({len(df_g)} alunos)...")
        n_amostra = min(len(df_g), 2000)
        df_amostra = df_g.sample(n_amostra, random_state=SEED_ALEATORIA)
        X = df_amostra[colunas_questoes].values.astype(float)

        resultados = []
        inercia = []
        for k in range(2, 7):
            km = KMeans(n_clusters=k, random_state=SEED_ALEATORIA, n_init=10)
            labels_km = km.fit_predict(X)
            inercia.append(km.inertia_)

            gmm = GaussianMixture(n_components=k, random_state=SEED_ALEATORIA)
            labels_gmm = gmm.fit_predict(X)

            hier = AgglomerativeClustering(n_clusters=k, linkage="ward")
            labels_hier = hier.fit_predict(X)

            resultados.append({
                "K": k,
                "KMeans_Sil": round(silhouette_score(X, labels_km), 4),
                "KMeans_DB": round(davies_bouldin_score(X, labels_km), 4),
                "GMM_Sil": round(silhouette_score(X, labels_gmm), 4),
                "Hier_Sil": round(silhouette_score(X, labels_hier), 4),
            })

        df_r = pd.DataFrame(resultados)
        df_r.to_csv(pasta_saida / f"metricas_{formatar_nome_curso(nome)}.csv", index=False, sep=SEPARADOR, encoding=ENCODING)

        plt.figure(figsize=(15, 4))
        plt.subplot(1, 3, 1)
        plt.plot(range(2, 7), inercia, "bo-")
        plt.title("Cotovelo")
        plt.subplot(1, 3, 2)
        plt.plot(df_r["K"], df_r["KMeans_Sil"], "bo-", label="KMeans")
        plt.plot(df_r["K"], df_r["GMM_Sil"], "rs-", label="GMM")
        plt.plot(df_r["K"], df_r["Hier_Sil"], "g^-", label="Hier")
        plt.legend()
        plt.title("Silhueta")
        plt.subplot(1, 3, 3)
        plt.plot(df_r["K"], df_r["KMeans_DB"], "bo-")
        plt.title("Davies-Bouldin")
        plt.suptitle(nome)
        plt.tight_layout()
        plt.savefig(pasta_saida / f"graficos_{formatar_nome_curso(nome)}.png", dpi=150)
        plt.close()

        melhor = df_r.loc[df_r["KMeans_Sil"].idxmax(), "K"]
        print(f"    Melhor k={int(melhor)} (sil={df_r.loc[df_r['KMeans_Sil'].idxmax(), 'KMeans_Sil']:.3f})")

    print("  Clustering finalizado!")


def executar_shap_rapido(df):
    print("\n  === SHAP (Feature Importance) ===")
    import lightgbm as lgb
    import shap
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from sklearn.model_selection import train_test_split

    pasta_saida = PASTA_MODELOS / "shap"
    pasta_saida.mkdir(parents=True, exist_ok=True)
    colunas_questoes = [f"Q{i}" for i in range(1, 39) if f"Q{i}" in df.columns]

    for co_grupo, df_g in df.groupby("CO_GRUPO"):
        nome = CURSOS_MAP.get(int(co_grupo), f"Curso_{co_grupo}")
        if len(df_g) < 200:
            continue

        print(f"  {nome} ({len(df_g)} alunos)...")
        n_amostra = min(len(df_g), 2000)
        df_amostra = df_g.sample(n_amostra, random_state=SEED_ALEATORIA)

        X = df_amostra[colunas_questoes].values.astype(int)
        acertos = X.sum(axis=1)
        y = (acertos >= np.median(acertos)).astype(int)

        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=SEED_ALEATORIA)

        model = lgb.LGBMClassifier(n_estimators=100, max_depth=5, random_state=SEED_ALEATORIA, verbose=-1)
        model.fit(X_train, y_train)
        acc = model.score(X_test, y_test)

        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X_test[:200])

        if isinstance(shap_values, list):
            sv = shap_values[1]
        else:
            sv = shap_values
        if len(sv.shape) == 3:
            sv = sv[:, :, 1]

        importance = np.abs(sv).mean(axis=0)
        df_imp = pd.DataFrame({
            "feature": [f"Q{i+1}" for i in range(len(importance))],
            "importance": importance,
            "importance_pct": (importance / importance.sum() * 100).round(2),
        }).sort_values("importance", ascending=False)

        df_imp.to_csv(pasta_saida / f"importancia_{formatar_nome_curso(nome)}.csv", index=False, sep=SEPARADOR, encoding=ENCODING)

        pd.DataFrame([{"Modelo": "LightGBM", "Acuracia": round(acc, 4)}]).to_csv(
            pasta_saida / f"metricas_{formatar_nome_curso(nome)}.csv", index=False, sep=SEPARADOR, encoding=ENCODING)

        fig, ax = plt.subplots(figsize=(10, 6))
        plt.barh(df_imp["feature"].head(10)[::-1], df_imp["importance"].head(10)[::-1])
        plt.title(f"SHAP Top 10 - {nome} (acc={acc:.3f})")
        plt.tight_layout()
        plt.savefig(pasta_saida / f"shap_{formatar_nome_curso(nome)}.png", dpi=150)
        plt.close()
        print(f"    Acc={acc:.3f}, Top={df_imp.head(3)['feature'].tolist()}")

    print("  SHAP finalizado!")


def executar_som_rapido(df):
    print("\n  === SOM (Self-Organizing Maps) ===")
    from algoritmos.psicometria.som_kohonen import SOM
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pasta_saida = PASTA_MODELOS / "psicometria"
    pasta_saida.mkdir(parents=True, exist_ok=True)
    colunas_questoes = [f"Q{i}" for i in range(1, 39) if f"Q{i}" in df.columns]

    for co_grupo, df_g in df.groupby("CO_GRUPO"):
        nome = CURSOS_MAP.get(int(co_grupo), f"Curso_{co_grupo}")
        if len(df_g) < 200:
            continue

        print(f"  {nome} ({len(df_g)} alunos)...")
        n_amostra = min(len(df_g), 1500)
        df_amostra = df_g.sample(n_amostra, random_state=SEED_ALEATORIA)
        X = df_amostra[colunas_questoes].values.astype(float)

        som = SOM(grid_x=8, grid_y=8, n_iter=80, learning_rate=0.5)
        som.ajustar(X)
        umatrix = som.calcular_umatrix()

        fig, ax = plt.subplots(figsize=(8, 6))
        im = ax.imshow(umatrix.T, cmap="YlOrRd", origin="lower")
        plt.colorbar(im)
        ax.set_title(f"SOM U-Matrix - {nome}")
        plt.tight_layout()
        plt.savefig(pasta_saida / f"som_{formatar_nome_curso(nome)}.png", dpi=150)
        plt.close()
        print(f"    SOM salvo")

    print("  SOM finalizado!")


def executar_dina_rapido(df):
    print("\n  === DINA (Diagnostico Cognitivo) ===")
    print("  [DESATIVADO NESTE EXECUTOR] O DINA exige a matriz-Q do Anexo IX do INEP")
    print("  (mestre_questao_oc.csv), nao uma Q aleatoria. Rode o DINA correto com:")
    print("      python algoritmos/cdm/dina_em.py")
    print("  Este atalho de amostra foi desativado para nao gerar diagnostico invalido.")
    return



def main():
    print("=" * 60)
    print("  PRISM-EDU: Execucao Completa de Algoritmos")
    print("=" * 60)

    df = carregar_amostra(n_alunos_max=80000)
    if df is None or df.empty:
        print("  ERRO: Nao foi possivel carregar dados.")
        return

    t_total = time.time()

    executar_eda_rapido(df)
    gc.collect()

    executar_clustering_rapido(df)
    gc.collect()

    executar_shap_rapido(df)
    gc.collect()

    executar_som_rapido(df)
    gc.collect()

    executar_dina_rapido(df)
    gc.collect()

    elapsed = time.time() - t_total
    print(f"\n{'='*60}")
    print(f"  TODOS OS ALGORITMOS EXECUTADOS EM {elapsed:.0f}s")
    print(f"  Resultados em: {PASTA_MODELOS}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
