import akshare as ak
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import datetime
import requests
import os
import base64
import sys
import pytz # 需要用到时区
from env_config import get_env_float, get_env_int, get_env_str

# ================= 配置区域 =================
WXPUSHER_TOKEN = os.environ.get('WXPUSHER_TOKEN', '')
WXPUSHER_UID = os.environ.get('WXPUSHER_UID', '')
IMGBB_KEY = os.environ.get('IMGBB_KEY', '')

# 策略参数
view_start_date = get_env_str("CHART_VIEW_START_DATE", "2024-12-30")
lag_days = get_env_int("CHART_LAG_DAYS", 150)
fetch_start_date = get_env_str("CHART_FETCH_START_DATE", "2023-01-01")

# 锚点参数
anchor_hstech = get_env_float("CHART_ANCHOR_HSTECH", 6700)
anchor_ratio = get_env_float("CHART_ANCHOR_RATIO", 160)
ratio_factor = anchor_ratio / anchor_hstech
hstech_ylim_top = get_env_float("CHART_HSTECH_YLIM_TOP", 9500)
hstech_ylim_bottom = get_env_float("CHART_HSTECH_YLIM_BOTTOM", 2500)

# ================= 核心功能函数 =================

def upload_to_imgbb(file_path):
    if not IMGBB_KEY:
        print("❌ 错误: 未配置 IMGBB_KEY")
        return None

    url = "https://api.imgbb.com/1/upload"
    try:
        print("正在上传图片到 ImgBB...")
        with open(file_path, "rb") as file:
            payload = {
                "key": IMGBB_KEY,
                "image": base64.b64encode(file.read()),
            }
            response = requests.post(url, payload)
            json_res = response.json()
            
            if response.status_code == 200 and json_res.get('success'):
                img_url = json_res['data']['url']
                print(f"✅ 图片上传成功: {img_url}")
                return img_url
            else:
                print(f"❌ ImgBB 上传失败: {response.text}")
                return None
    except Exception as e:
        print(f"❌ 上传请求出错: {e}")
        return None

def send_wxpusher_image(img_url, summary):
    url = "http://wxpusher.zjiecode.com/api/send/message"
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    content = (
        f"<h1>{summary}</h1><br>"
        f"📅 日期: {today}<br>"
        f"<p>恒生科技 vs 铜油比 (滞后{lag_days}天)</p>"
        f"<hr>"
        f"<img src='{img_url}' width='100%' /><br>"
        f"<p style='font-size:12px; color:gray;'>由 GitHub Actions 自动生成</p>"
    )
    data = {
        "appToken": WXPUSHER_TOKEN,
        "content": content,
        "summary": summary,
        "contentType": 2, 
        "uids": [WXPUSHER_UID],
    }
    requests.post(url, json=data)
    print("✅ 微信推送成功")

# ================= 数据获取与绘图 =================
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

    filename = "chart_push.png"
    plt.savefig(filename, dpi=100)
    plt.close()
    return filename

if __name__ == "__main__":
    # 【核心修改】时间锁逻辑
    # 1. 获取当前北京时间
    tz_cn = pytz.timezone('Asia/Shanghai')
    now_cn = datetime.datetime.now(tz_cn)
    
    print(f"当前北京时间: {now_cn.strftime('%H:%M')}")
    
    # 2. 判断是否是盘中（15点之前）
    # 如果现在的小时数小于 15 (比如 14点)，说明是盘中，直接退出，不发图
    if now_cn.hour < 15:
        print("🕒 处于盘中时间 (<15:00)，跳过图表发送。")
        sys.exit(0) # 正常退出，不报错
        
    print("🕒 处于收盘后 (>15:00)，开始生成图表...")

    # 3. 只有满足时间条件才执行下面的逻辑
    filename = generate_chart()
    if filename:
        img_url = upload_to_imgbb(filename)
        if img_url:
            send_wxpusher_image(img_url, "每日图表: 恒生科技趋势")
