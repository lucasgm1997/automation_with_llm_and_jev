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
    expect(
      tester
          .widget<FloatingActionButton>(find.byType(FloatingActionButton))
          .key,
      isNull,
    );
    performSemanticInteraction('counter.increment', 'tap');
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
    expect(
      () => performSemanticInteraction('disabled', 'tap'),
      throwsStateError,
    );
    semantics.dispose();
  });

  testWidgets('duplicate, missing and non-actionable identifiers cannot act', (
    tester,
  ) async {
    final semantics = tester.ensureSemantics();
    try {
      var taps = 0;
      Widget button() => MergeSemantics(
        child: Semantics(
          identifier: 'duplicate',
          child: ElevatedButton(
            onPressed: () => taps++,
            child: const Text('Tap'),
          ),
        ),
      );
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Column(
              children: [
                button(),
                button(),
                Semantics(
                  identifier: 'content',
                  child: const Text('Read only'),
                ),
                Offstage(
                  child: Semantics(
                    identifier: 'hidden',
                    child: const Text('Hidden'),
                  ),
                ),
              ],
            ),
          ),
        ),
      );
      for (final id in ['duplicate', 'missing', 'content', 'hidden']) {
        expect(() => performSemanticInteraction(id, 'tap'), throwsStateError);
      }
      expect(taps, 0);
    } finally {
      semantics.dispose();
    }
  });

  testWidgets('semantic focus selects an editable field without any key', (
    tester,
  ) async {
    final semantics = tester.ensureSemantics();
    try {
      String? changed;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Column(
              children: [
                MergeSemantics(
                  child: Semantics(
                    identifier: 'field',
                    child: TextField(onChanged: (value) => changed = value),
                  ),
                ),
                MergeSemantics(
                  child: Semantics(
                    identifier: 'readonly',
                    child: const TextField(readOnly: true),
                  ),
                ),
              ],
            ),
          ),
        ),
      );
      expect(
        () => performSemanticInteraction('readonly', 'focus'),
        throwsStateError,
      );
      performSemanticInteraction('field', 'focus');
      await tester.pump();
      final node = (captureSemanticSnapshot()['nodes'] as List).singleWhere(
        (node) => node['id'] == 'field',
      );
      expect(node['focused'], true);
      expect(node['actions'], contains('fill'));
      tester.testTextInput.enterText('Filled through focus');
      await tester.pump();
      expect(changed, 'Filled through focus');
    } finally {
      semantics.dispose();
    }
  });
}
