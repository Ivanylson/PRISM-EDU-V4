import pandas as pd
import numpy as np
from pathlib import Path
import warnings

from sklearn.model_selection import cross_validate, StratifiedKFold
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression, ElasticNet
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.svm import LinearSVC
from sklearn.neighbors import KNeighborsClassifier
from sklearn.naive_bayes import GaussianNB

warnings.filterwarnings('ignore')

print("=============================================================================")
print("Módulo Corrigido: Batalha de Modelos sobre os Itens (Q1-Q38)")
print("Alvo EXTERNO (NT_DIS_CE) - sem vazamento das questões objetivas")
print("=============================================================================")

DIRETORIO_ATUAL = Path(__file__).resolve().parent
DIRETORIO_RAIZ = DIRETORIO_ATUAL.parent
caminho_microdados = DIRETORIO_RAIZ / 'arquivosgerados' / 'relatorio_final_enade_2023.csv'
pasta_resultados = DIRETORIO_RAIZ / 'arquivosgerados' / 'RESULTADOS_FASE6_ML_AVANCADO'

df = pd.read_csv(caminho_microdados, sep=';', encoding='utf-8', low_memory=False)
df = df[df['TP_PR_GER'] > 0].copy()

colunas_q = [f'Q{i}' for i in range(1, 39)]
for col in colunas_q:
    df[col] = pd.to_numeric(df[col], errors='coerce').apply(lambda x: 1 if x == 1 else 0)

# --- ALVO EXTERNO: desempenho na prova DISCURSIVA (não derivado de Q1-Q38) ---
col_alvo = 'NT_DIS_CE' if 'NT_DIS_CE' in df.columns else 'NT_CE_D1'
df[col_alvo] = pd.to_numeric(df[col_alvo].astype(str).str.replace(',', '.'), errors='coerce')

# Apenas alunos com nota discursiva válida (>0)
df_modelo = df[df[col_alvo] > 0].copy()
corte = df_modelo[col_alvo].median()
df_modelo['CLASSE'] = (df_modelo[col_alvo] >= corte).astype(int)
print(f"Alvo: classe >= mediana da nota discursiva ({corte:.1f})")

# Subamostragem rápida e estável para benchmark
n_amostra = min(30000, len(df_modelo))
df_amostra = df_modelo.sample(n=n_amostra, random_state=42)
X = df_amostra[colunas_q].values
y = df_amostra['CLASSE'].values

X_escalado = StandardScaler().fit_transform(X)

# 1. ElasticNet como controle de variância (regressão com alvo contínuo externo)
en = ElasticNet(alpha=0.1, l1_ratio=0.5, random_state=42)
en.fit(X_escalado, df_amostra[col_alvo].values)
en_rmse = np.sqrt(np.mean((en.predict(X_escalado) - df_amostra[col_alvo].values) ** 2))
print(f"ElasticNet (controle): RMSE no mesmo conjunto {en_rmse:.2f}")

# 2. Avaliação honesta via K-Fold Cross-Validation (5 Folds), estratificada
modelos = {
    "Regressão Logística": LogisticRegression(max_iter=1000),
    "Árvore de Decisão": DecisionTreeClassifier(max_depth=6, random_state=42),
    "Random Forest": RandomForestClassifier(n_estimators=50, max_depth=6, random_state=42, n_jobs=-1),
    "SVM (Linear)": LinearSVC(dual=False),
    "k-NN (5 Neighbors)": KNeighborsClassifier(n_neighbors=5),
    "Naive Bayes": GaussianNB()
}

cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
resultados_batalha = []

for nome, mod in modelos.items():
    scores = cross_validate(mod, X_escalado, y, cv=cv,
                            scoring={'acc': 'accuracy', 'f1': 'f1', 'auc': 'roc_auc'},
                            n_jobs=-1)
    resultados_batalha.append({
        "Modelo": nome,
        "Acurácia Média CV": np.mean(scores['test_acc']),
        "Desvio Padrão": np.std(scores['test_acc']),
        "F1 Médio CV": np.mean(scores['test_f1']),
        "AUC-ROC Médio CV": np.mean(scores['test_auc']),
    })
    print(f"-> {nome}: acc {np.mean(scores['test_acc']):.4f} | AUC {np.mean(scores['test_auc']):.4f}")

pd.DataFrame(resultados_batalha).to_csv(pasta_resultados / 'batalha_classificadores_classicos.csv',
                                        index=False, sep=';', decimal=',')
print(f"\nSalvo: batalha_classificadores_classicos.csv (em {pasta_resultados})")

# Controle de variância: ElasticNet (regressão sobre alvo contínuo externo, mesmo amostra)
with open(pasta_resultados / 'controle_elasticnet_batalha.txt', 'w', encoding='utf-8') as f:
    f.write("Controle de variância da batalha de classificadores.\n")
    f.write(f"ElasticNet (alpha=0.1, l1_ratio=0.5) sobre itens Q1..Q38 -> NT_DIS_CE\n")
    f.write(f"RMSE no mesmo conjunto (amostra de {n_amostra}): {en_rmse:.4f}\n")
    f.write("Nota: RMSE no mesmo conjunto (diagnóstico de sinal), nao e validacao.\n")
print("Salvo: controle_elasticnet_batalha.txt")
