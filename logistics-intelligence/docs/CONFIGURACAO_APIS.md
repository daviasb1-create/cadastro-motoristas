# Configuração das APIs

Nenhuma chave é obrigatória. Sem chaves, o sistema usa as fontes gratuitas (Google Notícias RSS, PNCP,
sites oficiais e BrasilAPI) e textos-modelo. **A qualidade sobe muito com a Claude API e com uma API de busca.**

As chaves ficam no `.env` (local) ou em **Secrets** do GitHub (nuvem). Nunca no código ou no banco.

## Claude API (Anthropic) · recomendada
Uso: entender cada resultado, extrair empresa, rota e evidência, pesquisar a web com fonte verificada e
personalizar os e-mails.
1. Acesse <https://console.anthropic.com>, crie a conta e cadastre um cartão em **Billing**.
2. Em **API Keys > Create Key**, copie a chave (`sk-ant-...`).
3. Cole em `ANTHROPIC_API_KEY`.
4. Em **Limits**, defina um limite mensal de gasto (recomendado).
- Modelo padrão: `claude-opus-5-5`. Para reduzir custo, troque `ANTHROPIC_MODEL` (ex.: `claude-sonnet-5-5`
  ou `claude-haiku-5-5`); a qualidade de extração cai um pouco.

## Brave Search API · busca web, notícias e vagas
1. Acesse <https://api-dashboard.search.brave.com> e crie a conta.
2. Assine um plano de **Search** e gere a chave em **API Keys**.
3. Cole em `BRAVE_API_KEY`.

## Serper.dev · resultados do Google
1. Acesse <https://serper.dev> e crie a conta (há créditos gratuitos iniciais).
2. Copie a chave em **API Key** e cole em `SERPER_API_KEY`.

> Basta uma das duas (Brave ou Serper). Com as duas, a cobertura aumenta.

## Telegram · alertas
1. No Telegram, abra **@BotFather** > `/newbot` > escolha nome e usuário. Copie o token.
2. Cole em `TELEGRAM_BOT_TOKEN`.
3. Envie qualquer mensagem para o seu bot (ou adicione-o a um grupo e mande uma mensagem no grupo).
4. Abra no navegador `https://api.telegram.org/bot<SEU_TOKEN>/getUpdates` e copie o número em `"chat":{"id": ...}`.
5. Cole em `TELEGRAM_CHAT_ID` e use **Configurações > Score e alertas > Enviar alerta de teste**.

## E-mail (SMTP) · alertas para você
Para Microsoft 365: `SMTP_HOST=smtp.office365.com`, `SMTP_PORT=587`, usuário = seu e-mail.
Se a conta tiver MFA, o administrador precisa liberar **SMTP AUTH** para a caixa ou use uma senha de app.
`ALERT_EMAIL_TO` = quem recebe os alertas. Estes e-mails vão só para você, nunca para leads.

## Outlook · rascunhos automáticos (opcional)
Sem configurar nada, o botão **Abrir no Outlook** já abre o Outlook Web com destinatário, assunto e texto.
Para o sistema **criar rascunhos na sua caixa** (sem enviar):
1. Portal Azure > **Microsoft Entra ID > Registros de aplicativo > Novo registro**.
2. Em **Permissões de API > Microsoft Graph > Permissões de aplicativo**, adicione `Mail.ReadWrite` e clique em
   **Conceder consentimento do administrador**.
3. Em **Certificados e segredos**, crie um segredo.
4. Preencha `MS_TENANT_ID`, `MS_CLIENT_ID`, `MS_CLIENT_SECRET` e `MS_SENDER_MAILBOX` (sua caixa).
> Recomendação de segurança: peça ao administrador para restringir o app só à sua caixa
> (Application Access Policy do Exchange).

## Banco PostgreSQL (para usar o mesmo banco no PC e na nuvem)
Ver [IMPLANTACAO_NUVEM.md](IMPLANTACAO_NUVEM.md). Cole a URL em `DATABASE_URL`.

## Fontes sem chave (já ativas)
| Fonte | O que traz |
|---|---|
| Google Notícias (RSS) | expansão, novos CDs, fábricas, inaugurações |
| PNCP | licitações públicas de transporte/frete com proposta aberta em RJ, SP e SC |
| Site oficial da empresa | e-mails, telefones, WhatsApp e LinkedIn publicados (respeita robots.txt) |
| BrasilAPI | dados públicos do CNPJ (razão social, CNAE, endereço, telefone) |
