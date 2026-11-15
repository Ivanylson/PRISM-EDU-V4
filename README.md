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
streamlit run dashboard/app.py  # dashboard interativo (21 abas)
python executar_todos.py        # EDA + preditivos + SHAP (alvo externo NT_DIS_CE)

# governança do dado e do método
python algoritmos/irt/pipeline_irt.py --edicao enade_2023   # IRT 1PL/2PL (MML) por curso
python processamento/auditoria_qualidade.py --edicoes all   # catálogo, inventário e gates G1-G6
python executar_por_edicao.py --edicoes enade_2023 --motores irt
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
│   ├── irt/pipeline_irt.py     # IRT 1PL/Rasch e 2PL por MML + TIF, infit/outfit, DIF
│   ├── clustering/ preditivos/ shap/ xai/ psicometria/ nlp/ opencode/ estatistica/
├── dashboard/                  # Streamlit (abelhas, séries temporais, diagnóstico)
│   └── abas/aba_qualidade.py   # aba 21: cobertura, dicionário, gates, manifesto, IRT, métodos
├── modelos/                    # saídas (lca/, cdm/, shap/, irt/, qualidade/, ...)
└── correcoes/                  # material de revisão + backup pré-correção
```

## Governança do dado

A 21ª aba (**Qualidade, Proveniência e Métodos**) lê apenas artefatos gerados:

- `modelos/qualidade/qualidade_por_edicao.csv` — linhas, itens utilizáveis, cursos, IES, nulos, faixa de notas.
- `modelos/qualidade/catalogo_dados.json` — dicionário por edição (tipo, nulos na amostra, exemplo).
- `modelos/qualidade/gates.json` — G1 cobertura, G2 integridade, G3 alertas, G4 artefatos, G5 paridade matriz/dicionário, G6 validação especialista.
- `modelos/qualidade/qualidade_dados.json` — manifesto do run (ambiente, parâmetros, motores, avisos).
- `modelos/irt/<edicao>/` — ajuste IRT real por curso (`irt_resumo_geral.csv`, itens, TIF, habilidades, DIF).

Se um artefato não existe, a aba mostra o comando que o gera — nunca um número simulado. O relatório desta rodada está em `documentacao/relatorio_ampliacoes_15112026.md`.

## Dados

- Caminhos centralizados em `config.py`. Os resultados da série temporal ficam em
  `../seriesTemporais_microdados/resultados/` (ENADE por ano, Licenciaturas 2025, ENAMED 2025).
- O DINA precisa de `mestre_questao_oc.csv` (matriz item–OC do INEP), procurado em
  `../modeloprojetoENADE2023/arquivosgerados/RESULTADOS_LCA/` etc. Sem ele o DINA falha
  explicitamente — não usa matriz-Q aleatória.

## Ressalvas conhecidas

- `carregar_consolidado()` retorna **um ano representativo** (o mais recente) para evitar OOM
  com o consolidado agregado (7,1 M linhas).
- O arquivo das **Licenciaturas 2025** ainda não contém as notas oficiais (NT_FG/NT_CE ausentes;
  NT_GER presente em ~1,3% e NT_DIS parcial, escala 0–10) — comparar por item/OC ou reobter da INEP.