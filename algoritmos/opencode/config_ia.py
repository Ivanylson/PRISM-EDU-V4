"""
Transparencia da IA - configuracao REAL do stack de IA do PRISM-EDU.

Este modulo centraliza, de forma auditavel, o que o projeto efetivamente usa
como IA explicativa (servidor OpenCode local + modelos remotos), para que o
dashboard exiba a configuracao verdadeira em vez de pseudo-codigo ilustrativo.

Nao inventa valores: tudo vem de config.py e de sondagem real do servidor.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config import (  # noqa: E402
    MODELOS_OPENCODE, OPENCODE_SERVER_URL, OPENCODE_USERNAME,
)

# Politica de grounding efetivamente aplicada pelos prompts do projeto.
# Extraida dos templates reais (cliente_opencode.py / app.py), nao inventada.
POLITICA_GROUNDING = [
    "Responder apenas com base nos dados/contexto fornecidos (grounding).",
    "Quando faltar dado, responder 'Dados insuficientes' em vez de estimar.",
    "Nao inventar metodologias, teorias ou valores numericos.",
    "Citar a fonte (arquivo/coluna) quando fizer afirmacao quantitativa.",
    "Tom formal, focado em metricas acionaveis para o coordenador.",
]


def modelos_disponiveis():
    """Retorna a lista (id, rotulo) dos modelos configurados no projeto."""
    return list(MODELOS_OPENCODE.items())


def resumo_config():
    """Resumo auditavel da config de IA (sem segredos)."""
    return {
        "servidor_url": OPENCODE_SERVER_URL,
        "usuario_auth": OPENCODE_USERNAME,
        "n_modelos": len(MODELOS_OPENCODE),
        "modelos": modelos_disponiveis(),
        "politica_grounding": POLITICA_GROUNDING,
    }


def status_servidor(probe=None):
    """Sonda o servidor OpenCode. `probe` injetavel para testes.

    Retorna dict {ativo: bool, url: str, detalhe: str}.
    """
    url = OPENCODE_SERVER_URL
    if probe is not None:
        try:
            return {"ativo": bool(probe(url)), "url": url, "detalhe": "probe externo"}
        except Exception as exc:
            return {"ativo": False, "url": url, "detalhe": f"erro: {exc}"}
    try:
        import requests
        resp = requests.get(f"{url}/global/health", timeout=3)
        return {"ativo": resp.status_code == 200, "url": url,
                "detalhe": f"HTTP {resp.status_code}"}
    except Exception as exc:  # pragma: no cover - depende de rede
        return {"ativo": False, "url": url, "detalhe": f"offline: {exc}"}
