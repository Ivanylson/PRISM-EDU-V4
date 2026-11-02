"""
Simulador Contrafactual Curricular (What-If Analytics) - versao honesta.

Regras de integridade (para nao repetir o vazamento de alvo do parecer):
- O alvo deve ser EXTERNO as features (nota ENADE NT_DIS_CE > NT_CE_D1 > NT_GER).
- Se nao houver alvo externo, NAO se treina modelo supervisionado: retorna-se
  None e o chamador usa a leitura aritmetica (declarada), em vez de inventar.
- As features sao apenas itens/disciplinas (Q* ou nomes de disciplina), nunca NT_*.

API:
    detectar_alvo_externo(df) -> str | None
    taxa_excelencia(alvo, corte) -> float
    treinar_simulador(df, colunas_disc, alvo=None) -> (modelo | None, info)
    simular(modelo, df, colunas_disc, alteracoes, alvo=None, corte=60) -> dict
"""
import numpy as np
import pandas as pd

SEED = 42
COLUNAS_ALVO = ("NT_DIS_CE", "NT_CE_D1", "NT_GER")
CORTE_PADRAO = 60.0
PREFIXOS_FEATURE = ("Q",)


def detectar_alvo_externo(df):
    """Retorna o nome da primeira coluna de nota externa valida, ou None.

    So considera valido se houver variabilidade real (>= 2 valores unicos e
    mais de 10 observacoes), para evitar alvos degenerados.
    """
    if df is None or df.empty:
        return None
    for cand in COLUNAS_ALVO:
        if cand in df.columns:
            serie = pd.to_numeric(df[cand], errors="coerce")
            if serie.notna().sum() > 10 and serie.dropna().nunique() >= 2:
                return cand
    return None


def taxa_excelencia(alvo_ou_media, corte=CORTE_PADRAO):
    """Fracao (%) de alunos com nota >= corte. Aceita Series ou array-like."""
    serie = pd.to_numeric(pd.Series(alvo_ou_media), errors="coerce").dropna()
    if serie.empty:
        return 0.0
    return float((serie >= corte).mean() * 100)


def _colunas_feature(df, colunas_disc=None):
    if colunas_disc is not None:
        return [c for c in colunas_disc if c in df.columns]
    return [c for c in df.columns if str(c).upper().startswith(PREFIXOS_FEATURE)]


def treinar_simulador(df, colunas_disc=None, alvo=None):
    """Treina XGBoost supervisionado somente se houver alvo EXTERNO real.

    Retorna (modelo | None, info). Quando nao ha alvo externo valido, info
    indica modo 'aritmetico' e modelo=None (nada e inventado).
    """
    if df is None or df.empty:
        return None, {"modo": "indisponivel", "motivo": "sem dados"}
    cols = _colunas_feature(df, colunas_disc)
    if not cols:
        return None, {"modo": "indisponivel", "motivo": "sem features"}

    alvo = alvo or detectar_alvo_externo(df)
    if alvo is None:
        return None, {"modo": "aritmetico", "motivo": "sem alvo externo",
                      "alvo": None, "colunas": cols}

    base = df[cols].apply(pd.to_numeric, errors="coerce")
    y_raw = pd.to_numeric(df[alvo], errors="coerce")
    corte = CORTE_PADRAO
    y = (y_raw >= corte).astype(float)
    if y.dropna().nunique() < 2:
        corte = float(y_raw.dropna().median())
        y = (y_raw >= corte).astype(float)
    dados = base.copy()
    dados["_alvo"] = y
    dados = dados.dropna(subset=cols + ["_alvo"])
    if len(dados) < 30 or dados["_alvo"].nunique() < 2:
        return None, {"modo": "aritmetico", "motivo": "amostra/alvo insuficiente",
                      "alvo": alvo, "colunas": cols}

    try:
        from xgboost import XGBClassifier
        modelo = XGBClassifier(
            n_estimators=120, max_depth=3, learning_rate=0.1,
            objective="binary:logistic", random_state=SEED,
            use_label_encoder=False, eval_metric="logloss")
        modelo.fit(dados[cols], dados["_alvo"].astype(int))
    except Exception as exc:  # pragma: no cover - depende de ambiente
        return None, {"modo": "aritmetico", "motivo": f"xgboost indisponivel: {exc}",
                      "alvo": alvo, "colunas": cols}

    return modelo, {"modo": "supervisionado", "alvo": alvo, "corte": corte,
                    "colunas": cols, "n_treino": int(len(dados))}


def simular(modelo, df, colunas_disc, alteracoes, alvo=None, corte=CORTE_PADRAO):
    """Recalcula a taxa de excelencia aplicando os deltas de intervencao.

    Retorna dict com taxa_atual, taxa_simulada, diferenca e modo.
    """
    cols = _colunas_feature(df, colunas_disc)
    if not cols or df is None or df.empty:
        return {"taxa_atual": 0.0, "taxa_simulada": 0.0, "diferenca": 0.0,
                "modo": "indisponivel"}

    base = df[cols].apply(pd.to_numeric, errors="coerce")
    sim = base.copy()
    for disc, delta in (alteracoes or {}).items():
        if disc in sim.columns:
            sim[disc] = (sim[disc] + delta).clip(0, 100)

    if modelo is not None:
        atual = float(modelo.predict(base).mean() * 100)
        nova = float(modelo.predict(sim).mean() * 100)
        modo = "supervisionado"
    else:
        atual = taxa_excelencia(base.mean(axis=1), corte)
        nova = taxa_excelencia(sim.mean(axis=1), corte)
        modo = "aritmetico"

    return {"taxa_atual": atual, "taxa_simulada": nova,
            "diferenca": nova - atual, "modo": modo}
