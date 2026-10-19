const vm = require('node:vm'), fs=require('node:fs'), assert=require('node:assert/strict');
function element(){return {style:{},children:[],value:'',classList:{toggle(){}},appendChild(x){this.children.push(x)},addEventListener(event,fn){this[event]=fn},querySelector(){return element()},set innerHTML(v){this.html=v},get innerHTML(){return this.html}}}
const nodes=new Map();const context=vm.createContext({document:{getElementById(id){if(!nodes.has(id))nodes.set(id,element());return nodes.get(id)},createElement:element},klinecharts:{getSupportedIndicators(){return ['MA','VOL','RSI']}},setTimeout(fn){fn();return 1},clearTimeout(){}});
vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),context);
vm.runInContext(`
const operations=[];
const mock={removeIndicator(f){operations.push(['remove',f.id])},createIndicator(c){operations.push(['create',c.name,c.paneId]);return c.name+'_id'},setStyles(s){operations.push(['style',s.candle.type])}};
charts.push({chart:mock,indicators:new Map()});
applyAll();
if(operations.length!==2)throw Error('initial indicators');
selected.delete('VOL');selected.add('RSI');applyAll();
if(JSON.stringify(operations.slice(2))!==JSON.stringify([['remove','VOL_id'],['create','RSI','indicator_RSI']]))throw Error('indicator delta');
document.getElementById('chart-type').change({target:{value:'candle_stroke'}});
if(operations.at(-1)[1]!=='candle_stroke')throw Error('chart style');
`,context);
console.log('PASS: indicator changes preserve existing MA, remove VOL, add RSI, and style selection updates chart');

vm.runInContext(`
let period, symbol, scroll, zoom;
const subscribed=[];
klinecharts.init=()=>({setPeriod(p){period=p},setSymbol(s){symbol=s},setTimezone(){},setScrollEnabled(v){scroll=v},setZoomEnabled(v){zoom=v},setDataLoader(){},getBarSpace(){return {bar:6}},subscribeAction(a){subscribed.push(a)}});
createChart({code:'CU.SHF',label:'沪铜',candles:[]});
if(period.type!=='day'||period.span!==1)throw Error('daily period must be one day');
if(symbol.ticker!=='CU.SHF')throw Error('missing symbol ticker');
if(!scroll||!zoom)throw Error('chart interaction disabled');
if(subscribed.join(',')!=='onScroll,onZoom')throw Error('layout must not trigger linked scrolling');
`,context);
console.log('PASS: daily period, ticker, drag/zoom enabled, linked interaction events');
