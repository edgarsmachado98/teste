// Acesso direto pela rede da fábrica: se este computador alcança o VigIA Edge e confia no certificado
// (CA do cliente instalada pela TI), imagem e clipe vêm direto do Edge; senão, pelo túnel da nuvem.

const memo = new Map(); // edge_id -> {base|null, at}
const RETRY_MS = 10 * 60 * 1000;

function remembered(edgeId) {
  const hit = memo.get(edgeId);
  if (hit && Date.now() - hit.at < RETRY_MS) return hit;
  try {
    const saved = JSON.parse(sessionStorage.getItem(`vigia-lan-${edgeId}`) || "null");
    if (saved && Date.now() - saved.at < RETRY_MS) return saved;
  } catch { /* sem storage */ }
  return null;
}

function remember(edgeId, base) {
  const value = { base, at: Date.now() };
  memo.set(edgeId, value);
  try { sessionStorage.setItem(`vigia-lan-${edgeId}`, JSON.stringify(value)); } catch { /* sem storage */ }
}

async function reachable(base) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 1500);
  try {
    const r = await fetch(`${base}/ping`, { signal: ctrl.signal, cache: "no-store" });
    return r.ok;
  } catch {
    return false; // fora da rede da fábrica, certificado não confiável ou Edge desligado
  } finally {
    clearTimeout(timer);
  }
}

/** Endereço do Edge alcançável por este computador, ou null (usar a nuvem). */
export async function directBase(direct) {
  if (!direct?.bases?.length) return null;
  const hit = remembered(direct.edge_id);
  if (hit) return hit.base;
  for (const base of direct.bases) {
    if (await reachable(base)) { remember(direct.edge_id, base); return base; }
  }
  remember(direct.edge_id, null);
  return null;
}

/** O link direto falhou na hora de carregar: esquece e volta para a nuvem. */
export function forgetDirect(direct) {
  if (direct?.edge_id) remember(direct.edge_id, null);
}
