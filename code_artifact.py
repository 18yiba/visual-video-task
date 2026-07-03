"""Streamlit web interface for Video-EEG Experiment."""

import time
import random
import pandas as pd
from pathlib import Path
import streamlit as st

_GUI_ROOT = Path(__file__).resolve().parent
_PAGE_ICON_FILENAME = "🎬"

st.set_page_config(
    page_title="视频神经反应实验台",
    page_icon=_PAGE_ICON_FILENAME,
    layout="wide",
)

SIDEBAR_NAV_PAGES = ("首页", "实验设置", "实验会话", "数据导出")

# 定义10维评分指标
RATING_DIMENSIONS = [
    "愉悦度 (Valence)", "唤醒度 (Arousal)", "专注度 (Attention)", 
    "熟悉度 (Familiarity)", "喜好度 (Preference)", "真实感 (Realism)", 
    "情绪强度 (Emotion)", "视觉质量 (Quality)", "动态程度 (Dynamic)", "整体评分 (Overall)"
]

def init_session_state():
    """初始化全局状态"""
    defaults = {
        "gui_nav_mode": SIDEBAR_NAV_PAGES[0],
        "subject_id": "S001",
        "session_id": 1,
        "config": {
            "fixation_sec": 1.5,
            "video_sec": 8.0,  # 默认视频时长，实际应用中可读取视频元数据
            "blank_sec": 1.0,
            "iti_sec": 2.0,
            "trials_per_session": 90,
        },
        "experiment_state": "ready", # ready, fixation, video, blank, rating, iti, finished
        "current_trial": 0,
        "results": [],
        "playlist": []
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

def _set_gui_nav_mode(page: str) -> None:
    st.session_state.gui_nav_mode = page
    
def generate_playlist():
    """生成平衡的随机播放列表 (Mock)"""
    # 模拟 160独立 + 20重复 = 180 trial 的生成逻辑
    # 此处仅做列表生成演示
    trials = [f"video_{i:03d}.mp4" for i in range(st.session_state.config["trials_per_session"])]
    random.shuffle(trials)
    st.session_state.playlist = trials
    st.session_state.current_trial = 0
    st.session_state.experiment_state = "ready"
    st.session_state.results = []

def render_home() -> None:
    st.title("视频神经反应实验台")
    st.markdown(
        """
        ### 欢迎参与本次实验
        
        在接下来的任务中，您将观看一系列简短的视频片段。
        
        **实验流程：**
        1. 屏幕中央会出现十字注视点（请保持静止并注视屏幕中央）。
        2. 播放一段 6~12 秒的视频。
        3. 短暂空屏。
        4. 出现评分界面，请根据您的真实感受对视频进行 **10个维度的打分**。
        5. 短暂休息后自动进入下一个视频。
        
        **注意事项：**
        - 观看视频时请尽量保持身体和头部静止，减少眨眼，避免干扰脑电信号采集。
        - 评分阶段可以自由活动和操作鼠标。
        - 每次 Session 包含约 90 个视频，中途可根据提示休息。
        """
    )

def render_settings() -> None:
    st.title("实验参数配置")
    
    col1, col2 = st.columns(2)
    st.session_state.subject_id = col1.text_input("被试 ID (Subject ID)", value=st.session_state.subject_id)
    st.session_state.session_id = col2.selectbox("Session 编号", [1, 2], index=st.session_state.session_id - 1)
    
    st.markdown("### 时间参数控制")
    t_col1, t_col2, t_col3, t_col4 = st.columns(4)
    cfg = st.session_state.config
    
    cfg["fixation_sec"] = t_col1.number_input("注视点时长 (秒)", min_value=0.5, value=cfg["fixation_sec"], step=0.5)
    cfg["video_sec"] = t_col2.number_input("默认视频时长 (秒)", min_value=1.0, value=cfg["video_sec"], step=1.0)
    cfg["blank_sec"] = t_col3.number_input("空屏时长 (秒)", min_value=0.5, value=cfg["blank_sec"], step=0.5)
    cfg["iti_sec"] = t_col4.number_input("间隔时长 (ITI, 秒)", min_value=1.0, value=cfg["iti_sec"], step=0.5)
    
    if st.button("生成播放列表并初始化会话", type="primary"):
        generate_playlist()
        st.success(f"已为被试 {st.session_state.subject_id} 生成 Session {st.session_state.session_id} 的播放列表，共 {len(st.session_state.playlist)} 个 trial。")

def render_experiment() -> None:
    st.title(f"实验进行中 - 被试: {st.session_state.subject_id} | Session: {st.session_state.session_id}")
    
    if not st.session_state.playlist:
        st.warning("尚未生成播放列表，请先前往「实验设置」生成。")
        return

    current = st.session_state.current_trial
    total = len(st.session_state.playlist)
    
    if current >= total:
        st.session_state.experiment_state = "finished"
        
    st.progress(current / total, text=f"进度: {current} / {total} Trials")
    
    state = st.session_state.experiment_state
    container = st.empty()
    cfg = st.session_state.config

    if state == "ready":
        with container.container():
            st.info("准备就绪。请保持坐姿端正，注视屏幕。")
            if st.button("开始下一个 Trial", type="primary", use_container_width=True):
                st.session_state.experiment_state = "fixation"
                st.rerun()

    elif state == "fixation":
        # 注视点阶段
        container.markdown("<h1 style='text-align:center; font-size: 100px; padding: 150px 0;'>+</h1>", unsafe_allow_html=True)
        time.sleep(cfg["fixation_sec"])
        st.session_state.experiment_state = "video"
        st.rerun()

    elif state == "video":
        # 视频播放阶段 (实际应用中替换为真实视频路径)
        # 此处使用占位模拟视频播放时长
        with container.container():
            st.markdown(f"<h3 style='text-align:center;'>正在播放视频: {st.session_state.playlist[current]}</h3>", unsafe_allow_html=True)
            st.markdown("<div style='height: 300px; background-color: #000; color: #fff; display: flex; align-items: center; justify-content: center;'>VIDEO PLACEHOLDER</div>", unsafe_allow_html=True)
        
        # 实际开发中可以通过 JS 通信获取视频实际结束事件，这里用 sleep 模拟
        time.sleep(cfg["video_sec"])
        st.session_state.experiment_state = "blank"
        st.rerun()

    elif state == "blank":
        # 短暂空屏
        container.empty()
        time.sleep(cfg["blank_sec"])
        st.session_state.experiment_state = "rating"
        st.rerun()

    elif state == "rating":
        # 行为评分阶段
        with container.form(key=f"rating_form_{current}"):
            st.markdown("### 请对刚才观看的视频进行评分 (1-9分)")
            cols = st.columns(2)
            ratings = {}
            for i, dim in enumerate(RATING_DIMENSIONS):
                col = cols[i % 2]
                ratings[dim] = col.slider(dim, min_value=1, max_value=9, value=5, key=f"slider_{current}_{i}")
            
            submitted = st.form_submit_button("提交评分", type="primary")
            if submitted:
                # 保存数据
                result = {
                    "subject_id": st.session_state.subject_id,
                    "session_id": st.session_state.session_id,
                    "trial_idx": current,
                    "video_name": st.session_state.playlist[current],
                    "timestamp": time.time()
                }
                result.update(ratings)
                st.session_state.results.append(result)
                
                # 状态流转
                st.session_state.current_trial += 1
                st.session_state.experiment_state = "iti"
                st.rerun()

    elif state == "iti":
        # 间隔阶段
        container.markdown("<h2 style='text-align:center; padding: 150px 0;'>休息一下...</h2>", unsafe_allow_html=True)
        time.sleep(cfg["iti_sec"])
        st.session_state.experiment_state = "ready"
        st.rerun()

    elif state == "finished":
        container.success("🎉 本次 Session 的所有 Trial 已完成！感谢您的参与。")

def render_data_export() -> None:
    st.title("数据导出")
    results = st.session_state.results
    if not results:
        st.info("暂无数据。")
        return
        
    df = pd.DataFrame(results)
    st.dataframe(df)
    
    csv = df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="下载 CSV 结果文件",
        data=csv,
        file_name=f"exp_results_{st.session_state.subject_id}_session_{st.session_state.session_id}.csv",
        mime="text/csv",
        type="primary"
    )

def _inject_gui_nav_styles() -> None:
    st.markdown(
        """
        <style>
        .stApp { background-color: #ffffff; color: #0f172a; }
        section[data-testid="stSidebar"] {
          background: linear-gradient(180deg, #f8fafc 0%, #ffffff 100%);
          border-right: 1px solid rgba(15, 23, 42, 0.08);
        }
        section[data-testid="stSidebar"] .stButton > button {
          width: 100%; border-radius: 8px; padding: 0.6rem; font-weight: 600;
        }
        section[data-testid="stSidebar"] .stButton > button[kind="primary"] {
          background-color: #0F766E; color: white;
        }
        /* Hide sidebar collapse button for a cleaner kiosk-like look */
        [data-testid="collapsedControl"] { display: none; }
        </style>
        """,
        unsafe_allow_html=True,
    )

def main():
    init_session_state()
    _inject_gui_nav_styles()

    with st.sidebar:
        st.title("🎬 实验控制台")
        st.divider()
        for page in SIDEBAR_NAV_PAGES:
            is_active = st.session_state.gui_nav_mode == page
            st.button(
                page,
                key=f"nav_btn_{page}",
                type="primary" if is_active else "secondary",
                on_click=_set_gui_nav_mode,
                args=(page,),
            )
        mode = st.session_state.gui_nav_mode

    if mode == "首页":
        render_home()
    elif mode == "实验设置":
        render_settings()
    elif mode == "实验会话":
        render_experiment()
    elif mode == "数据导出":
        render_data_export()

if __name__ == "__main__":
    main()