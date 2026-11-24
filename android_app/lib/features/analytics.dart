import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

import '../core/format.dart';
import '../core/state.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';

class AnalyticsScreen extends ConsumerWidget {
  const AnalyticsScreen({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ov = ref.watch(overviewProvider);
    final ins = ref.watch(insightsProvider);
    final ex = ref.watch(experimentsProvider);
    final api = ref.read(apiProvider);
    return RefreshIndicator(
      onRefresh: () async {
        ref.invalidate(overviewProvider);
        ref.invalidate(insightsProvider);
        ref.invalidate(experimentsProvider);
      },
      child: ListView(padding: const EdgeInsets.fromLTRB(14, 0, 14, 30), children: [
        AsyncView<Map>(value: ov, onRetry: () => ref.invalidate(overviewProvider), builder: (o) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          GridView.count(crossAxisCount: 3, shrinkWrap: true, physics: const NeverScrollableScrollPhysics(), childAspectRatio: 1.25, mainAxisSpacing: 8, crossAxisSpacing: 8, children: [
            StatTile(label: 'Yayınlanan', value: '${o['published_videos']}', icon: Icons.public, color: AppColors.green),
            StatTile(label: 'İzlenme', value: compact(o['total_views'] as num?), icon: Icons.visibility_outlined),
            StatTile(label: 'Etkileşim', value: pct(o['engagement_rate'] as num?), icon: Icons.favorite_border),
          ]),
          if (o['note'] != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text('ℹ ${o['note']}', style: const TextStyle(color: AppColors.muted, fontSize: 11.5))),
          Row(children: [
            const Expanded(child: SectionTitle('En iyi videolar (ölçülmüş)')),
            TextButton.icon(onPressed: () async { await run(context, () => api.post('/api/v1/analytics/collect'), ok: 'Metrikler toplandı'); ref.invalidate(overviewProvider); ref.invalidate(insightsProvider); }, icon: const Icon(Icons.sync, size: 16), label: const Text('Metrikleri çek')),
          ]),
          if ((o['top_videos'] as List).isEmpty) const Card(child: Padding(padding: EdgeInsets.all(16), child: Text('Henüz ölçülmüş performans verisi yok. Videolar yayınlandıktan sonra platform API\'lerinden toplanır.', style: TextStyle(color: AppColors.muted, fontSize: 12)))),
          for (final v in (o['top_videos'] as List).cast<Map>()) Card(child: ListTile(dense: true, title: Text('${v['category']} · ${v['platform']}'), subtitle: Text('${v['metric'] == 'view_through' ? 'izlenme-geçişi' : 'etkileşim'} ${pct(v['score'] as num)} · ${compact(v['views'] as num)} izlenme'))),
        ])),
        const SectionTitle('Öğrenme motoru — içgörüler'),
        AsyncView<Map>(value: ins, onRetry: () => ref.invalidate(insightsProvider), builder: (i) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Card(
            color: i['sufficient'] == true ? null : const Color(0xFF2B2413),
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(i['sufficient'] == true ? '${i['n_videos']} ölçülmüş video üzerinden' : 'Veri yetersiz: ${i['n_videos']}/${i['min_required']} video', style: TextStyle(fontWeight: FontWeight.w800, color: i['sufficient'] == true ? AppColors.green : AppColors.amber)),
                const SizedBox(height: 6),
                for (final s in (i['insights'] as List)) Padding(padding: const EdgeInsets.symmetric(vertical: 2), child: Text('• $s', style: const TextStyle(fontSize: 12.5))),
                const SizedBox(height: 6),
                Text(i['note'] ?? '', style: const TextStyle(fontSize: 11, color: AppColors.muted)),
              ]),
            ),
          ),
          for (final (key, title) in const [('category', 'Kategori'), ('duration', 'Video uzunluğu'), ('posting_time', 'Yayın saati'), ('hook', 'Hook türü'), ('platform', 'Platform')])
            if ((i[key] as List).isNotEmpty) _Ranked(title: title, rows: (i[key] as List).cast<Map>()),
        ])),
        SectionTitle('A/B testleri', trailing: TextButton.icon(onPressed: () => _newExperiment(context, ref), icon: const Icon(Icons.add), label: const Text('Yeni test'))),
        AsyncView<List>(value: ex, isEmpty: (l) => l.isEmpty, emptyText: 'Deney yok. Başlık, hook, kapak veya format için test başlatın.', emptyIcon: Icons.science_outlined, builder: (l) => Column(children: [
          for (final e in l.cast<Map>()) _ExperimentCard(e: e, onStop: () async { await run(context, () => api.delete('/api/v1/analytics/experiments/${e['id']}')); ref.invalidate(experimentsProvider); }),
        ])),
      ]),
    );
  }

  Future<void> _newExperiment(BuildContext context, WidgetRef ref) async {
    String kind = 'hook';
    final minViews = TextEditingController(text: '500');
    final ok = await showDialog<bool>(context: context, builder: (_) => StatefulBuilder(builder: (c, set) => AlertDialog(
      title: const Text('Yeni A/B testi'),
      content: Column(mainAxisSize: MainAxisSize.min, children: [
        DropdownButtonFormField<String>(initialValue: kind, items: const [DropdownMenuItem(value: 'hook', child: Text('Hook (soru vs iddia)')), DropdownMenuItem(value: 'title', child: Text('Başlık (merak vs açıklayıcı)')), DropdownMenuItem(value: 'cover', child: Text('Kapak (başlıklı vs başlıksız)')), DropdownMenuItem(value: 'format', child: Text('Format (30 sn vs 45 sn)'))], onChanged: (v) => set(() => kind = v!)),
        const SizedBox(height: 10),
        TextField(controller: minViews, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Varyant başına asgari izlenme')),
        const SizedBox(height: 8),
        const Text('Otomasyon, yeni videolara varyantları dengeli atar. Sonuç yalnızca yeterli veriyle açıklanır.', style: TextStyle(fontSize: 11, color: AppColors.muted)),
      ]),
      actions: [TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Vazgeç')), FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Başlat'))],
    )));
    if (ok == true && context.mounted) {
      await run(context, () => ref.read(apiProvider).post('/api/v1/analytics/experiments', body: {'kind': kind, 'min_views_per_variant': int.tryParse(minViews.text) ?? 500}), ok: 'Deney başlatıldı');
      ref.invalidate(experimentsProvider);
    }
  }
}

class _Ranked extends StatelessWidget {
  const _Ranked({required this.title, required this.rows});
  final String title;
  final List<Map> rows;
  @override
  Widget build(BuildContext context) {
    final maxV = rows.fold<double>(0.0001, (m, r) => ((r['mean'] as num?)?.toDouble() ?? 0) > m ? (r['mean'] as num).toDouble() : m);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: const TextStyle(fontWeight: FontWeight.w800)),
          const SizedBox(height: 6),
          for (final r in rows)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Expanded(child: Text('${r['group']}', style: const TextStyle(fontSize: 12.5))),
                  Text('${r['mean'] == null ? '—' : pct(r['mean'] as num)}  (n=${r['n']})', style: const TextStyle(fontSize: 12)),
                  const SizedBox(width: 6),
                  Badge2('güven: ${r['confidence']}', color: r['confidence'] == 'yetersiz' ? AppColors.red : r['confidence'] == 'düşük' ? AppColors.amber : AppColors.green),
                ]),
                const SizedBox(height: 3),
                LinearProgressIndicator(value: ((r['mean'] as num?)?.toDouble() ?? 0) / maxV, minHeight: 5, borderRadius: BorderRadius.circular(3)),
                if (r['ci90'] != null) Text('%90 aralık: ${pct((r['ci90'] as List)[0] as num)} – ${pct((r['ci90'] as List)[1] as num)}', style: const TextStyle(fontSize: 10.5, color: AppColors.muted)),
              ]),
            ),
        ]),
      ),
    );
  }
}

class _ExperimentCard extends StatelessWidget {
  const _ExperimentCard({required this.e, required this.onStop});
  final Map e;
  final VoidCallback onStop;
  @override
  Widget build(BuildContext context) {
    final r = (e['result'] ?? {}) as Map;
    final vars = (r['variants'] ?? {}) as Map;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text('Test: ${e['kind']}', style: const TextStyle(fontWeight: FontWeight.w800))),
            Badge2(e['status'] == 'running' ? 'sürüyor' : e['status'] == 'concluded' ? 'sonuçlandı' : 'sonuçsuz', color: e['status'] == 'concluded' ? AppColors.green : AppColors.accent),
            if (e['status'] == 'running') IconButton(visualDensity: VisualDensity.compact, icon: const Icon(Icons.stop_circle_outlined, size: 20), onPressed: onStop),
          ]),
          for (final v in vars.entries) Text('${v.key}: ${v.value['label']} — n=${v.value['n']}, izlenme ${v.value['views']}, ort. ${v.value['mean'] == null ? '—' : pct(v.value['mean'] as num)}', style: const TextStyle(fontSize: 12)),
          const SizedBox(height: 4),
          Text(r['conclusive'] == true ? '🏆 Kazanan: ${r['winner']} (p=${r['p_value']})' : 'Sonuç yok: ${r['reason'] ?? 'veri bekleniyor'}', style: TextStyle(fontSize: 12, color: r['conclusive'] == true ? AppColors.green : AppColors.amber)),
          if (r['caveat'] != null) Text(r['caveat'], style: const TextStyle(fontSize: 10.5, color: AppColors.muted)),
        ]),
      ),
    );
  }
}
