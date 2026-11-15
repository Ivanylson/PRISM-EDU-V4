"""Teoria de Resposta ao Item (IRT) do PRISM-EDU.

Motor real (nao simulado) de estimacao de modelos dicotomicos:

  * 1PL / Rasch  -> dificuldade b_j, discriminacao fixa a_j = 1
  * 2PL          -> dificuldade b_j e discriminacao a_j

Estimacao por maxima verossimilhanca marginal (MML) com quadratura de
Gauss-Hermite e proficiencia latente padronizada (theta ~ N(0, 1)).
Tambem produz EAP/SE por aluno, confiabilidade marginal, ajuste de itens
(infit/outfit MNSQ), funcao de informacao do teste, DIF por Mantel-Haenszel
e indices de consistencia interna (alpha/omega).
"""

from .pipeline_irt import (  # noqa: F401
    ajustar_modelo_irt,
    estimar_irt_curso,
    executar_irt_edicao,
)
