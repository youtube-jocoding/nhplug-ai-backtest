'use strict';
const $=id=>document.getElementById(id),fmt=n=>new Intl.NumberFormat('ko-KR',{maximumFractionDigits:2}).format(n);
const word={BUY:'매수',SELL:'매도',HOLD:'보유 / 대기'};
let result=null,revision=0;
function list(el,items){el.replaceChildren(...items.map(x=>{const li=document.createElement('li');li.textContent=x;return li;}));}
function selectDay(day){
 if(!result)return;
 const s=result.signals.find(s=>s.date===day);if(!s)return;
 $('day').value=day;$('decision').textContent=word[s.action];$('reason').textContent=s.reason;
 $('aiReason').textContent=(s.provider==='codex-cli'?'실제 Codex 응답: ':'가상 테스트 응답: ')+s.ai_reason;
 list($('facts'),s.indicators);
 const t=result.trades.find(t=>t.signal_date===day);
 $('fill').textContent=t?`${t.date} ${word[t.side]} ${fmt(t.quantity)}주 × ${fmt(t.price)}원 · 비용 ${fmt(t.cost)}원`:s.executable_next_day?'체결 없음 (대기·보유 상태·예산 조건)':'마지막 날 판단 — 기간 내 다음 거래일이 없어 체결하지 않음';
 $('audit').textContent=JSON.stringify({information_through:s.input.information_through,price:s.input.market.price,high_52w:s.input.market.high_52w,turnover:s.input.market.turnover,input_hash:s.input_hash},null,2);
}
function svgEl(tag,attrs,text){const e=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v]of Object.entries(attrs))e.setAttribute(k,v);if(text!==undefined)e.textContent=text;return e;}
function chart(){
 const svg=$('chart');svg.replaceChildren();const bars=result.bars;
 const lo=Math.min(...bars.map(b=>b.low))*.99,hi=Math.max(...bars.map(b=>b.high))*1.01;
 const x=i=>72+i/(bars.length-1)*885,y=p=>320-(p-lo)/(hi-lo)*280;
 for(let i=0;i<=4;i++){const p=lo+(hi-lo)*i/4;svg.append(svgEl('line',{x1:72,x2:957,y1:y(p),y2:y(p),stroke:'#e9eff4'}),svgEl('text',{x:63,y:y(p)+4,'text-anchor':'end'},fmt(Math.round(p))));}
 const ticks=[...new Set([0,Math.floor((bars.length-1)/3),Math.floor((bars.length-1)*2/3),bars.length-1])];
 for(const i of ticks)svg.append(svgEl('text',{x:x(i),y:350,'text-anchor':'middle'},bars[i].date.slice(5)));
 svg.append(svgEl('polyline',{points:bars.map((b,i)=>`${x(i)},${y(b.close)}`).join(' '),fill:'none',stroke:'#008b8d','stroke-width':2.5}));
 bars.forEach((b,i)=>{const c=svgEl('circle',{cx:x(i),cy:y(b.close),r:4,fill:'#008b8d',tabindex:0,role:'button','aria-label':`${b.date} 판단 확인`});c.append(svgEl('title',{},`${b.date} 종가 ${fmt(b.close)}`));c.addEventListener('click',()=>selectDay(b.date));c.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' ')selectDay(b.date);});svg.append(c);});
 for(const t of result.trades){const i=bars.findIndex(b=>b.date===t.date),px=x(i),py=y(t.price),up=t.side==='BUY';const m=svgEl('polygon',{points:up?`${px},${py-10} ${px-8},${py+6} ${px+8},${py+6}`:`${px},${py+10} ${px-8},${py-6} ${px+8},${py-6}`,fill:up?'#008b8d':'#d74251',class:'marker',tabindex:0,role:'button','aria-label':`${t.date} ${word[t.side]} 체결`});m.append(svgEl('title',{},`${t.date} ${word[t.side]} ${fmt(t.price)}원`));m.addEventListener('click',()=>selectDay(t.signal_date));m.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' ')selectDay(t.signal_date);});svg.append(m);}
}
function render(){
 $('mInitial').textContent=fmt(result.initial);$('mFinal').textContent=fmt(result.final);$('mProfit').textContent=(result.profit>0?'+':'')+fmt(result.profit);$('mProfit').classList.toggle('loss',result.profit<0);$('mTrades').textContent=result.trades.length;
 $('warning').textContent=(result.source==='synthetic'?'샘플 가격 데이터':'NH 과거 시세')+' · '+(result.ai_mode==='codex-cli'?'실제 Codex 판단 기록 재생':'가상 테스트 판단 (AI 출력 아님)')+' · 실제 투자 성과 아님';
 $('source').textContent=`${result.name} · ${result.actual_start} ~ ${result.actual_end} · 조회: ${result.retrieved_at} · 매수 예산 ${fmt(result.buy_amount)}원 · 편도 비용 ${fmt(result.cost_rate_per_side*100)}% 가정`;
 $('day').replaceChildren(...result.signals.map(s=>new Option(s.date+' · '+word[s.action],s.date)));$('day').disabled=false;
 $('trades').replaceChildren(...result.trades.map(t=>{const row=document.createElement('tr');for(const v of[t.date,word[t.side],fmt(t.price),fmt(t.quantity),fmt(t.cost),t.signal_date]){const td=document.createElement('td');td.textContent=v;row.append(td);}row.addEventListener('click',()=>selectDay(t.signal_date));return row;}));
 $('empty').textContent=result.trades.length?'':'이 기간에는 체결이 없습니다. 결과를 만들기 위해 판단을 임의 변경하지 않습니다.';
 list($('assumptions'),result.assumptions);chart();selectDay(result.trades[0]?.signal_date||result.signals[0].date);$('download').disabled=false;
}
function clearResult(){revision++;result=null;for(const id of['mInitial','mFinal','mProfit','mTrades','decision','aiReason','fill','audit'])$(id).textContent='—';$('chart').replaceChildren();$('trades').replaceChildren();$('day').replaceChildren();$('day').disabled=true;$('download').disabled=true;$('facts').replaceChildren();$('reason').textContent='실행 결과가 없습니다.';$('source').textContent='';$('empty').textContent='';}
$('controls').addEventListener('submit',async e=>{
 e.preventDefault();clearResult();const submitted=revision;$('run').disabled=true;
 $('status').textContent='입력 검증 및 가상 매매 계산 중…';
 try{
  const response=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({dataset:$('dataset').value,mode:$('mode').value,start:$('start').value,end:$('end').value,initial:$('initial').value,fee:String(Number($('fee').value)/100)})});
  const data=await response.json();if(submitted!==revision)return;
  if(!response.ok)throw Error(data.error);result=data;render();
  $('status').textContent=`완료 · ${result.signals.length}일 판단 · 실제 주문 0건`;
 }catch(err){if(submitted===revision){$('status').textContent='실행 중단: '+err.message;$('warning').textContent='검증 실패 · 이전 결과를 표시하지 않습니다.';}}
 finally{$('run').disabled=false;}
});
$('day').addEventListener('change',()=>selectDay($('day').value));
function changed(){clearResult();$('status').textContent='조건이 변경됐습니다. 다시 실행하세요.';$('warning').textContent='선택한 가격·판단 출처를 확인하고 실행하세요. 실제 투자 성과 아님';}
$('controls').addEventListener('change',changed);
$('controls').addEventListener('input',changed);
$('download').addEventListener('click',()=>{if(!result)return;const url=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='backtest-'+result.run_hash.slice(0,12)+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
fetch('/api/datasets').then(r=>r.json()).then(items=>{$('dataset').replaceChildren(...items.map(d=>new Option(d.name+(d.source==='synthetic'?' (샘플)':' (NH)'),d.id)));
 if(new URLSearchParams(location.search).get('preset')==='filming'){
  const nh=items.find(d=>d.id==='nh-005930'&&d.source==='nh_period');
  if(!nh)throw Error('촬영 데이터 없음');
  $('dataset').value=nh.id;$('start').value='2026-09-14';$('end').value='2026-09-23';$('mode').value='replay';
  $('warning').textContent='NH 과거 시세 · 실제 Codex 판단 기록 재생 · 실제 투자 성과 아님';
  $('status').textContent='촬영 조건 준비 완료. 백테스트 실행을 누르세요.';
 }
}).catch(()=>{$('status').textContent='데이터 목록 또는 촬영 데이터를 불러오지 못했습니다.';$('run').disabled=true;});
