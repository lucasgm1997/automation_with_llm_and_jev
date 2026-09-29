import 'dart:convert';
import 'dart:io';

import 'package:automation_with_llm_and_jev/automation/semantic_snapshot.dart';
import 'package:automation_with_llm_and_jev/main.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> node(String id) =>
    (captureSemanticSnapshot()['nodes'] as List).singleWhere(
          (node) => node['id'] == id,
        )
        as Map<String, dynamic>;

Map<String, String> fixtureInputs() {
  final spec =
      jsonDecode(
            File('automation/examples/generic_journey.json').readAsStringSync(),
          )
          as Map;
  return {
    for (final input in spec['inputs'] as List)
      input['target'] as String: input['value'] as String,
  };
}

Future<void> tap(WidgetTester tester, String id) async {
  performSemanticInteraction(id, 'tap');
  await tester.pumpAndSettle();
}

Future<void> fill(WidgetTester tester, String id, String value) async {
  performSemanticInteraction(id, 'focus');
  await tester.pump();
  tester.testTextInput.enterText(value);
  await tester.pump();
}

void main() {
  testWidgets(
    'seven pages preserve every fixture and return to the same Home',
    (tester) async {
      final semantics = tester.ensureSemantics();
      try {
        final inputs = fixtureInputs();
        await tester.pumpWidget(const MyApp());
        final originalHome = tester.state(find.byType(MyHomePage));
        await tap(tester, 'generic.open');
        for (final page in ['a', 'b', 'c', 'd', 'e', 'f']) {
          final prefix = 'generic.$page';
          expect(
            node('$prefix.title')['label'],
            contains('Tela ${page.toUpperCase()}'),
          );
          for (final input in inputs.entries.where(
            (entry) => entry.key.startsWith('$prefix.'),
          )) {
            expect(node(input.key)['actions'], contains('fill'));
            await fill(tester, input.key, input.value);
            expect(node(input.key)['value'], input.value);
          }
          expect(node('$prefix.option1')['value'], 'Desmarcada');
          expect(node('$prefix.option2')['value'], 'Desmarcada');
          await tap(tester, '$prefix.option1');
          expect(node('$prefix.option1')['value'], 'Marcada');
          expect(node('$prefix.option2')['value'], 'Desmarcada');
          await tap(tester, '$prefix.option2');
          await tap(tester, '$prefix.next');
        }
        expect(node('generic.g.title')['label'], contains('Tela G'));
        for (final value in inputs.values) {
          expect(node('generic.g.summary')['label'], contains(value));
        }
        expect(
          node('generic.g.summary')['label'],
          contains('Opções marcadas: 12 de 12'),
        );
        await tap(tester, 'generic.g.confirm');
        expect(node('home.title')['label'], 'Flutter Demo Home Page');
        expect(
          node('generic.result')['label'],
          contains('Jornada A → B → C → D → E → F → G concluída.'),
        );
        for (final value in inputs.values) {
          expect(node('generic.result')['label'], contains(value));
        }
        expect(
          node('generic.result')['label'],
          contains('Opções marcadas: 12 de 12'),
        );
        expect(tester.state(find.byType(MyHomePage)), same(originalHome));
        expect(
          Navigator.of(tester.element(find.byType(MyHomePage))).canPop(),
          false,
        );
        await tap(tester, 'generic.open');
        expect(node('generic.a.text')['value'], isEmpty);
        expect(node('generic.a.option1')['value'], 'Desmarcada');
      } finally {
        semantics.dispose();
      }
    },
  );

  testWidgets(
    'going back and forward preserves data; a new journey resets it',
    (tester) async {
      final semantics = tester.ensureSemantics();
      try {
        await tester.pumpWidget(const MyApp());
        await tap(tester, 'generic.open');
        await fill(tester, 'generic.a.text', 'Preservar nome');
        await tap(tester, 'generic.a.next');
        await fill(tester, 'generic.b.street', 'Preservar endereço');
        await tap(tester, 'generic.b.option1');
        await tap(tester, 'generic.b.next');
        await tap(tester, 'generic.c.back');
        await tap(tester, 'generic.b.back');
        expect(node('generic.a.text')['value'], 'Preservar nome');
        await tap(tester, 'generic.a.next');
        expect(node('generic.b.street')['value'], 'Preservar endereço');
        expect(node('generic.b.option1')['value'], 'Marcada');
        expect(node('generic.b.option2')['value'], 'Desmarcada');
        await tap(tester, 'generic.b.option1');
        expect(node('generic.b.option1')['value'], 'Desmarcada');
        await tap(tester, 'generic.b.back');
        await tap(tester, 'generic.a.back');
        expect(find.bySemanticsIdentifier('generic.result'), findsNothing);
        await tap(tester, 'generic.open');
        expect(node('generic.a.text')['value'], isEmpty);
        await tap(tester, 'generic.a.next');
        expect(node('generic.b.street')['value'], isEmpty);
        expect(node('generic.b.option1')['value'], 'Desmarcada');
      } finally {
        semantics.dispose();
      }
    },
  );

  testWidgets(
    'only B and E wait; loading blocks duplicate actions and system back',
    (tester) async {
      final semantics = tester.ensureSemantics();
      try {
        await tester.pumpWidget(const MyApp());
        await tap(tester, 'generic.open');
        for (final page in ['a', 'b', 'c', 'd', 'e', 'f']) {
          final id = 'generic.$page.next';
          performSemanticInteraction(id, 'tap');
          // A second invocation in the same frame must not schedule another route.
          performSemanticInteraction(id, 'tap');
          await tester.pump();
          if (page == 'b' || page == 'e') {
            expect(
              node('generic.$page.loading')['label'],
              contains('Carregando'),
            );
            final nodes = captureSemanticSnapshot()['nodes'] as List;
            expect(
              nodes.every((node) => (node['actions'] as List).isEmpty),
              true,
            );
            expect(
              () => performSemanticInteraction(id, 'tap'),
              throwsStateError,
            );
            await tester.pump(const Duration(milliseconds: 900));
            expect(node('generic.$page.loading')['label'], contains('Aguarde'));
            await tester.binding.handlePopRoute();
            await tester.pump();
            expect(
              find.bySemanticsIdentifier('generic.$page.loading'),
              findsOneWidget,
            );
            await tester.pump(const Duration(milliseconds: 1100));
          } else {
            expect(
              find.bySemanticsIdentifier('generic.$page.loading'),
              findsNothing,
            );
          }
          await tester.pump(const Duration(milliseconds: 350));
          final next = String.fromCharCode(page.codeUnitAt(0) + 1);
          expect(
            node('generic.$next.title')['label'],
            contains('Tela ${next.toUpperCase()}'),
          );
        }
      } finally {
        semantics.dispose();
      }
    },
  );

  testWidgets(
    'disposing the journey during a wait does not navigate afterward',
    (tester) async {
      final semantics = tester.ensureSemantics();
      try {
        await tester.pumpWidget(const MyApp());
        await tap(tester, 'generic.open');
        await tap(tester, 'generic.a.next');
        performSemanticInteraction('generic.b.next', 'tap');
        await tester.pump();
        expect(node('generic.b.loading')['label'], contains('Carregando'));
        await tester.pumpWidget(const SizedBox.shrink());
        await tester.pump(const Duration(seconds: 3));
        expect(tester.takeException(), isNull);
        expect(find.byType(MyHomePage), findsNothing);
      } finally {
        semantics.dispose();
      }
    },
  );

  testWidgets(
    'four fields, checkboxes and next remain accessible with a phone keyboard',
    (tester) async {
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = const Size(390, 844);
      final semantics = tester.ensureSemantics();
      try {
        await tester.pumpWidget(const MyApp());
        await tap(tester, 'generic.open');
        tester.view.viewInsets = const FakeViewPadding(bottom: 300);
        await tester.pump();
        for (final field in ['text', 'email', 'phone', 'company']) {
          await fill(tester, 'generic.a.$field', 'Valor $field');
          expect(node('generic.a.$field')['value'], 'Valor $field');
        }
        expect(node('generic.a.option1')['actions'], contains('tap'));
        expect(node('generic.a.option2')['actions'], contains('tap'));
        expect(node('generic.a.next')['actions'], contains('tap'));
        expect(tester.takeException(), isNull);
      } finally {
        semantics.dispose();
        tester.view.resetViewInsets();
        tester.view.resetPhysicalSize();
        tester.view.resetDevicePixelRatio();
      }
    },
  );
}
