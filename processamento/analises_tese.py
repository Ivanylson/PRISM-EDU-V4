"""CLI: executa as analises de tese E1-E9 e grava artefatos JSON.

Uso:
    python processamento/analises_tese.py                 # ano mais recente
    python processamento/analises_tese.py --ano 2019 --max-linhas 50000
"""
import argparse
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import PASTA_MODELOS  # noqa: E402
from algoritmos.analises_tese import analises_tese as A  # noqa: E402

PASTA_SAIDA = PASTA_MODELOS / "analises_tese"


def _carregar_ano(ano, max_linhas):
    colunas = ["CO_IES", "CO_GRUPO", "CO_REGIAO_CURSO", "CO_CATEGAD", "CO_MODALIDADE",
               "TP_SEXO", "NU_ANO_CURSO", "NU_IDADE", "PESO_AMOSTRA",
               "QE_I01", "QE_I02", "QE_I03",
               "NT_DIS_CE", "NT_CE_D1", "NT_GER"]
    try:
        return A.carregar(ano, colunas=colunas, max_linhas=max_linhas)
    except Exception:
        return A.carregar(ano, max_linhas=max_linhas)


def main():
    ap = argparse.ArgumentParser(description="Analises de tese E1-E9 (PRISM-EDU)")
    ap.add_argument("--ano", type=int, default=None)
    ap.add_argument("--max-linhas", type=int, default=200000)
    args = ap.parse_args()

    edicoes = A.edicoes_disponiveis()
    if not edicoes:
        print("Dados insuficientes: microdados ENADE nao encontrados.")
        return
    ano = args.ano or edicoes[-1]
    print(f"Analisando ENADE {ano} (max {args.max_linhas} linhas)...")
    df = _carregar_ano(ano, args.max_linhas)
    print(f"  {len(df)} registros carregados.")

    resultados = {
        "E1_equidade": A.equidade(df, ano),
        "E2_valor_agregado": A.valor_agregado(df, ano),
        "E5_formacao": A.formacao(df, ano),
        "E6_eficiencia": A.eficiencia(df, ano),
        "E7_cluster_ies": A.cluster_ies(df, ano),
        "E8_distal": A.distal(df, ano),
        "E9_sensibilidade": A.sensibilidade(df, ano),
    }
    # E4 trienal: mesmo curso em edicoes distintas em que foi avaliado
    try:
        dfs_curso = {}
        for ed in edicoes[-6:]:
            dfe = _carregar_ano(ed, min(args.max_linhas, 40000))
            grupo = "CO_GRUPO"
            if grupo in dfe.columns:
                for g, sub in dfe.groupby(grupo):
                    dfs_curso.setdefault(g, {})[ed] = sub
        principais = sorted(dfs_curso, key=lambda g: -sum(len(v) for v in dfs_curso[g].values()))[:3]
        resultados["E4_trienal"] = {f"curso_{g}": A.trienal(dfs_curso, g) for g in principais}
    except Exception as exc:
        resultados["E4_trienal"] = {"status": "insuficiente", "motivo": str(exc)}

    PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
    (PASTA_SAIDA / f"analises_tese_{ano}.json").write_text(
        json.dumps(resultados, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\nGravado: {PASTA_SAIDA / f'analises_tese_{ano}.json'}")
    for nome, res in resultados.items():
        status = res.get("status", "ok") if isinstance(res, dict) else "ok"
        print(f"  {nome}: {status}")


if __name__ == "__main__":
    main()
