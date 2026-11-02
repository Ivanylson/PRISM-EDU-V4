"""Fase 6 - CDM/DINA (lote).

AVISO IMPORTANTE: este script foi SUBSTITUIDO pela versão honesta e completa:

    fase6_lca_para_cdm_restrito.py

A implementação anterior chamava de "diagnóstico cognitivo / DINA" uma simples
média de acertos por OC (sem modelo de resposta, sem estimação por EM), o que
era um rótulo enganoso. A versão correta:

  * monta a matriz-Q por curso a partir da matriz item-OC do INEP (Anexo IX);
  * estima o DINA restrito por EM (guess g, slip s, prevalência pi e perfis de
    domínio por aluno), com restrição de identificabilidade (g, s em [0, 0.5]);
  * gera o workbook de validação especialista, a comparação LCA vs DINA item a
    item e o resumo consolidado para os 28 cursos.

Para manter compatibilidade com quem invoca este arquivo, ele apenas executa o
pipeline real.
"""
import subprocess
import sys
from pathlib import Path

if __name__ == '__main__':
    script_real = Path(__file__).resolve().parent / 'fase6_lca_para_cdm_restrito.py'
    if not script_real.exists():
        sys.exit(f"ERRO: pipeline real não encontrado: {script_real}")

    print("=" * 72)
    print("AVISO: 'fase6_cdm_dina_lote.py' foi descontinuado.")
    print("Executando o pipeline real de DINA restrito (matriz-Q do INEP + EM)...")
    print("=" * 72)

    subprocess.run([sys.executable, str(script_real)], check=True)
