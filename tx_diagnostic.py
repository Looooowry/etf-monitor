import akshare as ak


SIGNAL_CODE = "sh510880"
START_DATE = "20230101"
END_DATE = "20260320"


print("1. 正在获取原始数据（不做任何处理）...")
try:
    df_raw = ak.stock_zh_a_hist_tx(
        symbol=SIGNAL_CODE,
        start_date=START_DATE,
        end_date=END_DATE,
        adjust="qfq",
    )
    print(f"✅ 数据获取成功！数据形状: {df_raw.shape}")
    print("\n2. 查看原始数据的前几行：")
    print(df_raw.head(3))
    print("\n3. 查看原始数据的列名：")
    print(df_raw.columns.tolist())
    print("\n4. 查看原始数据的索引：")
    print(df_raw.index)
except Exception as e:
    print(f"❌ 数据获取失败: {e}")
