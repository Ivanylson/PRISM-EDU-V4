"""
Avaliacao da IA: mede aderencia (groundedness), citacao de fonte e alucinacao.

Metricas por exemplo:
  - contem_fonte: a resposta cita a fonte esperada?
  - grounded: o valor numerico-chave aparece na resposta-base?
  - alucinou: apareceu numero que NAO existe na resposta-base?
Score agregado + taxa de alucinacao.
"""
from pathlib import Path
import json
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from algoritmos.finetuning.construir_dataset import PASTA_FT  # noqa: E402

RE_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def _numeros(texto):
    return {n.replace(",", ".") for n in RE_NUM.findall(texto or "")}


def avaliar_resposta(resposta, resposta_base, fonte=None):
    nums_base = _numeros(resposta_base)
    nums_resp = _numeros(resposta)
    citou = bool(fonte) and (fonte.split(".")[0] in (resposta or ""))
    grounded = len(nums_base & nums_resp) > 0 if nums_base else True
    alucinou = len(nums_resp - nums_base) > 0
    return {"contem_fonte": citou, "grounded": grounded, "alucinou": alucinou}


def avaliar_dataset(caminho=None, respostas_geradas=None):
    """Se `respostas_geradas` (dict pergunta->resposta) for None, avalia o baseline
    trivial 'eco' (devolve a propria resposta-base) para calibrar o pipeline."""
    caminho = Path(caminho or (PASTA_FT / "validacao.jsonl"))
    exemplos = [json.loads(l) for l in caminho.read_text(encoding="utf-8").splitlines() if l.strip()]
    detalhes, n = [], 0
    for ex in exemplos:
        msgs = {m["role"]: m["content"] for m in ex["messages"]}
        base = msgs.get("assistant", "")
        if respostas_geradas is None:
            resp = base
        else:
            resp = respostas_geradas.get(msgs.get("user", ""), "")
        m = avaliar_resposta(resp, base, fonte=ex.get("meta", {}).get("fonte"))
        detalhes.append(m)
        n += 1
    if not n:
        return {"n": 0, "groundedness": 0.0, "citacao": 0.0, "alucinacao": 0.0}
    return {"n": n,
            "groundedness": sum(d["grounded"] for d in detalhes) / n,
            "citacao": sum(d["contem_fonte"] for d in detalhes) / n,
            "alucinacao": sum(d["alucinou"] for d in detalhes) / n}


def salvar_avaliacao(pasta=None, respostas_geradas=None):
    pasta = Path(pasta or PASTA_FT)
    resultado = avaliar_dataset(respostas_geradas=respostas_geradas)
    (pasta / "avaliacao.json").write_text(
        json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    return resultado
