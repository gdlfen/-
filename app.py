import streamlit as st
import pandas as pd
import sqlite3
import os
import zipfile
import json
from openai import OpenAI

# --- 全局与主题配置 ---
st.set_page_config(page_title="典藏传世名方系统", page_icon="📜", layout="wide")

# 注入自定义 CSS：庄重、古朴的中医古籍风格
st.markdown("""
    <style>
    /* 全局宣纸背景色与字体 */
    .stApp {
        background-color: #FDFBF7;
        font-family: 'Noto Serif SC', 'SimSun', 'Songti SC', serif;
        color: #2C2825;
    }
    /* 标题样式：深沉赭石色 */
    h1, h2, h3 {
        color: #792D11 !important;
        font-weight: bold;
    }
    /* 侧边栏样式 */
    [data-testid="stSidebar"] {
        background-color: #F2E8D5;
        border-right: 2px solid #D9C5A0;
    }
    /* 按钮样式：仿古红 */
    .stButton>button {
        background-color: #792D11;
        color: #FFFFFF;
        border-radius: 4px;
        border: 1px solid #4A1A08;
        transition: all 0.3s ease;
        padding: 0.5rem 1rem;
        font-weight: bold;
    }
    .stButton>button:hover {
        background-color: #4A1A08;
        color: #FDFBF7;
        border: 1px solid #792D11;
    }
    /* 检索卡片边框效果 */
    [data-testid="stVerticalBlockBorderWrapper"] {
        background-color: #FFFFFF;
        border: 1px solid #E8DCC4 !important;
        box-shadow: 0 4px 6px rgba(0,0,0,0.02);
        border-radius: 8px;
    }
    /* 高亮标示（AI输出用） */
    mark.yellow-highlight {
        background-color: #FFF2CC;
        color: #B83B00;
        font-weight: bold;
        padding: 0 4px;
        border-radius: 2px;
        border-bottom: 2px solid #F0B27A;
    }
    /* 声明提醒文字 */
    .disclaimer {
        color: #B83B00;
        font-size: 0.85rem;
        padding: 10px;
        border-top: 1px dashed #D9C5A0;
        margin-top: 30px;
    }
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
            
    # 确保日志表和配置表存在
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS query_logs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  ip_address TEXT, search_type TEXT, keyword TEXT, 
                  query_time DATETIME DEFAULT CURRENT_TIMESTAMP)''')
                  
    c.execute('''CREATE TABLE IF NOT EXISTS ai_config
                 (id INTEGER PRIMARY KEY CHECK (id = 1), 
                  api_key TEXT, base_url TEXT, model_name TEXT)''')
    
    # 初始化 AI 配置数据
    c.execute("SELECT COUNT(*) FROM ai_config")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO ai_config (id, api_key, base_url, model_name) VALUES (1, '', 'https://api.deepseek.com/v1', 'deepseek-chat')")
        
    conn.commit()
    conn.close()
    return True, "Success"

status, msg = init_system()
if not status:
    st.error(f"⚠️ 系统初始化失败: {msg}")
    st.stop()

def get_connection():
    return sqlite3.connect(DB_FILE, check_same_thread=False)

def log_query(search_type, keyword):
    """记录访客查询日志"""
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("INSERT INTO query_logs (search_type, keyword) VALUES (?, ?)", (search_type, keyword))
        conn.commit()
        conn.close()
    except:
        pass

# --- 高亮函数 ---
def highlight_text(text, kw_list):
    if not isinstance(text, str) or not text: 
        return ""
    for kw in kw_list:
        if kw and len(kw) > 1: # 忽略单字，防止过度高亮
            text = text.replace(kw, f"<mark class='yellow-highlight'>{kw}</mark>")
    return text

# --- 2. 侧边栏与路由 ---
st.sidebar.markdown("<h1 style='text-align: center; font-size: 60px;'>☯️</h1>", unsafe_allow_html=True)
st.sidebar.title("📜 中医典藏系统")
page = st.sidebar.radio("模块导航", [
    "🔍 传世名方基础检索", 
    "🤖 传世名方 AI 智能检索",
    "🍲 四季养生食谱检索", 
    "⚙️ 典藏后台管理系统"
])

# 侧边栏免责声明
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
            query = "SELECT * FROM formulas WHERE 临床病名 LIKE ? OR 方剂名 LIKE ? OR 病例详情 LIKE ?"
            df_result = pd.read_sql(query, conn, params=(f'%{search_term}%', f'%{search_term}%', f'%{search_term}%'))
            conn.close()
            
            if df_result.empty:
                st.info("📉 浩瀚医海，未寻得完全匹配的记载。")
            else:
                st.success(f"✅ 检索完毕，共得 {len(df_result)} 则良方（按原文记载列出）：")
                
                # 采用全新的卡片式版面
                for _, row in df_result.iterrows():
                    with st.container(border=True):
                        st.markdown(f"### 🛡️ 【{row.get('方剂名', '未知')}】")
                        st.markdown(f"**👨‍⚕️ 医家名:** {row.get('大医名', '未知')} &nbsp;&nbsp;|&nbsp;&nbsp; **🏷️ 方别:** {row.get('方别', '未知')} &nbsp;&nbsp;|&nbsp;&nbsp; **🩺 临床病名:** {row.get('临床病名', '未知')}")
                        st.markdown(f"**📜 方剂详情:**<br>{row.get('方剂详情', '')}", unsafe_allow_html=True)
                        st.markdown(f"**📝 临证提要:**<br>{row.get('临证提要', '无')}", unsafe_allow_html=True)
                        st.markdown(f"**📖 病例详情:**<br>{row.get('病例详情', '无')}", unsafe_allow_html=True)
                        
                        if pd.notna(row.get('按语')):
                            st.markdown(f"**💡 按语:**<br>{row.get('按语')}", unsafe_allow_html=True)
                        if pd.notna(row.get('现代研究')):
                            st.markdown(f"**🔬 现代研究:**<br>{row.get('现代研究')}", unsafe_allow_html=True)

# ==========================================
# 模块二：传世名方 AI 智能检索
# ==========================================
elif page == "🤖 传世名方 AI 智能检索":
    st.title("🤖 AI 智能检索")
    st.markdown("基于大模型的深度语义解析。**声明：AI 严格限定于本地《传世名方》数据库内进行比对筛查，宁缺毋滥，拒绝凭空伪造。**")
    
    # AI 加密入口
    if "ai_auth" not in st.session_state:
        st.session_state.ai_auth = False

    if not st.session_state.ai_auth:
        ai_pwd = st.text_input("🔑 请输入医师/高级访问密码以启用 AI 引擎", type="password")
        if st.button("解锁 AI 引擎"):
            if ai_pwd == "888":  # 默认AI密码
                st.session_state.ai_auth = True
                st.rerun()
            else:
                st.error("密码错误，无法启用。")
    else:
        # 获取后台统一配置的 AI 参数
        conn = get_connection()
        conf = pd.read_sql("SELECT * FROM ai_config WHERE id=1", conn).iloc[0]
        conn.close()
        
        api_key = conf['api_key']
        base_url = conf['base_url']
        model_name = conf['model_name']

        condition_desc = st.text_area("✍️ 请详细描述疾病情况 (如: 胃痛时而剧烈，隐隐作痛，伴有头晕不眠，舌淡白...)", height=150)
        
        if st.button("🧠 提交 AI 深度检索", type="primary"):
            if not condition_desc.strip():
                st.warning("请详细描述病症！")
            elif not api_key or api_key == "":
                st.error("⚠️ AI 尚未配置，请先进入【后台管理系统 -> AI配置】设置 API Key。")
            else:
                with st.spinner("AI 正在典藏库中为您彻查比对...这可能需要十几秒，请稍候。"):
                    # 预抓取数据库进行 RAG 本地检索
                    conn = get_connection()
                    df_all = pd.read_sql("SELECT id, 方剂名, 临床病名, 方剂详情, 病例详情 FROM formulas", conn)
                    conn.close()
                    
                    # 考虑到大模型Token限制，构建语料库 (实际商用需接入向量数据库Milvus，此处作轻量化处理)
                    corpus = df_all.to_dict(orient="records")
                    corpus_str = json.dumps(corpus[:100], ensure_ascii=False) # 限制长度防截断报错
                    
                    system_prompt = """你是一位资深严谨的现代老中医。
                    规则1：你只能使用我提供的<数据库语料>来回答，绝对不能编造或使用外部知识！如果不匹配，请返回空列表。
                    规则2：根据用户的【病情描述】，在语料中全面分析筛查，选择匹配合适的病例或方剂（不合适的不选择），并计算匹配度排序。
                    规则3：输出严格的 JSON 格式。必须包含："matched_ids" (匹配的方剂id数组，按匹配度从高到低排序)，以及 "highlight_keywords" (需要在正文中高亮显示的关键词列表，原文字词，必须完全一致才能高亮，如症状词)。
                    格式: {"matched_ids": [1, 5, 2], "highlight_keywords": ["胃痛", "舌淡白", "头晕"]}"""
                    
                    user_prompt = f"<数据库语料>\n{corpus_str}\n</数据库语料>\n\n用户的【病情描述】：{condition_desc}"

                    try:
                        client = OpenAI(api_key=api_key, base_url=base_url)
                        response = client.chat.completions.create(
                            model=model_name,
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt}
                            ],
                            temperature=0.1,  # 极低随机性，保障严谨
                            response_format={ "type": "json_object" }
                        )
                        
                        ai_result = json.loads(response.choices[0].message.content)
                        matched_ids = ai_result.get("matched_ids", [])
                        keywords = ai_result.get("highlight_keywords", [])
                        
                        log_query("AI深度检索", condition_desc)
                        
                        if not matched_ids:
                            st.info("🤖 经过系统缜密分析，本地传世名方库中暂无与此证候高度契合的方剂。")
                        else:
                            st.success(f"🤖 AI 解析完毕！已为您从库中筛出最契合的 {len(matched_ids)} 剂良方（按匹配度降序排布）：")
                            
                            conn = get_connection()
                            placeholders = ','.join('?' * len(matched_ids))
                            sql = f"SELECT * FROM formulas WHERE id IN ({placeholders})"
                            df_matched = pd.read_sql(sql, conn, params=tuple(matched_ids))
                            conn.close()
                            
                            # 按照 AI 返回的 ID 顺序重新排序
                            df_matched['id_cat'] = pd.Categorical(df_matched['id'], categories=matched_ids, ordered=True)
                            df_matched = df_matched.sort_values('id_cat')
                            
                            # 渲染卡片与黄色高亮
                            for _, row in df_matched.iterrows():
                                with st.container(border=True):
                                    st.markdown(f"### 🛡️ AI 推荐方剂：【{row.get('方剂名', '未知')}】")
                                    st.markdown(f"**👨‍⚕️ 医家名:** {row.get('大医名', '未知')} &nbsp;&nbsp;|&nbsp;&nbsp; **🏷️ 方别:** {row.get('方别', '未知')} &nbsp;&nbsp;|&nbsp;&nbsp; **🩺 临床病名:** {row.get('临床病名', '未知')}")
                                    
                                    # 实施智能高亮
                                    hz_fj = highlight_text(str(row.get('方剂详情', '')), keywords)
                                    hz_zy = highlight_text(str(row.get('临证提要', '')), keywords)
                                    hz_bl = highlight_text(str(row.get('病例详情', '')), keywords)
                                    hz_ay = highlight_text(str(row.get('按语', '')), keywords)
                                    hz_yj = highlight_text(str(row.get('现代研究', '')), keywords)
                                    
                                    st.markdown(f"**📜 方剂详情:**<br>{hz_fj}", unsafe_allow_html=True)
                                    st.markdown(f"**📝 临证提要:**<br>{hz_zy}", unsafe_allow_html=True)
                                    st.markdown(f"**📖 病例详情:**<br>{hz_bl}", unsafe_allow_html=True)
                                    
                                    if pd.notna(row.get('按语')) and row.get('按语'):
                                        st.markdown(f"**💡 按语:**<br>{hz_ay}", unsafe_allow_html=True)
                                    if pd.notna(row.get('现代研究')) and row.get('现代研究'):
                                        st.markdown(f"**🔬 现代研究:**<br>{hz_yj}", unsafe_allow_html=True)
                                    
                    except Exception as e:
                        st.error(f"AI 调用失败，请检查后台 API 配置、费用余额与网络连接。异常代码：{e}")

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
            if pwd == "admin123":
                st.session_state.admin_auth = True
                st.rerun()
            else:
                st.error("密码错误！")
    else:
        st.success("✅ 身份验证通过：Super Admin")
        
        tab_stat, tab_ai, tab_edit, tab_import, tab_danger = st.tabs([
            "📊 数据总览与统计", 
            "🧠 AI 引擎配置", 
            "✏️ 数据编辑(增删改)", 
            "📁 批量导入(Excel)", 
            "⚠️ 高危操作区"
        ])
        
        # --- 子模块：统计与日志 ---
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
            
            st.markdown("### 📝 访客检索日志")
            logs_df = pd.read_sql("SELECT id as 序号, query_time as 检索时间, search_type as 检索模块, keyword as 检索词 FROM query_logs ORDER BY id DESC LIMIT 50", conn)
            st.dataframe(logs_df, use_container_width=True)
            conn.close()

        # --- 子模块：AI 后台配置 ---
        with tab_ai:
            st.subheader("🤖 AI 模型接口参数统管")
            st.markdown("在此配置您的私有化大模型或第三方云端大模型接口密钥。")
            conn = get_connection()
            conf = pd.read_sql("SELECT * FROM ai_config WHERE id=1", conn).iloc[0]
            conn.close()
            
            with st.form("ai_config_form"):
                new_api_key = st.text_input("🔑 API Key", value=conf['api_key'], type="password")
                new_base_url = st.text_input("🌐 Base URL (接口地址)", value=conf['base_url'])
                new_model = st.text_input("🧠 调用的模型名称 (Model Name)", value=conf['model_name'])
                if st.form_submit_button("💾 保存/更新 AI 配置"):
                    conn = get_connection()
                    conn.execute("UPDATE ai_config SET api_key=?, base_url=?, model_name=? WHERE id=1", 
                                 (new_api_key, new_base_url, new_model))
                    conn.commit()
                    conn.close()
                    st.success("✅ AI 接口配置已在底层更新生效！")

        # --- 子模块：数据编辑 (增/删/改) ---
        with tab_edit:
            st.subheader("在线实时数据编辑器")
            st.markdown("说明：直接在表格中双击单元格即可**修改**；选中行左侧勾选框并按 `Delete` 键即可**批量删除**；滑到表格底部可**新增新数据行**。")
            
            conn = get_connection()
            table_choice = st.selectbox("选择要管理的数据表", ["formulas (传世名方表)", "recipes (养生食谱表)"])
            real_table = "formulas" if "formulas" in table_choice else "recipes"
            
            df_edit = pd.read_sql(f"SELECT * FROM {real_table}", conn)
            
            # 使用 Streamlit 强大的 data_editor 实现可视化 CRUD
            edited_df = st.data_editor(df_edit, num_rows="dynamic", use_container_width=True, height=500, key=f"editor_{real_table}")
            
            if st.button(f"💾 确认保存所作的增删改至 {real_table}"):
                edited_df.to_sql(real_table, conn, if_exists="replace", index=False)
                st.success("✅ 数据已同步覆写保存至数据库！")
            conn.close()

        # --- 子模块：批量导入 ---
        with tab_import:
            st.subheader("📥 Excel 多工作表批量智能导入")
            uploaded_file = st.file_uploader("请上传待导入的 Excel 文件 (.xlsx / .xls)", type=["xlsx", "xls"])
            target_table = st.radio("导入目标库", ["formulas", "recipes"])
            
            if uploaded_file is not None:
                xls = pd.ExcelFile(uploaded_file)
                sheet_names = xls.sheet_names
                st.write(f"📂 共检测到 {len(sheet_names)} 个工作表: `{sheet_names}`")
                
                if st.button("开始批量读取并智能去重导入"):
                    try:
                        conn = get_connection()
                        old_df = pd.read_sql(f"SELECT * FROM {target_table}", conn)
                        
                        df_list = [pd.read_excel(xls, sheet_name=s) for s in sheet_names]
                        new_data = pd.concat(df_list, ignore_index=True)
                        
                        # 智能去重逻辑：按核心列去重，保留最新数据
                        combined_df = pd.concat([old_df, new_data], ignore_index=True)
                        
                        if target_table == "formulas" and '方剂名' in combined_df.columns:
                            combined_df.drop_duplicates(subset=['方剂名', '临床病名'], keep='last', inplace=True)
                        elif target_table == "recipes" and '菜名' in combined_df.columns:
                            combined_df.drop_duplicates(subset=['菜名'], keep='last', inplace=True)
                            
                        combined_df.to_sql(target_table, conn, if_exists="replace", index=False)
                        conn.close()
                        st.success(f"🎉 导入成功！系统已自动过滤完全重复的数据，现总计 {len(combined_df)} 条记载。")
                    except Exception as e:
                        st.error(f"导入格式与原数据库结构不匹配或出错: {e}")

        # --- 子模块：高危操作 ---
        with tab_danger:
            st.subheader("☢️ 高危指令区")
            st.error("警告：下方的操作将物理抹除本地记录，一旦执行无法回退！")
            
            clear_table = st.selectbox("选择要物理清空的数据表", ["formulas", "recipes", "query_logs"])
            confirm_text = st.text_input(f"如果您确切明白后果，请在此处手动输入：【确认清空{clear_table}】")
            
            if st.button("🚨 强制执行一键清空"):
                if confirm_text == f"确认清空{clear_table}":
                    conn = get_connection()
                    conn.execute(f"DELETE FROM {clear_table}")
                    conn.commit()
                    conn.close()
                    st.success(f"💀 核心指令已下达，【{clear_table}】表已被永久清空。")
                    st.rerun()
                else:
                    st.warning("防误触锁生效：确认口令输入不正确，已自动中止清空操作。")
