"""Opt-in live CRUD validation through the Docker MCP; not a server workflow.

Run with the automation environment's Python and --vm-uri reachable from Docker.
The app must already be running lib/main_crud.dart with a fresh CrudCrud endpoint.
"""

import argparse
import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parents[2]


def sanitize(value):
    # CrudCrud's endpoint capability is in its URL path, not an Authorization header.
    text = json.dumps(value, ensure_ascii=False)
    # Location responses use a relative /api/<credential>/... URL.
    text = re.sub(r"(/api/)[a-fA-F0-9]{32}(?=/|[\"\\])", r"\1<endpoint>", text)
    text = re.sub(r"(https?://[^/\s\"]+/)[A-Za-z0-9_+%-]+=/", r"\1<vm-token>/", text)
    return json.loads(text)


async def main(args):
    started = perf_counter()
    artifact = Path(args.output)
    artifact.parent.mkdir(parents=True, exist_ok=True)
    calls_path = artifact.with_suffix('.calls.jsonl')
    report = {'status': 'failed', 'mcp_endpoint': args.mcp, 'checks': [], 'calls': []}
    scenario = json.loads((ROOT / 'automation/examples/crud_evidence.json').read_text())

    def check(name, passed):
        report['checks'].append({'name': name, 'passed': bool(passed)})

    with calls_path.open('w') as journal:
        def event(**data):
            entry = {'at': datetime.now(timezone.utc).isoformat(), **sanitize(data)}
            journal.write(json.dumps(entry, ensure_ascii=False) + '\n')
            journal.flush()
            print(json.dumps(entry, ensure_ascii=False), flush=True)

        try:
            async with httpx.AsyncClient(timeout=90, trust_env=False) as client:
                async with streamable_http_client(args.mcp, http_client=client) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()

                        async def call(name, **arguments):
                            event(tool=name, phase='start', arguments=arguments)
                            start = perf_counter()
                            response = await session.call_tool(name, arguments)
                            result = response.structuredContent
                            report['calls'].append(sanitize({
                                'tool': name, 'arguments': arguments, 'result': result,
                                'is_error': response.isError,
                                'duration_ms': round((perf_counter() - start) * 1000, 2),
                            }))
                            event(tool=name, phase='end', is_error=response.isError)
                            if response.isError or result is None:
                                raise RuntimeError(f'MCP tool {name} failed; see calls in artifact.')
                            return result

                        captures = []
                        try:
                            console = await call('start_console_capture', vm_uri=args.vm_uri, ttl_seconds=300)
                            captures.append(console['capture_id'])
                            network = await call('start_network_capture', vm_uri=args.vm_uri, ttl_seconds=300)
                            captures.append(network['capture_id'])
                            cid, nid = captures
                            check('Console connected', console['status'] == 'capturing')
                            check('HTTP profiling available', 'capturing' in network['isolates'].values())
                            report['initial_ui'] = await call('inspect_ui', vm_uri=args.vm_uri)
                            report['ui_run'] = await call('run_ui_task', vm_uri=args.vm_uri,
                                **scenario, min_confidence=0.55, max_steps=60)
                            for _ in range(10):
                                network_rows = await call('list_network_requests', capture_id=nid, contains='evidence_products')
                                rows = sorted(network_rows['items'], key=lambda row: row['start_time_us'])
                                if len(rows) >= 5 and all(row['state'] == 'completed' for row in rows):
                                    break
                                await asyncio.sleep(1)
                            report['network'] = network_rows
                            details = [await call('get_network_request', capture_id=nid,
                                request_id=row['request_id'], include_bodies=True) for row in rows]
                            report['details'] = details
                            logs = await call('read_console', capture_id=cid, contains='crud-demo', limit=100)
                            report['console'] = logs
                            errors = await call('list_network_requests', capture_id=nid, errors_only=True)
                            report['http_errors'] = errors
                            report['final_ui'] = await call('inspect_ui', vm_uri=args.vm_uri)
                            check('UI: six assertions passed', report['ui_run']['status'] == 'passed' and
                                len(report['ui_run'].get('assertions', [])) == 6 and
                                all(a['passed'] for a in report['ui_run']['assertions']))
                            check('Five completed real HTTP requests', len(rows) == 5 and
                                all(row['state'] == 'completed' and row['duration_ms'] is not None for row in rows))
                            check('HTTP sequence POST GET DELETE GET GET',
                                [row['method'] for row in rows] == ['POST', 'GET', 'DELETE', 'GET', 'GET'])
                            check('HTTP statuses 201 200 200/204 200 404', len(rows) == 5 and
                                [row['status_code'] for row in rows[:2]] == [201, 200] and
                                rows[2]['status_code'] in [200, 204] and
                                [row['status_code'] for row in rows[3:]] == [200, 404])
                            check('Request details available', all(d['details_available'] for d in details))
                            if len(details) == 5:
                                created = json.loads(details[0]['response_body']['text'])
                                sent = json.loads(details[0]['request_body']['text'])
                                listed = json.loads(details[1]['response_body']['text'])
                                after = json.loads(details[3]['response_body']['text'])
                                check('POST body matches created product', sent['name'] == created['name'] and sent['price'] == created['price'])
                                check('Created ID present in GET list', any(r['_id'] == created['_id'] and r['name'] == created['name'] for r in listed))
                                check('DELETE targets created ID', rows[2]['url'].endswith('/' + created['_id']))
                                check('Created ID absent after DELETE', all(r['_id'] != created['_id'] for r in after))
                                check('404 targets same deleted ID', rows[4]['url'].endswith('/' + created['_id']))
                            check('Error filter isolates HTTP 404', len(errors['items']) == 1 and errors['items'][0]['status_code'] == 404)
                            check('Console includes stdout and structured Logging',
                                {'Stdout', 'Logging'} <= {r['source'] for r in logs['items']})
                            check('Console confirms CRUD success', any('CRUD_SUCCESS' in r.get('message', '') for r in logs['items']))
                            check('Expected error includes stack trace', any(r['source'] == 'Logging' and
                                'EXPECTED_HTTP_ERROR' in r.get('message', '') and r.get('error') and
                                'main_crud.dart' in (r.get('stack_trace') or '') for r in logs['items']))
                            check('No unexpected app failure logged', not any(
                                any(marker in r.get('message', '') for marker in ['CRUD_FAILED', 'PROBE_FAILED', 'CLEANUP_FAILED'])
                                for r in logs['items']))
                            check('Evidence not truncated', not logs['history_truncated'] and not network_rows['history_truncated'] and not logs['has_more'])
                            report['status'] = 'passed' if all(c['passed'] for c in report['checks']) else 'failed'
                        finally:
                            for capture_id in captures:
                                await call('stop_capture', capture_id=capture_id)
        except Exception as exc:
            report['status'] = 'failed'
            report['error'] = sanitize(f'{type(exc).__name__}: {exc}')
        finally:
            report['total_ms'] = round((perf_counter() - started) * 1000, 2)
            artifact.write_text(json.dumps(sanitize(report), indent=2, ensure_ascii=False) + '\n')
            event(status=report['status'], checks_passed=sum(c['passed'] for c in report['checks']),
                  checks_total=len(report['checks']), artifact=str(artifact), total_ms=report['total_ms'])
    return report['status'] == 'passed'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-uri', required=True)
    parser.add_argument('--mcp', default='http://127.0.0.1:8765/mcp')
    parser.add_argument('--output', default=str(ROOT / 'automation/artifacts/crud-evidence-smoke.json'))
    raise SystemExit(0 if asyncio.run(main(parser.parse_args())) else 1)
