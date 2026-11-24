import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api_core.dart';

class SecureTokenStore implements TokenStore {
  static const _s = FlutterSecureStorage();
  @override
  Future<String?> readAccess() => _s.read(key: 'access');
  @override
  Future<String?> readRefresh() => _s.read(key: 'refresh');
  @override
  Future<void> save(String a, String r) async {
    await _s.write(key: 'access', value: a);
    await _s.write(key: 'refresh', value: r);
  }

  @override
  Future<void> clear() async {
    await _s.delete(key: 'access');
    await _s.delete(key: 'refresh');
  }
}

final prefsProvider = Provider<SharedPreferences>((_) => throw UnimplementedError('prefs override edilmeli'));
final tokenStoreProvider = Provider<TokenStore>((_) => SecureTokenStore());

enum AuthStatus { loading, loggedOut, loggedIn }

class SessionState {
  const SessionState({this.status = AuthStatus.loading, this.user, this.error});
  final AuthStatus status;
  final Json? user;
  final String? error;
}

class SessionNotifier extends Notifier<SessionState> {
  @override
  SessionState build() => const SessionState();

  ApiClient get _api => ref.read(apiProvider);

  Future<void> init() async {
    final base = ref.read(prefsProvider).getString('base_url');
    if (base == null || base.isEmpty) {
      state = const SessionState(status: AuthStatus.loggedOut);
      return;
    }
    try {
      final u = await _api.me();
      state = u == null ? const SessionState(status: AuthStatus.loggedOut) : SessionState(status: AuthStatus.loggedIn, user: u);
    } on ApiException catch (e) {
      // sunucuya ulaşılamıyorsa oturum açık kalır; ekranlar kendi hata durumunu gösterir
      final has = await ref.read(tokenStoreProvider).readRefresh() != null;
      state = SessionState(status: has && e.code == 'network' ? AuthStatus.loggedIn : AuthStatus.loggedOut, error: e.message);
    }
  }

  Future<void> authenticate(String url, String email, String password, {required bool register, String name = ''}) async {
    await ref.read(prefsProvider).setString('base_url', url.trim());
    _api.baseUrl = url;
    final u = register ? await _api.register(email, password, name) : await _api.login(email, password);
    state = SessionState(status: AuthStatus.loggedIn, user: u);
  }

  Future<void> logout() async {
    await _api.logout();
    state = const SessionState(status: AuthStatus.loggedOut);
  }

  void expired() => state = const SessionState(status: AuthStatus.loggedOut, error: 'Oturum süresi doldu, yeniden giriş yapın.');
}

final sessionProvider = NotifierProvider<SessionNotifier, SessionState>(SessionNotifier.new);

final apiProvider = Provider<ApiClient>((ref) {
  final base = ref.read(prefsProvider).getString('base_url') ?? 'http://10.0.2.2:8000';
  return ApiClient(baseUrl: base, tokens: ref.read(tokenStoreProvider), onSessionExpired: () => Future.microtask(() => ref.read(sessionProvider.notifier).expired()));
});

/// Canlı güncelleme sayacı: SSE olayları ve zamanlayıcı bunu artırır; dinleyen sağlayıcılar yenilenir.
class TickNotifier extends Notifier<int> {
  @override
  int build() => 0;
  void bump() => state++;
}

final tickProvider = NotifierProvider<TickNotifier, int>(TickNotifier.new);

typedef Q = Map<String, dynamic>;

FutureProvider<T> _getAuto<T>(String path, {bool live = false}) => FutureProvider.autoDispose<T>((ref) async {
      if (live) ref.watch(tickProvider);
      return await ref.read(apiProvider).get(path) as T;
    });

final dashboardProvider = FutureProvider.autoDispose<Map>((ref) async {
  ref.watch(tickProvider);
  return await ref.read(apiProvider).get('/api/v1/dashboard') as Map;
});
final systemProvider = _getAuto<Map>('/api/v1/system/status', live: true);
final channelsProvider = _getAuto<List>('/api/v1/channels');
final ideasProvider = _getAuto<List>('/api/v1/ideas?status=new', live: true);
final trendsProvider = _getAuto<List>('/api/v1/trends');
final tasksProvider = _getAuto<List>('/api/v1/tasks', live: true);
final automationProvider = _getAuto<Map>('/api/v1/automation/status', live: true);
final calendarProvider = _getAuto<Map>('/api/v1/calendar', live: true);
final insightsProvider = _getAuto<Map>('/api/v1/analytics/insights');
final overviewProvider = _getAuto<Map>('/api/v1/analytics/overview', live: true);
final experimentsProvider = _getAuto<List>('/api/v1/analytics/experiments');
final providersListProvider = _getAuto<Map>('/api/v1/providers', live: true);
final integrationsProvider = _getAuto<Map>('/api/v1/integrations');
final budgetProvider = _getAuto<Map>('/api/v1/costs/budget', live: true);
final costSummaryProvider = _getAuto<Map>('/api/v1/costs/summary', live: true);
final ledgerProvider = _getAuto<List>('/api/v1/costs/ledger?limit=40', live: true);
final notificationsProvider = _getAuto<Map>('/api/v1/notifications', live: true);
final settingsProvider = _getAuto<Map>('/api/v1/settings');
final musicProvider = _getAuto<List>('/api/v1/music');

class ProjectFilter {
  const ProjectFilter({this.status, this.q = ''});
  final String? status;
  final String q;
  @override
  bool operator ==(Object other) => other is ProjectFilter && other.status == status && other.q == q;
  @override
  int get hashCode => Object.hash(status, q);
}

final projectsProvider = FutureProvider.autoDispose.family<Map, ProjectFilter>((ref, f) async {
  ref.watch(tickProvider);
  final qs = <String, dynamic>{'limit': 60};
  if (f.status != null) qs['status'] = f.status;
  if (f.q.isNotEmpty) qs['q'] = f.q;
  return await ref.read(apiProvider).get('/api/v1/projects', query: qs) as Map;
});

final projectProvider = FutureProvider.autoDispose.family<Map, String>((ref, id) async {
  ref.watch(tickProvider);
  return await ref.read(apiProvider).get('/api/v1/projects/$id') as Map;
});
