import 'dart:math';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

import '../core/format.dart';
import '../core/state.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';
import 'projects.dart';

class StudioScreen extends ConsumerStatefulWidget {
  const StudioScreen({super.key, this.initialTopic, this.initialCategory, this.ideaId, this.channel});
  final String? initialTopic, initialCategory, ideaId;
  final Map? channel;
  @override
  ConsumerState<StudioScreen> createState() => _StudioState();
}

class _StudioState extends ConsumerState<StudioScreen> {
  final _form = GlobalKey<FormState>();
  late final _topic = TextEditingController(text: widget.initialTopic ?? '');
  late String _category = widget.initialCategory ?? 'Bilim';
  final _customCat = TextEditingController();
  bool _custom = false;
  double _duration = 30;
  String _style = 'cinematic', _lang = 'tr', _aspect = '9:16', _res = '720p', _tier = 'standard', _mode = 'hybrid', _gender = 'female', _emotion = 'neutral', _publishMode = 'auto', _privacy = 'public';
  double _speed = 1.0;
  final _platforms = <String>{'youtube', 'tiktok', 'instagram'};
  bool _subs = true, _music = true;
  Map? _estimate;
  bool _busy = false;
  final _idem = '${DateTime.now().microsecondsSinceEpoch}-${Random().nextInt(1 << 32)}';

  @override
  void initState() {
    super.initState();
    final c = widget.channel;
    if (c != null) {
      _category = c['category'] ?? _category;
      _style = c['style'] ?? _style;
      _lang = c['language'] ?? _lang;
      _aspect = c['aspect_ratio'] ?? _aspect;
      _res = c['resolution'] ?? _res;
      _duration = (c['duration'] ?? 30).toDouble();
      _tier = c['quality_tier'] ?? _tier;
      _mode = c['media_mode'] ?? _mode;
      _platforms
        ..clear()
        ..addAll(((c['platforms'] ?? ['youtube']) as List).cast<String>());
      final v = (c['voice'] ?? {}) as Map;
      _gender = v['gender'] ?? _gender;
      _emotion = v['emotion'] ?? _emotion;
      _speed = (v['speed'] ?? 1.0).toDouble();
    }
    if (!categories.contains(_category)) {
      _custom = true;
      _customCat.text = _category;
    }
  }

  Map<String, dynamic> _body() => {
        'topic': _topic.text.trim(),
        'category': _custom ? _customCat.text.trim() : _category,
        'language': _lang,
        'style': _style,
        'aspect_ratio': _aspect,
        'resolution': _res,
        'duration': _duration.round(),
        'quality_tier': _tier,
        'media_mode': _mode,
        'voice': {'gender': _gender, 'emotion': _emotion, 'speed': double.parse(_speed.toStringAsFixed(2))},
        'options': {'subtitles': _subs, 'music': _music, 'privacy': _privacy},
        'platforms': _platforms.toList(),
        'publish_mode': _publishMode,
        if (widget.channel != null) 'channel_id': widget.channel!['id'],
        if (widget.ideaId != null) 'idea_id': widget.ideaId,
      };

  Future<void> _estimateCost() async {
    if (!_form.currentState!.validate()) return;
    setState(() => _busy = true);
    try {
      final e = await ref.read(apiProvider).post('/api/v1/projects/estimate', body: _body()) as Map;
      setState(() => _estimate = e);
    } catch (e) {
      if (mounted) toast(context, '$e', error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _start() async {
    if (!_form.currentState!.validate()) return;
    if (_platforms.isEmpty && _publishMode == 'auto') {
      toast(context, 'Otomatik yayın için en az bir platform seçin', error: true);
      return;
    }
    setState(() => _busy = true);
    try {
      final r = await ref.read(apiProvider).post('/api/v1/projects', body: _body(), headers: {'Idempotency-Key': _idem}) as Map;
      ref.read(tickProvider.notifier).bump();
      if (!mounted) return;
      Navigator.push(context, MaterialPageRoute(builder: (_) => ProjectDetailScreen(id: r['project']['id'])));
      toast(context, 'Üretim kuyruğa alındı — uygulamayı kapatsanız bile bulutta devam eder');
    } catch (e) {
      if (mounted) toast(context, '$e', error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Widget _choice<T>(String label, T value, List<(T, String)> items, void Function(T) on, {String? help}) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Padding(padding: const EdgeInsets.only(top: 14, bottom: 6), child: Text(label, style: const TextStyle(fontSize: 12.5, color: AppColors.muted))),
        Wrap(spacing: 8, runSpacing: 4, children: [
          for (final it in items) ChoiceChip(label: Text(it.$2), selected: value == it.$1, onSelected: (_) => setState(() {
                on(it.$1);
                _estimate = null;
              })),
        ]),
        if (help != null) Padding(padding: const EdgeInsets.only(top: 4), child: Text(help, style: const TextStyle(fontSize: 11, color: AppColors.muted))),
      ]);

  @override
  Widget build(BuildContext context) {
    return Form(
      key: _form,
      child: ListView(padding: const EdgeInsets.fromLTRB(14, 4, 14, 30), children: [
        TextFormField(
          controller: _topic,
          minLines: 2,
          maxLines: 3,
          maxLength: 300,
          decoration: const InputDecoration(labelText: 'Video konusu', hintText: 'Örn. Güneş sistemindeki en büyük 5 gezegen'),
          validator: (v) => (v == null || v.trim().length < 3) ? 'En az 3 karakter' : null,
        ),
        Row(children: [
          Expanded(
            child: _custom
                ? TextFormField(controller: _customCat, decoration: const InputDecoration(labelText: 'Özel kategori'), validator: (v) => (v == null || v.trim().isEmpty) ? 'Kategori girin' : null)
                : DropdownButtonFormField<String>(
                    initialValue: categories.contains(_category) ? _category : categories.first,
                    decoration: const InputDecoration(labelText: 'Kategori'),
                    items: [for (final c in categories) DropdownMenuItem(value: c, child: Text(c))],
                    onChanged: (v) => setState(() => _category = v!),
                  ),
          ),
          const SizedBox(width: 8),
          FilterChip(label: const Text('Özel'), selected: _custom, onSelected: (v) => setState(() => _custom = v)),
        ]),
        const SizedBox(height: 14),
        Text('Süre: ${_duration.round()} sn', style: const TextStyle(fontSize: 12.5, color: AppColors.muted)),
        Slider(value: _duration, min: 10, max: 90, divisions: 16, label: '${_duration.round()} sn', onChanged: (v) => setState(() {
              _duration = v;
              _estimate = null;
            })),
        _choice('Görsel stil', _style, const [('cinematic', 'Sinematik'), ('documentary', 'Belgesel'), ('energetic', 'Enerjik'), ('minimal', 'Minimal'), ('anime', 'Anime'), ('3d', '3D')], (v) => _style = v),
        _choice('Dil', _lang, const [('tr', 'Türkçe'), ('en', 'English')], (v) => _lang = v),
        _choice('Seslendirme', _gender, const [('female', 'Kadın'), ('male', 'Erkek')], (v) => _gender = v),
        _choice('Duygu / ton', _emotion, const [('neutral', 'Nötr'), ('excited', 'Heyecanlı'), ('calm', 'Sakin'), ('serious', 'Ciddi'), ('warm', 'Sıcak'), ('dramatic', 'Dramatik')], (v) => _emotion = v),
        Text('Konuşma hızı: ${_speed.toStringAsFixed(2)}x', style: const TextStyle(fontSize: 12.5, color: AppColors.muted)),
        Slider(value: _speed, min: 0.8, max: 1.25, divisions: 9, onChanged: (v) => setState(() => _speed = v)),
        _choice('Video formatı', _aspect, const [('9:16', '9:16 Dikey'), ('16:9', '16:9 Yatay'), ('1:1', '1:1 Kare')], (v) => _aspect = v),
        _choice('Çözünürlük', _res, const [('720p', '720p'), ('1080p', '1080p')], (v) => _res = v),
        _choice('Üretim kalitesi', _tier, const [('draft', 'Taslak'), ('standard', 'Standart'), ('premium', 'Premium')], (v) => _tier = v, help: 'Taslak: hızlı/ucuz (yalnızca görsel+hareket). Premium: yüksek kalite render.'),
        _choice('Medya modu', _mode, const [('ai_video', 'Tam AI video'), ('hybrid', 'Hibrit'), ('slideshow', 'Görsel+hareket')], (v) => _mode = v,
            help: _mode == 'ai_video'
                ? 'Tüm sahneler için gerçek AI video sağlayıcısı gerekir; alınamazsa video "inceleme gerekli"ye düşer.'
                : _mode == 'hybrid'
                    ? 'Kanca sahneleri AI video, kalanı stok video veya AI görsel+hareket.'
                    : 'Sahne görselleri hareketlendirilir. Bu AI video DEĞİLDİR ve öyle raporlanmaz.'),
        const SizedBox(height: 14),
        const Text('Hedef platformlar', style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
        Wrap(spacing: 8, children: [
          for (final p in const [('youtube', 'YouTube Shorts'), ('tiktok', 'TikTok'), ('instagram', 'Instagram Reels')])
            FilterChip(label: Text(p.$2), selected: _platforms.contains(p.$1), onSelected: (v) => setState(() => v ? _platforms.add(p.$1) : _platforms.remove(p.$1))),
        ]),
        _choice('Yayın modu', _publishMode, const [('auto', 'Kalite eşiğine bağlı otomatik'), ('manual', 'Her zaman benim onayım')], (v) => _publishMode = v),
        _choice('Yayın görünürlüğü', _privacy, const [('public', 'Herkese açık'), ('unlisted', 'Liste dışı'), ('private', 'Özel')], (v) => _privacy = v),
        SwitchListTile(contentPadding: EdgeInsets.zero, title: const Text('Altyazı (kelime vurgulu)'), value: _subs, onChanged: (v) => setState(() => _subs = v)),
        SwitchListTile(contentPadding: EdgeInsets.zero, title: const Text('Arka plan müziği'), subtitle: const Text('Lisanslı kütüphaneniz yoksa sistemde sentezlenen telifsiz müzik'), value: _music, onChanged: (v) => setState(() => _music = v)),
        if (_estimate != null) _EstimateCard(_estimate!),
        const SizedBox(height: 10),
        Row(children: [
          Expanded(child: OutlinedButton.icon(onPressed: _busy ? null : _estimateCost, icon: const Icon(Icons.calculate_outlined), label: const Text('Maliyet tahmini'))),
          const SizedBox(width: 10),
          Expanded(
              flex: 2,
              child: FilledButton.icon(
                onPressed: _busy ? null : _start,
                icon: _busy ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.play_arrow_rounded),
                label: const Text('Üretimi başlat'),
                style: FilledButton.styleFrom(padding: const EdgeInsets.symmetric(vertical: 15)),
              )),
        ]),
      ]),
    );
  }
}

class _EstimateCard extends StatelessWidget {
  const _EstimateCard(this.e);
  final Map e;
  @override
  Widget build(BuildContext context) => Card(
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              const Expanded(child: Text('Tahmini maliyet', style: TextStyle(fontWeight: FontWeight.w800))),
              Text(usd(e['total_usd'] as num), style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800, color: AppColors.amber)),
            ]),
            const Divider(),
            for (final i in (e['items'] as List).cast<Map>())
              Padding(padding: const EdgeInsets.symmetric(vertical: 2), child: Row(children: [
                Expanded(child: Text('${i['label']} · ${i['provider']}', style: const TextStyle(fontSize: 12))),
                Text(usd(i['usd'] as num, d: 3), style: const TextStyle(fontSize: 12)),
              ])),
            for (final w in (e['warnings'] as List)) Padding(padding: const EdgeInsets.only(top: 6), child: Text('⚠ $w', style: const TextStyle(color: AppColors.amber, fontSize: 11.5))),
            Padding(padding: const EdgeInsets.only(top: 6), child: Text(e['note'], style: const TextStyle(color: AppColors.muted, fontSize: 10.5))),
          ]),
        ),
      );
}
