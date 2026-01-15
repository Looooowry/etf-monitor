import akshare as ak
import pandas as pd
import matplotlib
# 【关键】设置后端为 Agg，这样服务器没屏幕也能画图
matplotlib.use('Agg') 
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import datetime
import requests
import os

# ================= 配置区域 =================
WXPUSHER_TOKEN = os.environ.get('WXPUSHER_TOKEN', '')
WXPUSHER_UID = os.environ.get('WXPUSHER_UID', '')

# 策略参数
view_start_date = '2024-12-30' # 你可以根据需要修改这个查看起始日
lag_days = 150
fetch_start_date = '2023-01-01'

# 锚点对齐参数
anchor_hstech = 6700
anchor_ratio = 160
ratio_factor = anchor_ratio / anchor_hstech
hstech_ylim_top = 9500
hstech_ylim_bottom = 2500

# ================= 核心功能函数 =================

def upload_image_to_catbox(file_path):
    """
    将图片上传到 Catbox 图床 (免费、长期、无需key)
    返回图片 URL
    """
    try:
        url = "https://catbox.moe/user/api.php"
        data = {'reqtype': 'fileupload', 'userhash': ''}
        with open(file_path, 'rb') as f:
            files = {'fileToUpload': f}
            print("正在上传图片到图床...")
            response = requests.post(url, data=data, files=files)
            if response.status_code == 200:
                img_url = response.text
                print(f"图片上传成功: {img_url}")
                return img_url
            else:
                print(f"上传失败: {response.text}")
                return None
    except Exception as e:
        print(f"上传过程出错: {e}")
        return None

def send_wxpusher_image(img_url, summary):
    """发送包含图片的通知"""
    url = "http://wxpusher.zjiecode.com/api/send/message"
    
    # 构造 HTML 内容，使用 img 标签显示图片
    content = (
        f"<h1>{summary}</h1><br>"
        f"📅 日期: {datetime.datetime.now().strftime('%Y-%m-%d')}<br>"
        f"<p>恒生科技 vs 铜油比 (滞后{lag_days}天)</p>"
        f"<hr>"
        f"<img src='{img_url}' width='100%' /><br>"
        f"<p style='font-size:12px; color:gray;'>*图片由 GitHub Actions 自动生成</p>"
    )
    
    data = {
        "appToken": WXPUSHER_TOKEN,
        "content": content,
        "summary": summary,
        "contentType": 2, # HTML
        "uids": [WXPUSHER_UID],
    }
    try:
        requests.post(url, json=data)
        print("微信推送成功")
    except Exception as e:
        print(f"微信推送错误: {e}")

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
        print("❌ 数据获取失败，终止绘图")
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

    # 坐标计算
    ratio_ylim_bottom = hstech_ylim_bottom * ratio_factor
    ratio_ylim_top = hstech_ylim_top * ratio_factor

    # 绘图
    plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'bmh')
    fig, ax1 = plt.subplots(figsize=(12, 8)) # 调整尺寸适配手机屏幕

    # HSTECH
    color1 = '#004c6d'
    ax1.plot(plot_hstech.index, plot_hstech, color=color1, linewidth=1.8, label='Hang Seng TECH', alpha=0.95)
    ax1.set_ylabel('Hang Seng TECH Index', color=color1, fontsize=12, fontweight='bold')
    ax1.tick_params(axis='y', labelcolor=color1)
    ax1.set_ylim(hstech_ylim_bottom, hstech_ylim_top)

    # Ratio
    ax2 = ax1.twinx()
    color2 = '#d62728'
    ax2.plot(plot_ratio.index, plot_ratio, color=color2, linewidth=1.5, linestyle='-',
             label=f'LME/Brent Ratio (+{lag_days}d)', alpha=0.9)
    ax2.set_ylabel(f'LME Copper / Brent Ratio', color=color2, fontsize=12, fontweight='bold')
    ax2.tick_params(axis='y', labelcolor=color2)
    ax2.set_ylim(ratio_ylim_bottom, ratio_ylim_top)

    # 辅助
    if plot_ratio.index[0] <= today <= plot_ratio.index[-1]:
        ax1.axvline(today, color='black', linestyle='--', linewidth=1.5)
        # ax1.text(today, ax1.get_ylim()[0], ' TODAY', rotation=90, verticalalignment='bottom')

    plt.title(f'HSTECH vs Copper/Oil (+{lag_days}d)', fontsize=14)
    ax1.set_xlim(left=pd.to_datetime(view_start_date), right=plot_ratio.index[-1])

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')

    # X轴格式
    date_fmt = mdates.DateFormatter('%y-%m-%d')
    ax1.xaxis.set_major_formatter(date_fmt)
    ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
    plt.setp(ax1.get_xticklabels(), rotation=90, ha='center', fontsize=10)
    ax1.grid(True, which='major', axis='x', linestyle='--', alpha=0.5)
    plt.subplots_adjust(bottom=0.15)

    # 保存图片
    filename = "chart_output.png"
    plt.savefig(filename, dpi=100)
    print(f"✅ 图表已生成: {filename}")
    plt.close() # 释放内存
    return filename

if __name__ == "__main__":
    # 1. 生成图片
    img_path = generate_chart()
    
    if img_path:
        # 2. 上传图片
        img_url = upload_image_to_catbox(img_path)
        
        if img_url:
            # 3. 发送微信
            send_wxpusher_image(img_url, "每日图表: 恒生科技趋势")
        else:
            print("图片上传失败，无法发送")
