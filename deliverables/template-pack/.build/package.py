from pathlib import Path
import zipfile, xml.etree.ElementTree as ET, json, base64, html, shutil
from PIL import Image, ImageChops

root=Path(__file__).resolve().parents[1]
out=root/'output'
ns={'p':'http://schemas.openxmlformats.org/presentationml/2006/main','a':'http://schemas.openxmlformats.org/drawingml/2006/main','c':'http://schemas.openxmlformats.org/drawingml/2006/chart'}
files=sorted(out.glob('*_填充模板.pptx'))
assert len(files)==5
report=[]
sections=[]
for file in files:
    with zipfile.ZipFile(file) as z:
        assert z.testzip() is None
        slides=[n for n in z.namelist() if n.startswith('ppt/slides/slide') and n.endswith('.xml')]
        assert len(slides)==8
        trees=[ET.fromstring(z.read(n)) for n in slides]
        tables=sum(len(t.findall('.//a:tbl',ns)) for t in trees)
        charts=sum(len(t.findall('.//c:chart',ns)) for t in trees)
        ph=sum(len(t.findall('.//p:ph',ns)) for t in trees)
        pics=sum(len(t.findall('.//p:ph[@type="pic"]',ns)) for t in trees)
        books=[n for n in z.namelist() if n.startswith('ppt/embeddings/') and n.endswith('.xlsx')]
        assert tables==1 and charts==1 and pics==1 and ph>10 and len(books)==1, (file.name,tables,charts,pics,ph,books)
        report.append(dict(file=file.name,slides=8,native_tables=tables,native_charts=charts,placeholders=ph,picture_placeholders=pics,embedded_workbooks=len(books)))
    ident=file.name[:2]
    imgs=[]
    for n in range(1,9):
        image=root/'.build'/ident/f'native-{n:02}.png'
        assert image.exists()
        original=root/'.build'/ident/f'slide-{n:02}.png'
        difference=ImageChops.difference(Image.open(original).convert('RGB'),Image.open(image).convert('RGB'))
        assert difference.getbbox() is None, f'Visual changed: {ident}-{n}'
        uri='data:image/png;base64,'+base64.b64encode(image.read_bytes()).decode()
        imgs.append(f'<figure><img src="{uri}" alt="{html.escape(file.stem)} 第 {n} 页" loading="lazy"><figcaption>第 {n} 页</figcaption></figure>')
    sections.append(f'<section><h2>{html.escape(file.stem[3:].replace("_"," · "))}</h2><a href="{html.escape(file.name)}" download>下载此 PPTX</a><div class="pages">'+''.join(imgs)+'</div></section>')
page='''<!DOCTYPE html><html lang="zh-CN"><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>5 份 PPT 模板预览</title><style>*{box-sizing:border-box}body{margin:0;background:#f5f5f3;color:#20252c;font-family:"Microsoft YaHei",sans-serif}main{max-width:1400px;margin:auto;padding:40px 24px}h1{font-size:34px}p{line-height:1.8}section{margin:50px 0 70px}h2{font-size:26px}a{color:#225c95}.pages{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:22px;margin-top:24px}figure{margin:0}img{display:block;width:100%;height:auto;background:white;border:1px solid #ddd}figcaption{font-size:14px;color:#667;margin:8px 0}details{padding:18px;background:white}summary{cursor:pointer;font-size:18px}blockquote{line-height:1.9;margin:18px 0}@media(max-width:780px){.pages{grid-template-columns:1fr}main{padding:24px 14px}h1{font-size:28px}}</style><main><h1>套用我的模板 · 五种场景</h1><p>每份 8 页，16:9。文字、图表、表格可编辑，图片区域可替换。下方为最终 PPTX 的页面预览。</p><p><a href="使用说明.md">使用说明与附加要求示例</a></p>'''+''.join(sections)+'</main></html>'
(out/'模板预览.html').write_text(page,encoding='utf-8')
(root/'.build'/'structure-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
with zipfile.ZipFile(out/'PPT模板合集_5份.zip','w',zipfile.ZIP_DEFLATED) as z:
    for file in files+[out/'使用说明.md',out/'模板预览.html']:
        z.write(file,file.name)
with zipfile.ZipFile(out/'PPT模板合集_5份.zip') as z:
    assert z.testzip() is None and len(z.namelist())==7
print(json.dumps(report,ensure_ascii=False,indent=2))
previous=root/'.build'/'previous'
previous.mkdir(exist_ok=True)
for old in out.glob('*.pptx'):
    if old not in files:
        destination=previous/old.name
        assert old.resolve().is_relative_to(root.resolve()) and destination.resolve().is_relative_to(root.resolve())
        shutil.move(str(old),str(destination))
