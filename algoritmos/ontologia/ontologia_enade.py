"""
Ontologia educacional do PRISM-EDU (ENADE).

Modela, a partir de DADOS REAIS do projeto, o grafo de conhecimento:
    Curso --pertence_a--> Area (grupo ENADE)
    Questao --avalia--> ObjetivoConhecimento (OC)
    OC --parte_de--> Competencia
    Curso --avaliado_em--> Edicao (ano)
    OC --coocorre_com--> OC  (peso = coocorrencia real na mesma questao/matriz)

Nao usa dependencias externas (nem owlready2/rdflib): o grafo e' um dict de
nos/arestas e a exportacao para JSON-LD e Turtle e' feita a mao, de forma
auditavel. Fontes:
    - processamento/mapeamento_grupos_enade.json   (grupo -> curso por ano)
    - dados/processados/analise_por_questao_ies_*.csv  (questao -> PERFIL/COMPETENCIAS/OC1..OC3)
"""
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
import json
import re
import sys
import unicodedata

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

RAIZ = Path(__file__).resolve().parent.parent.parent
CAMINHO_MAPA_GRUPOS = RAIZ / "processamento" / "mapeamento_grupos_enade.json"
PASTA_DADOS = RAIZ / "dados" / "processados"

PREFIXO = "https://prism-edu.example/onto#"


def normalizar(texto):
    if texto is None:
        return ""
    txt = str(texto)
    txt = "".join(ch for ch in unicodedata.normalize("NFKD", txt) if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", txt).strip().lower()


def _slug(texto):
    return re.sub(r"[^a-z0-9]+", "_", normalizar(texto)).strip("_")


def _remover_prefixo_romano(texto):
    if texto is None:
        return ""
    m = re.match(r"^([IVXLCDM]{1,6})\s*[-.:]\s*(.+)$", str(texto).strip())
    return m.group(2).strip() if m else str(texto).strip()


@dataclass
class No:
    id: str
    tipo: str
    rotulo: str
    atributos: dict = field(default_factory=dict)


class OntologiaEnade:
    """Grafo de conhecimento educacional construido a partir de dados reais."""

    def __init__(self):
        self.nos = {}
        self.arestas = []  # (origem_id, relacao, destino_id, peso)

    # -- construcao ---------------------------------------------------------
    def adicionar_no(self, id_, tipo, rotulo, **atributos):
        if id_ not in self.nos:
            self.nos[id_] = No(id_, tipo, rotulo, atributos)
        return id_

    def adicionar_aresta(self, origem, relacao, destino, peso=None):
        self.arestas.append((origem, relacao, destino, peso))

    def carregar_grupos(self, caminho=None):
        caminho = Path(caminho or CAMINHO_MAPA_GRUPOS)
        if not caminho.exists():
            return 0
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        n = 0
        for ano, grupos in dados.items():
            edicao_id = self.adicionar_no(f"edicao_{ano}", "Edicao", f"ENADE {ano}",
                                          ano=int(ano))
            for grupo, curso in grupos.items():
                area_id = self.adicionar_no(f"area_{grupo}", "Area", f"Area {grupo}",
                                            codigo_grupo=int(grupo))
                curso_id = self.adicionar_no(f"curso_{_slug(curso)}", "Curso", curso)
                self.adicionar_aresta(curso_id, "pertence_a", area_id)
                self.adicionar_aresta(curso_id, "avaliado_em", edicao_id)
                n += 1
        return n

    def carregar_questoes(self, pasta=None, limite_arquivos=None):
        """Le analise_por_questao_ies_*.csv (questao -> Competencia/OC)."""
        pasta = Path(pasta or PASTA_DADOS)
        arquivos = sorted(pasta.glob("analise_por_questao_ies_enade_*.csv"))
        if limite_arquivos:
            arquivos = arquivos[-limite_arquivos:]
        coocorrencia = defaultdict(int)
        n_questoes = 0
        for arq in arquivos:
            try:
                import pandas as pd
                df = pd.read_csv(arq, sep=";", encoding="utf-8-sig", low_memory=False)
            except Exception:
                continue
            cols_oc = [c for c in df.columns if re.fullmatch(r"OC\d", str(c))]
            for _, linha in df.drop_duplicates(subset=["QUESTAO"] if "QUESTAO" in df.columns else None).iterrows():
                q = str(linha.get("QUESTAO", "")).strip()
                if not q or q == "nan":
                    continue
                q_id = self.adicionar_no(f"questao_{_slug(q)}", "Questao", q)
                comp = linha.get("COMPETENCIAS")
                comp_id = None
                if comp is not None and str(comp).strip() and str(comp).lower() != "nan":
                    c_limpo = _remover_prefixo_romano(comp)
                    comp_id = self.adicionar_no(f"comp_{_slug(c_limpo)}", "Competencia", c_limpo)
                    self.adicionar_aresta(q_id, "avalia", comp_id)
                ocs_da_questao = []
                for col in cols_oc:
                    valor = linha.get(col)
                    if valor is None or str(valor).strip().lower() in ("", "nan"):
                        continue
                    oc_limpo = _remover_prefixo_romano(valor)
                    if not oc_limpo:
                        continue
                    oc_id = self.adicionar_no(f"oc_{_slug(oc_limpo)}", "ObjetivoConhecimento", oc_limpo)
                    self.adicionar_aresta(q_id, "avalia", oc_id)
                    ocs_da_questao.append(oc_id)
                for i in range(len(ocs_da_questao)):
                    for j in range(i + 1, len(ocs_da_questao)):
                        a, b = sorted([ocs_da_questao[i], ocs_da_questao[j]])
                        coocorrencia[(a, b)] += 1
                n_questoes += 1
        for (a, b), peso in coocorrencia.items():
            self.adicionar_aresta(a, "coocorre_com", b, peso=peso)
        return n_questoes

    # -- metricas -----------------------------------------------------------
    def resumo(self):
        por_tipo = defaultdict(int)
        for no in self.nos.values():
            por_tipo[no.tipo] += 1
        por_rel = defaultdict(int)
        for _, rel, _, _ in self.arestas:
            por_rel[rel] += 1
        return {"nos": len(self.nos), "arestas": len(self.arestas),
                "por_tipo": dict(por_tipo), "por_relacao": dict(por_rel)}

    def validar(self):
        """Checa integridade basica do grafo."""
        problemas = []
        ids = set(self.nos)
        for origem, rel, destino, _ in self.arestas:
            if origem not in ids:
                problemas.append(f"origem inexistente: {origem}")
            if destino not in ids:
                problemas.append(f"destino inexistente: {destino}")
        # todo OC deve ser avaliado por >= 1 questao
        ocs = {i for i, n in self.nos.items() if n.tipo == "ObjetivoConhecimento"}
        avaliados = {d for _, rel, d, _ in self.arestas if rel == "avalia"}
        orfaos = ocs - avaliados
        if orfaos:
            problemas.append(f"{len(orfaos)} OC sem questao associada")
        return problemas

    # -- exportacao ---------------------------------------------------------
    def para_jsonld(self):
        grafo = []
        for no in self.nos.values():
            item = {"@id": PREFIXO + no.id, "@type": no.tipo, "rotulo": no.rotulo}
            item.update(no.atributos)
            grafo.append(item)
        for origem, rel, destino, peso in self.arestas:
            item = {"@id": f"{PREFIXO}{origem}--{rel}--{destino}",
                    "origem": PREFIXO + origem, "relacao": rel, "destino": PREFIXO + destino}
            if peso is not None:
                item["peso"] = peso
            grafo.append(item)
        return {"@context": {"rotulo": "https://prism-edu.example/onto#rotulo",
                             "relacao": "https://prism-edu.example/onto#relacao"},
                "@graph": grafo}

    def para_turtle(self):
        linhas = [f"@prefix prism: <{PREFIXO}> .", "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .", ""]
        for no in self.nos.values():
            linhas.append(f"prism:{no.id} a prism:{no.tipo} ;")
            linhas.append(f'    rdfs:label "{no.rotulo}" .')
        linhas.append("")
        for origem, rel, destino, peso in self.arestas:
            if peso is not None:
                linhas.append(f'prism:{origem} prism:{rel} prism:{destino} .  # peso={peso}')
            else:
                linhas.append(f"prism:{origem} prism:{rel} prism:{destino} .")
        return "\n".join(linhas)


def construir_ontologia(pasta_dados=None, limite_arquivos=None):
    onto = OntologiaEnade()
    onto.carregar_grupos()
    onto.carregar_questoes(pasta=pasta_dados, limite_arquivos=limite_arquivos)
    return onto
