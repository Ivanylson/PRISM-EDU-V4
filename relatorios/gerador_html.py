"""
Gerador de Relatorios HTML - PRISM-EDU
Gera relatorios HTML com analise por IES/Curso.
"""
import pandas as pd
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import PASTA_DADOS_PROCESSADOS, CURSOS_MAP, SEPARADOR, ENCODING, formatar_nome_curso


def gerar_relatorio_html():
    print("=" * 60)
    print("  PRISM-EDU: Gerador de Relatorios HTML")
    print("=" * 60)

    from config import carregar_consolidado
    print("  Carregando dados por ano (memoria leve)...")
    df = carregar_consolidado()
    if df is None or df.empty:
        print("  ERRO: Dados nao encontrados.")
        return
    pasta_saida = PASTA_DADOS_PROCESSADOS / "relatorios_html"
    pasta_saida.mkdir(parents=True, exist_ok=True)

    colunas_questoes = [f"Q{i}" for i in range(1, 39) if f"Q{i}" in df.columns]

    for co_grupo in df["CO_GRUPO"].unique():
        nome_curso = CURSOS_MAP.get(int(co_grupo), f"Curso_{co_grupo}")
        df_curso = df[df["CO_GRUPO"] == co_grupo]

        taxa_por_questao = {}
        for q in colunas_questoes:
            taxa_por_questao[q] = (pd.to_numeric(df_curso[q], errors="coerce").fillna(0) == 0).mean() * 100

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Relatorio - {nome_curso}</title>
<style>
body {{ font-family: Arial; margin: 20px; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ddd; padding: 8px; text-align: center; }}
th {{ background: #2E5984; color: white; }}
.critico {{ background: #ff6b6b; }} .atencao {{ background: #ffd93d; }} .ok {{ background: #6bcb77; }}
</style></head><body>
<h1>Relatorio de Diagnostico - {nome_curso}</h1>
<p>Total de alunos: {len(df_curso)}</p>
<h2>Taxa de Deficiencia por Questao</h2>
<table><tr><th>Questao</th><th>Taxa Deficiencia (%)</th><th>Status</th></tr>"""

        for q, taxa in taxa_por_questao.items():
            classe = "critico" if taxa > 60 else "atencao" if taxa > 40 else "ok"
            html += f"<tr><td>{q}</td><td>{taxa:.1f}%</td><td class='{classe}'>{'CRITICO' if classe == 'critico' else 'ATENCAO' if classe == 'atencao' else 'OK'}</td></tr>"

        html += "</table></body></html>"

        nome_arq = f"relatorio_{formatar_nome_curso(nome_curso)}.html"
        (pasta_saida / nome_arq).write_text(html, encoding=ENCODING)
        print(f"  Gerado: {nome_arq}")

    print(f"\n  Relatorios salvos em: {pasta_saida}")


if __name__ == "__main__":
    gerar_relatorio_html()
