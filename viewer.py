import argparse
import json
from pathlib import Path

HTML_TEMPLATE = r'''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Grok 4.6 / 4.7 ベンチマーク結果</title>
<style>
  .viz-root {
    color-scheme: light;
    --surface-1:#fcfcfb; --page-plane:#f9f9f7; --text-primary:#0b0b0b;
    --text-secondary:#52514e; --text-muted:#898781; --gridline:#e1e0d9;
    --baseline:#c3c2b7; --border:rgba(11,11,11,.10);
    --series-1:#2a78d6; --series-2:#008300;
  }
  @media (prefers-color-scheme: dark) {
    :root:where(:not([data-theme="light"])) .viz-root {
      color-scheme:dark; --surface-1:#1a1a19; --page-plane:#0d0d0d; --text-primary:#fff;
      --text-secondary:#c3c2b7; --text-muted:#898781; --gridline:#2c2c2a;
      --baseline:#383835; --border:rgba(255,255,255,.10); --series-1:#3987e5; --series-2:#00a040;
    }
  }
  :root[data-theme="dark"] .viz-root {
    color-scheme:dark; --surface-1:#1a1a19; --page-plane:#0d0d0d; --text-primary:#fff;
    --text-secondary:#c3c2b7; --text-muted:#898781; --gridline:#2c2c2a;
    --baseline:#383835; --border:rgba(255,255,255,.10); --series-1:#3987e5; --series-2:#00a040;
  }
  *{box-sizing:border-box} html,body{margin:0} body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--page-plane);color:var(--text-primary)}
  .page{max-width:1260px;margin:0 auto;padding:24px 20px 64px} header.top{display:flex;align-items:baseline;justify-content:space-between;gap:16px;flex-wrap:wrap}
  h1{font-size:21px;margin:0}.subtitle{color:var(--text-secondary);font-size:13px;margin:5px 0 18px}
  button{font:inherit;font-size:13px;padding:6px 12px;border-radius:6px;border:1px solid var(--border);background:var(--surface-1);color:var(--text-primary);cursor:pointer}
  .meta{background:var(--surface-1);border:1px solid var(--border);border-radius:8px;padding:12px 14px;margin-bottom:16px;font-size:12px;color:var(--text-secondary);line-height:1.55}
  nav{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:28px} nav a{font-size:13px;color:var(--text-secondary);text-decoration:none;padding:5px 10px;border-radius:6px;border:1px solid var(--border);background:var(--surface-1)}
  section.dataset{margin-bottom:42px} section.dataset h2{font-size:16px;margin:0 0 4px;padding-top:10px;border-top:1px solid var(--gridline)}
  .desc{color:var(--text-muted);font-size:12px;margin:0 0 10px}.legend{display:flex;gap:16px;margin-bottom:12px}.item{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--text-secondary)}.swatch{width:12px;height:8px;border-radius:2px}
  .chart-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}@media(max-width:900px){.chart-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:620px){.chart-grid{grid-template-columns:1fr}}
  figure{margin:0;background:var(--surface-1);border:1px solid var(--border);border-radius:8px;padding:13px 12px 7px}figcaption{font-size:12px;font-weight:600;color:var(--text-secondary);margin-bottom:4px}svg{display:block;width:100%;height:auto;overflow:visible}
  .axis,.cat{font-size:9px;fill:var(--text-muted)}.extreme{font-size:9px;fill:var(--text-secondary);font-weight:600}.gridline{stroke:var(--gridline);stroke-width:1}.baseline{stroke:var(--baseline);stroke-width:1}.bar{cursor:pointer}.bar:focus{outline:2px solid var(--series-1)}
  #tooltip{position:fixed;pointer-events:none;background:var(--text-primary);color:var(--surface-1);font-size:12px;padding:6px 9px;border-radius:6px;transform:translate(-50%,calc(-100% - 10px));opacity:0;z-index:10;line-height:1.45}#tooltip.visible{opacity:1}#tooltip .r{display:flex;gap:10px;justify-content:space-between}#tooltip b{font-weight:700}
  .table-wrap{overflow-x:auto;background:var(--surface-1);border:1px solid var(--border);border-radius:8px;padding:10px}table{width:100%;border-collapse:collapse;font-size:11px;white-space:nowrap}caption{text-align:left;font-size:13px;font-weight:600;color:var(--text-secondary);padding:2px 4px 8px}th,td{text-align:right;padding:6px 8px;border-bottom:1px solid var(--gridline);font-variant-numeric:tabular-nums}th:first-child,td:first-child,th:nth-child(2),td:nth-child(2),th:nth-child(3),td:nth-child(3){text-align:left}thead th{color:var(--text-muted);font-weight:600}tbody tr:hover{background:var(--gridline)}
</style>
</head>
<body><div class="viz-root"><div class="page">
<header class="top"><div><h1>Grok 4.6 / 4.7 ベンチマーク結果</h1><p class="subtitle">reasoning_effort = high / xhigh — スコア・レイテンシ・トークン・コスト比較</p></div><button id="theme">ダークモード切替</button></header>
<div class="meta" id="meta"></div><nav id="nav"></nav><div id="sections"></div>
<section id="raw"><div class="table-wrap"><table><caption>生データ（全レコード）</caption><thead><tr>
<th>dataset</th><th>model</th><th>effort</th><th>n</th><th>errors</th><th>score</th><th>latency(s)</th><th>prompt</th><th>completion</th><th>reasoning</th><th>total</th><th>total cost($)</th><th>avg cost($)</th>
</tr></thead><tbody id="tbody"></tbody></table></div></section>
</div></div><div id="tooltip"></div>
<script id="results-data" type="application/json">__DATA_JSON__</script>
<script>
(()=>{"use strict";
const payload=JSON.parse(document.getElementById("results-data").textContent);const rows=payload.rows||payload;const meta=payload.meta||{};
const efforts=["high","xhigh"],models=[...new Set(rows.map(r=>r.model))].sort(),datasets=[...new Set(rows.map(r=>r.dataset))],colors=["--series-1","--series-2"];
const metrics=[
 {k:"avg_score",t:"平均スコア",u:"",f:v=>v.toFixed(3)},
 {k:"avg_latency",t:"平均レイテンシ",u:"s",f:v=>v.toFixed(2)},
 {k:"avg_total_tokens",t:"平均トークン（合計）",u:"",f:v=>Math.round(v).toLocaleString()},
 {k:"avg_reasoning_tokens",t:"平均 reasoning tokens",u:"",f:v=>Math.round(v).toLocaleString()},
 {k:"total_cost_usd",t:"合計コスト",u:" USD",f:v=>v.toFixed(5)},
 {k:"avg_cost_usd",t:"1サンプル平均コスト",u:" USD",f:v=>v.toFixed(6)}];
function H(tag,attrs={},children=[]){const n=document.createElement(tag);Object.entries(attrs).forEach(([k,v])=>k==="class"?n.className=v:n.setAttribute(k,v));children.forEach(c=>n.appendChild(typeof c==="string"?document.createTextNode(c):c));return n}
function S(tag,attrs={}){const n=document.createElementNS("http://www.w3.org/2000/svg",tag);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,v));return n}
function ticks(max){if(max<=0)return{max:1,ts:[0,.25,.5,.75,1]};const raw=max/4,mag=10**Math.floor(Math.log10(raw)),r=raw/mag,step=(r>5?10:r>2?5:r>1?2:1)*mag,nmax=Math.ceil(max/step)*step,ts=[];for(let x=0;x<=nmax+1e-9;x+=step)ts.push(x);return{max:nmax,ts}}
const tip=document.getElementById("tooltip");function show(target,cat,entries){tip.innerHTML=`<div>${cat}</div>`+entries.map(e=>`<div class="r"><span>${e.n}</span><b>${e.v}</b></div>`).join("");const r=target.getBoundingClientRect();tip.style.left=(r.left+r.width/2)+"px";tip.style.top=r.top+"px";tip.classList.add("visible")}function hide(){tip.classList.remove("visible")}
function chart(svg,cats,series,m){const W=390,Ht=210,ml=48,mr=8,mt=22,mb=25,pw=W-ml-mr,ph=Ht-mt-mb;svg.setAttribute("viewBox",`0 0 ${W} ${Ht}`);const vals=series.flatMap(s=>s.v.filter(x=>x!=null)),mx=Math.max(0,...vals),tk=ticks(mx),g=S("g",{transform:`translate(${ml},${mt})`});tk.ts.forEach(x=>{const y=ph-x/tk.max*ph,l=S("line",{x1:0,x2:pw,y1:y,y2:y,class:"gridline"}),t=S("text",{x:-6,y:y,class:"axis","text-anchor":"end","dominant-baseline":"middle"});t.textContent=m.f(x);g.append(l,t)});g.append(S("line",{x1:0,x2:pw,y1:ph,y2:ph,class:"baseline"}));const gw=pw/cats.length,bw=Math.min(38,(gw*.72-3*(series.length-1))/series.length);let best=null;cats.forEach((c,ci)=>{const lab=S("text",{x:ci*gw+gw/2,y:ph+16,class:"cat","text-anchor":"middle"});lab.textContent=c;g.append(lab);series.forEach((s,si)=>{const v=s.v[ci];if(v==null)return;const bh=v/tk.max*ph,x=ci*gw+(gw-(bw*series.length+3*(series.length-1)))/2+si*(bw+3),y=ph-bh;const rect=S("rect",{x,y,width:bw,height:Math.max(bh,.5),rx:3,fill:`var(${colors[si]})`}),grp=S("g",{class:"bar",tabindex:0});grp.append(rect);const es=series.map(ss=>({n:ss.n,v:m.f(ss.v[ci])+m.u}));grp.onpointerenter=()=>show(grp,c,es);grp.onpointerleave=hide;grp.onfocus=()=>show(grp,c,es);grp.onblur=hide;g.append(grp);if(!best||v>best.v)best={v,x:x+bw/2,y}})});if(best){const t=S("text",{x:best.x,y:Math.max(9,best.y-5),class:"extreme","text-anchor":"middle"});t.textContent=m.f(best.v)+m.u;g.append(t)}svg.append(g)}
function section(ds){const rr=rows.filter(r=>r.dataset===ds),sec=H("section",{class:"dataset",id:`ds-${ds}`});sec.append(H("h2",{},[ds]),H("p",{class:"desc"},[`${models.join(" / ")} × reasoning_effort (${efforts.join(", ")})`]));const leg=H("div",{class:"legend"});models.forEach((m,i)=>{const sw=H("span",{class:"swatch"});sw.style.background=`var(${colors[i]})`;leg.append(H("span",{class:"item"},[sw,m]))});sec.append(leg);const grid=H("div",{class:"chart-grid"});metrics.forEach(m=>{const fig=H("figure"),svg=S("svg"),ser=models.map(md=>({n:md,v:efforts.map(e=>{const r=rr.find(x=>x.model===md&&x.effort===e);return r?r[m.k]:null})}));fig.append(H("figcaption",{},[m.t]),svg);grid.append(fig);chart(svg,efforts,ser,m)});sec.append(grid);return sec}
const nav=document.getElementById("nav"),sections=document.getElementById("sections");datasets.forEach(ds=>{nav.append(H("a",{href:`#ds-${ds}`},[ds]));sections.append(section(ds))});nav.append(H("a",{href:"#raw"},["生データ"]));
const p=meta.pricing_usd_per_mtok||{};document.getElementById("meta").textContent=`料金: 入力 $${p.input??2}/MTok、出力 $${p.output??6}/MTok。${meta.reasoning_billing||""} `+(meta.escalations?.length?`難易度引き上げ: ${meta.escalations.map(x=>x.dataset+" (+"+x.added+")").join(", ")}`:"難易度引き上げ: なし");
const tb=document.getElementById("tbody");rows.forEach(r=>{const vals=[r.dataset,r.model,r.effort,r.n,r.errors,r.avg_score.toFixed(3),r.avg_latency.toFixed(2),Math.round(r.avg_prompt_tokens),Math.round(r.avg_completion_tokens),Math.round(r.avg_reasoning_tokens),Math.round(r.avg_total_tokens),r.total_cost_usd.toFixed(6),r.avg_cost_usd.toFixed(6)];tb.append(H("tr",{},vals.map(v=>H("td",{},[String(v)]))))});
document.getElementById("theme").onclick=()=>{const e=document.documentElement;e.setAttribute("data-theme",e.getAttribute("data-theme")==="dark"?"light":"dark")};
})();
</script></body></html>'''


def build_html(payload) -> str:
    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return HTML_TEMPLATE.replace("__DATA_JSON__", data_json)


def main() -> None:
    parser = argparse.ArgumentParser(description="ベンチマーク結果(JSON)をHTMLビューワに変換する")
    parser.add_argument("input", type=str)
    parser.add_argument("-o", "--output", type=str, default=None)
    args = parser.parse_args()
    input_path = Path(args.input)
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    output_path = Path(args.output) if args.output else input_path.with_suffix(".html")
    output_path.write_text(build_html(payload), encoding="utf-8")
    print(f"{output_path} を生成しました")


if __name__ == "__main__":
    main()
