"""
Analise SHAP (SHapley Additive exPlanations) para modelos de previsao educacional.
Gera valores SHAP para LightGBM/XGBoost e visualizacoes interativas.
"""
import pandas as pd
import numpy as np
import shap
import lightgbm as lgb
import xgboost as xgb
from sklearn.model_selection import train_test_split
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
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


COLUNAS_ALVO_EXTERNO = ("NT_DIS_CE", "NT_CE_D1")


def _detectar_coluna_alvo(df):
    for col in COLUNAS_ALVO_EXTERNO:
        if col in df.columns:
            return col
    return None


def preparar_dados_predicao(df, colunas_questoes, coluna_alvo=None):
    """Prepara X (itens) e y (binario pela nota externa >= mediana).

    Requer alvo externo (NT_DIS_CE ou NT_CE_D1) para evitar alvo circular.
    """
    X = df[colunas_questoes].copy()
    for col in colunas_questoes:
        X[col] = pd.to_numeric(X[col], errors="coerce").fillna(0).astype(int)

    if coluna_alvo is None:
        coluna_alvo = _detectar_coluna_alvo(df)
    if coluna_alvo is None:
        raise ValueError(
            "Sem alvo externo (NT_DIS_CE/NT_CE_D1) na base. "
            "SHAP exige alvo nao circular derivado das proprias questoes."
        )

    y_raw = pd.to_numeric(df[coluna_alvo].astype(str).str.replace(",", "."), errors="coerce")
    mask_valido = X.notna().any(axis=1) & y_raw.notna() & (y_raw > 0)
    X = X.loc[mask_valido]
    y_raw = y_raw.loc[mask_valido]
    if len(X) < 50:
        raise ValueError("Apos filtro de alunos com nota externa valida, base insuficiente.")
    y = (y_raw >= y_raw.median()).astype(int)
    return X.values, y, list(colunas_questoes)


def treinar_modelo_lightgbm(X_train, y_train, X_test, y_test):
    model = lgb.LGBMClassifier(
        n_estimators=200, max_depth=6, learning_rate=0.1,
        random_state=SEED_ALEATORIA, verbose=-1
    )
    model.fit(X_train, y_train)
    acc_train = model.score(X_train, y_train)
    acc_test = model.score(X_test, y_test)
    return model, acc_train, acc_test


def treinar_modelo_xgboost(X_train, y_train, X_test, y_test):
    model = xgb.XGBClassifier(
        n_estimators=200, max_depth=6, learning_rate=0.1,
        random_state=SEED_ALEATORIA, use_label_encoder=False,
        eval_metric="logloss", verbosity=0
    )
    model.fit(X_train, y_train)
    acc_train = model.score(X_train, y_train)
    acc_test = model.score(X_test, y_test)
    return model, acc_train, acc_test


def calcular_shap(model, X, nomes_features, modelo_tipo="lightgbm"):
    if modelo_tipo in ("lightgbm", "xgboost"):
        explainer = shap.TreeExplainer(model)
    else:
        explainer = shap.KernelExplainer(model.predict_proba, shap.sample(X, 100))
    shap_values = explainer.shap_values(X)
    return explainer, shap_values


def gerar_graficos_shap(shap_values, X, nomes_features, nome_curso, pasta_saida, modelo_tipo="lightgbm"):
    pasta_graficos = pasta_saida / "shap_plots"
    pasta_graficos.mkdir(parents=True, exist_ok=True)

    try:
        if isinstance(shap_values, list):
            sv = shap_values[1] if len(shap_values) > 1 else shap_values[0]
        else:
            sv = shap_values

        if len(sv.shape) == 3:
            sv = sv[:, :, 1]

        fig, ax = plt.subplots(figsize=(12, 8))
        shap.summary_plot(sv, features=X, feature_names=nomes_features,
                          show=False, max_display=20)
        plt.title(f"SHAP Summary - {nome_curso}", fontsize=14, fontweight="bold")
        plt.tight_layout()
        caminho = pasta_graficos / f"shap_summary_{formatar_nome_curso(nome_curso)}.png"
        plt.savefig(caminho, dpi=300, bbox_inches="tight")
        plt.close("all")

        plt.figure(figsize=(12, 8))
        shap.summary_plot(sv, features=X, feature_names=nomes_features,
                          plot_type="bar", show=False, max_display=20)
        plt.title(f"SHAP Feature Importance - {nome_curso}", fontsize=14, fontweight="bold")
        plt.tight_layout()
        caminho_bar = pasta_graficos / f"shap_importance_{formatar_nome_curso(nome_curso)}.png"
        plt.savefig(caminho_bar, dpi=300, bbox_inches="tight")
        plt.close("all")

        return caminho, caminho_bar
    except Exception as e:
        print(f"    Aviso ao gerar graficos SHAP: {e}")
        return None, None


def executar_analise_shap(caminho_csv=None, df=None):
    print("=" * 60)
    print("  PRISM-EDU: Analise SHAP (Feature Importance)")
    print("=" * 60)

    if df is None:
        if caminho_csv is None:
            print("  Processando TODAS as edicoes (memoria leve, uma por vez)...")
            from config import iterar_edicoes_dados
            for edicao, df_ed in iterar_edicoes_dados():
                print(f"\n  --- EDICAO: {edicao.upper()} ---")
                executar_analise_shap(df=df_ed)
            print("\n  Analise SHAP concluida em todas as edicoes.")
            return
        else:
            df = pd.read_csv(caminho_csv, sep=SEPARADOR, encoding=ENCODING, low_memory=False)
        if df is None or df.empty:
            print(f"  ERRO: Dados nao encontrados.")
            return
    colunas_existentes = derivar_colunas_questoes(df)

    pasta_saida = pasta_saida_edicao("shap")
    pasta_saida.mkdir(parents=True, exist_ok=True)

    df = normalizar_coluna_grupo(df)
    grupos = df.groupby("CO_GRUPO")
    import os as _os
    limite_amb = _os.environ.get("PRISM_LIMITE_GRUPOS")
    limite_grupos = int(limite_amb) if limite_amb else None

    for idx, (co_grupo, df_grupo) in enumerate(grupos):
        if limite_grupos and idx >= limite_grupos:
            break
        nome_curso = CURSOS_MAP.get(int(co_grupo), f"Curso_{int(co_grupo)}")
        if len(df_grupo) < 100:
            continue
        colunas_existentes = derivar_colunas_questoes(df_grupo)
        if not colunas_existentes:
            continue

        print(f"\n  {nome_curso} ({len(df_grupo)} alunos)...")

        n_amostra = min(len(df_grupo), 3000)
        df_amostra = df_grupo.sample(n_amostra, random_state=SEED_ALEATORIA)

        try:
            X, y, nomes = preparar_dados_predicao(df_amostra, colunas_existentes)
        except ValueError as e:
            print(f"    Pulando {nome_curso}: {e}")
            continue
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=SEED_ALEATORIA)

        print(f"    Treinando LightGBM...")
        model_lgb, acc_lgb_train, acc_lgb_test = treinar_modelo_lightgbm(X_train, y_train, X_test, y_test)
        print(f"    LightGBM: train={acc_lgb_train:.3f}, test={acc_lgb_test:.3f}")

        print(f"    Calculando SHAP values...")
        explainer, shap_values = calcular_shap(model_lgb, X_test, nomes, "lightgbm")

        img1, img2 = gerar_graficos_shap(shap_values, X_test, nomes, nome_curso, pasta_saida)

        importance = np.abs(shap_values).mean(axis=0) if isinstance(shap_values, np.ndarray) else np.abs(shap_values[1]).mean(axis=0)
        df_importance = pd.DataFrame({
            "feature": nomes,
            "importance": importance
        }).sort_values("importance", ascending=False)

        csv_importance = pasta_saida / f"importancia_shap_{formatar_nome_curso(nome_curso)}.csv"
        df_importance.to_csv(csv_importance, index=False, sep=SEPARADOR, encoding=ENCODING)

        csv_metricas = pasta_saida / f"metricas_shap_{formatar_nome_curso(nome_curso)}.csv"
        pd.DataFrame([
            {"Modelo": "LightGBM", "Acuracia_Treino": round(acc_lgb_train, 4),
             "Acuracia_Teste": round(acc_lgb_test, 4)}
        ]).to_csv(csv_metricas, index=False, sep=SEPARADOR, encoding=ENCODING)

        print(f"    Top 5 features: {', '.join(df_importance.head(5)['feature'].tolist())}")

    print(f"\n  Analise SHAP finalizada!")


if __name__ == "__main__":
    executar_analise_shap()
