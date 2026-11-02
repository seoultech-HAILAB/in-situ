const {readFileSync}=require('node:fs');
const assert=require('node:assert/strict');
const {test}=require('node:test');
const React=require('react');
const {renderToStaticMarkup}=require('react-dom/server');
const ts=require('typescript');
const exportsObject={};
new Function('require','exports',ts.transpileModule(readFileSync('src/PrototypeEntry.tsx','utf8'),{
  compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText)(require,exportsObject);

test('prototype entry offers only two conditions and no natural-language task input',()=>{
  for(const condition of ['ex','in-situ']){
    const html=renderToStaticMarkup(React.createElement(exportsObject.PrototypeEntry,{
      busy:false,condition,onCondition:()=>{},onExample:()=>{},onStart:()=>{},
      children:[React.createElement('textarea',{key:'input','aria-label':'Input'}),React.createElement('textarea',{key:'target','aria-label':'Target'})]}));
    assert.equal((html.match(/<textarea/g)||[]).length,2);
    assert.equal((html.match(/aria-pressed=/g)||[]).length,2);
    assert.ok(html.includes('조건 1 · Ex-situ')&&html.includes('조건 2 · In-situ'));
    assert.ok(html.includes('본실험 과제로 선정된 자료가 아닙니다'));
    assert.ok(!html.includes('요구사항')&&!html.includes('B2'));
    assert.ok(!html.includes('disabled=""'));
  }
});
