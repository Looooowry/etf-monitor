import akshare as ak
import pandas as pd
import requests
import datetime
import os

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
    
    # 2. 获取实时数据 (为了盘中能运行)
    try:
        # 获取ETF实时行情
        df_spot = ak.fund_etf_spot_em()
        # 找到我们要的那个ETF
        row = df_spot[df_spot['代码'] == ETF_CODE]
        
        if not row.empty:
            current_price = float(row.iloc[0]['最新价'])
            current_date = datetime.datetime.now().strftime('%Y-%m-%d')
            
            # 检查历史数据最后一天是不是今天
            last_hist_date = df_hist.iloc[-1]['date']
            
            if last_hist_date != current_date:
                # 如果历史数据里没有今天，就把实时数据拼上去
                print(f"正在拼接实时数据: {current_date} 价格: {current_price}")
                new_row = pd.DataFrame({'date': [current_date], 'close': [current_price]})
                df_hist = pd.concat([df_hist, new_row], ignore_index=True)
            else:
                # 如果历史数据里已经有今天了(说明是收盘后很久跑的)，更新一下价格
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
    print(f"开始执行策略检查: {datetime.datetime.now()}")
    
    # 使用新的数据获取函数
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
    
    # 判断信号
    gold_cross = (prev_day['dif'] < prev_day['dea']) and (curr_day['dif'] > curr_day['dea'])
    death_cross = (prev_day['dif'] > prev_day['dea']) and (curr_day['dif'] < curr_day['dea'])
    
    msg_title = ""
    
    info_msg = (f"参考时间: {curr_day['date']}<br>"
                f"当前价格: {curr_day['close']}<br>"
                f"当前DIF: {curr_day['dif']:.4f}<br>"
                f"当前DEA: {curr_day['dea']:.4f}<br>"
                f"MACD柱: {curr_day['macd']:.4f}")
    
    print(info_msg.replace("<br>", "\n"))

    if gold_cross:
        msg_title = "【盘中预警】卖出信号 (金叉)"
        msg_content = f"<span style='color:orange'><b>建议卖出</b></span><br>当前可能正在形成金叉。<br><hr>{info_msg}"
        send_wxpusher(msg_title, msg_content)
        
    elif death_cross:
        msg_title = "【盘中预警】买入信号 (死叉)"
        msg_content = f"<span style='color:red'><b>建议买入</b></span><br>当前可能正在形成死叉。<br><hr>{info_msg}"
        send_wxpusher(msg_title, msg_content)
    else:
        # 每日心跳 (可选)
        print("无信号")
        send_wxpusher(f"监控正常 {curr_day['date']}", info_msg) # 如果嫌烦可以注释掉

if __name__ == "__main__":
    check_strategy()
