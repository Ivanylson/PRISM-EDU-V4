"""
Explicabilidade (XAI) - LIME + Counterfactual + Feature Attribution
fornece explicacoes locais e globais para decisoes de modelos educacionais.
"""
import pandas as pd
import numpy as np
from pathlib import Path
import sys
import warnings
warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config import (
    SEPARADOR, ENCODING, SEED_ALEATORIA, CURSOS_MAP,
    formatar_nome_curso, caminho_saida_algoritmo,
    pasta_saida_edicao, derivar_colunas_questoes, normalizar_coluna_grupo,
)

from algoritmos.shap.shap_analysis import (
    preparar_dados_predicao, treinar_modelo_lightgbm,
)
from sklearn.model_selection import train_test_split


def calcular_counterfactuals(model, X_test, y_test, nomes_features, n_instancias=5):
    from sklearn.metrics.pairwise import euclidean_distances

    resultados = []
    indices = np.random.RandomState(SEED_ALEATORIA).choice(len(X_test), min(n_instancias, len(X_test)), replace=False)

    for idx in indices:
        instancia = X_test[idx:idx+1]
        pred_original = model.predict(instancia)[0]
        probs_original = model.predict_proba(instancia)[0]

        instancia_modificada = instancia.copy()
        melhor_dist = np.inf
        melhor_instancia = None
        mudancas = []

        for j in range(X_test.shape[1]):
            teste = instancia.copy()
            if instancia[0, j] == 1:
                teste[0, j] = 0
            else:
                teste[0, j] = 1

            pred_teste = model.predict(teste)[0]
            if pred_teste != pred_original:
                dist = euclidean_distances(instancia, teste)[0, 0]
                if dist < melhor_dist:
                    melhor_dist = dist
                    melhor_instancia = teste.copy()
                    mudancas = [nomes_features[j]]

        if melhor_instancia is None:
            from itertools import combinations

            for j, k in combinations(range(X_test.shape[1]), 2):
                teste = instancia.copy()
                teste[0, j] = 1 - teste[0, j]
                teste[0, k] = 1 - teste[0, k]

                pred_teste = model.predict(teste)[0]
                if pred_teste != pred_original:
                    dist = euclidean_distances(instancia, teste)[0, 0]
                    if dist < melhor_dist:
                        melhor_dist = dist
                        melhor_instancia = teste.copy()
                        mudancas = [nomes_features[j], nomes_features[k]]

        if melhor_instancia is not None:
            diff = instancia[0] != melhor_instancia[0]
            features_mudadas = [nomes_features[j] for j in range(len(diff)) if diff[j]]

            resultados.append({
                "instancia_idx": int(idx),
                "pred_original": int(pred_original),
                "pred_contrafactual": int(model.predict(melhor_instancia)[0]),
                "distancia": round(melhor_dist, 4),
                "features_mudadas": " | ".join(features_mudadas),
                "n_mudancas": len(features_mudadas),
            })

    return pd.DataFrame(resultados)


def analise_atribuicao_global(model, X, y, nomes_features):
    from sklearn.inspection import permutation_importance

    result = permutation_importance(model, X, y, n_repeats=10, random_state=SEED_ALEATORIA, n_jobs=-1)

    df_atribuicao = pd.DataFrame({
        "feature": nomes_features,
        "importancia_media": result.importances_mean,
        "importancia_std": result.importances_std,
    }).sort_values("importancia_media", ascending=False)

    return df_atribuicao


def executar_xai_completo(caminho_csv=None, df=None):
    print("=" * 60)
    print("  PRISM-EDU: XAI (Explicabilidade)")
    print("=" * 60)

    if df is None:
        if caminho_csv is None:
            # Nunca carregar o CSV consolidado (4GB -> OOM). Uma edicao por vez.
            print("  Processando TODAS as edicoes (memoria leve, uma por vez)...")
            from config import iterar_edicoes_dados
            for edicao, df_ed in iterar_edicoes_dados():
                print(f"\n  --- EDICAO: {edicao.upper()} ---")
                executar_xai_completo(df=df_ed)
            print("\n  Motor XAI concluido em todas as edicoes.")
            return
        else:
            if not caminho_csv.exists():
                print(f"  ERRO: CSV nao encontrado.")
                return
            df = pd.read_csv(caminho_csv, sep=SEPARADOR, encoding=ENCODING, low_memory=False)
        if df is None or df.empty:
            print("  ERRO: Dados nao encontrados.")
            return
    colunas_existentes = derivar_colunas_questoes(df)
    return _executar_sobre_df(df, colunas_existentes)


def _executar_sobre_df(df, colunas_existentes):
    nomes_questoes = [f"Q{i}" for i in range(1, len(colunas_existentes) + 1)]

    pasta_saida = pasta_saida_edicao("xai")
    pasta_saida.mkdir(parents=True, exist_ok=True)

    import os as _os
    limite_amb = _os.environ.get("PRISM_LIMITE_GRUPOS")
    limite_grupos = int(limite_amb) if limite_amb else None

    df = normalizar_coluna_grupo(df)
    grupos = df.groupby("CO_GRUPO")
    for idx, (co_grupo, df_grupo) in enumerate(grupos):
        if limite_grupos and idx >= limite_grupos:
            break
        nome_curso = CURSOS_MAP.get(int(co_grupo), f"Curso_{int(co_grupo)}")
        if len(df_grupo) < 200:
            continue
        colunas_curso = derivar_colunas_questoes(df_grupo)
        if not colunas_curso:
            continue

        print(f"\n  {nome_curso} ({len(df_grupo)} alunos)...")

        n_amostra = min(len(df_grupo), 3000)
        df_amostra = df_grupo.sample(n_amostra, random_state=SEED_ALEATORIA)
        X, y, nomes = preparar_dados_predicao(df_amostra, colunas_curso)
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=SEED_ALEATORIA)

        model, acc_train, acc_test = treinar_modelo_lightgbm(X_train, y_train, X_test, y_test)
        print(f"    LightGBM: train={acc_train:.3f}, test={acc_test:.3f}")

        print(f"    Gerando counterfactuals...")
        df_cf = calcular_counterfactuals(model, X_test, y_test, nomes)
        if not df_cf.empty:
            csv_cf = pasta_saida / f"counterfactuals_{formatar_nome_curso(nome_curso)}.csv"
            df_cf.to_csv(csv_cf, index=False, sep=SEPARADOR, encoding=ENCODING)
            print(f"    Counterfactuals: {len(df_cf)} gerados")

        print(f"    Analise de atribuicao global...")
        df_atrib = analise_atribuicao_global(model, X_test, y_test, nomes)
        csv_atrib = pasta_saida / f"atribuicao_{formatar_nome_curso(nome_curso)}.csv"
        df_atrib.to_csv(csv_atrib, index=False, sep=SEPARADOR, encoding=ENCODING)
        print(f"    Top 5: {', '.join(df_atrib.head(5)['feature'].tolist())}")

    print(f"\n  XAI finalizado!")


if __name__ == "__main__":
    executar_xai_completo()
