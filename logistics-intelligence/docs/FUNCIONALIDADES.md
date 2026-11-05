# Funcionalidades implementadas (versão 1.0)

## Pesquisa e radar
- [x] Pesquisa automática 3x ao dia + monitor de urgentes (local com APScheduler ou nuvem com GitHub Actions)
- [x] Fontes: Google Notícias RSS, PNCP (licitações), Brave Search, Serper/Google, pesquisa web da Claude, RSS personalizados
- [x] Consultas geradas das Configurações (demanda explícita, expansão, vagas de logística, segmentos x regiões), rotacionadas
- [x] Fonte modular: ativar/desativar, limite diário, indicador de indisponibilidade, falhas seguidas
- [x] Categorias: empresa com potencial, transferência, urgente, urbana/last mile, licitação
- [x] Rotas detectadas só quando o texto declara o trajeto (sem dedução)
- [x] Itens já vistos não são reprocessados (economia de API)

## Inteligência e enriquecimento
- [x] Extração por IA com JSON Schema + validação anti-invenção em código
- [x] Heurística de reserva quando a IA não está configurada ou falha
- [x] Contatos do site oficial (e-mail, telefone, WhatsApp, LinkedIn) com URL de origem, respeitando robots.txt
- [x] CNPJ validado por dígito verificador e consultado na base pública (BrasilAPI/Receita)
- [x] Fonte registrada por campo ("Fonte" na ficha do lead) e "Não identificado" quando ausente
- [x] Deduplicação por CNPJ, domínio e nome normalizado + UF; novas descobertas viram histórico

## Pontuação
- [x] 0 a 100 com 10 critérios, justificativa por critério e 4 faixas de prioridade; porte não pontua

## Painel (Streamlit, tema escuro)
- [x] 11 telas: Visão geral, Radar de empresas, Radar de transferências, Urgentes, Banco de leads, Pipeline, Mapa,
      Central de abordagem, Relatórios, Configurações, Histórico de pesquisas
- [x] 16 indicadores (empresas, novos do dia, qualificados, urgentes, transferências, urbanas, sem contato,
      follow-ups vencidos, negociação, conversão, potencial ponderado, valor de editais) e gráficos por estado,
      segmento, prioridade, fonte, evolução semanal e mensal, funil
- [x] Botão de execução manual imediata (em segundo plano)

## CRM
- [x] 12 etapas, histórico completo, notas, conversas, responsável, potencial mensal, cotação, rotas,
      próximo contato, motivo de perda (obrigatório), cadastro manual de leads e contatos (com fonte)
- [x] Pipeline por etapas com movimentação e potencial ponderado

## Abordagem comercial
- [x] E-mail e WhatsApp gerados automaticamente para cada novo lead (score ≥ mínimo configurável)
- [x] 13 modelos de e-mail + 2 de WhatsApp, editáveis; escolha automática do modelo por perfil
- [x] Personalização por IA com travas: sem fatos novos, sem simular contato prévio, assinatura preservada,
      sem e-mails novos no texto, sem travessão
- [x] Botões: Copiar e-mail, Copiar assunto, Copiar mensagem completa, Abrir no Outlook (Web), mailto,
      Rascunho no Outlook via Graph (opcional), Copiar mensagem WhatsApp, Abrir conversa no WhatsApp,
      Copiar telefone, Registrar contato realizado
- [x] Aprovação humana obrigatória para registrar envio ou criar rascunho
- [x] Central de abordagem com os 8 filtros pedidos

## Follow-up
- [x] Agenda automática de 3, 5 e 7 dias + reativação 15 e 30 dias (prazos editáveis)
- [x] Nova mensagem gerada para cada etapa vencida; sem duplicar texto ou etapa
- [x] Resposta da empresa cancela follow-ups; listas de alertas comerciais na Central

## Alertas
- [x] Telegram (prioritário) e e-mail SMTP; níveis CRÍTICO, ALTO e NORMAL; score mínimo; limite por execução
- [x] Sem repetição (1 por oportunidade e canal), com e-mail e WhatsApp prontos no alerta
- [x] Relatório diário enviado na execução das 17:00

## Relatórios
- [x] Excel com 8 abas (+ histórico do funil) e relatório diário com resumo executivo e ações sugeridas

## Operação, segurança e LGPD
- [x] Retentativas, logs em arquivo e banco, histórico de erros, consumo de API e custo estimado
- [x] Credenciais só em `.env`/Secrets, mascaradas na tela e removidas dos logs
- [x] Descadastro (opt-out) bloqueia abordagens e follow-ups
- [x] Banco criptografado no cache da nuvem; artefatos desligados por padrão em repositório público
- [x] 34 testes automatizados
