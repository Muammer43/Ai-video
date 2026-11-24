import 'dart:async';

import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api_core.dart';
import 'state.dart';

/// Uygulama açıkken: (1) global SSE akışı ile canlı yenileme, (2) bildirim yoklama + yerel bildirim.
/// Uygulama KAPALIYKEN bildirim için FCM gerekir: sunucu tarafı hazırdır (POST /devices + FCM v1), istemci tarafı
/// Firebase yapılandırması (google-services.json) gerektirir ve bu sürümde derlemeye dahil edilmemiştir — docs/ANDROID_KULLANIM.md
class LiveService {
  LiveService(this.ref);
  final Ref ref;
  final _plugin = FlutterLocalNotificationsPlugin();
  StreamSubscription? _sse;
  Timer? _poll, _tick;
  bool _ready = false;
  bool enabled = true;

  Future<void> start() async {
    await _init();
    enabled = ref.read(prefsProvider).getBool('notif_enabled') ?? true;
    _tick = Timer.periodic(const Duration(seconds: 20), (_) => ref.read(tickProvider.notifier).bump());
    _poll = Timer.periodic(const Duration(seconds: 45), (_) => _checkNotifications());
    _listenSse();
    await _checkNotifications();
  }

  Future<void> _init() async {
    if (_ready) return;
    try {
      await _plugin.initialize(settings: const InitializationSettings(android: AndroidInitializationSettings('@mipmap/ic_launcher')));
      await _plugin.resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>()?.requestNotificationsPermission();
      _ready = true;
    } catch (_) {
      _ready = false;
    }
  }

  void _listenSse() {
    _sse?.cancel();
    final api = ref.read(apiProvider);
    _sse = api.sse('/api/v1/events/stream').listen((_) => ref.read(tickProvider.notifier).bump(), onError: (_) {}, onDone: () {
      Future.delayed(const Duration(seconds: 10), () {
        if (_tick != null) _listenSse();
      });
    });
  }

  Future<void> _checkNotifications() async {
    try {
      final d = await ref.read(apiProvider).get('/api/v1/notifications', query: {'unread': true, 'limit': 20}) as Map;
      final prefs = ref.read(prefsProvider);
      final seen = (prefs.getStringList('seen_notifs') ?? []).toSet();
      for (final n in (d['items'] as List).reversed) {
        final id = n['id'] as String;
        if (seen.contains(id)) continue;
        seen.add(id);
        if (enabled && _ready) {
          await _plugin.show(
            id: id.hashCode & 0x7fffffff,
            title: n['title'],
            body: n['body'],
            notificationDetails: NotificationDetails(
              android: AndroidNotificationDetails('aivf_main', 'Üretim bildirimleri',
                  channelDescription: 'Üretim, inceleme, yayın ve bütçe bildirimleri',
                  importance: n['level'] == 'error' ? Importance.high : Importance.defaultImportance, priority: Priority.defaultPriority),
            ),
          );
        }
      }
      await prefs.setStringList('seen_notifs', seen.toList().take(200).toList());
      ref.invalidate(notificationsProvider);
    } on ApiException catch (_) {} catch (_) {}
  }

  void stop() {
    _sse?.cancel();
    _poll?.cancel();
    _tick?.cancel();
    _sse = null;
    _poll = null;
    _tick = null;
  }
}

final liveProvider = Provider<LiveService>((ref) {
  final s = LiveService(ref);
  ref.onDispose(s.stop);
  return s;
});

Future<void> registerDeviceToken(ApiClient api, String token) async {
  await api.post('/api/v1/devices', body: {'token': token, 'platform': 'android'});
}

Future<void> clearSeen(SharedPreferences p) => p.remove('seen_notifs');
