import 'package:material_ui/material_ui.dart';

class AppColors {
  static const bg = Color(0xFF0B1120);
  static const panel = Color(0xFF121D30);
  static const panel2 = Color(0xFF17243A);
  static const line = Color(0xFF26364D);
  static const muted = Color(0xFF9AABC2);
  static const accent = Color(0xFF7C9CFF);
  static const accent2 = Color(0xFFA17CFF);
  static const green = Color(0xFF36D399);
  static const amber = Color(0xFFF5B84B);
  static const red = Color(0xFFF87272);
  static const blue = Color(0xFF5BC0F8);
}

Color statusColor(String s) {
  switch (s) {
    case 'PUBLISHED':
    case 'APPROVED':
      return AppColors.green;
    case 'NEEDS_REVIEW':
      return AppColors.amber;
    case 'FAILED':
      return AppColors.red;
    case 'CANCELLED':
      return AppColors.muted;
    case 'QUEUED':
      return AppColors.blue;
    default:
      return AppColors.accent;
  }
}

ThemeData buildTheme() {
  final scheme = ColorScheme.fromSeed(seedColor: AppColors.accent, brightness: Brightness.dark).copyWith(
    surface: AppColors.bg,
    primary: AppColors.accent,
    secondary: AppColors.accent2,
    error: AppColors.red,
  );
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: AppColors.bg,
    appBarTheme: const AppBarTheme(backgroundColor: AppColors.bg, elevation: 0, centerTitle: false, scrolledUnderElevation: 0),
    cardTheme: CardThemeData(
      color: AppColors.panel,
      elevation: 0,
      margin: const EdgeInsets.symmetric(vertical: 6),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16), side: const BorderSide(color: AppColors.line)),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: const Color(0xFF0C1525),
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: const BorderSide(color: AppColors.line)),
      enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: const BorderSide(color: AppColors.line)),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: AppColors.panel,
      indicatorColor: AppColors.accent.withValues(alpha: 0.25),
      labelTextStyle: WidgetStatePropertyAll(const TextStyle(fontSize: 11)),
    ),
    drawerTheme: const DrawerThemeData(backgroundColor: AppColors.panel),
    dividerColor: AppColors.line,
    chipTheme: ChipThemeData(
      backgroundColor: AppColors.panel2,
      side: const BorderSide(color: AppColors.line),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
    ),
    snackBarTheme: const SnackBarThemeData(behavior: SnackBarBehavior.floating),
  );
}
