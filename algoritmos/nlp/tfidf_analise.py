"""
Analise TF-IDF para textos de relatorios sintese educacionais.
Extração de topicos e padroes textuais.
"""
import pandas as pd
import numpy as np
from pathlib import Path
import sys
import re

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config import SEPARADOR, ENCODING, CURSOS_MAP, formatar_nome_curso, caminho_saida_algoritmo, pasta_saida_edicao


def limpar_texto(texto):
    if pd.isna(texto):
        return ""
    texto = str(texto).lower()
    texto = re.sub(r"[^\w\s]", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    stopwords_pt = {
        "de", "a", "o", "que", "e", "do", "da", "em", "um", "para", "com", "nao",
        "uma", "os", "no", "se", "na", "por", "mais", "as", "dos", "como", "mas",
        "foi", "ao", "ele", "das", "tem", "seu", "sua", "ou", "ser", "quando",
        "muito", "ha", "nos", "ja", "estao", "voce", "tambem", "me", "ate",
        "los", "les", "del", "las", "the", "and", "of", "to", "in", "for",
    }
    palavras = [p for p in texto.split() if p not in stopwords_pt and len(p) > 2]
    return " ".join(palavras)


def calcular_tfidf(textos, top_n=20):
    vocabulario = {}
    for texto in textos:
        for palavra in set(texto.split()):
            vocabulario[palavra] = vocabulario.get(palavra, 0) + 1

    n_docs = len(textos)
    df_termo = {p: count for p, count in vocabulario.items()}
    tfidf_resultados = []

    for texto in textos:
        palavras = texto.split()
        if not palavras:
            tfidf_resultados.append({})
            continue
        tf = {}
        for p in palavras:
            tf[p] = tf.get(p, 0) + 1
        total = len(palavras)
        tfidf = {}
        for p, tf_val in tf.items():
            idf = np.log(n_docs / (df_termo.get(p, 1) + 1))
            tfidf[p] = (tf_val / total) * idf
        tfidf_resultados.append(tfidf)

    return tfidf_resultados, vocabulario


def executar_nlp(pasta_sintese=None):
    print("=" * 60)
    print("  PRISM-EDU: Analise NLP (TF-IDF)")
    print("=" * 60)

    if pasta_sintese is None:
        pasta_sintese = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if pasta_sintese is None:
        print("  Processando TODAS as edicoes (memoria leve, uma por vez)...")
        from config import listar_edicoes_disponiveis, arquivos_sintese_edicao
        import os as _os
        edicoes = listar_edicoes_disponiveis()
        selecao = _os.environ.get("PRISM_EDICOES", "").strip()
        if selecao and selecao.lower() != "all":
            sels = {s for s in selecao.split(",") if s.strip()}
            edicoes = [e for e in edicoes if e in sels]
        processada = False
        for edicao in edicoes:
            sintese = arquivos_sintese_edicao(edicao)
            if not sintese:
                continue
            _os.environ["PRISM_EDICAO"] = edicao
            print(f"\n  --- EDICAO: {edicao.upper()} ---")
            executar_nlp(pasta_sintese=sintese)
            processada = True
        if not processada:
            print("  Nenhuma pasta de sintese encontrada. Pulando NLP.")
        _os.environ.pop("PRISM_EDICAO", None)
        return

    if isinstance(pasta_sintese, (list, tuple)):
        csvs = [Path(p) for p in pasta_sintese if Path(p).exists()]
    else:
        pasta_sintese = Path(pasta_sintese)
        if not pasta_sintese.exists():
            print("  Pasta de sintese nao encontrada. Pulando NLP.")
            return
        csvs = list(pasta_sintese.glob("*.csv"))
    if not csvs:
        print("  Nenhum CSV de sintese encontrado.")
        return

    print(f"  Processando {len(csvs)} arquivos de sintese...")
    pasta_saida = pasta_saida_edicao("nlp")
    pasta_saida.mkdir(parents=True, exist_ok=True)

    todos_tfidf = []
    for arq in csvs:
        nome_curso = arq.stem.replace("_conteudo", "")
        df = pd.read_csv(arq, sep=SEPARADOR, encoding=ENCODING, on_bad_lines="skip")
        if "OC1" not in df.columns and "OC_unificado" not in df.columns:
            continue

        col_texto = "OC1" if "OC1" in df.columns else "OC_unificado"
        textos = df[col_texto].apply(limpar_texto)
        textos_filtrados = textos[textos.str.len() > 5]

        if len(textos_filtrados) == 0:
            continue

        tfidf_scores, vocab = calcular_tfidf(textos_filtrados.tolist())

        palavras_importantes = {}
        for scores in tfidf_scores:
            for p, s in scores.items():
                palavras_importantes[p] = palavras_importantes.get(p, 0) + s

        top_palavras = sorted(palavras_importantes.items(), key=lambda x: x[1], reverse=True)[:20]

        df_tfidf = pd.DataFrame(top_palavras, columns=["Palavra", "Score_TFIDF"])
        csv_tfidf = pasta_saida / f"tfidf_{formatar_nome_curso(nome_curso)}.csv"
        df_tfidf.to_csv(csv_tfidf, index=False, sep=SEPARADOR, encoding=ENCODING)
        todos_tfidf.append({"curso": nome_curso, "n_palavras": len(vocab), "top5": [p for p, _ in top_palavras[:5]]})

    if todos_tfidf:
        df_resumo = pd.DataFrame(todos_tfidf)
        print(f"\n  Resumo:")
        for _, row in df_resumo.iterrows():
            print(f"    {row['curso']}: {row['n_palavras']} termos, top={row['top5']}")

    print(f"\n  NLP finalizado!")


if __name__ == "__main__":
    executar_nlp()
