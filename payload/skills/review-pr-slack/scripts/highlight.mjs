// Build-time syntax highlighter for build_html.py (shiki, dual theme).
// stdin:  JSON {"items": [{"lang": "dart", "text": "..."}]}
// stdout: JSON ["<span style=...>...</span>", ...]  (aligned by index; null = not highlighted)
// Each span carries the light color inline plus a --sd custom prop with the dark
// color; build_html.py's CSS swaps to var(--sd) in dark mode.
import { createHighlighter } from 'shiki';

const input = JSON.parse(await new Promise((resolve, reject) => {
  let data = '';
  process.stdin.on('data', c => (data += c));
  process.stdin.on('end', () => resolve(data));
  process.stdin.on('error', reject);
}));

const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const langs = [...new Set(input.items.map(i => i.lang))];
const hl = await createHighlighter({ themes: ['github-light', 'github-dark'], langs: [] });
const loaded = new Set();
for (const l of langs) {
  try { await hl.loadLanguage(l); loaded.add(l); } catch {}
}

const out = input.items.map(({ lang, text }) => {
  if (!loaded.has(lang) || !text.trim()) return null;
  try {
    const { tokens: L } = hl.codeToTokens(text, { lang, theme: 'github-light' });
    const { tokens: D } = hl.codeToTokens(text, { lang, theme: 'github-dark' });
    return L.map((line, li) =>
      line.map((t, ti) => {
        const light = t.color;
        const dark = D[li] && D[li][ti] && D[li][ti].color;
        if (!light && !dark) return esc(t.content);
        const style = `color:${light || 'inherit'}` + (dark ? `;--sd:${dark}` : '');
        return `<span style="${style}">${esc(t.content)}</span>`;
      }).join('')
    ).join('\n');
  } catch { return null; }
});

process.stdout.write(JSON.stringify(out));
