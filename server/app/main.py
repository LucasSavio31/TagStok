"""TagStock — controle de estoque por RFID (servidor que roda no PC).

Iniciar:   uvicorn app.main:app --host 0.0.0.0 --port 8100
Tela PC:   http://localhost:8100        Coletor: http://IP-DO-PC:8100/m
API:       http://localhost:8100/docs   (integração com ERP: mesmo login, cabeçalho X-Token)
"""
import csv
import io
import os
import secrets
import sqlite3
from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db, epc as epc_mod, impressao, regras, remoto
from .regras import Ctx, ErroRegra

NOME_SERVIDOR = "TagStock"
STATIC = os.path.join(os.path.dirname(__file__), "static")
SEM_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}


@asynccontextmanager
async def iniciar(_app):
    db.inicializar()
    yield


app = FastAPI(title="TagStock RFID", lifespan=iniciar)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def ignorar_filtros_vazios(request: Request, chamar):
    """Filtro vazio da tela (?local_id=&grupo=) = sem filtro (senão o FastAPI recusa "" como número)."""
    qs = request.scope.get("query_string", b"")
    if qs:
        from urllib.parse import parse_qsl, urlencode
        request.scope["query_string"] = urlencode([(k, v) for k, v in parse_qsl(qs.decode("latin-1")) if v != ""]).encode("latin-1")
    return await chamar(request)


@app.exception_handler(ErroRegra)
def erro_regra(_req, exc):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(epc_mod.ErroEpc)
def erro_epc(_req, exc):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(impressao.ErroImpressao)
def erro_impressao(_req, exc):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(RequestValidationError)
def erro_validacao(_req, exc: RequestValidationError):
    e = exc.errors()[0]
    campo = ".".join(str(x) for x in e["loc"] if x not in ("body", "query"))
    return JSONResponse(status_code=400, content={"detail": f"Campo inválido: {campo} ({e['msg']})"})


def conexao(request: Request):
    """Uma conexão por requisição; grava no fim ou desfaz tudo se deu erro.
    Quem altera dados começa com BEGIN IMMEDIATE (uma gravação de cada vez, sem furar saldo)."""
    con = db.conectar()
    try:
        if request.method != "GET":
            con.execute("BEGIN IMMEDIATE")
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


Con = sqlite3.Connection


class Usuario(BaseModel):
    id: int
    login: str
    nome: str
    perfil: str


def usuario_logado(request: Request, x_token: Optional[str] = Header(None), token: Optional[str] = Query(None)) -> Usuario:
    t = x_token or token
    if not t:
        raise HTTPException(401, "Faça o login")
    con = db.conectar()
    try:
        r = con.execute("""SELECT u.id, u.login, u.nome, u.perfil FROM sessoes s JOIN usuarios u ON u.id=s.usuario_id
                           WHERE s.token=? AND u.ativo=1""", (t,)).fetchone()
    finally:
        con.close()
    if not r:
        raise HTTPException(401, "Sessão expirada: faça o login de novo")
    return Usuario(**dict(r))


def admin(u: Usuario = Depends(usuario_logado)) -> Usuario:
    if u.perfil != "ADMIN":
        raise HTTPException(403, "Só o administrador pode fazer isso")
    return u


def ctx(request: Request, u: Usuario = Depends(usuario_logado)) -> Ctx:
    origem = (request.headers.get("x-origem") or "PC").upper()
    return Ctx(origem=origem if origem in ("PC", "COLETOR", "API") else "API",
               dispositivo=request.headers.get("x-dispositivo"), usuario=u.login)


Logado = Depends(usuario_logado)


def csv_resposta(nome, colunas, linhas):
    saida = io.StringIO()
    saida.write("﻿")
    w = csv.writer(saida, delimiter=";")
    w.writerow([t for t, _ in colunas])
    for l in linhas:
        w.writerow([(str(l.get(c)).replace(".", ",") if isinstance(l.get(c), float) else ("" if l.get(c) is None else l.get(c)))
                    for _, c in colunas])
    return StreamingResponse(iter([saida.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{nome}"'})


# ================================================================ telas e status
@app.get("/", include_in_schema=False)
def tela_pc():
    return FileResponse(os.path.join(STATIC, "index.html"), headers=SEM_CACHE)


@app.get("/m", include_in_schema=False)
def tela_coletor():
    return FileResponse(os.path.join(STATIC, "m.html"), headers=SEM_CACHE)


@app.get("/api/status")
def status(request: Request):
    """O coletor usa para achar o servidor na rede ("servidor": "TagStock")."""
    porta = request.url.port or 8100
    return {"ok": True, "servidor": NOME_SERVIDOR, "data_hora": db.agora(), "motivos": regras.MOTIVOS_BAIXA,
            "coletor": f"http://{db.ip_da_rede()}:{porta}", "banco": os.path.abspath(db.DB_PATH),
            "tela": int(os.path.getmtime(os.path.join(STATIC, "m.html")))}


# ================================================================ login e usuários
class Login(BaseModel):
    login: str
    senha: str


@app.post("/api/login")
def login(d: Login, con: Con = Depends(conexao)):
    r = con.execute("SELECT * FROM usuarios WHERE login=? AND ativo=1", (d.login.strip().lower(),)).fetchone()
    if not r or not db.confere_senha(d.senha, r["senha"]):
        raise HTTPException(401, "Usuário ou senha incorretos")
    token = secrets.token_urlsafe(24)
    con.execute("INSERT INTO sessoes (token, usuario_id, criada_em) VALUES (?,?,?)", (token, r["id"], db.agora()))
    return {"token": token, "usuario": {"id": r["id"], "login": r["login"], "nome": r["nome"], "perfil": r["perfil"]}}


@app.post("/api/logout")
def logout(x_token: Optional[str] = Header(None), con: Con = Depends(conexao)):
    con.execute("DELETE FROM sessoes WHERE token=?", (x_token,))
    return {"ok": True}


@app.get("/api/eu")
def eu(u: Usuario = Logado):
    return u


class UsuarioIn(BaseModel):
    login: str = Field(min_length=2)
    nome: str = Field(min_length=1)
    senha: Optional[str] = None
    perfil: Literal["ADMIN", "OPERADOR"] = "OPERADOR"
    ativo: bool = True


@app.get("/api/usuarios")
def usuarios(con: Con = Depends(conexao), _u=Depends(admin)):
    return db.linhas(con.execute("SELECT id, login, nome, perfil, ativo FROM usuarios ORDER BY login"))


@app.post("/api/usuarios")
def criar_usuario(d: UsuarioIn, con: Con = Depends(conexao), _u=Depends(admin)):
    if not d.senha or len(d.senha) < 4:
        raise ErroRegra("Senha com pelo menos 4 caracteres")
    try:
        cur = con.execute("INSERT INTO usuarios (login, nome, senha, perfil, ativo) VALUES (?,?,?,?,?)",
                          (d.login.strip().lower(), d.nome.strip(), db.hash_senha(d.senha), d.perfil, int(d.ativo)))
    except sqlite3.IntegrityError as e:
        raise ErroRegra("Já existe esse login") from e
    return {"id": cur.lastrowid}


@app.put("/api/usuarios/{uid}")
def alterar_usuario(uid: int, d: UsuarioIn, con: Con = Depends(conexao), u=Depends(admin)):
    if uid == u.id and (d.perfil != "ADMIN" or not d.ativo):
        raise ErroRegra("Você não pode tirar o seu próprio acesso de administrador")
    con.execute("UPDATE usuarios SET nome=?, perfil=?, ativo=? WHERE id=?", (d.nome.strip(), d.perfil, int(d.ativo), uid))
    if d.senha:
        if len(d.senha) < 4:
            raise ErroRegra("Senha com pelo menos 4 caracteres")
        con.execute("UPDATE usuarios SET senha=? WHERE id=?", (db.hash_senha(d.senha), uid))
        con.execute("DELETE FROM sessoes WHERE usuario_id=?", (uid,))
    return {"ok": True}


class TrocaSenha(BaseModel):
    atual: str
    nova: str = Field(min_length=4)


@app.post("/api/minha-senha")
def minha_senha(d: TrocaSenha, con: Con = Depends(conexao), u: Usuario = Logado):
    r = con.execute("SELECT senha FROM usuarios WHERE id=?", (u.id,)).fetchone()
    if not db.confere_senha(d.atual, r[0]):
        raise ErroRegra("Senha atual incorreta")
    con.execute("UPDATE usuarios SET senha=? WHERE id=?", (db.hash_senha(d.nova), u.id))
    return {"ok": True}


# ================================================================ configuração
@app.get("/api/config")
def ler_config(con: Con = Depends(conexao), _u=Logado):
    cfg = db.config(con)
    cfg["modelo_zpl_padrao"] = impressao.MODELO_PADRAO
    return cfg


@app.put("/api/config")
def gravar_config(d: dict, con: Con = Depends(conexao), _u=Depends(admin)):
    for chave, valor in d.items():
        if chave not in db.CONFIG_PADRAO:
            continue
        valor = "" if valor is None else str(valor)
        if chave == "prefixo_gs1_digitos" and not (valor.isdigit() and 6 <= int(valor) <= 12):
            raise ErroRegra("O prefixo GS1 da empresa tem de 6 a 12 dígitos")
        if chave == "filtro_epc" and not (valor.isdigit() and 0 <= int(valor) <= 7):
            raise ErroRegra("Filtro EPC vai de 0 a 7")
        con.execute("INSERT OR REPLACE INTO config (chave, valor) VALUES (?,?)", (chave, valor))
    return db.config(con)


# ================================================================ painel (análise)
@app.get("/api/painel")
def painel(con: Con = Depends(conexao), _u=Logado):
    return regras.painel(con)


# ================================================================ locais
class LocalIn(BaseModel):
    codigo: str = Field(min_length=1)
    nome: str = Field(min_length=1)
    tipo: Literal["DEPOSITO", "LOJA", "EXPEDICAO", "AVARIA"] = "DEPOSITO"
    ativo: bool = True


@app.get("/api/locais")
def locais(con: Con = Depends(conexao), _u=Logado):
    return db.linhas(con.execute(
        """SELECT l.*, (SELECT COUNT(*) FROM etiquetas t WHERE t.local_id=l.id AND t.status='ESTOQUE') AS quantidade
           FROM locais l ORDER BY l.ativo DESC, l.codigo"""))


@app.post("/api/locais")
def criar_local(d: LocalIn, con: Con = Depends(conexao), _u=Depends(admin)):
    try:
        cur = con.execute("INSERT INTO locais (codigo, nome, tipo, ativo) VALUES (?,?,?,?)",
                          (d.codigo.strip().upper(), d.nome.strip(), d.tipo, int(d.ativo)))
    except sqlite3.IntegrityError as e:
        raise ErroRegra("Já existe um local com esse código") from e
    return {"id": cur.lastrowid}


@app.put("/api/locais/{lid}")
def alterar_local(lid: int, d: LocalIn, con: Con = Depends(conexao), _u=Depends(admin)):
    regras.local(con, lid)
    if not d.ativo and con.execute("SELECT 1 FROM etiquetas WHERE local_id=? AND status='ESTOQUE'", (lid,)).fetchone():
        raise ErroRegra("O local tem peças no estoque: transfira antes de inativar")
    try:
        con.execute("UPDATE locais SET codigo=?, nome=?, tipo=?, ativo=? WHERE id=?",
                    (d.codigo.strip().upper(), d.nome.strip(), d.tipo, int(d.ativo), lid))
    except sqlite3.IntegrityError as e:
        raise ErroRegra("Já existe um local com esse código") from e
    return {"ok": True}


# ================================================================ produtos
class ProdutoIn(BaseModel):
    sku: str
    descricao: str
    gtin: Optional[str] = None
    grupo: Optional[str] = None
    subgrupo: Optional[str] = None
    cor: Optional[str] = None
    tamanho: Optional[str] = None
    unidade: str = "UN"
    preco: float = 0
    estoque_min: int = 0
    ativo: bool = True


SQL_PRODUTOS = """SELECT p.*, (SELECT COUNT(*) FROM etiquetas t WHERE t.produto_id=p.id AND t.status='ESTOQUE') AS saldo,
                         (SELECT COUNT(*) FROM etiquetas t WHERE t.produto_id=p.id AND t.status='EMITIDA') AS emitidas
                  FROM produtos p"""


@app.get("/api/produtos")
def produtos(q: Optional[str] = None, grupo: Optional[str] = None, ativos: bool = False,
             con: Con = Depends(conexao), _u=Logado):
    sql, args = SQL_PRODUTOS + " WHERE 1=1", []
    if q:
        sql += " AND (p.sku LIKE ? OR p.descricao LIKE ? OR p.gtin LIKE ? OR p.cor LIKE ? OR p.tamanho=?)"
        args += [f"%{q}%"] * 4 + [q]
    if grupo:
        sql += " AND p.grupo=?"
        args.append(grupo)
    if ativos:
        sql += " AND p.ativo=1"
    return db.linhas(con.execute(sql + " ORDER BY p.sku, p.cor, p.tamanho LIMIT 2000", args))


@app.get("/api/produtos/codigo/{codigo}")
def produto_por_codigo(codigo: str, con: Con = Depends(conexao), _u=Logado):
    """Código de barras bipado (EAN/GTIN) ou SKU digitado."""
    c = codigo.strip()
    r = con.execute(SQL_PRODUTOS + " WHERE p.sku=? OR p.gtin=? OR LTRIM(p.gtin,'0')=LTRIM(?,'0')", (c, c, c)).fetchone()
    if not r:
        raise HTTPException(404, f"Produto não encontrado: {c}")
    return dict(r)


@app.get("/api/grupos")
def grupos(con: Con = Depends(conexao), _u=Logado):
    return [r[0] for r in con.execute("SELECT DISTINCT grupo FROM produtos WHERE grupo IS NOT NULL ORDER BY grupo")]


@app.post("/api/produtos")
def criar_produto(d: ProdutoIn, con: Con = Depends(conexao), _u=Logado):
    return {"id": regras.salvar_produto(con, d.model_dump())}


@app.put("/api/produtos/{pid}")
def alterar_produto(pid: int, d: ProdutoIn, con: Con = Depends(conexao), _u=Logado):
    return {"id": regras.salvar_produto(con, d.model_dump(), pid)}


@app.delete("/api/produtos/{pid}")
def excluir_produto(pid: int, con: Con = Depends(conexao), _u=Depends(admin)):
    regras.produto(con, pid)
    if con.execute("SELECT 1 FROM etiquetas WHERE produto_id=?", (pid,)).fetchone():
        raise ErroRegra("O produto já tem etiquetas: desmarque Ativo em vez de excluir")
    con.execute("DELETE FROM pedido_itens WHERE produto_id=?", (pid,))
    con.execute("DELETE FROM produtos WHERE id=?", (pid,))
    return {"ok": True}


class Ids(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=20000)


@app.post("/api/produtos/excluir")
def excluir_produtos(d: Ids, con: Con = Depends(conexao), _u=Depends(admin)):
    """Exclui vários produtos. Produto que já tem etiquetas não é excluído (o histórico depende dele)."""
    excluidos, mantidos = 0, []
    for pid in dict.fromkeys(d.ids):
        p = con.execute("SELECT sku FROM produtos WHERE id=?", (pid,)).fetchone()
        if not p:
            continue
        if con.execute("SELECT 1 FROM etiquetas WHERE produto_id=?", (pid,)).fetchone():
            mantidos.append(p["sku"])
            continue
        con.execute("DELETE FROM pedido_itens WHERE produto_id=?", (pid,))
        con.execute("DELETE FROM produtos WHERE id=?", (pid,))
        excluidos += 1
    return {"excluidos": excluidos, "mantidos": mantidos}


class Importacao(BaseModel):
    csv: str


@app.post("/api/produtos/importar")
def importar_produtos(d: Importacao, con: Con = Depends(conexao), _u=Logado):
    return regras.importar_produtos(con, d.csv)


@app.get("/api/produtos.csv", include_in_schema=False)
def produtos_csv(con: Con = Depends(conexao), _u=Logado):
    linhas = db.linhas(con.execute(SQL_PRODUTOS + " ORDER BY p.sku"))
    return csv_resposta("produtos.csv", [("sku", "sku"), ("descricao", "descricao"), ("gtin", "gtin"), ("grupo", "grupo"),
                                         ("subgrupo", "subgrupo"), ("cor", "cor"), ("tamanho", "tamanho"), ("preco", "preco"),
                                         ("estoque_min", "estoque_min"), ("unidade", "unidade"), ("saldo", "saldo")], linhas)


# ================================================================ EPC
@app.get("/api/epc/gerar")
def epc_gerar(gtin: str, serial: int = 1, con: Con = Depends(conexao), _u=Logado):
    """Calculadora: mostra o EPC SGTIN-96 de um GTIN + série (não grava nada)."""
    cfg = db.config(con)
    e = epc_mod.sgtin96(gtin, serial, int(cfg["prefixo_gs1_digitos"]), int(cfg["filtro_epc"]))
    return epc_mod.decodificar(e).dict()


@app.get("/api/epc/{epc}")
def epc_historico(epc: str, con: Con = Depends(conexao), _u=Logado):
    return regras.historico(con, epc)


# ================================================================ etiquetas
class Epcs(BaseModel):
    epcs: list[str] = Field(max_length=20000)


class Verificar(Epcs):
    operacao: Literal["entrada", "baixa", "transferencia", "estorno", "cancelar", "vincular", "expedicao"]
    local_id: Optional[int] = None
    produto_id: Optional[int] = None


class VincularIn(Epcs):
    produto_id: int
    local_id: Optional[int] = None
    ativar: bool = True
    documento: Optional[str] = None


class EntradaIn(Epcs):
    local_id: Optional[int] = None
    documento: Optional[str] = None


class BaixaIn(Epcs):
    motivo: str
    local_id: Optional[int] = None
    documento: Optional[str] = None


class TransferenciaIn(Epcs):
    destino_id: int
    origem_id: Optional[int] = None
    documento: Optional[str] = None


class CancelarIn(Epcs):
    motivo: Optional[str] = None


class GravacaoIn(BaseModel):
    epc: str
    antigo: Optional[str] = None


@app.get("/api/etiquetas")
def etiquetas(status: Optional[str] = None, local_id: Optional[int] = None, produto_id: Optional[int] = None,
              q: Optional[str] = None, limite: int = 500, con: Con = Depends(conexao), _u=Logado):
    sql, args = regras.SQL_ETIQUETA + " WHERE 1=1", []
    if status:
        sql += " AND t.status=?"
        args.append(status)
    if local_id:
        sql += " AND t.local_id=?"
        args.append(local_id)
    if produto_id:
        sql += " AND t.produto_id=?"
        args.append(produto_id)
    if q:
        sql += " AND (t.epc LIKE ? OR p.sku LIKE ? OR p.descricao LIKE ?)"
        args += [f"%{q.upper()}%", f"%{q}%", f"%{q}%"]
    return db.linhas(con.execute(sql + " ORDER BY t.atualizada_em DESC LIMIT ?", (*args, min(limite, 5000))))


@app.post("/api/etiquetas/situacao")
def etiquetas_situacao(d: Epcs, con: Con = Depends(conexao), _u=Logado):
    return regras.situacao(con, d.epcs)


@app.post("/api/etiquetas/verificar")
def etiquetas_verificar(d: Verificar, con: Con = Depends(conexao), _u=Logado):
    return regras.verificar(con, d.epcs, d.operacao, d.local_id, d.produto_id)


@app.post("/api/etiquetas/vincular")
def etiquetas_vincular(d: VincularIn, con: Con = Depends(conexao), c: Ctx = Depends(ctx)):
    return regras.vincular(con, c, d.epcs, d.produto_id, d.local_id, d.ativar, d.documento)


@app.post("/api/etiquetas/entrada")
def etiquetas_entrada(d: EntradaIn, con: Con = Depends(conexao), c: Ctx = Depends(ctx)):
    return regras.entrada(con, c, d.epcs, d.local_id, d.documento)


@app.post("/api/etiquetas/baixa")
def etiquetas_baixa(d: BaixaIn, con: Con = Depends(conexao), c: Ctx = Depends(ctx)):
    return regras.baixar(con, c, d.epcs, d.motivo, d.local_id, d.documento)


@app.post("/api/etiquetas/estorno")
def etiquetas_estorno(d: Epcs, con: Con = Depends(conexao), c: Ctx = Depends(ctx)):
    return regras.estornar(con, c, d.epcs)


@app.post("/api/etiquetas/transferencia")
def etiquetas_transferencia(d: TransferenciaIn, con: Con = Depends(conexao), c: Ctx = Depends(ctx)):
    return regras.transferir(con, c, d.epcs, d.destino_id, d.origem_id, d.documento)


@app.post("/api/etiquetas/cancelar")
def etiquetas_cancelar(d: CancelarIn, con: Con = Depends(conexao), c: Ctx = Depends(ctx)):
    return regras.cancelar_etiquetas(con, c, d.epcs, d.motivo)


@app.post("/api/etiquetas/gravacao")
def etiquetas_gravacao(d: GravacaoIn, con: Con = Depends(conexao), c: Ctx = Depends(ctx)):
    """O coletor gravou um EPC emitido pelo sistema numa etiqueta física."""
    return regras.registrar_gravacao(con, c, d.epc, d.antigo)


@app.post("/api/antifurto")
def antifurto(d: Epcs, ponto: Optional[str] = None, con: Con = Depends(conexao), _u=Logado):
    return regras.antifurto(con, d.epcs, ponto)


# ================================================================ estoque e movimentos
@app.get("/api/estoque")
def estoque(local_id: Optional[int] = None, grupo: Optional[str] = None, q: Optional[str] = None,
            con: Con = Depends(conexao), _u=Logado):
    return regras.estoque(con, local_id, grupo, q)


@app.get("/api/estoque.csv", include_in_schema=False)
def estoque_csv(local_id: Optional[int] = None, grupo: Optional[str] = None, con: Con = Depends(conexao), _u=Logado):
    return csv_resposta("estoque.csv", [("Local", "local"), ("SKU", "sku"), ("Descrição", "descricao"), ("Cor", "cor"),
                                        ("Tamanho", "tamanho"), ("Grupo", "grupo"), ("GTIN", "gtin"), ("Quantidade", "quantidade")],
                        regras.estoque(con, local_id, grupo))


@app.get("/api/estoque/etiquetas.csv", include_in_schema=False)
def estoque_etiquetas_csv(local_id: Optional[int] = None, con: Con = Depends(conexao), _u=Logado):
    sql, args = regras.SQL_ETIQUETA + " WHERE t.status='ESTOQUE'", []
    if local_id:
        sql += " AND t.local_id=?"
        args.append(local_id)
    return csv_resposta("etiquetas-em-estoque.csv", [("EPC", "epc"), ("Local", "local"), ("SKU", "sku"), ("Descrição", "descricao"),
                                                     ("Cor", "cor"), ("Tamanho", "tamanho"), ("OF", "ordem"),
                                                     ("Última leitura", "ultima_leitura")],
                        db.linhas(con.execute(sql + " ORDER BY l.codigo, p.sku", args)))


SQL_MOV = """SELECT m.*, p.sku, p.descricao, p.cor, p.tamanho, lo.codigo AS origem_local, ld.codigo AS destino_local
             FROM movimentos m JOIN produtos p ON p.id=m.produto_id
             LEFT JOIN locais lo ON lo.id=m.local_origem LEFT JOIN locais ld ON ld.id=m.local_destino WHERE 1=1"""


def _filtro_mov(tipo, de, ate, q, local_id):
    sql, args = SQL_MOV, []
    if tipo:
        sql += " AND m.tipo=?"
        args.append(tipo)
    if de:
        sql += " AND m.data_hora >= ?"
        args.append(de)
    if ate:
        sql += " AND m.data_hora <= ?"
        args.append(ate + " 23:59:59")
    if q:
        sql += " AND (m.epc LIKE ? OR p.sku LIKE ? OR p.descricao LIKE ? OR m.documento LIKE ?)"
        args += [f"%{q.upper()}%", f"%{q}%", f"%{q}%", f"%{q}%"]
    if local_id:
        sql += " AND (m.local_origem=? OR m.local_destino=?)"
        args += [local_id, local_id]
    return sql + " ORDER BY m.id DESC", args


@app.get("/api/movimentos")
def movimentos(tipo: Optional[str] = None, de: Optional[str] = None, ate: Optional[str] = None, q: Optional[str] = None,
               local_id: Optional[int] = None, limite: int = 500, con: Con = Depends(conexao), _u=Logado):
    sql, args = _filtro_mov(tipo, de, ate, q, local_id)
    return db.linhas(con.execute(sql + " LIMIT ?", (*args, min(limite, 5000))))


@app.get("/api/movimentos.csv", include_in_schema=False)
def movimentos_csv(tipo: Optional[str] = None, de: Optional[str] = None, ate: Optional[str] = None, q: Optional[str] = None,
                   local_id: Optional[int] = None, con: Con = Depends(conexao), _u=Logado):
    sql, args = _filtro_mov(tipo, de, ate, q, local_id)
    return csv_resposta("movimentos.csv", [("Data/hora", "data_hora"), ("Tipo", "tipo"), ("EPC", "epc"), ("SKU", "sku"),
                                           ("Descrição", "descricao"), ("Cor", "cor"), ("Tamanho", "tamanho"),
                                           ("Qtd", "quantidade"), ("De", "origem_local"), ("Para", "destino_local"),
                                           ("Motivo", "motivo"), ("Documento", "documento"), ("Origem", "origem"),
                                           ("Usuário", "usuario")], db.linhas(con.execute(sql, args)))


# ================================================================ OF / emissão (iPRINT)
class ItemQtd(BaseModel):
    produto_id: int
    quantidade: int = Field(ge=0)


class OrdemIn(BaseModel):
    numero: Optional[str] = None
    local_id: Optional[int] = None
    documento: Optional[str] = None
    observacao: Optional[str] = None
    itens: list[ItemQtd]


class Imprimir(BaseModel):
    impressora_id: int
    epcs: Optional[list[str]] = None     # vazio = todas as ainda não impressas


class Consolidar(BaseModel):
    produto_origem: int
    produto_destino: int


class FinalizarOrdem(BaseModel):
    cancelar_nao_lidas: bool = False


@app.get("/api/ordens")
def ordens(status: Optional[str] = None, con: Con = Depends(conexao), _u=Logado):
    return regras.listar_ordens(con, status)


@app.post("/api/ordens")
def criar_ordem(d: OrdemIn, con: Con = Depends(conexao), c: Ctx = Depends(ctx)):
    oid = regras.criar_ordem(con, c, d.numero, [i.model_dump() for i in d.itens], d.local_id, d.documento, d.observacao)
    return regras.ordem(con, oid)


@app.get("/api/ordens/{oid}")
def ordem(oid: int, con: Con = Depends(conexao), _u=Logado):
    return regras.ordem(con, oid)


@app.get("/api/ordens/{oid}/etiquetas")
def ordem_etiquetas(oid: int, somente: Optional[str] = None, con: Con = Depends(conexao), _u=Logado):
    return regras.etiquetas_ordem(con, oid, somente)


@app.get("/api/ordens/{oid}/etiquetas.csv", include_in_schema=False)
def ordem_etiquetas_csv(oid: int, con: Con = Depends(conexao), _u=Logado):
    o = regras.ordem(con, oid)
    return csv_resposta(f"{o['numero']}-etiquetas.csv", [("EPC", "epc"), ("SKU", "sku"), ("Descrição", "descricao"), ("Cor", "cor"),
                                                         ("Tamanho", "tamanho"), ("GTIN", "gtin"), ("Série", "serial"),
                                                         ("Situação", "status"), ("Impressa", "impressa_em"),
                                                         ("Gravada", "gravada_em")], regras.etiquetas_ordem(con, oid))


def _modelo(con, impressora: dict | None = None) -> str:
    return db.config(con).get("modelo_zpl") or impressao.MODELO_PADRAO


@app.get("/api/ordens/{oid}/etiquetas.zpl", include_in_schema=False)
def ordem_zpl(oid: int, somente: Optional[str] = None, con: Con = Depends(conexao), _u=Logado):
    """Arquivo ZPL para mandar à impressora por outro programa (ZebraDesigner, Zebra Setup Utilities...)."""
    o = regras.ordem(con, oid)
    lista = [t for t in regras.etiquetas_ordem(con, oid, somente) if t["status"] == "EMITIDA"]
    zpl = impressao.zpl_lote(_modelo(con), lista, db.config(con).get("empresa", ""))
    return Response(zpl, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{o["numero"]}.zpl"'})


@app.post("/api/ordens/{oid}/imprimir")
def ordem_imprimir(oid: int, d: Imprimir, con: Con = Depends(conexao), _u=Logado):
    o = regras.ordem(con, oid)
    if o["status"] != "ABERTA":
        raise ErroRegra(f"A OF está {o['status'].lower()}")
    imp = con.execute("SELECT * FROM impressoras WHERE id=?", (d.impressora_id,)).fetchone()
    if not imp:
        raise ErroRegra("Impressora não encontrada")
    todas = regras.etiquetas_ordem(con, oid)
    if d.epcs:
        quero = {epc_mod.normalizar(e) for e in d.epcs}
        lista = [t for t in todas if t["epc"] in quero and t["status"] == "EMITIDA"]
    else:
        lista = [t for t in todas if t["status"] == "EMITIDA" and not t["impressa_em"]]
    if not lista:
        raise ErroRegra("Nenhuma etiqueta para imprimir (todas já impressas? use Reimprimir)")
    impressao.enviar(dict(imp), impressao.zpl_lote(_modelo(con), lista, db.config(con).get("empresa", "")))
    regras.marcar_impressas(con, [t["epc"] for t in lista])
    con.execute("UPDATE ordens SET impressa_em=? WHERE id=?", (db.agora(), oid))
    return {"impressas": len(lista)}


@app.get("/api/ordens/{oid}/proxima")
def ordem_proxima(oid: int, produto_id: Optional[int] = None, con: Con = Depends(conexao), _u=Logado):
    """Coletor sem impressora RFID: qual EPC gravar na próxima etiqueta."""
    return {"etiqueta": regras.proxima_para_gravar(con, oid, produto_id)}


@app.post("/api/ordens/{oid}/leituras")
def ordem_leituras(oid: int, d: Epcs, con: Con = Depends(conexao), _u=Logado):
    return {"leituras": regras.ler_ordem(con, oid, d.epcs), "ordem": regras.ordem(con, oid)}


@app.delete("/api/ordens/{oid}/leituras/{epc}")
def ordem_remover_leitura(oid: int, epc: str, con: Con = Depends(conexao), _u=Logado):
    regras.remover_leitura_ordem(con, oid, epc)
    return regras.ordem(con, oid)


@app.delete("/api/ordens/{oid}/leituras")
def ordem_limpar_leituras(oid: int, con: Con = Depends(conexao), _u=Logado):
    regras.limpar_leituras_ordem(con, oid)
    return regras.ordem(con, oid)


@app.post("/api/ordens/{oid}/consolidar")
def ordem_consolidar(oid: int, d: Consolidar, con: Con = Depends(conexao), c: Ctx = Depends(ctx)):
    n = regras.consolidar_kit(con, c, oid, d.produto_origem, d.produto_destino)
    return {"etiquetas": n, "ordem": regras.ordem(con, oid)}


@app.post("/api/ordens/{oid}/finalizar")
def ordem_finalizar(oid: int, d: FinalizarOrdem, con: Con = Depends(conexao), c: Ctx = Depends(ctx)):
    return regras.finalizar_ordem(con, c, oid, d.cancelar_nao_lidas)


@app.post("/api/ordens/{oid}/cancelar")
def ordem_cancelar(oid: int, con: Con = Depends(conexao), c: Ctx = Depends(ctx)):
    return {"canceladas": regras.cancelar_ordem(con, c, oid)}


# ================================================================ impressoras
class ImpressoraIn(BaseModel):
    nome: str = Field(min_length=1)
    tipo: Literal["REDE", "WINDOWS"] = "REDE"
    endereco: str = Field(min_length=1)
    porta: int = 9100
    ativo: bool = True


@app.get("/api/impressoras")
def impressoras(con: Con = Depends(conexao), _u=Logado):
    return db.linhas(con.execute("SELECT * FROM impressoras ORDER BY ativo DESC, nome"))


@app.get("/api/impressoras/windows")
def impressoras_windows(_u=Logado):
    return impressao.impressoras_windows()


@app.post("/api/impressoras")
def criar_impressora(d: ImpressoraIn, con: Con = Depends(conexao), _u=Depends(admin)):
    cur = con.execute("INSERT INTO impressoras (nome, tipo, endereco, porta, ativo) VALUES (?,?,?,?,?)",
                      (d.nome.strip(), d.tipo, d.endereco.strip(), d.porta, int(d.ativo)))
    return {"id": cur.lastrowid}


@app.put("/api/impressoras/{iid}")
def alterar_impressora(iid: int, d: ImpressoraIn, con: Con = Depends(conexao), _u=Depends(admin)):
    con.execute("UPDATE impressoras SET nome=?, tipo=?, endereco=?, porta=?, ativo=? WHERE id=?",
                (d.nome.strip(), d.tipo, d.endereco.strip(), d.porta, int(d.ativo), iid))
    return {"ok": True}


@app.delete("/api/impressoras/{iid}")
def excluir_impressora(iid: int, con: Con = Depends(conexao), _u=Depends(admin)):
    con.execute("DELETE FROM impressoras WHERE id=?", (iid,))
    return {"ok": True}


def _impressora(con, iid) -> dict:
    r = con.execute("SELECT * FROM impressoras WHERE id=?", (iid,)).fetchone()
    if not r:
        raise ErroRegra("Impressora não encontrada")
    return dict(r)


@app.post("/api/impressoras/{iid}/testar")
def testar_impressora(iid: int, con: Con = Depends(conexao), _u=Logado):
    return {"mensagem": impressao.testar(_impressora(con, iid))}


@app.post("/api/impressoras/{iid}/etiqueta-teste")
def etiqueta_teste(iid: int, con: Con = Depends(conexao), _u=Logado):
    """Imprime uma etiqueta de exemplo SEM gravar RFID (confere o layout)."""
    modelo = "\n".join(l for l in _modelo(con).splitlines() if not l.startswith("^RF") and not l.startswith("^RS"))
    t = {"epc": "000000000000000000000000", "descricao": "ETIQUETA DE TESTE", "sku": "TESTE", "cor": "AZUL", "tamanho": "M",
         "preco": 99.9, "gtin": "7891234567895", "ordem": "OF-TESTE", "serial": 1}
    impressao.enviar(_impressora(con, iid), impressao.zpl_etiqueta(modelo, t, db.config(con).get("empresa", "")))
    return {"ok": True}


# ================================================================ inventário
class InventarioIn(BaseModel):
    nome: Optional[str] = None
    local_id: Optional[int] = None
    grupo: Optional[str] = None


class LeiturasIn(Epcs):
    dispositivo: Optional[str] = None


class FinalizarInventario(BaseModel):
    ajustar: bool = True


class IncluirIn(BaseModel):
    epc: str
    produto_id: int


@app.get("/api/inventarios")
def inventarios(con: Con = Depends(conexao), _u=Logado):
    return db.linhas(con.execute(
        """SELECT i.*, l.codigo AS local,
                  (SELECT COUNT(*) FROM inventario_leituras WHERE inventario_id=i.id) AS lidas_agora
           FROM inventarios i LEFT JOIN locais l ON l.id=i.local_id ORDER BY i.id DESC LIMIT 200"""))


@app.post("/api/inventarios")
def criar_inventario(d: InventarioIn, con: Con = Depends(conexao), _u=Logado):
    return {"id": regras.criar_inventario(con, d.nome, d.local_id, d.grupo)}


@app.get("/api/inventarios/{iid}")
def inventario(iid: int, con: Con = Depends(conexao), _u=Logado):
    return regras.inventario(con, iid)


@app.post("/api/inventarios/{iid}/leituras")
def inventario_leituras(iid: int, d: LeiturasIn, con: Con = Depends(conexao), _u=Logado):
    return regras.ler_inventario(con, iid, d.epcs, d.dispositivo)


@app.delete("/api/inventarios/{iid}/leituras")
def inventario_zerar(iid: int, con: Con = Depends(conexao), _u=Logado):
    inv = regras.inventario(con, iid)
    if inv["status"] != "ABERTO":
        raise ErroRegra("Inventário já fechado")
    con.execute("DELETE FROM inventario_leituras WHERE inventario_id=?", (iid,))
    return {"ok": True}


@app.post("/api/inventarios/{iid}/incluir")
def inventario_incluir(iid: int, d: IncluirIn, con: Con = Depends(conexao), c: Ctx = Depends(ctx)):
    regras.incluir_desconhecida(con, c, iid, d.epc, d.produto_id)
    return {"ok": True}


@app.post("/api/inventarios/{iid}/finalizar")
def inventario_finalizar(iid: int, d: FinalizarInventario, con: Con = Depends(conexao), c: Ctx = Depends(ctx)):
    return regras.finalizar_inventario(con, c, iid, d.ajustar)


@app.post("/api/inventarios/{iid}/cancelar")
def inventario_cancelar(iid: int, con: Con = Depends(conexao), _u=Logado):
    con.execute("UPDATE inventarios SET status='CANCELADO', fechado_em=? WHERE id=? AND status='ABERTO'", (db.agora(), iid))
    return {"ok": True}


@app.get("/api/inventarios/{iid}/contagem.csv", include_in_schema=False)
def inventario_csv(iid: int, con: Con = Depends(conexao), _u=Logado):
    inv = regras.inventario(con, iid)
    return csv_resposta(f"inventario-{iid}.csv", [("EPC", "epc"), ("Situação", "situacao"), ("SKU", "sku"), ("Descrição", "descricao"),
                                                  ("Cor", "cor"), ("Tamanho", "tamanho"), ("Local no sistema", "local")],
                        inv["etiquetas"])


# ================================================================ expedição
class PedidoIn(BaseModel):
    numero: Optional[str] = None
    tipo: Literal["VENDA", "TRANSFERENCIA"] = "VENDA"
    cliente: Optional[str] = None
    local_id: Optional[int] = None
    destino_id: Optional[int] = None
    documento: Optional[str] = None
    itens: list[ItemQtd]


@app.get("/api/pedidos")
def pedidos(status: Optional[str] = None, con: Con = Depends(conexao), _u=Logado):
    return regras.listar_pedidos(con, status)


@app.post("/api/pedidos")
def criar_pedido(d: PedidoIn, con: Con = Depends(conexao), _u=Logado):
    pid = regras.criar_pedido(con, d.numero, d.tipo, [i.model_dump() for i in d.itens], d.cliente, d.local_id, d.destino_id, d.documento)
    return regras.pedido(con, pid)


@app.get("/api/pedidos/{pid}")
def pedido(pid: int, con: Con = Depends(conexao), _u=Logado):
    return regras.pedido(con, pid)


@app.post("/api/pedidos/{pid}/leituras")
def pedido_leituras(pid: int, d: Epcs, con: Con = Depends(conexao), _u=Logado):
    return {"leituras": regras.ler_pedido(con, pid, d.epcs), "pedido": regras.pedido(con, pid)}


@app.delete("/api/pedidos/{pid}/leituras/{epc}")
def pedido_remover_leitura(pid: int, epc: str, con: Con = Depends(conexao), _u=Logado):
    regras.remover_leitura_pedido(con, pid, epc)
    return regras.pedido(con, pid)


@app.post("/api/pedidos/{pid}/finalizar")
def pedido_finalizar(pid: int, con: Con = Depends(conexao), c: Ctx = Depends(ctx)):
    return regras.finalizar_pedido(con, c, pid)


@app.post("/api/pedidos/{pid}/cancelar")
def pedido_cancelar(pid: int, con: Con = Depends(conexao), _u=Logado):
    regras.cancelar_pedido(con, pid)
    return {"ok": True}


# ================================================================ alertas e dispositivos (monitor)
@app.get("/api/alertas")
def alertas(todos: bool = False, con: Con = Depends(conexao), _u=Logado):
    sql = "SELECT * FROM alertas" + ("" if todos else " WHERE lido=0") + " ORDER BY id DESC LIMIT 300"
    return db.linhas(con.execute(sql))


@app.post("/api/alertas/{aid}/lido")
def alerta_lido(aid: int, con: Con = Depends(conexao), _u=Logado):
    con.execute("UPDATE alertas SET lido=1 WHERE id=?", (aid,))
    return {"ok": True}


@app.post("/api/alertas/lidos")
def alertas_lidos(con: Con = Depends(conexao), _u=Logado):
    con.execute("UPDATE alertas SET lido=1 WHERE lido=0")
    return {"ok": True}


class Sinal(BaseModel):
    id: str
    nome: Optional[str] = None
    versao: Optional[str] = None
    bateria: Optional[int] = None
    rfid: Optional[str] = None
    tela: Optional[str] = None


@app.post("/api/dispositivos/sinal")
def dispositivo_sinal(d: Sinal, request: Request, con: Con = Depends(conexao), u: Usuario = Logado):
    con.execute("""INSERT INTO dispositivos (id, nome, ip, versao, bateria, rfid, tela, ultimo_sinal) VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET nome=excluded.nome, ip=excluded.ip, versao=excluded.versao,
                     bateria=excluded.bateria, rfid=COALESCE(excluded.rfid, rfid), tela=excluded.tela,
                     ultimo_sinal=excluded.ultimo_sinal""",
                (d.id, d.nome or u.login, request.client.host if request.client else None, d.versao, d.bateria, d.rfid,
                 d.tela, db.agora()))
    return {"ok": True, "data_hora": db.agora()}


@app.get("/api/dispositivos")
def dispositivos(con: Con = Depends(conexao), _u=Logado):
    lista = db.linhas(con.execute(
        """SELECT *, CAST((julianday('now','localtime') - julianday(ultimo_sinal)) * 86400 AS INTEGER) AS segundos
           FROM dispositivos ORDER BY ultimo_sinal DESC"""))
    for d in lista:
        d["online"] = d["segundos"] is not None and d["segundos"] < 60
    return lista


# ================================================================ estação PC (leitor remoto)
class ComandoIn(BaseModel):
    acao: Literal["ler", "parar", "limpar", "gravar", "escanear"]
    texto: Optional[str] = None
    potencia: Optional[int] = Field(None, ge=1, le=100)


class EventoIn(BaseModel):
    tipo: str
    dados: dict = {}


@app.post("/api/remoto/comando")
def remoto_comando(d: ComandoIn, _u=Logado):
    if d.acao == "gravar":
        t = epc_mod.normalizar(d.texto or "")
        if not t or len(t) > 32 or not all(c in "0123456789ABCDEF" for c in t):
            raise ErroRegra("EPC para gravar: até 32 caracteres hexadecimais")
        d.texto = t
    return remoto.comando(d.acao, d.texto, d.potencia)


@app.get("/api/remoto/comandos")
def remoto_comandos(apos: int = -1, dispositivo: Optional[str] = None, _u=Logado):
    return remoto.comandos_para_coletor(apos, dispositivo)


@app.post("/api/remoto/leituras")
def remoto_leituras(d: Epcs, _u=Logado):
    return {"total": remoto.registrar_leituras(d.epcs)}


@app.post("/api/remoto/remover")
def remoto_remover(d: Epcs, _u=Logado):
    remoto.remover(d.epcs)
    return {"ok": True}


@app.post("/api/remoto/evento")
def remoto_evento(d: EventoIn, _u=Logado):
    remoto.registrar_evento(d.tipo, d.dados)
    return {"ok": True}


@app.get("/api/remoto/estado")
def remoto_estado(eventos_apos: int = 0, con: Con = Depends(conexao), _u=Logado):
    e = remoto.estado(eventos_apos)
    sit = {s["epc"]: s for s in regras.situacao(con, [r["epc"] for r in e["leituras"]])}
    for r in e["leituras"]:
        r.update({k: v for k, v in sit.get(r["epc"], {}).items() if k != "epc"})
    return e


# ================================================================ sistema
class Limpar(BaseModel):
    manter_cadastros: bool = True
    confirmacao: str


@app.post("/api/limpar-tudo")
def limpar_tudo(d: Limpar, con: Con = Depends(conexao), _u=Depends(admin)):
    if d.confirmacao != "APAGAR":
        raise ErroRegra("Digite APAGAR para confirmar")
    for t in ("ordem_leituras", "pedido_leituras", "inventario_leituras", "inventario_resultado", "movimentos", "alertas",
              "etiquetas", "ordem_itens", "ordens", "pedido_itens", "pedidos", "inventarios", "dispositivos"):
        con.execute(f"DELETE FROM {t}")
    if not d.manter_cadastros:
        con.execute("DELETE FROM produtos")
        con.execute("DELETE FROM impressoras")
    return {"ok": True}
