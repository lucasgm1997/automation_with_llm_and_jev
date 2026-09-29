import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:marionette_flutter/marionette_flutter.dart';

import 'automation/semantic_snapshot.dart';
import 'demo_journeys.dart';
import 'generic_feature.dart';

void main() {
  if (kDebugMode) {
    MarionetteBinding.ensureInitialized();
    registerAutomationSemantics();
  } else {
    WidgetsFlutterBinding.ensureInitialized();
  }

  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Flutter Demo',
      theme: ThemeData(colorScheme: .fromSeed(seedColor: Colors.deepPurple)),
      home: const MyHomePage(title: 'Flutter Demo Home Page'),
    );
  }
}

class MyHomePage extends StatefulWidget {
  const MyHomePage({super.key, required this.title});

  final String title;

  @override
  State<MyHomePage> createState() => _MyHomePageState();
}

class _MyHomePageState extends State<MyHomePage> {
  GenericJourneyResult? _lastJourney;

  Future<void> _openGenericJourney() async {
    setState(() => _lastJourney = null);
    final result = await Navigator.of(context).push<GenericJourneyResult>(
      MaterialPageRoute(builder: (_) => const JourneyWithGenericPageAndField()),
    );
    if (mounted && result != null) setState(() => _lastJourney = result);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        backgroundColor: Theme.of(context).colorScheme.inversePrimary,

        title: identifiedText('home.title', widget.title),
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              identifiedControl(
                'generic.open',
                FilledButton.icon(
                  onPressed: _openGenericJourney,
                  icon: const Icon(Icons.route),
                  label: const Text('Iniciar jornada A → B → C'),
                ),
              ),
              const SizedBox(height: 16),
              identifiedControl(
                'journeys.open',
                IconButton(
                  tooltip: 'Abrir jornadas de login e produtos',
                  icon: const Icon(Icons.science_outlined),
                  onPressed: () => Navigator.of(context).push(
                    MaterialPageRoute(builder: (_) => const DemoJourneys()),
                  ),
                ),
              ),
              if (_lastJourney case final result?) ...[
                const SizedBox(height: 24),
                identifiedText(
                  'generic.result',
                  'Jornada A → B → C concluída.\n${result.summary}',
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
