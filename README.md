# Laya vs Jev: controle de ventilador e lâmpada via MQTT

Comparação de dois modelos de linguagem decidindo, em tempo real, se um **ventilador** e uma **lâmpada** devem ficar ligados, a partir de um sensor de temperatura e de presença ligado a um ESP32.

- **Laya** (`multilingual`): rodou localmente numa Jetson Nano de 8gb, na GPU (`cuda`).
- **Jev** (`jev-1.13-free`): chamado por API HTTP na nuvem.

**Resultado em uma frase:** o Jev acertou 100% das decisões do ventilador e da lâmpada; o Laya acertou 100% da lâmpada, mas errou o ventilador em todas as variantes testadas (26% a 61%), apesar de ser 3 a 5 vezes mais rápido.

---

## Sumário

1. [Arquitetura](#arquitetura)
2. [Regra esperada](#regra-esperada)
3. [Como o teste foi feito](#como-o-teste-foi-feito)
4. [Rodadas](#rodadas)
5. [Resultados](#resultados)
6. [Análise](#análise)
7. [Limitações](#limitações)
8. [Como reproduzir](#como-reproduzir)
9. [Arquivos](#arquivos)
10. [Próximos passos](#próximos-passos)

---

## Arquitetura

```
ESP32 (sensor de temperatura + presença, relé do ventilador, LED da lâmpada)
   │  publica JSON em casa/sala1/dados
   ▼
Broker MQTT (localhost:1883)
   │
   ▼
Jetson: script Python
   ├─ monta um texto descrevendo a sala
   ├─ pergunta ao modelo (Laya local ou Jev via API)
   ├─ publica o comando em casa/sala1/rele/set e casa/sala1/led/set
   └─ publica o log da decisão em casa/jetson/decisao
```

Tópicos MQTT usados:

| Tópico | Uso |
|---|---|
| `casa/sala1/dados` | leitura do ESP32 (JSON: `t`, `tok`, `d`, `base`, `p`, `ok`, `rele`, `led`) |
| `casa/sala1/status` | `online`/`offline` do ESP32 |
| `casa/sala1/rele/set` | comando do ventilador (`ON`/`OFF`) |
| `casa/sala1/led/set` | comando da lâmpada (`ON`/`OFF`) |
| `casa/jetson/auto` | liga/desliga a automação do script |
| `casa/jetson/decisao` | log JSON de cada decisão |
| `casa/jetson/status` | `online`/`offline` do script (com *last will*) |

Parâmetros: decisão a cada 2 s no máximo, dados considerados velhos após 10 s, leitura só é usada se o sensor reporta `ok`.

## Projeto do hardware (ESP32)

A montagem do ESP32 usada nos testes tem repositório próprio, com firmware, diagrama de ligação e fotos:

**[alinembs/SalaIOT-ESP32](https://github.com/alinembs/SalaIOT-ESP32)**

Resumo do que o repositório descreve (consulte o README dele para os detalhes e o diagrama Fritzing):

| Componente | Função | Ligação |
|---|---|---|
| ESP32 DOIT DevKit V1 | Controlador (Wi-Fi + MQTT), PlatformIO + Arduino | |
| HC-SR04 | Presença, por distância | TRIG GPIO5, ECHO GPIO18 (com divisor resistivo 1k/2k, pois o ECHO sai em 5 V) |
| DS18B20 | Temperatura | DATA GPIO4, com resistor de 4,7k para 3V3 |
| LED | Indicação (lâmpada) | GPIO2 (LED da placa) ou externo com 220 Ω |
| Módulo relé | Saída de carga (ventilador) | IN GPIO13 |

Como a presença funciona: o firmware mede a distância do ambiente vazio (calibração no boot ou pelo comando `calibrar`) e considera que há alguém quando a leitura fica bem abaixo dessa base. Nos logs deste teste, `cm` fica em torno de 277 a 280 com a sala vazia e em torno de 25 a 40 com uma pessoa na frente do sensor.

O firmware publica os dados a cada 1 s e quando a presença muda, e usa a mesma base de tópicos (`casa/sala1`) que os scripts deste repositório. Para o teste, a automação fixa do firmware foi desligada, de modo que só o modelo comandava as saídas.

## Regra esperada

Quem liga e desliga é o **modelo**. A regra abaixo só aparece no log (`esperado_rele`, `esperado_led`), para marcar acerto; ela **não** manda comando.

| Situação | Ventilador | Lâmpada |
|---|---|---|
| Pessoa e 30 °C ou mais | ligado | ligada |
| Sem pessoa e 30 °C ou mais | ligado | desligada |
| Pessoa e menos de 30 °C | desligado | ligada |
| Sem pessoa e menos de 30 °C | desligado | desligada |

Não existe a opção "manter": o modelo é obrigado a escolher `ligar` ou `desligar` a cada leitura. A confiança é registrada, mas não bloqueia o comando. A automação fixa do ESP32 foi desligada durante os testes, e um script rodou por vez.

Cada modelo recebe duas perguntas do tipo `choice` (`ventilador` e `lampada`), com os rótulos `ligar` e `desligar`.

## Como o teste foi feito

Em todas as rodadas, o cenário real foi o mesmo, executado à mão em frente ao sensor:

1. Temperatura alta no início, sem ninguém.
2. Temperatura diminui.
3. Pessoa na frente do sensor, com temperatura baixa.
4. Temperatura aumenta com a pessoa na frente.
5. Pessoa sai, com temperatura alta.
6. Temperatura diminui, sem ninguém.

A temperatura varia sozinha durante o teste, então o cenário não é idêntico amostra a amostra entre rodadas.

## Rodadas

| Rodada | Modelo | Entrada | Amostras |
|---|---|---|---|
| Jev rodada 1 | `jev-1.13-free` (API) | texto único (temperatura + presença) | 33 |
| Jev rodada 2 | `jev-1.13-free` | texto único | 46 |
| Laya v1 | `multilingual` (local, GPU) | texto único | 57 |
| Laya v2 `numero` | `multilingual` | estado separado por pergunta, temperatura em número | 97 |
| Laya v2 `faixa` | `multilingual` | estado separado, "quente/fria" calculado no código | 85 |

**Laya v2** separa o que cada pergunta enxerga: o ventilador só vê a temperatura e a lâmpada só vê a presença (uma chamada por pergunta).

- `numero`: o modelo recebe "A temperatura é 35.1 graus Celsius." e precisa comparar com 30.
- `faixa`: o script converte a temperatura em "A sala está quente." ou "A sala está fria.". Aqui o limite de 30 °C fica no código, então **não é comparável diretamente ao Jev**.

Todos os números abaixo foram calculados por script a partir dos logs das rodadas.

## Resultados

### Resultado geral

| Rodada | Ventilador | Lâmpada | Latência mín – mediana – máx |
|---|---|---|---|
| Jev rodada 1 | 33/33 (100%) | 33/33 (100%) | 569 – 633 – 829 ms |
| Jev rodada 2 | 46/46 (100%) | 46/46 (100%) | 566 – 628 – 1029 ms |
| **Jev total** | **79/79 (100%)** | **79/79 (100%)** | 566 – 633 – 1029 ms |
| Laya v1 | 15/57 (26%) | 57/57 (100%) | 103 – 121 – 257 ms |
| Laya v2 `numero` | 37/97 (38%) | 97/97 (100%) | 160 – 196 – 296 ms |
| Laya v2 `faixa` | 52/85 (61%) | 85/85 (100%) | 158 – 191 – 240 ms |

A latência da v2 do Laya inclui duas chamadas por ciclo.

### Ventilador por situação esperada

| Rodada | Esperado LIGAR (≥ 30 °C) | Esperado DESLIGAR (< 30 °C) | Respostas do modelo |
|---|---|---|---|
| Jev total | 48/48 | 31/31 | ligar 48, desligar 31 |
| Laya v1 | 8/43 | 7/14 | ligar 15, desligar 42 |
| Laya v2 `numero` | 8/68 | 29/29 | ligar 8, desligar 89 |
| Laya v2 `faixa` | 52/52 | 0/33 | ligar 85, desligar 0 |

### Ventilador perto do limite (29,8 a 30,4 °C)

| Rodada | Acertos |
|---|---|
| Jev total | 50/50 |
| Laya v1 | 5/12 |
| Laya v2 `numero` | 21/38 |
| Laya v2 `faixa` | 18/49 |

## Análise

**Jev**
- Acertou as 79 leituras do ventilador e da lâmpada, em duas rodadas.
- Fez 8 comandos de ventilador e 12 de lâmpada, todos corretos.
- Respeitou o limite nas passagens por 30 °C (30,0 ou 30,1 °C ligou; 29,9 °C desligou).
- A segunda rodada teve 5 ciclos de pessoa entrando e saindo com a temperatura em torno de 29,9 °C, e manteve 100%.

**Laya**
- A lâmpada ficou em 100% em todas as rodadas.
- O ventilador tem comportamento praticamente constante, não decisão:
  - **v1:** seguiu a presença (ligar com pessoa, desligar sem), ignorando a temperatura.
  - **v2 `numero`:** quase sempre `desligar` (89 de 97).
  - **v2 `faixa`:** sempre `ligar` (85 de 85), inclusive com o texto "A sala está fria".
- Os 61% da `faixa` enganam: um sistema que sempre liga teria o mesmo resultado, porque 52 das 85 amostras pediam ligar.
- Separar o estado por pergunta corrigiu a contaminação da v1 (o ventilador deixou de seguir a presença), mas não resolveu o ventilador.
- Com a entrada binária "quente/fria", o ventilador continuou falhando, então comparar número com limite não parece ser a causa principal. Os dados não indicam qual é: pode ser o texto da pergunta, os rótulos, a ordem dos `criteria` ou o checkpoint (hipóteses não testadas).
- Na carga do modelo aparece o aviso `this checkpoint ships invalid temperatures or values outside [0.5, 5]`, que indica confiança não calibrada.

**Velocidade e dependências**
- O Laya é cerca de 3 a 5 vezes mais rápido (mediana de 121 a 196 ms contra 633 ms) e roda sem internet nem chave.
- O Jev depende de internet e de chave de API (`OPENCODE_API_KEY`).
- A velocidade do Laya não compensa o erro no ventilador.

**Confiança**
- No Jev a confiança é sempre 1,0, então não informa nada.
- No Laya a calibração é inválida, então os valores não devem ser lidos como probabilidade.
- Nenhuma das duas serve como critério de decisão.

## Limitações

- O Jev teve duas rodadas; cada variante do Laya teve uma. O padrão de erro do Laya é sistemático (saída quase constante), então repetir dificilmente mudaria a conclusão, mas não foi medido.
- A temperatura evolui sozinha, então há poucas amostras exatamente no limite de 30 °C, e amostras repetidas com a mesma entrada. Contar por transição é mais justo do que por amostra.
- A variante `faixa` não é comparável diretamente ao Jev (o limite está no código).
- Os dados vêm de um único ambiente (um ESP32, uma sala, uma Jetson).
- O script de diagnóstico offline do Laya (`diag_laya.py`) foi escrito, mas **não foi executado**.

## Como reproduzir

Pré-requisitos: broker MQTT em `localhost:1883`, ESP32 montado e gravado conforme [SalaIOT-ESP32](https://github.com/alinembs/SalaIOT-ESP32) e publicando nos tópicos acima com a automação fixa desligada, e Python 3.

```bash
pip install paho-mqtt        # os dois scripts
pip install laya             # somente para o Laya (GPU/CUDA na Jetson)
```

**Jev** (requer chave de API):

```bash
export OPENCODE_API_KEY=...   # não commitar a chave
python3 test_jev.py
```

**Laya v1** (texto único):

```bash
python3 test-laya.py
```

**Laya v2** (estado separado por pergunta):

```bash
python3 test_laya_v2.py                     # variante numero
VARIANTE=faixa python3 test_laya_v2.py      # variante faixa
```

A v2 imprime um placar de acertos ao encerrar com `Ctrl+C`. Rode um script por vez e execute a mesma sequência de 6 etapas em cada um.

Cada decisão é impressa e publicada em `casa/jetson/decisao` como JSON, por exemplo:

```json
{"modelo": "jev-1.13-free", "t": 34.9, "p_esp": 0, "cm": 280.1,
 "ventilador": "ligar", "conf_ventilador": 1,
 "lampada": "desligar", "conf_lampada": 1,
 "rele": "ON", "led": "OFF",
 "esperado_rele": "ON", "esperado_led": "OFF",
 "ok_rele": true, "ok_led": true, "ms": 829}
```

## Arquivos

Os nomes abaixo são os dos scripts como foram executados; ajuste ao salvar no repositório.

| Arquivo | Conteúdo |
|---|---|
| `test_jev.py` | teste do Jev (API) |
| `test-laya.py` | Laya v1 (texto único) |
| `test_laya_v2.py` | Laya v2 (estado separado; variantes `numero` e `faixa`) |
| `diag_laya.py` | diagnóstico offline do Laya, sem MQTT (ainda não executado) |
| `logs/` | saídas brutas das 5 rodadas (sugestão) |

## Próximos passos

- Executar o `diag_laya.py` para comparar formulações da pergunta do ventilador (`ligar`/`desligar` vs `sim`/`nao`, ordem dos `criteria`, texto espelhando o da lâmpada) e a resposta completa do modelo.
- Se nenhuma formulação funcionar, deixar o limite de temperatura como regra em código e usar o Laya só para o que ele mostrou fazer bem (presença e linguagem).
- Repetir as rodadas e testar a borda com histerese em torno de 30 °C para ver a estabilidade do liga/desliga.
- Em produção, manter uma regra fixa de proteção (por exemplo, ventilador ligado acima de uma temperatura de segurança) independentemente do modelo.