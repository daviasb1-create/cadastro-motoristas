# Instalação no Windows 11

## 1. Instalar o Python
1. Acesse <https://www.python.org/downloads/> e baixe o **Python 3.12** (64 bits).
2. Na primeira tela do instalador, marque **"Add python.exe to PATH"** e clique em **Install Now**.
3. Para conferir, abra o **Prompt de Comando** (tecla Windows, digite `cmd`) e rode `python --version`.

## 2. Baixar o sistema
- **Opção simples:** no GitHub, clique em **Code > Download ZIP**, extraia e copie a pasta
  `logistics-intelligence` para **`C:\LI\logistics-intelligence`** (caminho curto; evite deixar dentro de Downloads,
  porque o ZIP cria pastas com nomes muito longos).
- **Opção Git:** `git clone https://github.com/daviasb1-create/cadastro-motoristas.git`

## 3. Primeira execução
1. Abra a pasta `logistics-intelligence`.
2. Dê dois cliques em **`iniciar_windows.bat`**.
   - Na primeira vez, ele cria o ambiente Python em `%LOCALAPPDATA%\LogisticsIntelligence\venv` (caminho curto,
     evita o limite de 260 caracteres do Windows), instala as dependências e copia `.env.example` para `.env`.
   - O painel abre só no seu computador (`localhost`); outras pessoas da rede não acessam.
   - O navegador abre em `http://localhost:8501`.
3. Para fechar, feche a janela preta do Prompt.

> Se o Windows mostrar "O Windows protegeu o computador", clique em **Mais informações > Executar assim mesmo**
> (o arquivo .bat é texto simples; você pode abri-lo no Bloco de Notas para conferir).

## 4. Configurar
No painel, abra **10. Configurações**:
1. **Empresa e comercial:** dados da Ícaro Express, seu nome, cargo, telefone, e-mail e assinatura.
2. **Credenciais:** cole as chaves das APIs (ver [CONFIGURACAO_APIS.md](CONFIGURACAO_APIS.md)).
   Elas ficam gravadas apenas no arquivo `.env` desta pasta.
3. **Score e alertas:** clique em "Enviar alerta de teste no Telegram".

## 5. Pesquisa automática com o PC ligado (opção B)
**Jeito 1 (mais simples):** dê dois cliques em `agendador_windows.bat` e deixe a janela aberta (pode minimizar).

**Jeito 2 (Agendador de Tarefas, roda sem janela aberta):**
1. Tecla Windows > digite **Agendador de Tarefas** > **Criar Tarefa Básica**.
2. Nome: `Radar 07h`. Disparador: **Diariamente**, 07:00.
3. Ação: **Iniciar um programa** > Programa: `C:\LI\logistics-intelligence\pesquisar_agora_windows.bat`
   e em **Iniciar em**: `C:\LI\logistics-intelligence`.
4. Repita para 12:00 e 17:00. Para o monitor de urgentes, crie tarefas 09:30 e 14:30 com o argumento `urgente`.
5. Nas propriedades da tarefa, marque **"Executar a tarefa assim que possível após uma inicialização agendada ter sido perdida"**.

Com o computador desligado nada roda. Para isso, use a nuvem: [IMPLANTACAO_NUVEM.md](IMPLANTACAO_NUVEM.md).

## Problemas comuns
| Sintoma | Solução |
|---|---|
| `python não é reconhecido` | Reinstale o Python marcando "Add to PATH". |
| Painel não abre | Acesse manualmente `http://localhost:8501`. |
| Fonte "sem_credencial" | Falta a chave daquela API em Configurações > Credenciais (é opcional). |
| Fonte "indisponivel" | Site fora do ar ou limite atingido; o sistema segue com as demais e registra no Histórico. |
| `ImportError ... O nome do arquivo ou a extensão é muito grande` | Caminho longo demais (limite do Windows). Mova a pasta para `C:\LI\logistics-intelligence`, apague a pasta `.venv` que estiver dentro dela, se existir, e rode o `iniciar_windows.bat` atualizado. |
| Erro na instalação | Apague a pasta `%LOCALAPPDATA%\LogisticsIntelligence\venv` e rode o `iniciar_windows.bat` de novo. |
| Quero recomeçar do zero | Feche o painel e apague `data\logistics.db`. |
