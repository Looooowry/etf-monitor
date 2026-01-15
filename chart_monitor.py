import akshare as ak
import pandas as pd
import matplotlib
matplotlib.use('Agg') # 后台绘图模式
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import datetime
import requests
import os
import subprocess
import time

# ================= 配置区域 =================
WXPUSHER_TOKEN = os.environ.get('WXPUSHER_TOKEN', '')
WXPUSHER_UID = os.environ.get('WXPUSHER_UID', '')
# GitHub 自动提供的环境变量
GITHUB_REPO = os.environ.get('GITHUB_REPOSITORY') # 格式: 用户名/仓库名

# 策略参数
view_start_date = '2024-12-30'
lag_days = 150
fetch_start_date = '2023-01-01'
anchor_hstech = 6700
anchor_ratio = 160
ratio_factor = anchor_ratio / anchor_hstech
hstech_ylim_top = 9500
hstech_ylim_bottom = 2500

# ================= 核心功能函数 =================

def push_image_to_github(file_path):
    """
    将生成的图片提交到 GitHub 仓库
    """
    try:
        print("正在将图片推送到 GitHub...")
        # 配置 git 用户（必须步骤）
        subprocess.run(["git", "config", "--global", "user.email", "action@github.com"], check=True)
        subprocess.run(["git", "config", "--global", "user.name", "GitHub Action"], check=True)
        
        # 添加文件、提交、推送
        subprocess.run(["git", "add", file_path], check=True)
        # 允许空提交（如果没有变化）
        subprocess.run(["git", "commit", "-m", f"Update chart: {datetime.datetime.now()}"], check=False)
        subprocess.run(["git", "push"], check=True)
        print("图片推送成功")
        return True
    except Exception as e:
        print(f"Git 推送失败: {e}")
        return False

def get_cdn_url(filename):
    """
    构造 jsDelivr 加速链接
    格式: https://cdn.jsdelivr.net/gh/用户/仓库@main/文件名
    """
    if not GITHUB_REPO:
        print("无法获取仓库信息")
        return None
    
    # 加上时间戳参数 ?v=... 是为了防止微信缓存旧图片，强制刷新
    timestamp = int(time.time())
    url = f"https://cdn.jsdelivr.net/gh/{GITHUB_REPO}@main/{filename}?v={timestamp}"
    return url

def send_wxpusher_image(img_url, summary):
    url = "http://wxpusher.zjiecode.com/api/send/message"
    
    # 提示信息
    content = (
        f"<h1>{summary}</h1><br>"
        f"📅 日期: {datetime.datetime.now().strftime('%Y-%m-%d')}<br>"
        f"<p>恒生科技 vs 铜油比 (滞后{lag_days}天)</p>"
        f"<hr>"
        f"<img src='{img_url}' width='100%' /><br>"
        f"<p style='font-size:12px; color:gray;'>*图片经由 jsDelivr 加速</p>"
    )
    
    data = {
        "appToken": WXPUSHER_TOKEN,
        "content": content,
        "summary": summary,
        "contentType": 2, 
        "uids": [WXPUSHER_UID],
    }
    try:
        requests.post(url, json=data)
        print("微信推送成功")
    except Exception as e:
        print(f"微信推送错误: {e}")

# ================= 数据获取与绘图 =================
# (这部分代码和之前一模一样，为了篇幅我简化展示，请保留之前的逻辑)
def get_data(symbol, type='future'):
    try:
        df = None
        if type == 'index':
            df = ak.stock_hk_index_daily_sina(symbol=symbol)
            df = df[['date', 'close']].rename(columns={'date': 'Date', 'close': 'Close'})
        elif type == 'future':
            df = ak.futures_foreign_hist(symbol=symbol)
            df = df[['date', 'close']].rename(columns={'date': 'Date', 'close': 'Close'})

        if df is not None:
            df['Date'] = pd.to_datetime(df['Date'])
            df.set_index('Date', inplace=True)
            df['Close'] = pd.to_numeric(df['Close'])
            return df[df.index >= pd.to_datetime(fetch_start_date)]['Close']
    except Exception as e:
        print(f"❌ {symbol} 获取失败: {e}")
        return None

def generate_chart():
    print("正在获取数据...")
    hstech = get_data("HSTECH", type='index')
    lme_copper = get_data("CAD", type='future')
    brent_oil = get_data("OIL", type='future')

    if hstech is None or lme_copper is None or brent_oil is None:
        print("❌ 数据获取失败")
        return None

    # 数据处理
    futures_df = pd.concat([lme_copper, brent_oil], axis=1, keys=['LME_Copper', 'Brent_Oil'])
    futures_df = futures_df.ffill().bfill()
    raw_ratio = futures_df['LME_Copper'] / futures_df['Brent_Oil']

    shifted_dates = raw_ratio.index + pd.Timedelta(days=lag_days)
    ratio_shifted = pd.Series(raw_ratio.values, index=shifted_dates)

    min_date = min(hstech.index.min(), ratio_shifted.index.min())
    max_date = max(hstech.index.max(), ratio_shifted.index.max())
    full_idx = pd.date_range(start=min_date, end=max_date, freq='D')

    plot_hstech = hstech.reindex(full_idx).interpolate(method='linear')
    plot_ratio = ratio_shifted.reindex(full_idx).interpolate(method='linear')

    plot_hstech = plot_hstech[plot_hstech.index >= pd.to_datetime(view_start_date)]
    plot_ratio = plot_ratio[plot_ratio.index >= pd.to_datetime(view_start_date)]
    
    today = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    plot_hstech = plot_hstech[plot_hstech.index <= today]

    ratio_ylim_bottom = hstech_ylim_bottom * ratio_factor
    ratio_ylim_top = hstech_ylim_top * ratio_factor

    # 绘图
    plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'bmh')
    fig, ax1 = plt.subplots(figsize=(12, 8))

    color1 = '#004c6d'
    ax1.plot(plot_hstech.index, plot_hstech, color=color1, linewidth=1.8, label='Hang Seng TECH', alpha=0.95)
    ax1.set_ylabel('Hang Seng TECH Index', color=color1, fontsize=12, fontweight='bold')
    ax1.tick_params(axis='y', labelcolor=color1)
    ax1.set_ylim(hstech_ylim_bottom, hstech_ylim_top)

    ax2 = ax1.twinx()
    color2 = '#d62728'
    ax2.plot(plot_ratio.index, plot_ratio, color=color2, linewidth=1.5, linestyle='-',
             label=f'LME/Brent Ratio (+{lag_days}d)', alpha=0.9)
    ax2.set_ylabel(f'LME Copper / Brent Ratio', color=color2, fontsize=12, fontweight='bold')
    ax2.tick_params(axis='y', labelcolor=color2)
    ax2.set_ylim(ratio_ylim_bottom, ratio_ylim_top)

    if plot_ratio.index[0] <= today <= plot_ratio.index[-1]:
        ax1.axvline(today, color='black', linestyle='--', linewidth=1.5)

    plt.title(f'HSTECH vs Copper/Oil (+{lag_days}d)', fontsize=14)
    ax1.set_xlim(left=pd.to_datetime(view_start_date), right=plot_ratio.index[-1])

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')

    date_fmt = mdates.DateFormatter('%y-%m-%d')
    ax1.xaxis.set_major_formatter(date_fmt)
    ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
    plt.setp(ax1.get_xticklabels(), rotation=90, ha='center', fontsize=10)
    ax1.grid(True, which='major', axis='x', linestyle='--', alpha=0.5)
    plt.subplots_adjust(bottom=0.15)

    # 【重点】保存的文件名固定，覆盖旧图，防止仓库无限膨胀
    filename = "latest_chart.png"
    plt.savefig(filename, dpi=100)
    plt.close()
    return filename

if __name__ == "__main__":
    # 1. 生成图片
    filename = generate_chart()
    
    if filename:
        # 2. 推送到 GitHub
        if push_image_to_github(filename):
            # 3. 获取加速链接
            img_url = get_cdn_url(filename)
            
            if img_url:
                print(f"图片链接: {img_url}")
                # 4. 发送微信
                send_wxpusher_image(img_url, "每日图表: 恒生科技趋势")
            else:
                print("URL生成失败")
        else:
            print("Git推送失败")
