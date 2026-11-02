# Correções LCA e DINA — PRISM-EDU

Estes arquivos portam para o pacote PRISM-EDU o rigor metodológico que existia na versão em fases (`projetoENADE200826`) e que tinha se perdido na refatoração. São substitutos diretos: cada um vai no lugar do arquivo de mesmo nome dentro de `PRISM-EDU/`.

## Arquivos e onde colocar

- `algoritmos/lca/pipeline_lca.py` → substitui `PRISM-EDU/algoritmos/lca/pipeline_lca.py`
- `algoritmos/cdm/dina_em.py` → substitui `PRISM-EDU/algoritmos/cdm/dina_em.py`
- `executar_todos.py` → substitui `PRISM-EDU/executar_todos.py`

Basta copiar por cima. As assinaturas públicas (classes e funções que o `main.py` chama) foram mantidas, então o menu e o dashboard continuam funcionando.

## O que mudou no LCA (`pipeline_lca.py`)

O EM de mistura de Bernoulli foi mantido, mas voltou o que dava credibilidade à análise:

- **Convergência de verdade.** Antes, `self.convergiu = True` estava fixo no código — o modelo sempre dizia que tinha convergido. Agora o EM marca convergência só quando a variação da log-verossimilhança cai abaixo da tolerância antes do teto de iterações, e isso é reportado por IES na saída.
- **aBIC de Sclove (1987)** voltou, ao lado de BIC e AIC, na tabela de critérios.
- **Regra de seleção de k declarada a priori:** filtra por tamanho mínimo de classe e entropia ≥ 0,80, escolhe o menor BIC entre os sobreviventes e, se nenhum atinge a entropia, cai para o menor BIC com uma ressalva explícita na saída. A justificativa da escolha vai gravada em `01_relatorio_geral_por_ies.csv`.
- **Bootstrap com Jaccard máximo.** Antes o bootstrap comparava a classe *c* com a classe *c*, o que é errado porque os rótulos da LCA trocam de posição entre ajustes. Agora usa emparelhamento por Jaccard máximo (Hennig, 2007) e reporta média e IC 95%.
- **MCA de verdade.** `kmeans_sobre_mca` deixou de ser PCA disfarçado. Agora faz Análise de Correspondência Múltipla sobre a matriz indicadora (métrica qui-quadrado ponderada pelas massas marginais) e roda o K-Means sobre essas coordenadas.
- **Itens constantes removidos** antes do ajuste — as posições de padding (`*` → 0) não entram mais no modelo inflando o número de parâmetros.

## O que mudou no DINA (`dina_em.py`)

- **A matriz-Q não é mais aleatória.** A versão anterior gerava a Q com `rng.randint(0, 2, ...)` — o diagnóstico cognitivo estava ajustando contra um mapeamento item-competência sorteado, sem significado. Agora a Q é construída a partir da matriz item-OC do INEP (Anexo IX), lida de `mestre_questao_oc.csv`. Se esse arquivo não for encontrado, o script **falha com uma mensagem clara** em vez de fabricar uma Q — é de propósito.
- **EM de verdade.** A estimação voltou a ser o EM real sobre os 2^K padrões latentes (com guess/slip por item restritos a [0, 0,5] para identificabilidade e suavização por pseudo-contagens), no lugar da heurística de média de acertos que não usava a verossimilhança.
- A função de Q aleatória saiu do caminho de análise; sobrou só `_q_sintetica_para_teste`, claramente marcada como uso exclusivo de teste.

## O que mudou no `executar_todos.py`

A função `executar_dina_rapido` gerava outra Q aleatória no atalho de amostra. Foi desativada: agora ela avisa que o DINA correto roda por `algoritmos/cdm/dina_em.py`, para não gravar diagnóstico inválido na pasta de resultados.

## Dependência: `mestre_questao_oc.csv`

O DINA precisa da matriz item-OC do INEP. Ela é gerada pela fase de diagnóstico de OCs da versão em fases (`fase4_motor_ia/LCA/5_diagnostico_OCs.py`, que grava `arquivosgerados/RESULTADOS_LCA/mestre_questao_oc.csv`). O `dina_em.py` procura esse arquivo em alguns lugares, incluindo `modeloprojetoENADE2023/arquivosgerados/RESULTADOS_LCA/`. Copie-o para lá, ou ajuste `localizar_mestre_oc()` para o caminho onde ele estiver.

## Como validei

Rodei os dois módulos com dados sintéticos de parâmetros conhecidos:

- LCA com três classes latentes separáveis: `estimar_k` escolheu k=3 (verdadeiro=3), entropia 0,84, Jaccard de estabilidade 0,95 (IC 0,92–0,97), e a MCA concordou com a LCA (ARI 0,94).
- DINA com guess/slip verdadeiros de 0,15: recuperou g médio 0,150 e s médio 0,155 (erro médio ~0,01) e as prevalências de domínio quase exatas.

## O que NÃO foi tocado (fica para o Ivanylson — ver Parecer 2)

- O SHAP em `executar_todos.py` ainda tem alvo circular (a nota-alvo é a soma dos próprios itens usados como features).
- Os dados internacionais (PIAAC, EGEL, TECO) continuam como `placeholder` no `config.py`.
- `preprocessamento_serie_temporal.py` ainda tem o caminho fixo `C:\Users\usuario\...` na linha 43 (trocar pela constante do `config.py`).
- `CURSOS_REVERSO` no `config.py` colapsa cursos com nomes repetidos.
