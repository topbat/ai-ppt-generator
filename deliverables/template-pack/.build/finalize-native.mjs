import fs from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import {PresentationFile,FileBlob} from '@oai/artifact-tool';
import {GlobalFonts} from '@napi-rs/canvas';
GlobalFonts.registerFromPath('C:/Windows/Fonts/msyh.ttc');
GlobalFonts.registerFromPath('C:/Windows/Fonts/msyhbd.ttc');
const ROOT='D:/xstarclaw/retry-ppt/main-ppt/deliverables/template-pack';
const SKILL='D:/CodexData/plugins/cache/openai-primary-runtime/presentations/26.904.11930/skills/presentations';
const {finalizePresentation}=await import(pathToFileURL(SKILL+'/container_tools/artifact_tool_utils.mjs'));
for(const name of (await fs.readdir(ROOT+'/output')).filter(n=>n.endsWith('_模板.pptx'))){
 const id=name.slice(0,2),dir=ROOT+'/.build/'+id,finalPath=ROOT+'/output/'+name.replace('_模板.pptx','_填充模板.pptx');
 await finalizePresentation({workspaceDir:ROOT,candidatePath:dir+'/candidate-native.pptx',finalPath,pythonExecutable:'C:/Users/HQ/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe',integrityValidatorPath:SKILL+'/container_tools/inspect_presentation_package_integrity.py',layoutValidatorPath:SKILL+'/container_tools/inspect_presentation_layout_geometry.py',layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-heading-fit','--require-native-table-slide','6'],explicitTotalSlideCount:8,requiredNativeTableOwnerSlides:[6],requiredNativeChartOwnerSlides:[5],fontPolicy:{basis:'design',families:['Microsoft YaHei']},verifyArtifactToolImport:true,receiptPath:dir+'/validation-native-v2.json'});
 const p=await PresentationFile.importPptx(await FileBlob.load(finalPath));
 for(let i=0;i<p.slides.items.length;i++){const blob=await p.export({slide:p.slides.items[i],format:'png',scale:1});await fs.writeFile(dir+'/native-'+String(i+1).padStart(2,'0')+'.png',new Uint8Array(await blob.arrayBuffer()));}
 console.log('FINAL_NATIVE '+name);
}
