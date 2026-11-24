import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

import '../core/format.dart';
import '../core/state.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';
import 'projects.dart';

class NotificationsScreen extends ConsumerWidget {
  const NotificationsScreen({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final n = ref.watch(notificationsProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Bildirimler'), actions: [
        TextButton(onPressed: () async { await run(context, () => ref.read(apiProvider).post('/api/v1/notifications/read')); ref.invalidate(notificationsProvider); }, child: const Text('Tümünü okundu yap')),
      ]),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(notificationsProvider),
        child: AsyncView<Map>(
          value: n,
          onRetry: () => ref.invalidate(notificationsProvider),
          isEmpty: (d) => (d['items'] as List).isEmpty,
          emptyText: 'Bildirim yok',
          emptyIcon: Icons.notifications_off_outlined,
          builder: (d) => ListView(padding: const EdgeInsets.all(14), children: [
            for (final i in (d['items'] as List).cast<Map>())
              Card(
                child: ListTile(
                  leading: Icon(i['level'] == 'error' ? Icons.error_outline : i['level'] == 'warning' ? Icons.warning_amber_rounded : Icons.info_outline, color: i['level'] == 'error' ? AppColors.red : i['level'] == 'warning' ? AppColors.amber : AppColors.accent),
                  title: Text(i['title'], style: TextStyle(fontWeight: i['read'] == true ? FontWeight.w500 : FontWeight.w800)),
                  subtitle: Text('${i['body']}\n${ago(i['created_at'])}', style: const TextStyle(fontSize: 11.5)),
                  isThreeLine: true,
                  onTap: () {
                    final pid = (i['data'] as Map)['project_id'];
                    if (pid != null) Navigator.push(context, MaterialPageRoute(builder: (_) => ProjectDetailScreen(id: pid)));
                  },
                ),
              ),
          ]),
        ),
      ),
    );
  }
}
