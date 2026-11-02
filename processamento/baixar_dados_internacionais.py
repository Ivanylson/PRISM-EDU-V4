"""
Baixa dados REAIS de exames internacionais a partir das fontes oficiais e os
integra em dados/internacionais/<sigla>/reais/ SEM apagar os placeholders.

O que cada fonte oferece (verificacao das paginas oficiais em 2026-09-15):
  PIAAC (OECD): microdados abertos (Public Use Files, PUF) em CSV, por pais.
  EGEL (CENEVAL/Mexico): informes anuais agregados em PDF (microdados nao
      sao publicos; exigem solicitacao institucional).
  TECO (ANVUR/Italia): relatorios TECO In-forma agregados em PDF.
  Saber Pro (ICFES/Colombia): informes nacionais agregados em PDF (microdados
      sob solicitacao ao portal DataIcfes).

O script:
  1) baixa os PUF do PIAAC (itens que possuem coluna de proficiencia real);
  2) normaliza para o formato esperado pela aba (colunas_esperadas);
  3) grava um ORIGEM_DADOS.md documentando links, datas e citacao;
  4) nao apaga nenhum placeholder existente.
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pandas as pd
import requests

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ_PROJETO))
from config import PASTA_INTERNACIONAIS, SEPARADOR, ENCODING  # noqa: E402

PIAAC_BASE = "https://webfs.oecd.org/piaac/cy1-puf-data/CSV/"
# codigo do pais no PUF -> nome oficial no dashboard
PIAAC_PAISES = {
    "ita": {"arquivo": "prgitap1.csv",   "nome": "Itália",  "ano": 2012},
    "mex": {"arquivo": "prgmexp1.csv",   "nome": "México",  "ano": 2012},
    "chl": {"arquivo": "prgchlp1.csv",   "nome": "Chile",   "ano": 2012},
    "per": {"arquivo": "prgperp1.csv",   "nome": "Peru",    "ano": 2012},
}
DOMINIOS_PIAAC = {
    "Literacy": (["PVLIT" + str(i) for i in range(1, 11)], 176, 225, 275, 325, 375),
    "Numeracy": (["PVNUM" + str(i) for i in range(1, 11)], 176, 225, 275, 325, 375),
    "Problem Solving": (["PVPSL" + str(i) for i in range(1, 11)], 241, 290, 340, None, None),
}

DOCUMENTOS_OFICIAIS = {
    "aber_pro": {
        "pasta": PASTA_INTERNACIONAIS / "pro" / "reais" / "documentos",
        "colecao": "Informe Nacional de Resultados Saber Pro y Saber TyT",
        "itens": [],
    },
    "egel": {
        "pasta": PASTA_INTERNACIONAIS / "egel" / "reais" / "documentos",
        "colecao": "Informe Anual de Resultados EGEL (CENEVAL)",
        "itens": [
            {
                "nome": "INFORME-ANUAL-DE-RESULTADOS-2022_EGEL_CENEVAL.pdf",
                "url": "https://ceneval.edu.mx/wp-content/uploads/2023/03/INFORME-ANUAL-DE-RESULTADOS-2022-XXX-Sesion-Ordinaria-de-la-Asamblea-General_2023_DIGITAL.pdf",
            },
        ],
    },
    "teco": {
        "pasta": PASTA_INTERNACIONAIS / "teco" / "reais" / "documentos",
        "colecao": "TECO In-forma (ANVUR)",
        "itens": [
            {
                "nome": "TECO-In-forma-2023.pdf",
                "url": "https://www.anvur.it/sites/default/files/2024-11/TECO-In-forma-2023.pdf",
            },
        ],
    },
}

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PRISM-EDU/dissertacao"}
TIMEOUT = 90


def _baixar(url: str, destino: Path) -> bool:
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists() and destino.stat().st_size > 0:
        # ja baixado: nao repete
        return True
    print(f"  Baixando {destino.name} ({url})")
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, stream=True)
    resp.raise_for_status()
    with open(destino, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=1 << 20):
            fh.write(chunk)
    print(f"  -> {destino.stat().st_size/1024/1024:.1f} MB")
    return True


def _escale_plausiveis(df_linha: pd.Series, colunas: list):
    vals = pd.to_numeric(df_linha[colunas], errors="coerce").dropna()
    return float(vals.mean()) if len(vals) else float("nan")


def _nivel_literacia(pont, cortes):
    """Nivel de proficiencia OECD PIAAC a partir dos pontos de corte.

    Literacy/Numeracy: Below Level 1 (<176), L1 (176-225), L2 (226-275),
    L3 (276-325), L4 (326-375), L5 (>375).
    Problem Solving:  Below L1 (<241), L1 (241-290), L2 (291-340), L3 (>340).
    """
    if pont is None or not cortes or not any(c is not None for c in cortes):
        return None
    if pont < cortes[0]:
        return "Below Level 1"
    if pont < cortes[1]:
        return "Level 1"
    if pont < cortes[2]:
        return "Level 2"
    c3, c4 = cortes[3], cortes[4]
    if c3 is not None and pont < c3:
        return "Level 3"
    if c4 is not None and pont < c4:
        return "Level 4"
    if c3 is None and c4 is None:
        return "Level 3"
    return "Level 5"


def _normalizar_piaac():
    pasta_puf = PASTA_INTERNACIONAIS / "piaac" / "reais" / "puf"
    linhas = []
    for sigla, cfg in PIAAC_PAISES.items():
        puf = pasta_puf / cfg["arquivo"]
        if not puf.exists():
            print(f"  [skip] PUF nao baixado para {sigla}: {puf}")
            continue
        print(f"  Normalizando {sigla} ({cfg['nome']})...")
        df = pd.read_csv(puf, encoding="utf-8", low_memory=False)
        cols_no = set(df.columns)
        for dominio, (cols_pv, *cortes) in DOMINIOS_PIAAC.items():
            if not all(c in cols_no for c in cols_pv):
                continue
            for _, row in df.iterrows():
                prof = _escale_plausiveis(row, cols_pv)
                if prof != prof:
                    continue
                linhas.append({
                    "PERSON_ID": f"{sigla.upper()}_{row.get('SEQID', '')}",
                    "COUNTRY": cfg["nome"],
                    "YEAR": cfg["ano"],
                    "DOMAIN": dominio,
                    "PROFICIENCY": round(prof, 1),
                    "SCALE": _nivel_literacia(prof, [float(c) if c is not None else None for c in cortes]) or "Below Level 1",
                })
        del df
    return pd.DataFrame(linhas)


def main():
    print("=" * 60)
    print("PRISM-EDU :: Baixador de dados internacionais (fontes oficiais)")
    print("=" * 60)

    # 1) PIAAC - microdados abertos
    print("\n[1/3] PIAAC (OECD) - microdados abertos (PUF)")
    for sigla, cfg in PIAAC_PAISES.items():
        url = PIAAC_BASE + cfg["arquivo"]
        destino = PASTA_INTERNACIONAIS / "piaac" / "reais" / "puf" / cfg["arquivo"]
        try:
            _baixar(url, destino)
        except Exception as exc:  # noqa: BLE001
            print(f"  [erro] {sigla}: {exc}")

    df_norm = _normalizar_piaac()
    saida_piaac = PASTA_INTERNACIONAIS / "piaac" / "reais" / "piaac_real.csv"
    if len(df_norm):
        saida_piaac.parent.mkdir(parents=True, exist_ok=True)
        df_norm.to_csv(saida_piaac, index=False, sep=SEPARADOR, encoding=ENCODING)
        print(f"\n  -> PIAAC normalizado: {len(df_norm)} linhas reais em {saida_piaac.name}")
    else:
        print("\n  [aviso] Nenhum dado PIAAC real pôde ser normalizado.")

    # 2) EGEL / TECO - documentos oficiais (agregados)
    print("\n[2/3] EGEL (CENEVAL) e TECO (ANVUR) - documentos oficiais")
    for sigla, cfg in DOCUMENTOS_OFICIAIS.items():
        for item in cfg["itens"]:
            destino = cfg["pasta"] / item["nome"]
            try:
                _baixar(item["url"], destino)
            except Exception as exc:  # noqa: BLE001
                print(f"  [erro] {item['nome']}: {exc}")

    # 3) ORIGEM_DADOS.md - procedencia com links e citacoes
    print("\n[3/3] Gravando ORIGEM_DADOS.md")
    from config import EXAMES_INTERNACIONAIS  # noqa: PLC0415
    hoje = datetime.date.today().isoformat()
    linhas_md = [
        "# Origem dos dados - Exames Internacionais",
        "",
        f"Documento gerado automaticamente em {hoje} pelo script "
        "`processamento/baixar_dados_internacionais.py`.",
        "",
        "Os arquivos **reais** ficam em `dados/internacionais/<sigla>/reais/`. "
        "Os placeholders simulados (gerar_placeholders.py) permanecem intactos "
        "em `dados/internacionais/<sigla>/*.csv`.",
        "",
        "## Fontes oficiais por exame",
        "",
    ]
    for sigla, info in EXAMES_INTERNACIONAIS.items():
        linhas_md.append(f"### {info['sigla']} - {info['nome']}")
        linhas_md.append(f"- Orgao: {info['orgao']}")
        linhas_md.append(f"- Tipo de fonte: {info['tipo_fonte']}")
        for fonte in info["fontes"]:
            linhas_md.append(f"- {fonte['nome']}: {fonte['url']}")
        linhas_md.append(f"- Citacao sugerida: {info['citacao']}")
        pasta_docs = PASTA_INTERNACIONAIS / sigla.lower() / "reais" / "documentos"
        if pasta_docs.exists():
            pdfs = list(pasta_docs.glob("*.pdf"))
            if pdfs:
                linhas_md.append("- Documentos oficiais baixados:")
                for p in pdfs:
                    linhas_md.append(f"  - `{p.name}`")
        linhas_md.append("")
    destino_md = PASTA_INTERNACIONAIS / "ORIGEM_DADOS.md"
    destino_md.write_text("\n".join(linhas_md), encoding="utf-8")
    print(f"  -> {destino_md}")

    print("\nConcluido. Nenhum placeholder foi removido.")


if __name__ == "__main__":
    main()