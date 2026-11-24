import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:material_ui/material_ui.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'core/state.dart';
import 'features/login.dart';
import 'features/shell.dart';
import 'ui/locale.dart';
import 'ui/theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await initializeDateFormatting('tr');
  SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(statusBarColor: Colors.transparent, statusBarIconBrightness: Brightness.light));
  final prefs = await SharedPreferences.getInstance();
  runApp(ProviderScope(overrides: [prefsProvider.overrideWithValue(prefs)], child: const App()));
}

class App extends ConsumerStatefulWidget {
  const App({super.key});
  @override
  ConsumerState<App> createState() => _AppState();
}

class _AppState extends ConsumerState<App> {
  @override
  void initState() {
    super.initState();
    Future.microtask(() => ref.read(sessionProvider.notifier).init());
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(sessionProvider);
    return MaterialApp(
      title: 'AI Video Factory Pro',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(),
      themeMode: ThemeMode.dark,
      darkTheme: buildTheme(),
      locale: const Locale('tr'),
      supportedLocales: appSupportedLocales,
      localizationsDelegates: appLocalizationsDelegates,
      home: switch (s.status) {
        AuthStatus.loading => const Scaffold(body: Center(child: CircularProgressIndicator())),
        AuthStatus.loggedOut => const LoginScreen(),
        AuthStatus.loggedIn => const Shell(),
      },
    );
  }
}
