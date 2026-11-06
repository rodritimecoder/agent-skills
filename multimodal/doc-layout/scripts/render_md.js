// render_md.js — Markdown -> standalone HTML with typeset math (KaTeX).
// Usage: node render_md.js IN.md OUT.html [--cdn]
// Math spans are masked before marked runs: `_{o}` inside \( ... \) would
// otherwise be turned into <em> and corrupt the LaTeX.
const fs = require('fs');
const path = require('path');

const MARKED = process.env.MARKED_MODULE ||
  '/home/rodri/.pi/agent/install/releases/1.3.0/node_modules/marked';
const KATEX = process.env.KATEX_DIST ||
  '/home/rodri/build/ROCmFPX-src/tools/server/webui/node_modules/katex/dist';

const { marked } = require(MARKED);

const [inPath, outPath, ...flags] = process.argv.slice(2);
if (!inPath || !outPath) {
  console.error('usage: render_md.js IN.md OUT.html [--cdn]');
  process.exit(2);
}
const useCdn = flags.includes('--cdn');
const md = fs.readFileSync(inPath, 'utf8');

// 1. mask math spans so markdown emphasis/underscores cannot touch them
const MATH_RE = /(\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\))/g;
const store = [];
const masked = md.replace(MATH_RE, (m) => `@@MATH${store.push(m) - 1}@@`);

// 2. markdown -> html, then restore the original delimiters
let body = marked.parse(masked);
body = body.replace(/@@MATH(\d+)@@/g, (_, i) => store[Number(i)] || '');

const katexBase = useCdn
  ? 'https://cdn.jsdelivr.net/npm/katex@0.16.11/dist'
  : `file://${KATEX}`;
const cssHref = useCdn ? `${katexBase}/katex.min.css`
  : `file://${KATEX}/katex.min.css`;

const css = `
  :root { color-scheme: light dark; }
  body { max-width: 840px; margin: 2.2rem auto; padding: 0 1.4rem;
         font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
         line-height: 1.65; font-size: 17px; color: #1b1b1b; background: #fff; }
  h1, h2, h3, h4 { line-height: 1.25; margin: 1.4em 0 .5em; }
  h2 { border-bottom: 1px solid #e5e5e5; padding-bottom: .25em; }
  img { max-width: 100%; height: auto; display: block; margin: 1em auto; }
  table { border-collapse: collapse; margin: 1em 0; }
  th, td { border: 1px solid #ddd; padding: 6px 10px; }
  th { background: #f5f5f5; }
  blockquote { border-left: 4px solid #e0e0e0; margin: 1em 0;
               padding-left: 1em; color: #555; }
  code { background: #f2f2f2; padding: 1px 4px; border-radius: 3px; }
  hr { border: 0; border-top: 1px solid #e5e5e5; margin: 2em 0; }
  .katex-display { overflow-x: auto; overflow-y: hidden; padding: .2em 0; }
  @media print { body { max-width: none; margin: 0; } }
`;

const html = `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${path.basename(inPath)}</title>
<base href="file://${path.dirname(path.resolve(inPath))}/">
${useCdn ? `<link rel="stylesheet" href="${cssHref}">` : `<link rel="stylesheet" href="file://${KATEX}/katex.min.css">`}
<style>${css}</style>
</head><body>
<article id="doc">${body}</article>
<script src="${useCdn ? `${katexBase}/katex.min.js` : `file://${KATEX}/katex.min.js`}"></script>
<script src="${useCdn ? `${katexBase}/contrib/auto-render.min.js` : `file://${KATEX}/contrib/auto-render.min.js`}"></script>
<script>
  renderMathInElement(document.getElementById('doc'), {
    delimiters: [
      { left: '$$', right: '$$', display: true },
      { left: '\\\\[', right: '\\\\]', display: true },
      { left: '\\\\(', right: '\\\\)', display: false }
    ],
    throwOnError: false
  });
</script>
</body></html>`;

fs.writeFileSync(outPath, html);
console.log(JSON.stringify({ ok: true, out: outPath, math_spans: store.length, cdn: useCdn }));
