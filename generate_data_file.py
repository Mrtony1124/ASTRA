# generate_data_file.py
import json
import shared_logic
import time

NUM_ENTRIES = 100_000_000
HASH_LEN_BYTES = 32
OUTPUT_FILE = f"database_{NUM_ENTRIES}.json"

def create_large_dataset():

    print("=" * 50)
    print(f"开始生成一个包含 {NUM_ENTRIES:,} 条记录的数据文件...")
    print(f"这将需要一些时间，并会创建一个较大的文件 ({NUM_ENTRIES * HASH_LEN_BYTES / 1e9:.2f} GB)。")
    start_time = time.time()

    db_hashes = shared_logic.generate_hash_database(NUM_ENTRIES, HASH_LEN_BYTES)

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
