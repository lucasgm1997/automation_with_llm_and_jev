// Controlled fixture for validating the collectors against a real Dart VM.
// No Marionette, log collector, HTTP interceptor or third-party package.
// Intentionally exercises stdout rather than replacing it with a logger.
// ignore_for_file: avoid_print
// Run: dart --enable-vm-service=0 runtime_evidence_probe.dart
// Start the MCP captures with the VM URI, then GET the printed /trigger URL.
import 'dart:convert';
import 'dart:developer' as developer;
import 'dart:io';

Future<void> main() async {
  final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
  final client = HttpClient();
  final base = 'http://127.0.0.1:${server.port}';
  print('EVIDENCE_PROBE_TRIGGER $base/trigger');
  await for (final request in server) {
    if (request.uri.path == '/trigger') {
      // Handle without blocking the server from answering the fixture requests.
      () async {
        print('EVIDENCE_STDOUT: action started');
        stderr.writeln('EVIDENCE_STDERR: controlled diagnostic');
        developer.log(
          'EVIDENCE_LOGGING: controlled validation failure',
          name: 'evidence.probe',
          level: 1000,
          error: 'EVIDENCE_ERROR',
          stackTrace: StackTrace.current,
        );
        for (final path in ['/ok', '/fail']) {
          final outgoing = await client.getUrl(
            Uri.parse('$base$path?token=probe-secret&source=fixture'),
          );
          outgoing.headers.set('Authorization', 'Bearer probe-secret');
          final response = await outgoing.close();
          await response.transform(utf8.decoder).join();
          print('EVIDENCE_HTTP: $path ${response.statusCode}');
        }
        request.response.write('probe complete');
        await request.response.close();
      }();
    } else if (request.uri.path == '/ok' || request.uri.path == '/fail') {
      () async {
        request.response.statusCode = request.uri.path == '/ok' ? 200 : 400;
        request.response.headers.contentType = ContentType.json;
        request.response.headers.set('Set-Cookie', 'session=probe-secret');
        request.response.write('{"message":"');
        await request.response.flush();
        await Future<void>.delayed(const Duration(milliseconds: 150));
        request.response.write(
          '${request.uri.path == '/ok' ? 'ok' : 'validation_failed'}",'
          '"password":"probe-secret"}',
        );
        await request.response.close();
      }();
    } else {
      request.response.statusCode = 404;
      await request.response.close();
    }
  }
}
