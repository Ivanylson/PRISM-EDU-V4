# Relatório de Consolidação e Expansão Semântica — PRISM-EDU

**Data:** 14/11/2026
**Projeto:** PRISM-EDU (`C:\Users\usuario\Downloads\projeto\PRISM-EDU`)
**Contexto:** continuidade do relatório de **05/11/2026**. Esta rodada atende ao pedido de consolidar o projeto e acrescentar, à **opção 16 → subseção 1** do menu CLI (“IA AVANÇADA → Ontologia educacional”), uma **ontologia `.owl` compatível com Protégé**, utilizável por **RDFLib, Owlready2, OWLAPY e OAK (Ontology Access Kit)**, em nível de pesquisa de ponta.

> **Nota de integridade:** todos os números deste relatório foram medidos nos artefatos reais do repositório. Não há instâncias, citações ou métricas fabricadas. Onde o dado não existe, o texto declara a lacuna.

---

## 1. Escopo solicitado e status

| # | Solicitação | Status | Evidência |
|---|---|---|---|
| 1 | Consolidar o PRISM-EDU | concluído | suíte de regressão `91 testes OK` (18,075 s) |
| 2 | Ontologia `.owl` na opção 16 → subseção 1 | concluído | `main.py` → `processamento/gerar_ontologia.py` |
| 3 | Abrir no Protégé | concluído | `modelos/ontologia/prism_edu.owl` (RDF/XML, 20.247.704 bytes) |
| 4 | Suporte a RDFLib | concluído | 240.366 triplas / 23.788 sujeitos |
| 5 | Suporte a Owlready2 | concluído | 26 classes / 83 propriedades / 23.603 indivíduos |
| 6 | Suporte a OWLAPY | concluído | 28 classes / 23.661 indivíduos |
| 7 | Suporte a OAK | concluído | 23.771 entidades (oaklib 0.7.4, venv isolado) |
| 8 | Nível de pesquisa de ponta | concluído | OWL 2 DL + SKOS + PROV-O + SHACL + SPARQL + manifesto com SHA-256 |
| 9 | Registrar no relatório 14.11.26 | concluído | este documento |
| 10 | Manter relatório 05/11/2026 | concluído | `relatorio_resolucao_05112026.md` preservado |

---

## 2. Decisão de arquitetura — deliberação dos múltiplos agentes

Antes de codificar, o problema foi decomposto em cinco perspectivas independentes (“agentes”), cada uma com um critério de “top” diferente. A decisão final é a interseção das cinco.

### 2.1 Perspectivas avaliadas

| Agente | Foco | Proposta inicial | Veredito |
|---|---|---|---|
| **A — Semântica formal** | rigor lógico, Protégé, raciocínio | OWL 2 DL completo com TBox, restrições, disjointness, inversas e axiomas de classe | **adotado** (com ajustes de compatibilidade) |
| **B — Dados e engenharia** | identidade, proveniência, rastreabilidade | ABox só com dados reais, chaves auditáveis e hash das fontes | **adotado** |
| **C — Ecossistema de ferramentas** | interoperabilidade real | um artefato por biblioteca seria fragmentação; melhor um `.owl` canônico + serializações | **adotado** |
| **D — Validação e integridade** | não publicar grafo inconsistente | SHACL + consultas de integridade + reasoner + testes de regressão | **adotado** |
| **E — Produto e pesquisa** | utilidade científica e pedagógica | ontologia como camada de significado, não como depósito de desempenho | **adotado** |

### 2.2 Alternativas descartadas

- **Grafo RDF artesanal** (já existente em `ontologia_enade.py`): útil como visualização, mas sem TBox formal, sem restrições e sem raciocínio. **Descartado como artefato principal**, mantido por compatibilidade e coberto por testes.
- **Ontologia só de TBox** (“ontologia de vitrine”): bonita no Protégé, mas não responde a nenhuma pergunta empírica. **Descartado**: a ABox usa dados reais do ENADE 2023.
- **Ontologia só de ABox** (dump de CSV em RDF): não é ontologia, é serialização. **Descartado**.
- **Uma ontologia por biblioteca** (uma para Owlready2, outra para OAK…): fragmenta a verdade e cria divergência silenciosa. **Descartado**: há um `.owl` canônico e três serializações equivalentes (`.ttl`, `.jsonld`, `.nt`).
- **Colocar item × IES × curso dentro do grafo**: geraria milhões de triplas e tornaria o Protégé inutilizável. **Descartado**: a tabela-fato continua em CSV; o grafo guarda agregados e o significado.

### 2.3 Decisão consolidada (“o que seria top”)

**OWL 2 DL formal com TBox completo + ABox real do ENADE 2023 + SKOS para dimensões contextuais + PROV-O/DCTERMS para proveniência + SHACL para integridade + SPARQL para consulta + adaptadores para as quatro bibliotecas + manifesto auditável com SHA-256.**

Justificativa: é a única combinação que satisfaz simultaneamente rigor lógico (A), rastreabilidade (B), interoperabilidade (C), verificabilidade (D) e utilidade científica (E), sem sacrificar o desempenho do dashboard.

---

## 3. O que foi construído

### 3.1 TBox — a camada formal

A TBox foi escrita em OWL 2 DL com hierarquia explícita e axiomas que um reasoner consegue explorar.

- **26 classes**, todas sob `prism:PrismEntity`:
  - estrutura de exame: `ExamFamily`, `ExamEdition`, `KnowledgeArea`, `ExamArea`, `CourseProgram`, `CourseOffering`, `HigherEducationInstitution`, `AssessmentItem`, `ItemApplication`;
  - desempenho: `PerformanceIndicator` → `ItemPerformance`, `InstitutionPerformance`, `InstitutionAreaPerformance`;
  - currículo: `CurricularElement` → `Competency`, `LearningObjective`, `GraduateProfile`;
  - análise: `PsychometricEstimate`, `AnalyticalMethod`, `LatentClass`, `MasteryProfile`, `Intervention`, `StudentCohort`, `ObjectiveCooccurrence`, `ContextualDimension`.
- **38 object properties**, com domínio, range e inversas declaradas (ex.: `inEdition` ↔ `hasItem`, `offeredBy` ↔ `offers`, `belongsToArea` ↔ `hasCourseProgram`, `belongsToFamily` ↔ `hasEdition`). No grafo, as inversas materializadas elevam o total de `owl:ObjectProperty` a **52**; o manifesto registra as **38 declaradas**.
- **23 data properties** (`hasQuestionNumber`, `deficiencyRate`, `guess`, `slip`, `masteryProbability`, `estimationStatus`, `hasSourceTable`, `hasSourceKey`, `hasVersion`…).
- **17 restrições OWL** (`owl:Restriction` com `someValuesFrom`), **10 axiomas de disjointness** entre classes incompatíveis (ex.: `AssessmentItem` × `ExamEdition`, `Competency` × `GraduateProfile`) e **características de propriedade** (`partOf` transitiva, `coOccursWith` simétrica).
- **5 métodos analíticos** declarados como indivíduos de `AnalyticalMethod`: DINA, LCA, IRT, K-Means/GMM/Hierárquico e SHAP/XAI, cada um ligado ao arquivo real do pipeline.
- **Proveniência**: `owl:Ontology` com `owl:versionInfo`, `owl:versionIRI`, `dcterms:created`, `prov:generatedAtTime`, `dcterms:source` e `prov:wasDerivedFrom` apontando para as fontes reais.

### 3.2 SKOS — dimensões contextuais

Sete esquemas e **51 conceitos** para as variáveis não curriculares já tratadas no dashboard:

| Esquema | Conceitos | Uso |
|---|---|---|
| `scheme_uf` | 27 | UF do curso |
| `scheme_regiao` | 5 | região do curso |
| `scheme_categoria_administrativa` | 6 | categoria da IES |
| `scheme_organizacao_academica` | 4 | organização acadêmica |
| `scheme_modalidade` | 2 | modalidade de ensino |
| `scheme_sexo` | 2 | sexo |
| `scheme_faixa_etaria` | 5 | faixa etária (recorte PRISM-EDU) |

Cada conceito tem `skos:prefLabel`, `skos:notation`, `skos:inScheme`, `skos:topConceptOf` e o inverso `skos:hasTopConcept`. Isso permite filtrar o grafo por contexto sem confundir contexto com currículo.

### 3.3 ABox — dados reais do ENADE 2023

A ABox padrão é construída a partir de:

- `dados/processados/analise_por_questao_ies_enade_2023.csv` (311.347 linhas);
- `processamento/mapeamento_grupos_enade.json` (edição → grupo → curso);
- `dados/processados/dina_estimativas_<curso>.csv` (28 cursos com artefato DINA, 923 estimativas ligadas).

Contagens reais no grafo publicado:

| Entidade | Indivíduos |
|---|---:|
| `AssessmentItem` | 923 |
| `CourseOffering` (IES × curso × edição) | 9.380 |
| `HigherEducationInstitution` | 1.318 |
| `InstitutionPerformance` | 1.318 |
| `InstitutionAreaPerformance` (IES × área) | 7.590 |
| `ItemPerformance` (agregado nacional por item) | 923 |
| `Competency` | 237 |
| `LearningObjective` | 448 |
| `GraduateProfile` | 126 |
| `ObjectiveCooccurrence` | 317 |
| `PsychometricEstimate` (DINA) | 923 |

Total: **240.366 triplas**, **23.788 sujeitos**, **23.603 indivíduos**.

### 3.4 Identidade e chaves (correção conceitual importante)

A versão anterior do grafo tratava `Q1` como identificador global. Isso é **errado**: a questão 1 de Medicina não é a questão 1 de Engenharia. A identidade do item passou a incluir **edição + área + questão**:

```
item_<edicao>_<grupo>_<questao>      →  item_enade_2023_36_q7
```

Decisões associadas:

- **`KnowledgeArea`** é global pelo **nome do curso** (Medicina é Medicina em qualquer edição).
- **`ExamArea`** preserva o `CO_GRUPO` real de cada edição, porque o código do grupo **não é estável entre anos**.
- **`CourseOffering`** = `CO_IES` + `CO_CURSO` (a oferta concreta), distinta de **`CourseProgram`** (o curso como programa).
- **IES sem nome** recebe o rótulo honesto `IES <código>`; nenhum nome foi inventado.

### 3.5 Artefatos publicados

| Formato | Arquivo | Bytes | Uso |
|---|---|---:|---|
| RDF/XML | `prism_edu.owl` | 20.247.704 | Protégé, OWLAPI, OWLAPY |
| Turtle | `prism_edu.ttl` | 11.659.345 | RDFLib, OAK, consultas rápidas |
| JSON-LD | `prism_edu.jsonld` | 34.056.877 | web semântica |
| N-Triples | `prism_edu.nt` | 37.690.417 | diff e versionamento |
| SHACL | `prism_edu.shapes.ttl` | 5.769 | validação de integridade |
| SPARQL | `queries/*.rq` | 8 consultas | perguntas de competência |
| Manifesto | `prism_edu_manifest.json` | 3.980 | contagens, fontes e SHA-256 |

Cada arquivo tem hash SHA-256 no manifesto, o que permite detectar divergência entre a ontologia e as fontes.

### 3.6 SHACL e consultas SPARQL

**8 NodeShapes** cobrem `AssessmentItem`, `CourseProgram`, `CourseOffering`, `ItemPerformance`, `InstitutionAreaPerformance`, `PsychometricEstimate`, `CurricularElement` e `ObjectiveCooccurrence`. Elas exigem, por exemplo, que todo item tenha exatamente uma edição e uma área, que taxas estejam em `[0,100]` e que estimativas DINA apontem para um item existente.

**8 consultas SPARQL** funcionam como *competency questions*:

| Consulta | Pergunta | Resultado real |
|---|---|---:|
| `q01_ocs_mais_criticos.rq` | OCs com maior taxa de deficiência | 20 linhas |
| `q02_cobertura_por_area.rq` | cobertura de OCs por área | 28 linhas |
| `q03_itens_sem_oc.rq` | itens sem OC associada | 0 linhas |
| `q04_dina_slip.rq` | itens com maior `slip` | 25 linhas |
| `q05_ies_por_area.rq` | IES com maior deficiência por área | 25 linhas |
| `q06_coocorrencia_ocs.rq` | pares de OCs que coocorrem | 25 linhas |
| `q07_visao_geral.rq` | itens, áreas e ofertas por edição | 1 linha |
| `q08_itens_criticos.rq` | itens críticos e OC associada | 40 linhas |

A consulta `q07` foi reescrita com subconsultas: a versão original fazia produto cartesiano item × oferta e levava **1.015,9 s**; agora executa em **0,5 s**.

### 3.7 Adaptadores para as quatro bibliotecas

`algoritmos/ontologia/adaptadores.py` expõe uma função por biblioteca, com fallback e mensagens de erro úteis:

- **`carregar_rdflib`** — parse RDF/XML com cache por `(caminho, mtime)`, evitando reparsear 20 MB a cada consulta.
- **`carregar_owlready2`** — `World` isolado, contagem de classes, propriedades e indivíduos, detecção de Java para raciocínio.
- **`carregar_owlapy`** — tenta caminho local absoluto antes da URI (correção específica de Windows), `classes_in_signature()` e `individuals_in_signature()`.
- **`carregar_oak`** — usa `.ttl` quando existe, `.owl` com `format="xml"`, e `all_entity_curies()` no lugar de `entities()` (que percorre entidade por entidade e é lento). Detecta instalação isolada via `PRISM_OAK_PYTHON`, `.venv-oak/` ou venv temporário.
- **`validar_shacl`** — `pyshacl` sobre o grafo e as shapes.
- **`status_stack`** — matriz de disponibilidade com versão e observação.

### 3.8 CLI e dashboard

- **`main.py`** — opção **16 → 1** pergunta quais edições incluir e chama `gerar_ontologia.py`; a **opção 8** valida a ontologia e a stack.
- **`processamento/gerar_ontologia.py`** — CLI com `--edicoes`, `--formato`, `--saida`, `--sem-dina`, `--sem-ies`, `--sem-coocorrencia`, `--limite-linhas`.
- **`processamento/validar_ontologia.py`** — reutiliza o grafo cacheado e checa stack, integridade, SHACL e bibliotecas opcionais.
- **Dashboard** — nova aba **20 “Ontologia Educacional (OWL 2 DL)”**: visão geral, TBox (classes e propriedades), execução de SPARQL e proveniência/stack. A lista `ABAS_DASHBOARD` passou a ter 20 entradas.

---

## 4. Validação executada (números reais)

### 4.1 Stack ontológica

| Biblioteca | Versão | Status |
|---|---|---|
| rdflib | 7.6.0 | OK (obrigatória) |
| owlready2 | 0.51 | OK |
| owlapy | 1.6.7 | OK |
| oaklib | 0.7.4 | OK (venv isolado) |
| pyshacl | 0.40.2 | OK (obrigatória) |

### 4.2 Checagens

| Checagem | Resultado |
|---|---|
| RDFLib — parse RDF/XML | **240.366 triplas / 23.788 sujeitos** |
| Integridade SPARQL (5 consultas) | **todas OK** (0 itens sem edição, 0 sem área, 0 cursos sem área, 0 taxas fora de `[0,100]`, 0 estimativas sem item) |
| SHACL (pyshacl) | **CONFORME** |
| Owlready2 | 26 classes / 83 propriedades / 23.603 indivíduos / Java disponível |
| OWLAPY | 28 classes / 23.661 indivíduos |
| OAK | 23.771 entidades, ontologia `https://prism-edu.example/onto` |
| HermiT | TBox **consistente** |
| Testes de regressão | **91 testes, OK, 18,075 s** |
| AppTest do dashboard | **0 exceptions**; métricas `Triplas RDF 240.366`, `Classes 26`, `Propriedades 61`, `Itens (ABox) 923`, `Indivíduos 23.603` |
| `py_compile` | OK nos arquivos alterados |

---

## 5. Defeitos reais encontrados e corrigidos

Esta seção é deliberadamente técnica: cada item foi um erro reproduzido, não uma hipótese.

| # | Defeito | Como apareceu | Correção |
|---|---|---|---|
| 1 | **IRI duplicada** `...onto#https://prism-edu.example/onto#dim_sexo` | o parser RDF/XML da OWLAPI recusou o arquivo | `_individuo` passou a aceitar `URIRef` **ou** nome local e nunca reconcatena o prefixo; `construir_skos` passou a usar o nome local |
| 2 | **`xml:base` ausente** | aviso do OWLAPI (“root element does not have an xml:base”) | serialização com `base=IRI_ONTOLOGIA` |
| 3 | **OWLAPY falhava no Windows** com `file:///C:/...` | `java.io.FileNotFoundException: C:\...\file:\C:\...` | o adaptador tenta `str(Path.resolve())` primeiro e a URI como fallback |
| 4 | **`q07` levava 1.015,9 s** | produto cartesiano item × oferta | reescrita com subconsultas; **0,5 s** |
| 5 | **OAK falhava no `.owl`** | escolhia `FunOwlImplementation` e não parseava RDF/XML | usa `.ttl` quando existe; senão `.owl` com `format="xml"` |
| 6 | **OAK `entities()` era lentíssimo** | ~0,4 s por entidade em 23 mil entidades | `all_entity_curies()` (5,3 s no total) |
| 7 | **Validador reparseava o grafo 13 vezes** | cada consulta abria um `Graph` novo | cache `@lru_cache` por `(caminho, mtime)` e grafo compartilhado |
| 8 | **OAK conflitava com o ambiente principal** | ~100 dependências (linkml, semsql, pydantic…) | instalação em **venv isolado**, detecção automática |
| 9 | **Rótulos `<NA>`** em OCs/competências | `pd.NA` convertido em texto | helper `_vazio` |
| 10 | **DINA ignorava 18 cursos de nome composto** | `slug("ENGENHARIA CIVIL")` = `engenharia_civil`, mas o arquivo é `dina_estimativas_engenhariacivil.csv`; só 10 cursos de nome único casavam | chave compacta (`slug_compacto`) e remoção de sufixo romano; **28 arquivos e 923 estimativas** passaram a ser ligados |

O defeito #1 é o mais relevante: ele só apareceu porque a OWLAPI foi usada como validador externo. O RDFLib aceitava a IRI malformada silenciosamente. Isso justifica a decisão de testar com **mais de uma** biblioteca.

---

## 6. Limitações declaradas e lacunas

1. **ABox padrão restrita ao ENADE 2023.** O grafo publicado cobre uma edição. `--edicoes todas` gera o grafo temporal completo, mas o artefato versionado é o de 2023 para manter tamanho e tempo de abertura razoáveis no Protégé.
2. **Desempenho item × IES × curso não está no grafo.** Essa tabela tem 311.347 linhas e geraria milhões de triplas. A ontologia guarda **agregados nacionais por item**, **agregados por IES** e **agregados por IES × área**; o cruzamento fino permanece no CSV, e o manifesto declara isso.
3. **IES sem nome.** Os arquivos de análise não trazem o nome da instituição; o rótulo é `IES <código>`. Nenhum nome foi inferido.
4. **DINA cobre 923 itens em 28 cursos.** Há **28 artefatos** `dina_estimativas_<curso>.csv` e **923 estimativas** ligadas (uma por item). Ainda assim, a estimativa existe apenas onde o pipeline gerou o artefato; não há imputação para itens sem arquivo.
5. **`CO_GRUPO` não é estável entre edições.** Por isso `ExamArea` é por edição e `KnowledgeArea` é pelo nome do curso. Comparações longitudinais devem usar a área de conhecimento, não o código do grupo.
6. **Raciocínio não roda na suíte de testes.** HermiT exige Java e é lento; a consistência da TBox foi verificada sob demanda e registrada, mas não está no CI.
7. **OAK em venv isolado.** No ambiente principal, `oaklib` conflita com Streamlit/pydantic. O adaptador detecta o venv, mas quem clonar o projeto precisa criá-lo (`requirements-ontologia.txt` documenta o procedimento).
8. **SKOS contextual é descritivo.** A presença de uma dimensão no grafo não autoriza inferência causal; o dashboard mantém o aviso “associação ≠ causalidade”.
9. **JSON-LD e N-Triples são grandes** (34,1 MB e 37,7 MB). São artefatos de interoperabilidade e diff, não de edição manual.
10. **Sem citações bibliográficas nesta rodada.** A verificação automática de literatura não estava disponível; o relatório não inventa referências. A seção 8 propõe o que buscar e onde.

---

## 7. Como reproduzir

```bash
# 1. Dependências mínimas (rdflib + pyshacl) e opcionais
python -m pip install -r requirements-ontologia.txt

# 2. Gerar a ontologia (ABox ENADE 2023)
python processamento/gerar_ontologia.py

# 3. Grafo temporal completo (todas as edições)
python processamento/gerar_ontologia.py --edicoes todas

# 4. Validar ontologia + stack
python processamento/validar_ontologia.py

# 5. Testes
python -m unittest discover -s testes -p "testes_regressao.py"

# 6. Pelo menu
python main.py    # 16 -> 1 (gerar) | 8 (validar)
```

No Protégé: `File > Open` → `modelos/ontologia/prism_edu.owl`; reasoner **HermiT** ou **Pellet**.

Para o OAK isolado (opcional):

```bash
python -m venv .venv-oak
.venv-oak\Scripts\python -m pip install oaklib
set PRISM_OAK_PYTHON=%CD%\.venv-oak\Scripts\python.exe
```

---

## 8. Roadmap de pesquisa de ponta

### 8.1 Curto prazo (consolidação)

- Rodar o reasoner no CI com `robot reason` ou `owlready2` + Java, falhando o build se a TBox ficar inconsistente.
- Adicionar **SHACL-AF** (regras) para derivar indicadores (ex.: classificação de item crítico) sem sair do grafo.
- Versionar a ontologia com **IRI de versão** já emitida (`https://prism-edu.example/onto/2026.11.14`) e publicar changelog.
- Empacotar o grafo como **RO-Crate** para reprodutibilidade FAIR.

### 8.2 Médio prazo (cobertura)

- ABox de **todas as edições** com `ExamArea` por ano e `KnowledgeArea` estável, permitindo consultas longitudinais no grafo.
- Materializar **item × oferta** apenas para os itens críticos (não para os 311 mil registros), usando reificação ou RDF-star.
- Ligar **classes latentes (LCA)** e **perfis de domínio (DINA)** como indivíduos reais, com `prov:wasDerivedFrom` apontando para os artefatos.
- Alinhamento com vocabulários externos: `schema.org` para instituições/cursos, e um mapeamento SKOS para classificações oficiais de área.

### 8.3 Longo prazo (contribuição científica)

- **Ontology Design Patterns (ODP)** para avaliação educacional em larga escala, reutilizável por outros exames (ENAMED, Licenciaturas, avaliações internacionais).
- **Competency questions formalizadas** e avaliadas por especialistas, com métricas de cobertura (quantas perguntas o grafo responde).
- Estudo de **qualidade ontológica** (consistência, completude, concisão, precisão) com revisão por pares.
- Integração com **SPARQL endpoint** e **SHACL** para auditoria contínua de novos artefatos.
- Submissão a veículos/eventos de web semântica aplicada à educação e de avaliação educacional; a busca bibliográfica deve ser feita em SciELO, ERIC, Scopus, Web of Science e Google Scholar, registrando DOIs — **sem fabricar referências**.

---

## 9. Arquivos relevantes

| Caminho | Papel |
|---|---|
| `algoritmos/ontologia/ontologia_owl.py` | gerador da TBox, SKOS, ABox, DINA e proveniência |
| `algoritmos/ontologia/adaptadores.py` | RDFLib, Owlready2, OWLAPY, OAK, SHACL e cache de grafo |
| `algoritmos/ontologia/shapes.ttl` | 8 formas SHACL |
| `algoritmos/ontologia/queries/*.rq` | 8 consultas SPARQL |
| `processamento/gerar_ontologia.py` | CLI da opção 16 → 1 |
| `processamento/validar_ontologia.py` | validação e matriz da stack |
| `modelos/ontologia/prism_edu.owl` | artefato Protégé |
| `modelos/ontologia/prism_edu_manifest.json` | manifesto com contagens, fontes e hashes |
| `dashboard/app.py` | aba 20 (ontologia) |
| `config.py` | `ABAS_DASHBOARD` com 20 abas |
| `testes/testes_regressao.py` | `TestOntologiaOWL` (7 testes) |
| `processamento/md_para_docx.py` | conversor Markdown → `.docx` (tabelas, ênfase e código) |
| `requirements-ontologia.txt` | stack ontológica opcional |

---

## 10. Observações finais

O PRISM-EDU agora tem uma **camada semântica formal** que não existia: uma ontologia OWL 2 DL construída sobre dados reais, validada por SHACL e por ferramentas independentes (RDFLib, Owlready2, OWLAPY, OAK e HermiT), com proveniência auditável e hashes das fontes.

O ponto central não é “ter um `.owl`”. É que a ontologia **define contratos de significado**: o que é um item, o que é uma oferta, o que é uma área de conhecimento, o que é um indicador de desempenho e o que é uma estimativa psicométrica. Com isso, consultas que antes exigiam código ad hoc passam a ser perguntas SPARQL, e a integridade deixa de depender de disciplina manual.

A rodada também mostrou o valor de validar com **múltiplas bibliotecas**: um erro real de IRI só apareceu na OWLAPI, e um gargalo real de 1.016 s só apareceu numa consulta SPARQL executada de verdade. Nenhum dos dois seria detectado por inspeção visual do arquivo.

**Estado final:** 91 testes OK; ontologia com 240.366 triplas e 23.603 indivíduos; SHACL conforme; TBox consistente no HermiT; dashboard com 20 abas e 0 exceções no AppTest. O relatório de **05/11/2026** permanece intacto como registro histórico; este documento cobre a rodada de **14/11/2026**.
