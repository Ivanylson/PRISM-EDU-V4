import pandas as pd
import numpy as np
from pathlib import Path
import unicodedata
from sklearn.cluster import KMeans
import warnings

warnings.filterwarnings('ignore')

# =============================================================================
# 1. MAPEAMENTO DE CURSOS E FUNÇÕES ÚTEIS
# =============================================================================
cursos_map = {
    5: 'Medicina Veterinária', 6: 'Odontologia', 12: 'Medicina', 17: 'Agronomia',
    19: 'Farmácia', 21: 'Arquitetura e Urbanismo', 23: 'Enfermagem', 27: 'Fonoaudiologia',
    28: 'Nutrição', 36: 'Fisioterapia', 51: 'Zootecnia', 55: 'Biomedicina',
    69: 'Tecnologia em Radiologia', 90: 'Tecnologia em Agronegócios', 
    91: 'Tecnologia em Gestão Hospitalar', 92: 'Tecnologia em Gestão Ambiental',
    95: 'Tecnologia em Estética e Cosmética', 5710: 'Engenharia Civil',
    5806: 'Engenharia Elétrica', 5814: 'Engenharia de Controle e Automação',
    5902: 'Engenharia Mecânica', 6002: 'Engenharia de Alimentos',
    6008: 'Engenharia Química', 6208: 'Engenharia de Produção',
    6307: 'Engenharia Ambiental', 6405: 'Engenharia Florestal',
    6410: 'Tecnologia em Segurança no Trabalho', 6411: 'Engenharia de Computação'
}

def formatar_nome(nome):
    nome = ''.join(ch for ch in unicodedata.normalize('NFKD', nome) if not unicodedata.combining(ch))
    return nome.lower().replace(' ', '_')

def limpar_texto_html(texto):
    if pd.isna(texto):
        return "Não especificado"
    texto = str(texto).replace('\n', ' ').strip()
    return texto

# =============================================================================
# 2. CONFIGURAÇÕES DE CAMINHOS AUTOMÁTICOS
# =============================================================================
print("Configurando diretórios de forma automática...")
DIRETORIO_ATUAL = Path(__file__).resolve().parent
DIRETORIO_RAIZ = DIRETORIO_ATUAL.parent # <--- Volta à raiz do projeto

caminho_microdados = DIRETORIO_RAIZ / 'arquivosgerados' / 'relatorio_final_enade_2023.csv'
pasta_sintese = DIRETORIO_RAIZ / 'arquivosgerados' / 'resultadofinal_relatoriosintese' / 'csv'

# Pasta de saída
pasta_relatorios_ies = DIRETORIO_RAIZ / 'arquivosgerados' / 'RESULTADOS' / 'relatorioIES'
pasta_relatorios_ies.mkdir(parents=True, exist_ok=True)

if not caminho_microdados.exists():
    print(f"\n ERRO: Base de dados principal não encontrada em:\n{caminho_microdados}")
    print("Por favor, execute a Fase 1 primeiro.")
    exit()

print("A carregar a base de dados principal...")
df_micro = pd.read_csv(caminho_microdados, sep=';', dtype=str)
grupos_disponiveis = df_micro['CO_GRUPO'].dropna().unique()

print("A gerar os Rankings por Grupos de IA (K-Means) para cada IES...\n")

# =============================================================================
# 3. MOTOR DE GERAÇÃO: RANKING K-MEANS POR IES (HTML)
# =============================================================================
for co_grupo in grupos_disponiveis:
    co_grupo_int = int(co_grupo)
    
    if co_grupo_int not in cursos_map:
        continue
        
    nome_curso = cursos_map[co_grupo_int]
    nome_formatado = formatar_nome(nome_curso)
    
    caminho_sintese = pasta_sintese / f"{nome_formatado}.csv"
    if not caminho_sintese.exists():
        continue
        
    # CORREÇÃO: Leitura com sep=';' para evitar bugs de separador
    df_sintese = pd.read_csv(caminho_sintese, sep=',')
    if 'POSIÇÃO' in df_sintese.columns:
        df_sintese.rename(columns={'POSIÇÃO': 'QUESTAO'}, inplace=True)
    df_sintese['QUESTAO'] = 'Q' + df_sintese['QUESTAO'].astype(str).str.strip()
    
    colunas_oc = [col for col in df_sintese.columns if str(col).startswith('OC')]
    
    df_curso = df_micro[df_micro['CO_GRUPO'] == str(co_grupo)].copy()
    
    if len(df_curso) < 10: 
        continue 
        
    ies_disponiveis = df_curso['CO_IES'].dropna().unique()
    
    # -------------------------------------------------------------------------
    # CABEÇALHO E ESTILOS CSS DO HTML
    # -------------------------------------------------------------------------
    html_content = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ranking K-Means - {nome_curso}</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; margin: 40px; color: #333; background-color: #f4f7f6; }}
        .container {{ background-color: #fff; padding: 30px; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); }}
        h1 {{ color: #2980b9; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
        h2 {{ color: #2c3e50; margin-top: 30px; }}
        .resumo {{ background-color: #e8f4f8; padding: 15px; border-radius: 8px; margin-bottom: 20px; font-size: 16px; border-left: 5px solid #3498db; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 20px; font-size: 14px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); }}
        th, td {{ padding: 12px 15px; border: 1px solid #ddd; text-align: left; vertical-align: middle; }}
        th {{ background-color: #2c3e50; color: #ffffff; text-transform: uppercase; font-size: 13px; letter-spacing: 0.5px; position: sticky; top: 0; }}
        .linha-ies {{ background-color: #ecf0f1; font-weight: bold; font-size: 18px; text-align: center; color: #2c3e50; }}
        .linha-perfil {{ font-weight: bold; text-align: center; background-color: #fcfcfc; }}
        .perfil-0 {{ color: #27ae60; }} /* Alto Desempenho (Verde) */
        .perfil-1 {{ color: #f39c12; }} /* Intermediário (Laranja) */
        .perfil-2 {{ color: #c0392b; }} /* Risco Crítico (Vermelho) */
        tr:hover {{ background-color: #f1f5f8; transition: background-color 0.3s; }}
        .erro-critico {{ color: #c0392b; font-weight: bold; font-size: 15px; text-align: center; }}
        .centralizado {{ text-align: center; }}
        .posicao {{ font-weight: bold; color: #34495e; }}
        .footer {{ margin-top: 40px; font-size: 13px; color: #7f8c8d; text-align: center; border-top: 1px solid #ddd; padding-top: 15px; font-style: italic; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Ranking de Deficiências por Grupos (IA): {nome_curso}</h1>
        
        <div class="resumo">
            <p><strong>Objetivo:</strong> Este relatório utiliza Inteligência Artificial (K-Means) para dividir os alunos de cada IES em perfis de desempenho e identifica os <strong>2 maiores GAPs (deficiências relativas)</strong> exclusivos de cada grupo.</p>
            <p><strong>Total de Instituições Analisadas:</strong> {len(ies_disponiveis)} | <strong>Total de Alunos:</strong> {len(df_curso)}</p>
        </div>
        
        <table>
            <thead>
                <tr>
                    <th class="centralizado" style="width: 8%;">Código IES</th>
                    <th class="centralizado" style="width: 14%;">Perfil IA</th>
                    <th class="centralizado" style="width: 10%;">Posição / Questão</th>
                    <th class="centralizado" style="width: 8%;">Erro (%)</th>
                    <th class="centralizado" style="width: 8%;">GAP (%)</th>
                    <th style="width: 26%;">Objetos de Conhecimento (Matérias)</th>
                    <th style="width: 26%;">Competência Exigida</th>
                </tr>
            </thead>
            <tbody>
"""
    
    # Roda a análise para CADA IES do curso
    for ies in ies_disponiveis:
        df_ies = df_curso[df_curso['CO_IES'] == ies].copy()
        
        if len(df_ies) < 5:
            continue
            
        cols_questoes = [f'Q{i}' for i in range(1, 39) if f'Q{i}' in df_ies.columns]
        for col in cols_questoes:
            df_ies[col] = np.where(df_ies[col] == '1', 1, 0)
            
        X = df_ies[cols_questoes]
        media_geral_ies = X.mean()
        
        num_perfis = 3 if len(df_ies) >= 10 else 2
        kmeans = KMeans(n_clusters=num_perfis, random_state=42, n_init=10)
        df_ies['PERFIL_IA'] = kmeans.fit_predict(X)
        
        perfis_data = []
        for perfil in range(num_perfis):
            alunos = df_ies[df_ies['PERFIL_IA'] == perfil]
            if len(alunos) == 0: continue
            nota_media = alunos[cols_questoes].sum(axis=1).mean()
            perfis_data.append((perfil, nota_media, alunos))
            
        perfis_data.sort(key=lambda x: x[1], reverse=True)
        
        titulos_perfis = ["Alto Desempenho", "Intermediário", "Risco Crítico"]
        
        # PREPARA OS DADOS DA IES ANTES DE GERAR O HTML (Para calcular os rowspans)
        dados_ies_processados = []
        
        for rank, (perfil_id, nota_media, alunos_grupo) in enumerate(perfis_data):
            nome_perfil = titulos_perfis[rank] if num_perfis == 3 else ("Alto Desempenho" if rank == 0 else "Risco Crítico")
            
            taxa_acertos_grupo = alunos_grupo[cols_questoes].mean()
            diferenca_para_media = taxa_acertos_grupo - media_geral_ies
            
            # Pega as 2 piores questões do grupo (GAPs)
            piores_gaps = diferenca_para_media.nsmallest(2).index.tolist()
            
            questoes_detalhes = []
            for questao in piores_gaps:
                gap_percentual = round(diferenca_para_media[questao] * 100, 1)
                erro_absoluto = round((1 - taxa_acertos_grupo[questao]) * 100, 1)
                
                info_q = df_sintese[df_sintese['QUESTAO'] == questao]
                comp = "Não especificada"
                texto_ocs = "Não especificado"
                
                if not info_q.empty:
                    # Garantir que a coluna "COMPETÊNCIAS" ou "COMPETENCIA" existe
                    if 'COMPETÊNCIAS' in info_q.columns:
                        comp = limpar_texto_html(info_q['COMPETÊNCIAS'].values[0])
                    elif 'COMPETENCIA' in info_q.columns:
                        comp = limpar_texto_html(info_q['COMPETENCIA'].values[0])
                    
                    lista_ocs = []
                    for coluna in colunas_oc:
                        valor_oc = info_q[coluna].values[0]
                        if pd.notna(valor_oc) and str(valor_oc).strip() != "":
                            lista_ocs.append(str(valor_oc).strip())
                    texto_ocs = " + ".join(lista_ocs) if lista_ocs else "Não especificado"
                    texto_ocs = limpar_texto_html(texto_ocs)
                
                questoes_detalhes.append({
                    'questao': questao,
                    'erro': erro_absoluto,
                    'gap': gap_percentual,
                    'ocs': texto_ocs,
                    'comp': comp
                })
                
            dados_ies_processados.append({
                'nome_perfil': nome_perfil,
                'qtd_alunos': len(alunos_grupo),
                'classe_cor': f"perfil-{rank}",
                'questoes': questoes_detalhes
            })
            
        # Calcula quantas linhas no total a IES vai ocupar (Soma de todas as questões de todos os perfis)
        rowspan_total_ies = sum([len(p['questoes']) for p in dados_ies_processados])
        
        if rowspan_total_ies == 0:
            continue
            
        primeira_linha_ies = True
        
        # GERAÇÃO DAS LINHAS HTML
        for perfil_info in dados_ies_processados:
            primeira_linha_perfil = True
            rowspan_perfil = len(perfil_info['questoes'])
            posicao = 1
            
            for q in perfil_info['questoes']:
                html_linha = "<tr>\n"
                
                # Célula da IES (Apenas na primeira linha geral)
                if primeira_linha_ies:
                    html_linha += f'<td rowspan="{rowspan_total_ies}" class="linha-ies">{ies}</td>\n'
                    primeira_linha_ies = False
                
                # Célula do Perfil (Apenas na primeira linha de cada perfil)
                if primeira_linha_perfil:
                    html_linha += f'<td rowspan="{rowspan_perfil}" class="linha-perfil"><span class="{perfil_info["classe_cor"]}">{perfil_info["nome_perfil"]}</span><br><span style="font-size: 12px; font-weight: normal; color: #7f8c8d;">({perfil_info["qtd_alunos"]} alunos)</span></td>\n'
                    primeira_linha_perfil = False
                
                # Células das Questões (Repetem em todas as linhas)
                html_linha += f'<td class="centralizado"><span class="posicao">{posicao}º Pior</span><br><b>{q["questao"]}</b></td>\n'
                html_linha += f'<td class="centralizado">{q["erro"]}%</td>\n'
                html_linha += f'<td class="erro-critico">{q["gap"]}%</td>\n'
                html_linha += f'<td>{q["ocs"]}</td>\n'
                html_linha += f'<td>{q["comp"]}</td>\n'
                
                html_linha += "</tr>\n"
                html_content += html_linha
                posicao += 1

    # Fechamento do HTML
    html_content += """
            </tbody>
        </table>
        <div class="footer">Relatório de Prescrição Educacional gerado automaticamente por motor de IA (K-Means).</div>
    </div>
</body>
</html>
"""
    
    # Guarda o ficheiro
    nome_ficheiro_html = f"{nome_formatado}_ranking_por_grupos_ia.html"
    caminho_html = pasta_relatorios_ies / nome_ficheiro_html
    
    with open(caminho_html, 'w', encoding='utf-8') as file:
        file.write(html_content)
        
    print(f"Ranking HTML gerado: {nome_ficheiro_html}")

print(f"\n{'='*75}")
print(f"PROCESSO CONCLUÍDO! Todos os relatórios HTML foram salvos em:\n{pasta_relatorios_ies}")
print(f"{'='*75}")