# JARVIS · Assistente pessoal por voz para Windows 11

Assistente de voz em português do Brasil que fica em segundo plano, atende ao chamado **"Jarvis"**, controla o Windows, acompanha **Outlook**, **Excel Online** e **WhatsApp Business** e funciona durante jogos em tela cheia, sem tocar nos arquivos do jogo.

| O que faz | Como |
|---|---|
| Ativação por voz | Detecção **local** da palavra "Jarvis" (Vosk; Porcupine opcional). O áudio não sai do PC. |
| Entende comandos | Reconhecimento de fala local em pt-BR + interpretador próprio de comandos (sem custo, sem internet). |
| Conversa livre | IA opcional e configurável: Claude (Anthropic API) ou Ollama (local e gratuito). |
| Responde falando | Perfis **JARVIS** (masculino) e **FRIDAY** (feminino) com vozes neurais pt-BR; reserva offline com vozes do Windows. |
| Controla o Windows | Abre/fecha programas e jogos (Menu Iniciar, Microsoft Store, Steam), pastas, janelas, volume, lembretes, arquivos. |
| Outlook | Não lidos, remetentes, resumos, pesquisa, anexos, agenda, rascunhos de resposta; envio só com confirmação. |
| Excel Online | Descobre planilhas, pendências, atrasados, busca, resumos, inconsistências; edição só com prévia, confirmação e auditoria. |
| WhatsApp Business | Lê as notificações do Windows (remetente e prévia), resume, abre conversas, prepara mensagens; nunca envia sozinho. |
| Central de notificações | Une tudo, evita repetição, prioriza importantes, respeita modo jogo e horário silencioso, resume "o que perdi". |
| Jogos | Modo jogo automático (ex.: `NSUNS4.exe`), redução do som do jogo durante a fala, atalhos globais e combinação no controle Xbox. |

## Instalação rápida

1. Instale o **Python 3.12** (marque *Add python.exe to PATH*) ou rode `winget install Python.Python.3.12`.
2. Copie a pasta `jarvis` para o seu computador (ex.: `C:\Users\Voce\Jarvis`).
3. Dê dois cliques em **`install.bat`**. Ele cria o ambiente, instala dependências, baixa o modelo de voz (~31 MB) e cria atalhos.
4. Abra pelo atalho **JARVIS** (ou `start.bat`) e diga: **"Jarvis, que horas são?"**

Detalhes, requisitos e geração do executável: [docs/INSTALACAO.md](docs/INSTALACAO.md).

## Primeiros passos recomendados

1. **Configurações > Ativação > Calibrar com a minha voz** (o modelo aprende como você pronuncia "Jarvis").
2. **Configurações > Jogos**: confira `NSUNS4.exe` e os atalhos (`Ctrl+Alt+S` interrompe a fala; `Ctrl+Alt+J` fala sem a palavra de ativação).
3. **Microsoft 365**: registre o aplicativo gratuito no Entra e conecte a conta ([guia](docs/INTEGRACOES.md#1-microsoft-365-outlook-e-excel-online)).
4. **Planilhas**: "Descobrir" ou "Adicionar link", depois escolha colunas de status e prazo.
5. **WhatsApp**: abra o WhatsApp Desktop com prévia de notificações ligada e cadastre os contatos com número.
6. **IA (opcional)**: escolha Claude ou Ollama para conversas livres.

## Documentação

- [Instalação e executável](docs/INSTALACAO.md)
- [Integrações: Microsoft 365, WhatsApp, IA, vozes](docs/INTEGRACOES.md)
- [Lista de comandos e comandos personalizados](docs/COMANDOS.md)
- [Solução de problemas](docs/SOLUCAO_DE_PROBLEMAS.md)
- [Arquitetura, decisões técnicas e limitações](docs/ARQUITETURA.md)

## Privacidade em uma frase

O microfone é processado no seu PC; só depois de chamado o comando vira texto, e esse texto só vai para a nuvem se você ativar um provedor de IA. Tokens e chaves ficam criptografados pelo Windows; histórico e memória podem ser vistos e apagados em **Configurações > Privacidade e memória**.

## Testes

```bat
run_tests.bat
```
133 testes automatizados cobrem interpretação de comandos, confirmações, Excel, Outlook/Graph, WhatsApp, notificações, ciclo de voz, IA e interface.
