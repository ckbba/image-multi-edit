from pathlib import Path
from playwright.sync_api import sync_playwright
import argparse, json

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "前端代码" / "drive.css"
OUT = ROOT / "output" / "drive-grid"
SVG = """<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}'><rect width='100%' height='100%' fill='{c}'/><path d='M0 0L{w} {h}M{w} 0L0 {h}' stroke='white' stroke-width='8'/></svg>"""

def uri(w, h, c):
    import urllib.parse
    return "data:image/svg+xml," + urllib.parse.quote(SVG.format(w=w, h=h, c=c))

def card(i, w, h, c):
    name = f"ChatGPT 图像 2026年10月14日 超长文件名称_{i:02d}.jpg"
    return f"""<div class='drive-card' data-i='{i}'><input type='checkbox' aria-label='选择'><button class='drive-more'>•••</button><button class='drive-card-main'><span class='drive-card-preview'><img src='{uri(w,h,c)}'></span><span>{name}</span><small>{110+i} KB</small></button>{"<div class='drive-popover'>菜单<br>重命名<br>删除</div>" if i==0 else ''}</div>"""

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--expect", choices=["red", "green"], required=True)
    args = ap.parse_args(); OUT.mkdir(parents=True, exist_ok=True)
    cards = "".join(card(i, *[(100,300,"#4263eb"),(400,100,"#e8590c"),(260,260,"#2b8a3e"),(90,320,"#862e9c")][i%4]) for i in range(16))
    html = f"""<!doctype html><style>*{{box-sizing:border-box}}body{{margin:0}}button{{font:inherit}}.drive-popover{{position:absolute;z-index:9;background:white;border:1px solid #888;padding:8px;top:30px;right:0}}</style><main class='drive-page'><div id='drive-collection' class='drive-collection grid'>{cards}</div></main>"""
    sizes = [(1904,972),(1216,900),(390,844)]; reports=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        for vw,vh in sizes:
            page=browser.new_page(viewport={"width":vw,"height":vh})
            page.set_content(html)
            page.add_style_tag(content=(ROOT / '前端代码' / 'style.css').read_text(encoding='utf-8'))
            page.add_style_tag(content=CSS.read_text(encoding="utf-8")); page.wait_for_timeout(100)
            report=page.eval_on_selector_all(".drive-card", """cards=>cards.map((c,i)=>{let q=s=>c.querySelector(s).getBoundingClientRect(),r=c.getBoundingClientRect(),p=q('.drive-card-preview'),im=q('img'),t=q('.drive-card-main>span:nth-child(2)'),m=q('small'),n=cards[i+1]?.getBoundingClientRect();return {i,card:[r.x,r.y,r.right,r.bottom],preview:[p.x,p.y,p.right,p.bottom],image:[im.x,im.y,im.right,im.bottom],title:[t.x,t.y,t.right,t.bottom],meta:[m.x,m.y,m.right,m.bottom],next:n&&[n.x,n.y,n.right,n.bottom]}})""")
            bad=[]
            for x in report:
                r,pv,im,t,m=x["card"],x["preview"],x["image"],x["title"],x["meta"]
                if im[0]<pv[0]-.1 or im[1]<pv[1]-.1 or im[2]>pv[2]+.1 or im[3]>pv[3]+.1: bad.append([x["i"],"image"])
                if t[3]>r[3]+.1 or t[1]<pv[3]-.1: bad.append([x["i"],"title"])
                if m[3]>r[3]+.1: bad.append([x["i"],"meta"])
            controls=page.eval_on_selector(".drive-card", """c=>{let r=c.getBoundingClientRect(),a=c.querySelector('input').getBoundingClientRect(),b=c.querySelector('.drive-more').getBoundingClientRect(),s=getComputedStyle(c.querySelector('.drive-more'));return {inside:a.left>=r.left&&a.top>=r.top&&b.right<=r.right&&b.top>=r.top,bg:s.backgroundColor,color:s.color}}""")
            reports.append({"viewport":[vw,vh],"bad":bad,"controls":controls})
            page.screenshot(path=str(OUT/f"{args.expect}-{vw}x{vh}.png"), full_page=True)
            page.close()
        browser.close()
    (OUT/f"{args.expect}-report.json").write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding="utf-8")
    failed=any(r["bad"] for r in reports)
    print(json.dumps({"expect":args.expect,"geometry_failed":failed,"reports":reports},ensure_ascii=False))
    raise SystemExit(0 if failed==(args.expect=="red") else 1)
if __name__ == "__main__": main()
