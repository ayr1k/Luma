// Run with: node --test tests/test_ui_lifecycle.cjs
// Execute the actual deletion controller with a minimal DOM, including the
// absence of the obsolete #diffs element that caused the 0.7.5 regression.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../local_agent/ui/index.html'),'utf8');
const source=html.slice(html.indexOf('function clearConversationView(){'),html.indexOf('async function projects()'));
function harness({active=true,allow=true,failDelete=false,failReload=false,rows=1}={}){
 const elements=new Map();
 const get=id=>{if(id==='diffs')return null;if(!elements.has(id))elements.set(id,{textContent:'stale',value:'draft',replaceChildren(...v){this.children=v;}});return elements.get(id);};
 const target={id:'deleted',name:'test'},other={id:'other',name:'other'};
 const state={project:active?target:other,session:{status:'completed'},activeTask:null,cancelWanted:false,
  selectedPlugins:['plugin'],selectedSkills:['skill'],draftAttachments:[{}],contextInfo:{},reviewData:{},reviewDetail:{},reviewProject:'deleted',reviewPath:'a',reviewPicked:new Set(['a']),
  draftDirty:true,tab:'changes',projectRows:rows===1?[target]:[target,other],projectMenuItem:target,pendingNavigation:'deleted',
  conversationDrafts:new Map([['deleted',{}],['other',{}]]),draftSignatures:new Map([['deleted','x']]),
  confirmDeletion:async()=>allow,
  window:{pywebview:{api:{request:async()=>({ok:!failDelete,error:'delete failed'})}}},
  document:{querySelectorAll:()=>[]},$:get,Option:function(text,value){this.text=text;this.value=value;},
  renderPluginChips(){},renderSkillChips(){},renderAttachments(){},showFilePlaceholder(){},render(){},
  renderProjects(){},projects:async()=>{if(failReload)throw Error('offline');},
 };
 vm.createContext(state);vm.runInContext(source,state);
 return {state,get,target,run:()=>state.deleteConversation(target)};
}
test('deleting the last active conversation clears all stale views without #diffs',async()=>{
 const h=harness();await h.run();assert.equal(h.state.project,null);assert.equal(h.state.session,null);assert.equal(h.state.projectRows.length,0);assert.equal(h.state.reviewData,null);assert.equal(h.state.draftDirty,false);assert.equal(h.get('prompt').value,'');assert.equal(h.state.conversationDrafts.has('deleted'),false);assert.equal(h.state.pendingNavigation,null);assert.equal(h.get('notice').textContent,'对话已删除，项目文件已保留。');
});
test('confirmed deletion stays removed if the subsequent list reload fails',async()=>{
 const h=harness({failReload:true});await assert.rejects(h.run(),/offline/);assert.equal(h.state.projectRows.length,0);assert.equal(h.state.project,null);
});
test('deleting an inactive conversation preserves the current conversation and draft',async()=>{
 const h=harness({active:false,rows:2});await h.run();assert.equal(h.state.project.id,'other');assert.equal(h.get('prompt').value,'draft');assert.deepEqual(h.state.projectRows.map(r=>r.id),['other']);assert.equal(h.state.conversationDrafts.has('other'),true);
});
test('cancelling deletion leaves state untouched',async()=>{
 const h=harness({allow:false});await h.run();assert.equal(h.state.project.id,'deleted');assert.equal(h.state.projectRows.length,1);
});
test('failed server deletion leaves the conversation available',async()=>{
 const h=harness({failDelete:true});await assert.rejects(h.run(),/delete failed/);assert.equal(h.state.project.id,'deleted');assert.equal(h.state.projectRows.length,1);
});
