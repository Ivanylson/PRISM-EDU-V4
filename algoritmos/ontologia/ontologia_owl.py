"""Ontologia OWL 2 DL do PRISM-EDU (Protégé-ready).

Este modulo constroi uma ontologia **OWL 2 DL** de verdade (TBox com classes,
propriedades, dominios/ranges, restricoes e caracteristicas; ABox populada
somente com dados reais do projeto) e a serializa em RDF/XML (``.owl``),
Turtle, JSON-LD e N-Triples.

Diferencas em relacao a ``ontologia_enade.py`` (grafo RDF artesanal):
    * ``owl:Ontology`` com versao, data e proveniencia (PROV-O / DCTERMS);
    * classes e propriedades OWL com dominio, range e restricoes;
    * vocabularios SKOS para as dimensoes contextuais (UF, regiao, ...);
    * individuos com IRIs estaveis e chaves auditaveis;
    * SHACL e consultas SPARQL como artefatos separados.

Fontes reais usadas (nenhum dado e' inventado):
    * ``processamento/mapeamento_grupos_enade.json``  (edicao -> grupo -> curso)
    * ``dados/processados/analise_por_questao_ies_<edicao>.csv``
    * ``dados/processados/dina_estimativas_<curso>.csv`` (opcional)

Uso programatico::

    from algoritmos.ontologia.ontologia_owl import construir_owl
    onto = construir_owl(edicoes=["enade_2023"])
    onto.salvar("modelos/ontologia")
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
import hashlib
import json
import re
import sys
import unicodedata

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

try:
    from rdflib import BNode, Graph, Literal, Namespace, URIRef
    from rdflib.namespace import DCTERMS, OWL, PROV, RDF, RDFS, SKOS, XSD
except ImportError as exc:  # pragma: no cover - mensagem amigavel
    raise ImportError(
        "A ontologia OWL requer 'rdflib'. Instale com:\n"
        "    python -m pip install -r requirements-ontologia.txt"
    ) from exc

RAIZ = Path(__file__).resolve().parent.parent.parent
CAMINHO_MAPA_GRUPOS = RAIZ / "processamento" / "mapeamento_grupos_enade.json"
PASTA_DADOS = RAIZ / "dados" / "processados"

PREFIXO = "https://prism-edu.example/onto#"
IRI_ONTOLOGIA = "https://prism-edu.example/onto"
VERSAO = "2026.11.14"
IRI_VERSAO = f"{IRI_ONTOLOGIA}/{VERSAO}"
NS = Namespace(PREFIXO)

# Namespaces auxiliares usados na proveniencia.
PRISM = NS


# ---------------------------------------------------------------------------
# utilidades
# ---------------------------------------------------------------------------
def normalizar(texto) -> str:
    if texto is None:
        return ""
    txt = str(texto)
    txt = "".join(ch for ch in unicodedata.normalize("NFKD", txt) if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", txt).strip().lower()


def slug(texto) -> str:
    """Slug ASCII seguro para IRI (sem acentos, sem espacos)."""
    return re.sub(r"[^a-z0-9]+", "_", normalizar(texto)).strip("_") or "x"


def slug_compacto(texto) -> str:
    """Chave de comparacao sem separadores.

    Necessaria porque ``slug('ENGENHARIA CIVIL')`` = ``engenharia_civil``,
    enquanto o nome do arquivo ``dina_estimativas_engenhariacivil.csv`` gera
    ``engenhariacivil``. Sem isso, cursos de nome composto eram silenciosamente
    ignorados no carregamento DINA.
    """
    return re.sub(r"[^a-z0-9]+", "", normalizar(texto)) or "x"


def _sem_romano_final(texto) -> str:
    """Remove sufixo romano final ('ENGENHARIA DE COMPUTACAO I' -> sem 'I')."""
    return re.sub(r"\s+[ivx]{1,4}$", "", normalizar(texto)).strip()


def _remover_prefixo_romano(texto) -> str:
    if texto is None:
        return ""
    m = re.match(r"^([IVXLCDM]{1,6})\s*[-.:]\s*(.+)$", str(texto).strip())
    return m.group(2).strip() if m else str(texto).strip()


def _vazio(valor) -> bool:
    """True para None, NaN, pd.NA e strings sentinela."""
    if valor is None:
        return True
    return str(valor).strip().lower() in {"", "nan", "none", "null", "<na>"}


def _decimal(valor):
    """Converte numeros com virgula ou ponto; retorna None se invalido."""
    if valor is None:
        return None
    txt = str(valor).strip()
    if txt == "" or txt.lower() in {"nan", "none", "null"}:
        return None
    txt = txt.replace("%", "").replace(" ", "")
    if "," in txt and "." in txt:
        txt = txt.replace(".", "").replace(",", ".")
    elif "," in txt:
        txt = txt.replace(",", ".")
    try:
        return float(txt)
    except ValueError:
        return None


def _int(valor):
    num = _decimal(valor)
    if num is None:
        return None
    try:
        return int(round(num))
    except (ValueError, OverflowError):
        return None


def _lit_decimal(valor, casas=6):
    num = _decimal(valor)
    if num is None:
        return None
    return Literal(f"{round(num, casas):.{casas}f}".rstrip("0").rstrip(".") or "0",
                   datatype=XSD.decimal)


def _lit_int(valor):
    num = _int(valor)
    if num is None:
        return None
    return Literal(num, datatype=XSD.integer)


def _sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with caminho.open("rb") as fh:
        for bloco in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# TBox: classes, propriedades e restricoes
# ---------------------------------------------------------------------------
CLASSES = [
    # (local, superclasse, rotulo, comentario)
    ("PrismEntity", None, "Entidade PRISM-EDU", "Classe raiz das entidades do dominio."),
    ("ExamFamily", "PrismEntity", "Familia de exame", "ENADE, ENAMED, ENADE Licenciaturas."),
    ("ExamEdition", "PrismEntity", "Edicao de exame", "Uma aplicacao anual de um exame."),
    ("KnowledgeArea", "PrismEntity", "Area de conhecimento",
     "Area avaliada no exame (estavel entre edicoes; identificada pelo nome do curso/area)."),
    ("ExamArea", "PrismEntity", "Area da edicao",
     "Recorte da area em uma edicao especifica; preserva o CO_GRUPO real, que e' instavel entre anos."),
    ("CourseProgram", "PrismEntity", "Curso (programa)",
     "Programa de curso superior (ex.: Medicina Veterinaria)."),
    ("CourseOffering", "PrismEntity", "Oferta de curso",
     "Oferta concreta identificada por CO_IES + CO_CURSO em uma edicao."),
    ("HigherEducationInstitution", "PrismEntity", "Instituicao de ensino superior",
     "IES identificada pelo CO_IES."),
    ("AssessmentItem", "PrismEntity", "Item de avaliacao",
     "Questao objetiva; identidade local a edicao/area (Q1 nao e' global)."),
    ("ItemApplication", "PrismEntity", "Aplicacao do item",
     "Aplicacao de um item a uma oferta de curso (classe de ligacao; nao populada por padrao)."),
    ("PerformanceIndicator", "PrismEntity", "Indicador de desempenho", "Classe raiz dos agregados."),
    ("ItemPerformance", "PerformanceIndicator", "Desempenho do item",
     "Agregado nacional de acertos/erros de um item em uma edicao."),
    ("InstitutionPerformance", "PerformanceIndicator", "Desempenho da IES",
     "Agregado de acertos/erros de uma IES em uma edicao."),
    ("InstitutionAreaPerformance", "PerformanceIndicator", "Desempenho da IES na area",
     "Agregado de acertos/erros de uma IES em uma area/edicao."),
    ("CurricularElement", "PrismEntity", "Elemento curricular", "Classe raiz de competencias, OCs e perfis."),
    ("Competency", "CurricularElement", "Competencia", "Competencia do perfil do egresso."),
    ("LearningObjective", "CurricularElement", "Objetivo de conhecimento (OC)",
     "Objeto de conhecimento/conteudo avaliado por itens."),
    ("GraduateProfile", "CurricularElement", "Perfil do egresso", "Perfil declarado na prova/area."),
    ("PsychometricEstimate", "PrismEntity", "Estimativa psicometrica",
     "Parametros estimados por modelo (ex.: DINA: guess/slip)."),
    ("AnalyticalMethod", "PrismEntity", "Metodo analitico", "DINA, LCA, IRT, K-Means, SHAP..."),
    ("LatentClass", "PrismEntity", "Classe latente", "Classe de um modelo LCA."),
    ("MasteryProfile", "PrismEntity", "Perfil de dominio", "Padrao latente alpha de um modelo CDM."),
    ("Intervention", "PrismEntity", "Intervencao pedagogica", "Acao curricular simulada (what-if)."),
    ("StudentCohort", "PrismEntity", "Coorte de estudantes", "Agregado de alunos (nao individuo)."),
    ("ObjectiveCooccurrence", "PrismEntity", "Coocorrencia de OCs",
     "Par de OCs avaliados pelo mesmo item; o peso e' o numero de itens."),
    ("ContextualDimension", "PrismEntity", "Dimensao contextual",
     "Dimensao socioestrutural descrita por um SKOS ConceptScheme."),
]

OBJECT_PROPERTIES = [
    # (local, dominio, range, inversa, caracteristicas, rotulo)
    ("belongsToArea", "CourseProgram", "KnowledgeArea", "hasCourseProgram", [], "pertence a area"),
    ("belongsToFamily", "ExamEdition", "ExamFamily", "hasEdition", [], "pertence a familia de exame"),
    ("courseAssessedIn", "CourseProgram", "ExamEdition", None, [], "avaliado na edicao"),
    ("inEdition", "AssessmentItem", "ExamEdition", "hasItem", [], "esta na edicao"),
    ("inKnowledgeArea", "AssessmentItem", "KnowledgeArea", None, [], "esta na area de conhecimento"),
    ("inExamArea", "AssessmentItem", "ExamArea", "hasItemOfExamArea", [], "esta na area da edicao"),
    ("examAreaInEdition", "ExamArea", "ExamEdition", "hasExamArea", [], "area da edicao"),
    ("examAreaRefersTo", "ExamArea", "KnowledgeArea", "hasExamAreaOfEdition", [],
     "area da edicao refere-se a area de conhecimento"),
    ("assessesCompetency", "AssessmentItem", "Competency", "assessedByItem", [], "avalia competencia"),
    ("assessesObjective", "AssessmentItem", "LearningObjective", "objectiveAssessedByItem", [],
     "avalia objetivo de conhecimento"),
    ("expressesProfile", "AssessmentItem", "GraduateProfile", "profileExpressedByItem", [],
     "expressa perfil do egresso"),
    ("partOf", "PrismEntity", "PrismEntity", None, ["transitive"], "parte de"),
    ("objectivePartOfCompetency", "LearningObjective", "Competency", "hasObjective", [], "OC parte de competencia"),
    ("coOccursWith", "LearningObjective", "LearningObjective", None, ["symmetric"],
     "coocorre com outro OC"),
    ("firstObjective", "ObjectiveCooccurrence", "LearningObjective", None, [], "primeiro OC do par"),
    ("secondObjective", "ObjectiveCooccurrence", "LearningObjective", None, [], "segundo OC do par"),
    ("aboutItem", "PerformanceIndicator", "AssessmentItem", "hasPerformance", [], "sobre o item"),
    ("aboutEdition", "PerformanceIndicator", "ExamEdition", None, [], "sobre a edicao"),
    ("aboutArea", "PerformanceIndicator", "KnowledgeArea", None, [], "sobre a area"),
    ("aboutInstitution", "PerformanceIndicator", "HigherEducationInstitution", None, [], "sobre a IES"),
    ("offeredBy", "CourseOffering", "HigherEducationInstitution", "offers", [], "ofertado por"),
    ("offersProgram", "CourseOffering", "CourseProgram", "hasOffering", [], "oferta o programa"),
    ("offeringInEdition", "CourseOffering", "ExamEdition", None, [], "oferta na edicao"),
    ("hasPsychometricEstimate", "AssessmentItem", "PsychometricEstimate", "estimateOfItem", [],
     "tem estimativa psicometrica"),
    ("usesMethod", "PsychometricEstimate", "AnalyticalMethod", None, [], "usa metodo"),
    ("targetsItem", "Intervention", "AssessmentItem", None, [], "intervem no item"),
    ("targetsObjective", "Intervention", "LearningObjective", None, [], "intervem no OC"),
    ("hasState", "CourseOffering", "SKOSConcept", None, [], "tem UF"),
    ("hasRegion", "CourseOffering", "SKOSConcept", None, [], "tem regiao"),
    ("hasAdministrativeCategory", "CourseOffering", "SKOSConcept", None, [], "tem categoria administrativa"),
    ("hasAcademicOrganization", "CourseOffering", "SKOSConcept", None, [], "tem organizacao academica"),
    ("hasModality", "CourseOffering", "SKOSConcept", None, [], "tem modalidade"),
    ("hasStudentSex", "StudentCohort", "SKOSConcept", None, [], "tem sexo"),
    ("hasAgeGroup", "StudentCohort", "SKOSConcept", None, [], "tem faixa etaria"),
    ("memberOfLatentClass", "StudentCohort", "LatentClass", None, [], "pertence a classe latente"),
    ("hasMasteryProfile", "StudentCohort", "MasteryProfile", None, [], "tem perfil de dominio"),
    ("applicationOfItem", "ItemApplication", "AssessmentItem", None, [], "aplicacao do item"),
    ("applicationAtOffering", "ItemApplication", "CourseOffering", None, [], "aplicacao na oferta"),
]

# SKOSConcept e' apenas um alias de skos:Concept para permitir range declarado.
SKOS_CONCEPT = SKOS.Concept

DATA_PROPERTIES = [
    # (local, dominio, range, rotulo)
    ("hasCode", None, XSD.string, "codigo"),
    ("hasName", None, XSD.string, "nome"),
    ("hasYear", None, XSD.integer, "ano"),
    ("hasQuestionNumber", "AssessmentItem", XSD.integer, "numero da questao"),
    ("hasExamAreaCode", "PsychometricEstimate", XSD.string, "area da prova (FG/CE)"),
    ("hasGroupCode", "ExamArea", XSD.string, "codigo do grupo (CO_GRUPO)"),
    ("hasCourseCode", "CourseOffering", XSD.string, "codigo do curso (CO_CURSO)"),
    ("hasCorrectCount", "PerformanceIndicator", XSD.integer, "quantidade de acertos"),
    ("hasErrorCount", "PerformanceIndicator", XSD.integer, "quantidade de erros"),
    ("hasResponseCount", "PerformanceIndicator", XSD.integer, "quantidade de respostas"),
    ("deficiencyRate", "PerformanceIndicator", XSD.decimal, "taxa de deficiencia (%)"),
    ("excellenceRate", "PerformanceIndicator", XSD.decimal, "taxa de excelencia (%)"),
    ("guess", "PsychometricEstimate", XSD.decimal, "parametro guess (g)"),
    ("slip", "PsychometricEstimate", XSD.decimal, "parametro slip (s)"),
    ("masteryProbability", "PsychometricEstimate", XSD.decimal, "P(domina atributos)"),
    ("correctProbability", "PsychometricEstimate", XSD.decimal, "P(acerto) do modelo"),
    ("discrimination", None, XSD.decimal, "discriminacao"),
    ("difficulty", None, XSD.decimal, "dificuldade"),
    ("hasWeight", "ObjectiveCooccurrence", XSD.integer, "peso da coocorrencia"),
    ("estimationStatus", "PsychometricEstimate", XSD.string, "status da estimacao"),
    ("hasSourceTable", None, XSD.string, "tabela de origem"),
    ("hasSourceKey", None, XSD.string, "chave na tabela de origem"),
    ("hasVersion", None, XSD.string, "versao"),
]

# Codigos oficiais do INEP usados no projeto (nao sao dados fabricados: sao
# listas de codigos publicas). A faixa etaria e' um recorte de analise nosso.
SCHEMES = {
    "scheme_uf": ("UF do curso", [
        ("11", "RO"), ("12", "AC"), ("13", "AM"), ("14", "RR"), ("15", "PA"), ("16", "AP"), ("17", "TO"),
        ("21", "MA"), ("22", "PI"), ("23", "CE"), ("24", "RN"), ("25", "PB"), ("26", "PE"), ("27", "AL"),
        ("28", "SE"), ("29", "BA"), ("31", "MG"), ("32", "ES"), ("33", "RJ"), ("35", "SP"), ("41", "PR"),
        ("42", "SC"), ("43", "RS"), ("50", "MS"), ("51", "MT"), ("52", "GO"), ("53", "DF"),
    ]),
    "scheme_regiao": ("Regiao do curso", [
        ("1", "Norte"), ("2", "Nordeste"), ("3", "Sudeste"), ("4", "Sul"), ("5", "Centro-Oeste"),
    ]),
    "scheme_categoria_administrativa": ("Categoria administrativa da IES", [
        ("1", "Publica Federal"), ("2", "Publica Estadual"), ("3", "Publica Municipal"),
        ("4", "Privada com fins lucrativos"), ("5", "Privada sem fins lucrativos"), ("6", "Especial"),
    ]),
    "scheme_organizacao_academica": ("Organizacao academica", [
        ("1", "Universidade"), ("2", "Centro Universitario"), ("3", "Faculdade"),
        ("4", "Instituto Federal de Educacao, Ciencia e Tecnologia / CEFET"),
    ]),
    "scheme_modalidade": ("Modalidade de ensino", [
        ("1", "Presencial"), ("2", "Educacao a distancia"),
    ]),
    "scheme_sexo": ("Sexo", [
        ("1", "Masculino"), ("2", "Feminino"),
    ]),
    "scheme_faixa_etaria": ("Faixa etaria (recorte PRISM-EDU)", [
        ("ate_24", "Ate 24 anos"), ("25_29", "25 a 29 anos"), ("30_39", "30 a 39 anos"),
        ("40_49", "40 a 49 anos"), ("50_mais", "50 anos ou mais"),
    ]),
}

METODOS = [
    ("metodo_dina", "DINA (Deterministic Inputs, Noisy And-gate)",
     "algoritmos/cdm/dina_em.py"),
    ("metodo_lca", "LCA (Analise de Classes Latentes)",
     "algoritmos/lca/pipeline_lca.py"),
    ("metodo_irt", "IRT (Teoria de Resposta ao Item)", "algoritmos/irt"),
    ("metodo_kmeans", "K-Means / GMM / Hierarquico", "algoritmos/clustering/validacao.py"),
    ("metodo_shap", "SHAP / XAI", "algoritmos/shap/shap_analysis.py"),
]


# ---------------------------------------------------------------------------
# Ontologia
# ---------------------------------------------------------------------------
class OntologiaOWL:
    """Constroi a ontologia OWL 2 DL do PRISM-EDU."""

    def __init__(self, edicoes=None, incluir_dina=True, incluir_ies=True,
                 incluir_coocorrencia=True, limite_linhas=None):
        self.g = Graph()
        self.edicoes = edicoes or ["enade_2023"]
        self.incluir_dina = incluir_dina
        self.incluir_ies = incluir_ies
        self.incluir_coocorrencia = incluir_coocorrencia
        self.limite_linhas = limite_linhas
        self.fontes = set()
        self.estatisticas = Counter()
        self._cursos_por_grupo = {}  # (edicao, grupo) -> slug do curso
        self._grupo_por_curso = {}   # (edicao, slug curso) -> grupo
        self._bind_prefixes()

    # -- infraestrutura -----------------------------------------------------
    def _bind_prefixes(self):
        self.g.bind("prism", NS)
        self.g.bind("owl", OWL)
        self.g.bind("rdf", RDF)
        self.g.bind("rdfs", RDFS)
        self.g.bind("xsd", XSD)
        self.g.bind("skos", SKOS)
        self.g.bind("dcterms", DCTERMS)
        self.g.bind("prov", PROV)

    def _u(self, local) -> URIRef:
        return NS[local]

    def _add(self, sujeito, predicado, objeto):
        self.g.add((sujeito, predicado, objeto))
        return sujeito

    def _individuo(self, local, classe, rotulo=None, **props):
        # aceita nome local (str) ou IRI ja expandida (URIRef); nunca duplica o prefixo
        s = local if isinstance(local, URIRef) else self._u(local)
        self.g.add((s, RDF.type, OWL.NamedIndividual))
        self.g.add((s, RDF.type, self._u(classe)))
        if rotulo:
            self.g.add((s, RDFS.label, Literal(str(rotulo), lang="pt")))
            self.g.add((s, SKOS.prefLabel, Literal(str(rotulo), lang="pt")))
        for chave, valor in props.items():
            if valor is None:
                continue
            pred = self._u(chave)
            if isinstance(valor, (URIRef, Literal, BNode)):
                self.g.add((s, pred, valor))
            elif isinstance(valor, (list, tuple, set)):
                for v in valor:
                    if v is not None:
                        self.g.add((s, pred, v))
            else:
                self.g.add((s, pred, Literal(valor)))
        return s

    def _label(self, s, texto):
        self.g.add((s, RDFS.label, Literal(str(texto), lang="pt")))
        self.g.add((s, SKOS.prefLabel, Literal(str(texto), lang="pt")))

    # -- TBox ---------------------------------------------------------------
    def construir_tbox(self):
        g = self.g
        onto = URIRef(IRI_ONTOLOGIA)
        g.add((onto, RDF.type, OWL.Ontology))
        g.add((onto, RDFS.label, Literal("Ontologia PRISM-EDU", lang="pt")))
        g.add((onto, DCTERMS.title, Literal("Ontologia PRISM-EDU", lang="pt")))
        g.add((onto, DCTERMS.description, Literal(
            "Ontologia OWL 2 DL do PRISM-EDU para representar edicoes do ENADE/ENAMED/"
            "Licenciaturas, areas, cursos, IES, itens, competencias, objetivos de "
            "conhecimento, desempenho agregado e estimativas psicometricas. "
            "ABox construida apenas a partir de dados reais do projeto.", lang="pt")))
        g.add((onto, OWL.versionInfo, Literal(VERSAO)))
        g.add((onto, OWL.versionIRI, URIRef(IRI_VERSAO)))
        g.add((onto, DCTERMS.created, Literal(date.today().isoformat(), datatype=XSD.date)))
        g.add((onto, PROV.generatedAtTime, Literal(
            datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            datatype=XSD.dateTime)))
        g.add((onto, DCTERMS.creator,
               Literal("processamento/gerar_ontologia.py")))
        g.add((onto, DCTERMS.license, Literal(
            "Uso academico. Dados de origem: microdados publicos do INEP.", lang="pt")))

        # classes
        for local, pai, rotulo, comentario in CLASSES:
            cls = self._u(local)
            g.add((cls, RDF.type, OWL.Class))
            self._label(cls, rotulo)
            g.add((cls, RDFS.comment, Literal(comentario, lang="pt")))
            if pai:
                g.add((cls, RDFS.subClassOf, self._u(pai)))

        # disjuncoes que sustentam o modelo (evitam interpretacoes ambiguas)
        disjuntas = [
            ("AssessmentItem", "ItemApplication"),
            ("AssessmentItem", "PerformanceIndicator"),
            ("AssessmentItem", "ExamEdition"),
            ("ExamEdition", "KnowledgeArea"),
            ("CourseProgram", "CourseOffering"),
            ("CourseProgram", "HigherEducationInstitution"),
            ("Competency", "LearningObjective"),
            ("Competency", "GraduateProfile"),
            ("LearningObjective", "GraduateProfile"),
            ("PsychometricEstimate", "PerformanceIndicator"),
        ]
        for a, b in disjuntas:
            g.add((self._u(a), OWL.disjointWith, self._u(b)))

        # object properties
        for local, dominio, range_, inversa, caracteristicas, rotulo in OBJECT_PROPERTIES:
            prop = self._u(local)
            g.add((prop, RDF.type, OWL.ObjectProperty))
            self._label(prop, rotulo)
            if dominio:
                g.add((prop, RDFS.domain, self._u(dominio)))
            if range_:
                alvo = SKOS_CONCEPT if range_ == "SKOSConcept" else self._u(range_)
                g.add((prop, RDFS.range, alvo))
            if inversa:
                g.add((prop, OWL.inverseOf, self._u(inversa)))
            tipos_car = {"transitive": OWL.TransitiveProperty,
                         "symmetric": OWL.SymmetricProperty,
                         "functional": OWL.FunctionalProperty,
                         "inverse_functional": OWL.InverseFunctionalProperty}
            for car in caracteristicas:
                g.add((prop, RDF.type, tipos_car[car]))

        # declara explicitamente as propriedades inversas (boas praticas OWL 2 DL)
        for local, dominio, range_, inversa, _car, rotulo in OBJECT_PROPERTIES:
            if not inversa:
                continue
            inv = self._u(inversa)
            if (inv, RDF.type, OWL.ObjectProperty) in g:
                continue
            g.add((inv, RDF.type, OWL.ObjectProperty))
            self._label(inv, f"inversa de {rotulo}")
            if range_:
                g.add((inv, RDFS.domain,
                       SKOS_CONCEPT if range_ == "SKOSConcept" else self._u(range_)))
            if dominio:
                g.add((inv, RDFS.range, self._u(dominio)))

        # data properties
        for local, dominio, range_, rotulo in DATA_PROPERTIES:
            prop = self._u(local)
            g.add((prop, RDF.type, OWL.DatatypeProperty))
            self._label(prop, rotulo)
            if dominio:
                g.add((prop, RDFS.domain, self._u(dominio)))
            if range_:
                g.add((prop, RDFS.range, range_))

        # anotacoes usadas
        for anot in (SKOS.prefLabel, SKOS.altLabel, SKOS.notation, SKOS.inScheme,
                     DCTERMS.source, DCTERMS.description, PROV.wasDerivedFrom,
                     self._u("hasSourceHash")):
            g.add((anot, RDF.type, OWL.AnnotationProperty))

        # restricoes (OWL 2 DL)
        self._restricao_some("AssessmentItem", "inEdition", "ExamEdition")
        self._restricao_some("AssessmentItem", "inKnowledgeArea", "KnowledgeArea")
        self._restricao_some("AssessmentItem", "inExamArea", "ExamArea")
        self._restricao_some("CourseProgram", "belongsToArea", "KnowledgeArea")
        self._restricao_some("CourseOffering", "offeredBy", "HigherEducationInstitution")
        self._restricao_some("CourseOffering", "offersProgram", "CourseProgram")
        self._restricao_some("CourseOffering", "offeringInEdition", "ExamEdition")
        self._restricao_some("ExamArea", "examAreaInEdition", "ExamEdition")
        self._restricao_some("ExamArea", "examAreaRefersTo", "KnowledgeArea")
        self._restricao_some("ItemPerformance", "aboutItem", "AssessmentItem")
        self._restricao_some("ItemPerformance", "aboutEdition", "ExamEdition")
        self._restricao_some("InstitutionAreaPerformance", "aboutInstitution",
                             "HigherEducationInstitution")
        self._restricao_some("InstitutionAreaPerformance", "aboutArea", "KnowledgeArea")
        self._restricao_some("PsychometricEstimate", "estimateOfItem", "AssessmentItem")
        self._restricao_some("ItemApplication", "applicationOfItem", "AssessmentItem")
        self._restricao_some("ItemApplication", "applicationAtOffering", "CourseOffering")
        # item exatamente em uma edicao
        r = BNode()
        g.add((r, RDF.type, OWL.Restriction))
        g.add((r, OWL.onProperty, self._u("inEdition")))
        g.add((r, OWL.qualifiedCardinality, Literal(1, datatype=XSD.nonNegativeInteger)))
        g.add((r, OWL.onClass, self._u("ExamEdition")))
        g.add((self._u("AssessmentItem"), RDFS.subClassOf, r))
        # objectivePartOfCompetency e' subpropriedade de partOf
        g.add((self._u("objectivePartOfCompetency"), RDFS.subPropertyOf, self._u("partOf")))

        self.estatisticas["classes"] = len(CLASSES)
        self.estatisticas["object_properties"] = len(OBJECT_PROPERTIES)
        self.estatisticas["data_properties"] = len(DATA_PROPERTIES)

    def _restricao_some(self, classe, prop, alvo):
        r = BNode()
        self.g.add((r, RDF.type, OWL.Restriction))
        self.g.add((r, OWL.onProperty, self._u(prop)))
        self.g.add((r, OWL.someValuesFrom, self._u(alvo)))
        self.g.add((self._u(classe), RDFS.subClassOf, r))

    # -- SKOS: dimensoes contextuais ---------------------------------------
    def construir_skos(self):
        for esquema, (rotulo, conceitos) in SCHEMES.items():
            scheme = self._u(esquema)
            self.g.add((scheme, RDF.type, SKOS.ConceptScheme))
            self._label(scheme, rotulo)
            dim_local = "dim_" + esquema.replace("scheme_", "")
            dim = self._u(dim_local)
            self._individuo(dim_local, "ContextualDimension", rotulo)
            self.g.add((dim, SKOS.inScheme, scheme))
            for codigo, nome in conceitos:
                c = self._u(f"{esquema}_{slug(codigo)}")
                self.g.add((c, RDF.type, SKOS.Concept))
                self.g.add((c, SKOS.prefLabel, Literal(nome, lang="pt")))
                self.g.add((c, SKOS.notation, Literal(str(codigo))))
                self.g.add((c, SKOS.inScheme, scheme))
                self.g.add((scheme, SKOS.hasTopConcept, c))
                self.g.add((c, SKOS.topConceptOf, scheme))
            self.estatisticas["conceitos_skos"] += len(conceitos)

    def construir_metodos(self):
        for local, rotulo, implementacao in METODOS:
            self._individuo(local, "AnalyticalMethod", rotulo)
            self.g.add((self._u(local), DCTERMS.source, Literal(implementacao)))
        self.estatisticas["metodos"] = len(METODOS)

    # -- ABox: edicoes, areas, cursos --------------------------------------
    def _carregar_mapa(self):
        if not CAMINHO_MAPA_GRUPOS.exists():
            return {}
        self.fontes.add(CAMINHO_MAPA_GRUPOS)
        return json.loads(CAMINHO_MAPA_GRUPOS.read_text(encoding="utf-8"))

    def _edicao_info(self, edicao):
        """Retorna (slug, ano, familia, rotulo) a partir do nome do arquivo."""
        m = re.match(r"^(enade|enamed|licenciaturas)_(\d{4})$", edicao)
        if not m:
            return slug(edicao), None, "fam_enade", edicao
        familia, ano = m.group(1), int(m.group(2))
        if familia == "enamed":
            return slug(edicao), ano, "fam_enamed", f"ENAMED {ano}"
        if familia == "licenciaturas":
            return slug(edicao), ano, "fam_licenciaturas", f"ENADE Licenciaturas {ano}"
        return slug(edicao), ano, "fam_enade", f"ENADE {ano}"

    def _criar_familias(self):
        for local, rotulo in [("fam_enade", "ENADE"),
                              ("fam_enamed", "ENAMED"),
                              ("fam_licenciaturas", "ENADE Licenciaturas")]:
            self._individuo(local, "ExamFamily", rotulo)

    def _criar_edicao(self, edicao, ano, familia, rotulo):
        ed = self._u(f"edicao_{slug(edicao)}")
        self._individuo(f"edicao_{slug(edicao)}", "ExamEdition", rotulo)
        if ano is not None:
            self.g.add((ed, self._u("hasYear"), Literal(int(ano), datatype=XSD.integer)))
        self.g.add((ed, self._u("hasCode"), Literal(edicao)))
        # ligacao edicao -> familia
        self.g.add((ed, self._u("belongsToFamily"), self._u(familia)))
        return ed

    def _garantir_area_curso(self, edicao_slug, grupo, nome_curso, rotulo_edicao):
        curso = (nome_curso or f"Area {grupo}").strip()
        curso_slug = slug(curso)
        area = self._u(f"area_{curso_slug}")
        if (area, RDF.type, self._u("KnowledgeArea")) not in self.g:
            self._individuo(f"area_{curso_slug}", "KnowledgeArea", curso.title())
        prog = self._u(f"curso_{curso_slug}")
        if (prog, RDF.type, self._u("CourseProgram")) not in self.g:
            self._individuo(f"curso_{curso_slug}", "CourseProgram", curso.title())
            self.g.add((prog, self._u("belongsToArea"), area))
        exam_area = self._u(f"areaed_{edicao_slug}_{slug(grupo)}")
        if (exam_area, RDF.type, self._u("ExamArea")) not in self.g:
            self._individuo(f"areaed_{edicao_slug}_{slug(grupo)}", "ExamArea",
                            f"{curso.title()} - area {grupo} ({rotulo_edicao})")
            self.g.add((exam_area, self._u("hasGroupCode"), Literal(str(grupo))))
            self.g.add((exam_area, self._u("examAreaRefersTo"), area))
            self.g.add((exam_area, self._u("examAreaInEdition"),
                        self._u(f"edicao_{edicao_slug}")))
        self._cursos_por_grupo[(edicao_slug, str(grupo))] = curso_slug
        self._grupo_por_curso[(edicao_slug, curso_slug)] = str(grupo)
        # chaves tolerantes ao formato do nome do arquivo DINA (sem separadores
        # e sem sufixo romano): 'engenhariacivil', 'engenhariadecomputacao'
        self._grupo_por_curso[(edicao_slug, slug_compacto(curso))] = str(grupo)
        self._grupo_por_curso[(edicao_slug, slug_compacto(_sem_romano_final(curso)))] = str(grupo)
        return area, prog, exam_area

    # -- ABox: leitura dos fatos -------------------------------------------
    def _ler_csv(self, caminho, colunas):
        import pandas as pd
        cabecalho = pd.read_csv(caminho, sep=";", encoding="utf-8-sig", nrows=0)
        usecols = [c for c in colunas if c in cabecalho.columns]
        if not usecols:
            return None
        try:
            df = pd.read_csv(caminho, sep=";", encoding="utf-8-sig",
                             usecols=usecols, low_memory=False,
                             nrows=self.limite_linhas)
        except UnicodeDecodeError:
            df = pd.read_csv(caminho, sep=";", encoding="latin-1",
                             usecols=usecols, low_memory=False,
                             nrows=self.limite_linhas)
        return df

    def carregar_edicao(self, edicao):
        import pandas as pd
        caminho = PASTA_DADOS / f"analise_por_questao_ies_{edicao}.csv"
        if not caminho.exists():
            print(f"  [aviso] arquivo nao encontrado: {caminho}")
            return
        self.fontes.add(caminho)
        edicao_slug, ano, familia, rotulo_edicao = self._edicao_info(edicao)
        self._criar_edicao(edicao, ano, familia, rotulo_edicao)

        colunas = ["CO_IES", "CO_CURSO", "CO_UF_CURSO", "CO_REGIAO_CURSO", "NOME_CURSO",
                   "CO_GRUPO", "NU_ANO", "QUESTAO", "PERFIL", "COMPETENCIAS",
                   "OC1", "OC2", "OC3", "QTD_ACERTOS", "QTD_ERROS", "TAXA_DEFICIENCIA_%"]
        df = self._ler_csv(caminho, colunas)
        if df is None or df.empty:
            print(f"  [aviso] sem colunas esperadas em {caminho.name}")
            return

        for c in ("CO_IES", "CO_CURSO", "CO_GRUPO", "CO_UF_CURSO", "CO_REGIAO_CURSO"):
            if c in df.columns:
                df[c] = df[c].map(lambda v: str(_int(v)) if _int(v) is not None else str(v).strip())
        for c in ("QTD_ACERTOS", "QTD_ERROS", "TAXA_DEFICIENCIA_%"):
            if c in df.columns:
                df[c] = df[c].map(_decimal)
        if "QUESTAO" in df.columns:
            df["QUESTAO"] = df["QUESTAO"].astype(str).str.strip()
        if "CO_GRUPO" not in df.columns:
            df["CO_GRUPO"] = "0"

        # mapa oficial (quando existe) -> areas/cursos
        mapa = self._carregar_mapa()
        grupos_mapa = mapa.get(str(ano), {}) if ano is not None else {}
        for grupo, curso in grupos_mapa.items():
            self._garantir_area_curso(edicao_slug, str(grupo), curso, rotulo_edicao)

        # nomes de curso observados (fallback e conferencia)
        nomes = {}
        if "NOME_CURSO" in df.columns:
            for grupo, sub in df.groupby("CO_GRUPO", observed=True):
                nome = sub["NOME_CURSO"].dropna().astype(str).str.strip()
                nome = nome[nome.ne("") & nome.str.lower().ne("nan")]
                nomes[str(grupo)] = nome.iloc[0] if len(nome) else None
        for grupo in sorted(df["CO_GRUPO"].dropna().unique()):
            if (edicao_slug, str(grupo)) not in self._cursos_por_grupo:
                self._garantir_area_curso(edicao_slug, str(grupo), nomes.get(str(grupo)),
                                          rotulo_edicao)

        # metadados curriculares por item (primeiro valor nao nulo por coluna)
        cols_meta = [c for c in ("PERFIL", "COMPETENCIAS", "OC1", "OC2", "OC3")
                     if c in df.columns]
        meta = df[["CO_GRUPO", "QUESTAO"] + cols_meta].copy()
        for c in cols_meta:
            meta[c] = (meta[c].astype("string").str.strip()
                       .replace({"": pd.NA, "nan": pd.NA, "None": pd.NA}))
        meta = meta.groupby(["CO_GRUPO", "QUESTAO"], as_index=False).first()

        itens_criados = set()
        cooc = Counter()
        for _, linha in meta.iterrows():
            grupo = str(linha["CO_GRUPO"])
            questao = str(linha["QUESTAO"]).strip()
            if not questao or questao.lower() == "nan":
                continue
            curso_slug = self._cursos_por_grupo.get((edicao_slug, grupo))
            if not curso_slug:
                continue
            item_local = f"item_{edicao_slug}_{slug(grupo)}_{slug(questao)}"
            item = self._u(item_local)
            if item_local in itens_criados:
                continue
            itens_criados.add(item_local)
            numero = re.sub(r"\D", "", questao)
            self._individuo(item_local, "AssessmentItem",
                            f"{questao} - {curso_slug.replace('_', ' ').title()} ({rotulo_edicao})")
            if numero:
                self.g.add((item, self._u("hasQuestionNumber"),
                            Literal(int(numero), datatype=XSD.integer)))
            self.g.add((item, self._u("hasCode"), Literal(f"{edicao}/{grupo}/{questao}")))
            self.g.add((item, self._u("inEdition"), self._u(f"edicao_{edicao_slug}")))
            self.g.add((item, self._u("inKnowledgeArea"), self._u(f"area_{curso_slug}")))
            self.g.add((item, self._u("inExamArea"),
                        self._u(f"areaed_{edicao_slug}_{slug(grupo)}")))

            perfil = linha.get("PERFIL")
            if not _vazio(perfil):
                perfil = str(perfil).strip()
                pid = f"perfil_{slug(perfil)}"
                if (self._u(pid), RDF.type, self._u("GraduateProfile")) not in self.g:
                    self._individuo(pid, "GraduateProfile", perfil)
                self.g.add((item, self._u("expressesProfile"), self._u(pid)))

            comp = linha.get("COMPETENCIAS")
            if not _vazio(comp):
                comp = str(comp).strip()
                cid = f"comp_{slug(comp)}"
                if (self._u(cid), RDF.type, self._u("Competency")) not in self.g:
                    self._individuo(cid, "Competency", _remover_prefixo_romano(comp))
                self.g.add((item, self._u("assessesCompetency"), self._u(cid)))

            ocs = []
            for col in ("OC1", "OC2", "OC3"):
                valor = linha.get(col)
                if _vazio(valor):
                    continue
                valor = str(valor).strip()
                oid = f"oc_{slug(valor)}"
                if (self._u(oid), RDF.type, self._u("LearningObjective")) not in self.g:
                    self._individuo(oid, "LearningObjective", _remover_prefixo_romano(valor))
                self.g.add((item, self._u("assessesObjective"), self._u(oid)))
                ocs.append(oid)
            if self.incluir_coocorrencia:
                for i in range(len(ocs)):
                    for j in range(i + 1, len(ocs)):
                        a, b = sorted([ocs[i], ocs[j]])
                        cooc[(a, b)] += 1

        # coocorrencias (reificadas com peso + propriedade simetrica)
        if self.incluir_coocorrencia:
            for (a, b), peso in cooc.items():
                self.g.add((self._u(a), self._u("coOccursWith"), self._u(b)))
                self.g.add((self._u(b), self._u("coOccursWith"), self._u(a)))
                local = f"cooc_{a[3:]}_{b[3:]}"
                self._individuo(local, "ObjectiveCooccurrence", f"{a[3:]} + {b[3:]}")
                self.g.add((self._u(local), self._u("firstObjective"), self._u(a)))
                self.g.add((self._u(local), self._u("secondObjective"), self._u(b)))
                self.g.add((self._u(local), self._u("hasWeight"),
                            Literal(int(peso), datatype=XSD.integer)))
            self.estatisticas["coocorrencias"] += len(cooc)

        # desempenho nacional por item
        if {"QTD_ACERTOS", "QTD_ERROS"}.issubset(df.columns):
            perf = (df.groupby(["CO_GRUPO", "QUESTAO"], observed=True)[["QTD_ACERTOS", "QTD_ERROS"]]
                    .sum(min_count=1).reset_index())
            for _, linha in perf.iterrows():
                grupo, questao = str(linha["CO_GRUPO"]), str(linha["QUESTAO"])
                acertos = _int(linha["QTD_ACERTOS"])
                erros = _int(linha["QTD_ERROS"])
                if acertos is None and erros is None:
                    continue
                local = f"perfitem_{edicao_slug}_{slug(grupo)}_{slug(questao)}"
                self._individuo(local, "ItemPerformance",
                                f"Desempenho {questao} - area {grupo} ({rotulo_edicao})")
                self.g.add((self._u(local), self._u("aboutItem"),
                            self._u(f"item_{edicao_slug}_{slug(grupo)}_{slug(questao)}")))
                self.g.add((self._u(local), self._u("aboutEdition"),
                            self._u(f"edicao_{edicao_slug}")))
                self.g.add((self._u(local), self._u("aboutArea"),
                            self._u(f"area_{self._cursos_por_grupo.get((edicao_slug, grupo), 'x')}")))
                self._contagens(local, acertos, erros)
            self.estatisticas["perf_itens"] += len(perf)

        # IES, ofertas e desempenho agregado
        if self.incluir_ies and "CO_IES" in df.columns:
            self._carregar_ies(df, edicao_slug, rotulo_edicao)

        self.estatisticas["itens"] += len(itens_criados)
        print(f"  [{edicao}] itens={len(itens_criados)} | linhas={len(df)}")

    def _contagens(self, local, acertos, erros):
        s = self._u(local)
        if acertos is not None:
            self.g.add((s, self._u("hasCorrectCount"), Literal(int(acertos), datatype=XSD.integer)))
        if erros is not None:
            self.g.add((s, self._u("hasErrorCount"), Literal(int(erros), datatype=XSD.integer)))
        total = (acertos or 0) + (erros or 0)
        if total:
            self.g.add((s, self._u("hasResponseCount"), Literal(int(total), datatype=XSD.integer)))
            taxa = round((erros or 0) / total * 100.0, 6)
            self.g.add((s, self._u("deficiencyRate"),
                        Literal(f"{taxa:.6f}".rstrip("0").rstrip("."), datatype=XSD.decimal)))

    def _carregar_ies(self, df, edicao_slug, rotulo_edicao):
        # IES
        for codigo in sorted(df["CO_IES"].dropna().unique()):
            codigo = str(codigo).strip()
            if not codigo or codigo.lower() == "nan":
                continue
            local = f"ies_{slug(codigo)}"
            if (self._u(local), RDF.type, self._u("HigherEducationInstitution")) not in self.g:
                self._individuo(local, "HigherEducationInstitution", f"IES {codigo}")
                self.g.add((self._u(local), self._u("hasCode"), Literal(codigo)))

        # ofertas de curso (CO_IES + CO_CURSO), com area e contexto quando houver
        if "CO_CURSO" in df.columns:
            cols_oferta = ["CO_IES", "CO_CURSO"] + [c for c in ("CO_GRUPO", "CO_UF_CURSO",
                                                                "CO_REGIAO_CURSO")
                                                     if c in df.columns]
            ofertas = df[cols_oferta].dropna().drop_duplicates()
            for _, linha in ofertas.iterrows():
                ies, curso = str(linha["CO_IES"]).strip(), str(linha["CO_CURSO"]).strip()
                if not ies or not curso or "nan" in (ies.lower(), curso.lower()):
                    continue
                local = f"oferta_{slug(ies)}_{slug(curso)}"
                if (self._u(local), RDF.type, self._u("CourseOffering")) not in self.g:
                    self._individuo(local, "CourseOffering",
                                    f"Oferta {curso} - IES {ies} ({rotulo_edicao})")
                    self.g.add((self._u(local), self._u("hasCourseCode"), Literal(curso)))
                    self.g.add((self._u(local), self._u("offeredBy"),
                                self._u(f"ies_{slug(ies)}")))
                    self.g.add((self._u(local), self._u("offeringInEdition"),
                                self._u(f"edicao_{edicao_slug}")))
                grupo = str(linha.get("CO_GRUPO", "")).strip()
                curso_slug = self._cursos_por_grupo.get((edicao_slug, grupo))
                if curso_slug:
                    self.g.add((self._u(local), self._u("offersProgram"),
                                self._u(f"curso_{curso_slug}")))
                uf = str(linha.get("CO_UF_CURSO", "")).strip()
                if uf and uf.lower() != "nan":
                    self.g.add((self._u(local), self._u("hasState"),
                                self._u(f"scheme_uf_{slug(uf)}")))
                regiao = str(linha.get("CO_REGIAO_CURSO", "")).strip()
                if regiao and regiao.lower() != "nan":
                    self.g.add((self._u(local), self._u("hasRegion"),
                                self._u(f"scheme_regiao_{slug(regiao)}")))
            self.estatisticas["ofertas"] += len(ofertas)

        if {"QTD_ACERTOS", "QTD_ERROS"}.issubset(df.columns):
            # desempenho por IES
            por_ies = (df.groupby("CO_IES", observed=True)[["QTD_ACERTOS", "QTD_ERROS"]]
                       .sum(min_count=1).reset_index())
            for _, linha in por_ies.iterrows():
                ies = str(linha["CO_IES"]).strip()
                local = f"perfies_{edicao_slug}_{slug(ies)}"
                self._individuo(local, "InstitutionPerformance",
                                f"Desempenho IES {ies} ({rotulo_edicao})")
                self.g.add((self._u(local), self._u("aboutInstitution"), self._u(f"ies_{slug(ies)}")))
                self.g.add((self._u(local), self._u("aboutEdition"),
                            self._u(f"edicao_{edicao_slug}")))
                self._contagens(local, _int(linha["QTD_ACERTOS"]), _int(linha["QTD_ERROS"]))
            self.estatisticas["perf_ies"] += len(por_ies)

            # desempenho por IES x area
            por_area = (df.groupby(["CO_IES", "CO_GRUPO"], observed=True)[["QTD_ACERTOS", "QTD_ERROS"]]
                        .sum(min_count=1).reset_index())
            for _, linha in por_area.iterrows():
                ies, grupo = str(linha["CO_IES"]).strip(), str(linha["CO_GRUPO"]).strip()
                curso_slug = self._cursos_por_grupo.get((edicao_slug, grupo))
                if not curso_slug:
                    continue
                local = f"perfiesarea_{edicao_slug}_{slug(ies)}_{slug(grupo)}"
                self._individuo(local, "InstitutionAreaPerformance",
                                f"Desempenho IES {ies} - area {grupo} ({rotulo_edicao})")
                self.g.add((self._u(local), self._u("aboutInstitution"), self._u(f"ies_{slug(ies)}")))
                self.g.add((self._u(local), self._u("aboutArea"), self._u(f"area_{curso_slug}")))
                self.g.add((self._u(local), self._u("aboutEdition"),
                            self._u(f"edicao_{edicao_slug}")))
                self._contagens(local, _int(linha["QTD_ACERTOS"]), _int(linha["QTD_ERROS"]))
            self.estatisticas["perf_ies_area"] += len(por_area)

    # -- ABox: DINA ---------------------------------------------------------
    def carregar_dina(self, edicao_base="enade_2023"):
        edicao_slug = slug(edicao_base)
        arquivos = sorted(PASTA_DADOS.glob("dina_estimativas_*.csv"))
        if not arquivos:
            return
        n = 0
        for arq in arquivos:
            chave_curso = arq.stem.replace("dina_estimativas_", "")
            curso_slug = slug(chave_curso)
            grupo = (self._grupo_por_curso.get((edicao_slug, curso_slug))
                     or self._grupo_por_curso.get((edicao_slug, slug_compacto(chave_curso))))
            if grupo is None:
                continue
            df = self._ler_csv(arq, ["Questao", "area_prova", "guess_g", "slip_s",
                                     "p_domina_atributos", "p_acerto_dina", "status"])
            if df is None or df.empty or "Questao" not in df.columns:
                continue
            self.fontes.add(arq)
            for _, linha in df.iterrows():
                questao = str(linha.get("Questao", "")).strip()
                if _vazio(questao):
                    continue
                item_local = f"item_{edicao_slug}_{slug(grupo)}_{slug(questao)}"
                if (self._u(item_local), RDF.type, self._u("AssessmentItem")) not in self.g:
                    continue
                local = f"dina_{edicao_slug}_{curso_slug}_{slug(questao)}"
                self._individuo(local, "PsychometricEstimate",
                                f"DINA {questao} - {curso_slug.replace('_', ' ').title()}")
                self.g.add((self._u(local), self._u("estimateOfItem"), self._u(item_local)))
                self.g.add((self._u(local), self._u("usesMethod"), self._u("metodo_dina")))
                self.g.add((self._u(local), self._u("hasSourceTable"), Literal(arq.name)))
                self.g.add((self._u(local), self._u("hasSourceKey"),
                            Literal(f"{curso_slug}/{questao}")))
                self.g.add((self._u(local), PROV.wasDerivedFrom,
                            URIRef("file:///" + arq.as_posix())))
                area_prova = linha.get("area_prova")
                if not _vazio(area_prova):
                    self.g.add((self._u(local), self._u("hasExamAreaCode"),
                                Literal(str(area_prova).strip())))
                for col, prop in (("guess_g", "guess"), ("slip_s", "slip"),
                                  ("p_domina_atributos", "masteryProbability"),
                                  ("p_acerto_dina", "correctProbability")):
                    valor = _lit_decimal(linha.get(col))
                    if valor is not None:
                        self.g.add((self._u(local), self._u(prop), valor))
                status = linha.get("status")
                if not _vazio(status):
                    self.g.add((self._u(local), self._u("estimationStatus"),
                                Literal(str(status).strip())))
                n += 1
        self.estatisticas["dina"] += n
        if n:
            print(f"  [DINA] estimativas ligadas a itens: {n}")

    # -- proveniencia -------------------------------------------------------
    def registrar_fontes(self):
        onto = URIRef(IRI_ONTOLOGIA)
        for caminho in sorted(self.fontes):
            caminho = Path(caminho)
            if not caminho.exists():
                continue
            self.g.add((onto, DCTERMS.source, Literal(str(caminho.relative_to(RAIZ)))))
            try:
                self.g.add((onto, self._u("hasSourceHash"),
                            Literal(f"{caminho.name}:sha256:{_sha256(caminho)}")))
            except OSError:
                pass

    # -- API ----------------------------------------------------------------
    def construir(self):
        self.construir_tbox()
        self.construir_skos()
        self.construir_metodos()
        self._criar_familias()
        for edicao in self.edicoes:
            self.carregar_edicao(edicao)
        if self.incluir_dina:
            candidatas = [e for e in self.edicoes if e.startswith("enade_")]
            edicao_dina = ("enade_2023" if "enade_2023" in self.edicoes
                           else (candidatas[-1] if candidatas else None))
            if edicao_dina:
                self.carregar_dina(edicao_dina)
        self.registrar_fontes()
        return self

    def resumo(self):
        por_classe = Counter()
        for s, _, o in self.g.triples((None, RDF.type, None)):
            if isinstance(o, URIRef) and str(o).startswith(PREFIXO):
                por_classe[str(o).split("#", 1)[1]] += 1
        return {"triplas": len(self.g), "por_classe": dict(sorted(por_classe.items())),
                "estatisticas": dict(self.estatisticas)}

    def validar(self):
        """Checagens estruturais honestas (nao substituem raciocinio OWL)."""
        problemas = []
        g = self.g

        def individuos(classe):
            return set(g.subjects(RDF.type, self._u(classe)))

        itens = individuos("AssessmentItem")
        for item in itens:
            if not list(g.objects(item, self._u("inEdition"))):
                problemas.append(f"item sem edicao: {item}")
            if not list(g.objects(item, self._u("inKnowledgeArea"))):
                problemas.append(f"item sem area: {item}")

        for perf in individuos("ItemPerformance"):
            if not list(g.objects(perf, self._u("aboutItem"))):
                problemas.append(f"desempenho de item sem item: {perf}")
            for _, _, valor in g.triples((perf, self._u("deficiencyRate"), None)):
                num = _decimal(valor)
                if num is not None and not (0 <= num <= 100):
                    problemas.append(f"taxa fora de [0,100]: {perf} = {num}")

        for oc in individuos("LearningObjective"):
            if not list(g.objects(oc, SKOS.prefLabel)) and not list(g.objects(oc, RDFS.label)):
                problemas.append(f"OC sem rotulo: {oc}")

        for prog in individuos("CourseProgram"):
            if not list(g.objects(prog, self._u("belongsToArea"))):
                problemas.append(f"curso sem area: {prog}")

        return problemas

    def salvar(self, pasta_saida, formatos=("owl", "ttl", "jsonld", "nt")):
        pasta = Path(pasta_saida)
        pasta.mkdir(parents=True, exist_ok=True)
        gerados = {}

        if "owl" in formatos:
            destino_owl = pasta / "prism_edu.owl"
            # base explicita: emite xml:base e IRIs relativas, o que agrada ao
            # parser RDF/XML da OWLAPI e ao Protege.
            self.g.serialize(destination=str(destino_owl), format="xml",
                             encoding="utf-8", base=IRI_ONTOLOGIA)
            gerados["owl"] = destino_owl

        if "ttl" in formatos:
            destino_ttl = pasta / "prism_edu.ttl"
            self.g.serialize(destination=str(destino_ttl), format="turtle", encoding="utf-8")
            gerados["ttl"] = destino_ttl

        if "jsonld" in formatos:
            destino_jsonld = pasta / "prism_edu.jsonld"
            self.g.serialize(destination=str(destino_jsonld), format="json-ld", indent=2)
            gerados["jsonld"] = destino_jsonld

        if "nt" in formatos:
            destino_nt = pasta / "prism_edu.nt"
            self.g.serialize(destination=str(destino_nt), format="nt", encoding="utf-8")
            gerados["nt"] = destino_nt

        # manifesto auditavel
        manifesto = {
            "ontologia": IRI_ONTOLOGIA,
            "versao": VERSAO,
            "iri_versao": IRI_VERSAO,
            "gerado_em": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "edicoes": self.edicoes,
            "incluir_dina": self.incluir_dina,
            "incluir_ies": self.incluir_ies,
            "resumo": self.resumo(),
            "arquivos": {k: {"nome": v.name, "bytes": v.stat().st_size,
                             "sha256": _sha256(v)} for k, v in gerados.items()},
            "fontes": [str(Path(p).relative_to(RAIZ)) for p in sorted(self.fontes)
                       if Path(p).exists()],
        }
        caminho_manifesto = pasta / "prism_edu_manifest.json"
        caminho_manifesto.write_text(json.dumps(manifesto, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
        gerados["manifesto"] = caminho_manifesto
        return gerados


def construir_owl(edicoes=None, incluir_dina=True, incluir_ies=True,
                  incluir_coocorrencia=True, limite_linhas=None):
    """Atalho de construcao (TBox + ABox real)."""
    return OntologiaOWL(edicoes=edicoes, incluir_dina=incluir_dina,
                        incluir_ies=incluir_ies,
                        incluir_coocorrencia=incluir_coocorrencia,
                        limite_linhas=limite_linhas).construir()
