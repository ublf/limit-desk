'use strict';
const metadata = {claude:{name:'Claude Code',number:'01'},codex:{name:'Codex',number:'02'},gemini:{name:'Gemini',number:'03'}};
const $ = id => document.getElementById(id);
const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function timeLeft(reset, now) {
  const difference = new Date(reset).getTime() - now;
  if (!reset || !Number.isFinite(difference)) return {text:'—',valid:false};
  if (difference <= 0) return {text:'更新待ち',valid:false};
  const total = Math.ceil(difference / 60000);
  const days = Math.floor(total / 1440);
  const hours = Math.floor(total % 1440 / 60);
  const minutes = total % 60;
  return {text:days ? days + '日 ' + hours + '時間' : hours ? hours + '時間 ' + minutes + '分' : minutes + '分',valid:true,minutes:difference / 60000};
}
function paceData(item, now) {
  const left = timeLeft(item.reset, now);
  const duration = item.durationMinutes;
  if (!left.valid || !Number.isFinite(duration) || duration <= 0 || left.minutes > duration) return null;
  const time = left.minutes / duration * 100;
  const quota = 100 - item.used;
  const delta = quota - time;
  return {time:time,quota:quota,delta:delta,tone:delta < -5 ? 'fast' : delta > 5 ? 'spare' : 'even'};
}
function windowHtml(item, now) {
  const remaining = Math.round((100 - Math.max(0,Math.min(100,item.used))) * 10) / 10;
  const left = timeLeft(item.reset,now);
  const pace = paceData(item,now);
  let comparison = '<div class="pace-unknown">' + (left.valid ? '期間不明 · 時間との比較なし' : '時間との比較なし') + '</div>';
  if (pace) {
    const delta = Math.round(Math.abs(pace.delta));
    const text = pace.tone === 'fast' ? '時間に対して ' + delta + 'pt 使いすぎ' : pace.tone === 'spare' ? '時間に対して ' + delta + 'pt 余裕' : '時間とほぼ同じペース';
    comparison = '<div class="pace ' + pace.tone + '"><div class="bar-row"><span>残り枠</span><meter min="0" max="100" value="' + remaining + '" aria-label="残り枠 ' + remaining + '%">' + remaining + '%</meter><span>' + remaining + '%</span></div><div class="bar-row time-bar"><span>残り時間</span><meter min="0" max="100" value="' + pace.time.toFixed(2) + '" aria-label="残り時間 ' + Math.round(pace.time) + '%">' + Math.round(pace.time) + '%</meter><span>' + Math.round(pace.time) + '%</span></div><p class="pace-note">' + text + '</p></div>';
  }
  return '<section class="window"><h3>' + esc(item.label) + '</h3><div class="quota"><strong>' + remaining + '</strong><span>%</span><small>残り</small></div><div class="time"><span>リセットまで</span><strong>' + esc(left.text) + '</strong></div>' + comparison + '</section>';
}
let latest = [];
let initial = true;
function render(providers, loading) {
  const now = Date.now();
  $('cards').innerHTML = Object.keys(metadata).map(id => {
    const meta = metadata[id];
    const data = providers.find(p => p.id === id) || {windows:[]};
    const ok = data.status === 'ok' && data.windows.length;
    const label = data.displayName ? 'Gemini / Antigravity' : meta.name;
    let stamp = '';
    if (data.snapshotAt) {
      const date = new Date(data.snapshotAt);
      if (Number.isFinite(date.getTime())) stamp = '<div class="snapshot">' + esc(date.toLocaleString('ja-JP',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'})) + ' の記録</div>';
    }
    return '<article class="service ' + id + '"><div class="service-head"><h2>' + esc(label) + '</h2><span class="service-number">' + meta.number + '</span></div>' + (ok ? data.windows.map(w => windowHtml(w,now)).join('') + stamp : '<div class="empty"><strong>—</strong><span>' + (loading ? '取得中' : '未取得') + '</span></div>') + '</article>';
  }).join('');
}
let pending = false;
function refresh() {
  if (pending) return;
  pending = true;
  $('refresh').disabled = true;
  const options = typeof AbortSignal !== 'undefined' && AbortSignal.timeout ? {signal:AbortSignal.timeout(65000)} : {};
  return fetch('/api/usage',options).then(response => {
    if (!response.ok) throw new Error('HTTP ' + response.status);
    return response.json();
  }).then(data => {
    if (!Array.isArray(data.providers)) throw new Error('Invalid response');
    latest = data.providers;
    initial = false;
    render(latest,false);
  }).catch(() => {
    if (initial) render([],false);
  }).then(() => {
    pending = false;
    $('refresh').disabled = false;
  });
}
$('refresh').addEventListener('click',refresh);
render([],true);
refresh();
setInterval(refresh,60000);
setInterval(() => { if (!initial) render(latest,false); },15000);

const tokenNumber = n => Number(n || 0).toLocaleString('ja-JP');
const localTime = n => new Date(n * 1000).toLocaleTimeString('ja-JP',{hour:'2-digit',minute:'2-digit'});
const chartFields = {five_hour:'5時間枠',seven_day:'週間枠'};
function chartSeries(data, metric) {
  return ((data.quotaHistory || {})[metric] || []).filter(p => Number.isFinite(p.time) && Number.isFinite(p.remaining) && p.remaining>=0 && p.remaining<=100 && p.time>=data.start && p.time<=data.end);
}
function chartHtml(data, metric) {
  const series=chartSeries(data,metric);
  if (!series.length) return '<p class="usage-note">この期間の残量記録はまだありません。これからCLIが通知する残量を記録します。</p>';
  const width=1000,height=300,left=65,right=24,top=25,bottom=46;
  const plotWidth=width-left-right,plotHeight=height-top-bottom;
  const x=n => left+(n-data.start)/Math.max(1,data.end-data.start)*plotWidth;
  const y=n => top+plotHeight-n/100*plotHeight;
  let svg='<svg class="token-chart" viewBox="0 0 '+width+' '+height+'" role="img" aria-label="'+esc(chartFields[metric])+'の残り利用枠。横軸は時刻、縦軸は0から100パーセント。"><title>'+esc(chartFields[metric])+' / 残り利用枠（%）</title>';
  for(let tick=0;tick<=100;tick+=25) svg+='<line class="chart-grid" x1="'+left+'" x2="'+(width-right)+'" y1="'+y(tick)+'" y2="'+y(tick)+'"/><text class="chart-label" x="'+(left-13)+'" y="'+(y(tick)+4)+'" text-anchor="end">'+tick+'%</text>';
  for(let i=0;i<=5;i++) {
    const time=data.start+(data.end-data.start)*i/5;
    svg+='<text class="chart-label" x="'+x(time)+'" y="'+(height-17)+'" text-anchor="'+(i===0?'start':i===5?'end':'middle')+'">'+esc(localTime(time))+'</text>';
  }
  svg+='<text class="chart-unit" x="'+left+'" y="13">残り利用枠</text>';
  // Connect observations only within one reset period and gaps of at most ten minutes.
  series.forEach((p,i) => {
    const previous=series[i-1];
    if(previous && p.reset===previous.reset && p.time-previous.time<=600) svg+='<line class="chart-line" x1="'+x(previous.time)+'" y1="'+y(previous.remaining)+'" x2="'+x(p.time)+'" y2="'+y(p.remaining)+'"/>';
    const description=localTime(p.time)+' / '+chartFields[metric]+' 残り '+p.remaining+'%';
    svg+='<g class="chart-point" tabindex="0" role="img" aria-label="'+esc(description)+'"><title>'+esc(description)+'</title><circle class="chart-hit" cx="'+x(p.time)+'" cy="'+y(p.remaining)+'" r="10"/><circle class="chart-dot" cx="'+x(p.time)+'" cy="'+y(p.remaining)+'" r="3"/></g>';
  });
  return svg+'</svg>'+(series.length===1?'<p class="usage-note">記録は1点です。次の残量が届くと推移を表示します。</p>':'');
}
let cachedUsage = null;
function usageReport(data) {
  const t = data.totals;

  const fields = [['新規入力','input_tokens'],['キャッシュ作成','cache_creation_input_tokens'],['キャッシュ読込','cache_read_input_tokens'],['出力','output_tokens']];
  let html = '<p class="usage-note">' + esc(localTime(data.start)) + '–' + esc(localTime(data.end)) + ' · ' + t.requests + 'リクエスト（メッセージIDで重複除外）</p>';
  html += '<div class="chart-heading"><h3>残り利用枠の推移</h3><select id="usageMetric" aria-label="グラフの利用枠">' + Object.keys(chartFields).map(key => '<option value="' + key + '">' + chartFields[key] + '</option>').join('') + '</select></div><div id="usageChart">' + chartHtml(data,'five_hour') + '</div>';
  html += '<p class="usage-note">CLIの実測記録。過去の未記録区間・10分を超える空白・リセットをまたぐ区間は線で結びません。</p>';
  if (!t.requests) return html;
  html += '<div class="token-totals">' + fields.map(f => '<div><span>' + f[0] + '</span><strong>' + tokenNumber(t[f[1]]) + '</strong></div>').join('') + '</div>';
  html += '<p class="usage-note">ローカル記録のトークン数です。種類ごとに重みが異なるため、5時間枠の消費率には換算できません。出力には思考 ' + tokenNumber(t.thinking) + ' トークンを含みます。Web・他の端末の利用は含みません。</p>';
  html += '<div class="usage-table-wrap"><table class="usage-table"><thead><tr><th>作業 / モデル</th><th>回数</th><th>新規入力</th><th>キャッシュ作成</th><th>キャッシュ読込</th><th>出力</th><th>最大入力文脈</th></tr></thead><tbody>';
  html += data.groups.map(g => '<tr><td><strong>' + esc(g.project) + '</strong><span>' + esc(g.agent ? 'サブ ' + g.agent.replace('agent-','').slice(0,8) : 'メイン') + ' · ' + localTime(g.first) + '–' + localTime(g.last) + '</span><span>' + esc(g.models.join(', ')) + '</span></td><td>' + g.requests + '</td><td>' + tokenNumber(g.input_tokens) + '</td><td>' + tokenNumber(g.cache_creation_input_tokens) + '</td><td>' + tokenNumber(g.cache_read_input_tokens) + '</td><td>' + tokenNumber(g.output_tokens) + '</td><td>' + tokenNumber(g.peakContext) + '</td></tr>').join('');
  html += '</tbody></table></div>';
  const top = data.groups[0];
  html += '<p class="usage-note">最多の記録：' + esc(top.project) + ' / ' + esc(top.agent || 'メイン') + '。主な操作：' + Object.keys(top.tools).slice(0,4).map(k => esc(k) + ' ' + top.tools[k] + '回').join('、') + '。</p>';
  if (top.largestReads && top.largestReads.length) html += '<p class="usage-note">大きな読み込み：' + top.largestReads.slice(0,3).map(r => esc(r.file) + '（' + tokenNumber(r.characters) + '文字）').join('、') + '。文字数はツール結果のサイズで、個別の枠消費率ではありません。</p>';
  return html;
}
let usageLoading = false;
function loadUsage() {
  if (usageLoading) return;
  usageLoading = true;
  $('reloadUsage').disabled = true;
  $('usageReport').textContent = '集計中…';
  fetch('/api/claude/usage-details?scope=' + encodeURIComponent($('usageScope').value)).then(r => {
    if (!r.ok) throw new Error('Request failed');
    return r.json();
  }).then(data => {
    cachedUsage = data;
    $('usageReport').innerHTML = usageReport(data);
    $('usageMetric').addEventListener('change',() => { $('usageChart').innerHTML = chartHtml(cachedUsage,$('usageMetric').value); });
  }).catch(() => {
    $('usageReport').textContent = '集計できませんでした。ダッシュボードを起動し直してください。';
  }).then(() => { usageLoading = false; $('reloadUsage').disabled = false; });
}
$('usageDetails').addEventListener('toggle',() => { if ($('usageDetails').open) loadUsage(); });
$('usageScope').addEventListener('change',loadUsage);
$('reloadUsage').addEventListener('click',loadUsage);
