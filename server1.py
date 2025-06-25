# server1.py (Final Version - Loads Pre-generated Data)
import numpy as np
import time
import os
import requests
from flask import Flask, request, jsonify, send_file
from collections import defaultdict
import traceback
import json

import shared_logic

# --- 配置 ---
S2_IP = "192.168.123.107"
S2_PORT = 5002
SERVER1_PORT = 5001
A_FILE = "lwe_matrix_A.npy"
HINT_FILE = "hint_matrix.npy"
QUERYABLE_ITEMS_FILE = "queryable_hashes.json"

app = Flask(__name__)


def partition_db_by_prefix(db_hashes):
    # ... (此函数与之前版本完全相同)
    local_db_params = {}
    groups = defaultdict(list)
    for h in db_hashes:
        prefix = shared_logic.get_prefix_from_hash(h)
        groups[prefix].append(h)
    prefix_list = sorted(groups.keys())
    num_rows = len(prefix_list)
    max_cols_per_row = max(len(items) for items in groups.values()) if groups else 0
    entry_vec_len = len(db_hashes[0]) if db_hashes else 0
    num_cols = max_cols_per_row * entry_vec_len
    local_db_params.update({'num_rows': num_rows, 'num_cols': num_cols, 'max_cols_per_row': max_cols_per_row,
                            'entry_vec_len': entry_vec_len})
    db_matrix = np.zeros((num_rows, num_cols), dtype=np.uint8)
    for i, prefix in enumerate(prefix_list):
        row_items = groups[prefix]
        row_vec = np.array([], dtype=np.uint8);
        for item_bytes in row_items:
            row_vec = np.concatenate([row_vec, shared_logic.bytes_to_int_array(item_bytes)])
        padding_len = num_cols - len(row_vec)
        if padding_len > 0:
            random_padding = np.random.randint(0, shared_logic.LWE_P, size=padding_len, dtype=np.uint8)
            padded_row_vec = np.concatenate([row_vec, random_padding])
        else:
            padded_row_vec = row_vec
        db_matrix[i, :] = padded_row_vec
    return db_matrix, [p.hex() for p in prefix_list], local_db_params


@app.route('/preprocess', methods=['POST'])
def preprocess():
    try:
        data = request.json
        num_entries = data['num_entries']
        print(f"S1: 开始预处理...规模: {num_entries}")

        # --- 【核心修正】开始 ---
        pregen_file_name = f"database_{num_entries}.json"

        # 计时器开始
        start_time = time.time()

        if os.path.exists(pregen_file_name):
            print(f"S1: 发现预生成的数据文件: {pregen_file_name}，正在加载...")
            with open(pregen_file_name, 'r') as f:
                db_hashes_hex = json.load(f)
            db_hashes = [bytes.fromhex(h) for h in db_hashes_hex]
            print("S1: 数据文件加载完成。")
        else:
            print("S1: 未发现预生成的数据文件，将动态生成数据...")
            # 只有在没有预生成文件时才动态生成
            db_hashes = shared_logic.generate_hash_database(num_entries, 32)
            # 注意：按照您的要求，动态生成的时间现在也被包含在计时内了

        # --- 【核心修正】结束 ---

        db_hashes_hex = [h.hex() for h in db_hashes]
        with open(QUERYABLE_ITEMS_FILE, 'w') as f:
            json.dump(db_hashes_hex, f)

        db_matrix, prefix_list, db_params = partition_db_by_prefix(db_hashes)

        app.config['DB_PARAMS'] = db_params
        app.config['DB_MATRIX'] = db_matrix

        A = shared_logic.generate_lwe_matrix_A(shared_logic.LWE_N, db_params['num_rows'])

        print("S1: 正在计算hint矩阵 (这会花费很长时间)...")
        chunk_size = 256
        num_cols = db_matrix.shape[1]
        hint = np.zeros((A.shape[0], num_cols), dtype=np.uint32)
        A_i64 = A.astype(np.int64)
        for i in range(0, num_cols, chunk_size):
            end = min(i + chunk_size, num_cols)
            hint_chunk = (A_i64 @ db_matrix[:, i:end].astype(np.int64)) % shared_logic.LWE_Q
            hint[:, i:end] = hint_chunk

        np.save(A_FILE, A)
        np.save(HINT_FILE, hint)

        print("S1: 正在生成OT加密列表...")
        encrypted_list = []
        for i, prefix_hex in enumerate(prefix_list):
            encrypted_list.append(
                shared_logic.encrypt_index(shared_logic.get_key_from_prefix(bytes.fromhex(prefix_hex)), i))

        app.config['ENCRYPTED_INDEX_LIST'] = encrypted_list

        end_time = time.time()

        print(f"S1: 预处理完成。服务器计算耗时: {end_time - start_time:.4f} 秒")
        return jsonify({"status": "preprocessing complete", "db_params": db_params, "time": end_time - start_time})

    except Exception as e:
        print(f"S1 CRASHED: {traceback.format_exc()}")
        return jsonify({"error": "S1 internal server error", "details": str(e)}), 500


# ... (The rest of the file is unchanged) ...
@app.route('/download/<filename>', methods=['GET'])
def download_file(filename):
    file_path = None
    if filename == 'A':
        file_path = A_FILE
    elif filename == 'hint':
        file_path = HINT_FILE
    elif filename == 'query_items':
        file_path = QUERYABLE_ITEMS_FILE
    else:
        return "File not found", 404
    retries = 5
    while retries > 0:
        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            try:
                return send_file(file_path, as_attachment=True)
            except Exception as e:
                return f"Error sending file: {e}", 500
        time.sleep(1);
        retries -= 1
    return "File not ready", 408


@app.route('/ot-setup', methods=['GET'])
def handle_ot_setup():
    return jsonify({"encrypted_index_list": app.config.get('ENCRYPTED_INDEX_LIST', [])})


@app.route('/compute-answer', methods=['POST'])
def compute_answer():
    db_matrix = app.config.get('DB_MATRIX')
    if db_matrix is None: return jsonify({"error": "Database not ready"}), 400
    data = request.json;
    qu = np.array(data['qu'], dtype=np.uint32);
    transaction_id = data['transaction_id']
    start_time = time.time()
    chunk_size = 256;
    num_cols = db_matrix.shape[1]
    ans = np.zeros(num_cols, dtype=np.uint32)
    qu_i64 = qu.astype(np.int64)
    for i in range(0, num_cols, chunk_size):
        end = min(i + chunk_size, num_cols)
        db_chunk = db_matrix[:, i:end]
        ans_chunk = (qu_i64 @ db_chunk.astype(np.int64)) % shared_logic.LWE_Q
        ans[i:end] = ans_chunk
    core_computation_time = time.time() - start_time
    try:
        requests.post(f"http://{S2_IP}:{S2_PORT}/receive-ans",
                      json={'ans': ans.tolist(), 'transaction_id': transaction_id}, timeout=10)
    except requests.exceptions.RequestException:
        return jsonify({"status": "failed to forward to s2"}), 500
    return jsonify({"status": "ans computed", "core_computation_time": core_computation_time})


if __name__ == '__main__':
    print(f"Server1 正在 http://0.0.0.0:{SERVER1_PORT} 上运行...")
    from waitress import serve

    serve(app, host='0.0.0.0', port=SERVER1_PORT)