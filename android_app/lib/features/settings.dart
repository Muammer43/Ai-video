import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

import '../core/notify.dart';
import '../core/state.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';
import 'costs.dart';

class SettingsScreen extends ConsumerStatefulWidget {
  const SettingsScreen({super.key});
  @override
  ConsumerState<SettingsScreen> createState() => _SettingsState();
}

class _SettingsState extends ConsumerState<SettingsScreen> {
  double _auto = 90, _low = 80, _review = 60;
  bool _inited = false;

  @override
  Widget build(BuildContext context) {
    final st = ref.watch(settingsProvider);
    final sys = ref.watch(systemProvider);
    final music = ref.watch(musicProvider);
    final session = ref.watch(sessionProvider);
    final api = ref.read(apiProvider);
    final prefs = ref.read(prefsProvider);
    return AsyncView<Map>(
      value: st,
      onRetry: () => ref.invalidate(settingsProvider),
      builder: (s) {
        if (!_inited) {
          _inited = true;
          final q = s['quality'] as Map;
          _auto = (q['auto_publish_min'] as num).toDouble();
          _low = (q['low_risk_min'] as num).toDouble();
          _review = (q['review_min'] as num).toDouble();
        }
        final server = s['server'] as Map;
        return ListView(padding: const EdgeInsets.fromLTRB(14, 0, 14, 30), children: [
          const SectionTitle('Hesap'),
          Card(child: Column(children: [
            ListTile(leading: const Icon(Icons.person_outline), title: Text('${session.user?['display_name'] ?? ''}'), subtitle: Text('${session.user?['email'] ?? ''} · ${session.user?['role'] ?? ''}')),
            ListTile(leading: const Icon(Icons.password), title: const Text('Parolayı değiştir'), onTap: () => _changePw(context, api)),
            ListTile(leading: const Icon(Icons.logout, color: AppColors.red), title: const Text('Çıkış yap'), onTap: () async { ref.read(liveProvider).stop(); await ref.read(sessionProvider.notifier).logout(); }),
          ])),
          const SectionTitle('Sunucu'),
          Card(child: Padding(padding: const EdgeInsets.all(14), child: Column(children: [
            Kv('Adres', api.baseUrl),
            Kv('Bağlantı', api.isInsecure ? '⚠ şifresiz (http)' : '🔒 HTTPS'),
            Kv('Kayıt', server['registration_open'] == true ? 'açık' : 'kapalı'),
            sys.maybeWhen(data: (x) => Column(children: [Kv('Sürüm', '${x['version']} (${x['env']})'), Kv('Kuyruk', '${x['queue_mode']}'), Kv('Disk', x['disk'] != null ? '${x['disk']['free_gb']} GB boş' : '—'), Kv('FFmpeg', '${x['ffmpeg']['version'] ?? x['ffmpeg']}')]), orElse: () => const SizedBox.shrink()),
          ]))),
          const SectionTitle('Bütçe ve maliyet'),
          Card(child: ListTile(leading: const Icon(Icons.payments_outlined), title: const Text('Bütçe, limitler ve harcama geçmişi'), trailing: const Icon(Icons.chevron_right), onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const CostsScreen())))),
          const SectionTitle('Kalite eşikleri (otomatik yayın)'),
          Card(child: Padding(padding: const EdgeInsets.all(14), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Otomatik yayın ≥ ${_auto.round()}', style: const TextStyle(fontSize: 12.5)),
            Slider(value: _auto, min: 70, max: 100, divisions: 30, onChanged: (v) => setState(() { _auto = v; if (_low > v) _low = v; })),
            Text('Düşük riskli otomatik yayın ≥ ${_low.round()}  (güvenlik/telif kontrolleri tam temizse)', style: const TextStyle(fontSize: 12.5)),
            Slider(value: _low, min: 50, max: 100, divisions: 50, onChanged: (v) => setState(() { _low = v > _auto ? _auto : v; if (_review >= _low) _review = _low - 1; })),
            Text('Kullanıcı incelemesi ≥ ${_review.round()}  (altı reddedilir)', style: const TextStyle(fontSize: 12.5)),
            Slider(value: _review, min: 20, max: 99, divisions: 79, onChanged: (v) => setState(() => _review = v >= _low ? _low - 1 : v)),
            const Text('Kritik güvenlik/telif/teknik bulgular puandan bağımsız olarak otomatik yayını engeller.', style: TextStyle(fontSize: 11, color: AppColors.muted)),
            Align(alignment: Alignment.centerRight, child: FilledButton(onPressed: () => run(context, () => api.put('/api/v1/settings/quality', body: {'auto_publish_min': _auto.round(), 'low_risk_min': _low.round(), 'review_min': _review.round()}), ok: 'Eşikler kaydedildi'), child: const Text('Kaydet'))),
          ]))),
          const SectionTitle('Bildirimler'),
          Card(child: StatefulBuilder(builder: (c, set) => SwitchListTile(
            title: const Text('Yerel bildirimler'),
            subtitle: const Text('Uygulama açıkken/arka plandayken üretim, inceleme, yayın ve bütçe olayları. Uygulama tamamen kapalıyken bildirim için sunucuda FCM + istemci Firebase kurulumu gerekir (docs/ANDROID_KULLANIM.md).', style: TextStyle(fontSize: 11)),
            value: prefs.getBool('notif_enabled') ?? true,
            onChanged: (v) async { await prefs.setBool('notif_enabled', v); ref.read(liveProvider).enabled = v; set(() {}); },
          ))),
          const SectionTitle('Müzik kütüphanesi (lisanslı)'),
          AsyncView<List>(value: music, isEmpty: (l) => l.isEmpty, emptyText: 'Kütüphane boş: sistem telifsiz sentezlenmiş müzik kullanır.\nLisanslı müzik yüklemek için POST /api/v1/music (lisans alanları zorunlu).', emptyIcon: Icons.library_music_outlined, builder: (l) => Card(child: Column(children: [
            for (final m in l.cast<Map>()) ListTile(dense: true, title: Text(m['title']), subtitle: Text('${m['mood']} · ${m['license_type']} · ${m['license_source']}', style: const TextStyle(fontSize: 11)), trailing: IconButton(icon: const Icon(Icons.delete_outline), onPressed: () async { await run(context, () => api.delete('/api/v1/music/${m['id']}')); ref.invalidate(musicProvider); })),
          ]))),
          const SectionTitle('Hakkında'),
          const Card(child: Padding(padding: EdgeInsets.all(14), child: Text('AI Video Factory Pro V2\nTelefon yalnızca kontrol panelidir; üretim, render ve yayın bulutta çalışır.\nTüm veriler gerçek backend\'den gelir.', style: TextStyle(fontSize: 12, color: AppColors.muted)))),
        ]);
      },
    );
  }

  Future<void> _changePw(BuildContext context, dynamic api) async {
    final o = TextEditingController(), n = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Parolayı değiştir'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          TextField(controller: o, obscureText: true, decoration: const InputDecoration(labelText: 'Eski parola')),
          const SizedBox(height: 10),
          TextField(controller: n, obscureText: true, decoration: const InputDecoration(labelText: 'Yeni parola (en az 10, harf+rakam)')),
        ]),
        actions: [TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Vazgeç')), FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Değiştir'))],
      ),
    );
    if (ok == true && context.mounted) {
      final done = await run(context, () => api.post('/api/v1/auth/change-password', body: {'old_password': o.text, 'new_password': n.text}), ok: 'Parola değişti; yeniden giriş yapın');
      if (done) await ref.read(sessionProvider.notifier).logout();
    }
  }
}
