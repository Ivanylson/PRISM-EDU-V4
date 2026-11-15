# PRISM-EDU — Relatório de Ampliações e Correções (15/11/2026)

**Escopo:** auditoria multiagente do projeto, adição de camada de governança de dados/métodos (21ª aba), implementação do motor IRT real e correção de defeitos estatísticos comprovados.

**Regra respeitada:** nada do trabalho existente foi removido. As mudanças são **aditivas** (nova aba, novo motor, novo módulo de auditoria, novos testes) ou **correções pontuais com defeito demonstrado** e registradas neste documento. Onde havia número fabricado, o número foi **substituído por artefato real** ou por um **cenário explicitamente rotulado como hipótese**.

**Baseline documental:** `documentacao/relatorio_resolucao_14112026.md` (20 abas, 91 testes, ontologia OWL). O estado anterior deste relatório é o ponto de partida; este documento descreve apenas o delta.

---

## 1. Sumário executivo

| # | Entrega | Tipo | Estado |
|---|---|---|---|
| 1 | Aba **“Qualidade, Proveniencia e Metodos”** (21ª), com 6 sub-abas | Adição | Implementada e testada |
| 2 | Motor **IRT real** (1PL/Rasch e 2PL por MML) + artefatos ENADE 2023 | Adição (substitui gráfico simulado) | 28 cursos gerados |
| 3 | **Auditoria de qualidade/proveniência** + 6 gates (G1–G6) | Adição | 21 edições auditadas |
| 4 | **15 testes novos** (`testes/testes_ampliacoes.py`) | Adição | Suíte 106 testes OK |
| 5 | Correção de **BH** e **Holm** (p-valores colapsavam) | Correção | Testado |
| 6 | Correção do **χ² de Mantel-Haenszel** | Correção | Testado |
| 7 | Correção do **alinhamento de resíduos do E2** | Correção | Testado |
| 8 | Remoção do bloco **“Impacto XGBoost”** fabricado | Correção | Reescrito como cenário declarado |
| 9 | Correção de **pastas de edição** (mkdir em leitura) | Correção | Testado por AppTest |
| 10 | Correção de **cache OWL**, **colunas ausentes** e **CO_GRUPO não numérico** | Correção | Testado por AppTest |

**Evidência global:** `Ran 106 tests ... OK` (50,3 s) e AppTest do dashboard sem exceções, com 21 abas e a nova aba renderizando 13 tabelas, 16 métricas e 6 gráficos.

---

## 2. Como a auditoria foi feita

Quatro agentes independentes, com escopos separados e evidência por arquivo/linha, sem executar o dashboard (o boot criava diretórios — ver §4.5):

| Agente | Escopo | Principais achados |
|---|---|---|
| **Dashboard/UX** | `dashboard/app.py` (5.6k linhas), `dashboard/abas/`, `componentes/` | Mapa das 20 abas e artefatos consumidos; 8 módulos `aba_*.py` órfãos; código duplicado (`_curto`, `_norm_oc`); 24 defeitos classificados S1–S3 |
| **Métodos estatísticos** | `algoritmos/estatistica/`, `algoritmos/analises_tese/`, IRT | BH e Holm invertidos; χ² MH fora da fórmula; E2 desalinhando resíduos; IRT inexistente (`modelos/irt/` vazio) apesar de declarado |
| **Dados/governança** | `processamento/`, `config.py`, `modelos/` | Falta de catálogo de dados, de manifesto de run e de gates; pastas de edição vazias sombreando artefatos populados |
| **Testes/documentação** | `testes/`, `documentacao/`, `README.md` | 91 testes na baseline; teste anti-fabricação era varredura de string (não pegava o `16.0`); contagens de abas desatualizadas |

Todas as correções da §4 foram aplicadas **somente após reprodução** do defeito (script mínimo ou teste falhando). O que não pôde ser provado como defeito ficou na §6 como pendência, sem alteração.

---

## 3. O que foi adicionado

### 3.1 Nova aba — “Qualidade, Proveniencia e Metodos” (21ª)

Arquivo: `dashboard/abas/aba_qualidade.py` (25,7 KB) · registro: `config.py` (`ABAS_DASHBOARD`) e `dashboard/app.py` (`elif aba == ABAS[20]`).

A aba foi criada como **camada de governança**, não como reescrita de nada. Ela responde a perguntas que nenhuma das 20 abas respondia: *o dado existe? está íntegro? de onde veio? qual método foi aplicado? o que é proibido comparar?*

| Sub-aba | Conteúdo | Fonte |
|---|---|---|
| **Cobertura e qualidade** | Linhas, colunas, itens `Q*` declarados × utilizáveis, cursos, IES, duplicatas, nulos em `NT_GER`, faixa de notas, alertas por edição | `modelos/qualidade/qualidade_por_edicao.csv` |
| **Dicionário de dados** | Tipo observado, % de nulos na amostra e exemplo por coluna, em cada edição; filtro por nome | `modelos/qualidade/catalogo_dados.json` |
| **Gates e pendências** | G1–G6 com status `ok/atenção/falha` + status de validação especialista da matriz-Q | `modelos/qualidade/gates.json`, `dados/processados/00_resumo_geral.csv` |
| **Manifesto do run** | Ambiente, parâmetros, inventário de motores por edição, avisos e download do JSON | `modelos/qualidade/qualidade_dados.json` |
| **IRT (método)** | Métricas do ajuste, mapa de itens (dificuldade × discriminação), TIF com erro-padrão, distribuição de θ, validade convergente e DIF por sexo | `modelos/irt/<edicao>/` |
| **Métodos e limitações** | Matriz de comparações **permitidas/proibidas** + registro das correções desta versão | Estático (documentação viva) |

Garantias de projeto da aba:

- **Nenhum número digitado à mão.** Toda tabela/gráfico lê um artefato; se o artefato não existe, a aba mostra o comando que o gera.
- **Cache invalidado por assinatura** `(caminho, mtime, tamanho)`, não por caminho puro.
- **Leitura sem efeito colateral:** não chama `pasta_saida_edicao()`, portanto não cria pastas.
- **`render_irt()` é API pública** e foi reutilizada na aba de Diagnóstico (ver §4.7).

### 3.2 Motor IRT real (`algoritmos/irt/pipeline_irt.py`, 25,6 KB)

O diretório `modelos/irt/` estava **vazio** e a ontologia já declarava `metodo_irt`; a única “IRT” do dashboard era um `np.random.normal`. Foi implementado um motor dicotômico de Teoria de Resposta ao Item:

- **Estimação:** máxima verossimilhança marginal (MML) com quadratura de Gauss-Hermite (`θ ~ N(0,1)`), otimizador L-BFGS-B com gradiente analítico.
- **Modelos:** **1PL/Rasch** (`a = 1`) e **2PL** (`a`, `b`), escolhidos por **BIC**; `a` parametrizado em `log(a)` com clipping para evitar overflow.
- **Proficiência:** EAP + erro-padrão posterior por aluno.
- **Diagnóstico:** infit/outfit MNSQ, confiabilidade marginal, correlação residual (independência local), TIF, α de Cronbach e ω de McDonald.
- **DIF:** Mantel-Haenszel por sexo com classificação ETS e correção FDR (BH).
- **Robustez:** descarte de itens constantes, tratamento de casos incompletos, `versao_irt` e manifesto por execução.
- **Integração:** `MOTORES["irt"] = ("algoritmos.irt.pipeline_irt", "executar_irt_edicao")` em `executar_por_edicao.py`; CLI própria.

**Artefatos gerados — ENADE 2023:**

| Métrica | Valor |
|---|---|
| Cursos | 28 |
| Itens calibrados | 923 |
| Arquivos | 142 (20,8 MB) |
| Modelo escolhido | 23 cursos 1PL · 5 cursos 2PL |
| Confiabilidade marginal | 0,537 – 0,735 (média 0,645) |
| Outfit MNSQ (itens) | 0,78 – 1,22; **nenhum** item fora de [0,5; 1,5] |
| Maior correlação residual | 0,17 (nenhum par acima de 0,30) |
| Convergência | 28/28 |

**Ressalva declarada (importante para a banca):** `r(θ, NT_GER)` ficou entre 0,953 e 0,977, mas **não é validade externa** — `NT_GER` é calculada a partir dos mesmos itens usados no ajuste. É evidência de coerência interna da escala, não de relação com um critério independente. A aba mostra essa ressalva no texto do gráfico.

**Comando:**

```bash
python algoritmos/irt/pipeline_irt.py --edicao enade_2023
# ou via orquestrador
python executar_por_edicao.py --edicoes enade_2023 --motores irt
```

### 3.3 Auditoria de qualidade e gates (`processamento/auditoria_qualidade.py`, 22,4 KB)

Gera quatro artefatos em `modelos/qualidade/`:

| Arquivo | Conteúdo |
|---|---|
| `qualidade_por_edicao.csv` | 21 linhas × 21 colunas (linhas, itens, cursos, IES, duplicatas, nulos, faixa de notas, SHA-256, status, alertas) |
| `catalogo_dados.json` | 664 KB — dicionário por edição: tipo observado, nulos na amostra, exemplo, convenções |
| `artefatos_por_motor.csv` | Inventário motor × edição (arquivos, bytes, padrões esperados/faltando) |
| `gates.json` | 6 gates com descrição, status e detalhe auditável |
| `qualidade_dados.json` | Manifesto: ambiente, parâmetros, avisos, resumo dos gates, validação especialista |

**Resultado atual dos gates:**

| Gate | Status | Detalhe |
|---|---|---|
| G1 cobertura ENADE | **OK** | 19 edições presentes; 2020 declarada sem dados |
| G2 integridade dos microdados | **OK** | nenhuma edição com erro de leitura |
| G3 alertas de qualidade | **ATENÇÃO** | `enamed_2025` e `licenciaturas_2025` |
| G4 artefatos por motor | **ATENÇÃO** | 72/215 combinações completas |
| G5 paridade matriz × dicionário | **OK** | 28/28 matrizes com dicionário |
| G6 validação especialista | **ATENÇÃO** | 28/28 cursos pendentes de validação humana |

**Comando:** `python processamento/auditoria_qualidade.py --edicoes all` (28,7 s).

Os gates são **honestos por construção**: não convertem ausência de artefato em sucesso. G4 e G6 ficam em “atenção” justamente porque há trabalho pendente — e a aba mostra exatamente quais combinações faltam.

### 3.4 Testes novos (`testes/testes_ampliacoes.py`, 15 testes)

| Grupo | Testes | O que garante |
|---|---|---|
| IRT | 5 | Recuperação de `a`, `b` e θ em dados simulados (r > 0,75 / 0,90 / 0,70); 1PL com `a = 1`; BIC preferindo 1PL quando os dados são Rasch; TIF correta; descarte de itens constantes |
| Testes múltiplos | 3 | BH e Holm com valores conhecidos; monotonicidade, limite ≤ 1 e **não colapso no menor p** |
| Mantel-Haenszel | 1 | χ² e OR conferem com a fórmula fechada em estrato único |
| E2 | 1 | Com índice não trivial e NaN no meio, o resíduo vai para a IES certa (topo = efeito +10, base = −10) |
| Gates | 3 | Ordem G1–G6; `falha` quando há edição com erro; `atenção` quando há validação pendente |
| Registro estrutural | 2 | 21ª aba registrada e motor `irt` no orquestrador |

### 3.5 Integrações

- `config.py`: `ABAS_DASHBOARD` passa de 20 para **21** itens; último = `"Qualidade, Proveniencia e Metodos"`.
- `dashboard/app.py`: branch `elif aba == ABAS[20]` antes do rodapé; `render_irt` reutilizado na aba de Diagnóstico; comentários de contagem de abas corrigidos (16/20 → 21).
- `executar_por_edicao.py`: motor `irt` registrado.
- `requirements.txt`: `pandas>=2.2` (necessário para `groupby(..., include_groups=False)` já usado no código).

---

## 4. Correções aplicadas (com defeito comprovado)

### 4.1 BH e Holm — p-valores ajustados colapsavam

**Antes (`algoritmos/estatistica/dif.py`):** o laço percorria do menor para o maior p aplicando `min()` corrente — o acumulador nunca podia subir, então **todos** os ajustados terminavam iguais ao menor valor.

**Agora:** BH percorre do maior para o menor (`min` corrente, como manda Benjamini-Hochberg); Holm percorre do menor para o maior (`max` corrente, como manda Holm).

| Entrada | BH antes | BH agora | Holm antes | Holm agora |
|---|---|---|---|---|
| `[0,001; 0,008; 0,039]` | todos = 0,003 | **0,003 · 0,012 · 0,039** | todos = 0,003 | **0,003 · 0,016 · 0,039** |

**Impacto:** as listas de DIF e os post-hocs não paramétricos estavam inflando descobertas (tudo virava significativo no menor p) ou mascarando itens. A correção muda a **classificação ETS** dos itens, não apenas a estética da tabela.

### 4.2 χ² de Mantel-Haenszel — fórmula incorreta

**Antes:** `(Σ(a_s − E_s)/√Var_s)² / n_estratos` — soma padronizada por estrato dividida pelo número de estratos.

**Agora:** `(Σ a_s − Σ E_s)² / Σ Var(a_s)` — a estatística MH canônica.

**Validação:** teste com estrato único (`a=30, b=10, c=20, d=40`) confere com a fórmula fechada em 3 casas.

### 4.3 E2 (valor agregado) — resíduos atribuídos ao aluno errado

**Antes:** `pd.concat([...reset_index(drop=True)...])` + `dropna()` e depois `d.loc[dados.index]` com o índice **resetado**, enquanto `d` mantinha o índice original. Os resíduos eram associados a linhas erradas e, em bases com índice não trivial, o `loc` levantava `KeyError`.

**Agora:** máscara booleana aplicada em `d` e em `Xc` **antes** do ajuste, preservando a indexação original.

**Validação:** teste sintético com efeito fixo por IES (1 → −10, 2 → 0, 3 → +10), índice começando em 1000 e NaN no meio: topo = IES 3, base = IES 1, valores acima de +9 e abaixo de −9.

### 4.4 IRT simulada no dashboard → IRT real

**Antes:** bloco “Análise de Esforço vs. Competência (IRT / Padrão de Resposta)” exibia `np.random.seed(42)` + duas normais de 100 pontos, com título “dados simulados ilustrativos”, dentro de uma aba de diagnóstico e seguido de prescrições por quadrante.

**Agora:** o bloco chama `render_irt()` e mostra o ajuste real do curso selecionado; os textos de interpretação dos quadrantes permanecem como **nota metodológica**, sem gráfico fabricado.

### 4.5 Pastas de edição criadas durante a navegação

**Antes:** `_pasta_motor()` chamava `pasta_saida_edicao()`, que **sempre** executa `mkdir`. Bastava navegar para criar `modelos/<motor>/<edicao>/` vazia — e, na visita seguinte, essa pasta vazia “ganhava” da pasta raiz populada, produzindo “artefato não encontrado” falso. O mesmo ocorria na descoberta de arquivos da aba OpenCode (uma chamada por módulo × edição).

**Agora:** novo `_pasta_edicao_leitura(motor, edicao)` **sem `mkdir`**, que só devolve a subpasta se ela for diretório e tiver conteúdo; caso contrário devolve a raiz do motor. Aplicado em `_pasta_motor`, nos três carregadores de LCA, na busca de arquivos LCA e na descoberta da aba OpenCode.

**Observação:** as pastas vazias já existentes em `modelos/irt/enade_2004..2022` etc. **não foram apagadas** (regra de não remover trabalho); a nova aba e o resolvedor de IRT simplesmente as ignoram.

### 4.6 Cache do grafo OWL nunca invalidava

**Antes:** `@st.cache_resource def _grafo_owl(caminho_str, _mtime)` — o prefixo `_` faz o Streamlit **não** incluir o argumento na chave de cache. Regenerar `prism_edu.owl` no mesmo caminho continuava servindo o grafo antigo.

**Agora:** o parâmetro se chama `mtime` e entra na chave. O grafo é recarregado quando o arquivo muda.

### 4.7 Colunas ausentes e `CO_GRUPO` não numérico

- `qdet.get("QTD_ACERTOS", 0).fillna(0)` → `AttributeError` quando a coluna não existia (`int` não tem `.fillna`). Agora usa `pd.to_numeric(...).fillna(0)` e soma com `QTD_ERROS`.
- `CURSOS_MAP.get(int(cg), ...)` → `ValueError` com `CO_GRUPO` não numérico. Agora há conversão protegida (`try/except (TypeError, ValueError)`), preservando o rótulo textual.

### 4.8 Bloco “Impacto XGBoost” fabricado

**Antes:** subtítulo “Simulação de Intervenção (Impacto XGBoost)” com `ganho_preditivo = (melhoria / 100) * 16.0` — 16 p.p. fixos, sem modelo, apresentados como “Projeção Preditiva”.

**Agora:** “Cenario Aritmetico de Intervencao (nao e projecao de modelo)”, com nota explicando que não existe modelo treinado ligando as fases de Sensemaking à nota, que o valor é uma **hipótese declarada pelo usuário** somada à taxa observada, e que uma estimativa real exigiria desenho quase-experimental com grupo de comparação.

### 4.9 Outros ajustes de higiene

- `requirements.txt`: `pandas>=2.2` (alinha com `include_groups=False` já usado).
- Comentários e docstrings “16 abas” → 21.
- `algoritmos/irt/pipeline_irt.py`: `np.exp` com clipping para eliminar `RuntimeWarning: overflow` durante a busca do otimizador.
- `dashboard/abas/aba_qualidade.py`: `style.applymap` → `style.map` (pandas 2.1+ deprecation).

---

## 5. Evidências de validação

### 5.1 Suíte de testes

```text
python -m unittest testes.testes_regressao testes.testes_ampliacoes
Ran 106 tests in 50.317s
OK
```

Baseline: 91 testes. Delta: +15 (todos os novos passando), nenhum teste antigo removido ou desativado.

> Nota operacional: no PowerShell, `python -m unittest` grava o banner em stderr e o shell retorna código 1 mesmo com `OK`. A validação deve ser feita pela linha `Ran N tests` + `OK`, não pelo exit code.

### 5.2 Dashboard (Streamlit AppTest)

| Verificação | Resultado |
|---|---|
| Boot de `dashboard/app.py` | sem exceções |
| Abas no seletor | 21, última = “Qualidade, Proveniencia e Metodos” |
| Render da nova aba | sem exceções |
| Sub-abas | 6 |
| Tabelas / métricas / gráficos | 13 / 16 / 6 |
| Cabeçalho | “Qualidade, Proveniencia e Metodos” |

### 5.3 Artefatos gerados

| Caminho | Conteúdo |
|---|---|
| `modelos/irt/enade_2023/` | 142 arquivos, 20,8 MB, 28 cursos, `irt_resumo_geral.csv`, `irt_manifesto.json` |
| `modelos/qualidade/` | 5 arquivos, incluindo `gates.json` (3 ok / 3 atenção / 0 falha) e `catalogo_dados.json` (664 KB) |

---

## 6. Achados não corrigidos (backlog priorizado)

Estes itens foram identificados com evidência, mas **não** foram alterados nesta rodada — seja por exigirem decisão de escopo/conteúdo, seja por não haver defeito provado. Ficam registrados para não se perderem.

### P1 — afetam resultado ou confiabilidade

| ID | Achado | Por que não foi corrigido agora | Encaminhamento |
|---|---|---|---|
| P1.1 | **E3 (invariância fatorial) nunca executa**: não aparece nos JSON de `modelos/analises_tese/` e o motor por edição só roda E1/E2/E5/E6/E9 | Exige itens-âncora e decisão sobre qual matriz comparar; implementar às pressas produziria número frágil | Implementar como análise própria, com âncoras explícitas, e publicar no JSON |
| P1.2 | **E6 “DEA” não é DEA**: é fronteira simples de proficiência por proxy de custo | Reescrever exige insumo de custo que o projeto não tem | Renomear para “fronteira descritiva” e documentar a limitação |
| P1.3 | **B6**: `_carregar_analise_ies(ano=2025)` concatena Licenciaturas e ENAMED **sem coluna de origem**, misturando exames em agregações por `CO_GRUPO` | Corrigir muda números já publicados em telas existentes; precisa de validação com o usuário | Adicionar coluna `ORIGEM_EXAME` e filtrar por ela nas telas; comparar antes/depois |
| P1.4 | **Teste anti-fabricação é varredura de string** e não pegava `(melhoria / 100) * 16.0` | Substituir por AST é mudança de infraestrutura de teste | Trocar por inspeção AST das constantes numéricas em blocos de “projeção” |
| P1.5 | **`os._exit(0)` no botão “Sair e Fechar”** mata o processo do servidor para todos os usuários | comportamento intencional em ambiente local; mudar afeta operação | Trocar por `st.stop()`/mensagem e encerramento controlado |

### P2 — robustez e arquitetura

| ID | Achado | Encaminhamento |
|---|---|---|
| P2.1 | 8 módulos `dashboard/abas/aba_*.py` órfãos + `componentes/utils.py` duplicando helpers com drift (`_carregar_analise_ies` sem `tipo`) | Consolidar em um único caminho de carregamento; remover só depois de migrar |
| P2.2 | `_curto` e `_norm_oc` definidos duas vezes em `app.py` (a segunda definição vence silenciosamente) | Unificar e apagar a duplicata |
| P2.3 | `st.stop()` dentro de `except` na aba OpenCode aborta o dashboard inteiro | Trocar por aviso local |
| P2.4 | Acessos sem guarda a `dfc["curso"]`, `dfc["ies"]`, `df_reanalise_ies["ies"]` | Usar `_tem_colunas`/`get` antes de indexar |
| P2.5 | `except Exception: pass` em ~59 pontos esconde corrupção de artefato | Logar e mostrar aviso, mantendo o fallback |
| P2.6 | `@st.cache_*` definidos dentro de blocos condicionais de aba | Mover para o topo do módulo |
| P2.7 | Ausência de CI, lockfile e ambiente reprodutível | Adicionar workflow de testes + `requirements` travado |

### P3 — higiene/documentação

| ID | Achado |
|---|---|
| P3.1 | Mojibake em algumas strings de UI (`Anǭlises`, `�?"`) em abas 13/18 |
| P3.2 | Textos “5 macro-áreas” onde a lista tem 4 |
| P3.3 | `injetar_css()` morto, com paleta escura fixa que conflitaria com o tema |
| P3.4 | `PASTA_MOD` duplicada nas raízes de busca da aba OpenCode; `st.markdown("---")` duplicado; variável `cor_barra` não usada |
| P3.5 | Aba “Análises adicionais” (G4) é só prosa, sem tabela/gráfico |

---

## 7. Como reproduzir

```bash
# 1. Testes (106)
python -m unittest testes.testes_regressao testes.testes_ampliacoes

# 2. IRT — ENADE 2023
python algoritmos/irt/pipeline_irt.py --edicao enade_2023

# 3. Auditoria de qualidade + gates
python processamento/auditoria_qualidade.py --edicoes all

# 4. Dashboard
streamlit run dashboard/app.py
# aba 21: "Qualidade, Proveniencia e Metodos"
```

---

## 8. Limites e riscos declarados

1. **IRT por edição:** apenas ENADE 2023 foi calibrado. As demais edições têm pastas vazias e a aba informa como gerar; nenhum resultado é extrapolado.
2. **Modelo por curso:** 23 dos 28 cursos preferiram 1PL por BIC. Isso é um resultado, não uma falha: a maioria das escalas ENADE é aproximadamente Rasch na amostra.
3. **`r(θ, NT_GER)` alto não é validação externa** — os dois usam os mesmos itens (ver §3.2).
4. **Gates em “atenção” são intencionais:** G4 (cobertura de artefatos) e G6 (validação humana da matriz-Q) refletem pendências reais, não erro de código.
5. **Amostragem da auditoria:** as métricas de nulos/duplicatas usam amostra inicial do arquivo, declarada no artefato; não substituem uma varredura completa linha a linha.
6. **Sem git:** o diretório não é repositório, portanto não há diff/commit associado a esta rodada; a rastreabilidade está neste relatório + `irt_manifesto.json` + `qualidade_dados.json` (ambiente, versões, parâmetros, timestamps).

---

## 9. Arquivos criados e alterados

**Criados**

| Arquivo | Papel |
|---|---|
| `algoritmos/irt/__init__.py` | Pacote do motor IRT |
| `algoritmos/irt/pipeline_irt.py` | Motor 1PL/2PL por MML, diagnóstico, DIF, CLI |
| `processamento/auditoria_qualidade.py` | Auditoria de microdados, catálogo, inventário e gates |
| `dashboard/abas/aba_qualidade.py` | 21ª aba (6 sub-abas) |
| `testes/testes_ampliacoes.py` | 15 testes das ampliações e correções |
| `modelos/irt/enade_2023/*` | 142 artefatos IRT (28 cursos) |
| `modelos/qualidade/*` | 5 artefatos de qualidade/proveniência |
| `documentacao/relatorio_ampliacoes_15112026.md` | Este relatório |

**Alterados**

| Arquivo | Mudança |
|---|---|
| `config.py` | 21ª aba em `ABAS_DASHBOARD` |
| `dashboard/app.py` | Branch `ABAS[20]`; IRT real no lugar do simulado; `_pasta_edicao_leitura`; correções de cache OWL, colunas e `CO_GRUPO`; cenário de intervenção reescrito; contagens de abas |
| `executar_por_edicao.py` | Motor `irt` registrado |
| `algoritmos/estatistica/dif.py` | BH corrigido; χ² MH corrigido |
| `algoritmos/estatistica/anova_robusta.py` | Holm corrigido |
| `algoritmos/analises_tese/analises_tese.py` | E2 alinhado ao índice original |
| `requirements.txt` | `pandas>=2.2` |

**Preservado integralmente:** todas as 20 abas anteriores, todos os motores, todos os artefatos e todas as pastas existentes (inclusive as vazias).
