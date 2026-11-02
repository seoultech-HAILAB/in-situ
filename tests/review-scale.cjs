const {readFileSync}=require('node:fs');
const assert=require('node:assert/strict');
const {test}=require('node:test');
const ts=require('typescript');
const exportsObject={};
new Function('require','exports',ts.transpileModule(readFileSync('src/useReviewScale.ts','utf8'),{
  compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText)(require,exportsObject);
const {laptopReviewScale}=exportsObject;
const laptop={screenWidth:1366,screenHeight:768,viewportWidth:1366,outerWidth:1366,finePointer:true};

test('laptop-sized PC screens use 67%, including Full HD laptops',()=>{
  assert.equal(laptopReviewScale(laptop),.67);
  assert.equal(laptopReviewScale({...laptop,screenWidth:1920,screenHeight:1080,viewportWidth:1920,outerWidth:1920}),.67);
  assert.equal(laptopReviewScale({...laptop,screenWidth:1920,screenHeight:1200}),.67);
});
test('manual browser reduction and accessibility enlargement are not multiplied',()=>{
  assert.equal(laptopReviewScale({...laptop,viewportWidth:2039}),1);
  assert.equal(laptopReviewScale({...laptop,viewportWidth:1093}),1);
  assert.equal(laptopReviewScale({...laptop,outerWidth:1382}),.67);
});
test('large monitors, touch devices and narrow windows stay at normal size',()=>{
  assert.equal(laptopReviewScale({...laptop,screenWidth:2560,screenHeight:1440}),1);
  assert.equal(laptopReviewScale({...laptop,finePointer:false}),1);
  assert.equal(laptopReviewScale({...laptop,viewportWidth:800,outerWidth:800}),1);
  assert.equal(laptopReviewScale({...laptop,screenWidth:0}),1);
});
