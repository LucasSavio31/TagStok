"""Testes do fluxo completo: OF -> impressão/gravação -> finalização -> estoque -> baixa/expedição/inventário."""
import os
import tempfile

import pytest

os.environ["TAGSTOCK_DB"] = os.path.join(tempfile.mkdtemp(), "teste.db")

from fastapi.testclient import TestClient  # noqa: E402

from app import db, epc  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def c():
    db.DB_PATH = os.path.join(tempfile.mkdtemp(), "teste.db")   # banco novo em cada teste
    with TestClient(app) as cliente:
        r = cliente.post("/api/login", json={"login": "admin", "senha": "admin"})
        assert r.status_code == 200
        cliente.headers["X-Token"] = r.json()["token"]
        yield cliente


def ok(r):
    assert r.status_code == 200, r.text
    return r.json()


def erro(r, trecho=""):
    assert r.status_code == 400, r.text
    assert trecho in r.json()["detail"], r.json()["detail"]


def produto(c, sku, gtin=None, cor="AZUL", tamanho="M", grupo="CAMISETAS"):
    return ok(c.post("/api/produtos", json={"sku": sku, "descricao": f"Camiseta {sku}", "gtin": gtin, "cor": cor,
                                            "tamanho": tamanho, "grupo": grupo, "preco": 59.9}))["id"]


def locais(c):
    return {l["codigo"]: l["id"] for l in ok(c.get("/api/locais"))}


# ---------------------------------------------------------------- EPC
def test_epc_vetor_gs1():
    d = epc.decodificar("3074257BF7194E4000001A85")
    assert d.esquema == "SGTIN-96" and d.gtin == "80614141123458" and d.serial == 6789
    assert epc.sgtin96("80614141123458", 6789, 7, 3) == "3074257BF7194E4000001A85"


def test_etiqueta_nfc(c):
    nfc = "4E4643000004A1B2C3D4E5F6"            # NTAG213 com UID 04A1B2C3D4E5F6, como o app entrega
    d = epc.decodificar(nfc)
    assert d.esquema == "NFC" and d.uid == "04A1B2C3D4E5F6"
    p = produto(c, "NFC-1")
    assert ok(c.post("/api/etiquetas/vincular", json={"epcs": [nfc], "produto_id": p}))["quantidade"] == 1
    assert ok(c.post("/api/etiquetas/baixa", json={"epcs": [nfc], "motivo": "VENDA"}))["quantidade"] == 1
    h = ok(c.get(f"/api/epc/{nfc}"))
    assert h["decodificado"]["esquema"] == "NFC" and h["etiqueta"]["status"] == "BAIXADA"


def test_gtin_invalido_recusado(c):
    erro(c.post("/api/produtos", json={"sku": "X", "descricao": "X", "gtin": "7891234567890"}), "GTIN")


def test_login_obrigatorio():
    with TestClient(app) as anon:
        assert anon.get("/api/painel").status_code == 401
        assert anon.get("/api/status").status_code == 200
        assert anon.post("/api/login", json={"login": "admin", "senha": "errada"}).status_code == 401


# ---------------------------------------------------------------- OF
def test_of_completa(c):
    p1 = produto(c, "CAM-AZ-M", "7891234567895")
    p2 = produto(c, "CAM-AZ-G", None, tamanho="G")
    of = ok(c.post("/api/ordens", json={"itens": [{"produto_id": p1, "quantidade": 3}, {"produto_id": p2, "quantidade": 2}]}))
    assert of["numero"] == "OF-000001" and of["quantidade"] == 5
    tags = ok(c.get(f"/api/ordens/{of['id']}/etiquetas"))
    assert len(tags) == 5 and len({t["epc"] for t in tags}) == 5
    sgtin = [t for t in tags if t["produto_id"] == p1]
    assert all(epc.decodificar(t["epc"]).gtin == "07891234567895" for t in sgtin)
    assert [t["serial"] for t in sgtin] == [1, 2, 3]
    gid = [t for t in tags if t["produto_id"] == p2]
    assert all(epc.decodificar(t["epc"]).esquema == "GID-96" for t in gid)

    zpl = c.get(f"/api/ordens/{of['id']}/etiquetas.zpl").text
    assert zpl.count("^XA") == 5 and sgtin[0]["epc"] in zpl and "^RFW,H" in zpl

    # nova OF do mesmo produto continua a série (nunca repete EPC)
    of2 = ok(c.post("/api/ordens", json={"itens": [{"produto_id": p1, "quantidade": 1}]}))
    assert ok(c.get(f"/api/ordens/{of2['id']}/etiquetas"))[0]["serial"] == 4

    # finalização: lê 4 das 5 peças + uma de outra OF
    lidas = [t["epc"] for t in tags[:4]]
    outra = ok(c.get(f"/api/ordens/{of2['id']}/etiquetas"))[0]["epc"]
    r = ok(c.post(f"/api/ordens/{of['id']}/leituras", json={"epcs": lidas + [outra, "E28011700000020A1B2C3D4E"]}))
    assert sum(1 for x in r["leituras"] if x["ok"]) == 4
    assert r["ordem"]["lidas"] == 4
    fim = ok(c.post(f"/api/ordens/{of['id']}/finalizar", json={}))
    assert fim["entradas"] == 4 and len(fim["divergencias"]) == 1
    assert sum(e["quantidade"] for e in ok(c.get("/api/estoque"))) == 4
    # a não lida continua EMITIDA e pode entrar depois
    ok(c.post("/api/etiquetas/entrada", json={"epcs": [tags[4]["epc"]]}))
    assert sum(e["quantidade"] for e in ok(c.get("/api/estoque"))) == 5


def test_consolidacao_kit(c):
    p1 = produto(c, "KIT-A", tamanho="P")
    p2 = produto(c, "KIT-B", tamanho="M")
    of = ok(c.post("/api/ordens", json={"itens": [{"produto_id": p1, "quantidade": 2}, {"produto_id": p2, "quantidade": 1}]}))
    r = ok(c.post(f"/api/ordens/{of['id']}/consolidar", json={"produto_origem": p1, "produto_destino": p2}))
    assert r["etiquetas"] == 2
    assert len(r["ordem"]["itens"]) == 1 and r["ordem"]["itens"][0]["quantidade"] == 3
    assert all(t["produto_id"] == p2 for t in ok(c.get(f"/api/ordens/{of['id']}/etiquetas")))


def test_gravacao_no_coletor(c):
    p = produto(c, "GRV", "7891234567895")
    of = ok(c.post("/api/ordens", json={"itens": [{"produto_id": p, "quantidade": 2}]}))
    prox = ok(c.get(f"/api/ordens/{of['id']}/proxima"))["etiqueta"]
    ok(c.post("/api/etiquetas/gravacao", json={"epc": prox["epc"], "antigo": "E2000000000000000000AAAA"}))
    prox2 = ok(c.get(f"/api/ordens/{of['id']}/proxima"))["etiqueta"]
    assert prox2["epc"] != prox["epc"]


# ---------------------------------------------------------------- vincular / baixa / estorno / transferência
def test_vincular_baixar_estornar_transferir(c):
    p = produto(c, "VINC")
    loc = locais(c)
    tags = ["E28011700000020A00000001", "E28011700000020A00000002", "E28011700000020A00000003"]
    r = ok(c.post("/api/etiquetas/vincular", json={"epcs": tags, "produto_id": p, "local_id": loc["DEP-01"]}))
    assert r["quantidade"] == 3
    # vincular de novo a outro produto: recusado
    p2 = produto(c, "OUTRO")
    r = ok(c.post("/api/etiquetas/vincular", json={"epcs": tags[:1], "produto_id": p2}))
    assert r["quantidade"] == 0 and "outro produto" in r["erros"][0]["motivo"]

    v = ok(c.post("/api/etiquetas/verificar", json={"epcs": tags, "operacao": "baixa", "local_id": loc["LOJA-01"]}))
    assert not any(x["ok"] for x in v) and v[0]["motivo"] == "Está em outro local"

    ok(c.post("/api/etiquetas/transferencia", json={"epcs": tags[:2], "destino_id": loc["LOJA-01"]}))
    est = {e["local"]: e["quantidade"] for e in ok(c.get("/api/estoque"))}
    assert est == {"DEP-01": 1, "LOJA-01": 2}

    r = ok(c.post("/api/etiquetas/baixa", json={"epcs": tags, "motivo": "VENDA", "local_id": loc["LOJA-01"]}))
    assert r["quantidade"] == 2 and len(r["erros"]) == 1
    erro(c.post("/api/etiquetas/baixa", json={"epcs": tags, "motivo": "XX"}), "Motivo")
    ok(c.post("/api/etiquetas/estorno", json={"epcs": tags[:1]}))
    h = ok(c.get(f"/api/epc/{tags[0]}"))
    assert h["etiqueta"]["status"] == "ESTOQUE" and h["etiqueta"]["local"] == "LOJA-01"
    assert [m["tipo"] for m in h["movimentos"]][:3] == ["ESTORNO", "BAIXA", "TRANSFERENCIA"]
    # reaproveitar etiqueta baixada em outro produto
    r = ok(c.post("/api/etiquetas/vincular", json={"epcs": [tags[1]], "produto_id": p2}))
    assert r["quantidade"] == 1


# ---------------------------------------------------------------- inventário
def test_inventario(c):
    p = produto(c, "INV", "7891234567895")
    loc = locais(c)
    of = ok(c.post("/api/ordens", json={"itens": [{"produto_id": p, "quantidade": 4}], "local_id": loc["DEP-01"]}))
    tags = [t["epc"] for t in ok(c.get(f"/api/ordens/{of['id']}/etiquetas"))]
    ok(c.post(f"/api/ordens/{of['id']}/leituras", json={"epcs": tags}))
    ok(c.post(f"/api/ordens/{of['id']}/finalizar", json={}))
    ok(c.post("/api/etiquetas/transferencia", json={"epcs": [tags[3]], "destino_id": loc["LOJA-01"]}))
    ok(c.post("/api/etiquetas/baixa", json={"epcs": [tags[2]], "motivo": "VENDA"}))
    # SGTIN de fornecedor que o sistema não conhece, mas o GTIN é de um produto cadastrado
    desconhecida = epc.sgtin96("7891234567895", 999999, 7, 1)

    inv = ok(c.post("/api/inventarios", json={"nome": "Depósito", "local_id": loc["DEP-01"]}))["id"]
    ok(c.post(f"/api/inventarios/{inv}/leituras", json={"epcs": [tags[0], tags[2], tags[3], desconhecida]}))
    d = ok(c.get(f"/api/inventarios/{inv}"))
    assert d["contagem"]["OK"] == 1 and d["contagem"]["FALTA"] == 1
    assert d["contagem"]["BAIXADA"] == 1 and d["contagem"]["OUTRO_LOCAL"] == 1 and d["contagem"]["DESCONHECIDA"] == 1
    assert d["acuracidade"] == 50.0
    desc = [t for t in d["etiquetas"] if t["situacao"] == "DESCONHECIDA"][0]
    assert desc["sugerido"]["id"] == p
    assert any(a["tipo"] == "BAIXADA_NO_ESTOQUE" for a in ok(c.get("/api/alertas")))
    ok(c.post(f"/api/inventarios/{inv}/incluir", json={"epc": desconhecida, "produto_id": p}))

    fim = ok(c.post(f"/api/inventarios/{inv}/finalizar", json={"ajustar": True}))
    assert fim["ajustes"] == 3   # falta sai, baixada volta, outro local vem para o depósito
    est = {e["local"]: e["quantidade"] for e in ok(c.get("/api/estoque"))}
    assert est == {"DEP-01": 4}
    assert ok(c.get(f"/api/inventarios/{inv}"))["status"] == "FINALIZADO"


# ---------------------------------------------------------------- expedição e antifurto
def test_expedicao_e_antifurto(c):
    p1 = produto(c, "EXP-1")
    p2 = produto(c, "EXP-2")
    loc = locais(c)
    t1 = [f"E28011700000020B0000000{i}" for i in range(3)]
    t2 = ["E28011700000020C00000001"]
    ok(c.post("/api/etiquetas/vincular", json={"epcs": t1, "produto_id": p1, "local_id": loc["DEP-01"]}))
    ok(c.post("/api/etiquetas/vincular", json={"epcs": t2, "produto_id": p2, "local_id": loc["DEP-01"]}))

    ped = ok(c.post("/api/pedidos", json={"cliente": "Cliente", "local_id": loc["DEP-01"],
                                          "itens": [{"produto_id": p1, "quantidade": 2}]}))
    r = ok(c.post(f"/api/pedidos/{ped['id']}/leituras", json={"epcs": t1 + t2}))
    oks = [x for x in r["leituras"] if x["ok"]]
    assert len(oks) == 2
    assert {x["motivo"] for x in r["leituras"] if not x["ok"]} == {"Quantidade do item já completa", "Produto não faz parte do pedido"}
    fim = ok(c.post(f"/api/pedidos/{ped['id']}/finalizar"))
    assert fim["quantidade"] == 2 and fim["faltas"] == []

    af = ok(c.post("/api/antifurto", json={"epcs": t1 + t2}))
    alarmes = {x["epc"] for x in af if x["alarme"]}
    assert alarmes == {t1[2], t2[0]}   # as vendidas passam; as que estão no estoque disparam
    assert sum(1 for a in ok(c.get("/api/alertas")) if a["tipo"] == "ANTIFURTO") == 2

    # transferência por pedido
    ped2 = ok(c.post("/api/pedidos", json={"tipo": "TRANSFERENCIA", "local_id": loc["DEP-01"], "destino_id": loc["LOJA-01"],
                                           "itens": [{"produto_id": p2, "quantidade": 1}]}))
    ok(c.post(f"/api/pedidos/{ped2['id']}/leituras", json={"epcs": t2}))
    ok(c.post(f"/api/pedidos/{ped2['id']}/finalizar"))
    assert ok(c.get(f"/api/epc/{t2[0]}"))["etiqueta"]["local"] == "LOJA-01"


# ---------------------------------------------------------------- diversos
def test_importar_produtos_e_painel(c):
    r = ok(c.post("/api/produtos/importar", json={"csv": "sku;descricao;gtin;cor;tamanho;preco\nA1;Calça;7891234567895;PRETO;38;129,90\n"
                                                         "A2;Calça;;PRETO;40;129,90\nA3;;;;;\n"}))
    assert r["criados"] == 2 and len(r["erros"]) == 1
    r = ok(c.post("/api/produtos/importar", json={"csv": "sku;descricao;preco\nA1;Calça jeans;99,90\n"}))
    assert r["atualizados"] == 1
    p = ok(c.get("/api/produtos/codigo/7891234567895"))
    assert p["descricao"] == "Calça jeans" and p["preco"] == 99.9
    painel = ok(c.get("/api/painel"))
    assert painel["produtos"] == 2 and len(painel["por_local"]) == 2


def test_excluir_produtos_em_lote(c):
    a, b, com_tag = produto(c, "DEL-A"), produto(c, "DEL-B"), produto(c, "DEL-C")
    ok(c.post("/api/etiquetas/vincular", json={"epcs": ["E28011700000020D00000001"], "produto_id": com_tag}))
    r = ok(c.post("/api/produtos/excluir", json={"ids": [a, b, com_tag]}))
    assert r == {"excluidos": 2, "mantidos": ["DEL-C"]}
    assert [p["sku"] for p in ok(c.get("/api/produtos"))] == ["DEL-C"]


def test_estacao_remota(c):
    ok(c.post("/api/remoto/comando", json={"acao": "limpar"}))
    ok(c.post("/api/remoto/comando", json={"acao": "ler", "potencia": 50}))
    cmds = ok(c.get("/api/remoto/comandos", params={"apos": 0, "dispositivo": "MC33"}))
    assert [x["acao"] for x in cmds["comandos"]][-1] == "ler"
    ok(c.post("/api/remoto/leituras", json={"epcs": ["E2801170000002AA00000001", "E2801170000002AA00000001"]}))
    e = ok(c.get("/api/remoto/estado"))
    assert e["online"] and e["leituras"][0]["vezes"] == 2 and e["leituras"][0]["status"] is None
    erro(c.post("/api/remoto/comando", json={"acao": "gravar", "texto": "XYZ"}), "hexadecimais")


def test_usuarios(c):
    ok(c.post("/api/usuarios", json={"login": "joao", "nome": "João", "senha": "1234"}))
    with TestClient(app) as outro:
        tk = ok(outro.post("/api/login", json={"login": "joao", "senha": "1234"}))["token"]
        outro.headers["X-Token"] = tk
        assert outro.get("/api/usuarios").status_code == 403
        assert outro.get("/api/painel").status_code == 200
