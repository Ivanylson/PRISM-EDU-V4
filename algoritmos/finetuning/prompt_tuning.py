"""
Prompt-tuning: seleciona exemplos few-shot representativos do dataset real.

Sem treino de pesos. Estrategia: escolher exemplos diversos (cursos/anos/OCs
distintos) que melhor ancoram o modelo quando injetados no prompt.
"""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from algoritmos.finetuning.construir_dataset import PASTA_FT  # noqa: E402


def carregar_exemplos(caminho=None):
    caminho = Path(caminho or (PASTA_FT / "treino.jsonl"))
    if not caminho.exists():
        raise FileNotFoundError(f"Dataset nao encontrado: {caminho}. Rode construir_dataset.")
    return [json.loads(l) for l in caminho.read_text(encoding="utf-8").splitlines() if l.strip()]


def selecionar_few_shot(exemplos, n=3):
    """Seleciona exemplos de OCs/cursos distintos para diversidade."""
    vistos, escolhidos = set(), []
    for ex in exemplos:
        meta = ex.get("meta", {})
        chave = (meta.get("curso"), meta.get("questao"))
        if chave in vistos:
            continue
        vistos.add(chave)
        escolhidos.append(ex)
        if len(escolhidos) >= n:
            break
    return escolhidos


def montar_prompt_few_shot(pergunta, exemplos):
    blocos = []
    for ex in exemplos:
        msgs = {m["role"]: m["content"] for m in ex["messages"]}
        blocos.append(f"Pergunta: {msgs.get('user','')}\nResposta: {msgs.get('assistant','')}")
    contexto = "\n\n".join(blocos)
    return (f"Exemplos de respostas ancoradas:\n{contexto}\n\n"
            f"Agora responda (com fonte, sem inventar):\n{pergunta}")


def gerar_config_prompt_tuning(n_few_shot=3, pasta=None):
    pasta = Path(pasta or PASTA_FT)
    exemplos = carregar_exemplos()
    few = selecionar_few_shot(exemplos, n=n_few_shot)
    config = {"n_exemplos_disponiveis": len(exemplos), "n_few_shot": len(few),
              "estrategia": "few-shot diversificado (prompt-tuning, sem treino de pesos)",
              "exemplos": few}
    (pasta / "prompt_tuning.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return config
