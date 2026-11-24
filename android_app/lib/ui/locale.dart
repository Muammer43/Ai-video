import 'package:flutter/widgets.dart';
import 'package:material_ui/material_ui.dart';

/// Türkçe (ve İngilizce) Material/Widgets/Cupertino yerelleştirmesi (material_ui'nin kendi temsilcileri).
/// Bunlar olmadan `locale: tr` zorlandığında TextField gibi bileşenler "No MaterialLocalizations found" ile çöker
/// ve release derlemede gri hata kutusu görünür.
final appLocalizationsDelegates = GlobalMaterialLocalizations.delegates;
const appSupportedLocales = [Locale('tr'), Locale('en')];
