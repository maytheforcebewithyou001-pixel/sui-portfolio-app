"""TAB 管理者: ユーザー追加補助＆シート管理"""
import streamlit as st
import bcrypt
import html
from config import logger
from data import get_spreadsheet_for, _sheet_name_for


def is_admin(username: str) -> bool:
    """指定ユーザーが管理者か判定"""
    admins = st.secrets.get("admin_users", ["admin"])
    if isinstance(admins, str):
        admins = [admins]
    return username in admins


def render(tab):
    with tab:
        st.markdown("### 👑 ユーザー管理（管理者専用）")
        st.caption("Streamlit Cloud の Secrets 編集は手動で行う必要があります。このツールは補助のみです。")

        # ── 現在のユーザー一覧 ──
        st.markdown("#### 登録済みユーザー")
        users = dict(st.secrets.get("users", {})) if st.secrets.get("users") else {}
        if users:
            admins = st.secrets.get("admin_users", ["admin"])
            if isinstance(admins, str): admins = [admins]
            for uname in sorted(users.keys()):
                role = " 👑 管理者" if uname in admins else ""
                sheet = _sheet_name_for(uname)
                st.markdown(f"- **{html.escape(uname)}**{role} → シート: `{html.escape(sheet)}`")
        else:
            st.info("まだユーザーが登録されていません（admin_users / users を secrets に追加してください）")

        st.markdown("---")

        # ── 新規ユーザーのハッシュ生成 ──
        st.markdown("#### 新規ユーザーのパスワードハッシュ生成")
        with st.form("add_user_form"):
            new_user = st.text_input("ユーザー名", placeholder="例: alice", key="new_user")
            new_pw = st.text_input("パスワード（8文字以上推奨）", type="password", key="new_pw")
            make_admin = st.checkbox("管理者権限を付与する", key="new_admin")
            submitted = st.form_submit_button("ハッシュ生成 & TOML スニペット出力", width="stretch")
        if submitted:
            if not new_user or not new_pw:
                st.error("ユーザー名とパスワードの両方を入力してください")
            elif len(new_pw) < 8:
                st.warning("パスワードは8文字以上を推奨します")
            else:
                hashed = bcrypt.hashpw(new_pw.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
                st.success("✓ ハッシュ生成完了。以下を Streamlit Cloud の Secrets に追加してください:")
                admin_snippet = ""
                if make_admin:
                    existing_admins = list(st.secrets.get("admin_users", ["admin"]))
                    if isinstance(existing_admins, str): existing_admins = [existing_admins]
                    if new_user not in existing_admins:
                        existing_admins.append(new_user)
                    admin_snippet = f'admin_users = {existing_admins}\n\n'
                toml_snippet = f'''{admin_snippet}[users]
# 既存ユーザーは残したまま以下を追記
{new_user} = "{hashed}"'''
                st.code(toml_snippet, language="toml")
                st.caption("⚠ Secrets 更新後、アプリは自動再起動します。数秒後にログインをお試しください。")
                logger.info("管理者が新規ユーザーハッシュを生成: user=%s admin=%s", new_user, make_admin)

        st.markdown("---")

        # ── シート事前作成 ──
        st.markdown("#### スプレッドシート事前作成")
        st.caption("新規ユーザーのシートを手動で作成します（初回ログイン時の自動作成でも代用可能）")
        pre_user = st.text_input("ユーザー名", key="pre_user", placeholder="作成対象のユーザー名")
        if st.button("シート作成", width="stretch", key="create_sheet_btn"):
            if not pre_user:
                st.error("ユーザー名を入力してください")
            else:
                # get_spreadsheet_for はキャッシュなので既存があればそれを返す
                sh = get_spreadsheet_for(pre_user)
                if sh is not None:
                    st.success(f"✓ シート '{_sheet_name_for(pre_user)}' を確認/作成しました")
                else:
                    st.error("シート作成に失敗しました。ログを確認してください。")

        st.markdown("---")
        st.markdown("#### 運用メモ")
        st.info(
            "- Streamlit Cloud の Secrets 編集: Manage app → Settings → Secrets\n"
            "- Secrets 更新後はアプリが自動再起動します\n"
            "- GCPサービスアカウントが作成者になるため、必要に応じて Google Drive で該当シートを手動共有してください"
        )
