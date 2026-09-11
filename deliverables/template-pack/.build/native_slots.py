from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from lxml import etree as E
root=Path(__file__).resolve().parents[1]
ns={'p':'http://schemas.openxmlformats.org/presentationml/2006/main','a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
P='{'+ns['p']+'}'
A='{'+ns['a']+'}'
ignore={'页码','模板说明','页面类型','分隔线','英文分类','模板编号','章节编号','数据声明'}
for src in sorted((root/'output').glob('*_模板.pptx')):
    target=root/'.build'/src.name[:2]/'candidate-native.pptx'
    with ZipFile(src) as iz, ZipFile(target,'w',ZIP_DEFLATED) as oz:
        for item in iz.infolist():
            data=iz.read(item.filename)
            if item.filename.startswith('ppt/slides/slide') and item.filename.endswith('.xml'):
                tree=E.fromstring(data)
                for index,shape in enumerate(tree.findall('.//p:sp',ns),1):
                    nv=shape.find('p:nvSpPr',ns)
                    if nv is None: continue
                    name=nv.find('p:cNvPr',ns).get('name','')
                    if name in ignore or name.startswith(('要点编号','章节序号')):continue
                    nvpr=nv.find('p:nvPr',ns)
                    if nvpr is None:nvpr=E.SubElement(nv,P+'nvPr')
                    typ='pic' if name.startswith('可替换图片') else 'title' if name in {'主标题','页面标题','章节标题','结束标题'} else 'subTitle' if name=='副标题' else 'body'
                    if nvpr.find('p:ph',ns) is None:E.SubElement(nvpr,P+'ph',type=typ,idx=str(index))
                    for paragraph in shape.findall('p:txBody/a:p',ns):
                        pp=paragraph.find('a:pPr',ns)
                        if pp is None:pp=E.Element(A+'pPr');paragraph.insert(0,pp)
                        pp.set('marL','0');pp.set('indent','0')
                        for tag in ['lnSpc','spcBef','spcAft','buNone','buChar','buAutoNum']:
                            for old in pp.findall('a:'+tag,ns):pp.remove(old)
                        for index2,(tag,unit,value) in enumerate([('lnSpc','spcPct','100000'),('spcBef','spcPts','0'),('spcAft','spcPts','0')]):
                            el=E.Element(A+tag);E.SubElement(el,A+unit,val=value);pp.insert(index2,el)
                        pp.insert(3,E.Element(A+'buNone'))
                data=E.tostring(tree,xml_declaration=True,encoding='UTF-8',standalone=True)
            oz.writestr(item,data)
    print(target.name,src.name)
