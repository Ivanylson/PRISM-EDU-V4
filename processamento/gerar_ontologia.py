"""CLI: gera a ontologia educacional do PRISM-EDU (JSON-LD + Turtle).

Exemplos:
    python processamento/gerar_ontologia.py
    python processamento/gerar_ontologia.py --limite-arquivos 3
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import PASTA_MODELOS  # noqa: E402
from algoritmos.ontologia.ontologia_enade import construir_ontologia  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Gera a ontologia educacional do PRISM-EDU")
    ap.add_argument("--limite-arquivos", type=int, default=None,
                    help="usa so os N arquivos de analise por questao mais recentes")
    ap.add_argument("--saida", default=None, help="pasta de saida (default modelos/ontologia)")
    args = ap.parse_args()

    pasta_saida = Path(args.saida) if args.saida else PASTA_MODELOS / "ontologia"
    pasta_saida.mkdir(parents=True, exist_ok=True)

    print("Construindo ontologia a partir de dados reais...")
    onto = construir_ontologia(limite_arquivos=args.limite_arquivos)
    resumo = onto.resumo()
    print(f"  Nos: {resumo['nos']} | Arestas: {resumo['arestas']}")
    print(f"  Por tipo: {resumo['por_tipo']}")
    print(f"  Por relacao: {resumo['por_relacao']}")

    problemas = onto.validar()
    if problemas:
        print(f"  Avisos de integridade ({len(problemas)}):")
        for p in problemas[:5]:
            print(f"    - {p}")

    caminho_ttl = pasta_saida / "prism_edu.ttl"
    caminho_jsonld = pasta_saida / "prism_edu.jsonld"
    caminho_ttl.write_text(onto.para_turtle(), encoding="utf-8")
    caminho_jsonld.write_text(json.dumps(onto.para_jsonld(), ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print(f"\nGravado:\n  {caminho_ttl}\n  {caminho_jsonld}")


if __name__ == "__main__":
    main()
