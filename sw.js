var V="newsflash-v2";
var SHELL=["./","index.html","manifest.webmanifest","icon-192.png","icon-512.png","apple-touch-icon.png"];
self.addEventListener("install",function(e){e.waitUntil(caches.open(V).then(function(c){return c.addAll(SHELL)}));self.skipWaiting()});
self.addEventListener("activate",function(e){e.waitUntil(caches.keys().then(function(ks){return Promise.all(ks.filter(function(k){return k!==V}).map(function(k){return caches.delete(k)}))}).then(function(){return self.clients.claim()}))});
function save(r,res){var cp=res.clone();caches.open(V).then(function(c){c.put(r,cp)});return res}
self.addEventListener("fetch",function(e){
var r=e.request;if(r.method!=="GET")return;
var u=new URL(r.url);
if(u.origin===location.origin&&u.pathname.indexOf("/news/")!==-1){
e.respondWith(fetch(r).then(function(res){return save(r,res)}).catch(function(){return caches.match(r)}));return}
e.respondWith(caches.match(r).then(function(m){
var f=fetch(r).then(function(res){return res.ok||res.type==="opaque"?save(r,res):res}).catch(function(){return m||caches.match("index.html")});
return m||f}))});
