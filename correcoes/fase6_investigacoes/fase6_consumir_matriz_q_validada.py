# -*- coding: utf-8 -*-
"""
=============================================================================
FASE 6 — DINA RESTRITO SOBRE A MATRIZ-Q VALIDADA PELO ESPECIALISTA
=============================================================================
Item (1) do artigo — fechamento do ciclo:

  LCA exploratória -> [validação especialista da matriz item-OC do INEP]
                    -> CDM restrito (DINA) sobre a matriz APROVADA.

Como usar:
  1. Abra VALIDADOR_ESPECIALISTA_CONSOLIDADO.xlsx (ou os workbooks por curso)
     e valide as colunas OC_* / STATUS.
  2. Salve a matriz validada de cada curso como:

       arquivosgerados/RESULTADOS_FASE6_LCA_CDM/matrizes_validadas/
                          matriz_q_validada_<curso_normalizado>.csv

     Formato mínimo: coluna "Questao" (Q1..Q38) + colunas binárias OC_*
     (0/1), na MESMA ordem/quantidade usada pelo pipeline original
     (ver dicionario_ocs_<curso>.csv para conferir os rótulos OC_*).
  3. Rode este script. Para cada matriz validada ele:
       - carrega os microdados do curso (ENADE 2023);
       - reestima o DINA por EM (mesma rotina fase6_dina_em.py);
       - grava dina_validado_<curso>.csv (parâmetros por item),
         dina_validado_perfis_<curso>.csv (domínio por aluno) e
         resumo_dina_validado.csv (consolidado).

Sem arquivos em matrizes_validadas/, o script informa e termina sem alterar
nada — seguro para rodar a qualquer momento.
=============================================================================
"""
import pandas as pd
import numpy as np
from pathlib import Path
import unicodedata
import re

from fase6_dina_em import estimar_dina

DIRETORIO_ATUAL = Path(__file__).resolve().parent
DIRETORIO_RAIZ = DIRETORIO_ATUAL.parent

CAMINHO_MICRODADOS = DIRETORIO_RAIZ / 'arquivosgerados' / 'relatorio_final_enade_2023.csv'
PASTA_SAIDA = DIRETORIO_RAIZ / 'arquivosgerados' / 'RESULTADOS_FASE6_LCA_CDM'
PASTA_VALIDADAS = PASTA_SAIDA / 'matrizes_validadas'
PASTA_VALIDADAS.mkdir(parents=True, exist_ok=True)

COLUNAS_Q = [f'Q{i}' for i in range(1, 39)]

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
NOME_PARA_CODIGO = {}


def normalizar_curso(texto):
    t = unicodedata.normalize('NFKD', str(texto))
    t = ''.join(c for c in t if not unicodedata.combining(c))
    return re.sub(r'\W', '', t).lower()


NOME_PARA_CODIGO.update({normalizar_curso(nome): cod for cod, nome in cursos_map.items()})


def carregar_microdados():
    df = pd.read_csv(CAMINHO_MICRODADOS, sep=';', encoding='utf-8', low_memory=False,
                     usecols=['ALUNO', 'CO_GRUPO', 'CO_IES', 'TP_PR_GER', 'NT_DIS_CE'] + COLUNAS_Q)
    df = df[df['TP_PR_GER'] > 0].copy()
    for col in COLUNAS_Q:
        df[col] = pd.to_numeric(df[col], errors='coerce').apply(lambda x: 1 if x == 1 else 0)
    return df


def main():
    arquivos = sorted(PASTA_VALIDADAS.glob('matriz_q_validada_*.csv'))
    if not arquivos:
        print("Nenhuma matriz validada encontrada em:")
        print(f"  {PASTA_VALIDADAS}")
        print("Execute a validação especialista primeiro (workbook VALIDADOR_ESPECIALISTA_CONSOLIDADO.xlsx).")
        print("Este script não alterou nada.")
        return

    print(f"Matrizes validadas encontradas: {len(arquivos)}")
    df_micro = carregar_microdados()
    resumo = []

    for caminho in arquivos:
        nome_curso = normalizar_curso(caminho.stem.replace('matriz_q_validada_', ''))
        cod_curso = NOME_PARA_CODIGO.get(nome_curso)
        if cod_curso is None:
            print(f"  [AVISO] curso desconhecido em {caminho.name} — pulando.")
            continue

        df_q = pd.read_csv(caminho, sep=';', decimal=',', encoding='utf-8-sig')
        df_q.columns = [str(c).strip() for c in df_q.columns]
        if 'Questao' not in df_q.columns:
            print(f"  [AVISO] {caminho.name} sem coluna 'Questao' — pulando.")
            continue

        oc_cols = [c for c in df_q.columns if c.startswith('OC_')]
        if not oc_cols:
            print(f"  [AVISO] {caminho.name} sem colunas OC_* — pulando.")
            continue

        df_q = df_q[df_q['Questao'].isin(COLUNAS_Q)].sort_values('Questao')
        df_q = df_q.set_index('Questao').reindex(COLUNAS_Q).reset_index()
        Q = df_q[oc_cols].astype(int).to_numpy()
        if Q.shape[0] != 38:
            print(f"  [AVISO] {caminho.name} com {Q.shape[0]} itens (esperado 38) — pulando.")
            continue

        df_curso = df_micro[df_micro['CO_GRUPO'] == cod_curso]
        if len(df_curso) < 50:
            print(f"  [AVISO] poucos alunos ({len(df_curso)}) — pulando.")
            continue

        X = df_curso[COLUNAS_Q].to_numpy(dtype=np.int8)
        print(f"\nReestimando DINA restrito — {cursos_map[cod_curso]} ({len(df_curso)} alunos, {len(oc_cols)} OC)...")
        g, s, pi, perfis_mastery, p_eta1, ll = estimar_dina(X, Q)

        taxa_acerto = X.mean(axis=0)
        df_est = pd.DataFrame({
            'Questao': COLUNAS_Q,
            'taxa_acerto_real': taxa_acerto,
            'guess_g': g,
            'slip_s': s,
            'p_domina_atributos': p_eta1,
            'p_acerto_dina': (1 - s) * p_eta1 + g * (1 - p_eta1),
        })
        df_est.to_csv(PASTA_SAIDA / f'dina_validado_{nome_curso}.csv',
                      index=False, sep=';', decimal=',', encoding='utf-8-sig')

        df_perf = pd.DataFrame(perfis_mastery, columns=oc_cols)
        df_perf.insert(0, 'ALUNO', df_curso['ALUNO'].reset_index(drop=True))
        df_perf.to_csv(PASTA_SAIDA / f'dina_validado_perfis_{nome_curso}.csv',
                       index=False, sep=';', decimal=',', encoding='utf-8-sig')

        n_param = 2 * 38 + len(oc_cols)
        bic = -2 * ll + n_param * np.log(len(df_curso))
        resumo.append({
            'curso': cursos_map[cod_curso],
            'n_alunos': len(df_curso),
            'n_ocs': len(oc_cols),
            'll_dina_validado': round(ll, 2),
            'bic_dina_validado': round(bic, 2),
            'guess_medio': round(float(g.mean()), 4),
            'slip_medio': round(float(s.mean()), 4),
        })
        print(f"  -> LL={ll:.2f} | BIC={bic:.0f} | g_medio={g.mean():.3f} | s_medio={s.mean():.3f}")

    if resumo:
        pd.DataFrame(resumo).to_csv(PASTA_SAIDA / 'resumo_dina_validado.csv',
                                    index=False, sep=';', decimal=',', encoding='utf-8-sig')
        print(f"\nDINA restrito sobre matriz validada concluído. Arquivos 'dina_validado_*' em:")
        print(f"  {PASTA_SAIDA}")


if __name__ == '__main__':
    main()
