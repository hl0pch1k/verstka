// Статичный снимок доски .dc.html: исполняет логику (renderVals) с подменой state и раскрывает
// sc-if / sc-for / {{ }} — для скриншота в headless Chrome. Анимации не проигрываются.
// node render_dc.js project/V2.dc.html '{"sect":"hist"}' out.html
const fs = require('fs');
const [file, stateJson = '{}', out = 'out.html'] = process.argv.slice(2);
const src = fs.readFileSync(file, 'utf8');
const markup = src.match(/<x-dc>([\s\S]*)<\/x-dc>/)[1];
const js = src.match(/<script type="text\/x-dc"[^>]*>([\s\S]*?)<\/script>/)[1];
const head = (src.match(/<head>([\s\S]*?)<\/head>/) || ['', ''])[1].replace(/<script[\s\S]*?<\/script>/g, '');
const propsM = src.match(/data-props='([^']*)'/);
const schema = propsM ? JSON.parse(propsM[1].replace(/&quot;/g, '"')) : {};
const props = { frozen: true };
for (const [k, v] of Object.entries(schema)) if (k[0] !== '$' && k !== 'frozen') props[k] = v && typeof v === 'object' && 'default' in v ? v.default : v;

class DCLogic {
  constructor(p) { this.props = p || {}; this.state = {}; }
  setState(u) { Object.assign(this.state, typeof u === 'function' ? u(this.state) : u); }
}
const Component = new Function('DCLogic', 'setTimeout', 'setInterval', js + '\nreturn Component;')(
  DCLogic, () => 0, () => 0);
const c = new Component(props);
Object.assign(c.state, JSON.parse(stateJson));
const vals = c.renderVals();

const get = (ctx, path) => path.trim().split('.').reduce((o, k) => (o == null ? o : o[k]), ctx);
const fill = (s, ctx) => s.replace(/\{\{([^}]*)\}\}/g, (_, p) => {
  const v = get(ctx, p);
  return v == null || typeof v === 'function' || v === false ? '' : String(v);
});

// разбор на дерево по тегам sc-if / sc-for
function parse(s) {
  const re = /<(\/?)sc-(if|for)\b([^>]*)>/g;
  const root = { kids: [] }; const stack = [root]; let last = 0, m;
  while ((m = re.exec(s))) {
    stack[stack.length - 1].kids.push(s.slice(last, m.index));
    last = re.lastIndex;
    if (m[1]) { stack.pop(); continue; }
    const node = { type: m[2], attrs: m[3], kids: [] };
    stack[stack.length - 1].kids.push(node); stack.push(node);
  }
  root.kids.push(s.slice(last));
  return root;
}
function render(node, ctx) {
  return node.kids.map((k) => {
    if (typeof k === 'string') return fill(k, ctx);
    const attr = (n) => (k.attrs.match(new RegExp(n + '="\\{\\{([^}]*)\\}\\}"')) || [])[1];
    if (k.type === 'if') return get(ctx, attr('value')) ? render(k, ctx) : '';
    const list = get(ctx, attr('list')) || [];
    const as = (k.attrs.match(/ as="(\w+)"/) || [])[1];
    return list.map((it) => render(k, Object.assign(Object.create(ctx), { [as]: it }))).join('');
  }).join('');
}
const body = render(parse(markup), vals).replace(/<helmet>|<\/helmet>/g, '');
fs.writeFileSync(out, '<!doctype html><html><head><meta charset="utf-8">' + head +
  '</head><body style="margin:0">' + body + '</body></html>');
console.log('ok', out);
