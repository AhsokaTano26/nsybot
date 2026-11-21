/**
 * Dependency-free SVG sources for docs/rss-architecture.md.
 *   node docs/diagrams/build-rss-architecture.mjs
 *   node docs/diagrams/build-rss-architecture.mjs --png  # requires rsvg-convert
 * The PNG files are checked in so reading the document needs no rendering tools.
 */
import {readFileSync, writeFileSync, mkdirSync} from 'node:fs';
import {dirname, resolve, join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const out = join(root, 'docs/assets/rss-architecture');
const theme = JSON.parse(readFileSync(join(root, 'figures/theme.json'), 'utf8'));
const C = theme.palette;
const font = [theme.typography.family, ...theme.typography.cjk_fallbacks].join(', ');
const xml = s => String(s).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
const width = (s, size) => [...s].reduce((n, c) => n + size * (theme.typography.ascii_advances[c.charCodeAt(0)-32] ?? 1), 0);
const layoutErrors=[];
mkdirSync(out, {recursive: true});

class Diagram {
  constructor(number, name, title, subtitle, h) {
    Object.assign(this, {number, name, title, subtitle, h, nodes: [], texts: [], back: [], edges: [], front: []});
    this.text(48, 33, 'NSYBOT  /  CURRENT IMPLEMENTATION', 13, C.muted, {spacing: 1.6});
    this.text(48, 83, title, 36, C.ink, {weight: 700});
    this.text(48, 119, subtitle, 17, C.muted);
    this.front.push(`<path d="M48 145H1072" stroke="${C.border}" stroke-width="1"/>`);
    this.text(1072, 77, `${String(number).padStart(2, '0')} / 06`, 17, C.blue, {anchor: 'end'});
  }
  text(x, y, value, size=17, color=C.ink, {anchor='start', weight=400, spacing=0, owner=null}={}) {
    this.texts.push({x, y, value, size, owner, anchor});
    this.front.push(`<text x="${x}" y="${y}" font-size="${size}" font-weight="${weight}" fill="${color}" text-anchor="${anchor}" letter-spacing="${spacing}">${xml(value)}</text>`);
  }
  card(id, x, y, w, h, kicker, title, lines=[], tone='blue') {
    const color = C[tone], fill = C[`${tone}_light`] || C.white;
    const node = {id,x,y,w,h};
    this.nodes.push(node);
    this.front.push(`<g id="${id}"><rect x="${x}" y="${y}" width="${w}" height="${h}" rx="15" fill="${C.white}" stroke="${C.border}" stroke-width="1.3"/><path d="M${x+15} ${y}H${x+w-15}Q${x+w} ${y} ${x+w} ${y+15}V${y+39}H${x}V${y+15}Q${x} ${y} ${x+15} ${y}Z" fill="${fill}"/></g>`);
    this.text(x+20,y+25,kicker,13,color,{weight:700,spacing:.6,owner:id});
    this.text(x+20,y+65,title,21,C.ink,{weight:700,owner:id});
    lines.forEach((line,i)=>this.text(x+20,y+93+i*25,line,17,C.muted,{owner:id}));
    return node;
  }
  band(x,y,w,h,title,lines,tone='blue') {
    const id=`note-${this.nodes.length}`;
    const node={id,x,y,w,h};this.nodes.push(node);
    this.front.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="14" fill="${C[`${tone}_light`] || C.white}"/>`);
    this.text(x+22,y+31,title,18,C[tone],{weight:700,owner:id});
    lines.forEach((line,i)=>this.text(x+22,y+61+25*i,line,17,C.ink,{owner:id}));
    return node;
  }
  scope(x,y,w,h,label) {
    this.back.push(`<path d="M${x+18} ${y}H${x+w-18}Q${x+w} ${y} ${x+w} ${y+18}V${y+h-18}Q${x+w} ${y+h} ${x+w-18} ${y+h}H${x+18}Q${x} ${y+h} ${x} ${y+h-18}V${y+18}Q${x} ${y} ${x+18} ${y}Z" fill="${C.paper}" stroke="${C.border}" stroke-dasharray="5 5"/>`);
    this.text(x+20,y+30,label,16,C.muted,{weight:700});
  }
  anchor(n,side) {return ({N:[n.x+n.w/2,n.y],S:[n.x+n.w/2,n.y+n.h],W:[n.x,n.y+n.h/2],E:[n.x+n.w,n.y+n.h/2]})[side];}
  edge(a,sa,b,sb,{via=[],tone='blue',dash=false,label=null,at=null,fromOffset=0,toOffset=0}={}) {
    const offset=(p,s,n)=>['N','S'].includes(s)?[p[0]+n,p[1]]:[p[0],p[1]+n];
    const p=[offset(this.anchor(a,sa),sa,fromOffset),...via,offset(this.anchor(b,sb),sb,toOffset)];
    const d=p.map((xy,i)=>`${i?'L':'M'}${xy.join(' ')}`).join(' ');
    this.edges.push(`<path d="${d}" fill="none" stroke="${C[tone]}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"${dash?' stroke-dasharray="6 5"':''} marker-end="url(#arrow-${tone})"/>`);
    if(label) this.label(...at,label,tone);
  }
  rawArrow(x1,y1,x2,y2,label,tone='blue',dash=false) {
    this.edges.push(`<path d="M${x1} ${y1}H${x2}" fill="none" stroke="${C[tone]}" stroke-width="2.2"${dash?' stroke-dasharray="6 5"':''} marker-end="url(#arrow-${tone})"/>`);
    this.label((x1+x2)/2,y1-15,label,tone);
  }
  label(x,y,value,tone='blue') {
    const lines=Array.isArray(value)?value:[value];
    const w=Math.max(...lines.map(s=>width(s,14)))+20,h=lines.length*20+10;
    this.front.push(`<rect x="${x-w/2}" y="${y-15}" width="${w}" height="${h}" rx="7" fill="${C.white}"/>`);
    lines.forEach((line,i)=>this.text(x,y+1+i*20,line,14,C[tone],{anchor:'middle',weight:600}));
  }
  footer(text) {this.text(48,this.h-24,text,13,C.muted);}
  save() {
    // Mechanical authoring check: owned text remains in its card, cards never overlap.
    for(const t of this.texts) {
      const n=this.nodes.find(n=>n.id===t.owner);
      if(n && (t.x+width(t.value,t.size)>n.x+n.w-10 || t.y>n.y+n.h-9))
        layoutErrors.push(`${this.name}: text exceeds ${n.id}: ${t.value}`);
      if(t.y>this.h || t.x>1120) throw new Error(`${this.name}: text outside canvas`);
    }
    for(let i=0;i<this.nodes.length;i++) for(let j=i+1;j<this.nodes.length;j++) {
      const a=this.nodes[i],b=this.nodes[j];
      if(a.x<b.x+b.w && a.x+a.w>b.x && a.y<b.y+b.h && a.y+a.h>b.y)
        throw new Error(`${this.name}: overlapping cards: ${a.id}, ${b.id}`);
    }
    const defs=['blue','teal','amber','red','purple'].map(t=>`<marker id="arrow-${t}" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" orient="auto"><path d="M0 0L10 5L0 10Z" fill="${C[t]}"/></marker>`).join('');
    const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="${(1120*25.4/96).toFixed(6)}mm" height="${(this.h*25.4/96).toFixed(6)}mm" viewBox="0 0 1120 ${this.h}" role="img" aria-labelledby="title description"><title id="title">${xml(this.title)}</title><desc id="description">${xml(this.subtitle)}</desc><defs>${defs}</defs><g font-family="${font}"><rect width="1120" height="${this.h}" fill="${C.white}"/>${this.back.join('')}${this.edges.join('')}${this.front.join('')}</g></svg>\n`;
    const path=join(out,`${this.name}.svg`);writeFileSync(path,svg);
    if(process.argv.includes('--png')) {
      const r=spawnSync('rsvg-convert',['--width','2240','--output',join(out,`${this.name}.png`),path],{encoding:'utf8',env:{...process.env,XDG_CACHE_HOME:process.env.XDG_CACHE_HOME || '/tmp/nsybot-figure-font-cache'}});
      if(r.status!==0) throw new Error(r.stderr || 'Install librsvg to render PNG files.');
    }
    console.log(`${this.name}: ${this.nodes.length} cards, ${this.texts.length} labels`);
  }
}

function overview() {
  const d=new Diagram(1,'01-overview','全账户采集，两条消费路径','订阅决定 QQ 投递范围；已采集的全部条目进入缓存与补偿流程。',1010);
  const u=d.card('accounts',48,192,280,132,'INPUT / USER + PLANTFORM','账户与平台列表',['无群订阅也参与采集','账号之间保留 5–15 秒间隔'],'teal');
  const c=d.card('collector',420,192,280,132,'COLLECT / 20 MIN','统一 RSS 采集',['启动即执行，之后每 20 分钟','主源失败后尝试备用 RSSHub']);
  const h=d.card('rsshub',792,192,280,132,'EXTERNAL / RSSHUB','主源与备用源',['同一账号每轮复用一份响应','返回有限的近期 RSS 窗口'],'purple');
  const snap=d.card('window',48,398,280,132,'STORE / RSS_FEED_CACHE','最近一次有效窗口',['按账号保存 entries 与 digest','抓取失败不覆盖旧快照'],'teal');
  const q=d.card('queue',420,398,280,132,'STORE / RSS_INGEST_QUEUE','先落原始条目队列',['只为缺失或损坏缓存排队','后台补偿不再抓取 RSS'],'amber');
  const state=d.card('source',792,398,280,132,'HEALTH / TWITTER','链路状态与待通知队列',['退避跨重启保留','独立上报 Uptime Kuma'],'purple');
  const sub=d.card('subscriptions',48,604,280,132,'POLICY / SUBSCRIBE + CONFIG','群订阅与群设置',['决定发送给谁、发最近几篇','不决定是否采集或存库'],'teal');
  const db=d.card('content',420,604,280,132,'STORE / CONTENT + IMAGE SYNC','历史正文与图片索引',['正文与图片 URL 持久化','索引按首次图片文章入库递增'],'teal');
  const api=d.card('api',792,604,280,132,'READ ONLY / FASTAPI','内部图片增量 API',['Bearer Token + seq 游标','只读元数据，不抓取、不发 QQ']);
  const det=d.card('detail',48,810,280,132,'STORE / DETAIL','逐群处理记录',['已投递、启动静默与跳过','跨重启查询去重'],'teal');
  const qq=d.card('qq',420,810,280,132,'DELIVER / 60 SEC','QQ 官方 Bot 投递',['优先读 Content，按群筛选','正文分页与原图共用群锁']);
  const aia=d.card('aiaibot',792,810,280,132,'CONSUMER / AIAIBOT','aiaibot 独立同步',['经 Docker 内网调用 API','图片下载与游标保存由其完成'],'purple');
  d.edge(u,'E',c,'W');d.edge(c,'E',h,'W');
  d.edge(h,'N',c,'N',{via:[[932,166],[560,166]],tone:'purple',label:'有效响应',at:[744,160]});
  d.edge(c,'S',q,'N',{label:'全部有效条目',at:[560,363]});
  d.edge(q,'W',snap,'E',{label:'保存窗口',at:[374,455]});
  d.edge(c,'E',state,'N',{via:[[748,258],[748,366],[932,366]],tone:'purple'});
  d.edge(q,'S',db,'N',{label:'原子入库',at:[560,571],tone:'teal'});
  d.edge(db,'E',api,'W',{label:'只读',at:[746,662],tone:'teal'});
  d.edge(snap,'W',qq,'W',{via:[[24,464],[24,780],[356,780],[356,902]],toOffset:26,tone:'teal'});
  d.edge(sub,'E',qq,'W',{via:[[384,670],[384,850]],toOffset:-26,tone:'teal'});
  d.edge(db,'S',qq,'N',{label:'读取正文',at:[560,776],tone:'teal'});
  d.edge(qq,'S',det,'S',{via:[[560,966],[188,966]],label:'写处理结果',at:[374,956]});
  d.edge(api,'S',aia,'N',{label:'分页元数据',at:[932,776]});
  d.footer('蓝：执行流程   绿：持久化数据   橙：等待与补偿   紫：外部系统 / 监控。所有图描述当前代码。');d.save();
}

function collection() {
  const d=new Diagram(2,'02-collection-state','采集轮次状态与 RSS 源切换','SourceRound 是单轮内存状态；暂停截止时间另存 RSSSourceStatus。',1040);
  const u=d.card('unobserved',48,224,280,132,'UNOBSERVED','本轮尚无有效观测',['每轮重新创建','账号级错误保持状态、清计数']);
  const a=d.card('available',420,224,280,132,'AVAILABLE','本轮已有有效响应',['有效空窗口也算成功','成功时清连续故障计数'],'teal');
  const f=d.card('failing',48,480,280,132,'FAILING','暂未成功，累计全源故障',['低于阈值时继续下一个账号','本轮结束仍失败则记下线'],'amber');
  const p=d.card('paused',792,480,280,132,'PAUSED','暂停本轮剩余 Twitter',['429 / 全源限流立即触发','或连续全源故障达到阈值'],'red');
  d.band(792,224,280,132,'已成功后的少量故障',['状态仍为 AVAILABLE','连续计数累加，到阈值暂停'],'teal');
  d.edge(u,'E',a,'W',{label:'有效响应',at:[374,278],tone:'teal'});
  d.edge(u,'S',f,'N',{label:['全源故障','未达阈值'],at:[188,401],tone:'amber'});
  d.edge(f,'E',a,'W',{via:[[376,546],[376,290]],label:'恢复',at:[376,413],tone:'teal'});
  d.edge(f,'E',p,'W',{label:'连续故障达到阈值 / 限流',at:[560,534],tone:'red'});
  d.edge(a,'S',p,'N',{via:[[560,402],[932,402]],label:'达到阈值 / 限流',at:[746,390],tone:'red'});
  d.edge(u,'N',p,'E',{via:[[188,183],[1096,183],[1096,546]],label:'首次即全源限流：立即暂停',at:[702,177],tone:'red'});
  d.band(48,686,640,146,'每个 RSSHub 实例：首次请求 + 3 次指数退避',['请求 → 等 2 秒 → 重试 → 等 4 秒 → 重试 → 等 8 秒 → 重试','仍失败则切备用；更长 Retry-After 可直接冷却并切源','资源超限直接切源；格式或网络错误保留正常重试'],'blue');
  const next=d.card('next-round',792,686,280,156,'PERSIST / NEXT ROUND','保存全局暂停截止时间',['默认至少退避 900 秒','到期后的下一次采集再探测','其他平台仍继续采集'],'purple');
  d.edge(p,'S',next,'N',{label:'记录 down 观测',at:[932,651],tone:'red'});
  d.band(48,874,1024,102,'两个层次的冷却，各自负责不同范围',['实例路由冷却在内存中；Twitter 全局 retry_at 持久化。暂停不创建账号级抓取重试队列。'],'amber');
  d.footer('默认连续故障阈值 = 3。单账号 400 / 404 / 410、资源超限优先按账号错误处理，不据此判定全局下线。');d.save();
}

function ingest() {
  const d=new Diagram(3,'03-ingest-transaction','持久化入库补偿与原子提交','原始条目先落盘；队列版本、正文和图片索引在事务边界内协同。',1060);
  d.scope(608,184,464,752,'写入细节 / 同一数据库事务');
  const q=d.card('queued',72,224,440,132,'DURABLE / QUEUED','已排队，等待到期处理',['相同内容不重置失败次数或退避时间','原始内容改变时生成新 version'],'amber');
  const work=d.card('processing',72,444,440,156,'WORKER / DUE + FORMAT','预算内加载并处理原始条目',['独立每 60 秒补偿；默认最多 100 条','4 MiB 批次预算，条目间检查 1 秒预算','单次 HTML 提取，缓存阶段不翻译']);
  const retry=d.card('retry-pending',72,688,208,156,'RETRY_PENDING','保留并退避',['30 / 60 / 120 秒…','最长 1 小时','超限原始条目保留'],'amber');
  const superseded=d.card('superseded',304,688,208,156,'SUPERSEDED','旧版本已失效',['不覆盖新版本','不清除新任务','旧任务结束'],'purple');
  const committed=d.band(72,904,440,96,'COMMITTED / 入库完成',['正文、索引与本版本确认一起生效'],'teal');
  const claim=d.card('claim',648,252,384,132,'01 / CLAIM + WRITE LOCK','按 id + version 删除队列行',['先校验版本并取得 SQLite 写锁','匹配不到则返回 SUPERSEDED']);
  const content=d.card('write-content',648,440,384,132,'02 / CONTENT','插入或更新正文与图片 URL',['保留已有有效译文','flush 成功后继续'],'teal');
  const index=d.card('write-index',648,628,384,132,'03 / RSS_IMAGE_SYNC','按需登记图片同步序号',['有图片且尚无索引时新增 seq','翻译更新不会生成新序号'],'teal');
  const commit=d.band(648,816,384,96,'04 / COMMIT',['全部成功才提交；任一步失败整体回滚'],'teal');
  d.edge(q,'S',work,'N',{label:'到期 + 预算允许',at:[292,399]});
  d.edge(work,'S',retry,'N',{via:[[292,645],[176,645]],label:'解析 / 写库失败',at:[177,637],tone:'amber'});
  d.edge(work,'S',superseded,'N',{via:[[292,645],[408,645]],label:'版本不匹配',at:[410,637],tone:'purple'});
  d.edge(work,'E',committed,'E',{via:[[556,522],[556,952]],label:'提交成功',at:[556,870],tone:'teal'});
  d.edge(retry,'W',q,'W',{via:[[34,766],[34,290]],dash:true,tone:'amber'});
  d.edge(claim,'S',content,'N');d.edge(content,'S',index,'N',{tone:'teal'});d.edge(index,'S',commit,'N',{tone:'teal'});
  d.footer('排队本身失败：本轮明确失败、旧快照不更新。队列成功后即使文章暂未入库，也能在 RSS 窗口之外继续补偿。');d.save();
}

function delivery() {
  const d=new Diagram(4,'04-qq-delivery','QQ 按群投递：窗口、去重与降级','每 60 秒检查缓存；成功记录与静默 / 过滤记录分别保存在 Detail。',1120);
  const gate=d.card('delivery-gate',48,224,280,156,'ENTRY / CACHE CHECK','读取可投递的新快照',['QQ 在线；自动推送避开 02–08','账号已在本次启动后刷新','摘要 / 订阅 / 配置变化才处理']);
  const choose=d.card('window-policy',420,224,280,156,'STARTUP / WINDOW','基线与篇数选择',['启动长离线时：全窗口静默','默认最近 1 篇，0 表示全部','窗口外文章持久化标记跳过']);
  const decide=d.card('per-article',792,224,280,156,'DECISION / PER GROUP','逐篇去重与群过滤',['先查成功与跳过记录','再按自转发 / 转发设置决策','允许发送才加载正文与翻译']);
  const quiet=d.card('quiet',48,476,280,132,'STARTUP / WINDOW','写入静默或窗口外标记',['rss-skip 记录，updated 为空','不删除 Content 历史'],'amber');
  const skip=d.card('already-or-filtered',420,476,280,156,'ALREADY_DELIVERED / FILTERED','已处理或被过滤',['已有成功 / skip 记录：不再发送','被群设置过滤：写 rss-skip','这些分支同样算处理完成'],'purple');
  const send=d.card('send',792,476,280,156,'SEND / GROUP LOCK','正文分页，再逐图发送',['需要时补翻译，共享单并发','正文、图片共用机器人限速','整篇持有群锁，保持发送顺序']);
  d.band(48,748,280,132,'单张图片失败的降级',['4 次失败后发提示','正文已成功仍算本篇送达','不会因此重复推送正文'],'amber');
  const retry=d.card('delivery-retry',420,748,280,132,'ERROR / NEXT CHECK','等待下次推送检查',['正文或 Detail 写入未确认完成','本轮不缓存为全部完成'],'red');
  const done=d.card('delivered',792,748,280,132,'STORE / DETAIL','写入成功投递记录',['article_id + 群 OpenID','updated 保存发送时间'],'teal');
  d.edge(gate,'E',choose,'W');d.edge(choose,'E',decide,'W');
  d.edge(choose,'S',quiet,'N',{via:[[560,425],[188,425]],label:'静默 / 窗口外',at:[374,413],tone:'amber'});
  d.edge(decide,'W',skip,'N',{via:[[744,302],[744,422],[560,422]],tone:'purple'});
  d.edge(decide,'S',send,'N',{label:'SEND',at:[932,426]});
  d.edge(send,'S',done,'N',{label:'正文完成',at:[932,698],tone:'teal'});
  d.edge(send,'W',retry,'N',{via:[[744,554],[744,696],[560,696]],label:'正文 / 记账异常',at:[650,684],tone:'red'});
  d.band(48,942,1024,112,'处理结果与跨轮复用',['各群均处理完成后，缓存账号 digest + 群订阅 + 群配置指纹；相同窗口不重复处理。','QQ 发送和 Detail 记账不是原子事务：发送后崩溃或记账失败，重试可能再次发送正文。'],'blue');
  d.footer('自动推送休息时段固定北京时间。手动 refresh 不受该休息时段限制，但仍遵守启动静默与逐群去重规则。');d.save();
}

function imageApi() {
  const d=new Diagram(5,'05-image-sync','内部图片同步：游标分页与消费者检查点','API 返回图片元数据；图片文件由 aiaibot 依据原始 URL 自行下载。',1140);
  const xs=[152,424,696,968], heads=[['aiaibot','独立消费进程','purple'],['nsybot HTTP','现有 FastAPI 服务','blue'],['SQLite','Content + ImageSync','teal'],['图片 CDN','原始图片 URL','purple']];
  xs.forEach((x,i)=>{d.card(`actor-${i}`,x-104,192,208,132,'PARTICIPANT',heads[i][0],[heads[i][1]],heads[i][2]);d.back.push(`<path d="M${x} 324V942" stroke="${C.border}" stroke-width="1.4" stroke-dasharray="5 6"/>`);});
  const activation=(x,y,h,tone)=>d.back.push(`<rect x="${x-6}" y="${y}" width="12" height="${h}" rx="4" fill="${C[`${tone}_light`]}" stroke="${C[tone]}"/>`);
  activation(152,360,554,'purple');activation(424,360,330,'blue');activation(696,462,126,'teal');activation(968,788,128,'purple');
  d.rawArrow(158,376,418,376,['GET /internal/v1/images','cursor=N · limit≤200']);
  d.rawArrow(430,478,690,478,['Bearer 鉴权通过后','读取 seq > N 的下一页'],'teal');
  d.rawArrow(690,574,430,574,['ORDER BY seq · LIMIT L+1','释放数据库会话'],'teal',true);
  d.rawArrow(418,674,158,674,['items · next_cursor · has_more','仅元数据，Cache-Control: no-store'],'blue',true);
  d.rawArrow(158,804,962,804,'按 items.images 中的原始 URL 下载图片','purple');
  d.rawArrow(962,900,158,900,'图片文件；此流量不经过 nsybot 的同步 API','purple',true);
  d.band(48,978,1024,112,'aiaibot 侧的消费契约',['图片与元数据幂等处理成功后，再持久化 next_cursor；失败保留旧游标，允许整页重放。','历史补拉从 cursor=0 开始。seq 按入库先后排序，晚补入的旧推文也会获得更大的新 seq。'],'purple');
  d.footer('消费者处理流程是接口使用约定，本仓库不包含 aiaibot 的实现。API 默认关闭；启用后通过共享 Docker 内网访问。');d.save();
}

function kuma() {
  const d=new Diagram(6,'06-kuma-health','Twitter 链路状态与 Kuma 通知','健康观测、通知入队、网络上报与确认各自分工；通知渠道由 Kuma 管理。',1030);
  const o=d.card('observe',48,224,280,156,'OBSERVE / SOURCE ROUND','接收本轮健康观测',['有效响应：up 心跳','全源限流 / 故障：down','状态变化与周期心跳分开判断']);
  const s=d.card('source-status',420,224,280,156,'PERSIST / SOURCE STATUS','更新持久化链路状态',['available 与 observed_at','retry_at 跨进程重启保留','与通知入队在同一事务'],'teal');
  const q=d.card('notice-outbox',792,224,280,156,'OUTBOX / SOURCE NOTICE','持久化待上报状态',['仅配置 UT_URL 时入队','连续同状态合并检测时间','不同状态按顺序保留'],'amber');
  const ack=d.card('ack',48,478,280,132,'ACK / ID + OBSERVED_AT','只确认已发送的那个版本',['匹配 id + observed_at 才删除','新观测不会被旧确认清除'],'teal');
  const push=d.card('kuma-api',420,478,280,132,'HTTP / UPTIME KUMA','提交 Push 状态与消息',['必须 HTTP 成功且 ok=true','发送采集检测时间与 up/down'],'purple');
  const task=d.card('notice-worker',792,478,280,132,'SCHEDULE / 60 SEC','独立读取通知队列',['按 id 顺序处理，单次最多 10 条','不等待 QQ 在线或推文入库']);
  const newer=d.band(48,724,280,132,'发送时出现新观测',['旧版本确认匹配不到新时间','新版仍在队列，之后继续上报','可能再次发送相同可用性'],'teal');
  const channel=d.card('kuma-channels',420,724,280,132,'NOTIFY / KUMA CHANNELS','由 Kuma 发送上下线通知',['Twitter 上线 / Twitter 下线','通知渠道及重发策略在其配置'],'purple');
  const fail=d.card('notice-retry',792,724,280,132,'RETRY / KEEP OUTBOX','未获确认，保留重试',['网络 / HTTP / ok 校验失败','下次 60 秒调度继续尝试'],'amber');
  d.edge(o,'E',s,'W');d.edge(s,'E',q,'W',{tone:'teal'});d.edge(q,'S',task,'N',{tone:'amber'});
  d.edge(task,'W',push,'E');d.edge(push,'W',ack,'E',{label:'确认成功',at:[374,530],tone:'teal'});
  d.edge(ack,'S',newer,'N',{label:'版本保护',at:[188,676],tone:'teal',dash:true});
  d.edge(push,'S',channel,'N',{label:'通知策略',at:[560,676],tone:'purple'});
  d.edge(push,'E',fail,'W',{via:[[748,544],[748,790]],label:'未确认',at:[748,672],tone:'amber'});
  d.edge(fail,'E',q,'E',{via:[[1096,790],[1096,302]],tone:'amber',dash:true});
  d.band(48,906,1024,78,'心跳不是仅在状态变化时发送',['正常启动和后续有效探测也会入队 up 心跳；Kuma 超时阈值应覆盖 20 分钟采集间隔与整轮耗时。'],'blue');
  d.footer('这里表示 nsybot 经 RSSHub 的 Twitter 采集链路，不代表 Twitter 全站可用性；上报允许重试，不能宣称严格一次通知。');d.save();
}

overview();collection();ingest();delivery();imageApi();kuma();
if(layoutErrors.length) throw new Error(layoutErrors.join('\n'));
