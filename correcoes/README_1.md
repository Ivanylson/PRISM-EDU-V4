# projetoENADE

Diagnóstico de perfis de aprendizagem a partir dos microdados do ENADE 2023. O pipeline lê as respostas item a item dos estudantes, identifica perfis latentes por instituição via Latent Class Analysis (LCA) e, na sequência, ajusta um modelo de diagnóstico cognitivo restrito (DINA) sobre uma matriz item–objeto de conhecimento validada. Há ainda um dashboard interativo em Streamlit para explorar os resultados por curso e IES.

## Requisitos

Python 3.10 ou superior. Instale as dependências num ambiente virtual:

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

Dois avisos antes de rodar. O `docling` (usado só na leitura dos relatórios-síntese em PDF) puxa modelos de layout e OCR pesados; se você não vai regenerar a matriz item–OC a partir do PDF, dá para pular essa parte. E a fase 1 baixa os microdados oficiais do INEP (por volta de 1,2 GB) direto do site `download.inep.gov.br` — reserve espaço em disco e uma conexão que aguente o download.

## Estrutura

```
projetoENADE/
├── menu_principal.py              # orquestrador (menu de terminal)
├── fase1_pre_processamento/       # microdados brutos -> CSV analítico + matriz item-OC
├── fase2_cruzamento_dados/        # cruzamentos e benchmarks descritivos
├── fase3_validacao_ia/            # comparação de modelos preditivos
├── fase4_motor_ia/                # agrupamento; e LCA/ = motor de classes latentes (paper)
├── fase5_visualizacao/            # dashboard Streamlit + relatórios
├── fase6_investigacoes/           # DINA/CDM, psicometria, estatística, ML avançado
├── tentativas/                    # versões antigas (old_/old2_) — não fazem parte da execução
└── arquivosgerados/               # tudo que o pipeline produz (CSV, xlsx, figuras, .md)
```

## Como rodar

O caminho simples é o menu:

```bash
python menu_principal.py
```

A opção 1 faz o pré-processamento, a 8 roda a LCA (o método do artigo) e a 7 abre o dashboard. A opção 6 ("RODA TUDO") encadeia pré-processamento, cruzamentos, agrupamento e a LCA.

Se preferir rodar fase a fase, respeite a ordem de dependência real, porque um script consome o que o anterior gravou em `arquivosgerados/`:

1. `fase1_pre_processamento/preprocessamentoMicrodados.py` baixa os microdados do INEP e grava `arquivosgerados/relatorio_final_enade_2023.csv` (identificador do aluno, códigos de curso/IES, notas e as respostas objetivas Q1–Q38).
2. `fase1_pre_processamento/preprocessamentoRelatorioSintese.py` extrai dos relatórios-síntese em PDF o conteúdo item–objeto de conhecimento (usa `docling` e `PyMuPDF`).
3. `fase4_motor_ia/LCA/0_pipeline_principal_LCA.py` lê o CSV do passo 1 e grava, em `arquivosgerados/RESULTADOS_LCA/`, o relatório geral por IES, a caracterização das classes e a tabela de critérios de seleção de *k*.
4. `fase4_motor_ia/LCA/5_diagnostico_OCs.py` consolida a matriz item–OC em `arquivosgerados/RESULTADOS_LCA/mestre_questao_oc.csv`. **A fase 6 depende deste arquivo**, e ele não é gerado pela opção "RODA TUDO" do menu — rode este script antes de partir para o DINA.
5. `fase6_investigacoes/fase6_lca_para_cdm_restrito.py` lê o CSV do passo 1 mais a matriz-Q do passo 4 e ajusta o DINA por curso, gravando os perfis de domínio, as estimativas de *guess*/*slip* e os workbooks de validação especialista em `arquivosgerados/RESULTADOS_FASE6_LCA_CDM/`.
6. `fase5_visualizacao/dashboard_completo.py` lê os CSV gerados e sobe o dashboard: `streamlit run fase5_visualizacao/dashboard_completo.py`.

## Ressalvas conhecidas

Antes de rodar tudo, veja o parecer de revisão do código (`parecer-codigo-enade-2026-09.md`). Três pontos que afetam a execução:

- `fase4_motor_ia/LCA/2b_arquetipos_nacionais.py` tem um caminho fixo (`/home/claude/dados_teste`) que não existe fora do ambiente de teste; troque por caminho relativo antes de rodar esse script.
- O pré-processamento engole exceções e imprime o erro sem interromper, então uma falha no download ou na leitura pode passar por "sucesso" com o CSV incompleto. Confira se `relatorio_final_enade_2023.csv` foi gerado com o número de linhas esperado antes de seguir.
- A fase 6 assume que a matriz-Q casa 1:1 com as colunas Q1–Q38; confirme o alinhamento por curso se algum resultado parecer estranho.
