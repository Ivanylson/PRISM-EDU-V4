"""Gera analise_por_questao_ies para ENADE (por ano), Licenciaturas e ENAMED.

Fonte principal: dados/processados/resultadosQuestoes (xlsx de mapeamento de questoes)
cruzados com os microdados por-ano (colunas Q1..QN) via operacoes vetorizadas.
Evita o CSV consolidado de 4GB migrando os dados por-ano/exame.
"""
import pandas as pd
import numpy as np
import unicodedata
import re
import json
from difflib import SequenceMatcher
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import (
    PASTA_DADOS_PROCESSADOS, SEPARADOR, ENCODING,
    CURSOS_MAP,
)

RAIZ = Path(__file__).resolve().parent.parent
PASTA_QUESTOES = RAIZ.parent / "seriesTemporais_questoes" / "resultados"
PASTA_RESULTADOS_QUESTOES = PASTA_DADOS_PROCESSADOS / "resultadosQuestoes"
PASTA_POR_ANO = PASTA_DADOS_PROCESSADOS / "por_ano"
PASTA_OUT = PASTA_DADOS_PROCESSADOS
PASTA_MAP_GRUPOS = Path(__file__).resolve().parent / "mapeamento_grupos_enade.json"

GRUPOS_POR_ANO = {}
if PASTA_MAP_GRUPOS.exists():
    try:
        GRUPOS_POR_ANO = json.loads(PASTA_MAP_GRUPOS.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ATENCAO: nao foi possivel carregar {PASTA_MAP_GRUPOS.name}: {e}")

COLUNAS_SAIDA = [
    "CO_IES", "CO_CURSO", "CO_UF_CURSO", "CO_REGIAO_CURSO", "NOME_CURSO",
    "CO_GRUPO", "NU_ANO", "QUESTAO", "PERFIL", "COMPETENCIAS", "OC1", "OC2",
    "OC3", "QTD_ACERTOS", "QTD_ERROS", "TAXA_DEFICIENCIA_%",
]

ARQUIVOS_IGNORAR = ("formacao geral", "resultados do conceito enade")
STOP_TOKENS = {"tecnologia", "em", "de", "da", "do", "no", "na", "e"}

ID_COLS = ["CO_IES", "CO_CURSO", "CO_UF_CURSO", "CO_REGIAO_CURSO"]


def normalizar_grupo(g):
    try:
        return int(float(g))
    except (ValueError, TypeError):
        return None


def nome_grupo(g, ano=None):
    g2 = normalizar_grupo(g)
    if g2 is not None:
        if ano is not None:
            mapa_ano = GRUPOS_POR_ANO.get(str(ano), {})
            nome = mapa_ano.get(str(g2))
            if nome:
                return _title(nome)
        if g2 in CURSOS_MAP:
            return CURSOS_MAP[g2]
    return f"Grupo_{g}"


def _title(nome):
    """Converte 'ADMINISTRACAO' -> 'Administracao' (mantendo siglas e numerais)."""
    if not isinstance(nome, str):
        return nome
    palavras = nome.split()
    out = []
    for p in palavras:
        if p.isupper() and len(p) > 1 and not p.isdigit():
            out.append(p[0] + p[1:].lower())
        else:
            out.append(p.capitalize())
    return " ".join(out)


def _norm(s):
    if not isinstance(s, str):
        s = str(s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _core_tokens(s):
    return [t for t in _norm(s).split() if t not in STOP_TOKENS]


def _pontuacao_equivalencia(nome, arquivo):
    sm = SequenceMatcher(None, _norm(nome), _norm(arquivo)).ratio()
    x = set(_core_tokens(nome))
    y = set(_core_tokens(arquivo))
    inter = len(x & y)
    denom = len(x) or 1
    cj = inter / denom
    return sm + cj


def encontrar_xlsx(nome_curso, xlsx_map, ano):
    """Retorna o caminho do xlsx de mapeamento mais parecido com nome_curso.

    Estrategia em camadas para evitar colisoes (ex.: 'fisica' nao deve casar
    com 'educacao fisica'):
      1. igualdade normalizada exata;
      2. contencao de tokens-core (nome totalmente contido, com minimo de
         tokens extras), desempatada por SequenceMatcher;
      3. pontuacao combinada (SequenceMatcher + contencao core), com limite.
    Grupos desconhecidos ('Grupo_N' fora do CURSOS_MAP) so casam via regra 1.
    """
    candidatos = {}
    for stem, xp in xlsx_map.items():
        if stem in ARQUIVOS_IGNORAR or "alteracao" in stem:
            continue
        if ARQUIVOS_IGNORAR and any(str(stem).startswith(i) for i in ARQUIVOS_IGNORAR):
            continue
        candidatos[stem] = xp

    if not candidatos:
        return nome_curso, None

    nome_limpo = _norm(nome_curso)
    nomes = list(candidatos.keys())

    is_generic = nome_curso.startswith("Grupo_")

    for stem in nomes:
        if _norm(stem) == nome_limpo:
            return nome_curso, candidatos[stem]

    if not is_generic:
        MODS = ("licenciatura", "bacharelado", "licenciaturas")
        core_nome = _core_tokens(nome_curso)
        subj = [t for t in core_nome if t not in MODS]
        if subj:
            nome_mod = next((t for t in core_nome if t in MODS), None)
            contidos = []
            for stem in nomes:
                cand_core = _core_tokens(stem)
                if not cand_core:
                    continue
                if not all(t in cand_core for t in subj):
                    continue
                cand_mod = next((t for t in cand_core if t in MODS), None)
                if nome_mod and cand_mod and cand_mod != nome_mod:
                    mod_conflict = 2
                elif cand_mod != nome_mod:
                    mod_conflict = 1
                else:
                    mod_conflict = 0
                n_extra = len([t for t in cand_core if t not in subj and t not in MODS and t != nome_mod])
                try:
                    first = min(cand_core.index(t) for t in subj)
                except ValueError:
                    first = 999
                sm = SequenceMatcher(None, _norm(nome_curso), _norm(stem)).ratio()
                contidos.append((n_extra, mod_conflict, -sm, stem, candidatos[stem]))
            if contidos:
                contidos.sort()
                return nome_curso, contidos[0][4]

    melhor, melhor_score = None, -1
    for stem in nomes:
        score = _pontuacao_equivalencia(nome_curso, stem)
        if score > melhor_score:
            melhor, melhor_score = stem, score
    if melhor is not None and melhor_score >= 0.65:
        return nome_curso, candidatos[melhor]

    print(f"    AVISO: sem xlsx para '{nome_curso}' (melhor: {melhor} {melhor_score:.2f})")
    return nome_curso, None


def carregar_xlsx_questoes(caminho):
    try:
        df = pd.read_excel(caminho, sheet_name="Table 1")
    except Exception:
        try:
            df = pd.read_excel(caminho)
        except Exception:
            return None
    rename = {}
    for c in df.columns:
        cl = str(c).lower().strip()
        if "posi" in cl:
            rename[c] = "POSIÇÃO"
        elif "perfil" in cl:
            rename[c] = "PERFIL"
        elif "compet" in cl:
            rename[c] = "COMPETENCIAS"
        elif cl.startswith("oc1"):
            rename[c] = "OC1"
        elif cl.startswith("oc2"):
            rename[c] = "OC2"
        elif cl.startswith("oc3"):
            rename[c] = "OC3"
    if rename:
        df = df.rename(columns=rename)
    return df


def mapear_questoes(df_questoes):
    mapping = {}
    for _, row in df_questoes.iterrows():
        pos = str(row.get("POSIÇÃO", "")).strip()
        if pos.startswith("D") or pos == "":
            continue
        try:
            num = int(pos)
        except (ValueError, TypeError):
            continue
        q_name = f"Q{num}"
        mapping[q_name] = {
            "PERFIL": str(row.get("PERFIL", "")).strip(),
            "COMPETENCIAS": str(row.get("COMPETENCIAS", "")).strip(),
            "OC1": str(row.get("OC1", "")).strip(),
            "OC2": str(row.get("OC2", "")).strip(),
            "OC3": str(row.get("OC3", "")).strip() if pd.notna(row.get("OC3")) else "",
        }
    return mapping


def _agregar_melted(melted, meta_map_df, id_cols, nome_curso, co_grupo, nu_ano):
    melted = melted.merge(meta_map_df, on="QUESTAO", how="left")
    for c in id_cols:
        if c in melted.columns:
            melted[c] = melted[c].fillna(0)

    melted["NOME_CURSO"] = nome_curso
    melted["CO_GRUPO"] = co_grupo
    melted["NU_ANO"] = nu_ano
    melted["ACERTOU"] = (melted["RESPOSTA"] == 1).astype(int)
    melted["ERROU"] = (melted["RESPOSTA"] == 0).astype(int)
    melted["TAXA_DEFICIENCIA_%"] = melted["ERROU"] * 100

    agg_cols = id_cols + ["NOME_CURSO", "CO_GRUPO", "NU_ANO", "QUESTAO",
                          "PERFIL", "COMPETENCIAS", "OC1", "OC2", "OC3"]
    agg_df = melted.groupby(agg_cols, as_index=False).agg({
        "ACERTOU": "sum",
        "ERROU": "sum",
        "TAXA_DEFICIENCIA_%": "mean",
    })
    agg_df.rename(columns={"ACERTOU": "QTD_ACERTOS", "ERROU": "QTD_ERROS"}, inplace=True)
    for col in COLUNAS_SAIDA:
        if col not in agg_df.columns:
            agg_df[col] = 0
    return agg_df[COLUNAS_SAIDA]


def _montar_xlsx_map(exame, ano):
    """Busca a pasta de xlsx (resultadosQuestoes primeiro, fallback na fonte externa)."""
    for base in (PASTA_RESULTADOS_QUESTOES, PASTA_QUESTOES):
        pasta = base / exame / str(ano)
        if pasta.exists():
            xlsx_map = {}
            for xlsx in pasta.glob("*.xlsx"):
                xlsx_map[xlsx.stem.lower().strip()] = xlsx
            if xlsx_map:
                return pasta, xlsx_map
    return None, {}


def gerar_enade():
    print("=" * 60)
    print("  ENADE - Analise por Questao/IES (serie temporal 2004-2026)")
    print("=" * 60)

    arquivos = sorted(PASTA_POR_ANO.glob("relatorio_final_enade_*.csv"))
    if not arquivos:
        print(f"  Nenhum arquivo por-ano em {PASTA_POR_ANO}")
        return

    for arq in arquivos:
        try:
            ano = int(arq.stem.split("_")[-1])
        except (ValueError, IndexError):
            continue
        print(f"\n  --- Ano {ano} ({arq.name}) ---")
        try:
            df = pd.read_csv(arq, sep=SEPARADOR, encoding=ENCODING, low_memory=False)
        except Exception as e:
            print(f"    ERRO ao ler: {e}")
            continue

        q_cols_present = [c for c in df.columns if c.startswith("Q") and c[1:].isdigit()]
        id_present = [c for c in ID_COLS if c in df.columns]
        if not q_cols_present:
            print("    Sem colunas Q no arquivo por-ano.")
            continue

        pasta_xlsx, xlsx_map = _montar_xlsx_map("enade", ano)
        if not xlsx_map:
            print("    Sem xlsx de mapeamento; tentando mapear por todos os cursos do CURSOS_MAP.")

        grupos = sorted(set(normalizar_grupo(g) for g in df["CO_GRUPO"].dropna() if normalizar_grupo(g) is not None))

        todos_resultados = []
        metas = {}
        for g in grupos:
            nc = nome_grupo(g, ano)
            xlsx_path = None
            if xlsx_map:
                _, xlsx_path = encontrar_xlsx(nc, xlsx_map, ano)
            if xlsx_path is None:
                continue

            meta_df = carregar_xlsx_questoes(xlsx_path)
            if meta_df is None or meta_df.empty:
                continue
            q_mapping = mapear_questoes(meta_df)
            q_cols = [q for q in sorted(q_mapping.keys(), key=lambda x: int(x[1:])) if q in df.columns]
            if not q_cols:
                continue
            metas[g] = (nc, q_cols, q_mapping, xlsx_path)
            print(f"    {nc} (grupo {g}): {len(q_cols)} questoes ({xlsx_path.name})")

        if not metas:
            print("    Nenhum curso com mapeamento encontrado.")
            continue

        for g, (nc, q_cols, q_mapping, xlsx_path) in metas.items():
            if g not in set(normalizar_grupo(v) for v in df["CO_GRUPO"].dropna()):
                continue
            df_g = df[df["CO_GRUPO"].astype(float).astype(int) == g].copy()
            if len(df_g) == 0:
                continue

            meta_map_df = pd.DataFrame([{"QUESTAO": q, **q_mapping[q]} for q in q_cols])
            melted = df_g[id_present + q_cols].melt(
                id_vars=id_present, value_vars=q_cols,
                var_name="QUESTAO", value_name="RESPOSTA"
            )
            melted["RESPOSTA"] = melted["RESPOSTA"].astype(str).str.strip()
            melted = melted[~melted["RESPOSTA"].isin(["", ".", "9", "8", "6", "nan", "None"])]
            melted["RESPOSTA"] = pd.to_numeric(melted["RESPOSTA"], errors="coerce")
            melted = melted.dropna(subset=["RESPOSTA"])
            melted = melted[melted["RESPOSTA"].isin([0, 1])]
            if melted.empty:
                continue
            agg = _agregar_melted(melted, meta_map_df, id_present, nc, g, ano)
            todos_resultados.append(agg)

        if not todos_resultados:
            print("    Nenhum resultado agregado.")
            continue

        final = pd.concat(todos_resultados, ignore_index=True)
        out = PASTA_OUT / f"analise_por_questao_ies_enade_{ano}.csv"
        final.to_csv(out, sep=SEPARADOR, encoding="utf-8-sig", index=False)
        print(f"    Salvo: {out.name} ({len(final):,} linhas, {final['CO_GRUPO'].nunique()} cursos)")


def gerar_licenciaturas():
    print("\n=== Licenciaturas 2025 ===")
    lic_csv = PASTA_DADOS_PROCESSADOS / "enadeLicenciaturas" / "relatorio_final_enade_licenciaturas_2025.csv"
    if not lic_csv.exists():
        print(f"  Nao encontrado: {lic_csv}")
        return None

    df = pd.read_csv(lic_csv, sep=SEPARADOR, encoding=ENCODING, low_memory=False)
    print(f"  Rows: {len(df)}, Grupos: {df['CO_GRUPO'].nunique()}")

    pasta_xlsx, xlsx_map = _montar_xlsx_map("enadeLicenciaturas", 2025)
    if not xlsx_map:
        print("  Pasta xlsx nao encontrada.")
        return None
    print(f"  XLSX: {sorted(xlsx_map.keys())}")

    todos_resultados = []
    grupos = sorted(set(normalizar_grupo(g) for g in df["CO_GRUPO"].dropna() if normalizar_grupo(g) is not None))
    for g in grupos:
        nc = nome_grupo(g)
        _, xlsx_path = encontrar_xlsx(nc, xlsx_map, 2025)
        if xlsx_path is None:
            print(f"  SKIP {nc} ({g}): sem xlsx")
            continue

        meta_df = carregar_xlsx_questoes(xlsx_path)
        if meta_df is None or meta_df.empty:
            continue
        q_mapping = mapear_questoes(meta_df)
        q_cols = [q for q in sorted(q_mapping.keys(), key=lambda x: int(x[1:])) if q in df.columns]
        if not q_cols:
            continue
        print(f"  {nc}: {len(q_cols)} questoes de {xlsx_path.name}")

        df_g = df[df["CO_GRUPO"].astype(float).astype(int) == g].copy()
        meta_map_df = pd.DataFrame([{"QUESTAO": q, **q_mapping[q]} for q in q_cols])
        id_cols = [c for c in ID_COLS if c in df_g.columns]
        melted = df_g[id_cols + q_cols].melt(
            id_vars=id_cols, value_vars=q_cols, var_name="QUESTAO", value_name="RESPOSTA"
        )
        melted["RESPOSTA"] = pd.to_numeric(melted["RESPOSTA"], errors="coerce")
        melted = melted.dropna(subset=["RESPOSTA"])
        melted = melted[~melted["RESPOSTA"].isin([8, 6])]
        melted = melted[melted["RESPOSTA"].isin([0, 1])]
        if melted.empty:
            continue
        agg = _agregar_melted(melted, meta_map_df, id_cols, nc, g, 2025)
        todos_resultados.append(agg)

    if not todos_resultados:
        print("  Nenhum resultado!")
        return None

    final = pd.concat(todos_resultados, ignore_index=True)
    out = PASTA_OUT / "analise_por_questao_ies_licenciaturas_2025.csv"
    final.to_csv(out, sep=SEPARADOR, encoding="utf-8-sig", index=False)
    print(f"  Salvo: {out.name} ({len(final):,} linhas)")
    return final


def gerar_enamed():
    print("\n=== ENAMED 2025 ===")
    enamed_csv = PASTA_DADOS_PROCESSADOS / "enamed" / "relatorio_final_enamed_2025.csv"
    if not enamed_csv.exists():
        print(f"  Nao encontrado: {enamed_csv}")
        return None

    df = pd.read_csv(enamed_csv, sep=SEPARADOR, encoding=ENCODING, low_memory=False)
    print(f"  Rows: {len(df)}")

    pasta_xlsx, xlsx_map = _montar_xlsx_map("enamed", 2025)
    xlsx_files = list(xlsx_map.values())
    if not xlsx_files:
        print("  Nenhum xlsx de ENAMED.")
        return None

    meta_df = carregar_xlsx_questoes(xlsx_files[0])
    if meta_df is None or meta_df.empty:
        return None
    q_mapping = mapear_questoes(meta_df)
    q_cols = [q for q in sorted(q_mapping.keys(), key=lambda x: int(x[1:])) if q in df.columns]
    print(f"  {len(q_cols)} questoes de {xlsx_files[0].name}")

    meta_map_df = pd.DataFrame([{"QUESTAO": q, **q_mapping[q]} for q in q_cols])
    id_cols = [c for c in ID_COLS if c in df.columns]
    melted = df[id_cols + q_cols].melt(
        id_vars=id_cols, value_vars=q_cols, var_name="QUESTAO", value_name="RESPOSTA"
    )
    melted["RESPOSTA"] = melted["RESPOSTA"].astype(str).str.strip()
    melted = melted[~melted["RESPOSTA"].isin(["", ".", "8", "6", "nan"])]
    melted["RESPOSTA"] = pd.to_numeric(melted["RESPOSTA"], errors="coerce")
    melted = melted.dropna(subset=["RESPOSTA"])
    melted = melted[melted["RESPOSTA"].isin([0, 1])]

    agg = _agregar_melted(melted, meta_map_df, id_cols, "ENAMED", 0, 2025)
    out = PASTA_OUT / "analise_por_questao_ies_enamed_2025.csv"
    agg.to_csv(out, sep=SEPARADOR, encoding="utf-8-sig", index=False)
    print(f"  Salvo: {out.name} ({len(agg):,} linhas)")
    return agg


if __name__ == "__main__":
    gerar_enade()
    gerar_licenciaturas()
    gerar_enamed()
    print("\n=== Concluido ===")
