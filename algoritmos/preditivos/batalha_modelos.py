"""
Batalha de Modelos Preditivos - LightGBM, XGBoost, Random Forest, Logistic Regression
Gera importancia de variaveis e metricas por curso.
"""
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split, StratifiedKFold
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score, f1_score, average_precision_score,
    roc_auc_score, brier_score_loss,
)
import lightgbm as lgb
import xgboost as xgb
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


MODELOS = {
    "LightGBM": lambda: lgb.LGBMClassifier(n_estimators=150, max_depth=5, learning_rate=0.1,
                                             random_state=SEED_ALEATORIA, verbose=-1),
    "XGBoost": lambda: xgb.XGBClassifier(n_estimators=150, max_depth=5, learning_rate=0.1,
                                           random_state=SEED_ALEATORIA, eval_metric="logloss", verbosity=0),
    "RandomForest": lambda: RandomForestClassifier(n_estimators=100, max_depth=8, random_state=SEED_ALEATORIA),
    "LogisticRegression": lambda: LogisticRegression(max_iter=500, random_state=SEED_ALEATORIA),
}


COLUNAS_ALVO_EXTERNO = ("NT_DIS_CE", "NT_CE_D1")


def _localizar_coluna_alvo(df):
    """Alvo externo (nota obtida em componente discursivo), nunca derivado das
    proprias questoes usadas como features (evita alvo circular)."""
    for col in COLUNAS_ALVO_EXTERNO:
        if col in df.columns:
            return col
    return None


def preparar_dados(df, colunas_questoes, coluna_alvo=None):
    """Prepara X (itens) e y (binario: nota externa >= mediana da nota externa).

    O alvo e a nota discursiva (NT_DIS_CE, com fallback NT_CE_D1), NAO a soma
    dos proprios itens - usar soma gerava alvo circular (a feature e a soma).
    """
    if coluna_alvo is None:
        coluna_alvo = _localizar_coluna_alvo(df)
    if coluna_alvo is None:
        return None, None, None

    df = df.copy()
    df[coluna_alvo] = pd.to_numeric(df[coluna_alvo].astype(str).str.replace(",", "."), errors="coerce")

    X = df[colunas_questoes].copy()
    for col in colunas_questoes:
        X[col] = pd.to_numeric(X[col], errors="coerce")
    mask_valido = X.notna().any(axis=1) & (X.notna().sum(axis=1) >= len(colunas_questoes) * 0.3)
    mask_valido &= df[coluna_alvo].notna() & (df[coluna_alvo] > 0)
    X = X.loc[mask_valido]
    if len(X) < 50:
        return None, None, None
    X = X.fillna(0).astype(int)
    y = (df.loc[mask_valido, coluna_alvo] >= df.loc[mask_valido, coluna_alvo].median()).astype(int)
    return X.values, y, list(colunas_questoes)


def avaliar_modelo_cv(factory, X, y, n_splits=5):
    """Validacao robusta: StratifiedKFold com Acc/F1/PR-AUC/ROC-AUC/Brier.
    Retorna (metricas agregadas, probabilidades out-of-fold)."""
    y = np.asarray(y).astype(int)
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=SEED_ALEATORIA)
    oof = np.full(len(y), np.nan)
    accs, f1s, prs, rocs, briers = [], [], [], [], []
    for idx_train, idx_test in skf.split(X, y):
        model = factory()
        model.fit(X[idx_train], y[idx_train])
        y_prob = model.predict_proba(X[idx_test])[:, 1]
        oof[idx_test] = y_prob
        y_pred = (y_prob >= 0.5).astype(int)
        accs.append(accuracy_score(y[idx_test], y_pred))
        f1s.append(f1_score(y[idx_test], y_pred, average="weighted"))
        if len(np.unique(y[idx_test])) > 1:
            prs.append(average_precision_score(y[idx_test], y_prob))
            rocs.append(roc_auc_score(y[idx_test], y_prob))
        briers.append(brier_score_loss(y[idx_test], y_prob))
    metricas = {
        "Acuracia": round(float(np.mean(accs)), 4),
        "Acuracia_SD": round(float(np.std(accs)), 4),
        "F1_Score": round(float(np.mean(f1s)), 4),
        "PR_AUC": round(float(np.mean(prs)), 4) if prs else np.nan,
        "ROC_AUC": round(float(np.mean(rocs)), 4) if rocs else np.nan,
        "Brier": round(float(np.mean(briers)), 4),
    }
    return metricas, oof


def tabela_calibracao(y_true, y_prob, n_bins=10):
    """Curva de calibracao (previsto x observado) em bins quantilicos."""
    df_cal = pd.DataFrame({"y": y_true, "p": y_prob}).dropna(subset=["p"])
    if df_cal["p"].nunique() < 2:
        return pd.DataFrame()
    n_bins_ef = min(n_bins, df_cal["p"].nunique())
    df_cal["bin"] = pd.qcut(df_cal["p"], n_bins_ef, duplicates="drop")
    tab = df_cal.groupby("bin", observed=False).agg(
        n=("y", "size"),
        previsto=("p", "mean"),
        observado=("y", "mean"),
    ).reset_index()
    tab["diferenca"] = (tab["observado"] - tab["previsto"]).round(4)
    return tab


def executar_batalha_curso(df_curso, colunas_questoes, nome_curso, pasta_saida=None):
    if len(df_curso) < 100:
        return None

    n_amostra = min(len(df_curso), 3000)
    df_amostra = df_curso.sample(n_amostra, random_state=SEED_ALEATORIA)
    X, y, nomes = preparar_dados(df_amostra, colunas_questoes)
    if X is None:
        return None
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=SEED_ALEATORIA)

    resultados = []
    melhor_modelo = None
    melhor_acc = 0

    for nome_mod, factory in MODELOS.items():
        try:
            model = factory()
            model.fit(X_train, y_train)
            y_pred = model.predict(X_test)
            acc = accuracy_score(y_test, y_pred)
            f1 = f1_score(y_test, y_pred, average="weighted")
            resultados.append({
                "Modelo": nome_mod,
                "Acuracia": round(acc, 4),
                "F1_Score": round(f1, 4),
            })
            if acc > melhor_acc:
                melhor_acc = acc
                melhor_modelo = (nome_mod, model)
        except Exception as e:
            resultados.append({"Modelo": nome_mod, "Acuracia": 0, "F1_Score": 0})

    if pasta_saida is None:
        pasta_saida = pasta_saida_edicao("preditivos")
    pasta_saida.mkdir(parents=True, exist_ok=True)

    df_resultados = pd.DataFrame(resultados)
    csv_metricas = pasta_saida / f"metricas_modelos_{formatar_nome_curso(nome_curso)}.csv"
    df_resultados.to_csv(csv_metricas, index=False, sep=SEPARADOR, encoding=ENCODING)

    resultados_cv = []
    calibracao_por_modelo = []
    for nome_mod, factory in MODELOS.items():
        try:
            metricas_cv, oof = avaliar_modelo_cv(factory, X, y)
            resultados_cv.append({"Modelo": nome_mod, **metricas_cv})
            tab = tabela_calibracao(y, oof)
            if not tab.empty:
                tab.insert(0, "Modelo", nome_mod)
                calibracao_por_modelo.append(tab)
        except Exception:
            resultados_cv.append({
                "Modelo": nome_mod, "Acuracia": 0, "Acuracia_SD": 0,
                "F1_Score": 0, "PR_AUC": 0, "ROC_AUC": 0, "Brier": 1,
            })
    df_cv = pd.DataFrame(resultados_cv)
    df_cv.to_csv(pasta_saida / f"metricas_modelos_cv_{formatar_nome_curso(nome_curso)}.csv",
                 index=False, sep=SEPARADOR, encoding=ENCODING)
    if calibracao_por_modelo:
        pd.concat(calibracao_por_modelo, ignore_index=True).to_csv(
            pasta_saida / f"calibracao_{formatar_nome_curso(nome_curso)}.csv",
            index=False, sep=SEPARADOR, encoding=ENCODING)

    if melhor_modelo:
        nome_melhor, model_melhor = melhor_modelo
        pesos = None
        if hasattr(model_melhor, "feature_importances_"):
            pesos = np.asarray(model_melhor.feature_importances_, dtype=float)
        elif hasattr(model_melhor, "coef_"):
            pesos = np.abs(np.ravel(model_melhor.coef_)).astype(float)
        else:
            try:
                from sklearn.inspection import permutation_importance

                perm = permutation_importance(
                    model_melhor,
                    X,
                    np.asarray(y).astype(int),
                    n_repeats=5,
                    random_state=SEED_ALEATORIA,
                    scoring="accuracy",
                )
                pesos = np.asarray(perm.importances_mean, dtype=float)
            except Exception:
                pesos = None

        if pesos is not None and len(pesos) == len(nomes) and pesos.sum() > 0:
            df_pesos = pd.DataFrame({
                "feature": nomes,
                "peso": pesos,
            }).sort_values("peso", ascending=False)
            df_pesos["peso_pct"] = (df_pesos["peso"] / df_pesos["peso"].sum() * 100).round(2)

            csv_pesos = pasta_saida / f"importancia_variaveis_{formatar_nome_curso(nome_curso)}.csv"
            df_pesos.to_csv(csv_pesos, index=False, sep=SEPARADOR, encoding=ENCODING)

    return df_resultados


def _executar_batalha_edicao(df, limite_grp=None):
    """Executa a batalha de modelos sobre um unico DataFrame (uma edicao).

    Grava em modelos/preditivos/<edicao>/ conforme a variavel PRISM_EDICAO
    (definida pelo orquestrador por edicao)."""
    pasta_saida = pasta_saida_edicao("preditivos")
    df = normalizar_coluna_grupo(df)

    for n_grp, (co_grupo, df_grupo) in enumerate(df.groupby("CO_GRUPO")):
        if limite_grp and n_grp >= limite_grp:
            break
        nome_curso = CURSOS_MAP.get(int(co_grupo), f"Curso_{int(co_grupo)}")
        colunas_existentes = derivar_colunas_questoes(df_grupo)
        if not colunas_existentes:
            continue
        print(f"  {nome_curso} ({len(df_grupo)} alunos)...", end=" ", flush=True)
        resultado = executar_batalha_curso(df_grupo, colunas_existentes, nome_curso, pasta_saida)
        if resultado is not None:
            melhor = resultado.loc[resultado["Acuracia"].idxmax()]
            print(f"Melhor: {melhor['Modelo']} (acc={melhor['Acuracia']:.3f})")
        else:
            print("pulado (<100 alunos ou sem alvo externo)")


def executar_pipeline(caminho_csv=None, df=None):
    print("=" * 60)
    print("  PRISM-EDU: Batalha de Modelos Preditivos")
    print("=" * 60)

    import os as _os
    limite_grp_amb = _os.environ.get("PRISM_LIMITE_GRUPOS")
    limite_grp = int(limite_grp_amb) if limite_grp_amb else None

    # Modo edicao unica: o orquestrador passa um DataFrame ou caminho.
    if df is not None or caminho_csv is not None:
        if df is None:
            df = pd.read_csv(caminho_csv, sep=SEPARADOR, encoding=ENCODING, low_memory=False)
        _executar_batalha_edicao(df, limite_grp)
        print(f"\n  Batalha finalizada!")
        return

    from config import PASTA_DADOS_EXTERNOS, listar_edicoes_disponiveis, caminho_arquivo_edicao

    for edicao in listar_edicoes_disponiveis():
        caminho = caminho_arquivo_edicao(edicao)
        if caminho is None:
            continue
        os.environ["PRISM_EDICAO"] = edicao
        print(f"\n  --- {edicao.upper()} ---")
        try:
            df = pd.read_csv(caminho, sep=SEPARADOR, encoding=ENCODING, low_memory=False)
        except Exception as e:
            print(f"  ERRO ao ler {caminho.name}: {e}")
            continue
        _executar_batalha_edicao(df, limite_grp)
        del df

    print(f"\n  Batalha finalizada!")


if __name__ == "__main__":
    executar_pipeline()
