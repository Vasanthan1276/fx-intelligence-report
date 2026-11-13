const test=require('node:test');
const assert=require('node:assert/strict');
const {freshness,expectedMarketDate,updateOverdue}=require('../dashboard-health.js');
const now=new Date('2026-11-13T09:00:00Z');
const current={marketDate:'2026-11-12',snapshotAt:'2026-11-12T22:44:00Z',status:{state:'updated',last_attempt_at_utc:'2026-11-12T22:23:00Z'}};
test('normal snapshot is within expected release window',()=>assert.equal(freshness(current,now).warning,false));
test('stale data warns even if last update succeeded',()=>assert.equal(freshness({...current,marketDate:'2026-11-10'},now).stale,true));
test('failed job explicitly labels retained snapshot',()=>assert.match(freshness({...current,status:{state:'failed'}},now).text,/failed.*retained snapshot/));
test('fallback does not conceal primary failure',()=>assert.match(freshness({...current,status:{...current.status,fx_fetch:{sources:[{status:'failed'},{status:'available'}]}}},now).text,/source failed/));
test('same-date check does not imply model refresh',()=>assert.match(freshness({...current,status:{...current.status,state:'no_new_market_data'}},now).text,/Existing model snapshot retained/));
test('missing telemetry remains unknown',()=>assert.match(freshness({...current,status:{}},now).text,/job health is unknown/));
test('missed schedule detected when publication stops',()=>assert.equal(updateOverdue('2026-11-10T22:00:00Z',now),true));
test('weekend has no false overdue alert',()=>assert.equal(updateOverdue('2026-11-13T22:00:00Z',new Date('2026-11-15T10:00:00Z')),false));
test('weekend retains Friday reference date',()=>assert.equal(expectedMarketDate(new Date('2026-11-15T15:00:00Z')),'2026-11-13'));
test('Good Friday and Easter Monday use Thursday observation',()=>assert.equal(expectedMarketDate(new Date('2026-04-06T20:00:00Z')),'2026-04-02'));
test('May Day holiday recognized',()=>assert.equal(expectedMarketDate(new Date('2026-05-01T20:00:00Z')),'2026-04-30'));
test('Christmas and Boxing day recognized',()=>assert.equal(expectedMarketDate(new Date('2026-12-26T20:00:00Z')),'2026-12-24'));
test('release grace respects Berlin daylight savings',()=>assert.equal(expectedMarketDate(new Date('2026-07-13T15:00:00Z')),'2026-07-10'));

// Exercise the generated chart code with controlled network/library results.
const fs=require('node:fs'),vm=require('node:vm');
const page=fs.readFileSync(require('node:path').join(__dirname,'../index.html'),'utf8');
const chartScript=[...page.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m=>m[1]).find(s=>s.includes('async function loadHistory'));
function chartContext(records, options={}){
  const nodes=Object.fromEntries(['currencySelect','chartTitle','chartSection','chart-error','fxChart'].map(id=>[id,{hidden:true,scrollIntoView(){}}]));
  const sandbox={document:{getElementById:id=>nodes[id]},window:{addEventListener(){}},console,
    fetch:async()=>{if(options.reject)throw new Error('Network unavailable');return {ok:options.ok!==false,json:async()=>({records})};},
    Chart:options.noLibrary?undefined:function(){this.destroy=()=>{};sandbox.drawn=true;}};
  vm.createContext(sandbox);vm.runInContext(chartScript,sandbox);
  return {sandbox,nodes};
}
test('history chart renders normal data',async()=>{const {sandbox,nodes}=chartContext([{date:'2026-11-12',JPY:.8}]);await sandbox.showCurrency('JPY',false);assert.equal(sandbox.drawn,true);assert.equal(nodes['chart-error'].hidden,true);});
test('empty historical chart displays an error',async()=>{const {sandbox,nodes}=chartContext([]);await sandbox.showCurrency('JPY',false);assert.match(nodes['chart-error'].textContent,/empty or malformed/);assert.equal(nodes['chart-error'].hidden,false);});
test('history source failure is visible',async()=>{const {sandbox,nodes}=chartContext([],{reject:true});await sandbox.showCurrency('JPY',false);assert.match(nodes['chart-error'].textContent,/Network unavailable/);});
test('missing chart library is visible',async()=>{const {sandbox,nodes}=chartContext([{date:'2026-11-12',JPY:.8}],{noLibrary:true});await sandbox.showCurrency('JPY',false);assert.match(nodes['chart-error'].textContent,/Chart library unavailable/);});
test('currency with no usable observations is visible',async()=>{const {sandbox,nodes}=chartContext([{date:'2026-11-12',JPY:null}]);await sandbox.showCurrency('JPY',false);assert.match(nodes['chart-error'].textContent,/No historical observations/);});
test('future market dates are flagged',()=>assert.match(freshness({...current,marketDate:'2026-11-20'},now).text,/future-dated/));
test('invalid market dates are unknown',()=>assert.match(freshness({...current,marketDate:'2026-99-99'},now).text,/unknown/));
