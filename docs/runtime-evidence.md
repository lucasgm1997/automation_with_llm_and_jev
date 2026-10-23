# Console e Network para desenvolvimento agêntico

São ferramentas independentes à disposição do agente. O agente implementa a
feature, verifica o comportamento no aplicativo e consulta UI, Console ou
Network conforme precisar. Não há sessão de teste obrigatória, integração por
tentativa nem relatório combinado gerado automaticamente. A coleta também
acompanha interações manuais.

O coletor usa o Dart VM Service diretamente. Não lê a janela do Debug Console
nem a página do DevTools: consome os streams de runtime e o perfil HTTP que
alimentam essas ferramentas. Funciona sem a instrumentação Marionette para
essas fontes. A inspeção de UI continua com seu backend próprio.

## Iniciar

Atualize o serviço Docker com `docker compose up --build -d --wait` e reconecte
o cliente MCP para descobrir as ferramentas. O endpoint continua sendo
`http://127.0.0.1:8765/mcp`. Não são necessários API key de LLM, Dart ou Python
no host para executar os coletores no Docker.

O app precisa estar aberto com VM Service acessível. Reutilize o processo de
descoberta e forwarding descrito no [README](../README.md). Em Docker Desktop,
use `host.docker.internal` no lugar do loopback da URI encaminhada. No modo
host, mantenha `127.0.0.1`. Se houver redirecionamento para DDS, forneça a URI
do DDS acessível do container, conforme o [diagnóstico Docker](docker.md).

Chame `start_console_capture` com:

```json
{
  "vm_uri": "http://host.docker.internal:39581/TOKEN=/",
  "ttl_seconds": 1800
}
```

Guarde o `capture_id` retornado. Para `start_network_capture`, envie os mesmos
argumentos e guarde seu outro ID. É possível usar somente uma das fontes.
O início retorna capacidades disponíveis; `capturing` descreve o coletor,
não significa que uma feature passou nem que todos os isolates têm suporte.

O estado das capturas é do processo MCP: permanece entre chamadas HTTP e
conexões de clientes. O servidor deve continuar rodando para coletar. Encerrar
o processo restaura o profiling habilitado pelo coletor quando a VM ainda está
acessível e perde o histórico local em memória.

## Console

Depois de reproduzir o problema, chame `read_console`:

```json
{
  "capture_id": "ID_DO_CONSOLE",
  "after_cursor": 0,
  "limit": 50,
  "contains": "Exception"
}
```

Os registros incluem origem, horário disponível, isolate, mensagem e, para
Logging, nível, logger, erro e stack trace quando presentes. Também é possível
filtrar `source` por `Stdout`, `Stderr`, `Logging` ou `Flutter.Error` e informar
`min_level` de 0 a 2000. Stdout/Stderr não recebem nível inferido: usar esse
filtro exclui mensagens sem nível conhecido. Cada WriteEvent é um fragmento de
saída; uma linha pode chegar em mais de um evento.

`Stdout`/`Stderr` dependem do embedder. `Logging` recebe eventos de
`dart:developer.log`; bibliotecas que não encaminham seus logs para uma fonte
exposta não aparecerão automaticamente. Eventos estruturados `Flutter.Error`
são capturados quando emitidos pelo framework; a ferramenta não altera a
configuração de tratamento de erros nem pausa o app em exceções. Erros que
somente aparecem na saída textual continuam disponíveis como Stdout/Stderr.

Não garante recuperar histórico anterior à assinatura; a VM/DDS pode entregar
eventos que estavam em buffer. Não coleta mensagens do compilador/IDE,
saída do `flutter run` no host, nem logcat de componentes nativos. A ausência
de logs não comprova ausência de erros de reatividade ou de lógica.

## Network

Chame `list_network_requests`:

```json
{
  "capture_id": "ID_DO_NETWORK",
  "after_cursor": 0,
  "limit": 50,
  "errors_only": true
}
```

`errors_only` seleciona falhas de transporte e status HTTP >= 400; `contains`
filtra texto dos metadados, inclusive endpoint. O resultado contém método,
URL, status, início/fim, tamanhos declarados e estado `pending`, `completed`
ou `failed`. Um HTTP 400 pode estar `completed`: a transferência terminou,
embora a resposta indique uma falha HTTP.

`duration_ms` mede o início da requisição até o término da resposta, incluindo
o download; não confunde o fim do envio com a conclusão da resposta. Requisições
pendentes têm duração final nula. São tempos observados da aplicação, sem
incluir inferência de modelo ou ações do agente.

Para investigar uma requisição, use seu `request_id` em `get_network_request`:

```json
{
  "capture_id": "ID_DO_NETWORK",
  "request_id": "ID_RETORNADO_PELA_LISTAGEM",
  "include_bodies": true
}
```

Headers e eventos são consultados sob demanda. Os corpos são opcionais:
`include_bodies` tem padrão `false`. Previews textuais são limitados; binários
e corpos acima de 32 KiB são omitidos. Corpos só podem ser consultados enquanto
a captura está conectada e a entrada ainda existe no profiler da VM.

O coletor habilita `ext.dart.io.httpEnableTimelineLogging`, usa
`ext.dart.io.getHttpProfile` com `updatedSince` e consulta
`ext.dart.io.getHttpProfileRequest` para detalhes. Polling: uma vez por segundo.
Captura requisições novas após a inicialização, sem importar o histórico já
existente nem limpar o perfil do DevTools. Requests anteriores, inclusive os
já em andamento ao iniciar, não fazem parte da captura.

Abrange clientes que alimentam o profiling do Dart (`dart:io`, como HttpClient,
e clientes integrados via `http_profile`). Não promete cobertura de WebViews,
plugins de rede nativos, chamadas de outro processo ou mensagens WebSocket;
esta primeira implementação coleta HTTP. Isolates sem as extensões retornam
`http_profiling_unavailable`; falhas de leitura retornam `read_failed`. Verifique
esses estados ao interpretar uma lista vazia.

## Consultas, encerramento e limites

- Use `next_cursor` como `after_cursor` para buscar novidades. Consultas não
  consomem registros. Não misture cursores entre capturas. Ao trocar filtros,
  volte a zero se quiser pesquisar todo o histórico retido.
- No Network, uma requisição pendente pode reaparecer com cursor mais recente
  quando seus metadados mudarem. A identificação da requisição permanece igual.
- `stop_capture({"capture_id": "..."})` encerra só aquela captura. Logs e
  metadados já coletados permanecem consultáveis; detalhes HTTP ao vivo não.
- O TTL padrão é 30 minutos, configurável de 10 segundos a 4 horas. Começar
  novamente a mesma fonte/URI ativa reutiliza a captura e não renova o TTL.
- Há até oito registros de captura; ao atingir o limite, novas capturas
  substituem registros inativos antigos. Cada captura retém até 500 itens.
  `evicted`, `events_dropped` e `history_truncated` indicam perda de histórico.
- Hot restart com a mesma conexão provoca nova descoberta dos isolates de rede.
  Se a VM desconectar, o estado vira `disconnected`; inicie outra captura com a
  URI atual. Não há reconexão silenciosa nem junção de históricos de VMs.
- Ao parar Network, os flags de profiling que esta captura habilitou são
  restaurados. Os que já estavam habilitados permanecem assim. Como esse estado
  é compartilhado pela VM, evite alterná-lo simultaneamente em outros profilers
  ou iniciar coletores duplicados por URIs diferentes da mesma VM. Nunca é
  chamado `clearHttpProfile`.
- Credenciais comuns são redigidas em URLs, headers, JSON e texto antes de
  retornar/armazenar evidências. Isso é uma proteção de melhor esforço: logs e
  conteúdos de aplicação podem conter dados sensíveis com nomes desconhecidos.
- Não há chamada automática a LLM, gravação automática em arquivos ou inclusão
  desses dados no contexto do Jev. O agente consulta explicitamente as ferramentas.

## Validação reproduzível

`automation/examples/runtime_evidence_probe.dart` produz logs de stdout,
stderr e `dart:developer.log` com stack trace, além de respostas HTTP 200 e 400
com download atrasado. Ele não usa Marionette, interceptor nem coletor de logs.

```sh
dart --enable-vm-service=0 automation/examples/runtime_evidence_probe.dart
```

O programa imprime a URI da VM e a URL `/trigger`. Inicie as capturas pelo MCP
usando a URI da VM (ajustada para acesso do Docker), e acesse a URL `/trigger`
com `curl` no host. Consulte Console e Network. A resposta 400 tem o corpo
`validation_failed`; a senha, o token e os cookies de teste devem aparecer
redigidos. Encerre uma captura e repita o trigger: a outra deve continuar.
Finalize o programa com Ctrl+C depois de parar as capturas.

Validação realizada em 23/10/2026 pelo endpoint MCP HTTP do Docker:

- O app Flutter instalado no `emulator-5556` aceitou a conexão dos dois
  coletores e a inspeção de UI, sem reconstruir ou modificar o APK.
- A fixture Dart confirmou requests reais HTTP 200/400, duração incluindo
  download, filtros de erro, detalhes de resposta e redaction das credenciais.
- Foram recebidos Stdout, Stderr e Logging com erro e stack trace.
- Parar Console manteve Network coletando novas requisições; o histórico do
  Console permaneceu consultável sem receber as novas mensagens.
- O teste de integração HTTP cobre persistência entre chamadas stateless,
  consulta durante o lock da UI e restauração do profiler no shutdown.

O resultado desse teste de desenvolvimento está em
`automation/artifacts/runtime-evidence-smoke.json`. Esse arquivo foi salvo pelo
cliente de validação; as ferramentas não criam relatórios por execução.

As fontes são o [protocolo Dart VM Service](https://github.com/dart-lang/sdk/blob/main/runtime/vm/service/service.md#streamlisten),
as [extensões de profiling HTTP](https://github.com/dart-lang/sdk/blob/main/runtime/vm/service/service_extension.md#gethttpprofile)
e a [cobertura de rede documentada pelo Flutter](https://docs.flutter.dev/tools/devtools/network#what-network-traffic-is-recorded).
