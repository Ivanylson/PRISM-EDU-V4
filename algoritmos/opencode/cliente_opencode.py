"""
Cliente OpenCode para integracao com IA explicativa.
Gera explicacoes em linguagem natural dos resultados de analise.
"""
import requests
import base64
import time
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config import OPENCODE_SERVER_URL, OPENCODE_USERNAME, MODELOS_OPENCODE, SEPARADOR, ENCODING


def verificar_servidor():
    try:
        resp = requests.get(f"{OPENCODE_SERVER_URL}/global/health", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


def criar_sessao(senha=""):
    headers = _auth_headers(senha)
    resp = requests.post(f"{OPENCODE_SERVER_URL}/session",
                         json={"message": "Analise de dados ENADE"},
                         headers=headers, timeout=15)
    if resp.status_code == 200:
        return resp.json().get("id")
    return None


def enviar_prompt(prompt, model_id="big-pickle", senha="", timeout=300):
    if not verificar_servidor():
        return {"success": False, "error": "Servidor OpenCode nao esta ativo."}

    session_id = criar_sessao(senha)
    if not session_id:
        return {"success": False, "error": "Falha ao criar sessao."}

    headers = _auth_headers(senha)
    headers["Content-Type"] = "application/json"

    msg_body = {
        "parts": [{"type": "text", "text": prompt}],
        "model": {"providerID": "opencode", "modelID": model_id},
    }

    async_resp = requests.post(
        f"{OPENCODE_SERVER_URL}/session/{session_id}/prompt_async",
        json=msg_body, headers=headers, timeout=30
    )

    if async_resp.status_code != 204:
        return {"success": False, "error": f"HTTP {async_resp.status_code}"}

    start = time.time()
    while time.time() - start < timeout:
        time.sleep(3)
        try:
            msg_resp = requests.get(
                f"{OPENCODE_SERVER_URL}/session/{session_id}/message?limit=5",
                headers=headers, timeout=10
            )
            if msg_resp.status_code == 200:
                messages = msg_resp.json()
                if isinstance(messages, list):
                    for msg in messages:
                        info = msg.get("info", {})
                        if info.get("role") == "assistant":
                            for part in msg.get("parts", []):
                                if part.get("type") == "text":
                                    text = part.get("text", "")
                                    if text and len(text.strip()) > 10:
                                        return {"success": True, "response": text, "model": model_id}
        except Exception:
            pass

    return {"success": False, "error": f"Timeout apos {timeout}s."}


def _auth_headers(senha=""):
    if senha:
        credenciais = f"{OPENCODE_USERNAME}:{senha}"
        encoded = base64.b64encode(credenciais.encode("utf-8")).decode("utf-8")
        return {"Authorization": f"Basic {encoded}"}
    return {}


def gerar_explicacao_csv(caminho_csv, tom="Didatico e acessivel", model_id="big-pickle", senha="", foco=""):
    import pandas as pd
    df = pd.read_csv(caminho_csv, sep=SEPARADOR, nrows=10, on_bad_lines="skip")
    n_linhas = sum(1 for _ in open(caminho_csv, "r", encoding="utf-8-sig")) - 1

    prompt = f"""Analise o seguinte dataset educacional brasileiro (ENADE) e gere uma explicacao {tom.lower()}.

INFORMACOES DO ARQUIVO:
- Linhas: ~{n_linhas}
- Colunas: {list(df.columns)}
- Amostra (5 primeiras linhas):
{df.head().to_string()}

FOCO: {foco if foco else 'Analise geral do dataset'}

Gere uma explicacao que:
1. Descreva o que sao os dados
2. Destaque padroes importantes
3. Identifique possiveis problemas ou anomalias
4. Sugira acoes concretas
5. Use linguagem acessivel para nao-especialistas"""

    return enviar_prompt(prompt, model_id=model_id, senha=senha)


def executar_explicacao(caminho_csv=None):
    print("=" * 60)
    print("  PRISM-EDU: OpenCode + IA Explicativa")
    print("=" * 60)

    if not verificar_servidor():
        print("  Servidor OpenCode offline. Inicie com: opencode serve --port 4096")
        return

    print("  Servidor OpenCode online!")

    if caminho_csv is None:
        from config import PASTA_CONSOLIDADO
        caminho_csv = PASTA_CONSOLIDADO

    if not caminho_csv.exists():
        print(f"  CSV nao encontrado: {caminho_csv}")
        return

    print(f"  Gerando explicacao para: {caminho_csv.name}")
    resultado = gerar_explicacao_csv(caminho_csv)

    if resultado["success"]:
        print(f"\n  RESPOSTA ({resultado['model']}):")
        print(f"  {resultado['response'][:500]}...")
    else:
        print(f"  ERRO: {resultado.get('error', 'Desconhecido')}")


if __name__ == "__main__":
    csv = sys.argv[1] if len(sys.argv) > 1 else None
    executar_explicacao(csv)
