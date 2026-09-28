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
