#!/bin/bash
# ui2.js zwischen /*UI2-START*/ und /*UI2-ENDE*/ ersetzen
python3 - <<'P'
p='/home/claude/jb/dashboard/index.html'; s=open(p,encoding='utf-8').read()
a=s.index('/*UI2-START*/')+len('/*UI2-START*/'); b=s.index('/*UI2-ENDE*/')
s=s[:a]+open('/home/claude/jb/ui2/ui2.js',encoding='utf-8').read()+s[b:]
open(p,'w',encoding='utf-8').write(s)
st=s.index('<script>',s.index('</header>')); en=s.index('</script>',st)
open('/tmp/claude-0/haupt.js','w').write(s[st+8:en])
P
node --check /tmp/claude-0/haupt.js && echo HAUPT_OK
