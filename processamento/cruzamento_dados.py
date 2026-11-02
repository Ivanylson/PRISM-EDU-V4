"""
Cruzamento de Dados - Microdados x Pedagogia (a partir das analises por-ano).
Le os arquivos analise_por_questao_ies_*.csv (ja com PERFIL/COMPETENCIAS/OC,
gerados a partir dos xlsx de resultadosQuestoes) e consolida em
analise_cruzamento.csv sem carregar o CSV consolidado de 4GB.
"""
import pandas as pd
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import PASTA_DADOS_PROCESSADOS, SEPARADOR, ENCODING


def executar_cruzamento():
    print("=" * 60)
    print("  PRISM-EDU: Cruzamento de Dados")
    print("=" * 60)

    pasta = PASTA_DADOS_PROCESSADOS
    padroes = [
        "analise_por_questao_ies_enade_*.csv",
        "analise_por_questao_ies_enadeLicenciaturas_*.csv",
        "analise_por_questao_ies_licenciaturas_*.csv",
        "analise_por_questao_ies_enamed_*.csv",
    ]

    arquivos = []
    for padrao in padroes:
        arquivos.extend(sorted(pasta.glob(padrao)))

    # remove duplicatas mantendo ordem; desconsidera copias em subpastas
    vistos = set()
    unicos = []
    for a in arquivos:
        if a.name in vistos:
            continue
        vistos.add(a.name)
        unicos.append(a)
    arquivos = unicos

    if not arquivos:
        print("  Nenhum arquivo analogico encontrado. Execute gerar_analise_questoes.py antes.")
        return

    print(f"  Arquivos encontrados ({len(arquivos)}):")
    for a in arquivos:
        print(f"    - {a.name}")

    partes = []
    for arq in arquivos:
        try:
            df = pd.read_csv(arq, sep=SEPARADOR, encoding="utf-8-sig", low_memory=False)
        except Exception as e:
            print(f"  ERRO ao ler {arq.name}: {e}")
            continue
        if df.empty:
            continue

        for col in ["QTD_ACERTOS", "QTD_ERROS", "TAXA_DEFICIENCIA_%"]:
            if col not in df.columns:
                df[col] = 0

        df["TOTAL_ALUNOS"] = df["QTD_ACERTOS"].fillna(0) + df["QTD_ERROS"].fillna(0)
        df["QTD_BRANCOS_NULOS"] = 0
        partes.append(df)

    if not partes:
        print("  Nenhum dado carregado.")
        return

    final = pd.concat(partes, ignore_index=True)

    colunas_base = [
        "NU_ANO", "CO_IES", "CO_CURSO", "NOME_CURSO", "CO_GRUPO",
        "CO_UF_CURSO", "CO_REGIAO_CURSO", "QUESTAO", "TOTAL_ALUNOS",
        "QTD_ACERTOS", "QTD_ERROS", "QTD_BRANCOS_NULOS", "TAXA_DEFICIENCIA_%",
    ]
    colunas_pedag = ["PERFIL", "COMPETENCIAS", "OC1", "OC2", "OC3"]
    colunas_pedag = [c for c in colunas_pedag if c in final.columns]

    # dedupe (mesma chave pode surgir ao concatenar anos com cursos repetidos)
    chave = ["NU_ANO", "CO_IES", "CO_CURSO", "CO_GRUPO", "QUESTAO"]
    chave = [c for c in chave if c in final.columns]
    if chave:
        final = final.drop_duplicates(subset=chave)

    colunas_saida = [c for c in colunas_base if c in final.columns] + colunas_pedag
    final = final[colunas_saida]
    final = final.sort_values(
        by=[c for c in ["CO_IES", "CO_CURSO", "TAXA_DEFICIENCIA_%"] if c in final.columns],
        ascending=[True, True, False],
    )

    caminho_saida = pasta / "analise_cruzamento.csv"
    final.to_csv(caminho_saida, index=False, sep=SEPARADOR, encoding="utf-8-sig")
    print(f"  Cruzamento salvo: {caminho_saida} ({len(final):,} registros)")


if __name__ == "__main__":
    executar_cruzamento()
