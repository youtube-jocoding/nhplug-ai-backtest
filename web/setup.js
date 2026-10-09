'use strict';
const el=id=>document.getElementById(id);
let connected=false,busy=false;
function buttons(){el('start').disabled=!connected||busy||!el('consent').checked;el('save').disabled=busy;}
async function post(path,data){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const d=await r.json();if(!r.ok)throw Error(d.error);return d;}
el('keys').addEventListener('submit',async e=>{e.preventDefault();el('save').disabled=true;el('connection').textContent='연결 확인 중…';try{const r=await post('/api/keys',{key:el('key').value,secret:el('secret').value});connected=true;el('connection').textContent=r.message;}catch(e){el('connection').textContent=e.message;}finally{el('key').value='';el('secret').value='';buttons();}});
el('consent').addEventListener('change',buttons);
el('start').addEventListener('click',async()=>{busy=true;buttons();el('result').hidden=true;try{await post('/api/start',{consent:el('consent').checked});await status();}catch(e){busy=false;el('progress').textContent=e.message;buttons();}});
async function status(){try{const r=await fetch('/api/status');if(!r.ok)throw Error('세션이 만료됐습니다. Codex에 설정 화면을 다시 열어 달라고 요청하세요.');const s=await r.json();connected=s.keys_saved;busy=s.busy;el('progress').textContent=s.message;if(connected&&!el('connection').textContent)el('connection').textContent='이 컴퓨터에 저장된 NH 키가 있습니다.';el('result').hidden=s.stage!=='done';buttons();}catch(e){el('progress').textContent=e.message;el('start').disabled=true;}}
status();setInterval(status,2000);
