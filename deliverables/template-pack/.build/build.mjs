import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {Presentation, PresentationFile, FileBlob} from '@oai/artifact-tool';
import {GlobalFonts} from '@napi-rs/canvas';
GlobalFonts.registerFromPath('C:/Windows/Fonts/msyh.ttc');
GlobalFonts.registerFromPath('C:/Windows/Fonts/msyhbd.ttc');
const SKILL='D:/CodexData/plugins/cache/openai-primary-runtime/presentations/26.904.11930/skills/presentations';
const ROOT='D:/xstarclaw/retry-ppt/main-ppt/deliverables/template-pack';
const PY='C:/Users/HQ/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe';
const {finalizePresentation,applyPresentationChartFont}=await import(pathToFileURL(SKILL+'/container_tools/artifact_tool_utils.mjs'));
const FONT='Microsoft YaHei';
const configs=[
 {id:'01',name:'经营分析_深蓝',title:'经营分析汇报',en:'BUSINESS REVIEW',ink:'#142C49',accent:'#287BC1',paper:'#FFFFFF',muted:'#657588',soft:'#EDF3F8',
  agenda:['经营概览','关键指标','业务分析','行动计划'],chapter:'经营表现与关键问题',sub:'汇报周期 / 业务范围 / 负责人',
  content:'核心结论与业务判断',left:'经营表现',right:'改进方向',a:['目标完成情况与主要变化','推动增长的关键业务因素','需要关注的异常指标'],b:['最优先解决的问题','可执行的改进措施','需要协调的资源与支持'],
  chart:'关键指标趋势',series:'示例指标',cats:['第一期','第二期','第三期','第四期'],values:[45,58,52,70],chartType:'line',
  table:'行动计划与责任分工',headers:['重点事项','具体行动','责任人','完成时间'],rows:[['事项一','填写行动内容','负责人','计划日期'],['事项二','填写行动内容','负责人','计划日期'],['事项三','填写行动内容','负责人','计划日期']],
  image:'业务场景与案例',imageLabel:'业务现场 / 案例图片',end:'下一阶段重点',endSub:'重点目标 · 关键行动 · 所需支持'},
 {id:'02',name:'项目方案_墨绿',title:'项目实施方案',en:'PROJECT PROPOSAL',ink:'#183C34',accent:'#487A61',paper:'#FAFBF7',muted:'#6C7A70',soft:'#EAF0E5',
  agenda:['项目背景','方案设计','实施安排','风险保障'],chapter:'方案设计与实施路径',sub:'项目名称 / 提案团队 / 提案日期',
  content:'项目目标与交付边界',left:'项目目标',right:'交付范围',a:['期望解决的业务问题','项目成功的衡量标准','主要相关方与使用场景'],b:['本期包含的交付成果','不包含的事项与边界','前置条件与协作要求'],
  chart:'阶段资源投入',series:'示例投入',cats:['调研','设计','实施','验收'],values:[20,30,40,10],chartType:'bar',
  table:'实施里程碑',headers:['阶段','主要交付','责任人','验收标准'],rows:[['调研阶段','需求清单','负责人','范围确认'],['实施阶段','阶段成果','负责人','指标达标'],['验收阶段','交付文档','负责人','验收签字']],
  image:'方案场景说明',imageLabel:'现场照片 / 方案示意',end:'实施准备事项',endSub:'范围确认 · 资源到位 · 时间安排'},
 {id:'03',name:'产品介绍_紫黑',title:'产品与解决方案',en:'PRODUCT OVERVIEW',ink:'#292237',accent:'#7657BA',paper:'#FCFBFE',muted:'#756E83',soft:'#EFEAF8',
  agenda:['客户需求','产品能力','应用场景','实施服务'],chapter:'核心能力与使用体验',sub:'产品名称 / 产品版本 / 演示日期',
  content:'客户需求与产品价值',left:'客户需求',right:'对应能力',a:['典型用户面临的问题','现有流程中的效率瓶颈','使用体验与协作需求'],b:['解决问题的核心功能','与现有系统的配合方式','可验证的价值与收益'],
  chart:'使用效果对比',series:'示例评分',cats:['场景一','场景二','场景三','场景四'],values:[60,75,68,85],chartType:'bar',
  table:'产品能力清单',headers:['能力模块','解决问题','交付形式','适用场景'],rows:[['模块一','填写业务问题','功能 / 服务','目标场景'],['模块二','填写业务问题','功能 / 服务','目标场景'],['模块三','填写业务问题','功能 / 服务','目标场景']],
  image:'产品界面与场景',imageLabel:'产品截图 / 使用场景',end:'产品体验与合作',endSub:'演示安排 · 试用范围 · 联系方式'},
 {id:'04',name:'培训教学_暖橙',title:'主题培训课程',en:'LEARNING SESSION',ink:'#493422',accent:'#C66A2D',paper:'#FFFCF7',muted:'#857568',soft:'#F7EDDF',
  agenda:['学习目标','核心知识','案例练习','课后应用'],chapter:'核心知识与实践方法',sub:'课程主题 / 适用学员 / 授课人',
  content:'关键概念与实际应用',left:'知识要点',right:'应用提示',a:['用一句话解释核心概念','理解概念所需的背景','概念的适用条件与边界'],b:['工作中何时使用这一方法','一个贴近实际的使用案例','常见错误及纠正方式'],
  chart:'练习结果分布',series:'示例得分',cats:['练习一','练习二','练习三','练习四'],values:[65,80,72,90],chartType:'bar',
  table:'练习与反馈',headers:['练习任务','完成要求','检查标准','反馈记录'],rows:[['任务一','填写操作要求','填写检查标准','待填写'],['任务二','填写操作要求','填写检查标准','待填写'],['任务三','填写操作要求','填写检查标准','待填写']],
  image:'操作示例与讲解',imageLabel:'操作截图 / 教学案例',end:'课程回顾与练习',endSub:'关键知识 · 工作应用 · 课后任务'},
 {id:'05',name:'工作总结_朱红',title:'阶段工作总结',en:'PERIOD REVIEW',ink:'#47292C',accent:'#AF4547',paper:'#FFFDFC',muted:'#836F73',soft:'#F7EBEB',
  agenda:['工作概况','成果展示','问题复盘','下期计划'],chapter:'重点成果与经验复盘',sub:'总结周期 / 所属部门 / 汇报人',
  content:'工作成果与问题复盘',left:'主要成果',right:'经验与改进',a:['本阶段完成的重点工作','已交付成果及对应价值','跨团队协作与支持情况'],b:['执行过程中的主要问题','可复用的经验和方法','下一阶段需要调整的做法'],
  chart:'工作完成情况',series:'示例完成量',cats:['任务一','任务二','任务三','任务四'],values:[80,60,90,75],chartType:'bar',
  table:'下阶段工作安排',headers:['工作任务','预期成果','责任人','计划时间'],rows:[['任务一','填写预期成果','负责人','计划日期'],['任务二','填写预期成果','负责人','计划日期'],['任务三','填写预期成果','负责人','计划日期']],
  image:'成果展示与说明',imageLabel:'成果照片 / 交付截图',end:'下阶段工作重点',endSub:'目标确认 · 行动安排 · 协作需求'},
];
function text(s,name,txt,x,y,w,h,size,color,bold=false,ph){
 const o=s.shapes.add({geometry:'textbox',name,position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0},...(ph?{placeholderType:ph,placeholderIndex:s.shapes.items.length+1}:{})});
 o.text=txt;o.text.style={typeface:FONT,fontSize:size,color,bold,autoFit:'none',verticalAlignment:'middle'};return o;
}
function line(s,c,x,y,w){s.shapes.add({geometry:'rect',name:'分隔线',position:{left:x,top:y,width:w,height:1},fill:c,line:{fill:'none',width:0}});}
function base(p,c,n,title,label){const s=p.slides.add();s.background.fill=c.paper;
 text(s,'组织名称','组织名称',64,25,300,25,16,c.muted,false,'body');
 text(s,'页码',String(n).padStart(2,'0')+' / 08',1110,25,105,25,16,c.muted);
 if(title)text(s,'页面标题',title,64,86,1148,72,42,c.ink,true,'title');
 line(s,c.accent,64,177,1152);text(s,'模板说明','模板示例 · 请替换内容',64,673,670,24,14,c.muted);
 text(s,'页面类型',label,988,673,230,24,14,c.muted);return s;}
function list(s,c,x,y,w,items){items.forEach((v,i)=>{text(s,'要点编号_'+i,String(i+1).padStart(2,'0'),x,y+i*102,48,32,20,c.accent,true);text(s,'内容要点_'+i,v,x+60,y+i*102,w-60,67,26,c.ink,false,'body');});}
async function build(c){
 const p=Presentation.create({slideSize:{width:1280,height:720}});let s;
 // 1. Minimal typographic cover with an editable title and metadata.
 s=p.slides.add();s.background.fill=c.ink;
 text(s,'组织名称','组织名称',72,42,480,40,20,'#FFFFFF',false,'body');
 text(s,'英文分类',c.en,72,182,1040,44,24,'#FFFFFF');
 text(s,'主标题',c.title,72,270,1090,118,76,'#FFFFFF',true,'title');
 text(s,'副标题',c.sub,76,425,1000,52,26,'#FFFFFF',false,'subtitle');
 text(s,'日期','汇报日期：YYYY.MM.DD',76,614,800,32,18,'#FFFFFF',false,'body');
 text(s,'模板编号','TEMPLATE '+c.id,1034,614,190,32,16,'#FFFFFF');
 // 2. Agenda: flat numbered rows, no pseudo controls.
 s=base(p,c,2,'内容目录','目录页');
 c.agenda.forEach((v,i)=>{text(s,'章节序号_'+i,'0'+(i+1),88,216+i*101,100,62,40,c.accent,true);text(s,'章节标题_'+i,v,220,218+i*101,905,60,32,c.ink,false,'body');if(i<3)line(s,c.soft,220,296+i*101,920);});
 // 3. Chapter page has generous whitespace and a sentence-sized summary.
 s=p.slides.add();s.background.fill=c.soft;
 text(s,'章节编号','01',72,68,480,180,132,c.accent,true);
 text(s,'章节标题',c.chapter,76,315,1128,100,56,c.ink,true,'title');
 text(s,'章节摘要','填写本章节的核心内容与讨论范围',80,465,1050,58,28,c.muted,false,'body');
 text(s,'模板说明','组织名称 / 章节过渡页',80,655,700,28,16,c.muted);
 // 4. Editable side-by-side content.
 s=base(p,c,4,c.content,'双栏内容页');
 text(s,'左栏标题',c.left,76,216,510,51,30,c.accent,true,'body');
 text(s,'右栏标题',c.right,688,216,510,51,30,c.accent,true,'body');
 list(s,c,76,300,510,c.a);list(s,c,688,300,510,c.b);
 // 5. Native data chart backed by an embedded example workbook.
 s=base(p,c,5,c.chart,'原生图表页');
 text(s,'数据声明','示例数据，非真实业务结果；单位：示例值',74,203,1020,33,18,c.muted);
 const ch=s.charts.add(c.chartType,{position:{left:64,top:260,width:804,height:350},categories:c.cats,series:[{name:c.series,values:c.values,fill:c.accent,line:{fill:c.accent,width:3},marker:{symbol:'circle',size:7}}],barOptions:{direction:'column',grouping:'clustered',gapWidth:100},hasLegend:false,dataLabels:{showValue:true,position:'outEnd',textStyle:{fontSize:18,typeface:FONT,color:c.ink}},xAxis:{textStyle:{fontSize:18,typeface:FONT,color:c.muted}},yAxis:{minimumScale:0,maximumScale:100,numberFormatCode:'0',textStyle:{fontSize:16,typeface:FONT,color:c.muted}},chartFill:c.paper,plotAreaFill:c.paper});
 applyPresentationChartFont(ch,{fontFamily:FONT});
 text(s,'结论标题','分析结论',928,270,286,44,28,c.accent,true,'body');
 text(s,'结论正文','填写变化趋势\n解释主要原因\n说明业务影响',928,340,278,180,27,c.ink,false,'body');
 text(s,'来源标注','数据来源：待填写',928,571,278,44,16,c.muted,false,'body');
 s.speakerNotes.textFrame.setText('本页数值仅为展示原生图表布局的示例，不代表真实业务结果。');
 // 6. Native table with semantic header and stable editable cells.
 s=base(p,c,6,c.table,'原生表格页');
 text(s,'表格摘要','填写本页计划、清单或对照关系的说明',72,205,1136,44,24,c.muted,false,'body');
 const vals=[c.headers,...c.rows];
 const tb=s.tables.add({rows:4,columns:4,left:72,top:292,width:1136,height:272,columnWidths:[220,380,220,316],values:vals});
 tb.borders.assign({fill:c.paper,width:2,style:'solid'});
 for(let r=0;r<4;r++)for(let k=0;k<4;k++){const cell=tb.getCell(r,k);cell.fill=r===0?c.ink:(r%2?c.soft:c.paper);cell.text.style={typeface:FONT,fontSize:23,bold:r===0,color:r===0?'#FFFFFF':c.ink};}
 text(s,'补充说明','补充说明：填写相关约束、依赖条件或更新日期',74,596,1110,42,20,c.muted,false,'body');
 // 7. Real picture placeholder, deliberately empty for source-specific imagery.
 s=base(p,c,7,c.image,'图文内容页');
 const pic=s.shapes.add({geometry:'rect',name:'可替换图片_横向',placeholderType:'picture',placeholderIndex:10,position:{left:72,top:233,width:688,height:387},fill:c.soft,line:{fill:c.muted,width:1,style:'dashed'}});
 pic.text='图片占位\n'+c.imageLabel;pic.text.style={typeface:FONT,fontSize:28,color:c.muted,alignment:'center',verticalAlignment:'middle'};
 text(s,'图文小标题','案例 / 场景名称',819,232,387,65,31,c.accent,true,'body');
 text(s,'场景描述','填写场景背景\n说明对象与关键过程',820,324,384,111,26,c.ink,false,'body');
 text(s,'场景价值','填写成果价值\n说明需要强调的细节',820,471,384,111,26,c.ink,false,'body');
 // 8. Closing page remains a usable content page.
 s=p.slides.add();s.background.fill=c.ink;
 text(s,'结束标题',c.end,74,165,1134,112,64,'#FFFFFF',true,'title');
 text(s,'结束摘要',c.endSub,80,322,1116,70,28,'#FFFFFF',false,'body');
 text(s,'下一步说明','填写最重要的下一步安排',80,438,1100,61,32,'#FFFFFF',false,'body');
 text(s,'联系信息','联系人 / 部门 / 联系方式',80,622,1090,40,20,'#FFFFFF',false,'body');
 const dir=ROOT+'/.build/'+c.id;await fs.mkdir(dir,{recursive:true});
 const candidatePath=dir+'/candidate.pptx';await(await PresentationFile.exportPptx(p)).save(candidatePath);
 const finalPath=ROOT+'/output/'+c.id+'_'+c.name+'_模板.pptx';
 await finalizePresentation({workspaceDir:ROOT,candidatePath,finalPath,pythonExecutable:PY,integrityValidatorPath:SKILL+'/container_tools/inspect_presentation_package_integrity.py',layoutValidatorPath:SKILL+'/container_tools/inspect_presentation_layout_geometry.py',layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-heading-fit','--require-native-table-slide','6'],explicitTotalSlideCount:8,requiredNativeTableOwnerSlides:[6],requiredNativeChartOwnerSlides:[5],materializeLiteralChartWorkbooks:true,fontPolicy:{basis:'design',families:[FONT]},verifyArtifactToolImport:true,receiptPath:dir+'/validation-v2.json'});
 console.log('FINAL '+finalPath);
 const final=await PresentationFile.importPptx(await FileBlob.load(finalPath));
 for(let i=0;i<final.slides.items.length;i++){const sl=final.slides.items[i];const blob=await final.export({slide:sl,format:'png',scale:1});await fs.writeFile(dir+'/slide-'+String(i+1).padStart(2,'0')+'.png',new Uint8Array(await blob.arrayBuffer()));}
 console.log('RENDERED '+c.id);
}
const only=process.argv[2];
for(const c of configs)if(!only||c.id===only)await build(c);
