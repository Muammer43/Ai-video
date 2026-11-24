import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

import '../core/api_core.dart';
import '../core/state.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});
  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  late final _url = TextEditingController(text: ref.read(prefsProvider).getString('base_url') ?? 'http://10.0.2.2:8000');
  final _email = TextEditingController();
  final _pw = TextEditingController();
  final _name = TextEditingController();
  bool _register = false, _busy = false, _hide = true;
  String? _info;
  final _form = GlobalKey<FormState>();

  Future<void> _test() async {
    setState(() => _info = 'Bağlantı deneniyor…');
    try {
      final c = ApiClient(baseUrl: _url.text, tokens: MemoryTokenStore());
      final h = await c.health();
      setState(() => _info = '✅ Sunucu yanıt verdi (sürüm ${h['version']})');
    } on ApiException catch (e) {
      setState(() => _info = '❌ ${e.message}');
    }
  }

  Future<void> _submit() async {
    if (!_form.currentState!.validate()) return;
    setState(() => _busy = true);
    final ok = await run(context, () => ref.read(sessionProvider.notifier).authenticate(_url.text, _email.text.trim(), _pw.text, register: _register, name: _name.text));
    if (mounted && !ok) setState(() => _busy = false);
  }

  @override
  Widget build(BuildContext context) {
    final err = ref.watch(sessionProvider).error;
    final insecure = _url.text.trim().startsWith('http://');
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(22),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 440),
              child: Form(
                key: _form,
                child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  const SizedBox(height: 10),
                  Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(gradient: const LinearGradient(colors: [AppColors.accent, AppColors.accent2]), borderRadius: BorderRadius.circular(16)),
                      child: const Icon(Icons.movie_creation_rounded, color: Colors.white, size: 30),
                    ),
                    const SizedBox(width: 12),
                    const Flexible(child: Text('AI Video Factory Pro', maxLines: 2, style: TextStyle(fontSize: 21, fontWeight: FontWeight.w800))),
                  ]),
                  const SizedBox(height: 6),
                  const Text('Bulut üretim sunucunuza bağlanın', textAlign: TextAlign.center, style: TextStyle(color: AppColors.muted)),
                  const SizedBox(height: 22),
                  if (err != null) Padding(padding: const EdgeInsets.only(bottom: 10), child: Text(err, style: const TextStyle(color: AppColors.amber))),
                  TextFormField(
                    controller: _url,
                    keyboardType: TextInputType.url,
                    decoration: const InputDecoration(labelText: 'Sunucu adresi', hintText: 'https://video.alanadiniz.com', prefixIcon: Icon(Icons.dns_outlined)),
                    validator: (v) => (v == null || !RegExp(r'^https?://').hasMatch(v.trim())) ? 'http(s):// ile başlayan adres girin' : null,
                    onChanged: (_) => setState(() {}),
                  ),
                  if (insecure)
                    const Padding(
                      padding: EdgeInsets.only(top: 6),
                      child: Text('⚠ http:// şifresiz bağlantıdır. Yalnızca yerel ağ/test için kullanın; internet üzerinden HTTPS kullanın.', style: TextStyle(color: AppColors.amber, fontSize: 11.5)),
                    ),
                  Align(alignment: Alignment.centerLeft, child: TextButton.icon(onPressed: _test, icon: const Icon(Icons.network_check, size: 18), label: const Text('Bağlantıyı sına'))),
                  if (_info != null) Padding(padding: const EdgeInsets.only(bottom: 8), child: Text(_info!, style: const TextStyle(fontSize: 12.5))),
                  if (_register) ...[
                    TextFormField(controller: _name, decoration: const InputDecoration(labelText: 'Ad', prefixIcon: Icon(Icons.person_outline))),
                    const SizedBox(height: 12),
                  ],
                  TextFormField(
                    controller: _email,
                    keyboardType: TextInputType.emailAddress,
                    autofillHints: const [AutofillHints.email],
                    decoration: const InputDecoration(labelText: 'E-posta', prefixIcon: Icon(Icons.alternate_email)),
                    validator: (v) => (v == null || !v.contains('@')) ? 'Geçerli e-posta girin' : null,
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: _pw,
                    obscureText: _hide,
                    autofillHints: const [AutofillHints.password],
                    decoration: InputDecoration(
                      labelText: 'Parola',
                      prefixIcon: const Icon(Icons.lock_outline),
                      suffixIcon: IconButton(icon: Icon(_hide ? Icons.visibility : Icons.visibility_off), onPressed: () => setState(() => _hide = !_hide)),
                      helperText: _register ? 'En az 10 karakter, harf ve rakam içermeli' : null,
                    ),
                    validator: (v) => (v == null || v.length < (_register ? 10 : 1)) ? (_register ? 'En az 10 karakter' : 'Parola girin') : null,
                  ),
                  const SizedBox(height: 18),
                  FilledButton(
                    onPressed: _busy ? null : _submit,
                    style: FilledButton.styleFrom(padding: const EdgeInsets.symmetric(vertical: 15)),
                    child: _busy ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2)) : Text(_register ? 'Hesap oluştur' : 'Giriş yap'),
                  ),
                  TextButton(onPressed: () => setState(() => _register = !_register), child: Text(_register ? 'Zaten hesabım var' : 'Yeni hesap oluştur')),
                ]),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
