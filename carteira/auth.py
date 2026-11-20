"""Usuários, carteiras e permissões de acesso.

Regras:
- Administradores veem e controlam todas as carteiras e gerenciam usuários.
- O dono de uma carteira tem todas as permissões sobre ela.
- Os demais usuários recebem, por carteira, as permissões:
    ver       -> visualizar a carteira (somente leitura)
    editar    -> controlar: registrar/excluir aportes, ativos e proventos
    gerenciar -> conceder/revogar acessos à carteira
  Controlar e gerenciar implicam visualizar.
"""
import re

from werkzeug.security import check_password_hash, generate_password_hash

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SENHA_MINIMA = 8
TODAS = {"ver": True, "editar": True, "gerenciar": True}
NENHUMA = {"ver": False, "editar": False, "gerenciar": False}


class ErroAcesso(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


def _validar_email(email):
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise ErroAcesso("E-mail inválido.")
    return email


def _validar_senha(senha):
    if len(senha or "") < SENHA_MINIMA:
        raise ErroAcesso(f"A senha deve ter pelo menos {SENHA_MINIMA} caracteres.")
    return senha


def publico(u):
    """Dados do usuário que podem ir para o navegador (sem hash de senha)."""
    if u is None:
        return None
    return {"id": u["id"], "email": u["email"], "nome": u["nome"],
            "admin": bool(u["admin"]), "ativo": bool(u["ativo"])}


# ------------------------------------------------------------------ usuários

def existe_usuario(conn):
    return conn.execute("SELECT 1 FROM usuarios LIMIT 1").fetchone() is not None


def obter_usuario(conn, uid):
    return conn.execute("SELECT * FROM usuarios WHERE id = ?", (uid,)).fetchone()


def usuario_por_email(conn, email):
    return conn.execute("SELECT * FROM usuarios WHERE email = ?", ((email or "").strip().lower(),)).fetchone()


def criar_usuario(conn, email, nome, senha, admin=False):
    email = _validar_email(email)
    nome = (nome or "").strip()
    if not nome:
        raise ErroAcesso("Nome é obrigatório.")
    _validar_senha(senha)
    if usuario_por_email(conn, email):
        raise ErroAcesso("Já existe um usuário com este e-mail.", 409)
    cur = conn.execute("INSERT INTO usuarios (email, nome, senha_hash, admin) VALUES (?, ?, ?, ?)",
                       (email, nome, generate_password_hash(senha), int(bool(admin))))
    return cur.lastrowid


def autenticar(conn, email, senha):
    u = usuario_por_email(conn, email)
    if u is None or not u["ativo"] or not check_password_hash(u["senha_hash"], senha or ""):
        return None
    return u


def alterar_senha(conn, uid, nova):
    _validar_senha(nova)
    conn.execute("UPDATE usuarios SET senha_hash = ? WHERE id = ?", (generate_password_hash(nova), uid))


def _total_admins_ativos(conn, exceto=None):
    return conn.execute("SELECT COUNT(*) FROM usuarios WHERE admin = 1 AND ativo = 1 AND id != ?",
                        (exceto or 0,)).fetchone()[0]


def atualizar_usuario(conn, uid, nome=None, admin=None, ativo=None):
    u = obter_usuario(conn, uid)
    if u is None:
        raise ErroAcesso("Usuário não encontrado.", 404)
    perde_admin = (admin is False or ativo is False) and u["admin"] and u["ativo"]
    if perde_admin and _total_admins_ativos(conn, exceto=uid) == 0:
        raise ErroAcesso("O sistema precisa de pelo menos um administrador ativo.", 409)
    conn.execute("UPDATE usuarios SET nome = ?, admin = ?, ativo = ? WHERE id = ?",
                 ((nome or u["nome"]).strip(), int(u["admin"] if admin is None else admin),
                  int(u["ativo"] if ativo is None else ativo), uid))


def listar_usuarios(conn):
    return [publico(u) for u in conn.execute("SELECT * FROM usuarios ORDER BY nome")]


# ----------------------------------------------------------------- carteiras

def criar_carteira(conn, nome, dono_id):
    nome = (nome or "").strip()
    if not nome:
        raise ErroAcesso("Nome da carteira é obrigatório.")
    if dono_id is not None and obter_usuario(conn, dono_id) is None:
        raise ErroAcesso("Dono não encontrado.", 404)
    return conn.execute("INSERT INTO carteiras (nome, dono_id) VALUES (?, ?)", (nome, dono_id)).lastrowid


def obter_carteira(conn, cid):
    return conn.execute("SELECT * FROM carteiras WHERE id = ?", (cid,)).fetchone()


def permissoes(conn, usuario, carteira_id):
    """Permissões efetivas de `usuario` (Row) sobre a carteira."""
    c = obter_carteira(conn, carteira_id)
    if c is None or usuario is None:
        return dict(NENHUMA)
    if usuario["admin"] or c["dono_id"] == usuario["id"]:
        return dict(TODAS)
    a = conn.execute("SELECT * FROM acessos WHERE carteira_id = ? AND usuario_id = ?",
                     (carteira_id, usuario["id"])).fetchone()
    if a is None:
        return dict(NENHUMA)
    editar, gerenciar = bool(a["pode_editar"]), bool(a["pode_gerenciar"])
    return {"ver": bool(a["pode_ver"]) or editar or gerenciar, "editar": editar, "gerenciar": gerenciar}


def carteiras_do_usuario(conn, usuario):
    """Carteiras que o usuário pode visualizar, com as permissões e o nome do dono."""
    linhas = conn.execute("""SELECT c.*, u.nome AS dono_nome, u.email AS dono_email
                             FROM carteiras c LEFT JOIN usuarios u ON u.id = c.dono_id
                             ORDER BY (c.dono_id = ?) DESC, c.nome""", (usuario["id"],)).fetchall()
    out = []
    for c in linhas:
        p = permissoes(conn, usuario, c["id"])
        if p["ver"]:
            out.append({"id": c["id"], "nome": c["nome"], "dono_id": c["dono_id"],
                        "dono_nome": c["dono_nome"], "dono_email": c["dono_email"],
                        "sou_dono": c["dono_id"] == usuario["id"], "permissoes": p})
    return out


def renomear_carteira(conn, cid, nome, dono_id=None, mudar_dono=False):
    nome = (nome or "").strip()
    if not nome:
        raise ErroAcesso("Nome da carteira é obrigatório.")
    if mudar_dono:
        if dono_id is not None and obter_usuario(conn, dono_id) is None:
            raise ErroAcesso("Dono não encontrado.", 404)
        conn.execute("UPDATE carteiras SET nome = ?, dono_id = ? WHERE id = ?", (nome, dono_id, cid))
        conn.execute("DELETE FROM acessos WHERE carteira_id = ? AND usuario_id = ?", (cid, dono_id or 0))
    else:
        conn.execute("UPDATE carteiras SET nome = ? WHERE id = ?", (nome, cid))


def excluir_carteira(conn, cid):
    usados = sum(conn.execute(f"SELECT COUNT(*) FROM {t} WHERE carteira_id = ?", (cid,)).fetchone()[0]
                 for t in ("aportes", "proventos"))
    if usados:
        raise ErroAcesso("A carteira possui aportes ou proventos; exclua-os antes de excluir a carteira.", 409)
    conn.execute("DELETE FROM ativos WHERE carteira_id = ?", (cid,))
    conn.execute("DELETE FROM acessos WHERE carteira_id = ?", (cid,))
    conn.execute("DELETE FROM carteiras WHERE id = ?", (cid,))


# ------------------------------------------------------------------ acessos

def listar_acessos(conn, cid):
    return [{"usuario_id": a["usuario_id"], "nome": a["nome"], "email": a["email"],
             "ver": bool(a["pode_ver"]) or bool(a["pode_editar"]) or bool(a["pode_gerenciar"]),
             "editar": bool(a["pode_editar"]), "gerenciar": bool(a["pode_gerenciar"])}
            for a in conn.execute("""SELECT a.*, u.nome, u.email FROM acessos a
                                     JOIN usuarios u ON u.id = a.usuario_id
                                     WHERE a.carteira_id = ? ORDER BY u.nome""", (cid,))]


def definir_acesso(conn, cid, email, ver=True, editar=False, gerenciar=False):
    u = usuario_por_email(conn, email)
    if u is None:
        raise ErroAcesso("Nenhum usuário cadastrado com este e-mail. Peça a um administrador para criá-lo.", 404)
    c = obter_carteira(conn, cid)
    if c["dono_id"] == u["id"]:
        raise ErroAcesso("O dono já tem acesso total à carteira.", 409)
    ver = bool(ver or editar or gerenciar)
    if not ver:
        conn.execute("DELETE FROM acessos WHERE carteira_id = ? AND usuario_id = ?", (cid, u["id"]))
        return u["id"]
    conn.execute("""INSERT INTO acessos (carteira_id, usuario_id, pode_ver, pode_editar, pode_gerenciar)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(carteira_id, usuario_id) DO UPDATE SET pode_ver = excluded.pode_ver,
                    pode_editar = excluded.pode_editar, pode_gerenciar = excluded.pode_gerenciar""",
                 (cid, u["id"], int(ver), int(bool(editar)), int(bool(gerenciar))))
    return u["id"]


def remover_acesso(conn, cid, uid):
    conn.execute("DELETE FROM acessos WHERE carteira_id = ? AND usuario_id = ?", (cid, uid))


def configuracao_inicial(conn, nome, email, senha, nome_carteira):
    """Cria o primeiro administrador e atribui a ele as carteiras sem dono (dados já existentes)."""
    if existe_usuario(conn):
        raise ErroAcesso("A configuração inicial já foi feita.", 409)
    uid = criar_usuario(conn, email, nome, senha, admin=True)
    sem_dono = [r["id"] for r in conn.execute("SELECT id FROM carteiras WHERE dono_id IS NULL ORDER BY id")]
    nome_carteira = (nome_carteira or "").strip() or f"Carteira {nome.strip()}"
    if sem_dono:
        conn.execute("UPDATE carteiras SET dono_id = ? WHERE dono_id IS NULL", (uid,))
        conn.execute("UPDATE carteiras SET nome = ? WHERE id = ?", (nome_carteira, sem_dono[0]))
        cid = sem_dono[0]
    else:
        cid = criar_carteira(conn, nome_carteira, uid)
    return uid, cid
