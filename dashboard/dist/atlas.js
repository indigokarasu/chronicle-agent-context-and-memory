(()=>{var JS=Object.create;var Wa=Object.defineProperty;var eP=Object.getOwnPropertyDescriptor;var tP=Object.getOwnPropertyNames;var rP=Object.getPrototypeOf,nP=Object.prototype.hasOwnProperty;var iP=(r,e,t)=>e in r?Wa(r,e,{enumerable:!0,configurable:!0,writable:!0,value:t}):r[e]=t;var b=(r,e,t)=>()=>{if(t)throw t[0];try{return r&&(e=r(r=0)),e}catch(n){throw t=[n],n}};var oP=(r,e)=>()=>{try{return e||r((e={exports:{}}).exports,e),e.exports}catch(t){throw e=0,t}},cr=(r,e)=>{for(var t in e)Wa(r,t,{get:e[t],enumerable:!0})},sP=(r,e,t,n)=>{if(e&&typeof e=="object"||typeof e=="function")for(let i of tP(e))!nP.call(r,i)&&i!==t&&Wa(r,i,{get:()=>e[i],enumerable:!(n=eP(e,i))||n.enumerable});return r};var aP=(r,e,t)=>(t=r!=null?JS(rP(r)):{},sP(e||!r||!r.__esModule?Wa(t,"default",{value:r,enumerable:!0}):t,r));var d=(r,e,t)=>iP(r,typeof e!="symbol"?e+"":e,t);var bo,gP,qa,yP,Zg,Rf=b(()=>{bo=globalThis,gP=globalThis.document||{},qa=globalThis.process||{},yP=globalThis.console,Zg=globalThis.navigator||{}});function Xa(r){if(typeof window<"u"&&window.process?.type==="renderer"||typeof process<"u"&&process.versions?.electron)return!0;let e=typeof navigator<"u"&&navigator.userAgent,t=r||e;return!!(t&&t.indexOf("Electron")>=0)}var Bf=b(()=>{});function Je(){return!(typeof process=="object"&&String(process)==="[object process]"&&!process?.browser)||Xa()}var Of=b(()=>{Bf()});function kf(r){return!r&&!Je()?"Node":Xa(r)?"Electron":(r||Zg.userAgent||"").indexOf("Edge")>-1?"Edge":globalThis.chrome?"Chrome":globalThis.safari?"Safari":globalThis.mozInnerScreenX?"Firefox":"Unknown"}var Kg=b(()=>{Of();Bf();Rf()});var Df,on=b(()=>{Rf();Of();Kg();Df="4.1.2"});function ti(r,e){if(!r)throw new Error(e||"Assertion failed")}var Nf=b(()=>{});function Ff(r){if(!r)return 0;let e;switch(typeof r){case"number":e=r;break;case"object":e=r.logLevel||r.priority||0;break;default:return 0}return ti(Number.isFinite(e)&&e>=0),e}function Qg(r){let{logLevel:e,message:t}=r;r.logLevel=Ff(e);let n=r.args?Array.from(r.args):[];for(;n.length&&n.shift()!==t;);switch(typeof e){case"string":case"function":t!==void 0&&n.unshift(t),r.message=e;break;case"object":Object.assign(r,e);break;default:}typeof r.message=="function"&&(r.message=r.message());let i=typeof r.message;return ti(i==="string"||i==="object"),Object.assign(r,{args:n},r.opts)}var Jg=b(()=>{Nf()});var sn,Za,ey=b(()=>{Jg();sn=()=>{},Za=class{constructor({level:e=0}={}){this.userData={},this._onceCache=new Set,this._level=e}set level(e){this.setLevel(e)}get level(){return this.getLevel()}setLevel(e){return this._level=e,this}getLevel(){return this._level}warn(e,...t){return this._log("warn",0,e,t,{once:!0})}error(e,...t){return this._log("error",0,e,t)}log(e,t,...n){return this._log("log",e,t,n)}info(e,t,...n){return this._log("info",e,t,n)}once(e,t,...n){return this._log("once",e,t,n,{once:!0})}_log(e,t,n,i,o={}){let s=Qg({logLevel:t,message:n,args:this._buildArgs(t,n,i),opts:o});return this._createLogFunction(e,s,o)}_buildArgs(e,t,n){return[e,t,...n]}_createLogFunction(e,t,n){if(!this._shouldLog(t.logLevel))return sn;let i=this._getOnceTag(n.tag??t.tag??t.message);if((n.once||t.once)&&i!==void 0){if(this._onceCache.has(i))return sn;this._onceCache.add(i)}return this._emit(e,t)}_shouldLog(e){return this.getLevel()>=Ff(e)}_getOnceTag(e){if(e!==void 0)try{return typeof e=="string"?e:String(e)}catch{return}}}});function bP(r){try{let e=window[r],t="__storage_test__";return e.setItem(t,t),e.removeItem(t),e}catch{return null}}var Ka,ty=b(()=>{Ka=class{constructor(e,t,n="sessionStorage"){this.storage=bP(n),this.id=e,this.config=t,this._loadConfiguration()}getConfiguration(){return this.config}setConfiguration(e){if(Object.assign(this.config,e),this.storage){let t=JSON.stringify(this.config);this.storage.setItem(this.id,t)}}_loadConfiguration(){let e={};if(this.storage){let t=this.storage.getItem(this.id);e=t?JSON.parse(t):{}}return Object.assign(this.config,e),this}}});function ry(r){let e;return r<10?e=`${r.toFixed(2)}ms`:r<100?e=`${r.toFixed(1)}ms`:r<1e3?e=`${r.toFixed(0)}ms`:e=`${(r/1e3).toFixed(2)}s`,e}function ny(r,e=8){let t=Math.max(e-r.length,0);return`${" ".repeat(t)}${r}`}var iy=b(()=>{});function oy(r){return typeof r!="string"?r:(r=r.toUpperCase(),Qa[r]||Qa.WHITE)}function sy(r,e,t){return!Je&&typeof r=="string"&&(e&&(r=`\x1B[${oy(e)}m${r}\x1B[39m`),t&&(r=`\x1B[${oy(t)+xP}m${r}\x1B[49m`)),r}var Qa,xP,ay=b(()=>{on();(function(r){r[r.BLACK=30]="BLACK",r[r.RED=31]="RED",r[r.GREEN=32]="GREEN",r[r.YELLOW=33]="YELLOW",r[r.BLUE=34]="BLUE",r[r.MAGENTA=35]="MAGENTA",r[r.CYAN=36]="CYAN",r[r.WHITE=37]="WHITE",r[r.BRIGHT_BLACK=90]="BRIGHT_BLACK",r[r.BRIGHT_RED=91]="BRIGHT_RED",r[r.BRIGHT_GREEN=92]="BRIGHT_GREEN",r[r.BRIGHT_YELLOW=93]="BRIGHT_YELLOW",r[r.BRIGHT_BLUE=94]="BRIGHT_BLUE",r[r.BRIGHT_MAGENTA=95]="BRIGHT_MAGENTA",r[r.BRIGHT_CYAN=96]="BRIGHT_CYAN",r[r.BRIGHT_WHITE=97]="BRIGHT_WHITE"})(Qa||(Qa={}));xP=10});function cy(r,e=["constructor"]){let t=Object.getPrototypeOf(r),n=Object.getOwnPropertyNames(t),i=r;for(let o of n){let s=i[o];typeof s=="function"&&(e.find(a=>o===a)||(i[o]=s.bind(r)))}}var ly=b(()=>{});var Ja,Dt,Uf=b(()=>{on();Ja=class{getHighResolutionTimer(){let e;if(Je()&&bo.performance)e=bo?.performance?.now?.();else if("hrtime"in qa){let t=qa?.hrtime?.();e=t[0]*1e3+t[1]/1e6}else e=Date.now();return e}getMemoryUsageMB(){let t=bo?.performance?.memory?.usedJSHeapSize;return t==null?null:Math.trunc(t/1024/1024)}},Dt=new Ja;globalThis.Probe=Ja;globalThis.probe=Dt});function vP(r,e,t){if(typeof e=="string"){let n=t.time?ny(ry(t.total)):"";e=t.time?`${r}: ${n}  ${e}`:`${r}: ${e}`,e=sy(e,t.color,t.background)}return e}function wP(r){for(let e in r)for(let t in r[e])return t||"untitled";return"empty"}var ri,Gf,Fe,zf=b(()=>{on();ey();ty();iy();ay();ly();Nf();Uf();ri={debug:Je()&&console.debug||console.log,log:console.log,info:console.info,warn:console.warn,error:console.error},Gf={enabled:!0,level:0},Fe=class extends Za{constructor({id:e}={id:""}){super({level:0}),this.VERSION=Df,this._startTs=Dt.getHighResolutionTimer(),this._deltaTs=Dt.getHighResolutionTimer(),this.userData={},this.LOG_THROTTLE_TIMEOUT=0,this.id=e,this.userData={},this._storage=new Ka(`__probe-${this.id}__`,{[this.id]:Gf}),this.timeStamp(`${this.id} started`),cy(this),Object.seal(this)}isEnabled(){return this._getConfiguration().enabled}getLevel(){return this._getConfiguration().level}getTotal(){return Number((Dt.getHighResolutionTimer()-this._startTs).toPrecision(10))}getDelta(){return Number((Dt.getHighResolutionTimer()-this._deltaTs).toPrecision(10))}set priority(e){this.level=e}get priority(){return this.level}getPriority(){return this.level}enable(e=!0){return this._updateConfiguration({enabled:e}),this}setLevel(e){return this._updateConfiguration({level:e}),this}get(e){return this._getConfiguration()[e]}set(e,t){this._updateConfiguration({[e]:t})}settings(){console.table?console.table(this._storage.config):console.log(this._storage.config)}assert(e,t){if(!e)throw new Error(t||"Assertion failed")}warn(e,...t){return this._log("warn",0,e,t,{method:ri.warn,once:!0})}error(e,...t){return this._log("error",0,e,t,{method:ri.error})}deprecated(e,t){return this.warn(`\`${e}\` is deprecated and will be removed in a later version. Use \`${t}\` instead`)}removed(e,t){return this.error(`\`${e}\` has been removed. Use \`${t}\` instead`)}probe(e,t,...n){let i=Dt.getMemoryUsageMB();if(i!==null){let o=`${i}MB `;typeof t=="function"?t=()=>`${o}${t()}`:typeof t=="string"&&(t=`${o}${t}`)}return this._log("log",e,t,n,{method:ri.log,time:!0,once:!0})}log(e,t,...n){return this._log("log",e,t,n,{method:ri.debug})}info(e,t,...n){return this._log("info",e,t,n,{method:console.info})}once(e,t,...n){return this._log("once",e,t,n,{method:ri.debug||ri.info,once:!0})}table(e,t,n){return t?this._log("table",e,t,n&&[n]||[],{method:console.table||sn,tag:wP(t)}):sn}time(e,t){return this._log("time",e,t,[],{method:console.time?console.time:console.info})}timeEnd(e,t){return this._log("time",e,t,[],{method:console.timeEnd?console.timeEnd:console.info})}timeStamp(e,t){return this._log("time",e,t,[],{method:console.timeStamp||sn})}group(e,t,n={collapsed:!1}){let i=(n.collapsed?console.groupCollapsed:console.group)||console.info;return this._log("group",e,t,[],{method:i})}groupCollapsed(e,t,n={}){return this.group(e,t,Object.assign({},n,{collapsed:!0}))}groupEnd(e){return this._log("groupEnd",e,"",[],{method:console.groupEnd||sn})}withGroup(e,t,n){this.group(e,t)();try{n()}finally{this.groupEnd(e)()}}trace(){console.trace&&console.trace()}_shouldLog(e){return this.isEnabled()&&super._shouldLog(e)}_emit(e,t){let n=t.method;ti(n),t.total=this.getTotal(),t.delta=this.getDelta(),this._deltaTs=Dt.getHighResolutionTimer();let i=vP(this.id,t.message,t);return n.bind(console,i,...t.args)}_getConfiguration(){return this._storage.config[this.id]||this._updateConfiguration(Gf),this._storage.config[this.id]}_updateConfiguration(e){let t=this._storage.config[this.id]||{...Gf};this._storage.setConfiguration({[this.id]:{...t,...e}})}};Fe.VERSION=Df});var uy=b(()=>{Uf();globalThis.probe||(globalThis.probe=Dt)});var fF,xo=b(()=>{zf();zf();uy();fF=new Fe({id:"@probe.gl/log"})});function So(){let r;if(typeof window<"u"&&window.performance)r=window.performance.now();else if(typeof process<"u"&&process.hrtime){let e=process.hrtime();r=e[0]*1e3+e[1]/1e6}else r=Date.now();return r}var id=b(()=>{});var cn,od=b(()=>{id();cn=class{constructor(e,t){this.sampleSize=1,this.time=0,this.count=0,this.samples=0,this.lastTiming=0,this.lastSampleTime=0,this.lastSampleCount=0,this._count=0,this._time=0,this._samples=0,this._startTime=0,this._timerPending=!1,this.name=e,this.type=t,this.reset()}reset(){return this.time=0,this.count=0,this.samples=0,this.lastTiming=0,this.lastSampleTime=0,this.lastSampleCount=0,this._count=0,this._time=0,this._samples=0,this._startTime=0,this._timerPending=!1,this}setSampleSize(e){return this.sampleSize=e,this}incrementCount(){return this.addCount(1),this}decrementCount(){return this.subtractCount(1),this}addCount(e){return this._count+=e,this._samples++,this._checkSampling(),this}subtractCount(e){return this._count-=e,this._samples++,this._checkSampling(),this}addTime(e){return this._time+=e,this.lastTiming=e,this._samples++,this._checkSampling(),this}timeStart(){return this._startTime=So(),this._timerPending=!0,this}timeEnd(){return this._timerPending?(this.addTime(So()-this._startTime),this._timerPending=!1,this._checkSampling(),this):this}getSampleAverageCount(){return this.sampleSize>0?this.lastSampleCount/this.sampleSize:0}getSampleAverageTime(){return this.sampleSize>0?this.lastSampleTime/this.sampleSize:0}getSampleHz(){return this.lastSampleTime>0?this.sampleSize/(this.lastSampleTime/1e3):0}getAverageCount(){return this.samples>0?this.count/this.samples:0}getAverageTime(){return this.samples>0?this.time/this.samples:0}getHz(){return this.time>0?this.samples/(this.time/1e3):0}_checkSampling(){this._samples===this.sampleSize&&(this.lastSampleTime=this._time,this.lastSampleCount=this._count,this.count+=this._count,this.time+=this._time,this.samples+=this._samples,this._time=0,this._count=0,this._samples=0)}}});var lt,Ey=b(()=>{od();lt=class{constructor(e){this.stats={},this.id=e.id,this.stats={},this._initializeStats(e.stats),Object.seal(this)}get(e,t="count"){return this._getOrCreate({name:e,type:t})}get size(){return Object.keys(this.stats).length}reset(){for(let e of Object.values(this.stats))e.reset();return this}forEach(e){for(let t of Object.values(this.stats))e(t)}getTable(){let e={};return this.forEach(t=>{e[t.name]={time:t.time||0,count:t.count||0,average:t.getAverageTime()||0,hz:t.getHz()||0}}),e}_initializeStats(e=[]){e.forEach(t=>this._getOrCreate(t))}_getOrCreate(e){let{name:t,type:n}=e,i=this.stats[t];return i||(e instanceof cn?i=e:i=new cn(t,n),this.stats[t]=i),i}}});var Po=b(()=>{Ey();od();id()});function Jy(r){return ArrayBuffer.isView(r)&&!(r instanceof DataView)}function e_(r){return Array.isArray(r)?r.length===0||typeof r[0]=="number":!1}function Ro(r){return Jy(r)||e_(r)}var t_=b(()=>{});var bd=b(()=>{t_()});function li(r){let e=r.split(""),t=0,n=0,i=!1,o=!1,s=!1;for(;t<r.length;){let a=r[t],c=r[t+1];if(o){s?s=!1:a==="\\"?s=!0:a==='"'&&(o=!1),t++;continue}if(i){a===`
`||a==="\r"?i=!1:e[t]=" ",t++;continue}if(n>0){if(a==="/"&&c==="*"){e[t]=" ",e[t+1]=" ",n++,t+=2;continue}if(a==="*"&&c==="/"){e[t]=" ",e[t+1]=" ",n--,t+=2;continue}a!==`
`&&a!=="\r"&&(e[t]=" "),t++;continue}if(a==='"'){o=!0,t++;continue}if(a==="/"&&c==="/"){e[t]=" ",e[t+1]=" ",i=!0,t+=2;continue}if(a==="/"&&c==="*"){e[t]=" ",e[t+1]=" ",n=1,t+=2;continue}t++}return e.join("")}function un(r,e){let t=li(r),n=[];for(let i of e){i.lastIndex=0;let o;for(o=i.exec(t);o;){let s=i===e[0],a=o.index,c=o[0].length;n.push({match:r.slice(a,a+c),index:a,length:c,bindingToken:o[s?1:2],groupToken:o[s?2:1],accessDeclaration:o[3]?.trim(),name:o[4]}),o=i.exec(t)}}return n.sort((i,o)=>i.index-o.index)}function Ld(r,e,t){let n=un(r,e);if(!n.length)return r;let i="",o=0;for(let s of n)i+=r.slice(o,s.index),i+=t(s),o=s.index+s.length;return i+=r.slice(o),i}function Ad(r){return/@binding\(\s*auto\s*\)/.test(li(r))}function y_(r,e){return un(r,e===ci||e===hc?W3:e).find(n=>n.bindingToken==="auto")}var rt,ci,hc,g_,W3,pc=b(()=>{rt="(?:var<\\s*(uniform|storage(?:\\s*,\\s*[A-Za-z_][A-Za-z0-9_]*)?)\\s*>|var)\\s+([A-Za-z_][A-Za-z0-9_]*)",ci=[new RegExp(`@binding\\(\\s*(auto|\\d+)\\s*\\)\\s*@group\\(\\s*(\\d+)\\s*\\)\\s*${rt}`,"g"),new RegExp(`@group\\(\\s*(\\d+)\\s*\\)\\s*@binding\\(\\s*(auto|\\d+)\\s*\\)\\s*${rt}`,"g")],hc=[new RegExp(`@binding\\(\\s*(auto|\\d+)\\s*\\)\\s*@group\\(\\s*(\\d+)\\s*\\)\\s*${rt}`,"g"),new RegExp(`@group\\(\\s*(\\d+)\\s*\\)\\s*@binding\\(\\s*(auto|\\d+)\\s*\\)\\s*${rt}`,"g")],g_=[new RegExp(`@binding\\(\\s*(\\d+)\\s*\\)\\s*@group\\(\\s*(\\d+)\\s*\\)\\s*${rt}`,"g"),new RegExp(`@group\\(\\s*(\\d+)\\s*\\)\\s*@binding\\(\\s*(\\d+)\\s*\\)\\s*${rt}`,"g")],W3=[new RegExp(`@binding\\(\\s*(auto)\\s*\\)\\s*@group\\(\\s*(\\d+)\\s*\\)\\s*${rt}`,"g"),new RegExp(`@group\\(\\s*(\\d+)\\s*\\)\\s*@binding\\(\\s*(auto)\\s*\\)\\s*${rt}`,"g"),new RegExp(`@binding\\(\\s*(auto)\\s*\\)\\s*@group\\(\\s*(\\d+)\\s*\\)(?:[\\s\\n\\r]*@[A-Za-z_][^\\n\\r]*)*[\\s\\n\\r]*${rt}`,"g"),new RegExp(`@group\\(\\s*(\\d+)\\s*\\)\\s*@binding\\(\\s*(auto)\\s*\\)(?:[\\s\\n\\r]*@[A-Za-z_][^\\n\\r]*)*[\\s\\n\\r]*${rt}`,"g")]});function gc(r,e={}){let t=__(r),n=j3(t);if(!n)return null;let i=H3(t,n);if(!i)return null;let o=q3(t,n,i);if(!o)return null;if(e.scanVertexAttributes===!1)return{attributes:[],bindings:o};let s=Y3(t,n);if(!s)return null;let a=J3(t,n,i,s,e.vertexEntryPoint);return a?{attributes:a,bindings:o}:null}function __(r){let e=li(r),t=/[A-Za-z_][A-Za-z0-9_]*|(?:0[xX][0-9A-Fa-f]+|\d+)|[@(){}<>\[\]:,;=]/g,n=[],i=t.exec(e);for(;i;)n.push({value:i[0],index:i.index}),i=t.exec(e);return n}function j3(r){let e=[],t=0;for(let n of r){if(n.value==="}"&&t===0)return null;e.push(t),n.value==="{"?t++:n.value==="}"&&t--}return t===0?e:null}function H3(r,e){let t=new Map;for(let n=0;n<r.length;n++){if(e[n]!==0||r[n].value!=="alias")continue;let i=r[n+1]?.value;if(!Do(i)||r[n+2]?.value!=="="||t.has(i))return null;let o=v_(r,e,n+3,";");if(o<0||o===n+3)return null;t.set(i,mc(r.slice(n+3,o))),n=o}return t}function Y3(r,e){let t=new Map;for(let n=0;n<r.length;n++){if(e[n]!==0||r[n].value!=="struct")continue;let i=r[n+1]?.value,o=n+2;if(!Do(i)||t.has(i)||r[o]?.value!=="{")return null;let s=Rd(r,o,"{","}");if(s<0)return null;t.set(i,r.slice(o+1,s)),n=s}return t}function q3(r,e,t){let n=[],i=new Set,o=new Set;for(let s=0;s<r.length;s++){if(e[s]!==0||r[s].value!=="var")continue;let a=w_(r,e,s),c=r.slice(a,s),l=Cd(c,"group"),u=Cd(c,"binding");if(l===null||u===null||l===void 0!=(u===void 0))return null;if(l===void 0||u===void 0)continue;let f=s+1,h=[];if(r[f]?.value==="<"){let v=Rd(r,f,"<",">");if(v<0)return null;let _=yc(r.slice(f+1,v),",");if(!_)return null;h=_.map(mc),f=v+1}let p=r[f]?.value;if(!Do(p)||r[f+1]?.value!==":")return null;let m=v_(r,e,f+2,";");if(m<0||m===f+2)return null;let g=Id(mc(r.slice(f+2,m)),t);if(!g)return null;let y=X3({name:p,group:l,location:u,addressSpace:h,resourceType:g}),x=`${l}:${u}`;if(!y||i.has(x)||o.has(p))return null;n.push(y),i.add(x),o.add(p),s=m}return Q3(n),n.sort((s,a)=>s.group-a.group||s.location-a.location||s.name.localeCompare(a.name))}function X3(r){let{name:e,group:t,location:n,addressSpace:i,resourceType:o}=r,s={name:e,group:t,location:n};if(i[0]==="uniform"&&i.length===1)return{...s,type:"uniform"};if(i[0]==="storage"&&i.length<=2){let a=i[1]||"read";return a==="read"?{...s,type:"read-only-storage"}:a==="read_write"?{...s,type:"storage"}:null}return i.length>0?null:o==="sampler"||o==="sampler_comparison"?{...s,type:"sampler",...o==="sampler_comparison"?{samplerType:"comparison"}:{}}:o==="texture_external"?{...s,type:"external-texture"}:Z3(s,o)||K3(s,o)}function Z3(r,e){let t=/^texture_storage_(1d|2d|2d_array|3d)<([A-Za-z0-9_]+),(read|write|read_write)>$/.exec(e);if(!t)return null;let n={read:"read-only",write:"write-only",read_write:"read-write"}[t[3]];return{...r,type:"storage",format:t[2],access:n,viewDimension:Md(t[1])}}function K3(r,e){let t=/^texture_(multisampled_)?(1d|2d|2d_array|cube|cube_array|3d)<(f32|i32|u32)>$/.exec(e);if(t){if(t[1]&&t[2]!=="2d")return null;let i={f32:"float",i32:"sint",u32:"uint"}[t[3]];return{...r,type:"texture",viewDimension:Md(t[2]),sampleType:i,multisampled:!!t[1]}}let n=/^texture_depth_(multisampled_)?(2d|2d_array|cube|cube_array)$/.exec(e);return!n||n[1]&&n[2]!=="2d"?null:{...r,type:"texture",viewDimension:Md(n[2]),sampleType:"depth",multisampled:!!n[1]}}function Q3(r){for(let e of r){if(e.type!=="sampler"||e.samplerType||!e.name.endsWith("Sampler"))continue;let t=e.name.slice(0,-7);r.find(i=>i.type==="texture"&&i.name===t&&i.group===e.group)?.sampleType==="depth"&&(e.samplerType="non-filtering")}}function J3(r,e,t,n,i){let o=eT(r,e);if(!o)return null;let s=o.filter(p=>p.vertex),a=i?s.find(p=>p.name===i):s.length===1?s[0]:void 0;if(!a)return s.length===0&&!i?[]:null;let c=yc(a.parameters,",");if(!c)return null;let l=[],u=new Set,f=new Set,h=new Set;for(let p of c)if(p.length>0&&!b_({declaration:p,aliases:t,structures:n,attributes:l,attributeLocations:u,attributeNames:f,visitedStructures:h}))return null;return l.sort((p,m)=>p.location-m.location||p.name.localeCompare(m.name))}function eT(r,e){let t=[],n=new Set;for(let i=0;i<r.length;i++){if(e[i]!==0||r[i].value!=="fn")continue;let o=r[i+1]?.value,s=i+2;if(!Do(o)||n.has(o)||r[s]?.value!=="(")return null;let a=Rd(r,s,"(",")");if(a<0)return null;let c=w_(r,e,i);t.push({name:o,vertex:x_(r.slice(c,i),"vertex"),parameters:r.slice(s+1,a)}),n.add(o),i=a}return t}function b_(r){let{declaration:e,aliases:t,structures:n,attributes:i,attributeLocations:o,attributeNames:s,visitedStructures:a}=r,c=nT(e,":");if(c<1||c===e.length-1)return!1;let l=iT(e.slice(0,c)),u=Cd(e.slice(0,c),"location"),f=x_(e.slice(0,c),"builtin"),h=Id(mc(e.slice(c+1)),t);if(!l||u===null||!h||u!==void 0&&f)return!1;if(u!==void 0){let g=rT(h);return!g||o.has(u)||s.has(l)?!1:(i.push({name:l,location:u,type:g}),o.add(u),s.add(l),!0)}if(f)return!0;let p=n.get(h);if(!p||a.has(h))return!1;let m=yc(p,",");if(!m)return!1;a.add(h);for(let g of m)if(g.length>0&&!b_({...r,declaration:g}))return!1;return a.delete(h),!0}function Id(r,e,t=new Set){let n=__(r),i="";for(let o of n){let s=e.get(o.value);if(!s){i+=tT(o.value);continue}if(t.has(o.value))return null;let a=new Set(t);a.add(o.value);let c=Id(s,e,a);if(!c)return null;i+=c}return i}function tT(r){let e=/^(vec[234]|mat[234]x[234])([fiuh])$/.exec(r);if(!e)return r;let t={f:"f32",i:"i32",u:"u32",h:"f16"}[e[2]];return`${e[1]}<${t}>`}function rT(r){return/^(?:i32|u32|f32|f16|vec[234]<(?:i32|u32|f32|f16)>)$/.test(r)?r:null}function Cd(r,e){let t;for(let n=0;n<r.length;n++)if(!(r[n].value!=="@"||r[n+1]?.value!==e)){if(t!==void 0||r[n+2]?.value!=="("||!/^\d+$/.test(r[n+3]?.value||"")||r[n+4]?.value!==")")return null;t=Number(r[n+3].value)}return t}function x_(r,e){return r.some((t,n)=>t.value==="@"&&r[n+1]?.value===e)}function Md(r){return r.replace("_","-")}function Rd(r,e,t,n){let i=0;for(let o=e;o<r.length;o++)if(r[o].value===t)i++;else if(r[o].value===n&&--i===0)return o;return-1}function yc(r,e){let t=[],n=0,i={"(":0,"<":0,"[":0,"{":0},o=Object.keys(i),s={")":"(",">":"<","]":"[","}":"{"};for(let a=0;a<r.length;a++){let c=r[a].value;if(c===e&&o.every(l=>i[l]===0)){t.push(r.slice(n,a)),n=a+1;continue}if(c in i)i[c]++;else if(c in s){let l=s[c];if(i[l]--,i[l]<0)return null}}return o.every(a=>i[a]===0)?(t.push(r.slice(n)),t):null}function nT(r,e){let t=yc(r,e);return t&&t.length===2?t[0].length:-1}function v_(r,e,t,n){for(let i=t;i<r.length;i++)if(e[i]===0&&r[i].value===n)return i;return-1}function w_(r,e,t){for(let n=t-1;n>=0;n--)if(r[n].value===";"&&e[n]===0||r[n].value==="}"&&e[n]===1)return n+1;return 0}function iT(r){for(let e=r.length-1;e>=0;e--)if(Do(r[e].value))return r[e].value;return null}function mc(r){return r.map(e=>e.value).join("")}function Do(r){return!!(r&&/^[A-Za-z_][A-Za-z0-9_]*$/.test(r))}var Bd=b(()=>{pc()});function dr(r,e){if(!r){let t=new Error(e||"shadertools: assertion failed.");throw Error.captureStackTrace?.(t,dr),t}}var _c=b(()=>{});function S_(r){let e={};for(let[t,n]of Object.entries(r))e[t]=oT(n);return e}function oT(r){let e=E_(r);if(e!=="object")return{value:r,...Od[e],type:e};if(typeof r=="object")return r?r.type!==void 0?{...r,...Od[r.type],type:r.type}:r.value===void 0?{type:"object",value:r}:(e=E_(r.value),{...r,...Od[e],type:e}):{type:"object",value:null};throw new Error("props")}function E_(r){return Array.isArray(r)||ArrayBuffer.isView(r)?"array":typeof r}var Od,P_=b(()=>{Od={number:{type:"number",validate(r,e){return Number.isFinite(r)&&typeof e=="object"&&(e.max===void 0||r<=e.max)&&(e.min===void 0||r>=e.min)}},array:{type:"array",validate(r,e){return Array.isArray(r)||ArrayBuffer.isView(r)}}}});var T_,L_,A_=b(()=>{T_=`#ifdef MODULE_LOGDEPTH
  logdepth_adjustPosition(gl_Position);
#endif
`,L_=`#ifdef MODULE_MATERIAL
  fragColor = material_filterColor(fragColor);
#endif

#ifdef MODULE_LIGHTING
  fragColor = lighting_filterColor(fragColor);
#endif

#ifdef MODULE_FOG
  fragColor = fog_filterColor(fragColor);
#endif

#ifdef MODULE_PICKING
  fragColor = picking_filterHighlightColor(fragColor);
  fragColor = picking_filterPickingColor(fragColor);
#endif

#ifdef MODULE_LOGDEPTH
  logdepth_setFragDepth();
#endif
`});function I_(r){let e={vertex:{},fragment:{}};for(let t in r){let n=r[t],i=aT(t);typeof n=="string"&&(n={order:0,injection:n}),e[i][t]=n}return e}function aT(r){let e=r.slice(0,2);switch(e){case"vs":return"vertex";case"fs":return"fragment";default:throw new Error(e)}}function Fo(r,e,t,n=!1,i="glsl",o={}){let s=e==="vertex";for(let a in t){let c=t[a];c.sort((u,f)=>u.order-f.order),kd.length=c.length;for(let u=0,f=c.length;u<f;++u)kd[u]=c[u].injection;let l=`${kd.join(`
`)}
`;switch(a){case"vs:#decl":(i==="wgsl"||s)&&(r=r.replace(No,l));break;case"vs:#main-start":(i==="wgsl"||s)&&(r=i==="wgsl"?bc(r,"vertex",l,"start",o.vertex):r.replace(C_,u=>u+l));break;case"vs:#main-end":(i==="wgsl"||s)&&(r=i==="wgsl"?bc(r,"vertex",l,"end",o.vertex):r.replace(M_,u=>l+u));break;case"fs:#decl":(i==="wgsl"||!s)&&(r=r.replace(No,l));break;case"fs:#main-start":(i==="wgsl"||!s)&&(r=i==="wgsl"?bc(r,"fragment",l,"start",o.fragment):r.replace(C_,u=>u+l));break;case"fs:#main-end":(i==="wgsl"||!s)&&(r=i==="wgsl"?bc(r,"fragment",l,"end",o.fragment):r.replace(M_,u=>l+u));break;default:r=r.replace(a,u=>u+l)}}return r=r.replace(No,""),n&&(r=r.replace(/\}\s*$/,a=>a+sT[e])),r}function bc(r,e,t,n,i){let o=cT(r,e,i);if(!o)return r;if(n==="start"){let s=o.openBraceIndex+1;return`${r.slice(0,s)}
${t}${r.slice(s)}`}return`${r.slice(0,o.closeBraceIndex)}${t}${r.slice(o.closeBraceIndex)}`}function cT(r,e,t){let n=e==="vertex"?"@vertex":"@fragment",i=r.indexOf(n);if(i<0)return null;let o=t?r.search(new RegExp(`\\bfn\\s+${lT(t)}\\s*\\(`)):r.indexOf("fn",i);if(o<0)return null;let s=r.indexOf("{",o);if(s<0)return null;let a=0;for(let c=s;c<r.length;c++){let l=r[c];if(l==="{")a++;else if(l==="}"&&(a--,a===0))return{openBraceIndex:s,closeBraceIndex:c}}return null}function lT(r){return r.replace(/[.*+?^${}()|[\]\\]/g,"\\$&")}var sT,C_,M_,kd,No,Dd=b(()=>{A_();sT={vertex:T_,fragment:L_},C_=/void\s+main\s*\([^)]*\)\s*\{\n?/,M_=/}\n?[^{}]*$/,kd=[],No="__LUMA_INJECT_DECLARATIONS__"});function ui(r){r.map(e=>uT(e))}function uT(r){if(r.instance)return;ui(r.dependencies||[]);let{propTypes:e={},deprecations:t=[],inject:n={}}=r,i={normalizedInjections:I_(n),parsedDeprecations:fT(t)};e&&(i.propValidators=S_(e)),r.instance=i;let o={};e&&(o=Object.entries(e).reduce((s,[a,c])=>{let l=c?.value;return l&&(s[a]=l),s},{})),r.defaultUniforms={...r.defaultUniforms,...o}}function Nd(r,e,t){r.deprecations?.forEach(n=>{n.regex?.test(e)&&(n.deprecated?t.deprecated(n.old,n.new)():t.removed(n.old,n.new)())})}function fT(r){return r.forEach(e=>{e.type==="function"?e.regex=new RegExp(`\\b${e.old}\\(`):e.regex=new RegExp(`${e.type} ${e.old};`)}),r}var xc=b(()=>{P_();Dd()});function fn(r){ui(r);let e={},t={};R_({modules:r,level:0,moduleMap:e,moduleDepth:t});let n=Object.keys(t).sort((i,o)=>t[o]-t[i]).map(i=>e[i]);return ui(n),n}function R_(r){let{modules:e,level:t,moduleMap:n,moduleDepth:i}=r;if(t>=5)throw new Error("Possible loop in shader dependency graph");for(let o of e)n[o.name]=o,(i[o.name]===void 0||i[o.name]<t)&&(i[o.name]=t);for(let o of e)o.dependencies&&R_({modules:o.dependencies,level:t+1,moduleMap:n,moduleDepth:i})}var Fd=b(()=>{xc()});var T,Ge=b(()=>{xo();T=new Fe({id:"luma.gl"})});function dT(r,e){return r!=null?!!r:e!==void 0?e!=="production":!1}function hT(){return dT(T.get("debug"),pT())}function pT(){let r=globalThis.process;if(r?.env)return r.env.NODE_ENV}var vc,Ud=b(()=>{Ge();vc={id:null,powerPreference:"high-performance",failIfMajorPerformanceCaveat:!1,featureLevel:void 0,optionalFeatures:[],xrCompatible:!1,createCanvasContext:void 0,webgl:{},onError:(r,e)=>{},onResize:(r,e)=>{let[t,n]=r.getDevicePixelSize();T.log(1,`${r} resized => ${t}x${n}px`)()},onPositionChange:(r,e)=>{let[t,n]=r.getPosition();T.log(1,`${r} repositioned => ${t},${n}`)()},onVisibilityChange:r=>T.log(1,`${r} Visibility changed ${r.isVisible}`)(),onDevicePixelRatioChange:(r,e)=>T.log(1,`${r} DPR changed ${e.oldRatio} => ${r.devicePixelRatio}`)(),debug:hT(),debugGPUTime:!1,debugShaders:T.get("debug-shaders")||void 0,debugFramebuffers:!!T.get("debug-framebuffers"),debugFactories:!!T.get("debug-factories"),debugWebGL:!!T.get("debug-webgl"),debugSpectorJS:void 0,debugSpectorJSUrl:void 0,_reuseDevices:!1,_cacheShaders:!0,_destroyShaders:!1,_cachePipelines:!0,_sharePipelines:!0,_destroyPipelines:!1,_initializeFeatures:!0,_disabledFeatures:{"compilation-status-async-webgl":!0},_handle:void 0}});function yT(r,e){let t=r.stats,n=!1;for(let c of e)t[c]||(r.get(c),n=!0);let i=Object.keys(t).length,o=B_.get(r);if(!n&&o?.orderedStatNames===e&&o.statCount===i)return;let s={},a=O_.get(e);a||(a=new Set(e),O_.set(e,a));for(let c of e)t[c]&&(s[c]=t[c]);for(let[c,l]of Object.entries(t))a.has(c)||(s[c]=l);for(let c of Object.keys(t))delete t[c];Object.assign(t,s),B_.set(r,{orderedStatNames:e,statCount:i})}var mT,gT,B_,O_,Gd,wc,zd=b(()=>{Po();mT="GPU Time and Memory",gT=["Adapter","GPU","GPU Type","GPU Backend","Frame Rate","CPU Time","GPU Time","GPU Memory","Buffer Memory","Texture Memory","External Buffer Memory","External Texture Memory","Swap Chain Texture"],B_=new WeakMap,O_=new WeakMap,Gd=class{constructor(){d(this,"stats",new Map)}getStats(e){return this.get(e)}get(e){this.stats.has(e)||this.stats.set(e,new lt({id:e}));let t=this.stats.get(e);return e===mT&&yT(t,gT),t}},wc=new Gd});var _T,k_,Uo,$d,fi,D_=b(()=>{Ud();zd();Ge();_T="set luma.log.level=1 (or higher) to trace rendering",k_="No matching device found. Ensure `@luma.gl/webgl` and/or `@luma.gl/webgpu` modules are imported.",Uo=class Uo{constructor(){d(this,"stats",wc);d(this,"log",T);d(this,"VERSION","9.4.1");d(this,"spector");d(this,"preregisteredAdapters",new Map);if(globalThis.luma){if(globalThis.luma.VERSION!==this.VERSION)throw T.error(`Found luma.gl ${globalThis.luma.VERSION} while initialzing ${this.VERSION}`)(),T.error("'yarn why @luma.gl/core' can help identify the source of the conflict")(),new Error("luma.gl - multiple versions detected: see console log");T.error("This version of luma.gl has already been initialized")()}T.log(1,`${this.VERSION} - ${_T}`)(),globalThis.luma=this}async createDevice(e={}){let t={...Uo.defaultProps,...e},n=this.selectAdapter(t.type,t.adapters);if(!n)throw new Error(k_);return t.waitForPageLoad&&await n.pageLoaded,await n.create(t)}async attachDevice(e,t){let n=this._getTypeFromHandle(e,t.adapters),i=n&&this.selectAdapter(n,t.adapters);if(!i)throw new Error(k_);return await i?.attach?.(e,t)}registerAdapters(e){for(let t of e)this.preregisteredAdapters.set(t.type,t)}getSupportedAdapters(e=[]){let t=this._getAdapterMap(e);return Array.from(t).map(([,n])=>n).filter(n=>n.isSupported?.()).map(n=>n.type)}getBestAvailableAdapterType(e=[]){let t=["webgpu","webgl","null"],n=this._getAdapterMap(e);for(let i of t)if(n.get(i)?.isSupported?.())return i;return null}selectAdapter(e,t=[]){let n=e;e==="best-available"&&(n=this.getBestAvailableAdapterType(t));let i=this._getAdapterMap(t);return n&&i.get(n)||null}enforceWebGL2(e=!0,t=[]){let i=this._getAdapterMap(t).get("webgl");i||T.warn("enforceWebGL2: webgl adapter not found")(),i?.enforceWebGL2?.(e)}setDefaultDeviceProps(e){Object.assign(Uo.defaultProps,e)}_getAdapterMap(e=[]){let t=new Map(this.preregisteredAdapters);for(let n of e)t.set(n.type,n);return t}_getTypeFromHandle(e,t=[]){return e instanceof WebGL2RenderingContext?"webgl":typeof GPUDevice<"u"&&e instanceof GPUDevice||e?.queue?"webgpu":e===null?"null":(e instanceof WebGLRenderingContext?T.warn("WebGL1 is not supported",e)():T.warn("Unknown handle type",e)(),null)}};d(Uo,"defaultProps",{...vc,type:"best-available",adapters:void 0,waitForPageLoad:!0});$d=Uo,fi=new $d});function vT(){return Ec||(xT()||typeof window>"u"?Ec=Promise.resolve():Ec=new Promise(r=>window.addEventListener("load",()=>r()))),Ec}var Go,bT,xT,Ec,N_=b(()=>{on();Go=class{get pageLoaded(){return vT()}},bT=Je()&&typeof document<"u",xT=()=>bT&&document.readyState==="complete",Ec=null});function $t(r="id"){Vd[r]=Vd[r]||1;let e=Vd[r]++;return`${r}-${e}`}var Vd,di=b(()=>{Vd={}});function LT(r,e){let t={...e};for(let n in r)r[n]!==void 0&&(t[n]=r[n]);return t}function V_(r,e){let t=r.stats,n=!1;for(let c of e)t[c]||(r.get(c),n=!0);let i=Object.keys(t).length,o=z_.get(r);if(!n&&o?.orderedStatNames===e&&o.statCount===i)return;let s={},a=$_.get(e);a||(a=new Set(e),$_.set(e,a));for(let c of e)t[c]&&(s[c]=t[c]);for(let[c,l]of Object.entries(t))a.has(c)||(s[c]=l);for(let c of Object.keys(t))delete t[c];Object.assign(t,s),z_.set(r,{orderedStatNames:e,statCount:i})}function W_(r){return r.type==="webgl"?TT:PT}function zo(r){let e=r.userData[wT];return e?.enabled?e:null}function Mr(){return globalThis.performance?.now?.()??Date.now()}function AT(r,e){let t=zo(r);if(!(!t||!t.activeDefaultFramebufferAcquireDepth))switch(t.transientCanvasResourceCreates=(t.transientCanvasResourceCreates||0)+1,e){case"Texture":t.transientCanvasTextureCreates=(t.transientCanvasTextureCreates||0)+1;break;case"TextureView":t.transientCanvasTextureViewCreates=(t.transientCanvasTextureViewCreates||0)+1;break;case"Sampler":t.transientCanvasSamplerCreates=(t.transientCanvasSamplerCreates||0)+1;break;case"Framebuffer":t.transientCanvasFramebufferCreates=(t.transientCanvasFramebufferCreates||0)+1;break;default:break}}function CT(r){let e=Object.getPrototypeOf(r);for(;e;){let t=Object.getPrototypeOf(e);if(!t||t===F.prototype)return MT(e)||r[Symbol.toStringTag]||r.constructor.name;e=t}return r[Symbol.toStringTag]||r.constructor.name}function MT(r){let e=Object.getOwnPropertyDescriptor(r,Symbol.toStringTag);return typeof e?.get=="function"?e.get.call(r):typeof e?.value=="string"?e.value:null}var wT,F_,U_,G_,ET,ST,PT,TT,z_,$_,F,ve=b(()=>{di();wT="cpu-hotspot-profiler",F_="GPU Resource Counts",U_="Resource Counts",G_="GPU Time and Memory",ET=["Resources","Buffers","Textures","Samplers","TextureViews","Framebuffers","QuerySets","Shaders","RenderPipelines","ComputePipelines","PipelineLayouts","VertexArrays","RenderPasss","RenderBundleEncoders","RenderBundles","ComputePasss","CommandEncoders","CommandBuffers"],ST=["Resources","Buffers","Textures","Samplers","TextureViews","Framebuffers","QuerySets","Shaders","RenderPipelines","SharedRenderPipelines","ComputePipelines","PipelineLayouts","VertexArrays","RenderPasss","RenderBundleEncoders","RenderBundles","ComputePasss","CommandEncoders","CommandBuffers"],PT=ET.flatMap(r=>[`${r} Created`,`${r} Active`]),TT=ST.flatMap(r=>[`${r} Created`,`${r} Active`]),z_=new WeakMap,$_=new WeakMap,F=class{constructor(e,t,n){d(this,"id");d(this,"props");d(this,"userData",{});d(this,"_device");d(this,"destroyed",!1);d(this,"allocatedBytes",0);d(this,"allocatedBytesName",null);d(this,"_attachedResources",new Set);if(!e)throw new Error("no device");this._device=e,this.props=LT(t,n);let i=this.props.id!=="undefined"?this.props.id:$t(this[Symbol.toStringTag]);this.props.id=i,this.id=i,this.userData=this.props.userData||{},this.addStats()}toString(){return`${this[Symbol.toStringTag]||this.constructor.name}:"${this.id}"`}toJSON(){return this.toString()}get ownsHandle(){return(this.props.handle===void 0||this.props.handle===null)&&!this.isHandleBorrowed}get isHandleBorrowed(){return!!this.props._isHandleBorrowed}destroy(){this.destroyed||this.destroyResource()}delete(){return this.destroy(),this}getProps(){return this.props}attachResource(e){this._attachedResources.add(e)}detachResource(e){this._attachedResources.delete(e)}destroyAttachedResource(e){this._attachedResources.delete(e)&&e.destroy()}destroyAttachedResources(){for(let e of this._attachedResources)e.destroy();this._attachedResources=new Set}destroyResource(){this.destroyed||(this.destroyAttachedResources(),this.removeStats(),this.destroyed=!0)}removeStats(){let e=zo(this._device),t=e?Mr():0,n=[this._device.statsManager.getStats(F_),this._device.statsManager.getStats(U_)],i=W_(this._device);for(let s of n)V_(s,i);let o=this.getStatsName();for(let s of n)s.get("Resources Active").decrementCount(),s.get(`${o}s Active`).decrementCount();e&&(e.statsBookkeepingCalls=(e.statsBookkeepingCalls||0)+1,e.statsBookkeepingTimeMs=(e.statsBookkeepingTimeMs||0)+(Mr()-t))}trackAllocatedMemory(e,t=this.getStatsName()){let n=zo(this._device),i=n?Mr():0,o=this._device.statsManager.getStats(G_);this.allocatedBytes>0&&this.allocatedBytesName&&(o.get("GPU Memory").subtractCount(this.allocatedBytes),o.get(`${this.allocatedBytesName} Memory`).subtractCount(this.allocatedBytes)),o.get("GPU Memory").addCount(e),o.get(`${t} Memory`).addCount(e),n&&(n.statsBookkeepingCalls=(n.statsBookkeepingCalls||0)+1,n.statsBookkeepingTimeMs=(n.statsBookkeepingTimeMs||0)+(Mr()-i)),this.allocatedBytes=e,this.allocatedBytesName=t}trackReferencedMemory(e,t=this.getStatsName()){this.trackAllocatedMemory(e,`External ${t}`)}trackDeallocatedMemory(e=this.getStatsName()){if(this.allocatedBytes===0){this.allocatedBytesName=null;return}let t=zo(this._device),n=t?Mr():0,i=this._device.statsManager.getStats(G_);i.get("GPU Memory").subtractCount(this.allocatedBytes),i.get(`${this.allocatedBytesName||e} Memory`).subtractCount(this.allocatedBytes),t&&(t.statsBookkeepingCalls=(t.statsBookkeepingCalls||0)+1,t.statsBookkeepingTimeMs=(t.statsBookkeepingTimeMs||0)+(Mr()-n)),this.allocatedBytes=0,this.allocatedBytesName=null}trackDeallocatedReferencedMemory(e=this.getStatsName()){this.trackDeallocatedMemory(`Referenced ${e}`)}addStats(){let e=this.getStatsName(),t=zo(this._device),n=t?Mr():0,i=[this._device.statsManager.getStats(F_),this._device.statsManager.getStats(U_)],o=W_(this._device);for(let s of i)V_(s,o);for(let s of i)s.get("Resources Created").incrementCount(),s.get("Resources Active").incrementCount(),s.get(`${e}s Created`).incrementCount(),s.get(`${e}s Active`).incrementCount();t&&(t.statsBookkeepingCalls=(t.statsBookkeepingCalls||0)+1,t.statsBookkeepingTimeMs=(t.statsBookkeepingTimeMs||0)+(Mr()-n)),AT(this._device,e)}getStatsName(){return CT(this)}};d(F,"defaultProps",{id:"undefined",handle:void 0,_isHandleBorrowed:!1,userData:void 0})});var Pe,z,Sc=b(()=>{ve();Pe=class Pe extends F{constructor(t,n){let i={...n};(n.usage||0)&Pe.INDEX&&!n.indexType&&(n.data instanceof Uint32Array?i.indexType="uint32":n.data instanceof Uint16Array?i.indexType="uint16":n.data instanceof Uint8Array&&(i.indexType="uint8")),delete i.data;super(t,i,Pe.defaultProps);d(this,"usage");d(this,"indexType");d(this,"updateTimestamp");d(this,"debugData",new ArrayBuffer(0));this.usage=i.usage||0,this.indexType=i.indexType,this.updateTimestamp=t.incrementTimestamp()}get[Symbol.toStringTag](){return"Buffer"}clone(t){return this.device.createBuffer({...this.props,...t})}_setDebugData(t,n,i){if(!this.device.props.debug)return;let o=null,s;ArrayBuffer.isView(t)?(o=t,s=t.buffer):s=t;let a=Math.min(t?t.byteLength:i,Pe.DEBUG_DATA_MAX_LENGTH);if(s===null)this.debugData=new ArrayBuffer(a);else{let c=Math.min(o?.byteOffset||0,s.byteLength),l=Math.max(0,s.byteLength-c),u=Math.min(a,l);this.debugData=new Uint8Array(s,c,u).slice().buffer}}};d(Pe,"INDEX",16),d(Pe,"VERTEX",32),d(Pe,"UNIFORM",64),d(Pe,"STORAGE",128),d(Pe,"INDIRECT",256),d(Pe,"QUERY_RESOLVE",512),d(Pe,"MAP_READ",1),d(Pe,"MAP_WRITE",2),d(Pe,"COPY_SRC",4),d(Pe,"COPY_DST",8),d(Pe,"DEBUG_DATA_MAX_LENGTH",32),d(Pe,"defaultProps",{...F.defaultProps,handle:void 0,usage:0,byteLength:0,byteOffset:0,data:null,indexType:"uint16",onMapped:void 0});z=Pe});function j_(){return Wd??Uint16Array}function H_(r){return!!(Wd&&r===Wd)}var Wd,Y_=b(()=>{Wd=globalThis.Float16Array});function q_(r){let e=r.includes("norm"),t=!e&&!r.startsWith("float"),n=r.startsWith("s"),i=jd[r],[o,s,a]=i||["uint8 ","i32",1];return{signedType:o,primitiveType:s,byteLength:a,normalized:e,integer:t,signed:n}}function X_(r){let e=r;switch(e){case"uint8":return"unorm8";case"sint8":return"snorm8";case"uint16":return"unorm16";case"sint16":return"snorm16";default:return e}}function ut(r,e){switch(e){case 1:return r;case 2:return r+r%2;default:return r+(4-r%4)%4}}function Pc(r){let e=ArrayBuffer.isView(r)?r.constructor:r;if(H_(e))return"float16";if(e===Uint8ClampedArray)return"uint8";let t=Object.values(jd).find(n=>e===n[4]);if(!t)throw new Error(e.name);return t[0]}function Z_(r){return Pc(r)}function dn(r){if(r==="float16")return j_();let e=jd[r];if(!e)throw new Error(r);let[,,,,t]=e;return t}function hn(r){return dn(r)}var jd,Tc=b(()=>{Y_();jd={uint8:["uint8","u32",1,!1,Uint8Array],sint8:["sint8","i32",1,!1,Int8Array],unorm8:["uint8","f32",1,!0,Uint8Array],snorm8:["sint8","f32",1,!0,Int8Array],uint16:["uint16","u32",2,!1,Uint16Array],sint16:["sint16","i32",2,!1,Int16Array],unorm16:["uint16","u32",2,!0,Uint16Array],snorm16:["sint16","i32",2,!0,Int16Array],float16:["float16","f16",2,!1,Uint16Array],float32:["float32","f32",4,!1,Float32Array],uint32:["uint32","u32",4,!1,Uint32Array],sint32:["sint32","i32",4,!1,Int32Array]}});var Hd,Te,Lc=b(()=>{Tc();Hd=class{getDataTypeInfo(e){return q_(e)}getNormalizedDataType(e){return X_(e)}alignTo(e,t){return ut(e,t)}getDataType(e){return Z_(e)}getTypedArrayConstructor(e){return hn(e)}},Te=new Hd});function IT(r,e){try{return Te.getDataTypeInfo(e)}catch{throw new Error(`Unsupported vertex format: ${r}`)}}function RT(r,e){if(!e)return 1;let t=Number(e);if(t===2||t===3||t===4)return t;throw new Error(`Unsupported vertex format: ${r}`)}function BT(r,e,t){if(t!==3)throw new Error(`Unsupported vertex format: ${r}`);switch(e){case"uint8":case"sint8":case"unorm8":case"snorm8":case"uint16":case"sint16":case"unorm16":case"snorm16":return`${e}x3-webgl`;default:throw new Error(`Unsupported vertex format: ${r}`)}}var Yd,ne,$o=b(()=>{Lc();Yd=class{getVertexFormatInfo(e){if(e==="unorm10-10-10-2")return{type:"unorm8",components:4,byteLength:4,integer:!1,signed:!1,normalized:!0};let t=e==="unorm8x4-bgra"?"unorm8x4":e,n;t.endsWith("-webgl")&&(t=t.slice(0,-6),n=!0);let i=t.split("x");if(i.length>2)throw new Error(`Unsupported vertex format: ${e}`);let[o,s]=i,a=o,c=RT(e,s),l=IT(e,a),u;try{u=n?BT(e,a,c):this.makeVertexFormat(l.signedType,c,l.normalized)}catch{throw new Error(`Unsupported vertex format: ${e}`)}if(u!==(n?e:t))throw new Error(`Unsupported vertex format: ${e}`);let f={type:a,components:c,byteLength:l.byteLength*c,integer:l.integer,signed:l.signed,normalized:l.normalized};return n&&(f.webglOnly=!0),f}makeVertexFormat(e,t,n){let i=n?Te.getNormalizedDataType(e):e;switch(i){case"unorm8":return t===1?"unorm8":t===3?"unorm8x3-webgl":`${i}x${t}`;case"snorm8":return t===1?"snorm8":t===3?"snorm8x3-webgl":`${i}x${t}`;case"uint8":case"sint8":if(t===3)throw new Error(`size: ${t}`);return t===1?i:`${i}x${t}`;case"uint16":return t===1?"uint16":t===3?"uint16x3-webgl":`${i}x${t}`;case"sint16":return t===1?"sint16":t===3?"sint16x3-webgl":`${i}x${t}`;case"unorm16":return t===1?"unorm16":t===3?"unorm16x3-webgl":`${i}x${t}`;case"snorm16":return t===1?"snorm16":t===3?"snorm16x3-webgl":`${i}x${t}`;case"float16":if(t===3)throw new Error(`size: ${t}`);return t===1?i:`${i}x${t}`;default:return t===1?i:`${i}x${t}`}}getVertexFormatFromAttribute(e,t,n){if(!t||t>4)throw new Error(`size ${t}`);let i=t,o=Te.getDataType(e);return this.makeVertexFormat(o,i,n)}getCompatibleVertexFormat(e){let t;switch(e.primitiveType){case"f32":t="float32";break;case"i32":t="sint32";break;case"u32":t="uint32";break;case"f16":return e.components<=2?"float16x2":"float16x4"}return e.components===1?t:`${t}x${e.components}`}},ne=new Yd});function Ic(r){let e=J_[r];if(!e)throw new Error(`Unsupported texture format ${r}`);return e}function Q_(){return J_}var Ae,K,Vt,OT,Ac,qd,Cc,Xd,kT,Zd,Ir,Kd,Qd,Mc,K_,DT,NT,J_,Jd=b(()=>{Ae="texture-compression-bc",K="texture-compression-astc",Vt="texture-compression-etc2",OT="texture-compression-etc1-webgl",Ac="texture-compression-pvrtc-webgl",qd="texture-compression-atc-webgl",Cc="float32-renderable-webgl",Xd="float16-renderable-webgl",kT="rgb9e5ufloat-renderable-webgl",Zd="snorm8-renderable-webgl",Ir="norm16-webgl",Kd="norm16-renderable-webgl",Qd="snorm16-renderable-webgl",Mc="float32-filterable",K_="float16-filterable-webgl";DT={r8unorm:{webgpu:527},rg8unorm:{webgpu:527},"rgb8unorm-webgl":{},rgba8unorm:{webgpu:31},"rgba8unorm-srgb":{webgpu:15},r8snorm:{render:Zd,webgpu:837},rg8snorm:{render:Zd,webgpu:837},"rgb8snorm-webgl":{},rgba8snorm:{render:Zd,webgpu:341},r8uint:{webgpu:515},rg8uint:{webgpu:515},rgba8uint:{webgpu:19},r8sint:{webgpu:515},rg8sint:{webgpu:515},rgba8sint:{webgpu:19},bgra8unorm:{webgpu:15},"bgra8unorm-srgb":{webgpu:15360},r16unorm:{f:Ir,render:Kd,webgpu:992},rg16unorm:{f:Ir,render:Kd,webgpu:992},"rgb16unorm-webgl":{f:Ir,render:!1},rgba16unorm:{f:Ir,render:Kd,webgpu:992},r16snorm:{f:Ir,render:Qd,webgpu:992},rg16snorm:{f:Ir,render:Qd,webgpu:992},"rgb16snorm-webgl":{f:Ir,render:!1},rgba16snorm:{f:Ir,render:Qd,webgpu:992},r16uint:{webgpu:515},rg16uint:{webgpu:515},rgba16uint:{webgpu:19},r16sint:{webgpu:515},rg16sint:{webgpu:515},rgba16sint:{webgpu:19},r16float:{render:Xd,filter:"float16-filterable-webgl",webgpu:527},rg16float:{render:Xd,filter:K_,webgpu:527},rgba16float:{render:Xd,filter:K_,webgpu:31},r32uint:{webgpu:19},rg32uint:{webgpu:16387},rgba32uint:{webgpu:19},r32sint:{webgpu:19},rg32sint:{webgpu:16387},rgba32sint:{webgpu:19},r32float:{render:Cc,filter:Mc,webgpu:19},rg32float:{render:!1,filter:Mc,webgpu:16387},"rgb32float-webgl":{render:Cc,filter:Mc},rgba32float:{render:Cc,filter:Mc,webgpu:19},"rgba4unorm-webgl":{channels:"rgba",bitsPerChannel:[4,4,4,4],packed:!0},"rgb565unorm-webgl":{channels:"rgb",bitsPerChannel:[5,6,5,0],packed:!0},"rgb5a1unorm-webgl":{channels:"rgba",bitsPerChannel:[5,5,5,1],packed:!0},rgb9e5ufloat:{channels:"rgb",packed:!0,render:kT,webgpu:5},rg11b10ufloat:{channels:"rgb",bitsPerChannel:[11,11,10,0],packed:!0,p:1,render:Cc,webgpu:517},rgb10a2unorm:{channels:"rgba",bitsPerChannel:[10,10,10,2],packed:!0,p:1,webgpu:527},rgb10a2uint:{channels:"rgba",bitsPerChannel:[10,10,10,2],packed:!0,p:1,webgpu:515},stencil8:{attachment:"stencil",bitsPerChannel:[8,0,0,0],dataType:"uint8",webgpu:3},depth16unorm:{attachment:"depth",bitsPerChannel:[16,0,0,0],dataType:"uint16",webgpu:3},depth24plus:{attachment:"depth",bitsPerChannel:[24,0,0,0],dataType:"uint32",webgpu:3},depth32float:{attachment:"depth",bitsPerChannel:[32,0,0,0],dataType:"float32",webgpu:3},"depth24plus-stencil8":{attachment:"depth-stencil",bitsPerChannel:[24,8,0,0],packed:!0,webgpu:3},"depth32float-stencil8":{attachment:"depth-stencil",bitsPerChannel:[32,8,0,0],packed:!0,f:"depth32float-stencil8",webgpu:3}},NT={"bc1-rgb-unorm-webgl":{f:Ae},"bc1-rgb-unorm-srgb-webgl":{f:Ae},"bc1-rgba-unorm":{f:Ae},"bc1-rgba-unorm-srgb":{f:Ae},"bc2-rgba-unorm":{f:Ae},"bc2-rgba-unorm-srgb":{f:Ae},"bc3-rgba-unorm":{f:Ae},"bc3-rgba-unorm-srgb":{f:Ae},"bc4-r-unorm":{f:Ae},"bc4-r-snorm":{f:Ae},"bc5-rg-unorm":{f:Ae},"bc5-rg-snorm":{f:Ae},"bc6h-rgb-ufloat":{f:Ae},"bc6h-rgb-float":{f:Ae},"bc7-rgba-unorm":{f:Ae},"bc7-rgba-unorm-srgb":{f:Ae},"etc2-rgb8unorm":{f:Vt},"etc2-rgb8unorm-srgb":{f:Vt},"etc2-rgb8a1unorm":{f:Vt},"etc2-rgb8a1unorm-srgb":{f:Vt},"etc2-rgba8unorm":{f:Vt},"etc2-rgba8unorm-srgb":{f:Vt},"eac-r11unorm":{f:Vt},"eac-r11snorm":{f:Vt},"eac-rg11unorm":{f:Vt},"eac-rg11snorm":{f:Vt},"astc-4x4-unorm":{f:K},"astc-4x4-unorm-srgb":{f:K},"astc-5x4-unorm":{f:K},"astc-5x4-unorm-srgb":{f:K},"astc-5x5-unorm":{f:K},"astc-5x5-unorm-srgb":{f:K},"astc-6x5-unorm":{f:K},"astc-6x5-unorm-srgb":{f:K},"astc-6x6-unorm":{f:K},"astc-6x6-unorm-srgb":{f:K},"astc-8x5-unorm":{f:K},"astc-8x5-unorm-srgb":{f:K},"astc-8x6-unorm":{f:K},"astc-8x6-unorm-srgb":{f:K},"astc-8x8-unorm":{f:K},"astc-8x8-unorm-srgb":{f:K},"astc-10x5-unorm":{f:K},"astc-10x5-unorm-srgb":{f:K},"astc-10x6-unorm":{f:K},"astc-10x6-unorm-srgb":{f:K},"astc-10x8-unorm":{f:K},"astc-10x8-unorm-srgb":{f:K},"astc-10x10-unorm":{f:K},"astc-10x10-unorm-srgb":{f:K},"astc-12x10-unorm":{f:K},"astc-12x10-unorm-srgb":{f:K},"astc-12x12-unorm":{f:K},"astc-12x12-unorm-srgb":{f:K},"pvrtc-rgb4unorm-webgl":{f:Ac},"pvrtc-rgba4unorm-webgl":{f:Ac},"pvrtc-rgb2unorm-webgl":{f:Ac},"pvrtc-rgba2unorm-webgl":{f:Ac},"etc1-rbg-unorm-webgl":{f:OT},"atc-rgb-unorm-webgl":{f:qd},"atc-rgba-unorm-webgl":{f:qd},"atc-rgbai-unorm-webgl":{f:qd}},J_={...DT,...NT}});function VT({format:r,width:e,height:t,depth:n,byteAlignment:i}){let o=ze.getInfo(r),{bytesPerPixel:s,bytesPerBlock:a=s,blockWidth:c=1,blockHeight:l=1,compressed:u=!1}=o,f=u?Math.ceil(e/c):e,h=u?Math.ceil(t/l):t,p=f*a,m=Math.ceil(p/i)*i,g=h,y=m*g*n;return{bytesPerPixel:s,bytesPerRow:m,rowsPerImage:g,depthOrArrayLayers:n,bytesPerImage:m*g,byteLength:y}}function WT(r){let e=Ic(r),t={format:r,create:e.f??!0,render:e.render??!0,filter:e.filter??!0,blend:e.blend??!0,store:e.store??!0},n=eb(r),i=r.startsWith("depth")||r.startsWith("stencil"),o=n?.signed,s=n?.integer,a=n?.webgl,c=!!n?.compressed;return t.render&&(t.render=!i&&!c),t.filter&&(t.filter=!i&&!o&&!s&&!a),t}function eb(r){let e=jT(r);if(ze.isCompressed(r)){e.channels="rgb",e.components=3,e.bytesPerPixel=1,e.srgb=!1,e.compressed=!0,e.bytesPerBlock=YT(r);let n=HT(r);n&&(e.blockWidth=n.blockWidth,e.blockHeight=n.blockHeight)}let t=e.packed?null:FT.exec(r);if(t){let[,n,i,o,s,a]=t,c=`${o}${i}`,l=Te.getDataTypeInfo(c),u=l.byteLength*8,f=n?.length??1,h=[u,f>=2?u:0,f>=3?u:0,f>=4?u:0];e={format:r,attachment:e.attachment,dataType:l.signedType,components:f,channels:n,integer:l.integer,signed:l.signed,normalized:l.normalized,bitsPerChannel:h,bytesPerPixel:l.byteLength*f,packed:e.packed,srgb:e.srgb},a==="-webgl"&&(e.webgl=!0),s==="-srgb"&&(e.srgb=!0)}return r.endsWith("-webgl")&&(e.webgl=!0),r.endsWith("-srgb")&&(e.srgb=!0),e}function jT(r){let e={...Ic(r)},t=e.bytesPerPixel||1,n=e.bitsPerChannel||[8,8,8,8];return delete e.bitsPerChannel,delete e.bytesPerPixel,delete e.f,delete e.render,delete e.filter,delete e.blend,delete e.store,delete e.webgpu,{...e,format:r,attachment:e.attachment||"color",channels:e.channels||"r",components:e.components||e.channels?.length||1,bytesPerPixel:t,bitsPerChannel:n,dataType:e.dataType||"uint8",srgb:e.srgb??!1,packed:e.packed??!1,webgl:e.webgl??!1,integer:e.integer??!1,signed:e.signed??!1,normalized:e.normalized??!1,compressed:e.compressed??!1}}function HT(r){let t=/.*-(\d+)x(\d+)-.*/.exec(r);if(t){let[,n,i]=t;return{blockWidth:Number(n),blockHeight:Number(i)}}return r.startsWith("bc")||r.startsWith("etc1")||r.startsWith("etc2")||r.startsWith("eac")||r.startsWith("atc")?{blockWidth:4,blockHeight:4}:r.startsWith("pvrtc-rgb4")||r.startsWith("pvrtc-rgba4")?{blockWidth:4,blockHeight:4}:r.startsWith("pvrtc-rgb2")||r.startsWith("pvrtc-rgba2")?{blockWidth:8,blockHeight:4}:null}function YT(r){return r.startsWith("bc1")||r.startsWith("bc4")||r.startsWith("etc1")||r.startsWith("etc2-rgb8")||r.startsWith("etc2-rgb8a1")||r.startsWith("eac-r11")||r==="atc-rgb-unorm-webgl"?8:r.startsWith("bc2")||r.startsWith("bc3")||r.startsWith("bc5")||r.startsWith("bc6h")||r.startsWith("bc7")||r.startsWith("etc2-rgba8")||r.startsWith("eac-rg11")||r.startsWith("astc")||r==="atc-rgba-unorm-webgl"||r==="atc-rgbai-unorm-webgl"?16:r.startsWith("pvrtc")?8:16}var FT,UT,GT,zT,$T,eh,ze,Rc=b(()=>{Lc();Jd();FT=/^(r|rg|rgb|rgba|bgra)([0-9]*)([a-z]*)(-srgb)?(-webgl)?$/,UT=["rgb","rgba","bgra"],GT=["depth","stencil"],zT=5,$T=["bc1","bc2","bc3","bc4","bc5","bc6","bc7","etc1","etc2","eac","atc","astc","pvrtc"],eh=class{isColor(e){return UT.some(t=>e.startsWith(t))}isDepthStencil(e){return GT.some(t=>e.startsWith(t))}isCompressed(e){return $T.some(t=>e.startsWith(t))}getInfo(e){return eb(e)}getCapabilities(e){return WT(e)}getWebGPUCapabilities(e){let t=Ic(e);return t.webgpu!==void 0?t.webgpu:this.isCompressed(e)&&!e.endsWith("-webgl")?zT:0}computeMemoryLayout(e){return VT(e)}},ze=new eh});function tb(r){return typeof ImageData<"u"&&r instanceof ImageData||typeof ImageBitmap<"u"&&r instanceof ImageBitmap||typeof HTMLImageElement<"u"&&r instanceof HTMLImageElement||typeof HTMLVideoElement<"u"&&r instanceof HTMLVideoElement||typeof VideoFrame<"u"&&r instanceof VideoFrame||typeof HTMLCanvasElement<"u"&&r instanceof HTMLCanvasElement||typeof OffscreenCanvas<"u"&&r instanceof OffscreenCanvas}function rb(r){if(typeof ImageData<"u"&&r instanceof ImageData||typeof ImageBitmap<"u"&&r instanceof ImageBitmap||typeof HTMLCanvasElement<"u"&&r instanceof HTMLCanvasElement||typeof OffscreenCanvas<"u"&&r instanceof OffscreenCanvas)return{width:r.width,height:r.height};if(typeof HTMLImageElement<"u"&&r instanceof HTMLImageElement)return{width:r.naturalWidth,height:r.naturalHeight};if(typeof HTMLVideoElement<"u"&&r instanceof HTMLVideoElement)return{width:r.videoWidth,height:r.videoHeight};if(typeof VideoFrame<"u"&&r instanceof VideoFrame)return{width:r.displayWidth,height:r.displayHeight};throw new Error("Unknown image type")}var nb=b(()=>{});function qT(r,e){let t=th(r),n=e.map(th).filter(i=>i!==void 0);return[t,...n].filter(i=>i!==void 0)}function th(r){if(r!==void 0){if(r===null||typeof r=="string"||typeof r=="number"||typeof r=="boolean")return r;if(r instanceof Error)return r.message;if(Array.isArray(r))return r.map(th);if(typeof r=="object"){if(XT(r)){let e=String(r);if(e!=="[object Object]")return e}return ZT(r)?KT(r):r.constructor?.name||"Object"}return String(r)}}function XT(r){return"toString"in r&&typeof r.toString=="function"&&r.toString!==Object.prototype.toString}function ZT(r){return"message"in r&&"type"in r}function KT(r){let e=typeof r.type=="string"?r.type:"message",t=typeof r.message=="string"?r.message:"",n=typeof r.lineNum=="number"?r.lineNum:null,i=typeof r.linePos=="number"?r.linePos:null,o=n!==null&&i!==null?` @ ${n}:${i}`:n!==null?` @ ${n}`:"";return`${e}${o}: ${t}`.trim()}function rh(){if(typeof HTMLCanvasElement>"u")return!1;let r=HTMLCanvasElement.prototype;return"layoutSubtree"in r&&typeof r.requestPaint=="function"}var Vo,Wo,Bc,hr,ib=b(()=>{zd();Ge();di();Sc();$o();Rc();nb();Jd();Ud();Vo=class{};Wo=class{constructor(e=[],t){d(this,"features");d(this,"disabledFeatures");this.features=new Set(e),this.disabledFeatures=t||{}}*[Symbol.iterator](){yield*this.features}has(e){return!this.disabledFeatures?.[e]&&this.features.has(e)}};Bc=class Bc{constructor(e){d(this,"id");d(this,"props");d(this,"userData",{});d(this,"statsManager",wc);d(this,"_factories",{});d(this,"timestamp",0);d(this,"_reused",!1);d(this,"_moduleData",{});d(this,"wgslLanguageFeatures",new Set);d(this,"_textureCaps",{});d(this,"_debugGPUTimeQuery",null);this.props={...Bc.defaultProps,...e},this.id=this.props.id||$t(this[Symbol.toStringTag].toLowerCase())}get[Symbol.toStringTag](){return"Device"}toString(){return`Device(${this.id})`}toJSON(){return this.toString()}getVertexFormatInfo(e){return ne.getVertexFormatInfo(e)}isVertexFormatSupported(e){return!0}getTextureFormatInfo(e){return ze.getInfo(e)}getTextureFormatCapabilities(e){let t=this._textureCaps[e];if(!t){let n=this._getDeviceTextureFormatCapabilities(e);t=this._getDeviceSpecificTextureFormatCapabilities(n),this._textureCaps[e]=t}return t}getMipLevelCount(e,t,n=1){let i=Math.max(e,t,n);return 1+Math.floor(Math.log2(i))}isExternalImage(e){return tb(e)}getExternalImageSize(e){return rb(e)}isTextureFormatSupported(e){return this.getTextureFormatCapabilities(e).create}isTextureFormatFilterable(e){return this.getTextureFormatCapabilities(e).filter}isTextureFormatRenderable(e){return this.getTextureFormatCapabilities(e).render}isTextureFormatCompressed(e){return ze.isCompressed(e)}getSupportedCompressedTextureFormats(){let e=[];for(let t of Object.keys(Q_()))this.isTextureFormatCompressed(t)&&this.isTextureFormatSupported(t)&&e.push(t);return e}pushDebugGroup(e){this.commandEncoder.pushDebugGroup(e)}popDebugGroup(){this.commandEncoder?.popDebugGroup()}insertDebugMarker(e){this.commandEncoder?.insertDebugMarker(e)}loseDevice(){return!1}incrementTimestamp(){return this.timestamp++}reportError(e,t,...n){if(!this.props.onError(e,t)){let o=qT(t,n);return T.error(this.type==="webgl"?"%cWebGL":"%cWebGPU","color: white; background: red; padding: 2px 6px; border-radius: 3px;",e.message,...o)}return()=>{}}debug(){if(this.props.debug)debugger;else T.once(0,`'Type luma.log.set({debug: true}) in console to enable debug breakpoints',
or create a device with the 'debug: true' prop.`)()}getDefaultCanvasContext(){if(!this.canvasContext)throw new Error("Device has no default CanvasContext. See props.createCanvasContext");return this.canvasContext}createFence(){throw new Error("createFence() not implemented")}beginRenderPass(e){return this.commandEncoder.beginRenderPass(e)}beginComputePass(e){return this.commandEncoder.beginComputePass(e)}writeBufferViaCommandEncoder(e,t,n,i=0){throw new Error("writeBufferViaCommandEncoder() not implemented")}generateMipmapsWebGPU(e){throw new Error("not implemented")}_createSharedRenderPipelineWebGL(e){throw new Error("_createSharedRenderPipelineWebGL() not implemented")}_createBindGroupLayoutWebGPU(e,t){throw new Error("_createBindGroupLayoutWebGPU() not implemented")}_createBindGroupWebGPU(e,t,n,i,o){throw new Error("_createBindGroupWebGPU() not implemented")}_supportsDebugGPUTime(){return this.features.has("timestamp-query")&&!!(this.props.debug||this.props.debugGPUTime)}_enableDebugGPUTime(e=256){if(!this._supportsDebugGPUTime())return null;if(this._debugGPUTimeQuery)return this._debugGPUTimeQuery;try{this._debugGPUTimeQuery=this.createQuerySet({type:"timestamp",count:e}),this.commandEncoder=this.createCommandEncoder({id:this.commandEncoder.props.id,timeProfilingQuerySet:this._debugGPUTimeQuery})}catch{this._debugGPUTimeQuery=null}return this._debugGPUTimeQuery}_disableDebugGPUTime(){this._debugGPUTimeQuery&&(this.commandEncoder.getTimeProfilingQuerySet()===this._debugGPUTimeQuery&&(this.commandEncoder=this.createCommandEncoder({id:this.commandEncoder.props.id})),this._debugGPUTimeQuery.destroy(),this._debugGPUTimeQuery=null)}_isDebugGPUTimeEnabled(){return this._debugGPUTimeQuery!==null}getCanvasContext(){return this.getDefaultCanvasContext()}readPixelsToArrayWebGL(e,t){throw new Error("not implemented")}readPixelsToBufferWebGL(e,t){throw new Error("not implemented")}setParametersWebGL(e){throw new Error("not implemented")}getParametersWebGL(e){throw new Error("not implemented")}withParametersWebGL(e,t){throw new Error("not implemented")}clearWebGL(e){throw new Error("not implemented")}resetWebGL(){throw new Error("not implemented")}getModuleData(e){var t;return(t=this._moduleData)[e]||(t[e]={}),this._moduleData[e]}static _getCanvasContextProps(e){return e.createCanvasContext===!0?{}:e.createCanvasContext}_getDeviceTextureFormatCapabilities(e){let t=ze.getCapabilities(e),n=o=>(typeof o=="string"?this.features.has(o):o)??!0,i=n(t.create);return{format:e,create:i,render:i&&n(t.render),filter:i&&n(t.filter),blend:i&&n(t.blend),store:i&&n(t.store)}}_normalizeBufferProps(e){(e instanceof ArrayBuffer||ArrayBuffer.isView(e))&&(e={data:e});let t={...e};if((e.usage||0)&z.INDEX&&(e.indexType||(e.data instanceof Uint32Array?t.indexType="uint32":e.data instanceof Uint16Array?t.indexType="uint16":e.data instanceof Uint8Array&&(t.data=new Uint16Array(e.data),t.indexType="uint16")),!t.indexType))throw new Error("indices buffer content must be of type uint16 or uint32");return t}};d(Bc,"defaultProps",{...vc});hr=Bc});var Oc,ob=b(()=>{Oc=class{constructor(e){d(this,"props");d(this,"_resizeObserver");d(this,"_intersectionObserver");d(this,"_observeDevicePixelRatioTimeout",null);d(this,"_observeDevicePixelRatioMediaQuery",null);d(this,"_handleDevicePixelRatioChange",()=>this._refreshDevicePixelRatio());d(this,"_trackPositionInterval",null);d(this,"_started",!1);this.props=e}get started(){return this._started}start(){if(this._started||!this.props.canvas)return;this._started=!0,this._intersectionObserver||(this._intersectionObserver=new IntersectionObserver(t=>this.props.onIntersection(t))),this._resizeObserver||(this._resizeObserver=new ResizeObserver(t=>this.props.onResize(t))),this._intersectionObserver.observe(this.props.canvas);let e=this.props.resizeObserverBox;try{this._resizeObserver.observe(this.props.canvas,{box:e})}catch{this._resizeObserver.observe(this.props.canvas,{box:"content-box"})}this._observeDevicePixelRatioTimeout=setTimeout(()=>this._refreshDevicePixelRatio(),0),this.props.trackPosition&&this._trackPosition()}stop(){this._started&&(this._started=!1,this._observeDevicePixelRatioTimeout&&(clearTimeout(this._observeDevicePixelRatioTimeout),this._observeDevicePixelRatioTimeout=null),this._observeDevicePixelRatioMediaQuery&&(this._observeDevicePixelRatioMediaQuery.removeEventListener("change",this._handleDevicePixelRatioChange),this._observeDevicePixelRatioMediaQuery=null),this._trackPositionInterval&&(clearInterval(this._trackPositionInterval),this._trackPositionInterval=null),this._resizeObserver?.disconnect(),this._intersectionObserver?.disconnect())}_refreshDevicePixelRatio(){this._started&&(this.props.onDevicePixelRatioChange(),this._observeDevicePixelRatioMediaQuery?.removeEventListener("change",this._handleDevicePixelRatioChange),this._observeDevicePixelRatioMediaQuery=matchMedia(`(resolution: ${window.devicePixelRatio}dppx)`),this._observeDevicePixelRatioMediaQuery.addEventListener("change",this._handleDevicePixelRatioChange,{once:!0}))}_trackPosition(e=100){this._trackPositionInterval||(this._trackPositionInterval=setInterval(()=>{this._started?this.props.onPositionChange():this._trackPositionInterval&&(clearInterval(this._trackPositionInterval),this._trackPositionInterval=null)},e))}}});function sb(){let r,e;return{promise:new Promise((n,i)=>{r=n,e=i}),resolve:r,reject:e}}var ab=b(()=>{});function Rr(r,e){if(!r){let t=new Error(e??"luma.gl assertion failed.");throw Error.captureStackTrace?.(t,Rr),t}}function Br(r,e){return Rr(r,e),r}var nh=b(()=>{});function QT(r){if(typeof r=="string"){let e=document.getElementById(r);if(!e)throw new Error(`${r} is not an HTML element`);return e}return r||document.body}function JT(r){let e=document.getElementById(r);if(!Or.isHTMLCanvas(e))throw new Error("Object is not a canvas element");return e}function eL(r){let{width:e,height:t}=r,n=document.createElement("canvas");n.id=$t("lumagl-auto-created-canvas"),n.width=e||1,n.height=t||1,n.style.width=Number.isFinite(e)?`${e}px`:"100%",n.style.height=Number.isFinite(t)?`${t}px`:"100%",r?.visible||(n.style.visibility="hidden");let i=QT(r?.container||null);return i.insertBefore(n,i.firstChild),n}function tL(r,e,t,n,i){let o=r,s=cb(o[0],e,t),a=lb(o[1],e,n,i),c=cb(o[0]+1,e,t),l=c===t-1?c:c-1;c=lb(o[1]+1,e,n,i);let u;return i?(c=c===0?c:c+1,u=a,a=c):u=c===n-1?c:c-1,{x:s,y:a,width:Math.max(l-s+1,1),height:Math.max(u-a+1,1)}}function cb(r,e,t){return Math.min(Math.round(r*e),t-1)}function lb(r,e,t,n){return n?Math.max(0,t-1-Math.round(r*e)):Math.min(Math.round(r*e),t-1)}var hi,Or,ih=b(()=>{on();ob();di();ab();nh();hi=class hi{constructor(e){d(this,"id");d(this,"props");d(this,"canvas");d(this,"htmlCanvas");d(this,"offscreenCanvas");d(this,"type");d(this,"initialized");d(this,"isInitialized",!1);d(this,"isVisible",!0);d(this,"cssWidth");d(this,"cssHeight");d(this,"devicePixelRatio");d(this,"devicePixelWidth");d(this,"devicePixelHeight");d(this,"drawingBufferWidth");d(this,"drawingBufferHeight");d(this,"_initializedResolvers",sb());d(this,"_canvasObserver");d(this,"_position",[0,0]);d(this,"destroyed",!1);d(this,"_needsDrawingBufferResize",!0);d(this,"_configuredDrawingBufferSize",[0,0]);this.props={...hi.defaultProps,...e},e=this.props,this.initialized=this._initializedResolvers.promise,Je()?e.canvas?typeof e.canvas=="string"?this.canvas=JT(e.canvas):this.canvas=e.canvas:this.canvas=eL(e):this.canvas={width:e.width||1,height:e.height||1},hi.isHTMLCanvas(this.canvas)?(this.id=e.id||this.canvas.id,this.type="html-canvas",this.htmlCanvas=this.canvas):hi.isOffscreenCanvas(this.canvas)?(this.id=e.id||"offscreen-canvas",this.type="offscreen-canvas",this.offscreenCanvas=this.canvas):(this.id=e.id||"node-canvas-context",this.type="node"),this.cssWidth=this.htmlCanvas?.clientWidth||this.canvas.width,this.cssHeight=this.htmlCanvas?.clientHeight||this.canvas.height,this.devicePixelWidth=this.canvas.width,this.devicePixelHeight=this.canvas.height,this.drawingBufferWidth=this.canvas.width,this.drawingBufferHeight=this.canvas.height,this._configuredDrawingBufferSize=[this.canvas.width,this.canvas.height],this.devicePixelRatio=globalThis.devicePixelRatio||1,this._position=[0,0],this._canvasObserver=new Oc({canvas:this.htmlCanvas,trackPosition:this.props.trackPosition,resizeObserverBox:this.props.pixelSizeSource==="css-dpr"?"content-box":"device-pixel-content-box",onResize:t=>this._handleResize(t),onIntersection:t=>this._handleIntersection(t),onDevicePixelRatioChange:()=>this._observeDevicePixelRatio(),onPositionChange:()=>this.updatePosition()})}static isHTMLCanvas(e){return typeof HTMLCanvasElement<"u"&&e instanceof HTMLCanvasElement}static isOffscreenCanvas(e){return typeof OffscreenCanvas<"u"&&e instanceof OffscreenCanvas}toString(){return`${this[Symbol.toStringTag]}(${this.id})`}destroy(){this.destroyed||(this.destroyed=!0,this._stopObservers(),this.device=null)}setProps(e){return"useDevicePixels"in e&&(this.props.useDevicePixels=e.useDevicePixels||!1,this._updateDrawingBufferSize()),this}getCurrentFramebuffer(e){return this._resizeDrawingBufferIfNeeded(),this._getCurrentFramebuffer(e)}getCSSSize(){return[this.cssWidth,this.cssHeight]}getPosition(){return this._position}getDevicePixelSize(){return[this.devicePixelWidth,this.devicePixelHeight]}getDrawingBufferSize(){return[this.drawingBufferWidth,this.drawingBufferHeight]}getMaxDrawingBufferSize(){let e=this.device.limits.maxTextureDimension2D;return[e,e]}setDrawingBufferSize(e,t){e=Math.floor(e),t=Math.floor(t),!(this.drawingBufferWidth===e&&this.drawingBufferHeight===t)&&(this.drawingBufferWidth=e,this.drawingBufferHeight=t,this._needsDrawingBufferResize=!0)}getDevicePixelRatio(){return typeof window<"u"&&window.devicePixelRatio||1}cssToDevicePixels(e,t=!0){let n=this.cssToDeviceRatio(),[i,o]=this.getDrawingBufferSize();return tL(e,n,i,o,t)}getPixelSize(){return this.getDevicePixelSize()}getAspect(){let[e,t]=this.getDrawingBufferSize();return e>0&&t>0?e/t:1}cssToDeviceRatio(){try{let[e]=this.getDrawingBufferSize(),[t]=this.getCSSSize();return t?e/t:1}catch{return 1}}resize(e){this.setDrawingBufferSize(e.width,e.height)}_setAutoCreatedCanvasId(e){this.htmlCanvas?.id==="lumagl-auto-created-canvas"&&(this.htmlCanvas.id=e)}_startObservers(){this.destroyed||this._canvasObserver.start()}_stopObservers(){this._canvasObserver.stop()}_handleIntersection(e){if(this.destroyed)return;let t=e.find(i=>i.target===this.canvas);if(!t)return;let n=t.isIntersecting;this.isVisible!==n&&(this.isVisible=n,this.device.props.onVisibilityChange(this))}_handleResize(e){if(this.destroyed)return;let t=e.find(o=>o.target===this.canvas);if(!t)return;let n=Br(t.contentBoxSize?.[0]);this.cssWidth=n.inlineSize,this.cssHeight=n.blockSize;let i=this.getDevicePixelSize();this._setDevicePixelSize(this._getDevicePixelSizeFromResizeEntry(t)),this._updateDrawingBufferSize(),this.device.props.onResize(this,{oldPixelSize:i})}_updateDrawingBufferSize(){if(this.props.autoResize)if(typeof this.props.useDevicePixels=="number"){let e=this.props.useDevicePixels;this.setDrawingBufferSize(this.cssWidth*e,this.cssHeight*e)}else this.props.useDevicePixels?this.setDrawingBufferSize(this.devicePixelWidth,this.devicePixelHeight):this.setDrawingBufferSize(this.cssWidth,this.cssHeight);this._initializedResolvers.resolve(),this.isInitialized=!0,this.updatePosition()}_getDevicePixelSizeFromResizeEntry(e){let t=Br(e.contentBoxSize?.[0]);return this.props.pixelSizeSource==="css-dpr"?this._getDevicePixelSizeFromCSSSize(t.inlineSize,t.blockSize):{devicePixelWidth:e.devicePixelContentBoxSize?.[0]?.inlineSize||t.inlineSize*devicePixelRatio,devicePixelHeight:e.devicePixelContentBoxSize?.[0]?.blockSize||t.blockSize*devicePixelRatio}}_getDevicePixelSizeFromCSSSize(e,t){let n=this.getDevicePixelRatio();return{devicePixelWidth:Math.floor(e*n),devicePixelHeight:Math.floor(t*n)}}_setDevicePixelSize({devicePixelWidth:e,devicePixelHeight:t}){let[n,i]=this.getMaxDrawingBufferSize();this.devicePixelWidth=Math.max(1,Math.min(e,n)),this.devicePixelHeight=Math.max(1,Math.min(t,i))}_resizeDrawingBufferIfNeeded(){if(this._needsDrawingBufferResize){this._needsDrawingBufferResize=!1,(this.drawingBufferWidth!==this.canvas.width||this.drawingBufferHeight!==this.canvas.height)&&(this.canvas.width=this.drawingBufferWidth,this.canvas.height=this.drawingBufferHeight);let[t,n]=this._configuredDrawingBufferSize;(this.drawingBufferWidth!==t||this.drawingBufferHeight!==n)&&(this._configureDevice(),this._configuredDrawingBufferSize=[this.drawingBufferWidth,this.drawingBufferHeight])}}_observeDevicePixelRatio(){if(this.destroyed||!this._canvasObserver.started)return;let e=this.devicePixelRatio;if(this.devicePixelRatio=window.devicePixelRatio,this.props.pixelSizeSource==="css-dpr"){let t=this.getDevicePixelSize();this._setDevicePixelSize(this._getDevicePixelSizeFromCSSSize(this.cssWidth,this.cssHeight)),this._updateDrawingBufferSize(),this.device.props.onResize(this,{oldPixelSize:t})}this.updatePosition(),this.device.props.onDevicePixelRatioChange?.(this,{oldRatio:e})}updatePosition(){if(this.destroyed)return;let e=this.htmlCanvas?.getBoundingClientRect();if(e){let t=[e.left,e.top];if(this._position??(this._position=t),t[0]!==this._position[0]||t[1]!==this._position[1]){let i=this._position;this._position=t,this.device.props.onPositionChange?.(this,{oldPosition:i})}}}};d(hi,"defaultProps",{id:void 0,canvas:null,width:800,height:600,useDevicePixels:!0,pixelSizeSource:"exact",autoResize:!0,container:null,visible:!0,alphaMode:"opaque",colorSpace:"srgb",colorFormat:void 0,toneMapping:"standard",trackPosition:!1});Or=hi});var pi,ub=b(()=>{ih();pi=class extends Or{};d(pi,"defaultProps",Or.defaultProps)});var jo,fb=b(()=>{ih();jo=class extends Or{}});var Ho,pn,oh=b(()=>{ve();Ho=class Ho extends F{get[Symbol.toStringTag](){return"Sampler"}constructor(e,t){t=Ho.normalizeProps(e,t),super(e,t,Ho.defaultProps)}static normalizeProps(e,t){return t}};d(Ho,"defaultProps",{...F.defaultProps,type:"color-sampler",addressModeU:"clamp-to-edge",addressModeV:"clamp-to-edge",addressModeW:"clamp-to-edge",magFilter:"nearest",minFilter:"nearest",mipmapFilter:"none",lodMinClamp:0,lodMaxClamp:32,compare:"less-equal",maxAnisotropy:1});pn=Ho});var rL,Q,Y,sh=b(()=>{ve();oh();Ge();Rc();rL={"1d":"1d","2d":"2d","2d-array":"2d",cube:"2d","cube-array":"2d","3d":"3d"},Q=class Q extends F{constructor(t,n,i){n=Q.normalizeProps(t,n);super(t,n,Q.defaultProps);d(this,"dimension");d(this,"baseDimension");d(this,"format");d(this,"width");d(this,"height");d(this,"depth");d(this,"mipLevels");d(this,"samples");d(this,"byteAlignment");d(this,"ready",Promise.resolve(this));d(this,"isReady",!0);d(this,"updateTimestamp");if(this.dimension=this.props.dimension,this.baseDimension=rL[this.dimension],this.format=this.props.format,this.width=this.props.width,this.height=this.props.height,this.depth=this.props.depth,this.mipLevels=this.props.mipLevels,this.samples=this.props.samples||1,this.dimension==="cube"&&(this.depth=6),this.props.width===void 0||this.props.height===void 0)if(t.isExternalImage(n.data)){let o=t.getExternalImageSize(n.data);this.width=o?.width||1,this.height=o?.height||1}else this.width=1,this.height=1,(this.props.width===void 0||this.props.height===void 0)&&T.warn(`${this} created with undefined width or height. This is deprecated. Use DynamicTexture instead.`)();this.byteAlignment=i?.byteAlignment||1,this.updateTimestamp=t.incrementTimestamp()}get[Symbol.toStringTag](){return"Texture"}toString(){return`Texture(${this.id},${this.format},${this.width}x${this.height})`}clone(t){return this.device.createTexture({...this.props,...t})}setSampler(t){this.sampler=t instanceof pn?t:this.device.createSampler(t)}copyImageData(t){let{data:n,depth:i,...o}=t;this.writeData(n,{...o,depthOrArrayLayers:o.depthOrArrayLayers??i})}computeMemoryLayout(t={}){let n=this._normalizeTextureReadOptions(t),{width:i=this.width,height:o=this.height,depthOrArrayLayers:s=this.depth}=n,{format:a,byteAlignment:c}=this;return ze.computeMemoryLayout({format:a,width:i,height:o,depth:s,byteAlignment:c})}readBuffer(t,n){throw new Error("readBuffer not implemented")}readDataAsync(t){throw new Error("readBuffer not implemented")}writeBuffer(t,n){throw new Error("readBuffer not implemented")}writeData(t,n){throw new Error("readBuffer not implemented")}readDataSyncWebGL(t){throw new Error("readDataSyncWebGL not available")}generateMipmapsWebGL(){throw new Error("generateMipmapsWebGL not available")}static normalizeProps(t,n){let i={...n},{width:o,height:s}=i;return typeof o=="number"&&(i.width=Math.max(1,Math.ceil(o))),typeof s=="number"&&(i.height=Math.max(1,Math.ceil(s))),i}_initializeData(t){this.device.isExternalImage(t)?this.copyExternalImage({image:t,width:this.width,height:this.height,depth:this.depth,mipLevel:0,x:0,y:0,z:0,aspect:"all",colorSpace:"srgb",premultipliedAlpha:!1,flipY:!1}):t&&this.copyImageData({data:t,mipLevel:0,x:0,y:0,z:0,aspect:"all"})}_normalizeCopyImageDataOptions(t){let{data:n,depth:i,...o}=t,s=this._normalizeTextureWriteOptions({...o,depthOrArrayLayers:o.depthOrArrayLayers??i});return{data:n,depth:s.depthOrArrayLayers,...s}}_normalizeCopyExternalImageOptions(t){let n=Q._omitUndefined(t),i=n.mipLevel??0,o=this._getMipLevelSize(i),s=this.device.getExternalImageSize(t.image),a={...Q.defaultCopyExternalImageOptions,...o,...s,...n};return a.width=Math.min(a.width,o.width-a.x),a.height=Math.min(a.height,o.height-a.y),a.depth=Math.min(a.depth,o.depthOrArrayLayers-a.z),a}_normalizeCopyElementImageOptions(t){let n=Q._omitUndefined(t),i=n.mipLevel??0,o=this._getMipLevelSize(i),s={...Q.defaultCopyElementImageOptions,...o,...n};return s.width=Math.min(s.width,o.width-s.x),s.height=Math.min(s.height,o.height-s.y),s.depth=Math.min(s.depth,o.depthOrArrayLayers-s.z),s}_normalizeTextureReadOptions(t){let n=Q._omitUndefined(t),i=n.mipLevel??0,o=this._getMipLevelSize(i),s={...Q.defaultTextureReadOptions,...o,...n};return s.width=Math.min(s.width,o.width-s.x),s.height=Math.min(s.height,o.height-s.y),s.depthOrArrayLayers=Math.min(s.depthOrArrayLayers,o.depthOrArrayLayers-s.z),s}_getSupportedColorReadOptions(t){let n=this._normalizeTextureReadOptions(t),i=ze.getInfo(this.format);switch(this._validateColorReadAspect(n),this._validateColorReadFormat(i),this.dimension){case"2d":case"cube":case"cube-array":case"2d-array":case"3d":return n;default:throw new Error(`${this} color readback does not support ${this.dimension} textures`)}}_validateColorReadAspect(t){if(t.aspect!=="all")throw new Error(`${this} color readback only supports aspect 'all'`)}_validateColorReadFormat(t){if(t.compressed)throw new Error(`${this} color readback does not support compressed formats (${this.format})`);switch(t.attachment){case"color":return;case"depth":throw new Error(`${this} color readback does not support depth formats (${this.format})`);case"stencil":throw new Error(`${this} color readback does not support stencil formats (${this.format})`);case"depth-stencil":throw new Error(`${this} color readback does not support depth-stencil formats (${this.format})`);default:throw new Error(`${this} color readback does not support format ${this.format}`)}}_normalizeTextureWriteOptions(t){let n=Q._omitUndefined(t),i=n.mipLevel??0,o=this._getMipLevelSize(i),s={...Q.defaultTextureWriteOptions,...o,...n};s.width=Math.min(s.width,o.width-s.x),s.height=Math.min(s.height,o.height-s.y),s.depthOrArrayLayers=Math.min(s.depthOrArrayLayers,o.depthOrArrayLayers-s.z);let a=ze.computeMemoryLayout({format:this.format,width:s.width,height:s.height,depth:s.depthOrArrayLayers,byteAlignment:this.byteAlignment}),c=a.bytesPerPixel*s.width;if(s.bytesPerRow=n.bytesPerRow??a.bytesPerRow,s.rowsPerImage=n.rowsPerImage??s.height,s.bytesPerRow<c)throw new Error(`bytesPerRow (${s.bytesPerRow}) must be at least ${c} for ${this.format}`);if(s.rowsPerImage<s.height)throw new Error(`rowsPerImage (${s.rowsPerImage}) must be at least ${s.height} for ${this.format}`);let l=this.device.getTextureFormatInfo(this.format).bytesPerPixel;if(l&&s.bytesPerRow%l!==0)throw new Error(`bytesPerRow (${s.bytesPerRow}) must be a multiple of bytesPerPixel (${l}) for ${this.format}`);return s}_getMipLevelSize(t){let n=Math.max(1,this.width>>t),i=this.baseDimension==="1d"?1:Math.max(1,this.height>>t),o=this.dimension==="3d"?Math.max(1,this.depth>>t):this.depth;return{width:n,height:i,depthOrArrayLayers:o}}getAllocatedByteLength(){let t=0;for(let n=0;n<this.mipLevels;n++){let{width:i,height:o,depthOrArrayLayers:s}=this._getMipLevelSize(n);t+=ze.computeMemoryLayout({format:this.format,width:i,height:o,depth:s,byteAlignment:1}).byteLength}return t*this.samples}static _omitUndefined(t){return Object.fromEntries(Object.entries(t).filter(([,n])=>n!==void 0))}};d(Q,"SAMPLE",4),d(Q,"STORAGE",8),d(Q,"RENDER",16),d(Q,"COPY_SRC",1),d(Q,"COPY_DST",2),d(Q,"TEXTURE",4),d(Q,"RENDER_ATTACHMENT",16),d(Q,"defaultProps",{...F.defaultProps,data:null,dimension:"2d",format:"rgba8unorm",usage:Q.SAMPLE|Q.RENDER|Q.COPY_DST,width:void 0,height:void 0,depth:1,mipLevels:1,samples:void 0,sampler:{},view:void 0}),d(Q,"defaultCopyDataOptions",{data:void 0,byteOffset:0,bytesPerRow:void 0,rowsPerImage:void 0,width:void 0,height:void 0,depthOrArrayLayers:void 0,depth:1,mipLevel:0,x:0,y:0,z:0,aspect:"all"}),d(Q,"defaultCopyExternalImageOptions",{image:void 0,sourceX:0,sourceY:0,width:void 0,height:void 0,depth:1,mipLevel:0,x:0,y:0,z:0,aspect:"all",colorSpace:"srgb",premultipliedAlpha:!1,flipY:!1}),d(Q,"defaultCopyElementImageOptions",{element:void 0,width:void 0,height:void 0,sourceX:0,sourceY:0,sourceWidth:void 0,sourceHeight:void 0,depth:1,mipLevel:0,x:0,y:0,z:0,aspect:"all",colorSpace:"srgb",premultipliedAlpha:!1,flipY:!1}),d(Q,"defaultTextureReadOptions",{x:0,y:0,z:0,width:void 0,height:void 0,depthOrArrayLayers:1,mipLevel:0,aspect:"all"}),d(Q,"defaultTextureWriteOptions",{byteOffset:0,bytesPerRow:void 0,rowsPerImage:void 0,x:0,y:0,z:0,width:void 0,height:void 0,depthOrArrayLayers:1,mipLevel:0,aspect:"all"});Y=Q});var kc,mn,db=b(()=>{ve();kc=class kc extends F{get[Symbol.toStringTag](){return"TextureView"}constructor(e,t){super(e,t,kc.defaultProps)}};d(kc,"defaultProps",{...F.defaultProps,format:void 0,dimension:void 0,aspect:"all",baseMipLevel:0,mipLevelCount:void 0,baseArrayLayer:0,arrayLayerCount:void 0});mn=kc});var Dc,Yo,hb=b(()=>{ve();Dc=class Dc extends F{constructor(t,n){super(t,n,Dc.defaultProps);d(this,"width");d(this,"height");d(this,"updateTimestamp");let i=this.props.source?t.getExternalImageSize(this.props.source):null;this.width=this.props.width||i?.width||0,this.height=this.props.height||i?.height||0,this.updateTimestamp=t.incrementTimestamp()}get[Symbol.toStringTag](){return"ExternalTexture"}};d(Dc,"defaultProps",{...F.defaultProps,source:void 0,width:0,height:0,colorSpace:"srgb",sampler:{}});Yo=Dc});function pb(r,e,t){let n="",i=e.split(/\r?\n/),o=r.slice().sort((s,a)=>s.lineNum-a.lineNum);switch(t?.showSourceCode||"no"){case"all":let s=0;for(let a=1;a<=i.length;a++){let c=i[a-1],l=o[s];for(c&&l&&(n+=mb(c,a,t));o.length>s&&l.lineNum===a;){let u=o[s++];u&&(n+=ah(u,i,u.lineNum,{...t,inlineSource:!1}))}}for(;o.length>s;){let a=o[s++];a&&(n+=ah(a,[],0,{...t,inlineSource:!1}))}return n;case"issues":case"no":for(let a of r)n+=ah(a,i,a.lineNum,{inlineSource:t?.showSourceCode!=="no"});return n}}function ah(r,e,t,n){if(n?.inlineSource){let o=nL(e,t),s=r.linePos>0?`${" ".repeat(r.linePos+5)}^^^
`:"";return`
${o}${s}${r.type.toUpperCase()}: ${r.message}

`}let i=r.type==="error"?"red":"orange";return n?.html?`<div class='luma-compiler-log-${r.type}' style="color:${i};"><b> ${r.type.toUpperCase()}: ${r.message}</b></div>`:`${r.type.toUpperCase()}: ${r.message}`}function nL(r,e,t){let n="";for(let i=e-2;i<=e;i++){let o=r[i-1];o!==void 0&&(n+=mb(o,e,t))}return n}function mb(r,e,t){let n=t?.html?oL(r):r;return`${iL(String(e),4)}: ${n}${t?.html?"<br/>":`
`}`}function iL(r,e){let t="";for(let n=r.length;n<e;++n)t+=" ";return t+r}function oL(r){return r.replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;").replaceAll("'","&#039;")}var gb=b(()=>{});function sL(r){return aL(r.source)||r.id||$t(`unnamed ${r.stage}-shader`)}function aL(r,e="unnamed"){return/#define[\s*]SHADER_NAME[\s*]([A-Za-z0-9_-]+)[\s*]/.exec(r)?.[1]??e}var Nc,gn,ch=b(()=>{ve();Ge();di();gb();Nc=class Nc extends F{constructor(t,n){n={...n,debugShaders:n.debugShaders||t.props.debugShaders||"errors"};super(t,{id:sL(n),...n},Nc.defaultProps);d(this,"stage");d(this,"source");d(this,"compilationStatus","pending");this.stage=this.props.stage,this.source=this.props.source}get[Symbol.toStringTag](){return"Shader"}getCompilationInfoSync(){return null}getTranslatedSource(){return null}async debugShader(){let t=this.props.debugShaders;switch(t){case"never":return;case"errors":if(this.compilationStatus==="success")return;break;case"warnings":case"always":break}try{let n=await this.getCompilationInfo();if(t==="warnings"&&n?.length===0)return;this._displayShaderLog(n,this.id)}catch(n){T.warn(`Shader ${this.id}: failed to fetch compilation info during debug logging`,n)()}}_displayShaderLog(t,n){if(typeof document>"u"||!document?.createElement)return;let i=n,o=`${this.stage} shader "${i}"`,s=pb(t,this.source,{showSourceCode:"all",html:!0}),a=this.getTranslatedSource(),c=document.createElement("div");c.innerHTML=`<h1>Compilation error in ${o}</h1>
<div style="display:flex;position:fixed;top:10px;right:20px;gap:2px;">
<button id="copy">Copy source</button><br/>
<button id="close">Close</button>
</div>
<code><pre>${s}</pre></code>`,a&&(c.innerHTML+=`<br /><h1>Translated Source</h1><br /><br /><code><pre>${a}</pre></code>`),c.style.top="0",c.style.left="0",c.style.background="white",c.style.position="fixed",c.style.zIndex="9999",c.style.maxWidth="100vw",c.style.maxHeight="100vh",c.style.overflowY="auto",document.body.appendChild(c),c.querySelector(".luma-compiler-log-error")?.scrollIntoView(),c.querySelector("button#close").onclick=()=>{c.remove()},c.querySelector("button#copy").onclick=()=>{navigator.clipboard.writeText(this.source)}}};d(Nc,"defaultProps",{...F.defaultProps,language:"auto",stage:void 0,source:"",sourceMap:null,entryPoint:"main",debugShaders:void 0});gn=Nc});var Fc,yn,yb=b(()=>{ve();sh();Ge();Fc=class Fc extends F{constructor(t,n={}){super(t,n,Fc.defaultProps);d(this,"width");d(this,"height");this.width=this.props.width,this.height=this.props.height}get[Symbol.toStringTag](){return"Framebuffer"}clone(t){let n=this.colorAttachments.map(o=>o.texture.clone(t)),i=this.depthStencilAttachment&&this.depthStencilAttachment.texture.clone(t);return this.device.createFramebuffer({...this.props,...t,colorAttachments:n,depthStencilAttachment:i})}resize(t){let n=!t;if(t){let[i,o]=Array.isArray(t)?t:[t.width,t.height];n=n||o!==this.height||i!==this.width,this.width=i,this.height=o}n&&(T.log(2,`Resizing framebuffer ${this.id} to ${this.width}x${this.height}`)(),this.resizeAttachments(this.width,this.height))}autoCreateAttachmentTextures(){if(this.props.colorAttachments.length===0&&!this.props.depthStencilAttachment)throw new Error("Framebuffer has noattachments");this.colorAttachments=this.props.colorAttachments.map((n,i)=>{if(typeof n=="string"){let o=this.createColorTexture(n,i);return this.attachResource(o),o.view}return n instanceof Y?n.view:n});let t=this.props.depthStencilAttachment;if(t)if(typeof t=="string"){let n=this.createDepthStencilTexture(t);this.attachResource(n),this.depthStencilAttachment=n.view}else t instanceof Y?this.depthStencilAttachment=t.view:this.depthStencilAttachment=t}createColorTexture(t,n){return this.device.createTexture({id:`${this.id}-color-attachment-${n}`,usage:Y.RENDER_ATTACHMENT,format:t,width:this.width,height:this.height,sampler:{magFilter:"linear",minFilter:"linear"}})}createDepthStencilTexture(t){return this.device.createTexture({id:`${this.id}-depth-stencil-attachment`,usage:Y.RENDER_ATTACHMENT|Y.SAMPLE,format:t,width:this.width,height:this.height})}resizeAttachments(t,n){if(this.colorAttachments.forEach((i,o)=>{let s=i.texture.clone({width:t,height:n});this.destroyAttachedResource(i),this.colorAttachments[o]=s.view,this.attachResource(s.view)}),this.depthStencilAttachment){let i=this.depthStencilAttachment.texture.clone({width:t,height:n});this.destroyAttachedResource(this.depthStencilAttachment),this.depthStencilAttachment=i.view,this.attachResource(i)}this.updateAttachments()}};d(Fc,"defaultProps",{...F.defaultProps,width:1,height:1,colorAttachments:[],depthStencilAttachment:null});yn=Fc});var Uc,ft,lh=b(()=>{ve();Uc=class Uc extends F{constructor(t,n){super(t,n,Uc.defaultProps);d(this,"shaderLayout");d(this,"bufferLayout");d(this,"linkStatus","pending");d(this,"hash","");d(this,"sharedRenderPipeline",null);this.shaderLayout=this.props.shaderLayout,this.bufferLayout=this.props.bufferLayout||[],this.sharedRenderPipeline=this.props._sharedRenderPipeline||null}get[Symbol.toStringTag](){return"RenderPipeline"}get isPending(){return this.linkStatus==="pending"||this.vs.compilationStatus==="pending"||this.fs?.compilationStatus==="pending"}get isErrored(){return this.linkStatus==="error"||this.vs.compilationStatus==="error"||this.fs?.compilationStatus==="error"}};d(Uc,"defaultProps",{...F.defaultProps,vs:null,vertexEntryPoint:"vertexMain",vsConstants:{},fs:null,fragmentEntryPoint:"fragmentMain",fsConstants:{},shaderLayout:null,bufferLayout:[],topology:"triangle-list",colorAttachmentFormats:void 0,depthStencilAttachmentFormat:void 0,parameters:{},varyings:void 0,bufferMode:void 0,disableWarnings:!1,_sharedRenderPipeline:void 0,_uniformBlockLayouts:[],bindings:void 0,bindGroups:void 0});ft=Uc});var qo,_b=b(()=>{ve();qo=class extends F{get[Symbol.toStringTag](){return"SharedRenderPipeline"}constructor(e,t){super(e,t,{...F.defaultProps,handle:void 0,vs:void 0,fs:void 0,varyings:void 0,bufferMode:void 0})}}});var Gc,kr,uh=b(()=>{ve();Gc=class Gc extends F{constructor(t,n){super(t,n,Gc.defaultProps);d(this,"hash","");d(this,"shaderLayout");this.shaderLayout=n.shaderLayout}get[Symbol.toStringTag](){return"ComputePipeline"}};d(Gc,"defaultProps",{...F.defaultProps,shader:void 0,entryPoint:void 0,constants:{},shaderLayout:void 0});kr=Gc});var zc,_n,bb=b(()=>{uh();lh();Ge();di();zc=class zc{constructor(e){d(this,"device");d(this,"_hashCounter",0);d(this,"_hashes",{});d(this,"_renderPipelineCache",{});d(this,"_computePipelineCache",{});d(this,"_sharedRenderPipelineCache",{});this.device=e}static getDefaultPipelineFactory(e){let t=e.getModuleData("@luma.gl/core");return t.defaultPipelineFactory||(t.defaultPipelineFactory=new zc(e)),t.defaultPipelineFactory}get[Symbol.toStringTag](){return"PipelineFactory"}toString(){return`PipelineFactory(${this.device.id})`}createRenderPipeline(e){if(!this.device.props._cachePipelines)return this.device.createRenderPipeline(e);let t={...ft.defaultProps,...e},n=this._renderPipelineCache,i=this._hashRenderPipeline(t),o=n[i]?.resource;if(o)n[i].useCount++,this.device.props.debugFactories&&T.log(3,`${this}: ${n[i].resource} reused, count=${n[i].useCount}, (id=${e.id})`)();else{let s=this.device.type==="webgl"&&this.device.props._sharePipelines?this.createSharedRenderPipeline(t):void 0;o=this.device.createRenderPipeline({...t,id:t.id?`${t.id}-cached`:$t("unnamed-cached"),_sharedRenderPipeline:s}),o.hash=i,n[i]={resource:o,useCount:1},this.device.props.debugFactories&&T.log(3,`${this}: ${o} created, count=${n[i].useCount}`)()}return o}createComputePipeline(e){if(!this.device.props._cachePipelines)return this.device.createComputePipeline(e);let t={...kr.defaultProps,...e},n=this._computePipelineCache,i=this._hashComputePipeline(t),o=n[i]?.resource;return o?(n[i].useCount++,this.device.props.debugFactories&&T.log(3,`${this}: ${n[i].resource} reused, count=${n[i].useCount}, (id=${e.id})`)()):(o=this.device.createComputePipeline({...t,id:t.id?`${t.id}-cached`:void 0}),o.hash=i,n[i]={resource:o,useCount:1},this.device.props.debugFactories&&T.log(3,`${this}: ${o} created, count=${n[i].useCount}`)()),o}release(e){if(!this.device.props._cachePipelines){e.destroy();return}let t=this._getCache(e),n=e.hash;t[n].useCount--,t[n].useCount===0?(this._destroyPipeline(e),this.device.props.debugFactories&&T.log(3,`${this}: ${e} released and destroyed`)()):t[n].useCount<0?(T.error(`${this}: ${e} released, useCount < 0, resetting`)(),t[n].useCount=0):this.device.props.debugFactories&&T.log(3,`${this}: ${e} released, count=${t[n].useCount}`)()}createSharedRenderPipeline(e){let t=this._hashSharedRenderPipeline(e),n=this._sharedRenderPipelineCache[t];return n||(n={resource:this.device._createSharedRenderPipelineWebGL(e),useCount:0},this._sharedRenderPipelineCache[t]=n),n.useCount++,n.resource}releaseSharedRenderPipeline(e){if(!e.sharedRenderPipeline)return;let t=this._hashSharedRenderPipeline(e.sharedRenderPipeline.props),n=this._sharedRenderPipelineCache[t];n&&(n.useCount--,n.useCount===0&&(n.resource.destroy(),delete this._sharedRenderPipelineCache[t]))}_destroyPipeline(e){let t=this._getCache(e);return this.device.props._destroyPipelines?(delete t[e.hash],e.destroy(),e instanceof ft&&this.releaseSharedRenderPipeline(e),!0):!1}_getCache(e){let t;if(e instanceof kr&&(t=this._computePipelineCache),e instanceof ft&&(t=this._renderPipelineCache),!t)throw new Error(`${this}`);if(!t[e.hash])throw new Error(`${this}: ${e} matched incorrect entry`);return t}_hashComputePipeline(e){let{type:t}=this.device,n=this._getHash(e.shader.source),i=this._getHash(JSON.stringify(e.shaderLayout));return`${t}/C/${n}SL${i}`}_hashRenderPipeline(e){let t=e.vs?this._getHash(e.vs.source):0,n=e.fs?this._getHash(e.fs.source):0,i=this._getWebGLVaryingHash(e),o=this._getHash(JSON.stringify(e.shaderLayout)),s=this._getHash(JSON.stringify(e._uniformBlockLayouts)),a=this._getHash(JSON.stringify(e.bufferLayout)),{type:c}=this.device;if(c==="webgl"){let l=this._getHash(JSON.stringify(e.parameters));return`${c}/R/${t}/${n}V${i}T${e.topology}P${l}SL${o}UBL${s}BL${a}`}else{let u=this._getHash(JSON.stringify({vertexEntryPoint:e.vertexEntryPoint,fragmentEntryPoint:e.fragmentEntryPoint})),f=this._getHash(JSON.stringify(e.parameters)),h=this._getWebGPUAttachmentHash(e);return`${c}/R/${t}/${n}V${i}T${e.topology}EP${u}P${f}SL${o}BL${a}A${h}`}}_hashSharedRenderPipeline(e){let t=e.vs?this._getHash(e.vs.source):0,n=e.fs?this._getHash(e.fs.source):0,i=this._getWebGLVaryingHash(e);return`webgl/S/${t}/${n}V${i}`}_getHash(e){return this._hashes[e]===void 0&&(this._hashes[e]=this._hashCounter++),this._hashes[e]}_getWebGLVaryingHash(e){let{varyings:t=[],bufferMode:n=null}=e;return this._getHash(JSON.stringify({varyings:t,bufferMode:n}))}_getWebGPUAttachmentHash(e){let t=e.colorAttachmentFormats??[this.device.preferredColorFormat],n=e.depthStencilAttachmentFormat??(e.parameters?.depthWriteEnabled?this.device.preferredDepthFormat:null);return this._getHash(JSON.stringify({colorAttachmentFormats:t,depthStencilAttachmentFormat:n}))}};d(zc,"defaultProps",{...ft.defaultProps});_n=zc});var $c,bn,xb=b(()=>{ch();Ge();$c=class $c{constructor(e){d(this,"device");d(this,"_cache",{});this.device=e}static getDefaultShaderFactory(e){let t=e.getModuleData("@luma.gl/core");return t.defaultShaderFactory||(t.defaultShaderFactory=new $c(e)),t.defaultShaderFactory}get[Symbol.toStringTag](){return"ShaderFactory"}toString(){return`${this[Symbol.toStringTag]}(${this.device.id})`}createShader(e){if(!this.device.props._cacheShaders)return this.device.createShader(e);let t=this._hashShader(e),n=this._cache[t];if(n)n.useCount++,this.device.props.debugFactories&&T.log(3,`${this}: Reusing shader ${n.resource.id} count=${n.useCount}`)();else{let i=this.device.createShader({...e,id:e.id?`${e.id}-cached`:void 0});this._cache[t]=n={resource:i,useCount:1},this.device.props.debugFactories&&T.log(3,`${this}: Created new shader ${i.id}`)()}return n.resource}release(e){if(!this.device.props._cacheShaders){e.destroy();return}let t=this._hashShader(e),n=this._cache[t];if(n)if(n.useCount--,n.useCount===0)this.device.props._destroyShaders&&(delete this._cache[t],n.resource.destroy(),this.device.props.debugFactories&&T.log(3,`${this}: Releasing shader ${e.id}, destroyed`)());else{if(n.useCount<0)throw new Error(`ShaderFactory: Shader ${e.id} released too many times`);this.device.props.debugFactories&&T.log(3,`${this}: Releasing shader ${e.id} count=${n.useCount}`)()}}_hashShader(e){return`${e.stage}:${e.source}`}};d($c,"defaultProps",{...gn.defaultProps});bn=$c});function Vc(r,e,t){let n=r.bindings.find(i=>i.name===e||`${i.name.toLocaleLowerCase()}uniforms`===e.toLocaleLowerCase());return!n&&!t?.ignoreWarnings&&T.warn(`Binding ${e} not set: Not found in shader layout.`)(),n||null}function xn(r,e){if(!e)return{};if(cL(e))return Object.fromEntries(Object.entries(e).map(([i,o])=>[Number(i),{...o}]));let t={};for(let[n,i]of Object.entries(e)){let s=Vc(r,n)?.group??0;t[s]||(t[s]={}),t[s][n]=i}return t}function mi(r){let e={};for(let t of Object.values(r))Object.assign(e,t);return e}function cL(r){let e=Object.keys(r);return e.length>0&&e.every(t=>/^\d+$/.test(t))}var vb=b(()=>{Ge()});var wt,Xo,wb=b(()=>{ve();wt=class wt extends F{get[Symbol.toStringTag](){return"RenderPass"}constructor(e,t,n=wt.defaultProps){t=wt.normalizeProps(e,t),super(e,t,n)}static normalizeProps(e,t){return t}};d(wt,"defaultClearColor",[0,0,0,1]),d(wt,"defaultClearDepth",1),d(wt,"defaultClearStencil",0),d(wt,"defaultProps",{...F.defaultProps,framebuffer:null,resolveTargets:void 0,parameters:void 0,clearColor:wt.defaultClearColor,clearColors:void 0,clearDepth:wt.defaultClearDepth,clearStencil:wt.defaultClearStencil,depthReadOnly:!1,stencilReadOnly:!1,discard:!1,occlusionQuerySet:void 0,timestampQuerySet:void 0,beginTimestampIndex:void 0,endTimestampIndex:void 0});Xo=wt});var Wc,Zo,Eb=b(()=>{ve();Wc=class Wc extends F{constructor(t,n){super(t,n,Wc.defaultProps);d(this,"_timeProfilingQuerySet",null);d(this,"_timeProfilingSlotCount",0);d(this,"_gpuTimeMs");this._timeProfilingQuerySet=n.timeProfilingQuerySet??null,this._timeProfilingSlotCount=0,this._gpuTimeMs=void 0}get[Symbol.toStringTag](){return"CommandEncoder"}async resolveTimeProfilingQuerySet(){if(this._gpuTimeMs=void 0,!this._timeProfilingQuerySet)return;let t=Math.floor(this._timeProfilingSlotCount/2);if(t<=0)return;let n=t*2,i=await this._timeProfilingQuerySet.readResults({firstQuery:0,queryCount:n}),o=0n;for(let s=0;s<n;s+=2)o+=i[s+1]-i[s];this._gpuTimeMs=Number(o)/1e6}getTimeProfilingSlotCount(){return this._timeProfilingSlotCount}getTimeProfilingQuerySet(){return this._timeProfilingQuerySet}_applyTimeProfilingToPassProps(t){let n=t||{};if(!this._supportsTimestampQueries()||!this._timeProfilingQuerySet||n.timestampQuerySet!==void 0||n.beginTimestampIndex!==void 0||n.endTimestampIndex!==void 0)return n;let i=this._timeProfilingSlotCount;return i+1>=this._timeProfilingQuerySet.props.count?n:(this._timeProfilingSlotCount+=2,{...n,timestampQuerySet:this._timeProfilingQuerySet,beginTimestampIndex:i,endTimestampIndex:i+1})}_supportsTimestampQueries(){return this.device.features.has("timestamp-query")}};d(Wc,"defaultProps",{...F.defaultProps,measureExecutionTime:void 0,timeProfilingQuerySet:void 0});Zo=Wc});var jc,Ko,Sb=b(()=>{ve();jc=class jc extends F{get[Symbol.toStringTag](){return"CommandBuffer"}constructor(e,t){super(e,t,jc.defaultProps)}};d(jc,"defaultProps",{...F.defaultProps});Ko=jc});var Hc,Qo,Pb=b(()=>{ve();Hc=class Hc extends F{constructor(t,n){super(t,n,Hc.defaultProps);d(this,"maxVertexAttributes");d(this,"indexBuffer",null);d(this,"attributes");this.maxVertexAttributes=t.limits.maxVertexAttributes,this.attributes=new Array(this.maxVertexAttributes).fill(null)}get[Symbol.toStringTag](){return"VertexArray"}getBufferSlot(t){return null}getDrawValidationError(){return null}setConstantWebGL(t,n){this.device.reportError(new Error("constant attributes not supported"),this)()}};d(Hc,"defaultProps",{...F.defaultProps,shaderLayout:void 0,bufferLayout:[]});Qo=Hc});var Yc,Jo,Tb=b(()=>{ve();Yc=class Yc extends F{get[Symbol.toStringTag](){return"TransformFeedback"}constructor(e,t){super(e,t,Yc.defaultProps)}};d(Yc,"defaultProps",{...F.defaultProps,layout:void 0,buffers:{}});Jo=Yc});var qc,es,Lb=b(()=>{ve();qc=class qc extends F{get[Symbol.toStringTag](){return"QuerySet"}constructor(e,t){super(e,t,qc.defaultProps)}};d(qc,"defaultProps",{...F.defaultProps,type:void 0,count:void 0});es=qc});var Xc,ts,Ab=b(()=>{ve();Xc=class Xc extends F{get[Symbol.toStringTag](){return"Fence"}constructor(e,t={}){super(e,t,Xc.defaultProps)}};d(Xc,"defaultProps",{...F.defaultProps});ts=Xc});function gi(r){let e=Zc(r),t=dL[e];if(!t)throw new Error(`Unsupported variable shader type: ${r}`);return t}function Cb(r){let e=Mb(r),t=fL[e];if(!t)throw new Error(`Unsupported attribute shader type: ${r}`);let[n,i]=t,o=n==="i32"||n==="u32",s=n!=="u32",a=uL[n]*i;return{primitiveType:n,components:i,byteLength:a,integer:o,signed:s}}function lL(r,e){return e===1?r:`vec${e}<${r}>`}function Mb(r){return hL[r]||r}function Zc(r){return pL[r]||r}var fh,nt,uL,fL,dL,hL,pL,rs=b(()=>{fh=class{getVariableShaderTypeInfo(e){return gi(e)}getAttributeShaderTypeInfo(e){return Cb(e)}makeShaderAttributeType(e,t){return lL(e,t)}resolveAttributeShaderTypeAlias(e){return Mb(e)}resolveVariableShaderTypeAlias(e){return Zc(e)}};nt=new fh,uL={f32:4,f16:2,i32:4,u32:4},fL={f32:["f32",1],"vec2<f32>":["f32",2],"vec3<f32>":["f32",3],"vec4<f32>":["f32",4],f16:["f16",1],"vec2<f16>":["f16",2],"vec3<f16>":["f16",3],"vec4<f16>":["f16",4],i32:["i32",1],"vec2<i32>":["i32",2],"vec3<i32>":["i32",3],"vec4<i32>":["i32",4],u32:["u32",1],"vec2<u32>":["u32",2],"vec3<u32>":["u32",3],"vec4<u32>":["u32",4]},dL={f32:{type:"f32",components:1},f16:{type:"f16",components:1},i32:{type:"i32",components:1},u32:{type:"u32",components:1},"vec2<f32>":{type:"f32",components:2},"vec3<f32>":{type:"f32",components:3},"vec4<f32>":{type:"f32",components:4},"vec2<f16>":{type:"f16",components:2},"vec3<f16>":{type:"f16",components:3},"vec4<f16>":{type:"f16",components:4},"vec2<i32>":{type:"i32",components:2},"vec3<i32>":{type:"i32",components:3},"vec4<i32>":{type:"i32",components:4},"vec2<u32>":{type:"u32",components:2},"vec3<u32>":{type:"u32",components:3},"vec4<u32>":{type:"u32",components:4},"mat2x2<f32>":{type:"f32",components:4},"mat2x3<f32>":{type:"f32",components:6},"mat2x4<f32>":{type:"f32",components:8},"mat3x2<f32>":{type:"f32",components:6},"mat3x3<f32>":{type:"f32",components:9},"mat3x4<f32>":{type:"f32",components:12},"mat4x2<f32>":{type:"f32",components:8},"mat4x3<f32>":{type:"f32",components:12},"mat4x4<f32>":{type:"f32",components:16},"mat2x2<f16>":{type:"f16",components:4},"mat2x3<f16>":{type:"f16",components:6},"mat2x4<f16>":{type:"f16",components:8},"mat3x2<f16>":{type:"f16",components:6},"mat3x3<f16>":{type:"f16",components:9},"mat3x4<f16>":{type:"f16",components:12},"mat4x2<f16>":{type:"f16",components:8},"mat4x3<f16>":{type:"f16",components:12},"mat4x4<f16>":{type:"f16",components:16},"mat2x2<i32>":{type:"i32",components:4},"mat2x3<i32>":{type:"i32",components:6},"mat2x4<i32>":{type:"i32",components:8},"mat3x2<i32>":{type:"i32",components:6},"mat3x3<i32>":{type:"i32",components:9},"mat3x4<i32>":{type:"i32",components:12},"mat4x2<i32>":{type:"i32",components:8},"mat4x3<i32>":{type:"i32",components:12},"mat4x4<i32>":{type:"i32",components:16},"mat2x2<u32>":{type:"u32",components:4},"mat2x3<u32>":{type:"u32",components:6},"mat2x4<u32>":{type:"u32",components:8},"mat3x2<u32>":{type:"u32",components:6},"mat3x3<u32>":{type:"u32",components:9},"mat3x4<u32>":{type:"u32",components:12},"mat4x2<u32>":{type:"u32",components:8},"mat4x3<u32>":{type:"u32",components:12},"mat4x4<u32>":{type:"u32",components:16}},hL={vec2i:"vec2<i32>",vec3i:"vec3<i32>",vec4i:"vec4<i32>",vec2u:"vec2<u32>",vec3u:"vec3<u32>",vec4u:"vec4<u32>",vec2f:"vec2<f32>",vec3f:"vec3<f32>",vec4f:"vec4<f32>",vec2h:"vec2<f16>",vec3h:"vec3<f16>",vec4h:"vec4<f16>"},pL={vec2i:"vec2<i32>",vec3i:"vec3<i32>",vec4i:"vec4<i32>",vec2u:"vec2<u32>",vec3u:"vec3<u32>",vec4u:"vec4<u32>",vec2f:"vec2<f32>",vec3f:"vec3<f32>",vec4f:"vec4<f32>",vec2h:"vec2<f16>",vec3h:"vec3<f16>",vec4h:"vec4<f16>",mat2x2f:"mat2x2<f32>",mat2x3f:"mat2x3<f32>",mat2x4f:"mat2x4<f32>",mat3x2f:"mat3x2<f32>",mat3x3f:"mat3x3<f32>",mat3x4f:"mat3x4<f32>",mat4x2f:"mat4x2<f32>",mat4x3f:"mat4x3<f32>",mat4x4f:"mat4x4<f32>",mat2x2i:"mat2x2<i32>",mat2x3i:"mat2x3<i32>",mat2x4i:"mat2x4<i32>",mat3x2i:"mat3x2<i32>",mat3x3i:"mat3x3<i32>",mat3x4i:"mat3x4<i32>",mat4x2i:"mat4x2<i32>",mat4x3i:"mat4x3<i32>",mat4x4i:"mat4x4<i32>",mat2x2u:"mat2x2<u32>",mat2x3u:"mat2x3<u32>",mat2x4u:"mat2x4<u32>",mat3x2u:"mat3x2<u32>",mat3x3u:"mat3x3<u32>",mat3x4u:"mat3x4<u32>",mat4x2u:"mat4x2<u32>",mat4x3u:"mat4x3<u32>",mat4x4u:"mat4x4<u32>",mat2x2h:"mat2x2<f16>",mat2x3h:"mat2x3<f16>",mat2x4h:"mat2x4<f16>",mat3x2h:"mat3x2<f16>",mat3x3h:"mat3x3<f16>",mat3x4h:"mat3x4<f16>",mat4x2h:"mat4x2<f16>",mat4x3h:"mat4x3<f16>",mat4x4h:"mat4x4<f16>"}});function vn(r,e={}){let t={...r},n=e.layout??"std140",i={},o=0;for(let[s,a]of Object.entries(t))o=dh(i,s,a,o,n);return o=ut(o,Dr(t,n)),{layout:n,byteLength:o*4,uniformTypes:t,fields:i}}function ns(r,e){let t=Zc(r),n=gi(t),i=/^mat(\d)x(\d)<.+>$/.exec(t);if(i){let s=Number(i[1]),a=Number(i[2]),c=Ib(a,t,n.type,e),l=gL(c.size,c.alignment,e);return{alignment:c.alignment,size:s*l,components:s*a,columns:s,rows:a,columnStride:l,shaderType:t,type:n.type}}let o=/^vec(\d)<.+>$/.exec(t);return o?Ib(Number(o[1]),t,n.type,e):{alignment:1,size:1,components:1,columns:1,rows:1,columnStride:1,shaderType:t,type:n.type}}function hh(r){return!!r&&typeof r=="object"&&!Array.isArray(r)}function dh(r,e,t,n,i){if(typeof t=="string"){let o=ns(t,i),s=ut(n,o.alignment);return r[e]={offset:s,...o},s+o.size}if(Array.isArray(t)){if(Array.isArray(t[0]))throw new Error(`Nested arrays are not supported for ${e}`);let o=t[0],s=t[1],a=Bb(o,i),c=ut(n,Dr(t,i));for(let l=0;l<s;l++)dh(r,`${e}[${l}]`,o,c+l*a,i);return c+a*s}if(hh(t)){let o=Dr(t,i),s=ut(n,o);for(let[a,c]of Object.entries(t))s=dh(r,`${e}.${a}`,c,s,i);return ut(s,o)}throw new Error(`Unsupported CompositeShaderType for ${e}`)}function Rb(r,e){if(typeof r=="string")return ns(r,e).size;if(Array.isArray(r)){let n=r[0],i=r[1];if(Array.isArray(n))throw new Error("Nested arrays are not supported");return Bb(n,e)*i}let t=0;for(let n of Object.values(r)){let i=n;t=ut(t,Dr(i,e)),t+=Rb(i,e)}return ut(t,Dr(r,e))}function Dr(r,e){if(typeof r=="string")return ns(r,e).alignment;if(Array.isArray(r)){let n=r[0],i=Dr(n,e);return Ob(e)?Math.max(i,4):i}let t=1;for(let n of Object.values(r)){let i=Dr(n,e);t=Math.max(t,i)}return yL(e)?Math.max(t,4):t}function Ib(r,e,t,n){return{alignment:r===2?2:4,size:r===3?3:r,components:r,columns:1,rows:r,columnStride:r===3?3:r,shaderType:e,type:t}}function Bb(r,e){let t=Rb(r,e),n=Dr(r,e);return mL(t,n,e)}function mL(r,e,t){return ut(r,Ob(t)?4:e)}function gL(r,e,t){return t==="std140"?4:ut(r,e)}function Ob(r){return r==="std140"||r==="wgsl-uniform"}function yL(r){return r==="std140"||r==="wgsl-uniform"}var Kc=b(()=>{Tc();rs()});function ph(r){return(!Qc||Qc.byteLength<r)&&(Qc=new ArrayBuffer(r)),Qc}function mh(r,e){let t=ph(r.BYTES_PER_ELEMENT*e);return new r(t,0,e)}var Qc,gh=b(()=>{});function _L(r){return ArrayBuffer.isView(r)&&!(r instanceof DataView)}function yi(r){return Array.isArray(r)?r.length===0||typeof r[0]=="number":_L(r)}var yh=b(()=>{});function bL(r){return!!r&&typeof r=="object"&&!Array.isArray(r)&&!ArrayBuffer.isView(r)}function xL(r,e,t){return Array.prototype.slice.call(r,e,t)}var Jc,kb=b(()=>{gh();yh();Ge();Kc();Jc=class{constructor(e){d(this,"layout");this.layout=e}has(e){return!!this.layout.fields[e]}get(e){let t=this.layout.fields[e];return t?{offset:t.offset,size:t.size}:void 0}getFlatUniformValues(e){let t={};for(let[n,i]of Object.entries(e)){let o=this.layout.uniformTypes[n];o?this._flattenCompositeValue(t,n,o,i):this.layout.fields[n]&&(t[n]=i)}return t}getData(e){let t=ph(this.layout.byteLength);new Uint8Array(t,0,this.layout.byteLength).fill(0);let n={i32:new Int32Array(t),u32:new Uint32Array(t),f32:new Float32Array(t),f16:new Uint16Array(t)},i=this.getFlatUniformValues(e);for(let[o,s]of Object.entries(i))this._writeLeafValue(n,o,s);return new Uint8Array(t,0,this.layout.byteLength)}_flattenCompositeValue(e,t,n,i){if(i!==void 0){if(typeof n=="string"||this.layout.fields[t]){e[t]=i;return}if(Array.isArray(n)){let o=n[0],s=n[1];if(Array.isArray(o))throw new Error(`Nested arrays are not supported for ${t}`);if(typeof o=="string"&&yi(i)){this._flattenPackedArray(e,t,o,s,i);return}if(!Array.isArray(i)){T.warn(`Unsupported uniform array value for ${t}:`,i)();return}for(let a=0;a<Math.min(i.length,s);a++){let c=i[a];c!==void 0&&this._flattenCompositeValue(e,`${t}[${a}]`,o,c)}return}if(hh(n)&&bL(i)){for(let[o,s]of Object.entries(i)){if(s===void 0)continue;let a=`${t}.${o}`;this._flattenCompositeValue(e,a,n[o],s)}return}T.warn(`Unsupported uniform value for ${t}:`,i)()}}_flattenPackedArray(e,t,n,i,o){let s=o,c=ns(n,this.layout.layout).components;for(let l=0;l<i;l++){let u=l*c;if(u>=s.length)break;c===1?e[`${t}[${l}]`]=Number(s[u]):e[`${t}[${l}]`]=xL(o,u,u+c)}}_writeLeafValue(e,t,n){let i=this.layout.fields[t];if(!i){T.warn(`Uniform ${t} not found in layout`)();return}let{type:o,components:s,columns:a,rows:c,offset:l,columnStride:u}=i,f=e[o];if(s===1){f[l]=Number(n);return}let h=n;if(a===1){for(let m=0;m<s;m++)f[l+m]=Number(h[m]??0);return}let p=0;for(let m=0;m<a;m++){let g=l+m*u;for(let y=0;y<c;y++)f[g+y]=Number(h[p++]??0)}}}});function Db(r,e,t=16){if(r===e)return!0;let n=r,i=e;if(!yi(n)||!yi(i)||n.length!==i.length)return!1;let o=Math.min(t,vL);if(n.length>o)return!1;for(let s=0;s<n.length;++s)if(i[s]!==n[s])return!1;return!0}function Nb(r){return yi(r)?r.slice():r}var vL,Fb=b(()=>{yh();vL=128});var el,Ub=b(()=>{Fb();el=class{constructor(e){d(this,"name");d(this,"uniforms",{});d(this,"modifiedUniforms",{});d(this,"modified",!0);d(this,"bindingLayout",{});d(this,"needsRedraw","initialized");if(this.name=e?.name||"unnamed",e?.name&&e?.shaderLayout){let t=e?.shaderLayout.bindings?.find(i=>i.type==="uniform"&&i.name===e?.name);if(!t)throw new Error(e?.name);let n=t;for(let i of n.uniforms||[])this.bindingLayout[i.name]=i}}setUniforms(e){for(let[t,n]of Object.entries(e))this._setUniform(t,n)&&!this.needsRedraw&&this.setNeedsRedraw(`${this.name}.${t}=${n}`)}setNeedsRedraw(e){this.needsRedraw=this.needsRedraw||e}getAllUniforms(){return this.modifiedUniforms={},this.needsRedraw=!1,this.uniforms||{}}_setUniform(e,t){return Db(this.uniforms[e],t)?!1:(this.uniforms[e]=Nb(t),this.modifiedUniforms[e]=!0,this.modified=!0,!0)}}});function EL(r){return r.type==="webgpu"?"wgsl-uniform":"std140"}var wL,wn,Gb=b(()=>{Sc();Ge();Kc();Ub();kb();wL=1024,wn=class{constructor(e,t){d(this,"device");d(this,"uniformBlocks",new Map);d(this,"shaderBlockLayouts",new Map);d(this,"shaderBlockWriters",new Map);d(this,"uniformBuffers",new Map);this.device=e;for(let[n,i]of Object.entries(t)){let o=n,s=vn(i.uniformTypes??{},{layout:i.layout??EL(e)}),a=new Jc(s);this.shaderBlockLayouts.set(o,s),this.shaderBlockWriters.set(o,a);let c=new el({name:n});c.setUniforms(a.getFlatUniformValues(i.defaultUniforms||{})),this.uniformBlocks.set(o,c)}}destroy(){for(let e of this.uniformBuffers.values())e.destroy()}setUniforms(e,t){for(let[n,i]of Object.entries(e)){let o=n,a=this.shaderBlockWriters.get(o)?.getFlatUniformValues(i||{});this.uniformBlocks.get(o)?.setUniforms(a||{})}this.updateUniformBuffers(t)}getUniformBufferByteLength(e){let t=this.shaderBlockLayouts.get(e)?.byteLength||0;return Math.max(t,wL)}getUniformBufferData(e){let t=this.uniformBlocks.get(e)?.getAllUniforms()||{};return this.shaderBlockWriters.get(e)?.getData(t)||new Uint8Array(0)}createUniformBuffer(e,t){t&&this.setUniforms(t);let n=this.getUniformBufferByteLength(e),i=this.device.createBuffer({usage:z.UNIFORM|z.COPY_DST,byteLength:n}),o=this.getUniformBufferData(e);return i.write(o),i}getManagedUniformBuffer(e){if(!this.uniformBuffers.get(e)){let t=this.getUniformBufferByteLength(e),n=this.device.createBuffer({usage:z.UNIFORM|z.COPY_DST,byteLength:t});this.uniformBuffers.set(e,n)}return this.uniformBuffers.get(e)}updateUniformBuffers(e){let t=!1;for(let n of this.uniformBlocks.keys()){let i=this.updateUniformBuffer(n,e);t||(t=i)}return t&&T.log(3,`UniformStore.updateUniformBuffers(): ${t}`)(),t}updateUniformBuffer(e,t){let n=this.uniformBlocks.get(e),i=this.uniformBuffers.get(e),o=!1;if(i&&n?.needsRedraw){o||(o=n.needsRedraw);let s=this.getUniformBufferData(e);i=this.uniformBuffers.get(e),i&&(t?this.device.writeBufferViaCommandEncoder(t,i,s):i.write(s));let a=this.uniformBlocks.get(e)?.getAllUniforms();T.log(4,`Writing to uniform buffer ${String(e)}`,s,a)()}return o}}});function _i(r){return r.attributes?r.attributes.map(e=>e.attribute):[r.name]}function _h(r){return Object.fromEntries(r.attributes.map(e=>[e.name,e.location]))}function tl(r){let e=1/0;for(let t of r)t!==void 0&&(e=Math.min(e,t));return e}function bh(r,e,t){SL(e);let n=new Map;for(let i of e){let o=PL(i);if(i.attributes)for(let s of i.attributes)n.has(s.attribute)||n.set(s.attribute,{bufferName:i.name,stepMode:i.stepMode,vertexFormat:s.format,byteOffset:s.byteOffset,byteStride:o});else i.format&&!n.has(i.name)&&n.set(i.name,{bufferName:i.name,stepMode:i.stepMode,vertexFormat:i.format,byteOffset:0,byteStride:o})}return r.attributes.map(i=>{let o=n.get(i.name);!o&&t?.warnOnMissingBufferLayout&&T.warn(`layout for attribute "${i.name}" not present in buffer layout`)();let s=nt.getAttributeShaderTypeInfo(i.type),a=o?.vertexFormat||ne.getCompatibleVertexFormat(s);return{attributeName:i.name,bufferName:o?.bufferName||i.name,location:i.location,vertexFormat:a,byteOffset:o?.byteOffset??0,byteStride:o?.byteStride??ne.getVertexFormatInfo(a).byteLength,stepMode:o?.stepMode||i.stepMode||(i.name.startsWith("instance")?"instance":"vertex")}}).sort((i,o)=>i.location-o.location)}function SL(r){for(let e of r)(e.attributes&&e.format||!e.attributes&&!e.format)&&T.warn(`BufferLayout ${e.name} must have either 'attributes' or 'format' field`)()}function PL(r){if(typeof r.byteStride=="number")return r.byteStride;if(r.attributes){let e=0;for(let t of r.attributes)e+=ne.getVertexFormatInfo(t.format).byteLength;return e}return ne.getVertexFormatInfo(r.format).byteLength}var xh=b(()=>{Ge();rs();$o()});function is(r,e){let t={},n=bh(r,e,{warnOnMissingBufferLayout:!0});for(let i of n){let o=TL(r,i);t[i.attributeName]=o}return t}function TL(r,e){let t=LL(r,e.attributeName),n=nt.getAttributeShaderTypeInfo(t.type),i=e.vertexFormat,o=ne.getVertexFormatInfo(i);return{attributeName:e.attributeName,bufferName:e.bufferName,location:t.location,shaderType:t.type,primitiveType:n.primitiveType,shaderComponents:n.components,vertexFormat:i,bufferDataType:o.type,bufferComponents:o.components,normalized:o.normalized,integer:n.integer,stepMode:e.stepMode,byteOffset:e.byteOffset,byteStride:e.byteStride}}function LL(r,e){let t=r.attributes.find(n=>n.name===e);return t||T.warn(`shader layout attribute "${e}" not present in shader`)(),t||null}var zb=b(()=>{Ge();rs();$o();xh()});var N=b(()=>{D_();N_();ib();ub();fb();Sc();sh();db();hb();ch();oh();yb();lh();_b();bb();xb();wb();uh();Eb();Sb();Pb();Tb();Lb();Ab();Kc();Gb();Lc();Tc();rs();$o();Rc();Ge();vb();nh();gh();zb();xh()});function os(r=[],e){let t=[],n={},i={},o={},s={};for(let a of r)$b({modules:t,defines:n,injections:i,vertexInputs:o,varyings:s},a),$b({modules:t,defines:n,injections:i,vertexInputs:o,varyings:s},a[e]);for(let a of Object.keys(s))if(o[a])throw new Error(`ShaderPlugin name "${a}" cannot be both a vertex input and a varying`);return{modules:t,defines:n,injections:i,vertexInputs:o,varyings:s}}function ss(r=[],e=[]){let t=[...r],n=new Set(t.map(i=>i.name));for(let i of e)n.has(i.name)||(t.push(i),n.add(i.name));return t}function $b(r,e){if(e){e.modules?.length&&r.modules.push(...e.modules),e.defines&&Object.assign(r.defines,e.defines);for(let[t,n]of Object.entries(e.vertexInputs||{})){Vb(t,"vertex input");let i=r.vertexInputs[t];if(i&&i!==n)throw new Error(`ShaderPlugin vertex input "${t}" has conflicting types "${i}" and "${n}"`);r.vertexInputs[t]=n}for(let[t,n]of Object.entries(e.varyings||{})){Vb(t,"varying");let i=CL(t,n),o=r.varyings[t];if(o&&(o.type!==i.type||o.interpolation!==i.interpolation))throw new Error(`ShaderPlugin varying "${t}" has conflicting declarations "${o.type}/${o.interpolation}" and "${i.type}/${i.interpolation}"`);r.varyings[t]=i}for(let t of e.injections||[])ML(t.target),r.injections[t.target]||(r.injections[t.target]=[]),r.injections[t.target].push({injection:t.injection,order:t.order??0})}}function Vb(r,e){if(!/^[A-Za-z_][A-Za-z0-9_]*$/.test(r)||r.startsWith("_luma_"))throw new Error(`ShaderPlugin ${e} "${r}" must be a valid non-reserved identifier`)}function CL(r,e){let{primitiveType:t}=nt.getAttributeShaderTypeInfo(e.type),n=t==="i32"||t==="u32",i=e.interpolation||(n?"flat":"smooth");if(n&&i==="smooth")throw new Error(`ShaderPlugin integer varying "${r}" must use flat interpolation`);return{type:e.type,interpolation:i}}function ML(r){if(!AL.test(r))throw new Error(`ShaderPlugin injection target "${r}" must be a named shader anchor or hook`)}var AL,Wb=b(()=>{N();AL=/^(vs|fs):(?:#(?:decl|main-start|main-end)|[A-Za-z_][\w-]*)$/});function as(r){return`${r.name}Uniforms`}function Hb(r,e){let t=e==="wgsl"?r.source:e==="vertex"?r.vs:r.fs;if(!t)return null;let n=as(r);return BL(t,e==="wgsl"?"wgsl":"glsl",n)}function Yb(r,e){let t=Object.keys(r.uniformTypes||{});if(!t.length)return null;let n=Hb(r,e);return n?{moduleName:r.name,uniformBlockName:as(r),stage:e,expectedUniformNames:t,actualUniformNames:n,matches:DL(t,n)}:null}function vh(r,e,t={}){let n=Yb(r,e);if(!n||n.matches)return n;let i=NL(n);return t.log?.error?.(i,n)(),t.throwOnError!==!1&&dr(!1,i),n}function cs(r){let e=[],t=FL(r);for(let n of t.matchAll(RL)){let i=n[1]?.trim()||null;e.push({blockName:n[2],body:n[3],instanceName:n[4]||null,layoutQualifier:i,hasLayoutQualifier:!!i,isStd140:!!(i&&/\blayout\s*\([^)]*\bstd140\b[^)]*\)/.exec(i))})}return e}function wh(r,e,t,n){let i=cs(r).filter(s=>!s.isStd140),o=new Set;for(let s of i){if(o.has(s.blockName))continue;o.add(s.blockName);let a=n?.label?`${n.label} `:"",c=s.hasLayoutQualifier?`declares ${UL(s.layoutQualifier)} instead of layout(std140)`:"does not declare layout(std140)",l=`${a}${e} shader uniform block ${s.blockName} ${c}. luma.gl host-side shader block packing assumes explicit layout(std140) for GLSL uniform blocks. Add \`layout(std140)\` to the block declaration.`;t?.warn?.(l,s)()}return i}function BL(r,e,t){let n=e==="wgsl"?OL(r,t):kL(r,t);if(!n)return null;let i=[];for(let o of n.split(`
`)){let s=o.replace(/\/\/.*$/,"").trim();if(!s||s.startsWith("#"))continue;let a=e==="wgsl"?s.match(/^([A-Za-z0-9_]+)\s*:/):s.match(IL);a&&i.push(a[1])}return i}function OL(r,e){let t=new RegExp(`\\bstruct\\s+${e}\\b`,"m").exec(r);if(!t)return null;let n=r.indexOf("{",t.index);if(n<0)return null;let i=0;for(let o=n;o<r.length;o++){let s=r[o];if(s==="{"){i++;continue}if(s==="}"&&(i--,i===0))return r.slice(n+1,o)}return null}function kL(r,e){return cs(r).find(n=>n.blockName===e)?.body||null}function DL(r,e){if(r.length!==e.length)return!1;for(let t=0;t<r.length;t++)if(r[t]!==e[t])return!1;return!0}function NL(r){let{expectedUniformNames:e,actualUniformNames:t}=r,n=e.filter(a=>!t.includes(a)),i=t.filter(a=>!e.includes(a)),o=[`Expected ${e.length} fields, found ${t.length}.`],s=GL(e,t);return s&&o.push(s),n.length&&o.push(`Missing from shader block (${n.length}): ${jb(n)}.`),i.length&&o.push(`Unexpected in shader block (${i.length}): ${jb(i)}.`),e.length<=12&&t.length<=12&&(n.length||i.length)&&(o.push(`Expected: ${e.join(", ")}.`),o.push(`Actual: ${t.join(", ")}.`)),`${r.moduleName}: ${r.stage} shader uniform block ${r.uniformBlockName} does not match module.uniformTypes. ${o.join(" ")}`}function FL(r){return r.replace(/\/\*[\s\S]*?\*\//g,"").replace(/\/\/.*$/gm,"")}function UL(r){return r.replace(/\s+/g," ").trim()}function GL(r,e){let t=Math.min(r.length,e.length);for(let n=0;n<t;n++)if(r[n]!==e[n])return`First mismatch at field ${n+1}: expected ${r[n]}, found ${e[n]}.`;return r.length>e.length?`Shader block ends after field ${e.length}; expected next field ${r[e.length]}.`:e.length>r.length?`Shader block has extra field ${e.length}: ${e[r.length]}.`:null}function jb(r,e=8){if(r.length<=e)return r.join(", ");let t=r.length-e;return`${r.slice(0,e).join(", ")}, ... (${t} more)`}var IL,RL,Eh=b(()=>{_c();IL=/^(?:uniform\s+)?(?:(?:lowp|mediump|highp)\s+)?[A-Za-z0-9_]+(?:<[^>]+>)?\s+([A-Za-z0-9_]+)(?:\s*\[[^\]]+\])?\s*;/,RL=/((?:layout\s*\([^)]*\)\s*)*)uniform\s+([A-Za-z_][A-Za-z0-9_]*)\s*\{([\s\S]*?)\}\s*([A-Za-z_][A-Za-z0-9_]*)?\s*;/g});function qb(r){switch(r?.gpu.toLowerCase()){case"apple":return`#define APPLE_GPU
// Apple optimizes away the calculation necessary for emulated fp64
#define LUMA_FP64_CODE_ELIMINATION_WORKAROUND 1
#define LUMA_FP32_TAN_PRECISION_WORKAROUND 1
// Intel GPU doesn't have full 32 bits precision in same cases, causes overflow
#define LUMA_FP64_HIGH_BITS_OVERFLOW_WORKAROUND 1
`;case"nvidia":return`#define NVIDIA_GPU
// Nvidia optimizes away the calculation necessary for emulated fp64
#define LUMA_FP64_CODE_ELIMINATION_WORKAROUND 1
`;case"intel":return`#define INTEL_GPU
// Intel optimizes away the calculation necessary for emulated fp64
#define LUMA_FP64_CODE_ELIMINATION_WORKAROUND 1
// Intel's built-in 'tan' function doesn't have acceptable precision
#define LUMA_FP32_TAN_PRECISION_WORKAROUND 1
// Intel GPU doesn't have full 32 bits precision in same cases, causes overflow
#define LUMA_FP64_HIGH_BITS_OVERFLOW_WORKAROUND 1
`;case"amd":return`#define AMD_GPU
`;default:return`#define DEFAULT_GPU
// Prevent driver from optimizing away the calculation necessary for emulated fp64
#define LUMA_FP64_CODE_ELIMINATION_WORKAROUND 1
// Headless Chrome's software shader 'tan' function doesn't have acceptable precision
#define LUMA_FP32_TAN_PRECISION_WORKAROUND 1
// If the GPU doesn't have full 32 bits precision, will causes overflow
#define LUMA_FP64_HIGH_BITS_OVERFLOW_WORKAROUND 1
`}}var Xb=b(()=>{});function Kb(r,e){if(Number(r.match(/^#version[ \t]+(\d+)/m)?.[1]||100)!==300)throw new Error("luma.gl v9 only supports GLSL 3.00 shader sources");switch(e){case"vertex":return r=Zb(r,zL),r;case"fragment":return r=Zb(r,$L),r;default:throw new Error(e)}}function Zb(r,e){for(let[t,n]of e)r=r.replace(t,n);return r}function Sh(r){return new RegExp(`\\b${r}[ \\t]+(\\w+[ \\t]+\\w+(\\[\\w+\\])?;)`,"g")}var Qb,zL,$L,Jb=b(()=>{Qb=[[/^(#version[ \t]+(100|300[ \t]+es))?[ \t]*\n/,`#version 300 es
`],[/\btexture(2D|2DProj|Cube)Lod(EXT)?\(/g,"textureLod("],[/\btexture(2D|2DProj|Cube)(EXT)?\(/g,"texture("]],zL=[...Qb,[Sh("attribute"),"in $1"],[Sh("varying"),"out $1"]],$L=[...Qb,[Sh("varying"),"in $1"]]});function rl(r,e,t="glsl"){let n="";for(let i in r){let o=r[i];if(n+=`${t==="wgsl"?"fn":"void"} ${o.signature} {
`,o.header&&(n+=`  ${o.header}`),e[i]){let a=e[i];a.sort((c,l)=>c.order-l.order);for(let c of a)n+=`  ${c.injection}
`}o.footer&&(n+=`  ${o.footer}`),n+=`}
`}return n}function Ph(r){let e={vertex:{},fragment:{}};for(let t of r){let n,i;typeof t!="string"?(n=t,i=n.hook):(n={},i=t),i=i.trim();let o=i.indexOf(":"),s=i.slice(0,o),a=i.slice(o+1),c=i.replace(/\(.+/,""),l=Object.assign(n,{signature:a});switch(s){case"vs":e.vertex[c]=l;break;case"fs":e.fragment[c]=l;break;default:throw new Error(s)}}return e}var ex=b(()=>{});function tx(r,e){return{name:VL(r,e),language:"glsl",version:WL(r)}}function VL(r,e="unnamed"){let n=/#define[^\S\r\n]*SHADER_NAME[^\S\r\n]*([A-Za-z0-9_-]+)\s*/.exec(r);return n?n[1]:e}function WL(r){let e=100,t=r.match(/[^\s]+/g);if(t&&t.length>=2&&t[0]==="#version"){let n=parseInt(t[1],10);Number.isFinite(n)&&(e=n)}if(e!==100&&e!==300)throw new Error(`Invalid GLSL version ${e}`);return e}var rx=b(()=>{});function nl(r,e=[]){let t=li(r),n=new Map;for(let o of e)n.set(ix(o.name,o.group,o.location),o.moduleName);let i=[];for(let o of nx){o.lastIndex=0;let s;for(s=o.exec(t);s;){let a=o===nx[0],c=Number(s[a?1:2]),l=Number(s[a?2:1]),u=s[3]?.trim(),f=s[4],h=s[5].trim(),p=n.get(ix(f,l,c));i.push(jL({name:f,group:l,binding:c,owner:p?"module":"application",moduleName:p,accessDeclaration:u,resourceType:h})),s=o.exec(t)}}return i.sort((o,s)=>o.group!==s.group?o.group-s.group:o.binding!==s.binding?o.binding-s.binding:o.name.localeCompare(s.name))}function jL(r){let e={name:r.name,group:r.group,binding:r.binding,owner:r.owner,kind:"unknown",moduleName:r.moduleName,resourceType:r.resourceType};if(r.accessDeclaration){let t=r.accessDeclaration.split(",").map(n=>n.trim());if(t[0]==="uniform")return{...e,kind:"uniform",access:"uniform"};if(t[0]==="storage"){let n=t[1]||"read_write";return{...e,kind:n==="read"?"read-only-storage":"storage",access:n}}}return r.resourceType==="sampler"||r.resourceType==="sampler_comparison"?{...e,kind:"sampler",samplerKind:r.resourceType==="sampler_comparison"?"comparison":"filtering"}:r.resourceType.startsWith("texture_storage_")?{...e,kind:"storage-texture",access:YL(r.resourceType),viewDimension:ox(r.resourceType)}:r.resourceType.startsWith("texture_")?{...e,kind:"texture",viewDimension:ox(r.resourceType),sampleType:HL(r.resourceType),multisampled:r.resourceType.startsWith("texture_multisampled_")}:e}function ix(r,e,t){return`${e}:${t}:${r}`}function ox(r){if(r.includes("cube_array"))return"cube-array";if(r.includes("2d_array"))return"2d-array";if(r.includes("cube"))return"cube";if(r.includes("3d"))return"3d";if(r.includes("2d"))return"2d";if(r.includes("1d"))return"1d"}function HL(r){if(r.startsWith("texture_depth_"))return"depth";if(r.includes("<i32>"))return"sint";if(r.includes("<u32>"))return"uint";if(r.includes("<f32>"))return"float"}function YL(r){return/,\s*([A-Za-z_][A-Za-z0-9_]*)\s*>$/.exec(r)?.[1]}var nx,Th=b(()=>{pc();nx=[new RegExp(`@binding\\(\\s*(\\d+)\\s*\\)\\s*@group\\(\\s*(\\d+)\\s*\\)\\s*${rt}\\s*:\\s*([^;]+);`,"g"),new RegExp(`@group\\(\\s*(\\d+)\\s*\\)\\s*@binding\\(\\s*(\\d+)\\s*\\)\\s*${rt}\\s*:\\s*([^;]+);`,"g")]});function Sn(r,e){let t=r.split(`
`),n=[],i=[],o=!0;for(let s of t){let a=s.match(qL),c=s.match(JL)||s.match(XL),l=s.match(ZL),u=s.match(KL),f=s.match(eA)||s.match(QL);if(a){let h=tA(a[1],e?.defines||{}),p=o&&h;i.push({parentActive:o,branchTaken:h,active:p}),o=p}else if(c||l){let h=(c||l)?.[1],p=!!e?.defines?.[h],m=c?p:!p,g=o&&m;i.push({parentActive:o,branchTaken:m,active:g}),o=g}else if(u){let h=i[i.length-1];if(!h)throw new Error("Encountered #else without matching #if, #ifdef or #ifndef");h.active=h.parentActive&&!h.branchTaken,h.branchTaken=!0,o=h.active}else f?(i.pop(),o=i.length?i[i.length-1].active:!0):o&&n.push(s)}if(i.length>0)throw new Error("Unterminated conditional block in shader source");return n.join(`
`)}function tA(r,e){let t=r.trim();if(/^[+-]?\d+(?:\.\d+)?$/.test(t))return Number(t)!==0;if(t==="true")return!0;if(t==="false")return!1;let n=t.match(new RegExp(`^!\\s*${En}$`));if(n)return!e[n[1]];let i=t.match(new RegExp(`^${En}$`));if(i)return!!e[i[1]];let o=t.match(new RegExp(`^defined\\s*\\(\\s*${En}\\s*\\)$`));if(o)return e[o[1]]!==void 0;let s=t.match(new RegExp(`^!\\s*defined\\s*\\(\\s*${En}\\s*\\)$`));if(s)return e[s[1]]===void 0;throw new Error(`Unsupported #if expression "${r}"`)}var En,qL,XL,ZL,KL,QL,JL,eA,Lh=b(()=>{En="([a-zA-Z_][a-zA-Z0-9_]*)",qL=/^\s*\#\s*if\s+(.+?)\s*(?:\/\/.*)?$/,XL=new RegExp(`^\\s*\\#\\s*ifdef\\s*${En}\\s*$`),ZL=new RegExp(`^\\s*\\#\\s*ifndef\\s*${En}\\s*(?:\\/\\/.*)?$`),KL=/^\s*\#\s*else\s*(?:\/\/.*)?$/,QL=/^\s*\#\s*endif\s*$/,JL=new RegExp(`^\\s*\\#\\s*ifdef\\s*${En}\\s*(?:\\/\\/.*)?$`),eA=/^\s*\#\s*endif\s*(?:\/\/.*)?$/});function cx(r,e){let t=[];for(let[n,i]of Object.entries(e))rA(r,n),t.push(`in ${il(i)} ${n};`);return t.join(`
`)}function lx(r,e,t){let n=Object.entries(t);if(n.length===0)return{source:r,declarations:"",initialization:""};let i=nA(r,e),o=r.slice(i.openParenthesis+1,i.closeParenthesis),s=iA(r,o),a=new Set(s.locations),c=[],l=[],u=[];for(let[g,y]of n){if(s.names.has(g)||aA(r,g))throw new Error(`ShaderPlugin vertex input "${g}" conflicts with an existing WGSL shader input or variable`);let x=cA(a);a.add(x);let v=`_luma_${g}`;c.push(`@location(${x}) ${v}: ${y}`),l.push(`var<private> ${g}: ${y};`),u.push(`${g} = ${v};`)}let f=o.trim()?`,
  `:`
  `,h=o.trim()?"":`
`,p=`${o}${f}${c.join(`,
  `)}${h}`;return{source:r.slice(0,i.openParenthesis+1)+p+r.slice(i.closeParenthesis),declarations:l.join(`
`),initialization:u.join(`
`)}}function il(r){let{primitiveType:e,components:t}=nt.getAttributeShaderTypeInfo(r),n=e==="i32"?"int":e==="u32"?"uint":"float";return t===1?n:`${n==="int"?"i":n==="uint"?"u":""}vec${t}`}function rA(r,e){let t=ol(e);if(new RegExp(`\\b(?:in|attribute)\\s+(?:(?:lowp|mediump|highp)\\s+)?[A-Za-z_][A-Za-z0-9_]*\\s+${t}\\s*(?:\\[|;)`).test(r))throw new Error(`ShaderPlugin vertex input "${e}" conflicts with an existing GLSL input`)}function nA(r,e){let n=new RegExp(`\\bfn\\s+${ol(e)}\\s*\\(`,"g").exec(r);if(!n)throw new Error(`ShaderPlugin vertex inputs require WGSL vertex entry point "${e}"`);let i=r.indexOf("(",n.index),o=ux(r,i,"(",")");if(o<0)throw new Error(`Unable to parse WGSL vertex entry point "${e}" parameters`);return{openParenthesis:i,closeParenthesis:o}}function iA(r,e){let t=sx(e),n=new Set(ax(e)),i=oA(e);for(let o of i){let s=sA(r,o);if(s!==null){t.push(...sx(s));for(let a of ax(s))n.add(a)}}return{locations:t,names:n}}function sx(r){let e=[],t=/@location\s*\(\s*(\d+)\s*\)/g,n=t.exec(r);for(;n;)e.push(Number(n[1])),n=t.exec(r);return e}function ax(r){let e=[],t=/(?:^|,)\s*(?:@[A-Za-z_][\w]*(?:\([^)]*\))?\s*)*([A-Za-z_][\w]*)\s*:/gm,n=t.exec(r);for(;n;)e.push(n[1]),n=t.exec(r);return e}function oA(r){let e=[],t=/:\s*([A-Za-z_][\w]*)\b/g,n=t.exec(r);for(;n;)e.push(n[1]),n=t.exec(r);return e}function sA(r,e){let n=new RegExp(`\\bstruct\\s+${ol(e)}\\s*\\{`,"g").exec(r);if(!n)return null;let i=r.indexOf("{",n.index),o=ux(r,i,"{","}");return o<0?null:r.slice(i+1,o)}function aA(r,e){let t=ol(e),n=new RegExp(`\\b(?:var(?:<[^>]+>)?|let|const)\\s+${t}\\b`,"g"),i=n.exec(r);for(;i;){if(lA(r,i.index)===0)return!0;i=n.exec(r)}return!1}function cA(r){let e=0;for(;r.has(e);)e++;return e}function ux(r,e,t,n){let i=0,o=0,s=!1;for(let a=e;a<r.length;a++){let c=r[a],l=r[a+1];if(s){c===`
`&&(s=!1);continue}if(o>0){c==="/"&&l==="*"?(o++,a++):c==="*"&&l==="/"&&(o--,a++);continue}if(c==="/"&&l==="/"){s=!0,a++;continue}if(c==="/"&&l==="*"){o=1,a++;continue}if(c===t&&i++,c===n&&--i===0)return a}return-1}function lA(r,e){let t=0,n=0,i=!1;for(let o=0;o<e;o++){let s=r[o],a=r[o+1];if(i){s===`
`&&(i=!1);continue}if(n>0){s==="/"&&a==="*"?(n++,o++):s==="*"&&a==="/"&&(n--,o++);continue}s==="/"&&a==="/"?(i=!0,o++):s==="/"&&a==="*"?(n=1,o++):s==="{"?t++:s==="}"&&t--}return t}function ol(r){return r.replace(/[.*+?^${}()|[\]\\]/g,"\\$&")}var Ah=b(()=>{N()});function dx(r,e,t){let n=[],i=[];for(let[o,s]of Object.entries(t)){wA(r,o);let a=s.interpolation==="flat"?"flat ":"",c=e==="vertex"?"out":"in";n.push(`${a}${c} ${il(s.type)} ${o};`),e==="vertex"&&i.push(`${o} = ${xA(s.type)};`)}return{declarations:n.join(`
`),initialization:i.join(`
`)}}function hx(r,e,t,n){let i=Object.entries(n);if(i.length===0)return{source:r,declarations:"",vertexInitialization:"",fragmentInitialization:""};let o=r,s=sl(o,e,"vertex"),a=uA(o,s),c=sl(o,t,"fragment"),l=fA(o,c),u=Ch(o,a),f=Ch(o,l.type),h=new Set([...al(s.parameters),...al(u.body),...al(c.parameters),...al(f.body)]),p=new Set([...fx(u.body),...fx(f.body)]),m=[],g=[],y=[],x=[];for(let[E,S]of i){if(h.has(E)||_A(o,E))throw new Error(`ShaderPlugin varying "${E}" conflicts with existing WGSL stage I/O or a module variable`);let C=bA(p);p.add(C);let A=S.interpolation==="flat"?" @interpolate(flat)":"";m.push(`  @location(${C})${A} ${E}: ${S.type},`),g.push(`var<private> ${E}: ${S.type};`),y.push(`${E} = ${vA(S.type)};`),x.push(`${E} = ${l.name}.${E};`)}dA(o,a,s.openBrace,s.closeBrace),o=hA(o,a,s,i.map(([E])=>E)),s=sl(o,e,"vertex"),o=pA(o,s,i.map(([E])=>E));let _=(a===l.type?[a]:[a,l.type]).map(E=>Ch(o,E).closeBrace).sort((E,S)=>S-E);for(let E of _)o=o.slice(0,E)+`${m.join(`
`)}
`+o.slice(E);if(c=sl(o,t,"fragment"),!new RegExp(`\\b${Pn(l.name)}\\s*:`).test(c.parameters))throw new Error(`Unable to preserve WGSL fragment input "${l.name}"`);return{source:o,declarations:g.join(`
`),vertexInitialization:y.join(`
`),fragmentInitialization:x.join(`
`)}}function sl(r,e,t){let i=new RegExp(`\\bfn\\s+${Pn(e)}\\s*\\(`,"g").exec(r);if(!i)throw new Error(`ShaderPlugin varyings require WGSL ${t} entry point "${e}"`);let o=r.indexOf("(",i.index),s=cl(r,o,"(",")"),a=r.indexOf("{",s),c=cl(r,a,"{","}");if(s<0||a<0||c<0)throw new Error(`Unable to parse WGSL ${t} entry point "${e}"`);return{openParenthesis:o,closeParenthesis:s,openBrace:a,closeBrace:c,parameters:r.slice(o+1,s)}}function uA(r,e){let t=r.slice(e.closeParenthesis+1,e.openBrace),n=/->\s*([A-Za-z_][\w]*)\s*$/.exec(t.trim());if(!n||Mh(r,n[1])===null)throw new Error("ShaderPlugin varyings require the WGSL vertex entry point to return a named struct");return n[1]}function fA(r,e){let t=[];for(let n of yA(e.parameters,",")){let i=/(?:@[A-Za-z_][\w]*(?:\([^)]*\))?\s*)*([A-Za-z_][\w]*)\s*:\s*([A-Za-z_][\w]*)\s*$/.exec(n.trim());i&&Mh(r,i[2])&&t.push({name:i[1],type:i[2]})}if(t.length!==1)throw new Error(`ShaderPlugin varyings require exactly one named WGSL fragment input struct; found ${t.length}`);return t[0]}function Ch(r,e){let t=Mh(r,e);if(!t)throw new Error(`Unable to find WGSL stage I/O struct "${e}"`);return t}function Mh(r,e){let n=new RegExp(`\\bstruct\\s+${Pn(e)}\\s*\\{`,"g").exec(r);if(!n)return null;let i=r.indexOf("{",n.index),o=cl(r,i,"{","}");return o<0?null:{openBrace:i,closeBrace:o,body:r.slice(i+1,o)}}function dA(r,e,t,n){let i=new RegExp(`\\b${Pn(e)}\\s*\\(`,"g"),o=i.exec(r);for(;o;){if(o.index<t||o.index>n)throw new Error(`ShaderPlugin varying output struct "${e}" is constructed outside the selected vertex entry point`);o=i.exec(r)}}function hA(r,e,t,n){let i=new RegExp(`\\b${Pn(e)}\\s*\\(`,"g"),o=[],s=i.exec(r);for(;s;){if(s.index>t.openBrace&&s.index<t.closeBrace){let a=r.indexOf("(",s.index),c=cl(r,a,"(",")");if(c<0||c>t.closeBrace)throw new Error(`Unable to parse WGSL output constructor "${e}"`);o.push({openParenthesis:a,closeParenthesis:c})}s=i.exec(r)}for(let a of o.sort((c,l)=>l.closeParenthesis-c.closeParenthesis)){let l=r.slice(a.openParenthesis+1,a.closeParenthesis).trim()?", ":"";r=r.slice(0,a.closeParenthesis)+l+n.join(", ")+r.slice(a.closeParenthesis)}return r}function pA(r,e,t){let n=mA(r,e.openBrace+1,e.closeBrace);for(let i=n.length-1;i>=0;i--){let o=n[i],s=r.slice(o.expressionStart,o.semicolon).trim();if(!s)throw new Error("ShaderPlugin varying vertex entry point cannot use an empty return");let a=`_luma_vertexOutput${i}`,c=t.map(u=>`${a}.${u} = ${u};`).join(`
`),l=`{
var ${a} = ${s};
${c}
return ${a};
}`;r=r.slice(0,o.start)+l+r.slice(o.semicolon+1)}return r}function mA(r,e,t){let n=[],i=e;for(;i<t;)if(i=Ih(r,i,t),r.slice(i,i+6)==="return"&&!/[A-Za-z0-9_]/.test(r[i+6]||"")){let o=i+6,s=gA(r,o,t);if(s<0)throw new Error("Unable to parse WGSL return statement in selected vertex entry point");n.push({start:i,expressionStart:o,semicolon:s}),i=s+1}else i++;return n}function gA(r,e,t){let n=0,i=0;for(let o=e;o<t;o++){let s=Ih(r,o,t);if(s!==o){o=s-1;continue}let a=r[o];if(a==="("&&n++,a===")"&&n--,a==="["&&i++,a==="]"&&i--,a===";"&&n===0&&i===0)return o}return-1}function Ih(r,e,t){let n=e;if(r[n]==="/"&&r[n+1]==="/"){let i=r.indexOf(`
`,n+2);return i<0||i>t?t:i+1}if(r[n]==="/"&&r[n+1]==="*"){let i=1;for(n+=2;n<t&&i>0;)r[n]==="/"&&r[n+1]==="*"?(i++,n+=2):r[n]==="*"&&r[n+1]==="/"?(i--,n+=2):n++}return n}function yA(r,e){let t=[],n=0,i=0,o=0;for(let s=0;s<r.length;s++){let a=r[s];a==="("&&i++,a===")"&&i--,a==="<"&&o++,a===">"&&o--,a===e&&i===0&&o===0&&(t.push(r.slice(n,s)),n=s+1)}return t.push(r.slice(n)),t}function fx(r){let e=[],t=/@location\s*\(\s*(\d+)\s*\)/g,n=t.exec(r);for(;n;)e.push(Number(n[1])),n=t.exec(r);return e}function al(r){let e=[],t=/(?:^|,)\s*(?:@[A-Za-z_][\w]*(?:\([^)]*\))?\s*)*([A-Za-z_][\w]*)\s*:/gm,n=t.exec(r);for(;n;)e.push(n[1]),n=t.exec(r);return e}function _A(r,e){let t=new RegExp(`\\b(?:var(?:<[^>]+>)?|let|const)\\s+${Pn(e)}\\b`,"g"),n=t.exec(r);for(;n;){if(EA(r,n.index)===0)return!0;n=t.exec(r)}return!1}function bA(r){let e=0;for(;r.has(e);)e++;return e}function xA(r){let{primitiveType:e,components:t}=nt.getAttributeShaderTypeInfo(r),n=e==="u32"?"0u":e==="i32"?"0":"0.0";return t===1?n:`${il(r)}(${n})`}function vA(r){let{primitiveType:e,components:t}=nt.getAttributeShaderTypeInfo(r),n=`${e}(0)`;return t===1?n:`${r}(${n})`}function wA(r,e){if(new RegExp(`\\b(?:flat\\s+|smooth\\s+)?(?:in|out|varying)\\s+(?:(?:lowp|mediump|highp)\\s+)?[A-Za-z_][A-Za-z0-9_]*\\s+${Pn(e)}\\s*(?:\\[|;)`).test(r))throw new Error(`ShaderPlugin varying "${e}" conflicts with existing GLSL stage I/O`)}function cl(r,e,t,n){let i=0,o=0,s=!1;for(let a=e;a<r.length;a++){let c=r[a],l=r[a+1];if(s){c===`
`&&(s=!1);continue}if(o>0){c==="/"&&l==="*"?(o++,a++):c==="*"&&l==="/"&&(o--,a++);continue}if(c==="/"&&l==="/"){s=!0,a++;continue}if(c==="/"&&l==="*"){o=1,a++;continue}if(c===t&&i++,c===n&&--i===0)return a}return-1}function EA(r,e){let t=0;for(let n=0;n<e;n++){let i=Ih(r,n,e);if(i!==n){n=i-1;continue}r[n]==="{"&&t++,r[n]==="}"&&t--}return t}function Pn(r){return r.replace(/[.*+?^${}()|[\]\\]/g,"\\$&")}var px=b(()=>{N();Ah()});function yx(r){let e=fn(r.modules||[]),{source:t,bindingAssignments:n}=PA(r.platformInfo,{...r,source:r.source,stage:"vertex",modules:e});return{source:t,getUniforms:bx(e),bindingAssignments:n,bindingTable:nl(t,n),shaderLayout:gc(t,{vertexEntryPoint:r.vertexEntryPoint,scanVertexAttributes:r.scanVertexAttributes})}}function _x(r){let{vs:e,fs:t}=r,n=fn(r.modules||[]);return{vs:mx(r.platformInfo,{...r,source:e,stage:"vertex",modules:n}),fs:mx(r.platformInfo,{...r,source:t,stage:"fragment",modules:n}),getUniforms:bx(n)}}function PA(r,e){let{source:t,stage:n,modules:i,defines:o={},hookFunctions:s=[],inject:a={},pluginInjections:c={},pluginVertexInputs:l={},pluginVaryings:u={},vertexEntryPoint:f="vertexMain",fragmentEntryPoint:h="fragmentMain",log:p}=e;dr(typeof t=="string","shader source must be a string");let m=Sn(t,{defines:o}),g=lx(m,f,l),y=hx(g.source,f,h,u),x=y.source,v="",_=Ph(s),w={},E={},S={};xx(c,w,E,S);for(let I in a){let R=typeof a[I]=="string"?{injection:a[I],order:0}:a[I],k=/^(v|f)s:(#)?([\w-]+)$/.exec(I);if(k){let W=k[2],V=k[3];W?V==="decl"?E[I]=[R]:S[I]=[R]:w[I]=[R]}else S[I]=[R]}TA(g.declarations,g.initialization,E,S),LA(y,E,S);let C=i,A=BA(x),B=RA(A.source),L=NA(C,e._bindingRegistry,B,o),M=[];for(let I of C){p&&Nd(I,x,p);let R=Sn(vx(I,"wgsl",p),{defines:o}),k=OA(R,I,{usedBindingsByGroup:B,bindingRegistry:e._bindingRegistry,reservedBindingKeysByGroup:L});M.push(...k.bindingAssignments);let W=k.source;v+=W;let V=AA(I);for(let ue in V){let Pr=/^(v|f)s:#([\w-]+)$/.exec(ue);if(Pr){let ei=Pr[2]==="decl"?E:S;ei[ue]=ei[ue]||[],ei[ue].push(V[ue])}else w[ue]=w[ue]||[],w[ue].push(V[ue])}}return v+=Rh,v=Fo(v,n,CA(E),!1,"wgsl",{vertex:f,fragment:h}),v+=MA(_,w),v+=VA(M),v+=A.source,v=Fo(v,n,S,!1,"wgsl",{vertex:f,fragment:h}),$A(v),{source:v,bindingAssignments:M}}function mx(r,e){let{source:t,stage:n,language:i="glsl",modules:o,defines:s={},hookFunctions:a=[],inject:c={},pluginInjections:l={},pluginVertexInputs:u={},pluginVaryings:f={},prologue:h=!0,log:p}=e;dr(typeof t=="string","shader source must be a string");let m=i==="glsl"?tx(t).version:-1,g=r.shaderLanguageVersion,y=m===100?"#version 100":"#version 300 es",v=t.split(`
`).slice(1).join(`
`),_={};o.forEach(L=>{Object.assign(_,L.defines)}),Object.assign(_,s);let w="";switch(i){case"wgsl":break;case"glsl":w=h?`${y}

// ----- PROLOGUE -------------------------
${`#define SHADER_TYPE_${n.toUpperCase()}`}

${qb(r)}
${n==="fragment"?SA:""}

// ----- APPLICATION DEFINES -------------------------

${IA(_)}

`:`${y}
`;break}let E=Ph(a),S={},C={},A={};xx(l,S,C,A);for(let L in c){let M=typeof c[L]=="string"?{injection:c[L],order:0}:c[L],I=/^(v|f)s:(#)?([\w-]+)$/.exec(L);if(I){let R=I[2],k=I[3];R?k==="decl"?C[L]=[M]:A[L]=[M]:S[L]=[M]}else A[L]=[M]}if(n==="vertex"){let L=cx(v,u);L&&(C["vs:#decl"]=C["vs:#decl"]||[],C["vs:#decl"].push({injection:L,order:Number.MIN_SAFE_INTEGER}))}let B=dx(v,n,f);if(B.declarations){let L=n==="vertex"?"vs:#decl":"fs:#decl";C[L]=C[L]||[],C[L].push({injection:B.declarations,order:Number.MIN_SAFE_INTEGER})}B.initialization&&(A["vs:#main-start"]=A["vs:#main-start"]||[],A["vs:#main-start"].push({injection:B.initialization,order:Number.MIN_SAFE_INTEGER}));for(let L of o){p&&Nd(L,v,p);let M=vx(L,n,p);w+=M;let I=L.instance?.normalizedInjections[n]||{};for(let R in I){let k=/^(v|f)s:#([\w-]+)$/.exec(R);if(k){let V=k[2]==="decl"?C:A;V[R]=V[R]||[],V[R].push(I[R])}else S[R]=S[R]||[],S[R].push(I[R])}}return w+="// ----- MAIN SHADER SOURCE -------------------------",w+=Rh,w=Fo(w,n,C),w+=rl(E[n],S),w+=v,w=Fo(w,n,A),i==="glsl"&&m!==g&&(w=Kb(w,n)),i==="glsl"&&wh(w,n,p),w.trim()}function bx(r){return function(t){let n={};for(let i of r){let o=i.getUniforms?.(t,n);Object.assign(n,o)}return n}}function xx(r,e,t,n){for(let i in r){let o=/^(v|f)s:(#)?([\w-]+)$/.exec(i);if(o){let s=o[2],a=o[3],c=s?a==="decl"?t:n:e;c[i]=c[i]||[],c[i].push(...r[i])}else n[i]=n[i]||[],n[i].push(...r[i])}}function TA(r,e,t,n){r&&(t["vs:#decl"]=t["vs:#decl"]||[],t["vs:#decl"].push({injection:r,order:Number.MIN_SAFE_INTEGER})),e&&(n["vs:#main-start"]=n["vs:#main-start"]||[],n["vs:#main-start"].push({injection:e,order:Number.MIN_SAFE_INTEGER}))}function LA(r,e,t){r.declarations&&(e["vs:#decl"]=e["vs:#decl"]||[],e["vs:#decl"].push({injection:r.declarations,order:Number.MIN_SAFE_INTEGER})),r.vertexInitialization&&(t["vs:#main-start"]=t["vs:#main-start"]||[],t["vs:#main-start"].push({injection:r.vertexInitialization,order:Number.MIN_SAFE_INTEGER})),r.fragmentInitialization&&(t["fs:#main-start"]=t["fs:#main-start"]||[],t["fs:#main-start"].push({injection:r.fragmentInitialization,order:Number.MIN_SAFE_INTEGER}))}function AA(r){return{...r.instance?.normalizedInjections.vertex||{},...r.instance?.normalizedInjections.fragment||{}}}function CA(r){let e=[...r["vs:#decl"]||[],...r["fs:#decl"]||[]];return e.length?{"vs:#decl":e}:{}}function MA(r,e){return rl(r.vertex,e,"wgsl")+rl(r.fragment,e,"wgsl")}function IA(r={}){let e="";for(let t in r){let n=r[t];(n||Number.isFinite(n))&&(e+=`#define ${t.toUpperCase()} ${r[t]}
`)}return e}function vx(r,e,t){let n;switch(e){case"vertex":n=r.vs||"";break;case"fragment":n=r.fs||"";break;case"wgsl":n=r.source||"";break;default:dr(!1)}if(!r.name)throw new Error("Shader module must have a name");vh(r,e,{log:t});let i=r.name.toUpperCase().replace(/[^0-9a-z]/gi,"_"),o=`// ----- MODULE ${r.name} ---------------

`;return e!=="wgsl"&&(o+=`#define MODULE_${i}
`),o+=`${n}
`,o}function RA(r){let e=new Map;for(let t of un(r,g_)){let n=Number(t.bindingToken),i=Number(t.groupToken);Bh(i,n,t.name),bi(e,i,n,`application binding "${t.name}"`)}return e}function BA(r){let e=un(r,hc),t=new Map;for(let o of e){if(o.bindingToken==="auto")continue;let s=Number(o.bindingToken),a=Number(o.groupToken);Bh(a,s,o.name),bi(t,a,s,`application binding "${o.name}"`)}let n={sawSupportedBindingDeclaration:e.length>0},i=Ld(r,hc,o=>DA(o,t,n));if(Ad(r)&&!n.sawSupportedBindingDeclaration)throw new Error('Unsupported @binding(auto) declaration form in application WGSL. Use adjacent "@group(N)" and "@binding(auto)" decorators followed by a bindable "var" declaration.');return{source:i}}function OA(r,e,t){let n=[],o={sawSupportedBindingDeclaration:un(r,ci).length>0,nextHintedBindingLocation:typeof e.firstBindingSlot=="number"?e.firstBindingSlot:null},s=Ld(r,ci,a=>kA(a,{module:e,context:t,bindingAssignments:n,relocationState:o}));if(Ad(r)&&!o.sawSupportedBindingDeclaration)throw new Error(`Unsupported @binding(auto) declaration form in module "${e.name}". Use adjacent "@group(N)" and "@binding(auto)" decorators followed by a bindable "var" declaration.`);return{source:s,bindingAssignments:n}}function kA(r,e){let{module:t,context:n,bindingAssignments:i,relocationState:o}=e,{match:s,bindingToken:a,groupToken:c,name:l}=r,u=Number(c);if(a==="auto"){let h=wx(u,t.name,l),p=n.bindingRegistry?.get(h),m=p!==void 0?p:GA(u,n.usedBindingsByGroup,t.name,o.nextHintedBindingLocation??void 0,n.bindingRegistry);return gx(t.name,u,m,l),p!==void 0&&FA(n.reservedBindingKeysByGroup,u,m,h)?(i.push({moduleName:t.name,name:l,group:u,location:m}),s.replace(/@binding\(\s*auto\s*\)/,`@binding(${m})`)):(bi(n.usedBindingsByGroup,u,m,`module "${t.name}" binding "${l}"`),n.bindingRegistry?.set(h,m),i.push({moduleName:t.name,name:l,group:u,location:m}),o.nextHintedBindingLocation!==null&&p===void 0&&(o.nextHintedBindingLocation=m+1),s.replace(/@binding\(\s*auto\s*\)/,`@binding(${m})`))}let f=Number(a);return gx(t.name,u,f,l),bi(n.usedBindingsByGroup,u,f,`module "${t.name}" binding "${l}"`),i.push({moduleName:t.name,name:l,group:u,location:f}),s}function DA(r,e,t){let{match:n,bindingToken:i,groupToken:o,name:s}=r,a=Number(o);if(i==="auto"){let c=zA(a,e);return Bh(a,c,s),bi(e,a,c,`application binding "${s}"`),n.replace(/@binding\(\s*auto\s*\)/,`@binding(${c})`)}return t.sawSupportedBindingDeclaration=!0,n}function NA(r,e,t,n){let i=new Map;if(!e)return i;for(let o of r)for(let s of UA(o,n)){let a=wx(s.group,o.name,s.name),c=e.get(a);if(c!==void 0){let l=i.get(s.group)||new Map,u=l.get(c);if(u&&u!==a)throw new Error(`Duplicate WGSL binding reservation for modules "${u}" and "${a}": group ${s.group}, binding ${c}.`);bi(t,s.group,c,`registered module binding "${a}"`),l.set(c,a),i.set(s.group,l)}}return i}function FA(r,e,t,n){let i=r.get(e);if(!i)return!1;let o=i.get(t);if(!o)return!1;if(o!==n)throw new Error(`Registered module binding "${n}" collided with "${o}": group ${e}, binding ${t}.`);return!0}function UA(r,e){let t=[],n=Sn(r.source||"",{defines:e});for(let i of un(n,ci))t.push({name:i.name,group:Number(i.groupToken)});return t}function Bh(r,e,t){if(r===0&&e>=ls)throw new Error(`Application binding "${t}" in group 0 uses reserved binding ${e}. Application-owned explicit group-0 bindings must stay below ${ls}.`)}function gx(r,e,t,n){if(e===0&&t<ls)throw new Error(`Module "${r}" binding "${n}" in group 0 uses reserved application binding ${t}. Module-owned explicit group-0 bindings must be ${ls} or higher.`)}function bi(r,e,t,n){let i=r.get(e)||new Set;if(i.has(t))throw new Error(`Duplicate WGSL binding assignment for ${n}: group ${e}, binding ${t}.`);i.add(t),r.set(e,i)}function GA(r,e,t,n,i){let o=e.get(r)||new Set,s=new Set,a=`${r}:`,c=`${a}${t}:`;for(let[u,f]of i||[])u.startsWith(c)&&s.add(f);let l=n??(r===0?ls:o.size>0?Math.max(...o)+1:0);for(;o.has(l)||s.has(l);)l++;for(let[u,f]of i||[])f===l&&u.startsWith(a)&&i?.delete(u);return l}function zA(r,e){let t=e.get(r)||new Set,n=0;for(;t.has(n);)n++;return n}function $A(r){let e=y_(r,ci);if(!e)return;let t=WA(r,e.index);throw t?new Error(`Unresolved @binding(auto) for module "${t}" binding "${e.name}" remained in assembled WGSL source.`):jA(r,e.index)?new Error(`Unresolved @binding(auto) for application binding "${e.name}" remained in assembled WGSL source.`):new Error(`Unresolved @binding(auto) remained in assembled WGSL source near "${HA(e.match)}".`)}function VA(r){if(r.length===0)return"";let e=`// ----- MODULE WGSL BINDING ASSIGNMENTS ---------------
`;for(let t of r)e+=`// ${t.moduleName}.${t.name} -> @group(${t.group}) @binding(${t.location})
`;return e+=`
`,e}function wx(r,e,t){return`${r}:${e}:${t}`}function WA(r,e){let t=/^\/\/ ----- MODULE ([^\n]+) ---------------$/gm,n,i;for(i=t.exec(r);i&&i.index<=e;)n=i[1],i=t.exec(r);return n}function jA(r,e){let t=r.indexOf(Rh);return t>=0?e>t:!0}function HA(r){return r.replace(/\s+/g," ").trim()}var Rh,ls,SA,Ex=b(()=>{Fd();Xb();Dd();Jb();xc();Eh();ex();_c();rx();Th();Bd();Lh();Ah();px();pc();Rh=`

${No}
`,ls=100,SA=`precision highp float;
`});var pr,dt,xi,Nr,Sx=b(()=>{xc();Ex();Th();Lh();Bd();_c();pr=class pr{constructor(){d(this,"_hookFunctions",[]);d(this,"_defaultModules",[])}static getDefaultShaderAssembler(e){return dr(e==="glsl"||e==="wgsl"),e==="wgsl"?(pr.defaultShaderAssemblers.wgsl=pr.defaultShaderAssemblers.wgsl||new Nr,pr.defaultShaderAssemblers.wgsl):(pr.defaultShaderAssemblers.glsl=pr.defaultShaderAssemblers.glsl||new xi,pr.defaultShaderAssemblers.glsl)}addDefaultModule(e){this._defaultModules.find(t=>t.name===(typeof e=="string"?e:e.name))||this._defaultModules.push(e)}removeDefaultModule(e){let t=typeof e=="string"?e:e.name;this._defaultModules=this._defaultModules.filter(n=>n.name!==t)}addShaderHook(e,t){t&&(e=Object.assign(t,{hook:e})),this._hookFunctions.push(e)}_getModuleList(e=[]){let t=new Array(this._defaultModules.length+e.length),n={},i=0;for(let o=0,s=this._defaultModules.length;o<s;++o){let a=this._defaultModules[o],c=a.name;t[i++]=a,n[c]=!0}for(let o=0,s=e.length;o<s;++o){let a=e[o],c=a.name;n[c]||(t[i++]=a,n[c]=!0)}return t.length=i,ui(t),t}};d(pr,"defaultShaderAssemblers",{});dt=pr,xi=class extends dt{constructor(){super(...arguments);d(this,"shaderLanguage","glsl")}assembleGLSLShaderPair(t){let n=this._getModuleList(t.modules),i=this._hookFunctions;return{..._x({...t,vs:t.vs,fs:t.fs,modules:n,hookFunctions:i}),modules:n}}},Nr=class r extends dt{constructor(){super(...arguments);d(this,"shaderLanguage","wgsl");d(this,"_wgslBindingRegistry",new Map)}assembleWGSLShader(t){let n=this._getModuleList(t.modules),i=this._hookFunctions,o=r.getShaderPreprocessorDefines(t,n),s=t.platformInfo.shaderLanguage==="wgsl"&&t.source?Sn(t.source,{defines:o}):t.source,{source:a,getUniforms:c,bindingAssignments:l}=yx({...t,source:s,defines:o,_bindingRegistry:this._wgslBindingRegistry,modules:n,hookFunctions:i}),u=t.platformInfo.shaderLanguage==="wgsl"?Sn(a,{defines:o}):a;return{source:u,getUniforms:c,modules:n,bindingAssignments:l,bindingTable:nl(u,l),shaderLayout:gc(u,{vertexEntryPoint:t.vertexEntryPoint,scanVertexAttributes:t.scanVertexAttributes})}}static getShaderPreprocessorDefines(t,n){return{...r.getPlatformPreprocessorDefines(t.platformInfo),...n.reduce((i,o)=>(Object.assign(i,o.defines),i),{}),...t.defines}}static getPlatformPreprocessorDefines(t){let n=t.limits||{};return{LUMA_SUPPORTS_VERTEX_STORAGE_BUFFERS:t.type==="webgpu"&&(n.maxStorageBuffersInVertexStage||0)>0,LUMA_FP32_TAN_PRECISION_WORKAROUND:t.type==="webgpu"&&t.gpu.toLowerCase()!=="nvidia"&&t.gpu.toLowerCase()!=="amd",LUMA_FP64_INTEGER_ARITHMETIC:t.type==="webgpu"&&t.gpu.toLowerCase()==="apple"}}}});function Oh(r){let{input:e,inputChannels:t,output:n}=r||{};if(!e)return qA;if(!t)throw new Error("inputChannels");let i=XA(t),o=Px(e,t);return`#version 300 es
in ${i} ${e};
out vec4 ${n};
void main() {
  ${n} = ${o};
}`}function XA(r){switch(r){case 1:return"float";case 2:return"vec2";case 3:return"vec3";case 4:return"vec4";default:throw new Error(`invalid channels: ${r}`)}}function Px(r,e){switch(e){case 1:return`vec4(${r}, 0.0, 0.0, 1.0)`;case 2:return`vec4(${r}, 0.0, 1.0)`;case 3:return`vec4(${r}, 1.0)`;case 4:return r;default:throw new Error(`invalid channels: ${e}`)}}var YA,qA,Tx=b(()=>{YA=`out vec4 transform_output;
void main() {
  transform_output = vec4(0);
}`,qA=`#version 300 es
${YA}`});function kh(r,{precision:e=we.precision}={}){return r=KA(r),`${parseFloat(r.toPrecision(e))}`}function mr(r){return Array.isArray(r)||ArrayBuffer.isView(r)&&!(r instanceof DataView)}function ie(r,e,t){return JA(r,n=>Math.max(e,Math.min(t,n)))}function Tn(r,e,t){return mr(r)?r.map((n,i)=>Tn(n,e[i],t)):t*e+(1-t)*r}function Wt(r,e,t){let n=we.EPSILON;t&&(we.EPSILON=t);try{if(r===e)return!0;if(mr(r)&&mr(e)){if(r.length!==e.length)return!1;for(let i=0;i<r.length;++i)if(!Wt(r[i],e[i]))return!1;return!0}return r&&r.equals?r.equals(e):e&&e.equals?e.equals(r):typeof r=="number"&&typeof e=="number"?Math.abs(r-e)<=we.EPSILON*Math.max(1,Math.abs(r),Math.abs(e)):!1}finally{we.EPSILON=n}}function KA(r){return Math.round(r/we.EPSILON)*we.EPSILON}function QA(r){return r.clone?r.clone():new Array(r.length)}function JA(r,e,t){if(mr(r)){let n=r;t=t||QA(n);for(let i=0;i<t.length&&i<n.length;++i){let o=typeof r=="number"?r:r[i];t[i]=e(o,i,t)}return t}return e(r)}var d8,h8,ZA,we,vi=b(()=>{d8=1/Math.PI*180,h8=1/180*Math.PI,ZA={EPSILON:1e-12,debug:!1,precision:4,printTypes:!1,printDegrees:!1,printRowMajor:!0,_cartographicRadians:!1};globalThis.mathgl=globalThis.mathgl||{config:{...ZA}};we=globalThis.mathgl.config});var wi,Dh=b(()=>{vi();wi=class extends Array{clone(){return new this.constructor().copy(this)}fromArray(e,t=0){for(let n=0;n<this.ELEMENTS;++n)this[n]=e[n+t];return this.check()}toArray(e=[],t=0){for(let n=0;n<this.ELEMENTS;++n)e[t+n]=this[n];return e}toObject(e){return e}from(e){return Array.isArray(e)?this.copy(e):this.fromObject(e)}to(e){return e===this?this:mr(e)?this.toArray(e):this.toObject(e)}toTarget(e){return e?this.to(e):this}toFloat32Array(){return new Float32Array(this)}toString(){return this.formatString(we)}formatString(e){let t="";for(let n=0;n<this.ELEMENTS;++n)t+=(n>0?", ":"")+kh(this[n],e);return`${e.printTypes?this.constructor.name:""}[${t}]`}equals(e){if(!e||this.length!==e.length)return!1;for(let t=0;t<this.ELEMENTS;++t)if(!Wt(this[t],e[t]))return!1;return!0}exactEquals(e){if(!e||this.length!==e.length)return!1;for(let t=0;t<this.ELEMENTS;++t)if(this[t]!==e[t])return!1;return!0}negate(){for(let e=0;e<this.ELEMENTS;++e)this[e]=-this[e];return this.check()}lerp(e,t,n){if(n===void 0)return this.lerp(this,e,t);for(let i=0;i<this.ELEMENTS;++i){let o=e[i],s=typeof t=="number"?t:t[i];this[i]=o+n*(s-o)}return this.check()}min(e){for(let t=0;t<this.ELEMENTS;++t)this[t]=Math.min(e[t],this[t]);return this.check()}max(e){for(let t=0;t<this.ELEMENTS;++t)this[t]=Math.max(e[t],this[t]);return this.check()}clamp(e,t){for(let n=0;n<this.ELEMENTS;++n)this[n]=Math.min(Math.max(this[n],e[n]),t[n]);return this.check()}add(...e){for(let t of e)for(let n=0;n<this.ELEMENTS;++n)this[n]+=t[n];return this.check()}subtract(...e){for(let t of e)for(let n=0;n<this.ELEMENTS;++n)this[n]-=t[n];return this.check()}scale(e){if(typeof e=="number")for(let t=0;t<this.ELEMENTS;++t)this[t]*=e;else for(let t=0;t<this.ELEMENTS&&t<e.length;++t)this[t]*=e[t];return this.check()}multiplyByScalar(e){for(let t=0;t<this.ELEMENTS;++t)this[t]*=e;return this.check()}check(){if(we.debug&&!this.validate())throw new Error(`math.gl: ${this.constructor.name} some fields set to invalid numbers'`);return this}validate(){let e=this.length===this.ELEMENTS;for(let t=0;t<this.ELEMENTS;++t)e=e&&Number.isFinite(this[t]);return e}sub(e){return this.subtract(e)}setScalar(e){for(let t=0;t<this.ELEMENTS;++t)this[t]=e;return this.check()}addScalar(e){for(let t=0;t<this.ELEMENTS;++t)this[t]+=e;return this.check()}subScalar(e){return this.addScalar(-e)}multiplyScalar(e){for(let t=0;t<this.ELEMENTS;++t)this[t]*=e;return this.check()}divideScalar(e){return this.multiplyByScalar(1/e)}clampScalar(e,t){for(let n=0;n<this.ELEMENTS;++n)this[n]=Math.min(Math.max(this[n],e),t);return this.check()}get elements(){return this}}});function eC(r,e){if(r.length!==e)return!1;for(let t=0;t<r.length;++t)if(!Number.isFinite(r[t]))return!1;return!0}function Ce(r){if(!Number.isFinite(r))throw new Error(`Invalid number ${JSON.stringify(r)}`);return r}function ll(r,e,t=""){if(we.debug&&!eC(r,e))throw new Error(`math.gl: ${t} some fields set to invalid numbers'`);return r}var us=b(()=>{vi()});function Nh(r,e){if(!r)throw new Error(`math.gl assertion ${e}`)}var Lx=b(()=>{});var ul,Ax=b(()=>{Dh();us();Lx();ul=class extends wi{get x(){return this[0]}set x(e){this[0]=Ce(e)}get y(){return this[1]}set y(e){this[1]=Ce(e)}len(){return Math.sqrt(this.lengthSquared())}magnitude(){return this.len()}lengthSquared(){let e=0;for(let t=0;t<this.ELEMENTS;++t)e+=this[t]*this[t];return e}magnitudeSquared(){return this.lengthSquared()}distance(e){return Math.sqrt(this.distanceSquared(e))}distanceSquared(e){let t=0;for(let n=0;n<this.ELEMENTS;++n){let i=this[n]-e[n];t+=i*i}return Ce(t)}dot(e){let t=0;for(let n=0;n<this.ELEMENTS;++n)t+=this[n]*e[n];return Ce(t)}normalize(){let e=this.magnitude();if(e!==0)for(let t=0;t<this.ELEMENTS;++t)this[t]/=e;return this.check()}multiply(...e){for(let t of e)for(let n=0;n<this.ELEMENTS;++n)this[n]*=t[n];return this.check()}divide(...e){for(let t of e)for(let n=0;n<this.ELEMENTS;++n)this[n]/=t[n];return this.check()}lengthSq(){return this.lengthSquared()}distanceTo(e){return this.distance(e)}distanceToSquared(e){return this.distanceSquared(e)}getComponent(e){return Nh(e>=0&&e<this.ELEMENTS,"index is out of range"),Ce(this[e])}setComponent(e,t){return Nh(e>=0&&e<this.ELEMENTS,"index is out of range"),this[e]=t,this.check()}addVectors(e,t){return this.copy(e).add(t)}subVectors(e,t){return this.copy(e).subtract(t)}multiplyVectors(e,t){return this.copy(e).multiply(t)}addScaledVector(e,t){return this.add(new this.constructor(e).multiplyScalar(t))}}});function ht(r){return r>=0?Math.round(r):r%.5===0?Math.floor(r):Math.round(r)}var J,jt,S8,Ln=b(()=>{J=typeof Float32Array<"u"?Float32Array:Array,jt=Math.random;S8=Math.PI/180});var $e={};cr($e,{add:()=>oC,angle:()=>SC,ceil:()=>sC,clone:()=>tC,copy:()=>nC,create:()=>Cx,cross:()=>yC,dist:()=>BC,distance:()=>Bx,div:()=>RC,divide:()=>Rx,dot:()=>gC,equals:()=>AC,exactEquals:()=>LC,floor:()=>aC,forEach:()=>DC,fromValues:()=>rC,inverse:()=>pC,len:()=>CC,length:()=>kx,lerp:()=>_C,max:()=>lC,min:()=>cC,mul:()=>IC,multiply:()=>Ix,negate:()=>hC,normalize:()=>mC,random:()=>bC,rotate:()=>EC,round:()=>uC,scale:()=>fC,scaleAndAdd:()=>dC,set:()=>iC,sqrDist:()=>OC,sqrLen:()=>kC,squaredDistance:()=>Ox,squaredLength:()=>Dx,str:()=>TC,sub:()=>MC,subtract:()=>Mx,transformMat2:()=>xC,transformMat2d:()=>vC,transformMat3:()=>wC,transformMat4:()=>Fh,zero:()=>PC});function Cx(){let r=new J(2);return J!=Float32Array&&(r[0]=0,r[1]=0),r}function tC(r){let e=new J(2);return e[0]=r[0],e[1]=r[1],e}function rC(r,e){let t=new J(2);return t[0]=r,t[1]=e,t}function nC(r,e){return r[0]=e[0],r[1]=e[1],r}function iC(r,e,t){return r[0]=e,r[1]=t,r}function oC(r,e,t){return r[0]=e[0]+t[0],r[1]=e[1]+t[1],r}function Mx(r,e,t){return r[0]=e[0]-t[0],r[1]=e[1]-t[1],r}function Ix(r,e,t){return r[0]=e[0]*t[0],r[1]=e[1]*t[1],r}function Rx(r,e,t){return r[0]=e[0]/t[0],r[1]=e[1]/t[1],r}function sC(r,e){return r[0]=Math.ceil(e[0]),r[1]=Math.ceil(e[1]),r}function aC(r,e){return r[0]=Math.floor(e[0]),r[1]=Math.floor(e[1]),r}function cC(r,e,t){return r[0]=Math.min(e[0],t[0]),r[1]=Math.min(e[1],t[1]),r}function lC(r,e,t){return r[0]=Math.max(e[0],t[0]),r[1]=Math.max(e[1],t[1]),r}function uC(r,e){return r[0]=ht(e[0]),r[1]=ht(e[1]),r}function fC(r,e,t){return r[0]=e[0]*t,r[1]=e[1]*t,r}function dC(r,e,t,n){return r[0]=e[0]+t[0]*n,r[1]=e[1]+t[1]*n,r}function Bx(r,e){let t=e[0]-r[0],n=e[1]-r[1];return Math.sqrt(t*t+n*n)}function Ox(r,e){let t=e[0]-r[0],n=e[1]-r[1];return t*t+n*n}function kx(r){let e=r[0],t=r[1];return Math.sqrt(e*e+t*t)}function Dx(r){let e=r[0],t=r[1];return e*e+t*t}function hC(r,e){return r[0]=-e[0],r[1]=-e[1],r}function pC(r,e){return r[0]=1/e[0],r[1]=1/e[1],r}function mC(r,e){let t=e[0],n=e[1],i=t*t+n*n;return i>0&&(i=1/Math.sqrt(i)),r[0]=e[0]*i,r[1]=e[1]*i,r}function gC(r,e){return r[0]*e[0]+r[1]*e[1]}function yC(r,e,t){let n=e[0]*t[1]-e[1]*t[0];return r[0]=r[1]=0,r[2]=n,r}function _C(r,e,t,n){let i=e[0],o=e[1];return r[0]=i+n*(t[0]-i),r[1]=o+n*(t[1]-o),r}function bC(r,e){e=e===void 0?1:e;let t=jt()*2*Math.PI;return r[0]=Math.cos(t)*e,r[1]=Math.sin(t)*e,r}function xC(r,e,t){let n=e[0],i=e[1];return r[0]=t[0]*n+t[2]*i,r[1]=t[1]*n+t[3]*i,r}function vC(r,e,t){let n=e[0],i=e[1];return r[0]=t[0]*n+t[2]*i+t[4],r[1]=t[1]*n+t[3]*i+t[5],r}function wC(r,e,t){let n=e[0],i=e[1];return r[0]=t[0]*n+t[3]*i+t[6],r[1]=t[1]*n+t[4]*i+t[7],r}function Fh(r,e,t){let n=e[0],i=e[1];return r[0]=t[0]*n+t[4]*i+t[12],r[1]=t[1]*n+t[5]*i+t[13],r}function EC(r,e,t,n){let i=e[0]-t[0],o=e[1]-t[1],s=Math.sin(n),a=Math.cos(n);return r[0]=i*a-o*s+t[0],r[1]=i*s+o*a+t[1],r}function SC(r,e){let t=r[0],n=r[1],i=e[0],o=e[1],s=Math.sqrt((t*t+n*n)*(i*i+o*o)),a=s&&(t*i+n*o)/s;return Math.acos(Math.min(Math.max(a,-1),1))}function PC(r){return r[0]=0,r[1]=0,r}function TC(r){return`vec2(${r[0]}, ${r[1]})`}function LC(r,e){return r[0]===e[0]&&r[1]===e[1]}function AC(r,e){let t=r[0],n=r[1],i=e[0],o=e[1];return Math.abs(t-i)<=1e-6*Math.max(1,Math.abs(t),Math.abs(i))&&Math.abs(n-o)<=1e-6*Math.max(1,Math.abs(n),Math.abs(o))}var CC,MC,IC,RC,BC,OC,kC,DC,Uh=b(()=>{Ln();CC=kx,MC=Mx,IC=Ix,RC=Rx,BC=Bx,OC=Ox,kC=Dx,DC=(function(){let r=Cx();return function(e,t,n,i,o,s){let a,c;for(t||(t=2),n||(n=0),i?c=Math.min(i*t+n,e.length):c=e.length,a=n;a<c;a+=t)r[0]=e[a],r[1]=e[a+1],o(r,r,s),e[a]=r[0],e[a+1]=r[1];return e}})()});function Nx(r,e,t){let n=e[0],i=e[1],o=t[3]*n+t[7]*i||1;return r[0]=(t[0]*n+t[4]*i)/o,r[1]=(t[1]*n+t[5]*i)/o,r}function fl(r,e,t){let n=e[0],i=e[1],o=e[2],s=t[3]*n+t[7]*i+t[11]*o||1;return r[0]=(t[0]*n+t[4]*i+t[8]*o)/s,r[1]=(t[1]*n+t[5]*i+t[9]*o)/s,r[2]=(t[2]*n+t[6]*i+t[10]*o)/s,r}function Fx(r,e,t){let n=e[0],i=e[1];return r[0]=t[0]*n+t[2]*i,r[1]=t[1]*n+t[3]*i,r[2]=e[2],r}var Gh=b(()=>{});var Cn={};cr(Cn,{add:()=>GC,angle:()=>Yh,bezier:()=>JC,ceil:()=>zC,clone:()=>NC,copy:()=>FC,create:()=>dl,cross:()=>An,dist:()=>cM,distance:()=>Vx,div:()=>aM,divide:()=>$x,dot:()=>fs,equals:()=>iM,exactEquals:()=>nM,floor:()=>$C,forEach:()=>fM,fromValues:()=>hl,hermite:()=>QC,inverse:()=>XC,len:()=>qh,length:()=>Ux,lerp:()=>ZC,max:()=>WC,min:()=>VC,mul:()=>sM,multiply:()=>zx,negate:()=>qC,normalize:()=>zh,random:()=>eM,rotateX:()=>Wh,rotateY:()=>jh,rotateZ:()=>Hh,round:()=>jC,scale:()=>HC,scaleAndAdd:()=>YC,set:()=>UC,slerp:()=>KC,sqrDist:()=>lM,sqrLen:()=>uM,squaredDistance:()=>Wx,squaredLength:()=>jx,str:()=>rM,sub:()=>oM,subtract:()=>Gx,transformMat3:()=>$h,transformMat4:()=>ds,transformQuat:()=>Vh,zero:()=>tM});function dl(){let r=new J(3);return J!=Float32Array&&(r[0]=0,r[1]=0,r[2]=0),r}function NC(r){let e=new J(3);return e[0]=r[0],e[1]=r[1],e[2]=r[2],e}function Ux(r){let e=r[0],t=r[1],n=r[2];return Math.sqrt(e*e+t*t+n*n)}function hl(r,e,t){let n=new J(3);return n[0]=r,n[1]=e,n[2]=t,n}function FC(r,e){return r[0]=e[0],r[1]=e[1],r[2]=e[2],r}function UC(r,e,t,n){return r[0]=e,r[1]=t,r[2]=n,r}function GC(r,e,t){return r[0]=e[0]+t[0],r[1]=e[1]+t[1],r[2]=e[2]+t[2],r}function Gx(r,e,t){return r[0]=e[0]-t[0],r[1]=e[1]-t[1],r[2]=e[2]-t[2],r}function zx(r,e,t){return r[0]=e[0]*t[0],r[1]=e[1]*t[1],r[2]=e[2]*t[2],r}function $x(r,e,t){return r[0]=e[0]/t[0],r[1]=e[1]/t[1],r[2]=e[2]/t[2],r}function zC(r,e){return r[0]=Math.ceil(e[0]),r[1]=Math.ceil(e[1]),r[2]=Math.ceil(e[2]),r}function $C(r,e){return r[0]=Math.floor(e[0]),r[1]=Math.floor(e[1]),r[2]=Math.floor(e[2]),r}function VC(r,e,t){return r[0]=Math.min(e[0],t[0]),r[1]=Math.min(e[1],t[1]),r[2]=Math.min(e[2],t[2]),r}function WC(r,e,t){return r[0]=Math.max(e[0],t[0]),r[1]=Math.max(e[1],t[1]),r[2]=Math.max(e[2],t[2]),r}function jC(r,e){return r[0]=ht(e[0]),r[1]=ht(e[1]),r[2]=ht(e[2]),r}function HC(r,e,t){return r[0]=e[0]*t,r[1]=e[1]*t,r[2]=e[2]*t,r}function YC(r,e,t,n){return r[0]=e[0]+t[0]*n,r[1]=e[1]+t[1]*n,r[2]=e[2]+t[2]*n,r}function Vx(r,e){let t=e[0]-r[0],n=e[1]-r[1],i=e[2]-r[2];return Math.sqrt(t*t+n*n+i*i)}function Wx(r,e){let t=e[0]-r[0],n=e[1]-r[1],i=e[2]-r[2];return t*t+n*n+i*i}function jx(r){let e=r[0],t=r[1],n=r[2];return e*e+t*t+n*n}function qC(r,e){return r[0]=-e[0],r[1]=-e[1],r[2]=-e[2],r}function XC(r,e){return r[0]=1/e[0],r[1]=1/e[1],r[2]=1/e[2],r}function zh(r,e){let t=e[0],n=e[1],i=e[2],o=t*t+n*n+i*i;return o>0&&(o=1/Math.sqrt(o)),r[0]=e[0]*o,r[1]=e[1]*o,r[2]=e[2]*o,r}function fs(r,e){return r[0]*e[0]+r[1]*e[1]+r[2]*e[2]}function An(r,e,t){let n=e[0],i=e[1],o=e[2],s=t[0],a=t[1],c=t[2];return r[0]=i*c-o*a,r[1]=o*s-n*c,r[2]=n*a-i*s,r}function ZC(r,e,t,n){let i=e[0],o=e[1],s=e[2];return r[0]=i+n*(t[0]-i),r[1]=o+n*(t[1]-o),r[2]=s+n*(t[2]-s),r}function KC(r,e,t,n){let i=Math.acos(Math.min(Math.max(fs(e,t),-1),1)),o=Math.sin(i),s=Math.sin((1-n)*i)/o,a=Math.sin(n*i)/o;return r[0]=s*e[0]+a*t[0],r[1]=s*e[1]+a*t[1],r[2]=s*e[2]+a*t[2],r}function QC(r,e,t,n,i,o){let s=o*o,a=s*(2*o-3)+1,c=s*(o-2)+o,l=s*(o-1),u=s*(3-2*o);return r[0]=e[0]*a+t[0]*c+n[0]*l+i[0]*u,r[1]=e[1]*a+t[1]*c+n[1]*l+i[1]*u,r[2]=e[2]*a+t[2]*c+n[2]*l+i[2]*u,r}function JC(r,e,t,n,i,o){let s=1-o,a=s*s,c=o*o,l=a*s,u=3*o*a,f=3*c*s,h=c*o;return r[0]=e[0]*l+t[0]*u+n[0]*f+i[0]*h,r[1]=e[1]*l+t[1]*u+n[1]*f+i[1]*h,r[2]=e[2]*l+t[2]*u+n[2]*f+i[2]*h,r}function eM(r,e){e=e===void 0?1:e;let t=jt()*2*Math.PI,n=jt()*2-1,i=Math.sqrt(1-n*n)*e;return r[0]=Math.cos(t)*i,r[1]=Math.sin(t)*i,r[2]=n*e,r}function ds(r,e,t){let n=e[0],i=e[1],o=e[2],s=t[3]*n+t[7]*i+t[11]*o+t[15];return s=s||1,r[0]=(t[0]*n+t[4]*i+t[8]*o+t[12])/s,r[1]=(t[1]*n+t[5]*i+t[9]*o+t[13])/s,r[2]=(t[2]*n+t[6]*i+t[10]*o+t[14])/s,r}function $h(r,e,t){let n=e[0],i=e[1],o=e[2];return r[0]=n*t[0]+i*t[3]+o*t[6],r[1]=n*t[1]+i*t[4]+o*t[7],r[2]=n*t[2]+i*t[5]+o*t[8],r}function Vh(r,e,t){let n=t[0],i=t[1],o=t[2],s=t[3],a=e[0],c=e[1],l=e[2],u=i*l-o*c,f=o*a-n*l,h=n*c-i*a,p=i*h-o*f,m=o*u-n*h,g=n*f-i*u,y=s*2;return u*=y,f*=y,h*=y,p*=2,m*=2,g*=2,r[0]=a+u+p,r[1]=c+f+m,r[2]=l+h+g,r}function Wh(r,e,t,n){let i=[],o=[];return i[0]=e[0]-t[0],i[1]=e[1]-t[1],i[2]=e[2]-t[2],o[0]=i[0],o[1]=i[1]*Math.cos(n)-i[2]*Math.sin(n),o[2]=i[1]*Math.sin(n)+i[2]*Math.cos(n),r[0]=o[0]+t[0],r[1]=o[1]+t[1],r[2]=o[2]+t[2],r}function jh(r,e,t,n){let i=[],o=[];return i[0]=e[0]-t[0],i[1]=e[1]-t[1],i[2]=e[2]-t[2],o[0]=i[2]*Math.sin(n)+i[0]*Math.cos(n),o[1]=i[1],o[2]=i[2]*Math.cos(n)-i[0]*Math.sin(n),r[0]=o[0]+t[0],r[1]=o[1]+t[1],r[2]=o[2]+t[2],r}function Hh(r,e,t,n){let i=[],o=[];return i[0]=e[0]-t[0],i[1]=e[1]-t[1],i[2]=e[2]-t[2],o[0]=i[0]*Math.cos(n)-i[1]*Math.sin(n),o[1]=i[0]*Math.sin(n)+i[1]*Math.cos(n),o[2]=i[2],r[0]=o[0]+t[0],r[1]=o[1]+t[1],r[2]=o[2]+t[2],r}function Yh(r,e){let t=r[0],n=r[1],i=r[2],o=e[0],s=e[1],a=e[2],c=Math.sqrt((t*t+n*n+i*i)*(o*o+s*s+a*a)),l=c&&fs(r,e)/c;return Math.acos(Math.min(Math.max(l,-1),1))}function tM(r){return r[0]=0,r[1]=0,r[2]=0,r}function rM(r){return`vec3(${r[0]}, ${r[1]}, ${r[2]})`}function nM(r,e){return r[0]===e[0]&&r[1]===e[1]&&r[2]===e[2]}function iM(r,e){let t=r[0],n=r[1],i=r[2],o=e[0],s=e[1],a=e[2];return Math.abs(t-o)<=1e-6*Math.max(1,Math.abs(t),Math.abs(o))&&Math.abs(n-s)<=1e-6*Math.max(1,Math.abs(n),Math.abs(s))&&Math.abs(i-a)<=1e-6*Math.max(1,Math.abs(i),Math.abs(a))}var oM,sM,aM,cM,lM,qh,uM,fM,hs=b(()=>{Ln();oM=Gx,sM=zx,aM=$x,cM=Vx,lM=Wx,qh=Ux,uM=jx,fM=(function(){let r=dl();return function(e,t,n,i,o,s){let a,c;for(t||(t=3),n||(n=0),i?c=Math.min(i*t+n,e.length):c=e.length,a=n;a<c;a+=t)r[0]=e[a],r[1]=e[a+1],r[2]=e[a+2],o(r,r,s),e[a]=r[0],e[a+1]=r[1],e[a+2]=r[2];return e}})()});var Xh,pl,Me,Hx=b(()=>{Ax();vi();us();hs();Gh();Xh=[0,0,0],Me=class r extends ul{static get ZERO(){return pl||(pl=new r(0,0,0),Object.freeze(pl)),pl}constructor(e=0,t=0,n=0){super(-0,-0,-0),arguments.length===1&&mr(e)?this.copy(e):(we.debug&&(Ce(e),Ce(t),Ce(n)),this[0]=e,this[1]=t,this[2]=n)}set(e,t,n){return this[0]=e,this[1]=t,this[2]=n,this.check()}copy(e){return this[0]=e[0],this[1]=e[1],this[2]=e[2],this.check()}fromObject(e){return we.debug&&(Ce(e.x),Ce(e.y),Ce(e.z)),this[0]=e.x,this[1]=e.y,this[2]=e.z,this.check()}toObject(e){return e.x=this[0],e.y=this[1],e.z=this[2],e}get ELEMENTS(){return 3}get z(){return this[2]}set z(e){this[2]=Ce(e)}angle(e){return Yh(this,e)}cross(e){return An(this,this,e),this.check()}rotateX({radians:e,origin:t=Xh}){return Wh(this,this,t,e),this.check()}rotateY({radians:e,origin:t=Xh}){return jh(this,this,t,e),this.check()}rotateZ({radians:e,origin:t=Xh}){return Hh(this,this,t,e),this.check()}transform(e){return this.transformAsPoint(e)}transformAsPoint(e){return ds(this,this,e),this.check()}transformAsVector(e){return fl(this,this,e),this.check()}transformByMatrix3(e){return $h(this,this,e),this.check()}transformByMatrix2(e){return Fx(this,this,e),this.check()}transformByQuaternion(e){return Vh(this,this,e),this.check()}}});var ml,Yx=b(()=>{Dh();us();vi();ml=class extends wi{toString(){let e="[";if(we.printRowMajor){e+="row-major:";for(let t=0;t<this.RANK;++t)for(let n=0;n<this.RANK;++n)e+=` ${this[n*this.RANK+t]}`}else{e+="column-major:";for(let t=0;t<this.ELEMENTS;++t)e+=` ${this[t]}`}return e+="]",e}getElementIndex(e,t){return t*this.RANK+e}getElement(e,t){return this[t*this.RANK+e]}setElement(e,t,n){return this[t*this.RANK+e]=Ce(n),this}getColumn(e,t=new Array(this.RANK).fill(-0)){let n=e*this.RANK;for(let i=0;i<this.RANK;++i)t[i]=this[n+i];return t}setColumn(e,t){let n=e*this.RANK;for(let i=0;i<this.RANK;++i)this[n+i]=t[i];return this}}});function qx(){let r=new J(9);return J!=Float32Array&&(r[1]=0,r[2]=0,r[3]=0,r[5]=0,r[6]=0,r[7]=0),r[0]=1,r[4]=1,r[8]=1,r}var Zh=b(()=>{Ln()});var be={};cr(be,{add:()=>DM,adjoint:()=>yM,clone:()=>hM,copy:()=>pM,create:()=>dM,decompose:()=>LM,determinant:()=>Jh,equals:()=>GM,exactEquals:()=>UM,frob:()=>kM,fromQuat:()=>sp,fromQuat2:()=>SM,fromRotation:()=>xM,fromRotationTranslation:()=>Kx,fromRotationTranslationScale:()=>AM,fromRotationTranslationScaleOrigin:()=>CM,fromScaling:()=>bM,fromTranslation:()=>_M,fromValues:()=>mM,fromXRotation:()=>vM,fromYRotation:()=>wM,fromZRotation:()=>EM,frustum:()=>ap,getRotation:()=>TM,getScaling:()=>Qx,getTranslation:()=>PM,identity:()=>Zx,invert:()=>Qh,lookAt:()=>up,mul:()=>zM,multiply:()=>ps,multiplyScalar:()=>NM,multiplyScalarAndAdd:()=>FM,ortho:()=>lp,orthoNO:()=>e0,orthoZO:()=>RM,perspective:()=>cp,perspectiveFromFieldOfView:()=>IM,perspectiveNO:()=>Jx,perspectiveZO:()=>MM,rotate:()=>rp,rotateX:()=>np,rotateY:()=>ip,rotateZ:()=>op,scale:()=>tp,set:()=>gM,str:()=>OM,sub:()=>$M,subtract:()=>t0,targetTo:()=>BM,translate:()=>ep,transpose:()=>Kh});function dM(){let r=new J(16);return J!=Float32Array&&(r[1]=0,r[2]=0,r[3]=0,r[4]=0,r[6]=0,r[7]=0,r[8]=0,r[9]=0,r[11]=0,r[12]=0,r[13]=0,r[14]=0),r[0]=1,r[5]=1,r[10]=1,r[15]=1,r}function hM(r){let e=new J(16);return e[0]=r[0],e[1]=r[1],e[2]=r[2],e[3]=r[3],e[4]=r[4],e[5]=r[5],e[6]=r[6],e[7]=r[7],e[8]=r[8],e[9]=r[9],e[10]=r[10],e[11]=r[11],e[12]=r[12],e[13]=r[13],e[14]=r[14],e[15]=r[15],e}function pM(r,e){return r[0]=e[0],r[1]=e[1],r[2]=e[2],r[3]=e[3],r[4]=e[4],r[5]=e[5],r[6]=e[6],r[7]=e[7],r[8]=e[8],r[9]=e[9],r[10]=e[10],r[11]=e[11],r[12]=e[12],r[13]=e[13],r[14]=e[14],r[15]=e[15],r}function mM(r,e,t,n,i,o,s,a,c,l,u,f,h,p,m,g){let y=new J(16);return y[0]=r,y[1]=e,y[2]=t,y[3]=n,y[4]=i,y[5]=o,y[6]=s,y[7]=a,y[8]=c,y[9]=l,y[10]=u,y[11]=f,y[12]=h,y[13]=p,y[14]=m,y[15]=g,y}function gM(r,e,t,n,i,o,s,a,c,l,u,f,h,p,m,g,y){return r[0]=e,r[1]=t,r[2]=n,r[3]=i,r[4]=o,r[5]=s,r[6]=a,r[7]=c,r[8]=l,r[9]=u,r[10]=f,r[11]=h,r[12]=p,r[13]=m,r[14]=g,r[15]=y,r}function Zx(r){return r[0]=1,r[1]=0,r[2]=0,r[3]=0,r[4]=0,r[5]=1,r[6]=0,r[7]=0,r[8]=0,r[9]=0,r[10]=1,r[11]=0,r[12]=0,r[13]=0,r[14]=0,r[15]=1,r}function Kh(r,e){if(r===e){let t=e[1],n=e[2],i=e[3],o=e[6],s=e[7],a=e[11];r[1]=e[4],r[2]=e[8],r[3]=e[12],r[4]=t,r[6]=e[9],r[7]=e[13],r[8]=n,r[9]=o,r[11]=e[14],r[12]=i,r[13]=s,r[14]=a}else r[0]=e[0],r[1]=e[4],r[2]=e[8],r[3]=e[12],r[4]=e[1],r[5]=e[5],r[6]=e[9],r[7]=e[13],r[8]=e[2],r[9]=e[6],r[10]=e[10],r[11]=e[14],r[12]=e[3],r[13]=e[7],r[14]=e[11],r[15]=e[15];return r}function Qh(r,e){let t=e[0],n=e[1],i=e[2],o=e[3],s=e[4],a=e[5],c=e[6],l=e[7],u=e[8],f=e[9],h=e[10],p=e[11],m=e[12],g=e[13],y=e[14],x=e[15],v=t*a-n*s,_=t*c-i*s,w=t*l-o*s,E=n*c-i*a,S=n*l-o*a,C=i*l-o*c,A=u*g-f*m,B=u*y-h*m,L=u*x-p*m,M=f*y-h*g,I=f*x-p*g,R=h*x-p*y,k=v*R-_*I+w*M+E*L-S*B+C*A;return k?(k=1/k,r[0]=(a*R-c*I+l*M)*k,r[1]=(i*I-n*R-o*M)*k,r[2]=(g*C-y*S+x*E)*k,r[3]=(h*S-f*C-p*E)*k,r[4]=(c*L-s*R-l*B)*k,r[5]=(t*R-i*L+o*B)*k,r[6]=(y*w-m*C-x*_)*k,r[7]=(u*C-h*w+p*_)*k,r[8]=(s*I-a*L+l*A)*k,r[9]=(n*L-t*I-o*A)*k,r[10]=(m*S-g*w+x*v)*k,r[11]=(f*w-u*S-p*v)*k,r[12]=(a*B-s*M-c*A)*k,r[13]=(t*M-n*B+i*A)*k,r[14]=(g*_-m*E-y*v)*k,r[15]=(u*E-f*_+h*v)*k,r):null}function yM(r,e){let t=e[0],n=e[1],i=e[2],o=e[3],s=e[4],a=e[5],c=e[6],l=e[7],u=e[8],f=e[9],h=e[10],p=e[11],m=e[12],g=e[13],y=e[14],x=e[15],v=t*a-n*s,_=t*c-i*s,w=t*l-o*s,E=n*c-i*a,S=n*l-o*a,C=i*l-o*c,A=u*g-f*m,B=u*y-h*m,L=u*x-p*m,M=f*y-h*g,I=f*x-p*g,R=h*x-p*y;return r[0]=a*R-c*I+l*M,r[1]=i*I-n*R-o*M,r[2]=g*C-y*S+x*E,r[3]=h*S-f*C-p*E,r[4]=c*L-s*R-l*B,r[5]=t*R-i*L+o*B,r[6]=y*w-m*C-x*_,r[7]=u*C-h*w+p*_,r[8]=s*I-a*L+l*A,r[9]=n*L-t*I-o*A,r[10]=m*S-g*w+x*v,r[11]=f*w-u*S-p*v,r[12]=a*B-s*M-c*A,r[13]=t*M-n*B+i*A,r[14]=g*_-m*E-y*v,r[15]=u*E-f*_+h*v,r}function Jh(r){let e=r[0],t=r[1],n=r[2],i=r[3],o=r[4],s=r[5],a=r[6],c=r[7],l=r[8],u=r[9],f=r[10],h=r[11],p=r[12],m=r[13],g=r[14],y=r[15],x=e*s-t*o,v=e*a-n*o,_=t*a-n*s,w=l*m-u*p,E=l*g-f*p,S=u*g-f*m,C=e*S-t*E+n*w,A=o*S-s*E+a*w,B=l*_-u*v+f*x,L=p*_-m*v+g*x;return c*C-i*A+y*B-h*L}function ps(r,e,t){let n=e[0],i=e[1],o=e[2],s=e[3],a=e[4],c=e[5],l=e[6],u=e[7],f=e[8],h=e[9],p=e[10],m=e[11],g=e[12],y=e[13],x=e[14],v=e[15],_=t[0],w=t[1],E=t[2],S=t[3];return r[0]=_*n+w*a+E*f+S*g,r[1]=_*i+w*c+E*h+S*y,r[2]=_*o+w*l+E*p+S*x,r[3]=_*s+w*u+E*m+S*v,_=t[4],w=t[5],E=t[6],S=t[7],r[4]=_*n+w*a+E*f+S*g,r[5]=_*i+w*c+E*h+S*y,r[6]=_*o+w*l+E*p+S*x,r[7]=_*s+w*u+E*m+S*v,_=t[8],w=t[9],E=t[10],S=t[11],r[8]=_*n+w*a+E*f+S*g,r[9]=_*i+w*c+E*h+S*y,r[10]=_*o+w*l+E*p+S*x,r[11]=_*s+w*u+E*m+S*v,_=t[12],w=t[13],E=t[14],S=t[15],r[12]=_*n+w*a+E*f+S*g,r[13]=_*i+w*c+E*h+S*y,r[14]=_*o+w*l+E*p+S*x,r[15]=_*s+w*u+E*m+S*v,r}function ep(r,e,t){let n=t[0],i=t[1],o=t[2],s,a,c,l,u,f,h,p,m,g,y,x;return e===r?(r[12]=e[0]*n+e[4]*i+e[8]*o+e[12],r[13]=e[1]*n+e[5]*i+e[9]*o+e[13],r[14]=e[2]*n+e[6]*i+e[10]*o+e[14],r[15]=e[3]*n+e[7]*i+e[11]*o+e[15]):(s=e[0],a=e[1],c=e[2],l=e[3],u=e[4],f=e[5],h=e[6],p=e[7],m=e[8],g=e[9],y=e[10],x=e[11],r[0]=s,r[1]=a,r[2]=c,r[3]=l,r[4]=u,r[5]=f,r[6]=h,r[7]=p,r[8]=m,r[9]=g,r[10]=y,r[11]=x,r[12]=s*n+u*i+m*o+e[12],r[13]=a*n+f*i+g*o+e[13],r[14]=c*n+h*i+y*o+e[14],r[15]=l*n+p*i+x*o+e[15]),r}function tp(r,e,t){let n=t[0],i=t[1],o=t[2];return r[0]=e[0]*n,r[1]=e[1]*n,r[2]=e[2]*n,r[3]=e[3]*n,r[4]=e[4]*i,r[5]=e[5]*i,r[6]=e[6]*i,r[7]=e[7]*i,r[8]=e[8]*o,r[9]=e[9]*o,r[10]=e[10]*o,r[11]=e[11]*o,r[12]=e[12],r[13]=e[13],r[14]=e[14],r[15]=e[15],r}function rp(r,e,t,n){let i=n[0],o=n[1],s=n[2],a=Math.sqrt(i*i+o*o+s*s),c,l,u,f,h,p,m,g,y,x,v,_,w,E,S,C,A,B,L,M,I,R,k,W;return a<1e-6?null:(a=1/a,i*=a,o*=a,s*=a,l=Math.sin(t),c=Math.cos(t),u=1-c,f=e[0],h=e[1],p=e[2],m=e[3],g=e[4],y=e[5],x=e[6],v=e[7],_=e[8],w=e[9],E=e[10],S=e[11],C=i*i*u+c,A=o*i*u+s*l,B=s*i*u-o*l,L=i*o*u-s*l,M=o*o*u+c,I=s*o*u+i*l,R=i*s*u+o*l,k=o*s*u-i*l,W=s*s*u+c,r[0]=f*C+g*A+_*B,r[1]=h*C+y*A+w*B,r[2]=p*C+x*A+E*B,r[3]=m*C+v*A+S*B,r[4]=f*L+g*M+_*I,r[5]=h*L+y*M+w*I,r[6]=p*L+x*M+E*I,r[7]=m*L+v*M+S*I,r[8]=f*R+g*k+_*W,r[9]=h*R+y*k+w*W,r[10]=p*R+x*k+E*W,r[11]=m*R+v*k+S*W,e!==r&&(r[12]=e[12],r[13]=e[13],r[14]=e[14],r[15]=e[15]),r)}function np(r,e,t){let n=Math.sin(t),i=Math.cos(t),o=e[4],s=e[5],a=e[6],c=e[7],l=e[8],u=e[9],f=e[10],h=e[11];return e!==r&&(r[0]=e[0],r[1]=e[1],r[2]=e[2],r[3]=e[3],r[12]=e[12],r[13]=e[13],r[14]=e[14],r[15]=e[15]),r[4]=o*i+l*n,r[5]=s*i+u*n,r[6]=a*i+f*n,r[7]=c*i+h*n,r[8]=l*i-o*n,r[9]=u*i-s*n,r[10]=f*i-a*n,r[11]=h*i-c*n,r}function ip(r,e,t){let n=Math.sin(t),i=Math.cos(t),o=e[0],s=e[1],a=e[2],c=e[3],l=e[8],u=e[9],f=e[10],h=e[11];return e!==r&&(r[4]=e[4],r[5]=e[5],r[6]=e[6],r[7]=e[7],r[12]=e[12],r[13]=e[13],r[14]=e[14],r[15]=e[15]),r[0]=o*i-l*n,r[1]=s*i-u*n,r[2]=a*i-f*n,r[3]=c*i-h*n,r[8]=o*n+l*i,r[9]=s*n+u*i,r[10]=a*n+f*i,r[11]=c*n+h*i,r}function op(r,e,t){let n=Math.sin(t),i=Math.cos(t),o=e[0],s=e[1],a=e[2],c=e[3],l=e[4],u=e[5],f=e[6],h=e[7];return e!==r&&(r[8]=e[8],r[9]=e[9],r[10]=e[10],r[11]=e[11],r[12]=e[12],r[13]=e[13],r[14]=e[14],r[15]=e[15]),r[0]=o*i+l*n,r[1]=s*i+u*n,r[2]=a*i+f*n,r[3]=c*i+h*n,r[4]=l*i-o*n,r[5]=u*i-s*n,r[6]=f*i-a*n,r[7]=h*i-c*n,r}function _M(r,e){return r[0]=1,r[1]=0,r[2]=0,r[3]=0,r[4]=0,r[5]=1,r[6]=0,r[7]=0,r[8]=0,r[9]=0,r[10]=1,r[11]=0,r[12]=e[0],r[13]=e[1],r[14]=e[2],r[15]=1,r}function bM(r,e){return r[0]=e[0],r[1]=0,r[2]=0,r[3]=0,r[4]=0,r[5]=e[1],r[6]=0,r[7]=0,r[8]=0,r[9]=0,r[10]=e[2],r[11]=0,r[12]=0,r[13]=0,r[14]=0,r[15]=1,r}function xM(r,e,t){let n=t[0],i=t[1],o=t[2],s=Math.sqrt(n*n+i*i+o*o),a,c,l;return s<1e-6?null:(s=1/s,n*=s,i*=s,o*=s,c=Math.sin(e),a=Math.cos(e),l=1-a,r[0]=n*n*l+a,r[1]=i*n*l+o*c,r[2]=o*n*l-i*c,r[3]=0,r[4]=n*i*l-o*c,r[5]=i*i*l+a,r[6]=o*i*l+n*c,r[7]=0,r[8]=n*o*l+i*c,r[9]=i*o*l-n*c,r[10]=o*o*l+a,r[11]=0,r[12]=0,r[13]=0,r[14]=0,r[15]=1,r)}function vM(r,e){let t=Math.sin(e),n=Math.cos(e);return r[0]=1,r[1]=0,r[2]=0,r[3]=0,r[4]=0,r[5]=n,r[6]=t,r[7]=0,r[8]=0,r[9]=-t,r[10]=n,r[11]=0,r[12]=0,r[13]=0,r[14]=0,r[15]=1,r}function wM(r,e){let t=Math.sin(e),n=Math.cos(e);return r[0]=n,r[1]=0,r[2]=-t,r[3]=0,r[4]=0,r[5]=1,r[6]=0,r[7]=0,r[8]=t,r[9]=0,r[10]=n,r[11]=0,r[12]=0,r[13]=0,r[14]=0,r[15]=1,r}function EM(r,e){let t=Math.sin(e),n=Math.cos(e);return r[0]=n,r[1]=t,r[2]=0,r[3]=0,r[4]=-t,r[5]=n,r[6]=0,r[7]=0,r[8]=0,r[9]=0,r[10]=1,r[11]=0,r[12]=0,r[13]=0,r[14]=0,r[15]=1,r}function Kx(r,e,t){let n=e[0],i=e[1],o=e[2],s=e[3],a=n+n,c=i+i,l=o+o,u=n*a,f=n*c,h=n*l,p=i*c,m=i*l,g=o*l,y=s*a,x=s*c,v=s*l;return r[0]=1-(p+g),r[1]=f+v,r[2]=h-x,r[3]=0,r[4]=f-v,r[5]=1-(u+g),r[6]=m+y,r[7]=0,r[8]=h+x,r[9]=m-y,r[10]=1-(u+p),r[11]=0,r[12]=t[0],r[13]=t[1],r[14]=t[2],r[15]=1,r}function SM(r,e){let t=new J(3),n=-e[0],i=-e[1],o=-e[2],s=e[3],a=e[4],c=e[5],l=e[6],u=e[7],f=n*n+i*i+o*o+s*s;return f>0?(t[0]=(a*s+u*n+c*o-l*i)*2/f,t[1]=(c*s+u*i+l*n-a*o)*2/f,t[2]=(l*s+u*o+a*i-c*n)*2/f):(t[0]=(a*s+u*n+c*o-l*i)*2,t[1]=(c*s+u*i+l*n-a*o)*2,t[2]=(l*s+u*o+a*i-c*n)*2),Kx(r,e,t),r}function PM(r,e){return r[0]=e[12],r[1]=e[13],r[2]=e[14],r}function Qx(r,e){let t=e[0],n=e[1],i=e[2],o=e[4],s=e[5],a=e[6],c=e[8],l=e[9],u=e[10];return r[0]=Math.sqrt(t*t+n*n+i*i),r[1]=Math.sqrt(o*o+s*s+a*a),r[2]=Math.sqrt(c*c+l*l+u*u),r}function TM(r,e){let t=new J(3);Qx(t,e);let n=1/t[0],i=1/t[1],o=1/t[2],s=e[0]*n,a=e[1]*i,c=e[2]*o,l=e[4]*n,u=e[5]*i,f=e[6]*o,h=e[8]*n,p=e[9]*i,m=e[10]*o,g=s+u+m,y=0;return g>0?(y=Math.sqrt(g+1)*2,r[3]=.25*y,r[0]=(f-p)/y,r[1]=(h-c)/y,r[2]=(a-l)/y):s>u&&s>m?(y=Math.sqrt(1+s-u-m)*2,r[3]=(f-p)/y,r[0]=.25*y,r[1]=(a+l)/y,r[2]=(h+c)/y):u>m?(y=Math.sqrt(1+u-s-m)*2,r[3]=(h-c)/y,r[0]=(a+l)/y,r[1]=.25*y,r[2]=(f+p)/y):(y=Math.sqrt(1+m-s-u)*2,r[3]=(a-l)/y,r[0]=(h+c)/y,r[1]=(f+p)/y,r[2]=.25*y),r}function LM(r,e,t,n){e[0]=n[12],e[1]=n[13],e[2]=n[14];let i=n[0],o=n[1],s=n[2],a=n[4],c=n[5],l=n[6],u=n[8],f=n[9],h=n[10];t[0]=Math.sqrt(i*i+o*o+s*s),t[1]=Math.sqrt(a*a+c*c+l*l),t[2]=Math.sqrt(u*u+f*f+h*h);let p=1/t[0],m=1/t[1],g=1/t[2],y=i*p,x=o*m,v=s*g,_=a*p,w=c*m,E=l*g,S=u*p,C=f*m,A=h*g,B=y+w+A,L=0;return B>0?(L=Math.sqrt(B+1)*2,r[3]=.25*L,r[0]=(E-C)/L,r[1]=(S-v)/L,r[2]=(x-_)/L):y>w&&y>A?(L=Math.sqrt(1+y-w-A)*2,r[3]=(E-C)/L,r[0]=.25*L,r[1]=(x+_)/L,r[2]=(S+v)/L):w>A?(L=Math.sqrt(1+w-y-A)*2,r[3]=(S-v)/L,r[0]=(x+_)/L,r[1]=.25*L,r[2]=(E+C)/L):(L=Math.sqrt(1+A-y-w)*2,r[3]=(x-_)/L,r[0]=(S+v)/L,r[1]=(E+C)/L,r[2]=.25*L),r}function AM(r,e,t,n){let i=e[0],o=e[1],s=e[2],a=e[3],c=i+i,l=o+o,u=s+s,f=i*c,h=i*l,p=i*u,m=o*l,g=o*u,y=s*u,x=a*c,v=a*l,_=a*u,w=n[0],E=n[1],S=n[2];return r[0]=(1-(m+y))*w,r[1]=(h+_)*w,r[2]=(p-v)*w,r[3]=0,r[4]=(h-_)*E,r[5]=(1-(f+y))*E,r[6]=(g+x)*E,r[7]=0,r[8]=(p+v)*S,r[9]=(g-x)*S,r[10]=(1-(f+m))*S,r[11]=0,r[12]=t[0],r[13]=t[1],r[14]=t[2],r[15]=1,r}function CM(r,e,t,n,i){let o=e[0],s=e[1],a=e[2],c=e[3],l=o+o,u=s+s,f=a+a,h=o*l,p=o*u,m=o*f,g=s*u,y=s*f,x=a*f,v=c*l,_=c*u,w=c*f,E=n[0],S=n[1],C=n[2],A=i[0],B=i[1],L=i[2],M=(1-(g+x))*E,I=(p+w)*E,R=(m-_)*E,k=(p-w)*S,W=(1-(h+x))*S,V=(y+v)*S,ue=(m+_)*C,Pr=(y-v)*C,rn=(1-(h+g))*C;return r[0]=M,r[1]=I,r[2]=R,r[3]=0,r[4]=k,r[5]=W,r[6]=V,r[7]=0,r[8]=ue,r[9]=Pr,r[10]=rn,r[11]=0,r[12]=t[0]+A-(M*A+k*B+ue*L),r[13]=t[1]+B-(I*A+W*B+Pr*L),r[14]=t[2]+L-(R*A+V*B+rn*L),r[15]=1,r}function sp(r,e){let t=e[0],n=e[1],i=e[2],o=e[3],s=t+t,a=n+n,c=i+i,l=t*s,u=n*s,f=n*a,h=i*s,p=i*a,m=i*c,g=o*s,y=o*a,x=o*c;return r[0]=1-f-m,r[1]=u+x,r[2]=h-y,r[3]=0,r[4]=u-x,r[5]=1-l-m,r[6]=p+g,r[7]=0,r[8]=h+y,r[9]=p-g,r[10]=1-l-f,r[11]=0,r[12]=0,r[13]=0,r[14]=0,r[15]=1,r}function ap(r,e,t,n,i,o,s){let a=1/(t-e),c=1/(i-n),l=1/(o-s);return r[0]=o*2*a,r[1]=0,r[2]=0,r[3]=0,r[4]=0,r[5]=o*2*c,r[6]=0,r[7]=0,r[8]=(t+e)*a,r[9]=(i+n)*c,r[10]=(s+o)*l,r[11]=-1,r[12]=0,r[13]=0,r[14]=s*o*2*l,r[15]=0,r}function Jx(r,e,t,n,i){let o=1/Math.tan(e/2);if(r[0]=o/t,r[1]=0,r[2]=0,r[3]=0,r[4]=0,r[5]=o,r[6]=0,r[7]=0,r[8]=0,r[9]=0,r[11]=-1,r[12]=0,r[13]=0,r[15]=0,i!=null&&i!==1/0){let s=1/(n-i);r[10]=(i+n)*s,r[14]=2*i*n*s}else r[10]=-1,r[14]=-2*n;return r}function MM(r,e,t,n,i){let o=1/Math.tan(e/2);if(r[0]=o/t,r[1]=0,r[2]=0,r[3]=0,r[4]=0,r[5]=o,r[6]=0,r[7]=0,r[8]=0,r[9]=0,r[11]=-1,r[12]=0,r[13]=0,r[15]=0,i!=null&&i!==1/0){let s=1/(n-i);r[10]=i*s,r[14]=i*n*s}else r[10]=-1,r[14]=-n;return r}function IM(r,e,t,n){let i=Math.tan(e.upDegrees*Math.PI/180),o=Math.tan(e.downDegrees*Math.PI/180),s=Math.tan(e.leftDegrees*Math.PI/180),a=Math.tan(e.rightDegrees*Math.PI/180),c=2/(s+a),l=2/(i+o);return r[0]=c,r[1]=0,r[2]=0,r[3]=0,r[4]=0,r[5]=l,r[6]=0,r[7]=0,r[8]=-((s-a)*c*.5),r[9]=(i-o)*l*.5,r[10]=n/(t-n),r[11]=-1,r[12]=0,r[13]=0,r[14]=n*t/(t-n),r[15]=0,r}function e0(r,e,t,n,i,o,s){let a=1/(e-t),c=1/(n-i),l=1/(o-s);return r[0]=-2*a,r[1]=0,r[2]=0,r[3]=0,r[4]=0,r[5]=-2*c,r[6]=0,r[7]=0,r[8]=0,r[9]=0,r[10]=2*l,r[11]=0,r[12]=(e+t)*a,r[13]=(i+n)*c,r[14]=(s+o)*l,r[15]=1,r}function RM(r,e,t,n,i,o,s){let a=1/(e-t),c=1/(n-i),l=1/(o-s);return r[0]=-2*a,r[1]=0,r[2]=0,r[3]=0,r[4]=0,r[5]=-2*c,r[6]=0,r[7]=0,r[8]=0,r[9]=0,r[10]=l,r[11]=0,r[12]=(e+t)*a,r[13]=(i+n)*c,r[14]=o*l,r[15]=1,r}function up(r,e,t,n){let i,o,s,a,c,l,u,f,h,p,m=e[0],g=e[1],y=e[2],x=n[0],v=n[1],_=n[2],w=t[0],E=t[1],S=t[2];return Math.abs(m-w)<1e-6&&Math.abs(g-E)<1e-6&&Math.abs(y-S)<1e-6?Zx(r):(f=m-w,h=g-E,p=y-S,i=1/Math.sqrt(f*f+h*h+p*p),f*=i,h*=i,p*=i,o=v*p-_*h,s=_*f-x*p,a=x*h-v*f,i=Math.sqrt(o*o+s*s+a*a),i?(i=1/i,o*=i,s*=i,a*=i):(o=0,s=0,a=0),c=h*a-p*s,l=p*o-f*a,u=f*s-h*o,i=Math.sqrt(c*c+l*l+u*u),i?(i=1/i,c*=i,l*=i,u*=i):(c=0,l=0,u=0),r[0]=o,r[1]=c,r[2]=f,r[3]=0,r[4]=s,r[5]=l,r[6]=h,r[7]=0,r[8]=a,r[9]=u,r[10]=p,r[11]=0,r[12]=-(o*m+s*g+a*y),r[13]=-(c*m+l*g+u*y),r[14]=-(f*m+h*g+p*y),r[15]=1,r)}function BM(r,e,t,n){let i=e[0],o=e[1],s=e[2],a=n[0],c=n[1],l=n[2],u=i-t[0],f=o-t[1],h=s-t[2],p=u*u+f*f+h*h;p>0&&(p=1/Math.sqrt(p),u*=p,f*=p,h*=p);let m=c*h-l*f,g=l*u-a*h,y=a*f-c*u;return p=m*m+g*g+y*y,p>0&&(p=1/Math.sqrt(p),m*=p,g*=p,y*=p),r[0]=m,r[1]=g,r[2]=y,r[3]=0,r[4]=f*y-h*g,r[5]=h*m-u*y,r[6]=u*g-f*m,r[7]=0,r[8]=u,r[9]=f,r[10]=h,r[11]=0,r[12]=i,r[13]=o,r[14]=s,r[15]=1,r}function OM(r){return`mat4(${r[0]}, ${r[1]}, ${r[2]}, ${r[3]}, ${r[4]}, ${r[5]}, ${r[6]}, ${r[7]}, ${r[8]}, ${r[9]}, ${r[10]}, ${r[11]}, ${r[12]}, ${r[13]}, ${r[14]}, ${r[15]})`}function kM(r){return Math.sqrt(r[0]*r[0]+r[1]*r[1]+r[2]*r[2]+r[3]*r[3]+r[4]*r[4]+r[5]*r[5]+r[6]*r[6]+r[7]*r[7]+r[8]*r[8]+r[9]*r[9]+r[10]*r[10]+r[11]*r[11]+r[12]*r[12]+r[13]*r[13]+r[14]*r[14]+r[15]*r[15])}function DM(r,e,t){return r[0]=e[0]+t[0],r[1]=e[1]+t[1],r[2]=e[2]+t[2],r[3]=e[3]+t[3],r[4]=e[4]+t[4],r[5]=e[5]+t[5],r[6]=e[6]+t[6],r[7]=e[7]+t[7],r[8]=e[8]+t[8],r[9]=e[9]+t[9],r[10]=e[10]+t[10],r[11]=e[11]+t[11],r[12]=e[12]+t[12],r[13]=e[13]+t[13],r[14]=e[14]+t[14],r[15]=e[15]+t[15],r}function t0(r,e,t){return r[0]=e[0]-t[0],r[1]=e[1]-t[1],r[2]=e[2]-t[2],r[3]=e[3]-t[3],r[4]=e[4]-t[4],r[5]=e[5]-t[5],r[6]=e[6]-t[6],r[7]=e[7]-t[7],r[8]=e[8]-t[8],r[9]=e[9]-t[9],r[10]=e[10]-t[10],r[11]=e[11]-t[11],r[12]=e[12]-t[12],r[13]=e[13]-t[13],r[14]=e[14]-t[14],r[15]=e[15]-t[15],r}function NM(r,e,t){return r[0]=e[0]*t,r[1]=e[1]*t,r[2]=e[2]*t,r[3]=e[3]*t,r[4]=e[4]*t,r[5]=e[5]*t,r[6]=e[6]*t,r[7]=e[7]*t,r[8]=e[8]*t,r[9]=e[9]*t,r[10]=e[10]*t,r[11]=e[11]*t,r[12]=e[12]*t,r[13]=e[13]*t,r[14]=e[14]*t,r[15]=e[15]*t,r}function FM(r,e,t,n){return r[0]=e[0]+t[0]*n,r[1]=e[1]+t[1]*n,r[2]=e[2]+t[2]*n,r[3]=e[3]+t[3]*n,r[4]=e[4]+t[4]*n,r[5]=e[5]+t[5]*n,r[6]=e[6]+t[6]*n,r[7]=e[7]+t[7]*n,r[8]=e[8]+t[8]*n,r[9]=e[9]+t[9]*n,r[10]=e[10]+t[10]*n,r[11]=e[11]+t[11]*n,r[12]=e[12]+t[12]*n,r[13]=e[13]+t[13]*n,r[14]=e[14]+t[14]*n,r[15]=e[15]+t[15]*n,r}function UM(r,e){return r[0]===e[0]&&r[1]===e[1]&&r[2]===e[2]&&r[3]===e[3]&&r[4]===e[4]&&r[5]===e[5]&&r[6]===e[6]&&r[7]===e[7]&&r[8]===e[8]&&r[9]===e[9]&&r[10]===e[10]&&r[11]===e[11]&&r[12]===e[12]&&r[13]===e[13]&&r[14]===e[14]&&r[15]===e[15]}function GM(r,e){let t=r[0],n=r[1],i=r[2],o=r[3],s=r[4],a=r[5],c=r[6],l=r[7],u=r[8],f=r[9],h=r[10],p=r[11],m=r[12],g=r[13],y=r[14],x=r[15],v=e[0],_=e[1],w=e[2],E=e[3],S=e[4],C=e[5],A=e[6],B=e[7],L=e[8],M=e[9],I=e[10],R=e[11],k=e[12],W=e[13],V=e[14],ue=e[15];return Math.abs(t-v)<=1e-6*Math.max(1,Math.abs(t),Math.abs(v))&&Math.abs(n-_)<=1e-6*Math.max(1,Math.abs(n),Math.abs(_))&&Math.abs(i-w)<=1e-6*Math.max(1,Math.abs(i),Math.abs(w))&&Math.abs(o-E)<=1e-6*Math.max(1,Math.abs(o),Math.abs(E))&&Math.abs(s-S)<=1e-6*Math.max(1,Math.abs(s),Math.abs(S))&&Math.abs(a-C)<=1e-6*Math.max(1,Math.abs(a),Math.abs(C))&&Math.abs(c-A)<=1e-6*Math.max(1,Math.abs(c),Math.abs(A))&&Math.abs(l-B)<=1e-6*Math.max(1,Math.abs(l),Math.abs(B))&&Math.abs(u-L)<=1e-6*Math.max(1,Math.abs(u),Math.abs(L))&&Math.abs(f-M)<=1e-6*Math.max(1,Math.abs(f),Math.abs(M))&&Math.abs(h-I)<=1e-6*Math.max(1,Math.abs(h),Math.abs(I))&&Math.abs(p-R)<=1e-6*Math.max(1,Math.abs(p),Math.abs(R))&&Math.abs(m-k)<=1e-6*Math.max(1,Math.abs(m),Math.abs(k))&&Math.abs(g-W)<=1e-6*Math.max(1,Math.abs(g),Math.abs(W))&&Math.abs(y-V)<=1e-6*Math.max(1,Math.abs(y),Math.abs(V))&&Math.abs(x-ue)<=1e-6*Math.max(1,Math.abs(x),Math.abs(ue))}var cp,lp,zM,$M,fp=b(()=>{Ln();cp=Jx;lp=e0;zM=ps,$M=t0});var Et={};cr(Et,{add:()=>a0,ceil:()=>VM,clone:()=>n0,copy:()=>o0,create:()=>r0,cross:()=>KM,dist:()=>sI,distance:()=>d0,div:()=>oI,divide:()=>u0,dot:()=>p0,equals:()=>rI,exactEquals:()=>g0,floor:()=>WM,forEach:()=>uI,fromValues:()=>i0,inverse:()=>ZM,len:()=>cI,length:()=>dp,lerp:()=>m0,max:()=>HM,min:()=>jM,mul:()=>iI,multiply:()=>l0,negate:()=>XM,normalize:()=>pp,random:()=>QM,round:()=>YM,scale:()=>f0,scaleAndAdd:()=>qM,set:()=>s0,sqrDist:()=>aI,sqrLen:()=>lI,squaredDistance:()=>h0,squaredLength:()=>hp,str:()=>tI,sub:()=>nI,subtract:()=>c0,transformMat4:()=>mp,transformQuat:()=>JM,zero:()=>eI});function r0(){let r=new J(4);return J!=Float32Array&&(r[0]=0,r[1]=0,r[2]=0,r[3]=0),r}function n0(r){let e=new J(4);return e[0]=r[0],e[1]=r[1],e[2]=r[2],e[3]=r[3],e}function i0(r,e,t,n){let i=new J(4);return i[0]=r,i[1]=e,i[2]=t,i[3]=n,i}function o0(r,e){return r[0]=e[0],r[1]=e[1],r[2]=e[2],r[3]=e[3],r}function s0(r,e,t,n,i){return r[0]=e,r[1]=t,r[2]=n,r[3]=i,r}function a0(r,e,t){return r[0]=e[0]+t[0],r[1]=e[1]+t[1],r[2]=e[2]+t[2],r[3]=e[3]+t[3],r}function c0(r,e,t){return r[0]=e[0]-t[0],r[1]=e[1]-t[1],r[2]=e[2]-t[2],r[3]=e[3]-t[3],r}function l0(r,e,t){return r[0]=e[0]*t[0],r[1]=e[1]*t[1],r[2]=e[2]*t[2],r[3]=e[3]*t[3],r}function u0(r,e,t){return r[0]=e[0]/t[0],r[1]=e[1]/t[1],r[2]=e[2]/t[2],r[3]=e[3]/t[3],r}function VM(r,e){return r[0]=Math.ceil(e[0]),r[1]=Math.ceil(e[1]),r[2]=Math.ceil(e[2]),r[3]=Math.ceil(e[3]),r}function WM(r,e){return r[0]=Math.floor(e[0]),r[1]=Math.floor(e[1]),r[2]=Math.floor(e[2]),r[3]=Math.floor(e[3]),r}function jM(r,e,t){return r[0]=Math.min(e[0],t[0]),r[1]=Math.min(e[1],t[1]),r[2]=Math.min(e[2],t[2]),r[3]=Math.min(e[3],t[3]),r}function HM(r,e,t){return r[0]=Math.max(e[0],t[0]),r[1]=Math.max(e[1],t[1]),r[2]=Math.max(e[2],t[2]),r[3]=Math.max(e[3],t[3]),r}function YM(r,e){return r[0]=ht(e[0]),r[1]=ht(e[1]),r[2]=ht(e[2]),r[3]=ht(e[3]),r}function f0(r,e,t){return r[0]=e[0]*t,r[1]=e[1]*t,r[2]=e[2]*t,r[3]=e[3]*t,r}function qM(r,e,t,n){return r[0]=e[0]+t[0]*n,r[1]=e[1]+t[1]*n,r[2]=e[2]+t[2]*n,r[3]=e[3]+t[3]*n,r}function d0(r,e){let t=e[0]-r[0],n=e[1]-r[1],i=e[2]-r[2],o=e[3]-r[3];return Math.sqrt(t*t+n*n+i*i+o*o)}function h0(r,e){let t=e[0]-r[0],n=e[1]-r[1],i=e[2]-r[2],o=e[3]-r[3];return t*t+n*n+i*i+o*o}function dp(r){let e=r[0],t=r[1],n=r[2],i=r[3];return Math.sqrt(e*e+t*t+n*n+i*i)}function hp(r){let e=r[0],t=r[1],n=r[2],i=r[3];return e*e+t*t+n*n+i*i}function XM(r,e){return r[0]=-e[0],r[1]=-e[1],r[2]=-e[2],r[3]=-e[3],r}function ZM(r,e){return r[0]=1/e[0],r[1]=1/e[1],r[2]=1/e[2],r[3]=1/e[3],r}function pp(r,e){let t=e[0],n=e[1],i=e[2],o=e[3],s=t*t+n*n+i*i+o*o;return s>0&&(s=1/Math.sqrt(s)),r[0]=t*s,r[1]=n*s,r[2]=i*s,r[3]=o*s,r}function p0(r,e){return r[0]*e[0]+r[1]*e[1]+r[2]*e[2]+r[3]*e[3]}function KM(r,e,t,n){let i=t[0]*n[1]-t[1]*n[0],o=t[0]*n[2]-t[2]*n[0],s=t[0]*n[3]-t[3]*n[0],a=t[1]*n[2]-t[2]*n[1],c=t[1]*n[3]-t[3]*n[1],l=t[2]*n[3]-t[3]*n[2],u=e[0],f=e[1],h=e[2],p=e[3];return r[0]=f*l-h*c+p*a,r[1]=-(u*l)+h*s-p*o,r[2]=u*c-f*s+p*i,r[3]=-(u*a)+f*o-h*i,r}function m0(r,e,t,n){let i=e[0],o=e[1],s=e[2],a=e[3];return r[0]=i+n*(t[0]-i),r[1]=o+n*(t[1]-o),r[2]=s+n*(t[2]-s),r[3]=a+n*(t[3]-a),r}function QM(r,e){e=e===void 0?1:e;let t,n,i,o,s,a;do t=jt()*2-1,n=jt()*2-1,s=t*t+n*n;while(s>=1);do i=jt()*2-1,o=jt()*2-1,a=i*i+o*o;while(a>=1);let c=Math.sqrt((1-s)/a);return r[0]=e*t,r[1]=e*n,r[2]=e*i*c,r[3]=e*o*c,r}function mp(r,e,t){let n=e[0],i=e[1],o=e[2],s=e[3];return r[0]=t[0]*n+t[4]*i+t[8]*o+t[12]*s,r[1]=t[1]*n+t[5]*i+t[9]*o+t[13]*s,r[2]=t[2]*n+t[6]*i+t[10]*o+t[14]*s,r[3]=t[3]*n+t[7]*i+t[11]*o+t[15]*s,r}function JM(r,e,t){let n=e[0],i=e[1],o=e[2],s=t[0],a=t[1],c=t[2],l=t[3],u=l*n+a*o-c*i,f=l*i+c*n-s*o,h=l*o+s*i-a*n,p=-s*n-a*i-c*o;return r[0]=u*l+p*-s+f*-c-h*-a,r[1]=f*l+p*-a+h*-s-u*-c,r[2]=h*l+p*-c+u*-a-f*-s,r[3]=e[3],r}function eI(r){return r[0]=0,r[1]=0,r[2]=0,r[3]=0,r}function tI(r){return`vec4(${r[0]}, ${r[1]}, ${r[2]}, ${r[3]})`}function g0(r,e){return r[0]===e[0]&&r[1]===e[1]&&r[2]===e[2]&&r[3]===e[3]}function rI(r,e){let t=r[0],n=r[1],i=r[2],o=r[3],s=e[0],a=e[1],c=e[2],l=e[3];return Math.abs(t-s)<=1e-6*Math.max(1,Math.abs(t),Math.abs(s))&&Math.abs(n-a)<=1e-6*Math.max(1,Math.abs(n),Math.abs(a))&&Math.abs(i-c)<=1e-6*Math.max(1,Math.abs(i),Math.abs(c))&&Math.abs(o-l)<=1e-6*Math.max(1,Math.abs(o),Math.abs(l))}var nI,iI,oI,sI,aI,cI,lI,uI,gl=b(()=>{Ln();nI=c0,iI=l0,oI=u0,sI=d0,aI=h0,cI=dp,lI=hp,uI=(function(){let r=r0();return function(e,t,n,i,o,s){let a,c;for(t||(t=4),n||(n=0),i?c=Math.min(i*t+n,e.length):c=e.length,a=n;a<c;a+=t)r[0]=e[a],r[1]=e[a+1],r[2]=e[a+2],r[3]=e[a+3],o(r,r,s),e[a]=r[0],e[a+1]=r[1],e[a+2]=r[2],e[a+3]=r[3];return e}})()});function pI(){return yl||(yl=new ge([0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]),Object.freeze(yl)),yl}function mI(){return _l||(_l=new ge,Object.freeze(_l)),_l}function y0(r){if(r>Math.PI*2)throw Error("expected radians")}function gI(r,e,t,n,i,o){let s=2*o/(t-e),a=2*o/(i-n),c=(t+e)/(t-e),l=(i+n)/(i-n),u=-1,f=-1,h=-2*o;return r[0]=s,r[1]=0,r[2]=0,r[3]=0,r[4]=0,r[5]=a,r[6]=0,r[7]=0,r[8]=c,r[9]=l,r[10]=u,r[11]=f,r[12]=0,r[13]=0,r[14]=h,r[15]=0,r}var _p,fI,dI,gp,yp,hI,ge,yl,_l,_0=b(()=>{Yx();us();Gh();fp();Uh();hs();gl();(function(r){r[r.COL0ROW0=0]="COL0ROW0",r[r.COL0ROW1=1]="COL0ROW1",r[r.COL0ROW2=2]="COL0ROW2",r[r.COL0ROW3=3]="COL0ROW3",r[r.COL1ROW0=4]="COL1ROW0",r[r.COL1ROW1=5]="COL1ROW1",r[r.COL1ROW2=6]="COL1ROW2",r[r.COL1ROW3=7]="COL1ROW3",r[r.COL2ROW0=8]="COL2ROW0",r[r.COL2ROW1=9]="COL2ROW1",r[r.COL2ROW2=10]="COL2ROW2",r[r.COL2ROW3=11]="COL2ROW3",r[r.COL3ROW0=12]="COL3ROW0",r[r.COL3ROW1=13]="COL3ROW1",r[r.COL3ROW2=14]="COL3ROW2",r[r.COL3ROW3=15]="COL3ROW3"})(_p||(_p={}));fI=45*Math.PI/180,dI=1,gp=.1,yp=500,hI=Object.freeze([1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]),ge=class extends ml{static get IDENTITY(){return mI()}static get ZERO(){return pI()}get ELEMENTS(){return 16}get RANK(){return 4}get INDICES(){return _p}constructor(e){super(-0,-0,-0,-0,-0,-0,-0,-0,-0,-0,-0,-0,-0,-0,-0,-0),arguments.length===1&&Array.isArray(e)?this.copy(e):this.identity()}copy(e){return this[0]=e[0],this[1]=e[1],this[2]=e[2],this[3]=e[3],this[4]=e[4],this[5]=e[5],this[6]=e[6],this[7]=e[7],this[8]=e[8],this[9]=e[9],this[10]=e[10],this[11]=e[11],this[12]=e[12],this[13]=e[13],this[14]=e[14],this[15]=e[15],this.check()}set(e,t,n,i,o,s,a,c,l,u,f,h,p,m,g,y){return this[0]=e,this[1]=t,this[2]=n,this[3]=i,this[4]=o,this[5]=s,this[6]=a,this[7]=c,this[8]=l,this[9]=u,this[10]=f,this[11]=h,this[12]=p,this[13]=m,this[14]=g,this[15]=y,this.check()}setRowMajor(e,t,n,i,o,s,a,c,l,u,f,h,p,m,g,y){return this[0]=e,this[1]=o,this[2]=l,this[3]=p,this[4]=t,this[5]=s,this[6]=u,this[7]=m,this[8]=n,this[9]=a,this[10]=f,this[11]=g,this[12]=i,this[13]=c,this[14]=h,this[15]=y,this.check()}toRowMajor(e){return e[0]=this[0],e[1]=this[4],e[2]=this[8],e[3]=this[12],e[4]=this[1],e[5]=this[5],e[6]=this[9],e[7]=this[13],e[8]=this[2],e[9]=this[6],e[10]=this[10],e[11]=this[14],e[12]=this[3],e[13]=this[7],e[14]=this[11],e[15]=this[15],e}identity(){return this.copy(hI)}fromObject(e){return this.check()}fromQuaternion(e){return sp(this,e),this.check()}frustum(e){let{left:t,right:n,bottom:i,top:o,near:s=gp,far:a=yp}=e;return a===1/0?gI(this,t,n,i,o,s):ap(this,t,n,i,o,s,a),this.check()}lookAt(e){let{eye:t,center:n=[0,0,0],up:i=[0,1,0]}=e;return up(this,t,n,i),this.check()}ortho(e){let{left:t,right:n,bottom:i,top:o,near:s=gp,far:a=yp}=e;return lp(this,t,n,i,o,s,a),this.check()}orthographic(e){let{fovy:t=fI,aspect:n=dI,focalDistance:i=1,near:o=gp,far:s=yp}=e;y0(t);let a=t/2,c=i*Math.tan(a),l=c*n;return this.ortho({left:-l,right:l,bottom:-c,top:c,near:o,far:s})}perspective(e){let{fovy:t=45*Math.PI/180,aspect:n=1,near:i=.1,far:o=500}=e;return y0(t),cp(this,t,n,i,o),this.check()}determinant(){return Jh(this)}getScale(e=[-0,-0,-0]){return e[0]=Math.sqrt(this[0]*this[0]+this[1]*this[1]+this[2]*this[2]),e[1]=Math.sqrt(this[4]*this[4]+this[5]*this[5]+this[6]*this[6]),e[2]=Math.sqrt(this[8]*this[8]+this[9]*this[9]+this[10]*this[10]),e}getTranslation(e=[-0,-0,-0]){return e[0]=this[12],e[1]=this[13],e[2]=this[14],e}getRotation(e,t){e=e||[-0,-0,-0,-0,-0,-0,-0,-0,-0,-0,-0,-0,-0,-0,-0,-0],t=t||[-0,-0,-0];let n=this.getScale(t),i=1/n[0],o=1/n[1],s=1/n[2];return e[0]=this[0]*i,e[1]=this[1]*o,e[2]=this[2]*s,e[3]=0,e[4]=this[4]*i,e[5]=this[5]*o,e[6]=this[6]*s,e[7]=0,e[8]=this[8]*i,e[9]=this[9]*o,e[10]=this[10]*s,e[11]=0,e[12]=0,e[13]=0,e[14]=0,e[15]=1,e}getRotationMatrix3(e,t){e=e||[-0,-0,-0,-0,-0,-0,-0,-0,-0],t=t||[-0,-0,-0];let n=this.getScale(t),i=1/n[0],o=1/n[1],s=1/n[2];return e[0]=this[0]*i,e[1]=this[1]*o,e[2]=this[2]*s,e[3]=this[4]*i,e[4]=this[5]*o,e[5]=this[6]*s,e[6]=this[8]*i,e[7]=this[9]*o,e[8]=this[10]*s,e}transpose(){return Kh(this,this),this.check()}invert(){return Qh(this,this),this.check()}multiplyLeft(e){return ps(this,e,this),this.check()}multiplyRight(e){return ps(this,this,e),this.check()}rotateX(e){return np(this,this,e),this.check()}rotateY(e){return ip(this,this,e),this.check()}rotateZ(e){return op(this,this,e),this.check()}rotateXYZ(e){return this.rotateX(e[0]).rotateY(e[1]).rotateZ(e[2])}rotateAxis(e,t){return rp(this,this,e,t),this.check()}scale(e){return tp(this,this,Array.isArray(e)?e:[e,e,e]),this.check()}translate(e){return ep(this,this,e),this.check()}transform(e,t){return e.length===4?(t=mp(t||[-0,-0,-0,-0],e,this),ll(t,4),t):this.transformAsPoint(e,t)}transformAsPoint(e,t){let{length:n}=e,i;switch(n){case 2:i=Fh(t||[-0,-0],e,this);break;case 3:i=ds(t||[-0,-0,-0],e,this);break;default:throw new Error("Illegal vector")}return ll(i,e.length),i}transformAsVector(e,t){let n;switch(e.length){case 2:n=Nx(t||[-0,-0],e,this);break;case 3:n=fl(t||[-0,-0,-0],e,this);break;default:throw new Error("Illegal vector")}return ll(n,e.length),n}transformPoint(e,t){return this.transformAsPoint(e,t)}transformVector(e,t){return this.transformAsPoint(e,t)}transformDirection(e,t){return this.transformAsVector(e,t)}makeRotationX(e){return this.identity().rotateX(e)}makeTranslation(e,t,n){return this.identity().translate([e,t,n])}}});function b0(){let r=new J(4);return J!=Float32Array&&(r[0]=0,r[1]=0,r[2]=0),r[3]=1,r}function yI(r,e,t){t=t*.5;let n=Math.sin(t);return r[0]=n*e[0],r[1]=n*e[1],r[2]=n*e[2],r[3]=Math.cos(t),r}function bp(r,e,t,n){let i=e[0],o=e[1],s=e[2],a=e[3],c=t[0],l=t[1],u=t[2],f=t[3],h,p,m,g,y;return h=i*c+o*l+s*u+a*f,h<0&&(h=-h,c=-c,l=-l,u=-u,f=-f),1-h>1e-6?(p=Math.acos(h),y=Math.sin(p),m=Math.sin((1-n)*p)/y,g=Math.sin(n*p)/y):(m=1-n,g=n),r[0]=m*i+g*c,r[1]=m*o+g*l,r[2]=m*s+g*u,r[3]=m*a+g*f,r}function _I(r,e){let t=e[0]+e[4]+e[8],n;if(t>0)n=Math.sqrt(t+1),r[3]=.5*n,n=.5/n,r[0]=(e[5]-e[7])*n,r[1]=(e[6]-e[2])*n,r[2]=(e[1]-e[3])*n;else{let i=0;e[4]>e[0]&&(i=1),e[8]>e[i*3+i]&&(i=2);let o=(i+1)%3,s=(i+2)%3;n=Math.sqrt(e[i*3+i]-e[o*3+o]-e[s*3+s]+1),r[i]=.5*n,n=.5/n,r[3]=(e[o*3+s]-e[s*3+o])*n,r[o]=(e[o*3+i]+e[i*3+o])*n,r[s]=(e[s*3+i]+e[i*3+s])*n}return r}var x0,W8,j8,H8,v0=b(()=>{Ln();Zh();hs();gl();x0=pp,W8=(function(){let r=dl(),e=hl(1,0,0),t=hl(0,1,0);return function(n,i,o){let s=fs(i,o);return s<-.999999?(An(r,e,i),qh(r)<1e-6&&An(r,t,i),zh(r,r),yI(n,r,Math.PI),n):s>.999999?(n[0]=0,n[1]=0,n[2]=0,n[3]=1,n):(An(r,i,o),n[0]=r[0],n[1]=r[1],n[2]=r[2],n[3]=1+s,x0(n,n))}})(),j8=(function(){let r=b0(),e=b0();return function(t,n,i,o,s,a){return bp(r,n,s,a),bp(e,i,o,a),bp(t,r,e,2*a*(1-a)),t}})(),H8=(function(){let r=qx();return function(e,t,n,i){return r[0]=n[0],r[3]=n[1],r[6]=n[2],r[1]=i[0],r[4]=i[1],r[7]=i[2],r[2]=-t[0],r[5]=-t[1],r[8]=-t[2],x0(e,_I(e,r))}})()});var Y8,q8,X8,Z8,w0=b(()=>{Y8=Math.PI/2,q8=Math.PI/4,X8=Math.PI/6,Z8=Math.PI*2});var Ee=b(()=>{Hx();_0();w0();vi();Zh();fp();v0();Uh();hs();gl()});function xp(r,e=[],t=0){let n=Math.fround(r),i=r-n;return e[t]=n,e[t+1]=i,e}function E0(r){return r-Math.fround(r)}function S0(r){let e=new Float32Array(32);for(let t=0;t<4;++t)for(let n=0;n<4;++n){let i=t*4+n;xp(r[n*4+t],e,i*2)}return e}var P0=b(()=>{});function bl(r,e=!0){return r??e}function vp(r=[0,0,0],e=!0){return e?r.map(t=>t/255):[...r]}function T0(r,e=!0){let t=vp(r.slice(0,3),e),n=Number.isFinite(r[3]),i=n?r[3]:1;return[t[0],t[1],t[2],e&&n?i/255:i]}var wp=b(()=>{});var vI,wI,Mn,L0=b(()=>{vI=`#ifdef LUMA_FP32_TAN_PRECISION_WORKAROUND

// All these functions are for substituting tan() function from Intel GPU only
const float TWO_PI = 6.2831854820251465;
const float PI_2 = 1.5707963705062866;
const float PI_16 = 0.1963495463132858;

const float SIN_TABLE_0 = 0.19509032368659973;
const float SIN_TABLE_1 = 0.3826834261417389;
const float SIN_TABLE_2 = 0.5555702447891235;
const float SIN_TABLE_3 = 0.7071067690849304;

const float COS_TABLE_0 = 0.9807852506637573;
const float COS_TABLE_1 = 0.9238795042037964;
const float COS_TABLE_2 = 0.8314695954322815;
const float COS_TABLE_3 = 0.7071067690849304;

const float INVERSE_FACTORIAL_3 = 1.666666716337204e-01; // 1/3!
const float INVERSE_FACTORIAL_5 = 8.333333767950535e-03; // 1/5!
const float INVERSE_FACTORIAL_7 = 1.9841270113829523e-04; // 1/7!
const float INVERSE_FACTORIAL_9 = 2.75573188446287533e-06; // 1/9!

float sin_taylor_fp32(float a) {
  float r, s, t, x;

  if (a == 0.0) {
    return 0.0;
  }

  x = -a * a;
  s = a;
  r = a;

  r = r * x;
  t = r * INVERSE_FACTORIAL_3;
  s = s + t;

  r = r * x;
  t = r * INVERSE_FACTORIAL_5;
  s = s + t;

  r = r * x;
  t = r * INVERSE_FACTORIAL_7;
  s = s + t;

  r = r * x;
  t = r * INVERSE_FACTORIAL_9;
  s = s + t;

  return s;
}

void sincos_taylor_fp32(float a, out float sin_t, out float cos_t) {
  if (a == 0.0) {
    sin_t = 0.0;
    cos_t = 1.0;
  }
  sin_t = sin_taylor_fp32(a);
  cos_t = sqrt(1.0 - sin_t * sin_t);
}

float tan_taylor_fp32(float a) {
    float sin_a;
    float cos_a;

    if (a == 0.0) {
        return 0.0;
    }

    // 2pi range reduction
    float z = floor(a / TWO_PI);
    float r = a - TWO_PI * z;

    float t;
    float q = floor(r / PI_2 + 0.5);
    int j = int(q);

    if (j < -2 || j > 2) {
        return 1.0 / 0.0;
    }

    t = r - PI_2 * q;

    q = floor(t / PI_16 + 0.5);
    int k = int(q);
    int abs_k = int(abs(float(k)));

    if (abs_k > 4) {
        return 1.0 / 0.0;
    } else {
        t = t - PI_16 * q;
    }

    float u = 0.0;
    float v = 0.0;

    float sin_t, cos_t;
    float s, c;
    sincos_taylor_fp32(t, sin_t, cos_t);

    if (k == 0) {
        s = sin_t;
        c = cos_t;
    } else {
        if (abs(float(abs_k) - 1.0) < 0.5) {
            u = COS_TABLE_0;
            v = SIN_TABLE_0;
        } else if (abs(float(abs_k) - 2.0) < 0.5) {
            u = COS_TABLE_1;
            v = SIN_TABLE_1;
        } else if (abs(float(abs_k) - 3.0) < 0.5) {
            u = COS_TABLE_2;
            v = SIN_TABLE_2;
        } else if (abs(float(abs_k) - 4.0) < 0.5) {
            u = COS_TABLE_3;
            v = SIN_TABLE_3;
        }
        if (k > 0) {
            s = u * sin_t + v * cos_t;
            c = u * cos_t - v * sin_t;
        } else {
            s = u * sin_t - v * cos_t;
            c = u * cos_t + v * sin_t;
        }
    }

    if (j == 0) {
        sin_a = s;
        cos_a = c;
    } else if (j == 1) {
        sin_a = c;
        cos_a = -s;
    } else if (j == -1) {
        sin_a = -c;
        cos_a = s;
    } else {
        sin_a = -s;
        cos_a = -c;
    }
    return sin_a / cos_a;
}
#endif

float tan_fp32(float a) {
#ifdef LUMA_FP32_TAN_PRECISION_WORKAROUND
  return tan_taylor_fp32(a);
#else
  return tan(a);
#endif
}
`,wI=`#ifdef LUMA_FP32_TAN_PRECISION_WORKAROUND
const FP32_TWO_PI: f32 = 6.2831854820251465;
const FP32_PI_2: f32 = 1.5707963705062866;
const FP32_PI_16: f32 = 0.1963495463132858;

const FP32_SIN_TABLE_0: f32 = 0.19509032368659973;
const FP32_SIN_TABLE_1: f32 = 0.3826834261417389;
const FP32_SIN_TABLE_2: f32 = 0.5555702447891235;
const FP32_SIN_TABLE_3: f32 = 0.7071067690849304;

const FP32_COS_TABLE_0: f32 = 0.9807852506637573;
const FP32_COS_TABLE_1: f32 = 0.9238795042037964;
const FP32_COS_TABLE_2: f32 = 0.8314695954322815;
const FP32_COS_TABLE_3: f32 = 0.7071067690849304;

const FP32_INVERSE_FACTORIAL_3: f32 = 1.666666716337204e-01;
const FP32_INVERSE_FACTORIAL_5: f32 = 8.333333767950535e-03;
const FP32_INVERSE_FACTORIAL_7: f32 = 1.9841270113829523e-04;
const FP32_INVERSE_FACTORIAL_9: f32 = 2.75573188446287533e-06;
const FP32_OVERFLOW: f32 = 3.402823466e+38;

fn sin_taylor_fp32(a: f32) -> f32 {
  if (a == 0.0) {
    return 0.0;
  }

  let x = -a * a;
  var sum = a;
  var term = a;

  term = term * x;
  sum = sum + term * FP32_INVERSE_FACTORIAL_3;
  term = term * x;
  sum = sum + term * FP32_INVERSE_FACTORIAL_5;
  term = term * x;
  sum = sum + term * FP32_INVERSE_FACTORIAL_7;
  term = term * x;
  sum = sum + term * FP32_INVERSE_FACTORIAL_9;

  return sum;
}

fn tan_taylor_fp32(a: f32) -> f32 {
  if (a == 0.0) {
    return 0.0;
  }

  let z = floor(a / FP32_TWO_PI);
  let reduced = a - FP32_TWO_PI * z;

  var quadrantValue = floor(reduced / FP32_PI_2 + 0.5);
  let quadrant = i32(quadrantValue);
  if (quadrant < -2 || quadrant > 2) {
    return FP32_OVERFLOW;
  }

  var angle = reduced - FP32_PI_2 * quadrantValue;
  quadrantValue = floor(angle / FP32_PI_16 + 0.5);
  let tableIndex = i32(quadrantValue);
  let absoluteTableIndex = abs(tableIndex);
  if (absoluteTableIndex > 4) {
    return FP32_OVERFLOW;
  }

  angle = angle - FP32_PI_16 * quadrantValue;
  let sinAngle = sin_taylor_fp32(angle);
  let cosAngle = sqrt(1.0 - sinAngle * sinAngle);

  var tableCos = 0.0;
  var tableSin = 0.0;
  if (absoluteTableIndex == 1) {
    tableCos = FP32_COS_TABLE_0;
    tableSin = FP32_SIN_TABLE_0;
  } else if (absoluteTableIndex == 2) {
    tableCos = FP32_COS_TABLE_1;
    tableSin = FP32_SIN_TABLE_1;
  } else if (absoluteTableIndex == 3) {
    tableCos = FP32_COS_TABLE_2;
    tableSin = FP32_SIN_TABLE_2;
  } else if (absoluteTableIndex == 4) {
    tableCos = FP32_COS_TABLE_3;
    tableSin = FP32_SIN_TABLE_3;
  }

  var sinReduced = sinAngle;
  var cosReduced = cosAngle;
  if (tableIndex > 0) {
    sinReduced = tableCos * sinAngle + tableSin * cosAngle;
    cosReduced = tableCos * cosAngle - tableSin * sinAngle;
  } else if (tableIndex < 0) {
    sinReduced = tableCos * sinAngle - tableSin * cosAngle;
    cosReduced = tableCos * cosAngle + tableSin * sinAngle;
  }

  var sinValue = 0.0;
  var cosValue = 0.0;
  if (quadrant == 0) {
    sinValue = sinReduced;
    cosValue = cosReduced;
  } else if (quadrant == 1) {
    sinValue = cosReduced;
    cosValue = -sinReduced;
  } else if (quadrant == -1) {
    sinValue = -cosReduced;
    cosValue = sinReduced;
  } else {
    sinValue = -sinReduced;
    cosValue = -cosReduced;
  }

  return sinValue / cosValue;
}

fn tan_fp32(a: f32) -> f32 {
  return tan_taylor_fp32(a);
}
#else
fn tan_fp32(a: f32) -> f32 {
  return tan(a);
}
#endif
`,Mn={name:"fp32",source:wI,vs:vI}});var Ep,A0=b(()=>{Ep=`
layout(std140) uniform fp64arithmeticUniforms {
  uniform float ONE;
  uniform float SPLIT;
} fp64;

/*
About LUMA_FP64_CODE_ELIMINATION_WORKAROUND

The purpose of this workaround is to prevent shader compilers from
optimizing away necessary arithmetic operations by swapping their sequences
or transform the equation to some 'equivalent' form.

These helpers implement Dekker/Veltkamp-style error tracking. If the compiler
folds constants or reassociates the arithmetic, the high/low split can stop
tracking the rounding error correctly. That failure mode tends to look fine in
simple coordinate setup, but then breaks down inside iterative arithmetic such
as fp64 Mandelbrot loops.

The method is to multiply an artifical variable, ONE, which will be known to
the compiler to be 1 only at runtime. The whole expression is then represented
as a polynomial with respective to ONE. In the coefficients of all terms, only one a
and one b should appear

err = (a + b) * ONE^6 - a * ONE^5 - (a + b) * ONE^4 + a * ONE^3 - b - (a + b) * ONE^2 + a * ONE
*/

float prevent_fp64_optimization(float value) {
#if defined(LUMA_FP64_CODE_ELIMINATION_WORKAROUND)
  return value + fp64.ONE * 0.0;
#else
  return value;
#endif
}

// Divide float number to high and low floats to extend fraction bits
vec2 split(float a) {
  // Keep SPLIT as a runtime uniform so the compiler cannot fold the Dekker
  // split into a constant expression and reassociate the recovery steps.
  float split = prevent_fp64_optimization(fp64.SPLIT);
  float t = prevent_fp64_optimization(a * split);
  float temp = t - a;
  float a_hi = t - temp;
  float a_lo = a - a_hi;
  return vec2(a_hi, a_lo);
}

// Divide float number again when high float uses too many fraction bits
vec2 split2(vec2 a) {
  vec2 b = split(a.x);
  b.y += a.y;
  return b;
}

// Special sum operation when a > b
vec2 quickTwoSum(float a, float b) {
#if defined(LUMA_FP64_CODE_ELIMINATION_WORKAROUND)
  float sum = (a + b) * fp64.ONE;
  float err = b - (sum - a) * fp64.ONE;
#else
  float sum = a + b;
  float err = b - (sum - a);
#endif
  return vec2(sum, err);
}

// General sum operation
vec2 twoSum(float a, float b) {
  float s = (a + b);
#if defined(LUMA_FP64_CODE_ELIMINATION_WORKAROUND)
  float v = (s * fp64.ONE - a) * fp64.ONE;
  float err = (a - (s - v) * fp64.ONE) * fp64.ONE * fp64.ONE * fp64.ONE + (b - v);
#else
  float v = s - a;
  float err = (a - (s - v)) + (b - v);
#endif
  return vec2(s, err);
}

vec2 twoSub(float a, float b) {
  float s = (a - b);
#if defined(LUMA_FP64_CODE_ELIMINATION_WORKAROUND)
  float v = (s * fp64.ONE - a) * fp64.ONE;
  float err = (a - (s - v) * fp64.ONE) * fp64.ONE * fp64.ONE * fp64.ONE - (b + v);
#else
  float v = s - a;
  float err = (a - (s - v)) - (b + v);
#endif
  return vec2(s, err);
}

vec2 twoSqr(float a) {
  float prod = a * a;
  vec2 a_fp64 = split(a);
#if defined(LUMA_FP64_CODE_ELIMINATION_WORKAROUND)
  float err = ((a_fp64.x * a_fp64.x - prod) * fp64.ONE + 2.0 * a_fp64.x *
    a_fp64.y * fp64.ONE * fp64.ONE) + a_fp64.y * a_fp64.y * fp64.ONE * fp64.ONE * fp64.ONE;
#else
  float err = ((a_fp64.x * a_fp64.x - prod) + 2.0 * a_fp64.x * a_fp64.y) + a_fp64.y * a_fp64.y;
#endif
  return vec2(prod, err);
}

vec2 twoProd(float a, float b) {
  float prod = a * b;
  vec2 a_fp64 = split(a);
  vec2 b_fp64 = split(b);
  // twoProd is especially sensitive because mul_fp64 and div_fp64 both depend
  // on the split terms and cross terms staying in the original evaluation
  // order. If the compiler folds or reassociates them, the low part tends to
  // collapse to zero or NaN on some drivers.
  float highProduct = prevent_fp64_optimization(a_fp64.x * b_fp64.x);
  float crossProduct1 = prevent_fp64_optimization(a_fp64.x * b_fp64.y);
  float crossProduct2 = prevent_fp64_optimization(a_fp64.y * b_fp64.x);
  float lowProduct = prevent_fp64_optimization(a_fp64.y * b_fp64.y);
#if defined(LUMA_FP64_CODE_ELIMINATION_WORKAROUND)
  float err1 = (highProduct - prod) * fp64.ONE;
  float err2 = crossProduct1 * fp64.ONE * fp64.ONE;
  float err3 = crossProduct2 * fp64.ONE * fp64.ONE * fp64.ONE;
  float err4 = lowProduct * fp64.ONE * fp64.ONE * fp64.ONE * fp64.ONE;
#else
  float err1 = highProduct - prod;
  float err2 = crossProduct1;
  float err3 = crossProduct2;
  float err4 = lowProduct;
#endif
  float err = ((err1 + err2) + err3) + err4;
  return vec2(prod, err);
}

vec2 sum_fp64(vec2 a, vec2 b) {
  vec2 s, t;
  s = twoSum(a.x, b.x);
  t = twoSum(a.y, b.y);
  s.y += t.x;
  s = quickTwoSum(s.x, s.y);
  s.y += t.y;
  s = quickTwoSum(s.x, s.y);
  return s;
}

vec2 sub_fp64(vec2 a, vec2 b) {
  vec2 s, t;
  s = twoSub(a.x, b.x);
  t = twoSub(a.y, b.y);
  s.y += t.x;
  s = quickTwoSum(s.x, s.y);
  s.y += t.y;
  s = quickTwoSum(s.x, s.y);
  return s;
}

vec2 mul_fp64(vec2 a, vec2 b) {
  vec2 prod = twoProd(a.x, b.x);
  // y component is for the error
  prod.y += a.x * b.y;
#if defined(LUMA_FP64_HIGH_BITS_OVERFLOW_WORKAROUND)
  prod = split2(prod);
#endif
  prod = quickTwoSum(prod.x, prod.y);
  prod.y += a.y * b.x;
#if defined(LUMA_FP64_HIGH_BITS_OVERFLOW_WORKAROUND)
  prod = split2(prod);
#endif
  prod = quickTwoSum(prod.x, prod.y);
  return prod;
}

vec2 div_fp64(vec2 a, vec2 b) {
  float xn = 1.0 / b.x;
#if defined(LUMA_FP64_HIGH_BITS_OVERFLOW_WORKAROUND)
  vec2 yn = mul_fp64(a, vec2(xn, 0));
#else
  vec2 yn = a * xn;
#endif
  float diff = (sub_fp64(a, mul_fp64(b, yn))).x;
  vec2 prod = twoProd(xn, diff);
  return sum_fp64(yn, prod);
}

vec2 sqrt_fp64(vec2 a) {
  if (a.x == 0.0 && a.y == 0.0) return vec2(0.0, 0.0);
  if (a.x < 0.0) return vec2(0.0 / 0.0, 0.0 / 0.0);

  float x = 1.0 / sqrt(a.x);
  float yn = a.x * x;
#if defined(LUMA_FP64_CODE_ELIMINATION_WORKAROUND)
  vec2 yn_sqr = twoSqr(yn) * fp64.ONE;
#else
  vec2 yn_sqr = twoSqr(yn);
#endif
  float diff = sub_fp64(a, yn_sqr).x;
  vec2 prod = twoProd(x * 0.5, diff);
#if defined(LUMA_FP64_HIGH_BITS_OVERFLOW_WORKAROUND)
  return sum_fp64(split(yn), prod);
#else
  return sum_fp64(vec2(yn, 0.0), prod);
#endif
}
`});var C0,M0=b(()=>{C0=`struct Fp64F32Bits {
  sign: u32,
  baseExponent: i32,
  significand: u32,
  isZero: bool,
  isInf: bool,
  isNan: bool,
};

// Decode an f32 as (-1)^sign * significand * 2^baseExponent.
fn fp64_decode_f32_bits(bits: u32) -> Fp64F32Bits {
  let sign = bits >> 31u;
  let exponentBits = (bits >> 23u) & 0xffu;
  let fraction = bits & 0x7fffffu;

  if (exponentBits == 0xffu) {
    return Fp64F32Bits(sign, 0, 0u, false, fraction == 0u, fraction != 0u);
  }
  if (exponentBits == 0u) {
    return Fp64F32Bits(sign, -149, fraction, fraction == 0u, false, false);
  }
  return Fp64F32Bits(sign, i32(exponentBits) - 150, 0x800000u | fraction, false, false, false);
}

fn fp64_f32_magnitude_compare(aBits: u32, bBits: u32) -> i32 {
  let aMagnitude = aBits & 0x7fffffffu;
  let bMagnitude = bBits & 0x7fffffffu;
  if (aMagnitude == bMagnitude) {
    return 0;
  }
  return select(-1, 1, aMagnitude > bMagnitude);
}

fn fp64_make_residual_f32_bits(
  exactSign: u32,
  exactMagnitude: vec2u,
  exactBaseExponent: i32,
  highBits: u32
) -> u32 {
  if (fp64_u64_is_zero(exactMagnitude)) {
    return 0u;
  }

  let high = fp64_decode_f32_bits(highBits);
  if (high.isInf || high.isNan) {
    return exactSign << 31u;
  }
  if (high.isZero) {
    return fp64_make_f32_bits_from_u64(exactSign, exactMagnitude, exactBaseExponent);
  }

  let commonBaseExponent = min(exactBaseExponent, high.baseExponent);
  let exactShift = exactBaseExponent - commonBaseExponent;
  let highShift = high.baseExponent - commonBaseExponent;

  // A normal two-sum/two-product residual never needs a shift this large.
  // This guard gives deterministic underflow behavior outside that contract.
  if (exactShift >= 64 || highShift >= 64) {
    return exactSign << 31u;
  }

  let exactAligned = fp64_u64_shift_left(exactMagnitude, u32(exactShift));
  let highAligned = fp64_u64_shift_left(vec2u(0u, high.significand), u32(highShift));
  let comparison = fp64_u64_compare(exactAligned, highAligned);
  if (comparison == 0) {
    return 0u;
  }

  var residualSign = exactSign;
  var residualMagnitude: vec2u;
  if (comparison > 0) {
    residualMagnitude = fp64_u64_sub(exactAligned, highAligned);
  } else {
    residualSign = exactSign ^ 1u;
    residualMagnitude = fp64_u64_sub(highAligned, exactAligned);
  }
  return fp64_make_f32_bits_from_u64(
    residualSign,
    residualMagnitude,
    commonBaseExponent
  );
}

fn fp64_split_accumulator_bits(
  sign: u32,
  magnitude: vec2u,
  baseExponent: i32
) -> vec2u {
  let highBits = fp64_make_f32_bits_from_u64(sign, magnitude, baseExponent);
  let lowBits = fp64_make_residual_f32_bits(sign, magnitude, baseExponent, highBits);
  return vec2u(highBits, lowBits);
}

fn fp64_two_sum_integer_bits(aBits: u32, bBits: u32) -> vec2u {
  let a = fp64_decode_f32_bits(aBits);
  let b = fp64_decode_f32_bits(bBits);

  if (a.isNan || b.isNan) {
    return vec2u(0x7fc00000u, 0u);
  }
  if (a.isInf || b.isInf) {
    if (a.isInf && b.isInf && a.sign != b.sign) {
      return vec2u(0x7fc00000u, 0u);
    }
    return select(vec2u(bBits, 0u), vec2u(aBits, 0u), a.isInf);
  }
  if (a.isZero && b.isZero) {
    return vec2u((a.sign & b.sign) << 31u, 0u);
  }
  if (a.isZero) {
    return vec2u(bBits, 0u);
  }
  if (b.isZero) {
    return vec2u(aBits, 0u);
  }

  let exponentDifference = select(
    b.baseExponent - a.baseExponent,
    a.baseExponent - b.baseExponent,
    a.baseExponent >= b.baseExponent
  );

  // Beyond half an ulp, rounding cannot change the larger operand. Returning
  // the smaller operand intact also avoids an unbounded integer alignment.
  // At a power-of-two boundary the spacing below the larger operand is half
  // the spacing above it, so an opposite-sign gap-25 operand can still change
  // the rounded high limb. Gap 26 is the first universally safe early-out.
  if (exponentDifference > 25) {
    if (fp64_f32_magnitude_compare(aBits, bBits) >= 0) {
      return vec2u(aBits, bBits);
    }
    return vec2u(bBits, aBits);
  }

  let commonBaseExponent = min(a.baseExponent, b.baseExponent);
  let aMagnitude = fp64_u64_shift_left(
    vec2u(0u, a.significand),
    u32(a.baseExponent - commonBaseExponent)
  );
  let bMagnitude = fp64_u64_shift_left(
    vec2u(0u, b.significand),
    u32(b.baseExponent - commonBaseExponent)
  );

  var resultSign = a.sign;
  var resultMagnitude: vec2u;
  if (a.sign == b.sign) {
    resultMagnitude = fp64_u64_add(aMagnitude, bMagnitude);
  } else {
    let comparison = fp64_u64_compare(aMagnitude, bMagnitude);
    if (comparison == 0) {
      return vec2u(0u, 0u);
    }
    if (comparison > 0) {
      resultMagnitude = fp64_u64_sub(aMagnitude, bMagnitude);
    } else {
      resultSign = b.sign;
      resultMagnitude = fp64_u64_sub(bMagnitude, aMagnitude);
    }
  }

  return fp64_split_accumulator_bits(resultSign, resultMagnitude, commonBaseExponent);
}

fn fp64_two_sum_integer(a: f32, b: f32) -> vec2f {
  let resultBits = fp64_two_sum_integer_bits(bitcast<u32>(a), bitcast<u32>(b));
  return vec2f(bitcast<f32>(resultBits.x), bitcast<f32>(resultBits.y));
}

fn fp64_multiply_significands(a: u32, b: u32) -> vec2u {
  let aLow = a & 0xffffu;
  let aHigh = a >> 16u;
  let bLow = b & 0xffffu;
  let bHigh = b >> 16u;
  let lowProduct = aLow * bLow;
  let crossProduct = aLow * bHigh + aHigh * bLow;
  let highProduct = aHigh * bHigh;

  var result = vec2u(0u, lowProduct);
  result = fp64_u64_add(
    result,
    fp64_u64_shift_left(vec2u(0u, crossProduct), 16u)
  );
  result = fp64_u64_add(result, vec2u(highProduct, 0u));
  return result;
}

fn fp64_two_prod_integer_bits(aBits: u32, bBits: u32) -> vec2u {
  let a = fp64_decode_f32_bits(aBits);
  let b = fp64_decode_f32_bits(bBits);
  let resultSign = a.sign ^ b.sign;

  if (a.isNan || b.isNan || ((a.isZero || b.isZero) && (a.isInf || b.isInf))) {
    return vec2u(0x7fc00000u, 0u);
  }
  if (a.isInf || b.isInf) {
    return vec2u((resultSign << 31u) | 0x7f800000u, resultSign << 31u);
  }
  if (a.isZero || b.isZero) {
    return vec2u(resultSign << 31u, resultSign << 31u);
  }

  let magnitude = fp64_multiply_significands(a.significand, b.significand);
  return fp64_split_accumulator_bits(
    resultSign,
    magnitude,
    a.baseExponent + b.baseExponent
  );
}

fn fp64_two_prod_integer(a: f32, b: f32) -> vec2f {
  let resultBits = fp64_two_prod_integer_bits(bitcast<u32>(a), bitcast<u32>(b));
  return vec2f(bitcast<f32>(resultBits.x), bitcast<f32>(resultBits.y));
}

fn fp64_round_add_integer(a: f32, b: f32) -> f32 {
  return fp64_two_sum_integer(a, b).x;
}

fn fp64_round_mul_integer(a: f32, b: f32) -> f32 {
  return fp64_two_prod_integer(a, b).x;
}

#ifndef LUMA_FP64_PREDICATE_ONLY
fn fp64_f32_finite_exponent(value: Fp64F32Bits) -> i32 {
  let mostSignificantBit = 31u - countLeadingZeros(value.significand);
  return value.baseExponent + i32(mostSignificantBit);
}

fn fp64_scale_f32_integer(value: f32, exponent: i32) -> f32 {
  let decoded = fp64_decode_f32_bits(bitcast<u32>(value));
  if (decoded.isZero || decoded.isInf || decoded.isNan) {
    return value;
  }
  let resultBits = fp64_make_f32_bits_from_u64(
    decoded.sign,
    vec2u(0u, decoded.significand),
    decoded.baseExponent + exponent
  );
  return bitcast<f32>(resultBits);
}

// Divide normalized significands so the hardware operation cannot overflow,
// underflow, or flush a subnormal result. Reapply the exponent with integer
// packing, which also produces subnormal correction limbs without relying on
// floating-point arithmetic to preserve them.
fn fp64_divide_f32_integer(aValue: f32, bValue: f32) -> f32 {
  let a = fp64_decode_f32_bits(bitcast<u32>(aValue));
  let b = fp64_decode_f32_bits(bitcast<u32>(bValue));
  if (a.isZero || b.isZero || a.isInf || b.isInf || a.isNan || b.isNan) {
    return aValue / bValue;
  }

  let aMostSignificantBit = 31u - countLeadingZeros(a.significand);
  let bMostSignificantBit = 31u - countLeadingZeros(b.significand);
  let normalizedABits = fp64_make_f32_bits_from_u64(
    a.sign,
    vec2u(0u, a.significand),
    -i32(aMostSignificantBit)
  );
  let normalizedBBits = fp64_make_f32_bits_from_u64(
    b.sign,
    vec2u(0u, b.significand),
    -i32(bMostSignificantBit)
  );
  let normalizedQuotient = bitcast<f32>(normalizedABits) / bitcast<f32>(normalizedBBits);
  let quotient = fp64_decode_f32_bits(bitcast<u32>(normalizedQuotient));
  let exponentShift =
    a.baseExponent + i32(aMostSignificantBit) -
    b.baseExponent - i32(bMostSignificantBit);
  let quotientBits = fp64_make_f32_bits_from_u64(
    quotient.sign,
    vec2u(0u, quotient.significand),
    quotient.baseExponent + exponentShift
  );
  return bitcast<f32>(quotientBits);
}
#endif

#ifndef LUMA_FP64_PREDICATE_ONLY
fn split(a: f32) -> vec2f {
  let aBits = bitcast<u32>(a);
  let decoded = fp64_decode_f32_bits(aBits);
  if (decoded.isZero || decoded.isInf || decoded.isNan) {
    return vec2f(a, 0.0);
  }

  var roundedHigh = decoded.significand >> 12u;
  let remainder = decoded.significand & 0xfffu;
  if (remainder > 0x800u || (remainder == 0x800u && (roundedHigh & 1u) == 1u)) {
    roundedHigh = roundedHigh + 1u;
  }
  var highMagnitude = vec2u(0u, roundedHigh << 12u);
  var highBits = fp64_make_f32_bits_from_u64(
    decoded.sign,
    highMagnitude,
    decoded.baseExponent
  );
  // Rounding the high limb of a maximum-exponent value can overflow even
  // though the original value is finite. Truncate only in that boundary case
  // so split remains an exact finite decomposition.
  if (fp64_decode_f32_bits(highBits).isInf) {
    roundedHigh = decoded.significand >> 12u;
    highMagnitude = vec2u(0u, roundedHigh << 12u);
    highBits = fp64_make_f32_bits_from_u64(
      decoded.sign,
      highMagnitude,
      decoded.baseExponent
    );
  }
  let lowBits = fp64_make_residual_f32_bits(
    decoded.sign,
    vec2u(0u, decoded.significand),
    decoded.baseExponent,
    highBits
  );
  return vec2f(bitcast<f32>(highBits), bitcast<f32>(lowBits));
}

fn split2(a: vec2f) -> vec2f {
  var result = split(a.x);
  result.y = fp64_round_add_integer(result.y, a.y);
  return result;
}
#endif

#ifndef LUMA_FP64_PREDICATE_ONLY
fn quickTwoSum(a: f32, b: f32) -> vec2f {
  return fp64_two_sum_integer(a, b);
}
#endif

fn twoSum(a: f32, b: f32) -> vec2f {
  return fp64_two_sum_integer(a, b);
}

fn twoSub(a: f32, b: f32) -> vec2f {
  let bBits = bitcast<u32>(b) ^ 0x80000000u;
  let resultBits = fp64_two_sum_integer_bits(bitcast<u32>(a), bBits);
  return vec2f(bitcast<f32>(resultBits.x), bitcast<f32>(resultBits.y));
}

#ifndef LUMA_FP64_PREDICATE_ONLY
fn twoSqr(a: f32) -> vec2f {
  return fp64_two_prod_integer(a, a);
}

fn twoProd(a: f32, b: f32) -> vec2f {
  return fp64_two_prod_integer(a, b);
}
#endif

fn sum_fp64(a: vec2f, b: vec2f) -> vec2f {
  var sum = fp64_two_sum_integer(a.x, b.x);
  let lowSum = fp64_two_sum_integer(a.y, b.y);
  sum.y = fp64_round_add_integer(sum.y, lowSum.x);
  sum = fp64_two_sum_integer(sum.x, sum.y);
  sum.y = fp64_round_add_integer(sum.y, lowSum.y);
  return fp64_two_sum_integer(sum.x, sum.y);
}

fn sub_fp64(a: vec2f, b: vec2f) -> vec2f {
  let negatedB = vec2f(
    bitcast<f32>(bitcast<u32>(b.x) ^ 0x80000000u),
    bitcast<f32>(bitcast<u32>(b.y) ^ 0x80000000u)
  );
  return sum_fp64(a, negatedB);
}

fn mul_fp64(a: vec2f, b: vec2f) -> vec2f {
  var product = fp64_two_prod_integer(a.x, b.x);
  let crossProduct1 = fp64_round_mul_integer(a.x, b.y);
  product.y = fp64_round_add_integer(product.y, crossProduct1);
  product = fp64_two_sum_integer(product.x, product.y);
  let crossProduct2 = fp64_round_mul_integer(a.y, b.x);
  product.y = fp64_round_add_integer(product.y, crossProduct2);
  return fp64_two_sum_integer(product.x, product.y);
}

#ifndef LUMA_FP64_PREDICATE_ONLY
fn fp64_scale_fp64_integer(value: vec2f, exponent: i32) -> vec2f {
  let high = fp64_scale_f32_integer(value.x, exponent);
  let low = fp64_scale_f32_integer(value.y, exponent);
  return sum_fp64(vec2f(high, 0.0), vec2f(low, 0.0));
}

fn fp64_div_fp64_normalized(a: vec2f, b: vec2f) -> vec2f {
  let quotientHigh = fp64_divide_f32_integer(a.x, b.x);
  var quotient = vec2f(quotientHigh, 0.0);

  let remainder = sub_fp64(a, mul_fp64(b, quotient));
  let quotientLow = fp64_divide_f32_integer(remainder.x, b.x);
  quotient = sum_fp64(quotient, vec2f(quotientLow, 0.0));

  let secondRemainder = sub_fp64(a, mul_fp64(b, quotient));
  let correction = fp64_divide_f32_integer(secondRemainder.x, b.x);
  return sum_fp64(quotient, vec2f(correction, 0.0));
}

fn div_fp64(a: vec2f, b: vec2f) -> vec2f {
  let decodedA = fp64_decode_f32_bits(bitcast<u32>(a.x));
  let decodedB = fp64_decode_f32_bits(bitcast<u32>(b.x));
  if (
    decodedA.isZero || decodedB.isZero ||
    decodedA.isInf || decodedB.isInf ||
    decodedA.isNan || decodedB.isNan
  ) {
    return fp64_div_fp64_normalized(a, b);
  }

  let exponentA = fp64_f32_finite_exponent(decodedA);
  let exponentB = fp64_f32_finite_exponent(decodedB);
  // Correct the quotient near unity so b * q and the remainder stay clear of
  // both f32 underflow and overflow. The exponent difference is applied once.
  let normalizedA = fp64_scale_fp64_integer(a, -exponentA);
  let normalizedB = fp64_scale_fp64_integer(b, -exponentB);
  let normalizedQuotient = fp64_div_fp64_normalized(normalizedA, normalizedB);
  return fp64_scale_fp64_integer(normalizedQuotient, exponentA - exponentB);
}

fn fp64_sqrt_fp64_normalized(a: vec2f) -> vec2f {
  let estimate = sqrt(a.x);
  let difference = sub_fp64(a, fp64_two_prod_integer(estimate, estimate)).x;
  let denominator = fp64_round_add_integer(estimate, estimate);
  let correction = fp64_divide_f32_integer(difference, denominator);
  return sum_fp64(vec2f(estimate, 0.0), vec2f(correction, 0.0));
}

fn sqrt_fp64(a: vec2f) -> vec2f {
  let decoded = fp64_decode_f32_bits(bitcast<u32>(a.x));
  let decodedLow = fp64_decode_f32_bits(bitcast<u32>(a.y));
  if (decoded.isZero && decodedLow.isZero) {
    return vec2f(0.0, 0.0);
  }
  if (decoded.sign == 1u) {
    let nanValue = fp64_nan(a.x);
    return vec2f(nanValue, nanValue);
  }

  if (decoded.isInf || decoded.isNan) {
    return fp64_sqrt_fp64_normalized(a);
  }
  let exponent = fp64_f32_finite_exponent(decoded);
  // An even scale lets the final square-root rescale use an integer exponent.
  let evenExponent = exponent - (exponent & 1);
  let normalizedA = fp64_scale_fp64_integer(a, -evenExponent);
  let normalizedRoot = fp64_sqrt_fp64_normalized(normalizedA);
  return fp64_scale_fp64_integer(normalizedRoot, evenExponent / 2);
}
#endif
`});var I0,R0=b(()=>{M0();I0=`struct Fp64ArithmeticUniforms {
  ONE: f32,
  SPLIT: f32,
};

@group(0) @binding(auto) var<uniform> fp64arithmetic : Fp64ArithmeticUniforms;

#ifndef LUMA_FP64_F32_INPUT_ONLY
struct Fp64Bits {
  sign: u32,
  exponent: i32,
  significand: vec2u,
  isZero: bool,
  isInf: bool,
  isNan: bool,
};
#endif

#ifndef LUMA_FP64_PREDICATE_ONLY
fn fp64_nan(seed: f32) -> f32 {
  let nanBits = 0x7fc00000u | select(0u, 1u, seed < 0.0);
  return bitcast<f32>(nanBits);
}
#endif

fn fp64_u64_is_zero(value: vec2u) -> bool {
  return value.x == 0u && value.y == 0u;
}

fn fp64_u64_compare(a: vec2u, b: vec2u) -> i32 {
  if (a.x != b.x) {
    return select(-1, 1, a.x > b.x);
  }
  if (a.y != b.y) {
    return select(-1, 1, a.y > b.y);
  }
  return 0;
}

fn fp64_u64_add(a: vec2u, b: vec2u) -> vec2u {
  let low = a.y + b.y;
  let carry = select(0u, 1u, low < a.y);
  return vec2u(a.x + b.x + carry, low);
}

fn fp64_u64_sub(a: vec2u, b: vec2u) -> vec2u {
  let borrow = select(0u, 1u, a.y < b.y);
  return vec2u(a.x - b.x - borrow, a.y - b.y);
}

fn fp64_u64_shift_left(value: vec2u, shift: u32) -> vec2u {
  if (shift == 0u) {
    return value;
  }
  if (shift < 32u) {
    return vec2u((value.x << shift) | (value.y >> (32u - shift)), value.y << shift);
  }
  if (shift == 32u) {
    return vec2u(value.y, 0u);
  }
  if (shift < 64u) {
    return vec2u(value.y << (shift - 32u), 0u);
  }
  return vec2u(0u);
}

fn fp64_u64_shift_right(value: vec2u, shift: u32) -> vec2u {
  if (shift == 0u) {
    return value;
  }
  if (shift < 32u) {
    return vec2u(value.x >> shift, (value.y >> shift) | (value.x << (32u - shift)));
  }
  if (shift == 32u) {
    return vec2u(0u, value.x);
  }
  if (shift < 64u) {
    return vec2u(0u, value.x >> (shift - 32u));
  }
  return vec2u(0u);
}

fn fp64_u64_get_bit(value: vec2u, bitIndex: u32) -> bool {
  if (bitIndex >= 64u) {
    return false;
  }
  if (bitIndex >= 32u) {
    return ((value.x >> (bitIndex - 32u)) & 1u) != 0u;
  }
  return ((value.y >> bitIndex) & 1u) != 0u;
}

fn fp64_u64_has_bits_below(value: vec2u, bitCount: u32) -> bool {
  if (bitCount == 0u) {
    return false;
  }
  if (bitCount >= 64u) {
    return !fp64_u64_is_zero(value);
  }
  if (bitCount > 32u) {
    let highBitCount = bitCount - 32u;
    let highMask = (1u << highBitCount) - 1u;
    return value.y != 0u || (value.x & highMask) != 0u;
  }
  if (bitCount == 32u) {
    return value.y != 0u;
  }
  let lowMask = (1u << bitCount) - 1u;
  return (value.y & lowMask) != 0u;
}

#ifndef LUMA_FP64_F32_INPUT_ONLY
fn fp64_u64_shift_right_sticky(value: vec2u, shift: u32) -> vec2u {
  var shifted = fp64_u64_shift_right(value, shift);
  if (fp64_u64_has_bits_below(value, shift)) {
    shifted.y = shifted.y | 1u;
  }
  return shifted;
}
#endif

fn fp64_u64_count_leading_zeros(value: vec2u) -> u32 {
  if (value.x != 0u) {
    return countLeadingZeros(value.x);
  }
  return 32u + countLeadingZeros(value.y);
}

fn fp64_round_shift_right_to_u32(value: vec2u, shift: u32) -> u32 {
  if (shift == 0u) {
    return value.y;
  }

  let truncated = fp64_u64_shift_right(value, shift);
  var rounded = truncated.y;
  let guard = fp64_u64_get_bit(value, shift - 1u);
  let hasTrailingBits = fp64_u64_has_bits_below(value, shift - 1u);
  if (guard && (hasTrailingBits || (rounded & 1u) == 1u)) {
    rounded = rounded + 1u;
  }
  return rounded;
}

#ifndef LUMA_FP64_F32_INPUT_ONLY
fn fp64_round_shift_right(value: vec2u, shift: u32) -> vec2u {
  if (shift == 0u) {
    return value;
  }

  var rounded = fp64_u64_shift_right(value, shift);
  let guard = fp64_u64_get_bit(value, shift - 1u);
  let hasTrailingBits = fp64_u64_has_bits_below(value, shift - 1u);
  if (guard && (hasTrailingBits || (rounded.y & 1u) == 1u)) {
    rounded = fp64_u64_add(rounded, vec2u(0u, 1u));
  }
  return rounded;
}
#endif

fn fp64_make_f32_bits_from_u64(sign: u32, significand: vec2u, baseExponent: i32) -> u32 {
  if (fp64_u64_is_zero(significand)) {
    return sign << 31u;
  }

  let leadingZeros = fp64_u64_count_leading_zeros(significand);
  let mostSignificantBit = 63u - leadingZeros;
  var exponent = baseExponent + i32(mostSignificantBit);

  if (exponent > 127) {
    return (sign << 31u) | 0x7f800000u;
  }

  if (exponent >= -126) {
    let shift = i32(mostSignificantBit) - 23;
    var significand24: u32;
    if (shift > 0) {
      significand24 = fp64_round_shift_right_to_u32(significand, u32(shift));
    } else {
      significand24 = fp64_u64_shift_left(significand, u32(-shift)).y;
    }

    if (significand24 >= 0x1000000u) {
      significand24 = significand24 >> 1u;
      exponent = exponent + 1;
      if (exponent > 127) {
        return (sign << 31u) | 0x7f800000u;
      }
    }

    return (sign << 31u) | (u32(exponent + 127) << 23u) | (significand24 & 0x7fffffu);
  }

  let scaleExponent = baseExponent + 149;
  var mantissa: u32;
  if (scaleExponent >= 0) {
    mantissa = fp64_u64_shift_left(significand, u32(scaleExponent)).y;
  } else {
    mantissa = fp64_round_shift_right_to_u32(significand, u32(-scaleExponent));
  }

  if (mantissa >= 0x800000u) {
    return (sign << 31u) | 0x00800000u;
  }
  return (sign << 31u) | mantissa;
}

#ifndef LUMA_FP64_F32_INPUT_ONLY
fn fp64_decode_bits(bits: vec2u) -> Fp64Bits {
  let sign = bits.x >> 31u;
  let exponentBits = (bits.x >> 20u) & 0x7ffu;
  let fractionHigh = bits.x & 0xfffffu;
  let fractionLow = bits.y;
  let fraction = vec2u(fractionHigh, fractionLow);

  if (exponentBits == 0x7ffu) {
    let isInf = fp64_u64_is_zero(fraction);
    return Fp64Bits(sign, 0, vec2u(0u), false, isInf, !isInf);
  }

  if (exponentBits == 0u) {
    let isZero = fp64_u64_is_zero(fraction);
    return Fp64Bits(sign, -1022, fraction, isZero, false, false);
  }

  return Fp64Bits(sign, i32(exponentBits) - 1023, vec2u((1u << 20u) | fractionHigh, fractionLow), false, false, false);
}

fn fp64_finite_magnitude_compare(a: Fp64Bits, b: Fp64Bits) -> i32 {
  if (a.exponent != b.exponent) {
    return select(-1, 1, a.exponent > b.exponent);
  }
  return fp64_u64_compare(a.significand, b.significand);
}
#endif

#ifndef LUMA_FP64_F32_INPUT_ONLY
struct Fp64RawF32Bits {
  sign: u32,
  baseExponent: i32,
  significand: u32,
  isZero: bool,
  isInf: bool,
  isNan: bool,
};

// Decode an f32 as (-1)^sign * significand * 2^baseExponent. This shared
// integer representation lets normalization remain independent of the
// selected double-single arithmetic implementation.
fn fp64_decode_raw_f32_bits(bits: u32) -> Fp64RawF32Bits {
  let sign = bits >> 31u;
  let exponentBits = (bits >> 23u) & 0xffu;
  let fraction = bits & 0x7fffffu;

  if (exponentBits == 0xffu) {
    return Fp64RawF32Bits(sign, 0, 0u, false, fraction == 0u, fraction != 0u);
  }
  if (exponentBits == 0u) {
    return Fp64RawF32Bits(sign, -149, fraction, fraction == 0u, false, false);
  }
  return Fp64RawF32Bits(
    sign,
    i32(exponentBits) - 150,
    0x800000u | fraction,
    false,
    false,
    false
  );
}

fn fp64_raw_f32_magnitude_compare(aBits: u32, bBits: u32) -> i32 {
  let aMagnitude = aBits & 0x7fffffffu;
  let bMagnitude = bBits & 0x7fffffffu;
  if (aMagnitude == bMagnitude) {
    return 0;
  }
  return select(-1, 1, aMagnitude > bMagnitude);
}

fn fp64_make_raw_residual_f32_bits(
  exactSign: u32,
  exactMagnitude: vec2u,
  exactBaseExponent: i32,
  highBits: u32
) -> u32 {
  if (fp64_u64_is_zero(exactMagnitude)) {
    return 0u;
  }

  let high = fp64_decode_raw_f32_bits(highBits);
  if (high.isInf || high.isNan) {
    return 0u;
  }
  if (high.isZero) {
    return fp64_make_f32_bits_from_u64(exactSign, exactMagnitude, exactBaseExponent);
  }

  let commonBaseExponent = min(exactBaseExponent, high.baseExponent);
  let exactShift = exactBaseExponent - commonBaseExponent;
  let highShift = high.baseExponent - commonBaseExponent;
  if (exactShift >= 64 || highShift >= 64) {
    return 0u;
  }

  let exactAligned = fp64_u64_shift_left(exactMagnitude, u32(exactShift));
  let highAligned = fp64_u64_shift_left(vec2u(0u, high.significand), u32(highShift));
  let comparison = fp64_u64_compare(exactAligned, highAligned);
  if (comparison == 0) {
    return 0u;
  }

  var residualSign = exactSign;
  var residualMagnitude: vec2u;
  if (comparison > 0) {
    residualMagnitude = fp64_u64_sub(exactAligned, highAligned);
  } else {
    residualSign = exactSign ^ 1u;
    residualMagnitude = fp64_u64_sub(highAligned, exactAligned);
  }
  return fp64_make_f32_bits_from_u64(
    residualSign,
    residualMagnitude,
    commonBaseExponent
  );
}

fn fp64_split_raw_accumulator_bits(
  sign: u32,
  magnitude: vec2u,
  baseExponent: i32
) -> vec2u {
  if (fp64_u64_is_zero(magnitude)) {
    return vec2u(0u);
  }
  let highBits = fp64_make_f32_bits_from_u64(sign, magnitude, baseExponent);
  let rawLowBits = fp64_make_raw_residual_f32_bits(sign, magnitude, baseExponent, highBits);
  let lowBits = select(rawLowBits, 0u, (rawLowBits & 0x7fffffffu) == 0u);
  if ((highBits & 0x7fffffffu) == 0u && (lowBits & 0x7fffffffu) == 0u) {
    return vec2u(0u);
  }
  return vec2u(highBits, lowBits);
}
#endif

#ifndef LUMA_FP64_F32_INPUT_ONLY
// Round an arithmetic accumulator to binary64 before splitting it. The
// aligned add/subtract paths retain three guard bits plus a sticky bit, which
// is sufficient for round-to-nearest-even at the binary64 boundary.
fn fp64_split_binary64_accumulator_bits(
  sign: u32,
  magnitude: vec2u,
  baseExponent: i32
) -> vec2u {
  if (fp64_u64_is_zero(magnitude)) {
    return vec2u(0u);
  }

  let mostSignificantBit = 63u - fp64_u64_count_leading_zeros(magnitude);
  let exponent = baseExponent + i32(mostSignificantBit);
  if (exponent > 1023) {
    return vec2u((sign << 31u) | 0x7f800000u, 0u);
  }

  var roundedMagnitude = magnitude;
  var roundedBaseExponent = baseExponent;
  if (exponent >= -1022) {
    if (mostSignificantBit > 52u) {
      let shift = mostSignificantBit - 52u;
      roundedMagnitude = fp64_round_shift_right(magnitude, shift);
      roundedBaseExponent = baseExponent + i32(shift);
    }
  } else {
    let shift = -1074 - baseExponent;
    if (shift > 0) {
      roundedMagnitude = fp64_round_shift_right(magnitude, u32(shift));
      roundedBaseExponent = -1074;
    }
  }

  if (fp64_u64_is_zero(roundedMagnitude)) {
    return vec2u(0u);
  }
  return fp64_split_raw_accumulator_bits(sign, roundedMagnitude, roundedBaseExponent);
}
#endif

#ifndef LUMA_FP64_PREDICATE_ONLY
fn fp64_add_raw_f32_bits(aBits: u32, bBits: u32) -> vec2u {
  let a = fp64_decode_raw_f32_bits(aBits);
  let b = fp64_decode_raw_f32_bits(bBits);

  if (a.isNan || b.isNan) {
    return vec2u(0x7fc00000u, 0u);
  }
  if (a.isInf || b.isInf) {
    if (a.isInf && b.isInf && a.sign != b.sign) {
      return vec2u(0x7fc00000u, 0u);
    }
    return select(vec2u(bBits, 0u), vec2u(aBits, 0u), a.isInf);
  }
  if (a.isZero && b.isZero) {
    return vec2u(0u);
  }
  if (a.isZero) {
    return vec2u(bBits, 0u);
  }
  if (b.isZero) {
    return vec2u(aBits, 0u);
  }

  let exponentDifference = abs(a.baseExponent - b.baseExponent);
  if (exponentDifference > 25) {
    if (fp64_raw_f32_magnitude_compare(aBits, bBits) >= 0) {
      return vec2u(aBits, bBits);
    }
    return vec2u(bBits, aBits);
  }

  let commonBaseExponent = min(a.baseExponent, b.baseExponent);
  let aMagnitude = fp64_u64_shift_left(
    vec2u(0u, a.significand),
    u32(a.baseExponent - commonBaseExponent)
  );
  let bMagnitude = fp64_u64_shift_left(
    vec2u(0u, b.significand),
    u32(b.baseExponent - commonBaseExponent)
  );

  var resultSign = a.sign;
  var resultMagnitude: vec2u;
  if (a.sign == b.sign) {
    resultMagnitude = fp64_u64_add(aMagnitude, bMagnitude);
  } else {
    let comparison = fp64_u64_compare(aMagnitude, bMagnitude);
    if (comparison == 0) {
      return vec2u(0u);
    }
    if (comparison > 0) {
      resultMagnitude = fp64_u64_sub(aMagnitude, bMagnitude);
    } else {
      resultSign = b.sign;
      resultMagnitude = fp64_u64_sub(bMagnitude, aMagnitude);
    }
  }

  return fp64_split_raw_accumulator_bits(
    resultSign,
    resultMagnitude,
    commonBaseExponent
  );
}
#endif

#ifndef LUMA_FP64_F32_INPUT_ONLY
fn fp64_add_aligned_magnitudes_to_fp64_bits(
  sign: u32,
  larger: Fp64Bits,
  smaller: Fp64Bits
) -> vec2u {
  let largeSignificand = fp64_u64_shift_left(larger.significand, 3u);
  let smallSignificand = fp64_u64_shift_right_sticky(
    fp64_u64_shift_left(smaller.significand, 3u),
    u32(larger.exponent - smaller.exponent)
  );
  let resultSignificand = fp64_u64_add(largeSignificand, smallSignificand);
  return fp64_split_binary64_accumulator_bits(
    sign,
    resultSignificand,
    larger.exponent - 55
  );
}

fn fp64_sub_aligned_magnitudes_to_fp64_bits(
  sign: u32,
  larger: Fp64Bits,
  smaller: Fp64Bits
) -> vec2u {
  let largeSignificand = fp64_u64_shift_left(larger.significand, 3u);
  let smallSignificand = fp64_u64_shift_right_sticky(
    fp64_u64_shift_left(smaller.significand, 3u),
    u32(larger.exponent - smaller.exponent)
  );
  let resultSignificand = fp64_u64_sub(largeSignificand, smallSignificand);
  return fp64_split_binary64_accumulator_bits(
    sign,
    resultSignificand,
    larger.exponent - 55
  );
}

fn fp64_add_aligned_magnitudes_to_f32_bits(sign: u32, larger: Fp64Bits, smaller: Fp64Bits) -> u32 {
  let largeSignificand = fp64_u64_shift_left(larger.significand, 3u);
  let smallSignificand = fp64_u64_shift_right_sticky(
    fp64_u64_shift_left(smaller.significand, 3u),
    u32(larger.exponent - smaller.exponent)
  );
  let resultSignificand = fp64_u64_add(largeSignificand, smallSignificand);
  return fp64_make_f32_bits_from_u64(sign, resultSignificand, larger.exponent - 55);
}

fn fp64_sub_aligned_magnitudes_to_f32_bits(sign: u32, larger: Fp64Bits, smaller: Fp64Bits) -> u32 {
  let largeSignificand = fp64_u64_shift_left(larger.significand, 3u);
  let smallSignificand = fp64_u64_shift_right_sticky(
    fp64_u64_shift_left(smaller.significand, 3u),
    u32(larger.exponent - smaller.exponent)
  );
  let resultSignificand = fp64_u64_sub(largeSignificand, smallSignificand);
  return fp64_make_f32_bits_from_u64(sign, resultSignificand, larger.exponent - 55);
}

// Subtract two raw binary64 values and round the exact result once to f32.
// The input words are canonical high/low words: .x contains sign/exponent/high
// fraction bits, and .y contains the low 32 fraction bits.
fn sub_fp64u32_to_f32_bits(aBits: vec2u, bBits: vec2u) -> u32 {
  let a = fp64_decode_bits(aBits);
  let b = fp64_decode_bits(bBits);
  let bSubtractionSign = b.sign ^ 1u;

  if (a.isNan || b.isNan) {
    return 0x7fc00000u;
  }
  if (a.isInf && b.isInf) {
    if (a.sign == bSubtractionSign) {
      return (a.sign << 31u) | 0x7f800000u;
    }
    return 0x7fc00000u;
  }
  if (a.isInf) {
    return (a.sign << 31u) | 0x7f800000u;
  }
  if (b.isInf) {
    return (bSubtractionSign << 31u) | 0x7f800000u;
  }
  if (a.isZero && b.isZero) {
    return select(0u, 0x80000000u, a.sign == 1u && b.sign == 0u);
  }

  let magnitudeComparison = fp64_finite_magnitude_compare(a, b);
  if (a.sign == bSubtractionSign) {
    if (magnitudeComparison >= 0) {
      return fp64_add_aligned_magnitudes_to_f32_bits(a.sign, a, b);
    }
    return fp64_add_aligned_magnitudes_to_f32_bits(a.sign, b, a);
  }

  if (magnitudeComparison == 0) {
    return 0u;
  }
  if (magnitudeComparison > 0) {
    return fp64_sub_aligned_magnitudes_to_f32_bits(a.sign, a, b);
  }
  return fp64_sub_aligned_magnitudes_to_f32_bits(bSubtractionSign, b, a);
}

fn sub_fp64u32_to_f32(aBits: vec2u, bBits: vec2u) -> f32 {
  return bitcast<f32>(sub_fp64u32_to_f32_bits(aBits, bBits));
}

// Subtract two raw binary64 values, round once to binary64, then split the
// result into normalized f32 limbs. Finite results must fit within the f32
// exponent range; larger magnitudes map to infinity and smaller magnitudes
// map to zero. The input words use canonical high/low word order.
fn sub_fp64u32_to_fp64_bits(aBits: vec2u, bBits: vec2u) -> vec2u {
  let a = fp64_decode_bits(aBits);
  let b = fp64_decode_bits(bBits);
  let bSubtractionSign = b.sign ^ 1u;

  if (a.isNan || b.isNan) {
    return vec2u(0x7fc00000u, 0u);
  }
  if (a.isInf && b.isInf) {
    if (a.sign == bSubtractionSign) {
      return vec2u((a.sign << 31u) | 0x7f800000u, 0u);
    }
    return vec2u(0x7fc00000u, 0u);
  }
  if (a.isInf) {
    return vec2u((a.sign << 31u) | 0x7f800000u, 0u);
  }
  if (b.isInf) {
    return vec2u((bSubtractionSign << 31u) | 0x7f800000u, 0u);
  }
  if (a.isZero && b.isZero) {
    return vec2u(0u);
  }

  let magnitudeComparison = fp64_finite_magnitude_compare(a, b);
  if (a.sign == bSubtractionSign) {
    if (magnitudeComparison >= 0) {
      return fp64_add_aligned_magnitudes_to_fp64_bits(a.sign, a, b);
    }
    return fp64_add_aligned_magnitudes_to_fp64_bits(a.sign, b, a);
  }

  if (magnitudeComparison == 0) {
    return vec2u(0u);
  }
  if (magnitudeComparison > 0) {
    return fp64_sub_aligned_magnitudes_to_fp64_bits(a.sign, a, b);
  }
  return fp64_sub_aligned_magnitudes_to_fp64_bits(bSubtractionSign, b, a);
}

fn sub_fp64u32_to_fp64(aBits: vec2u, bBits: vec2u) -> vec2f {
  let resultBits = sub_fp64u32_to_fp64_bits(aBits, bBits);
  return vec2f(bitcast<f32>(resultBits.x), bitcast<f32>(resultBits.y));
}
#endif

#ifndef LUMA_FP64_PREDICATE_ONLY
fn fp64_runtime_zero() -> f32 {
  return fp64arithmetic.ONE * 0.0;
}

fn prevent_fp64_optimization(value: f32) -> f32 {
#ifdef LUMA_FP64_CODE_ELIMINATION_WORKAROUND
  return value + fp64_runtime_zero();
#else
  return value;
#endif
}
#endif

#ifdef LUMA_FP64_INTEGER_ARITHMETIC
${C0}
#else
fn split(a: f32) -> vec2f {
  let splitValue = prevent_fp64_optimization(fp64arithmetic.SPLIT + fp64_runtime_zero());
  let t = prevent_fp64_optimization(a * splitValue);
  let temp = prevent_fp64_optimization(t - a);
  let aHi = prevent_fp64_optimization(t - temp);
  let aLo = prevent_fp64_optimization(a - aHi);
  return vec2f(aHi, aLo);
}

fn split2(a: vec2f) -> vec2f {
  var b = split(a.x);
  b.y = b.y + a.y;
  return b;
}

fn quickTwoSum(a: f32, b: f32) -> vec2f {
#ifdef LUMA_FP64_CODE_ELIMINATION_WORKAROUND
  let sum = prevent_fp64_optimization((a + b) * fp64arithmetic.ONE);
  let err = prevent_fp64_optimization(b - (sum - a) * fp64arithmetic.ONE);
#else
  let sum = prevent_fp64_optimization(a + b);
  let err = prevent_fp64_optimization(b - (sum - a));
#endif
  return vec2f(sum, err);
}

fn twoSum(a: f32, b: f32) -> vec2f {
  let s = prevent_fp64_optimization(a + b);
#ifdef LUMA_FP64_CODE_ELIMINATION_WORKAROUND
  let v = prevent_fp64_optimization((s * fp64arithmetic.ONE - a) * fp64arithmetic.ONE);
  let err =
    prevent_fp64_optimization((a - (s - v) * fp64arithmetic.ONE) *
      fp64arithmetic.ONE *
      fp64arithmetic.ONE *
      fp64arithmetic.ONE) +
    prevent_fp64_optimization(b - v);
#else
  let v = prevent_fp64_optimization(s - a);
  let err = prevent_fp64_optimization(a - (s - v)) + prevent_fp64_optimization(b - v);
#endif
  return vec2f(s, err);
}

fn twoSub(a: f32, b: f32) -> vec2f {
  let s = prevent_fp64_optimization(a - b);
#ifdef LUMA_FP64_CODE_ELIMINATION_WORKAROUND
  let v = prevent_fp64_optimization((s * fp64arithmetic.ONE - a) * fp64arithmetic.ONE);
  let err =
    prevent_fp64_optimization((a - (s - v) * fp64arithmetic.ONE) *
      fp64arithmetic.ONE *
      fp64arithmetic.ONE *
      fp64arithmetic.ONE) -
    prevent_fp64_optimization(b + v);
#else
  let v = prevent_fp64_optimization(s - a);
  let err = prevent_fp64_optimization(a - (s - v)) - prevent_fp64_optimization(b + v);
#endif
  return vec2f(s, err);
}

fn twoSqr(a: f32) -> vec2f {
  let prod = prevent_fp64_optimization(a * a);
  let aFp64 = split(a);
  let highProduct = prevent_fp64_optimization(aFp64.x * aFp64.x);
  let crossProduct = prevent_fp64_optimization(2.0 * aFp64.x * aFp64.y);
  let lowProduct = prevent_fp64_optimization(aFp64.y * aFp64.y);
#ifdef LUMA_FP64_CODE_ELIMINATION_WORKAROUND
  let err =
    (prevent_fp64_optimization(highProduct - prod) * fp64arithmetic.ONE +
      crossProduct * fp64arithmetic.ONE * fp64arithmetic.ONE) +
    lowProduct * fp64arithmetic.ONE * fp64arithmetic.ONE * fp64arithmetic.ONE;
#else
  let err = ((prevent_fp64_optimization(highProduct - prod) + crossProduct) + lowProduct);
#endif
  return vec2f(prod, err);
}

fn twoProd(a: f32, b: f32) -> vec2f {
  let prod = prevent_fp64_optimization(a * b);
  let aFp64 = split(a);
  let bFp64 = split(b);
  let highProduct = prevent_fp64_optimization(aFp64.x * bFp64.x);
  let crossProduct1 = prevent_fp64_optimization(aFp64.x * bFp64.y);
  let crossProduct2 = prevent_fp64_optimization(aFp64.y * bFp64.x);
  let lowProduct = prevent_fp64_optimization(aFp64.y * bFp64.y);
#ifdef LUMA_FP64_CODE_ELIMINATION_WORKAROUND
  let err1 = (highProduct - prod) * fp64arithmetic.ONE;
  let err2 = crossProduct1 * fp64arithmetic.ONE * fp64arithmetic.ONE;
  let err3 = crossProduct2 * fp64arithmetic.ONE * fp64arithmetic.ONE * fp64arithmetic.ONE;
  let err4 =
    lowProduct *
    fp64arithmetic.ONE *
    fp64arithmetic.ONE *
    fp64arithmetic.ONE *
    fp64arithmetic.ONE;
#else
  let err1 = highProduct - prod;
  let err2 = crossProduct1;
  let err3 = crossProduct2;
  let err4 = lowProduct;
#endif
  let err12InputA = prevent_fp64_optimization(err1);
  let err12InputB = prevent_fp64_optimization(err2);
  let err12 = prevent_fp64_optimization(err12InputA + err12InputB);
  let err123InputA = prevent_fp64_optimization(err12);
  let err123InputB = prevent_fp64_optimization(err3);
  let err123 = prevent_fp64_optimization(err123InputA + err123InputB);
  let err1234InputA = prevent_fp64_optimization(err123);
  let err1234InputB = prevent_fp64_optimization(err4);
  let err = prevent_fp64_optimization(err1234InputA + err1234InputB);
  return vec2f(prod, err);
}

fn sum_fp64(a: vec2f, b: vec2f) -> vec2f {
  var s = twoSum(a.x, b.x);
  let t = twoSum(a.y, b.y);
  s.y = prevent_fp64_optimization(s.y + t.x);
  s = quickTwoSum(s.x, s.y);
  s.y = prevent_fp64_optimization(s.y + t.y);
  s = quickTwoSum(s.x, s.y);
  return s;
}

fn sub_fp64(a: vec2f, b: vec2f) -> vec2f {
  var s = twoSub(a.x, b.x);
  let t = twoSub(a.y, b.y);
  s.y = prevent_fp64_optimization(s.y + t.x);
  s = quickTwoSum(s.x, s.y);
  s.y = prevent_fp64_optimization(s.y + t.y);
  s = quickTwoSum(s.x, s.y);
  return s;
}

fn mul_fp64(a: vec2f, b: vec2f) -> vec2f {
  var prod = twoProd(a.x, b.x);
  let crossProduct1 = prevent_fp64_optimization(a.x * b.y);
  prod.y = prevent_fp64_optimization(prod.y + crossProduct1);
#ifdef LUMA_FP64_HIGH_BITS_OVERFLOW_WORKAROUND
  prod = split2(prod);
#endif
  prod = quickTwoSum(prod.x, prod.y);
  let crossProduct2 = prevent_fp64_optimization(a.y * b.x);
  prod.y = prevent_fp64_optimization(prod.y + crossProduct2);
#ifdef LUMA_FP64_HIGH_BITS_OVERFLOW_WORKAROUND
  prod = split2(prod);
#endif
  prod = quickTwoSum(prod.x, prod.y);
  return prod;
}

#ifndef LUMA_FP64_PREDICATE_ONLY
fn div_fp64(a: vec2f, b: vec2f) -> vec2f {
  let xn = prevent_fp64_optimization(1.0 / b.x);
  let yn = mul_fp64(a, vec2f(xn, fp64_runtime_zero()));
  let diff = prevent_fp64_optimization(sub_fp64(a, mul_fp64(b, yn)).x);
  let prod = twoProd(xn, diff);
  return sum_fp64(yn, prod);
}

fn sqrt_fp64(a: vec2f) -> vec2f {
  if (a.x == 0.0 && a.y == 0.0) {
    return vec2f(0.0, 0.0);
  }
  if (a.x < 0.0) {
    let nanValue = fp64_nan(a.x);
    return vec2f(nanValue, nanValue);
  }

  let x = prevent_fp64_optimization(1.0 / sqrt(a.x));
  let yn = prevent_fp64_optimization(a.x * x);
#ifdef LUMA_FP64_CODE_ELIMINATION_WORKAROUND
  let ynSqr = twoSqr(yn) * fp64arithmetic.ONE;
#else
  let ynSqr = twoSqr(yn);
#endif
  let diff = prevent_fp64_optimization(sub_fp64(a, ynSqr).x);
  let prod = twoProd(prevent_fp64_optimization(x * 0.5), diff);
#ifdef LUMA_FP64_HIGH_BITS_OVERFLOW_WORKAROUND
  return sum_fp64(split(yn), prod);
#else
  return sum_fp64(vec2f(yn, 0.0), prod);
#endif
}
#endif
#endif

#ifndef LUMA_FP64_PREDICATE_ONLY
fn fp64_f32_bits_is_nan(bits: u32) -> bool {
  return (bits & 0x7fffffffu) > 0x7f800000u;
}

fn fp64_f32_bits_is_inf(bits: u32) -> bool {
  return (bits & 0x7fffffffu) == 0x7f800000u;
}

fn fp64_compare_f32_bits(aBits: u32, bBits: u32) -> i32 {
  let aMagnitude = aBits & 0x7fffffffu;
  let bMagnitude = bBits & 0x7fffffffu;
  if (aMagnitude == 0u && bMagnitude == 0u) {
    return 0;
  }
  let aSign = aBits >> 31u;
  let bSign = bBits >> 31u;
  if (aSign != bSign) {
    return select(1, -1, aSign == 1u);
  }
  if (aMagnitude == bMagnitude) {
    return 0;
  }
  let magnitudeComparison = select(-1, 1, aMagnitude > bMagnitude);
  return select(magnitudeComparison, -magnitudeComparison, aSign == 1u);
}

// Normalize an arbitrary pair of finite f32 limbs with integer accumulation.
// This is independent of LUMA_FP64_INTEGER_ARITHMETIC and canonicalizes every
// representation of zero to vec2f(+0.0, +0.0).
fn normalize_fp64(value: vec2f) -> vec2f {
  let resultBits = fp64_add_raw_f32_bits(bitcast<u32>(value.x), bitcast<u32>(value.y));
  return vec2f(bitcast<f32>(resultBits.x), bitcast<f32>(resultBits.y));
}

fn is_nan_fp64(value: vec2f) -> bool {
  let normalized = normalize_fp64(value);
  return fp64_f32_bits_is_nan(bitcast<u32>(normalized.x)) ||
    fp64_f32_bits_is_nan(bitcast<u32>(normalized.y));
}

fn is_finite_fp64(value: vec2f) -> bool {
  let normalized = normalize_fp64(value);
  let highBits = bitcast<u32>(normalized.x);
  let lowBits = bitcast<u32>(normalized.y);
  return !fp64_f32_bits_is_nan(highBits) && !fp64_f32_bits_is_nan(lowBits) &&
    !fp64_f32_bits_is_inf(highBits) && !fp64_f32_bits_is_inf(lowBits);
}

// Returns -1, 0, or 1. NaN is unordered and returns 0; call is_nan_fp64 or
// is_finite_fp64 first when 0 must mean a finite zero.
fn sign_fp64(value: vec2f) -> i32 {
  let normalized = normalize_fp64(value);
  let highBits = bitcast<u32>(normalized.x);
  let lowBits = bitcast<u32>(normalized.y);
  if (fp64_f32_bits_is_nan(highBits) || fp64_f32_bits_is_nan(lowBits)) {
    return 0;
  }
  if ((highBits & 0x7fffffffu) != 0u) {
    return select(1, -1, (highBits >> 31u) == 1u);
  }
  if ((lowBits & 0x7fffffffu) != 0u) {
    return select(1, -1, (lowBits >> 31u) == 1u);
  }
  return 0;
}

// Compares double-single values and returns -1, 0, or 1. NaN is unordered
// and returns 0; callers that require equality semantics must first check
// is_nan_fp64 or is_finite_fp64.
fn compare_fp64(a: vec2f, b: vec2f) -> i32 {
  let normalizedA = normalize_fp64(a);
  let normalizedB = normalize_fp64(b);
  let aHighBits = bitcast<u32>(normalizedA.x);
  let aLowBits = bitcast<u32>(normalizedA.y);
  let bHighBits = bitcast<u32>(normalizedB.x);
  let bLowBits = bitcast<u32>(normalizedB.y);
  if (fp64_f32_bits_is_nan(aHighBits) || fp64_f32_bits_is_nan(aLowBits) ||
      fp64_f32_bits_is_nan(bHighBits) || fp64_f32_bits_is_nan(bLowBits)) {
    return 0;
  }
  let highComparison = fp64_compare_f32_bits(aHighBits, bHighBits);
  if (highComparison != 0) {
    return highComparison;
  }
  return fp64_compare_f32_bits(aLowBits, bLowBits);
}
#endif
`});var EI,Sp,B0=b(()=>{P0();A0();R0();EI={ONE:1,SPLIT:4097},Sp={name:"fp64arithmetic",source:I0,fs:Ep,vs:Ep,defaultUniforms:EI,uniformTypes:{ONE:"f32",SPLIT:"f32"},fp64ify:xp,fp64LowPart:E0,fp64ifyMatrix4:S0}});function k0(r){return`layout(std140) uniform ${r}Uniforms {
  float useByteColors;
} ${r};

vec3 ${r}_normalize(vec3 inputColor) {
  return ${r}.useByteColors > 0.5 ? inputColor / 255.0 : inputColor;
}

vec4 ${r}_normalize(vec4 inputColor) {
  return ${r}.useByteColors > 0.5 ? inputColor / 255.0 : inputColor;
}

vec4 ${r}_premultiplyAlpha(vec4 inputColor) {
  return vec4(inputColor.rgb * inputColor.a, inputColor.a);
}

vec4 ${r}_unpremultiplyAlpha(vec4 inputColor) {
  return inputColor.a > 0.0 ? vec4(inputColor.rgb / inputColor.a, inputColor.a) : vec4(0.0);
}

vec4 ${r}_premultiply_alpha(vec4 inputColor) {
  return ${r}_premultiplyAlpha(inputColor);
}

vec4 ${r}_unpremultiply_alpha(vec4 inputColor) {
  return ${r}_unpremultiplyAlpha(inputColor);
}
`}function D0(r){return`struct ${r}Uniforms {
  useByteColors: f32
};

@group(0) @binding(auto) var<uniform> ${r} : ${r}Uniforms;

fn ${r}_normalize(inputColor: vec3<f32>) -> vec3<f32> {
  return select(inputColor, inputColor / 255.0, ${r}.useByteColors > 0.5);
}

fn ${r}_normalize4(inputColor: vec4<f32>) -> vec4<f32> {
  return select(inputColor, inputColor / 255.0, ${r}.useByteColors > 0.5);
}

fn ${r}_premultiplyAlpha(inputColor: vec4<f32>) -> vec4<f32> {
  return vec4<f32>(inputColor.rgb * inputColor.a, inputColor.a);
}

fn ${r}_unpremultiplyAlpha(inputColor: vec4<f32>) -> vec4<f32> {
  return select(
    vec4<f32>(0.0),
    vec4<f32>(inputColor.rgb / inputColor.a, inputColor.a),
    inputColor.a > 0.0
  );
}

fn ${r}_premultiply_alpha(inputColor: vec4<f32>) -> vec4<f32> {
  return ${r}_premultiplyAlpha(inputColor);
}

fn ${r}_unpremultiply_alpha(inputColor: vec4<f32>) -> vec4<f32> {
  return ${r}_unpremultiplyAlpha(inputColor);
}
`}var gr,SI,PI,T7,L7,TI,LI,A7,C7,O0,M7,AI,I7,N0,F0=b(()=>{gr={RGBA8UNORM:0,RGBA16FLOAT:1,RGBA32FLOAT:2},SI={rgba8unorm:4,rgba16float:8,rgba32float:16},PI={...SI},T7={rgba8unorm:gr.RGBA8UNORM,rgba16float:gr.RGBA16FLOAT,rgba32float:gr.RGBA32FLOAT},L7={[gr.RGBA8UNORM]:"rgba8unorm",[gr.RGBA16FLOAT]:"rgba16float",[gr.RGBA32FLOAT]:"rgba32float"},TI={useByteColors:"f32"},LI={useByteColors:!0},A7={format:gr.RGBA8UNORM,wordStride:PI.rgba8unorm/Uint32Array.BYTES_PER_ELEMENT,wordOffset:0,_padding:0},C7=k0("colors"),O0=k0("floatColors"),M7=D0("colors"),AI=D0("floatColors"),I7=`struct storageColorsUniforms {
  format: u32,
  wordStride: u32,
  wordOffset: u32,
  _padding: u32
};

@group(0) @binding(auto) var<uniform> storageColors : storageColorsUniforms;
@group(0) @binding(auto) var<storage, read> storageColorsBuffer : array<u32>;

const STORAGE_COLOR_FORMAT_RGBA8UNORM : u32 = ${gr.RGBA8UNORM}u;
const STORAGE_COLOR_FORMAT_RGBA16FLOAT : u32 = ${gr.RGBA16FLOAT}u;

fn storageColors_getWordIndex(rowIndex: u32) -> u32 {
  return storageColors.wordOffset + rowIndex * storageColors.wordStride;
}

fn storageColors_readRgba8UnormColor(wordIndex: u32) -> vec4<f32> {
  return unpack4x8unorm(storageColorsBuffer[wordIndex]);
}

fn storageColors_readRgba16FloatColor(wordIndex: u32) -> vec4<f32> {
  let redGreen = unpack2x16float(storageColorsBuffer[wordIndex]);
  let blueAlpha = unpack2x16float(storageColorsBuffer[wordIndex + 1u]);
  return vec4<f32>(redGreen.x, redGreen.y, blueAlpha.x, blueAlpha.y);
}

fn storageColors_readRgba32FloatColor(wordIndex: u32) -> vec4<f32> {
  return vec4<f32>(
    bitcast<f32>(storageColorsBuffer[wordIndex]),
    bitcast<f32>(storageColorsBuffer[wordIndex + 1u]),
    bitcast<f32>(storageColorsBuffer[wordIndex + 2u]),
    bitcast<f32>(storageColorsBuffer[wordIndex + 3u])
  );
}

fn storageColors_readColor(rowIndex: u32) -> vec4<f32> {
  let wordIndex = storageColors_getWordIndex(rowIndex);
  if (storageColors.format == STORAGE_COLOR_FORMAT_RGBA8UNORM) {
    return storageColors_readRgba8UnormColor(wordIndex);
  }
  if (storageColors.format == STORAGE_COLOR_FORMAT_RGBA16FLOAT) {
    return storageColors_readRgba16FloatColor(wordIndex);
  }
  return storageColors_readRgba32FloatColor(wordIndex);
}
`;N0={name:"floatColors",props:{},uniforms:{},vs:O0,fs:O0,source:AI,uniformTypes:TI,defaultUniforms:LI}});function RI(r={},e){let t={},n=bl(r.useByteColors,!0);if(r.highlightedObjectColor!==void 0)if(r.highlightedObjectColor===null)t.isHighlightActive=!1;else{t.isHighlightActive=!0;let i=r.highlightedObjectColor.slice(0,3);t.highlightedObjectColor=i}return r.highlightColor&&(t.highlightColor=T0(r.highlightColor,n)),r.isActive!==void 0&&(t.isActive=!!r.isActive,t.isAttribute=!!r.isAttribute),r.useByteColors!==void 0&&(t.useByteColors=!!r.useByteColors),t}var CI,MI,II,Fr,U0=b(()=>{wp();CI=[0,1,1,1],MI=`layout(std140) uniform pickingUniforms {
  float isActive;
  float isAttribute;
  float isHighlightActive;
  float useByteColors;
  vec3 highlightedObjectColor;
  vec4 highlightColor;
} picking;

out vec4 picking_vRGBcolor_Avalid;

// Normalize unsigned byte color to 0-1 range
vec3 picking_normalizeColor(vec3 color) {
  return picking.useByteColors > 0.5 ? color / 255.0 : color;
}

// Normalize unsigned byte color to 0-1 range
vec4 picking_normalizeColor(vec4 color) {
  return picking.useByteColors > 0.5 ? color / 255.0 : color;
}

bool picking_isColorZero(vec3 color) {
  return dot(color, vec3(1.0)) < 0.00001;
}

bool picking_isColorValid(vec3 color) {
  return dot(color, vec3(1.0)) > 0.00001;
}

// Check if this vertex is highlighted 
bool isVertexHighlighted(vec3 vertexColor) {
  vec3 highlightedObjectColor = picking_normalizeColor(picking.highlightedObjectColor);
  return
    bool(picking.isHighlightActive) && picking_isColorZero(abs(vertexColor - highlightedObjectColor));
}

// Set the current picking color
void picking_setPickingColor(vec3 pickingColor) {
  pickingColor = picking_normalizeColor(pickingColor);

  if (bool(picking.isActive)) {
    // Use alpha as the validity flag. If pickingColor is [0, 0, 0] fragment is non-pickable
    picking_vRGBcolor_Avalid.a = float(picking_isColorValid(pickingColor));

    if (!bool(picking.isAttribute)) {
      // Stores the picking color so that the fragment shader can render it during picking
      picking_vRGBcolor_Avalid.rgb = pickingColor;
    }
  } else {
    // Do the comparison with selected item color in vertex shader as it should mean fewer compares
    picking_vRGBcolor_Avalid.a = float(isVertexHighlighted(pickingColor));
  }
}

void picking_setPickingAttribute(float value) {
  if (bool(picking.isAttribute)) {
    picking_vRGBcolor_Avalid.r = value;
  }
}

void picking_setPickingAttribute(vec2 value) {
  if (bool(picking.isAttribute)) {
    picking_vRGBcolor_Avalid.rg = value;
  }
}

void picking_setPickingAttribute(vec3 value) {
  if (bool(picking.isAttribute)) {
    picking_vRGBcolor_Avalid.rgb = value;
  }
}
`,II=`layout(std140) uniform pickingUniforms {
  float isActive;
  float isAttribute;
  float isHighlightActive;
  float useByteColors;
  vec3 highlightedObjectColor;
  vec4 highlightColor;
} picking;

in vec4 picking_vRGBcolor_Avalid;

/*
 * Returns highlight color if this item is selected.
 */
vec4 picking_filterHighlightColor(vec4 color) {
  // If we are still picking, we don't highlight
  if (picking.isActive > 0.5) {
    return color;
  }

  bool selected = bool(picking_vRGBcolor_Avalid.a);

  if (selected) {
    // Blend in highlight color based on its alpha value
    float highLightAlpha = picking.highlightColor.a;
    float blendedAlpha = highLightAlpha + color.a * (1.0 - highLightAlpha);
    float highLightRatio = highLightAlpha / blendedAlpha;

    vec3 blendedRGB = mix(color.rgb, picking.highlightColor.rgb, highLightRatio);
    return vec4(blendedRGB, blendedAlpha);
  } else {
    return color;
  }
}

/*
 * Returns picking color if picking enabled else unmodified argument.
 */
vec4 picking_filterPickingColor(vec4 color) {
  if (bool(picking.isActive)) {
    if (picking_vRGBcolor_Avalid.a == 0.0) {
      discard;
    }
    return picking_vRGBcolor_Avalid;
  }
  return color;
}

/*
 * Returns picking color if picking is enabled if not
 * highlight color if this item is selected, otherwise unmodified argument.
 */
vec4 picking_filterColor(vec4 color) {
  vec4 highlightColor = picking_filterHighlightColor(color);
  return picking_filterPickingColor(highlightColor);
}
`,Fr={props:{},uniforms:{},name:"picking",uniformTypes:{isActive:"f32",isAttribute:"f32",isHighlightActive:"f32",useByteColors:"f32",highlightedObjectColor:"vec3<f32>",highlightColor:"vec4<f32>"},defaultUniforms:{isActive:!1,isAttribute:!1,isHighlightActive:!1,useByteColors:!0,highlightedObjectColor:[0,0,0],highlightColor:CI},vs:MI,fs:II,getUniforms:RI}});var Pp,G0=b(()=>{Pp=`precision highp int;

// #if (defined(SHADER_TYPE_FRAGMENT) && defined(LIGHTING_FRAGMENT)) || (defined(SHADER_TYPE_VERTEX) && defined(LIGHTING_VERTEX))
struct AmbientLight {
  vec3 color;
};

struct PointLight {
  vec3 color;
  vec3 position;
  vec3 attenuation; // 2nd order x:Constant-y:Linear-z:Exponential
};

struct SpotLight {
  vec3 color;
  vec3 position;
  vec3 direction;
  vec3 attenuation;
  vec2 coneCos;
};

struct DirectionalLight {
  vec3 color;
  vec3 direction;
};

struct UniformLight {
  vec3 color;
  vec3 position;
  vec3 direction;
  vec3 attenuation;
  vec2 coneCos;
};

layout(std140) uniform lightingUniforms {
  int enabled;
  int directionalLightCount;
  int pointLightCount;
  int spotLightCount;
  vec3 ambientColor;
  UniformLight lights[5];
} lighting;

PointLight lighting_getPointLight(int index) {
  UniformLight light = lighting.lights[index];
  return PointLight(light.color, light.position, light.attenuation);
}

SpotLight lighting_getSpotLight(int index) {
  UniformLight light = lighting.lights[lighting.pointLightCount + index];
  return SpotLight(light.color, light.position, light.direction, light.attenuation, light.coneCos);
}

DirectionalLight lighting_getDirectionalLight(int index) {
  UniformLight light =
    lighting.lights[lighting.pointLightCount + lighting.spotLightCount + index];
  return DirectionalLight(light.color, light.direction);
}

float getPointLightAttenuation(PointLight pointLight, float distance) {
  return pointLight.attenuation.x
       + pointLight.attenuation.y * distance
       + pointLight.attenuation.z * distance * distance;
}

float getSpotLightAttenuation(SpotLight spotLight, vec3 positionWorldspace) {
  vec3 light_direction = normalize(positionWorldspace - spotLight.position);
  float coneFactor = smoothstep(
    spotLight.coneCos.y,
    spotLight.coneCos.x,
    dot(normalize(spotLight.direction), light_direction)
  );
  float distanceAttenuation = getPointLightAttenuation(
    PointLight(spotLight.color, spotLight.position, spotLight.attenuation),
    distance(spotLight.position, positionWorldspace)
  );
  return distanceAttenuation / max(coneFactor, 0.0001);
}

// #endif
`});var z0,$0=b(()=>{z0=`// #if (defined(SHADER_TYPE_FRAGMENT) && defined(LIGHTING_FRAGMENT)) || (defined(SHADER_TYPE_VERTEX) && defined(LIGHTING_VERTEX))
const MAX_LIGHTS: i32 = 5;

struct AmbientLight {
  color: vec3<f32>,
};

struct PointLight {
  color: vec3<f32>,
  position: vec3<f32>,
  attenuation: vec3<f32>, // 2nd order x:Constant-y:Linear-z:Exponential
};

struct SpotLight {
  color: vec3<f32>,
  position: vec3<f32>,
  direction: vec3<f32>,
  attenuation: vec3<f32>,
  coneCos: vec2<f32>,
};

struct DirectionalLight {
  color: vec3<f32>,
  direction: vec3<f32>,
};

struct UniformLight {
  color: vec3<f32>,
  position: vec3<f32>,
  direction: vec3<f32>,
  attenuation: vec3<f32>,
  coneCos: vec2<f32>,
};

struct lightingUniforms {
  enabled: i32,
  directionalLightCount: i32,
  pointLightCount: i32,
  spotLightCount: i32,
  ambientColor: vec3<f32>,
  lights: array<UniformLight, 5>,
};

@group(2) @binding(auto) var<uniform> lighting : lightingUniforms;

fn lighting_getPointLight(index: i32) -> PointLight {
  let light = lighting.lights[index];
  return PointLight(light.color, light.position, light.attenuation);
}

fn lighting_getSpotLight(index: i32) -> SpotLight {
  let light = lighting.lights[lighting.pointLightCount + index];
  return SpotLight(light.color, light.position, light.direction, light.attenuation, light.coneCos);
}

fn lighting_getDirectionalLight(index: i32) -> DirectionalLight {
  let light = lighting.lights[lighting.pointLightCount + lighting.spotLightCount + index];
  return DirectionalLight(light.color, light.direction);
}

fn getPointLightAttenuation(pointLight: PointLight, distance: f32) -> f32 {
  return pointLight.attenuation.x
       + pointLight.attenuation.y * distance
       + pointLight.attenuation.z * distance * distance;
}

fn getSpotLightAttenuation(spotLight: SpotLight, positionWorldspace: vec3<f32>) -> f32 {
  let lightDirection = normalize(positionWorldspace - spotLight.position);
  let coneFactor = smoothstep(
    spotLight.coneCos.y,
    spotLight.coneCos.x,
    dot(normalize(spotLight.direction), lightDirection)
  );
  let distanceAttenuation = getPointLightAttenuation(
    PointLight(spotLight.color, spotLight.position, spotLight.attenuation),
    distance(spotLight.position, positionWorldspace)
  );
  return distanceAttenuation / max(coneFactor, 0.0001);
}
`});function OI(r,e={}){if(r=r&&{...r},!r)return vl();r.lights&&(r={...r,...DI(r.lights),lights:void 0});let{useByteColors:t,ambientLight:n,pointLights:i,spotLights:o,directionalLights:s}=r||{};if(!(n||i&&i.length>0||o&&o.length>0||s&&s.length>0))return{...vl(),enabled:0};let c={...vl(),...kI({useByteColors:t,ambientLight:n,pointLights:i,spotLights:o,directionalLights:s})};return r.enabled!==void 0&&(c.enabled=r.enabled?1:0),c}function kI({useByteColors:r,ambientLight:e,pointLights:t=[],spotLights:n=[],directionalLights:i=[]}){let o=W0(),s=0,a=0,c=0,l=0;for(let u of t){if(s>=In)break;o[s]={...o[s],color:xl(u,r),position:u.position,attenuation:u.attenuation||[1,0,0]},s++,a++}for(let u of n){if(s>=In)break;o[s]={...o[s],color:xl(u,r),position:u.position,direction:u.direction,attenuation:u.attenuation||[1,0,0],coneCos:FI(u)},s++,c++}for(let u of i){if(s>=In)break;o[s]={...o[s],color:xl(u,r),direction:u.direction},s++,l++}return t.length+n.length+i.length>In&&T.warn(`MAX_LIGHTS exceeded, truncating to ${In}`)(),{ambientColor:xl(e,r),directionalLightCount:l,pointLightCount:a,spotLightCount:c,lights:o}}function DI(r){let e={pointLights:[],spotLights:[],directionalLights:[]};for(let t of r||[])switch(t.type){case"ambient":e.ambientLight=t;break;case"directional":e.directionalLights?.push(t);break;case"point":e.pointLights?.push(t);break;case"spot":e.spotLights?.push(t);break;default:}return e}function xl(r={},e){let{color:t=[0,0,0],intensity:n=1}=r;return vp(t,bl(e,!0)).map(o=>o*n)}function vl(){return{enabled:1,directionalLightCount:0,pointLightCount:0,spotLightCount:0,ambientColor:[.1,.1,.1],lights:W0()}}function W0(){return Array.from({length:In},()=>NI())}function NI(){return{color:[1,1,1],position:[1,1,2],direction:[1,1,1],attenuation:[1,0,0],coneCos:[1,0]}}function FI(r){let e=r.innerConeAngle??0,t=r.outerConeAngle??Math.PI/4;return[Math.cos(e),Math.cos(t)]}var In,BI,V0,j0=b(()=>{N();G0();$0();wp();In=5,BI={color:"vec3<f32>",position:"vec3<f32>",direction:"vec3<f32>",attenuation:"vec3<f32>",coneCos:"vec2<f32>"},V0={props:{},uniforms:{},name:"lighting",defines:{},uniformTypes:{enabled:"i32",directionalLightCount:"i32",pointLightCount:"i32",spotLightCount:"i32",ambientColor:"vec3<f32>",lights:[BI,In]},defaultUniforms:vl(),bindingLayout:[{name:"lighting",group:2}],firstBindingSlot:0,source:z0,vs:Pp,fs:Pp,getUniforms:OI}});var H0,Y0,q0=b(()=>{H0=`layout(std140) uniform phongMaterialUniforms {
  uniform bool unlit;
  uniform float ambient;
  uniform float diffuse;
  uniform float shininess;
  uniform vec3  specularColor;
} material;
`,Y0=`layout(std140) uniform phongMaterialUniforms {
  uniform bool unlit;
  uniform float ambient;
  uniform float diffuse;
  uniform float shininess;
  uniform vec3  specularColor;
} material;

vec3 lighting_getLightColor(vec3 surfaceColor, vec3 light_direction, vec3 view_direction, vec3 normal_worldspace, vec3 color) {
  vec3 halfway_direction = normalize(light_direction + view_direction);
  float lambertian = dot(light_direction, normal_worldspace);
  float specular = 0.0;
  if (lambertian > 0.0) {
    float specular_angle = max(dot(normal_worldspace, halfway_direction), 0.0);
    specular = pow(specular_angle, material.shininess);
  }
  lambertian = max(lambertian, 0.0);
  return (lambertian * material.diffuse * surfaceColor + specular * floatColors_normalize(material.specularColor)) * color;
}

vec3 lighting_getLightColor(vec3 surfaceColor, vec3 cameraPosition, vec3 position_worldspace, vec3 normal_worldspace) {
  vec3 lightColor = surfaceColor;

  if (material.unlit) {
    return surfaceColor;
  }

  if (lighting.enabled == 0) {
    return lightColor;
  }

  vec3 view_direction = normalize(cameraPosition - position_worldspace);
  lightColor = material.ambient * surfaceColor * lighting.ambientColor;

  for (int i = 0; i < lighting.pointLightCount; i++) {
    PointLight pointLight = lighting_getPointLight(i);
    vec3 light_position_worldspace = pointLight.position;
    vec3 light_direction = normalize(light_position_worldspace - position_worldspace);
    float light_attenuation = getPointLightAttenuation(pointLight, distance(light_position_worldspace, position_worldspace));
    lightColor += lighting_getLightColor(surfaceColor, light_direction, view_direction, normal_worldspace, pointLight.color / light_attenuation);
  }

  for (int i = 0; i < lighting.spotLightCount; i++) {
    SpotLight spotLight = lighting_getSpotLight(i);
    vec3 light_position_worldspace = spotLight.position;
    vec3 light_direction = normalize(light_position_worldspace - position_worldspace);
    float light_attenuation = getSpotLightAttenuation(spotLight, position_worldspace);
    lightColor += lighting_getLightColor(surfaceColor, light_direction, view_direction, normal_worldspace, spotLight.color / light_attenuation);
  }

  for (int i = 0; i < lighting.directionalLightCount; i++) {
    DirectionalLight directionalLight = lighting_getDirectionalLight(i);
    lightColor += lighting_getLightColor(surfaceColor, -directionalLight.direction, view_direction, normal_worldspace, directionalLight.color);
  }
  
  return lightColor;
}
`});var X0,Z0=b(()=>{X0=`struct phongMaterialUniforms {
  unlit: u32,
  ambient: f32,
  diffuse: f32,
  shininess: f32,
  specularColor: vec3<f32>,
};

@group(3) @binding(auto) var<uniform> phongMaterial : phongMaterialUniforms;

fn lighting_getLightColor(surfaceColor: vec3<f32>, light_direction: vec3<f32>, view_direction: vec3<f32>, normal_worldspace: vec3<f32>, color: vec3<f32>) -> vec3<f32> {
  let halfway_direction: vec3<f32> = normalize(light_direction + view_direction);
  var lambertian: f32 = dot(light_direction, normal_worldspace);
  var specular: f32 = 0.0;
  if (lambertian > 0.0) {
    let specular_angle = max(dot(normal_worldspace, halfway_direction), 0.0);
    specular = pow(specular_angle, phongMaterial.shininess);
  }
  lambertian = max(lambertian, 0.0);
  return (
    lambertian * phongMaterial.diffuse * surfaceColor +
    specular * floatColors_normalize(phongMaterial.specularColor)
  ) * color;
}

fn lighting_getLightColor2(surfaceColor: vec3<f32>, cameraPosition: vec3<f32>, position_worldspace: vec3<f32>, normal_worldspace: vec3<f32>) -> vec3<f32> {
  var lightColor: vec3<f32> = surfaceColor;

  if (phongMaterial.unlit != 0u) {
    return surfaceColor;
  }

  if (lighting.enabled == 0) {
    return lightColor;
  }

  let view_direction: vec3<f32> = normalize(cameraPosition - position_worldspace);
  lightColor = phongMaterial.ambient * surfaceColor * lighting.ambientColor;

  for (var i: i32 = 0; i < lighting.pointLightCount; i++) {
    let pointLight: PointLight = lighting_getPointLight(i);
    let light_position_worldspace: vec3<f32> = pointLight.position;
    let light_direction: vec3<f32> = normalize(light_position_worldspace - position_worldspace);
    let light_attenuation = getPointLightAttenuation(
      pointLight,
      distance(light_position_worldspace, position_worldspace)
    );
    lightColor += lighting_getLightColor(
      surfaceColor,
      light_direction,
      view_direction,
      normal_worldspace,
      pointLight.color / light_attenuation
    );
  }

  for (var i: i32 = 0; i < lighting.spotLightCount; i++) {
    let spotLight: SpotLight = lighting_getSpotLight(i);
    let light_position_worldspace: vec3<f32> = spotLight.position;
    let light_direction: vec3<f32> = normalize(light_position_worldspace - position_worldspace);
    let light_attenuation = getSpotLightAttenuation(spotLight, position_worldspace);
    lightColor += lighting_getLightColor(
      surfaceColor,
      light_direction,
      view_direction,
      normal_worldspace,
      spotLight.color / light_attenuation
    );
  }

  for (var i: i32 = 0; i < lighting.directionalLightCount; i++) {
    let directionalLight: DirectionalLight = lighting_getDirectionalLight(i);
    lightColor += lighting_getLightColor(surfaceColor, -directionalLight.direction, view_direction, normal_worldspace, directionalLight.color);
  }  
  
  return lightColor;
}

fn lighting_getSpecularLightColor(cameraPosition: vec3<f32>, position_worldspace: vec3<f32>, normal_worldspace: vec3<f32>) -> vec3<f32>{
  var lightColor = vec3<f32>(0, 0, 0);
  let surfaceColor = vec3<f32>(0, 0, 0);

  if (lighting.enabled != 0) {
    let view_direction = normalize(cameraPosition - position_worldspace);

    for (var i: i32 = 0; i < lighting.pointLightCount; i++) {
      let pointLight: PointLight = lighting_getPointLight(i);
      let light_position_worldspace: vec3<f32> = pointLight.position;
      let light_direction: vec3<f32> = normalize(light_position_worldspace - position_worldspace);
      let light_attenuation = getPointLightAttenuation(
        pointLight,
        distance(light_position_worldspace, position_worldspace)
      );
      lightColor += lighting_getLightColor(
        surfaceColor,
        light_direction,
        view_direction,
        normal_worldspace,
        pointLight.color / light_attenuation
      );
    }

    for (var i: i32 = 0; i < lighting.spotLightCount; i++) {
      let spotLight: SpotLight = lighting_getSpotLight(i);
      let light_position_worldspace: vec3<f32> = spotLight.position;
      let light_direction: vec3<f32> = normalize(light_position_worldspace - position_worldspace);
      let light_attenuation = getSpotLightAttenuation(spotLight, position_worldspace);
      lightColor += lighting_getLightColor(
        surfaceColor,
        light_direction,
        view_direction,
        normal_worldspace,
        spotLight.color / light_attenuation
      );
    }

    for (var i: i32 = 0; i < lighting.directionalLightCount; i++) {
        let directionalLight: DirectionalLight = lighting_getDirectionalLight(i);
        lightColor += lighting_getLightColor(surfaceColor, -directionalLight.direction, view_direction, normal_worldspace, directionalLight.color);
    }
  }
  return lightColor;
}
`});var UI,Si,K0=b(()=>{F0();j0();q0();Z0();UI=[38.25,38.25,38.25],Si={props:{},name:"gouraudMaterial",bindingLayout:[{name:"gouraudMaterial",group:3}],vs:Y0.replace("phongMaterial","gouraudMaterial"),fs:H0.replace("phongMaterial","gouraudMaterial"),source:X0.replaceAll("phongMaterial","gouraudMaterial"),defines:{LIGHTING_VERTEX:!0},dependencies:[V0,N0],uniformTypes:{unlit:"i32",ambient:"f32",diffuse:"f32",shininess:"f32",specularColor:"vec3<f32>"},defaultUniforms:{unlit:!1,ambient:.35,diffuse:.6,shininess:32,specularColor:UI},getUniforms(r){return{...Si.defaultUniforms,...r}}}});var qe=b(()=>{Fd();Wb();Eh();Sx();Tx();L0();B0();U0();K0()});function Xt(r="id"){qp[r]=qp[r]||1;let e=qp[r]++;return`${r}-${e}`}var qp,zi=b(()=>{qp={}});function Fn(r){switch(r){case"POSITION":return"positions";case"NORMAL":return"normals";case"TEXCOORD_0":return"texCoords";case"TEXCOORD_1":return"texCoords1";case"COLOR_0":return"colors";default:return r}}function kB(r){let e=[];for(let[t,n]of Object.entries(r)){if(!n)continue;let{value:i,size:o,normalized:s}=n;if(o===void 0)throw new Error(`Attribute ${t} is missing a size`);e.push({name:Fn(t),format:ne.getVertexFormatFromAttribute(i,o,s)})}return e}var yt,Wl=b(()=>{N();zi();yt=class{constructor(e){d(this,"id");d(this,"topology");d(this,"vertexCount");d(this,"indices");d(this,"attributes");d(this,"bufferLayout");d(this,"userData",{});let{attributes:t={},indices:n=null,vertexCount:i=null}=e;this.id=e.id||Xt("geometry"),this.topology=e.topology,n&&(this.indices=ArrayBuffer.isView(n)?{value:n,size:1}:n),this.attributes={};for(let[o,s]of Object.entries(t)){let a=ArrayBuffer.isView(s)?{value:s}:s;if(!ArrayBuffer.isView(a.value))throw new Error(`${this._print(o)}: must be typed array or object with value as typed array`);if((o==="POSITION"||o==="positions")&&!a.size&&(a.size=3),o==="indices"){if(this.indices)throw new Error("Multiple indices detected");this.indices=a}else{let c=Fn(o),l=Object.keys(this.attributes).find(u=>Fn(u)===c);l&&delete this.attributes[l],this.attributes[o]=a}}this.indices&&this.indices.isIndexed!==void 0&&(this.indices=Object.assign({},this.indices),delete this.indices.isIndexed),this.vertexCount=i||this._calculateVertexCount(this.attributes,this.indices),this.bufferLayout=e.bufferLayout||kB(this.attributes)}getVertexCount(){return this.vertexCount}getAttributes(){return this.indices?{indices:this.indices,...this.attributes}:this.attributes}_print(e){return`Geometry ${this.id} attribute ${e}`}_setAttributes(e,t){return this}_calculateVertexCount(e,t){if(t)return t.value.length;let n=1/0;for(let i of Object.values(e)){if(!i)continue;let{value:o,size:s,constant:a}=i;!a&&o&&s!==void 0&&s>=1&&(n=Math.min(n,o.length/s))}return n}}});function Hv(r,e={}){let t=e.bufferName||"geometry";if(DB(r,t))return r;let n=e.minAttributeAlignment||4,i=NB(r,e.attributes),o=[],s=0,a=1/0;for(let[u,f]of i){if(!f)continue;if(f.constant)throw new Error(`Attribute ${u} is constant`);let{value:h,size:p,normalized:m}=f;if(!ArrayBuffer.isView(h))throw new Error(`Attribute ${u} is missing typed array data`);if(p===void 0)throw new Error(`Attribute ${u} is missing a size`);let g=ne.getVertexFormatFromAttribute(h,p,m),y=ne.getVertexFormatInfo(g);s=jv(s,n),o.push({sourceName:u,attributeName:Fn(u),value:h,size:p,format:g,byteOffset:s,byteLength:y.byteLength}),s+=y.byteLength;let x=h.length/p;if(!Number.isInteger(x))throw new Error(`Attribute ${u} length is not divisible by size`);a=Math.min(a,x)}if(o.length===0||!Number.isFinite(a))throw new Error(`Geometry ${r.id} has no interleavable attributes`);let c=jv(s,n),l=new ArrayBuffer(a*c);for(let u of o)FB(l,a,c,u);return new yt({id:r.id,topology:r.topology||"triangle-list",vertexCount:r.vertexCount,indices:r.indices,attributes:{[t]:{value:new Uint8Array(l),size:c,byteStride:c}},bufferLayout:[{name:t,stepMode:"vertex",byteStride:c,attributes:o.map(u=>({attribute:u.attributeName,format:u.format,byteOffset:u.byteOffset}))}]})}function DB(r,e){if(r.bufferLayout.length!==1)return!1;let t=r.bufferLayout[0];return t.name===e&&!!t.attributes?.length&&!!r.attributes[e]}function NB(r,e){return e?e.map(t=>[t,r.attributes[t]]):Object.entries(r.attributes)}function FB(r,e,t,n){let i=n.value.constructor,o=i.BYTES_PER_ELEMENT;if(n.byteOffset%o!==0||t%o!==0)throw new Error(`Attribute ${n.sourceName} is not aligned to its component type`);let s=new i(r),a=n.value,c=n.byteOffset/o,l=t/o;for(let u=0;u<e;u++){let f=u*n.size,h=u*l+c;for(let p=0;p<n.size;p++)s[h+p]=a[f+p]}}function jv(r,e){return Math.ceil(r/e)*e}var Yv=b(()=>{N();Wl()});var UB,GB,Un,qv=b(()=>{UB=1,GB=1,Un=class{constructor(){d(this,"time",0);d(this,"channels",new Map);d(this,"animations",new Map);d(this,"playing",!1);d(this,"lastEngineTime",-1)}addChannel(e){let{delay:t=0,duration:n=Number.POSITIVE_INFINITY,rate:i=1,repeat:o=1}=e,s=UB++,a={time:0,delay:t,duration:n,rate:i,repeat:o};return this._setChannelTime(a,this.time),this.channels.set(s,a),s}removeChannel(e){this.channels.delete(e);for(let[t,n]of this.animations)n.channel===e&&this.detachAnimation(t)}isFinished(e){let t=this.channels.get(e);return t===void 0?!1:this.time>=t.delay+t.duration*t.repeat}getTime(e){if(e===void 0)return this.time;let t=this.channels.get(e);return t===void 0?-1:t.time}setTime(e){this.time=Math.max(0,e);let t=this.channels.values();for(let i of t)this._setChannelTime(i,this.time);let n=this.animations.values();for(let i of n){let{animation:o,channel:s}=i;o.setTime(this.getTime(s))}}play(){this.playing=!0}pause(){this.playing=!1,this.lastEngineTime=-1}reset(){this.setTime(0)}attachAnimation(e,t){let n=GB++;return this.animations.set(n,{animation:e,channel:t}),e.setTime(this.getTime(t)),n}detachAnimation(e){this.animations.delete(e)}update(e){this.playing&&(this.lastEngineTime===-1&&(this.lastEngineTime=e),this.setTime(this.time+(e-this.lastEngineTime)),this.lastEngineTime=e)}_setChannelTime(e,t){let n=t-e.delay,i=e.duration*e.repeat;n>=i?e.time=e.duration*e.rate:(e.time=Math.max(0,n)%e.duration,e.time*=e.rate)}}});function Xv(r){let e=typeof window<"u"?window.requestAnimationFrame||window.webkitRequestAnimationFrame||window.mozRequestAnimationFrame:null;return e?e.call(window,r):setTimeout(()=>r(typeof performance<"u"?performance.now():Date.now()),1e3/60)}function Zv(r){let e=typeof window<"u"?window.cancelAnimationFrame||window.webkitCancelAnimationFrame||window.mozCancelAnimationFrame:null;if(e){e.call(window,r);return}clearTimeout(r)}var Kv=b(()=>{});var zB,$B,Qv,Bs,Os,Jv=b(()=>{N();Kv();Po();zB=0,$B="Animation Loop",Qv={requestAnimationFrame:r=>Xv(r),cancelAnimationFrame:r=>Zv(r)},Bs=class Bs{constructor(e){d(this,"device",null);d(this,"canvas",null);d(this,"props");d(this,"animationProps",null);d(this,"timeline",null);d(this,"stats");d(this,"sharedStats");d(this,"cpuTime");d(this,"gpuTime");d(this,"frameRate");d(this,"display");d(this,"_needsRedraw","initialized");d(this,"_initialized",!1);d(this,"_running",!1);d(this,"_animationFrameId",null);d(this,"_nextFramePromise",null);d(this,"_resolveNextFrame",null);d(this,"_cpuStartTime",0);d(this,"_error",null);d(this,"_lastFrameTime",0);if(this.props={...Bs.defaultAnimationLoopProps,...e},e=this.props,!e.device)throw new Error("No device provided");this.stats=e.stats||new lt({id:`animation-loop-${zB++}`}),this.sharedStats=fi.stats.get($B),this.frameRate=this.stats.get("Frame Rate"),this.frameRate.setSampleSize(1),this.cpuTime=this.stats.get("CPU Time"),this.gpuTime=this.stats.get("GPU Time"),this.setProps({autoResizeViewport:e.autoResizeViewport,animationFrameProvider:e.animationFrameProvider}),this.start=this.start.bind(this),this.stop=this.stop.bind(this),this._onMousemove=this._onMousemove.bind(this),this._onMouseleave=this._onMouseleave.bind(this)}destroy(){this.stop(),this._setDisplay(null),this.device?._disableDebugGPUTime()}delete(){this.destroy()}reportError(e){this._error=e,this.props.onError(e),this.props.onError===Bs.defaultAnimationLoopProps.onError&&typeof window<"u"&&typeof ErrorEvent<"u"&&window.dispatchEvent(new ErrorEvent("error",{error:e,message:e.message}))}setNeedsRedraw(e){return this._needsRedraw=this._needsRedraw||e,this}needsRedraw(){let e=this._needsRedraw;return this._needsRedraw=!1,e}setProps(e){if("autoResizeViewport"in e&&(this.props.autoResizeViewport=e.autoResizeViewport||!1),"animationFrameProvider"in e){let t=e.animationFrameProvider||Qv;if(t!==this.props.animationFrameProvider){let n=this._animationFrameId!==null;n&&this._cancelAnimationFrame(),this.props.animationFrameProvider=t,n&&this._requestAnimationFrame()}}return this}async start(){if(this._running)return this;this._running=!0;try{let e;if(!this._initialized){if(this._initialized=!0,await this._initDevice(),this._initialize(),!this._running)return null;await this.props.onInitialize(this._getAnimationProps())}return this._running?(e!==!1&&(this._cancelAnimationFrame(),this._requestAnimationFrame()),this):null}catch(e){let t=e instanceof Error?e:new Error("Unknown error");throw this.props.onError(t),t}}stop(){if(this._running){let e=this.animationProps;this._cancelAnimationFrame(),this._nextFramePromise=null,this._resolveNextFrame=null,this._running=!1,this._lastFrameTime=0,e&&this.props.onFinalize(e)}return this}redraw(e,t=null){return this.device?.isLost||this._error?this:(this._beginFrameTimers(e),this._setupFrame(),this.animationProps&&(this.animationProps.animationFrame=t),this._updateAnimationProps(),this._renderFrame(this._getAnimationProps()),this._clearNeedsRedraw(),this._resolveNextFrame&&(this._resolveNextFrame(this),this._nextFramePromise=null,this._resolveNextFrame=null),this._endFrameTimers(),this)}attachTimeline(e){return this.timeline=e,this.timeline}detachTimeline(){this.timeline=null}waitForRender(){return this.setNeedsRedraw("waitForRender"),this._nextFramePromise||(this._nextFramePromise=new Promise(e=>{this._resolveNextFrame=e})),this._nextFramePromise}async toDataURL(){if(this.setNeedsRedraw("toDataURL"),await this.waitForRender(),this.canvas instanceof HTMLCanvasElement)return this.canvas.toDataURL();throw new Error("OffscreenCanvas")}_initialize(){this._startEventHandling(),this._initializeAnimationProps(),this._updateAnimationProps(),this._resizeViewport(),this.device?._enableDebugGPUTime()}_setDisplay(e){this.display&&(this.display.destroy(),this.display.animationLoop=null),e&&(e.animationLoop=this),this.display=e}_requestAnimationFrame(){this._running&&(this._animationFrameId=this.props.animationFrameProvider.requestAnimationFrame(this._animationFrame.bind(this)))}_cancelAnimationFrame(){this._animationFrameId!==null&&(this.props.animationFrameProvider.cancelAnimationFrame(this._animationFrameId),this._animationFrameId=null)}_animationFrame(e,t){if(this._running)try{this.redraw(e,t??null),this._requestAnimationFrame()}catch(n){let i=n instanceof Error?n:new Error(String(n));this.reportError(i),this.stop()}}_renderFrame(e){if(this.display){this.display._renderFrame(e);return}let t=this.props.onRender(this._getAnimationProps());this.device&&t!==!1&&this.device.submit()}_clearNeedsRedraw(){this._needsRedraw=!1}_setupFrame(){this._resizeViewport()}_initializeAnimationProps(){let e=this.device?.getDefaultCanvasContext();if(!this.device||!e)throw new Error("loop");let t=e?.canvas,n=e.props.useDevicePixels;this.animationProps={animationLoop:this,device:this.device,canvasContext:e,canvas:t,useDevicePixels:n,timeline:this.timeline,needsRedraw:!1,width:1,height:1,aspect:1,time:0,startTime:Date.now(),engineTime:0,tick:0,tock:0,animationFrame:null,_mousePosition:null}}_getAnimationProps(){if(!this.animationProps)throw new Error("animationProps");return this.animationProps}_updateAnimationProps(){if(!this.animationProps)return;let{width:e,height:t,aspect:n}=this._getSizeAndAspect();(e!==this.animationProps.width||t!==this.animationProps.height)&&this.setNeedsRedraw("drawing buffer resized"),n!==this.animationProps.aspect&&this.setNeedsRedraw("drawing buffer aspect changed"),this.animationProps.width=e,this.animationProps.height=t,this.animationProps.aspect=n,this.animationProps.needsRedraw=this._needsRedraw,this.animationProps.engineTime=Date.now()-this.animationProps.startTime,this.timeline&&this.timeline.update(this.animationProps.engineTime),this.animationProps.tick=Math.floor(this.animationProps.time/1e3*60),this.animationProps.tock++,this.animationProps.time=this.timeline?this.timeline.getTime():this.animationProps.engineTime}async _initDevice(){if(this.device=await this.props.device,!this.device)throw new Error("No device provided");this.canvas=this.device.getDefaultCanvasContext().canvas||null}_createInfoDiv(){if(this.canvas&&this.props.onAddHTML){let e=document.createElement("div");document.body.appendChild(e),e.style.position="relative";let t=document.createElement("div");t.style.position="absolute",t.style.left="10px",t.style.bottom="10px",t.style.width="300px",t.style.background="white",this.canvas instanceof HTMLCanvasElement&&e.appendChild(this.canvas),e.appendChild(t);let n=this.props.onAddHTML(t);n&&(t.innerHTML=n)}}_getSizeAndAspect(){if(!this.device)return{width:1,height:1,aspect:1};let[e,t]=this.device.getDefaultCanvasContext().getDrawingBufferSize(),n=e>0&&t>0?e/t:1;return{width:e,height:t,aspect:n}}_resizeViewport(){this.props.autoResizeViewport&&this.device.gl&&this.device.gl.viewport(0,0,this.device.gl.drawingBufferWidth,this.device.gl.drawingBufferHeight)}_beginFrameTimers(e){let t=e??(typeof performance<"u"?performance.now():Date.now());if(this._lastFrameTime){let n=t-this._lastFrameTime;n>0&&this.frameRate.addTime(n)}this._lastFrameTime=t,this.device?._isDebugGPUTimeEnabled()&&this._consumeEncodedGpuTime(),this.cpuTime.timeStart()}_endFrameTimers(){this.device?._isDebugGPUTimeEnabled()&&this._consumeEncodedGpuTime(),this.cpuTime.timeEnd(),this._updateSharedStats()}_consumeEncodedGpuTime(){if(!this.device)return;let e=this.device.commandEncoder._gpuTimeMs;e!==void 0&&(this.gpuTime.addTime(e),this.device.commandEncoder._gpuTimeMs=void 0)}_updateSharedStats(){if(this.stats!==this.sharedStats){for(let e of Object.keys(this.sharedStats.stats))this.stats.stats[e]||delete this.sharedStats.stats[e];this.stats.forEach(e=>{let t=this.sharedStats.get(e.name,e.type);t.sampleSize=e.sampleSize,t.time=e.time,t.count=e.count,t.samples=e.samples,t.lastTiming=e.lastTiming,t.lastSampleTime=e.lastSampleTime,t.lastSampleCount=e.lastSampleCount,t._count=e._count,t._time=e._time,t._samples=e._samples,t._startTime=e._startTime,t._timerPending=e._timerPending})}}_startEventHandling(){this.canvas&&(this.canvas.addEventListener("mousemove",this._onMousemove.bind(this)),this.canvas.addEventListener("mouseleave",this._onMouseleave.bind(this)))}_onMousemove(e){e instanceof MouseEvent&&(this._getAnimationProps()._mousePosition=[e.offsetX,e.offsetY])}_onMouseleave(e){this._getAnimationProps()._mousePosition=null}};d(Bs,"defaultAnimationLoopProps",{device:null,onAddHTML:()=>"",onInitialize:async()=>null,onRender:()=>{},onFinalize:()=>{},onError:e=>{console.error(e)},stats:void 0,autoResizeViewport:!1,animationFrameProvider:Qv});Os=Bs});function ew(r,e){if(e instanceof jl)return e;let t=Hv(e),n=VB(r,t),{attributes:i,bufferLayout:o}=WB(r,t);return new jl({topology:t.topology||"triangle-list",bufferLayout:o,vertexCount:t.vertexCount,indices:n,attributes:i})}function VB(r,e){if(!e.indices)return;let t=e.indices.value;return r.createBuffer({usage:z.INDEX,data:t})}function WB(r,e){let t={};for(let[n,i]of Object.entries(e.attributes)){let o=e.bufferLayout.find(s=>s.name===n)?.name||Fn(n);i&&(t[o]=r.createBuffer({data:i.value,id:`${n}-buffer`}))}return{attributes:t,bufferLayout:e.bufferLayout,vertexCount:e.vertexCount}}var jl,tw=b(()=>{N();Wl();Yv();zi();jl=class{constructor(e){d(this,"id");d(this,"userData",{});d(this,"topology");d(this,"bufferLayout",[]);d(this,"vertexCount");d(this,"indices");d(this,"attributes");if(this.id=e.id||Xt("geometry"),this.topology=e.topology,this.indices=e.indices||null,this.attributes=e.attributes,this.vertexCount=e.vertexCount,this.bufferLayout=e.bufferLayout||[],this.indices&&!(this.indices.usage&z.INDEX))throw new Error("Index buffer must have INDEX usage")}destroy(){this.indices?.destroy();for(let e of Object.values(this.attributes))e.destroy()}getVertexCount(){return this.vertexCount}getAttributes(){return this.attributes}getIndexes(){return this.indices||null}_calculateVertexCount(e){return e.byteLength/12}}});function rw(r,e){let t={},n="Values";if(r.attributes.length===0&&!r.varyings?.length)return{"No attributes or varyings":{[n]:"N/A"}};for(let i of r.attributes)if(i){let o=`${i.location} ${i.name}: ${i.type}`;t[`in ${o}`]={[n]:i.stepMode||"vertex"}}for(let i of r.varyings||[]){let o=`${i.location} ${i.name}`;t[`out ${o}`]={[n]:JSON.stringify(i)}}return t}var nw=b(()=>{});function ow(r,e,t){if(r.device.type!=="webgl")return;let n=YB(r.device);if(!n.flushing){if(XB(r)){jB(r,t,n);return}e&&qB(e)&&e.handle!==null&&(n.queuedFramebuffers.includes(e)||n.queuedFramebuffers.push(e))}}function jB(r,e,t){if(t.queuedFramebuffers.length===0)return;let n=r.device,{gl:i}=n,o=i.getParameter(36010),s=i.getParameter(36006),[a,c]=r.device.getDefaultCanvasContext().getDrawingBufferSize(),l=iw(e.top,8),u=iw(e.left,8);t.flushing=!0;try{for(let f of t.queuedFramebuffers){let[h,p,m,g,y]=HB({framebuffer:f,targetWidth:a,targetHeight:c,topPx:l,leftPx:u,minimap:e.minimap});i.bindFramebuffer(36008,f.handle),i.bindFramebuffer(36009,null),i.blitFramebuffer(0,0,f.width,f.height,h,p,m,g,16384,9728),l+=y+8}}finally{i.bindFramebuffer(36008,o),i.bindFramebuffer(36009,s),t.flushing=!1}}function HB(r){let{framebuffer:e,targetWidth:t,targetHeight:n,topPx:i,leftPx:o,minimap:s}=r,a=s?Math.max(Math.floor(t/4),1):t,c=s?Math.max(Math.floor(n/4),1):n,l=Math.min(a/e.width,c/e.height),u=Math.max(Math.floor(e.width*l),1),f=Math.max(Math.floor(e.height*l),1),h=o,p=Math.max(n-i-f,0),m=h+u,g=p+f;return[h,p,m,g,f]}function YB(r){var e;return(e=r.userData)[Hl]||(e[Hl]={flushing:!1,queuedFramebuffers:[]}),r.userData[Hl]}function qB(r){return"colorAttachments"in r}function XB(r){let e=r.props.framebuffer;return!e||e.handle===null}function iw(r,e){if(!r)return e;let t=Number.parseInt(r,10);return Number.isFinite(t)?t:e}var Hl,sw=b(()=>{Hl="__debugFramebufferState"});function $i(r,e,t){if(r===e)return!0;if(!t||!r||!e)return!1;if(Array.isArray(r)){if(!Array.isArray(e)||r.length!==e.length)return!1;for(let n=0;n<r.length;n++)if(!$i(r[n],e[n],t-1))return!1;return!0}if(Array.isArray(e))return!1;if(typeof r=="object"&&typeof e=="object"){let n=Object.keys(r),i=Object.keys(e);if(n.length!==i.length)return!1;for(let o of n)if(!e.hasOwnProperty(o)||!$i(r[o],e[o],t-1))return!1;return!0}return!1}var aw=b(()=>{});var Vi,cw=b(()=>{N();Vi=class{constructor(e){d(this,"bufferLayouts");this.bufferLayouts=e}getBufferLayout(e){return this.bufferLayouts.find(t=>t.name===e)||null}getAttributeNamesForBuffer(e){return _i(e)}mergeBufferLayouts(e,t){let n=[...e];for(let i of t){let o=n.findIndex(s=>s.name===i.name);o<0?n.push(i):n[o]=i}return n}}});function lw(r,e){let t=_h(r),n=e.slice();return n.sort((i,o)=>{let s=tl(_i(i).map(c=>t[c])),a=tl(_i(o).map(c=>t[c]));return s-a}),n}var uw=b(()=>{N()});function Wi(r,e){if(!r||!e.some(n=>n.bindingLayout?.length))return r;let t={...r,bindings:r.bindings.map(n=>({...n}))};"attributes"in(r||{})&&(t.attributes=r?.attributes||[]);for(let n of e)for(let i of n.bindingLayout||[])for(let o of ZB(i.name)){let s=t.bindings.find(a=>a.name===o);s?.group===0&&(s.group=i.group),s&&i.visibility!==void 0&&(s.visibility=i.visibility)}return t}function fw(r,e,t=[]){return r?e?{...r,attributes:r.attributes.length?JB(r.attributes,e.attributes.filter(n=>t.includes(n.name))):e.attributes,bindings:QB(r.bindings,e.bindings)}:r:e}function ks(r){return!!(r.uniformTypes&&!KB(r.uniformTypes))}function dw(r){let e=[];for(let t of r){let n=as(t),i=new Set([t.vs,t.fs].flatMap(s=>s?cs(s).filter(a=>a.isStd140).map(a=>a.blockName):[])),o=i.has(n)?n:i.size===1?i.values().next().value:void 0;ks(t)&&o&&e.push({name:o,uniformTypes:t.uniformTypes})}return e}function Yl(r,e){let t=[],n=new Set;for(let i of[...r||[],...e||[]])n.has(i.name)||(n.add(i.name),t.push(i));return t}function ZB(r){let e=new Set([r,`${r}Uniforms`]);return r.endsWith("Uniforms")||e.add(`${r}Sampler`),[...e]}function KB(r){for(let e in r)return!1;return!0}function QB(r,e){let t=r.map(o=>({...o})),n=new Set(r.map(o=>o.name)),i=new Set(r.map(o=>`${o.group}:${o.location}`));for(let o of e){let s=`${o.group}:${o.location}`;!n.has(o.name)&&!i.has(s)&&t.push({...o})}return t}function JB(r,e){let t=r.map(o=>({...o})),n=new Map(r.map(o=>[o.name,o])),i=new Map(r.map(o=>[o.location,o]));for(let o of e){let s=n.get(o.name);if(s){if(s.type!==o.type||s.location!==o.location)throw new Error(`Shader attribute "${o.name}" conflicts with its inferred type or location`);continue}let a=i.get(o.location);if(a)throw new Error(`Shader attributes "${a.name}" and "${o.name}" both use location ${o.location}`);t.push({...o})}return t}var Xp=b(()=>{qe()});function eO(r){return Ro(r)||typeof r=="number"||typeof r=="boolean"}function hw(r,e={}){let t={bindings:{},uniforms:{}};return Object.keys(r).forEach(n=>{let i=r[n];Object.prototype.hasOwnProperty.call(e,n)||eO(i)?t.uniforms[n]=i:t.bindings[n]=i}),t}var pw=b(()=>{bd()});function mw(r={},e={},t={}){let n={...r};for(let[i,o]of Object.entries(e))o!==void 0&&(n[i]=Zp(r[i],o,t[i]));return n}function Zp(r,e,t){if(!t||typeof t=="string")return Ds(e);if(Array.isArray(t)){if(Kp(e)||!Array.isArray(e))return Ds(e);let s=Array.isArray(r)&&!Kp(r)?[...r]:[],a=s.slice();for(let c=0;c<e.length;c++){let l=e[c];l!==void 0&&(a[c]=Zp(s[c],l,t[0]))}return a}if(!Qp(e))return Ds(e);let n=t,i=Qp(r)?r:{},o={...i};for(let[s,a]of Object.entries(e))a!==void 0&&(o[s]=Zp(i[s],a,n[s]));return o}function Ds(r){return ArrayBuffer.isView(r)?Array.prototype.slice.call(r):Array.isArray(r)?Kp(r)?r.slice():r.map(t=>t===void 0?void 0:Ds(t)):Qp(r)?Object.fromEntries(Object.entries(r).map(([e,t])=>[e,t===void 0?void 0:Ds(t)])):r}function Kp(r){return ArrayBuffer.isView(r)||Array.isArray(r)&&(r.length===0||typeof r[0]=="number")}function Qp(r){return!!r&&typeof r=="object"&&!Array.isArray(r)&&!ArrayBuffer.isView(r)}function tO(r){return!!r?.dependencies}var ji,Jp=b(()=>{N();qe();pw();ji=class{constructor(e,t){d(this,"options",{disableWarnings:!1});d(this,"modules");d(this,"moduleUniforms");d(this,"moduleBindings");d(this,"directBindings",{});Object.assign(this.options,t);let n=fn(Object.values(e).filter(tO));for(let i of n)e[i.name]=i;T.log(1,"Creating ShaderInputs with modules",Object.keys(e))(),this.modules=e,this.moduleUniforms={},this.moduleBindings={};for(let[i,o]of Object.entries(e))o&&(this._addModule(o),o.name&&i!==o.name&&!this.options.disableWarnings&&T.warn(`Module name: ${i} vs ${o.name}`)())}destroy(){}setProps(e){e.bindings&&Object.assign(this.directBindings,e.bindings);for(let t of Object.keys(e)){if(t==="bindings")continue;let n=t,i=e[n]||{},o=this.modules[n];if(!o)this.options.disableWarnings||T.warn(`Module ${t} not found`)();else{let s=this.moduleUniforms[n],a=this.moduleBindings[n],c=o.getUniforms?.(i,s)||i,{uniforms:l,bindings:u}=hw(c,o.uniformTypes);this.moduleUniforms[n]=mw(s,l,o.uniformTypes),this.moduleBindings[n]={...a,...u}}}}getModules(){return Object.values(this.modules)}addModules(e){let t=fn(e);for(let n of t){let i=n.name;this.modules[i]||(this.modules[i]=n,this._addModule(n))}}getUniformValues(){return this.moduleUniforms}getBindingValues(){let e={};for(let t of Object.values(this.moduleBindings))Object.assign(e,t);return Object.assign(e,this.directBindings),e}getModuleBindingValues(e){let t=this.moduleBindings[e];return t?{...t}:{}}getDebugTable(){let e={};for(let[t,n]of Object.entries(this.moduleUniforms))for(let[i,o]of Object.entries(n))e[`${t}.${i}`]={type:this.modules[t].uniformTypes?.[i],value:String(o)};return e}_addModule(e){let t=e.name;this.moduleUniforms[t]=mw({},e.defaultUniforms||{},e.uniformTypes),this.moduleBindings[t]={}}}});function em(r){return r!==null&&typeof r=="object"&&"buffer"in r}function nO(r){return r instanceof Ie?r.buffer:r}function gw(r){return{buffer:nO(r.buffer),offset:r.offset,size:r.size}}var rO,Ie,tm=b(()=>{N();zi();rO=z.DEBUG_DATA_MAX_LENGTH,Ie=class{constructor(e,t){d(this,"device");d(this,"id");d(this,"ready");d(this,"usage");d(this,"props");d(this,"isReady",!0);d(this,"destroyed",!1);d(this,"generation",0);d(this,"updateTimestamp");d(this,"debugData",new ArrayBuffer(0));d(this,"_debugDataEnabled");d(this,"_maxDebugDataByteLength");d(this,"_ownsBuffer");d(this,"_buffer");let{debugData:n=!1,buffer:i,ownsBuffer:o=!0,...s}=t;if(i&&i.device!==e)throw new Error("DynamicBuffer adopted buffers must belong to the supplied device");if(i&&(s.byteLength!==void 0||s.data!==void 0))throw new Error("DynamicBuffer cannot combine an adopted buffer with byteLength or data");let a=t.id||i?.id||Xt("dynamic-buffer"),c={...s,id:a,usage:s.usage??i?.usage,indexType:s.indexType??i?.indexType};(c.usage||0)&z.INDEX&&!c.indexType&&(s.data instanceof Uint32Array?c.indexType="uint32":s.data instanceof Uint16Array?c.indexType="uint16":s.data instanceof Uint8Array&&(c.indexType="uint8")),delete c.data,delete c.byteOffset,this.device=e,this.id=a,this.props=c,this.usage=c.usage||0,this._debugDataEnabled=!!n,this._maxDebugDataByteLength=typeof n=="object"&&n.maxByteLength!==void 0?n.maxByteLength:rO,this._ownsBuffer=o,this._buffer=i??this.device.createBuffer({...s,id:a}),this.ready=Promise.resolve(this._buffer),this.updateTimestamp=this._buffer.updateTimestamp,this._resetDebugData(this._buffer.byteLength),s.data&&this._writeDebugData(s.data,s.byteOffset||0)}get buffer(){return this._buffer}get byteLength(){return this._buffer.byteLength}get[Symbol.toStringTag](){return"DynamicBuffer"}toString(){return`DynamicBuffer:"${this.id}":${this.byteLength}B`}toJSON(){return this.toString()}write(e,t=0){this._buffer.write(e,t),this._touch(),this._writeDebugData(e,t)}async mapAndWriteAsync(e,t=0,n=this.byteLength-t){let i=null;await this._buffer.mapAndWriteAsync(async(o,s)=>{await e(o,s),i=new Uint8Array(o.slice(0,n))},t,n),this._touch(),i&&this._writeDebugData(i,t)}async readAsync(e=0,t=this.byteLength-e){let n=await this._buffer.readAsync(e,t);return this._writeDebugData(n,e)&&this._touch(),n}async mapAndReadAsync(e,t=0,n=this.byteLength-t){let i=null,o=await this._buffer.mapAndReadAsync(async(s,a)=>(i=new Uint8Array(s.slice(0)),await e(s,a)),t,n);return i&&this._writeDebugData(i,t)&&this._touch(),o}resize(e){let{byteLength:t,preserveData:n=!1}=e;if(t===this.byteLength)return!1;let i=Math.min(e.copyByteLength??Math.min(this.byteLength,t),this.byteLength,t),o=this._buffer,s=this.debugData.slice(0),{data:a,byteOffset:c,...l}=this.props,u=this.device.createBuffer({...l,byteLength:t});return n&&i>0&&this._copyBufferContents(o,u,i),this._buffer=u,this._resetDebugData(t),n&&s.byteLength>0&&this._writeDebugData(s,0),this._ownsBuffer&&o.destroy(),this._ownsBuffer=!0,this.generation++,this._touch(),!0}ensureSize(e,t){return e<=this.byteLength?!1:this.resize({byteLength:e,preserveData:t?.preserveData})}getBinding(e){return e?.offset===void 0&&e?.size===void 0?this._buffer:{buffer:this._buffer,offset:e?.offset,size:e?.size}}destroy(){this.destroyed||(this._ownsBuffer&&this._buffer.destroy(),this.destroyed=!0,this.debugData=new ArrayBuffer(0))}_copyBufferContents(e,t,n){let i=this.device.type==="webgpu"?Math.ceil(n/4)*4:n,o=this.device.createCommandEncoder();o.copyBufferToBuffer({sourceBuffer:e,destinationBuffer:t,size:i}),this.device.submit(o.finish())}_touch(){this.updateTimestamp=this.device.incrementTimestamp()}_resetDebugData(e){if(!this._debugDataEnabled){this.debugData=new ArrayBuffer(0);return}this.debugData=new ArrayBuffer(Math.min(e,this._maxDebugDataByteLength))}_writeDebugData(e,t){if(!this._debugDataEnabled||this.debugData.byteLength===0||t>=this.debugData.byteLength)return!1;let n=ArrayBuffer.isView(e)?new Uint8Array(e.buffer,e.byteOffset,e.byteLength):new Uint8Array(e),i=new Uint8Array(this.debugData),o=Math.min(n.byteLength,i.byteLength-t);return i.set(n.subarray(0,o),t),o>0}}});function Ns(r){return r!==null&&typeof r=="object"&&"resolveTextureBinding"in r&&typeof r.resolveTextureBinding=="function"}function iO(r){return r?.type==="texture"||r?.type==="external-texture"}function yw(r,e,t){let n=Vc(r,e,{ignoreWarnings:!0});return iO(n)?n:r.bindings.length===0&&t?.fallbackGroup!==void 0?{type:"texture",name:e,group:t.fallbackGroup,location:0}:null}var _w=b(()=>{N()});function nm(r,e){return r.shaderLanguage!==void 0&&r.shaderLanguage!==e?!1:e==="glsl"?"assembleGLSLShaderPair"in r&&typeof r.assembleGLSLShaderPair=="function":"assembleWGSLShader"in r&&typeof r.assembleWGSLShader=="function"}function aO(r,e){return!r||Object.keys(e).length===0?r:{...r,attributes:r.attributes.map(t=>{let n=t.name.startsWith("_luma_")?t.name.slice(6):null;return n&&e[n]?{...t,name:n}:t})}}function cO(r,e,t){if(Ns(e)){let n=yw(t,r,{fallbackGroup:0});return n?e.resolveTextureBinding(n):null}return e instanceof Ie?e.buffer:em(e)?gw(e):e}function lO(r){return r&&!bw(r)?r:null}function uO(r){return r&&bw(r)?r:void 0}function bw(r){return sO.includes(r)}function fO(r){return{type:r.type,shaderLanguage:r.info.shadingLanguage,shaderLanguageVersion:r.info.shadingLanguageVersion,gpu:r.info.gpu,limits:r.limits,features:r.features}}var Zt,oO,rm,sO,Fs,Re,im=b(()=>{N();qe();tw();nw();sw();aw();cw();uw();Xp();zi();Jp();tm();_w();Zt=2,oO=1e4,rm="render pipeline initialization failed",sO=["stencil8","depth16unorm","depth24plus","depth24plus-stencil8","depth32float","depth32float-stencil8"],Fs=class Fs{constructor(e,t){d(this,"device");d(this,"id");d(this,"source");d(this,"vs");d(this,"fs");d(this,"pipelineFactory");d(this,"shaderFactory");d(this,"userData",{});d(this,"parameters");d(this,"topology");d(this,"bufferLayout");d(this,"isInstanced");d(this,"instanceCount",0);d(this,"vertexCount");d(this,"indexCount");d(this,"firstVertex");d(this,"firstIndex");d(this,"indexBuffer",null);d(this,"bufferAttributes",{});d(this,"constantAttributes",{});d(this,"bindings",{});d(this,"vertexArray");d(this,"transformFeedback",null);d(this,"pipeline");d(this,"shaderInputs");d(this,"material",null);d(this,"_uniformStore");d(this,"_attributeInfos",{});d(this,"_gpuGeometry",null);d(this,"props");d(this,"_dynamicIndexBufferSource",null);d(this,"_dynamicAttributeBufferSources",{});d(this,"_colorAttachmentFormats");d(this,"_depthStencilAttachmentFormat");d(this,"_pipelineNeedsUpdate","newly created");d(this,"_needsRedraw","initializing");d(this,"_drawBlockedReason",!1);d(this,"_destroyed",!1);d(this,"_lastDrawTimestamp",-1);d(this,"_bindingTable",[]);d(this,"_lastLogTime",0);d(this,"_logOpen",!1);d(this,"_drawCount",0);let n=Fs.defaultProps.shaderAssembler;this.props={...Fs.defaultProps,...t,shaderAssembler:t.shaderAssembler??(nm(n,e.info.shadingLanguage)?n:dt.getDefaultShaderAssembler(e.info.shadingLanguage))},t=this.props,this.id=t.id||Xt("model"),this.device=e,Object.assign(this.userData,t.userData),this.material=t.material||null;let i=fO(e),o=os(this.props.plugins,i.shaderLanguage),s=ss(this.props.modules,o.modules),a=Object.fromEntries(s.map(h=>[h.name,h])),c=t.shaderInputs||new ji(a,{disableWarnings:this.props.disableWarnings});t.shaderInputs&&o.modules.length>0&&c.addModules(o.modules),this.setShaderInputs(c);let l=Yl(this.props.modules,c.getModules()),u={...o.defines,...this.props.defines};if(this.device.type==="webgl"&&(this.props._uniformBlockLayouts=dw(l)),this.props.shaderLayout=Wi(this.props.shaderLayout,l)||null,this.device.type==="webgpu"&&this.props.source){let h=this.props.shaderAssembler;Rr(nm(h,"wgsl"));let{source:p,getUniforms:m,bindingTable:g,shaderLayout:y}=h.assembleWGSLShader({platformInfo:i,...this.props,modules:l,defines:u,pluginInjections:o.injections,pluginVertexInputs:o.vertexInputs,pluginVaryings:o.varyings});this.source=p,this._getModuleUniforms=m,this._bindingTable=g;let x=y??e.getShaderLayout?.(this.source),v=aO(x,o.vertexInputs),_=fw(this.props.shaderLayout,v,Object.keys(o.vertexInputs));this.props.shaderLayout=Wi(_||null,l)||null}else{let h=this.props.shaderAssembler;Rr(nm(h,"glsl"));let{vs:p,fs:m,getUniforms:g}=h.assembleGLSLShaderPair({platformInfo:i,...this.props,modules:l,defines:u,pluginInjections:o.injections,pluginVertexInputs:o.vertexInputs,pluginVaryings:o.varyings});this.vs=p,this.fs=m,this._getModuleUniforms=g,this._bindingTable=[]}this.vertexCount=this.props.vertexCount,this.indexCount=this.props.indexCount,this.firstVertex=this.props.firstVertex,this.firstIndex=this.props.firstIndex,this.instanceCount=this.props.instanceCount,this.topology=this.props.topology,this.bufferLayout=this.props.bufferLayout,this.parameters=this.props.parameters,this._colorAttachmentFormats=this.props.colorAttachmentFormats,this._depthStencilAttachmentFormat=this.props.depthStencilAttachmentFormat,t.geometry&&this.setGeometry(t.geometry),this.pipelineFactory=t.pipelineFactory||_n.getDefaultPipelineFactory(this.device),this.shaderFactory=t.shaderFactory||bn.getDefaultShaderFactory(this.device),this.pipeline=this._updatePipeline(),this.vertexArray=e.createVertexArray({shaderLayout:this.pipeline.shaderLayout,bufferLayout:this.pipeline.bufferLayout}),this._gpuGeometry&&this._setGeometryAttributes(this._gpuGeometry),"isInstanced"in t&&(this.isInstanced=t.isInstanced),t.instanceCount&&this.setInstanceCount(t.instanceCount),t.vertexCount&&this.setVertexCount(t.vertexCount),t.indexBuffer&&this.setIndexBuffer(t.indexBuffer),t.attributes&&this.setAttributes(t.attributes),t.constantAttributes&&this.setConstantAttributes(t.constantAttributes),t.bindings&&this.setBindings(t.bindings),t.transformFeedback&&(this.transformFeedback=t.transformFeedback)}get[Symbol.toStringTag](){return"Model"}toString(){return`Model(${this.id})`}destroy(){this._destroyed||(this.pipelineFactory.release(this.pipeline),this.shaderFactory.release(this.pipeline.vs),this.pipeline.fs&&this.pipeline.fs!==this.pipeline.vs&&this.shaderFactory.release(this.pipeline.fs),this._uniformStore.destroy(),this._gpuGeometry?.destroy(),this._destroyed=!0)}needsRedraw(){this._getBindingsUpdateTimestamp()>this._lastDrawTimestamp&&this.setNeedsRedraw("contents of bound textures or buffers updated");let e=this._needsRedraw;return this._needsRedraw=!1,e}setNeedsRedraw(e){this._needsRedraw||(this._needsRedraw=e)}getBindingDebugTable(){return this._bindingTable}predraw(e){this._syncDynamicBuffers(),this.updateShaderInputs(e),this.material?.updateShaderInputs(e),this.pipeline=this._updatePipeline()}draw(e){if(this._drawBlockedReason&&!this._pipelineNeedsUpdate)return T.info(Zt,`>>> DRAWING ABORTED ${this.id}: ${this._drawBlockedReason}`)(),!1;let t=this._areBindingsLoading();if(t)return T.info(Zt,`>>> DRAWING ABORTED ${this.id}: ${t} not loaded`)(),!1;this._syncAttachmentFormats(e);try{e.pushDebugGroup(`${this}.predraw(${e})`),this.device.type==="webgpu"?(this.updateShaderInputs(),this.material?.updateShaderInputs(),this._syncDynamicBuffers(),this.pipeline=this._updatePipeline()):this.predraw(this.device.commandEncoder)}finally{e.popDebugGroup()}let n,i=this.pipeline.isErrored;try{if(e.pushDebugGroup(`${this}.draw(${e})`),this._logDrawCallStart(),this.pipeline=this._updatePipeline(),i=this.pipeline.isErrored,i)T.info(Zt,`>>> DRAWING ABORTED ${this.id}: ${rm}`)(),n=!1;else{let o=this.vertexArray.getDrawValidationError();if(o)T.info(Zt,`>>> DRAWING ABORTED ${this.id}: ${o}`)(),this._drawBlockedReason=o,n=!1;else{let s=this._getCurrentShaderLayout(),a=this._getBindings(s),c=this._getBindGroups(s,a),{indexBuffer:l}=this.vertexArray,u=l?this.indexCount??l.byteLength/(l.indexType==="uint32"?4:2):void 0;e.setPipeline(this.pipeline),e.setBindings(c,{_bindGroupCacheKeys:this._getBindGroupCacheKeys()}),e.setVertexArray(this.vertexArray),n=this.isInstanced===!0&&this.instanceCount===0?!0:e.draw({isInstanced:this.isInstanced,vertexCount:this.vertexCount,instanceCount:this.isInstanced?this.instanceCount:void 0,indexCount:u,firstVertex:this.firstVertex,firstIndex:this.firstIndex,transformFeedback:this.transformFeedback||void 0,uniforms:this.props.uniforms,parameters:this.parameters,topology:this.topology})}}}finally{e.popDebugGroup(),this._logDrawCallEnd()}return this._logFramebuffer(e),n?(this._lastDrawTimestamp=this.device.timestamp,this._needsRedraw=!1):i?(this._needsRedraw=rm,this._drawBlockedReason=rm):this._drawBlockedReason?this._needsRedraw=this._drawBlockedReason:this._needsRedraw="waiting for resource initialization",n}setGeometry(e){this._gpuGeometry?.destroy();let t=e&&ew(this.device,e);if(t){this.setTopology(t.topology||"triangle-list");let n=new Vi(this.bufferLayout);this.bufferLayout=n.mergeBufferLayouts(t.bufferLayout,this.bufferLayout),this.vertexArray&&this._setGeometryAttributes(t)}this._gpuGeometry=t}setTopology(e){e!==this.topology&&(this.topology=e,this._setPipelineNeedsUpdate("topology"))}setBufferLayout(e){let t=new Vi(this.bufferLayout),n=this._gpuGeometry?t.mergeBufferLayouts(e,this._gpuGeometry.bufferLayout):e;$i(n,this.bufferLayout,-1)||(this.bufferLayout=n,this._setPipelineNeedsUpdate("bufferLayout"),this.pipeline=this._updatePipeline(),this.vertexArray=this.device.createVertexArray({shaderLayout:this.pipeline.shaderLayout,bufferLayout:this.pipeline.bufferLayout}),this._gpuGeometry&&this._setGeometryAttributes(this._gpuGeometry))}setParameters(e){$i(e,this.parameters,2)||(this.parameters=e,this._setPipelineNeedsUpdate("parameters"))}setInstanceCount(e){this.instanceCount=e,this.isInstanced===void 0&&e>0&&(this.isInstanced=!0),this.setNeedsRedraw("instanceCount")}setVertexCount(e){this.vertexCount=e,this.setNeedsRedraw("vertexCount")}setIndexCount(e){this.indexCount=e,this.setNeedsRedraw("indexCount")}setDrawOffsets({firstVertex:e,firstIndex:t}){this.firstVertex=e,this.firstIndex=t,this.setNeedsRedraw("drawOffsets")}setShaderInputs(e){this.shaderInputs=e,this._uniformStore=new wn(this.device,this.shaderInputs.modules);for(let[t,n]of Object.entries(this.shaderInputs.modules))if(ks(n)&&!this.material?.ownsModule(t)){let i=this._uniformStore.getManagedUniformBuffer(t);this.bindings[`${t}Uniforms`]=i}this.setNeedsRedraw("shaderInputs")}setMaterial(e){this.material=e,this.setNeedsRedraw("material")}updateShaderInputs(e){this._uniformStore.setUniforms(this.shaderInputs.getUniformValues(),e),this.setBindings(this._getNonMaterialBindings(this.shaderInputs.getBindingValues())),this.setNeedsRedraw("shaderInputs")}setBindings(e){Object.assign(this.bindings,e),this.setNeedsRedraw("bindings")}setTransformFeedback(e){this.transformFeedback=e,this.setNeedsRedraw("transformFeedback")}setIndexBuffer(e){let t=e instanceof Ie?e.buffer:e;this.indexBuffer=t,this._dynamicIndexBufferSource=e instanceof Ie?{source:e,generation:e.generation}:null,this.vertexArray.setIndexBuffer(t),this.setNeedsRedraw("indexBuffer")}setAttributes(e,t){this._drawBlockedReason=!1;let n=t?.disableWarnings??this.props.disableWarnings;e.indices&&T.warn(`Model:${this.id} setAttributes() - indexBuffer should be set using setIndexBuffer()`)(),this.bufferLayout=lw(this.pipeline.shaderLayout,this.bufferLayout);let i=new Vi(this.bufferLayout);for(let[o,s]of Object.entries(e)){let a=s instanceof Ie?s.buffer:s,c=i.getBufferLayout(o);if(!c){n||T.warn(`Model(${this.id}): Missing layout for buffer "${o}".`)();continue}let l=i.getAttributeNamesForBuffer(c),u=!1;for(let f of l){let h=this._attributeInfos[f];if(h){let p=this.device.type==="webgpu"?this.vertexArray.getBufferSlot(h.bufferName):h.location;if(p===null){n||T.warn(`Model(${this.id}): Missing vertex array slot for buffer "${h.bufferName}".`)();continue}this.vertexArray.setBuffer(p,a),s instanceof Ie?this._dynamicAttributeBufferSources[p]={source:s,generation:s.generation}:delete this._dynamicAttributeBufferSources[p],u=!0}}!u&&!n&&T.warn(`Model(${this.id}): Ignoring buffer "${a.id}" for unknown attribute "${o}"`)()}this.setNeedsRedraw("attributes")}setConstantAttributes(e,t){for(let[n,i]of Object.entries(e)){let o=this._attributeInfos[n];o?this.vertexArray.setConstantWebGL(o.location,i):(t?.disableWarnings??this.props.disableWarnings)||T.warn(`Model "${this.id}: Ignoring constant supplied for unknown attribute "${n}"`)()}this.setNeedsRedraw("constants")}_areBindingsLoading(){for(let e of Object.values(this.bindings))if(Ns(e)&&!e.isReady)return e.id;for(let e of Object.values(this.material?.bindings||{}))if(Ns(e)&&!e.isReady)return e.id;return!1}_getBindings(e=this._getCurrentShaderLayout()){let t={};for(let[n,i]of Object.entries(this.bindings)){let o=cO(n,i,e);o&&(t[n]=o)}return t}_getBindGroups(e=this._getCurrentShaderLayout(),t=this._getBindings(e)){let n=e.bindings.length?xn(e,t):{0:t};if(!this.material)return n;for(let[i,o]of Object.entries(this.material.getBindingsByGroup(e))){let s=Number(i);n[s]={...n[s]||{},...o}}return n}_getBindGroupCacheKeys(){let e=this.material?.getBindGroupCacheKey(3);return e?{3:e}:{}}_getBindingsUpdateTimestamp(){let e=0;this._dynamicIndexBufferSource&&(e=Math.max(e,this._dynamicIndexBufferSource.source.updateTimestamp));for(let t of Object.values(this._dynamicAttributeBufferSources))e=Math.max(e,t.source.updateTimestamp);for(let t of Object.values(this.bindings))t instanceof mn?e=Math.max(e,t.texture.updateTimestamp):t instanceof z||t instanceof Y||t instanceof Yo||t instanceof Ie?e=Math.max(e,t.updateTimestamp):Ns(t)?e=t.isReady?Math.max(e,t.updateTimestamp):1/0:em(t)&&(e=Math.max(e,(t.buffer instanceof Ie,t.buffer.updateTimestamp)));return Math.max(e,this.material?.getBindingsUpdateTimestamp()||0)}_setGeometryAttributes(e){let t={...e.attributes};for(let[n]of Object.entries(t))!this.pipeline.shaderLayout.attributes.find(i=>i.name===n)&&n!=="positions"&&delete t[n];this.vertexCount=e.vertexCount,this.setIndexBuffer(e.indices||null),this.setAttributes(e.attributes,{disableWarnings:!0}),this.setAttributes(t,{disableWarnings:this.props.disableWarnings}),this.setNeedsRedraw("geometry attributes")}_setPipelineNeedsUpdate(e){this._pipelineNeedsUpdate||(this._pipelineNeedsUpdate=e),this._drawBlockedReason=!1,this.setNeedsRedraw(e)}_updatePipeline(){if(this._pipelineNeedsUpdate){let e=null,t=null;this.pipeline&&(T.log(1,`Model ${this.id}: Recreating pipeline because "${this._pipelineNeedsUpdate}".`)(),e=this.pipeline.vs,t=this.pipeline.fs),this._pipelineNeedsUpdate=!1;let n=this.shaderFactory.createShader({id:`${this.id}-vertex`,stage:"vertex",source:this.source||this.vs,debugShaders:this.props.debugShaders}),i=null;this.source?i=n:this.fs&&(i=this.shaderFactory.createShader({id:`${this.id}-fragment`,stage:"fragment",source:this.source||this.fs,debugShaders:this.props.debugShaders})),this.pipeline=this.pipelineFactory.createRenderPipeline({...this.props,bindings:void 0,bufferLayout:this.bufferLayout,colorAttachmentFormats:this._colorAttachmentFormats,depthStencilAttachmentFormat:this._depthStencilAttachmentFormat,topology:this.topology,parameters:this.parameters,bindGroups:void 0,vs:n,fs:i}),this._attributeInfos=is(this.pipeline.shaderLayout,this.bufferLayout),e&&this.shaderFactory.release(e),t&&t!==e&&this.shaderFactory.release(t)}return this.pipeline}_logDrawCallStart(){let e=T.level>3?0:oO;T.level<2||Date.now()-this._lastLogTime<e||(this._lastLogTime=Date.now(),this._logOpen=!0,T.group(Zt,`>>> DRAWING MODEL ${this.id}`,{collapsed:T.level<=2})())}_logDrawCallEnd(){if(this._logOpen){let e=rw(this.pipeline.shaderLayout,this.id);T.table(Zt,e)();let t=this.shaderInputs.getDebugTable();T.table(Zt,t)();let n=this._getAttributeDebugTable();T.table(Zt,this._attributeInfos)(),T.table(Zt,n)(),T.groupEnd(Zt)(),this._logOpen=!1}}_logFramebuffer(e){let t=this.device.props.debugFramebuffers;if(this._drawCount++,!t)return;let n=e.props.framebuffer;ow(e,n,{id:n?.id||`${this.id}-framebuffer`,minimap:!0})}_getAttributeDebugTable(){let e={};for(let[t,n]of Object.entries(this._attributeInfos)){let i=this.vertexArray.attributes[n.location];e[n.location]={name:t,type:n.shaderType,values:i?this._getBufferOrConstantValues(i,n.bufferDataType):"null"}}if(this.vertexArray.indexBuffer){let{indexBuffer:t}=this.vertexArray,n=t.indexType==="uint32"?new Uint32Array(t.debugData):new Uint16Array(t.debugData);e.indices={name:"indices",type:t.indexType,values:n.toString()}}return e}_getBufferOrConstantValues(e,t){let n=Te.getTypedArrayConstructor(t);return(e instanceof z?new n(e.debugData):e).toString()}_getNonMaterialBindings(e){if(!this.material)return e;let t={};for(let[n,i]of Object.entries(e))this.material.ownsBinding(n)||(t[n]=i);return t}_getCurrentShaderLayout(){return this.pipeline?.shaderLayout||this.props.shaderLayout||{bindings:[]}}_syncDynamicBuffers(){if(this._dynamicIndexBufferSource&&this._dynamicIndexBufferSource.generation!==this._dynamicIndexBufferSource.source.generation){let e=this._dynamicIndexBufferSource.source.buffer;this.indexBuffer=e,this.vertexArray.setIndexBuffer(e),this._dynamicIndexBufferSource.generation=this._dynamicIndexBufferSource.source.generation,this.setNeedsRedraw("dynamic index buffer")}for(let[e,t]of Object.entries(this._dynamicAttributeBufferSources))t.generation!==t.source.generation&&(this.vertexArray.setBuffer(Number(e),t.source.buffer),t.generation=t.source.generation,this.setNeedsRedraw("dynamic attribute buffer"))}_syncAttachmentFormats(e){if(this.device.type!=="webgpu")return;let t=e.framebuffer||e.props.framebuffer,n=e.props,i=n.colorAttachmentFormats??t?.colorAttachments?.map(s=>lO(s?.texture?.format)),o=n.depthStencilAttachmentFormat===!1?void 0:n.depthStencilAttachmentFormat??uO(t?.depthStencilAttachment?.texture?.format);(!$i(this._colorAttachmentFormats,i,1)||this._depthStencilAttachmentFormat!==o)&&(this._colorAttachmentFormats=i,this._depthStencilAttachmentFormat=o,this._setPipelineNeedsUpdate("attachment formats"))}};d(Fs,"defaultProps",{...ft.defaultProps,source:void 0,vs:null,fs:null,id:"unnamed",handle:void 0,userData:{},defines:{},modules:[],plugins:[],geometry:null,indexBuffer:null,indexCount:void 0,firstVertex:0,firstIndex:0,attributes:{},constantAttributes:{},bindings:{},uniforms:{},varyings:[],isInstanced:void 0,instanceCount:0,vertexCount:0,shaderInputs:void 0,material:void 0,pipelineFactory:void 0,shaderFactory:void 0,transformFeedback:void 0,shaderAssembler:dt.getDefaultShaderAssembler("glsl"),debugShaders:void 0,disableWarnings:void 0});Re=Fs});var dO,hO,Us,Be,xw=b(()=>{N();qe();im();dO=35980,hO=35981,Us=class Us{constructor(e,t=Us.defaultProps){d(this,"device");d(this,"model");d(this,"transformFeedback");if(!Us.isSupported(e))throw new Error("BufferTransform not yet implemented on WebGPU");this.device=e,this.model=new Re(this.device,{id:t.id||"buffer-transform-model",fs:t.fs||Oh(),topology:t.topology||"point-list",varyings:t.outputs||t.varyings,...t,bufferMode:t.bufferMode||(t.feedbackBufferMode==="interleaved"?dO:hO)}),this.transformFeedback=this.device.createTransformFeedback({layout:this.model.pipeline.shaderLayout,buffers:t.feedbackBuffers}),this.model.setTransformFeedback(this.transformFeedback)}static isSupported(e){return e?.info?.type==="webgl"}destroy(){this.model&&this.model.destroy()}delete(){this.destroy()}run(e){e?.inputBuffers&&this.model.setAttributes(e.inputBuffers),e?.outputBuffers&&this.transformFeedback.setBuffers(e.outputBuffers);let t=this.device.beginRenderPass({discard:!0,...e});this.model.draw(t),t.end()}getBuffer(e){return this.transformFeedback.getBuffer(e)}readAsync(e){let t=this.getBuffer(e);if(!t)throw new Error("BufferTransform#getBuffer");if(t instanceof z)return t.readAsync();let{buffer:n,byteOffset:i=0,byteLength:o=n.byteLength}=t;return n.readAsync(i,o)}};d(Us,"defaultProps",{...Re.defaultProps,feedbackBufferMode:"separate",outputs:void 0,feedbackBuffers:void 0});Be=Us});function mO(r){return{type:r.type,shaderLanguage:r.info.shadingLanguage,shaderLanguageVersion:r.info.shadingLanguageVersion,gpu:r.info.gpu,limits:r.limits,features:r.features}}var om,pO,ql,ot,vw=b(()=>{N();qe();bd();Jp();Xp();zi();om=2,pO=1e4,ql=class ql{constructor(e,t){d(this,"device");d(this,"id");d(this,"pipelineFactory");d(this,"shaderFactory");d(this,"userData",{});d(this,"bindings",{});d(this,"pipeline");d(this,"source");d(this,"shader");d(this,"shaderInputs");d(this,"_uniformStore");d(this,"_pipelineNeedsUpdate","newly created");d(this,"_getModuleUniforms");d(this,"props");d(this,"_destroyed",!1);d(this,"_lastLogTime",0);d(this,"_logOpen",!1);d(this,"_drawCount",0);if(e.type!=="webgpu")throw new Error("Computation is only supported in WebGPU");this.props={...ql.defaultProps,...t},t=this.props,this.id=t.id||Xt("model"),this.device=e,Object.assign(this.userData,t.userData);let n=mO(e),i=os(this.props.plugins,n.shaderLanguage);if(Object.keys(i.vertexInputs).length>0||Object.keys(i.varyings).length>0)throw new Error("Computation does not support ShaderPlugin vertex inputs or varyings");let o=ss(this.props.modules,i.modules),s=Object.fromEntries(o.map(m=>[m.name,m]));this.shaderInputs=t.shaderInputs||new ji(s),t.shaderInputs&&i.modules.length>0&&this.shaderInputs.addModules(i.modules),this.setShaderInputs(this.shaderInputs);let a=Yl(this.props.modules,this.shaderInputs?.getModules()),c={...i.defines,...this.props.defines};this.props.shaderLayout=Wi(this.props.shaderLayout,a)||null,this.pipelineFactory=t.pipelineFactory||_n.getDefaultPipelineFactory(this.device),this.shaderFactory=t.shaderFactory||bn.getDefaultShaderFactory(this.device);let l=this.props.shaderAssembler;Rr(l instanceof Nr);let{source:u,getUniforms:f,shaderLayout:h}=l.assembleWGSLShader({platformInfo:n,...this.props,modules:a,defines:c,scanVertexAttributes:!1,pluginInjections:i.injections});this.source=u,this._getModuleUniforms=f;let p=h??e.getShaderLayout?.(this.source,{scanVertexAttributes:!1});this.props.shaderLayout=Wi(this.props.shaderLayout||p||null,a)||null,this.pipeline=this._updatePipeline(),t.bindings&&this.setBindings(t.bindings)}destroy(){this._destroyed||(this.pipelineFactory.release(this.pipeline),this.shaderFactory.release(this.shader),this._uniformStore.destroy(),this._destroyed=!0)}predraw(e){this.updateShaderInputs(e)}dispatch(e,t,n,i){try{this._logDrawCallStart(),this._setPipeline(e),e.dispatch(t,n,i)}finally{this._logDrawCallEnd()}}dispatchIndirect(e,t,n=0){try{this._logDrawCallStart(),this._setPipeline(e),e.dispatchIndirect(t,n)}finally{this._logDrawCallEnd()}}_setPipeline(e){this.pipeline=this._updatePipeline(),this.pipeline.setBindings(this.bindings),e.setPipeline(this.pipeline),e.setBindings({})}setVertexCount(e){}setInstanceCount(e){}setShaderInputs(e){this.shaderInputs=e,this._uniformStore=new wn(this.device,this.shaderInputs.modules);for(let[t,n]of Object.entries(this.shaderInputs.modules))if(ks(n)){let i=this._uniformStore.getManagedUniformBuffer(t);this.bindings[`${t}Uniforms`]=i}}setShaderModuleProps(e){let t=this._getModuleUniforms(e),n=Object.keys(t).filter(o=>{let s=t[o];return!Ro(s)&&typeof s!="number"&&typeof s!="boolean"}),i={};for(let o of n)i[o]=t[o],delete t[o]}updateShaderInputs(e){this._uniformStore.setUniforms(this.shaderInputs.getUniformValues(),e)}setBindings(e){Object.assign(this.bindings,e)}_setPipelineNeedsUpdate(e){this._pipelineNeedsUpdate=this._pipelineNeedsUpdate||e}_updatePipeline(){if(this._pipelineNeedsUpdate){let e=null;this.pipeline&&(T.log(1,`Model ${this.id}: Recreating pipeline because "${this._pipelineNeedsUpdate}".`)(),e=this.shader),this._pipelineNeedsUpdate=!1,this.shader=this.shaderFactory.createShader({id:`${this.id}-fragment`,stage:"compute",source:this.source,debugShaders:this.props.debugShaders}),this.pipeline=this.pipelineFactory.createComputePipeline({...this.props,shader:this.shader}),e&&this.shaderFactory.release(e)}return this.pipeline}_logDrawCallStart(){let e=T.level>3?0:pO;T.level<2||Date.now()-this._lastLogTime<e||(this._lastLogTime=Date.now(),this._logOpen=!0,T.group(om,`>>> DRAWING MODEL ${this.id}`,{collapsed:T.level<=2})())}_logDrawCallEnd(){if(this._logOpen){let e=this.shaderInputs.getDebugTable();T.table(om,e)(),T.groupEnd(om)(),this._logOpen=!1}}_getBufferOrConstantValues(e,t){let n=Te.getTypedArrayConstructor(t);return(e instanceof z?new n(e.debugData):e).toString()}};d(ql,"defaultProps",{...kr.defaultProps,id:"unnamed",handle:void 0,userData:{},source:"",modules:[],defines:{},plugins:[],bindings:void 0,shaderInputs:void 0,pipelineFactory:void 0,shaderFactory:void 0,shaderAssembler:dt.getDefaultShaderAssembler("wgsl"),debugShaders:void 0});ot=ql});var de=b(()=>{qv();Jv();im();xw();Wl();tm();vw()});function Dw(r=!0){let e=HTMLCanvasElement.prototype;if(!r&&e.originalGetContext){e.getContext=e.originalGetContext,e.originalGetContext=void 0;return}e.originalGetContext=e.getContext,e.getContext=function(t,n){if(t==="webgl"||t==="experimental-webgl"){let i=this.originalGetContext("webgl2",n);return i instanceof HTMLElement&&HO(i),i}return this.originalGetContext(t,n)}}function HO(r){r.getExtension("EXT_color_buffer_float");let e={...$O,WEBGL_disjoint_timer_query:r.getExtension("EXT_disjoint_timer_query_webgl2"),WEBGL_draw_buffers:VO(r),OES_vertex_array_object:WO(r),ANGLE_instanced_arrays:jO(r)},t=r.getExtension.bind(r);r.getExtension=function(i){let o=t(i);return o||(i in e?e[i]:null)};let n=r.getSupportedExtensions;r.getSupportedExtensions=function(){return(n.apply(r)||[])?.concat(Object.keys(e))}}var $O,VO,WO,jO,Nw=b(()=>{$O={WEBGL_depth_texture:{UNSIGNED_INT_24_8_WEBGL:34042},OES_element_index_uint:{},OES_texture_float:{},OES_texture_half_float:{HALF_FLOAT_OES:5131},EXT_color_buffer_float:{},OES_standard_derivatives:{FRAGMENT_SHADER_DERIVATIVE_HINT_OES:35723},EXT_frag_depth:{},EXT_blend_minmax:{MIN_EXT:32775,MAX_EXT:32776},EXT_shader_texture_lod:{}},VO=r=>({drawBuffersWEBGL(e){return r.drawBuffers(e)},COLOR_ATTACHMENT0_WEBGL:36064,COLOR_ATTACHMENT1_WEBGL:36065,COLOR_ATTACHMENT2_WEBGL:36066,COLOR_ATTACHMENT3_WEBGL:36067}),WO=r=>({VERTEX_ARRAY_BINDING_OES:34229,createVertexArrayOES(){return r.createVertexArray()},deleteVertexArrayOES(e){return r.deleteVertexArray(e)},isVertexArrayOES(e){return r.isVertexArray(e)},bindVertexArrayOES(e){return r.bindVertexArray(e)}}),jO=r=>({VERTEX_ATTRIB_ARRAY_DIVISOR_ANGLE:35070,drawArraysInstancedANGLE(...e){return r.drawArraysInstanced(...e)},drawElementsInstancedANGLE(...e){return r.drawElementsInstanced(...e)},vertexAttribDivisorANGLE(...e){return r.vertexAttribDivisor(...e)}})});async function Uw(){if(!ru){gm();return}await ru.load()}function Gw(r,e){return ru?ru.makeDebugContext(r,e):(gm(),r)}async function zw(r){if(!mm){gm();return}await mm.load(r)}function $w(r){return mm?.initialize(r)||null}function gm(){Fw||(Fw=!0,T.warn("Import @luma.gl/webgl/debug before enabling WebGL debugging.")())}var ru,mm,Fw,ym=b(()=>{N();ru=null,mm=null,Fw=!1});function _m(r){return Array.isArray(r)||ArrayBuffer.isView(r)&&!(r instanceof DataView)}function le(r,e,t){return e[r]!==void 0?e[r]:t[r]}var ta,ye,Vw,st,Ww,ea,jw,Hw,bm,er,xm,Yw,vm=b(()=>{ta={3042:!1,32773:new Float32Array([0,0,0,0]),32777:32774,34877:32774,32969:1,32968:0,32971:1,32970:0,3106:new Float32Array([0,0,0,0]),3107:[!0,!0,!0,!0],2884:!1,2885:1029,2929:!1,2931:1,2932:513,2928:new Float32Array([0,1]),2930:!0,3024:!0,35725:null,36006:null,36007:null,34229:null,34964:null,2886:2305,33170:4352,2849:1,32823:!1,32824:0,10752:0,32926:!1,32928:!1,32938:1,32939:!1,3089:!1,3088:new Int32Array([0,0,1024,1024]),2960:!1,2961:0,2968:4294967295,36005:4294967295,2962:519,2967:0,2963:4294967295,34816:519,36003:0,36004:4294967295,2964:7680,2965:7680,2966:7680,34817:7680,34818:7680,34819:7680,2978:[0,0,1024,1024],36389:null,36662:null,36663:null,35053:null,35055:null,35723:4352,36010:null,35977:!1,3333:4,3317:4,37440:!1,37441:!1,37443:37444,3330:0,3332:0,3331:0,3314:0,32878:0,3316:0,3315:0,32877:0},ye=(r,e,t)=>e?r.enable(t):r.disable(t),Vw=(r,e,t)=>r.hint(t,e),st=(r,e,t)=>r.pixelStorei(t,e),Ww=(r,e,t)=>{let n=t===36006?36009:36008;return r.bindFramebuffer(n,e)},ea=(r,e,t)=>{let i={34964:34962,36662:36662,36663:36663,35053:35051,35055:35052}[t];r.bindBuffer(i,e)};jw={3042:ye,32773:(r,e)=>r.blendColor(...e),32777:"blendEquation",34877:"blendEquation",32969:"blendFunc",32968:"blendFunc",32971:"blendFunc",32970:"blendFunc",3106:(r,e)=>r.clearColor(...e),3107:(r,e)=>r.colorMask(...e),2884:ye,2885:(r,e)=>r.cullFace(e),2929:ye,2931:(r,e)=>r.clearDepth(e),2932:(r,e)=>r.depthFunc(e),2928:(r,e)=>r.depthRange(...e),2930:(r,e)=>r.depthMask(e),3024:ye,35723:Vw,35725:(r,e)=>r.useProgram(e),36007:(r,e)=>r.bindRenderbuffer(36161,e),36389:(r,e)=>r.bindTransformFeedback?.(36386,e),34229:(r,e)=>r.bindVertexArray(e),36006:Ww,36010:Ww,34964:ea,36662:ea,36663:ea,35053:ea,35055:ea,2886:(r,e)=>r.frontFace(e),33170:Vw,2849:(r,e)=>r.lineWidth(e),32823:ye,32824:"polygonOffset",10752:"polygonOffset",35977:ye,32926:ye,32928:ye,32938:"sampleCoverage",32939:"sampleCoverage",3089:ye,3088:(r,e)=>r.scissor(...e),2960:ye,2961:(r,e)=>r.clearStencil(e),2968:(r,e)=>r.stencilMaskSeparate(1028,e),36005:(r,e)=>r.stencilMaskSeparate(1029,e),2962:"stencilFuncFront",2967:"stencilFuncFront",2963:"stencilFuncFront",34816:"stencilFuncBack",36003:"stencilFuncBack",36004:"stencilFuncBack",2964:"stencilOpFront",2965:"stencilOpFront",2966:"stencilOpFront",34817:"stencilOpBack",34818:"stencilOpBack",34819:"stencilOpBack",2978:(r,e)=>r.viewport(...e),34383:ye,10754:ye,12288:ye,12289:ye,12290:ye,12291:ye,12292:ye,12293:ye,12294:ye,12295:ye,3333:st,3317:st,37440:st,37441:st,37443:st,3330:st,3332:st,3331:st,3314:st,32878:st,3316:st,3315:st,32877:st,framebuffer:(r,e)=>{let t=e&&"handle"in e?e.handle:e;return r.bindFramebuffer(36160,t)},blend:(r,e)=>e?r.enable(3042):r.disable(3042),blendColor:(r,e)=>r.blendColor(...e),blendEquation:(r,e)=>{let t=typeof e=="number"?[e,e]:e;r.blendEquationSeparate(...t)},blendFunc:(r,e)=>{let t=e?.length===2?[...e,...e]:e;r.blendFuncSeparate(...t)},clearColor:(r,e)=>r.clearColor(...e),clearDepth:(r,e)=>r.clearDepth(e),clearStencil:(r,e)=>r.clearStencil(e),colorMask:(r,e)=>r.colorMask(...e),cull:(r,e)=>e?r.enable(2884):r.disable(2884),cullFace:(r,e)=>r.cullFace(e),depthTest:(r,e)=>e?r.enable(2929):r.disable(2929),depthFunc:(r,e)=>r.depthFunc(e),depthMask:(r,e)=>r.depthMask(e),depthRange:(r,e)=>r.depthRange(...e),dither:(r,e)=>e?r.enable(3024):r.disable(3024),derivativeHint:(r,e)=>{r.hint(35723,e)},frontFace:(r,e)=>r.frontFace(e),mipmapHint:(r,e)=>r.hint(33170,e),lineWidth:(r,e)=>r.lineWidth(e),polygonOffsetFill:(r,e)=>e?r.enable(32823):r.disable(32823),polygonOffset:(r,e)=>r.polygonOffset(...e),sampleCoverage:(r,e)=>r.sampleCoverage(e[0],e[1]||!1),scissorTest:(r,e)=>e?r.enable(3089):r.disable(3089),scissor:(r,e)=>r.scissor(...e),stencilTest:(r,e)=>e?r.enable(2960):r.disable(2960),stencilMask:(r,e)=>{e=_m(e)?e:[e,e];let[t,n]=e;r.stencilMaskSeparate(1028,t),r.stencilMaskSeparate(1029,n)},stencilFunc:(r,e)=>{e=_m(e)&&e.length===3?[...e,...e]:e;let[t,n,i,o,s,a]=e;r.stencilFuncSeparate(1028,t,n,i),r.stencilFuncSeparate(1029,o,s,a)},stencilOp:(r,e)=>{e=_m(e)&&e.length===3?[...e,...e]:e;let[t,n,i,o,s,a]=e;r.stencilOpSeparate(1028,t,n,i),r.stencilOpSeparate(1029,o,s,a)},viewport:(r,e)=>r.viewport(...e)};Hw={blendEquation:(r,e,t)=>r.blendEquationSeparate(le(32777,e,t),le(34877,e,t)),blendFunc:(r,e,t)=>r.blendFuncSeparate(le(32969,e,t),le(32968,e,t),le(32971,e,t),le(32970,e,t)),polygonOffset:(r,e,t)=>r.polygonOffset(le(32824,e,t),le(10752,e,t)),sampleCoverage:(r,e,t)=>r.sampleCoverage(le(32938,e,t),le(32939,e,t)),stencilFuncFront:(r,e,t)=>r.stencilFuncSeparate(1028,le(2962,e,t),le(2967,e,t),le(2963,e,t)),stencilFuncBack:(r,e,t)=>r.stencilFuncSeparate(1029,le(34816,e,t),le(36003,e,t),le(36004,e,t)),stencilOpFront:(r,e,t)=>r.stencilOpSeparate(1028,le(2964,e,t),le(2965,e,t),le(2966,e,t)),stencilOpBack:(r,e,t)=>r.stencilOpSeparate(1029,le(34817,e,t),le(34818,e,t),le(34819,e,t))},bm={enable:(r,e)=>r({[e]:!0}),disable:(r,e)=>r({[e]:!1}),pixelStorei:(r,e,t)=>r({[e]:t}),hint:(r,e,t)=>r({[e]:t}),useProgram:(r,e)=>r({35725:e}),bindRenderbuffer:(r,e,t)=>r({36007:t}),bindTransformFeedback:(r,e,t)=>r({36389:t}),bindVertexArray:(r,e)=>r({34229:e}),bindFramebuffer:(r,e,t)=>{switch(e){case 36160:return r({36006:t,36010:t});case 36009:return r({36006:t});case 36008:return r({36010:t});default:return null}},bindBuffer:(r,e,t)=>{let n={34962:[34964],36662:[36662],36663:[36663],35051:[35053],35052:[35055]}[e];return n?r({[n]:t}):{valueChanged:!0}},blendColor:(r,e,t,n,i)=>r({32773:new Float32Array([e,t,n,i])}),blendEquation:(r,e)=>r({32777:e,34877:e}),blendEquationSeparate:(r,e,t)=>r({32777:e,34877:t}),blendFunc:(r,e,t)=>r({32969:e,32968:t,32971:e,32970:t}),blendFuncSeparate:(r,e,t,n,i)=>r({32969:e,32968:t,32971:n,32970:i}),clearColor:(r,e,t,n,i)=>r({3106:new Float32Array([e,t,n,i])}),clearDepth:(r,e)=>r({2931:e}),clearStencil:(r,e)=>r({2961:e}),colorMask:(r,e,t,n,i)=>r({3107:[e,t,n,i]}),cullFace:(r,e)=>r({2885:e}),depthFunc:(r,e)=>r({2932:e}),depthRange:(r,e,t)=>r({2928:new Float32Array([e,t])}),depthMask:(r,e)=>r({2930:e}),frontFace:(r,e)=>r({2886:e}),lineWidth:(r,e)=>r({2849:e}),polygonOffset:(r,e,t)=>r({32824:e,10752:t}),sampleCoverage:(r,e,t)=>r({32938:e,32939:t}),scissor:(r,e,t,n,i)=>r({3088:new Int32Array([e,t,n,i])}),stencilMask:(r,e)=>r({2968:e,36005:e}),stencilMaskSeparate:(r,e,t)=>r({[e===1028?2968:36005]:t}),stencilFunc:(r,e,t,n)=>r({2962:e,2967:t,2963:n,34816:e,36003:t,36004:n}),stencilFuncSeparate:(r,e,t,n,i)=>r({[e===1028?2962:34816]:t,[e===1028?2967:36003]:n,[e===1028?2963:36004]:i}),stencilOp:(r,e,t,n)=>r({2964:e,2965:t,2966:n,34817:e,34818:t,34819:n}),stencilOpSeparate:(r,e,t,n,i)=>r({[e===1028?2964:34817]:t,[e===1028?2965:34818]:n,[e===1028?2966:34819]:i}),viewport:(r,e,t,n,i)=>r({2978:[e,t,n,i]})},er=(r,e)=>r.isEnabled(e),xm={3042:er,2884:er,2929:er,3024:er,32823:er,32926:er,32928:er,3089:er,2960:er,35977:er},Yw=new Set([34016,36388,36387,35983,35368,34965,35739,35738,3074,34853,34854,34855,34856,34857,34858,34859,34860,34861,34862,34863,34864,34865,34866,34867,34868,35097,32873,35869,32874,34068])});function Mt(r,e){if(YO(e))return;let t={};for(let i in e){let o=Number(i),s=jw[i];s&&(typeof s=="string"?t[s]=!0:s(r,e[i],o))}let n=r.lumaState?.cache;if(n)for(let i in t){let o=Hw[i];o(r,e,n)}}function nu(r,e=ta){if(typeof e=="number"){let i=e,o=xm[i];return o?o(r,i):r.getParameter(i)}let t=Array.isArray(e)?e:Object.keys(e),n={};for(let i of t){let o=xm[i];n[i]=o?o(r,Number(i)):r.getParameter(Number(i))}return n}function qw(r){Mt(r,ta)}function YO(r){for(let e in r)return!1;return!0}var Xi=b(()=>{vm()});function Zw(r,e){if(r===e)return!0;if(Xw(r)&&Xw(e)&&r.length===e.length){for(let t=0;t<r.length;++t)if(r[t]!==e[t])return!1;return!0}return!1}function Xw(r){return Array.isArray(r)||ArrayBuffer.isView(r)}var Kw=b(()=>{});function Qw(r,e){let t=r[e].bind(r);r[e]=function(i){if(i===void 0||Yw.has(i))return t(i);let o=It.get(r);return i in o.cache||(o.cache[i]=t(i)),o.enable?o.cache[i]:t(i)},Object.defineProperty(r[e],"name",{value:`${e}-from-cache`,configurable:!1})}function qO(r,e,t){if(!r[e])return;let n=r[e].bind(r);r[e]=function(...o){let s=It.get(r),{valueChanged:a,oldValue:c}=t(s._updateCache,...o);return a&&n(...o),c},Object.defineProperty(r[e],"name",{value:`${e}-to-cache`,configurable:!1})}function XO(r){let e=r.useProgram.bind(r);r.useProgram=function(n){let i=It.get(r);i.program!==n&&(e(n),i.program=n)}}var It,wm=b(()=>{Xi();Kw();vm();It=class{constructor(e,t){d(this,"gl");d(this,"program",null);d(this,"stateStack",[]);d(this,"enable",!0);d(this,"cache",null);d(this,"log");d(this,"initialized",!1);this.gl=e,this.log=t?.log||(()=>{}),this._updateCache=this._updateCache.bind(this),Object.seal(this)}static get(e){return e.lumaState}push(e={}){this.stateStack.push({})}pop(){let e=this.stateStack[this.stateStack.length-1];Mt(this.gl,e),this.stateStack.pop()}trackState(e,t){if(this.cache=t?.copyState?nu(e):Object.assign({},ta),this.initialized)throw new Error("WebGLStateTracker");this.initialized=!0,this.gl.lumaState=this,XO(e);for(let n in bm){let i=bm[n];qO(e,n,i)}Qw(e,"getParameter"),Qw(e,"isEnabled")}_updateCache(e){let t=!1,n,i=this.stateStack.length>0?this.stateStack[this.stateStack.length-1]:null;for(let o in e){let s=e[o],a=this.cache[o];Zw(s,a)||(t=!0,n=a,i&&!(o in i)&&(i[o]=a),this.cache[o]=s)}return{valueChanged:t,oldValue:n}}}});function ra(r){let e=r.luma||{_polyfilled:!1,extensions:{},softwareRenderer:!1};return e._polyfilled??(e._polyfilled=!1),e.extensions||(e.extensions={}),r.luma=e,e}var Em=b(()=>{});function Jw(r,e,t){let n="",i=c=>{let l=c.statusMessage;l&&(n||(n=l))};r.addEventListener("webglcontextcreationerror",i,!1);let o=t.failIfMajorPerformanceCaveat!==!0,s={preserveDrawingBuffer:!0,...t,failIfMajorPerformanceCaveat:!0},a=null;try{a||(a=r.getContext("webgl2",s)),!a&&s.failIfMajorPerformanceCaveat&&(n||(n="Only software GPU is available. Set `failIfMajorPerformanceCaveat: false` to allow."));let c=!1;if(!a&&o&&(s.failIfMajorPerformanceCaveat=!1,a=r.getContext("webgl2",s),c=!0),a||(a=r.getContext("webgl",{}),a&&(a=null,n||(n="Your browser only supports WebGL1"))),!a)throw n||(n="Your browser does not support WebGL"),new Error(`Failed to create WebGL context: ${n}`);let l=ra(a);l.softwareRenderer=c;let{onContextLost:u,onContextRestored:f}=e;return r.addEventListener("webglcontextlost",h=>u(h),!1),r.addEventListener("webglcontextrestored",h=>f(h),!1),a}finally{r.removeEventListener("webglcontextcreationerror",i,!1)}}var eE=b(()=>{Em()});function Rt(r,e,t){return t[e]===void 0&&(t[e]=r.getExtension(e)||null),t[e]}var na=b(()=>{});function tE(r,e){let t=r.getParameter(7936),n=r.getParameter(7937);Rt(r,"WEBGL_debug_renderer_info",e);let i=e.WEBGL_debug_renderer_info,o=r.getParameter(i?i.UNMASKED_VENDOR_WEBGL:7936),s=r.getParameter(i?i.UNMASKED_RENDERER_WEBGL:7937),a=o||t,c=s||n,l=r.getParameter(7938),u=rE(a,c),f=ZO(a,c),h=KO(a,c);return{type:"webgl",gpu:u,gpuType:h,gpuBackend:f,vendor:a,renderer:c,version:l,shadingLanguage:"glsl",shadingLanguageVersion:300}}function rE(r,e){return/NVIDIA/i.exec(r)||/NVIDIA/i.exec(e)?"nvidia":/INTEL/i.exec(r)||/INTEL/i.exec(e)?"intel":/Apple/i.exec(r)||/Apple/i.exec(e)?"apple":/AMD/i.exec(r)||/AMD/i.exec(e)||/ATI/i.exec(r)||/ATI/i.exec(e)?"amd":/SwiftShader/i.exec(r)||/SwiftShader/i.exec(e)?"software":"unknown"}function ZO(r,e){return/Metal/i.exec(r)||/Metal/i.exec(e)?"metal":/ANGLE/i.exec(r)||/ANGLE/i.exec(e)?"opengl":"unknown"}function KO(r,e){if(/SwiftShader/i.exec(r)||/SwiftShader/i.exec(e))return"cpu";switch(rE(r,e)){case"apple":return QO(r,e)?"integrated":"unknown";case"intel":return"integrated";case"software":return"cpu";case"unknown":return"unknown";default:return"discrete"}}function QO(r,e){return/Apple (M\d|A\d|GPU)/i.test(`${r} ${e}`)}var nE=b(()=>{na()});function iu(r){switch(r){case"uint8":return 5121;case"sint8":return 5120;case"unorm8":return 5121;case"snorm8":return 5120;case"uint16":return 5123;case"sint16":return 5122;case"unorm16":return 5123;case"snorm16":return 5122;case"uint32":return 5125;case"sint32":return 5124;case"float16":return 5131;case"float32":return 5126}throw new Error(String(r))}var Sm=b(()=>{});function sE(r){return r in su}function Cm(r,e,t){return aE(r,e,t,new Set)}function aE(r,e,t,n){let i=su[e];if(!i||n.has(e))return!1;n.add(e);let o=(i.features||[]).every(s=>aE(r,s,t,n));return n.delete(e),o?(i.extensions||[]).every(s=>!!Rt(r,s,t)):!1}function cE(r,e,t){let n=e.create,i=au[e.format];i?.gl===void 0&&(n=!1),i?.x&&(n=n&&!!Rt(r,i.x,t)),e.format==="stencil8"&&(n=!1);let o=i?.r===!1?!1:i?.r===void 0||Cm(r,i.r,t),s=n&&e.render&&o&&sk(r,e.format,t);return{format:e.format,create:n&&e.create,render:s,filter:n&&e.filter,blend:n&&e.blend,store:n&&e.store}}function sk(r,e,t){let n=au[e],i=n?.gl;if(i===void 0||n?.x&&!Rt(r,n.x,t))return!1;let o=r.getParameter(32873),s=r.getParameter(36006),a=r.createTexture(),c=r.createFramebuffer();if(!a||!c)return!1;let l=0,u=Number(r.getError());for(;u!==l;)u=r.getError();let f=!1;try{if(r.bindTexture(3553,a),r.texStorage2D(3553,1,i,1,1),Number(r.getError())!==l)return!1;r.bindFramebuffer(36160,c),r.framebufferTexture2D(36160,36064,3553,a,0),f=Number(r.checkFramebufferStatus(36160))===36053&&Number(r.getError())===l}finally{r.bindFramebuffer(36160,s),r.deleteFramebuffer(c),r.bindTexture(3553,o),r.deleteTexture(a)}return f}function cu(r){let e=au[r],t=ck(r),n=ze.getInfo(r);return n.compressed&&(e.dataFormat=t),{internalFormat:t,format:e?.dataFormat||ak(n.channels,n.integer,n.normalized,t),type:n.dataType?iu(n.dataType):e?.types?.[0]||5121,compressed:n.compressed||!1}}function lE(r){switch(ze.getInfo(r).attachment){case"depth":return 36096;case"stencil":return 36128;case"depth-stencil":return 33306;default:throw new Error(`Not a depth stencil format: ${r}`)}}function ak(r,e,t,n){if(n===6408||n===6407)return n;switch(r){case"r":return e&&!t?36244:6403;case"rg":return e&&!t?33320:33319;case"rgb":return e&&!t?36248:6407;case"rgba":return e&&!t?36249:6408;case"bgra":throw new Error("bgra pixels not supported by WebGL");default:return 6408}}function ck(r){let t=au[r]?.gl;if(t===void 0)throw new Error(`Unsupported texture format ${r}`);return t}var ia,oa,Zi,Ki,JO,ek,tk,rk,nk,ik,iE,oE,Pm,Tm,Lm,Am,ou,ok,su,au,Qi=b(()=>{N();na();Sm();ia="WEBGL_compressed_texture_s3tc",oa="WEBGL_compressed_texture_s3tc_srgb",Zi="EXT_texture_compression_rgtc",Ki="EXT_texture_compression_bptc",JO="WEBGL_compressed_texture_etc",ek="WEBGL_compressed_texture_astc",tk="WEBGL_compressed_texture_etc1",rk="WEBGL_compressed_texture_pvrtc",nk="WEBGL_compressed_texture_atc",ik="EXT_texture_norm16",iE="EXT_render_snorm",oE="EXT_color_buffer_float",Pm="snorm8-renderable-webgl",Tm="norm16-renderable-webgl",Lm="snorm16-renderable-webgl",Am="float16-renderable-webgl",ou="float32-renderable-webgl",ok="rgb9e5ufloat-renderable-webgl",su={"float32-renderable-webgl":{extensions:[oE]},"float16-renderable-webgl":{extensions:["EXT_color_buffer_half_float"]},"rgb9e5ufloat-renderable-webgl":{extensions:["WEBGL_render_shared_exponent"]},"snorm8-renderable-webgl":{extensions:[iE]},"norm16-webgl":{extensions:[ik]},"norm16-renderable-webgl":{features:["norm16-webgl"]},"snorm16-renderable-webgl":{features:["norm16-webgl"],extensions:[iE]},"float32-filterable":{extensions:["OES_texture_float_linear"]},"float16-filterable-webgl":{extensions:["OES_texture_half_float_linear"]},"texture-filterable-anisotropic-webgl":{extensions:["EXT_texture_filter_anisotropic"]},"texture-blend-float-webgl":{extensions:["EXT_float_blend"]},"texture-compression-bc":{extensions:[ia,oa,Zi,Ki]},"texture-compression-bc5-webgl":{extensions:[Zi]},"texture-compression-bc7-webgl":{extensions:[Ki]},"texture-compression-etc2":{extensions:[JO]},"texture-compression-astc":{extensions:[ek]},"texture-compression-etc1-webgl":{extensions:[tk]},"texture-compression-pvrtc-webgl":{extensions:[rk]},"texture-compression-atc-webgl":{extensions:[nk]}};au={r8unorm:{gl:33321,rb:!0},r8snorm:{gl:36756,r:Pm},r8uint:{gl:33330,rb:!0},r8sint:{gl:33329,rb:!0},rg8unorm:{gl:33323,rb:!0},rg8snorm:{gl:36757,r:Pm},rg8uint:{gl:33336,rb:!0},rg8sint:{gl:33335,rb:!0},r16uint:{gl:33332,rb:!0},r16sint:{gl:33331,rb:!0},r16float:{gl:33325,rb:!0,r:Am},r16unorm:{gl:33322,rb:!0,r:Tm},r16snorm:{gl:36760,r:Lm},"rgba4unorm-webgl":{gl:32854,rb:!0},"rgb565unorm-webgl":{gl:36194,rb:!0},"rgb5a1unorm-webgl":{gl:32855,rb:!0},"rgb8unorm-webgl":{gl:32849},"rgb8snorm-webgl":{gl:36758},rgba8unorm:{gl:32856},"rgba8unorm-srgb":{gl:35907},rgba8snorm:{gl:36759,r:Pm},rgba8uint:{gl:36220},rgba8sint:{gl:36238},bgra8unorm:{},"bgra8unorm-srgb":{},rg16uint:{gl:33338},rg16sint:{gl:33337},rg16float:{gl:33327,rb:!0,r:Am},rg16unorm:{gl:33324,r:Tm},rg16snorm:{gl:36761,r:Lm},r32uint:{gl:33334,rb:!0},r32sint:{gl:33333,rb:!0},r32float:{gl:33326,r:ou},rgb9e5ufloat:{gl:35901,r:ok},rg11b10ufloat:{gl:35898,rb:!0},rgb10a2unorm:{gl:32857,rb:!0},rgb10a2uint:{gl:36975,rb:!0},"rgb16unorm-webgl":{gl:32852,r:!1},"rgb16snorm-webgl":{gl:36762,r:!1},rg32uint:{gl:33340,rb:!0},rg32sint:{gl:33339,rb:!0},rg32float:{gl:33328,rb:!0,r:ou},rgba16uint:{gl:36214,rb:!0},rgba16sint:{gl:36232,rb:!0},rgba16float:{gl:34842,r:Am},rgba16unorm:{gl:32859,rb:!0,r:Tm},rgba16snorm:{gl:36763,r:Lm},"rgb32float-webgl":{gl:34837,x:oE,r:ou,dataFormat:6407,types:[5126]},rgba32uint:{gl:36208,rb:!0},rgba32sint:{gl:36226,rb:!0},rgba32float:{gl:34836,rb:!0,r:ou},stencil8:{gl:36168,rb:!0},depth16unorm:{gl:33189,dataFormat:6402,types:[5123],rb:!0},depth24plus:{gl:33190,dataFormat:6402,types:[5125]},depth32float:{gl:36012,dataFormat:6402,types:[5126],rb:!0},"depth24plus-stencil8":{gl:35056,rb:!0,depthTexture:!0,dataFormat:34041,types:[34042]},"depth32float-stencil8":{gl:36013,dataFormat:34041,types:[36269],rb:!0},"bc1-rgb-unorm-webgl":{gl:33776,x:ia},"bc1-rgb-unorm-srgb-webgl":{gl:35916,x:oa},"bc1-rgba-unorm":{gl:33777,x:ia},"bc1-rgba-unorm-srgb":{gl:35916,x:oa},"bc2-rgba-unorm":{gl:33778,x:ia},"bc2-rgba-unorm-srgb":{gl:35918,x:oa},"bc3-rgba-unorm":{gl:33779,x:ia},"bc3-rgba-unorm-srgb":{gl:35919,x:oa},"bc4-r-unorm":{gl:36283,x:Zi},"bc4-r-snorm":{gl:36284,x:Zi},"bc5-rg-unorm":{gl:36285,x:Zi},"bc5-rg-snorm":{gl:36286,x:Zi},"bc6h-rgb-ufloat":{gl:36495,x:Ki},"bc6h-rgb-float":{gl:36494,x:Ki},"bc7-rgba-unorm":{gl:36492,x:Ki},"bc7-rgba-unorm-srgb":{gl:36493,x:Ki},"etc2-rgb8unorm":{gl:37492},"etc2-rgb8unorm-srgb":{gl:37494},"etc2-rgb8a1unorm":{gl:37496},"etc2-rgb8a1unorm-srgb":{gl:37497},"etc2-rgba8unorm":{gl:37493},"etc2-rgba8unorm-srgb":{gl:37495},"eac-r11unorm":{gl:37488},"eac-r11snorm":{gl:37489},"eac-rg11unorm":{gl:37490},"eac-rg11snorm":{gl:37491},"astc-4x4-unorm":{gl:37808},"astc-4x4-unorm-srgb":{gl:37840},"astc-5x4-unorm":{gl:37809},"astc-5x4-unorm-srgb":{gl:37841},"astc-5x5-unorm":{gl:37810},"astc-5x5-unorm-srgb":{gl:37842},"astc-6x5-unorm":{gl:37811},"astc-6x5-unorm-srgb":{gl:37843},"astc-6x6-unorm":{gl:37812},"astc-6x6-unorm-srgb":{gl:37844},"astc-8x5-unorm":{gl:37813},"astc-8x5-unorm-srgb":{gl:37845},"astc-8x6-unorm":{gl:37814},"astc-8x6-unorm-srgb":{gl:37846},"astc-8x8-unorm":{gl:37815},"astc-8x8-unorm-srgb":{gl:37847},"astc-10x5-unorm":{gl:37816},"astc-10x5-unorm-srgb":{gl:37848},"astc-10x6-unorm":{gl:37817},"astc-10x6-unorm-srgb":{gl:37849},"astc-10x8-unorm":{gl:37818},"astc-10x8-unorm-srgb":{gl:37850},"astc-10x10-unorm":{gl:37819},"astc-10x10-unorm-srgb":{gl:37851},"astc-12x10-unorm":{gl:37820},"astc-12x10-unorm-srgb":{gl:37852},"astc-12x12-unorm":{gl:37821},"astc-12x12-unorm-srgb":{gl:37853},"pvrtc-rgb4unorm-webgl":{gl:35840},"pvrtc-rgba4unorm-webgl":{gl:35842},"pvrtc-rgb2unorm-webgl":{gl:35841},"pvrtc-rgba2unorm-webgl":{gl:35843},"etc1-rbg-unorm-webgl":{gl:36196},"atc-rgb-unorm-webgl":{gl:35986},"atc-rgba-unorm-webgl":{gl:35986},"atc-rgbai-unorm-webgl":{gl:34798}}});var uE,lu,fE=b(()=>{N();na();Qi();uE={"depth-clip-control":"EXT_depth_clamp","timestamp-query":"EXT_disjoint_timer_query_webgl2","compilation-status-async-webgl":"KHR_parallel_shader_compile","html-in-canvas":r=>rh()&&typeof r.texElementImage2D=="function","polygon-mode-webgl":"WEBGL_polygon_mode","provoking-vertex-webgl":"WEBGL_provoking_vertex","shader-clip-cull-distance-webgl":"WEBGL_clip_cull_distance","shader-noperspective-interpolation-webgl":"NV_shader_noperspective_interpolation","shader-conservative-depth-webgl":"EXT_conservative_depth"},lu=class extends Wo{constructor(t,n,i){super([],i);d(this,"gl");d(this,"extensions");d(this,"testedFeatures",new Set);this.gl=t,this.extensions=n,Rt(t,"EXT_color_buffer_float",n)}*[Symbol.iterator](){let t=this.getFeatures();for(let n of t)this.has(n)&&(yield n);return[]}has(t){return this.disabledFeatures?.[t]?!1:(this.testedFeatures.has(t)||(this.testedFeatures.add(t),sE(t)&&Cm(this.gl,t,this.extensions)&&this.features.add(t),this.getWebGLFeature(t)&&this.features.add(t)),this.features.has(t))}initializeFeatures(){let t=this.getFeatures().filter(n=>n!=="polygon-mode-webgl");for(let n of t)this.has(n)}getFeatures(){return[...Object.keys(uE),...Object.keys(su)]}getWebGLFeature(t){let n=uE[t];return typeof n=="string"?!!Rt(this.gl,n,this.extensions):typeof n=="function"?n(this.gl):!!n}}});var uu,dE=b(()=>{N();uu=class extends Vo{constructor(t){super();d(this,"gl");d(this,"limits",{});this.gl=t}get maxTextureDimension1D(){return 0}get maxTextureDimension2D(){return this.getParameter(3379)}get maxTextureDimension3D(){return this.getParameter(32883)}get maxTextureArrayLayers(){return this.getParameter(35071)}get maxBindGroups(){return 0}get maxBindGroupsPlusVertexBuffers(){return 0}get maxBindingsPerBindGroup(){return 0}get maxDynamicUniformBuffersPerPipelineLayout(){return 0}get maxDynamicStorageBuffersPerPipelineLayout(){return 0}get maxSampledTexturesPerShaderStage(){return this.getParameter(35660)}get maxSamplersPerShaderStage(){return this.getParameter(35661)}get maxStorageBuffersPerShaderStage(){return 0}get maxStorageBuffersInVertexStage(){return 0}get maxStorageBuffersInFragmentStage(){return 0}get maxStorageTexturesPerShaderStage(){return 0}get maxStorageTexturesInVertexStage(){return 0}get maxStorageTexturesInFragmentStage(){return 0}get maxUniformBuffersPerShaderStage(){return this.getParameter(35375)}get maxUniformBufferBindingSize(){return this.getParameter(35376)}get maxStorageBufferBindingSize(){return 0}get maxBufferSize(){return Number.MAX_SAFE_INTEGER}get minUniformBufferOffsetAlignment(){return this.getParameter(35380)}get minStorageBufferOffsetAlignment(){return 0}get maxVertexBuffers(){return 16}get maxVertexAttributes(){return this.getParameter(34921)}get maxVertexBufferArrayStride(){return 2048}get maxInterStageShaderVariables(){return this.getParameter(35659)}get maxColorAttachments(){return this.getParameter(36063)}get maxColorAttachmentBytesPerSample(){return 0}get maxComputeWorkgroupStorageSize(){return 0}get maxComputeInvocationsPerWorkgroup(){return 0}get maxComputeWorkgroupSizeX(){return 0}get maxComputeWorkgroupSizeY(){return 0}get maxComputeWorkgroupSizeZ(){return 0}get maxComputeWorkgroupsPerDimension(){return 0}getParameter(t){return this.limits[t]===void 0&&(this.limits[t]=this.gl.getParameter(t)),this.limits[t]||0}}});function lk(r){return r<34069?r+34069:r}function uk(r){switch(r){case 36053:return"success";case 36054:return"Mismatched attachments";case 36055:return"No attachments";case 36057:return"Height/width mismatch";case 36061:return"Unsupported or split attachments";case 36182:return"Samples mismatch";default:return`${r}`}}var tr,fu=b(()=>{N();Qi();tr=class extends yn{constructor(t,n){super(t,n);d(this,"device");d(this,"gl");d(this,"handle");d(this,"colorAttachments",[]);d(this,"depthStencilAttachment",null);let i=n.handle,o=i===null;this.device=t,this.gl=t.gl,this.handle=i||o?i:this.gl.createFramebuffer(),o||(t._setWebGLDebugMetadata(this.handle,this,{spector:this.props}),n.handle||(this.autoCreateAttachmentTextures(),this.updateAttachments()))}destroy(){super.destroy(),!this.destroyed&&this.handle!==null&&!this.props.handle&&this.gl.deleteFramebuffer(this.handle)}updateAttachments(){let t=this.gl.bindFramebuffer(36160,this.handle);for(let n=0;n<this.colorAttachments.length;++n){let i=this.colorAttachments[n];if(i){let o=36064+n;this._attachTextureView(o,i)}}if(this.depthStencilAttachment){let n=lE(this.depthStencilAttachment.props.format);this._attachTextureView(n,this.depthStencilAttachment)}if(this.device.props.debug){let n=this.gl.checkFramebufferStatus(36160);if(n!==36053)throw new Error(`Framebuffer ${uk(n)}`)}this.gl.bindFramebuffer(36160,t)}_attachTextureView(t,n){let{gl:i}=this.device,{texture:o}=n,s=n.props.baseMipLevel,a=n.props.baseArrayLayer;switch(i.bindTexture(o.glTarget,o.handle),o.glTarget){case 35866:case 32879:i.framebufferTextureLayer(36160,t,o.handle,s,a);break;case 34067:let c=lk(a);i.framebufferTexture2D(36160,t,c,o.handle,s);break;case 3553:i.framebufferTexture2D(36160,t,3553,o.handle,s);break;default:throw new Error("Illegal texture type")}i.bindTexture(o.glTarget,null)}resizeAttachments(t,n){if(this.handle===null){this.width=t,this.height=n;return}super.resizeAttachments(t,n)}}});var du,hE=b(()=>{N();fu();du=class extends pi{constructor(t,n){super(n);d(this,"device");d(this,"handle",null);d(this,"_framebuffer",null);this.device=t,this._setAutoCreatedCanvasId(`${this.device.id}-canvas`),this._configureDevice()}get[Symbol.toStringTag](){return"WebGLCanvasContext"}_configureDevice(){(this.drawingBufferWidth!==this._framebuffer?.width||this.drawingBufferHeight!==this._framebuffer?.height)&&this._framebuffer?.resize([this.drawingBufferWidth,this.drawingBufferHeight])}_getCurrentFramebuffer(){return this._framebuffer||(this._framebuffer=new tr(this.device,{id:"canvas-context-framebuffer",handle:null,width:this.drawingBufferWidth,height:this.drawingBufferHeight})),this._framebuffer}}});var hu,pE=b(()=>{N();hu=class extends jo{constructor(t,n={}){super(n);d(this,"device");d(this,"handle",null);d(this,"context2d");this.device=t;let i=`${this[Symbol.toStringTag]}(${this.id})`;if(!this.device.getDefaultCanvasContext().offscreenCanvas)throw new Error(`${i}: WebGL PresentationContext requires the default CanvasContext canvas to be an OffscreenCanvas`);let s=this.canvas.getContext("2d");if(!s)throw new Error(`${i}: Failed to create 2d presentation context`);this.context2d=s,this._setAutoCreatedCanvasId(`${this.device.id}-presentation-canvas`),this._configureDevice(),this._startObservers()}get[Symbol.toStringTag](){return"WebGLPresentationContext"}present(){this._resizeDrawingBufferIfNeeded(),this.device.submit();let t=this.device.getDefaultCanvasContext(),[n,i]=t.getDrawingBufferSize();if(!(this.drawingBufferWidth===0||this.drawingBufferHeight===0||n===0||i===0||t.canvas.width===0||t.canvas.height===0)){if(n!==this.drawingBufferWidth||i!==this.drawingBufferHeight||t.canvas.width!==this.drawingBufferWidth||t.canvas.height!==this.drawingBufferHeight)throw new Error(`${this[Symbol.toStringTag]}(${this.id}): Default canvas context size ${n}x${i} does not match presentation size ${this.drawingBufferWidth}x${this.drawingBufferHeight}`);this.context2d.clearRect(0,0,this.drawingBufferWidth,this.drawingBufferHeight),this.context2d.drawImage(t.canvas,0,0)}}_configureDevice(){}_getCurrentFramebuffer(t){let n=this.device.getDefaultCanvasContext();return n.setDrawingBufferSize(this.drawingBufferWidth,this.drawingBufferHeight),n.getCurrentFramebuffer(t)}}});function mE(r="id"){Mm[r]=Mm[r]||1;let e=Mm[r]++;return`${r}-${e}`}var Mm,gE=b(()=>{Mm={}});function fk(r){return r&z.INDEX?34963:r&z.VERTEX?34962:r&z.UNIFORM?35345:34962}function dk(r){return r&z.INDEX||r&z.VERTEX?35044:r&z.UNIFORM?35048:35044}var Bt,pu=b(()=>{N();Bt=class extends z{constructor(t,n={}){super(t,n);d(this,"device");d(this,"gl");d(this,"handle");d(this,"glTarget");d(this,"glUsage");d(this,"glIndexType",5123);d(this,"byteLength",0);d(this,"bytesUsed",0);this.device=t,this.gl=this.device.gl;let i=typeof n=="object"?n.handle:void 0;this.handle=i||this.gl.createBuffer(),t._setWebGLDebugMetadata(this.handle,this,{spector:{...this.props,data:typeof this.props.data}}),this.glTarget=fk(this.props.usage),this.glUsage=dk(this.props.usage),this.glIndexType=this.props.indexType==="uint32"?5125:5123,n.data?this._initWithData(n.data,n.byteOffset,n.byteLength):this._initWithByteLength(n.byteLength||0)}destroy(){!this.destroyed&&this.handle&&(this.removeStats(),this.props.handle?this.trackDeallocatedReferencedMemory("Buffer"):(this.trackDeallocatedMemory(),this.gl.deleteBuffer(this.handle)),this.destroyed=!0,this.handle=null)}_initWithData(t,n=0,i=t.byteLength+n){let o=this.glTarget;this.gl.bindBuffer(o,this.handle),this.gl.bufferData(o,i,this.glUsage),this.gl.bufferSubData(o,n,t),this.gl.bindBuffer(o,null),this.bytesUsed=i,this.byteLength=i,this._setDebugData(t,n,i),this.props.handle?this.trackReferencedMemory(i,"Buffer"):this.trackAllocatedMemory(i)}_initWithByteLength(t){let n=t;t===0&&(n=new Float32Array(0));let i=this.glTarget;return this.gl.bindBuffer(i,this.handle),this.gl.bufferData(i,n,this.glUsage),this.gl.bindBuffer(i,null),this.bytesUsed=t,this.byteLength=t,this._setDebugData(null,0,t),this.props.handle?this.trackReferencedMemory(t,"Buffer"):this.trackAllocatedMemory(t),this}write(t,n=0){let i=ArrayBuffer.isView(t)?t:new Uint8Array(t),o=0,s=void 0,a=36663;this.gl.bindBuffer(a,this.handle),o!==0||s!==void 0?this.gl.bufferSubData(a,n,i,o,s):this.gl.bufferSubData(a,n,i),this.gl.bindBuffer(a,null),this._setDebugData(t,n,t.byteLength)}async mapAndWriteAsync(t,n=0,i=this.byteLength-n){let o=new ArrayBuffer(i);await t(o,"copied"),this.write(o,n)}async readAsync(t=0,n){return this.readSyncWebGL(t,n)}async mapAndReadAsync(t,n=0,i){let o=await this.readAsync(n,i);return await t(o.buffer,"copied")}readSyncWebGL(t=0,n){n=n??this.byteLength-t;let i=new Uint8Array(n),o=0;return this.gl.bindBuffer(36662,this.handle),this.gl.getBufferSubData(36662,t,i,o,n),this.gl.bindBuffer(36662,null),this._setDebugData(i,t,n),i}}});function yE(r){let e=r.split(/\r?\n/),t=[];for(let n of e){if(n.length<=1)continue;let i=n.trim(),o=n.split(":"),s=o[0]?.trim();if(o.length===2){let[p,m]=o;if(!p||!m){t.push({message:i,type:mu(s||"info"),lineNum:0,linePos:0});continue}t.push({message:m.trim(),type:mu(p),lineNum:0,linePos:0});continue}let[a,c,l,...u]=o;if(!a||!c||!l){t.push({message:o.slice(1).join(":").trim()||i,type:mu(s||"info"),lineNum:0,linePos:0});continue}let f=parseInt(l,10);Number.isNaN(f)&&(f=0);let h=parseInt(c,10);Number.isNaN(h)&&(h=0),t.push({message:u.join(":").trim(),type:mu(a),lineNum:f,linePos:h})}return t}function mu(r){let e=["warning","error","info"],t=r.toLowerCase();return e.includes(t)?t:"info"}var _E=b(()=>{});function hk(r){return r.split(/\r?\n/).find(e=>e.trim())?.trim()}var gu,bE=b(()=>{N();_E();gu=class extends gn{constructor(t,n){super(t,n);d(this,"device");d(this,"handle");d(this,"_compilationInfoLog","");this.device=t;let i=this.props.handle;switch(this.props.stage){case"vertex":this.handle=i||this.device.gl.createShader(35633);break;case"fragment":this.handle=i||this.device.gl.createShader(35632);break;default:throw new Error(this.props.stage)}t._setWebGLDebugMetadata(this.handle,this,{spector:this.props});let o=this._compile(this.source);o&&typeof o.catch=="function"&&o.catch(()=>{this.compilationStatus="error"})}destroy(){this.handle&&(this.removeStats(),this.device.gl.deleteShader(this.handle),this.destroyed=!0,this.handle.destroyed=!0)}get asyncCompilationStatus(){return this._waitForCompilationComplete().then(()=>(this._getCompilationStatus(),this.compilationStatus))}async getCompilationInfo(){return await this._waitForCompilationComplete(),this.getCompilationInfoSync()}getCompilationInfoSync(){let t=this._getCompilationInfoLog();return t?yE(t):[]}getTranslatedSource(){return this.device.getExtension("WEBGL_debug_shaders").WEBGL_debug_shaders?.getTranslatedShaderSource(this.handle)||null}_compile(t){t=t.startsWith("#version ")?t:`#version 300 es
${t}`;let{gl:n}=this.device;if(n.shaderSource(this.handle,t),n.compileShader(this.handle),!this.device.props.debug){this.compilationStatus="pending";return}if(!this.device.features.has("compilation-status-async-webgl")){if(this._getCompilationStatus(),this.debugShader(),this.compilationStatus==="error")throw new Error(this._getCompilationErrorMessage(t));return}return T.once(1,"Shader compilation is asynchronous")(),this._waitForCompilationComplete().then(()=>{T.info(2,`Shader ${this.id} - async compilation complete: ${this.compilationStatus}`)(),this._getCompilationStatus(),this.debugShader()})}async _waitForCompilationComplete(){let t=async o=>await new Promise(s=>setTimeout(s,o));if(!this.device.features.has("compilation-status-async-webgl")){await t(10);return}let{gl:i}=this.device;for(;;){if(i.getShaderParameter(this.handle,37297))return;await t(10)}}_getCompilationStatus(){this.compilationStatus=this.device.gl.getShaderParameter(this.handle,35713)?"success":"error",this.compilationStatus==="error"&&this._getCompilationInfoLog()}_getCompilationErrorMessage(t){let n=`${this.props.stage} shader ${this.props.id}`,i=hk(this._getCompilationInfoLog()),o=this.getCompilationInfoSync(),s=o.find(f=>f.type==="error"&&f.message.trim())||o.find(f=>f.message.trim())||o.find(f=>f.type==="error")||o[0];if(!s)return i?`GLSL compilation errors in ${n}: ${i}`:`GLSL compilation errors in ${n}: WebGL did not provide a shader compiler log`;let a=s.lineNum?t.split(/\r?\n/)[s.lineNum-1]?.trim():void 0,c=s.lineNum?` line ${s.lineNum}`:"",l=a?`
Source: ${a}`:"",u=s.message.trim()||i||"WebGL did not provide a shader compiler log";return`GLSL compilation errors in ${n}:${c}: ${u}${l}`}_getCompilationInfoLog(){let t=this.device.gl.getShaderInfoLog(this.handle)?.trim();return t&&(this._compilationInfoLog=t),this._compilationInfoLog}}});function vE(r,e,t,n){if(yk(e))return n(r);let i=r;i.pushState();try{return pk(r,e),Mt(i.gl,t),n(r)}finally{i.popState()}}function pk(r,e){let t=r,{gl:n}=t;if(e.cullMode)switch(e.cullMode){case"none":n.disable(2884);break;case"front":n.enable(2884),n.cullFace(1028);break;case"back":n.enable(2884),n.cullFace(1029);break}if(e.frontFace&&n.frontFace(Hn("frontFace",e.frontFace,{ccw:2305,cw:2304})),e.unclippedDepth&&r.features.has("depth-clip-control")&&n.enable(34383),e.depthBias!==void 0&&(n.enable(32823),n.polygonOffset(e.depthBias,e.depthBiasSlopeScale||0)),e.provokingVertex&&r.features.has("provoking-vertex-webgl")){let o=t.getExtension("WEBGL_provoking_vertex").WEBGL_provoking_vertex,s=Hn("provokingVertex",e.provokingVertex,{first:36429,last:36430});o?.provokingVertexWEBGL(s)}if((e.polygonMode||e.polygonOffsetLine)&&r.features.has("polygon-mode-webgl")){if(e.polygonMode){let o=t.getExtension("WEBGL_polygon_mode").WEBGL_polygon_mode,s=Hn("polygonMode",e.polygonMode,{fill:6914,line:6913});o?.polygonModeWEBGL(1028,s),o?.polygonModeWEBGL(1029,s)}e.polygonOffsetLine&&n.enable(10754)}if(r.features.has("shader-clip-cull-distance-webgl")&&(e.clipDistance0&&n.enable(12288),e.clipDistance1&&n.enable(12289),e.clipDistance2&&n.enable(12290),e.clipDistance3&&n.enable(12291),e.clipDistance4&&n.enable(12292),e.clipDistance5&&n.enable(12293),e.clipDistance6&&n.enable(12294),e.clipDistance7&&n.enable(12295)),e.depthWriteEnabled!==void 0&&n.depthMask(gk("depthWriteEnabled",e.depthWriteEnabled)),e.depthCompare&&(e.depthCompare!=="always"?n.enable(2929):n.disable(2929),n.depthFunc(_u("depthCompare",e.depthCompare))),e.clearDepth!==void 0&&n.clearDepth(e.clearDepth),e.stencilWriteMask){let i=e.stencilWriteMask;n.stencilMaskSeparate(1028,i),n.stencilMaskSeparate(1029,i)}if(e.stencilReadMask&&T.warn("stencilReadMask not supported under WebGL"),e.stencilCompare){let i=e.stencilReadMask||4294967295,o=_u("depthCompare",e.stencilCompare);e.stencilCompare!=="always"?n.enable(2960):n.disable(2960),n.stencilFuncSeparate(1028,o,0,i),n.stencilFuncSeparate(1029,o,0,i)}if(e.stencilPassOperation&&e.stencilFailOperation&&e.stencilDepthFailOperation){let i=Im("stencilPassOperation",e.stencilPassOperation),o=Im("stencilFailOperation",e.stencilFailOperation),s=Im("stencilDepthFailOperation",e.stencilDepthFailOperation);n.stencilOpSeparate(1028,o,s,i),n.stencilOpSeparate(1029,o,s,i)}switch(e.blend){case!0:n.enable(3042);break;case!1:n.disable(3042);break;default:}if(e.blendColorOperation||e.blendAlphaOperation){let i=xE("blendColorOperation",e.blendColorOperation||"add"),o=xE("blendAlphaOperation",e.blendAlphaOperation||"add");n.blendEquationSeparate(i,o);let s=yu("blendColorSrcFactor",e.blendColorSrcFactor||"one"),a=yu("blendColorDstFactor",e.blendColorDstFactor||"zero"),c=yu("blendAlphaSrcFactor",e.blendAlphaSrcFactor||"one"),l=yu("blendAlphaDstFactor",e.blendAlphaDstFactor||"zero");n.blendFuncSeparate(s,a,c,l)}}function _u(r,e){return Hn(r,e,{never:512,less:513,equal:514,"less-equal":515,greater:516,"not-equal":517,"greater-equal":518,always:519})}function Im(r,e){return Hn(r,e,{keep:7680,zero:0,replace:7681,invert:5386,"increment-clamp":7682,"decrement-clamp":7683,"increment-wrap":34055,"decrement-wrap":34056})}function xE(r,e){return Hn(r,e,{add:32774,subtract:32778,"reverse-subtract":32779,min:32775,max:32776})}function yu(r,e,t="color"){return Hn(r,e,{one:1,zero:0,src:768,"one-minus-src":769,dst:774,"one-minus-dst":775,"src-alpha":770,"one-minus-src-alpha":771,"dst-alpha":772,"one-minus-dst-alpha":773,"src-alpha-saturated":776,constant:t==="color"?32769:32771,"one-minus-constant":t==="color"?32770:32772,src1:768,"one-minus-src1":769,"src1-alpha":770,"one-minus-src1-alpha":771})}function mk(r,e){return`Illegal parameter ${e} for ${r}`}function Hn(r,e,t){if(!(e in t))throw new Error(mk(r,e));return t[e]}function gk(r,e){return e}function yk(r){let e=!0;for(let t in r){e=!1;break}return e}var Rm=b(()=>{N();Xi()});function bu(r){let e={};return r.addressModeU&&(e[10242]=Bm(r.addressModeU)),r.addressModeV&&(e[10243]=Bm(r.addressModeV)),r.addressModeW&&(e[32882]=Bm(r.addressModeW)),r.magFilter&&(e[10240]=Om(r.magFilter)),(r.minFilter||r.mipmapFilter)&&(e[10241]=_k(r.minFilter||"linear",r.mipmapFilter)),r.lodMinClamp!==void 0&&(e[33082]=r.lodMinClamp),r.lodMaxClamp!==void 0&&(e[33083]=r.lodMaxClamp),r.type==="comparison-sampler"&&(e[34892]=34894),r.compare&&(e[34893]=_u("compare",r.compare)),r.maxAnisotropy&&(e[34046]=r.maxAnisotropy),e}function Bm(r){switch(r){case"clamp-to-edge":return 33071;case"repeat":return 10497;case"mirror-repeat":return 33648}}function Om(r){switch(r){case"nearest":return 9728;case"linear":return 9729}}function _k(r,e="none"){if(!e)return Om(r);switch(e){case"none":return Om(r);case"nearest":switch(r){case"nearest":return 9984;case"linear":return 9985}break;case"linear":switch(r){case"nearest":return 9986;case"linear":return 9987}}}var km=b(()=>{Rm()});var xu,wE=b(()=>{N();km();xu=class extends pn{constructor(t,n){super(t,n);d(this,"device");d(this,"handle");d(this,"parameters");this.device=t,this.parameters=bu(n),this.handle=n.handle||this.device.gl.createSampler(),this._setSamplerParameters(this.parameters)}destroy(){this.handle&&(this.device.gl.deleteSampler(this.handle),this.handle=void 0)}toString(){return`Sampler(${this.id},${JSON.stringify(this.props)})`}_setSamplerParameters(t){for(let[n,i]of Object.entries(t)){let o=Number(n);switch(o){case 33082:case 33083:this.device.gl.samplerParameterf(this.handle,o,i);break;default:this.device.gl.samplerParameteri(this.handle,o,i);break}}}}});function Ot(r,e,t){if(bk(e))return t(r);let{nocatch:n=!0}=e,i=It.get(r);i.push(),Mt(r,e);let o;if(n)o=t(r),i.pop();else try{o=t(r)}finally{i.pop()}return o}function bk(r){for(let e in r)return!1;return!0}var vu=b(()=>{Xi();wm()});var rr,Dm=b(()=>{N();rr=class extends mn{constructor(t,n){super(t,{...Y.defaultProps,...n});d(this,"device");d(this,"gl");d(this,"handle");d(this,"texture");this.device=t,this.gl=this.device.gl,this.handle=null,this.texture=n.texture}}});function wu(r){return xk[r]}var xk,Nm=b(()=>{xk={5124:"sint32",5125:"uint32",5122:"sint16",5123:"uint16",5120:"sint8",5121:"uint8",5126:"float32",5131:"float16",33635:"uint16",32819:"uint16",32820:"uint16",33640:"uint32",35899:"uint32",35902:"uint32",34042:"uint32",36269:"uint32"}});function vk(r,e=0){return e?new r.constructor(r.buffer,r.byteOffset+e,(r.byteLength-e)/r.BYTES_PER_ELEMENT):r}function wk(r,e){if(e%r.BYTES_PER_ELEMENT!==0)throw new Error(`Texture byteOffset ${e} must align to typed array element size ${r.BYTES_PER_ELEMENT}`);return e/r.BYTES_PER_ELEMENT}function Ek(r){switch(r){case"1d":break;case"2d":return 3553;case"3d":return 32879;case"cube":return 34067;case"2d-array":return 35866;case"cube-array":break}throw new Error(r)}function sa(r,e,t){return e==="cube"?34069+t:r}var nr,Eu=b(()=>{N();Qi();km();vu();Dm();Nm();nr=class extends Y{constructor(t,n){super(t,n,{byteAlignment:1});d(this,"device");d(this,"gl");d(this,"handle");d(this,"sampler");d(this,"view");d(this,"glTarget");d(this,"glFormat");d(this,"glType");d(this,"glInternalFormat");d(this,"compressed");d(this,"_textureUnit",0);d(this,"_framebuffer",null);d(this,"_framebufferAttachmentKey",null);this.device=t,this.gl=this.device.gl;let i=cu(this.props.format);if(this.glTarget=Ek(this.props.dimension),this.glInternalFormat=i.internalFormat,this.glFormat=i.format,this.glType=i.type,this.compressed=i.compressed,this.isHandleBorrowed&&this.props.handle===void 0)throw new Error("Borrowed WebGL textures require a texture handle");if(this.handle=this.props.handle||this.gl.createTexture(),this.device._setWebGLDebugMetadata(this.handle,this,{spector:this.props}),!this.isHandleBorrowed){this.gl.bindTexture(this.glTarget,this.handle);let{dimension:o,width:s,height:a,depth:c,mipLevels:l,glTarget:u,glInternalFormat:f}=this;if(!this.compressed)switch(o){case"2d":case"cube":this.gl.texStorage2D(u,l,f,s,a);break;case"2d-array":case"3d":this.gl.texStorage3D(u,l,f,s,a,c);break;default:throw new Error(o)}this.gl.bindTexture(this.glTarget,null),this._initializeData(n.data)}this.ownsHandle?this.trackAllocatedMemory(this.getAllocatedByteLength(),"Texture"):this.trackReferencedMemory(this.getAllocatedByteLength(),"Texture"),this.isHandleBorrowed||this.setSampler(this.props.sampler),this.view=new rr(this.device,{...this.props,texture:this}),Object.seal(this)}destroy(){this.handle&&(this._framebuffer?.destroy(),this._framebuffer=null,this._framebufferAttachmentKey=null,this.removeStats(),this.ownsHandle?(this.gl.deleteTexture(this.handle),this.trackDeallocatedMemory("Texture")):this.trackDeallocatedReferencedMemory("Texture"),this.destroyed=!0)}createView(t){return new rr(this.device,{...t,texture:this})}clone(t){if(this.isHandleBorrowed&&t&&(t.width!==this.width||t.height!==this.height))throw new Error(`Cannot resize borrowed read-only ${this}`);return super.clone(t)}setSampler(t={}){this._assertWritable("set sampler parameters on"),super.setSampler(t);let n=bu(this.sampler.props);this._setSamplerParameters(n)}copyExternalImage(t){this._assertWritable("copy external image data into");let n=this._normalizeCopyExternalImageOptions(t);if(n.sourceX||n.sourceY)throw new Error("WebGL does not support sourceX/sourceY)");let{glFormat:i,glType:o}=this,{image:s,depth:a,mipLevel:c,x:l,y:u,z:f,width:h,height:p}=n,m=sa(this.glTarget,this.dimension,f),g=n.flipY?{37440:!0}:{};return this.gl.bindTexture(this.glTarget,this.handle),Ot(this.gl,g,()=>{switch(this.dimension){case"2d":case"cube":this.gl.texSubImage2D(m,c,l,u,h,p,i,o,s);break;case"2d-array":case"3d":this.gl.texSubImage3D(m,c,l,u,f,h,p,a,i,o,s);break;default:}}),this.gl.bindTexture(this.glTarget,null),{width:n.width,height:n.height}}copyElementImage(t){this._assertWritable("copy element image data into");let n=this._normalizeCopyElementImageOptions(t),{glFormat:i}=this,{element:o,depth:s,mipLevel:a,sourceX:c,sourceY:l,sourceWidth:u,sourceHeight:f,x:h,y:p,z:m,width:g,height:y}=n,x=sa(this.glTarget,this.dimension,m),v=n.flipY?{37440:!0}:{},_=this.gl;if(s!==1||this.dimension!=="2d"&&this.dimension!=="cube")throw new Error(`${this} copyElementImage only supports 2d and cube textures on WebGL`);if(a!==0||h!==0||p!==0)throw new Error(`${this} copyElementImage only supports full base-level uploads on WebGL`);if(typeof _.texElementImage2D!="function")throw new Error(`${this} copyElementImage is not supported by this WebGL implementation`);return this.gl.bindTexture(this.glTarget,this.handle),Ot(this.gl,v,()=>{_.texElementImage2D?.(x,i,o,{sx:c,sy:l,swidth:u??g,sheight:f??y,width:g,height:y})}),this.gl.bindTexture(this.glTarget,null),{width:n.width,height:n.height}}copyImageData(t){super.copyImageData(t)}readBuffer(t={},n){if(!n)throw new Error(`${this} readBuffer requires a destination buffer`);let i=this._getSupportedColorReadOptions(t),o=t.byteOffset??0,s=this.computeMemoryLayout(i);if(n.byteLength<o+s.byteLength)throw new Error(`${this} readBuffer target is too small (${n.byteLength} < ${o+s.byteLength})`);let a=n;this.gl.bindBuffer(35051,a.handle);try{this._readColorTextureLayers(i,s,c=>{this.gl.readPixels(i.x,i.y,i.width,i.height,this.glFormat,this.glType,o+c)})}finally{this.gl.bindBuffer(35051,null)}return n}async readDataAsync(t={}){throw new Error(`${this} readDataAsync is deprecated; use readBuffer() with an explicit destination buffer or DynamicTexture.readAsync()`)}writeBuffer(t,n={}){this._assertWritable("write buffer data into");let i=this._normalizeTextureWriteOptions(n),{width:o,height:s,depthOrArrayLayers:a,mipLevel:c,byteOffset:l,x:u,y:f,z:h}=i,{glFormat:p,glType:m,compressed:g}=this,y=sa(this.glTarget,this.dimension,h);if(g)throw new Error("writeBuffer for compressed textures is not implemented in WebGL");let{bytesPerPixel:x}=this.device.getTextureFormatInfo(this.format),v=x?i.bytesPerRow/x:void 0,_={3317:this.byteAlignment,...v!==void 0?{3314:v}:{},32878:i.rowsPerImage};this.gl.bindTexture(this.glTarget,this.handle),this.gl.bindBuffer(35052,t.handle),Ot(this.gl,_,()=>{switch(this.dimension){case"2d":case"cube":this.gl.texSubImage2D(y,c,u,f,o,s,p,m,l);break;case"2d-array":case"3d":this.gl.texSubImage3D(y,c,u,f,h,o,s,a,p,m,l);break;default:}}),this.gl.bindBuffer(35052,null),this.gl.bindTexture(this.glTarget,null)}writeData(t,n={}){this._assertWritable("write data into");let i=this._normalizeTextureWriteOptions(n),o=ArrayBuffer.isView(t)?t:new Uint8Array(t),{width:s,height:a,depthOrArrayLayers:c,mipLevel:l,x:u,y:f,z:h,byteOffset:p}=i,{glFormat:m,glType:g,compressed:y}=this,x=sa(this.glTarget,this.dimension,h),v;if(!y){let{bytesPerPixel:A}=this.device.getTextureFormatInfo(this.format);A&&(v=i.bytesPerRow/A)}let _=this.compressed?{}:{3317:this.byteAlignment,...v!==void 0?{3314:v}:{},32878:i.rowsPerImage},w=wk(o,p),E=y?vk(o,p):o,S=this._getMipLevelSize(l),C=u===0&&f===0&&h===0&&s===S.width&&a===S.height&&c===S.depthOrArrayLayers;this.gl.bindTexture(this.glTarget,this.handle),this.gl.bindBuffer(35052,null),Ot(this.gl,_,()=>{switch(this.dimension){case"2d":case"cube":y?C?this.gl.compressedTexImage2D(x,l,m,s,a,0,E):this.gl.compressedTexSubImage2D(x,l,u,f,s,a,m,E):this.gl.texSubImage2D(x,l,u,f,s,a,m,g,o,w);break;case"2d-array":case"3d":y?C?this.gl.compressedTexImage3D(x,l,m,s,a,c,0,E):this.gl.compressedTexSubImage3D(x,l,u,f,h,s,a,c,m,E):this.gl.texSubImage3D(x,l,u,f,h,s,a,c,m,g,o,w);break;default:}}),this.gl.bindTexture(this.glTarget,null)}_getRowByteAlignment(t,n){return 1}_getFramebuffer(){return this._framebuffer||(this._framebuffer=this.device.createFramebuffer({id:`framebuffer-for-${this.id}`,width:this.width,height:this.height,colorAttachments:[this]})),this._framebuffer}readDataSyncWebGL(t={}){let n=this._getSupportedColorReadOptions(t),i=this.computeMemoryLayout(n),o=wu(this.glType),s=hn(o),a=new s(i.byteLength/s.BYTES_PER_ELEMENT);return this._readColorTextureLayers(n,i,c=>{let l=new s(a.buffer,a.byteOffset+c,i.bytesPerImage/s.BYTES_PER_ELEMENT);this.gl.readPixels(n.x,n.y,n.width,n.height,this.glFormat,this.glType,l)}),a.buffer}_readColorTextureLayers(t,n,i){let o=this._getFramebuffer(),s=n.bytesPerRow/n.bytesPerPixel,a={3333:this.byteAlignment,...s!==t.width?{3330:s}:{}},c=this.gl.getParameter(3074),l=this.gl.bindFramebuffer(36160,o.handle);try{this.gl.readBuffer(36064),Ot(this.gl,a,()=>{for(let u=0;u<t.depthOrArrayLayers;u++)this._attachReadSubresource(o,t.mipLevel,t.z+u),i(u*n.bytesPerImage)})}finally{this.gl.bindFramebuffer(36160,l||null),this.gl.readBuffer(c)}}_attachReadSubresource(t,n,i){let o=`${n}:${i}`;if(this._framebufferAttachmentKey!==o){switch(this.dimension){case"2d":this.gl.framebufferTexture2D(36160,36064,3553,this.handle,n);break;case"cube":this.gl.framebufferTexture2D(36160,36064,sa(this.glTarget,this.dimension,i),this.handle,n);break;case"2d-array":case"3d":this.gl.framebufferTextureLayer(36160,36064,this.handle,n,i);break;default:throw new Error(`${this} color readback does not support ${this.dimension} textures`)}if(this.device.props.debug){let s=Number(this.gl.checkFramebufferStatus(36160));if(s!==36053)throw new Error(`${t} incomplete for ${this} readback (${s})`)}this._framebufferAttachmentKey=o}}generateMipmapsWebGL(t){if(this._assertWritable("generate mipmaps for"),!(!(this.device.isTextureFormatRenderable(this.props.format)&&this.device.isTextureFormatFilterable(this.props.format))&&(T.warn(`${this} is not renderable or filterable, may not be able to generate mipmaps`)(),!t?.force)))try{this.gl.bindTexture(this.glTarget,this.handle),this.gl.generateMipmap(this.glTarget)}catch(i){T.warn(`Error generating mipmap for ${this}: ${i.message}`)()}finally{this.gl.bindTexture(this.glTarget,null)}}_setSamplerParameters(t){T.log(2,`${this.id} sampler parameters`,this.device.getGLKeys(t))(),this.gl.bindTexture(this.glTarget,this.handle);for(let[n,i]of Object.entries(t)){let o=Number(n),s=i;switch(o){case 33082:case 33083:this.gl.texParameterf(this.glTarget,o,s);break;case 10240:case 10241:this.gl.texParameteri(this.glTarget,o,s);break;case 10242:case 10243:case 32882:this.gl.texParameteri(this.glTarget,o,s);break;case 34046:this.device.features.has("texture-filterable-anisotropic-webgl")&&this.gl.texParameteri(this.glTarget,o,s);break;case 34892:case 34893:this.gl.texParameteri(this.glTarget,o,s);break}}this.gl.bindTexture(this.glTarget,null)}_getActiveUnit(){return this.gl.getParameter(34016)-33984}_bind(t){let{gl:n}=this;return t!==void 0&&(this._textureUnit=t,n.activeTexture(33984+t)),n.bindTexture(this.glTarget,this.handle),t}_unbind(t){let{gl:n}=this;return t!==void 0&&(this._textureUnit=t,n.activeTexture(33984+t)),n.bindTexture(this.glTarget,null),t}_assertWritable(t){if(this.isHandleBorrowed)throw new Error(`Cannot ${t} borrowed read-only ${this}`)}}});function EE(r,e,t,n){let i=r,o=n;o===!0&&(o=1),o===!1&&(o=0);let s=typeof o=="number"?[o]:o;switch(t){case 35678:case 35680:case 35679:case 35682:case 36289:case 36292:case 36293:case 36298:case 36299:case 36300:case 36303:case 36306:case 36307:case 36308:case 36311:if(typeof n!="number")throw new Error("samplers must be set to integers");return r.uniform1i(e,n);case 5126:return r.uniform1fv(e,s);case 35664:return r.uniform2fv(e,s);case 35665:return r.uniform3fv(e,s);case 35666:return r.uniform4fv(e,s);case 5124:return r.uniform1iv(e,s);case 35667:return r.uniform2iv(e,s);case 35668:return r.uniform3iv(e,s);case 35669:return r.uniform4iv(e,s);case 35670:return r.uniform1iv(e,s);case 35671:return r.uniform2iv(e,s);case 35672:return r.uniform3iv(e,s);case 35673:return r.uniform4iv(e,s);case 5125:return i.uniform1uiv(e,s,1);case 36294:return i.uniform2uiv(e,s,2);case 36295:return i.uniform3uiv(e,s,3);case 36296:return i.uniform4uiv(e,s,4);case 35674:return r.uniformMatrix2fv(e,!1,s);case 35675:return r.uniformMatrix3fv(e,!1,s);case 35676:return r.uniformMatrix4fv(e,!1,s);case 35685:return i.uniformMatrix2x3fv(e,!1,s);case 35686:return i.uniformMatrix2x4fv(e,!1,s);case 35687:return i.uniformMatrix3x2fv(e,!1,s);case 35688:return i.uniformMatrix3x4fv(e,!1,s);case 35689:return i.uniformMatrix4x2fv(e,!1,s);case 35690:return i.uniformMatrix4x3fv(e,!1,s)}throw new Error("Illegal uniform")}var SE=b(()=>{});function PE(r){return Pk[r]}function Su(r){return Sk[r]}function Pu(r){return!!LE[r]}function TE(r){return LE[r]}var Sk,LE,Pk,Tu=b(()=>{Sk={5126:"f32",35664:"vec2<f32>",35665:"vec3<f32>",35666:"vec4<f32>",5124:"i32",35667:"vec2<i32>",35668:"vec3<i32>",35669:"vec4<i32>",5125:"u32",36294:"vec2<u32>",36295:"vec3<u32>",36296:"vec4<u32>",35670:"f32",35671:"vec2<f32>",35672:"vec3<f32>",35673:"vec4<f32>",35674:"mat2x2<f32>",35685:"mat2x3<f32>",35686:"mat2x4<f32>",35687:"mat3x2<f32>",35675:"mat3x3<f32>",35688:"mat3x4<f32>",35689:"mat4x2<f32>",35690:"mat4x3<f32>",35676:"mat4x4<f32>"},LE={35678:{viewDimension:"2d",sampleType:"float"},35680:{viewDimension:"cube",sampleType:"float"},35679:{viewDimension:"3d",sampleType:"float"},35682:{viewDimension:"3d",sampleType:"depth"},36289:{viewDimension:"2d-array",sampleType:"float"},36292:{viewDimension:"2d-array",sampleType:"depth"},36293:{viewDimension:"cube",sampleType:"float"},36298:{viewDimension:"2d",sampleType:"sint"},36299:{viewDimension:"3d",sampleType:"sint"},36300:{viewDimension:"cube",sampleType:"sint"},36303:{viewDimension:"2d-array",sampleType:"uint"},36306:{viewDimension:"2d",sampleType:"uint"},36307:{viewDimension:"3d",sampleType:"uint"},36308:{viewDimension:"cube",sampleType:"uint"},36311:{viewDimension:"2d-array",sampleType:"uint"}},Pk={uint8:5121,sint8:5120,unorm8:5121,snorm8:5120,uint16:5123,sint16:5122,unorm16:5123,snorm16:5122,uint32:5125,sint32:5124,float16:5131,float32:5126}});function CE(r,e,t={}){let n={attributes:[],bindings:[]};n.attributes=Tk(r,e);let i=Ck(r,e,t);for(let c of i){let l=c.uniforms.map(u=>({name:u.name,format:u.format,byteOffset:u.byteOffset,byteStride:u.byteStride,arrayLength:u.arrayLength}));n.bindings.push({type:"uniform",name:c.name,group:0,location:c.location,visibility:(c.vertex?1:0)|(c.fragment?2:0),minBindingSize:c.byteLength,uniforms:l})}let o=Ak(r,e),s=0;for(let c of o)if(Pu(c.type)){let{viewDimension:l,sampleType:u}=TE(c.type);n.bindings.push({type:"texture",name:c.name,group:0,location:s,viewDimension:l,sampleType:u}),c.textureUnit=s,s+=1}o.length&&(n.uniforms=o);let a=Lk(r,e);return a?.length&&(n.varyings=a),n}function Tk(r,e){let t=[],n=r.getProgramParameter(e,35721);for(let i=0;i<n;i++){let o=r.getActiveAttrib(e,i);if(!o)throw new Error("activeInfo");let{name:s,type:a}=o,c=r.getAttribLocation(e,s);if(c>=0){let l=Su(a),u=/instance/i.test(s)?"instance":"vertex";t.push({name:s,location:c,stepMode:u,type:l})}}return t.sort((i,o)=>i.location-o.location),t}function Lk(r,e){let t=[],n=r.getProgramParameter(e,35971);for(let i=0;i<n;i++){let o=r.getTransformFeedbackVarying(e,i);if(!o)throw new Error("activeInfo");let{name:s,type:a,size:c}=o,l=Su(a),{type:u,components:f}=gi(l);t.push({location:i,name:s,type:u,size:c*f})}return t.sort((i,o)=>i.location-o.location),t}function Ak(r,e){let t=[],n=r.getProgramParameter(e,35718);for(let i=0;i<n;i++){let o=r.getActiveUniform(e,i);if(!o)throw new Error("activeInfo");let{name:s,size:a,type:c}=o,{name:l,isArray:u}=Dk(s),f=r.getUniformLocation(e,l),h={location:f,name:l,size:a,type:c,isArray:u};if(t.push(h),h.size>1)for(let p=0;p<h.size;p++){let m=`${l}[${p}]`;f=r.getUniformLocation(e,m);let g={...h,name:m,location:f};t.push(g)}}return t}function Ck(r,e,t){let n=[],i=Ik(r,e,t);for(let[s,a]of i){n.push(a);try{let c=AE(r,e,s,a.name);Mk(c,a)}catch(c){let l=c instanceof Error?c.message:String(c);T.once(0,`WebGL uniform block reflection failed for "${a.name}"; using supplied std140 metadata. ${l}`)()}}let o=r.getProgramParameter(e,35382);if(!Number.isInteger(o)||o<0)throw new Error(`Failed to reflect WebGL uniform blocks: ACTIVE_UNIFORM_BLOCKS returned ${String(o)}`);for(let s=0;s<o;s++)i.has(s)||n.push(AE(r,e,s));return n.sort((s,a)=>s.location-a.location),n}function Mk(r,e){for(let t of r.uniforms){let n=e.uniforms.find(i=>t.name===i.name||t.name.endsWith(`.${i.name}`));if(!n)throw new Error(`Failed to validate WebGL uniform block "${e.name}": reflected unexpected member "${t.name}"`);if(t.format!==n.format||t.arrayLength!==n.arrayLength||t.byteOffset!==n.byteOffset||t.byteStride!==n.byteStride)throw new Error(`Failed to validate WebGL uniform block "${e.name}": reflected layout for "${t.name}" does not match supplied std140 metadata`)}}function Ik(r,e,t){let n=new Map;for(let o of t.uniformBlockLayouts||[])n.set(o.name,Bk(o));for(let o of t.shaderLayout?.bindings||[])kk(o)&&n.set(o.name,o);let i=new Map;for(let o of n.values()){let s=Rk(r,e,o.name);if(!s)continue;let{blockIndex:a,blockName:c}=s;if(i.has(a))throw new Error(`Multiple supplied uniform block layouts resolve to active WebGL block "${c}"`);i.set(a,{name:c,location:a,byteLength:o.minBindingSize,vertex:!!(o.visibility&&o.visibility&1),fragment:!!(o.visibility&&o.visibility&2),uniformCount:o.uniforms.length,uniforms:o.uniforms.map(l=>({...l}))})}return i}function Rk(r,e,t){let n=t.endsWith("Uniforms")?[t,t.slice(0,-8)]:[t,`${t}Uniforms`];for(let i of n){let o=r.getUniformBlockIndex(e,i);if(o!==4294967295){if(!Number.isInteger(o)||o<0)throw new Error(`Failed to resolve WebGL uniform block "${i}": getUniformBlockIndex returned ${String(o)}`);return{blockIndex:o,blockName:i}}}return null}function AE(r,e,t,n){let i=n||r.getActiveUniformBlockName(e,t);if(!i)throw new Error(`Failed to reflect WebGL uniform block at index ${t}: missing block name`);let o=(_,w)=>{let E=r.getActiveUniformBlockParameter(e,t,_);if(E==null)throw new Error(`Failed to reflect WebGL uniform block "${i}": ${w} returned null`);return E},s=Yn(o(35391,"UNIFORM_BLOCK_BINDING"),i,"UNIFORM_BLOCK_BINDING",0),a=Yn(o(35392,"UNIFORM_BLOCK_DATA_SIZE"),i,"UNIFORM_BLOCK_DATA_SIZE",0),c=Yn(o(35394,"UNIFORM_BLOCK_ACTIVE_UNIFORMS"),i,"UNIFORM_BLOCK_ACTIVE_UNIFORMS",0),l=ME(o(35395,"UNIFORM_BLOCK_ACTIVE_UNIFORM_INDICES"),i,"UNIFORM_BLOCK_ACTIVE_UNIFORM_INDICES",c),u=aa(r,e,l,35383,"UNIFORM_TYPE",i,c),f=aa(r,e,l,35384,"UNIFORM_SIZE",i,c),h=aa(r,e,l,35386,"UNIFORM_BLOCK_INDEX",i,c),p=aa(r,e,l,35387,"UNIFORM_OFFSET",i,c),m=aa(r,e,l,35388,"UNIFORM_ARRAY_STRIDE",i,c),g=[];for(let _=0;_<c;_++){if(h[_]!==t)throw new Error(`Failed to reflect WebGL uniform block "${i}": active uniform index ${l[_]} belongs to block ${h[_]}, expected ${t}`);let w=l[_],E=r.getActiveUniform(e,w);if(!E)throw new Error(`Failed to reflect WebGL uniform block "${i}": getActiveUniform(${w}) returned null`);let S=Yn(u[_],i,`UNIFORM_TYPE[${_}]`,1),C=Yn(f[_],i,`UNIFORM_SIZE[${_}]`,1),A=Yn(p[_],i,`UNIFORM_OFFSET[${_}]`,0),B=Yn(m[_],i,`UNIFORM_ARRAY_STRIDE[${_}]`,0);if(E.type!==S||E.size!==C)throw new Error(`Failed to reflect WebGL uniform block "${i}": getActiveUniform(${w}) disagrees with getActiveUniforms`);g.push({name:E.name,format:Su(S),arrayLength:C,byteOffset:A,byteStride:B})}let y={name:i,location:s,byteLength:a,vertex:!!o(35396,"UNIFORM_BLOCK_REFERENCED_BY_VERTEX_SHADER"),fragment:!!o(35398,"UNIFORM_BLOCK_REFERENCED_BY_FRAGMENT_SHADER"),uniformCount:c,uniforms:g},x=new Set(y.uniforms.map(_=>_.name.split(".")[0]).filter(_=>!!_)),v=y.name.replace(/Uniforms$/,"");if(x.size===1&&!x.has(y.name)&&!x.has(v)){let[_]=x;T.warn(`Uniform block "${y.name}" uses GLSL instance "${_}". luma.gl binds uniform buffers by block name ("${y.name}") and alias ("${v}"). Prefer matching the instance name to one of those to avoid confusing silent mismatches.`)()}return y}function aa(r,e,t,n,i,o,s){let a=r.getActiveUniforms(e,t,n);if(a===null)throw new Error(`Failed to reflect WebGL uniform block "${o}": ${i} returned null`);return ME(a,o,i,s)}function ME(r,e,t,n){if(!Array.isArray(r)&&!ArrayBuffer.isView(r))throw new Error(`Failed to reflect WebGL uniform block "${e}": ${t} returned a non-array value`);let i=Array.from(r);if(i.length!==n||i.some(o=>!Number.isInteger(o)))throw new Error(`Failed to reflect WebGL uniform block "${e}": ${t} returned ${i.length} invalid values, expected ${n}`);return i}function Yn(r,e,t,n){if(!Number.isInteger(r)||r<n)throw new Error(`Failed to reflect WebGL uniform block "${e}": ${t} returned ${String(r)}`);return r}function Bk(r){let e=vn(r.uniformTypes,{layout:"std140"}),t=Ok(r.uniformTypes,e.fields);return{type:"uniform",name:r.name,group:0,location:0,minBindingSize:e.byteLength,uniforms:t}}function Ok(r,e){let t=[],n=(o,s)=>{if(typeof s=="string"){let a=e[o];if(!a)throw new Error(`Missing std140 layout field ${o}`);t.push({name:o,format:a.shaderType,arrayLength:1,byteOffset:a.offset*4,byteStride:0});return}if(Array.isArray(s)){i(o,s[0],s[1]);return}for(let[a,c]of Object.entries(s))n(`${o}.${a}`,c)},i=(o,s,a)=>{if(typeof s=="string"){let c=e[`${o}[0]`],l=a>1?e[`${o}[1]`]:void 0;if(!c)throw new Error(`Missing std140 array layout field ${o}[0]`);t.push({name:`${o}[0]`,format:c.shaderType,arrayLength:a,byteOffset:c.offset*4,byteStride:l?(l.offset-c.offset)*4:0});return}if(Array.isArray(s))throw new Error(`Nested uniform arrays are not supported for ${o}`);for(let[c,l]of Object.entries(s)){if(typeof l!="string")throw new Error(`Composite uniform array members are not supported for ${o}`);let u=`${o}[0].${c}`,f=`${o}[1].${c}`,h=e[u],p=a>1?e[f]:void 0;if(!h)throw new Error(`Missing std140 array layout field ${u}`);t.push({name:u,format:h.shaderType,arrayLength:a,byteOffset:h.offset*4,byteStride:p?(p.offset-h.offset)*4:0})}};for(let[o,s]of Object.entries(r))n(o,s);return t}function kk(r){return r.type==="uniform"&&Number.isInteger(r.minBindingSize)&&r.minBindingSize>=0&&Array.isArray(r.uniforms)&&r.uniforms.every(e=>typeof e.name=="string"&&typeof e.format=="string"&&Number.isInteger(e.arrayLength)&&e.arrayLength>0&&Number.isInteger(e.byteOffset)&&e.byteOffset>=0&&Number.isInteger(e.byteStride)&&e.byteStride>=0)}function Dk(r){if(r[r.length-1]!=="]")return{name:r,length:1,isArray:!1};let t=/([^[]*)(\[[0-9]+\])?/.exec(r);return{name:Br(t?.[1],`Failed to parse GLSL uniform name ${r}`),length:t?.[2]?1:0,isArray:!!t?.[2]}}var IE=b(()=>{N();Tu()});function Nk(r,e){let t={...r,attributes:r.attributes.map(n=>({...n})),bindings:r.bindings.map(n=>({...n}))};for(let n of e?.attributes||[]){let i=t.attributes.find(o=>o.name===n.name);i?(i.type=n.type||i.type,i.stepMode=n.stepMode||i.stepMode):T.warn(`shader layout attribute ${n.name} not present in shader`)}for(let n of e?.bindings||[]){let i=BE(t,n.name);if(!i){T.warn(`shader layout binding ${n.name} not present in shader`);continue}Object.assign(i,n)}return t}function BE(r,e){return r.bindings.find(t=>t.name===e||t.name===`${e}Uniforms`||`${t.name}Uniforms`===e)}function RE(r,e){return r[e]||r[`${e}Uniforms`]||r[e.replace(/Uniforms$/,"")]}var Lu,OE=b(()=>{N();SE();pu();fu();Eu();Dm();IE();Lu=class extends ft{constructor(t,n){super(t,n);d(this,"device");d(this,"handle");d(this,"vs");d(this,"fs");d(this,"introspectedLayout");d(this,"bindings",{});d(this,"uniforms",{});d(this,"varyings",null);d(this,"_uniformCount",0);d(this,"_uniformSetters",{});this.device=t;let i=this.sharedRenderPipeline||this.device._createSharedRenderPipelineWebGL(n);this.sharedRenderPipeline=i,this.handle=i.handle,this.vs=i.vs,this.fs=i.fs,this.linkStatus=i.linkStatus,this.introspectedLayout=CE(this.device.gl,this.handle,{uniformBlockLayouts:n._uniformBlockLayouts,shaderLayout:n.shaderLayout}),this.device._setWebGLDebugMetadata(this.handle,this,{spector:{id:this.props.id}}),this.shaderLayout=n.shaderLayout?Nk(this.introspectedLayout,n.shaderLayout):this.introspectedLayout}get[Symbol.toStringTag](){return"WEBGLRenderPipeline"}destroy(){this.destroyed||(this.sharedRenderPipeline&&!this.props._sharedRenderPipeline&&this.sharedRenderPipeline.destroy(),this.destroyResource())}setBindings(t,n){let i=mi(xn(this.shaderLayout,t));for(let[o,s]of Object.entries(i)){let a=BE(this.shaderLayout,o);if(a){switch(s||T.warn(`Unsetting binding "${o}" in render pipeline "${this.id}"`)(),a.type){case"uniform":if(!(s instanceof Bt)&&!(s.buffer instanceof Bt))throw new Error("buffer value");break;case"texture":if(!(s instanceof rr||s instanceof nr||s instanceof tr))throw new Error(`${this} Bad texture binding for ${o}`);break;case"sampler":T.warn(`Ignoring sampler ${o}`)();break;default:throw new Error(a.type)}this.bindings[o]=s}else{let c=this.shaderLayout.bindings.map(l=>`"${l.name}"`).join(", ");n?.disableWarnings||T.warn(`No binding "${o}" in render pipeline "${this.id}", expected one of ${c}`,s)()}}}draw(t){let n=t.renderPass,i=t.bindGroups?mi(t.bindGroups):t.bindings||this.bindings;return n.setPipeline(this),n.setBindings(i),n.setVertexArray(t.vertexArray),n.draw({parameters:t.parameters,topology:t.topology,isInstanced:t.isInstanced,vertexCount:t.vertexCount,indexCount:t.indexCount,instanceCount:t.instanceCount,firstVertex:t.firstVertex,firstIndex:t.firstIndex,firstInstance:t.firstInstance,baseVertex:t.baseVertex,transformFeedback:t.transformFeedback,uniforms:t.uniforms})}_areTexturesRenderable(t){let n=!0;for(let i of this.shaderLayout.bindings)RE(t,i.name)||(T.warn(`Binding ${i.name} not found in ${this.id}`)(),n=!1);return n}_applyBindings(t,n){if(this._syncLinkStatus(),this.linkStatus!=="success")return;let{gl:i}=this.device;i.useProgram(this.handle);let o=0,s=0;for(let a of this.shaderLayout.bindings){let c=RE(t,a.name);if(!c)throw new Error(`No value for binding ${a.name} in ${this.id}`);switch(a.type){case"uniform":let{name:l}=a,u=i.getUniformBlockIndex(this.handle,l);if(u===4294967295)throw new Error(`Invalid uniform block name ${l}`);if(i.uniformBlockBinding(this.handle,u,s),c instanceof Bt)i.bindBufferBase(35345,s,c.handle);else{let h=c;i.bindBufferRange(35345,s,h.buffer.handle,h.offset||0,h.size||h.buffer.byteLength-(h.offset||0))}s+=1;break;case"texture":if(!(c instanceof rr||c instanceof nr||c instanceof tr))throw new Error("texture");let f;if(c instanceof rr)f=c.texture;else if(c instanceof nr)f=c;else if(c instanceof tr&&c.colorAttachments[0]instanceof rr)T.warn("Passing framebuffer in texture binding may be deprecated. Use fbo.colorAttachments[0] instead")(),f=c.colorAttachments[0].texture;else throw new Error("No texture");i.activeTexture(33984+o),i.bindTexture(f.glTarget,f.handle),o+=1;break;case"sampler":break;case"storage":case"read-only-storage":throw new Error(`binding type '${a.type}' not supported in WebGL`)}}}_applyUniforms(t){for(let n of this.shaderLayout.uniforms||[]){let{name:i,location:o,type:s,textureUnit:a}=n,c=t[i]??a;c!==void 0&&EE(this.device.gl,o,s,c)}}_syncLinkStatus(){this.linkStatus=this.sharedRenderPipeline.linkStatus}}});var kE,Au,DE=b(()=>{N();Tu();kE=4,Au=class extends qo{constructor(t,n){super(t,n);d(this,"device");d(this,"handle");d(this,"vs");d(this,"fs");d(this,"linkStatus","pending");this.device=t,this.handle=n.handle||this.device.gl.createProgram(),this.vs=n.vs,this.fs=n.fs,n.varyings&&n.varyings.length>0&&this.device.gl.transformFeedbackVaryings(this.handle,n.varyings,n.bufferMode||35981),this._linkShaders()}destroy(){this.destroyed||(this.device.gl.useProgram(null),this.device.gl.deleteProgram(this.handle),this.handle.destroyed=!0,this.destroyResource())}async _linkShaders(){let{gl:t}=this.device;if(t.attachShader(this.handle,this.vs.handle),t.attachShader(this.handle,this.fs.handle),T.time(kE,`linkProgram for ${this.id}`)(),t.linkProgram(this.handle),T.timeEnd(kE,`linkProgram for ${this.id}`)(),!this.device.features.has("compilation-status-async-webgl")){let i=this._getLinkStatus();this._reportLinkStatus(i);return}T.once(1,"RenderPipeline linking is asynchronous")(),await this._waitForLinkComplete(),T.info(2,`RenderPipeline ${this.id} - async linking complete: ${this.linkStatus}`)();let n=this._getLinkStatus();this._reportLinkStatus(n)}async _reportLinkStatus(t){switch(t){case"success":return;default:let n=t==="link-error"?"Link error":"Validation error";switch(this.vs.compilationStatus){case"error":throw this.vs.debugShader(),new Error(`${this} ${n} during compilation of ${this.vs}`);case"pending":await this.vs.asyncCompilationStatus,this.vs.debugShader();break;case"success":break}switch(this.fs?.compilationStatus){case"error":throw this.fs.debugShader(),new Error(`${this} ${n} during compilation of ${this.fs}`);case"pending":await this.fs.asyncCompilationStatus,this.fs.debugShader();break;case"success":break}let i=this.device.gl.getProgramInfoLog(this.handle);this.device.reportError(new Error(`${n} during ${t}: ${i}`),this)(),this.device.debug()}}_getLinkStatus(){let{gl:t}=this.device;return t.getProgramParameter(this.handle,35714)?(this._initializeSamplerUniforms(),t.validateProgram(this.handle),t.getProgramParameter(this.handle,35715)?(this.linkStatus="success","success"):(this.linkStatus="error","validation-error")):(this.linkStatus="error","link-error")}_initializeSamplerUniforms(){let{gl:t}=this.device;t.useProgram(this.handle);let n=0,i=t.getProgramParameter(this.handle,35718);for(let o=0;o<i;o++){let s=t.getActiveUniform(this.handle,o);if(s&&Pu(s.type)){let a=s.name.endsWith("[0]"),c=a?s.name.slice(0,-3):s.name,l=t.getUniformLocation(this.handle,c);l!==null&&(n=this._assignSamplerUniform(l,s,a,n))}}}_assignSamplerUniform(t,n,i,o){let{gl:s}=this.device;if(i&&n.size>1){let a=Int32Array.from({length:n.size},(c,l)=>o+l);return s.uniform1iv(t,a),o+n.size}return s.uniform1i(t,o),o+1}async _waitForLinkComplete(){let t=async o=>await new Promise(s=>setTimeout(s,o));if(!this.device.features.has("compilation-status-async-webgl")){await t(10);return}let{gl:i}=this.device;for(;;){if(i.getProgramParameter(this.handle,37297))return;await t(10)}}}});function Fk(r,e){let t=e.sourceBuffer,n=e.destinationBuffer;r.gl.bindBuffer(36662,t.handle),r.gl.bindBuffer(36663,n.handle),r.gl.copyBufferSubData(36662,36663,e.sourceOffset??0,e.destinationOffset??0,e.size),r.gl.bindBuffer(36662,null),r.gl.bindBuffer(36663,null)}function Uk(r,e){let{sourceBuffer:t,byteOffset:n=0,destinationTexture:i,mipLevel:o=0,origin:s=[0,0,0],aspect:a="all",bytesPerRow:c,rowsPerImage:l,size:u}=e;if(a!=="all")throw new Error("copyBufferToTexture aspect is not supported in WebGL");i.writeBuffer(t,{byteOffset:n,bytesPerRow:c,rowsPerImage:l,mipLevel:o,x:s[0]??0,y:s[1]??0,z:s[2]??0,width:u[0],height:u[1],depthOrArrayLayers:u[2]})}function Gk(r,e){let{sourceTexture:t,mipLevel:n=0,aspect:i="all",width:o=e.sourceTexture.width,height:s=e.sourceTexture.height,depthOrArrayLayers:a,origin:c=[0,0,0],destinationBuffer:l,byteOffset:u=0,bytesPerRow:f,rowsPerImage:h}=e;if(t instanceof Y){t.readBuffer({x:c[0]??0,y:c[1]??0,z:c[2]??0,width:o,height:s,depthOrArrayLayers:a,mipLevel:n,aspect:i,byteOffset:u},l);return}if(i!=="all")throw new Error("aspect not supported in WebGL");if(n!==0||a!==void 0||f||h)throw new Error("not implemented");let{framebuffer:p,destroyFramebuffer:m}=NE(t),g;try{let y=l,x=o||p.width,v=s||p.height,_=Br(p.colorAttachments[0]),w=cu(_.texture.props.format),E=w.format,S=w.type;r.gl.bindBuffer(35051,y.handle),g=r.gl.bindFramebuffer(36160,p.handle),r.gl.readPixels(c[0],c[1],x,v,E,S,u)}finally{r.gl.bindBuffer(35051,null),g!==void 0&&r.gl.bindFramebuffer(36160,g),m&&p.destroy()}}function zk(r,e){let{sourceTexture:t,destinationMipLevel:n=0,origin:i=[0,0],destinationOrigin:o=[0,0,0],destinationTexture:s}=e,{width:a=e.destinationTexture.width,height:c=e.destinationTexture.height}=e,{framebuffer:l,destroyFramebuffer:u}=NE(t),[f=0,h=0]=i,[p,m,g]=o,y=r.gl.bindFramebuffer(36160,l.handle),x,v;if(s instanceof nr)x=s,a=Number.isFinite(a)?a:x.width,c=Number.isFinite(c)?c:x.height,x._bind(0),v=x.glTarget;else throw new Error("invalid destination");switch(v){case 3553:case 34067:r.gl.copyTexSubImage2D(v,n,p,m,f,h,a,c);break;case 35866:case 32879:r.gl.copyTexSubImage3D(v,n,p,m,g,f,h,a,c);break;default:}x&&x._unbind(),r.gl.bindFramebuffer(36160,y),u&&l.destroy()}function NE(r){if(r instanceof Y){let{width:e,height:t,id:n}=r;return{framebuffer:r.device.createFramebuffer({id:`framebuffer-for-${n}`,width:e,height:t,colorAttachments:[r]}),destroyFramebuffer:!0}}return{framebuffer:r,destroyFramebuffer:!1}}var Cu,FE=b(()=>{N();Qi();Eu();Cu=class extends Ko{constructor(t,n={}){super(t,n);d(this,"device");d(this,"handle",null);d(this,"commands",[]);this.device=t}_executeCommands(t=this.commands){for(let n of t)switch(n.name){case"copy-buffer-to-buffer":Fk(this.device,n.options);break;case"copy-buffer-to-texture":Uk(this.device,n.options);break;case"copy-texture-to-buffer":Gk(this.device,n.options);break;case"copy-texture-to-texture":zk(this.device,n.options);break;default:throw new Error(n.name)}}}});function UE(r){switch(r){case"point-list":return 0;case"line-list":return 1;case"line-strip":return 3;case"triangle-list":return 4;case"triangle-strip":return 5;default:throw new Error(r)}}function GE(r){switch(r){case"point-list":return 0;case"line-list":return 1;case"line-strip":return 1;case"triangle-list":return 4;case"triangle-strip":return 4;default:throw new Error(r)}}var Fm=b(()=>{});var $k,Mu,zE=b(()=>{N();vu();Xi();Fm();Rm();$k=[1,2,4,8],Mu=class extends Xo{constructor(t,n){super(t,n);d(this,"device");d(this,"handle",null);d(this,"glParameters",{});d(this,"pipeline",null);d(this,"bindings",{});d(this,"bindingsPipeline",null);d(this,"vertexArray",null);this.device=t;let i=this.props.framebuffer,o=!i||i.handle===null;o&&t.getDefaultCanvasContext()._resizeDrawingBufferIfNeeded();let s;if(!n?.parameters?.viewport)if(!o&&i){let{width:a,height:c}=i;s=[0,0,a,c]}else{let[a,c]=t.getDefaultCanvasContext().getDrawingBufferSize();s=[0,0,a,c]}if(this.device.pushState(),this.setParameters({viewport:s,...this.props.parameters}),!o&&i?.colorAttachments.length){let a=i.colorAttachments.map((c,l)=>36064+l);this.device.gl.drawBuffers(a)}else o&&this.device.gl.drawBuffers([1029]);this.clear(),this.props.timestampQuerySet&&this.props.beginTimestampIndex!==void 0&&this.props.timestampQuerySet.writeTimestamp(this.props.beginTimestampIndex)}end(){this.destroyed||(this.props.timestampQuerySet&&this.props.endTimestampIndex!==void 0&&this.props.timestampQuerySet.writeTimestamp(this.props.endTimestampIndex),this.device.popState(),this.destroy())}pushDebugGroup(t){}popDebugGroup(){}insertDebugMarker(t){}executeBundles(t){throw new Error("Render bundles are only supported in WebGPU")}setParameters(t={}){let n={...this.glParameters};n.framebuffer=this.props.framebuffer||null,this.props.depthReadOnly&&(n.depthMask=!this.props.depthReadOnly),n.stencilMask=this.props.stencilReadOnly?0:1,n[35977]=this.props.discard,t.viewport&&(t.viewport.length>=6?(n.viewport=t.viewport.slice(0,4),n.depthRange=[t.viewport[4],t.viewport[5]]):n.viewport=t.viewport),t.scissorRect&&(n.scissorTest=!0,n.scissor=t.scissorRect),t.blendConstant&&(n.blendColor=t.blendConstant),t.stencilReference!==void 0&&(n[2967]=t.stencilReference,n[36003]=t.stencilReference),"colorMask"in t&&(n.colorMask=$k.map(i=>!!(i&t.colorMask))),this.glParameters=n,Mt(this.device.gl,n)}setPipeline(t){this.pipeline=t}setBindings(t,n){if(!this.pipeline)throw new Error("RenderPass.setPipeline() must be called before setBindings()");this.bindings=mi(xn(this.pipeline.shaderLayout,t)),this.bindingsPipeline=this.pipeline}setVertexArray(t){this.vertexArray=t}draw(t){let n=this.pipeline,i=this.vertexArray;if(!n)throw new Error("RenderPass.setPipeline() must be called before draw()");if(!i)throw new Error("RenderPass.setVertexArray() must be called before draw()");if(n.shaderLayout.bindings.length>0&&this.bindingsPipeline!==n)throw new Error("RenderPass.setBindings() must be called after setPipeline() before draw()");n._syncLinkStatus();let{parameters:o=n.props.parameters,topology:s=n.props.topology,vertexCount:a,indexCount:c,instanceCount:l,isInstanced:u=!1,firstVertex:f=0,transformFeedback:h,uniforms:p=n.uniforms}=t,m=UE(s),g=!!i.indexBuffer,y=i.indexBuffer?.glIndexType,x=c??a??0;if(n.linkStatus!=="success")return T.info(2,`RenderPipeline:${n.id}.draw() aborted - waiting for shader linking`)(),!1;if(!n._areTexturesRenderable(this.bindings))return T.info(2,`RenderPipeline:${n.id}.draw() aborted - textures not yet loaded`)(),!1;this.device.gl.useProgram(n.handle),i.bindBeforeRender(this);let v=h;return v&&v.begin(n.props.topology),n._applyBindings(this.bindings,{disableWarnings:n.props.disableWarnings}),n._applyUniforms(p),vE(this.device,o,this.glParameters,()=>{g&&u?this.device.gl.drawElementsInstanced(m,x,y,f,l||0):g?this.device.gl.drawElements(m,x,y,f):u?this.device.gl.drawArraysInstanced(m,f,a||0,l||0):this.device.gl.drawArrays(m,f,a||0),v&&v.end()}),i.unbindAfterRender(this),!0}drawIndirect(t,n=0){throw new Error("Indirect drawing is only supported in WebGPU")}drawIndexedIndirect(t,n=0){throw new Error("Indirect drawing is only supported in WebGPU")}beginOcclusionQuery(t){this.props.occlusionQuerySet?.beginOcclusionQuery()}endOcclusionQuery(){this.props.occlusionQuerySet?.endOcclusionQuery()}clear(){let t={...this.glParameters},n=0;this.props.clearColors&&this.props.clearColors.forEach((i,o)=>{i&&this.clearColorBuffer(o,i)}),this.props.clearColor!==!1&&this.props.clearColors===void 0&&(n|=16384,t.clearColor=this.props.clearColor),this.props.clearDepth!==!1&&(n|=256,t.clearDepth=this.props.clearDepth),this.props.clearStencil!==!1&&(n|=1024,t.clearStencil=this.props.clearStencil),n!==0&&Ot(this.device.gl,t,()=>{this.device.gl.clear(n)})}clearColorBuffer(t=0,n=[0,0,0,0]){Ot(this.device.gl,{framebuffer:this.props.framebuffer},()=>{switch(n.constructor){case Int8Array:case Int16Array:case Int32Array:this.device.gl.clearBufferiv(6144,t,n);break;case Uint8Array:case Uint8ClampedArray:case Uint16Array:case Uint32Array:this.device.gl.clearBufferuiv(6144,t,n);break;case Float32Array:this.device.gl.clearBufferfv(6144,t,n);break;default:throw new Error("clearColorBuffer: color must be typed array")}})}}});var ca,$E=b(()=>{N();FE();zE();ca=class extends Zo{constructor(t,n){super(t,n);d(this,"device");d(this,"handle",null);d(this,"commandBuffer");this.device=t,this.commandBuffer=new Cu(t,{id:this.id,userData:this.userData})}destroy(){this.destroyResource()}finish(){return this.destroy(),this.commandBuffer}beginRenderPass(t={}){return new Mu(this.device,this._applyTimeProfilingToPassProps(t))}beginComputePass(t={}){throw new Error("ComputePass not supported in WebGL")}copyBufferToBuffer(t){this.commandBuffer.commands.push({name:"copy-buffer-to-buffer",options:t})}copyBufferToTexture(t){this.commandBuffer.commands.push({name:"copy-buffer-to-texture",options:t})}copyTextureToBuffer(t){this.commandBuffer.commands.push({name:"copy-texture-to-buffer",options:t})}copyTextureToTexture(t){this.commandBuffer.commands.push({name:"copy-texture-to-texture",options:t})}pushDebugGroup(t){}popDebugGroup(){}insertDebugMarker(t){}resolveQuerySet(t,n,i){throw new Error("resolveQuerySet is not supported in WebGL")}writeTimestamp(t,n){t.writeTimestamp(n)}}});function VE(r){let{target:e,source:t,start:n=0,count:i=1}=r,o=t.length,s=i*o,a=0;for(let c=n;a<o;a++)e[c++]=t[a]??0;for(;a<s;)a<s-a?(e.copyWithin(n+a,n,n+a),a*=2):(e.copyWithin(n+a,n,n+s-a),a=s);return r.target}var WE=b(()=>{});function Vk(r){return Array.isArray(r)?new Float32Array(r):r}function Wk(r,e){if(!r||!e||r.length!==e.length||r.constructor!==e.constructor)return!1;for(let t=0;t<r.length;++t)if(r[t]!==e[t])return!1;return!0}var Iu,jE=b(()=>{N();on();Sm();WE();Iu=class r extends Qo{constructor(t,n){super(t,n);d(this,"device");d(this,"handle");d(this,"attributeInfosByLocation");d(this,"buffer",null);d(this,"bufferValue",null);this.device=t,this.handle=this.device.gl.createVertexArray(),this.attributeInfosByLocation=new Array(this.maxVertexAttributes).fill(null);for(let i of Object.values(is(n.shaderLayout,n.bufferLayout)))this.attributeInfosByLocation[i.location]=i}get[Symbol.toStringTag](){return"VertexArray"}static isConstantAttributeZeroSupported(t){return kf()==="Chrome"}destroy(){super.destroy(),this.buffer&&this.buffer?.destroy(),this.handle&&(this.device.gl.deleteVertexArray(this.handle),this.handle=void 0)}setIndexBuffer(t){let n=t;if(n&&n.glTarget!==34963)throw new Error("Use .setBuffer()");this.device.gl.bindVertexArray(this.handle),this.device.gl.bindBuffer(34963,n?n.handle:null),this.indexBuffer=n,this.device.gl.bindVertexArray(null)}setBuffer(t,n){let i=n;if(i.glTarget===34963)throw new Error("Use .setIndexBuffer()");let{size:o,type:s,stride:a,offset:c,normalized:l,integer:u,divisor:f}=this._getAccessor(t);this.device.gl.bindVertexArray(this.handle),this.device.gl.bindBuffer(34962,i.handle),u?this.device.gl.vertexAttribIPointer(t,o,s,a,c):this.device.gl.vertexAttribPointer(t,o,s,l,a,c),this.device.gl.bindBuffer(34962,null),this.device.gl.enableVertexAttribArray(t),this.device.gl.vertexAttribDivisor(t,f||0),this.attributes[t]=i,this.device.gl.bindVertexArray(null)}setConstantWebGL(t,n){this._enable(t,!1),this.attributes[t]=n}bindBeforeRender(){this.device.gl.bindVertexArray(this.handle),this._applyConstantAttributes()}unbindAfterRender(){this.device.gl.bindVertexArray(null)}_applyConstantAttributes(){for(let t=0;t<this.maxVertexAttributes;++t){let n=this.attributes[t];ArrayBuffer.isView(n)&&this.device.setConstantAttributeWebGL(t,n)}}_getAccessor(t){let n=this.attributeInfosByLocation[t];if(!n)throw new Error(`Unknown attribute location ${t}`);let i=iu(n.bufferDataType);return{size:n.bufferComponents,type:i,stride:n.byteStride,offset:n.byteOffset,normalized:n.normalized,integer:n.integer,divisor:n.stepMode==="instance"?1:0}}_enable(t,n=!0){let o=r.isConstantAttributeZeroSupported(this.device)||t!==0;(n||o)&&(t=Number(t),this.device.gl.bindVertexArray(this.handle),n?this.device.gl.enableVertexAttribArray(t):this.device.gl.disableVertexAttribArray(t),this.device.gl.bindVertexArray(null))}getConstantBuffer(t,n){let i=Vk(n),o=i.byteLength*t,s=i.length*t;if(this.buffer&&o!==this.buffer.byteLength)throw new Error(`Buffer size is immutable, byte length ${o} !== ${this.buffer.byteLength}.`);let a=!this.buffer;if(this.buffer=this.buffer||this.device.createBuffer({byteLength:o}),a||(a=!Wk(i,this.bufferValue)),a){let c=mh(n.constructor,s);VE({target:c,source:i,start:0,count:s}),this.buffer.write(c),this.bufferValue=n}return this.buffer}}});function HE(r){return typeof r=="number"?Number.isInteger(r):/^\d+$/.test(r)}var Ru,YE=b(()=>{N();Bu();Fm();Ru=class extends Jo{constructor(t,n){super(t,n);d(this,"device");d(this,"gl");d(this,"handle");d(this,"layout");d(this,"buffers",{});d(this,"unusedBuffers",{});d(this,"bindOnUse",!0);d(this,"_bound",!1);this.device=t,this.gl=t.gl,this.handle=this.props.handle||this.gl.createTransformFeedback(),this.layout=this.props.layout,n.buffers&&this.setBuffers(n.buffers),Object.seal(this)}destroy(){this.gl.deleteTransformFeedback(this.handle),super.destroy()}begin(t="point-list"){this.gl.bindTransformFeedback(36386,this.handle),this.bindOnUse&&this._bindBuffers(),this.gl.beginTransformFeedback(GE(t))}end(){this.gl.endTransformFeedback(),this.bindOnUse&&this._unbindBuffers(),this.gl.bindTransformFeedback(36386,null)}setBuffers(t){this.buffers={},this.unusedBuffers={},this.bind(()=>{for(let[n,i]of Object.entries(t))this.setBuffer(n,i)})}setBuffer(t,n){let i=this._getVaryingIndex(t),{buffer:o,byteLength:s,byteOffset:a}=this._getBufferRange(n);if(i<0){this.unusedBuffers[t]=o,T.warn(`${this.id} unusedBuffers varying buffer ${t}`)();return}this.buffers[i]={buffer:o,byteLength:s,byteOffset:a},this.bindOnUse||this._bindBuffer(i,o,a,s)}getBuffer(t){if(HE(t))return this.buffers[t]||null;let n=this._getVaryingIndex(t);return this.buffers[n]??null}bind(t=this.handle){if(typeof t!="function")return this.gl.bindTransformFeedback(36386,t),this;let n;return this._bound?n=t():(this.gl.bindTransformFeedback(36386,this.handle),this._bound=!0,n=t(),this._bound=!1,this.gl.bindTransformFeedback(36386,null)),n}unbind(){this.bind(null)}_getBufferRange(t){if(t instanceof Bt)return{buffer:t,byteOffset:0,byteLength:t.byteLength};let{buffer:n,byteOffset:i=0,byteLength:o=t.buffer.byteLength}=t;return{buffer:n,byteOffset:i,byteLength:o}}_getVaryingIndex(t){if(HE(t))return Number(t);for(let n of this.layout.varyings||[])if(t===n.name)return n.location;return-1}_bindBuffers(){for(let[t,n]of Object.entries(this.buffers)){let{buffer:i,byteLength:o,byteOffset:s}=this._getBufferRange(n);this._bindBuffer(Number(t),i,s,o)}}_unbindBuffers(){for(let t in this.buffers)this.gl.bindBufferBase(35982,Number(t),null)}_bindBuffer(t,n,i=0,o){let s=n&&n.handle;!s||o===void 0?this.gl.bindBufferBase(35982,t,s):this.gl.bindBufferRange(35982,t,s,i,o)}}});var Ou,qE=b(()=>{N();Ou=class extends es{constructor(t,n){super(t,n);d(this,"device");d(this,"handle");d(this,"_timestampPairs",[]);d(this,"_pendingReads",new Set);d(this,"_occlusionQuery",null);d(this,"_occlusionActive",!1);if(this.device=t,n.type==="timestamp"){if(n.count<2)throw new Error("Timestamp QuerySet requires at least two query slots");this._timestampPairs=new Array(Math.ceil(n.count/2)).fill(null).map(()=>({activeQuery:null,completedQueries:[]})),this.handle=null}else{if(n.count>1)throw new Error("WebGL occlusion QuerySet can only have one value");let i=this.device.gl.createQuery();if(!i)throw new Error("WebGL query not supported");this.handle=i}Object.seal(this)}get[Symbol.toStringTag](){return"QuerySet"}destroy(){if(!this.destroyed){this.handle&&this.device.gl.deleteQuery(this.handle);for(let t of this._timestampPairs){t.activeQuery&&(this._cancelPendingQuery(t.activeQuery),this.device.gl.deleteQuery(t.activeQuery.handle));for(let n of t.completedQueries)this._cancelPendingQuery(n),this.device.gl.deleteQuery(n.handle)}this._occlusionQuery&&(this._cancelPendingQuery(this._occlusionQuery),this.device.gl.deleteQuery(this._occlusionQuery.handle));for(let t of Array.from(this._pendingReads))this._cancelPendingQuery(t);this.destroyResource()}}isResultAvailable(t){return this.props.type==="timestamp"?t===void 0?this._timestampPairs.some((n,i)=>this._isTimestampPairAvailable(i)):this._isTimestampPairAvailable(this._getTimestampPairIndex(t)):this._occlusionQuery?this._pollQueryAvailability(this._occlusionQuery):!1}async readResults(t){let n=t?.firstQuery||0,i=t?.queryCount||this.props.count-n;if(this._validateRange(n,i),this.props.type==="timestamp"){let o=new Array(i).fill(0n),s=Math.floor(n/2),a=Math.floor((n+i-1)/2);for(let c=s;c<=a;c++){let l=await this._consumeTimestampPairResult(c),u=c*2,f=u+1;u>=n&&u<n+i&&(o[u-n]=0n),f>=n&&f<n+i&&(o[f-n]=l)}return o}if(!this._occlusionQuery)throw new Error("Occlusion query has not been started");return[await this._consumeQueryResult(this._occlusionQuery)]}async readTimestampDuration(t,n){if(this.props.type!=="timestamp")throw new Error("Timestamp durations require a timestamp QuerySet");if(t<0||n>=this.props.count||n<=t)throw new Error("Timestamp duration range is out of bounds");if(t%2!==0||n!==t+1)throw new Error("WebGL timestamp durations require adjacent even/odd query indices");let i=await this._consumeTimestampPairResult(this._getTimestampPairIndex(t));return Number(i)/1e6}beginOcclusionQuery(){if(this.props.type!=="occlusion")throw new Error("Occlusion queries require an occlusion QuerySet");if(!this.handle)throw new Error("WebGL occlusion query is not available");if(this._occlusionActive)throw new Error("Occlusion query is already active");this.device.gl.beginQuery(35887,this.handle),this._occlusionQuery={handle:this.handle,promise:null,result:null,disjoint:!1,cancelled:!1,pollRequestId:null,resolve:null,reject:null},this._occlusionActive=!0}endOcclusionQuery(){if(!this._occlusionActive)throw new Error("Occlusion query is not active");this.device.gl.endQuery(35887),this._occlusionActive=!1}writeTimestamp(t){if(this.props.type!=="timestamp")throw new Error("Timestamp writes require a timestamp QuerySet");let n=this._getTimestampPairIndex(t),i=this._timestampPairs[n];if(t%2===0){if(i.activeQuery)throw new Error("Timestamp query pair is already active");let o=this.device.gl.createQuery();if(!o)throw new Error("WebGL query not supported");let s={handle:o,promise:null,result:null,disjoint:!1,cancelled:!1,pollRequestId:null,resolve:null,reject:null};this.device.gl.beginQuery(35007,o),i.activeQuery=s;return}if(!i.activeQuery)throw new Error("Timestamp query pair was ended before it was started");this.device.gl.endQuery(35007),i.completedQueries.push(i.activeQuery),i.activeQuery=null}_validateRange(t,n){if(t<0||n<0||t+n>this.props.count)throw new Error("Query read range is out of bounds")}_getTimestampPairIndex(t){if(t<0||t>=this.props.count)throw new Error("Query index is out of bounds");return Math.floor(t/2)}_isTimestampPairAvailable(t){let n=this._timestampPairs[t];return!n||n.completedQueries.length===0?!1:this._pollQueryAvailability(n.completedQueries[0])}_pollQueryAvailability(t){if(t.cancelled||this.destroyed)return t.result=0n,!0;if(t.result!==null||t.disjoint)return!0;if(!this.device.gl.getQueryParameter(t.handle,34919))return!1;let i=!!this.device.gl.getParameter(36795);return t.disjoint=i,t.result=i?0n:BigInt(this.device.gl.getQueryParameter(t.handle,34918)),!0}async _consumeTimestampPairResult(t){let n=this._timestampPairs[t];if(!n||n.completedQueries.length===0)throw new Error("Timestamp query pair has no completed result");let i=n.completedQueries.shift();try{return await this._consumeQueryResult(i)}finally{this.device.gl.deleteQuery(i.handle)}}_consumeQueryResult(t){return t.promise||(this._pendingReads.add(t),t.promise=new Promise((n,i)=>{t.resolve=n,t.reject=i;let o=()=>{if(t.pollRequestId=null,t.cancelled||this.destroyed){this._pendingReads.delete(t),t.promise=null,t.resolve=null,t.reject=null,n(0n);return}if(!this._pollQueryAvailability(t)){t.pollRequestId=this._requestAnimationFrame(o);return}this._pendingReads.delete(t),t.promise=null,t.resolve=null,t.reject=null,t.disjoint?i(new Error("GPU timestamp query was invalidated by a disjoint event")):n(t.result||0n)};o()})),t.promise}_cancelPendingQuery(t){if(this._pendingReads.delete(t),t.cancelled=!0,t.pollRequestId!==null&&(this._cancelAnimationFrame(t.pollRequestId),t.pollRequestId=null),t.resolve){let n=t.resolve;t.promise=null,t.resolve=null,t.reject=null,n(0n)}}_requestAnimationFrame(t){return requestAnimationFrame(t)}_cancelAnimationFrame(t){cancelAnimationFrame(t)}}});var ku,XE=b(()=>{N();ku=class extends ts{constructor(t,n={}){super(t,{});d(this,"device");d(this,"gl");d(this,"handle");d(this,"signaled");d(this,"_signaled",!1);this.device=t,this.gl=t.gl;let i=this.props.handle||this.gl.fenceSync(this.gl.SYNC_GPU_COMMANDS_COMPLETE,0);if(!i)throw new Error("Failed to create WebGL fence");this.handle=i,this.signaled=new Promise(o=>{let s=()=>{let a=this.gl.clientWaitSync(this.handle,0,0);a===this.gl.ALREADY_SIGNALED||a===this.gl.CONDITION_SATISFIED?(this._signaled=!0,o()):setTimeout(s,1)};s()})}isSignaled(){if(this._signaled)return!0;let t=this.gl.getSyncParameter(this.handle,this.gl.SYNC_STATUS);return this._signaled=t===this.gl.SIGNALED,this._signaled}destroy(){this.destroyed||this.gl.deleteSync(this.handle)}}});function Um(r){switch(r){case 6406:case 33326:case 6403:case 36244:return 1;case 33339:case 33340:case 33328:case 33320:case 33319:return 2;case 6407:case 36248:case 34837:return 3;case 6408:case 36249:case 34836:return 4;default:return 0}}function ZE(r){switch(r){case 5121:return 1;case 33635:case 32819:case 32820:return 2;case 5126:return 4;default:return 0}}var KE=b(()=>{});function QE(r,e){let{sourceX:t=0,sourceY:n=0,sourceAttachment:i=0}=e||{},{target:o=null,sourceWidth:s,sourceHeight:a,sourceDepth:c,sourceFormat:l,sourceType:u}=e||{},{framebuffer:f,deleteFramebuffer:h}=e2(r),{gl:p,handle:m}=f;s||(s=f.width),a||(a=f.height);let g=f.colorAttachments[i]?.texture;if(!g)throw new Error(`Invalid framebuffer attachment ${i}`);c=g?.depth||1,l||(l=g?.glFormat||6408),u||(u=g?.glType||5121),o=Hk(o,u,l,s,a,c);let y=Te.getDataType(o);u=u||PE(y);let x=p.bindFramebuffer(36160,m);return p.readBuffer(36064+i),p.readPixels(t,n,s,a,l,u,o),p.readBuffer(36064),p.bindFramebuffer(36160,x||null),h&&f.destroy(),o}function JE(r,e){let{target:t,sourceX:n=0,sourceY:i=0,sourceFormat:o=6408,targetByteOffset:s=0}=e||{},{sourceWidth:a,sourceHeight:c,sourceType:l}=e||{},{framebuffer:u,deleteFramebuffer:f}=e2(r);a=a||u.width,c=c||u.height;let h=u;l=l||5121;let p=t;if(!p){let g=Um(o),y=ZE(l),x=s+a*c*g*y;p=h.device.createBuffer({byteLength:x})}let m=r.device.createCommandEncoder();return m.copyTextureToBuffer({sourceTexture:r,width:a,height:c,origin:[n,i],destinationBuffer:p,byteOffset:s}),m.destroy(),f&&u.destroy(),p}function e2(r){return r instanceof yn?{framebuffer:r,deleteFramebuffer:!1}:{framebuffer:jk(r),deleteFramebuffer:!0}}function jk(r,e){let{device:t,width:n,height:i,id:o}=r;return t.createFramebuffer({...e,id:`framebuffer-for-${o}`,width:n,height:i,colorAttachments:[r]})}function Hk(r,e,t,n,i,o){if(r)return r;e||(e=5121);let s=wu(e),a=Te.getTypedArrayConstructor(s),c=Um(t);return new a(n*i*c)}var t2=b(()=>{N();Tu();KE();Nm()});var Gm={};cr(Gm,{WebGLDevice:()=>qr});function Yk(r,e,t){switch(t.length){case 1:r.gl.vertexAttrib1fv(e,t);break;case 2:r.gl.vertexAttrib2fv(e,t);break;case 3:r.gl.vertexAttrib3fv(e,t);break;case 4:r.gl.vertexAttrib4fv(e,t);break;default:}}function qk(r,e,t){r.gl.vertexAttribI4iv(e,t)}function Xk(r,e,t){r.gl.vertexAttribI4uiv(e,t)}function Zk(r,e){if(!r||!e||r.length!==e.length||r.constructor!==e.constructor)return!1;for(let t=0;t<r.length;++t)if(r[t]!==e[t])return!1;return!0}var qr,Du=b(()=>{N();wm();eE();Em();nE();fE();dE();hE();pE();ym();Qi();gE();pu();bE();wE();Eu();fu();OE();DE();$E();jE();YE();qE();XE();t2();Xi();vu();na();qr=class r extends hr{constructor(t){super({...t,id:t.id||mE("webgl-device")});d(this,"type","webgl");d(this,"handle");d(this,"features");d(this,"limits");d(this,"info");d(this,"canvasContext");d(this,"preferredColorFormat","rgba8unorm");d(this,"preferredDepthFormat","depth24plus");d(this,"commandEncoder");d(this,"lost");d(this,"_resolveContextLost");d(this,"_isLost",!1);d(this,"gl");d(this,"_constants");d(this,"extensions");d(this,"_polyfilled",!1);d(this,"spectorJS");let n=hr._getCanvasContextProps(t);if(!n)throw new Error("WebGLDevice requires props.createCanvasContext to be set");let i=n.canvas?.gl??null,o=r.getDeviceFromContext(i);if(o)throw new Error(`WebGL context already attached to device ${o.id}`);this.canvasContext=new du(this,n),this.lost=new Promise(f=>{this._resolveContextLost=f});let s={...t.webgl};n.alphaMode==="premultiplied"&&(s.premultipliedAlpha=!0),t.powerPreference!==void 0&&(s.powerPreference=t.powerPreference),t.failIfMajorPerformanceCaveat!==void 0&&(s.failIfMajorPerformanceCaveat=t.failIfMajorPerformanceCaveat);let c=this.props._handle||Jw(this.canvasContext.canvas,{onContextLost:f=>this._resolveContextLost?.({reason:"destroyed",message:"Entered sleep mode, or too many apps or browser tabs are using the GPU."}),onContextRestored:f=>{console.log("WebGL context restored")}},s);if(!c)throw new Error("WebGL context creation failed");if(o=r.getDeviceFromContext(c),o){if(t._reuseDevices)return T.log(1,`Not creating a new Device, instead returning a reference to Device ${o.id} already attached to WebGL context`,o)(),this.canvasContext.destroy(),o._reused=!0,o;throw new Error(`WebGL context already attached to device ${o.id}`)}this.handle=c,this.gl=c,this.spectorJS=$w({...this.props,gl:this.handle});let l=ra(this.handle);l.device=this,l.extensions||(l.extensions={}),this.extensions=l.extensions,this.info=tE(this.gl,this.extensions),this.limits=new uu(this.gl),this.features=new lu(this.gl,this.extensions,this.props._disabledFeatures),this.props._initializeFeatures&&this.features.initializeFeatures(),new It(this.gl,{log:(...f)=>T.log(1,...f)()}).trackState(this.gl,{copyState:!1}),(t.debug||t.debugWebGL)&&(this.gl=Gw(this.gl,{debugWebGL:!0,traceWebGL:t.debugWebGL}),T.warn("WebGL debug mode activated. Performance reduced.")()),t.debugWebGL&&(T.level=Math.max(T.level,1)),this.commandEncoder=new ca(this,{id:`${this}-command-encoder`}),this.canvasContext._startObservers()}static getDeviceFromContext(t){return t?t.luma?.device??null:null}get[Symbol.toStringTag](){return"WebGLDevice"}toString(){return`${this[Symbol.toStringTag]}(${this.id})`}isVertexFormatSupported(t){return t!=="unorm8x4-bgra"}destroy(){if(!this.props._reuseDevices&&!this._reused){this._isLost=!0,this.commandEncoder?.destroy();let t=ra(this.handle);t.device=null}}get isLost(){return this._isLost||this.gl.isContextLost()}createCanvasContext(t){throw new Error("WebGL only supports a single canvas")}createPresentationContext(t){return new hu(this,t||{})}createBuffer(t){let n=this._normalizeBufferProps(t);return new Bt(this,n)}createTexture(t){return new nr(this,t)}createExternalTexture(t){throw new Error("ExternalTexture is not available on WebGL")}createSampler(t){return new xu(this,t)}createShader(t){return new gu(this,t)}createFramebuffer(t){return new tr(this,t)}createVertexArray(t){return new Iu(this,t)}createTransformFeedback(t){return new Ru(this,t)}createQuerySet(t){return new Ou(this,t)}createFence(){return new ku(this)}createRenderPipeline(t){return new Lu(this,t)}_createSharedRenderPipelineWebGL(t){return new Au(this,t)}createComputePipeline(t){throw new Error("ComputePipeline not supported in WebGL")}createRenderBundleEncoder(t){throw new Error("Render bundles are only supported in WebGPU")}createCommandEncoder(t={}){return new ca(this,t)}submit(t){let n=null;t||({submittedCommandEncoder:n,commandBuffer:t}=this._finalizeDefaultCommandEncoderForSubmit());try{t._executeCommands(),n&&n.resolveTimeProfilingQuerySet().then(()=>{this.commandEncoder._gpuTimeMs=n._gpuTimeMs}).catch(()=>{})}finally{t.destroy()}}writeBufferViaCommandEncoder(t,n,i,o=0){n.write(i,o)}_finalizeDefaultCommandEncoderForSubmit(){let t=this.commandEncoder,n=t.finish();return this.commandEncoder.destroy(),this.commandEncoder=this.createCommandEncoder({id:t.props.id,timeProfilingQuerySet:t.getTimeProfilingQuerySet()}),{submittedCommandEncoder:t,commandBuffer:n}}readPixelsToArrayWebGL(t,n){return QE(t,n)}readPixelsToBufferWebGL(t,n){return JE(t,n)}setParametersWebGL(t){Mt(this.gl,t)}getParametersWebGL(t){return nu(this.gl,t)}withParametersWebGL(t,n){return Ot(this.gl,t,n)}resetWebGL(){T.warn("WebGLDevice.resetWebGL is deprecated, use only for debugging")(),qw(this.gl)}_getDeviceSpecificTextureFormatCapabilities(t){return cE(this.gl,t,this.extensions)}loseDevice(){let t=!1,i=this.getExtension("WEBGL_lose_context").WEBGL_lose_context;return i&&(t=!0,i.loseContext()),this._resolveContextLost?.({reason:"destroyed",message:"Application triggered context loss"}),t}pushState(){It.get(this.gl).push()}popState(){It.get(this.gl).pop()}getGLKey(t,n){let i=Number(t);for(let o in this.gl)if(this.gl[o]===i)return`GL.${o}`;return n?.emptyIfUnknown?"":String(t)}getGLKeys(t){let n={emptyIfUnknown:!0};return Object.entries(t).reduce((i,[o,s])=>(i[`${o}:${this.getGLKey(o,n)}`]=`${s}:${this.getGLKey(s,n)}`,i),{})}setConstantAttributeWebGL(t,n){let i=this.limits.maxVertexAttributes;this._constants=this._constants||new Array(i).fill(null);let o=this._constants[t];switch(o&&Zk(o,n)&&T.info(1,`setConstantAttributeWebGL(${t}) could have been skipped, value unchanged`)(),this._constants[t]=n,n.constructor){case Float32Array:Yk(this,t,n);break;case Int32Array:qk(this,t,n);break;case Uint32Array:Xk(this,t,n);break;default:throw new Error("constant")}}getExtension(t){return Rt(this.gl,t,this.extensions),this.extensions}_setWebGLDebugMetadata(t,n,i){t.luma=n;let o={props:i.spector,id:i.spector.id};t.__SPECTOR_Metadata=o}}});function Kk(r){return typeof WebGL2RenderingContext<"u"&&r instanceof WebGL2RenderingContext?!0:!!(r&&typeof r.createVertexArray=="function")}function r2(r){return{...r,debug:r.debug??hr.defaultProps.debug,debugWebGL:r.debugWebGL??hr.defaultProps.debugWebGL,debugSpectorJS:r.debugSpectorJS??!!T.get("debug-spectorjs")}}async function n2(r){let e=[];(r.debugWebGL||r.debug)&&e.push(Uw()),r.debugSpectorJS&&e.push(zw(r));let t=await Promise.allSettled(e);for(let n of t)n.status==="rejected"&&T.error(`Failed to initialize debug libraries ${n.reason}`)()}var la,zm,ua,i2=b(()=>{N();Nw();ym();la=1,zm=class extends Go{constructor(){super(...arguments);d(this,"type","webgl")}enforceWebGL2(t){Dw(t)}isSupported(){return typeof WebGL2RenderingContext<"u"}isDeviceHandle(t){return typeof WebGL2RenderingContext<"u"&&t instanceof WebGL2RenderingContext?!0:(typeof WebGLRenderingContext<"u"&&t instanceof WebGLRenderingContext&&T.warn("WebGL1 is not supported",t)(),!1)}async attach(t,n={}){let{WebGLDevice:i}=await Promise.resolve().then(()=>(Du(),Gm));if(t instanceof i)return t;let o=i.getDeviceFromContext(t);if(o)return o;if(!Kk(t))throw new Error("Invalid WebGL2RenderingContext");n=r2(n),await n2(n);let s=n.createCanvasContext===!0?{}:n.createCanvasContext;return new i({...n,_handle:t,createCanvasContext:{canvas:t.canvas,autoResize:!1,...s}})}async create(t={}){let{WebGLDevice:n}=await Promise.resolve().then(()=>(Du(),Gm));t=r2(t),await n2(t);try{let i=new n(t);T.groupCollapsed(la,`WebGLDevice ${i.id} created`)();let o=`${i._reused?"Reusing":"Created"} device with WebGL2 ${i.props.debug?"debug ":""}context: ${i.info.vendor}, ${i.info.renderer} for canvas: ${i.canvasContext.id}`;return T.probe(la,o)(),T.table(la,i.info)(),i}finally{T.groupEnd(la)(),T.info(la,"%cWebGL call tracing: luma.log.set('debug-webgl') ","color: white; background: blue; padding: 2px 6px; border-radius: 3px;")()}}};ua=new zm});var Bu=b(()=>{i2();Du();pu()});function zu(r){return h2.test(r)}function $u(r){return p2.test(r)}function m2(r){let e=h2.exec(r),t=p2.exec(r),n=e?.[1]??t?.[1]??r;try{ne.getVertexFormatInfo(n)}catch{throw new Error(`Unsupported GPUVector format ${r}`)}return n}function vr(r){let e=m2(r),t=zu(r),n=$u(r),i=ne.getVertexFormatInfo(e),o=i.type,s=i.normalized,a=r4(o,s);return{format:r,elementFormat:e,vertexList:t,valueList:n,type:o,signedDataType:n4(e,o),primitiveType:a,components:i.components,byteLength:i.byteLength,integer:i.integer,signed:i.signed,normalized:s,...i.webglOnly?{webglOnly:!0}:{}}}function r4(r,e){if(e)return"f32";switch(r){case"float32":return"f32";case"float16":return"f16";case"uint8":case"uint16":case"uint32":return"u32";case"sint8":case"sint16":case"sint32":return"i32";default:throw new Error(`Unsupported GPUVector component type ${r}`)}}function n4(r,e){if(r==="unorm10-10-10-2")return"uint32";switch(e){case"unorm8":return"uint8";case"snorm8":return"sint8";case"unorm16":return"uint16";case"snorm16":return"sint16";default:return e}}var h2,p2,Vu=b(()=>{N();h2=/^vertex-list<([^<>]+)>$/,p2=/^value-list<([^<>]+)>$/});function Wm(r,e){if(!Number.isSafeInteger(r)||r<0)throw new Error(`${e} must be a non-negative safe integer`)}var wr,jm=b(()=>{N();wr=class{constructor(e){d(this,"buffer");d(this,"format");d(this,"length");d(this,"byteOffset");d(this,"byteStride");let t=ne.getVertexFormatInfo(e.format).byteLength,n=e.byteOffset??0,i=e.byteStride??t;if(Wm(e.length,"GPUDataView length"),Wm(n,"GPUDataView byteOffset"),Wm(i,"GPUDataView byteStride"),i<t)throw new Error(`GPUDataView byteStride ${i} is smaller than ${e.format} byte length ${t}`);let o=e.length===0?0:(e.length-1)*i+t,s=n+o;if(!Number.isSafeInteger(o)||!Number.isSafeInteger(s))throw new Error("GPUDataView byte range must use safe integers");if(s>e.buffer.byteLength)throw new Error("GPUDataView exceeds its backing buffer byte length");this.buffer=e.buffer,this.format=e.format,this.length=e.length,this.byteOffset=n,this.byteStride=i}get elementByteLength(){return ne.getVertexFormatInfo(this.format).byteLength}get byteLength(){return this.length===0?0:(this.length-1)*this.byteStride+this.elementByteLength}}});function ju(r){return!!(r&&typeof r=="object"&&r.type==="struct")}function y2(r,e){let t=Object.entries(r);if(t.length===0)throw new Error("GPUData struct format must declare at least one field");return e==="packed"?i4(t):o4(t)}function i4(r){let e=[],t=0,n=0;for(let[i,o]of r){let s=ne.getVertexFormatInfo(o);if(s.webglOnly)throw new Error(`Packed GPUData struct field "${i}" uses WebGL-only format ${o}`);t=g2(t,Math.min(4,s.byteLength)),e.push([i,Object.freeze({format:o,byteOffset:t,byteLength:s.byteLength})]),t+=s.byteLength,n+=s.components}return Object.freeze({type:"struct",layout:"packed",fields:Object.freeze(Object.fromEntries(e)),components:n,byteStride:g2(t,4),rowByteLength:t})}function o4(r){let e=Object.fromEntries(r.map(([s,a])=>[s,s4(a)])),t=vn(e,{layout:"wgsl-storage"}),n=[],i=0,o=0;for(let[s,a]of r){let c=ne.getVertexFormatInfo(a),l=t.fields[s].offset*4;n.push([s,Object.freeze({format:a,byteOffset:l,byteLength:c.byteLength})]),i=Math.max(i,l+c.byteLength),o+=c.components}return Object.freeze({type:"struct",layout:"wgsl-storage",fields:Object.freeze(Object.fromEntries(n)),components:o,byteStride:t.byteLength,rowByteLength:i})}function s4(r){let e=ne.getVertexFormatInfo(r);switch(e.type){case"float32":return Wu("f32",e.components);case"sint32":return Wu("i32",e.components);case"uint32":return Wu("u32",e.components);default:{let t=Math.ceil(e.byteLength/4);return Wu("u32",t)}}}function Wu(r,e){return e===1?r:`vec${e}<${r}>`}function g2(r,e){return Math.ceil(r/e)*e}var _2=b(()=>{N()});var Hm,Ym,Ji,qm=b(()=>{jm();_2();Vu();Hm=class{constructor(e,t){d(this,"buffer");d(this,"ownsDataBuffer");this.buffer=e,this.ownsDataBuffer=t}get ownsBuffer(){return this.ownsDataBuffer}transferBufferOwnership(e){if(e.buffer!==this.buffer)throw new Error("GPUData ownership can only be transferred to the same buffer");e.ownsDataBuffer=this.ownsDataBuffer,this.ownsDataBuffer=!1}destroy(){this.ownsDataBuffer&&(this.buffer.destroy(),this.ownsDataBuffer=!1)}},Ym=class extends Hm{constructor(t){let{buffer:n,format:i,length:o,valueLength:s,stride:a,byteOffset:c=0,byteStride:l,rowByteLength:u,ownsBuffer:f=!1,readbackMetadata:h,valueOffsets:p,nullBitmap:m,valueByteLength:g,dataType:y}=t;super(n,f);d(this,"dataType");d(this,"format");d(this,"length");d(this,"valueLength");d(this,"stride");d(this,"byteOffset");d(this,"byteStride");d(this,"rowByteLength");d(this,"readbackMetadata");d(this,"valueOffsets");d(this,"nullBitmap");d(this,"valueByteLength");let x;i?typeof i=="string"?x=i:x=y2(i,t.layout??"wgsl-storage"):x=void 0;let v=ju(x)?x:void 0,_=typeof x=="string"?vr(x):void 0;if(this.dataType=y,this.format=x,this.length=o,this.valueLength=s??o,this.stride=a??_?.components??v?.components??l??u??1,this.byteOffset=c,this.rowByteLength=u??v?.rowByteLength??_?.byteLength??l??this.stride,this.byteStride=l??v?.byteStride??this.rowByteLength,v){if(this.rowByteLength<v.rowByteLength)throw new Error(`GPUData rowByteLength ${this.rowByteLength} is smaller than struct format row byte length ${v.rowByteLength}`);if(this.byteStride<Math.max(v.byteStride,this.rowByteLength))throw new Error(`GPUData byteStride ${this.byteStride} is smaller than its struct row layout`)}this.readbackMetadata=h,this.valueOffsets=p,this.nullBitmap=m,this.valueByteLength=g}getChild(t){if(!ju(this.format))return null;let n=this.format.fields[t];return n?new wr({buffer:this.buffer,format:n.format,length:this.length,byteOffset:this.byteOffset+n.byteOffset,byteStride:this.byteStride}):null}getChildAt(t){if(!ju(this.format))return null;let n=Object.values(this.format.fields)[t];return n?new wr({buffer:this.buffer,format:n.format,length:this.length,byteOffset:this.byteOffset+n.byteOffset,byteStride:this.byteStride}):null}},Ji=Ym});function b2(r){let e=r.format?vr(r.format):void 0,t=r.rowByteLength??r.byteStride??e?.byteLength;if(t===void 0)throw new Error("GPUVector requires format or explicit rowByteLength");return{stride:r.stride??e?.components??1,byteStride:r.byteStride??t,rowByteLength:t}}function a4(r){return r[0]?.format}function c4(r,e){if(r.find(n=>n.format!==e))throw new Error("GPUVector data chunks must share the declared format")}var ir,x2=b(()=>{qm();Vu();ir=class{constructor(e){d(this,"name");d(this,"dataType");d(this,"format");d(this,"length");d(this,"valueLength");d(this,"stride");d(this,"byteOffset");d(this,"byteStride");d(this,"rowByteLength");d(this,"bufferLayout");d(this,"data",[]);d(this,"device");d(this,"bufferProps");d(this,"isAppendable",!1);d(this,"ownsDataChunks",!0);d(this,"ownedVectors",[]);d(this,"appendableByteLength",0);switch(e.type){case"buffer":{let{name:t,buffer:n,format:i,length:o,valueLength:s=o,byteOffset:a=0,ownsBuffer:c=!1}=e,{stride:l,byteStride:u,rowByteLength:f}=b2(e);this.name=t,this.dataType=e.dataType,this.format=i,this.length=o,this.valueLength=s,this.stride=l,this.byteOffset=a,this.byteStride=u,this.rowByteLength=f,this.data.push(new Ji({buffer:n,format:i,length:o,valueLength:s,stride:l,byteOffset:a,byteStride:u,rowByteLength:f,ownsBuffer:c,dataType:e.dataType}));return}case"interleaved":{let{name:t,buffer:n,format:i,length:o,valueLength:s=o,byteOffset:a=0,byteStride:c,attributes:l,ownsBuffer:u=!1}=e;this.name=t,this.dataType=e.dataType,this.format=i,this.length=o,this.valueLength=s,this.stride=c,this.byteOffset=a,this.byteStride=c,this.rowByteLength=c,this.bufferLayout={name:t,byteStride:c,attributes:l},this.data.push(new Ji({buffer:n,format:i,length:o,valueLength:s,stride:c,byteOffset:a,byteStride:c,rowByteLength:c,ownsBuffer:u,dataType:e.dataType}));return}case"data":{let t=e.format??a4(e.data),n=t?vr(t):void 0,{name:i,data:o,stride:s=o[0]?.stride??n?.components??1,valueLength:a=o.reduce((h,p)=>h+p.valueLength,0),byteStride:c=o[0]?.byteStride??n?.byteLength,rowByteLength:l=o[0]?.rowByteLength??n?.byteLength,bufferLayout:u,ownsData:f=!1}=e;if(c===void 0||l===void 0)throw new Error("GPUVector requires format or explicit byte layout metadata");t&&c4(o,t),this.name=i,this.dataType=e.dataType,this.format=t,this.length=o.reduce((h,p)=>h+p.length,0),this.valueLength=a,this.stride=s,this.byteOffset=o.length===1?o[0].byteOffset:0,this.byteStride=c,this.rowByteLength=l,this.bufferLayout=u,this.ownsDataChunks=f,this.data.push(...o);return}case"appendable":{let{name:t,device:n,format:i,valueLength:o=0,bufferProps:s}=e,{stride:a,byteStride:c,rowByteLength:l}=b2(e);this.name=t,this.dataType=e.dataType,this.format=i,this.length=0,this.valueLength=o,this.stride=a,this.byteOffset=0,this.byteStride=c,this.rowByteLength=l,this.device=n,this.bufferProps=s,this.isAppendable=!0;return}}}get ownsBuffer(){return this.ownsDataChunks&&this.data.some(e=>e.ownsBuffer)||this.ownedVectors.some(e=>e.ownsBuffer)}get capacityRows(){return this.isAppendable?this.length:void 0}get appendedByteLength(){return this.appendableByteLength}addData(e){if(this.format&&e.format!==this.format)throw new Error("GPUVector.addData() requires matching formats");if(e.byteStride!==this.byteStride)throw new Error("GPUVector.addData() requires matching byteStride");if(e.rowByteLength!==this.rowByteLength)throw new Error("GPUVector.addData() requires matching rowByteLength");return this.data.push(e),this.length+=e.length,this.valueLength+=e.valueLength,this}appendDataChunk(e,t=this.appendableByteLength+e.buffer.byteLength){if(!this.isAppendable)throw new Error("GPUVector.appendDataChunk() requires appendable vector storage");if(this.format&&e.format!==this.format)throw new Error("GPUVector.appendDataChunk() requires matching formats");if(e.byteStride!==this.byteStride||e.rowByteLength!==this.rowByteLength)throw new Error("GPUVector.appendDataChunk() requires matching byte layout metadata");return this.data.push(e),this.length+=e.length,this.valueLength+=e.valueLength,this.appendableByteLength=t,this}resetLastBatch(){if(!this.isAppendable)throw new Error("GPUVector.resetLastBatch() requires appendable vector storage");for(let e of this.data.splice(0))e.destroy();return this.length=0,this.valueLength=0,this.appendableByteLength=0,this}retainOwnedVectors(e){return this.ownedVectors.push(...e),this}transferBufferOwnership(e){let t=this.data[0],n=e.data[0];if(!t||!n||t.buffer!==n.buffer)throw new Error("GPUVector ownership can only be transferred to the same buffer");t.transferBufferOwnership(n)}destroy(){if(this.ownsDataChunks)for(let e of this.data)e.destroy();for(let e of this.ownedVectors.splice(0))e.destroy()}}});var Xm=b(()=>{qm();jm();x2();Vu()});var Zm,Ve,ma=b(()=>{N();Zm=class{constructor(){d(this,"poolSize",20);d(this,"bufferPools");this.bufferPools=new Map}createOrReuse(e,t){if(t>e.limits.maxBufferSize)throw new Error(`Buffer pool cannot allocate ${t} bytes: device.limits.maxBufferSize is ${e.limits.maxBufferSize}`);let n=this.bufferPools.get(e),i=n?n.findIndex(s=>s.byteLength>=t):-1;if(i<0)return e.createBuffer({usage:z.VERTEX|z.STORAGE|z.COPY_DST|z.COPY_SRC,byteLength:t});let[o]=n.splice(i,1);return o}recycle(e){let t=e.device;this.bufferPools.has(t)||this.bufferPools.set(t,[]);let n=this.bufferPools.get(t),i=n.findIndex(o=>o.byteLength>e.byteLength);i<0?n.push(e):n.splice(i,0,e),this.purge()}purge(){for(let[e,t]of this.bufferPools){let n=e.isLost?0:this.poolSize;for(;t.length>n;)t.shift().destroy();t.length===0&&this.bufferPools.delete(e)}}},Ve=new Zm});function l4(r,e,t,n){let{ValueType:i,size:o,offset:s,stride:a}=r,c=a/i.BYTES_PER_ELEMENT,l=s/i.BYTES_PER_ELEMENT,u=n-t;if(c===o){let h=l+t*c;return e.subarray(h,h+u*o)}let f=new i(u*o);for(let h=0;h<u;h++){let p=l+(t+h)*c;f.set(e.subarray(p,p+o),h*o)}return f}function Yu(r){if(r instanceof Z)return r;if(typeof r=="number"||Array.isArray(r))return Z.fromConstant(r);if(r instanceof Ji)return Z.fromGPUData(r);if(r instanceof wr)return Z.fromGPUDataView(r);throw new Error("getGPUDataEvaluator() requires GPUDataEvaluator, GPUData, GPUDataView, number, or number[]")}function u4(r){if(!r.format)throw new Error("GPUDataEvaluator.fromGPUData() requires GPUData format metadata");if(zu(r.format)||$u(r.format))throw new Error("GPUDataEvaluator.fromGPUData() does not support variable-length input");let t=vr(r.format).byteLength;if(r.rowByteLength!==t)throw new Error(`GPUDataEvaluator.fromGPUData() requires rowByteLength ${t} for GPUData`)}function v2(r){let e=vr(r.format),t=dn(e.signedDataType),n=t.BYTES_PER_ELEMENT*e.components;if(e.byteLength!==n)throw new Error(`GPUDataEvaluator does not support packed vertex format ${r.format}: ${e.byteLength} physical bytes cannot expose ${e.components} ${e.signedDataType} components`);if(r.byteOffset%t.BYTES_PER_ELEMENT!==0||r.byteStride%t.BYTES_PER_ELEMENT!==0)throw new Error(`GPUDataEvaluator requires ${r.format} offset and stride aligned to ${t.BYTES_PER_ELEMENT} bytes`);return{type:e.signedDataType,size:e.components,offset:r.byteOffset,stride:r.byteStride,normalized:e.normalized,length:r.length,format:r.format}}function Hu(r){let e=f4(r).buffer;return e instanceof Ie?e.buffer:e}function f4(r){let[e,...t]=r.data;if(!e||t.length>0)throw new Error(`GPUDataEvaluator requires exactly one GPUData chunk for "${r.name}"`);return e}function d4(r){let e=[];return w2(r,e,{byteOffset:0}),e}function w2(r,e,t){let n=r.source;if(n&&!(n instanceof Z)&&n.name==="interleave"){for(let i of Object.values(n.inputs))i instanceof Z&&w2(i,e,t);return}e.push({attribute:r.id??r.toString(),format:E2(r.type,r.size,r.normalized),byteOffset:t.byteOffset}),t.byteOffset+=r.ValueType.BYTES_PER_ELEMENT*r.size}function E2(r,e,t=!1){if(e<1||e>4)throw new Error(`Cannot synthesize a GPUVector vertex format with ${e} components`);let n=r;if(t)switch(r){case"uint8":n="unorm8";break;case"sint8":n="snorm8";break;case"uint16":n="unorm16";break;case"sint16":n="snorm16";break;case"float32":n="float32";break;default:throw new Error(`Unsupported normalized vertex format for ${r}`)}return(n==="uint8"||n==="sint8"||n==="uint16"||n==="sint16"||n==="unorm8"||n==="snorm8"||n==="unorm16"||n==="snorm16")&&e===3?`${n}x3-webgl`:`${n}${e===1?"":`x${e}`}`}function h4(r,e,t=!1){return e>=1&&e<=4?E2(r,e,t):void 0}var Z,Er=b(()=>{N();de();Xm();ma();Z=class r{constructor(e){d(this,"type");d(this,"size");d(this,"normalized");d(this,"isConstant");d(this,"length");d(this,"ValueType");d(this,"source",null);d(this,"format");d(this,"_id");d(this,"_destroyed",!1);d(this,"_value");d(this,"_offset");d(this,"_stride");d(this,"_byteLength");d(this,"_gpuVector");d(this,"_bufferOwnership","owned");d(this,"_targetBuffer");let{id:t,value:n,buffer:i,gpuData:o,format:s,source:a=null,isConstant:c=!1}=e;if(!a&&!n&&!i&&!o)throw new Error("GPUDataEvaluator must have a value source");let{type:l,size:u,offset:f,stride:h,normalized:p,length:m}=e;if(a instanceof r?(l=l??a.type,u=u??a.size,f=f??a.offset,h=h??a.stride,p=p??a.normalized,m=m??a.length):(u=u??1,f=f??0,p=p??!1,m=c?1:m),!l)throw new Error("GPUDataEvaluator: type not defined");if(this._id=t,this.type=l,this.size=u,this.ValueType=dn(this.type),this._offset=f,this._stride=h||this.ValueType.BYTES_PER_ELEMENT*u,this.normalized=p,this.source=a,this.format=s,m===void 0)if(c)m=1;else{if(!n)throw new Error("GPUDataEvaluator: length not defined");m=Math.ceil(n.byteLength/this.stride)}this.isConstant=c,this.length=m;let g=this.ValueType.BYTES_PER_ELEMENT*this.size;this._byteLength=m===0?0:(m-1)*this.stride+g,this._value=n,this._bufferOwnership=a instanceof r||i||o?"borrowed":"owned",o?this._gpuVector=new ir({type:"data",name:this._id??"data",format:o.format,data:[o],stride:o.stride,byteStride:o.byteStride,rowByteLength:o.rowByteLength}):i&&(this._gpuVector=this.createGPUVectorView({buffer:i,name:this._id,format:this.format}))}static get bufferPoolSize(){return Ve.poolSize}static set bufferPoolSize(e){if(!Number.isSafeInteger(e)||e<0)throw new Error("GPUDataEvaluator.bufferPoolSize must be a non-negative safe integer");Ve.poolSize=e,Ve.purge()}get offset(){return this._offset}get stride(){return this._stride}get byteLength(){return this._byteLength}static fromArray(e,{type:t,size:n=1,offset:i=0,stride:o=0,normalized:s=!1}){let a=t,c;if(Array.isArray(e)){a=a||"float32";let u=dn(a);c=new u(e)}else e instanceof Float64Array?(a="uint32",n*=2,i*=2,o*=2,c=new Uint32Array(e.buffer,e.byteOffset,e.byteLength/4)):(a=a||Pc(e),c=e);let l=`<${a} * ${n}>`;return new r({id:l,type:a,size:n,offset:i,stride:o,normalized:s,value:c})}static fromConstant(e,t="float32"){let n=dn(t),i;return Array.isArray(e)?i=`[${e.join(",")}]`:(i=String(e),e=[e]),new r({id:i,isConstant:!0,type:t,size:e.length,value:new n(e)})}static fromGPUData(e,t={}){u4(e);let n=new wr({buffer:e.buffer,format:e.format,length:e.length,byteOffset:e.byteOffset,byteStride:e.byteStride});return new r({...v2(n),id:t.id,gpuData:e})}static fromGPUDataView(e,t={}){return new r({...v2(e),id:t.id,buffer:e.buffer})}get value(){return this._value||(this.source instanceof r?this.source.value:void 0)}get evaluated(){return!!this._gpuVector}get id(){return this._id}get gpuVector(){if(!this._gpuVector)throw new Error(`${this} not evaluated`);return this._gpuVector}get buffer(){return Hu(this.gpuVector)}setTargetBuffer({buffer:e,byteOffset:t=0,byteStride:n=this.stride}){if(this._destroyed)throw new Error(`GPUDataEvaluator ${this} already destroyed`);if(this._gpuVector)throw new Error(`GPUDataEvaluator ${this} already evaluated`);if(!this.source||this.source instanceof r)throw new Error("GPUDataEvaluator target buffers require a deferred operation source");this._targetBuffer={buffer:e,byteOffset:t,byteStride:n}}async evaluate(e,t={}){if(this._destroyed)throw new Error(`GPUDataEvaluator ${this} already destroyed`);if(this._gpuVector)return this._gpuVector;let n;if(this.source instanceof r){let i=await this.source.evaluate(e);return this._gpuVector=this.createGPUVectorView({...t,buffer:Hu(i)}),this._gpuVector}if(n=this._getEvaluationBuffer(e),this._value)n.write(this._value);else{let i=await this.source.execute(e,n);if(!i.success)throw i.error||new Error(`${this.source} evaluation failed`);i.value&&(this._value=i.value)}return this._gpuVector=this.createGPUVectorView({...t,buffer:n}),this._gpuVector}evaluateSync(e,t={}){if(this._destroyed)throw new Error(`GPUDataEvaluator ${this} already destroyed`);if(this._gpuVector)return this._gpuVector;let n;if(this.source instanceof r){let i=this.source.evaluateSync(e);return this._gpuVector=this.createGPUVectorView({...t,buffer:Hu(i)}),this._gpuVector}if(n=this._getEvaluationBuffer(e),this._value)n.write(this._value);else{let i=this.source.executeSync(e,n);if(!i.success)throw i.error||new Error(`${this.source} evaluation failed`);i.value&&(this._value=i.value)}return this._gpuVector=this.createGPUVectorView({...t,buffer:n}),this._gpuVector}createGPUVectorView(e){let t=e.name??this._id??"vector",n=e.format??this.format??h4(this.type,this.size,this.normalized);if(e.interleaved){let i=typeof e.interleaved=="object"&&e.interleaved.attributes?e.interleaved.attributes:d4(this);return new ir({type:"interleaved",name:t,buffer:e.buffer,format:e.format??this.format,length:this.length,byteOffset:this.offset,byteStride:this.stride,attributes:i,ownsBuffer:!1})}return new ir({type:"buffer",name:t,buffer:e.buffer,format:n,length:this.length,stride:this.size,byteOffset:this.offset,byteStride:this.stride,rowByteLength:this.ValueType.BYTES_PER_ELEMENT*this.size,ownsBuffer:!1})}_getEvaluationBuffer(e){let t=this._targetBuffer;if(!t)return Ve.createOrReuse(e,this.byteLength);if(t.buffer.device!==e)throw new Error("GPUDataEvaluator target buffer belongs to a different device");let n=this.ValueType.BYTES_PER_ELEMENT*this.size,i=this.length===0?0:(this.length-1)*t.byteStride+n;if(t.byteOffset+i>t.buffer.byteLength)throw new Error("GPUDataEvaluator target buffer is too small for the output layout");return this._offset=t.byteOffset,this._stride=t.byteStride,this._byteLength=i,this._bufferOwnership="borrowed",this._targetBuffer=void 0,t.buffer}async readValue(e=0,t){let{ValueType:n}=this,{size:i,offset:o,stride:s,length:a}=this,c=n.BYTES_PER_ELEMENT*i;if(t=t??a,e=Math.max(0,Math.min(a,e)),t=Math.max(e,Math.min(a,t)),this._value)return l4(this,this._value,e,t);let l=t-e;if(l===0)return new n(0);let u=o+e*s,f=s===c?l*c:(l-1)*s+c,h=await this.buffer.readAsync(u,f),p=new n(h.buffer,h.byteOffset,h.byteLength/n.BYTES_PER_ELEMENT);if(s===c)return p;let m=new Uint8Array(c*l);for(let g=0;g<l;g++){let y=g*s;m.set(h.subarray(y,y+c),g*c)}return new n(m.buffer)}async ensureCPUValue(){let e=this.value;if(e)return e;let t=await this.buffer.readAsync(0,this.offset+this.byteLength);if(t.byteLength%this.ValueType.BYTES_PER_ELEMENT!==0)throw new Error(`${this} backing buffer byte length is not aligned to its scalar type`);let n=t.slice();return this._value=new this.ValueType(n.buffer,n.byteOffset,n.byteLength/this.ValueType.BYTES_PER_ELEMENT),this._value}ensureCPUValueSync(){let e=this.value;if(e)return e;throw new Error(`${this} CPU value is not available for synchronous evaluation`)}toString(){return this._id??this.source?.toString()??this.constructor.name}destroy(){this._gpuVector&&(this._bufferOwnership==="owned"&&Ve.recycle(Hu(this._gpuVector)),this._gpuVector=void 0),this._targetBuffer=void 0,this._destroyed=!0}}});var eo,qu=b(()=>{eo={add:{arity:2,symbol:"arithmetic_add"},subtract:{arity:2,symbol:"arithmetic_subtract"},multiply:{arity:2,symbol:"arithmetic_multiply"},divide:{arity:2,symbol:"arithmetic_divide"},pow:{arity:2,symbol:"pow"},sqrt:{arity:1,symbol:"sqrt"},abs:{arity:1,symbol:"abs"},sin:{arity:1,symbol:"sin"},cos:{arity:1,symbol:"cos"},tan:{arity:1,symbol:"arithmetic_tan"},exp:{arity:1,symbol:"exp"},log:{arity:1,symbol:"log"}}});function F2(r,{operations:e,inputs:t}){switch(r.kind){case"input":if(!(r.name in t))throw new Error(`Unknown expression input '${r.name}'`);return;case"literal":if(Array.isArray(r.value)){for(let n of r.value)if(!Number.isFinite(n))throw new Error(`Expression literal array must contain only finite values, got ${n}`)}else if(!Number.isFinite(r.value))throw new Error(`Expression literal must be finite, got ${r.value}`);return;case"call":{let n=e[r.op];if(!n)throw new Error(`Unknown expression op '${r.op}'`);if(r.args.length!==n.arity)throw new Error(`Expression op '${r.op}' expects ${n.arity} args, got ${r.args.length}`);for(let i of r.args)F2(i,{operations:e,inputs:t});return}default:{let n=r;throw new Error(`Unsupported expression node ${n.kind}`)}}}function Xu(r,e){return F2(r,e),U2(r,e)}function U2(r,e){switch(r.kind){case"input":{let t=e.inputs[r.name];return e.laneIndex<t.size?e.formatInput(r.name):e.formatOutOfBoundsInput(r.name)}case"literal":return e.formatLiteral(r.value);case"call":{let t=e.operations[r.op],n=r.args.map(i=>U2(i,e));return e.formatCall(t.symbol,n)}default:{let t=r;throw new Error(`Unsupported expression node ${t.kind}`)}}}var eg=b(()=>{});function Oe(r,e,t=!1){if(t)return e===1?"float":`vec${e}`;switch(r){case"uint8":case"uint16":case"uint32":return e===1?"uint":`uvec${e}`;case"sint8":case"sint16":case"sint32":return e===1?"int":`ivec${e}`;default:return e===1?"float":`vec${e}`}}function Zu(r,e,t=!1){let n;if(t)switch(r){case"uint8":n="unorm8";break;case"sint8":n="snorm8";break;case"uint16":n="unorm16";break;case"sint16":n="snorm16";break;case"float32":n="float32";break;default:throw new Error(`Unsupported normalized vertex format for ${r}`)}else n=r;return e===1?n:e===3&&!n.startsWith("float32")&&!n.endsWith("32")?`${n}x3-webgl`:`${n}x${e}`}function Xr(r){switch(r[0]){case"u":return"0u";case"s":return"0";default:return"0."}}function G2(r,e){switch(r){case"uint8":case"uint16":case"uint32":return`${Math.trunc(e)}u`;case"sint8":case"sint16":case"sint32":return`${Math.trunc(e)}`;default:return Number.isInteger(e)?`${e}.0`:`${e}`}}function z2(r){switch(r){case"uint8":return"r8uint";case"sint8":return"r8sint";case"uint16":return"r16uint";case"sint16":return"r16sint";case"uint32":return"r32uint";case"sint32":return"r32sint";case"float32":return"r32float";default:throw new Error(`Unsupported WebGL gather texture format for ${r}`)}}function $2(r){switch(r){case"uint32":return"usampler2D";case"sint32":return"isampler2D";case"float32":return"sampler2D";default:throw new Error(`Unsupported WebGL gather sampler type for ${r}`)}}var ro=b(()=>{});function ke({module:r,elementWise:e=!1,expression:t,inputs:n,output:i,operationType:o=i.type,outputBuffer:s}){let a=s.device,c=Xn("result",i.type,i.size,i.normalized),l=[r,c],u=[],f={},h=Oe(i.type,1,i.normalized),p=Oe(o,1,i.normalized),m="",g=null,y={TYPE:p,RESULT_LEN:i.size.toString()},x=w4(n);for(let[E,S]of x)l.push(tg(E,S.type,S.size,S.normalized,o)),u.push(rg(E,S)),S instanceof Z?f[E]=S.buffer:(g=g||Ve.createOrReuse(a,s.byteLength),f[E]=g),m+=`TYPE ${E}[${S.size}]; get_${E}(${E});
`,y[`${E.toUpperCase()}_LEN`]=S.size.toString();let v="";if(t)for(let E=0;E<i.size;E++)v+=`result[${E}]=${t(E)};
`;else if(e)for(let E=0;E<i.size;E++){let S=Xr(p),C=x.map(([A,B])=>E<B.size?`${A}[${E}]`:S);v+=`result[${E}]=${r.name}(${C.join(", ")});
`}else v=`${r.name}(${x.map(([E])=>E).join(", ")}, result);`;let _=`#version 300 es

void main() {
${m}
${h} result[${i.size}];
${v}
set_result(result);
}
  `,w=new Be(a,{vs:_,shaderAssembler:v4,defines:y,modules:l,bufferLayout:u,vertexCount:1,instanceCount:i.length,attributes:f,feedbackBufferMode:"interleaved",outputs:c.varyings});a.statsManager.getStats(b4).get(x4).incrementCount(),w.run({inputBuffers:f,outputBuffers:{[c.varyings[0]]:i.offset===0?s:{buffer:s,byteOffset:i.offset,byteLength:i.byteLength}}}),g&&Ve.recycle(g)}function w4(r){return Array.isArray(r)?r.map((e,t)=>[`x${t}`,e]):Object.entries(r)}function tg(r,e,t,n=!1,i=e){let o="",s="";for(let c=0;c<t;c+=4){let l=Math.min(t-c,4),u=Oe(e,l,n);o+=`in ${u} a${r}_${c};
`;for(let f=0;f<l;f++){let h=`a${r}_${c}`;l>1&&(h=`${h}[${f}]`),(n||e!==i)&&(h=`TYPE(${h})`),s+=`v[${c+f}]=${h};
`}}let a=`
${o}
void get_${r}(out TYPE v[${t}]) {
  ${s}
}
`;return{name:r,vs:a}}function rg(r,e){let t={name:r,stepMode:e.isConstant?"vertex":"instance",byteStride:e.stride,attributes:[]};for(let n=0;n<e.size;n+=4){let i=Math.min(e.size-n,4);t.attributes.push({attribute:`a${r}_${n}`,format:Zu(e.type,i,e.normalized),byteOffset:e.offset+e.ValueType.BYTES_PER_ELEMENT*n})}return t}function Xn(r,e,t,n=!1){let i=[],o=Oe(e,1,n),s="",a="";for(let c=0;c<t;c+=4){let l=Math.min(t-c,4),u=Oe(e,l,n);i.push(`${r}_${c}`),s+=`flat out ${u} ${r}_${c};
`;let f=Array.from({length:l},(h,p)=>c+p);a+=`${r}_${c} = ${u}(${f.map(h=>`v[${h}]`).join(",")});
`}return{name:r,varyings:i,vs:`
${s}
void set_${r}(in ${o} v[${t}]) {
  ${a}
}
`}}var b4,x4,v4,at=b(()=>{de();qe();Er();ma();ro();b4="GPGPU Operation Counts",x4="Transform Runs",v4=new xi});var E4,Ku,ng=b(()=>{qe();eg();qu();at();ro();E4=`TYPE arithmetic_add(TYPE x, TYPE y) {
  return x + y;
}

TYPE arithmetic_subtract(TYPE x, TYPE y) {
  return x - y;
}

TYPE arithmetic_multiply(TYPE x, TYPE y) {
  return x * y;
}

TYPE arithmetic_divide(TYPE x, TYPE y) {
  return x / y;
}

float arithmetic_tan(float x) {
  return tan_fp32(x);
}
`,Ku=({inputs:r,output:e,target:t})=>{let n=e.type,i=Oe(n,1,e.normalized),o=Xr(i),s=r.namedInputs;return ke({module:{name:"arithmetic",dependencies:[Mn],vs:E4},inputs:s,output:e,operationType:n,outputBuffer:t,expression:a=>Xu(r.expression,{operations:eo,inputs:s,laneIndex:a,formatInput:c=>`${c}[${a}]`,formatOutOfBoundsInput:c=>s[c].size===1?`${c}[0]`:o,formatLiteral:c=>{let l=Array.isArray(c)?c[a]??0:c;return`${i}(${G2(n,l)})`},formatCall:(c,l)=>`${c}(${l.join(", ")})`})}),{success:!0}}});var S4,P4,W2,V2,j2=b(()=>{N();de();Er();ma();ng();at();S4="GPGPU Operation Counts",P4="Transform Runs",W2=({inputs:r,output:e,target:t})=>{let{sourceValues:n}=r,i=t.device;if(n.length===0){let f=new e.ValueType(e.length*e.size);return t.write(f),{success:!0,value:f}}if(n.isConstant){let f=n.value,h=new e.ValueType(e.length*e.size);for(let p=0;p<e.length;p++){let m=f[p];h[p*2]=m,h[p*2+1]=m}return t.write(h),{success:!0,value:h}}let o=i.createTexture({width:1,height:e.length,format:"rg32float",usage:Y.RENDER|Y.COPY_SRC|Y.COPY_DST}),s=i.createFramebuffer({colorAttachments:[o]}),a=`#version 300 es

flat out float extent_value;

void main() {
  float sourceValues[SOURCE_VALUES_LEN];
  get_sourceValues(sourceValues);
  extent_value = sourceValues[gl_VertexID];

  float y = (float(gl_VertexID) + 0.5) / float(CHANNEL_COUNT) * 2.0 - 1.0;
  gl_Position = vec4(0.0, y, 0.0, 1.0);
  gl_PointSize = 1.0;
}
  `,c=`#version 300 es

precision highp float;

flat in float extent_value;
out vec2 fragColor;

void main() {
  fragColor = vec2(-extent_value, extent_value);
}
  `,l=new Re(i,{vs:a,fs:c,topology:"point-list",parameters:{depthCompare:"always",blend:!0,blendColorSrcFactor:"one",blendColorDstFactor:"one",blendColorOperation:"max",blendAlphaSrcFactor:"one",blendAlphaDstFactor:"one",blendAlphaOperation:"max"},modules:[tg("sourceValues",n.type,n.size,n.normalized)],defines:{TYPE:"float",SOURCE_VALUES_LEN:n.size.toString(),CHANNEL_COUNT:e.length.toString()},attributes:{sourceValues:n.buffer},bufferLayout:[rg("sourceValues",n)],instanceCount:n.length,vertexCount:e.length,disableWarnings:!0}),u=Ve.createOrReuse(i,e.byteLength);try{let f=i.beginRenderPass({framebuffer:s,parameters:{viewport:[0,0,1,e.length]},clearColor:[-V2,-V2,0,0],clearDepth:!1,clearStencil:!1});i.statsManager.getStats(S4).get(P4).incrementCount(),l.draw(f),f.end();let h=i.createCommandEncoder();return h.copyTextureToBuffer({sourceTexture:o,width:1,height:e.length,destinationBuffer:u,byteOffset:0,bytesPerRow:8}),i.submit(h.finish()),Ku({device:i,inputs:{expression:{kind:"call",op:"multiply",args:[{kind:"input",name:"x"},{kind:"literal",value:[-1,1]}]},namedInputs:{x:new Z({buffer:u,size:2,type:"float32",length:e.length})}},output:e,target:t})}finally{l.destroy(),Ve.recycle(u),s.destroy(),o.destroy()}},V2=3e38});function T4(r,e){let t=e.reduce((n,[,i])=>n+Math.ceil(i.size/4),0);if(t>r)throw new Error(`interleave() requires ${t} vertex attributes, exceeding device limit ${r}`)}function L4(r,e){if(e.size>r)throw new Error(`interleave() output size ${e.size} exceeds device inter-stage component limit ${r}`)}var H2,Y2=b(()=>{at();H2=({inputs:r,output:e,target:t})=>{let n=r.map((c,l)=>[`x${l}`,c]);T4(t.device.limits.maxVertexAttributes,n),L4(t.device.limits.maxInterStageShaderVariables,e);let i=n.map(([c,l])=>`in TYPE ${c}[${l.size}]`).join(", "),o=0,s=n.map(([c,l])=>{let u=Array.from({length:l.size},(f,h)=>`  result[${o+h}] = ${c}[${h}];`).join(`
`);return o+=l.size,u}).join(`
`),a=`void interleave(${i}, out TYPE result[RESULT_LEN]) {
${s}
}
`;return ke({module:{name:"interleave",vs:a},inputs:r,output:e,outputBuffer:t}),{success:!0}}});function A4(){let r=new Uint16Array([255]);return new Uint8Array(r.buffer)[0]>0}var C4,q2,X2=b(()=>{at();C4=`#define LE ${A4()?1:0}
const uint F32_NAN = 0xffffffffu;
const uint F32_INF = 0x7f800000u;

// Find first set bit using binary search
// https://en.wikipedia.org/wiki/Find_first_set#CLZ
int countLeadingZeros(uint a) {
  if (a == 0u) return 32;
  int n = 0;
  if ((a & 0xffff0000u) == 0u) { n += 16; a = a << 16; }
  if ((a & 0xff000000u) == 0u) { n += 8;  a = a << 8;  }
  if ((a & 0xf0000000u) == 0u) { n += 4;  a = a << 4;  }
  if ((a & 0xc0000000u) == 0u) { n += 2;  a = a << 2;  }
  if ((a & 0x80000000u) == 0u) return n + 1;
  return n;
}

uint roundShiftRight(uint value, int shift) {
  if (shift <= 0) {
    return value << (-shift);
  }

  if (shift >= 32) {
    if (shift == 32 && value > 0x80000000u) {
      return 1u;
    }
    return 0u;
  }

  uint truncated = value >> shift;
  uint halfShift = 1u << (shift - 1);
  uint remainder = value & ((1u << shift) - 1u);
  if (remainder > halfShift || (remainder == halfShift && (truncated & 1u) == 1u)) {
    return truncated + 1u;
  }
  return truncated;
}

uint makeFloat_(uint sign, int exponent, uint mantissa) {
  return (sign << 31) | (uint(exponent + 127) << 23) | (mantissa & 0x7fffffu);
}

/**
 * Assemble a float32 in bit representation according to IEEE 754
 * https://en.wikipedia.org/wiki/Single-precision_floating-point_format
 */
uint makeFloat(uint sign, int exponent, uint significand) {
  if (significand == 0u) {
    return sign << 31;
  }

  // Remove any extra leading zeros for better precision
  int lead_zeros = countLeadingZeros(significand);
  // Significand is encoded as 1.fraction
  int normalizedExponent = exponent + 31 - lead_zeros;

  if (normalizedExponent > 127) {
    return (sign << 31) | F32_INF;
  }

  uint mantissa;
  if (normalizedExponent >= -126) {
    mantissa = roundShiftRight(significand, 8 - lead_zeros);
    if (mantissa >= 0x1000000u) {
      mantissa >>= 1;
      normalizedExponent++;
      if (normalizedExponent > 127) {
        return (sign << 31) | F32_INF;
      }
    }
    return makeFloat_(sign, normalizedExponent, mantissa);
  }

  int subnormalShift = -149 - exponent;
  mantissa = roundShiftRight(significand, subnormalShift);
  if (mantissa >= 0x800000u) {
    return (sign << 31) | (1u << 23);
  }
  return (sign << 31) | mantissa;
}

/**
 * Parse 8-byte memory as a float64 number according to IEEE 754
 * https://en.wikipedia.org/wiki/Double-precision_floating-point_format
 * Returns 8-byte memory as 2 float32 numbers, consisting of
 * high part: fround(d)
 * low part: d - fround(d)
 */
uvec2 parseAsDouble(uvec2 d) {
  #if LE
  d = d.yx; // to big endian
  #endif

  uint sign = (d[0] >> 31) & 1u; // first bit
  uint exponentBits = (d[0] >> 20) & 0x7ffu;
  int exponent = int(exponentBits) - 1023; // next 11 bits
  uint fractionHigh = d[0] & 0xfffffu;
  uint fractionLow = d[1];

  if (exponentBits == 0x7ffu) {
    if (fractionHigh == 0u && fractionLow == 0u) {
      return uvec2((sign << 31) | F32_INF, F32_NAN);
    }
    return uvec2(F32_NAN);
  }
  
  if (exponentBits == 0u) {
    // All float64 subnormals are too small to survive a float32 split.
    return uvec2(sign << 31);
  }

  if (exponent > 127) {
    return uvec2((sign << 31) | F32_INF, ((1u - sign) << 31) | F32_INF);
  }

  uint hi_part;
  uint low_part;

  // float64 significand has 52 bits
  // float32 significand has 23 bits
  // The significand of the high part is the significand of the double, trimmed
  uint f_hi = 0x800000u | (fractionHigh << 3) | (fractionLow >> 29);
  uint f_low = fractionLow & 0x1fffffffu;

  if (exponent < -126) {
    // For tiny normals, the top 24 significand bits still contribute to the float32
    // high part, but they land in the float32 subnormal range.
    hi_part = makeFloat(sign, exponent - 23, f_hi);

    // The residual keeps the remaining 29 significand bits at the original double scale.
    low_part = makeFloat(sign, exponent - 52, f_low);
    return uvec2(hi_part, low_part);
  }

  bool roundUp = f_low > 0x10000000u || (f_low == 0x10000000u && (f_hi & 1u) == 1u);

  uint f_rounded = f_hi + (roundUp ? 1u : 0u);
  int exponent_hi = exponent;
  if (f_rounded == 0x1000000u) {
    f_rounded = 0x800000u;
    exponent_hi++;
  }

  if (exponent_hi > 127) {
    // Overflows float32 limit
    hi_part = (sign << 31) | F32_INF;
    low_part = ((1u - sign) << 31) | F32_INF;
    return uvec2(hi_part, low_part);
  }
  
  hi_part = makeFloat_(sign, exponent_hi, f_rounded);

  int remainder = int(f_low);
  uint sign_low = sign;
  if (roundUp) {
    remainder -= 0x20000000;
  }
  if (remainder < 0) {
    sign_low = 1u - sign;
    remainder = -remainder;
  }
  low_part = makeFloat(sign_low, exponent - 52, uint(remainder));

  return uvec2(hi_part, low_part);
}

void fround(in uint x[X_LEN], out float result[X_LEN]) {
  int n = X_LEN / 2;
  for (int i = 0; i < n; i++) {
    uvec2 f = parseAsDouble(uvec2(x[i * 2], x[i * 2 + 1]));
    result[i] = uintBitsToFloat(f.x);
    result[i + n] = uintBitsToFloat(f.y);
  }
}
`,q2=({inputs:r,output:e,target:t})=>(ke({module:{name:"fround",vs:C4},inputs:r,output:e,operationType:"uint32",outputBuffer:t}),{success:!0})});function Qu(r,e,t){let n=$2(t),i=Oe(e,1),o=Array.from({length:r.size},(s,a)=>`  v[${a}] = ${i}(texelFetch(source_values_texture, ivec2(${a}, rowIndex), 0).r);`).join(`
`);return{name:"source_values_texture",vs:`
uniform highp ${n} source_values_texture;
void read_source_values(int rowIndex, out TYPE v[${r.size}]) {
${o}
}
`}}function Ju(r,e,t){let n=t.createTexture({width:Math.max(r.size,1),height:r.length,format:z2(e),usage:Y.SAMPLE|Y.COPY_DST});if(r.length===0)return n;let i=t.createCommandEncoder();return i.copyBufferToTexture({sourceBuffer:r.buffer,destinationTexture:n,byteOffset:r.offset,bytesPerRow:r.stride,rowsPerImage:r.length,size:[r.size,r.length,1]}),t.submit(i.finish()),n}var ig=b(()=>{N();ro()});function M4(r,e){let t=Oe(r.type,1),n="aids_0";return r.type!==B4(e)&&(n=`${e}(${n})`),{name:"ids",vs:`
in ${t} aids_0;
void get_ids(out INDEX_TYPE v[1]) {
  v[0] = ${n};
}
`}}function I4(r){return{name:"ids",stepMode:r.isConstant?"vertex":"instance",byteStride:r.stride,attributes:[{attribute:"aids_0",format:Zu(r.type,1,r.normalized),byteOffset:r.offset}]}}function R4(r){return{name:"gather",vs:`
void zero_result(out TYPE result[RESULT_LEN]) {
  for (int i = 0; i < RESULT_LEN; i++) {
    result[i] = ${Xr(r)};
  }
}

void gather(in INDEX_TYPE ids[1], out TYPE result[RESULT_LEN]) {
  int sourceIndex = int(ids[0]);
  if (sourceIndex < 0 || sourceIndex >= SOURCE_VALUES_ROWS) {
    zero_result(result);
    return;
  }
  read_source_values(sourceIndex, result);
}
`}}function B4(r){switch(r){case"uint":return"uint32";case"int":return"sint32";default:return"float32"}}var Z2,K2=b(()=>{de();ro();at();ig();Z2=async({inputs:r,output:e,target:t})=>{let{ids:n,sourceValues:i}=r,o=t.device,s=Xn("result",e.type,e.size),a=Oe(n.type,1),c=Oe(e.type,1),l=e.type,u=Ju(i,l,o),f=`#version 300 es

void main() {
  INDEX_TYPE ids[1];
  get_ids(ids);
  TYPE result[${e.size}];
  gather(ids, result);
  set_result(result);
}
  `,h=new Be(o,{vs:f,defines:{INDEX_TYPE:a,TYPE:c,RESULT_LEN:e.size.toString(),SOURCE_VALUES_ROWS:i.length.toString()},modules:[M4(n,a),Qu(i,e.type,l),R4(e.type),s],bindings:{source_values_texture:u},bufferLayout:[I4(n)],vertexCount:1,instanceCount:e.length,feedbackBufferMode:"interleaved",outputs:s.varyings});try{return h.run({inputBuffers:{ids:n.buffer},outputBuffers:{[s.varyings[0]]:t}}),{success:!0}}finally{h.destroy(),u.destroy()}}});var O4,Q2,J2=b(()=>{at();O4=`void row_dot(in TYPE x[X_LEN], in TYPE y[Y_LEN], out float result[1]) {
  float sum = 0.0;
  for (int i = 0; i < X_LEN; i++) {
    sum += float(x[i]) * float(y[i]);
  }
  result[0] = sum;
}
`,Q2=({inputs:r,output:e,target:t})=>(ke({module:{name:"row_dot",vs:O4},inputs:r,output:e,operationType:"float32",outputBuffer:t}),{success:!0})});var k4,e1,t1=b(()=>{at();k4=`void equalAll(in TYPE x[X_LEN], in TYPE y[Y_LEN], out uint result[1]) {
  uint allEqual = uint(1);
  for (int i = 0; i < X_LEN; i++) {
    if (x[i] != y[i]) {
      allEqual = uint(0);
      break;
    }
  }
  result[0] = allEqual;
}
`,e1=({inputs:r,output:e,target:t})=>(ke({module:{name:"equalAll",vs:k4},inputs:r,output:e,operationType:e.type==="uint32"?r.x.type:e.type,outputBuffer:t}),{success:!0})});var D4,r1,n1=b(()=>{at();D4=`void row_length(in TYPE x[X_LEN], out float result[1]) {
  float sum = 0.0;
  for (int i = 0; i < X_LEN; i++) {
    sum += float(x[i]) * float(x[i]);
  }
  result[0] = sqrt(sum);
}
`,r1=({inputs:r,output:e,target:t})=>(ke({module:{name:"row_length",vs:D4},inputs:r,output:e,operationType:"float32",outputBuffer:t}),{success:!0})});function N4(){return{name:"segmentedMap",vs:`
uint read_segment_start(int segmentIndex) {
  TYPE value[1];
  read_source_values(segmentIndex, value);
  return uint(value[0]);
}

void segmentedMap(out TYPE result[RESULT_LEN]) {
  uint vertexIndex = uint(gl_InstanceID);
  int low = 0;
  int high = SEGMENTS_LENGTH;

  while (low < high) {
    int mid = low + (high - low) / 2;
    uint midStart = read_segment_start(mid);
    if (midStart <= vertexIndex) {
      low = mid + 1;
    } else {
      high = mid;
    }
  }

  uint segmentIndex = uint(max(low - 1, 0));
  uint segmentStart = read_segment_start(int(segmentIndex));
  result[0] = segmentIndex;
  result[1] = vertexIndex - segmentStart;
}
`}}var i1,o1=b(()=>{de();ig();at();i1=async({inputs:r,output:e,target:t})=>{let{segments:n}=r,i=t.device,o=Xn("result",e.type,e.size),s=n.type,a=Ju(n,s,i),c=new Be(i,{vs:`#version 300 es

void main() {
  TYPE result[RESULT_LEN];
  segmentedMap(result);
  set_result(result);
}
`,defines:{TYPE:"uint",RESULT_LEN:e.size.toString(),SEGMENTS_LENGTH:n.length.toString()},modules:[Qu(n,e.type,s),N4(),o],bindings:{source_values_texture:a},vertexCount:1,instanceCount:e.length,feedbackBufferMode:"interleaved",outputs:o.varyings});try{return c.run({outputBuffers:{[o.varyings[0]]:t}}),{success:!0}}finally{c.destroy(),a.destroy()}}});function og(r,e,t,n){return t<e.size?`${r}[${t}]`:e.size===1?`${r}[0]`:n}var s1,a1=b(()=>{at();ro();s1=async({inputs:r,output:e,target:t})=>{let n=Oe(e.type,1,e.normalized),i=Xr(n);return ke({module:{name:"select",vs:""},inputs:r,output:e,operationType:e.type,outputBuffer:t,expression:o=>{let s=og("condition",r.condition,o,i),a=og("whenTrue",r.whenTrue,o,i),c=og("whenFalse",r.whenFalse,o,i);return`(${s} != ${i} ? ${a} : ${c})`}}),{success:!0}}});var c1,l1=b(()=>{de();at();c1=({inputs:r,output:e,target:t})=>{let n=Xn("result",e.type,e.size),i=new Be(t.device,{vs:`#version 300 es

void main() {
  int result[1];
  result[0] = START + gl_InstanceID * STEP;
  set_result(result);
}
`,defines:{START:r.start.toString(),STEP:r.step.toString()},modules:[n],vertexCount:1,instanceCount:e.length,feedbackBufferMode:"interleaved",outputs:n.varyings});try{return i.run({outputBuffers:{[n.varyings[0]]:t}}),{success:!0}}finally{i.destroy()}}});var u1,f1=b(()=>{at();u1=({inputs:r,output:e,target:t})=>{let{columns:n}=r;return ke({module:{name:"swizzle",vs:"// swizzle expression handled inline"},expression:i=>`x[${n[i]}]`,inputs:{x:r.x},output:e,outputBuffer:t}),{success:!0}}});var d1={};cr(d1,{arithmetic:()=>Ku,dot:()=>Q2,equalAll:()=>e1,extent:()=>W2,fround:()=>q2,gather:()=>Z2,interleave:()=>H2,length:()=>r1,segmentedMap:()=>i1,select:()=>s1,sequence:()=>c1,swizzle:()=>u1});var h1=b(()=>{ng();j2();Y2();X2();K2();J2();t1();n1();o1();a1();l1();f1()});function or(r,e){let t=F4(e),n=Math.max(1,Math.ceil(r)),i=Math.min(n,t),o=Math.min(Math.ceil(n/i),t),s=Math.ceil(n/i/o);if(s>t)throw new Error(`WebGPU dispatch requires ${n} workgroups, exceeding the 3D dispatch limit of ${t} per dimension`);return{x:i,y:o,z:s}}function sg(r,e="workgroupId"){return`((${e}.z * ${r.y}u + ${e}.y) * ${r.x}u + ${e}.x)`}function Zr(r,e,t="workgroupId",n="localId"){return`(${sg(r,t)} * ${e}u + ${n}.x)`}function F4(r){return Number.isFinite(r)&&r>0?Math.floor(r):65535}var no=b(()=>{});function Kr(r,e){switch(r){case"u32":return`${e}u`;case"f32":return Number.isInteger(e)?`${e}.0`:`${e}`;default:return`${e}`}}function p1(r,e){switch(r){case"uint32":return Kr("u32",Math.trunc(e));case"sint32":return`${Math.trunc(e)}`;case"float32":return Kr("f32",e);default:throw new Error(`WebGPU operations only support 32-bit output types, got ${r}`)}}function Qr(r){switch(r){case"uint32":return"0u";case"sint32":return"0";case"float32":return"0.0";default:throw new Error(`WebGPU operations only support 32-bit output types, got ${r}`)}}function te(r){switch(r){case"uint32":return"u32";case"sint32":return"i32";case"float32":return"f32";default:throw new Error(`WebGPU operations only support 32-bit storage types, got ${r}`)}}var Zn=b(()=>{});function De({module:r,elementWise:e=!1,expression:t,inputs:n,output:i,operationType:o=i.type,outputBuffer:s}){if(!r.source)throw new Error(`WebGPU computation ${r.name} requires WGSL source`);let a=Y4(n),c=a.map(([v,_])=>({name:v,input:_})),l=c.filter(({input:v})=>!v.isConstant).map((v,_)=>({...v,index:_})),u=te(o),f=te(i.type),h={TYPE:u,RESULT_LEN:i.size.toString()},p=or(Math.ceil(i.length/ag),s.device.limits.maxComputeWorkgroupsPerDimension);for(let[v,_]of a)h[`${v.toUpperCase()}_LEN`]=_.size.toString();let m=`
${X4(r.source,h)}
${l.map(({name:v,input:_,index:w})=>$4(v,_,w)).join(`
`)}
${c.map(({name:v,input:_})=>V4(v,_,o)).join(`
`)}
${W4(i,l.length)}
${j4(i)}

@compute @workgroup_size(${ag}) fn main(
  @builtin(workgroup_id) workgroupId: vec3<u32>,
  @builtin(local_invocation_id) localId: vec3<u32>
) {
  let rowIndex = ${Zr(p,ag)};
  if (rowIndex >= ${i.length}u) {
    return;
  }

${c.map(({name:v})=>`  let ${v} = read_${v}(rowIndex);`).join(`
`)}
  var result: array<${f}, ${i.size}>;
${H4(r.name,a,i,e,t)}
  write_result(rowIndex, result);
}
`,g=new ot(s.device,{source:m,modules:r.dependencies,shaderAssembler:z4,shaderLayout:{bindings:[...l.map(({name:v},_)=>({name:v,type:"storage",group:0,location:_})),{name:"result",type:"storage",group:0,location:l.length}]}}),y=Object.fromEntries(l.map(({name:v,input:_})=>[v,_.buffer]));y.result=s,g.setBindings(y);let x=s.device.beginComputePass({});s.device.statsManager.getStats(U4).get(G4).incrementCount(),g.dispatch(x,p.x,p.y,p.z),x.end(),s.device.submit(),g.destroy()}function $4(r,e,t){if(e.isConstant)return"";let n=te(e.type);return`@group(0) @binding(${t}) var<storage, read> ${r}: array<${n}>;`}function V4(r,e,t){let n=te(t),i=e.type===t?"":n,o=e.stride/e.ValueType.BYTES_PER_ELEMENT,s=e.offset/e.ValueType.BYTES_PER_ELEMENT;return e.isConstant?`fn read_${r}(_rowIndex: u32) -> array<${n}, ${e.size}> {
  return array<${n}, ${e.size}>(${q4(e,i)});
}`:`fn read_${r}(rowIndex: u32) -> array<${n}, ${e.size}> {
  var value: array<${n}, ${e.size}>;
  let rowOffset = ${s}u + rowIndex * ${o}u;
${Array.from({length:e.size},(a,c)=>i?`  value[${c}] = ${i}(${r}[rowOffset + ${c}u]);`:`  value[${c}] = ${r}[rowOffset + ${c}u];`).join(`
`)}
  return value;
}`}function W4(r,e){let t=te(r.type);return`@group(0) @binding(${e}) var<storage, read_write> result: array<${t}>;`}function j4(r){let e=r.stride/r.ValueType.BYTES_PER_ELEMENT,t=r.offset/r.ValueType.BYTES_PER_ELEMENT;return`fn write_result(rowIndex: u32, value: array<${te(r.type)}, ${r.size}>) {
  let rowOffset = ${t}u + rowIndex * ${e}u;
${Array.from({length:r.size},(i,o)=>`  result[rowOffset + ${o}u] = value[${o}];`).join(`
`)}
}`}function H4(r,e,t,n,i){let o="";if(i)for(let s=0;s<t.size;s++)o+=`  result[${s}] = ${i(s)};
`;else if(n){let s=Qr(t.type),a=te(t.type);for(let c=0;c<t.size;c++){let l=e.map(([u,f])=>c<f.size?te(f.type)===a?`${u}[${c}]`:`${a}(${u}[${c}])`:s);o+=`  result[${c}] = ${r}(${l.join(", ")});
`}}else o+=`result = ${r}(${e.map(([s])=>s).join(", ")});`;return o.trimEnd()}function Y4(r){return Array.isArray(r)?r.map((e,t)=>[`x${t}`,e]):Object.entries(r)}function q4(r,e){let t=r.value;if(!t)throw new Error(`Constant input ${r} is missing CPU values`);return Array.from({length:r.size},(n,i)=>Kr(e,t[i]??0)).join(", ")}function X4(r,e){for(let t in e)r=r.replaceAll(`{${t}}`,e[t]);return r}var ag,U4,G4,z4,Sr=b(()=>{de();qe();no();Zn();ag=64,U4="GPGPU Operation Counts",G4="Computation Runs",z4=new Nr});var Z4,m1,g1=b(()=>{qe();eg();qu();Sr();Zn();Z4=`fn arithmetic_add(x: {TYPE}, y: {TYPE}) -> {TYPE} {
  return x + y;
}

fn arithmetic_subtract(x: {TYPE}, y: {TYPE}) -> {TYPE} {
  return x - y;
}

fn arithmetic_multiply(x: {TYPE}, y: {TYPE}) -> {TYPE} {
  return x * y;
}

fn arithmetic_divide(x: {TYPE}, y: {TYPE}) -> {TYPE} {
  return x / y;
}

fn arithmetic_tan(x: f32) -> f32 {
  return tan_fp32(x);
}
`,m1=({inputs:r,output:e,target:t})=>{let n=e.type,i=te(n),o=Qr(n),s=r.namedInputs;return De({module:{name:"arithmetic",source:Z4,dependencies:[Mn]},inputs:s,output:e,operationType:n,outputBuffer:t,expression:a=>Xu(r.expression,{operations:eo,inputs:s,laneIndex:a,formatInput:c=>`${c}[${a}]`,formatOutOfBoundsInput:c=>s[c].size===1?`${c}[0]`:o,formatLiteral:c=>{let l=Array.isArray(c)?c[a]??0:c;return`${i}(${p1(n,l)})`},formatCall:(c,l)=>`${c}(${l.join(", ")})`})}),{success:!0}}});var K4,y1,_1=b(()=>{Sr();K4=`fn row_dot(x: array<{TYPE}, {X_LEN}>, y: array<{TYPE}, {Y_LEN}>) -> array<f32, 1> {
  var sum = 0.0;
  for (var i = 0u; i < {X_LEN}u; i = i + 1u) {
    sum += f32(x[i]) * f32(y[i]);
  }
  return array<f32, 1>(sum);
}
`,y1=({inputs:r,output:e,target:t})=>(De({module:{name:"row_dot",source:K4},inputs:r,output:e,operationType:"float32",outputBuffer:t}),{success:!0})});var Q4,b1,x1=b(()=>{Sr();Q4=`fn equalAll(x: array<{TYPE}, {X_LEN}>, y: array<{TYPE}, {Y_LEN}>) -> array<u32, 1> {
  var allEqual = 1u;
  for (var i = 0u; i < {X_LEN}u; i = i + 1u) {
    if (x[i] != y[i]) {
      allEqual = 0u;
      break;
    }
  }
  return array<u32, 1>(allEqual);
}
`,b1=({inputs:r,output:e,target:t})=>(De({module:{name:"equalAll",source:Q4},inputs:r,output:e,operationType:r.x.type,outputBuffer:t}),{success:!0})});function io(r,e,t){let n=te(e.type);return`@group(0) @binding(${t}) var<storage, read> ${r}: array<${n}>;`}function cg(r,e,t,n=r){let i=te(t);if(e.isConstant){let l=e.value;if(!l)throw new Error(`Constant input ${e} is missing CPU values`);return`fn read_${n}(_sourceIndex: u32) -> array<${i}, ${e.size}> {
  return array<${i}, ${e.size}>(${Array.from({length:e.size},(u,f)=>Kr(i,l[f]??0)).join(", ")});
}`}let o=e.stride/e.ValueType.BYTES_PER_ELEMENT,s=e.offset/e.ValueType.BYTES_PER_ELEMENT,c=te(e.type)===i?"":`${i}`;return`fn read_${n}(sourceIndex: u32) -> array<${i}, ${e.size}> {
  var value: array<${i}, ${e.size}>;
  let rowOffset = ${s}u + sourceIndex * ${o}u;
${Array.from({length:e.size},(l,u)=>c?`  value[${u}] = ${c}(${r}[rowOffset + ${u}u]);`:`  value[${u}] = ${r}[rowOffset + ${u}u];`).join(`
`)}
  return value;
}`}function ef(r,e){return cg("sourceValues",r,e,"source_values")}function oo(r,e){let t=te(r.type);return`@group(0) @binding(${e}) var<storage, read_write> result: array<${t}>;`}function so(r){let e=r.stride/r.ValueType.BYTES_PER_ELEMENT,t=r.offset/r.ValueType.BYTES_PER_ELEMENT;return`fn write_result(rowIndex: u32, value: array<${te(r.type)}, ${r.size}>) {
  let rowOffset = ${t}u + rowIndex * ${e}u;
${Array.from({length:r.size},(i,o)=>`  result[rowOffset + ${o}u] = value[${o}];`).join(`
`)}
}`}function v1(r,e){let t=Qr(r);return`fn zero_result() -> array<${te(r)}, ${e}> {
  var result: array<${te(r)}, ${e}>;
${Array.from({length:e},(n,i)=>`  result[${i}] = ${t};`).join(`
`)}
  return result;
}`}var We,tf=b(()=>{Zn();We=64});function J4({input:r,inputMode:e,inputGroupCount:t,channelCount:n,outputType:i,outputBuffer:o,outputLength:s,outputStride:a,outputOffset:c}){let l=te(i),u=or(s,o.device.limits.maxComputeWorkgroupsPerDimension),f=new Z({buffer:o,type:i,size:2,length:s,stride:a,offset:c}),h=`
${r.isConstant?"":io("sourceValues",r,0)}
${ef(r,i)}
${oo(f,r.isConstant?0:1)}
${so(f)}
${eD(e,i,n,t)}

var<workgroup> sharedMin: array<${l}, ${We}>;
var<workgroup> sharedMax: array<${l}, ${We}>;

@compute @workgroup_size(${We}) fn main(
  @builtin(workgroup_id) workgroupId: vec3<u32>,
  @builtin(local_invocation_id) localId: vec3<u32>
) {
  let outputRowIndex = ${sg(u)};
  if (outputRowIndex >= ${s}u) {
    return;
  }

  let channelIndex = outputRowIndex % ${n}u;
  let outputGroupIndex = outputRowIndex / ${n}u;
  let inputGroupIndex = outputGroupIndex * ${We}u + localId.x;

  let result = extent_pass(channelIndex, inputGroupIndex);
  sharedMin[localId.x] = result[0];
  sharedMax[localId.x] = result[1];
  workgroupBarrier();

  var stride = ${Math.floor(We/2)}u;
  loop {
    if (stride == 0u) {
      break;
    }
    if (localId.x < stride) {
      let compareIndex = localId.x + stride;
      if (sharedMin[compareIndex] < sharedMin[localId.x]) {
        sharedMin[localId.x] = sharedMin[compareIndex];
      }
      if (sharedMax[compareIndex] > sharedMax[localId.x]) {
        sharedMax[localId.x] = sharedMax[compareIndex];
      }
    }
    workgroupBarrier();
    stride = stride / 2u;
  }

  if (localId.x == 0u) {
    write_result(outputRowIndex, array<${l}, 2>(sharedMin[0], sharedMax[0]));
  }
}
`,p=new ot(o.device,{source:h,shaderLayout:{bindings:[...r.isConstant?[]:[{name:"sourceValues",type:"storage",group:0,location:0}],{name:"result",type:"storage",group:0,location:r.isConstant?0:1}]}}),m={result:o};r.isConstant||(m.sourceValues=r.buffer),p.setBindings(m);let g=o.device.beginComputePass({});p.dispatch(g,u.x,u.y,u.z),g.end(),o.device.submit(),p.destroy()}function eD(r,e,t,n){let i=te(e),[o,s]=tD(e);return r==="raw"?`fn extent_pass(channelIndex: u32, inputGroupIndex: u32) -> array<${i}, 2> {
  var result: array<${i}, 2>;
  result[0] = ${o};
  result[1] = ${s};

  if (inputGroupIndex < ${n}u) {
    let value = read_source_values(inputGroupIndex);
    result[0] = value[channelIndex];
    result[1] = value[channelIndex];
  }

  return result;
}`:`fn extent_pass(channelIndex: u32, inputGroupIndex: u32) -> array<${i}, 2> {
  var result: array<${i}, 2>;
  result[0] = ${o};
  result[1] = ${s};

  if (inputGroupIndex < ${n}u) {
    let rowIndex = inputGroupIndex * ${t}u + channelIndex;
    let value = read_source_values(rowIndex);
    result[0] = value[0];
    result[1] = value[1];
  }

  return result;
}`}function tD(r){switch(r){case"uint32":return["0xffffffffu","0u"];case"sint32":return["2147483647","-2147483648"];case"float32":return["3.402823e38","-3.402823e38"];default:throw new Error(`Unsupported WebGPU extent type for ${r}`)}}var w1,E1=b(()=>{de();Er();ma();no();Zn();tf();w1=({inputs:r,output:e,target:t})=>{let{sourceValues:n}=r;if(n.length===0){let c=new e.ValueType(e.length*e.size);return t.write(c),{success:!0,value:c}}if(n.isConstant){let c=n.value;if(!c)throw new Error(`Constant input ${n} is missing CPU values`);let l=new e.ValueType(e.length*e.size);for(let u=0;u<e.length;u++){let f=c[u];l[u*2]=f,l[u*2+1]=f}return t.write(l),{success:!0,value:l}}let i=[],o=n,s="raw",a=n.length;try{for(;;){let c=Math.ceil(a/We),l=e.length*c,u=c===1?t:Ve.createOrReuse(t.device,l*e.stride);if(c>1&&i.push(u),J4({input:o,inputMode:s,inputGroupCount:a,channelCount:e.length,outputType:e.type,outputBuffer:u,outputLength:l,outputStride:e.stride,outputOffset:e.offset}),c===1)break;o=new Z({buffer:u,type:e.type,size:2,length:l}),s="partial",a=c}return{success:!0}}finally{for(let c of i)Ve.recycle(c)}}});function rD(){let r=new Uint16Array([255]);return new Uint8Array(r.buffer)[0]>0}var nD,S1,P1=b(()=>{Sr();nD=`const LE: bool = ${rD()?"true":"false"};
const F32_NAN: u32 = 0xffffffffu;
const F32_INF: u32 = 0x7f800000u;

fn roundShiftRight(value: u32, shift: i32) -> u32 {
  if (shift <= 0) {
    return value << u32(-shift);
  }

  if (shift >= 32) {
    if (shift == 32 && value > 0x80000000u) {
      return 1u;
    }
    return 0u;
  }

  let shiftU32 = u32(shift);
  let truncated = value >> shiftU32;
  let halfShift = 1u << u32(shift - 1);
  let remainder = value & ((1u << shiftU32) - 1u);
  if (remainder > halfShift || (remainder == halfShift && (truncated & 1u) == 1u)) {
    return truncated + 1u;
  }
  return truncated;
}

fn makeFloatImmediate(sign: u32, exponent: i32, mantissa: u32) -> u32 {
  return (sign << 31u) | (u32(exponent + 127) << 23u) | (mantissa & 0x7fffffu);
}

fn makeFloat(sign: u32, exponent: i32, significand: u32) -> u32 {
  if (significand == 0u) {
    return sign << 31u;
  }

  let leadingZeros = i32(countLeadingZeros(significand));
  var normalizedExponent = exponent + 31 - leadingZeros;

  if (normalizedExponent > 127) {
    return (sign << 31u) | F32_INF;
  }

  var mantissa: u32;
  if (normalizedExponent >= -126) {
    mantissa = roundShiftRight(significand, 8 - leadingZeros);
    if (mantissa >= 0x1000000u) {
      mantissa = mantissa >> 1u;
      normalizedExponent += 1;
      if (normalizedExponent > 127) {
        return (sign << 31u) | F32_INF;
      }
    }
    return makeFloatImmediate(sign, normalizedExponent, mantissa);
  }

  let subnormalShift = -149 - exponent;
  mantissa = roundShiftRight(significand, subnormalShift);
  if (mantissa >= 0x800000u) {
    return (sign << 31u) | (1u << 23u);
  }
  return (sign << 31u) | mantissa;
}

fn parseAsDouble(words: vec2<u32>) -> vec2<u32> {
  var d = words;
  if (LE) {
    d = d.yx;
  }

  let sign = (d.x >> 31u) & 1u;
  let exponentBits = (d.x >> 20u) & 0x7ffu;
  let exponent = i32(exponentBits) - 1023;
  let fractionHigh = d.x & 0xfffffu;
  let fractionLow = d.y;

  if (exponentBits == 0x7ffu) {
    if (fractionHigh == 0u && fractionLow == 0u) {
      return vec2<u32>((sign << 31u) | F32_INF, F32_NAN);
    }
    return vec2<u32>(F32_NAN);
  }

  if (exponentBits == 0u) {
    return vec2<u32>(sign << 31u);
  }

  if (exponent > 127) {
    return vec2<u32>((sign << 31u) | F32_INF, ((1u - sign) << 31u) | F32_INF);
  }

  let highSignificand = 0x800000u | (fractionHigh << 3u) | (fractionLow >> 29u);
  let lowSignificand = fractionLow & 0x1fffffffu;

  if (exponent < -126) {
    let highPart = makeFloat(sign, exponent - 23, highSignificand);
    let lowPart = makeFloat(sign, exponent - 52, lowSignificand);
    return vec2<u32>(highPart, lowPart);
  }

  let roundUp = lowSignificand > 0x10000000u ||
    (lowSignificand == 0x10000000u && (highSignificand & 1u) == 1u);

  var roundedSignificand = highSignificand + select(0u, 1u, roundUp);
  var highExponent = exponent;
  if (roundedSignificand == 0x1000000u) {
    roundedSignificand = 0x800000u;
    highExponent += 1;
  }

  if (highExponent > 127) {
    return vec2<u32>((sign << 31u) | F32_INF, ((1u - sign) << 31u) | F32_INF);
  }

  let highPart = makeFloatImmediate(sign, highExponent, roundedSignificand);

  var remainder = i32(lowSignificand);
  var lowSign = sign;
  if (roundUp) {
    remainder -= 0x20000000;
  }
  if (remainder < 0) {
    lowSign = 1u - sign;
    remainder = -remainder;
  }

  let lowPart = makeFloat(lowSign, exponent - 52, u32(remainder));
  return vec2<u32>(highPart, lowPart);
}

fn fround(x: array<u32, {X_LEN}>) -> array<f32, {RESULT_LEN}> {
  var result: array<f32, {RESULT_LEN}>;
  let n = {X_LEN}u / 2u;
  for (var i = 0u; i < n; i = i + 1u) {
    let parts = parseAsDouble(vec2<u32>(x[i * 2u], x[i * 2u + 1u]));
    result[i] = bitcast<f32>(parts.x);
    result[i + n] = bitcast<f32>(parts.y);
  }
  return result;
}
`,S1=({inputs:r,output:e,target:t})=>(De({module:{name:"fround",source:nD},inputs:r,output:e,operationType:"uint32",outputBuffer:t}),{success:!0})});function iD(r,e){if(r.isConstant){let i=r.value;if(!i)throw new Error(`Constant input ${r} is missing CPU values`);return`fn read_ids(_rowIndex: u32) -> ${e} {
  return ${Kr(e,i[0]??0)};
}`}let t=r.stride/r.ValueType.BYTES_PER_ELEMENT,n=r.offset/r.ValueType.BYTES_PER_ELEMENT;return`fn read_ids(rowIndex: u32) -> ${e} {
  let rowOffset = ${n}u + rowIndex * ${t}u;
  return ids[rowOffset];
}`}function oD(r,e,t,n){let i=te(r),o=te(e);return`fn gather(idsValue: ${i}) -> array<${o}, ${t}> {
  let sourceIndex = ${i==="u32"?"i32(idsValue)":i==="i32"?"idsValue":"i32(idsValue)"};
  if (sourceIndex < 0 || sourceIndex >= ${n}) {
    return zero_result();
  }
  return read_source_values(u32(sourceIndex));
}`}var T1,L1=b(()=>{de();no();Zn();tf();T1=async({inputs:r,output:e,target:t})=>{let{ids:n,sourceValues:i}=r,o=te(n.type),s=[];n.isConstant||s.push({name:"ids",input:n,index:s.length}),i.isConstant||s.push({name:"sourceValues",input:i,index:s.length});let a=or(Math.ceil(e.length/We),t.device.limits.maxComputeWorkgroupsPerDimension),c=`
${s.map(({name:h,input:p,index:m})=>io(h,p,m)).join(`
`)}
${iD(n,o)}
${ef(i,e.type)}
${oo(e,s.length)}
${so(e)}
${v1(e.type,e.size)}
${oD(n.type,e.type,e.size,i.length)}

@compute @workgroup_size(${We}) fn main(
  @builtin(workgroup_id) workgroupId: vec3<u32>,
  @builtin(local_invocation_id) localId: vec3<u32>
) {
  let rowIndex = ${Zr(a,We)};
  if (rowIndex >= ${e.length}u) {
    return;
  }

  let idsValue = read_ids(rowIndex);
  let result = gather(idsValue);
  write_result(rowIndex, result);
}
`,l=new ot(t.device,{source:c,shaderLayout:{bindings:[...s.map(({name:h,index:p})=>({name:h,type:"storage",group:0,location:p})),{name:"result",type:"storage",group:0,location:s.length}]}}),u={};n.isConstant||(u.ids=n.buffer),i.isConstant||(u.sourceValues=i.buffer),u.result=t,l.setBindings(u);let f=t.device.beginComputePass({});return l.dispatch(f,a.x,a.y,a.z),f.end(),t.device.submit(),l.destroy(),{success:!0}}});function sD(r){return`fn segmented_map(vertexIndex: u32) -> array<u32, 2> {
  var low = 0i;
  var high = ${r}i;
  while (low < high) {
    let mid = low + (high - low) / 2i;
    let midStart = read_segments(u32(mid))[0];
    if (midStart <= vertexIndex) {
      low = mid + 1i;
    } else {
      high = mid;
    }
  }

  let segmentIndex = u32(max(low - 1i, 0i));
  let segmentStart = read_segments(segmentIndex)[0];
  return array<u32, 2>(segmentIndex, vertexIndex - segmentStart);
}`}var A1,C1=b(()=>{de();no();tf();A1=async({inputs:r,output:e,target:t})=>{let{segments:n}=r,i=n.isConstant?[]:[{name:"segments",input:n,index:0}],o=or(Math.ceil(e.length/We),t.device.limits.maxComputeWorkgroupsPerDimension),s=`
${i.map(({name:u,input:f,index:h})=>io(u,f,h)).join(`
`)}
${cg("segments",n,"uint32")}
${oo(e,i.length)}
${so(e)}
${sD(n.length)}

@compute @workgroup_size(${We}) fn main(
  @builtin(workgroup_id) workgroupId: vec3<u32>,
  @builtin(local_invocation_id) localId: vec3<u32>
) {
  let rowIndex = ${Zr(o,We)};
  if (rowIndex >= ${e.length}u) {
    return;
  }

  let result = segmented_map(rowIndex);
  write_result(rowIndex, result);
}
`,a=new ot(t.device,{source:s,shaderLayout:{bindings:[...i.map(({name:u,index:f})=>({name:u,type:"storage",group:0,location:f})),{name:"result",type:"storage",group:0,location:i.length}]}}),c=Object.fromEntries(i.map(({name:u,input:f})=>[u,f.buffer]));c.result=t,a.setBindings(c);let l=t.device.beginComputePass({});return a.dispatch(l,o.x,o.y,o.z),l.end(),t.device.submit(),a.destroy(),{success:!0}}});function aD(r,e){let n=e.filter(([,i])=>!i.isConstant).length+1;if(n>r.maxStorageBuffersPerShaderStage)throw new Error(`interleave() requires ${n} storage buffers, exceeding device limit ${r.maxStorageBuffersPerShaderStage}`);if(n>r.maxBindingsPerBindGroup)throw new Error(`interleave() requires ${n} bindings, exceeding bind group limit ${r.maxBindingsPerBindGroup}`)}var rf,M1=b(()=>{Sr();rf=({inputs:r,output:e,target:t})=>{let n=r.map((c,l)=>[`x${l}`,c]);aD(t.device.limits,n);let i=n.map(([c,l])=>`${c}: array<{TYPE}, ${l.size}>`).join(", "),o=0,s=n.map(([c,l])=>{let u=Array.from({length:l.size},(f,h)=>`  out[${o+h}] = ${c}[${h}];`).join(`
`);return o+=l.size,u}).join(`
`),a=`fn interleave(${i}) -> array<{TYPE}, {RESULT_LEN}> {
  var out: array<{TYPE}, {RESULT_LEN}>;
${s}
  return out;
}
`;return De({module:{name:"interleave",source:a},inputs:r,output:e,outputBuffer:t}),{success:!0}}});var cD,I1,R1=b(()=>{Sr();cD=`fn row_length(x: array<{TYPE}, {X_LEN}>) -> array<f32, 1> {
  var sum = 0.0;
  for (var i = 0u; i < {X_LEN}u; i = i + 1u) {
    sum += f32(x[i]) * f32(x[i]);
  }
  return array<f32, 1>(sqrt(sum));
}
`,I1=({inputs:r,output:e,target:t})=>(De({module:{name:"row_length",source:cD},inputs:r,output:e,operationType:"float32",outputBuffer:t}),{success:!0})});function lg(r,e,t,n){return t<e.size?`${r}[${t}]`:e.size===1?`${r}[0]`:n}var B1,O1=b(()=>{Sr();Zn();B1=async({inputs:r,output:e,target:t})=>{let n=Qr(e.type);return De({module:{name:"select",source:`// inline expression select
`},inputs:r,output:e,operationType:e.type,outputBuffer:t,expression:i=>{let o=lg("condition",r.condition,i,n),s=lg("whenTrue",r.whenTrue,i,n);return`select(${lg("whenFalse",r.whenFalse,i,n)}, ${s}, ${o} != ${n})`}}),{success:!0}}});var ug,k1,D1=b(()=>{de();no();ug=64,k1=({inputs:r,output:e,target:t})=>{let n=or(Math.ceil(e.length/ug),t.device.limits.maxComputeWorkgroupsPerDimension),i=`@group(0) @binding(0) var<storage, read_write> result: array<i32>;

@compute @workgroup_size(${ug}) fn main(
  @builtin(workgroup_id) workgroupId: vec3<u32>,
  @builtin(local_invocation_id) localId: vec3<u32>
) {
  let rowIndex = ${Zr(n,ug)};
  if (rowIndex >= ${e.length}u) {
    return;
  }

  let rowOffset = ${e.offset/e.ValueType.BYTES_PER_ELEMENT}u + rowIndex * ${e.stride/e.ValueType.BYTES_PER_ELEMENT}u;
  result[rowOffset] = ${r.start} + i32(rowIndex) * ${r.step};
}
`,o=new ot(t.device,{source:i,shaderLayout:{bindings:[{name:"result",type:"storage",group:0,location:0}]}});o.setBindings({result:t});let s=t.device.beginComputePass({});return o.dispatch(s,n.x,n.y,n.z),s.end(),t.device.submit(),o.destroy(),{success:!0}}});var N1,F1=b(()=>{Sr();N1=({inputs:r,output:e,target:t})=>{let{columns:n}=r;return De({module:{name:"swizzle",source:"// swizzle expression handled inline"},expression:i=>`x[${n[i]}]`,inputs:{x:r.x},output:e,outputBuffer:t}),{success:!0}}});var U1={};cr(U1,{arithmetic:()=>m1,dot:()=>y1,equalAll:()=>b1,extent:()=>w1,fround:()=>S1,gather:()=>T1,interleave:()=>rf,length:()=>I1,segmentedMap:()=>A1,select:()=>B1,sequence:()=>k1,swizzle:()=>N1});var fg=b(()=>{g1();_1();x1();E1();P1();L1();C1();M1();R1();O1();D1();F1()});var IS=oP((Eue,kg)=>{"use strict";kg.exports=Ef;kg.exports.default=Ef;function Ef(r,e,t){t=t||2;var n=e&&e.length,i=n?e[0]*t:r.length,o=AS(r,0,i,t,!0),s=[];if(!o||o.next===o.prev)return s;var a,c,l,u,f,h,p;if(n&&(o=FN(r,e,o,t)),r.length>80*t){a=l=r[0],c=u=r[1];for(var m=t;m<i;m+=t)f=r[m],h=r[m+1],f<a&&(a=f),h<c&&(c=h),f>l&&(l=f),h>u&&(u=h);p=Math.max(l-a,u-c),p=p!==0?32767/p:0}return Da(o,s,t,a,c,p,0),s}function AS(r,e,t,n,i){var o,s;if(i===Og(r,e,t,n)>0)for(o=e;o<t;o+=n)s=LS(o,r[o],r[o+1],s);else for(o=t-n;o>=e;o-=n)s=LS(o,r[o],r[o+1],s);return s&&Sf(s,s.next)&&(Fa(s),s=s.next),s}function Qn(r,e){if(!r)return r;e||(e=r);var t=r,n;do if(n=!1,!t.steiner&&(Sf(t,t.next)||se(t.prev,t,t.next)===0)){if(Fa(t),t=e=t.prev,t===t.next)break;n=!0}else t=t.next;while(n||t!==e);return e}function Da(r,e,t,n,i,o,s){if(r){!s&&o&&VN(r,n,i,o);for(var a=r,c,l;r.prev!==r.next;){if(c=r.prev,l=r.next,o?kN(r,n,i,o):ON(r)){e.push(c.i/t|0),e.push(r.i/t|0),e.push(l.i/t|0),Fa(r),r=l.next,a=l.next;continue}if(r=l,r===a){s?s===1?(r=DN(Qn(r),e,t),Da(r,e,t,n,i,o,2)):s===2&&NN(r,e,t,n,i,o):Da(Qn(r),e,t,n,i,o,1);break}}}}function ON(r){var e=r.prev,t=r,n=r.next;if(se(e,t,n)>=0)return!1;for(var i=e.x,o=t.x,s=n.x,a=e.y,c=t.y,l=n.y,u=i<o?i<s?i:s:o<s?o:s,f=a<c?a<l?a:l:c<l?c:l,h=i>o?i>s?i:s:o>s?o:s,p=a>c?a>l?a:l:c>l?c:l,m=n.next;m!==e;){if(m.x>=u&&m.x<=h&&m.y>=f&&m.y<=p&&fo(i,a,o,c,s,l,m.x,m.y)&&se(m.prev,m,m.next)>=0)return!1;m=m.next}return!0}function kN(r,e,t,n){var i=r.prev,o=r,s=r.next;if(se(i,o,s)>=0)return!1;for(var a=i.x,c=o.x,l=s.x,u=i.y,f=o.y,h=s.y,p=a<c?a<l?a:l:c<l?c:l,m=u<f?u<h?u:h:f<h?f:h,g=a>c?a>l?a:l:c>l?c:l,y=u>f?u>h?u:h:f>h?f:h,x=Rg(p,m,e,t,n),v=Rg(g,y,e,t,n),_=r.prevZ,w=r.nextZ;_&&_.z>=x&&w&&w.z<=v;){if(_.x>=p&&_.x<=g&&_.y>=m&&_.y<=y&&_!==i&&_!==s&&fo(a,u,c,f,l,h,_.x,_.y)&&se(_.prev,_,_.next)>=0||(_=_.prevZ,w.x>=p&&w.x<=g&&w.y>=m&&w.y<=y&&w!==i&&w!==s&&fo(a,u,c,f,l,h,w.x,w.y)&&se(w.prev,w,w.next)>=0))return!1;w=w.nextZ}for(;_&&_.z>=x;){if(_.x>=p&&_.x<=g&&_.y>=m&&_.y<=y&&_!==i&&_!==s&&fo(a,u,c,f,l,h,_.x,_.y)&&se(_.prev,_,_.next)>=0)return!1;_=_.prevZ}for(;w&&w.z<=v;){if(w.x>=p&&w.x<=g&&w.y>=m&&w.y<=y&&w!==i&&w!==s&&fo(a,u,c,f,l,h,w.x,w.y)&&se(w.prev,w,w.next)>=0)return!1;w=w.nextZ}return!0}function DN(r,e,t){var n=r;do{var i=n.prev,o=n.next.next;!Sf(i,o)&&CS(i,n,n.next,o)&&Na(i,o)&&Na(o,i)&&(e.push(i.i/t|0),e.push(n.i/t|0),e.push(o.i/t|0),Fa(n),Fa(n.next),n=r=o),n=n.next}while(n!==r);return Qn(n)}function NN(r,e,t,n,i,o){var s=r;do{for(var a=s.next.next;a!==s.prev;){if(s.i!==a.i&&HN(s,a)){var c=MS(s,a);s=Qn(s,s.next),c=Qn(c,c.next),Da(s,e,t,n,i,o,0),Da(c,e,t,n,i,o,0);return}a=a.next}s=s.next}while(s!==r)}function FN(r,e,t,n){var i=[],o,s,a,c,l;for(o=0,s=e.length;o<s;o++)a=e[o]*n,c=o<s-1?e[o+1]*n:r.length,l=AS(r,a,c,n,!1),l===l.next&&(l.steiner=!0),i.push(jN(l));for(i.sort(UN),o=0;o<i.length;o++)t=GN(i[o],t);return t}function UN(r,e){return r.x-e.x}function GN(r,e){var t=zN(r,e);if(!t)return e;var n=MS(t,r);return Qn(n,n.next),Qn(t,t.next)}function zN(r,e){var t=e,n=r.x,i=r.y,o=-1/0,s;do{if(i<=t.y&&i>=t.next.y&&t.next.y!==t.y){var a=t.x+(i-t.y)*(t.next.x-t.x)/(t.next.y-t.y);if(a<=n&&a>o&&(o=a,s=t.x<t.next.x?t:t.next,a===n))return s}t=t.next}while(t!==e);if(!s)return null;var c=s,l=s.x,u=s.y,f=1/0,h;t=s;do n>=t.x&&t.x>=l&&n!==t.x&&fo(i<u?n:o,i,l,u,i<u?o:n,i,t.x,t.y)&&(h=Math.abs(i-t.y)/(n-t.x),Na(t,r)&&(h<f||h===f&&(t.x>s.x||t.x===s.x&&$N(s,t)))&&(s=t,f=h)),t=t.next;while(t!==c);return s}function $N(r,e){return se(r.prev,r,e.prev)<0&&se(e.next,r,r.next)<0}function VN(r,e,t,n){var i=r;do i.z===0&&(i.z=Rg(i.x,i.y,e,t,n)),i.prevZ=i.prev,i.nextZ=i.next,i=i.next;while(i!==r);i.prevZ.nextZ=null,i.prevZ=null,WN(i)}function WN(r){var e,t,n,i,o,s,a,c,l=1;do{for(t=r,r=null,o=null,s=0;t;){for(s++,n=t,a=0,e=0;e<l&&(a++,n=n.nextZ,!!n);e++);for(c=l;a>0||c>0&&n;)a!==0&&(c===0||!n||t.z<=n.z)?(i=t,t=t.nextZ,a--):(i=n,n=n.nextZ,c--),o?o.nextZ=i:r=i,i.prevZ=o,o=i;t=n}o.nextZ=null,l*=2}while(s>1);return r}function Rg(r,e,t,n,i){return r=(r-t)*i|0,e=(e-n)*i|0,r=(r|r<<8)&16711935,r=(r|r<<4)&252645135,r=(r|r<<2)&858993459,r=(r|r<<1)&1431655765,e=(e|e<<8)&16711935,e=(e|e<<4)&252645135,e=(e|e<<2)&858993459,e=(e|e<<1)&1431655765,r|e<<1}function jN(r){var e=r,t=r;do(e.x<t.x||e.x===t.x&&e.y<t.y)&&(t=e),e=e.next;while(e!==r);return t}function fo(r,e,t,n,i,o,s,a){return(i-s)*(e-a)>=(r-s)*(o-a)&&(r-s)*(n-a)>=(t-s)*(e-a)&&(t-s)*(o-a)>=(i-s)*(n-a)}function HN(r,e){return r.next.i!==e.i&&r.prev.i!==e.i&&!YN(r,e)&&(Na(r,e)&&Na(e,r)&&qN(r,e)&&(se(r.prev,r,e.prev)||se(r,e.prev,e))||Sf(r,e)&&se(r.prev,r,r.next)>0&&se(e.prev,e,e.next)>0)}function se(r,e,t){return(e.y-r.y)*(t.x-e.x)-(e.x-r.x)*(t.y-e.y)}function Sf(r,e){return r.x===e.x&&r.y===e.y}function CS(r,e,t,n){var i=wf(se(r,e,t)),o=wf(se(r,e,n)),s=wf(se(t,n,r)),a=wf(se(t,n,e));return!!(i!==o&&s!==a||i===0&&vf(r,t,e)||o===0&&vf(r,n,e)||s===0&&vf(t,r,n)||a===0&&vf(t,e,n))}function vf(r,e,t){return e.x<=Math.max(r.x,t.x)&&e.x>=Math.min(r.x,t.x)&&e.y<=Math.max(r.y,t.y)&&e.y>=Math.min(r.y,t.y)}function wf(r){return r>0?1:r<0?-1:0}function YN(r,e){var t=r;do{if(t.i!==r.i&&t.next.i!==r.i&&t.i!==e.i&&t.next.i!==e.i&&CS(t,t.next,r,e))return!0;t=t.next}while(t!==r);return!1}function Na(r,e){return se(r.prev,r,r.next)<0?se(r,e,r.next)>=0&&se(r,r.prev,e)>=0:se(r,e,r.prev)<0||se(r,r.next,e)<0}function qN(r,e){var t=r,n=!1,i=(r.x+e.x)/2,o=(r.y+e.y)/2;do t.y>o!=t.next.y>o&&t.next.y!==t.y&&i<(t.next.x-t.x)*(o-t.y)/(t.next.y-t.y)+t.x&&(n=!n),t=t.next;while(t!==r);return n}function MS(r,e){var t=new Bg(r.i,r.x,r.y),n=new Bg(e.i,e.x,e.y),i=r.next,o=e.prev;return r.next=e,e.prev=r,t.next=i,i.prev=t,n.next=t,t.prev=n,o.next=n,n.prev=o,n}function LS(r,e,t,n){var i=new Bg(r,e,t);return n?(i.next=n.next,i.prev=n,n.next.prev=i,n.next=i):(i.prev=i,i.next=i),i}function Fa(r){r.next.prev=r.prev,r.prev.next=r.next,r.prevZ&&(r.prevZ.nextZ=r.nextZ),r.nextZ&&(r.nextZ.prevZ=r.prevZ)}function Bg(r,e,t){this.i=r,this.x=e,this.y=t,this.prev=null,this.next=null,this.z=0,this.prevZ=null,this.nextZ=null,this.steiner=!1}Ef.deviation=function(r,e,t,n){var i=e&&e.length,o=i?e[0]*t:r.length,s=Math.abs(Og(r,0,o,t));if(i)for(var a=0,c=e.length;a<c;a++){var l=e[a]*t,u=a<c-1?e[a+1]*t:r.length;s-=Math.abs(Og(r,l,u,t))}var f=0;for(a=0;a<n.length;a+=3){var h=n[a]*t,p=n[a+1]*t,m=n[a+2]*t;f+=Math.abs((r[h]-r[m])*(r[p+1]-r[h+1])-(r[h]-r[p])*(r[m+1]-r[h+1]))}return s===0&&f===0?0:Math.abs((f-s)/s)};function Og(r,e,t,n){for(var i=0,o=e,s=t-n;o<t;o+=n)i+=(r[s]-r[o])*(r[o+1]+r[s+1]),s=o;return i}Ef.flatten=function(r){for(var e=r[0][0].length,t={vertices:[],holes:[],dimensions:e},n=0,i=0;i<r.length;i++){for(var o=0;o<r[i].length;o++)for(var s=0;s<e;s++)t.vertices.push(r[i][o][s]);i>0&&(n+=r[i-1].length,t.holes.push(n))}return t}});var vt=window.__HERMES_PLUGIN_SDK__,w6=window.__HERMES_PLUGINS__,Wg=vt&&vt.React,P=Wg&&Wg.createElement,ja=vt&&vt.hooks||{},jg=vt&&vt.components||{},lr=vt&&vt.fetchJSON,He="/api/plugins/chronicle",E6=vt&&vt.utils&&vt.utils.cn||function(){return Array.prototype.filter.call(arguments,Boolean).join(" ")};function re(r){return Number(r||0).toLocaleString()}function If(r){if(!r)return"never";let e=typeof r=="number"?r*1e3:new Date(r).getTime();if(!isFinite(e))return String(r);let t=Math.floor((Date.now()-e)/6e4);if(t<1)return"just now";if(t<60)return t+"m ago";let n=Math.floor(t/60);return n<24?n+"h ago":Math.floor(n/24)+"d ago"}function Ye(r){if(r==null||r==="")return"";let e=typeof r=="number"?new Date(r*1e3):new Date(r);return isFinite(e.getTime())?e.toLocaleString([],{month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"}):String(r)}function Hg(){if(document.getElementById("chr-css"))return;let r=document.createElement("style");r.id="chr-css",r.textContent=[".chr{--panel:rgba(255,255,255,.025);--panel2:rgba(255,255,255,.05);--bd:rgba(150,130,230,.18);--bd2:rgba(150,130,230,.30);--title:#cdc6f5;--tx:#e7e5f1;--muted:#9b97b8;--accent:#a78bfa;--ok:#4fd6a6;--warn:#f0b54e;--danger:#f0706e;--info:#6aa6f2;--mono:ui-monospace,'SF Mono',Menlo,Consolas,monospace;--color-background:#0a0a14;--color-foreground:#e7e5f1;--color-card:#0e0e1a;--color-card-foreground:#e7e5f1;--color-popover:#12121f;--color-popover-foreground:#e7e5f1;--color-border:rgba(150,130,230,.18);--color-input:rgba(150,130,230,.22);--color-muted:#15151f;--color-muted-foreground:#9b97b8;--color-primary:#a78bfa;--color-primary-foreground:#0a0a14;--color-secondary:#17151f;--color-secondary-foreground:#cdc6f5;--color-accent:#1c1830;--color-accent-foreground:#cdc6f5;--color-destructive:#f0706e;--color-destructive-foreground:#0a0a14;--color-ring:#a78bfa;display:flex;flex-direction:column;gap:1rem;color:var(--tx)}",".chr .text-muted-foreground{color:var(--muted)}",".chr-tabs{display:flex;gap:.25rem;border-bottom:1px solid var(--bd);padding:0 .25rem}",".chr-tab{background:none;border:0;border-bottom:2px solid transparent;color:var(--muted);padding:.45rem .75rem;font-size:.85rem;cursor:pointer}",".chr-tab[aria-selected=true]{color:var(--tx);border-bottom-color:var(--accent)}",".chr-kpis{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:.75rem}",".chr-kpi{border:1px solid var(--bd);border-radius:.6rem;background:var(--panel);padding:.7rem .85rem}",".chr-kpi-l{font-size:.72rem;color:var(--muted)}",".chr-kpi-v{font-size:1.35rem;font-weight:300;font-variant-numeric:tabular-nums}",".chr-kpi-u{font-size:.8rem;color:var(--muted);margin-left:.15rem}",".chr-grid{display:grid;grid-template-columns:1fr 1fr;gap:1rem}",".chr-comp{display:flex;align-items:center;gap:1.25rem}",".chr-donut{width:7rem;height:7rem;border-radius:9999px;background:var(--g);display:grid;place-items:center;flex:0 0 auto}",".chr-donut .ctr{width:4.8rem;height:4.8rem;border-radius:9999px;background:var(--color-card);display:flex;flex-direction:column;align-items:center;justify-content:center}",".chr-legend{flex:1 1 auto;min-width:0}",".chr-leg-row{display:flex;align-items:center;gap:.6rem;font-size:.8rem;padding:.18rem 0}",".chr-sw{width:.6rem;height:.6rem;border-radius:2px;flex:0 0 auto}",".chr-leg-name{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",".chr-leg-ct,.chr-num{font-variant-numeric:tabular-nums}",".chr-leg-pct{color:var(--muted);font-variant-numeric:tabular-nums;width:3.2em;text-align:right}",".chr-cov{display:flex;align-items:center;gap:.6rem;font-size:.8rem;padding:.18rem 0}",".chr-cov-l{flex:0 0 5.5rem}",".chr-track{flex:1 1 auto;height:6px;border-radius:9999px;background:var(--bd);overflow:hidden}",".chr-fill{display:block;height:100%;border-radius:9999px}",".chr-cov-v{flex:0 0 auto;width:3.2em;text-align:right;font-variant-numeric:tabular-nums;color:var(--muted)}",".chr-act{display:flex;align-items:center;gap:.5rem;font-size:.78rem;padding:.18rem 0}",".chr-mark{width:.5rem;height:.5rem;border-radius:9999px;flex:0 0 auto}",".chr-act-sum{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",".chr-act-time{flex:0 0 auto;white-space:nowrap;font-size:.72rem;color:var(--muted)}",".chr-err{padding:1rem;font-size:.85rem;color:var(--danger)}",".chr-quiet{font-size:.8rem;color:var(--muted)}","@media(max-width:900px){.chr-grid{grid-template-columns:1fr}.chr-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}}"].join(""),document.head.appendChild(r)}var cP={observed:{label:"Turn",color:[106,166,242]},asserted:{label:"Belief written",color:[240,181,78]},signal:{label:"Signal",color:[167,139,250]},folded:{label:"Folded",color:[79,214,166]},compressed:{label:"Compressed",color:[63,184,160]},checkpoint_digest:{label:"Checkpoint",color:[143,211,196]},decayed:{label:"Decayed",color:[124,122,147]},retracted:{label:"Retracted",color:[240,112,110]},corrected:{label:"Corrected",color:[255,154,118]},contradicted:{label:"Contradicted",color:[240,112,110]},confirmed:{label:"Confirmed",color:[155,212,122]},derived:{label:"Derived",color:[224,192,112]}},lP={label:"Other",color:[155,151,184]};function Qe(r){return cP[r]||{...lP,label:r}}var uP=/^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})/;function nn(r,e){let t=r.indexOf(":"),n=r.slice(0,t),i=r.slice(t+1);if(n==="cron")return e&&e[i]||"Cron job "+i.slice(0,8);if(n==="background")return i.charAt(0).toUpperCase()+i.slice(1)+" (no session)";let o=uP.exec(i);return o?"Session "+new Date(Date.UTC(+o[1],+o[2]-1,+o[3],+o[4],+o[5],+o[6])).toLocaleString([],{month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"}):"Session "+i.slice(0,18)}var Ha=class{constructor(){this.n=0,this.cap=0,this.seq=new Int32Array(0),this.t=new Int32Array(0),this.type=new Uint8Array(0),this.lane=new Int32Array(0),this.session=new Int32Array(0),this.types=[],this.typeIx=new Map,this.lanes=[],this.laneIx=new Map,this.sessions=[],this.sessionIx=new Map,this.lastSeq=0,this.t0=null,this.version=0,this.rowOfLane=new Int32Array(0),this.positions=new Float32Array(0),this.colors=new Uint8Array(0)}_grow(e){let t=this.n+e;if(t<=this.cap)return;let n=Math.max(1024,this.cap);for(;n<t;)n*=2;let i=(o,s,a=1)=>{let c=new o(n*a);return c.set(s.subarray(0,this.n*a)),c};this.seq=i(Int32Array,this.seq),this.t=i(Int32Array,this.t),this.type=i(Uint8Array,this.type),this.lane=i(Int32Array,this.lane),this.session=i(Int32Array,this.session),this.positions=i(Float32Array,this.positions,2),this.colors=i(Uint8Array,this.colors,4),this.cap=n}append(e){if(!e||!e.n)return 0;this._grow(e.n);let t=e.types.map(s=>(this.typeIx.has(s)||(this.typeIx.set(s,this.types.length),this.types.push(s)),this.typeIx.get(s))),n=e.writers.map(([s,a])=>{this.laneIx.has(a)||(this.laneIx.set(a,this.lanes.length),this.lanes.push({key:a,count:0,first:null,last:null,sessions:new Set}));let c=this.laneIx.get(a),l=-1;return s&&(this.sessionIx.has(s)||(this.sessionIx.set(s,this.sessions.length),this.sessions.push({id:s,lane:c,count:0,first:null,last:null})),l=this.sessionIx.get(s)),[c,l]}),i=e.seq0,o=e.t0;this.t0===null&&(this.t0=e.t0);for(let s=0;s<e.n;s++){i+=e.dseq[s],o+=e.dt[s];let a=this.n+s,[c,l]=n[e.writer[s]];this.seq[a]=i,this.t[a]=o,this.type[a]=t[e.type[s]],this.lane[a]=c,this.session[a]=l;let u=this.lanes[c];if(u.count++,u.first===null&&(u.first=o),u.last=o,l>=0){let f=this.sessions[l];f.count++,f.first===null&&(f.first=o),f.last=o,u.sessions.add(l)}}return this.n+=e.n,this.lastSeq=i,this.version++,e.n}orderLanes(e){let t=new Int32Array(this.lanes.length).fill(-1);if(e&&this.rowOfLane.length){t.set(this.rowOfLane.subarray(0,Math.min(this.rowOfLane.length,t.length)));let n=this.rowOfLane.length?Math.max(...this.rowOfLane)+1:0;for(let i=0;i<t.length;i++)t[i]<0&&(t[i]=n++)}else this.lanes.map((n,i)=>i).sort((n,i)=>this.lanes[i].count-this.lanes[n].count).forEach((n,i)=>{t[n]=i});this.rowOfLane=t,this.laneAtRow=new Int32Array(t.length),t.forEach((n,i)=>{this.laneAtRow[n]=i}),e||this.fillGeometry(0)}fillGeometry(e){let t=this.types.map(n=>Qe(n).color);for(let n=e;n<this.n;n++){this.positions[2*n]=(this.t[n]-this.t0)/3600,this.positions[2*n+1]=this.rowOfLane[this.lane[n]]+.5;let i=t[this.type[n]];this.colors[4*n]=i[0],this.colors[4*n+1]=i[1],this.colors[4*n+2]=i[2],this.colors[4*n+3]=200}this.version++}xOf(e){return(e-this.t0)/3600}epochOf(e){return this.t0+e*3600}extentX(){return this.n?[0,(this.t[this.n-1]-this.t0)/3600]:[0,1]}bin(e,t,n){let i=this.types.length,o=new Uint32Array(n*i),s=(t-e)/n;if(s<=0)return{counts:o,nt:i,width:s,max:0};for(let c=0;c<this.n;c++){let l=this.positions[2*c];l<e||l>=t||o[Math.floor((l-e)/s)*i+this.type[c]]++}let a=0;for(let c=0;c<n;c++){let l=0;for(let u=0;u<i;u++)l+=o[c*i+u];l>a&&(a=l)}return{counts:o,nt:i,width:s,max:a}}indexOfSeq(e){let t=0,n=this.n-1;for(;t<=n;){let i=t+n>>1;if(this.seq[i]===e)return i;this.seq[i]<e?t=i+1:n=i-1}return-1}indicesWhere(e,t=2e5){let n=[];for(let i=0;i<this.n&&n.length<t;i++)e(i)&&n.push(i);return n}};async function Yg(r,e,t,n){let i=r.lastSeq;for(;;){if(n&&n.aborted)return;let o=await lr(He+"/atlas/events?after_seq="+i+"&limit=50000");if(o.error)throw new Error(o.error);if(r.append(o),i=o.next_after_seq,t(r.n,e),o.done)return}}async function qg(r){let e=r.n,t=await lr(He+"/atlas/events?after_seq="+r.lastSeq+"&limit=50000");return t.error||!t.n?0:(r.append(t),r.orderLanes(!0),r.fillGeometry(e),t.n)}function Ya(r,e){if(!r)throw new Error(e||"loader assertion failed.")}var kt={self:typeof self<"u"&&self,window:typeof window<"u"&&window,global:typeof global<"u"&&global,document:typeof document<"u"&&document},fP=kt.self||kt.window||kt.global||{},dP=kt.window||kt.self||kt.global||{},hP=kt.global||kt.self||kt.window||{},pP=kt.document||{};var _o=!!(typeof process!="object"||String(process)!=="[object process]"||process.browser);var Xg=typeof process<"u"&&process.version&&/v([0-9]*)/.exec(process.version),mP=Xg&&parseFloat(Xg[1])||0;xo();var $f="4.4.5",EP=$f[0]>="0"&&$f[0]<="9"?`v${$f}`:"";function SP(){let r=new Fe({id:"loaders.gl"});return globalThis.loaders||(globalThis.loaders={}),globalThis.loaders.log=r,globalThis.loaders.version=EP,globalThis.probe||(globalThis.probe={}),globalThis.probe.loaders=r,r}var Vf=SP();var PP=r=>typeof r=="boolean",Nt=r=>typeof r=="function",Ft=r=>r!==null&&typeof r=="object",ec=r=>Ft(r)&&r.constructor==={}.constructor;var Wf=r=>typeof SharedArrayBuffer<"u"&&r instanceof SharedArrayBuffer,ni=r=>Ft(r)&&typeof r.byteLength=="number"&&typeof r.slice=="function";var jf=r=>!!r&&Nt(r[Symbol.iterator]),Hf=r=>!!r&&Nt(r[Symbol.asyncIterator]);var et=r=>typeof Response<"u"&&r instanceof Response||Ft(r)&&Nt(r.arrayBuffer)&&Nt(r.text)&&Nt(r.json);var tt=r=>typeof Blob<"u"&&r instanceof Blob;var fy=r=>typeof ReadableStream<"u"&&r instanceof ReadableStream||Ft(r)&&Nt(r.tee)&&Nt(r.cancel)&&Nt(r.getReader);var dy=r=>Ft(r)&&Nt(r.read)&&Nt(r.pipe)&&PP(r.readable),vo=r=>fy(r)||dy(r);function Yf(r,e){return hy(r||{},e)}function hy(r,e,t=0){if(t>3)return e;let n={...r};for(let[i,o]of Object.entries(e))o&&typeof o=="object"&&!Array.isArray(o)?n[i]=hy(n[i]||{},e[i],t+1):n[i]=e[i];return n}var py="latest";function TP(){return globalThis._loadersgl_?.version||(globalThis._loadersgl_=globalThis._loadersgl_||{},globalThis._loadersgl_.version="4.4.5"),globalThis._loadersgl_.version}var my=TP();function Ue(r,e){if(!r)throw new Error(e||"loaders.gl assertion failed.")}var Ut={self:typeof self<"u"&&self,window:typeof window<"u"&&window,global:typeof global<"u"&&global,document:typeof document<"u"&&document},wF=Ut.self||Ut.window||Ut.global||{},EF=Ut.window||Ut.self||Ut.global||{},SF=Ut.global||Ut.self||Ut.window||{},PF=Ut.document||{};var ct=typeof process!="object"||String(process)!=="[object process]"||process.browser;var yy=typeof window<"u"&&typeof window.orientation<"u",gy=typeof process<"u"&&process.version&&/v([0-9]*)/.exec(process.version),TF=gy&&parseFloat(gy[1])||0;var wo=class{constructor(e,t){d(this,"name");d(this,"workerThread");d(this,"isRunning",!0);d(this,"result");d(this,"_resolve",()=>{});d(this,"_reject",()=>{});this.name=e,this.workerThread=t,this.result=new Promise((n,i)=>{this._resolve=n,this._reject=i})}postMessage(e,t){this.workerThread.postMessage({source:"loaders.gl",type:e,payload:t})}done(e){Ue(this.isRunning),this.isRunning=!1,this._resolve(e)}error(e){Ue(this.isRunning),this.isRunning=!1,this._reject(e)}};var ii=class{terminate(){}};var qf=new Map;function _y(r){Ue(r.source&&!r.url||!r.source&&r.url);let e=qf.get(r.source||r.url);return e||(r.url&&(e=LP(r.url),qf.set(r.url,e)),r.source&&(e=by(r.source),qf.set(r.source,e))),Ue(e),e}function LP(r){if(!r.startsWith("http"))return r;let e=AP(r);return by(e)}function by(r){let e=new Blob([r],{type:"application/javascript"});return URL.createObjectURL(e)}function AP(r){return`try {
  importScripts('${r}');
} catch (error) {
  console.error(error);
  throw error;
}`}function Xf(r,e=!0,t){let n=t||new Set;if(r){if(xy(r))n.add(r);else if(xy(r.buffer))n.add(r.buffer);else if(!ArrayBuffer.isView(r)){if(e&&typeof r=="object")for(let i in r)Xf(r[i],e,n)}}return t===void 0?Array.from(n):[]}function xy(r){return r?r instanceof ArrayBuffer||typeof MessagePort<"u"&&r instanceof MessagePort||typeof ImageBitmap<"u"&&r instanceof ImageBitmap||typeof OffscreenCanvas<"u"&&r instanceof OffscreenCanvas:!1}var Zf=()=>{},Lr=class{constructor(e){d(this,"name");d(this,"source");d(this,"url");d(this,"terminated",!1);d(this,"worker");d(this,"onMessage");d(this,"onError");d(this,"_loadableURL","");let{name:t,source:n,url:i}=e;Ue(n||i),this.name=t,this.source=n,this.url=i,this.onMessage=Zf,this.onError=o=>console.log(o),this.worker=ct?this._createBrowserWorker():this._createNodeWorker()}static isSupported(){return typeof Worker<"u"&&ct||typeof ii<"u"&&!ct}destroy(){this.onMessage=Zf,this.onError=Zf,this.worker.terminate(),this.terminated=!0}get isRunning(){return!!this.onMessage}postMessage(e,t){t=t||Xf(e),this.worker.postMessage(e,t)}_getErrorFromErrorEvent(e){let t="Failed to load ";return t+=`worker ${this.name} from ${this.url}. `,e.message&&(t+=`${e.message} in `),e.lineno&&(t+=`:${e.lineno}:${e.colno}`),new Error(t)}_createBrowserWorker(){this._loadableURL=_y({source:this.source,url:this.url});let e=new Worker(this._loadableURL,{name:this.name});return e.onmessage=t=>{t.data?this.onMessage(t.data):this.onError(new Error("No data received"))},e.onerror=t=>{this.onError(this._getErrorFromErrorEvent(t)),this.terminated=!0},e.onmessageerror=t=>console.error(t),e}_createNodeWorker(){let e;if(this.url){let n=this.url.includes(":/")||this.url.startsWith("/")?this.url:`./${this.url}`,i=this.url.endsWith(".ts")||this.url.endsWith(".mjs")?"module":"commonjs";e=new ii(n,{eval:!1,type:i})}else if(this.source)e=new ii(this.source,{eval:!0});else throw new Error("no worker");return e.on("message",t=>{this.onMessage(t)}),e.on("error",t=>{this.onError(t)}),e.on("exit",t=>{}),e}};var Eo=class{constructor(e){d(this,"name","unnamed");d(this,"source");d(this,"url");d(this,"maxConcurrency",1);d(this,"maxMobileConcurrency",1);d(this,"onDebug",()=>{});d(this,"reuseWorkers",!0);d(this,"props",{});d(this,"jobQueue",[]);d(this,"idleQueue",[]);d(this,"count",0);d(this,"isDestroyed",!1);this.source=e.source,this.url=e.url,this.setProps(e)}static isSupported(){return Lr.isSupported()}destroy(){this.idleQueue.forEach(e=>e.destroy()),this.isDestroyed=!0}setProps(e){this.props={...this.props,...e},e.name!==void 0&&(this.name=e.name),e.maxConcurrency!==void 0&&(this.maxConcurrency=e.maxConcurrency),e.maxMobileConcurrency!==void 0&&(this.maxMobileConcurrency=e.maxMobileConcurrency),e.reuseWorkers!==void 0&&(this.reuseWorkers=e.reuseWorkers),e.onDebug!==void 0&&(this.onDebug=e.onDebug)}async startJob(e,t=(i,o,s)=>i.done(s),n=(i,o)=>i.error(o)){let i=new Promise(o=>(this.jobQueue.push({name:e,onMessage:t,onError:n,onStart:o}),this));return this._startQueuedJob(),await i}async _startQueuedJob(){if(!this.jobQueue.length)return;let e=this._getAvailableWorker();if(!e)return;let t=this.jobQueue.shift();if(t){this.onDebug({message:"Starting job",name:t.name,workerThread:e,backlog:this.jobQueue.length});let n=new wo(t.name,e);e.onMessage=i=>t.onMessage(n,i.type,i.payload),e.onError=i=>t.onError(n,i),t.onStart(n);try{await n.result}catch(i){console.error(`Worker exception: ${i}`)}finally{this.returnWorkerToQueue(e)}}}returnWorkerToQueue(e){!ct||this.isDestroyed||!this.reuseWorkers||this.count>this._getMaxConcurrency()?(e.destroy(),this.count--):this.idleQueue.push(e),this.isDestroyed||this._startQueuedJob()}_getAvailableWorker(){if(this.idleQueue.length>0)return this.idleQueue.shift()||null;if(this.count<this._getMaxConcurrency()){this.count++;let e=`${this.name.toLowerCase()} (#${this.count} of ${this.maxConcurrency})`;return new Lr({name:e,source:this.source,url:this.url})}return null}_getMaxConcurrency(){return yy?this.maxMobileConcurrency:this.maxConcurrency}};var CP={maxConcurrency:3,maxMobileConcurrency:1,reuseWorkers:!0,onDebug:()=>{}},Ar=class Ar{constructor(e){d(this,"props");d(this,"workerPools",new Map);this.props={...CP},this.setProps(e),this.workerPools=new Map}static isSupported(){return Lr.isSupported()}static getWorkerFarm(e={}){return Ar._workerFarm=Ar._workerFarm||new Ar({}),Ar._workerFarm.setProps(e),Ar._workerFarm}destroy(){for(let e of this.workerPools.values())e.destroy();this.workerPools=new Map}setProps(e){this.props={...this.props,...e};for(let t of this.workerPools.values())t.setProps(this._getWorkerPoolProps())}getWorkerPool(e){let{name:t,source:n,url:i}=e,o=this.workerPools.get(t);return o||(o=new Eo({name:t,source:n,url:i}),o.setProps(this._getWorkerPoolProps()),this.workerPools.set(t,o)),o}_getWorkerPoolProps(){return{maxConcurrency:this.props.maxConcurrency,maxMobileConcurrency:this.props.maxMobileConcurrency,reuseWorkers:this.props.reuseWorkers,onDebug:this.props.onDebug}}};d(Ar,"_workerFarm");var an=Ar;function Kf(r,e={}){let t=e[r.id]||{},n=ct?`${r.id}-worker.js`:`${r.id}-worker-node.js`,i=t.workerUrl;if(!i&&r.id==="compression"&&(i=e.workerUrl),(e._workerType||e?.core?._workerType)==="test"&&(ct?i=`modules/${r.module}/dist/${n}`:i=`modules/${r.module}/src/workers/${r.id}-worker-node.ts`),!i){let s=r.version;s==="latest"&&(s=py);let a=s?`@${s}`:"";i=`https://unpkg.com/@loaders.gl/${r.module}${a}/dist/${n}`}return Ue(i),i}function Qf(r,e=my){Ue(r,"no worker provided");let t=r.version;return!(!e||!t)}function Jf(r,e){if(!an.isSupported())return!1;let t=e?._nodeWorkers??e?.core?._nodeWorkers;if(!ct&&!t)return!1;let n=e?.worker??e?.core?.worker;return!!(r.worker&&n)}async function ed(r,e,t,n,i){let o=r.id,s=Kf(r,t),c=an.getWorkerFarm(t?.core).getWorkerPool({name:o,url:s});t=JSON.parse(JSON.stringify(t)),n=JSON.parse(JSON.stringify(n||{}));let l=await c.startJob("process-on-worker",MP.bind(null,i));return l.postMessage("process",{input:e,options:t,context:n}),await(await l.result).result}async function MP(r,e,t,n){switch(t){case"done":e.done(n);break;case"error":e.error(new Error(n.error));break;case"process":let{id:i,input:o,options:s}=n;try{let a=await r(o,s);e.postMessage("done",{id:i,result:a})}catch(a){let c=a instanceof Error?a.message:"unknown error";e.postMessage("error",{id:i,error:c})}break;default:console.warn(`parse-with-worker unknown message ${t}`)}}function td(r,e,t){if(t=t||r.byteLength,r.byteLength<t||e.byteLength<t)return!1;let n=new Uint8Array(r),i=new Uint8Array(e);for(let o=0;o<n.length;++o)if(n[o]!==i[o])return!1;return!0}function rd(...r){return vy(r)}function vy(r){let e=r.map(o=>o instanceof ArrayBuffer?new Uint8Array(o):o),t=e.reduce((o,s)=>o+s.byteLength,0),n=new Uint8Array(t),i=0;for(let o of e)n.set(o,i),i+=o.byteLength;return n.buffer}async function nd(r){let e=[];for await(let t of r)e.push(IP(t));return rd(...e)}function IP(r){if(r instanceof ArrayBuffer)return r;if(ArrayBuffer.isView(r)){let{buffer:e,byteOffset:t,byteLength:n}=r;return wy(e,t,n)}return wy(r)}function wy(r,e=0,t=r.byteLength-e){let n=new Uint8Array(r,e,t),i=new Uint8Array(n.length);return i.set(n),i.buffer}var RP="",Sy={};function sd(r){for(let e in Sy)if(r.startsWith(e)){let t=Sy[e];r=r.replace(e,t)}return!r.startsWith("http://")&&!r.startsWith("https://")&&(r=`${RP}${r}`),r}function rc(r){return r&&typeof r=="object"&&r.isBuffer}function oi(r){if(rc(r))return r;if(r instanceof ArrayBuffer)return r;if(Wf(r))return tc(r);if(ArrayBuffer.isView(r)){let e=r.buffer;return r.byteOffset===0&&r.byteLength===r.buffer.byteLength?e:e.slice(r.byteOffset,r.byteOffset+r.byteLength)}if(typeof r=="string"){let e=r;return new TextEncoder().encode(e).buffer}if(r&&typeof r=="object"&&r._toArrayBuffer)return r._toArrayBuffer();throw new Error("toArrayBuffer")}function To(r){if(r instanceof ArrayBuffer)return r;if(Wf(r))return tc(r);let{buffer:e,byteOffset:t,byteLength:n}=r;return e instanceof ArrayBuffer&&t===0&&n===e.byteLength?e:tc(e,t,n)}function tc(r,e=0,t=r.byteLength-e){let n=new Uint8Array(r,e,t),i=new Uint8Array(n.length);return i.set(n),i.buffer}function ad(r){return ArrayBuffer.isView(r)?r:new Uint8Array(r)}var ur={};cr(ur,{dirname:()=>OP,filename:()=>BP,join:()=>kP,resolve:()=>DP});function Py(){if(typeof process<"u"&&typeof process.cwd<"u")return process.cwd();let r=window.location?.pathname;return r?.slice(0,r.lastIndexOf("/")+1)||""}function BP(r){let e=r?r.lastIndexOf("/"):-1;return e>=0?r.substr(e+1):r}function OP(r){let e=r?r.lastIndexOf("/"):-1;return e>=0?r.substr(0,e):""}function kP(...r){return r=r.map((t,n)=>(n&&(t=t.replace(new RegExp("^/"),"")),n!==r.length-1&&(t=t.replace(new RegExp("/$"),"")),t)),r.join("/")}function DP(...r){let e=[];for(let o=0;o<r.length;o++)e[o]=r[o];let t="",n=!1,i;for(let o=e.length-1;o>=-1&&!n;o--){let s;o>=0?s=e[o]:(i===void 0&&(i=Py()),s=i),s.length!==0&&(t=`${s}/${t}`,n=s.charCodeAt(0)===Lo)}return t=NP(t,!n),n?`/${t}`:t.length>0?t:"."}var Lo=47,cd=46;function NP(r,e){let t="",n=-1,i=0,o,s=!1;for(let a=0;a<=r.length;++a){if(a<r.length)o=r.charCodeAt(a);else{if(o===Lo)break;o=Lo}if(o===Lo){if(!(n===a-1||i===1))if(n!==a-1&&i===2){if(t.length<2||!s||t.charCodeAt(t.length-1)!==cd||t.charCodeAt(t.length-2)!==cd){if(t.length>2){let c=t.length-1,l=c;for(;l>=0&&t.charCodeAt(l)!==Lo;--l);if(l!==c){t=l===-1?"":t.slice(0,l),n=a,i=0,s=!1;continue}}else if(t.length===2||t.length===1){t="",n=a,i=0,s=!1;continue}}e&&(t.length>0?t+="/..":t="..",s=!0)}else{let c=r.slice(n+1,a);t.length>0?t+=`/${c}`:t=c,s=!1}n=a,i=0}else o===cd&&i!==-1?++i:i=-1}return t}var nc=class extends Error{constructor(t,n){super(t);d(this,"reason");d(this,"url");d(this,"response");this.reason=n.reason,this.url=n.url,this.response=n.response}};var GP=/^data:([-\w.]+\/[-\w.+]+)(;|,)/,zP=/^([-\w.]+\/[-\w.+]+)/;function ld(r,e){return r.toLowerCase()===e.toLowerCase()}function Ty(r){let e=zP.exec(r);return e?e[1]:r}function ud(r){let e=GP.exec(r);return e?e[1]:""}var Ly=/\?.*/;function Ay(r){let e=r.match(Ly);return e&&e[0]}function Cr(r){return r.replace(Ly,"")}function Cy(r){if(r.length<50)return r;let e=r.slice(r.length-15);return`${r.substr(0,32)}...${e}`}function ln(r){return et(r)?r.url:tt(r)?("name"in r?r.name:"")||"":typeof r=="string"?r:""}function si(r){if(et(r)){let e=r.headers.get("content-type")||"",t=Cr(r.url);return Ty(e)||ud(t)}return tt(r)?r.type||"":typeof r=="string"?ud(r):""}function My(r){return et(r)?r.headers["content-length"]||-1:tt(r)?r.size:typeof r=="string"?r.length:r instanceof ArrayBuffer||ArrayBuffer.isView(r)?r.byteLength:-1}async function ic(r){if(et(r))return r;let e={},t=My(r);t>=0&&(e["content-length"]=String(t));let n=ln(r),i=si(r);i&&(e["content-type"]=i);let o=await VP(r);o&&(e["x-first-bytes"]=o),typeof r=="string"&&(r=new TextEncoder().encode(r));let s=new Response(r,{headers:e});return Object.defineProperty(s,"url",{value:n}),s}async function Iy(r){if(!r.ok)throw await $P(r)}async function $P(r){let e=Cy(r.url),t=`Failed to fetch resource (${r.status}) ${r.statusText}: ${e}`;t=t.length>100?`${t.slice(0,100)}...`:t;let n={reason:r.statusText,url:r.url,response:r};try{let i=r.headers.get("Content-Type");n.reason=!r.bodyUsed&&i?.includes("application/json")?await r.json():await r.text()}catch{}return new nc(t,n)}async function VP(r){if(typeof r=="string")return`data:,${r.slice(0,5)}`;if(r instanceof Blob){let t=r.slice(0,5);return await new Promise(n=>{let i=new FileReader;i.onload=o=>n(o?.target?.result),i.readAsDataURL(t)})}if(r instanceof ArrayBuffer){let t=r.slice(0,5);return`data:base64,${WP(t)}`}return null}function WP(r){let e="",t=new Uint8Array(r);for(let n=0;n<t.byteLength;n++)e+=String.fromCharCode(t[n]);return btoa(e)}function jP(r){return!HP(r)&&!YP(r)}function HP(r){return r.startsWith("http:")||r.startsWith("https:")}function YP(r){return r.startsWith("data:")}async function fd(r,e){if(typeof r=="string"){let t=sd(r);return jP(t)&&globalThis.loaders?.fetchNode?globalThis.loaders?.fetchNode(t,e):await fetch(t,e)}return await ic(r)}xo();var Ao=new Fe({id:"loaders.gl"}),oc=class{log(){return()=>{}}info(){return()=>{}}warn(){return()=>{}}error(){return()=>{}}},sc=class{constructor(){d(this,"console");this.console=console}log(...e){return this.console.log.bind(this.console,...e)}info(...e){return this.console.info.bind(this.console,...e)}warn(...e){return this.console.warn.bind(this.console,...e)}error(...e){return this.console.error.bind(this.console,...e)}};var ac={core:{baseUrl:void 0,fetch:null,mimeType:void 0,fallbackMimeType:void 0,ignoreRegisteredLoaders:void 0,nothrow:!1,log:new sc,useLocalLibraries:!1,CDN:"https://unpkg.com/@loaders.gl",worker:!0,maxConcurrency:3,maxMobileConcurrency:1,reuseWorkers:_o,_nodeWorkers:!1,_workerType:"",limit:0,_limitMB:0,batchSize:"auto",batchDebounceMs:0,metadata:!1,transforms:[]}},Ry={baseUri:"core.baseUrl",fetch:"core.fetch",mimeType:"core.mimeType",fallbackMimeType:"core.fallbackMimeType",ignoreRegisteredLoaders:"core.ignoreRegisteredLoaders",nothrow:"core.nothrow",log:"core.log",useLocalLibraries:"core.useLocalLibraries",CDN:"core.CDN",worker:"core.worker",maxConcurrency:"core.maxConcurrency",maxMobileConcurrency:"core.maxMobileConcurrency",reuseWorkers:"core.reuseWorkers",_nodeWorkers:"core.nodeWorkers",_workerType:"core._workerType",_worker:"core._workerType",limit:"core.limit",_limitMB:"core._limitMB",batchSize:"core.batchSize",batchDebounceMs:"core.batchDebounceMs",metadata:"core.metadata",transforms:"core.transforms",throws:"nothrow",dataType:"(no longer used)",uri:"core.baseUrl",method:"core.fetch.method",headers:"core.fetch.headers",body:"core.fetch.body",mode:"core.fetch.mode",credentials:"core.fetch.credentials",cache:"core.fetch.cache",redirect:"core.fetch.redirect",referrer:"core.fetch.referrer",referrerPolicy:"core.fetch.referrerPolicy",integrity:"core.fetch.integrity",keepalive:"core.fetch.keepalive",signal:"core.fetch.signal"};var dd=["baseUrl","fetch","mimeType","fallbackMimeType","ignoreRegisteredLoaders","nothrow","log","useLocalLibraries","CDN","worker","maxConcurrency","maxMobileConcurrency","reuseWorkers","_nodeWorkers","_workerType","limit","_limitMB","batchSize","batchDebounceMs","metadata","transforms"];function hd(){globalThis.loaders=globalThis.loaders||{};let{loaders:r}=globalThis;return r._state||(r._state={}),r._state}function pd(){let r=hd();return r.globalOptions=r.globalOptions||{...ac,core:{...ac.core}},fr(r.globalOptions)}function ky(r,e,t,n){return t=t||[],t=Array.isArray(t)?t:[t],qP(r,t),fr(ZP(e,r,n))}function fr(r){let e=QP(r);Dy(e);for(let t of dd)e.core&&e.core[t]!==void 0&&delete e[t];return e.core&&e.core._workerType!==void 0&&delete e._worker,e}function qP(r,e){By(r,null,ac,Ry,e);for(let t of e){let n=r&&r[t.id]||{},i=t.options&&t.options[t.id]||{},o=t.deprecatedOptions&&t.deprecatedOptions[t.id]||{};By(n,t.id,i,o,e)}}function By(r,e,t,n,i){let o=e||"Top level",s=e?`${e}.`:"";for(let a in r){let c=!e&&Ft(r[a]),l=a==="baseUri"&&!e,u=a==="workerUrl"&&e;if(!(a in t)&&!l&&!u){if(a in n)Ao.level>0&&Ao.warn(`${o} loader option '${s}${a}' no longer supported, use '${n[a]}'`)();else if(!c&&Ao.level>0){let f=XP(a,i);Ao.warn(`${o} loader option '${s}${a}' not recognized. ${f}`)()}}}}function XP(r,e){let t=r.toLowerCase(),n="";for(let i of e)for(let o in i.options){if(r===o)return`Did you mean '${i.id}.${o}'?`;let s=o.toLowerCase();(t.startsWith(s)||s.startsWith(t))&&(n=n||`Did you mean '${i.id}.${o}'?`)}return n}function ZP(r,e,t){let n=r.options||{},i={...n};n.core&&(i.core={...n.core}),Dy(i),i.core?.log===null&&(i.core={...i.core,log:new oc}),Oy(i,fr(pd()));let o=fr(e);return Oy(i,o),KP(i,t),JP(i),i}function Oy(r,e){for(let t in e)if(t in e){let n=e[t];ec(n)&&ec(r[t])?r[t]={...r[t],...e[t]}:r[t]=e[t]}}function KP(r,e){if(!e)return;r.core?.baseUrl!==void 0||(r.core||(r.core={}),r.core.baseUrl=ur.dirname(Cr(e)))}function QP(r){let e={...r};return r.core&&(e.core={...r.core}),e}function Dy(r){r.baseUri!==void 0&&(r.core||(r.core={}),r.core.baseUrl===void 0&&(r.core.baseUrl=r.baseUri));for(let t of dd)if(r[t]!==void 0){let i=r.core=r.core||{};i[t]===void 0&&(i[t]=r[t])}let e=r._worker;e!==void 0&&(r.core||(r.core={}),r.core._workerType===void 0&&(r.core._workerType=e))}function JP(r){let e=r.core;if(e)for(let t of dd)e[t]!==void 0&&(r[t]=e[t])}function Co(r){return r?(Array.isArray(r)&&(r=r[0]),Array.isArray(r?.extensions)):!1}function Mo(r){Ya(r,"null loader"),Ya(Co(r),"invalid loader");let e;return Array.isArray(r)&&(e=r[1],r=r[0],r={...r,options:{...r.options,...e}}),(r?.parseTextSync||r?.parseText)&&(r.text=!0),r.text||(r.binary=!0),r}var Ny=()=>{let r=hd();return r.loaderRegistry=r.loaderRegistry||[],r.loaderRegistry};function md(r){let e=Ny();r=Array.isArray(r)?r:[r];for(let t of r){let n=Mo(t);e.find(i=>n===i)||e.unshift(n)}}function Fy(){return Ny()}var e3=/\.([^.]+)$/;async function zy(r,e=[],t,n){if(!$y(r))return null;let i=fr(t||{});if(i.core||(i.core={}),r instanceof Response&&Uy(r)){let s=await r.clone().text(),a=cc(s,e,{...i,core:{...i.core,nothrow:!0}},n);if(a)return a}let o=cc(r,e,{...i,core:{...i.core,nothrow:!0}},n);if(o)return o;if(tt(r)&&(r=await r.slice(0,10).arrayBuffer(),o=cc(r,e,i,n)),!o&&r instanceof Response&&Uy(r)){let s=await r.clone().text();o=cc(s,e,i,n)}if(!o&&!i.core.nothrow)throw new Error(Vy(r));return o}function Uy(r){let e=si(r);return!!(e&&(e.startsWith("text/")||e==="application/json"||e.endsWith("+json")))}function cc(r,e=[],t,n){if(!$y(r))return null;let i=fr(t||{});if(i.core||(i.core={}),e&&!Array.isArray(e))return Mo(e);let o=[];e&&(o=o.concat(e)),i.core.ignoreRegisteredLoaders||o.push(...Fy()),r3(o);let s=t3(r,o,i,n);if(!s&&!i.core.nothrow)throw new Error(Vy(r));return s}function t3(r,e,t,n){let i=ln(r),o=si(r),s=Cr(i)||n?.url,a=null,c="";return t?.core?.mimeType&&(a=gd(e,t?.core?.mimeType),c=`match forced by supplied MIME type ${t?.core?.mimeType}`),a=a||n3(e,s),c=c||(a?`matched url ${s}`:""),a=a||gd(e,o),c=c||(a?`matched MIME type ${o}`:""),a=a||o3(e,r),c=c||(a?`matched initial data ${Wy(r)}`:""),t?.core?.fallbackMimeType&&(a=a||gd(e,t?.core?.fallbackMimeType),c=c||(a?`matched fallback MIME type ${o}`:"")),c&&Vf.log(1,`selectLoader selected ${a?.name}: ${c}.`),a}function $y(r){return!(r instanceof Response&&r.status===204)}function Vy(r){let e=ln(r),t=si(r),n="No valid loader found (";n+=e?`${ur.filename(e)}, `:"no url provided, ",n+=`MIME type: ${t?`"${t}"`:"not provided"}, `;let i=r?Wy(r):"";return n+=i?` first bytes: "${i}"`:"first bytes: not available",n+=")",n}function r3(r){for(let e of r)Mo(e)}function n3(r,e){let t=e&&e3.exec(e),n=t&&t[1];return n?i3(r,n):null}function i3(r,e){e=e.toLowerCase();for(let t of r)for(let n of t.extensions)if(n.toLowerCase()===e)return t;return null}function gd(r,e){for(let t of r)if(t.mimeTypes?.some(n=>ld(e,n))||ld(e,`application/x.${t.id}`))return t;return null}function o3(r,e){if(!e)return null;for(let t of r)if(typeof e=="string"){if(s3(e,t))return t}else if(ArrayBuffer.isView(e)){if(Gy(e.buffer,e.byteOffset,t))return t}else if(e instanceof ArrayBuffer&&Gy(e,0,t))return t;return null}function s3(r,e){return e.testText?e.testText(r):(Array.isArray(e.tests)?e.tests:[e.tests]).some(n=>r.startsWith(n))}function Gy(r,e,t){return(Array.isArray(t.tests)?t.tests:[t.tests]).some(i=>a3(r,e,t,i))}function a3(r,e,t,n){if(ni(n))return td(n,r,n.byteLength);switch(typeof n){case"function":return n(To(r));case"string":let i=yd(r,e,n.length);return n===i;default:return!1}}function Wy(r,e=5){return typeof r=="string"?r.slice(0,e):ArrayBuffer.isView(r)?yd(r.buffer,r.byteOffset,e):r instanceof ArrayBuffer?yd(r,0,e):""}function yd(r,e,t){if(r.byteLength<e+t)return"";let n=new DataView(r),i="";for(let o=0;o<t;o++)i+=String.fromCharCode(n.getUint8(e+o));return i}var c3=256*1024;function*jy(r,e){let t=e?.chunkSize||c3,n=0,i=new TextEncoder;for(;n<r.length;){let o=Math.min(r.length-n,t),s=r.slice(n,n+o);n+=o,yield To(i.encode(s))}}function*Hy(r,e={}){let{chunkSize:t=262144}=e,n=0;for(;n<r.byteLength;){let i=Math.min(r.byteLength-n,t),o=new ArrayBuffer(i),s=new Uint8Array(r,n,i);new Uint8Array(o).set(s),n+=i,yield o}}async function*Yy(r,e){let t=e?.chunkSize||1048576,n=0;for(;n<r.size;){let i=n+t,o=await r.slice(n,i).arrayBuffer();n=i,yield o}}function _d(r,e){return _o?l3(r,e):u3(r,e)}async function*l3(r,e){let t=r.getReader(),n;try{for(;;){let i=n||t.read();e?._streamReadAhead&&(n=t.read());let{done:o,value:s}=await i;if(o)return;yield oi(s)}}catch{t.releaseLock()}}async function*u3(r,e){for await(let t of r)yield oi(t)}function qy(r,e){if(typeof r=="string")return jy(r,e);if(r instanceof ArrayBuffer)return Hy(r,e);if(tt(r))return Yy(r,e);if(vo(r))return _d(r,e);if(et(r)){let t=r.body;if(!t)throw new Error("Readable stream not available on Response");return _d(t,e)}throw new Error("makeIterator")}var Xy="Cannot convert supplied data type";function f3(r,e,t){if(e.text&&typeof r=="string")return r;if(rc(r)&&(r=r.buffer),ni(r)){let n=ad(r);return e.text&&!e.binary?new TextDecoder("utf8").decode(n):oi(n)}throw new Error(Xy)}async function Zy(r,e,t){if(typeof r=="string"||ni(r))return f3(r,e,t);if(tt(r)&&(r=await ic(r)),et(r))return await Iy(r),e.binary?await r.arrayBuffer():await r.text();if(vo(r)&&(r=qy(r,t)),jf(r)||Hf(r))return nd(r);throw new Error(Xy)}function lc(r,e){let t=pd(),n=r||t,i=n.fetch??n.core?.fetch;return typeof i=="function"?i:Ft(i)?o=>fd(o,i):e?.fetch?e?.fetch:fd}function Ky(r,e,t){if(t)return t;let n={fetch:lc(e,r),...r};if(n.url){let i=Cr(n.url);n.baseUrl=i,n.queryString=Ay(n.url),n.filename=ur.filename(i),n.baseUrl=ur.dirname(i)}return Array.isArray(n.loaders)||(n.loaders=null),n}function Qy(r,e){if(r&&!Array.isArray(r))return r;let t;if(r&&(t=Array.isArray(r)?r:[r]),e&&e.loaders){let n=Array.isArray(e.loaders)?e.loaders:[e.loaders];t=t?[...t,...n]:n}return t&&t.length?t:void 0}async function Io(r,e,t,n){e&&!Array.isArray(e)&&!Co(e)&&(n=void 0,t=e,e=void 0),r=await r,t=t||{};let i=ln(r),s=Qy(e,n),a=await zy(r,s,t);if(!a)return null;let c=ky(t,a,s,i);return n=Ky({url:i,_parse:Io,loaders:s},c,n||null),await d3(a,r,c,n)}async function d3(r,e,t,n){if(Qf(r),t=Yf(r.options,t),et(e)){let{ok:o,redirected:s,status:a,statusText:c,type:l,url:u}=e,f=Object.fromEntries(e.headers.entries());n.response={headers:f,ok:o,redirected:s,status:a,statusText:c,type:l,url:u}}e=await Zy(e,r,t);let i=r;if(i.parseTextSync&&typeof e=="string")return i.parseTextSync(e,t,n);if(Jf(r,t))return await ed(r,e,t,n,Io);if(i.parseText&&typeof e=="string")return await i.parseText(e,t,n);if(i.parse)return await i.parse(e,t,n);throw Ue(!i.parseSync),new Error(`${r.id} loader - no parser found and worker is disabled`)}async function ai(r,e,t,n){let i,o;!Array.isArray(e)&&!Co(e)?(i=[],o=e,n=void 0):(i=e,o=t);let s=lc(o),a=r;return typeof r=="string"&&(a=await s(r)),tt(r)&&(a=await s(r)),typeof r=="string"&&(fr(o||{}).core?.baseUrl||(o={...o,core:{...o?.core,baseUrl:r}})),Array.isArray(i)?await Io(a,i,o):await Io(a,i,o)}var r_="4.5.1";function Bo(r,e){if(!r)throw new Error(e||"loader assertion failed.")}var Gt={self:typeof self<"u"&&self,window:typeof window<"u"&&window,global:typeof global<"u"&&global,document:typeof document<"u"&&document},h3=Gt.self||Gt.window||Gt.global||{},p3=Gt.window||Gt.self||Gt.global||{},m3=Gt.global||Gt.self||Gt.window||{},g3=Gt.document||{};var xd=!!(typeof process!="object"||String(process)!=="[object process]"||process.browser);var n_=typeof process<"u"&&process.version&&/v([0-9]*)/.exec(process.version),y3=n_&&parseFloat(n_[1])||0;var _3=globalThis.loaders?.parseImageNode,vd=typeof Image<"u",wd=typeof ImageBitmap<"u",b3=!!_3,Ed=xd?!0:b3;function i_(r){switch(r){case"auto":return wd||vd||Ed;case"imagebitmap":return wd;case"image":return vd;case"data":return Ed;default:throw new Error(`@loaders.gl/images: image ${r} not supported in this environment`)}}function o_(){if(wd)return"imagebitmap";if(vd)return"image";if(Ed)return"data";throw new Error("Install '@loaders.gl/polyfills' to parse images under Node.js")}function x3(r){let e=v3(r);if(!e)throw new Error("Not an image");return e}function s_(r){switch(x3(r)){case"data":return r;case"image":case"imagebitmap":let e=document.createElement("canvas"),t=e.getContext("2d");if(!t)throw new Error("getImageData");return e.width=r.width,e.height=r.height,t.drawImage(r,0,0),t.getImageData(0,0,r.width,r.height);default:throw new Error("getImageData")}}function v3(r){return typeof ImageBitmap<"u"&&r instanceof ImageBitmap?"imagebitmap":typeof Image<"u"&&r instanceof Image?"image":r&&typeof r=="object"&&r.data&&r.width&&r.height?"data":null}var w3=/^data:image\/svg\+xml/,E3=/\.svg((\?|#).*)?$/;function uc(r){return r&&(w3.test(r)||E3.test(r))}function a_(r,e){if(uc(e)){let n=new TextDecoder().decode(r);try{typeof unescape=="function"&&typeof encodeURIComponent=="function"&&(n=unescape(encodeURIComponent(n)))}catch(o){throw new Error(o.message)}return`data:image/svg+xml;base64,${btoa(n)}`}return Sd(r,e)}function Sd(r,e){if(uc(e))throw new Error("SVG cannot be parsed directly to imagebitmap");return new Blob([new Uint8Array(r)])}async function fc(r,e,t){let n=a_(r,t),i=self.URL||self.webkitURL,o=typeof n!="string"&&i.createObjectURL(n);try{return await S3(o||n,e)}finally{o&&i.revokeObjectURL(o)}}async function S3(r,e){let t=new Image;return t.src=r,e.image&&e.image.decode&&t.decode?(await t.decode(),t):await new Promise((n,i)=>{try{t.onload=()=>n(t),t.onerror=o=>{let s=o instanceof Error?o.message:"error";i(new Error(s))}}catch(o){i(o)}})}var c_=!0;async function l_(r,e,t){let n;uc(t)?n=await fc(r,e,t):n=Sd(r,t);let i=e&&e.imagebitmap;return await P3(n,i)}async function P3(r,e=null){if((T3(e)||!c_)&&(e=null),e)try{return await createImageBitmap(r,e)}catch(t){console.warn(t),c_=!1}return await createImageBitmap(r)}function T3(r){if(!r)return!0;for(let e in r)if(Object.prototype.hasOwnProperty.call(r,e))return!1;return!0}function u_(r){return!M3(r,"ftyp",4)||(r[8]&96)===0?null:L3(r)}function L3(r){switch(A3(r,8,12).replace("\0"," ").trim()){case"avif":case"avis":return{extension:"avif",mimeType:"image/avif"};default:return null}}function A3(r,e,t){return String.fromCharCode(...r.slice(e,t))}function C3(r){return[...r].map(e=>e.charCodeAt(0))}function M3(r,e,t=0){let n=C3(e);for(let i=0;i<n.length;++i)if(n[i]!==r[i+t])return!1;return!0}var zt=!1,Oo=!0;function dc(r){let e=ko(r);return R3(e)||k3(e)||B3(e)||O3(e)||I3(e)}function I3(r){let e=new Uint8Array(r instanceof DataView?r.buffer:r),t=u_(e);return t?{mimeType:t.mimeType,width:0,height:0}:null}function R3(r){let e=ko(r);return e.byteLength>=24&&e.getUint32(0,zt)===2303741511?{mimeType:"image/png",width:e.getUint32(16,zt),height:e.getUint32(20,zt)}:null}function B3(r){let e=ko(r);return e.byteLength>=10&&e.getUint32(0,zt)===1195984440?{mimeType:"image/gif",width:e.getUint16(6,Oo),height:e.getUint16(8,Oo)}:null}function O3(r){let e=ko(r);return e.byteLength>=14&&e.getUint16(0,zt)===16973&&e.getUint32(2,Oo)===e.byteLength?{mimeType:"image/bmp",width:e.getUint32(18,Oo),height:e.getUint32(22,Oo)}:null}function k3(r){let e=ko(r);if(!(e.byteLength>=3&&e.getUint16(0,zt)===65496&&e.getUint8(2)===255))return null;let{tableMarkers:n,sofMarkers:i}=D3(),o=2;for(;o+9<e.byteLength;){let s=e.getUint16(o,zt);if(i.has(s))return{mimeType:"image/jpeg",height:e.getUint16(o+5,zt),width:e.getUint16(o+7,zt)};if(!n.has(s))return null;o+=2,o+=e.getUint16(o,zt)}return null}function D3(){let r=new Set([65499,65476,65484,65501,65534]);for(let t=65504;t<65520;++t)r.add(t);return{tableMarkers:r,sofMarkers:new Set([65472,65473,65474,65475,65477,65478,65479,65481,65482,65483,65485,65486,65487,65502])}}function ko(r){if(r instanceof DataView)return r;if(ArrayBuffer.isView(r))return new DataView(r.buffer);if(r instanceof ArrayBuffer)return new DataView(r);throw new Error("toDataView")}async function f_(r,e){let{mimeType:t}=dc(r)||{},n=globalThis.loaders?.parseImageNode;return Bo(n),await n(r,t)}async function d_(r,e,t){e=e||{};let i=(e.image||{}).type||"auto",{url:o}=t||{},s=N3(i),a;switch(s){case"imagebitmap":a=await l_(r,e,o);break;case"image":a=await fc(r,e,o);break;case"data":a=await f_(r,e);break;default:Bo(!1)}return i==="data"&&(a=s_(a)),a}function N3(r){switch(r){case"auto":case"data":return o_();default:return i_(r),r}}var F3=["png","jpg","jpeg","gif","webp","bmp","ico","svg","avif"],U3=["image/png","image/jpeg","image/gif","image/webp","image/avif","image/bmp","image/vnd.microsoft.icon","image/svg+xml"],G3={image:{type:"auto",decode:!0}},Pd={dataType:null,batchType:null,id:"image",module:"images",name:"Images",version:r_,mimeTypes:U3,extensions:F3,parse:d_,tests:[r=>!!dc(new DataView(r))],options:G3};xo();var z3=new Fe({id:"deck"}),$=z3;var Td={};function h_(r){Td=r}function me(r,e,t,n){$.level>0&&Td[r]&&Td[r].call(null,e,t,n)}function $3(r){let e=r[0],t=r[r.length-1];return e==="{"&&t==="}"||e==="["&&t==="]"}var p_={dataType:null,batchType:null,id:"JSON",name:"JSON",module:"",version:"",options:{},extensions:["json","geojson"],mimeTypes:["application/json","application/geo+json"],testText:$3,parseTextSync:JSON.parse};function V3(){let r="9.4.0",e=globalThis.deck&&globalThis.deck.VERSION;if(e&&e!==r)throw new Error(`deck.gl - multiple versions detected: ${e} vs ${r}`);return e||($.log(1,`deck.gl ${r}`)(),globalThis.deck={...globalThis.deck,VERSION:r,version:r,log:$,_registerLoggers:h_},md([p_,[Pd,{imagebitmap:{premultiplyAlpha:"none"}}]])),r}var m_=V3();qe();var GI=`struct LayerUniforms {
  opacity: f32,
};

@group(0) @binding(auto)
var<uniform> layer: LayerUniforms;
`,Q0=`layout(std140) uniform layerUniforms {
  uniform float opacity;
} layer;
`,Tp={name:"layer",source:GI,vs:Q0,fs:Q0,getUniforms:r=>({opacity:Math.pow(r.opacity,.45454545454545453)}),uniformTypes:{opacity:"f32"}};var zI=`

@must_use
fn deckgl_premultiplied_alpha(fragColor: vec4<f32>) -> vec4<f32> {
    return vec4(fragColor.rgb * fragColor.a, fragColor.a); 
};
`,Ur={name:"color",dependencies:[],source:zI,getUniforms:r=>({})};var $I=`const SMOOTH_EDGE_RADIUS: f32 = 0.5;

struct VertexGeometry {
  position: vec4<f32>,
  worldPosition: vec3<f32>,
  worldPositionAlt: vec3<f32>,
  normal: vec3<f32>,
  uv: vec2<f32>,
  pickingColor: vec3<f32>,
};

var<private> geometry_: VertexGeometry = VertexGeometry(
  vec4<f32>(0.0, 0.0, 1.0, 0.0),
  vec3<f32>(0.0, 0.0, 0.0),
  vec3<f32>(0.0, 0.0, 0.0),
  vec3<f32>(0.0, 0.0, 0.0),
  vec2<f32>(0.0, 0.0),
  vec3<f32>(0.0, 0.0, 0.0)
);

struct FragmentGeometry {
  uv: vec2<f32>,
};

var<private> fragmentGeometry: FragmentGeometry;

fn smoothedge(edge: f32, x: f32) -> f32 {
  return smoothstep(edge - SMOOTH_EDGE_RADIUS, edge + SMOOTH_EDGE_RADIUS, x);
}
`,J0="#define SMOOTH_EDGE_RADIUS 0.5",VI=`${J0}

struct VertexGeometry {
  vec4 position;
  vec3 worldPosition;
  vec3 worldPositionAlt;
  vec3 normal;
  vec2 uv;
  vec3 pickingColor;
} geometry = VertexGeometry(
  vec4(0.0, 0.0, 1.0, 0.0),
  vec3(0.0),
  vec3(0.0),
  vec3(0.0),
  vec2(0.0),
  vec3(0.0)
);
`,WI=`${J0}

struct FragmentGeometry {
  vec2 uv;
};
FragmentGeometry geometry;

float smoothedge(float edge, float x) {
  return smoothstep(edge - SMOOTH_EDGE_RADIUS, edge + SMOOTH_EDGE_RADIUS, x);
}
`,wl={name:"geometry",source:$I,vs:VI,fs:WI};qe();Ee();var G;(function(r){r[r.Start=1]="Start",r[r.Move=2]="Move",r[r.End=4]="End",r[r.Cancel=8]="Cancel"})(G||(G={}));var oe;(function(r){r[r.None=0]="None",r[r.Left=1]="Left",r[r.Right=2]="Right",r[r.Up=4]="Up",r[r.Down=8]="Down",r[r.Horizontal=3]="Horizontal",r[r.Vertical=12]="Vertical",r[r.All=15]="All"})(oe||(oe={}));var D;(function(r){r[r.Possible=1]="Possible",r[r.Began=2]="Began",r[r.Changed=4]="Changed",r[r.Ended=8]="Ended",r[r.Recognized=8]="Recognized",r[r.Cancelled=16]="Cancelled",r[r.Failed=32]="Failed"})(D||(D={}));var ev="compute",Lp="auto",Rn="manipulation",Bn="none",ms="pan-x",gs="pan-y";function Ap(r){if(r.includes(Bn))return Bn;let e=r.includes(ms),t=r.includes(gs);return e&&t?Bn:e||t?e?ms:gs:r.includes(Rn)?Rn:Lp}var ys=class{constructor(e,t){this.actions="",this.manager=e,this.set(t)}set(e){e===ev&&(e=this.compute()),this.manager.element&&(this.manager.element.style.touchAction=e,this.actions=e)}update(){this.set(this.manager.options.touchAction)}compute(){let e=[];for(let t of this.manager.recognizers)t.options.enable&&(e=e.concat(t.getTouchAction()));return Ap(e.join(" "))}};function Pi(r){return r.trim().split(/\s+/g)}function El(r,e,t){if(r)for(let n of Pi(e))r.addEventListener(n,t,!1)}function Sl(r,e,t){if(r)for(let n of Pi(e))r.removeEventListener(n,t,!1)}function Cp(r){return(r.ownerDocument||r).defaultView}function Mp(r,e){let t=r;for(;t;){if(t===e)return!0;t=t.parentNode}return!1}function Pl(r){let e=r.length;if(e===1)return{x:Math.round(r[0].clientX),y:Math.round(r[0].clientY)};let t=0,n=0,i=0;for(;i<e;)t+=r[i].clientX,n+=r[i].clientY,i++;return{x:Math.round(t/e),y:Math.round(n/e)}}function Ip(r){let e=[],t=0;for(;t<r.pointers.length;)e[t]={clientX:Math.round(r.pointers[t].clientX),clientY:Math.round(r.pointers[t].clientY)},t++;return{timeStamp:Date.now(),pointers:e,center:Pl(e),deltaX:r.deltaX,deltaY:r.deltaY}}function Ti(r,e){let t=e.x-r.x,n=e.y-r.y;return Math.sqrt(t*t+n*n)}function _s(r,e){let t=e.clientX-r.clientX,n=e.clientY-r.clientY;return Math.sqrt(t*t+n*n)}function tv(r,e){let t=e.x-r.x,n=e.y-r.y;return Math.atan2(n,t)*180/Math.PI}function Rp(r,e){let t=e.clientX-r.clientX,n=e.clientY-r.clientY;return Math.atan2(n,t)*180/Math.PI}function Li(r,e){return r===e?oe.None:Math.abs(r)>=Math.abs(e)?r<0?oe.Left:oe.Right:e<0?oe.Up:oe.Down}function rv(r,e){let t=e.center,n=r.offsetDelta,i=r.prevDelta,o=r.prevInput;return(e.eventType===G.Start||o?.eventType===G.End)&&(i=r.prevDelta={x:o?.deltaX||0,y:o?.deltaY||0},n=r.offsetDelta={x:t.x,y:t.y}),{deltaX:i.x+(t.x-n.x),deltaY:i.y+(t.y-n.y)}}function Tl(r,e,t){return{x:e/r||0,y:t/r||0}}function nv(r,e){return _s(e[0],e[1])/_s(r[0],r[1])}function iv(r,e){return Rp(e[1],e[0])-Rp(r[1],r[0])}function ov(r,e){let t=r.lastInterval||e,n=e.timeStamp-t.timeStamp,i,o,s,a;if(e.eventType!==G.Cancel&&(n>25||t.velocity===void 0)){let c=e.deltaX-t.deltaX,l=e.deltaY-t.deltaY,u=Tl(n,c,l);o=u.x,s=u.y,i=Math.abs(u.x)>Math.abs(u.y)?u.x:u.y,a=Li(c,l),r.lastInterval=e}else i=t.velocity,o=t.velocityX,s=t.velocityY,a=t.direction;e.velocity=i,e.velocityX=o,e.velocityY=s,e.direction=a}function Bp(r,e){return"pointerId"in r?r.pointerId:e}function sv(r,e){r.movementOrigin=new Map(e.map((t,n)=>[Bp(t,n),{clientX:t.clientX,clientY:t.clientY}])),r.firstMovementTime=void 0}function HI(r,e){let t=e.pointers.map(Bp);if(r.movementOrigin?.size===t.length&&t.every(i=>r.movementOrigin.has(i))||sv(r,e.pointers),e.distancePerPointer=e.pointers.map((i,o)=>_s(r.movementOrigin.get(t[o]),i)),e.eventType&G.Move&&e.distancePerPointer.some(i=>i>0)&&(r.firstMovementTime??(r.firstMovementTime=e.timeStamp)),e.movementDeltaTime=r.firstMovementTime===void 0?0:e.timeStamp-r.firstMovementTime,e.eventType&(G.End|G.Cancel)){let i=e.changedPointers.map(o=>Bp(o,e.pointers.indexOf(o)));sv(r,e.pointers.filter((o,s)=>!i.includes(t[s])))}}function av(r,e){let{session:t}=r,{pointers:n}=e,{length:i}=n;t.firstInput||(t.firstInput=Ip(e)),i>1&&!t.firstMultiple?t.firstMultiple=Ip(e):i===1&&(t.firstMultiple=!1);let{firstInput:o,firstMultiple:s}=t,a=s?s.center:o.center,c=e.center=Pl(n);e.timeStamp=Date.now(),e.deltaTime=e.timeStamp-o.timeStamp,HI(t,e),e.angle=tv(a,c),e.distance=Ti(a,c);let{deltaX:l,deltaY:u}=rv(t,e);e.deltaX=l,e.deltaY=u,e.offsetDirection=Li(e.deltaX,e.deltaY);let f=Tl(e.deltaTime,e.deltaX,e.deltaY);e.overallVelocityX=f.x,e.overallVelocityY=f.y,e.overallVelocity=Math.abs(f.x)>Math.abs(f.y)?f.x:f.y,e.scale=s?nv(s.pointers,n):1,e.rotation=s?iv(s.pointers,n):0,e.maxPointers=t.prevInput?e.pointers.length>t.prevInput.maxPointers?e.pointers.length:t.prevInput.maxPointers:e.pointers.length;let h=r.element;return Mp(e.srcEvent.target,h)&&(h=e.srcEvent.target),e.target=h,ov(t,e),e}function cv(r,e,t){let n=t.pointers.length,i=t.changedPointers.length,o=e&G.Start&&n-i===0,s=e&(G.End|G.Cancel)&&n-i===0;t.isFirst=!!o,t.isFinal=!!s,o&&(r.session={}),t.eventType=e;let a=av(r,t);r.emit("hammer.input",a),r.recognize(a),r.session.prevInput=a}var bs=class{constructor(e){this.evEl="",this.evWin="",this.evTarget="",this.domHandler=t=>{this.manager.options.enable&&this.handler(t)},this.manager=e,this.element=e.element,this.target=e.options.inputTarget||e.element}callback(e,t){cv(this.manager,e,t)}init(){El(this.element,this.evEl,this.domHandler),El(this.target,this.evTarget,this.domHandler),El(Cp(this.element),this.evWin,this.domHandler)}destroy(){Sl(this.element,this.evEl,this.domHandler),Sl(this.target,this.evTarget,this.domHandler),Sl(Cp(this.element),this.evWin,this.domHandler)}};var YI={pointerdown:G.Start,pointermove:G.Move,pointerup:G.End,pointercancel:G.Cancel,pointerout:G.Cancel},qI="pointerdown",XI="pointermove pointerup pointercancel",xs=class extends bs{constructor(e){super(e),this.evEl=qI,this.evWin=XI,this.store=this.manager.session.pointerEvents=[],this.init()}handler(e){let{store:t}=this,n=!1,i=YI[e.type],o=e.pointerType,s=o==="touch",a=t.findIndex(c=>c.pointerId===e.pointerId);i&G.Start&&(e.buttons||s)?a<0&&(t.push(e),a=t.length-1):i&(G.End|G.Cancel)&&(n=!0),!(a<0)&&(t[a]=e,this.callback(i,{pointers:t,changedPointers:[e],eventType:i,pointerType:o,srcEvent:e}),n&&t.splice(a,1))}};var ZI=["","webkit","Moz","MS","ms","o"];function lv(r,e){let t=e[0].toUpperCase()+e.slice(1);for(let n of ZI){let i=n?n+t:e;if(i in r)return i}}var KI=1,uv=2,fv={touchAction:"compute",enable:!0,inputTarget:null,cssProps:{userSelect:"none",userDrag:"none",touchCallout:"none",tapHighlightColor:"rgba(0,0,0,0)"}},vs=class{constructor(e,t){this.options={...fv,...t,cssProps:{...fv.cssProps,...t.cssProps},inputTarget:t.inputTarget||e},this.handlers={},this.session={},this.recognizers=[],this.oldCssProps={},this.element=e,this.input=new xs(this),this.touchAction=new ys(this,this.options.touchAction),this.toggleCssProps(!0)}set(e){return Object.assign(this.options,e),e.touchAction&&this.touchAction.update(),e.inputTarget&&(this.input.destroy(),this.input.target=e.inputTarget,this.input.init()),this}stop(e){this.session.stopped=e?uv:KI}recognize(e){let{session:t}=this;if(t.stopped)return;this.session.prevented&&e.srcEvent.preventDefault();let n,{recognizers:i}=this,{curRecognizer:o}=t;(!o||o&&o.state&D.Recognized)&&(o=t.curRecognizer=null);let s=0;for(;s<i.length;)n=i[s],t.stopped!==uv&&(!o||n===o||n.canRecognizeWith(o))?n.recognize(e):n.reset(),!o&&n.state&(D.Began|D.Changed|D.Ended)&&(o=t.curRecognizer=n),s++}get(e){let{recognizers:t}=this;for(let n=0;n<t.length;n++)if(t[n].options.event===e)return t[n];return null}add(e){if(Array.isArray(e)){for(let n of e)this.add(n);return this}let t=this.get(e.options.event);return t&&this.remove(t),this.recognizers.push(e),e.manager=this,this.touchAction.update(),e}remove(e){if(Array.isArray(e)){for(let n of e)this.remove(n);return this}let t=typeof e=="string"?this.get(e):e;if(t){let{recognizers:n}=this,i=n.indexOf(t);i!==-1&&(n.splice(i,1),this.touchAction.update())}return this}on(e,t){if(!e||!t)return;let{handlers:n}=this;for(let i of Pi(e))n[i]=n[i]||[],n[i].push(t)}off(e,t){if(!e)return;let{handlers:n}=this;for(let i of Pi(e))t?n[i]&&n[i].splice(n[i].indexOf(t),1):delete n[i]}emit(e,t){let n=this.handlers[e]&&this.handlers[e].slice();if(!n||!n.length)return;let i=t;i.type=e,i.preventDefault=function(){t.srcEvent.preventDefault()};let o=0;for(;o<n.length;)n[o](i),o++}destroy(){this.toggleCssProps(!1),this.handlers={},this.session={},this.input.destroy(),this.element=null}toggleCssProps(e){let{element:t}=this;if(t){for(let[n,i]of Object.entries(this.options.cssProps)){let o=lv(t.style,n);e?(this.oldCssProps[o]=t.style[o],t.style[o]=i):t.style[o]=this.oldCssProps[o]||""}e||(this.oldCssProps={})}}};var QI=1;function dv(){return QI++}function Op(r){return r&D.Cancelled?"cancel":r&D.Ended?"end":r&D.Changed?"move":r&D.Began?"start":""}var St=class{constructor(e){this.options=e,this.id=dv(),this.state=D.Possible,this.simultaneous={},this.requireFail=[]}set(e){return Object.assign(this.options,e),this.manager.touchAction.update(),this}recognizeWith(e){if(Array.isArray(e)){for(let i of e)this.recognizeWith(i);return this}let t;if(typeof e=="string"){if(t=this.manager.get(e),!t)throw new Error(`Cannot find recognizer ${e}`)}else t=e;let{simultaneous:n}=this;return n[t.id]||(n[t.id]=t,t.recognizeWith(this)),this}dropRecognizeWith(e){if(Array.isArray(e)){for(let n of e)this.dropRecognizeWith(n);return this}let t;return typeof e=="string"?t=this.manager.get(e):t=e,t&&delete this.simultaneous[t.id],this}requireFailure(e){if(Array.isArray(e)){for(let i of e)this.requireFailure(i);return this}let t;if(typeof e=="string"){if(t=this.manager.get(e),!t)throw new Error(`Cannot find recognizer ${e}`)}else t=e;let{requireFail:n}=this;return n.indexOf(t)===-1&&(n.push(t),t.requireFailure(this)),this}dropRequireFailure(e){if(Array.isArray(e)){for(let n of e)this.dropRequireFailure(n);return this}let t;if(typeof e=="string"?t=this.manager.get(e):t=e,t){let n=this.requireFail.indexOf(t);n>-1&&this.requireFail.splice(n,1)}return this}hasRequireFailures(){return!!this.requireFail.find(e=>e.options.enable)}canRecognizeWith(e){return!!this.simultaneous[e.id]}emit(e){if(!e)return;let{state:t}=this;t<D.Ended&&this.manager.emit(this.options.event+Op(t),e),this.manager.emit(this.options.event,e),e.additionalEvent&&this.manager.emit(e.additionalEvent,e),t>=D.Ended&&this.manager.emit(this.options.event+Op(t),e)}tryEmit(e){this.canEmit()?this.emit(e):this.state=D.Failed}canEmit(){let e=0;for(;e<this.requireFail.length;){if(!(this.requireFail[e].state&(D.Failed|D.Possible)))return!1;e++}return!0}recognize(e){let t={...e};if(!this.options.enable){this.reset(),this.state=D.Failed;return}this.state&(D.Recognized|D.Cancelled|D.Failed)&&(this.state=D.Possible),this.state=this.process(t),this.state&(D.Began|D.Changed|D.Ended|D.Cancelled)&&this.tryEmit(t)}getEventNames(){return[this.options.event]}reset(){}};function JI(r){return Math.abs(((r+180)%360+360)%360-180)}function eR(r,e){return(e.distance===void 0||r.distance>=e.distance)&&(e.distancePerPointer===void 0||r.distancePerPointer.length>0&&r.distancePerPointer.every(t=>t>=e.distancePerPointer))&&(e.movementDeltaTime===void 0||r.movementDeltaTime>=e.movementDeltaTime)&&(e.rotation===void 0||JI(r.rotation)>=e.rotation)&&(e.scale===void 0||Math.abs(r.scale-1)>=e.scale)}var On=class extends St{attrTest(e){let t=this.options.pointers;return t===0||e.pointers.length===t}coherentTest(e){let t=this.options.coherent;return!t?.length||t.some(n=>eR(e,n))}process(e){let{state:t}=this,{eventType:n}=e,i=t&(D.Began|D.Changed),o=this.attrTest(e);return i&&(n&G.Cancel||!o)?t|D.Cancelled:i||o?n&G.End?t|D.Ended:t&D.Began?t|D.Changed:D.Began:D.Failed}};var tR=["","start","move","end","cancel"],Ai=class extends St{constructor(e={}){super({enable:!0,event:"doubleclickdrag",pointers:1,interval:500,time:350,threshold:28,dragThreshold:1,pixelsPerScale:120,...e}),this._tapStart=null,this._lastTap=null,this._drag=null,this._emittedStart=!1}getTouchAction(){return[Rn]}getEventNames(){return tR.map(e=>this.options.event+e)}process(e){let{options:t}=this;return e.pointers.length===t.pointers?e.eventType&G.Start?this._handleStart(e):e.eventType&G.Move?this._handleMove(e):e.eventType&G.Cancel?this._handleEnd(e,!0):e.eventType&G.End?this._handleEnd(e,!1):D.Failed:(this.reset(),D.Failed)}reset(){this._tapStart=null,this._lastTap=null,this._drag=null,this._emittedStart=!1}emit(e){if(e){if(this.state===D.Began){if(!this._drag?.active||this._emittedStart)return;this._emittedStart=!0,this.manager.emit(`${this.options.event}start`,e),this.manager.emit(this.options.event,e);return}if(this.state===D.Changed){if(!this._emittedStart)return;this.manager.emit(`${this.options.event}move`,e),this.manager.emit(this.options.event,e);return}if(this.state===D.Ended){if(!this._emittedStart)return;this.manager.emit(this.options.event,e),this.manager.emit(`${this.options.event}end`,e),this._emittedStart=!1;return}if(this.state===D.Cancelled){if(!this._emittedStart)return;this.manager.emit(this.options.event,e),this.manager.emit(`${this.options.event}cancel`,e),this._emittedStart=!1}}}_handleStart(e){let t=this._getPointerId(e);return this._lastTap&&this._isTapMatch(e,this._lastTap)?(this._tapStart=null,this._lastTap=null,this._drag={startCenter:e.center,pointerId:t,active:!1},this._emittedStart=!1,D.Began):(this._tapStart={center:e.center,timeStamp:e.timeStamp,pointerId:t},this._lastTap=null,this._drag=null,this._emittedStart=!1,D.Failed)}_handleMove(e){if(!this._drag||!this._isSamePointer(e,this._drag.pointerId))return D.Failed;let t=this._drag.startCenter.y-e.center.y;return!this._drag.active&&Math.abs(t)<this.options.dragThreshold?D.Began:(this._drag.active=!0,e.scale=Math.pow(2,t/this.options.pixelsPerScale),this._emittedStart?D.Changed:D.Began)}_handleEnd(e,t){if(this._drag&&this._isSamePointer(e,this._drag.pointerId)){let{active:n,startCenter:i}=this._drag;if(this._drag=null,this._tapStart=null,this._lastTap=null,!n)return this._emittedStart=!1,D.Failed;let o=i.y-e.center.y;return e.scale=Math.pow(2,o/this.options.pixelsPerScale),t?D.Cancelled:D.Ended}return!this._tapStart||!this._isSamePointer(e,this._tapStart.pointerId)?(t&&this.reset(),D.Failed):(this._isValidTap(e)?this._lastTap={center:e.center,timeStamp:e.timeStamp,pointerId:this._tapStart.pointerId}:this._lastTap=null,this._tapStart=null,D.Failed)}_isTapMatch(e,t){return e.timeStamp-t.timeStamp<=this.options.interval&&Ti(e.center,t.center)<=this.options.threshold}_isValidTap(e){return e.deltaTime<=this.options.time&&e.distance<=this.options.threshold}_getPointerId(e){return"pointerId"in e.srcEvent?e.srcEvent.pointerId:null}_isSamePointer(e,t){return t===null||this._getPointerId(e)===t}};var kn=class extends St{constructor(e={}){super({enable:!0,event:"tap",pointers:1,taps:1,interval:300,time:250,threshold:9,posThreshold:10,...e}),this.pTime=null,this.pCenter=null,this._timer=null,this._input=null,this.count=0}getTouchAction(){return[Rn]}process(e){let{options:t}=this,n=e.pointers.length===t.pointers,i=e.distance<t.threshold,o=e.deltaTime<t.time;if(this.reset(),e.eventType&G.Start&&this.count===0)return this.failTimeout();if(i&&o&&n){if(e.eventType!==G.End)return this.failTimeout();let s=this.pTime?e.timeStamp-this.pTime<t.interval:!0,a=!this.pCenter||Ti(this.pCenter,e.center)<t.posThreshold;if(this.pTime=e.timeStamp,this.pCenter=e.center,!a||!s?this.count=1:this.count+=1,this._input=e,this.count%t.taps===0)return this.hasRequireFailures()?(this._timer=setTimeout(()=>{this.state=D.Recognized,this.tryEmit(this._input)},t.interval),D.Began):D.Recognized}return D.Failed}failTimeout(){return this._timer=setTimeout(()=>{this.state=D.Failed},this.options.interval),D.Failed}reset(){clearTimeout(this._timer)}emit(e){this.state===D.Recognized&&(e.tapCount=this.count,this.manager.emit(this.options.event,e))}};var Ci=class extends On{constructor(){super(...arguments),this.wheelSession=null,this.wheelSessionUnsubscribe=null,this.handleWheelSessionEvent=e=>{e.device==="trackpad"&&this.handleTrackpadEvent(e)}}set(e){let{wheelSession:t,...n}=e;return t&&t!==this.wheelSession&&(this.wheelSessionUnsubscribe?.(),this.wheelSessionUnsubscribe=null,this.wheelSession=t),super.set(n),this.updateWheelSessionSubscription(),this}getTrackpadInput(e,t={}){let{srcEvent:n}=e,i=t.deltaX??e.deltaX,o=t.deltaY??e.deltaY,s=Li(i,o),a=Math.sqrt(e.deltaX*e.deltaX+e.deltaY*e.deltaY),c=n;return{pointers:[c,c],changedPointers:[c,c],pointerType:"trackpad",srcEvent:c,eventType:e.eventType,timeStamp:e.timeStamp,deltaTime:e.deltaTime,center:e.center,deltaX:i,deltaY:o,angle:Math.atan2(o,i)*180/Math.PI,distance:Math.sqrt(i*i+o*o),distancePerPointer:[a,a],movementDeltaTime:e.deltaTime,scale:1,rotation:0,direction:s,offsetDirection:s,velocity:e.velocity,velocityX:e.velocityX,velocityY:e.velocityY,overallVelocity:e.overallVelocity,overallVelocityX:e.overallVelocityX,overallVelocityY:e.overallVelocityY,maxPointers:2,target:n.target||this.manager.element,additionalEvent:"",...t}}updateWheelSessionSubscription(){let e=!!(this.wheelSession&&this.options.enable&&this.options.trackpad&&this.options.pointers===2);e&&!this.wheelSessionUnsubscribe?this.wheelSessionUnsubscribe=this.wheelSession.on(this.handleWheelSessionEvent):!e&&this.wheelSessionUnsubscribe&&(this.wheelSessionUnsubscribe(),this.wheelSessionUnsubscribe=null)}};var rR=["","start","move","end","cancel","up","down","left","right"],Gr=class extends Ci{constructor(e={}){super({enable:!0,pointers:1,event:"pan",threshold:10,direction:oe.All,trackpad:!1,coherent:[],...e}),this.trackpadGesture=!1,this.pX=null,this.pY=null}getTouchAction(){let{options:{direction:e}}=this,t=[];return e&oe.Horizontal&&t.push(gs),e&oe.Vertical&&t.push(ms),t}getEventNames(){return rR.map(e=>this.options.event+e)}directionTest(e){let{options:t}=this,n=!0,{distance:i}=e,{direction:o}=e,s=e.deltaX,a=e.deltaY;return o&t.direction||(t.direction&oe.Horizontal?(o=s===0?oe.None:s<0?oe.Left:oe.Right,n=s!==this.pX,i=Math.abs(e.deltaX)):(o=a===0?oe.None:a<0?oe.Up:oe.Down,n=a!==this.pY,i=Math.abs(e.deltaY))),e.direction=o,n&&i>t.threshold&&!!(o&t.direction)}attrTest(e){let t=!!(this.state&D.Began),n=!(this.options.coherent?.length&&e.eventType&(G.End|G.Cancel));return super.attrTest(e)&&(t||n&&this.coherentTest(e)&&this.directionTest(e))}emit(e){this.pX=e.deltaX,this.pY=e.deltaY;let t=oe[e.direction].toLowerCase();t&&(e.additionalEvent=this.options.event+t),super.emit(e)}handleTrackpadEvent(e){e.isFirst&&(this.trackpadGesture=!e.srcEvent.ctrlKey,!this.trackpadGesture&&this.state&(D.Recognized|D.Cancelled|D.Failed)&&(this.state=D.Possible)),this.trackpadGesture&&(this.recognize(this.getTrackpadInput(e,{deltaX:-e.deltaX,deltaY:-e.deltaY,velocity:-e.velocity,velocityX:-e.velocityX,velocityY:-e.velocityY,overallVelocity:-e.overallVelocity,overallVelocityX:-e.overallVelocityX,overallVelocityY:-e.overallVelocityY})),e.isFinal&&(this.trackpadGesture=!1))}};var nR=["","start","move","end","cancel","in","out"],Mi=class extends Ci{constructor(e={}){super({enable:!0,event:"pinch",threshold:0,pointers:2,trackpad:!1,coherent:[],...e}),this.trackpadGesture=!1}getTouchAction(){return[Bn]}getEventNames(){return nR.map(e=>this.options.event+e)}attrTest(e){let t=!!this.options.coherent?.length,n=!!(this.state&D.Began),i=!(t&&e.eventType&(G.End|G.Cancel));return super.attrTest(e)&&(n||i&&(t?this.coherentTest(e):Math.abs(e.scale-1)>this.options.threshold))}emit(e){if(e.scale!==1){let t=e.scale<1?"in":"out";e.additionalEvent=this.options.event+t}super.emit(e)}handleTrackpadEvent(e){e.isFirst&&(this.trackpadGesture=e.srcEvent.ctrlKey,!this.trackpadGesture&&this.state&(D.Recognized|D.Cancelled|D.Failed)&&(this.state=D.Possible)),this.trackpadGesture&&(this.recognize(this.getTrackpadInput(e,{deltaX:0,deltaY:0,velocity:0,velocityX:0,velocityY:0,overallVelocity:0,overallVelocityX:0,overallVelocityY:0,scale:Math.exp(-e.deltaY/100)})),e.isFinal&&(this.trackpadGesture=!1))}};var Ht=class{constructor(e,t,n){this.element=e,this.callback=t,this.options=n}listen(e,t){t?this.element.addEventListener(e,this.handleEvent,{passive:!1}):this.element.removeEventListener(e,this.handleEvent)}};var hv=typeof navigator<"u"&&navigator.userAgent?navigator.userAgent.toLowerCase():"";var aR=hv.indexOf("firefox")!==-1,cR=40,lR=.25,Ll=class extends Ht{constructor(e,t,n){n.enable=n.enable??!1,super(e,t,n),this.handleEvent=i=>{if(!this.options.enable)return;let o=i.deltaY;globalThis.WheelEvent&&(aR&&i.deltaMode===globalThis.WheelEvent.DOM_DELTA_PIXEL&&(o/=globalThis.devicePixelRatio),i.deltaMode===globalThis.WheelEvent.DOM_DELTA_LINE&&(o*=cR)),i.shiftKey&&o&&(o=o*lR),this.callback({type:"wheel",center:{x:i.clientX,y:i.clientY},delta:-o,device:this.options.wheelSession?.device??"unknown",srcEvent:i,pointerType:"mouse",target:i.target})},n.enable&&(this.wheelSessionUnsubscribe=this.options.wheelSession?.on(()=>{}),this.listen("wheel",!0))}destroy(){this.listen("wheel",!1),this.wheelSessionUnsubscribe?.(),this.wheelSessionUnsubscribe=void 0}enableEventType(e,t){e==="wheel"&&this.options.enable!==t&&(this.options.enable=t,t&&!this.wheelSessionUnsubscribe&&(this.wheelSessionUnsubscribe=this.options.wheelSession?.on(()=>{})),this.listen("wheel",t),t||(this.wheelSessionUnsubscribe?.(),this.wheelSessionUnsubscribe=void 0))}};var uR=4.000244140625,pv=40,fR=0,dR=1,hR=40,mv=40,pR=120,mR={classificationDelay:32,endDelay:80},Al=class{constructor(e,t={}){this.subscriptions=new Map,this.session=null,this.classificationTimer=null,this.endTimer=null,this.pressedControlKeys=new Set,this.listeningForControlKeys=!1,this.handleEvent=n=>{if(!this.hasSubscribers)return"unknown";let i=yR(n,this.pressedControlKeys.size>0),o=this.session;if(o&&i.timeStamp-o.lastTimeStamp>=this.options.endDelay){if(this.end(),!this.hasSubscribers)return"unknown";o=null}o?(this.scheduleEnd(),this.addSample(o,i)):(o=this.startPendingSession(i),this.scheduleEnd());let{device:s}=o;return s==="unknown"&&(s=kp(o.samples,!1),s!=="unknown"&&this.begin(o,s)),s},this.finishClassification=()=>{if(this.classificationTimer=null,!this.session||this.session.device!=="unknown")return;let n=this.session,i=kp(n.samples,!0);this.begin(n,i==="unknown"?"mouse":i)},this.end=()=>{if(!this.session)return;if(this.session.device==="unknown"){let i=this.session,o=kp(i.samples,!0);this.begin(i,o==="unknown"?"mouse":o)}if(!this.session)return;let n=this.session;this.emit(G.End,n.lastEvent),this.reset()},this.handleKeyDown=n=>{n.key==="Control"&&this.pressedControlKeys.add(n.code||n.key)},this.handleKeyUp=n=>{n.key==="Control"&&(n.code?this.pressedControlKeys.delete(n.code):this.pressedControlKeys.clear())},this.handleWindowBlur=()=>{this.pressedControlKeys.clear()},this.element=e,this.options={...mR,...t},this.element?.addEventListener("wheel",this.handleEvent,{passive:!0})}get hasSubscribers(){return this.subscriptions.size>0}get device(){return this.session?.device??"unknown"}on(e){let t={listener:e};return this.subscriptions.set(e,t),this.updateControlKeyEventListeners(),()=>{this.subscriptions.get(e)===t&&this.off(e)}}off(e){this.subscriptions.delete(e),this.updateControlKeyEventListeners(),this.hasSubscribers||this.reset()}cancel(){let e=this.session;e&&e.device!=="unknown"&&this.emit(G.Cancel,e.lastEvent),this.reset()}destroy(){this.cancel(),this.subscriptions.clear(),this.updateControlKeyEventListeners(),this.element?.removeEventListener("wheel",this.handleEvent)}startPendingSession(e){let t={samples:[e],device:"unknown",firstTimeStamp:e.timeStamp,lastTimeStamp:e.timeStamp,totalDeltaX:e.deltaX,totalDeltaY:e.deltaY,velocityX:0,velocityY:0,lastEvent:e.event};return this.session=t,this.classificationTimer=globalThis.setTimeout(this.finishClassification,this.options.classificationDelay),t}addSample(e,t){if(e.samples.push(t),e.lastTimeStamp=t.timeStamp,e.lastEvent=t.event,e.totalDeltaX+=t.deltaX,e.totalDeltaY+=t.deltaY,e.device!=="unknown"){let n=e.samples[e.samples.length-2],i=t.timeStamp-n.timeStamp;e.velocityX=i>0?t.deltaX/i:0,e.velocityY=i>0?t.deltaY/i:0,this.emit(G.Move,t.event,{velocityX:e.velocityX,velocityY:e.velocityY})}}begin(e,t){e.device=t,this.clearClassificationTimer(),this.emit(G.Start,e.samples[0].event);let n=e.lastTimeStamp-e.firstTimeStamp;e.velocityX=n>0?e.totalDeltaX/n:0,e.velocityY=n>0?e.totalDeltaY/n:0,this.emit(G.Move,e.lastEvent,{velocityX:e.velocityX,velocityY:e.velocityY})}scheduleEnd(){this.clearEndTimer(),this.endTimer=globalThis.setTimeout(this.end,this.options.endDelay)}emit(e,t,n){let i=this.session;if(!i||i.device==="unknown")return;let o=e===G.Start,s=e===G.End||e===G.Cancel,a=o?i.firstTimeStamp:i.lastTimeStamp,c=o?0:Math.max(0,a-i.firstTimeStamp),l=o?0:i.totalDeltaX,u=o?0:i.totalDeltaY,f=c>0?l/c:0,h=c>0?u/c:0,p=o?0:n?.velocityX??i.velocityX,m=o?0:n?.velocityY??i.velocityY,g={eventType:e,device:i.device,srcEvent:t,timeStamp:a,center:{x:t.clientX,y:t.clientY},deltaX:l,deltaY:u,deltaTime:c,velocity:Math.abs(p)>Math.abs(m)?p:m,velocityX:p,velocityY:m,overallVelocity:Math.abs(f)>Math.abs(h)?f:h,overallVelocityX:f,overallVelocityY:h,isFirst:o,isFinal:s};for(let{listener:y}of[...this.subscriptions.values()])y(g)}reset(){this.clearClassificationTimer(),this.clearEndTimer(),this.session=null}clearClassificationTimer(){this.classificationTimer!==null&&(globalThis.clearTimeout(this.classificationTimer),this.classificationTimer=null)}clearEndTimer(){this.endTimer!==null&&(globalThis.clearTimeout(this.endTimer),this.endTimer=null)}updateControlKeyEventListeners(){let e=this.hasSubscribers,t=gR();!t||e===this.listeningForControlKeys||(this.listeningForControlKeys=e,e?(t.addEventListener("keydown",this.handleKeyDown,!0),t.addEventListener("keyup",this.handleKeyUp,!0),t.addEventListener("blur",this.handleWindowBlur)):(t.removeEventListener("keydown",this.handleKeyDown,!0),t.removeEventListener("keyup",this.handleKeyUp,!0),t.removeEventListener("blur",this.handleWindowBlur),this.pressedControlKeys.clear()))}};function gR(){return typeof window<"u"?window:globalThis.document?.defaultView}function yR(r,e){let t=r.deltaX,n=r.deltaY;return r.deltaMode===dR&&(t*=pv,n*=pv),{event:r,timeStamp:r.timeStamp,deltaX:t,deltaY:n,isControlKeyDown:e}}function kp(r,e){return r.some(({event:t,isControlKeyDown:n})=>t.ctrlKey&&!n)?"trackpad":r.some(({event:t})=>t.deltaMode!==fR)||r.some(_R)||r.every(({event:t})=>{let n=t.wheelDelta;return n!==void 0&&Math.abs(n)%40===0})?"mouse":r.some(({deltaX:t})=>t!==0)||r.length>1&&bR(r)?"trackpad":e?"mouse":"unknown"}function _R({event:r,deltaX:e,deltaY:t}){if(e!==0||t===0)return!1;let n=Math.abs(t/uR);if(Number.isInteger(n))return!0;let i=r.wheelDelta;return typeof i=="number"&&i!==0&&i%pR===0}function bR(r){for(let e=0;e<r.length;e++){let t=r[e];if(Math.abs(t.deltaX)>mv||Math.abs(t.deltaY)>mv||e>0&&t.timeStamp-r[e-1].timeStamp>hR)return!1}return!0}var gv=["mousedown","mousemove","mouseup","mouseover","mouseout","mouseenter","mouseleave"],Cl=class extends Ht{constructor(e,t,n){super(e,t,{enable:!0,...n}),this.handleEvent=o=>{this.handleOverEvent(o),this.handleOutEvent(o),this.handleEnterEvent(o),this.handleLeaveEvent(o),this.handleMoveEvent(o)},this.pressed=!1;let{enable:i=!1}=this.options;this.enableMoveEvent=i,this.enableLeaveEvent=i,this.enableEnterEvent=i,this.enableOutEvent=i,this.enableOverEvent=i,i&&gv.forEach(o=>this.listen(o,!0))}destroy(){gv.forEach(e=>this.listen(e,!1))}enableEventType(e,t){switch(e){case"pointermove":this.enableMoveEvent!==t&&(this.enableMoveEvent=t,this.listen("mousedown",t),this.listen("mousemove",t),this.listen("mouseup",t));break;case"pointerover":this.enableOverEvent!==t&&(this.enableOverEvent=t,this.listen("mouseover",t));break;case"pointerout":this.enableOutEvent!==t&&(this.enableOutEvent=t,this.listen("mouseout",t));break;case"pointerenter":this.enableEnterEvent!==t&&(this.enableEnterEvent=t,this.listen("mouseenter",t));break;case"pointerleave":this.enableLeaveEvent!==t&&(this.enableLeaveEvent=t,this.listen("mouseleave",t));break;default:}}handleOverEvent(e){this.enableOverEvent&&e.type==="mouseover"&&this._emit("pointerover",e)}handleOutEvent(e){this.enableOutEvent&&e.type==="mouseout"&&this._emit("pointerout",e)}handleEnterEvent(e){this.enableEnterEvent&&e.type==="mouseenter"&&this._emit("pointerenter",e)}handleLeaveEvent(e){this.enableLeaveEvent&&e.type==="mouseleave"&&this._emit("pointerleave",e)}handleMoveEvent(e){if(this.enableMoveEvent)switch(e.type){case"mousedown":e.button>=0&&(this.pressed=!0);break;case"mousemove":e.buttons===0&&(this.pressed=!1),this.pressed||this._emit("pointermove",e);break;case"mouseup":this.pressed=!1;break;default:}}_emit(e,t){this.callback({type:e,center:{x:t.clientX,y:t.clientY},srcEvent:t,pointerType:"mouse",target:t.target})}};var yv=["keydown","keyup"],Ml=class extends Ht{constructor(e,t,n){super(e,t,{enable:!0,tabIndex:0,...n}),this.handleEvent=o=>{let s=o.target||o.srcElement;s.tagName==="INPUT"&&s.type==="text"||s.tagName==="TEXTAREA"||(this.enableDownEvent&&o.type==="keydown"&&this.callback({type:"keydown",srcEvent:o,key:o.key,target:o.target}),this.enableUpEvent&&o.type==="keyup"&&this.callback({type:"keyup",srcEvent:o,key:o.key,target:o.target}))};let{enable:i=!1}=this.options;this.enableDownEvent=i,this.enableUpEvent=i,e.tabIndex=this.options.tabIndex,e.style.outline="none",i&&yv.forEach(o=>this.listen(o,!0))}destroy(){yv.forEach(e=>this.listen(e,!1))}enableEventType(e,t){e==="keydown"&&this.enableDownEvent!==t&&(this.enableDownEvent=t,this.listen(e,t)),e==="keyup"&&this.enableUpEvent!==t&&(this.enableUpEvent=t,this.listen(e,t))}};var Il=class extends Ht{constructor(e,t,n){n.enable=n.enable??!1,super(e,t,n),this.handleEvent=i=>{this.options.enable&&this.callback({type:"contextmenu",center:{x:i.clientX,y:i.clientY},srcEvent:i,pointerType:"mouse",target:i.target})},n.enable&&this.listen("contextmenu",!0)}destroy(){this.listen("contextmenu",!1)}enableEventType(e,t){e==="contextmenu"&&this.options.enable!==t&&(this.options.enable=t,this.listen("contextmenu",t))}};var xR={pointerdown:1,pointermove:2,pointerup:4,mousedown:1,mousemove:2,mouseup:4},vR=0,wR=1,ER=2,SR=1,PR=2,TR=4;function _v(r){let e=xR[r.srcEvent.type];if(!e)return null;let{buttons:t,button:n}=r.srcEvent,i=!1,o=!1,s=!1;return e===2?(i=!!(t&SR),o=!!(t&TR),s=!!(t&PR)):(i=n===vR,o=n===wR,s=n===ER),{leftButton:i,middleButton:o,rightButton:s}}function bv(r,e){let t=r.center;if(!t)return null;let n=e.getBoundingClientRect(),i=n.width/e.offsetWidth||1,o=n.height/e.offsetHeight||1,s={x:(t.x-n.left-e.clientLeft)/i,y:(t.y-n.top-e.clientTop)/o};return{center:t,offsetCenter:s}}var LR={srcElement:"root",priority:0},Rl=class{constructor(e,t){this.handleEvent=n=>{if(this.isEmpty())return;let i=this._normalizeEvent(n),o=n.srcEvent.target;for(;o&&o!==i.rootElement;){if(this._emit(i,o),i.handled)return;o=o.parentNode}this._emit(i,"root")},this.eventManager=e,this.recognizerName=t,this.handlers=[],this.handlersByElement=new Map,this._active=!1}isEmpty(){return!this._active}add(e,t,n,i=!1,o=!1){let{handlers:s,handlersByElement:a}=this,c={...LR,...n},l=a.get(c.srcElement);l||(l=[],a.set(c.srcElement,l));let u={type:e,handler:t,srcElement:c.srcElement,priority:c.priority};i&&(u.once=!0),o&&(u.passive=!0),s.push(u),this._active=this._active||!u.passive;let f=l.length-1;for(;f>=0&&!(l[f].priority>=u.priority);)f--;l.splice(f+1,0,u)}remove(e,t){let{handlers:n,handlersByElement:i}=this;for(let o=n.length-1;o>=0;o--){let s=n[o];if(s.type===e&&s.handler===t){n.splice(o,1);let a=i.get(s.srcElement);a.splice(a.indexOf(s),1),a.length===0&&i.delete(s.srcElement)}}this._active=n.some(o=>!o.passive)}_emit(e,t){let n=this.handlersByElement.get(t);if(n){let i=!1,o=()=>{e.handled=!0},s=()=>{e.handled=!0,i=!0},a=[];for(let c=0;c<n.length;c++){let{type:l,handler:u,once:f}=n[c];if(u({...e,type:l,stopPropagation:o,stopImmediatePropagation:s}),f&&a.push(n[c]),i)break}for(let c=0;c<a.length;c++){let{type:l,handler:u}=a[c];this.remove(l,u)}}}_normalizeEvent(e){let t=this.eventManager.getElement();return{...e,..._v(e),...bv(e,t),preventDefault:()=>{e.srcEvent.preventDefault()},stopImmediatePropagation:null,stopPropagation:null,handled:!1,rootElement:t}}};function AR(r){if("recognizer"in r)return r;let e,t=Array.isArray(r)?[...r]:[r];if(typeof t[0]=="function"){let n=t.shift(),i=t.shift()||{};e=new n(i)}else e=t.shift();return{recognizer:e,recognizeWith:typeof t[0]=="string"?[t[0]]:t[0],requireFailure:typeof t[1]=="string"?[t[1]]:t[1]}}var ws=class{constructor(e=null,t={}){if(this._onBasicInput=n=>{this.manager.emit(n.srcEvent.type,n)},this._onOtherEvent=n=>{this.manager.emit(n.type,n)},this.options={recognizers:[],events:{},touchAction:"compute",tabIndex:0,cssProps:{},...t},this.events=new Map,this.element=e,this.wheelSession=new Al(e),!!e){this.manager=new vs(e,this.options);for(let n of this.options.recognizers){let{recognizer:i,recognizeWith:o,requireFailure:s}=AR(n);this.manager.add(i),o&&i.recognizeWith(o),s&&i.requireFailure(s)}this.manager.on("hammer.input",this._onBasicInput),this.wheelInput=new Ll(e,this._onOtherEvent,{enable:!1,wheelSession:this.wheelSession}),this.moveInput=new Cl(e,this._onOtherEvent,{enable:!1}),this.keyInput=new Ml(e,this._onOtherEvent,{enable:!1,tabIndex:t.tabIndex}),this.contextmenuInput=new Il(e,this._onOtherEvent,{enable:!1}),this.on(this.options.events)}}getElement(){return this.element}destroy(){if(!this.element){this.wheelSession.destroy();return}this.wheelInput.destroy(),this.wheelSession.destroy(),this.moveInput.destroy(),this.keyInput.destroy(),this.contextmenuInput.destroy(),this.manager.destroy()}on(e,t,n){this._addEventHandler(e,t,n,!1)}once(e,t,n){this._addEventHandler(e,t,n,!0)}watch(e,t,n){this._addEventHandler(e,t,n,!1,!0)}off(e,t){this._removeEventHandler(e,t)}emit(e){this.manager?.emit(e.type,e)}_toggleRecognizer(e,t){let{manager:n}=this;if(!n)return;let i=n.get(e);i&&(i.set({enable:t,wheelSession:this.wheelSession}),n.touchAction.update()),this.wheelInput?.enableEventType(e,t),this.moveInput?.enableEventType(e,t),this.keyInput?.enableEventType(e,t),this.contextmenuInput?.enableEventType(e,t)}_addEventHandler(e,t,n,i,o){if(typeof e!="string"){n=t;for(let[l,u]of Object.entries(e))this._addEventHandler(l,u,n,i,o);return}let{manager:s,events:a}=this;if(!s)return;let c=a.get(e);if(!c){let l=this._getRecognizerName(e)||e;c=new Rl(this,l),a.set(e,c),s&&s.on(e,c.handleEvent)}c.add(e,t,n,i,o),c.isEmpty()||this._toggleRecognizer(c.recognizerName,!0)}_removeEventHandler(e,t){if(typeof e!="string"){for(let[o,s]of Object.entries(e))this._removeEventHandler(o,s);return}let{events:n}=this,i=n.get(e);if(i&&(i.remove(e,t),i.isEmpty())){let{recognizerName:o}=i,s=!1;for(let a of n.values())if(a.recognizerName===o&&!a.isEmpty()){s=!0;break}s||this._toggleRecognizer(o,!1)}}_getRecognizerName(e){return this.manager.recognizers.find(t=>t.getEventNames().includes(e))?.options.event}};var Dp={DEFAULT:"default",LNGLAT:"lnglat",METER_OFFSETS:"meter-offsets",LNGLAT_OFFSETS:"lnglat-offsets",CARTESIAN:"cartesian"};Object.defineProperty(Dp,"IDENTITY",{get:()=>($.deprecated("COORDINATE_SYSTEM.IDENTITY","COORDINATE_SYSTEM.CARTESIAN")(),Dp.CARTESIAN)});var Se={WEB_MERCATOR:1,GLOBE:2,WEB_MERCATOR_AUTO_OFFSET:4,IDENTITY:0},pt={common:0,meters:1,pixels:2},Ii={click:"onClick",dblclick:"onClick",panstart:"onDragStart",panmove:"onDrag",panend:"onDragEnd"},Np={multipan:[Gr,{threshold:10,pointers:2,trackpad:!0}],pinch:[Mi,{trackpad:!0},null,["multipan"]],pan:[Gr,{threshold:1},["pinch"],["multipan"]],dblclick:[kn,{event:"dblclick",taps:2,enable:!1}],dblclickdrag:[Ai,{event:"dblclickdrag",enable:!1},["dblclick"],null],click:[kn,{event:"click"},["dblclickdrag"],["dblclick","dblclickdrag"]]};function CR(r,e){if(r===e)return!0;if(Array.isArray(r)){let t=r.length;if(!e||e.length!==t)return!1;for(let n=0;n<t;n++)if(r[n]!==e[n])return!1;return!0}return!1}function Yt(r){let e={},t;return n=>{for(let i in n)if(!CR(n[i],e[i])){t=r(n),e=n;break}return t}}var xv=[0,0,0,0],MR=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,0],vv=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1],IR=[0,0,0],wv=[0,0,0],RR={default:-1,cartesian:0,lnglat:1,"meter-offsets":2,"lnglat-offsets":3};function Dn(r){let e=RR[r];if(e===void 0)throw new Error(`Invalid coordinateSystem: ${r}`);return e}var BR=Yt(kR);function Fp(r,e,t=wv){t.length<3&&(t=[t[0],t[1],0]);let n=t,i,o=!0;switch(e==="lnglat-offsets"||e==="meter-offsets"?i=t:i=r.isGeospatial?[Math.fround(r.longitude),Math.fround(r.latitude),0]:null,r.projectionMode){case Se.WEB_MERCATOR:(e==="lnglat"||e==="cartesian")&&(i=[0,0,0],o=!1);break;case Se.WEB_MERCATOR_AUTO_OFFSET:e==="lnglat"?n=i:e==="cartesian"&&(n=[Math.fround(r.center[0]),Math.fround(r.center[1]),0],i=r.unprojectPosition(n),n[0]-=t[0],n[1]-=t[1],n[2]-=t[2]);break;case Se.IDENTITY:n=r.position.map(Math.fround),n[2]=n[2]||0;break;case Se.GLOBE:o=!1,i=null;break;default:o=!1}return{geospatialOrigin:i,shaderCoordinateOrigin:n,offsetMode:o}}function OR(r,e,t){let{viewMatrixUncentered:n,projectionMatrix:i}=r,{viewMatrix:o,viewProjectionMatrix:s}=r,a=xv,c=xv,l=r.cameraPosition,{geospatialOrigin:u,shaderCoordinateOrigin:f,offsetMode:h}=Fp(r,e,t);return h&&(c=r.projectPosition(u||f),l=[l[0]-c[0],l[1]-c[1],l[2]-c[2]],c[3]=1,a=Et.transformMat4([],c,s),o=n||o,s=be.multiply([],i,o),s=be.multiply([],s,MR)),{viewMatrix:o,viewProjectionMatrix:s,projectionCenter:a,originCommon:c,cameraPosCommon:l,shaderCoordinateOrigin:f,geospatialOrigin:u}}function Ev({viewport:r,devicePixelRatio:e=1,modelMatrix:t=null,coordinateSystem:n="default",coordinateOrigin:i=wv,autoWrapLongitude:o=!1}){n==="default"&&(n=r.isGeospatial?"lnglat":"cartesian");let s=BR({viewport:r,devicePixelRatio:e,coordinateSystem:n,coordinateOrigin:i});return s.wrapLongitude=o,s.modelMatrix=t||vv,s}function kR({viewport:r,devicePixelRatio:e,coordinateSystem:t,coordinateOrigin:n}){let{projectionCenter:i,viewProjectionMatrix:o,originCommon:s,cameraPosCommon:a,shaderCoordinateOrigin:c,geospatialOrigin:l}=OR(r,t,n),u=r.getDistanceScales(),f=[r.width*e,r.height*e],h=Et.transformMat4([],[0,0,-r.focalDistance,1],r.projectionMatrix)[3]||1,p={coordinateSystem:Dn(t),projectionMode:r.projectionMode,coordinateOrigin:c,commonOrigin:s.slice(0,3),center:i,pseudoMeters:!!r._pseudoMeters,viewportSize:f,devicePixelRatio:e,focalDistance:h,commonUnitsPerMeter:u.unitsPerMeter,commonUnitsPerWorldUnit:u.unitsPerMeter,commonUnitsPerWorldUnit2:IR,scale:r.scale,wrapLongitude:!1,viewProjectionMatrix:o,modelMatrix:vv,cameraPosition:a};if(l){let m=r.getDistanceScales(l);switch(t){case"meter-offsets":p.commonUnitsPerWorldUnit=m.unitsPerMeter,p.commonUnitsPerWorldUnit2=m.unitsPerMeter2;break;case"lnglat":case"lnglat-offsets":r._pseudoMeters||(p.commonUnitsPerMeter=m.unitsPerMeter),p.commonUnitsPerWorldUnit=m.unitsPerDegree,p.commonUnitsPerWorldUnit2=m.unitsPerDegree2;break;case"cartesian":p.commonUnitsPerWorldUnit=[1,1,m.unitsPerMeter[2]],p.commonUnitsPerWorldUnit2=[0,0,m.unitsPerMeter2[2]];break;default:break}}if(r.projectionMode===Se.GLOBE&&t==="meter-offsets"){let y=n[0]*Math.PI/180,x=n[1]*Math.PI/180,v=Math.cos(x),_=((n[2]||0)/6370972+1)*256;p.commonOrigin=[Math.sin(y)*v*_,-Math.cos(y)*v*_,Math.sin(x)*_]}return p}var DR=["default","lnglat","meter-offsets","lnglat-offsets","cartesian"],NR=DR.map(r=>`const COORDINATE_SYSTEM_${r.toUpperCase().replaceAll("-","_")}: i32 = ${Dn(r)};`).join(""),FR=Object.keys(Se).map(r=>`const PROJECTION_MODE_${r}: i32 = ${Se[r]};`).join(""),UR=Object.keys(pt).map(r=>`const UNIT_${r.toUpperCase()}: i32 = ${pt[r]};`).join(""),GR=`${NR}
${FR}
${UR}

const TILE_SIZE: f32 = 512.0;
const PI: f32 = 3.1415926536;
const WORLD_SCALE: f32 = TILE_SIZE / (PI * 2.0);
const ZERO_64_LOW: vec3<f32> = vec3<f32>(0.0, 0.0, 0.0);
const EARTH_RADIUS: f32 = 6370972.0; // meters
const GLOBE_RADIUS: f32 = 256.0;

// -----------------------------------------------------------------------------
// Uniform block (converted from GLSL uniform block)
// -----------------------------------------------------------------------------
struct ProjectUniforms {
  wrapLongitude: i32,
  coordinateSystem: i32,
  commonUnitsPerMeter: vec3<f32>,
  projectionMode: i32,
  scale: f32,
  commonUnitsPerWorldUnit: vec3<f32>,
  commonUnitsPerWorldUnit2: vec3<f32>,
  center: vec4<f32>,
  modelMatrix: mat4x4<f32>,
  viewProjectionMatrix: mat4x4<f32>,
  viewportSize: vec2<f32>,
  devicePixelRatio: f32,
  focalDistance: f32,
  cameraPosition: vec3<f32>,
  coordinateOrigin: vec3<f32>,
  commonOrigin: vec3<f32>,
  pseudoMeters: i32,
};

@group(0) @binding(auto)
var<uniform> project: ProjectUniforms;

// -----------------------------------------------------------------------------
// Geometry data shared across the project helpers.
// The active layer shader is responsible for populating this private module
// state before calling the project functions below.
// -----------------------------------------------------------------------------

// Structure to carry additional geometry data used by deck.gl filters.
struct Geometry {
  worldPosition: vec3<f32>,
  worldPositionAlt: vec3<f32>,
  position: vec4<f32>,
  normal: vec3<f32>,
  uv: vec2<f32>,
  pickingColor: vec3<f32>,
};

var<private> geometry: Geometry;
`,Sv=`${GR}

// -----------------------------------------------------------------------------
// Functions
// -----------------------------------------------------------------------------

// Returns an adjustment factor for commonUnitsPerMeter
fn _project_size_at_latitude(lat: f32) -> f32 {
  let y = clamp(lat, -89.9, 89.9);
  return 1.0 / cos(radians(y));
}

// Overloaded version: scales a value in meters at a given latitude.
fn _project_size_at_latitude_m(meters: f32, lat: f32) -> f32 {
  return meters * project.commonUnitsPerMeter.z * _project_size_at_latitude(lat);
}

// Computes a non-linear scale factor based on geometry.
// (Note: This function relies on "geometry" being provided.)
fn project_size() -> f32 {
  if (project.projectionMode == PROJECTION_MODE_WEB_MERCATOR &&
      project.coordinateSystem == COORDINATE_SYSTEM_LNGLAT &&
      project.pseudoMeters == 0) {
    if (geometry.position.w == 0.0) {
      return _project_size_at_latitude(geometry.worldPosition.y);
    }
    let y: f32 = geometry.position.y / TILE_SIZE * 2.0 - 1.0;
    let y2 = y * y;
    let y4 = y2 * y2;
    let y6 = y4 * y2;
    return 1.0 + 4.9348 * y2 + 4.0587 * y4 + 1.5642 * y6;
  }
  return 1.0;
}

// Overloads to scale offsets (meters to world units)
fn project_size_float(meters: f32) -> f32 {
  return meters * project.commonUnitsPerMeter.z * project_size();
}

fn project_size_vec2(meters: vec2<f32>) -> vec2<f32> {
  return meters * project.commonUnitsPerMeter.xy * project_size();
}

fn project_size_vec3(meters: vec3<f32>) -> vec3<f32> {
  return meters * project.commonUnitsPerMeter * project_size();
}

fn project_size_vec4(meters: vec4<f32>) -> vec4<f32> {
  return vec4<f32>(meters.xyz * project.commonUnitsPerMeter, meters.w);
}

// Returns a rotation matrix aligning the z\u2011axis with the given up vector.
fn project_get_orientation_matrix(up: vec3<f32>) -> mat3x3<f32> {
  let uz = normalize(up);
  let ux = select(
    vec3<f32>(1.0, 0.0, 0.0),
    normalize(vec3<f32>(uz.y, -uz.x, 0.0)),
    abs(uz.z) == 1.0
  );
  let uy = cross(uz, ux);
  return mat3x3<f32>(ux, uy, uz);
}

// Since WGSL does not support "out" parameters, we return a struct.
struct RotationResult {
  needsRotation: bool,
  transform: mat3x3<f32>,
};

fn project_needs_rotation(commonPosition: vec3<f32>) -> RotationResult {
  if (project.projectionMode == PROJECTION_MODE_GLOBE) {
    return RotationResult(true, project_get_orientation_matrix(commonPosition));
  } else {
    return RotationResult(false, mat3x3<f32>());  // identity alternative if needed
  };
}

// Projects a normal vector from the current coordinate system to world space.
fn project_normal(vector: vec3<f32>) -> vec3<f32> {
  let normal_modelspace = project.modelMatrix * vec4<f32>(vector, 0.0);
  var n = normalize(normal_modelspace.xyz * project.commonUnitsPerMeter);
  let rotResult = project_needs_rotation(geometry.position.xyz);
  if (rotResult.needsRotation) {
    n = rotResult.transform * n;
  }
  return n;
}

// Applies a scale offset based on y-offset (dy)
fn project_offset_(offset: vec4<f32>) -> vec4<f32> {
  let dy: f32 = offset.y;
  let commonUnitsPerWorldUnit = project.commonUnitsPerWorldUnit + project.commonUnitsPerWorldUnit2 * dy;
  return vec4<f32>(offset.xyz * commonUnitsPerWorldUnit, offset.w);
}

// Projects lng/lat coordinates to a unit tile [0,1]
fn project_mercator_(lnglat: vec2<f32>) -> vec2<f32> {
  var x = lnglat.x;
  if (project.wrapLongitude != 0) {
    x = ((x + 180.0) % 360.0) - 180.0;
  }
  let y = clamp(lnglat.y, -89.9, 89.9);
  return vec2<f32>(
    radians(x) + PI,
    PI + log(tan_fp32(PI * 0.25 + radians(y) * 0.5))
  ) * WORLD_SCALE;
}

// Projects lng/lat/z coordinates for a globe projection.
fn project_globe_(lnglatz: vec3<f32>) -> vec3<f32> {
  let lambda = radians(lnglatz.x);
  let phi = radians(lnglatz.y);
  let cosPhi = cos(phi);
  let D = (lnglatz.z / EARTH_RADIUS + 1.0) * GLOBE_RADIUS;
  return vec3<f32>(
    sin(lambda) * cosPhi,
    -cos(lambda) * cosPhi,
    sin(phi)
  ) * D;
}

// Projects positions (with an optional 64-bit low part) from the input
// coordinate system to the common space.
fn project_position_vec4_f64(position: vec4<f32>, position64Low: vec3<f32>) -> vec4<f32> {
  var position_world = project.modelMatrix * position;

  // Work around for a Mac+NVIDIA bug:
  if (project.projectionMode == PROJECTION_MODE_WEB_MERCATOR) {
    if (project.coordinateSystem == COORDINATE_SYSTEM_LNGLAT) {
      return vec4<f32>(
        project_mercator_(position_world.xy),
        _project_size_at_latitude_m(position_world.z, position_world.y),
        position_world.w
      );
    }
    if (project.coordinateSystem == COORDINATE_SYSTEM_CARTESIAN) {
      position_world = vec4f(position_world.xyz + project.coordinateOrigin, position_world.w);
    }
  }
  if (project.projectionMode == PROJECTION_MODE_GLOBE) {
    if (project.coordinateSystem == COORDINATE_SYSTEM_LNGLAT) {
      return vec4<f32>(
        project_globe_(position_world.xyz),
        position_world.w
      );
    }
    if (project.coordinateSystem == COORDINATE_SYSTEM_METER_OFFSETS) {
      let enuMatrix = project_get_orientation_matrix(project.commonOrigin);
      let metersToCommon = GLOBE_RADIUS / EARTH_RADIUS;
      let offsetCommon = (enuMatrix * vec3<f32>(-position_world.x, -position_world.y, position_world.z)) * metersToCommon;
      return vec4<f32>(project.commonOrigin + offsetCommon, position_world.w);
    }
  }
  if (project.projectionMode == PROJECTION_MODE_WEB_MERCATOR_AUTO_OFFSET) {
    if (project.coordinateSystem == COORDINATE_SYSTEM_LNGLAT) {
      if (abs(position_world.y - project.coordinateOrigin.y) > 0.25) {
        return vec4<f32>(
          project_mercator_(position_world.xy) - project.commonOrigin.xy,
          project_size_float(position_world.z),
          position_world.w
        );
      }
    }
  }
  if (project.projectionMode == PROJECTION_MODE_IDENTITY ||
      (project.projectionMode == PROJECTION_MODE_WEB_MERCATOR_AUTO_OFFSET &&
       (project.coordinateSystem == COORDINATE_SYSTEM_LNGLAT ||
        project.coordinateSystem == COORDINATE_SYSTEM_CARTESIAN))) {
    position_world = vec4f(position_world.xyz - project.coordinateOrigin, position_world.w);
  }

  return project_offset_(position_world) +
         project_offset_(project.modelMatrix * vec4<f32>(position64Low, 0.0));
}

// Overloaded versions for different input types.
fn project_position_vec4_f32(position: vec4<f32>) -> vec4<f32> {
  return project_position_vec4_f64(position, ZERO_64_LOW);
}

fn project_position_vec3_f64(position: vec3<f32>, position64Low: vec3<f32>) -> vec3<f32> {
  let projected_position = project_position_vec4_f64(vec4<f32>(position, 1.0), position64Low);
  return projected_position.xyz;
}

fn project_position_vec3_f32(position: vec3<f32>) -> vec3<f32> {
  let projected_position = project_position_vec4_f64(vec4<f32>(position, 1.0), ZERO_64_LOW);
  return projected_position.xyz;
}

fn project_position_vec2_f32(position: vec2<f32>) -> vec2<f32> {
  let projected_position = project_position_vec4_f64(vec4<f32>(position, 0.0, 1.0), ZERO_64_LOW);
  return projected_position.xy;
}

// Transforms a common space position to clip space.
fn project_common_position_to_clipspace_with_projection(position: vec4<f32>, viewProjectionMatrix: mat4x4<f32>, center: vec4<f32>) -> vec4<f32> {
  var clipPosition = viewProjectionMatrix * position + center;
  // deck.gl projection matrices use WebGL's [-w, w] depth range; WebGPU clips z to [0, w].
  clipPosition.z = (clipPosition.z + clipPosition.w) * 0.5;
  return clipPosition;
}

// Uses the project viewProjectionMatrix and center.
fn project_common_position_to_clipspace(position: vec4<f32>) -> vec4<f32> {
  return project_common_position_to_clipspace_with_projection(position, project.viewProjectionMatrix, project.center);
}

// Returns a clip space offset corresponding to a given number of screen pixels.
fn project_pixel_size_to_clipspace(pixels: vec2<f32>) -> vec2<f32> {
  let offset = pixels / project.viewportSize * project.devicePixelRatio * 2.0;
  return offset * project.focalDistance;
}

fn project_meter_size_to_pixel(meters: f32) -> f32 {
  return project_size_float(meters) * project.scale;
}

fn project_unit_size_to_pixel(size: f32, unit: i32) -> f32 {
  if (unit == UNIT_METERS) {
    return project_meter_size_to_pixel(size);
  } else if (unit == UNIT_COMMON) {
    return size * project.scale;
  }
  // UNIT_PIXELS: no scaling applied.
  return size;
}

fn project_pixel_size_float(pixels: f32) -> f32 {
  return pixels / project.scale;
}

fn project_pixel_size_vec2(pixels: vec2<f32>) -> vec2<f32> {
  return pixels / project.scale;
}
`;var zR=["default","lnglat","meter-offsets","lnglat-offsets","cartesian"],$R=zR.map(r=>`const int COORDINATE_SYSTEM_${r.toUpperCase().replaceAll("-","_")} = ${Dn(r)};`).join(""),VR=Object.keys(Se).map(r=>`const int PROJECTION_MODE_${r} = ${Se[r]};`).join(""),WR=Object.keys(pt).map(r=>`const int UNIT_${r.toUpperCase()} = ${pt[r]};`).join(""),Pv=`${$R}
${VR}
${WR}
layout(std140) uniform projectUniforms {
bool wrapLongitude;
int coordinateSystem;
vec3 commonUnitsPerMeter;
int projectionMode;
float scale;
vec3 commonUnitsPerWorldUnit;
vec3 commonUnitsPerWorldUnit2;
vec4 center;
mat4 modelMatrix;
mat4 viewProjectionMatrix;
vec2 viewportSize;
float devicePixelRatio;
float focalDistance;
vec3 cameraPosition;
vec3 coordinateOrigin;
vec3 commonOrigin;
bool pseudoMeters;
} project;
const float TILE_SIZE = 512.0;
const float PI = 3.1415926536;
const float WORLD_SCALE = TILE_SIZE / (PI * 2.0);
const vec3 ZERO_64_LOW = vec3(0.0);
const float EARTH_RADIUS = 6370972.0;
const float GLOBE_RADIUS = 256.0;
float project_size_at_latitude(float lat) {
float y = clamp(lat, -89.9, 89.9);
return 1.0 / cos(radians(y));
}
float project_size() {
if (project.projectionMode == PROJECTION_MODE_WEB_MERCATOR &&
project.coordinateSystem == COORDINATE_SYSTEM_LNGLAT &&
project.pseudoMeters == false) {
if (geometry.position.w == 0.0) {
return project_size_at_latitude(geometry.worldPosition.y);
}
float y = geometry.position.y / TILE_SIZE * 2.0 - 1.0;
float y2 = y * y;
float y4 = y2 * y2;
float y6 = y4 * y2;
return 1.0 + 4.9348 * y2 + 4.0587 * y4 + 1.5642 * y6;
}
return 1.0;
}
float project_size_at_latitude(float meters, float lat) {
return meters * project.commonUnitsPerMeter.z * project_size_at_latitude(lat);
}
float project_size(float meters) {
return meters * project.commonUnitsPerMeter.z * project_size();
}
vec2 project_size(vec2 meters) {
return meters * project.commonUnitsPerMeter.xy * project_size();
}
vec3 project_size(vec3 meters) {
return meters * project.commonUnitsPerMeter * project_size();
}
vec4 project_size(vec4 meters) {
return vec4(meters.xyz * project.commonUnitsPerMeter, meters.w);
}
mat3 project_get_orientation_matrix(vec3 up) {
vec3 uz = normalize(up);
vec3 ux = abs(uz.z) == 1.0 ? vec3(1.0, 0.0, 0.0) : normalize(vec3(uz.y, -uz.x, 0));
vec3 uy = cross(uz, ux);
return mat3(ux, uy, uz);
}
bool project_needs_rotation(vec3 commonPosition, out mat3 transform) {
if (project.projectionMode == PROJECTION_MODE_GLOBE) {
transform = project_get_orientation_matrix(commonPosition);
return true;
}
return false;
}
vec3 project_normal(vec3 vector) {
vec4 normal_modelspace = project.modelMatrix * vec4(vector, 0.0);
vec3 n = normalize(normal_modelspace.xyz * project.commonUnitsPerMeter);
mat3 rotation;
if (project_needs_rotation(geometry.position.xyz, rotation)) {
n = rotation * n;
}
return n;
}
vec4 project_offset_(vec4 offset) {
float dy = offset.y;
vec3 commonUnitsPerWorldUnit = project.commonUnitsPerWorldUnit + project.commonUnitsPerWorldUnit2 * dy;
return vec4(offset.xyz * commonUnitsPerWorldUnit, offset.w);
}
vec2 project_mercator_(vec2 lnglat) {
float x = lnglat.x;
if (project.wrapLongitude) {
x = mod(x + 180., 360.0) - 180.;
}
float y = clamp(lnglat.y, -89.9, 89.9);
return vec2(
radians(x) + PI,
PI + log(tan_fp32(PI * 0.25 + radians(y) * 0.5))
) * WORLD_SCALE;
}
vec3 project_globe_(vec3 lnglatz) {
float lambda = radians(lnglatz.x);
float phi = radians(lnglatz.y);
float cosPhi = cos(phi);
float D = (lnglatz.z / EARTH_RADIUS + 1.0) * GLOBE_RADIUS;
return vec3(
sin(lambda) * cosPhi,
-cos(lambda) * cosPhi,
sin(phi)
) * D;
}
vec4 project_position(vec4 position, vec3 position64Low) {
vec4 position_world = project.modelMatrix * position;
if (project.projectionMode == PROJECTION_MODE_WEB_MERCATOR) {
if (project.coordinateSystem == COORDINATE_SYSTEM_LNGLAT) {
return vec4(
project_mercator_(position_world.xy),
project_size_at_latitude(position_world.z, position_world.y),
position_world.w
);
}
if (project.coordinateSystem == COORDINATE_SYSTEM_CARTESIAN) {
position_world.xyz += project.coordinateOrigin;
}
}
if (project.projectionMode == PROJECTION_MODE_GLOBE) {
if (project.coordinateSystem == COORDINATE_SYSTEM_LNGLAT) {
return vec4(
project_globe_(position_world.xyz),
position_world.w
);
}
if (project.coordinateSystem == COORDINATE_SYSTEM_METER_OFFSETS) {
mat3 enuMatrix = project_get_orientation_matrix(project.commonOrigin);
float metersToCommon = GLOBE_RADIUS / EARTH_RADIUS;
vec3 offsetCommon = (enuMatrix * vec3(-position_world.xy, position_world.z)) * metersToCommon;
return vec4(project.commonOrigin + offsetCommon, position_world.w);
}
}
if (project.projectionMode == PROJECTION_MODE_WEB_MERCATOR_AUTO_OFFSET) {
if (project.coordinateSystem == COORDINATE_SYSTEM_LNGLAT) {
if (abs(position_world.y - project.coordinateOrigin.y) > 0.25) {
return vec4(
project_mercator_(position_world.xy) - project.commonOrigin.xy,
project_size(position_world.z),
position_world.w
);
}
}
}
if (project.projectionMode == PROJECTION_MODE_IDENTITY ||
(project.projectionMode == PROJECTION_MODE_WEB_MERCATOR_AUTO_OFFSET &&
(project.coordinateSystem == COORDINATE_SYSTEM_LNGLAT ||
project.coordinateSystem == COORDINATE_SYSTEM_CARTESIAN))) {
position_world.xyz -= project.coordinateOrigin;
}
return project_offset_(position_world) + project_offset_(project.modelMatrix * vec4(position64Low, 0.0));
}
vec4 project_position(vec4 position) {
return project_position(position, ZERO_64_LOW);
}
vec3 project_position(vec3 position, vec3 position64Low) {
vec4 projected_position = project_position(vec4(position, 1.0), position64Low);
return projected_position.xyz;
}
vec3 project_position(vec3 position) {
vec4 projected_position = project_position(vec4(position, 1.0), ZERO_64_LOW);
return projected_position.xyz;
}
vec2 project_position(vec2 position) {
vec4 projected_position = project_position(vec4(position, 0.0, 1.0), ZERO_64_LOW);
return projected_position.xy;
}
vec4 project_common_position_to_clipspace(vec4 position, mat4 viewProjectionMatrix, vec4 center) {
return viewProjectionMatrix * position + center;
}
vec4 project_common_position_to_clipspace(vec4 position) {
return project_common_position_to_clipspace(position, project.viewProjectionMatrix, project.center);
}
vec2 project_pixel_size_to_clipspace(vec2 pixels) {
vec2 offset = pixels / project.viewportSize * project.devicePixelRatio * 2.0;
return offset * project.focalDistance;
}
float project_size_to_pixel(float meters) {
return project_size(meters) * project.scale;
}
vec2 project_size_to_pixel(vec2 meters) {
return project_size(meters) * project.scale;
}
float project_size_to_pixel(float size, int unit) {
if (unit == UNIT_METERS) return project_size_to_pixel(size);
if (unit == UNIT_COMMON) return size * project.scale;
return size;
}
float project_pixel_size(float pixels) {
return pixels / project.scale;
}
vec2 project_pixel_size(vec2 pixels) {
return pixels / project.scale;
}
`;var jR={};function HR(r=jR){return"viewport"in r?Ev(r):{}}var Ri={name:"project",dependencies:[Mn,wl],source:Sv,vs:Pv,getUniforms:HR,uniformTypes:{wrapLongitude:"f32",coordinateSystem:"i32",commonUnitsPerMeter:"vec3<f32>",projectionMode:"i32",scale:"f32",commonUnitsPerWorldUnit:"vec3<f32>",commonUnitsPerWorldUnit2:"vec3<f32>",center:"vec4<f32>",modelMatrix:"mat4x4<f32>",viewProjectionMatrix:"mat4x4<f32>",viewportSize:"vec2<f32>",devicePixelRatio:"f32",focalDistance:"f32",cameraPosition:"vec3<f32>",coordinateOrigin:"vec3<f32>",commonOrigin:"vec3<f32>",pseudoMeters:"f32"}};var YR=`// Define a structure to hold both the clip-space position and the common position.
struct ProjectResult {
  clipPosition: vec4<f32>,
  commonPosition: vec4<f32>,
};

// This function mimics the GLSL version with the 'out' parameter by returning both values.
fn project_position_to_clipspace_and_commonspace(
    position: vec3<f32>,
    position64Low: vec3<f32>,
    offset: vec3<f32>
) -> ProjectResult {
  // Compute the projected position.
  let projectedPosition: vec3<f32> = project_position_vec3_f64(position, position64Low);

  // Start with the provided offset.
  var finalOffset: vec3<f32> = offset;

  // Get whether a rotation is needed and the rotation matrix.
  let rotationResult = project_needs_rotation(projectedPosition);

  // If rotation is needed, update the offset.
  if (rotationResult.needsRotation) {
    finalOffset = rotationResult.transform * offset;
  }

  // Compute the common position.
  let commonPosition: vec4<f32> = vec4<f32>(projectedPosition + finalOffset, 1.0);

  // Convert to clip-space.
  let clipPosition: vec4<f32> = project_common_position_to_clipspace(commonPosition);

  return ProjectResult(clipPosition, commonPosition);
}

// A convenience overload that returns only the clip-space position.
fn project_position_to_clipspace(
    position: vec3<f32>,
    position64Low: vec3<f32>,
    offset: vec3<f32>
) -> vec4<f32> {
  return project_position_to_clipspace_and_commonspace(position, position64Low, offset).clipPosition;
}
`,qR=`vec4 project_position_to_clipspace(
  vec3 position, vec3 position64Low, vec3 offset, out vec4 commonPosition
) {
  vec3 projectedPosition = project_position(position, position64Low);
  mat3 rotation;
  if (project_needs_rotation(projectedPosition, rotation)) {
    // offset is specified as ENU
    // when in globe projection, rotate offset so that the ground alighs with the surface of the globe
    offset = rotation * offset;
  }
  commonPosition = vec4(projectedPosition + offset, 1.0);
  return project_common_position_to_clipspace(commonPosition);
}

vec4 project_position_to_clipspace(
  vec3 position, vec3 position64Low, vec3 offset
) {
  vec4 commonPosition;
  return project_position_to_clipspace(position, position64Low, offset, commonPosition);
}
`,zr={name:"project32",dependencies:[Ri],source:YR,vs:qR};Ee();Ee();function Up(){return[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]}function $r(r,e){let t=Et.transformMat4([],e,r);return Et.scale(t,t,1/t[3]),t}function Es(r,e,t){return r<e?e:r>t?t:r}function XR(r){return Math.log(r)*Math.LOG2E}var Ss=Math.log2||XR;Ee();function Pt(r,e){if(!r)throw new Error(e||"@math.gl/web-mercator: assertion failed.")}var Tt=Math.PI,Tv=Tt/4,mt=Tt/180,Gp=180/Tt,Bi=512,Bl=4003e4,Oi=85.051129,Lv=1.5;function zp(r){return Ss(r)}function gt(r){let[e,t]=r;Pt(Number.isFinite(e)),Pt(Number.isFinite(t)&&t>=-90&&t<=90,"invalid latitude");let n=e*mt,i=t*mt,o=Bi*(n+Tt)/(2*Tt),s=Bi*(Tt+Math.log(Math.tan(Tv+i*.5)))/(2*Tt);return[o,s]}function it(r){let[e,t]=r,n=e/Bi*(2*Tt)-Tt,i=2*(Math.atan(Math.exp(t/Bi*(2*Tt)-Tt))-Tv);return[n*Gp,i*Gp]}function $p(r){let{latitude:e}=r;Pt(Number.isFinite(e));let t=Math.cos(e*mt);return zp(Bl*t)-9}function Ps(r){let e=Math.cos(r*mt);return Bi/Bl/e}function ki(r){let{latitude:e,longitude:t,highPrecision:n=!1}=r;Pt(Number.isFinite(e)&&Number.isFinite(t));let i=Bi,o=Math.cos(e*mt),s=i/360,a=s/o,c=i/Bl/o,l={unitsPerMeter:[c,c,c],metersPerUnit:[1/c,1/c,1/c],unitsPerDegree:[s,a,c],degreesPerUnit:[1/s,1/a,1/c]};if(n){let u=mt*Math.tan(e*mt)/o,f=s*u/2,h=i/Bl*u,p=h/a*c;l.unitsPerDegree2=[0,f,h],l.unitsPerMeter2=[p,0,p]}return l}function Ts(r,e){let[t,n,i]=r,[o,s,a]=e,{unitsPerMeter:c,unitsPerMeter2:l}=ki({longitude:t,latitude:n,highPrecision:!0}),u=gt(r);u[0]+=o*(c[0]+l[0]*s),u[1]+=s*(c[1]+l[1]*s);let f=it(u),h=(i||0)+(a||0);return Number.isFinite(i)||Number.isFinite(a)?[f[0],f[1],h]:f}function Ol(r){let{height:e,pitch:t,bearing:n,altitude:i,scale:o,center:s}=r,a=Up();be.translate(a,a,[0,0,-i]),be.rotateX(a,a,-t*mt),be.rotateZ(a,a,n*mt);let c=o/e;return be.scale(a,a,[c,c,c]),s&&be.translate(a,a,Cn.negate([],s)),a}function Vp(r){let{width:e,height:t,altitude:n,pitch:i=0,offset:o,center:s,scale:a,nearZMultiplier:c=1,farZMultiplier:l=1}=r,{fovy:u=Nn(Lv)}=r;n!==void 0&&(u=Nn(n));let f=u*mt,h=i*mt,p=Ls(u),m=p;s&&(m+=s[2]*a/Math.cos(h)/t);let g=f*(.5+(o?o[1]:0)/t),y=Math.sin(g)*m/Math.sin(Es(Math.PI/2-h-g,.01,Math.PI-.01)),x=Math.sin(h)*y+m,v=m*10,_=Math.min(x*l,v);return{fov:f,aspect:e/t,focalDistance:p,near:c,far:_}}function Nn(r){return 2*Math.atan(.5/r)*Gp}function Ls(r){return .5/Math.tan(.5*r*mt)}function Vr(r,e){let[t,n,i=0]=r;return Pt(Number.isFinite(t)&&Number.isFinite(n)&&Number.isFinite(i)),$r(e,[t,n,i,1])}function qt(r,e,t=0){let[n,i,o]=r;if(Pt(Number.isFinite(n)&&Number.isFinite(i),"invalid pixel coordinate"),Number.isFinite(o))return $r(e,[n,i,o,1]);let s=$r(e,[n,i,0,1]),a=$r(e,[n,i,1,1]),c=s[2],l=a[2],u=c===l?0:((t||0)-c)/(l-c);return $e.lerp([],s,a,u)}function kl(r){let{width:e,height:t,bounds:n,minExtent:i=0,maxZoom:o=24,offset:s=[0,0]}=r,[[a,c],[l,u]]=n,f=ZR(r.padding),h=gt([a,Es(u,-Oi,Oi)]),p=gt([l,Es(c,-Oi,Oi)]),m=[Math.max(Math.abs(p[0]-h[0]),i),Math.max(Math.abs(p[1]-h[1]),i)],g=[e-f.left-f.right-Math.abs(s[0])*2,t-f.top-f.bottom-Math.abs(s[1])*2];Pt(g[0]>0&&g[1]>0);let y=g[0]/m[0],x=g[1]/m[1],v=(f.right-f.left)/2/y,_=(f.top-f.bottom)/2/x,w=[(p[0]+h[0])/2+v,(p[1]+h[1])/2+_],E=it(w),S=Math.min(o,Ss(Math.abs(Math.min(y,x))));return Pt(Number.isFinite(S)),{longitude:E[0],latitude:E[1],zoom:S}}function ZR(r=0){return typeof r=="number"?{top:r,bottom:r,left:r,right:r}:(Pt(Number.isFinite(r.top)&&Number.isFinite(r.bottom)&&Number.isFinite(r.left)&&Number.isFinite(r.right)),r)}Ee();var Av=Math.PI/180;function Dl(r,e=0){let{width:t,height:n,unproject:i}=r,o={targetZ:e},s=i([0,n],o),a=i([t,n],o),c,l,u=r.fovy?.5*r.fovy*Av:Math.atan(.5/r.altitude),f=(90-r.pitch)*Av;return u>f-.01?(c=Cv(r,0,e),l=Cv(r,t,e)):(c=i([0,0],o),l=i([t,0],o)),[s,a,l,c]}function Cv(r,e,t){let{pixelUnprojectionMatrix:n}=r,i=$r(n,[e,0,1,1]),o=$r(n,[e,r.height,1,1]),a=(t*r.distanceScales.unitsPerMeter[2]-i[2])/(o[2]-i[2]),c=$e.lerp([],i,o,a),l=it(c);return l.push(t),l}var Iv=`
layout(std140) uniform shadowUniforms {
  bool drawShadowMap;
  bool useShadowMap;
  vec4 color;
  highp int lightId;
  float lightCount;
  mat4 viewProjectionMatrix0;
  mat4 viewProjectionMatrix1;
  vec4 projectCenter0;
  vec4 projectCenter1;
} shadow;
`,JR=`
const int max_lights = 2;

out vec3 shadow_vPosition[max_lights];

vec4 shadow_setVertexPosition(vec4 position_commonspace) {
  mat4 viewProjectionMatrices[max_lights];
  viewProjectionMatrices[0] = shadow.viewProjectionMatrix0;
  viewProjectionMatrices[1] = shadow.viewProjectionMatrix1;
  vec4 projectCenters[max_lights];
  projectCenters[0] = shadow.projectCenter0;
  projectCenters[1] = shadow.projectCenter1;

  if (shadow.drawShadowMap) {
    return project_common_position_to_clipspace(position_commonspace, viewProjectionMatrices[shadow.lightId], projectCenters[shadow.lightId]);
  }
  if (shadow.useShadowMap) {
    for (int i = 0; i < max_lights; i++) {
      if(i < int(shadow.lightCount)) {
        vec4 shadowMap_position = project_common_position_to_clipspace(position_commonspace, viewProjectionMatrices[i], projectCenters[i]);
        shadow_vPosition[i] = (shadowMap_position.xyz / shadowMap_position.w + 1.0) / 2.0;
      }
    }
  }
  return gl_Position;
}
`,eB=`
${Iv}
${JR}
`,tB=`
const int max_lights = 2;
uniform sampler2D shadow_uShadowMap0;
uniform sampler2D shadow_uShadowMap1;

in vec3 shadow_vPosition[max_lights];

const vec4 bitPackShift = vec4(1.0, 255.0, 65025.0, 16581375.0);
const vec4 bitUnpackShift = 1.0 / bitPackShift;
const vec4 bitMask = vec4(1.0 / 255.0, 1.0 / 255.0, 1.0 / 255.0,  0.0);

float shadow_getShadowWeight(vec3 position, sampler2D shadowMap) {
  vec4 rgbaDepth = texture(shadowMap, position.xy);

  float z = dot(rgbaDepth, bitUnpackShift);
  return smoothstep(0.001, 0.01, position.z - z);
}

vec4 shadow_filterShadowColor(vec4 color) {
  if (shadow.drawShadowMap) {
    vec4 rgbaDepth = fract(gl_FragCoord.z * bitPackShift);
    rgbaDepth -= rgbaDepth.gbaa * bitMask;
    return rgbaDepth;
  }
  if (shadow.useShadowMap) {
    float shadowAlpha = 0.0;
    shadowAlpha += shadow_getShadowWeight(shadow_vPosition[0], shadow_uShadowMap0);
    if(shadow.lightCount > 1.0) {
      shadowAlpha += shadow_getShadowWeight(shadow_vPosition[1], shadow_uShadowMap1);
    }
    shadowAlpha *= shadow.color.a / shadow.lightCount;
    float blendedAlpha = shadowAlpha + color.a * (1.0 - shadowAlpha);

    return vec4(
      mix(color.rgb, shadow.color.rgb, shadowAlpha / blendedAlpha),
      blendedAlpha
    );
  }
  return color;
}
`,rB=`
${Iv}
${tB}
`,nB=Yt(cB),iB=Yt(lB),oB=[0,0,0,1],sB=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,0];function aB(r,e){let[t,n,i]=r,o=qt([t,n,i],e);return Number.isFinite(i)?o:[o[0],o[1],0]}function cB({viewport:r,center:e}){return new ge(r.viewProjectionMatrix).invert().transform(e)}function lB({viewport:r,shadowMatrices:e}){let t=[],n=r.pixelUnprojectionMatrix,i=r.isGeospatial?void 0:1,o=[[0,0,i],[r.width,0,i],[0,r.height,i],[r.width,r.height,i],[0,0,-1],[r.width,0,-1],[0,r.height,-1],[r.width,r.height,-1]].map(s=>aB(s,n));for(let s of e){let a=s.clone().translate(new Me(r.center).negate()),c=o.map(u=>a.transform(u)),l=new ge().ortho({left:Math.min(...c.map(u=>u[0])),right:Math.max(...c.map(u=>u[0])),bottom:Math.min(...c.map(u=>u[1])),top:Math.max(...c.map(u=>u[1])),near:Math.min(...c.map(u=>-u[2])),far:Math.max(...c.map(u=>-u[2]))});t.push(l.multiplyRight(s))}return t}function uB(r){let{shadowEnabled:e=!0,project:t}=r;if(!e||!t||!r.shadowMatrices||!r.shadowMatrices.length)return{drawShadowMap:!1,useShadowMap:!1,shadow_uShadowMap0:r.dummyShadowMap,shadow_uShadowMap1:r.dummyShadowMap};let n=Ri.getUniforms(t),i=nB({viewport:t.viewport,center:n.center}),o=[],s=iB({shadowMatrices:r.shadowMatrices,viewport:t.viewport}).slice();for(let c=0;c<r.shadowMatrices.length;c++){let l=s[c],u=l.clone().translate(new Me(t.viewport.center).negate());n.coordinateSystem===Dn("lnglat")&&n.projectionMode===Se.WEB_MERCATOR?(s[c]=u,o[c]=i):(s[c]=l.clone().multiplyRight(sB),o[c]=u.transform(i))}let a={drawShadowMap:!!r.drawToShadowMap,useShadowMap:r.shadowMaps?r.shadowMaps.length>0:!1,color:r.shadowColor||oB,lightId:r.shadowLightId||0,lightCount:r.shadowMatrices.length,shadow_uShadowMap0:r.dummyShadowMap,shadow_uShadowMap1:r.dummyShadowMap};for(let c=0;c<s.length;c++)a[`viewProjectionMatrix${c}`]=s[c],a[`projectCenter${c}`]=o[c];for(let c=0;c<2;c++)a[`shadow_uShadowMap${c}`]=r.shadowMaps&&r.shadowMaps[c]||r.dummyShadowMap;return a}var Nl={name:"shadow",dependencies:[Ri],vs:eB,fs:rB,inject:{"vs:DECKGL_FILTER_GL_POSITION":`
    position = shadow_setVertexPosition(geometry.position);
    `,"fs:DECKGL_FILTER_COLOR":`
    color = shadow_filterShadowColor(color);
    `},getUniforms:uB,uniformTypes:{drawShadowMap:"f32",useShadowMap:"f32",color:"vec4<f32>",lightId:"i32",lightCount:"f32",viewProjectionMatrix0:"mat4x4<f32>",viewProjectionMatrix1:"mat4x4<f32>",projectCenter0:"vec4<f32>",projectCenter1:"vec4<f32>"}};qe();var Fl=10,As=16777215;function Bv(r,e){r.length===Fl?$.warn(`pickMultipleObjects can only exclude ${Fl} previously picked objects for layers without picking buffers`)():r.push(e)}var fB=`  float disabledPickingIndexCount;
  vec4 disabledPickingIndices0;
  vec4 disabledPickingIndices1;
  vec4 disabledPickingIndices2;
`;function Rv(r){return r.replace(`  vec4 highlightColor;
} picking;`,`  vec4 highlightColor;
${fB}} picking;`)}function Wp(r,e){return[r[e]||0,r[e+1]||0,r[e+2]||0,r[e+3]||0]}var dB=`vec3 picking_getPickingColorFromIndex(float objectIndex) {
  if (objectIndex < 0.0 || objectIndex >= ${As}.0) {
    return vec3(0.0);
  }

  for (int i = 0; i < ${Fl}; i++) {
    if (float(i) >= picking.disabledPickingIndexCount) {
      break;
    }
    vec4 disabledIndices = i < 4
      ? picking.disabledPickingIndices0
      : (i < 8 ? picking.disabledPickingIndices1 : picking.disabledPickingIndices2);
    float disabledIndex = disabledIndices[i - (i / 4) * 4];
    if (disabledIndex == objectIndex) {
      return vec3(0.0);
    }
  }

  float encodedIndex = objectIndex + 1.0;
  return vec3(
    mod(encodedIndex, 256.0),
    mod(floor(encodedIndex / 256.0), 256.0),
    mod(floor(encodedIndex / 65536.0), 256.0)
  );
}

vec3 picking_getPickingColorFromIndex(uint objectIndex) {
  return picking_getPickingColorFromIndex(float(objectIndex));
}

vec3 picking_getPickingColorFromInstanceID() {
  return picking_getPickingColorFromIndex(float(gl_InstanceID));
}

void picking_setPickingColorFromInstanceID() {
  picking_setPickingColor(picking_getPickingColorFromInstanceID());
}
`,hB=`struct pickingUniforms {
  isActive: f32,
  isAttribute: f32,
  isHighlightActive: f32,
  useByteColors: f32,
  highlightedObjectColor: vec3<f32>,
  highlightColor: vec4<f32>,
  disabledPickingIndexCount: f32,
  disabledPickingIndices0: vec4<f32>,
  disabledPickingIndices1: vec4<f32>,
  disabledPickingIndices2: vec4<f32>,
};

@group(0) @binding(auto) var<uniform> picking: pickingUniforms;

fn picking_normalizeColor(color: vec3<f32>) -> vec3<f32> {
  return select(color, color / 255.0, picking.useByteColors > 0.5);
}

fn picking_normalizeColor4(color: vec4<f32>) -> vec4<f32> {
  return select(color, color / 255.0, picking.useByteColors > 0.5);
}

fn picking_isColorZero(color: vec3<f32>) -> bool {
  return dot(color, vec3<f32>(1.0)) < 0.00001;
}

fn picking_isColorValid(color: vec3<f32>) -> bool {
  return dot(color, vec3<f32>(1.0)) > 0.00001;
}

fn picking_getPickingColorFromIndex(objectIndex: u32) -> vec3<f32> {
  if (objectIndex >= ${As}u) {
    return vec3<f32>(0.0);
  }

  for (var i = 0; i < ${Fl}; i = i + 1) {
    if (f32(i) >= picking.disabledPickingIndexCount) {
      break;
    }
    let disabledIndices = select(
      picking.disabledPickingIndices2,
      select(picking.disabledPickingIndices1, picking.disabledPickingIndices0, i < 4),
      i < 8
    );
    let disabledIndex = disabledIndices[i % 4];
    if (disabledIndex == f32(objectIndex)) {
      return vec3<f32>(0.0);
    }
  }

  let encodedIndex = objectIndex + 1u;
  return vec3<f32>(
    f32(encodedIndex % 256u),
    f32((encodedIndex / 256u) % 256u),
    f32((encodedIndex / 65536u) % 256u)
  ) / 255.0;
}
`,Wr={...Fr,vs:`${Rv(Fr.vs)}
${dB}`,fs:Rv(Fr.fs),source:hB,uniformTypes:{...Fr.uniformTypes,disabledPickingIndexCount:"f32",disabledPickingIndices0:"vec4<f32>",disabledPickingIndices1:"vec4<f32>",disabledPickingIndices2:"vec4<f32>"},defaultUniforms:{...Fr.defaultUniforms,useByteColors:!0,disabledPickingIndexCount:0,disabledPickingIndices0:[0,0,0,0],disabledPickingIndices1:[0,0,0,0],disabledPickingIndices2:[0,0,0,0]},getUniforms(r,e){let t=Fr.getUniforms(r,e),n=r.disabledPickingIndices||[];return t.disabledPickingIndexCount=n.length,t.disabledPickingIndices0=Wp(n,0),t.disabledPickingIndices1=Wp(n,4),t.disabledPickingIndices2=Wp(n,8),t},inject:{"vs:DECKGL_FILTER_GL_POSITION":`
    // for picking depth values
    picking_setPickingAttribute(position.z / position.w);
  `,"vs:DECKGL_FILTER_COLOR":`
  picking_setPickingColor(geometry.pickingColor);
  `,"fs:DECKGL_FILTER_COLOR":{order:99,injection:`
  // use highlight color if this fragment belongs to the selected object.
  color = picking_filterHighlightColor(color);

  // use picking color if rendering to picking FBO.
  color = picking_filterPickingColor(color);
    `}}};var mB=[wl],gB=["vs:DECKGL_FILTER_SIZE(inout vec3 size, VertexGeometry geometry)","vs:DECKGL_FILTER_GL_POSITION(inout vec4 position, VertexGeometry geometry)","vs:DECKGL_FILTER_COLOR(inout vec4 color, VertexGeometry geometry)","fs:DECKGL_FILTER_COLOR(inout vec4 color, FragmentGeometry geometry)"],yB=[];function Ov(r){let e=dt.getDefaultShaderAssembler(r);for(let n of mB)e.addDefaultModule(n);e._hookFunctions.length=0;let t=r==="glsl"?gB:yB;for(let n of t)e.addShaderHook(n);return e}var _B=[255,255,255],bB=1,xB=0,Ul=class{constructor(e={}){this.type="ambient";let{color:t=_B}=e,{intensity:n=bB}=e;this.id=e.id||`ambient-${xB++}`,this.color=t,this.intensity=n}};Ee();var vB=[255,255,255],wB=1,EB=[0,0,-1],SB=0,Cs=class{constructor(e={}){this.type="directional";let{color:t=vB}=e,{intensity:n=wB}=e,{direction:i=EB}=e,{_shadow:o=!1}=e;this.id=e.id||`directional-${SB++}`,this.color=t,this.intensity=n,this.type="directional",this.direction=new Me(i).normalize().toArray(),this.shadow=o}getProjectedLight(e){return this}};Ee();var Ms=class{constructor(e,t={id:"pass"}){let{id:n}=t;this.id=n,this.device=e,this.props={...t}}setProps(e){Object.assign(this.props,e)}render(e){}cleanup(){}};var PB={depthWriteEnabled:!0,depthCompare:"less-equal",blendColorOperation:"add",blendColorSrcFactor:"one",blendColorDstFactor:"one-minus-src-alpha",blendAlphaOperation:"add",blendAlphaSrcFactor:"one",blendAlphaDstFactor:"one-minus-src-alpha"},yr=class extends Ms{constructor(){super(...arguments),this._lastRenderIndex=-1}render(e){this._render(e)}_render(e){let{canvasContext:t=this.device.canvasContext}=e,n=e.target??t.getCurrentFramebuffer(),[i,o]=t.getDrawingBufferSize(),s=e.clearCanvas??!0,a=e.clearColor??(s?[0,0,0,0]:!1),c=s?1:!1,l=s?0:!1,u=e.colorMask??15,f={viewport:[0,0,i,o]};e.colorMask&&(f.colorMask=u),e.scissorRect&&(f.scissorRect=e.scissorRect);let{shaderModuleProps:h,viewports:p,views:m,onViewportActive:g,clearStack:y=!0}=e,x=e.pass||"unknown",v=this.device.type==="webgpu";y&&(this._lastRenderIndex=-1);let _=[];if(!p.length)return this.device.beginRenderPass({framebuffer:n,parameters:f,clearColor:a,clearDepth:c,clearStencil:l}).end(),this.device.submit(),_;try{for(let w of p){g?.(w);let E=this._getDrawLayerParams(w,e),S=m&&m[w.id],C=w.subViewports||[w],A=v?C.map(B=>[B]):[C];for(let B of A){let L=this.device.beginRenderPass({framebuffer:n,parameters:f,clearColor:a,clearDepth:c,clearStencil:l});try{for(let M of B){let I=this._drawLayersInViewport(L,{target:n,canvasContext:t,shaderModuleProps:h,viewport:M,view:S,pass:x,layers:e.layers,isPicking:e.isPicking},E);_.push(I)}}finally{L.end(),v&&this.device.submit()}a=!1,c=!1,l=!1}}return _}finally{v||this.device.submit()}}_getDrawLayerParams(e,{layers:t,pass:n,isPicking:i=!1,layerFilter:o,cullRect:s,views:a,effects:c,canvasContext:l=this.device.canvasContext,shaderModuleProps:u},f=!1){let h=[],p=Dv(this._lastRenderIndex+1),m={layer:t[0],viewport:e,isPicking:i,renderPass:n,cullRect:s},g={};for(let y=0;y<t.length;y++){let x=t[y],v=this._shouldDrawLayer(x,m,o,g),_={shouldDrawLayer:v};if(v&&!f){_.shouldDrawLayer=!0,_.layerRenderIndex=p(x,v),_.shaderModuleProps=this._getShaderModuleProps(x,c,n,l,u);let w=x.context.device.type==="webgpu"?PB:null;_.layerParameters={...w,...x.context.deck?.props.parameters,...a?.[e.id]?.props.parameters,...this.getLayerParameters(x,y,e)}}h[y]=_}return h}_drawLayersInViewport(e,{layers:t,shaderModuleProps:n,pass:i,target:o,canvasContext:s,viewport:a,view:c,isPicking:l},u){let f=TB(this.device,{canvasContext:s,shaderModuleProps:n,target:o,viewport:a});if(c){let{clear:p,clearColor:m,clearDepth:g,clearStencil:y}=c.props;if(p){let x=[0,0,0,0],v=1,_=0;Array.isArray(m)&&!l?x=[...m.slice(0,3),m[3]||255].map(E=>E/255):m===!1&&(x=!1),g!==void 0&&(v=g),y!==void 0&&(_=y),this.device.beginRenderPass({framebuffer:o,parameters:{viewport:f,scissorRect:f},clearColor:x,clearDepth:v,clearStencil:_}).end()}}let h={totalCount:t.length,visibleCount:0,compositeCount:0,pickableCount:0};e.setParameters({viewport:f});for(let p=0;p<t.length;p++){let m=t[p],g=u[p],{shouldDrawLayer:y}=g;if(y&&m.props.pickable&&h.pickableCount++,m.isComposite&&h.compositeCount++,m.isDrawable&&g.shouldDrawLayer){let{layerRenderIndex:x,shaderModuleProps:v,layerParameters:_}=g;h.visibleCount++,this._lastRenderIndex=Math.max(this._lastRenderIndex,x),v.project&&(v.project.viewport=a),m.context.renderPass=e;try{m._drawLayer({renderPass:e,shaderModuleProps:v,uniforms:{layerIndex:x},parameters:_})}catch(w){m.raiseError(w,`drawing ${m} to ${i}`)}}}return h}shouldDrawLayer(e){return!0}getShaderModuleProps(e,t,n){return null}getLayerParameters(e,t,n){return e.props.parameters}_shouldDrawLayer(e,t,n,i){if(!(e.props.visible&&this.shouldDrawLayer(e)))return!1;t.layer=e;let s=e.parent;for(;s;){if(!s.props.visible||!s.filterSubLayer(t))return!1;t.layer=s,s=s.parent}if(n){let a=t.layer.id;if(a in i||(i[a]=n(t)),!i[a])return!1}return e.activateViewport(t.viewport),!0}_getShaderModuleProps(e,t,n,i,o){let s=i.cssToDeviceRatio(),a=e.internalState?.propsInTransition||e.props,c={layer:a,picking:{isActive:!1},project:{viewport:e.context.viewport,devicePixelRatio:s,modelMatrix:a.modelMatrix,coordinateSystem:a.coordinateSystem,coordinateOrigin:a.coordinateOrigin,autoWrapLongitude:e.wrapLongitude}};if(t)for(let l of t)kv(c,l.getShaderModuleProps?.(e,c));for(let l of e.context.defaultShaderModules)l.name in c||(c[l.name]={});return kv(c,this.getShaderModuleProps(e,t,c),o)}};function Dv(r=0,e={}){let t={},n=(i,o)=>{let s=i.props._offset,a=i.id,c=i.parent&&i.parent.id,l;if(c&&!(c in e)&&n(i.parent,!1),c in t){let u=t[c]=t[c]||Dv(e[c],e);l=u(i,o),t[a]=u}else Number.isFinite(s)?(l=s+(e[c]||0),t[a]=null):l=r;return o&&l>=r&&(r=l+1),e[a]=l,l};return n}function TB(r,{canvasContext:e=r.canvasContext,shaderModuleProps:t,target:n,viewport:i}){let o=t?.project?.devicePixelRatio??e.cssToDeviceRatio(),[,s]=e.getDrawingBufferSize(),a=n?n.height:s,c=i;return[c.x*o,a-(c.y+c.height)*o,c.width*o,c.height*o]}function kv(r,...e){for(let t of e)if(t)for(let n in t)r[n]?Object.assign(r[n],t[n]):r[n]=t[n];return r}var Is=class extends yr{constructor(e,t){super(e,t);let n=e.createTexture({format:"rgba8unorm",width:1,height:1,sampler:{minFilter:"linear",magFilter:"linear",addressModeU:"clamp-to-edge",addressModeV:"clamp-to-edge"}}),i=e.createTexture({format:"depth16unorm",width:1,height:1});this.fbo=e.createFramebuffer({id:"shadowmap",width:1,height:1,colorAttachments:[n],depthStencilAttachment:i})}delete(){this.fbo&&(this.fbo.destroy(),this.fbo=null)}getShadowMap(){return this.fbo.colorAttachments[0].texture}render(e){let t=this.fbo,n=this.device.canvasContext.cssToDeviceRatio(),i=e.viewports[0],o=i.width*n,s=i.height*n,a=[1,1,1,1];(o!==t.width||s!==t.height)&&t.resize({width:o,height:s}),super.render({...e,clearColor:a,target:t,pass:"shadow"})}getLayerParameters(e,t,n){return{...e.props.parameters,blend:!1,depthWriteEnabled:!0,depthCompare:"less-equal"}}shouldDrawLayer(e){return e.props.shadowEnabled!==!1}getShaderModuleProps(e,t,n){return{shadow:{project:n.project,drawToShadowMap:!0}}}};var LB={color:[255,255,255],intensity:1},Nv=[{color:[255,255,255],intensity:1,direction:[-1,3,-1]},{color:[255,255,255],intensity:.9,direction:[1,-8,-2.5]}],AB=[0,0,0,200/255],Di=class{constructor(e={}){this.id="lighting-effect",this.shadowColor=AB,this.shadow=!1,this.directionalLights=[],this.pointLights=[],this.shadowPasses=[],this.dummyShadowMap=null,this.setProps(e)}setup(e){this.context=e;let{device:t,deck:n}=e;this.shadow&&!this.dummyShadowMap&&(this._createShadowPasses(t),n._addDefaultShaderModule(Nl),this.dummyShadowMap=t.createTexture({width:1,height:1}))}setProps(e){this.ambientLight=void 0,this.directionalLights=[],this.pointLights=[];for(let t in e){let n=e[t];switch(n.type){case"ambient":this.ambientLight=n;break;case"directional":this.directionalLights.push(n);break;case"point":this.pointLights.push(n);break;default:}}this._applyDefaultLights(),this.shadow=this.directionalLights.some(t=>t.shadow),this.context&&this.setup(this.context),this.props=e}preRender({layers:e,layerFilter:t,viewports:n,onViewportActive:i,views:o}){if(this.shadow){this.shadowMatrices=this._calculateMatrices();for(let s=0;s<this.shadowPasses.length;s++)this.shadowPasses[s].render({layers:e,layerFilter:t,viewports:n,onViewportActive:i,views:o,shaderModuleProps:{shadow:{shadowLightId:s,dummyShadowMap:this.dummyShadowMap,shadowMatrices:this.shadowMatrices}}})}}getShaderModuleProps(e,t){let n=this.shadow?{project:t.project,shadowMaps:this.shadowPasses.map(s=>s.getShadowMap()),dummyShadowMap:this.dummyShadowMap,shadowColor:this.shadowColor,shadowMatrices:this.shadowMatrices}:{},i={enabled:!0,lights:this._getLights(e)},o=e.props.material;return{shadow:n,lighting:i,phongMaterial:o,gouraudMaterial:o}}cleanup(e){for(let t of this.shadowPasses)t.delete();this.shadowPasses.length=0,this.dummyShadowMap&&(this.dummyShadowMap.destroy(),this.dummyShadowMap=null,e.deck._removeDefaultShaderModule(Nl))}_calculateMatrices(){let e=[];for(let t of this.directionalLights){let n=new ge().lookAt({eye:new Me(t.direction).negate()});e.push(n)}return e}_createShadowPasses(e){for(let t=0;t<this.directionalLights.length;t++){let n=new Is(e);this.shadowPasses[t]=n}}_applyDefaultLights(){let{ambientLight:e,pointLights:t,directionalLights:n}=this;!e&&t.length===0&&n.length===0&&(this.ambientLight=new Ul(LB),this.directionalLights.push(new Cs(Nv[0]),new Cs(Nv[1])))}_getLights(e){let t=[];this.ambientLight&&t.push(this.ambientLight);for(let n of this.pointLights)t.push(n.getProjectedLight({layer:e}));for(let n of this.directionalLights)t.push(n.getProjectedLight({layer:e}));return t}};var jp=class{constructor(e={}){this._pool=[],this.opts={overAlloc:2,poolSize:100},this.setOptions(e)}setOptions(e){Object.assign(this.opts,e)}allocate(e,t,{size:n=1,type:i,padding:o=0,copy:s=!1,initialize:a=!1,maxCount:c}){let l=i||e&&e.constructor||Float32Array,u=t*n+o;if(ArrayBuffer.isView(e)){if(u<=e.length)return e;if(u*e.BYTES_PER_ELEMENT<=e.buffer.byteLength)return new l(e.buffer,0,u)}let f=1/0;c&&(f=c*n+o);let h=this._allocate(l,u,a,f);return e&&s?h.set(e):a||h.fill(0,0,4),this._release(e),h}release(e){this._release(e)}_allocate(e,t,n,i){let o=Math.max(Math.ceil(t*this.opts.overAlloc),1);o>i&&(o=i);let s=this._pool,a=e.BYTES_PER_ELEMENT*o,c=s.findIndex(l=>l.byteLength>=a);if(c>=0){let l=new e(s.splice(c,1)[0],0,o);return n&&l.fill(0),l}return new e(o)}_release(e){if(!ArrayBuffer.isView(e))return;let t=this._pool,{buffer:n}=e,{byteLength:i}=n,o=t.findIndex(s=>s.byteLength>=i);o<0?t.push(n):(o>0||t.length<this.opts.poolSize)&&t.splice(o,0,n),t.length>this.opts.poolSize&&t.shift()}},Lt=new jp;Ee();function Fi(){return[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]}function Hp(r,e){let t=r%e;return t<0?e+t:t}function Uv(r){return[r[12],r[13],r[14]]}function Gv(r){return{left:Ni(r[3]+r[0],r[7]+r[4],r[11]+r[8],r[15]+r[12]),right:Ni(r[3]-r[0],r[7]-r[4],r[11]-r[8],r[15]-r[12]),bottom:Ni(r[3]+r[1],r[7]+r[5],r[11]+r[9],r[15]+r[13]),top:Ni(r[3]-r[1],r[7]-r[5],r[11]-r[9],r[15]-r[13]),near:Ni(r[3]+r[2],r[7]+r[6],r[11]+r[10],r[15]+r[14]),far:Ni(r[3]-r[2],r[7]-r[6],r[11]-r[10],r[15]-r[14])}}var Fv=new Me;function Ni(r,e,t,n){Fv.set(r,e,t);let i=Fv.len();return{distance:n/i,normal:new Me(-r/i,-e/i,-t/i)}}function CB(r){return r-Math.fround(r)}var Rs;function Ui(r,e){let{size:t=1,startIndex:n=0}=e,i=e.endIndex!==void 0?e.endIndex:r.length,o=(i-n)/t;Rs=Lt.allocate(Rs,o,{type:Float32Array,size:t*2});let s=n,a=0;for(;s<i;){for(let c=0;c<t;c++){let l=r[s++];Rs[a+c]=l,Rs[a+c+t]=CB(l)}a+=t*2}return Rs.subarray(0,o*t*2)}function zv(r){let e=null,t=!1;for(let n of r)n&&(e?(t||(e=[[e[0][0],e[0][1]],[e[1][0],e[1][1]]],t=!0),e[0][0]=Math.min(e[0][0],n[0][0]),e[0][1]=Math.min(e[0][1],n[0][1]),e[1][0]=Math.max(e[1][0],n[1][0]),e[1][1]=Math.max(e[1][1],n[1][1])):e=n);return e}Ee();var MB=Math.PI/180,IB=Fi(),$v=[0,0,0],RB={unitsPerMeter:[1,1,1],metersPerUnit:[1,1,1]};function BB({width:r,height:e,orthographic:t,fovyRadians:n,focalDistance:i,padding:o,near:s,far:a}){let c=r/e,l=t?new ge().orthographic({fovy:n,aspect:c,focalDistance:i,near:s,far:a}):new ge().perspective({fovy:n,aspect:c,near:s,far:a});if(o){let{left:u=0,right:f=0,top:h=0,bottom:p=0}=o,m=ie((u+r-f)/2,0,r)-r/2,g=ie((h+e-p)/2,0,e)-e/2;l[8]-=m*2/r,l[9]+=g*2/e}return l}var Gl=class r{constructor(e={}){this._frustumPlanes={},this.id=e.id||this.constructor.displayName||"viewport",this.x=e.x||0,this.y=e.y||0,this.width=e.width||1,this.height=e.height||1,this.zoom=e.zoom||0,this.padding=e.padding,this.distanceScales=e.distanceScales||RB,this.focalDistance=e.focalDistance||1,this.position=e.position||$v,this.modelMatrix=e.modelMatrix||null;let{longitude:t,latitude:n}=e;this.isGeospatial=Number.isFinite(n)&&Number.isFinite(t),this._initProps(e),this._initMatrices(e),this.equals=this.equals.bind(this),this.project=this.project.bind(this),this.unproject=this.unproject.bind(this),this.projectPosition=this.projectPosition.bind(this),this.unprojectPosition=this.unprojectPosition.bind(this),this.projectFlat=this.projectFlat.bind(this),this.unprojectFlat=this.unprojectFlat.bind(this)}get subViewports(){return null}get metersPerPixel(){return this.distanceScales.metersPerUnit[2]/this.scale}get projectionMode(){return this.isGeospatial?this.zoom<12?Se.WEB_MERCATOR:Se.WEB_MERCATOR_AUTO_OFFSET:Se.IDENTITY}equals(e){return e instanceof r?this===e?!0:e.width===this.width&&e.height===this.height&&e.scale===this.scale&&e.projectionMode===this.projectionMode&&e.resolution===this.resolution&&Wt(e.distanceScales.unitsPerMeter,this.distanceScales.unitsPerMeter)&&Wt(e.projectionMatrix,this.projectionMatrix)&&Wt(e.viewMatrix,this.viewMatrix):!1}project(e,{topLeft:t=!0}={}){let n=this.projectPosition(e),i=Vr(n,this.pixelProjectionMatrix),[o,s]=i,a=t?s:this.height-s;return e.length===2?[o,a]:[o,a,i[2]]}unproject(e,{topLeft:t=!0,targetZ:n}={}){let[i,o,s]=e,a=t?o:this.height-o,c=n&&n*this.distanceScales.unitsPerMeter[2],l=qt([i,a,s],this.pixelUnprojectionMatrix,c),[u,f,h]=this.unprojectPosition(l);return Number.isFinite(s)?[u,f,h]:Number.isFinite(n)?[u,f,n]:[u,f]}projectPosition(e){let[t,n]=this.projectFlat(e),i=(e[2]||0)*this.distanceScales.unitsPerMeter[2];return[t,n,i]}unprojectPosition(e){let[t,n]=this.unprojectFlat(e),i=(e[2]||0)*this.distanceScales.metersPerUnit[2];return[t,n,i]}projectFlat(e){if(this.isGeospatial){let t=gt(e);return t[1]=ie(t[1],-318,830),t}return e}unprojectFlat(e){return this.isGeospatial?it(e):e}getBounds(e={}){let t={targetZ:e.z||0},n=this.unproject([0,0],t),i=this.unproject([this.width,0],t),o=this.unproject([0,this.height],t),s=this.unproject([this.width,this.height],t);return[Math.min(n[0],i[0],o[0],s[0]),Math.min(n[1],i[1],o[1],s[1]),Math.max(n[0],i[0],o[0],s[0]),Math.max(n[1],i[1],o[1],s[1])]}getDistanceScales(e){return e&&this.isGeospatial?ki({longitude:e[0],latitude:e[1],highPrecision:!0}):this.distanceScales}containsPixel({x:e,y:t,width:n=1,height:i=1}){return e<this.x+this.width&&this.x<e+n&&t<this.y+this.height&&this.y<t+i}getFrustumPlanes(){return this._frustumPlanes.near?this._frustumPlanes:(Object.assign(this._frustumPlanes,Gv(this.viewProjectionMatrix)),this._frustumPlanes)}panByPosition(e,t,n){return null}_initProps(e){let t=e.longitude,n=e.latitude;this.isGeospatial&&(Number.isFinite(e.zoom)||(this.zoom=$p({latitude:n})+Math.log2(this.focalDistance)),this.distanceScales=e.distanceScales||ki({latitude:n,longitude:t}));let i=Math.pow(2,this.zoom);this.scale=i;let{position:o,modelMatrix:s}=e,a=$v;if(o&&(a=s?new ge(s).transformAsVector(o,[]):o),this.isGeospatial){let c=this.projectPosition([t,n,0]);this.center=new Me(a).scale(this.distanceScales.unitsPerMeter).add(c)}else this.center=this.projectPosition(a)}_initMatrices(e){let{viewMatrix:t=IB,projectionMatrix:n=null,orthographic:i=!1,fovyRadians:o,fovy:s=75,near:a=.1,far:c=1e3,padding:l=null,focalDistance:u=1}=e;this.viewMatrixUncentered=t,this.viewMatrix=new ge().multiplyRight(t).translate(new Me(this.center).negate()),this.projectionMatrix=n||BB({width:this.width,height:this.height,orthographic:i,fovyRadians:o||s*MB,focalDistance:u,padding:l,near:a,far:c});let f=Fi();be.multiply(f,f,this.projectionMatrix),be.multiply(f,f,this.viewMatrix),this.viewProjectionMatrix=f,this.viewMatrixInverse=be.invert([],this.viewMatrix)||this.viewMatrix,this.cameraPosition=Uv(this.viewMatrixInverse);let h=Fi(),p=Fi();be.scale(h,h,[this.width/2,-this.height/2,1]),be.translate(h,h,[1,-1,0]),be.multiply(p,h,this.viewProjectionMatrix),this.pixelProjectionMatrix=p,this.pixelUnprojectionMatrix=be.invert(Fi(),this.pixelProjectionMatrix),this.pixelUnprojectionMatrix||$.warn("Pixel project matrix not invertible")()}};Gl.displayName="Viewport";var Gi=Gl;Ee();var zl=class r extends Gi{constructor(e={}){let{latitude:t=0,longitude:n=0,zoom:i=0,pitch:o=0,bearing:s=0,nearZMultiplier:a=.1,farZMultiplier:c=1.01,nearZ:l,farZ:u,orthographic:f=!1,projectionMatrix:h,repeat:p=!1,worldOffset:m=0,position:g,padding:y,legacyMeterSizes:x=!1}=e,{width:v,height:_,altitude:w=1.5}=e,E=Math.pow(2,i);v=v||1,_=_||1;let S,C=null;if(h)w=h[5]/2,S=Nn(w);else{e.fovy?(S=e.fovy,w=Ls(S)):S=Nn(w);let B;if(y){let{top:L=0,bottom:M=0}=y;B=[0,ie((L+_-M)/2,0,_)-_/2]}C=Vp({width:v,height:_,scale:E,center:g&&[0,0,g[2]*Ps(t)],offset:B,pitch:o,fovy:S,nearZMultiplier:a,farZMultiplier:c}),Number.isFinite(l)&&(C.near=l),Number.isFinite(u)&&(C.far=u)}let A=Ol({height:_,pitch:o,bearing:s,scale:E,altitude:w});m&&(A=new ge().translate([512*m,0,0]).multiplyLeft(A)),super({...e,width:v,height:_,viewMatrix:A,longitude:n,latitude:t,zoom:i,...C,fovy:S,focalDistance:w}),this.latitude=t,this.longitude=n,this.zoom=i,this.pitch=o,this.bearing=s,this.altitude=w,this.fovy=S,this.orthographic=f,this._subViewports=p?[]:null,this._pseudoMeters=x,Object.freeze(this)}get subViewports(){if(this._subViewports&&!this._subViewports.length){let e=this.getBounds(),t=Math.floor((e[0]+180)/360),n=Math.ceil((e[2]-180)/360);for(let i=t;i<=n;i++){let o=i?new r({...this,worldOffset:i}):this;this._subViewports.push(o)}}return this._subViewports}equals(e){return e instanceof r&&e._pseudoMeters===this._pseudoMeters&&super.equals(e)}projectPosition(e){if(this._pseudoMeters)return super.projectPosition(e);let[t,n]=this.projectFlat(e),i=(e[2]||0)*Ps(e[1]);return[t,n,i]}unprojectPosition(e){if(this._pseudoMeters)return super.unprojectPosition(e);let[t,n]=this.unprojectFlat(e),i=(e[2]||0)/Ps(n);return[t,n,i]}addMetersToLngLat(e,t){return Ts(e,t)}panByPosition(e,t,n){let i=qt(t,this.pixelUnprojectionMatrix),o=this.projectFlat(e),s=$e.add([],o,$e.negate([],i)),a=$e.add([],this.center,s),[c,l]=this.unprojectFlat(a);return{longitude:c,latitude:l}}panByPosition3D(e,t){let n=e[2]||0,i=$e.sub([],e,this.unproject(t,{targetZ:n}));return{longitude:this.longitude+i[0],latitude:this.latitude+i[1]}}getBounds(e={}){let t=Dl(this,e.z||0);return[Math.min(t[0][0],t[1][0],t[2][0],t[3][0]),Math.min(t[0][1],t[1][1],t[2][1],t[3][1]),Math.max(t[0][0],t[1][0],t[2][0],t[3][0]),Math.max(t[0][1],t[1][1],t[2][1],t[3][1])]}fitBounds(e,t={}){let{width:n,height:i}=this,{longitude:o,latitude:s,zoom:a}=kl({width:n,height:i,bounds:e,...t});return new r({width:n,height:i,longitude:o,latitude:s,zoom:a})}};zl.displayName="WebMercatorViewport";var $l=zl;Ee();var Vv=[0,0,0];function Yp(r,e,t=!1){let n=e.projectPosition(r);if(t&&e instanceof $l){let[i,o,s=0]=r,a=e.getDistanceScales([i,o]);n[2]=s*a.unitsPerMeter[2]}return n}function OB(r){let{viewport:e,modelMatrix:t,coordinateOrigin:n}=r,{coordinateSystem:i,fromCoordinateSystem:o,fromCoordinateOrigin:s}=r;return i==="default"&&(i=e.isGeospatial?"lnglat":"cartesian"),o===void 0?o=i:o==="default"&&(o=e.isGeospatial?"lnglat":"cartesian"),s===void 0&&(s=n),{viewport:e,coordinateSystem:i,coordinateOrigin:n,modelMatrix:t,fromCoordinateSystem:o,fromCoordinateOrigin:s}}function Vl(r,{viewport:e,modelMatrix:t,coordinateSystem:n,coordinateOrigin:i,offsetMode:o}){let[s,a,c=0]=r;switch(t&&([s,a,c]=Et.transformMat4([],[s,a,c,1],t)),n){case"default":return Vl(r,{viewport:e,modelMatrix:t,coordinateSystem:e.isGeospatial?"lnglat":"cartesian",coordinateOrigin:i,offsetMode:o});case"lnglat":return Yp([s,a,c],e,o);case"lnglat-offsets":return Yp([s+i[0],a+i[1],c+(i[2]||0)],e,o);case"meter-offsets":return Yp(Ts(i,[s,a,c]),e,o);case"cartesian":return e.isGeospatial?[s+i[0],a+i[1],c+i[2]]:e.projectPosition([s,a,c]);default:throw new Error(`Invalid coordinateSystem: ${n}`)}}function Wv(r,e){let{viewport:t,coordinateSystem:n,coordinateOrigin:i,modelMatrix:o,fromCoordinateSystem:s,fromCoordinateOrigin:a}=OB(e),{autoOffset:c=!0}=e,{geospatialOrigin:l=Vv,shaderCoordinateOrigin:u=Vv,offsetMode:f=!1}=c?Fp(t,n,i):{},h=Vl(r,{viewport:t,modelMatrix:o,coordinateSystem:s,coordinateOrigin:a,offsetMode:f});if(f){let p=t.projectPosition(l||u);Cn.sub(h,h,p)}return h}var gO={blendColorOperation:"add",blendColorSrcFactor:"one",blendColorDstFactor:"zero",blendAlphaOperation:"add",blendAlphaSrcFactor:"constant",blendAlphaDstFactor:"zero"},Gn=class extends yr{constructor(){super(...arguments),this._colorEncoderState=null}render(e){return"pickingFBO"in e?this._drawPickingBuffer(e):{decodePickingColor:null,stats:super._render(e)}}_drawPickingBuffer({layers:e,layerFilter:t,views:n,viewports:i,onViewportActive:o,pickingFBO:s,deviceRect:{x:a,y:c,width:l,height:u},cullRect:f,effects:h,pass:p="picking",pickZ:m,canvasContext:g,shaderModuleProps:y,clearColor:x}){this.pickZ=m;let v=this._resetColorEncoder(m),_=[a,c,l,u],w=super._render({target:s,layers:e,layerFilter:t,views:n,viewports:i,onViewportActive:o,cullRect:f,effects:h?.filter(S=>S.useInPicking),pass:p,canvasContext:g,isPicking:!0,shaderModuleProps:y,clearColor:x??[0,0,0,0],colorMask:15,scissorRect:_});return this._colorEncoderState=null,{decodePickingColor:v&&yO.bind(null,v),stats:w}}shouldDrawLayer(e){let{pickable:t,operation:n}=e.props;return t&&n.includes("draw")||n.includes("terrain")||n.includes("mask")}getShaderModuleProps(e,t,n){return{picking:{isActive:1,isAttribute:this.pickZ,disabledPickingIndices:e.internalState?.disabledPickingIndices},lighting:{enabled:!1}}}getLayerParameters(e,t,n){let i={...e.props.parameters},{pickable:o,operation:s}=e.props;return this._colorEncoderState?o&&s.includes("draw")?(Object.assign(i,gO),i.blend=!0,this.device.type==="webgpu"?i.blendConstant=ww(this._colorEncoderState,e,n):i.blendColor=ww(this._colorEncoderState,e,n),s.includes("terrain")&&e.state?._hasPickingCover&&(i.blendAlphaSrcFactor="one")):s.includes("terrain")&&(i.blend=!1):i.blend=!1,i}_resetColorEncoder(e){return this._colorEncoderState=e?null:{byLayer:new Map,byAlpha:[]},this._colorEncoderState}};function ww(r,e,t){let{byLayer:n,byAlpha:i}=r,o,s=n.get(e);return s?(s.viewports.push(t),o=s.a):(o=n.size+1,o<=255?(s={a:o,layer:e,viewports:[t]},n.set(e,s),i[o]=s):($.warn("Too many pickable layers, only picking the first 255")(),o=0)),[0,0,0,o/255]}function yO(r,e){let t=r.byAlpha[e[3]];return t&&{pickedLayer:t.layer,pickedViewports:t.viewports,pickedObjectIndex:t.layer.decodePickingColor(e)}}de();var jr={NO_STATE:"Awaiting state",MATCHED:"Matched. State transferred from previous layer",INITIALIZED:"Initialized",AWAITING_GC:"Discarded. Awaiting garbage collection",AWAITING_FINALIZATION:"No longer matched. Awaiting garbage collection",FINALIZED:"Finalized! Awaiting garbage collection"},Hi=Symbol.for("component"),Kt=Symbol.for("propTypes"),Xl=Symbol.for("deprecatedProps"),_r=Symbol.for("asyncPropDefaults"),Qt=Symbol.for("asyncPropOriginal"),At=Symbol.for("asyncPropResolved");function Zl(r,e=()=>!0){return Array.isArray(r)?Ew(r,e,[]):e(r)?[r]:[]}function Ew(r,e,t){let n=-1;for(;++n<r.length;){let i=r[n];Array.isArray(i)?Ew(i,e,t):e(i)&&t.push(i)}return t}function Sw({target:r,source:e,start:t=0,count:n=1}){let i=e.length,o=n*i,s=0;for(let a=t;s<i;s++)r[a++]=e[s];for(;s<o;)s<o-s?(r.copyWithin(t+s,t,t+s),s*=2):(r.copyWithin(t+s,t,t+o-s),s=o);return r}Po();var Gs=class{constructor(e,t,n){this._loadCount=0,this._subscribers=new Set,this.id=e,this.context=n,this.setData(t)}subscribe(e){this._subscribers.add(e)}unsubscribe(e){this._subscribers.delete(e)}inUse(){return this._subscribers.size>0}delete(){}getData(){return this.isLoaded?this._error?Promise.reject(this._error):this._content:this._loader.then(()=>this.getData())}setData(e,t){if(e===this._data&&!t)return;this._data=e;let n=++this._loadCount,i=e;typeof e=="string"&&(i=ai(e)),i instanceof Promise?(this.isLoaded=!1,this._loader=i.then(o=>{this._loadCount===n&&(this.isLoaded=!0,this._error=void 0,this._content=o)}).catch(o=>{this._loadCount===n&&(this.isLoaded=!0,this._error=o||!0)})):(this.isLoaded=!0,this._error=void 0,this._content=e);for(let o of this._subscribers)o.onChange(this.getData())}};var zs=class{constructor(e){this.protocol=e.protocol||"resource://",this._context={device:e.device,gl:e.device?.gl,resourceManager:this},this._resources={},this._consumers={},this._pruneRequest=null}contains(e){return e.startsWith(this.protocol)?!0:e in this._resources}add({resourceId:e,data:t,forceUpdate:n=!1,persistent:i=!0}){let o=this._resources[e];o?o.setData(t,n):(o=new Gs(e,t,this._context),this._resources[e]=o),o.persistent=i}remove(e){let t=this._resources[e];t&&(t.delete(),delete this._resources[e])}unsubscribe({consumerId:e}){let t=this._consumers[e];if(t){for(let n in t){let i=t[n],o=this._resources[i.resourceId];o&&o.unsubscribe(i)}delete this._consumers[e],this.prune()}}subscribe({resourceId:e,onChange:t,consumerId:n,requestId:i="default"}){let{_resources:o,protocol:s}=this;e.startsWith(s)&&(e=e.replace(s,""),o[e]||this.add({resourceId:e,data:null,persistent:!1}));let a=o[e];if(this._track(n,i,a,t),a)return a.getData()}prune(){this._pruneRequest||(this._pruneRequest=setTimeout(()=>this._prune(),0))}finalize(){for(let e in this._resources)this._resources[e].delete()}_track(e,t,n,i){let o=this._consumers,s=o[e]=o[e]||{},a=s[t],c=a&&a.resourceId&&this._resources[a.resourceId];c&&(c.unsubscribe(a),this.prune()),n&&(a?(a.onChange=i,a.resourceId=n.id):a={onChange:i,resourceId:n.id},s[t]=a,n.subscribe(a))}_prune(){this._pruneRequest=null;for(let e of Object.keys(this._resources)){let t=this._resources[e];!t.persistent&&!t.inUse()&&(t.delete(),delete this._resources[e])}}};var _O="layerManager.setLayers",bO="layerManager.activateViewport",$s=class{constructor(e,t){this._lastRenderedLayers=[],this._needsRedraw=!1,this._needsUpdate=!1,this._nextLayers=null,this._debug=!1,this._defaultShaderModulesChanged=!1,this.activateViewport=a=>{me(bO,this,a),a&&(this.context.viewport=a)};let{deck:n,stats:i,viewport:o,timeline:s}=t||{};this.layers=[],this.resourceManager=new zs({device:e,protocol:"deck://"}),this.context={mousePosition:null,userData:{},layerManager:this,device:e,gl:e?.gl,deck:n,shaderAssembler:Ov(e?.info?.shadingLanguage||"glsl"),defaultShaderModules:[Tp],renderPass:void 0,stats:i||new lt({id:"deck.gl"}),viewport:o||new Gi({id:"DEFAULT-INITIAL-VIEWPORT"}),timeline:s||new Un,resourceManager:this.resourceManager,onError:void 0},Object.seal(this)}finalize(){this.resourceManager.finalize();for(let e of this.layers)this._finalizeLayer(e)}needsRedraw(e={clearRedrawFlags:!1}){let t=this._needsRedraw;e.clearRedrawFlags&&(this._needsRedraw=!1);for(let n of this.layers){let i=n.getNeedsRedraw(e);t=t||i}return t}needsUpdate(){return this._nextLayers&&this._nextLayers!==this._lastRenderedLayers?"layers changed":this._defaultShaderModulesChanged?"shader modules changed":this._needsUpdate}setNeedsRedraw(e){this._needsRedraw=this._needsRedraw||e}setNeedsUpdate(e){this._needsUpdate=this._needsUpdate||e}getLayers({layerIds:e}={}){return e?this.layers.filter(t=>e.find(n=>t.id.indexOf(n)===0)):this.layers}setProps(e){"debug"in e&&(this._debug=e.debug),"userData"in e&&(this.context.userData=e.userData),"layers"in e&&(this._nextLayers=e.layers),"onError"in e&&(this.context.onError=e.onError)}setLayers(e,t){me(_O,this,t,e),this._lastRenderedLayers=e;let n=Zl(e,Boolean);for(let i of n)i.context=this.context;this._updateLayers(this.layers,n)}updateLayers(){let e=this.needsUpdate();e&&(this.setNeedsRedraw(`updating layers: ${e}`),this.setLayers(this._nextLayers||this._lastRenderedLayers,e)),this._nextLayers=null}addDefaultShaderModule(e){let{defaultShaderModules:t}=this.context;t.find(n=>n.name===e.name)||(t.push(e),this._defaultShaderModulesChanged=!0)}removeDefaultShaderModule(e){let{defaultShaderModules:t}=this.context,n=t.findIndex(i=>i.name===e.name);n>=0&&(t.splice(n,1),this._defaultShaderModulesChanged=!0)}_handleError(e,t,n){n.raiseError(t,`${e} of ${n}`)}_updateLayers(e,t){let n={};for(let s of e)n[s.id]?$.warn(`Multiple old layers with same id ${s.id}`)():n[s.id]=s;if(this._defaultShaderModulesChanged){for(let s of e)s.setNeedsUpdate(),s.setChangeFlags({extensionsChanged:!0});this._defaultShaderModulesChanged=!1}let i=[];this._updateSublayersRecursively(t,n,i),this._finalizeOldLayers(n);let o=!1;for(let s of i)if(s.hasUniformTransition()){o=`Uniform transition in ${s}`;break}this._needsUpdate=o,this.layers=i}_updateSublayersRecursively(e,t,n){for(let i of e){i.context=this.context;let o=t[i.id];o===null&&$.warn(`Multiple new layers with same id ${i.id}`)(),t[i.id]=null;let s=null;try{this._debug&&o!==i&&i.validateProps(),o?(this._transferLayerState(o,i),this._updateLayer(i)):this._initializeLayer(i),n.push(i),s=i.isComposite?i.getSubLayers():null}catch(a){this._handleError("matching",a,i)}s&&this._updateSublayersRecursively(s,t,n)}}_finalizeOldLayers(e){for(let t in e){let n=e[t];n&&this._finalizeLayer(n)}}_initializeLayer(e){try{e._initialize(),e.lifecycle=jr.INITIALIZED}catch(t){this._handleError("initialization",t,e)}}_transferLayerState(e,t){t._transferState(e),t.lifecycle=jr.MATCHED,t!==e&&(e.lifecycle=jr.AWAITING_GC)}_updateLayer(e){try{e._update()}catch(t){this._handleError("update",t,e)}}_finalizeLayer(e){this._needsRedraw=this._needsRedraw||`finalized ${e}`,e.lifecycle=jr.AWAITING_FINALIZATION;try{e._finalize(),e.lifecycle=jr.FINALIZED}catch(t){this._handleError("finalization",t,e)}}};function ce(r,e,t){if(r===e)return!0;if(!t||!r||!e)return!1;if(Array.isArray(r)){if(!Array.isArray(e)||r.length!==e.length)return!1;for(let n=0;n<r.length;n++)if(!ce(r[n],e[n],t-1))return!1;return!0}if(Array.isArray(e))return!1;if(typeof r=="object"&&typeof e=="object"){let n=Object.keys(r),i=Object.keys(e);if(n.length!==i.length)return!1;for(let o of n)if(!e.hasOwnProperty(o)||!ce(r[o],e[o],t-1))return!1;return!0}return!1}var Hr="default-canvas",Vs=class{constructor(e){this.views=[],this.width=100,this.height=100,this.viewState={},this.controllers={},this.timeline=e.timeline,this._viewports=[],this._viewportMap={},this._isUpdating=!1,this._needsRedraw="First render",this._needsUpdate="Initialize",this._eventManager=e.eventManager,this._eventManagers=e.eventManagers||{},this._viewEventManagers={},this._eventCallbacks={onViewStateChange:e.onViewStateChange,onInteractionStateChange:e.onInteractionStateChange},this._pickPosition=e.pickPosition,this._getCanvasContext=e.getCanvasContext,Object.seal(this),this.setProps(e)}finalize(){for(let e in this.controllers){let t=this.controllers[e];t&&t.finalize()}this.controllers={}}needsRedraw(e={clearRedrawFlags:!1}){let t=this._needsRedraw;return e.clearRedrawFlags&&(this._needsRedraw=!1),t}setNeedsUpdate(e){this._needsUpdate=this._needsUpdate||e,this._needsRedraw=this._needsRedraw||e}updateViewStates(){for(let e in this.controllers){let t=this.controllers[e];t&&t.updateTransition()}}getViewports(e){return e?this._viewports.filter(t=>{let n=!e.canvasId||this.getCanvasId(t.id)===e.canvasId,i=!("x"in e)||t.containsPixel(e);return n&&i}):this._viewports}getViews(){let e={};return this.views.forEach(t=>{e[t.id]=t}),e}getView(e){return this.views.find(t=>t.id===e)}getViewState(e){let t=typeof e=="string"?this.getView(e):e,n=t&&this.viewState[t.getViewStateId()]||this.viewState;return t?t.filterViewState(n):n}getViewport(e){return this._viewportMap[e]}getCanvasId(e){let t=typeof e=="string"?this.getView(e):e;return t?this._viewEventManagers[t.id]?.canvasId||this._getCanvasIdFromView(t):void 0}unproject(e,t){let n=this.getViewports(),i={x:e[0],y:e[1]};for(let o=n.length-1;o>=0;--o){let s=n[o];if(s.containsPixel(i)){let a=e.slice();return a[0]-=s.x,a[1]-=s.y,s.unproject(a,t)}}return null}setProps(e){e.views&&this._setViews(e.views),e.viewState&&this._setViewState(e.viewState),("width"in e||"height"in e)&&this._setSize(e.width,e.height),"pickPosition"in e&&(this._pickPosition=e.pickPosition),"eventManagers"in e&&this._setEventManagers(e.eventManagers||{}),this._isUpdating||this._update()}_update(){this._isUpdating=!0,this._needsUpdate&&(this._needsUpdate=!1,this._rebuildViewports()),this._needsUpdate&&(this._needsUpdate=!1,this._rebuildViewports()),this._isUpdating=!1}_setSize(e,t){(e!==this.width||t!==this.height)&&(this.width=e,this.height=t,this.setNeedsUpdate("Size changed"))}_setViews(e){e=Zl(e,Boolean),this._diffViews(e,this.views)&&this.setNeedsUpdate("views changed"),this.views=e}_setViewState(e){e?(!ce(e,this.viewState,3)&&this.setNeedsUpdate("viewState changed"),this.viewState=e):$.warn("missing `viewState` or `initialViewState`")()}_setEventManagers(e){this._eventManagers!==e&&(this._eventManagers=e,this.setNeedsUpdate("eventManagers changed"))}_getCanvasIdFromView(e){return e.props.canvasId||this._getCanvasContext?.(e.id)?.id||Hr}_getCanvasDimensions(e){let t=this._getCanvasContext?.(e.id),[n,i]=t?.getCSSSize()||[this.width,this.height];return{width:n,height:i}}_getViewEventManager(e){let t=this.getCanvasId(e)||Hr;return{canvasId:t,eventManager:this._eventManagers[t]||this._eventManager}}_startViewportRebuild(){let e=this.controllers,t=this._viewEventManagers;return this._viewports=[],this.controllers={},this._viewEventManagers={},{oldControllers:e,oldViewEventManagers:t}}_getReusableController(e,t,n){return e&&(t?.canvasId!==n.canvasId||t?.eventManager!==n.eventManager)?(e.finalize(),null):e}_createController(e,t){let n=t.type;return new n({timeline:this.timeline,eventManager:this._getViewEventManager(e).eventManager,onViewStateChange:this._eventCallbacks.onViewStateChange,onStateChange:this._eventCallbacks.onInteractionStateChange,makeViewport:o=>this.getView(e.id)?.makeViewport({viewState:o,...this._getCanvasDimensions(e)}),pickPosition:(o,s)=>this._pickPosition?.(o,s,e.id)})}_updateController(e,t,n,i){let o=e.controller;if(o&&n){let s={...t,...o,id:e.id,x:n.x,y:n.y,width:n.width,height:n.height};return(!i||i.constructor!==o.type)&&(i=this._createController(e,s)),i&&i.setProps(s),i}return null}_rebuildViewports(){let{views:e}=this,{oldControllers:t,oldViewEventManagers:n}=this._startViewportRebuild(),i=!1;for(let o=e.length;o--;){let s=e[o],{width:a,height:c}=this._getCanvasDimensions(s),l=this._getViewEventManager(s);this._viewEventManagers[s.id]=l;let u=this.getViewState(s),f=s.makeViewport({viewState:u,width:a,height:c}),h=this._getReusableController(t[s.id],n[s.id],l),p=!!s.controller;p&&!h&&(i=!0),(i||!p)&&h&&(h.finalize(),h=null),this.controllers[s.id]=this._updateController(s,u,f,h),f&&this._viewports.unshift(f)}for(let o in t){let s=t[o];s&&!this.controllers[o]&&s.finalize()}this._buildViewportMap()}_buildViewportMap(){this._viewportMap={},this._viewports.forEach(e=>{e.id&&(this._viewportMap[e.id]=this._viewportMap[e.id]||e)})}_diffViews(e,t){return e.length!==t.length?!0:e.some((n,i)=>!e[i].equals(t[i]))}};var xO=/^(?:\d+\.?\d*|\.\d+)$/;function Xe(r){switch(typeof r){case"number":if(!Number.isFinite(r))throw new Error(`Could not parse position string ${r}`);return{type:"literal",value:r};case"string":try{let e=vO(r);return new am(e).parseExpression()}catch(e){let t=e instanceof Error?e.message:String(e);throw new Error(`Could not parse position string ${r}: ${t}`)}default:throw new Error(`Could not parse position string ${r}`)}}function sm(r,e){switch(r.type){case"literal":return r.value;case"percentage":return Math.round(r.value*e);case"binary":let t=sm(r.left,e),n=sm(r.right,e);return r.operator==="+"?t+n:t-n;default:throw new Error("Unknown layout expression type")}}function Ze(r,e){return sm(r,e)}function vO(r){let e=[],t=0;for(;t<r.length;){let n=r[t];if(/\s/.test(n)){t++;continue}if(n==="+"||n==="-"||n==="("||n===")"||n==="%"){e.push({type:"symbol",value:n}),t++;continue}if(Pw(n)||n==="."){let i=t,o=n===".";for(t++;t<r.length;){let a=r[t];if(Pw(a)){t++;continue}if(a==="."&&!o){o=!0,t++;continue}break}let s=r.slice(i,t);if(!xO.test(s))throw new Error("Invalid number token");e.push({type:"number",value:parseFloat(s)});continue}if(Tw(n)){let i=t;for(;t<r.length&&Tw(r[t]);)t++;let o=r.slice(i,t).toLowerCase();e.push({type:"word",value:o});continue}throw new Error("Invalid token in position string")}return e}var am=class{constructor(e){this.index=0,this.tokens=e}parseExpression(){let e=this.parseBinaryExpression();if(this.index<this.tokens.length)throw new Error("Unexpected token at end of expression");return e}parseBinaryExpression(){let e=this.parseFactor(),t=this.peek();for(;wO(t);){this.index++;let n=this.parseFactor();e={type:"binary",operator:t.value,left:e,right:n},t=this.peek()}return e}parseFactor(){let e=this.peek();if(!e)throw new Error("Unexpected end of expression");if(e.type==="symbol"&&e.value==="+")return this.index++,this.parseFactor();if(e.type==="symbol"&&e.value==="-"){this.index++;let t=this.parseFactor();return{type:"binary",operator:"-",left:{type:"literal",value:0},right:t}}if(e.type==="symbol"&&e.value==="("){this.index++;let t=this.parseBinaryExpression();if(!this.consumeSymbol(")"))throw new Error("Missing closing parenthesis");return t}if(e.type==="word"&&e.value==="calc"){if(this.index++,!this.consumeSymbol("("))throw new Error("Missing opening parenthesis after calc");let t=this.parseBinaryExpression();if(!this.consumeSymbol(")"))throw new Error("Missing closing parenthesis");return t}if(e.type==="number"){this.index++;let t=e.value,n=this.peek();return n&&n.type==="symbol"&&n.value==="%"?(this.index++,{type:"percentage",value:t/100}):n&&n.type==="word"&&n.value==="px"?(this.index++,{type:"literal",value:t}):{type:"literal",value:t}}throw new Error("Unexpected token in expression")}consumeSymbol(e){let t=this.peek();return t&&t.type==="symbol"&&t.value===e?(this.index++,!0):!1}peek(){return this.tokens[this.index]||null}};function Pw(r){return r>="0"&&r<="9"}function Tw(r){return r>="a"&&r<="z"||r>="A"&&r<="Z"}function wO(r){return!!(r&&r.type==="symbol"&&(r.value==="+"||r.value==="-"))}function Lw(r,e){let t={...r};for(let n in e)n!=="id"&&(Array.isArray(t[n])&&Array.isArray(e[n])?t[n]=EO(t[n],e[n]):t[n]=e[n]);return t}function EO(r,e){r=r.slice();for(let t=0;t<e.length;t++){let n=e[t];Number.isFinite(n)&&(r[t]=n)}return r}var zn=class{constructor(e){let{id:t,x:n=0,y:i=0,width:o="100%",height:s="100%",padding:a=null}=e;this.id=t||this.constructor.displayName||"view",this.props={...e,id:this.id},this._x=Xe(n),this._y=Xe(i),this._width=Xe(o),this._height=Xe(s),this._padding=a&&{left:Xe(a.left||0),right:Xe(a.right||0),top:Xe(a.top||0),bottom:Xe(a.bottom||0)},this.equals=this.equals.bind(this),Object.seal(this)}equals(e){return this===e?!0:this.constructor===e.constructor&&ce(this.props,e.props,2)}clone(e){let t=this.constructor;return new t({...this.props,...e})}makeViewport({width:e,height:t,viewState:n}){n=this.filterViewState(n);let i=this.getDimensions({width:e,height:t});if(!i.height||!i.width)return null;let o=this.getViewportType(n);return new o({...n,...this.props,...i})}getViewStateId(){let{viewState:e}=this.props;return typeof e=="string"?e:e?.id||this.id}filterViewState(e){return this.props.viewState&&typeof this.props.viewState=="object"?this.props.viewState.id?Lw(e,this.props.viewState):this.props.viewState:e}getDimensions({width:e,height:t}){let n={x:Ze(this._x,e),y:Ze(this._y,t),width:Ze(this._width,e),height:Ze(this._height,t)};return this._padding&&(n.padding={left:Ze(this._padding.left,e),top:Ze(this._padding.top,t),right:Ze(this._padding.right,e),bottom:Ze(this._padding.bottom,t)}),n}get controller(){let e=this.props.controller;return e?e===!0?{type:this.ControllerType}:typeof e=="function"?{type:e}:{type:this.ControllerType,...e}:null}};Ee();var Ct=class{constructor(e){this._inProgress=!1,this._handle=null,this.time=0,this.settings={duration:0},this._timeline=e}get inProgress(){return this._inProgress}start(e){this.cancel(),this.settings=e,this._inProgress=!0,this.settings.onStart?.(this)}end(){this._inProgress&&(this._timeline.removeChannel(this._handle),this._handle=null,this._inProgress=!1,this.settings.onEnd?.(this))}cancel(){this._inProgress&&(this.settings.onInterrupt?.(this),this._timeline.removeChannel(this._handle),this._handle=null,this._inProgress=!1)}update(){if(!this._inProgress)return!1;if(this._handle===null){let{_timeline:e,settings:t}=this;this._handle=e.addChannel({delay:e.getTime(),duration:t.duration})}return this.time=this._timeline.getTime(this._handle),this._onUpdate(),this.settings.onUpdate?.(this),this._timeline.isFinished(this._handle)&&this.end(),!0}_onUpdate(){}};var Aw=()=>{},Cw={mode:"preserve"},SO={mode:"hard"},cm={BREAK:1,SNAP_TO_END:2,IGNORE:3},PO=r=>r,TO=cm.BREAK,Ws=class{constructor(e){this._onTransitionUpdate=t=>{let{time:n,settings:{interpolator:i,startProps:o,endProps:s,duration:a,easing:c}}=t,l=c(n/a),u=i.interpolateProps(o,s,l);this.propsInTransition=this.getControllerState({...this.props,...u},Cw).getViewportProps(),this.onViewStateChange({viewState:this.propsInTransition,oldViewState:this.props})},this.getControllerState=e.getControllerState,this.propsInTransition=null,this.transition=new Ct(e.timeline),this.onViewStateChange=e.onViewStateChange||Aw,this.onStateChange=e.onStateChange||Aw}finalize(){this.transition.cancel()}getViewportInTransition(){return this.propsInTransition}processViewStateChange(e){let t=!1,n=this.props;if(this.props=e,!n||this._shouldIgnoreViewportChange(n,e))return!1;if(this._isTransitionEnabled(e)){let i=n;if(this.transition.inProgress){let{interruption:o,endProps:s}=this.transition.settings;i={...n,...o===cm.SNAP_TO_END?s:this.propsInTransition||n}}this._triggerTransition(i,e),t=!0}else this.transition.cancel();return t}updateTransition(){this.transition.update()}_isTransitionEnabled(e){let{transitionDuration:t,transitionInterpolator:n}=e;return(t>0||t==="auto")&&!!n}_isUpdateDueToCurrentTransition(e){return this.transition.inProgress&&this.propsInTransition?this.transition.settings.interpolator.arePropsEqual(e,this.propsInTransition):!1}_shouldIgnoreViewportChange(e,t){return this.transition.inProgress?this.transition.settings.interruption===cm.IGNORE||this._isUpdateDueToCurrentTransition(t):this._isTransitionEnabled(t)?t.transitionInterpolator.arePropsEqual(e,t):!0}_triggerTransition(e,t){let n=this.getControllerState(e,Cw),i=this.getControllerState(t,SO).shortestPathFrom(n),o=t.transitionInterpolator,s=o.getDuration?o.getDuration(e,t):t.transitionDuration;if(s===0)return;let a=o.initializeProps(e,i);this.propsInTransition={};let c={duration:s,easing:t.transitionEasing||PO,interpolator:o,interruption:t.transitionInterruption||TO,startProps:a.start,endProps:a.end,onStart:t.onTransitionStart,onUpdate:this._onTransitionUpdate,onInterrupt:this._onTransitionEnd(t.onTransitionInterrupt),onEnd:this._onTransitionEnd(t.onTransitionEnd)};this.transition.start(c),this.onStateChange({inTransition:!0}),this.updateTransition()}_onTransitionEnd(e){return t=>{this.propsInTransition=null,this.onStateChange({inTransition:!1,isZooming:!1,isPanning:!1,isRotating:!1}),e?.(t)}}};Ee();function q(r,e){if(!r)throw new Error(e||"deck.gl: assertion failed.")}var js=class{constructor(e){let{compare:t,extract:n,required:i}=e;this._propsToCompare=t,this._propsToExtract=n||t,this._requiredProps=i}arePropsEqual(e,t){for(let n of this._propsToCompare)if(!(n in e)||!(n in t)||!Wt(e[n],t[n]))return!1;return!0}initializeProps(e,t){let n={},i={};for(let o of this._propsToExtract)(o in e||o in t)&&(n[o]=e[o],i[o]=t[o]);return this._checkRequiredProps(n),this._checkRequiredProps(i),{start:n,end:i}}getDuration(e,t){return t.transitionDuration}_checkRequiredProps(e){this._requiredProps&&this._requiredProps.forEach(t=>{let n=e[t];q(Number.isFinite(n)||Array.isArray(n),`${t} is required for transition`)})}};Ee();var LO=["longitude","latitude","zoom","bearing","pitch"],AO=["longitude","latitude","zoom"],br=class extends js{constructor(e={}){let t=Array.isArray(e)?e:e.transitionProps,n=Array.isArray(e)?{}:e;n.transitionProps=Array.isArray(t)?{compare:t,required:t}:t||{compare:LO,required:AO},super(n.transitionProps),this.opts=n}initializeProps(e,t){let n=super.initializeProps(e,t),{makeViewport:i,around:o}=this.opts;if(i&&o){let s=i(e),a=i(t),c=s.unproject(o);n.start.around=o,Object.assign(n.end,{around:a.project(c),aroundPosition:c,width:t.width,height:t.height})}return n}interpolateProps(e,t,n){let i={};for(let o of this._propsToExtract)i[o]=Tn(e[o]||0,t[o]||0,n);if(t.aroundPosition&&this.opts.makeViewport){let o=this.opts.makeViewport({...t,...i});Object.assign(i,o.panByPosition(t.aroundPosition,Tn(e.around,t.around,n)))}return i}};var Jt={transitionDuration:0},CO=300,MO=300,lm=r=>1-(1-r)*(1-r),IO=r=>r===1?1:1-Math.pow(2,-10*r),$n={WHEEL:["wheel"],PAN:["panstart","panmove","panend"],PINCH:["pinchstart","pinchmove","pinchend"],MULTI_PAN:["multipanstart","multipanmove","multipanend"],DOUBLE_CLICK:["dblclick"],DOUBLE_CLICK_DRAG:["dblclickdragstart","dblclickdragmove","dblclickdragend","dblclickdragcancel"],KEYBOARD:["keydown"]},Vn={},Wn=class{constructor(e){this.state={},this._events={},this._interactionState={isDragging:!1},this._customEvents=[],this._eventStartBlocked=null,this._panMove=!1,this._multiPanMode=null,this._multiPanStartCenter=null,this._doubleClickDragAnchor=null,this._suppressDoubleClickUntil=0,this.invertPan=!1,this.dragMode="rotate",this.inertia=0,this.scrollZoom=!0,this.dragPan=!0,this.dragRotate=!0,this.doubleClickZoom=!0,this.doubleClickDragZoom=!0,this.touchZoom=!0,this.touchRotate=!1,this.multiTouchDrag=null,this.trackpadGesture=!1,this.zoomAround="pointer",this.keyboard=!0,this.transitionManager=new Ws({...e,getControllerState:(t,n)=>new this.ControllerState({...t,constraintContext:n,makeViewport:e.makeViewport}),onViewStateChange:this._onTransition.bind(this),onStateChange:this._setInteractionState.bind(this)}),this.handleEvent=this.handleEvent.bind(this),this.eventManager=e.eventManager,this.onViewStateChange=e.onViewStateChange||(()=>{}),this.onStateChange=e.onStateChange||(()=>{}),this.makeViewport=e.makeViewport,this.pickPosition=e.pickPosition}set events(e){this.toggleEvents(this._customEvents,!1),this.toggleEvents(e,!0),this._customEvents=e,this.props&&this.setProps(this.props)}finalize(){for(let e in this._events)this._events[e]&&this.eventManager?.off(e,this.handleEvent);this.transitionManager.finalize()}handleEvent(e){this._controllerState=void 0;let t=this._eventStartBlocked;switch(e.type){case"panstart":return t?!1:this._onPanStart(e);case"panmove":return this._onPan(e);case"panend":return this._onPanEnd(e);case"pinchstart":return t||!this._isTrackpadGestureAllowed(e)?!1:this._onPinchStart(e);case"pinchmove":return this._isTrackpadGestureAllowed(e)?this._onPinch(e):!1;case"pinchend":return this._isTrackpadGestureAllowed(e)?this._onPinchEnd(e):!1;case"multipanstart":return t?!1:this._onMultiPanStart(e);case"multipanmove":return this._onMultiPan(e);case"multipanend":return this._onMultiPanEnd(e);case"dblclick":return this._onDoubleClick(e);case"dblclickdragstart":return t?!1:this._onDoubleClickDragStart(e);case"dblclickdragmove":return this._onDoubleClickDrag(e);case"dblclickdragend":case"dblclickdragcancel":return this._onDoubleClickDragEnd(e);case"wheel":return this._onWheel(e);case"keydown":return this._onKeyDown(e);default:return!1}}get controllerState(){return this._controllerState=this._controllerState||new this.ControllerState({makeViewport:this.makeViewport,...this.props,...this.state}),this._controllerState}getCenter(e){let{x:t,y:n}=this.props,{offsetCenter:i}=e;return[i.x-t,i.y-n]}getZoomPosition(e){if(this.zoomAround==="pointer")return e;let t=this.makeViewport(this.controllerState.getViewportProps()),[n,i]=Vr(t.center,t.pixelProjectionMatrix);return[n,i]}isPointInBounds(e,t){let{width:n,height:i}=this.props;if(t&&t.handled)return!1;let o=e[0]>=0&&e[0]<=n&&e[1]>=0&&e[1]<=i;return o&&t&&t.stopPropagation(),o}isFunctionKeyPressed(e){let{srcEvent:t}=e;return!!(t.metaKey||t.altKey||t.ctrlKey||t.shiftKey)}isDragging(){return this._interactionState.isDragging||!1}blockEvents(e){let t=setTimeout(()=>{this._eventStartBlocked===t&&(this._eventStartBlocked=null)},e);this._eventStartBlocked=t}setProps(e){e.maxBoundsPadding===void 0&&(e.maxBoundsPadding=null),e.dragMode&&(this.dragMode=e.dragMode);let t=this.props;this.props=e,"transitionInterpolator"in e||(e.transitionInterpolator=this._getTransitionProps().transitionInterpolator),this.transitionManager.processViewStateChange(e);let{inertia:n}=e;this.inertia=Number.isFinite(n)?n:n===!0?CO:0;let{scrollZoom:i=!0,dragPan:o=!0,dragRotate:s=!0,doubleClickZoom:a=!0,doubleClickDragZoom:c=!1,touchZoom:l=!0,touchRotate:u=!1,multiTouchDrag:f=u?"rotate":null,trackpadGesture:h=!1,zoomAround:p="pointer",keyboard:m=!0}=e,g=!!this.onViewStateChange;if(this.toggleEvents($n.WHEEL,g&&i),this.toggleEvents($n.PAN,g),this.toggleEvents($n.PINCH,g&&(l||f==="rotate")),this.toggleEvents($n.MULTI_PAN,g&&!!f),this.toggleEvents($n.DOUBLE_CLICK,g&&a),this.toggleEvents($n.DOUBLE_CLICK_DRAG,g&&c),this.toggleEvents($n.KEYBOARD,g&&m),this.scrollZoom=i,this.dragPan=o,this.dragRotate=s,this.doubleClickZoom=a,this.doubleClickDragZoom=c,this.touchZoom=l,this.touchRotate=f==="rotate",this.multiTouchDrag=f,this.trackpadGesture=h,this.zoomAround=p,this.keyboard=m,(!t||t.height!==e.height||t.width!==e.width||t.maxBounds!==e.maxBounds||t.maxBoundsPadding!==e.maxBoundsPadding)&&e.maxBounds){let x=new this.ControllerState({...e,makeViewport:this.makeViewport}),v=x.getViewportProps();Object.keys(v).some(w=>!ce(v[w],e[w],1))&&this.updateViewport(x)}}updateTransition(){this.transitionManager.updateTransition()}toggleEvents(e,t){this.eventManager&&e.forEach(n=>{this._events[n]!==t&&(this._events[n]=t,t?this.eventManager.on(n,this.handleEvent):this.eventManager.off(n,this.handleEvent))})}updateViewport(e,t=null,n={}){let i={...e.getViewportProps(),...t},o=this.controllerState!==e;if(this.state=e.getState(),this._setInteractionState(n),o){let s=this.controllerState&&this.controllerState.getViewportProps();this.onViewStateChange&&this.onViewStateChange({viewState:i,interactionState:this._interactionState,oldViewState:s,viewId:this.props.id})}}_onTransition(e){this.onViewStateChange({...e,interactionState:this._interactionState,viewId:this.props.id})}_setInteractionState(e){Object.assign(this._interactionState,e),this.onStateChange(this._interactionState)}_getConstraintContext(e,t){return this.props.rubberBand?{mode:t==="update"?"elastic":t==="end"?"rebound":"hard"}:{mode:"hard"}}_getReboundTransition(e,t){if(e.mode!=="rebound")return null;let n=t.getViewportProps();return Object.keys(n).some(o=>!ce(this.props[o],n[o],1))?{...this._getTransitionProps(),transitionDuration:MO,transitionEasing:IO}:null}_onPanStart(e){let t=this.getCenter(e);if(!this.isPointInBounds(t,e))return!1;let n=this.isFunctionKeyPressed(e)||e.rightButton||!1;(this.invertPan||this.dragMode==="pan")&&(n=!n);let i=n?"pan":"rotate",o=this._getConstraintContext(i,"start"),s=n?this.controllerState.panStart({pos:t},o):this.controllerState.rotateStart({pos:t},o);return this._panMove=n,this.updateViewport(s,Jt,{isDragging:!0}),!0}_onPan(e){return this.isDragging()?this._panMove?this._onPanMove(e):this._onPanRotate(e):!1}_onPanEnd(e){return this.isDragging()?this._panMove?this._onPanMoveEnd(e):this._onPanRotateEnd(e):!1}_onPanMove(e){if(!this.dragPan)return!1;let t=this.getCenter(e),n=this.controllerState.pan({pos:t},this._getConstraintContext("pan","update"));return this.updateViewport(n,Jt,{isDragging:!0,isPanning:!0}),!0}_onPanMoveEnd(e){let{inertia:t}=this;if(this.dragPan&&t&&e.velocity){let n=this.getCenter(e),i=[n[0]+e.velocityX*t/2,n[1]+e.velocityY*t/2],o=this.controllerState.pan({pos:i}).panEnd();this.updateViewport(o,{...this._getTransitionProps(),transitionDuration:t,transitionEasing:lm},{isDragging:!1,isPanning:!0})}else{let n=this.controllerState,i=this._getConstraintContext("pan","end"),o=n.panEnd(i),s=this._getReboundTransition(i,o);this.updateViewport(o,s,{isDragging:!1,isPanning:!!s})}return!0}_onPanRotate(e){if(!this.dragRotate)return!1;let t=this.getCenter(e),n=this.controllerState.rotate({pos:t},this._getConstraintContext("rotate","update"));return this.updateViewport(n,Jt,{isDragging:!0,isRotating:!0}),!0}_onPanRotateEnd(e){let{inertia:t}=this;if(this.dragRotate&&t&&e.velocity){let n=this.getCenter(e),i=[n[0]+e.velocityX*t/2,n[1]+e.velocityY*t/2],o=this.controllerState.rotate({pos:i}).rotateEnd();this.updateViewport(o,{...this._getTransitionProps(),transitionDuration:t,transitionEasing:lm},{isDragging:!1,isRotating:!0})}else{let n=this.controllerState,i=this._getConstraintContext("rotate","end"),o=n.rotateEnd(i),s=this._getReboundTransition(i,o);this.updateViewport(o,s,{isDragging:!1,isRotating:!!s})}return!0}_onWheel(e){if(!this.scrollZoom||this.trackpadGesture&&e.device!=="mouse")return!1;let t=this.getCenter(e);if(!this.isPointInBounds(t,e))return!1;e.srcEvent.preventDefault();let{speed:n=.01,smooth:i=!1}=this.scrollZoom===!0?{}:this.scrollZoom,{delta:o}=e,s=2/(1+Math.exp(-Math.abs(o*n)));o<0&&s!==0&&(s=1/s);let a=this.getZoomPosition(t),c=i?{...this._getTransitionProps({around:a}),transitionDuration:250}:Jt,l=this.controllerState.zoom({pos:a,scale:s});return this.updateViewport(l,c,{isZooming:!0,isPanning:!0}),i||this._setInteractionState({isZooming:!1,isPanning:!1}),!0}_onMultiPanStart(e){let{multiTouchDrag:t}=this;if(!t||!this._isMultiPanEventAllowed(e,t))return!1;let n=e.offsetCenter;if(!this.isPointInBounds(this.getCenter(e),e))return!1;let i=e.pointerType==="trackpad",o={x:n.x-(i?0:e.deltaX),y:n.y-(i?0:e.deltaY)},s={...e,offsetCenter:o},a=this.getCenter(s),c=t==="pan"?this.controllerState.panStart({pos:a},this._getConstraintContext("pan","start")):this.controllerState.rotateStart({pos:a},this._getConstraintContext("rotate","start"));return this._multiPanMode=t,this._multiPanStartCenter=o,this.updateViewport(c,Jt,{isDragging:!0}),!0}_onMultiPan(e){let{mode:t,event:n}=this._getMultiPanEvent(e);return!t||!n||!this.isDragging()?!1:t==="pan"?this._onPanMove(n):this._onPanRotate(n)}_onMultiPanEnd(e){let{mode:t,event:n}=this._getMultiPanEvent(e);if(!t||!n||!this.isDragging())return this._resetMultiPan(),!1;let i=t==="pan"?this._onPanMoveEnd(n):this._onPanRotateEnd(n);return this._resetMultiPan(),i}_isTrackpadGestureAllowed(e){return e.pointerType!=="trackpad"||this.trackpadGesture}_isMultiPanEventAllowed(e,t){return e.pointerType==="trackpad"?this.trackpadGesture&&(t==="pan"?this.dragPan:this.dragRotate):e.pointerType==="touch"&&(t==="pan"?this.dragPan:this.dragRotate)}_getMultiPanEvent(e){let t=this._multiPanMode,n=this._multiPanStartCenter;return!t||!n?{mode:null,event:null}:{mode:t,event:{...e,offsetCenter:{x:n.x+e.deltaX,y:n.y+e.deltaY}}}}_resetMultiPan(){this._multiPanMode=null,this._multiPanStartCenter=null}_onPinchStart(e){this._doubleClickDragAnchor=null;let t=this.getCenter(e);if(!this.isPointInBounds(t,e))return!1;let n=this.controllerState.zoomStart({pos:this.getZoomPosition(t)},this._getConstraintContext("zoom","start")).rotateStart({pos:t},this._getConstraintContext("rotate","start"));return Vn._startPinchRotation=e.rotation,Vn._lastPinchEvent=e,this.updateViewport(n,Jt,{isDragging:!0}),!0}_onPinch(e){if(!this.touchZoom&&!this.touchRotate||!this.isDragging())return!1;let t=this.controllerState;if(this.touchZoom){let{scale:n}=e,i=this.getCenter(e);t=t.zoom({pos:this.getZoomPosition(i),scale:n},this._getConstraintContext("zoom","update"))}if(this.touchRotate){let{rotation:n}=e;t=t.rotate({deltaAngleX:Vn._startPinchRotation-n},this._getConstraintContext("rotate","update"))}return this.updateViewport(t,Jt,{isDragging:!0,isPanning:this.touchZoom,isZooming:this.touchZoom,isRotating:this.touchRotate}),Vn._lastPinchEvent=e,!0}_onPinchEnd(e){if(!this.isDragging())return!1;let{inertia:t}=this,{_lastPinchEvent:n}=Vn;if(this.touchZoom&&t&&n&&e.scale!==n.scale){let i=this.getCenter(e),o=this.getZoomPosition(i),s=this.controllerState.rotateEnd(),a=Math.log2(e.scale),c=(a-Math.log2(n.scale))/(e.deltaTime-n.deltaTime),l=Math.pow(2,a+c*t/2);s=s.zoom({pos:o,scale:l}).zoomEnd(),this.updateViewport(s,{...this._getTransitionProps({around:o}),transitionDuration:t,transitionEasing:lm},{isDragging:!1,isPanning:this.touchZoom,isZooming:this.touchZoom,isRotating:!1}),this.blockEvents(t)}else{let i=this.controllerState,o=this._getConstraintContext("zoom","end"),s=this._getConstraintContext("rotate","end"),a=i.zoomEnd(o).rotateEnd(s),c=this._getReboundTransition(this.touchZoom?o:s,a);this.updateViewport(a,c,{isDragging:!1,isPanning:!!c&&this.touchZoom,isZooming:!!c&&this.touchZoom,isRotating:!!c&&this.touchRotate})}return Vn._startPinchRotation=null,Vn._lastPinchEvent=null,!0}_onDoubleClick(e){if(!this.doubleClickZoom||Date.now()<this._suppressDoubleClickUntil)return!1;let t=this.getCenter(e);if(!this.isPointInBounds(t,e))return!1;let n=this.isFunctionKeyPressed(e),i=this.getZoomPosition(t),o=this.controllerState.zoom({pos:i,scale:n?.5:2});return this.updateViewport(o,this._getTransitionProps({around:i}),{isZooming:!0,isPanning:!0}),this.blockEvents(100),!0}_onDoubleClickDragStart(e){if(!this.doubleClickDragZoom)return this._doubleClickDragAnchor=null,!1;let t=this.getCenter(e);if(!this.isPointInBounds(t,e))return this._doubleClickDragAnchor=null,!1;this._doubleClickDragAnchor=this.getZoomPosition(t);let n=this.controllerState.zoomStart({pos:this._doubleClickDragAnchor},this._getConstraintContext("zoom","start"));return e.scale!==1&&(n=n.zoom({pos:this._doubleClickDragAnchor,scale:e.scale},this._getConstraintContext("zoom","update"))),this.updateViewport(n,Jt,{isDragging:!0,isPanning:!0,isZooming:!0}),!0}_onDoubleClickDrag(e){let t=this._doubleClickDragAnchor;if(!t)return!1;let n=this.controllerState.zoom({pos:t,scale:e.scale},this._getConstraintContext("zoom","update"));return this.updateViewport(n,Jt,{isDragging:!0,isPanning:!0,isZooming:!0}),!0}_onDoubleClickDragEnd(e){if(!this._doubleClickDragAnchor)return!1;this._doubleClickDragAnchor=null;let n=this.controllerState,i=this._getConstraintContext("zoom","end"),o=n.zoomEnd(i),s=this._getReboundTransition(i,o);return this.updateViewport(o,s,{isDragging:!1,isPanning:!!s,isZooming:!!s}),this._suppressDoubleClickUntil=Date.now()+100,this.blockEvents(100),!0}_onKeyDown(e){if(!this.keyboard)return!1;let t=this.isFunctionKeyPressed(e),{zoomSpeed:n,moveSpeed:i,rotateSpeedX:o,rotateSpeedY:s}=this.keyboard===!0?{}:this.keyboard,{controllerState:a}=this,c,l={};switch(e.srcEvent.code){case"Minus":c=t?a.zoomOut(n).zoomOut(n):a.zoomOut(n),l.isZooming=!0;break;case"Equal":c=t?a.zoomIn(n).zoomIn(n):a.zoomIn(n),l.isZooming=!0;break;case"ArrowLeft":t?(c=a.rotateLeft(o),l.isRotating=!0):(c=a.moveLeft(i),l.isPanning=!0);break;case"ArrowRight":t?(c=a.rotateRight(o),l.isRotating=!0):(c=a.moveRight(i),l.isPanning=!0);break;case"ArrowUp":t?(c=a.rotateUp(s),l.isRotating=!0):(c=a.moveUp(i),l.isPanning=!0);break;case"ArrowDown":t?(c=a.rotateDown(s),l.isRotating=!0):(c=a.moveDown(i),l.isPanning=!0);break;default:return!1}return this.updateViewport(c,this._getTransitionProps(),l),!0}_getTransitionProps(e){let{transition:t}=this;return!t||!t.transitionInterpolator?Jt:e?{...t,transitionInterpolator:new br({...e,...t.transitionInterpolator.opts,makeViewport:this.controllerState.makeViewport})}:t}};var _t=Symbol("constraintAround"),jn=class{constructor(e,t,n,i){this.makeViewport=n,this._viewportProps=this.applyConstraints(e,i),this._state=t}getViewportProps(){return this._viewportProps}getState(){return this._state}};function Yr(r,e,t){let n=r-e;return n&&Number.isFinite(n)?e+n*t/(t+Math.abs(n)):e}function Yi(r,e,t){let n=Ze(Xe(t?.left??0),r),i=Ze(Xe(t?.right??0),r),o=Ze(Xe(t?.top??0),e),s=Ze(Xe(t?.bottom??0),e);return{x:n,y:o,width:r-n-i,height:e-o-s}}function Kl(r,e,t){let[n,i]=r.project(e);return n=Number.isFinite(n)?n:r.width/2,i=Number.isFinite(i)?i:r.height/2,{left:n-t.x,right:t.x+t.width-n,top:i-t.y,bottom:t.y+t.height-i}}var Mw=5,RO=1.2,Iw=512,Rw=[[-1/0,-90],[1/0,90]],BO=1;function Hs([r,e]){if(Math.abs(e)>90&&(e=Math.sign(e)*90),Number.isFinite(r)){let[n,i]=gt([r,e]);return[n,ie(i,0,Iw)]}let[,t]=gt([0,e]);return[r,ie(t,0,Iw)]}var um=class extends jn{constructor(e){let{width:t,height:n,latitude:i,longitude:o,zoom:s,bearing:a=0,pitch:c=0,altitude:l=1.5,position:u=[0,0,0],maxZoom:f=20,minZoom:h=0,maxPitch:p=60,minPitch:m=0,startPanLngLat:g,startZoomLngLat:y,startRotatePos:x,startRotateLngLat:v,startBearing:_,startPitch:w,startZoom:E,normalize:S=!0,rubberBand:C=!1}=e,{[_t]:A}=e;q(Number.isFinite(o)),q(Number.isFinite(i)),q(Number.isFinite(s));let B=e.maxBounds||(S?Rw:null),L=e.maxBoundsPadding||null;super({width:t,height:n,latitude:i,longitude:o,zoom:s,bearing:a,pitch:c,altitude:l,maxZoom:f,minZoom:h,maxPitch:p,minPitch:m,normalize:S,position:u,maxBounds:B,maxBoundsPadding:L,rubberBand:C,[_t]:A},{startPanLngLat:g,startZoomLngLat:y,startRotatePos:x,startRotateLngLat:v,startBearing:_,startPitch:w,startZoom:E},e.makeViewport,e.constraintContext),this.getAltitude=e.getAltitude}panStart({pos:e},t){return this._getUpdatedState({startPanLngLat:this._unproject(e)},t)}pan({pos:e,startPos:t},n){let i=this.getState().startPanLngLat||this._unproject(t);if(!i)return this;let s=this.makeViewport(this.getViewportProps()).panByPosition(i,e);return this._getUpdatedState(s,n)}panEnd(e){return this._getUpdatedState({startPanLngLat:null},e)}rotateStart({pos:e}){let t=this.getAltitude?.(e);return this._getUpdatedState({startRotatePos:e,startRotateLngLat:t!==void 0?this._unproject3D(e,t):void 0,startBearing:this.getViewportProps().bearing,startPitch:this.getViewportProps().pitch})}rotate({pos:e,deltaAngleX:t=0,deltaAngleY:n=0}){let{startRotatePos:i,startRotateLngLat:o,startBearing:s,startPitch:a}=this.getState();if(!i||s===void 0||a===void 0)return this;let c;if(e?c=this._getNewRotation(e,i,a,s):c={bearing:s+t,pitch:a+n},o){let l=this.makeViewport({...this.getViewportProps(),...c}),u="panByPosition3D"in l?"panByPosition3D":"panByPosition";return this._getUpdatedState({...c,...l[u](o,i)})}return this._getUpdatedState(c)}rotateEnd(){return this._getUpdatedState({startRotatePos:null,startRotateLngLat:null,startBearing:null,startPitch:null})}zoomStart({pos:e},t){return this._getUpdatedState({startZoomLngLat:this._unproject(e),startZoom:this.getViewportProps().zoom},t)}zoom({pos:e,startPos:t,scale:n},i){let{startZoom:o,startZoomLngLat:s}=this.getState();return s||(o=this.getViewportProps().zoom,s=this._unproject(t)||this._unproject(e)),s?this._getUpdatedState({zoom:o+Math.log2(n),[_t]:{position:s,screenPosition:e}},i):this}zoomEnd(e){return this._getUpdatedState({startZoomLngLat:null,startZoom:null},e)}zoomIn(e=2,t){return this._zoomFromCenter(e,t)}zoomOut(e=2,t){return this._zoomFromCenter(1/e,t)}moveLeft(e=100,t){return this._panFromCenter([e,0],t)}moveRight(e=100,t){return this._panFromCenter([-e,0],t)}moveUp(e=100,t){return this._panFromCenter([0,e],t)}moveDown(e=100,t){return this._panFromCenter([0,-e],t)}rotateLeft(e=15){return this._getUpdatedState({bearing:this.getViewportProps().bearing-e})}rotateRight(e=15){return this._getUpdatedState({bearing:this.getViewportProps().bearing+e})}rotateUp(e=10){return this._getUpdatedState({pitch:this.getViewportProps().pitch+e})}rotateDown(e=10){return this._getUpdatedState({pitch:this.getViewportProps().pitch-e})}shortestPathFrom(e){let t=e.getViewportProps(),n={...this.getViewportProps()},{bearing:i,longitude:o}=n;return Math.abs(i-t.bearing)>180&&(n.bearing=i<0?i+360:i-360),Math.abs(o-t.longitude)>180&&(n.longitude=o<0?o+360:o-360),n}applyConstraints(e,t){let n=e,i=n[_t];delete n[_t];let{maxPitch:o,minPitch:s,pitch:a,bearing:c,normalize:l,maxBounds:u,rubberBand:f}=e;l&&(c<-180||c>180)&&(e.bearing=Hp(c+180,360)-180),e.pitch=ie(a,s,o);let h=this._constrainZoom(e.zoom,e),p=f&&t?.mode==="elastic";if(e.zoom=t?.mode==="preserve"?e.zoom:p?Yr(e.zoom,h,BO):h,i){let m=this.makeViewport(e);Object.assign(e,m.panByPosition(i.position,i.screenPosition))}if(l&&(e.longitude<-180||e.longitude>180)&&(e.longitude=Hp(e.longitude+180,360)-180),u){let m=Yi(e.width,e.height,e.maxBoundsPadding),g=this.makeViewport({...e,bearing:0,pitch:0}),y=Kl(g,[e.longitude,e.latitude],m),x=Hs(u[0]),v=Hs(u[1]),_=2**e.zoom,w=[x[0]+y.left/_,x[1]+y.bottom/_],E=[v[0]-y.right/_,v[1]-y.top/_],S=Hs([e.longitude,e.latitude]),C=[ie(S[0],w[0],E[0]),ie(S[1],w[1],E[1])],A=S.slice();if(m.width>=0&&(A[0]=t?.mode==="preserve"?S[0]:p?Yr(S[0],C[0],m.width/2/_):C[0]),m.height>=0&&(A[1]=t?.mode==="preserve"?S[1]:p?Yr(S[1],C[1],m.height/2/_):C[1]),A[0]!==S[0]||A[1]!==S[1]){let[B,L]=it(A);A[0]!==S[0]&&(e.longitude=B),A[1]!==S[1]&&(e.latitude=L)}}return e}_constrainZoom(e,t){t||(t=this.getViewportProps());let{maxZoom:n,maxBounds:i}=t,o=i!==null&&t.width>0&&t.height>0,{minZoom:s}=t;if(o){let a=Yi(t.width,t.height,t.maxBoundsPadding),c=Hs(i[0]),l=Hs(i[1]),u=l[0]-c[0],f=l[1]-c[1];a.width>0&&Number.isFinite(u)&&u>0&&(s=Math.max(s,Math.log2(a.width/u))),a.height>0&&Number.isFinite(f)&&f>0&&(s=Math.max(s,Math.log2(a.height/f))),s>n&&(s=n)}return ie(e,s,n)}_zoomFromCenter(e,t){let{width:n,height:i}=this.getViewportProps();return this.zoom({pos:[n/2,i/2],scale:e},t)}_panFromCenter(e,t){let{width:n,height:i}=this.getViewportProps();return this.pan({startPos:[n/2,i/2],pos:[n/2+e[0],i/2+e[1]]},t)}_getUpdatedState(e,t){return new this.constructor({makeViewport:this.makeViewport,...this.getViewportProps(),...this.getState(),...e,constraintContext:t})}_unproject(e){let t=this.makeViewport(this.getViewportProps());return e&&t.unproject(e)}_unproject3D(e,t){return this.makeViewport(this.getViewportProps()).unproject(e,{targetZ:t})}_getNewRotation(e,t,n,i){let o=e[0]-t[0],s=e[1]-t[1],a=e[1],c=t[1],{width:l,height:u}=this.getViewportProps(),f=o/l,h=0;s>0?Math.abs(u-c)>Mw&&(h=s/(c-u)*RO):s<0&&c>Mw&&(h=1-a/c),h=ie(h,-1,1);let{minPitch:p,maxPitch:m}=this.getViewportProps(),g=i+180*f,y=n;return h>0?y=n+h*(m-n):h<0&&(y=n-h*(p-n)),{pitch:y,bearing:g}}},Ys=class extends Wn{constructor(){super(...arguments),this.ControllerState=um,this.transition={transitionDuration:300,transitionInterpolator:new br({transitionProps:{compare:["longitude","latitude","zoom","bearing","pitch","position"],required:["longitude","latitude","zoom"]}})},this.dragMode="pan",this.rotationPivot="center",this._getAltitude=e=>{if(this.rotationPivot==="2d")return 0;if(this.rotationPivot==="3d"&&this.pickPosition){let{x:t,y:n}=this.props,i=this.pickPosition(t+e[0],n+e[1]);if(i&&i.coordinate&&i.coordinate.length>=3)return i.coordinate[2]}}}setProps(e){"rotationPivot"in e&&(this.rotationPivot=e.rotationPivot||"center"),e.getAltitude=this._getAltitude,e.position=e.position||[0,0,0],e.maxBounds=e.maxBounds||(e.normalize===!1?null:Rw),super.setProps(e)}updateViewport(e,t=null,n={}){let i=e.getState();n.isDragging&&i.startRotateLngLat?n={...n,rotationPivotPosition:i.startRotateLngLat}:n.isDragging===!1&&(n={...n,rotationPivotPosition:void 0}),super.updateViewport(e,t,n)}};var Ql=class extends zn{constructor(e={}){super(e)}getViewportType(){return $l}get ControllerType(){return Ys}};Ql.displayName="MapView";var Bw=Ql;var OO=new Di;function kO(r,e){let t=r.order??1/0,n=e.order??1/0;return t-n}var qs=class{constructor(e){this._resolvedEffects=[],this._defaultEffects=[],this.effects=[],this._context=e,this._needsRedraw="Initial render",this._setEffects([])}addDefaultEffect(e){let t=this._defaultEffects;if(!t.find(n=>n.id===e.id)){let n=t.findIndex(i=>kO(i,e)>0);n<0?t.push(e):t.splice(n,0,e),e.setup(this._context),this._setEffects(this.effects)}}setProps(e){"effects"in e&&(ce(e.effects,this.effects,1)||this._setEffects(e.effects))}needsRedraw(e={clearRedrawFlags:!1}){let t=this._needsRedraw;return e.clearRedrawFlags&&(this._needsRedraw=!1),t}getEffects(){return this._resolvedEffects}_setEffects(e){let t={};for(let i of this.effects)t[i.id]=i;let n=[];for(let i of e){let o=t[i.id],s=i;o&&o!==i?o.setProps?(o.setProps(i.props),s=o):o.cleanup(this._context):o||i.setup(this._context),n.push(s),delete t[i.id]}for(let i in t)t[i].cleanup(this._context);this.effects=n,this._resolvedEffects=n.concat(this._defaultEffects),e.some(i=>i instanceof Di)||this._resolvedEffects.push(OO),this._needsRedraw="effects changed"}finalize(){for(let e of this._resolvedEffects)e.cleanup(this._context);this.effects.length=0,this._resolvedEffects.length=0,this._defaultEffects.length=0}};var Xs=class extends yr{shouldDrawLayer(e){let{operation:t}=e.props;return t.includes("draw")||t.includes("terrain")}render(e){return this._render(e)}};var DO="deckRenderer.renderLayers",Zs=class{constructor(e,t={}){this.device=e,this.stats=t.stats,this.layerFilter=null,this.drawPickingColors=!1,this.drawLayersPass=new Xs(e),this.pickLayersPass=new Gn(e),this.renderCount=0,this._needsRedraw="Initial render",this.renderBuffers=[],this.lastPostProcessEffect=null}setProps(e){this.layerFilter!==e.layerFilter&&(this.layerFilter=e.layerFilter,this._needsRedraw="layerFilter changed"),this.drawPickingColors!==e.drawPickingColors&&(this.drawPickingColors=e.drawPickingColors,this._needsRedraw="drawPickingColors changed")}renderLayers(e){let t=this.drawPickingColors?this.pickLayersPass:this.drawLayersPass,n={layerFilter:this.layerFilter,isPicking:this.drawPickingColors,...e};if(!e.viewports.length){let a=t.render(n),c="stats"in a?a.stats:a;this._updateStats(c);return}n.effects&&this._preRender(n.effects,n);let i=this.lastPostProcessEffect?this.renderBuffers[0]:n.target;this.lastPostProcessEffect&&(n.clearColor=[0,0,0,0],n.clearCanvas=!0);let o=t.render({...n,target:i}),s="stats"in o?o.stats:o;n.effects&&(this.lastPostProcessEffect&&(n.clearCanvas=e.clearCanvas===void 0?!0:e.clearCanvas),this._postRender(n.effects,n)),this.renderCount++,me(DO,this,s,e),this._updateStats(s)}needsRedraw(e={clearRedrawFlags:!1}){let t=this._needsRedraw;return e.clearRedrawFlags&&(this._needsRedraw=!1),t}finalize(){let{renderBuffers:e}=this;for(let t of e)t.delete();e.length=0}_updateStats(e){if(!this.stats)return;let t=0;for(let{visibleCount:n}of e)t+=n;this.stats.get("Layers rendered").addCount(t)}_preRender(e,t){this.lastPostProcessEffect=null,t.preRenderStats=t.preRenderStats||{};for(let n of e)t.preRenderStats[n.id]=n.preRender(t),n.postRender&&(this.lastPostProcessEffect=n.id);this.lastPostProcessEffect&&this._resizeRenderBuffers(t.canvasContext)}_resizeRenderBuffers(e=this.device.canvasContext){let{renderBuffers:t}=this,n=e.getDrawingBufferSize(),[i,o]=n;t.length===0&&[0,1].map(s=>{let a=this.device.createTexture({sampler:{minFilter:"linear",magFilter:"linear"},width:i,height:o});t.push(this.device.createFramebuffer({id:`deck-renderbuffer-${s}`,colorAttachments:[a]}))});for(let s of t)s.resize(n)}_postRender(e,t){let{renderBuffers:n}=this,i=t.target??t.canvasContext?.getCurrentFramebuffer()??t.target,o={...t,inputBuffer:n[0],swapBuffer:n[1]};for(let s of e)if(s.postRender){o.target=s.id===this.lastPostProcessEffect?i:void 0;let a=s.postRender(o);o.inputBuffer=a,o.swapBuffer=a===n[0]?n[1]:n[0]}}};N();var NO={pickedColor:null,pickedObjectIndex:-1};function fm({pickedColors:r,decodePickingColor:e,deviceX:t,deviceY:n,deviceRadius:i,deviceRect:o}){let{x:s,y:a,width:c,height:l}=o,u=i*i,f=-1,h=0;for(let p=0;p<l;p++){let m=p+a-n,g=m*m;if(g>u)h+=4*c;else for(let y=0;y<c;y++){if(r[h+3]-1>=0){let v=y+s-t,_=v*v+g;_<=u&&(u=_,f=h)}h+=4}}if(f>=0){let p=r.slice(f,f+4),m=e(p);if(m){let g=Math.floor(f/4/c),y=f/4-g*c;return{...m,pickedColor:p,pickedX:s+y,pickedY:a+g}}$.error("Picked non-existent layer. Is picking buffer corrupt?")()}return NO}function dm({pickedColors:r,decodePickingColor:e}){let t=new Map;if(r){for(let n=0;n<r.length;n+=4)if(r[n+3]-1>=0){let o=r.slice(n,n+4),s=o.join(",");if(!t.has(s)){let a=e(o);a?t.set(s,{...a,color:o}):$.error("Picked non-existent layer. Is picking buffer corrupt?")()}}}return Array.from(t.values())}function Jl({pickInfo:r,viewports:e,pixelRatio:t,x:n,y:i,z:o}){let s=e[0];e.length>1&&(s=FO(r?.pickedViewports||e,{x:n,y:i}));let a;if(s){let c=[n-s.x,i-s.y];o!==void 0&&(c[2]=o),a=s.unproject(c)}return{color:null,layer:null,viewport:s,index:-1,picked:!1,x:n,y:i,pixel:[n,i],coordinate:a,devicePixel:r&&"pickedX"in r?[r.pickedX,r.pickedY]:void 0,pixelRatio:t}}function hm(r){let{pickInfo:e,lastPickedInfo:t,mode:n,layers:i}=r,{pickedColor:o,pickedLayer:s,pickedObjectIndex:a}=e,c=s?[s]:[];if(n==="hover"){let f=t.index,h=t.layerId,p=s?s.props.id:null;if(p!==h||a!==f){if(p!==h){let m=i.find(g=>g.props.id===h);m&&c.unshift(m)}t.layerId=p,t.index=a,t.info=null}}let l=Jl(r),u=new Map;return u.set(null,l),c.forEach(f=>{let h={...l};f===s&&(h.color=o,h.index=a,h.picked=!0),h=eu({layer:f,info:h,mode:n});let p=h.layer;f===s&&n==="hover"&&(t.info=h),u.set(p.id,h),n==="hover"&&p.updateAutoHighlight(h)}),u}function eu({layer:r,info:e,mode:t}){for(;r&&e;){let n=e.layer||null;e.sourceLayer=n,e.layer=r,e=r.getPickingInfo({info:e,mode:t,sourceLayer:n}),r=r.parent}return e}function FO(r,e){for(let t=r.length-1;t>=0;t--){let n=r[t];if(n.containsPixel(e))return n}return r[0]}var Ks=class{constructor(e,t={}){this._pickable=!0,this.device=e,this.stats=t.stats,this.pickLayersPass=new Gn(e),this.lastPickedInfo={index:-1,layerId:null,info:null}}setProps(e){"layerFilter"in e&&(this.layerFilter=e.layerFilter),"_pickable"in e&&(this._pickable=e._pickable)}finalize(){this.pickingFBO&&this.pickingFBO.destroy(),this.depthFBO&&this.depthFBO.destroy()}pickObjectAsync(e){return this._pickClosestObjectAsync(e)}pickObjectsAsync(e){return this._pickVisibleObjectsAsync(e)}pickObject(e){return this._pickClosestObject(e)}pickObjects(e){return this._pickVisibleObjects(e)}getLastPickedObject({x:e,y:t,layers:n,viewports:i},o=this.lastPickedInfo.info){let s=o&&o.layer&&o.layer.id,a=o&&o.viewport&&o.viewport.id,c=s?n.find(h=>h.id===s):null,l=a&&i.find(h=>h.id===a)||i[0],u=l&&l.unproject([e-l.x,t-l.y]);return{...o,...{x:e,y:t,viewport:l,coordinate:u,layer:c}}}_resizeBuffer(e=this.device.getDefaultCanvasContext()){if(!this.pickingFBO){let i=this.device.createTexture({format:"rgba8unorm",width:1,height:1,usage:Y.RENDER_ATTACHMENT|Y.COPY_SRC});if(this.pickingFBO=this.device.createFramebuffer({colorAttachments:[i],depthStencilAttachment:"depth16unorm"}),this.device.isTextureFormatRenderable("rgba32float")){let o=this.device.createTexture({format:"rgba32float",width:1,height:1,usage:Y.RENDER_ATTACHMENT|Y.COPY_SRC}),s=this.device.createFramebuffer({colorAttachments:[o],depthStencilAttachment:"depth16unorm"});this.depthFBO=s}}let[t,n]=e.getDrawingBufferSize();this.pickingFBO?.resize({width:t,height:n}),this.depthFBO?.resize({width:t,height:n})}_getPickable(e){if(this._pickable===!1)return null;let t=e.filter(n=>this.pickLayersPass.shouldDrawLayer(n)&&!n.isComposite);return t.length?t:null}async _pickClosestObjectAsync({layers:e,views:t,viewports:n,x:i,y:o,radius:s=0,depth:a=1,mode:c="query",unproject3D:l,canvasContext:u=this.device.getDefaultCanvasContext(),onViewportActive:f,effects:h}){let p=u.cssToDeviceRatio(),m=this._getPickable(e);if(!m||n.length===0)return{result:[],emptyInfo:Jl({viewports:n,x:i,y:o,pixelRatio:p})};this._resizeBuffer(u);let g=u.cssToDevicePixels([i,o],!0),y=[g.x+Math.floor(g.width/2),g.y+Math.floor(g.height/2)],x=Math.round(s*p),{width:v,height:_}=this.pickingFBO,w=this._getPickingRect({deviceX:y[0],deviceY:y[1],deviceRadius:x,deviceWidth:v,deviceHeight:_}),E={x:i-s,y:o-s,width:s*2+1,height:s*2+1},S,C=[],A=new Set;for(let B=0;B<a;B++){let L;if(w){let R=await this._drawAndSampleAsync({layers:m,views:t,viewports:n,onViewportActive:f,deviceRect:w,cullRect:E,effects:h,pass:`picking:${c}`,canvasContext:u});L=fm({...R,deviceX:y[0],deviceY:y[1],deviceRadius:x,deviceRect:w})}else L={pickedColor:null,pickedObjectIndex:-1};let M,I=this._getDepthLayers(L,m,l);if(I.length>0){let{pickedColors:R}=await this._drawAndSampleAsync({layers:I,views:t,viewports:n,onViewportActive:f,deviceRect:{x:L.pickedX??y[0],y:L.pickedY??y[1],width:1,height:1},cullRect:E,effects:h,pass:`picking:${c}:z`,canvasContext:u},!0);R[3]&&(M=R[0])}L.pickedLayer&&B+1<a&&(A.add(L.pickedLayer),L.pickedLayer.disablePickingIndex(L.pickedObjectIndex)),S=hm({pickInfo:L,lastPickedInfo:this.lastPickedInfo,mode:c,layers:m,viewports:n,x:i,y:o,z:M,pixelRatio:p});for(let R of S.values())R.layer&&C.push(R);if(!L.pickedColor)break}for(let B of A)B.restorePickingColors();return{result:C,emptyInfo:S.get(null)}}_pickClosestObject({layers:e,views:t,viewports:n,x:i,y:o,radius:s=0,depth:a=1,mode:c="query",unproject3D:l,canvasContext:u=this.device.getDefaultCanvasContext(),onViewportActive:f,effects:h}){let p=u.cssToDeviceRatio(),m=this._getPickable(e);if(!m||n.length===0)return{result:[],emptyInfo:Jl({viewports:n,x:i,y:o,pixelRatio:p})};this._resizeBuffer(u);let g=u.cssToDevicePixels([i,o],!0),y=[g.x+Math.floor(g.width/2),g.y+Math.floor(g.height/2)],x=Math.round(s*p),{width:v,height:_}=this.pickingFBO,w=this._getPickingRect({deviceX:y[0],deviceY:y[1],deviceRadius:x,deviceWidth:v,deviceHeight:_}),E={x:i-s,y:o-s,width:s*2+1,height:s*2+1},S,C=[],A=new Set;for(let B=0;B<a;B++){let L;if(w){let R=this._drawAndSample({layers:m,views:t,viewports:n,onViewportActive:f,deviceRect:w,cullRect:E,effects:h,pass:`picking:${c}`,canvasContext:u});L=fm({...R,deviceX:y[0],deviceY:y[1],deviceRadius:x,deviceRect:w})}else L={pickedColor:null,pickedObjectIndex:-1};let M,I=this._getDepthLayers(L,m,l);if(I.length>0){let{pickedColors:R}=this._drawAndSample({layers:I,views:t,viewports:n,onViewportActive:f,deviceRect:{x:L.pickedX??y[0],y:L.pickedY??y[1],width:1,height:1},cullRect:E,effects:h,pass:`picking:${c}:z`,canvasContext:u},!0);R[3]&&(M=R[0])}L.pickedLayer&&B+1<a&&(A.add(L.pickedLayer),L.pickedLayer.disablePickingIndex(L.pickedObjectIndex)),S=hm({pickInfo:L,lastPickedInfo:this.lastPickedInfo,mode:c,layers:m,viewports:n,x:i,y:o,z:M,pixelRatio:p});for(let R of S.values())R.layer&&C.push(R);if(!L.pickedColor)break}for(let B of A)B.restorePickingColors();return{result:C,emptyInfo:S.get(null)}}async _pickVisibleObjectsAsync({layers:e,views:t,viewports:n,x:i,y:o,width:s=1,height:a=1,mode:c="query",maxObjects:l=null,canvasContext:u=this.device.getDefaultCanvasContext(),onViewportActive:f,effects:h}){let p=this._getPickable(e);if(!p||n.length===0)return[];this._resizeBuffer(u);let m=u.cssToDeviceRatio(),g=u.cssToDevicePixels([i,o],!0),y=g.x,x=g.y+g.height,v=u.cssToDevicePixels([i+s,o+a],!0),_=v.x+v.width,w=v.y,E={x:y,y:w,width:_-y,height:x-w},S=await this._drawAndSampleAsync({layers:p,views:t,viewports:n,onViewportActive:f,deviceRect:E,cullRect:{x:i,y:o,width:s,height:a},effects:h,pass:`picking:${c}`,canvasContext:u}),C=dm(S),A=new Map,B=[],L=Number.isFinite(l);for(let M=0;M<C.length&&!(L&&B.length>=l);M++){let I=C[M],R={color:I.pickedColor,layer:null,index:I.pickedObjectIndex,picked:!0,x:i,y:o,pixelRatio:m};R=eu({layer:I.pickedLayer,info:R,mode:c});let k=R.layer.id;A.has(k)||A.set(k,new Set);let W=A.get(k),V=R.object??R.index;W.has(V)||(W.add(V),B.push(R))}return B}_pickVisibleObjects({layers:e,views:t,viewports:n,x:i,y:o,width:s=1,height:a=1,mode:c="query",maxObjects:l=null,canvasContext:u=this.device.getDefaultCanvasContext(),onViewportActive:f,effects:h}){let p=this._getPickable(e);if(!p||n.length===0)return[];this._resizeBuffer(u);let m=u.cssToDeviceRatio(),g=u.cssToDevicePixels([i,o],!0),y=g.x,x=g.y+g.height,v=u.cssToDevicePixels([i+s,o+a],!0),_=v.x+v.width,w=v.y,E={x:y,y:w,width:_-y,height:x-w},S=this._drawAndSample({layers:p,views:t,viewports:n,onViewportActive:f,deviceRect:E,cullRect:{x:i,y:o,width:s,height:a},effects:h,pass:`picking:${c}`,canvasContext:u}),C=dm(S),A=new Map,B=[],L=Number.isFinite(l);for(let M=0;M<C.length&&!(L&&B.length>=l);M++){let I=C[M],R={color:I.pickedColor,layer:null,index:I.pickedObjectIndex,picked:!0,x:i,y:o,pixelRatio:m};R=eu({layer:I.pickedLayer,info:R,mode:c});let k=R.layer.id;A.has(k)||A.set(k,new Set);let W=A.get(k),V=R.object??R.index;W.has(V)||(W.add(V),B.push(R))}return B}async _drawAndSampleAsync({layers:e,views:t,viewports:n,onViewportActive:i,deviceRect:o,cullRect:s,effects:a,pass:c,canvasContext:l},u=!1){let f=u?this.depthFBO:this.pickingFBO,h={layers:e,layerFilter:this.layerFilter,views:t,viewports:n,onViewportActive:i,pickingFBO:f,deviceRect:o,cullRect:s,effects:a,pass:c,canvasContext:l,pickZ:u,preRenderStats:{},isPicking:!0};for(let E of a)E.useInPicking&&(h.preRenderStats[E.id]=E.preRender(h));let{decodePickingColor:p,stats:m}=this.pickLayersPass.render(h);this._updateStats(m);let{x:g,y,width:x,height:v}=o,_=f.colorAttachments[0]?.texture;if(!_)throw new Error("Picking framebuffer color attachment is missing");let w=await this._readTextureDataAsync(_,{x:g,y,width:x,height:v},u?Float32Array:Uint8Array);if(!u){let E=!1;for(let S=3;S<w.length;S+=4)if(w[S]!==0){E=!0;break}!E&&w.length>0&&$.warn("Async pick readback returned only zero alpha values",{deviceRect:o,bytes:Array.from(w.subarray(0,Math.min(w.length,16)))})()}return{pickedColors:w,decodePickingColor:p}}async _readTextureDataAsync(e,t,n){let{width:i,height:o}=t,s=e.computeMemoryLayout(t),a=this.device.createBuffer({byteLength:s.byteLength,usage:z.COPY_DST|z.MAP_READ});try{e.readBuffer(t,a);let c=await a.readAsync(0,s.byteLength),l=n.BYTES_PER_ELEMENT;if(s.bytesPerRow%l!==0)throw new Error(`Texture readback row stride ${s.bytesPerRow} is not aligned to ${l}-byte elements.`);let u=new n(c.buffer,c.byteOffset,s.byteLength/l),f=i*4,h=s.bytesPerRow/l;if(h<f)throw new Error(`Texture readback row stride ${h} is smaller than packed row length ${f}.`);let p=new n(i*o*4);for(let m=0;m<o;m++){let g=m*h;p.set(u.subarray(g,g+f),m*f)}return p}finally{a.destroy()}}_drawAndSample({layers:e,views:t,viewports:n,onViewportActive:i,deviceRect:o,cullRect:s,effects:a,pass:c,canvasContext:l},u=!1){let f=u?this.depthFBO:this.pickingFBO,h={layers:e,layerFilter:this.layerFilter,views:t,viewports:n,onViewportActive:i,pickingFBO:f,deviceRect:o,cullRect:s,effects:a,pass:c,canvasContext:l,pickZ:u,preRenderStats:{},isPicking:!0};for(let w of a)w.useInPicking&&(h.preRenderStats[w.id]=w.preRender(h));let{decodePickingColor:p,stats:m}=this.pickLayersPass.render(h);this._updateStats(m);let{x:g,y,width:x,height:v}=o,_=new(u?Float32Array:Uint8Array)(x*v*4);return this.device.readPixelsToArrayWebGL(f,{sourceX:g,sourceY:y,sourceWidth:x,sourceHeight:v,target:_}),{pickedColors:_,decodePickingColor:p}}_updateStats(e){if(!this.stats)return;let t=0;for(let{visibleCount:n}of e)t+=n;this.stats.get("Layers picked").addCount(t)}_getDepthLayers(e,t,n){if(!n||!this.depthFBO)return[];let{pickedLayer:i}=e,o=i?.state?.terrainDrawMode==="drape";return i&&!o?[i]:t.filter(s=>s.props.operation.includes("terrain"))}_getPickingRect({deviceX:e,deviceY:t,deviceRadius:n,deviceWidth:i,deviceHeight:o}){let s=Math.max(0,e-n),a=Math.max(0,t-n),c=Math.min(i,e+n+1)-s,l=Math.min(o,t+n+1)-a;return c<=0||l<=0?null:{x:s,y:a,width:c,height:l}}};var UO={"top-left":{top:0,left:0},"top-right":{top:0,right:0},"bottom-left":{bottom:0,left:0},"bottom-right":{bottom:0,right:0},fill:{top:0,left:0,bottom:0,right:0}},GO="top-left",Ow="root",tu=class{constructor({deck:e,parentElement:t}){this.defaultWidgets=[],this.widgets=[],this.resolvedWidgets=[],this.containers={},this.lastViewports={},this.deck=e,t?.classList.add("deck-widget-container"),this.parentElement=t}getWidgets(){return this.resolvedWidgets}setProps(e){if(e.widgets&&!ce(e.widgets,this.widgets,1)){let t=e.widgets.filter(Boolean);this._setWidgets(t)}}finalize(){for(let e of this.getWidgets())this._removeWidget(e);this.defaultWidgets.length=0,this.resolvedWidgets.length=0;for(let e in this.containers)this.containers[e].remove()}addDefault(e){this.defaultWidgets.find(t=>t.id===e.id)||(this._addWidget(e),this.defaultWidgets.push(e),this._setWidgets(this.widgets))}onRedraw({viewports:e,layers:t}){let n=e.reduce((i,o)=>(i[o.id]=o,i),{});for(let i of this.getWidgets()){let{viewId:o}=i;if(o){let s=n[o];s&&(i.onViewportChange&&i.onViewportChange(s),i.onRedraw?.({viewports:[s],layers:t}))}else{if(i.onViewportChange)for(let s of e)i.onViewportChange(s);i.onRedraw?.({viewports:e,layers:t})}}this.lastViewports=n,this._updateContainers()}onHover(e,t){for(let n of this.getWidgets()){let{viewId:i}=n;(!i||i===e.viewport?.id)&&n.onHover?.(e,t)}}getCanvasBounds(e){let n=this.deck?.getCanvas?.()?.getBoundingClientRect(),i=this.parentElement?.getBoundingClientRect(),o=this.deck?.getCanvasContext?.(e?.id);if(o&&i){o.updatePosition();let[s,a]=o.getPosition(),[c,l]=o.getCSSSize();return{x:s-i.left,y:a-i.top,width:c,height:l}}return{x:n&&i?n.left-i.left:0,y:n&&i?n.top-i.top:0,width:n?.width||this.deck?.width||0,height:n?.height||this.deck?.height||0}}onEvent(e,t){let n=Ii[t.type];if(n)for(let i of this.getWidgets()){let{viewId:o}=i;(!o||o===e.viewport?.id)&&i[n]?.(e,t)}}_setWidgets(e){let t={};for(let n of this.resolvedWidgets)t[n.id]=n;this.resolvedWidgets.length=0;for(let n of this.defaultWidgets)t[n.id]=null,this.resolvedWidgets.push(n);for(let n of e){let i=t[n.id];i?i.viewId!==n.viewId||i.placement!==n.placement?(this._removeWidget(i),this._addWidget(n)):n!==i&&(i.setProps(n.props),n=i):this._addWidget(n),t[n.id]=null,this.resolvedWidgets.push(n)}for(let n in t){let i=t[n];i&&this._removeWidget(i)}this.widgets=e}_addWidget(e){let{viewId:t=null,placement:n=GO}=e,i=e.props._container??t;e.widgetManager=this,e.deck=this.deck,e.rootElement=e._onAdd({deck:this.deck,viewId:t}),e.rootElement&&this._getContainer(i,n).append(e.rootElement),e.updateHTML()}_removeWidget(e){e.onRemove?.(),e.rootElement&&e.rootElement.remove(),e.rootElement=void 0,e.deck=void 0,e.widgetManager=void 0}_getContainer(e,t){if(e&&typeof e!="string")return e;let n=e||Ow,i=this.containers[n];i||(i=document.createElement("div"),i.style.pointerEvents="none",i.style.position="absolute",i.style.overflow="hidden",this.parentElement?.append(i),this.containers[n]=i);let o=i.querySelector(`.${t}`);return o||(o=globalThis.document.createElement("div"),o.className=t,o.style.position="absolute",o.style.zIndex="2",Object.assign(o.style,UO[t]),i.append(o)),o}_updateContainers(){for(let e in this.containers){let t=this.lastViewports[e]||null,n=e===Ow||t,i=this.containers[e];if(n){let o=this._getContainerBounds(t);i.style.display="block",i.style.left=`${o.x}px`,i.style.top=`${o.y}px`,i.style.width=`${o.width}px`,i.style.height=`${o.height}px`}else i.style.display="none"}}_getContainerBounds(e){if(!e)return{x:0,y:0,width:this.parentElement?.clientWidth||this.deck.width,height:this.parentElement?.clientHeight||this.deck.height};let t=this.getCanvasBounds(e);return{x:t.x+e.x,y:t.y+e.y,width:e.width,height:e.height}}};function pm(r,e){e&&Object.entries(e).map(([t,n])=>{t.startsWith("--")?r.style.setProperty(t,n):r.style[t]=n})}function kw(r,e){e&&Object.keys(e).map(t=>{t.startsWith("--")?r.style.removeProperty(t):r.style[t]=""})}var qi=class{constructor(e){this.viewId=null,this.props={...this.constructor.defaultProps,...e},this.id=this.props.id}setProps(e){let t=this.props,n=this.rootElement;n&&t.className!==e.className&&(t.className&&n.classList.remove(t.className),e.className&&n.classList.add(e.className)),n&&!ce(t.style,e.style,1)&&(kw(n,t.style),pm(n,e.style)),Object.assign(this.props,e),this.updateHTML()}updateHTML(){this.rootElement&&this.onRenderHTML(this.rootElement)}get viewIds(){return this.viewId?[this.viewId]:this.deck?.getViews().map(e=>e.id)??[]}getViewState(e){return this.deck?.viewManager?.getViewState(e)||{}}setViewState(e,t){this.deck?._onViewStateChange({viewId:e,viewState:t,interactionState:{}})}onCreateRootElement(){let e=["deck-widget",this.className,this.props.className],t=document.createElement("div");return e.filter(n=>typeof n=="string"&&n.length>0).forEach(n=>t.classList.add(n)),pm(t,this.props.style),t}_onAdd(e){return this.onAdd(e)??this.onCreateRootElement()}onAdd(e){}onRemove(){}onViewportChange(e){}onRedraw(e){}onHover(e,t){}onClick(e,t){}onDrag(e,t){}onDragStart(e,t){}onDragEnd(e,t){}};qi.defaultProps={id:"widget",style:{},_container:null,className:""};var zO={zIndex:"1",position:"absolute",pointerEvents:"none",color:"#a0a7b4",backgroundColor:"#29323c",padding:"10px",top:"0",left:"0",display:"none"},Qs=class extends qi{constructor(e={}){super(e),this.id="default-tooltip",this.placement="fill",this.className="deck-tooltip",this.isVisible=!1,this.setProps(e)}onCreateRootElement(){let e=document.createElement("div");return e.className=this.className,Object.assign(e.style,zO),e}onRenderHTML(e){}onViewportChange(e){this.isVisible&&e.id===this.lastViewport?.id&&!e.equals(this.lastViewport)&&this.setTooltip(null),this.lastViewport=e}onHover(e){let{deck:t}=this,n=t&&t.props.getTooltip;if(!n)return;let i=n(e),o=this.widgetManager?.getCanvasBounds(e.viewport),s=e.x+(o?.x||0),a=e.y+(o?.y||0);this.setTooltip(i,s,a)}setTooltip(e,t,n){let i=this.rootElement;if(i){if(typeof e=="string")i.innerText=e;else if(e)e.text&&(i.innerText=e.text),e.html&&(i.innerHTML=e.html),e.className&&(i.className=e.className);else{this.isVisible=!1,i.style.display="none";return}this.isVisible=!0,i.style.display="block",i.style.transform=`translate(${t}px, ${n}px)`,e&&typeof e=="object"&&"style"in e&&Object.assign(i.style,e.style)}}};Qs.defaultProps={...qi.defaultProps};var Js=class{constructor(e){this.targets={},this.order=[],this.eventManagers={},this._eventRootToCanvasId=new WeakMap,this._createEventManager=e.createEventManager,this._getEventRoot=e.getEventRoot}finalize(){for(let e of Object.values(this.targets))e.eventManager.destroy(),e.presentationContext.destroy();this.targets={},this.order=[],this.eventManagers={},this._eventRootToCanvasId=new WeakMap}syncCanvasEntries(e){let t=this._normalizeCanvasList(e.canvases),n={},i=[],o=new Map;for(let{canvas:a}of t){let c=this._getEventRoot(a);o.set(c,(o.get(c)||0)+1)}for(let{id:a,canvas:c}of t){let l=this._getEventRoot(c),u=o.get(l)===1?l:c,f=this.targets[a];if(!f||f.device!==e.device||f.canvas!==c||f.eventRoot!==u){f?.eventManager.destroy(),f?.presentationContext.destroy();let h=e.device.createPresentationContext({id:a,canvas:c,useDevicePixels:e.useDevicePixels,autoResize:!0});f={id:a,device:e.device,canvas:c,eventRoot:u,presentationContext:h,eventManager:this._createEventManager(u)}}this._eventRootToCanvasId.set(u,a),this._eventRootToCanvasId.set(c,a),n[a]=f,i.push(a)}for(let[a,c]of Object.entries(this.targets))n[a]||(c.eventManager.destroy(),c.presentationContext.destroy());this.targets=n,this.order=i;let s=Object.fromEntries(Object.entries(n).map(([a,c])=>[a,c.eventManager]));this._haveSameEventManagers(s)||(this.eventManagers=s)}getCanvasIdFromEvent(e){return e?this._eventRootToCanvasId.get(e):void 0}getTarget(e){return this.targets[e||this.order[0]||Hr]||null}_normalizeCanvasList(e=[]){let t=new Set;return e.map((n,i)=>{let o,s;return typeof n=="string"?(o=document.getElementById(n),q(o,`Canvas with id ${n} not found`),s=n):(o=n,s=o.id||`deckgl-canvas-${i}`),q(!t.has(s),`Duplicate canvas id ${s}`),t.add(s),{id:s,canvas:o}})}_haveSameEventManagers(e){let t=Object.keys(e),n=Object.keys(this.eventManagers);return t.length===n.length&&t.every(i=>e[i]===this.eventManagers[i])}};N();Bu();de();de();Po();function xr(){}var Qk=({isDragging:r})=>r?"grabbing":"grab",o2={id:"",width:"100%",height:"100%",style:null,viewState:null,initialViewState:null,pickingRadius:0,pickAsync:"auto",layerFilter:null,parameters:{},parent:null,device:null,deviceProps:{},gl:null,canvas:null,_canvases:null,layers:[],effects:[],views:null,controller:null,useDevicePixels:!0,touchAction:"none",eventRecognizerOptions:{},_framebuffer:null,_animate:!1,_pickable:!0,_typedArrayManagerProps:{},_customRender:null,widgets:[],onDeviceInitialized:xr,onWebGLInitialized:xr,onResize:xr,onViewStateChange:xr,onInteractionStateChange:xr,onBeforeRender:xr,onAfterRender:xr,onLoad:xr,onError:r=>$.error(r.message,r.cause)(),onHover:null,onClick:null,onDragStart:null,onDrag:null,onDragEnd:null,_onMetrics:null,getCursor:Qk,getTooltip:null,debug:!1,drawPickingColors:!1},fa=class{constructor(e){this.width=0,this.height=0,this.userData={},this.device=null,this.canvas=null,this.viewManager=null,this.layerManager=null,this.effectManager=null,this.deckRenderer=null,this.deckPicker=null,this.eventManager=null,this.eventManagers={},this.widgetManager=null,this.tooltip=null,this.animationLoop=null,this._canvasContext=null,this._deviceResizeHandler=null,this.cursorState={isHovering:!1,isDragging:!1},this.stats=new lt({id:"deck.gl"}),this.metrics={fps:0,setPropsTime:0,layersCount:0,drawLayersCount:0,updateLayersCount:0,updateAttributesCount:0,updateAttributesTime:0,framesRedrawn:0,pickTime:0,pickCount:0,pickLayersCount:0,gpuTime:0,gpuTimePerFrame:0,cpuTime:0,cpuTimePerFrame:0,bufferMemory:0,textureMemory:0,renderbufferMemory:0,gpuMemory:0},this._metricsCounter=0,this._hoverPickSequence=0,this._pointerDownPickSequence=0,this._needsRedraw="Initial render",this._canvasManager=new Js({createEventManager:i=>this._createEventManager(i),getEventRoot:i=>this._getEventRoot(i)}),this._ownedCanvas=null,this._pickRequest={mode:"hover",x:-1,y:-1,radius:0,canvasId:void 0,event:null,unproject3D:!1},this._lastPointerDownInfo=null,this._lastPointerDownInfoPromise=null,this._onPointerMove=i=>{let{_pickRequest:o}=this,s=this._getCanvasIdFromEvent(i);if(i.type==="pointerleave")o.x=-1,o.y=-1,o.radius=0,o.canvasId=s;else{if(i.leftButton||i.rightButton)return;{let a=i.offsetCenter;if(!a)return;o.x=a.x,o.y=a.y,o.radius=this.props.pickingRadius,o.canvasId=s}}this.layerManager&&(this.layerManager.context.mousePosition={x:o.x,y:o.y}),o.event=i},this._onEvent=i=>{let o=Ii[i.type],s=i.offsetCenter,a=this._getCanvasIdFromEvent(i);if(!o||!s||!this.layerManager)return;let c=this.layerManager.getLayers(),l=this._getInternalPickingMode();if(!l)return;if(l==="sync"){let f=i.type==="click"&&this._shouldUnproject3D(c)?this._getFirstPickedInfo(this._pickPointSync(this._getPointPickOptions(s.x,s.y,{unproject3D:!0,canvasId:a},c))):this._getLastPointerDownPickingInfo(s.x,s.y,a,c);this._dispatchPickingEvent(f,i);return}(this._lastPointerDownInfoPromise||Promise.resolve(this._getLastPointerDownPickingInfo(s.x,s.y,a,c))).then(f=>{this._dispatchPickingEvent(f,i)}).catch(f=>this.props.onError?.(f))},this._onPointerDown=i=>{let o=i.offsetCenter,s=this._getCanvasIdFromEvent(i);if(!o)return;let a=this._getInternalPickingMode();if(!a)return;let c=this.layerManager?.getLayers()||[],l=++this._pointerDownPickSequence;if(a==="sync"){let f=this._pickPointSync({x:o.x,y:o.y,canvasId:s,radius:this.props.pickingRadius}),h=this._getFirstPickedInfo(f);this._lastPointerDownInfo=h,this._lastPointerDownInfoPromise=Promise.resolve(h);return}let u=this._pickPointAsync(this._getPointPickOptions(o.x,o.y,{canvasId:s},c)).then(f=>this._getFirstPickedInfo(f)).then(f=>(l===this._pointerDownPickSequence&&(this._lastPointerDownInfo=f),f)).catch(f=>{this.props.onError?.(f);let h=this.deckPicker&&this.viewManager?this._getLastPointerDownPickingInfo(o.x,o.y,s,c):{};return l===this._pointerDownPickSequence&&(this._lastPointerDownInfo=h),h});this._lastPointerDownInfo=null,this._lastPointerDownInfoPromise=u};let t=e;this.props={...o2,...e},e=this.props,this._validateCanvasConfiguration(e),e.viewState&&e.initialViewState&&$.warn("View state tracking is disabled. Use either `initialViewState` for auto update or `viewState` for manual update.")(),this.viewState=this.props.initialViewState,e.device&&(this.device=e.device,this._setDeviceCanvasContext(e.device));let n=this.device;!n&&e.gl&&(e.gl instanceof WebGLRenderingContext&&$.error("WebGL1 context not supported.")(),n=ua.attach(e.gl,{_cacheShaders:!0,_cachePipelines:!0,...this.props.deviceProps})),n||(n=this._createDevice(e)),this.animationLoop=this._createAnimationLoop(n,e),this.setProps(t),e._typedArrayManagerProps&&Lt.setOptions(e._typedArrayManagerProps),this.animationLoop.start()}finalize(){this._restoreDeviceResizeHandler(),this.animationLoop?.stop(),this.animationLoop?.destroy(),this.animationLoop=null,this._hoverPickSequence++,this._pointerDownPickSequence++,this._lastPointerDownInfo=null,this._lastPointerDownInfoPromise=null,this.layerManager?.finalize(),this.layerManager=null,this.viewManager?.finalize(),this.viewManager=null,this.effectManager?.finalize(),this.effectManager=null,this.deckRenderer?.finalize(),this.deckRenderer=null,this.deckPicker?.finalize(),this.deckPicker=null,Object.keys(this._canvasManager.targets).length||this.eventManager?.destroy(),this.eventManager=null,this.eventManagers={},this.widgetManager?.finalize(),this.widgetManager=null,this._canvasManager.finalize(),this._isMultiCanvasMode()?this.canvas=null:this.canvas&&this.canvas===this._ownedCanvas&&(this.canvas.parentElement?.removeChild(this.canvas),this.canvas=null,this._ownedCanvas=null),this._canvasContext=null}setProps(e){this.stats.get("setProps Time").timeStart(),"onLayerHover"in e&&$.removed("onLayerHover","onHover")(),"onLayerClick"in e&&$.removed("onLayerClick","onClick")(),e.initialViewState&&!ce(this.props.initialViewState,e.initialViewState,3)&&(this.viewState=e.initialViewState),q(!("_canvases"in e)||Array.isArray(e._canvases)===this._isMultiCanvasMode()),Object.assign(this.props,e),this._validateCanvasConfiguration(this.props),this._validateInternalPickingMode(),this.device&&this._isMultiCanvasMode()&&this._syncCanvasTargets(),this._setCanvasSize(this.props);let t=Object.create(this.props);if(Object.assign(t,{views:this._getViews(),width:this.width,height:this.height,viewState:this._getViewState(),eventManagers:this.eventManagers}),e.device&&e.device.id!==this.device?.id){let n=e.device.getDefaultCanvasContext();this.animationLoop?.stop(),!this._isMultiCanvasMode()&&this.canvas!==n.canvas&&(this.canvas?.remove(),this.eventManager?.destroy(),this.canvas=null),this._setDeviceCanvasContext(e.device),$.log(`recreating animation loop for new device! id=${e.device.id}`)(),this.animationLoop=this._createAnimationLoop(e.device,e),this.animationLoop.start()}if(this.animationLoop?.setProps(t),e.useDevicePixels!==void 0&&this._canvasContext?.setProps){this._canvasContext.setProps({useDevicePixels:e.useDevicePixels});for(let n of Object.values(this._canvasManager.targets))n.presentationContext.setProps({useDevicePixels:e.useDevicePixels})}this.layerManager&&(this.viewManager.setProps(t),this.layerManager.activateViewport(this.getViewports()[0]),this.layerManager.setProps(t),this.effectManager.setProps(t),this.deckRenderer.setProps(t),this.deckPicker.setProps(t),this.widgetManager.setProps(t)),this.stats.get("setProps Time").timeEnd()}needsRedraw(e={clearRedrawFlags:!1}){if(!this.layerManager)return!1;if(this.props._animate)return"Deck._animate";let t=this._needsRedraw;e.clearRedrawFlags&&(this._needsRedraw=!1);let n=this.viewManager.needsRedraw(e),i=this.layerManager.needsRedraw(e),o=this.effectManager.needsRedraw(e),s=this.deckRenderer.needsRedraw(e);return t=t||n||i||o||s,t}redraw(e){if(!this.layerManager)return;let t=this.needsRedraw({clearRedrawFlags:!0});t=e||t,t&&(this.stats.get("Redraw Count").incrementCount(),this.props._customRender?this.props._customRender(t):this._drawLayers(t))}get isInitialized(){return this.viewManager!==null}getViews(){return q(this.viewManager),this.viewManager.views}getView(e){return q(this.viewManager),this.viewManager.getView(e)}getViewports(e){return q(this.viewManager),this.viewManager.getViewports(e)}getCanvas(){return this.canvas}getCanvasContext(e){let t=e?this.viewManager?.getView(e)?.props.canvasId:void 0;return this._getCanvasContext(t)}getEventManager(e){if(!e||!this.viewManager)return this.eventManager;let t=this.viewManager.getCanvasId(e)||Hr;return this.eventManagers[t]||this.eventManager}async pickObjectAsync(e){let t=(await this._pickAsync("pickObjectAsync","pickObject Time",e)).result;return t.length?t[0]:null}async pickObjectsAsync(e){return await this._pickAsync("pickObjectsAsync","pickObjects Time",e)}pickObject(e){let t=this._pick("pickObject","pickObject Time",e).result;return t.length?t[0]:null}pickMultipleObjects(e){return e.depth=e.depth||10,this._pick("pickObject","pickMultipleObjects Time",e).result}pickObjects(e){return this._pick("pickObjects","pickObjects Time",e)}_pickPositionForController(e,t,n){return this._getInternalPickingMode()!=="sync"?null:this.pickObject({x:e,y:t,radius:0,unproject3D:!0,canvasId:n?this.viewManager?.getCanvasId(n):void 0})}_addResources(e,t=!1){for(let n in e)this.layerManager.resourceManager.add({resourceId:n,data:e[n],forceUpdate:t})}_removeResources(e){for(let t of e)this.layerManager.resourceManager.remove(t)}_addDefaultEffect(e){this.effectManager.addDefaultEffect(e)}_addDefaultShaderModule(e){this.layerManager.addDefaultShaderModule(e)}_removeDefaultShaderModule(e){this.layerManager?.removeDefaultShaderModule(e)}_resolveInternalPickingMode(){let{pickAsync:e}=this.props,t=this.device?.type||this.props.deviceProps?.type;if(e==="auto")return t==="webgpu"?"async":"sync";if(e==="sync"&&t==="webgpu")throw new Error('`pickAsync: "sync"` is not supported when Deck is using a WebGPU device.');return e}_getInternalPickingMode(){try{return this._resolveInternalPickingMode()}catch(e){return this.props.onError?.(e),null}}_validateInternalPickingMode(){this._getInternalPickingMode()}_getFirstPickedInfo({result:e,emptyInfo:t}){return e[0]||t}_shouldUnproject3D(e=this.layerManager?.getLayers()||[]){return e.some(t=>t.props.pickable==="3d")}_getPointPickOptions(e,t,n={},i=this.layerManager?.getLayers()||[]){return{x:e,y:t,canvasId:n.canvasId,radius:this.props.pickingRadius,unproject3D:this._shouldUnproject3D(i),...n}}_pickPointSync(e){return this._pick("pickObject","pickObject Time",e)}_pickPointAsync(e){return this._pickAsync("pickObjectAsync","pickObject Time",e)}_getLastPointerDownPickingInfo(e,t,n,i=this.layerManager?.getLayers()||[]){return this.deckPicker.getLastPickedObject({x:e,y:t,layers:i,viewports:this.getViewports({x:e,y:t,canvasId:n})},this._lastPointerDownInfo)}_applyHoverCallbacks({result:e,emptyInfo:t},n){if(!this.widgetManager)return;this.cursorState.isHovering=e.length>0;let i=t,o=!1;for(let s of e)i=s,o=s.layer?.onHover(s,n)||o;o||(this.props.onHover?.(i,n),this.widgetManager.onHover(i,n))}_dispatchPickingEvent(e,t){if(!this.layerManager||!this.widgetManager)return;let n=Ii[t.type];if(!n)return;let{layer:i}=e,o=i&&(i[n]||i.props[n]),s=this.props[n],a=!1;o&&(a=o.call(i,e,t)),a||(s?.(e,t),this.widgetManager.onEvent(e,t))}_pickAsync(e,t,n){q(this.deckPicker);let{stats:i}=this,o=this._isMultiCanvasMode()?n.canvasId||this._getDefaultCanvasId():n.canvasId,s=this._getCanvasContext(o)||void 0;i.get("Pick Count").incrementCount(),i.get(t).timeStart(),this._resizeForCanvasTarget(o);let a=this.deckPicker[e]({layers:this.layerManager.getLayers(n),views:this.viewManager.getViews(),viewports:this.getViewports({...n,canvasId:o}),onViewportActive:this.layerManager.activateViewport,effects:this.effectManager.getEffects(),...n,canvasId:o,canvasContext:s});return i.get(t).timeEnd(),a}_pick(e,t,n){q(this.deckPicker);let{stats:i}=this,o=this._isMultiCanvasMode()?n.canvasId||this._getDefaultCanvasId():n.canvasId,s=this._getCanvasContext(o)||void 0;i.get("Pick Count").incrementCount(),i.get(t).timeStart(),this._resizeForCanvasTarget(o);let a=this.deckPicker[e]({layers:this.layerManager.getLayers(n),views:this.viewManager.getViews(),viewports:this.getViewports({...n,canvasId:o}),onViewportActive:this.layerManager.activateViewport,effects:this.effectManager.getEffects(),...n,canvasId:o,canvasContext:s});return i.get(t).timeEnd(),a}_createCanvas(e){let t=e.canvas;return typeof t=="string"&&(t=document.getElementById(t),q(t)),t?this._ownedCanvas=null:(t=document.createElement("canvas"),t.id=e.id||"deckgl-overlay",e.width&&typeof e.width=="number"&&(t.width=e.width),e.height&&typeof e.height=="number"&&(t.height=e.height),(e.parent||document.body).appendChild(t),this._ownedCanvas=t),Object.assign(t.style,e.style),t}_isMultiCanvasMode(){return Array.isArray(this.props._canvases)}_getDefaultCanvasId(){return this._canvasManager.order[0]||Hr}_validateCanvasConfiguration(e){Array.isArray(e._canvases)&&(q(!e.canvas),q(!e.gl),q(!e.device?.canvasContext||e.device.getDefaultCanvasContext().offscreenCanvas))}_createEventManager(e){let t=new ws(e,{touchAction:this.props.touchAction,recognizers:Object.keys(Np).map(n=>{let[i,o,s,a]=Np[n],c=this.props.eventRecognizerOptions?.[n],l={...o,...c,event:n};return{recognizer:new i(l),recognizeWith:s,requireFailure:a}}),events:{pointerdown:this._onPointerDown,pointermove:this._onPointerMove,pointerleave:this._onPointerMove}});for(let n in Ii)n==="dblclick"?t.watch(n,this._onEvent):t.on(n,this._onEvent);return t}_getEventRoot(e){return e.closest(".deck-events-root")||this.props.parent?.querySelector(".deck-events-root")||e}_syncCanvasTargets(){if(!this.device||!this._isMultiCanvasMode())return;this._canvasManager.syncCanvasEntries({device:this.device,canvases:this.props._canvases||[],useDevicePixels:this.props.useDevicePixels}),this.eventManagers=this._canvasManager.eventManagers;let e=this._getDefaultCanvasId();this.eventManager=this.eventManagers[e]||null,this.canvas=this._canvasManager.targets[e]?.canvas||null}_setCanvasContext(e){this._canvasContext=e,"style"in e.canvas&&(this.canvas=e.canvas)}_setDeviceCanvasContext(e,t={}){let n=e.getDefaultCanvasContext();this._setCanvasContext(n),this._setDeviceResizeHandler(e,t)}_setDeviceResizeHandler(e,t={}){let n=!!t.syncDrawingBuffer;if(this._deviceResizeHandler?.device===e){this._deviceResizeHandler.syncDrawingBuffer=n;return}this._restoreDeviceResizeHandler();let i=o=>{this._isMultiCanvasMode()?this._updateMultiCanvasDimensions():o===this._canvasContext&&this._canvasContext&&this._onCanvasContextResize(this._canvasContext,{syncDrawingBuffer:this._deviceResizeHandler?.syncDrawingBuffer})};e.props.onResize=i,this._deviceResizeHandler={device:e,onResize:i,syncDrawingBuffer:n}}_restoreDeviceResizeHandler(){let e=this._deviceResizeHandler;e&&e.device.props?.onResize===e.onResize&&(e.device.props.onResize=xr),this._deviceResizeHandler=null}_setCanvasSize(e){if(this._isMultiCanvasMode()||!this.canvas)return;let{width:t,height:n}=e;if(t||t===0){let i=Number.isFinite(t)?`${t}px`:t;this.canvas.style.width=i}if(n||n===0){let i=Number.isFinite(n)?`${n}px`:n;this.canvas.style.position=e.style?.position||"absolute",this.canvas.style.height=i}}_getCanvasIdFromEvent(e){return this._canvasManager.getCanvasIdFromEvent(e?.rootElement)}_getCanvasContext(e){return this._canvasManager.getTarget(e)?.presentationContext||this._canvasContext}_resizeForCanvasTarget(e){let t=this._canvasManager.getTarget(e);if(!t||!this.device?.canvasContext)return;let[n,i]=t.presentationContext.getDrawingBufferSize();this.device.canvasContext.setDrawingBufferSize(n,i)}_createDeviceCanvas(e){if(this._isMultiCanvasMode()){let t=globalThis.OffscreenCanvas;if(!t)throw new Error("`_canvases` requires OffscreenCanvas support.");let n=typeof e.width=="number"&&Number.isFinite(e.width)?e.width:1,i=typeof e.height=="number"&&Number.isFinite(e.height)?e.height:1;return new t(n,i)}return this._createCanvas(e)}_updateCanvasSize(e=this._canvasContext){if(this._isMultiCanvasMode()){this._updateMultiCanvasDimensions();return}let{canvas:t}=this,[n,i]=e?e.getCSSSize():[t?.clientWidth??t?.width??0,t?.clientHeight??t?.height??0];(n!==this.width||i!==this.height)&&(this.width=n,this.height=i,this.viewManager?.setProps({width:n,height:i}),this.layerManager?.activateViewport(this.getViewports()[0]),this.props.onResize({width:n,height:i},e||void 0))}_onCanvasContextResize(e,t={}){if(t.syncDrawingBuffer){let{width:n,height:i}=e.canvas;e.setDrawingBufferSize(n,i)}this._needsRedraw="Canvas resized",this._updateCanvasSize(e)}_updateMultiCanvasDimensions(){let[e,t]=this._getCanvasContext()?.getCSSSize()||[0,0];(e!==this.width||t!==this.height)&&(this.width=e,this.height=t,this.props.onResize({width:e,height:t})),this._needsRedraw="Canvas resized",this.viewManager?.setNeedsUpdate("Canvas resized"),this.viewManager?.setProps({width:this.width,height:this.height})}_createAnimationLoop(e,t){let{gl:n,onError:i}=t;return new Os({device:e,autoResizeDrawingBuffer:!n&&!Array.isArray(t._canvases),autoResizeViewport:!1,onInitialize:o=>this._setDevice(o.device),onRender:this._onRenderFrame.bind(this),onError:i})}_createDevice(e){let t=this.props.deviceProps?.createCanvasContext,n=typeof t=="object"?t:void 0,i={adapters:[],_cacheShaders:!0,_cachePipelines:!0,...e.deviceProps};i.adapters.includes(ua)||i.adapters.push(ua);let o={alphaMode:this.props.deviceProps?.type==="webgpu"?"premultiplied":void 0};return fi.createDevice({_reuseDevices:!0,type:"webgl",...i,createCanvasContext:{...o,...n,canvas:this._createDeviceCanvas(e),useDevicePixels:this.props.useDevicePixels,autoResize:!0}})}_getViewState(){return this.props.viewState||this.viewState}_getViews(){let{views:e}=this.props,t=Array.isArray(e)?e:e?[e]:[new Bw({id:"default-view"})];return t.length&&this.props.controller&&(t[0]=t[0].clone({controller:this.props.controller})),t}_onContextLost(){let{onError:e}=this.props;this.animationLoop&&e&&e(new Error("WebGL context is lost"))}_pickAndCallback(){let{_pickRequest:e}=this;if(e.event){let t=e.event,n=this.layerManager?.getLayers()||[],i=this._getPointPickOptions(e.x,e.y,{canvasId:e.canvasId,radius:e.radius,mode:e.mode},n),o=this._getInternalPickingMode(),s=++this._hoverPickSequence;if(e.event=null,e.canvasId=void 0,!o)return;if(o==="sync"){this._applyHoverCallbacks(this._pickPointSync(i),t);return}this._pickPointAsync(i).then(({result:a,emptyInfo:c})=>{s===this._hoverPickSequence&&this._applyHoverCallbacks({result:a,emptyInfo:c},t)}).catch(a=>this.props.onError?.(a))}}_updateCursor(){let e=this.props.getCursor(this.cursorState);if(this._isMultiCanvasMode()){for(let n of Object.values(this._canvasManager.targets))n.canvas.style.cursor=e;return}let t=this.props.parent||this.canvas;t&&(t.style.cursor=e)}_setDevice(e){if(this.device=e,this._validateInternalPickingMode(),!this.animationLoop)return;this._setDeviceCanvasContext(e,{syncDrawingBuffer:!!(this.props.gl&&this.props.device!==e)}),this._isMultiCanvasMode()?this._syncCanvasTargets():this.canvas&&!this.canvas.isConnected&&this.props.parent&&this.props.parent.insertBefore(this.canvas,this.props.parent.firstChild),this.device.type==="webgl"&&this.device.setParametersWebGL({blend:!0,blendFunc:[770,771,1,771],polygonOffsetFill:!0,depthTest:!0,depthFunc:515}),this.props.onDeviceInitialized(this.device),this.device.type==="webgl"&&this.props.onWebGLInitialized(this.device.gl);let t=new Un;if(t.play(),this.animationLoop.attachTimeline(t),!this._isMultiCanvasMode()){let o=this.canvas&&this._getEventRoot(this.canvas);q(o),this.eventManager=this._createEventManager(o),this.eventManagers={[Hr]:this.eventManager}}this.viewManager=new Vs({timeline:t,eventManager:this.eventManager,eventManagers:this.eventManagers,getCanvasContext:this._isMultiCanvasMode()?this.getCanvasContext.bind(this):void 0,onViewStateChange:this._onViewStateChange.bind(this),onInteractionStateChange:this._onInteractionStateChange.bind(this),pickPosition:this._pickPositionForController.bind(this),views:this._getViews(),viewState:this._getViewState(),width:this.width,height:this.height});let n=this.viewManager.getViewports()[0];this.layerManager=new $s(this.device,{deck:this,stats:this.stats,viewport:n,timeline:t}),this.effectManager=new qs({deck:this,device:this.device}),this.deckRenderer=new Zs(this.device,{stats:this.stats}),this.deckPicker=new Ks(this.device,{stats:this.stats});let i=this.props.parent?.querySelector(".deck-widgets-root")||(this._isMultiCanvasMode()?this.props.parent||this.canvas?.parentElement:null)||this.canvas?.parentElement;this.widgetManager=new tu({deck:this,parentElement:i}),this.widgetManager.addDefault(new Qs),this.setProps({}),this._updateCanvasSize(this._canvasContext),this.props.onLoad()}_drawLayers(e,t){let{device:n,gl:i}=this.layerManager.context;this.props.onBeforeRender({device:n,gl:i});let o={target:this.props._framebuffer,layers:this.layerManager.getLayers(),viewports:this.viewManager.getViewports(),onViewportActive:this.layerManager.activateViewport,views:this.viewManager.getViews(),pass:"screen",effects:this.effectManager.getEffects(),...t};if(this._isMultiCanvasMode()&&o.pass==="screen"&&!o.target&&this._canvasManager.order.length)for(let s of this._canvasManager.order){let a=o.viewports.filter(u=>this.viewManager.getCanvasId(u.id)===s);if(!a.length){let u=this._canvasManager.targets[s];this._resizeForCanvasTarget(s),this.deckRenderer?.renderLayers({...o,canvasContext:u.presentationContext,target:u.presentationContext.getCurrentFramebuffer(),viewports:[],clearCanvas:!0}),u.presentationContext.present();continue}let c=this._canvasManager.targets[s];this._resizeForCanvasTarget(s);let l=c.presentationContext.getCurrentFramebuffer();this.deckRenderer?.renderLayers({...o,canvasContext:c.presentationContext,target:l,viewports:a}),c.presentationContext.present()}else this.deckRenderer?.renderLayers(o);o.pass==="screen"&&this.widgetManager.onRedraw({viewports:o.viewports,layers:o.layers}),this.props.onAfterRender({device:n,gl:i})}_onRenderFrame(){this._getFrameStats(),this._metricsCounter++%60===0&&(this._getMetrics(),this.stats.reset(),$.table(4,this.metrics)(),this.props._onMetrics&&this.props._onMetrics(this.metrics)),this._updateCursor(),this.layerManager.updateLayers(),this._pickAndCallback(),this.redraw(),this.viewManager&&this.viewManager.updateViewStates()}_onViewStateChange(e){let t=this.props.onViewStateChange(e)||e.viewState;this.viewState&&(this.viewState={...this.viewState,[e.viewId]:t},this.props.viewState||this.viewManager&&this.viewManager.setProps({viewState:this.viewState}))}_onInteractionStateChange(e){this.cursorState.isDragging=e.isDragging||!1,this.props.onInteractionStateChange(e)}_getFrameStats(){let{stats:e}=this;e.get("frameRate").timeEnd(),e.get("frameRate").timeStart();let t=this.animationLoop.stats;e.get("GPU Time").addTime(t.get("GPU Time").lastTiming),e.get("CPU Time").addTime(t.get("CPU Time").lastTiming)}_getMetrics(){let{metrics:e,stats:t}=this;e.fps=t.get("frameRate").getHz(),e.setPropsTime=t.get("setProps Time").time,e.updateAttributesTime=t.get("Update Attributes").time,e.framesRedrawn=t.get("Redraw Count").count,e.pickTime=t.get("pickObject Time").time+t.get("pickMultipleObjects Time").time+t.get("pickObjects Time").time,e.pickCount=t.get("Pick Count").count,e.layersCount=this.layerManager?.layers.length??0,e.drawLayersCount=t.get("Layers rendered").lastSampleCount,e.pickLayersCount=t.get("Layers picked").lastSampleCount,e.updateLayersCount=t.get("Layer updates").count,e.updateAttributesCount=t.get("Attributes updated").count,e.gpuTime=t.get("GPU Time").time,e.cpuTime=t.get("CPU Time").time,e.gpuTimePerFrame=t.get("GPU Time").getAverageTime(),e.cpuTimePerFrame=t.get("CPU Time").getAverageTime();let n=fi.stats.get("GPU Time and Memory");e.bufferMemory=n.get("Buffer Memory").count,e.textureMemory=n.get("Texture Memory").count,e.renderbufferMemory=n.get("Renderbuffer Memory").count,e.gpuMemory=n.get("GPU Memory").count}};fa.defaultProps=o2;fa.VERSION=m_;var $m=fa;N();N();function s2(r){switch(r){case"float64":return Float64Array;case"uint8":case"unorm8":return Uint8ClampedArray;default:return hn(r)}}var a2=Te.getDataType.bind(Te);function da(r,e,t){if(e.size>4)return null;let n=t==="webgpu"&&e.type==="uint8"?"unorm8":e.type,i=e.size,o=!!(t!=="webgpu"&&i===3&&n&&["uint8","sint8","unorm8","snorm8","uint16","sint16","unorm16","snorm16"].includes(n));return{attribute:r,format:i>1?`${n}x${i}${o?"-webgl":""}`:e.type,byteOffset:e.offset||0}}function bt(r){return r.stride||r.size*r.bytesPerElement}function c2(r,e){return r.type===e.type&&r.size===e.size&&bt(r)===bt(e)&&(r.offset||0)===(e.offset||0)}function Vm(r,e){e.offset&&$.removed("shaderAttribute.offset","vertexOffset, elementOffset")();let t=bt(r),n=e.vertexOffset!==void 0?e.vertexOffset:r.vertexOffset||0,i=e.elementOffset||0,o=n*t+i*r.bytesPerElement+(r.offset||0);return{...e,offset:o,stride:t}}function Jk(r,e){let t=Vm(r,e);return{high:t,low:{...t,offset:t.offset+r.size*4}}}var ha=class{constructor(e,t,n){this._buffer=null,this.device=e,this.id=t.id||"",this.size=t.size||1;let i=t.logicalType||t.type,o=i==="float64",{defaultValue:s}=t;s=Number.isFinite(s)?[s]:s||new Array(this.size).fill(0);let a;o?a="float32":!i&&t.isIndexed?a="uint32":a=i||"float32";let c=s2(i||a);this.doublePrecision=o,o&&t.fp64===!1&&(c=Float32Array),this.value=null,this.settings={...t,defaultType:c,defaultValue:s,logicalType:i,type:a,normalized:a.includes("norm"),size:this.size,bytesPerElement:c.BYTES_PER_ELEMENT},this.state={...n,externalBuffer:null,bufferAccessor:this.settings,allocatedValue:null,numInstances:0,bounds:null,constant:!1}}get isConstant(){return this.state.constant}get buffer(){return this._buffer}get byteOffset(){let e=this.getAccessor();return e.vertexOffset?e.vertexOffset*bt(e):0}get numInstances(){return this.state.numInstances}set numInstances(e){this.state.numInstances=e}get isDoublePrecisionBuffer(){return this._shouldSplitDoublePrecisionValue(this.value)}delete(){this._buffer&&(this._buffer.delete(),this._buffer=null),Lt.release(this.state.allocatedValue),this.state.allocatedValue=null}getBuffer(){return this.state.constant&&this.device.type!=="webgpu"?null:this.state.externalBuffer||this._buffer}getValue(e=this.id,t=null){let n={};if(this.state.constant){let i=this.value;if(this.device.type==="webgpu"&&this._buffer)n[e]=this._buffer;else if(t){let o=Vm(this.getAccessor(),t),s=o.offset/i.BYTES_PER_ELEMENT,a=o.size||this.size;n[e]=i.subarray(s,s+a)}else n[e]=i}else n[e]=this.getBuffer();return this.doublePrecision&&(this.isDoublePrecisionBuffer?n[`${e}64Low`]=n[e]:n[`${e}64Low`]=new Float32Array(this.size)),n}_getBufferLayout(e=this.id,t=null){let n=this.getAccessor(),i=[],o={name:this.id,byteStride:this.device.type==="webgpu"&&this.state.constant?0:bt(n)};if(this.doublePrecision){let s=Jk(n,t||{});i.push(da(e,{...n,...s.high},this.device.type),da(`${e}64Low`,{...n,...s.low},this.device.type))}else if(t){let s=Vm(n,t);i.push(da(e,{...n,...s},this.device.type))}else i.push(da(e,n,this.device.type));return o.attributes=i.filter(Boolean),o}setAccessor(e){this.state.bufferAccessor=e}getAccessor(){return this.state.bufferAccessor}getBounds(){if(this.state.bounds)return this.state.bounds;let e=null;if(this.state.constant&&this.value){let t=Array.from(this.value);e=[t,t]}else{let{value:t,numInstances:n,size:i}=this,o=n*i;if(t&&o&&t.length>=o){let s=new Array(i).fill(1/0),a=new Array(i).fill(-1/0);for(let c=0;c<o;)for(let l=0;l<i;l++){let u=t[c++];u<s[l]&&(s[l]=u),u>a[l]&&(a[l]=u)}e=[s,a]}}return this.state.bounds=e,e}setData(e){let{state:t}=this,n;ArrayBuffer.isView(e)?n={value:e}:e instanceof z?n={buffer:e}:n=e;let i={...this.settings,...n};if(ArrayBuffer.isView(n.value)){if(!n.type)if(this.doublePrecision&&n.value instanceof Float64Array)i.type="float32";else{let s=a2(n.value);i.type=i.normalized?s.replace("int","norm"):s}i.bytesPerElement=n.value.BYTES_PER_ELEMENT,i.stride=bt(i)}if(t.bounds=null,n.constant){let o=n.value;if(o=this._normalizeValue(o,[],0),this.settings.normalized&&(o=this.normalizeConstant(o)),!(!t.constant||!this._areValuesEqual(o,this.value)))return!1;t.externalBuffer=null,t.constant=!0,this.value=ArrayBuffer.isView(o)?o:new Float32Array(o)}else if(n.buffer){let o=n.buffer;t.externalBuffer=o,t.constant=!1,this.value=n.value||null}else if(n.value){this._checkExternalBuffer(n);let o=n.value,s=o;t.externalBuffer=null,t.constant=!1,this.value=o,this._shouldSplitDoublePrecisionValue(s)&&(s=Ui(s,i),o instanceof Float32Array&&(i.stride=i.size*2*Float32Array.BYTES_PER_ELEMENT));let{buffer:a}=this,c=bt(i),l=(i.vertexOffset||0)*c;if(this.settings.isIndexed){let f=this.settings.defaultType;s.constructor!==f&&(s=new f(s))}let u=s.byteLength+l+c*2;(!a||a.byteLength<u)&&(a=this._createBuffer(u)),a.write(s,l)}return this.setAccessor(i),!0}updateSubBuffer(e={}){this.state.bounds=null;let t=this.value,{startOffset:n=0,endOffset:i}=e,o=this._shouldSplitDoublePrecisionValue(t);this.buffer.write(o?Ui(t,{size:this.size,startIndex:n,endIndex:i}):t.subarray(n,i),n*(o?8:t.BYTES_PER_ELEMENT)+this.byteOffset)}allocate(e,t=!1){let{state:n}=this,i=n.allocatedValue,o=Lt.allocate(i,e+1,{size:this.size,type:this.settings.defaultType,copy:t});this.value=o;let s=this._shouldSplitDoublePrecisionValue(o),a=s&&o instanceof Float32Array?{...this.settings,stride:this.size*2*Float32Array.BYTES_PER_ELEMENT}:this.settings;this.setAccessor(a);let{byteOffset:c}=this,{buffer:l}=this,u=o.byteLength*(s&&o instanceof Float32Array?2:1);return(!l||l.byteLength<u+c)&&(l=this._createBuffer(u+c),t&&i&&l.write(this._shouldSplitDoublePrecisionValue(i)?Ui(i,this):i,c)),n.allocatedValue=o,n.constant=!1,n.externalBuffer=null,!0}_shouldSplitDoublePrecisionValue(e){return!!(this.doublePrecision&&(e instanceof Float64Array||this.device.type==="webgpu"&&e instanceof Float32Array))}_checkExternalBuffer(e){let{value:t}=e;if(!ArrayBuffer.isView(t))throw new Error(`Attribute ${this.id} value is not TypedArray`);let n=this.settings.defaultType,i=!1;if(this.doublePrecision&&(i=t.BYTES_PER_ELEMENT<4),i)throw new Error(`Attribute ${this.id} does not support ${t.constructor.name}`);!(t instanceof n)&&this.settings.normalized&&!("normalized"in e)&&$.warn(`Attribute ${this.id} is normalized`)()}normalizeConstant(e){switch(this.settings.type){case"snorm8":return new Float32Array(e).map(t=>(t+128)/255*2-1);case"snorm16":return new Float32Array(e).map(t=>(t+32768)/65535*2-1);case"unorm8":return new Float32Array(e).map(t=>t/255);case"unorm16":return new Float32Array(e).map(t=>t/65535);default:return e}}_normalizeValue(e,t,n){let{defaultValue:i,size:o}=this.settings;if(Number.isFinite(e))return t[n]=e,t;if(!e){let s=o;for(;--s>=0;)t[n+s]=i[s];return t}switch(o){case 4:t[n+3]=Number.isFinite(e[3])?e[3]:i[3];case 3:t[n+2]=Number.isFinite(e[2])?e[2]:i[2];case 2:t[n+1]=Number.isFinite(e[1])?e[1]:i[1];case 1:t[n+0]=Number.isFinite(e[0])?e[0]:i[0];break;default:let s=o;for(;--s>=0;)t[n+s]=Number.isFinite(e[s])?e[s]:i[s]}return t}_areValuesEqual(e,t){if(!e||!t)return!1;let{size:n}=this;for(let i=0;i<n;i++)if(e[i]!==t[i])return!1;return!0}_createBuffer(e){this._buffer&&this._buffer.destroy();let{isIndexed:t,type:n}=this.settings,i=this.device.type==="webgpu"&&!t?z.VERTEX|z.STORAGE|z.COPY_DST|z.COPY_SRC:(t?z.INDEX:z.VERTEX)|z.COPY_DST;return this._buffer=this.device.createBuffer({...this._buffer?.props,id:this.id,usage:i,indexType:t?n:void 0,byteLength:e}),this._buffer}};var l2=[],u2=[];function Nu(r,e=0,t=1/0){let n=l2,i={index:-1,data:r,target:[]};return r?typeof r[Symbol.iterator]=="function"?n=r:r.length>0&&(u2.length=r.length,n=u2):n=l2,(e>0||Number.isFinite(t))&&(n=(Array.isArray(n)?n:Array.from(n)).slice(e,t),i.index=e-1),{iterable:n,objectInfo:i}}function Fu(r){return r&&r[Symbol.asyncIterator]}function Uu(r,e){let{size:t,stride:n,offset:i,startIndices:o,nested:s}=e,a=r.BYTES_PER_ELEMENT,c=n?n/a:t,l=i?i/a:0,u=Math.floor((r.length-l)/c);return(f,{index:h,target:p})=>{if(!o){let x=h*c+l;for(let v=0;v<t;v++)p[v]=r[x+v];return p}let m=o[h],g=o[h+1]||u,y;if(s){y=new Array(g-m);for(let x=m;x<g;x++){let v=x*c+l;p=new Array(t);for(let _=0;_<t;_++)p[_]=r[v+_];y[x-m]=p}}else if(c===t)y=r.subarray(m*t+l,g*t+l);else{y=new r.constructor((g-m)*t);let x=0;for(let v=m;v<g;v++){let _=v*c+l;for(let w=0;w<t;w++)y[x++]=r[_+w]}}return y}}var f2=[],pa=[[0,1/0]];function d2(r,e){if(r===pa||(e[0]<0&&(e[0]=0),e[0]>=e[1]))return r;let t=[],n=r.length,i=0;for(let o=0;o<n;o++){let s=r[o];s[1]<e[0]?(t.push(s),i=o+1):s[0]>e[1]?t.push(s):e=[Math.min(s[0],e[0]),Math.max(s[1],e[1])]}return t.splice(i,0,e),t}var t4={interpolation:{duration:0,easing:r=>r},spring:{stiffness:.05,damping:.5}};function Gu(r,e){if(!r)return null;Number.isFinite(r)&&(r={type:"interpolation",duration:r});let t=r.type||"interpolation";return{...t4[t],...e,...r,type:t}}var qn=class extends ha{constructor(e,t){super(e,t,{startIndices:null,constantValue:null,lastExternalBuffer:null,binaryValue:null,binaryAccessor:null,needsUpdate:!0,needsRedraw:!1,layoutChanged:!1,updateRanges:pa}),this.constant=!1,this.settings.update=t.update||(t.accessor?this._autoUpdater:void 0),Object.seal(this.settings),Object.seal(this.state),this._validateAttributeUpdaters()}get startIndices(){return this.state.startIndices}set startIndices(e){this.state.startIndices=e}needsUpdate(){return this.state.needsUpdate}needsRedraw({clearChangedFlags:e=!1}={}){let t=this.state.needsRedraw;return this.state.needsRedraw=t&&!e,t}layoutChanged(){return this.state.layoutChanged}setAccessor(e){var t;(t=this.state).layoutChanged||(t.layoutChanged=!c2(e,this.getAccessor())),super.setAccessor(e)}getUpdateTriggers(){let{accessor:e}=this.settings;return[this.id].concat(typeof e!="function"&&e||[])}supportsTransition(){return!!this.settings.transition}getTransitionSetting(e){if(!e||!this.supportsTransition())return null;let{accessor:t}=this.settings,n=this.settings.transition,i=Array.isArray(t)?e[t.find(o=>e[o])]:e[t];return Gu(i,n)}setNeedsUpdate(e=this.id,t){if(this.state.needsUpdate=this.state.needsUpdate||e,this.setNeedsRedraw(e),t){let{startRow:n=0,endRow:i=1/0}=t;this.state.updateRanges=d2(this.state.updateRanges,[n,i])}else this.state.updateRanges=pa}clearNeedsUpdate(){this.state.needsUpdate=!1,this.state.updateRanges=f2}setNeedsRedraw(e=this.id){this.state.needsRedraw=this.state.needsRedraw||e}allocate(e){let{state:t,settings:n}=this;if(n.noAlloc)return!1;if(n.update){let i=this.isConstant;return super.allocate(e,t.updateRanges!==pa),t.layoutChanged||(t.layoutChanged=i&&this.device.type==="webgpu"),!0}return!1}updateBuffer({numInstances:e,data:t,props:n,context:i}){if(!this.needsUpdate())return!1;let{state:{updateRanges:o},settings:{update:s,noAlloc:a}}=this,c=!0;if(s){for(let[l,u]of o)s.call(i,this,{data:t,startRow:l,endRow:u,props:n,numInstances:e});if(this.value)if(this.constant||!this.buffer||this.buffer.byteLength<this.value.byteLength+this.byteOffset){if(this.constant){let l=this.value;this.value=null,this.setConstantValue(i,l)}else this.setData({value:this.value,constant:this.constant});this.constant=!1}else for(let[l,u]of o){let f=Number.isFinite(l)?this.getVertexOffset(l):0,h=Number.isFinite(u)?this.getVertexOffset(u):a||!Number.isFinite(e)?this.value.length:e*this.size;super.updateSubBuffer({startOffset:f,endOffset:h})}this._checkAttributeArray()}else c=!1;return this.clearNeedsUpdate(),this.setNeedsRedraw(),c}setConstantValue(e,t){var n;if(t===void 0||typeof t=="function")return!1;let i=this.isConstant,o=this.settings.transform&&e?this.settings.transform.call(e,t):t,s=this.settings.defaultType;this.state.constantValue=this._normalizeValue(o,new s(this.size),0);let a=this.setData({constant:!0,value:o});if(this.device.type==="webgpu"){let c=this.state.constantValue;this.doublePrecision&&(c instanceof Float32Array||c instanceof Float64Array)&&(c=Ui(c,{size:this.size}),this.setAccessor({...this.getAccessor(),stride:this.size*2*Float32Array.BYTES_PER_ELEMENT}));let l=this._buffer;(!l||l.byteLength<c.byteLength)&&(l=this._createBuffer(c.byteLength)),l.write(c),(n=this.state).layoutChanged||(n.layoutChanged=!i),this.constant=!1}return a&&this.setNeedsRedraw(),this.clearNeedsUpdate(),!0}getConstantValue(){return this.isConstant?this.state.constantValue:null}setExternalBuffer(e){let{state:t}=this;return e?(this.clearNeedsUpdate(),t.lastExternalBuffer===e||(t.lastExternalBuffer=e,this.setNeedsRedraw(),this.setData(e)),!0):(t.lastExternalBuffer=null,!1)}setBinaryValue(e,t=null){let{state:n,settings:i}=this;if(!e)return n.binaryValue=null,n.binaryAccessor=null,!1;if(i.noAlloc)return!1;if(n.binaryValue===e)return this.clearNeedsUpdate(),!0;if(n.binaryValue=e,this.setNeedsRedraw(),i.transform||t!==this.startIndices){ArrayBuffer.isView(e)&&(e={value:e});let s=e;q(ArrayBuffer.isView(s.value),`invalid ${i.accessor}`);let a=!!s.size&&s.size!==this.size;return n.binaryAccessor=Uu(s.value,{size:s.size||this.size,stride:s.stride,offset:s.offset,startIndices:t,nested:a}),!1}return this.clearNeedsUpdate(),this.setData(e),!0}getVertexOffset(e){let{startIndices:t}=this;return(t?e<t.length?t[e]:this.numInstances:e)*this.size}getValue(){let e=this.settings.shaderAttributes,t=super.getValue();if(!e)return t;for(let n in e)Object.assign(t,super.getValue(n,e[n]));return t}getBufferLayout(e){this.state.layoutChanged=!1;let t=this.settings.shaderAttributes,n=super._getBufferLayout(),{stepMode:i}=this.settings;if(i==="dynamic"?n.stepMode=e?e.isInstanced?"instance":"vertex":"instance":n.stepMode=i??"vertex",!t)return n;for(let o in t){let s=super._getBufferLayout(o,t[o]);n.attributes.push(...s.attributes)}return n}_autoUpdater(e,{data:t,startRow:n,endRow:i,props:o,numInstances:s}){let{settings:a,state:c,value:l,size:u,startIndices:f}=e,{accessor:h,transform:p}=a,m=c.binaryAccessor||(typeof h=="function"?h:o[h]);q(typeof m=="function",`accessor "${h}" is not a function`);let g=e.getVertexOffset(n),{iterable:y,objectInfo:x}=Nu(t,n,i);for(let v of y){x.index++;let _=m(v,x);if(p&&(_=p.call(this,_)),f){let w=(x.index<f.length-1?f[x.index+1]:s)-f[x.index];if(_&&Array.isArray(_[0])){let E=g;for(let S of _)e._normalizeValue(S,l,E),E+=u}else _&&_.length>u?l.set(_,g):(e._normalizeValue(_,x.target,0),Sw({target:l,source:x.target,start:g,count:w}));g+=w*u}else e._normalizeValue(_,l,g),g+=u}}_validateAttributeUpdaters(){let{settings:e}=this;if(!(e.noAlloc||typeof e.update=="function"))throw new Error(`Attribute ${this.id} missing update or accessor`)}_checkAttributeArray(){let{value:e}=this,t=Math.min(4,this.size);if(e&&e.length>=t){let n=!0;switch(t){case 4:n=n&&Number.isFinite(e[3]);case 3:n=n&&Number.isFinite(e[2]);case 2:n=n&&Number.isFinite(e[1]);case 1:n=n&&Number.isFinite(e[0]);break;default:n=!1}if(!n)throw new Error(`Illegal attribute generated for ${this.id}`)}}};Er();Xm();Er();var ga=class r{constructor({id:e,gpuDataEvaluators:t,gpuVector:n,format:i}){d(this,"gpuDataEvaluators");d(this,"format");d(this,"length");d(this,"id");d(this,"_gpuVector");d(this,"_ownsGPUDataEvaluators");d(this,"_destroyed",!1);if(t.length===0)throw new Error("GPUVectorEvaluator requires at least one GPUData evaluator");p4(t),this.id=e,this.gpuDataEvaluators=t,this.format=i??t[0].format,this.length=t.reduce((o,s)=>o+s.length,0),this._gpuVector=n,this._ownsGPUDataEvaluators=!n}static fromGPUVector(e){if(e.bufferLayout)throw new Error(`GPUVectorEvaluator.fromGPUVector() does not accept interleaved vector "${e.name}"`);if(e.data.length===0)throw new Error(`GPUVectorEvaluator.fromGPUVector() requires GPUData for "${e.name}"`);return new r({id:e.name,gpuDataEvaluators:e.data.map(t=>Z.fromGPUData(t,{id:e.name})),gpuVector:e,format:e.format})}static fromGPUDataEvaluators(e,t={}){return new r({id:t.id,gpuDataEvaluators:e,format:t.format})}get evaluated(){return!!this._gpuVector}get gpuVector(){if(!this._gpuVector)throw new Error(`${this} not evaluated`);return this._gpuVector}mapGPUData(e){return r.fromGPUDataEvaluators(this.gpuDataEvaluators.map((t,n)=>e(t,n)),{id:this.id})}async evaluate(e,t={}){if(this._destroyed)throw new Error(`GPUVectorEvaluator ${this} already destroyed`);if(this._gpuVector)return this._gpuVector;let n=await Promise.all(this.gpuDataEvaluators.map(a=>a.evaluate(e,t))),i=n[0],o=n.map(S2),s=t.format??this.format??i.format;return this._gpuVector=new ir({type:"data",name:t.name??this.id??"vector",format:s,data:o,stride:i.stride,byteStride:i.byteStride,rowByteLength:i.rowByteLength,bufferLayout:i.bufferLayout}),this._gpuVector}evaluateSync(e,t={}){if(this._destroyed)throw new Error(`GPUVectorEvaluator ${this} already destroyed`);if(this._gpuVector)return this._gpuVector;let n=this.gpuDataEvaluators.map(a=>a.evaluateSync(e,t)),i=n[0],o=n.map(S2),s=t.format??this.format??i.format;return this._gpuVector=new ir({type:"data",name:t.name??this.id??"vector",format:s,data:o,stride:i.stride,byteStride:i.byteStride,rowByteLength:i.rowByteLength,bufferLayout:i.bufferLayout}),this._gpuVector}destroy(){if(this._ownsGPUDataEvaluators)for(let e of this.gpuDataEvaluators)e.destroy();this._gpuVector=void 0,this._destroyed=!0}toString(){return this.id??this.constructor.name}};function p4(r){let e=r[0];for(let t of r.slice(1))if(t.type!==e.type||t.size!==e.size||t.normalized!==e.normalized||t.format!==e.format)throw new Error("GPUVectorEvaluator requires matching GPUData evaluator layouts")}function S2(r){let[e,...t]=r.data;if(!e||t.length>0)throw new Error(`GPUVectorEvaluator requires one GPUData chunk for "${r.name}"`);return e}Er();N();var Jm={};cr(Jm,{arithmetic:()=>P2,dot:()=>I2,equalAll:()=>R2,extent:()=>L2,fround:()=>A2,gather:()=>C2,interleave:()=>M2,length:()=>B2,segmentedMap:()=>O2,select:()=>k2,sequence:()=>D2,swizzle:()=>N2});qu();function to({elementWise:r,func:e,inputs:t,output:n,outputBuffer:i}){let o=Array.isArray(t)?t:Object.values(t);for(let m of o)if(!m.value)throw new Error(`${m} does not have CPU value`);let s=n.length,a=n.size,c=new n.ValueType(s*a);for(let m=0;m<s;m++){let g=o.map(y=>he(y,m));if(r)for(let y=0;y<a;y++)c[m*a+y]=e.apply(null,g.map(x=>x[y]));else e.call(null,c.subarray(m*a,m*a+a),...g)}let l=n.ValueType.BYTES_PER_ELEMENT,u=n.offset/l,f=n.stride/l,h=a,p=c;if(u!==0||f!==h){p=new n.ValueType(u+n.byteLength/l);for(let m=0;m<s;m++){let g=m*h,y=u+m*f,x=c.subarray(g,g+a);p.set(x,y),i.write(x,y*l)}}else i.write(c);return{success:!0,value:p}}function he(r,e){let t=r.value,n=r.size,i=r.offset/r.ValueType.BYTES_PER_ELEMENT,o=r.stride/r.ValueType.BYTES_PER_ELEMENT,s=r.isConstant?0:e,a=i+s*o,c=t.slice(a,a+n);if(!r.normalized)return c;let l=new Float32Array(n);for(let u=0;u<n;u++)l[u]=m4(c[u],r.type);return l}function m4(r,e){switch(e){case"uint8":return r/255;case"uint16":return r/65535;case"uint32":return r/4294967295;case"sint8":return Math.max(r/127,-1);case"sint16":return Math.max(r/32767,-1);case"sint32":return Math.max(r/2147483647,-1);case"float32":return r;default:throw new Error(`Unsupported normalized source type ${e}`)}}var P2=({inputs:r,output:e,target:t})=>{for(let i of Object.values(r.namedInputs))if(!i.value)throw new Error(`${i} does not have CPU value`);let n=new e.ValueType(e.length*e.size);for(let i=0;i<e.length;i++){let o=Object.fromEntries(Object.entries(r.namedInputs).map(([s,a])=>[s,he(a,i)]));for(let s=0;s<e.size;s++)n[i*e.size+s]=T2(r.expression,o,s)}return t.write(n),{success:!0,value:n}};function T2(r,e,t){switch(r.kind){case"input":{let n=e[r.name];return t<n.length?n[t]:n.length===1?n[0]:0}case"literal":return Array.isArray(r.value)?r.value[t]??0:r.value;case"call":{g4(r.op,r.args.length);let n=r.args.map(i=>T2(i,e,t));switch(r.op){case"add":return n[0]+n[1];case"subtract":return n[0]-n[1];case"multiply":return n[0]*n[1];case"divide":return n[0]/n[1];case"pow":return Math.pow(n[0],n[1]);case"sqrt":return Math.sqrt(n[0]);case"abs":return Math.abs(n[0]);case"sin":return Math.sin(n[0]);case"cos":return Math.cos(n[0]);case"tan":return Math.tan(n[0]);case"exp":return Math.exp(n[0]);case"log":return Math.log(n[0]);default:{let i=r.op;throw new Error(`Unsupported arithmetic op ${i}`)}}}default:{let n=r;throw new Error(`Unsupported expression node ${n.kind}`)}}}function g4(r,e){let t=eo[r].arity;if(e!==t)throw new Error(`Arithmetic op '${r}' expects ${t} args, got ${e}`)}var L2=({inputs:r,output:e,target:t})=>{let{sourceValues:n}=r;if(!n.value)throw new Error(`${n} does not have CPU value`);let o=new e.ValueType(e.length*e.size);if(n.length===0)return{success:!1,error:new Error(`${n} is empty`)};for(let s=0;s<n.size;s++){let a=he(n,0)[s],c=s*e.size,l=c+1;o[c]=a,o[l]=a;for(let u=1;u<n.length;u++){let f=he(n,u)[s];f<o[c]&&(o[c]=f),f>o[l]&&(o[l]=f)}}return t.write(o),{success:!0,value:o}};var A2=({inputs:r,output:e,target:t})=>to({func:(n,i)=>{let o=n.length/2,s=new Float64Array(i.buffer);for(let a=0;a<o;a++){let c=s[a];n[a]=Math.fround(c),n[a+o]=c-n[a]}return n},inputs:r,output:e,outputBuffer:t});var C2=async({inputs:r,output:e,target:t})=>{let{ids:n,sourceValues:i}=r,o=n.value,s=i.value;if(!o)throw new Error(`${n} does not have CPU value`);if(!s)throw new Error(`${i} does not have CPU value`);let a=new e.ValueType(e.length*e.size),c=new Array(e.size).fill(0);for(let l=0;l<e.length;l++){let u=he(n,l),f=Number(u[0]),h=y4(f,i.length)?he(i,f):c;a.set(h,l*e.size)}return t.write(a),{success:!0,value:a}};function y4(r,e){return Number.isInteger(r)&&r>=0&&r<e}var M2=({inputs:r,output:e,target:t})=>to({func:(n,...i)=>{let o=0;for(let s of i)n.set(s,o),o+=s.length},inputs:r,output:e,outputBuffer:t});var I2=({inputs:r,output:e,target:t})=>{let{x:n,y:i}=r,o=new e.ValueType(e.length);for(let s=0;s<e.length;s++){let a=he(n,s),c=he(i,s),l=0;for(let u=0;u<n.size;u++)l+=a[u]*c[u];o[s]=l}return t.write(o),{success:!0,value:o}};var R2=({inputs:r,output:e,target:t})=>{let{x:n,y:i}=r,o=new e.ValueType(e.length);for(let s=0;s<e.length;s++){let a=he(n,s),c=he(i,s),l=1;for(let u=0;u<n.size;u++)if(a[u]!==c[u]){l=0;break}o[s]=l}return t.write(o),{success:!0,value:o}};var B2=({inputs:r,output:e,target:t})=>{let{x:n}=r,i=new e.ValueType(e.length);for(let o=0;o<e.length;o++){let s=he(n,o),a=0;for(let c=0;c<n.size;c++)a+=s[c]*s[c];i[o]=Math.sqrt(a)}return t.write(i),{success:!0,value:i}};var O2=async({inputs:r,output:e,target:t})=>{let{segments:n,vertexCount:i}=r,o=n.value;if(!o)throw new Error(`${n} does not have CPU value`);_4(o,n,i);let s=new e.ValueType(e.length*e.size),a=0;for(let c=0;c<i;c++){for(;a+1<n.length&&o[Km(n,a+1)]<=c;)a++;let l=o[Km(n,a)],u=c*e.size;s[u]=a,s[u+1]=c-l}return t.write(s),{success:!0,value:s}};function _4(r,e,t){if(e.length<1)throw new Error("segmentedMap segments must contain at least one segment start");let n=0;for(let i=0;i<e.length;i++){let o=r[Km(e,i)];if(i===0&&o!==0)throw new Error(`segmentedMap segments must start at 0, got ${o}`);if(i>0&&o<n)throw new Error(`segmentedMap segments must be non-decreasing, got ${o} after ${n}`);n=o}if(n>t)throw new Error(`segmentedMap last segment start must be <= vertexCount, got ${n} > ${t}`)}function Km(r,e){return r.offset/r.ValueType.BYTES_PER_ELEMENT+e*(r.stride/r.ValueType.BYTES_PER_ELEMENT)}var k2=async({inputs:r,output:e,target:t})=>{let{condition:n,whenTrue:i,whenFalse:o}=r,s=new e.ValueType(e.length*e.size);for(let a=0;a<e.length;a++){let c=he(n,a),l=he(i,a),u=he(o,a);for(let f=0;f<e.size;f++){let h=Qm(c,n.size,f);s[a*e.size+f]=h!==0?Qm(l,i.size,f):Qm(u,o.size,f)}}return t.write(s),{success:!0,value:s}};function Qm(r,e,t){return t<e?r[t]:e===1?r[0]:0}var D2=({inputs:r,output:e,target:t})=>{let n=new e.ValueType(e.length);for(let i=0;i<e.length;i++)n[i]=r.start+i*r.step;return t.write(n),{success:!0,value:n}};var N2=({inputs:r,output:e,target:t})=>{let{columns:n}=r;return to({func:(i,o)=>{for(let s=0;s<n.length;s++)i[s]=o[n[s]]},inputs:{x:r.x},output:e,outputBuffer:t})};var dg=class{constructor(){d(this,"_modules",{cpu:Jm})}add(e,t){let n=this._modules[e];if(typeof t.then=="function"){let o=Promise.all([Promise.resolve(n||{}),t]).then(([s,a])=>({...s,...a}));return this._modules[e]=o,o.then(s=>{this._modules[e]=s}).catch(s=>{T.error(`Failed to register ${e} backend: ${s}`)()}),o}if(n&&typeof n.then=="function"){let o=Promise.resolve(n).then(s=>({...s,...t})).then(s=>(this._modules[e]=s,s)).catch(s=>{throw T.error(`Failed to register ${e} backend: ${s}`)(),s});return this._modules[e]=o,o}let i={...n||{},...t};return this._modules[e]=i,Promise.resolve(i)}async get(e,t){let n=this._modules[e];if(!n)if(e==="webgl")n=this.add("webgl",Promise.resolve().then(()=>(h1(),d1)));else if(e==="webgpu")n=this.add("webgpu",Promise.resolve().then(()=>(fg(),U1)));else throw new Error(`${e} backend not registered`);let o=(await n)[t];if(typeof o!="function")throw new Error(`${e} backend does not implement ${t}`);return o}getSync(e,t){let n=this._modules[e];if(!n)throw new Error(`${e} backend not registered`);if(typeof n.then=="function")throw new Error(`${e} backend is not loaded yet`);let o=n[t];if(typeof o!="function")throw new Error(`${e} backend does not implement ${t}`);return o}clear(){this._modules={}}},ao=new dg;var nf=class{constructor(e){d(this,"inputs");d(this,"dependencies");this.inputs=e,this.dependencies=Array.from(e instanceof Array?e:Object.values(e)).filter(t=>t instanceof Z)}async execute(e,t){return await this._resolveDependencies(e),await this._executeWithHandler(await ao.get(this._getHandlerRegistry(e),this.name),t)}executeSync(e,t){this._resolveDependenciesSync(e);let n=this._executeWithHandler(ao.getSync(this._getHandlerRegistry(e),this.name),t);if(lD(n))throw new Error(`${this.name} returned a Promise in executeSync()`);return n}shouldExecuteOnCPU(){return this.output.length<=1&&Array.from(this.dependencies).every(e=>!!e.value)}_getHandlerRegistry(e){return this.shouldExecuteOnCPU()?"cpu":e.type}async _resolveDependencies(e){for(let n of this.dependencies)await n.evaluate(e);if(this._getHandlerRegistry(e)==="cpu"||e.type==="null")for(let n of this.dependencies)await n.ensureCPUValue()}_resolveDependenciesSync(e){for(let n of this.dependencies)n.evaluateSync(e);if(this._getHandlerRegistry(e)==="cpu"||e.type==="null")for(let n of this.dependencies)n.ensureCPUValueSync()}_executeWithHandler(e,t){return e({device:t.device,inputs:this.inputs,output:this.output,target:t})}};function lD(r){return typeof r?.then=="function"}function G1(...r){let e=uD(r.map(t=>t.type));return e[0]!=="f"&&r.some(t=>t.normalized)&&(e="float32"),{isConstant:r.every(t=>t.isConstant),type:e,size:r.reduce((t,n)=>Math.max(t,n.size),0),length:r.reduce((t,n)=>Math.max(t,n.length),0)}}function uD(r){let e=0,t=0;for(let n of r){if(n[0]==="f")return"float32";let i=n.endsWith("8")?8:n.endsWith("6")?16:32;n[0]==="u"?e=Math.max(e,i):t=Math.max(t,i)}return e&&!t?`uint${e}`:t&&e<32?`sint${Math.max(t,e*2)}`:"float32"}Er();var hg=class extends nf{constructor(t){super(t);d(this,"name","interleave");d(this,"output");let{isConstant:n,type:i,length:o}=G1(...t);this.output=new Z({isConstant:n,type:i,size:t.reduce((s,a)=>s+a.size,0),length:o,source:this})}toString(){return`_${this.inputs.join("_")}_`}};function pg(...r){if(r.length===0)throw new Error("interleave() requires at least one input");return r.length===1?Yu(r[0]):new hg(r.map(Yu)).output}de();Er();function gg(r,e){let t=dD(e);for(let n of t)n.evaluateSync(r);return fD(t),e}function fD(r){let e=new Set(r.flatMap(pD)),t=new Set;for(let n of r)of(n,t);for(let n of t)n.evaluated&&!e.has(n.buffer)&&n.destroy()}function dD(r){let e=new Set;return mg(r,e,new Set),Array.from(e)}function mg(r,e,t){if(mD(r)){e.add(r);return}if(!(!r||typeof r!="object"||t.has(r))){if(t.add(r),Array.isArray(r)){for(let n of r)mg(n,e,t);return}if(hD(r))for(let n of Object.values(r))mg(n,e,t)}}function hD(r){let e=Object.getPrototypeOf(r);return e===Object.prototype||e===null}function of(r,e){if(r instanceof ga){for(let n of r.gpuDataEvaluators)of(n,e);return}let t=r.source;if(t){if(t instanceof Z){e.has(t)||(e.add(t),of(t,e));return}for(let n of t.dependencies)e.has(n)||(e.add(n),of(n,e))}}function pD(r){return r instanceof Z?[r.buffer]:r.gpuVector.data.map(e=>e.buffer instanceof Ie?e.buffer.buffer:e.buffer)}function mD(r){return r instanceof Z||r instanceof ga}fg();var _a=class{constructor(e,{id:t,isTransitionAttribute:n}){this.packedBuffers={},this.device=e,this.id=t,this.isTransitionAttribute=n,this.device.type==="webgpu"&&ao.add("webgpu",{interleave:rf})}hasGroups(e){return this.device.type==="webgpu"&&Object.values(e).some(t=>!!t.settings.bufferGroup)}finalize(){for(let e of Object.values(this.packedBuffers))e.packed.destroy();this.packedBuffers={}}getBufferLayouts(e,t){let n=this._getPackedGroups(e,t,{requireValues:!1,excludeAttributes:{}});return this._getBufferLayouts(e,n,t)}getBindings(e,t,n,i){let o=this._getPackedGroups(e,n,{requireValues:!0,excludeAttributes:i}),s={},a=new Set;for(let c of o.values()){let l=!this.packedBuffers[c.id]||c.attributes.some(u=>!!t[u.id]);s[c.id]=this._getPackedBuffer(c,l);for(let u of c.attributes)a.add(u.id)}return{bufferLayouts:this._getBufferLayouts(e,o,n).filter(c=>!i[c.name]&&!e[c.name]?.settings.isIndexed),buffers:s,groupedAttributeIds:a}}_getPackedGroups(e,t,{requireValues:n,excludeAttributes:i}){let o=new Map;for(let a of Object.values(e)){let c=a.settings.bufferGroup;if(!c)continue;let l=o.get(c)||[];l.push(a),o.set(c,l)}let s=new Map;for(let[a,c]of o){let l=this._getPackedGroup(a,c,t,n,i);l&&s.set(a,l)}return s}_getPackedGroup(e,t,n,i,o){if(t.length<2)return null;let s=t.map(p=>p.getBufferLayout(n)),a=s[0].stepMode,c=Math.max(1,t[0].numInstances),l=i&&t.every(p=>p.isConstant);for(let p=0;p<t.length;p++){let m=t[p],g=m.getAccessor(),y=g.size*g.bytesPerElement;if(o[m.id]||m.settings.isIndexed||m.settings.noAlloc||m.doublePrecision||this.isTransitionAttribute(m.id)||s[p].stepMode!==a||m.numInstances!==t[0].numInstances||(g.offset||0)!==0||(g.vertexOffset||0)!==0||bt(g)!==y||i&&(m.isConstant?!m.getConstantValue()||m.getConstantValue().byteLength<y:!ArrayBuffer.isView(m.value)||m.value.byteLength<c*y))return null}let u={},f=[],h=0;for(let p=0;p<t.length;p++){let m=t[p];h=z1(h),u[m.id]=h;for(let g of s[p].attributes||[])f.push({...g,byteOffset:h+(g.byteOffset||0)});h+=bt(m.getAccessor())}return h=z1(h),{id:e,attributes:t,byteStride:h,byteOffsets:u,rowCount:c,layout:{name:e,byteStride:l?0:h,stepMode:a,attributes:f}}}_getBufferLayouts(e,t,n){let i=[],o=new Set,s=new Set;for(let a of t.values())for(let c of a.attributes)s.add(c.id);for(let a of Object.values(e)){let c=a.settings.bufferGroup,l=c&&t.get(c);l&&s.has(a.id)?o.has(l.id)||(i.push(l.layout),o.add(l.id)):i.push(a.getBufferLayout(n))}return i}_getPackedBuffer(e,t){let n=JSON.stringify({byteStride:e.layout.byteStride,attributes:e.layout.attributes}),i=this.packedBuffers[e.id];if((!i||i.layoutKey!==n)&&(t=!0),t){i&&(i.packed.destroy(),delete this.packedBuffers[e.id]);let o=this._interleavePackedGroup(e);return this.packedBuffers[e.id]={packed:o,layoutKey:n},o.buffer}if(!i)throw new Error(`Attribute buffer group ${e.id} has no packed buffer`);return i.packed.buffer}_interleavePackedGroup(e){let t=e.attributes.map(i=>this._getInterleaveInput(e,i)),n=pg(...t);return gg(this.device,n),n}_getInterleaveInput(e,t){let n=bt(t.getAccessor()),i=e.byteOffsets[t.id];if(ya(`${e.id}.${t.id} rowByteLength`,n),ya(`${e.id}.${t.id} groupByteOffset`,i),t.isConstant){let c=t.getConstantValue();if(!c)throw new Error(`Attribute group ${e.id} is missing constant value ${t.id}`);return ya(`${e.id}.${t.id} constant byteOffset`,c.byteOffset),new Z({id:t.id,type:"uint32",size:n/4,isConstant:!0,value:new Uint32Array(c.buffer,c.byteOffset,n/Uint32Array.BYTES_PER_ELEMENT)})}let o=t.getBuffer(),s=t.byteOffset,a=t.getAccessor().stride||n;if(ya(`${e.id}.${t.id} byteOffset`,s),ya(`${e.id}.${t.id} stride`,a),!o)throw new Error(`Attribute group ${e.id} cannot interleave missing buffer ${t.id}`);return new Z({id:t.id,type:"uint32",size:n/4,offset:s,stride:a,length:e.rowCount,buffer:o})}};function z1(r){return Math.ceil(r/4)*4}function ya(r,e){if(e%4!==0)throw new Error(`Attribute buffer groups require 32-bit alignment: ${r}=${e}`)}de();qe();function yg(r){let{source:e,target:t,start:n=0,size:i,getData:o}=r,s=r.end||t.length,a=e.length,c=s-n;if(a>c){t.set(e.subarray(0,c),n);return}if(t.set(e,n),!o)return;let l=a;for(;l<c;){let u=o(l,e);for(let f=0;f<i;f++)t[n+l]=u[f]||0,l++}}function $1({source:r,target:e,size:t,getData:n,sourceStartIndices:i,targetStartIndices:o}){if(!i||!o)return yg({source:r,target:e,size:t,getData:n}),e;let s=0,a=0,c=n&&((u,f)=>n(u+a,f)),l=Math.min(i.length,o.length);for(let u=1;u<l;u++){let f=i[u]*t,h=o[u]*t;yg({source:r.subarray(s,f),target:e,start:a,end:h,size:t,getData:c}),s=f,a=h}return a<e.length&&yg({source:[],target:e,start:a,size:t,getData:c}),e}function V1(r){let{device:e,settings:t,value:n}=r,i=new qn(e,t);return i.setData({value:n instanceof Float64Array?new Float64Array(0):new Float32Array(0),normalized:t.normalized}),i}function sf(r){switch(r){case 1:return"float";case 2:return"vec2";case 3:return"vec3";case 4:return"vec4";default:throw new Error(`No defined attribute type for size "${r}"`)}}function af(r){switch(r){case 1:return"float32";case 2:return"float32x2";case 3:return"float32x3";case 4:return"float32x4";default:throw new Error("invalid type size")}}function cf(r){r.push(r.shift())}function W1(r,e){let{settings:t,value:n,size:i}=r,o=r.isDoublePrecisionBuffer?2:1,s=0,{shaderAttributes:a}=r.settings;if(a)for(let c of Object.values(a))s=Math.max(s,c.vertexOffset??0);return(t.noAlloc?n.length:(e+s)*i)*o}function lf({device:r,source:e,target:t}){return(!t||t.byteLength<e.byteLength)&&(t?.destroy(),t=r.createBuffer({byteLength:e.byteLength,usage:e.usage})),t}function uf({device:r,buffer:e,attribute:t,fromLength:n,toLength:i,fromStartIndices:o,getData:s=a=>a}){let a=t.isDoublePrecisionBuffer?2:1,c=t.size*a,l=t.byteOffset,u=t.settings.bytesPerElement<4?l/t.settings.bytesPerElement*4:l,f=t.startIndices,h=o&&f,p=t.isConstant;if(!h&&e&&n>=i)return e;let m=t.value instanceof Float64Array?Float32Array:t.value.constructor,g=p?t.value:new m(t.getBuffer().readSyncWebGL(l,i*m.BYTES_PER_ELEMENT).buffer);if(t.settings.normalized&&!p){let _=s;s=(w,E)=>t.normalizeConstant(_(w,E))}let y=p?(_,w)=>s(g,w):(_,w)=>s(g.subarray(_+l,_+l+c),w),x=e?new Float32Array(e.readSyncWebGL(u,n*4).buffer):new Float32Array(0),v=new Float32Array(i);return $1({source:x,target:v,sourceStartIndices:o,targetStartIndices:f,size:c,getData:y}),(!e||e.byteLength<v.byteLength+u)&&(e?.destroy(),e=r.createBuffer({byteLength:v.byteLength+u,usage:35050})),e.write(v,u),e}var co=class{constructor({device:e,attribute:t,timeline:n}){this.buffers=[],this.currentLength=0,this.device=e,this.transition=new Ct(n),this.attribute=t,this.attributeInTransition=V1(t),this.currentStartIndices=t.startIndices}get inProgress(){return this.transition.inProgress}start(e,t,n=1/0){this.settings=e,this.currentStartIndices=this.attribute.startIndices,this.currentLength=W1(this.attribute,t),this.transition.start({...e,duration:n})}update(){let e=this.transition.update();return e&&this.onUpdate(),e}setBuffer(e){let{stride:t}=this.attributeInTransition.getAccessor();this.attributeInTransition.setData({buffer:e,normalized:this.attribute.settings.normalized,value:this.attributeInTransition.value,stride:t})}cancel(){this.transition.cancel()}delete(){this.cancel();for(let e of this.buffers)e.destroy();this.buffers.length=0}};var ba=class extends co{constructor({device:e,attribute:t,timeline:n}){super({device:e,attribute:t,timeline:n}),this.type="interpolation",this.transform=bD(e,t)}start(e,t){let n=this.currentLength,i=this.currentStartIndices;if(super.start(e,t,e.duration),e.duration<=0){this.transition.cancel();return}let{buffers:o,attribute:s}=this;cf(o),o[0]=uf({device:this.device,buffer:o[0],attribute:s,fromLength:n,toLength:this.currentLength,fromStartIndices:i,getData:e.enter}),o[1]=lf({device:this.device,source:o[0],target:o[1]}),this.setBuffer(o[1]);let{transform:a}=this,c=a.model,l=Math.floor(this.currentLength/s.size);H1(s)&&(l/=2),c.setVertexCount(l),s.isConstant?(c.setAttributes({aFrom:o[0]}),c.setConstantAttributes({aTo:s.value})):c.setAttributes({aFrom:o[0],aTo:s.getBuffer()}),a.transformFeedback.setBuffers({vCurrent:o[1]})}onUpdate(){let{duration:e,easing:t}=this.settings,{time:n}=this.transition,i=n/e;t&&(i=t(i));let{model:o}=this.transform,s={time:i};o.shaderInputs.setProps({interpolation:s}),this.transform.run({discard:!0})}delete(){super.delete(),this.transform.destroy()}},gD=`layout(std140) uniform interpolationUniforms {
  float time;
} interpolation;
`,j1={name:"interpolation",vs:gD,uniformTypes:{time:"f32"}},yD=`#version 300 es
#define SHADER_NAME interpolation-transition-vertex-shader

in ATTRIBUTE_TYPE aFrom;
in ATTRIBUTE_TYPE aTo;
out ATTRIBUTE_TYPE vCurrent;

void main(void) {
  vCurrent = mix(aFrom, aTo, interpolation.time);
  gl_Position = vec4(0.0);
}
`,_D=`#version 300 es
#define SHADER_NAME interpolation-transition-vertex-shader

in ATTRIBUTE_TYPE aFrom;
in ATTRIBUTE_TYPE aFrom64Low;
in ATTRIBUTE_TYPE aTo;
in ATTRIBUTE_TYPE aTo64Low;
out ATTRIBUTE_TYPE vCurrent;
out ATTRIBUTE_TYPE vCurrent64Low;

vec2 mix_fp64(vec2 a, vec2 b, float x) {
  vec2 range = sub_fp64(b, a);
  return sum_fp64(a, mul_fp64(range, vec2(x, 0.0)));
}

void main(void) {
  for (int i=0; i<ATTRIBUTE_SIZE; i++) {
    vec2 value = mix_fp64(vec2(aFrom[i], aFrom64Low[i]), vec2(aTo[i], aTo64Low[i]), interpolation.time);
    vCurrent[i] = value.x;
    vCurrent64Low[i] = value.y;
  }
  gl_Position = vec4(0.0);
}
`;function H1(r){return r.isDoublePrecisionBuffer}function bD(r,e){let t=e.size,n=sf(t),i=af(t),o=e.getBufferLayout();return H1(e)?new Be(r,{vs:_D,bufferLayout:[{name:"aFrom",byteStride:8*t,attributes:[{attribute:"aFrom",format:i,byteOffset:0},{attribute:"aFrom64Low",format:i,byteOffset:4*t}]},{name:"aTo",byteStride:8*t,attributes:[{attribute:"aTo",format:i,byteOffset:0},{attribute:"aTo64Low",format:i,byteOffset:4*t}]}],modules:[Sp,j1],defines:{ATTRIBUTE_TYPE:n,ATTRIBUTE_SIZE:t},moduleSettings:{},varyings:["vCurrent","vCurrent64Low"],bufferMode:35980,disableWarnings:!0}):new Be(r,{vs:yD,bufferLayout:[{name:"aFrom",format:i},{name:"aTo",format:o.attributes[0].format}],modules:[j1],defines:{ATTRIBUTE_TYPE:n},varyings:["vCurrent"],disableWarnings:!0})}de();var xa=class extends co{constructor({device:e,attribute:t,timeline:n}){super({device:e,attribute:t,timeline:n}),this.type="spring",this.texture=PD(e),this.framebuffer=TD(e,this.texture),this.transform=SD(e,t)}start(e,t){let n=this.currentLength,i=this.currentStartIndices;super.start(e,t);let{buffers:o,attribute:s}=this;for(let c=0;c<2;c++)o[c]=uf({device:this.device,buffer:o[c],attribute:s,fromLength:n,toLength:this.currentLength,fromStartIndices:i,getData:e.enter});o[2]=lf({device:this.device,source:o[0],target:o[2]}),this.setBuffer(o[1]);let{model:a}=this.transform;a.setVertexCount(Math.floor(this.currentLength/s.size)),s.isConstant?a.setConstantAttributes({aTo:s.value}):a.setAttributes({aTo:s.getBuffer()})}onUpdate(){let{buffers:e,transform:t,framebuffer:n,transition:i}=this,o=this.settings;t.model.setAttributes({aPrev:e[0],aCur:e[1]}),t.transformFeedback.setBuffers({vNext:e[2]});let s={stiffness:o.stiffness,damping:o.damping};t.model.shaderInputs.setProps({spring:s}),t.run({framebuffer:n,discard:!1,parameters:{viewport:[0,0,1,1]},clearColor:[0,0,0,0]}),cf(e),this.setBuffer(e[1]),this.device.readPixelsToArrayWebGL(n)[0]>0||i.end()}delete(){super.delete(),this.transform.destroy(),this.texture.destroy(),this.framebuffer.destroy()}},xD=`layout(std140) uniform springUniforms {
  float damping;
  float stiffness;
} spring;
`,vD={name:"spring",vs:xD,uniformTypes:{damping:"f32",stiffness:"f32"}},wD=`#version 300 es
#define SHADER_NAME spring-transition-vertex-shader

#define EPSILON 0.00001

in ATTRIBUTE_TYPE aPrev;
in ATTRIBUTE_TYPE aCur;
in ATTRIBUTE_TYPE aTo;
out ATTRIBUTE_TYPE vNext;
out float vIsTransitioningFlag;

ATTRIBUTE_TYPE getNextValue(ATTRIBUTE_TYPE cur, ATTRIBUTE_TYPE prev, ATTRIBUTE_TYPE dest) {
  ATTRIBUTE_TYPE velocity = cur - prev;
  ATTRIBUTE_TYPE delta = dest - cur;
  ATTRIBUTE_TYPE force = delta * spring.stiffness;
  ATTRIBUTE_TYPE resistance = velocity * spring.damping;
  return force - resistance + velocity + cur;
}

void main(void) {
  bool isTransitioning = length(aCur - aPrev) > EPSILON || length(aTo - aCur) > EPSILON;
  vIsTransitioningFlag = isTransitioning ? 1.0 : 0.0;

  vNext = getNextValue(aCur, aPrev, aTo);
  gl_Position = vec4(0, 0, 0, 1);
  gl_PointSize = 100.0;
}
`,ED=`#version 300 es
#define SHADER_NAME spring-transition-is-transitioning-fragment-shader

in float vIsTransitioningFlag;

out vec4 fragColor;

void main(void) {
  if (vIsTransitioningFlag == 0.0) {
    discard;
  }
  fragColor = vec4(1.0);
}`;function SD(r,e){let t=sf(e.size),n=af(e.size);return new Be(r,{vs:wD,fs:ED,bufferLayout:[{name:"aPrev",format:n},{name:"aCur",format:n},{name:"aTo",format:e.getBufferLayout().attributes[0].format}],varyings:["vNext"],modules:[vD],defines:{ATTRIBUTE_TYPE:t},parameters:{depthCompare:"always",blendColorOperation:"max",blendColorSrcFactor:"one",blendColorDstFactor:"one",blendAlphaOperation:"max",blendAlphaSrcFactor:"one",blendAlphaDstFactor:"one"}})}function PD(r){return r.createTexture({data:new Uint8Array(4),format:"rgba8unorm",width:1,height:1})}function TD(r,e){return r.createFramebuffer({id:"spring-transition-is-transitioning-framebuffer",width:1,height:1,colorAttachments:[e]})}var LD={interpolation:ba,spring:xa},va=class{constructor(e,{id:t,timeline:n}){if(!e)throw new Error("AttributeTransitionManager is constructed without device");this.id=t,this.device=e,this.timeline=n,this.transitions={},this.needsRedraw=!1,this.numInstances=1}finalize(){for(let e in this.transitions)this._removeTransition(e)}update({attributes:e,transitions:t,numInstances:n}){this.numInstances=n||1;for(let i in e){let o=e[i],s=o.getTransitionSetting(t);s&&this._updateAttribute(i,o,s)}for(let i in this.transitions){let o=e[i];(!o||!o.getTransitionSetting(t))&&this._removeTransition(i)}}hasAttribute(e){let t=this.transitions[e];return t&&t.inProgress}getAttributes(){let e={};for(let t in this.transitions){let n=this.transitions[t];n.inProgress&&(e[t]=n.attributeInTransition)}return e}run(){if(this.numInstances===0)return!1;for(let t in this.transitions)this.transitions[t].update()&&(this.needsRedraw=!0);let e=this.needsRedraw;return this.needsRedraw=!1,e}_removeTransition(e){this.transitions[e].delete(),delete this.transitions[e]}_updateAttribute(e,t,n){let i=this.transitions[e],o=!i||i.type!==n.type;if(o){i&&this._removeTransition(e);let s=LD[n.type];s?this.transitions[e]=new s({attribute:t,timeline:this.timeline,device:this.device}):($.error(`unsupported transition type '${n.type}'`)(),o=!1)}(o||t.needsRedraw())&&(this.needsRedraw=!0,this.transitions[e].start(n,this.numInstances))}};var Y1="attributeManager.invalidate",AD="attributeManager.updateStart",CD="attributeManager.updateEnd",MD="attribute.updateStart",ID="attribute.allocate",RD="attribute.updateEnd",wa=class{constructor(e,{id:t="attribute-manager",stats:n,timeline:i}={}){this.mergeBoundsMemoized=Yt(zv),this.id=t,this.device=e,this.attributes={},this.updateTriggers={},this.needsRedraw=!0,this.userData={},this.stats=n,this.attributeTransitionManager=new va(e,{id:`${t}-transitions`,timeline:i}),this.attributeBufferGroups=e.type==="webgpu"?new _a(e,{id:t,isTransitionAttribute:o=>this.attributeTransitionManager.hasAttribute(o)}):null,Object.seal(this)}finalize(){this.attributeBufferGroups?.finalize();for(let e in this.attributes)this.attributes[e].delete();this.attributeTransitionManager.finalize()}getNeedsRedraw(e={clearRedrawFlags:!1}){let t=this.needsRedraw;return this.needsRedraw=this.needsRedraw&&!e.clearRedrawFlags,t&&this.id}setNeedsRedraw(){this.needsRedraw=!0}add(e){this._add(e)}addInstanced(e){this._add(e,{stepMode:"instance"})}remove(e){for(let t of e)this.attributes[t]!==void 0&&(this.attributes[t].delete(),delete this.attributes[t])}invalidate(e,t){let n=this._invalidateTrigger(e,t);me(Y1,this,e,n)}invalidateAll(e){for(let t in this.attributes)this.attributes[t].setNeedsUpdate(t,e);me(Y1,this,"all")}update({data:e,numInstances:t,startIndices:n=null,transitions:i,props:o={},buffers:s={},context:a={}}){let c=!1;me(AD,this),this.stats&&this.stats.get("Update Attributes").timeStart();for(let l in this.attributes){let u=this.attributes[l],f=u.settings.accessor;u.startIndices=n,u.numInstances=t,o[l]&&$.removed(`props.${l}`,`data.attributes.${l}`)(),u.setExternalBuffer(s[l])||u.setBinaryValue(typeof f=="string"?s[f]:void 0,e.startIndices)||typeof f=="string"&&!s[f]&&u.setConstantValue(a,o[f])||u.needsUpdate()&&(c=!0,this._updateAttribute({attribute:u,numInstances:t,data:e,props:o,context:a})),this.needsRedraw=this.needsRedraw||u.needsRedraw()}c&&me(CD,this,t),this.stats&&(this.stats.get("Update Attributes").timeEnd(),c&&this.stats.get("Attributes updated").incrementCount()),this.attributeTransitionManager.update({attributes:this.attributes,numInstances:t,transitions:i})}updateTransition(){let{attributeTransitionManager:e}=this,t=e.run();return this.needsRedraw=this.needsRedraw||t,t}getAttributes(){return{...this.attributes,...this.attributeTransitionManager.getAttributes()}}getBounds(e){let t=e.map(n=>this.attributes[n]?.getBounds());return this.mergeBoundsMemoized(t)}getChangedAttributes(e={clearChangedFlags:!1}){let{attributes:t,attributeTransitionManager:n}=this,i={...n.getAttributes()};for(let o in t){let s=t[o];s.needsRedraw(e)&&!n.hasAttribute(o)&&(i[o]=s)}return i}getBufferLayouts(e){return this.hasBufferGroups()?this.attributeBufferGroups.getBufferLayouts(this.getAttributes(),e):Object.values(this.getAttributes()).map(t=>t.getBufferLayout(e))}hasBufferGroups(){return!!this.attributeBufferGroups?.hasGroups(this.attributes)}getBufferGroupBindings(e,t,n={}){return this.attributeBufferGroups?this.attributeBufferGroups.getBindings(this.getAttributes(),e,t,n):{bufferLayouts:this.getBufferLayouts(t),buffers:{},groupedAttributeIds:new Set}}_add(e,t){for(let n in e){let i=e[n],o={...i,id:n,size:i.isIndexed&&1||i.size||1,...t};this.attributes[n]=new qn(this.device,o)}this._mapUpdateTriggersToAttributes()}_mapUpdateTriggersToAttributes(){let e={};for(let t in this.attributes)this.attributes[t].getUpdateTriggers().forEach(i=>{e[i]||(e[i]=[]),e[i].push(t)});this.updateTriggers=e}_invalidateTrigger(e,t){let{attributes:n,updateTriggers:i}=this,o=i[e];return o&&o.forEach(s=>{let a=n[s];a&&a.setNeedsUpdate(a.id,t)}),o}_updateAttribute(e){let{attribute:t,numInstances:n}=e;if(me(MD,t),t.constant){t.setConstantValue(e.context,t.value);return}t.allocate(n)&&me(ID,t,n),t.updateBuffer(e)&&(this.needsRedraw=!0,me(RD,t,n))}};N();Bu();Ee();var Ea=class extends Ct{get value(){return this._value}_onUpdate(){let{time:e,settings:{fromValue:t,toValue:n,duration:i,easing:o}}=this,s=o(e/i);this._value=Tn(t,n,s)}};var q1=1e-5;function X1(r,e,t,n,i){let o=e-r,a=(t-e)*i,c=-o*n;return a+c+o+e}function BD(r,e,t,n,i){if(Array.isArray(t)){let o=[];for(let s=0;s<t.length;s++)o[s]=X1(r[s],e[s],t[s],n,i);return o}return X1(r,e,t,n,i)}function Z1(r,e){if(Array.isArray(r)){let t=0;for(let n=0;n<r.length;n++){let i=r[n]-e[n];t+=i*i}return Math.sqrt(t)}return Math.abs(r-e)}var Sa=class extends Ct{get value(){return this._currValue}_onUpdate(){let{fromValue:e,toValue:t,damping:n,stiffness:i}=this.settings,{_prevValue:o=e,_currValue:s=e}=this,a=BD(o,s,t,n,i),c=Z1(a,t),l=Z1(a,s);c<q1&&l<q1&&(a=t,this.end()),this._prevValue=s,this._currValue=a}};var OD={interpolation:Ea,spring:Sa},Pa=class{constructor(e){this.transitions=new Map,this.timeline=e}get active(){return this.transitions.size>0}add(e,t,n,i){let{transitions:o}=this;if(o.has(e)){let c=o.get(e),{value:l=c.settings.fromValue}=c;t=l,this.remove(e)}if(i=Gu(i),!i)return;let s=OD[i.type];if(!s){$.error(`unsupported transition type '${i.type}'`)();return}let a=new s(this.timeline);a.start({...i,fromValue:t,toValue:n}),o.set(e,a)}remove(e){let{transitions:t}=this;t.has(e)&&(t.get(e).cancel(),t.delete(e))}update(){let e={};for(let[t,n]of this.transitions)n.update(),e[t]=n.value,n.inProgress||this.remove(t);return e}clear(){for(let e of this.transitions.keys())this.remove(e)}};function Q1(r){let e=r[Kt];for(let t in e){let n=e[t],{validate:i}=n;if(i&&!i(r[t],n))throw new Error(`Invalid prop ${t}: ${r[t]}`)}}function J1(r,e){let t=eS({newProps:r,oldProps:e,propTypes:r[Kt],ignoreProps:{data:null,updateTriggers:null,extensions:null,transitions:null}}),n=DD(r,e),i=!1;return n||(i=ND(r,e)),{dataChanged:n,propsChanged:t,updateTriggersChanged:i,extensionsChanged:FD(r,e),transitionsChanged:kD(r,e)}}function kD(r,e){if(!r.transitions)return!1;let t={},n=r[Kt],i=!1;for(let o in r.transitions){let s=n[o],a=s&&s.type;(a==="number"||a==="color"||a==="array")&&_g(r[o],e[o],s)&&(t[o]=!0,i=!0)}return i?t:!1}function eS({newProps:r,oldProps:e,ignoreProps:t={},propTypes:n={},triggerName:i="props"}){if(e===r)return!1;if(typeof r!="object"||r===null)return`${i} changed shallowly`;if(typeof e!="object"||e===null)return`${i} changed shallowly`;for(let o of Object.keys(r))if(!(o in t)){if(!(o in e))return`${i}.${o} added`;let s=_g(r[o],e[o],n[o]);if(s)return`${i}.${o} ${s}`}for(let o of Object.keys(e))if(!(o in t)){if(!(o in r))return`${i}.${o} dropped`;if(!Object.hasOwnProperty.call(r,o)){let s=_g(r[o],e[o],n[o]);if(s)return`${i}.${o} ${s}`}}return!1}function _g(r,e,t){let n=t&&t.equal;return n&&!n(r,e,t)||!n&&(n=r&&e&&r.equals,n&&!n.call(r,e))?"changed deeply":!n&&e!==r?"changed shallowly":null}function DD(r,e){if(e===null)return"oldProps is null, initial diff";let t=!1,{dataComparator:n,_dataDiff:i}=r;return n?n(r.data,e.data)||(t="Data comparator detected a change"):r.data!==e.data&&(t="A new data container was supplied"),t&&i&&(t=i(r.data,e.data)||t),t}function ND(r,e){if(e===null)return{all:!0};if("all"in r.updateTriggers&&K1(r,e,"all"))return{all:!0};let t={},n=!1;for(let i in r.updateTriggers)i!=="all"&&K1(r,e,i)&&(t[i]=!0,n=!0);return n?t:!1}function FD(r,e){if(e===null)return!0;let t=e.extensions,{extensions:n}=r;if(n===t)return!1;if(!t||!n||n.length!==t.length)return!0;for(let i=0;i<n.length;i++)if(!n[i].equals(t[i]))return!0;return!1}function K1(r,e,t){let n=r.updateTriggers[t];n=n??{};let i=e.updateTriggers[t];return i=i??{},eS({oldProps:i,newProps:n,triggerName:t})}var UD="count(): argument not an object",GD="count(): argument not a container";function tS(r){if(!$D(r))throw new Error(UD);if(typeof r.count=="function")return r.count();if(Number.isFinite(r.size))return r.size;if(Number.isFinite(r.length))return r.length;if(zD(r))return Object.keys(r).length;throw new Error(GD)}function zD(r){return r!==null&&typeof r=="object"&&r.constructor===Object}function $D(r){return r!==null&&typeof r=="object"}function bg(r,e){if(!e)return r;let t={...r,...e};if("defines"in e&&(t.defines={...r.defines,...e.defines}),"modules"in e&&(t.modules=(r.modules||[]).concat(e.modules),e.modules.some(n=>n.name==="project64"))){let n=t.modules.findIndex(i=>i.name==="project32");n>=0&&t.modules.splice(n,1)}if("inject"in e)if(!r.inject)t.inject=e.inject;else{let n={...r.inject};for(let i in e.inject)n[i]=(n[i]||"")+e.inject[i];t.inject=n}return t}N();var VD={minFilter:"linear",mipmapFilter:"linear",magFilter:"linear",addressModeU:"clamp-to-edge",addressModeV:"clamp-to-edge"},xg={};function rS(r,e,t,n){if(t instanceof Y)return t;t.constructor&&t.constructor.name!=="Object"&&(t={data:t});let i=null;t.compressed&&(i={minFilter:"linear",mipmapFilter:t.data.length>1?"nearest":"linear"});let{width:o,height:s}=t.data,a=e.createTexture({...t,sampler:{...VD,...i,...n},mipLevels:e.getMipLevelCount(o,s)});return e.type==="webgl"?a.generateMipmapsWebGL():e.type==="webgpu"&&e.generateMipmapsWebGPU(a),xg[a.id]=r,a}function nS(r,e){!e||!(e instanceof Y)||xg[e.id]===r&&(e.delete(),delete xg[e.id])}var WD={boolean:{validate(r,e){return!0},equal(r,e,t){return!!r==!!e}},number:{validate(r,e){return Number.isFinite(r)&&(!("max"in e)||r<=e.max)&&(!("min"in e)||r>=e.min)}},color:{validate(r,e){return e.optional&&!r||vg(r)&&(r.length===3||r.length===4)},equal(r,e,t){return ce(r,e,1)}},accessor:{validate(r,e){let t=ff(r);return t==="function"||t===ff(e.value)},equal(r,e,t){return typeof e=="function"?!0:ce(r,e,1)}},array:{validate(r,e){return e.optional&&!r||vg(r)},equal(r,e,t){let{compare:n}=t,i=Number.isInteger(n)?n:n?1:0;return n?ce(r,e,i):r===e}},object:{equal(r,e,t){if(t.ignore)return!0;let{compare:n}=t,i=Number.isInteger(n)?n:n?1:0;return n?ce(r,e,i):r===e}},function:{validate(r,e){return e.optional&&!r||typeof r=="function"},equal(r,e,t){return!t.compare&&t.ignore!==!1||r===e}},data:{transform:(r,e,t)=>{if(!r)return r;let{dataTransform:n}=t.props;return n?n(r):typeof r.shape=="string"&&r.shape.endsWith("-table")&&Array.isArray(r.data)?r.data:r}},image:{transform:(r,e,t)=>{let n=t.context;return!n||!n.device?null:rS(t.id,n.device,r,{...e.parameters,...t.props.textureParameters})},release:(r,e,t)=>{nS(t.id,r)}}};function iS(r){let e={},t={},n={};for(let[i,o]of Object.entries(r)){let s=o?.deprecatedFor;if(s)n[i]=Array.isArray(s)?s:[s];else{let a=jD(i,o);e[i]=a,t[i]=a.value}}return{propTypes:e,defaultProps:t,deprecatedProps:n}}function jD(r,e){switch(ff(e)){case"object":return Ta(r,e);case"array":return Ta(r,{type:"array",value:e,compare:!1});case"boolean":return Ta(r,{type:"boolean",value:e});case"number":return Ta(r,{type:"number",value:e});case"function":return Ta(r,{type:"function",value:e,compare:!0});default:return{name:r,type:"unknown",value:e}}}function Ta(r,e){return"type"in e?{name:r,...WD[e.type],...e}:"value"in e?{name:r,type:ff(e.value),...e}:{name:r,type:"object",value:e}}function vg(r){return Array.isArray(r)||ArrayBuffer.isView(r)}function ff(r){return vg(r)?"array":r===null?"null":typeof r}function oS(r,e){let t;for(let o=e.length-1;o>=0;o--){let s=e[o];"extensions"in s&&(t=s.extensions)}let n=wg(r.constructor,t),i=Object.create(n);i[Hi]=r,i[Qt]={},i[At]={};for(let o=0;o<e.length;++o){let s=e[o];for(let a in s)i[a]=s[a]}return Object.freeze(i),i}var HD="_mergedDefaultProps";function wg(r,e){if(!(r instanceof df.constructor))return{};let t=HD;if(e)for(let i of e){let o=i.constructor;o&&(t+=`:${o.extensionName||o.name}`)}let n=sS(r,t);return n||(r[t]=YD(r,e||[]))}function YD(r,e){if(!r.prototype)return null;let n=Object.getPrototypeOf(r),i=wg(n),o=sS(r,"defaultProps")||{},s=iS(o),a=Object.assign(Object.create(null),i,s.defaultProps),c=Object.assign(Object.create(null),i?.[Kt],s.propTypes),l=Object.assign(Object.create(null),i?.[Xl],s.deprecatedProps);for(let u of e){let f=wg(u.constructor);f&&(Object.assign(a,f),Object.assign(c,f[Kt]),Object.assign(l,f[Xl]))}return qD(a,r),ZD(a,c),XD(a,l),a[Kt]=c,a[Xl]=l,e.length===0&&!Eg(r,"_propTypes")&&(r._propTypes=c),a}function qD(r,e){let t=QD(e);Object.defineProperties(r,{id:{writable:!0,value:t}})}function XD(r,e){for(let t in e)Object.defineProperty(r,t,{enumerable:!1,set(n){let i=`${this.id}: ${t}`;for(let o of e[t])Eg(this,o)||(this[o]=n);$.deprecated(i,e[t].join("/"))()}})}function ZD(r,e){let t={},n={};for(let i in e){let o=e[i],{name:s,value:a}=o;o.async&&(t[s]=a,n[s]=KD(s))}r[_r]=t,r[Qt]={},Object.defineProperties(r,n)}function KD(r){return{enumerable:!0,set(e){typeof e=="string"||e instanceof Promise||Fu(e)?this[Qt][r]=e:this[At][r]=e},get(){if(this[At]){if(r in this[At])return this[At][r]||this[_r][r];if(r in this[Qt]){let e=this[Hi]&&this[Hi].internalState;if(e&&e.hasAsyncProp(r))return e.getAsyncProp(r)||this[_r][r]}}return this[_r][r]}}}function Eg(r,e){return Object.prototype.hasOwnProperty.call(r,e)}function sS(r,e){return Eg(r,e)&&r[e]}function QD(r){let e=r.componentName;return e||$.warn(`${r.name}.componentName not specified`)(),e||r.name}var JD=0,La=class{constructor(...e){this.props=oS(this,e),this.id=this.props.id,this.count=JD++}clone(e){let{props:t}=this,n={};for(let i in t[_r])i in t[At]?n[i]=t[At][i]:i in t[Qt]&&(n[i]=t[Qt][i]);return new this.constructor({...t,...n,...e})}};La.componentName="Component";La.defaultProps={};var df=La;var eN=Object.freeze({}),Aa=class{constructor(e){this.component=e,this.asyncProps={},this.onAsyncPropUpdated=()=>{},this.oldProps=null,this.oldAsyncProps=null}finalize(){for(let e in this.asyncProps){let t=this.asyncProps[e];t&&t.type&&t.type.release&&t.type.release(t.resolvedValue,t.type,this.component)}this.asyncProps={},this.component=null,this.resetOldProps()}getOldProps(){return this.oldAsyncProps||this.oldProps||eN}resetOldProps(){this.oldAsyncProps=null,this.oldProps=this.component?this.component.props:null}hasAsyncProp(e){return e in this.asyncProps}getAsyncProp(e){let t=this.asyncProps[e];return t&&t.resolvedValue}isAsyncPropLoading(e){if(e){let t=this.asyncProps[e];return!!(t&&t.pendingLoadCount>0&&t.pendingLoadCount!==t.resolvedLoadCount)}for(let t in this.asyncProps)if(this.isAsyncPropLoading(t))return!0;return!1}reloadAsyncProp(e,t){this._watchPromise(e,Promise.resolve(t))}setAsyncProps(e){this.component=e[Hi]||this.component;let t=e[At]||{},n=e[Qt]||e,i=e[_r]||{};for(let o in t){let s=t[o];this._createAsyncPropData(o,i[o]),this._updateAsyncProp(o,s),t[o]=this.getAsyncProp(o)}for(let o in n){let s=n[o];this._createAsyncPropData(o,i[o]),this._updateAsyncProp(o,s)}}_fetch(e,t){return null}_onResolve(e,t){}_onError(e,t){}_updateAsyncProp(e,t){if(this._didAsyncInputValueChange(e,t)){if(typeof t=="string"&&(t=this._fetch(e,t)),t instanceof Promise){this._watchPromise(e,t);return}if(Fu(t)){this._resolveAsyncIterable(e,t);return}this._setPropValue(e,t)}}_freezeAsyncOldProps(){if(!this.oldAsyncProps&&this.oldProps){this.oldAsyncProps=Object.create(this.oldProps);for(let e in this.asyncProps)Object.defineProperty(this.oldAsyncProps,e,{enumerable:!0,value:this.oldProps[e]})}}_didAsyncInputValueChange(e,t){let n=this.asyncProps[e];return t===n.resolvedValue||t===n.lastValue?!1:(n.lastValue=t,!0)}_setPropValue(e,t){this._freezeAsyncOldProps();let n=this.asyncProps[e];n&&(t=this._postProcessValue(n,t),n.resolvedValue=t,n.pendingLoadCount++,n.resolvedLoadCount=n.pendingLoadCount)}_setAsyncPropValue(e,t,n){let i=this.asyncProps[e];i&&n>=i.resolvedLoadCount&&t!==void 0&&(this._freezeAsyncOldProps(),i.resolvedValue=t,i.resolvedLoadCount=n,this.onAsyncPropUpdated(e,t))}_watchPromise(e,t){let n=this.asyncProps[e];if(n){n.pendingLoadCount++;let i=n.pendingLoadCount;t.then(o=>{this.component&&(o=this._postProcessValue(n,o),this._setAsyncPropValue(e,o,i),this._onResolve(e,o))}).catch(o=>{this._onError(e,o)})}}async _resolveAsyncIterable(e,t){if(e!=="data"){this._setPropValue(e,t);return}let n=this.asyncProps[e];if(!n)return;n.pendingLoadCount++;let i=n.pendingLoadCount,o=[],s=0;for await(let a of t){if(!this.component)return;let{dataTransform:c}=this.component.props;c?o=c(a,o):o=o.concat(a),Object.defineProperty(o,"__diff",{enumerable:!1,value:[{startRow:s,endRow:o.length}]}),s=o.length,this._setAsyncPropValue(e,o,i)}this._onResolve(e,o)}_postProcessValue(e,t){let n=e.type;return n&&this.component&&(n.release&&n.release(e.resolvedValue,n,this.component),n.transform)?n.transform(t,n,this.component):t}_createAsyncPropData(e,t){if(!this.asyncProps[e]){let i=this.component&&this.component.props[Kt];this.asyncProps[e]={type:i&&i[e],lastValue:null,resolvedValue:t,pendingLoadCount:0,resolvedLoadCount:0}}}};var Ca=class extends Aa{constructor({attributeManager:e,layer:t}){super(t),this.attributeManager=e,this.needsRedraw=!0,this.needsUpdate=!0,this.subLayers=null,this.usesPickingColorCache=!1,this.disabledPickingIndices=[]}get layer(){return this.component}_fetch(e,t){let n=this.layer,i=n?.props.fetch;return i?i(t,{propName:e,layer:n}):super._fetch(e,t)}_onResolve(e,t){let n=this.layer;if(n){let i=n.props.onDataLoad;e==="data"&&i&&i(t,{propName:e,layer:n})}}_onError(e,t){let n=this.layer;n&&n.raiseError(t,`loading ${e} of ${this.layer}`)}};var tN="layer.changeFlag",rN="layer.initialize",nN="layer.update",iN="layer.finalize",oN="layer.matched",aS=2**24-1,sN=Object.freeze([]),aN=Yt(({oldViewport:r,viewport:e})=>r.equals(e)),xt=new Uint8ClampedArray(0);function cS(r){return r.rowIndexes||r.pickingColors||r.instancePickingColors}function Sg(r){return r.rowIndexes}function Pg(r){return r.pickingColors||r.instancePickingColors}var cN={data:{type:"data",value:sN,async:!0},dataComparator:{type:"function",value:null,optional:!0},_dataDiff:{type:"function",value:r=>r&&r.__diff,optional:!0},dataTransform:{type:"function",value:null,optional:!0},onDataLoad:{type:"function",value:null,optional:!0},onError:{type:"function",value:null,optional:!0},fetch:{type:"function",value:(r,{propName:e,layer:t,loaders:n,loadOptions:i,signal:o})=>{let{resourceManager:s}=t.context;i=i||t.getLoadOptions(),n=n||t.props.loaders,o&&(i={...i,core:{...i?.core,fetch:{...i?.core?.fetch,signal:o}}});let a=s.contains(r);return!a&&!i&&(s.add({resourceId:r,data:ai(r,n),persistent:!1}),a=!0),a?s.subscribe({resourceId:r,onChange:c=>t.internalState?.reloadAsyncProp(e,c),consumerId:t.id,requestId:e}):ai(r,n,i)}},updateTriggers:{},visible:!0,pickable:!1,opacity:{type:"number",min:0,max:1,value:1},operation:"draw",onHover:{type:"function",value:null,optional:!0},onClick:{type:"function",value:null,optional:!0},onDragStart:{type:"function",value:null,optional:!0},onDrag:{type:"function",value:null,optional:!0},onDragEnd:{type:"function",value:null,optional:!0},coordinateSystem:"default",coordinateOrigin:{type:"array",value:[0,0,0],compare:!0},modelMatrix:{type:"array",value:null,compare:!0,optional:!0},wrapLongitude:!1,positionFormat:"XYZ",colorFormat:"RGBA",parameters:{type:"object",value:{},optional:!0,compare:2},loadOptions:{type:"object",value:null,optional:!0,ignore:!0},transitions:null,extensions:[],loaders:{type:"array",value:[],optional:!0,ignore:!0},getPolygonOffset:{type:"function",value:({layerIndex:r})=>[0,-r*100]},highlightedObjectIndex:null,autoHighlight:!1,highlightColor:{type:"accessor",value:[0,0,128,128]}},Ma=class extends df{constructor(){super(...arguments),this.internalState=null,this.lifecycle=jr.NO_STATE,this.parent=null}static get componentName(){return Object.prototype.hasOwnProperty.call(this,"layerName")?this.layerName:""}get root(){let e=this;for(;e.parent;)e=e.parent;return e}toString(){return`${this.constructor.layerName||this.constructor.name}({id: '${this.props.id}'})`}project(e){q(this.internalState);let t=this.internalState.viewport||this.context.viewport,n=Vl(e,{viewport:t,modelMatrix:this.props.modelMatrix,coordinateOrigin:this.props.coordinateOrigin,coordinateSystem:this.props.coordinateSystem}),[i,o,s]=Vr(n,t.pixelProjectionMatrix);return e.length===2?[i,o]:[i,o,s]}unproject(e){return q(this.internalState),(this.internalState.viewport||this.context.viewport).unproject(e)}projectPosition(e,t){q(this.internalState);let n=this.internalState.viewport||this.context.viewport;return Wv(e,{viewport:n,modelMatrix:this.props.modelMatrix,coordinateOrigin:this.props.coordinateOrigin,coordinateSystem:this.props.coordinateSystem,...t})}get isComposite(){return!1}get isDrawable(){return!0}setState(e){this.setChangeFlags({stateChanged:!0}),Object.assign(this.state,e),this.setNeedsRedraw()}setNeedsRedraw(){this.internalState&&(this.internalState.needsRedraw=!0)}setNeedsUpdate(){this.internalState&&(this.context.layerManager.setNeedsUpdate(String(this)),this.internalState.needsUpdate=!0)}get isLoaded(){return this.internalState?!this.internalState.isAsyncPropLoading():!1}get wrapLongitude(){return this.props.wrapLongitude}isPickable(){return this.props.pickable&&this.props.visible}getModels(){let e=this.state;return e&&(e.models||e.model&&[e.model])||[]}setShaderModuleProps(...e){for(let t of this.getModels())t.shaderInputs.setProps(...e)}getAttributeManager(){return this.internalState&&this.internalState.attributeManager}getCurrentLayer(){return this.internalState&&this.internalState.layer}getLoadOptions(){return this.props.loadOptions}use64bitPositions(){let{coordinateSystem:e}=this.props;return e==="default"||e==="lnglat"||e==="cartesian"}onHover(e,t){return this.props.onHover&&this.props.onHover(e,t)||!1}onClick(e,t){return this.props.onClick&&this.props.onClick(e,t)||!1}nullPickingColor(){return[0,0,0]}encodePickingColor(e,t=[]){return t[0]=e+1&255,t[1]=e+1>>8&255,t[2]=e+1>>8>>8&255,t}decodePickingColor(e){q(e instanceof Uint8Array);let[t,n,i]=e;return t+n*256+i*65536-1}getNumInstances(){return Number.isFinite(this.props.numInstances)?this.props.numInstances:this.state&&this.state.numInstances!==void 0?this.state.numInstances:tS(this.props.data)}getStartIndices(){return this.props.startIndices?this.props.startIndices:this.state&&this.state.startIndices?this.state.startIndices:null}getBounds(){return this.getAttributeManager()?.getBounds(["positions","instancePositions"])}getShaders(e){e=bg(e,{disableWarnings:!0,modules:this.context.defaultShaderModules});for(let t of this.props.extensions)e=bg(e,t.getShaders.call(this,t));return e}shouldUpdateState(e){return e.changeFlags.propsOrDataChanged}updateState(e){let t=this.getAttributeManager(),{dataChanged:n}=e.changeFlags;if(n&&t)if(Array.isArray(n))for(let i of n)t.invalidateAll(i);else t.invalidateAll();if(t){let{props:i}=e,o=this.internalState.hasPickingBuffer,s=Number.isInteger(i.highlightedObjectIndex)||!!i.pickable||i.extensions.some(a=>a.getNeedsPickingBuffer.call(this,a));if(o!==s){this.internalState.hasPickingBuffer=s;let a=cS(t.attributes);a&&(s&&a.constant&&(a.constant=!1,t.invalidate(a.id)),!a.value&&!s&&(a.constant=!0,a.value=Sg(t.attributes)?[As]:[0,0,0]))}}}finalizeState(e){for(let n of this.getModels())n.destroy();let t=this.getAttributeManager();t&&t.finalize(),this.context&&this.context.resourceManager.unsubscribe({consumerId:this.id}),this.internalState&&(this.internalState.uniformTransitions.clear(),this.internalState.finalize())}draw(e){for(let t of this.getModels())t.draw(e.renderPass)}getPickingInfo({info:e,mode:t,sourceLayer:n}){let{index:i}=e;return i>=0&&Array.isArray(this.props.data)&&(e.object=this.props.data[i]),e}raiseError(e,t){t&&(e=new Error(`${t}: ${e.message}`,{cause:e})),this.props.onError?.(e)||this.context?.onError?.(e,this)}getNeedsRedraw(e={clearRedrawFlags:!1}){return this._getNeedsRedraw(e)}needsUpdate(){return this.internalState?this.internalState.needsUpdate||this.hasUniformTransition()||this.shouldUpdateState(this._getUpdateParams()):!1}hasUniformTransition(){return this.internalState?.uniformTransitions.active||!1}activateViewport(e){if(!this.internalState)return;let t=this.internalState.viewport;this.internalState.viewport=e,(!t||!aN({oldViewport:t,viewport:e}))&&(this.setChangeFlags({viewportChanged:!0}),this.isComposite?this.needsUpdate()&&this.setNeedsUpdate():this._update())}invalidateAttribute(e="all"){let t=this.getAttributeManager();t&&(e==="all"?t.invalidateAll():t.invalidate(e))}updateAttributes(e){let t=!1;for(let n in e)e[n].layoutChanged()&&(t=!0);for(let n of this.getModels())this._setModelAttributes(n,e,t)}_updateAttributes(){let e=this.getAttributeManager();if(!e)return;let t=this.props,n=this.getNumInstances(),i=this.getStartIndices();e.update({data:t.data,numInstances:n,startIndices:i,props:t,transitions:t.transitions,buffers:t.data.attributes,context:this});let o=e.getChangedAttributes({clearChangedFlags:!0});this.updateAttributes(o)}_updateAttributeTransition(){let e=this.getAttributeManager();e&&e.updateTransition()}_updateUniformTransition(){let{uniformTransitions:e}=this.internalState;if(e.active){let t=e.update(),n=Object.create(this.props);for(let i in t)Object.defineProperty(n,i,{value:t[i]});return n}return this.props}calculateInstancePickingColors(e,{numInstances:t}){if(e.constant)return;let n=Math.floor(xt.length/4);this.internalState.usesPickingColorCache=!0;let i=t>0&&xt[0]===0;if(n<t||i){t>aS&&$.warn("Layer has too many data objects. Picking might not be able to distinguish all objects.")(),xt=Lt.allocate(xt,t,{size:4,copy:!0,maxCount:Math.max(t,aS)});let o=Math.floor(xt.length/4),s=[0,0,0],a=i?0:n;for(let c=a;c<o;c++)this.encodePickingColor(c,s),xt[c*4+0]=s[0],xt[c*4+1]=s[1],xt[c*4+2]=s[2],xt[c*4+3]=0}e.value=xt.subarray(0,t*4)}_setModelAttributes(e,t,n=!1){if(!Object.keys(t).length)return;let i=this.getAttributeManager();if(i?.hasBufferGroups()){this._setGroupedModelAttributes(e,i,t);return}if(n){let c=this.getAttributeManager();e.setBufferLayout(c.getBufferLayouts(e)),t=c.getAttributes()}let o=e.userData?.excludeAttributes||{},s={},a={};for(let c in t){if(o[c])continue;let l=t[c].getValue();for(let u in l){let f=l[u];f instanceof z?t[c].settings.isIndexed?e.setIndexBuffer(f):s[u]=f:f&&(a[u]=f)}}e.setAttributes(s),e.setConstantAttributes(a)}_setGroupedModelAttributes(e,t,n){let i=e.userData?.excludeAttributes||{},o=t.getBufferGroupBindings(n,e,i);e.setBufferLayout(o.bufferLayouts);let s={...o.buffers},a={},c=t.getAttributes();for(let l in c){if(i[l]||o.groupedAttributeIds.has(l))continue;let u=c[l],f=u.getValue();for(let h in f){let p=f[h];p instanceof z?u.settings.isIndexed?e.setIndexBuffer(p):s[h]=p:p&&(a[h]=p)}}e.setAttributes(s),e.setConstantAttributes(a)}disablePickingIndex(e){let t=this.props.data;if(!("attributes"in t)){this._disablePickingIndex(e);return}let n=this.getAttributeManager().attributes,i=Sg(n),o=Pg(n),s=i&&t.attributes&&t.attributes[i.id];if(s&&s.value){let c=s.value;for(let l=0;l<t.length;l++){let u=i.getVertexOffset(l);c[u]===e&&this._disablePickingIndex(l)}return}let a=o&&t.attributes&&t.attributes[o.id];if(a&&a.value){let c=a.value,l=this.encodePickingColor(e);for(let u=0;u<t.length;u++){let f=o.getVertexOffset(u);c[f]===l[0]&&c[f+1]===l[1]&&c[f+2]===l[2]&&this._disablePickingIndex(u)}}else this._disablePickingIndex(e)}_disablePickingIndex(e){let t=this.getAttributeManager().attributes,n=Sg(t);if(n){let a=n.getVertexOffset(e),c=n.getVertexOffset(e+1),l=new Uint32Array(c-a);l.fill(As),n.buffer.write(l,a*l.BYTES_PER_ELEMENT);return}let i=Pg(t);if(!i){this.internalState&&Bv(this.internalState.disabledPickingIndices,e);return}let o=i.getVertexOffset(e),s=i.getVertexOffset(e+1);i.buffer.write(new Uint8Array(s-o),o)}restorePickingColors(){let e=this.getAttributeManager().attributes,t=cS(e);if(!t){this.internalState&&(this.internalState.disabledPickingIndices.length=0);return}let n=Pg(e);this.internalState.usesPickingColorCache&&n&&n.value.buffer!==xt.buffer&&(n.value=xt.subarray(0,n.value.length)),t.updateSubBuffer({startOffset:0})}_initialize(){q(!this.internalState),me(rN,this);let e=this._getAttributeManager();this.internalState=new Ca({attributeManager:e,layer:this}),this._clearChangeFlags(),this.state={},Object.defineProperty(this.state,"attributeManager",{get:()=>($.deprecated("layer.state.attributeManager","layer.getAttributeManager()")(),e)}),this.internalState.uniformTransitions=new Pa(this.context.timeline),this.internalState.onAsyncPropUpdated=this._onAsyncPropUpdated.bind(this),this.internalState.setAsyncProps(this.props),this.initializeState(this.context);for(let t of this.props.extensions)t.initializeState.call(this,this.context,t);this.setChangeFlags({dataChanged:"init",propsChanged:"init",viewportChanged:!0,extensionsChanged:!0}),this._update()}_transferState(e){me(oN,this,this===e);let{state:t,internalState:n}=e;this!==e&&(this.internalState=n,this.state=t,this.internalState.setAsyncProps(this.props),this._diffProps(this.props,this.internalState.getOldProps()))}_update(){let e=this.needsUpdate();if(me(nN,this,e),!e)return;this.context.stats.get("Layer updates").incrementCount();let t=this.props,n=this.context,i=this.internalState,o=n.viewport,s=this._updateUniformTransition();i.propsInTransition=s,n.viewport=i.viewport||o,this.props=s;try{let a=this._getUpdateParams(),c=this.getModels();if(n.device)this.updateState(a);else try{this.updateState(a)}catch{}for(let u of this.props.extensions)u.updateState.call(this,a,u);this.setNeedsRedraw(),this._updateAttributes();let l=this.getModels()[0]!==c[0];this._postUpdate(a,l)}finally{n.viewport=o,this.props=t,this._clearChangeFlags(),i.needsUpdate=!1,i.resetOldProps()}}_finalize(){me(iN,this),this.finalizeState(this.context);for(let e of this.props.extensions)e.finalizeState.call(this,this.context,e)}_drawLayer({renderPass:e,shaderModuleProps:t=null,uniforms:n={},parameters:i={}}){this._updateAttributeTransition();let o=this.props,s=this.context;this.props=this.internalState.propsInTransition||o;try{t&&this.setShaderModuleProps(t);let{getPolygonOffset:a}=this.props,c=a&&a(n)||[0,0];s.device instanceof qr&&s.device.setParametersWebGL({polygonOffset:c});let l=s.device instanceof qr?null:lN(i);if(uN(this.getModels(),e,i,l),s.device instanceof qr)s.device.withParametersWebGL(i,()=>{let u={renderPass:e,shaderModuleProps:t,uniforms:n,parameters:i,context:s};for(let f of this.props.extensions)f.draw.call(this,u,f);this.draw(u)});else{l?.renderPassParameters&&e.setParameters(l.renderPassParameters);let u={renderPass:e,shaderModuleProps:t,uniforms:n,parameters:i,context:s};for(let f of this.props.extensions)f.draw.call(this,u,f);this.draw(u)}}finally{this.props=o}}getChangeFlags(){return this.internalState?.changeFlags}setChangeFlags(e){if(!this.internalState)return;let{changeFlags:t}=this.internalState;for(let i in e)if(e[i]){let o=!1;switch(i){case"dataChanged":let s=e[i],a=t[i];s&&Array.isArray(a)&&(t.dataChanged=Array.isArray(s)?a.concat(s):s,o=!0);default:t[i]||(t[i]=e[i],o=!0)}o&&me(tN,this,i,e)}let n=!!(t.dataChanged||t.updateTriggersChanged||t.propsChanged||t.extensionsChanged);t.propsOrDataChanged=n,t.somethingChanged=n||t.viewportChanged||t.stateChanged}_clearChangeFlags(){this.internalState.changeFlags={dataChanged:!1,propsChanged:!1,updateTriggersChanged:!1,viewportChanged:!1,stateChanged:!1,extensionsChanged:!1,propsOrDataChanged:!1,somethingChanged:!1}}_diffProps(e,t){let n=J1(e,t);if(n.updateTriggersChanged)for(let i in n.updateTriggersChanged)n.updateTriggersChanged[i]&&this.invalidateAttribute(i);if(n.transitionsChanged)for(let i in n.transitionsChanged)this.internalState.uniformTransitions.add(i,t[i],e[i],e.transitions?.[i]);return this.setChangeFlags(n)}validateProps(){Q1(this.props)}updateAutoHighlight(e){this.props.autoHighlight&&!Number.isInteger(this.props.highlightedObjectIndex)&&this._updateAutoHighlight(e)}_updateAutoHighlight(e){let t={highlightedObjectColor:e.picked?e.color:null},{highlightColor:n}=this.props;e.picked&&typeof n=="function"&&(t.highlightColor=n(e)),this.setShaderModuleProps({picking:t}),this.setNeedsRedraw()}_getAttributeManager(){let e=this.context;return new wa(e.device,{id:this.props.id,stats:e.stats,timeline:e.timeline})}_postUpdate(e,t){let{props:n,oldProps:i}=e,o=this.state.model;o?.isInstanced&&o.setInstanceCount(this.getNumInstances());let{autoHighlight:s,highlightedObjectIndex:a,highlightColor:c}=n;if(t||i.autoHighlight!==s||i.highlightedObjectIndex!==a||i.highlightColor!==c){let l={};Array.isArray(c)&&(l.highlightColor=c),(t||i.autoHighlight!==s||a!==i.highlightedObjectIndex)&&(l.highlightedObjectColor=Number.isFinite(a)&&a>=0?this.encodePickingColor(a):null),this.setShaderModuleProps({picking:l})}}_getUpdateParams(){return{props:this.props,oldProps:this.internalState.getOldProps(),context:this.context,changeFlags:this.internalState.changeFlags}}_getNeedsRedraw(e){if(!this.internalState)return!1;let t=!1;t=t||this.internalState.needsRedraw&&this.id;let n=this.getAttributeManager(),i=n?n.getNeedsRedraw(e):!1;if(t=t||i,t)for(let o of this.props.extensions)o.onNeedsRedraw.call(this,o);return this.internalState.needsRedraw=this.internalState.needsRedraw&&!e.clearRedrawFlags,t}_onAsyncPropUpdated(){this._diffProps(this.props,this.internalState.getOldProps()),this.setNeedsUpdate()}};Ma.defaultProps=cN;Ma.layerName="Layer";var Kn=Ma;function lN(r){let{blendConstant:e,...t}=r;return e?{pipelineParameters:t,renderPassParameters:{blendConstant:e}}:{pipelineParameters:t}}function uN(r,e,t,n){for(let i of r)i.device.type==="webgpu"?(fN(i,e),i.setParameters({...i.parameters,...n?.pipelineParameters})):i.setParameters(t)}function fN(r,e){let t=e.props.framebuffer||(e.framebuffer??null);if(!t)return;let n=t.colorAttachments.map(s=>s?.texture?.format??null),i=t.depthStencilAttachment?.texture?.format,o=r;(!dN(o.props.colorAttachmentFormats,n)||o.props.depthStencilAttachmentFormat!==i)&&(o.props.colorAttachmentFormats=n,o.props.depthStencilAttachmentFormat=i,o._setPipelineNeedsUpdate("attachment formats"))}function dN(r,e){if(r===e)return!0;if(!r||!e||r.length!==e.length)return!1;for(let t=0;t<r.length;t++)if(r[t]!==e[t])return!1;return!0}Ee();var hN=new ge().lookAt({eye:[0,0,1]});function pN({width:r,height:e,near:t,far:n,padding:i}){let o=-r/2,s=r/2,a=-e/2,c=e/2;if(i){let{left:l=0,right:u=0,top:f=0,bottom:h=0}=i,p=ie((l+r-u)/2,0,r)-r/2,m=ie((f+e-h)/2,0,e)-e/2;o-=p,s-=p,a+=m,c+=m}return new ge().ortho({left:o,right:s,bottom:a,top:c,near:t,far:n})}var hf=class extends Gi{constructor(e){let{width:t,height:n,near:i=.1,far:o=1e3,zoom:s=0,target:a=[0,0,0],padding:c=null,flipY:l=!0}=e,u=e.zoomX??(Array.isArray(s)?s[0]:s),f=e.zoomY??(Array.isArray(s)?s[1]:s),h=Number.isFinite(e.zoom)?e.zoom:Math.min(u,f),p=Math.pow(2,h),m;if(u!==h||f!==h){let g=Math.pow(2,u),y=Math.pow(2,f);m={unitsPerMeter:[g/p,y/p,1],metersPerUnit:[p/g,p/y,1]}}super({...e,longitude:void 0,position:a,viewMatrix:hN.clone().scale([p,p*(l?-1:1),p]),projectionMatrix:pN({width:t||1,height:n||1,padding:c,near:i,far:o}),zoom:h,distanceScales:m}),this.target=a,this.zoomX=u,this.zoomY=f,this.flipY=l}projectFlat([e,t]){let{unitsPerMeter:n}=this.distanceScales;return[e*n[0],t*n[1]]}unprojectFlat([e,t]){let{metersPerUnit:n}=this.distanceScales;return[e*n[0],t*n[1]]}panByPosition(e,t,n){let i=qt(t,this.pixelUnprojectionMatrix),o=this.projectFlat(e),s=$e.add([],o,$e.negate([],i)),a=$e.add([],this.center,s);return{target:this.unprojectFlat(a)}}};hf.displayName="OrthographicViewport";var lS=hf;Ee();var uS=1;function Tg({zoom:r=0,zoomX:e,zoomY:t}){return e=e??(Array.isArray(r)?r[0]:r),t=t??(Array.isArray(r)?r[1]:r),{zoomX:e,zoomY:t}}function mN(r,e,t,n,i){let o=r[0][e]+t,s=r[1][e]-n,a=(o+s)/2;return{minimum:o,maximum:s,midpoint:a,settledTarget:Number.isFinite(t)&&Number.isFinite(n)&&o<=s?ie(i,o,s):a}}var Lg=class extends jn{constructor(e){let{width:t,height:n,target:i=[0,0,0],zoom:o=0,zoomAxis:s="all",minZoom:a=-1/0,maxZoom:c=1/0,minZoomX:l=a,maxZoomX:u=c,minZoomY:f=a,maxZoomY:h=c,maxBounds:p=null,maxBoundsPadding:m=null,rubberBand:g=!1,startPanPosition:y,startZoomPosition:x,startZoom:v}=e,{[_t]:_}=e,{zoomX:w,zoomY:E}=Tg(e);super({width:t,height:n,target:i,zoom:o,zoomX:w,zoomY:E,zoomAxis:s,minZoomX:l,maxZoomX:u,minZoomY:f,maxZoomY:h,maxBounds:p,maxBoundsPadding:m,rubberBand:g,[_t]:_},{startPanPosition:y,startZoomPosition:x,startZoom:v},e.makeViewport,e.constraintContext)}panStart({pos:e},t){return this._getUpdatedState({startPanPosition:this._unproject(e)},t)}pan({pos:e,startPosition:t},n){let i=this.getState().startPanPosition||t;if(!i)return this;let s=this.makeViewport(this.getViewportProps()).panByPosition(i,e);return this._getUpdatedState(s,n)}panEnd(e){return this._getUpdatedState({startPanPosition:null},e)}rotateStart(){return this}rotate(){return this}rotateEnd(){return this}shortestPathFrom(e){let t=e.getViewportProps();return{...this.getViewportProps()}}zoomStart({pos:e},t){let{zoomX:n,zoomY:i}=this.getViewportProps();return this._getUpdatedState({startZoomPosition:this._unproject(e),startZoom:[n,i]},t)}zoom({pos:e,startPos:t,scale:n},i){let{startZoom:o,startZoomPosition:s}=this.getState();if(!s){let{zoomX:c,zoomY:l}=this.getViewportProps();o=[c,l],s=this._unproject(t||e)}if(!s)return this;let a=this._calculateNewZoom({scale:n,startZoom:o});return this._getUpdatedState({...a,[_t]:{position:s,screenPosition:e}},i)}zoomEnd(e){return this._getUpdatedState({startZoomPosition:null,startZoom:null},e)}zoomIn(e=2,t){return this._getUpdatedState(this._calculateNewZoom({scale:e}),t)}zoomOut(e=2,t){return this._getUpdatedState(this._calculateNewZoom({scale:1/e}),t)}moveLeft(e=50,t){return this._panFromCenter([-e,0],t)}moveRight(e=50,t){return this._panFromCenter([e,0],t)}moveUp(e=50,t){return this._panFromCenter([0,-e],t)}moveDown(e=50,t){return this._panFromCenter([0,e],t)}rotateLeft(e=15){return this}rotateRight(e=15){return this}rotateUp(e=10){return this}rotateDown(e=10){return this}_project(e){return this.makeViewport(this.getViewportProps()).project(e)}_unproject(e){let t=this.makeViewport(this.getViewportProps()),[n,i]=t.unproject(e);return[n,i]}_calculateNewZoom({scale:e,startZoom:t}){let{zoomX:n,zoomY:i,zoomAxis:o}=this.getViewportProps();t===void 0&&(t=[n,i]);let s=Math.log2(e),[a,c]=t;switch(o){case"X":a+=s;break;case"Y":c+=s;break;default:a+=s,c+=s}return{zoomX:a,zoomY:c}}_panFromCenter(e,t){let{target:n}=this.getViewportProps(),i=this._project(n);return this.pan({startPosition:n,pos:[i[0]+e[0],i[1]+e[1]]},t)}_getUpdatedState(e,t){return new this.constructor({makeViewport:this.makeViewport,...this.getViewportProps(),...this.getState(),...e,constraintContext:t})}applyConstraints(e,t){let n=e,i=n[_t];delete n[_t];let o=Tg(e),s=this._constrainZoom(o,e),a=e.rubberBand&&t?.mode==="elastic",{zoomX:c,zoomY:l}=t?.mode==="preserve"?o:a?{zoomX:Yr(o.zoomX,s.zoomX,uS),zoomY:Yr(o.zoomY,s.zoomY,uS)}:s;if(e.zoomX=c,e.zoomY=l,i){let p=this.makeViewport({...e,zoomX:c,zoomY:l});Object.assign(e,p.panByPosition(i.position,i.screenPosition))}e.zoom=Array.isArray(e.zoom)||e.zoomX!==e.zoomY?[e.zoomX,e.zoomY]:e.zoomX;let{maxBounds:u,rubberBand:f,target:h}=e;if(u){let p=Yi(e.width,e.height,e.maxBoundsPadding),m=this.makeViewport(e),g=Kl(m,h,p),y=m.project(h),x=[0,1].map(E=>{let S=h.slice();S[E]+=1;let C=m.project(S)[E]-y[E];return Number.isFinite(C)?C:2**(E===0?c:l)*(E===0?1:-1)}),v=x.map((E,S)=>{let C=S===0?g.left:g.top,A=S===0?g.right:g.bottom,B=Math.abs(E);return E>=0?[C/B,A/B]:[A/B,C/B]}),_=h.slice(),w=[p.width,p.height];for(let[E,[S,C]]of v.entries()){if(w[E]<0)continue;let{minimum:A,maximum:B,midpoint:L,settledTarget:M}=mN(u,E,S,C,h[E]);if(t?.mode!=="preserve"&&f&&(!Number.isFinite(S)||!Number.isFinite(C))){_[E]=L;continue}let I=f?M:ie(h[E],A,B);_[E]=t?.mode==="preserve"?h[E]:a?Yr(h[E],I,(E===0?p.width:p.height)/2/Math.abs(x[E])):I}(_[0]!==h[0]||_[1]!==h[1])&&(e.target=_)}return e}_constrainZoom({zoomX:e,zoomY:t},n){n||(n=this.getViewportProps());let{zoomAxis:i,maxZoomX:o,maxZoomY:s,maxBounds:a}=n,{minZoomX:c,minZoomY:l}=n;if(a!==null&&n.width>0&&n.height>0){let f=Yi(n.width,n.height,n.maxBoundsPadding),h=a[0],p=a[1],m=p[0]-h[0],g=p[1]-h[1];f.width>0&&Number.isFinite(m)&&m>0&&(c=Math.max(c,Math.log2(f.width/m)),c>o&&(c=o)),f.height>0&&Number.isFinite(g)&&g>0&&(l=Math.max(l,Math.log2(f.height/g)),l>s&&(l=s))}switch(i){case"X":e=ie(e,c,o);break;case"Y":t=ie(t,l,s);break;default:let f=Math.min(o-e,s-t,0);f===0&&(f=Math.max(c-e,l-t,0)),f!==0&&(e+=f,t+=f)}return{zoomX:e,zoomY:t}}},Ia=class extends Wn{constructor(){super(...arguments),this.ControllerState=Lg,this.transition={transitionDuration:300,transitionInterpolator:new br(["target","zoomX","zoomY"])},this.dragMode="pan"}setProps(e){Object.assign(e,Tg(e)),super.setProps(e)}_onMultiPanStart(e){return this.multiTouchDrag==="pan"&&super._onMultiPanStart(e)}_onPanRotate(){return!1}};var pf=class extends zn{constructor(e={}){super(e)}getViewportType(){return lS}get ControllerType(){return Ia}};pf.displayName="OrthographicView";var mf=pf;N();var lo=class{constructor(e){this.indexStarts=[0],this.vertexStarts=[0],this.vertexCount=0,this.instanceCount=0;let{attributes:t={}}=e;this.typedArrayManager=Lt,this.attributes={},this._attributeDefs=t,this.opts=e,this.updateGeometry(e)}updateGeometry(e){Object.assign(this.opts,e);let{data:t,buffers:n={},getGeometry:i,geometryBuffer:o,positionFormat:s,dataChanged:a,normalize:c=!0}=this.opts;if(this.data=t,this.getGeometry=i,this.positionSize=o&&o.size||(s==="XY"?2:3),this.buffers=n,this.normalize=c,o&&(q(t.startIndices),this.getGeometry=this.getGeometryFromBuffer(o),c||(n.vertexPositions=o)),this.geometryBuffer=n.vertexPositions,Array.isArray(a))for(let l of a)this._rebuildGeometry(l);else this._rebuildGeometry()}updatePartialGeometry({startRow:e,endRow:t}){this._rebuildGeometry({startRow:e,endRow:t})}getGeometryFromBuffer(e){let t=e.value||e;return ArrayBuffer.isView(t)?Uu(t,{size:this.positionSize,offset:e.offset,stride:e.stride,startIndices:this.data.startIndices}):null}_allocate(e,t){let{attributes:n,buffers:i,_attributeDefs:o,typedArrayManager:s}=this;for(let a in o)if(a in i)s.release(n[a]),n[a]=null;else{let c=o[a];c.copy=t,n[a]=s.allocate(n[a],e,c)}}_forEachGeometry(e,t,n){let{data:i,getGeometry:o}=this,{iterable:s,objectInfo:a}=Nu(i,t,n);for(let c of s){a.index++;let l=o?o(c,a):null;e(l,a.index)}}_rebuildGeometry(e){if(!this.data)return;let{indexStarts:t,vertexStarts:n,instanceCount:i}=this,{data:o,geometryBuffer:s}=this,{startRow:a=0,endRow:c=1/0}=e||{},l={};if(e||(t=[0],n=[0]),this.normalize||!s)this._forEachGeometry((f,h)=>{let p=f&&this.normalizeGeometry(f);l[h]=p,n[h+1]=n[h]+(p?this.getGeometrySize(p):0)},a,c),i=n[n.length-1];else if(n=o.startIndices,i=n[o.length]||0,ArrayBuffer.isView(s))i=i||s.length/this.positionSize;else if(s instanceof z){let f=this.positionSize*4;i=i||s.byteLength/f}else if(s.buffer){let f=s.stride||this.positionSize*4;i=i||s.buffer.byteLength/f}else if(s.value){let f=s.value,h=s.stride/f.BYTES_PER_ELEMENT||this.positionSize;i=i||f.length/h}this._allocate(i,!!e),this.indexStarts=t,this.vertexStarts=n,this.instanceCount=i;let u={};this._forEachGeometry((f,h)=>{let p=l[h]||f;u.vertexStart=n[h],u.indexStart=t[h];let m=h<n.length-1?n[h+1]:i;u.geometrySize=m-n[h],u.geometryIndex=h,this.updateGeometryAttributes(p,u)},a,c),this.vertexCount=t[t.length-1]}};de();var fS=`layout(std140) uniform lineUniforms {
  float widthScale;
  float widthMinPixels;
  float widthMaxPixels;
  float useShortestPath;
  highp int widthUnits;
} line;
`,dS={name:"line",source:"",vs:fS,fs:fS,uniformTypes:{widthScale:"f32",widthMinPixels:"f32",widthMaxPixels:"f32",useShortestPath:"f32",widthUnits:"i32"}};var hS=`// ---------- Helper Structures & Functions ----------

// Placeholder filter functions.
fn deckgl_filter_size(offset: vec3<f32>, geometry: Geometry) -> vec3<f32> {
  return offset;
}
fn deckgl_filter_gl_position(p: vec4<f32>, geometry: Geometry) -> vec4<f32> {
  if (picking.isAttribute > 0.5) {
    // For depth picking, write normalized depth into the picking payload.
    // This mirrors the legacy DECKGL_FILTER_GL_POSITION hook on WebGL.
  }
  return p;
}

// Compute an extrusion offset given a line direction (in clipspace),
// an offset direction (-1 or 1), and a width in pixels.
// Assumes a uniform "project" with a viewportSize field is available.
fn getExtrusionOffset(line_clipspace: vec2<f32>, offset_direction: f32, width: f32) -> vec2<f32> {
  // project.viewportSize should be provided as a uniform (not shown here)
  let dir_screenspace = normalize(line_clipspace * project.viewportSize);
  // Rotate by 90\xB0: (x,y) becomes (-y,x)
  let rotated = vec2<f32>(-dir_screenspace.y, dir_screenspace.x);
  return rotated * offset_direction * width / 2.0;
}

// Splits the line between two points at a given x coordinate.
// Interpolates the y and z components.
fn splitLine(a: vec3<f32>, b: vec3<f32>, x: f32) -> vec3<f32> {
  let t: f32 = (x - a.x) / (b.x - a.x);
  return vec3<f32>(x, a.yz + t * (b.yz - a.yz));
}

// ---------- Uniforms & Global Structures ----------

struct LineUniforms {
  widthScale: f32,
  widthMinPixels: f32,
  widthMaxPixels: f32,
  useShortestPath: f32,
  widthUnits: i32,
};

@group(0) @binding(0)
var<uniform> line: LineUniforms;



// ---------- Vertex Output Structure ----------

struct Varyings {
  @builtin(position) gl_Position: vec4<f32>,
  @location(0) vColor: vec4<f32>,
  @location(1) uv: vec2<f32>,
  @location(2) pickingColor: vec3<f32>,
};

// ---------- Vertex Shader Entry Point ----------

@vertex
fn vertexMain(
  @builtin(instance_index) instanceIndex: u32,
  @location(0) positions: vec3<f32>,
  @location(1) instanceSourcePositions: vec3<f32>,
  @location(2) instanceTargetPositions: vec3<f32>,
  @location(3) instanceSourcePositions64Low: vec3<f32>,
  @location(4) instanceTargetPositions64Low: vec3<f32>,
  @location(5) instanceColors: vec4<f32>,
  @location(6) instanceWidths: f32
) -> Varyings {
  geometry.worldPosition = instanceSourcePositions;
  geometry.worldPositionAlt = instanceTargetPositions;

  var source_world: vec3<f32> = instanceSourcePositions;
  var target_world: vec3<f32> = instanceTargetPositions;
  var source_world_64low: vec3<f32> = instanceSourcePositions64Low;
  var target_world_64low: vec3<f32> = instanceTargetPositions64Low;

  // Apply shortest-path adjustments if needed.
  if (line.useShortestPath > 0.5 || line.useShortestPath < -0.5) {
    source_world.x = (source_world.x + 180.0 % 360.0) - 180.0;
    target_world.x = (target_world.x + 180.0 % 360.0) - 180.0;
    let deltaLng: f32 = target_world.x - source_world.x;

    if (deltaLng * line.useShortestPath > 180.0) {
      source_world.x = source_world.x + 360.0 * line.useShortestPath;
      source_world = splitLine(source_world, target_world, 180.0 * line.useShortestPath);
      source_world_64low = vec3<f32>(0.0, 0.0, 0.0);
    } else if (deltaLng * line.useShortestPath < -180.0) {
      target_world.x = target_world.x + 360.0 * line.useShortestPath;
      target_world = splitLine(source_world, target_world, 180.0 * line.useShortestPath);
      target_world_64low = vec3<f32>(0.0, 0.0, 0.0);
    } else if (line.useShortestPath < 0.0) {
      var abortOut: Varyings;
      abortOut.gl_Position = vec4<f32>(0.0);
      abortOut.vColor = vec4<f32>(0.0);
      abortOut.uv = vec2<f32>(0.0);
      return abortOut;
    }
  }

  // Project Pos and target positions to clip space.
  let sourceResult = project_position_to_clipspace_and_commonspace(source_world, source_world_64low, vec3<f32>(0.0));
  let targetResult = project_position_to_clipspace_and_commonspace(target_world, target_world_64low, vec3<f32>(0.0));
  let sourcePos: vec4<f32> = sourceResult.clipPosition;
  let targetPos: vec4<f32> = targetResult.clipPosition;
  let source_commonspace: vec4<f32> = sourceResult.commonPosition;
  let target_commonspace: vec4<f32> = targetResult.commonPosition;

  // Interpolate along the line segment.
  let segmentIndex: f32 = positions.x;
  let p: vec4<f32> = sourcePos + segmentIndex * (targetPos - sourcePos);
  geometry.position = source_commonspace + segmentIndex * (target_commonspace - source_commonspace);
#ifdef ANTIALIASING
  var uv: vec2<f32> = positions.xy;
#else
  let uv: vec2<f32> = positions.xy;
#endif
  geometry.uv = uv;
  geometry.pickingColor = picking_getPickingColorFromIndex(instanceIndex);

  // Determine width in pixels.
  let widthPixels: f32 = clamp(
    project_unit_size_to_pixel(instanceWidths * line.widthScale, line.widthUnits),
    line.widthMinPixels, line.widthMaxPixels
  );

  // Compute extrusion offset.
  let extrusion: vec2<f32> = getExtrusionOffset(targetPos.xy - sourcePos.xy, positions.y, widthPixels);
  let offset: vec3<f32> = vec3<f32>(extrusion, 0.0);

  // Apply deck.gl filter functions.
#ifdef ANTIALIASING
  var filteredOffset = deckgl_filter_size(offset, geometry);
  let halfWidthPixels = length(filteredOffset.xy);
  if (halfWidthPixels > 0.0) {
    // Keep the declared edge at abs(uv.y) == 1 while rasterizing the outer half of the centered
    // one-device-pixel coverage ramp.
    let coverageScale = 1.0 + 0.5 / project.devicePixelRatio / halfWidthPixels;
    filteredOffset *= coverageScale;
    uv.y *= coverageScale;
  }
  geometry.uv = uv;
#else
  let filteredOffset = deckgl_filter_size(offset, geometry);
#endif
  let filteredP = deckgl_filter_gl_position(p, geometry);

  let clipOffset: vec2<f32> = project_pixel_size_to_clipspace(filteredOffset.xy);
  let finalPosition: vec4<f32> = filteredP + vec4<f32>(clipOffset, 0.0, 0.0);

  // Compute color.
  var vColor: vec4<f32> = vec4<f32>(instanceColors.rgb, instanceColors.a * layer.opacity);
  // vColor = deckgl_filter_color(vColor, geometry);

  var output: Varyings;
  output.gl_Position = finalPosition;
  output.vColor = vColor;
  output.uv = uv;
  output.pickingColor = geometry.pickingColor;
  return output;
}

@fragment
fn fragmentMain(
  @location(0) vColor: vec4<f32>,
  @location(1) uv: vec2<f32>,
  @location(2) pickingColor: vec3<f32>
) -> @location(0) vec4<f32> {
  // Create and initialize geometry with the provided uv.
  var geometry: Geometry;
  geometry.uv = uv;

  // Start with the input color.
  var fragColor: vec4<f32> = vColor;

#ifdef ANTIALIASING
  // Distance to the edge in device pixels, from the derivative of uv.y. Taken in uniform control
  // flow, ahead of the picking discard below
  let edgeCoord = abs(uv.y);
  let edgePixels = (1.0 - edgeCoord) / max(fwidth(edgeCoord), 1e-6);

  // Fragments outside the coverage ramp must not write depth or picking colors.
  if (edgePixels <= -SMOOTH_EDGE_RADIUS) {
    discard;
  }

  // Feather one device pixel across the width, before premultiplication below. The ends are left
  // hard - they abut neighbors
  fragColor.a *= smoothedge(0.0, edgePixels);
#endif

  if (picking.isActive > 0.5) {
    if (!picking_isColorValid(pickingColor)) {
      discard;
    }
    return vec4<f32>(pickingColor, 1.0);
  }

  if (picking.isHighlightActive > 0.5) {
    let highlightedObjectColor = picking_normalizeColor(picking.highlightedObjectColor);
    if (picking_isColorZero(abs(pickingColor - highlightedObjectColor))) {
      let highLightAlpha = picking.highlightColor.a;
      let blendedAlpha = highLightAlpha + fragColor.a * (1.0 - highLightAlpha);
      if (blendedAlpha > 0.0) {
        let highLightRatio = highLightAlpha / blendedAlpha;
        fragColor = vec4<f32>(
          mix(fragColor.rgb, picking.highlightColor.rgb, highLightRatio),
          blendedAlpha
        );
      } else {
        fragColor = vec4<f32>(fragColor.rgb, 0.0);
      }
    }
  }

  // Apply premultiplied alpha as required by transparent canvas
  fragColor = deckgl_premultiplied_alpha(fragColor);

  return fragColor;
}
`;var pS=`#version 300 es
#define SHADER_NAME line-layer-vertex-shader
in vec3 positions;
in vec3 instanceSourcePositions;
in vec3 instanceTargetPositions;
in vec3 instanceSourcePositions64Low;
in vec3 instanceTargetPositions64Low;
in vec4 instanceColors;
in float instanceWidths;
out vec4 vColor;
out vec2 uv;
vec2 getExtrusionOffset(vec2 line_clipspace, float offset_direction, float width) {
vec2 dir_screenspace = normalize(line_clipspace * project.viewportSize);
dir_screenspace = vec2(-dir_screenspace.y, dir_screenspace.x);
return dir_screenspace * offset_direction * width / 2.0;
}
vec3 splitLine(vec3 a, vec3 b, float x) {
float t = (x - a.x) / (b.x - a.x);
return vec3(x, mix(a.yz, b.yz, t));
}
void main(void) {
geometry.worldPosition = instanceSourcePositions;
geometry.worldPositionAlt = instanceTargetPositions;
vec3 source_world = instanceSourcePositions;
vec3 target_world = instanceTargetPositions;
vec3 source_world_64low = instanceSourcePositions64Low;
vec3 target_world_64low = instanceTargetPositions64Low;
if (line.useShortestPath > 0.5 || line.useShortestPath < -0.5) {
source_world.x = mod(source_world.x + 180., 360.0) - 180.;
target_world.x = mod(target_world.x + 180., 360.0) - 180.;
float deltaLng = target_world.x - source_world.x;
if (deltaLng * line.useShortestPath > 180.) {
source_world.x += 360. * line.useShortestPath;
source_world = splitLine(source_world, target_world, 180. * line.useShortestPath);
source_world_64low = vec3(0.0);
} else if (deltaLng * line.useShortestPath < -180.) {
target_world.x += 360. * line.useShortestPath;
target_world = splitLine(source_world, target_world, 180. * line.useShortestPath);
target_world_64low = vec3(0.0);
} else if (line.useShortestPath < 0.) {
gl_Position = vec4(0.);
return;
}
}
vec4 source_commonspace;
vec4 target_commonspace;
vec4 source = project_position_to_clipspace(source_world, source_world_64low, vec3(0.), source_commonspace);
vec4 target = project_position_to_clipspace(target_world, target_world_64low, vec3(0.), target_commonspace);
float segmentIndex = positions.x;
vec4 p = mix(source, target, segmentIndex);
geometry.position = mix(source_commonspace, target_commonspace, segmentIndex);
uv = positions.xy;
geometry.uv = uv;
geometry.pickingColor = picking_getPickingColorFromInstanceID();
float widthPixels = clamp(
project_size_to_pixel(instanceWidths * line.widthScale, line.widthUnits),
line.widthMinPixels, line.widthMaxPixels
);
vec3 offset = vec3(
getExtrusionOffset(target.xy - source.xy, positions.y, widthPixels),
0.0);
DECKGL_FILTER_SIZE(offset, geometry);
#ifdef ANTIALIASING
float halfWidthPixels = length(offset.xy);
if (halfWidthPixels > 0.0) {
float coverageScale = 1.0 + 0.5 / project.devicePixelRatio / halfWidthPixels;
offset.xy *= coverageScale;
uv.y *= coverageScale;
}
geometry.uv = uv;
#endif
DECKGL_FILTER_GL_POSITION(p, geometry);
gl_Position = p + vec4(project_pixel_size_to_clipspace(offset.xy), 0.0, 0.0);
vColor = vec4(instanceColors.rgb, instanceColors.a * layer.opacity);
DECKGL_FILTER_COLOR(vColor, geometry);
}
`;var mS=`#version 300 es
#define SHADER_NAME line-layer-fragment-shader
precision highp float;
in vec4 vColor;
in vec2 uv;
out vec4 fragColor;
void main(void) {
geometry.uv = uv;
fragColor = vColor;
#ifdef ANTIALIASING
float edgeCoord = abs(uv.y);
float edgePixels = (1.0 - edgeCoord) / max(fwidth(edgeCoord), 1e-6);
if (edgePixels <= -SMOOTH_EDGE_RADIUS) {
discard;
}
fragColor.a *= smoothedge(0.0, edgePixels);
#endif
DECKGL_FILTER_COLOR(fragColor, geometry);
}
`;var gN=[0,0,0,255],yN={getSourcePosition:{type:"accessor",value:r=>r.sourcePosition},getTargetPosition:{type:"accessor",value:r=>r.targetPosition},getColor:{type:"accessor",value:gN},getWidth:{type:"accessor",value:1},widthUnits:"pixels",widthScale:{type:"number",value:1,min:0},widthMinPixels:{type:"number",value:0,min:0},widthMaxPixels:{type:"number",value:Number.MAX_SAFE_INTEGER,min:0},antialiasing:!1},Ra=class extends Kn{getBounds(){return this.getAttributeManager()?.getBounds(["instanceSourcePositions","instanceTargetPositions"])}getShaders(){let{antialiasing:e}=this.props;return super.getShaders({vs:pS,fs:mS,source:hS,defines:e?{ANTIALIASING:1}:{},modules:[zr,Ur,Wr,dS]})}get wrapLongitude(){return!1}initializeState(){this.getAttributeManager().addInstanced({instanceSourcePositions:{size:3,type:"float64",fp64:this.use64bitPositions(),transition:!0,accessor:"getSourcePosition"},instanceTargetPositions:{size:3,type:"float64",fp64:this.use64bitPositions(),transition:!0,accessor:"getTargetPosition"},instanceColors:{size:this.props.colorFormat.length,type:"unorm8",transition:!0,accessor:"getColor",defaultValue:[0,0,0,255]},instanceWidths:{size:1,transition:!0,accessor:"getWidth",defaultValue:1}})}updateState(e){super.updateState(e);let{props:t,oldProps:n,changeFlags:i}=e;(i.extensionsChanged||t.antialiasing!==n.antialiasing)&&(this.state.model?.destroy(),this.state.model=this._getModel(),this.getAttributeManager().invalidateAll())}draw({uniforms:e}){let{widthUnits:t,widthScale:n,widthMinPixels:i,widthMaxPixels:o,wrapLongitude:s}=this.props,a=this.state.model,c={widthUnits:pt[t],widthScale:n,widthMinPixels:i,widthMaxPixels:o,useShortestPath:s?1:0};a.shaderInputs.setProps({line:c}),a.draw(this.context.renderPass),s&&(a.shaderInputs.setProps({line:{...c,useShortestPath:-1}}),a.draw(this.context.renderPass))}_getModel(){let e=[0,-1,0,0,1,0,1,-1,0,1,1,0];return new Re(this.context.device,{...this.getShaders(),id:this.props.id,bufferLayout:this.getAttributeManager().getBufferLayouts(),geometry:new yt({topology:"triangle-strip",attributes:{positions:{size:3,value:new Float32Array(e)}}}),isInstanced:!0})}};Ra.layerName="LineLayer";Ra.defaultProps=yN;var Ag=Ra;de();var gS=`layout(std140) uniform scatterplotUniforms {
  float radiusScale;
  float radiusMinPixels;
  float radiusMaxPixels;
  float lineWidthScale;
  float lineWidthMinPixels;
  float lineWidthMaxPixels;
  float stroked;
  float filled;
  bool antialiasing;
  bool billboard;
  highp int radiusUnits;
  highp int lineWidthUnits;
} scatterplot;
`,yS={name:"scatterplot",vs:gS,fs:gS,source:"",uniformTypes:{radiusScale:"f32",radiusMinPixels:"f32",radiusMaxPixels:"f32",lineWidthScale:"f32",lineWidthMinPixels:"f32",lineWidthMaxPixels:"f32",stroked:"f32",filled:"f32",antialiasing:"f32",billboard:"f32",radiusUnits:"i32",lineWidthUnits:"i32"}};var _S=`#version 300 es
#define SHADER_NAME scatterplot-layer-vertex-shader
in vec3 positions;
in vec3 instancePositions;
in vec3 instancePositions64Low;
in float instanceRadius;
in float instanceLineWidths;
in vec4 instanceFillColors;
in vec4 instanceLineColors;
#ifdef USE_ROW_INDEXES
in float rowIndexes;
#endif
in vec2 instancePixelOffset;
out vec4 vFillColor;
out vec4 vLineColor;
out vec2 unitPosition;
out float innerUnitRadius;
out float outerRadiusPixels;
void main(void) {
geometry.worldPosition = instancePositions;
outerRadiusPixels = clamp(
project_size_to_pixel(scatterplot.radiusScale * instanceRadius, scatterplot.radiusUnits),
scatterplot.radiusMinPixels, scatterplot.radiusMaxPixels
);
float lineWidthPixels = clamp(
project_size_to_pixel(scatterplot.lineWidthScale * instanceLineWidths, scatterplot.lineWidthUnits),
scatterplot.lineWidthMinPixels, scatterplot.lineWidthMaxPixels
);
outerRadiusPixels += scatterplot.stroked * lineWidthPixels / 2.0;
float edgePadding = scatterplot.antialiasing ? (outerRadiusPixels + SMOOTH_EDGE_RADIUS) / outerRadiusPixels : 1.0;
unitPosition = edgePadding * positions.xy;
geometry.uv = unitPosition;
#ifdef USE_ROW_INDEXES
geometry.pickingColor = picking_getPickingColorFromIndex(rowIndexes);
#else
geometry.pickingColor = picking_getPickingColorFromInstanceID();
#endif
innerUnitRadius = 1.0 - scatterplot.stroked * lineWidthPixels / outerRadiusPixels;
if (scatterplot.billboard) {
gl_Position = project_position_to_clipspace(instancePositions, instancePositions64Low, vec3(0.0), geometry.position);
DECKGL_FILTER_GL_POSITION(gl_Position, geometry);
vec3 offset = edgePadding * positions * outerRadiusPixels;
offset.xy += instancePixelOffset;
DECKGL_FILTER_SIZE(offset, geometry);
gl_Position.xy += project_pixel_size_to_clipspace(offset.xy);
} else {
vec3 offset = edgePadding * positions * project_pixel_size(outerRadiusPixels);
offset.xy += project_pixel_size(instancePixelOffset);
DECKGL_FILTER_SIZE(offset, geometry);
gl_Position = project_position_to_clipspace(instancePositions, instancePositions64Low, offset, geometry.position);
DECKGL_FILTER_GL_POSITION(gl_Position, geometry);
}
vFillColor = vec4(instanceFillColors.rgb, instanceFillColors.a * layer.opacity);
DECKGL_FILTER_COLOR(vFillColor, geometry);
vLineColor = vec4(instanceLineColors.rgb, instanceLineColors.a * layer.opacity);
DECKGL_FILTER_COLOR(vLineColor, geometry);
}
`;var bS=`#version 300 es
#define SHADER_NAME scatterplot-layer-fragment-shader
precision highp float;
in vec4 vFillColor;
in vec4 vLineColor;
in vec2 unitPosition;
in float innerUnitRadius;
in float outerRadiusPixels;
out vec4 fragColor;
void main(void) {
geometry.uv = unitPosition;
float distToCenter = length(unitPosition) * outerRadiusPixels;
float inCircle = scatterplot.antialiasing ?
smoothedge(distToCenter, outerRadiusPixels) :
step(distToCenter, outerRadiusPixels);
if (inCircle == 0.0) {
discard;
}
if (scatterplot.stroked > 0.5) {
float isLine = scatterplot.antialiasing ?
smoothedge(innerUnitRadius * outerRadiusPixels, distToCenter) :
step(innerUnitRadius * outerRadiusPixels, distToCenter);
if (scatterplot.filled > 0.5) {
fragColor = mix(vFillColor, vLineColor, isLine);
} else {
if (isLine == 0.0) {
discard;
}
fragColor = vec4(vLineColor.rgb, vLineColor.a * isLine);
}
} else if (scatterplot.filled < 0.5) {
discard;
} else {
fragColor = vFillColor;
}
fragColor.a *= inCircle;
DECKGL_FILTER_COLOR(fragColor, geometry);
}
`;var _N=`// Main shaders

struct ScatterplotUniforms {
  radiusScale: f32,
  radiusMinPixels: f32,
  radiusMaxPixels: f32,
  lineWidthScale: f32,
  lineWidthMinPixels: f32,
  lineWidthMaxPixels: f32,
  stroked: f32,
  filled: i32,
  antialiasing: i32,
  billboard: i32,
  radiusUnits: i32,
  lineWidthUnits: i32,
};

@group(0) @binding(0) var<uniform> scatterplot: ScatterplotUniforms;

struct Attributes {
  @builtin(instance_index) instanceIndex : u32,
  @builtin(vertex_index) vertexIndex : u32,
  @location(0) positions: vec3<f32>,
  @location(1) instancePositions: vec3<f32>,
  @location(2) instancePositions64Low: vec3<f32>,
  @location(3) instanceRadius: f32,
  @location(4) instanceLineWidths: f32,
  @location(5) instanceFillColors: vec4<f32>,
  @location(6) instanceLineColors: vec4<f32>,
  @location(7) instancePixelOffset: vec2<f32>,
  PICKING_COLOR_ATTRIBUTE
};

struct Varyings {
  @builtin(position) position: vec4<f32>,
  @location(0) vFillColor: vec4<f32>,
  @location(1) vLineColor: vec4<f32>,
  @location(2) unitPosition: vec2<f32>,
  @location(3) innerUnitRadius: f32,
  @location(4) outerRadiusPixels: f32,
  @location(5) pickingColor: vec3<f32>,
  @location(6) clipCoordinates: vec2<f32>,
};

@vertex
fn vertexMain(attributes: Attributes) -> Varyings {
  var varyings: Varyings;

  // Draw an inline geometry constant array clip space triangle to verify that rendering works.
  // var positions = array<vec2<f32>, 3>(vec2(0.0, 0.5), vec2(-0.5, -0.5), vec2(0.5, -0.5));
  // if (attributes.instanceIndex == 0) {
  //   varyings.position = vec4<f32>(positions[attributes.vertexIndex], 0.0, 1.0);
  //   return varyings;
  // }

  geometry.worldPosition = attributes.instancePositions;

  // Multiply out radius and clamp to limits
  varyings.outerRadiusPixels = clamp(
    project_unit_size_to_pixel(scatterplot.radiusScale * attributes.instanceRadius, scatterplot.radiusUnits),
    scatterplot.radiusMinPixels, scatterplot.radiusMaxPixels
  );

  // Multiply out line width and clamp to limits
  let lineWidthPixels = clamp(
    project_unit_size_to_pixel(scatterplot.lineWidthScale * attributes.instanceLineWidths, scatterplot.lineWidthUnits),
    scatterplot.lineWidthMinPixels, scatterplot.lineWidthMaxPixels
  );

  // outer radius needs to offset by half stroke width
  varyings.outerRadiusPixels += scatterplot.stroked * lineWidthPixels / 2.0;
  // Expand geometry to accommodate edge smoothing
  // WGSL selects the second value when the condition is true, so keep the antialiased path second.
  let edgePadding = select(
    1.0,
    (varyings.outerRadiusPixels + SMOOTH_EDGE_RADIUS) / varyings.outerRadiusPixels,
    scatterplot.antialiasing != 0
  );

  // position on the containing square in [-1, 1] space
  varyings.unitPosition = edgePadding * attributes.positions.xy;
  geometry.uv = varyings.unitPosition;
  geometry.pickingColor = PICKING_COLOR_VALUE;

  varyings.innerUnitRadius = 1.0 - scatterplot.stroked * lineWidthPixels / varyings.outerRadiusPixels;

  if (scatterplot.billboard != 0) {
    let projectedPosition = project_position_to_clipspace_and_commonspace(
      attributes.instancePositions,
      attributes.instancePositions64Low,
      vec3<f32>(0.0)
    );
    geometry.position = projectedPosition.commonPosition;
    varyings.position = projectedPosition.clipPosition;
    // DECKGL_FILTER_GL_POSITION(varyings.position, geometry);
    var offset = edgePadding * attributes.positions * varyings.outerRadiusPixels;
    offset = vec3<f32>(offset.xy + attributes.instancePixelOffset, offset.z);
    // DECKGL_FILTER_SIZE(offset, geometry);
    let clipPixels = project_pixel_size_to_clipspace(offset.xy);
    varyings.position = vec4<f32>(varyings.position.x + clipPixels.x, varyings.position.y + clipPixels.y, varyings.position.z, varyings.position.w);
    geometry.position = vec4<f32>(
      geometry.position.xy + project_pixel_size_vec2(offset.xy),
      geometry.position.zw
    );
  } else {
    var offset = edgePadding * attributes.positions * project_pixel_size_float(varyings.outerRadiusPixels);
    offset = vec3<f32>(offset.xy + project_pixel_size_vec2(attributes.instancePixelOffset), offset.z);
    // DECKGL_FILTER_SIZE(offset, geometry);
    let projectedPosition = project_position_to_clipspace_and_commonspace(
      attributes.instancePositions,
      attributes.instancePositions64Low,
      offset
    );
    geometry.position = projectedPosition.commonPosition;
    varyings.position = projectedPosition.clipPosition;
    // DECKGL_FILTER_GL_POSITION(varyings.position, geometry);
  }

  varyings.clipCoordinates = geometry.position.xy;
  clip_filterPosition(&varyings.position, geometry.worldPosition.xy);

  // Apply opacity to instance color, or return instance picking color
  varyings.vFillColor = vec4<f32>(attributes.instanceFillColors.rgb, attributes.instanceFillColors.a * layer.opacity);
  // DECKGL_FILTER_COLOR(varyings.vFillColor, geometry);
  varyings.vLineColor = vec4<f32>(attributes.instanceLineColors.rgb, attributes.instanceLineColors.a * layer.opacity);
  // DECKGL_FILTER_COLOR(varyings.vLineColor, geometry);
  varyings.pickingColor = geometry.pickingColor;

  return varyings;
}

@fragment
fn fragmentMain(varyings: Varyings) -> @location(0) vec4<f32> {
  // var geometry: Geometry;
  // geometry.uv = unitPosition;

  let distToCenter = length(varyings.unitPosition) * varyings.outerRadiusPixels;
  let inCircle = select(
    step(distToCenter, varyings.outerRadiusPixels),
    smoothedge(distToCenter, varyings.outerRadiusPixels),
    scatterplot.antialiasing != 0
  );

  if (inCircle == 0.0) {
    discard;
  }

  var fragColor: vec4<f32>;

  if (scatterplot.stroked != 0) {
    let isLine = select(
      step(varyings.innerUnitRadius * varyings.outerRadiusPixels, distToCenter),
      smoothedge(varyings.innerUnitRadius * varyings.outerRadiusPixels, distToCenter),
      scatterplot.antialiasing != 0
    );

    if (scatterplot.filled != 0) {
      fragColor = mix(varyings.vFillColor, varyings.vLineColor, isLine);
    } else {
      if (isLine == 0.0) {
        discard;
      }
      fragColor = vec4<f32>(varyings.vLineColor.rgb, varyings.vLineColor.a * isLine);
    }
  } else if (scatterplot.filled == 0) {
    discard;
  } else {
    fragColor = varyings.vFillColor;
  }

  fragColor.a *= inCircle;

  clip_filterColor(varyings.clipCoordinates);

  if (picking.isActive > 0.5) {
    if (!picking_isColorValid(varyings.pickingColor)) {
      discard;
    }
    return vec4<f32>(varyings.pickingColor, 1.0);
  }

  if (picking.isHighlightActive > 0.5) {
    let highlightedObjectColor = picking_normalizeColor(picking.highlightedObjectColor);
    if (picking_isColorZero(abs(varyings.pickingColor - highlightedObjectColor))) {
      let highLightAlpha = picking.highlightColor.a;
      let blendedAlpha = highLightAlpha + fragColor.a * (1.0 - highLightAlpha);
      if (blendedAlpha > 0.0) {
        let highLightRatio = highLightAlpha / blendedAlpha;
        fragColor = vec4<f32>(
          mix(fragColor.rgb, picking.highlightColor.rgb, highLightRatio),
          blendedAlpha
        );
      } else {
        fragColor = vec4<f32>(fragColor.rgb, 0.0);
      }
    }
  }

  // Apply premultiplied alpha as required by transparent canvas
  fragColor = deckgl_premultiplied_alpha(fragColor);

  return fragColor;
  // return vec4<f32>(0, 0, 1, 1);
}
`;function xS(r){return _N.replace("PICKING_COLOR_ATTRIBUTE",r?"@location(8) rowIndexes: u32,":"").replace("PICKING_COLOR_VALUE",r?"picking_getPickingColorFromIndex(attributes.rowIndexes)":"picking_getPickingColorFromIndex(attributes.instanceIndex)")}var bN=`struct ClipUniforms {
  enabled: i32,
  mode: i32,
  bounds: vec4<f32>,
};

@group(2) @binding(auto) var<uniform> clipUniforms: ClipUniforms;

fn clip_isInBounds(coordinates: vec2<f32>) -> bool {
  return coordinates.x >= clipUniforms.bounds.x &&
    coordinates.y >= clipUniforms.bounds.y &&
    coordinates.x < clipUniforms.bounds.z &&
    coordinates.y < clipUniforms.bounds.w;
}

fn clip_filterPosition(position: ptr<function, vec4<f32>>, instanceCoordinates: vec2<f32>) {
  if (
    clipUniforms.enabled != 0 &&
    clipUniforms.mode == 1 &&
    !clip_isInBounds(instanceCoordinates)
  ) {
    *position = vec4<f32>(2.0, 2.0, 2.0, 1.0);
  }
}

fn clip_filterColor(geometryCoordinates: vec2<f32>) {
  if (
    clipUniforms.enabled != 0 &&
    clipUniforms.mode == 0 &&
    !clip_isInBounds(geometryCoordinates)
  ) {
    discard;
  }
}
`,xN={name:"clip",source:bN,props:{},uniforms:{},bindingLayout:[{name:"clip",group:2}],uniformTypes:{enabled:"i32",mode:"i32",bounds:"vec4<f32>"},defaultUniforms:{enabled:0,mode:0,bounds:[0,0,1,1]},getUniforms(r={}){let e={};return r.enabled!==void 0&&(e.enabled=r.enabled?1:0),r.mode!==void 0&&(e.mode=r.mode==="instance"?1:0),r.bounds!==void 0&&(e.bounds=r.bounds),e}},gf=xN;var vS=[0,0,0,255],vN={radiusUnits:"meters",radiusScale:{type:"number",min:0,value:1},radiusMinPixels:{type:"number",min:0,value:0},radiusMaxPixels:{type:"number",min:0,value:Number.MAX_SAFE_INTEGER},lineWidthUnits:"meters",lineWidthScale:{type:"number",min:0,value:1},lineWidthMinPixels:{type:"number",min:0,value:0},lineWidthMaxPixels:{type:"number",min:0,value:Number.MAX_SAFE_INTEGER},stroked:!1,filled:!0,billboard:!1,antialiasing:!0,getPosition:{type:"accessor",value:r=>r.position},getRadius:{type:"accessor",value:1},getFillColor:{type:"accessor",value:vS},getLineColor:{type:"accessor",value:vS},getLineWidth:{type:"accessor",value:1},getPixelOffset:{type:"accessor",value:[0,0]},strokeWidth:{deprecatedFor:"getLineWidth"},outline:{deprecatedFor:"stroked"},getColor:{deprecatedFor:["getFillColor","getLineColor"]}},Ba=class extends Kn{getShaders(){let e=!!this.props.data?.attributes?.rowIndexes;return super.getShaders({vs:_S,fs:bS,source:xS(e),defines:e?{USE_ROW_INDEXES:!0}:{},modules:[zr,Ur,Wr,yS,...this.context.device.type==="webgpu"?[gf]:[]]})}initializeState(){let e=this.props.data?.attributes?.rowIndexes?{rowIndexes:{size:1,type:"uint32",noAlloc:!0}}:{};this.getAttributeManager().addInstanced({instancePositions:{size:3,type:"float64",fp64:this.use64bitPositions(),transition:!0,accessor:"getPosition"},instanceRadius:{size:1,transition:!0,accessor:"getRadius",defaultValue:1,bufferGroup:"scatterplot-instance-data"},instanceFillColors:{size:this.props.colorFormat.length,transition:!0,type:"unorm8",accessor:"getFillColor",defaultValue:[0,0,0,255],bufferGroup:"scatterplot-instance-data"},instanceLineColors:{size:this.props.colorFormat.length,transition:!0,type:"unorm8",accessor:"getLineColor",defaultValue:[0,0,0,255],bufferGroup:"scatterplot-instance-data"},instanceLineWidths:{size:1,transition:!0,accessor:"getLineWidth",defaultValue:1,bufferGroup:"scatterplot-instance-data"},instancePixelOffset:{size:2,transition:!0,accessor:"getPixelOffset",bufferGroup:"scatterplot-instance-data"},...e})}updateState(e){super.updateState(e),e.changeFlags.extensionsChanged&&(this.state.model?.destroy(),this.state.model=this._getModel(),this.getAttributeManager().invalidateAll())}draw({uniforms:e}){let{radiusUnits:t,radiusScale:n,radiusMinPixels:i,radiusMaxPixels:o,stroked:s,filled:a,billboard:c,antialiasing:l,lineWidthUnits:u,lineWidthScale:f,lineWidthMinPixels:h,lineWidthMaxPixels:p}=this.props,m={stroked:s,filled:a,billboard:c,antialiasing:l,radiusUnits:pt[t],radiusScale:n,radiusMinPixels:i,radiusMaxPixels:o,lineWidthUnits:pt[u],lineWidthScale:f,lineWidthMinPixels:h,lineWidthMaxPixels:p},g=this.state.model;g.shaderInputs.setProps({scatterplot:m}),g.draw(this.context.renderPass)}_getModel(){let e=[-1,-1,0,1,-1,0,-1,1,0,1,1,0];return new Re(this.context.device,{...this.getShaders(),id:this.props.id,bufferLayout:this.getAttributeManager().getBufferLayouts(),geometry:new yt({topology:"triangle-strip",attributes:{positions:{size:3,value:new Float32Array(e)}}}),isInstanced:!0})}};Ba.defaultProps=vN;Ba.layerName="ScatterplotLayer";var yf=Ba;var _f={CLOCKWISE:1,COUNTER_CLOCKWISE:-1};function Oa(r,e,t={}){return wS(r,t)!==e?(wN(r,t),!0):!1}function wS(r,e={}){return Math.sign(bf(r,e))}var Cg={x:0,y:1,z:2};function bf(r,e={}){let{start:t=0,end:n=r.length,plane:i="xy"}=e,o=e.size||2,s=0,a=Cg[i[0]],c=Cg[i[1]];for(let l=t,u=n-o;l<n;l+=o)s+=(r[l+a]-r[u+a])*(r[l+c]+r[u+c]),u=l;return s/2}function wN(r,e){let{start:t=0,end:n=r.length,size:i=2}=e,o=(n-t)/i,s=Math.floor(o/2);for(let a=0;a<s;++a){let c=t+a*i,l=t+(o-1-a)*i;for(let u=0;u<i;++u){let f=r[c+u];r[c+u]=r[l+u],r[l+u]=f}}}function sr(r,e){let t=e.length,n=r.length;if(n>0){let i=!0;for(let o=0;o<t;o++)if(r[n-t+o]!==e[o]){i=!1;break}if(i)return!1}for(let i=0;i<t;i++)r[n+i]=e[i];return!0}function Mg(r,e){let t=e.length;for(let n=0;n<t;n++)r[n]=e[n]}function uo(r,e,t,n,i=[]){let o=n+e*t;for(let s=0;s<t;s++)i[s]=r[o+s];return i}function ES(r,e,t,n,i=[]){let o,s;if(t&8)o=(n[3]-r[1])/(e[1]-r[1]),s=3;else if(t&4)o=(n[1]-r[1])/(e[1]-r[1]),s=1;else if(t&2)o=(n[2]-r[0])/(e[0]-r[0]),s=2;else if(t&1)o=(n[0]-r[0])/(e[0]-r[0]),s=0;else return null;for(let a=0;a<r.length;a++)i[a]=(s&1)===a?n[s]:o*(e[a]-r[a])+r[a];return i}function SS(r,e){let t=0;return r[0]<e[0]?t|=1:r[0]>e[2]&&(t|=2),r[1]<e[1]?t|=4:r[1]>e[3]&&(t|=8),t}var PS=0,SN=1;function ka(r,e=null,t){if(!r.length)return[];let{size:n=2,gridResolution:i=10,gridOffset:o=[0,0],edgeTypes:s=!1}=t||{},a=[],c=[{pos:r,types:s?new Array(r.length/n).fill(SN):null,holes:e||[]}],l=[[],[]],u=[];for(;c.length;){let{pos:f,types:h,holes:p}=c.shift();TN(f,n,p[0]||f.length,l),u=PN(l[0],i,o,u);let m=SS(l[1],u);if(m){let g=TS(f,h,n,0,p[0]||f.length,u,m),y={pos:g[0].pos,types:g[0].types,holes:[]},x={pos:g[1].pos,types:g[1].types,holes:[]};c.push(y,x);for(let v=0;v<p.length;v++)g=TS(f,h,n,p[v],p[v+1]||f.length,u,m),g[0]&&(y.holes.push(y.pos.length),y.pos=xf(y.pos,g[0].pos),s&&(y.types=xf(y.types,g[0].types))),g[1]&&(x.holes.push(x.pos.length),x.pos=xf(x.pos,g[1].pos),s&&(x.types=xf(x.types,g[1].types)))}else{let g={positions:f};s&&(g.edgeTypes=h),p.length&&(g.holeIndices=p),a.push(g)}}return a}function TS(r,e,t,n,i,o,s){let a=(i-n)/t,c=[],l=[],u=[],f=[],h=[],p,m,g,y=uo(r,a-1,t,n),x=Math.sign(s&8?y[1]-o[3]:y[0]-o[2]),v=e&&e[a-1],_=0,w=0;for(let E=0;E<a;E++)p=uo(r,E,t,n,p),m=Math.sign(s&8?p[1]-o[3]:p[0]-o[2]),g=e&&e[n/t+E],m&&x&&x!==m&&(ES(y,p,s,o,h),sr(c,h)&&u.push(v),sr(l,h)&&f.push(v)),m<=0?(sr(c,p)&&u.push(g),_-=m):u.length&&(u[u.length-1]=PS),m>=0?(sr(l,p)&&f.push(g),w+=m):f.length&&(f[f.length-1]=PS),Mg(y,p),x=m,v=g;return[_?{pos:c,types:e&&u}:null,w?{pos:l,types:e&&f}:null]}function PN(r,e,t,n){let i=Math.floor((r[0]-t[0])/e)*e+t[0],o=Math.floor((r[1]-t[1])/e)*e+t[1];return n[0]=i,n[1]=o,n[2]=i+e,n[3]=o+e,n}function TN(r,e,t,n){let i=1/0,o=-1/0,s=1/0,a=-1/0;for(let c=0;c<t;c+=e){let l=r[c],u=r[c+1];i=l<i?l:i,o=l>o?l:o,s=u<s?u:s,a=u>a?u:a}return n[0][0]=i,n[0][1]=s,n[1][0]=o,n[1][1]=a,n}function xf(r,e){for(let t=0;t<e.length;t++)r.push(e[t]);return r}var AN=85.051129;function Ig(r,e=null,t){let{size:n=2,normalize:i=!0,edgeTypes:o=!1}=t||{};e=e||[];let s=[],a=[],c=0,l=0;for(let f=0;f<=e.length;f++){let h=e[f]||r.length,p=l,m=CN(r,n,c,h);for(let g=m;g<h;g++)s[l++]=r[g];for(let g=c;g<m;g++)s[l++]=r[g];IN(s,n,p,l),MN(s,n,p,l,t?.maxLatitude),c=h,a[f]=l}a.pop();let u=ka(s,a,{size:n,gridResolution:360,gridOffset:[-180,-180],edgeTypes:o});if(i)for(let f of u)RN(f.positions,n);return u}function CN(r,e,t,n){let i=-1,o=-1;for(let s=t+1;s<n;s+=e){let a=Math.abs(r[s]);a>i&&(i=a,o=s-1)}return o}function MN(r,e,t,n,i=AN){let o=r[t],s=r[n-e];if(Math.abs(o-s)>180){let a=uo(r,0,e,t);a[0]+=Math.round((s-o)/360)*360,sr(r,a),a[1]=Math.sign(a[1])*i,sr(r,a),a[0]=o,sr(r,a)}}function IN(r,e,t,n){let i=r[0],o;for(let s=t;s<n;s+=e){o=r[s];let a=o-i;(a>180||a<-180)&&(o-=Math.round(a/360)*360),r[s]=i=o}}function RN(r,e){let t,n=r.length/e;for(let o=0;o<n&&(t=r[o*e],(t+180)%360===0);o++);let i=-Math.round(t/360)*360;if(i!==0)for(let o=0;o<n;o++)r[o*e]+=i}de();var DS=aP(IS(),1);var Pf=_f.CLOCKWISE,RS=_f.COUNTER_CLOCKWISE,Jr={isClosed:!0};function XN(r){if(r=r&&r.positions||r,!Array.isArray(r)&&!ArrayBuffer.isView(r))throw new Error("invalid polygon")}function ho(r){return"positions"in r?r.positions:r}function Ua(r){return"holeIndices"in r?r.holeIndices:null}function ZN(r){return Array.isArray(r[0])}function KN(r){return r.length>=1&&r[0].length>=2&&Number.isFinite(r[0][0])}function QN(r){let e=r[0],t=r[r.length-1];return e[0]===t[0]&&e[1]===t[1]&&e[2]===t[2]}function JN(r,e,t,n){for(let i=0;i<e;i++)if(r[t+i]!==r[n-e+i])return!1;return!0}function BS(r,e,t,n,i){let o=e,s=t.length;for(let a=0;a<s;a++)for(let c=0;c<n;c++)r[o++]=t[a][c]||0;if(!QN(t))for(let a=0;a<n;a++)r[o++]=t[0][a]||0;return Jr.start=e,Jr.end=o,Jr.size=n,Oa(r,i,Jr),o}function OS(r,e,t,n,i=0,o,s){o=o||t.length;let a=o-i;if(a<=0)return e;let c=e;for(let l=0;l<a;l++)r[c++]=t[i+l];if(!JN(t,n,i,o))for(let l=0;l<n;l++)r[c++]=t[i+l];return Jr.start=e,Jr.end=c,Jr.size=n,Oa(r,s,Jr),c}function NS(r,e){XN(r);let t=[],n=[];if("positions"in r){let{positions:i,holeIndices:o}=r;if(o){let s=0;for(let a=0;a<=o.length;a++)s=OS(t,s,i,e,o[a-1],o[a],a===0?Pf:RS),n.push(s);return n.pop(),{positions:t,holeIndices:n}}r=i}if(!ZN(r))return OS(t,0,r,e,0,t.length,Pf),t;if(!KN(r)){let i=0;for(let[o,s]of r.entries())i=BS(t,i,s,e,o===0?Pf:RS),n.push(i);return n.pop(),{positions:t,holeIndices:n}}return BS(t,0,r,e,Pf),t}function Dg(r,e,t){let n=r.length/3,i=0;for(let o=0;o<n;o++){let s=(o+1)%n;i+=r[o*3+e]*r[s*3+t],i-=r[s*3+e]*r[o*3+t]}return Math.abs(i/2)}function kS(r,e,t,n){let i=r.length/3;for(let o=0;o<i;o++){let s=o*3,a=r[s+0],c=r[s+1],l=r[s+2];r[s+e]=a,r[s+t]=c,r[s+n]=l}}function FS(r,e,t,n){let i=Ua(r);i&&(i=i.map(a=>a/e));let o=ho(r),s=n&&e===3;if(t){let a=o.length;o=o.slice();let c=[];for(let l=0;l<a;l+=e){c[0]=o[l],c[1]=o[l+1],s&&(c[2]=o[l+2]);let u=t(c);o[l]=u[0],o[l+1]=u[1],s&&(o[l+2]=u[2])}}if(s){let a=Dg(o,0,1),c=Dg(o,0,2),l=Dg(o,1,2);if(!a&&!c&&!l)return[];a>c&&a>l||(c>l?(t||(o=o.slice()),kS(o,0,2,1)):(t||(o=o.slice()),kS(o,2,0,1)))}return(0,DS.default)(o,i,e)}var Ga=class extends lo{constructor(e){let{fp64:t,IndexType:n=Uint32Array}=e;super({...e,attributes:{positions:{size:3,type:t?Float64Array:Float32Array},vertexValid:{type:Uint16Array,size:1},indices:{type:n,size:1}}})}get(e){let{attributes:t}=this;return e==="indices"?t.indices&&t.indices.subarray(0,this.vertexCount):t[e]}updateGeometry(e){super.updateGeometry(e);let t=this.buffers.indices;if(t)this.vertexCount=(t.value||t).length;else if(this.data&&!this.getGeometry)throw new Error("missing indices buffer")}normalizeGeometry(e){if(this.normalize){let t=NS(e,this.positionSize);return this.opts.resolution?ka(ho(t),Ua(t),{size:this.positionSize,gridResolution:this.opts.resolution,edgeTypes:!0}):this.opts.wrapLongitude?Ig(ho(t),Ua(t),{size:this.positionSize,maxLatitude:86,edgeTypes:!0}):t}return e}getGeometrySize(e){if(US(e)){let t=0;for(let n of e)t+=this.getGeometrySize(n);return t}return ho(e).length/this.positionSize}getGeometryFromBuffer(e){return this.normalize||!this.buffers.indices?super.getGeometryFromBuffer(e):null}updateGeometryAttributes(e,t){if(e&&US(e))for(let n of e){let i=this.getGeometrySize(n);t.geometrySize=i,this.updateGeometryAttributes(n,t),t.vertexStart+=i,t.indexStart=this.indexStarts[t.geometryIndex+1]}else{let n=e;this._updateIndices(n,t),this._updatePositions(n,t),this._updateVertexValid(n,t)}}_updateIndices(e,{geometryIndex:t,vertexStart:n,indexStart:i}){let{attributes:o,indexStarts:s,typedArrayManager:a}=this,c=o.indices;if(!c||!e)return;let l=i,u=FS(e,this.positionSize,this.opts.preproject,this.opts.full3d);c=a.allocate(c,i+u.length,{copy:!0});for(let f=0;f<u.length;f++)c[l++]=u[f]+n;s[t+1]=i+u.length,o.indices=c}_updatePositions(e,{vertexStart:t,geometrySize:n}){let{attributes:{positions:i},positionSize:o}=this;if(!i||!e)return;let s=ho(e);for(let a=t,c=0;c<n;a++,c++){let l=s[c*o],u=s[c*o+1],f=o>2?s[c*o+2]:0;i[a*3]=l,i[a*3+1]=u,i[a*3+2]=f}}_updateVertexValid(e,{vertexStart:t,geometrySize:n}){let{positionSize:i}=this,o=this.attributes.vertexValid,s=e&&Ua(e);if(e&&e.edgeTypes?o.set(e.edgeTypes,t):o.fill(1,t,t+n),s)for(let a=0;a<s.length;a++)o[t+s[a]/i-1]=0;o[t+n-1]=0}};function US(r){return Array.isArray(r)&&r.length>0&&!Number.isFinite(r[0])}var t6=`struct SolidPolygonUniforms {
  extruded: f32,
  isWireframe: f32,
  elevationScale: f32,
};

@group(0) @binding(auto) var<uniform> solidPolygon: SolidPolygonUniforms;
`,GS=`layout(std140) uniform solidPolygonUniforms {
  bool extruded;
  bool isWireframe;
  float elevationScale;
} solidPolygon;
`,zS={name:"solidPolygon",source:t6,vs:GS,fs:GS,uniformTypes:{extruded:"f32",isWireframe:"f32",elevationScale:"f32"}};var Tf=`in vec4 fillColors;
in vec4 lineColors;
in float rowIndexes;
out vec4 vColor;
struct PolygonProps {
vec3 positions;
vec3 positions64Low;
vec3 normal;
float elevations;
};
vec3 project_offset_normal(vec3 vector) {
if (project.coordinateSystem == COORDINATE_SYSTEM_LNGLAT ||
project.coordinateSystem == COORDINATE_SYSTEM_LNGLAT_OFFSETS) {
return normalize(vector * project.commonUnitsPerWorldUnit);
}
return project_normal(vector);
}
void calculatePosition(PolygonProps props) {
vec3 pos = props.positions;
vec3 pos64Low = props.positions64Low;
vec3 normal = props.normal;
vec4 colors = solidPolygon.isWireframe ? lineColors : fillColors;
geometry.worldPosition = props.positions;
geometry.pickingColor = picking_getPickingColorFromIndex(rowIndexes);
if (solidPolygon.extruded) {
pos.z += props.elevations * solidPolygon.elevationScale;
}
gl_Position = project_position_to_clipspace(pos, pos64Low, vec3(0.), geometry.position);
DECKGL_FILTER_GL_POSITION(gl_Position, geometry);
if (solidPolygon.extruded) {
#ifdef IS_SIDE_VERTEX
normal = project_offset_normal(normal);
#else
normal = project_normal(normal);
#endif
geometry.normal = normal;
vec3 lightColor = lighting_getLightColor(colors.rgb, project.cameraPosition, geometry.position.xyz, geometry.normal);
vColor = vec4(lightColor, colors.a * layer.opacity);
} else {
vColor = vec4(colors.rgb, colors.a * layer.opacity);
}
DECKGL_FILTER_COLOR(vColor, geometry);
}
`;var $S=`#version 300 es
#define SHADER_NAME solid-polygon-layer-vertex-shader
in vec3 vertexPositions;
in vec3 vertexPositions64Low;
in float elevations;
${Tf}
void main(void) {
PolygonProps props;
props.positions = vertexPositions;
props.positions64Low = vertexPositions64Low;
props.elevations = elevations;
props.normal = vec3(0.0, 0.0, 1.0);
calculatePosition(props);
}
`;var VS=`#version 300 es
#define SHADER_NAME solid-polygon-layer-vertex-shader-side
#define IS_SIDE_VERTEX
in vec2 positions;
in vec3 vertexPositions;
in vec3 nextVertexPositions;
in vec3 vertexPositions64Low;
in vec3 nextVertexPositions64Low;
in float elevations;
in float instanceVertexValid;
${Tf}
void main(void) {
if(instanceVertexValid < 0.5){
gl_Position = vec4(0.);
return;
}
PolygonProps props;
vec3 pos;
vec3 pos64Low;
vec3 nextPos;
vec3 nextPos64Low;
#if RING_WINDING_ORDER_CW == 1
pos = vertexPositions;
pos64Low = vertexPositions64Low;
nextPos = nextVertexPositions;
nextPos64Low = nextVertexPositions64Low;
#else
pos = nextVertexPositions;
pos64Low = nextVertexPositions64Low;
nextPos = vertexPositions;
nextPos64Low = vertexPositions64Low;
#endif
props.positions = mix(pos, nextPos, positions.x);
props.positions64Low = mix(pos64Low, nextPos64Low, positions.x);
props.normal = vec3(
pos.y - nextPos.y + (pos64Low.y - nextPos64Low.y),
nextPos.x - pos.x + (nextPos64Low.x - pos64Low.x),
0.0);
props.elevations = elevations * positions.y;
calculatePosition(props);
}
`;var WS=`#version 300 es
#define SHADER_NAME solid-polygon-layer-fragment-shader
precision highp float;
in vec4 vColor;
out vec4 fragColor;
void main(void) {
fragColor = vColor;
geometry.uv = vec2(0.);
DECKGL_FILTER_COLOR(fragColor, geometry);
}
`;function jS(){return`fn project_offset_normal(vector: vec3<f32>) -> vec3<f32> {
  if (project.coordinateSystem == COORDINATE_SYSTEM_LNGLAT ||
      project.coordinateSystem == COORDINATE_SYSTEM_LNGLAT_OFFSETS) {
    return normalize(vector * project.commonUnitsPerWorldUnit);
  }
  return project_normal(vector);
}

fn apply_polygon_color(
  colors: vec4<f32>,
  normal: vec3<f32>,
  position: vec4<f32>
) -> vec4<f32> {
  if (solidPolygon.extruded > 0.5) {
    let lightColor = lighting_getLightColor2(
      colors.rgb,
      project.cameraPosition,
      position.xyz,
      normal
    );
    return vec4<f32>(lightColor, colors.a * layer.opacity);
  }
  return vec4<f32>(colors.rgb, colors.a * layer.opacity);
}
`}function HS(){return`@fragment
fn fragmentMain(inp: Varyings) -> @location(0) vec4<f32> {
  geometry.uv = vec2<f32>(0.0, 0.0);

  clip_filterColor(inp.clipCoordinates);

  if (picking.isActive > 0.5) {
    if (!picking_isColorValid(inp.pickingColor)) {
      discard;
    }
    return vec4<f32>(inp.pickingColor, 1.0);
  }

  var fragColor = inp.vColor;

  if (picking.isHighlightActive > 0.5) {
    let highlightedObjectColor = picking_normalizeColor(picking.highlightedObjectColor);
    if (picking_isColorZero(abs(inp.pickingColor - highlightedObjectColor))) {
      let highLightAlpha = picking.highlightColor.a;
      let blendedAlpha = highLightAlpha + fragColor.a * (1.0 - highLightAlpha);
      if (blendedAlpha > 0.0) {
        let highLightRatio = highLightAlpha / blendedAlpha;
        fragColor = vec4<f32>(
          mix(fragColor.rgb, picking.highlightColor.rgb, highLightRatio),
          blendedAlpha
        );
      } else {
        fragColor = vec4<f32>(fragColor.rgb, 0.0);
      }
    }
  }

  return deckgl_premultiplied_alpha(fragColor);
}
`}function r6(){return`${jS()}

struct Attributes {
  @location(0) vertexPositions: vec3<f32>,
  @location(1) vertexPositions64Low: vec3<f32>,
  @location(2) elevations: f32,
  @location(3) fillColors: vec4<f32>,
  @location(4) lineColors: vec4<f32>,
  @location(5) rowIndexes: u32,
};

struct Varyings {
  @builtin(position) position: vec4<f32>,
  @location(0) vColor: vec4<f32>,
  @location(1) pickingColor: vec3<f32>,
  @location(2) clipCoordinates: vec2<f32>,
};

@vertex
fn vertexMain(attributes: Attributes) -> Varyings {
  var outp: Varyings;

  var pos = attributes.vertexPositions;
  if (solidPolygon.extruded > 0.5) {
    pos.z += attributes.elevations * solidPolygon.elevationScale;
  }

  geometry.worldPosition = attributes.vertexPositions;
  geometry.pickingColor = picking_getPickingColorFromIndex(attributes.rowIndexes);

  let projectedPosition = project_position_to_clipspace_and_commonspace(
    pos,
    attributes.vertexPositions64Low,
    vec3<f32>(0.0)
  );
  geometry.position = projectedPosition.commonPosition;
  outp.position = projectedPosition.clipPosition;

  let normal = project_normal(vec3<f32>(0.0, 0.0, 1.0));
  geometry.normal = normal;

  let colors = select(
    attributes.fillColors,
    attributes.lineColors,
    solidPolygon.isWireframe > 0.5
  );
  outp.vColor = apply_polygon_color(colors, normal, geometry.position);
  outp.pickingColor = geometry.pickingColor;

  outp.clipCoordinates = geometry.position.xy;
  clip_filterPosition(&outp.position, geometry.worldPosition.xy);

  return outp;
}

${HS()}
`}function n6(r){return`const RING_WINDING_ORDER_CW: bool = ${r?"true":"false"};

${jS()}

struct Attributes {
  @location(0) positions: vec2<f32>,
  @location(1) vertexPositions: vec3<f32>,
  @location(2) vertexPositions64Low: vec3<f32>,
  @location(3) nextVertexPositions: vec3<f32>,
  @location(4) nextVertexPositions64Low: vec3<f32>,
  @location(5) vertexValid: f32,
  @location(6) elevations: f32,
  @location(7) fillColors: vec4<f32>,
  @location(8) lineColors: vec4<f32>,
  @location(9) rowIndexes: u32,
};

struct Varyings {
  @builtin(position) position: vec4<f32>,
  @location(0) vColor: vec4<f32>,
  @location(1) pickingColor: vec3<f32>,
  @location(2) clipCoordinates: vec2<f32>,
};

@vertex
fn vertexMain(attributes: Attributes) -> Varyings {
  var outp: Varyings;
  outp.position = vec4<f32>(0.0);
  outp.vColor = vec4<f32>(0.0);
  outp.pickingColor = picking_getPickingColorFromIndex(attributes.rowIndexes);
  outp.clipCoordinates = vec2<f32>(0.0);

  if (attributes.vertexValid < 0.5) {
    return outp;
  }

  let pos = select(attributes.nextVertexPositions, attributes.vertexPositions, RING_WINDING_ORDER_CW);
  let pos64Low = select(
    attributes.nextVertexPositions64Low,
    attributes.vertexPositions64Low,
    RING_WINDING_ORDER_CW
  );
  let nextPos = select(attributes.vertexPositions, attributes.nextVertexPositions, RING_WINDING_ORDER_CW);
  let nextPos64Low = select(
    attributes.vertexPositions64Low,
    attributes.nextVertexPositions64Low,
    RING_WINDING_ORDER_CW
  );

  let position = mix(pos, nextPos, attributes.positions.x);
  let position64Low = mix(pos64Low, nextPos64Low, attributes.positions.x);

  var worldPosition = position;
  if (solidPolygon.extruded > 0.5) {
    worldPosition.z += attributes.elevations * attributes.positions.y * solidPolygon.elevationScale;
  }

  geometry.worldPosition = position;
  geometry.pickingColor = picking_getPickingColorFromIndex(attributes.rowIndexes);

  let projectedPosition = project_position_to_clipspace_and_commonspace(
    worldPosition,
    position64Low,
    vec3<f32>(0.0)
  );
  geometry.position = projectedPosition.commonPosition;
  outp.position = projectedPosition.clipPosition;

  let normal = project_offset_normal(vec3<f32>(
    pos.y - nextPos.y + (pos64Low.y - nextPos64Low.y),
    nextPos.x - pos.x + (nextPos64Low.x - pos64Low.x),
    0.0
  ));
  geometry.normal = normal;

  let colors = select(
    attributes.fillColors,
    attributes.lineColors,
    solidPolygon.isWireframe > 0.5
  );
  outp.vColor = apply_polygon_color(colors, normal, geometry.position);
  outp.pickingColor = geometry.pickingColor;

  outp.clipCoordinates = geometry.position.xy;
  clip_filterPosition(&outp.position, geometry.worldPosition.xy);

  return outp;
}

${HS()}
`}function YS(r,e){return r==="top"?r6():n6(e)}var Af=[0,0,0,255],i6={filled:!0,extruded:!1,wireframe:!1,_normalize:!0,_windingOrder:"CW",_full3d:!1,elevationScale:{type:"number",min:0,value:1},getPolygon:{type:"accessor",value:r=>r.polygon},getElevation:{type:"accessor",value:1e3},getFillColor:{type:"accessor",value:Af},getLineColor:{type:"accessor",value:Af},material:!0},Lf={enter:(r,e)=>e.length?e.subarray(e.length-r.length):r},za=class extends Kn{getShaders(e){let t=!this.props._normalize&&this.props._windingOrder==="CCW"?0:1;return super.getShaders({vs:e==="top"?$S:VS,fs:WS,source:YS(e,!!t),defines:{RING_WINDING_ORDER_CW:t},modules:[zr,Ur,Si,Wr,zS,...this.context.device.type==="webgpu"?[gf]:[]]})}get wrapLongitude(){return!1}getBounds(){return this.getAttributeManager()?.getBounds(["vertexPositions"])}initializeState(){let{viewport:e}=this.context,{coordinateSystem:t}=this.props,{_full3d:n}=this.props;e.isGeospatial&&t==="default"&&(t="lnglat");let i;t==="lnglat"&&(n?i=e.projectPosition.bind(e):i=e.projectFlat.bind(e)),this.setState({numInstances:0,polygonTesselator:new Ga({preproject:i,fp64:this.use64bitPositions(),IndexType:Uint32Array})});let o=this.getAttributeManager(),s=!0,a=this.context.device.type==="webgpu";o.add({indices:{size:1,isIndexed:!0,update:this.calculateIndices,noAlloc:s},vertexPositions:{size:3,type:"float64",stepMode:"dynamic",fp64:this.use64bitPositions(),transition:Lf,accessor:"getPolygon",update:this.calculatePositions,noAlloc:s,...a?{}:{shaderAttributes:{nextVertexPositions:{vertexOffset:1}}}},...a?{nextVertexPositions:{size:3,type:"float64",stepMode:"dynamic",fp64:this.use64bitPositions(),transition:!1,update:this.calculateNextPositions,noAlloc:s}}:{},[a?"vertexValid":"instanceVertexValid"]:{size:1,type:a?"float32":"uint16",stepMode:"instance",update:this.calculateVertexValid,noAlloc:s},elevations:{size:1,stepMode:"dynamic",transition:Lf,accessor:"getElevation",bufferGroup:"solid-polygon-instance-data"},fillColors:{size:this.props.colorFormat.length,type:"unorm8",stepMode:"dynamic",transition:Lf,accessor:"getFillColor",defaultValue:Af,bufferGroup:"solid-polygon-instance-data"},lineColors:{size:this.props.colorFormat.length,type:"unorm8",stepMode:"dynamic",transition:Lf,accessor:"getLineColor",defaultValue:Af,bufferGroup:"solid-polygon-instance-data"},rowIndexes:{size:1,type:"uint32",stepMode:"dynamic",accessor:(c,{index:l})=>c&&c.__source?c.__source.index:l,bufferGroup:"solid-polygon-instance-data"}})}getPickingInfo(e){let t=super.getPickingInfo(e),{index:n}=t,i=this.props.data;return i[0]&&i[0].__source&&(t.object=i.find(o=>o.__source.index===n)),t}disablePickingIndex(e){let t=this.props.data;if(t[0]&&t[0].__source)for(let n=0;n<t.length;n++)t[n].__source.index===e&&this._disablePickingIndex(n);else super.disablePickingIndex(e)}draw({uniforms:e}){let{extruded:t,filled:n,wireframe:i,elevationScale:o}=this.props,{topModel:s,sideModel:a,wireframeModel:c,polygonTesselator:l}=this.state,u={extruded:!!t,elevationScale:o,isWireframe:!1};c&&i&&(c.setInstanceCount(l.instanceCount-1),c.shaderInputs.setProps({solidPolygon:{...u,isWireframe:!0}}),c.draw(this.context.renderPass)),a&&n&&(a.setInstanceCount(l.instanceCount-1),a.shaderInputs.setProps({solidPolygon:u}),a.draw(this.context.renderPass)),s&&n&&(s.setVertexCount(l.vertexCount),s.shaderInputs.setProps({solidPolygon:u}),s.draw(this.context.renderPass))}updateState(e){super.updateState(e),this.updateGeometry(e);let{props:t,oldProps:n,changeFlags:i}=e,o=this.getAttributeManager();(i.extensionsChanged||t.filled!==n.filled||t.extruded!==n.extruded)&&(this.state.models?.forEach(a=>a.destroy()),this.setState(this._getModels()),o.invalidateAll())}updateGeometry({props:e,oldProps:t,changeFlags:n}){if(n.dataChanged||n.updateTriggersChanged&&(n.updateTriggersChanged.all||n.updateTriggersChanged.getPolygon)){let{polygonTesselator:o}=this.state,s=e.data.attributes||{};o.updateGeometry({data:e.data,normalize:e._normalize,geometryBuffer:s.getPolygon,buffers:this.context.device.type==="webgpu"?{...s}:s,getGeometry:e.getPolygon,positionFormat:e.positionFormat,wrapLongitude:e.wrapLongitude,resolution:this.context.viewport.resolution,fp64:this.use64bitPositions(),dataChanged:n.dataChanged,full3d:e._full3d}),this.setState({numInstances:o.instanceCount,startIndices:o.vertexStarts}),n.dataChanged||this.getAttributeManager().invalidateAll()}}_getModels(){let{id:e,filled:t,extruded:n}=this.props,i,o,s;if(t){let a=this.getShaders("top");a.defines={...a.defines,NON_INSTANCED_MODEL:1};let c=this.getAttributeManager().getBufferLayouts({isInstanced:!1});this.context.device.type==="webgpu"&&(c=c.filter(l=>l.name!=="indices"&&l.name!=="vertexValid"&&l.name!=="instanceVertexValid"&&l.name!=="nextVertexPositions")),i=new Re(this.context.device,{...a,id:`${e}-top`,topology:"triangle-list",bufferLayout:c,isIndexed:!0,userData:{excludeAttributes:{vertexValid:!0,instanceVertexValid:!0,nextVertexPositions:!0}}})}if(n){let a=this.getAttributeManager().getBufferLayouts({isInstanced:!0});this.context.device.type==="webgpu"&&(a=a.filter(c=>c.name!=="indices")),o=new Re(this.context.device,{...this.getShaders("side"),id:`${e}-side`,bufferLayout:a,geometry:new yt({topology:"triangle-strip",attributes:{positions:{size:2,value:new Float32Array([1,0,0,0,1,1,0,1])}}}),isInstanced:!0,userData:{excludeAttributes:{indices:!0}}}),s=new Re(this.context.device,{...this.getShaders("side"),id:`${e}-wireframe`,bufferLayout:a,geometry:new yt({topology:"line-strip",attributes:{positions:{size:2,value:new Float32Array([1,0,0,0,0,1,1,1])}}}),isInstanced:!0,userData:{excludeAttributes:{indices:!0}}})}return{models:[o,s,i].filter(Boolean),topModel:i,sideModel:o,wireframeModel:s}}calculateIndices(e){let{polygonTesselator:t}=this.state;e.startIndices=t.indexStarts,e.value=t.get("indices")}calculatePositions(e){let{polygonTesselator:t}=this.state;e.startIndices=t.vertexStarts;let n=this.props.data.attributes?.getPolygon;if(this.context.device.type==="webgpu"&&ArrayBuffer.isView(n?.value)){let{value:i,size:o=3,offset:s=0,stride:a}=n,c=s/i.BYTES_PER_ELEMENT,l=a?a/i.BYTES_PER_ELEMENT:o,u=new Float64Array(t.instanceCount*3);for(let f=0;f<t.instanceCount;f++){let h=c+f*l,p=f*3;u[p]=i[h],u[p+1]=i[h+1],u[p+2]=o>2?i[h+2]:0}e.value=u;return}e.value=t.get("positions")}calculateVertexValid(e){let t=this.props.data.attributes?.instanceVertexValid?.value,n=this.context.device.type==="webgpu"&&t?t:this.state.polygonTesselator.get("vertexValid");e.value=this.context.device.type==="webgpu"&&n?Float32Array.from(n):n}calculateNextPositions(e){let{polygonTesselator:t}=this.state,n=this.getAttributeManager().getAttributes(),i=n.vertexPositions.value,o=this.props.data.attributes?.instanceVertexValid?.value||n.vertexValid?.value||t.get("vertexValid");if(e.startIndices=t.vertexStarts,!i){e.value=i;return}let s=i.length/3,a=new i.constructor(i.length);for(let c=0;c<s;c++){let l=c*3,u=o?.[c]&&c+1<s?l+3:l;for(let f=0;f<3;f++)a[l+f]=i[u+f]}e.value=a}};za.defaultProps=i6;za.layerName="SolidPolygonLayer";var po=za;var en=190,je=84,$a=22,o6=9,s6=2,a6=28,mo=24,Ng=[.25,.5,1,2,3,6,12,mo,2*mo,7*mo,14*mo,30*mo];function Ug(r,e,t){let n=document.createElement("div");n.className="atl-canvas-root";let i=document.createElement("div");i.className="atl-deck";let o=document.createElement("div");o.className="atl-labels",o.style.top=je+$a+"px",o.style.width=en+"px";let s=document.createElement("div");s.className="atl-axis",s.style.top=je+"px",s.style.left=en+"px",s.style.height=$a+"px";let a=document.createElement("div");a.className="atl-actlabel",a.style.width=en+"px",a.style.height=je+"px",a.textContent="Events over time";let c=document.createElement("div");c.className="atl-bar";let l=document.createElement("span"),u=document.createElement("button");u.className="atl-link",u.textContent="Whole log",c.append(l,u),n.append(i,o,s,a,c),r.appendChild(n);let f={},h=null,p=[],m=null,g=-1,y={w:r.clientWidth||800,h:r.clientHeight||560},x=()=>Math.max(50,y.w-en),v=()=>Math.max(50,y.h-je-$a),_={writers:{target:[0,0,0],zoomX:0,zoomY:Math.log2(o6),zoomAxis:"X"},activity:{target:[0,je/2,0],zoomX:0,zoomY:0}},w=[new mf({id:"activity",x:en,y:0,width:`calc(100% - ${en}px)`,height:je,flipY:!0,controller:!1}),new mf({id:"writers",x:en,y:je+$a,width:`calc(100% - ${en}px)`,height:`calc(100% - ${je+$a}px)`,flipY:!0,controller:{dragPan:!0,scrollZoom:{speed:.02,smooth:!1},doubleClickZoom:!1,inertia:!1,keyboard:!1}})];function E(){let O=_.writers,U=x()/2/Math.pow(2,O.zoomX);return[O.target[0]-U,O.target[0]+U]}function S(){return Math.pow(2,_.writers.zoomY)}function C(O){let[U,H]=e.extentX(),xe=Math.max(1/60,H-U),pe=Math.log2(x()/(xe*1.04)),fe=Math.log2(x()/(5/60)),X=Math.min(fe,Math.max(pe,O.zoomX)),ee=x()/2/Math.pow(2,X),_e=xe*.02,Le=O.target[0];Le=Math.max(U-_e+ee,Math.min(H+_e-ee,Le)),H-U+2*_e<2*ee&&(Le=(U+H)/2);let ae=Math.log2(Math.min(a6,Math.max(s6,Math.pow(2,O.zoomY)))),Ke=e.lanes.length,Ne=v()/2/Math.pow(2,ae),Tr=O.target[1];return Tr=Ke<=2*Ne?Ne:Math.max(Ne,Math.min(Ke-Ne,Tr)),{...O,target:[Le,Tr,0],zoomX:X,zoomY:ae,zoomAxis:"X"}}function A(O){let U=C(O);_={writers:U,activity:{target:[U.target[0],je/2,0],zoomX:U.zoomX,zoomY:0}},V()}function B(){let[O,U]=E(),H=Math.max(10,Math.floor(x()/3)),{counts:xe,nt:pe,width:fe,max:X}=e.bin(O,U,H),ee=e.types.map((ae,Ke)=>Ke),_e=[];if(X>0)for(let ae=0;ae<H;ae++){let Ke=0,Ne=O+ae*fe,Tr=Ne+fe*.86;for(let Gg of ee){let zg=xe[ae*pe+Gg];if(!zg)continue;let $g=je-2-Ke/X*(je-10);Ke+=zg;let Vg=je-2-Ke/X*(je-10);_e.push({polygon:[[Ne,$g],[Tr,$g],[Tr,Vg],[Ne,Vg]],color:Qe(e.types[Gg]).color})}}let Le=[new po({id:"activity-bars",data:_e,getPolygon:ae=>ae.polygon,getFillColor:ae=>[...ae.color,220]})];if(m){let[ae,Ke]=m[0]<m[1]?m:[m[1],m[0]];Le.push(new po({id:"activity-brush",data:[{polygon:[[ae,0],[Ke,0],[Ke,je],[ae,je]]}],getPolygon:Ne=>Ne.polygon,getFillColor:[167,139,250,60]}))}return Le}function L(){let O=e.lanes.length,[U,H]=e.extentX(),xe=[];for(let X=0;X<O;X+=2)xe.push(X);let pe=[new po({id:"writers-bands",data:xe,getPolygon:X=>[[U-1e5,X],[H+1e5,X],[H+1e5,X+1],[U-1e5,X+1]],getFillColor:[255,255,255,7],updateTriggers:{getPolygon:[O,H]}})],fe=h&&h.laneRow!=null?h.laneRow:-1;if(fe>=0||g>=0){let X=[fe,g].filter(ee=>ee>=0);pe.push(new po({id:"writers-rowmark",data:X,getPolygon:ee=>[[U-1e5,ee],[H+1e5,ee],[H+1e5,ee+1],[U-1e5,ee+1]],getFillColor:ee=>ee===fe?[167,139,250,38]:[255,255,255,18],updateTriggers:{getFillColor:[fe]}}))}if(h&&h.kind==="lane"&&h.lane!=null){let ee=[...e.lanes[h.lane].sessions].map(_e=>e.sessions[_e]);pe.push(new Ag({id:"writers-runs",data:ee,getSourcePosition:_e=>[e.xOf(_e.first),fe+.5],getTargetPosition:_e=>[e.xOf(_e.last)+1/120,fe+.5],getColor:[205,198,245,150],getWidth:5,widthUnits:"pixels"}))}return pe.push(new yf({id:"writers-events",data:{length:e.n,attributes:{getPosition:{value:e.positions,size:2},getFillColor:{value:e.colors,size:4,normalized:!0}}},radiusUnits:"pixels",getRadius:1.7,radiusMinPixels:1.2,pickable:!0,stroked:!1,updateTriggers:{getPosition:e.version,getFillColor:e.version}})),p.length&&pe.push(new yf({id:"writers-highlight",data:p,getPosition:X=>[e.positions[2*X],e.positions[2*X+1]],radiusUnits:"pixels",getRadius:p.length>400?2.4:4.5,stroked:!0,filled:!1,lineWidthUnits:"pixels",getLineWidth:1.4,getLineColor:[255,255,255,230],updateTriggers:{getPosition:e.version}})),pe}function M({layer:O,index:U,coordinate:H,viewport:xe}){if(O&&O.id==="writers-events"&&U>=0){let pe=U,fe=e.lanes[e.lane[pe]],X=new Date(e.t[pe]*1e3);return{html:`<div class="atl-tip"><b>${Fg(Qe(e.types[e.type[pe]]).label)}</b><br>${Fg(nn(fe.key,f))}<br><span>${X.toLocaleString([],{month:"short",day:"numeric",hour:"2-digit",minute:"2-digit",second:"2-digit"})}</span></div>`,style:{background:"transparent",padding:"0",boxShadow:"none"}}}return null}let I=new $m({parent:i,width:"100%",height:"100%",views:w,viewState:_,controller:!0,pickingRadius:5,layerFilter:({layer:O,viewport:U})=>O.id.startsWith(U.id),getTooltip:M,onViewStateChange:({viewId:O,viewState:U})=>(O==="writers"&&A(U),_[O]),onHover:O=>{let U=O.viewport&&O.viewport.id==="writers"&&O.coordinate?Math.floor(O.coordinate[1]):-1,H=U>=0&&U<e.lanes.length?U:-1;H!==g&&(g=H,V())},onClick:(O,U)=>{if(O.viewport)if(O.viewport.id==="writers"){if(O.layer&&O.layer.id==="writers-events"&&O.index>=0)t.onEvent(O.index);else if(O.coordinate){let H=Math.floor(O.coordinate[1]);H>=0&&H<e.lanes.length&&t.onLane(e.laneAtRow[H])}}else O.viewport.id==="activity"&&U&&U.tapCount===2&&rn()},onDragStart:O=>{O.viewport&&O.viewport.id==="activity"&&O.coordinate&&(m=[O.coordinate[0],O.coordinate[0]],V())},onDrag:O=>{m&&O.coordinate&&(m=[m[0],O.coordinate[0]],V())},onDragEnd:()=>{if(!m)return;let[O,U]=m[0]<m[1]?m:[m[1],m[0]];m=null,U-O>1/60?Pr(O,U):V()}});function R(){let O=S(),H=_.writers.target[1]-v()/2/O,xe=Math.max(0,Math.floor(H)),pe=Math.min(e.lanes.length-1,Math.ceil(H+v()/O)),fe=O>=11?1:Math.ceil(11/O),X=[];for(let ee=xe;ee<=pe;ee++){if(ee%fe!==0)continue;let _e=e.lanes[e.laneAtRow[ee]];if(!_e)continue;let Le=(ee-H)*O+O/2,ae=h&&h.laneRow===ee;X.push(`<div class="atl-label${ae?" is-sel":""}" data-row="${ee}" style="top:${Le.toFixed(1)}px">${Fg(nn(_e.key,f))}<span>${_e.count.toLocaleString()}</span></div>`)}o.innerHTML=X.join("")}function k(){let[O,U]=E(),H=(U-O)/x(),xe=Ng.find(ae=>ae/H>=90)||Ng[Ng.length-1],pe=[],fe=e.epochOf(O),X=e.epochOf(U),ee=xe*3600,_e=new Date(fe*1e3);_e.setHours(0,0,0,0);let Le=_e.getTime()/1e3;for(;Le<fe;)Le+=ee;for(let ae=0;Le<=X&&ae<200;Le+=ee,ae++){let Ke=(e.xOf(Le)-O)/H,Ne=new Date(Le*1e3),Tr=xe>=mo||Ne.getHours()===0&&Ne.getMinutes()===0?Ne.toLocaleDateString([],{month:"short",day:"numeric"}):Ne.toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"});pe.push(`<div class="atl-tick" style="left:${Ke.toFixed(1)}px">${Tr}</div>`)}s.innerHTML=pe.join("")}u.addEventListener("click",()=>rn()),o.addEventListener("click",O=>{let U=O.target.closest(".atl-label");U&&t.onLane(e.laneAtRow[+U.dataset.row])});let W=0;function V(){W||(W=requestAnimationFrame(()=>{W=0,I.setProps({viewState:_,layers:[...B(),...L()]}),R(),k(),ue()}))}function ue(){let[O,U]=E(),[H,xe]=e.extentX(),pe=O<=H+1e-6&&U>=xe-1e-6,fe=X=>new Date(e.epochOf(X)*1e3).toLocaleString([],{month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"});l.textContent=fe(Math.max(O,H))+" \u2192 "+fe(Math.min(U,xe)),u.style.visibility=pe?"hidden":"visible"}function Pr(O,U){let H=Math.log2(x()/Math.max(.016666666666666666,U-O));A({..._.writers,target:[(O+U)/2,_.writers.target[1],0],zoomX:H})}function rn(){let[O,U]=e.extentX();A({..._.writers,target:[(O+U)/2,0,0],zoomX:-1/0})}let ei=new ResizeObserver(()=>{y={w:r.clientWidth,h:r.clientHeight},A(_.writers)});return ei.observe(r),{fitAll:rn,zoomTo:Pr,modelChanged(){A(_.writers)},setCronNames(O){f=O||{},V()},setSelection(O,U){h=O,p=U||[],V()},focusEvent(O){let U=e.positions[2*O],H=e.positions[2*O+1],xe=Math.max(_.writers.zoomX,Math.log2(x()/24));A({..._.writers,target:[U,H,0],zoomX:xe})},focusRow(O){A({..._.writers,target:[_.writers.target[0],O+.5,0]})},destroy(){ei.disconnect(),W&&cancelAnimationFrame(W),I.finalize(),n.remove()}}}function Fg(r){return String(r??"").replace(/[&<>"']/g,e=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[e])}var{useState:qS,useEffect:c6}=ja,l6={active:"success",superseded:"outline",draft:"warning",retracted:"destructive",forgotten:"destructive"},XS={fact:"Fact",note:"Note",episode:"Episode",reference:"Reference",procedure:"Procedure",entity:"Entity",relationship:"Relationship"};function ZS({status:r}){let e=jg.Badge;return P(e,{tone:l6[r]||"outline"},r==="superseded"?"replaced":r==="draft"?"pending review":r||"active")}function ar({title:r,children:e,count:t}){return P("div",{className:"atl-sec"},P("div",{className:"atl-sec-t"},r,t!=null?P("span",{className:"chr-num"}," "+re(t)):null),e)}function tn({b:r,onBelief:e}){return r?P("button",{className:"atl-row",onClick:()=>e(r.belief_id)},P("span",{className:"atl-row-k"},XS[r.kind]||r.kind,r.label?" \xB7 "+r.label:""),P("span",{className:"atl-row-x"},r.text||"(empty)"),P("span",{className:"atl-row-m"},P(ZS,{status:r.status}),r.created_at?" "+Ye(r.created_at):"")):null}function go(r){let[e,t]=qS({loading:!0,data:null,error:null});return c6(()=>{let n=!0;return t({loading:!0,data:null,error:null}),lr(r).then(i=>n&&t({loading:!1,data:i,error:i&&i.error?i.error:null})).catch(i=>n&&t({loading:!1,data:null,error:i&&i.message||"failed"})),()=>{n=!1}},[r]),e}function yo({state:r,children:e}){return r.loading?P("div",{className:"chr-quiet atl-pad"},"Loading\u2026"):r.error?P("div",{className:"chr-err"},r.error):r.data&&r.data.found===!1?P("div",{className:"chr-quiet atl-pad"},"Not found in the store."):e(r.data)}function KS({sel:r,model:e,cronNames:t,onBelief:n,onEventSeq:i,onSession:o,onLane:s}){return r?r.kind==="event"?P(u6,{seq:r.seq,model:e,cronNames:t,onBelief:n,onEventSeq:i,onSession:o,onLane:s}):r.kind==="session"?P(f6,{id:r.id,model:e,cronNames:t,onBelief:n,onEventSeq:i,onLane:s}):r.kind==="belief"?P(d6,{id:r.id,onBelief:n,onEventSeq:i,onSession:o}):r.kind==="lane"?P(h6,{lane:r.lane,model:e,cronNames:t,onSession:o}):null:P("div",{className:"atl-pad chr-quiet"},P("p",null,"Every point is one event in the log, on the row of whatever wrote it: a cron job, a chat session, or a background process."),P("p",null,"Click a point, a row label, or anything in the lists below to see where it came from and what memory it produced. Drag across the chart above to zoom to a time range; double-click it to see everything."))}function u6({seq:r,model:e,cronNames:t,onBelief:n,onEventSeq:i,onSession:o,onLane:s}){let a=go(He+"/atlas/event?seq="+r);return P(yo,{state:a},c=>{let l=Qe(c.type),u=e.laneIx.get(c.lane);return P("div",null,P("div",{className:"atl-head"},P("span",{className:"chr-mark",style:{background:"rgb("+l.color.join(",")+")"}}),P("span",null,l.label),P("span",{className:"chr-quiet"}," \xB7 "+c.actor+" \xB7 "+Ye(c.recorded_at))),P("div",{className:"atl-text"},c.text||P("span",{className:"chr-quiet"},"This event carries no readable text.")),P("div",{className:"atl-links"},u!=null?P("button",{className:"atl-link",onClick:()=>s(u)},nn(c.lane,t)):null,c.session_id?P("button",{className:"atl-link",onClick:()=>o(c.session_id)},"Open this run"):null),c.source?P(ar,{title:"Extracted from"},P("button",{className:"atl-row",onClick:()=>i(c.source.seq)},P("span",{className:"atl-row-k"},Qe(c.source.type).label+" \xB7 "+c.source.actor),P("span",{className:"atl-row-x"},c.source.text||"\u2014"),P("span",{className:"atl-row-m"},Ye(c.source.recorded_at)))):null,c.source_beliefs&&c.source_beliefs.length?P(ar,{title:"Memory extracted from that turn",count:c.source_beliefs.length},c.source_beliefs.map(f=>P(tn,{key:f.belief_id,b:f,onBelief:n}))):null,c.beliefs.length||!c.source?P(ar,{title:"Memory citing this event",count:c.beliefs.length},c.beliefs.length?c.beliefs.map(f=>P(tn,{key:f.belief_id,b:f,onBelief:n})):P("div",{className:"chr-quiet"},"No belief cites this event.")):null)})}function f6({id:r,model:e,cronNames:t,onBelief:n,onEventSeq:i,onLane:o}){let s=go(He+"/atlas/session?id="+encodeURIComponent(r));return P(yo,{state:s},a=>{let c=e.laneIx.get(a.lane);return P("div",null,P("div",{className:"atl-head"},P("span",null,nn(a.lane,t)),P("span",{className:"chr-quiet"}," \xB7 "+re(a.events)+" events \xB7 "+Ye(a.first_at))),c!=null?P("div",{className:"atl-links"},P("button",{className:"atl-link",onClick:()=>o(c)},"All runs of this writer")):null,a.summary?P("div",{className:"atl-text"},a.summary):null,P("div",{className:"atl-chips"},Object.entries(a.types).map(([l,u])=>P("span",{key:l,className:"atl-chip"},Qe(l).label+" "+re(u)))),P(ar,{title:"Memory formed from this run",count:a.beliefs.length},a.beliefs.length?a.beliefs.map(l=>P(tn,{key:l.belief_id,b:l,onBelief:n})):P("div",{className:"chr-quiet"},"No belief cites this run.")),P(ar,{title:a.events>a.turns.length?"First "+a.turns.length+" events":"Events",count:a.events},a.turns.map(l=>P("button",{key:l.seq,className:"atl-row",onClick:()=>i(l.seq)},P("span",{className:"atl-row-k"},Qe(l.type).label+" \xB7 "+l.actor),P("span",{className:"atl-row-x"},l.text||"\u2014"),P("span",{className:"atl-row-m"},Ye(l.recorded_at))))))})}function d6({id:r,onBelief:e,onEventSeq:t,onSession:n}){let i=go(He+"/atlas/belief?id="+encodeURIComponent(r));return P(yo,{state:i},o=>P("div",null,P("div",{className:"atl-head"},P("span",null,(XS[o.kind]||o.kind)+(o.label?" \xB7 "+o.label:"")),P(ZS,{status:o.status})),o.entity_name?P("div",{className:"chr-quiet"},"About: "+o.entity_name):null,P("div",{className:"atl-text"},o.text||"(empty)"),P("div",{className:"atl-facts"},o.confidence!=null?P("span",null,"Confidence "+Number(o.confidence).toFixed(2)):null,o.created_at?P("span",null,"Written "+Ye(o.created_at)):null,o.valid_until?P("span",null,"Held until "+Ye(o.valid_until)):null,o.provenance&&o.provenance.sightings>1?P("span",null,"Seen "+re(o.provenance.sightings)+" times"):null,o.identical_active>1?P("span",{className:"atl-warn"},re(o.identical_active)+" identical active copies"):null),o.replaced.length?P(ar,{title:"Replaced"},o.replaced.map(s=>P(tn,{key:s.belief_id,b:s,onBelief:e}))):null,o.replaced_by.length?P(ar,{title:"Replaced by"},o.replaced_by.map(s=>P(tn,{key:s.belief_id,b:s,onBelief:e}))):null,o.contradictions.length?P(ar,{title:"Contradicted by",count:o.contradictions.length},o.contradictions.map(s=>P("div",{key:s.id},P(tn,{b:s.other,onBelief:e}),s.detail?P("div",{className:"chr-quiet atl-sub"},s.detail+" \xB7 "+s.status):null))):null,P(ar,{title:"Where it came from",count:o.supports_total},o.supports.length?o.supports.map(s=>P("button",{key:s.seq,className:"atl-row",onClick:()=>t(s.seq)},P("span",{className:"atl-row-k"},Qe(s.type).label+" \xB7 "+s.actor+(s.rule?" \xB7 "+s.rule:"")),P("span",{className:"atl-row-x"},s.text||"\u2014"),P("span",{className:"atl-row-m"},Ye(s.recorded_at),s.session_id?" ":null,s.session_id?P("a",{className:"atl-inline",onClick:a=>{a.stopPropagation(),n(s.session_id)}},"run"):null))):P("div",{className:"chr-quiet"},"No event in the log is cited as this belief's source."))))}function h6({lane:r,model:e,cronNames:t,onSession:n}){let i=e.lanes[r];if(!i)return null;let o=[...i.sessions].map(a=>e.sessions[a]).sort((a,c)=>c.first-a.first),s=new Map;for(let a=0;a<e.n;a++)if(e.lane[a]===r){let c=e.types[e.type[a]];s.set(c,(s.get(c)||0)+1)}return P("div",null,P("div",{className:"atl-head"},P("span",null,nn(i.key,t))),P("div",{className:"atl-facts"},P("span",null,re(i.count)+" events"),o.length?P("span",null,re(o.length)+" runs"):null,P("span",null,Ye(i.first)+" \u2192 "+Ye(i.last))),P("div",{className:"atl-chips"},[...s.entries()].sort((a,c)=>c[1]-a[1]).map(([a,c])=>P("span",{key:a,className:"atl-chip"},Qe(a).label+" "+re(c)))),o.length?P(ar,{title:o.length>60?"Latest 60 runs":"Runs",count:o.length},o.slice(0,60).map(a=>P("button",{key:a.id,className:"atl-row",onClick:()=>n(a.id)},P("span",{className:"atl-row-x"},Ye(a.first)),P("span",{className:"atl-row-m"},re(a.count)+" events")))):null)}function QS({model:r,onBelief:e}){let[t,n]=qS("contradictions");return P("div",{className:"atl-lenses"},P("div",{className:"chr-tabs",role:"tablist"},[["contradictions","Contradictions"],["histories","Replaced facts"],["duplicates","Duplicate notes"]].map(([o,s])=>P("button",{key:o,className:"chr-tab",role:"tab","aria-selected":t===o,onClick:()=>n(o)},s))),t==="contradictions"?P(p6,{onBelief:e}):t==="histories"?P(m6,{model:r,onBelief:e}):P(g6,{onBelief:e}))}function p6({onBelief:r}){let e=go(He+"/atlas/contradictions?limit=100");return P(yo,{state:e},t=>P("div",{className:"atl-lens"},P("div",{className:"chr-quiet atl-pad-s"},re(t.total)+" open. Pairs of beliefs the store holds that cannot both be true; newest first."),t.items.map(n=>P("div",{key:n.id,className:"atl-pair"},P(tn,{b:n.a,onBelief:r}),P("div",{className:"atl-vs"},"vs"),P(tn,{b:n.b,onBelief:r})))))}function m6({model:r,onBelief:e}){let t=go(He+"/atlas/histories?limit=100");return P(yo,{state:t},n=>{let[i,o]=r.extentX(),s=Math.max(1e-6,o-i),a=c=>{let l=Date.parse(c)/1e3;return isFinite(l)?Math.max(0,Math.min(1,(r.xOf(l)-i)/s)):null};return P("div",{className:"atl-lens"},P("div",{className:"chr-quiet atl-pad-s"},re(n.total)+" facts whose value changed. Each bar spans the whole log; each segment is one value, from when it was written until the next."),n.items.map(c=>P("div",{key:c.entity_id+"/"+c.predicate,className:"atl-hist"},P("div",{className:"atl-hist-l"},c.entity+" \xB7 "+c.predicate),P("div",{className:"atl-hist-bar"},c.versions.map((l,u)=>{let f=a(l.created_at),h=c.versions[u+1],p=h?a(h.created_at):1;return f==null?null:P("button",{key:l.belief_id,title:l.value+" ("+l.status+")",className:"atl-seg atl-seg-"+(l.status||"active"),style:{left:(f*100).toFixed(3)+"%",width:Math.max(.4,((p??1)-f)*100).toFixed(3)+"%"},onClick:()=>e(l.belief_id)})})),P("div",{className:"atl-hist-v"},c.versions.map(l=>l.value).join(" \u2192 ")))))})}function g6({onBelief:r}){let e=go(He+"/atlas/duplicates?limit=50");return P(yo,{state:e},t=>{let n=t.items.length?t.items[0].copies:1;return P("div",{className:"atl-lens"},P("div",{className:"chr-quiet atl-pad-s"},re(t.redundant)+" extra copies across "+re(t.groups)+" notes stored more than once with identical text. New repeats merge; these predate that."),t.items.map(i=>P("button",{key:i.example_id,className:"atl-row atl-dup",onClick:()=>r(i.example_id)},P("span",{className:"atl-dup-n chr-num"},re(i.copies)+"\xD7"),P("span",{className:"atl-dup-bar"},P("span",{style:{width:(i.copies/n*100).toFixed(1)+"%"}})),P("span",{className:"atl-row-x"},i.text),P("span",{className:"atl-row-m"},i.subject+" \xB7 "+Ye(i.first_at)+" \u2192 "+Ye(i.last_at)))))})}var{useState:Jn,useEffect:Cf,useRef:Mf,useCallback:Va}=ja,y6=1e4,_6=6e4;function b6(){if(Hg(),document.getElementById("atl-css"))return;let r=document.createElement("style");r.id="atl-css",r.textContent=[".atl{display:flex;flex-direction:column;gap:.75rem}",".atl-stats{display:flex;flex-wrap:wrap;align-items:baseline;gap:.35rem 1.1rem;font-size:.8rem;color:var(--muted)}",".atl-stats b{color:var(--tx);font-weight:500;font-variant-numeric:tabular-nums}",".atl-live{margin-left:auto;display:flex;align-items:center;gap:.4rem}",".atl-dot{width:.45rem;height:.45rem;border-radius:9999px;background:var(--ok)}",".atl-dot.is-off{background:var(--muted)}",".atl-body{display:grid;grid-template-columns:minmax(0,1fr) 370px;gap:.75rem;align-items:start}",".atl-main{display:flex;flex-direction:column;gap:.6rem;min-width:0}",".atl-canvas{position:relative;height:560px;border:1px solid var(--bd);border-radius:.6rem;background:var(--panel);overflow:hidden}",".atl-canvas-root,.atl-deck{position:absolute;inset:0}",".atl-labels{position:absolute;left:0;bottom:0;overflow:hidden;border-right:1px solid var(--bd);pointer-events:auto}",".atl-label{position:absolute;left:0;right:0;transform:translateY(-50%);display:flex;gap:.4rem;align-items:center;padding:0 .55rem;font-size:.7rem;line-height:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;cursor:pointer;color:var(--tx)}",".atl-label span{margin-left:auto;color:var(--muted);font-variant-numeric:tabular-nums;font-size:.64rem}",".atl-label:hover,.atl-label.is-sel{color:var(--accent)}",".atl-axis{position:absolute;right:0;border-top:1px solid var(--bd);border-bottom:1px solid var(--bd);pointer-events:none}",".atl-tick{position:absolute;top:4px;transform:translateX(-50%);font-size:.66rem;color:var(--muted);white-space:nowrap}",".atl-bar{position:absolute;top:.35rem;right:.6rem;display:flex;gap:.7rem;align-items:center;font-size:.7rem;color:var(--muted);pointer-events:auto;background:rgba(10,10,20,.6);border-radius:.3rem;padding:.1rem .4rem;z-index:2}",".atl-actlabel{position:absolute;left:0;top:0;display:flex;align-items:flex-end;padding:.5rem .55rem;font-size:.7rem;color:var(--muted);border-right:1px solid var(--bd);pointer-events:none}",".atl-tip{background:#12121f;border:1px solid var(--bd2);border-radius:.4rem;padding:.35rem .5rem;font-size:.72rem;color:#e7e5f1;line-height:1.35}",".atl-tip span{color:#9b97b8}",".atl-legend{display:flex;flex-wrap:wrap;gap:.3rem .9rem;font-size:.72rem;color:var(--muted)}",".atl-legend i{display:inline-block;width:.55rem;height:.55rem;border-radius:9999px;margin-right:.3rem;vertical-align:-1px}",".atl-progress{position:absolute;inset:auto 0 0 0;padding:.4rem .7rem;font-size:.72rem;color:var(--muted);background:linear-gradient(transparent,rgba(10,10,20,.85))}",".atl-side{border:1px solid var(--bd);border-radius:.6rem;background:var(--panel);max-height:calc(560px + 18rem);overflow:auto;padding:.7rem .8rem;position:sticky;top:.5rem}",".atl-pad{padding:.5rem .2rem}.atl-pad-s{padding:.35rem 0 .5rem}",".atl-pad p{margin:0 0 .6rem;font-size:.8rem;line-height:1.45}",".atl-head{display:flex;flex-wrap:wrap;align-items:center;gap:.4rem;font-size:.9rem;margin-bottom:.45rem}",".atl-text{font-size:.82rem;line-height:1.45;white-space:pre-wrap;word-break:break-word;background:var(--panel2);border-radius:.4rem;padding:.5rem .6rem;margin:.4rem 0}",".atl-links{display:flex;flex-wrap:wrap;gap:.4rem;margin:.3rem 0}",".atl-link,.atl-inline{background:none;border:0;padding:0;color:var(--accent);font-size:.76rem;cursor:pointer;text-decoration:underline;text-underline-offset:2px}",".atl-facts{display:flex;flex-wrap:wrap;gap:.25rem .8rem;font-size:.74rem;color:var(--muted);margin:.3rem 0}",".atl-warn{color:var(--warn)}",".atl-chips{display:flex;flex-wrap:wrap;gap:.3rem;margin:.4rem 0}",".atl-chip{font-size:.68rem;background:var(--panel2);border-radius:9999px;padding:.1rem .45rem;font-variant-numeric:tabular-nums}",".atl-sec{margin-top:.75rem}",".atl-sec-t{font-size:.72rem;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin-bottom:.3rem}",".atl-row{display:grid;grid-template-columns:1fr auto;gap:.1rem .5rem;width:100%;text-align:left;background:none;border:0;border-top:1px solid var(--bd);padding:.4rem .15rem;color:var(--tx);cursor:pointer}",".atl-row:hover{background:var(--panel2)}",".atl-row-k{grid-column:1/2;font-size:.68rem;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",".atl-row-m{grid-column:2/3;grid-row:1/2;font-size:.68rem;color:var(--muted);white-space:nowrap;text-align:right}",".atl-row-x{grid-column:1/3;font-size:.78rem;line-height:1.35;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}",".atl-sub{font-size:.7rem;padding:0 .15rem .3rem}",".atl-lenses{border:1px solid var(--bd);border-radius:.6rem;background:var(--panel);padding:.2rem .7rem .7rem}",".atl-lens{max-height:22rem;overflow:auto}",".atl-pair{display:grid;grid-template-columns:1fr auto 1fr;gap:.5rem;align-items:start;border-top:1px solid var(--bd);padding:.25rem 0}",".atl-pair .atl-row{border-top:0}",".atl-vs{font-size:.66rem;color:var(--danger);padding-top:.55rem}",".atl-hist{display:grid;grid-template-columns:14rem 1fr;gap:.2rem .7rem;align-items:center;border-top:1px solid var(--bd);padding:.4rem 0}",".atl-hist-l{font-size:.74rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",".atl-hist-bar{position:relative;height:.7rem;background:var(--panel2);border-radius:3px}",".atl-seg{position:absolute;top:0;bottom:0;border:0;padding:0;border-radius:2px;cursor:pointer;background:var(--muted);opacity:.55}",".atl-seg-active{background:var(--ok);opacity:1}.atl-seg-draft{background:var(--warn);opacity:.9}",".atl-seg:hover{outline:1px solid #fff}",".atl-hist-v{grid-column:2/3;font-size:.7rem;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",".atl-dup{grid-template-columns:3.2rem 6rem 1fr auto}",".atl-dup .atl-row-x{grid-column:3/4;-webkit-line-clamp:1}",".atl-dup .atl-row-m{grid-column:4/5}",".atl-dup-n{font-size:.78rem;align-self:center}",".atl-dup-bar{align-self:center;height:.35rem;background:var(--panel2);border-radius:9999px;overflow:hidden}",".atl-dup-bar span{display:block;height:100%;background:var(--warn)}","@media(max-width:1100px){.atl-body{grid-template-columns:1fr}.atl-side{position:static;max-height:none}}"].join(""),document.head.appendChild(r)}function x6(){let r=Mf(null),e=Mf(null),t=Mf(null),[n,i]=Jn(null),[o,s]=Jn({loaded:0,total:0,done:!1}),[a,c]=Jn(null),[l,u]=Jn({}),[f,h]=Jn(null),[p,m]=Jn({ok:!1,at:null}),[,g]=Jn(0);Cf(()=>{b6()},[]),Cf(()=>{let M=!1,I=new Ha;e.current=I;let R={aborted:!1};return lr(He+"/atlas/lanes").then(k=>!M&&u(k.cron_names||{})).catch(()=>{}),lr(He+"/atlas/summary").then(async k=>{if(M)return;if(k.error)throw new Error(k.error);i(k);let W=!1;await Yg(I,k.events,(V,ue)=>{M||(!W&&V?(I.orderLanes(!1),t.current=Ug(r.current,I,x.current),t.current.fitAll(),W=!0):W&&(I.orderLanes(!1),t.current.modelChanged(),t.current.fitAll()),s({loaded:V,total:ue,done:!1}))},R),!M&&(I.orderLanes(!1),!t.current&&I.n&&(t.current=Ug(r.current,I,x.current)),t.current&&(t.current.modelChanged(),t.current.fitAll()),s({loaded:I.n,total:I.n,done:!0}),m({ok:!0,at:Date.now()}))}).catch(k=>!M&&c(k&&k.message||"failed to load")),()=>{M=!0,R.aborted=!0,t.current&&t.current.destroy(),t.current=null}},[]),Cf(()=>{t.current&&t.current.setCronNames(l)},[l,o.done]),Cf(()=>{if(!o.done)return;let M=()=>{document.visibilityState!=="visible"||!e.current||qg(e.current).then(V=>{V&&t.current&&t.current.modelChanged(),m({ok:!0,at:Date.now()})}).catch(()=>m(V=>({ok:!1,at:V.at})))},I=()=>{document.visibilityState==="visible"&&lr(He+"/atlas/summary").then(V=>{V.error||i(V)}).catch(()=>{})},R=setInterval(M,y6),k=setInterval(I,_6),W=setInterval(()=>g(V=>V+1),15e3);return()=>{clearInterval(R),clearInterval(k),clearInterval(W)}},[o.done]);let y=Va(M=>{h(M);let I=e.current,R=t.current;if(!I||!R||!M){R&&R.setSelection(null,[]);return}if(M.kind==="event"){let k=I.indexOfSeq(M.seq),W=k>=0?I.rowOfLane[I.lane[k]]:null;R.setSelection({...M,laneRow:W},k>=0?[k]:[]),k>=0&&M.focus&&R.focusEvent(k)}else if(M.kind==="session"){let k=I.sessionIx.get(M.id),W=k==null?[]:I.indicesWhere(ue=>I.session[ue]===k,5e3),V=k==null?null:I.rowOfLane[I.sessions[k].lane];R.setSelection({...M,laneRow:V},W),W.length&&R.focusEvent(W[0])}else if(M.kind==="lane"){let k=I.rowOfLane[M.lane];R.setSelection({...M,laneRow:k},[]),R.focusRow(k)}else R.setSelection({...M,laneRow:null},[])},[]),x=Mf(null);x.current={onEvent:M=>y({kind:"event",seq:e.current.seq[M]}),onLane:M=>y({kind:"lane",lane:M})};let v=Va(M=>y({kind:"belief",id:M}),[y]),_=Va(M=>y({kind:"event",seq:M,focus:!0}),[y]),w=Va(M=>y({kind:"session",id:M}),[y]),E=Va(M=>y({kind:"lane",lane:M}),[y]);if(a)return P("div",{className:"chr-err"},"The Atlas could not read the store: "+a);let S=e.current,C=n&&n.beliefs||{},A=C.fact||{},B=C.note||{},L=S&&S.types.length?S.types:[];return P("div",{className:"atl"},P("div",{className:"atl-stats"},n?[P("span",{key:"e"},P("b",null,re(n.events))," events"),S&&o.done?P("span",{key:"w"},P("b",null,re(S.lanes.length))," writers"):null,P("span",{key:"f"},P("b",null,re(A.active))," facts in force"),A.superseded?P("span",{key:"fs"},P("b",null,re(A.superseded))," replaced"):null,A.draft?P("span",{key:"fd"},P("b",null,re(A.draft))," pending review"):null,P("span",{key:"n"},P("b",null,re(B.active))," notes"),P("span",{key:"c"},P("b",null,re(n.contradictions_open))," open contradictions")]:P("span",null,"Reading the store\u2026"),P("span",{className:"atl-live"},P("span",{className:"atl-dot"+(p.ok?"":" is-off")}),o.done?p.ok?"Live \xB7 checked "+If(new Date(p.at).toISOString()):"Not updating \xB7 last checked "+If(p.at?new Date(p.at).toISOString():null):"Loading")),P("div",{className:"atl-body"},P("div",{className:"atl-main"},P("div",{className:"atl-canvas",ref:r},o.done?null:P("div",{className:"atl-progress"},o.total?"Loaded "+re(o.loaded)+" of "+re(o.total)+" events":"Loading events\u2026")),P("div",{className:"atl-legend"},L.map(M=>{let I=Qe(M);return P("span",{key:M},P("i",{style:{background:"rgb("+I.color.join(",")+")"}}),I.label)})),S?P(QS,{model:S,onBelief:v}):null),P("div",{className:"atl-side"},S?P(KS,{sel:f,model:S,cronNames:l,onBelief:v,onEventSeq:_,onSession:w,onLane:E}):null)))}window.__CHRONICLE_ATLAS__={Atlas:x6};})();
