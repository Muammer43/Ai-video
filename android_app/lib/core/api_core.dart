// Saf Dart ağ katmanı (Flutter bağımlılığı yok) — hem uygulamada hem `tool/connect_check.dart` içinde kullanılır.
import 'dart:async';
import 'dart:convert';

import 'package:dio/dio.dart';

abstract class TokenStore {
  Future<String?> readAccess();
  Future<String?> readRefresh();
  Future<void> save(String access, String refresh);
  Future<void> clear();
}

class MemoryTokenStore implements TokenStore {
  String? access, refresh;
  @override
  Future<String?> readAccess() async => access;
  @override
  Future<String?> readRefresh() async => refresh;
  @override
  Future<void> save(String a, String r) async {
    access = a;
    refresh = r;
  }

  @override
  Future<void> clear() async {
    access = null;
    refresh = null;
  }
}

class ApiException implements Exception {
  final int? status;
  final String code;
  final String message;
  final Map<String, dynamic>? data;
  ApiException(this.message, {this.status, this.code = 'error', this.data});
  bool get isAuth => status == 401;
  @override
  String toString() => message;
}

typedef Json = Map<String, dynamic>;

class ApiClient {
  ApiClient({required String baseUrl, required this.tokens, Dio? dio, this.onSessionExpired})
      : _base = _clean(baseUrl),
        dio = dio ?? Dio() {
    this.dio.options
      ..baseUrl = _base
      ..connectTimeout = const Duration(seconds: 15)
      ..receiveTimeout = const Duration(seconds: 60)
      ..validateStatus = (s) => s != null && s < 500;
  }

  final Dio dio;
  final TokenStore tokens;
  final void Function()? onSessionExpired;
  String _base;
  Completer<bool>? _refreshing;

  static String _clean(String u) => u.trim().replaceAll(RegExp(r'/+$'), '');
  String get baseUrl => _base;
  bool get isInsecure => _base.startsWith('http://');
  set baseUrl(String v) {
    _base = _clean(v);
    dio.options.baseUrl = _base;
  }

  ApiException _err(Response r) {
    final d = r.data;
    if (d is Map && d['error'] is Map) {
      final e = d['error'] as Map;
      return ApiException((e['message'] ?? 'Hata').toString(),
          status: r.statusCode, code: (e['code'] ?? 'error').toString(), data: (e['data'] as Map?)?.cast<String, dynamic>());
    }
    return ApiException('Sunucu hatası (${r.statusCode})', status: r.statusCode);
  }

  Future<bool> _refresh() async {
    if (_refreshing != null) return _refreshing!.future;
    final c = _refreshing = Completer<bool>();
    try {
      final rt = await tokens.readRefresh();
      if (rt == null) {
        c.complete(false);
      } else {
        final r = await dio.post('/api/v1/auth/refresh', data: {'refresh_token': rt});
        if (r.statusCode == 200 && r.data is Map) {
          await tokens.save(r.data['access_token'], r.data['refresh_token']);
          c.complete(true);
        } else {
          await tokens.clear();
          c.complete(false);
        }
      }
    } catch (_) {
      c.complete(false);
    }
    final ok = await c.future;
    _refreshing = null;
    if (!ok) onSessionExpired?.call();
    return ok;
  }

  Future<dynamic> _send(String method, String path,
      {Object? body, Map<String, dynamic>? query, Map<String, String>? headers, bool auth = true, bool retry = true}) async {
    final h = <String, String>{...?headers};
    if (auth) {
      final t = await tokens.readAccess();
      if (t != null) h['Authorization'] = 'Bearer $t';
    }
    Response r;
    try {
      r = await dio.request(path, data: body, queryParameters: query, options: Options(method: method, headers: h));
    } on DioException catch (e) {
      final why = switch (e.type) {
        DioExceptionType.connectionTimeout || DioExceptionType.receiveTimeout || DioExceptionType.sendTimeout => 'Sunucuya ulaşılamadı (zaman aşımı)',
        DioExceptionType.connectionError => 'Sunucuya bağlanılamadı. Adresi ve ağ bağlantısını kontrol edin.',
        _ => 'Ağ hatası: ${e.message}',
      };
      throw ApiException(why, code: 'network');
    }
    if (r.statusCode == 401 && auth && retry && path != '/api/v1/auth/refresh') {
      if (await _refresh()) return _send(method, path, body: body, query: query, headers: headers, auth: auth, retry: false);
    }
    if ((r.statusCode ?? 500) >= 400) throw _err(r);
    return r.data;
  }

  Future<dynamic> get(String p, {Map<String, dynamic>? query}) => _send('GET', p, query: query);
  Future<dynamic> post(String p, {Object? body, Map<String, String>? headers}) => _send('POST', p, body: body ?? {}, headers: headers);
  Future<dynamic> put(String p, {Object? body}) => _send('PUT', p, body: body ?? {});
  Future<dynamic> delete(String p) => _send('DELETE', p);

  // ---- kimlik ----
  Future<Json> login(String email, String password) async {
    final d = await _send('POST', '/api/v1/auth/login', body: {'email': email, 'password': password}, auth: false);
    await tokens.save(d['access_token'], d['refresh_token']);
    return (d['user'] as Map).cast<String, dynamic>();
  }

  Future<Json> register(String email, String password, String name) async {
    final d = await _send('POST', '/api/v1/auth/register', body: {'email': email, 'password': password, 'display_name': name}, auth: false);
    await tokens.save(d['access_token'], d['refresh_token']);
    return (d['user'] as Map).cast<String, dynamic>();
  }

  Future<void> logout() async {
    try {
      final rt = await tokens.readRefresh();
      if (rt != null) await _send('POST', '/api/v1/auth/logout', body: {'refresh_token': rt}, retry: false);
    } catch (_) {}
    await tokens.clear();
  }

  Future<Json> health() async => ((await _send('GET', '/api/v1/health', auth: false)) as Map).cast<String, dynamic>();
  Future<Json?> me() async {
    try {
      return ((await get('/api/v1/auth/me')) as Map).cast<String, dynamic>();
    } on ApiException catch (e) {
      if (e.isAuth) return null;
      rethrow;
    }
  }

  // ---- SSE (Authorization başlığıyla; URL'de token yok) ----
  Stream<Json> sse(String path, {int after = 0}) async* {
    var last = after;
    var failures = 0;
    while (true) {
      try {
        final t = await tokens.readAccess();
        final r = await dio.get<ResponseBody>(path,
            queryParameters: {'after': last},
            options: Options(responseType: ResponseType.stream, headers: {'Authorization': 'Bearer $t', 'Accept': 'text/event-stream'},
                receiveTimeout: const Duration(minutes: 10)));
        if (r.statusCode == 401) {
          if (!await _refresh()) return;
          continue;
        }
        if (r.statusCode != 200) throw ApiException('SSE ${r.statusCode}');
        failures = 0;
        String? event;
        final buf = StringBuffer();
        await for (final line in utf8.decoder.bind(r.data!.stream.cast<List<int>>()).transform(const LineSplitter())) {
          if (line.startsWith('event:')) {
            event = line.substring(6).trim();
          } else if (line.startsWith('data:')) {
            buf.write(line.substring(5).trim());
          } else if (line.isEmpty && buf.isNotEmpty) {
            final m = (jsonDecode(buf.toString()) as Map).cast<String, dynamic>();
            buf.clear();
            if (event == 'end') {
              yield {...m, '_end': true};
              return;
            }
            if (m['id'] is int) last = m['id'] as int;
            yield m;
            event = null;
          }
        }
      } catch (e) {
        if (++failures > 6) rethrow;
        await Future<void>.delayed(Duration(seconds: 2 * failures));
      }
    }
  }
}
