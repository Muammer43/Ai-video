import 'dart:async';
import 'dart:io';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';
import 'package:video_player/video_player.dart';

import '../core/api_core.dart';
import '../core/format.dart';
import '../core/state.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';

class ProjectsScreen extends ConsumerStatefulWidget {
  const ProjectsScreen({super.key});
  @override
  ConsumerState<ProjectsScreen> createState() => _ProjectsState();
}

class _ProjectsState extends ConsumerState<ProjectsScreen> {
  String? _status;
  String _q = '';
  Timer? _deb;

  static const _filters = [
    (null, 'Tümü'),
    ('QUEUED,PROCESSING,WAITING_PROVIDER,RENDERING,QUALITY_CHECK', 'Üretimde'),
    ('NEEDS_REVIEW', 'İnceleme'),
    ('APPROVED,PUBLISHING', 'Yayına hazır'),
    ('PUBLISHED', 'Yayınlandı'),
    ('FAILED,CANCELLED', 'Başarısız/İptal'),
  ];

  @override
  Widget build(BuildContext context) {
    final f = ProjectFilter(status: _status, q: _q);
    final list = ref.watch(projectsProvider(f));
    return Column(children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(14, 0, 14, 4),
        child: TextField(
          decoration: const InputDecoration(hintText: 'Konuda ara…', prefixIcon: Icon(Icons.search), isDense: true),
          onChanged: (v) {
            _deb?.cancel();
            _deb = Timer(const Duration(milliseconds: 400), () => setState(() => _q = v.trim()));
          },
        ),
      ),
      SizedBox(
        height: 46,
        child: ListView(scrollDirection: Axis.horizontal, padding: const EdgeInsets.symmetric(horizontal: 12), children: [
          for (final x in _filters)
            Padding(padding: const EdgeInsets.symmetric(horizontal: 3, vertical: 6), child: ChoiceChip(label: Text(x.$2), selected: _status == x.$1, onSelected: (_) => setState(() => _status = x.$1))),
        ]),
      ),
      Expanded(
        child: RefreshIndicator(
          onRefresh: () async => ref.invalidate(projectsProvider(f)),
          child: AsyncView<Map>(
            value: list,
            onRetry: () => ref.invalidate(projectsProvider(f)),
            isEmpty: (d) => (d['items'] as List).isEmpty,
            emptyText: 'Bu filtrede proje yok.\nAI Video Studio\'dan yeni bir video üretin.',
            emptyIcon: Icons.video_library_outlined,
            builder: (d) => ListView.builder(
              padding: const EdgeInsets.fromLTRB(14, 0, 14, 20),
              itemCount: (d['items'] as List).length,
              itemBuilder: (_, i) => _ProjectCard((d['items'] as List)[i] as Map),
            ),
          ),
        ),
      ),
    ]);
  }
}

class _ProjectCard extends StatelessWidget {
  const _ProjectCard(this.p);
  final Map p;
  @override
  Widget build(BuildContext context) {
    final st = p['status'] as String;
    final active = activeStatuses.contains(st);
    return Card(
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => ProjectDetailScreen(id: p['id']))),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Expanded(child: Text(p['title'] ?? p['topic'], maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w700))),
              const SizedBox(width: 8),
              StatusChip(st),
            ]),
            const SizedBox(height: 6),
            Text('${p['category']} · ${p['duration_target']} sn · ${p['aspect_ratio']} · ${ago(p['created_at'])}', style: const TextStyle(color: AppColors.muted, fontSize: 11.5)),
            if (active) ...[
              const SizedBox(height: 10),
              LinearProgressIndicator(value: (p['progress'] as int) / 100, minHeight: 6, borderRadius: BorderRadius.circular(4)),
              const SizedBox(height: 4),
              Text('${p['stage_message'] ?? ''}  %${p['progress']}', style: const TextStyle(fontSize: 11.5, color: AppColors.muted), maxLines: 1, overflow: TextOverflow.ellipsis),
            ],
            if (!active && p['quality_score'] != null)
              Padding(padding: const EdgeInsets.only(top: 8), child: Row(children: [
                const Icon(Icons.verified_outlined, size: 14, color: AppColors.muted),
                const SizedBox(width: 4),
                Text('Kalite ${p['quality_score']}/100', style: const TextStyle(fontSize: 11.5)),
                const SizedBox(width: 12),
                Text('Maliyet ${usd(p['cost_actual'] as num)}', style: const TextStyle(fontSize: 11.5, color: AppColors.muted)),
              ])),
            if (st == 'FAILED' && (p['error'] as String).isNotEmpty)
              Padding(padding: const EdgeInsets.only(top: 6), child: Text(p['error'], maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(color: AppColors.red, fontSize: 11.5))),
          ]),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------- DETAY
class ProjectDetailScreen extends ConsumerStatefulWidget {
  const ProjectDetailScreen({super.key, required this.id});
  final String id;
  @override
  ConsumerState<ProjectDetailScreen> createState() => _DetailState();
}

class _DetailState extends ConsumerState<ProjectDetailScreen> {
  final _events = <Map>[];
  StreamSubscription? _sub;
  bool _override = false;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _sub = ref.read(apiProvider).sse('/api/v1/projects/${widget.id}/stream').listen((e) {
      if (!mounted) return;
      if (e['_end'] == true) {
        ref.invalidate(projectProvider(widget.id));
        return;
      }
      setState(() => _events.add(e));
      ref.invalidate(projectProvider(widget.id));
    }, onError: (_) {});
  }

  @override
  void dispose() {
    _sub?.cancel();
    super.dispose();
  }

  Future<void> _act(Future<dynamic> Function() f, String ok) async {
    setState(() => _busy = true);
    await run(context, f, ok: ok);
    ref.invalidate(projectProvider(widget.id));
    ref.read(tickProvider.notifier).bump();
    if (mounted) setState(() => _busy = false);
  }

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(projectProvider(widget.id));
    final api = ref.read(apiProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Proje detayı'), actions: [
        IconButton(
            tooltip: 'Sil',
            icon: const Icon(Icons.delete_outline),
            onPressed: () async {
              if (await confirm(context, 'Projeyi sil', 'Video ve tüm dosyalar kalıcı olarak silinir.', ok: 'Sil')) {
                if (!context.mounted) return;
                if (await run(context, () => api.delete('/api/v1/projects/${widget.id}'), ok: 'Silindi') && context.mounted) {
                  ref.read(tickProvider.notifier).bump();
                  Navigator.pop(context);
                }
              }
            }),
      ]),
      body: AsyncView<Map>(
        value: async,
        onRetry: () => ref.invalidate(projectProvider(widget.id)),
        builder: (p) {
          final st = p['status'] as String;
          final qr = (p['quality_report'] ?? {}) as Map;
          final crit = (qr['critical'] as List?) ?? [];
          return ListView(padding: const EdgeInsets.fromLTRB(14, 0, 14, 30), children: [
            Text(p['title'] ?? p['topic'], style: const TextStyle(fontSize: 19, fontWeight: FontWeight.w800)),
            const SizedBox(height: 4),
            Text('${p['topic']}', style: const TextStyle(color: AppColors.muted, fontSize: 12)),
            const SizedBox(height: 10),
            Row(children: [StatusChip(st), const SizedBox(width: 8), Text('%${p['progress']}', style: const TextStyle(fontWeight: FontWeight.w700)), const Spacer(), Text('deneme ${p['attempts']}', style: const TextStyle(color: AppColors.muted, fontSize: 11))]),
            const SizedBox(height: 8),
            LinearProgressIndicator(value: (p['progress'] as int) / 100, minHeight: 7, borderRadius: BorderRadius.circular(5)),
            const SizedBox(height: 6),
            Text(p['stage_message'] ?? '', style: const TextStyle(fontSize: 12, color: AppColors.muted)),
            const SizedBox(height: 10),
            PipelineBar(stage: p['stage'], status: st),
            if (st == 'FAILED' && (p['error'] as String).isNotEmpty)
              Card(color: const Color(0xFF2B1717), child: Padding(padding: const EdgeInsets.all(12), child: Text('${p['error_code']}: ${p['error']}', style: const TextStyle(color: AppColors.red, fontSize: 12.5)))),
            _Actions(p: p, busy: _busy, forceOverride: _override, crit: crit, onOverride: (v) => setState(() => _override = v), act: _act, api: api),
            if (p['has_video'] == true) _VideoPlayerCard(id: widget.id, aspect: p['aspect_ratio']),
            if (p['has_video'] == true) _DownloadButton(id: widget.id),
            if (qr.isNotEmpty) _QcCard(qr: qr, score: p['quality_score']),
            if ((p['script'] ?? {}).isNotEmpty) _ScriptCard(p: p),
            if ((p['media_report'] ?? {}).isNotEmpty) _MediaCard(p: p),
            if ((p['publications'] as List?)?.isNotEmpty ?? false) _PubCard(pubs: (p['publications'] as List).cast<Map>(), api: api, onChanged: () => ref.invalidate(projectProvider(widget.id))),
            _CostCard(estimate: p['cost_estimate'] as num, actual: p['cost_actual'] as num, id: widget.id),
            const SectionTitle('Canlı günlük'),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: _events.isEmpty
                    ? const Text('Olay bekleniyor…', style: TextStyle(color: AppColors.muted, fontSize: 12))
                    : Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        for (final e in _events.reversed.take(40))
                          Padding(
                            padding: const EdgeInsets.symmetric(vertical: 2),
                            child: Text('${(e['created_at'] as String).substring(11, 19)}  [${e['stage']}] ${e['message']}',
                                style: TextStyle(fontSize: 11.5, color: e['level'] == 'error' ? AppColors.red : e['level'] == 'warning' ? AppColors.amber : AppColors.muted)),
                          ),
                      ]),
              ),
            ),
          ]);
        },
      ),
    );
  }
}

class _Actions extends StatelessWidget {
  const _Actions({required this.p, required this.busy, required this.forceOverride, required this.crit, required this.onOverride, required this.act, required this.api});
  final Map p;
  final bool busy, forceOverride;
  final List crit;
  final void Function(bool) onOverride;
  final Future<void> Function(Future<dynamic> Function(), String) act;
  final ApiClient api;
  @override
  Widget build(BuildContext context) {
    final st = p['status'] as String, id = p['id'] as String;
    final btns = <Widget>[];
    if (activeStatuses.contains(st)) {
      btns.add(OutlinedButton.icon(onPressed: busy ? null : () async {
        if (await confirm(context, 'İşi iptal et', 'Üretim en yakın güvenli noktada durdurulur.')) act(() => api.post('/api/v1/projects/$id/cancel'), 'İptal istendi');
      }, icon: const Icon(Icons.stop_circle_outlined), label: const Text('İptal et')));
    }
    if (const {'FAILED', 'CANCELLED', 'NEEDS_REVIEW'}.contains(st)) {
      btns.add(OutlinedButton.icon(onPressed: busy ? null : () => act(() => api.post('/api/v1/projects/$id/retry', body: {'reset': false}), 'Yeniden kuyruğa alındı'), icon: const Icon(Icons.refresh), label: const Text('Yeniden dene')));
      if (st != 'NEEDS_REVIEW') {
        btns.add(OutlinedButton.icon(onPressed: busy ? null : () async {
          if (await confirm(context, 'Sıfırdan üret', 'Senaryo, sahneler ve dosyalar silinip baştan üretilir (maliyet oluşur).')) act(() => api.post('/api/v1/projects/$id/retry', body: {'reset': true}), 'Sıfırdan başlatıldı');
        }, icon: const Icon(Icons.restart_alt), label: const Text('Sıfırdan')));
      }
    }
    final review = st == 'NEEDS_REVIEW' || st == 'APPROVED';
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      if (st == 'NEEDS_REVIEW')
        Card(
          color: const Color(0xFF2B2413),
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('Kullanıcı incelemesi gerekli', style: TextStyle(color: AppColors.amber, fontWeight: FontWeight.w800)),
              const SizedBox(height: 4),
              for (final r in ((p['quality_report']?['reasons'] as List?) ?? [])) Text('• $r', style: const TextStyle(fontSize: 12)),
              if (crit.isNotEmpty) CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                value: forceOverride,
                onChanged: (v) => onOverride(v ?? false),
                title: Text('Kritik bulgulara (${crit.join(', ')}) rağmen yayınlamayı kabul ediyorum', style: const TextStyle(fontSize: 12)),
              ),
            ]),
          ),
        ),
      Wrap(spacing: 8, runSpacing: 8, children: [
        ...btns,
        if (review)
          FilledButton.icon(
            onPressed: busy || (crit.isNotEmpty && !forceOverride) ? null : () => act(() async {
              final r = await api.post('/api/v1/projects/$id/approve', body: {'override': forceOverride}) as Map;
              if (context.mounted) toast(context, r['message']);
            }, 'Onaylandı'),
            icon: const Icon(Icons.publish),
            label: const Text('Onayla ve yayınla'),
          ),
        if (st == 'NEEDS_REVIEW')
          OutlinedButton.icon(onPressed: busy ? null : () => act(() => api.post('/api/v1/projects/$id/reject'), 'Reddedildi'), icon: const Icon(Icons.thumb_down_alt_outlined), label: const Text('Reddet')),
      ]),
    ]);
  }
}

class _VideoPlayerCard extends ConsumerStatefulWidget {
  const _VideoPlayerCard({required this.id, required this.aspect});
  final String id, aspect;
  @override
  ConsumerState<_VideoPlayerCard> createState() => _VideoState();
}

class _VideoState extends ConsumerState<_VideoPlayerCard> {
  VideoPlayerController? _c;
  String? _err;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final api = ref.read(apiProvider);
      final m = await api.get('/api/v1/projects/${widget.id}/media') as Map;
      final c = VideoPlayerController.networkUrl(Uri.parse('${api.baseUrl}${m['video']['path']}'));
      await c.initialize();
      if (!mounted) {
        c.dispose();
        return;
      }
      setState(() => _c = c);
    } catch (e) {
      if (mounted) setState(() => _err = 'Video yüklenemedi: $e');
    }
  }

  @override
  void dispose() {
    _c?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = _c;
    return Card(
      clipBehavior: Clip.antiAlias,
      child: _err != null
          ? Padding(padding: const EdgeInsets.all(16), child: Text(_err!, style: const TextStyle(color: AppColors.red)))
          : c == null
              ? const SizedBox(height: 220, child: Center(child: CircularProgressIndicator()))
              : Column(children: [
                  ConstrainedBox(constraints: const BoxConstraints(maxHeight: 460), child: AspectRatio(aspectRatio: c.value.aspectRatio, child: VideoPlayer(c))),
                  ValueListenableBuilder<VideoPlayerValue>(
                    valueListenable: c,
                    builder: (_, v, _) => Row(children: [
                      IconButton(icon: Icon(v.isPlaying ? Icons.pause_circle : Icons.play_circle), iconSize: 34, onPressed: () => v.isPlaying ? c.pause() : c.play()),
                      Expanded(child: Slider(value: v.position.inMilliseconds.clamp(0, v.duration.inMilliseconds).toDouble(), max: v.duration.inMilliseconds.toDouble().clamp(1, double.infinity), onChanged: (x) => c.seekTo(Duration(milliseconds: x.round())))),
                      Text('${v.position.inSeconds}/${v.duration.inSeconds}s', style: const TextStyle(fontSize: 11)),
                      const SizedBox(width: 10),
                    ]),
                  ),
                ]),
    );
  }
}

class _DownloadButton extends ConsumerStatefulWidget {
  const _DownloadButton({required this.id});
  final String id;
  @override
  ConsumerState<_DownloadButton> createState() => _DlState();
}

class _DlState extends ConsumerState<_DownloadButton> {
  double? _prog;
  Future<void> _download() async {
    final api = ref.read(apiProvider);
    setState(() => _prog = 0);
    try {
      final m = await api.get('/api/v1/projects/${widget.id}/media') as Map;
      final dir = await getApplicationDocumentsDirectory();
      final f = File('${dir.path}/ai_video_${widget.id.substring(0, 8)}.mp4');
      await api.dio.download(m['video']['path'], f.path, onReceiveProgress: (r, t) => setState(() => _prog = t > 0 ? r / t : null));
      setState(() => _prog = null);
      if (!mounted) return;
      toast(context, 'İndirildi: ${f.path}');
      await SharePlus.instance.share(ShareParams(files: [XFile(f.path, mimeType: 'video/mp4')], text: 'AI Video Factory'));
    } catch (e) {
      setState(() => _prog = null);
      if (mounted) toast(context, 'İndirme hatası: $e', error: true);
    }
  }

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: 4),
        child: OutlinedButton.icon(onPressed: _prog == null ? _download : null, icon: const Icon(Icons.download_rounded), label: Text(_prog == null ? 'MP4 indir / paylaş' : 'İndiriliyor %${(_prog! * 100).round()}')),
      );
}

class _QcCard extends StatelessWidget {
  const _QcCard({required this.qr, required this.score});
  final Map qr;
  final dynamic score;
  @override
  Widget build(BuildContext context) {
    final decision = qr['decision'] as String;
    final c = decision == 'auto_publish' ? AppColors.green : decision == 'review' ? AppColors.amber : AppColors.red;
    final lbl = decision == 'auto_publish' ? 'Otomatik yayına uygun' : decision == 'review' ? 'İnceleme gerekli' : 'Reddedildi';
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const SectionTitle('Kalite kontrolü'),
      Card(
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Text('$score', style: TextStyle(fontSize: 34, fontWeight: FontWeight.w900, color: c)),
              const Text(' / 100', style: TextStyle(color: AppColors.muted)),
              const SizedBox(width: 14),
              Expanded(child: Text(lbl, style: TextStyle(color: c, fontWeight: FontWeight.w800))),
            ]),
            for (final r in (qr['reasons'] as List)) Text('• $r', style: const TextStyle(fontSize: 12, color: AppColors.muted)),
            const Divider(),
            for (final k in (qr['checks'] as List).cast<Map>())
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 3),
                child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Icon(k['status'] == 'pass' ? Icons.check_circle : k['status'] == 'warn' ? Icons.warning_amber_rounded : Icons.cancel, size: 16, color: k['status'] == 'pass' ? AppColors.green : k['status'] == 'warn' ? AppColors.amber : AppColors.red),
                  const SizedBox(width: 8),
                  Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(k['name'] + (k['critical'] == true ? '  · KRİTİK' : ''), style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600)),
                    Text(k['detail'], style: const TextStyle(fontSize: 11, color: AppColors.muted)),
                  ])),
                ]),
              ),
            if ((qr['risk_flags'] as List).isNotEmpty) ...[
              const Divider(),
              const Text('Risk bayrakları', style: TextStyle(fontWeight: FontWeight.w700, fontSize: 12.5)),
              for (final f in (qr['risk_flags'] as List).cast<Map>()) Text('⚑ ${f['detail']}', style: TextStyle(fontSize: 11.5, color: f['severity'] == 'high' ? AppColors.amber : AppColors.muted)),
            ],
          ]),
        ),
      ),
    ]);
  }
}

class _ScriptCard extends StatelessWidget {
  const _ScriptCard({required this.p});
  final Map p;
  @override
  Widget build(BuildContext context) {
    final s = p['script'] as Map;
    final meta = (p['script_meta'] ?? {}) as Map;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      SectionTitle('Senaryo', trailing: meta['is_ai'] == false ? const Badge2('Şablon — AI değil', color: AppColors.amber) : Badge2(meta['provider'] ?? '', color: AppColors.accent)),
      Card(
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Hook: ${s['hook'] ?? ''}', style: const TextStyle(fontWeight: FontWeight.w700)),
            const SizedBox(height: 8),
            for (final sc in (p['scenes'] as List).cast<Map>())
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Container(width: 22, height: 22, alignment: Alignment.center, decoration: BoxDecoration(color: AppColors.panel2, borderRadius: BorderRadius.circular(6)), child: Text('${(sc['idx'] as int) + 1}', style: const TextStyle(fontSize: 11))),
                  const SizedBox(width: 8),
                  Expanded(child: Text(sc['narration'], style: const TextStyle(fontSize: 12.5))),
                ]),
              ),
            const Divider(),
            Text('Başlık: ${s['title'] ?? ''}', style: const TextStyle(fontSize: 12)),
            Text('Açıklama: ${s['description'] ?? ''}', style: const TextStyle(fontSize: 12, color: AppColors.muted)),
            Text((s['hashtags'] as List? ?? []).join(' '), style: const TextStyle(fontSize: 12, color: AppColors.accent)),
            if ((s['facts_to_verify'] as List? ?? []).isNotEmpty) Text('Doğrulanacak iddialar: ${(s['facts_to_verify'] as List).join('; ')}', style: const TextStyle(fontSize: 11.5, color: AppColors.amber)),
          ]),
        ),
      ),
    ]);
  }
}

class _MediaCard extends StatelessWidget {
  const _MediaCard({required this.p});
  final Map p;
  @override
  Widget build(BuildContext context) {
    final mr = p['media_report'] as Map;
    final counts = (mr['counts'] as Map?) ?? {};
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const SectionTitle('Medya kökeni (dürüst raporlama)'),
      Card(
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Wrap(spacing: 8, runSpacing: 6, children: [for (final e in counts.entries) Badge2('${originLabels[e.key] ?? e.key} × ${e.value}', color: e.key == 'ai_video' ? AppColors.green : e.key == 'procedural' ? AppColors.amber : AppColors.accent)]),
            const SizedBox(height: 6),
            Text('Gerçek AI video oranı: ${pct((mr['ai_video_ratio'] as num?) ?? 0, d: 0)}', style: const TextStyle(fontSize: 12)),
            for (final f in ((mr['fallbacks'] as List?) ?? []).cast<Map>()) Text('↪ Sahne ${(f['scene'] as int) + 1} ${f['step']} başarısız → yedek (${(f['reason'] as List).isNotEmpty ? (f['reason'] as List).last : ''})', style: const TextStyle(fontSize: 11, color: AppColors.muted)),
          ]),
        ),
      ),
    ]);
  }
}

class _PubCard extends StatelessWidget {
  const _PubCard({required this.pubs, required this.api, required this.onChanged});
  final List<Map> pubs;
  final ApiClient api;
  final VoidCallback onChanged;
  @override
  Widget build(BuildContext context) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const SectionTitle('Yayınlar (platform doğrulamalı)'),
        Card(
          child: Column(children: [
            for (final x in pubs)
              ListTile(
                title: Text('${x['platform']}', style: const TextStyle(fontWeight: FontWeight.w700)),
                subtitle: Text([if ((x['external_url'] as String? ?? '').isNotEmpty) x['external_url'], if ((x['error'] as String? ?? '').isNotEmpty) x['error'], if (x['effective_privacy'] != '') 'görünürlük: ${x['effective_privacy']}'].join('\n'), style: const TextStyle(fontSize: 11.5)),
                trailing: x['status'] == 'FAILED' || x['status'] == 'NEEDS_ACTION'
                    ? TextButton(onPressed: () async { await run(context, () => api.post('/api/v1/publications/${x['id']}/retry'), ok: 'Yeniden denenecek'); onChanged(); }, child: const Text('Tekrar'))
                    : Badge2(x['status'], color: x['status'] == 'PUBLISHED' ? AppColors.green : AppColors.accent),
                isThreeLine: true,
              ),
          ]),
        ),
      ]);
}

class _CostCard extends ConsumerWidget {
  const _CostCard({required this.estimate, required this.actual, required this.id});
  final num estimate, actual;
  final String id;
  @override
  Widget build(BuildContext context, WidgetRef ref) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const SectionTitle('Maliyet'),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(children: [
              Kv('Tahmin', usd(estimate)),
              Kv('Gerçekleşen', usd(actual, d: 3)),
              FutureBuilder(
                future: ref.read(apiProvider).get('/api/v1/costs/ledger', query: {'project_id': id, 'limit': 40}),
                builder: (_, s) => !s.hasData ? const SizedBox.shrink() : Column(children: [for (final e in (s.data as List).cast<Map>()) Kv('${e['kind']} · ${e['provider']}', '${usd(e['cost_usd'] as num, d: 4)}${e['estimated'] == true ? ' (tahmini)' : ''}')]),
              ),
            ]),
          ),
        ),
      ]);
}
