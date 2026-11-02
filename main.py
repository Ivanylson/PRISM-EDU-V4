import os
import sys
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))


def executar_script(pasta: str, nome_arquivo: str):
    caminho = BASE_DIR / pasta / nome_arquivo
    print(f"\n{'='*60}")
    print(f"  INICIANDO: {nome_arquivo} (pasta: {pasta})")
    print(f"{'='*60}")
    if not caminho.exists():
        print(f"  ERRO: '{nome_arquivo}' nao encontrado em '{pasta}'.")
        input("  ENTER para continuar...")
        return
    try:
        subprocess.run([sys.executable, str(caminho)], check=True)
        print(f"  OK: {nome_arquivo} finalizado.")
    except subprocess.CalledProcessError:
        print(f"  ERRO: Falha ao executar {nome_arquivo}.")
        input("  ENTER para continuar...")


def abrir_dashboard():
    caminho = BASE_DIR / "dashboard" / "app.py"
    print(f"\n{'='*60}")
    print(f"  ABRINDO DASHBOARD PRISM-EDU")
    print(f"{'='*60}")
    if not caminho.exists():
        print(f"  Dashboard nao encontrado em: {caminho}")
        input("  ENTER para continuar...")
        return
    try:
        subprocess.run([sys.executable, "-m", "streamlit", "run", str(caminho)])
    except Exception as e:
        print(f"  ERRO ao abrir dashboard: {e}")
        input("  ENTER para continuar...")


def executar_motores_por_edicao():
    print("\n" + "=" * 60)
    print("  MOTORES 5-11 POR EDICAO (memoria leve)")
    print("  Uma edicao por vez; saida em modelos/<motor>/<edicao>/")
    print("=" * 60)
    print("  Edicoes disponiveis:")
    print("    all                 = ENADE 2004-2023 + Licenciaturas 2025 + ENAMED 2025")
    print("    enade               = apenas ENADE 2004-2023")
    print("    licenciaturas       = apenas Licenciaturas 2025")
    print("    enamed              = apenas ENAMED 2025")
    sel = input("  Edicoes [all]: ").strip() or "all"
    if sel == "enade":
        edicoes = ",".join([f"enade_{a}" for a in range(2004, 2024)])
    elif sel == "licenciaturas":
        edicoes = "licenciaturas_2025"
    elif sel == "enamed":
        edicoes = "enamed_2025"
    else:
        edicoes = "all"
    motores = input("  Motores (ex.: all | clustering,shap,som) [all]: ").strip() or "all"
    comando = [sys.executable, str(BASE_DIR / "executar_por_edicao.py"), "--edicoes", edicoes, "--motores", motores]
    try:
        subprocess.run(comando, check=True)
        print("\n  MOTORES POR EDICAO FINALIZADOS!")
    except subprocess.CalledProcessError as e:
        print(f"  ERRO ao executar motores por edicao: {e}")
    input("  ENTER para voltar ao menu...")


def menu_ia_avancada():
    while True:
        os.system("cls" if os.name == "nt" else "clear")
        print("\n" + "=" * 60)
        print("  IA AVANCADA (PRISM-EDU)")
        print("=" * 60)
        print("  1. Ontologia educacional (JSON-LD + Turtle)")
        print("  2. RAG local - indexar corpus (TF-IDF)")
        print("  3. RAG local - consultar")
        print("  4. Prompt-tuning + avaliacao de IA (dataset)")
        print("  5. Analises de tese E1-E9 (microdados)")
        print("  6. Validar servidor MCP")
        print("  7. Gerar relatorio de tese (.docx)")
        print("  0. Voltar")
        print("-" * 60)
        op = input("  Selecione uma opcao: ").strip()
        if op == "1":
            subprocess.run([sys.executable, str(BASE_DIR / "processamento" / "gerar_ontologia.py")], check=False)
        elif op == "2":
            subprocess.run([sys.executable, str(BASE_DIR / "processamento" / "analise_rag.py"), "indexar"], check=False)
        elif op == "3":
            pergunta = input("  Pergunta: ").strip()
            if pergunta:
                subprocess.run([sys.executable, str(BASE_DIR / "processamento" / "analise_rag.py"),
                                "consultar", pergunta], check=False)
            input("  ENTER para continuar...")
        elif op == "4":
            subprocess.run([sys.executable, str(BASE_DIR / "processamento" / "avaliar_ia.py"), "tudo"], check=False)
        elif op == "5":
            subprocess.run([sys.executable, str(BASE_DIR / "processamento" / "analises_tese.py")], check=False)
        elif op == "6":
            subprocess.run([sys.executable, str(BASE_DIR / "processamento" / "validar_mcp.py")], check=False)
        elif op == "7":
            subprocess.run([sys.executable, str(BASE_DIR / "processamento" / "md_para_docx.py"),
                            str(BASE_DIR / "documentacao" / "PRISM-EDU_Relatorio_Tese.md"),
                            str(BASE_DIR / "documentacao" / "PRISM-EDU_Relatorio_Tese.docx")], check=False)
        elif op == "0":
            break
        else:
            print("  Opcao invalida!")
            input("  ENTER para continuar...")
        if op in ("1", "2", "4", "5", "6", "7"):
            input("  ENTER para continuar...")


def menu():
    while True:
        os.system("cls" if os.name == "nt" else "clear")
        print("\n  PRISM-EDU - Plataforma de IA Educacional")
        print("  Dados: ENADE 2004-2023 | Licenciaturas 2025 | ENAMED 2025")
        print("  Algoritmos: LCA | SHAP | XAI | K-Means | CDM | LightGBM | NLP | SOM")
        print("-" * 60)
        print("  1. Pre-processamento de Microdados (Serie Temporal)")
        print("  2. Pre-processamento de Questoes")
        print("  3. Cruzamento de Dados")
        print("  4. Analises Exploratorias (EDA)")
        print("  5. Motor de IA - Clustering (K-Means + GMM + Hierarquico)")
        print("  6. Motor de IA - LCA (Classes Latentes)")
        print("  7. Motor de IA - Preditivos (LightGBM + XGBoost)")
        print("  8. Motor de IA - SHAP & XAI")
        print("  9. Motor de IA - CDM/DINA")
        print(" 10. Motor de IA - Psicometria (SOM + Grafos)")
        print(" 11. Motor de IA - NLP (TF-IDF)")
        print("     (etapas 5-11 processam TODAS as edicoes: ENADE 2004-2023 | Lic 2025 | ENAMED 2025)")
        print("-" * 60)
        print(" 12. RODAR TUDO (Pipeline Completo)")
        print(" 13. ABRIR DASHBOARD INTERATIVO")
        print(" 14. GERAR RELATORIOS")
        print(" 15. MOTORES POR EDICAO (memoria leve - todas as edicoes)")
        print(" 16. IA AVANCADA (ontologia | RAG | prompt-tuning | analises de tese | MCP)")
        print("  0. Sair")
        print("-" * 60)

        escolha = input("  Selecione uma opcao: ")

        if escolha == "1":
            executar_script("processamento", "preprocessador_microdados.py")
        elif escolha == "2":
            executar_script("processamento", "preprocessador_questoes.py")
        elif escolha == "3":
            executar_script("processamento", "cruzamento_dados.py")
        elif escolha == "4":
            executar_script("processamento", "analises_exploratorias.py")
        elif escolha == "5":
            executar_script("algoritmos/clustering", "validacao.py")
        elif escolha == "6":
            executar_script("algoritmos/lca", "pipeline_lca.py")
        elif escolha == "7":
            executar_script("algoritmos/preditivos", "batalha_modelos.py")
        elif escolha == "8":
            executar_script("algoritmos/shap", "shap_analysis.py")
        elif escolha == "9":
            executar_script("algoritmos/cdm", "dina_em.py")
            executar_script("algoritmos/cdm", "ponte_lca_cdm.py")
            executar_script("algoritmos/cdm", "perfil_aluno_oc.py")
        elif escolha == "10":
            executar_script("algoritmos/psicometria", "som_kohonen.py")
        elif escolha == "11":
            executar_script("algoritmos/nlp", "tfidf_analise.py")
        elif escolha == "12":
            print("\n  Executando pipeline completo...")
            for pasta, script in [
                ("processamento", "preprocessador_microdados.py"),
                ("processamento", "preprocessador_questoes.py"),
                ("processamento", "cruzamento_dados.py"),
                ("processamento", "analises_exploratorias.py"),
                ("algoritmos/clustering", "validacao.py"),
                ("algoritmos/lca", "pipeline_lca.py"),
                ("algoritmos/preditivos", "batalha_modelos.py"),
                ("algoritmos/shap", "shap_analysis.py"),
            ]:
                executar_script(pasta, script)
            print("\n  PIPELINE COMPLETO FINALIZADO!")
            input("  ENTER para voltar ao menu...")
        elif escolha == "13":
            abrir_dashboard()
        elif escolha == "14":
            executar_script("relatorios", "gerador_html.py")
        elif escolha == "15":
            executar_motores_por_edicao()
        elif escolha == "16":
            menu_ia_avancada()
        elif escolha == "0":
            print("  Encerrando...")
            break
        else:
            print("  Opcao invalida!")
            input("  ENTER para continuar...")


if __name__ == "__main__":
    menu()
