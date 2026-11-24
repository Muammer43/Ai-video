import 'package:intl/intl.dart';

const statusLabels = {
  'QUEUED': 'Kuyrukta',
  'PROCESSING': 'İşleniyor',
  'WAITING_PROVIDER': 'Sağlayıcı bekleniyor',
  'RENDERING': 'Render ediliyor',
  'QUALITY_CHECK': 'Kalite kontrolü',
  'APPROVED': 'Onaylandı',
  'NEEDS_REVIEW': 'İnceleme gerekli',
  'PUBLISHING': 'Yayınlanıyor',
  'PUBLISHED': 'Yayınlandı',
  'FAILED': 'Başarısız',
  'CANCELLED': 'İptal edildi',
  'PROCESSING_OK': 'Tamam',
};

const activeStatuses = {'QUEUED', 'PROCESSING', 'WAITING_PROVIDER', 'RENDERING', 'QUALITY_CHECK'};
const stages = ['TOPIC', 'SCRIPT', 'STORYBOARD', 'VOICE', 'ASSETS', 'EDIT', 'QC', 'PUBLISH'];
const stageLabels = {
  'TOPIC': 'Konu', 'RESEARCH': 'Araştırma', 'IDEA': 'Fikir', 'SCRIPT': 'Senaryo', 'STORYBOARD': 'Storyboard', 'VOICE': 'Ses',
  'ASSETS': 'Görsel/Video', 'EDIT': 'Kurgu', 'QC': 'Kalite', 'PUBLISH': 'Yayın',
};
const originLabels = {
  'ai_video': 'AI video', 'ai_image_motion': 'AI görsel + hareket', 'stock': 'Stok video', 'slideshow': 'Slayt', 'procedural': 'Yer tutucu (AI değil)',
};
const kindLabels = {'llm': 'Metin (LLM)', 'image': 'Görsel', 'video': 'Video', 'tts': 'Seslendirme', 'stt': 'Altyazı zamanlama (STT)'};
const costKindLabels = {
  'llm': 'LLM', 'image': 'Görsel', 'video': 'Video', 'tts': 'Ses', 'stt': 'STT', 'server': 'Sunucu', 'storage': 'Depolama', 'publish': 'Yayın'
};
const categories = ['Oyun', 'GTA 6', 'Teknoloji', 'Yapay Zekâ', 'Otomobil', 'Bilim', 'Tarih', 'Bilgi', 'Eğlence', 'Finans', 'Seyahat', 'Eğitim', 'Hikâye', 'Belgesel'];

String statusLabel(String s) => statusLabels[s] ?? s;
String usd(num? v, {int d = 2}) => v == null ? '—' : '\$${v.toStringAsFixed(v.abs() < 0.1 && v != 0 ? 4 : d)}';
String pct(num? v, {int d = 1}) => v == null ? '—' : '%${(v * 100).toStringAsFixed(d)}';
String compact(num? v) => v == null ? '—' : NumberFormat.compact(locale: 'tr').format(v);

DateTime? parseDt(dynamic s) => s == null ? null : DateTime.tryParse(s.toString())?.toLocal();
String dt(dynamic s) {
  final d = parseDt(s);
  return d == null ? '—' : DateFormat('d MMM HH:mm', 'tr').format(d);
}

String ago(dynamic s) {
  final d = parseDt(s);
  if (d == null) return '—';
  final diff = DateTime.now().difference(d);
  if (diff.inSeconds < 60) return 'şimdi';
  if (diff.inMinutes < 60) return '${diff.inMinutes} dk önce';
  if (diff.inHours < 24) return '${diff.inHours} sa önce';
  return '${diff.inDays} gün önce';
}

String dayKey(dynamic s) {
  final d = parseDt(s);
  return d == null ? 'Zamanlanmamış' : DateFormat('d MMMM EEEE', 'tr').format(d);
}
