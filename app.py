import streamlit as st
import pandas as pd
import sqlite3
import os
import zipfile  # 引入解压模块

# --- 全局配置 ---
DB_FILE = 'tcm_database.db'
ZIP_FILE = 'tcm_database.zip'

# --- 自动解压逻辑 ---
if not os.path.exists(DB_FILE):
    if os.path.exists(ZIP_FILE):
        # 如果发现有 zip 包但没有 db 文件，就自动解压
        with zipfile.ZipFile(ZIP_FILE, 'r') as zip_ref:
            zip_ref.extractall('.') # 解压到当前目录
    else:
        st.error("⚠️ 未找到数据库文件或压缩包，请检查 GitHub 仓库。")
        st.stop()

def get_connection():
    return sqlite3.connect(DB_FILE, check_same_thread=False)

# --- 以下为您原来的前端界面与路由代码 ---
st.set_page_config(page_title="名方检索系统", page_icon="🌿", layout="centered")

# 检查数据库文件是否存在
if not os.path.exists(DB_FILE):
    st.error("⚠️ 未找到数据库文件 tcm_database.db，请确保已将其上传至 GitHub 仓库根目录。")
    st.stop()

# 侧边栏导航
st.sidebar.title("🌿 系统菜单")
page = st.sidebar.radio("请选择功能模块", ["🔍 临床病名检索", "⚙️ 后台管理系统"])

# ----------------- 用户搜索端 -----------------
if page == "🔍 临床病名检索":
    st.title("🔍 传世名方检索系统")
    st.markdown("通过输入**临床病名**搜索相关的名方及详细病例。")
    
    search_term = st.text_input("💡 临床病名 (例如：胃及十二指肠溃疡、感冒)", "")
    
    if st.button("开始搜索", type="primary"):
        if search_term.strip() == "":
            st.warning("⚠️ 请先输入您要查询的临床病名！")
        else:
            conn = get_connection()
            query = "SELECT * FROM prescriptions WHERE 临床病名 LIKE ?"
            df_result = pd.read_sql(query, conn, params=(f'%{search_term}%',))
            conn.close()
            
            if df_result.empty:
                st.info("📉 未找到匹配结果，请尝试缩短或更换关键词。")
            else:
                st.success(f"✅ 检索成功！共找到 {len(df_result)} 条相关记录：")
                
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

# ----------------- 后台管理端 -----------------
elif page == "⚙️ 后台管理系统":
    st.title("⚙️ 数据库后台管理")
    
    password = st.text_input("🔑 请输入管理员密码", type="password")
    
    if password == "admin123":
        st.success("✅ 登录成功！")
        conn = get_connection()
        
        # 1. 查看数据
        st.subheader("📊 现有记录总览")
        df_all = pd.read_sql("SELECT id, 大医名, 方剂名, 临床病名 FROM prescriptions", conn)
        st.dataframe(df_all, use_container_width=True)
        
        # 2. 增加数据
        st.subheader("➕ 添加新名方")
        with st.form("add_form"):
            new_doc = st.text_input("大医名")
            new_fj = st.text_input("方剂名")
            new_bm = st.text_input("临床病名")
            new_xq = st.text_area("方剂详情")
            new_bl = st.text_area("病例详情")
            submitted = st.form_submit_button("保存至数据库")
            
            if submitted:
                if new_fj and new_bm:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO prescriptions (大医名, 方剂名, 临床病名, 方剂详情, 病例详情)
                        VALUES (?, ?, ?, ?, ?)
                    """, (new_doc, new_fj, new_bm, new_xq, new_bl))
                    conn.commit()
                    st.success("🎉 记录已添加！")
                    st.rerun()
                else:
                    st.error("方剂名和临床病名为必填项！")
                    
        # 3. 删除数据
        st.subheader("🗑️ 移除记录")
        delete_id = st.number_input("输入要删除的记录ID", min_value=0, step=1)
        if st.button("确认删除"):
            cursor = conn.cursor()
            cursor.execute("DELETE FROM prescriptions WHERE id = ?", (delete_id,))
            conn.commit()
            st.success(f"已删除ID为 {delete_id} 的记录。")
            st.rerun()
            
        conn.close()
    elif password != "":
        st.error("❌ 密码错误！")
