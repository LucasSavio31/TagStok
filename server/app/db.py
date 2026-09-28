"""Banco de dados SQLite do TagStock (um arquivo, em AppData\\Local\\TagStock\\tagstock.db)."""
import hashlib
import os
import secrets
import socket
import sqlite3
from datetime import datetime

DB_PADRAO = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "TagStock", "tagstock.db")
DB_PATH = os.environ.get("TAGSTOCK_DB") or DB_PADRAO

# Situação de cada etiqueta (ciclo de vida):
#   EMITIDA   -> EPC gerado/impresso/gravado, ainda não entrou no estoque
#   ESTOQUE   -> peça no estoque de um local
#   BAIXADA   -> saiu (venda, consumo, avaria, perda...); pode ser estornada
#   CANCELADA -> etiqueta inutilizada (impressão com defeito, perdida antes de usar)
STATUS_ETIQUETA = ("EMITIDA", "ESTOQUE", "BAIXADA", "CANCELADA")

SCHEMA = """
CREATE TABLE IF NOT EXISTS config (
    chave TEXT PRIMARY KEY,
    valor TEXT
);

CREATE TABLE IF NOT EXISTS locais (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo    TEXT NOT NULL UNIQUE,
    nome      TEXT NOT NULL,
    tipo      TEXT NOT NULL DEFAULT 'DEPOSITO',   -- DEPOSITO | LOJA | EXPEDICAO | AVARIA
    ativo     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS produtos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sku         TEXT NOT NULL UNIQUE,     -- referência / código interno
    descricao   TEXT NOT NULL,
    gtin        TEXT UNIQUE,              -- EAN-13 / GTIN-14 (vira o EPC SGTIN-96)
    grupo       TEXT,
    subgrupo    TEXT,
    cor         TEXT,
    tamanho     TEXT,
    unidade     TEXT NOT NULL DEFAULT 'UN',
    preco       REAL NOT NULL DEFAULT 0,
    estoque_min INTEGER NOT NULL DEFAULT 0,
    ativo       INTEGER NOT NULL DEFAULT 1,
    criado_em   TEXT
);

-- Cada etiqueta RFID = 1 peça
CREATE TABLE IF NOT EXISTS etiquetas (
    epc           TEXT PRIMARY KEY,
    produto_id    INTEGER NOT NULL REFERENCES produtos(id),
    local_id      INTEGER REFERENCES locais(id),
    status        TEXT NOT NULL DEFAULT 'EMITIDA',
    serial        INTEGER,
    ordem_id      INTEGER REFERENCES ordens(id),
    origem        TEXT NOT NULL DEFAULT 'EMISSAO',   -- EMISSAO | VINCULACAO | INVENTARIO
    impressa_em   TEXT,
    gravada_em    TEXT,
    criada_em     TEXT NOT NULL,
    atualizada_em TEXT NOT NULL,
    ultima_leitura TEXT
);
CREATE INDEX IF NOT EXISTS ix_etiquetas_produto ON etiquetas(produto_id);
CREATE INDEX IF NOT EXISTS ix_etiquetas_local ON etiquetas(local_id, status);

-- Próximo número de série por GTIN (ou por produto no GID-96): nunca repete
CREATE TABLE IF NOT EXISTS seriais (
    chave  TEXT PRIMARY KEY,
    ultimo INTEGER NOT NULL
);

-- OF (ordem de fabricação / produção): a grade de produtos (cor x tamanho) e quantidades.
-- Gera um EPC serializado por peça para imprimir (iPRINT) ou gravar no coletor.
-- Finalizar a OF = ler as peças prontas: as lidas entram no estoque.
CREATE TABLE IF NOT EXISTS ordens (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    numero        TEXT NOT NULL UNIQUE,
    local_id      INTEGER REFERENCES locais(id),   -- onde as peças entram ao finalizar
    documento     TEXT,
    observacao    TEXT,
    status        TEXT NOT NULL DEFAULT 'ABERTA',  -- ABERTA | FINALIZADA | CANCELADA
    criada_em     TEXT NOT NULL,
    impressa_em   TEXT,
    finalizada_em TEXT
);

CREATE TABLE IF NOT EXISTS ordem_itens (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ordem_id   INTEGER NOT NULL REFERENCES ordens(id),
    produto_id INTEGER NOT NULL REFERENCES produtos(id),
    quantidade INTEGER NOT NULL,
    UNIQUE (ordem_id, produto_id)
);

-- Peças lidas na finalização da OF (conferência)
CREATE TABLE IF NOT EXISTS ordem_leituras (
    ordem_id  INTEGER NOT NULL REFERENCES ordens(id),
    epc       TEXT NOT NULL,
    data_hora TEXT NOT NULL,
    PRIMARY KEY (ordem_id, epc)
);

CREATE TABLE IF NOT EXISTS usuarios (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    login  TEXT NOT NULL UNIQUE,
    nome   TEXT NOT NULL,
    senha  TEXT NOT NULL,                     -- hash (sha256 com sal)
    perfil TEXT NOT NULL DEFAULT 'OPERADOR',  -- ADMIN | OPERADOR
    ativo  INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS sessoes (
    token      TEXT PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    criada_em  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS impressoras (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    nome     TEXT NOT NULL,
    tipo     TEXT NOT NULL DEFAULT 'REDE',     -- REDE (IP:9100) | WINDOWS (fila do Windows)
    endereco TEXT NOT NULL,                    -- IP ou nome da impressora no Windows
    porta    INTEGER NOT NULL DEFAULT 9100,
    modelo   TEXT NOT NULL DEFAULT 'PADRAO',   -- modelo de etiqueta (config modelo_zpl)
    ativo    INTEGER NOT NULL DEFAULT 1
);

-- Histórico (kardex por etiqueta)
CREATE TABLE IF NOT EXISTS movimentos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    data_hora   TEXT NOT NULL,
    tipo        TEXT NOT NULL,   -- EMISSAO | VINCULACAO | ENTRADA | BAIXA | ESTORNO | TRANSFERENCIA
                                 -- | AJUSTE_ENTRADA | AJUSTE_SAIDA | CANCELAMENTO | REGRAVACAO | EXPEDICAO
    epc         TEXT NOT NULL,
    produto_id  INTEGER NOT NULL REFERENCES produtos(id),
    local_origem  INTEGER REFERENCES locais(id),
    local_destino INTEGER REFERENCES locais(id),
    quantidade  INTEGER NOT NULL DEFAULT 0,   -- +1 entrou no estoque, -1 saiu, 0 não mexe no saldo
    motivo      TEXT,
    documento   TEXT,
    origem      TEXT NOT NULL DEFAULT 'PC',   -- PC | COLETOR | API
    dispositivo TEXT,
    usuario     TEXT
);
CREATE INDEX IF NOT EXISTS ix_mov_epc ON movimentos(epc);
CREATE INDEX IF NOT EXISTS ix_mov_data ON movimentos(data_hora);

CREATE TABLE IF NOT EXISTS inventarios (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    nome       TEXT NOT NULL,
    local_id   INTEGER REFERENCES locais(id),   -- NULL = todos os locais
    grupo      TEXT,                            -- inventário parcial por grupo
    status     TEXT NOT NULL DEFAULT 'ABERTO',  -- ABERTO | FINALIZADO | CANCELADO
    ajustado   INTEGER NOT NULL DEFAULT 0,
    aberto_em  TEXT NOT NULL,
    fechado_em TEXT,
    esperado   INTEGER, lidas INTEGER, ok INTEGER, faltas INTEGER, sobras INTEGER
);

CREATE TABLE IF NOT EXISTS inventario_leituras (
    inventario_id INTEGER NOT NULL REFERENCES inventarios(id),
    epc           TEXT NOT NULL,
    data_hora     TEXT NOT NULL,
    dispositivo   TEXT,
    PRIMARY KEY (inventario_id, epc)
);

-- Fotografia do resultado ao finalizar (o estoque muda depois)
CREATE TABLE IF NOT EXISTS inventario_resultado (
    inventario_id INTEGER NOT NULL REFERENCES inventarios(id),
    epc           TEXT NOT NULL,
    produto_id    INTEGER REFERENCES produtos(id),
    situacao      TEXT NOT NULL,   -- OK | FALTA | SOBRA | OUTRO_LOCAL | BAIXADA | DESCONHECIDA
    local_id      INTEGER,
    PRIMARY KEY (inventario_id, epc)
);

-- Expedição / conferência de embarque
CREATE TABLE IF NOT EXISTS pedidos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    numero        TEXT NOT NULL UNIQUE,
    tipo          TEXT NOT NULL DEFAULT 'VENDA',   -- VENDA (baixa) | TRANSFERENCIA (vai para outro local)
    cliente       TEXT,
    local_id      INTEGER REFERENCES locais(id),   -- de onde sai
    destino_id    INTEGER REFERENCES locais(id),   -- transferência: para onde vai
    documento     TEXT,
    status        TEXT NOT NULL DEFAULT 'ABERTO',  -- ABERTO | FINALIZADO | CANCELADO
    criado_em     TEXT NOT NULL,
    finalizado_em TEXT
);

CREATE TABLE IF NOT EXISTS pedido_itens (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    pedido_id  INTEGER NOT NULL REFERENCES pedidos(id),
    produto_id INTEGER NOT NULL REFERENCES produtos(id),
    quantidade INTEGER NOT NULL,
    UNIQUE (pedido_id, produto_id)
);

CREATE TABLE IF NOT EXISTS pedido_leituras (
    pedido_id INTEGER NOT NULL REFERENCES pedidos(id),
    epc       TEXT NOT NULL,
    item_id   INTEGER NOT NULL REFERENCES pedido_itens(id),
    data_hora TEXT NOT NULL,
    PRIMARY KEY (pedido_id, epc)
);

-- Coletores que falaram com o servidor (monitor)
CREATE TABLE IF NOT EXISTS dispositivos (
    id           TEXT PRIMARY KEY,
    nome         TEXT,
    ip           TEXT,
    versao       TEXT,
    bateria      INTEGER,
    rfid         TEXT,
    tela         TEXT,
    ultimo_sinal TEXT NOT NULL
);

-- Alertas: situações que alguém precisa olhar (etiqueta baixada achada no estoque...)
CREATE TABLE IF NOT EXISTS alertas (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    data_hora TEXT NOT NULL,
    tipo      TEXT NOT NULL,
    mensagem  TEXT NOT NULL,
    epc       TEXT,
    lido      INTEGER NOT NULL DEFAULT 0
);
"""

CONFIG_PADRAO = {
    "empresa": "Minha Empresa",
    "prefixo_gs1_digitos": "7",     # tamanho do prefixo da empresa na GS1 (partição do SGTIN-96)
    "filtro_epc": "1",              # 1 = item de ponto de venda
    "gid_gerente": "1",             # GID-96 dos produtos sem GTIN
    "local_padrao": "",             # id do local onde as etiquetas ativadas entram
    "modelo_zpl": "",               # vazio = modelo padrão (impressao.MODELO_PADRAO)
    "potencia_gravacao": "30",
}


def agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hoje() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def conectar() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def ip_da_rede() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def inicializar() -> None:
    pasta = os.path.dirname(DB_PATH)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    con = conectar()
    try:
        con.execute("PRAGMA journal_mode = WAL")
        con.executescript(SCHEMA)
        for chave, valor in CONFIG_PADRAO.items():
            con.execute("INSERT OR IGNORE INTO config (chave, valor) VALUES (?, ?)", (chave, valor))
        if not con.execute("SELECT 1 FROM locais").fetchone():
            cur = con.execute("INSERT INTO locais (codigo, nome, tipo) VALUES ('DEP-01', 'Depósito', 'DEPOSITO')")
            con.execute("INSERT INTO locais (codigo, nome, tipo) VALUES ('LOJA-01', 'Loja', 'LOJA')")
            con.execute("UPDATE config SET valor=? WHERE chave='local_padrao'", (str(cur.lastrowid),))
        if not con.execute("SELECT 1 FROM usuarios").fetchone():
            con.execute("INSERT INTO usuarios (login, nome, senha, perfil) VALUES ('admin', 'Administrador', ?, 'ADMIN')",
                        (hash_senha("admin"),))
        con.commit()
    finally:
        con.close()


def hash_senha(senha: str, sal: str | None = None) -> str:
    """sal$sha256(sal+senha): a senha não fica gravada no banco."""
    sal = sal or secrets.token_hex(8)
    return sal + "$" + hashlib.sha256((sal + senha).encode()).hexdigest()


def confere_senha(senha: str, guardada: str) -> bool:
    sal = guardada.split("$", 1)[0]
    return secrets.compare_digest(hash_senha(senha, sal), guardada)


def config(con) -> dict:
    return {r["chave"]: r["valor"] for r in con.execute("SELECT chave, valor FROM config")}


def linhas(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]
