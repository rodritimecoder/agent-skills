// render.js — offline Chromium renderer for kem-ocr (reference-matching style).
// Reads a JSON spec from stdin, writes a PNG, prints a JSON result line.
// Spec: {mode, text, out, width, scale}
//   mode: "text" (markdown), "formula" (LaTeX), "html" (raw HTML, e.g. OTSL->HTML)
//   text: candidate text
//   out: output png path
//   width: render target width (default 900; should be original image width)
//   scale: device scale factor (default 1.0; formulas use 3.0)
const fs = require('fs');
const { execFileSync } = require('child_process');

const KATEX = '/home/rodri/build/ROCmFPX-src/tools/server/webui/node_modules/katex/dist';
const MARKED = '/home/rodri/.pi/agent/install/releases/1.3.0/node_modules/marked';
const CHROME = '/home/rodri/.cache/ms-playwright/chromium-1247/chrome-linux64/chrome';

const marked = require(MARKED);

let spec = '';
process.stdin.on('data', d => spec += d);
process.stdin.on('end', () => {
  try {
    const s = JSON.parse(spec);
    const mode = s.mode || 'text';
    const W = s.width || 900;
    const scale = s.scale || 1.0;
    const out = s.out;
    const text = (s.text || '').toString();

    const CSS = `body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
      "Microsoft YaHei", SimSun, sans-serif; padding: 0; margin: 0; background: #fff;
      font-size: 18px; line-height: 2.0; }
    h1 { font-size: 1.8em; margin: 0.8em 0 0.4em; }
    h2 { font-size: 1.5em; margin: 0.7em 0 0.4em; }
    h3 { font-size: 1.3em; margin: 0.5em 0 0.3em; }
    h4, h5, h6 { font-size: 1.1em; margin: 0.4em 0 0.3em; }
    table { border-collapse: collapse; margin: 0.6em 0; }
    th, td { border: 1px solid #ddd; padding: 6px 10px; }
    th { background-color: #f2f2f2; }
    pre { background: #f5f5f5; padding: 12px; border-radius: 4px; overflow-x: auto; }
    code { background: #f0f0f0; padding: 2px 4px; border-radius: 3px; font-size: 0.9em; }
    pre code { background: none; padding: 0; }
    blockquote { border-left: 4px solid #ddd; margin: 0.6em 0; padding: 0.4em 1em; color: #555; }
    img { max-width: 100%; }`;

    let content;
    if (mode === 'formula') {
      let expr = text.trim();
      const delims = [['$$','$$'], ['\\[','\\]'], ['\\(','\\)']];
      for (const [l, r] of delims) {
        if (expr.startsWith(l) && expr.endsWith(r) && expr.length > l.length + r.length) {
          expr = expr.slice(l.length, expr.length - r.length).trim();
          break;
        }
      }
      if (expr.startsWith('$') && expr.endsWith('$') && !expr.startsWith('$$')) {
        expr = expr.slice(1, -1).trim();
      }
      const esc = expr.replace(/\\/g, '\\\\').replace(/`/g, '\\`').replace(/\$/g, '\\$');
      content = `<div id="out"></div><script>katex.render(\`${esc}\`, document.getElementById('out'), {displayMode:true,throwOnError:false});</script>`;
    } else if (mode === 'html') {
      content = text;
    } else {
      content = marked.parse(text, { gfm: true, breaks: true });
    }

    const html = `<!DOCTYPE html><html><head><meta charset="UTF-8">
<link rel="stylesheet" href="file://${KATEX}/katex.min.css">
${mode === 'formula' ? `<script src="file://${KATEX}/katex.min.js"></script>` : ''}
<style>${CSS}</style>
</head><body><div id="capture-area">${content}</div></body></html>`;

    const htmlPath = out + '.html';
    fs.writeFileSync(htmlPath, html);
    const args = [
      '--headless=new', '--disable-gpu', '--no-sandbox',
      `--force-device-scale-factor=${scale}`,
      `--screenshot=${out}`, `--window-size=${W},1200`,
      `file://${htmlPath}`
    ];
    execFileSync(CHROME, args, { stdio: 'pipe', timeout: 60000 });
    fs.unlinkSync(htmlPath);
    console.log(JSON.stringify({ ok: true, path: out, mode, width: W, scale }));
  } catch (e) {
    console.log(JSON.stringify({ ok: false, error: String(e) }));
    process.exit(1);
  }
});
