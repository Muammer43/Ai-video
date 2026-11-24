import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

import '../core/format.dart';
import '../core/state.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';
import 'studio.dart';

class ChannelsScreen extends ConsumerWidget {
  const ChannelsScreen({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final list = ref.watch(channelsProvider);
    final api = ref.read(apiProvider);
    return Scaffold(
      body: AsyncView<List>(
        value: list,
        onRetry: () => ref.invalidate(channelsProvider),
        isEmpty: (l) => l.isEmpty,
        emptyText: 'Henüz içerik kanalı yok.\nBir niş için kanal oluşturup otomatik üretimi açın.',
        emptyIcon: Icons.hub_outlined,
        builder: (l) => ListView(padding: const EdgeInsets.fromLTRB(14, 0, 14, 90), children: [
          for (final c in l.cast<Map>())
            Card(
              child: Padding(
                padding: const EdgeInsets.all(14),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [
                    Expanded(child: Text(c['name'], style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16))),
                    Badge2(c['automation_enabled'] == true ? 'Otomasyon açık' : 'Manuel', color: c['automation_enabled'] == true ? AppColors.green : AppColors.muted),
                  ]),
                  const SizedBox(height: 6),
                  Text('${c['category']} · ${c['language']} · ${c['style']} · ${c['duration']} sn · ${c['aspect_ratio']} · ${c['media_mode']}', style: const TextStyle(color: AppColors.muted, fontSize: 12)),
                  Text('Platformlar: ${(c['platforms'] as List).join(', ')} · günde ${c['videos_per_day']} video · saatler (UTC): ${(c['posting_hours'] as List).isEmpty ? 'otomatik' : (c['posting_hours'] as List).join(', ')}', style: const TextStyle(color: AppColors.muted, fontSize: 12)),
                  Row(mainAxisAlignment: MainAxisAlignment.end, children: [
                    TextButton(onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => Scaffold(appBar: AppBar(title: Text('${c['name']} ile üret')), body: StudioScreen(channel: c)))), child: const Text('Video üret')),
                    TextButton(onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => ChannelForm(channel: c))), child: const Text('Düzenle')),
                    TextButton(
                      onPressed: () async {
                        if (await confirm(context, 'Kanalı sil', '${c['name']} silinsin mi? Mevcut projeler korunur.', ok: 'Sil')) {
                          if (!context.mounted) return;
                          await run(context, () => api.delete('/api/v1/channels/${c['id']}'), ok: 'Silindi');
                          ref.invalidate(channelsProvider);
                        }
                      },
                      child: const Text('Sil', style: TextStyle(color: AppColors.red)),
                    ),
                  ]),
                ]),
              ),
            ),
        ]),
      ),
      floatingActionButton: FloatingActionButton.extended(onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const ChannelForm())), icon: const Icon(Icons.add), label: const Text('Yeni kanal')),
    );
  }
}

class ChannelForm extends ConsumerStatefulWidget {
  const ChannelForm({super.key, this.channel});
  final Map? channel;
  @override
  ConsumerState<ChannelForm> createState() => _ChannelFormState();
}

class _ChannelFormState extends ConsumerState<ChannelForm> {
  final _form = GlobalKey<FormState>();
  late final _name = TextEditingController(text: widget.channel?['name'] ?? '');
  late final _intro = TextEditingController(text: widget.channel?['brand']?['intro_text'] ?? '');
  late final _outro = TextEditingController(text: widget.channel?['brand']?['outro_text'] ?? '');
  late String _cat = widget.channel?['category'] ?? 'Bilim';
  late String _lang = widget.channel?['language'] ?? 'tr';
  late String _style = widget.channel?['style'] ?? 'cinematic';
  late String _tier = widget.channel?['quality_tier'] ?? 'standard';
  late String _mode = widget.channel?['media_mode'] ?? 'hybrid';
  late String _gender = widget.channel?['voice']?['gender'] ?? 'female';
  late double _dur = (widget.channel?['duration'] ?? 30).toDouble();
  late int _perDay = widget.channel?['videos_per_day'] ?? 1;
  late bool _auto = widget.channel?['automation_enabled'] ?? false;
  late bool _autoPub = widget.channel?['auto_publish'] ?? true;
  late final Set<String> _plat = ((widget.channel?['platforms'] ?? ['youtube']) as List).cast<String>().toSet();
  late final Set<int> _hours = ((widget.channel?['posting_hours'] ?? <int>[]) as List).cast<int>().toSet();
  bool _busy = false;

  Future<void> _save() async {
    if (!_form.currentState!.validate()) return;
    setState(() => _busy = true);
    final brand = {if (_intro.text.trim().isNotEmpty) 'intro_text': _intro.text.trim(), if (_outro.text.trim().isNotEmpty) 'outro_text': _outro.text.trim()};
    final body = {
      'name': _name.text.trim(), 'category': _cat, 'language': _lang, 'style': _style, 'quality_tier': _tier, 'media_mode': _mode, 'duration': _dur.round(),
      'voice': {'gender': _gender}, 'platforms': _plat.toList(), 'automation_enabled': _auto, 'videos_per_day': _perDay, 'posting_hours': (_hours.toList()..sort()),
      'auto_publish': _autoPub, 'brand': brand,
    };
    final api = ref.read(apiProvider);
    final ok = await run(context, () => widget.channel == null ? api.post('/api/v1/channels', body: body) : api.put('/api/v1/channels/${widget.channel!['id']}', body: body), ok: 'Kanal kaydedildi');
    if (!mounted) return;
    setState(() => _busy = false);
    if (ok) {
      ref.invalidate(channelsProvider);
      Navigator.pop(context);
    }
  }

  Widget _dd(String label, String v, Map<String, String> items, void Function(String) on) => DropdownButtonFormField<String>(
        initialValue: v, decoration: InputDecoration(labelText: label), items: [for (final e in items.entries) DropdownMenuItem(value: e.key, child: Text(e.value))], onChanged: (x) => setState(() => on(x!)));

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.channel == null ? 'Yeni kanal' : 'Kanalı düzenle')),
      body: Form(
        key: _form,
        child: ListView(padding: const EdgeInsets.all(14), children: [
          TextFormField(controller: _name, decoration: const InputDecoration(labelText: 'Kanal adı'), validator: (v) => (v == null || v.trim().length < 2) ? 'En az 2 karakter' : null),
          const SizedBox(height: 12),
          _dd('Kategori / niş', categories.contains(_cat) ? _cat : categories.first, {for (final c in categories) c: c}, (v) => _cat = v),
          const SizedBox(height: 12),
          Row(children: [
            Expanded(child: _dd('Dil', _lang, const {'tr': 'Türkçe', 'en': 'English'}, (v) => _lang = v)),
            const SizedBox(width: 10),
            Expanded(child: _dd('Ses', _gender, const {'female': 'Kadın', 'male': 'Erkek'}, (v) => _gender = v)),
          ]),
          const SizedBox(height: 12),
          _dd('Görsel stil', _style, const {'cinematic': 'Sinematik', 'documentary': 'Belgesel', 'energetic': 'Enerjik', 'minimal': 'Minimal', 'anime': 'Anime', '3d': '3D'}, (v) => _style = v),
          const SizedBox(height: 12),
          _dd('Kalite', _tier, const {'draft': 'Taslak', 'standard': 'Standart', 'premium': 'Premium'}, (v) => _tier = v),
          const SizedBox(height: 12),
          _dd('Medya modu', _mode, const {'ai_video': 'Tam AI video', 'hybrid': 'Hibrit', 'slideshow': 'Görsel+hareket'}, (v) => _mode = v),
          Text('Süre: ${_dur.round()} sn', style: const TextStyle(color: AppColors.muted, fontSize: 12.5)),
          Slider(value: _dur, min: 10, max: 90, divisions: 16, onChanged: (v) => setState(() => _dur = v)),
          const Text('Platformlar', style: TextStyle(color: AppColors.muted, fontSize: 12.5)),
          Wrap(spacing: 8, children: [for (final p in const [('youtube', 'YouTube Shorts'), ('tiktok', 'TikTok'), ('instagram', 'Instagram Reels')]) FilterChip(label: Text(p.$2), selected: _plat.contains(p.$1), onSelected: (v) => setState(() => v ? _plat.add(p.$1) : _plat.remove(p.$1)))]),
          const SectionTitle('Otomasyon'),
          SwitchListTile(contentPadding: EdgeInsets.zero, title: const Text('Otomatik üretimi aç'), subtitle: const Text('Sistem fikir bulur, üretir, kalite kontrolünden geçirir'), value: _auto, onChanged: (v) => setState(() => _auto = v)),
          SwitchListTile(contentPadding: EdgeInsets.zero, title: const Text('Kalite eşiğine bağlı otomatik yayın'), subtitle: const Text('Kapalıysa her video onayınızı bekler'), value: _autoPub, onChanged: (v) => setState(() => _autoPub = v)),
          Row(children: [const Expanded(child: Text('Günlük video sayısı')), IconButton(onPressed: _perDay > 1 ? () => setState(() => _perDay--) : null, icon: const Icon(Icons.remove_circle_outline)), Text('$_perDay', style: const TextStyle(fontWeight: FontWeight.w800)), IconButton(onPressed: _perDay < 12 ? () => setState(() => _perDay++) : null, icon: const Icon(Icons.add_circle_outline))]),
          const Text('Yayın saatleri (UTC) — boşsa hemen yayınlanır', style: TextStyle(color: AppColors.muted, fontSize: 12)),
          Wrap(spacing: 6, runSpacing: 2, children: [for (var h = 0; h < 24; h += 1) FilterChip(visualDensity: VisualDensity.compact, label: Text(h.toString().padLeft(2, '0')), selected: _hours.contains(h), onSelected: (v) => setState(() => v ? _hours.add(h) : _hours.remove(h)))]),
          const SectionTitle('Marka'),
          TextFormField(controller: _intro, maxLength: 80, decoration: const InputDecoration(labelText: 'Intro metni (isteğe bağlı)')),
          TextFormField(controller: _outro, maxLength: 80, decoration: const InputDecoration(labelText: 'Outro / CTA metni (isteğe bağlı)')),
          const Text('Logo/filigran yüklemesi API üzerinden yapılır (POST /api/v1/channels/{id}/logo).', style: TextStyle(color: AppColors.muted, fontSize: 11)),
          const SizedBox(height: 16),
          FilledButton(onPressed: _busy ? null : _save, style: FilledButton.styleFrom(padding: const EdgeInsets.symmetric(vertical: 15)), child: _busy ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)) : const Text('Kaydet')),
        ]),
      ),
    );
  }
}
