// Connect the browser prototypes to the local SQLite-backed demo API.
const api = async (path, options = {}) => {
  const response = await fetch(path, {headers:{'Content-Type':'application/json'}, ...options});
  const body = await response.json().catch(()=>({}));
  if (!response.ok) throw new Error(body.error || '请求未完成');
  return body;
};
const notifyApp = message => {
  const toast = document.getElementById('toast');
  if (toast) { toast.textContent=message; toast.classList.add('show'); clearTimeout(window._apiToast); window._apiToast=setTimeout(()=>toast.classList.remove('show'),2800); }
  else alert(message);
};

if (location.pathname.endsWith('/tenders.html')) {
  window._bidPage=1;
  const baseTenderRender=render;
  const filteredTenderRecords=()=>{const q=document.getElementById('searchInput').value.trim().toLowerCase(),region=document.getElementById('regionFilter').value,type=document.getElementById('typeFilter').value,source=document.getElementById('sourceFilter').value;let list=records.filter(x=>(!q||(x.title+x.unit+x.type+x.region).toLowerCase().includes(q))&&(!region||x.region===region)&&(!type||x.type===type)&&(!source||x.source===source)&&(activeTab==='全部项目'||activeTab==='我的收藏'&&saved.has(x.id)||x.kind===activeTab));if(page==='我的收藏'||activeTab==='我的收藏')list=list.filter(x=>saved.has(x.id));return list};
  const drawTenderPages=()=>{const box=document.querySelector('.pages');if(!box)return;const count=Math.max(1,Math.ceil(filteredTenderRecords().length/5));window._bidPage=Math.min(Math.max(1,window._bidPage),count);const pageButtons=[];const add=(label,target,disabled=false,active=false)=>{const b=document.createElement('button');b.textContent=label;if(active)b.className='active';b.disabled=disabled;b.onclick=()=>{window._bidPage=target;render()};pageButtons.push(b)};add('‹',window._bidPage-1,window._bidPage===1);for(let n=1;n<=count;n++){if(count>7&&n>3&&n<count-2){if(n===4||n===count-3){const gap=document.createElement('button');gap.textContent='…';gap.disabled=true;pageButtons.push(gap)}continue}add(String(n),n,false,n===window._bidPage)}add('›',window._bidPage+1,window._bidPage===count);box.replaceChildren(...pageButtons)};
  render=function(){baseTenderRender();drawTenderPages()};
  const tenderStats=document.querySelectorAll('.stats .stat-value');
  const syncNotices=items=>{
    const stored=items.map(x=>({id:x.id,title:x.title,unit:x.unit,region:x.region,type:x.type,budget:x.budget,
      deadline:x.deadline||'待公布',source:x.source,kind:x.kind,status:x.status,published_at:x.published_at,
      sourceUrl:x.source_url||'',description:x.description||'',date:(x.published_at||'').slice(5,10)}));
    records.splice(0,records.length,...stored); render();
    if(tenderStats[0])tenderStats[0].textContent=stored.filter(x=>(x.published_at||'').slice(0,10)===new Date().toISOString().slice(0,10)).length;
    if(tenderStats[1])tenderStats[1].textContent=stored.length;
    const statLabels=document.querySelectorAll('.stats .stat-head');if(statLabels[1])statLabels[1].firstChild.textContent='本地库项目';const statFooters=document.querySelectorAll('.stats .stat-foot');if(statFooters[0])statFooters[0].textContent='来自已接入来源的今日公告';if(statFooters[1])statFooters[1].textContent='当前 SQLite 数据库内的公告';
    const limit=new Date();limit.setDate(limit.getDate()+7);if(tenderStats[2])tenderStats[2].textContent=stored.filter(x=>x.deadline&&new Date(x.deadline)>=new Date()&&new Date(x.deadline)<=limit).length;
    api('/api/platforms').then(platforms=>{if(tenderStats[3])tenderStats[3].textContent=platforms.length}).catch(()=>{});
    const mainNav=document.querySelector('.nav-item[data-nav="招标信息"] .count');if(mainNav)mainNav.textContent=stored.length;
    const trendCount=document.querySelector('.trend-summary b');if(trendCount)trendCount.textContent=stored.filter(x=>{const d=new Date(x.published_at||'');return !Number.isNaN(d.getTime())&&(Date.now()-d.getTime())<7*86400000}).length;
    const trendLabel=document.querySelector('.trend-summary span');if(trendLabel)trendLabel.textContent='本地库统计';const chart=document.querySelector('.chart');if(chart)chart.style.display='none';const trendFoot=document.querySelector('.trend-summary')?.nextElementSibling;if(trendFoot)trendFoot.textContent='近 7 日入库公告';
    const cats=document.querySelectorAll('.cat-row');cats.forEach(row=>{const name=row.querySelector('.cat-name')?.textContent.trim(),count=row.querySelector('.cat-num');if(count)count.textContent=stored.filter(x=>x.type===name).length});
    const reminder=document.querySelector('.notice-list');if(reminder){const soon=stored.filter(x=>x.deadline&&new Date(x.deadline)>=new Date()&&new Date(x.deadline)<=limit).sort((a,b)=>a.deadline.localeCompare(b.deadline)).slice(0,3);reminder.innerHTML=soon.map(x=>{const item=document.createElement('div');item.className='notice';item.innerHTML='<i class="notice-dot"></i><div><b></b><small></small></div>';item.querySelector('b').textContent=x.title;item.querySelector('small').textContent=`报名截止：${x.deadline} · 来源：${x.source}`;return item.outerHTML}).join('')||'<div class="notice">近期没有临近截止的已入库项目</div>'}
    const dateChip=document.querySelector('.date-chip');if(dateChip)dateChip.lastChild.textContent=new Date().toLocaleDateString('zh-CN',{year:'numeric',month:'long',day:'2-digit'});
    const result=document.getElementById('resultCount');if(result){const shown=document.querySelectorAll('#rows [data-view]').length;result.textContent=`显示 ${shown?1:0}–${shown} 条，共 ${stored.length} 条`}
    const fill=(id,values,label)=>{const select=document.getElementById(id);if(!select)return;const current=select.value;select.replaceChildren(new Option(label,''),...values.filter(Boolean).sort().map(value=>new Option(value,value)));if(values.includes(current))select.value=current};fill('regionFilter',[...new Set(stored.map(x=>x.region))],'全部地区');fill('typeFilter',[...new Set(stored.map(x=>x.type))],'全部类型');fill('sourceFilter',[...new Set(stored.map(x=>x.source))],'全部来源');
  };
  window.reloadNotices=()=>api('/api/notices').then(syncNotices).catch(e=>notifyApp('数据库信息读取失败：'+e.message));
  const updateMemberBadge=s=>{memberLoggedIn=!!s.authenticated;document.querySelectorAll('b,span,small').forEach(el=>{if(el.textContent.trim()==='林先生')el.textContent=s.authenticated?s.member.name:'访客';if(el.textContent.trim()==='专业版会员 · 有效期至 2026.12')el.textContent=s.authenticated?`${s.member.level}会员`:'登录后查看会员专属原文链接'});const avatar=document.querySelector('.user .avatar'),button=document.getElementById('loginBtn');if(avatar)avatar.textContent=s.authenticated?(s.member.name||'会').slice(0,1):'访';if(button)button.textContent=s.authenticated?'退出登录':'会员登录'};
  api('/api/session').then(s=>{updateMemberBadge(s);return window.reloadNotices()}).catch(()=>window.reloadNotices());
  document.getElementById('loginBtn').onclick=async()=>{if(memberLoggedIn){await api('/api/logout',{method:'POST',body:'{}'});updateMemberBadge({authenticated:false});await window.reloadNotices();notifyApp('已退出会员账号');return}document.getElementById('modalBg').classList.add('show')};
  setInterval(async()=>{try{const items=await api('/api/notices');const signature=items.map(x=>x.id+':'+x.updated_at+':'+x.source_url).join('|');if(signature!==window._noticeSignature){window._noticeSignature=signature;syncNotices(items)}}catch{ }},30000);
  new MutationObserver(()=>{const result=document.getElementById('resultCount');if(!result)return;const shown=document.querySelectorAll('#rows [data-view]').length;result.textContent=`显示 ${shown?1:0}–${shown} 条，共 ${records.length} 条`}).observe(document.getElementById('rows'),{childList:true});
  document.querySelectorAll('.filters input,.filters select,.tab,.nav-item').forEach(el=>el.addEventListener('input',()=>{window._bidPage=1;render()}));
  document.querySelectorAll('.tab,.nav-item').forEach(el=>el.addEventListener('click',()=>{window._bidPage=1;render()}));
  document.getElementById('submitLogin').onclick=async()=>{const fields=document.querySelectorAll('#modalBg .field input');try{const result=await api('/api/login',{method:'POST',body:JSON.stringify({phone:fields[0].value.trim(),password:fields[1].value})});updateMemberBadge({authenticated:true,member:{name:result.member.name,level:'会员'}});document.getElementById('modalBg').classList.remove('show');await window.reloadNotices();notifyApp('登录成功，项目原文链接已开放')}catch(e){notifyApp(e.message)}};
  document.getElementById('registerBtn').onclick=async()=>{const name=prompt('请输入姓名');if(!name)return;const phone=prompt('请输入 11 位手机号');if(!phone)return;const password=prompt('请设置至少 8 位密码');if(!password)return;try{const result=await api('/api/register',{method:'POST',body:JSON.stringify({name,phone,password})});updateMemberBadge({authenticated:true,member:{name:result.member.name,level:'基础版'}});document.getElementById('modalBg').classList.remove('show');await window.reloadNotices();notifyApp('注册成功，已登录')}catch(e){notifyApp(e.message)}};
}

if(location.pathname.endsWith('/index.html')||location.pathname.endsWith('/')){
  document.querySelectorAll('body *').forEach(el=>{if(el.children.length===0&&el.textContent.trim()==='当前为交互式界面原型，业务数据和服务接口待接入')el.textContent='本机服务已连接 · 数据保存在 E 盘数据库'});
}

if(location.pathname.endsWith('/maintenance.html')){
  const adminHeader=document.querySelector('.top span');if(adminHeader)adminHeader.textContent='本机运维面板 · 无管理员登录认证';
  const refreshStatus=async()=>{try{const result=await api('/api/status'),s=result.stats,stats=document.querySelectorAll('.grid .stat strong'),labels=document.querySelectorAll('.grid .stat span');if(labels[0])labels[0].textContent='本机服务状态';if(labels[1])labels[1].textContent='数据库项目总量';if(labels[2])labels[2].textContent='会员账号总量';if(labels[3])labels[3].textContent='启用中的采集任务';if(stats[0])stats[0].textContent='● 正常';if(stats[1])stats[1].textContent=s.notices;if(stats[2])stats[2].textContent=s.members;if(stats[3])stats[3].textContent=s.enabled_tasks;const checked=document.querySelector('.panels .panel .head small');if(checked)checked.textContent=`检查时间：${new Date(s.checked_at).toLocaleString('zh-CN')} · 数据库 ${(s.database_bytes/1024).toFixed(1)} KB`;const logBox=document.querySelector('.logs .body');if(logBox)logBox.innerHTML=result.logs.map(x=>{const row=document.createElement('div');row.className='log';const time=document.createElement('span'),action=document.createElement('b'),detail=document.createElement('span');time.textContent=x.created_at;action.textContent=x.action;detail.textContent=x.detail;row.append(time,action,detail);return row.outerHTML}).join('')||'<div class="log">暂无操作记录</div>';const serviceRows=document.querySelectorAll('.panels .panel:first-child .row');if(serviceRows[0])serviceRows[0].innerHTML=`<span><b>公开招标查询服务</b>　数据库公告 ${s.notices} 条</span><span class="badge">运行正常</span>`;if(serviceRows[1])serviceRows[1].innerHTML=`<span><b>会员与登录服务</b>　会员 ${s.members} 个</span><span class="badge">运行正常</span>`;if(serviceRows[2])serviceRows[2].innerHTML=`<span><b>来源采集服务</b>　已启用 ${s.enabled_sources}/${s.sources}</span><span class="badge">运行正常</span>`;if(serviceRows[3])serviceRows[3].innerHTML=`<span><b>采集任务调度</b>　启用 ${s.enabled_tasks}/${s.tasks} 个任务</span><span class="badge ${s.enabled_tasks?'':'warn'}">${s.enabled_tasks?'运行中':'待配置'}</span>`;if(serviceRows[4])serviceRows[4].innerHTML=`<span><b>已核验采集平台</b>　${s.verified_platforms}/${s.platforms} 个</span><span class="badge">正常</span>`}catch(e){notifyApp('系统状态读取失败：'+e.message)}};
  const accessPanel=document.querySelectorAll('.panels .panel')[1];if(accessPanel){accessPanel.querySelector('.head').firstChild.textContent='本机管理访问范围';accessPanel.querySelector('.head small').textContent='当前版本说明';const body=accessPanel.querySelector('.body');body.innerHTML='';['管理页面仅供本机使用','管理员账号与角色权限尚未配置','服务仅监听 127.0.0.1','双重验证尚未启用'].forEach(text=>{const row=document.createElement('div');row.className='row';row.textContent=text;body.appendChild(row)})}
  refreshStatus();document.getElementById('refresh')?.addEventListener('click',refreshStatus);
}

if (location.pathname.endsWith('/collection.html')) {
  let current={tasks:[],sources:[],notices:{total:0,linked:0}};
  const reload=async()=>{
    current=await api('/api/tasks'); data.splice(0,data.length,...current.tasks.map(t=>[
      t.name,t.source_name||'未绑定来源',t.connector_type==='json'?'JSON API':t.connector_type==='zhejiang_ggzy'?'浙江官方检索接口':t.connector_type==='hainan_ggzy'?'海南公开页面适配器':'RSS / Atom',t.enabled?'运行中':'已暂停',t.last_run||'尚未运行',String(t.added_count||'—'),t.id,t.last_status
    ])); render();
    const operator=document.querySelector('.top span');if(operator)operator.textContent='本机任务调度器 · 状态实时更新';
    const sourcesEl=document.querySelector('.right .panel');
    if(sourcesEl){const list=sourcesEl.querySelectorAll('.source');list.forEach(x=>x.remove());const head=sourcesEl.querySelector('.head');
      current.sources.forEach(s=>{const item=document.createElement('div');item.className='source';item.innerHTML=`<div class="source-line"><b></b><span class="badge"></span></div><small></small>`;item.querySelector('b').textContent=s.name;item.querySelector('.badge').textContent=s.last_status||'待运行';item.querySelector('small').textContent=`${s.allowed_host} · ${s.category} · ${s.last_checked||'尚未运行'}${s.last_error?' · '+s.last_error:''}`;head.after(item)});
    }
    const stats=document.querySelectorAll('.stat strong'),labels=document.querySelectorAll('.stat span');if(labels[0])labels[0].textContent='已登记来源';if(labels[1])labels[1].textContent='数据库内公告';if(labels[2])labels[2].textContent='启用采集任务';if(labels[3])labels[3].textContent='近期任务成功率';if(stats[0])stats[0].textContent=current.sources.length;if(stats[1])stats[1].textContent=current.notices.total;if(stats[2])stats[2].textContent=current.tasks.filter(t=>t.enabled).length;const finished=current.tasks.filter(t=>(t.last_status||'').startsWith('完成')||(t.last_status||'').startsWith('异常'));if(stats[3])stats[3].textContent=finished.length?Math.round(finished.filter(t=>t.last_status.startsWith('完成')).length/finished.length*100)+'%':'暂无';
    const reviewRows=document.querySelectorAll('.review-row');if(reviewRows.length){const panel=document.querySelector('.review .head');if(panel){const note=document.createElement('div');note.className='rule-note';note.textContent='已采集公告直接入库，并按来源公告标识去重；人工审核队列尚未配置。';panel.after(note)}reviewRows.forEach(row=>row.remove())}
    const jobs=document.querySelector('.jobs');if(jobs){jobs.replaceChildren();const recent=[...current.tasks].filter(t=>t.last_run).sort((a,b)=>b.last_run.localeCompare(a.last_run)).slice(0,5);recent.forEach(t=>{const row=document.createElement('div'),name=document.createElement('span'),status=document.createElement('span'),b=document.createElement('b');row.className='job';b.textContent=t.name;name.appendChild(b);status.textContent=`${t.last_run} · ${t.last_status||'已运行'}`;row.append(name,status);jobs.appendChild(row)});if(!recent.length)jobs.textContent='暂无采集运行记录'}
  };
  const drawPlatforms=platforms=>{
    const tbody=document.getElementById('platformRows');if(!tbody)return;
    tbody.innerHTML=platforms.map(p=>`<tr><td><b>${escapeHtml(p.name)}</b></td><td><a href="${escapeHtml(p.homepage_url)}" target="_blank" rel="noopener noreferrer">官网 ↗</a></td><td>${escapeHtml(p.region)} · ${escapeHtml(p.categories)}</td><td>${escapeHtml(p.access_method)}<br><small style="color:#9aa6b4">${escapeHtml(p.policy_note)}</small></td><td><span class="badge ${p.enabled?'status-ready':'status-pending'}">${escapeHtml(p.review_status)}</span></td><td>${p.connector_count||0}</td><td><button class="action" data-platform-toggle="${p.id}" data-enabled="${p.enabled?1:0}">${p.enabled?'暂停采集':'核验并启用'}</button></td></tr>`).join('')||'<tr><td colspan="7" style="padding:20px;color:#97a3b2">平台库暂无记录</td></tr>';
    tbody.querySelectorAll('[data-platform-toggle]').forEach(b=>b.onclick=async()=>{const enable=b.dataset.enabled!=='1';if(enable&&!confirm('请确认已核对该平台的访问规则、可用接入方式和允许频率，再启用采集。'))return;try{await api(`/api/platforms/${b.dataset.platformToggle}`,{method:'PATCH',body:JSON.stringify({enabled:enable,review_status:enable?'已核验并启用':'已暂停'})});await refreshPlatforms();notifyApp(enable?'平台已启用，关联任务可运行':'平台采集已暂停')}catch(e){notifyApp(e.message)}});
  };
  const refreshPlatforms=async()=>drawPlatforms(await api('/api/platforms'));
  const drawTasks=()=>{
    const tbody=document.getElementById('tasks'); if(!tbody)return;
    tbody.innerHTML=current.tasks.map(t=>`<tr><td><b>${escapeHtml(t.name)}</b></td><td>${escapeHtml(t.source_name||'来源已删除')}</td><td>${t.connector_type==='json'?'JSON API':t.connector_type==='zhejiang_ggzy'?'浙江官方检索接口':t.connector_type==='hainan_ggzy'?'海南公开页面适配器':'RSS / Atom'}</td><td><span class="badge ${t.enabled?'':'pause'}">${t.enabled?(t.last_status||'运行中'):'已暂停'}</span></td><td>${escapeHtml(t.last_run||'尚未运行')}</td><td>${t.added_count||'—'}</td><td><button class="action" data-run="${t.id}">运行</button> <button class="action" data-pause="${t.id}" data-enabled="${t.enabled?1:0}">${t.enabled?'暂停':'启用'}</button></td></tr>`).join('')||'<tr><td colspan="7" style="text-align:center;padding:30px;color:#9aa6b4">还没有采集任务，请创建任务并绑定公开 RSS / Atom 来源。</td></tr>';
    tbody.querySelectorAll('[data-run]').forEach(b=>b.onclick=async()=>{b.disabled=true;b.textContent='运行中…';try{const result=await api(`/api/tasks/${b.dataset.run}/run`,{method:'POST',body:'{}'});const progress=result.cursor?.progress_label?`（${result.cursor.progress_label}）`:result.total>result.read?`（匹配 ${result.total} 条，分批回填中）`:'';notifyApp(`采集完成：读取 ${result.read} 条${progress}，新增或更新 ${result.upserted} 条`)}catch(e){notifyApp('采集失败：'+e.message)}finally{await reload()}});
    tbody.querySelectorAll('[data-pause]').forEach(b=>b.onclick=async()=>{try{await api(`/api/tasks/${b.dataset.pause}`,{method:'PATCH',body:JSON.stringify({enabled:b.dataset.enabled!=='1'})});await reload()}catch(e){notifyApp(e.message)}});
    const count=document.getElementById('taskCount');if(count)count.textContent=`SQLite 库内 ${current.notices.total} 条公告 · ${current.notices.linked} 条具备已校验原文链接；采集信息持续保存在本机数据库。`;
  };
  window.render=()=>{drawTasks()};
  const originalRender=render; render=drawTasks;
  api('/api/tasks').then(reload).catch(e=>notifyApp('数据库连接失败：'+e.message));refreshPlatforms().catch(e=>notifyApp('平台库读取失败：'+e.message));setInterval(()=>reload().catch(()=>{}),30000);
  document.getElementById('addTask').onclick=()=>document.getElementById('mb').classList.add('show');
  document.getElementById('addPlatform').onclick=()=>document.getElementById('platformModal').classList.add('show');document.getElementById('closePlatform').onclick=()=>document.getElementById('platformModal').classList.remove('show');
  document.getElementById('savePlatform').onclick=async()=>{try{await api('/api/platforms',{method:'POST',body:JSON.stringify({name:document.getElementById('platformName').value,homepage_url:document.getElementById('platformUrl').value,region:document.getElementById('platformRegion').value,categories:document.getElementById('platformCategories').value,policy_note:document.getElementById('platformPolicy').value})});document.getElementById('platformModal').classList.remove('show');await refreshPlatforms();notifyApp('平台已登记为待核验，不会自动开始采集')}catch(e){notifyApp('登记失败：'+e.message)}};
  document.getElementById('save').onclick=async()=>{
    const name=document.getElementById('taskName').value.trim();
    const feed=document.querySelector('#mb input[placeholder^="https://"]').value.trim();
    const category=document.querySelector('#mb select').value;
    const cadence=document.querySelectorAll('#mb select')[1]?.value||'手动运行';
    if(!name||!feed){notifyApp('请填写任务名称和来源公开接口或 RSS / Atom 地址');return}
    const connectorChoice=prompt('选择公开接入类型：输入 rss、json、zj（浙江）或 hn（海南）','rss');if(!connectorChoice)return;
    const choice=connectorChoice.trim().toLowerCase();if(!['rss','json','zj','hn'].includes(choice)){notifyApp('仅支持 rss、json、zj 或 hn');return}const connector=choice==='zj'?'zhejiang_ggzy':choice==='hn'?'hainan_ggzy':choice;
    let adapterConfig={};
    if(connector==='json'){const raw=prompt('填写 JSON 字段映射配置，例如：{"items_path":"data.items","title_path":"title","link_path":"url","id_path":"id","published_path":"published_at","description_path":"description"}','{"items_path":"data.items","title_path":"title","link_path":"url","id_path":"id","published_path":"published_at","description_path":"description"}');if(!raw)return;try{adapterConfig=JSON.parse(raw)}catch{notifyApp('字段映射必须是有效 JSON');return}}
    if(connector==='zhejiang_ggzy')adapterConfig={category_code:'002001001',page_size:16};
    if(connector==='hainan_ggzy')adapterConfig={category_path:'jgzbgg',page_size:10};
    try{const sourceName=prompt('请填写这个公开来源的平台名称（需与平台库中的名称一致）',name+' 来源');if(!sourceName)return;
      let platforms=await api('/api/platforms');let platform=platforms.find(p=>p.name===sourceName);if(!platform){await api('/api/platforms',{method:'POST',body:JSON.stringify({name:sourceName,homepage_url:new URL(feed).origin+'/',region:'待确认',categories:category,access_method:connector==='zhejiang_ggzy'?'浙江官方公开检索接口':connector==='hainan_ggzy'?'海南官方公开页面':connector==='json'?'公开 JSON API':'RSS / Atom Feed',policy_note:'请核验来源公开规则与采集频率'})});platforms=await api('/api/platforms');platform=platforms.find(p=>p.name===sourceName);await refreshPlatforms()}
      await api('/api/sources',{method:'POST',body:JSON.stringify({name:sourceName,feed_url:feed,category,platform_id:platform.id,connector_type:connector,adapter_config:adapterConfig})});
      const latest=await api('/api/tasks');const source=latest.sources.find(s=>s.name===sourceName);
      await api('/api/tasks',{method:'POST',body:JSON.stringify({name,source_id:source.id,cadence})});
      document.getElementById('mb').classList.remove('show');document.getElementById('taskName').value='';document.querySelector('#mb input[placeholder^="https://"]').value='';await reload();await refreshPlatforms();notifyApp('来源和采集任务已保存；完成平台核验后即可运行');
    }catch(e){notifyApp('保存失败：'+e.message)}
  };
  document.getElementById('runAll').onclick=async()=>{await reload();for(const t of current.tasks.filter(x=>x.enabled)){try{await api(`/api/tasks/${t.id}/run`,{method:'POST',body:'{}'})}catch(e){notifyApp(`${t.name}：${e.message}`)}}await reload();notifyApp('已完成所有启用任务的调度')};
  const search=document.getElementById('q');search?.addEventListener('input',()=>{const q=search.value.toLowerCase();const rows=document.querySelectorAll('#tasks tr');rows.forEach(r=>r.hidden=!r.innerText.toLowerCase().includes(q))});
}

if (location.pathname.endsWith('/members.html')) {
  const refreshMembers=async()=>{const items=await api('/api/members');data.splice(0,data.length,...items.map(m=>[m.name,m.phone,m.level,m.status,m.created_at,m.expires_at,m.logins,m.id]));render();document.querySelectorAll('#rows tr').forEach(tr=>{const text=tr.innerText||'';const member=items.find(m=>text.includes(m.name)&&text.includes(m.phone));if(member)tr.dataset.memberId=member.id});const count=items.length,valid=items.filter(m=>m.status==='正常').length,expiring=items.filter(m=>m.status==='即将到期').length;const stats=document.querySelectorAll('.stat strong');if(stats[0])stats[0].textContent=count;if(stats[1])stats[1].textContent=valid;if(stats[2])stats[2].textContent=items.filter(m=>m.created_at===new Date().toISOString().slice(0,10)).length;if(stats[3])stats[3].textContent=expiring;document.querySelector('#count').textContent=`当前展示 ${count} 条会员记录 · 数据已保存到本机数据库`;document.querySelectorAll('#rows .act').forEach(button=>button.onclick=async()=>{const id=button.closest('tr')?.dataset.memberId;const member=items.find(m=>String(m.id)===String(id));if(!member)return;const operation=button.textContent.trim();if(operation==='查看'){alert(`${member.name}\n手机号：${member.phone}\n等级：${member.level}\n状态：${member.status}\n到期：${member.expires_at||'未设置'}`);return}const level=prompt('修改会员等级：基础版 / 专业版 / 企业版',member.level);if(!level)return;const status=prompt('修改账号状态：正常 / 即将到期 / 已停用',member.status);if(!status)return;try{await api(`/api/members/${id}`,{method:'PATCH',body:JSON.stringify({level,status})});notifyApp('会员资料已更新');await refreshMembers()}catch(e){notifyApp(e.message)}})};
  refreshMembers().catch(e=>notifyApp('会员数据库读取失败：'+e.message));
  document.getElementById('add').onclick=()=>document.getElementById('mb').classList.add('show');
  document.getElementById('save').onclick=async()=>{try{await api('/api/members',{method:'POST',body:JSON.stringify({name:document.getElementById('name').value,phone:document.getElementById('phone').value,level:document.getElementById('newlevel').value,password:document.getElementById('memberPassword').value})});document.getElementById('mb').classList.remove('show');notifyApp('会员账号已创建');await refreshMembers()}catch(e){notifyApp(e.message)}};
  const loginHeader=document.querySelector('.table thead th:nth-child(6)');if(loginHeader)loginHeader.textContent='登录次数';
  document.getElementById('export').onclick=async()=>{try{const items=await api('/api/members'),q=document.getElementById('q').value.trim(),level=document.getElementById('level').value,status=document.getElementById('status').value;const selected=items.filter(m=>(!q||(m.name+m.phone).includes(q))&&(!level||m.level===level)&&(!status||m.status===status));const csv=[['姓名','手机号','会员等级','账号状态','加入时间','服务到期','登录次数'],...selected.map(m=>[m.name,m.phone,m.level,m.status,m.created_at,m.expires_at,m.logins])].map(row=>row.map(v=>'"'+String(v??'').replaceAll('"','""')+'"').join(',')).join('\r\n');const url=URL.createObjectURL(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download='会员名单.csv';a.click();URL.revokeObjectURL(url);notifyApp(`已导出 ${selected.length} 条会员记录`)}catch(e){notifyApp(e.message)}};
}

function escapeHtml(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
