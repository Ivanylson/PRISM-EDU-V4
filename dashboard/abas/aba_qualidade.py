"""Aba "Qualidade, Proveniencia e Metodos" -- PRISM-EDU.

Reune, em um unico lugar auditavel:

  1. Cobertura e qualidade dos microdados por edicao
     (artefatos de ``processamento/auditoria_qualidade.py``);
  2. Dicionario de dados legivel por maquina (``catalogo_dados.json``);
  3. Gates de integridade e pendencias de validacao especialista;
  4. Manifesto do run (ambiente, parametros, avisos, inventario de motores);
  5. Teoria de Resposta ao Item (IRT) real -- 1PL/Rasch e 2PL;
  6. Matriz de metodos e limitacoes (comparacoes permitidas e proibidas).

Nada aqui inventa numeros: quando um artefato nao existe, a aba informa como
gerar e nao exibe tabela simulada.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config import ENCODING, PASTA_DADOS_PROCESSADOS, PASTA_MODELOS, SEPARADOR

PASTA_QUALIDADE = PASTA_MODELOS / "qualidade"
PASTA_IRT = PASTA_MODELOS / "irt"


# ---------------------------------------------------------------------------
# Carregadores com cache (invalidam quando o arquivo muda de tamanho/mtime)
# ---------------------------------------------------------------------------
def _assinatura(caminho: Path):
    try:
        st_ = caminho.stat()
        return (str(caminho), int(st_.st_mtime), int(st_.st_size))
    except OSError:
        return (str(caminho), 0, 0)


@st.cache_data(show_spinner=False)
def _ler_csv(assinatura, sep=SEPARADOR, decimal=","):
    caminho = Path(assinatura[0])
    if not caminho.exists():
        return None
    try:
        return pd.read_csv(caminho, sep=sep, decimal=decimal, encoding=ENCODING,
                           low_memory=False)
    except Exception:
        return None


@st.cache_data(show_spinner=False)
def _ler_json(assinatura):
    caminho = Path(assinatura[0])
    if not caminho.exists():
        return None
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except Exception:
        return None


def _csv(caminho: Path):
    return _ler_csv(_assinatura(caminho))


def _json(caminho: Path):
    return _ler_json(_assinatura(caminho))


# ---------------------------------------------------------------------------
# Localizacao de edicoes e cursos
# ---------------------------------------------------------------------------
def _edicoes_irt():
    if not PASTA_IRT.exists():
        return []
    # Apenas edicoes com resumo gerado: pastas vazias podem existir como efeito
    # colateral de chamadas antigas de pasta_saida_edicao.
    return sorted(p.parent.name for p in PASTA_IRT.glob("*/irt_resumo_geral.csv"))


def _resolver_pasta_irt(edicao):
    if edicao:
        p = PASTA_IRT / edicao
        if (p / "irt_resumo_geral.csv").exists():
            return p
    edicoes = _edicoes_irt()
    return PASTA_IRT / edicoes[-1] if edicoes else None


def _slug(texto):
    from config import formatar_nome_curso
    return formatar_nome_curso(str(texto or ""))


def _localizar_arquivo(pasta: Path, prefixo: str, chave: str):
    """Localiza ``<prefixo>_<chave>.csv`` tolerando pequenas variacoes de slug."""
    if pasta is None:
        return None
    exato = pasta / f"{prefixo}_{chave}.csv"
    if exato.exists():
        return exato
    if not pasta.exists():
        return None
    alvo = _slug(chave)
    candidatos = list(pasta.glob(f"{prefixo}_*.csv"))
    for c in candidatos:
        if c.stem.replace(f"{prefixo}_", "") == alvo:
            return c
    # fallback por conteudo do nome (sem acento/underscore)
    compacto = alvo.replace("_", "")
    for c in candidatos:
        if c.stem.replace(f"{prefixo}_", "").replace("_", "") == compacto:
            return c
    return None


# ---------------------------------------------------------------------------
# Sub-aba 1: cobertura e qualidade
# ---------------------------------------------------------------------------
def _aba_cobertura():
    st.markdown(
        "Retrato auditavel dos microdados: quantas edicoes existem, quantos itens "
        "tem dados utilizaveis, duplicidade de chave, nulos e faixa das notas. "
        "As metricas usam uma **amostra inicial** de linhas (nao a base inteira) e "
        "estao declaradas nos avisos do artefato."
    )
    caminho = PASTA_QUALIDADE / "qualidade_por_edicao.csv"
    df = _csv(caminho)
    if df is None or df.empty:
        st.info("Artefato ainda nao gerado. Rode:\n\n"
                "```bash\npython processamento/auditoria_qualidade.py\n```")
        return

    for col in ("n_linhas", "n_colunas", "n_itens_q", "n_itens_com_dados",
                "n_cursos", "n_ies", "bytes", "pct_nulos_ntger_amostra",
                "duplicatas_aluno_amostra"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Edicoes auditadas", len(df))
    c2.metric("Com status OK", int((df["status"] == "ok").sum()))
    c3.metric("Com atencao", int((df["status"] == "atencao").sum()))
    c4.metric("Com erro", int((df["status"] == "erro").sum()))

    st.subheader("Cobertura por edicao")
    base = df.copy()
    if "n_linhas" in base.columns:
        base = base.sort_values("n_linhas", ascending=False)
    fig = px.bar(
        base, x="edicao", y="n_linhas", color="status",
        color_discrete_map={"ok": "#2E7D32", "atencao": "#EF6C00", "erro": "#C62828"},
        title="Linhas por edicao (contagem fisica do arquivo)",
    )
    fig.update_layout(xaxis_tickangle=-45, height=380)
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Itens com dados utilizaveis")
    if {"edicao", "n_itens_q", "n_itens_com_dados"}.issubset(base.columns):
        comp = base[["edicao", "n_itens_q", "n_itens_com_dados"]].melt(
            id_vars="edicao", var_name="Medida", value_name="Itens")
        comp["Medida"] = comp["Medida"].map({
            "n_itens_q": "Colunas Q* no arquivo",
            "n_itens_com_dados": "Itens com >=50% de 0/1",
        })
        fig2 = px.bar(comp, x="edicao", y="Itens", color="Medida", barmode="group",
                      title="Itens declarados x itens realmente utilizaveis")
        fig2.update_layout(xaxis_tickangle=-45, height=360)
        st.plotly_chart(fig2, use_container_width=True)

    st.subheader("Tabela de qualidade")
    cols_pref = [c for c in [
        "edicao", "arquivo", "n_linhas", "n_colunas", "n_itens_q",
        "n_itens_com_dados", "n_cursos", "n_ies", "duplicatas_aluno_amostra",
        "pct_nulos_ntger_amostra", "ntger_min", "ntger_max", "status", "alertas",
    ] if c in df.columns]
    st.dataframe(df[cols_pref], use_container_width=True, hide_index=True)

    if "alertas" in df.columns:
        alertas = df[df["alertas"].astype(str).str.len() > 2]
        if not alertas.empty:
            st.subheader("Alertas registrados")
            for r in alertas.itertuples():
                st.warning(f"**{r.edicao}**: {r.alertas}")


# ---------------------------------------------------------------------------
# Sub-aba 2: dicionario de dados
# ---------------------------------------------------------------------------
def _aba_dicionario():
    st.markdown(
        "Dicionario minimo gerado a partir dos **cabecalhos reais** e das "
        "convencoes do pipeline. Serve para responder: qual o tipo, o dominio e a "
        "semantica de cada coluna, e em quais edicoes ela e garantida."
    )
    caminho = PASTA_QUALIDADE / "catalogo_dados.json"
    catalogo = _json(caminho)
    if not catalogo:
        st.info("Artefato ainda nao gerado. Rode:\n\n"
                "```bash\npython processamento/auditoria_qualidade.py\n```")
        return

    convencoes = catalogo.get("convencoes", {})
    if convencoes:
        st.subheader("Convencoes do projeto")
        st.dataframe(
            pd.DataFrame([{"Convencao": k, "Definicao": v} for k, v in convencoes.items()]),
            use_container_width=True, hide_index=True)

    edicoes = catalogo.get("edicoes", {})
    if not edicoes:
        st.warning("Catalogo sem edicoes registradas.")
        return
    edicao = st.selectbox("Edicao:", sorted(edicoes), key="sb_dicionario_edicao")
    info = edicoes[edicao]
    st.caption(f"Arquivo: `{info.get('arquivo')}` | {info.get('n_colunas')} colunas")

    df_cols = pd.DataFrame([
        {"Coluna": c, **v} for c, v in (info.get("colunas") or {}).items()
    ])
    if df_cols.empty:
        st.warning("Catalogo sem colunas para esta edicao.")
        return
    df_cols = df_cols.rename(columns={
        "tipo_observado": "Tipo observado",
        "nulo_amostra_pct": "Nulos na amostra (%)",
        "exemplo": "Exemplo",
    })
    busca = st.text_input("Filtrar coluna (ex.: NT_, Q1, CO_IES):", key="txt_dic_busca")
    if busca.strip():
        df_cols = df_cols[df_cols["Coluna"].str.contains(busca.strip(), case=False, na=False)]
    st.dataframe(df_cols, use_container_width=True, hide_index=True, height=460)


# ---------------------------------------------------------------------------
# Sub-aba 3: gates e pendencias
# ---------------------------------------------------------------------------
def _aba_gates():
    st.markdown(
        "Gates de integridade com status explicito. **Falha** indica inconsistencia "
        "que impede leitura; **atencao** indica situacao conhecida que precisa de "
        "decisao (ex.: validacao especialista pendente)."
    )
    gates = _json(PASTA_QUALIDADE / "gates.json")
    if not gates:
        st.info("Artefato ainda nao gerado. Rode:\n\n"
                "```bash\npython processamento/auditoria_qualidade.py\n```")
    else:
        df_g = pd.DataFrame(gates)
        mapa = {"ok": "OK", "atencao": "ATENCAO", "falha": "FALHA"}
        df_g["status"] = df_g["status"].map(lambda s: mapa.get(s, s))
        st.dataframe(df_g, use_container_width=True, hide_index=True)
        resumo = df_g["status"].value_counts().to_dict()
        c1, c2, c3 = st.columns(3)
        c1.metric("OK", resumo.get("OK", 0))
        c2.metric("Atencao", resumo.get("ATENCAO", 0))
        c3.metric("Falha", resumo.get("FALHA", 0))
        st.caption("Fonte: `modelos/qualidade/gates.json`. "
                   "Regra: falha bloqueia leitura; atencao exige decisao documentada.")

    st.subheader("Validacao especialista da matriz-Q")
    caminho = PASTA_DADOS_PROCESSADOS / "00_resumo_geral.csv"
    df = _csv(caminho)
    if df is None or df.empty:
        st.info(f"`{caminho.name}` nao encontrado.")
        return
    status_cols = [c for c in df.columns if "status" in c.lower() or "valid" in c.lower()]
    st.dataframe(df.head(40), use_container_width=True, hide_index=True, height=320)
    if status_cols:
        st.caption("Colunas de status: " + ", ".join(status_cols))
        for c in status_cols[:2]:
            vc = df[c].astype(str).value_counts().rename_axis(c).reset_index(name="Cursos")
            st.dataframe(vc, use_container_width=True, hide_index=True)
    st.info(
        "A validacao de conteudo da matriz-Q e humana por definicao: o dashboard "
        "apenas **rastreia** o status. O detalhamento dos itens criticos esta em "
        "`dados/processados/00_ORIENTACOES_VALIDACAO.md`."
    )


# ---------------------------------------------------------------------------
# Sub-aba 4: manifesto do run
# ---------------------------------------------------------------------------
def _aba_manifesto():
    st.markdown(
        "Manifesto do run: o que foi executado, com quais parametros, em qual "
        "ambiente e quais artefatos existem. E a generalizacao, para todo o "
        "projeto, da tabela de proveniencia que a aba de Ontologia ja exibia."
    )
    caminho = PASTA_QUALIDADE / "qualidade_dados.json"
    manifesto = _json(caminho)
    if not manifesto:
        st.info("Artefato ainda nao gerado. Rode:\n\n"
                "```bash\npython processamento/auditoria_qualidade.py\n```")
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Versao", manifesto.get("versao", "-"))
    c2.metric("Edicoes", manifesto.get("n_edicoes", "-"))
    c3.metric("Duracao (s)", manifesto.get("duracao_seg", "-"))
    st.caption(f"Gerado em: `{manifesto.get('gerado_em')}`")

    st.subheader("Ambiente e parametros")
    ambiente = manifesto.get("ambiente", {})
    parametros = manifesto.get("parametros", {})
    st.dataframe(
        pd.DataFrame([
            {"Chave": k, "Valor": str(v)} for k, v in {**ambiente, **parametros}.items()
        ]),
        use_container_width=True, hide_index=True)

    st.subheader("Inventario de motores")
    motores = manifesto.get("motores", {})
    if motores:
        linhas = []
        for motor, info in motores.items():
            edicoes = info.get("edicoes", {}) if isinstance(info, dict) else {}
            linhas.append({
                "Motor": motor,
                "Existe": "sim" if info.get("existe") else "nao",
                "Arquivos na raiz": info.get("arquivos_raiz", 0),
                "Edicoes com artefatos": len(edicoes),
                "Bytes": info.get("bytes_raiz", 0),
            })
        st.dataframe(pd.DataFrame(linhas), use_container_width=True, hide_index=True)
        detalhe = st.selectbox("Detalhar motor:", sorted(motores), key="sb_motor_manifesto")
        edicoes = motores[detalhe].get("edicoes", {})
        if edicoes:
            st.dataframe(
                pd.DataFrame([
                    {"Edicao": k, **v} for k, v in edicoes.items()
                ]).sort_values("Edicao"),
                use_container_width=True, hide_index=True)

    st.subheader("Avisos declarados")
    for aviso in manifesto.get("avisos", []):
        st.info(aviso)

    st.download_button(
        "Baixar manifesto completo (JSON)",
        json.dumps(manifesto, ensure_ascii=False, indent=2),
        file_name="prism_edu_manifesto_qualidade.json",
        mime="application/json",
    )


# ---------------------------------------------------------------------------
# Sub-aba 5: IRT real
# ---------------------------------------------------------------------------
def _aba_irt(edicao, chave_curso):
    st.markdown(
        "**Teoria de Resposta ao Item (IRT)** ajustada por maxima verossimilhanca "
        "marginal (MML) com quadratura de Gauss-Hermite, proficiencia `theta ~ N(0,1)`. "
        "Modelos dicotomicos **1PL/Rasch** (`a=1`) e **2PL** (`a` e `b`), escolhidos "
        "por **BIC**. Diagnostico: infit/outfit MNSQ, confiabilidade marginal, "
        "correlacao residual (independencia local), TIF e DIF por sexo (Mantel-Haenszel)."
    )
    pasta = _resolver_pasta_irt(edicao)
    if pasta is None or not pasta.exists():
        st.info("IRT ainda nao gerado. Rode:\n\n"
                "```bash\npython algoritmos/irt/pipeline_irt.py --edicao enade_2023\n"
                "python executar_por_edicao.py --edicoes enade_2023 --motores irt\n```")
        return

    resumo = _csv(pasta / "irt_resumo_geral.csv")
    if resumo is None or resumo.empty:
        st.info(f"Pasta `{pasta.name}` sem `irt_resumo_geral.csv`.")
        return

    for c in ("n_alunos", "n_itens", "confiabilidade_marginal", "bic",
              "corr_theta_ntger", "outfit_medio", "alpha_cronbach", "omega_mcdonald"):
        if c in resumo.columns:
            resumo[c] = pd.to_numeric(resumo[c], errors="coerce")

    cursos = sorted(resumo["curso"].dropna().unique())
    indice = 0
    if chave_curso:
        alvo = _slug(chave_curso)
        for i, c in enumerate(cursos):
            if _slug(c) == alvo:
                indice = i
                break
    curso = st.selectbox("Curso:", cursos, index=indice, key="sb_irt_curso")
    linha = resumo[resumo["curso"] == curso].iloc[0]

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Modelo", str(linha.get("modelo_escolhido", "-")))
    c2.metric("Alunos (ajuste)", f"{int(linha.get('n_alunos', 0)):,}")
    c3.metric("Itens", int(linha.get("n_itens", 0)))
    conf = linha.get("confiabilidade_marginal")
    c4.metric("Confiabilidade", f"{conf:.3f}" if pd.notna(conf) else "-")
    r = linha.get("corr_theta_ntger")
    c5.metric("r(theta, NT_GER)", f"{r:.3f}" if pd.notna(r) else "-")

    st.caption(
        f"Edicao: `{pasta.name}` | criterio: {linha.get('criterio_escolha', 'BIC')} | "
        f"BIC 1PL={linha.get('bic_1pl', '-')} / 2PL={linha.get('bic_2pl', '-')} | "
        f"alpha={linha.get('alpha_cronbach', '-')} omega={linha.get('omega_mcdonald', '-')}"
    )

    slug = linha.get("slug") or _slug(curso)
    itens = _csv(_localizar_arquivo(pasta, "irt_itens", slug) or Path("__nao_existe__"))
    if itens is not None and not itens.empty:
        for c in ("a_discriminacao", "b_dificuldade", "prop_acerto",
                  "infit_mnsq", "outfit_mnsq"):
            if c in itens.columns:
                itens[c] = pd.to_numeric(itens[c], errors="coerce")
        st.subheader("Mapa de itens (dificuldade x discriminacao)")
        fig = px.scatter(
            itens, x="b_dificuldade", y="a_discriminacao",
            color="ajuste_outfit" if "ajuste_outfit" in itens.columns else None,
            hover_name="item" if "item" in itens.columns else None,
            hover_data=[c for c in ["prop_acerto", "infit_mnsq", "outfit_mnsq"]
                        if c in itens.columns],
            title=f"Itens de {curso} -- cada ponto e uma questao objetiva",
        )
        fig.add_vline(x=0, line_dash="dot", opacity=0.4)
        fig.add_hline(y=1, line_dash="dot", opacity=0.4)
        fig.update_layout(height=420)
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            "Leitura: `b` alto = item dificil; `a` alto = item que separa melhor "
            "alunos com proficiencias proximas. Outfit fora de [0,5; 1,5] sinaliza "
            "item com ajuste ruim ao modelo."
        )
        st.dataframe(itens, use_container_width=True, hide_index=True, height=300)
    else:
        st.warning("Arquivo de itens nao encontrado para este curso.")

    tif = _csv(_localizar_arquivo(pasta, "irt_tif", slug) or Path("__nao_existe__"))
    if tif is not None and not tif.empty:
        for c in ("theta", "informacao", "erro_padrao"):
            tif[c] = pd.to_numeric(tif[c], errors="coerce")
        st.subheader("Funcao de informacao do teste (TIF)")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=tif["theta"], y=tif["informacao"],
                                 mode="lines", name="Informacao"))
        fig.add_trace(go.Scatter(x=tif["theta"], y=tif["erro_padrao"],
                                 mode="lines", name="Erro padrao",
                                 yaxis="y2", line=dict(dash="dot")))
        fig.update_layout(
            height=380,
            xaxis_title="Proficiencia (theta)",
            yaxis=dict(title="Informacao"),
            yaxis2=dict(title="Erro padrao", overlaying="y", side="right"),
            legend=dict(orientation="h"),
        )
        st.plotly_chart(fig, use_container_width=True)

    hab = _csv(_localizar_arquivo(pasta, "irt_abilidades", slug) or Path("__nao_existe__"))
    if hab is not None and not hab.empty:
        for c in ("theta_eap", "theta_se", "NT_GER"):
            if c in hab.columns:
                hab[c] = pd.to_numeric(hab[c], errors="coerce")
        st.subheader("Distribuicao de proficiencia")
        fig = px.histogram(hab, x="theta_eap", nbins=40,
                           title=f"Theta EAP por aluno -- {curso}")
        fig.update_layout(height=340, xaxis_title="theta (EAP)", yaxis_title="Alunos")
        st.plotly_chart(fig, use_container_width=True)

        if "NT_GER" in hab.columns and hab["NT_GER"].notna().sum() >= 20:
            amostra = hab.dropna(subset=["theta_eap", "NT_GER"])
            if len(amostra) > 4000:
                amostra = amostra.sample(4000, random_state=42)
            fig = px.scatter(
                amostra, x="theta_eap", y="NT_GER",
                color="TP_SEXO" if "TP_SEXO" in amostra.columns else None,
                opacity=0.45, title="Validade convergente: theta x nota geral (NT_GER)",
            )
            fig.update_layout(height=400)
            st.plotly_chart(fig, use_container_width=True)
            st.caption(
                f"Correlacao de Pearson observada no ajuste: r = {linha.get('corr_theta_ntger')}. "
                "O item nao entra no modelo; a nota e usada apenas como validacao externa."
            )

    dif = _csv(_localizar_arquivo(pasta, "irt_dif", slug) or Path("__nao_existe__"))
    if dif is not None and not dif.empty:
        st.subheader("DIF por sexo (Mantel-Haenszel + FDR)")
        st.dataframe(dif, use_container_width=True, hide_index=True, height=300)
        st.caption("Classificacao ETS do delta_MH: A desprezivel, B leve-moderado, "
                   "C moderado-grande. `p_fdr` ja corrigido por Benjamini-Hochberg.")

    with st.expander("Parametros completos do ajuste deste curso"):
        st.dataframe(
            pd.DataFrame([{"Chave": k, "Valor": str(v)} for k, v in linha.items()]),
            use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Sub-aba 6: metodos e limitacoes
# ---------------------------------------------------------------------------
def _aba_metodos():
    st.markdown(
        "Matriz de **comparacoes permitidas e proibidas**. Ela existe para evitar "
        "conclusoes invalidas a partir de colunas homonimas que nao representam o "
        "mesmo construto entre edicoes."
    )
    dados = [
        ("Comparar notas (NT_*) entre edicoes do mesmo exame",
         "PERMITIDO", "Notas sao metricas calibradas por edicao."),
        ("Comparar `Q*` cru entre edicoes",
         "PROIBIDO", "`Q1` nao e o mesmo item em anos diferentes; drift semantico."),
        ("Comparar proficiencia por OC entre edicoes",
         "PERMITIDO COM CAUTELA", "Exige ancora de itens/OC comum e mesma prova."),
        ("Cruzar LCA (perfil latente) com DINA (atributos)",
         "PERMITIDO", "E descritivo; a concordancia e reportada, nao inferida."),
        ("Tratar LCA/DINA como diagnostico individual",
         "PROIBIDO", "Sao modelos populacionais; o uso individual e descritivo."),
        ("Comparar ENADE com Licenciaturas/ENAMED",
         "PROIBIDO SEM RESSALVA", "Desenhos, populacoes e matrizes distintos."),
        ("Inferir causalidade de intervencao pedagogica",
         "PROIBIDO", "Nao ha desenho experimental ou quase-experimental."),
        ("Usar SHAP como prova de causalidade",
         "PROIBIDO", "SHAP explica o modelo, nao o mundo."),
        ("Comparar theta IRT entre edicoes sem ancora",
         "PROIBIDO", "Escala padronizada por edicao; exige itens-ancora."),
        ("Reportar metrica sem artefato de origem",
         "PROIBIDO", "Toda metrica do painel aponta para um arquivo gerado."),
    ]
    df = pd.DataFrame(dados, columns=["Operacao", "Status", "Justificativa"])

    def _cor(s):
        if s == "PERMITIDO":
            return "background-color: #E8F5E9"
        if s == "PROIBIDO":
            return "background-color: #FFEBEE"
        return "background-color: #FFF8E1"

    st.dataframe(df.style.map(_cor, subset=["Status"]),
                 use_container_width=True, hide_index=True)

    st.subheader("Correcoes metodologicas aplicadas nesta versao")
    st.markdown(
        """
        - **Correcao de testes multiplos (BH e Holm):** as rotinas aplicavam um
          minimo corrente e colapsavam todos os p-valores ajustados no menor valor.
          Agora BH percorre do maior p para o menor (minimo corrente) e Holm do
          menor para o maior (maximo corrente), como definido na literatura.
        - **Qui-quadrado de Mantel-Haenszel:** passou a usar
          `(sum a_s - E_s)^2 / sum Var(a_s)` em vez de dividir pelo numero de estratos.
        - **E2 (valor agregado):** os residuos eram atribuidos a alunos errados
          porque o indice era resetado antes do `dropna`. O filtro agora preserva a
          indexacao original.
        - **IRT:** a secao que exibia `np.random` foi substituida por um motor real
          (1PL/2PL por MML) e por graficos lidos dos artefatos em `modelos/irt/`.
        """
    )
    st.info(
        "Relatorio completo das ampliacoes e correcoes: "
        "`documentacao/relatorio_ampliacoes_15112026.md`."
    )


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------
def render_irt(edicao="", chave_curso=None):
    """API publica para reutilizar a secao IRT fora desta aba."""
    _aba_irt(edicao, chave_curso)


def render(ctx=None):
    ctx = ctx or {}
    edicao = (ctx.get("edicao") or "").strip()
    chave_curso = ctx.get("chave_curso")

    st.header("Qualidade, Proveniencia e Metodos")
    st.markdown(
        "Camada de **governanca do dado e do metodo**: o que existe, com que "
        "qualidade, de onde veio, quais gates passaram e quais comparacoes sao "
        "legitimas. Todas as tabelas desta aba sao lidas de artefatos gerados; "
        "nenhum valor e digitado a mao."
    )

    t1, t2, t3, t4, t5, t6 = st.tabs([
        "Cobertura e qualidade",
        "Dicionario de dados",
        "Gates e pendencias",
        "Manifesto do run",
        "IRT (metodo)",
        "Metodos e limitacoes",
    ])
    with t1:
        _aba_cobertura()
    with t2:
        _aba_dicionario()
    with t3:
        _aba_gates()
    with t4:
        _aba_manifesto()
    with t5:
        _aba_irt(edicao, chave_curso)
    with t6:
        _aba_metodos()
