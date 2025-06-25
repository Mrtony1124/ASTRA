# shared_logic.py (Final Corrected Version)
import numpy as np
import random
import os
import base64
import hashlib
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import math # 新增导入

# --- LWE 和 协议核心参数 ---
LWE_N = 1024
LWE_Q = 2**32
LWE_P = 2**8
SCALING_FACTOR = LWE_Q // LWE_P

# --- OT 和数据库分区参数 ---
PREFIX_BYTES = 2

# --- OPRF 模拟参数 ---
OPRF_GROUP_ORDER = 65521 # 这是一个素数

def generate_lwe_matrix_A(rows, cols):
    return np.random.randint(0, LWE_Q, size=(rows, cols), dtype=np.uint32)

def generate_noise_vector(dim, hamming_weight=64):
    noise = np.zeros(dim, dtype=np.int64)
    indices = np.random.choice(dim, size=hamming_weight, replace=False)
    values = np.random.randint(-2, 3, size=hamming_weight)
    values[values == 0] = 1
    noise[indices] = values
    return noise

def round_and_scale(vector, delta):
    return np.round(vector * (1/delta)).astype(np.uint8)

def generate_hash_database(num_entries, hash_len_bytes=32):
    db_hashes = set()
    while len(db_hashes) < num_entries:
        random_data = os.urandom(32)
        h = hashlib.sha256(random_data).digest()
        db_hashes.add(h[:hash_len_bytes])
    return list(db_hashes)

def get_prefix_from_hash(item_hash):
    return item_hash[:PREFIX_BYTES]

def bytes_to_int_array(b):
    return np.frombuffer(b, dtype=np.uint8)

def int_array_to_bytes(arr):
    return arr.astype(np.uint8).tobytes()

def get_key_from_prefix(prefix_bytes, salt=b'salt_for_ot_v2'):
    key = hashlib.sha256(salt + prefix_bytes).digest()
    return base64.urlsafe_b64encode(key)

def encrypt_index(key, index):
    f = Fernet(key)
    return f.encrypt(index.to_bytes(4, 'big')).decode('utf-8')

def decrypt_index(key, token):
    f = Fernet(key)
    try:
        return int.from_bytes(f.decrypt(token.encode('utf-8')), 'big')
    except Exception:
        return None

def hash_to_group_element(item_hash):
    return int.from_bytes(item_hash, 'big') % OPRF_GROUP_ORDER

def oprf_blind(element):
    """客户端：致盲元素"""
    # --- 【核心修正】---
    # 必须确保致盲因子与指数的模数互质，这样它的模逆才存在
    exponent_modulus = OPRF_GROUP_ORDER - 1
    while True:
        blinding_factor = random.randint(2, exponent_modulus - 1)
        if math.gcd(blinding_factor, exponent_modulus) == 1:
            # 找到了一个有效的致盲因子，跳出循环
            break
    # --- 【修正结束】---
    blinded_element = pow(element, blinding_factor, OPRF_GROUP_ORDER)
    return blinded_element, blinding_factor

def oprf_evaluate(blinded_element, sk_oprf):
    return pow(blinded_element, sk_oprf, OPRF_GROUP_ORDER)

def oprf_unblind(evaluated_element, blinding_factor):
    """客户端：解除致盲"""
    exponent_modulus = OPRF_GROUP_ORDER - 1
    inverse_blinding = pow(blinding_factor, -1, exponent_modulus)
    return pow(evaluated_element, inverse_blinding, OPRF_GROUP_ORDER)

def oprf_server_eval_on_item(item, sk_oprf):
    element = hash_to_group_element(item)
    return pow(element, sk_oprf, OPRF_GROUP_ORDER)