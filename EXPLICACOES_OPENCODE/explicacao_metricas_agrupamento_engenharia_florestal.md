# Análise de Agrupamento — Engenharia Florestal (ENADE)

## O que são estes dados?

Este arquivo contém os resultados de um experimento de **clusterização** (agrupamento) aplicado aos dados do ENADE (Exame Nacional de Desempenho Estudantil) referentes ao curso de **Engenharia Florestal**. A ideia central é: se separarmos as instituições de ensino (ou os alunos) em grupos com base em suas características de desempenho, quantos grupos naturais existem e qual método de separação funciona melhor?

Foram testados **três métodos de agrupamento**, cada um com uma lógica diferente:

| Método | Como funciona (em palavras simples) |
|---|---|
| **KMeans** | Divide os dados em grupos tentando que cada ponto fique o mais perto possível do centro do seu grupo. É como colocar postos de atendimento no meio de bairros para minimizar a distância de todo mundo. |
| **GMM** (Mixture of Gaussians) | Parecido com o KMeans, mas aceita que os grupos possam ter formatos e tamanhos diferentes — mais flexível. |
| **Hierárquico** | Constrói uma "árvore" de relações entre os pontos, do mais parecido ao menos parecido, e depois corta essa árvore em若干 grupos. |

Para cada método, foram testadas **divisões de 2 a 6 grupos** (coluna `K_Grupos`), e a qualidade de cada divisão foi avaliada por duas métricas:

- **Silhueta** (Silhouette Score): Mede o quão bem cada ponto se encaixa no seu grupo comparado aos outros. Varia de -1 a 1. **Quanto maior, melhor.**
- **Davies-Bouldin**: Mede a "confusão" entre os grupos — quanto mais baixo, mais separados e claros estão os grupos.

Para o KMeans, há também a **Inércia** (soma das distâncias ao centro do grupo) — quanto menor, mais compactos estão os grupos.

---

## Principais achados

### 1. Menos grupos = melhor agrupamento

Há uma tendência muito clara e consistente: **quanto menos grupos, melhores são os resultados**. Veja a tabela resumo:

| K (nº de grupos) | Silhueta KMeans | Silhueta GMM | Silhueta Hierárquico | Davies KMeans | Davies GMM | Davies Hierárquico |
|---|---|---|---|---|---|---|
| **2** | **0.081** | **0.083** | **0.064** | **3.29** | **3.34** | **3.58** |
| 3 | 0.064 | 0.075 | 0.053 | 3.34 | 3.56 | 3.64 |
| 4 | 0.050 | 0.037 | 0.039 | 3.66 | 4.35 | 4.24 |
| 5 | 0.043 | 0.012 | 0.019 | 3.90 | 3.96 | 4.27 |
| **6** | **0.040** | **0.027** | **0.012** | **4.09** | **4.09** | **4.68** |

- A **Silhueta cai sistematicamente** ao aumentar o número de grupos, em todos os métodos.
- O **Davies-Bouldin sobe** sistematicamente, indicando que os grupos ficam cada vez mais "embaralhados".

**Interpretação prática:** Os dados de Engenharia Florestal não se dividem naturalmente em muitos subgrupos. A separação mais limpa é em **2 grupos** — possivelmente uma divisão binária do tipo "desempenho acima da média" vs. "desempenho abaixo da média".

### 2. O melhor cenário: K=2 com GMM

O método **GMM com 2 grupos** alcançou a melhor Silhueta de todo o experimento (0.083), seguido de perto pelo KMeans com 2 grupos (0.081). O GMM leva uma leve vantagem por ser mais flexível na hora de definir os limites dos grupos.

### 3. A Inércia do KMeans: uma história à parte

Enquanto todas as outras métricas pioram com mais grupos, a **Inércia do KMeans melhora constantemente** (de 10.508 em K=2 para 9.518 em K=6). Isso é esperado e **não é necessariamente bom** — é como recortar uma foto em pedaços cada vez menores: cada pedaço fica mais "puro", mas a foto como um todo perde sentido. A Inércia sozinha não é suficiente para escolher o melhor K.

---

## Anomalias e pontos de atenção

### Ponto crítico: GMM com K=4

Há um **pico de Davies-Bouldin no GMM com 4 grupos** (4.35), o pior valor de todo o experimento. Isso sugere que, ao tentar forçar 4 grupos com o método GMM, os limites entre eles ficam particularmente borrados. É como tentar separar uma turma em 4 times quando os alunos se misturam naturalmente em apenas 2.

### Silhueta do GMM com K=5: quase zero

A Silhueta do GMM com 5 grupos cai para **0.012** — praticamente zero. Um valor de Silhueta próximo de zero significa que os pontos estão quase equidistantes entre grupos vizinhos. Em termos práticos, **a separação em 5 grupos pelo método GMM é essencialmente inútil** para estes dados.

### Hierárquico: o mais fraco dos três

O método Hierárquico consistentemente apresenta os **piores resultados** em todas as configurações de K. Isso pode indicar que a estrutura dos dados de Engenharia Florestal não possui a hierarquia de semelhanças que este método pressupõe.

---

## Resumo visual da tendência

```
Silhueta (quanto maior, melhor)
K=2: ████████ 0.081 (melhor)
K=3: ██████   0.064
K=4: █████    0.050
K=5: ████     0.043
K=6: ████     0.040 (pior)

Davies-Bouldin (quanto menor, melhor)
K=2: ████     3.29  (melhor)
K=3: ████     3.34
K=4: █████    3.66
K=5: ██████   3.90
K=6: ███████  4.09  (pior)
```

---

## Recomendações práticas

1. **Use 2 grupos** como base para análises subsequentes. Todos os métodos e métricas convergem para essa conclusão. Não tente forçar 4, 5 ou 6 grupos nos dados de Engenharia Florestal — a estrutura natural dos dados não suporta essa granularidade.

2. **Prefira o GMM ou KMeans** ao Hierárquico para esta disciplina. O Hierárquico não conseguiu extrair padrões tão claros quanto os outros dois métodos.

3. **Interprete a divisão de 2 grupos com cautela.** Uma Silhueta de 0.08, embora seja a melhor configuração encontrada, ainda é **baixa** (o ideal seria acima de 0.25 para agrupamentos razoáveis). Isso indica que, mesmo com a melhor configuração, a separação entre grupos não é muito nítida. Os dados de Engenharia Florestal possuem uma **continuidade gradativa** de desempenho, sem fronteiras marcadas.

4. **Complementary approaches**: Para uma análise mais rica, combine estes resultados com outras técnicas já presentes no projeto (LCA, SOM Kohonen, etc.) para entender melhor a estrutura dos dados.

5. **Investigue a causa da baixa separabilidade.** Pode ser que as variáveis disponíveis não sejam suficientemente discriminantes, ou que a Engenharia Florestal, por ser um curso menor e mais homogêneo, tenha de fato menos variação entre as IES do que cursos maiores como Medicina ou Engenharia Civil.

---

*Análise gerada com base no arquivo `metricas_agrupamento_engenharia_florestal.csv` — 5 configurações testadas, 3 métodos de agrupamento, 2 métricas de validação.*
