// Uses host frontend dependencies; never installs into or mutates Hermes.
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {createRequire} from 'node:module';
import fs from 'node:fs';
import {execFileSync,spawn} from 'node:child_process';
import readline from 'node:readline';
const pending = new Map();
let serial = 0;
const bridge = spawn(process.env.PULSE_BUILDER_PYTHON || 'python', ['-u', path.join(path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..'), 'scripts/builder-preview-bridge.py')], {stdio:['pipe','pipe','inherit']});
readline.createInterface({input:bridge.stdout}).on('line', line => {const out=JSON.parse(line); const handler=pending.get(out.id); pending.delete(out.id); if(out.error)handler?.reject(Error(out.error));else handler?.resolve(out.result);});
bridge.on('exit',()=>{for(const h of pending.values())h.reject(Error('Builder bridge stopped'));pending.clear();});
process.on('exit',()=>bridge.kill());
const pureCall = (route,body) => new Promise((resolve,reject)=>{const id=++serial;pending.set(id,{resolve,reject});bridge.stdin.write(JSON.stringify({id,path:route,body})+'\n');});
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const source=process.argv[2];
if(!source)throw new Error('Usage: node scripts/preview-server.mjs HERMES_SOURCE [PORT]');
// Newer Hermes checkouts keep the desktop's dependencies in apps/desktop; older ones at the root.
const moduleRoots=[source,path.join(source,'apps/desktop')];
const resolveModule=name=>{for(const base of moduleRoots){try{return createRequire(path.join(base,'package.json')).resolve(name);}catch{}}throw new Error(`Cannot find ${name} in ${moduleRoots.join(' or ')}`);};
const moduleDir=name=>moduleRoots.map(base=>path.join(base,'node_modules',name)).find(dir=>fs.existsSync(path.join(dir,'package.json')));
const {createServer}=await import(pathToFileURL(resolveModule('vite')).href);
const {default:tailwindcss}=await import(pathToFileURL(resolveModule('@tailwindcss/vite')).href);
const aliases=[{find:/^@\/i18n$/,replacement:path.join(root,'preview/host-inert-services.js')},{find:/^@\/lib\/keybinds\/use-keybind-hint$/,replacement:path.join(root,'preview/host-inert-services.js')},{find:'@hermes/plugin-sdk',replacement:path.join(root,'preview/sdk-mock.js')},{find:'@desktop-ui',replacement:path.join(source,'apps/desktop/src/components/ui')},{find:'@',replacement:path.join(source,'apps/desktop/src')}];
for(const name of ['react','react-dom','@tanstack/react-query','@radix-ui/react-tooltip','radix-ui']){const dir=moduleDir(name);if(dir)aliases.push({find:name,replacement:dir});}
const server=await createServer({root:path.join(root,'preview'),cacheDir:path.join(process.env.TMPDIR || process.env.TEMP,'pulse-rings-vite-'+(process.argv[3] || '5198')),resolve:{alias:aliases,dedupe:['react','react-dom']},server:{host:'127.0.0.1',port:Number(process.argv[3] || 5198),strictPort:true,fs:{allow:[root,source]}},plugins:[tailwindcss(),{name:'host-sdk-css',resolveId(id){if(id==='virtual:host-sdk-css')return path.join(source,'apps/desktop/src/styles.css');}},{name:'legacy-renderer-characterization',resolveId(id){if(id==='virtual:pulse-baseline')return '\0pulse-baseline';if(id==='virtual:pulse-builder-baseline')return '\0pulse-builder-baseline';},load(id){if(id==='\0pulse-baseline')return execFileSync('git',['show','3b04572:desktop/plugin.js'],{cwd:root,encoding:'utf8'});if(id==='\0pulse-builder-baseline')return execFileSync('git',['show','57434d7:desktop/plugin.js'],{cwd:root,encoding:'utf8'});}},{name:'recorded-fixture',configureServer(s){
  s.middlewares.use('/builder-mock',async(request,res)=>{try{let text='';for await(const chunk of request){text+=chunk;if(text.length>65536)throw Error('Body too large');}const input=JSON.parse(text);if(!['/layout-check','/builder/preview','/builder/templates','/builder/from-template','/builder/layouts','/brands','/catalog','/fixture-disclosure'].includes(input.path))throw Error('Not a pure route');const result=await pureCall(input.path,input.body);res.setHeader('Content-Type','application/json');res.end(JSON.stringify(result));}catch(e){res.statusCode=400;res.end(JSON.stringify({error:String(e)}));}});
  s.middlewares.use('/recorded-icons',(_req,res)=>{res.setHeader('Content-Type','application/json');res.end(JSON.stringify(Object.fromEntries(['nousresearch','nvidiadeveloper','typesafe','6EbMcWJHdb','ollama'].map(code=>[code,'data:image/png;base64,'+fs.readFileSync(path.join(root,'tests/fixtures/icons',code+'.png')).toString('base64')]))));});
  s.middlewares.use('/ui-fixture',(request,res)=>{const name=request.url.split('?')[0].replace(/^\//,'');if(!/^[a-z-]+$/.test(name)){res.statusCode=400;res.end();return;}const file=path.join(root,'tests/fixtures/ui',name+'.json');if(!fs.existsSync(file)){res.statusCode=404;res.end();return;}res.setHeader('Content-Type','application/json');res.end(fs.readFileSync(file));});
}}]});
await server.listen();console.log('Pulsr synthetic fixture preview '+server.resolvedUrls.local[0]);
