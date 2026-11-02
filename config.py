from pathlib import Path
import os
import re
import json

RAIZ_PROJETO = Path(__file__).resolve().parent
RAIZ_EXTERNO = RAIZ_PROJETO.parent

PASTA_DADOS_BRUTOS = RAIZ_PROJETO / "dados" / "brutos"
PASTA_DADOS_PROCESSADOS = RAIZ_PROJETO / "dados" / "processados"
PASTA_INTERNACIONAIS = RAIZ_PROJETO / "dados" / "internacionais"
PASTA_ALGORITMOS = RAIZ_PROJETO / "algoritmos"
PASTA_PROCESSAMENTO = RAIZ_PROJETO / "processamento"
PASTA_DASHBOARD = RAIZ_PROJETO / "dashboard"
PASTA_RELATORIOS = RAIZ_PROJETO / "relatorios"
PASTA_MODELOS = RAIZ_PROJETO / "modelos"
PASTA_TESTES = RAIZ_PROJETO / "testes"

PASTA_SERIE_MICRODADOS = RAIZ_EXTERNO / "seriesTemporais_microdados"
PASTA_SERIE_QUESTOES = RAIZ_EXTERNO / "seriesTemporais_questoes"
PASTA_DADOS_EXTERNOS = PASTA_SERIE_MICRODADOS / "resultados"
PASTA_QUESTOES_EXTERNAS = PASTA_SERIE_QUESTOES / "resultados"
PASTA_MODELO_REFERENCIA = RAIZ_EXTERNO / "modeloprojetoENADE2023"

PASTA_RESULTADOS_ENADE = PASTA_DADOS_EXTERNOS / "enade"
PASTA_RESULTADOS_LICENCIATURAS = PASTA_DADOS_EXTERNOS / "enadeLicenciaturas"
PASTA_RESULTADOS_ENAMED = PASTA_DADOS_EXTERNOS / "enamed"
PASTA_CONSOLIDADO = PASTA_DADOS_EXTERNOS / "relatorio_final_consolidado.csv"

SEPARADOR = ";"
ENCODING = "utf-8"
SEED_ALEATORIA = 42
TAMANHO_CHUNK = 100000
MIN_ALUNOS_POR_IES = 50
K_MIN = 2
K_MAX = 6
N_BOOTSTRAP = 100
ENTROPIA_MINIMA = 0.80
LIMITE_TOP_N = 5

ANOS_ENADE = list(range(2004, 2024))
ANOS_ENADE_SEM_DADOS = [2020]

CURSOS_MAP = {
    5: "Medicina Veterinaria", 6: "Odontologia", 12: "Medicina", 17: "Agronomia",
    19: "Farmacia", 21: "Arquitetura e Urbanismo", 23: "Enfermagem", 27: "Fonoaudiologia",
    28: "Nutricao", 36: "Fisioterapia", 51: "Zootecnia", 55: "Biomedicina",
    69: "Tecnologia em Radiologia", 90: "Tecnologia em Agronegocios",
    91: "Tecnologia em Gestao Hospitalar", 92: "Tecnologia em Gestao Ambiental",
    95: "Tecnologia em Estetica e Cosmetica", 5710: "Engenharia Civil",
    5806: "Engenharia Eletrica", 5814: "Engenharia de Controle e Automacao",
    5902: "Engenharia Mecanica", 6002: "Engenharia de Alimentos",
    6008: "Engenharia Quimica", 6208: "Engenharia de Producao",
    6307: "Engenharia Ambiental", 6405: "Engenharia Florestal",
    6410: "Tecnologia em Seguranca no Trabalho", 6411: "Engenharia de Computacao",
    2001: "Matematica (Licenciatura)", 2501: "Letras - Portugues e Literaturas (Licenciatura)",
    6407: "Letras (Licenciatura)", 904: "Ciencias Biologicas", 905: "Fisica",
    2402: "Quimica", 4301: "Educacao Fisica",
    702: "Letras (Licenciatura)", 906: "Matematica (Licenciatura)",
    1402: "Pedagogia (Licenciatura)", 1502: "Historia (Licenciatura)",
    1602: "Geografia (Licenciatura)", 3002: "Filosofia (Licenciatura)",
    3202: "Ciencias Sociais (Licenciatura)", 3502: "Musica (Licenciatura)",
    4005: "Artes Visuais (Licenciatura)", 5402: "Computacao (Licenciatura)",
}

def _montar_cursos_reversos():
    """Reverso lossless: cada nome de curso aponta para a lista ordenada de
    codigos. Nomes repetidos (ex.: 'Letras (Licenciatura)') nao sao colapsados."""
    reverso = {}
    for cod, nome in CURSOS_MAP.items():
        reverso.setdefault(nome, []).append(int(cod))
    return {nome: sorted(cods) for nome, cods in reverso.items()}


CURSOS_REVERSO = _montar_cursos_reversos()

PASTA_MAP_GRUPOS_POR_ANO = RAIZ_PROJETO / "processamento" / "mapeamento_grupos_enade.json"

def _montar_cursos_map_ano():
    """Mapa CO_GRUPO -> nome por edicao ENADE, extraido dos dicionarios
    oficiais do INEP (fonte da verdade por edicao)."""
    mapa = {}
    caminho = PASTA_MAP_GRUPOS_POR_ANO
    if caminho.exists():
        try:
            mapa = json.loads(caminho.read_text(encoding="utf-8"))
        except Exception:
            mapa = {}
    return mapa


CURSOS_MAP_POR_ANO = _montar_cursos_map_ano()


def _title(nome):
    if not isinstance(nome, str):
        return nome
    palavras = nome.split()
    out = []
    for p in palavras:
        if p.isupper() and len(p) > 1 and not p.isdigit():
            out.append(p[0] + p[1:].lower())
        else:
            out.append(p.capitalize())
    return " ".join(out)


def nome_grupo_ano(g, ano=None):
    """Nome do curso para o codigo CO_GRUPO considerando a edicao (ano).
    Prioriza o dicionario da edicao; cai para CURSOS_MAP (glb) e, por fim,
    para um rotulo generico 'Grupo N'."""
    try:
        cod = int(g)
    except (ValueError, TypeError):
        return f"Grupo {g}"
    if ano is not None:
        grupos_ano = CURSOS_MAP_POR_ANO.get(str(ano), {})
        nome = grupos_ano.get(str(cod))
        if nome:
            return _title(nome)
    return CURSOS_MAP.get(cod, f"Grupo {cod}")

EXAMES_INTERNACIONAIS = {
    "aber_pro": {
        "nome": "Saber Pro (Examen de Estado de Calidad de la Educacion Superior)",
        "pais": "Colombia",
        "sigla": "Pro",
        "cor": "#FCD116",
        "icone": "flag",
        "status": "_dinamico",
        "colunas_esperadas": ["ALUNO", "PAIS", "ANNO", "AREA", "PUNTAJE", "NIVEL"],
        "orgao": "ICFES - Instituto Colombiano para la Evaluacion de la Educacion",
        "tipo_fonte": "Relatorios agregados oficiais (microdados sob solicitacao ao DataIcfes)",
        "fontes": [
            {"nome": "ICFES - Saber Pro", "url": "https://www.icfes.gov.co/web/guest/saber-pro"},
            {"nome": "ICFES - Datos abiertos ICFES", "url": "https://www.icfes.gov.co/investigaciones/data-icfes"},
            {"nome": "ICFES - Resultados agregados PIR", "url": "https://www.icfes.gov.co/publicaciones-icfes/documentos-de-analisis-de-resultados"},
        ],
        "citacao": "ICFES. (2023). Informe nacional de resultados Saber Pro y Saber TyT. Bogota: Instituto Colombiano para la Evaluacion de la Educacion. https://www.icfes.gov.co",
    },
    "egel": {
        "nome": "EGEL (Examen General para el Egreso de la Licenciatura)",
        "pais": "Mexico",
        "sigla": "EGEL",
        "cor": "#006847",
        "icone": "flag",
        "status": "_dinamico",
        "colunas_esperadas": ["ALUNO", "PAIS", "ANNO", "CAMPO", "CALIFICACION", "NIVEL"],
        "orgao": "CENEVAL - Centro Nacional de Evaluacion para la Educacion Superior",
        "tipo_fonte": "Informes anuales de resultados EGEL (agregados)",
        "fontes": [
            {"nome": "CENEVAL - EGEL", "url": "https://ceneval.edu.mx/examenes-egreso-egel/"},
            {"nome": "CENEVAL - Informes anuales EGEL", "url": "https://ceneval.edu.mx/informes-anuales-de-resultados-egel"},
            {"nome": "CENEVAL - Informe Anual de Resultados 2022 (PDF)", "url": "https://ceneval.edu.mx/wp-content/uploads/2023/03/INFORME-ANUAL-DE-RESULTADOS-2022-XXX-Sesion-Ordinaria-de-la-Asamblea-General_2023_DIGITAL.pdf"},
        ],
        "citacao": "CENEVAL. (2023). Informe anual de resultados 2022. Ciudad de Mexico: Centro Nacional de Evaluacion para la Educacion Superior. https://ceneval.edu.mx",
    },
    "teco": {
        "nome": "TECO (Test sulle Competenze)",
        "pais": "Italia",
        "sigla": "TECO",
        "cor": "#008C45",
        "icone": "flag",
        "status": "_dinamico",
        "colunas_esperadas": ["STUDENT", "COUNTRY", "YEAR", "FIELD", "SCORE", "LEVEL"],
        "orgao": "ANVUR - Agenzia Nazionale di Valutazione del Sistema Universitario e della Ricerca",
        "tipo_fonte": "Relatorios TECO In-forma (agregados)",
        "fontes": [
            {"nome": "ANVUR - Pagina TECO", "url": "https://www.anvur.it/en/quality-assurance/study-programmes/university/periodic-assessment/teco"},
            {"nome": "ANVUR - TECO In-forma 2023 (PDF)", "url": "https://www.anvur.it/sites/default/files/2024-11/TECO-In-forma-2023.pdf"},
            {"nome": "ANVUR - Dati e pubblicazioni", "url": "https://www.anvur.it/en/data-and-publications"},
        ],
        "citacao": "ANVUR. (2023). TECO In-forma: indagine sulle competenze degli studenti universitari. Roma: Agenzia Nazionale di Valutazione del Sistema Universitario e della Ricerca. https://www.anvur.it",
    },
    "piaac": {
        "nome": "PIAAC (Programme for the International Assessment of Adult Competencies)",
        "pais": "OECD",
        "sigla": "PIAAC",
        "cor": "#003399",
        "icone": "globe",
        "status": "_dinamico",
        "colunas_esperadas": ["PERSON_ID", "COUNTRY", "YEAR", "DOMAIN", "PROFICIENCY", "SCALE"],
        "orgao": "OECD - Survey of Adult Skills",
        "tipo_fonte": "Microdados abertos (Public Use Files, PUF) em CSV",
        "fontes": [
            {"nome": "OECD - PIAAC 1st Cycle Database", "url": "https://www.oecd.org/en/data/datasets/piaac-1st-cycle-database.html"},
            {"nome": "OECD - PIAAC data e metodologia", "url": "https://www.oecd.org/en/about/programmes/piaac/piaac-data.html"},
            {"nome": "OECD - Servidor de arquivos PUF (CSV)", "url": "https://webfs.oecd.org/piaac/cy1-puf-data/CSV/"},
        ],
        "citacao": "OECD. (2016). The Survey of Adult Skills: Reader's Companion (2nd ed.). Paris: OECD Publishing. Dados PIAAC PUF. https://webfs.oecd.org/piaac/cy1-puf-data/CSV/",
    },
}


def _status_exame_internacional(sigla: str) -> str:
    """Status dinamico baseado no que existe em PASTA_INTERNACIONAIS/<sigla>:
    'disponivel' se houver dados reais na subpasta 'reais',
    'placeholder_simulado' se so houver CSVs de exemplo gerados por
    gerar_placeholders.py, 'aguardando_dados' se vazio."""
    pasta = PASTA_INTERNACIONAIS / sigla.lower()
    if pasta.exists():
        reais = list((pasta / "reais").glob("*.csv")) if (pasta / "reais").exists() else []
        if reais:
            return "disponivel"
        csvs = list(pasta.glob("*.csv"))
        if csvs:
            if any(p.name.startswith("placeholder") for p in csvs):
                return "placeholder_simulado"
            return "disponivel"
    return "aguardando_dados"


for _exame in EXAMES_INTERNACIONAIS.values():
    _exame["status"] = _status_exame_internacional(_exame["sigla"])

MODELOS_OPENCODE = {
    "big-pickle": "Big Pickle",
    "nemotron-3-super-free": "Nemotron 3 Super Free",
    "deepseek-v4-flash-free": "DeepSeek V4 Flash Free",
    "minimax-m2.5-free": "MiniMax M2.5 Free",
    "qwen3.6-plus-free": "Qwen3.6 Plus Free",
}

OPENCODE_SERVER_URL = "http://localhost:4096"
OPENCODE_USERNAME = "opencode"

ABAS_DASHBOARD = [
    "Diagnostico e Prescricao",
    "Fatores de Sucesso (Preditivo)",
    "Validacao + Clustering",
    "Plano de Acao por Perfil",
    "LCA - Classes Latentes",
    "OpenCode + IA Explicativa",
    "Matriz-Q",
    "ML Avancado",
    "Psicometria Computacional",
    "Auditoria de Competencias do Seculo XXI",
    "Simulador Contrafactual",
    "Estudo de Caso (O Paradoxo)",
    "Suporte a Tomada de Decisao Pedagogica",
    "Series Temporais ENADE (2004-2023)",
    "Exames Internacionais",
    "SHAP & XAI Dashboard",
    "Ranking IA por IES (K-Means)",
    "Analises de Tese (E1-E9)",
]


def formatar_nome_curso(nome: str) -> str:
    import unicodedata
    nome = "".join(ch for ch in unicodedata.normalize("NFKD", nome) if not unicodedata.combining(ch))
    return nome.lower().replace(" ", "_")


def caminho_saida_algoritmo(modulo: str, nome_arquivo: str) -> Path:
    pasta = PASTA_MODELOS / modulo
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta / nome_arquivo


def pasta_saida_edicao(modulo: str, edicao: str = "") -> Path:
    """Pasta de saida de um motor com subpasta opcional por edicao.

    Quando o orquestrador por edicao roda os motores, define a variavel de
    ambiente PRISM_EDICAO (ex.: 'enade_2023', 'licenciaturas_2025',
    'enamed_2025'); cada motor, entao, grava em modelos/<modulo>/<edicao>/.
    Sem a variavel, comporta-se como antes (modelos/<modulo>/).
    """
    edicao_ef = edicao or os.environ.get("PRISM_EDICAO") or ""
    pasta = PASTA_MODELOS / modulo
    if edicao_ef:
        pasta = pasta / edicao_ef
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def listar_anos_disponiveis() -> list:
    anos = []
    if PASTA_RESULTADOS_ENADE.exists():
        for p in sorted(PASTA_RESULTADOS_ENADE.iterdir()):
            if p.is_file() and p.suffix == ".csv":
                try:
                    ano = int(p.stem.split("_")[-1])
                    anos.append(ano)
                except (ValueError, IndexError):
                    pass
    return sorted(anos)


def derivar_colunas_questoes(df, max_questoes=None):
    """Q1, Q2, ..., Qn em ordem numerica, considerando apenas itens com alguma
    resposta na base. Edicoes variam: ENADE 28-66 itens, Licenciaturas ~80,
    ENAMED 100. Colunas que sao apenas preenchimento (todas nulas) sao
    descartadas para nao contaminar os modelos."""
    cols = [c for c in df.columns if isinstance(c, str) and re.fullmatch(r"Q\d{1,3}", c)]
    cols = [c for c in cols if df[c].notna().any()]
    cols.sort(key=lambda c: int(c[1:]))
    if max_questoes:
        cols = cols[:max_questoes]
    return cols


def normalizar_coluna_grupo(df, nome_grupo_fallback="0"):
    """Garante uma coluna CO_GRUPO utilizavel para o agrupamento dos motores.

    ENAMED nao possui CO_GRUPO (toda a coluna e nula): deriva de CO_CURSO
    quando existir, caso contrario usa o grupo 0. O retorno e uma copia para
    nao alterar a base carregada."""
    import pandas as pd
    if df is None or df.empty:
        return df
    if "CO_GRUPO" in df.columns and df["CO_GRUPO"].notna().any():
        return df
    df = df.copy()
    if "CO_CURSO" in df.columns and df["CO_CURSO"].notna().any():
        df["CO_GRUPO"] = pd.to_numeric(df["CO_CURSO"], errors="coerce").fillna(0).astype(int)
    else:
        df["CO_GRUPO"] = pd.to_numeric(nome_grupo_fallback, errors="coerce").fillna(0).astype(int)
    return df


def listar_edicoes_disponiveis() -> list:
    """Edicoes com dados: enade_YYYY (2004-2023), licenciaturas_2025,
    enamed_2025."""
    edicoes = []
    if PASTA_RESULTADOS_ENADE.exists():
        for p in sorted(PASTA_RESULTADOS_ENADE.glob("relatorio_final_enade_*.csv")):
            try:
                ano = int(p.stem.split("_")[-1])
            except (ValueError, IndexError):
                continue
            edicoes.append(f"enade_{ano}")
    if PASTA_RESULTADOS_LICENCIATURAS.exists():
        for p in sorted(PASTA_RESULTADOS_LICENCIATURAS.glob("relatorio_final_*.csv")):
            edicoes.append("licenciaturas_2025")
    if PASTA_RESULTADOS_ENAMED.exists():
        for p in sorted(PASTA_RESULTADOS_ENAMED.glob("relatorio_final_*.csv")):
            edicoes.append("enamed_2025")
    return sorted(set(edicoes))


def caminho_arquivo_edicao(edicao: str):
    """Caminho do CSV de microdados da edicao (ex.: 'enade_2019')."""
    if edicao.startswith("enade_"):
        ano = edicao.split("_")[-1]
        caminho = PASTA_RESULTADOS_ENADE / f"relatorio_final_enade_{ano}.csv"
        return caminho if caminho.exists() else None
    if edicao == "licenciaturas_2025":
        caminho = PASTA_RESULTADOS_LICENCIATURAS / "relatorio_final_enade_licenciaturas_2025.csv"
        return caminho if caminho.exists() else None
    if edicao == "enamed_2025":
        caminho = PASTA_RESULTADOS_ENAMED / "relatorio_final_enamed_2025.csv"
        return caminho if caminho.exists() else None
    return None


def pasta_sintese_edicao(edicao: str) -> Path:
    """Pasta com os CSVs de sintese de competencias (OC) por edicao,
    usados pelo motor NLP (TF-IDF). Ex.: dados/processados/questoes."""
    return PASTA_DADOS_PROCESSADOS / "questoes"


def arquivos_sintese_edicao(edicao: str) -> list:
    """CSVs de sintese (OC) da edicao para o motor NLP."""
    pasta = pasta_sintese_edicao(edicao)
    if edicao.startswith("enade_"):
        ano = edicao.split("_")[-1]
        padrao = f"questoes_enade_{ano}_*.csv"
    elif edicao == "licenciaturas_2025":
        padrao = "questoes_enadeLicenciaturas_2025_*.csv"
    elif edicao == "enamed_2025":
        padrao = "questoes_enamed_2025_*.csv"
    else:
        return []
    return sorted(pasta.glob(padrao)) if pasta.exists() else []


def carregar_consolidado():
    import pandas as pd
    pastas = [
        PASTA_DADOS_EXTERNOS / "enade",
        PASTA_DADOS_PROCESSADOS / "por_ano",
    ]
    arquivos = []
    for p in pastas:
        if p.exists():
            arquivos.extend(sorted(p.glob("relatorio_final_enade_*.csv")))
    if not arquivos:
        # Nao ler o CSV consolidado (4GB -> OOM). Sem per-year, nao ha dados.
        return None

    # Concatenar todos os anos estouraria a memoria (~3.8GB) e misturaria
    # bancos de questoes de anos distintos. Retornamos UM ano representativo
    # (o mais recente) para que os algoritmos rodem em memoria de forma segura.
    ano_mais_recente = None
    def _ano(caminho):
        try:
            return int(caminho.stem.split("_")[-1])
        except (ValueError, IndexError):
            return None
    tmp = []
    for f in arquivos:
        a = _ano(f)
        if a is not None:
            tmp.append((a, f))
    if not tmp:
        return None
    ano_mais_recente, arquivo = max(tmp, key=lambda x: x[0])
    print(f"  [carregar_consolidado] Usando ano mais recente: {ano_mais_recente} ({arquivo.name})")
    return pd.read_csv(arquivo, sep=SEPARADOR, encoding=ENCODING, low_memory=False)


def iterar_edicoes_dados(edicoes=None, n_alunos_max=None):
    """Itera as edicoes disponiveis (memoria leve, uma por vez).

    Para cada edicao define a variavel PRISM_EDICAO (usada por
    pasta_saida_edicao para gravar em modelos/<motor>/<edicao>/) e entrega o
    DataFrame da edicao. Nunca concatena edicoes (evita o CSV consolidado de
    ~4GB/OOM). Uso:
        for edicao, df in iterar_edicoes_dados():
            executar_motor(df=df)
    """
    import os
    if edicoes is None:
        edicoes = listar_edicoes_disponiveis()
    selecao = os.environ.get("PRISM_EDICOES", "").strip()
    if selecao and selecao.lower() != "all":
        sels = {s for s in selecao.split(",") if s.strip()}
        edicoes = [e for e in edicoes if e in sels]
    for edicao in edicoes:
        caminho = caminho_arquivo_edicao(edicao)
        if caminho is None:
            print(f"  [iterar_edicoes_dados] Sem arquivo para {edicao}, pulando.")
            continue
        os.environ["PRISM_EDICAO"] = edicao
        try:
            import pandas as pd
            df = pd.read_csv(caminho, sep=SEPARADOR, encoding=ENCODING, low_memory=False)
            if n_alunos_max and len(df) > n_alunos_max:
                print(f"    Amostrando {n_alunos_max} de {len(df)} alunos de {edicao}.")
                df = df.sample(n_alunos_max, random_state=SEED_ALEATORIA)
            yield edicao, df
            del df
        except Exception as exc:
            print(f"  [iterar_edicoes_dados] ERRO na edicao {edicao}: {exc}")
    os.environ.pop("PRISM_EDICAO", None)


def carregar_por_ano(ano: int):
    import pandas as pd
    caminho = PASTA_RESULTADOS_ENADE / f"relatorio_final_enade_{ano}.csv"
    if caminho.exists():
        return pd.read_csv(caminho, sep=SEPARADOR, encoding=ENCODING, low_memory=False)
    return None
