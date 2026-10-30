# Tutorial de instalação do JARVIS

Tempo total: cerca de 20 minutos para o básico, mais 10 a 15 minutos por integração (Outlook, Spotify etc.).
Não precisa ser administrador do computador.

---

## Já tem o JARVIS instalado? Atualize assim (5 minutos)

1. Feche o JARVIS: ícone perto do relógio > **Sair**.
2. Baixe o **jarvis-assistente-v3.zip** > botão direito > **Propriedades** > marque **Desbloquear** > OK.
3. Botão direito no zip > **Extrair tudo** > escolha **a mesma pasta** onde o JARVIS já está > confirme **Substituir os arquivos**.
   Seu arquivo `.env` (chave da Fish Audio) e suas configurações são mantidos.
4. Dê dois cliques em **install.bat** e espere "Instalação concluída" (ele instala os componentes novos da roteirização).
5. Abra o JARVIS pelo atalho e siga a seção **Roteirização** da Parte 2.

Instalação nova? Siga a Parte 1 inteira.

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

### Voz do JARVIS pela Fish Audio (cerca de 2 minutos)

1. Em https://fish.audio, entre na sua conta > **API Keys** > crie uma chave e copie.
2. Na pasta do JARVIS, abra o arquivo **.env** com o Bloco de Notas (botão direito > Abrir com > Bloco de Notas).
3. Deixe a linha assim, com a sua chave: `FISH_AUDIO_API_KEY=sua_chave_aqui` > Salvar.
4. Dê dois cliques em **test_fish_voice.bat**: deve aparecer "TESTE OK" e você vai ouvir a voz.
5. Reinicie o JARVIS. Pronto: todas as respostas passam a usar essa voz.

O ID da voz (`a5b93aeddcc948c19ea04f0afe9d178c`) e o modelo (`s2.1-pro`) já vêm configurados.

### Roteirização dos agregados (cerca de 5 minutos)

O JARVIS monta a rota com **o próprio código da sua ferramenta** `roteirizacao_icaro.html` (o mesmo resultado do navegador).

**A) Primeira vez:**
1. Diga **"Jarvis, abre a pasta da rota"** (ou ⚙ > aba **Roteirização** > **Abrir pasta**).
   Ele cria `Documentos\Roteirizacao Icaro` com as pastas:
   - `1 - Fretes chegando`
   - `2 - Cargas ja no Rio`
   - `3 - Agendamentos`
   - `Rotas geradas` (onde saem o Excel e os PDFs do Circuit)
2. Em ⚙ > **Roteirização**, a Situação deve mostrar **"ferramenta encontrada"**.

**B) Todo dia:**
1. Exporte o relatório do sistema (o mesmo que você sobe na ferramenta) e salve em **`2 - Cargas ja no Rio`**.
   Se tiver relatório de chegando ou de agendamentos, salve nas pastas 1 e 3.
2. Diga **"Jarvis, monta a rota"**. Ele monta para o próximo dia útil e mostra a tabela por motorista.
   Feriado: **"Jarvis, monta a rota de amanhã, é feriado"**.
3. Ajuste por voz, se precisar:
   - "o Ronald não vai hoje" / "o Ronald vai sim"
   - "move a nota 1234 para o Deusereis" (pode falar só o final do número)
   - "troca a rota do Marcos com a do Ronald"
   - "realoca o Jeferson para OES 1"
   - "tira a nota 1234" / "restaura a nota 1234"
   - "rota do Lucas", "como ficou a rota", "o que ficou fora da rota"
4. **"Jarvis, gera o Excel da rota"** e **"Jarvis, gera os PDFs do Circuit"**: os arquivos abrem sozinhos da pasta `Rotas geradas`.
5. **"Jarvis, abre o mapa da rota"** abre a ferramenta no navegador para ver o mapa.

A rota montada fica salva: se fechar o JARVIS, ela volta quando abrir de novo.
Planilhas com mais de 20 horas são ignoradas (para não misturar o dia anterior); dá para mudar em ⚙ > Roteirização.

**C) Quando mudar a ferramenta** (motoristas, custos, regras): copie o HTML novo para a pasta `referencia` do JARVIS, com o nome `roteirizacao_icaro.html`.

**D) Publicar a ferramenta corrigida no Netlify** (mapa e exclusão de Nilópolis/São Paulo):
1. Guarde uma cópia do arquivo atual do site.
2. No Netlify, abra o site > **Deploys** > arraste a pasta com o `roteirizacao_icaro.html` novo (renomeie para `index.html` se o site usa esse nome).
3. Abra o site, monte a rota, vá na aba **Mapa** > **geocodificar**. Cada entrega deve aparecer com o próprio pino.

### Outlook e Excel Online (desligado; só se o TI liberar)

O Outlook vem **desligado** porque a empresa exige aprovação do administrador. Quando o TI aprovar o aplicativo, marque **Ligar Outlook** em ⚙ > **Microsoft 365** e siga os passos abaixo.

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
| "Não encontrei planilhas recentes" | Salve o relatório em `Documentos\Roteirizacao Icaro\2 - Cargas ja no Rio` (arquivo com menos de 20 horas) |
| "Não achei a ferramenta de roteirização" | Confira se existe `referencia\roteirizacao_icaro.html` dentro da pasta do JARVIS |
| "Tem mais de um Yuri" | Diga nome e sobrenome: "rota do Ronald Yuri" |
| Mapa não mostra entregas | Clique em geocodificar de novo; se aparecer "token inválido ou bloqueado", use o mapa pelo site do Netlify |

Para diagnóstico detalhado: abra **start_debug.bat** e repita o problema. Se precisar de ajuda, envie o arquivo:
`%APPDATA%\Jarvis\logs\jarvis.log`
(cole esse endereço na barra do Explorador de Arquivos).

---

## Onde aprender mais

- `docs\COMANDOS.md`: tudo que dá para pedir
- `docs\INTEGRACOES.md`: detalhes de cada conexão
- `docs\SOLUCAO_DE_PROBLEMAS.md`: problemas e soluções
