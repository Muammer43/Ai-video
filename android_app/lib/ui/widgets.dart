import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

import '../core/api_core.dart';
import '../core/format.dart';
import 'theme.dart';

/// AsyncValue için tek tip yükleme / hata / boş durum gösterimi.
class AsyncView<T> extends StatelessWidget {
  const AsyncView({super.key, required this.value, required this.builder, this.onRetry, this.isEmpty, this.emptyText = 'Henüz kayıt yok', this.emptyIcon = Icons.inbox_outlined});
  final AsyncValue<T> value;
  final Widget Function(T data) builder;
  final VoidCallback? onRetry;
  final bool Function(T data)? isEmpty;
  final String emptyText;
  final IconData emptyIcon;

  @override
  Widget build(BuildContext context) {
    return value.when(
      skipLoadingOnRefresh: true,
      loading: () => const Center(child: Padding(padding: EdgeInsets.all(40), child: CircularProgressIndicator())),
      error: (e, _) => ErrorState(message: e.toString(), onRetry: onRetry),
      data: (d) => (isEmpty?.call(d) ?? false) ? EmptyState(icon: emptyIcon, text: emptyText) : builder(d),
    );
  }
}

class ErrorState extends StatelessWidget {
  const ErrorState({super.key, required this.message, this.onRetry});
  final String message;
  final VoidCallback? onRetry;
  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(28),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            const Icon(Icons.cloud_off_rounded, size: 44, color: AppColors.red),
            const SizedBox(height: 12),
            Text(message, textAlign: TextAlign.center, style: const TextStyle(color: AppColors.muted)),
            if (onRetry != null) ...[const SizedBox(height: 14), FilledButton.tonal(onPressed: onRetry, child: const Text('Tekrar dene'))],
          ]),
        ),
      );
}

class EmptyState extends StatelessWidget {
  const EmptyState({super.key, required this.text, this.icon = Icons.inbox_outlined, this.action});
  final String text;
  final IconData icon;
  final Widget? action;
  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(36),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Icon(icon, size: 48, color: AppColors.muted),
            const SizedBox(height: 10),
            Text(text, textAlign: TextAlign.center, style: const TextStyle(color: AppColors.muted)),
            if (action != null) ...[const SizedBox(height: 14), action!],
          ]),
        ),
      );
}

class StatusChip extends StatelessWidget {
  const StatusChip(this.status, {super.key});
  final String status;
  @override
  Widget build(BuildContext context) {
    final c = statusColor(status);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
      decoration: BoxDecoration(color: c.withValues(alpha: 0.16), borderRadius: BorderRadius.circular(20), border: Border.all(color: c.withValues(alpha: 0.5))),
      child: Text(statusLabel(status), style: TextStyle(color: c, fontSize: 11, fontWeight: FontWeight.w700)),
    );
  }
}

class Badge2 extends StatelessWidget {
  const Badge2(this.text, {super.key, this.color = AppColors.muted});
  final String text;
  final Color color;
  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
        decoration: BoxDecoration(color: color.withValues(alpha: 0.15), borderRadius: BorderRadius.circular(8)),
        child: Text(text, style: TextStyle(color: color, fontSize: 10.5, fontWeight: FontWeight.w600)),
      );
}

class StatTile extends StatelessWidget {
  const StatTile({super.key, required this.label, required this.value, this.icon, this.color = AppColors.accent, this.hint});
  final String label;
  final String value;
  final IconData? icon;
  final Color color;
  final String? hint;
  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(13),
        decoration: BoxDecoration(
          gradient: const LinearGradient(colors: [AppColors.panel2, AppColors.panel], begin: Alignment.topLeft, end: Alignment.bottomRight),
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: AppColors.line),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
          Row(children: [
            if (icon != null) Icon(icon, size: 15, color: color),
            if (icon != null) const SizedBox(width: 6),
            Expanded(child: Text(label, style: const TextStyle(color: AppColors.muted, fontSize: 11.5), overflow: TextOverflow.ellipsis)),
          ]),
          Text(value, style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w800)),
          if (hint != null) Text(hint!, style: const TextStyle(color: AppColors.muted, fontSize: 10)),
        ]),
      );
}

class SectionTitle extends StatelessWidget {
  const SectionTitle(this.text, {super.key, this.trailing});
  final String text;
  final Widget? trailing;
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(4, 18, 4, 6),
        child: Row(children: [
          Expanded(child: Text(text, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700))),
          if (trailing != null) trailing!,
        ]),
      );
}

class Meter extends StatelessWidget {
  const Meter({super.key, required this.label, required this.value, required this.max, this.color});
  final String label;
  final double value, max;
  final Color? color;
  @override
  Widget build(BuildContext context) {
    final f = max <= 0 ? 0.0 : (value / max).clamp(0.0, 1.0);
    final c = color ?? (f > 0.9 ? AppColors.red : f > 0.7 ? AppColors.amber : AppColors.green);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
        Text(label, style: const TextStyle(fontSize: 12, color: AppColors.muted)),
        Text('${usd(value)} / ${usd(max)}', style: const TextStyle(fontSize: 12)),
      ]),
      const SizedBox(height: 5),
      ClipRRect(borderRadius: BorderRadius.circular(6), child: LinearProgressIndicator(value: f, minHeight: 7, color: c, backgroundColor: AppColors.line)),
    ]);
  }
}

/// Üretim hattı adım göstergesi (TOPIC → … → PUBLISH).
class PipelineBar extends StatelessWidget {
  const PipelineBar({super.key, required this.stage, required this.status});
  final String stage, status;
  @override
  Widget build(BuildContext context) {
    final idx = stages.indexOf(stage == 'RESEARCH' || stage == 'IDEA' ? 'TOPIC' : stage);
    final done = {'APPROVED', 'PUBLISHING', 'PUBLISHED', 'NEEDS_REVIEW'}.contains(status);
    return Wrap(spacing: 6, runSpacing: 6, children: [
      for (var i = 0; i < stages.length; i++)
        Builder(builder: (_) {
          final isDone = done ? i <= stages.indexOf('QC') : i < idx;
          final isCur = !done && i == idx && activeStatuses.contains(status);
          final c = status == 'FAILED' && i == idx ? AppColors.red : isDone ? AppColors.green : isCur ? AppColors.accent : AppColors.muted;
          return Container(
            padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
            decoration: BoxDecoration(color: c.withValues(alpha: isCur ? 0.25 : 0.12), borderRadius: BorderRadius.circular(14), border: Border.all(color: c.withValues(alpha: 0.5))),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              if (isCur) const SizedBox(width: 10, height: 10, child: CircularProgressIndicator(strokeWidth: 2)) else Icon(isDone ? Icons.check_circle : Icons.circle_outlined, size: 12, color: c),
              const SizedBox(width: 5),
              Text(stageLabels[stages[i]]!, style: TextStyle(fontSize: 11, color: c, fontWeight: FontWeight.w600)),
            ]),
          );
        }),
    ]);
  }
}

void toast(BuildContext c, String msg, {bool error = false}) {
  ScaffoldMessenger.of(c)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(msg), backgroundColor: error ? const Color(0xFF7A2B2B) : AppColors.panel2, duration: Duration(seconds: error ? 5 : 3)));
}

/// İşlemi çalıştırır, hatayı gösterir. true dönerse başarılı.
Future<bool> run(BuildContext c, Future<dynamic> Function() fn, {String? ok}) async {
  try {
    await fn();
    if (ok != null && c.mounted) toast(c, ok);
    return true;
  } on ApiException catch (e) {
    if (c.mounted) toast(c, e.message, error: true);
  } catch (e) {
    if (c.mounted) toast(c, 'Beklenmeyen hata: $e', error: true);
  }
  return false;
}

Future<bool> confirm(BuildContext c, String title, String body, {String ok = 'Evet'}) async {
  final r = await showDialog<bool>(
    context: c,
    builder: (_) => AlertDialog(
      title: Text(title),
      content: Text(body),
      actions: [TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Vazgeç')), FilledButton(onPressed: () => Navigator.pop(c, true), child: Text(ok))],
    ),
  );
  return r ?? false;
}

class Kv extends StatelessWidget {
  const Kv(this.k, this.v, {super.key});
  final String k;
  final String v;
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(width: 110, child: Text(k, style: const TextStyle(color: AppColors.muted, fontSize: 12))),
          Expanded(child: Text(v, style: const TextStyle(fontSize: 12.5))),
        ]),
      );
}
