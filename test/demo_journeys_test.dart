import 'package:automation_with_llm_and_jev/automation/semantic_snapshot.dart';
import 'package:automation_with_llm_and_jev/main.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('login fields expose fill actions and redact passwords', (
    tester,
  ) async {
    final handle = tester.ensureSemantics();
    try {
      await tester.pumpWidget(const MyApp());
      await tester.tap(find.bySemanticsIdentifier('journeys.open'));
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
        find.bySemanticsIdentifier('login.email'),
        'invalid@example.test',
      );
      await tester.enterText(
        find.bySemanticsIdentifier('login.password'),
        'Wrong123!',
      );
      await tester.pump();
      expect(node('login.password')['value'], '<redacted>');
      expect(node('login.password')['is_empty'], false);
      await tester.tap(find.bySemanticsIdentifier('login.submit'));
      await tester.pumpAndSettle();
      expect(node('login.error')['label'], contains('Credenciais inválidas'));
      expect(find.bySemanticsIdentifier('products.create'), findsNothing);
    } finally {
      handle.dispose();
    }
  });

  testWidgets('login, required product fields and creation work through UI', (
    tester,
  ) async {
    final handle = tester.ensureSemantics();
    try {
      await tester.pumpWidget(const MyApp());
      await tester.tap(find.bySemanticsIdentifier('journeys.open'));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.bySemanticsIdentifier('login.email'),
        'dev@example.test',
      );
      await tester.enterText(
        find.bySemanticsIdentifier('login.password'),
        'Demo123!',
      );
      await tester.tap(find.bySemanticsIdentifier('login.submit'));
      await tester.pumpAndSettle();
      expect(find.text('Meus produtos'), findsOneWidget);
      await tester.tap(find.bySemanticsIdentifier('products.create'));
      await tester.pumpAndSettle();
      await tester.tap(find.bySemanticsIdentifier('product.save'));
      await tester.pump();
      expect(find.text('Informe o nome do produto.'), findsOneWidget);
      await tester.enterText(
        find.bySemanticsIdentifier('product.name'),
        'Cadeira',
      );
      await tester.enterText(find.bySemanticsIdentifier('product.price'), '-2');
      await tester.tap(find.bySemanticsIdentifier('product.save'));
      await tester.pump();
      expect(find.text('Informe um preço maior que zero.'), findsOneWidget);
      await tester.enterText(
        find.bySemanticsIdentifier('product.price'),
        '25,50',
      );
      await tester.tap(find.bySemanticsIdentifier('product.save'));
      await tester.pumpAndSettle();
      expect(find.text('Produto cadastrado: Cadeira'), findsOneWidget);
      expect(find.text('Cadeira'), findsOneWidget);
      expect(find.text('R\$ 25.50'), findsOneWidget);
    } finally {
      handle.dispose();
    }
  });
}
