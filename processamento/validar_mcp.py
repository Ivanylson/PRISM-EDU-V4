"""Valida o servidor MCP do PRISM-EDU (handshake JSON-RPC + tools/list + tools/call).

Uso:
    python processamento/validar_mcp.py
"""
from pathlib import Path
import json
import subprocess
import sys

RAIZ = Path(__file__).resolve().parent.parent
SERVIDOR = RAIZ / "mcp" / "prism_edu_server.py"


def _chamar(requisicoes):
    entrada = "\n".join(json.dumps(r) for r in requisicoes) + "\n"
    proc = subprocess.run([sys.executable, str(SERVIDOR)], input=entrada,
                          capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0 and not proc.stdout:
        raise RuntimeError(proc.stderr.strip() or "servidor MCP falhou")
    return [json.loads(l) for l in proc.stdout.splitlines() if l.strip()]


def main():
    print("Validando servidor MCP do PRISM-EDU...")
    respostas = _chamar([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "listar_cursos_avaliados", "arguments": {}}},
    ])
    por_id = {r.get("id"): r for r in respostas}

    info = por_id.get(1, {}).get("result", {}).get("serverInfo", {})
    assert info.get("name") == "prism-edu", "serverInfo invalido"
    print(f"  OK initialize -> {info}")

    tools = por_id.get(2, {}).get("result", {}).get("tools", [])
    nomes = [t["name"] for t in tools]
    assert len(nomes) >= 5, "poucas tools expostas"
    print(f"  OK tools/list -> {nomes}")

    conteudo = por_id.get(3, {}).get("result", {}).get("content", [{}])
    payload = json.loads(conteudo[0].get("text", "{}"))
    assert payload.get("n_cursos", 0) > 0, "listar_cursos vazio"
    print(f"  OK tools/call -> {payload.get('n_edicoes')} edicoes, "
          f"{payload.get('n_cursos')} cursos")

    print("\nServidor MCP validado com sucesso.")


if __name__ == "__main__":
    main()
