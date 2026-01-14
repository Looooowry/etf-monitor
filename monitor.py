import akshare as ak
import pandas as pd
import requests
import datetime
import os

# ================= 配置区域 =================
# 你的 PushPlus Token (去 pushplus.plus 官网免费申请)
# 如果使用 GitHub Actions，建议从环境变量读取，本地运行可直接填入字符串
PUSHPLUS_TOKEN = os.environ.get('PUSHPLUS_TOKEN', '你的_PUSHPLUS_TOKEN_填在这里')

# 策略参数
ETF_CODE = "510880"  # 红利ETF
FAST_PERIOD = 20
SLOW_PERIOD = 40
SIGNAL_PERIOD = 15

# ================= 核心函数 =================

def send_wechat_msg(title, content):
    """发送微信通知 (使用 PushPlus)"""
    url = 'http://www.pushplus.plus/send'
    data = {
        "token": PUSHPLUS_TOKEN,
        "title": title,
        "content": content,
        "template": "html"
    }
    try:
        response = requests.post(url, json=data)
        print(f"推送结果: {response.text}")
    except Exception as e:
        print(f"推送失败: {e}")

def calculate_macd(df, fast_p, slow_p, signal_p):
    """计算自定义 MACD"""
    # 计算 EMA
    df['ema_fast'] = df['close'].ewm(span=fast_p, adjust=False).mean()
    df['ema_slow'] = df['close'].ewm(span=slow_p, adjust=False).mean()
    
    # 计算 DIF, DEA, MACD柱
    df['dif'] = df['ema_fast'] - df['ema_slow']
    df['dea'] = df['dif'].ewm(span=signal_p, adjust=False).mean()
    df['macd'] = (df['dif'] - df['dea']) * 2
    return df

def check_strategy():
    print(f"开始执行策略检查: {datetime.datetime.now()}")
    
    # 1. 获取数据 (使用 akshare 获取 ETF 历史数据)
    try:
        # 东财接口，返回数据较快
        df = ak.fund_etf_hist_em(symbol=ETF_CODE, period="daily", adjust="qfq")
        # 重命名列以符合习惯
        df.rename(columns={'日期': 'date', '收盘': 'close'}, inplace=True)
    except Exception as e:
        print(f"获取数据失败: {e}")
        send_wechat_msg("程序报错", f"获取数据失败: {str(e)}")
        return

    # 确保数据足够计算
    if len(df) < SLOW_PERIOD + SIGNAL_PERIOD:
        print("数据量不足")
        return

    # 2. 计算指标
    df = calculate_macd(df, FAST_PERIOD, SLOW_PERIOD, SIGNAL_PERIOD)
    
    # 取最后两行数据（昨天和今天/最新）
    prev_day = df.iloc[-2]
    curr_day = df.iloc[-1]
    
    curr_date_str = curr_day['date']
    
    # 3. 判断信号
    # 定义金叉和死叉
    # 金叉: 昨天 DIF < DEA, 今天 DIF > DEA
    gold_cross = (prev_day['dif'] < prev_day['dea']) and (curr_day['dif'] > curr_day['dea'])
    
    # 死叉: 昨天 DIF > DEA, 今天 DIF < DEA
    death_cross = (prev_day['dif'] > prev_day['dea']) and (curr_day['dif'] < curr_day['dea'])
    
    msg_title = ""
    msg_content = ""
    
    # 打印当前数值方便调试
    info_msg = (f"日期: {curr_date_str}<br>"
                f"当前DIF: {curr_day['dif']:.4f}<br>"
                f"当前DEA: {curr_day['dea']:.4f}<br>"
                f"MACD柱: {curr_day['macd']:.4f}")
    print(info_msg.replace("<br>", "\n"))

    # 执行你的反向策略逻辑
    if gold_cross:
        msg_title = "【卖出信号】红利ETF金叉"
        msg_content = (f"<b>触发时间:</b> {datetime.datetime.now()}<br>"
                       f"<b>信号:</b> 红利ETF ({ETF_CODE}) MACD金叉<br>"
                       f"<b>操作:</b> <span style='color:green'>卖出</span> 恒生科技ETF (515980)<br>"
                       f"<hr>{info_msg}")
        
    elif death_cross:
        msg_title = "【买入信号】红利ETF死叉"
        msg_content = (f"<b>触发时间:</b> {datetime.datetime.now()}<br>"
                       f"<b>信号:</b> 红利ETF ({ETF_CODE}) MACD死叉<br>"
                       f"<b>操作:</b> <span style='color:red'>买入</span> 恒生科技ETF (515980)<br>"
                       f"<hr>{info_msg}")
    
    # 4. 发送通知
    if msg_title:
        print("检测到信号，正在推送...")
        send_wechat_msg(msg_title, msg_content)
    else:
        print("今日无交易信号。")
        # 如果你想每天都收到确认（即使没信号），可以把下面这行注释取消
        # send_wechat_msg("每日巡检：无信号", info_msg)

if __name__ == "__main__":
    check_strategy()
