import pandas as pd
import numpy as np
from pathlib import Path
import warnings

from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.ensemble import AdaBoostClassifier, RandomForestRegressor
from sklearn.neural_network import MLPClassifier, MLPRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import (accuracy_score, balanced_accuracy_score, roc_auc_score,
                             mean_squared_error, mean_absolute_error, r2_score)
from sklearn.inspection import permutation_importance

try:
    from lightgbm import LGBMClassifier, LGBMRegressor
except ImportError:
    LGBMClassifier, LGBMRegressor = None, None

warnings.filterwarnings('ignore')

# =============================================================================
# 1. CONFIGURAÇÕES DE CAMINHOS
# =============================================================================
print("Inicializando Fase 6 de Fronteira: Psicometria Clássica (TCT) & IA Educacional...")

DIRETORIO_ATUAL = Path(__file__).resolve().parent
DIRETORIO_RAIZ = DIRETORIO_ATUAL.parent

caminho_microdados = DIRETORIO_RAIZ / 'arquivosgerados' / 'relatorio_final_enade_2023.csv'
pasta_resultados_ml = DIRETORIO_RAIZ / 'arquivosgerados' / 'RESULTADOS_FASE6_ML_AVANCADO_PSICOMETRIA'
pasta_resultados_ml.mkdir(parents=True, exist_ok=True)

# =============================================================================
# 2. CARREGAMENTO E ENGENHARIA DE SINAIS PSICOMÉTRICOS (TCT)
# =============================================================================
print("\nCarregando microdados...")
df = pd.read_csv(caminho_microdados, sep=';', encoding='utf-8', low_memory=False)
if 'TP_PR_GER' in df.columns:
    df = df[df['TP_PR_GER'] > 0].copy()

df.columns = [str(c).strip().upper() for c in df.columns]
colunas_q = [f'Q{i}' for i in range(1, 39)]

print("Estimando Estatísticas de Teoria Clássica dos Testes (TCT) por item...")
for col in colunas_q:
    df[col] = pd.to_numeric(df[col], errors='coerce').apply(lambda x: 1 if x == 1 else 0)

# --- ESTATÍSTICAS TCT POR ITEM (NÃO É IRT) ---
# Dificuldade (b) = 1 - taxa de acerto ; Discriminação (a) = correlação ponto-bisserial item-total
df['SOMA_OBJETIVA'] = df[colunas_q].sum(axis=1)
pesos_irt = {}

for col in colunas_q:
    taxa_acerto = df[col].mean()
    dificuldade_b = 1.0 - taxa_acerto
    discriminacao_a = df[col].corr(df['SOMA_OBJETIVA'])
    if np.isnan(discriminacao_a) or discriminacao_a < 0.1:
        discriminacao_a = 0.1
    pesos_irt[col] = {"a": discriminacao_a, "b": dificuldade_b}

df_pesos_irt = pd.DataFrame.from_dict(pesos_irt, orient='index').reset_index()
df_pesos_irt.columns = ['Questao', 'Discriminacao_A', 'Dificuldade_B']
df_pesos_irt['Metodo'] = 'TCT (dificuldade=1-p; discriminacao=ponto-bisserial item-total)'
df_pesos_irt.to_csv(pasta_resultados_ml / 'metricas_irt_questoes.csv', index=False, sep=';', decimal=',')
print("Salvo: metricas_irt_questoes.csv (estatísticas TCT, corretamente rotuladas)")

# --- ALVO EXTERNO (SEM VAZAMENTO) ---
coluna_reg_alvo = 'NT_DIS_CE' if 'NT_DIS_CE' in df.columns else 'NT_CE_D1'
df[coluna_reg_alvo] = pd.to_numeric(df[coluna_reg_alvo].astype(str).str.replace(',', '.'), errors='coerce')

# Apenas alunos com nota discursiva válida (>0). Ausência NÃO vira zero.
df_modelo = df[df[coluna_reg_alvo] > 0].copy()
mediana_alvo = df_modelo[coluna_reg_alvo].median()
df_modelo['CLASSE_DESEMPENHO'] = (df_modelo[coluna_reg_alvo] >= mediana_alvo).astype(int)
print(f"Alunos com {coluna_reg_alvo} válida: {len(df_modelo)} | classe >= mediana ({mediana_alvo:.1f})")

# Features = ponderação TCT dos itens (a * (1+b) se acerto)
X_irt = np.zeros((len(df_modelo), len(colunas_q)))
for idx, col in enumerate(colunas_q):
    X_irt[:, idx] = df_modelo[col].values * pesos_irt[col]['a'] * (1 + pesos_irt[col]['b'])

y_classe = df_modelo['CLASSE_DESEMPENHO'].values
y_continua = df_modelo[coluna_reg_alvo].values

# =============================================================================
# 3. REDUÇÃO DE DIMENSIONALIDADE (PCA sobre Matriz TCT-ponderada)
# =============================================================================
print("\n[PCA] Extraindo Componentes Principais da Matriz Ponderada por TCT...")
scaler = StandardScaler()
X_escalado = scaler.fit_transform(X_irt)

pca = PCA(n_components=6, random_state=42)
X_pca = pca.fit_transform(X_escalado)

# =============================================================================
# 4. CLASSIFICAÇÃO (MLP vs AdaBoost vs LightGBM) — alvo externo honesto
# =============================================================================
print("\n--- TREINANDO MODELOS DE CLASSIFICAÇÃO (alvo: classe da nota discursiva) ---")
X_train, X_test, y_train, y_test = train_test_split(X_pca, y_classe, test_size=0.25, random_state=42, stratify=y_classe)

modelos_clf = {
    "Rede Neural (MLP)": MLPClassifier(hidden_layer_sizes=(50, 25), max_iter=300, random_state=42),
    "AdaBoost": AdaBoostClassifier(n_estimators=100, random_state=42)
}
if LGBMClassifier:
    modelos_clf["LightGBM"] = LGBMClassifier(n_estimators=100, learning_rate=0.05, random_state=42, verbose=-1)

resultados_clf = []
for nome, modelo in modelos_clf.items():
    modelo.fit(X_train, y_train)
    preds = modelo.predict(X_test)
    proba = modelo.predict_proba(X_test)[:, 1] if hasattr(modelo, 'predict_proba') else np.nan
    auc = roc_auc_score(y_test, proba) if not np.isscalar(proba) else np.nan
    resultados_clf.append({
        "Modelo": nome,
        "Acurácia": accuracy_score(y_test, preds),
        "Acurácia_Balanceada": balanced_accuracy_score(y_test, preds),
        "AUC_ROC": auc,
    })
    print(f"  -> {nome}: acc {accuracy_score(y_test, preds):.4f} | AUC {auc:.4f}")

pd.DataFrame(resultados_clf).to_csv(pasta_resultados_ml / 'resultado_classificacao.csv', index=False, sep=';', decimal=',')

# =============================================================================
# 5. REGRESSÃO NÃO-LINEAR DA NOTA DISCURSIVA (sem fillna(0))
# =============================================================================
print("\n--- INICIANDO PREVISÃO DA NOTA DISCURSIVA (REGRESSÃO) ---")
X_train_reg, X_test_reg, y_train_reg, y_test_reg = train_test_split(X_pca, y_continua, test_size=0.25, random_state=42)

modelos_reg = {
    "Ridge (Regularização L2)": Ridge(alpha=1.0),
    "Rede Neural Regressora (MLP-R)": MLPRegressor(hidden_layer_sizes=(64, 32), max_iter=500, random_state=42, early_stopping=True),
    "Random Forest Regressor (RFR)": RandomForestRegressor(n_estimators=50, max_depth=10, random_state=42, n_jobs=-1)
}
if LGBMRegressor:
    modelos_reg["LightGBM Regressor"] = LGBMRegressor(n_estimators=100, learning_rate=0.05, random_state=42, verbose=-1)

resultados_reg = []
for nome, modelo in modelos_reg.items():
    print(f"Treinando {nome}...")
    modelo.fit(X_train_reg, y_train_reg)
    preds = modelo.predict(X_test_reg)
    rmse = np.sqrt(mean_squared_error(y_test_reg, preds))
    mae = mean_absolute_error(y_test_reg, preds)
    r2 = r2_score(y_test_reg, preds)
    resultados_reg.append({"Modelo": nome, "RMSE": rmse, "MAE": mae, "R2": r2})
    print(f"  -> {nome}: RMSE {rmse:.2f} | MAE {mae:.2f} | R² {r2:.4f}")

pd.DataFrame(resultados_reg).to_csv(pasta_resultados_ml / 'resultado_regressao.csv', index=False, sep=';', decimal=',')

# =============================================================================
# 6. EXPORTAÇÃO EXPLICATIVA (Importância por Permutação dos itens)
# =============================================================================
print("\nCalculando importância por permutação dos itens (XAI honesta)...")
rf_xai = RandomForestRegressor(n_estimators=50, max_depth=10, random_state=42, n_jobs=-1)
rf_xai.fit(X_train_reg, y_train_reg)
perm_imp = permutation_importance(rf_xai, X_test_reg, y_test_reg, n_repeats=5, random_state=42, n_jobs=-1)
df_importancia = pd.DataFrame({
    "Componente_PCA": [f"PCA_{i + 1}" for i in range(perm_imp.importances_mean.shape[0])],
    "Importancia_Permutacao": perm_imp.importances_mean,
}).sort_values(by="Importancia_Permutacao", ascending=False)
df_importancia.to_csv(pasta_resultados_ml / 'ia_explicativa_shap.csv', index=False, sep=';', decimal=',')

# =============================================================================
# 7. BASE COMPACTADA PARA K-MEANS (com alvo externo)
# =============================================================================
df_final_kmeans = pd.DataFrame(X_pca, columns=[f'PCA_COMP_{i}' for i in range(1, 7)])
df_final_kmeans.insert(0, 'ALUNO', df_modelo['ALUNO'].values)
df_final_kmeans.insert(1, 'CO_GRUPO', df_modelo['CO_GRUPO'].values)
df_final_kmeans.insert(2, 'CO_IES', df_modelo['CO_IES'].values)
df_final_kmeans[coluna_reg_alvo] = df_modelo[coluna_reg_alvo].values
df_final_kmeans['CLASSE_DESEMPENHO'] = df_modelo['CLASSE_DESEMPENHO'].values
df_final_kmeans.to_csv(pasta_resultados_ml / 'microdados_processados_pca.csv', index=False, sep=';', decimal=',')

print("\nPipeline de Fronteira concluído com sucesso! (TCT + modelos com alvo externo)")
