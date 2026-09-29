import 'dart:math';

import 'package:flutter/material.dart';

const genericJourneyLabel = 'A → B → C → D → E → F → G';

typedef _Field = ({String id, String label});

class _Step {
  const _Step(
    this.id,
    this.title,
    this.fields,
    this.options, {
    this.wait = false,
  });

  final String id;
  final String title;
  final List<_Field> fields;
  final List<String> options;
  final bool wait;

  String get prefix => 'generic.$id';
}

const _steps = [
  _Step(
    'a',
    'Dados pessoais',
    [
      (id: 'text', label: 'Nome'),
      (id: 'email', label: 'E-mail'),
      (id: 'phone', label: 'Telefone'),
      (id: 'company', label: 'Empresa'),
    ],
    ['Aceito os termos', 'Receber atualizações'],
  ),
  _Step(
    'b',
    'Endereço',
    [
      (id: 'street', label: 'Rua'),
      (id: 'number', label: 'Número'),
      (id: 'city', label: 'Cidade'),
      (id: 'postal_code', label: 'CEP'),
    ],
    ['Endereço principal', 'Usar para cobrança'],
    wait: true,
  ),
  _Step(
    'c',
    'Contato',
    [
      (id: 'contact_name', label: 'Nome do contato'),
      (id: 'contact_phone', label: 'Telefone do contato'),
    ],
    ['Contato por e-mail', 'Contato por telefone'],
  ),
  _Step(
    'd',
    'Preferências',
    [
      (id: 'category', label: 'Categoria de interesse'),
      (id: 'notes', label: 'Preferências adicionais'),
    ],
    ['Receber novidades', 'Receber ofertas'],
  ),
  _Step(
    'e',
    'Entrega',
    [
      (id: 'recipient', label: 'Destinatário'),
      (id: 'instructions', label: 'Instruções de entrega'),
    ],
    ['Entregar na portaria', 'Avisar ao chegar'],
    wait: true,
  ),
  _Step(
    'f',
    'Revisão dos dados',
    [
      (id: 'reference', label: 'Referência do pedido'),
      (id: 'comments', label: 'Observações finais'),
    ],
    ['Revisei os dados', 'Confirmo minhas escolhas'],
  ),
];

class GenericJourneyResult {
  GenericJourneyResult({
    required Map<String, String> fields,
    required Map<String, bool> options,
  }) : fields = Map.unmodifiable(fields),
       options = Map.unmodifiable(options);

  final Map<String, String> fields;
  final Map<String, bool> options;

  String get summary => [
    'Opções marcadas: ${options.values.where((value) => value).length} de 12',
    for (final step in _steps) ...[
      '\nTela ${step.id.toUpperCase()} — ${step.title}',
      for (final field in step.fields)
        '${field.label}: ${fields['${step.prefix}.${field.id}'] ?? ''}',
      for (var index = 0; index < step.options.length; index++)
        '${step.options[index]}: ${options['${step.prefix}.option${index + 1}'] == true ? 'Marcada' : 'Desmarcada'}',
    ],
  ].join('\n');
}

class _Draft {
  final fields = <String, String>{};
  final options = <String, bool>{};
  final random = Random();

  GenericJourneyResult get result =>
      GenericJourneyResult(fields: fields, options: options);
}

class JourneyWithGenericPageAndField extends StatefulWidget {
  const JourneyWithGenericPageAndField({super.key});

  @override
  State<JourneyWithGenericPageAndField> createState() => _JourneyState();
}

class _JourneyState extends State<JourneyWithGenericPageAndField> {
  final _draft = _Draft();

  @override
  Widget build(BuildContext context) => _FormPage(index: 0, draft: _draft);
}

class _FormPage extends StatefulWidget {
  const _FormPage({required this.index, required this.draft});

  final int index;
  final _Draft draft;

  @override
  State<_FormPage> createState() => _FormPageState();
}

class _FormPageState extends State<_FormPage> {
  late final Map<String, TextEditingController> _controllers;
  bool _loading = false;
  bool _advancing = false;

  _Step get _step => _steps[widget.index];
  String get _nextLetter =>
      String.fromCharCode('A'.codeUnitAt(0) + widget.index + 1);

  @override
  void initState() {
    super.initState();
    _controllers = {
      for (final field in _step.fields)
        field.id: TextEditingController(
          text: widget.draft.fields['${_step.prefix}.${field.id}'] ?? '',
        ),
    };
  }

  @override
  void dispose() {
    for (final controller in _controllers.values) {
      controller.dispose();
    }
    super.dispose();
  }

  Future<void> _next() async {
    if (_advancing) return;
    _advancing = true;
    FocusScope.of(context).unfocus();
    try {
      if (_step.wait) {
        setState(() => _loading = true);
        await Future<void>.delayed(
          Duration(seconds: 1 + widget.draft.random.nextInt(2)),
        );
        if (!mounted) return;
        setState(() => _loading = false);
      }
      final result = await Navigator.of(context).push<GenericJourneyResult>(
        MaterialPageRoute(
          builder: (_) => widget.index == _steps.length - 1
              ? _ConfirmationPage(result: widget.draft.result)
              : _FormPage(index: widget.index + 1, draft: widget.draft),
        ),
      );
      if (mounted && result != null) Navigator.of(context).pop(result);
    } finally {
      _advancing = false;
    }
  }

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: !_loading,
    child: Scaffold(
      appBar: _pageAppBar(
        context,
        'Tela ${_step.id.toUpperCase()} — ${_step.title}',
        _step.prefix,
        widget.index == 0
            ? 'Voltar à página inicial'
            : 'Voltar à tela anterior',
        enabled: !_loading,
      ),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            _text('${_step.prefix}.progress', 'Etapa ${widget.index + 1} de 7'),
            const SizedBox(height: 16),
            Expanded(
              child: LayoutBuilder(
                builder: (context, constraints) {
                  // Two columns keep dense forms usable with the keyboard open.
                  final width = constraints.maxWidth >= 320
                      ? (constraints.maxWidth - 12) / 2
                      : constraints.maxWidth;
                  return SingleChildScrollView(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Wrap(
                          spacing: 12,
                          runSpacing: 16,
                          children: [
                            for (final field in _step.fields)
                              SizedBox(
                                width: width,
                                child: _control(
                                  '${_step.prefix}.${field.id}',
                                  TextField(
                                    controller: _controllers[field.id],
                                    enabled: !_loading,
                                    onChanged: (value) =>
                                        widget
                                                .draft
                                                .fields['${_step.prefix}.${field.id}'] =
                                            value,
                                    decoration: InputDecoration(
                                      labelText: field.label,
                                      border: const OutlineInputBorder(),
                                      isDense: true,
                                    ),
                                  ),
                                ),
                              ),
                          ],
                        ),
                        const SizedBox(height: 16),
                        for (
                          var index = 0;
                          index < _step.options.length;
                          index++
                        )
                          _checkbox(index),
                      ],
                    ),
                  );
                },
              ),
            ),
            if (_loading)
              Semantics(
                identifier: '${_step.prefix}.loading',
                label: 'Carregando. Aguarde para avançar à tela $_nextLetter.',
                liveRegion: true,
                excludeSemantics: true,
                child: const Padding(
                  padding: EdgeInsets.symmetric(vertical: 12),
                  child: Column(
                    children: [
                      LinearProgressIndicator(),
                      SizedBox(height: 8),
                      Text('Aguarde, preparando a próxima tela…'),
                    ],
                  ),
                ),
              ),
            const SizedBox(height: 12),
            SafeArea(
              top: false,
              child: _control(
                '${_step.prefix}.next',
                FilledButton(
                  onPressed: _loading ? null : _next,
                  child: Text('Ir para tela $_nextLetter'),
                ),
              ),
            ),
          ],
        ),
      ),
    ),
  );

  Widget _checkbox(int index) {
    final id = '${_step.prefix}.option${index + 1}';
    final selected = widget.draft.options[id] ?? false;
    return _control(
      id,
      CheckboxListTile(
        title: Text(_step.options[index]),
        value: selected,
        dense: true,
        contentPadding: EdgeInsets.zero,
        onChanged: _loading
            ? null
            : (value) =>
                  setState(() => widget.draft.options[id] = value ?? false),
        controlAffinity: ListTileControlAffinity.leading,
      ),
      value: selected ? 'Marcada' : 'Desmarcada',
    );
  }
}

class _ConfirmationPage extends StatelessWidget {
  const _ConfirmationPage({required this.result});

  final GenericJourneyResult result;

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: _pageAppBar(
      context,
      'Tela G — Confirmação',
      'generic.g',
      'Voltar à tela F',
    ),
    body: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _text(
            'generic.g.progress',
            'Etapa 7 de 7. Confira os dados e confirme.',
          ),
          const SizedBox(height: 16),
          Expanded(
            child: SingleChildScrollView(
              child: _text('generic.g.summary', result.summary),
            ),
          ),
          const SizedBox(height: 12),
          SafeArea(
            top: false,
            child: _control(
              'generic.g.confirm',
              FilledButton(
                onPressed: () => Navigator.of(context).pop(result),
                child: const Text('Confirmar e voltar à página inicial'),
              ),
            ),
          ),
        ],
      ),
    ),
  );
}

Widget _control(String id, Widget child, {String? value}) => MergeSemantics(
  child: Semantics(identifier: id, value: value, child: child),
);

Widget _text(String id, String text) => Semantics(
  identifier: id,
  label: text,
  excludeSemantics: true,
  child: Text(text),
);

AppBar _pageAppBar(
  BuildContext context,
  String title,
  String id,
  String backLabel, {
  bool enabled = true,
}) => AppBar(
  title: _text('$id.title', title),
  leading: _control(
    '$id.back',
    IconButton(
      tooltip: backLabel,
      icon: const Icon(Icons.arrow_back),
      onPressed: enabled ? () => Navigator.of(context).pop() : null,
    ),
  ),
);
