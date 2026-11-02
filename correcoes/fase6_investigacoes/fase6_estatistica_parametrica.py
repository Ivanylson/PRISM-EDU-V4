import pandas as pd
import numpy as np
from pathlib import Path
import scipy.stats as stats
import warnings

warnings.filterwarnings('ignore')

print("=============================================================================")
print("Módulo Avançado: Estatística Paramétrica (ANOVA, p-Valor formatado e Eta-Quadrado)")
print("=============================================================================")

DIRETORIO_ATUAL = Path(__file__).resolve().parent
DIRETORIO_RAIZ = DIRETORIO_ATUAL.parent
caminho_microdados = DIRETORIO_RAIZ / 'arquivosgerados' / 'relatorio_final_enade_2023.csv'
pasta_resultados = DIRETORIO_RAIZ / 'arquivosgerados' / 'RESULTADOS_FASE6_ML_AVANCADO'
pasta_resultados.mkdir(parents=True, exist_ok=True)

try:
    df = pd.read_csv(caminho_microdados, sep=';', encoding='utf-8', low_memory=False)
    df = df[df['TP_PR_GER'] > 0].copy()
except Exception as e:
    print(f"Erro ao ler microdados: {e}")
    exit()

df.columns = [str(c).strip().upper() for c in df.columns]

# Tratamento estrito de tipos para as notas existentes.
# NOTA: ausência permanece NaN (não é transformada em zero) — alunos sem nota
# são removidos nas análises abaixo via filtros explícitos de validade (>0).
notas_existentes = ['NT_FG_D1', 'NT_DIS_CE', 'NT_CE_D1']
for col in notas_existentes:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', '.'), errors='coerce')

# =============================================================================
# 1. ANOVA Unidirecional com Correção Científica (Eta-Quadrado)
# =============================================================================
print("[ANOVA] Calculando variância e Tamanho do Efeito (Eta-Quadrado) para as Regiões...")
if 'CO_REGIAO_CURSO' in df.columns and 'NT_DIS_CE' in df.columns:
    
    # Limpar zeros e nulos para não sujar a média regional
    df_anova_clean = df[df['NT_DIS_CE'] > 0]
    
    grupos = [comportamento['NT_DIS_CE'].values for nome, comportamento in df_anova_clean.groupby('CO_REGIAO_CURSO')]
    
    # Validação contra grupos vazios
    grupos = [g for g in grupos if len(g) > 0]
    
    k = len(grupos) # Número de regiões
    N = sum(len(g) for g in grupos) # Número total de alunos válidos
    
    if k > 1:
        f_stat, p_val = stats.f_oneway(*grupos)
        
        # Cálculo do Eta-Quadrado a partir do F-Statistic
        df_between = k - 1
        df_within = N - k
        eta_squared = (f_stat * df_between) / ((f_stat * df_between) + df_within)
        
        # Formatação Padrão APA para o p-valor
        p_val_formatado = "< 0.001" if p_val < 0.001 else f"{p_val:.4f}"
        
    else:
        f_stat, p_val_formatado, eta_squared = 0, "N/A", 0

    df_res_anova = pd.DataFrame([{
        "Variável_Independente": "CO_REGIAO_CURSO",
        "Variável_Dependente": "NT_DIS_CE",
        "F-Statistic": round(f_stat, 2),
        "p-Value": p_val_formatado,
        "Eta-Quadrado (Tamanho Efeito)": round(eta_squared, 4)
    }])
    
    df_res_anova.to_csv(pasta_resultados / 'resultado_estatistica_anova.csv', index=False, sep=';')
    print(f"ANOVA concluída! p-Value: {p_val_formatado} | Eta-Quadrado: {eta_squared:.4f}")

# =============================================================================
# 2. Matrizes de Correlação Real (Pearson vs Spearman)
# =============================================================================
print("[CORRELAÇÃO] Computando Matrizes lineares e não-lineares das notas...")
# Garantir que só correlaciona alunos que efetivamente tiraram notas
df_corr_clean = df[(df[notas_existentes] > 0).all(axis=1)][notas_existentes]

if len(df_corr_clean) > 0:
    corr_pearson = df_corr_clean.corr(method='pearson')
    corr_spearman = df_corr_clean.corr(method='spearman')
    
    corr_pearson.to_csv(pasta_resultados / 'corr_pearson.csv', sep=';')
    corr_spearman.to_csv(pasta_resultados / 'corr_spearman.csv', sep=';')
    print("Matrizes de correlação salvas com sucesso.")
else:
    print("Dados insuficientes para gerar correlações válidas (removendo zeros absolutos).")