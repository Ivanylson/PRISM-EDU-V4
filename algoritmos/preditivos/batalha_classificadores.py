"""
Batalha de Classificadores Classicos (K-NN, Decision Tree, Random Forest, SVM, MLP)
====================================================================================
Benchmark honesto (StratifiedKFold 5x) para prever o extremo de desempenho
(nota externa >= mediana) a partir das respostas aos itens (Q*).

O alvo e EXTERNO (NT_DIS_CE > NT_CE_D1 > NT_GER), nunca derivado das proprias
questoes usadas como features, evitando alvo circular.
"""
import numpy as np
import pandas as pd
from time import perf_counter

from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.neighbors import KNeighborsClassifier
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.svm import SVC
from sklearn.neural_network import MLPClassifier
from sklearn.metrics import (
    accuracy_score, f1_score, roc_auc_score, average_precision_score,
)

from config import derivar_colunas_questoes

# Ordem de prioridade do alvo externo (menos dependente das objetivas primeiro).
COLUNAS_ALVO_EXTERNO = ("NT_DIS_CE", "NT_CE_D1", "NT_GER")


def preparar_colunas(df):
    """Colunas de itens (Q1..Qn) presentes na base, com ao menos uma resposta."""
    try:
        return derivar_colunas_questoes(df)
    except AttributeError:
        cols = [c for c in df.columns if isinstance(c, str) and c[:1] == "Q" and c[1:].isdigit()]
        return [c for c in cols if df[c].notna().any()]


def construir_fabricas(random_state=42):
    """Dicionario {nome: fabrica de classificador} conforme a spec:
    K-NN, DT, RF, SVM e MLP."""
    return {
        "K-NN (k=5)": lambda: make_pipeline(
            StandardScaler(), KNeighborsClassifier(n_neighbors=5, n_jobs=-1)),
        "Arvore de Decisao (DT)": lambda: DecisionTreeClassifier(
            max_depth=6, min_samples_leaf=5, random_state=random_state),
        "Random Forest (RF)": lambda: RandomForestClassifier(
            n_estimators=120, max_depth=8, min_samples_leaf=3,
            n_jobs=-1, random_state=random_state),
        "SVM (RBF)": lambda: make_pipeline(
            StandardScaler(), SVC(kernel="rbf", C=1.0, probability=True, random_state=random_state)),
        "MLP (Redes Neurais)": lambda: make_pipeline(
            StandardScaler(), MLPClassifier(hidden_layer_sizes=(64, 32),
                                            max_iter=500, random_state=random_state)),
    }


def preparar_dados(df, colunas_questoes=None, n_max=3000, random_state=42):
    """Prepara X (itens 0/1) e y (nota externa >= mediana).

    Retorna (X, y) ou (None, None) quando nao ha dados suficientes."""
    if df is None or len(df) < 100:
        return None, None
    if not colunas_questoes:
        colunas_questoes = preparar_colunas(df)
    if len(colunas_questoes) < 3:
        return None, None

    col_alvo = next((c for c in COLUNAS_ALVO_EXTERNO if c in df.columns), None)
    if col_alvo is None:
        return None, None

    df = df.copy()
    df[col_alvo] = pd.to_numeric(df[col_alvo].astype(str).str.replace(",", "."), errors="coerce")

    X = df[colunas_questoes].copy()
    for c in colunas_questoes:
        X[c] = pd.to_numeric(X[c], errors="coerce").map(lambda v: 1.0 if v == 1 else 0.0)

    mask = X.notna().sum(axis=1) >= len(colunas_questoes) * 0.3
    mask &= df[col_alvo].notna() & (df[col_alvo] > 0)
    X, alvo = X.loc[mask], df.loc[mask, col_alvo]
    if len(X) < 100:
        return None, None

    X = X.fillna(0).to_numpy(dtype=float)
    y = (alvo >= alvo.median()).astype(int).to_numpy()

    if len(X) > n_max:
        idx = np.random.RandomState(random_state).choice(len(X), n_max, replace=False)
        X, y = X[idx], y[idx]
    return X, y


def executar_batalha(df, colunas_questoes=None, n_max=2500, n_splits=5, random_state=42):
    """Executa a batalha K-NN/DT/RF/SVM/MLP com validacao cruzada estratificada.

    Retorna DataFrame [Modelo, Acuracia, Acuracia_SD, F1_Score, ROC_AUC, PR_AUC, Tempo_s]
    ordenado por acuracia (decrescente)."""
    X, y = preparar_dados(df, colunas_questoes, n_max=n_max, random_state=random_state)
    if X is None:
        return None

    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=random_state)
    linhas = []
    for nome, fabrica in construir_fabricas(random_state).items():
        t0 = perf_counter()
        accs, f1s, rocs, prs = [], [], [], []
        try:
            for idx_tr, idx_te in skf.split(X, y):
                clf = fabrica()
                clf.fit(X[idx_tr], y[idx_tr])
                proba = np.clip(clf.predict_proba(X[idx_te])[:, 1], 1e-6, 1 - 1e-6)
                pred = (proba >= 0.5).astype(int)
                accs.append(accuracy_score(y[idx_te], pred))
                f1s.append(f1_score(y[idx_te], pred, average="weighted"))
                if len(np.unique(y[idx_te])) > 1:
                    rocs.append(roc_auc_score(y[idx_te], proba))
                    prs.append(average_precision_score(y[idx_te], proba))
        except Exception:
            accs, f1s, rocs, prs = [0.0], [0.0], [], []
        linhas.append({
            "Modelo": nome,
            "Acuracia": round(float(np.mean(accs)), 4),
            "Acuracia_SD": round(float(np.std(accs)), 4),
            "F1_Score": round(float(np.mean(f1s)), 4),
            "ROC_AUC": round(float(np.mean(rocs)), 4) if rocs else np.nan,
            "PR_AUC": round(float(np.mean(prs)), 4) if prs else np.nan,
            "Tempo_s": round(perf_counter() - t0, 2),
        })

    df_res = pd.DataFrame(linhas)
    if "Acuracia" in df_res.columns:
        df_res = df_res.sort_values("Acuracia", ascending=False).reset_index(drop=True)
    return df_res


if __name__ == "__main__":
    from pathlib import Path
    caminho = Path(__file__).resolve().parent.parent.parent.parent / "modeloprojetoENADE2023" / "arquivosgerados" / "relatorio_final_enade_2023.csv"
    if not caminho.exists():
        print("Microdados de referencia nao encontrados; rode pelo orquestrador/aba.")
        raise SystemExit(1)
    df = pd.read_csv(caminho, sep=";", encoding="utf-8-sig", low_memory=False)
    df_grp = df[df["CO_GRUPO"] == 5]
    res = executar_batalha(df_grp)
    print(res.to_string(index=False))