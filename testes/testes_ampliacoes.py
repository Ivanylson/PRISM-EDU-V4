"""Testes das ampliacoes de 15/11/2026 -- PRISM-EDU.

Cobre:
  * motor IRT real (1PL/2PL por MML) -- recuperacao de parametros;
  * correcao das rotinas de testes multiplos (BH e Holm);
  * correcao da estatistica de Mantel-Haenszel;
  * correcao do alinhamento de residuos em E2 (valor agregado);
  * gates da auditoria de qualidade;
  * registro da nova aba e do motor IRT no orquestrador.

Rode com:
    python -m unittest testes.testes_ampliacoes -v
"""
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import ABAS_DASHBOARD, SEED_ALEATORIA


# ---------------------------------------------------------------------------
# Dados sinteticos
# ---------------------------------------------------------------------------
def _dados_irt(n=1500, j=15, seed=SEED_ALEATORIA):
    rng = np.random.default_rng(seed)
    a = np.exp(rng.normal(0.0, 0.25, j))
    b = rng.normal(0.0, 1.0, j)
    theta = rng.normal(0.0, 1.0, n)
    p = 1.0 / (1.0 + np.exp(-(theta[:, None] - b[None, :]) * a[None, :]))
    x = (rng.random((n, j)) < p).astype(float)
    return x, a, b, theta


# ---------------------------------------------------------------------------
# IRT
# ---------------------------------------------------------------------------
class TestIRT(unittest.TestCase):
    def test_recupera_parametros_2pl(self):
        from algoritmos.irt.pipeline_irt import ajustar_modelo_irt

        x, a, b, theta = _dados_irt()
        fit = ajustar_modelo_irt(x, modelo="2PL")
        self.assertTrue(fit["convergiu"])
        self.assertGreater(np.corrcoef(fit["a"], a)[0, 1], 0.75)
        self.assertGreater(np.corrcoef(fit["b"], b)[0, 1], 0.90)
        self.assertGreater(np.corrcoef(fit["theta_eap"], theta)[0, 1], 0.70)
        self.assertTrue(0.0 <= fit["confiabilidade_marginal"] <= 1.0)
        self.assertTrue(np.all(np.isfinite(fit["a"])))
        self.assertTrue(np.all(fit["a"] > 0))

    def test_1pl_tem_discriminacao_fixa(self):
        from algoritmos.irt.pipeline_irt import ajustar_modelo_irt

        x, _, _, _ = _dados_irt(n=800, j=12)
        fit = ajustar_modelo_irt(x, modelo="1PL")
        self.assertTrue(np.allclose(fit["a"], 1.0))
        self.assertEqual(fit["n_params"], 12)

    def test_bic_penaliza_2pl_quando_dados_sao_rasch(self):
        from algoritmos.irt.pipeline_irt import ajustar_modelo_irt

        rng = np.random.default_rng(7)
        n, j = 1200, 12
        b = np.linspace(-1.5, 1.5, j)
        theta = rng.normal(0, 1, n)
        p = 1.0 / (1.0 + np.exp(-(theta[:, None] - b[None, :])))
        x = (rng.random((n, j)) < p).astype(float)
        f1 = ajustar_modelo_irt(x, modelo="1PL")
        f2 = ajustar_modelo_irt(x, modelo="2PL")
        # Com dados gerados por Rasch, o BIC deve preferir (ou empatar) o 1PL
        self.assertLessEqual(f1["bic"], f2["bic"] + 1e-6)

    def test_funcao_informacao(self):
        from algoritmos.irt.pipeline_irt import funcao_informacao

        tif = funcao_informacao(np.ones(5), np.linspace(-1, 1, 5))
        self.assertEqual(list(tif.columns), ["theta", "informacao", "erro_padrao"])
        self.assertTrue((tif["informacao"] > 0).all())
        self.assertTrue(np.allclose(tif["erro_padrao"], 1.0 / np.sqrt(tif["informacao"])))

    def test_preparar_matriz_respostas_filtra_itens_constantes(self):
        from algoritmos.irt.pipeline_irt import preparar_matriz_respostas

        rng = np.random.default_rng(3)
        n = 400
        df = pd.DataFrame({
            "Q1": rng.integers(0, 2, n),
            "Q2": rng.integers(0, 2, n),
            "Q3": np.ones(n),          # constante -> deve sair
            "Q4": rng.integers(0, 2, n),
            "CO_GRUPO": 1,
            "ALUNO": np.arange(n),
        })
        X, base, itens, descartados = preparar_matriz_respostas(df)
        self.assertNotIn("Q3", itens)
        self.assertEqual(X.shape, (len(base), len(itens)))
        self.assertEqual(descartados, 0)


# ---------------------------------------------------------------------------
# Testes multiplos
# ---------------------------------------------------------------------------
class TestCorrecaoTestesMultiplos(unittest.TestCase):
    def test_bh_valores_conhecidos(self):
        from algoritmos.estatistica.dif import fdr_bh

        ajustados = fdr_bh([0.001, 0.008, 0.039])
        self.assertTrue(np.allclose(ajustados, [0.003, 0.012, 0.039], atol=1e-6))

    def test_holm_valores_conhecidos(self):
        from algoritmos.estatistica.anova_robusta import _holm_bonferroni

        ajustados = _holm_bonferroni([0.001, 0.008, 0.039])
        self.assertTrue(np.allclose(ajustados, [0.003, 0.016, 0.039], atol=1e-6))

    def test_ajustados_sao_monotonos_e_limitados(self):
        from algoritmos.estatistica.anova_robusta import _holm_bonferroni
        from algoritmos.estatistica.dif import fdr_bh

        p = [0.0001, 0.02, 0.03, 0.20, 0.9]
        for fn in (fdr_bh, _holm_bonferroni):
            ajustados = fn(p)
            self.assertTrue(np.all(ajustados >= np.asarray(p) - 1e-12))
            self.assertTrue(np.all(ajustados <= 1.0))
            # nunca colapsar todos no menor p
            self.assertGreater(len(set(np.round(ajustados, 8))), 1)


# ---------------------------------------------------------------------------
# Mantel-Haenszel
# ---------------------------------------------------------------------------
class TestMantelHaenszelCorrigido(unittest.TestCase):
    def test_chi2_bate_com_formula_de_um_estrato(self):
        from algoritmos.estatistica.dif import _mh_item

        # um unico estrato: a=30, b=10, c=20, d=40
        respostas = np.array([1] * 30 + [0] * 10 + [1] * 20 + [0] * 40)
        grupos = np.array([1] * 40 + [0] * 60)
        estratos = np.zeros(100, dtype=int)
        mh = _mh_item(respostas, grupos, estratos)

        a, b, c, d = 30.0, 10.0, 20.0, 40.0
        T = a + b + c + d
        n1, n0 = a + b, c + d
        m1, m0 = a + c, b + d
        esperado = n1 * m1 / T
        var = n1 * n0 * m1 * m0 / (T ** 2 * (T - 1))
        chi2 = (a - esperado) ** 2 / var
        self.assertAlmostEqual(mh["qui_quadrado"], chi2, places=3)
        self.assertAlmostEqual(mh["OR_MH"], (a * d) / (b * c), places=3)


# ---------------------------------------------------------------------------
# E2: alinhamento de residuos
# ---------------------------------------------------------------------------
class TestE2Alinhamento(unittest.TestCase):
    def test_residuos_vao_para_o_aluno_certo_com_indice_nao_trivial(self):
        from algoritmos.analises_tese.analises_tese import valor_agregado

        rng = np.random.default_rng(11)
        n = 600
        ies = np.repeat([1, 2, 3], n // 3)
        idade = rng.integers(18, 40, n)
        # nota = 0.5*idade + efeito fixo da IES (sem ruido)
        efeito = {1: -10.0, 2: 0.0, 3: 10.0}
        nota = 0.5 * idade + np.array([efeito[i] for i in ies])
        df = pd.DataFrame({
            "CO_IES": ies,
            "NT_DIS_CE": nota,
            "QE_I01": rng.choice(list("ABCDE"), n),
            "QE_I02": rng.choice(list("ABCDE"), n),
            "QE_I03": rng.choice(list("ABCDE"), n),
            "NU_IDADE": idade,
            "TP_SEXO": rng.choice(["M", "F"], n),
        })
        # indice nao trivial + NaN no meio (o bug antigo desalinhava ou quebrava)
        df.index = np.arange(1000, 1000 + n)
        df.loc[df.index[10], "QE_I02"] = np.nan

        out = valor_agregado(df, 2023)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["n_ies"], 3)
        top = out["top_ies"][0]
        bottom = out["bottom_ies"][-1]
        self.assertEqual(int(top["CO_IES"]), 3)
        self.assertEqual(int(bottom["CO_IES"]), 1)
        self.assertGreater(top["valor_agregado"], 9.0)
        self.assertLess(bottom["valor_agregado"], -9.0)


# ---------------------------------------------------------------------------
# Gates de qualidade
# ---------------------------------------------------------------------------
class TestGatesQualidade(unittest.TestCase):
    def _frames(self):
        qual = pd.DataFrame([
            {"edicao": "enade_2023", "status": "ok"},
            {"edicao": "enade_2019", "status": "ok"},
        ])
        art = pd.DataFrame([
            {"motor": "lca", "edicao": "enade_2023", "arquivos": 3,
             "bytes": 10, "padroes_esperados": [], "padroes_faltando": [], "status": "ok"},
        ])
        paridade = {"n_matrizes": 2, "n_dicionarios": 2,
                    "somente_matriz": [], "somente_dicionario": []}
        validacao = {"arquivo": "00_resumo_geral.csv", "n_cursos": 2, "pendentes": 0}
        return qual, art, paridade, validacao

    def test_gates_em_ordem_e_com_status(self):
        from processamento.auditoria_qualidade import calcular_gates

        gates = calcular_gates(*self._frames())
        nomes = [g["gate"] for g in gates]
        self.assertEqual(nomes, [
            "G1_cobertura_enade", "G2_integridade_microdados",
            "G3_alertas_de_qualidade", "G4_artefatos_motores",
            "G5_paridade_matriz_dicionario", "G6_validacao_especialista",
        ])
        self.assertTrue(all(g["status"] in ("ok", "atencao", "falha") for g in gates))

    def test_gate_falha_quando_edicao_tem_erro(self):
        from processamento.auditoria_qualidade import calcular_gates

        qual, art, paridade, validacao = self._frames()
        qual.loc[0, "status"] = "erro"
        gates = {g["gate"]: g for g in calcular_gates(qual, art, paridade, validacao)}
        self.assertEqual(gates["G2_integridade_microdados"]["status"], "falha")

    def test_gate_atencao_quando_validacao_pendente(self):
        from processamento.auditoria_qualidade import calcular_gates

        qual, art, paridade, validacao = self._frames()
        validacao["pendentes"] = 2
        gates = {g["gate"]: g for g in calcular_gates(qual, art, paridade, validacao)}
        self.assertEqual(gates["G6_validacao_especialista"]["status"], "atencao")


# ---------------------------------------------------------------------------
# Registro estrutural (aba + motor)
# ---------------------------------------------------------------------------
class TestRegistroEstrutural(unittest.TestCase):
    def test_nova_aba_registrada_no_config(self):
        self.assertIn("Qualidade, Proveniencia e Metodos", ABAS_DASHBOARD)
        self.assertEqual(len(ABAS_DASHBOARD), 21)
        self.assertEqual(ABAS_DASHBOARD[-1], "Qualidade, Proveniencia e Metodos")

    def test_motor_irt_registrado_no_orquestrador(self):
        from executar_por_edicao import MOTORES

        self.assertIn("irt", MOTORES)
        self.assertEqual(MOTORES["irt"][0], "algoritmos.irt.pipeline_irt")
        self.assertEqual(MOTORES["irt"][1], "executar_irt_edicao")


if __name__ == "__main__":
    unittest.main()
