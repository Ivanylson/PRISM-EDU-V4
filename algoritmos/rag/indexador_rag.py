"""
RAG local para o PRISM-EDU (Retrieval-Augmented Generation) SEM dependencias
pesadas: chunking + TF-IDF + busca por similaridade de cosseno.

Justificativa: o projeto defende soberania dos dados (nada sai para APIs
externas). Embeddings densos exigiriam sentence-transformers (~GB) ou API
remota. Aqui usamos TF-IDF (word + char n-grams) do scikit-learn, ja presente,
com indice em memoria/numpy -- auditavel e offline.

Artefatos:
    modelos/rag/corpus.jsonl   (1 chunk por linha: {id, fonte, texto, meta})
    modelos/rag/indice.npz     (matriz TF-IDF esparsa + metadados)
"""
from pathlib import Path
import json
import re
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

RAIZ = Path(__file__).resolve().parent.parent.parent
PASTA_RAG = RAIZ / "modelos" / "rag"
PROJETO_PAI = RAIZ.parent

# Fontes textuais reais do projeto (artefatos, nao microdados brutos).
FONTES_PADRAO = [
    (PROJETO_PAI / "modeloprojetoENADE2023" / "arquivosgerados" / "RESULTADOS" / "Dashboards", "*.md"),
    (PROJETO_PAI / "modeloprojetoENADE2023" / "preprocessamento" / "relatoriosintese", "*.pdf"),
    (PROJETO_PAI / "modeloprojetoENADE2023" / "preprocessamento" / "relatoriosintesesimplificado", "*.pdf"),
    (RAIZ / "dados" / "internacionais", "*.md"),
]

TAMANHO_CHUNK = 900
SOBREPOSICAO = 150


def _ler_pdf(caminho):
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(caminho))
        return "\n".join(pagina.get_text() for pagina in doc)
    except Exception:
        return ""


def _ler_texto(caminho):
    if caminho.suffix.lower() == ".pdf":
        return _ler_pdf(caminho)
    for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return caminho.read_text(encoding=enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return ""


def dividir_em_chunks(texto, tamanho=TAMANHO_CHUNK, sobreposicao=SOBREPOSICAO):
    """Divide texto em chunks por paragrafos, respeitando ~tamanho."""
    texto = re.sub(r"\s+", " ", texto or "").strip()
    if not texto:
        return []
    if len(texto) <= tamanho:
        return [texto]
    chunks = []
    inicio = 0
    while inicio < len(texto):
        fim = min(inicio + tamanho, len(texto))
        if fim < len(texto):
            corte = texto.rfind(". ", inicio, fim)
            if corte > inicio + tamanho // 2:
                fim = corte + 1
        chunks.append(texto[inicio:fim].strip())
        if fim >= len(texto):
            break
        inicio = max(fim - sobreposicao, inicio + 1)
    return [c for c in chunks if c]


def construir_corpus(fontes=None, limite_por_fonte=None):
    """Varre as fontes e devolve lista de chunks com metadados."""
    fontes = fontes or FONTES_PADRAO
    chunks = []
    cid = 0
    for pasta, padrao in fontes:
        pasta = Path(pasta)
        if not pasta.exists():
            continue
        arquivos = sorted(pasta.glob(padrao))
        if limite_por_fonte:
            arquivos = arquivos[:limite_por_fonte]
        for arq in arquivos:
            texto = _ler_texto(arq)
            for parte in dividir_em_chunks(texto):
                chunks.append({"id": f"c{cid}", "fonte": arq.name,
                               "caminho": str(arq), "texto": parte,
                               "meta": {"tipo": arq.suffix.lstrip(".")}})
                cid += 1
    return chunks


class IndiceRAG:
    """Indice TF-IDF em memoria com busca por cosseno."""

    def __init__(self):
        self.vetorizador = None
        self.matriz = None
        self.chunks = []

    def indexar(self, chunks):
        from sklearn.feature_extraction.text import TfidfVectorizer
        self.chunks = [c for c in chunks if c.get("texto")]
        if not self.chunks:
            raise ValueError("Corpus vazio: nenhum chunk para indexar.")
        textos = [c["texto"] for c in self.chunks]
        self.vetorizador = TfidfVectorizer(
            ngram_range=(1, 2), min_df=1, sublinear_tf=True)
        self.matriz = self.vetorizador.fit_transform(textos)
        return self

    def buscar(self, consulta, top_k=5, limiar=0.05):
        """Retorna lista de {score, fonte, texto, id}. Vazio se nada superar limiar."""
        if self.vetorizador is None or self.matriz is None:
            return []
        from sklearn.metrics.pairwise import cosine_similarity
        q = self.vetorizador.transform([consulta])
        scores = cosine_similarity(q, self.matriz)[0]
        ordem = np.argsort(scores)[::-1][:top_k]
        resultados = []
        for i in ordem:
            if scores[i] >= limiar:
                c = self.chunks[i]
                resultados.append({"score": float(scores[i]), "id": c["id"],
                                   "fonte": c["fonte"], "texto": c["texto"]})
        return resultados

    def salvar(self, pasta=None):
        pasta = Path(pasta or PASTA_RAG)
        pasta.mkdir(parents=True, exist_ok=True)
        with open(pasta / "corpus.jsonl", "w", encoding="utf-8") as f:
            for c in self.chunks:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
        from scipy import sparse
        sparse.save_npz(pasta / "indice.npz", self.matriz)
        (pasta / "metadados.json").write_text(
            json.dumps({"n_chunks": len(self.chunks), "n_features": self.matriz.shape[1]},
                       ensure_ascii=False), encoding="utf-8")
        return pasta

    def carregar(self, pasta=None):
        pasta = Path(pasta or PASTA_RAG)
        corpus = pasta / "corpus.jsonl"
        if not corpus.exists():
            raise FileNotFoundError(f"Corpus nao encontrado: {corpus}")
        self.chunks = [json.loads(l) for l in corpus.read_text(encoding="utf-8").splitlines() if l.strip()]
        from sklearn.feature_extraction.text import TfidfVectorizer
        from scipy import sparse
        textos = [c["texto"] for c in self.chunks]
        self.vetorizador = TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True)
        self.vetorizador.fit(textos)
        self.matriz = sparse.load_npz(pasta / "indice.npz")
        return self


def indexar_corpus_padrao(limite_por_fonte=None):
    chunks = construir_corpus(limite_por_fonte=limite_por_fonte)
    indice = IndiceRAG().indexar(chunks)
    indice.salvar()
    return indice
