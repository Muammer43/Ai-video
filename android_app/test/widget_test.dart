import 'package:ai_video_factory/core/api_core.dart';
import 'package:ai_video_factory/core/state.dart';
import 'package:ai_video_factory/features/dashboard.dart';
import 'package:ai_video_factory/features/login.dart';
import 'package:ai_video_factory/features/projects.dart';
import 'package:ai_video_factory/ui/theme.dart';
import 'package:ai_video_factory/ui/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:material_ui/material_ui.dart';
import 'package:shared_preferences/shared_preferences.dart';

Future<Widget> app(Widget child, {List overrides = const []}) async {
  SharedPreferences.setMockInitialValues({'base_url': 'http://10.0.2.2:8000'});
  final prefs = await SharedPreferences.getInstance();
  await initializeDateFormatting('tr');
  return ProviderScope(
    // ignore: argument_type_not_assignable
    overrides: [prefsProvider.overrideWithValue(prefs), tokenStoreProvider.overrideWithValue(MemoryTokenStore()), ...overrides.cast()],
    child: MaterialApp(theme: buildTheme(), home: Scaffold(body: child)),
  );
}

final fakeDash = {
  'videos_total': 12, 'videos_today': 3, 'queue': 2, 'in_progress': 1, 'completed': 7, 'failed': 1, 'needs_review': 2, 'ready_to_publish': 1,
  'published_videos': 0, 'total_views': null, 'engagement_rate': null, 'metrics_note': 'Henüz platform metriği toplanmadı', 'cost_today_usd': 0.42,
  'cost_month_usd': 3.1, 'avg_cost_per_video_usd': 0.08,
  'budget': {'spent_today_usd': 0.42, 'daily_usd': 5, 'spent_month_usd': 3.1, 'monthly_usd': 100, 'paused': false, 'paused_reason': ''},
  'providers': [
    {'name': 'openai', 'kind': 'llm', 'label': 'OpenAI', 'configured': false, 'is_ai': true, 'offline': false, 'calls': 0, 'success_rate': null, 'last_error': ''},
    {'name': 'template', 'kind': 'llm', 'label': 'Yerel şablon (AI değil)', 'configured': true, 'is_ai': false, 'offline': true, 'calls': 3, 'success_rate': 1.0, 'last_error': ''},
  ],
  'series': [for (var i = 0; i < 14; i++) {'date': '2026-11-${(i + 10).toString().padLeft(2, '0')}', 'produced': i % 4, 'published': i % 2}],
};

void main() {
  testWidgets('Giriş ekranı: doğrulama ve http uyarısı (dar telefon ekranı)', (t) async {
    t.view.physicalSize = const Size(360 * 2, 640 * 2);
    t.view.devicePixelRatio = 2;
    addTearDown(t.view.reset);
    await t.pumpWidget(await app(const LoginScreen()));
    expect(find.text('AI Video Factory Pro'), findsOneWidget);
    expect(find.textContaining('şifresiz'), findsOneWidget); // http:// uyarısı
    await t.tap(find.text('Giriş yap'));
    await t.pump();
    expect(find.text('Geçerli e-posta girin'), findsOneWidget);
    await t.tap(find.text('Yeni hesap oluştur'));
    await t.pump();
    expect(find.text('Hesap oluştur'), findsOneWidget);
  });

  testWidgets('Dashboard gerçek (sahte sağlayıcılı) veriyi gösterir, veri yoksa uydurma sayı göstermez', (t) async {
    await t.pumpWidget(await app(const DashboardScreen(), overrides: [
      dashboardProvider.overrideWith((ref) async => fakeDash),
      systemProvider.overrideWith((ref) async => {'ok': true, 'queue_mode': 'celery+redis', 'database': {'ok': true}, 'workers': {'ok': true, 'online': 2}, 'ffmpeg': {'ok': true}}),
    ]));
    await t.pumpAndSettle();
    expect(find.text('12'), findsOneWidget);
    expect(find.textContaining('Sistem çalışıyor'), findsOneWidget);
    expect(find.text('metrik yok'), findsNWidgets(2)); // izlenme/etkileşim: veri yok → '—'
    await t.scrollUntilVisible(find.text('AI değil'), 400, scrollable: find.byType(Scrollable).first);
    expect(find.text('AI değil'), findsOneWidget);
  });

  testWidgets('Projeler: liste, durum rozeti ve boş durum', (t) async {
    await t.pumpWidget(await app(const ProjectsScreen(), overrides: [
      projectsProvider.overrideWith((ref, f) async => {
            'total': 1,
            'items': [
              {'id': 'p1', 'topic': 'Uzay', 'title': 'Uzay Gerçekleri', 'category': 'Bilim', 'duration_target': 30, 'aspect_ratio': '9:16', 'created_at': DateTime.now().toIso8601String(), 'status': 'RENDERING', 'progress': 72, 'stage_message': 'Render', 'quality_score': null, 'cost_actual': 0.1, 'error': ''}
            ]
          }),
    ]));
    await t.pumpAndSettle();
    expect(find.text('Uzay Gerçekleri'), findsOneWidget);
    expect(find.text('Render ediliyor'), findsOneWidget);
    expect(find.textContaining('%72'), findsOneWidget);
  });

  testWidgets('AsyncView hata durumunda tekrar dene butonu çalışır', (t) async {
    var retried = false;
    await t.pumpWidget(await app(AsyncView<int>(value: AsyncValue.error('Sunucuya bağlanılamadı', StackTrace.empty), builder: (_) => const SizedBox(), onRetry: () => retried = true)));
    expect(find.text('Sunucuya bağlanılamadı'), findsOneWidget);
    await t.tap(find.text('Tekrar dene'));
    expect(retried, true);
  });

  testWidgets('PipelineBar ve StatusChip', (t) async {
    await t.pumpWidget(await app(const Column(children: [PipelineBar(stage: 'ASSETS', status: 'PROCESSING'), StatusChip('NEEDS_REVIEW')])));
    expect(find.text('Görsel/Video'), findsOneWidget);
    expect(find.text('İnceleme gerekli'), findsOneWidget);
  });
}
