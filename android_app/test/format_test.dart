import 'package:ai_video_factory/core/format.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('durum etiketleri Türkçe', () {
    expect(statusLabel('NEEDS_REVIEW'), 'İnceleme gerekli');
    expect(statusLabel('PUBLISHED'), 'Yayınlandı');
    expect(statusLabel('X'), 'X');
    for (final s in ['QUEUED', 'PROCESSING', 'WAITING_PROVIDER', 'RENDERING', 'QUALITY_CHECK', 'APPROVED', 'NEEDS_REVIEW', 'PUBLISHING', 'PUBLISHED', 'FAILED', 'CANCELLED']) {
      expect(statusLabels.containsKey(s), true, reason: s);
    }
  });
  test('para ve yüzde biçimleri; veri yoksa uydurma değil çizgi', () {
    expect(usd(null), '—');
    expect(usd(1.5), '\$1.50');
    expect(usd(0.0123), '\$0.0123');
    expect(pct(null), '—');
    expect(pct(0.1234), '%12.3');
    expect(compact(null), '—');
  });
  test('kategoriler spesifikasyondaki listeyi içerir', () {
    for (final c in ['Oyun', 'GTA 6', 'Teknoloji', 'Yapay Zekâ', 'Otomobil', 'Bilim', 'Tarih', 'Bilgi', 'Eğlence', 'Finans', 'Seyahat', 'Eğitim', 'Hikâye', 'Belgesel']) {
      expect(categories, contains(c));
    }
  });
  test('tarih yardımcıları', () {
    expect(parseDt(null), isNull);
    expect(ago(DateTime.now().toUtc().toIso8601String()), 'şimdi');
  });
}
