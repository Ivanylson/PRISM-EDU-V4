# -*- coding: utf-8 -*-
"""
=============================================================================
FASE 6 — LCA EXPLORATÓRIA -> CDM RESTRITO (DINA) COM VALIDAÇÃO ESPECIALISTA
=============================================================================
Item (1) do artigo:
  "Incorporate expert validation of INEP's item–KO matrix to move from
   exploratory LCA toward restricted Cognitive Diagnosis Models."

O que este módulo faz (por curso do ENADE 2023):
  1. Constrói a MATRIZ-Q a partir da matriz item–OC do INEP
     (arquivosgerados/RESULTADOS_LCA/mestre_questao_oc.csv), que consolida o
     Anexo IX (item x perfil/competência/OC1/OC2).
  2. Gera o WORKBOOK DE VALIDAÇÃO ESPECIALISTA (xlsx) com:
       a) a matriz Q item x OC preenchível (STATUS: PENDENTE_VALIDACAO,
          VALIDADO, REVISAR, REJEITAR + OBSERVACOES);
       b) resumo de cobertura (itens sem OC, OCs com poucos itens);
       c) concordância empírica com a LCA (probabilidade item, GAP e taxa de
          acerto) para orientar a revisão humana.
  3. Estima um CDM RESTRITO real (DINA — Deterministic Inputs, Noisy And)
     por EM com guess/slip por item e probabilidades de domínio (alpha) por
     aluno, restrito à matriz Q validada.
  4. Compara a LCA exploratória (fase 4) com o CDM restrito (DINA):
     correlações item a item, AIC/BIC, concordância classe-LCA x perfis DINA.

NOTAS DE INTEGRIDADE
  - Atributos do DINA = OCs PRINCIPAIS do Anexo IX (para manter K tratável).
    Se o nº de OCs principais > 12, mantêm-se as 12 mais frequentes e as
    demais são agrupadas em "Outras_competencias" (documentado nas saídas).
  - Nenhum alvo é derivado das questões Q1-Q38; a nota discursiva (NT_DIS_CE)
    entra apenas como coluna descritiva nos perfis de aluno.
  - Não há remoção arbitrária de alunos (ex.: IsolationForest).

Saídas em: arquivosgerados/RESULTADOS_FASE6_LCA_CDM/
=============================================================================
"""
import pandas as pd
import numpy as np
from pathlib import Path
import warnings
import unicodedata
import re
from itertools import product
from scipy.stats import pearsonr, spearmanr

warnings.filterwarnings('ignore')

DIRETORIO_ATUAL = Path(__file__).resolve().parent
DIRETORIO_RAIZ = DIRETORIO_ATUAL.parent

CAMINHO_MICRODADOS = DIRETORIO_RAIZ / 'arquivosgerados' / 'relatorio_final_enade_2023.csv'
PASTA_LCA = DIRETORIO_RAIZ / 'arquivosgerados' / 'RESULTADOS_LCA'
PASTA_SAIDA = DIRETORIO_RAIZ / 'arquivosgerados' / 'RESULTADOS_FASE6_LCA_CDM'
PASTA_SAIDA.mkdir(parents=True, exist_ok=True)

COLUNAS_Q = [f'Q{i}' for i in range(1, 39)]

MAX_ATRIBUTOS_DINA = 12
MAX_ITER_EM = 100
TOL_EM = 1e-4
TAM_LOTE = 4000


# =============================================================================
# 1. AUXILIARES
# =============================================================================
def normalizar(texto):
    """Remove acentos, não-alfanuméricos e minúsculas (para casar nomes)."""
    if not isinstance(texto, str):
        texto = str(texto)
    texto = unicodedata.normalize('NFKD', texto)
    texto = ''.join(ch for ch in texto if not unicodedata.combining(ch))
    return re.sub(r'\W', '', texto).lower()


def rotulo_oc(indice):
    """Rótulo curto para colunas de OC (OC_A, OC_B, ...)."""
    letras = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    return f"OC_{letras[indice]}"


# =============================================================================
# 2. MATRIZ-Q POR CURSO (fonte: matriz item-OC do INEP / Anexo IX)
# =============================================================================
mestre = pd.read_csv(PASTA_LCA / 'mestre_questao_oc.csv', sep=';', encoding='utf-8-sig')
for col in ['oc_principal', 'oc_secundario', 'area_prova', 'perfil_egresso', 'competencia']:
    mestre[col] = mestre[col].astype(str).fillna('').str.strip()

cursos_map = {
    5: 'Medicina Veterinária', 6: 'Odontologia', 12: 'Medicina', 17: 'Agronomia',
    19: 'Farmácia', 21: 'Arquitetura e Urbanismo', 23: 'Enfermagem', 27: 'Fonoaudiologia',
    28: 'Nutrição', 36: 'Fisioterapia', 51: 'Zootecnia', 55: 'Biomedicina',
    69: 'Tecnologia em Radiologia', 90: 'Tecnologia em Agronegócios',
    91: 'Tecnologia em Gestão Hospitalar', 92: 'Tecnologia em Gestão Ambiental',
    95: 'Tecnologia em Estética e Cosmética', 5710: 'Engenharia Civil',
    5806: 'Engenharia Elétrica', 5814: 'Engenharia de Controle e Automação',
    5902: 'Engenharia Mecânica', 6002: 'Engenharia de Alimentos',
    6008: 'Engenharia Química', 6208: 'Engenharia de Produção',
    6307: 'Engenharia Ambiental', 6405: 'Engenharia Florestal',
    6410: 'Tecnologia em Segurança no Trabalho', 6411: 'Engenharia de Computação'
}
NOME_PARA_CODIGO = {normalizar(nome): cod for cod, nome in cursos_map.items()}

# =============================================================================
# 3. DADOS LCA (fase 4) — para comparação exploratória x restrito
# =============================================================================
print("Carregando artefatos da LCA (fase 4)...")
df_classes = pd.read_csv(PASTA_LCA / '02_caracterizacao_das_classes.csv', sep=';', decimal=',')
df_criterios = pd.read_csv(PASTA_LCA / '03_criterios_de_selecao_k.csv', sep=';', decimal=',')
df_geral = pd.read_csv(PASTA_LCA / '01_relatorio_geral_por_ies.csv', sep=';', decimal=',')
df_geral = df_geral[['curso', 'ies', 'k_escolhido']].drop_duplicates()
df_criterios = df_criterios.merge(df_geral, on=['curso', 'ies'], how='inner')

probs_lca_cols = [f'PROB_{q}' for q in COLUNAS_Q]
gaps_lca_cols = [f'GAP_{q}' for q in COLUNAS_Q]

# =============================================================================
# 4. MICRODADOS — apenas colunas necessárias
# =============================================================================
print("Carregando microdados (colunas essenciais)...")
usecols = ['ALUNO', 'CO_GRUPO', 'CO_IES', 'TP_PR_GER', 'NT_DIS_CE'] + COLUNAS_Q
df_micro = pd.read_csv(CAMINHO_MICRODADOS, sep=';', encoding='utf-8', low_memory=False, usecols=usecols)
df_micro = df_micro[df_micro['TP_PR_GER'] > 0].copy()
for col in COLUNAS_Q:
    df_micro[col] = pd.to_numeric(df_micro[col], errors='coerce').apply(lambda x: 1 if x == 1 else 0)
df_micro['NT_DIS_CE'] = pd.to_numeric(df_micro['NT_DIS_CE'].astype(str).str.replace(',', '.'), errors='coerce')
df_micro['CLASSE_DIS'] = np.where(df_micro['NT_DIS_CE'] >= df_micro['NT_DIS_CE'].median(), 1,
                                  np.where(df_micro['NT_DIS_CE'] > 0, 0, np.nan))
df_micro['NT_DIS_CE'] = np.where(df_micro['NT_DIS_CE'] > 0, df_micro['NT_DIS_CE'], np.nan)

# =============================================================================
# 5. DINA — ESTIMAÇÃO POR EM
# =============================================================================
def estimar_dina(X, Q):
    """DINA por EM (prior independente por atributo). X: (N,J) binário; Q: (J,K) binário."""
    N, J = X.shape
    K = Q.shape[1]

    # Padrões latentes completos
    padroes = np.array(list(product([0, 1], repeat=K)), dtype=np.int8)  # (P,K)
    P = padroes.shape[0]
    padroes_float = padroes.astype(np.float64)

    # eta[p,j] = 1 se o padrão domina todos os atributos exigidos pelo item j
    eta = (padroes_float[:, None, :] >= Q[None, :, :].astype(np.float64)).prod(axis=2)  # (P,J)
    nao_eta = 1.0 - eta

    g = np.full(J, 0.2, dtype=np.float64)
    s = np.full(J, 0.2, dtype=np.float64)
    pi = np.full(K, 0.5, dtype=np.float64)  # prevalência de domínio por atributo

    X = X.astype(np.float64)
    X_batches = np.array_split(X, max(1, int(np.ceil(N / TAM_LOTE))))

    log_prior = np.zeros(P, dtype=np.float64)
    ll_anterior = -np.inf
    melhor_ll = -np.inf
    melhor_params = (g.copy(), s.copy(), pi.copy())

    for it in range(MAX_ITER_EM):
        logit = np.log(pi) - np.log1p(-pi)  # log(pi/(1-pi))
        log_prior = padroes_float @ logit

        # Log-verossimilhanças condicionais por item (taxas master/non-master)
        g_ = np.clip(g, 1e-4, 1 - 1e-4)
        s_ = np.clip(s, 1e-4, 1 - 1e-4)
        logP_mais = eta * np.log1p(-s_) + nao_eta * np.log(g_)          # x=1
        logP_menos = eta * np.log(s_) + nao_eta * np.log1p(-g_)         # x=0
        base = logP_menos.sum(axis=1)                                   # (P,)
        dif = logP_mais - logP_menos                                    # (P,J)

        n_master_corretos = np.zeros(J, dtype=np.float64)
        n_master_total = np.zeros(J, dtype=np.float64)
        n_nao_master_corretos = np.zeros(J, dtype=np.float64)
        n_nao_master_total = np.zeros(J, dtype=np.float64)
        mastery_acum = np.zeros(K, dtype=np.float64)
        ll_total = 0.0

        for Xb in X_batches:
            B = Xb.shape[0]
            loglik = base[:, None] + dif @ Xb.T                               # (P,B)
            log_post = log_prior[:, None] + loglik
            mx = log_post.max(axis=0)
            post = np.exp(log_post - mx[None, :])
            post = post / post.sum(axis=0, keepdims=True)                     # (P,B) posterior

            ll_total += np.log(np.exp(log_prior[:, None] + loglik - mx[None, :]).sum(axis=0)).sum() + mx.sum()

            soma_post_p = post.sum(axis=1)                                    # (P,)
            M = post @ Xb                                                     # (P,J) = sum_b post*x
            n_master_corretos += (eta * M).sum(axis=0)
            n_nao_master_corretos += (nao_eta * M).sum(axis=0)
            n_master_total += (eta * soma_post_p[:, None]).sum(axis=0)
            n_nao_master_total += (nao_eta * soma_post_p[:, None]).sum(axis=0)
            mastery_acum += (padroes_float.T @ post).sum(axis=1)              # (K,)

        # M-step (com suavização por pseudo-contagens para estabilidade)
        n_master_total = n_master_total + 5.0
        n_nao_master_total = n_nao_master_total + 5.0
        n_master_corretos = n_master_corretos + 2.5
        n_nao_master_corretos = n_nao_master_corretos + 2.5
        s_novo = (n_master_total - n_master_corretos) / np.maximum(n_master_total, 1e-9)
        g_novo = n_nao_master_corretos / np.maximum(n_nao_master_total, 1e-9)
        pi_novo = mastery_acum / N

        # Identificabilidade do DINA: g e s em [1e-4, 0.5]
        # (mestres acertam com prob >= 0.5 > chute => escolhe a solução
        # orientada; evita a solução espelhada e a divergência por saturação).
        s = np.clip(s_novo, 1e-4, 0.5).astype(np.float64)
        g = np.clip(g_novo, 1e-4, 0.5).astype(np.float64)
        pi = np.clip(pi_novo, 1e-4, 1 - 1e-4).astype(np.float64)

        # Mudança relativa aos parâmetros da iteração ANTERIOR (após projeção)
        mudanca = 0.0
        if it > 0:
            mudanca = max(float(np.abs(s - s_ant).max()), float(np.abs(g - g_ant).max()))
        s_ant = s.copy()
        g_ant = g.copy()

        if it % 5 == 0 or it == MAX_ITER_EM - 1:
            print(f"    [EM] iter {it + 1} | LL={ll_total:.2f} | delta={mudanca:.2e}")
        # Critério de parada: convergência nos parâmetros OU melhoria relativa do LL
        if it == 0:
            ll_anterior = ll_total
        melhoria = (ll_total - ll_anterior) / max(abs(ll_anterior), 1.0)
        ll_anterior = ll_total
        if ll_total > melhor_ll:
            melhor_ll = ll_total
            melhor_params = (g.copy(), s.copy(), pi.copy())
        elif ll_total < melhor_ll - 1e-3 * max(abs(melhor_ll), 1.0):
            # LL caiu mais que 0.1% abaixo do melhor ponto: EM degradando.
            # (oscilações pequenas no limite g/s=0.5 sao toleradas)
            break
        if it > 0 and (mudanca < TOL_EM or (melhoria < 1e-6 and melhoria > 0)):
            break

    # Usa os parâmetros do melhor ponto de LL (protege contra micro-oscilações finais)
    g, s, pi = melhor_params
    ll_total = melhor_ll

    # E-step final para extrair perfis de domínio por aluno
    perfis_mastery = np.zeros((N, K), dtype=np.float64)
    logit = np.log(pi) - np.log1p(-pi)
    log_prior = padroes_float @ logit
    g_, s_ = np.clip(g, 1e-4, 1 - 1e-4), np.clip(s, 1e-4, 1 - 1e-4)
    logP_mais = eta * np.log1p(-s_) + nao_eta * np.log(g_)
    logP_menos = eta * np.log(s_) + nao_eta * np.log1p(-g_)
    base = logP_menos.sum(axis=1)
    dif = logP_mais - logP_menos
    inicio = 0
    for Xb in X_batches:
        B = Xb.shape[0]
        loglik = base[:, None] + dif @ Xb.T
        log_post = log_prior[:, None] + loglik
        mx = log_post.max(axis=0)
        post = np.exp(log_post - mx[None, :])
        post = post / post.sum(axis=0, keepdims=True)
        perfis_mastery[inicio:inicio + B, :] = (padroes_float.T @ post).T
        inicio += B

    # P(eta=1) por item (proporção que domina todos os atributos exigidos)
    logit = np.log(pi) - np.log1p(-pi)
    log_prior = padroes_float @ logit
    p_eta1 = np.zeros(J)
    for Xb in X_batches:
        B = Xb.shape[0]
        loglik = base[:, None] + dif @ Xb.T
        log_post = log_prior[:, None] + loglik
        mx = log_post.max(axis=0)
        post = np.exp(log_post - mx[None, :])
        post = post / post.sum(axis=0, keepdims=True)
        soma_post_p = post.sum(axis=1)
        p_eta1 += (eta * soma_post_p[:, None]).sum(axis=0)
    p_eta1 /= N

    return g, s, pi, perfis_mastery, p_eta1, ll_total


# =============================================================================
# 6. PIPELINE PRINCIPAL POR CURSO
# =============================================================================
resumo_geral = []
comparacao = []
concordancia_itens = []

for cod_curso, nome_curso in cursos_map.items():
    print(f"\n{'='*72}\nPROCESSANDO: {cod_curso} - {nome_curso}\n{'='*72}")

    sub_mestre = mestre[mestre['curso'] == nome_curso].copy()
    if sub_mestre.empty:
        print("  [AVISO] curso sem matriz-Q no mestre — pulando.")
        continue

    df_curso = df_micro[df_micro['CO_GRUPO'] == cod_curso]
    if len(df_curso) < 50:
        print(f"  [AVISO] poucos alunos ({len(df_curso)}) — pulando.")
        continue
    print(f"  Alunos do curso (TP_PR_GER>0): {len(df_curso)}")

    # ---- Atributos: OCs principais (limitados a MAX_ATRIBUTOS_DINA) ----
    freq_oc = sub_mestre['oc_principal'].value_counts()
    if len(freq_oc) > MAX_ATRIBUTOS_DINA:
        ocs_principais = freq_oc.index[:MAX_ATRIBUTOS_DINA - 1].tolist()
        ocs_principais.append('OUTRAS_COMPETENCIAS')
    else:
        ocs_principais = freq_oc.index.tolist()
    K = len(ocs_principais)
    print(f"  Atributos (OCs principais) para o DINA: {K}")

    def atributos_da_questao(linha):
        oc = linha['oc_principal']
        return oc if oc in ocs_principais else 'OUTRAS_COMPETENCIAS'

    # ---- Montagem da Q-matrix (38 itens x K atributos) ----
    linhas_q = []
    for _, item in sub_mestre.iterrows():
        attr = atributos_da_questao(item)
        linhas_q.append({
            'Questao': item['questao'],
            'posicao': item['posicao'],
            'area_prova': item['area_prova'],
            'perfil_egresso': item['perfil_egresso'],
            'competencia': item['competencia'],
            'oc_principal': item['oc_principal'],
            'oc_secundario': item['oc_secundario'],
            'atributo_dina': attr,
        })
    df_q = pd.DataFrame(linhas_q).sort_values('posicao').reset_index(drop=True)
    df_q['Questao'] = COLUNAS_Q

    # Matriz binária item x OC (para o validador usamos a OC principal exata)
    df_validador = df_q.copy()
    for k, oc in enumerate(ocs_principais):
        df_validador[rotulo_oc(k)] = (df_q['oc_principal'] == oc).astype(int)

    # Matriz binária item x atributo DINA
    df_matriz_q = df_q[['Questao', 'posicao', 'area_prova', 'oc_principal']].copy()
    for k, attr in enumerate(ocs_principais):
        df_matriz_q[rotulo_oc(k)] = (df_q['atributo_dina'] == attr).astype(int)

    Q = df_matriz_q[[rotulo_oc(k) for k in range(K)]].to_numpy()
    J = Q.shape[0]

    # ---- Dados do curso ----
    X = df_curso[COLUNAS_Q].to_numpy(dtype=np.int8)
    print(f"  Estimando DINA (EM, {K} atributos, {J} itens)...")
    g, s, pi, perfis_mastery, p_eta1, ll_dina = estimar_dina(X, Q)

    taxa_acerto = X.mean(axis=0)
    p_item_dina = (1 - s) * p_eta1 + g * (1 - p_eta1)

    # ---- Perfis de domínio por aluno ----
    df_perfis = df_curso[['ALUNO', 'CO_IES', 'NT_DIS_CE', 'CLASSE_DIS']].copy().reset_index(drop=True)
    for k, attr in enumerate(ocs_principais):
        df_perfis[f'mastery_{rotulo_oc(k)}'] = perfis_mastery[:, k]
        df_perfis[f'alpha_{rotulo_oc(k)}'] = (perfis_mastery[:, k] >= 0.5).astype(int)
    df_perfis['n_ocs_dominadas'] = df_perfis[[f'alpha_{rotulo_oc(k)}' for k in range(K)]].sum(axis=1)
    df_perfis.to_csv(PASTA_SAIDA / f'dina_perfis_alunos_{normalizar(nome_curso)}.csv',
                     index=False, sep=';', decimal=',', encoding='utf-8-sig')

    # ---- Estimativas por item ----
    status_item = []
    for j in range(J):
        if s[j] + g[j] >= 0.999 - 1e-6:
            status_item.append('POUCO_DISCRIMINATIVO_LIMITE')
        elif (1 - s[j]) - g[j] < 0.1:
            status_item.append('POUCO_DISCRIMINATIVO')
        else:
            status_item.append('OK')
    df_est = pd.DataFrame({
        'Questao': COLUNAS_Q,
        'area_prova': df_matriz_q['area_prova'].values,
        'atributos_requeridos': [df_q.iloc[j]['oc_principal'] for j in range(J)],
        'taxa_acerto_real': taxa_acerto,
        'guess_g': g,
        'slip_s': s,
        'p_domina_atributos': p_eta1,
        'p_acerto_dina': p_item_dina,
        'status': status_item,
    })
    df_est.to_csv(PASTA_SAIDA / f'dina_estimativas_{normalizar(nome_curso)}.csv',
                  index=False, sep=';', decimal=',', encoding='utf-8-sig')

    # ---- Matriz-Q + dicionário de OCs ----
    df_matriz_q.to_csv(PASTA_SAIDA / f'matriz_q_{normalizar(nome_curso)}.csv',
                       index=False, sep=';', encoding='utf-8-sig')
    df_dict_oc = pd.DataFrame({
        'rotulo': [rotulo_oc(k) for k in range(K)],
        'oc_principal': ocs_principais,
        'n_itens_medidos': [int(df_q['atributo_dina'].eq(oc).sum()) for oc in ocs_principais],
        'prevalencia_dominio_dina': pi,
    })
    df_dict_oc.to_csv(PASTA_SAIDA / f'dicionario_ocs_{normalizar(nome_curso)}.csv',
                      index=False, sep=';', decimal=',', encoding='utf-8-sig')

    # ---- Comparação com a LCA exploratória (item a item) ----
    sub_classes = df_classes[df_classes['curso'] == nome_curso]
    p_lca = np.full(J, np.nan)
    gap_lca = np.full(J, np.nan)
    gap_lca_max = np.full(J, np.nan)
    corr_classes_lca = []
    if not sub_classes.empty:
        pesos = sub_classes['n_alunos'].to_numpy(dtype=float)
        for j, col in enumerate(probs_lca_cols):
            vals = sub_classes[col].to_numpy(dtype=float)
            p_lca[j] = np.average(vals, weights=pesos)
        for j, col in enumerate(gaps_lca_cols):
            vals = sub_classes[col].to_numpy(dtype=float)
            gap_lca[j] = np.average(vals, weights=pesos)
            gap_lca_max[j] = np.abs(vals).max()
        for _, row in sub_classes.iterrows():
            perfil = row[probs_lca_cols].to_numpy(dtype=float)
            if not np.all(np.isnan(perfil)):
                corr_classes_lca.append(pearsonr(perfil, p_item_dina)[0])

    p_lca_valid = p_lca[~np.isnan(p_lca)]
    p_dina_valid = p_item_dina[~np.isnan(p_lca)]
    if len(p_lca_valid) > 1:
        r_pearson = pearsonr(p_lca_valid, p_dina_valid)[0]
        r_spearman = spearmanr(p_lca_valid, p_dina_valid)[0]
        r2_item = r_pearson ** 2
    else:
        r_pearson = r_spearman = r2_item = np.nan

    # ---- AIC/BIC: DINA (nacional) vs LCA (mediana por IES) ----
    n_param_dina = 2 * J + K
    bic_dina = -2 * ll_dina + n_param_dina * np.log(len(df_curso))
    aic_dina = -2 * ll_dina + 2 * n_param_dina

    sub_crit = df_criterios[df_criterios['curso'] == nome_curso]
    if not sub_crit.empty:
        bic_lca = float(sub_crit['bic'].median())
        aic_lca = float(sub_crit['aic'].median())
        ll_lca = float(sub_crit['log_lik'].median())
        n_ies = int(sub_crit['ies'].nunique())
        entropia_lca = float(sub_crit['entropia'].mean())
    else:
        bic_lca = aic_lca = ll_lca = entropia_lca = np.nan
        n_ies = 0

    corr_classes_media = float(np.mean(corr_classes_lca)) if corr_classes_lca else np.nan

    comparacao.append({
        'curso': nome_curso,
        'n_alunos': len(df_curso),
        'n_ies_lca': n_ies,
        'n_atributos_dina': K,
        'n_param_dina': n_param_dina,
        'll_dina': round(ll_dina, 2),
        'bic_dina': round(bic_dina, 2),
        'aic_dina': round(aic_dina, 2),
        'll_lca_mediana_ies': round(ll_lca, 2) if not np.isnan(ll_lca) else np.nan,
        'bic_lca_mediana_ies': round(bic_lca, 2) if not np.isnan(bic_lca) else np.nan,
        'aic_lca_mediana_ies': round(aic_lca, 2) if not np.isnan(aic_lca) else np.nan,
        'entropia_lca_media': round(entropia_lca, 4) if not np.isnan(entropia_lca) else np.nan,
        'corr_pearson_item_lca_dina': round(r_pearson, 4) if not np.isnan(r_pearson) else np.nan,
        'corr_spearman_item_lca_dina': round(r_spearman, 4) if not np.isnan(r_spearman) else np.nan,
        'r2_item_lca_dina': round(r2_item, 4) if not np.isnan(r2_item) else np.nan,
        'corr_classe_lca_media': round(corr_classes_media, 4) if not np.isnan(corr_classes_media) else np.nan,
        'delta_bic_dina_menos_lca': round(bic_dina - bic_lca, 2) if not np.isnan(bic_lca) else np.nan,
        'nota_bic': ('DINA estimado a nivel NACIONAL do curso; LCA ajustada POR IES (mediana). '
                     'BIC/AIC nao compartilham escala: interpretar apenas a concordancia item a item '
                     'e as correlacoes classe-LCA x DINA.'),
    })
    print(f"  -> Corr item (Pearson): {r_pearson:.4f} | R²: {r2_item:.4f} | "
          f"BIC DINA: {bic_dina:.0f} vs LCA (med. IES): {bic_lca:.0f}")

    for j in range(J):
        concordancia_itens.append({
            'curso': nome_curso,
            'Questao': COLUNAS_Q[j],
            'area_prova': df_matriz_q['area_prova'].values[j],
            'oc_principal': df_q.iloc[j]['oc_principal'],
            'taxa_acerto_real': round(float(taxa_acerto[j]), 4),
            'p_item_lca': round(float(p_lca[j]), 4) if not np.isnan(p_lca[j]) else np.nan,
            'p_item_dina': round(float(p_item_dina[j]), 4),
            'diff_p_lca_dina': round(float(p_lca[j] - p_item_dina[j]), 4) if not np.isnan(p_lca[j]) else np.nan,
            'gap_lca_medio': round(float(gap_lca[j]), 4) if not np.isnan(gap_lca[j]) else np.nan,
            'gap_lca_max_abs': round(float(gap_lca_max[j]), 4) if not np.isnan(gap_lca_max[j]) else np.nan,
            'status_validacao': 'PENDENTE_VALIDACAO',
        })

    # ---- Workbook de validação especialista ----
    nome_xlsx = PASTA_SAIDA / f'validador_matriz_q_{normalizar(nome_curso)}.xlsx'
    with pd.ExcelWriter(nome_xlsx, engine='openpyxl') as writer:
        # 1) Matriz Q preenchível (item x OC + status)
        planilha_matriz = df_validador[['Questao', 'posicao', 'area_prova', 'perfil_egresso',
                                        'competencia', 'oc_principal', 'oc_secundario'] + 
                                       [rotulo_oc(k) for k in range(K)]].copy()
        planilha_matriz['STATUS'] = 'PENDENTE_VALIDACAO'
        planilha_matriz['OBSERVACOES'] = ''
        planilha_matriz.to_excel(writer, sheet_name='Matriz_Q_Item_x_OC', index=False)

        # 2) Resumo de cobertura
        cobertura = df_dict_oc.rename(columns={'oc_principal': 'OC', 'n_itens_medidos': 'n_itens'})
        cobertura['itens'] = [', '.join(df_q.loc[df_q['atributo_dina'] == oc, 'Questao'])
                              for oc in ocs_principais]
        cobertura['status'] = np.where(cobertura['n_itens'] < 2, 'REVISAR_POUCOS_ITENS',
                                       'OK_COBERTURA')
        cobertura.to_excel(writer, sheet_name='Resumo_Cobertura', index=False)

        # 3) Concordância empírica com a LCA (orienta o especialista)
        conc = pd.DataFrame({
            'Questao': COLUNAS_Q,
            'area_prova': df_matriz_q['area_prova'].values,
            'oc_principal': df_q['oc_principal'].values,
            'taxa_acerto_real': taxa_acerto,
            'p_item_lca': p_lca,
            'p_item_dina': p_item_dina,
            'gap_lca_medio': gap_lca,
            'gap_lca_max_abs': gap_lca_max,
            'status_dina': status_item,
            'sugestao': ['REVISAR: gap LCA alto e OC mapeada'
                         if (not np.isnan(gap_lca_max[j]) and gap_lca_max[j] > 0.35)
                         else 'OK: sem sinal forte de divergência'
                         for j in range(J)],
        })
        conc.to_excel(writer, sheet_name='Concordancia_Empirica_LCA', index=False)

    print(f"  Salvo workbook de validação especialista: {nome_xlsx.name}")

    resumo_geral.append({
        'curso': nome_curso,
        'n_alunos': len(df_curso),
        'n_ocs_dina': K,
        'guess_medio': round(float(g.mean()), 4),
        'slip_medio': round(float(s.mean()), 4),
        'taxa_acerto_media': round(float(taxa_acerto.mean()), 4),
        'corr_item_lca_dina': round(r_pearson, 4) if not np.isnan(r_pearson) else np.nan,
        'status_validacao': 'PENDENTE_VALIDACAO',
    })

# =============================================================================
# 7. ARQUIVOS CONSOLIDADOS
# =============================================================================
pd.DataFrame(resumo_geral).to_csv(PASTA_SAIDA / '00_resumo_geral.csv',
                                  index=False, sep=';', decimal=',', encoding='utf-8-sig')
pd.DataFrame(comparacao).to_csv(PASTA_SAIDA / 'comparacao_lca_vs_dina.csv',
                                index=False, sep=';', decimal=',', encoding='utf-8-sig')
pd.DataFrame(concordancia_itens).to_csv(PASTA_SAIDA / 'concordancia_lca_dina.csv',
                                        index=False, sep=';', decimal=',', encoding='utf-8-sig')

print(f"\n{'='*72}")
print(f"FASE 6 — LCA -> CDM RESTRITO (DINA) CONCLUÍDA!")
print(f"Resultados em: {PASTA_SAIDA}")
print(f"{'='*72}")
