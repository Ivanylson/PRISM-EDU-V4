"""Testes de regressao sinteticos para o PRISM-EDU.
Valida que correcoes metodologicas permanecem corretas apos alteracoes futuras.
Rode com: python -m unittest testes.testes_regressao -v
"""
import sys
from pathlib import Path
import unittest
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import SEED_ALEATORIA

RNG = np.random.default_rng(SEED_ALEATORIA)


# ---------------------------------------------------------------------------
# Dados sinteticos auxiliares
# ---------------------------------------------------------------------------

def _gerar_dados_lca_sinteticos(k_verdadeiro=3, n=2000, n_itens=25, seed=SEED_ALEATORIA):
    """Gera X binario com k classes latentes separaveis."""
    rng = np.random.default_rng(seed)
    tamanhos = rng.multinomial(n, [1 / k_verdadeiro] * k_verdadeiro)
    blocos = []
    for k_idx, n_k in enumerate(tamanhos):
        probs = np.full(n_itens, 0.15 + 0.3 * k_idx)
        bloco = (rng.random((n_k, n_itens)) < probs).astype(int)
        blocos.append(bloco)
    X = np.vstack(blocos)
    return X, np.concatenate([np.full(n_k, k_idx) for k_idx, n_k in enumerate(tamanhos)])


def _gerar_dados_dina_sinteticos(n=800, n_itens=15, n_atributos=3, seed=SEED_ALEATORIA):
    """Gera X binario simulando DINA com guess/slip conhecidos."""
    rng = np.random.default_rng(seed)
    Q = np.zeros((n_itens, n_atributos), dtype=int)
    for j in range(n_itens):
        Q[j, rng.integers(0, n_atributos)] = 1
    alphas = rng.integers(0, 2, size=(n, n_atributos))
    eta = (alphas[:, None, :] >= Q[None, :, :]).prod(axis=2)
    g = np.full(n_itens, 0.15)
    s = np.full(n_itens, 0.15)
    probs_item = eta * (1 - s) + (1 - eta) * g
    X = (rng.random((n, n_itens)) < probs_item).astype(int)
    return X, Q, g, s, alphas


def _gerar_dados_fidedignidade(n=300, n_itens=10, seed=SEED_ALEATORIA):
    """Itens com alta consistencia interna."""
    rng = np.random.default_rng(seed)
    latente = rng.normal(0, 1, n)
    X = np.zeros((n, n_itens))
    for j in range(n_itens):
        X[:, j] = (latente + rng.normal(0, 0.5, n) > 0).astype(float)
    return X


def _gerar_dados_dif(n_focal=400, n_ref=400, n_itens=20, seed=SEED_ALEATORIA):
    """Um item com DIF forte, o resto sem DIF."""
    rng = np.random.default_rng(seed)
    escore_ref = rng.integers(0, n_itens, n_ref)
    escore_focal = rng.integers(0, n_itens, n_focal)
    prob_base = escore_ref / n_itens
    prob_base_focal = escore_focal / n_itens
    X_ref = np.zeros((n_ref, n_itens), dtype=int)
    X_focal = np.zeros((n_focal, n_itens), dtype=int)
    for j in range(1, n_itens):
        X_ref[:, j] = (rng.random(n_ref) < prob_base).astype(int)
        X_focal[:, j] = (rng.random(n_focal) < prob_base_focal).astype(int)
    X_ref[:, 0] = (rng.random(n_ref) < prob_base).astype(int)
    X_focal[:, 0] = (rng.random(n_focal) < 0.8).astype(int)
    return X_ref, X_focal, escore_ref, escore_focal


# ---------------------------------------------------------------------------
# Testes
# ---------------------------------------------------------------------------

class TestLCA(unittest.TestCase):
    """Validacao do CHANGELOG: k=3 escolhido, entropia >= 0.8."""

    def test_estimar_k_escolhe_k_correto(self):
        from algoritmos.lca.pipeline_lca import estimar_k, ConfiguracaoLCA
        X, _ = _gerar_dados_lca_sinteticos(k_verdadeiro=3, n=2000, n_itens=25)
        config = ConfiguracaoLCA(k_min=2, k_max=5, n_init=15, seed=42)
        k, modelo, _, _ = estimar_k(X, config)
        self.assertEqual(k, 3)
        entropia = modelo.entropia_normalizada(X)
        self.assertGreaterEqual(entropia, 0.70, f"Entropia {entropia:.3f} abaixo do minimo")

    def test_mca_vs_lca_alta_concordancia(self):
        from algoritmos.lca.pipeline_lca import (
            ModeloLCA, ConfiguracaoLCA, kmeans_sobre_mca,
        )
        from sklearn.metrics import adjusted_rand_score
        X, _ = _gerar_dados_lca_sinteticos(k_verdadeiro=3, n=2000, n_itens=25)
        config = ConfiguracaoLCA(n_init=15, seed=42)
        modelo = ModeloLCA(config, k=3).ajustar(X)
        labels_lca = modelo.rotulos(X)
        labels_km = kmeans_sobre_mca(X, 3, seed=42)
        ari = adjusted_rand_score(labels_lca, labels_km)
        self.assertGreaterEqual(ari, 0.50, f"ARI LCA vs KMeans-MCA {ari:.3f} abaixo do esperado")


class TestLCAAgrupamentoPorCurso(unittest.TestCase):
    """A LCA deve agrupar/rotular por CO_GRUPO (chave de CURSOS_MAP), nao por
    CO_CURSO (codigo do curso na IES, que gera rotulos 'Curso_<codigo>')."""

    def _df(self):
        import pandas as pd
        return pd.DataFrame({
            "CO_IES": [1, 1, 1, 1, 2, 2, 2, 2],
            "CO_CURSO": [10, 11, 10, 11, 20, 21, 20, 21],
            "CO_GRUPO": [5, 5, 5, 5, 6, 6, 6, 6],
            "Q1": [1, 0, 1, 0, 1, 1, 0, 0],
            "Q2": [1, 1, 0, 0, 1, 0, 1, 0],
        })

    def test_coluna_curso_prefere_co_grupo(self):
        from algoritmos.lca.pipeline_lca import _coluna_curso
        df = self._df()
        self.assertEqual(_coluna_curso(df), "CO_GRUPO")
        self.assertEqual(_coluna_curso(df.drop(columns=["CO_GRUPO"])), "CO_CURSO")

    def test_filtro_agrupa_por_grupo_e_nao_por_curso(self):
        from algoritmos.lca.pipeline_lca import filtrar_ies_validas
        df = self._df()
        out = filtrar_ies_validas(df, ["Q1", "Q2"], min_ies=1)
        # IES 1 -> CO_GRUPO 5 ; IES 2 -> CO_GRUPO 6 (CO_CURSO distintos colapsam)
        grupos = out.groupby(["CO_IES", "CO_GRUPO"]).ngroups
        self.assertEqual(grupos, 2)

    def test_nome_vem_do_co_grupo(self):
        from algoritmos.lca.pipeline_lca import _coluna_curso
        from config import CURSOS_MAP
        df = self._df()
        col = _coluna_curso(df)
        nomes = {CURSOS_MAP.get(int(g), f"Curso_{g}") for g in df[col].unique()}
        self.assertIn("Medicina Veterinaria", nomes)
        self.assertIn("Odontologia", nomes)
        self.assertFalse(any(str(n).startswith("Curso_") for n in nomes))


class TestDINA(unittest.TestCase):
    """Validacao do CHANGELOG: guess/slip ~ 0.15 recuperados."""

    def test_recupera_parametros(self):
        from algoritmos.cdm.dina_em import DINA_EM
        X, Q, g_true, s_true, _ = _gerar_dados_dina_sinteticos(n=1200, n_itens=15, n_atributos=3)
        modelo = DINA_EM(max_iter=100, tol=1e-4, tam_lote=4000)
        modelo.ajustar(X, Q)
        diff_g = np.abs(modelo.g - g_true).mean()
        diff_s = np.abs(modelo.s - s_true).mean()
        self.assertLess(diff_g, 0.08, f"Erro medio guess {diff_g:.4f} acima do limite")
        self.assertLess(diff_s, 0.08, f"Erro medio slip {diff_s:.4f} acima do limite")

    def test_perfil_mastery_dimensoes(self):
        from algoritmos.cdm.dina_em import DINA_EM
        X, Q, _, _, _ = _gerar_dados_dina_sinteticos(n=600, n_itens=10, n_atributos=3)
        modelo = DINA_EM().ajustar(X, Q)
        perfil = modelo.prever()
        self.assertEqual(perfil.shape, (600, 3))


class TestFidedignidade(unittest.TestCase):

    def test_alpha_cronbach_itens_correlacionados(self):
        from algoritmos.estatistica.fidedignidade import alpha_cronbach
        X = _gerar_dados_fidedignidade(n=300, n_itens=8, seed=42)
        alpha = alpha_cronbach(X)
        self.assertGreaterEqual(alpha, 0.60, f"Alpha {alpha:.3f} esperado >= 0.60")

    def test_alpha_cronbach_itens_aleatorios_baixo(self):
        from algoritmos.estatistica.fidedignidade import alpha_cronbach
        rng = np.random.default_rng(42)
        X = rng.integers(0, 2, size=(300, 8))
        alpha = alpha_cronbach(X)
        self.assertLess(alpha, 0.15, f"Alpha aleatorio {alpha:.3f} esperado baixo")

    def test_omega_mcdonald_positivo(self):
        from algoritmos.estatistica.fidedignidade import omega_mcdonald
        X = _gerar_dados_fidedignidade(n=300, n_itens=8, seed=42)
        omega = omega_mcdonald(X, n_fatores=1, semente=42)
        self.assertFalse(np.isnan(omega), "Omega nao deve ser NaN")
        self.assertGreater(omega, 0.0)


class TestANOVARobusta(unittest.TestCase):

    def test_detecta_diferenca_entre_grupos(self):
        from algoritmos.estatistica.anova_robusta import anova_robusta
        rng = np.random.default_rng(42)
        g1 = rng.normal(50, 5, 200)
        g2 = rng.normal(55, 5, 200)
        res = anova_robusta([g1, g2], nomes=["A", "B"])
        self.assertTrue(res["valido"])
        self.assertLess(res["p_anova"], 0.05)
        self.assertGreater(res["eta2"], 0.0)

    def test_sem_diferenca_p_alto(self):
        from algoritmos.estatistica.anova_robusta import anova_robusta
        rng = np.random.default_rng(42)
        g1 = rng.normal(50, 5, 500)
        g2 = rng.normal(50, 5, 500)
        res = anova_robusta([g1, g2], nomes=["A", "B"])
        self.assertGreater(res["p_anova"], 0.05)

    def test_valido_para_grupos_insuficientes(self):
        from algoritmos.estatistica.anova_robusta import anova_robusta
        res = anova_robusta([])
        self.assertFalse(res["valido"])


class TestFDR(unittest.TestCase):

    def test_monotonia(self):
        from algoritmos.estatistica.dif import fdr_bh
        p = np.array([0.01, 0.04, 0.03, 0.10, 0.50])
        adj = fdr_bh(p)
        ordem = np.argsort(p)
        for i in range(1, len(ordem)):
            idx_prev, idx_curr = ordem[i - 1], ordem[i]
            self.assertGreaterEqual(adj[idx_curr], adj[idx_prev] - 1e-10)

    def test_menor_p_ajustado_nao_aumenta_demais(self):
        from algoritmos.estatistica.dif import fdr_bh
        p = np.array([0.001, 0.005, 0.05, 0.5])
        adj = fdr_bh(p)
        self.assertLessEqual(adj[0], 0.05)


class TestDIF(unittest.TestCase):

    def test_identifica_item_com_dif(self):
        from algoritmos.estatistica.dif import manter_haenszel_dif
        X_ref, X_focal, escore_ref, escore_focal = _gerar_dados_dif()
        df_ref = pd.DataFrame(X_ref, columns=[f"Q{i+1}" for i in range(20)])
        df_ref["grupo"] = 0
        df_ref["escore"] = escore_ref
        df_focal = pd.DataFrame(X_focal, columns=[f"Q{i+1}" for i in range(20)])
        df_focal["grupo"] = 1
        df_focal["escore"] = escore_focal
        df = pd.concat([df_ref, df_focal], ignore_index=True)
        res = manter_haenszel_dif(df, [f"Q{i+1}" for i in range(20)],
                                  "grupo", col_escore="escore")
        self.assertFalse(res.empty)
        item_dif = res[res["item"] == "Q1"]
        self.assertGreater(abs(item_dif.iloc[0]["delta_MH"]), 0)


class TestBatalhaAlvoCircular(unittest.TestCase):

    def test_retorna_none_sem_alvo(self):
        from algoritmos.preditivos.batalha_modelos import preparar_dados
        rng = np.random.default_rng(42)
        df = pd.DataFrame({f"Q{i+1}": rng.integers(0, 2, 100) for i in range(10)})
        X, y, nomes = preparar_dados(df, [f"Q{i+1}" for i in range(10)])
        self.assertIsNone(X)
        self.assertIsNone(y)

    def test_usa_alvo_externo(self):
        from algoritmos.preditivos.batalha_modelos import preparar_dados
        rng = np.random.default_rng(42)
        n = 200
        df = pd.DataFrame({f"Q{i+1}": rng.integers(0, 2, n) for i in range(10)})
        df["NT_DIS_CE"] = rng.normal(5, 1, n)
        df.loc[rng.choice(n, 20), "NT_DIS_CE"] = np.nan
        X, y, nomes = preparar_dados(df, [f"Q{i+1}" for i in range(10)])
        self.assertIsNotNone(X)
        self.assertIsNotNone(y)
        self.assertIn(0, y.values)
        self.assertIn(1, y.values)


class TestSHAPAlvoCircular(unittest.TestCase):

    def test_levanta_sem_alvo(self):
        from algoritmos.shap.shap_analysis import preparar_dados_predicao
        rng = np.random.default_rng(42)
        df = pd.DataFrame({f"Q{i+1}": rng.integers(0, 2, 200) for i in range(10)})
        with self.assertRaises(ValueError):
            preparar_dados_predicao(df, [f"Q{i+1}" for i in range(10)])

    def test_usa_alvo_externo(self):
        from algoritmos.shap.shap_analysis import preparar_dados_predicao
        rng = np.random.default_rng(42)
        n = 200
        df = pd.DataFrame({f"Q{i+1}": rng.integers(0, 2, n) for i in range(10)})
        df["NT_DIS_CE"] = rng.normal(5, 1, n)
        X, y, nomes = preparar_dados_predicao(df, [f"Q{i+1}" for i in range(10)])
        self.assertEqual(len(y), len(X))


class TestBatalhaClassificadoresClassicos(unittest.TestCase):

    def test_retorna_none_sem_dados(self):
        from algoritmos.preditivos.batalha_classificadores import executar_batalha
        self.assertIsNone(executar_batalha(None))

    def test_executa_cinco_modelos(self):
        from algoritmos.preditivos.batalha_classificadores import (
            executar_batalha, preparar_colunas,
        )
        rng = np.random.default_rng(42)
        n = 300
        cols = [f"Q{i+1}" for i in range(10)]
        df = pd.DataFrame({c: rng.integers(0, 2, n) for c in cols})
        df["NT_DIS_CE"] = rng.normal(5, 1, n)
        df.loc[rng.choice(n, 15), "NT_DIS_CE"] = np.nan
        res = executar_batalha(df, preparar_colunas(df), n_max=200, n_splits=3)
        self.assertIsNotNone(res)
        self.assertEqual(len(res), 5)
        for col in ("Modelo", "Acuracia", "F1_Score", "ROC_AUC"):
            self.assertIn(col, res.columns)
        self.assertLessEqual(res["Modelo"].str.contains("MLP").sum(), 1)

    def test_usa_alvo_externo_sem_alvo_circular(self):
        from algoritmos.preditivos.batalha_classificadores import preparar_dados
        rng = np.random.default_rng(42)
        df = pd.DataFrame({f"Q{i+1}": rng.integers(0, 2, 200) for i in range(10)})
        X, y = preparar_dados(df, [f"Q{i+1}" for i in range(10)])
        self.assertIsNone(X)
        self.assertIsNone(y)


class TestDetecaoDrift(unittest.TestCase):

    def test_psi_zero_para_identicas(self):
        from algoritmos.drift.detectar_drift import psi
        rng = np.random.default_rng(1)
        a = rng.integers(0, 2, 500)
        self.assertLess(psi(a, a.copy()), 0.01)

    def test_psi_detecta_shift(self):
        from algoritmos.drift.detectar_drift import psi
        rng = np.random.default_rng(1)
        a = rng.integers(0, 2, 500)
        b = np.ones(500, dtype=int)
        self.assertGreater(psi(a, b), 0.4)

    def test_ks_wasserstein_detectam_diferenca(self):
        from algoritmos.drift.detectar_drift import ks_wasserstein
        rng = np.random.default_rng(1)
        a = rng.normal(0, 1, 800)
        b = rng.normal(2, 1, 800)
        d, p, w = ks_wasserstein(a, b)
        self.assertLess(p, 0.05)
        self.assertGreater(w, 0.5)

    def test_drift_univariado_retorna_status(self):
        from algoritmos.drift.detectar_drift import drift_univariado
        rng = np.random.default_rng(1)
        cols = [f"Q{i+1}" for i in range(8)]
        ref = pd.DataFrame({c: rng.integers(0, 2, 400) for c in cols})
        prod = pd.DataFrame({c: rng.integers(0, 2, 400) for c in cols})
        for c in cols[:3]:
            prod[c] = 1
        uni = drift_univariado(ref, prod, cols)
        self.assertFalse(uni.empty)
        self.assertIn("Status", uni.columns)
        self.assertGreaterEqual(int(uni["Status"].str.startswith("Drift").sum()), 1)

    def test_drift_pca_detecta_shift(self):
        from algoritmos.drift.detectar_drift import drift_pca_multivariado
        rng = np.random.default_rng(1)
        cols = [f"Q{i+1}" for i in range(15)]
        ref = pd.DataFrame({c: (rng.random(600) > 0.6).astype(int) for c in cols})
        prod = pd.DataFrame({c: ((rng.random(600) + 0.5) > 0.6).astype(int) for c in cols})
        res = drift_pca_multivariado(ref, prod, cols)
        self.assertIsNotNone(res)
        self.assertIn("status", res)
        self.assertIn("mse_prod", res)
        self.assertGreater(res["mse_prod"], res["mse_baseline"])


class TestPipelineDriftTemporal(unittest.TestCase):
    """Pipeline de drift temporal: mapeamento Q->OC, proficiencia e comparacao
    no nivel de OC/notas (nunca por colunas Q* cruas)."""

    def _tabela(self):
        return pd.DataFrame({
            "CO_GRUPO": [5, 5, 5, 5],
            "QUESTAO": ["Q1", "Q2", "Q3", "Q4"],
            "OC1": ["IV - Sanidade e producao animal", "V - Reproducao animal",
                    "IV - Sanidade e producao animal", "VI - Inspecao de produtos"],
            "OC2": [None, None, None, None],
            "OC3": [None, None, None, None],
        })

    def test_remover_prefixo_oc(self):
        from algoritmos.drift.pipeline_drift import remover_prefixo_oc, chave_oc
        self.assertEqual(remover_prefixo_oc("IV - Sanidade e producao animal"),
                         "Sanidade e producao animal")
        self.assertEqual(remover_prefixo_oc("INFORMACAO E COMUNICACAO"), "INFORMACAO E COMUNICACAO")
        self.assertEqual(chave_oc("VI - Reproducao animal"), chave_oc("Reproducao animal"))

    def test_mapa_para_grupo(self):
        from algoritmos.drift.pipeline_drift import mapa_para_grupo
        mapa = mapa_para_grupo(self._tabela(), co_grupo=5)
        self.assertIn("Q1", mapa)
        self.assertIn("sanidade e producao animal", {chave for chave, _ in mapa["Q1"]})
        self.assertEqual(mapa_para_grupo(self._tabela(), co_grupo=6), {})

    def test_proficiencia_oc_intervalo_e_media(self):
        from algoritmos.drift.pipeline_drift import proficiencia_oc
        df = pd.DataFrame({
            "ALUNO": [1, 2, 3, 4],
            "CO_GRUPO": [5, 5, 5, 5],
            "Q1": [1, 0, 1, 1], "Q2": [1, 1, 0, 0],
            "Q3": [0, 1, 1, 0], "Q4": [1, 1, 1, 1],
            "NT_GER": [40, 50, 60, 70],
        })
        prof, info = proficiencia_oc(df, self._tabela(), edicao="enade_2019")
        self.assertFalse(prof.empty)
        col_sanidade = "sanidade e producao animal"
        self.assertIn(col_sanidade, prof.columns)
        valores = prof[col_sanidade].dropna()
        self.assertGreaterEqual(valores.min(), 0)
        self.assertLessEqual(valores.max(), 100)
        # Q1 e Q3 pertencem a sanidade; Q1=1,Q3=0 -> media 0.5 -> 50
        self.assertAlmostEqual(valores.iloc[0], 50.0)
        # NT_GER preservado
        self.assertListEqual(list(prof["NT_GER"]), [40, 50, 60, 70])
        self.assertIn("n_itens", info[col_sanidade])

    def test_comparacao_nao_usa_colunas_q_cruas(self):
        from algoritmos.drift.pipeline_drift import _comparar_um_curso
        rng = np.random.default_rng(7)
        n = 200
        a = pd.DataFrame({
            "NOME_CURSO": ["Medicina"] * n, "CO_GRUPO": [12] * n,
            "sanidade": rng.normal(55, 10, n), "reproducao": rng.normal(50, 10, n),
            "inspecao": rng.normal(60, 10, n), "NT_GER": rng.normal(55, 12, n),
        })
        b = a.copy()
        b[["sanidade", "reproducao", "inspecao"]] = b[["sanidade", "reproducao", "inspecao"]] + 8
        uni, pca = _comparar_um_curso(
            a, b, ["sanidade", "reproducao", "inspecao"], ["sanidade", "reproducao", "inspecao"],
            {"sanidade": {"rotulo": "Sanidade"}}, {"sanidade": {"rotulo": "Sanidade"}}, ("NT_GER",))
        self.assertIsNotNone(uni)
        variaveis = set(uni["Variavel"])
        self.assertNotIn("Q1", variaveis)
        self.assertTrue(variaveis <= {"sanidade", "reproducao", "inspecao", "NT_GER"})
        self.assertIsNotNone(pca)

    def test_referencia_segue_ciclo_do_curso(self):
        from algoritmos.drift.pipeline_drift import referencia_do_curso
        # Medicina (grupo 12) avaliada em 2016, 2019, 2023: anterior de 2019 = 2016
        self.assertEqual(referencia_do_curso("enade_2019", "medicina", "consecutivas"), "enade_2016")
        # Primeira edicao do curso nao tem referencia
        self.assertIsNone(referencia_do_curso("enade_2004", "medicina", "consecutivas"))
        # Baseline fixo
        self.assertEqual(referencia_do_curso("enade_2023", "medicina", "baseline", baseline=2019),
                         "enade_2019")

    def test_modo_baseline_ignora_curso_sem_baseline(self):
        from algoritmos.drift.pipeline_drift import referencia_do_curso
        # Engenharia de Alimentos 6002 so aparece em 2017/2019/2023
        self.assertIsNone(referencia_do_curso("enade_2023", "engenharia de alimentos", "baseline", baseline=2004))

    def test_tendencia_monta_matriz_dos_artefatos(self):
        import tempfile, os
        from algoritmos.drift.pipeline_drift import montar_tendencia
        with tempfile.TemporaryDirectory() as tmp:
            pasta_prod = os.path.join(tmp, "enade_2019")
            os.makedirs(pasta_prod)
            pd.DataFrame({
                "Curso": ["Medicina", "Medicina"],
                "Variavel": ["sanidade", "NT_GER"],
                "Status": ["Drift (KS significativo)", "Sem drift"],
                "KS_p": [0.01, 0.4],
            }).to_csv(os.path.join(pasta_prod, "drift_univariado_enade_2016.csv"), index=False)
            gravados = montar_tendencia(pasta_drift=tmp)
            self.assertIn("tendencia_long", gravados)
            self.assertTrue(os.path.exists(gravados["tendencia_long"]))
            longo = pd.read_csv(gravados["tendencia_long"])
            self.assertIn("enade_2019 vs enade_2016", set(longo["Par"]))


class TestAntiRegressaoConteudoFabricado(unittest.TestCase):
    """Garante que valores/conteudos fabricados removidos pelo parecer NAO voltem.

    Varre os dashboards procurando as strings proibidas. Se alguem reintroduzir
    uma tabela/dado inventado, o teste falha.
    """

    ARQUIVOS = [
        Path(__file__).resolve().parent.parent / "correcoes" / "fase5_visualizacao" / "dashboard_completo.py",
        Path(__file__).resolve().parent.parent / "dashboard" / "app.py",
    ]

    # strings que representam conteudo fabricado ja removido
    PROIBIDAS = [
        "melhoria / 100 * 16",
        "entropia 0,88",
        "Entropia (0.88)",
        "83% de reprova",
        "elevação exponencial",
        "elevacao exponencial",
    ]

    def _ler(self, caminho):
        if not caminho.exists():
            self.skipTest(f"{caminho} nao encontrado")
        return caminho.read_text(encoding="utf-8", errors="replace")

    def test_sem_strings_fabricadas(self):
        for caminho in self.ARQUIVOS:
            conteudo = self._ler(caminho)
            for proibida in self.PROIBIDAS:
                self.assertNotIn(
                    proibida, conteudo,
                    f"String fabricada '{proibida}' reapareceu em {caminho.name}")

    def test_lca_sem_tabela_hardcoded(self):
        """A tabela LCA fabricada tinha 'Log-Likelihood' com valores digitados."""
        for caminho in self.ARQUIVOS:
            conteudo = self._ler(caminho)
            self.assertNotIn('"Log-Likelihood": [-1520', conteudo.replace("'", '"'),
                             f"Tabela LCA fabricada reapareceu em {caminho.name}")

    def test_simulador_sem_alvo_circular(self):
        """O alvo 'Alto_Desempenho = Media_Global >= 60' nao pode voltar como treino."""
        for caminho in self.ARQUIVOS:
            conteudo = self._ler(caminho)
            self.assertNotIn(
                "df_treino['Alto_Desempenho'] = np.where(df_treino['Media_Global']",
                conteudo,
                f"Alvo circular do simulador reapareceu em {caminho.name}")


class TestSimuladorContrafactualHonesto(unittest.TestCase):
    """O simulador so treina com alvo EXTERNO; sem alvo, cai em aritmetico."""

    def _df(self):
        rng = np.random.default_rng(3)
        n = 120
        return pd.DataFrame({
            "Q1": rng.integers(0, 2, n), "Q2": rng.integers(0, 2, n),
            "Q3": rng.integers(0, 2, n), "Q4": rng.integers(0, 2, n),
            "NT_GER": rng.normal(55, 12, n),
        })

    def test_detecta_alvo_externo(self):
        from algoritmos.xai.simulador_contrafactual import detectar_alvo_externo
        self.assertEqual(detectar_alvo_externo(self._df()), "NT_GER")
        self.assertIsNone(detectar_alvo_externo(pd.DataFrame({"Q1": [1, 0, 1, 0]})))

    def test_sem_alvo_nao_treina(self):
        from algoritmos.xai.simulador_contrafactual import treinar_simulador
        df = self._df().drop(columns=["NT_GER"])
        modelo, info = treinar_simulador(df, ["Q1", "Q2", "Q3", "Q4"])
        self.assertIsNone(modelo)
        self.assertEqual(info["modo"], "aritmetico")

    def test_com_alvo_treina_supervisionado(self):
        from algoritmos.xai.simulador_contrafactual import treinar_simulador, simular
        df = self._df()
        modelo, info = treinar_simulador(df, ["Q1", "Q2", "Q3", "Q4"], alvo="NT_GER")
        self.assertIsNotNone(modelo)
        self.assertEqual(info["modo"], "supervisionado")
        res = simular(modelo, df, ["Q1", "Q2", "Q3", "Q4"], {"Q1": 10})
        self.assertEqual(res["modo"], "supervisionado")

    def test_aritmetico_recalcula(self):
        from algoritmos.xai.simulador_contrafactual import simular
        rng = np.random.default_rng(11)
        n = 120
        df = pd.DataFrame({
            "d1": rng.normal(50, 12, n).clip(0, 100),
            "d2": rng.normal(55, 12, n).clip(0, 100),
            "d3": rng.normal(58, 12, n).clip(0, 100),
        })
        res = simular(None, df, ["d1", "d2", "d3"], {"d1": 10})
        self.assertEqual(res["modo"], "aritmetico")
        self.assertGreater(res["taxa_simulada"], res["taxa_atual"])


class TestTransparenciaIA(unittest.TestCase):
    """A config de IA exibida deve vir de config.py (nao pseudo-codigo)."""

    def test_resumo_config_real(self):
        from algoritmos.opencode.config_ia import resumo_config
        cfg = resumo_config()
        self.assertGreaterEqual(cfg["n_modelos"], 1)
        self.assertTrue(cfg["servidor_url"].startswith("http"))
        self.assertIn("big-pickle", dict(cfg["modelos"]))
        self.assertTrue(len(cfg["politica_grounding"]) >= 3)

    def test_status_servidor_probe_injetavel(self):
        from algoritmos.opencode.config_ia import status_servidor
        res_on = status_servidor(probe=lambda url: True)
        res_off = status_servidor(probe=lambda url: False)
        self.assertTrue(res_on["ativo"])
        self.assertFalse(res_off["ativo"])


class TestOntologia(unittest.TestCase):
    """Ontologia educacional: grafo real, exportavel, sem nos orfaos."""

    def _onto(self):
        from algoritmos.ontologia.ontologia_enade import OntologiaEnade
        onto = OntologiaEnade()
        onto.carregar_grupos()
        return onto

    def test_carrega_grupos_reais(self):
        onto = self._onto()
        resumo = onto.resumo()
        self.assertGreater(resumo["por_tipo"].get("Curso", 0), 50)
        self.assertGreater(resumo["por_tipo"].get("Edicao", 0), 10)

    def test_arestas_consistentes(self):
        onto = self._onto()
        ids = set(onto.nos)
        for origem, _rel, destino, _peso in onto.arestas:
            self.assertIn(origem, ids)
            self.assertIn(destino, ids)

    def test_exportacao_jsonld_e_turtle(self):
        onto = self._onto()
        jsonld = onto.para_jsonld()
        self.assertIn("@graph", jsonld)
        self.assertGreater(len(jsonld["@graph"]), 0)
        ttl = onto.para_turtle()
        self.assertIn("@prefix prism:", ttl)
        self.assertIn("a prism:Curso", ttl)

    def test_remover_prefixo_romano_ontologia(self):
        from algoritmos.ontologia.ontologia_enade import _remover_prefixo_romano
        self.assertEqual(_remover_prefixo_romano("IV - Etica e cidadania"), "Etica e cidadania")
        self.assertEqual(_remover_prefixo_romano("Morfofisiologia"), "Morfofisiologia")


class TestRAGLocal(unittest.TestCase):
    """RAG local: chunking, indice TF-IDF e grounding (citacao de fonte)."""

    def _indice(self):
        from algoritmos.rag.indexador_rag import IndiceRAG
        chunks = [
            {"id": "c0", "fonte": "medicina.md",
             "texto": "competencias de medicina incluem clinica medica e saude coletiva", "meta": {}},
            {"id": "c1", "fonte": "eng.md",
             "texto": "engenharia de alimentos aborda processos e microbiologia de alimentos", "meta": {}},
            {"id": "c2", "fonte": "ped.md",
             "texto": "pedagogia trata de didatica e avaliacao da aprendizagem", "meta": {}},
        ]
        return IndiceRAG().indexar(chunks)

    def test_chunking_respeita_tamanho(self):
        from algoritmos.rag.indexador_rag import dividir_em_chunks
        texto = "frase. " * 400
        chunks = dividir_em_chunks(texto, tamanho=200, sobreposicao=20)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= 240 for c in chunks))

    def test_busca_ordena_por_relevancia(self):
        idx = self._indice()
        res = idx.buscar("clinica medica saude", top_k=3)
        self.assertGreater(len(res), 0)
        self.assertEqual(res[0]["fonte"], "medicina.md")

    def test_busca_respeita_limiar(self):
        idx = self._indice()
        res = idx.buscar("assunto totalmente alheio xyzzy", top_k=3, limiar=0.5)
        self.assertEqual(res, [])

    def test_prompt_rag_exige_citacao(self):
        from algoritmos.rag.rag_opencode import construir_prompt_rag
        res = [{"fonte": "medicina.md", "texto": "conteudo x"}]
        prompt = construir_prompt_rag("pergunta?", res)
        self.assertIn("[medicina.md]", prompt)
        self.assertIn("Dados insuficientes", prompt)

    def test_responder_sem_fonte_recusa(self):
        from algoritmos.rag.rag_opencode import responder_com_rag
        res = responder_com_rag("algo", indice=self._indice(), limiar=0.9,
                                enviar_prompt=lambda *a, **k: {"response": "x", "success": True})
        self.assertEqual(res["fontes"], [])
        self.assertIn("Dados insuficientes", res["resposta"])

    def test_responder_com_fonte_usa_modelo(self):
        from algoritmos.rag.rag_opencode import responder_com_rag
        capturado = {}

        def fake(prompt, model_id="big-pickle"):
            capturado["prompt"] = prompt
            return {"response": "Clinica medica [medicina.md]", "success": True}

        res = responder_com_rag("clinica medica", indice=self._indice(), enviar_prompt=fake)
        self.assertTrue(res["sucesso"])
        self.assertIn("medicina.md", res["fontes"])
        self.assertIn("medicina.md", capturado["prompt"])


class TestServidorMCP(unittest.TestCase):
    """Servidor MCP: handshake JSON-RPC, tools/list e tools/call honestas."""

    def _req(self, metodo, params=None, rid=1):
        from mcp.prism_edu_server import tratar_requisicao
        req = {"jsonrpc": "2.0", "id": rid, "method": metodo}
        if params is not None:
            req["params"] = params
        return tratar_requisicao(req)

    def test_initialize_handshake(self):
        resp = self._req("initialize")
        self.assertEqual(resp["result"]["serverInfo"]["name"], "prism-edu")
        self.assertIn("protocolVersion", resp["result"])

    def test_notificacao_sem_resposta(self):
        from mcp.prism_edu_server import tratar_requisicao
        resp = tratar_requisicao({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertIsNone(resp)

    def test_tools_list_nao_vazia(self):
        resp = self._req("tools/list")
        nomes = [t["name"] for t in resp["result"]["tools"]]
        self.assertIn("buscar_corpus_rag", nomes)
        self.assertIn("resumo_ontologia", nomes)
        self.assertTrue(all("inputSchema" in t for t in resp["result"]["tools"]))

    def test_tools_call_desconhecida_erro(self):
        resp = self._req("tools/call", {"name": "inexistente", "arguments": {}})
        self.assertIn("error", resp)

    def test_listar_cursos_avaliados(self):
        import json as _json
        resp = self._req("tools/call", {"name": "listar_cursos_avaliados", "arguments": {}})
        payload = _json.loads(resp["result"]["content"][0]["text"])
        self.assertGreater(payload["n_cursos"], 0)
        self.assertGreater(payload["n_edicoes"], 0)

    def test_config_ia_grounding(self):
        import json as _json
        resp = self._req("tools/call", {"name": "config_ia", "arguments": {}})
        payload = _json.loads(resp["result"]["content"][0]["text"])
        self.assertGreaterEqual(len(payload["politica_grounding"]), 3)

    def test_simular_sem_csv_declara_insuficiente(self):
        resp = self._req("tools/call",
                         {"name": "simular_cenario", "arguments": {"curso": "MEDICINA"}})
        texto = resp["result"]["content"][0]["text"]
        self.assertIn("Dados insuficientes", texto)


class TestFinetuningPromptTuning(unittest.TestCase):
    """Dataset/prompt-tuning/avaliacao: sem treino de pesos, com grounding."""

    def _exemplos(self):
        from algoritmos.finetuning.construir_dataset import _exemplo_de_linha
        linhas = [
            {"NOME_CURSO": "MEDICINA", "NU_ANO": 2019, "QUESTAO": "1",
             "OC1": "Saude coletiva", "TAXA_DEFICIENCIA_%": 40.0},
            {"NOME_CURSO": "MEDICINA", "NU_ANO": 2019, "QUESTAO": "2",
             "OC1": "Clinica medica", "TAXA_DEFICIENCIA_%": 25.0},
            {"NOME_CURSO": "MEDICINA", "NU_ANO": 2019, "QUESTAO": "1",
             "OC1": "Saude coletiva", "TAXA_DEFICIENCIA_%": 40.0},
        ]
        return [e for e in (_exemplo_de_linha(r) for r in linhas) if e]

    def test_exemplo_tem_3_papeis(self):
        ex = self._exemplos()[0]
        papeis = [m["role"] for m in ex["messages"]]
        self.assertEqual(papeis, ["system", "user", "assistant"])
        self.assertIn("40.0", ex["messages"][2]["content"])

    def test_linha_sem_oc_ignorada(self):
        from algoritmos.finetuning.construir_dataset import _exemplo_de_linha
        self.assertIsNone(_exemplo_de_linha({"NOME_CURSO": "X", "OC1": ""}))

    def test_few_shot_diversificado(self):
        from algoritmos.finetuning.prompt_tuning import selecionar_few_shot
        few = selecionar_few_shot(self._exemplos(), n=5)
        chaves = {(e["meta"].get("curso"), e["meta"].get("questao")) for e in few}
        self.assertEqual(len(chaves), len(few))

    def test_avaliacao_detecta_alucinacao(self):
        from algoritmos.finetuning.avaliar_ia import avaliar_resposta
        ok = avaliar_resposta("Taxa 40 [f]", "Taxa 40 [f]", fonte="f.csv")
        self.assertTrue(ok["grounded"])
        self.assertFalse(ok["alucinou"])
        ruim = avaliar_resposta("Taxa 99", "Taxa 40", fonte="f.csv")
        self.assertTrue(ruim["alucinou"])
        self.assertFalse(ruim["grounded"])


class TestAnalisesTese(unittest.TestCase):
    """E1-E9: analises ancoradas em microdados reais (ou 'insuficiente')."""

    def _df(self):
        import numpy as np
        import pandas as pd
        rng = np.random.default_rng(42)
        n = 1200
        return pd.DataFrame({
            "CO_IES": rng.integers(1, 12, n),
            "CO_GRUPO": rng.integers(1, 5, n),
            "CO_REGIAO_CURSO": rng.integers(1, 6, n),
            "CO_CATEGAD": rng.integers(1, 4, n),
            "CO_MODALIDADE": rng.integers(1, 3, n),
            "TP_SEXO": rng.choice(["M", "F"], n),
            "NU_ANO_CURSO": rng.integers(1, 6, n),
            "NU_IDADE": rng.integers(18, 40, n),
            "PESO_AMOSTRA": rng.uniform(1, 10, n),
            "QE_I01": rng.choice(["A", "B", "C", "D"], n),
            "QE_I02": rng.choice(["A", "B", "C"], n),
            "QE_I03": rng.choice(["A", "B"], n),
            "NT_DIS_CE": rng.normal(50, 15, n),
            "Q1": rng.integers(0, 2, n), "Q2": rng.integers(0, 2, n),
            "Q3": rng.integers(0, 2, n), "Q4": rng.integers(0, 2, n),
            "Q5": rng.integers(0, 2, n), "Q6": rng.integers(0, 2, n),
        })

    def test_e1_equidade_ok(self):
        from algoritmos.analises_tese import analises_tese as A
        res = A.equidade(self._df(), 2019)
        self.assertEqual(res["status"], "ok")
        self.assertIn("regiao", res)
        self.assertGreaterEqual(res["regiao"]["gap"], 0)

    def test_e2_valor_agregado_ok(self):
        from algoritmos.analises_tese import analises_tese as A
        res = A.valor_agregado(self._df(), 2019)
        self.assertEqual(res["status"], "ok")
        self.assertGreaterEqual(res["n"], 100)

    def test_e5_e6_e7_ok(self):
        from algoritmos.analises_tese import analises_tese as A
        df = self._df()
        self.assertEqual(A.formacao(df, 2019)["status"], "ok")
        self.assertEqual(A.eficiencia(df, 2019)["status"], "ok")
        self.assertEqual(A.cluster_ies(df, 2019)["status"], "ok")

    def test_e8_e9_ok(self):
        from algoritmos.analises_tese import analises_tese as A
        df = self._df()
        self.assertEqual(A.distal(df, 2019)["status"], "ok")
        res = A.sensibilidade(df, 2019)
        self.assertEqual(res["status"], "ok")
        self.assertIn("tau_kendall_peso", res)

    def test_insuficiente_sem_nota(self):
        import pandas as pd
        from algoritmos.analises_tese import analises_tese as A
        df = pd.DataFrame({"CO_IES": [1, 2], "Q1": [1, 0]})
        self.assertEqual(A.equidade(df)["status"], "insuficiente")


class TestPonteLCACDM(unittest.TestCase):
    """Ponte LCA -> CDM restrito (DINA): matriz-Q do INEP, rotulos OC e
    artefatos por curso. Integridade: a matriz-Q vem do Anexo IX, nao e
    aleatoria, e o alvo (nota) nao entra na estimacao."""

    def _mestre(self):
        import pandas as pd
        return pd.DataFrame({
            "curso": ["Agronomia"] * 6,
            "questao": [f"Q{i}" for i in range(1, 7)],
            "posicao": list(range(1, 7)),
            "area_prova": ["FG"] * 6,
            "oc_principal": ["OC1", "OC1", "OC2", "OC2", "OC2", "OC3"],
            "oc_secundario": [""] * 6,
        })

    def test_localiza_mestre_local(self):
        from algoritmos.cdm.dina_em import localizar_mestre_oc
        caminho = localizar_mestre_oc()
        self.assertTrue(caminho.exists())
        self.assertEqual(caminho.name, "mestre_questao_oc.csv")

    def test_constroi_q_matrix_por_oc(self):
        from algoritmos.cdm.ponte_lca_cdm import construir_q_matrix_curso
        Q, ocs, df = construir_q_matrix_curso(self._mestre())
        self.assertEqual(Q.shape[1], len(ocs))
        self.assertEqual(Q.shape[0], 6)
        self.assertTrue(set(ocs).issubset({"OC1", "OC2", "OC3"}))
        # cada item mede exatamente 1 atributo
        self.assertTrue(np.all(Q.sum(axis=1) == 1))

    def test_rotulo_oc(self):
        from algoritmos.cdm.ponte_lca_cdm import rotulo_oc
        self.assertEqual(rotulo_oc(0), "OC_A")
        self.assertEqual(rotulo_oc(1), "OC_B")

    def test_normalizar_casa_nome_curso(self):
        from algoritmos.cdm.ponte_lca_cdm import normalizar
        self.assertEqual(normalizar("Arquitetura e Urbanismo"), "arquiteturaeurbanismo")
        self.assertEqual(normalizar("Medicina Veterinária"), "medicinaveterinaria")

    def test_mestre_nao_tem_colunas_nt(self):
        from algoritmos.cdm.dina_em import localizar_mestre_oc
        import pandas as pd
        mestre = pd.read_csv(localizar_mestre_oc(), sep=";", encoding="utf-8-sig", nrows=5)
        self.assertFalse(any("NT_" in c for c in mestre.columns),
                         "mestre (matriz-Q) nao deve conter colunas-alvo NT_*")


def _micro_sintetico(n=80, seed=SEED_ALEATORIA):
    """Microdados minimos de Agronomia (CO_GRUPO 17) para regressao."""
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({
        "ALUNO": [f"aluno_{i}" for i in range(n)],
        "CO_GRUPO": [17] * n,
        "CO_CURSO": [1701] * n,
        "CO_IES": rng.integers(1, 5, n),
        "TP_PR_GER": [1] * n,
        "NT_DIS_CE": rng.normal(50, 10, n),
    })
    for j in range(1, 7):
        df[f"Q{j}"] = rng.integers(0, 2, n)
    return df


def _mestre_agronomia_alinhado():
    """Mestre de Agronomia cujos itens NAO sao as primeiras colunas Q*.

    Testa o alinhamento por rotulo ('questao'), nao por posicao no CSV.
    """
    return pd.DataFrame({
        "curso": ["Agronomia"] * 3,
        "questao": ["Q2", "Q4", "Q6"],
        "posicao": [1, 2, 3],
        "area_prova": ["CE"] * 3,
        "oc_principal": ["OC1", "OC2", "OC3"],
        "oc_secundario": [""] * 3,
    })


class TestPonteLCACDMArtefatos(unittest.TestCase):
    """Regressao ponta a ponta da ponte LCA->CDM com dados sinteticos.

    Garante que os artefatos consumidos pelo dashboard sao gerados, que os
    itens sao alinhados pelo rotulo real da questao e que o alvo externo
    (NT_DIS_CE) nao entra na matriz-Q.
    """

    def test_processar_edicao_gera_artefatos_validos(self):
        import tempfile
        from algoritmos.cdm.ponte_lca_cdm import processar_edicao

        df = _micro_sintetico()
        mestre = _mestre_agronomia_alinhado()
        with tempfile.TemporaryDirectory() as tmp:
            resumo = processar_edicao(
                edicao="teste", df=df, mestre=mestre, pasta_saida=tmp)
            pasta = Path(tmp)

            for nome in [
                "00_resumo_geral.csv", "comparacao_lca_vs_dina.csv",
                "concordancia_lca_dina.csv", "dina_estimativas_agronomia.csv",
                "dina_perfis_alunos_agronomia.csv", "matriz_q_agronomia.csv",
                "dicionario_ocs_agronomia.csv", "validador_matriz_q_agronomia.xlsx",
            ]:
                self.assertTrue((pasta / nome).exists(), f"artefato ausente: {nome}")

            self.assertEqual(len(resumo), 1)
            self.assertEqual(resumo.iloc[0]["curso"], "Agronomia")
            self.assertEqual(int(resumo.iloc[0]["n_alunos"]), len(df))

            mq = pd.read_csv(pasta / "matriz_q_agronomia.csv", sep=";")
            # Alinhamento por rotulo, nao pelas 3 primeiras colunas Q (Q1..Q3)
            self.assertListEqual(list(mq["Questao"]), ["Q2", "Q4", "Q6"])
            self.assertNotIn("NT_DIS_CE", mq.columns)
            cols_q = [c for c in mq.columns if c.startswith("OC_")]
            self.assertEqual(len(cols_q), 3)
            self.assertTrue((mq[cols_q].sum(axis=1) == 1).all())

            dic = pd.read_csv(pasta / "dicionario_ocs_agronomia.csv",
                              sep=";", decimal=",")
            self.assertEqual(int(dic["n_itens_medidos"].sum()), 3)
            self.assertTrue((dic["n_itens_medidos"] >= 1).all())

            est = pd.read_csv(pasta / "dina_estimativas_agronomia.csv",
                              sep=";", decimal=",")
            self.assertListEqual(list(est["Questao"]), ["Q2", "Q4", "Q6"])
            # o M-step aplica limite de identificabilidade em [0, 0.5]
            self.assertTrue(((est["guess_g"] >= 0) & (est["guess_g"] <= 0.5)).all())
            self.assertTrue(((est["slip_s"] >= 0) & (est["slip_s"] <= 0.5)).all())
            self.assertNotIn("NT_DIS_CE", est.columns)

            perf = pd.read_csv(pasta / "dina_perfis_alunos_agronomia.csv",
                               sep=";", decimal=",")
            self.assertEqual(len(perf), len(df))
            self.assertIn("NT_DIS_CE", perf.columns)  # descritivo, nao feature
            for c in [c for c in perf.columns if c.startswith("alpha_")]:
                self.assertTrue(set(perf[c].unique()).issubset({0, 1}))
            self.assertTrue(
                (perf["n_ocs_dominadas"] ==
                 perf[[c for c in perf.columns if c.startswith("alpha_")]].sum(axis=1)).all())

            comp = pd.read_csv(pasta / "comparacao_lca_vs_dina.csv",
                               sep=";", decimal=",")
            self.assertEqual(int(comp.iloc[0]["n_atributos_dina"]), 3)

            conc = pd.read_csv(pasta / "concordancia_lca_dina.csv",
                               sep=";", decimal=",")
            self.assertEqual(len(conc), 3)
            self.assertTrue(set(conc["status_validacao"]) == {"PENDENTE_VALIDACAO"})

    def test_alvo_nao_altera_estimacao_dina(self):
        """Trocar apenas NT_DIS_CE nao pode mudar guess/slip (alvo externo)."""
        import tempfile
        from algoritmos.cdm.ponte_lca_cdm import processar_edicao

        df = _micro_sintetico(seed=7)
        mestre = _mestre_agronomia_alinhado()
        df2 = df.copy()
        df2["NT_DIS_CE"] = df2["NT_DIS_CE"] + 1000
        with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
            processar_edicao(edicao="teste", df=df, mestre=mestre, pasta_saida=t1)
            processar_edicao(edicao="teste", df=df2, mestre=mestre, pasta_saida=t2)
            e1 = pd.read_csv(Path(t1) / "dina_estimativas_agronomia.csv",
                             sep=";", decimal=",")
            e2 = pd.read_csv(Path(t2) / "dina_estimativas_agronomia.csv",
                             sep=";", decimal=",")
            pd.testing.assert_series_equal(e1["guess_g"], e2["guess_g"])
            pd.testing.assert_series_equal(e1["slip_s"], e2["slip_s"])


class TestPerfilAlunoOC(unittest.TestCase):
    """Perfil cognitivo por aluno x OC: media de acerto observada (nao CDM).

    O artefato deve ser rotulado honestamente: primeira aba com os dados e
    segunda aba 'LEIA-ME' declarando que NAO e um modelo DINA/CDM.
    """

    def test_formata_nome_arquivo(self):
        from algoritmos.cdm.perfil_aluno_oc import formatar_nome_arquivo
        self.assertEqual(formatar_nome_arquivo("Medicina Veterinária"), "medicina_veterinaria")

    def test_media_acerto_por_oc(self):
        import pandas as pd
        from algoritmos.cdm.perfil_aluno_oc import normalizar
        df = pd.DataFrame({"ALUNO": ["a", "b"], "Q1": [1, 0], "Q2": [1, 1]})
        m = df[["Q1", "Q2"]].to_numpy(dtype=float).mean(axis=1) * 100
        self.assertAlmostEqual(m[0], 100.0)
        self.assertAlmostEqual(m[1], 50.0)
        # normalizacao de OC nao depende de acentos
        self.assertEqual(normalizar("Zootecnia"), "zootecnia")

    def test_gerar_perfis_rotulo_honesto_e_media_real(self):
        import tempfile
        from algoritmos.cdm.perfil_aluno_oc import gerar_perfis_edicao

        df = _micro_sintetico(seed=3)
        mestre = _mestre_agronomia_alinhado()
        with tempfile.TemporaryDirectory() as tmp:
            gerados = gerar_perfis_edicao(
                edicao="teste", df=df, mestre=mestre, pasta_saida=tmp)
            self.assertIn("Agronomia", gerados)
            caminho = Path(tmp) / "diagnostico_cognitivo_agronomia.xlsx"
            self.assertTrue(caminho.exists())

            xls = pd.ExcelFile(caminho, engine="openpyxl")
            try:
                self.assertListEqual(xls.sheet_names, ["Perfil_Aluno_OC", "LEIA-ME"])
            finally:
                xls.close()

            dados = pd.read_excel(caminho, sheet_name="Perfil_Aluno_OC", engine="openpyxl")
            self.assertListEqual(
                list(dados.columns),
                ["ALUNO", "CO_GRUPO", "NOME_CURSO", "Conhecimentos Gerais",
                 "OC1", "OC2", "OC3",
                 "MAIOR_DOMINIO_DISCIPLINA", "PIOR_DEFICIENCIA_DISCIPLINA"])
            self.assertNotIn("CO_CURSO", dados.columns)
            self.assertEqual(int(dados.iloc[0]["CO_GRUPO"]), 17)

            # media observada: OC1 = Q2; OC2 = Q4; OC3 = Q6
            for oc, q in [("OC1", "Q2"), ("OC2", "Q4"), ("OC3", "Q6")]:
                esperado = round(float(df.iloc[0][q]) * 100, 2)
                self.assertAlmostEqual(float(dados.iloc[0][oc]), esperado)
            # Conhecimentos Gerais = media de Q1..Q9 (apenas Q1..Q6 existem)
            esperado_cg = round(df.iloc[0][[f"Q{i}" for i in range(1, 7)]]
                                .to_numpy(dtype=float).mean() * 100, 2)
            self.assertAlmostEqual(float(dados.iloc[0]["Conhecimentos Gerais"]), esperado_cg)

            meta = pd.read_excel(caminho, sheet_name="LEIA-ME", engine="openpyxl")
            campos = dict(zip(meta["campo"], meta["valor"]))
            self.assertIn("NAO E UM CDM/DINA", str(campos["AVISO_DE_INTEGRIDADE"]))
            self.assertIn("descritivo", str(campos["METODO"]).lower())
            self.assertEqual(str(campos["FONTE_MATRIZ_OC"]).split()[0],
                             "mestre_questao_oc.csv")

    def test_oc_sem_coluna_no_microdado_nao_quebra(self):
        import tempfile
        from algoritmos.cdm.perfil_aluno_oc import gerar_perfis_edicao

        df = _micro_sintetico(n=20)
        mestre = _mestre_agronomia_alinhado().iloc[[0]].copy()
        mestre["questao"] = "Q99"  # nao existe no microdado
        with tempfile.TemporaryDirectory() as tmp:
            gerar_perfis_edicao(edicao="teste", df=df, mestre=mestre, pasta_saida=tmp)
            caminho = Path(tmp) / "diagnostico_cognitivo_agronomia.xlsx"
            dados = pd.read_excel(caminho, sheet_name=0, engine="openpyxl")
            self.assertEqual(str(dados.iloc[0]["MAIOR_DOMINIO_DISCIPLINA"]), "SEM_OC")
            self.assertEqual(len([c for c in dados.columns if c.startswith("OC")]), 0)


class TestPreditivosCVeCalibracao(unittest.TestCase):
    """Regressao: CV nao pode falhar silenciosamente com y Series (indice nao posicional)."""

    def test_cv_aceita_serie_com_indice_nao_posicional(self):
        import pandas as pd
        from sklearn.linear_model import LogisticRegression
        from algoritmos.preditivos.batalha_modelos import avaliar_modelo_cv, tabela_calibracao

        rng = np.random.RandomState(0)
        X = rng.randint(0, 2, size=(180, 6))
        y = pd.Series(rng.randint(0, 2, size=180), index=np.arange(500, 680))
        metricas, oof = avaliar_modelo_cv(LogisticRegression, X, y, n_splits=3)
        self.assertEqual(len(oof), 180)
        self.assertFalse(np.isnan(oof).any())
        self.assertGreater(len(tabela_calibracao(y, oof)), 0)

    def test_importancia_e_calibracao_geradas(self):
        import tempfile
        from pathlib import Path
        import pandas as pd
        from algoritmos.preditivos.batalha_modelos import executar_batalha_curso

        rng = np.random.RandomState(1)
        n = 240
        df = pd.DataFrame(rng.randint(0, 2, size=(n, 6)),
                          columns=[f"Q{i}" for i in range(1, 7)])
        score = df.sum(axis=1).to_numpy()
        df["NT_DIS_CE"] = np.where(score >= 3, 70.0, 30.0)
        colunas = [f"Q{i}" for i in range(1, 7)]
        with tempfile.TemporaryDirectory() as tmp:
            executar_batalha_curso(df, colunas, "Curso Teste", Path(tmp))
            self.assertTrue(list(Path(tmp).glob("calibracao_*.csv")))
            self.assertTrue(list(Path(tmp).glob("importancia_variaveis_*.csv")))
            self.assertTrue(list(Path(tmp).glob("metricas_modelos_cv_*.csv")))


if __name__ == "__main__":
    unittest.main()
