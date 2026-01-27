import akshare as ak
import pandas as pd
import requests
import datetime
import os
import pytz
import time
import numpy as np

# ================= 配置区域 =================
WXPUSHER_TOKEN = os.environ.get('WXPUSHER_TOKEN', '')
WXPUSHER_UID = os.environ.get('WXPUSHER_UID', '')

SIGNAL_CODE = "510880"   # 红利
TARGET_CODE = "515980"   # 恒生科技

FAST_PERIOD = 21
SLOW_PERIOD = 42
SIGNAL_PERIOD = 16

VOL_WINDOW = 20
CORR_WINDOW = 20
EXTREME_VOL_THRESHOLD = 0.03
EXTREME_CORR_THRESHOLD = 0.7

# ================= 核心工具函数 =================
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

def get_sina_data(code, retries=3):
    """从新浪获取单个ETF数据"""
    prefix = "sh" if code.startswith('5') else "sz"
    symbol = prefix + code
    
    for i in range(retries):
        try:
            print(f"📡 正在获取 {code} (新浪源)...")
            df = ak.fund_etf_hist_sina(symbol=symbol)
            df = df[['date', 'close']]
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            return df
        except Exception as e:
            print(f"❌ 获取 {code} 失败: {e}")
            time.sleep(3)
    return None

def get_data_for_risk_analysis():
    """获取双标的数据并对齐"""
    # 1. 获取信号源 (红利) - 新浪
    df_signal = get_sina_data(SIGNAL_CODE)
    if df_signal is None: return None
    df_signal.rename(columns={'close': 'close_signal'}, inplace=True)

    # 2. 获取标的 (恒生科技) - 新浪
    df_target = get_sina_data(TARGET_CODE)
    if df_target is None: return None
    df_target.rename(columns={'close': 'close_target'}, inplace=True)

    # 3. 合并
    df_merged = pd.concat([df_signal, df_target], axis=1, join='inner')
    
    # 4. 尝试实时补全 (可选，失败不影响主流程)
    try:
        spot = ak.fund_etf_spot_em() # 实时接口依然尝试一下东财，挂了也没事
        row_signal = spot[spot['代码'] == SIGNAL_CODE]
        row_target = spot[spot['代码'] == TARGET_CODE]

        if not row_signal.empty and not row_target.empty:
            curr_sig = float(row_signal.iloc[0]['最新价'])
            curr_tar = float(row_target.iloc[0]['最新价'])
            
            tz_cn = pytz.timezone('Asia/Shanghai')
            today = datetime.datetime.now(tz_cn).replace(hour=0, minute=0, second=0, microsecond=0)
            
            if df_merged.index[-1] != today:
                new_row = pd.DataFrame({
                    'close_signal': [curr_sig],
                    'close_target': [curr_tar]
                }, index=[today])
                df_merged = pd.concat([df_merged, new_row])
            else:
                df_merged.iloc[-1, 0] = curr_sig
                df_merged.iloc[-1, 1] = curr_tar
    except Exception:
        pass

    return df_merged

def calculate_indicators(df):
    df['ema_fast'] = df['close_signal'].ewm(span=FAST_PERIOD, adjust=False).mean()
    df['ema_slow'] = df['close_signal'].ewm(span=SLOW_PERIOD, adjust=False).mean()
    df['dif'] = df['ema_fast'] - df['ema_slow']
    df['dea'] = df['dif'].ewm(span=SIGNAL_PERIOD, adjust=False).mean()
    df['macd'] = (df['dif'] - df['dea']) * 2

    df['ret_signal'] = df['close_signal'].pct_change()
    df['ret_target'] = df['close_target'].pct_change()
    df['volatility'] = df['ret_signal'].rolling(window=VOL_WINDOW).std()
    df['correlation'] = df['ret_signal'].rolling(window=CORR_WINDOW).corr(df['ret_target'])
    return df

def check_strategy():
    tz_cn = pytz.timezone('Asia/Shanghai')
    now_cn = datetime.datetime.now(tz_cn)
    print(f"执行风控策略 (新浪源): {now_cn}")

    is_closing_mode = now_cn.hour >= 15
    mode_name = "收盘确认" if is_closing_mode else "盘中预警"

    df = get_data_for_risk_analysis()
    if df is None or len(df) < max(SLOW_PERIOD, CORR_WINDOW) + 5:
        send_wxpusher("风控报警", "数据获取失败，无法计算指标。")
        return

    df = calculate_indicators(df)
    
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    
    curr_dif, curr_dea = curr['dif'], curr['dea']
    prev_dif, prev_dea = prev['dif'], prev['dea']
    vol, corr = curr['volatility'], curr['correlation']

    gold_cross = (prev_dif < prev_dea) and (curr_dif > curr_dea)
    death_cross = (prev_dif > prev_dea) and (curr_dif < curr_dea)

    risk_triggered = False
    risk_msg = ""
    if vol > EXTREME_VOL_THRESHOLD and corr > EXTREME_CORR_THRESHOLD:
        risk_triggered = True
        risk_msg = f"极端风控 (Vol:{vol:.2%} > 3%, Corr:{corr:.2f} > 0.7)"
    
    recent_corrs = df['correlation'].tail(5)
    if len(recent_corrs) == 5 and (recent_corrs > 0.8).all():
        risk_triggered = True
        risk_msg = f"结构性风控 (连续5天相关性 > 0.8)"

    info_msg = (f"<b>【高级风控版】</b><br>"
                f"模式: {mode_name}<br>"
                f"日期: {curr.name.strftime('%Y-%m-%d')}<br>"
                f"------------------<br>"
                f"波动率: {vol:.2%} {'⚠️' if vol>0.03 else '✅'}<br>"
                f"相关性: {corr:.2f} {'⚠️' if corr>0.7 else '✅'}<br>"
                f"风控状态: {'<span style=color:red><b>拦截中</b></span>' if risk_triggered else '<span style=color:green>正常</span>'}<br>"
                f"------------------<br>"
                f"DIF: {curr_dif:.4f}<br>"
                f"DEA: {curr_dea:.4f}")
    
    print(info_msg.replace("<br>", "\n"))

    msg_title = ""
    if gold_cross:
        if risk_triggered:
            msg_title = f"【{mode_name}】信号被拦截 (金叉)"
            msg_content = f"<span style='color:gray'><b>原策略卖出，但风控拦截。</b></span><br>原因: {risk_msg}<br><hr>{info_msg}"
        else:
            msg_title = f"【{mode_name}】卖出信号 (金叉)"
            msg_content = f"<span style='color:orange'><b>建议卖出 (风控通过)</b></span><br><hr>{info_msg}"
        send_wxpusher(msg_title, msg_content)
    elif death_cross:
        if risk_triggered:
            msg_title = f"【{mode_name}】信号被拦截 (死叉)"
            msg_content = f"<span style='color:gray'><b>原策略买入，但风控拦截。</b></span><br>原因: {risk_msg}<br><hr>{info_msg}"
        else:
            msg_title = f"【{mode_name}】买入信号 (死叉)"
            msg_content = f"<span style='color:red'><b>建议买入 (风控通过)</b></span><br><hr>{info_msg}"
        send_wxpusher(msg_title, msg_content)
    else:
        if is_closing_mode:
            status_text = f"高风险状态 ({risk_msg})" if risk_triggered else "市场情绪稳定"
            daily_title = f"风控日报: {SIGNAL_CODE}"
            daily_content = f"{status_text}<br>今日无操作信号。<br><hr>{info_msg}"
            send_wxpusher(daily_title, daily_content)

if __name__ == "__main__":
    check_strategy()
