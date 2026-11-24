import 'package:fl_chart/fl_chart.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

import '../core/format.dart';
import '../core/state.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';

class CostsScreen extends ConsumerStatefulWidget {
  const CostsScreen({super.key});
  @override
  ConsumerState<CostsScreen> createState() => _CostsState();
}

class _CostsState extends ConsumerState<CostsScreen> {
  final _daily = TextEditingController(), _monthly = TextEditingController(), _perVideo = TextEditingController();
  bool _inited = false, _block = true;

  @override
  Widget build(BuildContext context) {
    final sum = ref.watch(costSummaryProvider);
    final ledger = ref.watch(ledgerProvider);
    final api = ref.read(apiProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Maliyet ve bütçe')),
      body: AsyncView<Map>(
        value: sum,
        onRetry: () => ref.invalidate(costSummaryProvider),
        builder: (s) {
          final b = s['budget'] as Map;
          if (!_inited) {
            _inited = true;
            _daily.text = '${b['daily_usd']}';
            _monthly.text = '${b['monthly_usd']}';
            _perVideo.text = '${b['per_video_usd']}';
            _block = b['block_expensive_fallback'] == true;
          }
          final byKind = (s['by_kind'] as Map).cast<String, dynamic>();
          return ListView(padding: const EdgeInsets.fromLTRB(14, 0, 14, 30), children: [
            if (b['paused'] == true)
              Card(
                color: const Color(0xFF2B1717),
                child: Padding(
                  padding: const EdgeInsets.all(14),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    const Text('⏸ Üretim bütçe nedeniyle durduruldu', style: TextStyle(color: AppColors.red, fontWeight: FontWeight.w800)),
                    Text('${b['paused_reason']}', style: const TextStyle(fontSize: 12)),
                    const SizedBox(height: 8),
                    FilledButton(onPressed: () async { if (await run(context, () => api.post('/api/v1/costs/resume'), ok: 'Üretim devam ediyor')) ref.invalidate(costSummaryProvider); }, child: const Text('Limiti artırdım — devam et')),
                  ]),
                ),
              ),
            const SectionTitle('Harcama'),
            Card(child: Padding(padding: const EdgeInsets.all(14), child: Column(children: [
              Meter(label: 'Bugün', value: (b['spent_today_usd'] as num).toDouble(), max: (b['daily_usd'] as num).toDouble()),
              const SizedBox(height: 12),
              Meter(label: 'Bu ay', value: (b['spent_month_usd'] as num).toDouble(), max: (b['monthly_usd'] as num).toDouble()),
              const SizedBox(height: 12),
              Kv('Son ${s['days']} gün', usd(s['total_usd'] as num, d: 3)),
              Kv('Tahmini payı', '${usd(s['estimated_share_usd'] as num, d: 3)} (sağlayıcı maliyet bildirmedi)'),
            ]))),
            if (byKind.isNotEmpty) ...[
              const SectionTitle('Kalem dağılımı'),
              Card(child: Padding(padding: const EdgeInsets.all(14), child: SizedBox(height: 160, child: Row(children: [
                Expanded(child: PieChart(PieChartData(sectionsSpace: 2, centerSpaceRadius: 30, sections: [
                  for (final (i, e) in byKind.entries.indexed)
                    PieChartSectionData(value: (e.value as num).toDouble(), color: _palette[i % _palette.length], radius: 40, showTitle: false),
                ]))),
                Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.start, children: [
                  for (final (i, e) in byKind.entries.indexed) Row(children: [Icon(Icons.circle, size: 10, color: _palette[i % _palette.length]), const SizedBox(width: 6), Text('${costKindLabels[e.key] ?? e.key}  ${usd(e.value as num, d: 3)}', style: const TextStyle(fontSize: 12))]),
                ]),
              ])))),
              const SectionTitle('Sağlayıcı karşılaştırması'),
              Card(child: Column(children: [for (final e in (s['by_provider'] as Map).entries) ListTile(dense: true, title: Text('${e.key}'), trailing: Text(usd(e.value as num, d: 3)))])),
            ],
            const SectionTitle('Bütçe sınırları'),
            Card(child: Padding(padding: const EdgeInsets.all(14), child: Column(children: [
              _num(_daily, 'Günlük limit (USD)'),
              const SizedBox(height: 10),
              _num(_monthly, 'Aylık limit (USD)'),
              const SizedBox(height: 10),
              _num(_perVideo, 'Video başına limit (USD)'),
              SwitchListTile(contentPadding: EdgeInsets.zero, title: const Text('Pahalı sağlayıcıya otomatik geçişi engelle'), subtitle: const Text('Yedek sağlayıcı daha pahalı kademedeyse kullanılmaz'), value: _block, onChanged: (v) => setState(() => _block = v)),
              Align(alignment: Alignment.centerRight, child: FilledButton(onPressed: () async {
                final body = {'daily_usd': double.tryParse(_daily.text), 'monthly_usd': double.tryParse(_monthly.text), 'per_video_usd': double.tryParse(_perVideo.text), 'block_expensive_fallback': _block}..removeWhere((_, v) => v == null);
                if (await run(context, () => api.put('/api/v1/costs/budget', body: body), ok: 'Bütçe güncellendi')) { ref.invalidate(costSummaryProvider); ref.invalidate(budgetProvider); }
              }, child: const Text('Kaydet'))),
            ]))),
            const SectionTitle('Son harcamalar'),
            AsyncView<List>(value: ledger, isEmpty: (l) => l.isEmpty, emptyText: 'Henüz maliyet kaydı yok', builder: (l) => Card(child: Column(children: [
              for (final e in l.cast<Map>())
                ListTile(dense: true, title: Text('${costKindLabels[e['kind']] ?? e['kind']} · ${e['provider']}', style: const TextStyle(fontSize: 13)), subtitle: Text('${dt(e['created_at'])}${e['estimated'] == true ? ' · tahmini' : ' · sağlayıcı bildirimi'}', style: const TextStyle(fontSize: 11)), trailing: Text(usd(e['cost_usd'] as num, d: 4))),
            ]))),
          ]);
        },
      ),
    );
  }

  Widget _num(TextEditingController c, String l) => TextField(controller: c, keyboardType: const TextInputType.numberWithOptions(decimal: true), decoration: InputDecoration(labelText: l, isDense: true));
}

const _palette = [AppColors.accent, AppColors.green, AppColors.amber, AppColors.blue, AppColors.accent2, AppColors.red, AppColors.muted];
