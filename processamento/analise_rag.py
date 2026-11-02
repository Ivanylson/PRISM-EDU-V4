"""CLI: indexar e consultar o RAG local do PRISM-EDU.

Exemplos:
    python processamento/analise_rag.py indexar
    python processamento/analise_rag.py indexar --limite-por-fonte 5
    python processamento/analise_rag.py consultar "Quais as competencias de Medicina?"
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from algoritmos.rag.indexador_rag import indexar_corpus_padrao, IndiceRAG, PASTA_RAG  # noqa: E402


def cmd_indexar(args):
    print("Indexando corpus RAG (TF-IDF)...")
    indice = indexar_corpus_padrao(limite_por_fonte=args.limite_por_fonte)
    print(f"  Chunks indexados: {len(indice.chunks)}")
    print(f"  Dimensoes TF-IDF: {indice.matriz.shape}")
    print(f"  Gravado em: {PASTA_RAG}")


def cmd_consultar(args):
    indice = IndiceRAG().carregar(PASTA_RAG)
    resultados = indice.buscar(args.pergunta, top_k=args.top_k)
    if not resultados:
        print("Nenhuma fonte acima do limiar (Dados insuficientes).")
        return
    for r in resultados:
        print(f"\n[{r['score']:.3f}] {r['fonte']}")
        print(f"  {r['texto'][:200]}...")


def main():
    ap = argparse.ArgumentParser(description="RAG local do PRISM-EDU")
    sub = ap.add_subparsers(dest="comando", required=True)
    p_idx = sub.add_parser("indexar")
    p_idx.add_argument("--limite-por-fonte", type=int, default=None)
    p_idx.set_defaults(func=cmd_indexar)
    p_con = sub.add_parser("consultar")
    p_con.add_argument("pergunta")
    p_con.add_argument("--top-k", type=int, default=5)
    p_con.set_defaults(func=cmd_consultar)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
