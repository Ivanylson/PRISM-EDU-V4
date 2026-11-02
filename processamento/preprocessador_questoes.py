"""
Preprocessador de Questoes - Serie Temporal
Le os arquivos .xlsx de estrutura de questoes gerados por seriesTemporais_questoes
e os converte para CSVs padronizados.
"""
import pandas as pd
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import PASTA_SERIE_QUESTOES, PASTA_DADOS_PROCESSADOS, SEPARADOR, ENCODING


def preprocessar_questoes():
    print("=" * 60)
    print("  PRISM-EDU: Pre-processamento de Questoes")
    print("=" * 60)

    pasta_questoes = PASTA_SERIE_QUESTOES
    if not pasta_questoes.exists():
        print(f"  Pasta de questoes nao encontrada: {pasta_questoes}")
        return

    pasta_resultados = pasta_questoes / "resultados"
    if not pasta_resultados.exists():
        pasta_resultados = pasta_questoes

    xlsx_files = list(pasta_resultados.rglob("*.xlsx"))
    print(f"  Encontrados {len(xlsx_files)} arquivos .xlsx de questoes")

    pasta_saida = PASTA_DADOS_PROCESSADOS / "questoes"
    pasta_saida.mkdir(parents=True, exist_ok=True)

    total_registros = 0
    for arq in sorted(xlsx_files):
        try:
            partes = arq.relative_to(pasta_resultados).parts
            if len(partes) >= 3:
                exame = partes[0]
                ano = partes[1]
                curso = partes[2].replace(".xlsx", "")
            else:
                exame = "enade"
                ano = "unknown"
                curso = arq.stem

            df = pd.read_excel(arq, engine="openpyxl")
            nome_saida = f"questoes_{exame}_{ano}_{curso}.csv"
            df.to_csv(pasta_saida / nome_saida, index=False, sep=SEPARADOR, encoding=ENCODING)
            total_registros += len(df)
        except Exception as e:
            print(f"    Erro ao processar {arq.name}: {e}")

    print(f"  Total: {total_registros} registros de questoes processados")
    print(f"  Saida: {pasta_saida}")


if __name__ == "__main__":
    preprocessar_questoes()
