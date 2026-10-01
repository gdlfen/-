import streamlit as st
import pandas as pd
import sqlite3
import os
import zipfile
import json
from openai import OpenAI

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


# --- 1. 数据库解压与初始化 ---
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

    # 确保辅助表存在
    conn = sqlite3.connect(DB_FILE)
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

    conn.commit()
    conn.close()
    return True, "Success"


status, msg = init_system()
if not status:
    st.error(f"⚠️️ 系统初始化失败: {msg}")
    st.stop()


def get_connection():
    return sqlite3.connect(DB_FILE, check_same_thread=False)


def log_query(search_type, keyword):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("INSERT INTO query_logs (search_type, keyword) VALUES (?, ?)", (search_type, keyword))
        conn.commit()
        conn.close()
    except:
        pass


def highlight_text(text, kw_list):
    if not isinstance(text, str) or not text: return ""
    for kw in kw_list:
        if kw and len(kw) > 1:
            text = text.replace(kw, f"<mark class='yellow-highlight'>{kw}</mark>")
    return text


# --- 2. 侧边栏与路由 ---
st.sidebar.markdown("<h1 style='text-align: center; font-size: 60px;'>☯️</h1>", unsafe_allow_html=True)
st.sidebar.title("📜 中医典藏系统V2.0")
page = st.sidebar.radio("模块导航", [
    "🔍 传世名方基础检索",
    "🤖 传世名方 AI 检索",
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
    st.markdown("输入临床病名或症状，极速在传世医典中进行词汇检索匹配。")
    search_term = st.text_input("💡 检索词 (例如：感冒、十二指肠溃疡)", "")

    if st.button("开始常规检索", type="primary"):
        if search_term.strip():
            log_query("基础名方检索", search_term)
            conn = get_connection()
            # 限制返回100条防卡顿
            query = "SELECT * FROM formulas WHERE 临床病名 LIKE ? OR 方剂名 LIKE ? OR 病例详情 LIKE ? LIMIT 100"
            df_result = pd.read_sql(query, conn, params=(f'%{search_term}%', f'%{search_term}%', f'%{search_term}%'))
            conn.close()

            if df_result.empty:
                st.info("📉 浩瀚医海，未寻得完全匹配的记载。")
            else:
                st.success(f"✅ 检索完毕，共得 {len(df_result)} 则良方：")
                for _, row in df_result.iterrows():
                    with st.container(border=True):
                        st.markdown(f"### 🛡️ 【{row.get('方剂名', '未知')}】")
                        st.markdown(
                            f"**👨‍⚕️ 医家名:** {row.get('大医名', '未知')} &nbsp;&nbsp;|&nbsp;&nbsp; **🏷️ 方别:** {row.get('方别', '未知')} &nbsp;&nbsp;|&nbsp;&nbsp; **🩺 临床病名:** {row.get('临床病名', '未知')}")
                        st.markdown(f"**📜 方剂详情:**<br>{row.get('方剂详情', '')}", unsafe_allow_html=True)
                        st.markdown(f"**📝 临证提要:**<br>{row.get('临证提要', '无')}", unsafe_allow_html=True)
                        st.markdown(f"**📖 病例详情:**<br>{row.get('病例详情', '无')}", unsafe_allow_html=True)
                        if pd.notna(row.get('按语')): st.markdown(f"**💡 按语:**<br>{row.get('按语')}",
                                                                  unsafe_allow_html=True)
                        if pd.notna(row.get('现代研究')): st.markdown(f"**🔬 现代研究:**<br>{row.get('现代研究')}",
                                                                      unsafe_allow_html=True)

# ==========================================
# 模块二：传世名方 AI 智能检索
# ==========================================
elif page == "🤖 传世名方 AI 检索":
    st.title("🤖 AI 智能检索")
    st.markdown(
        "基于大模型的深度语义解析。**声明：AI 严格限定于本地《传世名方》数据库内进行比对筛查，宁缺毋滥，拒绝凭空伪造。**")

    if "ai_auth" not in st.session_state:
        st.session_state.ai_auth = False

    if not st.session_state.ai_auth:
        ai_pwd = st.text_input("🔑 请输入访问密码以启用 AI 引擎", type="password")
        if st.button("解锁 AI 引擎"):
            if ai_pwd == "888":
                st.session_state.ai_auth = True
                st.rerun()
            else:
                st.error("密码错误，无法启用。")
    else:
        conn = get_connection()
        conf = pd.read_sql("SELECT * FROM ai_config WHERE id=1", conn).iloc[0]
        conn.close()

        api_key = conf['api_key']
        base_url = conf['base_url']
        model_name = conf['model_name']

        condition_desc = st.text_area("✍️ 请详细描述疾病情况 (如: 胃痛时而剧烈，隐隐作痛，伴有头晕不眠，舌淡白...)",
                                      height=150)

        if st.button("🧠 提交 AI 深度匹配", type="primary"):
            if not condition_desc.strip():
                st.warning("请详细描述病症！")
            elif not api_key or api_key == "":
                st.error("⚠️ AI 尚未配置，请先进入【后台管理系统 -> AI引擎配置】设置 API Key。")
            else:
                with st.spinner("AI 正在典藏库中为您彻查比对...这可能需要十几秒，请稍候。"):
                    conn = get_connection()
                    df_all = pd.read_sql("SELECT id, 方剂名, 临床病名, 方剂详情, 病例详情 FROM formulas", conn)
                    conn.close()

                    corpus = df_all.to_dict(orient="records")
                    corpus_str = json.dumps(corpus[:100], ensure_ascii=False)

                    system_prompt = """你是一位资深严谨的中医专家。
                    规则1：你只能在我提供的<数据库语料>来选择推荐方剂，绝对不能从外部选择推荐方剂！如果确实没有合适的，请返回空列表。
                    规则2：针对用户的【病情描述】，结合你所掌握的中医知识和经验，根据我提供的<数据库语料>中各方剂的方剂详情、病例详情、临床病名、按语、现代研究、临证提要等全部内容对方剂的功效、组方原则、
                    病例应用、实践研究等方面进行分析筛选，从我提供的<数据库语料>中推荐符合用户的【病情描述】的疾病的病理、病机、病症治疗的方剂。
                    规则3：输出严格的JSON。格式: {"matched_ids": [1, 5], "highlight_keywords": ["胃痛", "舌淡白"]}"""
                    user_prompt = f"<数据库语料>\n{corpus_str}\n</数据库语料>\n\n用户的病情：{condition_desc}"

                    try:
                        client = OpenAI(api_key=api_key, base_url=base_url)
                        response = client.chat.completions.create(
                            model=model_name,
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
                            placeholders = ','.join('?' * len(matched_ids))
                            df_matched = pd.read_sql(f"SELECT * FROM formulas WHERE id IN ({placeholders})", conn,
                                                     params=tuple(matched_ids))
                            conn.close()

                            df_matched['id_cat'] = pd.Categorical(df_matched['id'], categories=matched_ids,
                                                                  ordered=True)
                            df_matched = df_matched.sort_values('id_cat')

                            for _, row in df_matched.iterrows():
                                with st.container(border=True):
                                    st.markdown(f"### 🛡️ AI 推荐：【{row.get('方剂名', '未知')}】")
                                    st.markdown(
                                        f"**👨‍⚕️ 医家:** {row.get('大医名', '')} &nbsp;|&nbsp; **🏷️ 方别:** {row.get('方别', '')} &nbsp;|&nbsp; **🩺 适用病名:** {row.get('临床病名', '')}")
                                    st.markdown(
                                        f"**📜 方剂详情:**<br>{highlight_text(str(row.get('方剂详情', '')), keywords)}",
                                        unsafe_allow_html=True)
                                    st.markdown(
                                        f"**📝 临证提要:**<br>{highlight_text(str(row.get('临证提要', '')), keywords)}",
                                        unsafe_allow_html=True)
                                    st.markdown(
                                        f"**📖 病例详情:**<br>{highlight_text(str(row.get('病例详情', '')), keywords)}",
                                        unsafe_allow_html=True)
                                    if pd.notna(row.get('按语')) and str(row.get('按语')).strip():
                                        st.markdown(f"**💡 按语:**<br>{highlight_text(str(row.get('按语')), keywords)}",
                                                    unsafe_allow_html=True)
                                    if pd.notna(row.get('现代研究')) and str(row.get('现代研究')).strip():
                                        st.markdown(
                                            f"**🔬 现代研究:**<br>{highlight_text(str(row.get('现代研究')), keywords)}",
                                            unsafe_allow_html=True)
                    except Exception as e:
                        st.error(f"AI 调用失败，请检查配置与网络：{e}")

# ==========================================
# 模块三：养生食谱检索
# ==========================================
elif page == "🍲 四季养生食谱检索":
    st.title("🍲 养生食谱数据库")
    st.markdown("多维度精准匹配，顺应四时养生。不填的条件默认不作限制。")

    with st.container(border=True):
        col1, col2 = st.columns(2)
        with col1:
            cailiao = st.text_input("🥦 食材用料 (如: 猪肉、山药)")
            gongxiao = st.text_input("✨ 核心功效 (如: 健脾、润肺)")
            nianji = st.text_input("👴 适用年龄 (如: 老年、儿童)")
        with col2:
            xingbie = st.text_input("👫 适用性别 (如: 男、女)")
            pinlei = st.text_input("🥘 菜式品类 (如: 汤羹、粥)")

        if st.button("查询养生食谱", type="primary"):
            query = "SELECT * FROM recipes WHERE 1=1"
            params = []
            if cailiao: query += " AND 材料和制作 LIKE ?"; params.append(f'%{cailiao}%')
            if gongxiao: query += " AND 功效和注意事项 LIKE ?"; params.append(f'%{gongxiao}%')
            if nianji: query += " AND 适合年纪 LIKE ?"; params.append(f'%{nianji}%')
            if xingbie: query += " AND 适合性别 LIKE ?"; params.append(f'%{xingbie}%')
            if pinlei: query += " AND 品类 LIKE ?"; params.append(f'%{pinlei}%')
            query += " LIMIT 150"  # 限制150条防卡顿

            conn = get_connection()
            df_result = pd.read_sql(query, conn, params=tuple(params))
            conn.close()

            log_query("食谱检索", f"{cailiao}|{gongxiao}")

            if df_result.empty:
                st.info("📉 未寻得符合全部条件的食谱，请尝试精简检索词。")
            else:
                st.success(f"✅ 寻得 {len(df_result)} 道养生佳肴：")
                for _, row in df_result.iterrows():
                    with st.expander(f"🍲 【{row.get('菜名', '未知')}】 | 类: {row.get('品类', '')}"):
                        st.markdown(f"**🥦 材料与制作:**\n {row.get('材料和制作', '')}")
                        st.markdown(f"**✨ 功效与禁忌:**\n {row.get('功效和注意事项', '')}")
                        st.markdown("---")
                        c1, c2, c3 = st.columns(3)
                        c1.markdown(f"**👴 年纪:** {row.get('适合年纪', '老少皆宜')}")
                        c2.markdown(f"**👫 性别:** {row.get('适合性别', '男女皆宜')}")
                        c3.markdown(f"**🌸 季节:** {row.get('适合季节', '四季皆宜')}")

# ==========================================
# 模块四：后台管理系统
# ==========================================
elif page == "⚙️ 典藏后台管理系统":
    st.title("⚙️ 系统中枢及数据管理")

    if "admin_auth" not in st.session_state:
        st.session_state.admin_auth = False

    if not st.session_state.admin_auth:
        pwd = st.text_input("🔑 请输入系统超级管理员密码", type="password")
        if st.button("进入中枢"):
            if pwd == "123":
                st.session_state.admin_auth = True
                st.rerun()
            else:
                st.error("密码错误！")
    else:
        st.success("✅ 身份验证通过：田 夫 (为了系统流畅，请规范操作)")

        tab_stat, tab_ai, tab_edit, tab_import, tab_danger = st.tabs([
            "📊 数据统计", "🧠 AI 引擎配置", "✏️ 数据维护(增删)", "📁 批量导入", "⚠️ 高危操作"
        ])

        with tab_stat:
            st.subheader("平台数据态势")
            conn = get_connection()
            num_formulas = pd.read_sql("SELECT COUNT(*) as c FROM formulas", conn).iloc[0]['c']
            num_recipes = pd.read_sql("SELECT COUNT(*) as c FROM recipes", conn).iloc[0]['c']
            num_logs = pd.read_sql("SELECT COUNT(*) as c FROM query_logs", conn).iloc[0]['c']
            sc1, sc2, sc3 = st.columns(3)
            sc1.metric("📚 传世名方总数", num_formulas)
            sc2.metric("🍲 养生食谱总数", num_recipes)
            sc3.metric("👣 历史总检索次数", num_logs)

            st.markdown("### 📝 最近访客检索日志")
            logs_df = pd.read_sql(
                "SELECT id as 序号, query_time as 检索时间, search_type as 检索模块, keyword as 检索词 FROM query_logs ORDER BY id DESC LIMIT 50",
                conn)
            st.dataframe(logs_df, use_container_width=True)
            conn.close()

        with tab_ai:
            st.subheader("🤖 AI 模型接口参数统管")
            conn = get_connection()
            conf = pd.read_sql("SELECT * FROM ai_config WHERE id=1", conn).iloc[0]
            conn.close()

            # 取消form结构，使保存按钮稳定触发
            new_api_key = st.text_input("🔑 API Key", value=conf['api_key'], type="password")
            new_base_url = st.text_input("🌐 Base URL (接口地址)", value=conf['base_url'])
            new_model = st.text_input("🧠 调用的模型名称 (Model Name)", value=conf['model_name'])
            if st.button("💾 保存更新 AI 配置", type="primary"):
                conn = get_connection()
                conn.execute("UPDATE ai_config SET api_key=?, base_url=?, model_name=? WHERE id=1",
                             (new_api_key, new_base_url, new_model))
                conn.commit()
                conn.close()
                st.success("✅ AI 接口配置已更新生效！")

        with tab_edit:
            st.subheader("✏️ 数据精确定向维护")
            st.warning("⚠️ 数据库体积庞大，全量铺开会导致浏览器崩溃卡死。请通过下方表单精确完成录入、修改与删除。")

            action_type = st.radio("请选择执行的操作", ["➕ 新增记录", "🔍 搜索与修改", "🗑️ 定向删除"], horizontal=True)

            if action_type == "➕ 新增记录":
                tbl = st.selectbox("目标表", ["formulas (名方)", "recipes (食谱)"])
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
                                st.success("新增成功！")
                            else:
                                st.error("必填项不可为空！")
                    else:
                        st.info("正在录入：养生食谱")
                        r_name = st.text_input("菜名*")
                        r_type = st.text_input("品类")
                        r_mat = st.text_area("材料和制作")
                        r_eff = st.text_area("功效和注意事项")
                        if st.form_submit_button("保存至食谱库"):
                            if r_name:
                                conn = get_connection()
                                conn.execute(
                                    "INSERT INTO recipes (菜名, 品类, 材料和制作, 功效和注意事项) VALUES (?,?,?,?)",
                                    (r_name, r_type, r_mat, r_eff))
                                conn.commit()
                                conn.close()
                                st.success("新增成功！")
                            else:
                                st.error("菜名为必填项！")

            elif action_type == "🔍 搜索与修改":
                st.markdown("通过关键字定位数据并进行编辑更新。")
                edit_tbl = st.selectbox("修改目标表", ["formulas (名方)", "recipes (食谱)"])
                real_tbl = "formulas" if "formulas" in edit_tbl else "recipes"

                search_kw = st.text_input("🔍 输入检索词 (如方名、菜名、病名等以查找)")

                if search_kw.strip():
                    conn = get_connection()
                    if real_tbl == "formulas":
                        query = "SELECT id, 方剂名, 临床病名, 大医名 FROM formulas WHERE 方剂名 LIKE ? OR 临床病名 LIKE ? LIMIT 20"
                    else:
                        query = "SELECT id, 菜名, 品类 FROM recipes WHERE 菜名 LIKE ? OR 功效和注意事项 LIKE ? LIMIT 20"

                    search_res = pd.read_sql(query, conn, params=(f'%{search_kw}%', f'%{search_kw}%'))
                    conn.close()

                    if search_res.empty:
                        st.info("未找到匹配的记录。")
                    else:
                        st.write(f"找到 {len(search_res)} 条关联记录 (最多显示前20条)：")
                        st.dataframe(search_res, hide_index=True)

                        edit_id = st.number_input("请输入您要修改的记录 ID", min_value=0, step=1, value=0)

                        if edit_id > 0:
                            conn = get_connection()
                            record = pd.read_sql(f"SELECT * FROM {real_tbl} WHERE id=?", conn, params=(edit_id,))
                            conn.close()

                            if not record.empty:
                                row = record.iloc[0]
                                with st.form("update_form"):
                                    if real_tbl == "formulas":
                                        st.info(f"正在修改 ID: {edit_id} 的名方")
                                        u_f_name = st.text_input("方剂名*", value=row.get('方剂名') if pd.notna(
                                            row.get('方剂名')) else "")
                                        u_b_name = st.text_input("临床病名*", value=row.get('临床病名') if pd.notna(
                                            row.get('临床病名')) else "")
                                        u_d_name = st.text_input("大医名", value=row.get('大医名') if pd.notna(
                                            row.get('大医名')) else "")
                                        u_det = st.text_area("方剂详情", value=row.get('方剂详情') if pd.notna(
                                            row.get('方剂详情')) else "")
                                        u_cas = st.text_area("病例详情", value=row.get('病例详情') if pd.notna(
                                            row.get('病例详情')) else "")
                                        u_sumry = st.text_area("临证提要", value=row.get('临证提要') if pd.notna(
                                            row.get('临证提要')) else "")

                                        if st.form_submit_button("💾 保存名方修改", type="primary"):
                                            if u_f_name and u_b_name:
                                                conn = get_connection()
                                                conn.execute(
                                                    "UPDATE formulas SET 方剂名=?, 临床病名=?, 大医名=?, 方剂详情=?, 病例详情=?, 临证提要=? WHERE id=?",
                                                    (u_f_name, u_b_name, u_d_name, u_det, u_cas, u_sumry, edit_id))
                                                conn.commit()
                                                conn.close()
                                                st.success("名方记录修改成功！")
                                            else:
                                                st.error("必填项不可为空！")
                                    else:
                                        st.info(f"正在修改 ID: {edit_id} 的食谱")
                                        u_r_name = st.text_input("菜名*", value=row.get('菜名') if pd.notna(
                                            row.get('菜名')) else "")
                                        u_r_type = st.text_input("品类", value=row.get('品类') if pd.notna(
                                            row.get('品类')) else "")
                                        u_r_mat = st.text_area("材料和制作", value=row.get('材料和制作') if pd.notna(
                                            row.get('材料和制作')) else "")
                                        u_r_eff = st.text_area("功效和注意事项",
                                                               value=row.get('功效和注意事项') if pd.notna(
                                                                   row.get('功效和注意事项')) else "")

                                        if st.form_submit_button("💾 保存食谱修改", type="primary"):
                                            if u_r_name:
                                                conn = get_connection()
                                                conn.execute(
                                                    "UPDATE recipes SET 菜名=?, 品类=?, 材料和制作=?, 功效和注意事项=? WHERE id=?",
                                                    (u_r_name, u_r_type, u_r_mat, u_r_eff, edit_id))
                                                conn.commit()
                                                conn.close()
                                                st.success("食谱记录修改成功！")
                                            else:
                                                st.error("菜名为必填项！")
                            else:
                                st.warning("未找到该 ID 对应的记录，请核对后输入。")

            elif action_type == "🗑️️ 定向删除":
                st.markdown("通过 ID 精确定位数据并删除，确保系统响应极速不卡顿。")
                del_tbl = st.selectbox("目标表", ["formulas", "recipes"])
                del_id = st.number_input(f"请输入要删除的 {del_tbl} 记录的 ID", min_value=1, step=1)

                # 预览要删除的数据
                conn = get_connection()
                preview = pd.read_sql(f"SELECT * FROM {del_tbl} WHERE id=?", conn, params=(del_id,))
                conn.close()
                if not preview.empty:
                    st.dataframe(preview)
                    if st.button("🚨 确认删除此记录"):
                        conn = get_connection()
                        conn.execute(f"DELETE FROM {del_tbl} WHERE id=?", (del_id,))
                        conn.commit()
                        conn.close()
                        st.success("已成功删除！")
                        st.rerun()
                else:
                    st.info("未找到此 ID 对应的数据。")
        with tab_import:
            st.subheader("📥 Excel 批量智能导入")
            uploaded_file = st.file_uploader("请上传待导入的 Excel 文件 (.xlsx)", type=["xlsx", "xls"])
            target_table = st.radio("导入目标库", ["formulas", "recipes"])

            if uploaded_file is not None:
                xls = pd.ExcelFile(uploaded_file)
                st.write(f"📂 检测到 {len(xls.sheet_names)} 个工作表")
                if st.button("开始批量读取并智能去重导入", type="primary"):
                    try:
                        conn = get_connection()
                        old_df = pd.read_sql(f"SELECT * FROM {target_table}", conn)
                        df_list = [pd.read_excel(xls, sheet_name=s) for s in xls.sheet_names]
                        new_data = pd.concat(df_list, ignore_index=True)
                        combined_df = pd.concat([old_df, new_data], ignore_index=True)

                        if target_table == "formulas" and '方剂名' in combined_df.columns:
                            combined_df.drop_duplicates(subset=['方剂名', '临床病名'], keep='last', inplace=True)
                        elif target_table == "recipes" and '菜名' in combined_df.columns:
                            combined_df.drop_duplicates(subset=['菜名'], keep='last', inplace=True)

                        combined_df.to_sql(target_table, conn, if_exists="replace", index=False)
                        conn.close()
                        st.success(f"🎉 导入成功！过滤重复后库中共存有 {len(combined_df)} 条数据。")
                    except Exception as e:
                        st.error(f"导入出错，可能是文件格式不匹配: {e}")

        with tab_danger:
            st.subheader("☢️ 高危指令区")
            clear_table = st.selectbox("选择要物理清空的数据表", ["formulas", "recipes", "query_logs"])
            confirm_text = st.text_input(f"如果您确切明白后果，请在此处手动输入：确认清空{clear_table}")
            if st.button("🚨 强制执行一键清空"):
                if confirm_text == f"确认清空{clear_table}":
                    conn = get_connection()
                    conn.execute(f"DELETE FROM {clear_table}")
                    conn.commit()
                    conn.close()
                    st.success(f"💀 核心指令已下达，【{clear_table}】已被永久清空。")
                else:
                    st.warning("防误触锁生效：口令不正确。")
