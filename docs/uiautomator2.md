# Backend Android com UI Automator

O executor oferece `backend="uiautomator2"`, usando o cliente Python
[OpenATX uiautomator2](https://github.com/openatx/uiautomator2). O serviço Java
é iniciado no dispositivo por ADB e permanece ativo durante uma inspeção ou
jornada. O MCP, o cliente Python e o loop de decisões ficam no container; o app,
o emulador e o serviço Android ficam fora dele.

Essa abordagem usa a [acessibilidade do Android](https://developer.android.com/training/testing/other-components/ui-automator),
sem acessar a árvore de widgets do Flutter ou o Dart VM Service. Pode alcançar
apps de outros frameworks e builds release que exponham controles acessíveis.
O experimento deste repositório usa o APK debug já instalado; não constitui uma
validação de todos os frameworks ou de um APK release.

## Conexão

No host, mantenha o emulador conectado ao ADB e abra o app instalado:

```sh
adb devices
adb -s emulator-5556 shell am start -W \
  -n com.example.automation_with_llm_and_jev/.MainActivity
docker compose up --build -d --wait
```

O cliente no container acessa o servidor ADB do host em
`host.docker.internal:5037`. `ANDROID_ADB_SERVER_HOST` e
`ANDROID_ADB_SERVER_PORT` permitem alterar esse destino. A conexão foi
verificada no Docker Desktop deste Mac, sem expor o ADB na rede local nem criar
`adb forward` para o Dart. Para Linux, use `compose.host.yaml`, que seleciona
`127.0.0.1:5037`. Não é preciso instalar o binário `adb` na imagem: `adbutils`
implementa o protocolo do servidor ADB.

No MCP HTTP em `http://127.0.0.1:8765/mcp`, chame `inspect_ui` com:

```json
{
  "backend": "uiautomator2",
  "device_id": "emulator-5556",
  "app_id": "com.example.automation_with_llm_and_jev"
}
```

O retorno informa os IDs, rótulos, ações e estados observados. Para
`run_ui_task`, adicione a esse objeto o `goal`, os 16 `inputs` e as 19
`success_conditions` de `automation/examples/generic_journey.json`, e passe
explicitamente `min_confidence: 0.55`, `max_steps: 60` e `provider: "jev"`.
Não envie `vm_uri` nesse backend. O limite global continua sendo 40 segundos,
incluindo a inicialização do worker/serviço. Preparação não conta como teste.

## Seleção e execução

O driver usa `resource-id` quando disponível. Sem ele, aceita texto ou descrição
de acessibilidade únicos e fornece um ID gerado em `inspect_ui`. No app Flutter
deste repositório, os `Semantics.identifier` existentes aparecem como
`resource-id`, permitindo reutilizar o cenário sem modificar o APK.

Antes de interagir, verifica o pacote em primeiro plano, a unicidade do seletor
e se o controle continua habilitado. Toques usam o centro dos limites visíveis;
preenchimentos usam `setText`, inclusive com Unicode. A observação seguinte e
as asserções verificam o efeito. O helper permanece ativo durante a jornada,
mas cada RPC usa sua conexão de transporte; isso não implica um socket HTTP
permanente. Não há repetição automática de gestos quando uma resposta falha.

O worker é isolado em subprocesso para que timeout/cancelamento não deixe uma
fila de comandos executando depois do encerramento. Um gesto já enviado pode
ter ocorrido: inspecione o estado antes de repetir uma execução interrompida.
O processo encerra o helper que iniciou, sem fechar o app. A versão 3.7.1 está
fixada porque o driver usa a primitiva RPC sem retry dessa biblioteca.

## Limitações

- Controles desenhados sem informação de acessibilidade podem não aparecer.
  Não há reconhecimento visual/OCR ou fallback por coordenadas fornecidas pelo modelo.
- IDs duplicados ou controles interativos sem seletor estável interrompem a execução.
- Nesta primeira versão há toque e preenchimento. Não há scroll automático,
  gestos complexos, navegação entre apps ou tratamento automático de permissões.
- A leitura se restringe ao pacote informado. Campos de senha e fixtures são
  redigidos nos relatórios; a inspeção omite valores de campos de texto.
- O lock do MCP serializa chamadas nesse servidor. Evite outros controladores
  de UI Automator/Marionette operando simultaneamente no mesmo dispositivo.

Na primeira inspeção deste APK debug, a árvore Android estava vazia embora a
tela estivesse visível. Abrir o app novamente com o helper de acessibilidade
já ativo fez os controles aparecerem. Esse detalhe é distinto de precisar
recompilar ou de conectar uma VM: o APK instalado foi reutilizado. O backend
não força esse reinício, pois isso descartaria o estado atual da jornada.

As sessões de `inspect_ui` e `run_ui_task` são independentes. Cada jornada
reutiliza um único helper e um cliente Jev; não reinicia o serviço a cada toque.

## Experimento

O comparativo usa o mesmo cenário JSON e o mesmo provedor Jev, com
`min_confidence=0.55`, `max_steps=60` e orçamento global de 40 segundos.
A referência anterior com Marionette no Docker passou 19/19 asserções em
36 ações e 18.225,42 ms, trace
`automation/artifacts/20261023T040554Z-1be3e283.json`.
Uma execução por backend serve como verificação funcional e medição exploratória,
sem estabelecer uma média de desempenho.

Em 23/10/2026 (UTC), o novo backend executou a jornada via `run_ui_task` no
endpoint MCP do container, após `inspect_ui` confirmar a Home sem resultado
anterior. Não houve build, instalação ou alteração do APK. Jev escolheu todos
os gestos da jornada: 16 preenchimentos, 12 checkboxes, navegação A–G,
confirmação em G e retorno à Home.

| Medida | Marionette (referência anterior) | UI Automator |
| --- | ---: | ---: |
| Status | `passed` | `passed` |
| Asserções | 19/19 | 19/19 |
| Ações executadas | 36 | 36 |
| Tempo total | 18.225,42 ms | 34.485,23 ms |
| Inicialização | 56,98 ms | 1.206,43 ms |
| Leitura da UI: média | 46,08 ms | 92,12 ms |
| Toque: média | 20,38 ms | 322,71 ms |
| Preenchimento: média | 117,01 ms | 350,58 ms |
| Inferência Jev: média | 220,64 ms | 207,16 ms |
| Chamadas ao Jev | 36 | 43 |

Os dois testes usaram `jev-1.14.0`, confiança mínima configurada de **0,55** e
limite de **60** passos. A menor confiança retornada no teste UI Automator foi
**0,78**. Sete decisões foram descartadas porque a UI mudou entre a inferência
e a verificação anterior ao gesto; não foram sete gestos adicionais.

O backend Android levou aproximadamente **1,89 vez** o tempo da referência.
O custo maior observado está principalmente nas interações e leituras nativas,
além da inicialização e das inferências descartadas. Este resultado valida a
alternativa agnóstica, mas não demonstra ganho de velocidade sobre Marionette.
Não houve bloqueio nem redução de confiança ou alteração das asserções.

Trace: `automation/artifacts/20261023T044221Z-9c26372c.json` no host,
`/app/automation/artifacts/20261023T044221Z-9c26372c.json` no container.
O tempo total inclui inicialização e encerramento da sessão do teste; as
inspeções MCP anterior e posterior e os probes de desenvolvimento são separados.
