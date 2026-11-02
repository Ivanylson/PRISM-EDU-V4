"""
Análise de Drift Temporal (CLI)
===============================
Gera os artefatos de drift entre edições do ENADE usando o mesmo pipeline dos
motores (algoritmos/drift/pipeline_drift.py).

A comparação é sempre dentro do mesmo curso, contra a edição anterior em que
aquele curso foi avaliado (ciclo trienal do ENADE). Assim, cada curso tem a sua
própria série de referências.

Modos:
  consecutivas_tendencia (default): curso vs. edição anterior do curso + matriz
  consecutivas:                    apenas curso vs. edição anterior do curso
  baseline:                        curso vs. referência fixa (--baseline)

Exemplos:
  python processamento/analise_drift_temporal.py --modo consecutivas_tendencia
  python processamento/analise_drift_temporal.py --modo baseline --baseline 2019
  python processamento/analise_drift_temporal.py --edicao enade_2023 --modo consecutivas
"""
import argparse
import sys

from algoritmos.drift.pipeline_drift import (
    MODO_PADRAO,
    MODOS,
    _registrar_resumo,
    comparar_edicao_prod,
    edicoes_enade,
    gerar_tendencia,
    montar_tendencia,
    salvar_por_referencia,
)
from config import PASTA_MODELOS


def _processar_edicao(edicao, modo, baseline, max_alunos, pasta_drift=None):
    resultado = comparar_edicao_prod(edicao, modo=modo, baseline=baseline, max_alunos=max_alunos)
    gravados = salvar_por_referencia(edicao, resultado, pasta_drift=pasta_drift)
    _registrar_resumo(edicao, modo, resultado, gravados, pasta_drift=pasta_drift)
    meta = resultado["meta"]
    print(f"[{edicao}] {meta['n_comparacoes']} variáveis em {meta['n_cursos_comuns']} cursos; "
          f"{meta['n_drift']} com drift; refs: {meta.get('referencias') or '—'}")
    for ref, caminho in gravados:
        print(f"    {caminho.name} (ref {ref})")
    return gravados


def main():
    ap = argparse.ArgumentParser(description="PRISM-EDU: drift temporal entre edições.")
    ap.add_argument("--modo", default=MODO_PADRAO, choices=MODOS)
    ap.add_argument("--baseline", default="2019", help="Ano de referência no modo baseline.")
    ap.add_argument("--edicao", default="", help="Edição específica (ex.: enade_2023).")
    ap.add_argument("--max-alunos", type=int, default=20000)
    ap.add_argument("--recarregar", action="store_true", help="Ignora o cache de pares.")
    args = ap.parse_args()

    pasta_drift = PASTA_MODELOS / "drift"
    if args.edicao:
        _processar_edicao(args.edicao, args.modo, args.baseline, args.max_alunos, pasta_drift=pasta_drift)
        if args.modo in ("consecutivas_tendencia", "baseline"):
            montar_tendencia(args.modo, args.baseline, pasta_drift=pasta_drift)
        return

    resultado = gerar_tendencia(modo=args.modo, baseline=args.baseline,
                                recarregar=args.recarregar, max_alunos=args.max_alunos,
                                pasta_drift=pasta_drift)
    print(f"\nEdições calculadas: {resultado.get('edicoes_calculadas') or 'nenhuma (cache)'}")
    print("Arquivos de tendência gerados:")
    for nome, caminho in resultado.get("arquivos", {}).items():
        print(f"  - {nome}: {caminho}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
