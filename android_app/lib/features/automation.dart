import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

import '../core/format.dart';
import '../core/state.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';
import 'projects.dart';
import 'studio.dart';

class AutomationScreen extends ConsumerStatefulWidget {
  const AutomationScreen({super.key});
  @override
  ConsumerState<AutomationScreen> createState() => _AutomationState();
}

class _AutomationState extends ConsumerState<AutomationScreen> {
  String _cat = 'Teknoloji';
  int _count = 5;

  Future<void> _generate() async {
    final api = ref.read(apiProvider);
    await run(context, () async {
      final r = await api.post('/api/v1/ideas/generate', body: {'category': _cat, 'count': _count}) as Map;
      return r;
    }, ok: 'Fikir üretimi kuyruğa alındı — birkaç saniye içinde listede görünür');
    ref.invalidate(tasksProvider);
  }

  @override
  Widget build(BuildContext context) {
    final auto = ref.watch(automationProvider);
    final ideas = ref.watch(ideasProvider);
    final tasks = ref.watch(tasksProvider);
    final trends = ref.watch(trendsProvider);
    final api = ref.read(apiProvider);
    return RefreshIndicator(
      onRefresh: () async {
        ref.invalidate(automationProvider);
        ref.invalidate(ideasProvider);
        ref.invalidate(trendsProvider);
      },
      child: ListView(padding: const EdgeInsets.fromLTRB(14, 0, 14, 30), children: [
        AsyncView<Map>(value: auto, onRetry: () => ref.invalidate(automationProvider), builder: (a) {
          final paused = a['paused'] == true;
          return Card(
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Icon(paused ? Icons.pause_circle : Icons.play_circle, color: paused ? AppColors.amber : AppColors.green, size: 30),
                  const SizedBox(width: 10),
                  Expanded(child: Text(paused ? 'Otomasyon duraklatıldı' : (a['channels_automated'] as int) > 0 ? 'Otomasyon çalışıyor' : 'Hiçbir kanalda otomasyon açık değil', style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16))),
                ]),
                const SizedBox(height: 6),
                Text('${a['channels_automated']}/${a['channels_total']} kanalda otomatik üretim · ${a['active_projects']} aktif iş${a['budget_paused'] == true ? ' · BÜTÇE DURAKLATMASI' : ''}', style: const TextStyle(color: AppColors.muted, fontSize: 12)),
                const SizedBox(height: 10),
                Row(children: [
                  FilledButton.tonal(onPressed: () async { await run(context, () => api.post('/api/v1/automation/${paused ? 'resume' : 'pause'}'), ok: paused ? 'Devam ediyor' : 'Duraklatıldı'); ref.invalidate(automationProvider); }, child: Text(paused ? 'Devam ettir' : 'Duraklat')),
                ]),
                const Divider(height: 24),
                if ((a['channels'] as List).isEmpty) const Text('Önce "İçerik Kanalları" sayfasında bir kanal oluşturun.', style: TextStyle(color: AppColors.muted, fontSize: 12)),
                for (final c in (a['channels'] as List).cast<Map>())
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    title: Text(c['name']),
                    subtitle: Text('${c['enabled'] == true ? 'Açık' : 'Kapalı'} · günde ${c['videos_per_day']} video · son çalışma ${ago(c['last_run_at'])}', style: const TextStyle(fontSize: 11.5)),
                    trailing: TextButton(
                      onPressed: () async {
                        final res = await api.post('/api/v1/channels/${c['id']}/run-now').catchError((e) => {'started': false, 'message': '$e'}) as Map;
                        if (!context.mounted) return;
                        if (res['started'] == true) {
                          Navigator.push(context, MaterialPageRoute(builder: (_) => ProjectDetailScreen(id: res['project_id'])));
                        } else {
                          toast(context, res['message']?.toString() ?? 'Başlatılamadı', error: res['message'] == null);
                        }
                        ref.invalidate(ideasProvider);
                      },
                      child: const Text('Şimdi üret'),
                    ),
                  ),
              ]),
            ),
          );
        }),
        const SectionTitle('Fikir üretimi'),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(children: [
              Row(children: [
                Expanded(child: DropdownButtonFormField<String>(initialValue: _cat, decoration: const InputDecoration(labelText: 'Kategori', isDense: true), items: [for (final c in categories) DropdownMenuItem(value: c, child: Text(c))], onChanged: (v) => setState(() => _cat = v!))),
                const SizedBox(width: 10),
                SizedBox(width: 84, child: DropdownButtonFormField<int>(initialValue: _count, decoration: const InputDecoration(labelText: 'Adet', isDense: true), items: [for (final n in [3, 5, 8, 10]) DropdownMenuItem(value: n, child: Text('$n'))], onChanged: (v) => setState(() => _count = v!))),
              ]),
              const SizedBox(height: 10),
              Row(children: [
                Expanded(child: FilledButton.icon(onPressed: _generate, icon: const Icon(Icons.lightbulb_outline), label: const Text('Fikir üret'))),
                const SizedBox(width: 8),
                OutlinedButton.icon(onPressed: () async { await run(context, () => api.post('/api/v1/trends/refresh', body: [_cat]), ok: 'Trend araştırması başlatıldı'); ref.invalidate(tasksProvider); }, icon: const Icon(Icons.trending_up), label: const Text('Trendler')),
              ]),
              const SizedBox(height: 6),
              const Text('Fikirler yalnızca gerçek trend kaynaklarından (YouTube Trending, Hacker News, Wikipedia) ve LLM değerlendirmesinden üretilir; trend verisi yoksa uydurulmaz.', style: TextStyle(color: AppColors.muted, fontSize: 11)),
            ]),
          ),
        ),
        SectionTitle('Önerilen fikirler', trailing: IconButton(icon: const Icon(Icons.refresh), onPressed: () => ref.invalidate(ideasProvider))),
        AsyncView<List>(
          value: ideas,
          onRetry: () => ref.invalidate(ideasProvider),
          isEmpty: (l) => l.isEmpty,
          emptyText: 'Henüz fikir yok. Yukarıdan fikir üretin.',
          emptyIcon: Icons.lightbulb_outline,
          builder: (l) => Column(children: [
            for (final i in l.cast<Map>())
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Row(children: [
                      Expanded(child: Text(i['title'], style: const TextStyle(fontWeight: FontWeight.w700))),
                      Badge2('${(i['score'] as num).toStringAsFixed(0)} puan', color: AppColors.green),
                    ]),
                    const SizedBox(height: 4),
                    Text('${i['category']} · ${i['format']} · ${i['audience']}', style: const TextStyle(fontSize: 11.5, color: AppColors.muted)),
                    if ((i['angle'] as String).isNotEmpty) Text(i['angle'], style: const TextStyle(fontSize: 12)),
                    if (i['source']?['is_ai'] == false) const Padding(padding: EdgeInsets.only(top: 4), child: Badge2('şablon fikir — AI değerlendirmesi değil', color: AppColors.amber)),
                    if (((i['score_detail'] ?? {})['reason'] ?? '') != '') Text('Gerekçe: ${i['score_detail']['reason']}', style: const TextStyle(fontSize: 11, color: AppColors.muted)),
                    Row(mainAxisAlignment: MainAxisAlignment.end, children: [
                      TextButton(onPressed: () async { await run(context, () => api.delete('/api/v1/ideas/${i['id']}')); ref.invalidate(ideasProvider); }, child: const Text('Reddet')),
                      TextButton(onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => Scaffold(appBar: AppBar(title: const Text('Fikirden üret')), body: StudioScreen(initialTopic: i['title'], initialCategory: i['category'], ideaId: i['id'])))), child: const Text('Düzenleyip üret')),
                      FilledButton(onPressed: () async {
                        try {
                          final r = await api.post('/api/v1/ideas/${i['id']}/produce') as Map;
                          ref.invalidate(ideasProvider);
                          ref.read(tickProvider.notifier).bump();
                          if (context.mounted) Navigator.push(context, MaterialPageRoute(builder: (_) => ProjectDetailScreen(id: r['project_id'])));
                        } catch (e) {
                          if (context.mounted) toast(context, '$e', error: true);
                        }
                      }, child: const Text('Üret')),
                    ]),
                  ]),
                ),
              ),
          ]),
        ),
        const SectionTitle('Trend araştırması'),
        AsyncView<List>(value: trends, isEmpty: (l) => l.isEmpty, emptyText: 'Trend verisi yok (kaynaklar henüz çekilmedi veya erişilemedi).', emptyIcon: Icons.trending_up, builder: (l) => Card(child: Column(children: [
          for (final t in l.cast<Map>().take(12)) ListTile(dense: true, title: Text(t['title'], maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 13)), subtitle: Text('${t['source']} · ${t['category']} · ${ago(t['fetched_at'])}', style: const TextStyle(fontSize: 11))),
        ]))),
        const SectionTitle('Arka plan görevleri'),
        AsyncView<List>(value: tasks, isEmpty: (l) => l.isEmpty, emptyText: 'Görev yok', builder: (l) => Card(child: Column(children: [
          for (final t in l.cast<Map>().take(8))
            ListTile(
              dense: true,
              leading: Icon(t['status'] == 'DONE' ? Icons.check_circle : t['status'] == 'FAILED' ? Icons.error : Icons.sync, size: 18, color: t['status'] == 'DONE' ? AppColors.green : t['status'] == 'FAILED' ? AppColors.red : AppColors.accent),
              title: Text('${t['type']}', style: const TextStyle(fontSize: 13)),
              subtitle: Text('${t['status']} · ${ago(t['created_at'])}${(t['error'] as String).isNotEmpty ? '\n${t['error']}' : ''}', style: const TextStyle(fontSize: 11)),
              trailing: t['status'] == 'QUEUED' ? TextButton(onPressed: () async { await run(context, () => api.post('/api/v1/tasks/${t['id']}/cancel')); ref.invalidate(tasksProvider); }, child: const Text('İptal')) : null,
            ),
        ]))),
      ]),
    );
  }
}
