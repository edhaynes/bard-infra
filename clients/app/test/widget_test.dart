import 'package:bard_pro/app_state.dart';
import 'package:bard_pro/main.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  // A connection-less state keeps the shell fully offline (no health probes, no
  // ssh, no registry call) so the widget test never touches the network.
  AppState offlineState() => AppState(connections: []);

  testWidgets('shell shows the six tabs', (tester) async {
    await tester.pumpWidget(BardProApp(state: offlineState()));
    await tester.pump();

    for (final label in ['Dashboard', 'Connections', 'Terminal', 'Chat', 'Models', 'Box']) {
      expect(find.text(label), findsWidgets, reason: 'missing $label tab');
    }
  });

  testWidgets('Box tab without a connection prompts to add one', (tester) async {
    await tester.pumpWidget(BardProApp(state: offlineState()));
    await tester.pump();

    await tester.tap(find.byIcon(Icons.inbox_outlined));
    await tester.pump();

    expect(find.textContaining('Add a connection first'), findsOneWidget);
  });

  testWidgets('Dashboard with no connection prompts to add one', (tester) async {
    await tester.pumpWidget(BardProApp(state: offlineState()));
    await tester.pump();

    expect(find.textContaining('No active connection'), findsWidgets);
  });

  testWidgets('Connections tab has an Add affordance', (tester) async {
    await tester.pumpWidget(BardProApp(state: offlineState()));
    await tester.pump();

    await tester.tap(find.byIcon(Icons.hub_outlined));
    await tester.pump();

    expect(find.text('Add'), findsOneWidget);
  });

  testWidgets('Chat tab renders an input when offline it prompts for a connection',
      (tester) async {
    await tester.pumpWidget(BardProApp(state: offlineState()));
    await tester.pump();

    await tester.tap(find.byIcon(Icons.chat_outlined));
    await tester.pump();

    expect(find.textContaining('No active connection'), findsWidgets);
  });
}
