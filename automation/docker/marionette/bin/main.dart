// The pinned upstream package supplies the stdio MCP server.
import 'dart:io';
import 'package:marionette_mcp/src/mcp_server_runner.dart';

Future<void> main() async {
  exitCode = await runMcpServer(logLevel: 'WARNING');
}
