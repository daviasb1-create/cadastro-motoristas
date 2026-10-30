# Integrações

Resumo do que depende de você e do custo de cada parte:

| Integração | O que você precisa fazer | Custo |
|---|---|---|
| Voz e comandos locais | Nada além da instalação | Gratuito, offline |
| Vozes neurais (JARVIS/FRIDAY) | Nada (padrão) | Gratuito, exige internet |
| Microsoft 365 (Outlook/Excel) | Registrar um aplicativo no Entra (uma vez) e conectar a conta | Gratuito |
| WhatsApp Business | Usar o WhatsApp Desktop com notificações e prévia ligadas | Gratuito |
| IA na nuvem (Claude) | Criar chave na Anthropic | Pago por uso |
| IA local (Ollama) | Instalar o Ollama e baixar um modelo | Gratuito (usa CPU/RAM/GPU) |
| Porcupine (ativação mais precisa) | Criar AccessKey gratuita na Picovoice | Gratuito para uso pessoal |
| Azure AI Speech (voz oficial) | Criar recurso Speech no Azure | Cota gratuita mensal; depois pago |

---

## 1. Microsoft 365 (Outlook e Excel Online)

> O Outlook vem **desligado**. Com ele desligado, o login pede só `User.Read` e `Files.ReadWrite.All` (planilhas). Ligue em **Configurações > Microsoft 365** quando o TI aprovar o acesso a e-mail e agenda.

O JARVIS usa a **API oficial Microsoft Graph** com login OAuth 2.0 (PKCE) na página da própria Microsoft. A senha nunca passa pelo JARVIS. Os tokens ficam em `%APPDATA%\Jarvis\msal_token_cache.bin`, criptografados pela DPAPI do Windows.

### 1.1 Registrar o aplicativo (uma vez, ~5 minutos)

Desde junho de 2024 a Microsoft exige que novos registros de aplicativo fiquem dentro de um **diretório (tenant)**.

- **Conta corporativa** (e-mail da empresa no Microsoft 365): registre no diretório da empresa, se a política permitir que usuários registrem aplicativos. Se a opção estiver bloqueada, peça ao TI (passo 1.3).
- **Conta pessoal** (outlook.com/hotmail): crie um diretório gratuito pelo Programa de Desenvolvedores do Microsoft 365 ou por uma conta Azure gratuita, e registre lá aceitando contas pessoais.

Passos:

1. Acesse <https://entra.microsoft.com> > **Identidade** > **Aplicativos** > **Registros de aplicativo** > **Novo registro**.
2. Nome: `JARVIS pessoal`.
3. Tipos de conta:
   - conta corporativa: *Contas somente neste diretório organizacional*;
   - conta pessoal: *Contas em qualquer diretório organizacional e contas pessoais da Microsoft*.
4. URI de redirecionamento: plataforma **Cliente público/nativo (celular e área de trabalho)**, valor `http://localhost`.
5. Clique em **Registrar** e copie o **ID do aplicativo (cliente)**.
6. Menu **Autenticação** > *Configurações avançadas* > **Permitir fluxos de cliente público: Sim** (necessário para o login com código).
7. Menu **Permissões de API** > *Adicionar permissão* > **Microsoft Graph** > **Permissões delegadas**:
   - `User.Read`
   - `Mail.ReadWrite` (ler e criar rascunhos)
   - `Mail.Send` (envio, sempre com sua confirmação)
   - `Calendars.ReadWrite` (ler e criar/remarcar compromissos, sempre com confirmação)
   - `Files.ReadWrite.All` (planilhas suas e compartilhadas com você)

Se você já tinha conectado a conta antes desta versão, conecte de novo para liberar a criação de compromissos (a permissão mudou de leitura para leitura e escrita).

Desmarque em **Configurações > Microsoft 365** as funções que não quiser; o JARVIS pede só os escopos das funções ativas.

### 1.2 Conectar no JARVIS

1. **Configurações > Microsoft 365**: cole o ID do aplicativo.
2. Locatário (*tenant*):
   - conta corporativa: `organizations` ou o *ID do diretório* da empresa (mostrado na página do aplicativo);
   - conta pessoal: `consumers` (há relatos de falha com `common` para contas pessoais).
3. **Conectar (navegador)**. Se o navegador não abrir, use **Conectar com código** (abre microsoft.com/devicelogin e mostra o código).
4. Os indicadores **OUTLOOK** e **EXCEL** ficam verdes.

### 1.3 Consentimento do administrador

Algumas empresas bloqueiam o consentimento de usuários. Sintoma: erro `AADSTS65001` ou tela "Precisa da aprovação do administrador". Solução: o administrador abre o aplicativo no Entra > **Permissões de API** > **Conceder consentimento do administrador**. Alternativa: desativar `Mail.Send` e `Files.ReadWrite.All` reduz o pedido a permissões mais simples.

Requisitos da conta: a caixa de e-mail precisa estar no **Exchange Online** (Microsoft 365 ou Outlook.com). Caixas locais (Exchange on-premises) não são acessíveis pelo Graph.

### 1.4 Configurar planilhas

O JARVIS não presume nomes de arquivos nem de colunas.

1. **Configurações > Planilhas > Descobrir**: lista planilhas do seu OneDrive, recentes e compartilhadas. Escolha uma.
   Ou **Adicionar link**: no Excel Online, *Compartilhar > Copiar link* e cole.
2. Selecione a planilha > **Carregar abas e colunas**. O JARVIS sugere colunas prováveis; você confirma:
   - **Apelido falado**: como você vai chamar ("pendências", "controle", "entregas");
   - **Aba** e **linha do cabeçalho** (automático detecta a primeira linha com títulos);
   - **Coluna de status** + **valores pendentes** (ex.: `pendente, em aberto`) ou **valores concluídos** (tudo que não for "concluído" vira pendência);
   - **Coluna de data/prazo** (para "atrasadas" e "mais antigas");
   - **Colunas-chave** (ex.: `Nota Fiscal, Cliente`) usadas nas respostas e na checagem de duplicidade;
   - **Avisar quando surgirem novas pendências** (verifica a cada 10 minutos).
3. **Aplicar a esta planilha**.

Garantias:
- leitura direta do arquivo real, sem cópias;
- edição apenas por pedido, com prévia "valor atual > novo valor" e confirmação;
- antes de gravar, o JARVIS relê a célula: se alguém alterou nesse meio-tempo, não grava;
- cada gravação fica na tabela `excel_audit` (Configurações > Privacidade > Auditoria de planilhas) e pode ser desfeita com "cancele a última ação";
- planilha nova só com pedido explícito ("cria uma planilha chamada...") e nunca sobrescreve arquivo existente.

Limitação: planilhas `.xls` antigas e arquivos protegidos por senha não são suportados pela API do Excel; converta para `.xlsx`.

---

## 2. WhatsApp Business

### Método escolhido e por quê

| Opção | Viável para a sua conta? | Decisão |
|---|---|---|
| **Notificações do Windows** (WhatsApp Desktop / WhatsApp Web) | Sim, gratuito, local | **Implementado** |
| Links oficiais `whatsapp://send` e `wa.me` | Sim | **Implementado** para abrir conversas e preencher texto |
| WhatsApp Business Platform (API Cloud da Meta) | Exige conta Meta Business, configuração de webhook público e cobrança por mensagem; não lê o histórico do app | Não usado |
| Automação do WhatsApp Web, bibliotecas não oficiais, extração de sessão | Viola os termos e arrisca banimento do número | **Rejeitado** |

O JARVIS lê as notificações que o próprio Windows exibiu (banco local da Central de Notificações, com permissões do seu usuário). Daí obtém **remetente** e **prévia**. Não acessa conversas antigas, não acessa o celular e nunca envia mensagens sozinho.

### Configuração

1. Instale o **WhatsApp** para Windows (Microsoft Store) e conecte o seu **WhatsApp Business** em *Aparelhos conectados* no celular. (O WhatsApp Web no navegador também funciona, desde que as notificações do site estejam permitidas.)
2. No WhatsApp Desktop: *Configurações > Notificações*: ative as notificações e **Mostrar prévias**.
3. No Windows: *Configurações > Sistema > Notificações > WhatsApp*: ativado, com **Mostrar notificações na central de notificações**.
4. **Configurações > WhatsApp** no JARVIS: cadastre os contatos que quer abrir ou para quem quer ditar mensagens (nome + número com DDI e DDD, ex.: `+5521999998888`).

### Limitações reais

- Sem prévia ligada, o Windows recebe apenas "Nova mensagem": o JARVIS informa o remetente (quando disponível) e diz que o conteúdo não estava acessível.
- Se o WhatsApp Desktop estiver fechado (e sem WhatsApp Web aberto), nenhuma notificação chega ao Windows.
- Para abrir uma conversa direto é preciso o número cadastrado; sem ele, o JARVIS abre o WhatsApp e informa quem chamou por último.
- O formato do banco de notificações do Windows não é documentado oficialmente. Se uma atualização do Windows alterar o formato, o indicador WHATSAPP fica vermelho e o restante do JARVIS segue funcionando.

### Sobre a API oficial (WhatsApp Business Platform)

Requisitos: conta Meta Business verificada, número registrado na plataforma (hoje existe o modo "coexistência", que permite usar o mesmo número no app Business e na API), servidor HTTPS público para receber webhooks e um provedor/BSP ou a API Cloud. A cobrança é por mensagem e muda com frequência; fontes divergem sobre a gratuidade das conversas de atendimento a partir de outubro de 2026. Consulte a tabela oficial da Meta antes de qualquer decisão. Para o objetivo "saber quem me chamou e abrir a conversa", as notificações do Windows resolvem sem custo.

---

## 3. Inteligência artificial (opcional)

Sem IA, o JARVIS entende todos os comandos listados em [COMANDOS.md](COMANDOS.md). A IA serve para frases livres, contexto ("quais delas são mais antigas?"), resumos e redação de respostas.

### Claude (Anthropic API)

1. Crie uma conta em <https://console.anthropic.com>, cadastre forma de pagamento e gere uma **API key**.
2. **Configurações > IA**: provedor *Claude*, cole a chave (vai para o Gerenciador de Credenciais do Windows), **Testar conexão**.
3. Modelo padrão: `claude-opus-5-5` (mais capaz). Para gastar menos, use `claude-haiku-5-5`.

Custo de referência (preços de tabela, por milhão de tokens): Opus 5.5 US$ 4 entrada / US$ 20 saída; Haiku 5.5 US$ 0,10 / US$ 0,50. Cada pedido livre envia as instruções e a lista de ações (~4 mil tokens, com cache automático que reduz o custo das repetições) mais o contexto. Ordem de grandeza: alguns centavos de dólar por pedido no Opus e frações de centavo no Haiku. Comandos reconhecidos localmente não geram custo.

O JARVIS ativa o *fallback* automático do servidor da Anthropic: se o modelo recusar um pedido por política, outro modelo tenta responder.

**Perguntas gerais e pesquisa na web.** Com o Claude ativo, qualquer pergunta que não seja um comando ("Jarvis, quanto está o dólar hoje?", "quem ganhou o jogo do Flamengo?", "explica o que é ICMS-ST") vai para o Claude. Perguntas de conhecimento geral são respondidas direto; fatos atuais usam a **pesquisa na web oficial da Anthropic** (até 3 pesquisas por pergunta, localizada no Brasil), com a fonte citada na resposta. A pesquisa custa US$ 10 por 1.000 pesquisas, além dos tokens; desligue em Configurações > IA se não quiser.

**Importante:** a assinatura do Claude (claude.ai Pro/Max) não inclui a API. A chave da API é uma conta separada, cobrada por uso, em console.anthropic.com.

### Ollama (local e gratuito)

1. Instale em <https://ollama.com> e rode `ollama pull llama3.1` (ou outro modelo com suporte a *tools*).
2. **Configurações > IA**: provedor *Ollama*, URL `http://localhost:11434`, modelo `llama3.1`.

Exige memória (8 GB+ livres para modelos de 8B) e é mais lento que a nuvem, principalmente sem placa de vídeo. Evite durante jogos.

### Privacidade com IA

Com IA ativa, vão para o provedor: o texto do pedido, o contexto recente e, nos resumos, trechos de e-mails/mensagens/planilhas necessários. Desmarque **Permitir enviar conteúdo de e-mails/mensagens à IA** para resumos apenas locais (listas de remetentes e assuntos).

---

## 4. Voz do JARVIS pela Fish Audio

O JARVIS fala **todas** as respostas com a voz escolhida na Fish Audio: respostas da IA, comandos, avisos de notificações e o "Às suas ordens".

| Configuração | Valor |
|---|---|
| Provedor | Fish Audio API (`POST https://api.fish.audio/v1/tts`) |
| ID da voz (JARVIS) | `a5b93aeddcc948c19ea04f0afe9d178c` (já vem configurado) |
| Modelo | `s2.1-pro` |
| Idioma | português do Brasil (definido pelo texto e pela voz) |
| Formato | WAV em streaming (o áudio começa a tocar enquanto ainda está chegando) |

### Configurar (2 minutos)

1. Em https://fish.audio, entre na sua conta > **API Keys** > crie uma chave.
2. Na pasta do JARVIS, abra o arquivo **`.env`** no Bloco de Notas (o instalador já cria; se não existir, copie `.env.example` para `.env`).
3. Cole a chave assim, sem aspas e sem espaços:
   ```
   FISH_AUDIO_API_KEY=sua_chave_aqui
   ```
4. Salve e reinicie o JARVIS.
5. Teste: dois cliques em **`test_fish_voice.bat`**. Ele confere a chave, o ID da voz e o modelo, mostra o tempo até o primeiro áudio, salva `fish_teste.wav` e toca. Ou: **Configurações > Voz > Testar voz Fish Audio**.

A chave fica só no arquivo `.env` (que não vai para o GitHub). Ela não aparece na tela nem nos registros.

### Como funciona no dia a dia

- **Velocidade e volume:** Configurações > Voz. "Velocidade" e "Volume da voz" valem para a Fish Audio; "Volume na geração (dB)" ajusta o volume no próprio áudio gerado. Por voz: "fala mais devagar", "fala mais alto".
- **Interrupção:** chamar "Jarvis", apertar `Ctrl+Alt+S`, o botão Parar ou digitar um novo comando corta a fala na hora e para o download do áudio.
- **Sem repetição:** a mesma frase pedida duas vezes seguidas (em até 3 segundos, ou já na fila) é falada uma vez só.
- **Cache:** frases curtas (até 160 caracteres, como "Às suas ordens") são guardadas após a primeira vez e tocam na hora, sem gastar créditos de novo.
- **Reserva:** se a Fish Audio falhar antes de começar a falar (sem internet, sem créditos, chave inválida, limite de uso), o JARVIS responde na hora com a voz reserva (neural da Microsoft ou a do Windows) e avisa em Atividades. Falhas temporárias: tenta a Fish Audio de novo após 60 segundos. Problemas de conta (chave, créditos, ID): após 10 minutos.
- **Perfil FRIDAY:** usa a voz neural feminina, a menos que você cole um ID da Fish Audio no campo "ID da voz FRIDAY".

### Custo

A Fish Audio cobra pelo texto convertido em fala, conforme o plano da sua conta (confira em fish.audio). O cache das frases curtas reduz o gasto com respostas repetidas.

## 5. Vozes reserva

| Motor | Qualidade | Requisito |
|---|---|---|
| **Neural Edge** (padrão) | Alta (pt-BR-AntonioNeural / FranciscaNeural) | Internet; usa o serviço de leitura em voz alta do Microsoft Edge, que não é uma API comercial oficial e pode mudar |
| **Azure AI Speech** | Alta, oficial, com SSML | Recurso *Speech* no Azure (cota gratuita mensal); chave e região em Configurações > Voz |
| **Windows (SAPI)** | Média (Daniel/Maria) | Offline; instale o pacote de voz pt-BR em *Configurações > Hora e idioma > Fala* |

No modo *Automático*, se a voz online falhar, o JARVIS usa a voz do Windows por 2 minutos e tenta a online de novo. Frases de confirmação ("Às suas ordens") são pré-geradas para resposta instantânea.

As vozes dos filmes são de atores reais e não podem ser reproduzidas legalmente. Os perfis usam vozes sintéticas com estilo próximo: JARVIS grave e calmo (tom levemente abaixado), FRIDAY clara e confiante. Outras vozes pt-BR podem ser testadas em Configurações > Voz (ex.: `pt-BR-ThalitaMultilingualNeural`).

---

## 6. Spotify

| Nível | Requisito | O que funciona |
|---|---|---|
| **Básico** | Nenhum (qualquer conta, até gratuita) | "pausa", "continua", "próxima", "música anterior" pelas teclas de mídia do Windows; "toca X" abre a busca no app do Spotify |
| **Completo** | Spotify **Premium** + app gratuito no Spotify for Developers | "toca Back in Black", "toca Coldplay", "coloca a playlist de rock", "quero ouvir o álbum Thriller" tocam na hora; "que música é essa?", volume e aleatório |

Regras atuais do Spotify (fevereiro de 2026): o dono do app em modo de desenvolvimento precisa ter Premium, cada pessoa pode ter um Client ID, com até 5 usuários autorizados, e controlar a reprodução exige Premium.

### Conectar (nível completo, ~5 minutos)

1. Acesse <https://developer.spotify.com/dashboard> com sua conta Spotify e clique em **Create app**.
2. Nome: `JARVIS`. Descrição: `Assistente pessoal`.
3. **Redirect URI**: `http://127.0.0.1:8888/callback` (exatamente assim; o Spotify não aceita `localhost`).
4. Em *Which API/SDKs are you planning to use?*, marque **Web API**. Salve.
5. Copie o **Client ID** (não é necessário o Client Secret: o login usa PKCE).
6. No JARVIS: **Configurações > Música > Client ID do app Spotify**, cole e clique em **Conectar Spotify**. Autorize na página do Spotify.

Para criar e editar playlists, a autorização inclui também as permissões de playlist. Se você conectou numa versão anterior do JARVIS, clique em **Conectar Spotify** de novo.

O JARVIS guarda apenas o token de renovação, no Gerenciador de Credenciais do Windows. Desconectar apaga o token.

Para tocar, o app do Spotify precisa estar aberto em algum aparelho (PC, celular, caixa). Se nenhum estiver ativo, o JARVIS abre o Spotify do PC e toca nele.

## 7. Roteirização Ícaro

O JARVIS usa o mesmo motor da ferramenta `roteirizacao_icaro.html` (mesmas regras de carga obrigatória, capacidade, peso que trava a Fiorino, saída única e margem de custo), lendo as planilhas de uma pasta em vez do upload no navegador.

1. **Configuração da filial**: o arquivo `config\rota_filial.json` (motoristas, custos, adicionais, regiões, regras de CEP e bairro, clientes prioritários, capacidades e faixas) vem no pacote e **não vai para o GitHub**. Para outra filial, copie `config\rota_filial.example.json`, preencha e salve como `rota_filial.json`.
2. **Pasta**: na primeira vez, o JARVIS cria `Documentos\Roteirizacao Icaro` com as subpastas:
   - `1 - Fretes chegando`, `2 - Cargas ja no Rio`, `3 - Agendamentos` (cada uma aceita várias planilhas .xlsx, .xls ou .csv);
   - `De-para CEP (opcional)`: só se o relatório não tiver coluna de região;
   - `Rotas geradas`: Excel (Resumo, Romaneio, Fora realocar) e romaneios para impressão.
3. Planilhas com mais de 20 horas são ignoradas e avisadas, para não misturar o dia anterior (ajuste em **Configurações > Roteirização**).
4. Colunas são detectadas automaticamente como na ferramenta. Se alguma não for achada, o JARVIS diz qual falta.

A ferramenta HTML continua disponível ("abre a ferramenta de roteirização") para conferência visual e ajustes por clique.

## 8. Porcupine (opcional)

Detecção da palavra "jarvis" mais precisa e com menos falsos disparos.

1. Crie conta em <https://console.picovoice.ai> e copie a **AccessKey** (gratuita para uso pessoal, com limites do plano).
2. `install.bat -Optional` (ou `.venv\Scripts\pip install pvporcupine`).
3. **Configurações > Ativação**: detecção *Porcupine*, cole a AccessKey, reinicie o JARVIS.

A detecção continua 100% local; a chave serve para licenciamento.
