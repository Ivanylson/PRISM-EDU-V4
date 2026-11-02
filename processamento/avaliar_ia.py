"""CLI: pipeline de fine-tuning/prompt-tuning do PRISM-EDU.

Etapas (sem treino de pesos):
    dataset    -> modelos/finetuning/{treino,validacao}.jsonl
    prompt     -> modelos/finetuning/prompt_tuning.json (few-shot)
    avaliar    -> modelos/finetuning/avaliacao.json
    tudo       -> roda as tres etapas

Uso:
    python processamento/avaliar_ia.py tudo
    python processamento/avaliar_ia.py dataset --limite-por-arquivo 20
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from algoritmos.finetuning.construir_dataset import construir_dataset_padrao  # noqa: E402
from algoritmos.finetuning.prompt_tuning import gerar_config_prompt_tuning  # noqa: E402
from algoritmos.finetuning.avaliar_ia import salvar_avaliacao  # noqa: E402


def cmd_dataset(args):
    res = construir_dataset_padrao(limite_por_arquivo=args.limite_por_arquivo,
                                   limite_arquivos=args.limite_arquivos)
    print(f"Dataset: {res['n_total']} exemplos "
          f"({res['n_treino']} treino / {res['n_validacao']} validacao)")


def cmd_prompt(args):
    cfg = gerar_config_prompt_tuning(n_few_shot=args.n_few_shot)
    print(f"Prompt-tuning: {cfg['n_few_shot']} exemplos few-shot "
          f"de {cfg['n_exemplos_disponiveis']} disponiveis")


def cmd_avaliar(_args):
    res = salvar_avaliacao()
    print(f"Avaliacao (baseline eco): n={res['n']} "
          f"groundedness={res['groundedness']:.2f} citacao={res['citacao']:.2f} "
          f"alucinacao={res['alucinacao']:.2f}")


def cmd_tudo(args):
    cmd_dataset(args)
    cmd_prompt(args)
    cmd_avaliar(args)


def main():
    ap = argparse.ArgumentParser(description="Fine-tuning/prompt-tuning PRISM-EDU")
    sub = ap.add_subparsers(dest="comando", required=True)
    for nome in ("dataset", "tudo"):
        p = sub.add_parser(nome)
        p.add_argument("--limite-por-arquivo", type=int, default=None)
        p.add_argument("--limite-arquivos", type=int, default=3)
        p.add_argument("--n-few-shot", type=int, default=3)
    p_prompt = sub.add_parser("prompt")
    p_prompt.add_argument("--n-few-shot", type=int, default=3)
    sub.add_parser("avaliar")
    args = ap.parse_args()
    {"dataset": cmd_dataset, "prompt": cmd_prompt,
     "avaliar": cmd_avaliar, "tudo": cmd_tudo}[args.comando](args)


if __name__ == "__main__":
    main()
