import pandas as pd
import numpy as np
from pathlib import Path
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.multioutput import MultiOutputClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import hamming_loss, accuracy_score
import warnings

warnings.filterwarnings('ignore')

print("=============================================================================")
print("Módulo Corrigido: NLP Educacional (TF-IDF sobre Cadeias de Acertos)")
print("Avaliação HONESTA em split treino/teste (não mede mais no treino)")
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

# Alunos com as duas notas discursivas VÁLIDAS (>0) — ausência não vira 0.
multirrotulos_alvo = ['NT_FG_D1_PT', 'NT_FG_D_CT']
for col in multirrotulos_alvo:
    df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', '.'), errors='coerce')
df_modelo = df[df[multirrotulos_alvo].notna().all(axis=1)].copy()
df_modelo = df_modelo[(df_modelo[multirrotulos_alvo] > 0).all(axis=1)]

# Subamostragem aleatória (reprodutível) para viabilidade computacional
df_amostra = df_modelo.sample(n=min(5000, len(df_modelo)), random_state=42)
print(f"Amostra de modelagem: {len(df_amostra)} alunos (notas discursivas válidas)")

print("[NLP] Transformando a matriz de respostas em documentos textuais (ACERTO/ERRO)...")
df_amostra['CORPUS_RESPOSTAS'] = df_amostra[colunas_q].astype(str).agg(' '.join, axis=1)

vectorizer = TfidfVectorizer(ngram_range=(1, 3), max_features=100,
                             token_pattern=r'\b\w+\b')
X_tfidf = vectorizer.fit_transform(df_amostra['CORPUS_RESPOSTAS']).toarray()

# Multirrótulo: nota acima da mediana (calculada sobre valores válidos) em cada discursiva
y_multi = np.zeros((len(df_amostra), len(multirrotulos_alvo)))
for idx, col in enumerate(multirrotulos_alvo):
    mediana_alvo = df_amostra[col].median()
    y_multi[:, idx] = (df_amostra[col].values >= mediana_alvo).astype(int)

print("[ML-RÓTULO] Classificação multirrótulo com split treino/teste (70/30)...")
X_train, X_test, y_train, y_test = train_test_split(X_tfidf, y_multi, test_size=0.3, random_state=42)

clf_multitask = MultiOutputClassifier(RandomForestClassifier(n_estimators=30, random_state=42), n_jobs=-1)
clf_multitask.fit(X_train, y_train)
preds_multi = clf_multitask.predict(X_test)

perda_hamming = hamming_loss(y_test, preds_multi)
acuracia_por_alvo = [accuracy_score(y_test[:, i], preds_multi[:, i]) for i in range(len(multirrotulos_alvo))]
print(f"NLP Multirrótulo (TESTE) | Hamming Loss: {perda_hamming:.4f}")

df_nlp = pd.DataFrame([
    {"Métrica": "Hamming Loss (split de teste)", "Valor": round(perda_hamming, 4)},
    {"Métrica": f"Acurácia {multirrotulos_alvo[0]} (teste)", "Valor": round(acuracia_por_alvo[0], 4)},
    {"Métrica": f"Acurácia {multirrotulos_alvo[1]} (teste)", "Valor": round(acuracia_por_alvo[1], 4)},
])
df_nlp.to_csv(pasta_resultados / 'resultado_nlp_multilabel.csv', index=False, sep=';', decimal=',')
print("Salvo: resultado_nlp_multilabel.csv (avaliação em conjunto de teste)")
