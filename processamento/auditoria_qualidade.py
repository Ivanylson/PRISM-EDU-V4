"""
Auditoria de Qualidade e Proveniencia -- PRISM-EDU
==================================================

Gera um retrato auditavel do estado dos dados e dos artefatos do projeto:

  * cobertura de edicoes (ENADE 2004-2023, Licenciaturas 2025, ENAMED 2025);
  * qualidade basica dos microdados (linhas, colunas, itens com dados,
    duplicidade de chave, nulos e faixa das notas);
  * inventario dos motores/artefatos (quantos arquivos por edicao, bytes,
    ultima atualizacao);
  * gates de integridade com status ok/atencao/falha;
  * catalogo de colunas (dicionario de dados minimo, legivel por maquina);
  * manifesto do run (versao, parametros, ambiente, arquivos gerados).

Nada e apagado ou movido. O modulo apenas le os dados/artefatos existentes e
grava novos arquivos em ``modelos/qualidade/`` (ou em ``--saida``).

Uso:
    python processamento/auditoria_qualidade.py
    python processamento/auditoria_qualidade.py --edicoes enade_2023,enamed_2025
    python processamento/auditoria_qualidade.py --hash
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from config import (  # noqa: E402
    ANOS_ENADE, ANOS_ENADE_SEM_DADOS, CURSOS_MAP, ENCODING, PASTA_DADOS_PROCESSADOS,
    PASTA_MODELOS, SEPARADOR, SEED_ALEATORIA, caminho_arquivo_edicao,
    listar_edicoes_disponiveis,
)

VERSAO = "1.0.0"
SAIDA_PADRAO = PASTA_MODELOS / "qualidade"

MOTORES = [
    "analises_tese", "cdm", "clustering", "drift", "irt", "lca",
    "nlp", "preditivos", "psicometria", "shap", "xai",
]

# Artefatos considerados essenciais por motor (globs aceitos).
ARTEFATOS_ESPERADOS = {
    "lca": ["01_relatorio_geral_por_ies.csv", "02_caracterizacao_das_classes.csv",
            "03_criterios_de_selecao_k.csv"],
    "cdm": ["comparacao_lca_vs_dina.csv", "diagnostico_cognitivo_*.xlsx"],
    "clustering": ["metricas_*.csv", "validacao_*.csv"],
    "preditivos": ["metricas_modelos_*.csv"],
    "shap": ["importancia_*.csv"],
    "xai": ["atribuicao_*.csv"],
    "psicometria": ["som_*.png"],
    "nlp": ["*.csv"],
    "drift": ["drift_univariado_*.csv"],
    "analises_tese": ["analises_tese_*.json"],
    "irt": ["irt_resumo_geral.csv", "irt_itens_*.csv"],
}

NOTAS = ["NT_GER", "NT_FG", "NT_CE", "NT_OBJ_FG", "NT_OBJ_CE", "NT_DIS_CE"]
Q_VALORES_VALIDOS = {"0", "1"}


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _agora():
    return datetime.now(timezone.utc).isoformat()


def _sha256(caminho: Path, limite_bytes=200 * 1024 * 1024):
    """SHA-256 de arquivos pequenos/medios; ignora arquivos enormes por padrao."""
    caminho = Path(caminho)
    if not caminho.exists() or caminho.stat().st_size > limite_bytes:
        return None
    h = hashlib.sha256()
    with caminho.open("rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def _contar_linhas(caminho: Path):
    """Conta linhas fisicas rapidamente (sem carregar o CSV)."""
    try:
        with Path(caminho).open("rb") as f:
            n = sum(bloco.count(b"\n") for bloco in iter(lambda: f.read(4 * 1024 * 1024), b""))
        return max(0, n - 1)  # desconta o cabecalho
    except Exception:
        return None


def _edicao_ano(edicao):
    try:
        return int(str(edicao).split("_")[-1])
    except (ValueError, IndexError):
        return None


# ---------------------------------------------------------------------------
# Microdados
# ---------------------------------------------------------------------------
def auditar_microdados(edicoes=None, nrows_amostra=20000, com_hash=False):
    """Metricas de qualidade por edicao (leitura leve: cabecalho + amostra)."""
    edicoes = edicoes or listar_edicoes_disponiveis()
    linhas = []
    for edicao in edicoes:
        caminho = caminho_arquivo_edicao(edicao)
        registro = {"edicao": edicao, "arquivo": None, "bytes": None,
                    "n_linhas": None, "n_linhas_amostra": None,
                    "n_colunas": None, "n_itens_q": None, "n_itens_com_dados": None,
                    "n_cursos": None, "n_ies": None,
                    "duplicatas_aluno_amostra": None, "pct_nulos_aluno_amostra": None,
                    "colunas_nota_presentes": [], "colunas_nota_ausentes": [],
                    "pct_nulos_ntger_amostra": None, "ntger_min": None, "ntger_max": None,
                    "ntger_fora_0_100": None, "sha256": None, "status": "erro",
                    "alertas": []}
        if caminho is None or not Path(caminho).exists():
            registro["alertas"].append("Arquivo ausente para a edicao.")
            linhas.append(registro)
            continue

        caminho = Path(caminho)
        registro["arquivo"] = caminho.name
        registro["bytes"] = int(caminho.stat().st_size)
        registro["n_linhas"] = _contar_linhas(caminho)
        if com_hash:
            registro["sha256"] = _sha256(caminho, limite_bytes=8 * 1024 ** 3)
        try:
            header = pd.read_csv(caminho, sep=SEPARADOR, encoding=ENCODING, nrows=0)
            colunas = list(header.columns)
        except Exception as exc:
            registro["alertas"].append(f"Nao foi possivel ler o cabecalho: {exc}")
            linhas.append(registro)
            continue

        registro["n_colunas"] = len(colunas)
        qcols = [c for c in colunas if isinstance(c, str) and c.startswith("Q") and c[1:].isdigit()]
        registro["n_itens_q"] = len(qcols)
        notas_presentes = [c for c in NOTAS if c in colunas]
        registro["colunas_nota_presentes"] = notas_presentes
        registro["colunas_nota_ausentes"] = [c for c in NOTAS if c not in colunas]

        usecols = [c for c in ["ALUNO", "CO_GRUPO", "CO_IES", "NT_GER", "TP_SEXO"] if c in colunas]
        usecols += qcols
        try:
            amostra = pd.read_csv(caminho, sep=SEPARADOR, encoding=ENCODING,
                                  usecols=usecols, nrows=nrows_amostra,
                                  low_memory=False)
        except Exception as exc:
            registro["alertas"].append(f"Falha ao amostrar o CSV: {exc}")
            linhas.append(registro)
            continue

        registro["n_linhas_amostra"] = int(len(amostra))
        if "ALUNO" in amostra.columns:
            registro["duplicatas_aluno_amostra"] = int(amostra["ALUNO"].duplicated().sum())
            registro["pct_nulos_aluno_amostra"] = round(
                float(amostra["ALUNO"].isna().mean() * 100), 2)
        if "CO_GRUPO" in amostra.columns:
            registro["n_cursos"] = int(pd.to_numeric(
                amostra["CO_GRUPO"], errors="coerce").dropna().nunique())
        if "CO_IES" in amostra.columns:
            registro["n_ies"] = int(pd.to_numeric(
                amostra["CO_IES"], errors="coerce").dropna().nunique())

        if qcols:
            Q = amostra[qcols].apply(pd.to_numeric, errors="coerce")
            Q = Q.where(Q.isin([0, 1]))
            registro["n_itens_com_dados"] = int(
                (Q.notna().mean() > 0.5).sum())
        else:
            registro["n_itens_com_dados"] = 0

        if "NT_GER" in amostra.columns:
            nt = pd.to_numeric(amostra["NT_GER"], errors="coerce")
            registro["pct_nulos_ntger_amostra"] = round(float(nt.isna().mean() * 100), 2)
            validos = nt.dropna()
            if len(validos):
                registro["ntger_min"] = round(float(validos.min()), 3)
                registro["ntger_max"] = round(float(validos.max()), 3)
                registro["ntger_fora_0_100"] = int(((validos < 0) | (validos > 100)).sum())

        # Status e alertas
        alertas = registro["alertas"]
        if registro["n_itens_com_dados"] is not None and registro["n_itens_com_dados"] < 5:
            alertas.append("Menos de 5 itens com dados utilizaveis.")
        if (registro["pct_nulos_ntger_amostra"] is not None
                and registro["pct_nulos_ntger_amostra"] > 20):
            alertas.append("NT_GER ausente em mais de 20% da amostra inicial.")
        if registro["ntger_fora_0_100"]:
            alertas.append("NT_GER fora do intervalo 0-100.")
        if registro["duplicatas_aluno_amostra"]:
            alertas.append("ALUNO duplicado na amostra inicial.")
        if registro["colunas_nota_ausentes"]:
            alertas.append("Colunas de nota ausentes: " + ", ".join(registro["colunas_nota_ausentes"]))
        if registro["n_ies"] == 0:
            alertas.append("Sem CO_IES (ex.: ENAMED); analise por IES nao se aplica.")

        registro["status"] = (
            "erro" if registro["n_itens_com_dados"] is None or registro["n_itens_com_dados"] < 5
            else "atencao" if alertas else "ok"
        )
        linhas.append(registro)

    return pd.DataFrame(linhas)


# ---------------------------------------------------------------------------
# Artefatos
# ---------------------------------------------------------------------------
def inventariar_motores(com_hash=False):
    """Inventario de arquivos por motor e por edicao."""
    inventario = {}
    for motor in MOTORES:
        raiz = PASTA_MODELOS / motor
        item = {"existe": raiz.exists(), "arquivos_raiz": 0, "bytes_raiz": 0,
                "edicoes": {}, "sha256_resumo": None}
        if not raiz.exists():
            inventario[motor] = item
            continue
        for arq in raiz.iterdir():
            if arq.is_file():
                item["arquivos_raiz"] += 1
                try:
                    item["bytes_raiz"] += arq.stat().st_size
                except OSError:
                    pass
        for sub in sorted([p for p in raiz.iterdir() if p.is_dir()]):
            arquivos = [p for p in sub.rglob("*") if p.is_file()]
            total = sum(p.stat().st_size for p in arquivos if p.exists())
            atualizado = None
            if arquivos:
                try:
                    atualizado = datetime.fromtimestamp(
                        max(p.stat().st_mtime for p in arquivos), tz=timezone.utc
                    ).isoformat()
                except OSError:
                    atualizado = None
            item["edicoes"][sub.name] = {
                "arquivos": len(arquivos),
                "bytes": int(total),
                "atualizado_em": atualizado,
            }
        inventario[motor] = item
    return inventario


def avaliar_artefatos(inventario):
    """Cobertura dos artefatos essenciais por motor/edicao."""
    resultados = []
    for motor, esperados in ARTEFATOS_ESPERADOS.items():
        item = inventario.get(motor, {})
        for edicao, info in (item.get("edicoes") or {}).items():
            pasta = PASTA_MODELOS / motor / edicao
            faltando = []
            for padrao in esperados:
                achou = False
                try:
                    achou = any(Path(p).exists() for p in pasta.glob(padrao))
                except Exception:
                    achou = False
                if not achou:
                    faltando.append(padrao)
            resultados.append({
                "motor": motor, "edicao": edicao,
                "arquivos": info.get("arquivos", 0),
                "bytes": info.get("bytes", 0),
                "padroes_esperados": esperados,
                "padroes_faltando": faltando,
                "status": "ok" if not faltando else "atencao",
            })
    return pd.DataFrame(resultados)


def comparar_planilhas_e_dicionarios():
    """Verifica paridade matriz-Q / dicionario de OCs por curso."""
    pasta = PASTA_DADOS_PROCESSADOS
    matrizes = {p.stem.replace("matriz_q_", "") for p in pasta.glob("matriz_q_*.csv")}
    dicionarios = {p.stem.replace("dicionario_ocs_", "") for p in pasta.glob("dicionario_ocs_*.csv")}
    return {
        "n_matrizes": len(matrizes),
        "n_dicionarios": len(dicionarios),
        "somente_matriz": sorted(matrizes - dicionarios),
        "somente_dicionario": sorted(dicionarios - matrizes),
    }


def status_validacao_especialista():
    caminho = PASTA_DADOS_PROCESSADOS / "00_resumo_geral.csv"
    if not caminho.exists():
        return {"arquivo": None, "n_cursos": 0, "pendentes": None}
    try:
        df = pd.read_csv(caminho, sep=SEPARADOR, encoding=ENCODING, low_memory=False)
        col = next((c for c in df.columns if "status" in c.lower() and "valid" in c.lower()), None)
        if col is None:
            return {"arquivo": caminho.name, "n_cursos": int(len(df)), "pendentes": None}
        vc = df[col].astype(str).str.upper().value_counts().to_dict()
        return {"arquivo": caminho.name, "n_cursos": int(len(df)),
                "pendentes": int(vc.get("PENDENTE_VALIDACAO", 0)), "contagem": vc}
    except Exception as exc:
        return {"arquivo": caminho.name, "n_cursos": None, "pendentes": None,
                "erro": str(exc)}


# ---------------------------------------------------------------------------
# Catalogo de dados
# ---------------------------------------------------------------------------
def catalogo_de_dados(edicoes=None):
    """Dicionario de dados minimo a partir dos cabecalhos reais."""
    edicoes = edicoes or listar_edicoes_disponiveis()
    catalogo = {"versao": VERSAO, "gerado_em": _agora(),
                "convencoes": {
                    "separador": SEPARADOR, "encoding": ENCODING,
                    "itens": "Colunas Q<n> sao itens dicotomicos: 1=acerto, 0=erro, .=branco/invalido.",
                    "notas": "NT_* em escala 0-100 quando presentes; ausencia declarada por edicao.",
                    "ALUNO": "Identificador sintetico criado no pre-processamento; chave logica por edicao.",
                },
                "edicoes": {}}
    for edicao in edicoes:
        caminho = caminho_arquivo_edicao(edicao)
        if caminho is None or not Path(caminho).exists():
            continue
        try:
            header = pd.read_csv(caminho, sep=SEPARADOR, encoding=ENCODING, nrows=200)
        except Exception:
            continue
        colunas = {}
        for c in header.columns:
            serie = header[c]
            nulos = float(serie.isna().mean())
            exemplo = next((v for v in serie.dropna().tolist() if str(v).strip() != ""), None)
            colunas[str(c)] = {
                "tipo_observado": str(serie.dtype),
                "nulo_amostra_pct": round(nulos * 100, 2),
                "exemplo": None if exemplo is None else str(exemplo)[:80],
            }
        catalogo["edicoes"][edicao] = {
            "arquivo": Path(caminho).name,
            "n_colunas": len(header.columns),
            "colunas": colunas,
        }
    return catalogo


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------
def _gate(nome, descricao, status, detalhe):
    return {"gate": nome, "descricao": descricao, "status": status, "detalhe": detalhe}


def calcular_gates(df_qualidade, df_artefatos, paridade, validacao):
    gates = []

    anos_presentes = sorted({_edicao_ano(e) for e in df_qualidade["edicao"]
                             if str(e).startswith("enade_") and _edicao_ano(e)})
    ausentes_esperados = [a for a in ANOS_ENADE if a not in anos_presentes and a not in ANOS_ENADE_SEM_DADOS]
    gates.append(_gate(
        "G1_cobertura_enade",
        "Todas as edicoes ENADE previstas (exceto 2020, declarada sem dados) possuem arquivo.",
        "ok" if not ausentes_esperados else "falha",
        f"presentes={len(anos_presentes)}; ausentes_nao_declaradas={ausentes_esperados}; "
        f"sem_dados_declaradas={ANOS_ENADE_SEM_DADOS}",
    ))

    criticos = df_qualidade[(df_qualidade["status"] == "erro")]
    gates.append(_gate(
        "G2_integridade_microdados",
        "Nenhuma edicao com erro de leitura/itens utilizaveis.",
        "ok" if criticos.empty else "falha",
        "sem erros" if criticos.empty else "edicoes com erro: " + ", ".join(criticos["edicao"].tolist()),
    ))

    atencao = df_qualidade[df_qualidade["status"] == "atencao"]
    gates.append(_gate(
        "G3_alertas_de_qualidade",
        "Edicoes sem alertas de nulos, duplicidade ou notas fora da escala.",
        "ok" if atencao.empty else "atencao",
        "sem alertas" if atencao.empty else "edicoes com alerta: " + ", ".join(atencao["edicao"].tolist()),
    ))

    if df_artefatos.empty:
        gates.append(_gate("G4_artefatos_motores", "Artefatos essenciais presentes por motor/edicao.",
                           "atencao", "nenhum artefato de motor encontrado"))
    else:
        falhas = df_artefatos[df_artefatos["status"] != "ok"]
        gates.append(_gate(
            "G4_artefatos_motores",
            "Artefatos essenciais presentes por motor/edicao.",
            "ok" if falhas.empty else "atencao",
            f"{len(df_artefatos) - len(falhas)}/{len(df_artefatos)} combinacoes completas; "
            f"faltando em: " + ", ".join(sorted({f"{r.motor}/{r.edicao}" for r in falhas.itertuples()}))[:500],
        ))

    ok_paridade = not paridade.get("somente_matriz") and not paridade.get("somente_dicionario")
    gates.append(_gate(
        "G5_paridade_matriz_dicionario",
        "Toda matriz-Q tem dicionario de OCs correspondente (e vice-versa).",
        "ok" if ok_paridade else "atencao",
        f"matrizes={paridade.get('n_matrizes')}, dicionarios={paridade.get('n_dicionarios')}, "
        f"so_matriz={paridade.get('somente_matriz')}, so_dicionario={paridade.get('somente_dicionario')}",
    ))

    pend = validacao.get("pendentes")
    gates.append(_gate(
        "G6_validacao_especialista",
        "Validacao da matriz-Q pelos especialistas registrada.",
        "ok" if pend == 0 else "atencao",
        (f"{pend} de {validacao.get('n_cursos')} cursos pendentes"
         if pend is not None else "arquivo de validacao ausente/sem coluna de status"),
    ))

    return gates


# ---------------------------------------------------------------------------
# Orquestracao
# ---------------------------------------------------------------------------
def executar(edicoes=None, saida=None, com_hash=False, nrows_amostra=20000):
    t0 = time.time()
    saida = Path(saida) if saida else SAIDA_PADRAO
    saida.mkdir(parents=True, exist_ok=True)

    print(f"[qualidade] Auditando {len(edicoes) if edicoes else 'todas as'} edicoes...")
    df_qual = auditar_microdados(edicoes=edicoes, nrows_amostra=nrows_amostra, com_hash=com_hash)
    inventario = inventariar_motores(com_hash=com_hash)
    df_art = avaliar_artefatos(inventario)
    paridade = comparar_planilhas_e_dicionarios()
    validacao = status_validacao_especialista()
    gates = calcular_gates(df_qual, df_art, paridade, validacao)
    catalogo = catalogo_de_dados(edicoes=edicoes)

    df_qual.to_csv(saida / "qualidade_por_edicao.csv", index=False,
                   sep=SEPARADOR, decimal=",", encoding="utf-8-sig")
    if not df_art.empty:
        df_art.to_csv(saida / "artefatos_por_motor.csv", index=False,
                      sep=SEPARADOR, decimal=",", encoding="utf-8-sig")

    resumo = {
        "versao": VERSAO,
        "gerado_em": _agora(),
        "duracao_seg": round(time.time() - t0, 2),
        "edicoes_auditadas": df_qual["edicao"].tolist(),
        "n_edicoes": int(len(df_qual)),
        "status_por_edicao": df_qual["status"].value_counts().to_dict(),
        "gates": gates,
        "resumo_gates": {
            "ok": sum(g["status"] == "ok" for g in gates),
            "atencao": sum(g["status"] == "atencao" for g in gates),
            "falha": sum(g["status"] == "falha" for g in gates),
        },
        "motores": inventario,
        "paridade_matriz_dicionario": paridade,
        "validacao_especialista": validacao,
        "ambiente": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "plataforma": platform.platform(),
        },
        "parametros": {
            "seed": SEED_ALEATORIA,
            "nrows_amostra": nrows_amostra,
            "hash_habilitado": com_hash,
        },
        "avisos": [
            "Metricas de nulos/duplicidade usam a amostra inicial (nrows_amostra), nao a base inteira.",
            "O inventario mede presenca de arquivos, nao a correcao cientifica do conteudo.",
            "Arquivos maiores que 200 MB nao sao hasheados por padrao.",
        ],
    }
    (saida / "qualidade_dados.json").write_text(
        json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")
    (saida / "gates.json").write_text(
        json.dumps(gates, ensure_ascii=False, indent=2), encoding="utf-8")
    (saida / "catalogo_dados.json").write_text(
        json.dumps(catalogo, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[qualidade] Gates: {resumo['resumo_gates']}")
    print(f"[qualidade] Saida: {saida}")
    return resumo


def main():
    ap = argparse.ArgumentParser(description="PRISM-EDU: auditoria de qualidade e proveniencia.")
    ap.add_argument("--edicoes", default="all",
                    help="Edicoes separadas por virgula, ou 'all' (default).")
    ap.add_argument("--saida", default=None, help="Pasta de saida (default modelos/qualidade).")
    ap.add_argument("--hash", action="store_true", help="Calcula SHA-256 (mais lento).")
    ap.add_argument("--nrows-amostra", type=int, default=20000,
                    help="Linhas iniciais usadas nas metricas de qualidade (default 20000).")
    args = ap.parse_args()

    disponiveis = listar_edicoes_disponiveis()
    if args.edicoes.strip().lower() in ("", "all"):
        edicoes = disponiveis
    else:
        pedidas = [e.strip() for e in args.edicoes.split(",") if e.strip()]
        edicoes = [e for e in pedidas if e in disponiveis]
        if len(edicoes) < len(pedidas):
            print(f"[aviso] ignoradas (sem arquivo): {sorted(set(pedidas) - set(edicoes))}")

    executar(edicoes=edicoes, saida=args.saida, com_hash=args.hash,
             nrows_amostra=args.nrows_amostra)


if __name__ == "__main__":
    main()
