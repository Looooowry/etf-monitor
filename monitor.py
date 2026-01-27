import akshare as ak
import pandas as pd
import requests
import datetime
import os
import pytz
import time

# ================= 配置区域 =================
WXPUSHER_TOKEN = os.environ.get('WXPUSHER_TOKEN', '')
WXPUSHER_UID = os.environ.get('WXPUSHER_UID', '')

ETF_CODE = "510880"
FAST_PERIOD = 20
SLOW_PERIOD = 40
SIGNAL_PERIOD = 15

# ================= 核心函数 =================
def send_wxpusher(title, content):
    url = "http://wxpusher.zjiecode.com/api/send/message"
    data = {
        "appToken": WXPUSHER_TOKEN,
        "content": f"<h1>{title}</h1><br>{content}",
        "summary": title,
        "contentType": 2,
        "uids": [WXPUSHER_UID],
    }
    try:
        requests.post(url, json=data)
    except Exception as e:
        print(f"推送错误: {e}")

def get_sina_data_with_retry(code):
    """使用新浪接口获取数据 (抗封锁版)"""
    # 新浪接口要求: 上海基金加 sh, 深圳加 sz
    prefix = "sh" if code.startswith('5') else "sz"
    sina_symbol = prefix + code
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            print(f"📡 正在从新浪获取数据 (第 {attempt + 1} 次)...")
            # 【核心修改】切换为 Sina 接口
            df = ak.fund_etf_hist_sina(symbol=sina_symbol)
            
            # 新浪返回的列名通常是英文: date, open, high, low, close, volume
            # 我们只需要 date 和 close
            df = df[['date', 'close']]
            
            # 确保是日期格式
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
            return df
            
        except Exception as e:
            print(f"❌ 新浪接口报错: {e}")
            time.sleep(5) # 失败稍微歇一下
    
    return None

def get_merged_data():
    """获取数据流程"""
    try:
        # 1. 获取历史数据 (使用新浪)
        df_hist = get_sina_data_with_retry(ETF_CODE)
        if df_hist is None:
            return None
            
        # 2. 尝试获取实时数据 (依然尝试东财，因为新浪实时接口比较复杂，如果东财挂了就只用历史)
        try:
            df_spot = ak.fund_etf_spot_em()
            row = df_spot[df_spot['代码'] == ETF_CODE]
            if not row.empty:
                current_price = float(row.iloc[0]['最新价'])
                tz_cn = pytz.timezone('Asia/Shanghai')
                current_date = datetime.datetime.now(tz_cn).strftime('%Y-%m-%d')
                
                if df_hist.iloc[-1]['date'] != current_date:
                    print(f"拼接实时数据: {current_date} 价格: {current_price}")
                    new_row = pd.DataFrame({'date': [current_date], 'close': [current_price]})
                    df_hist = pd.concat([df_hist, new_row], ignore_index=True)
                else:
                    print("更新今日收盘价")
                    df_hist.iloc[-1, df_hist.columns.get_loc('close')] = current_price
        except Exception:
            print("⚠️ 实时数据获取失败，将使用截止昨日的历史数据运行")
            
        return df_hist
    except Exception as e:
        print(f"数据处理总流程错误: {e}")
        return None

def calculate_macd(df, fast_p, slow_p, signal_p):
    df['ema_fast'] = df['close'].ewm(span=fast_p, adjust=False).mean()
    df['ema_slow'] = df['close'].ewm(span=slow_p, adjust=False).mean()
    df['dif'] = df['ema_fast'] - df['ema_slow']
    df['dea'] = df['dif'].ewm(span=signal_p, adjust=False).mean()
    df['macd'] = (df['dif'] - df['dea']) * 2
    return df

def check_strategy():
    tz_cn = pytz.timezone('Asia/Shanghai')
    now_cn = datetime.datetime.now(tz_cn)
    print(f"开始执行策略检查 (新浪源): {now_cn}")
    
    is_closing_mode = now_cn.hour >= 15
    mode_name = "收盘确认" if is_closing_mode else "盘中预警"

    df = get_merged_data()
    if df is None:
        send_wxpusher("报警: 数据获取失败", "新浪和东财接口均无法访问，请检查 GitHub 网络。")
        return

    if len(df) < SLOW_PERIOD + SIGNAL_PERIOD:
        print("数据量不足")
        return

    df = calculate_macd(df, FAST_PERIOD, SLOW_PERIOD, SIGNAL_PERIOD)
    
    prev_day = df.iloc[-2]
    curr_day = df.iloc[-1]
    
    gold_cross = (prev_day['dif'] < prev_day['dea']) and (curr_day['dif'] > curr_day['dea'])
    death_cross = (prev_day['dif'] > prev_day['dea']) and (curr_day['dif'] < curr_day['dea'])
    
    msg_title = ""
    info_msg = (f"模式: {mode_name}<br>"
                f"参考时间: {curr_day['date']}<br>"
                f"当前价格: {curr_day['close']}<br>"
                f"当前DIF: {curr_day['dif']:.4f}<br>"
                f"当前DEA: {curr_day['dea']:.4f}<br>"
                f"MACD柱: {curr_day['macd']:.4f}")
    
    print(info_msg.replace("<br>", "\n"))

    if gold_cross:
        msg_title = f"【{mode_name}】卖出信号 (金叉)"
        msg_content = f"<span style='color:orange'><b>建议卖出</b></span><br>MACD发生金叉。<br><hr>{info_msg}"
        send_wxpusher(msg_title, msg_content)
    elif death_cross:
        msg_title = f"【{mode_name}】买入信号 (死叉)"
        msg_content = f"<span style='color:red'><b>建议买入</b></span><br>MACD发生死叉。<br><hr>{info_msg}"
        send_wxpusher(msg_title, msg_content)
    else:
        print("无交易信号")
        if is_closing_mode:
            daily_title = f"监控正常: {ETF_CODE}"
            daily_content = f"今日无操作信号。<br><hr>{info_msg}"
            send_wxpusher(daily_title, daily_content)

if __name__ == "__main__":
    check_strategy()
