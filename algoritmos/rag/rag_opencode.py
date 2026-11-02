"""
RAG + OpenCode: responde perguntas ancoradas (grounded) nos artefatos reais.

Regra de grounding: o modelo so pode responder com base nos chunks recuperados
e DEVE citar a fonte [fonte]. Fora do contexto, responde "Dados insuficientes".
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from algoritmos.opencode.config_ia import POLITICA_GROUNDING  # noqa: E402
from algoritmos.rag.indexador_rag import IndiceRAG, PASTA_RAG  # noqa: E402

INSTRUCAO_GROUNDING = (
    "Voce e um assistente do PRISM-EDU. Responda EXCLUSIVAMENTE com base nas "
    "FONTES fornecidas. Cite a fonte como [nome_do_arquivo] apos cada afirmacao. "
    "Se a resposta nao estiver nas fontes, responda exatamente: "
    "'Dados insuficientes nas fontes fornecidas.' Nao invente numeros."
)


def montar_contexto(resultados):
    """Formata os chunks recuperados em bloco de contexto citavel."""
    blocos = []
    for r in resultados:
        blocos.append(f"[{r['fonte']}] {r['texto']}")
    return "\n\n".join(blocos)


def construir_prompt_rag(pergunta, resultados):
    contexto = montar_contexto(resultados)
    if not contexto:
        contexto = "(nenhuma fonte relevante recuperada)"
    return (
        f"{INSTRUCAO_GROUNDING}\n\n"
        f"=== FONTES ===\n{contexto}\n\n"
        f"=== PERGUNTA ===\n{pergunta}\n\n"
        f"=== RESPOSTA (com citacoes [fonte]) ==="
    )


def responder_com_rag(pergunta, indice=None, top_k=5, limiar=0.05,
                      enviar_prompt=None, model_id="big-pickle"):
    """Recupera contexto e responde. `enviar_prompt` injetavel para testes.

    Retorna dict {pergunta, resposta, fontes, usou_rag, sucesso}.
    """
    if indice is None:
        indice = IndiceRAG()
        try:
            indice.carregar(PASTA_RAG)
        except FileNotFoundError:
            return {"pergunta": pergunta, "resposta": "Dados insuficientes nas fontes fornecidas.",
                    "fontes": [], "usou_rag": False, "sucesso": False,
                    "motivo": "indice RAG nao encontrado; rode analise_rag.py indexar"}

    resultados = indice.buscar(pergunta, top_k=top_k, limiar=limiar)
    fontes = sorted({r["fonte"] for r in resultados})
    if not resultados:
        return {"pergunta": pergunta, "resposta": "Dados insuficientes nas fontes fornecidas.",
                "fontes": [], "usou_rag": True, "sucesso": True, "motivo": "sem fonte acima do limiar"}

    prompt = construir_prompt_rag(pergunta, resultados)
    if enviar_prompt is None:
        from dashboard.componentes.opencode import enviar_prompt_opencode
        enviar_prompt = enviar_prompt_opencode

    try:
        bruto = enviar_prompt(prompt, model_id=model_id)
        if isinstance(bruto, dict):
            resposta = bruto.get("response") or bruto.get("resposta") or str(bruto)
            sucesso = bruto.get("success", True)
        else:
            resposta = str(bruto)
            sucesso = True
    except Exception as exc:  # pragma: no cover - depende de rede
        return {"pergunta": pergunta, "resposta": f"Erro ao consultar o modelo: {exc}",
                "fontes": fontes, "usou_rag": True, "sucesso": False}

    return {"pergunta": pergunta, "resposta": resposta, "fontes": fontes,
            "usou_rag": True, "sucesso": sucesso}
