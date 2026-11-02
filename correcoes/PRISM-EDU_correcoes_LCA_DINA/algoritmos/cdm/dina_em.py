"""
DINA via EM (Deterministic Inputs, Noisy "And" gate) - PRISM-EDU
CDM restrito de la Torre (2009). Parametros por item: guess g e slip s.
Prevalencia de dominio por atributo: pi. Perfil latente por aluno: alpha.

IMPORTANTE (correcao metodologica):
  A matriz-Q NAO e aleatoria. Ela e construida a partir da matriz item-OC do
  INEP (Anexo IX), consolidada em 'mestre_questao_oc.csv' pela fase de
  diagnostico de OCs. Sem essa matriz o DINA nao roda - preferimos falhar
  explicitamente a fabricar um mapeamento item-competencia sem sentido.

A estimacao e por EM real sobre os 2^K padroes latentes (nao por heuristica de
media de acertos).
"""
import pandas as pd
import numpy as np
from pathlib import Path
from itertools import product
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config import (
    SEPARADOR, ENCODING, SEED_ALEATORIA, CURSOS_MAP,
    formatar_nome_curso, caminho_saida_algoritmo,
)
try:
    from config import PASTA_MODELO_REFERENCIA, PASTA_DADOS_EXTERNOS
except ImportError:
    PASTA_MODELO_REFERENCIA = Path(__file__).resolve().parent.parent.parent
    PASTA_DADOS_EXTERNOS = Path(__file__).resolve().parent.parent.parent

MAX_ATRIBUTOS = 12
COLUNAS_Q = [f"Q{i}" for i in range(1, 39)]


class DINA_EM:
    """DINA estimado por EM (prior independente por atributo)."""

    def __init__(self, max_iter=100, tol=1e-4, tam_lote=4000, seed=SEED_ALEATORIA):
        self.max_iter = max_iter
        self.tol = tol
        self.tam_lote = tam_lote
        self.seed = seed
        self.g = self.s = self.pi = None
        self.perfis_mastery = None
        self.p_eta1 = None
        self.log_likelihood = None
        self.q_matrix = None

    def ajustar(self, X, Q):
        """X: (N,J) binario; Q: (J,K) binario. EM real sobre 2^K padroes."""
        X = np.asarray(X, dtype=np.float64)
        Q = np.asarray(Q, dtype=np.float64)
        N, J = X.shape
        K = Q.shape[1]
        self.q_matrix = Q

        padroes = np.array(list(product([0, 1], repeat=K)), dtype=np.float64)  # (P,K)
        eta = (padroes[:, None, :] >= Q[None, :, :]).prod(axis=2)               # (P,J)
        nao_eta = 1.0 - eta

        g = np.full(J, 0.2)
        s = np.full(J, 0.2)
        pi = np.full(K, 0.5)
        X_lotes = np.array_split(X, max(1, int(np.ceil(N / self.tam_lote))))

        ll_ant = -np.inf
        melhor_ll = -np.inf
        melhor = (g.copy(), s.copy(), pi.copy())
        s_ant = g_ant = None

        for it in range(self.max_iter):
            log_prior = padroes @ (np.log(pi) - np.log1p(-pi))
            g_ = np.clip(g, 1e-4, 1 - 1e-4)
            s_ = np.clip(s, 1e-4, 1 - 1e-4)
            logP1 = eta * np.log1p(-s_) + nao_eta * np.log(g_)   # x=1
            logP0 = eta * np.log(s_) + nao_eta * np.log1p(-g_)   # x=0
            base = logP0.sum(axis=1)
            dif = logP1 - logP0

            nmc = nmt = nnmc = nnmt = None
            nmc = np.zeros(J); nmt = np.zeros(J); nnmc = np.zeros(J); nnmt = np.zeros(J)
            mastery = np.zeros(K)
            ll = 0.0
            for Xb in X_lotes:
                loglik = base[:, None] + dif @ Xb.T
                log_post = log_prior[:, None] + loglik
                mx = log_post.max(axis=0)
                post = np.exp(log_post - mx[None, :])
                post /= post.sum(axis=0, keepdims=True)
                ll += (np.log(np.exp(log_prior[:, None] + loglik - mx[None, :]).sum(axis=0)).sum()
                       + mx.sum())
                soma_post = post.sum(axis=1)
                M = post @ Xb
                nmc += (eta * M).sum(axis=0)
                nnmc += (nao_eta * M).sum(axis=0)
                nmt += (eta * soma_post[:, None]).sum(axis=0)
                nnmt += (nao_eta * soma_post[:, None]).sum(axis=0)
                mastery += (padroes.T @ post).sum(axis=1)

            # M-step com pseudo-contagens (estabilidade)
            nmt += 5.0; nnmt += 5.0; nmc += 2.5; nnmc += 2.5
            s = np.clip((nmt - nmc) / np.maximum(nmt, 1e-9), 1e-4, 0.5)
            g = np.clip(nnmc / np.maximum(nnmt, 1e-9), 1e-4, 0.5)   # g,s < 0.5: identificabilidade
            pi = np.clip(mastery / N, 1e-4, 1 - 1e-4)

            mudanca = 0.0
            if s_ant is not None:
                mudanca = max(np.abs(s - s_ant).max(), np.abs(g - g_ant).max())
            s_ant, g_ant = s.copy(), g.copy()

            if it == 0:
                ll_ant = ll
            melhoria = (ll - ll_ant) / max(abs(ll_ant), 1.0)
            ll_ant = ll
            if ll > melhor_ll:
                melhor_ll = ll
                melhor = (g.copy(), s.copy(), pi.copy())
            elif ll < melhor_ll - 1e-3 * max(abs(melhor_ll), 1.0):
                break
            if it > 0 and (mudanca < self.tol or (0 < melhoria < 1e-6)):
                break

        self.g, self.s, self.pi = melhor
        self.log_likelihood = melhor_ll

        # E-step final: perfis de dominio por aluno e P(eta=1) por item
        log_prior = padroes @ (np.log(self.pi) - np.log1p(-self.pi))
        g_ = np.clip(self.g, 1e-4, 1 - 1e-4); s_ = np.clip(self.s, 1e-4, 1 - 1e-4)
        logP1 = eta * np.log1p(-s_) + nao_eta * np.log(g_)
        logP0 = eta * np.log(s_) + nao_eta * np.log1p(-g_)
        base = logP0.sum(axis=1); dif = logP1 - logP0
        self.perfis_mastery = np.zeros((N, K))
        self.p_eta1 = np.zeros(J)
        ini = 0
        for Xb in X_lotes:
            B = Xb.shape[0]
            log_post = log_prior[:, None] + base[:, None] + dif @ Xb.T
            mx = log_post.max(axis=0)
            post = np.exp(log_post - mx[None, :]); post /= post.sum(axis=0, keepdims=True)
            self.perfis_mastery[ini:ini + B, :] = (padroes.T @ post).T
            self.p_eta1 += (eta * post.sum(axis=1)[:, None]).sum(axis=0)
            ini += B
        self.p_eta1 /= N
        return self

    def prever(self):
        return self.perfis_mastery

    @property
    def n_params(self):
        J = self.q_matrix.shape[0]
        K = self.q_matrix.shape[1]
        return 2 * J + K

    def bic(self, n):
        return -2 * self.log_likelihood + self.n_params * np.log(n)

    def aic(self):
        return -2 * self.log_likelihood + 2 * self.n_params


# ==========================================================================
# MATRIZ-Q A PARTIR DO ANEXO IX DO INEP (nao aleatoria)
# ==========================================================================
def localizar_mestre_oc():
    """Procura o mestre_questao_oc.csv (matriz item-OC do INEP)."""
    candidatos = [
        PASTA_MODELO_REFERENCIA / "arquivosgerados" / "RESULTADOS_LCA" / "mestre_questao_oc.csv",
        PASTA_DADOS_EXTERNOS / "mestre_questao_oc.csv",
        Path(__file__).resolve().parent / "mestre_questao_oc.csv",
    ]
    for c in candidatos:
        if c.exists():
            return c
    raise FileNotFoundError(
        "mestre_questao_oc.csv nao encontrado. Gere-o na fase de diagnostico de OCs "
        "(5_diagnostico_OCs) ou aponte o caminho. O DINA NAO usa matriz-Q aleatoria.\n"
        "Locais procurados:\n  " + "\n  ".join(str(c) for c in candidatos)
    )


def construir_q_matrix_curso(mestre_curso, max_atributos=MAX_ATRIBUTOS):
    """Monta Q (J itens x K atributos) a partir das OCs principais do curso.
    Alinha os itens pela coluna 'posicao'. Retorna (Q, ocs, df_itens)."""
    df = mestre_curso.sort_values("posicao").reset_index(drop=True)
    freq = df["oc_principal"].value_counts()
    if len(freq) > max_atributos:
        ocs = freq.index[:max_atributos - 1].tolist() + ["OUTRAS_COMPETENCIAS"]
    else:
        ocs = freq.index.tolist()
    K = len(ocs)

    def atributo(oc):
        return oc if oc in ocs else "OUTRAS_COMPETENCIAS"

    Q = np.zeros((len(df), K), dtype=int)
    for i, (_, item) in enumerate(df.iterrows()):
        attr = atributo(item["oc_principal"])
        Q[i, ocs.index(attr)] = 1
    return Q, ocs, df


def executar_dina(caminho_csv=None):
    print("=" * 60)
    print("  PRISM-EDU: DINA (Diagnostico Cognitivo via EM)")
    print("=" * 60)

    if caminho_csv is None:
        from config import carregar_consolidado
        df = carregar_consolidado()
        if df is None or df.empty:
            print("  ERRO: dados nao encontrados.")
            return
    else:
        df = pd.read_csv(caminho_csv, sep=SEPARADOR, encoding=ENCODING, low_memory=False)

    mestre = pd.read_csv(localizar_mestre_oc(), sep=";", encoding="utf-8-sig")
    mestre["oc_principal"] = mestre["oc_principal"].astype(str).str.strip()
    print(f"  Matriz item-OC (Anexo IX) carregada: {len(mestre)} linhas")

    cols_q = [c for c in COLUNAS_Q if c in df.columns]
    pasta = caminho_saida_algoritmo("cdm", "placeholder.csv").parent
    pasta.mkdir(parents=True, exist_ok=True)

    resumo = []
    for cod, nome in CURSOS_MAP.items():
        sub_mestre = mestre[mestre["curso"] == nome] if "curso" in mestre.columns else pd.DataFrame()
        if sub_mestre.empty:
            continue
        df_curso = df[df["CO_GRUPO"] == cod] if "CO_GRUPO" in df.columns else pd.DataFrame()
        if len(df_curso) < 50:
            continue

        Q, ocs, df_itens = construir_q_matrix_curso(sub_mestre)
        J = Q.shape[0]
        # alinhamento item<->coluna: usa as J primeiras questoes, com verificacao
        cols_curso = cols_q[:J]
        if len(cols_curso) < J:
            print(f"  [AVISO] {nome}: mestre tem {J} itens mas so ha {len(cols_curso)} colunas Q; alinhando ao minimo.")
            J = len(cols_curso)
            Q = Q[:J]
        X = (df_curso[cols_curso].apply(lambda c: (c.astype(str) == "1").astype(int))).to_numpy()

        modelo = DINA_EM().ajustar(X, Q)
        p_item = (1 - modelo.s) * modelo.p_eta1 + modelo.g * (1 - modelo.p_eta1)

        pd.DataFrame({
            "questao": cols_curso,
            "oc_principal": df_itens["oc_principal"].values[:J],
            "guess_g": modelo.g.round(4),
            "slip_s": modelo.s.round(4),
            "p_domina_atributos": modelo.p_eta1.round(4),
            "p_acerto_dina": p_item.round(4),
            "taxa_acerto_real": X.mean(axis=0).round(4),
        }).to_csv(pasta / f"dina_estimativas_{formatar_nome_curso(nome)}.csv",
                  index=False, sep=SEPARADOR, encoding=ENCODING)

        pd.DataFrame(Q, columns=[f"OC_{i+1}" for i in range(Q.shape[1])],
                     index=cols_curso).to_csv(
            pasta / f"q_matrix_{formatar_nome_curso(nome)}.csv", sep=SEPARADOR, encoding=ENCODING)

        resumo.append({
            "curso": nome, "n_alunos": len(df_curso), "n_itens": J, "n_atributos": Q.shape[1],
            "guess_medio": round(float(modelo.g.mean()), 4),
            "slip_medio": round(float(modelo.s.mean()), 4),
            "log_lik": round(float(modelo.log_likelihood), 2),
            "bic": round(float(modelo.bic(len(df_curso))), 2),
        })
        print(f"    {nome}: {J} itens x {Q.shape[1]} OCs | g={modelo.g.mean():.3f} s={modelo.s.mean():.3f}")

    if resumo:
        pd.DataFrame(resumo).to_csv(pasta / "00_resumo_dina.csv",
                                    index=False, sep=SEPARADOR, encoding=ENCODING)
        print(f"\n  DINA concluido para {len(resumo)} cursos. Saida: {pasta}")
    else:
        print("  Nenhum curso processado (sem matriz-Q ou sem alunos suficientes).")


def _q_sintetica_para_teste(n_itens, n_atributos, seed=SEED_ALEATORIA):
    """SO PARA TESTES UNITARIOS. Nunca usar em analise real - a matriz-Q de
    producao vem do Anexo IX (localizar_mestre_oc)."""
    rng = np.random.default_rng(seed)
    Q = np.zeros((n_itens, n_atributos), dtype=int)
    for j in range(n_itens):
        Q[j, rng.integers(0, n_atributos)] = 1  # cada item mede >=1 atributo
    return Q


if __name__ == "__main__":
    executar_dina()
