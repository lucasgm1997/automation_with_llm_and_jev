import 'package:automation_with_llm_and_jev/automation/semantic_snapshot.dart';
import 'package:automation_with_llm_and_jev/main.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('login fields expose fill actions and redact passwords', (
    tester,
  ) async {
    final handle = tester.ensureSemantics();
    try {
      await tester.pumpWidget(const MyApp());
      await tester.tap(find.byKey(const ValueKey('journeys.open')));
      await tester.pumpAndSettle();
      Map<String, dynamic> node(String id) =>
          (captureSemanticSnapshot()['nodes'] as List).singleWhere(
                (node) => node['id'] == id,
              )
              as Map<String, dynamic>;
      expect(node('login.email')['actions'], contains('fill'));
      expect(node('login.password')['role'], 'textField');
      expect(node('login.password')['is_empty'], true);
      await tester.enterText(
        find.byKey(const ValueKey('login.email')),
        'invalid@example.test',
      );
      await tester.enterText(
        find.byKey(const ValueKey('login.password')),
        'Wrong123!',
      );
      await tester.pump();
      expect(node('login.password')['value'], '<redacted>');
      expect(node('login.password')['is_empty'], false);
      await tester.tap(find.byKey(const ValueKey('login.submit')));
      await tester.pumpAndSettle();
      expect(node('login.error')['label'], contains('Credenciais inválidas'));
      expect(find.byKey(const ValueKey('products.create')), findsNothing);
    } finally {
      handle.dispose();
    }
  });

  testWidgets('login, required product fields and creation work through UI', (
    tester,
  ) async {
    await tester.pumpWidget(const MyApp());
    await tester.tap(find.byKey(const ValueKey('journeys.open')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const ValueKey('login.email')),
      'dev@example.test',
    );
    await tester.enterText(
      find.byKey(const ValueKey('login.password')),
      'Demo123!',
    );
    await tester.tap(find.byKey(const ValueKey('login.submit')));
    await tester.pumpAndSettle();
    expect(find.text('Meus produtos'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('products.create')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('product.save')));
    await tester.pump();
    expect(find.text('Informe o nome do produto.'), findsOneWidget);
    await tester.enterText(
      find.byKey(const ValueKey('product.name')),
      'Cadeira',
    );
    await tester.enterText(find.byKey(const ValueKey('product.price')), '-2');
    await tester.tap(find.byKey(const ValueKey('product.save')));
    await tester.pump();
    expect(find.text('Informe um preço maior que zero.'), findsOneWidget);
    await tester.enterText(
      find.byKey(const ValueKey('product.price')),
      '25,50',
    );
    await tester.tap(find.byKey(const ValueKey('product.save')));
    await tester.pumpAndSettle();
    expect(find.text('Produto cadastrado: Cadeira'), findsOneWidget);
    expect(find.text('Cadeira'), findsOneWidget);
    expect(find.text('R\$ 25.50'), findsOneWidget);
  });
}
