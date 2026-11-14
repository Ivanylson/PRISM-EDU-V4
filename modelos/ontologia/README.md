# Ontologia PRISM-EDU (OWL 2 DL)

Gerada por `processamento/gerar_ontologia.py` a partir de dados reais do projeto.
Edicoes incluidas: enade_2023.

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
como arquivo; `file:///C:/...` faz o JPype montar `C:\...\file:\C:\...`).

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
