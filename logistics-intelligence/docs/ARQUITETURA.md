# Arquitetura

```
logistics-intelligence/
├── app.py                    # painel Streamlit (menu com 11 telas)
├── run_pipeline.py           # execução por linha de comando (agendador, GitHub Actions)
├── scheduler_service.py      # agendador local (APScheduler, America/Sao_Paulo)
├── config/                   # settings.py (ambiente/credenciais) e defaults.py (padrões editáveis, 15 modelos)
├── database/                 # models.py (17 tabelas SQLAlchemy) e db.py (conexão, configurações)
├── modules/
│   ├── search/               # fontes: google_news, pncp, brave, serper, claude_web, rss_custom + registry
│   ├── enrichment/           # extractor (IA/heurística + validação anti-invenção), website, cnpj
│   ├── lead_scoring/         # pontuação 0-100 explicável
│   ├── crm/                  # service (empresas, leads, status, follow-ups, LGPD) e approach (rascunhos)
│   ├── email_generator/      # e-mails + links Outlook/mailto + rascunho via Microsoft Graph
│   ├── whatsapp_generator/   # mensagens curtas + link wa.me
│   ├── alerts/               # Telegram, SMTP e despacho sem repetição
│   ├── scheduler/            # pipeline (orquestração com retentativas)
│   ├── reports/              # consultas, relatório diário e Excel (8 abas)
│   └── ai/                   # cliente Claude (saída estruturada, pesquisa web, fallback de recusa)
├── services/                 # http (robots.txt, retentativas), logger (oculta segredos), textutil, usage, timeutil
├── dashboard/                # telas, componentes, tema escuro
├── tests/                    # 34 testes automatizados (sem rede, sem custo)
└── docs/
```

## Fluxo de uma execução
1. **Coleta:** cada fonte ativa gera consultas a partir de Configurações > Pesquisa, rotacionadas a cada execução.
2. **Filtro:** resultados já vistos (tabela `itens_vistos`) são ignorados, o que evita gastar API duas vezes.
   Resultados sem sinal logístico são descartados.
3. **Extração:** a Claude recebe lotes de 8 resultados e devolve JSON validado por schema. Depois, regras em código
   descartam empresa que não aparece no texto, contato que não está na fonte, volume sem número citado e site que
   não corresponde. Sem chave, uma heurística por palavras-chave faz o trabalho (com qualidade menor).
4. **Persistência:** deduplicação (CNPJ > domínio > nome normalizado + UF), oportunidade com impressão digital
   única, rota detectada, lead e histórico "descoberta".
5. **Enriquecimento:** site oficial (até 4 páginas, robots.txt) e CNPJ público.
6. **Pontuação** e atualização do status automático (Novo lead > Pesquisando contato > Contato identificado).
7. **Abordagem:** um rascunho por lead + canal + etapa; textos idênticos não se repetem.
8. **Follow-ups vencidos** recebem nova mensagem para a etapa.
9. **Alertas** (1 por oportunidade e canal) e **relatório diário**.

## Banco de dados
Tabelas: `empresas`, `leads`, `contatos`, `oportunidades`, `fontes`, `rotas`, `pesquisas`, `historico`,
`pipeline`, `followups`, `notificacoes`, `configuracoes`, `logs_execucao`, `mensagens`, `modelos`,
`consumo_api`, `itens_vistos`. SQLite por padrão; PostgreSQL definindo `DATABASE_URL` (mesmo código).

## Como adicionar uma fonte
1. Crie `modules/search/minha_fonte.py` com uma classe que herda `BaseSource` e implementa
   `search(ctx) -> list[RawResult]`. Use `services.http` (timeout, retentativas) e `self.track()` a cada chamada.
2. Registre em `modules/search/registry.py` (`SOURCE_CLASSES` e `SOURCE_DEFINITIONS`).
3. Ela aparece em Configurações > Fontes, com limite diário e ativação.

## Pontuação (máximo 100)
| Critério | Máx. |
|---|---|
| Evidência concreta de demanda | 20 |
| Compatibilidade regional | 15 |
| Transferência interestadual | 10 |
| Potencial de recorrência | 10 |
| Urgência (prazo/publicação) | 10 |
| Acesso ao contato | 10 |
| Potencial de volume (só com base informada) | 10 |
| Veículos compatíveis | 5 |
| Viabilidade operacional | 5 |
| Aproveitamento de rotas | 5 |

80 a 100 prioritária · 60 a 79 qualificada · 40 a 59 em observação · 0 a 39 baixa.
Cada oportunidade guarda a justificativa de cada critério (botão "Ver por que..." nos radares).
