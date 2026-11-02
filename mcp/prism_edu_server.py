"""
Servidor MCP (Model Context Protocol) do PRISM-EDU.

Expoe os artefatos reais do projeto como ferramentas consultaveis por agentes
de IA. Implementacao manual de JSON-RPC 2.0 sobre stdio (sem SDK/dependencia
nova), compativel com a config `mcp` do OpenCode:

    {"command": ["python", "mcp/prism_edu_server.py"], "type": "local"}

Protocolo: initialize -> notifications/initialized -> tools/list -> tools/call.
Reutiliza TODOS os modulos reais (ontologia, drift, RAG, simulador, IA/config).

Uso:
    python mcp/prism_edu_server.py            # stdio (para o OpenCode)
    python mcp/prism_edu_server.py --list     # imprime as tools e sai
    python mcp/prism_edu_server.py --call <tool> '<json-args>'
"""
from pathlib import Path
import json
import sys

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

PROTOCOLO = "2024-11-05"
NOME = "prism-edu"
VERSAO = "1.0.0"


# --------------------------------------------------------------------------
# Tool schemas (JSON Schema) + implementacoes
# --------------------------------------------------------------------------
def _tool_descricoes():
    return [
        {"name": "listar_cursos_avaliados",
         "description": "Lista os cursos (CO_GRUPO) e edicoes ENADE do PRISM-EDU.",
         "inputSchema": {"type": "object", "properties": {}}},
        {"name": "resumo_ontologia",
         "description": "Resumo da ontologia educacional (nos e relacoes por tipo).",
         "inputSchema": {"type": "object", "properties": {}}},
        {"name": "buscar_objetivos_conhecimento",
         "description": "Retorna objetivos de conhecimento de um curso na ontologia.",
         "inputSchema": {"type": "object",
                         "properties": {"curso": {"type": "string"},
                                        "limite": {"type": "integer"}},
                         "required": ["curso"]}},
        {"name": "drift_temporal",
         "description": "Le a serie de drift temporal de um objeto de conhecimento.",
         "inputSchema": {"type": "object",
                         "properties": {"produto": {"type": "string"}}}},
        {"name": "buscar_corpus_rag",
         "description": "Busca trechos relevantes no corpus RAG local (TF-IDF).",
         "inputSchema": {"type": "object",
                         "properties": {"consulta": {"type": "string"},
                                        "top_k": {"type": "integer"}},
                         "required": ["consulta"]}},
        {"name": "simular_cenario",
         "description": "Simula cenario contrafactual de excelencia sobre microdados processados.",
         "inputSchema": {"type": "object",
                         "properties": {"curso": {"type": "string"},
                                        "csv": {"type": "string"},
                                        "esforco": {"type": "number"}},
                         "required": ["curso", "csv"]}},
        {"name": "config_ia",
         "description": "Configuracao de IA/OpenCode e politica de grounding.",
         "inputSchema": {"type": "object", "properties": {}}},
    ]


def _texto(conteudo):
    return {"content": [{"type": "text", "text": conteudo}]}


def _json_conteudo(obj):
    return _texto(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def _tool_listar_cursos_avaliados(_args):
    arquivo = RAIZ / "processamento" / "mapeamento_grupos_enade.json"
    if not arquivo.exists():
        return _texto("Dados insuficientes: mapeamento_grupos_enade.json ausente.")
    mapa = json.loads(arquivo.read_text(encoding="utf-8"))
    cursos = sorted({c for por_grupo in mapa.values() for c in por_grupo.values()})
    return _json_conteudo({"edicoes": sorted(mapa.keys(), reverse=True),
                           "n_edicoes": len(mapa), "n_cursos": len(cursos),
                           "cursos": cursos})


def _tool_resumo_ontologia(_args):
    from algoritmos.ontologia.ontologia_enade import OntologiaEnade
    onto = OntologiaEnade()
    onto.carregar_grupos()
    return _json_conteudo(onto.resumo())


def _tool_buscar_objetivos(_args):
    from algoritmos.ontologia.ontologia_enade import OntologiaEnade
    onto = OntologiaEnade()
    onto.carregar_grupos()
    try:
        onto.carregar_questoes()
    except FileNotFoundError:
        pass
    alvo = _args["curso"].lower()
    limite = int(_args.get("limite", 30))
    ocs = sorted({n.rotulo for n in onto.nos.values()
                  if n.tipo == "ObjetivoConhecimento" and alvo in n.rotulo.lower()})
    if not ocs:
        ocs = sorted({n.rotulo for n in onto.nos.values()
                      if n.tipo == "ObjetivoConhecimento"})
    return _json_conteudo({"curso": _args["curso"], "objetivos": ocs[:limite],
                           "n": len(ocs)})


def _tool_drift_temporal(args):
    from algoritmos.drift.pipeline_drift import _pasta_global
    pasta = _pasta_global()
    arquivo = pasta / "tendencia_long.csv"
    if not arquivo.exists():
        return _texto("Dados insuficientes: rode processamento/analise_drift_temporal.py.")
    import pandas as pd
    df = pd.read_csv(arquivo, sep=";")
    produto = args.get("produto")
    if produto:
        mascara = df.astype(str).apply(lambda c: c.str.contains(produto, case=False, na=False))
        df = df[mascara.any(axis=1)]
    return _json_conteudo({"n": len(df), "linhas": df.head(30).to_dict("records")})


def _tool_buscar_corpus_rag(args):
    from algoritmos.rag.indexador_rag import IndiceRAG, PASTA_RAG
    try:
        indice = IndiceRAG().carregar(PASTA_RAG)
    except FileNotFoundError:
        return _texto("Dados insuficientes: rode processamento/analise_rag.py indexar.")
    res = indice.buscar(args["consulta"], top_k=int(args.get("top_k", 5)))
    if not res:
        return _texto("Dados insuficientes nas fontes fornecidas.")
    return _json_conteudo([{"score": r["score"], "fonte": r["fonte"],
                            "texto": r["texto"][:400]} for r in res])


def _tool_simular_cenario(args):
    from algoritmos.xai.simulador_contrafactual import treinar_simulador, simular
    caminho = args.get("csv")
    if not caminho or not Path(caminho).exists():
        return _texto("Dados insuficientes: forneca o argumento 'csv' com um arquivo "
                      "de microdados processado (ex.: relatorio_final_enade_<ano>.csv).")
    import pandas as pd
    df = pd.read_csv(caminho, sep=None, engine="python")
    try:
        modelo = treinar_simulador(df)
    except Exception as exc:  # noqa: BLE001
        return _texto(f"Dados insuficientes para simular: {exc}")
    colunas = [c for c in df.columns if str(c).startswith("Q")]
    res = simular(modelo, df, colunas,
                  alteracoes={args["curso"]: float(args.get("esforco", 0.2))})
    return _json_conteudo(res)


def _tool_config_ia(_args):
    from algoritmos.opencode.config_ia import resumo_config
    return _json_conteudo(resumo_config())


TOOLS = {
    "listar_cursos_avaliados": _tool_listar_cursos_avaliados,
    "resumo_ontologia": _tool_resumo_ontologia,
    "buscar_objetivos_conhecimento": _tool_buscar_objetivos,
    "drift_temporal": _tool_drift_temporal,
    "buscar_corpus_rag": _tool_buscar_corpus_rag,
    "simular_cenario": _tool_simular_cenario,
    "config_ia": _tool_config_ia,
}


# --------------------------------------------------------------------------
# JSON-RPC 2.0
# --------------------------------------------------------------------------
def _resposta(req_id, resultado):
    return {"jsonrpc": "2.0", "id": req_id, "result": resultado}


def _erro(req_id, codigo, mensagem):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": codigo, "message": mensagem}}


def tratar_requisicao(req):
    """Processa uma requisicao JSON-RPC e retorna a resposta (ou None se notificacao)."""
    metodo = req.get("method")
    req_id = req.get("id")

    if metodo == "initialize":
        return _resposta(req_id, {
            "protocolVersion": PROTOCOLO,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": NOME, "version": VERSAO}})
    if metodo in ("notifications/initialized", "initialized"):
        return None
    if metodo == "ping":
        return _resposta(req_id, {})
    if metodo == "tools/list":
        return _resposta(req_id, {"tools": _tool_descricoes()})
    if metodo == "tools/call":
        params = req.get("params", {})
        nome = params.get("name")
        args = params.get("arguments", {}) or {}
        if nome not in TOOLS:
            return _erro(req_id, -32602, f"Tool desconhecida: {nome}")
        try:
            return _resposta(req_id, TOOLS[nome](args))
        except Exception as exc:  # noqa: BLE001
            return _resposta(req_id, {"content": [{"type": "text",
                            "text": f"Erro ao executar {nome}: {exc}"}],
                            "isError": True})
    if req_id is None:
        return None
    return _erro(req_id, -32601, f"Metodo nao encontrado: {metodo}")


def servir_stdio():
    for linha in sys.stdin:
        linha = linha.strip()
        if not linha:
            continue
        try:
            req = json.loads(linha)
        except json.JSONDecodeError:
            continue
        resp = tratar_requisicao(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--list":
        print(json.dumps({"tools": _tool_descricoes()}, ensure_ascii=False, indent=2))
        return
    if len(sys.argv) >= 3 and sys.argv[1] == "--call":
        args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        resp = tratar_requisicao({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                  "params": {"name": sys.argv[2], "arguments": args}})
        print(json.dumps(resp, ensure_ascii=False, indent=2))
        return
    servir_stdio()


if __name__ == "__main__":
    main()
