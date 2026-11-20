/* Service worker: o app abre mesmo com a rede instável (dados sempre vêm do servidor). */
const CACHE = "carteira-v1";
const ESSENCIAIS = ["/static/style.css", "/static/app.js", "/static/vendor/chart.umd.min.js", "/static/icons/icon-192.png"];

self.addEventListener("install", ev => {
  ev.waitUntil(caches.open(CACHE).then(c => c.addAll(ESSENCIAIS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", ev => {
  ev.waitUntil(caches.keys().then(chaves => Promise.all(chaves.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", ev => {
  const url = new URL(ev.request.url);
  if (ev.request.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/auth/")) return;  // dados: sempre da rede
  // páginas e arquivos: rede primeiro (sempre a versão mais nova), cópia local se estiver sem conexão
  ev.respondWith(fetch(ev.request).then(resp => {
    if (resp.ok && url.pathname.startsWith("/static/")) {
      const copia = resp.clone();
      caches.open(CACHE).then(c => c.put(ev.request, copia));
    }
    return resp;
  }).catch(() => caches.match(ev.request).then(r => r || new Response(
    "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'><body style='font-family:system-ui;padding:2em'>" +
    "<h2>Sem conexão com o servidor</h2><p>Verifique se o computador com a Carteira de Aportes está ligado e conectado.</p>",
    { headers: { "Content-Type": "text/html; charset=utf-8" } }))));
});
