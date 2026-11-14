"""Adaptadores opcionais para a ontologia OWL do PRISM-EDU.

Cada funcao tenta usar uma biblioteca diferente para ler o mesmo arquivo
``prism_edu.owl`` e devolve um dicionario com ``ok`` e metricas. Nenhuma
biblioteca e' obrigatoria para gerar a ontologia (isso e' feito com rdflib);
elas sao a camada de interoperabilidade para pesquisa.

Bibliotecas:
    * rdflib      -> parsing RDF/XML, Turtle, JSON-LD; SPARQL.
    * owlready2   -> acesso orientado a objetos, reasoner (Java opcional).
    * owlapy      -> aprendizado de ontologias / OWL API em Python.
    * oaklib (OAK)-> Ontology Access Kit: adaptadores e operacoes.
    * pyshacl     -> validacao SHACL.

Todas as funcoes sao tolerantes a ausencia da biblioteca: retornam
``{"ok": False, "motivo": "nao instalado"}`` em vez de levantar excecao.
"""
from __future__ import annotations

from pathlib import Path
import importlib
import json
import shutil
import subprocess
from functools import lru_cache

BIBLIOTECAS = {
    "rdflib": {
        "pacote": "rdflib",
        "papel": "Parsing RDF/XML, Turtle, JSON-LD e consultas SPARQL.",
        "obrigatoria": True,
    },
    "owlready2": {
        "pacote": "owlready2",
        "papel": "API orientada a objetos e raciocinio OWL (reasoner via Java).",
        "obrigatoria": False,
    },
    "owlapy": {
        "pacote": "owlapy",
        "papel": "Aprendizado de ontologias e ponte com a OWL API.",
        "obrigatoria": False,
    },
    "oaklib": {
        "pacote": "oaklib",
        "papel": "Ontology Access Kit: adaptadores, busca e operacoes sobre a ontologia.",
        "obrigatoria": False,
    },
    "pyshacl": {
        "pacote": "pyshacl",
        "papel": "Validacao SHACL dos dados.",
        "obrigatoria": False,
    },
}


def _versao(modulo) -> str:
    for attr in ("__version__", "VERSION", "version"):
        valor = getattr(modulo, attr, None)
        if valor:
            return str(valor)
    return "?"


def _java_disponivel() -> bool:
    return shutil.which("java") is not None


def status_stack() -> list:
    """Matriz de disponibilidade das bibliotecas da stack ontologica."""
    linhas = []
    for chave, meta in BIBLIOTECAS.items():
        item = {"nome": chave, "papel": meta["papel"],
                "obrigatoria": meta["obrigatoria"], "instalado": False,
                "versao": None, "observacao": ""}
        try:
            modulo = importlib.import_module(meta["pacote"])
            item["instalado"] = True
            item["versao"] = _versao(modulo)
        except Exception as exc:  # ImportError ou erro de dependencia nativa
            item["observacao"] = f"{type(exc).__name__}: {exc}"
            if chave == "oaklib":
                interpretadores = _candidatos_python_oak()
                if interpretadores:
                    versao = _versao_oak_venv(interpretadores[0])
                    if versao:
                        item["instalado"] = True
                        item["versao"] = versao
                        item["observacao"] = (
                            f"via venv isolado: {interpretadores[0]}")
        linhas.append(item)
    return linhas


# ---------------------------------------------------------------------------
# rdflib
# ---------------------------------------------------------------------------
@lru_cache(maxsize=4)
def _grafo_rdflib(caminho_str, _mtime):
    """Parse unico e cacheado por (caminho, mtime). Evita reparsear 20+ MB."""
    from rdflib import Graph
    grafo = Graph()
    grafo.parse(caminho_str, format="xml")
    return grafo


def carregar_grafo(caminho):
    """Devolve o grafo rdflib, reaproveitando o parse enquanto o arquivo nao muda."""
    alvo = Path(caminho).resolve()
    return _grafo_rdflib(str(alvo), alvo.stat().st_mtime)


def carregar_rdflib(caminho):
    try:
        import rdflib  # noqa: F401
    except ImportError as exc:
        return {"ok": False, "motivo": "nao instalado", "erro": str(exc)}
    try:
        g = carregar_grafo(caminho)
        return {"ok": True, "versao": _versao(importlib.import_module("rdflib")),
                "triplas": len(g), "sujeitos": len(set(g.subjects()))}
    except Exception as exc:
        return {"ok": False, "erro": f"{type(exc).__name__}: {exc}"}


def consultar_sparql(caminho, consulta: str, limite=None, grafo=None):
    """Executa uma consulta SPARQL e devolve (colunas, linhas).

    ``grafo`` permite reutilizar um parse ja feito (recomendado em lotes).
    """
    g = grafo if grafo is not None else carregar_grafo(caminho)
    resultado = g.query(consulta)
    colunas = [str(v) for v in resultado.vars] if resultado.vars else []
    linhas = []
    for i, linha in enumerate(resultado):
        if limite is not None and i >= limite:
            break
        linhas.append([None if v is None else str(v) for v in linha])
    return colunas, linhas


# ---------------------------------------------------------------------------
# owlready2
# ---------------------------------------------------------------------------
def carregar_owlready2(caminho):
    try:
        import owlready2
    except Exception as exc:
        return {"ok": False, "motivo": "nao instalado", "erro": str(exc)}
    try:
        mundo = owlready2.World()
        onto = mundo.get_ontology(str(Path(caminho).resolve())).load()
        classes = list(onto.classes())
        propriedades = list(onto.properties())
        individuos = list(onto.individuals())
        if not individuos:
            # Fallback: algumas versoes do owlready2 nao registram em
            # Ontology.individuals() individuos sem tipo owl:NamedIndividual.
            vistos = set()
            for cls in classes:
                try:
                    vistos.update(cls.instances())
                except Exception:
                    continue
            individuos = list(vistos)
        return {"ok": True, "versao": _versao(owlready2),
                "classes": len(classes), "propriedades": len(propriedades),
                "individuos": len(individuos),
                "java_disponivel": _java_disponivel(),
                "observacao": ("Reasoner exigiria Java (nao executado nesta checagem)."
                               if not _java_disponivel() else
                               "Java disponivel; raciocinio pode ser executado sob demanda.")}
    except Exception as exc:
        return {"ok": False, "erro": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# owlapy
# ---------------------------------------------------------------------------
def carregar_owlapy(caminho):
    try:
        import owlapy
    except Exception as exc:
        return {"ok": False, "motivo": "nao instalado", "erro": str(exc)}
    # No Windows, a OWLAPI resolve o argumento como caminho de arquivo; passar
    # 'file:///C:/...' faz o JPype montar 'C:\...\file:\C:\...'. Por isso o
    # caminho local absoluto vem primeiro e a URI fica como fallback (Linux/macOS).
    local = Path(caminho).resolve()
    candidatos = [str(local), local.as_posix(), local.as_uri()]
    onto = None
    erros = []
    # A API do OWLAPY mudou entre versoes; tentamos os caminhos conhecidos.
    classes_api = (("owlapy.owl_ontology", "SyncOntology"),
                   ("owlapy.owl_ontology", "Ontology"),
                   ("owlapy.ontology", "Ontology"))
    for arg in candidatos:
        for modulo_nome, classe_nome in classes_api:
            try:
                modulo = importlib.import_module(modulo_nome)
                classe = getattr(modulo, classe_nome)
                onto = classe(arg)
                break
            except Exception as exc:
                erros.append(f"{modulo_nome}.{classe_nome}({arg}): "
                             f"{type(exc).__name__}: {str(exc)[:160]}")
        if onto is not None:
            break
    if onto is None:
        return {"ok": False, "erro": " | ".join(erros[-2:]) or "API nao reconhecida"}
    try:
        classes = list(onto.classes_in_signature())
        individuos = list(onto.individuals_in_signature())
        return {"ok": True, "versao": _versao(owlapy),
                "classes": len(classes), "individuos": len(individuos),
                "recurso": str(local)}
    except Exception as exc:
        return {"ok": False, "erro": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# OAK (Ontology Access Kit)
# ---------------------------------------------------------------------------
# O oaklib arrasta ~100 dependencias (linkml, semsql, pronto, sqlalchemy...).
# Instala-lo no ambiente principal pode conflitar com Streamlit/pydantic. A
# estrategia e' aceitar um interpretador isolado (venv) via variavel de
# ambiente PRISM_OAK_PYTHON ou pelos caminhos convencionais abaixo.
_SCRIPT_OAK = r"""
import json, sys
from pathlib import Path
try:
    import oaklib
    from oaklib import get_adapter
except Exception as exc:
    print(json.dumps({"ok": False, "motivo": "nao instalado",
                      "erro": f"{type(exc).__name__}: {exc}"}))
    sys.exit(0)
alvo = Path(sys.argv[1])
casos = []
ttl = alvo.with_suffix(".ttl")
if ttl.exists():
    casos.append((str(ttl), None))
casos.append((str(alvo), "xml"))
erros = []
for desc, fmt in casos:
    try:
        ad = get_adapter(desc, format=fmt)
        try:
            ents = list(ad.all_entity_curies())
        except Exception:
            ents = [e for i, e in enumerate(ad.entities()) if i < 5000]
        print(json.dumps({"ok": True, "versao": getattr(oaklib, "__version__", "?"),
                          "entidades": len(ents), "recurso": desc,
                          "formato": fmt or Path(desc).suffix.lstrip("."),
                          "ontologias": list(ad.ontologies())}))
        sys.exit(0)
    except Exception as exc:
        erros.append(f"{desc}: {type(exc).__name__}: {exc}")
print(json.dumps({"ok": False, "erro": " | ".join(erros[-2:])}))
"""


def _candidatos_python_oak():
    import os
    candidatos = []
    env = os.environ.get("PRISM_OAK_PYTHON")
    if env:
        candidatos.append(Path(env))
    raiz = Path(__file__).resolve().parent.parent.parent
    candidatos.append(raiz / ".venv-oak" / "Scripts" / "python.exe")
    candidatos.append(raiz / ".venv-oak" / "bin" / "python")
    candidatos.append(Path(r"C:\Users\usuario\AppData\Local\Temp\opencode\oak_env\Scripts\python.exe"))
    return [c for c in candidatos if c.exists()]


def _versao_oak_venv(interpretador: Path):
    try:
        saida = subprocess.run(
            [str(interpretador), "-c",
             "import oaklib; print(getattr(oaklib, '__version__', '?'))"],
            capture_output=True, text=True, timeout=120,
        )
        if saida.returncode == 0 and saida.stdout.strip():
            return saida.stdout.strip().splitlines()[-1]
    except Exception:
        pass
    return None


def _oak_ler(alvo):
    """Le a ontologia com oaklib no processo atual (usa .ttl quando existe)."""
    from oaklib import get_adapter
    alvo = Path(alvo)
    casos = []
    ttl = alvo.with_suffix(".ttl")
    if ttl.exists():
        casos.append((str(ttl), None))
    casos.append((str(alvo), "xml"))
    erros = []
    for desc, fmt in casos:
        try:
            ad = get_adapter(desc, format=fmt)
            try:
                curies = list(ad.all_entity_curies())
            except Exception:
                curies = [e for i, e in enumerate(ad.entities()) if i < 5000]
            return {"ok": True, "entidades": len(curies),
                    "ontologias": list(ad.ontologies()), "recurso": desc,
                    "formato": fmt or Path(desc).suffix.lstrip(".")}
        except Exception as exc:
            erros.append(f"{desc}: {type(exc).__name__}: {exc}")
    return {"ok": False, "erro": " | ".join(erros[-2:])}


def carregar_oak(caminho):
    local = str(Path(caminho).resolve())
    try:
        import oaklib  # noqa: F401
    except Exception:
        oaklib = None

    if oaklib is not None:
        resultado = _oak_ler(local)
        if resultado.get("ok"):
            resultado["modo"] = "in-process"
            resultado["versao"] = _versao(importlib.import_module("oaklib"))
        return resultado

    # fallback: interpretador isolado com oaklib instalado
    candidatos = _candidatos_python_oak()
    if not candidatos:
        return {"ok": False, "motivo": "nao instalado",
                "erro": ("oaklib ausente no ambiente principal e nenhum venv "
                         "isolado encontrado (defina PRISM_OAK_PYTHON)")}
    erros = []
    for interpretador in candidatos:
        try:
            saida = subprocess.run(
                [str(interpretador), "-c", _SCRIPT_OAK, local],
                capture_output=True, text=True, timeout=900,
            )
        except Exception as exc:
            erros.append(f"{interpretador}: {type(exc).__name__}: {exc}")
            continue
        linhas = [ln for ln in (saida.stdout or "").splitlines() if ln.strip()]
        for linha in reversed(linhas):
            try:
                resultado = json.loads(linha)
            except json.JSONDecodeError:
                continue
            if resultado.get("ok"):
                resultado["modo"] = f"subprocess:{interpretador}"
                return resultado
            erros.append(str(resultado.get("erro") or resultado.get("motivo")))
            break
        else:
            erros.append(f"{interpretador}: sem saida JSON "
                         f"(rc={saida.returncode}) {saida.stderr[-200:]}")
    return {"ok": False, "erro": " | ".join(erros[-2:])}


# ---------------------------------------------------------------------------
# SHACL
# ---------------------------------------------------------------------------
def validar_shacl(caminho_dados, caminho_shapes):
    try:
        from pyshacl import validate
    except Exception as exc:
        return {"ok": False, "motivo": "nao instalado", "erro": str(exc)}
    try:
        conformes, _, texto = validate(
            str(caminho_dados),
            shacl_graph=str(caminho_shapes),
            inference="rdfs",
            abort_on_first=False,
            allow_infos=True,
            allow_warnings=True,
        )
        return {"ok": True, "conformes": bool(conformes), "relatorio": texto}
    except Exception as exc:
        return {"ok": False, "erro": f"{type(exc).__name__}: {exc}"}


def resumo_stack_texto() -> str:
    linhas = []
    for item in status_stack():
        estado = f"OK {item['versao']}" if item["instalado"] else "AUSENTE"
        marca = "*" if item["obrigatoria"] else " "
        linhas.append(f"  {marca} {item['nome']:<11} {estado:<14} {item['papel']}")
    linhas.append("  (* = obrigatoria para gerar/validar a ontologia)")
    return "\n".join(linhas)
