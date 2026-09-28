// TagStock — base da tela do PC: API com login, avisos, diálogo, tabelas, leitor e navegação.
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = v => v == null ? "" : String(v).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const num = n => (n ?? 0).toLocaleString("pt-BR");
const moeda = n => (n ?? 0).toLocaleString("pt-BR", {style: "currency", currency: "BRL"});
const dataBR = s => s ? s.slice(8, 10) + "/" + s.slice(5, 7) + "/" + s.slice(0, 4) + (s.length > 10 ? " " + s.slice(11, 16) : "") : "";
const variante = t => [t.cor, t.tamanho].filter(Boolean).join(" / ");
let token = localStorage.getItem("tagstock_token");
let usuario = null;
let CFG = {}, LOCAIS = [], MOTIVOS = [];

async function api(metodo, url, corpo) {
  const r = await fetch(url, {method: metodo, headers: {"Content-Type": "application/json", "X-Token": token || "", "X-Origem": "PC"},
                              body: corpo === undefined ? undefined : JSON.stringify(corpo)});
  if (r.status === 401) { mostrarLogin(); throw new Error("Faça o login"); }
  const dados = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(dados.detail || ("Erro " + r.status));
  return dados;
}
const get = u => api("GET", u), post = (u, b = {}) => api("POST", u, b), put = (u, b) => api("PUT", u, b), del = u => api("DELETE", u);
const comToken = u => u + (u.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(token);
function baixar(url) { const a = document.createElement("a"); a.href = comToken(url); a.download = ""; document.body.append(a); a.click(); a.remove(); }

function avisar(texto, tipo = "ok", ms = 3800) {
  const d = document.createElement("div");
  d.className = "aviso " + tipo; d.textContent = texto;
  $("#avisos").append(d); setTimeout(() => d.remove(), ms);
}
async function tentar(fn) { try { return await fn(); } catch (e) { avisar(e.message, "erro", 6000); } }

// Diálogo: botoes = [[rótulo, classe, função async], ...]. aoFechar: chamado quando o diálogo fecha.
let dlgFechou = null;
function abrirDlg(titulo, html, botoes = [], opts = {}) {
  if ($("#dlg").open) { const f = dlgFechou; dlgFechou = null; f?.(); }
  $("#dlgTitulo").textContent = titulo; $("#dlgConteudo").innerHTML = html;
  const pe = $("#dlgPe"); pe.innerHTML = "";
  for (const [rotulo, classe, acao] of botoes) {
    const b = document.createElement("button"); b.textContent = rotulo; b.className = classe || "";
    b.onclick = async () => { b.disabled = true; try { await tentar(acao); } finally { b.disabled = false; } };
    pe.append(b);
  }
  pe.classList.toggle("oculto", !botoes.length);
  $("#dlg").classList.toggle("largo", !!opts.largo);
  dlgFechou = opts.aoFechar || null;
  if (!$("#dlg").open) $("#dlg").showModal();
}
function fecharDlg() { $("#dlg").close(); }
$("#dlg").addEventListener("close", () => { const f = dlgFechou; dlgFechou = null; f?.(); Leitor.saida = paginaSaida; });

function opcoesLocais(sel, vazio) {
  return (vazio ? `<option value="">${esc(vazio)}</option>` : "") +
    LOCAIS.filter(l => l.ativo).map(l => `<option value="${l.id}" ${String(sel) === String(l.id) ? "selected" : ""}>${esc(l.codigo)} · ${esc(l.nome)}</option>`).join("");
}
function tabela(colunas, linhas, opts = {}) {
  if (!linhas.length) return `<div class="vazio">${opts.vazio || "Nada para mostrar"}</div>`;
  const cab = colunas.map(c => `<th class="${c.n ? "n" : ""}">${c.t}</th>`).join("");
  const corpo = linhas.map((l, i) => `<tr class="${opts.clic ? "clic" : ""}" data-i="${i}">` +
    colunas.map(c => `<td class="${c.n ? "n" : ""} ${c.cl || ""}">${c.f ? c.f(l, i) : esc(l[c.k])}</td>`).join("") + "</tr>").join("");
  return `<div class="tabela" style="${opts.alt ? "max-height:" + opts.alt : ""}"><table><thead><tr>${cab}</tr></thead><tbody>${corpo}</tbody></table></div>`;
}
// Lista com caixas de seleção: uma por linha + "selecionar todos" no cabeçalho, contador e ações em lote.
//   el: onde desenhar · colunas/linhas: como em tabela() · opts:
//     chave: l => id da linha (padrão l.id) · acoes: [[rótulo, classe, async selecionadas => {}], ...]
//     marcavel: l => pode marcar? · aoClicar: l => {} (clique na linha) · nome: arquivo do CSV
// A seleção fica guardada em el._sel e sobrevive quando a lista é redesenhada (ex.: atualização a cada 3 s).
function listaSel(el, colunas, linhas, opts = {}) {
  if (!el) return;
  const chave = l => String((opts.chave || (x => x.id))(l));
  const marcavel = opts.marcavel || (() => true);
  const sel = opts.sel || el._sel || (el._sel = new Set());   // opts.sel: seleção guardada pela tela (página redesenhada inteira)
  const existentes = new Set(linhas.filter(marcavel).map(chave));
  [...sel].forEach(k => existentes.has(k) || sel.delete(k));
  const acoes = (opts.acoes || []).filter(Boolean);
  const cols = [{t: '<input type="checkbox" class="selTodos" title="Selecionar todos">',
                 f: l => marcavel(l) ? `<input type="checkbox" class="selLinha" data-k="${esc(chave(l))}" ${sel.has(chave(l)) ? "checked" : ""}>` : ""},
                ...colunas];
  el.innerHTML = (linhas.length ? `<div class="barra-sel"><span class="nsel fraco"></span>
      ${acoes.map((a, i) => `<button class="peq ${a[1] || ""}" data-acao-lote="${i}">${a[0]}</button>`).join("")}
      <button class="peq" data-csv-lote>⬇ CSV das selecionadas</button></div>` : "") + tabela(cols, linhas, {...opts, clic: opts.clic ?? !!opts.aoClicar});
  const escolhidas = () => linhas.filter(l => marcavel(l) && sel.has(chave(l)));
  const atualizar = () => {
    const n = escolhidas().length, total = existentes.size;
    const nsel = $(".nsel", el); if (nsel) nsel.textContent = n ? `${n} selecionada(s)` : "Nenhuma selecionada";
    $$("[data-acao-lote],[data-csv-lote]", el).forEach(b => b.disabled = !n);
    const todos = $(".selTodos", el);
    if (todos) { todos.checked = n > 0 && n === total; todos.indeterminate = n > 0 && n < total; todos.disabled = !total; }
  };
  $$(".selLinha", el).forEach(c => c.onchange = () => { c.checked ? sel.add(c.dataset.k) : sel.delete(c.dataset.k); atualizar(); });
  const todos = $(".selTodos", el);
  if (todos) todos.onchange = () => {
    $$(".selLinha", el).forEach(c => { c.checked = todos.checked; todos.checked ? sel.add(c.dataset.k) : sel.delete(c.dataset.k); });
    linhas.filter(marcavel).forEach(l => todos.checked ? sel.add(chave(l)) : sel.delete(chave(l)));   // inclui as que não couberam na tela
    atualizar();
  };
  $$("[data-acao-lote]", el).forEach(b => b.onclick = async () => {
    const lista = escolhidas(); if (!lista.length) return;
    b.disabled = true;
    try { await tentar(() => acoes[+b.dataset.acaoLote][2](lista)); } finally { atualizar(); }
  });
  const csv = $("[data-csv-lote]", el);
  if (csv) csv.onclick = () => csvDasLinhas(opts.nome || "selecionadas", colunas, escolhidas());
  if (opts.aoClicar) ligarLinhas(el, linhas, opts.aoClicar);
  el.limparSelecao = () => { sel.clear(); atualizar(); };
  atualizar();
}
// Pergunta rápida (funciona por cima de outro diálogo). opcoes: [[valor, rótulo], ...] = lista; null = campo de texto; false = só confirmar.
// Devolve o valor escolhido, ou null se cancelou.
function escolher(titulo, texto, rotulo, opcoes, padrao = "") {
  return new Promise(ok => {
    const d = $("#dlgEscolha");
    $("#escTitulo").textContent = titulo; $("#escTexto").innerHTML = texto || ""; $("#escRotulo").textContent = rotulo || "";
    const texto_ = opcoes === null;
    $("#escSelect").classList.toggle("oculto", !opcoes); $("#escInput").classList.toggle("oculto", !texto_);
    $("#escRotulo").classList.toggle("oculto", !rotulo);
    if (opcoes) $("#escSelect").innerHTML = opcoes.map(([v, r]) => `<option value="${esc(v)}" ${String(v) === String(padrao) ? "selected" : ""}>${esc(r)}</option>`).join("");
    else if (texto_) $("#escInput").value = padrao;
    let resposta = null;
    $("#escSim").onclick = e => { e.preventDefault(); resposta = opcoes ? $("#escSelect").value : texto_ ? $("#escInput").value : "ok"; d.close(); };
    $("#escNao").onclick = () => d.close();
    $("#formEscolha").onsubmit = e => { e.preventDefault(); $("#escSim").click(); };
    d.onclose = () => ok(resposta);
    d.showModal();
    (opcoes ? $("#escSelect") : texto_ ? $("#escInput") : $("#escSim")).focus();
  });
}
const confirmar = (titulo, texto) => escolher(titulo, texto, "", false).then(v => v !== null);
const opcoesDeLocais = () => LOCAIS.filter(l => l.ativo).map(l => [l.id, `${l.codigo} · ${l.nome}`]);

// Ações em lote para qualquer lista de etiquetas (linhas com .epc). depois(): recarrega a tela.
function acoesEtiquetas(depois, quais = ["entrada", "baixa", "estorno", "transferencia", "cancelar"]) {
  const epcs = l => l.map(t => t.epc);
  const resultado = async (r, nome) => {
    avisar(`${nome}: ${r.quantidade} ok` + (r.erros.length ? `\n${r.erros.length} recusada(s): ` +
      [...new Set(r.erros.map(x => x.motivo))].slice(0, 3).join("; ") : ""), r.erros.length ? "erro" : "ok", r.erros.length ? 8000 : 3800);
    await depois?.();
  };
  const A = {
    entrada: ["📥 Dar entrada", "", async l => {
      const lid = await escolher("Entrada", `${l.length} etiqueta(s) emitida(s) entram no estoque.`, "Local", opcoesDeLocais(), CFG.local_padrao);
      if (lid !== null) await resultado(await post("/api/etiquetas/entrada", {epcs: epcs(l), local_id: +lid}), "Entrada"); }],
    baixa: ["📤 Baixar", "perigo", async l => {
      const m = await escolher("Baixar", `${l.length} peça(s) saem do estoque.`, "Motivo", MOTIVOS.map(x => [x, x]), "VENDA");
      if (m !== null) await resultado(await post("/api/etiquetas/baixa", {epcs: epcs(l), motivo: m}), "Baixa"); }],
    estorno: ["↩ Estornar baixa", "", async l => {
      if (await confirmar("Estornar", `${l.length} peça(s) baixada(s) voltam ao estoque.`))
        await resultado(await post("/api/etiquetas/estorno", {epcs: epcs(l)}), "Estorno"); }],
    transferencia: ["🔁 Transferir", "", async l => {
      const lid = await escolher("Transferir", `${l.length} peça(s).`, "Para o local", opcoesDeLocais());
      if (lid !== null) await resultado(await post("/api/etiquetas/transferencia", {epcs: epcs(l), destino_id: +lid}), "Transferência"); }],
    cancelar: ["🚫 Cancelar etiquetas", "perigo", async l => {
      const m = await escolher("Cancelar etiquetas", `${l.length} etiqueta(s) ficam inutilizadas (as que estão no estoque saem dele).`, "Motivo", null, "");
      if (m !== null) await resultado(await post("/api/etiquetas/cancelar", {epcs: epcs(l), motivo: m || null}), "Cancelar"); }],
  };
  return quais.map(q => A[q]);
}
// Faz uma ação para cada item selecionado (rotas de um item só) e resume o resultado.
async function emLote(lista, nome, fazer, depois) {
  let ok = 0; const erros = [];
  for (const x of lista) { try { await fazer(x); ok++; } catch (e) { erros.push(e.message); } }
  avisar(`${nome}: ${ok} ok` + (erros.length ? `\n${erros.length} com erro: ${[...new Set(erros)].slice(0, 3).join("; ")}` : ""), erros.length ? "erro" : "ok", erros.length ? 8000 : 3800);
  await depois?.();
}
function textoCelula(c, l) {
  if (c.csv) return c.csv(l);
  if (c.k) return l[c.k] ?? "";
  if (!c.f) return "";
  const d = document.createElement("div"); d.innerHTML = c.f(l); return d.textContent.trim();
}
function csvDasLinhas(nome, colunas, linhas) {
  const cols = colunas.filter(c => c.t && !/<input/.test(c.t));
  const q = v => { const s = String(v ?? "").replace(/\s+/g, " ").trim(); return /[;"\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const texto = "﻿" + [cols.map(c => q(c.t.replace(/<[^>]+>/g, ""))).join(";"), ...linhas.map(l => cols.map(c => q(textoCelula(c, l))).join(";"))].join("\r\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([texto], {type: "text/csv;charset=utf-8"}));
  a.download = nome + ".csv"; document.body.append(a); a.click(); a.remove();
}
function ligarLinhas(el, linhas, fn) {
  $$("tr.clic", el).forEach(tr => tr.onclick = e => { if (e.target.closest("button,input,a,select")) return; fn(linhas[+tr.dataset.i]); });
}
function progresso(feito, total) {
  const p = total ? Math.min(100, Math.round(100 * feito / total)) : 0;
  return `<div class="progresso ${feito > total ? "passou" : feito === total && total ? "cheio" : ""}"><span style="width:${p}%"></span></div>`;
}
const NOMES_SITUACAO = {ESTOQUE: "em estoque", EMITIDA: "emitida", BAIXADA: "baixada", CANCELADA: "cancelada", OK: "ok", FALTA: "falta",
  SOBRA: "sobra", OUTRO_LOCAL: "outro local", DESCONHECIDA: "desconhecida", ABERTA: "aberta", ABERTO: "aberto",
  FINALIZADA: "finalizada", FINALIZADO: "finalizado", CANCELADO: "cancelado"};
const selo = s => s ? `<span class="selo ${esc(s)}">${esc(NOMES_SITUACAO[s] || s.toLowerCase())}</span>` : `<span class="selo alerta">não cadastrada</span>`;
function descProduto(t) {
  if (!t.sku) return t.sugerido ? `<span class="fraco">GTIN do EPC = ${esc(t.sugerido.sku)} ${esc(t.sugerido.descricao)}</span>`
                                : `<span class="fraco">${esc(t.esquema || "")}</span>`;
  return `<b>${esc(t.sku)}</b> ${esc(t.descricao)} <span class="fraco">${esc(variante(t))}</span>`;
}

// ============================================================ login
function mostrarLogin() {
  token = null; localStorage.removeItem("tagstock_token");
  $("#telaLogin").classList.remove("oculto");
  setTimeout(() => $("#formLogin [name=login]").focus(), 50);
}
$("#formLogin").onsubmit = async e => {
  e.preventDefault();
  const f = new FormData(e.target);
  const r = await fetch("/api/login", {method: "POST", headers: {"Content-Type": "application/json"},
                                        body: JSON.stringify({login: f.get("login"), senha: f.get("senha")})});
  const d = await r.json();
  if (!r.ok) { $("#erroLogin").textContent = d.detail; return; }
  token = d.token;
  localStorage.setItem("tagstock_token", token);
  $("#telaLogin").classList.add("oculto"); $("#erroLogin").textContent = "";
  e.target.reset();
  iniciar();
};
$("#sair").onclick = async () => { await post("/api/logout").catch(() => {}); mostrarLogin(); };

// ============================================================ leitor
// O leitor é o coletor aberto na tela "Estação PC" (o PC manda ler/parar pela rede) ou um
// leitor USB que "digita" o EPC + Enter no campo de captura. Cada tela diz para onde vão
// as etiquetas novas: Leitor.saida = epcs => {...}
const Leitor = {
  saida: null, vistas: new Set(), eventos: 0, online: false, lendo: false, aoEvento: null, ultimo: null,
  async comando(acao, extra = {}) { return post("/api/remoto/comando", {acao, potencia: +$("#potencia").value, ...extra}); },
  async ler() { this.vistas.clear(); await this.comando("limpar"); await this.comando("ler"); },
  async parar() { await this.comando("parar"); },
  // Ao trocar de tela, o que o coletor já tinha lido não vai para a tela nova (só leituras novas)
  esquecer() { this.vistas = new Set((this.ultimo?.leituras || []).map(l => l.epc)); },
  entregar(epcs) {
    const novas = epcs.map(e => (e || "").trim().toUpperCase()).filter(e => e && !this.vistas.has(e));
    novas.forEach(e => this.vistas.add(e));
    if (novas.length && this.saida) this.saida(novas);
    else if (novas.length && !this.saida) avisar("Esta tela não usa leituras RFID", "info");
  },
  async ciclo() {
    if (!token) return;
    try {
      const e = await get("/api/remoto/estado?eventos_apos=" + this.eventos);
      this.online = e.online; this.lendo = e.lendo; this.ultimo = e;
      $("#pontoLeitor").className = "ponto" + (e.lendo ? " lendo" : e.online ? " on" : "");
      $("#textoLeitor").textContent = e.online ? (e.lendo ? "Lendo… " + e.leituras.length + " etiqueta(s)" : "Coletor pronto" + (e.dispositivo ? " · " + e.dispositivo : ""))
                                               : "Coletor desconectado";
      $("#btLer").disabled = !e.online || e.lendo; $("#btParar").disabled = !e.online || !e.lendo;
      for (const ev of e.eventos) { this.eventos = Math.max(this.eventos, ev.id); this.aoEvento?.(ev); }
      if (e.leituras.length && this.saida) this.entregar(e.leituras.map(l => l.epc));
      estacaoAtualizar?.(e);
    } catch (x) {}
  },
};
let paginaSaida = null, estacaoAtualizar = null;
$("#btLer").onclick = () => tentar(() => Leitor.ler());
$("#btParar").onclick = () => tentar(() => Leitor.parar());

function campoCaptura(id, dica = "Leitor USB: leia aqui — ou cole/digite EPCs e tecle Enter") {
  return `<div class="captura"><input id="${id}" placeholder="${esc(dica)}" autocomplete="off">` +
         `<button onclick="enviarCaptura('${id}')">Enviar</button></div>`;
}
function enviarCaptura(id) { const el = $("#" + id); Leitor.entregar(el.value.split(/[\s,;]+/)); el.value = ""; el.focus(); }
document.addEventListener("keydown", e => {
  if (e.key === "Enter" && e.target.matches(".captura input")) { e.preventDefault(); enviarCaptura(e.target.id); }
});

// ============================================================ navegação
const PAGINAS = {};
let intervaloPagina = null;
function ir(p) { if (location.hash === "#" + p) abrir(); else location.hash = p; }
async function abrir() {
  const [p, arg] = (location.hash.slice(1) || "painel").split("/");
  const pag = PAGINAS[p] || PAGINAS.painel;
  clearInterval(intervaloPagina); intervaloPagina = null;
  if ($("#dlg").open) $("#dlg").close();
  Leitor.saida = paginaSaida = null; Leitor.aoEvento = null; estacaoAtualizar = null; Leitor.esquecer();
  $$("nav a").forEach(a => a.classList.toggle("ativo", a.dataset.p === (PAGINAS[p] ? p : "painel")));
  $("#titulo").textContent = pag.titulo;
  $("#main").innerHTML = "";
  await tentar(() => pag.abrir($("#main"), arg));
}
function definirSaida(fn) { Leitor.saida = paginaSaida = fn; }
$$("nav a").forEach(a => a.onclick = () => ir(a.dataset.p));
window.addEventListener("hashchange", abrir);
function aCada(ms, fn) { clearInterval(intervaloPagina); intervaloPagina = setInterval(() => { if (!$("#dlg").open) fn(); }, ms); }

async function carregarBase() {
  [CFG, LOCAIS] = await Promise.all([get("/api/config"), get("/api/locais")]);
  const st = await (await fetch("/api/status")).json();
  MOTIVOS = st.motivos;
  $("#enderecoColetor").innerHTML = "📱 Coletor: <b>" + esc(st.coletor) + "</b>";
}
async function atualizarBadge() {
  if (!token) return;
  try { const a = await get("/api/alertas"); $("#badgeAlertas").textContent = a.length || ""; } catch (e) {}
}
let iniciado = false;
async function iniciar() {
  if (!token) return mostrarLogin();
  try { usuario = await get("/api/eu"); } catch (e) { return; }
  $("#quem").textContent = "👤 " + usuario.nome + " (" + usuario.perfil.toLowerCase() + ")";
  $$(".so-admin").forEach(el => el.classList.toggle("oculto", usuario.perfil !== "ADMIN"));
  await carregarBase();
  if (!iniciado) {
    iniciado = true;
    setInterval(atualizarBadge, 10000);
    setInterval(() => Leitor.ciclo(), 700);
  }
  atualizarBadge();
  abrir();
}
