"""Static text of the review sheet: CSS, JavaScript and the reviewer instructions.

Kept apart from ``pack_sheet.py`` so that the writer code stays short. Pure constants.
"""

CSS = """
body{font:14px/1.4 system-ui,sans-serif;margin:0 auto;max-width:1020px;padding:0 16px;
color:#1a1a1a;background:#fff}
header{position:sticky;top:0;background:#fff;border-bottom:1px solid #ccc;padding:6px 0;z-index:2}
h1{font-size:18px;margin:4px 0}h2{font-size:16px;margin:22px 0 4px}
h2 small{font-weight:normal;color:#555;font-size:12px}
.panel{margin:4px 0}.cap{font-size:12px;color:#555}
svg{width:100%;height:auto;border:1px solid #ddd;background:#fcfcfc}
.g{stroke:#e3e3e3;stroke-width:1}.t{font-size:10px;fill:#666}
.pv{fill:none;stroke:#1f5fbf;stroke-width:1.1}.op{fill:none;stroke:#2a8a3e;stroke-width:1.1}
.sp{fill:none;stroke:#d9731a;stroke-width:1.2;stroke-dasharray:5 3}
.man{fill:#999;opacity:.25}
.form{display:grid;grid-template-columns:130px 200px 1fr 120px;gap:8px;margin:6px 0;
align-items:start}
.form label{display:flex;flex-direction:column;font-size:12px;color:#444}
.form input,.form select,.form textarea{font:inherit;padding:3px}
.wide{min-width:0}.dup{outline:2px solid #c0392b}
@media(max-width:700px){.form{grid-template-columns:1fr 1fr}}
@media print{header{position:static}section{break-inside:avoid}}
"""

SCRIPT = """
const KEY='loop_review_answers_v1';
const secs=[...document.querySelectorAll('section')];
const q=(s,c)=>s.querySelector(c);
function save(){try{localStorage.setItem(KEY,JSON.stringify(secs.map(rowOf)))}catch(e){}}
function rowOf(s){return{tag:s.dataset.tag,rank:q(s,'.rank').value,category:q(s,'.cat').value,
next_action:q(s,'.act').value,confidence:q(s,'.conf').value}}
function load(){try{const d=JSON.parse(localStorage.getItem(KEY)||'[]');
d.forEach(r=>{const s=secs.find(x=>x.dataset.tag===r.tag);if(!s)return;
q(s,'.rank').value=r.rank;q(s,'.cat').value=r.category;q(s,'.act').value=r.next_action;
q(s,'.conf').value=r.confidence})}catch(e){}}
function check(){const rows=secs.map(rowOf);const seen={};
rows.forEach(r=>{if(r.rank)seen[r.rank]=(seen[r.rank]||0)+1});
secs.forEach(s=>q(s,'.rank').classList.toggle('dup',seen[q(s,'.rank').value]>1));
const done=rows.filter(r=>r.rank&&r.category).length;
const dups=Object.keys(seen).filter(k=>seen[k]>1);
document.getElementById('status').textContent=done+'/'+rows.length+' answered'+
(dups.length?'; duplicate ranks: '+dups.join(', '):'');save()}
const esc=v=>'"'+String(v).replace(/"/g,'""')+'"';
function exportCsv(){const head='tag,rank,category,next_action,confidence';
const lines=secs.map(rowOf).map(r=>[r.tag,r.rank,r.category,r.next_action,r.confidence]
.map(esc).join(','));const blob=new Blob([[head,...lines].join('\\r\\n')],{type:'text/csv'});
const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='answers.csv';
a.click()}
document.addEventListener('input',check);load();check();
document.getElementById('export').onclick=exportCsv;
"""

INSTRUCTIONS = """# Loop review - instructions for the reviewer

You get 20 control loops, each recorded for 6 hours at one sample every 10 seconds.
Please do not use any automatic analysis tool; look at the trends and use your own plant
experience. Plan about 45 minutes in total.

## What to do

1. Open `review_sheet.html` in a normal browser (no network needed). For each loop you see
   the PV with its setpoint, and the controller output OP (grey bands = manual mode).
2. Rank the loops by what you would go and look at FIRST on a plant: rank 1 is the loop
   you would deal with first, rank 20 the one you would not touch. Every rank 1-20 is used
   once. Ties are not allowed.
3. For each loop pick the problem category that fits best:
{categories}
4. Write the next action in your own words, as you would put it on a work order (one or two
   sentences, e.g. "check the valve", "retune", "look for the source upstream").
5. Give your confidence from 1 (guess) to 5 (certain).
6. Press "Export answers CSV" at the top of the sheet and send back `answers.csv`.
   (Alternatively fill `answers_template.csv` with the columns tag, rank, category,
   next_action, confidence.)

## Notes

- All loops are simulated; tag names carry no meaning beyond the first letters
  (F flow, T temperature, L level, P pressure). Level loops are integrating processes.
- Loops are in random order; the order tells nothing about priority.
- Raw data of each loop is in `<TAG>.csv` (t_s, sp, pv, op, mode; mode 0 = manual,
  1 = auto) if you want to look at it in your own tool.
- There is no right or wrong answer for your priority; we compare it later with a
  separate automatic list.
"""
