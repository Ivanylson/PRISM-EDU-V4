import pandas as pd
import numpy as np
import time
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.neural_network import MLPClassifier, MLPRegressor
from sklearn.base import BaseEstimator, ClassifierMixin
import xgboost as xgb
import lightgbm as lgb
import warnings

warnings.filterwarnings('ignore')

# =====================================================================
# CONFIGURAÇÃO DE DIRETÓRIOS DO PROJETO
# =====================================================================
DIRETORIO_ATUAL = Path(__file__).resolve().parent
DIRETORIO_RAIZ = DIRETORIO_ATUAL.parent
pasta_resultados_ml = DIRETORIO_RAIZ / 'arquivosgerados' / 'RESULTADOS_FASE6_ML_AVANCADO'
pasta_resultados_ml.mkdir(parents=True, exist_ok=True)

# =====================================================================
# CLASSE HÍBRIDA CUSTOMIZADA (Inspirada no paradigma GrowNet)
# =====================================================================
class HybridNNBoostClassifier(BaseEstimator, ClassifierMixin):
    def __init__(self, n_estimators=6, learning_rate=0.1):
        self.n_estimators = n_estimators
        self.learning_rate = learning_rate
        self.estimators = []
        self.classes_ = np.array([0, 1])
        
    def fit(self, X, y):
        base_nn = MLPClassifier(hidden_layer_sizes=(8,), max_iter=100, random_state=42)
        base_nn.fit(X, y)
        self.estimators.append(base_nn)
        
        y_pred = base_nn.predict_proba(X)[:, 1]
        
        for i in range(self.n_estimators - 1):
            residual = y - y_pred
            weak_nn = MLPRegressor(hidden_layer_sizes=(8,), max_iter=100, random_state=42 + i)
            weak_nn.fit(X, residual)
            self.estimators.append(weak_nn)
            
            y_pred += self.learning_rate * weak_nn.predict(X)
            y_pred = np.clip(y_pred, 0, 1)
            
        return self
        
    def predict_proba(self, X):
        y_pred = self.estimators[0].predict_proba(X)[:, 1]
        for weak_nn in self.estimators[1:]:
            y_pred += self.learning_rate * weak_nn.predict(X)
        y_pred = np.clip(y_pred, 0, 1)
        return np.vstack([1 - y_pred, y_pred]).T
        
    def predict(self, X):
        prob = self.predict_proba(X)[:, 1]
        return (prob >= 0.5).astype(int)

# =====================================================================
# PIPELINE DE BENCHMARKING DE ARQUITETURAS
# =====================================================================
def executar_pipeline_avancado():
    print("=== Módulo de Benchmarking: GBDTs vs DNNs vs Modelos Híbridos ===")
    
    # Busca o arquivo de PCA gerado anteriormente na pasta correta
    caminho_pca = pasta_resultados_ml / "microdados_processados_pca.csv"
    
    try:
        df = pd.read_csv(caminho_pca, sep=";", decimal=",")
        print(f"Arquivo PCA carregado com sucesso: {len(df)} registros encontrados.")
    except FileNotFoundError:
        print(f"ERRO: O arquivo não foi encontrado no caminho: {caminho_pca}")
        print("Certifique-se de que o script de PCA foi executado primeiro.")
        return

    if 'CLASSE_DESEMPENHO' not in df.columns:
        print("ERRO: coluna 'CLASSE_DESEMPENHO' (alvo externo) não encontrada em microdados_processados_pca.csv.")
        print("Execute fase6_machine_learning_avancado.py para gerar o alvo externo honesto.")
        return

    features = ['PCA_COMP_1', 'PCA_COMP_2', 'PCA_COMP_3', 'PCA_COMP_4', 'PCA_COMP_5', 'PCA_COMP_6']
    X = df[features].values

    # ALVO EXTERNO (NT_DIS_CE binarizado na mediana), SEM vazamento:
    # não é derivado dos PCA_COMPs usados como features.
    y = df['CLASSE_DESEMPENHO'].astype(int).values
    print(f"Alvo externo utilizado: classe da nota discursiva (0={int((y==0).sum())}, 1={int((y==1).sum())})")

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
    
    resultados = []
    
    modelos = {
        "XGBoost (GBDT Padrão)": xgb.XGBClassifier(n_estimators=100, learning_rate=0.05, max_depth=4, eval_metric='logloss', random_state=42),
        "LightGBM (GBDT Otimizado)": lgb.LGBMClassifier(n_estimators=100, learning_rate=0.05, max_depth=4, random_state=42, verbose=-1),
        "Deep Neural Network (DNN)": MLPClassifier(hidden_layer_sizes=(64, 32, 16), max_iter=300, random_state=42),
        "Modelo Híbrido (NN-Boost)": HybridNNBoostClassifier(n_estimators=6, learning_rate=0.1)
    }
    
    for nome, modelo in modelos.items():
        print(f"Treinando arquitetura: {nome}...")
        start_time = time.time()
        modelo.fit(X_train, y_train)
        tempo_treino = time.time() - start_time
        
        y_pred = modelo.predict(X_test)
        y_prob = modelo.predict_proba(X_test)[:, 1]
        
        resultados.append({
            "Arquitetura": nome,
            "Acurácia": round(accuracy_score(y_test, y_pred), 4),
            "AUC-ROC": round(roc_auc_score(y_test, y_prob), 4),
            "Custo Computacional (s)": round(tempo_treino, 4)
        })
        
    df_resultados = pd.DataFrame(resultados)
    
    # Salva na mesma pasta dos resultados de ML
    caminho_saida = pasta_resultados_ml / "benchmark_arquiteturas_auc.csv"
    df_resultados.to_csv(caminho_saida, sep=";", index=False)
    
    print(f"\n[Métricas de Avaliação Consolidadas exportadas com sucesso para: {caminho_saida}]")
    print("\n=== TABELA COMPARATIVA DE DESEMPENHO E AVALIAÇÃO AUC ===")
    print(df_resultados.to_string(index=False))

if __name__ == "__main__":
    executar_pipeline_avancado()