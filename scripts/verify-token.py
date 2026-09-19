#!/usr/bin/env python3
"""verify-token.py — read the reCAPTCHA response token + checkbox state.

Small companion used to confirm a solve landed, kept out of the runner so quoting
a nested JS selector never has to survive a shell layer.

    verify-token.py [cdp-port]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as cfg  # noqa: E402
from cdp import CDP  # noqa: E402

JS = r"""
(()=>{
  const g = document.querySelector('textarea[name="g-recaptcha-response"],#g-recaptcha-response');
  const anchors=[...document.querySelectorAll('iframe')].filter(f=>(f.src||'').includes('/anchor'));
  const bfs=[...document.querySelectorAll('iframe')].filter(f=>(f.src||'').includes('/bframe'));
  let checked=null;
  if(anchors.length){
    try{ const d=anchors[0].contentDocument;
      const cb=d&&d.querySelector('.recaptcha-checkbox');
      checked=cb?cb.getAttribute('aria-checked'):null; }catch(e){ checked='err:'+e.name; }
  }
  return JSON.stringify({url:location.href,
    tokenLen: g ? (g.value||'').length : 0,
    tokenHead: g ? (g.value||'').slice(0,32) : null,
    checked: checked,
    bframeArmed: bfs.length ? bfs[0].getBoundingClientRect().y > -100 : null,
    title: document.title});
})()
"""

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else cfg.CDP_PORT
    c = CDP(port=port, host=cfg.CDP_HOST)
    print(json.dumps(c.js(JS), indent=2))
    c.close()
