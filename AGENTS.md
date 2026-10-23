# Desenvolvimento neste projeto

## Arquitetura e padrões

- Para novos produtos e funcionalidades, siga o padrão **View → ViewModel →
  Service → DataSource**. Respeite eventuais orientações específicas do usuário
  para a tarefa e leia os documentos de arquitetura que ele indicar.
- **View:** apresenta a interface, observa o estado do ViewModel e encaminha
  as ações do usuário. Não faz chamadas HTTP nem acessa o DataSource diretamente.
- **ViewModel:** gerencia o estado da apresentação e as ações da tela,
  utilizando o Service para executar as operações da funcionalidade.
- **Service:** concentra as regras de negócio e a coordenação das operações,
  utilizando o DataSource para acessar os dados.
- **DataSource:** realiza o acesso à API e o tratamento dos dados de transporte,
  mantendo os detalhes HTTP fora da View, do ViewModel e do Service.
- Use **Riverpod** para resolver e fornecer as dependências. Disponibilize Dio,
  DataSources, Services e ViewModels por providers, compondo suas dependências
  por esses providers.
- Crie e obtenha as instâncias pelos **providers**, sem implementar singletons
  globais, campos `static instance`, factories que retornam uma instância global
  ou localizadores globais paralelos. Não crie um `ProviderContainer` global
  auxiliar para acessar dependências fora da composição da aplicação.
- Injete as dependências de Services e DataSources pelos construtores, a partir
  dos providers. Ao compor providers, use `ref.watch` para acompanhar as
  dependências; mantenha a recuperação delas explícita e substituível nos testes.
- Deixe o Riverpod controlar a criação, a reutilização e o ciclo de vida das
  instâncias. Não instancie Services, DataSources ou Dio a cada `build` da View.
  Providers podem ser declarados no nível superior do arquivo; essa declaração
  não deve esconder uma instância global criada fora do provider.
- Use **Riverpod também para gerenciamento de estado**. Exponha o estado do
  ViewModel por providers; a View deve usar **`ref.watch`** para acompanhar
  mudanças e reconstruir a interface. Use **`ref.read`** em callbacks de ações
  para acessar o ViewModel e disparar comandos; não o use como substituto de
  `ref.watch` quando a interface precisar reagir às mudanças de estado.
- Use **Dio** para consumir os endpoints HTTP. Forneça o cliente por um provider
  Riverpod e utilize-o nos DataSources.
- Em alterações de código existente, mantenha a refatoração necessária dentro
  do escopo da tarefa; não migre funcionalidades alheias automaticamente.
- `lib/main_crud.dart` é uma demonstração de coleta de evidências. Sua
  organização em um único arquivo não define a arquitetura de novos produtos.
- Confira a conformidade arquitetural no código: responsabilidades, direção
  das dependências e padrões solicitados. Testes de UI aprovados não comprovam
  essa conformidade.

## Ferramentas disponíveis, de uso opcional

Existe um MCP do projeto com três fontes independentes de evidências:
**UI**, **Console** e **Network**. Escolha as ferramentas quando ajudarem a
implementar, verificar um requisito ou investigar uma falha. Sua disponibilidade
não obriga chamar o MCP em toda tarefa, consultar as três fontes ou integrá-las
em uma execução conjunta. Um pedido explícito de teste deve ser atendido.

- UI: `inspect_ui` e `run_ui_task`.
- Console: `start_console_capture` e `read_console`.
- Network: `start_network_capture`, `list_network_requests` e `get_network_request`.
- Encerramento individual: `stop_capture`.

Ao decidir usar essas capacidades, consulte a skill
[`flutter-evidence`](.agents/skills/flutter-evidence/SKILL.md). Ela explica
conexão, escolha das ferramentas, limites e interpretação dos resultados.

O servidor preferencial deste projeto é `jev-e2e-docker`, por Streamable HTTP
em `http://127.0.0.1:8765/mcp`, configurado em `.codex/config.toml`.
O app e o emulador ficam no host; os coletores e o executor ficam no Docker.
A configuração não comprova que o serviço esteja ativo ou que a sessão atual
tenha carregado suas ferramentas. Verifique a disponibilidade quando precisar.

## Referências e validação

- [README](README.md): ambiente, SDK e retomada do app instalado.
- [Docker](docs/docker.md): iniciar o MCP e diagnosticar a conexão com a VM.
- [Console e Network](docs/runtime-evidence.md): cobertura e exemplos de consulta.
- `automation/examples/`: cenários de teste; adapte as asserções aos requisitos
  da tarefa, sem reutilizar um resultado anterior como aprovação da mudança.

Use análise estática e testes adequados à alteração. Ao relatar o resultado,
distinga o que foi implementado do que foi efetivamente verificado. Se o MCP
não tiver sido usado, não afirme validação em runtime por essas ferramentas.
