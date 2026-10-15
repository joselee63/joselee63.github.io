# ======================================
# 숨은 사진 만들기 — 사진 + 메시지를 비밀번호로 암호화해서 web/secret.json 으로 저장
#   · 사이트에서 제목 앞 국기를 빠르게 5번 누르면 비밀번호 입력창이 뜨고, 맞으면 사진이 보입니다.
#   · 저장소·사이트에는 암호화된 secret.json 만 올라가고, 원본 사진과 비밀번호는 올라가지 않습니다.
#   · 실행:  python tools/make_secret.py  [사진 경로]   (기본: 저장소 바깥의 ../secret_photo.jpg)
#     필요 패키지: pip install cryptography pillow
#   · 암호화: PBKDF2-SHA256(60만 회)로 비밀번호 → 키, AES-256-GCM (브라우저 WebCrypto 로 풀 수 있는 방식)
# ======================================
import os, sys, io, json, base64, getpass

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    from PIL import Image
except ImportError:
    sys.exit("필요한 패키지가 없습니다:  pip install cryptography pillow")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "web", "secret.json")
ITER = 600_000
MAX_SIDE = 1400                                     # 사진 긴 변 (용량 줄이기)


def photo_data_url(path):
    im = Image.open(path)
    im = im.convert("RGB")
    im.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(ROOT), "secret_photo.jpg")
    if not os.path.exists(path):
        sys.exit(f"사진을 찾지 못했습니다: {path}")
    print(f"사진: {path}")
    pw = getpass.getpass("비밀번호 (입력해도 화면에 안 보입니다): ")
    if len(pw) < 4:
        sys.exit("비밀번호는 4글자 이상으로 해 주세요.")
    if getpass.getpass("비밀번호 한 번 더: ") != pw:
        sys.exit("두 비밀번호가 다릅니다. 다시 실행해 주세요.")
    msg = input("사진 아래 메시지 (없으면 그냥 Enter): ").strip()

    plain = json.dumps({"img": photo_data_url(path), "msg": msg}, ensure_ascii=False).encode("utf-8")
    salt, iv = os.urandom(16), os.urandom(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITER).derive(pw.encode("utf-8"))
    data = AESGCM(key).encrypt(iv, plain, None)      # 암호문 + 인증 태그 (WebCrypto AES-GCM 과 같은 형식)
    b64 = lambda b: base64.b64encode(b).decode("ascii")
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"v": 1, "iter": ITER, "salt": b64(salt), "iv": b64(iv), "data": b64(data)}, f)
    print(f"완료: {OUT} ({os.path.getsize(OUT) / 1024:.0f}KB) — 커밋·배포하면 사이트에 반영됩니다.")


if __name__ == "__main__":
    main()
