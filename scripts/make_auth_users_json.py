"""FC_AUTH_USERS_JSON 組み立てスクリプト — 秘密情報をチャット・画面に出さないための道具

使い方(⚠ Claude Code の `!` 経由ではなく、別ウィンドウの PowerShell で。リポジトリ直下):
  python scripts\make_auth_users_json.py | clip

対話プロンプトは stderr に出るので clip に混ざらない。完成した JSON だけが
クリップボードに入り、Secret Manager (例: fc-auth-users) やローカル環境変数へ
直接貼り付けられる。パスワードは getpass で非表示入力・どこにも保存しない。

各ユーザーのハッシュ入手方法:
  p = パスワードを入力して bcrypt ハッシュを新規生成(父アカウント用)
  h = 既存の bcrypt ハッシュを貼り付け(非表示入力)
  g = gcloud で Secret Manager から取得(admin の現行ハッシュ fc-auth-hash 用。
      事前に gcloud auth login 済みであること)
"""
import getpass
import json
import subprocess
import sys

import bcrypt


def eprint(*args):
    print(*args, file=sys.stderr, flush=True)


def ask(prompt: str) -> str:
    eprint(prompt)
    return input().strip()


def hidden_input(prompt: str) -> str:
    """対話時は非表示入力。Windowsのgetpassはstdinがパイプでも実コンソールを
    読みに行って永久に待つため、非TTY時(自動テスト等)は明示的にstdinへ落とす"""
    if sys.stdin.isatty():
        return getpass.getpass(prompt, stream=sys.stderr)
    eprint(prompt)
    return input()


def valid_hash(h: str) -> bool:
    return h.startswith(("$2a$", "$2b$", "$2y$")) and len(h) == 60


def hash_from_password() -> str:
    while True:
        pw = hidden_input("パスワード(非表示・12文字以上推奨): ")
        if len(pw) < 8:
            eprint("✗ 8文字未満は不可。やり直し。")
            continue
        pw2 = hidden_input("確認のためもう一度: ")
        if pw != pw2:
            eprint("✗ 一致しません。やり直し。")
            continue
        return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def hash_from_paste() -> str:
    while True:
        h = hidden_input("bcryptハッシュを貼り付け(非表示): ").strip()
        if valid_hash(h):
            return h
        eprint("✗ bcryptハッシュの形式($2b$...で60文字)ではありません。やり直し。")


def hash_from_gcloud() -> str:
    secret = ask("Secret Manager のシークレット名(既定: fc-auth-hash):") or "fc-auth-hash"
    r = subprocess.run(
        ["gcloud", "secrets", "versions", "access", "latest", "--secret", secret],
        capture_output=True, text=True, shell=True,
    )
    h = r.stdout.strip()
    if r.returncode != 0 or not valid_hash(h):
        eprint(f"✗ 取得失敗または形式不正(gcloud rc={r.returncode})。stderr: {r.stderr.strip()[:200]}")
        raise SystemExit(1)
    eprint(f"✓ {secret} から取得")
    return h


def main():
    users = {}
    eprint("=== FC_AUTH_USERS_JSON 組み立て ===")
    eprint("ユーザーを順に登録します(admin も忘れずに)。ユーザー名を空 Enter で確定・出力。")
    while True:
        name = ask(f"\nユーザー名(半角英数、現在{len(users)}人登録済み):")
        if not name:
            break
        if not name.isascii() or " " in name:
            eprint("✗ 半角英数(空白なし)にしてください。シート名サフィックスにも使われます。")
            continue
        method = ask("ハッシュ入手方法 [p=パスワードから生成 / h=貼り付け / g=gcloud取得]:").lower()
        if method == "p":
            users[name] = hash_from_password()
        elif method == "h":
            users[name] = hash_from_paste()
        elif method == "g":
            users[name] = hash_from_gcloud()
        else:
            eprint("✗ p / h / g のいずれかを指定。")
            continue
        eprint(f"✓ {name} を登録")
    if not users:
        eprint("登録なし。終了。")
        raise SystemExit(1)
    print(json.dumps(users, ensure_ascii=False), end="")
    eprint(f"\n✓ {len(users)}人分の JSON を stdout に出力しました(| clip 推奨)。")
    eprint("  登録ユーザー: " + ", ".join(users))


if __name__ == "__main__":
    main()
