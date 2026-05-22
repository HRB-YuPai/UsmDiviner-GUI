# BLK vs BLB3 实现对比与集成指南

## 目录

1. [算法流程对比](#算法流程对比)
2. [关键差异](#关键差异)
3. [统一解密框架设计](#统一解密框架设计)
4. [集成步骤](#集成步骤)
5. [测试建议](#测试建议)

---

## 算法流程对比

### BLK 解密流程

```
输入文件
    ↓
[头部解析] → 提取 Signature, Key, Seed
    ↓
[Key处理] → SBox(可选) → AES解密 → XOR InitVector
    ↓
[计算Seed] → XOR所有Seed数据 ⊕ Key高低部分 ⊕ InitSeed
    ↓
[生成Pad] → MT19937_64(Seed) → 生成4096字节XOR Pad
    ↓
[XOR解密] → 从偏移0x2A开始XOR所有数据
    ↓
输出解密数据
```

### BLB3 解密流程

```
输入文件
    ↓
[头部提取] → 前16字节作为加密头
    ↓
[初始XOR] → 与加密头XOR (前16字节)
    ↓
[AES处理] → 修改的AES加密(实际解密作用)
    ↓
[RC4加密] → RC4密钥调度 + PRGA阶段
    ↓
[Descramble] → 3轮变换 + SBox替换 + GF(256)乘法
    ↓
输出解密数据(前128字节特殊处理)
```

---

## 关键差异

### 表格对比

| 特性 | BLK | BLB3 | 难度 |
|------|-----|------|------|
| **动态密钥** | ✓ (从文件读取) | ✗ (固定的16字节头) | BLK更难 |
| **伪随机算法** | MT19937_64 | RC4 | 相当 |
| **AES使用** | 用于Key处理 | 用于数据解密 | 相当 |
| **初始化向量** | 文件特定 + 游戏参数 | 文件头本身 | BLK更复杂 |
| **处理范围** | 整个文件(从0x2A) | 前128字节特殊 | 相当 |
| **有限域算术** | ✗ | ✓ (GF256) | BLB3多一步 |

### 代码复杂度

```
BLK 复杂度评分:
  - 头部解析: ⭐⭐
  - Key处理: ⭐⭐⭐⭐
  - Seed计算: ⭐⭐⭐
  - XOR Pad生成: ⭐⭐
  - 总体: ⭐⭐⭐⭐ (较复杂但逻辑清晰)

BLB3 复杂度评分:
  - 头部处理: ⭐
  - AES修改: ⭐⭐⭐⭐⭐ (最难,自定义AES)
  - RC4: ⭐⭐⭐
  - Descramble: ⭐⭐⭐
  - GF256: ⭐⭐
  - 总体: ⭐⭐⭐⭐⭐ (逻辑分散,需多种算法)
```

---

## 统一解密框架设计

### 3.1 接口定义

```python
from abc import ABC, abstractmethod
from typing import Tuple, Optional
from dataclasses import dataclass


@dataclass
class DecryptionParams:
    """加密参数基类"""
    name: str
    description: str


@dataclass
class BLKParams(DecryptionParams):
    """BLK特定参数"""
    init_vector: bytes
    expansion_key: bytes
    init_seed: int
    sbox: Optional[bytes] = None


@dataclass
class BLB3Params(DecryptionParams):
    """BLB3特定参数"""
    rc4_key: bytes
    sbox: bytes
    shift_row: bytes
    aes_key: bytes
    aes_mul: bytes
    aes_sbox: bytes


class FileDecryptor(ABC):
    """文件解密器基类"""
    
    @abstractmethod
    def detect(self, data: bytes) -> bool:
        """检测文件格式"""
        pass
    
    @abstractmethod
    def decrypt(self, data: bytes) -> bytes:
        """解密数据"""
        pass
    
    @abstractmethod
    def get_name(self) -> str:
        """获取解密器名称"""
        pass
```

### 3.2 具体实现

```python
class UnifiedDecryptor:
    """统一解密器 - 自动检测并处理BLK/BLB3"""
    
    def __init__(self):
        self.decryptors: list[FileDecryptor] = []
        self.register_defaults()
    
    def register_defaults(self) -> None:
        """注册内置解密器"""
        self.decryptors.append(BLKDecryptor(...))
        self.decryptors.append(BLB3Decryptor(...))
    
    def register(self, decryptor: FileDecryptor) -> None:
        """注册自定义解密器"""
        self.decryptors.append(decryptor)
    
    def identify_format(self, data: bytes) -> Optional[FileDecryptor]:
        """识别文件格式"""
        for decryptor in self.decryptors:
            if decryptor.detect(data):
                return decryptor
        return None
    
    def decrypt(self, data: bytes) -> Tuple[bytes, str]:
        """自动解密
        
        Returns:
            (解密数据, 使用的解密器名称)
        """
        decryptor = self.identify_format(data)
        if decryptor is None:
            raise ValueError("无法识别文件格式")
        
        try:
            decrypted = decryptor.decrypt(data)
            return decrypted, decryptor.get_name()
        except Exception as e:
            raise RuntimeError(f"{decryptor.get_name()}解密失败: {e}")
```

### 3.3 格式识别策略

```python
def identify_file_format(data: bytes) -> str:
    """
    识别内容: BLK vs BLB3
    
    BLK特征:
    - 以null分割的ASCII/UTF-8 Signature开头
    - 通常在前64字节内有null字节
    - 第二个字段是Int32 (Key大小)
    
    BLB3特征:
    - 无明显文本头部
    - 直接进入加密数据
    - 前16字节为加密头,通常高熵
    
    策略: 
    1. 尝试找null字节位置
    2. 检查是否为有效UTF-8
    3. 检查Key大小字段是否合理(1-16KB)
    4. 若都不满足,认为是BLB3
    """
    
    # 尝试BLK
    try:
        null_pos = data.index(b'\x00')
        if null_pos > 0 and null_pos < 64:
            sig = data[:null_pos]
            try:
                # 尝试解码为UTF-8
                sig.decode('utf-8')
                # 检查Key大小字段
                if len(data) >= null_pos + 5:
                    key_size = struct.unpack('<I', 
                        data[null_pos+1:null_pos+5])[0]
                    if 0 < key_size <= 0x10000:
                        return 'BLK'
            except UnicodeDecodeError:
                pass
    except ValueError:
        pass
    
    # 认为是BLB3
    return 'BLB3'
```

---

## 集成步骤

### 步骤1: 环境准备

```bash
# 安装必需的库
pip install pycryptodome

# 或使用conda
conda install pycryptodome
```

### 步骤2: 集成到UsmDiviner

```python
# usmdiviner/crypto.py (新文件)

from .blk_decryptor import BLKDecryptor, GameParams
from .blb3_decryptor import BLB3Decryptor

# 游戏参数库
class CryptoParams:
    GENSHIN_IMPACT = GameParams(...)
    HONKAI_3RD = GameParams(...)
    
    # 可为多个版本/服务器添加参数
    GENSHIN_GLOBAL = GameParams(...)
    GENSHIN_CHINA = GameParams(...)


def decrypt_file(file_path: str, game: str = "GI") -> bytes:
    """便捷解密函数"""
    
    with open(file_path, 'rb') as f:
        data = f.read()
    
    # 自动识别格式
    fmt = identify_file_format(data)
    
    if fmt == 'BLK':
        params = getattr(CryptoParams, f'{game}_PARAMS')
        decryptor = BLKDecryptor(params)
    else:  # BLB3
        decryptor = BLB3Decryptor(...)
    
    return decryptor.decrypt(data)
```

### 步骤3: 集成到CLI

```python
# 修改 usmdiviner/cli.py

@click.command()
@click.option('--input', type=click.Path(exists=True))
@click.option('--output', type=click.Path())
@click.option('--format', type=click.Choice(['auto', 'blk', 'blb3']))
def decrypt_cmd(input, output, format):
    """解密游戏加密文件"""
    
    from . import crypto
    
    decrypted = crypto.decrypt_file(input)
    
    with open(output, 'wb') as f:
        f.write(decrypted)
    
    click.echo(f"✓ 解密完成: {output}")
```

### 步骤4: 测试集成

```python
# tests/test_decryptor.py

import pytest
from pathlib import Path
from usmdiviner.crypto import decrypt_file


class TestDecryption:
    
    @pytest.fixture
    def sample_blk_file(self, tmp_path):
        """生成测试BLK文件样本"""
        # 实现... 需要真实的加密样本
        pass
    
    @pytest.fixture
    def sample_blb3_file(self, tmp_path):
        """生成测试BLB3文件样本"""
        pass
    
    def test_blk_decryption(self, sample_blk_file):
        """测试BLK解密"""
        decrypted = decrypt_file(str(sample_blk_file), format='blk')
        assert len(decrypted) > 0
    
    def test_blb3_decryption(self, sample_blb3_file):
        """测试BLB3解密"""
        decrypted = decrypt_file(str(sample_blb3_file), format='blb3')
        assert len(decrypted) > 0
    
    def test_auto_detection(self, sample_blk_file, sample_blb3_file):
        """测试自动格式检测"""
        blk_result = decrypt_file(str(sample_blk_file))
        assert len(blk_result) > 0
        
        blb3_result = decrypt_file(str(sample_blb3_file))
        assert len(blb3_result) > 0
```

---

## 测试建议

### 5.1 单元测试

```python
# 测试MT19937_64
def test_mt19937_64():
    """测试MT19937_64是否与C#实现相同"""
    mt = MT19937_64(0x567BA22BABB08098)
    
    # 预期的前几个输出值(来自C#测试)
    expected = [
        0x8d8d04c3a2ec8a4a,
        0x19434bd9c1b39e35,
        0x80c76fea12c1cbe5,
    ]
    
    for exp in expected:
        result = mt.genrand_int64()
        assert result == exp, f"MT输出不匹配: {hex(result)} != {hex(exp)}"


# 测试AES
def test_aes_decryption():
    """测试AES解密"""
    from Crypto.Cipher import AES
    
    key = bytes(16)  # 全零密钥
    plaintext = b'Hello World!!!!!'
    
    cipher = AES.new(key, AES.MODE_ECB)
    encrypted = cipher.encrypt(plaintext)
    decrypted = cipher.decrypt(encrypted)
    
    assert decrypted == plaintext


# 测试XOR Pad生成
def test_xor_pad_generation():
    """测试XOR Pad生成的确定性"""
    seed = 0x1234567890ABCDEF
    
    pad1 = generate_xor_pad(seed, 0x1000)
    pad2 = generate_xor_pad(seed, 0x1000)
    
    assert pad1 == pad2, "XOR Pad生成不确定"
```

### 5.2 集成测试

```python
# 测试完整的BLK解密
def test_blk_full_decryption():
    """端到端测试"""
    test_file = Path("test_data/sample.blk")
    
    if not test_file.exists():
        pytest.skip("测试文件不存在")
    
    with open(test_file, 'rb') as f:
        encrypted = f.read()
    
    params = GameParams(...)
    decryptor = BLKDecryptor(params)
    decrypted = decryptor.decrypt(encrypted)
    
    # 验证解密结果
    assert len(decrypted) > 0
    assert not contains_null_padding(decrypted)


def test_multi_file_decryption():
    """测试批量文件解密"""
    test_dir = Path("test_data/blk_files")
    
    for blk_file in test_dir.glob("*.blk"):
        with open(blk_file, 'rb') as f:
            encrypted = f.read()
        
        decryptor = BLKDecryptor(...)
        decrypted = decryptor.decrypt(encrypted)
        
        assert len(decrypted) > 0
```

### 5.3 性能测试

```python
import time


def benchmark_blk_decryption():
    """BLK解密性能基准测试"""
    
    test_file = Path("test_data/large.blk")
    with open(test_file, 'rb') as f:
        data = f.read()
    
    decryptor = BLKDecryptor(...)
    
    # 预热
    decryptor.decrypt(data[:1000])
    
    # 实际测试
    start = time.time()
    for _ in range(10):
        decryptor.decrypt(data)
    elapsed = time.time() - start
    
    avg_time = elapsed / 10
    throughput = len(data) / avg_time / (1024 * 1024)  # MB/s
    
    print(f"平均时间: {avg_time*1000:.2f}ms")
    print(f"吞吐量: {throughput:.2f} MB/s")
    
    # 性能目标
    assert throughput > 10, f"性能过低: {throughput:.2f} MB/s < 10 MB/s"
```

---

## 实现检查清单

### BLK实现检查

- [ ] MT19937_64 初始化正确
- [ ] Seed计算公式实现无误
- [ ] XOR Pad循环使用正确
- [ ] 处理Key为多个4096字节块的情况
- [ ] 处理seed数据不足的情况
- [ ] SBox application仅在需要时应用
- [ ] AES解密使用正确的密钥

### BLB3实现检查

- [ ] RC4 KSA和PRGA实现正确
- [ ] Descramble三轮循环正确
- [ ] GF(256)乘法表正确
- [ ] 处理前128字节特殊逻辑
- [ ] 修改的AES实现匹配C#版本
- [ ] ShiftRow索引计算正确

### 集成检查

- [ ] 格式自动检测工作正常
- [ ] 错误处理完善
- [ ] 性能达到目标
- [ ] 单元测试覆盖>80%
- [ ] 集成测试通过
- [ ] 文档完整

---

## 常见问题

**Q: 为什么我的解密输出与预期不同?**

A: 检查以下几点:
1. 确认游戏参数正确(InitVector, ExpansionKey, InitSeed)
2. 确认Key大小正确(通常0x1000)
3. 确认Seed数据完整性
4. 使用调试日志跟踪每一步

**Q: MT19937_64为什么与C#实现不同?**

A: 常见原因:
1. 位移运算有符号/无符号问题
2. 溢出处理不同(确保使用64位掩码)
3. 初始化种子方式不同
4. 验证: 运行已知向量测试

**Q: 性能太低怎么办?**

A: 优化策略:
1. 使用NumPy处理XOR操作
2. 预生成XOR Pad缓存
3. 使用多线程处理多个文件
4. 编译关键部分为Cython

---

## 参考资源

- [AnimeStudio GitHub](https://github.com/YuukiPS/AnimeStudio)
- [Mersenne Twister论文](http://www.math.sci.hiroshima-u.ac.jp/m-mat/MT/mt19937ar.c)
- [AES标准(FIPS 197)](https://nvlpubs.nist.gov/nistpubs/FIPS/NIST.FIPS.197.pdf)
- [PyCryptodome文档](https://pycryptodome.readthedocs.io/)

---

**最后更新**: 2026年5月23日
