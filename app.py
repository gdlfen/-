import streamlit as st
import pandas as pd
import sqlite3
import os
import zipfile

# --- 全局配置 ---
DB_FILE = 'tcm_database.db'
ZIP_FILE = 'tcm_database.zip'  # 请确保仓库中上传的压缩包叫这个名字

# --- 自动解压逻辑 ---
if not os.path.exists(DB_FILE):
    if os.path.exists(ZIP_FILE):
        try:
            with zipfile.ZipFile(ZIP_FILE, 'r') as zip_ref:
                zip_ref.extractall(".") 
        except Exception as e:
            st.error(f"解压失败: {e}")
            st.stop()
    else:
        st.error("⚠️ 未找到数据库压缩包，请确保已将 zip 文件上传至 GitHub 仓库根目录。")
        st.stop()

def get_connection():
    return sqlite3.connect(DB_FILE, check_same_thread=False)

# --- 前端界面与路由 ---
st.set_page_config(page_title="中医养生与名方检索", page_icon="🌿", layout="centered")

st.sidebar.title("🌿 系统菜单")
page = st.sidebar.radio("请选择功能模块", ["🔍 传世名方检索", "🍲 养生食谱检索", "⚙️ 后台管理系统"])

# ----------------- 功能1：传世名方检索 -----------------
if page == "🔍 传世名方检索":
    st.title("🔍 传世名方检索系统")
    st.markdown("通过输入**临床病名**搜索相关的名方及详细病例。")
    
    search_term = st.text_input("💡 临床病名 (例如：溃疡、感冒)", "")
    
    if st.button("开始搜索名方", type="primary"):
        if search_term.strip() == "":
            st.warning("⚠️ 请先输入您要查询的临床病名！")
        else:
            conn = get_connection()
            # 【修复点】表名从 prescriptions 改为 formulas
            query = "SELECT * FROM formulas WHERE 临床病名 LIKE ?"
            df_result = pd.read_sql(query, conn, params=(f'%{search_term}%',))
            conn.close()
            
            if df_result.empty:
                st.info("📉 未找到匹配结果，请尝试缩短或更换关键词。")
            else:
                st.success(f"✅ 检索成功！共找到 {len(df_result)} 条相关名方：")
                for index, row in df_result.iterrows():
                    fangji = row.get('方剂名', '未知')
                    bingming = row.get('临床病名', '未知')
                    with st.expander(f"📌 【{fangji}】 匹配病名: {bingming}"):
                        st.markdown(f"**👨‍⚕️ 大医名:** {row.get('大医名', '无')}")
                        st.markdown(f"**🏷️ 方别:** {row.get('方别', '无')}")
                        st.markdown(f"**📜 方剂详情:**\n\n {row.get('方剂详情', '无')}")
                        st.markdown(f"**🩺 病例详情:**\n\n {row.get('病例详情', '无')}")
                        st.markdown(f"**📝 临证提要:**\n\n {row.get('临证提要', '无')}")
                        if pd.notna(row.get('按语')):
                            st.markdown(f"**💡 按语:**\n\n {row.get('按语')}")
                        if pd.notna(row.get('现代研究')):
                            st.markdown(f"**🔬 现代研究:**\n\n {row.get('现代研究')}")

# ----------------- 功能2：养生食谱检索 -----------------
elif page == "🍲 养生食谱检索":
    st.title("🍲 养生食谱检索系统")
    st.markdown("可组合输入多个条件进行精准匹配。不填的条件默认不作限制。")
    
    col1, col2 = st.columns(2)
    with col1:
        cailiao = st.text_input("🥦 材料 (如: 猪肉、枸杞)")
        gongxiao = st.text_input("✨ 功效 (如: 健脾、补血)")
        nianji = st.text_input("👴 适合年纪 (如: 老年、儿童)")
    with col2:
        xingbie = st.text_input("👫 适合性别 (如: 男、女)")
        pinlei = st.text_input("🥘 品类 (如: 汤羹、热菜)")

    if st.button("开始搜索食谱", type="primary"):
        # 动态构建 SQL 语句，实现多条件匹配
        query = "SELECT * FROM recipes WHERE 1=1"
        params = []
        
        if cailiao.strip():
            query += " AND 材料和制作 LIKE ?"
            params.append(f'%{cailiao}%')
        if gongxiao.strip():
            query += " AND 功效和注意事项 LIKE ?"
            params.append(f'%{gongxiao}%')
        if nianji.strip():
            query += " AND 适合年纪 LIKE ?"
            params.append(f'%{nianji}%')
        if xingbie.strip():
            query += " AND 适合性别 LIKE ?"
            params.append(f'%{xingbie}%')
        if pinlei.strip():
            query += " AND 品类 LIKE ?"
            params.append(f'%{pinlei}%')

        conn = get_connection()
        df_result = pd.read_sql(query, conn, params=tuple(params))
        conn.close()
        
        if df_result.empty:
            st.info("📉 未找到符合全部条件的食谱，请尝试减少条件或更改关键词。")
        else:
            st.success(f"✅ 检索成功！共找到 {len(df_result)} 道养生食谱：")
            for index, row in df_result.iterrows():
                caiming = row.get('菜名', '未知菜品')
                with st.expander(f"🍲 【{caiming}】 | {row.get('品类', '')}"):
                    st.markdown(f"**🥦 材料和制作:**\n\n {row.get('材料和制作', '无')}")
                    st.markdown(f"**✨ 功效和注意事项:**\n\n {row.get('功效和注意事项', '无')}")
                    
                    st.markdown("---")
                    c1, c2, c3 = st.columns(3)
                    c1.markdown(f"**👴 适合年纪:** {row.get('适合年纪', '通用')}")
                    c2.markdown(f"**👫 适合性别:** {row.get('适合性别', '通用')}")
                    c3.markdown(f"**🌸 适合季节:** {row.get('适合季节', '不限')}")

# ----------------- 后台管理端 -----------------
elif page == "⚙️ 后台管理系统":
    st.title("⚙️ 数据库后台管理")
    password = st.text_input("🔑 请输入管理员密码", type="password")
    
    if password == "admin123":
        st.success("✅ 登录成功！")
        conn = get_connection()
        
        st.subheader("📊 传世名方数据表 (formulas)")
        try:
            df_formulas = pd.read_sql("SELECT id, 大医名, 方剂名, 临床病名 FROM formulas LIMIT 50", conn)
            st.dataframe(df_formulas, use_container_width=True)
        except:
            st.warning("暂无名方数据")
            
        st.subheader("📊 养生食谱数据表 (recipes)")
        try:
            df_recipes = pd.read_sql("SELECT id, 菜名, 品类, 适合年纪 FROM recipes LIMIT 50", conn)
            st.dataframe(df_recipes, use_container_width=True)
        except:
            st.warning("暂无食谱数据")
            
        conn.close()
    elif password != "":
        st.error("❌ 密码错误！")
