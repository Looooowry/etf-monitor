import akshare as ak
import pandas as pd
import requests
import datetime
import os

# ================= 配置区域 =================
# 这里我们从 GitHub 的 Secrets 读取那两个码
# 如果你在本地运行，可以直接把字符串填在 '' 里面
WXPUSHER_TOKEN = os.environ.get('WXPUSHER_TOKEN', '') 
WXPUSHER_UID = os.environ.get('WXPUSHER_UID', '')

# 策略参数
ETF_CODE = "510880"  # 红利ETF
FAST_PERIOD = 20
SLOW_PERIOD = 40
SIGNAL_PERIOD = 15

# ================= 核心函数 =================

def send_wxpusher(title, content):
    """发送微信通知 (使用 WxPusher)"""
    url = "http://wxpusher.zjiecode.com/api/send/message"
    data = {
        "appToken": WXPUSHER_TOKEN,
        "content": f"<h1>{title}</h1><br>{content}",
        "summary": title, # 消息卡片上显示的摘要
        "contentType": 2, # 内容类型 2 表示 HTML
        "uids": [WXPUSHER_UID],
    }
    try:
        response = requests.post(url, json=data)
        res_json = response.json()
        if res_json['success']:
            print("推送成功")
        else:
            print(f"推送失败: {res_json['msg']}")
    except Exception as e:
        print(f"推送请求错误: {e}")

def calculate_macd(df, fast_p, slow_p, signal_p):
    """计算自定义 MACD"""
    df['ema_fast'] = df['close'].ewm(span=fast_p, adjust=False).mean()
    df['ema_slow'] = df['close'].ewm(span=slow_p, adjust=False).mean()
    df['dif'] = df['ema_fast'] - df['ema_slow']
    df['dea'] = df['dif'].ewm(span=signal_p, adjust=False).mean()
    df['macd'] = (df['dif'] - df['dea']) * 2
    return df

def check_strategy():
    print(f"开始执行策略检查: {datetime.datetime.now()}")
    
    # 1. 获取数据
    try:
        df = ak.fund_etf_hist_em(symbol=ETF_CODE, period="daily", adjust="qfq")
        df.rename(columns={'日期': 'date', '收盘': 'close'}, inplace=True)
    except Exception as e:
        print(f"获取数据失败: {e}")
        return

    if len(df) < SLOW_PERIOD + SIGNAL_PERIOD:
        print("数据量不足")
        return

    # 2. 计算指标
    df = calculate_macd(df, FAST_PERIOD, SLOW_PERIOD, SIGNAL_PERIOD)
    
    prev_day = df.iloc[-2]
    curr_day = df.iloc[-1]
    curr_date_str = curr_day['date']
    
    # 3. 判断信号
    gold_cross = (prev_day['dif'] < prev_day['dea']) and (curr_day['dif'] > curr_day['dea'])
    death_cross = (prev_day['dif'] > prev_day['dea']) and (curr_day['dif'] < curr_day['dea'])
    
    msg_title = ""
    msg_content = ""
    
    # 构造基本信息
    info_msg = (f"日期: {curr_date_str}<br>"
                f"当前DIF: {curr_day['dif']:.4f}<br>"
                f"当前DEA: {curr_day['dea']:.4f}<br>"
                f"MACD柱: {curr_day['macd']:.4f}")
    
    print(info_msg.replace("<br>", "\n"))

    if gold_cross:
        msg_title = "【卖出信号】红利ETF金叉"
        msg_content = (f"<span style='color:orange'><b>触发操作：卖出</b></span><br>"
                       f"恒生科技ETF (515980)<br>"
                       f"<hr>{info_msg}")
        
    elif death_cross:
        msg_title = "【买入信号】红利ETF死叉"
        msg_content = (f"<span style='color:red'><b>触发操作：买入</b></span><br>"
                       f"恒生科技ETF (515980)<br>"
                       f"<hr>{info_msg}")
    
    # 4. 发送通知
    if msg_title:
        print("检测到信号，正在推送...")
        send_wxpusher(msg_title, msg_content)
    else:
        print("今日无交易信号。")

if __name__ == "__main__":
    # 【新增】这两行是强制测试代码
    print("正在发送测试消息...")
    send_wxpusher("测试成功", "恭喜！如果你看到这条消息，说明你的 GitHub Actions 监控机器人已经活了！")

    # 原来的策略检查
    check_strategy()
