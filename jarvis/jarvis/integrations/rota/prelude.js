// Ambiente mínimo de navegador para rodar o código da roteirizacao_icaro.html fora do navegador.
// Os elementos da página viram objetos "coringa": aceitam qualquer leitura, escrita ou chamada,
// e os campos de configuração (<input value="...">) devolvem o valor padrão escrito no HTML.
var __INPUTS = {};      // id -> valor padrão do HTML (preenchido pelo Python)
var __CHECKED = {};     // id -> marcado por padrão
var __LISTENERS = {};   // id -> {evento: [funções]}
var __STORE = {};       // localStorage (salvo pelo Python num arquivo)
var __LOGS = [];
var __ELEMS = {};

function __classList() { return { add() {}, remove() {}, toggle() {}, contains() { return false; } }; }
function __elem(id) {
  if (id && __ELEMS[id]) return __ELEMS[id];
  var base = {
    id: id || "",
    value: id && (id in __INPUTS) ? __INPUTS[id] : "",
    checked: id && (id in __CHECKED) ? __CHECKED[id] : false,
    disabled: false, innerHTML: "", textContent: "", innerText: "", style: {}, dataset: {},
    classList: __classList(), children: [], options: [],
    addEventListener(ev, fn) { if (!id) return; (__LISTENERS[id] = __LISTENERS[id] || {}); (__LISTENERS[id][ev] = __LISTENERS[id][ev] || []).push(fn); },
    removeEventListener() {}, appendChild(x) { return x; }, insertBefore(x) { return x; }, remove() {},
    setAttribute() {}, getAttribute() { return null; }, removeAttribute() {},
    querySelector() { return __elem(""); }, querySelectorAll() { return []; },
    closest() { return __elem(""); }, scrollIntoView() {}, focus() {}, click() {}, select() {},
    getContext() { return null; }, getBoundingClientRect() { return { top: 0, left: 0, width: 0, height: 0 }; }
  };
  var el = new Proxy(base, {
    get(t, p) { if (p in t) return t[p]; if (typeof p === "symbol") return undefined; return function () { return __elem(""); }; },
    set(t, p, v) { t[p] = v; return true; }
  });
  if (id) __ELEMS[id] = el;
  return el;
}
var document = {
  readyState: "complete",
  documentElement: __elem("__html"), body: __elem("__body"), head: __elem("__head"),
  querySelector(sel) { var m = /^#([\w-]+)$/.exec(sel || ""); return m ? __elem(m[1]) : __elem(""); },
  querySelectorAll() { return []; },
  getElementById(id) { return __elem(id); },
  createElement() { return __elem(""); },
  addEventListener() {}, removeEventListener() {}
};
var localStorage = {
  getItem(k) { return (k in __STORE) ? __STORE[k] : null; },
  setItem(k, v) { __STORE[k] = String(v); },
  removeItem(k) { delete __STORE[k]; }
};
var window = this; window.document = document; window.localStorage = localStorage;
var navigator = { userAgent: "jarvis", clipboard: { writeText() { return Promise.resolve(); } } };
var location = { href: "", hostname: "jarvis" };
function alert(msg) { __LOGS.push("alert: " + msg); }
function confirm() { return true; }
function prompt() { return null; }
function setTimeout(fn) { return 0; }
function clearTimeout() {}
function setInterval() { return 0; }
function clearInterval() {}
var URL = { createObjectURL() { return ""; }, revokeObjectURL() {} };
var console = { log() {}, warn() {}, error(m) { __LOGS.push("erro: " + m); }, info() {} };
// base64 (o gerador de PDF usa atob/btoa do navegador)
var __B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
function btoa(s) { s = String(s); var out = "";
  for (var i = 0; i < s.length; i += 3) { var a = s.charCodeAt(i) & 255, b = s.charCodeAt(i + 1), c = s.charCodeAt(i + 2);
    out += __B64[a >> 2] + __B64[((a & 3) << 4) | ((b & 255) >> 4)] + (isNaN(b) ? "=" : __B64[((b & 15) << 2) | ((c & 255) >> 6)]) + (isNaN(c) ? "=" : __B64[c & 63]); }
  return out; }
function atob(s) { s = String(s).replace(/[^A-Za-z0-9+/]/g, ""); var out = "", buf = 0, bits = 0;
  for (var i = 0; i < s.length; i++) { buf = (buf << 6) | __B64.indexOf(s[i]); bits += 6; if (bits >= 8) { bits -= 8; out += String.fromCharCode((buf >> bits) & 255); } }
  return out; }
window.atob = atob; window.btoa = btoa;
