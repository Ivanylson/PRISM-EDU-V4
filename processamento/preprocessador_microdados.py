"""
Pipeline de Pre-processamento de Microdados - Serie Temporal ENADE 2004-2023
Suporta ENADE, ENADE Licenciaturas e ENAMED.
Gera CSVs por ano + consolidado geral.
"""
import pandas as pd
import numpy as np
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import (
    PASTA_DADOS_EXTERNOS, PASTA_SERIE_MICRODADOS, PASTA_DADOS_PROCESSADOS,
    CURSOS_MAP, SEPARADOR, ENCODING, SEED_ALEATORIA, TAMANHO_CHUNK,
    ANOS_ENADE, formatar_nome_curso,
)


def extrair_38_questoes(vetor_fg, vetor_ce):
    v_fg = str(vetor_fg).strip() if pd.notna(vetor_fg) and str(vetor_fg).lower() != "nan" else ""
    v_ce = str(vetor_ce).strip() if pd.notna(vetor_ce) and str(vetor_ce).lower() != "nan" else ""
    tudo = (v_fg + v_ce).ljust(38, "*")[:38]
    return list(tudo)


def normalizar_questoes_vetor(vetor_respostas, n_questoes=38):
    s = str(vetor_respostas).strip() if pd.notna(vetor_respostas) else ""
    s = s.ljust(n_questoes, "*")[:n_questoes]
    return list(s)


def converter_questoes_binario(df, colunas_q):
    for col in colunas_q:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    return df


def detectar_formato_arq3(caminho_arq3):
    with open(caminho_arq3, "r", encoding="latin-1", errors="replace") as f:
        cabecalho = f.readline().strip()
    cols = cabecalho.split(";")
    formato = {
        "colunas": cols,
        "tem_tp_pr_ger": "TP_PR_GER" in cols,
        "tem_dsvt_ace_ofg": "DS_VT_ACE_OFG" in cols,
        "tem_dsvt_ace_oce": "DS_VT_ACE_OCE" in cols,
        "tem_ds_vt_ace_obj": "DS_VT_ACE_OBJ" in cols,
        "tem_ofg": "OFG" in cabecalho.upper(),
        "tem_oce": "OCE" in cabecalho.upper(),
    }
    return formato


def processar_arq3_em_memoria(caminho_arq3, formato):
    cols_necessarias = []
    if formato["tem_tp_pr_ger"]:
        cols_necessarias.extend(["TP_PR_GER", "TP_PRES"])
    if formato["tem_dsvt_ace_ofg"]:
        cols_necessarias.extend(["DS_VT_ACE_OFG", "DS_VT_ACE_OCE"])
    elif formato["tem_ds_vt_ace_obj"]:
        cols_necessarias.append("DS_VT_ACE_OBJ")

    cols_existentes = [c for c in cols_necessarias if c in formato["colunas"]]
    if not cols_existentes:
        return pd.DataFrame()

    chunks = []
    for chunk in pd.read_csv(caminho_arq3, sep=";", usecols=cols_existentes,
                             encoding="latin-1", chunksize=TAMANHO_CHUNK,
                             on_bad_lines="skip", low_memory=False):
        if formato["tem_tp_pr_ger"] and "TP_PR_GER" in chunk.columns:
            mask = chunk["TP_PR_GER"].astype(str).str.strip().isin(["333", "555"])
            chunk = chunk[mask].copy()
        if not chunk.empty:
            chunks.append(chunk)

    if not chunks:
        return pd.DataFrame()
    return pd.concat(chunks, ignore_index=True)


def gerar_ids_alunos(df, colunas_id):
    contadores = {}
    ids = []
    for _, row in df.iterrows():
        chave = tuple(int(row[c]) if pd.notna(row[c]) else 0 for c in colunas_id)
        contadores[chave] = contadores.get(chave, 0) + 1
        partes = [f"aluno{contadores[chave]}"]
        partes.extend([str(int(row[c])) if pd.notna(row[c]) else "0" for c in colunas_id])
        ids.append("_".join(partes))
    return ids


def processar_ano(ano, caminho_arq1, caminho_arq3, formato_arq3):
    print(f"    Processando {ano}...")
    t0 = time.time()

    cols_arq1 = ["NU_ANO", "CO_CURSO", "CO_IES", "CO_GRUPO", "CO_UF_CURSO", "CO_REGIAO_CURSO"]
    df_ref = pd.read_csv(caminho_arq1, sep=";", usecols=cols_arq1, encoding="latin-1",
                          on_bad_lines="skip", dtype=str)
    df_ref["CO_CURSO"] = pd.to_numeric(df_ref["CO_CURSO"], errors="coerce")
    df_ref = df_ref.dropna(subset=["CO_CURSO"]).drop_duplicates(subset=["CO_CURSO"])

    df_resp = processar_arq3_em_memoria(caminho_arq3, formato_arq3)
    if df_resp.empty:
        print(f"    AVISO: Nenhuma resposta valida em {ano}")
        return pd.DataFrame()

    if "CO_CURSO" not in df_resp.columns:
        print(f"    ERRO: CO_CURSO nao encontrado no arq3 de {ano}")
        return pd.DataFrame()

    df_resp["CO_CURSO"] = pd.to_numeric(df_resp["CO_CURSO"], errors="coerce")
    df_resp = df_resp.dropna(subset=["CO_CURSO"])
    df_resp = df_resp[df_resp["CO_CURSO"].isin(df_ref["CO_CURSO"])].copy()

    df_merged = df_resp.merge(df_ref, on="CO_CURSO", how="left", suffixes=("", "_ref"))
    for col in cols_arq1:
        if f"{col}_ref" in df_merged.columns:
            df_merged[col] = df_merged[col].fillna(df_merged[f"{col}_ref"])
            df_merged.drop(columns=[f"{col}_ref"], inplace=True, errors="ignore")

    if "NU_ANO" not in df_merged.columns or df_merged["NU_ANO"].isna().all():
        df_merged["NU_ANO"] = ano

    id_cols = ["NU_ANO", "CO_CURSO", "CO_IES", "CO_GRUPO"]
    df_merged["ALUNO"] = gerar_ids_alunos(df_merged, id_cols)

    colunas_questoes = [f"Q{i}" for i in range(1, 39)]
    if formato["tem_dsvt_ace_ofg"]:
        respostas = df_merged.apply(
            lambda r: extrair_38_questoes(r.get("DS_VT_ACE_OFG", ""), r.get("DS_VT_ACE_OCE", "")),
            axis=1
        )
        df_q = pd.DataFrame(respostas.tolist(), columns=colunas_questoes, index=df_merged.index)
        df_merged = pd.concat([df_merged.drop(columns=["DS_VT_ACE_OFG", "DS_VT_ACE_OCE"],
                                               errors="ignore"), df_q], axis=1)
    elif formato["tem_ds_vt_ace_obj"]:
        respostas = df_merged["DS_VT_ACE_OBJ"].apply(
            lambda x: normalizar_questoes_vetor(x)
        )
        df_q = pd.DataFrame(respostas.tolist(), columns=colunas_questoes, index=df_merged.index)
        df_merged = pd.concat([df_merged.drop(columns=["DS_VT_ACE_OBJ"], errors="ignore"), df_q], axis=1)
    else:
        for q in colunas_questoes:
            if q not in df_merged.columns:
                df_merged[q] = "*"

    for col in colunas_questoes:
        df_merged[col] = df_merged[col].fillna("*")

    for col in ["TP_PRES", "TP_PR_GER", "TP_PR_OB_FG", "TP_PR_DI_FG",
                 "TP_PR_OB_CE", "TP_PR_DI_CE", "CO_IES", "CO_GRUPO", "NU_ANO"]:
        if col in df_merged.columns:
            df_merged[col] = pd.to_numeric(df_merged[col], errors="coerce").fillna(0).astype(int)

    colunas_saida = ["ALUNO", "NU_ANO", "CO_CURSO", "CO_IES", "CO_GRUPO", "CO_UF_CURSO", "CO_REGIAO_CURSO"]
    for col in ["TP_PRES", "TP_PR_GER", "TP_PR_OB_FG", "TP_PR_DI_FG", "TP_PR_OB_CE", "TP_PR_DI_CE",
                 "NT_FG_D1_PT", "NT_FG_D1_CT", "NT_FG_D1", "NT_DIS_CE", "NT_CE_D1"]:
        if col in df_merged.columns:
            colunas_saida.append(col)
    colunas_saida.extend(colunas_questoes)

    colunas_finais = [c for c in colunas_saida if c in df_merged.columns]

    elapsed = time.time() - t0
    print(f"    {ano}: {len(df_merged)} registros em {elapsed:.1f}s")
    return df_merged[colunas_finais].reset_index(drop=True)


def encontrar_arquivos_ano(pasta_base, ano):
    arquivos = list(pasta_base.rglob("*.txt"))
    arq1 = None
    arq3 = None
    for a in arquivos:
        nome = a.name.lower()
        if "arq1" in nome and str(ano) in nome:
            arq1 = a
        elif "arq3" in nome and str(ano) in nome:
            arq3 = a
    return arq1, arq3


def executar_preprocessamento():
    print("=" * 60)
    print("  PRISM-EDU: Pre-processamento de Microdados - Serie Temporal")
    print("=" * 60)

    pasta_enade = PASTA_DADOS_EXTERNOS / "enade"
    if not pasta_enade.exists():
        print(f"  Pasta de dados nao encontrada: {pasta_enade}")
        print("  Verifique se os dados brutos foram copiados para dados/brutos/")
        return

    arquivos_enade = sorted(pasta_enade.glob("relatorio_final_enade_*.csv"))
    print(f"  Encontrados {len(arquivos_enade)} arquivos de serie temporal ENADE")

    pasta_saida = PASTA_DADOS_PROCESSADOS / "por_ano"
    pasta_saida.mkdir(parents=True, exist_ok=True)

    total_registros = 0
    for arq in arquivos_enade:
        nome = arq.stem
        try:
            ano = int(nome.split("_")[-1])
        except ValueError:
            continue

        df = pd.read_csv(arq, sep=SEPARADOR, encoding=ENCODING, low_memory=False)
        df.to_csv(pasta_saida / f"{nome}.csv", index=False, sep=SEPARADOR, encoding=ENCODING)
        total_registros += len(df)
        print(f"    {ano}: {len(df)} registros copiados")

    consolidado = PASTA_DADOS_EXTERNOS / "relatorio_final_consolidado.csv"
    if consolidado.exists():
        print(f"\n  Consolidado existente encontrado (4GB+) - ignorado para evitar estouro de memoria.")
        print(f"  Os arquivos por ano ja foram copiados acima.")

    licenciaturas = PASTA_DADOS_EXTERNOS / "enadeLicenciaturas"
    if licenciaturas.exists():
        for arq in licenciaturas.glob("*.csv"):
            df = pd.read_csv(arq, sep=SEPARADOR, encoding=ENCODING, low_memory=False)
            print(f"  Licenciaturas: {len(df)} registros")

    enamed = PASTA_DADOS_EXTERNOS / "enamed"
    if enamed.exists():
        for arq in enamed.glob("*.csv"):
            df = pd.read_csv(arq, sep=SEPARADOR, encoding=ENCODING, low_memory=False)
            print(f"  ENAMED: {len(df)} registros")

    print(f"\n  TOTAL: {total_registros} registros processados")
    print(f"  Saida: {PASTA_DADOS_PROCESSADOS}")


def executar_download_e_processamento():
    print("=" * 60)
    print("  PRISM-EDU: Download e Processamento de Microdados")
    print("=" * 60)

    pasta_raw = PASTA_DADOS_EXTERNOS
    if not pasta_raw.exists():
        pasta_raw.mkdir(parents=True, exist_ok=True)

    print("  Procurando arquivos ja disponiveis...")
    executar_preprocessamento()


if __name__ == "__main__":
    executar_preprocessamento()
