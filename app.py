import json
import os
import re
import sqlite3
import zipfile

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

# --- 全局与主题配置 (必须放在最顶部) ---
st.set_page_config(page_title="典藏传世名方系统V2.0", page_icon="📜", layout="wide")

# 注入自定义 CSS：庄重、古朴的中医古籍风格
st.markdown("""
    <style>
    .stApp { background-color: #FDFBF7; font-family: 'Noto Serif SC', 'SimSun', 'Songti SC', serif; color: #2C2825; }
    h1, h2, h3 { color: #792D11 !important; font-weight: bold; }
    [data-testid="stSidebar"] { background-color: #F2E8D5; border-right: 2px solid #D9C5A0; }
    .stButton>button { background-color: #792D11; color: #FFFFFF; border-radius: 4px; border: 1px solid #4A1A08; transition: all 0.3s ease; font-weight: bold; }
    .stButton>button:hover { background-color: #4A1A08; color: #FDFBF7; border: 1px solid #792D11; }
    [data-testid="stVerticalBlockBorderWrapper"] { background-color: #FFFFFF; border: 1px solid #E8DCC4 !important; box-shadow: 0 4px 6px rgba(0,0,0,0.02); border-radius: 8px; }
    mark.yellow-highlight { background-color: #FFF2CC; color: #B83B00; font-weight: bold; padding: 0 4px; border-radius: 2px; border-bottom: 2px solid #F0B27A; }
    .disclaimer { color: #B83B00; font-size: 0.85rem; padding: 10px; border-top: 1px dashed #D9C5A0; margin-top: 30px; }
    </style>
""", unsafe_allow_html=True)

DB_FILE = "tcm_database.db"
ZIP_FILE = "tcm_database.zip"

FORMULA_TABLE = "formulas"
RECIPE_TABLE = "recipes"
VERIF_TABLE = "各种验方表"

VERIF_COLUMNS = ["方名", "方剂", "主治功能", "案例", "来源", "备注"]
FORMULA_COLUMNS = [
    "id", "大医名", "方剂名", "方剂详情", "临床病名", "病例详情",
    "按语", "现代研究", "临证提要", "方别", "其他",
]
RECIPE_COLUMNS = [
    "id", "菜名", "材料和制作", "功效", "注意事项", "适合季节",
    "适合年纪", "适合性别", "餐别", "版别", "出处", "编者及其身份", "品类",
]
TABLE_COLUMNS = {
    FORMULA_TABLE: FORMULA_COLUMNS,
    RECIPE_TABLE: RECIPE_COLUMNS,
}

DEFAULT_AI_CONFIG = {
    "api_key": "",
    "base_url": "https://api.deepseek.com/v1",
    "model_name": "deepseek-chat",
}

# AI 用户设置的浏览器 localStorage 存储组件
AI_STORAGE_COMPONENT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "ai_storage_component")

# 病名编号：阿拉伯数字、全角数字、中文数字
_NUM_CHARS = "0-9０-９一二三四五六七八九十百零〇两"
# （一） / (1) / （1） 等括号编号
_PAREN_NUM_RE = re.compile(rf"^[（(]\s*[{_NUM_CHARS}\s]+?\s*[）)]\s*")
# 1. / 1、 / 1) / 一、 / 三． 等编号
_DOT_NUM_RE = re.compile(rf"^[{_NUM_CHARS}]+\s*[.．、,，)）:：]\s*")
# 数据中偶见的缺左括号写法，如 “四)神经精神疾病”
_UNBALANCED_PAREN_RE = re.compile(rf"^[（(]?\s*[{_NUM_CHARS}\s]+?\s*[）)]\s*")
# 去掉编号后可能残留的前导标点，如 “29..前列腺增生症”
_LEADING_PUNCT_RE = re.compile(r"^[.．、,，;；:：\-—_·\s]+")


# --- 1. 数据库解压与初始化 ---
def get_table_columns(conn, table_name):
    """读取数据表列名（中文表名同样适用）。"""
    return [row[1] for row in conn.execute(f'PRAGMA table_info("{table_name}")')]


def migrate_recipes_table(conn):
    """把旧版食谱表迁移为：功效、注意事项 两列，且注意事项位于功效之后、适合季节之前。"""
    cols = get_table_columns(conn, RECIPE_TABLE)
    if not cols:
        return
    if cols == RECIPE_COLUMNS:
        return

    def pick(*names):
        for name in names:
            if name in cols:
                return f'"{name}"'
        return "NULL"

    conn.execute("DROP TABLE IF EXISTS recipes__legacy_migration")
    conn.execute("ALTER TABLE recipes RENAME TO recipes__legacy_migration")
    conn.execute("""
        CREATE TABLE recipes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            菜名 TEXT,
            材料和制作 TEXT,
            功效 TEXT,
            注意事项 TEXT,
            适合季节 TEXT,
            适合年纪 TEXT,
            适合性别 TEXT,
            餐别 TEXT,
            版别 TEXT,
            出处 TEXT,
            编者及其身份 TEXT,
            品类 TEXT
        )
    """)
    select_expr = ", ".join([
        pick("id"),
        pick("菜名"),
        pick("材料和制作"),
        pick("功效", "功效和注意事项"),
        pick("注意事项", "季节功能"),
        pick("适合季节"),
        pick("适合年纪"),
        pick("适合性别"),
        pick("餐别"),
        pick("版别"),
        pick("出处"),
        pick("编者及其身份"),
        pick("品类"),
    ])
    conn.execute(f"""
        INSERT INTO recipes ({", ".join(f'"{c}"' for c in RECIPE_COLUMNS)})
        SELECT {select_expr} FROM recipes__legacy_migration
    """)
    conn.execute("DROP TABLE recipes__legacy_migration")


def rebuild_imported_table(conn, table_name, columns):
    """Excel 导入后重建标准表结构，恢复 id 主键与自增，避免后续增删改失效。"""
    existing = get_table_columns(conn, table_name)
    if not existing:
        return
    temp_name = f"{table_name}__imported"
    conn.execute(f'DROP TABLE IF EXISTS "{temp_name}"')
    conn.execute(f'ALTER TABLE "{table_name}" RENAME TO "{temp_name}"')
    col_defs = ", ".join(f'"{c}" TEXT' for c in columns if c != "id")
    conn.execute(f'CREATE TABLE "{table_name}" (id INTEGER PRIMARY KEY AUTOINCREMENT, {col_defs})')
    select_expr = ", ".join(f'"{c}"' if c in existing else "NULL" for c in columns)
    col_list = ", ".join(f'"{c}"' for c in columns)
    conn.execute(
        f'INSERT INTO "{table_name}" ({col_list}) SELECT {select_expr} FROM "{temp_name}"')
    conn.execute(f'DROP TABLE "{temp_name}"')


def ensure_schema(conn):
    """建表与旧库迁移，可重复执行。"""
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS query_logs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  ip_address TEXT, search_type TEXT, keyword TEXT,
                  query_time DATETIME DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS ai_config
                 (id INTEGER PRIMARY KEY CHECK (id = 1),
                  api_key TEXT, base_url TEXT, model_name TEXT)''')

    c.execute("SELECT COUNT(*) FROM ai_config")
    if c.fetchone()[0] == 0:
        c.execute(
            "INSERT INTO ai_config (id, api_key, base_url, model_name) VALUES (1, '', 'https://api.deepseek.com/v1', 'deepseek-chat')")

    c.execute(f'''CREATE TABLE IF NOT EXISTS "{VERIF_TABLE}"
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  方名 TEXT,
                  方剂 TEXT,
                  主治功能 TEXT,
                  案例 TEXT,
                  来源 TEXT,
                  备注 TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS recipes
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  菜名 TEXT,
                  材料和制作 TEXT,
                  功效 TEXT,
                  注意事项 TEXT,
                  适合季节 TEXT,
                  适合年纪 TEXT,
                  适合性别 TEXT,
                  餐别 TEXT,
                  版别 TEXT,
                  出处 TEXT,
                  编者及其身份 TEXT,
                  品类 TEXT)''')

    migrate_recipes_table(conn)
    conn.commit()


@st.cache_resource
def init_system():
    if not os.path.exists(DB_FILE):
        if os.path.exists(ZIP_FILE):
            try:
                with zipfile.ZipFile(ZIP_FILE, 'r') as zip_ref:
                    zip_ref.extractall(".")
            except Exception as e:
                return False, f"解压失败: {e}"
        else:
            return False, "未找到数据库文件或压缩包。"

    conn = sqlite3.connect(DB_FILE)
    try:
        ensure_schema(conn)
    except Exception as e:
        conn.close()
        return False, f"数据库结构初始化失败: {e}"
    conn.close()
    return True, "Success"


status, msg = init_system()
if not status:
    st.error(f"⚠️️ 系统初始化失败: {msg}")
    st.stop()


def get_connection():
    return sqlite3.connect(DB_FILE, check_same_thread=False)


@st.cache_resource
def _get_ai_storage_component():
    """浏览器 localStorage 存储组件；组件目录缺失时返回 None，页面仍可正常使用。"""
    if not os.path.isdir(AI_STORAGE_COMPONENT_DIR):
        return None
    try:
        return components.declare_component("tcm_ai_storage", path=AI_STORAGE_COMPONENT_DIR)
    except Exception:
        return None


def _save_ai_settings_callback():
    """保存按钮回调：把当前输入交给浏览器存储组件写入 localStorage。"""
    config = {
        "api_key": str(st.session_state.get("ai_user_api_key", "")).strip(),
        "base_url": str(st.session_state.get("ai_user_base_url", "")).strip(),
        "model_name": str(st.session_state.get("ai_user_model_name", "")).strip(),
    }
    st.session_state.ai_user_config = config
    st.session_state["ai_storage_action"] = "save"
    st.session_state["ai_storage_payload"] = config
    st.session_state["ai_storage_action_id"] = int(
        st.session_state.get("ai_storage_action_id", 0)) + 1


def _clear_ai_settings_callback():
    """清空按钮回调：让浏览器组件删除 localStorage，并重置输入框。"""
    st.session_state.ai_user_config = dict(DEFAULT_AI_CONFIG)
    st.session_state["ai_user_api_key"] = ""
    st.session_state["ai_user_base_url"] = DEFAULT_AI_CONFIG["base_url"]
    st.session_state["ai_user_model_name"] = DEFAULT_AI_CONFIG["model_name"]
    st.session_state["ai_storage_action"] = "clear"
    st.session_state["ai_storage_payload"] = None
    st.session_state["ai_storage_action_id"] = int(
        st.session_state.get("ai_storage_action_id", 0)) + 1


def _dismiss_ai_settings_notice():
    """用户重新编辑设置时，移除上一次的保存/清空提示。"""
    st.session_state.pop("ai_settings_notice", None)


def log_query(search_type, keyword):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("INSERT INTO query_logs (search_type, keyword) VALUES (?, ?)", (search_type, keyword))
        conn.commit()
        conn.close()
    except Exception:
        pass


def highlight_text(text, kw_list):
    if not isinstance(text, str) or not text:
        return ""
    for kw in kw_list:
        if kw and len(kw) > 1:
            text = text.replace(kw, f"<mark class='yellow-highlight'>{kw}</mark>")
    return text


def safe_text(value, default=""):
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def strip_leading_number(text):
    """去掉字符串开头的层级编号，如 (一)、1.、一、、四)。"""
    s = str(text or "").strip()
    for _ in range(4):
        new = _PAREN_NUM_RE.sub("", s, count=1)
        if new == s:
            new = _DOT_NUM_RE.sub("", s, count=1)
        if new == s:
            new = _UNBALANCED_PAREN_RE.sub("", s, count=1)
        if new == s:
            break
        s = new.strip()
    s = _LEADING_PUNCT_RE.sub("", s)
    return s.strip()


def normalize_disease_name(raw):
    """取多层病名的最后一层，去掉前面的编号，并清理空白。"""
    if raw is None:
        return ""
    try:
        if pd.isna(raw):
            return ""
    except (TypeError, ValueError):
        pass
    s = str(raw).strip().replace("\u3000", " ")
    if not s:
        return ""
    parts = [p.strip() for p in re.split(r"[/／]", s) if p.strip()]
    if not parts:
        return ""
    s = strip_leading_number(parts[-1])
    s = re.sub(r"\s+", "", s)
    return s.strip()


def render_formula_card(row):
    with st.container(border=True):
        st.markdown(f"### 🛡️ 【{safe_text(row.get('方剂名'), '未知')}】")
        st.markdown(
            f"**👨‍⚕️ 医家名:** {safe_text(row.get('大医名'), '未知')} &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"**🏷️ 方别:** {safe_text(row.get('方别'), '未知')} &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"**🩺 临床病名:** {safe_text(row.get('临床病名'), '未知')}")
        st.markdown(f"**📜 方剂详情:**<br>{safe_text(row.get('方剂详情'))}", unsafe_allow_html=True)
        st.markdown(f"**📝 临证提要:**<br>{safe_text(row.get('临证提要'), '无')}", unsafe_allow_html=True)
        st.markdown(f"**📖 病例详情:**<br>{safe_text(row.get('病例详情'), '无')}", unsafe_allow_html=True)
        if safe_text(row.get('按语')):
            st.markdown(f"**💡 按语:**<br>{safe_text(row.get('按语'))}", unsafe_allow_html=True)
        if safe_text(row.get('现代研究')):
            st.markdown(f"**🔬 现代研究:**<br>{safe_text(row.get('现代研究'))}", unsafe_allow_html=True)


def render_verif_card(row):
    with st.container(border=True):
        st.markdown(f"### 🧾 【{safe_text(row.get('方名'), '未知')}】")
        st.markdown(f"**📜 方剂:**<br>{safe_text(row.get('方剂'), '无')}", unsafe_allow_html=True)
        st.markdown(f"**🩺 主治功能:**<br>{safe_text(row.get('主治功能'), '无')}", unsafe_allow_html=True)
        st.markdown(f"**📖 案例:**<br>{safe_text(row.get('案例'), '无')}", unsafe_allow_html=True)
        st.markdown(
            f"**📚 来源:** {safe_text(row.get('来源'), '未注明')} &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"**🗒️ 备注:** {safe_text(row.get('备注'), '无')}")


def split_verif_indications(raw):
    """把“主治功能”拆成可选的病名/功能项，兼容多行、分号、顿号。"""
    if raw is None:
        return []
    try:
        if pd.isna(raw):
            return []
    except (TypeError, ValueError):
        pass
    parts = re.split(r"[\r\n；;、/／]+", str(raw))
    return [p.strip() for p in parts if p.strip()]


@st.cache_data(show_spinner=False)
def load_disease_options():
    """“屡试屡验方”（排除“被忽略的名方”）中清理、去重后的病名菜单。"""
    conn = get_connection()
    try:
        df = pd.read_sql(
            "SELECT 临床病名 FROM formulas WHERE TRIM(方别) = ?",
            conn,
            params=("屡试屡验方",),
        )
    finally:
        conn.close()
    names = {normalize_disease_name(x) for x in df["临床病名"].tolist()}
    names.discard("")
    return sorted(names)


@st.cache_data(show_spinner=False)
def load_disease_index():
    """病名 -> 记录 ID 的映射，供“方式二”精确检索。"""
    conn = get_connection()
    try:
        df = pd.read_sql("SELECT id, 临床病名 FROM formulas", conn)
    finally:
        conn.close()
    mapping = {}
    for record_id, raw in zip(df["id"].tolist(), df["临床病名"].tolist()):
        name = normalize_disease_name(raw)
        if name:
            mapping.setdefault(name, []).append(int(record_id))
    return mapping


@st.cache_data(show_spinner=False)
def load_verif_options():
    """各种验方表中去重后的主治功能/病名菜单。"""
    conn = get_connection()
    try:
        df = pd.read_sql(f'SELECT 主治功能 FROM "{VERIF_TABLE}"', conn)
    finally:
        conn.close()
    names = set()
    for raw in df["主治功能"].tolist():
        for part in split_verif_indications(raw):
            name = normalize_disease_name(part)
            if name:
                names.add(name)
    return sorted(names)


@st.cache_data(show_spinner=False)
def load_verif_index():
    """主治功能 -> 记录 ID 的映射，供各种验方的“方式二”检索。"""
    conn = get_connection()
    try:
        df = pd.read_sql(f'SELECT id, 主治功能 FROM "{VERIF_TABLE}"', conn)
    finally:
        conn.close()
    mapping = {}
    for record_id, raw in zip(df["id"].tolist(), df["主治功能"].tolist()):
        for part in split_verif_indications(raw):
            name = normalize_disease_name(part)
            if name:
                ids = mapping.setdefault(name, [])
                if int(record_id) not in ids:
                    ids.append(int(record_id))
    return mapping


def clear_search_caches():
    st.cache_data.clear()


# --- 2. 侧边栏与路由 ---
st.sidebar.markdown("<h1 style='text-align: center; font-size: 60px;'>☯️</h1>", unsafe_allow_html=True)
st.sidebar.title("📜 中医典藏系统V2.0")
page = st.sidebar.radio("模块导航", [
    "🔍 传世名方基础检索",
    "🤖 传世名方 AI 检索",
    "🧾 各种验方检索",
    "🍲 四季养生食谱检索",
    "⚙️ 典藏后台管理系统"
])

st.sidebar.markdown("""
<div class="disclaimer">
<b>⚠️ 免责声明：</b><br>
本系统纯属医学资料检索系统，不作辩证诊断，结果仅供参考，须在医生指导下使用，否则后果自负。
</div>
""", unsafe_allow_html=True)

# ==========================================
# 模块一：传世名方基础检索
# ==========================================
if page == "🔍 传世名方基础检索":
    st.title("🔍 传世名方基础检索")
    st.markdown("仅在数据表的 **【临床病名】** 列中检索。可输入疾病名称，也可从菜单选择疾病名称。")

    search_mode = st.radio(
        "检索方式",
        ["方式一：输入疾病名称检索", "方式二：选择疾病名称检索"],
        horizontal=True,
        key="formula_search_mode",
    )

    search_term = ""
    submitted = False

    if search_mode == "方式一：输入疾病名称检索":
        search_term = st.text_input(
            "💡 方式一：输入疾病名称检索（例如：感冒、十二指肠溃疡）",
            "",
            key="formula_text_term",
        )
        submitted = st.button("开始常规检索", type="primary", key="formula_text_search")
    else:
        disease_options = load_disease_options()
        if not disease_options:
            st.info("📉 暂无可选择的疾病名称，请先在后台导入“屡试屡验方”数据。")
        else:
            search_term = st.selectbox(
                "📋 方式二：选择疾病名称检索",
                disease_options,
                index=None,
                placeholder="请输入或选择疾病名称…",
                key="formula_select_term",
            )
            submitted = st.button("开始常规检索", type="primary", key="formula_select_search")

    if submitted:
        if not search_term or not str(search_term).strip():
            st.warning("请先输入或选择疾病名称。")
        else:
            search_term = str(search_term).strip()
            log_query("基础名方检索", search_term)
            conn = get_connection()
            try:
                if search_mode == "方式一：输入疾病名称检索":
                    # 只检索“临床病名”列，不再匹配方剂名、病例详情等其它列
                    df_result = pd.read_sql(
                        "SELECT * FROM formulas WHERE 临床病名 LIKE ? LIMIT 100",
                        conn,
                        params=(f"%{search_term}%",),
                    )
                else:
                    matched_ids = load_disease_index().get(search_term, [])[:100]
                    if not matched_ids:
                        df_result = pd.DataFrame()
                    else:
                        placeholders = ",".join("?" * len(matched_ids))
                        df_result = pd.read_sql(
                            f"SELECT * FROM formulas WHERE id IN ({placeholders}) LIMIT 100",
                            conn,
                            params=tuple(matched_ids),
                        )
            finally:
                conn.close()

            if df_result.empty:
                st.info("📉 浩瀚医海，未寻得完全匹配的记载。")
            else:
                st.success(f"✅ 检索完毕，共得 {len(df_result)} 则良方：")
                for _, row in df_result.iterrows():
                    render_formula_card(row)

# ==========================================
# 模块二：传世名方 AI 智能检索
# ==========================================
elif page == "🤖 传世名方 AI 检索":
    st.title("🤖 AI 智能检索")
    st.markdown(
        "基于大模型的深度语义解析。**声明：AI 严格限定于本地《传世名方》数据库内进行比对筛查，宁缺毋滥，拒绝凭空伪造。**")

    if "ai_user_config" not in st.session_state:
        st.session_state.ai_user_config = dict(DEFAULT_AI_CONFIG)
    if "ai_storage_loaded" not in st.session_state:
        st.session_state.ai_storage_loaded = False
    if "ai_storage_action_id" not in st.session_state:
        st.session_state.ai_storage_action_id = 0

    action = st.session_state.pop("ai_storage_action", "")
    payload = st.session_state.pop("ai_storage_payload", None)
    action_id = int(st.session_state.get("ai_storage_action_id", 0))

    storage_component = _get_ai_storage_component()
    storage_result = None
    component_error = ""
    if storage_component is not None:
        try:
            storage_result = storage_component(
                action=action,
                payload=payload,
                action_id=action_id,
                key="ai_storage_bridge",
                default=None,
            )
        except Exception as e:
            component_error = str(e)
            storage_component = None

    if action:
        if storage_component is None:
            st.session_state["ai_settings_notice"] = (
                "warning",
                f"⚠️ 浏览器存储组件不可用，设置仅在本次会话有效。{component_error}".strip(),
            )
        elif action == "save":
            st.session_state["ai_settings_notice"] = (
                "success",
                "✅ AI 设置已保存到当前浏览器，刷新或重新打开页面后仍会保留。",
            )
        else:
            st.session_state["ai_settings_notice"] = (
                "success",
                "✅ 已清空当前浏览器中保存的 AI 设置。",
            )
    elif not st.session_state.ai_storage_loaded and isinstance(storage_result, dict):
        loaded_settings = storage_result.get("settings")
        if isinstance(loaded_settings, dict):
            loaded_config = dict(DEFAULT_AI_CONFIG)
            for key in loaded_config:
                value = loaded_settings.get(key)
                if isinstance(value, str):
                    loaded_config[key] = value.strip()
            st.session_state.ai_user_config = loaded_config
            st.session_state["ai_user_api_key"] = loaded_config["api_key"]
            st.session_state["ai_user_base_url"] = loaded_config["base_url"]
            st.session_state["ai_user_model_name"] = loaded_config["model_name"]
        st.session_state.ai_storage_loaded = True

    notice = st.session_state.get("ai_settings_notice")
    if notice:
        notice_kind, notice_text = notice
        getattr(st, notice_kind)(notice_text)

    saved_config = st.session_state.ai_user_config
    with st.expander("⚙️ AI 引擎设置（用户设置）", expanded=not bool(saved_config.get("api_key"))):
        st.caption("设置保存在当前浏览器的本地存储（localStorage）中，刷新或关闭后仍会保留；仅对当前浏览器和当前访问地址有效。可随时修改、保存或清空。")
        for widget_key, widget_value in (
            ("ai_user_api_key", saved_config.get("api_key", "")),
            ("ai_user_base_url", saved_config.get("base_url", DEFAULT_AI_CONFIG["base_url"])),
            ("ai_user_model_name", saved_config.get("model_name", DEFAULT_AI_CONFIG["model_name"])),
        ):
            if widget_key not in st.session_state:
                st.session_state[widget_key] = widget_value
        api_key = st.text_input("🔑 我的 API Key", type="password", key="ai_user_api_key",
                                on_change=_dismiss_ai_settings_notice)
        base_url = st.text_input("🌐 Base URL (接口地址)", key="ai_user_base_url",
                                 on_change=_dismiss_ai_settings_notice)
        model_name = st.text_input("🧠 调用的模型名称 (Model Name)", key="ai_user_model_name",
                                   on_change=_dismiss_ai_settings_notice)
        save_col, clear_col = st.columns(2)
        with save_col:
            st.button("💾 保存我的 AI 设置", key="ai_user_save", on_click=_save_ai_settings_callback)
        with clear_col:
            st.button("🗑️ 清空我的 AI 设置", key="ai_user_clear", on_click=_clear_ai_settings_callback)

    condition_desc = st.text_area(
        "✍️ 请详细描述疾病情况 (如: 胃痛时而剧烈，隐隐作痛，伴有头晕不眠，舌淡白...)",
        height=150,
        key="ai_condition_desc",
    )

    if st.button("🧠 提交 AI 深度匹配", type="primary", key="ai_submit"):
        if not condition_desc.strip():
            st.warning("请详细描述病症！")
        elif not api_key or not api_key.strip():
            st.error("⚠️ AI 尚未配置，请先在上方【AI 引擎设置（用户设置）】中填写您自己的 API Key。")
        else:
            with st.spinner("AI 正在典藏库中为您彻查比对...这可能需要十几秒，请稍候。"):
                conn = get_connection()
                try:
                    df_all = pd.read_sql(
                        "SELECT id, 方剂名, 临床病名, 方剂详情, 病例详情 FROM formulas", conn)
                finally:
                    conn.close()

                corpus = df_all.to_dict(orient="records")
                corpus_str = json.dumps(corpus[:100], ensure_ascii=False)

                system_prompt = """你是一位资深严谨的中医专家，请根据你所掌握的中医知识和经验，针对用户的【病情描述】进行全面的综合分析或将【病情描述】切成分词进行文字匹配，严格按照以下规则在我提供的<数据库语料>中推荐合适的方剂：
                    规则1：你只能使用我提供的<数据库语料>来分析或文字匹配检索，绝对不能编造外部知识！如果确实没有合适的，请返回空列表。
                    规则2：根据用户的【病情描述】，在语料中全面筛查分析，或将【病情描述】切成分词，在我提供的<数据库语料>中进行文字匹配，选择合适或匹配的方剂，按照合适度或匹配度减序排序。
                    规则3：输出严格的JSON。格式: {"matched_ids": [1, 5], "highlight_keywords": ["胃痛", "舌淡白"]}"""

                user_prompt = f"<数据库语料>\n{corpus_str}\n</数据库语料>\n\n用户的病情：{condition_desc}"

                try:
                    # 延迟导入：即使 AI 依赖未安装或版本异常，基础检索模块仍可正常使用
                    from openai import OpenAI

                    client = OpenAI(
                        api_key=api_key.strip(),
                        base_url=base_url.strip() or None,
                    )
                    response = client.chat.completions.create(
                        model=model_name.strip() or "deepseek-chat",
                        messages=[{"role": "system", "content": system_prompt},
                                  {"role": "user", "content": user_prompt}],
                        temperature=0.1,
                        response_format={"type": "json_object"}
                    )
                    ai_result = json.loads(response.choices[0].message.content)
                    matched_ids = ai_result.get("matched_ids", [])
                    keywords = ai_result.get("highlight_keywords", [])
                    log_query("AI深度检索", condition_desc)

                    if not matched_ids:
                        st.info("🤖 经过系统缜密分析，本地传世名方库中暂无与此高度契合的方剂。")
                    else:
                        st.success(f"🤖 已为您筛出最契合的 {len(matched_ids)} 剂良方（高亮显示病机词）：")
                        conn = get_connection()
                        try:
                            placeholders = ",".join("?" * len(matched_ids))
                            df_matched = pd.read_sql(
                                f"SELECT * FROM formulas WHERE id IN ({placeholders})",
                                conn,
                                params=tuple(matched_ids),
                            )
                        finally:
                            conn.close()

                        df_matched['id_cat'] = pd.Categorical(
                            df_matched['id'], categories=matched_ids, ordered=True)
                        df_matched = df_matched.sort_values('id_cat')

                        for _, row in df_matched.iterrows():
                            with st.container(border=True):
                                st.markdown(f"### 🛡️ AI 推荐：【{safe_text(row.get('方剂名'), '未知')}】")
                                st.markdown(
                                    f"**👨‍⚕️ 医家:** {safe_text(row.get('大医名'))} &nbsp;|&nbsp; "
                                    f"**🏷️ 方别:** {safe_text(row.get('方别'))} &nbsp;|&nbsp; "
                                    f"**🩺 适用病名:** {safe_text(row.get('临床病名'))}")
                                st.markdown(
                                    f"**📜 方剂详情:**<br>{highlight_text(str(row.get('方剂详情', '')), keywords)}",
                                    unsafe_allow_html=True)
                                st.markdown(
                                    f"**📝 临证提要:**<br>{highlight_text(str(row.get('临证提要', '')), keywords)}",
                                    unsafe_allow_html=True)
                                st.markdown(
                                    f"**📖 病例详情:**<br>{highlight_text(str(row.get('病例详情', '')), keywords)}",
                                    unsafe_allow_html=True)
                                if safe_text(row.get('按语')):
                                    st.markdown(
                                        f"**💡 按语:**<br>{highlight_text(str(row.get('按语')), keywords)}",
                                        unsafe_allow_html=True)
                                if safe_text(row.get('现代研究')):
                                    st.markdown(
                                        f"**🔬 现代研究:**<br>{highlight_text(str(row.get('现代研究')), keywords)}",
                                        unsafe_allow_html=True)
                except Exception as e:
                    st.error(f"AI 调用失败，请检查配置与网络：{e}")

# ==========================================
# 模块三：各种验方检索
# ==========================================
elif page == "🧾 各种验方检索":
    st.title("🧾 各种验方检索")
    st.markdown("在 **【各种验方表】** 中检索。支持输入疾病名称，也支持从菜单中选择疾病名称（按主治功能整理）。")

    conn = get_connection()
    try:
        verif_count = pd.read_sql(f'SELECT COUNT(*) AS c FROM "{VERIF_TABLE}"', conn).iloc[0]["c"]
    finally:
        conn.close()

    if not verif_count:
        st.info("📭 【各种验方表】暂无数据。请进入【典藏后台管理系统 → 📁 批量导入】导入数据后再检索。")

    search_mode = st.radio(
        "检索方式",
        ["方式一：输入疾病名称检索", "方式二：选择疾病名称检索"],
        horizontal=True,
        key="verif_search_mode",
    )

    search_term = ""
    submitted = False

    if search_mode == "方式一：输入疾病名称检索":
        search_term = st.text_input(
            "💡 方式一：输入疾病名称检索（例如：感冒、咳嗽，也可输入方名）",
            "",
            key="verif_text_term",
        )
        submitted = st.button("开始验方检索", type="primary", key="verif_text_search")
    else:
        verif_options = load_verif_options()
        if not verif_options:
            st.info("📉 暂无可选择的疾病名称，请先在后台导入“各种验方表”数据。")
        else:
            search_term = st.selectbox(
                "📋 方式二：选择疾病名称检索",
                verif_options,
                index=None,
                placeholder="请输入或选择疾病名称…",
                key="verif_select_term",
            )
            submitted = st.button("开始验方检索", type="primary", key="verif_select_search")

    if submitted:
        if not search_term or not str(search_term).strip():
            st.warning("请先输入或选择疾病名称。")
        else:
            search_term = str(search_term).strip()
            log_query("各种验方检索", search_term)
            conn = get_connection()
            try:
                if search_mode == "方式一：输入疾病名称检索":
                    df_result = pd.read_sql(
                        f'SELECT * FROM "{VERIF_TABLE}" '
                        "WHERE 主治功能 LIKE ? OR 方名 LIKE ? LIMIT 100",
                        conn,
                        params=(f"%{search_term}%", f"%{search_term}%"),
                    )
                else:
                    matched_ids = load_verif_index().get(search_term, [])[:100]
                    if not matched_ids:
                        df_result = pd.DataFrame()
                    else:
                        placeholders = ",".join("?" * len(matched_ids))
                        df_result = pd.read_sql(
                            f'SELECT * FROM "{VERIF_TABLE}" WHERE id IN ({placeholders}) LIMIT 100',
                            conn,
                            params=tuple(matched_ids),
                        )
            finally:
                conn.close()

            if df_result.empty:
                st.info("📉 未寻得匹配的验方记载。")
            else:
                st.success(f"✅ 检索完毕，共得 {len(df_result)} 则验方：")
                for _, row in df_result.iterrows():
                    render_verif_card(row)

# ==========================================
# 模块四：养生食谱检索
# ==========================================
elif page == "🍲 四季养生食谱检索":
    st.title("🍲 养生食谱数据库")
    st.markdown("多维度精准匹配，顺应四时养生。不填的条件默认不作限制。")

    with st.container(border=True):
        col1, col2 = st.columns(2)
        with col1:
            cailiao = st.text_input("🥦 食材用料 (如: 猪肉、山药)", key="recipe_cailiao")
            gongxiao = st.text_input("✨ 核心功效 (如: 健脾、润肺)", key="recipe_gongxiao")
            nianji = st.text_input("👴 适用年龄 (如: 老年、儿童)", key="recipe_nianji")
        with col2:
            zhuyi = st.text_input("⚠️ 注意事项 (如: 忌辛辣、脾胃虚寒少食)", key="recipe_zhuyi")
            xingbie = st.text_input("👫 适用性别 (如: 男、女)", key="recipe_xingbie")
            pinlei = st.text_input("🥘 菜式品类 (如: 汤羹、粥)", key="recipe_pinlei")

        if st.button("查询养生食谱", type="primary", key="recipe_search"):
            query = "SELECT * FROM recipes WHERE 1=1"
            params = []
            if cailiao:
                query += " AND 材料和制作 LIKE ?"
                params.append(f'%{cailiao}%')
            if gongxiao:
                query += " AND 功效 LIKE ?"
                params.append(f'%{gongxiao}%')
            if zhuyi:
                query += " AND 注意事项 LIKE ?"
                params.append(f'%{zhuyi}%')
            if nianji:
                query += " AND 适合年纪 LIKE ?"
                params.append(f'%{nianji}%')
            if xingbie:
                query += " AND 适合性别 LIKE ?"
                params.append(f'%{xingbie}%')
            if pinlei:
                query += " AND 品类 LIKE ?"
                params.append(f'%{pinlei}%')
            query += " LIMIT 150"  # 限制150条防卡顿

            conn = get_connection()
            try:
                df_result = pd.read_sql(query, conn, params=tuple(params))
            finally:
                conn.close()

            log_query("食谱检索", f"{cailiao}|{gongxiao}|{zhuyi}")

            if df_result.empty:
                st.info("📉 未寻得符合全部条件的食谱，请尝试精简检索词。")
            else:
                st.success(f"✅ 寻得 {len(df_result)} 道养生佳肴：")
                for _, row in df_result.iterrows():
                    with st.expander(f"🍲 【{safe_text(row.get('菜名'), '未知')}】 | 类: {safe_text(row.get('品类'))}"):
                        st.markdown(f"**🥦 材料与制作:**\n {safe_text(row.get('材料和制作'))}")
                        st.markdown(f"**✨ 功效:**\n {safe_text(row.get('功效'))}")
                        st.markdown(f"**⚠️ 注意事项:**\n {safe_text(row.get('注意事项'))}")
                        st.markdown("---")
                        c1, c2, c3 = st.columns(3)
                        c1.markdown(f"**👴 年纪:** {safe_text(row.get('适合年纪'), '老少皆宜')}")
                        c2.markdown(f"**👫 性别:** {safe_text(row.get('适合性别'), '男女皆宜')}")
                        c3.markdown(f"**🌸 季节:** {safe_text(row.get('适合季节'), '四季皆宜')}")

# ==========================================
# 模块五：后台管理系统
# ==========================================
elif page == "⚙️ 典藏后台管理系统":
    st.title("⚙️ 系统中枢及数据管理")

    if "admin_auth" not in st.session_state:
        st.session_state.admin_auth = False

    if not st.session_state.admin_auth:
        pwd = st.text_input("🔑 请输入系统超级管理员密码", type="password", key="admin_pwd")
        if st.button("进入中枢", key="admin_login"):
            if pwd == "123":
                st.session_state.admin_auth = True
                st.rerun()
            else:
                st.error("密码错误！")
    else:
        st.success("✅ 身份验证通过：田 夫 (为了系统流畅，请规范操作)")

        tab_stat, tab_edit, tab_import, tab_danger = st.tabs([
            "📊 数据统计", "✏️ 数据维护(增删)", "📁 批量导入", "⚠️ 高危操作"
        ])

        with tab_stat:
            st.subheader("平台数据态势")
            conn = get_connection()
            try:
                num_formulas = pd.read_sql("SELECT COUNT(*) as c FROM formulas", conn).iloc[0]['c']
                num_recipes = pd.read_sql("SELECT COUNT(*) as c FROM recipes", conn).iloc[0]['c']
                num_verif = pd.read_sql(f'SELECT COUNT(*) as c FROM "{VERIF_TABLE}"', conn).iloc[0]['c']
                num_logs = pd.read_sql("SELECT COUNT(*) as c FROM query_logs", conn).iloc[0]['c']
            finally:
                conn.close()
            sc1, sc2, sc3, sc4 = st.columns(4)
            sc1.metric("📚 传世名方总数", num_formulas)
            sc2.metric("🧾 各种验方总数", num_verif)
            sc3.metric("🍲 养生食谱总数", num_recipes)
            sc4.metric("👣 历史总检索次数", num_logs)

            st.markdown("### 📝 最近访客检索日志")
            conn = get_connection()
            try:
                logs_df = pd.read_sql(
                    "SELECT id as 序号, query_time as 检索时间, search_type as 检索模块, keyword as 检索词 "
                    "FROM query_logs ORDER BY id DESC LIMIT 50",
                    conn)
            finally:
                conn.close()
            st.dataframe(logs_df)

        with tab_edit:
            st.subheader("✏️ 数据精确定向维护")
            st.warning("⚠️ 数据库体积庞大，全量铺开会导致浏览器崩溃卡死。请通过下方表单精确完成录入、修改与删除。")

            action_type = st.radio(
                "请选择执行的操作",
                ["➕ 新增记录", "🔍 搜索与修改", "🗑️ 定向删除"],
                horizontal=True,
                key="admin_action",
            )

            if action_type == "➕ 新增记录":
                tbl = st.selectbox(
                    "目标表",
                    ["formulas (名方)", "recipes (食谱)", "各种验方表 (验方)"],
                    key="admin_insert_table",
                )
                with st.form("insert_f"):
                    if "formulas" in tbl:
                        st.info("正在录入：传世名方")
                        f_name = st.text_input("方剂名*")
                        b_name = st.text_input("临床病名*")
                        d_name = st.text_input("大医名")
                        det = st.text_area("方剂详情")
                        cas = st.text_area("病例详情")
                        sumry = st.text_area("临证提要")
                        if st.form_submit_button("保存至名方库"):
                            if f_name and b_name:
                                conn = get_connection()
                                conn.execute(
                                    "INSERT INTO formulas (方剂名, 临床病名, 大医名, 方剂详情, 病例详情, 临证提要) VALUES (?,?,?,?,?,?)",
                                    (f_name, b_name, d_name, det, cas, sumry))
                                conn.commit()
                                conn.close()
                                clear_search_caches()
                                st.success("新增成功！")
                            else:
                                st.error("必填项不可为空！")
                    elif "recipes" in tbl:
                        st.info("正在录入：养生食谱")
                        r_name = st.text_input("菜名*")
                        r_type = st.text_input("品类")
                        r_mat = st.text_area("材料和制作")
                        r_eff = st.text_area("功效")
                        r_note = st.text_area("注意事项")
                        if st.form_submit_button("保存至食谱库"):
                            if r_name:
                                conn = get_connection()
                                conn.execute(
                                    "INSERT INTO recipes (菜名, 品类, 材料和制作, 功效, 注意事项) VALUES (?,?,?,?,?)",
                                    (r_name, r_type, r_mat, r_eff, r_note))
                                conn.commit()
                                conn.close()
                                st.success("新增成功！")
                            else:
                                st.error("菜名为必填项！")
                    else:
                        st.info("正在录入：各种验方")
                        v_name = st.text_input("方名*")
                        v_recipe = st.text_area("方剂")
                        v_indication = st.text_area("主治功能")
                        v_case = st.text_area("案例")
                        v_source = st.text_input("来源")
                        v_note = st.text_input("备注")
                        if st.form_submit_button("保存至验方库"):
                            if v_name:
                                conn = get_connection()
                                conn.execute(
                                    f'INSERT INTO "{VERIF_TABLE}" (方名, 方剂, 主治功能, 案例, 来源, 备注) '
                                    "VALUES (?,?,?,?,?,?)",
                                    (v_name, v_recipe, v_indication, v_case, v_source, v_note))
                                conn.commit()
                                conn.close()
                                clear_search_caches()
                                st.success("新增成功！")
                            else:
                                st.error("方名为必填项！")

            elif action_type == "🔍 搜索与修改":
                st.markdown("通过关键字定位数据并进行编辑更新。")
                edit_tbl = st.selectbox(
                    "修改目标表",
                    ["formulas (名方)", "recipes (食谱)", "各种验方表 (验方)"],
                    key="admin_edit_table",
                )
                if "formulas" in edit_tbl:
                    real_tbl = FORMULA_TABLE
                elif "recipes" in edit_tbl:
                    real_tbl = RECIPE_TABLE
                else:
                    real_tbl = VERIF_TABLE

                search_kw = st.text_input("🔍 输入检索词 (如方名、菜名、病名等以查找)", key="admin_edit_kw")

                if search_kw.strip():
                    conn = get_connection()
                    try:
                        if real_tbl == FORMULA_TABLE:
                            query = ("SELECT id, 方剂名, 临床病名, 大医名 FROM formulas "
                                     "WHERE 方剂名 LIKE ? OR 临床病名 LIKE ? LIMIT 20")
                        elif real_tbl == RECIPE_TABLE:
                            query = ("SELECT id, 菜名, 品类 FROM recipes "
                                     "WHERE 菜名 LIKE ? OR 功效 LIKE ? OR 注意事项 LIKE ? LIMIT 20")
                        else:
                            query = (f'SELECT id, 方名, 主治功能 FROM "{VERIF_TABLE}" '
                                     "WHERE 方名 LIKE ? OR 主治功能 LIKE ? LIMIT 20")
                        search_res = pd.read_sql(
                            query, conn,
                            params=tuple([f'%{search_kw}%'] * query.count("?")))
                    finally:
                        conn.close()

                    if search_res.empty:
                        st.info("未找到匹配的记录。")
                    else:
                        st.write(f"找到 {len(search_res)} 条关联记录 (最多显示前20条)：")
                        st.dataframe(search_res, hide_index=True)

                        edit_id = st.number_input("请输入您要修改的记录 ID", min_value=0, step=1, value=0)

                        if edit_id > 0:
                            conn = get_connection()
                            try:
                                record = pd.read_sql(
                                    f'SELECT * FROM "{real_tbl}" WHERE id=?', conn, params=(edit_id,))
                            finally:
                                conn.close()

                            if not record.empty:
                                row = record.iloc[0]
                                with st.form("update_form"):
                                    if real_tbl == FORMULA_TABLE:
                                        st.info(f"正在修改 ID: {edit_id} 的名方")
                                        u_f_name = st.text_input("方剂名*", value=safe_text(row.get('方剂名')))
                                        u_b_name = st.text_input("临床病名*", value=safe_text(row.get('临床病名')))
                                        u_d_name = st.text_input("大医名", value=safe_text(row.get('大医名')))
                                        u_det = st.text_area("方剂详情", value=safe_text(row.get('方剂详情')))
                                        u_cas = st.text_area("病例详情", value=safe_text(row.get('病例详情')))
                                        u_sumry = st.text_area("临证提要", value=safe_text(row.get('临证提要')))

                                        if st.form_submit_button("💾 保存名方修改", type="primary"):
                                            if u_f_name and u_b_name:
                                                conn = get_connection()
                                                conn.execute(
                                                    "UPDATE formulas SET 方剂名=?, 临床病名=?, 大医名=?, 方剂详情=?, 病例详情=?, 临证提要=? WHERE id=?",
                                                    (u_f_name, u_b_name, u_d_name, u_det, u_cas, u_sumry, edit_id))
                                                conn.commit()
                                                conn.close()
                                                clear_search_caches()
                                                st.success("名方记录修改成功！")
                                            else:
                                                st.error("必填项不可为空！")
                                    elif real_tbl == RECIPE_TABLE:
                                        st.info(f"正在修改 ID: {edit_id} 的食谱")
                                        u_r_name = st.text_input("菜名*", value=safe_text(row.get('菜名')))
                                        u_r_type = st.text_input("品类", value=safe_text(row.get('品类')))
                                        u_r_mat = st.text_area("材料和制作", value=safe_text(row.get('材料和制作')))
                                        u_r_eff = st.text_area("功效", value=safe_text(row.get('功效')))
                                        u_r_note = st.text_area("注意事项", value=safe_text(row.get('注意事项')))

                                        if st.form_submit_button("💾 保存食谱修改", type="primary"):
                                            if u_r_name:
                                                conn = get_connection()
                                                conn.execute(
                                                    "UPDATE recipes SET 菜名=?, 品类=?, 材料和制作=?, 功效=?, 注意事项=? WHERE id=?",
                                                    (u_r_name, u_r_type, u_r_mat, u_r_eff, u_r_note, edit_id))
                                                conn.commit()
                                                conn.close()
                                                st.success("食谱记录修改成功！")
                                            else:
                                                st.error("菜名为必填项！")
                                    else:
                                        st.info(f"正在修改 ID: {edit_id} 的验方")
                                        u_v_name = st.text_input("方名*", value=safe_text(row.get('方名')))
                                        u_v_recipe = st.text_area("方剂", value=safe_text(row.get('方剂')))
                                        u_v_indication = st.text_area("主治功能", value=safe_text(row.get('主治功能')))
                                        u_v_case = st.text_area("案例", value=safe_text(row.get('案例')))
                                        u_v_source = st.text_input("来源", value=safe_text(row.get('来源')))
                                        u_v_note = st.text_input("备注", value=safe_text(row.get('备注')))

                                        if st.form_submit_button("💾 保存验方修改", type="primary"):
                                            if u_v_name:
                                                conn = get_connection()
                                                conn.execute(
                                                    f'UPDATE "{VERIF_TABLE}" SET 方名=?, 方剂=?, 主治功能=?, 案例=?, 来源=?, 备注=? WHERE id=?',
                                                    (u_v_name, u_v_recipe, u_v_indication, u_v_case, u_v_source, u_v_note, edit_id))
                                                conn.commit()
                                                conn.close()
                                                clear_search_caches()
                                                st.success("验方记录修改成功！")
                                            else:
                                                st.error("方名为必填项！")
                            else:
                                st.warning("未找到该 ID 对应的记录，请核对后输入。")

            elif action_type == "🗑️ 定向删除":
                st.markdown("通过 ID 精确定位数据并删除，确保系统响应极速不卡顿。")
                del_tbl = st.selectbox(
                    "目标表", [FORMULA_TABLE, RECIPE_TABLE, VERIF_TABLE], key="admin_del_table")
                del_id = st.number_input(
                    f"请输入要删除的 {del_tbl} 记录的 ID", min_value=1, step=1, key="admin_del_id")

                # 预览要删除的数据
                conn = get_connection()
                try:
                    preview = pd.read_sql(
                        f'SELECT * FROM "{del_tbl}" WHERE id=?', conn, params=(del_id,))
                finally:
                    conn.close()
                if not preview.empty:
                    st.dataframe(preview)
                    if st.button("🚨 确认删除此记录", key="admin_del_confirm"):
                        conn = get_connection()
                        conn.execute(f'DELETE FROM "{del_tbl}" WHERE id=?', (del_id,))
                        conn.commit()
                        conn.close()
                        clear_search_caches()
                        st.success("已成功删除！")
                        st.rerun()
                else:
                    st.info("未找到此 ID 对应的数据。")

        with tab_import:
            st.subheader("📥 Excel 批量智能导入")
            uploaded_file = st.file_uploader("请上传待导入的 Excel 文件 (.xlsx)", type=["xlsx", "xls"])
            target_label = st.radio(
                "导入目标库",
                ["formulas (名方)", "recipes (食谱)", "各种验方表 (验方)"],
                key="admin_import_table",
            )
            if "formulas" in target_label:
                target_table = FORMULA_TABLE
            elif "recipes" in target_label:
                target_table = RECIPE_TABLE
            else:
                target_table = VERIF_TABLE

            if uploaded_file is not None:
                xls = pd.ExcelFile(uploaded_file)
                st.write(f"📂 检测到 {len(xls.sheet_names)} 个工作表")
                if st.button("开始批量读取并智能去重导入", type="primary", key="admin_import_run"):
                    try:
                        conn = get_connection()
                        if target_table == VERIF_TABLE:
                            df_list = [pd.read_excel(xls, sheet_name=s) for s in xls.sheet_names]
                            new_data = pd.concat(df_list, ignore_index=True)
                            new_data.columns = [str(c).strip() for c in new_data.columns]
                            for col in VERIF_COLUMNS:
                                if col not in new_data.columns:
                                    new_data[col] = ""
                            new_data = new_data[VERIF_COLUMNS].fillna("")

                            old_df = pd.read_sql(
                                f'SELECT 方名, 主治功能 FROM "{VERIF_TABLE}"', conn)
                            existing = {
                                (safe_text(r["方名"]), safe_text(r["主治功能"]))
                                for _, r in old_df.iterrows()
                            }
                            inserted = 0
                            for _, r in new_data.iterrows():
                                name = safe_text(r["方名"])
                                if not name:
                                    continue
                                key = (name, safe_text(r["主治功能"]))
                                if key in existing:
                                    continue
                                conn.execute(
                                    f'INSERT INTO "{VERIF_TABLE}" (方名, 方剂, 主治功能, 案例, 来源, 备注) '
                                    "VALUES (?,?,?,?,?,?)",
                                    (name, safe_text(r["方剂"]), safe_text(r["主治功能"]),
                                     safe_text(r["案例"]), safe_text(r["来源"]), safe_text(r["备注"])))
                                existing.add(key)
                                inserted += 1
                            conn.commit()
                            total = conn.execute(
                                f'SELECT COUNT(*) FROM "{VERIF_TABLE}"').fetchone()[0]
                            conn.close()
                            clear_search_caches()
                            st.success(f"🎉 导入成功！新增 {inserted} 条，过滤重复后验方库中共存有 {total} 条数据。")
                        else:
                            old_df = pd.read_sql(f'SELECT * FROM "{target_table}"', conn)
                            df_list = [pd.read_excel(xls, sheet_name=s) for s in xls.sheet_names]
                            new_data = pd.concat(df_list, ignore_index=True)
                            new_data.columns = [str(c).strip() for c in new_data.columns]
                            # 忽略上传文件中的 id 列，新增记录由数据库统一分配主键
                            if "id" in new_data.columns:
                                new_data = new_data.drop(columns=["id"])

                            # 兼容旧版食谱表头：功效和注意事项 -> 功效；季节功能 -> 注意事项
                            if target_table == RECIPE_TABLE:
                                if "功效和注意事项" in new_data.columns:
                                    if "功效" not in new_data.columns:
                                        new_data.rename(columns={"功效和注意事项": "功效"}, inplace=True)
                                    else:
                                        new_data["功效"] = new_data["功效"].where(
                                            new_data["功效"].fillna("").astype(str).str.strip() != "",
                                            new_data["功效和注意事项"])
                                        new_data.drop(columns=["功效和注意事项"], inplace=True)
                                if "季节功能" in new_data.columns:
                                    if "注意事项" not in new_data.columns:
                                        new_data.rename(columns={"季节功能": "注意事项"}, inplace=True)
                                    else:
                                        new_data["注意事项"] = new_data["注意事项"].where(
                                            new_data["注意事项"].fillna("").astype(str).str.strip() != "",
                                            new_data["季节功能"])
                                        new_data.drop(columns=["季节功能"], inplace=True)

                            combined_df = pd.concat([old_df, new_data], ignore_index=True)

                            if target_table == FORMULA_TABLE and '方剂名' in combined_df.columns:
                                combined_df.drop_duplicates(subset=['方剂名', '临床病名'], keep='last', inplace=True)
                            elif target_table == RECIPE_TABLE and '菜名' in combined_df.columns:
                                combined_df.drop_duplicates(subset=['菜名'], keep='last', inplace=True)

                            combined_df.to_sql(target_table, conn, if_exists="replace", index=False)
                            rebuild_imported_table(conn, target_table, TABLE_COLUMNS[target_table])
                            conn.commit()
                            conn.close()
                            clear_search_caches()
                            st.success(f"🎉 导入成功！过滤重复后库中共存有 {len(combined_df)} 条数据。")
                    except Exception as e:
                        st.error(f"导入出错，可能是文件格式不匹配: {e}")

        with tab_danger:
            st.subheader("☢️ 高危指令区")
            clear_table = st.selectbox(
                "选择要物理清空的数据表",
                [FORMULA_TABLE, RECIPE_TABLE, VERIF_TABLE, "query_logs"],
                key="admin_clear_table",
            )
            confirm_text = st.text_input(
                f"如果您确切明白后果，请在此处手动输入：确认清空{clear_table}", key="admin_clear_confirm")
            if st.button("🚨 强制执行一键清空", key="admin_clear_run"):
                if confirm_text == f"确认清空{clear_table}":
                    conn = get_connection()
                    conn.execute(f'DELETE FROM "{clear_table}"')
                    conn.commit()
                    conn.close()
                    clear_search_caches()
                    st.success(f"💀 核心指令已下达，【{clear_table}】已被永久清空。")
                else:
                    st.warning("防误触锁生效：口令不正确。")
