import akshare as ak
import pandas as pd
import requests
import datetime
import os
import pytz # 用于处理时区

# ================= 配置区域 =================
WXPUSHER_TOKEN = os.environ.get('WXPUSHER_TOKEN', '')
WXPUSHER_UID = os.environ.get('WXPUSHER_UID', '')

ETF_CODE = "510880"
FAST_PERIOD = 20
SLOW_PERIOD = 40
SIGNAL_PERIOD = 15

# ================= 核心函数 =================
def send_wxpusher(title, content):
    """发送微信通知"""
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

def get_merged_data():
    """获取历史数据并拼接当前实时数据"""
    # 1. 获取历史数据
    df_hist = ak.fund_etf_hist_em(symbol=ETF_CODE, period="daily", adjust="qfq")
    df_hist.rename(columns={'日期': 'date', '收盘': 'close'}, inplace=True)
    df_hist = df_hist[['date', 'close']]
    
    # 2. 获取实时数据
    try:
        df_spot = ak.fund_etf_spot_em()
        row = df_spot[df_spot['代码'] == ETF_CODE]
        
        if not row.empty:
            current_price = float(row.iloc[0]['最新价'])
            # 获取北京时间日期
            tz_cn = pytz.timezone('Asia/Shanghai')
            current_date = datetime.datetime.now(tz_cn).strftime('%Y-%m-%d')
            
            last_hist_date = df_hist.iloc[-1]['date']
            
            if last_hist_date != current_date:
                # 拼接今日实时数据
                print(f"正在拼接实时数据: {current_date} 价格: {current_price}")
                new_row = pd.DataFrame({'date': [current_date], 'close': [current_price]})
                df_hist = pd.concat([df_hist, new_row], ignore_index=True)
            else:
                # 更新今日收盘价
                print("历史数据已包含今日，更新为最新价格")
                df_hist.iloc[-1, df_hist.columns.get_loc('close')] = current_price
                
    except Exception as e:
        print(f"获取实时数据失败，仅使用历史数据: {e}")
        
    return df_hist

def calculate_macd(df, fast_p, slow_p, signal_p):
    df['ema_fast'] = df['close'].ewm(span=fast_p, adjust=False).mean()
    df['ema_slow'] = df['close'].ewm(span=slow_p, adjust=False).mean()
    df['dif'] = df['ema_fast'] - df['ema_slow']
    df['dea'] = df['dif'].ewm(span=signal_p, adjust=False).mean()
    df['macd'] = (df['dif'] - df['dea']) * 2
    return df

def check_strategy():
    # 获取当前北京时间
    tz_cn = pytz.timezone('Asia/Shanghai')
    now_cn = datetime.datetime.now(tz_cn)
    print(f"开始执行策略检查: {now_cn}")
    
    # 判断运行模式：收盘模式(15点之后) vs 盘中模式(15点之前)
    is_closing_mode = now_cn.hour >= 15
    mode_name = "收盘确认" if is_closing_mode else "盘中预警"

    # 获取数据
    try:
        df = get_merged_data()
    except Exception as e:
        print(f"数据处理错误: {e}")
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
    
    # 构造消息内容
    info_msg = (f"模式: {mode_name}<br>"
                f"参考时间: {curr_day['date']}<br>"
                f"当前价格: {curr_day['close']}<br>"
                f"当前DIF: {curr_day['dif']:.4f}<br>"
                f"当前DEA: {curr_day['dea']:.4f}<br>"
                f"MACD柱: {curr_day['macd']:.4f}")
    
    print(info_msg.replace("<br>", "\n"))

    # === 信号判断逻辑 ===
    
    if gold_cross:
        msg_title = f"【{mode_name}】卖出信号 (金叉)"
        msg_content = f"<span style='color:orange'><b>建议卖出</b></span><br>MACD发生金叉。<br><hr>{info_msg}"
        send_wxpusher(msg_title, msg_content)
        
    elif death_cross:
        msg_title = f"【{mode_name}】买入信号 (死叉)"
        msg_content = f"<span style='color:red'><b>建议买入</b></span><br>MACD发生死叉。<br><hr>{info_msg}"
        send_wxpusher(msg_title, msg_content)
        
    else:
        # === 无信号时的逻辑 ===
        print("无交易信号")
        
        # 如果是【收盘模式】，必须报平安
        if is_closing_mode:
            daily_title = f"监控正常: {ETF_CODE}"
            daily_content = (f"今日收盘无操作信号。<br>"
                             f"<hr>{info_msg}")
            send_wxpusher(daily_title, daily_content)
        
        # 如果是【盘中模式】，无信号则保持沉默，不发送消息
        else:
            print("盘中无信号，不发送通知。")

if __name__ == "__main__":
    check_strategy()
