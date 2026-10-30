# Solução de problemas

Primeiro passo para qualquer problema: abra `start_debug.bat` e repita a ação. O console e o arquivo `%APPDATA%\Jarvis\logs\jarvis.log` mostram a causa. Tokens e chaves aparecem mascarados no log.

## Instalação

| Sintoma | Causa provável | Solução |
|---|---|---|
| "Python 3.11-3.13 não encontrado" | Python ausente ou fora do PATH | `winget install Python.Python.3.12` e rode `install.bat` de novo |
| Erro ao instalar `vosk`/`PySide6` | Python 32 bits ou versão 3.14+ | Instale Python 3.12 **64 bits** |
| "execução de scripts foi desabilitada" | Política do PowerShell | Use `install.bat` (já passa `-ExecutionPolicy Bypass` só para o instalador) |
| Download do modelo falha | Proxy/firewall | Baixe manualmente `https://alphacephei.com/vosk/models/vosk-model-small-pt-0.3.zip` e extraia em `models\` |

## Voz e microfone

| Sintoma | Solução |
|---|---|
| Indicador MICROFONE vermelho: "Modelo de voz ausente" | Rode `.venv\Scripts\python scripts\download_models.py` |
| Indicador MICROFONE vermelho: "Microfone indisponível" | *Configurações do Windows > Privacidade e segurança > Microfone*: ative **Permitir que aplicativos da área de trabalho acessem o microfone**. Escolha o microfone em Configurações > Ativação |
| Não reage a "Jarvis" | **Calibrar com a minha voz**; aumente a sensibilidade; fale "Jarvis" isolado e com pausa curta; teste com `Ctrl+Alt+J` para separar ativação de reconhecimento |
| Dispara sozinho | Diminua a sensibilidade; remova variantes muito comuns em Configurações > Ativação; use headset; considere Porcupine |
| Entende errado os comandos | Fale mais perto do microfone; modelo grande ou Whisper (Configurações > Ativação); comandos com baixa confiança são confirmados antes de executar |
| Não fala nada | Indicador de atividade mostra "Voz indisponível"? Sem internet a voz neural falha e o JARVIS usa a voz do Windows: instale a voz pt-BR em *Configurações > Hora e idioma > Fala > Adicionar vozes* |
| Fala com voz robótica | Está usando a reserva offline (sem internet ou serviço instável). Volta sozinho para a neural em 2 minutos |
| Responde a si mesmo | Use headset ou reduza o volume da voz; o JARVIS descarta o eco da confirmação inicial |

## Jogos

| Sintoma | Solução |
|---|---|
| Não ouve durante o jogo | Microfone exclusivo do jogo/Discord? Desative "Permitir que aplicativos assumam controle exclusivo" nas propriedades avançadas do microfone (Painel de Som) |
| O som do jogo dispara a escuta | Use headset; diminua a sensibilidade |
| Jogo não abaixa o volume durante a fala | Configurações > Jogos: "Abaixar o som de outros apps" ligado; confira se o modo jogo ativou (indicador MODO JOGO verde). Processo do Storm 4: `NSUNS4.exe`; se a sua versão usar outro nome, veja no Gerenciador de Tarefas e ajuste |
| Atalho não funciona | Outro programa já usa a combinação (o JARVIS avisa em Atividades). Troque em Configurações > Jogos |
| Combinação do controle não funciona | Controles Xbox via XInput apenas. Controle PlayStation: use DS4Windows/Steam Input e mapeie o touchpad para o atalho de teclado |
| Queda de FPS | O JARVIS pausa animações no modo jogo e usa ~1-3% de CPU ao escutar. Se usar Whisper ou Ollama, troque por Vosk / IA na nuvem enquanto joga |

## Microsoft 365

| Sintoma / erro | Solução |
|---|---|
| `AADSTS50011` (redirect URI) | No registro do app: plataforma *Cliente público/nativo* com `http://localhost` |
| `AADSTS7000218` ou falha no "Conectar com código" | Autenticação > **Permitir fluxos de cliente público: Sim** |
| `AADSTS65001` / "aprovação do administrador" | Veja [consentimento do administrador](INTEGRACOES.md#13-consentimento-do-administrador) |
| `AADSTS700016` (aplicativo não encontrado) | ID do aplicativo errado ou locatário errado (`organizations`, `consumers` ou o ID da empresa) |
| Conta pessoal não entra com `common` | Use locatário `consumers` |
| "Sua sessão expirou" | Configurações > Microsoft 365 > Conectar de novo |
| "Caixa de e-mail não disponível para a API" | A caixa não está no Exchange Online |
| Planilha não aparece em "Descobrir" | Use **Adicionar link** (Excel Online > Compartilhar > Copiar link) |
| "Coluna de status não configurada" | Configurações > Planilhas > selecione > Carregar abas e colunas > Aplicar |
| "A célula foi alterada por outra pessoa" | Proteção contra sobrescrever trabalho alheio. Peça a alteração de novo |

## WhatsApp

| Sintoma | Solução |
|---|---|
| Indicador WHATSAPP vermelho "Notificações do Windows inacessíveis" | Precisa existir `%LOCALAPPDATA%\Microsoft\Windows\Notifications\wpndatabase.db`. Ative notificações no Windows (Configurações > Sistema > Notificações) |
| Nunca detecta mensagens | WhatsApp Desktop aberto (ou WhatsApp Web no navegador)? Notificações do WhatsApp ligadas no Windows e dentro do app? |
| Só aparece "conteúdo indisponível" | Ative **Mostrar prévias** nas notificações do WhatsApp |
| WhatsApp Web não detectado | O navegador precisa ter permissão de notificação para web.whatsapp.com. Se o nome do app aparecer diferente, adicione um trecho dele em Configurações > WhatsApp > Identificação do app |
| "Não tenho o número de Fulano" | Cadastre o contato em Configurações > WhatsApp |
| Conversa abre no navegador e não no app | Configurações > WhatsApp > "Abrir conversas no aplicativo" |

## IA

| Sintoma | Solução |
|---|---|
| "Chave da API Anthropic foi recusada" | Gere outra chave em console.anthropic.com e cole em Configurações > IA |
| "Limite de uso da IA atingido" | Limites/créditos da conta Anthropic. Comandos locais continuam |
| "O Ollama não respondeu" | Ollama aberto? `ollama list` mostra o modelo? URL correta? |
| Respostas lentas | Esforço "Baixo"; modelo Haiku; respostas curtas |

## Dados e privacidade

- Ver e apagar dados: Configurações > Privacidade e memória.
- Recomeçar do zero: feche o JARVIS e apague `%APPDATA%\Jarvis`.
- `settings.json` corrompido: o JARVIS salva uma cópia `settings.corrompido.json` e volta aos padrões.
