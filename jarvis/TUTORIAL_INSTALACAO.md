# Tutorial de instalação do JARVIS

Tempo total: cerca de 20 minutos para o básico, mais 10 a 15 minutos por integração (Outlook, Spotify etc.).
Não precisa ser administrador do computador.

---

## Parte 1: o básico (voz e comandos do Windows)

### Passo 1: instalar o Python (uma vez)

O JARVIS é escrito em Python, então o computador precisa dele.

1. Clique no botão Iniciar, digite **PowerShell** e abra.
2. Cole o comando abaixo e aperte Enter:
   ```
   winget install Python.Python.3.12
   ```
3. Espere terminar e **feche o PowerShell**.

Se o comando `winget` não funcionar: entre em https://www.python.org/downloads/, baixe o **Python 3.12**, e na primeira tela do instalador **marque a caixa "Add python.exe to PATH"** antes de clicar em *Install Now*.

### Passo 2: colocar os arquivos no lugar certo

1. Baixe o arquivo **jarvis-assistente.zip**.
2. **Antes de extrair:** clique com o botão direito no zip > **Propriedades** > marque **Desbloquear** (se aparecer) > OK.
   Isso evita que o Windows bloqueie os arquivos baixados da internet.
3. Crie uma pasta fixa, por exemplo: `C:\Users\SEU_USUARIO\Jarvis`
   (evite a Área de Trabalho e pastas do OneDrive).
4. Clique com o botão direito no zip > **Extrair tudo** > escolha a pasta criada.

Dentro da pasta você deve ver arquivos como `install.bat`, `start.bat` e `README.md`.

### Passo 3: instalar

1. Dê dois cliques em **install.bat**.
2. Se aparecer a tela azul "O Windows protegeu o computador": clique em **Mais informações** > **Executar assim mesmo**.
3. Aguarde de 5 a 10 minutos. Ele vai:
   - preparar o ambiente,
   - instalar os componentes,
   - baixar o modelo de voz em português (31 MB),
   - criar o atalho **JARVIS** na Área de Trabalho e no Menu Iniciar.
4. Quando aparecer **"Instalação concluída"**, aperte qualquer tecla para fechar.

### Passo 4: abrir e liberar o microfone

1. Abra pelo atalho **JARVIS** na Área de Trabalho.
2. Se o indicador **MICROFONE** ficar vermelho:
   *Configurações do Windows > Privacidade e segurança > Microfone* > ative **"Permitir que aplicativos da área de trabalho acessem o microfone"**.
3. No JARVIS, clique na engrenagem (⚙) > aba **Ativação** e confira se o microfone e a saída de som certos estão escolhidos.

### Passo 5: calibrar a sua voz (importante)

1. ⚙ > aba **Ativação** > **Calibrar com a minha voz**.
2. Diga **"Jarvis"** três vezes, uma após cada bipe.
3. Clique em **Salvar**.

Isso faz o JARVIS reconhecer como **você** pronuncia "Jarvis". É o passo que mais melhora o acerto.

### Passo 6: testar

Diga:
- "**Jarvis**" (ele responde "Às suas ordens")
- "**Jarvis, que horas são?**"
- "**Jarvis, abre o navegador**"
- "**Jarvis, aumenta o volume**"
- "**Jarvis, me lembra de beber água em 2 minutos**"

Atalhos de teclado (funcionam até com jogo aberto):
- `Ctrl + Alt + J`: falar sem dizer "Jarvis"
- `Ctrl + Alt + S`: parar a fala
- `Ctrl + Alt + M`: ligar/desligar o microfone

### Passo 7: iniciar junto com o Windows (opcional)

⚙ > aba **Geral** > marque **Iniciar com o Windows** > Salvar.
Ele passa a abrir sozinho, escondido na bandeja (perto do relógio).

---

## Parte 2: integrações (faça só as que for usar)

### Outlook e Excel Online (cerca de 10 minutos)

Você usa o Outlook web, o que funciona normalmente.

**A) Registrar o "aplicativo" na Microsoft (uma vez):**
1. Entre em https://entra.microsoft.com com a sua conta do trabalho.
2. Menu **Identidade > Aplicativos > Registros de aplicativo > Novo registro**.
3. Nome: `JARVIS pessoal`. Tipo de conta: **Contas somente neste diretório organizacional**.
4. URI de redirecionamento: escolha **Cliente público/nativo (celular e área de trabalho)** e digite `http://localhost`.
5. Clique em **Registrar** e **copie o "ID do aplicativo (cliente)"**.
6. Menu **Autenticação** > **Permitir fluxos de cliente público: Sim** > Salvar.
7. Menu **Permissões de API > Adicionar permissão > Microsoft Graph > Permissões delegadas**, marque:
   `User.Read`, `Mail.ReadWrite`, `Mail.Send`, `Calendars.ReadWrite`, `Files.ReadWrite.All` > Adicionar.

Se a opção de registrar estiver bloqueada ou pedir "aprovação do administrador", peça ao TI da empresa para fazer esses passos ou aprovar o aplicativo.

**B) Conectar no JARVIS:**
1. ⚙ > aba **Microsoft 365** > cole o ID no campo **ID do aplicativo**.
2. Locatário: `organizations`.
3. Clique em **Conectar (navegador)** e faça login na página da Microsoft.
4. Os indicadores **OUTLOOK** e **EXCEL** ficam verdes.
5. Preencha **Gestor** (nome ou e-mail) para comandos como "procura o último e-mail do meu gestor".

**C) Escolher as planilhas:**
1. ⚙ > aba **Planilhas** > **Descobrir** (ou **Adicionar link**: no Excel Online, *Compartilhar > Copiar link*).
2. Selecione a planilha > **Carregar abas e colunas**.
3. Confira: apelido falado (ex.: "pendências"), coluna de status, valores pendentes (ex.: `pendente`), coluna de prazo.
4. **Aplicar a esta planilha** > Salvar.

Teste: "Jarvis, tenho e-mails novos?", "Jarvis, verifica minhas pendências", "Jarvis, marca reunião com o Carlos amanhã às 10h".

### WhatsApp Business (cerca de 5 minutos)

1. Instale o **WhatsApp** para Windows (Microsoft Store) e conecte o seu WhatsApp Business pelo celular (*Aparelhos conectados*).
2. No WhatsApp do PC: *Configurações > Notificações* > ative as notificações e **Mostrar prévias**.
3. No Windows: *Configurações > Sistema > Notificações > WhatsApp* > ativado.
4. No JARVIS: ⚙ > aba **WhatsApp** > cadastre os contatos (nome e número com +55 e DDD, ex.: `+5521999998888`).

Teste: peça para alguém te mandar mensagem e diga "Jarvis, quem me chamou no WhatsApp?".

### Spotify (cerca de 5 minutos, precisa de Premium para tocar direto)

1. Entre em https://developer.spotify.com/dashboard > **Create app**.
2. Nome `JARVIS`, Redirect URI **exatamente** `http://127.0.0.1:8888/callback`, marque **Web API** > Salvar.
3. Copie o **Client ID**.
4. No JARVIS: ⚙ > aba **Música** > cole o Client ID > **Conectar Spotify** > autorize.

Teste: "Jarvis, toca Back in Black". Sem Premium, "pausa", "próxima" e "música anterior" funcionam mesmo assim.

### Música de fundo (modo Homem de Ferro)

⚙ > aba **Música** > **Escolher…** e selecione um MP3 seu, ou clique num dos botões de sugestão (Spotify/YouTube) > Salvar.
Teste: "Jarvis, modo Homem de Ferro".

### Claude: perguntas livres e pesquisa na internet (opcional, pago por uso)

1. Crie conta em https://console.anthropic.com, adicione forma de pagamento e um **limite mensal** (ex.: US$ 5).
2. Gere uma **API key**.
3. No JARVIS: ⚙ > aba **IA** > provedor **Claude** > cole a chave > **Testar conexão**.
4. Para economizar, troque o modelo para `claude-haiku-5-5`.

A assinatura do claude.ai **não** inclui a API; é uma conta separada.
Teste: "Jarvis, quanto está o dólar hoje?".

---

## Parte 3: se algo der errado

| Problema | Solução |
|---|---|
| install.bat fecha sozinho ou dá erro de Python | Refaça o Passo 1 e reinicie o computador |
| "Modelo de voz ausente" | Rode de novo o `install.bat` (ele só baixa o que falta) |
| Não reage a "Jarvis" | Refaça a calibração; aumente a sensibilidade em ⚙ > Ativação; use `Ctrl+Alt+J` para testar |
| Dispara sozinho | Diminua a sensibilidade; use fone de ouvido |
| Não fala nada | ⚙ > Voz > Testar voz. Sem internet ele usa a voz do Windows: instale a voz em português em *Configurações > Hora e idioma > Fala* |
| Outlook não conecta | Veja a mensagem de erro e o guia `docs\SOLUCAO_DE_PROBLEMAS.md` |

Para diagnóstico detalhado: abra **start_debug.bat** e repita o problema. Se precisar de ajuda, envie o arquivo:
`%APPDATA%\Jarvis\logs\jarvis.log`
(cole esse endereço na barra do Explorador de Arquivos).

---

## Onde aprender mais

- `docs\COMANDOS.md`: tudo que dá para pedir
- `docs\INTEGRACOES.md`: detalhes de cada conexão
- `docs\SOLUCAO_DE_PROBLEMAS.md`: problemas e soluções
