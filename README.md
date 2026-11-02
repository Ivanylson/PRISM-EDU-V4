# PRISM-EDU

Plataforma de IA educacional sobre os microdados do **ENADE (2004–2023)**, **ENADE Licenciaturas (2025)** e **ENAMED (2025)**. O núcleo estatístico identifica perfis latentes de aprendizagem por IES via **LCA** (Latent Class Analysis) e faz diagnóstico cognitivo restrito por curso com **DINA** (CDM de la Torre) a partir da matriz item–objeto de conhecimento do INEP (Anexo IX), com SHAP/XAI, preditivos e dashboard Streamlit.

## Requisitos e ambiente

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

## Como rodar

```bash
python main.py                  # menu: pré-processamento, algoritmos, pipeline, dashboard
streamlit run dashboard/app.py  # dashboard interativo
python executar_todos.py        # EDA + preditivos + SHAP (alvo externo NT_DIS_CE)
```

## Estrutura

```
PRISM-EDU/
├── config.py                   # centraliza caminhos, CURSOS_MAP, formatadores
├── main.py                     # orquestrador (menu)
├── executar_todos.py           # EDA, métricas, LightGBM/XGBoost, SHAP por curso
├── processamento/              # microdados, questões, cruzamentos, EDA
├── algoritmos/
│   ├── lca/pipeline_lca.py     # LCA (EM, aBIC, entropia, bootstrap Jaccard, MCA)
│   ├── cdm/dina_em.py          # DINA via EM com matriz-Q do INEP (não aleatória)
│   ├── clustering/ preditivos/ shap/ xai/ psicometria/ nlp/ opencode/ estatistica/
├── dashboard/                  # Streamlit (abelhas, séries temporais, diagnóstico)
├── modelos/                    # saídas (lca/, cdm/, shap/, ...)
└── correcoes/                  # material de revisão + backup pré-correção
```

## Dados

- Caminhos centralizados em `config.py`. Os resultads da série temporal ficam em
  `../seriesTemporais_microdados/resultados/` (ENADE por ano, Licenciaturas 2025, ENAMED 2025).
- O DINA precisa de `mestre_questao_oc.csv` (matriz item–OC do INEP), procurado em
  `../modeloprojetoENADE2023/arquivosgerados/RESULTADOS_LCA/` etc. Sem ele o DINA falha
  explicitamente — não usa matriz-Q aleatória.

## Ressalvas conhecidas

- `carregar_consolidado()` retorna **um ano representativo** (o mais recente) para evitar OOM
  com o consolidado agregado (7,1 M linhas).
- O arquivo das **Licenciaturas 2025** ainda não contém as notas oficiais (NT_FG/NT_CE ausentes;
  NT_GER presente em ~1,3% e NT_DIS parcial, escala 0–10) — comparar por item/OC ou reobter da INEP.