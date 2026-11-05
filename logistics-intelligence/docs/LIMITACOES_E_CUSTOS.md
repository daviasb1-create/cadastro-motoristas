# Limitações, custos e LGPD

## Limitações (o que o sistema NÃO faz)
| Item | Situação | Motivo / alternativa |
|---|---|---|
| LinkedIn | Não faz raspagem | Termos de uso proíbem. O sistema guarda o link da página da empresa quando publicado no site oficial e mostra resultados públicos que aparecem nas APIs de busca. |
| Google Maps / Places | Não implementado na v1 | Exige conta com faturamento e os termos limitam armazenar dados. Pode ser adicionado como nova fonte. |
| Portais de frete com login (ex.: Fretebras) | Não acessa | Área restrita. Pedidos públicos indexados aparecem via Brave/Serper/Claude. |
| Sites de vagas | Só o que é público via APIs de busca | Não raspa Gupy, Indeed etc. diretamente. |
| Envio de mensagens | Nunca envia | Decisão de projeto (LGPD e aprovação humana). |
| Sem chave da Claude | Funciona com heurística | Extração de nome da empresa e categoria fica bem menos precisa. |
| Google Notícias RSS | Uso moderado | É um feed público; o Google pode limitar volume. O sistema faz poucas consultas por execução. |
| Mapa | Coordenadas de ~45 cidades | Cidades fora da lista aparecem no centro do estado (indicado como aproximado). |
| Potencial de faturamento | Só com valores informados | O sistema não inventa faturamento; editais usam o valor oficial do PNCP. |
| Testes em ambiente real | As integrações externas foram testadas com respostas simuladas nos formatos oficiais | A primeira execução real (no seu PC ou no GitHub Actions) valida a conectividade; acompanhe em Histórico de pesquisas. |
| Painel | Sem login | Use localmente ou publique como app privado. |

## Custos estimados (valores de referência; confira sempre o site de cada serviço)
| Serviço | Custo | Consumo padrão do radar |
|---|---|---|
| Google Notícias RSS, PNCP, BrasilAPI, sites oficiais, Telegram | Gratuito | ilimitado na prática |
| GitHub Actions | Grátis em repositório público; 2.000 min/mês grátis em privado | ≈ 600 a 900 min/mês |
| Neon / Supabase (PostgreSQL) | Plano gratuito suficiente | < 100 MB no primeiro ano |
| Claude Opus 5.5 | US$ 4 por milhão de tokens de entrada, US$ 20 de saída; pesquisa web US$ 10 por 1.000 buscas | ver abaixo |
| Brave Search API | plano pago por volume de consultas | até 60 consultas/dia (configurável) |
| Serper.dev | créditos gratuitos iniciais; depois pacotes pré-pagos | até 60 consultas/dia (configurável) |

**Estimativa Claude com os limites padrão** (20 chamadas de IA + 8 buscas web por execução, 3 execuções completas
+ 2 urgentes por dia): cerca de **US$ 2 a 6 por dia** (≈ US$ 60 a 180 por mês) no Opus 5.5. A maior parte vem da
pesquisa web da Claude e da personalização dos e-mails.

Como reduzir:
1. Configurações > Agenda e limites: diminua chamadas de IA e buscas web por execução.
2. Configurações > Fontes: reduza o limite diário de "Claude: pesquisa na web" (padrão 4/dia).
3. Troque `ANTHROPIC_MODEL` para `claude-sonnet-5-5` (cerca de metade do custo) ou `claude-haiku-5-5` (bem mais barato,
   extração menos precisa).
4. Defina um limite de gasto no console da Anthropic.

O consumo real (chamadas, tokens, buscas e custo estimado) aparece em **Histórico de pesquisas > Consumo de APIs**.

## LGPD: como o sistema trata dados
- Finalidade: prospecção B2B (legítimo interesse). Prioriza canais corporativos (e-mails do domínio da empresa,
  telefones comerciais publicados). E-mails de provedores gratuitos são ignorados na coleta automática de sites.
- Cada contato guarda a fonte e o link de origem. Contatos manuais exigem informar a fonte.
- Não coleta dados sensíveis, não acessa áreas restritas, não contorna CAPTCHA e respeita robots.txt.
- **Descadastro:** botão "Descadastrar (LGPD)" na ficha do lead bloqueia abordagens, alertas e follow-ups.
  Se alguém pedir exclusão total, apague a empresa do banco (ou peça suporte técnico).
- Nenhuma mensagem é enviada sem você; o registro de envio exige aprovação explícita.
- Inclua nas suas mensagens uma forma simples de a pessoa pedir para não ser mais contatada, e respeite.
- Credenciais só em variáveis de ambiente, ocultadas na interface e nos logs.
- Repositório público: não publique banco, planilhas ou relatórios. O workflow já impede isso por padrão.
