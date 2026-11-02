import pandas as pd
import numpy as np
from pathlib import Path
import warnings
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings('ignore')

print("=============================================================================")
print("Módulo Exploratório: Redes Neurais de Kohonen (Self-Organizing Maps)")
print("NOTA: análise exploratória ilustrativa (grelha pequena, amostra). Sem remoção de dados.")
print("=============================================================================")

DIRETORIO_ATUAL = Path(__file__).resolve().parent
DIRETORIO_RAIZ = DIRETORIO_ATUAL.parent

caminho_microdados = DIRETORIO_RAIZ / 'arquivosgerados' / 'relatorio_final_enade_2023.csv'
# Dashboard lê este resultado na pasta de psicometria
pasta_resultados_ml = DIRETORIO_RAIZ / 'arquivosgerados' / 'RESULTADOS_FASE6_ML_AVANCADO_PSICOMETRIA'
pasta_resultados_ml.mkdir(parents=True, exist_ok=True)

# 1. Carregamento (SEM IsolationForest descartando dados)
df = pd.read_csv(caminho_microdados, sep=';', encoding='utf-8', low_memory=False)
if 'TP_PR_GER' in df.columns:
    df = df[df['TP_PR_GER'] > 0].copy()

df.columns = [str(c).strip().upper() for c in df.columns]
colunas_q = [f'Q{i}' for i in range(1, 39)]

for col in colunas_q:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors='coerce').apply(lambda x: 1 if x == 1 else 0)

X_bruto = df[colunas_q].values

# 2. Topologia de Kohonen (SOM) sobre as 38 dimensões cognitivas
print("[SOM] Treinando grelha competitiva de Kohonen (amostra de 5000)...")
rng = np.random.RandomState(42)
amostra_idx = rng.choice(len(X_bruto), size=min(5000, len(X_bruto)), replace=False)

X_escalado = StandardScaler().fit_transform(X_bruto[amostra_idx])

linhas_grelha, colunas_grelha = 3, 3
total_neuronios = linhas_grelha * colunas_grelha

pesos_som = rng.uniform(0.1, 0.9, (total_neuronios, len(colunas_q)))

# Coordenadas 2D de cada neurônio na grelha (para vizinhança topológica)
coords_grelha = np.array([[i, j] for i in range(linhas_grelha) for j in range(colunas_grelha)])

n_epocas = 20
tau = n_epocas / np.log(total_neuronios)

for epoca in range(n_epocas):
    t = epoca
    taxa_aprendizado = 0.3 * np.exp(-t / tau)
    raio_vizinhanca = max(1.0, 3.0 * np.exp(-t / tau))

    ordem = rng.permutation(len(X_escalado))
    for idx in ordem[:2000]:
        amostra = X_escalado[idx]
        distancias = np.linalg.norm(pesos_som - amostra, axis=1)
        bmu_idx = np.argmin(distancias)

        dist_bmu = np.linalg.norm(coords_grelha - coords_grelha[bmu_idx], axis=1)
        vizinhos = dist_bmu <= raio_vizinhanca
        influencia = np.exp(-dist_bmu ** 2 / (2 * raio_vizinhanca ** 2))
        pesos_som[vizinhos] += taxa_aprendizado * influencia[vizinhos, None] * (amostra - pesos_som[vizinhos])

print("Rede Neural SOM concluída (análise exploratória).")

# 3. Exportação das Propriedades Topológicas para o Dashboard
ativacao_questoes = np.mean(np.abs(pesos_som), axis=0)

df_som = pd.DataFrame({
    "Questao": colunas_q,
    "Ativacao_Topologica": ativacao_questoes
}).sort_values(by="Ativacao_Topologica", ascending=False)

df_som.to_csv(pasta_resultados_ml / 'resultado_som_kohonen.csv', index=False, sep=';', decimal=',')
print(f"Arquivo de topologia de rede salvo em: {pasta_resultados_ml / 'resultado_som_kohonen.csv'}")
