import 'package:automation_with_llm_and_jev/automation/semantic_snapshot.dart';
import 'package:automation_with_llm_and_jev/main.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> node(String id) =>
    (captureSemanticSnapshot()['nodes'] as List).singleWhere(
          (node) => node['id'] == id,
        )
        as Map<String, dynamic>;

Future<void> tap(WidgetTester tester, String id) async {
  performSemanticInteraction(id, 'tap');
  await tester.pumpAndSettle();
}

Future<void> fill(WidgetTester tester, String value) async {
  performSemanticInteraction('generic.a.text', 'focus');
  await tester.pump();
  tester.testTextInput.enterText(value);
  await tester.pump();
}

void main() {
  testWidgets(
    'A, independent checkboxes in B and C return a result to the same Home',
    (tester) async {
      final semantics = tester.ensureSemantics();
      try {
        await tester.pumpWidget(const MyApp());
        final originalHome = tester.state(find.byType(MyHomePage));
        await tap(tester, 'generic.open');
        expect(node('generic.a.title')['label'], 'Tela A');
        expect(node('generic.a.text')['actions'], contains('fill'));
        await fill(tester, 'Texto de teste');
        expect(node('generic.a.text')['value'], 'Texto de teste');
        await tap(tester, 'generic.a.next');

        expect(node('generic.b.title')['label'], 'Tela B');
        expect(node('generic.b.option1')['value'], 'Desmarcada');
        expect(node('generic.b.option2')['value'], 'Desmarcada');
        await tap(tester, 'generic.b.option1');
        expect(node('generic.b.option1')['value'], 'Marcada');
        expect(node('generic.b.option2')['value'], 'Desmarcada');
        await tap(tester, 'generic.b.option2');
        await tap(tester, 'generic.b.option1');
        expect(node('generic.b.option1')['value'], 'Desmarcada');
        expect(node('generic.b.option2')['value'], 'Marcada');
        await tap(tester, 'generic.b.option1');
        await tap(tester, 'generic.b.next');

        expect(node('generic.c.title')['label'], 'Tela C');
        expect(node('generic.c.summary')['label'], contains('Texto de teste'));
        await tap(tester, 'generic.c.confirm');
        expect(node('home.title')['label'], 'Flutter Demo Home Page');
        expect(
          node('generic.result')['label'],
          contains('Jornada A → B → C concluída.'),
        );
        expect(
          node('generic.result')['label'],
          contains('Texto: Texto de teste'),
        );
        expect(node('generic.result')['label'], contains('Opção 1: Marcada'));
        expect(node('generic.result')['label'], contains('Opção 2: Marcada'));
        expect(tester.state(find.byType(MyHomePage)), same(originalHome));
        expect(
          Navigator.of(tester.element(find.byType(MyHomePage))).canPop(),
          false,
        );

        await tap(tester, 'generic.open');
        expect(node('generic.a.text')['value'], isEmpty);
        await tap(tester, 'generic.a.next');
        expect(node('generic.b.option1')['value'], 'Desmarcada');
        expect(node('generic.b.option2')['value'], 'Desmarcada');
      } finally {
        semantics.dispose();
      }
    },
  );

  testWidgets(
    'back navigation keeps previous values and cancellation has no result',
    (tester) async {
      final semantics = tester.ensureSemantics();
      try {
        await tester.pumpWidget(const MyApp());
        await tap(tester, 'generic.open');
        await fill(tester, 'Preservar texto');
        await tap(tester, 'generic.a.next');
        await tap(tester, 'generic.b.option1');
        await tap(tester, 'generic.b.next');
        await tap(tester, 'generic.c.back');
        expect(node('generic.b.option1')['value'], 'Marcada');
        expect(node('generic.b.option2')['value'], 'Desmarcada');
        await tap(tester, 'generic.b.back');
        expect(node('generic.a.text')['value'], 'Preservar texto');
        await tap(tester, 'generic.a.back');
        expect(node('home.title')['label'], 'Flutter Demo Home Page');
        expect(find.bySemanticsIdentifier('generic.result'), findsNothing);
        expect(
          Navigator.of(tester.element(find.byType(MyHomePage))).canPop(),
          false,
        );
      } finally {
        semantics.dispose();
      }
    },
  );
}
