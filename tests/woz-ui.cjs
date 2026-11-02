const {readFileSync}=require('node:fs');
const assert=require('node:assert/strict');
const {test}=require('node:test');
const React=require('react');
const {renderToStaticMarkup}=require('react-dom/server');
const ts=require('typescript');
const cache={};
function localRequire(path){
  if(!path.startsWith('.'))return require(path);
  const filename='src/'+path.replace(/^\.\//,'')+(path==='./WozEntry'?'.tsx':'.ts');
  if(cache[filename])return cache[filename];
  const exports={};cache[filename]=exports;
  new Function('require','exports',ts.transpileModule(readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText)(localRequire,exports);
  return exports;
}
test('frozen entry selects a task without exposing task descriptions or code origin to participants',()=>{
  const {WozEntry}=localRequire('./WozEntry');
  const props={tasks:[{id:'frozen',title:'예제',description:'SECRET',initial_origin:'authored_mock'}],taskId:'frozen',busy:false,loading:false,condition:'in-situ',researcher:false,onChoose(){},onCondition(){},onStart(){}};
  const html=renderToStaticMarkup(React.createElement(WozEntry,props));
  assert.ok(html.includes('검수 과제')&&html.includes('변환 시작'));
  assert.ok(!html.includes('SECRET')&&!html.includes('authored_mock')&&!html.includes('LLM 코드·Step 생성'));
  assert.ok(renderToStaticMarkup(React.createElement(WozEntry,{...props,researcher:true})).includes('authored_mock'));
  assert.ok(renderToStaticMarkup(React.createElement(WozEntry,{...props,taskId:''})).includes('disabled=""'));
});
