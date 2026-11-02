import pandas as pd
import numpy as np
from pathlib import Path
import warnings

from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.ensemble import AdaBoostClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.linear_model import Ridge, Lasso, ElasticNet
from sklearn.metrics import (accuracy_score, balanced_accuracy_score, precision_score,
                             recall_score, f1_score, roc_auc_score, mean_squared_error,
                             mean_absolute_error, r2_score)
from sklearn.inspection import permutation_importance

try:
    from lightgbm import LGBMClassifier
except ImportError:
    LGBMClassifier = None

try:
    import shap
    SHAP_DISPONIVEL = True
except ImportError:
    SHAP_DISPONIVEL = False

warnings.filterwarnings('ignore')

# =============================================================================
# 1. CONFIGURAÇÕES DE CAMINHOS
# =============================================================================
print("Inicializando Fase 6 Avançada: Machine Learning sob Medida (Métricas Honestas)...")

DIRETORIO_ATUAL = Path(__file__).resolve().parent
DIRETORIO_RAIZ = DIRETORIO_ATUAL.parent

caminho_microdados = DIRETORIO_RAIZ / 'arquivosgerados' / 'relatorio_final_enade_2023.csv'
pasta_resultados_ml = DIRETORIO_RAIZ / 'arquivosgerados' / 'RESULTADOS_FASE6_ML_AVANCADO'
pasta_resultados_ml.mkdir(parents=True, exist_ok=True)

# =============================================================================
# 2. CARREGAMENTO E ENGENHARIA DE VARIÁVEIS
# =============================================================================
print("\nCarregando microdados...")
df = pd.read_csv(caminho_microdados, sep=';', encoding='utf-8', low_memory=False)
if 'TP_PR_GER' in df.columns:
    df = df[df['TP_PR_GER'] > 0].copy()

df.columns = [str(c).strip().upper() for c in df.columns]
colunas_q = [f'Q{i}' for i in range(1, 39)]

for col in colunas_q:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors='coerce').apply(lambda x: 1 if x == 1 else 0)
    else:
        df[col] = 0

print("Processando respostas objetivas (Q1 a Q38)...")

# --- ALVO EXTERNO (SEM VAZAMENTO) ---
# Classificação e regressão predizem o desempenho NA DISCURSIVA (NT_DIS_CE),
# que NÃO é derivado das respostas objetivas Q1-Q38 usadas como features.
coluna_reg_alvo = 'NT_DIS_CE' if 'NT_DIS_CE' in df.columns else 'NT_CE_D1'
df[coluna_reg_alvo] = pd.to_numeric(df[coluna_reg_alvo].astype(str).str.replace(',', '.'), errors='coerce')

# Apenas alunos com nota discursiva válida (>0). Ausência NÃO é tratada como zero.
df_modelo = df[df[coluna_reg_alvo] > 0].copy()
print(f"Alunos com {coluna_reg_alvo} válida (>0): {len(df_modelo)}")

mediana_alvo = df_modelo[coluna_reg_alvo].median()
df_modelo['CLASSE_DESEMPENHO'] = (df_modelo[coluna_reg_alvo] >= mediana_alvo).astype(int)
print(f"Classe binária (>= mediana {mediana_alvo:.1f}): 0={int((df_modelo['CLASSE_DESEMPENHO']==0).sum())}, "
      f"1={int((df_modelo['CLASSE_DESEMPENHO']==1).sum())}")

X_questoes = df_modelo[colunas_q].values
y_classe = df_modelo['CLASSE_DESEMPENHO'].values
y_continua = df_modelo[coluna_reg_alvo].values

# =============================================================================
# 3. REDUÇÃO DE DIMENSIONALIDADE (PCA) — só para os modelos de classificação/regressão
# =============================================================================
print("\n[PCA] Reduzindo as 38 dimensões para Componentes Principais...")
scaler = StandardScaler()
X_escalado = scaler.fit_transform(X_questoes)

pca = PCA(n_components=6, random_state=42)
X_pca = pca.fit_transform(X_escalado)

variancia_explicada = np.sum(pca.explained_variance_ratio_) * 100
print(f"PCA Concluído. 6 componentes explicam {variancia_explicada:.2f}% da variância coletiva.")

# =============================================================================
# 4. SPLIT ESTRATIFICADO HONESTO (sem IsolationForest removendo dados)
# =============================================================================
X_train, X_test, y_train, y_test = train_test_split(
    X_pca, y_classe, test_size=0.25, random_state=42, stratify=y_classe)
print(f"Treino: {len(X_train)} | Teste: {len(X_test)}")

# =============================================================================
# 5. BATALHA DE CLASSIFICAÇÃO (MLP, AdaBoost, LightGBM)
# =============================================================================
print("\n--- INICIANDO BATALHA DE MODELOS DE CLASSIFICAÇÃO (alvo externo: discursiva) ---")

modelos_clf = {
    "Rede Neural (MLP)": MLPClassifier(hidden_layer_sizes=(50, 25), max_iter=300, random_state=42),
    "AdaBoost": AdaBoostClassifier(n_estimators=100, random_state=42)
}

if LGBMClassifier:
    modelos_clf["LightGBM"] = LGBMClassifier(n_estimators=100, learning_rate=0.05, random_state=42, verbose=-1)

resultados_clf = []

for nome, modelo in modelos_clf.items():
    print(f"Treinando {nome}...")
    modelo.fit(X_train, y_train)
    preds = modelo.predict(X_test)
    if hasattr(modelo, 'predict_proba'):
        proba = modelo.predict_proba(X_test)[:, 1]
        auc = roc_auc_score(y_test, proba)
    else:
        auc = np.nan
    resultados_clf.append({
        "Modelo": nome,
        "Acurácia": accuracy_score(y_test, preds),
        "Acurácia_Balanceada": balanced_accuracy_score(y_test, preds),
        "Precision": precision_score(y_test, preds),
        "Recall": recall_score(y_test, preds),
        "F1": f1_score(y_test, preds),
        "AUC_ROC": auc
    })
    print(f"  -> Acurácia: {accuracy_score(y_test, preds):.4f} | AUC-ROC: {auc:.4f}")

df_res_clf = pd.DataFrame(resultados_clf)
df_res_clf.to_csv(pasta_resultados_ml / 'resultado_classificacao.csv', index=False, sep=';', decimal=',')
print(f"Salvo: resultado_classificacao.csv")

# =============================================================================
# 6. IA EXPLICATIVA (XAI) REAL — SHAP sobre LightGBM nas 38 questões
# =============================================================================
print("\n--- APLICANDO IA EXPLICATIVA (SHAP REAL / Permutação) ---")

df_importancia = None
X_ques_train, X_ques_test, y_ques_train, y_ques_test = train_test_split(
    X_questoes, y_classe, test_size=0.25, random_state=42, stratify=y_classe)

modelo_lgb_xai = None
if LGBMClassifier:
    modelo_lgb_xai = LGBMClassifier(n_estimators=100, learning_rate=0.05, random_state=42, verbose=-1)
    modelo_lgb_xai.fit(X_ques_train, y_ques_train)
else:
    modelo_lgb_xai = AdaBoostClassifier(n_estimators=100, random_state=42)
    modelo_lgb_xai.fit(X_ques_train, y_ques_train)

# Importância por permutação (sempre calculada, método honesto e estável)
print("Calculando importância por permutação no conjunto de teste...")
perm_imp = permutation_importance(modelo_lgb_xai, X_ques_test, y_ques_test,
                                  n_repeats=5, random_state=42, n_jobs=-1)
importancia_perm = perm_imp.importances_mean

# SHAP real (se disponível), restrito a uma amostra para viabilidade
importancia_shap = np.full(len(colunas_q), np.nan)
if SHAP_DISPONIVEL and LGBMClassifier:
    try:
        print("Calculando SHAP (TreeExplainer) em amostra de 2000 alunos...")
        rng = np.random.RandomState(42)
        idx_amostra = rng.choice(len(X_ques_test), size=min(2000, len(X_ques_test)), replace=False)
        X_shap_sample = X_ques_test[idx_amostra]
        explainer = shap.TreeExplainer(modelo_lgb_xai, feature_perturbation='tree_path_dependent')
        shap_values = explainer.shap_values(X_shap_sample)
        if isinstance(shap_values, list):
            shap_values = shap_values[1] if len(shap_values) > 1 else shap_values[0]
        importancia_shap = np.abs(shap_values).mean(axis=0)
        print("SHAP concluído com sucesso.")
    except Exception as e:
        print(f"[AVISO] SHAP falhou ({e}); usando apenas importância por permutação.")

df_importancia = pd.DataFrame({
    "Questao": colunas_q,
    "Importancia_SHAP_media_abs": importancia_shap,
    "Importancia_Permutacao": importancia_perm
}).sort_values(by="Importancia_Permutacao", ascending=False)
df_importancia.to_csv(pasta_resultados_ml / 'ia_explicativa_shap.csv', index=False, sep=';', decimal=',')
print(f"Salvo: ia_explicativa_shap.csv (XAI honesta: SHAP real + permutação)")

# =============================================================================
# 7. REGRESSÃO AVANÇADA (Ridge, Lasso, ElasticNet) — só notas válidas, sem fillna(0)
# =============================================================================
print("\n--- INICIANDO PREVISÃO DA NOTA DISCURSIVA (REGRESSÃO) ---")
X_train_reg, X_test_reg, y_train_reg, y_test_reg = train_test_split(
    X_pca, y_continua, test_size=0.25, random_state=42)

modelos_reg = {
    "Ridge Regression": Ridge(alpha=1.0),
    "Lasso Regression": Lasso(alpha=0.1),
    "ElasticNet": ElasticNet(alpha=0.1, l1_ratio=0.5)
}

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

df_res_reg = pd.DataFrame(resultados_reg)
df_res_reg.to_csv(pasta_resultados_ml / 'resultado_regressao.csv', index=False, sep=';', decimal=',')

# =============================================================================
# 8. EXPORTAÇÃO DO DATASET COMPACTADO (PCA + alvo externo) PARA K-MEANS / BOOSTING
# =============================================================================
df_final_kmeans = pd.DataFrame(X_pca, columns=[f'PCA_COMP_{i}' for i in range(1, 7)])
df_final_kmeans.insert(0, 'ALUNO', df_modelo['ALUNO'].values)
df_final_kmeans.insert(1, 'CO_GRUPO', df_modelo['CO_GRUPO'].values)
df_final_kmeans.insert(2, 'CO_IES', df_modelo['CO_IES'].values)
df_final_kmeans['NT_DIS_CE'] = df_modelo[coluna_reg_alvo].values
df_final_kmeans['CLASSE_DESEMPENHO'] = df_modelo['CLASSE_DESEMPENHO'].values
df_final_kmeans.to_csv(pasta_resultados_ml / 'microdados_processados_pca.csv', index=False, sep=';', decimal=',')

print(f"\n=============================================================================")
print(f"Pipeline honesto executado! Artefatos salvos em:\n{pasta_resultados_ml}")
print(f"Nota: NENHUM alvo é derivado das questões Q1-Q38 (sem vazamento de dados).")
print(f"=============================================================================")
