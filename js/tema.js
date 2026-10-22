/* Tema da interface: claro por padrão; o modo escuro fica guardado neste navegador.
   Carregado no <head> para aplicar o tema antes de a página aparecer. */
(function () {
  'use strict';
  const CHAVE = 'core-rh-tema';
  const raiz = document.documentElement;

  function ler() {
    try { return localStorage.getItem(CHAVE) === 'escuro' ? 'escuro' : 'claro'; } catch (e) { return 'claro'; }
  }
  function aplicar(tema) {
    raiz.dataset.theme = tema === 'escuro' ? 'dark' : 'light';
    const botao = document.getElementById('btn-tema');
    if (botao) {
      botao.textContent = tema === 'escuro' ? '☀ Modo claro' : '☾ Modo escuro';
      botao.setAttribute('aria-pressed', String(tema === 'escuro'));
    }
  }

  aplicar(ler());
  document.addEventListener('DOMContentLoaded', () => {
    aplicar(ler());
    document.getElementById('btn-tema').addEventListener('click', () => {
      const novo = raiz.dataset.theme === 'dark' ? 'claro' : 'escuro';
      try { localStorage.setItem(CHAVE, novo); } catch (e) { /* sem armazenamento: vale só nesta página */ }
      aplicar(novo);
    });
  });
})();
