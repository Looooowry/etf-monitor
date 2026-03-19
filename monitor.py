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
MA_PERIOD = 250
SELL_PROFIT_TARGET = 0.075
INITIAL_CAPITAL = 100000.0
LOT_SIZE = 100
HISTORY_START_DATE = "20180101"

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
    """使用东方财富接口获取前复权历史数据"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            print(f"📡 正在从东方财富获取数据 (第 {attempt + 1} 次)...")
            df = ak.fund_etf_hist_em(
                symbol=code,
                period="daily",
                start_date=HISTORY_START_DATE,
                adjust="qfq",
            )
            df = df[['日期', '收盘']].rename(columns={'日期': 'date', '收盘': 'close'})
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
            return df
            
        except Exception as e:
            print(f"❌ 东方财富接口报错: {e}")
            time.sleep(5) # 失败稍微歇一下
    
    return None

def get_merged_data():
    """获取数据流程"""
    try:
        # 1. 获取历史数据 (使用东方财富前复权)
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

        df_hist['close'] = pd.to_numeric(df_hist['close'], errors='coerce')
        df_hist = df_hist.dropna(subset=['close'])
        df_hist = df_hist.sort_values('date').drop_duplicates(subset='date', keep='last').reset_index(drop=True)
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

def calculate_ma250_strategy(df):
    df = df.copy()
    df['ma250'] = df['close'].rolling(window=MA_PERIOD).mean()

    actions = []
    below_ma250_flags = []
    buy_condition_flags = []
    sell_condition_flags = []
    has_position_before_flags = []
    avg_cost_before_values = []
    profit_rate_before_values = []
    target_sell_price_before_values = []
    trade_shares_values = []
    trade_value_values = []
    realized_profit_values = []
    cash_values = []
    shares_values = []
    avg_cost_values = []
    has_position_values = []
    current_profit_rate_values = []
    current_target_sell_price_values = []
    portfolio_value_values = []

    cash = INITIAL_CAPITAL
    shares = 0
    avg_cost = 0.0

    for _, row in df.iterrows():
        price = float(row['close'])
        ma250 = row['ma250']

        has_position_before = shares > 0
        avg_cost_before = avg_cost if has_position_before else 0.0
        below_ma250 = pd.notna(ma250) and price < float(ma250)
        profit_rate_before = (price / avg_cost_before - 1) if has_position_before and avg_cost_before > 0 else 0.0
        target_sell_price_before = avg_cost_before * (1 + SELL_PROFIT_TARGET) if has_position_before else 0.0

        buy_condition = below_ma250 and not has_position_before
        sell_condition = has_position_before and profit_rate_before >= SELL_PROFIT_TARGET

        action = "hold"
        trade_shares = 0
        trade_value = 0.0
        realized_profit = 0.0

        if buy_condition:
            buy_shares = int(cash / price / LOT_SIZE) * LOT_SIZE
            if buy_shares > 0:
                trade_shares = buy_shares
                trade_value = buy_shares * price
                cash -= trade_value
                shares = buy_shares
                avg_cost = price
                action = "buy"
            else:
                buy_condition = False
        elif sell_condition:
            trade_shares = shares
            trade_value = shares * price
            realized_profit = (price - avg_cost_before) * shares
            cash += trade_value
            shares = 0
            avg_cost = 0.0
            action = "sell"

        has_position = shares > 0
        current_avg_cost = avg_cost if has_position else 0.0
        current_profit_rate = (price / current_avg_cost - 1) if has_position and current_avg_cost > 0 else 0.0
        current_target_sell_price = current_avg_cost * (1 + SELL_PROFIT_TARGET) if has_position else 0.0
        portfolio_value = cash + shares * price

        actions.append(action)
        below_ma250_flags.append(below_ma250)
        buy_condition_flags.append(buy_condition)
        sell_condition_flags.append(sell_condition)
        has_position_before_flags.append(has_position_before)
        avg_cost_before_values.append(avg_cost_before)
        profit_rate_before_values.append(profit_rate_before)
        target_sell_price_before_values.append(target_sell_price_before)
        trade_shares_values.append(trade_shares)
        trade_value_values.append(trade_value)
        realized_profit_values.append(realized_profit)
        cash_values.append(cash)
        shares_values.append(shares)
        avg_cost_values.append(current_avg_cost)
        has_position_values.append(has_position)
        current_profit_rate_values.append(current_profit_rate)
        current_target_sell_price_values.append(current_target_sell_price)
        portfolio_value_values.append(portfolio_value)

    df['ma_action'] = actions
    df['below_ma250'] = below_ma250_flags
    df['buy_condition'] = buy_condition_flags
    df['sell_condition'] = sell_condition_flags
    df['has_position_before'] = has_position_before_flags
    df['avg_cost_before'] = avg_cost_before_values
    df['profit_rate_before'] = profit_rate_before_values
    df['target_sell_price_before'] = target_sell_price_before_values
    df['trade_shares'] = trade_shares_values
    df['trade_value'] = trade_value_values
    df['realized_profit'] = realized_profit_values
    df['cash'] = cash_values
    df['shares'] = shares_values
    df['avg_cost'] = avg_cost_values
    df['has_position'] = has_position_values
    df['current_profit_rate'] = current_profit_rate_values
    df['current_target_sell_price'] = current_target_sell_price_values
    df['portfolio_value'] = portfolio_value_values
    return df

def format_optional_price(value):
    if value is None or pd.isna(value) or value <= 0:
        return "-"
    return f"{value:.4f}"

def format_optional_pct(value):
    if value is None or pd.isna(value):
        return "-"
    return f"{value:.2%}"

def bool_to_text(value):
    return "是" if bool(value) else "否"

def check_strategy():
    tz_cn = pytz.timezone('Asia/Shanghai')
    now_cn = datetime.datetime.now(tz_cn)
    print(f"开始执行策略检查 (东方财富历史源): {now_cn}")
    
    is_closing_mode = now_cn.hour >= 15
    mode_name = "收盘确认" if is_closing_mode else "盘中预警"

    df = get_merged_data()
    if df is None:
        send_wxpusher("报警: 数据获取失败", "东方财富历史接口和东财实时接口均无法访问，请检查 GitHub 网络。")
        return

    if len(df) < SLOW_PERIOD + SIGNAL_PERIOD:
        print("数据量不足")
        return

    df = calculate_macd(df, FAST_PERIOD, SLOW_PERIOD, SIGNAL_PERIOD)
    df = calculate_ma250_strategy(df)
    
    prev_day = df.iloc[-2]
    curr_day = df.iloc[-1]
    
    gold_cross = (prev_day['dif'] < prev_day['dea']) and (curr_day['dif'] > curr_day['dea'])
    death_cross = (prev_day['dif'] > prev_day['dea']) and (curr_day['dif'] < curr_day['dea'])

    macd_signal_text = "卖出信号 (金叉)" if gold_cross else "买入信号 (死叉)" if death_cross else "无信号"

    ma_action = curr_day['ma_action']
    ma_signal_text = "无动作"
    if ma_action == "buy":
        ma_signal_text = "买入信号 (低于250日线)"
    elif ma_action == "sell":
        ma_signal_text = "清仓信号 (收益达到7.5%)"
    elif curr_day['has_position']:
        ma_signal_text = "持仓中，等待止盈"
    else:
        ma_signal_text = "空仓，等待买点"

    display_cost = curr_day['avg_cost_before'] if ma_action == "sell" else curr_day['avg_cost']
    display_profit_rate = curr_day['profit_rate_before'] if ma_action == "sell" else (
        curr_day['current_profit_rate'] if curr_day['has_position'] else None
    )
    display_target_sell_price = curr_day['target_sell_price_before'] if ma_action == "sell" else curr_day['current_target_sell_price']
    position_status = "已清仓" if ma_action == "sell" else "持仓中" if curr_day['has_position'] else "空仓"

    macd_info_msg = (f"<b>【MACD监控】</b><br>"
                     f"模式: {mode_name}<br>"
                     f"参考时间: {curr_day['date']}<br>"
                     f"当前价格: {curr_day['close']:.4f}<br>"
                     f"当前DIF: {curr_day['dif']:.4f}<br>"
                     f"当前DEA: {curr_day['dea']:.4f}<br>"
                     f"MACD柱: {curr_day['macd']:.4f}<br>"
                     f"当日信号: {macd_signal_text}")

    ma_info_msg = (f"<b>【250日线仓位监控】</b><br>"
                   f"模式: {mode_name}<br>"
                   f"参考时间: {curr_day['date']}<br>"
                   f"当前价格: {curr_day['close']:.4f}<br>"
                   f"250日线: {format_optional_price(curr_day['ma250'])}<br>"
                   f"是否低于250日线: {bool_to_text(curr_day['below_ma250'])}<br>"
                   f"买入条件满足: {bool_to_text(curr_day['buy_condition'])}<br>"
                   f"7.5%清仓条件满足: {bool_to_text(curr_day['sell_condition'])}<br>"
                   f"模拟账户初始资金: {INITIAL_CAPITAL:,.0f} 元<br>"
                   f"持仓状态: {position_status}<br>"
                   f"持仓份额: {int(curr_day['shares'])}<br>"
                   f"持仓成本价: {format_optional_price(display_cost)}<br>"
                   f"当前收益率: {format_optional_pct(display_profit_rate)}<br>"
                   f"目标清仓价: {format_optional_price(display_target_sell_price)}<br>"
                   f"当日动作: {ma_signal_text}<br>"
                   f"当次成交份额: {int(curr_day['trade_shares'])}<br>"
                   f"当次成交金额: {curr_day['trade_value']:.2f} 元<br>"
                   f"当次实现收益: {curr_day['realized_profit']:.2f} 元<br>"
                   f"模拟现金: {curr_day['cash']:.2f} 元<br>"
                   f"模拟总资产: {curr_day['portfolio_value']:.2f} 元")

    print(macd_info_msg.replace("<br>", "\n"))
    print(ma_info_msg.replace("<br>", "\n"))

    signal_titles = []
    signal_summaries = []

    if gold_cross:
        signal_titles.append("MACD卖出")
        signal_summaries.append("<span style='color:orange'><b>MACD卖出信号</b></span><br>MACD发生金叉。")
    elif death_cross:
        signal_titles.append("MACD买入")
        signal_summaries.append("<span style='color:red'><b>MACD买入信号</b></span><br>MACD发生死叉。")

    if ma_action == "buy":
        signal_titles.append("250日线买入")
        signal_summaries.append(
            f"<span style='color:red'><b>250日线买入信号</b></span><br>"
            f"当前价格低于250日线，模拟账户按 {INITIAL_CAPITAL:,.0f} 元全仓买入。"
        )
    elif ma_action == "sell":
        signal_titles.append("7.5%止盈清仓")
        signal_summaries.append(
            f"<span style='color:orange'><b>250日线清仓信号</b></span><br>"
            f"模拟持仓收益率达到 {SELL_PROFIT_TARGET:.2%}，执行清仓。"
        )

    if signal_titles:
        msg_title = f"【{mode_name}】" + " / ".join(signal_titles)
        msg_content = "<br><hr>".join(signal_summaries + [macd_info_msg, ma_info_msg])
        send_wxpusher(msg_title, msg_content)
    else:
        print("无新交易信号")
        if is_closing_mode:
            daily_title = f"监控正常: {ETF_CODE}"
            daily_content = f"今日无新交易信号。<br><hr>{macd_info_msg}<br><hr>{ma_info_msg}"
            send_wxpusher(daily_title, daily_content)

if __name__ == "__main__":
    check_strategy()
