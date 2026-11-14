"""CLI: gera a ontologia educacional do PRISM-EDU em OWL 2 DL.

Saidas (por padrao em ``modelos/ontologia/``):
    prism_edu.owl          RDF/XML OWL 2 DL (abre no Protege)
    prism_edu.ttl          Turtle
    prism_edu.jsonld       JSON-LD
    prism_edu.nt           N-Triples
    prism_edu_manifest.json  manifesto auditavel (contagens, fontes, hashes)
    prism_edu.shapes.ttl   SHACL
    queries/*.rq           consultas SPARQL de exemplo

Exemplos:
    python processamento/gerar_ontologia.py
    python processamento/gerar_ontologia.py --edicoes enade_2023
    python processamento/gerar_ontologia.py --edicoes enade_2022,enade_2023
    python processamento/gerar_ontologia.py --edicoes todas --sem-dina
    python processamento/gerar_ontologia.py --formato owl --saida modelos/ontologia
"""
import argparse
import shutil
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import PASTA_MODELOS, PASTA_DADOS_PROCESSADOS  # noqa: E402
from algoritmos.ontologia.ontologia_owl import construir_owl  # noqa: E402
from algoritmos.ontologia.adaptadores import resumo_stack_texto  # noqa: E402

PASTA_ASSETS = Path(__file__).resolve().parent.parent / "algoritmos" / "ontologia"
EDICAO_PADRAO = "enade_2023"


def descobrir_edicoes():
    edicoes = []
    for arq in sorted(PASTA_DADOS_PROCESSADOS.glob("analise_por_questao_ies_*.csv")):
        nome = arq.stem.replace("analise_por_questao_ies_", "")
        edicoes.append(nome)
    return edicoes


def resolver_edicoes(texto):
    if not texto:
        return [EDICAO_PADRAO]
    texto = texto.strip()
    if texto.lower() in {"todas", "all", "*"}:
        return descobrir_edicoes()
    return [e.strip() for e in texto.split(",") if e.strip()]


def copiar_assets(pasta_saida):
    destino_shapes = pasta_saida / "prism_edu.shapes.ttl"
    shutil.copyfile(PASTA_ASSETS / "shapes.ttl", destino_shapes)
    destino_queries = pasta_saida / "queries"
    destino_queries.mkdir(parents=True, exist_ok=True)
    for arq in sorted((PASTA_ASSETS / "queries").glob("*.rq")):
        shutil.copyfile(arq, destino_queries / arq.name)
    return destino_shapes, destino_queries


def escrever_readme(pasta_saida, edicoes):
    conteudo = f"""# Ontologia PRISM-EDU (OWL 2 DL)

Gerada por `processamento/gerar_ontologia.py` a partir de dados reais do projeto.
Edicoes incluidas: {", ".join(edicoes)}.

## Arquivos

| Arquivo | Uso |
|---|---|
| `prism_edu.owl` | Abrir no **Protege** (RDF/XML, OWL 2 DL). |
| `prism_edu.ttl` | Turtle para RDFLib, OAK e consultas rapidas. |
| `prism_edu.jsonld` | JSON-LD para web semantica. |
| `prism_edu.nt` | N-Triples para diff/versionamento. |
| `prism_edu.shapes.ttl` | Formas SHACL (validacao de integridade). |
| `queries/*.rq` | Consultas SPARQL de exemplo. |
| `prism_edu_manifest.json` | Manifesto com contagens, fontes e hashes SHA-256. |

## Protege

1. Abra o Protege (5.6+).
2. `File > Open` e selecione `prism_edu.owl`.
3. As classes ficam em `prism:PrismEntity`; as propriedades usam os prefixos
   `prism:`, `skos:`, `dcterms:` e `prov:`.
4. Para raciocinio, use um reasoner OWL 2 (HermiT/Pellet) — requer Java.

## RDFLib

```python
from rdflib import Graph
g = Graph(); g.parse("prism_edu.owl", format="xml")
print(len(g))
```

## Owlready2

```python
from owlready2 import get_ontology
onto = get_ontology("prism_edu.owl").load()
print(len(list(onto.classes())), len(list(onto.individuals())))
```

## OWLAPY

No Windows, passe o **caminho local absoluto** (a OWLAPI resolve o argumento
como arquivo; `file:///C:/...` faz o JPype montar `C:\\...\\file:\\C:\\...`).

```python
from pathlib import Path
from owlapy.owl_ontology import SyncOntology
onto = SyncOntology(str(Path("prism_edu.owl").resolve()))
print(len(list(onto.classes_in_signature())))
```

## OAK (Ontology Access Kit)

O adaptador le melhor o `.ttl`; para o `.owl`, informe `format="xml"`
(sem isso o OAK escolhe `FunOwlImplementation` e falha). `entities()`
percorre entidade por entidade (lento): use `all_entity_curies()` para
apenas contar.

```python
from oaklib import get_adapter
adapter = get_adapter("prism_edu.ttl")
print(len(list(adapter.all_entity_curies())))
```

## Validacao

```bash
python processamento/validar_ontologia.py
```

## Limites declarados

- A ABox inclui apenas as edicoes listadas acima.
- `CO_IES` nao tem nome de instituicao nos arquivos de analise; o rotulo e'
  `IES <codigo>` (nao inventamos nomes).
- O desempenho item x IES x curso permanece na tabela-fato CSV
  (`analise_por_questao_ies_*.csv`); a ontologia guarda agregados nacionais
  por item e agregados por IES e por IES x area.
- As estimativas DINA sao as do pipeline `enade_2023` e sao ligadas ao item
  correspondente quando a chave existe.
"""
    (pasta_saida / "README.md").write_text(conteudo, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="Gera a ontologia OWL 2 DL do PRISM-EDU")
    ap.add_argument("--edicoes", default=EDICAO_PADRAO,
                    help=("edicoes separadas por virgula (ex.: enade_2023) ou 'todas'. "
                          f"Padrao: {EDICAO_PADRAO}"))
    ap.add_argument("--formato", default="todos",
                    choices=["todos", "owl", "ttl", "jsonld", "nt"],
                    help="formato(s) a gravar (padrao: todos)")
    ap.add_argument("--saida", default=None,
                    help="pasta de saida (default modelos/ontologia)")
    ap.add_argument("--sem-dina", action="store_true",
                    help="nao inclui estimativas DINA")
    ap.add_argument("--sem-ies", action="store_true",
                    help="nao inclui IES, ofertas e agregados por IES")
    ap.add_argument("--sem-coocorrencia", action="store_true",
                    help="nao inclui coocorrencia de OCs")
    ap.add_argument("--limite-linhas", type=int, default=None,
                    help="limita linhas por arquivo (teste rapido)")
    args = ap.parse_args()

    edicoes = resolver_edicoes(args.edicoes)
    if not edicoes:
        print("Nenhuma edicao encontrada.")
        return 1

    pasta_saida = Path(args.saida) if args.saida else PASTA_MODELOS / "ontologia"
    pasta_saida.mkdir(parents=True, exist_ok=True)

    print("Stack ontologica disponivel:")
    print(resumo_stack_texto())
    print(f"\nConstruindo ontologia OWL 2 DL a partir de dados reais...")
    print(f"  Edicoes: {', '.join(edicoes)}")

    onto = construir_owl(
        edicoes=edicoes,
        incluir_dina=not args.sem_dina,
        incluir_ies=not args.sem_ies,
        incluir_coocorrencia=not args.sem_coocorrencia,
        limite_linhas=args.limite_linhas,
    )
    resumo = onto.resumo()
    print(f"\n  Triplas: {resumo['triplas']:,}")
    print(f"  Estatisticas: {resumo['estatisticas']}")

    problemas = onto.validar()
    if problemas:
        print(f"  Avisos de integridade ({len(problemas)}):")
        for p in problemas[:10]:
            print(f"    - {p}")
    else:
        print("  Integridade estrutural: OK")

    formatos = (("owl", "ttl", "jsonld", "nt") if args.formato == "todos"
                else (args.formato,))
    gerados = onto.salvar(pasta_saida, formatos=formatos)

    destino_shapes, destino_queries = copiar_assets(pasta_saida)
    escrever_readme(pasta_saida, edicoes)

    print("\nGravado:")
    for chave, caminho in gerados.items():
        print(f"  {chave:<9} {caminho}  ({caminho.stat().st_size:,} bytes)")
    print(f"  shapes    {destino_shapes}")
    print(f"  queries   {destino_queries} ({len(list(destino_queries.glob('*.rq')))} consultas)")
    print(f"  README    {pasta_saida / 'README.md'}")
    print("\nAbra prism_edu.owl no Protege. Valide com:")
    print("  python processamento/validar_ontologia.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
