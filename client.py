# client.py (Final - with Infinite Timeout for Preprocessing)
import numpy as np
import requests
import time
import pandas as pd
import uuid
from pybloom_live import BloomFilter
import random
import hashlib
import os
import json
import shared_logic

S1_IP = ""
S2_IP = ""
S1_PORT = ;
S2_PORT =
S1_URL = f"http://{S1_IP}:{S1_PORT}"
S2_URL = f"http://{S2_IP}:{S2_PORT}"

DATABASE_SIZES = [10 ** 7]
HASH_LEN_BYTES = 
A_FILE = "lwe_matrix_A.npy"
BF_FILE_NAME_TEMPLATE = "bf_{}.bin"
QUERYABLE_ITEMS_FILE = "queryable_hashes.json"

DB_PARAMS = {}
QUERYABLE_HASHES = []

def run_single_query():

    global DB_PARAMS, QUERYABLE_HASHES
    LWE_A = np.load(A_FILE)
    target_hash_hex = random.choice(QUERYABLE_HASHES)
    target_hash = bytes.fromhex(target_hash_hex)
    transaction_id = str(uuid.uuid4())
    print(f"\n--- [{transaction_id}] Running Query: Target Hash='{target_hash.hex()}' ---")
    metrics = {"db_size": DB_PARAMS['num_entries'], "entry_len": HASH_LEN_BYTES}
    start_time_ot = time.time()
    try:
        resp_ot = requests.get(f"{S1_URL}/ot-setup");
        resp_ot.raise_for_status()
        encrypted_list = resp_ot.json()['encrypted_index_list']
    except requests.exceptions.RequestException as e:
        return None, f"OT setup failed: {e}"
    my_prefix = shared_logic.get_prefix_from_hash(target_hash)
    my_key = shared_logic.get_key_from_prefix(my_prefix)
    target_row_b = next((shared_logic.decrypt_index(my_key, token) for token in encrypted_list if
                         shared_logic.decrypt_index(my_key, token) is not None), None)
    if target_row_b is None: return None, "OT failed: Query item's prefix not found."
    metrics['time_ot'] = time.time() - start_time_ot
    print(f"OT成功, 找到行索引: {target_row_b}")
    start_time_qgen = time.time()
    s = np.random.randint(0, shared_logic.LWE_Q, size=shared_logic.LWE_N, dtype=np.uint32)
    e = shared_logic.generate_noise_vector(DB_PARAMS['num_rows'])
    u_b = np.zeros(DB_PARAMS['num_rows'], dtype=np.int64);
    u_b[target_row_b] = 1
    sA = s.astype(np.int64) @ LWE_A.astype(np.int64) % shared_logic.LWE_Q
    qu = (sA + e + shared_logic.SCALING_FACTOR * u_b) % shared_logic.LWE_Q
    metrics['time_query_gen'] = time.time() - start_time_qgen
    try:
        requests.post(f"{S2_URL}/receive-s", json={'s': s.tolist(), 'transaction_id': transaction_id})
        response_s1 = requests.post(f"{S1_URL}/compute-answer",
                                    json={'qu': qu.tolist(), 'transaction_id': transaction_id})
        metrics['time_s1_computation'] = response_s1.json()['core_computation_time']
        time.sleep(1)
    except requests.exceptions.RequestException as e:
        return None, f"Failed to connect during computation: {e}"
    start_time_verify = time.time();
    bf = None
    try:
        resp_s2_setup = requests.post(f"{S2_URL}/setup-verification",
                                      json={'transaction_id': transaction_id, 'db_params': DB_PARAMS})
        bf_download_url = f"{S2_URL}/download-bf/{transaction_id}";
        bf_file_name = BF_FILE_NAME_TEMPLATE.format(transaction_id)
        start_time_bf_dl = time.time()
        with requests.get(bf_download_url, stream=True) as r:
            r.raise_for_status()
            with open(bf_file_name, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192): f.write(chunk)
        metrics['time_bf_download'] = time.time() - start_time_bf_dl
        metrics['comm_bf_bytes'] = os.path.getsize(bf_file_name)
        with open(bf_file_name, "rb") as f:
            bf = BloomFilter.fromfile(f)
        os.remove(bf_file_name)
        element = shared_logic.hash_to_group_element(target_hash)
        blinded_element, blinding_factor = shared_logic.oprf_blind(element)
        resp_s2_eval = requests.post(f"{S2_URL}/oprf-interactive-eval",
                                     json={'transaction_id': transaction_id, 'blinded_element': blinded_element})
        evaluated_element = resp_s2_eval.json()['evaluated_element']
        final_oprf_value = shared_logic.oprf_unblind(evaluated_element, blinding_factor)
        is_present = final_oprf_value in bf
    except Exception as e:
        return None, f"S2 verification failed: {e}"
    finally:
        temp_bf_path = BF_FILE_NAME_TEMPLATE.format(transaction_id)
        if os.path.exists(temp_bf_path): os.remove(temp_bf_path)
    s2_metrics = resp_s2_eval.json()['s2_metrics'];
    metrics.update({f'time_s2_{k}': v for k, v in s2_metrics.items()})
    metrics['time_client_verification'] = (time.time() - start_time_verify) - metrics.get('time_bf_download', 0) - sum(
        s2_metrics.values())
    print(f"[{transaction_id}] 查询结果验证: {'成功' if is_present else '失败'}")
    if not is_present: print("Verification failed unexpectedly.")
    metrics['time_online_total'] = sum([v for k, v in metrics.items() if k.startswith('time_')])
    metrics['comm_online_total_bytes'] = len(str(qu.tolist())) + len(str(s.tolist())) + len(str(blinded_element)) + len(
        resp_s2_eval.text) + metrics.get('comm_bf_bytes', 0)
    return metrics, None

def run_experiment():
    global DB_PARAMS, QUERYABLE_HASHES
    results = []

    for size in DATABASE_SIZES:
        print("=" * 50)
        print(f"开始为规模 {size} 进行全自动设置...")

        try:
           
            print(f"向Server1发送预处理请求")
            resp_s1_prep = requests.post(f"{S1_URL}/preprocess", json={'num_entries': size}, timeout=None)
         

            resp_s1_prep.raise_for_status()
            DB_PARAMS = resp_s1_prep.json()['db_params']
            DB_PARAMS['num_entries'] = size
            s1_preprocess_time = resp_s1_prep.json()['time']
            print(f"S1预处理完成") 

        
            print("客户端正在下载可查询项列表...")
            resp_items = requests.get(f"{S1_URL}/download/query_items", timeout=300)
            resp_items.raise_for_status()
            QUERYABLE_HASHES = resp_items.json()
            print(f"客户端下载可查询项列表完成, ")

            print("客户端正在下载 A 矩阵...")
            start_time = time.time()
            with requests.get(f"{S1_URL}/download/A", stream=True, timeout=600) as r: 
                r.raise_for_status()
                open(A_FILE, 'wb').write(r.content)
            time_client_setup = time.time() - start_time
            comm_client_setup_bytes = os.path.getsize(A_FILE)
            print(f"客户端下载 A 矩阵完成")

            print("正在触发Server2进行设置...")
            resp_s2_setup = requests.post(f"{S2_URL}/setup", json={})
            resp_s2_setup.raise_for_status()
            time_s2_setup = resp_s2_setup.json()['time']
            comm_s2_setup_bytes = resp_s2_setup.json()['size_bytes']
            print(f"Server2设置完成")

        except requests.exceptions.RequestException as e:
            print(f"预处理或设置失败: {e}")
            continue

        query_metrics_list = []
        for i in range(3):
            print(f"\n--- 第 {i + 1}/3 次查询 ---")
            metrics, error_msg = run_single_query()
            if metrics:
                query_metrics_list.append(metrics)
            else:
                print(f"查询失败")
                break
            time.sleep(1)

        if not query_metrics_list:
            continue

        avg_metrics = pd.DataFrame(query_metrics_list).mean().to_dict()
        avg_metrics.update({
            'db_size': size,
            'entry_len': HASH_LEN_BYTES,
            's1_preprocess_time': s1_preprocess_time,
            'offline_client_setup_time': time_client_setup,
            'offline_s2_setup_time': time_s2_setup,
            'offline_comm_client_bytes': comm_client_setup_bytes,
            'offline_comm_s2_bytes': comm_s2_setup_bytes
        })
        results.append(avg_metrics)

    if results:
        df = pd.DataFrame(results)
        df.to_csv('experiment_results_large_scale.csv', index=False)
        print("\n\n实验完成！")
        print(df)


if __name__ == '__main__':
    run_experiment()
