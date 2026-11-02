import pandas as pd
import numpy as np
from pathlib import Path
import warnings
from sklearn.model_selection import train_test_split
from sklearn.neural_network import MLPRegressor
from sklearn.metrics import r2_score, mean_squared_error, mean_absolute_error

warnings.filterwarnings('ignore')

print("=============================================================================")
print("Módulo de Fronteira: Rede de Dependência de Itens (Grafo de Coocorrência)")
print("NOTA: não é 'GKT temporal' — é uma análise estática de grafo item-item")
print("=============================================================================")

DIRETORIO_ATUAL = Path(__file__).resolve().parent
DIRETORIO_RAIZ = DIRETORIO_ATUAL.parent

caminho_microdados = DIRETORIO_RAIZ / 'arquivosgerados' / 'relatorio_final_enade_2023.csv'
pasta_resultados_ml = DIRETORIO_RAIZ / 'arquivosgerados' / 'RESULTADOS_FASE6_ML_AVANCADO_PSICOMETRIA'
pasta_resultados_ml.mkdir(parents=True, exist_ok=True)

# 1. Carregamento (SEM remoção arbitrária de 'anomalias' via IsolationForest)
df = pd.read_csv(caminho_microdados, sep=';', encoding='utf-8', low_memory=False)
if 'TP_PR_GER' in df.columns:
    df = df[df['TP_PR_GER'] > 0].copy()

df.columns = [str(c).strip().upper() for c in df.columns]
colunas_q = [f'Q{i}' for i in range(1, 39)]

for col in colunas_q:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors='coerce').apply(lambda x: 1 if x == 1 else 0)

# Alvo externo válido (sem fillna(0))
coluna_reg_alvo = 'NT_DIS_CE' if 'NT_DIS_CE' in df.columns else 'NT_CE_D1'
df[coluna_reg_alvo] = pd.to_numeric(df[coluna_reg_alvo].astype(str).str.replace(',', '.'), errors='coerce')
df_modelo = df[df[coluna_reg_alvo] > 0].copy()
X_limpo = df_modelo[colunas_q].values
y = df_modelo[coluna_reg_alvo].values
print(f"Alunos com nota discursiva válida: {len(df_modelo)}")

# 2. Matriz de Adjacência do Grafo Cognitivo (relação item-item)
print("[GRAFO] Construindo grafo de coocorrência item-item (correlação)...")
matriz_corr_grafo = np.corrcoef(X_limpo.T)
matriz_corr_grafo = np.nan_to_num(matriz_corr_grafo)

limiar_aresta = 0.15
matriz_adjacencia = np.where(matriz_corr_grafo > limiar_aresta, matriz_corr_grafo, 0)
np.fill_diagonal(matriz_adjacencia, 0)

# 3. Features baseadas no grafo (influência da vizinhança)
print("[GRAFO] Executando propagação de mensagens (message passing) no grafo...")
X_grafo_features = np.dot(X_limpo, matriz_adjacencia)

# 4. Modelagem preditiva com SPLIT HONESTO (não mede no próprio treino)
print("[GRAFO] Treinando rede neural sobre os embeddings do grafo (split 70/30)...")
X_train, X_test, y_train, y_test = train_test_split(X_grafo_features, y, test_size=0.3, random_state=42)

predictor = MLPRegressor(hidden_layer_sizes=(64, 32), max_iter=300, random_state=42, early_stopping=True)
predictor.fit(X_train, y_train)
preds = predictor.predict(X_test)

rmse = np.sqrt(mean_squared_error(y_test, preds))
mae = mean_absolute_error(y_test, preds)
r2 = r2_score(y_test, preds)
print(f"Rede Neural sobre grafo (TESTE) -> R²: {r2:.4f} | RMSE: {rmse:.2f}")

# 5. Centralidade de conhecimento das questões no grafo
centralidade_grau = np.sum(matriz_adjacencia, axis=1)
df_grafo_resultados = pd.DataFrame({
    "Questao": colunas_q,
    "Centralidade_Grafo": centralidade_grau
}).sort_values(by="Centralidade_Grafo", ascending=False)

df_grafo_resultados.to_csv(pasta_resultados_ml / 'resultado_graph_knowledge.csv', index=False, sep=';', decimal=',')

df_perf = pd.DataFrame([{"Modelo": "Rede Neural sobre Grafo de Itens", "RMSE": rmse, "MAE": mae, "R2": r2}])
df_perf.to_csv(pasta_resultados_ml / 'performance_gkt.csv', index=False, sep=';', decimal=',')

print("Resultados da rede de dependência de itens salvos com sucesso!")
