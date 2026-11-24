import 'dart:convert';

import 'package:ai_video_factory/core/api_core.dart';
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

/// Sahte HTTP bağdaştırıcı (MOCK): ApiClient'ın istek/yanıt mantığını sınar; gerçek sunucu testi için tool/connect_check.dart.
class FakeAdapter implements HttpClientAdapter {
  FakeAdapter(this.handler);
  final (int, Object) Function(RequestOptions) handler;
  final calls = <String>[];
  @override
  Future<ResponseBody> fetch(RequestOptions o, Stream<List<int>>? body, Future<void>? cancel) async {
    calls.add('${o.method} ${o.path} ${o.headers['Authorization'] ?? ''}');
    final (code, data) = handler(o);
    return ResponseBody.fromString(jsonEncode(data), code, headers: {Headers.contentTypeHeader: ['application/json']});
  }

  @override
  void close({bool force = false}) {}
}

ApiClient make(FakeAdapter a, MemoryTokenStore s, {void Function()? expired}) {
  final dio = Dio()..httpClientAdapter = a;
  return ApiClient(baseUrl: 'http://x.test/', tokens: s, dio: dio, onSessionExpired: expired);
}

void main() {
  test('baseUrl sondaki eğik çizgiyi temizler ve http uyarısı verir', () {
    final c = make(FakeAdapter((_) => (200, {})), MemoryTokenStore());
    expect(c.baseUrl, 'http://x.test');
    expect(c.isInsecure, true);
    c.baseUrl = 'https://secure.test///';
    expect(c.baseUrl, 'https://secure.test');
    expect(c.isInsecure, false);
  });

  test('sunucu hata gövdesini ApiException olarak ayrıştırır', () async {
    final c = make(FakeAdapter((_) => (402, {'error': {'code': 'budget_exceeded', 'message': 'Bütçe aşıldı', 'data': {'x': 1}}})), MemoryTokenStore());
    expect(() => c.get('/api/v1/projects'), throwsA(isA<ApiException>().having((e) => e.code, 'code', 'budget_exceeded').having((e) => e.message, 'message', 'Bütçe aşıldı').having((e) => e.status, 'status', 402)));
  });

  test('401 alınca refresh token ile yeniler ve isteği tekrarlar', () async {
    final store = MemoryTokenStore()..access = 'old'..refresh = 'r1';
    final a = FakeAdapter((o) {
      if (o.path == '/api/v1/auth/refresh') return (200, {'access_token': 'new', 'refresh_token': 'r2'});
      return o.headers['Authorization'] == 'Bearer new' ? (200, {'ok': true}) : (401, {'error': {'code': 'token_expired', 'message': 'süre doldu'}});
    });
    final c = make(a, store);
    final r = await c.get('/api/v1/dashboard');
    expect(r['ok'], true);
    expect(store.access, 'new');
    expect(store.refresh, 'r2');
    expect(a.calls.where((x) => x.contains('/auth/refresh')).length, 1);
  });

  test('eşzamanlı 401\'lerde tek yenileme yapılır', () async {
    final store = MemoryTokenStore()..access = 'old'..refresh = 'r1';
    final a = FakeAdapter((o) => o.path == '/api/v1/auth/refresh' ? (200, {'access_token': 'new', 'refresh_token': 'r2'}) : (o.headers['Authorization'] == 'Bearer new' ? (200, {}) : (401, {})));
    final c = make(a, store);
    await Future.wait([c.get('/a'), c.get('/b'), c.get('/c')]);
    expect(a.calls.where((x) => x.contains('/auth/refresh')).length, 1);
  });

  test('yenileme başarısızsa oturum sonlanır ve callback çağrılır', () async {
    final store = MemoryTokenStore()..access = 'old'..refresh = 'bad';
    var expired = false;
    final c = make(FakeAdapter((o) => o.path.endsWith('/refresh') ? (401, {'error': {'message': 'x'}}) : (401, {'error': {'code': 'token_expired', 'message': 'süre'}})), store, expired: () => expired = true);
    await expectLater(c.get('/api/v1/x'), throwsA(isA<ApiException>()));
    expect(expired, true);
    expect(store.access, isNull);
  });

  test('login jetonları saklar, logout temizler', () async {
    final store = MemoryTokenStore();
    final c = make(FakeAdapter((o) => o.path.endsWith('/login') ? (200, {'access_token': 'A', 'refresh_token': 'R', 'user': {'email': 'a@b.c'}}) : (200, {'ok': true})), store);
    final u = await c.login('a@b.c', 'pw');
    expect(u['email'], 'a@b.c');
    expect(store.access, 'A');
    await c.logout();
    expect(store.access, isNull);
  });

  test('ağ hatası anlaşılır Türkçe mesaja çevrilir', () async {
    final dio = Dio()..httpClientAdapter = _Boom();
    final c = ApiClient(baseUrl: 'http://x.test', tokens: MemoryTokenStore(), dio: dio);
    expect(() => c.health(), throwsA(isA<ApiException>().having((e) => e.code, 'code', 'network').having((e) => e.message, 'msg', contains('bağlanılamadı'))));
  });
}

class _Boom implements HttpClientAdapter {
  @override
  Future<ResponseBody> fetch(RequestOptions o, Stream<List<int>>? b, Future<void>? c) async => throw DioException(requestOptions: o, type: DioExceptionType.connectionError);
  @override
  void close({bool force = false}) {}
}
