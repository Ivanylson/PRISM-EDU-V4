"""
Analises Exploratorias (EDA) - Fadiga, FG vs CE, Objetivas vs Discursivas, Ranking OC, Benchmark Regional
Usa arquivos por ano (memoria leve) em vez do consolidado de 4GB.
"""
import pandas as pd
import numpy as np
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import PASTA_DADOS_PROCESSADOS, PASTA_DADOS_EXTERNOS, CURSOS_MAP, SEPARADOR, ENCODING


def _carregar_por_ano():
    # Um ano por vez (memoria leve). Concatenar todos os anos (3.9GB) estouraria a memoria.
    from config import carregar_consolidado
    return carregar_consolidado()


def executar_eda():
    print("=" * 60)
    print("  PRISM-EDU: Analises Exploratorias (EDA)")
    print("=" * 60)

    df = _carregar_por_ano()
    if df is None or df.empty:
        print("  ERRO: Nenhum arquivo por ano encontrado.")
        return

    pasta_saida = PASTA_DADOS_PROCESSADOS
    pasta_saida.mkdir(parents=True, exist_ok=True)
    colunas_questoes = [f"Q{i}" for i in range(1, 39) if f"Q{i}" in df.columns]

    print(f"  Registros carregados: {len(df):,}")

    print("  Analise 1: Fadiga de Prova...")
    fadiga = []
    total = len(df)
    for i, q_col in enumerate(colunas_questoes, 1):
        brancos = df[q_col].astype(str).isin(["9", "*", "."]).sum()
        taxa = (brancos / total * 100) if total > 0 else 0
        fadiga.append({
            "QUESTAO": q_col,
            "BLOCO": "Formacao Geral (1-10)" if i <= 10 else "Componente Especifico (11-38)",
            "QTD_ABANDONO_BRANCO": int(brancos),
            "TAXA_ABANDONO_%": round(taxa, 2),
        })
    pd.DataFrame(fadiga).to_csv(pasta_saida / "analise_1_fadiga_prova.csv", index=False, sep=SEPARADOR, encoding=ENCODING)

    print("  Analise 2: FG vs CE...")
    if colunas_questoes and "CO_IES" in df.columns and "CO_GRUPO" in df.columns:
        tmp = df[["CO_IES", "CO_GRUPO"] + colunas_questoes].copy()
        for col in colunas_questoes:
            tmp[col] = pd.to_numeric(tmp[col], errors="coerce")
        defs = []
        for _, row in tmp.iterrows():
            for i, col in enumerate(colunas_questoes, 1):
                val = row[col]
                if pd.notna(val) and val not in [0, 9]:
                    defs.append({
                        "CO_IES": row["CO_IES"], "CO_GRUPO": row["CO_GRUPO"],
                        "QUESTAO": col,
                        "BLOCO": "FG" if i <= 10 else "CE",
                        "ACERTO": int(val == 1),
                    })
        if defs:
            df_defs = pd.DataFrame(defs)
            fg_ce = df_defs.groupby(["CO_IES", "CO_GRUPO", "BLOCO"])["ACERTO"].mean().reset_index()
            fg_ce.rename(columns={"ACERTO": "TAXA_ACERTO_%"}, inplace=True)
            fg_ce["TAXA_ACERTO_%"] = (fg_ce["TAXA_ACERTO_%"] * 100).round(2)
            fg_ce.to_csv(pasta_saida / "analise_2_fg_vs_ce.csv", index=False, sep=SEPARADOR, encoding=ENCODING)

    print("  Analise 3: Objetivas vs Discursivas...")
    if colunas_questoes and "CO_IES" in df.columns and "CO_GRUPO" in df.columns:
        tmp3 = df[["CO_IES", "CO_GRUPO"] + colunas_questoes].copy()
        for col in colunas_questoes:
            tmp3[col] = pd.to_numeric(tmp3[col], errors="coerce").fillna(0).astype(int)
        tmp3["TOTAL_ACERTOS_OBJ"] = tmp3[colunas_questoes].sum(axis=1)
        obj_disc = tmp3.groupby(["CO_IES", "CO_GRUPO"]).agg({
            "TOTAL_ACERTOS_OBJ": "mean",
        }).reset_index()
        obj_disc["TOTAL_ACERTOS_OBJ"] = obj_disc["TOTAL_ACERTOS_OBJ"].round(2)
        obj_disc.to_csv(pasta_saida / "analise_3_objetivas_vs_discursivas.csv", index=False, sep=SEPARADOR, encoding=ENCODING)

    print("  Analise 4: Ranking Nacional por OC...")
    analise_path = pasta_saida / "analise_por_ies_curso_enade.csv"
    if analise_path.exists():
        try:
            df_a = pd.read_csv(analise_path, sep=SEPARADOR, encoding=ENCODING, low_memory=False)
            if "OC1" in df_a.columns and "TAXA_DEFICIENCIA_%" in df_a.columns:
                df_oc = df_a.groupby(["CO_GRUPO", "OC1"])["TAXA_DEFICIENCIA_%"].mean().reset_index()
                df_oc.to_csv(pasta_saida / "analise_4_ranking_nacional_oc1.csv", index=False, sep=SEPARADOR, encoding=ENCODING)
        except Exception as e:
            print(f"  WARN: erro na analise 4: {e}")

    print("  Analise 5: Benchmark Regional...")
    if "CO_UF_CURSO" in df.columns and "CO_GRUPO" in df.columns and colunas_questoes:
        tmp5 = df[["CO_UF_CURSO", "CO_GRUPO", "CO_IES"] + colunas_questoes].copy() if "CO_IES" in df.columns else df[["CO_UF_CURSO", "CO_GRUPO"] + colunas_questoes].copy()
        for col in colunas_questoes:
            tmp5[col] = pd.to_numeric(tmp5[col], errors="coerce").fillna(0).astype(int)
        tmp5["ACERTOS"] = tmp5[colunas_questoes].sum(axis=1)
        df_estado = tmp5.groupby(["CO_UF_CURSO", "CO_GRUPO"])["ACERTOS"].mean().reset_index()
        df_estado.rename(columns={"ACERTOS": "MEDIA_ESTADUAL_ACERTOS"}, inplace=True)
        if "CO_IES" in tmp5.columns:
            df_ies = tmp5.groupby(["CO_IES", "CO_UF_CURSO", "CO_GRUPO"])["ACERTOS"].mean().reset_index()
            df_ies.rename(columns={"ACERTOS": "MEDIA_IES_ACERTOS"}, inplace=True)
            df_bench = pd.merge(df_ies, df_estado, on=["CO_UF_CURSO", "CO_GRUPO"], how="left")
            df_bench["DIFERENCA"] = (df_bench["MEDIA_IES_ACERTOS"] - df_bench["MEDIA_ESTADUAL_ACERTOS"]).round(2)
            df_bench.to_csv(pasta_saida / "analise_5_benchmark_regional.csv", index=False, sep=SEPARADOR, encoding=ENCODING)

    print(f"\n  5 analises EDA salvas em: {pasta_saida}")


if __name__ == "__main__":
    executar_eda()
