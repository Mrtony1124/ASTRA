# generate_data_file.py
import json
import shared_logic  # 确保此文件与 shared_logic.py 在同一目录
import time

# --- 配置 ---
# 您可以修改这个值来生成不同规模的数据文件
NUM_ENTRIES = 100_000_000
HASH_LEN_BYTES = 32
OUTPUT_FILE = f"database_{NUM_ENTRIES}.json"


def create_large_dataset():
    """
    生成一个大型数据集并保存到文件中。
    """
    print("=" * 50)
    print(f"开始生成一个包含 {NUM_ENTRIES:,} 条记录的数据文件...")
    print(f"这将需要一些时间，并会创建一个较大的文件 ({NUM_ENTRIES * HASH_LEN_BYTES / 1e9:.2f} GB)。")
    start_time = time.time()

    # 调用我们已有的函数来生成哈希列表
    db_hashes = shared_logic.generate_hash_database(NUM_ENTRIES, HASH_LEN_BYTES)

    # 将字节串转换为十六进制字符串以便保存为JSON
    db_hashes_hex = [h.hex() for h in db_hashes]

    print("正在将数据写入磁盘...")
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(db_hashes_hex, f)

    end_time = time.time()
    print("=" * 50)
    print(f"数据文件 '{OUTPUT_FILE}' 已成功生成！")
    print(f"总耗时: {end_time - start_time:.2f} 秒。")
    print("=" * 50)


if __name__ == '__main__':
    create_large_dataset()