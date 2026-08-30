"""streamlit @st.cache_data の置換 (Streamlit退役 2026-08-30)

ttl_cache(ttl): 位置引数・キーワード引数をキーに戻り値をTTL秒メモ化する。
fn.clear() でキャッシュ全消去(@st.cache_data の .clear() と同じ用途)。

st.cache_data と違い戻り値は「同一オブジェクト」を返す(pickleコピーしない)。
呼び出し側は戻り値の DataFrame/dict を直接変更しないこと — 変更が必要なら
.copy() してから使う(api/service.py は既にこの規約で書かれている)。
"""
import functools
import threading
import time


def ttl_cache(ttl: float):
    """戻り値をTTL秒キャッシュするデコレータ。引数はハッシュ可能であること"""
    def deco(fn):
        store = {}
        lock = threading.Lock()

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            now = time.monotonic()
            with lock:
                hit = store.get(key)
                if hit is not None and now - hit[1] < ttl:
                    return hit[0]
            val = fn(*args, **kwargs)
            with lock:
                store[key] = (val, now)
            return val

        def clear():
            with lock:
                store.clear()

        wrapper.clear = clear
        return wrapper
    return deco
