// Android istemcisinin ağ katmanını (ApiClient) GERÇEK çalışan backend'e karşı sınar.
// Kullanım: dart run tool/connect_check.dart http://127.0.0.1:8000
import 'dart:io';

import 'package:dio/dio.dart';

import 'package:ai_video_factory/core/api_core.dart';

Future<void> main(List<String> args) async {
  final base = args.isNotEmpty ? args[0] : 'http://127.0.0.1:8000';
  final store = MemoryTokenStore();
  var expired = false;
  final api = ApiClient(baseUrl: base, tokens: store, onSessionExpired: () => expired = true);
  final results = <String, bool>{};
  void check(String name, bool ok, [String extra = '']) {
    results[name] = ok;
    stdout.writeln('${ok ? "OK  " : "FAIL"} $name $extra');
  }

  final h = await api.health();
  check('health', h['ok'] == true, '(${h['version']})');
  final email = 'dart_${DateTime.now().millisecondsSinceEpoch}@example.com';
  final u = await api.register(email, 'Passw0rd!dart', 'Dart Test');
  check('register+token', u['email'] == email);
  check('me', (await api.me())?['email'] == email);
  try {
    await ApiClient(baseUrl: base, tokens: MemoryTokenStore()).get('/api/v1/projects');
    check('unauth rejected', false);
  } on ApiException catch (e) {
    check('unauth rejected', e.status == 401 && e.code == 'auth_required');
  }
  // erişim token'ı bozulunca otomatik yenileme
  store.access = 'broken.token.value';
  final dash = await api.get('/api/v1/dashboard') as Map;
  check('auto refresh on 401', dash.containsKey('videos_total') && !expired && store.access != 'broken.token.value');
  final est = await api.post('/api/v1/projects/estimate', body: {
    'topic': 'Bağlantı testi', 'duration': 20, 'quality_tier': 'draft', 'media_mode': 'slideshow', 'platforms': ['youtube']
  }) as Map;
  check('estimate', est['items'] is List && (est['items'] as List).isNotEmpty);
  final created = await api.post('/api/v1/projects', headers: {'Idempotency-Key': 'dart-$email'}, body: {
    'topic': 'Dart istemci bağlantı testi konusu', 'category': 'Bilim', 'duration': 15, 'quality_tier': 'draft', 'media_mode': 'slideshow', 'platforms': []
  }) as Map;
  final pid = created['project']['id'] as String;
  check('create project', pid.isNotEmpty);
  var sawProgress = false;
  var ended = false;
  await for (final ev in api.sse('/api/v1/projects/$pid/stream')) {
    if (ev['_end'] == true) {
      ended = true;
      break;
    }
    if (ev['progress'] != null) sawProgress = true;
  }
  check('sse progress+end', sawProgress && ended);
  final p = await api.get('/api/v1/projects/$pid') as Map;
  check('final status', p['status'] == 'NEEDS_REVIEW', '(${p['status']}, skor ${p['quality_score']})');
  final media = await api.get('/api/v1/projects/$pid/media') as Map;
  final r = await api.dio.get<List<int>>(media['video']['path'] as String,
      options: Options(responseType: ResponseType.bytes));
  check('video download', r.statusCode == 200 && (r.data?.length ?? 0) > 10000, '(${r.data?.length} bayt)');
  await api.logout();
  final failed = results.entries.where((e) => !e.value).map((e) => e.key).toList();
  stdout.writeln(failed.isEmpty ? 'TÜMÜ GEÇTİ (${results.length})' : 'BAŞARISIZ: $failed');
  exit(failed.isEmpty ? 0 : 1);
}
