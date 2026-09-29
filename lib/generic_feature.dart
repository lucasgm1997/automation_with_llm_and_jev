import 'package:flutter/material.dart';

class GenericJourneyResult {
  const GenericJourneyResult({
    required this.text,
    required this.optionOne,
    required this.optionTwo,
  });

  final String text;
  final bool optionOne;
  final bool optionTwo;

  String get summary =>
      'Texto: $text\n'
      'Opção 1: ${optionOne ? 'Marcada' : 'Desmarcada'}\n'
      'Opção 2: ${optionTwo ? 'Marcada' : 'Desmarcada'}';
}

class JourneyWithGenericPageAndField extends StatelessWidget {
  const JourneyWithGenericPageAndField({super.key});

  @override
  Widget build(BuildContext context) => const _PageA();
}

class _PageA extends StatefulWidget {
  const _PageA();

  @override
  State<_PageA> createState() => _PageAState();
}

class _PageAState extends State<_PageA> {
  final _text = TextEditingController();

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  Future<void> _next() async {
    FocusScope.of(context).unfocus();
    final result = await Navigator.of(context).push<GenericJourneyResult>(
      MaterialPageRoute(builder: (_) => _PageB(text: _text.text)),
    );
    if (mounted && result != null) Navigator.of(context).pop(result);
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: _pageAppBar(
      context,
      'Tela A',
      'generic.a',
      'Voltar à página inicial',
    ),
    body: ListView(
      padding: const EdgeInsets.all(24),
      children: [
        const Text('Etapa 1 de 3. Preencha o campo e avance para a tela B.'),
        const SizedBox(height: 24),
        _control(
          'generic.a.text',
          TextField(
            controller: _text,
            decoration: const InputDecoration(
              labelText: 'Texto genérico',
              border: OutlineInputBorder(),
            ),
          ),
        ),
        const SizedBox(height: 24),
        _control(
          'generic.a.next',
          FilledButton(onPressed: _next, child: const Text('Ir para tela B')),
        ),
      ],
    ),
  );
}

class _PageB extends StatefulWidget {
  const _PageB({required this.text});

  final String text;

  @override
  State<_PageB> createState() => _PageBState();
}

class _PageBState extends State<_PageB> {
  bool _optionOne = false;
  bool _optionTwo = false;

  Future<void> _next() async {
    final result = await Navigator.of(context).push<GenericJourneyResult>(
      MaterialPageRoute(
        builder: (_) => _PageC(
          result: GenericJourneyResult(
            text: widget.text,
            optionOne: _optionOne,
            optionTwo: _optionTwo,
          ),
        ),
      ),
    );
    if (mounted && result != null) Navigator.of(context).pop(result);
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: _pageAppBar(context, 'Tela B', 'generic.b', 'Voltar à tela A'),
    body: ListView(
      padding: const EdgeInsets.all(24),
      children: [
        const Text('Etapa 2 de 3. Escolha as opções e avance para a tela C.'),
        const SizedBox(height: 24),
        _control(
          'generic.b.option1',
          CheckboxListTile(
            title: const Text('Opção 1'),
            value: _optionOne,
            onChanged: (value) => setState(() => _optionOne = value ?? false),
            controlAffinity: ListTileControlAffinity.leading,
          ),
          value: _optionOne ? 'Marcada' : 'Desmarcada',
        ),
        _control(
          'generic.b.option2',
          CheckboxListTile(
            title: const Text('Opção 2'),
            value: _optionTwo,
            onChanged: (value) => setState(() => _optionTwo = value ?? false),
            controlAffinity: ListTileControlAffinity.leading,
          ),
          value: _optionTwo ? 'Marcada' : 'Desmarcada',
        ),
        const SizedBox(height: 24),
        _control(
          'generic.b.next',
          FilledButton(onPressed: _next, child: const Text('Ir para tela C')),
        ),
      ],
    ),
  );
}

class _PageC extends StatelessWidget {
  const _PageC({required this.result});

  final GenericJourneyResult result;

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: _pageAppBar(context, 'Tela C', 'generic.c', 'Voltar à tela B'),
    body: ListView(
      padding: const EdgeInsets.all(24),
      children: [
        const Text('Etapa 3 de 3. Confira os dados e confirme a jornada.'),
        const SizedBox(height: 24),
        _text('generic.c.summary', result.summary),
        const SizedBox(height: 24),
        _control(
          'generic.c.confirm',
          FilledButton(
            onPressed: () => Navigator.of(context).pop(result),
            child: const Text('Confirmar e voltar à página inicial'),
          ),
        ),
      ],
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
  String backLabel,
) => AppBar(
  title: _text('$id.title', title),
  leading: _control(
    '$id.back',
    IconButton(
      tooltip: backLabel,
      icon: const Icon(Icons.arrow_back),
      onPressed: () => Navigator.of(context).pop(),
    ),
  ),
);
