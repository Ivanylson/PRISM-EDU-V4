"""Estatistica robusta para dados educacionais (scipy/sklearn apenas)."""
from .anova_robusta import anova_robusta, formatar_p
from .fidedignidade import alpha_cronbach, omega_mcdonald
from .dif import manter_haenszel_dif, fdr_bh

__all__ = [
    "anova_robusta",
    "formatar_p",
    "alpha_cronbach",
    "omega_mcdonald",
    "manter_haenszel_dif",
    "fdr_bh",
]
