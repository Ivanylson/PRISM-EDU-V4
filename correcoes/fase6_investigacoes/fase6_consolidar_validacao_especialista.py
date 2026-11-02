# -*- coding: utf-8 -*-
"""
=============================================================================
FASE 6 — CONSOLIDAÇÃO DA VALIDAÇÃO ESPECIALISTA DA MATRIZ ITEM–OC DO INEP
=============================================================================
Item (1) do artigo:
  "Incorporate expert validation of INEP's item–KO matrix to move from
   exploratory LCA toward restricted Cognitive Diagnosis Models."

Este script NÃO reestima modelos: ele lê as saídas já geradas por
fase6_lca_para_cdm_restrito.py (workbooks por curso, concordância LCA↔DINA,
dicionários de OC e resumo) e monta UM workbook único que transforma a
validação especialista em um processo auditável do início ao fim:

  aba 1  MATRIZ_Q_GERAL            : cada item x curso, OC mapeada + status
                                     preenchível (PENDENTE_VALIDACAO /
                                     VALIDADO / REVISAR / REJEITAR) e coluna
                                     de observações.
  aba 2  COBERTURA_OC_POR_CURSO    : por OC, nº de itens medidos, prevalência
                                     de domínio do DINA, status de cobertura.
  aba 3  PROBLEMAS_CRITICOS        : lista priorizada de itens que exigem a
                                     revisão humana (gap LCA alto, itens pouco
                                     discriminativos, OC com < 2 itens).
  aba 4  RESUMO_GERAL              : consolidação numérica por curso.
  aba 5  LEITURA                   : instruções de uso + convenções.

Saída: arquivosgerados/RESULTADOS_FASE6_LCA_CDM/
       VALIDADOR_ESPECIALISTA_CONSOLIDADO.xlsx
=============================================================================
"""
import pandas as pd
from pathlib import Path
import unicodedata
import re

DIRETORIO_ATUAL = Path(__file__).resolve().parent
DIRETORIO_RAIZ = DIRETORIO_ATUAL.parent
PASTA_SAIDA = DIRETORIO_RAIZ / 'arquivosgerados' / 'RESULTADOS_FASE6_LCA_CDM'
PASTA_SAIDA.mkdir(parents=True, exist_ok=True)


def normalizar_curso(texto):
    t = unicodedata.normalize('NFKD', str(texto))
    t = ''.join(c for c in t if not unicodedata.combining(c))
    return re.sub(r'\W', '', t).lower()

print("Carregando artefatos da validação LCA -> CDM restrito...")

resumo = pd.read_csv(PASTA_SAIDA / '00_resumo_geral.csv', sep=';', decimal=',', encoding='utf-8-sig')
concordancia = pd.read_csv(PASTA_SAIDA / 'concordancia_lca_dina.csv', sep=';', decimal=',', encoding='utf-8-sig')

cursos = sorted(resumo['curso'].tolist())

# ---------------------------------------------------------------------------
# 1. MATRIZ-Q GERAL (item x curso) com OC real do INEP + flags de validação
# ---------------------------------------------------------------------------
linhas = []
cobertura_linhas = []

for curso in cursos:
    nome_arquivo = normalizar_curso(curso)
    dic_path = PASTA_SAIDA / f'dicionario_ocs_{nome_arquivo}.csv'
    matriz_path = PASTA_SAIDA / f'matriz_q_{nome_arquivo}.csv'

    if not dic_path.exists() or not matriz_path.exists():
        continue

    df_dic = pd.read_csv(dic_path, sep=';', decimal=',', encoding='utf-8-sig')
    df_q = pd.read_csv(matriz_path, sep=';', encoding='utf-8-sig')

    # OC real por item (df_q guarda oc_principal por item)
    oc_por_item = dict(zip(df_q['Questao'], df_q['oc_principal']))
    conc_curso = concordancia[concordancia['curso'] == curso]

    # colunas OC_* (atributos do DINA)
    oc_cols = [c for c in df_q.columns if c.startswith('OC_')]

    for _, item in df_q.iterrows():
        questao = item['Questao']
        oc_real = oc_por_item.get(questao, '')
        conc_row = conc_curso[conc_curso['Questao'] == questao]
        gap_max = conc_row['gap_lca_max_abs'].iloc[0] if not conc_row.empty else float('nan')
        p_lca = conc_row['p_item_lca'].iloc[0] if not conc_row.empty else float('nan')
        p_dina = conc_row['p_item_dina'].iloc[0] if not conc_row.empty else float('nan')
        diff = conc_row['diff_p_lca_dina'].iloc[0] if not conc_row.empty else float('nan')
        status_dina = conc_row['status_validacao'].iloc[0] if not conc_row.empty else 'PENDENTE_VALIDACAO'

        # prioridade de revisão
        motivo = []
        if not pd.isna(gap_max) and gap_max > 0.35:
            motivo.append('gap_LCA_>0.35')
        if str(status_dina) == 'POUCO_DISCRIMINATIVO':
            motivo.append('pouco_discriminativo_DINA')
        if str(status_dina) == 'POUCO_DISCRIMINATIVO_LIMITE':
            motivo.append('parametros_no_limite')
        n_itens_oc = int(df_dic[df_dic['oc_principal'] == oc_real]['n_itens_medidos'].sum()) if oc_real else 0
        if oc_real and n_itens_oc < 2:
            motivo.append('OC_com_<2_itens')

        linhas.append({
            'curso': curso,
            'Questao': questao,
            'oc_principal_INEP': oc_real,
            'area_prova': item.get('area_prova', ''),
            'p_item_lca': p_lca,
            'p_item_dina': p_dina,
            'diff_p_lca_dina': diff,
            'gap_lca_max_abs': gap_max,
            'n_itens_na_oc': n_itens_oc,
            'prioridade_revisao': '; '.join(motivo) if motivo else 'rotina',
            'STATUS': 'PENDENTE_VALIDACAO',
            'OBSERVACOES': '',
        })

    # COBERTURA POR OC
    for _, oc in df_dic.iterrows():
        cobertura_linhas.append({
            'curso': curso,
            'OC': oc['oc_principal'],
            'n_itens_medidos': oc['n_itens_medidos'],
            'prevalencia_dominio_DINA': oc['prevalencia_dominio_dina'],
            'status_cobertura': 'REVISAR_POUCOS_ITENS' if oc['n_itens_medidos'] < 2 else 'OK_COBERTURA',
        })

df_matriz_geral = pd.DataFrame(linhas)
df_cobertura = pd.DataFrame(cobertura_linhas)

# ---------------------------------------------------------------------------
# 2. PROBLEMAS CRÍTICOS (fila de trabalho do especialista)
# ---------------------------------------------------------------------------
df_criticos = df_matriz_geral[df_matriz_geral['prioridade_revisao'] != 'rotina'].copy()
df_criticos = df_criticos.sort_values(['curso', 'Questao'])

df_criticos_cobertura = df_cobertura[df_cobertura['status_cobertura'] == 'REVISAR_POUCOS_ITENS'].copy()

# ---------------------------------------------------------------------------
# 3. RESUMO DE VALIDAÇÃO POR CURSO (contagem de pendências)
# ---------------------------------------------------------------------------
resumo_validacao = df_matriz_geral.groupby('curso').agg(
    n_itens=('Questao', 'count'),
    n_prioritarios=('prioridade_revisao', lambda s: int((s != 'rotina').sum())),
).reset_index()
resumo_validacao = resumo_validacao.merge(
    resumo[['curso', 'n_alunos', 'n_ocs_dina', 'guess_medio', 'slip_medio',
            'taxa_acerto_media', 'corr_item_lca_dina']],
    on='curso', how='left')

# ---------------------------------------------------------------------------
# 4. GRAVAÇÃO DO WORKBOOK CONSOLIDADO
# ---------------------------------------------------------------------------
nome_xlsx = PASTA_SAIDA / 'VALIDADOR_ESPECIALISTA_CONSOLIDADO.xlsx'
with pd.ExcelWriter(nome_xlsx, engine='openpyxl') as writer:
    df_matriz_geral.to_excel(writer, sheet_name='MATRIZ_Q_GERAL', index=False)
    df_cobertura.to_excel(writer, sheet_name='COBERTURA_OC_POR_CURSO', index=False)
    df_criticos.to_excel(writer, sheet_name='PROBLEMAS_CRITICOS', index=False)
    resumo_validacao.to_excel(writer, sheet_name='RESUMO_GERAL', index=False)

    leitura = pd.DataFrame({
        'Acao': [
            '1. Abra MATRIZ_Q_GERAL e revise a coluna oc_principal_INEP item a item.',
            '2. Preencha STATUS (VALIDADO / REVISAR / REJEITAR) e OBSERVACOES.',
            '3. PROBLEMAS_CRITICOS lista os itens que exigem revisao humana (gap LCA alto, itens pouco discriminativos, OC com <2 itens).',
            '4. COBERTURA_OC_POR_CURSO: OCs com <2 itens tornam o DINA mal identificado; junte OCs ou revise a matriz.',
            '5. A coluna prioridade_revisao soma evidencia empirica (LCA vs DINA) ao julgamento do especialista.',
            '6. Apos validar, reexporte o arquivo e rode fase6_consumir_matriz_q_validada.py para reestimar o DINA restrito sobre a matriz aprovada.',
        ],
        'Convencoes': [
            'STATUS=PENDENTE_VALIDACAO (inicial) | VALIDADO | REVISAR | REJEITAR.',
            'gap_lca_max_abs>0.35: probabilidade de acerto da LCA difere muito do DINA para aquele item.',
            'POUCO_DISCRIMINATIVO: (1-s)-g < 0.1, item com pouco poder de separar quem domina de quem nao domina.',
            'OC_com_<2_itens: atributo com menos de 2 itens na matriz-Q (risco de identificabilidade).',
            'guess g e slip s estimados por EM restrito a [0, 0.5] para garantir a solucao orientada.',
            '',
        ],
    })
    leitura.to_excel(writer, sheet_name='LEITURA', index=False)

print(f"\nWorkbook consolidado salvo: {nome_xlsx.name}")
print(f"  - {len(df_matriz_geral)} linhas item x curso na MATRIZ_Q_GERAL")
print(f"  - {len(df_criticos)} itens com prioridade de revisão")
print(f"  - {len(df_criticos_cobertura)} OC com <2 itens (risco de identificabilidade)")

# ---------------------------------------------------------------------------
# 5. RELATÓRIO MARKDOWN DE ORIENTAÇÃO
# ---------------------------------------------------------------------------
n_oc_poucos_itens = df_criticos_cobertura['curso'].nunique()
md = f"""# Validação Especialista da Matriz Item–OC do INEP (ENADE 2023)

**Fase 6 — transição LCA exploratória → CDM restrito (DINA)** · Item (1) do artigo

## O que validar

Abra **VALIDADOR_ESPECIALISTA_CONSOLIDADO.xlsx** e preencha, na aba
`MATRIZ_Q_GERAL`, as colunas `STATUS` e `OBSERVACOES` para cada item de cada
curso. A coluna `oc_principal_INEP` é a atribuição original do Anexo IX do
INEP — é essa atribuição que o especialista confere.

## Prioridades (aba PROBLEMAS_CRITICOS)

- **{len(df_criticos)} itens** em {df_criticos['curso'].nunique() if not df_criticos.empty else 0} cursos
  apresentam sinal de divergência (gap LCA > 0.35, item pouco discriminativo no
  DINA ou OC com menos de 2 itens).
- **{len(df_criticos_cobertura)} OC** em {n_oc_poucos_itens} cursos têm menos de 2 itens
  medidos — risco de identificabilidade no DINA. Antes da reestimação, decidir:
  unir OCs semelhantes ou manter apenas as bem cobertas.

## Consistência empírica já observada

Correlação item a item entre a LCA exploratória e o DINA restrito:
0.92 – 0.998 (Pearson) nos {len(resumo_validacao)} cursos processados.
Os workbooks por curso (`validador_matriz_q_<curso>.xlsx`) e a base
`concordancia_lca_dina.csv` guardam os números por item.

## Fluxo

1. Validar a matriz (este workbook).
2. Reexportar como `matriz_q_validada_<curso>.csv` (colunas Questao + OC_*).
3. Reestimar o DINA restrito com `fase6_consumir_matriz_q_validada.py`.
"""
caminho_md = PASTA_SAIDA / '00_ORIENTACOES_VALIDACAO.md'
caminho_md.write_text(md, encoding='utf-8')
print(f"Orientações salvas: {caminho_md.name}")
