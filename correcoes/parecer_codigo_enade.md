# Parecer — código do projeto ENADE (projetoENADE200826.zip)

Revisado em 01/09/2026. Li a fundo o núcleo do pipeline (pré-processamento, LCA da fase 4, DINA da fase 6 e o módulo de estatística paramétrica) e fiz uma varredura de qualidade nos 55 arquivos `.py`. Não abri linha por linha o dashboard de 2871 linhas nem alguns scripts exploratórios da fase 6. Também não tive a versão *anterior* do código em mãos: comparei com as cópias `old_`/`old2_` guardadas em `tentativas/` e com a maturidade geral, então quando eu digo "melhorou" é isso que estou medindo. Se você me apontar o que exatamente o aluno mexeu, eu avalio o delta com precisão.

## Veredito

O núcleo estatístico melhorou de verdade e está acima do que se vê num aluno de graduação. Mas "melhor" está escondendo duas coisas que, para um paper, pesam mais que a elegância do código: o projeto **não roda de ponta a ponta como está** (caminho fixo de teste, dependências não declaradas, falha que passa por sucesso), e o módulo de estatística paramétrica **repete a lacuna de pressuposto que o Davi já apontou** nos papers de carbono/SE4AI. Antes de submeter, é nesses dois pontos que eu mexeria primeiro.

## O que de fato ficou bom

A LCA em `fase4_motor_ia/LCA/0_pipeline_principal_LCA.py` está bem feita: EM em espaço-log com log-sum-exp para estabilidade numérica, 20 inicializações para escapar de ótimo local, e seleção de *k* por BIC/AIC/aBIC combinada com entropia e tamanho mínimo de classe — com a regra de decisão declarada *a priori* (linhas 349-385) em vez de escolhida depois de ver o resultado. A fórmula do aBIC de Sclove está correta, a entropia de Celeux & Soromenho está correta, e há bootstrap de estabilidade por Jaccard (Hennig) e checagem cruzada com K-means. É triangulação real, não enfeite.

O DINA da fase 6 também está sério: identificabilidade garantida travando *guess* e *slip* em [1e-4, 0,5], suavização por pseudo-contagens, e a honestidade de escrever, no próprio código (linhas 461-463), que BIC/AIC do DINA nacional e da LCA por IES não estão na mesma escala e por isso só a correlação item a item deve ser interpretada. Muita gente publicada não tem esse cuidado.

Some a isso a documentação com referências reais (de la Torre, Nylund, Collins & Lanza, Hennig, Greenacre), as decisões metodológicas escritas por extenso — tratar branco e anulada como não-acerto, com a limitação reconhecida (linhas 129-147) — e um detalhe que me chamou atenção: em vários pontos ele anota explicitamente "sem fillna(0)" para não transformar ausência de nota em zero. Ele aprendeu a lição do zero que suja média. Na fase 4 usou Mann-Whitney, não-paramétrico, onde cabia (`3_ies_padrao_misto.py`). Ou seja: ele *sabe* fazer certo — o que torna o deslize da ANOVA mais estranho, não menos.

## O que impede rodar ou reproduzir

**1. Caminho fixo que quebra na sua máquina. [certeza]** Em `fase4_motor_ia/LCA/2b_arquetipos_nacionais.py:49` está `PASTA_DADOS = Path("/home/claude/dados_teste")`. Isso é um path Linux de ambiente de teste que vazou para o código; no Windows do braga ele simplesmente não existe e o script morre. Trocar por caminho relativo via `Path(__file__)`, como o resto do projeto já faz.

**2. Sem `requirements.txt`, sem README, sem `pyproject`. [certeza]** Ninguém recria o ambiente nem sabe a ordem de execução ou as versões de pandas/scikit/scipy que ele usou. Para o SBIE, na hora de entregar artefato reproduzível, é esse o ponto que trava. Um `requirements.txt` com versões travadas e um README de dez linhas (como rodar, o que entra, o que sai) resolvem.

**3. Falha silenciosa no pré-processamento. [certeza → provável no impacto]** `preprocessamentoMicrodados.py` embrulha o processo inteiro num `try/except` que só dá `print` do erro (linhas 136-137) e não repropaga. O `menu_principal.py` chama esse script com `check=True` esperando detectar falha — mas o script sai com código 0 mesmo quando quebra. Então o pipeline anuncia "SUCESSO" com o CSV pela metade ou inexistente. No projeto todo são 16 `except:` nus e 18 `except Exception`; a maioria está na cola do OpenCode (`gerar_explicacao_opencode.py`), o que é um alívio — o núcleo estatístico está limpo —, mas o do pré-processamento é o perigoso porque mascara dado faltando.

## O que um revisor de paper vai cutucar

**4. A "MCA" não é MCA. [certeza]** `kmeans_sobre_mca` (em `0_pipeline_principal_LCA.py`, linhas 461-488) faz SVD de matriz binária padronizada por z-score. Isso é PCA, não Análise de Correspondência Múltipla — que opera na matriz indicadora com métrica qui-quadrado ponderada pelas frequências marginais. O próprio docstring admite "implementação simplificada". Um revisor de psicometria pega na hora. Ou implementa MCA de verdade (`prince`/`mca`) ou renomeia para "K-means sobre PCA da matriz binária" no código e no texto.

**5. Itens mortos entrando no modelo. [provável]** `extrair_38_questoes` concatena o vetor de FG com o de CE e preenche até 38 caracteres. O ENADE 2023 objetivo tem por volta de 35 questões (8 de FG + 27 de CE — vale confirmar no dicionário do INEP). As posições que sobram viram coluna `*` → 0 constante e entram na LCA e no DINA como item que não varia, inflando o número de parâmetros (um por item, por classe) e endurecendo o BIC/aBIC à toa, o que pode empurrar a escolha de *k* para baixo. Remover colunas constantes por curso antes de ajustar.

**6. Alinhamento da matriz-Q assumido, não verificado. [provável]** Em `fase6_lca_para_cdm_restrito.py:329` força-se `df_q['Questao'] = COLUNAS_Q` depois de ordenar o mestre por `posicao`. Isso assume que a ordem e a quantidade de itens em `mestre_questao_oc.csv` batem 1:1 com Q1..Q38 do vetor de respostas. Se algum curso tiver número de linhas diferente de 38 ou ordem diferente, das duas uma: a matriz-Q casa com as questões erradas em silêncio — e aí o DINA daquele curso está medindo a competência trocada —, ou o script levanta exceção. E o laço de cursos (linha 286) não tem `try/except`, então uma exceção derruba a rodada inteira. Verificar o alinhamento explicitamente e blindar curso a curso.

**7. ANOVA sem checar pressuposto. [certeza]** `fase6_estatistica_parametrica.py:54` roda `f_oneway` sobre a nota por região sem Shapiro/Levene e sem alternativa não-paramétrica (Kruskal-Wallis). É o mesmo tipo de coisa que o Davi apontou nos outros papers. Com centenas de milhares de alunos, o p-valor vira "< 0,001" automático e não diz nada; o eta-quadrado — que ele já calcula, bom — é o que interessa. Eu lideraria pelo tamanho de efeito e ou testaria o pressuposto ou trocaria por Kruskal-Wallis. Ele já usa Mann-Whitney na fase 4, então é inconsistência, não desconhecimento.

## Software e organização (menor, mas cobra juros)

**8. `estimar_dina` duplicado. [certeza]** O mesmo estimador está em `fase6_dina_em.py` (que se anuncia como "módulo compartilhado") e copiado inteiro dentro de `fase6_lca_para_cdm_restrito.py:134`. Duas cópias divergem com o tempo e alguém corrige um bug só numa. Importar de um lugar só.

**9. Dashboard de 2871 linhas num arquivo. [provável]** `dashboard_completo.py` saiu de 271 para 2871 linhas, 39 funções, 475 chamadas `st.`. E, pelo que ficou combinado, o paper abandonou a linha do DashOCCEnade em favor da LCA pura. Vale decidir com ele: o dashboard é entregável do artigo ou ferramenta paralela? Se é paralela, não precisa arrastar 2900 linhas para o repositório do paper.

**10. Versionamento por cópia. [chute]** A pasta `tentativas/` guarda 17 arquivos `old_`/`old2_`. Não consigo afirmar que não há git (só vi as cópias manuais), mas se o controle de versão for por nome de arquivo, migrar para git resolve isso e ainda te dá o diff que eu não tenho agora.

## Por onde eu começaria

Primeiro os três que impedem rodar e submeter: o caminho fixo (item 1), o `requirements.txt` + README (item 2) e a falha silenciosa do pré-processamento (item 3). Depois os três que o revisor enxerga: renomear ou implementar a MCA (item 4), as colunas constantes (item 5) e a ANOVA com o alinhamento da matriz-Q (itens 6 e 7). Duplicação e dashboard podem esperar.

Se quiser, eu escrevo os comentários de correção direto nos arquivos, ou preparo um `requirements.txt` e um README a partir do que o código importa.
