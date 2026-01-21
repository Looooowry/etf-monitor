import akshare as ak
import pandas as pd
import requests
import datetime
import os
import pytz
import numpy as np  # 必须确保 requirements.txt 里加了 numpy

# ================= 配置区域 =================
WXPUSHER_TOKEN = os.environ.get('WXPUSHER_TOKEN', '')
WXPUSHER_UID = os.environ.get('WXPUSHER_UID', '')

# --- 标的设置 ---
SIGNAL_CODE = "510880"   # 信号源：红利ETF (用于计算MACD)
TARGET_CODE = "515980"   # 交易标的：恒生科技ETF (用于计算相关性)

# --- MACD 参数 ---
FAST_PERIOD = 21
SLOW_PERIOD = 42
SIGNAL_PERIOD = 16

# --- 风控参数 ---
VOL_WINDOW = 20          # 波动率计算窗口
CORR_WINDOW = 20         # 相关性计算窗口
EXTREME_VOL_THRESHOLD = 0.03   # 极端波动率阈值 (3%)
EXTREME_CORR_THRESHOLD = 0.7   # 极端正相关性阈值 (70%)

# ================= 核心工具函数 =================

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

def get_data_for_risk_analysis():
    """获取双标的数据并对齐"""
    try:
        # 1. 获取信号源 (红利)
        df_signal = ak.fund_etf_hist_em(symbol=SIGNAL_CODE, period="daily", adjust="qfq")
        df_signal = df_signal[['日期', '收盘']].rename(columns={'日期': 'date', '收盘': 'close_signal'})
        df_signal['date'] = pd.to_datetime(df_signal['date'])
        df_signal.set_index('date', inplace=True)

        # 2. 获取标的 (恒生科技)
        df_target = ak.fund_etf_hist_em(symbol=TARGET_CODE, period="daily", adjust="qfq")
        df_target = df_target[['日期', '收盘']].rename(columns={'日期': 'date', '收盘': 'close_target'})
        df_target['date'] = pd.to_datetime(df_target['date'])
        df_target.set_index('date', inplace=True)

        # 3. 合并
        df_merged = pd.concat([df_signal, df_target], axis=1, join='inner')
        
        # 4. 尝试获取实时数据拼接 (盘中用)
        try:
            spot_signal = ak.fund_etf_spot_em()
            row_signal = spot_signal[spot_signal['代码'] == SIGNAL_CODE]
            
            spot_target = ak.fund_etf_spot_em()
            row_target = spot_target[spot_target['代码'] == TARGET_CODE]

            if not row_signal.empty and not row_target.empty:
                current_price_signal = float(row_signal.iloc[0]['最新价'])
                current_price_target = float(row_target.iloc[0]['最新价'])
                
                tz_cn = pytz.timezone('Asia/Shanghai')
                today = datetime.datetime.now(tz_cn).replace(hour=0, minute=0, second=0, microsecond=0)
                
                if df_merged.index[-1] != today:
                    print(f"拼接实时数据: 红利{current_price_signal}, 恒科{current_price_target}")
                    new_row = pd.DataFrame({
                        'close_signal': [current_price_signal],
                        'close_target': [current_price_target]
                    }, index=[today])
                    df_merged = pd.concat([df_merged, new_row])
                else:
                    df_merged.iloc[-1, 0] = current_price_signal
                    df_merged.iloc[-1, 1] = current_price_target
        except Exception:
            pass # 实时获取失败则忽略

        return df_merged

    except Exception as e:
        print(f"数据获取失败: {e}")
        return None

def calculate_indicators(df):
    """计算指标"""
    # MACD
    df['ema_fast'] = df['close_signal'].ewm(span=FAST_PERIOD, adjust=False).mean()
    df['ema_slow'] = df['close_signal'].ewm(span=SLOW_PERIOD, adjust=False).mean()
    df['dif'] = df['ema_fast'] - df['ema_slow']
    df['dea'] = df['dif'].ewm(span=SIGNAL_PERIOD, adjust=False).mean()
    df['macd'] = (df['dif'] - df['dea']) * 2

    # 收益率
    df['ret_signal'] = df['close_signal'].pct_change()
    df['ret_target'] = df['close_target'].pct_change()

    # 波动率 & 相关性
    df['volatility'] = df['ret_signal'].rolling(window=VOL_WINDOW).std()
    df['correlation'] = df['ret_signal'].rolling(window=CORR_WINDOW).corr(df['ret_target'])

    return df

def check_strategy():
    tz_cn = pytz.timezone('Asia/Shanghai')
    now_cn = datetime.datetime.now(tz_cn)
    print(f"执行风控策略检查: {now_cn}")

    is_closing_mode = now_cn.hour >= 15
    mode_name = "收盘确认" if is_closing_mode else "盘中预警"

    df = get_data_for_risk_analysis()
    if df is None or len(df) < max(SLOW_PERIOD, CORR_WINDOW) + 5:
        print("数据不足")
        return

    df = calculate_indicators(df)
    
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    
    # 提取指标
    curr_dif, curr_dea = curr['dif'], curr['dea']
    prev_dif, prev_dea = prev['dif'], prev['dea']
    vol, corr = curr['volatility'], curr['correlation']

    # 信号判断
    gold_cross = (prev_dif < prev_dea) and (curr_dif > curr_dea)
    death_cross = (prev_dif > prev_dea) and (curr_dif < curr_dea)

    # === 风控逻辑 ===
    risk_triggered = False
    risk_msg = ""

    # 条件A: 极端风险
    if vol > EXTREME_VOL_THRESHOLD and corr > EXTREME_CORR_THRESHOLD:
        risk_triggered = True
        risk_msg = f"极端风控 (Vol:{vol:.2%} > 3%, Corr:{corr:.2f} > 0.7)"
    
    # 条件B: 连续高度相关
    recent_corrs = df['correlation'].tail(5)
    if len(recent_corrs) == 5 and (recent_corrs > 0.8).all():
        risk_triggered = True
        risk_msg = f"结构性风控 (连续5天相关性 > 0.8)"

    # === 构造消息 ===
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
            send_wxpusher(msg_title, msg_content)
        else:
            msg_title = f"【{mode_name}】卖出信号 (金叉)"
            msg_content = f"<span style='color:orange'><b>建议卖出 (风控通过)</b></span><br><hr>{info_msg}"
            send_wxpusher(msg_title, msg_content)

    elif death_cross:
        if risk_triggered:
            msg_title = f"【{mode_name}】信号被拦截 (死叉)"
            msg_content = f"<span style='color:gray'><b>原策略买入，但风控拦截。</b></span><br>原因: {risk_msg}<br><hr>{info_msg}"
            send_wxpusher(msg_title, msg_content)
        else:
            msg_title = f"【{mode_name}】买入信号 (死叉)"
            msg_content = f"<span style='color:red'><b>建议买入 (风控通过)</b></span><br><hr>{info_msg}"
            send_wxpusher(msg_title, msg_content)

    else:
        # 无信号时
        if is_closing_mode:
            # 收盘时发送日报，方便你对比两个策略的数据
            status_text = f"高风险状态 ({risk_msg})" if risk_triggered else "市场情绪稳定"
            daily_title = f"风控日报: {SIGNAL_CODE}"
            daily_content = f"{status_text}<br>今日无操作信号。<br><hr>{info_msg}"
            send_wxpusher(daily_title, daily_content)

if __name__ == "__main__":
    check_strategy()
