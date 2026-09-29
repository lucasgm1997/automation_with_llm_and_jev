import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:automation_with_llm_and_jev/main.dart';

void main() {
  testWidgets('Home opens the login journey and receives back navigation', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(const MyApp());
    expect(find.text('Flutter Demo Home Page'), findsOneWidget);
    await tester.tap(find.byIcon(Icons.science_outlined));
    await tester.pumpAndSettle();
    expect(find.text('Login'), findsOneWidget);
    await tester.tap(find.byIcon(Icons.arrow_back));
    await tester.pumpAndSettle();
    expect(find.text('Flutter Demo Home Page'), findsOneWidget);
  });
}
