"""
Construcao do dataset de fine-tuning/prompt-tuning a partir dos artefatos reais.

IMPORTANTE (honestidade metodologica): NAO treinamos pesos de um LLM. Geramos
pares instrucao->resposta ancorados nos dados (grounding) para:
  (a) prompt-tuning: few-shot / system prompt calibrado;
  (b) avaliacao: medir aderencia do modelo a resposta-base.

Formato: JSONL estilo chat ({"messages": [...]}) + split treino/validacao.
"""
from pathlib import Path
import json
import random
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

RAIZ = Path(__file__).resolve().parent.parent.parent
PASTA_FT = RAIZ / "modelos" / "finetuning"
PASTA_DADOS = RAIZ / "dados" / "processados"

SYSTEM = ("Voce e assistente do PRISM-EDU. Responda com base nos dados fornecidos, "
          "cite a fonte e nunca invente valores.")


def _arquivos_questoes(limite_arquivos=None):
    if not PASTA_DADOS.exists():
        return []
    arquivos = sorted(PASTA_DADOS.glob("analise_por_questao_ies_enade_*.csv"))
    if limite_arquivos:
        arquivos = arquivos[-limite_arquivos:]
    return arquivos


def _exemplo_de_linha(row):
    curso = row.get("NOME_CURSO", "curso")
    oc = str(row.get("OC1", "") or row.get("COMPETENCIAS", "") or "").strip()
    taxa = row.get("TAXA_DEFICIENCIA_%")
    questao = row.get("QUESTAO", "")
    if not oc:
        return None
    pergunta = (f"No ENADE {row.get('NU_ANO')}, qual a taxa de deficiencia na "
                f"questao {questao} ({curso}) e a qual objetivo de conhecimento se refere?")
    resposta = (f"Objetivo de conhecimento: {oc}. Taxa de deficiencia: {taxa}% "
                f"(fonte: analise_por_questao_ies_enade_{row.get('NU_ANO')}.csv).")
    return {"messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": pergunta},
                         {"role": "assistant", "content": resposta}],
            "meta": {"curso": curso, "ano": str(row.get("NU_ANO")), "questao": str(questao)}}


def construir_dataset(limite_por_arquivo=None, limite_arquivos=None):
    exemplos = []
    for arq in _arquivos_questoes(limite_arquivos):
        nrows = limite_por_arquivo or 200
        try:
            df = pd.read_csv(arq, sep=";", encoding="utf-8-sig", low_memory=False,
                             nrows=200000)
        except Exception:
            continue
        if "TAXA_DEFICIENCIA_%" in df.columns:
            df = df.sort_values("TAXA_DEFICIENCIA_%", ascending=False)
        for _, row in df.head(nrows).iterrows():
            ex = _exemplo_de_linha(row)
            if ex:
                ex["meta"]["fonte"] = arq.name
                exemplos.append(ex)
    return exemplos


def dividir(exemplos, frac_validacao=0.2, semente=42):
    rnd = random.Random(semente)
    copia = list(exemplos)
    rnd.shuffle(copia)
    corte = int(len(copia) * (1 - frac_validacao))
    return copia[:corte], copia[corte:]


def salvar_dataset(exemplos, pasta=None, frac_validacao=0.2, semente=42):
    pasta = Path(pasta or PASTA_FT)
    pasta.mkdir(parents=True, exist_ok=True)
    treino, validacao = dividir(exemplos, frac_validacao, semente)
    for nome, parte in (("treino.jsonl", treino), ("validacao.jsonl", validacao)):
        with open(pasta / nome, "w", encoding="utf-8") as f:
            for ex in parte:
                f.write(json.dumps(ex, ensure_ascii=False) + "\n")
    (pasta / "resumo.json").write_text(json.dumps(
        {"n_total": len(exemplos), "n_treino": len(treino), "n_validacao": len(validacao),
         "formato": "chat-jsonl", "tipo": "prompt-tuning (sem treino de pesos)"},
        ensure_ascii=False, indent=2), encoding="utf-8")
    return {"n_total": len(exemplos), "n_treino": len(treino), "n_validacao": len(validacao)}


def construir_dataset_padrao(limite_por_arquivo=None, limite_arquivos=3):
    return salvar_dataset(
        construir_dataset(limite_por_arquivo=limite_por_arquivo,
                          limite_arquivos=limite_arquivos))
