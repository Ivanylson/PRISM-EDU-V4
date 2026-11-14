"""Valida a ontologia OWL do PRISM-EDU e a stack ontologica.

Checagens:
    1. parsing RDF/XML com rdflib;
    2. consultas de integridade (itens, areas, taxas);
    3. SHACL com pyshacl (se instalado);
    4. leitura opcional com owlready2, OWLAPY e OAK;
    5. execucao das consultas SPARQL de exemplo.

Exemplos:
    python processamento/validar_ontologia.py
    python processamento/validar_ontologia.py --exigir-opcionais
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import PASTA_MODELOS  # noqa: E402
from algoritmos.ontologia.adaptadores import (  # noqa: E402
    carregar_grafo, carregar_oak, carregar_owlapy, carregar_owlready2, carregar_rdflib,
    consultar_sparql, resumo_stack_texto, status_stack, validar_shacl,
)

CONSULTAS_INTEGRIDADE = {
    "itens sem edicao": """
        PREFIX prism: <https://prism-edu.example/onto#>
        SELECT (COUNT(?item) AS ?n) WHERE {
          ?item a prism:AssessmentItem .
          FILTER NOT EXISTS { ?item prism:inEdition ?e }
        }""",
    "itens sem area": """
        PREFIX prism: <https://prism-edu.example/onto#>
        SELECT (COUNT(?item) AS ?n) WHERE {
          ?item a prism:AssessmentItem .
          FILTER NOT EXISTS { ?item prism:inKnowledgeArea ?a }
        }""",
    "cursos sem area": """
        PREFIX prism: <https://prism-edu.example/onto#>
        SELECT (COUNT(?c) AS ?n) WHERE {
          ?c a prism:CourseProgram .
          FILTER NOT EXISTS { ?c prism:belongsToArea ?a }
        }""",
    "taxas fora de [0,100]": """
        PREFIX prism: <https://prism-edu.example/onto#>
        SELECT (COUNT(?p) AS ?n) WHERE {
          ?p prism:deficiencyRate ?t .
          FILTER (?t < 0 || ?t > 100)
        }""",
    "estimativas sem item": """
        PREFIX prism: <https://prism-edu.example/onto#>
        SELECT (COUNT(?e) AS ?n) WHERE {
          ?e a prism:PsychometricEstimate .
          FILTER NOT EXISTS { ?e prism:estimateOfItem ?i }
        }""",
}


def _valor_unico(colunas, linhas):
    if not linhas:
        return None
    return linhas[0][0] if linhas[0] else None


def main():
    ap = argparse.ArgumentParser(description="Valida a ontologia OWL do PRISM-EDU")
    ap.add_argument("--ontologia", default=str(PASTA_MODELOS / "ontologia" / "prism_edu.owl"))
    ap.add_argument("--shapes", default=str(PASTA_MODELOS / "ontologia" / "prism_edu.shapes.ttl"))
    ap.add_argument("--consultas", default=str(PASTA_MODELOS / "ontologia" / "queries"))
    ap.add_argument("--limite", type=int, default=5,
                    help="linhas exibidas por consulta")
    ap.add_argument("--exigir-opcionais", action="store_true",
                    help="falha se owlready2/OWLAPY/OAK nao estiverem instalados")
    args = ap.parse_args()

    caminho = Path(args.ontologia)
    shapes = Path(args.shapes)
    consultas = Path(args.consultas)
    falhas = []

    print("=" * 68)
    print("  VALIDACAO DA ONTOLOGIA PRISM-EDU")
    print("=" * 68)
    print("Stack ontologica:")
    print(resumo_stack_texto())

    if not caminho.exists():
        print(f"\n[ERRO] ontologia nao encontrada: {caminho}")
        print("Gere com: python processamento/gerar_ontologia.py")
        return 2

    # 1. rdflib
    print("\n[1] rdflib (RDF/XML)")
    r = carregar_rdflib(caminho)
    grafo = None
    if r.get("ok"):
        print(f"  OK - {r['triplas']:,} triplas, {r['sujeitos']:,} sujeitos")
        try:
            grafo = carregar_grafo(caminho)
        except Exception:
            grafo = None
    else:
        print(f"  FALHA - {r.get('erro')}")
        falhas.append("rdflib")

    # 2. integridade via SPARQL
    print("\n[2] Integridade estrutural (SPARQL)")
    if r.get("ok"):
        for nome, consulta in CONSULTAS_INTEGRIDADE.items():
            try:
                colunas, linhas = consultar_sparql(caminho, consulta, limite=1, grafo=grafo)
                n = _valor_unico(colunas, linhas)
                n_int = int(float(n)) if n is not None else 0
                estado = "OK" if n_int == 0 else f"ATENCAO ({n_int})"
                print(f"  {nome:<26} {estado}")
                if n_int != 0:
                    falhas.append(nome)
            except Exception as exc:
                print(f"  {nome:<26} ERRO ({type(exc).__name__}: {exc})")
                falhas.append(nome)

    # 3. SHACL
    print("\n[3] SHACL (pyshacl)")
    if shapes.exists():
        s = validar_shacl(caminho, shapes)
        if s.get("ok"):
            print(f"  {'CONFORME' if s['conformes'] else 'NAO CONFORME'}")
            if not s["conformes"]:
                falhas.append("shacl")
                texto = s.get("relatorio", "")
                print("  " + "\n  ".join(texto.splitlines()[:15]))
        else:
            print(f"  nao executado - {s.get('motivo') or s.get('erro')}")
    else:
        print(f"  shapes nao encontrado: {shapes}")

    # 4. bibliotecas opcionais
    print("\n[4] Bibliotecas opcionais")
    for nome, funcao in (("owlready2", carregar_owlready2),
                         ("owlapy", carregar_owlapy),
                         ("oaklib", carregar_oak)):
        res = funcao(caminho)
        if res.get("ok"):
            detalhes = ", ".join(f"{k}={v}" for k, v in res.items()
                                 if k not in {"ok", "versao", "recurso", "observacao"})
            print(f"  {nome:<11} OK {res.get('versao', '')} {detalhes}")
            if res.get("observacao"):
                print(f"              {res['observacao']}")
        else:
            print(f"  {nome:<11} indisponivel - {res.get('motivo') or res.get('erro')}")
            if args.exigir_opcionais:
                falhas.append(nome)

    # 5. consultas de exemplo
    print("\n[5] Consultas SPARQL de exemplo")
    if consultas.exists() and r.get("ok"):
        for arq in sorted(consultas.glob("*.rq")):
            try:
                colunas, linhas = consultar_sparql(caminho, arq.read_text(encoding="utf-8"),
                                                   limite=args.limite, grafo=grafo)
                print(f"  {arq.name:<32} {len(linhas)} linha(s) | colunas: {', '.join(colunas)}")
                for linha in linhas[:min(args.limite, 3)]:
                    print("      " + " | ".join("" if v is None else v for v in linha))
            except Exception as exc:
                print(f"  {arq.name:<32} ERRO ({type(exc).__name__}: {exc})")
                falhas.append(arq.name)
    elif not consultas.exists():
        print(f"  pasta de consultas nao encontrada: {consultas}")

    # resumo
    print("\n" + "=" * 68)
    if falhas:
        print(f"  RESULTADO: {len(falhas)} ponto(s) de atencao: {', '.join(falhas)}")
        return 1
    print("  RESULTADO: ontologia valida para o conjunto de checagens executado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
