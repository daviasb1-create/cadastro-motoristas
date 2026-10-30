# Arquitetura

## Visão geral

```
 Microfone ──► VAD (energia) ──► Palavra de ativação LOCAL ──► Captura do comando (+pré-roll)
                                     (Vosk ou Porcupine)          │
                                                                  ▼
                                                   Reconhecimento LOCAL pt-BR (Vosk/Whisper)
                                                                  │ texto + confiança
                                                                  ▼
 Texto digitado ─────────────────────────────────────►  Assistente (orquestrador)
                                                         1. confirmação pendente (sim/não)
                                                         2. resposta a pergunta anterior
                                                         3. referências de contexto
                                                         4. interpretador local (regras pt-BR)
                                                         5. IA opcional (Claude/Ollama) com ferramentas
                                                                  │
                                                                  ▼
                                               Registro de ações (risco: safe / confirm / blocked)
          ┌───────────────┬───────────────┬──────────┼───────────┬──────────────┬──────────────┐
       Windows          Volume        Lembretes   Outlook      Excel        WhatsApp     Central de
 (apps, janelas, pastas) (Core Audio)   (SQLite)   (Graph)      (Graph)  (notificações)  notificações
                                                                  │
                                                                  ▼
                                    Resposta ──► Fala (fila, interrupção, redução do som do jogo)
                                             └─► Interface (eventos via ponte Qt) e bandeja
```

Todos os módulos conversam por um **barramento de eventos**; a interface só assina eventos. Isso permite rodar o mesmo núcleo com interface, em modo texto (`--cli`) ou nos testes.

## Decisões técnicas

| Necessidade | Escolha | Alternativas consideradas | Motivo |
|---|---|---|---|
| Linguagem | Python 3.12 | C#/.NET 8 | Melhor ecossistema de voz local (Vosk, Porcupine, Whisper) e IA; integração Windows via ctypes/pycaw sem perda real de desempenho para este caso |
| Interface | PySide6 (Qt 6) | WinUI 3, Electron, pywebview | Nativa, leve (~60 MB RAM), bandeja do sistema embutida, animação por QPainter que **para** quando a janela está oculta |
| Palavra de ativação | Vosk com gramática restrita + calibração | Porcupine, openWakeWord | Gratuito e sem conta; "Jarvis" isolado (openWakeWord só tem "hey jarvis"). Porcupine fica como opção mais precisa |
| Reconhecimento de fala | Vosk pt-BR (local, streaming) | Whisper local, nuvem | Latência baixa e privacidade; o resultado sai assim que a fala termina. Whisper opcional para precisão |
| Interpretação | Regras pt-BR locais + IA opcional | Só IA | Comandos frequentes sem custo, sem internet e em milissegundos |
| Síntese de voz | Fish Audio (voz escolhida, streaming WAV) com reservas edge-tts e SAPI; Azure opcional | Piper, só SAPI | Melhor qualidade pt-BR gratuita; reserva offline garante resposta |
| Microsoft 365 | Graph REST + MSAL (PKCE) + msal-extensions (DPAPI) | COM do Outlook desktop, IMAP | Oficial, funciona com Outlook/Excel **online**, permissões mínimas por escopo |
| WhatsApp | Leitura das notificações do Windows + links oficiais | API Cloud da Meta, automação do WhatsApp Web | Único método gratuito, local e dentro dos termos para a conta comum |
| Segredos | Gerenciador de Credenciais (keyring) / DPAPI | Arquivo de configuração | Nada sensível em texto simples |
| Armazenamento | SQLite local | Arquivos JSON | Consultas, retenção e limpeza por tabela |

## Desempenho

- Silêncio não aciona reconhecimento (VAD por energia); detector de ativação roda só durante fala.
- Frases de confirmação pré-geradas: "Às suas ordens" toca sem rede e sem espera.
- Comando dito numa frase só ("Jarvis, abre o navegador") não espera confirmação: o áudio anterior à detecção (pré-roll de 1,2 s) entra no reconhecimento.
- Execução de comandos numa thread própria; a escuta continua (permite "Jarvis, pare" no meio da fala).
- Animação a 30 fps apenas com janela visível; zero com janela oculta, minimizada ou em modo jogo.
- Controle Xbox: leitura a 15 Hz com controle conectado, a cada 2 s sem controle.
- Falhas de internet: Graph tenta de novo com espera crescente e responde com mensagem clara; voz cai para a offline; comandos locais seguem.

## Segurança

| Requisito | Implementação |
|---|---|
| Nada de comando de terminal por voz | Só ações registradas; tipo `command` apenas para atalhos escritos pelo usuário |
| Confirmação antes de enviar/alterar | Ações `confirm`, prévia de destinatário/conteúdo/valor antigo e novo; e-mail sai de rascunho; WhatsApp só abre a conversa preenchida |
| Proteção contra reconhecimento errado | Confiança abaixo do limite: repete o que entendeu e pede "sim"; mudança de assunto descarta confirmação pendente |
| Credenciais | Tokens MSAL com DPAPI; chaves no Gerenciador de Credenciais; logs com mascaramento |
| Permissões mínimas | Escopos Graph por função ativada; nenhum privilégio de administrador no Windows |
| Transparência | Indicadores de microfone/estado, histórico de atividades, auditoria do Excel, tela de privacidade com visualizar/apagar |
| Jogo | Nenhuma injeção, leitura de memória ou alteração de arquivos do jogo; só APIs públicas do Windows (sessões de áudio, XInput, RegisterHotKey) |

## Estrutura de diretórios

```
jarvis/
├── jarvis/
│   ├── app.py                 inicialização e ligação dos componentes
│   ├── core/                  configuração, eventos, SQLite, segredos, logs, caminhos
│   ├── nlu/                   normalização, números/horas por extenso, regras de comandos
│   ├── brain/                 orquestrador, contexto, IA, frases
│   ├── actions/               ações do Windows, volume, lembretes, controle, comandos personalizados
│   ├── integrations/          Microsoft Graph (auth, Outlook, Excel), roteirização, WhatsApp, Spotify, notificações
│   ├── notifications/         central de notificações
│   ├── audio/                 microfone, VAD, ativação, reconhecimento, síntese, reprodução, ducking
│   ├── voice/                 ciclo de voz (estados, pré-roll, interrupção, continuação)
│   ├── gaming/                modo jogo, atalhos globais, controle Xbox
│   ├── platform/              APIs nativas do Windows, atalhos .lnk, Steam
│   └── ui/                    janela, núcleo animado, bandeja, configurações
├── tests/                     175 testes automatizados (pytest)
├── scripts/                   instalação, modelo de voz, ícone, executável
├── installer/                 instalador Inno Setup
├── config/                    exemplo de configuração sem segredos
└── docs/                      documentação
```

## Situação por etapa

| Etapa | Implementado | Testado aqui | Depende de você |
|---|---|---|---|
| 1. Núcleo | Interface, bandeja, autostart, ativação, reconhecimento, perfis de voz, comandos do Windows | Lógica, interface (render), ciclo de voz com áudio simulado | Testar microfone real e calibrar |
| 2. Jogos | Modo jogo, interrupção, silencioso, ducking, atalhos, controle | Regras, combinações, atalhos (parser) | Testar no Storm 4 em tela cheia |
| 3. Outlook | Login, leitura, resumos, pesquisa, anexos, agenda, rascunhos, envio confirmado, aviso de novos | Com respostas simuladas do Graph | Registrar app e conectar conta |
| 4. Excel | Descoberta, link, pendências, atrasadas, busca, resumo, inconsistências, edição auditada, criação | Com respostas simuladas do Graph | Configurar planilhas e colunas |
| 5. WhatsApp | Notificações, remetentes, resumo, abrir conversa, preparar mensagem | Com banco de notificações simulado | WhatsApp Desktop com prévias, contatos |
| 6. Central | Unificação, deduplicação, importância, silêncio, histórico, resumo, memória, comandos personalizados | Sim | Preferências |
| 7. Finalização | Testes, scripts, executável e instalador configurados | Testes; executável não gerado (exige Windows) | Rodar `build_exe.ps1` se quiser .exe |

O ambiente de desenvolvimento usado foi Linux sem acesso à internet externa: microfone real, vozes neurais, download do modelo e APIs da Microsoft não puderam ser exercitados aqui. As chamadas a essas bibliotecas foram conferidas no código-fonte delas e cobertas por testes com dublês; a validação final acontece no seu Windows.

## Limitações conhecidas

- "Jarvis" não é palavra do português: a precisão da ativação com Vosk depende da calibração. Porcupine resolve melhor esse ponto.
- O modelo Vosk pequeno erra mais com ruído; Whisper/modelo grande melhoram com mais CPU.
- Leitura do WhatsApp limitada ao que aparece nas notificações; formato do banco do Windows não é oficial.
- Em tela cheia exclusiva, a janela do JARVIS não aparece sobre o jogo (por design do Windows); voz e áudio funcionam normalmente.
- Fechar "o Outlook" quando ele é uma aba do navegador não é feito (o JARVIS não fecha abas por segurança).
- A edição de planilhas por frase livre ("muda o status da nota X") exige IA ativa; consultas funcionam sem IA.
