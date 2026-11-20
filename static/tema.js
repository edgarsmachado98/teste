// Botão de tema claro/escuro. A escolha fica salva neste navegador; sem escolha, segue o sistema.
(function () {
  const raiz = document.documentElement;
  const escuroDoSistema = () => window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches;
  const atual = () => raiz.dataset.theme || (escuroDoSistema() ? "dark" : "light");
  function rotular(btn) {
    const proximo = atual() === "dark" ? "claro" : "escuro";
    btn.title = `Mudar para o modo ${proximo}`;
    btn.setAttribute("aria-label", btn.title);
  }
  function iniciar() {
    const btn = document.getElementById("btn-tema");
    if (!btn) return;
    rotular(btn);
    btn.addEventListener("click", () => {
      const novo = atual() === "dark" ? "light" : "dark";
      raiz.dataset.theme = novo;
      try { localStorage.setItem("tema", novo); } catch (e) { /* navegador sem armazenamento */ }
      rotular(btn);
      document.dispatchEvent(new CustomEvent("tema-alterado", { detail: novo }));
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar);
  else iniciar();
})();
