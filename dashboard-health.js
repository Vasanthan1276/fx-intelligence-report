/* Freshness is evaluated in the viewer's browser even if publishing stops. */
(function (root) {
  'use strict';
  const DAY = 86400000;
  function easter(year) {
    const a=year%19,b=Math.floor(year/100),c=year%100,d=Math.floor(b/4),e=b%4,
      f=Math.floor((b+8)/25),g=Math.floor((b-f+1)/3),h=(19*a+b-d-g+15)%30,
      i=Math.floor(c/4),k=c%4,l=(32+2*e+2*i-h-k)%7,m=Math.floor((a+11*h+22*l)/451),
      month=Math.floor((h+l-7*m+114)/31),day=(h+l-7*m+114)%31+1;
    return Date.UTC(year,month-1,day);
  }
  function expectedMarketDate(now) {
    const parts=Object.fromEntries(new Intl.DateTimeFormat('en-GB', {timeZone:'Europe/Berlin',
      year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',hourCycle:'h23'}).formatToParts(now).map(p=>[p.type,p.value]));
    let date=new Date(`${parts.year}-${parts.month}-${parts.day}T00:00:00Z`);
    // ECB usually publishes around 16:00 CET; allow two hours of release grace.
    if (+parts.hour < 18) date=new Date(+date-DAY);
    for (;;) {
      const md=date.toISOString().slice(5,10), day=date.getUTCDay(), e=easter(date.getUTCFullYear());
      if (day!==0 && day!==6 && !['01-01','05-01','12-25','12-26'].includes(md) && +date!==e-2*DAY && +date!==e+DAY) break;
      date=new Date(+date-DAY);
    }
    return date.toISOString().slice(0,10);
  }
  function updateOverdue(lastAttempt, now) {
    if (!lastAttempt || !Number.isFinite(Date.parse(lastAttempt))) return null;
    // Backup is 17:30 UTC, with 8h grace for observed GitHub scheduling delays.
    let d=new Date(Date.UTC(now.getUTCFullYear(),now.getUTCMonth(),now.getUTCDate(),17,30));
    for(let n=0;n<8;n++,d=new Date(+d-DAY)) {
      if(d.getUTCDay()!==0 && d.getUTCDay()!==6 && +d+8*3600000<=+now)
        return Date.parse(lastAttempt)<+d-3600000;
    }
    return false;
  }
  function freshness(config, now=new Date()) {
    const s=config.status||{}, expected=expectedMarketDate(now), messages=[];
    const marketMs=Date.parse(config.marketDate+'T00:00:00Z');
    const validMarket=/^\d{4}-\d{2}-\d{2}$/.test(config.marketDate||'') && Number.isFinite(marketMs)
      && new Date(marketMs).toISOString().slice(0,10)===config.marketDate;
    const future=validMarket && marketMs>+now;
    const stale=validMarket && config.marketDate<expected;
    const overdue=updateOverdue(s.last_attempt_at_utc,now);
    if(!validMarket) messages.push('Market observation date is unknown.');
    else if(future) messages.push('Market observation is future-dated; data integrity needs review.');
    else if(stale) messages.push(`Stale reference data: ${config.marketDate}; expected ${expected} or later.`);
    else messages.push(`Reference data dated ${config.marketDate}; expected ${expected} or later.`);
    if(s.state==='failed') messages.push('Latest recorded update failed. Showing the retained snapshot; recommendations have not been refreshed.');
    else if(s.state==='no_new_market_data') messages.push('ECB rechecked; no new market date. Existing model snapshot retained.');
    else if(s.state==='updated') messages.push('Last recorded model update completed.');
    else messages.push('Update monitoring not yet recorded; job health is unknown.');
    if(overdue) messages.push('Scheduled update is overdue or its status was not published. Check Actions.');
    const fallback=(s.fx_fetch?.sources||[]).some(x=>x.status==='failed');
    if(fallback && s.state!=='failed') messages.push('An ECB source failed; validated fallback data is in use. See source health.');
    return {stale,overdue,warning:stale||overdue||future||s.state==='failed'||!s.state||fallback||!validMarket,
      text:messages.join(' '), expected};
  }
  if(typeof module!=='undefined' && module.exports) module.exports={freshness,expectedMarketDate,updateOverdue};
  if(typeof document==='undefined') return;
  function paint() {
    const state=freshness(root.fxReviewConfig);
    const banner=document.getElementById('freshness-banner');
    banner.textContent=state.text;
    banner.className='freshness-banner '+(state.warning?'warning':'healthy');
    document.getElementById('snapshot-time').textContent=Number.isFinite(Date.parse(root.fxReviewConfig.snapshotAt))
      ? new Intl.DateTimeFormat('en-SG',{timeZone:'Asia/Singapore',dateStyle:'medium',timeStyle:'short'}).format(new Date(root.fxReviewConfig.snapshotAt))+' SGT'
      : 'Unknown';
  }
  async function checkWorkflow() {
    const label=document.getElementById('workflow-check');
    try {
      const response=await fetch('https://api.github.com/repos/Vasanthan1276/fx-intelligence-report/actions/workflows/update-fx.yml/runs?branch=main&per_page=1',{cache:'no-store',signal:AbortSignal.timeout(8000)});
      if(!response.ok) throw new Error('unavailable');
      const run=(await response.json()).workflow_runs?.[0];
      if(!run) throw new Error('empty');
      label.textContent=`GitHub main workflow: ${run.conclusion||run.status} · started ${run.created_at} (UTC)`;
      if(['failure','cancelled','timed_out','action_required','startup_failure','stale'].includes(run.conclusion)) label.classList.add('job-failed');
    } catch (_) { label.textContent='GitHub job check unavailable (network or API limit). Published status and timestamps shown above; use the Actions link.'; }
  }
  document.addEventListener('DOMContentLoaded',()=>{
    const classic=new URLSearchParams(location.search).get('layout')==='classic';
    document.body.classList.toggle('classic-layout',classic);
    document.getElementById('layout-toggle').href=classic?'?':'?layout=classic';
    document.getElementById('layout-toggle').textContent=classic?'Review layout':'Classic layout';
    const sourcePanel=document.getElementById('source-details');
    if(classic && sourcePanel) sourcePanel.open=true;
    paint(); setInterval(paint,60000); checkWorkflow();
  });
})(typeof window!=='undefined'?window:this);
