// ئەگەر ئەم پەڕەیە لە شوێنێکی جیاوازتر (وەک Vercel) هەڵگیراوە لە سێرڤەری پایتۆن، ناونیشانی سێرڤەرەکە لێرە دابنێ
// نموونە: const API_BASE = "https://vidora.onrender.com";
const API_BASE = "";
if(API_BASE && !/^https:\/\/[A-Za-z0-9.-]+(:\d+)?$/.test(API_BASE)) throw new Error("API_BASE دروست نییە");

const hosts = {tiktok:["tiktok.com"],instagram:["instagram.com","instagr.am"],snapchat:["snapchat.com"]};
const names = {tiktok:"تیکتۆک",instagram:"ئینستاگرام",snapchat:"سناپچات"};
let plat="tiktok", qual="hd";
const $=id=>document.getElementById(id);
const msg=(t,c)=>{const m=$("msg");m.className="msg "+c;m.textContent=t;m.style.display=t?"block":"none"};

document.querySelectorAll(".plat").forEach(b=>b.onclick=()=>{
  document.querySelectorAll(".plat").forEach(x=>x.classList.remove("on"));
  b.classList.add("on");plat=b.dataset.p;
});
document.querySelectorAll(".qo").forEach(b=>b.onclick=()=>{
  document.querySelectorAll(".qo").forEach(x=>x.classList.remove("on"));
  b.classList.add("on");qual=b.dataset.q;
});
$("paste").onclick=async()=>{
  try{$("url").value=await navigator.clipboard.readText()}
  catch(e){$("url").focus();msg("تکایە بە دەستی لینکەکە لێرە بلکێنە (Paste).","info")}
};

function valid(u){
  try{const h=new URL(u).hostname.toLowerCase();return hosts[plat].some(x=>h===x||h.endsWith("."+x))}
  catch(e){return false}
}

function showLink(href){
  const m=$("msg");m.className="msg info";m.style.display="block";m.textContent="ڤیدیۆکە ئامادەیە ✓ ";
  const a=document.createElement("a");a.href=href;a.textContent="ئەگەر دابەزین دەستی پێنەکرد، لێرە دابگرە";
  a.style.cssText="display:block;margin-top:8px;color:inherit;font-weight:800;text-decoration:underline";
  m.appendChild(a);
}

$("go").onclick=async()=>{
  const u=$("url").value.trim();
  if(!u){msg("تکایە لینکی ڤیدیۆکە بنووسە.","err");return}
  if(!valid(u)){msg("ئەم لینکە هی "+names[plat]+" نییە. پلاتفۆرمەکە یان لینکەکە بپشکنە.","err");return}
  const bar=$("bar"),fill=bar.firstElementChild,btn=$("go");
  btn.disabled=true;btn.textContent="چاوەڕێ بکە...";bar.style.display="block";fill.style.width="15%";msg("","");
  let p=15;const t=setInterval(()=>{p=Math.min(p+4,90);fill.style.width=p+"%"},400);
  const ctl=new AbortController();const to=setTimeout(()=>ctl.abort(),170000);
  try{
    const r=await fetch(API_BASE+"/api/download",{method:"POST",headers:{"Content-Type":"application/json"},signal:ctl.signal,body:JSON.stringify({url:u,platform:plat,quality:qual})});
    let d=null;try{d=await r.json()}catch(e){}
    if(!r.ok||!d||!d.download_url){
      const err=new Error(d&&d.error?d.error:"سێرڤەر وەڵامی دروستی نەدایەوە (کۆد "+r.status+"). ئایا API_BASE ڕاستە؟");
      err.detail=d&&d.detail;throw err;
    }
    fill.style.width="100%";
    const rel=d.download_url;
    if(typeof rel!=="string"||!/^\/api\/file\/[0-9a-f]{32}\.[A-Za-z0-9]{2,5}(\?name=[^&#]*)?$/.test(rel)) throw new Error("وەڵامی سێرڤەر دروست نییە.");
    const href=API_BASE+rel;
    showLink(href);
    window.location.href=href;
  }catch(e){
    fill.style.width="100%";
    let t2=e.name==="AbortError"?"کات تەواو بوو. دووبارە هەوڵ بدەرەوە.":(e.message==="Failed to fetch"?"پەیوەندی بە سێرڤەرەوە نەکرا. سێرڤەرەکە چالاک نییە یان API_BASE هەڵەیە.":e.message);
    msg(t2,"err");
    if(e.detail){const s=document.createElement("small");s.dir="ltr";s.style.cssText="display:block;margin-top:6px;opacity:.7;word-break:break-all";s.textContent=e.detail;$("msg").appendChild(s)}
  }finally{
    clearTimeout(to);clearInterval(t);btn.disabled=false;btn.textContent="داگرتن ⬇";
    setTimeout(()=>{bar.style.display="none";fill.style.width="0"},900);
  }
};
// ───────── شوێنی ڕیکلام (بانەری ساکار، بێ سکریپتی لایەنی سێیەم، CSP ناشکێنێت)
// وێنەی بانەر بخەرە ناو static/ads/ و لێرە زیادی بکە. نموونە:
// {img:"/ads/banner1.webp", href:"https://example.com", alt:"ناوی ڕیکلامکەر"}
const ADS=[];
const SHOW_AD_PLACEHOLDER=true;
(function renderAd(){
  const slot=document.getElementById("ad-slot");if(!slot)return;
  const ok=ADS.filter(a=>/^\/ads\/[\w.-]+\.(png|jpe?g|webp|gif|svg)$/i.test(a.img||"")&&/^https:\/\/[^\s]+$/.test(a.href||""));
  let node;
  if(ok.length){
    const a=ok[Math.floor(Math.random()*ok.length)];
    node=document.createElement("a");node.className="ad-link";node.href=a.href;
    node.target="_blank";node.rel="sponsored noopener noreferrer";
    const im=document.createElement("img");im.src=a.img;im.alt=String(a.alt||"ڕیکلام");im.loading="lazy";node.appendChild(im);
    slot.appendChild(node);
    const sm=document.createElement("small");sm.textContent="ڕیکلام";slot.appendChild(sm);
  }else if(SHOW_AD_PLACEHOLDER){
    node=document.createElement("a");node.className="ad-ph";node.href="/advertise";node.textContent="ڕیکلامەکەت لێرە بنووسە ←";
    slot.appendChild(node);
  }else return;
  slot.hidden=false;
})();
if("serviceWorker" in navigator){navigator.serviceWorker.register("/service-worker.js").catch(()=>{})}
