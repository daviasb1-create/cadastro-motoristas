# ⚡ TURBO BOOST PRO

Otimizador de desempenho para **Windows 11** (compatível com Windows 10), feito em Python + CustomTkinter.
Interface escura com azul neon, 100% em português, funciona **offline** e **toda alteração é reversível**.

---

## 1. Instalação e execução (5 minutos)

### Requisitos
- Windows 10 (1809+) ou Windows 11, 64 bits
- [Python 3.11 ou 3.12](https://www.python.org/downloads/) (marque **"Add python.exe to PATH"** na instalação)

### Rodar direto do código
```bat
cd turbo_boost_pro
run.bat
```
O `run.bat` cria um ambiente virtual, instala as dependências e abre o programa.

Manual, se preferir:
```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

### Gerar o executável e o instalador (.exe)
```bat
build.bat
```
Resultado:
| Arquivo | O que é |
|---|---|
| `dist\TurboBoostPro\TurboBoostPro.exe` | Executável (modo pasta: abre mais rápido que arquivo único) |
| `installer\Output\TurboBoostPro_Setup_1.2.0.exe` | Instalador com atalhos e desinstalador (requer [Inno Setup 6](https://jrsoftware.org/isdl.php) instalado) |

> O app abre como **usuário comum** e só pede administrador quando você usa um recurso que exige
> (botão "Elevar para admin" na barra lateral, ou o aviso que aparece na prévia de cada ação).
> Para usar tudo de uma vez: clique com o botão direito no atalho › **Executar como administrador**.

---

## 2. Fluxo de uso recomendado

1. **Diagnóstico › ANALISAR MEU PC**: veja gargalos e recomendações (cada uma com botão de correção).
2. **Painel › TURBO MODE**: revise a prévia e execute. Para jogar, ative antes de abrir o jogo.
3. **Gaming Boost**: "Ativar todas" + crie **perfis** dos seus jogos (ou "Detectar jogos da Steam").
4. **Desempenho › Inicialização**: "Desativar recomendados" (efeito no próximo boot).
5. **Limpeza**: Analisar › Limpar.
6. Teste seus jogos. Se algo piorar: **Segurança › Reverter** o item ou **RESTAURAR TUDO**.

---

## 3. Funcionalidades

| Módulo | O que faz de verdade |
|---|---|
| **Painel** | CPU (uso, GHz), GPU (uso, VRAM), RAM, disco (atividade, leitura/escrita), rede, temperaturas, uptime, histórico 60 s e **Índice de desempenho** (0-100) |
| **TURBO MODE** | Cria e ativa plano de energia dedicado (CPU mín. 100%, sem estacionamento de núcleos, PCIe/USB sem economia), libera RAM (working sets + Standby List), fecha apps de fundo não essenciais, pausa serviços (Search, telemetria, WER…), aplica 15 ajustes de registro, limpa cache DNS. **Um clique desfaz tudo** (apps são reabertos, serviços reiniciados, plano original restaurado) |
| **Modos** | Automático · Gamer · Máximo Desempenho · Equilibrado |
| **Gaming Boost** | Game Mode, Game DVR off, HAGS, otimizações de jogos em janela + VRR, MMCSS (prioridade CPU/GPU para jogos), Win32PrioritySeparation, mouse sem aceleração, NetworkThrottlingIndex, Nagle off, timer 0,5 ms, tela cheia exclusiva (opcional) |
| **Perfis por jogo** | Prioridade, GPU dedicada (DirectX UserGpuPreferences), tela cheia exclusiva por executável, fechar apps/pausar serviços/liberar RAM/timer ao abrir o jogo. **Detecção automática**: aplica ao abrir, reverte ao fechar |
| **Limpeza** | Temp do usuário/Windows, miniaturas, WER/dumps, logs, Lixeira, downloads do Windows Update, Otimização de Entrega, WinSxS (DISM), cache de navegadores e apps (Discord, Spotify, Teams, Steam, Epic, Office), shaders DirectX/NVIDIA/AMD/Intel. Mostra o tamanho **antes** de excluir. **Arquivos grandes**: lista e envia para a Lixeira |
| **Desempenho** | Processos (CPU/RAM em tempo real, encerrar, prioridade), Inicialização (desativa pelo mesmo mecanismo do Gerenciador de Tarefas), Serviços (pausar ou definir Manual, com restauração) |
| **Windows Avançado** | Responsividade, efeitos visuais, plano de energia, DNS (teste de latência offline + troca reversível), TRIM/desfragmentação/NTFS, apps de segundo plano, Widgets, Edge em segundo plano, sugestões, telemetria mínima, P2P de atualizações |
| **Diagnóstico** | Mede uso por 6 s, identifica gargalo (CPU/GPU/RAM/disco), RAM em canal único, Windows em HD, disco cheio, temperatura, uptime, plano de energia, ajustes pendentes, inicialização, serviços e processos pesados. Nota 0-100 e **relatório HTML** |
| **Segurança** | RESTAURAR TUDO, histórico de alterações com reversão individual, ponto de restauração, backups e logs |

---

## 3.1 WINDOWS ULTRA LITE (novo na versão 1.1)

Aba **🪶 Windows Ultra Lite**. Deixa o Windows 11 enxuto sem formatar. Execute como **administrador**.

| Sub-aba | O que faz de verdade | Como desfaz |
|---|---|---|
| **Visão geral** | Verifica a versão/edição do Windows; botões **APLICAR ULTRA LITE**, **GAMING EDITION** (liga/desliga) e **RESTAURAR WINDOWS ORIGINAL** | Botão DESATIVAR em cada perfil ou RESTAURAR |
| **Gaming Edition** | Plano de energia TURBO, Game Mode, MMCSS, HAGS, prioridade de primeiro plano, mouse/teclado sem atraso, efeitos visuais mínimos, timer 0,5 ms, boost automático de jogos. **CS2**: prioridade Alta de CPU/E-S permanente (IFEO), GPU dedicada, `autoexec.cfg` opcional, opções de inicialização e configurações de vídeo recomendadas | Um clique (DESATIVAR PERFIL) |
| **Debloat** | Lista apps pré-instalados (Notícias, Clima, Solitaire, Copilot, Widgets, Teams, Clipchamp, atalhos promocionais…) com seleção individual. Remove só para o seu usuário (`Remove-AppxPackage`) | Reinstalação offline (`Add-AppxPackage -Register` da cópia do sistema) ou pela Store |
| **Serviços** | Tabela com finalidade, estado, tipo de inicialização e RAM de cada serviço. Perfis **Conservador / Avançado / Extremo** | Restaurar serviços (tipo original salvo) |
| **Registro** | Todos os 37 ajustes com chave, valor atual → novo e efeito documentado. Aplicação individual com backup | Desligar o ajuste |
| **Recursos e tarefas** | Recursos opcionais (XPS, Fax, PowerShell 2.0, SMB1, IE, Recall, Hyper-V opcional…) e 17 tarefas agendadas de telemetria | Reativação offline (recursos não são apagados) |
| **Comparação** | Mede RAM, processos, serviços, CPU em repouso, tempo de boot, espaço livre e apps na inicialização, antes/depois, com diferença em % | - |
| **Log** | Todas as operações em tempo real (`%LOCALAPPDATA%\TurboBoostPro\logs`) | - |

**Nunca alterados:** Defender, Firewall, Windows Update/BITS/UsoSvc, Microsoft Store (e seus frameworks), Xbox Identity/Gaming Services, áudio, Bluetooth, rede (DHCP, DNS, Wi-Fi), Plug and Play, drivers e codecs.

**Não implementado de propósito:** desligar a Integridade de Memória (HVCI/VBS). Ela pode custar 3-10% de FPS, mas é uma proteção de segurança; o Diagnóstico informa o estado e você decide manualmente.

**Como medir o ganho:** Comparação › Medir agora → aplicar → **reiniciar** → esperar 2 min → Medir agora.

---

## 3.2 COMPETITIVO (CS2) · Etapa 2 (novo na versão 1.2)

Aba **🎯 Competitivo (CS2)**. Foco em desempenho real medido em jogo, não em números de RAM.

| Sub-aba | O que faz |
|---|---|
| **Análise** | CPU (limite de desempenho, turbo, estacionamento, X3D/híbrida), RAM (XMP/EXPO, canal, paginação, compressão, paginação ativa), GPU (fabricante, driver, monitor abaixo da taxa máxima, HAGS, recomendações NVIDIA/AMD/Intel), latência (timer, DPC/ISR, ping/jitter/perda, economia de energia da placa de rede), disco (SSD/HDD, TRIM, otimização agendada, tempo de boot e itens que atrasaram) e processos que consomem CPU em repouso. Botão **APLICAR ETAPA 2**: somente o que ainda não foi aplicado |
| **Modo CS2** | **JOGAR CS2 OTIMIZADO**: plano TURBO, serviços pausados e apps fechados; tudo volta ao fechar o jogo. Perfil do cs2.exe (prioridade Alta, GPU dedicada, tela cheia exclusiva opcional). Perfis de CPU **Competitivo** e **Eficiente** (menos calor) e estacionamento de núcleos |
| **Benchmark** | PresentMon (Intel, MIT, sem injeção no jogo): FPS médio, 1% low, 0,1% low, frametime médio/P99/variação, travadas, latência, CPU ou GPU como limite, modo de apresentação, uso de CPU/GPU/RAM e processos concorrentes. Comparação com veredito que ignora diferenças dentro do ruído |
| **Testes A/B** | Timer 0,5 ms (alterna automaticamente 4 × 20 s e decide pelo 1% low), HAGS, tela cheia exclusiva e perfil de CPU |
| **Ajustes rejeitados** | 15 ajustes populares avaliados e não aplicados, com o motivo |

**Mudanças de comportamento:** o timer de 0,5 ms não é mais ativado automaticamente (só se o teste A/B aprovar), e o cache em espera da RAM não é mais esvaziado em jogos, porque isso causa travadas.

---

## 4. Segurança (como o programa protege o seu PC)

- **Prévia obrigatória**: toda ação mostra a chave de registro, o valor atual e o novo valor antes de executar; você pode desmarcar item a item.
- **Ponto de restauração** do Windows antes de alterações críticas (quando executado como administrador).
- **Backup de cada valor original** em `%LOCALAPPDATA%\TurboBoostPro\backup\journal.json`, salvo **antes** de cada escrita. Valores que não existiam são apagados na reversão (o registro volta exatamente ao estado anterior).
- **Nunca toca**: Windows Defender, Firewall, Windows Update (só é parado enquanto o cache de downloads é limpo e reiniciado logo em seguida), processos críticos do sistema, `System32`, `WinSxS` (só via DISM oficial), Prefetch e `Windows.old`.
- **Nada é irreversível nas configurações**: serviços nunca são "Desativados" (no máximo "Manual"), inicialização usa o mesmo mecanismo do Gerenciador de Tarefas, plano de energia é uma cópia (o original não é editado).
- Arquivos do usuário só vão para a **Lixeira**. A limpeza de lixo exclui apenas caches/temporários dentro das pastas listadas e preserva temporários com menos de 24 h.

---

## 5. Expectativas realistas (leia antes de medir resultados)

Análise honesta, para você avaliar o ganho com números e não com sensação:

| Situação | Ganho esperado |
|---|---|
| PC com muitos apps em segundo plano, plano Equilibrado, Game DVR ativo | **Alto**: 5-20% de FPS médio e, principalmente, menos travadas (1% low) |
| Notebook na tomada que estava em modo economia | **Alto** (o plano de energia faz muita diferença) |
| PC já limpo, desktop com plano Alto Desempenho | **Baixo**: 0-5%. O gargalo passa a ser hardware |
| Windows em HD mecânico, 1 pente de RAM, 8 GB ou menos | Software **não resolve**. O diagnóstico aponta o upgrade com maior retorno |

Pontos de atenção:
- **"Liberar RAM"** ajuda quando a RAM está quase cheia antes de abrir um jogo. Com RAM sobrando, não muda FPS (RAM livre não acelera nada por si só).
- **Tela cheia exclusiva (FSO off)** e **HAGS** variam por jogo/GPU: teste com e sem. Por isso não entram no pacote automático.
- **Plano TURBO em notebook** aumenta temperatura e consumo de bateria.
- Meça com uma ferramenta de FPS (ex.: CapFrameX, overlay da NVIDIA/AMD) antes e depois, no mesmo trecho do jogo.

---

## 6. Solução de problemas

| Problema | Solução |
|---|---|
| Temperatura "N/D" | Muitas placas-mãe não expõem sensor ao Windows. Abra o [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) (gratuito, offline): o app lê os sensores dele automaticamente |
| GPU "sem leitura" | Atualize o driver de vídeo (os contadores "GPU Engine" do Windows exigem WDDM 2.x) |
| Ponto de restauração falha | Segurança › "Ativar Proteção do Sistema (C:)" |
| SmartScreen/antivírus alerta o .exe | Executáveis PyInstaller não assinados costumam gerar falso positivo. Assine com certificado de code signing para distribuir |
| Algo ficou estranho após otimizar | Segurança › RESTAURAR TUDO e reinicie. Se necessário, use o ponto de restauração do Windows |

---

## 7. Estrutura do projeto

```
turbo_boost_pro/
├── main.py                    # ponto de entrada
├── tbp/
│   ├── config.py              # caminhos e preferências
│   ├── utils.py               # comandos, PowerShell, log
│   ├── core/                  # lógica (sem interface)
│   │   ├── journal.py         # backup + reversão de tudo
│   │   ├── registry.py        # acesso ao registro
│   │   ├── tweaks.py          # catálogo de otimizações do registro
│   │   ├── engine.py          # TURBO MODE, modos, sessões de jogo, modo automático
│   │   ├── monitor.py         # CPU/GPU/RAM/disco/temperatura em tempo real
│   │   ├── power.py           # plano de energia
│   │   ├── memory.py          # liberação de RAM
│   │   ├── processes.py       # processos e apps de fundo
│   │   ├── services.py        # serviços
│   │   ├── startup.py         # inicialização
│   │   ├── cleaner.py         # limpeza
│   │   ├── network.py         # DNS e rede
│   │   ├── storage.py         # SSD/HDD
│   │   ├── gaming.py          # perfis de jogos, Steam
│   │   ├── diagnostics.py     # ANALISAR MEU PC + relatório
│   │   ├── restore_point.py   # ponto de restauração
│   │   └── winapi.py          # chamadas nativas (admin, timer, broadcast)
│   └── ui/                    # interface CustomTkinter
├── tests/                     # testes de backup/reversão (pytest)
├── build.bat · run.bat        # build e execução
├── turbo_boost_pro.spec       # PyInstaller
└── installer/turbo_boost_pro.iss  # instalador Inno Setup
```

Testes: `pip install pytest` e `python -m pytest tests`.

Dados do app: `%LOCALAPPDATA%\TurboBoostPro` (backups, logs, relatórios, perfis e preferências).
