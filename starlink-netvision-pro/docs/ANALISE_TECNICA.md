# Análise técnica: Starlink Mini como única infraestrutura de rede

Levantamento feito antes do desenvolvimento, com base no código das bibliotecas usadas pela comunidade, nos descritores de protocolo extraídos da própria antena e em testes com servidor gRPC equivalente. Nada aqui depende de endpoint inventado.

## 1. O que a Starlink Mini expõe na rede local

| Item | Situação real |
|---|---|
| Documentação oficial da API local (kit residencial/Mini) | **Não existe.** A SpaceX não publica a API. |
| Interface disponível | Serviço **gRPC** sem autenticação na LAN, em `192.168.100.1:9200`, método `SpaceX.API.Device.Device/Handle`. É o canal usado pelo app oficial. |
| Definições do protocolo | Obtidas por **server reflection** do próprio equipamento. O programa não embute `.proto`; lê o que o firmware publica. |
| Bibliotecas usadas | `starlink-grpc-core` (status e histórico) e `yagrc` (reflection), mantidas pela comunidade (sparky8512/starlink-grpc-tools). |
| Interface web do roteador | Não há painel web com API de clientes. Configuração é feita pelo app Starlink. |
| SNMP, syslog, NetFlow, espelhamento de porta | **Não disponíveis.** |
| Logs de DNS dos aparelhos | **Não disponíveis.** |

### Dados efetivamente obtidos da antena (`get_status`, `get_history`)

- Estado (conectada, procurando, obstruída, sem satélites, inicializando etc.)
- ID, hardware, versão de firmware, país, tempo ligado
- **Throughput atual da rede inteira** (download e upload em bps, todos os aparelhos somados)
- Latência e taxa de perda até o PoP (gateway da Starlink)
- Obstrução (fração do céu, obstruída agora), azimute e elevação
- GPS (válido, nº de satélites)
- Alertas (aquecimento, temperatura, motor, mobilidade etc.)
- Histórico de ~15 min, segundo a segundo, com estatísticas calculadas pela antena

### Lista de clientes Wi-Fi (`wifi_get_clients`)

Os descritores extraídos da antena mostram que o protocolo tem o método `wifi_get_clients`, com estes campos por aparelho: `name`, `given_name`, `mac_address`, `ip_address`, `signal_strength`, `iface` (2,4/5 GHz), `rx_stats.bytes`, `tx_stats.bytes`, `associated_time_s`, `snr`.

**Limitação:** não há confirmação pública de que todo firmware da Mini responda a esse método, nem de qual endereço responde (a Mini integra antena e roteador). Por isso o programa:

1. testa, em ordem, os alvos configurados (padrão: `192.168.100.1:9200` e `192.168.1.1:9000`);
2. memoriza o primeiro que responder e mostra o resultado e o log da sondagem na página **Starlink Mini**;
3. se nenhum responder, usa o scanner local (item 2) sem perder funcionalidade.

## 2. Matriz de requisitos x fonte de dados

| Requisito | Pela Starlink? | Implementação no programa | Diferença / limitação |
|---|---|---|---|
| Status da antena | Sim | gRPC `get_status` a cada 2 s | Nenhuma |
| Dispositivos conectados | Parcial | API Starlink (se liberada) + **ARP ativo** (Npcap) ou **ICMP + tabela ARP do Windows** | O scanner vê aparelhos IPv4 ativos; um aparelho em repouso profundo pode demorar a aparecer |
| IP e MAC | Sim / scanner | API ou tabela ARP | Nenhuma |
| Nome do aparelho | Parcial | Nome DHCP da API; senão DNS reverso, mDNS e NetBIOS | Celulares raramente respondem; use **Renomear** |
| Fabricante | Não | Base OUI do Wireshark embutida no Scapy (offline) | iPhone/Android/Windows usam **MAC privado aleatório**: o fabricante fica oculto e o programa sinaliza isso |
| Novos dispositivos e desconexões | Não | Comparação entre varreduras (offline após 2 ausências) | Detecção em até 1 intervalo de varredura (60 s padrão) |
| Velocidade download/upload | Não (só uso atual) | Teste HTTP multi-conexão (Cloudflare, configurável) | Consome dados |
| Uso atual da rede toda | Sim | Throughput informado pela antena | Agregado; não separa por aparelho |
| Ping, jitter, perda | Sim (até o PoP) | Ping ICMP real (API `IcmpSendEcho`, sem admin) para 1.1.1.1 e 8.8.8.8 + ping da antena | Nenhuma |
| Histórico diário/mensal | Não (só 15 min) | SQLite local, agregado por minuto | Só registra enquanto o programa roda |
| Consumo do computador | Não | Contadores das placas de rede (psutil) | Nenhuma |
| Consumo da rede toda | Indireto | Integração do throughput da antena no tempo | Estimativa (amostragem a cada 2 s) |
| Consumo por aparelho | Parcial | Contadores `rx/tx` do roteador, quando `wifi_get_clients` responde | Sem a API, não há como medir por aparelho sem roteador próprio |
| Programas usando a internet (este PC) | Não | **Npcap**: captura só de cabeçalhos + dono da porta via tabela de conexões | Sem Npcap: modo básico (conexões ativas, sem bytes) |
| Serviços (YouTube, TikTok...) neste PC | Não | Respostas DNS e SNI do TLS (texto em claro) | **Estimativa**. CDNs compartilhadas reduzem a precisão |
| Serviços de outros aparelhos | Não | **DNS local opcional**: o aparelho usa este PC como DNS | Exige configurar o DNS no aparelho; não vê quem usa DNS criptografado (DoH/DoT) |

## 3. Por que o PC não enxerga o tráfego dos outros aparelhos

- O Wi-Fi WPA2/WPA3 cifra cada aparelho com chave própria; um PC comum não lê o tráfego alheio.
- O roteador da Mini não faz espelhamento de porta nem exporta fluxos ou logs.
- Placas Wi-Fi no Windows não operam em modo monitor de forma confiável.

Alternativas reais, da mais simples à mais completa:

1. **DNS local do NetVision** (incluído): identifica serviços por aparelho, sem volume exato.
2. Contadores por aparelho via `wifi_get_clients` (incluído, depende do firmware).
3. Roteador próprio com contabilidade por cliente (OpenWrt/MikroTik) atrás da Mini: dá volume exato por aparelho e por serviço. Exige hardware adicional; fora do escopo atual.

## 4. Privacidade e limites deliberados

- Nenhum conteúdo HTTPS é decifrado. Nada de payload é armazenado.
- Metadados usados: tamanho de pacote, IPs, portas, nome consultado no DNS e SNI do TLS (enviado em claro pelo próprio navegador).
- Toda identificação de serviço é marcada como estimativa, com nível de confiança (alta, média, baixa).

## 5. Privilégios no Windows

| Ação | Precisa de administrador? |
|---|---|
| Abrir o programa, Starlink, ping, scanner ICMP/ARP, teste de velocidade, histórico | Não |
| Inicializar com o Windows (registro `HKCU\...\Run`) | Não |
| Captura por aplicativo | Não, se o Npcap foi instalado **sem** "restringir a administradores" |
| Liberar o DNS local no Firewall | **Sim**, pedido via UAC só quando você clica no botão |

## 6. O que foi testado e como

| Área | Teste |
|---|---|
| Cliente Starlink | Servidor gRPC com **descritores reais extraídos da antena** e reflection, rodando como processo separado: status, histórico, lista Wi-Fi, fallback entre alvos e antena offline |
| Scanner | Parsers de `arp -a` (PT-BR), `route print`, `nbtstat`, `/proc/net/arp`; varredura real na rede do ambiente de teste |
| Fabricante e MAC privado | Base OUI real |
| Apps por processo | **Captura real** de pacotes com atribuição ao processo correto |
| DNS/SNI | Pacotes DNS e TLS ClientHello montados byte a byte e interpretados |
| DNS local | Encaminhamento real para servidor DNS upstream de teste |
| Ping | ICMP real (loopback); no Windows, a CI executa a API nativa `IcmpSendEcho` |
| Teste de velocidade | Download e upload reais contra servidor HTTP local |
| Banco e relatórios | Agregação diária/mensal, CSV e HTML |
| Executável | Build PyInstaller executado contra a antena de teste, sem erros de importação |

**Não testado neste ambiente** (exige o seu equipamento): resposta do firmware real da sua Mini ao `wifi_get_clients`, captura via Npcap em Wi-Fi no Windows 11 e notificações da bandeja do Windows. O workflow `.github/workflows/netvision-windows.yml` roda testes e gera o `.exe` em Windows real.
