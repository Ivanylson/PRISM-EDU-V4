"""Utilitario: converte um Markdown simples em .docx (python-docx).

Suporta titulos (#..####), paragrafos, listas (- e 1.) e blocos de codigo (```).
Uso:
    python processamento/md_para_docx.py entrada.md saida.docx
"""
from pathlib import Path
import sys


def markdown_para_docx(md_texto, saida, titulo=None):
    from docx import Document
    from docx.shared import Pt

    doc = Document()
    if titulo:
        doc.add_heading(titulo, level=0)

    em_codigo = False
    for linha in md_texto.splitlines():
        s = linha.rstrip()
        if s.strip().startswith("```"):
            em_codigo = not em_codigo
            continue
        if em_codigo:
            p = doc.add_paragraph(s)
            p.runs[0].font.name = "Consolas" if p.runs else None
            continue
        if not s.strip():
            continue
        if s.startswith("#### "):
            doc.add_heading(s[5:], level=4)
        elif s.startswith("### "):
            doc.add_heading(s[4:], level=3)
        elif s.startswith("## "):
            doc.add_heading(s[3:], level=2)
        elif s.startswith("# "):
            doc.add_heading(s[2:], level=1)
        elif s.lstrip().startswith("- "):
            doc.add_paragraph(s.lstrip()[2:], style="List Bullet")
        elif s.lstrip()[:2].rstrip().rstrip(".").isdigit() and ". " in s:
            doc.add_paragraph(s.split(". ", 1)[-1], style="List Number")
        else:
            doc.add_paragraph(s)

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
