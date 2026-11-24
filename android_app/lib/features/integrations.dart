import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';
import 'package:url_launcher/url_launcher.dart';

import '../core/state.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';

class IntegrationsScreen extends ConsumerWidget {
  const IntegrationsScreen({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final data = ref.watch(integrationsProvider);
    final api = ref.read(apiProvider);
    return RefreshIndicator(
      onRefresh: () async => ref.invalidate(integrationsProvider),
      child: AsyncView<Map>(
        value: data,
        onRetry: () => ref.invalidate(integrationsProvider),
        builder: (d) => ListView(padding: const EdgeInsets.fromLTRB(14, 0, 14, 30), children: [
          if (d['https'] != true)
            const Card(color: Color(0xFF2B2413), child: Padding(padding: EdgeInsets.all(12), child: Text('⚠ Sunucu PUBLIC_BASE_URL https:// değil. OAuth yönlendirmeleri için HTTPS gerekir; Instagram ayrıca videonun herkese açık HTTPS adresinden erişilebilir olmasını ister.', style: TextStyle(fontSize: 12, color: AppColors.amber)))),
          for (final p in (d['platforms'] as List).cast<Map>())
            Card(
              child: Padding(
                padding: const EdgeInsets.all(14),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [
                    Icon(p['platform'] == 'youtube' ? Icons.smart_display : p['platform'] == 'tiktok' ? Icons.music_note : Icons.camera_alt_outlined, color: AppColors.accent),
                    const SizedBox(width: 10),
                    Expanded(child: Text(p['label'], style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16))),
                    Badge2(p['oauth_configured'] == true ? 'OAuth hazır' : 'sunucuda yapılandırılmamış', color: p['oauth_configured'] == true ? AppColors.green : AppColors.amber),
                  ]),
                  const SizedBox(height: 6),
                  Text(p['requirements'], style: const TextStyle(fontSize: 11.5, color: AppColors.muted)),
                  if (p['oauth_configured'] != true) Padding(padding: const EdgeInsets.only(top: 6), child: Text('Gerekli: ${p['config_hint']}', style: const TextStyle(fontSize: 11.5, color: AppColors.amber))),
                  const Divider(height: 20),
                  if ((p['accounts'] as List).isEmpty) const Text('Bağlı hesap yok — bağlanana kadar bu platforma yayın yapılmaz.', style: TextStyle(fontSize: 12)),
                  for (final a in (p['accounts'] as List).cast<Map>())
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      dense: true,
                      title: Text('${a['display_name']}'),
                      subtitle: Text('${a['account_type']} · ${a['status'] == 'active' ? 'aktif' : 'YENİDEN BAĞLANMALI'}${(a['capabilities'] as Map)['private_only'] == true ? ' · yalnızca özel paylaşım (denetimsiz)' : ''}${(a['last_error'] as String).isNotEmpty ? '\n${a['last_error']}' : ''}', style: const TextStyle(fontSize: 11.5)),
                      trailing: IconButton(icon: const Icon(Icons.link_off, size: 20), onPressed: () async {
                        if (await confirm(context, 'Bağlantıyı kes', '${a['display_name']} hesabıyla yayın durur.', ok: 'Kes')) {
                          if (!context.mounted) return;
                          await run(context, () => api.delete('/api/v1/integrations/accounts/${a['id']}'), ok: 'Bağlantı kesildi');
                          ref.invalidate(integrationsProvider);
                        }
                      }),
                    ),
                  Align(
                    alignment: Alignment.centerRight,
                    child: FilledButton.icon(
                      onPressed: p['oauth_configured'] != true ? null : () async {
                        try {
                          final r = await api.post('/api/v1/integrations/${p['platform']}/authorize') as Map;
                          await launchUrl(Uri.parse(r['url']), mode: LaunchMode.externalApplication);
                          if (context.mounted) toast(context, 'Tarayıcıda yetkilendirmeyi tamamlayın, sonra buraya dönüp yenileyin');
                        } catch (e) {
                          if (context.mounted) toast(context, '$e', error: true);
                        }
                      },
                      icon: const Icon(Icons.add_link),
                      label: const Text('Hesap bağla'),
                    ),
                  ),
                ]),
              ),
            ),
        ]),
      ),
    );
  }
}
