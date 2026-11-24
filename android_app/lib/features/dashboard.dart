import 'package:fl_chart/fl_chart.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

import '../core/format.dart';
import '../core/state.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';
import 'costs.dart';

class DashboardScreen extends ConsumerWidget {
  const DashboardScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final dash = ref.watch(dashboardProvider);
    final sys = ref.watch(systemProvider);
    return RefreshIndicator(
      onRefresh: () async {
        ref.invalidate(dashboardProvider);
        ref.invalidate(systemProvider);
        await ref.read(dashboardProvider.future);
      },
      child: AsyncView<Map>(
        value: dash,
        onRetry: () => ref.invalidate(dashboardProvider),
        builder: (d) => ListView(padding: const EdgeInsets.fromLTRB(14, 0, 14, 24), children: [
          _SystemBanner(sys: sys, d: d),
          const SizedBox(height: 8),
          GridView.count(
            crossAxisCount: 2,
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            childAspectRatio: 1.55,
            mainAxisSpacing: 10,
            crossAxisSpacing: 10,
            children: [
              StatTile(label: 'Toplam üretilen video', value: '${d['videos_total']}', icon: Icons.movie_outlined),
              StatTile(label: 'Bugünkü üretim', value: '${d['videos_today']}', icon: Icons.today_outlined, color: AppColors.blue),
              StatTile(label: 'Üretim kuyruğu', value: '${d['queue']}', icon: Icons.hourglass_top_rounded, color: AppColors.blue, hint: '${d['in_progress']} işleniyor'),
              StatTile(label: 'Tamamlanan', value: '${d['completed']}', icon: Icons.check_circle_outline, color: AppColors.green),
              StatTile(label: 'Başarısız', value: '${d['failed']}', icon: Icons.error_outline, color: AppColors.red),
              StatTile(label: 'İnceleme bekleyen', value: '${d['needs_review']}', icon: Icons.rate_review_outlined, color: AppColors.amber),
              StatTile(label: 'Yayına hazır', value: '${d['ready_to_publish']}', icon: Icons.outbox_outlined, color: AppColors.green),
              StatTile(label: 'Yayınlanan (doğrulanmış)', value: '${d['published_videos']}', icon: Icons.public, color: AppColors.green),
              StatTile(label: 'Toplam izlenme', value: compact(d['total_views'] as num?), icon: Icons.visibility_outlined, hint: d['total_views'] == null ? 'metrik yok' : null),
              StatTile(label: 'Etkileşim oranı', value: pct(d['engagement_rate'] as num?), icon: Icons.favorite_border, hint: d['engagement_rate'] == null ? 'metrik yok' : null),
              StatTile(label: 'Günlük maliyet', value: usd(d['cost_today_usd'] as num?), icon: Icons.payments_outlined, color: AppColors.amber),
              StatTile(label: 'Video başı ort. maliyet', value: usd(d['avg_cost_per_video_usd'] as num?), icon: Icons.calculate_outlined, color: AppColors.amber),
            ],
          ),
          if (d['metrics_note'] != null)
            Padding(padding: const EdgeInsets.only(top: 8), child: Text('ℹ ${d['metrics_note']}', style: const TextStyle(color: AppColors.muted, fontSize: 11.5))),
          const SectionTitle('Son 14 gün'),
          Card(child: Padding(padding: const EdgeInsets.fromLTRB(8, 16, 14, 8), child: SizedBox(height: 170, child: _SeriesChart(series: (d['series'] as List).cast<Map>())))),
          SectionTitle('Bütçe', trailing: TextButton(onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const CostsScreen())), child: const Text('Maliyet detayı'))),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(children: [
                Meter(label: 'Bugün', value: (d['budget']['spent_today_usd'] as num).toDouble(), max: (d['budget']['daily_usd'] as num).toDouble()),
                const SizedBox(height: 12),
                Meter(label: 'Bu ay', value: (d['budget']['spent_month_usd'] as num).toDouble(), max: (d['budget']['monthly_usd'] as num).toDouble()),
                if (d['budget']['paused'] == true) ...[
                  const SizedBox(height: 10),
                  Text('⏸ Üretim duraklatıldı: ${d['budget']['paused_reason']}', style: const TextStyle(color: AppColors.red, fontSize: 12)),
                ],
              ]),
            ),
          ),
          const SectionTitle('AI servislerinin durumu'),
          Card(child: Column(children: [for (final p in (d['providers'] as List).cast<Map>()) _ProviderRow(p)])),
        ]),
      ),
    );
  }
}

class _SystemBanner extends StatelessWidget {
  const _SystemBanner({required this.sys, required this.d});
  final AsyncValue<Map> sys;
  final Map d;
  @override
  Widget build(BuildContext context) {
    return sys.when(
      loading: () => const SizedBox(height: 4, child: LinearProgressIndicator()),
      error: (e, _) => Card(child: ListTile(leading: const Icon(Icons.cloud_off, color: AppColors.red), title: const Text('Sistem durumu alınamadı'), subtitle: Text('$e'))),
      data: (s) {
        final eager = s['queue_mode'].toString().startsWith('eager');
        final workersOk = s['workers']['ok'];
        final ok = s['ok'] == true && (eager || workersOk == true);
        final c = ok ? AppColors.green : AppColors.red;
        return Card(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Row(children: [
              Icon(ok ? Icons.check_circle : Icons.warning_amber_rounded, color: c),
              const SizedBox(width: 10),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(ok ? 'Sistem çalışıyor' : 'Sistem dikkat gerektiriyor', style: TextStyle(color: c, fontWeight: FontWeight.w800)),
                  Text(
                    'DB: ${s['database']['ok'] == true ? 'tamam' : 'HATA'} · Kuyruk: ${s['queue_mode']} · İşçi: ${eager ? 'eager' : (workersOk == true ? '${s['workers']['online']} çevrimiçi' : 'YOK')} · FFmpeg: ${s['ffmpeg']['ok'] == true ? 'tamam' : 'YOK'}',
                    style: const TextStyle(fontSize: 11.5, color: AppColors.muted),
                  ),
                ]),
              ),
            ]),
          ),
        );
      },
    );
  }
}

class _ProviderRow extends StatelessWidget {
  const _ProviderRow(this.p);
  final Map p;
  @override
  Widget build(BuildContext context) {
    final conf = p['configured'] == true;
    final sr = p['success_rate'] as num?;
    return ListTile(
      dense: true,
      leading: Icon(conf ? Icons.circle : Icons.circle_outlined, size: 12, color: !conf ? AppColors.muted : (p['last_error'] as String).isNotEmpty ? AppColors.amber : AppColors.green),
      title: Row(children: [
        Text('${kindLabels[p['kind']] ?? p['kind']} · ${p['label']}', style: const TextStyle(fontSize: 13)),
        const SizedBox(width: 6),
        if (p['is_ai'] == false) const Badge2('AI değil', color: AppColors.amber),
      ]),
      subtitle: Text(!conf ? 'yapılandırılmamış' : sr == null ? 'henüz çağrı yok' : '${p['calls']} çağrı · başarı ${pct(sr, d: 0)}${(p['last_error'] as String).isNotEmpty ? ' · son hata: ${p['last_error']}' : ''}',
          style: const TextStyle(fontSize: 11), maxLines: 2, overflow: TextOverflow.ellipsis),
    );
  }
}

class _SeriesChart extends StatelessWidget {
  const _SeriesChart({required this.series});
  final List<Map> series;
  @override
  Widget build(BuildContext context) {
    final maxY = series.fold<num>(1, (m, e) => [m, e['produced'] as num, e['published'] as num].reduce((a, b) => a > b ? a : b)).toDouble();
    return BarChart(BarChartData(
      maxY: maxY + 1,
      gridData: FlGridData(show: true, drawVerticalLine: false, getDrawingHorizontalLine: (_) => const FlLine(color: AppColors.line, strokeWidth: 0.6)),
      borderData: FlBorderData(show: false),
      titlesData: FlTitlesData(
        topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
        rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
        leftTitles: AxisTitles(sideTitles: SideTitles(showTitles: true, reservedSize: 28, interval: maxY > 6 ? (maxY / 4).ceilToDouble() : 1, getTitlesWidget: (v, _) => Text(v.toInt().toString(), style: const TextStyle(fontSize: 10, color: AppColors.muted)))),
        bottomTitles: AxisTitles(
          sideTitles: SideTitles(
            showTitles: true,
            reservedSize: 22,
            getTitlesWidget: (v, _) {
              final i = v.toInt();
              if (i < 0 || i >= series.length || i % 3 != 0) return const SizedBox.shrink();
              final d = series[i]['date'] as String;
              return Padding(padding: const EdgeInsets.only(top: 4), child: Text('${d.substring(8)}/${d.substring(5, 7)}', style: const TextStyle(fontSize: 10, color: AppColors.muted)));
            },
          ),
        ),
      ),
      barGroups: [
        for (var i = 0; i < series.length; i++)
          BarChartGroupData(x: i, barsSpace: 2, barRods: [
            BarChartRodData(toY: (series[i]['produced'] as num).toDouble(), color: AppColors.accent, width: 6, borderRadius: BorderRadius.circular(2)),
            BarChartRodData(toY: (series[i]['published'] as num).toDouble(), color: AppColors.green, width: 6, borderRadius: BorderRadius.circular(2)),
          ]),
      ],
    ));
  }
}
