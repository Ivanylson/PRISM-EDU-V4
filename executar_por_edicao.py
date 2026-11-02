"""
Orquestrador Por Edicao - PRISM-EDU
-----------------------------------
Roda os Motores de IA (5-11) em TODAS as edicoes disponiveis:

  ENADE 2004-2023 | Licenciaturas 2025 | ENAMED 2025

Memoria leve: cada edicao e carregada uma unica vez; os motores recebem o
mesmo DataFrame por referencia; o DataFrame e descartado (gc) ao final da
edicao. Nunca concatena edicoes (evita o CSV consolidado de ~4GB/OOM).

Saidas: modelos/<motor>/<edicao>/...

Uso:
    python executar_por_edicao.py                          # tudo
    python executar_por_edicao.py --edicoes enade_2019,enamed_2025
    python executar_por_edicao.py --motores clustering,shap
    python executar_por_edicao.py --n-alunos-max 50000 --limite-grupos 3
"""
import os
import sys
import gc
import time
import argparse
import importlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import (
    SEPARADOR, ENCODING, SEED_ALEATORIA,
    listar_edicoes_disponiveis, caminho_arquivo_edicao,
    arquivos_sintese_edicao, formatar_nome_curso,
)

# disponivel -> (modulo, funcao). Todas as funcoes aceitam (caminho_csv=None,
# df=None); o orquestrador passa o df por referencia (memoria compartilhada).
MOTORES = {
    "clustering": ("algoritmos.clustering.validacao", "executar_pipeline"),
    "lca": ("algoritmos.lca.pipeline_lca", "executar_pipeline_completo"),
    "preditivos": ("algoritmos.preditivos.batalha_modelos", "executar_pipeline"),
    "shap": ("algoritmos.shap.shap_analysis", "executar_analise_shap"),
    "xai": ("algoritmos.xai.lime_explainer", "executar_xai_completo"),
    "som": ("algoritmos.psicometria.som_kohonen", "executar_som"),
    "dina": ("algoritmos.cdm.dina_em", "executar_dina"),
    "ponte_cdm": ("algoritmos.cdm.ponte_lca_cdm", "executar_ponte_edicao"),
    "perfil_oc": ("algoritmos.cdm.perfil_aluno_oc", "executar_perfil_edicao"),
    "drift": ("algoritmos.drift.pipeline_drift", "executar_drift_edicao"),
    "nlp": ("algoritmos.nlp.tfidf_analise", "executar_nlp"),
    "trienal": ("algoritmos.analises_tese.analises_tese", "executar_trienal_edicao"),
}

# motores que operam sobre o DataFrame de alunos (memoria pesada).
MOTORES_DF = [m for m in MOTORES if m != "nlp"]


def _ler_csv_leve(caminho, n_alunos_max=None):
    print(f"  Carregando: {caminho.name} ({caminho.stat().st_size/1e6:.0f} MB)")
    df = __import__("pandas").read_csv(caminho, sep=SEPARADOR, encoding=ENCODING, low_memory=False)
    if n_alunos_max and len(df) > n_alunos_max:
        print(f"  Amostrando {n_alunos_max} de {len(df)} alunos (--n-alunos-max)...")
        df = df.sample(n_alunos_max, random_state=SEED_ALEATORIA)
    return df


def executar_edicao(edicao, motores, n_alunos_max=None, limite_grupos=None):
    start = time.time()
    print("\n" + "=" * 70)
    print(f"  EDICAO: {edicao.upper()}")
    print("=" * 70)

    os.environ["PRISM_EDICAO"] = edicao
    if limite_grupos:
        os.environ["PRISM_LIMITE_GRUPOS"] = str(limite_grupos)
    elif "PRISM_LIMITE_GRUPOS" in os.environ:
        del os.environ["PRISM_LIMITE_GRUPOS"]

    caminho = caminho_arquivo_edicao(edicao)
    if caminho is None:
        print(f"  [AVISO] Sem arquivo de microdados para {edicao}.")
        caminho = None

    df = None
    for motor in motores:
        if motor == "nlp":
            sintese = arquivos_sintese_edicao(edicao)
            if not sintese:
                print("\n  === NLP (TF-IDF) ===  [sem CSVs de sintese para esta edicao]")
                continue
            print("\n  === NLP (TF-IDF) ===")
            mod = importlib.import_module(MOTORES["nlp"][0])
            getattr(mod, MOTORES["nlp"][1])(pasta_sintese=sintese)
            gc.collect()
            continue

        if df is None:
            df = _ler_csv_leve(caminho, n_alunos_max)
        mod = importlib.import_module(MOTORES[motor][0])
        print(f"\n  --- Motor: {motor.upper()} ---")
        getattr(mod, MOTORES[motor][1])(caminho_csv=None, df=df)
        gc.collect()

    if df is not None:
        del df
        gc.collect()
    print(f"\n  Edicao {edicao} concluida em {time.time()-start:.0f}s")


def main():
    ap = argparse.ArgumentParser(description="PRISM-EDU: motores de IA por edicao (memoria leve).")
    ap.add_argument("--edicoes", default="all",
                    help="Edicoes separadas por virgula, ou 'all' (default).")
    ap.add_argument("--motores", default="all",
                    help="Motores separados por virgula, ou 'all' (default).")
    ap.add_argument("--n-alunos-max", type=int, default=None,
                    help="Limita o numero de alunos por edicao (amostra).")
    ap.add_argument("--limite-grupos", type=int, default=None,
                    help="Limita o numero de cursos/grupos processados por motor.")
    args = ap.parse_args()

    disponiveis = listar_edicoes_disponiveis()
    if not disponiveis:
        print("ERRO: nenhuma edicao encontrada (procure por 'relatorio_final_*.csv').")
        return

    if args.edicoes.strip().lower() in ("", "all"):
        edicoes = disponiveis
    else:
        pedidos = [e.strip() for e in args.edicoes.split(",") if e.strip()]
        desconhecidas = [e for e in pedidos if e not in disponiveis]
        if desconhecidas:
            print(f"[AVISO] Edicoes nao disponiveis: {desconhecidas}")
        edicoes = [e for e in pedidos if e in disponiveis]

    if args.motores.strip().lower() in ("", "all"):
        motores = list(MOTORES.keys())
    else:
        motores = [m.strip() for m in args.motores.split(",") if m.strip()]
        desconhec = [m for m in motores if m not in MOTORES]
        if desconhec:
            print(f"[AVISO] Motores desconhecidos: {desconhec}")

    print(f"Edicoes ({len(edicoes)}): {', '.join(edicoes)}")
    print(f"Motores ({len(motores)}): {', '.join(motores)}")

    t_total = time.time()
    for edicao in edicoes:
        executar_edicao(edicao, motores, args.n_alunos_max, args.limite_grupos)

    print("\n" + "=" * 70)
    print(f"  TODAS AS EDICOES PROCESSADAS EM {time.time()-t_total:.0f}s")
    print("  Resultados em: modelos/<motor>/<edicao>/")
    print("=" * 70)


if __name__ == "__main__":
    main()