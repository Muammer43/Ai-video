import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

import '../core/format.dart';
import '../core/state.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';
import 'projects.dart';

class CalendarScreen extends ConsumerWidget {
  const CalendarScreen({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final cal = ref.watch(calendarProvider);
    final api = ref.read(apiProvider);
    return RefreshIndicator(
      onRefresh: () async => ref.invalidate(calendarProvider),
      child: AsyncView<Map>(
        value: cal,
        onRetry: () => ref.invalidate(calendarProvider),
        isEmpty: (d) => (d['publications'] as List).isEmpty && (d['pipeline'] as List).isEmpty,
        emptyText: 'Planlanmış yayın veya üretimde iş yok.',
        emptyIcon: Icons.calendar_month_outlined,
        builder: (d) {
          final pubs = (d['publications'] as List).cast<Map>();
          final groups = <String, List<Map>>{};
          pubs.sort((a, b) => ((a['scheduled_at'] ?? a['published_at'] ?? '') as String).compareTo((b['scheduled_at'] ?? b['published_at'] ?? '') as String));
          for (final p in pubs) {
            groups.putIfAbsent(dayKey(p['scheduled_at'] ?? p['published_at']), () => []).add(p);
          }
          return ListView(padding: const EdgeInsets.fromLTRB(14, 0, 14, 30), children: [
            if ((d['pipeline'] as List).isNotEmpty) ...[
              const SectionTitle('Üretim hattında'),
              for (final p in (d['pipeline'] as List).cast<Map>())
                Card(child: ListTile(
                  onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => ProjectDetailScreen(id: p['id']))),
                  title: Text(p['topic'], maxLines: 1, overflow: TextOverflow.ellipsis),
                  subtitle: Text(p['publish_at'] != null ? 'Planlı yayın: ${dt(p['publish_at'])}' : 'Yayın zamanı: kalite onayından hemen sonra', style: const TextStyle(fontSize: 11.5)),
                  trailing: StatusChip(p['status']),
                )),
            ],
            for (final e in groups.entries) ...[
              SectionTitle(e.key),
              for (final x in e.value)
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Row(children: [
                        Icon(x['platform'] == 'youtube' ? Icons.smart_display : x['platform'] == 'tiktok' ? Icons.music_note : Icons.camera_alt_outlined, size: 18, color: AppColors.accent),
                        const SizedBox(width: 8),
                        Expanded(child: Text('${x['topic'] ?? x['title']}', maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w700))),
                        Badge2(x['status'], color: x['status'] == 'PUBLISHED' ? AppColors.green : x['status'] == 'FAILED' ? AppColors.red : x['status'] == 'NEEDS_ACTION' ? AppColors.amber : AppColors.accent),
                      ]),
                      const SizedBox(height: 4),
                      Text('${x['platform']} · ${x['scheduled_at'] != null ? 'planlı ${dt(x['scheduled_at'])}' : ''}${x['published_at'] != null ? ' · yayın ${dt(x['published_at'])}${x['verified'] == true ? ' (doğrulandı)' : ''}' : ''}', style: const TextStyle(fontSize: 11.5, color: AppColors.muted)),
                      if ((x['error'] as String).isNotEmpty) Text(x['error'], style: const TextStyle(fontSize: 11.5, color: AppColors.amber)),
                      Wrap(children: [
                        if ((x['external_url'] as String).isNotEmpty) Text(x['external_url'], style: const TextStyle(fontSize: 11.5, color: AppColors.accent)),
                      ]),
                      if (const {'QUEUED', 'FAILED', 'NEEDS_ACTION'}.contains(x['status']))
                        Row(mainAxisAlignment: MainAxisAlignment.end, children: [
                          TextButton(
                            onPressed: () async {
                              final d0 = await showDatePicker(context: context, initialDate: DateTime.now().add(const Duration(hours: 1)), firstDate: DateTime.now(), lastDate: DateTime.now().add(const Duration(days: 90)));
                              if (d0 == null || !context.mounted) return;
                              final t = await showTimePicker(context: context, initialTime: TimeOfDay.now());
                              if (t == null || !context.mounted) return;
                              final when = DateTime(d0.year, d0.month, d0.day, t.hour, t.minute).toUtc();
                              await run(context, () => api.post('/api/v1/publications/${x['id']}/reschedule', body: {'scheduled_at': when.toIso8601String()}), ok: 'Yeniden zamanlandı');
                              ref.invalidate(calendarProvider);
                            },
                            child: const Text('Zamanla'),
                          ),
                          if (x['status'] != 'QUEUED') TextButton(onPressed: () async { await run(context, () => api.post('/api/v1/publications/${x['id']}/retry'), ok: 'Yeniden denenecek'); ref.invalidate(calendarProvider); }, child: const Text('Tekrar dene')),
                          TextButton(onPressed: () async { await run(context, () => api.post('/api/v1/publications/${x['id']}/cancel'), ok: 'İptal edildi'); ref.invalidate(calendarProvider); }, child: const Text('İptal', style: TextStyle(color: AppColors.red))),
                        ]),
                    ]),
                  ),
                ),
            ],
          ]);
        },
      ),
    );
  }
}
