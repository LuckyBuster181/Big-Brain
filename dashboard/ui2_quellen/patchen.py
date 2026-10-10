# baut dashboard/index.html aus index_vor_ui2.html + UI-2.0-Teilen neu
import re
D='/home/claude/jb/ui2/'
s=open(D+'index_vor_ui2.html',encoding='utf-8').read()
r=lambda f: open(D+f,encoding='utf-8').read()
def ein(alt,neu,n=1):
    global s
    assert s.count(alt)==n, (alt[:60], s.count(alt)); s=s.replace(alt,neu)
ein('</head>',r('stil.css')+'\n</head>')
a=s.index('  <nav>',s.index('<header>')); b=s.index('</nav>',a)+len('</nav>\n'); s=s[:a]+s[b:]
ein('</header>\n','</header>\n'+r('leiste.html')+'\n')
ein('<section class="page" id="page-jarvis">','<section class="page" id="page-jarvis">\n'+r('voll.html'))
ein('        <div class="card" style="margin-bottom:14px;">\n          <h2>Kern</h2>', r('status.html')+'        <div class="card" style="margin-bottom:14px;">\n          <h2>Kern</h2>')
ein('const WECKWORT =','let WECKWORT =')
ein('else if (ev.typ === "quellen") { quellen = ev.quellen || []; }','else if (ev.typ === "quellen") { quellen = ev.quellen || []; try { window.dispatchEvent(new CustomEvent("jarvis-quellen", { detail: quellen })); } catch (e) {} }')
# Seiten 2.0: Markt und Alltag neu (IDs bleiben, die alte Logik läuft weiter)
def sektion(pid, neu):
    global s
    a0=s.index('id="page-%s"'%pid); a0=s.rindex('<section',0,a0); b0=s.index('</section>',a0)+len('</section>')
    s=s[:a0]+r(neu).strip()+s[b0:]
sektion('markt','markt.html'); sektion('alltag','alltag.html')
# Fehler seit Phase 4: zwei Funktionen "ansichtSetzen" - die Markt-Version überschrieb die Kalender-Version
ein('function ansichtSetzen(a) {\n  jm.ansicht = a;','function marktAnsichtSetzen(a) {\n  jm.ansicht = a;')
ein('$("ansichtLive").addEventListener("click", () => ansichtSetzen("live"));','$("ansichtLive").addEventListener("click", () => marktAnsichtSetzen("live"));')
ein('$("ansichtAlle").addEventListener("click", () => ansichtSetzen("alle"));','$("ansichtAlle").addEventListener("click", () => marktAnsichtSetzen("alle"));')
i=s.rindex('</script>'); s=s[:i]+'\n/*UI2-START*/'+r('ui2.js')+r('seiten2.js')+'/*UI2-ENDE*/\n'+s[i:]
open('/home/claude/jb/dashboard/index.html','w',encoding='utf-8').write(s)
st=s.index('<script>',s.index('</header>')); en=s.index('</script>',st)
open('/tmp/claude-0/haupt.js','w').write(s[st+8:en])
print(len(s.encode()))
