"""Utilitario: converte um Markdown simples em .docx (python-docx).

Suporta titulos (#..####), paragrafos, listas (- e 1.), tabelas (| ... |),
citacoes (>), enfase inline (**negrito** e `codigo`) e blocos de codigo (```).
Uso:
    python processamento/md_para_docx.py entrada.md saida.docx
"""
from pathlib import Path
import re
import sys


def _runs_inline(paragrafo, texto):
    """Escreve texto no paragrafo interpretando **negrito** e `codigo`."""
    for token in re.split(r"(\*\*.+?\*\*|`[^`]+`)", texto):
        if not token:
            continue
        if token.startswith("**") and token.endswith("**") and len(token) > 4:
            run = paragrafo.add_run(token[2:-2])
            run.bold = True
        elif token.startswith("`") and token.endswith("`") and len(token) > 2:
            run = paragrafo.add_run(token[1:-1])
            run.font.name = "Consolas"
        else:
            paragrafo.add_run(token)


def _celulas(linha):
    return [c.strip() for c in linha.strip().strip("|").split("|")]


def _adicionar_tabela(doc, bloco):
    """Converte linhas '| a | b |' em uma tabela docx (com cabecalho)."""
    if len(bloco) < 2:
        doc.add_paragraph(bloco[0])
        return
    cabecalho = _celulas(bloco[0])
    inicio = 1
    if re.fullmatch(r"[\s|:\-]+", bloco[1]):
        inicio = 2  # linha separadora |---|---|
    corpo = [_celulas(linha) for linha in bloco[inicio:]]
    ncols = len(cabecalho)
    tabela = doc.add_table(rows=1, cols=ncols)
    try:
        tabela.style = "Table Grid"
    except Exception:
        pass
    for j, texto in enumerate(cabecalho):
        celula = tabela.rows[0].cells[j]
        celula.text = ""
        _runs_inline(celula.paragraphs[0], texto)
        for run in celula.paragraphs[0].runs:
            run.bold = True
    for linha in corpo:
        celulas = tabela.add_row().cells
        for j in range(ncols):
            celula = celulas[j]
            celula.text = ""
            _runs_inline(celula.paragraphs[0], linha[j] if j < len(linha) else "")
    doc.add_paragraph("")


def markdown_para_docx(md_texto, saida, titulo=None):
    from docx import Document

    doc = Document()
    if titulo:
        doc.add_heading(titulo, level=0)

    linhas = md_texto.splitlines()
    em_codigo = False
    i = 0
    while i < len(linhas):
        s = linhas[i].rstrip()
        i += 1

        if s.strip().startswith("```"):
            em_codigo = not em_codigo
            continue

        if em_codigo:
            if not s.strip():
                continue
            p = doc.add_paragraph(s)
            if p.runs:
                p.runs[0].font.name = "Consolas"
            continue

        if not s.strip():
            continue

        # tabela: consome linhas consecutivas que comecam com '|'
        if s.lstrip().startswith("|"):
            bloco = [s.strip()]
            while i < len(linhas) and linhas[i].lstrip().startswith("|"):
                bloco.append(linhas[i].strip())
                i += 1
            _adicionar_tabela(doc, bloco)
            continue

        if s.strip() in {"---", "***", "___"}:
            continue

        if s.startswith("#### "):
            doc.add_heading(s[5:], level=4)
        elif s.startswith("### "):
            doc.add_heading(s[4:], level=3)
        elif s.startswith("## "):
            doc.add_heading(s[3:], level=2)
        elif s.startswith("# "):
            doc.add_heading(s[2:], level=1)
        elif s.lstrip().startswith(">"):
            texto = s.lstrip().lstrip(">").strip()
            p = doc.add_paragraph(style="Intense Quote")
            _runs_inline(p, texto)
        elif re.match(r"^\s*[-*] ", s):
            p = doc.add_paragraph(style="List Bullet")
            _runs_inline(p, re.sub(r"^\s*[-*] ", "", s))
        elif re.match(r"^\s*\d+\.\s+", s):
            p = doc.add_paragraph(style="List Number")
            _runs_inline(p, re.sub(r"^\s*\d+\.\s+", "", s))
        else:
            p = doc.add_paragraph()
            _runs_inline(p, s)

    Path(saida).parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(saida))
    return saida


def main():
    if len(sys.argv) < 3:
        print("Uso: python processamento/md_para_docx.py entrada.md saida.docx")
        return
    entrada = Path(sys.argv[1])
    markdown_para_docx(entrada.read_text(encoding="utf-8"), sys.argv[2])
    print(f"Gravado: {sys.argv[2]}")


if __name__ == "__main__":
    main()
