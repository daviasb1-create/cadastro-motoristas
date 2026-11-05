# LOGISTICS INTELLIGENCE · Radar Comercial de Transportes

Plataforma de inteligência comercial da **Ícaro Express**. Todos os dias ela pesquisa empresas que podem
contratar transporte rodoviário, transferências RJ ↔ SP ↔ Joinville, distribuição urbana, last mile e
operações dedicadas. Também identifica os contatos publicados, pontua cada oportunidade com justificativa
e deixa **e-mail e WhatsApp prontos para revisar, copiar e enviar**.

> Nenhuma mensagem é enviada automaticamente. Você revisa, aprova e envia.

---

## Início rápido (Windows 11)

1. Instale o **Python 3.12** em <https://www.python.org/downloads/> e marque **"Add python.exe to PATH"**.
2. Baixe esta pasta (`logistics-intelligence`).
3. Dê dois cliques em **`iniciar_windows.bat`**. Na primeira vez, ele instala tudo (3 a 5 minutos).
4. O painel abre no navegador em `http://localhost:8501`.
5. Em **10. Configurações**, preencha os dados da Ícaro Express, sua assinatura e as credenciais.
6. Clique em **▶ Executar pesquisa agora** na Visão geral.

O guia completo está em [docs/INSTALACAO_WINDOWS.md](docs/INSTALACAO_WINDOWS.md).

## Como fica rodando todo dia

| Opção | Funciona com o PC desligado? | Painel vê os dados? | Guia |
|---|---|---|---|
| **A. GitHub Actions + PostgreSQL gratuito (recomendado)** | Sim | Sim (mesmo banco) | [docs/IMPLANTACAO_NUVEM.md](docs/IMPLANTACAO_NUVEM.md) |
| B. Agendador local no Windows | Não | Sim | [docs/INSTALACAO_WINDOWS.md](docs/INSTALACAO_WINDOWS.md) |
| C. GitHub Actions + SQLite criptografado | Sim | Não (só alertas no Telegram) | [docs/IMPLANTACAO_NUVEM.md](docs/IMPLANTACAO_NUVEM.md) |

Horários padrão (America/Sao_Paulo): pesquisa completa às **07:00, 12:00 e 17:00** e monitor de urgentes às
**09:30 e 14:30** (dias úteis). O relatório diário sai na execução das 17:00.

## O que o sistema faz

1. **Pesquisa** em fontes permitidas: Google Notícias (RSS), PNCP (licitações oficiais), Brave Search,
   Serper (Google), pesquisa web da Claude com fonte verificada e feeds RSS que você adicionar.
2. **Deduplica** empresas por CNPJ, domínio do site e nome normalizado + UF.
3. **Extrai** a oportunidade com IA (ou heurística, sem chave). Nome, contato, volume e rota só entram se
   estiverem escritos na fonte. O que não existe aparece como "Não identificado".
4. **Enriquece**: visita o site oficial (respeitando robots.txt) e coleta e-mails e telefones corporativos;
   consulta o CNPJ na base pública da Receita (BrasilAPI).
5. **Pontua de 0 a 100** em 10 critérios explicados (o porte da empresa não conta ponto).
6. **Gera a abordagem**: escolhe um dos 13 modelos, personaliza com IA sem inventar fatos e prepara o WhatsApp.
7. **Alerta** no Telegram/e-mail (CRÍTICO, ALTO, NORMAL), sem repetir a mesma oportunidade.
8. **Acompanha** o CRM: 12 etapas, notas, conversas, follow-ups de 3, 5 e 7 dias e reativação em 15 e 30 dias.

A lista completa está em [docs/FUNCIONALIDADES.md](docs/FUNCIONALIDADES.md).

## Comandos úteis

```bash
streamlit run app.py                         # painel
python run_pipeline.py                       # pesquisa completa agora
python run_pipeline.py --mode urgente        # só oportunidades urgentes
python run_pipeline.py --excel leads.xlsx    # pesquisa + exporta Excel
python scheduler_service.py                  # agendador local (07h, 12h, 17h)
python -m pytest -q tests                    # testes
```

## Documentação

- [Instalação no Windows 11](docs/INSTALACAO_WINDOWS.md)
- [Configuração das APIs (como obter cada chave)](docs/CONFIGURACAO_APIS.md)
- [Execução local e rotina diária de uso](docs/EXECUCAO_LOCAL.md)
- [Implantação na nuvem (GitHub Actions)](docs/IMPLANTACAO_NUVEM.md)
- [Arquitetura e como adicionar fontes](docs/ARQUITETURA.md)
- [Funcionalidades implementadas](docs/FUNCIONALIDADES.md)
- [Limitações, custos e LGPD](docs/LIMITACOES_E_CUSTOS.md)
