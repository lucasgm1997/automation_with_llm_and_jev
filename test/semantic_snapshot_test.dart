import 'package:automation_with_llm_and_jev/automation/semantic_snapshot.dart';
import 'package:automation_with_llm_and_jev/main.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('snapshot reads the actual accessible value after a UI tap', (
    tester,
  ) async {
    final semantics = tester.ensureSemantics();
    await tester.pumpWidget(const MyApp());

    Map<String, dynamic> node(String id) =>
        (captureSemanticSnapshot()['nodes'] as List).singleWhere(
              (node) => node['id'] == id,
            )
            as Map<String, dynamic>;

    expect(node('counter.value')['value'], '0');
    expect(node('counter.increment')['actions'], ['tap']);
    expect(node('counter.increment')['label'], 'Increment');
    expect(node('counter.increment')['key_count'], 1);
    await tester.tap(find.byKey(const ValueKey('counter.increment')));
    await tester.pump();
    expect(node('counter.value')['value'], '1');
    semantics.dispose();
  });

  testWidgets('disabled controls have no allowed tap action', (tester) async {
    final semantics = tester.ensureSemantics();
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: MergeSemantics(
            child: Semantics(
              identifier: 'disabled',
              child: const ElevatedButton(
                key: ValueKey('disabled'),
                onPressed: null,
                child: Text('Disabled'),
              ),
            ),
          ),
        ),
      ),
    );
    final node = (captureSemanticSnapshot()['nodes'] as List).singleWhere(
      (node) => node['id'] == 'disabled',
    );
    expect(node['enabled'], false);
    expect(node['actions'], isEmpty);
    semantics.dispose();
  });
}
