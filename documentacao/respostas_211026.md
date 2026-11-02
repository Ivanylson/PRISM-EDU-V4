# Resposta 21/10/2026 — PRISM-EDU (correções do parecer + IA avançada)

**Resumo executivo:** nesta etapa foram resolvidas as pendências apontadas no parecer (conteúdo fabricado, vazamento de alvo e drift temporal) e implantadas cinco camadas novas de IA, todas ancoradas em dados reais: **ontologia educacional** (JSON-LD/Turtle), **RAG local soberano** (TF-IDF), **servidor MCP** (7 ferramentas), **prompt-tuning + avaliação** (sem treino de pesos) e **nove análises de tese (E1–E9)**. A suíte de regressão subiu de 41 para **67/67 testes OK**. Princípio mantido em todo o código: quando o dado não existe, o sistema declara **"Dados insuficientes"** em vez de estimar ou inventar.

---

## 1. O que foi pedido ontem — está resolvido?

Sim. As duas pendências da véspera (20/10) estão **concluídas e verificadas**:

| Pendência de ontem | Status | Evidência |
|---|---|---|
| **Drift temporal** (comparação por ciclo, não por ano cru) | ✅ resolvido | `modelos/drift/tendencia_long.csv`, `tendencia_status_oc.csv` (143 OCs), `resumo_temporal.csv`; `montar_tendencia` varre por referência do filename |
| **ABAS[10] — vazamento de alvo** (alvo circular = soma dos próprios itens) | ✅ resolvido | alvo externo `NT_DIS_CE` → `NT_CE_D1` → `NT_GER`; features apenas `Q*` (`dashboard/app.py:3190`, `:3273`) |

Ambos foram reconfirmados nesta sessão por busca direta no código (`grep` em `dashboard/app.py` e nos artefatos de drift).

---

## 2. Correções do parecer (base)

1. **Simulador contrafactual honesto** — removido o número fabricado "83% de reprovação futura"; o alvo passou a ser externo e, sem alvo, o modo `aritmetico` é **declarado**.
2. **Transparência da IA** — a seção lê a configuração real de `config.py` (servidor, modelos, política de grounding); blocos inventados removidos.
3. **Drift temporal** — referência = edição anterior em que o curso realmente foi avaliado (o ENADE não repete cursos em anos consecutivos).
4. **Testes anti-regressão** — varredura automática dos dashboards por strings de conteúdo fabricado.

---

## 3. Novas camadas de IA

### 3.1 Ontologia educacional
- Grafo real do mapeamento oficial do INEP + `analise_por_questao_ies_enade_*.csv`.
- **1198 nós / 4335 arestas** (Edição, Área, Curso, Questão, Competência, Objetivo de Conhecimento).
- Exportação **JSON-LD** e **Turtle** sem bibliotecas RDF externas.
- CLI: `python processamento/gerar_ontologia.py`

### 3.2 RAG local soberano
- **34.668 chunks** indexados dos artefatos reais (dashboards .md + relatórios-síntese .pdf).
- TF-IDF (scikit-learn) + similaridade de cosseno; grounding obrigatório com citação `[fonte]`.
- Sem embeddings externos (soberania dos dados, zero dependência pesada).
- CLI: `python processamento/analise_rag.py indexar` e `... consultar "<pergunta>"`

### 3.3 Servidor MCP
- JSON-RPC 2.0 sobre stdio (implementação manual, sem SDK).
- 7 ferramentas: `listar_cursos_avaliados`, `resumo_ontologia`, `buscar_objetivos_conhecimento`, `drift_temporal`, `buscar_corpus_rag`, `simular_cenario`, `config_ia`.
- Validado: 19 edições, 209 cursos. CLI: `python processamento/validar_mcp.py`

### 3.4 Prompt-tuning + avaliação
- Dataset chat-JSONL ancorado, split treino/validação, few-shot diversificado.
- Métricas de **groundedness**, citação e **taxa de alucinação**.
- Sem treino de pesos (calibração de contexto, não fine-tuning de parâmetros).
- CLI: `python processamento/avaliar_ia.py tudo`

---

## 4. Análises de tese E1–E9

Ancoradas em colunas reais (`CO_REGIAO_CURSO`, `CO_CATEGAD`, `CO_MODALIDADE`, `TP_SEXO`, `NU_IDADE`, `QE_I*`, `PESO_AMOSTRA`, notas `NT_*`).

| Código | Análise | Método |
|---|---|---|
| E1 | Equidade | gap por região, categoria administrativa, sexo e modalidade |
| E2 | Valor agregado | resíduo observado − esperado pelo perfil socioeconômico |
| E3 | Invariância | correlação das cargas do 1º componente entre edições |
| E4 | Ciclo trienal | tendência por curso nas edições em que foi avaliado |
| E5 | Formação | proficiência por modalidade e tempo de curso |
| E6 | Eficiência | fronteira DEA simples |
| E7 | Perfis de IES | K-Means sobre indicadores agregados |
| E8 | Desfechos distais | tercil de proficiência × variáveis QE_I* |
| E9 | Sensibilidade | robustez do ranking a peso amostral (tau de Kendall) e limiar |

CLI: `python processamento/analises_tese.py --ano 2019 --max-linhas 40000`
Dashboard: nova aba **"Analises de Tese (E1-E9)"** (18ª aba), read-only dos artefatos.

---

## 5. Integração

- **`main.py`**: nova opção **16 — IA AVANÇADA** (ontologia, RAG, prompt-tuning, E1–E9, MCP, relatório).
- **`executar_por_edicao.py`**: motor `trienal` registrado em `MOTORES`.
- **`dashboard/app.py`**: 18 abas (nova aba de tese).
- **`requirements.txt`**: adicionado `python-docx` (demais dependências já presentes).
- **MCP com caminho absoluto** nos dois `opencode.jsonc` (PRISM-EDU e modeloprojetoENADE2023).

---

## 6. Verificação

| Validação | Resultado |
|---|---|
| `python -m unittest testes.testes_regressao` | **67/67 OK** |
| `py_compile` de todos os módulos novos | 0 erros |
| `gerar_ontologia.py` | 1198 nós / 4335 arestas |
| `analise_rag.py indexar` | 34.668 chunks |
| `avaliar_ia.py tudo` | dataset + few-shot + avaliação OK |
| `analises_tese.py --ano 2019` | E1–E9 OK (E2 corrigido: controles categóricos) |
| `validar_mcp.py` | handshake + tools/list + tools/call OK |
| MCP por caminho absoluto de outro diretório | OK |
| Smoke AppTest do dashboard | 0 exceções, 18 abas, aba de tese renderiza |

---

## 7. Como reproduzir

```
python main.py                                   # menu (opção 16 = IA Avançada)
python processamento/gerar_ontologia.py          # ontologia JSON-LD + Turtle
python processamento/analise_rag.py indexar      # índice RAG
python processamento/avaliar_ia.py tudo          # dataset + prompt-tuning + avaliação
python processamento/analises_tese.py --ano 2019 # E1-E9
python processamento/validar_mcp.py              # validação MCP
python -m unittest testes.testes_regressao       # suíte de regressão
```

## 8. Limitações declaradas

- As análises E1–E9 usam amostragem (`--max-linhas`) por memória; os números são representativos e o artefato registra o n.
- O prompt-tuning não altera pesos do modelo (few-shot).
- O RAG usa TF-IDF (léxico), não embeddings densos — escolha de auditabilidade e zero dependência pesada.
- Dados internacionais EGEL/TECO permanecem não públicos; apenas PIAAC tem microdados reais.
