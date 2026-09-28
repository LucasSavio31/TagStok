// TagStock — páginas da tela do PC.

// ============================================================ Análise (painel)
PAGINAS.painel = {
  titulo: "Análise",
  async abrir(el) {
    const d = await get("/api/painel");
    const maxLocal = Math.max(1, ...d.por_local.map(l => l.quantidade));
    const maxGrupo = Math.max(1, ...d.por_grupo.map(g => g.quantidade));
    const dias = [];
    for (let i = 13; i >= 0; i--) {
      const dt = new Date(Date.now() - i * 864e5), k = dt.toISOString().slice(0, 10);
      const achado = d.dias.find(x => x.dia === k) || {entradas: 0, baixas: 0};
      dias.push({dia: k, ...achado});
    }
    const maxDia = Math.max(1, ...dias.map(x => Math.max(x.entradas, x.baixas)));
    const kpi = (rot, val, p) => `<div class="kpi ${p ? "clic" : ""}" ${p ? `onclick="ir('${p}')"` : ""}><div class="rot">${rot}</div><div class="val">${val}</div></div>`;
    el.innerHTML = `
      <div class="kpis">
        ${kpi("Peças em estoque", num(d.em_estoque), "estoque")}
        ${kpi("Valor em estoque", moeda(d.valor_estoque), "estoque")}
        ${kpi("Etiquetas emitidas (aguardando)", num(d.emitidas), "etiquetas")}
        ${kpi("Entradas hoje", num(d.entradas_hoje), "movimentos")}
        ${kpi("Baixas hoje", num(d.baixadas_hoje), "movimentos")}
        ${kpi("OFs abertas", num(d.ordens_abertas), "ordens")}
        ${kpi("Pedidos em conferência", num(d.pedidos_abertos), "pedidos")}
        ${kpi("Alertas", num(d.alertas), "alertas")}
      </div>
      <div class="grade2">
        <div class="card"><h2>Estoque por local</h2><div class="barras">${d.por_local.map(l =>
          `<div class="linha"><span>${esc(l.codigo)} <span class="fraco">${esc(l.nome)}</span></span><div class="b" style="width:${100 * l.quantidade / maxLocal}%"></div><b class="n">${num(l.quantidade)}</b></div>`).join("") || '<div class="vazio">Sem locais</div>'}</div></div>
        <div class="card"><h2>Estoque por grupo</h2><div class="barras">${d.por_grupo.map(g =>
          `<div class="linha"><span>${esc(g.grupo)}</span><div class="b" style="width:${100 * g.quantidade / maxGrupo}%;background:var(--info)"></div><b class="n">${num(g.quantidade)}</b></div>`).join("") || '<div class="vazio">Sem peças no estoque</div>'}</div></div>
      </div>
      <div class="card"><h2>Entradas × baixas (14 dias)<span class="dir legenda"><span><i style="background:var(--primaria)"></i>Entradas</span><span><i style="background:#e57373"></i>Baixas</span></span></h2>
        <div class="colunas">${dias.map(x => `<div class="dia" title="${dataBR(x.dia)}: ${x.entradas} entradas, ${x.baixas} baixas">
          <div class="par"><div class="e" style="height:${130 * x.entradas / maxDia}px"></div><div class="s" style="height:${130 * x.baixas / maxDia}px"></div></div>
          <span>${x.dia.slice(8, 10)}/${x.dia.slice(5, 7)}</span></div>`).join("")}</div></div>
      <div class="grade2">
        <div class="card"><h2>Abaixo do estoque mínimo</h2><div id="pnMin"></div></div>
        <div class="card"><h2>Últimos inventários</h2><div id="pnInv"></div></div>
      </div>`;
    listaSel($("#pnMin"), [
      {t: "SKU", f: p => `<b>${esc(p.sku)}</b>`}, {t: "Descrição", f: p => `${esc(p.descricao)} <span class="fraco">${esc(variante(p))}</span>`},
      {t: "Mínimo", k: "estoque_min", n: 1}, {t: "Saldo", n: 1, f: p => `<b style="color:var(--perigo)">${p.saldo}</b>`, csv: p => p.saldo}],
      d.abaixo_minimo, {vazio: "Nenhum produto abaixo do mínimo", alt: "300px", nome: "abaixo-do-minimo",
        acoes: [["🖨 Gerar OF de reposição", "p", async l => {
          const ordem = await post("/api/ordens", {itens: l.map(p => ({produto_id: p.id, quantidade: Math.max(1, p.estoque_min - p.saldo)})), observacao: "Reposição do estoque mínimo"});
          avisar(`${ordem.numero} gerada com ${ordem.quantidade} etiqueta(s)`); ir("ordem/" + ordem.id); }]]});
    listaSel($("#pnInv"), [
      {t: "Inventário", f: i => esc(i.nome)}, {t: "Data", f: i => dataBR(i.fechado_em)},
      {t: "Acuracidade", n: 1, f: i => i.esperado ? (100 * i.ok / i.esperado).toFixed(1) + "%" : "-"},
      {t: "Faltas", k: "faltas", n: 1}, {t: "Sobras", k: "sobras", n: 1}], d.inventarios,
      {vazio: "Nenhum inventário finalizado", alt: "300px", nome: "inventarios", aoClicar: i => ir("inventario/" + i.id)});
  },
};

// ============================================================ Estoque
PAGINAS.estoque = {
  titulo: "Estoque",
  async abrir(el) {
    const grupos = await get("/api/grupos");
    el.innerHTML = `<div class="card"><div class="filtros">
        <label>Local<select id="fLocal">${opcoesLocais("", "Todos os locais")}</select></label>
        <label>Grupo<select id="fGrupo"><option value="">Todos</option>${grupos.map(g => `<option>${esc(g)}</option>`).join("")}</select></label>
        <label>Buscar<input id="fBusca" placeholder="SKU, descrição, GTIN, cor"></label>
        <span style="flex:1"></span>
        <button onclick="baixar('/api/estoque.csv?local_id='+$('#fLocal').value+'&grupo='+encodeURIComponent($('#fGrupo').value))">⬇ CSV por produto</button>
        <button onclick="baixar('/api/estoque/etiquetas.csv?local_id='+$('#fLocal').value)">⬇ CSV das etiquetas</button>
      </div><div id="tot" class="fraco" style="margin-bottom:8px"></div><div id="lista"></div></div>`;
    const carregar = async () => {
      const q = new URLSearchParams({local_id: $("#fLocal").value, grupo: $("#fGrupo").value, q: $("#fBusca").value});
      const linhas = await get("/api/estoque?" + q);
      $("#tot").textContent = `${num(linhas.reduce((s, l) => s + l.quantidade, 0))} peça(s) · ${linhas.length} linha(s) produto × local`;
      // Ações em lote: valem para TODAS as peças dos itens (produto × local) selecionados
      const pecas = async l => (await Promise.all(l.map(x => get(`/api/etiquetas?status=ESTOQUE&produto_id=${x.produto_id}&local_id=${x.local_id}&limite=5000`)))).flat();
      const emPecas = ([rotulo, classe, fn]) => [rotulo + " (todas as peças)", classe, async l => fn(await pecas(l))];
      listaSel($("#lista"), [
        {t: "Local", k: "local"}, {t: "SKU", f: l => `<b>${esc(l.sku)}</b>`, csv: l => l.sku}, {t: "Descrição", k: "descricao"},
        {t: "Cor", k: "cor"}, {t: "Tam.", k: "tamanho"}, {t: "Grupo", k: "grupo"}, {t: "GTIN", k: "gtin", cl: "mono"},
        {t: "Qtd", n: 1, f: l => `<b>${num(l.quantidade)}</b>`, csv: l => l.quantidade}], linhas,
        {chave: l => l.produto_id + "-" + l.local_id, vazio: "Nenhuma peça no estoque", nome: "estoque",
         aoClicar: l => mostrarEtiquetasProduto(l.produto_id, l.local_id, `${l.sku} em ${l.local}`),
         acoes: acoesEtiquetas(carregar, ["transferencia", "baixa"]).map(emPecas)});
    };
    ["fLocal", "fGrupo"].forEach(id => $("#" + id).onchange = () => tentar(carregar));
    let t; $("#fBusca").oninput = () => { clearTimeout(t); t = setTimeout(() => tentar(carregar), 300); };
    await carregar();
  },
};

async function mostrarEtiquetasProduto(produtoId, localId, titulo) {
  const lista = await get(`/api/etiquetas?status=ESTOQUE&produto_id=${produtoId}&local_id=${localId || ""}&limite=5000`);
  abrirDlg("Etiquetas: " + titulo, `<div class="fraco" style="margin-bottom:8px">${lista.length} etiqueta(s). Clique para ver o histórico.</div><div id="dlgEtqs"></div>`,
    [], {largo: true});
  listaSel($("#dlgEtqs"), [{t: "EPC", k: "epc", cl: "mono"}, {t: "OF", k: "ordem"}, {t: "Série", k: "serial", n: 1}, {t: "Última leitura", f: t => dataBR(t.ultima_leitura)}],
    lista, {chave: t => t.epc, alt: "55vh", nome: "etiquetas", aoClicar: t => mostrarEtiqueta(t.epc),
            acoes: acoesEtiquetas(async () => { fecharDlg(); abrir(); }, ["transferencia", "baixa", "cancelar"])});
}

// ============================================================ Etiquetas / rastreio
PAGINAS.etiquetas = {
  titulo: "Etiquetas / rastreio",
  async abrir(el) {
    el.innerHTML = `<div class="card"><h2>Rastrear uma etiqueta</h2>
        <div class="fraco" style="margin-bottom:6px">Leia com o coletor (▶ Ler no topo), com um leitor USB, ou digite o EPC. Mostra o produto, onde está e todo o histórico.</div>
        ${campoCaptura("capRastreio", "EPC da etiqueta")}</div>
      <div class="card"><div class="filtros">
        <label>Situação<select id="fSt"><option value="">Todas</option><option>EMITIDA</option><option selected>ESTOQUE</option><option>BAIXADA</option><option>CANCELADA</option></select></label>
        <label>Local<select id="fLocal">${opcoesLocais("", "Todos")}</select></label>
        <label>Buscar<input id="fBusca" placeholder="EPC, SKU ou descrição"></label></div><div id="lista"></div></div>`;
    definirSaida(epcs => mostrarEtiqueta(epcs[epcs.length - 1]));
    const carregar = async () => {
      const q = new URLSearchParams({status: $("#fSt").value, local_id: $("#fLocal").value, q: $("#fBusca").value, limite: 500});
      const lista = await get("/api/etiquetas?" + q);
      listaSel($("#lista"), [{t: "EPC", k: "epc", cl: "mono"}, {t: "Produto", f: descProduto}, {t: "Situação", f: t => selo(t.status), csv: t => t.status},
        {t: "Local", k: "local"}, {t: "OF", k: "ordem"}, {t: "Atualizada", f: t => dataBR(t.atualizada_em)}], lista,
        {chave: t => t.epc, vazio: "Nenhuma etiqueta", nome: "etiquetas", aoClicar: t => mostrarEtiqueta(t.epc), acoes: acoesEtiquetas(carregar)});
    };
    ["fSt", "fLocal"].forEach(id => $("#" + id).onchange = () => tentar(carregar));
    let t; $("#fBusca").oninput = () => { clearTimeout(t); t = setTimeout(() => tentar(carregar), 300); };
    await carregar();
  },
};

async function mostrarEtiqueta(epc) {
  const h = await get("/api/epc/" + encodeURIComponent(epc));
  const t = h.etiqueta, d = h.decodificado;
  const dec = d.esquema === "SGTIN-96" ? `SGTIN-96 · GTIN <b>${esc(d.gtin)}</b> · série ${esc(d.serial)} · filtro ${esc(d.filtro)}`
            : d.esquema === "GID-96" ? `GID-96 · gerente ${esc(d.gerente)} · classe ${esc(d.classe)} · série ${esc(d.serial)}` : "Formato livre (não GS1)";
  const html = `<div class="mono" style="font-size:15px;margin-bottom:4px">${esc(h.epc)}</div>
    <div class="fraco" style="margin-bottom:12px">${dec}${d.uri ? "<br>" + esc(d.uri) : ""}</div>
    ${t ? `<div class="kpis" style="grid-template-columns:repeat(4,1fr)">
      <div class="kpi"><div class="rot">Produto</div><div><b>${esc(t.sku)}</b><br>${esc(t.descricao)}<br><span class="fraco">${esc(variante(t))}</span></div></div>
      <div class="kpi"><div class="rot">Situação</div><div class="val" style="font-size:18px">${selo(t.status)}</div></div>
      <div class="kpi"><div class="rot">Local</div><div class="val" style="font-size:18px">${esc(t.local || "-")}</div></div>
      <div class="kpi"><div class="rot">Origem</div><div>${esc(t.origem)}${t.ordem ? "<br>OF " + esc(t.ordem) : ""}<br><span class="fraco">última leitura ${dataBR(t.ultima_leitura) || "-"}</span></div></div></div>`
      : `<div class="dica">Etiqueta não cadastrada.${h.sugerido ? ` O GTIN do EPC é do produto <b>${esc(h.sugerido.sku)} ${esc(h.sugerido.descricao)}</b>.` : ""} Use a Estação RFID → Vincular.</div>`}
    <h4 style="margin:10px 0 6px">Histórico</h4><div id="dlgHist"></div>`;
  const botoes = [];
  if (t?.status === "BAIXADA") botoes.push(["Estornar baixa", "", async () => { await post("/api/etiquetas/estorno", {epcs: [h.epc]}); avisar("Estornada"); mostrarEtiqueta(h.epc); }]);
  if (t && ["EMITIDA", "ESTOQUE"].includes(t.status)) botoes.push(["Cancelar etiqueta", "perigo", async () => {
    const m = prompt("Motivo do cancelamento (etiqueta danificada, perdida...)"); if (m === null) return;
    await post("/api/etiquetas/cancelar", {epcs: [h.epc], motivo: m}); avisar("Etiqueta cancelada"); mostrarEtiqueta(h.epc); }]);
  abrirDlg("Etiqueta", html, botoes, {largo: true});
  listaSel($("#dlgHist"), [{t: "Data/hora", f: m => dataBR(m.data_hora), csv: m => m.data_hora}, {t: "Tipo", k: "tipo"},
    {t: "Qtd", n: 1, f: m => m.quantidade > 0 ? "+1" : m.quantidade < 0 ? "-1" : ""},
    {t: "De → para", f: m => esc([m.origem_local, m.destino_local].filter(Boolean).join(" → "))}, {t: "Motivo", k: "motivo"},
    {t: "Documento", k: "documento"}, {t: "Quem", f: m => esc([m.usuario, m.origem].filter(Boolean).join(" · "))}], h.movimentos,
    {vazio: "Sem movimentos", alt: "40vh", nome: "historico-" + h.epc});
}

// ============================================================ Seletor de produtos (grade) para OF e pedido
async function seletorItens(el, opts = {}) {
  const produtos = await get("/api/produtos?ativos=true");
  const grupos = [...new Set(produtos.map(p => p.grupo).filter(Boolean))].sort();
  const qtd = new Map();
  el.innerHTML = `<div class="filtros"><label>Grupo<select class="sGrupo"><option value="">Todos</option>${grupos.map(g => `<option>${esc(g)}</option>`).join("")}</select></label>
      <label style="flex:1">Buscar produto<input class="sBusca" placeholder="SKU, descrição, cor, tamanho, GTIN (ou bipe o código de barras)"></label>
      <label>Qtd. para todos os filtrados<span class="botoes"><input class="sTodos" type="number" min="0" style="width:90px"><button class="sAplicar">Aplicar</button></span></label></div>
    <div class="sLista"></div><div class="fraco sResumo" style="margin-top:6px"></div>`;
  const filtrados = () => {
    const q = $(".sBusca", el).value.toLowerCase(), g = $(".sGrupo", el).value;
    return produtos.filter(p => (!g || p.grupo === g) &&
      (!q || [p.sku, p.descricao, p.cor, p.tamanho, p.gtin].some(v => (v || "").toLowerCase().includes(q))));
  };
  const resumo = () => {
    const itens = [...qtd.values()].filter(v => v > 0);
    $(".sResumo", el).textContent = `${itens.length} produto(s) · ${num(itens.reduce((a, b) => a + b, 0))} peça(s) no total`;
  };
  const desenhar = () => {
    const lista = filtrados().slice(0, 400);
    const definir = async (l, v) => { l.forEach(p => qtd.set(p.id, v)); desenhar(); resumo(); };
    listaSel($(".sLista", el), [{t: "SKU", f: p => `<b>${esc(p.sku)}</b>`, csv: p => p.sku}, {t: "Descrição", k: "descricao"}, {t: "Cor", k: "cor"},
      {t: "Tam.", k: "tamanho"}, {t: "GTIN", k: "gtin", cl: "mono"}, ...(opts.saldo ? [{t: "Saldo", k: "saldo", n: 1}] : []),
      {t: "Quantidade", n: 1, f: p => `<input type="number" min="0" data-id="${p.id}" value="${qtd.get(p.id) || ""}" style="width:90px;text-align:right">`, csv: p => qtd.get(p.id) || 0}],
      lista, {alt: "42vh", vazio: "Nenhum produto (cadastre em Produtos)", nome: "grade",
        acoes: [["Quantidade das selecionadas…", "", async l => {
                  const v = await escolher("Quantidade", `${l.length} produto(s) selecionado(s).`, "Quantidade de cada um", null, "1");
                  if (v !== null) await definir(l, Math.max(0, parseInt(v) || 0)); }],
                ["Zerar selecionadas", "", l => definir(l, 0)]]});
    $$("input[data-id]", el).forEach(i => i.oninput = () => { qtd.set(+i.dataset.id, Math.max(0, parseInt(i.value) || 0)); resumo(); });
  };
  $(".sBusca", el).oninput = desenhar; $(".sGrupo", el).onchange = desenhar;
  $(".sBusca", el).onkeydown = e => { if (e.key === "Enter") { const f = filtrados(); if (f.length === 1) { qtd.set(f[0].id, (qtd.get(f[0].id) || 0) + 1); $(".sBusca", el).value = ""; desenhar(); resumo(); } } };
  $(".sAplicar", el).onclick = () => { const v = parseInt($(".sTodos", el).value) || 0; filtrados().forEach(p => qtd.set(p.id, v)); desenhar(); resumo(); };
  (opts.iniciais || []).forEach(i => qtd.set(i.produto_id, i.quantidade));
  desenhar(); resumo();
  return () => [...qtd.entries()].filter(([, v]) => v > 0).map(([produto_id, quantidade]) => ({produto_id, quantidade}));
}

// ============================================================ OF / Emissão (iPRINT)
PAGINAS.ordens = {
  titulo: "OF · Emissão de etiquetas",
  async abrir(el) {
    el.innerHTML = `<div class="dica">Cada <b>OF</b> (ordem de fabricação/produção) tem a grade de produtos e quantidades. O sistema gera um
      <b>EPC SGTIN-96 serializado</b> (padrão GS1) para cada peça. Imprima na impressora RFID (ou grave no coletor, tela <i>Gravar OF</i>),
      aplique nas peças e <b>finalize a OF lendo as peças</b>: as lidas entram no estoque.</div>
      <div class="card"><h2>Ordens<span class="dir"><select id="fSt"><option value="ABERTA">Abertas</option><option value="">Todas</option>
        <option value="FINALIZADA">Finalizadas</option><option value="CANCELADA">Canceladas</option></select>
        <button class="p" id="btNova">+ Nova OF</button></span></h2><div id="lista"></div></div>`;
    const carregar = async () => {
      const lista = await get("/api/ordens?status=" + $("#fSt").value);
      listaSel($("#lista"), [{t: "OF", f: o => `<b>${esc(o.numero)}</b>`, csv: o => o.numero}, {t: "Documento", k: "documento"},
        {t: "Produtos", f: o => `${o.itens} · <span class="fraco">${esc((o.skus || "").slice(0, 60))}</span>`},
        {t: "Peças", k: "quantidade", n: 1}, {t: "Impressas", n: 1, f: o => o.impressas + o.gravadas ? num(Math.max(o.impressas, o.gravadas)) : "-"},
        {t: "Conferência", f: o => `${progresso(o.lidas, o.quantidade)}<span class="fraco">${o.lidas}/${o.quantidade}</span>`, csv: o => `${o.lidas}/${o.quantidade}`},
        {t: "Local", k: "local"}, {t: "Situação", f: o => selo(o.status), csv: o => o.status}, {t: "Criada", f: o => dataBR(o.criada_em)}], lista,
        {vazio: "Nenhuma OF", nome: "ordens", aoClicar: o => ir("ordem/" + o.id),
         acoes: [["🚫 Cancelar selecionadas", "perigo", async l => {
           const abertas = l.filter(o => o.status === "ABERTA");
           if (!abertas.length) return avisar("Só OF aberta pode ser cancelada", "info");
           if (!await confirmar("Cancelar OFs", `Cancelar ${abertas.length} OF(s) aberta(s)? As etiquetas ainda não usadas são canceladas.` +
             (abertas.length < l.length ? `<br>${l.length - abertas.length} selecionada(s) não estão abertas e ficam como estão.` : ""))) return;
           await emLote(abertas, "OFs canceladas", o => post(`/api/ordens/${o.id}/cancelar`), carregar); }]]});
    };
    $("#fSt").onchange = () => tentar(carregar);
    $("#btNova").onclick = () => novaOrdem();
    await carregar();
  },
};

async function novaOrdem() {
  abrirDlg("Nova OF", `<div class="form"><label>Número (vazio = automático)<input id="oNum" placeholder="OF-000001"></label>
      <label>Documento (NF, pedido do ERP)<input id="oDoc"></label>
      <label>Local de entrada<select id="oLocal">${opcoesLocais(CFG.local_padrao)}</select></label>
      <label class="largo">Observação<input id="oObs"></label></div><h4 style="margin:14px 0 6px">Grade (produtos e quantidades)</h4><div id="oItens"></div>`,
    [["Cancelar", "", fecharDlg], ["Gerar etiquetas", "p", async () => {
      const itens = pegar();
      const o = await post("/api/ordens", {numero: $("#oNum").value || null, documento: $("#oDoc").value || null,
                                           local_id: +$("#oLocal").value || null, observacao: $("#oObs").value || null, itens});
      avisar(`${o.numero}: ${o.quantidade} EPC(s) gerados`); fecharDlg(); ir("ordem/" + o.id);
    }]], {largo: true});
  const pegar = await seletorItens($("#oItens"));
}

PAGINAS.ordem = {
  titulo: "OF",
  async abrir(el, id) {
    const impressoras = (await get("/api/impressoras")).filter(i => i.ativo);
    const selGrade = new Set(), selEtqs = new Set();   // a seleção continua quando a tela redesenha (a cada leitura)
    let o, etqs = [];
    const desenhar = async () => {
      [o, etqs] = await Promise.all([get("/api/ordens/" + id), get(`/api/ordens/${id}/etiquetas`)]);
      $("#titulo").textContent = "OF " + o.numero;
      const aberta = o.status === "ABERTA";
      el.innerHTML = `<div class="botoes" style="margin-bottom:12px"><button onclick="ir('ordens')">← Ordens</button>${selo(o.status)}
          <span class="fraco">Criada ${dataBR(o.criada_em)} · entra em <b>${esc(o.local || "-")}</b>${o.documento ? " · doc. " + esc(o.documento) : ""}${o.impressa_em ? " · impressa " + dataBR(o.impressa_em) : ""}</span></div>
        <div class="kpis"><div class="kpi"><div class="rot">Peças na OF</div><div class="val">${num(o.quantidade)}</div></div>
          <div class="kpi"><div class="rot">Conferidas (lidas)</div><div class="val">${num(o.lidas)}</div>${progresso(o.lidas, o.quantidade)}</div>
          <div class="kpi"><div class="rot">Faltam</div><div class="val">${num(Math.max(0, o.quantidade - o.lidas))}</div></div></div>
        ${aberta ? `<div class="card"><h2>1 · Imprimir etiquetas RFID</h2><div class="botoes">
            <select id="oImp">${impressoras.map(i => `<option value="${i.id}">${esc(i.nome)} (${i.tipo === "REDE" ? esc(i.endereco) : "Windows"})</option>`).join("") || "<option value=''>Cadastre uma impressora</option>"}</select>
            <button class="p" id="btImprimir">🖨 Imprimir as não impressas</button>
            <button id="btZpl">⬇ Arquivo ZPL</button><button id="btCsv">⬇ Lista de EPCs (CSV)</button>
            <span class="fraco">Sem impressora RFID? Grave no coletor: tela <b>Gravar OF</b>.</span></div></div>
          <div class="card"><h2>2 · Finalizar: ler as peças prontas<span class="dir"><button id="btLimpar">Zerar leituras</button></span></h2>
            <div class="fraco">Leia as peças com o coletor (▶ Ler no topo, ou no coletor: tela <b>Finalizar OF</b>) ou com um leitor USB.</div>
            ${campoCaptura("capOF")}<div id="ultimas" class="fraco"></div></div>` : ""}
        <div class="card"><h2>Grade da OF${aberta && o.itens.length > 1 ? '<span class="dir"><button id="btKit">Consolidação de kit</button></span>' : ""}</h2><div id="ofGrade"></div></div>
        <div class="card"><h2>Etiquetas</h2><div id="etqs"></div></div>
        ${aberta ? `<div class="botoes"><button class="suc" id="btFinalizar">✔ Finalizar OF (entrada das lidas)</button>
          <button class="perigo" id="btCancelar">Cancelar OF</button></div>` : ""}`;
      listaSel($("#ofGrade"), [{t: "SKU", f: i => `<b>${esc(i.sku)}</b>`, csv: i => i.sku}, {t: "Descrição", k: "descricao"}, {t: "Cor", k: "cor"}, {t: "Tam.", k: "tamanho"},
          {t: "GTIN", k: "gtin", cl: "mono"}, {t: "Qtd", k: "quantidade", n: 1}, {t: "Impressas", k: "impressas", n: 1}, {t: "Gravadas", k: "gravadas", n: 1},
          {t: "Lidas", n: 1, f: i => `<b style="color:${i.lidas === i.quantidade ? "var(--sucesso)" : i.lidas > 0 ? "var(--alerta)" : "inherit"}">${i.lidas}</b>`, csv: i => i.lidas},
          {t: "", f: i => progresso(i.lidas, i.quantidade)}], o.itens,
        {sel: selGrade, nome: o.numero + "-grade",
         acoes: aberta && impressoras.length ? [["🖨 Imprimir estes itens", "p", async l => {
           const ids = new Set(l.map(i => i.produto_id));
           const epcs = etqs.filter(t => ids.has(t.produto_id) && t.status === "EMITIDA" && !t.impressa_em).map(t => t.epc);
           if (!epcs.length) return avisar("As etiquetas destes itens já foram impressas (use Reimprimir nas etiquetas)", "info");
           const r = await post(`/api/ordens/${id}/imprimir`, {impressora_id: +$("#oImp").value, epcs}); avisar(`${r.impressas} etiqueta(s) enviadas`); desenhar(); }]] : []});
      listaSel($("#etqs"), [{t: "EPC", k: "epc", cl: "mono"}, {t: "Produto", f: t => `${esc(t.sku)} <span class="fraco">${esc(variante(t))}</span>`, csv: t => t.sku},
        {t: "Série", k: "serial", n: 1}, {t: "Impressa", f: t => t.impressa_em ? "✔" : "", csv: t => t.impressa_em || ""},
        {t: "Gravada", f: t => t.gravada_em ? "✔" : "", csv: t => t.gravada_em || ""}, {t: "Lida", f: t => t.lida ? "✔" : "", csv: t => t.lida ? "sim" : ""},
        {t: "Situação", f: t => selo(t.status), csv: t => t.status}], etqs,
        {sel: selEtqs, chave: t => t.epc, alt: "45vh", nome: o.numero + "-etiquetas", aoClicar: t => mostrarEtiqueta(t.epc),
         acoes: aberta ? [
           ...(impressoras.length ? [["🖨 Reimprimir", "", async l => {
             const epcs = l.filter(t => t.status === "EMITIDA").map(t => t.epc);
             if (!epcs.length) return avisar("Só etiqueta emitida (ainda não usada) é reimpressa", "info");
             const r = await post(`/api/ordens/${id}/imprimir`, {impressora_id: +$("#oImp").value, epcs}); avisar(`${r.impressas} reimpressa(s)`); desenhar(); }]] : []),
           ["✔ Marcar como lidas", "", async l => { const r = await post(`/api/ordens/${id}/leituras`, {epcs: l.map(t => t.epc)});
             const ruins = r.leituras.filter(x => !x.ok); avisar(`${r.leituras.length - ruins.length} marcada(s) como lidas` + (ruins.length ? `\n${ruins.length} recusada(s)` : ""), ruins.length ? "erro" : "ok"); desenhar(); }],
           ["✖ Desmarcar leitura", "", async l => emLote(l.filter(t => t.lida), "Leituras removidas", t => del(`/api/ordens/${id}/leituras/${t.epc}`), desenhar)],
           acoesEtiquetas(desenhar, ["cancelar"])[0]] : acoesEtiquetas(desenhar, ["transferencia", "baixa"])});
      if (!aberta) return;
      $("#btImprimir").onclick = () => tentar(async () => {
        const r = await post(`/api/ordens/${id}/imprimir`, {impressora_id: +$("#oImp").value}); avisar(`${r.impressas} etiqueta(s) enviadas para a impressora`); desenhar(); });
      $("#btZpl").onclick = () => baixar(`/api/ordens/${id}/etiquetas.zpl`);
      $("#btCsv").onclick = () => baixar(`/api/ordens/${id}/etiquetas.csv`);
      $("#btLimpar").onclick = () => tentar(async () => { if (!confirm("Zerar as leituras desta OF?")) return; await del(`/api/ordens/${id}/leituras`); Leitor.esquecer(); desenhar(); });
      $("#btFinalizar").onclick = () => finalizarOrdem(o);
      $("#btCancelar").onclick = () => tentar(async () => {
        if (!confirm(`Cancelar a ${o.numero}? As etiquetas ainda não usadas serão canceladas.`)) return;
        const r = await post(`/api/ordens/${id}/cancelar`); avisar(`OF cancelada (${r.canceladas} etiquetas)`); desenhar(); });
      if ($("#btKit")) $("#btKit").onclick = () => consolidarKit(o, desenhar);
    };
    let fila = [], enviando = false;
    const enviar = async () => {
      if (enviando || !fila.length) return;
      enviando = true;
      const lote = fila.splice(0);
      try {
        const r = await post(`/api/ordens/${id}/leituras`, {epcs: lote});
        const ruins = r.leituras.filter(x => !x.ok);
        if (ruins.length) avisar(ruins.slice(0, 4).map(x => x.epc.slice(-8) + ": " + x.motivo).join("\n") + (ruins.length > 4 ? `\n+${ruins.length - 4}` : ""), "erro");
        await desenhar();
      } catch (e) { avisar(e.message, "erro"); } finally { enviando = false; if (fila.length) enviar(); }
    };
    definirSaida(epcs => { fila.push(...epcs); enviar(); });
    await desenhar();
  },
};

function consolidarKit(o, depois) {
  const opc = o.itens.map(i => `<option value="${i.produto_id}">${esc(i.sku)} · ${esc(variante(i))} (${i.quantidade})</option>`).join("");
  abrirDlg("Consolidação de kit", `<div class="dica">Troca o produto de destino de um item da OF por outro produto da mesma OF.
      Vale para <b>todas as peças</b> daquela cor/tamanho (o EPC gravado continua o mesmo).</div>
    <div class="form"><label>Peças do produto<select id="kO">${opc}</select></label><label>Passam a ser do produto<select id="kD">${opc}</select></label></div>`,
    [["Cancelar", "", fecharDlg], ["Consolidar", "p", async () => {
      const r = await post(`/api/ordens/${o.id}/consolidar`, {produto_origem: +$("#kO").value, produto_destino: +$("#kD").value});
      avisar(`${r.etiquetas} etiqueta(s) consolidadas`); fecharDlg(); depois(); }]]);
  $("#kD").selectedIndex = Math.min(1, o.itens.length - 1);
}

function finalizarOrdem(o) {
  const div = o.itens.filter(i => i.lidas !== i.quantidade);
  abrirDlg("Finalizar " + o.numero, `<p><b>${o.lidas}</b> de <b>${o.quantidade}</b> peças foram lidas. As lidas entram no estoque de <b>${esc(o.local)}</b>.</p>
      ${div.length ? `<div class="dica" style="background:var(--f-alerta)">Divergências:<br>${div.map(i => `${esc(i.sku)} ${esc(variante(i))}: ${i.lidas} de ${i.quantidade}`).join("<br>")}</div>` : ""}
      <label class="check"><input type="checkbox" id="fCanc"> Cancelar as etiquetas não lidas (senão ficam emitidas e podem entrar depois pela Entrada)</label>`,
    [["Voltar", "", fecharDlg], ["Finalizar", "suc", async () => {
      const r = await post(`/api/ordens/${o.id}/finalizar`, {cancelar_nao_lidas: $("#fCanc").checked});
      fecharDlg(); avisar(`${r.entradas} peça(s) entraram no estoque` + (r.canceladas ? `, ${r.canceladas} canceladas` : "")); abrir(); }]]);
}

// ============================================================ Estação RFID (bancada)
PAGINAS.estacao = {
  titulo: "Estação RFID",
  async abrir(el) {
    const produtos = await get("/api/produtos?ativos=true");
    const ordens = await get("/api/ordens?status=ABERTA");
    const lidas = new Map();   // epc -> situação
    el.innerHTML = `<div class="dica">Deixe o coletor na tela <b>Estação PC</b> (fora do cabo USB). Use <b>▶ Ler</b> no topo, um leitor USB no campo abaixo,
        ou cole uma lista de EPCs. As ações valem para as etiquetas <b>marcadas</b>.</div>
      <div class="grade2" style="grid-template-columns:1.4fr 1fr">
        <div class="card"><h2>Etiquetas lidas <span id="nLidas" class="selo">0</span><span class="dir"><button id="btLimparLista">Limpar lista</button></span></h2>
          ${campoCaptura("capEst")}<div id="lidas"></div></div>
        <div class="card"><h2>Ações</h2><div class="lista-acoes" style="grid-template-columns:1fr">
          <div class="acao"><h4>🔗 Vincular a um produto</h4><div class="fraco">Etiqueta com EPC qualquer (virgem, de fornecedor, reaproveitada) vira uma peça do produto.</div>
            <label>Produto<input id="vBusca" list="listaProd" placeholder="SKU ou descrição"></label>
            <datalist id="listaProd">${produtos.map(p => `<option value="${esc(p.sku)}">${esc(p.descricao)} ${esc(variante(p))}</option>`).join("")}</datalist>
            <label>Local<select id="vLocal">${opcoesLocais(CFG.local_padrao)}</select></label>
            <label class="check"><input type="checkbox" id="vAtivar" checked> Já entra no estoque</label><button class="p" data-a="vincular">Vincular</button></div>
          <div class="acao"><h4>📥 Entrada (ativar emitidas)</h4><label>Local<select id="eLocal">${opcoesLocais(CFG.local_padrao)}</select></label>
            <label>Documento<input id="eDoc" placeholder="NF / romaneio"></label><button class="p" data-a="entrada">Dar entrada</button></div>
          <div class="acao"><h4>📤 Baixa</h4><label>Motivo<select id="bMotivo">${MOTIVOS.map(m => `<option>${m}</option>`).join("")}</select></label>
            <label>Documento<input id="bDoc" placeholder="cupom, NF"></label><button class="perigo" data-a="baixa">Baixar</button>
            <button data-a="estorno">Estornar baixa</button></div>
          <div class="acao"><h4>🔁 Transferir</h4><label>Para o local<select id="tLocal">${opcoesLocais()}</select></label><button class="p" data-a="transferencia">Transferir</button></div>
          <div class="acao"><h4>✍ Gravar EPC (coletor)</h4><div class="fraco">Deixe só a etiqueta a gravar perto do coletor.</div>
            <label>Próximo EPC da OF<select id="gOF"><option value="">— escolha a OF —</option>${ordens.map(o => `<option value="${o.id}">${esc(o.numero)}</option>`).join("")}</select></label>
            <label>ou EPC a gravar<input id="gEpc" class="mono" placeholder="24 caracteres hexadecimais"></label>
            <button class="p" id="btGravar">Gravar</button><div id="gRes" class="fraco"></div></div>
          <div class="acao"><h4>🚫 Cancelar etiquetas</h4><button class="perigo" data-a="cancelar">Cancelar marcadas</button></div>
        </div></div></div>`;
    const selEst = new Set();   // etiqueta lida entra já marcada
    const tirar = epcs => { epcs.forEach(e => { lidas.delete(e); selEst.delete(e); }); post("/api/remoto/remover", {epcs}).catch(() => {}); desenhar(); };
    const desenhar = () => {
      const lista = [...lidas.values()];
      $("#nLidas").textContent = lista.length;
      listaSel($("#lidas"), [{t: "EPC", k: "epc", cl: "mono"}, {t: "Produto", f: descProduto}, {t: "Situação", f: t => selo(t.status), csv: t => t.status || "NAO CADASTRADA"},
        {t: "Local", k: "local"}, {t: "", f: t => `<button class="link" data-x="${t.epc}">✕</button>`}], lista,
        {sel: selEst, chave: t => t.epc, alt: "60vh", vazio: "Nenhuma etiqueta lida", nome: "etiquetas-lidas", aoClicar: t => mostrarEtiqueta(t.epc),
         acoes: [["✕ Tirar da lista", "", async l => tirar(l.map(t => t.epc))]]});
      $$("[data-x]").forEach(b => b.onclick = () => tirar([b.dataset.x]));
    };
    const atualizarSituacao = async epcs => {
      if (!epcs.length) return;
      for (const s of await post("/api/etiquetas/situacao", {epcs})) { if (!lidas.has(s.epc)) selEst.add(s.epc); lidas.set(s.epc, s); }
      desenhar();
    };
    definirSaida(epcs => tentar(() => atualizarSituacao(epcs)));
    const marcadas = () => [...lidas.keys()].filter(e => selEst.has(e));
    $("#btLimparLista").onclick = () => { lidas.clear(); selEst.clear(); Leitor.comando("limpar").catch(() => {}); Leitor.vistas.clear(); desenhar(); };
    const resultado = async (r, nome) => {
      avisar(`${nome}: ${r.quantidade} ok` + (r.erros.length ? `\n${r.erros.length} recusada(s): ` + r.erros.slice(0, 3).map(x => x.motivo).join("; ") : ""), r.erros.length ? "erro" : "ok");
      await atualizarSituacao([...lidas.keys()]);
    };
    $$("[data-a]").forEach(b => b.onclick = () => tentar(async () => {
      const epcs = marcadas(); if (!epcs.length) return avisar("Nenhuma etiqueta marcada", "info");
      const a = b.dataset.a;
      if (a === "vincular") {
        const p = produtos.find(x => x.sku === $("#vBusca").value.trim()); if (!p) return avisar("Escolha o produto da lista", "erro");
        await resultado(await post("/api/etiquetas/vincular", {epcs, produto_id: p.id, local_id: +$("#vLocal").value, ativar: $("#vAtivar").checked}), "Vincular");
      } else if (a === "entrada") await resultado(await post("/api/etiquetas/entrada", {epcs, local_id: +$("#eLocal").value, documento: $("#eDoc").value || null}), "Entrada");
      else if (a === "baixa") { if (!confirm(`Baixar ${epcs.length} peça(s) (${$("#bMotivo").value})?`)) return;
        await resultado(await post("/api/etiquetas/baixa", {epcs, motivo: $("#bMotivo").value, documento: $("#bDoc").value || null}), "Baixa"); }
      else if (a === "estorno") await resultado(await post("/api/etiquetas/estorno", {epcs}), "Estorno");
      else if (a === "transferencia") await resultado(await post("/api/etiquetas/transferencia", {epcs, destino_id: +$("#tLocal").value}), "Transferência");
      else if (a === "cancelar") { const m = prompt(`Cancelar ${epcs.length} etiqueta(s)? Motivo:`); if (m === null) return;
        await resultado(await post("/api/etiquetas/cancelar", {epcs, motivo: m}), "Cancelar"); }
    }));
    let gravando = null;
    $("#btGravar").onclick = () => tentar(async () => {
      if (!Leitor.online) return avisar("Coletor desconectado: abra a tela Estação PC no coletor", "erro");
      let epc = $("#gEpc").value.trim().toUpperCase();
      if ($("#gOF").value) {
        const r = await get(`/api/ordens/${$("#gOF").value}/proxima`);
        if (!r.etiqueta) return avisar("Todas as etiquetas desta OF já foram gravadas", "info");
        epc = r.etiqueta.epc;
      }
      if (!epc) return avisar("Escolha a OF ou digite o EPC", "info");
      gravando = epc; $("#gRes").textContent = "Gravando " + epc + "…";
      await Leitor.comando("gravar", {texto: epc, potencia: +(CFG.potencia_gravacao || 30)});
    });
    Leitor.aoEvento = async ev => {
      if (ev.tipo !== "gravacao") return;
      const d = ev.dados;
      if (d.ok) {
        $("#gRes").innerHTML = `✔ Gravado <span class="mono">${esc(d.novo)}</span>`;
        await post("/api/etiquetas/gravacao", {epc: d.novo, antigo: d.antigo}).catch(e => avisar(e.message, "erro"));
        avisar("Etiqueta gravada"); await atualizarSituacao([d.novo]);
      } else { $("#gRes").textContent = "✖ " + d.mensagem; avisar(d.mensagem, "erro"); }
      gravando = null;
    };
    desenhar();
  },
};

// ============================================================ Expedição (conferência de embarque)
PAGINAS.pedidos = {
  titulo: "Expedição · conferência",
  async abrir(el) {
    el.innerHTML = `<div class="dica">Pedido de <b>venda</b> (as peças conferidas são baixadas) ou de <b>transferência</b> entre locais.
      Na conferência cada peça lida é validada: tem que estar no estoque do local de saída, ser um produto do pedido e não passar da quantidade.</div>
      <div class="card"><h2>Pedidos<span class="dir"><select id="fSt"><option value="ABERTO">Em conferência</option><option value="">Todos</option>
        <option value="FINALIZADO">Finalizados</option><option value="CANCELADO">Cancelados</option></select><button class="p" id="btNovo">+ Novo pedido</button></span></h2><div id="lista"></div></div>`;
    const carregar = async () => {
      const lista = await get("/api/pedidos?status=" + $("#fSt").value);
      listaSel($("#lista"), [{t: "Pedido", f: p => `<b>${esc(p.numero)}</b>`, csv: p => p.numero}, {t: "Tipo", k: "tipo"},
        {t: "Cliente / destino", f: p => esc(p.tipo === "VENDA" ? p.cliente : "→ " + p.destino)},
        {t: "Sai de", k: "local"}, {t: "Conferência", f: p => `${progresso(p.lidas, p.quantidade)}<span class="fraco">${p.lidas}/${p.quantidade}</span>`, csv: p => `${p.lidas}/${p.quantidade}`},
        {t: "Situação", f: p => selo(p.status), csv: p => p.status}, {t: "Criado", f: p => dataBR(p.criado_em)}], lista,
        {vazio: "Nenhum pedido", nome: "pedidos", aoClicar: p => ir("pedido/" + p.id),
         acoes: [["🚫 Cancelar selecionados", "perigo", async l => {
           const abertos = l.filter(p => p.status === "ABERTO");
           if (!abertos.length) return avisar("Só pedido em conferência pode ser cancelado", "info");
           if (!await confirmar("Cancelar pedidos", `Cancelar ${abertos.length} pedido(s)? Nenhuma peça é baixada.`)) return;
           await emLote(abertos, "Pedidos cancelados", p => post(`/api/pedidos/${p.id}/cancelar`), carregar); }]]});
    };
    $("#fSt").onchange = () => tentar(carregar);
    $("#btNovo").onclick = () => novoPedido();
    await carregar();
  },
};

async function novoPedido() {
  abrirDlg("Novo pedido", `<div class="form"><label>Número (vazio = automático)<input id="pNum"></label>
      <label>Tipo<select id="pTipo"><option value="VENDA">Venda (baixa)</option><option value="TRANSFERENCIA">Transferência</option></select></label>
      <label>Sai do local<select id="pLocal">${opcoesLocais(CFG.local_padrao, "Qualquer local")}</select></label>
      <label id="lCliente">Cliente<input id="pCliente"></label><label id="lDestino" class="oculto">Destino<select id="pDestino">${opcoesLocais()}</select></label>
      <label>Documento (NF)<input id="pDoc"></label></div><h4 style="margin:14px 0 6px">Itens</h4><div id="pItens"></div>`,
    [["Cancelar", "", fecharDlg], ["Criar pedido", "p", async () => {
      const tipo = $("#pTipo").value;
      const p = await post("/api/pedidos", {numero: $("#pNum").value || null, tipo, cliente: $("#pCliente").value || null, local_id: +$("#pLocal").value || null,
        destino_id: tipo === "TRANSFERENCIA" ? +$("#pDestino").value : null, documento: $("#pDoc").value || null, itens: pegar()});
      avisar("Pedido " + p.numero + " criado"); fecharDlg(); ir("pedido/" + p.id);
    }]], {largo: true});
  $("#pTipo").onchange = () => { const t = $("#pTipo").value === "TRANSFERENCIA"; $("#lCliente").classList.toggle("oculto", t); $("#lDestino").classList.toggle("oculto", !t); };
  const pegar = await seletorItens($("#pItens"), {saldo: true});
}

PAGINAS.pedido = {
  titulo: "Pedido",
  async abrir(el, id) {
    let p;
    const selItens = new Set(), selLidas = new Set();
    const desenhar = async () => {
      p = await get("/api/pedidos/" + id);
      $("#titulo").textContent = "Pedido " + p.numero;
      const aberto = p.status === "ABERTO";
      el.innerHTML = `<div class="botoes" style="margin-bottom:12px"><button onclick="ir('pedidos')">← Pedidos</button>${selo(p.status)}
          <span class="fraco">${p.tipo === "VENDA" ? "Venda para " + esc(p.cliente || "-") : "Transferência → " + esc(p.destino)} · sai de ${esc(p.local || "qualquer local")}${p.documento ? " · doc. " + esc(p.documento) : ""}</span></div>
        <div class="kpis"><div class="kpi"><div class="rot">Peças no pedido</div><div class="val">${p.quantidade}</div></div>
          <div class="kpi"><div class="rot">Conferidas</div><div class="val">${p.lidas}</div>${progresso(p.lidas, p.quantidade)}</div>
          <div class="kpi"><div class="rot">Faltam</div><div class="val">${Math.max(0, p.quantidade - p.lidas)}</div></div></div>
        ${aberto ? `<div class="card"><h2>Conferir</h2><div class="fraco">Leia as peças (▶ Ler no topo, tela <b>Expedição</b> no coletor, ou leitor USB).</div>${campoCaptura("capPed")}<div id="recusas"></div></div>` : ""}
        <div class="grade2"><div class="card"><h2>Itens</h2><div id="pdItens"></div></div>
          <div class="card"><h2>Peças conferidas</h2><div id="pdLidas"></div></div></div>
        ${aberto ? `<div class="botoes"><button class="suc" id="btFin">✔ Finalizar ${p.tipo === "VENDA" ? "(baixar as conferidas)" : "(transferir as conferidas)"}</button>
          <button class="perigo" id="btCanc">Cancelar pedido</button></div>` : ""}`;
      const remover = l => emLote(l, "Peças removidas da conferência", async t => { await del(`/api/pedidos/${id}/leituras/${t.epc}`); Leitor.vistas.delete(t.epc); }, desenhar);
      listaSel($("#pdItens"), [{t: "SKU", f: i => `<b>${esc(i.sku)}</b>`, csv: i => i.sku}, {t: "Descrição", f: i => `${esc(i.descricao)} <span class="fraco">${esc(variante(i))}</span>`},
          {t: "Pedido", k: "quantidade", n: 1}, {t: "Conferido", k: "lidas", n: 1}, {t: "", f: i => progresso(i.lidas, i.quantidade)}], p.itens,
        {sel: selItens, nome: p.numero + "-itens", acoes: aberto ? [["✖ Tirar as peças conferidas destes itens", "", async l => {
          const skus = new Set(l.map(i => i.sku));
          await remover(p.leituras.filter(t => skus.has(t.sku))); }]] : []});
      listaSel($("#pdLidas"), [{t: "EPC", k: "epc", cl: "mono"}, {t: "Produto", f: t => `${esc(t.sku)} <span class="fraco">${esc(variante(t))}</span>`, csv: t => t.sku},
          {t: "", f: t => aberto ? `<button class="link" data-x="${t.epc}">remover</button>` : ""}], p.leituras,
        {sel: selLidas, chave: t => t.epc, alt: "40vh", nome: p.numero + "-conferidas", aoClicar: t => mostrarEtiqueta(t.epc),
         acoes: aberto ? [["✖ Remover selecionadas", "", remover]] : []});
      if (!aberto) return;
      $$("[data-x]").forEach(b => b.onclick = () => remover([{epc: b.dataset.x}]));
      $("#btFin").onclick = () => tentar(async () => {
        const falta = p.quantidade - p.lidas;
        if (!confirm(falta > 0 ? `Faltam ${falta} peça(s). Finalizar mesmo assim?` : "Finalizar o pedido?")) return;
        const r = await post(`/api/pedidos/${id}/finalizar`); avisar(`${r.quantidade} peça(s) ${p.tipo === "VENDA" ? "baixadas" : "transferidas"}`); desenhar(); });
      $("#btCanc").onclick = () => tentar(async () => { if (!confirm("Cancelar o pedido?")) return; await post(`/api/pedidos/${id}/cancelar`); desenhar(); });
    };
    definirSaida(epcs => tentar(async () => {
      const r = await post(`/api/pedidos/${id}/leituras`, {epcs});
      const ruins = r.leituras.filter(x => !x.ok);
      if (ruins.length) avisar(ruins.slice(0, 4).map(x => (x.sku || x.epc.slice(-8)) + ": " + x.motivo).join("\n"), "erro");
      await desenhar();
    }));
    await desenhar();
  },
};

// ============================================================ Inventário
PAGINAS.inventarios = {
  titulo: "Inventário",
  async abrir(el) {
    const grupos = await get("/api/grupos");
    el.innerHTML = `<div class="card"><h2>Novo inventário</h2><div class="filtros">
        <label>Nome<input id="iNome" placeholder="Ex.: Loja - setembro"></label>
        <label>Local<select id="iLocal">${opcoesLocais("", "Todos os locais")}</select></label>
        <label>Parcial por grupo<select id="iGrupo"><option value="">Total (todos os grupos)</option>${grupos.map(g => `<option>${esc(g)}</option>`).join("")}</select></label>
        <button class="p" id="btCriar">Iniciar</button></div>
        <div class="fraco">Depois leia as peças com o coletor (tela <b>Inventário</b>) ou pelo PC. O resultado aparece ao vivo.</div></div>
      <div class="card"><h2>Inventários</h2><div id="lista"></div></div>`;
    $("#btCriar").onclick = () => tentar(async () => {
      const r = await post("/api/inventarios", {nome: $("#iNome").value, local_id: +$("#iLocal").value || null, grupo: $("#iGrupo").value || null});
      ir("inventario/" + r.id); });
    const carregar = async () => {
      const lista = await get("/api/inventarios");
      listaSel($("#lista"), [{t: "Inventário", f: i => `<b>${esc(i.nome)}</b>`, csv: i => i.nome}, {t: "Escopo", f: i => esc([i.local || "Todos os locais", i.grupo].filter(Boolean).join(" · "))},
        {t: "Aberto", f: i => dataBR(i.aberto_em)}, {t: "Lidas", n: 1, f: i => num(i.status === "ABERTO" ? i.lidas_agora : i.lidas), csv: i => i.status === "ABERTO" ? i.lidas_agora : i.lidas},
        {t: "Acuracidade", n: 1, f: i => i.esperado ? (100 * i.ok / i.esperado).toFixed(1) + "%" : "-"}, {t: "Situação", f: i => selo(i.status), csv: i => i.status}], lista,
        {vazio: "Nenhum inventário", nome: "inventarios", aoClicar: i => ir("inventario/" + i.id),
         acoes: [["🚫 Cancelar selecionados", "perigo", async l => {
           const abertos = l.filter(i => i.status === "ABERTO");
           if (!abertos.length) return avisar("Só inventário aberto pode ser cancelado", "info");
           if (!await confirmar("Cancelar inventários", `Cancelar ${abertos.length} inventário(s)? Nada é ajustado no estoque.`)) return;
           await emLote(abertos, "Inventários cancelados", i => post(`/api/inventarios/${i.id}/cancelar`), carregar); }]]});
    };
    await carregar();
  },
};

PAGINAS.inventario = {
  titulo: "Inventário",
  async abrir(el, id) {
    let filtro = "", inv, filtroProdutos = null;
    const selProd = new Set(), selEtqs = new Set();   // seleção continua na atualização automática (3 s)
    const desenhar = async () => {
      inv = await get("/api/inventarios/" + id);
      $("#titulo").textContent = "Inventário: " + inv.nome;
      const aberto = inv.status === "ABERTO", c = inv.contagem;
      const lista = inv.etiquetas.filter(t => !filtro || t.situacao === filtro);
      const chip = (s, rot, n) => `<button class="${filtro === s ? "p" : ""} peq" data-f="${s}">${rot} (${num(n)})</button>`;
      el.innerHTML = `<div class="botoes" style="margin-bottom:12px"><button onclick="ir('inventarios')">← Inventários</button>${selo(inv.status)}
          <span class="fraco">${esc([inv.local || "Todos os locais", inv.grupo ? "grupo " + inv.grupo : "total"].join(" · "))} · aberto ${dataBR(inv.aberto_em)}</span>
          <span style="flex:1"></span><button onclick="baixar('/api/inventarios/${id}/contagem.csv')">⬇ Arquivo da contagem (CSV)</button></div>
        <div class="kpis"><div class="kpi"><div class="rot">Esperado (sistema)</div><div class="val">${num(inv.esperado)}</div></div>
          <div class="kpi"><div class="rot">Lidas</div><div class="val">${num(inv.lidas)}</div></div>
          <div class="kpi"><div class="rot">Encontradas</div><div class="val" style="color:var(--sucesso)">${num(c.OK)}</div></div>
          <div class="kpi"><div class="rot">Faltando</div><div class="val" style="color:var(--perigo)">${num(c.FALTA)}</div></div>
          <div class="kpi"><div class="rot">Sobrando / outro local</div><div class="val" style="color:var(--alerta)">${num(c.SOBRA + c.OUTRO_LOCAL + c.BAIXADA + c.DESCONHECIDA)}</div></div>
          <div class="kpi"><div class="rot">Acuracidade</div><div class="val">${inv.acuracidade == null ? "-" : inv.acuracidade + "%"}</div></div></div>
        ${aberto ? `<div class="card"><h2>Ler peças</h2>${campoCaptura("capInv")}</div>` : ""}
        <div class="grade2"><div class="card"><h2>Por produto</h2><div id="ivProd"></div></div>
          <div class="card"><h2>Etiquetas</h2><div class="botoes" style="margin-bottom:8px">${chip("", "Todas", inv.etiquetas.length)}${chip("OK", "Ok", c.OK)}${chip("FALTA", "Faltando", c.FALTA)}
              ${chip("SOBRA", "Sobra", c.SOBRA)}${chip("OUTRO_LOCAL", "Outro local", c.OUTRO_LOCAL)}${chip("BAIXADA", "Baixada", c.BAIXADA)}${chip("DESCONHECIDA", "Desconhecida", c.DESCONHECIDA)}</div>
            <div id="ivEtqs"></div></div></div>
        ${aberto ? `<div class="botoes"><button class="suc" id="btFin">✔ Finalizar inventário</button><button id="btZerar">Zerar leituras</button><button class="perigo" id="btCanc">Cancelar</button></div>` : ""}`;
      $$("[data-f]").forEach(b => b.onclick = () => { filtro = b.dataset.f; desenhar(); });
      listaSel($("#ivProd"), [{t: "SKU", f: p => `<b>${esc(p.sku)}</b>`, csv: p => p.sku}, {t: "Descrição", f: p => `${esc(p.descricao)} <span class="fraco">${esc(variante(p))}</span>`},
          {t: "Sistema", k: "esperado", n: 1}, {t: "Lido", k: "lido", n: 1},
          {t: "Diferença", n: 1, f: p => `<b style="color:${p.diferenca < 0 ? "var(--perigo)" : p.diferenca > 0 ? "var(--alerta)" : "var(--sucesso)"}">${p.diferenca > 0 ? "+" : ""}${p.diferenca}</b>`, csv: p => p.diferenca}],
        inv.produtos, {sel: selProd, chave: p => p.produto_id, alt: "50vh", nome: "inventario-" + id + "-produtos",
          acoes: [["🔎 Ver só as etiquetas destes produtos", "", async l => { filtroProdutos = new Set(l.map(p => p.produto_id)); await desenhar(); }]]});
      const visiveis = (filtroProdutos ? lista.filter(t => filtroProdutos.has(t.produto_id)) : lista).slice(0, 1500);
      listaSel($("#ivEtqs"), [{t: "EPC", k: "epc", cl: "mono"}, {t: "Produto", f: descProduto}, {t: "Situação", f: t => selo(t.situacao), csv: t => t.situacao},
          {t: "Local no sistema", k: "local"},
          {t: "", f: t => aberto && t.situacao === "DESCONHECIDA" ? `<button class="link" data-inc="${t.epc}">incluir</button>` : ""}], visiveis,
        {sel: selEtqs, chave: t => t.epc, alt: "50vh", nome: "inventario-" + id + "-etiquetas", aoClicar: t => mostrarEtiqueta(t.epc),
         acoes: [filtroProdutos ? ["✖ Mostrar todos os produtos", "", async () => { filtroProdutos = null; await desenhar(); }] : null,
                 aberto ? ["➕ Incluir desconhecidas no estoque", "", async l => {
                   const desc = l.filter(t => t.situacao === "DESCONHECIDA");
                   if (!desc.length) return avisar("Nenhuma etiqueta desconhecida selecionada", "info");
                   const produtos = await get("/api/produtos?ativos=true");
                   const pid = await escolher("Incluir no estoque", `${desc.length} etiqueta(s) desconhecida(s) viram peças do produto:`, "Produto",
                     produtos.map(p => [p.id, `${p.sku} · ${p.descricao} ${variante(p)}`]), desc[0].sugerido?.id);
                   if (pid === null) return;
                   await emLote(desc, "Incluídas", t => post(`/api/inventarios/${id}/incluir`, {epc: t.epc, produto_id: +pid}), desenhar); }] : null]});
      if (!aberto) return;
      $$("[data-inc]").forEach(b => b.onclick = () => incluirDesconhecida(id, inv.etiquetas.find(t => t.epc === b.dataset.inc), desenhar));
      $("#btFin").onclick = () => abrirDlg("Finalizar inventário", `<p>Encontradas <b>${c.OK}</b> de <b>${inv.esperado}</b> (acuracidade ${inv.acuracidade ?? "-"}%).</p>
          <label class="check"><input type="checkbox" id="fAj" checked> Ajustar o estoque: faltas (${c.FALTA}) saem, sobras e baixadas encontradas (${c.SOBRA + c.BAIXADA}) entram${inv.local_id ? `, peças de outro local (${c.OUTRO_LOCAL}) vêm para ${esc(inv.local)}` : ""}</label>
          ${c.DESCONHECIDA ? `<div class="dica" style="background:var(--f-alerta);margin-top:10px">${c.DESCONHECIDA} etiqueta(s) desconhecida(s) não entram no estoque. Use "incluir" antes para vincular a um produto.</div>` : ""}`,
        [["Voltar", "", fecharDlg], ["Finalizar", "suc", async () => {
          const r = await post(`/api/inventarios/${id}/finalizar`, {ajustar: $("#fAj").checked}); fecharDlg(); avisar(`Inventário finalizado · ${r.ajustes} ajuste(s)`); desenhar(); }]]);
      $("#btZerar").onclick = () => tentar(async () => { if (!confirm("Apagar todas as leituras deste inventário?")) return; await del(`/api/inventarios/${id}/leituras`); Leitor.esquecer(); desenhar(); });
      $("#btCanc").onclick = () => tentar(async () => { if (!confirm("Cancelar o inventário (nada é ajustado)?")) return; await post(`/api/inventarios/${id}/cancelar`); desenhar(); });
    };
    definirSaida(epcs => tentar(async () => { await post(`/api/inventarios/${id}/leituras`, {epcs}); await desenhar(); }));
    await desenhar();
    aCada(3000, () => inv?.status === "ABERTO" && tentar(desenhar));
  },
};

async function incluirDesconhecida(invId, t, depois) {
  const produtos = await get("/api/produtos?ativos=true");
  abrirDlg("Incluir etiqueta no estoque", `<div class="mono" style="margin-bottom:8px">${esc(t.epc)}</div>
      <label class="form">Produto<select id="incP">${produtos.map(p => `<option value="${p.id}" ${t.sugerido?.id === p.id ? "selected" : ""}>${esc(p.sku)} · ${esc(p.descricao)} ${esc(variante(p))}</option>`).join("")}</select></label>`,
    [["Cancelar", "", fecharDlg], ["Incluir", "p", async () => {
      await post(`/api/inventarios/${invId}/incluir`, {epc: t.epc, produto_id: +$("#incP").value}); fecharDlg(); avisar("Etiqueta incluída"); depois(); }]]);
}

// ============================================================ Antifurto
PAGINAS.antifurto = {
  titulo: "Antifurto",
  async abrir(el) {
    const alarmes = new Map();
    el.innerHTML = `<div class="dica">Deixe o coletor (ou um leitor fixo) na saída lendo sem parar. Peça <b>vendida/baixada</b> passa em silêncio; peça que
        ainda está <b>no estoque</b> dispara o alarme e gera um alerta. Toque em <b>Conferido</b> para tirar da lista.</div>
      <div class="card"><h2>Alarmes <span class="selo erro" id="nAl">0</span><span class="dir"><input id="afPonto" placeholder="Ponto (ex.: Porta loja)" style="width:180px">
        <button id="btLimparAf">Limpar lista</button></span></h2>${campoCaptura("capAf")}<div id="alarmes"></div></div>`;
    const bip = () => { try { const a = new AudioContext(), o = a.createOscillator(); o.frequency.value = 1200; o.connect(a.destination); o.start(); setTimeout(() => { o.stop(); a.close(); }, 350); } catch (e) {} };
    const desenhar = () => {
      const lista = [...alarmes.values()];
      $("#nAl").textContent = lista.length;
      listaSel($("#alarmes"), [{t: "Hora", k: "hora"}, {t: "EPC", k: "epc", cl: "mono"}, {t: "Produto", f: descProduto}, {t: "Local", k: "local"},
        {t: "", f: t => `<button class="peq" data-ok="${t.epc}">Conferido</button>`}], lista,
        {chave: t => t.epc, vazio: "Nenhum alarme", nome: "alarmes-antifurto", aoClicar: t => mostrarEtiqueta(t.epc),
         acoes: [["✔ Conferido (tirar da lista)", "", async l => { l.forEach(t => alarmes.delete(t.epc)); desenhar(); }],
                 ["📤 Baixar como venda", "perigo", async l => {
                   if (!await confirmar("Baixar como venda", `${l.length} peça(s) passaram sem baixa. Registrar a venda agora?`)) return;
                   const r = await post("/api/etiquetas/baixa", {epcs: l.map(t => t.epc), motivo: "VENDA", documento: "ANTIFURTO"});
                   r.ok.forEach(e => alarmes.delete(e)); avisar(`${r.quantidade} baixada(s)`); desenhar(); }]]});
      $$("[data-ok]").forEach(b => b.onclick = () => { alarmes.delete(b.dataset.ok); desenhar(); });
    };
    definirSaida(epcs => tentar(async () => {
      const r = await post("/api/antifurto?ponto=" + encodeURIComponent($("#afPonto").value), {epcs});
      const novos = r.filter(x => x.alarme);
      novos.forEach(x => alarmes.set(x.epc, {...x, hora: new Date().toLocaleTimeString("pt-BR")}));
      if (novos.length) { bip(); desenhar(); }
    }));
    $("#btLimparAf").onclick = () => { alarmes.clear(); Leitor.esquecer(); desenhar(); };
    desenhar();
  },
};

// ============================================================ Movimentações
PAGINAS.movimentos = {
  titulo: "Movimentações",
  async abrir(el) {
    const tipos = ["EMISSAO", "VINCULACAO", "ENTRADA", "BAIXA", "ESTORNO", "TRANSFERENCIA", "AJUSTE_ENTRADA", "AJUSTE_SAIDA", "CANCELAMENTO", "REGRAVACAO", "CONSOLIDACAO"];
    const hoje = new Date().toISOString().slice(0, 10);
    el.innerHTML = `<div class="card"><div class="filtros">
      <label>Tipo<select id="mTipo"><option value="">Todos</option>${tipos.map(t => `<option>${t}</option>`).join("")}</select></label>
      <label>De<input type="date" id="mDe" value="${new Date(Date.now() - 7 * 864e5).toISOString().slice(0, 10)}"></label><label>Até<input type="date" id="mAte" value="${hoje}"></label>
      <label>Local<select id="mLocal">${opcoesLocais("", "Todos")}</select></label>
      <label>Buscar<input id="mQ" placeholder="EPC, SKU, documento"></label><button class="p" id="btFiltrar">Filtrar</button>
      <span style="flex:1"></span><button id="btCsv">⬇ CSV</button></div><div id="lista"></div></div>`;
    const qs = () => new URLSearchParams({tipo: $("#mTipo").value, de: $("#mDe").value, ate: $("#mAte").value, local_id: $("#mLocal").value, q: $("#mQ").value});
    const carregar = async () => {
      const lista = await get("/api/movimentos?limite=1000&" + qs());
      // O histórico não se apaga (kardex): a seleção serve para exportar e para agir nas etiquetas desses movimentos
      const etiquetasDe = l => [...new Map(l.map(m => [m.epc, {epc: m.epc}])).values()];
      listaSel($("#lista"), [{t: "Data/hora", f: m => dataBR(m.data_hora), csv: m => m.data_hora}, {t: "Tipo", k: "tipo"}, {t: "EPC", k: "epc", cl: "mono"},
        {t: "Produto", f: m => `<b>${esc(m.sku)}</b> <span class="fraco">${esc(variante(m))}</span>`, csv: m => m.sku},
        {t: "Qtd", n: 1, f: m => m.quantidade > 0 ? "+1" : m.quantidade < 0 ? "-1" : "", csv: m => m.quantidade},
        {t: "De → para", f: m => esc([m.origem_local, m.destino_local].filter(Boolean).join(" → "))}, {t: "Motivo", k: "motivo"}, {t: "Documento", k: "documento"},
        {t: "Quem", f: m => esc([m.usuario, m.origem].filter(Boolean).join(" · "))}], lista,
        {alt: "68vh", vazio: "Nenhum movimento no período", nome: "movimentos", aoClicar: m => mostrarEtiqueta(m.epc),
         acoes: acoesEtiquetas(carregar, ["estorno", "transferencia", "baixa"]).map(([r, c, fn]) => [r + " (etiquetas)", c, l => fn(etiquetasDe(l))])});
    };
    $("#btFiltrar").onclick = () => tentar(carregar);
    $("#btCsv").onclick = () => baixar("/api/movimentos.csv?" + qs());
    await carregar();
  },
};

// ============================================================ Alertas
PAGINAS.alertas = {
  titulo: "Alertas",
  async abrir(el) {
    const selAlertas = new Set();
    const carregar = async () => {
      const todos = $("#aTodos")?.checked;
      const lista = await get("/api/alertas?todos=" + !!todos);
      el.innerHTML = `<div class="card"><h2>Alertas<span class="dir"><label class="check"><input type="checkbox" id="aTodos" ${todos ? "checked" : ""}> mostrar os lidos</label>
          <button id="btLidos">Marcar todos como lidos</button></span></h2><div id="alLista"></div></div>`;
      const depois = async () => { atualizarBadge(); await carregar(); };
      listaSel($("#alLista"), [{t: "Data/hora", f: a => dataBR(a.data_hora), csv: a => a.data_hora},
          {t: "Tipo", f: a => `<span class="selo ${a.tipo === "ANTIFURTO" ? "erro" : "alerta"}">${esc(a.tipo.replace(/_/g, " ").toLowerCase())}</span>`, csv: a => a.tipo},
          {t: "Mensagem", k: "mensagem"}, {t: "EPC", f: a => a.epc ? `<button class="link mono" data-epc="${a.epc}">${esc(a.epc)}</button>` : "", csv: a => a.epc || ""},
          {t: "", f: a => a.lido ? "" : `<button class="peq" data-lido="${a.id}">Lido</button>`}], lista,
        {sel: selAlertas, vazio: "Nenhum alerta 🎉", nome: "alertas", acoes: [
          ["✔ Marcar como lidos", "", async l => { await post("/api/alertas/lidos", {ids: l.map(a => a.id)}); avisar(`${l.length} marcado(s) como lido(s)`); await depois(); }],
          usuario.perfil === "ADMIN" ? ["🗑 Excluir", "perigo", async l => {
            if (!await confirmar("Excluir alertas", `Excluir ${l.length} alerta(s)?`)) return;
            await post("/api/alertas/excluir", {ids: l.map(a => a.id)}); avisar(`${l.length} excluído(s)`); await depois(); }] : null]});
      $("#aTodos").onchange = () => tentar(carregar);
      $("#btLidos").onclick = () => tentar(async () => { await post("/api/alertas/lidos"); atualizarBadge(); carregar(); });
      $$("[data-lido]").forEach(b => b.onclick = () => tentar(async () => { await post(`/api/alertas/${b.dataset.lido}/lido`); atualizarBadge(); carregar(); }));
      $$("[data-epc]").forEach(b => b.onclick = () => tentar(() => mostrarEtiqueta(b.dataset.epc)));
    };
    await carregar();
  },
};

// ============================================================ Monitor (dispositivos e impressoras)
PAGINAS.monitor = {
  titulo: "Monitor",
  async abrir(el) {
    const selDisp = new Set(), selImp = new Set(), testes = {};
    el.innerHTML = `<div class="card"><h2>Coletores</h2><div id="mnDisp"></div></div><div class="card"><h2>Impressoras</h2><div id="mnImp"></div></div>`;
    const testar = async i => {
      testes[i.id] = "testando…"; desenharImp();
      try { testes[i.id] = "✔ " + (await post(`/api/impressoras/${i.id}/testar`)).mensagem; } catch (e) { testes[i.id] = "✖ " + e.message; }
      desenharImp();
    };
    let imps = [];
    const desenharImp = () => {
      listaSel($("#mnImp"), [{t: "Impressora", f: i => `<b>${esc(i.nome)}</b>`, csv: i => i.nome},
          {t: "Conexão", f: i => i.tipo === "REDE" ? esc(i.endereco + ":" + i.porta) : "Windows: " + esc(i.endereco)},
          {t: "Teste", f: i => `<button class="peq" data-t="${i.id}">Testar conexão</button> <span class="fraco">${esc(testes[i.id] || "")}</span>`, csv: i => testes[i.id] || ""}], imps,
        {sel: selImp, vazio: "Nenhuma impressora cadastrada", nome: "impressoras",
         acoes: [["🔌 Testar selecionadas", "", async l => { for (const i of l) await testar(i); }]]});
      $$("[data-t]", $("#mnImp")).forEach(b => b.onclick = () => testar(imps.find(i => i.id === +b.dataset.t)));
    };
    const carregar = async () => {
      let disp;
      [disp, imps] = await Promise.all([get("/api/dispositivos"), get("/api/impressoras")]);
      listaSel($("#mnDisp"), [{t: "", f: d => `<span class="ponto ${d.online ? "on" : ""}"></span>`},
          {t: "Coletor", f: d => `<b>${esc(d.nome || d.id)}</b><br><span class="fraco">${esc(d.id)}</span>`, csv: d => d.nome || d.id}, {t: "IP", k: "ip"}, {t: "Tela", k: "tela"},
          {t: "RFID", k: "rfid"}, {t: "Bateria", n: 1, f: d => d.bateria == null ? "-" : d.bateria + "%", csv: d => d.bateria ?? ""}, {t: "App", k: "versao"},
          {t: "Último sinal", f: d => d.online ? "agora" : dataBR(d.ultimo_sinal), csv: d => d.ultimo_sinal}], disp,
        {sel: selDisp, vazio: "Nenhum coletor conectou ainda", nome: "coletores",
         acoes: [usuario.perfil === "ADMIN" ? ["🗑 Tirar do monitor", "perigo", async l => {
           if (!await confirmar("Tirar do monitor", `${l.length} coletor(es) saem da lista. Voltam sozinhos se falarem com o servidor de novo.`)) return;
           await post("/api/dispositivos/excluir", {ids: l.map(d => d.id)}); avisar(`${l.length} coletor(es) removido(s)`); await carregar(); }] : null]});
      desenharImp();
    };
    await carregar();
    aCada(10000, () => tentar(carregar));
  },
};

// ============================================================ Produtos
PAGINAS.produtos = {
  titulo: "Produtos",
  async abrir(el) {
    const adm = usuario.perfil === "ADMIN";
    el.innerHTML = `<div class="card"><div class="filtros"><label>Buscar<input id="pQ" placeholder="SKU, descrição, GTIN, cor"></label>
        <span style="flex:1"></span><button id="btImp">⬆ Importar CSV</button><button onclick="baixar('/api/produtos.csv')">⬇ Exportar CSV</button>
        <button class="p" id="btNovo">+ Novo produto</button></div><div id="lista"></div></div>`;
    const ativo = (l, v) => emLote(l.filter(p => !!p.ativo !== v), v ? "Ativados" : "Desativados", p => put("/api/produtos/" + p.id, {...p, ativo: v}), carregar);
    const carregar = async () => {
      const lista = await get("/api/produtos?q=" + encodeURIComponent($("#pQ").value));
      listaSel($("#lista"), [
        {t: "SKU", f: p => `<b>${esc(p.sku)}</b>`, csv: p => p.sku}, {t: "Descrição", k: "descricao"}, {t: "Cor", k: "cor"}, {t: "Tam.", k: "tamanho"},
        {t: "Grupo", f: p => esc([p.grupo, p.subgrupo].filter(Boolean).join(" / "))}, {t: "GTIN / EAN", k: "gtin", cl: "mono"},
        {t: "Preço", n: 1, f: p => p.preco ? moeda(p.preco) : "", csv: p => String(p.preco).replace(".", ",")}, {t: "Mín.", k: "estoque_min", n: 1}, {t: "Saldo", k: "saldo", n: 1},
        {t: "Ativo", f: p => p.ativo ? "" : '<span class="selo">inativo</span>', csv: p => p.ativo ? "sim" : "não"}], lista,
        {alt: "70vh", vazio: "Nenhum produto cadastrado", nome: "produtos", aoClicar: p => editarProduto(p, carregar),
         acoes: [
           ["🖨 Gerar OF", "p", async l => {
             const q = await escolher("Gerar OF", `${l.length} produto(s) selecionado(s).`, "Etiquetas de cada produto", null, "1");
             const n = parseInt(q); if (q === null || !(n > 0)) return;
             const o = await post("/api/ordens", {itens: l.filter(p => p.ativo).map(p => ({produto_id: p.id, quantidade: n}))});
             avisar(`${o.numero}: ${o.quantidade} etiqueta(s)`); ir("ordem/" + o.id); }],
           ["✔ Ativar", "", l => ativo(l, true)], ["⏸ Desativar", "", l => ativo(l, false)],
           adm ? ["🗑 Excluir", "perigo", async l => {
             const nomes = l.slice(0, 8).map(p => p.sku).join(", ") + (l.length > 8 ? ` e mais ${l.length - 8}` : "");
             if (!await confirmar("Excluir produtos", `Excluir ${l.length} produto(s)?<br><b>${esc(nomes)}</b><br>Produto que já tem etiquetas não é excluído (desative em vez disso).`)) return;
             const r = await post("/api/produtos/excluir", {ids: l.map(p => p.id)});
             avisar(`${r.excluidos} produto(s) excluído(s)` + (r.mantidos.length ? `\n${r.mantidos.length} mantido(s) porque já têm etiquetas: ${r.mantidos.slice(0, 5).join(", ")}${r.mantidos.length > 5 ? "…" : ""}` : ""),
                    r.mantidos.length ? "info" : "ok", r.mantidos.length ? 9000 : 3800);
             await carregar(); }] : null]});
    };
    let t; $("#pQ").oninput = () => { clearTimeout(t); t = setTimeout(() => tentar(carregar), 300); };
    $("#btNovo").onclick = () => editarProduto(null, carregar);
    $("#btImp").onclick = () => abrirDlg("Importar produtos (CSV)", `<div class="dica">Primeira linha com os nomes das colunas (separador <b>;</b>):<br>
        <span class="mono">sku;descricao;gtin;grupo;subgrupo;cor;tamanho;preco;estoque_min;unidade</span><br>SKU que já existe é atualizado. Pode colar do Excel.</div>
        <input type="file" id="impArq" accept=".csv,.txt"><textarea id="impTxt" rows="12" style="width:100%;margin-top:8px" placeholder="sku;descricao;gtin;cor;tamanho;preco"></textarea>`,
      [["Cancelar", "", fecharDlg], ["Importar", "p", async () => {
        const r = await post("/api/produtos/importar", {csv: $("#impTxt").value.replace(/\t/g, ";")});
        avisar(`${r.criados} criado(s), ${r.atualizados} atualizado(s)` + (r.erros.length ? `\n${r.erros.length} erro(s): ${r.erros.slice(0, 3).join("; ")}` : ""), r.erros.length ? "erro" : "ok", 8000);
        fecharDlg(); carregar(); }]]);
    document.addEventListener("change", async e => { if (e.target.id === "impArq" && e.target.files[0]) $("#impTxt").value = await e.target.files[0].text(); });
    await carregar();
  },
};

function editarProduto(p, depois) {
  p = p || {ativo: 1, unidade: "UN", preco: 0, estoque_min: 0};
  const campo = (k, rot, tipo = "text", extra = "") => `<label>${rot}<input id="pr_${k}" type="${tipo}" value="${esc(p[k] ?? "")}" ${extra}></label>`;
  abrirDlg(p.id ? "Produto " + p.sku : "Novo produto", `<div class="form">${campo("sku", "SKU / referência *")}${campo("descricao", "Descrição *")}
      ${campo("gtin", "GTIN / EAN (vira o EPC SGTIN-96)")}${campo("grupo", "Grupo")}${campo("subgrupo", "Subgrupo")}${campo("cor", "Cor")}${campo("tamanho", "Tamanho")}
      ${campo("unidade", "Unidade")}${campo("preco", "Preço", "number", 'step="0.01" min="0"')}${campo("estoque_min", "Estoque mínimo", "number", 'min="0"')}
      <label class="check largo"><input type="checkbox" id="pr_ativo" ${p.ativo ? "checked" : ""}> Ativo</label></div>
      <div class="fraco" style="margin-top:8px">Sem GTIN, o sistema usa EPC GID-96 (código interno) nas etiquetas deste produto.</div>`,
    [...(p.id && usuario.perfil === "ADMIN" ? [["Excluir", "perigo", async () => { if (!confirm("Excluir o produto?")) return; await del("/api/produtos/" + p.id); fecharDlg(); depois(); }]] : []),
     ["Cancelar", "", fecharDlg], ["Salvar", "p", async () => {
      const d = {}; ["sku", "descricao", "gtin", "grupo", "subgrupo", "cor", "tamanho", "unidade"].forEach(k => d[k] = $("#pr_" + k).value.trim() || null);
      d.preco = parseFloat($("#pr_preco").value) || 0; d.estoque_min = parseInt($("#pr_estoque_min").value) || 0; d.ativo = $("#pr_ativo").checked;
      d.unidade = d.unidade || "UN";
      if (p.id) await put("/api/produtos/" + p.id, d); else await post("/api/produtos", d);
      avisar("Produto salvo"); fecharDlg(); depois(); }]]);
}

// ============================================================ Locais
PAGINAS.locais = {
  titulo: "Locais de estoque",
  async abrir(el) {
    LOCAIS = await get("/api/locais");
    const adm = usuario.perfil === "ADMIN";
    el.innerHTML = `<div class="card"><h2>Locais<span class="dir"><button class="p" id="btNovo">+ Novo local</button></span></h2><div id="lcLista"></div></div>`;
    const salvarAtivo = (l, v) => emLote(l.filter(x => !!x.ativo !== v), v ? "Ativados" : "Inativados",
      x => put("/api/locais/" + x.id, {codigo: x.codigo, nome: x.nome, tipo: x.tipo, ativo: v}), async () => { await carregarBase(); ir("locais"); });
    listaSel($("#lcLista"), [
      {t: "Código", f: l => `<b>${esc(l.codigo)}</b>`, csv: l => l.codigo}, {t: "Nome", k: "nome"}, {t: "Tipo", k: "tipo"}, {t: "Peças", k: "quantidade", n: 1},
      {t: "", f: l => (String(l.id) === String(CFG.local_padrao) ? '<span class="selo ok">padrão</span> ' : "") + (l.ativo ? "" : '<span class="selo">inativo</span>'),
       csv: l => l.ativo ? "ativo" : "inativo"}],
      LOCAIS, {nome: "locais", aoClicar: l => editar(l), acoes: adm ? [
        ["✔ Ativar", "", l => salvarAtivo(l, true)], ["⏸ Inativar", "", l => salvarAtivo(l, false)],
        ["🗑 Excluir", "perigo", async l => {
          if (!await confirmar("Excluir locais", `Excluir ${l.length} local(is)? Local já usado (peças, histórico, OF, pedido ou inventário) ou o local padrão não é excluído — inative.`)) return;
          const r = await post("/api/locais/excluir", {ids: l.map(x => x.id)});
          avisar(`${r.excluidos} excluído(s)` + (r.mantidos.length ? `\n${r.mantidos.length} mantido(s) porque já foram usados: ${r.mantidos.join(", ")}` : ""), r.mantidos.length ? "info" : "ok", 8000);
          await carregarBase(); ir("locais"); }]] : []});
    const editar = l => {
      l = l || {tipo: "DEPOSITO", ativo: 1};
      abrirDlg(l.id ? "Local " + l.codigo : "Novo local", `<div class="form"><label>Código<input id="lc" value="${esc(l.codigo || "")}"></label>
          <label>Nome<input id="ln" value="${esc(l.nome || "")}"></label><label>Tipo<select id="lt">${["DEPOSITO", "LOJA", "EXPEDICAO", "AVARIA"].map(t => `<option ${t === l.tipo ? "selected" : ""}>${t}</option>`).join("")}</select></label>
          <label class="check"><input type="checkbox" id="la" ${l.ativo ? "checked" : ""}> Ativo</label></div>`,
        [["Cancelar", "", fecharDlg], ["Salvar", "p", async () => {
          const d = {codigo: $("#lc").value, nome: $("#ln").value, tipo: $("#lt").value, ativo: $("#la").checked};
          if (l.id) await put("/api/locais/" + l.id, d); else await post("/api/locais", d);
          fecharDlg(); await carregarBase(); ir("locais"); }]]);
    };
    $("#btNovo").onclick = () => editar();
  },
};

// ============================================================ Impressoras
PAGINAS.impressoras = {
  titulo: "Impressoras RFID",
  async abrir(el) {
    const lista = await get("/api/impressoras");
    el.innerHTML = `<div class="dica">Impressoras Zebra RFID (ZD621R, ZT411 RFID, ZT231R…) em ZPL. <b>Rede</b>: IP da impressora, porta 9100.
        <b>Windows</b>: impressora USB instalada com o driver ZDesigner (o sistema manda o ZPL direto, em modo RAW). O layout da etiqueta fica em Configurações.</div>
      <div class="card"><h2>Impressoras<span class="dir"><button class="p" id="btNova">+ Nova impressora</button></span></h2><div id="imLista"></div></div>`;
    const teste = i => post(`/api/impressoras/${i.id}/etiqueta-teste`);
    listaSel($("#imLista"), [
      {t: "Nome", f: i => `<b>${esc(i.nome)}</b>`, csv: i => i.nome}, {t: "Conexão", f: i => i.tipo === "REDE" ? "Rede · " + esc(i.endereco + ":" + i.porta) : "Windows · " + esc(i.endereco)},
      {t: "", f: i => `<button class="peq" data-teste="${i.id}">Etiqueta de teste</button> ${i.ativo ? "" : '<span class="selo">inativa</span>'}`, csv: i => i.ativo ? "ativa" : "inativa"}],
      lista, {vazio: "Nenhuma impressora", nome: "impressoras", aoClicar: i => editar(i), acoes: [
        ["🧾 Etiqueta de teste", "", l => emLote(l, "Etiquetas de teste enviadas", teste)],
        usuario.perfil === "ADMIN" ? ["🗑 Excluir", "perigo", async l => {
          if (!await confirmar("Excluir impressoras", `Excluir ${l.length} impressora(s)?`)) return;
          await emLote(l, "Excluídas", i => del("/api/impressoras/" + i.id), async () => ir("impressoras")); }] : null]});
    const editar = async i => {
      i = i || {tipo: "REDE", porta: 9100, ativo: 1};
      const win = await get("/api/impressoras/windows").catch(() => []);
      abrirDlg(i.id ? "Impressora " + i.nome : "Nova impressora", `<div class="form"><label>Nome<input id="in" value="${esc(i.nome || "")}" placeholder="Zebra ZD621R expedição"></label>
          <label>Conexão<select id="it"><option value="REDE" ${i.tipo === "REDE" ? "selected" : ""}>Rede (IP)</option><option value="WINDOWS" ${i.tipo === "WINDOWS" ? "selected" : ""}>Windows (USB)</option></select></label>
          <label id="lIp">IP da impressora<input id="ie" value="${esc(i.tipo === "REDE" ? i.endereco || "" : "")}" placeholder="192.168.0.50"></label>
          <label id="lPorta">Porta<input id="ip" type="number" value="${i.porta || 9100}"></label>
          <label id="lWin" class="largo">Impressora do Windows<select id="iw">${win.map(w => `<option ${w === i.endereco ? "selected" : ""}>${esc(w)}</option>`).join("") || "<option value=''>Nenhuma encontrada</option>"}</select></label>
          <label class="check"><input type="checkbox" id="ia" ${i.ativo ? "checked" : ""}> Ativa</label></div>`,
        [...(i.id ? [["Excluir", "perigo", async () => { if (!confirm("Excluir?")) return; await del("/api/impressoras/" + i.id); fecharDlg(); ir("impressoras"); }]] : []),
         ["Cancelar", "", fecharDlg], ["Salvar", "p", async () => {
          const tipo = $("#it").value;
          const d = {nome: $("#in").value, tipo, endereco: tipo === "REDE" ? $("#ie").value : $("#iw").value, porta: +$("#ip").value || 9100, ativo: $("#ia").checked};
          if (i.id) await put("/api/impressoras/" + i.id, d); else await post("/api/impressoras", d);
          fecharDlg(); ir("impressoras"); }]]);
      const troca = () => { const r = $("#it").value === "REDE"; $("#lIp").classList.toggle("oculto", !r); $("#lPorta").classList.toggle("oculto", !r); $("#lWin").classList.toggle("oculto", r); };
      $("#it").onchange = troca; troca();
    };
    $("#btNova").onclick = () => editar();
    $$("[data-teste]").forEach(b => b.onclick = () => tentar(async () => { await post(`/api/impressoras/${b.dataset.teste}/etiqueta-teste`); avisar("Etiqueta de teste enviada (sem gravar RFID)"); }));
  },
};

// ============================================================ Usuários
PAGINAS.usuarios = {
  titulo: "Usuários",
  async abrir(el) {
    const lista = await get("/api/usuarios");
    el.innerHTML = `<div class="card"><h2>Usuários<span class="dir"><button class="p" id="btNovo">+ Novo usuário</button></span></h2><div id="usLista"></div></div>
      <div class="card"><h2>Minha senha</h2><div class="filtros"><label>Senha atual<input type="password" id="sa"></label><label>Nova senha<input type="password" id="sn"></label>
        <button class="p" id="btSenha">Trocar</button></div></div>`;
    const editar = u => {
      u = u || {perfil: "OPERADOR", ativo: 1};
      abrirDlg(u.id ? "Usuário " + u.login : "Novo usuário", `<div class="form"><label>Login<input id="ul" value="${esc(u.login || "")}" ${u.id ? "disabled" : ""}></label>
          <label>Nome<input id="un" value="${esc(u.nome || "")}"></label><label>${u.id ? "Nova senha (vazio = mantém)" : "Senha"}<input id="us" type="password"></label>
          <label>Perfil<select id="up"><option ${u.perfil === "OPERADOR" ? "selected" : ""}>OPERADOR</option><option ${u.perfil === "ADMIN" ? "selected" : ""}>ADMIN</option></select></label>
          <label class="check"><input type="checkbox" id="ua" ${u.ativo ? "checked" : ""}> Ativo</label></div>`,
        [["Cancelar", "", fecharDlg], ["Salvar", "p", async () => {
          const d = {login: $("#ul").value, nome: $("#un").value, senha: $("#us").value || null, perfil: $("#up").value, ativo: $("#ua").checked};
          if (u.id) await put("/api/usuarios/" + u.id, d); else await post("/api/usuarios", d);
          fecharDlg(); ir("usuarios"); }]]);
    };
    const outros = l => l.filter(u => u.id !== usuario.id);
    const ativo = (l, v) => emLote(outros(l).filter(u => !!u.ativo !== v), v ? "Ativados" : "Inativados",
      u => put("/api/usuarios/" + u.id, {login: u.login, nome: u.nome, perfil: u.perfil, ativo: v}), async () => ir("usuarios"));
    listaSel($("#usLista"), [{t: "Login", f: u => `<b>${esc(u.login)}</b>`, csv: u => u.login}, {t: "Nome", k: "nome"}, {t: "Perfil", k: "perfil"},
      {t: "", f: u => (u.id === usuario.id ? '<span class="selo ok">você</span> ' : "") + (u.ativo ? "" : '<span class="selo">inativo</span>'), csv: u => u.ativo ? "ativo" : "inativo"}],
      lista, {nome: "usuarios", aoClicar: u => editar(u), acoes: [
        ["✔ Ativar", "", l => ativo(l, true)], ["⏸ Inativar", "", l => ativo(l, false)],
        ["🗑 Excluir", "perigo", async l => {
          const alvo = outros(l);
          if (!alvo.length) return avisar("Você não pode excluir o seu próprio usuário", "info");
          if (!await confirmar("Excluir usuários", `Excluir ${alvo.length} usuário(s): <b>${esc(alvo.map(u => u.login).join(", "))}</b>?<br>O histórico continua mostrando o login de quem fez cada movimento.`)) return;
          await post("/api/usuarios/excluir", {ids: alvo.map(u => u.id)}); avisar(`${alvo.length} excluído(s)`); ir("usuarios"); }]]});
    $("#btNovo").onclick = () => editar();
    $("#btSenha").onclick = () => tentar(async () => { await post("/api/minha-senha", {atual: $("#sa").value, nova: $("#sn").value}); avisar("Senha trocada"); $("#sa").value = $("#sn").value = ""; });
  },
};

// ============================================================ Configurações
PAGINAS.config = {
  titulo: "Configurações",
  async abrir(el) {
    CFG = await get("/api/config");
    const adm = usuario.perfil === "ADMIN";
    el.innerHTML = `<div class="card"><h2>Empresa e codificação EPC (GS1)</h2><div class="form">
        <label>Nome da empresa (sai na etiqueta)<input id="cEmp" value="${esc(CFG.empresa)}"></label>
        <label>Dígitos do prefixo GS1 da empresa<select id="cPref">${[6, 7, 8, 9, 10, 11, 12].map(n => `<option ${String(n) === CFG.prefixo_gs1_digitos ? "selected" : ""}>${n}</option>`).join("")}</select></label>
        <label>Filtro EPC<select id="cFiltro">${[["0", "0 - todos"], ["1", "1 - item de venda (PDV)"], ["2", "2 - caixa de embarque"], ["3", "3 - carga completa"]]
          .map(([v, t]) => `<option value="${v}" ${v === CFG.filtro_epc ? "selected" : ""}>${t}</option>`).join("")}</select></label>
        <label>Gerente GID-96 (produtos sem GTIN)<input id="cGid" type="number" value="${esc(CFG.gid_gerente)}"></label>
        <label>Local padrão (entradas)<select id="cLocal">${opcoesLocais(CFG.local_padrao)}</select></label>
        <label>Potência para gravar no coletor (%)<input id="cPot" type="number" min="5" max="100" value="${esc(CFG.potencia_gravacao)}"></label></div>
        <div class="fraco" style="margin-top:8px">O prefixo GS1 é o número da empresa na GS1 Brasil (o começo do EAN, ex.: 789 + código). O número de dígitos define a partição do SGTIN-96.</div></div>
      <div class="card"><h2>Layout da etiqueta (ZPL)<span class="dir"><button id="btPadrao">Voltar ao padrão</button></span></h2>
        <div class="fraco" style="margin-bottom:6px">Campos: {EPC} {DESCRICAO} {SKU} {COR} {TAMANHO} {PRECO} {CODIGO_BARRAS} {GTIN} {OF} {SERIAL} {EMPRESA} {GRUPO}.
          A linha <span class="mono">^RFW,H,,,A^FD{EPC}^FS</span> grava o EPC no chip. Padrão: 100 × 50 mm, 203 dpi.</div>
        <textarea id="cZpl" rows="18" style="width:100%">${esc(CFG.modelo_zpl || CFG.modelo_zpl_padrao)}</textarea></div>
      ${adm ? '<div class="botoes" style="margin-bottom:14px"><button class="p" id="btSalvar">Salvar configurações</button></div>' : '<div class="fraco">Só o administrador altera as configurações.</div>'}
      <div class="card"><h2>Calculadora EPC</h2><div class="filtros"><label>GTIN / EAN<input id="kG" placeholder="7891234567895"></label><label>Série<input id="kS" type="number" value="1"></label>
        <button id="btGerar">Gerar EPC</button><label style="flex:1">ou EPC para decodificar<input id="kE" class="mono"></label><button id="btDec">Decodificar</button></div><div id="kRes" class="mono"></div></div>
      ${adm ? `<div class="card"><h2>Limpar tudo</h2><div class="fraco">Apaga etiquetas, OFs, pedidos, inventários, movimentos e alertas (para recomeçar). A numeração de série dos EPCs continua, para nunca repetir.</div>
        <div class="filtros" style="margin-top:8px"><label class="check"><input type="checkbox" id="lManter" checked> Manter produtos, locais e impressoras</label>
        <button class="perigo" id="btLimpar">Limpar tudo…</button></div></div>` : ""}`;
    $("#btPadrao").onclick = () => $("#cZpl").value = CFG.modelo_zpl_padrao;
    if (adm) $("#btSalvar").onclick = () => tentar(async () => {
      const zpl = $("#cZpl").value.trim() === CFG.modelo_zpl_padrao.trim() ? "" : $("#cZpl").value;
      CFG = {...CFG, ...await put("/api/config", {empresa: $("#cEmp").value, prefixo_gs1_digitos: $("#cPref").value, filtro_epc: $("#cFiltro").value,
        gid_gerente: $("#cGid").value, local_padrao: $("#cLocal").value, potencia_gravacao: $("#cPot").value, modelo_zpl: zpl})};
      avisar("Configurações salvas"); });
    $("#btGerar").onclick = () => tentar(async () => { const d = await get(`/api/epc/gerar?gtin=${encodeURIComponent($("#kG").value)}&serial=${+$("#kS").value || 1}`);
      $("#kRes").innerHTML = `EPC <b>${esc(d.epc)}</b><br>${esc(d.uri)}`; });
    $("#btDec").onclick = () => tentar(async () => { const h = await get("/api/epc/" + encodeURIComponent($("#kE").value.trim())); const d = h.decodificado;
      $("#kRes").innerHTML = `${esc(d.esquema)}${d.gtin ? " · GTIN <b>" + esc(d.gtin) + "</b>" : ""}${d.serial != null ? " · série " + esc(d.serial) : ""}${d.uri ? "<br>" + esc(d.uri) : ""}` +
        (h.etiqueta ? `<br>Cadastrada: ${esc(h.etiqueta.sku)} · ${esc(h.etiqueta.status)}` : ""); });
    if (adm) $("#btLimpar").onclick = () => tentar(async () => {
      const c = prompt("Isso apaga toda a movimentação. Digite APAGAR para confirmar:"); if (c === null) return;
      await post("/api/limpar-tudo", {manter_cadastros: $("#lManter").checked, confirmacao: c}); avisar("Banco limpo"); await carregarBase(); ir("painel"); });
  },
};
