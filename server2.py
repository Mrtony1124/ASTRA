# server2.py (Final Diagnostic Version)
import numpy as np
import os
import time
import requests
from flask import Flask, request, jsonify, send_file
from pybloom_live import BloomFilter
import random
import json

import shared_logic

# --- 配置 ---
S1_IP = "192.168.1.101"
S1_PORT = 5001
SERVER2_PORT = 5002
HINT_FILE = "hint_matrix.npy"
BF_FILE_NAME_TEMPLATE = "bf_{}.bin"
DEBUG_DIR = "debug_files"

app = Flask(__name__)
TRANSACTION_STORE = {}
SK_OPRF = random.randint(2, shared_logic.OPRF_GROUP_ORDER - 1)

# setup, receive_s, receive_ans, setup_verification, download_bf 接口均与上一版相同
@app.route('/setup', methods=['POST'])
def setup_server2():
    s1_url = f"http://{S1_IP}:{S1_PORT}"; print("S2: 正在从Server1下载hint矩阵...")
    try:
        start_time = time.time()
        with requests.get(f"{s1_url}/download/hint", stream=True, timeout=300) as r:
            r.raise_for_status()
            with open(HINT_FILE, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192): f.write(chunk)
        hint_size_bytes = os.path.getsize(HINT_FILE); app.config['HINT_MATRIX'] = np.load(HINT_FILE)
        setup_time = time.time() - start_time
        print(f"S2: Hint矩阵下载并加载完成。耗时: {setup_time:.4f}s")
        return jsonify({"status": "s2 setup complete", "time": setup_time, "size_bytes": hint_size_bytes})
    except Exception as e: print(f"S2: 设置失败 - {e}"); return jsonify({"error": str(e)}), 500

@app.route('/receive-s', methods=['POST'])
def receive_s():
    data = request.json; transaction_id = data['transaction_id']
    if transaction_id not in TRANSACTION_STORE: TRANSACTION_STORE[transaction_id] = {}
    TRANSACTION_STORE[transaction_id]['s'] = np.array(data['s'], dtype=np.uint32)
    return jsonify({"status": "s received"})

@app.route('/receive-ans', methods=['POST'])
def receive_ans():
    data = request.json; transaction_id = data['transaction_id']
    if transaction_id not in TRANSACTION_STORE: TRANSACTION_STORE[transaction_id] = {}
    TRANSACTION_STORE[transaction_id]['ans'] = np.array(data['ans'], dtype=np.uint32)
    return jsonify({"status": "ans received"})

@app.route('/setup-verification', methods=['POST'])
def setup_verification():
    hint_matrix = app.config.get('HINT_MATRIX')
    if hint_matrix is None: return jsonify({"error": "S2 Hint matrix not loaded"}), 500
    data = request.json; transaction_id = data['transaction_id']; db_params = data['db_params']
    if transaction_id not in TRANSACTION_STORE or 's' not in TRANSACTION_STORE[transaction_id] or 'ans' not in TRANSACTION_STORE[transaction_id]:
        return jsonify({"error": "s or ans not received"}), 400
    s = TRANSACTION_STORE[transaction_id]['s']; ans = TRANSACTION_STORE[transaction_id]['ans']
    start_time_decrypt = time.time()
    s_i64 = s.astype(np.int64); hint_matrix_i64 = hint_matrix.astype(np.int64); ans_i64 = ans.astype(np.int64)
    s_hint = (s_i64 @ hint_matrix_i64) % shared_logic.LWE_Q
    diff_mod_q = (ans_i64 - s_hint + shared_logic.LWE_Q) % shared_logic.LWE_Q
    q = shared_logic.LWE_Q; half_q = q // 2; centered_diff = diff_mod_q.copy().astype(np.int64)
    centered_diff[centered_diff > half_q] -= q
    recovered_row_p = shared_logic.round_and_scale(centered_diff, shared_logic.SCALING_FACTOR)
    decryption_time = time.time() - start_time_decrypt
    start_time_bloom = time.time()
    entry_vec_len = db_params['entry_vec_len']; max_cols_per_row = db_params['max_cols_per_row']
    recovered_items = []
    for i in range(max_cols_per_row):
        item_vec = recovered_row_p[i*entry_vec_len:(i+1)*entry_vec_len]
        if np.any(item_vec): recovered_items.append(shared_logic.int_array_to_bytes(item_vec))
    bf = BloomFilter(capacity=len(recovered_items) or 1, error_rate=1e-9)
    for item_bytes in recovered_items:
        bf.add(shared_logic.oprf_server_eval_on_item(item_bytes, SK_OPRF))
    bf_file_name = BF_FILE_NAME_TEMPLATE.format(transaction_id)
    with open(bf_file_name, "wb") as f: bf.tofile(f)
    TRANSACTION_STORE[transaction_id].update({
        'decryption_time': decryption_time, 'bloom_gen_time': time.time() - start_time_bloom,
        'recovered_items_hex': [item.hex() for item in recovered_items]
    })
    return jsonify({"status": "bloom filter created"})

@app.route('/get-debug-info/<transaction_id>', methods=['GET'])
def get_debug_info(transaction_id):
    if transaction_id in TRANSACTION_STORE and 'recovered_items_hex' in TRANSACTION_STORE[transaction_id]:
        return jsonify({"recovered_items_hex": TRANSACTION_STORE[transaction_id]['recovered_items_hex']})
    return jsonify({"error": "No debug info found for this transaction"}), 404

@app.route('/download-bf/<transaction_id>', methods=['GET'])
def download_bf(transaction_id):
    bf_file_name = BF_FILE_NAME_TEMPLATE.format(transaction_id)
    try:
        response = send_file(bf_file_name, as_attachment=True)
        @response.call_on_close
        def remove_file():
            try: os.remove(bf_file_name)
            except OSError: pass
        return response
    except FileNotFoundError: return jsonify({"error": "bf file not found"}), 404

@app.route('/oprf-interactive-eval', methods=['POST'])
def oprf_interactive_eval():
    data = request.json; transaction_id = data['transaction_id']; blinded_element = data['blinded_element']
    start_time = time.time()
    evaluated_element = shared_logic.oprf_evaluate(blinded_element, SK_OPRF)
    s2_metrics = {
        "decryption_time": TRANSACTION_STORE[transaction_id].get('decryption_time', 0),
        "bloom_gen_time": TRANSACTION_STORE[transaction_id].get('bloom_gen_time', 0),
        "oprf_eval_time": time.time() - start_time,
    }
    # --- 【核心修正】---
    # 在调试期间，我们不删除事务记录，以确保客户端可以获取调试信息
    # if transaction_id in TRANSACTION_STORE:
    #     del TRANSACTION_STORE[transaction_id]
    # --- 【修正结束】---
    return jsonify({"status": "oprf evaluation complete", "evaluated_element": evaluated_element, "s2_metrics": s2_metrics})

if __name__ == '__main__':
    if not os.path.exists(DEBUG_DIR): os.makedirs(DEBUG_DIR)
    print(f"Server2 正在 http://0.0.0.0:{SERVER2_PORT} 上运行...")
    from waitress import serve
    serve(app, host='0.0.0.0', port=SERVER2_PORT)