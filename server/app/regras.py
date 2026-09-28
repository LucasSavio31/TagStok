"""Regras do TagStock: tudo que muda o estoque passa por aqui.

Ciclo de vida da etiqueta (1 etiqueta = 1 peça):

    OF / Vincular ──► EMITIDA ──(finalizar OF / entrada)──► ESTOQUE ──(baixa / expedição)──► BAIXADA
                         │                                     │  ▲                          │
                         └──────────(cancelar)──► CANCELADA ◄──┘  └────────(estorno)─────────┘

Cada mudança grava um movimento (kardex da etiqueta) com data/hora do servidor.
"""
import csv
import io
from dataclasses import dataclass

from . import db, epc as epcs_mod

MOTIVOS_BAIXA = ["VENDA", "CONSUMO", "AVARIA", "PERDA", "FURTO", "DEVOLUCAO_FORNECEDOR", "AMOSTRA"]


class ErroRegra(Exception):
    pass


@dataclass
class Ctx:
    """Quem está fazendo: vai para o histórico."""
    origem: str = "PC"          # PC | COLETOR | API
    dispositivo: str | None = None
    usuario: str | None = None


# ================================================================ auxiliares
def _norm(epcs) -> list[str]:
    vistos, saida = set(), []
    for e in epcs or []:
        n = epcs_mod.normalizar(e)
        if n and n not in vistos:
            vistos.add(n)
            saida.append(n)
    return saida


def produto(con, produto_id: int) -> dict:
    p = con.execute("SELECT * FROM produtos WHERE id=?", (produto_id,)).fetchone()
    if not p:
        raise ErroRegra("Produto não encontrado")
    return dict(p)


def local(con, local_id) -> dict:
    l = con.execute("SELECT * FROM locais WHERE id=?", (local_id,)).fetchone()
    if not l:
        raise ErroRegra("Local não encontrado")
    return dict(l)


def local_padrao(con) -> int:
    cfg = db.config(con)
    try:
        lid = int(cfg.get("local_padrao") or 0)
    except ValueError:
        lid = 0
    if lid and con.execute("SELECT 1 FROM locais WHERE id=? AND ativo=1", (lid,)).fetchone():
        return lid
    r = con.execute("SELECT id FROM locais WHERE ativo=1 ORDER BY id LIMIT 1").fetchone()
    if not r:
        raise ErroRegra("Cadastre um local de estoque")
    return r[0]


def _local_ou_padrao(con, local_id) -> int:
    if local_id:
        l = local(con, local_id)
        if not l["ativo"]:
            raise ErroRegra(f"O local {l['codigo']} está inativo")
        return l["id"]
    return local_padrao(con)


def mov(con, ctx: Ctx, tipo, epc, produto_id, qtd=0, origem_local=None, destino_local=None, motivo=None, documento=None):
    con.execute("""INSERT INTO movimentos (data_hora, tipo, epc, produto_id, local_origem, local_destino, quantidade,
                                           motivo, documento, origem, dispositivo, usuario)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (db.agora(), tipo, epc, produto_id, origem_local, destino_local, qtd, motivo, documento,
                 ctx.origem, ctx.dispositivo, ctx.usuario))


def alerta(con, tipo: str, mensagem: str, epc: str | None = None, repetir_minutos: int = 10) -> None:
    """Grava um alerta (sem repetir o mesmo alerta da mesma etiqueta em poucos minutos)."""
    if epc and con.execute("""SELECT 1 FROM alertas WHERE tipo=? AND epc=? AND lido=0
                              AND data_hora >= datetime('now','localtime', ?)""",
                           (tipo, epc, f"-{repetir_minutos} minutes")).fetchone():
        return
    con.execute("INSERT INTO alertas (data_hora, tipo, mensagem, epc) VALUES (?,?,?,?)", (db.agora(), tipo, mensagem, epc))


def _etiqueta(con, epc: str):
    return con.execute("SELECT * FROM etiquetas WHERE epc=?", (epc,)).fetchone()


def _atualizar(con, epc, **campos):
    campos["atualizada_em"] = db.agora()
    sets = ", ".join(f"{k}=?" for k in campos)
    con.execute(f"UPDATE etiquetas SET {sets} WHERE epc=?", (*campos.values(), epc))


def produto_por_gtin(con, gtin: str | None):
    if not gtin:
        return None
    g = gtin.lstrip("0")
    r = con.execute("SELECT * FROM produtos WHERE LTRIM(gtin,'0')=?", (g,)).fetchone()
    return dict(r) if r else None


SQL_ETIQUETA = """
    SELECT t.epc, t.status, t.serial, t.origem, t.ordem_id, t.local_id, t.criada_em, t.atualizada_em,
           t.impressa_em, t.gravada_em, t.ultima_leitura,
           p.id AS produto_id, p.sku, p.descricao, p.cor, p.tamanho, p.grupo, p.gtin, p.preco,
           l.codigo AS local, l.nome AS local_nome, o.numero AS ordem
    FROM etiquetas t JOIN produtos p ON p.id=t.produto_id
    LEFT JOIN locais l ON l.id=t.local_id LEFT JOIN ordens o ON o.id=t.ordem_id
"""


def situacao(con, epcs) -> list[dict]:
    """O que o sistema sabe de cada EPC lido (para a tela mostrar na hora)."""
    saida = []
    for e in _norm(epcs):
        r = con.execute(SQL_ETIQUETA + " WHERE t.epc=?", (e,)).fetchone()
        if r:
            item = dict(r)
        else:
            d = epcs_mod.decodificar(e)
            item = {"epc": e, "status": None, "esquema": d.esquema, "gtin_epc": d.gtin, "serial_epc": d.serial}
            sug = produto_por_gtin(con, d.gtin) if d.gtin else None
            if not sug and d.esquema == "GID-96" and d.classe:
                r2 = con.execute("SELECT * FROM produtos WHERE id=?", (d.classe,)).fetchone()
                sug = dict(r2) if r2 else None
            if sug:
                item["sugerido"] = {k: sug[k] for k in ("id", "sku", "descricao", "cor", "tamanho")}
        saida.append(item)
    return saida


def marcar_leitura(con, epcs) -> None:
    agora = db.agora()
    con.executemany("UPDATE etiquetas SET ultima_leitura=? WHERE epc=?", [(agora, e) for e in _norm(epcs)])


# ================================================================ geração de EPC (serialização)
def _proximo_serial(con, chave: str, quantidade: int) -> int:
    r = con.execute("SELECT ultimo FROM seriais WHERE chave=?", (chave,)).fetchone()
    inicio = (r[0] if r else 0) + 1
    con.execute("INSERT INTO seriais (chave, ultimo) VALUES (?, ?) ON CONFLICT(chave) DO UPDATE SET ultimo=excluded.ultimo",
                (chave, inicio + quantidade - 1))
    return inicio


def gerar_epcs(con, prod: dict, quantidade: int) -> list[tuple[str, int]]:
    """Gera EPCs novos e únicos para o produto: SGTIN-96 (tem GTIN) ou GID-96 (não tem)."""
    cfg = db.config(con)
    saida = []
    while len(saida) < quantidade:
        falta = quantidade - len(saida)
        if prod.get("gtin"):
            g14 = epcs_mod.gtin14(prod["gtin"])
            inicio = _proximo_serial(con, "sgtin:" + g14, falta)
            novos = [(epcs_mod.sgtin96(g14, s, int(cfg.get("prefixo_gs1_digitos") or 7), int(cfg.get("filtro_epc") or 1)), s)
                     for s in range(inicio, inicio + falta)]
        else:
            inicio = _proximo_serial(con, f"gid:{prod['id']}", falta)
            novos = [(epcs_mod.gid96(int(cfg.get("gid_gerente") or 1), prod["id"], s), s) for s in range(inicio, inicio + falta)]
        # etiqueta vinculada à mão pode já ter usado um desses números: pula
        saida += [(e, s) for e, s in novos if not _etiqueta(con, e)]
    return saida


# ================================================================ produtos
CAMPOS_PRODUTO = ("sku", "descricao", "gtin", "grupo", "subgrupo", "cor", "tamanho", "unidade", "preco", "estoque_min", "ativo")


def validar_produto(dados: dict) -> dict:
    d = {k: dados.get(k) for k in CAMPOS_PRODUTO if k in dados}
    for k in ("sku", "descricao", "gtin", "grupo", "subgrupo", "cor", "tamanho", "unidade"):
        if k in d:
            d[k] = (str(d[k]).strip() if d[k] is not None else None) or None
    if not d.get("sku"):
        raise ErroRegra("Informe o SKU / referência")
    if not d.get("descricao"):
        raise ErroRegra("Informe a descrição")
    if d.get("gtin") and not epcs_mod.gtin_valido(d["gtin"]):
        raise ErroRegra(f"GTIN/EAN inválido: {d['gtin']} (confira o dígito verificador)")
    d["unidade"] = (d.get("unidade") or "UN").upper()
    return d


def salvar_produto(con, dados: dict, produto_id: int | None = None) -> int:
    d = validar_produto(dados)
    try:
        if produto_id:
            produto(con, produto_id)
            sets = ", ".join(f"{k}=?" for k in d)
            con.execute(f"UPDATE produtos SET {sets} WHERE id=?", (*d.values(), produto_id))
            return produto_id
        d["criado_em"] = db.agora()
        cur = con.execute(f"INSERT INTO produtos ({', '.join(d)}) VALUES ({', '.join('?' * len(d))})", tuple(d.values()))
        return cur.lastrowid
    except Exception as e:  # noqa: BLE001
        if "UNIQUE" in str(e):
            campo = "GTIN" if "gtin" in str(e) else "SKU"
            raise ErroRegra(f"Já existe produto com esse {campo}") from e
        raise


def importar_produtos(con, texto: str) -> dict:
    """CSV (; ou ,) com cabeçalho: sku;descricao;gtin;grupo;subgrupo;cor;tamanho;preco;estoque_min;unidade.
    SKU que já existe é atualizado."""
    texto = texto.lstrip("﻿")
    primeira = texto.splitlines()[0] if texto.strip() else ""
    sep = ";" if primeira.count(";") >= primeira.count(",") else ","
    leitor = csv.DictReader(io.StringIO(texto), delimiter=sep)
    criados = atualizados = 0
    erros = []
    for n, linha in enumerate(leitor, start=2):
        linha = {(k or "").strip().lower(): (v or "").strip() for k, v in linha.items()}
        try:
            for k in ("preco", "estoque_min"):
                if linha.get(k):
                    linha[k] = float(linha[k].replace(".", "").replace(",", ".")) if "," in linha[k] else float(linha[k])
                else:
                    linha.pop(k, None)
            if "estoque_min" in linha:
                linha["estoque_min"] = int(linha["estoque_min"])
            existe = con.execute("SELECT id FROM produtos WHERE sku=?", (linha.get("sku"),)).fetchone()
            salvar_produto(con, linha, existe[0] if existe else None)
            if existe:
                atualizados += 1
            else:
                criados += 1
        except (ErroRegra, ValueError, epcs_mod.ErroEpc) as e:
            erros.append(f"linha {n}: {e}")
    return {"criados": criados, "atualizados": atualizados, "erros": erros}


# ================================================================ OF (ordem de fabricação) e emissão
def criar_ordem(con, ctx: Ctx, numero: str | None, itens: list[dict], local_id=None, documento=None, observacao=None) -> int:
    itens = [i for i in itens if int(i.get("quantidade") or 0) > 0]
    if not itens:
        raise ErroRegra("Informe pelo menos um produto com quantidade")
    if len({i["produto_id"] for i in itens}) != len(itens):
        raise ErroRegra("O mesmo produto aparece duas vezes na OF")
    if sum(int(i["quantidade"]) for i in itens) > 20000:
        raise ErroRegra("Máximo de 20.000 etiquetas por OF")
    lid = _local_ou_padrao(con, local_id)
    if not numero:
        ultimo = con.execute("SELECT COUNT(*) FROM ordens").fetchone()[0]
        numero = f"OF-{ultimo + 1:06d}"
        while con.execute("SELECT 1 FROM ordens WHERE numero=?", (numero,)).fetchone():
            ultimo += 1
            numero = f"OF-{ultimo + 1:06d}"
    elif con.execute("SELECT 1 FROM ordens WHERE numero=?", (numero.strip(),)).fetchone():
        raise ErroRegra(f"Já existe a OF {numero}")
    cur = con.execute("INSERT INTO ordens (numero, local_id, documento, observacao, criada_em) VALUES (?,?,?,?,?)",
                      (numero.strip(), lid, documento, observacao, db.agora()))
    oid = cur.lastrowid
    agora = db.agora()
    for i in itens:
        prod = produto(con, int(i["produto_id"]))
        if not prod["ativo"]:
            raise ErroRegra(f"Produto {prod['sku']} está inativo")
        q = int(i["quantidade"])
        con.execute("INSERT INTO ordem_itens (ordem_id, produto_id, quantidade) VALUES (?,?,?)", (oid, prod["id"], q))
        for e, serial in gerar_epcs(con, prod, q):
            con.execute("""INSERT INTO etiquetas (epc, produto_id, local_id, status, serial, ordem_id, origem, criada_em, atualizada_em)
                           VALUES (?,?,NULL,'EMITIDA',?,?, 'EMISSAO', ?, ?)""", (e, prod["id"], serial, oid, agora, agora))
            mov(con, ctx, "EMISSAO", e, prod["id"], 0, documento=numero)
    return oid


def listar_ordens(con, status: str | None = None) -> list[dict]:
    sql = """SELECT o.*, l.codigo AS local,
                (SELECT COALESCE(SUM(quantidade),0) FROM ordem_itens WHERE ordem_id=o.id) AS quantidade,
                (SELECT COUNT(*) FROM ordem_itens WHERE ordem_id=o.id) AS itens,
                (SELECT COUNT(*) FROM ordem_leituras WHERE ordem_id=o.id) AS lidas,
                (SELECT COUNT(*) FROM etiquetas WHERE ordem_id=o.id AND impressa_em IS NOT NULL) AS impressas,
                (SELECT COUNT(*) FROM etiquetas WHERE ordem_id=o.id AND gravada_em IS NOT NULL) AS gravadas,
                (SELECT GROUP_CONCAT(p.sku, ', ') FROM ordem_itens i JOIN produtos p ON p.id=i.produto_id WHERE i.ordem_id=o.id) AS skus
             FROM ordens o LEFT JOIN locais l ON l.id=o.local_id"""
    args = ()
    if status:
        sql += " WHERE o.status=?"
        args = (status,)
    return db.linhas(con.execute(sql + " ORDER BY o.id DESC LIMIT 300", args))


def ordem(con, ordem_id: int) -> dict:
    o = con.execute("SELECT o.*, l.codigo AS local FROM ordens o LEFT JOIN locais l ON l.id=o.local_id WHERE o.id=?",
                    (ordem_id,)).fetchone()
    if not o:
        raise ErroRegra("OF não encontrada")
    o = dict(o)
    o["itens"] = db.linhas(con.execute(
        """SELECT i.id, i.produto_id, i.quantidade, p.sku, p.descricao, p.cor, p.tamanho, p.gtin,
                  (SELECT COUNT(*) FROM etiquetas t WHERE t.ordem_id=i.ordem_id AND t.produto_id=i.produto_id AND t.status!='CANCELADA') AS etiquetas,
                  (SELECT COUNT(*) FROM etiquetas t WHERE t.ordem_id=i.ordem_id AND t.produto_id=i.produto_id AND t.impressa_em IS NOT NULL) AS impressas,
                  (SELECT COUNT(*) FROM etiquetas t WHERE t.ordem_id=i.ordem_id AND t.produto_id=i.produto_id AND t.gravada_em IS NOT NULL) AS gravadas,
                  (SELECT COUNT(*) FROM ordem_leituras r JOIN etiquetas t ON t.epc=r.epc
                     WHERE r.ordem_id=i.ordem_id AND t.produto_id=i.produto_id) AS lidas
           FROM ordem_itens i JOIN produtos p ON p.id=i.produto_id WHERE i.ordem_id=? ORDER BY p.sku, p.cor, p.tamanho""",
        (ordem_id,)))
    o["quantidade"] = sum(i["quantidade"] for i in o["itens"])
    o["lidas"] = sum(i["lidas"] for i in o["itens"])
    return o


def etiquetas_ordem(con, ordem_id: int, somente=None) -> list[dict]:
    sql = SQL_ETIQUETA + " WHERE t.ordem_id=?"
    args = [ordem_id]
    if somente == "nao_impressas":
        sql += " AND t.impressa_em IS NULL AND t.status='EMITIDA'"
    elif somente == "nao_gravadas":
        sql += " AND t.gravada_em IS NULL AND t.status='EMITIDA'"
    sql += " ORDER BY p.sku, p.cor, p.tamanho, t.serial"
    lista = db.linhas(con.execute(sql, args))
    lidas = {r[0] for r in con.execute("SELECT epc FROM ordem_leituras WHERE ordem_id=?", (ordem_id,))}
    for t in lista:
        t["lida"] = t["epc"] in lidas
    return lista


def _ordem_aberta(con, ordem_id) -> dict:
    o = con.execute("SELECT * FROM ordens WHERE id=?", (ordem_id,)).fetchone()
    if not o:
        raise ErroRegra("OF não encontrada")
    if o["status"] != "ABERTA":
        raise ErroRegra(f"A OF {o['numero']} está {o['status'].lower()}")
    return dict(o)


def marcar_impressas(con, epcs) -> None:
    agora = db.agora()
    con.executemany("UPDATE etiquetas SET impressa_em=? WHERE epc=?", [(agora, e) for e in _norm(epcs)])


def proxima_para_gravar(con, ordem_id: int, produto_id: int | None = None) -> dict | None:
    """Coletor sem impressora RFID: a próxima etiqueta da OF que ainda não foi gravada."""
    _ordem_aberta(con, ordem_id)
    sql = SQL_ETIQUETA + " WHERE t.ordem_id=? AND t.status='EMITIDA' AND t.gravada_em IS NULL"
    args = [ordem_id]
    if produto_id:
        sql += " AND t.produto_id=?"
        args.append(produto_id)
    r = con.execute(sql + " ORDER BY p.sku, p.cor, p.tamanho, t.serial LIMIT 1", args).fetchone()
    return dict(r) if r else None


def registrar_gravacao(con, ctx: Ctx, epc_novo: str, epc_antigo: str | None = None) -> dict:
    """O coletor gravou epc_novo numa etiqueta física (que antes tinha epc_antigo)."""
    novo = epcs_mod.normalizar(epc_novo)
    antigo = epcs_mod.normalizar(epc_antigo or "")
    t = _etiqueta(con, novo)
    if not t:
        raise ErroRegra("Esse EPC não foi emitido pelo sistema")
    _atualizar(con, novo, gravada_em=db.agora())
    if antigo and antigo != novo:
        velho = _etiqueta(con, antigo)
        if velho and velho["status"] in ("EMITIDA", "ESTOQUE"):
            # a etiqueta física deixou de ter o EPC antigo: ele não existe mais
            if velho["status"] == "ESTOQUE":
                mov(con, ctx, "AJUSTE_SAIDA", antigo, velho["produto_id"], -1, velho["local_id"], motivo="REGRAVADA", documento=novo)
            _atualizar(con, antigo, status="CANCELADA")
            mov(con, ctx, "CANCELAMENTO", antigo, velho["produto_id"], 0, motivo="REGRAVADA", documento=novo)
    mov(con, ctx, "REGRAVACAO", novo, t["produto_id"], 0, motivo=f"EPC anterior {antigo}" if antigo else None)
    return dict(con.execute(SQL_ETIQUETA + " WHERE t.epc=?", (novo,)).fetchone())


def ler_ordem(con, ordem_id: int, epcs) -> list[dict]:
    """Finalização por RFID: cada peça lida é conferida com a OF."""
    o = _ordem_aberta(con, ordem_id)
    saida = []
    agora = db.agora()
    for s in situacao(con, epcs):
        e = s["epc"]
        if s.get("status") is None:
            s.update(ok=False, motivo="Etiqueta não cadastrada")
        elif s.get("ordem_id") != o["id"]:
            s.update(ok=False, motivo=f"Não é desta OF ({s.get('ordem') or 'sem OF'})")
        elif s["status"] != "EMITIDA":
            s.update(ok=False, motivo=f"Etiqueta {s['status'].lower()}")
        else:
            nova = con.execute("INSERT OR IGNORE INTO ordem_leituras (ordem_id, epc, data_hora) VALUES (?,?,?)",
                               (o["id"], e, agora)).rowcount
            s.update(ok=True, nova=bool(nova))
        saida.append(s)
    marcar_leitura(con, epcs)
    return saida


def remover_leitura_ordem(con, ordem_id: int, epc: str) -> None:
    _ordem_aberta(con, ordem_id)
    con.execute("DELETE FROM ordem_leituras WHERE ordem_id=? AND epc=?", (ordem_id, epcs_mod.normalizar(epc)))


def limpar_leituras_ordem(con, ordem_id: int) -> None:
    _ordem_aberta(con, ordem_id)
    con.execute("DELETE FROM ordem_leituras WHERE ordem_id=?", (ordem_id,))


def consolidar_kit(con, ctx: Ctx, ordem_id: int, produto_origem: int, produto_destino: int) -> int:
    """Troca o produto de destino de um item da OF por outro produto da mesma OF
    (vale para todas as peças daquela cor/tamanho). As etiquetas mantêm o EPC."""
    o = _ordem_aberta(con, ordem_id)
    if produto_origem == produto_destino:
        raise ErroRegra("Escolha um produto de destino diferente")
    itens = {r["produto_id"]: dict(r) for r in con.execute("SELECT * FROM ordem_itens WHERE ordem_id=?", (ordem_id,))}
    if produto_origem not in itens or produto_destino not in itens:
        raise ErroRegra("Os dois produtos precisam fazer parte da OF")
    tags = [r[0] for r in con.execute("SELECT epc FROM etiquetas WHERE ordem_id=? AND produto_id=? AND status='EMITIDA'",
                                      (ordem_id, produto_origem))]
    for e in tags:
        _atualizar(con, e, produto_id=produto_destino)
        mov(con, ctx, "CONSOLIDACAO", e, produto_destino, 0, motivo=f"Kit: de {produto(con, produto_origem)['sku']}",
            documento=o["numero"])
    con.execute("UPDATE ordem_itens SET quantidade=quantidade+? WHERE ordem_id=? AND produto_id=?",
                (itens[produto_origem]["quantidade"], ordem_id, produto_destino))
    con.execute("DELETE FROM ordem_itens WHERE ordem_id=? AND produto_id=?", (ordem_id, produto_origem))
    return len(tags)


def finalizar_ordem(con, ctx: Ctx, ordem_id: int, cancelar_nao_lidas: bool = False) -> dict:
    """As peças lidas entram no estoque do local da OF. As não lidas continuam EMITIDAS
    (podem entrar depois pela Entrada) ou são canceladas."""
    o = _ordem_aberta(con, ordem_id)
    resumo = ordem(con, ordem_id)
    lidas = [r[0] for r in con.execute(
        "SELECT r.epc FROM ordem_leituras r JOIN etiquetas t ON t.epc=r.epc WHERE r.ordem_id=? AND t.status='EMITIDA'", (ordem_id,))]
    if not lidas:
        raise ErroRegra("Nenhuma peça foi lida: leia as etiquetas antes de finalizar")
    for e in lidas:
        t = _etiqueta(con, e)
        _atualizar(con, e, status="ESTOQUE", local_id=o["local_id"])
        mov(con, ctx, "ENTRADA", e, t["produto_id"], 1, destino_local=o["local_id"], motivo="FINALIZACAO OF", documento=o["numero"])
    canceladas = 0
    if cancelar_nao_lidas:
        for r in con.execute("SELECT epc, produto_id FROM etiquetas WHERE ordem_id=? AND status='EMITIDA'", (ordem_id,)).fetchall():
            _atualizar(con, r["epc"], status="CANCELADA")
            mov(con, ctx, "CANCELAMENTO", r["epc"], r["produto_id"], 0, motivo="NAO LIDA NA OF", documento=o["numero"])
            canceladas += 1
    con.execute("UPDATE ordens SET status='FINALIZADA', finalizada_em=? WHERE id=?", (db.agora(), ordem_id))
    divergencias = [{"sku": i["sku"], "descricao": i["descricao"], "cor": i["cor"], "tamanho": i["tamanho"],
                     "prevista": i["quantidade"], "lida": i["lidas"]} for i in resumo["itens"] if i["lidas"] != i["quantidade"]]
    return {"entradas": len(lidas), "canceladas": canceladas, "divergencias": divergencias}


def cancelar_ordem(con, ctx: Ctx, ordem_id: int) -> int:
    o = _ordem_aberta(con, ordem_id)
    n = 0
    for r in con.execute("SELECT epc, produto_id FROM etiquetas WHERE ordem_id=? AND status='EMITIDA'", (ordem_id,)).fetchall():
        _atualizar(con, r["epc"], status="CANCELADA")
        mov(con, ctx, "CANCELAMENTO", r["epc"], r["produto_id"], 0, motivo="OF CANCELADA", documento=o["numero"])
        n += 1
    con.execute("UPDATE ordens SET status='CANCELADA', finalizada_em=? WHERE id=?", (db.agora(), ordem_id))
    return n


# ================================================================ operações por etiqueta
def _checar(t, operacao: str, local_id=None, produto_id=None) -> str | None:
    """Motivo pelo qual a operação não pode ser feita nessa etiqueta (None = pode)."""
    if operacao == "vincular":
        # etiqueta baixada ou cancelada pode ser reaproveitada (tag rígida, lacre...)
        if t and t["status"] in ("EMITIDA", "ESTOQUE"):
            if produto_id is None or t["produto_id"] != produto_id:
                return f"Já vinculada a outro produto ({t['status'].lower()})"
            if t["status"] == "ESTOQUE":
                return "Já está no estoque"
        return None
    if t is None:
        return "Etiqueta não cadastrada (use Vincular)"
    st = t["status"]
    if operacao == "entrada":
        if st == "ESTOQUE":
            return "Já está no estoque"
        if st == "BAIXADA":
            return "Etiqueta baixada (use Estornar)"
        if st == "CANCELADA":
            return "Etiqueta cancelada"
        return None
    if operacao in ("baixa", "transferencia", "expedicao"):
        if st != "ESTOQUE":
            return {"EMITIDA": "Ainda não entrou no estoque", "BAIXADA": "Já foi baixada", "CANCELADA": "Etiqueta cancelada"}[st]
        if local_id and t["local_id"] != int(local_id):
            return "Está em outro local"
        return None
    if operacao == "estorno":
        return None if st == "BAIXADA" else "Só etiqueta baixada pode ser estornada"
    if operacao == "cancelar":
        return None if st in ("EMITIDA", "ESTOQUE") else f"Etiqueta {st.lower()}"
    raise ErroRegra(f"Operação desconhecida: {operacao}")


def verificar(con, epcs, operacao: str, local_id=None, produto_id=None) -> list[dict]:
    """Confere as etiquetas lidas para uma operação, sem gravar nada (a tela monta a lista)."""
    saida = []
    for s in situacao(con, epcs):
        t = _etiqueta(con, s["epc"])
        motivo = _checar(t, operacao, local_id, produto_id)
        s.update(ok=motivo is None, motivo=motivo)
        saida.append(s)
    marcar_leitura(con, epcs)
    return saida


def _executar(con, epcs, operacao, local_id, fazer, produto_id=None) -> dict:
    ok, erros = [], []
    for e in _norm(epcs):
        t = _etiqueta(con, e)
        motivo = _checar(t, operacao, local_id, produto_id)
        if motivo:
            erros.append({"epc": e, "motivo": motivo})
            continue
        fazer(e, t)
        ok.append(e)
    return {"ok": ok, "erros": erros, "quantidade": len(ok)}


def vincular(con, ctx: Ctx, epcs, produto_id: int, local_id=None, ativar: bool = True, documento=None) -> dict:
    """Etiqueta que já tem EPC (virgem, de fornecedor, reaproveitada) passa a ser uma peça do produto."""
    prod = produto(con, produto_id)
    if not prod["ativo"]:
        raise ErroRegra("Produto inativo")
    lid = _local_ou_padrao(con, local_id) if ativar else None
    agora = db.agora()

    def fazer(e, t):
        if t:
            _atualizar(con, e, produto_id=produto_id, status="ESTOQUE" if ativar else "EMITIDA", local_id=lid,
                       origem="VINCULACAO", ordem_id=None)
        else:
            con.execute("""INSERT INTO etiquetas (epc, produto_id, local_id, status, origem, criada_em, atualizada_em)
                           VALUES (?,?,?,?, 'VINCULACAO', ?, ?)""", (e, produto_id, lid, "ESTOQUE" if ativar else "EMITIDA", agora, agora))
        mov(con, ctx, "VINCULACAO", e, produto_id, 0, documento=documento)
        if ativar:
            mov(con, ctx, "ENTRADA", e, produto_id, 1, destino_local=lid, documento=documento)
    return _executar(con, epcs, "vincular", None, fazer, produto_id)


def entrada(con, ctx: Ctx, epcs, local_id=None, documento=None) -> dict:
    """Ativa etiquetas EMITIDAS: a peça entra no estoque do local."""
    lid = _local_ou_padrao(con, local_id)

    def fazer(e, t):
        _atualizar(con, e, status="ESTOQUE", local_id=lid)
        mov(con, ctx, "ENTRADA", e, t["produto_id"], 1, destino_local=lid, documento=documento)
    return _executar(con, epcs, "entrada", None, fazer)


def baixar(con, ctx: Ctx, epcs, motivo: str, local_id=None, documento=None) -> dict:
    if motivo not in MOTIVOS_BAIXA:
        raise ErroRegra("Motivo de baixa inválido")

    def fazer(e, t):
        _atualizar(con, e, status="BAIXADA")
        mov(con, ctx, "BAIXA", e, t["produto_id"], -1, origem_local=t["local_id"], motivo=motivo, documento=documento)
    return _executar(con, epcs, "baixa", local_id, fazer)


def estornar(con, ctx: Ctx, epcs, documento=None) -> dict:
    """Desfaz a baixa: a peça volta para o local onde estava."""
    def fazer(e, t):
        lid = t["local_id"] or local_padrao(con)
        _atualizar(con, e, status="ESTOQUE", local_id=lid)
        mov(con, ctx, "ESTORNO", e, t["produto_id"], 1, destino_local=lid, documento=documento)
    return _executar(con, epcs, "estorno", None, fazer)


def transferir(con, ctx: Ctx, epcs, destino_id: int, origem_id=None, documento=None) -> dict:
    destino = local(con, destino_id)
    if not destino["ativo"]:
        raise ErroRegra("Local de destino inativo")

    def fazer(e, t):
        if t["local_id"] == destino_id:
            return
        _atualizar(con, e, local_id=destino_id)
        mov(con, ctx, "TRANSFERENCIA", e, t["produto_id"], 0, t["local_id"], destino_id, documento=documento)
    return _executar(con, epcs, "transferencia", origem_id, fazer)


def cancelar_etiquetas(con, ctx: Ctx, epcs, motivo: str | None = None) -> dict:
    def fazer(e, t):
        if t["status"] == "ESTOQUE":
            mov(con, ctx, "AJUSTE_SAIDA", e, t["produto_id"], -1, t["local_id"], motivo=motivo or "CANCELADA")
        _atualizar(con, e, status="CANCELADA")
        mov(con, ctx, "CANCELAMENTO", e, t["produto_id"], 0, motivo=motivo)
    return _executar(con, epcs, "cancelar", None, fazer)


def historico(con, epc: str) -> dict:
    """Rastreabilidade: tudo sobre uma etiqueta."""
    e = epcs_mod.normalizar(epc)
    r = con.execute(SQL_ETIQUETA + " WHERE t.epc=?", (e,)).fetchone()
    d = epcs_mod.decodificar(e)
    return {
        "epc": e, "decodificado": d.dict(), "etiqueta": dict(r) if r else None,
        "sugerido": None if r else (situacao(con, [e])[0].get("sugerido")),
        "movimentos": db.linhas(con.execute(
            """SELECT m.*, lo.codigo AS origem_local, ld.codigo AS destino_local, p.sku
               FROM movimentos m JOIN produtos p ON p.id=m.produto_id
               LEFT JOIN locais lo ON lo.id=m.local_origem LEFT JOIN locais ld ON ld.id=m.local_destino
               WHERE m.epc=? ORDER BY m.id DESC""", (e,))),
    }


# ================================================================ estoque e painel
def estoque(con, local_id=None, grupo=None, busca=None) -> list[dict]:
    """Quantidade por produto e local (só etiquetas no estoque)."""
    sql = """SELECT p.id AS produto_id, p.sku, p.descricao, p.grupo, p.subgrupo, p.cor, p.tamanho, p.gtin, p.preco,
                    p.estoque_min, l.id AS local_id, l.codigo AS local, COUNT(t.epc) AS quantidade
             FROM etiquetas t JOIN produtos p ON p.id=t.produto_id JOIN locais l ON l.id=t.local_id
             WHERE t.status='ESTOQUE'"""
    args = []
    if local_id:
        sql += " AND t.local_id=?"
        args.append(local_id)
    if grupo:
        sql += " AND p.grupo=?"
        args.append(grupo)
    if busca:
        sql += " AND (p.sku LIKE ? OR p.descricao LIKE ? OR p.gtin LIKE ? OR p.cor LIKE ?)"
        args += [f"%{busca}%"] * 4
    return db.linhas(con.execute(sql + " GROUP BY p.id, l.id ORDER BY p.sku, p.cor, p.tamanho, l.codigo", args))


def painel(con) -> dict:
    def v(sql, *a):
        return con.execute(sql, a).fetchone()[0] or 0
    dias = db.linhas(con.execute(
        """SELECT substr(data_hora,1,10) AS dia,
                  SUM(CASE WHEN tipo='ENTRADA' THEN 1 ELSE 0 END) AS entradas,
                  SUM(CASE WHEN tipo='BAIXA' THEN 1 ELSE 0 END) AS baixas
           FROM movimentos WHERE data_hora >= date('now','localtime','-13 day')
           GROUP BY dia ORDER BY dia"""))
    return {
        "empresa": db.config(con).get("empresa"),
        "em_estoque": v("SELECT COUNT(*) FROM etiquetas WHERE status='ESTOQUE'"),
        "valor_estoque": v("SELECT SUM(p.preco) FROM etiquetas t JOIN produtos p ON p.id=t.produto_id WHERE t.status='ESTOQUE'"),
        "emitidas": v("SELECT COUNT(*) FROM etiquetas WHERE status='EMITIDA'"),
        "baixadas_hoje": v("SELECT COUNT(*) FROM movimentos WHERE tipo='BAIXA' AND substr(data_hora,1,10)=?", db.hoje()),
        "entradas_hoje": v("SELECT COUNT(*) FROM movimentos WHERE tipo='ENTRADA' AND substr(data_hora,1,10)=?", db.hoje()),
        "produtos": v("SELECT COUNT(*) FROM produtos WHERE ativo=1"),
        "ordens_abertas": v("SELECT COUNT(*) FROM ordens WHERE status='ABERTA'"),
        "pedidos_abertos": v("SELECT COUNT(*) FROM pedidos WHERE status='ABERTO'"),
        "inventarios_abertos": v("SELECT COUNT(*) FROM inventarios WHERE status='ABERTO'"),
        "alertas": v("SELECT COUNT(*) FROM alertas WHERE lido=0"),
        "por_local": db.linhas(con.execute(
            """SELECT l.id, l.codigo, l.nome, l.tipo, COUNT(t.epc) AS quantidade FROM locais l
               LEFT JOIN etiquetas t ON t.local_id=l.id AND t.status='ESTOQUE' WHERE l.ativo=1
               GROUP BY l.id ORDER BY l.codigo""")),
        "por_grupo": db.linhas(con.execute(
            """SELECT COALESCE(p.grupo,'(sem grupo)') AS grupo, COUNT(*) AS quantidade FROM etiquetas t
               JOIN produtos p ON p.id=t.produto_id WHERE t.status='ESTOQUE' GROUP BY 1 ORDER BY 2 DESC LIMIT 12""")),
        "dias": dias,
        "abaixo_minimo": db.linhas(con.execute(
            """SELECT p.id, p.sku, p.descricao, p.cor, p.tamanho, p.estoque_min,
                      (SELECT COUNT(*) FROM etiquetas t WHERE t.produto_id=p.id AND t.status='ESTOQUE') AS saldo
               FROM produtos p WHERE p.ativo=1 AND p.estoque_min > 0 AND
                     (SELECT COUNT(*) FROM etiquetas t WHERE t.produto_id=p.id AND t.status='ESTOQUE') < p.estoque_min
               ORDER BY p.sku LIMIT 50""")),
        "inventarios": db.linhas(con.execute(
            """SELECT id, nome, fechado_em, esperado, ok, faltas, sobras FROM inventarios
               WHERE status='FINALIZADO' ORDER BY id DESC LIMIT 6""")),
    }


# ================================================================ inventário
def criar_inventario(con, nome: str, local_id=None, grupo=None) -> int:
    if local_id:
        local(con, local_id)
    nome = (nome or "").strip() or f"Inventário {db.agora()[:16]}"
    cur = con.execute("INSERT INTO inventarios (nome, local_id, grupo, aberto_em) VALUES (?,?,?,?)",
                      (nome, local_id or None, (grupo or "").strip() or None, db.agora()))
    return cur.lastrowid


def _inventario(con, inv_id) -> dict:
    r = con.execute("SELECT i.*, l.codigo AS local FROM inventarios i LEFT JOIN locais l ON l.id=i.local_id WHERE i.id=?",
                    (inv_id,)).fetchone()
    if not r:
        raise ErroRegra("Inventário não encontrado")
    return dict(r)


def ler_inventario(con, inv_id: int, epcs, dispositivo=None) -> dict:
    inv = _inventario(con, inv_id)
    if inv["status"] != "ABERTO":
        raise ErroRegra("Inventário já fechado")
    agora = db.agora()
    novas = 0
    for e in _norm(epcs):
        novas += con.execute("INSERT OR IGNORE INTO inventario_leituras (inventario_id, epc, data_hora, dispositivo) VALUES (?,?,?,?)",
                             (inv_id, e, agora, dispositivo)).rowcount
        t = _etiqueta(con, e)
        if t and t["status"] == "BAIXADA":
            p = produto(con, t["produto_id"])
            alerta(con, "BAIXADA_NO_ESTOQUE", f"Etiqueta baixada encontrada no inventário {inv['nome']}: {p['sku']} {p['descricao']}", e)
    marcar_leitura(con, epcs)
    total = con.execute("SELECT COUNT(*) FROM inventario_leituras WHERE inventario_id=?", (inv_id,)).fetchone()[0]
    return {"novas": novas, "lidas": total}


def _classificar_inventario(con, inv: dict) -> list[dict]:
    """Compara o esperado (estoque do escopo) com o lido."""
    filtro, args = "t.status='ESTOQUE'", []
    if inv["local_id"]:
        filtro += " AND t.local_id=?"
        args.append(inv["local_id"])
    if inv["grupo"]:
        filtro += " AND p.grupo=?"
        args.append(inv["grupo"])
    esperadas = {r["epc"]: dict(r) for r in con.execute(SQL_ETIQUETA + " WHERE " + filtro, args)}
    lidas = [r[0] for r in con.execute("SELECT epc FROM inventario_leituras WHERE inventario_id=?", (inv["id"],))]
    lidas_set = set(lidas)
    saida = []
    for e, t in esperadas.items():
        t["situacao"] = "OK" if e in lidas_set else "FALTA"
        saida.append(t)
    for e in lidas:
        if e in esperadas:
            continue
        r = con.execute(SQL_ETIQUETA + " WHERE t.epc=?", (e,)).fetchone()
        if r:
            t = dict(r)
            if inv["grupo"] and t["grupo"] != inv["grupo"]:
                continue   # inventário parcial: peça de outro grupo não conta
            if t["status"] == "ESTOQUE":
                t["situacao"] = "OUTRO_LOCAL"
            elif t["status"] == "BAIXADA":
                t["situacao"] = "BAIXADA"
            else:
                t["situacao"] = "SOBRA"      # emitida (nunca entrou) ou cancelada, mas está aqui
            saida.append(t)
        else:
            s = situacao(con, [e])[0]
            s["situacao"] = "DESCONHECIDA"
            saida.append(s)
    return saida


def inventario(con, inv_id: int) -> dict:
    inv = _inventario(con, inv_id)
    if inv["status"] == "ABERTO":
        etiquetas = _classificar_inventario(con, inv)
    else:
        etiquetas = db.linhas(con.execute(
            """SELECT r.epc, r.situacao, r.produto_id, p.sku, p.descricao, p.cor, p.tamanho, l.codigo AS local
               FROM inventario_resultado r LEFT JOIN produtos p ON p.id=r.produto_id LEFT JOIN locais l ON l.id=r.local_id
               WHERE r.inventario_id=?""", (inv_id,)))
    cont = {s: 0 for s in ("OK", "FALTA", "SOBRA", "OUTRO_LOCAL", "BAIXADA", "DESCONHECIDA")}
    por_produto: dict = {}
    for t in etiquetas:
        cont[t["situacao"]] += 1
        pid = t.get("produto_id")
        if not pid:
            continue
        p = por_produto.setdefault(pid, {"produto_id": pid, "sku": t.get("sku"), "descricao": t.get("descricao"),
                                         "cor": t.get("cor"), "tamanho": t.get("tamanho"), "esperado": 0, "lido": 0})
        if t["situacao"] in ("OK", "FALTA"):
            p["esperado"] += 1
        if t["situacao"] != "FALTA":
            p["lido"] += 1
    for p in por_produto.values():
        p["diferenca"] = p["lido"] - p["esperado"]
    esperado = cont["OK"] + cont["FALTA"]
    inv.update(
        etiquetas=etiquetas, contagem=cont, esperado=esperado,
        lidas=con.execute("SELECT COUNT(*) FROM inventario_leituras WHERE inventario_id=?", (inv_id,)).fetchone()[0],
        acuracidade=round(100.0 * cont["OK"] / esperado, 1) if esperado else None,
        produtos=sorted(por_produto.values(), key=lambda p: (p["diferenca"] == 0, p["sku"] or "")),
    )
    return inv


def incluir_desconhecida(con, ctx: Ctx, inv_id: int, epc: str, produto_id: int) -> None:
    inv = _inventario(con, inv_id)
    if inv["status"] != "ABERTO":
        raise ErroRegra("Inventário já fechado")
    e = epcs_mod.normalizar(epc)
    if _etiqueta(con, e):
        raise ErroRegra("Essa etiqueta já está cadastrada")
    vincular(con, ctx, [e], produto_id, inv["local_id"], ativar=True, documento=inv["nome"])


def finalizar_inventario(con, ctx: Ctx, inv_id: int, ajustar: bool) -> dict:
    """Guarda o resultado. Com ajustar: faltas saem do estoque, sobras entram e peças de
    outro local passam para o local do inventário."""
    inv = inventario(con, inv_id)
    if inv["status"] != "ABERTO":
        raise ErroRegra("Inventário já fechado")
    doc = f"INV-{inv_id}"
    ajustes = 0
    for t in inv["etiquetas"]:
        con.execute("INSERT OR REPLACE INTO inventario_resultado (inventario_id, epc, produto_id, situacao, local_id) VALUES (?,?,?,?,?)",
                    (inv_id, t["epc"], t.get("produto_id"), t["situacao"], t.get("local_id")))
        if not ajustar:
            continue
        e, sit = t["epc"], t["situacao"]
        destino = inv["local_id"] or t.get("local_id") or local_padrao(con)
        if sit == "FALTA":
            _atualizar(con, e, status="BAIXADA")
            mov(con, ctx, "AJUSTE_SAIDA", e, t["produto_id"], -1, t["local_id"], motivo="FALTA NO INVENTARIO", documento=doc)
            ajustes += 1
        elif sit in ("SOBRA", "BAIXADA"):
            _atualizar(con, e, status="ESTOQUE", local_id=destino)
            mov(con, ctx, "AJUSTE_ENTRADA", e, t["produto_id"], 1, destino_local=destino, motivo="SOBRA NO INVENTARIO", documento=doc)
            ajustes += 1
        elif sit == "OUTRO_LOCAL" and inv["local_id"]:
            _atualizar(con, e, local_id=inv["local_id"])
            mov(con, ctx, "TRANSFERENCIA", e, t["produto_id"], 0, t["local_id"], inv["local_id"], motivo="INVENTARIO", documento=doc)
            ajustes += 1
    c = inv["contagem"]
    con.execute("""UPDATE inventarios SET status='FINALIZADO', fechado_em=?, ajustado=?, esperado=?, lidas=?, ok=?, faltas=?, sobras=?
                   WHERE id=?""", (db.agora(), int(ajustar), inv["esperado"], inv["lidas"], c["OK"], c["FALTA"],
                                   c["SOBRA"] + c["OUTRO_LOCAL"] + c["BAIXADA"] + c["DESCONHECIDA"], inv_id))
    return {"ajustes": ajustes, "acuracidade": inv["acuracidade"], "contagem": c}


# ================================================================ expedição (conferência de embarque)
def criar_pedido(con, numero, tipo, itens, cliente=None, local_id=None, destino_id=None, documento=None) -> int:
    numero = (numero or "").strip()
    if not numero:
        n = con.execute("SELECT COUNT(*) FROM pedidos").fetchone()[0] + 1
        numero = f"PED-{n:06d}"
    if con.execute("SELECT 1 FROM pedidos WHERE numero=?", (numero,)).fetchone():
        raise ErroRegra(f"Já existe o pedido {numero}")
    if tipo not in ("VENDA", "TRANSFERENCIA"):
        raise ErroRegra("Tipo deve ser VENDA ou TRANSFERENCIA")
    if tipo == "TRANSFERENCIA":
        if not destino_id:
            raise ErroRegra("Escolha o local de destino da transferência")
        local(con, destino_id)
        if local_id and int(local_id) == int(destino_id):
            raise ErroRegra("Origem e destino são o mesmo local")
    itens = [i for i in itens if int(i.get("quantidade") or 0) > 0]
    if not itens:
        raise ErroRegra("Informe pelo menos um produto com quantidade")
    cur = con.execute("""INSERT INTO pedidos (numero, tipo, cliente, local_id, destino_id, documento, criado_em)
                         VALUES (?,?,?,?,?,?,?)""", (numero, tipo, cliente, local_id or None, destino_id or None, documento, db.agora()))
    for i in itens:
        produto(con, int(i["produto_id"]))
        try:
            con.execute("INSERT INTO pedido_itens (pedido_id, produto_id, quantidade) VALUES (?,?,?)",
                        (cur.lastrowid, int(i["produto_id"]), int(i["quantidade"])))
        except Exception as e:  # noqa: BLE001
            raise ErroRegra("O mesmo produto aparece duas vezes no pedido") from e
    return cur.lastrowid


def pedido(con, pedido_id: int) -> dict:
    p = con.execute("""SELECT pd.*, l.codigo AS local, d.codigo AS destino FROM pedidos pd
                       LEFT JOIN locais l ON l.id=pd.local_id LEFT JOIN locais d ON d.id=pd.destino_id WHERE pd.id=?""",
                    (pedido_id,)).fetchone()
    if not p:
        raise ErroRegra("Pedido não encontrado")
    p = dict(p)
    p["itens"] = db.linhas(con.execute(
        """SELECT i.id, i.produto_id, i.quantidade, p.sku, p.descricao, p.cor, p.tamanho,
                  (SELECT COUNT(*) FROM pedido_leituras r WHERE r.item_id=i.id) AS lidas
           FROM pedido_itens i JOIN produtos p ON p.id=i.produto_id WHERE i.pedido_id=? ORDER BY p.sku, p.cor, p.tamanho""",
        (pedido_id,)))
    p["leituras"] = db.linhas(con.execute(
        """SELECT r.epc, r.data_hora, p.sku, p.descricao, p.cor, p.tamanho FROM pedido_leituras r
           JOIN pedido_itens i ON i.id=r.item_id JOIN produtos p ON p.id=i.produto_id
           WHERE r.pedido_id=? ORDER BY r.data_hora DESC""", (pedido_id,)))
    p["quantidade"] = sum(i["quantidade"] for i in p["itens"])
    p["lidas"] = sum(i["lidas"] for i in p["itens"])
    return p


def listar_pedidos(con, status=None) -> list[dict]:
    sql = """SELECT pd.*, l.codigo AS local, d.codigo AS destino,
                (SELECT COALESCE(SUM(quantidade),0) FROM pedido_itens WHERE pedido_id=pd.id) AS quantidade,
                (SELECT COUNT(*) FROM pedido_leituras WHERE pedido_id=pd.id) AS lidas
             FROM pedidos pd LEFT JOIN locais l ON l.id=pd.local_id LEFT JOIN locais d ON d.id=pd.destino_id"""
    args = ()
    if status:
        sql += " WHERE pd.status=?"
        args = (status,)
    return db.linhas(con.execute(sql + " ORDER BY pd.id DESC LIMIT 300", args))


def _pedido_aberto(con, pedido_id) -> dict:
    p = pedido(con, pedido_id)
    if p["status"] != "ABERTO":
        raise ErroRegra(f"Pedido {p['numero']} está {p['status'].lower()}")
    return p


def ler_pedido(con, pedido_id: int, epcs) -> list[dict]:
    """Conferência: cada peça lida tem que estar no estoque, no local de saída e fazer parte do pedido."""
    p = _pedido_aberto(con, pedido_id)
    itens = {i["produto_id"]: i for i in p["itens"]}
    lidas = {r[0] for r in con.execute("SELECT epc FROM pedido_leituras WHERE pedido_id=?", (pedido_id,))}
    saida = []
    for s in situacao(con, epcs):
        e = s["epc"]
        t = _etiqueta(con, e)
        if e in lidas:
            s.update(ok=True, nova=False)
        else:
            motivo = _checar(t, "expedicao", p["local_id"])
            item = itens.get(t["produto_id"]) if t else None
            if not motivo and not item:
                motivo = "Produto não faz parte do pedido"
            if not motivo and item["lidas"] >= item["quantidade"]:
                motivo = "Quantidade do item já completa"
            if motivo:
                s.update(ok=False, motivo=motivo)
            else:
                con.execute("INSERT INTO pedido_leituras (pedido_id, epc, item_id, data_hora) VALUES (?,?,?,?)",
                            (pedido_id, e, item["id"], db.agora()))
                item["lidas"] += 1
                lidas.add(e)
                s.update(ok=True, nova=True)
        saida.append(s)
    marcar_leitura(con, epcs)
    return saida


def remover_leitura_pedido(con, pedido_id: int, epc: str) -> None:
    _pedido_aberto(con, pedido_id)
    con.execute("DELETE FROM pedido_leituras WHERE pedido_id=? AND epc=?", (pedido_id, epcs_mod.normalizar(epc)))


def finalizar_pedido(con, ctx: Ctx, pedido_id: int) -> dict:
    p = _pedido_aberto(con, pedido_id)
    epcs = [r[0] for r in con.execute("SELECT epc FROM pedido_leituras WHERE pedido_id=?", (pedido_id,))]
    if not epcs:
        raise ErroRegra("Nenhuma peça conferida")
    if p["tipo"] == "VENDA":
        r = baixar(con, ctx, epcs, "VENDA", p["local_id"], documento=p["numero"])
    else:
        r = transferir(con, ctx, epcs, p["destino_id"], p["local_id"], documento=p["numero"])
    if r["erros"]:
        raise ErroRegra("Algumas peças mudaram desde a conferência: " +
                        ", ".join(f"{x['epc']} ({x['motivo']})" for x in r["erros"][:5]))
    con.execute("UPDATE pedidos SET status='FINALIZADO', finalizado_em=? WHERE id=?", (db.agora(), pedido_id))
    faltas = [{"sku": i["sku"], "descricao": i["descricao"], "cor": i["cor"], "tamanho": i["tamanho"],
               "pedido": i["quantidade"], "conferido": i["lidas"]} for i in p["itens"] if i["lidas"] < i["quantidade"]]
    return {"quantidade": len(epcs), "faltas": faltas}


def cancelar_pedido(con, pedido_id: int) -> None:
    _pedido_aberto(con, pedido_id)
    con.execute("UPDATE pedidos SET status='CANCELADO', finalizado_em=? WHERE id=?", (db.agora(), pedido_id))


# ================================================================ antifurto
def antifurto(con, epcs, ponto: str | None = None) -> list[dict]:
    """Portal / saída: peça que ainda está no estoque (não foi vendida) passando = alarme."""
    saida = []
    for s in situacao(con, epcs):
        if s.get("status") == "ESTOQUE":
            s["alarme"] = True
            alerta(con, "ANTIFURTO", f"Peça não vendida passou{' em ' + ponto if ponto else ''}: "
                                     f"{s['sku']} {s['descricao']} {s.get('cor') or ''} {s.get('tamanho') or ''}".strip(), s["epc"], 2)
        else:
            s["alarme"] = False
        saida.append(s)
    marcar_leitura(con, epcs)
    return saida
