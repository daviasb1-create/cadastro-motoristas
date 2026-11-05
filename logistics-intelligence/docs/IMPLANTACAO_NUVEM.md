# Implantação na nuvem (roda com o computador desligado)

A automação usa **GitHub Actions** (arquivo `.github/workflows/radar-diario.yml`, na raiz do repositório).
O GitHub executa a pesquisa nos horários definidos, envia os alertas no Telegram e guarda os dados.

## Atenção: o repositório `cadastro-motoristas` é PÚBLICO
Em repositório público, qualquer pessoa pode ver o código, os logs das execuções e os artefatos.
Os dados de leads (nomes, e-mails, telefones) **não podem ficar expostos** (LGPD). Por isso o workflow:
- só funciona se houver um banco externo (`DATABASE_URL`) **ou** uma senha de criptografia (`DB_ENCRYPTION_KEY`);
- não publica planilhas/relatórios como artefato, a menos que você crie a variável `PUBLICAR_ARTEFATOS = sim`.

**Recomendação:** torne o repositório privado (Settings > General > Danger Zone > Change visibility) ou crie um
repositório privado só para este sistema. Em repositório privado o plano gratuito inclui 2.000 minutos/mês de
Actions; o radar usa cerca de 3 a 6 minutos por execução (≈ 600 a 900 minutos/mês).

## Opção A (recomendada): GitHub Actions + PostgreSQL gratuito
O mesmo banco é usado pela nuvem e pelo painel no seu PC: tudo que o robô encontra de madrugada aparece no painel.

1. Crie um banco PostgreSQL gratuito, por exemplo no **Neon** (<https://neon.tech>) ou no **Supabase**
   (<https://supabase.com>). Copie a *connection string* (`postgresql://usuario:senha@host/banco?sslmode=require`).
2. No GitHub: **Settings > Secrets and variables > Actions > New repository secret**:
   - `DATABASE_URL` = a connection string
   - `ANTHROPIC_API_KEY`, `BRAVE_API_KEY` e/ou `SERPER_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
   - (opcional) `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `ALERT_EMAIL_TO`
3. No seu PC, coloque a mesma `DATABASE_URL` no `.env` e abra o painel.
4. Faça o merge deste código no branch **main** (o GitHub só executa agendamentos a partir do branch padrão).
5. Teste agora: aba **Actions > Radar comercial diário > Run workflow**.

## Opção C: GitHub Actions + SQLite criptografado (sem banco externo)
1. Crie o secret `DB_ENCRYPTION_KEY` com uma senha longa (ex.: 40 caracteres aleatórios). Guarde-a.
2. Cadastre as demais chaves (passo 2 acima, sem `DATABASE_URL`).
3. O banco fica no cache do GitHub, criptografado com AES-256 entre as execuções.

Limitação: o painel no seu PC **não** enxerga esses dados. Você recebe os alertas no Telegram com o e-mail e o
WhatsApp prontos. Para ver tudo no painel, use a Opção A.

## Painel acessível de qualquer lugar (opcional)
Com a Opção A, é possível publicar o painel no **Streamlit Community Cloud** (<https://share.streamlit.io>)
apontando para `logistics-intelligence/app.py` e cadastrando `DATABASE_URL` em *Secrets*.
Atenção: o painel não tem login próprio. Publique somente com o app **privado** (opção de visualizadores
restritos do Streamlit Cloud), pois ele exibe dados de contato.

## Horários
GitHub usa UTC. Brasília é UTC-3 (sem horário de verão desde 2019).
| Horário local | cron (UTC) | Tipo |
|---|---|---|
| 07:00 | `0 10 * * *` | completa |
| 12:00 | `0 15 * * *` | completa |
| 17:00 | `0 20 * * *` | completa + relatório diário |
| 09:30 (seg a sex) | `30 12 * * 1-5` | urgente |
| 14:30 (seg a sex) | `30 17 * * 1-5` | urgente |

O GitHub pode atrasar execuções agendadas em 5 a 30 minutos em horários de pico. Para mudar horários, edite o
arquivo `.github/workflows/radar-diario.yml`.

## Falhas e retentativas
- Cada execução tenta até 3 vezes se todas as fontes falharem.
- Fontes com erro ficam marcadas como "indisponível" e aparecem em **Histórico de pesquisas**.
- Se a execução falhar, o GitHub envia e-mail ao dono do repositório (configurável em Settings > Notifications).
