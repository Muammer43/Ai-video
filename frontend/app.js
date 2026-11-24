'use strict';
const $ = (id) => document.getElementById(id);
const API = '/api/v1';
const CATS = ['Oyun','GTA 6','Teknoloji','Yapay Zekâ','Otomobil','Bilim','Tarih','Bilgi','Eğlence','Finans','Seyahat','Eğitim','Hikâye','Belgesel'];
const ST = {QUEUED:'Kuyrukta',PROCESSING:'İşleniyor',WAITING_PROVIDER:'Sağlayıcı bekleniyor',RENDERING:'Render',QUALITY_CHECK:'Kalite kontrolü',APPROVED:'Onaylandı',NEEDS_REVIEW:'İnceleme gerekli',PUBLISHING:'Yayınlanıyor',PUBLISHED:'Yayınlandı',FAILED:'Başarısız',CANCELLED:'İptal'};
const ACTIVE = new Set(['QUEUED','PROCESSING','WAITING_PROVIDER','RENDERING','QUALITY_CHECK']);
let tokens = JSON.parse(sessionStorage.getItem('aivf_tokens') || 'null');
const esc = (s = '') => String(s).replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

async function api(path, opts = {}, retry = true) {
  const h = {'Content-Type': 'application/json', ...(opts.headers || {})};
  if (tokens) h.Authorization = 'Bearer ' + tokens.access_token;
  const r = await fetch(API + path, {...opts, headers: h});
  if (r.status === 401 && tokens && retry && path !== '/auth/refresh') {
    const rr = await fetch(API + '/auth/refresh', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({refresh_token: tokens.refresh_token})});
    if (rr.ok) { saveTokens(await rr.json()); return api(path, opts, false); }
    logout(); throw new Error('Oturum süresi doldu');
  }
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error?.message || ('Hata ' + r.status));
  return d;
}
function saveTokens(t) { tokens = t; sessionStorage.setItem('aivf_tokens', JSON.stringify(t)); }
function logout() { tokens = null; sessionStorage.removeItem('aivf_tokens'); show(); }
function show() { $('login').hidden = !!tokens; $('app').hidden = !tokens; if (tokens) boot(); }

async function auth(path) {
  $('loginMsg').textContent = '';
  try { saveTokens(await api(path, {method: 'POST', body: JSON.stringify({email: $('email').value, password: $('password').value})}, false)); show(); }
  catch (e) { $('loginMsg').textContent = e.message; }
}
$('loginForm').addEventListener('submit', (e) => { e.preventDefault(); auth('/auth/login'); });
$('regBtn').addEventListener('click', () => auth('/auth/register'));
$('logout').addEventListener('click', async () => { try { await api('/auth/logout', {method: 'POST', body: JSON.stringify({refresh_token: tokens.refresh_token})}); } catch (_) {} logout(); });

function body() {
  return {topic: $('topic').value.trim(), category: $('category').value, duration: +$('duration').value, style: $('style').value, media_mode: $('mode').value,
    quality_tier: $('tier').value, voice: {gender: $('gender').value}, platforms: [...document.querySelectorAll('.checks input:checked')].map((x) => x.value)};
}
$('estBtn').addEventListener('click', async () => {
  try { const e = await api('/projects/estimate', {method: 'POST', body: JSON.stringify(body())});
    $('estimate').textContent = 'Tahmini maliyet: $' + e.total_usd.toFixed(3) + '\n' + e.items.map((i) => `• ${i.label} (${i.provider}): $${i.usd.toFixed(4)}`).join('\n') + (e.warnings.length ? '\n⚠ ' + e.warnings.join('\n⚠ ') : '');
  } catch (e) { $('estimate').textContent = e.message; }
});
$('createForm').addEventListener('submit', async (e) => {
  e.preventDefault(); const b = $('createBtn'); b.disabled = true;
  try { const r = await api('/projects', {method: 'POST', body: JSON.stringify(body()), headers: {'Idempotency-Key': crypto.randomUUID()}}); $('topic').value = ''; await loadJobs(); showDetail(r.project.id); }
  catch (err) { alert(err.message); } finally { b.disabled = false; }
});

async function boot() {
  $('category').innerHTML = CATS.map((c) => `<option>${esc(c)}</option>`).join('');
  loadAll(); clearInterval(window._t); window._t = setInterval(loadAll, 8000);
}
async function loadAll() { try { await Promise.all([loadStats(), loadJobs()]); } catch (_) {} }
async function loadStats() {
  const d = await api('/dashboard'); const s = await api('/system/status').catch(() => null);
  $('sys').textContent = s ? (s.ok ? '● Sistem çalışıyor' : '● Dikkat') : '● bilinmiyor'; $('sys').className = 'pill ' + (s && s.ok ? 'ok' : 'warn');
  const t = (l, v, h = '') => `<div class="stat"><span class="muted small">${l}</span><b>${esc(v)}</b><span class="muted small">${h}</span></div>`;
  $('stats').innerHTML = t('Toplam video', d.videos_total) + t('Kuyruk / işleniyor', d.queue + ' / ' + d.in_progress) + t('İnceleme bekleyen', d.needs_review) + t('Yayınlanan (doğrulanmış)', d.published_videos)
    + t('Başarısız', d.failed) + t('Yayına hazır', d.ready_to_publish) + t('Bugünkü maliyet', '$' + d.cost_today_usd.toFixed(3), `limit $${d.budget.daily_usd}`) + t('Toplam izlenme', d.total_views ?? '—', d.total_views == null ? 'metrik yok' : '');
  $('providers').innerHTML = d.providers.map((p) => `<div>${p.configured ? '●' : '○'} ${esc(p.kind)} · ${esc(p.label)} ${p.is_ai ? '' : '<span class="pill warn">AI değil</span>'} <span class="muted">${p.configured ? '' : '(yapılandırılmamış)'}</span></div>`).join('');
}
async function loadJobs() {
  const d = await api('/projects?limit=30');
  $('jobs').innerHTML = d.items.length ? d.items.map((j) => `<div class="job"><div class="top"><b>${esc(j.title || j.topic)}</b><span class="pill">${esc(ST[j.status] || j.status)}</span></div>
    ${ACTIVE.has(j.status) ? `<div class="bar"><span style="width:${j.progress}%"></span></div><div class="small muted">${esc(j.stage_message)} · %${j.progress}</div>` : `<div class="small muted">Kalite: ${j.quality_score ?? '—'} · Maliyet $${j.cost_actual.toFixed(3)}</div>`}
    <div class="actions"><button class="secondary small" data-id="${j.id}" data-act="open">Detay</button></div></div>`).join('') : '<p class="muted">Henüz proje yok.</p>';
  document.querySelectorAll('[data-act=open]').forEach((b) => b.addEventListener('click', () => showDetail(b.dataset.id)));
}
$('refresh').addEventListener('click', loadAll);

let es = null;
async function showDetail(id) {
  const p = await api('/projects/' + id); const el = $('detail'); el.hidden = false;
  const qr = p.quality_report || {}; const crit = qr.critical || [];
  let media = ''; if (p.has_video) { const m = await api(`/projects/${id}/media`); media = `<video controls playsinline src="${m.video.path}"></video>`; }
  el.innerHTML = `<h2>${esc(p.title || p.topic)}</h2><p><span class="pill">${esc(ST[p.status] || p.status)}</span> <span class="muted small">${esc(p.stage_message)} %${p.progress}</span></p>
   ${p.error ? `<p class="bad">${esc(p.error_code)}: ${esc(p.error)}</p>` : ''}${media}
   ${qr.checks ? `<h3>Kalite ${p.quality_score}/100 — ${esc(qr.decision)}</h3>` + qr.reasons.map((r) => `<div class="warn small">• ${esc(r)}</div>`).join('') + qr.checks.map((c) => `<div class="small ${c.status === 'pass' ? 'ok' : c.status === 'warn' ? 'warn' : 'bad'}">${c.status === 'pass' ? '✔' : c.status === 'warn' ? '⚠' : '✘'} ${esc(c.name)} — <span class="muted">${esc(c.detail)}</span></div>`).join('') : ''}
   ${(p.media_report && p.media_report.counts) ? '<p class="small muted">Medya kökeni: ' + Object.entries(p.media_report.counts).map(([k, v]) => `${esc(k)}×${v}`).join(', ') + '</p>' : ''}
   <div class="actions" id="acts"></div><pre id="log" class="small muted"></pre>`;
  const acts = $('acts'); const add = (t, f, cls = '') => { const b = document.createElement('button'); b.textContent = t; b.className = cls; b.addEventListener('click', async () => { try { const r = await f(); if (r && r.message) alert(r.message); } catch (e) { alert(e.message); } showDetail(id); loadAll(); }); acts.appendChild(b); };
  if (ACTIVE.has(p.status)) add('İptal et', () => api(`/projects/${id}/cancel`, {method: 'POST', body: '{}'}), 'secondary');
  if (['FAILED', 'CANCELLED', 'NEEDS_REVIEW'].includes(p.status)) add('Yeniden dene', () => api(`/projects/${id}/retry`, {method: 'POST', body: '{}'}), 'secondary');
  if (p.status === 'NEEDS_REVIEW') add('Onayla ve yayınla', () => { const ov = crit.length ? confirm('Kritik bulgular: ' + crit.join(', ') + '. Yine de yayınlansın mı?') : false; if (crit.length && !ov) throw new Error('Vazgeçildi'); return api(`/projects/${id}/approve`, {method: 'POST', body: JSON.stringify({override: ov})}); });
  if (!ACTIVE.has(p.status)) add('Sil', async () => { if (confirm('Silinsin mi?')) { await api('/projects/' + id, {method: 'DELETE'}); el.hidden = true; } }, 'secondary');
  if (es) es.abort(); es = new AbortController();
  if (ACTIVE.has(p.status)) streamEvents(id, es.signal);
  el.scrollIntoView({behavior: 'smooth'});
}
async function streamEvents(id, signal) {  // Authorization başlıklı SSE (URL'de token yok)
  try {
    const r = await fetch(`${API}/projects/${id}/stream`, {headers: {Authorization: 'Bearer ' + tokens.access_token}, signal});
    const rd = r.body.getReader(); const dec = new TextDecoder(); let buf = '';
    for (;;) { const {done, value} = await rd.read(); if (done) break; buf += dec.decode(value, {stream: true}); const parts = buf.split('\n\n'); buf = parts.pop();
      for (const p of parts) { const m = p.match(/^data: (.*)$/m); if (!m) continue; const e = JSON.parse(m[1]); if (p.includes('event: end')) { showDetail(id); return; }
        if (e.message) { const l = $('log'); if (l) l.textContent = `${e.created_at.slice(11, 19)} [${e.stage}] ${e.message}\n` + l.textContent; } } }
  } catch (_) {}
}
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
show();
