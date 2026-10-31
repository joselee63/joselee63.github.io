/* ======================================
   숨은 사진 — 제목 앞 국기를 빠르게 5번 누르면 비밀번호 입력 → 맞으면 사진과 메시지
   · secret.json(tools/make_secret.py 로 만든 암호화 파일)이 없으면 아무 일도 일어나지 않음
   · 복호화: PBKDF2-SHA256 → AES-256-GCM (브라우저 WebCrypto, 서버로 아무것도 보내지 않음)
   ====================================== */
(function(){
  "use strict";
  var flag = document.querySelector("h1 .flag");
  if (!flag || !window.crypto || !crypto.subtle) return;
  flag.style.touchAction = "manipulation";            // 연속 터치가 휴대폰 확대로 바뀌지 않게

  var taps = 0, last = 0, box = null;
  flag.addEventListener("click", function(e){
    e.preventDefault(); e.stopPropagation();            // 국기는 '처음 화면' 링크로 동작하지 않음
    var t = Date.now();
    taps = t - last < 700 ? taps + 1 : 1;
    last = t;
    if (taps >= 5) { taps = 0; open(); }
  });

  function b64(s){ var bin = atob(s), a = new Uint8Array(bin.length); for (var i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i); return a; }
  function el(tag, css, html){ var d = document.createElement(tag); if (css) d.style.cssText = css; if (html) d.innerHTML = html; return d; }

  function open(){
    fetch("secret.json", { cache: "no-cache" }).then(function(r){ return r.ok ? r.json() : null; }).then(function(sec){
      if (sec && !box) show(sec);
    }, function(){});
  }

  function show(sec){
    box = el("div", "position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px;" +
      "background:rgba(0,0,0,.55);-webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px);opacity:0;transition:opacity .3s");
    var card = el("div", "background:var(--card,#fff);color:var(--fg,#1d1d1f);border-radius:22px;padding:22px;max-width:min(92vw,720px);" +
      "box-shadow:0 20px 60px rgba(0,0,0,.35);text-align:center;transform:scale(.96);transition:transform .3s");
    var form = el("form", "display:flex;flex-direction:column;gap:10px;align-items:center;min-width:240px",
      '<div style="font-size:30px">🤫</div><div style="font-weight:700;font-size:15px">비밀번호</div>' +
      '<input type="password" autocomplete="off" style="font:inherit;font-size:16px;padding:9px 14px;border-radius:12px;' +
      'border:1px solid var(--line,#ddd);background:var(--soft,#f2f2f4);color:inherit;width:200px;text-align:center">' +
      '<div class="err" style="font-size:12.5px;color:var(--up,#e5383b);min-height:16px"></div>' +
      '<button type="submit" style="font:inherit;font-weight:700;cursor:pointer;border:0;border-radius:999px;padding:9px 22px;' +
      'background:var(--accent,#1d1d1f);color:var(--accent-fg,#fff)">열기</button>');
    card.appendChild(form); box.appendChild(card); document.body.appendChild(box);
    requestAnimationFrame(function(){ box.style.opacity = "1"; card.style.transform = "scale(1)"; });
    var input = form.querySelector("input"), err = form.querySelector(".err");
    input.focus();

    form.addEventListener("submit", function(e){
      e.preventDefault();
      err.textContent = "여는 중…";
      decrypt(sec, input.value).then(function(p){
        card.innerHTML = "";
        var img = el("img", "display:block;max-width:100%;max-height:72vh;border-radius:14px;opacity:0;transition:opacity .6s");
        img.alt = ""; img.src = p.img;
        card.appendChild(img);
        if (p.msg) card.appendChild(el("div", "margin-top:14px;font-size:17px;font-weight:700;letter-spacing:-.2px")).textContent = p.msg;
        img.onload = function(){ img.style.opacity = "1"; };
      }, function(){
        err.textContent = "비밀번호가 달라요";
        input.select();
        card.animate && card.animate([{ transform: "translateX(0)" }, { transform: "translateX(-8px)" }, { transform: "translateX(8px)" },
                                      { transform: "translateX(0)" }], { duration: 300 });
      });
    });
    box.addEventListener("click", function(e){ if (e.target === box) close(); });
    document.addEventListener("keydown", esc);
  }

  function esc(e){ if (e.key === "Escape") close(); }
  function close(){
    if (!box) return;
    var b = box; box = null; document.removeEventListener("keydown", esc);
    b.style.opacity = "0"; setTimeout(function(){ b.remove(); }, 300);
  }

  function decrypt(sec, pw){
    var enc = new TextEncoder();
    return crypto.subtle.importKey("raw", enc.encode(pw), "PBKDF2", false, ["deriveKey"]).then(function(base){
      return crypto.subtle.deriveKey({ name: "PBKDF2", salt: b64(sec.salt), iterations: sec.iter, hash: "SHA-256" },
                                     base, { name: "AES-GCM", length: 256 }, false, ["decrypt"]);
    }).then(function(key){
      return crypto.subtle.decrypt({ name: "AES-GCM", iv: b64(sec.iv) }, key, b64(sec.data));
    }).then(function(buf){ return JSON.parse(new TextDecoder().decode(buf)); });
  }
})();
