import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

import '../core/notify.dart';
import '../core/state.dart';
import '../ui/theme.dart';
import 'analytics.dart';
import 'automation.dart';
import 'calendar.dart';
import 'channels.dart';
import 'dashboard.dart';
import 'integrations.dart';
import 'models_screen.dart';
import 'notifications_screen.dart';
import 'projects.dart';
import 'settings.dart';
import 'studio.dart';

class _Dest {
  const _Dest(this.title, this.icon, this.builder);
  final String title;
  final IconData icon;
  final Widget Function() builder;
}

final _dests = <_Dest>[
  _Dest('Dashboard', Icons.dashboard_rounded, () => const DashboardScreen()),
  _Dest('AI Video Studio', Icons.auto_awesome_rounded, () => const StudioScreen()),
  _Dest('Otomatik Üretim', Icons.bolt_rounded, () => const AutomationScreen()),
  _Dest('Projeler', Icons.video_library_rounded, () => const ProjectsScreen()),
  _Dest('İçerik Kanalları', Icons.hub_rounded, () => const ChannelsScreen()),
  _Dest('Yayın Takvimi', Icons.calendar_month_rounded, () => const CalendarScreen()),
  _Dest('Analiz Merkezi', Icons.insights_rounded, () => const AnalyticsScreen()),
  _Dest('AI Modelleri', Icons.psychology_rounded, () => const ModelsScreen()),
  _Dest('Entegrasyonlar', Icons.link_rounded, () => const IntegrationsScreen()),
  _Dest('Ayarlar', Icons.settings_rounded, () => const SettingsScreen()),
];

/// Alt çubukta sık kullanılan 4 sayfa; "Daha fazla" çekmecesi 10 sayfanın tamamını listeler.
const _bottom = [0, 1, 3, 2];

class Shell extends ConsumerStatefulWidget {
  const Shell({super.key});
  @override
  ConsumerState<Shell> createState() => _ShellState();
}

class _ShellState extends ConsumerState<Shell> {
  int _index = 0;
  final _key = GlobalKey<ScaffoldState>();

  @override
  void initState() {
    super.initState();
    Future.microtask(() => ref.read(liveProvider).start());
  }

  void _go(int i) => setState(() => _index = i);

  @override
  Widget build(BuildContext context) {
    final unread = ref.watch(notificationsProvider).maybeWhen(data: (d) => (d['unread'] as int?) ?? 0, orElse: () => 0);
    final dest = _dests[_index];
    final bottomIdx = _bottom.indexOf(_index);
    return Scaffold(
      key: _key,
      appBar: AppBar(
        title: Text(dest.title, style: const TextStyle(fontWeight: FontWeight.w800)),
        leading: IconButton(icon: const Icon(Icons.menu_rounded), tooltip: 'Menü', onPressed: () => _key.currentState?.openDrawer()),
        actions: [
          IconButton(
            tooltip: 'Bildirimler',
            icon: Badge(isLabelVisible: unread > 0, label: Text('$unread'), child: const Icon(Icons.notifications_none_rounded)),
            onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const NotificationsScreen())),
          ),
        ],
      ),
      drawer: Drawer(
        child: SafeArea(
          child: ListView(children: [
            const Padding(
              padding: EdgeInsets.fromLTRB(20, 18, 20, 10),
              child: Text('AI Video Factory Pro', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
            ),
            for (var i = 0; i < _dests.length; i++)
              ListTile(
                leading: Icon(_dests[i].icon, color: i == _index ? AppColors.accent : AppColors.muted),
                title: Text(_dests[i].title, style: TextStyle(fontWeight: i == _index ? FontWeight.w800 : FontWeight.w500)),
                selected: i == _index,
                onTap: () {
                  Navigator.pop(context);
                  _go(i);
                },
              ),
          ]),
        ),
      ),
      body: KeyedSubtree(key: ValueKey(_index), child: dest.builder()),
      bottomNavigationBar: NavigationBar(
        selectedIndex: bottomIdx < 0 ? 4 : bottomIdx,
        onDestinationSelected: (i) => i == 4 ? _key.currentState?.openDrawer() : _go(_bottom[i]),
        destinations: [
          for (final i in _bottom) NavigationDestination(icon: Icon(_dests[i].icon), label: i == 1 ? 'Studio' : i == 2 ? 'Otomasyon' : _dests[i].title),
          const NavigationDestination(icon: Icon(Icons.apps_rounded), label: 'Daha fazla'),
        ],
      ),
    );
  }
}
