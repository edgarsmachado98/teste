/* Cliente da API do servidor. A sessão fica em cookie HttpOnly (não acessível ao JavaScript). */
(function () {
  'use strict';

  async function chamar(metodo, caminho, corpo) {
    const opcoes = {
      method: metodo,
      credentials: 'same-origin',
      headers: { 'X-Requested-With': 'escala' },
    };
    if (metodo !== 'GET') {
      opcoes.headers['Content-Type'] = 'application/json';
      opcoes.body = JSON.stringify(corpo === undefined ? {} : corpo);
    }
    let resp;
    try {
      resp = await fetch(caminho, opcoes);
    } catch (e) {
      throw Object.assign(new Error('Não foi possível conectar ao servidor. Verifique se ele está em execução.'), { status: 0 });
    }
    let dados = null;
    try { dados = await resp.json(); } catch (e) { /* resposta sem corpo JSON */ }
    if (!resp.ok) {
      const erro = Object.assign(new Error((dados && dados.erro) || `Erro ${resp.status} no servidor.`), { status: resp.status });
      // sessão expirada ou encerrada por um administrador
      if (resp.status === 401 && !/^\/api\/(login|primeiro-acesso|minha-senha)$/.test(caminho)) {
        window.dispatchEvent(new CustomEvent('sessao-expirada'));
      }
      throw erro;
    }
    return dados;
  }

  window.EscalaApi = {
    get: (c) => chamar('GET', c),
    post: (c, b) => chamar('POST', c, b),
    put: (c, b) => chamar('PUT', c, b),
    del: (c) => chamar('DELETE', c),
  };
})();
