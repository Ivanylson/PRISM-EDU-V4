# PRISM-EDU — Relatório de Tese: Avanços em IA Educacional sobre o ENADE

**Escopo:** correção das pendências do parecer (conteúdo fabricado, vazamento de alvo, drift temporal) e implantação de capacidades avançadas de IA (ontologia, RAG, MCP, prompt-tuning) mais nove análises de nível mestrado/doutorado sobre os microdados reais do ENADE 2004–2023.

**Princípio metodológico não negociável:** nenhum dado fabricado. Quando a informação não existe nos dados, o sistema declara explicitamente "Dados insuficientes" em vez de estimar ou inventar. Todo número é rastreável a um artefato real.

---

## 1. Correções do parecer (base)

### 1.1 Simulador contrafactual honesto
- Substituído o número fabricado "83% de reprovação futura" pela leitura do gap observado.
- O alvo do modelo passou a ser externo (`NT_DIS_CE` → `NT_CE_D1` → `NT_GER`), eliminando o vazamento de alvo (alvo circular = soma dos próprios itens-features).
- Quando não há alvo externo disponível, o simulador opera em modo `aritmetico` **declarado** (não disfarçado de ML).

### 1.2 Transparência da IA
- A seção de IA do dashboard deixou de exibir pseudo-código e passou a ler a configuração real (`config.py`): servidor, modelos disponíveis e política de grounding.
- Blocos inventados (Guardrails, "Nota para a Banca") foram removidos.

### 1.3 Drift temporal corrigido
- `montar_tendencia` varre os artefatos `modelos/drift/<prod>/drift_univariado_<ref>.csv` pela referência contida no nome do arquivo.
- Comparação por ciclo: como o ENADE **não avalia os mesmos cursos em anos consecutivos**, a referência válida é a edição anterior em que o curso foi avaliado.
- Modos: `consecutivas_tendencia` (default), `consecutivas`, `baseline` (referência fixa via `PRISM_DRIFT_BASELINE`, default 2019).

### 1.4 Testes anti-regressão
- Varredura automática dos dashboards por strings proibidas (números fabricados removidos) — falha a suíte se qualquer conteúdo inventado reaparecer.

---

## 2. Ontologia educacional (P1)

Grafo real construído a partir do mapeamento oficial do INEP e dos arquivos `analise_por_questao_ies_enade_*.csv`.

- **Entidades:** Edição, Área, Curso, Questão, Competência, Objetivo de Conhecimento (OC).
- **Relações:** `pertence_a`, `avaliado_em`, `avalia`, `coocorre_com`.
- **Tamanho real** (2 arquivos de amostra): 560–422 nós e 1.362–1.118 arestas, dependendo do recorte.
- **Exportação:** JSON-LD (`prism_edu.jsonld`) e Turtle (`prism_edu.ttl`), gerados sem dependência de bibliotecas RDF externas.
- **Validação de integridade:** nenhuma aresta órfã (todas apontam para nós existentes).

CLI: `python processamento/gerar_ontologia.py`

---

## 3. RAG local soberano (P2)

Pipeline de *Retrieval-Augmented Generation* sem dependências pesadas, preservando a soberania dos dados (nada sai para APIs externas).

- **Chunking** por parágrafos com sobreposição; 34.668 chunks indexados dos artefatos reais (dashboards .md, relatórios-síntese .pdf).
- **Indexação** TF-IDF (word + char n-grams, sublinear tf) do scikit-learn.
- **Recuperação** por similaridade de cosseno com limiar honesto: abaixo do limiar → "Dados insuficientes nas fontes fornecidas."
- **Grounding obrigatório:** o modelo só responde com base nos chunks recuperados e **deve citar [fonte]**.

CLI: `python processamento/analise_rag.py indexar` e `... consultar "<pergunta>"`

---

## 4. Servidor MCP (P3)

Servidor *Model Context Protocol* (JSON-RPC 2.0 sobre stdio) que expõe os artefatos do projeto a agentes de IA.

Ferramentas expostas (7): `listar_cursos_avaliados`, `resumo_ontologia`, `buscar_objetivos_conhecimento`, `drift_temporal`, `buscar_corpus_rag`, `simular_cenario`, `config_ia`.

- Implementação manual (sem SDK), compatível com a configuração `mcp` do OpenCode (`opencode.jsonc`).
- Validação: `python processamento/validar_mcp.py` (handshake, tools/list, tools/call) — 19 edições, 209 cursos.
- Ferramentas sem dados retornam explicitamente "Dados insuficientes".

---

## 5. Prompt-tuning e avaliação (P4)

**Honestidade metodológica:** não há treino de pesos de LLM. O pipeline gera dataset ancorado, seleciona exemplos few-shot e mede aderência.

- **Dataset:** pares instrução→resposta no formato chat-JSONL, com split treino/validação reprodutível.
- **Prompt-tuning:** seleção few-shot diversificada (cursos/questões distintos).
- **Avaliação:** métricas de *groundedness*, citação de fonte e **taxa de alucinação** (número que não existe na resposta-base).

CLI: `python processamento/avaliar_ia.py tudo`

---

## 6. Análises de tese E1–E9 (P5)

Todas ancoradas em colunas reais dos microdados (`CO_REGIAO_CURSO`, `CO_CATEGAD`, `CO_MODALIDADE`, `TP_SEXO`, `NU_IDADE`, `QE_I*`, `PESO_AMOSTRA`, notas externas `NT_*`). Dado ausente → "insuficiente".

| Código | Análise | Método |
|---|---|---|
| E1 | Equidade | gap de proficiência por região, categoria administrativa, sexo e modalidade |
| E2 | Valor agregado | resíduo proficiência observada − esperada pelo perfil socioeconômico (regressão) |
| E3 | Invariância | correlação das cargas do 1º componente (PCA) entre edições, nas questões comuns |
| E4 | Ciclo trienal | tendência por curso comparando apenas as edições em que ele foi avaliado |
| E5 | Formação | proficiência por modalidade, categoria e tempo de curso |
| E6 | Eficiência | fronteira DEA simples (proficiência por proxy de escala) |
| E7 | Perfis de IES | KMeans sobre indicadores agregados das IES |
| E8 | Desfechos distais | associação entre tercil de proficiência e variáveis distais (QE_I*) |
| E9 | Sensibilidade | robustez do ranking a peso amostral (tau de Kendall) e limiar de excelência |

**Interpretação crítica já validada:** o número de participantes do ENADE não é uma série linear — reflete os ciclos trienais de avaliação (2004→2007→2010→…) e a pandemia em 2021. A sazonalidade **não** deve ser lida como crescimento/queda do ensino.

CLI: `python processamento/analises_tese.py --ano 2019 --max-linhas 40000`

---

## 7. Integração e reprodutibilidade (P6)

- Motor `trienal` registrado em `MOTORES` de `executar_por_edicao.py` (roda E1/E2/E5/E6/E9 por edição).
- CLI geral em `main.py`; abas no dashboard (`dashboard/app.py`).
- Artefatos persistidos em `modelos/` (ontologia, rag, finetuning, analises_tese).
- Suíte de regressão unificada em `testes/testes_regressao.py` cobrindo todas as camadas.

---

## 8. Como reproduzir

```
python main.py                                   # menu interativo do projeto
python processamento/gerar_ontologia.py          # ontologia JSON-LD + Turtle
python processamento/analise_rag.py indexar      # indice RAG (TF-IDF)
python processamento/avaliar_ia.py tudo          # dataset + prompt-tuning + avaliacao
python processamento/analises_tese.py --ano 2019 # analises E1-E9
python processamento/validar_mcp.py              # valida servidor MCP
python -m unittest testes.testes_regressao       # suite de regressao
```

## 9. Limitações declaradas

- Análises E1–E9 usam amostragem (`--max-linhas`) por restrição de memória; os números são representativos, não censitários, e o próprio artefato registra o n.
- O prompt-tuning não altera pesos do modelo; é calibração de contexto (few-shot), não fine-tuning de parâmetros.
- O RAG usa TF-IDF (léxico) e não embeddings densos, por escolha deliberada de zero dependência pesada e auditabilidade.
- Dados internacionais EGEL/TECO permanecem documentados como não públicos (apenas PIAAC tem microdados reais).
