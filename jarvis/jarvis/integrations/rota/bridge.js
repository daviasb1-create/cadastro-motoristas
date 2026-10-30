// Ponte entre o JARVIS e o código da ferramenta. Só chama funções que já existem no HTML
// (buildMapping, assign, moveNoteTo, toggleGo, swapDrivers, removeNoteData, restoreNote,
// setReassign, saveDay, loadDay e o botão Exportar); nenhuma regra de rota é reescrita aqui.

// Lê as planilhas como readOneWorkbook/route fazem no navegador (mesmas opções do SheetJS).
function __jLoad(src, files) {
  var allRows = [], hset = new Set(), names = [];
  files.forEach(function (f) {
    var wb = XLSX.read(f.b64, { type: "base64", cellDates: true });
    var ws = wb.Sheets[wb.SheetNames[0]];
    var json = XLSX.utils.sheet_to_json(ws, { defval: "", raw: false });
    var raw = XLSX.utils.sheet_to_json(ws, { defval: "", raw: true });
    var rows = json.map(function (r, i) { return Object.assign({}, r, { __d: raw[i] }); });
    var headers = json.length ? Object.keys(json[0]).filter(function (k) { return k !== "__d"; }) : [];
    allRows = allRows.concat(rows); headers.forEach(function (h) { hset.add(h); }); names.push(f.name);
  });
  if (!allRows.length) return { ok: false, msg: "Planilha(s) sem dados." };
  STATE.files[src] = names.join(", "); STATE.headers[src] = Array.from(hset); STATE.rows[src] = allRows;
  buildMapping();
  return { ok: true, rows: allRows.length };
}

function __jReset() {
  STATE.files = {}; STATE.headers = {}; STATE.rows = {}; STATE.mapping = {}; STATE.result = null;
  REASSIGN = {}; REMOVED = new Set();
}

function __jStatus() { return { ok: !document.getElementById("processBtn").disabled, msg: document.getElementById("mapStatus").textContent }; }

function __jIdx(nome) { return DRIVERS.findIndex(function (d) { return d.motorista === nome; }); }

// Monta a rota (igual ao botão Processar): data, fim de semana/feriado e ausências
function __jAssign(opts) {
  document.getElementById("dataRota").value = opts.data;
  DIA_FDS = !!opts.fds;
  DRIVERS.forEach(function (d) { d.disponivel = (opts.ausentes || []).indexOf(d.motorista) < 0; });
  STATE.result = assign();
  saveDay();
  return __jResult();
}

function __jIso(d) { return d instanceof Date ? d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0") : null; }
function __jNote(r) {
  return { nf: r.nf, cte: r.cte, cliente: r.cliente, destinatario: r.destinatario, telefone: r.telefone, cep: r.cep,
    municipio: r.municipio, bairro: r.bairro, endereco: r.endereco, peso: r.peso, volume: r.volume, qtdVol: r.qtdVol || 0,
    valorFrete: r.valorFrete, prazo: __jIso(r.prazo), regLabel: r.regLabel, agendado: !!r.agendado,
    obrigatoria: !!((r.prazo && STATE.result && r.prazo <= STATE.result.dataRota) || r._prioridade || r.agendado || isWhpBud(r.cliente)),
    motivo: r._reason || r._excMotivo || "", urgente: !!r._urgent };
}
function __jResult() {
  var R = STATE.result; if (!R) return null;
  return {
    data: __jIso(R.dataRota), fds: DIA_FDS, total: R.total, iss: R.iss, hasValor: R.hasValor, limite: R.limite, vermelho: R.vermelho,
    regioes: R.allRegions || [],
    motoristas: DRIVERS.map(function (d, i) { return { idx: i, nome: d.motorista, regiao: d.regiao, veiculo: d.veiculo, cls: d.cls, disponivel: !!d.disponivel }; }),
    manifests: R.manifests.map(function (m) {
      return { idx: DRIVERS.indexOf(m.driver), nome: m.driver.motorista, regiao: m.regiaoDia || m.driver.regiao, veiculo: m.driver.veiculo,
        cls: m.driver.cls, ausente: !!m.absent, notas: m.items.map(__jNote), peso: m.peso, vol: m.vol, qtdVol: m.qtdVol || 0,
        frete: m.valorFrete || 0, custo: m.custo, adicional: m.addonLabel || "", pct: m.pctCusto, faixa: m.band || "",
        recomenda: m.recomenda || "", gargalo: m.gargalo || "", mx: m.mx || 0, maxnf: m.driver.maxnf };
    }),
    fora: R.overflow.map(__jNote),
    foraFilial: (R.redespachoList || []).map(__jNote),
    whpBarrados: (R.barradosList || []).length,
    fdsCnpj: (R.fdsCnpjList || []).length
  };
}

// Ajustes do dia, com as mesmas funções dos botões da ferramenta
function __jMove(nf, idx) { moveNoteTo(nf, idx); saveDay(); return __jResult(); }
function __jRemove(nf) { removeNoteData(nf); saveDay(); return __jResult(); }
function __jRestore(nf) { restoreNote(nf); saveDay(); return __jResult(); }
function __jToggle(idx) { toggleGo(idx); saveDay(); return __jResult(); }
function __jSwap(a, b) { swapDrivers(a, b); saveDay(); return __jResult(); }
function __jReassign(idx, regiao) {
  if (regiao) REASSIGN[idx] = regiao; else delete REASSIGN[idx];
  STATE.result = assign(); saveDay(); return __jResult();
}
function __jRestoreDay() { return loadDay() ? __jResult() : null; }

// Excel: executa o mesmo código do botão "Exportar Excel" e devolve o arquivo em base64
function __jExcel() {
  var out = null, nome = "";
  var orig = XLSX.writeFile;
  XLSX.writeFile = function (wb, fname) { nome = fname; out = XLSX.write(wb, { type: "base64", bookType: "xlsx" }); };
  try { (__LISTENERS.exportBtn.click || [])[0](); } finally { XLSX.writeFile = orig; }
  return { nome: nome, b64: out };
}

// PDF do Circuit: mesmo layout da ferramenta (circuitDoc/circuitFname), um arquivo por motorista
function __jB64(buf) {
  var bytes = new Uint8Array(buf), chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/", out = "";
  for (var i = 0; i < bytes.length; i += 3) {
    var a = bytes[i], b = bytes[i + 1], c = bytes[i + 2];
    out += chars[a >> 2] + chars[((a & 3) << 4) | (b >> 4 || 0)] +
      (i + 1 < bytes.length ? chars[((b & 15) << 2) | (c >> 6 || 0)] : "=") + (i + 2 < bytes.length ? chars[c & 63] : "=");
  }
  return out;
}
function __jCircuit(idx) {
  var R = STATE.result; if (!R) return [];
  var dt = R.dataRota ? R.dataRota.toLocaleDateString("pt-BR") : "";
  return R.manifests.filter(function (m) { return !m.absent && m.items && m.items.length && (idx == null || DRIVERS.indexOf(m.driver) === idx); })
    .map(function (m) { var doc = circuitDoc(m, R); return { nome: circuitFname(m, dt), motorista: m.driver.motorista, b64: __jB64(doc.output("arraybuffer")) }; });
}
