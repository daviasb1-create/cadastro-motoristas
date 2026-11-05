"""Valores padrão editáveis pelo painel de Configurações.

Tudo aqui é gravado no banco na primeira execução e, a partir daí, o que vale
é o que estiver salvo no banco (editável pela interface).
"""
from __future__ import annotations

UFS = ["AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA",
       "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"]

CRM_STATUSES = [
    "Novo lead",
    "Pesquisando contato",
    "Contato identificado",
    "Primeiro contato realizado",
    "Aguardando resposta",
    "Cotação solicitada",
    "Cotação enviada",
    "Em negociação",
    "Teste operacional",
    "Contrato fechado",
    "Perdido",
    "Reativação futura",
]

# Probabilidade de fechamento por etapa (usada na estimativa de faturamento ponderado)
STAGE_PROBABILITY = {
    "Novo lead": 0.02, "Pesquisando contato": 0.03, "Contato identificado": 0.05,
    "Primeiro contato realizado": 0.08, "Aguardando resposta": 0.08, "Cotação solicitada": 0.25,
    "Cotação enviada": 0.35, "Em negociação": 0.5, "Teste operacional": 0.7,
    "Contrato fechado": 1.0, "Perdido": 0.0, "Reativação futura": 0.02,
}

OPPORTUNITY_CATEGORIES = {
    "empresa": "Empresa com potencial logístico",
    "transferencia": "Transferência / rota recorrente",
    "urgente": "Oportunidade urgente",
    "urbana": "Distribuição urbana / last mile",
    "licitacao": "Licitação pública",
}

SERVICE_TYPES = [
    "Transporte rodoviário de cargas", "Transferência entre estados/filiais",
    "Distribuição urbana", "Distribuição regional", "Entregas B2B", "Last mile",
    "Operação dedicada", "Cargas volumosas (móveis/eletros)", "Carga de retorno",
]

DEFAULT_SETTINGS: dict = {
    "empresa": {
        "nome": "Ícaro Express",
        "site": "",
        "telefone": "",
        "email": "",
        "cidade_base": "Rio de Janeiro - RJ",
        "apresentacao_curta": (
            "transportadora rodoviária com operação em Rio de Janeiro, São Paulo e Joinville, "
            "atendendo transferências entre filiais, distribuição urbana e regional, entregas B2B "
            "e cargas volumosas"
        ),
        "diferenciais": (
            "frota de leves a carreta (Fiorino, HR, Bongo, VUC, 3/4, truck e carreta), "
            "operação recorrente ou sob demanda e acompanhamento próximo de cada entrega"
        ),
    },
    "comercial": {
        "nome": "",
        "cargo": "Comercial",
        "telefone": "",
        "email": "",
        "assinatura": "{nome}\n{cargo} | {empresa}\n{telefone}\n{email}",
    },
    "regioes": {
        "estados": ["RJ", "SP", "SC"],
        "estados_conexao": ["MG", "PR", "ES", "RS"],
        "cidades_prioritarias": [
            "Rio de Janeiro", "Duque de Caxias", "Nova Iguaçu", "São Gonçalo", "Niterói",
            "Itaguaí", "Queimados", "Resende", "São Paulo", "Guarulhos", "Barueri", "Osasco",
            "Cajamar", "Jundiaí", "Campinas", "São Bernardo do Campo", "Embu das Artes",
            "Joinville", "Itajaí", "Navegantes", "Jaraguá do Sul", "Blumenau", "Araquari",
        ],
    },
    "rotas": [
        {"origem": "RJ", "destino": "SP", "ativa": True, "obs": "Transferência recorrente"},
        {"origem": "SP", "destino": "RJ", "ativa": True, "obs": "Transferência recorrente"},
        {"origem": "SP", "destino": "SC", "ativa": True, "obs": "SP ↔ Joinville"},
        {"origem": "SC", "destino": "SP", "ativa": True, "obs": "Joinville ↔ SP"},
        {"origem": "RJ", "destino": "SC", "ativa": True, "obs": "RJ ↔ Joinville"},
        {"origem": "SC", "destino": "RJ", "ativa": True, "obs": "Joinville ↔ RJ"},
    ],
    "segmentos": [
        "Indústria", "Fabricante", "Distribuidor", "Atacadista", "Importador", "E-commerce",
        "Varejo", "Móveis", "Eletrodomésticos", "Materiais de construção", "Equipamentos",
        "Operador logístico", "Autopeças", "Alimentos e bebidas", "Cosméticos", "Farmacêutico",
    ],
    "veiculos": ["Fiorino", "HR", "Bongo", "VUC", "3/4", "Truck", "Carreta"],
    "score": {"minimo_alerta": 60, "minimo_abordagem": 40},
    "agenda": {
        "pesquisas": ["07:00", "12:00", "17:00"],
        "monitor_urgente": ["09:30", "14:30"],
        "max_tentativas": 3,
    },
    "followup": {"dias": [3, 5, 7], "reativacao": [15, 30]},
    "alertas": {
        "telegram": True,
        "email": False,
        "niveis": ["CRITICO", "ALTO", "NORMAL"],
        "max_por_execucao": 15,
    },
    "limites": {
        "max_chamadas_ia_por_execucao": 20,
        "max_enriquecimentos_por_execucao": 15,
        "max_buscas_web_ia_por_execucao": 8,
        "itens_por_lote_ia": 8,
    },
    "pesquisa": {
        "termos_demanda": [
            "cotação de frete", "contratar transportadora", "busca transportadora",
            "parceiro logístico", "cadastro de transportadoras", "homologação de transportadoras",
        ],
        "termos_expansao": [
            "novo centro de distribuição", "inaugura centro de distribuição", "nova fábrica",
            "amplia operação logística", "novo CD", "nova unidade",
        ],
        "termos_vagas": [
            "vaga analista de logística", "vaga coordenador de transportes",
            "vaga supervisor de expedição", "vaga comprador de fretes",
        ],
        "termos_licitacao": [
            "transporte", "frete", "logística", "distribuição", "mudança", "carga",
        ],
    },
}

# Biblioteca de modelos comerciais (editável no painel).
# Variáveis: {saudacao} {empresa} {servico} {contexto} {rota} {regioes} {remetente_empresa}
# {apresentacao} {diferenciais} {remetente_nome} {assinatura} {cargo_contato} {quem_fala}
DEFAULT_TEMPLATES: list[dict] = [
    {
        "key": "apresentacao_inicial", "nome": "1. Apresentação inicial", "canal": "email",
        "assunto": "Transporte de cargas para a {empresa}",
        "corpo": (
            "{saudacao}\n\n{contexto}Sou da {remetente_empresa}, {apresentacao}.\n\n"
            "Entrei em contato porque acredito que podemos apoiar a {empresa} em {servico}. "
            "Trabalhamos com {diferenciais}.\n\n"
            "Faz sentido conversarmos 15 minutos nesta semana para eu entender como funciona a "
            "operação de vocês hoje?\n\nAtenciosamente,\n{assinatura}"
        ),
    },
    {
        "key": "industria", "nome": "2. Prospecção de indústria", "canal": "email",
        "assunto": "Transferências e distribuição para a {empresa}",
        "corpo": (
            "{saudacao}\n\n{contexto}Sou da {remetente_empresa}. Atendemos indústrias no "
            "{regioes} com transferências entre fábrica, depósitos e filiais, além de "
            "distribuição para clientes B2B.\n\nPara a {empresa}, vejo espaço para apoiar em "
            "{servico}, com veículos dimensionados para cada tipo de carga e programação "
            "recorrente ou sob demanda.\n\nQuem seria a pessoa ideal para tratar de transporte "
            "aí na {empresa}? Se for você, posso enviar uma proposta inicial?\n\n"
            "Atenciosamente,\n{assinatura}"
        ),
    },
    {
        "key": "ecommerce", "nome": "3. Prospecção de e-commerce", "canal": "email",
        "assunto": "Entregas e distribuição para a {empresa}",
        "corpo": (
            "{saudacao}\n\n{contexto}Sou da {remetente_empresa} e trabalhamos com distribuição "
            "urbana, entregas B2B e last mile no {regioes}, incluindo cargas volumosas.\n\n"
            "Podemos apoiar a {empresa} em {servico}, seja como operação principal ou como "
            "reforço em picos de demanda.\n\nVocês estão avaliando parceiros de entrega neste "
            "momento?\n\nAtenciosamente,\n{assinatura}"
        ),
    },
    {
        "key": "transferencias", "nome": "4. Transferências interestaduais", "canal": "email",
        "assunto": "Transferências {rota} para a {empresa}",
        "corpo": (
            "{saudacao}\n\n{contexto}Sou da {remetente_empresa}. Operamos transferências "
            "recorrentes entre Rio de Janeiro, São Paulo e Joinville, com saídas programadas "
            "e veículos de leve a carreta.\n\nSe a {empresa} movimenta mercadorias entre "
            "unidades ou centros de distribuição nessas regiões, podemos assumir {servico} com "
            "rota dedicada ou compartilhada.\n\nQual é hoje a frequência dessas transferências? "
            "Com essa informação consigo montar uma proposta objetiva.\n\n"
            "Atenciosamente,\n{assinatura}"
        ),
    },
    {
        "key": "distribuicao_urbana", "nome": "5. Distribuição urbana", "canal": "email",
        "assunto": "Distribuição urbana para a {empresa}",
        "corpo": (
            "{saudacao}\n\n{contexto}Sou da {remetente_empresa}. Fazemos distribuição urbana e "
            "regional com Fiorino, HR, VUC e 3/4, com roteirização diária e comprovante de "
            "entrega.\n\nPodemos apoiar a {empresa} em {servico}.\n\nVocês trabalham hoje com "
            "frota própria, terceirizada ou uma combinação das duas?\n\n"
            "Atenciosamente,\n{assinatura}"
        ),
    },
    {
        "key": "operacao_dedicada", "nome": "6. Operação dedicada", "canal": "email",
        "assunto": "Operação dedicada de transporte para a {empresa}",
        "corpo": (
            "{saudacao}\n\n{contexto}Sou da {remetente_empresa}. Estruturamos operações "
            "dedicadas, com veículos e motoristas fixos para a rotina do cliente, indicadores de "
            "prazo e um ponto de contato único.\n\nPara a {empresa}, isso pode atender "
            "{servico}.\n\nTeria disponibilidade para uma conversa rápida para eu entender o "
            "volume e a rotina atual?\n\nAtenciosamente,\n{assinatura}"
        ),
    },
    {
        "key": "cadastro_transportadora", "nome": "7. Cadastro como transportadora", "canal": "email",
        "assunto": "Cadastro da {remetente_empresa} como transportadora da {empresa}",
        "corpo": (
            "{saudacao}\n\n{contexto}Sou da {remetente_empresa}, {apresentacao}.\n\n"
            "Gostaríamos de participar do processo de cadastro/homologação de transportadoras "
            "da {empresa}. Podemos enviar a documentação necessária e uma apresentação da "
            "operação.\n\nPoderia me indicar o procedimento ou a pessoa responsável?\n\n"
            "Atenciosamente,\n{assinatura}"
        ),
    },
    {
        "key": "followup_1", "nome": "8. Follow-up após primeiro contato", "canal": "email",
        "assunto": "Re: Transporte de cargas para a {empresa}",
        "corpo": (
            "{saudacao}\n\nRetomando meu contato anterior sobre {servico} para a {empresa}.\n\n"
            "Sei que a rotina é corrida. Se fizer sentido, posso enviar uma proposta com base em "
            "uma rota ou volume de exemplo, sem compromisso.\n\nQual seria o melhor caminho?\n\n"
            "Atenciosamente,\n{assinatura}"
        ),
    },
    {
        "key": "followup_apresentacao", "nome": "9. Follow-up após apresentação", "canal": "email",
        "assunto": "Apresentação {remetente_empresa}: alguma dúvida?",
        "corpo": (
            "{saudacao}\n\nConseguiu avaliar a apresentação da {remetente_empresa} que enviei?\n\n"
            "Se houver alguma rota ou demanda específica em análise, monto uma cotação para "
            "comparação com o que vocês praticam hoje.\n\nPosso contar com um retorno até o fim "
            "da semana?\n\nAtenciosamente,\n{assinatura}"
        ),
    },
    {
        "key": "reativacao", "nome": "10. Reativação de contato", "canal": "email",
        "assunto": "{empresa}: transporte para os próximos meses",
        "corpo": (
            "{saudacao}\n\nConversamos há algum tempo sobre {servico}. Como o planejamento "
            "logístico costuma mudar ao longo do ano, queria saber se surgiu alguma nova demanda "
            "de transporte na {empresa}.\n\nSe for útil, continuo à disposição para uma cotação."
            "\n\nAtenciosamente,\n{assinatura}"
        ),
    },
    {
        "key": "resposta_cotacao", "nome": "11. Resposta a solicitação de cotação", "canal": "email",
        "assunto": "Cotação de transporte: {empresa}",
        "corpo": (
            "{saudacao}\n\n{contexto}A {remetente_empresa} tem interesse em participar desta "
            "cotação. Atuamos com {diferenciais}.\n\nPara fecharmos o valor com precisão, "
            "poderia confirmar: origem e destino, tipo e peso/volume da carga, frequência e "
            "data de início?\n\nAtenciosamente,\n{assinatura}"
        ),
    },
    {
        "key": "gestor_logistica", "nome": "12. Apresentação para gestor de logística", "canal": "email",
        "assunto": "{remetente_empresa}: apoio em transporte para a {empresa}",
        "corpo": (
            "{saudacao}\n\n{contexto}Como você responde pela logística da {empresa}, achei "
            "pertinente apresentar a {remetente_empresa}: {apresentacao}.\n\nPodemos apoiar em "
            "{servico}, inclusive como transportadora de contingência para picos e rotas "
            "específicas.\n\nVocê teria 15 minutos nos próximos dias para conversarmos?\n\n"
            "Atenciosamente,\n{assinatura}"
        ),
    },
    {
        "key": "followup_final", "nome": "13. Follow-up final (encerramento cordial)", "canal": "email",
        "assunto": "Encerrando por agora: {empresa}",
        "corpo": (
            "{saudacao}\n\nComo não tive retorno, imagino que transporte não seja prioridade para a "
            "{empresa} neste momento, e está tudo bem.\n\nVou deixar meu contato abaixo. Se surgir "
            "alguma demanda de {servico}, é só me chamar que respondo no mesmo dia.\n\n"
            "Atenciosamente,\n{assinatura}"
        ),
    },
    {
        "key": "whatsapp_inicial", "nome": "WhatsApp: primeiro contato", "canal": "whatsapp",
        "assunto": "",
        "corpo": (
            "{saudacao_curta} {quem_fala}. Trabalhamos com "
            "{servico_curto} no {regioes}. {contexto_curto}Vocês estão avaliando parceiros de "
            "transporte no momento?"
        ),
    },
    {
        "key": "whatsapp_followup", "nome": "WhatsApp: follow-up", "canal": "whatsapp",
        "assunto": "",
        "corpo": (
            "{saudacao_curta} {quem_fala}. Passando para "
            "retomar o contato sobre {servico_curto}. Posso te enviar uma proposta rápida?"
        ),
    },
]

# Etapas de follow-up -> modelo usado
FOLLOWUP_STAGES = {
    "primeiro_contato": {"label": "1º contato", "template": None},
    "fu_1": {"label": "Follow-up 1", "template": "followup_1"},
    "fu_2": {"label": "Follow-up 2", "template": "followup_apresentacao"},
    "fu_3": {"label": "Follow-up 3", "template": "followup_final"},
    "reativacao_1": {"label": "Reativação 1", "template": "reativacao"},
    "reativacao_2": {"label": "Reativação 2", "template": "apresentacao_inicial"},
}
