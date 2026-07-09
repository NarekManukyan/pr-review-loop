#!/usr/bin/env python3
"""Build GitHub-style HTML review report.

Run from a working dir containing:
  findings.json  - list of findings {mr,file,line,severity,reviewer,category,title,body,snippet,id[,plusone]}
                   plus per-MR summaries {mr,reviewer,summary}
  meta.json      - {"title": str, "date": str, "order": [mr,...],
                    "<mr>": {title,author,source,target,state,url,verdict,fix_prompt}}
  mr<N>.diff     - unified diff per MR (generated files pre-excluded)
Writes mr-review.html to the same dir.
"""
import json, html, re, sys, os, subprocess

BASE = os.getcwd()
SKILL_SCRIPTS = os.path.dirname(os.path.abspath(__file__))
findings = json.load(open(f'{BASE}/findings.json'))
meta = json.load(open(f'{BASE}/meta.json'))

# (lang, text) -> highlighted HTML; populated by bake_highlighting() below.
HL = {}
def hl_code(lang, text):
    """Return baked shiki HTML for a code chunk, or escaped plain text."""
    return HL.get((lang, text)) or esc(text)

SEV_COLORS = {'P0': ('#cf222e', '#FFEBE9', 'P0 · Blocker'),
              'P1': ('#bc4c00', '#fff1e5', 'P1 · Should fix'),
              'P2': ('#9a6700', '#fff8c5', 'P2 · Nice to fix')}
REV_COLORS = {'A': '#8250df', 'B': '#0969da', 'C': '#1a7f37', 'D': '#cf222e',
              'panel': '#57606a'}
REV_NAMES = {'A': 'Reviewer A · Architecture & Patterns',
             'B': 'Reviewer B · Correctness & Edge Cases',
             'C': 'Reviewer C · Performance & Code Quality',
             'D': 'Reviewer D · Build & Analyze',
             'panel': 'Panel review'}

def rev_color(r):
    return REV_COLORS.get(r, '#57606a')

def rev_name(r):
    return REV_NAMES.get(r, f'Reviewer {r}')

def rev_avatar(r):
    # single-letter reviewers show the letter; multi-char keys (e.g. "panel") show a compact tag
    return r if len(r) == 1 else 'R'

def build_badge(m, short=False):
    """Render the Build & Analyze result from meta['<mr>']['build']."""
    b = m.get('build')
    if not b:
        return ''
    if b.get('compiles') is None:
        return "<span class='bchip bskip'>build skipped</span>"
    if b.get('compiles'):
        w = b.get('analyzer_warnings', 0)
        label = 'build ✅' if short else f"build ✅ · {b.get('analyzer_errors',0)} errors · {w} warnings"
        return f"<span class='bchip bok'>{label}</span>"
    e = b.get('analyzer_errors', '?')
    return f"<span class='bchip bfail'>build ❌ · {e} errors</span>"

def esc(s): return html.escape(str(s or ''))

def md(s):
    """Minimal inline markdown for comment text: `code` and **bold**.

    Single-asterisk italic is deliberately unsupported — reviewer text is full
    of glob patterns like *_bloc.dart that would mangle.
    """
    parts = re.split(r'(`[^`\n]+`)', str(s or ''))
    out = []
    for p in parts:
        if len(p) > 2 and p.startswith('`') and p.endswith('`'):
            out.append(f'<code>{html.escape(p[1:-1])}</code>')
        else:
            e = html.escape(p)
            e = re.sub(r'\*\*([^*\n]+)\*\*', r'<b>\1</b>', e)
            out.append(e)
    return ''.join(out)

def parse_diff(difftext):
    """Return {path: [(sign, old_ln, new_ln, text)]}"""
    files = {}
    cur = None
    old_ln = new_ln = 0
    for line in difftext.split('\n'):
        if line.startswith('+++ b/'):
            cur = line[6:]
            files[cur] = []
        elif line.startswith('--- '):
            continue
        elif line.startswith('@@'):
            m = re.match(r'@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@', line)
            if m and cur:
                old_ln, new_ln = int(m.group(1)), int(m.group(2))
                files[cur].append(('hunk', None, None, line))
        elif cur is not None:
            if line.startswith('+'):
                files[cur].append(('+', None, new_ln, line[1:])); new_ln += 1
            elif line.startswith('-'):
                files[cur].append(('-', old_ln, None, line[1:])); old_ln += 1
            elif line.startswith('\\'):
                continue
            else:
                files[cur].append((' ', old_ln, new_ln, line[1:] if line else ''))
                old_ln += 1; new_ln += 1
    return files

def render_comment(f):
    rc = rev_color(f['reviewer'])
    snippet = (f"<pre class='snippet'><code>{hl_code(lang_of(f['file']), f['snippet'])}</code></pre>"
               if f.get('snippet') else '')
    if f.get('plusone'):
        return f"""
    <div class="comment plusone" id="finding-{f['id']}">
      <div class="comment-head">
        <span class="avatar" style="background:{rc}">{rev_avatar(f['reviewer'])}</span>
        <span class="rev-name">{esc(rev_name(f['reviewer']))}</span>
        <span class="sev" style="color:var(--muted);background:var(--header);border:1px solid var(--border)">👍 +1</span>
      </div>
      <div class="comment-body"><div class="cbody">{md(f['body'])}</div></div>
    </div>"""
    c, bg, label = SEV_COLORS[f['severity']]
    return f"""
    <div class="comment" id="finding-{f['id']}">
      <div class="comment-head">
        <span class="avatar" style="background:{rc}">{rev_avatar(f['reviewer'])}</span>
        <span class="rev-name">{esc(rev_name(f['reviewer']))}</span>
        <span class="sev" style="color:{c};background:{bg};border:1px solid {c}33">{label}</span>
      </div>
      <div class="comment-body">
        <div class="ctitle">{md(f['title'])}</div>
        <div class="cbody">{md(f['body'])}</div>
        {snippet}
      </div>
    </div>"""

# file extension -> shiki language id (for client-side highlighting)
LANG_BY_EXT = {'dart':'dart','js':'javascript','ts':'typescript','tsx':'tsx','jsx':'jsx',
               'json':'json','yaml':'yaml','yml':'yaml','kt':'kotlin','kts':'kotlin',
               'swift':'swift','py':'python','rb':'ruby','go':'go','rs':'rust','java':'java',
               'gradle':'groovy','sh':'bash','html':'html','css':'css','xml':'xml','sql':'sql'}
def lang_of(path):
    return LANG_BY_EXT.get(path.rsplit('.', 1)[-1].lower(), 'text')

def render_file(mr, path, lines, file_findings):
    # Files with no comments: collapsed name-only entry, no diff content.
    if not file_findings:
        return f"""
    <details class="file nocomments">
      <summary><span class="fpath">{esc(path)}</span><span class="nbadge">changed · no comments</span></summary>
    </details>"""
    by_line = {}
    for f in file_findings:
        by_line.setdefault(f.get('line') or 0, []).append(f)
    # Split into hunks; keep only hunks containing at least one commented line.
    hunks = []  # (header_text, [(sign,ol,nl,text)])
    for sign, ol, nl, text in lines:
        if sign == 'hunk':
            hunks.append((text, []))
        elif hunks:
            hunks[-1][1].append((sign, ol, nl, text))
    matched = set()
    rows = []
    hidden = 0
    for header, hlines in hunks:
        has_comment = any(nl in by_line and sign != '-' for sign, ol, nl, _ in hlines)
        if not has_comment:
            hidden += 1
            continue
        rows.append(f"<tr class='hunk'><td class='ln'></td><td class='ln'></td><td class='code'>{esc(header)}</td></tr>")
        for sign, ol, nl, text in hlines:
            cls = {'+': 'add', '-': 'del', ' ': 'ctx'}[sign]
            mark = {'+': '+', '-': '-', ' ': ''}[sign]
            rows.append(
                f"<tr class='{cls}'><td class='ln'>{ol or ''}</td><td class='ln'>{nl or ''}</td>"
                f"<td class='code'><span class='sign'>{mark}</span><span class='ct'>{hl_code(lang_of(path), text)}</span></td></tr>")
            if nl in by_line and sign != '-':
                for f in by_line[nl]:
                    matched.add(f['id'])
                    rows.append(f"<tr class='crow'><td colspan='3'>{render_comment(f)}</td></tr>")
    if hidden:
        rows.append(f"<tr class='hunk'><td class='ln'></td><td class='ln'></td>"
                    f"<td class='code'>… {hidden} hunk{'s' if hidden != 1 else ''} without comments hidden</td></tr>")
    # findings whose line not in any kept hunk -> file-bottom section
    unmatched = [f for f in file_findings if f['id'] not in matched]
    tail = ''
    if unmatched:
        tail = "<div class='file-tail'>" + ''.join(
            f"<div class='tail-line'>Line {f.get('line','?')} (outside changed hunks):</div>{render_comment(f)}"
            for f in unmatched) + "</div>"
    table = f"<div class='tblwrap'><table class='difftbl'>{''.join(rows)}</table></div>" if rows else ''
    nfind = sum(1 for f in file_findings if not f.get('plusone'))
    badge = f"<span class='fbadge'>{nfind} comment{'s' if nfind!=1 else ''}</span>"
    return f"""
    <details class="file" open data-lang="{lang_of(path)}">
      <summary><span class="fpath">{esc(path)}</span>{badge}</summary>
      {table}
      {tail}
    </details>"""

def sev_count(fs, s): return sum(1 for f in fs if f['severity'] == s and not f.get('plusone'))

def render_mr(mr):
    m = meta[str(mr)]
    fs = [f for f in findings if f.get('mr') == mr and 'severity' in f]
    summaries = [f for f in findings if f.get('mr') == mr and 'summary' in f]
    diff = parse_diff(open(f'{BASE}/mr{mr}.diff').read())
    p0, p1, p2 = (sev_count(fs, s) for s in ('P0', 'P1', 'P2'))
    verdict = m.get('verdict', '')
    files_html = []
    for path, lines in diff.items():
        ffs = sorted([f for f in fs if f['file'] == path], key=lambda x: x.get('line') or 0)
        files_html.append(render_file(mr, path, lines, ffs))
    # findings on files not present in kept diff (shouldn't happen, but safe)
    diff_paths = set(diff.keys())
    orphans = [f for f in fs if f['file'] not in diff_paths]
    orphan_html = ''
    if orphans:
        orphan_html = "<h3 class='sub'>Other findings</h3>" + ''.join(
            f"<div class='tail-line'>{esc(f['file'])}:{f.get('line','?')}</div>{render_comment(f)}" for f in orphans)
    sums = ''.join(f"<li><b>{esc(rev_name(s['reviewer']))}:</b> {md(s['summary'])}</li>" for s in sorted(summaries, key=lambda x: x['reviewer']))
    RES_CHIP = {'resolved': ('✅ resolved', '#1a7f37', '#dafbe1'),
                'deferred': ('📌 deferred', '#9a6700', '#fff8c5'),
                'disputed': ('❌ still open', '#cf222e', '#ffebe9'),
                'clarified': ('💡 clarified — withdrawn', '#0969da', '#ddf4ff')}
    disc_html = ''
    if m.get('discussion'):
        items = []
        for d in m['discussion']:
            label, c, bg = RES_CHIP.get(d.get('resolution', ''), (esc(d.get('resolution', '')), '#57606a', '#f6f8fa'))
            items.append(
                f"<div class='disc'><div class='disc-head'><b>{esc(d.get('by', 'developer'))}:</b> "
                f"<span class='disc-quote'>“{md(d.get('quote', ''))}”</span>"
                f"<span class='bchip' style='color:{c};background:{bg};border:1px solid {c}33'>{label}</span></div>"
                f"<div class='disc-resp'>{md(d.get('response', ''))}</div></div>")
        disc_html = "<div class='discussion'><div class='disc-title'>💬 Thread follow-ups</div>" + ''.join(items) + "</div>"
    state_badge = {'merged': ('#8250df', 'Merged'), 'opened': ('#1a7f37', 'Open')}.get(m['state'], ('#57606a', m['state']))
    fixes = m.get('fix_prompt', '')
    fix_html = f"""
      <details class="fixprompt"><summary>📋 Fix Prompt — paste into Claude Code</summary>
      <pre><code>{esc(fixes)}</code></pre></details>""" if fixes else ''
    return f"""
    <section class="mr" id="mr{mr}">
      <div class="mr-head">
        <h2><a href="{esc(m['url'])}" target="_blank">!{mr}</a> {esc(m['title'])}</h2>
        <div class="mr-meta">
          <span class="state" style="background:{state_badge[0]}">{state_badge[1]}</span>
          {build_badge(m)}
          <span>{esc(m['author'])} wants to merge <code>{esc(m['source'])}</code> → <code>{esc(m['target'])}</code></span>
        </div>
      </div>
      <div class="overview">
        <div class="counts">
          <span class="cnt" style="color:#cf222e">P0: {p0}</span>
          <span class="cnt" style="color:#bc4c00">P1: {p1}</span>
          <span class="cnt" style="color:#9a6700">P2: {p2}</span>
          <span class="verdict">{esc(verdict)}</span>
        </div>
        <ul class="sums">{sums}</ul>
        {disc_html}
      </div>
      {''.join(files_html)}
      {orphan_html}
      {fix_html}
    </section>"""

total = {s: sev_count([f for f in findings if 'severity' in f], s) for s in ('P0','P1','P2')}
ORDER = meta.get('order') or sorted({f['mr'] for f in findings})

def bake_highlighting():
    """Pre-highlight all code via node+shiki (scripts/highlight.mjs) into HL.

    Baked inline spans survive sandboxed previews (Slack, mail clients) where
    external scripts are blocked. On any failure HL stays empty and the page
    falls back to the client-side CDN script.
    """
    items, keys = [], []
    seen = set()
    def add(lang, text):
        k = (lang, text)
        if text.strip() and k not in seen:
            seen.add(k); keys.append(k); items.append({'lang': lang, 'text': text})
    for mr in ORDER:
        diff = parse_diff(open(f'{BASE}/mr{mr}.diff').read())
        fs = [f for f in findings if f.get('mr') == int(mr) and 'severity' in f]
        commented = {f['file'] for f in fs}
        for path, lines in diff.items():
            if path not in commented:
                continue
            lang = lang_of(path)
            for sign, ol, nl, text in lines:
                if sign != 'hunk':
                    add(lang, text)
    for f in findings:
        if f.get('snippet'):
            add(lang_of(f['file']), f['snippet'])
    if not items:
        return
    try:
        r = subprocess.run(
            ['node', f'{SKILL_SCRIPTS}/highlight.mjs'],
            input=json.dumps({'items': items}), capture_output=True,
            text=True, cwd=SKILL_SCRIPTS, timeout=120,
        )
        if r.returncode != 0:
            print('highlight.mjs failed, falling back to client-side:', r.stderr[:300], file=sys.stderr)
            return
        for k, frag in zip(keys, json.loads(r.stdout)):
            if frag is not None:
                HL[k] = frag
    except Exception as e:
        print('highlighting skipped:', e, file=sys.stderr)

bake_highlighting()

def overview_table():
    rows = []
    for mr in ORDER:
        m = meta[str(mr)]
        fs = [f for f in findings if f.get('mr') == int(mr) and 'severity' in f]
        p0, p1, p2 = (sev_count(fs, s) for s in ('P0', 'P1', 'P2'))
        rows.append(
            f"<tr><td><a href='#mr{mr}'>!{mr}</a></td>"
            f"<td>{esc(m['title'])}</td><td>{esc(m['state'])}</td>"
            f"<td style='text-align:center'>{p0}</td><td style='text-align:center'>{p1}</td>"
            f"<td style='text-align:center'>{p2}</td><td>{build_badge(m)}</td>"
            f"<td>{esc(m.get('verdict',''))}</td></tr>")
    return ("<table class='ovtbl'><tr><th>MR</th><th>Title</th><th>State</th>"
            "<th>P0</th><th>P1</th><th>P2</th><th>Build</th><th>Verdict</th></tr>" + ''.join(rows) + "</table>")
TITLE = meta.get('title', 'MR Review — Panel of 3')
SUBTITLE = meta.get('subtitle', 'Reviewer A: Architecture & Patterns · B: Correctness & Edge Cases · '
                                'C: Performance & Code Quality · Generated files excluded.')
body = ''.join(render_mr(int(mr)) for mr in ORDER)

# Client-side CDN highlighting — emitted only when build-time baking failed
# (e.g. node/shiki unavailable). Does not run in sandboxed previews (Slack).
CLIENT_SCRIPT = """<script type="module">
try {
  const { createHighlighter } = await import('https://esm.sh/shiki@3');
  const cells = [...document.querySelectorAll('td.code .ct, pre.snippet code')];
  const langOf = el => el.closest('[data-lang]')?.dataset.lang || 'text';
  const wanted = [...new Set(cells.map(langOf))].filter(l => l !== 'text');
  if (wanted.length) {
    const hl = await createHighlighter({ themes: ['github-light', 'github-dark'], langs: [] });
    const loaded = new Set();
    for (const l of wanted) {
      try { await hl.loadLanguage(l); loaded.add(l); } catch {}
    }
    for (const el of cells) {
      const lang = langOf(el);
      if (!loaded.has(lang)) continue;
      const text = el.textContent;
      if (!text.trim()) continue;
      try {
        const { tokens: L } = hl.codeToTokens(text, { lang, theme: 'github-light' });
        const { tokens: D } = hl.codeToTokens(text, { lang, theme: 'github-dark' });
        const frag = document.createDocumentFragment();
        L.forEach((line, i) => {
          if (i) frag.appendChild(document.createTextNode('\\n'));
          line.forEach((t, j) => {
            const s = document.createElement('span');
            s.textContent = t.content;
            if (t.color) s.style.color = t.color;
            const dark = D[i] && D[i][j] && D[i][j].color;
            if (dark) s.style.setProperty('--sd', dark);
            frag.appendChild(s);
          });
        });
        el.replaceChildren(frag);
      } catch {}
    }
  }
} catch (e) { /* no network — keep plain text */ }
</script>"""

THEME_SCRIPT = """<script>
(function(){
  var KEY='mrreview-theme', root=document.documentElement;
  function apply(v){
    if(v==='light'||v==='dark') root.setAttribute('data-theme',v); else root.removeAttribute('data-theme');
    var btns=document.querySelectorAll('.theme-toggle button');
    for(var i=0;i<btns.length;i++){ var s=btns[i].getAttribute('data-set'); btns[i].classList.toggle('active', s===(v||'system')); }
  }
  var saved=null; try{ saved=localStorage.getItem(KEY); }catch(e){}
  apply(saved||'system');
  document.addEventListener('click',function(e){
    var b=e.target.closest && e.target.closest('.theme-toggle button'); if(!b) return;
    var v=b.getAttribute('data-set'); try{ localStorage.setItem(KEY,v); }catch(e){} apply(v);
  });
})();
</script>"""

page = f"""<meta charset="utf-8">
<title>{esc(TITLE)}</title>
<script>try{{var v=localStorage.getItem('mrreview-theme');if(v==='light'||v==='dark')document.documentElement.setAttribute('data-theme',v);}}catch(e){{}}</script>
<style>
  /* ---- theme tokens ---- */
  :root {{
    color-scheme: light;
    --bg:#f6f8fa; --card:#fff; --card-alt:#fcfcfd; --header:#f6f8fa;
    --border:#d1d9e0; --border-soft:#eff2f5;
    --text:#1f2328; --muted:#57606a; --soft:#3d444d; --link:#0969da;
    --code-bg:#eff2f5; --ln:#59636e;
    --hunk-bg:#ddf4ff; --hunk-fg:#57606a;
    --add-bg:#dafbe1; --add-ln:#aceebb; --del-bg:#ffebe9; --del-ln:#ffcecb;
  }}
  :root[data-theme="dark"] {{
    color-scheme: dark;
    --bg:#0d1117; --card:#161b22; --card-alt:#0d1117; --header:#1b222c;
    --border:#30363d; --border-soft:#21262d;
    --text:#e6edf3; --muted:#8b949e; --soft:#c9d1d9; --link:#4493f8;
    --code-bg:#343941; --ln:#6e7681;
    --hunk-bg:#132e4d; --hunk-fg:#8b949e;
    --add-bg:#12261e; --add-ln:#1a4327; --del-bg:#25171c; --del-ln:#4c1d24;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      color-scheme: dark;
      --bg:#0d1117; --card:#161b22; --card-alt:#0d1117; --header:#1b222c;
      --border:#30363d; --border-soft:#21262d;
      --text:#e6edf3; --muted:#8b949e; --soft:#c9d1d9; --link:#4493f8;
      --code-bg:#343941; --ln:#6e7681;
      --hunk-bg:#132e4d; --hunk-fg:#8b949e;
      --add-bg:#12261e; --add-ln:#1a4327; --del-bg:#25171c; --del-ln:#4c1d24;
    }}
  }}
  /* baked/highlighted code carries a --sd (dark) color; swap to it in dark mode */
  :root[data-theme="dark"] span[style*="--sd"] {{ color: var(--sd) !important; }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) span[style*="--sd"] {{ color: var(--sd) !important; }}
  }}

  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
         color:var(--text); background:var(--bg); margin:0; padding:24px; line-height:1.5; }}
  .wrap {{ max-width: 1100px; margin: 0 auto; }}
  h1 {{ font-size: 24px; }}
  .theme-toggle {{ position:fixed; top:12px; right:12px; z-index:100; display:flex; gap:2px;
                   background:var(--card); border:1px solid var(--border); border-radius:8px; padding:3px;
                   box-shadow:0 1px 4px rgba(0,0,0,.15); }}
  .theme-toggle button {{ border:0; background:transparent; color:var(--muted); cursor:pointer;
                          font-size:14px; line-height:1; padding:4px 8px; border-radius:6px; }}
  .theme-toggle button.active {{ background:var(--header); color:var(--text); }}
  .banner {{ background:var(--card); border:1px solid var(--border); border-radius:8px; padding:16px 20px; margin-bottom:24px; }}
  .banner .tot {{ font-weight:600; margin-right:16px; }}
  .mr {{ background:var(--card); border:1px solid var(--border); border-radius:8px; margin-bottom:32px; padding:0 0 16px; overflow:hidden; }}
  .mr-head {{ padding:16px 20px; border-bottom:1px solid var(--border); background:var(--card); }}
  .mr-head h2 {{ margin:0 0 6px; font-size:19px; font-weight:600; }}
  .mr-head h2 a {{ color:var(--link); text-decoration:none; }}
  .mr-meta {{ font-size:13px; color:var(--muted); display:flex; gap:10px; align-items:center; flex-wrap:wrap; }}
  .state {{ color:#fff; border-radius:2em; padding:3px 10px; font-size:12px; font-weight:600; }}
  code {{ background:var(--code-bg); padding:1px 5px; border-radius:4px; font-size:12px; }}
  .overview {{ padding:14px 20px; border-bottom:1px solid var(--border); background:var(--card-alt); }}
  .counts {{ display:flex; gap:16px; font-weight:600; font-size:14px; align-items:center; flex-wrap:wrap; }}
  .verdict {{ margin-left:auto; font-size:14px; }}
  .sums {{ margin:10px 0 0; padding-left:18px; font-size:13.5px; color:var(--soft); }}
  .sums li {{ margin-bottom:4px; }}
  .file {{ margin:16px 16px 0; border:1px solid var(--border); border-radius:8px; overflow:hidden; background:var(--card); }}
  .file > summary {{ padding:8px 12px; background:var(--header); cursor:pointer; font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
                     font-size:12.5px; font-weight:600; display:flex; align-items:center; gap:10px; border-bottom:1px solid var(--border); }}
  .fbadge {{ background:var(--link); color:#fff; border-radius:2em; font-size:11px; padding:2px 8px; font-family:-apple-system,sans-serif; }}
  .nbadge {{ color:var(--muted); font-weight:400; font-size:11.5px; font-family:-apple-system,sans-serif; }}
  .ovtbl {{ border-collapse:collapse; margin-top:12px; width:100%; font-size:13px; }}
  .ovtbl th, .ovtbl td {{ border:1px solid var(--border); padding:6px 10px; text-align:left; }}
  .ovtbl th {{ background:var(--header); }}
  .ovtbl a {{ color:var(--link); text-decoration:none; font-weight:600; }}
  .bchip {{ border-radius:2em; padding:2px 10px; font-size:11.5px; font-weight:600; white-space:nowrap; }}
  .bok {{ color:#1a7f37; background:#dafbe1; border:1px solid #1a7f3733; }}
  .bfail {{ color:#cf222e; background:#ffebe9; border:1px solid #cf222e33; }}
  .bskip {{ color:var(--muted); background:var(--header); border:1px solid var(--border); }}
  .discussion {{ margin-top:12px; border-top:1px dashed var(--border); padding-top:10px; }}
  .disc-title {{ font-weight:600; font-size:13.5px; margin-bottom:8px; }}
  .disc {{ border:1px solid var(--border); border-radius:8px; padding:8px 12px; margin-bottom:8px; background:var(--card); font-size:13.5px; }}
  .disc-head {{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; }}
  .disc-quote {{ color:var(--muted); font-style:italic; }}
  .disc-head .bchip {{ margin-left:auto; }}
  .disc-resp {{ margin-top:6px; color:var(--soft); }}
  .file.nocomments > summary {{ border-bottom:none; opacity:.75; }}
  .tblwrap {{ overflow-x:auto; }}
  .difftbl {{ border-collapse:collapse; width:100%; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; }}
  .difftbl td {{ padding:0 8px; white-space:pre; vertical-align:top; line-height:20px; }}
  .ln {{ width:1%; min-width:40px; text-align:right; color:var(--ln); user-select:none; background:var(--card); border-right:1px solid var(--border-soft); }}
  .sign {{ display:inline-block; width:12px; color:var(--ln); }}
  tr.add td {{ background:var(--add-bg); }} tr.add .ln {{ background:var(--add-ln); }}
  tr.del td {{ background:var(--del-bg); }} tr.del .ln {{ background:var(--del-ln); }}
  tr.hunk td {{ background:var(--hunk-bg); color:var(--hunk-fg); padding:4px 8px; }}
  tr.crow > td {{ padding:8px 16px; background:var(--header); border-top:1px solid var(--border); border-bottom:1px solid var(--border); white-space:normal; }}
  .comment.plusone {{ margin-left:32px; margin-top:6px; opacity:.92; }}
  .comment {{ background:var(--card); border:1px solid var(--border); border-radius:8px; max-width:820px;
              font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
  .comment-head {{ display:flex; align-items:center; gap:8px; padding:8px 12px; background:var(--header);
                   border-bottom:1px solid var(--border); border-radius:8px 8px 0 0; font-size:13px; }}
  .avatar {{ width:24px; height:24px; border-radius:50%; color:#fff; font-weight:700; font-size:12px;
             display:flex; align-items:center; justify-content:center; flex:none; }}
  .rev-name {{ font-weight:600; }}
  .sev {{ margin-left:auto; border-radius:2em; padding:2px 10px; font-size:11.5px; font-weight:600; }}
  .comment-body {{ padding:10px 14px; font-size:13.5px; }}
  .ctitle {{ font-weight:600; margin-bottom:4px; }}
  .cbody {{ color:var(--soft); white-space:pre-wrap; }}
  .snippet {{ background:var(--header); border:1px solid var(--border); border-radius:6px; padding:8px 10px; margin:8px 0 0;
              font-size:12px; overflow-x:auto; }}
  .file-tail {{ padding:10px 12px; background:var(--card-alt); border-top:1px solid var(--border); display:flex; flex-direction:column; gap:8px; }}
  .tail-line {{ font-size:12px; color:var(--muted); font-family:ui-monospace,Menlo,monospace; }}
  .fixprompt {{ margin:16px; border:1px solid var(--border); border-radius:8px; background:var(--card); }}
  .fixprompt > summary {{ padding:10px 14px; cursor:pointer; font-weight:600; font-size:14px; background:var(--header); }}
  .fixprompt pre {{ margin:0; padding:14px; overflow-x:auto; font-size:12px; background:var(--card); white-space:pre-wrap; }}
  .sub {{ margin:16px 16px 0; }}
</style>
<div class="theme-toggle" role="group" aria-label="Theme">
  <button type="button" data-set="light" title="Light">☀</button>
  <button type="button" data-set="dark" title="Dark">☾</button>
  <button type="button" data-set="system" title="System">🖥</button>
</div>
<div class="wrap">
  <h1>🔍 {esc(TITLE)}</h1>
  <div class="banner">
    <span class="tot">Totals:</span>
    <span class="cnt" style="color:#cf222e;font-weight:600">P0: {total['P0']}</span> ·
    <span class="cnt" style="color:#bc4c00;font-weight:600">P1: {total['P1']}</span> ·
    <span class="cnt" style="color:#9a6700;font-weight:600">P2: {total['P2']}</span>
    <div style="font-size:13px;color:var(--muted);margin-top:6px">
      Reviewed {esc(meta.get('date',''))} · {esc(SUBTITLE)}
    </div>
    {overview_table()}
  </div>
  {body}
</div>
{'' if HL else CLIENT_SCRIPT}
{THEME_SCRIPT}
"""
open(f'{BASE}/mr-review.html', 'w', encoding='utf-8').write(page)
print('written', f'{BASE}/mr-review.html', len(page))
