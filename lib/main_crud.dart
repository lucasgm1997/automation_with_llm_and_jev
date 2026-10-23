import 'dart:convert';
import 'dart:developer' as developer;
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:marionette_flutter/marionette_flutter.dart';

import 'automation/semantic_snapshot.dart';
import 'demo_journeys.dart';

const crudApiUrl = String.fromEnvironment('CRUD_API_URL');

void main() {
  if (kDebugMode) {
    MarionetteBinding.ensureInitialized();
    registerAutomationSemantics();
  } else {
    WidgetsFlutterBinding.ensureInitialized();
  }
  runApp(const CrudApp());
}

class CrudApp extends StatefulWidget {
  const CrudApp({super.key});

  @override
  State<CrudApp> createState() => _CrudAppState();
}

class _CrudAppState extends State<CrudApp> {
  @override
  Widget build(BuildContext context) {
    return const Placeholder();
  }
}
