import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

import '../core/format.dart';
import '../core/state.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';

const _credNames = {'openai': 'OpenAI', 'anthropic': 'Anthropic', 'fal': 'fal.ai', 'runway': 'Runway', 'replicate': 'Replicate', 'elevenlabs': 'ElevenLabs', 'pexels': 'Pexels', 'pixabay': 'Pixabay', 'youtube_data': 'YouTube Data API (trend)'};

class ModelsScreen extends ConsumerWidget {
  const ModelsScreen({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final data = ref.watch(providersListProvider);
    final api = ref.read(apiProvider);
    return RefreshIndicator(
      onRefresh: () async => ref.invalidate(providersListProvider),
      child: AsyncView<Map>(
        value: data,
        onRetry: () => ref.invalidate(providersListProvider),
        builder: (d) {
          final provs = (d['providers'] as List).cast<Map>();
          final prefs = (d['preferences'] as Map).cast<String, dynamic>();
          return ListView(padding: const EdgeInsets.fromLTRB(14, 0, 14, 30), children: [
            Card(color: const Color(0xFF14233A), child: Padding(padding: const EdgeInsets.all(12), child: Text('${d['pricing_note']}  (fiyat tablosu tarihi: ${d['pricing_as_of']})\nÇevrimdışı yerel sağlayıcılar ${d['offline_allowed'] == true ? 'AÇIK' : 'KAPALI'}: bunlar AI değildir ve çıktıları otomatik yayına alınmaz.', style: const TextStyle(fontSize: 11.5, color: AppColors.muted)))),
            for (final kind in kindLabels.keys) ...[
              SectionTitle(kindLabels[kind]!, trailing: TextButton(onPressed: () => _order(context, ref, kind, (prefs[kind] as List).cast<String>(), provs.where((p) => p['kind'] == kind).map((p) => p['name'] as String).toList()), child: const Text('Öncelik sırası'))),
              Text('Sıra: ${((prefs[kind] ?? []) as List).join(' → ')}', style: const TextStyle(fontSize: 11, color: AppColors.muted)),
              for (final p in provs.where((p) => p['kind'] == kind)) _ProviderCard(p: p, api: api, onChanged: () => ref.invalidate(providersListProvider)),
            ],
            const SectionTitle('Diğer anahtarlar'),
            Card(child: ListTile(title: const Text('YouTube Data API anahtarı'), subtitle: const Text('Trend araştırması (videos.list mostPopular) için', style: TextStyle(fontSize: 11.5)), trailing: const Icon(Icons.key), onTap: () => _setKey(context, ref, 'youtube_data'))),
          ]);
        },
      ),
    );
  }

  Future<void> _order(BuildContext context, WidgetRef ref, String kind, List<String> current, List<String> all) async {
    final list = [...current, ...all.where((a) => !current.contains(a))];
    final res = await showDialog<List<String>>(
      context: context,
      builder: (_) => StatefulBuilder(builder: (c, set) => AlertDialog(
        title: Text('${kindLabels[kind]} sağlayıcı sırası'),
        content: SizedBox(
          width: 320,
          height: 60.0 * list.length + 10,
          child: ReorderableListView(
            onReorderItem: (a, b) => set(() => list.insert(b, list.removeAt(a))),
            children: [for (final n in list) ListTile(key: ValueKey(n), title: Text(n), leading: const Icon(Icons.drag_handle))],
          ),
        ),
        actions: [TextButton(onPressed: () => Navigator.pop(c), child: const Text('Vazgeç')), FilledButton(onPressed: () => Navigator.pop(c, list), child: const Text('Kaydet'))],
      )),
    );
    if (res != null && context.mounted) {
      await run(context, () => ref.read(apiProvider).put('/api/v1/providers/preferences', body: {kind: res}), ok: 'Sıra kaydedildi');
      ref.invalidate(providersListProvider);
    }
  }
}

Future<void> _setKey(BuildContext context, WidgetRef ref, String name) async {
  final c = TextEditingController();
  final ok = await showDialog<bool>(
    context: context,
    builder: (_) => AlertDialog(
      title: Text('${_credNames[name] ?? name} anahtarı'),
      content: Column(mainAxisSize: MainAxisSize.min, children: [
        TextField(controller: c, obscureText: true, autocorrect: false, enableSuggestions: false, decoration: const InputDecoration(labelText: 'API anahtarı')),
        const SizedBox(height: 8),
        const Text('Anahtar sunucuda şifrelenerek saklanır; uygulamada veya günlüklerde görünmez.', style: TextStyle(fontSize: 11, color: AppColors.muted)),
      ]),
      actions: [TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Vazgeç')), FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Kaydet'))],
    ),
  );
  if (ok == true && c.text.trim().length >= 8 && context.mounted) {
    await run(context, () => ref.read(apiProvider).put('/api/v1/providers/$name/credential', body: {'secret': c.text.trim()}), ok: 'Anahtar kaydedildi');
    ref.invalidate(providersListProvider);
  }
}

class _ProviderCard extends ConsumerWidget {
  const _ProviderCard({required this.p, required this.api, required this.onChanged});
  final Map p;
  final dynamic api;
  final VoidCallback onChanged;
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final conf = p['configured'] == true;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Icon(conf ? Icons.check_circle : Icons.radio_button_unchecked, color: conf ? AppColors.green : AppColors.muted, size: 18),
            const SizedBox(width: 8),
            Expanded(child: Text(p['label'], style: const TextStyle(fontWeight: FontWeight.w700))),
            if (p['is_ai'] == false) const Badge2('AI değil', color: AppColors.amber),
            if (p['offline'] == true) const Padding(padding: EdgeInsets.only(left: 4), child: Badge2('yerel', color: AppColors.blue)),
          ]),
          const SizedBox(height: 4),
          Text(conf ? (p['key_source'] != null ? 'Anahtar: ${p['key_source']} ${p['credential_hint'] ?? ''}' : 'Kullanıma hazır') : 'Yapılandırılmamış — ${p['needs_key'] != null ? '${_credNames[p['needs_key']] ?? p['needs_key']} anahtarı gerekli' : 'kullanılamıyor'}', style: const TextStyle(fontSize: 11.5, color: AppColors.muted)),
          if ((p['calls'] as int) > 0) ...[
            const SizedBox(height: 4),
            Text('${p['calls']} çağrı · başarı ${pct(p['success_rate'] as num?, d: 0)} · ort. ${p['avg_latency_s']} sn · ort. maliyet ${usd(p['avg_cost_usd'] as num?, d: 4)} · toplam ${usd(p['total_cost_usd'] as num, d: 3)}${(p['rate_limited'] as int) > 0 ? ' · ${p['rate_limited']}× rate-limit' : ''}', style: const TextStyle(fontSize: 11.5)),
            if ((p['last_meta'] as Map).isNotEmpty) Text('Son çıktı: ${(p['last_meta'] as Map).entries.where((e) => const {'resolution', 'duration', 'model'}.contains(e.key)).map((e) => '${e.key}=${e.value}').join(', ')}', style: const TextStyle(fontSize: 11, color: AppColors.muted)),
            if ((p['last_error'] as String).isNotEmpty) Text('Son hata: ${p['last_error']}', maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 11, color: AppColors.amber)),
          ],
          if (p['needs_key'] != null)
            Row(mainAxisAlignment: MainAxisAlignment.end, children: [
              if (conf) TextButton(onPressed: () async {
                final r = await ref.read(apiProvider).post('/api/v1/providers/${p['needs_key']}/test') as Map;
                if (context.mounted) toast(context, '${r['ok'] == true ? '✅' : r['ok'] == false ? '❌' : 'ℹ'} ${r['detail']}', error: r['ok'] == false);
              }, child: const Text('Anahtarı sına')),
              if (p['key_source'] == 'kullanıcı') TextButton(onPressed: () async { await run(context, () => ref.read(apiProvider).delete('/api/v1/providers/${p['needs_key']}/credential'), ok: 'Silindi'); onChanged(); }, child: const Text('Sil', style: TextStyle(color: AppColors.red))),
              FilledButton.tonal(onPressed: () => _setKey(context, ref, p['needs_key']), child: Text(conf ? 'Değiştir' : 'Anahtar ekle')),
            ]),
        ]),
      ),
    );
  }
}
