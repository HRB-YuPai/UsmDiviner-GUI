# AnimeStudio BLK/BLB3 文件解密算法技术分析报告

**作者**: 技术分析  
**日期**: 2026年5月23日  
**适用版本**: AnimeStudio CryptoHelper v1.0+

---

## 目录

1. [执行摘要](#执行摘要)
2. [文件格式识别](#文件格式识别)
3. [BLK 解密算法详解](#blk-解密算法详解)
4. [BLB3 解密算法详解](#blb3-解密算法详解)
5. [关键参数库](#关键参数库)
6. [Python实现指南](#python实现指南)
7. [对比分析](#对比分析)

---

## 执行摘要

AnimeStudio 使用两种主要的文件加密格式：
- **BLK**: 基于XOR流加密 + Mersenne Twister伪随机数生成器 + AES-128
- **BLB3**: 基于AES-128 + RC4 + Descramble

本报告详细分析这两种格式的加密机制，为双格式解密的Python实现提供完整的技术基础。

| 特性 | BLK | BLB3 |
|------|-----|------|
| 主要算法 | XOR Stream + MT19937_64 + AES | AES + RC4 + Descramble |
| 文件头结构 | Signature + Key + Seed | 16字节加密头 |
| Key处理 | AES解密 | 内联处理 |
| 数据加密 | XOR Pad流 | AES + RC4 |
| 适用游戏 | 原神(GI)为主 | 崩坏3(BH3)为主 |

---

## 文件格式识别

### 1.1 文件签名

BLK文件从以下签名开始：

```csharp
var signature = reader.ReadStringToNull();  // 读取null分割的C字符串
```

典型的BLK签名：
- 格式：`"プリセット"` 或 ASCII字符串
- 特征：包含null终止符
- 长度：通常 1-16 字节

### 1.2 BLK vs BLB3 识别规则

**BLK 特征**:
```
Header结构: [Signature(可变长)] [Key Size(4B)] [Key(KeySize)] [Seed Size(2B)] [Seed Data(SeedSize)]
指令流: 遇到 0x2A(42)字节偏移 -> 开始XOR解密
```

**BLB3 特征**:
```
Header结构: [加密16字节头部] [其他数据]
特点: 无明显Signature字段，直接进入加密数据
处理: 前128字节特殊处理
```

**识别方法**:
```python
def is_blk_file(data: bytes) -> bool:
    # 检查是否存在null分割的签名
    try:
        null_pos = data.index(b'\x00')
        if null_pos < 64:  # 合理的签名长度范围
            return True
    except ValueError:
        pass
    return False

def is_blb3_file(data: bytes) -> bool:
    # BLB3通常没有明显的文本签名
    # 但会在处理中通过AES + RC4特征识别
    return not is_blk_file(data)
```

---

## BLK 解密算法详解

### 2.1 文件头结构

```csharp
// BlkUtils.cs - 行 15-27
var signature = reader.ReadStringToNull();      // 签名 (可变)
Logger.Verbose($"Signature: {signature}");
var count = reader.ReadInt32();                 // KeySize (4字节,小端)
Logger.Verbose($"Key size: {count}");
var key = reader.ReadBytes(count);              // 密钥数据
reader.Position += count;                        // 跳过相同大小的填充
var seedSize = Math.Min(reader.ReadInt16(), 
                       blk.SBox.IsNullOrEmpty() ? 0x800 : 0x1000);
Logger.Verbose($"Seed size: 0x{seedSize:X8}");
```

**参数含义**:
- `DataOffset = 0x2A` (42字节): 实际数据开始位置
- `KeySize = 0x1000` (4096字节): 密钥大小常数
- `SeedBlockSize = 0x800` (2048字节): 种子块大小

### 2.2 Key处理流程

#### 阶段 1: SBox应用 (仅限GI)

```csharp
// BlkUtils.cs - 行 29-32
if (!blk.SBox.IsNullOrEmpty() && blk.Type.IsGI())
{
    for (int i = 0; i < 0x10; i++)
    {
        key[i] = blk.SBox[(i % 4 * 0x100) | key[i]];
    }
}
```

**解析**:
- 仅适用于原神(GI)
- 对Key的前16字节进行SBox变换
- SBox查表: `index = (i % 4) * 256 + key[i]`
- 效果: 对称加密强化

```python
# Python实现
def apply_sbox_to_key(key_data: bytearray, sbox: bytes) -> None:
    """对Key前16字节应用SBox"""
    for i in range(16):
        key_data[i] = sbox[(i % 4) * 256 + key_data[i]]
```

#### 阶段 2: AES解密

```csharp
// BlkUtils.cs - 行 34
AES.Decrypt(key, blk.ExpansionKey);
```

**AES参数**:
- 算法: AES-128 (标准ECB模式)
- 密钥: `blk.ExpansionKey` (16字节预设密钥)
- 输入/输出: 密钥数据本身(in-place)

```python
# Python实现 - 需要crypto库
from Crypto.Cipher import AES

def decrypt_key_with_aes(key_data: bytes, expansion_key: bytes) -> bytes:
    """使用AES-128 ECB解密密钥"""
    cipher = AES.new(expansion_key, AES.MODE_ECB)
    decrypted = cipher.decrypt(key_data)
    return decrypted
```

#### 阶段 3: Vector XOR

```csharp
// BlkUtils.cs - 行 36-38
for (int i = 0; i < 0x10; i++)
{
    key[i] ^= blk.InitVector[i];
}
```

**操作**: 对解密后的Key前16字节XOR `InitVector`

```python
# Python实现
def xor_with_init_vector(key_data: bytearray, init_vector: bytes) -> None:
    """使用InitVector对Key进行XOR操作"""
    for i in range(min(16, len(key_data))):
        key_data[i] ^= init_vector[i]
```

### 2.3 Seed计算 (核心)

这是BLK解密的关键步骤。

#### Seed来源计算

```csharp
// BlkUtils.cs - 行 40-46
ulong keySeed = ulong.MaxValue;  // 初始值: 0xFFFFFFFFFFFFFFFF

var dataPos = reader.Position;
for (int i = 0; i < seedSize; i += 8)
{
    keySeed ^= reader.ReadUInt64();  // 连续读取8字节,进行XOR
}
reader.Position = dataPos;  // 重置位置
```

**流程**:
1. 初始化 `keySeed = 0xFFFFFFFFFFFFFFFF`
2. 从文件读取 `seedSize` 字节(默认2048)
3. 每次读取8字节的小端序64位整数
4. 与 `keySeed` 进行XOR累积
5. 最后位置复位

```python
# Python实现
def calculate_key_seed(data: bytes, seed_size: int) -> int:
    """计算用于MT19937_64的种子"""
    key_seed = 0xFFFFFFFFFFFFFFFF
    for i in range(0, seed_size, 8):
        value = int.from_bytes(data[i:i+8], byteorder='little')
        key_seed ^= value
    return key_seed & 0xFFFFFFFFFFFFFFFF  # 确保64位
```

#### 最终Seed合成

```csharp
// BlkUtils.cs - 行 48-52
var keyLow = BinaryPrimitives.ReadUInt64LittleEndian(key.AsSpan(0, 8));
var keyHigh = BinaryPrimitives.ReadUInt64LittleEndian(key.AsSpan(8, 16));
var seed = keyLow ^ keyHigh ^ keySeed ^ blk.InitSeed;

Logger.Verbose($"Seed: 0x{seed:X8}");

var mt64 = new MT19937_64(seed);
```

**Seed公式**:
```
seed = (Key[0:8]小端) ^ (Key[8:16]小端) ^ keySeed ^ InitSeed
```

**Python实现**:
```python
def compute_final_seed(key: bytes, key_seed: int, init_seed: int) -> int:
    """合成最终的MT19937_64种子"""
    key_low = int.from_bytes(key[0:8], byteorder='little')
    key_high = int.from_bytes(key[8:16], byteorder='little')
    final_seed = key_low ^ key_high ^ key_seed ^ init_seed
    return final_seed & 0xFFFFFFFFFFFFFFFF
```

### 2.4 XOR Pad生成

```csharp
// BlkUtils.cs - 行 54-58
var xorpad = new byte[KeySize];  // KeySize = 0x1000 = 4096
for (int i = 0; i < KeySize; i += 8)
{
    BinaryPrimitives.WriteUInt64LittleEndian(
        xorpad.AsSpan(i, 8), mt64.Int64());
}
```

**过程**:
1. 初始化4096字节的XOR Pad缓冲区
2. 使用MT19937_64生成伪随机数
3. 每次生成64位(8字节)
4. 以小端序写入缓冲区

```python
# Python实现
def generate_xor_pad(seed: int, pad_size: int = 0x1000) -> bytes:
    """使用MT19937_64生成XOR Pad"""
    mt = MT19937_64(seed)
    pad = bytearray()
    for _ in range(0, pad_size, 8):
        value = mt.int64()
        pad.extend(value.to_bytes(8, byteorder='little'))
    return bytes(pad)
```

### 2.5 XORStream应用

```csharp
// BlkUtils.cs - 行 60
return new XORStream(reader.BaseStream, DataOffset, xorpad);
```

**XORStream 类实现** (伪代码):
```csharp
public class XORStream
{
    private Stream baseStream;
    private int dataOffset;
    private byte[] xorpad;
    private long position;

    public XORStream(Stream base, int offset, byte[] pad)
    {
        baseStream = base;
        dataOffset = offset;
        xorpad = pad;
        position = 0;
    }

    public int Read(byte[] buffer, int offset, int count)
    {
        baseStream.Position = dataOffset + position;
        int bytesRead = baseStream.Read(buffer, offset, count);
        for (int i = 0; i < bytesRead; i++)
        {
            buffer[offset + i] ^= xorpad[(position + i) % xorpad.Length];
        }
        position += bytesRead;
        return bytesRead;
    }
}
```

**Python实现**:
```python
class XORStream:
    """模拟XORStream行为的Python类"""
    def __init__(self, data: bytes, data_offset: int, xor_pad: bytes):
        self.data = data
        self.data_offset = data_offset
        self.xor_pad = xor_pad
        self.position = 0

    def read(self, size: int) -> bytes:
        """读取并XOR解密数据"""
        start = self.data_offset + self.position
        end = start + size
        encrypted = self.data[start:end]
        
        decrypted = bytearray()
        for i, byte in enumerate(encrypted):
            xor_index = (self.position + i) % len(self.xor_pad)
            decrypted.append(byte ^ self.xor_pad[xor_index])
        
        self.position += len(encrypted)
        return bytes(decrypted)
```

### 2.6 完整BLK解密流程总结

```python
def decrypt_blk_file(blk_data: bytes, 
                     init_vector: bytes,
                     expansion_key: bytes, 
                     init_seed: int,
                     sbox: bytes = None) -> bytes:
    """完整的BLK文件解密流程"""
    
    # 第一步: 解析文件头
    offset = 0
    null_pos = blk_data.index(b'\x00')
    signature = blk_data[:null_pos].decode('utf-8', errors='ignore')
    offset = null_pos + 1
    
    # 读取Key大小和Key数据
    key_size = int.from_bytes(blk_data[offset:offset+4], 'little')
    offset += 4
    key_data = bytearray(blk_data[offset:offset+key_size])
    offset += key_size * 2  # 跳过填充
    
    # 读取Seed大小
    seed_size = int.from_bytes(blk_data[offset:offset+2], 'little')
    seed_size = min(seed_size, 0x1000 if sbox else 0x800)
    offset += 2
    
    # 第二步: 处理Key
    # - 应用SBox (如果需要)
    if sbox:
        for i in range(16):
            key_data[i] = sbox[(i % 4) * 256 + key_data[i]]
    
    # - AES解密
    from Crypto.Cipher import AES
    cipher = AES.new(expansion_key, AES.MODE_ECB)
    key_data = bytearray(cipher.decrypt(bytes(key_data[:16]))) + key_data[16:]
    
    # - XOR InitVector
    for i in range(16):
        key_data[i] ^= init_vector[i]
    
    # 第三步: 计算Seed
    key_seed = 0xFFFFFFFFFFFFFFFF
    for i in range(0, seed_size, 8):
        value = int.from_bytes(
            blk_data[offset+i:offset+i+8], 'little'
        )
        key_seed ^= value
    
    final_seed = (
        int.from_bytes(key_data[0:8], 'little') ^
        int.from_bytes(key_data[8:16], 'little') ^
        key_seed ^
        init_seed
    ) & 0xFFFFFFFFFFFFFFFF
    
    # 第四步: 生成XOR Pad
    mt = MT19937_64(final_seed)
    xor_pad = bytearray()
    for _ in range(0, 0x1000, 8):
        value = mt.int64()
        xor_pad.extend(value.to_bytes(8, 'little'))
    
    # 第五步: 应用XOR解密
    data_offset = 0x2A  # 42
    decrypted = bytearray()
    for i in range(data_offset, len(blk_data)):
        xor_index = (i - data_offset) % len(xor_pad)
        decrypted.append(blk_data[i] ^ xor_pad[xor_index])
    
    return bytes(decrypted)
```

---

## 2.7 MT19937_64 伪随机生成器实现

**MT19937_64参数**:
```csharp
private const ulong N = 312;
private const ulong M = 156;
private const ulong MATRIX_A = 0xB5026F5AA96619E9L;
private const ulong UPPER_MASK = 0xFFFFFFFF80000000;
private const ulong LOWER_MASK = 0X7FFFFFFFUL;
```

**关键Python实现**:
```python
class MT19937_64:
    """Mersenne Twister 双精度版本"""
    
    N = 312
    M = 156
    MATRIX_A = 0xB5026F5AA96619E9
    UPPER_MASK = 0xFFFFFFFF80000000
    LOWER_MASK = 0x7FFFFFFF
    
    def __init__(self, seed: int):
        self.mt = [0] * (self.N + 1)
        self.mti = self.N + 1
        self.init(seed)
    
    def init(self, seed: int):
        """初始化状态数组"""
        self.mt[0] = seed & 0xFFFFFFFFFFFFFFFF
        for i in range(1, self.N):
            prev = self.mt[i-1]
            self.mt[i] = (
                6364136223846793005 * (prev ^ (prev >> 62)) + i
            ) & 0xFFFFFFFFFFFFFFFF
    
    def int64(self) -> int:
        """生成下一个64位随机数"""
        if self.mti >= self.N:
            self._twist()
        
        x = self.mt[self.mti]
        self.mti += 1
        
        # Tempering operations
        x ^= (x >> 29) & 0x5555555555555555
        x ^= (x << 17) & 0x71D67FFFEDA60000
        x ^= (x << 37) & 0xFFF7EEE000000000
        x ^= x >> 43
        
        return x & 0xFFFFFFFFFFFFFFFF
    
    def _twist(self):
        """状态转移函数"""
        mag01 = [0x0, self.MATRIX_A]
        
        for kk in range(self.N - self.M):
            y = (self.mt[kk] & self.UPPER_MASK) | \
                (self.mt[kk+1] & self.LOWER_MASK)
            self.mt[kk] = self.mt[kk + self.M] ^ \
                         (y >> 1) ^ mag01[y & 0x1]
        
        for kk in range(self.N - self.M, self.N - 1):
            y = (self.mt[kk] & self.UPPER_MASK) | \
                (self.mt[kk+1] & self.LOWER_MASK)
            self.mt[kk] = self.mt[kk - (self.N - self.M)] ^ \
                         (y >> 1) ^ mag01[y & 0x1]
        
        y = (self.mt[self.N-1] & self.UPPER_MASK) | \
            (self.mt[0] & self.LOWER_MASK)
        self.mt[self.N-1] = self.mt[self.M-1] ^ \
                           (y >> 1) ^ mag01[y & 0x1]
        
        self.mti = 0
```

---

## BLB3 解密算法详解

### 3.1 BLB3 整体流程

```csharp
// BlbUtils.cs - 行 17-46
public static void Decrypt(byte[] header, Span<byte> buffer)
{
    buffer = buffer[..Math.Min(128, buffer.Length)];
    
    // 步骤1: 初始XOR
    var count = Math.Min(buffer.Length, header.Length);
    for (int i = 0; i < count; i++)
    {
        buffer[i] ^= header[i];
    }

    if (buffer.Length >= 16)
    {
        // 步骤2: 修改的AES加密(实际是解密)
        BlbAES.Encrypt(buffer.Slice(0, 16).ToArray(), header)
            .CopyTo(buffer);

        if (buffer.Length > 16)
        {
            // 步骤3: RC4加密
            RC4(buffer);
        }

        // 步骤4: Descramble操作
        Descramble(buffer.Slice(0, 16));
    }
}
```

### 3.2 BLB3 关键参数

**BLB3使用的静态密钥** (CryptoHelper.cs):

```csharp
public static readonly byte[] Blb3RC4Key = new byte[256] { ... };    // RC4初始密钥表
public static readonly byte[] Blb3SBox = new byte[1024] { ... };     // SBox替换表
public static readonly byte[] Blb3ShiftRow = new byte[48] { ... };   // Shift行映射
public static readonly byte[] Blb3Key = new byte[8] { ... };         // Mhy Key
public static readonly byte[] Blb3Mul = new byte[8] { ... };         // Mhy Multiplier
```

### 3.3 BLB3 RC4实现

```csharp
// BlbUtils.cs - 行 73-100
public static void RC4(Span<byte> buf)
{
    byte[] S = new byte[256];
    BlbRC4Key.CopyTo(S, 0);
    byte[] T = new byte[256];
    int i = 0;
    
    // KSA (Key Scheduling Algorithm) 变体
    for (i = 0; i < 256; i += 2)
    {
        T[i] = buf[i & 6];
        T[i + 1] = buf[(i + 1) & 7];
    }

    int j = 0;
    for (i = 0; i < 256; i++)
    {
        j = (j + S[i] + T[i]) % 256;
        // Swap
        byte temp = S[j];
        S[j] = S[i];
        S[i] = temp;
    }
    
    // PRGA (Pseudo-Random Generation Algorithm) 变体
    i = j = 0;
    for (int iteration = 0; iteration < buf.Length - 0x10; iteration++)
    {
        i = (i + 1) % 256;
        j = (j + S[i]) % 256;
        byte temp = S[j];
        S[j] = S[i];
        S[i] = temp;
        
        uint K = S[(S[j] + S[i]) % 256];
        switch (buf[(i % 8) + 8] % 3)
        {
            case 0: buf[iteration + 0x10] ^= (byte)K; break;
            case 1: buf[iteration + 0x10] -= (byte)K; break;
            case 2: buf[iteration + 0x10] += (byte)K; break;
        }
    }
}
```

### 3.4 Descramble操作

```csharp
// BlbUtils.cs - 行 62-70
public static void Descramble(Span<byte> buf)
{
    byte[] vector = new byte[buf.Length];
    for (int i = 0; i < 3; i++)
    {
        for (int j = 0; j < buf.Length; j++)
        {
            int k = BlbShiftRow[(2 - i) * 0x10 + j];
            int idx = j % 8;
            vector[j] = (byte)(BlbKey[idx] ^ 
                BlbSBox[(j % 4 * 0x100) | 
                    GF256Mul(BlbMul[idx], buf[k % buf.Length])]);
        }
        vector.AsSpan(0, buf.Length).CopyTo(buf);
    }
}
```

**GF(256)乘法** (有限域算术):
```csharp
private static int GF256Mul(int a, int b) => 
    (a == 0 || b == 0) ? 0 : 
    CryptoHelper.GF256Exp[(CryptoHelper.GF256Log[a] + 
                          CryptoHelper.GF256Log[b]) % 0xFF];
```

---

## 关键参数库

### 4.1 原神(GI)参数

```python
GI_PARAMS = {
    'InitVector': bytes.fromhex('E3FC2D269CC5A2ECD3F8C6D377C249B9'),
    'GIExpansionKey': bytes.fromhex(
        '542FED675DDD112EB74013E329AB6D283ED04D51D30B8F3C8F7D560DB35C5BDF'
        '8F0526E59D36EE17F940C3056AF11D2C79EDC6E20C1587938EC191E58D441098'
        '3408'  # 总160字节
    ),
    'GIInitSeed': 0x567BA22BABB08098,
    'SBox': bytes.fromhex('F7E7D8B864...'),  # 256字节SBox
}
```

### 4.2 BLB3全局参数

```python
BLB3_PARAMS = {
    'RC4Key': bytes([0x29, 0x23, 0xBE, 0x84, ...]),  # 256字节
    'SBox': bytes([0xD0, 0x20, 0x41, 0x4A, ...]),    # 1024字节
    'ShiftRow': bytes([0x05, 0x0A, 0x03, ...]),      # 48字节
    'Key': bytes([0xA9, 0x85, 0x57, 0x4D, ...]),     # 8字节
    'Mul': bytes([0xC8, 0x73, 0xBF, 0x25, ...]),     # 8字节
    'AESSBox': bytes([0x63, 0x7d, 0x75, ...]),       # 256字节
}
```

---

## Python实现指南

### 5.1 完整的BLK解密类

```python
import struct
from typing import Optional, Tuple
from Crypto.Cipher import AES

class MT19937_64:
    """Mersenne Twister 64-bit实现"""
    
    def __init__(self, seed: int):
        self.N = 312
        self.M = 156
        self.MATRIX_A = 0xB5026F5AA96619E9
        self.UPPER_MASK = 0xFFFFFFFF80000000
        self.LOWER_MASK = 0x7FFFFFFF
        
        self.mt = [0] * (self.N + 1)
        self.mti = self.N + 1
        self.init_genrand(seed)
    
    def init_genrand(self, seed: int):
        self.mt[0] = seed & 0xFFFFFFFFFFFFFFFF
        for i in range(1, self.N):
            mult = 6364136223846793005
            prev = self.mt[i - 1]
            self.mt[i] = (mult * (prev ^ (prev >> 62)) + i) & 0xFFFFFFFFFFFFFFFF
    
    def genrand_int64(self) -> int:
        if self.mti >= self.N:
            self._twist()
        
        y = self.mt[self.mti]
        self.mti += 1
        
        y ^= (y >> 29) & 0x5555555555555555
        y ^= (y << 17) & 0x71D67FFFEDA60000
        y ^= (y << 37) & 0xFFF7EEE000000000
        y ^= y >> 43
        
        return y & 0xFFFFFFFFFFFFFFFF
    
    def _twist(self):
        mag01 = [0, self.MATRIX_A]
        
        for kk in range(self.N - self.M):
            y = (self.mt[kk] & self.UPPER_MASK) | (self.mt[kk + 1] & self.LOWER_MASK)
            self.mt[kk] = (self.mt[kk + self.M] ^ (y >> 1) ^ 
                          mag01[y & 0x1]) & 0xFFFFFFFFFFFFFFFF
        
        for kk in range(self.N - self.M, self.N - 1):
            y = (self.mt[kk] & self.UPPER_MASK) | (self.mt[kk + 1] & self.LOWER_MASK)
            self.mt[kk] = (self.mt[kk - (self.N - self.M)] ^ (y >> 1) ^ 
                          mag01[y & 0x1]) & 0xFFFFFFFFFFFFFFFF
        
        y = (self.mt[self.N - 1] & self.UPPER_MASK) | (self.mt[0] & self.LOWER_MASK)
        self.mt[self.N - 1] = (self.mt[self.M - 1] ^ (y >> 1) ^ 
                              mag01[y & 0x1]) & 0xFFFFFFFFFFFFFFFF


class BLKDecryptor:
    """BLK文件解密器"""
    
    DATA_OFFSET = 0x2A
    KEY_SIZE = 0x1000
    SEED_BLOCK_SIZE = 0x800
    
    def __init__(self, 
                 init_vector: bytes,
                 expansion_key: bytes,
                 init_seed: int,
                 sbox: Optional[bytes] = None):
        self.init_vector = init_vector
        self.expansion_key = expansion_key
        self.init_seed = init_seed
        self.sbox = sbox
    
    def decrypt(self, blk_data: bytes) -> bytes:
        """解密BLK文件"""
        
        # 解析文件头
        offset = 0
        
        # 读取签名
        null_pos = blk_data.find(b'\x00')
        signature = blk_data[:null_pos].decode('utf-8', errors='ignore')
        offset = null_pos + 1
        
        # 读取Key大小
        key_size = struct.unpack('<I', blk_data[offset:offset+4])[0]
        offset += 4
        
        # 读取Key数据
        key_data = bytearray(blk_data[offset:offset+key_size])
        offset += key_size
        
        # 跳过填充
        offset += key_size
        
        # 读取Seed大小
        seed_size_val = struct.unpack('<H', blk_data[offset:offset+2])[0]
        seed_size = min(seed_size_val, self.SEED_BLOCK_SIZE * 2 
                       if self.sbox else self.SEED_BLOCK_SIZE)
        offset += 2
        
        # 处理Key
        self._process_key(key_data)
        
        # 计算Seed
        seed = self._calculate_seed(blk_data[offset:offset+seed_size], key_data)
        
        # 生成XOR Pad
        xor_pad = self._generate_xor_pad(seed)
        
        # 应用XOR解密
        return self._apply_xor_decryption(blk_data, xor_pad)
    
    def _process_key(self, key_data: bytearray) -> None:
        """处理Key: SBox + AES + XOR"""
        
        # 应用SBox (GI only)
        if self.sbox:
            for i in range(16):
                key_data[i] = self.sbox[(i % 4) * 256 + key_data[i]]
        
        # AES解密
        cipher = AES.new(self.expansion_key, AES.MODE_ECB)
        decrypted = cipher.decrypt(bytes(key_data[:16]))
        key_data[:16] = bytearray(decrypted)
        
        # XOR InitVector
        for i in range(16):
            key_data[i] ^= self.init_vector[i]
    
    def _calculate_seed(self, seed_data: bytes, key_data: bytes) -> int:
        """计算MT19937_64种子"""
        
        # 计算keySeed
        key_seed = 0xFFFFFFFFFFFFFFFF
        for i in range(0, len(seed_data), 8):
            value = struct.unpack('<Q', seed_data[i:i+8])[0]
            key_seed ^= value
        key_seed &= 0xFFFFFFFFFFFFFFFF
        
        # 提取Key的高低部分
        key_low = struct.unpack('<Q', key_data[0:8])[0]
        key_high = struct.unpack('<Q', key_data[8:16])[0]
        
        # 计算最终Seed
        final_seed = (key_low ^ key_high ^ key_seed ^ self.init_seed) & 0xFFFFFFFFFFFFFFFF
        return final_seed
    
    def _generate_xor_pad(self, seed: int) -> bytes:
        """使用MT19937_64生成XOR Pad"""
        
        mt = MT19937_64(seed)
        pad = bytearray()
        
        for _ in range(0, self.KEY_SIZE, 8):
            value = mt.genrand_int64()
            pad.extend(struct.pack('<Q', value))
        
        return bytes(pad)
    
    def _apply_xor_decryption(self, blk_data: bytes, xor_pad: bytes) -> bytes:
        """应用XOR解密"""
        
        decrypted = bytearray()
        for i in range(self.DATA_OFFSET, len(blk_data)):
            xor_index = (i - self.DATA_OFFSET) % len(xor_pad)
            decrypted.append(blk_data[i] ^ xor_pad[xor_index])
        
        return bytes(decrypted)
```

### 5.2 BLB3解密实现

```python
class BLB3Decryptor:
    """BLB3文件解密器"""
    
    def __init__(self,
                 rc4_key: bytes,
                 sbox: bytes,
                 shift_row: bytes,
                 key: bytes,
                 mul: bytes,
                 aes_sbox: bytes):
        self.rc4_key = rc4_key
        self.sbox = sbox
        self.shift_row = shift_row
        self.key = key
        self.mul = mul
        self.aes_sbox = aes_sbox
    
    def decrypt(self, header: bytes, buffer: bytes) -> bytes:
        """解密BLB3数据"""
        
        buffer = bytearray(buffer[:128])
        
        # 步骤1: 初始XOR
        for i in range(min(len(buffer), len(header))):
            buffer[i] ^= header[i]
        
        if len(buffer) >= 16:
            # 步骤2: 修改的AES (实际是加密过程)
            buffer[:16] = bytearray(self._blb_aes_encrypt(buffer[:16], header))
            
            # 步骤3: RC4
            if len(buffer) > 16:
                self._rc4(buffer)
            
            # 步骤4: Descramble
            self._descramble(buffer[:16])
        
        return bytes(buffer)
    
    def _rc4(self, buf: bytearray) -> None:
        """RC4加密"""
        
        S = bytearray(self.rc4_key)
        T = bytearray(256)
        
        for i in range(256):
            T[i] = buf[i & 6 if i < 8 else i & 7]
        
        j = 0
        for i in range(256):
            j = (j + S[i] + T[i]) % 256
            S[i], S[j] = S[j], S[i]
        
        # PRGA
        i = j = 0
        for iteration in range(len(buf) - 16):
            i = (i + 1) % 256
            j = (j + S[i]) % 256
            S[i], S[j] = S[j], S[i]
            
            K = S[(S[i] + S[j]) % 256]
            control = buf[(i % 8) + 8] % 3
            
            if control == 0:
                buf[iteration + 16] ^= K
            elif control == 1:
                buf[iteration + 16] = (buf[iteration + 16] - K) & 0xFF
            else:
                buf[iteration + 16] = (buf[iteration + 16] + K) & 0xFF
    
    def _descramble(self, buf: bytearray) -> None:
        """Descramble操作"""
        
        vector = bytearray(len(buf))
        for iteration in range(3):
            for j in range(len(buf)):
                k = self.shift_row[(2 - iteration) * 16 + j]
                idx = j % 8
                mul_result = self._gf256_mul(self.mul[idx], buf[k % len(buf)])
                vector[j] = (self.key[idx] ^ 
                            self.sbox[(j % 4) * 256 + mul_result])
            buf[:] = vector
    
    @staticmethod
    def _gf256_mul(a: int, b: int) -> int:
        """GF(256)乘法"""
        if a == 0 or b == 0:
            return 0
        # 需要GF256对数和指数表
        # 这里省略具体实现
        return 0
    
    def _blb_aes_encrypt(self, data: bytes, key: bytes) -> bytes:
        """修改的BLB AES加密"""
        # 这是一个特殊的AES变体
        # 需要实现自定义的expand, sub_bytes, shift_rows, mix_cols
        pass
```

### 5.3 使用示例

```python
# BLK解密示例
gi_decryptor = BLKDecryptor(
    init_vector=bytes.fromhex('E3FC2D269CC5A2ECD3F8C6D377C249B9'),
    expansion_key=bytes.fromhex('542FED67...'),  # GIExpansionKey
    init_seed=0x567BA22BABB08098,
    sbox=bytes.fromhex('F7E7D8B8...')  # GISBox
)

with open('video.blk', 'rb') as f:
    encrypted_data = f.read()

decrypted_data = gi_decryptor.decrypt(encrypted_data)

# BLB3解密示例
blb3_decryptor = BLB3Decryptor(
    rc4_key=...,
    sbox=...,
    shift_row=...,
    key=...,
    mul=...,
    aes_sbox=...
)

header = encrypted_data[:16]
buffer = encrypted_data[16:144]
decrypted = blb3_decryptor.decrypt(header, buffer)
```

---

## 对比分析

### 6.1 安全性对比

| 方面 | BLK | BLB3 |
|------|-----|------|
| 密钥复杂度 | ⭐⭐⭐⭐ (XOR + AES + MT) | ⭐⭐⭐ (AES + RC4) |
| 初向量 | 动态(来自文件) | 固定(16字节头部) |
| 伪随机性 | MT19937_64 (周期长) | RC4 (标准) |
| 加密范围 | 全文件 | 前128字节特殊 |

### 6.2 性能对比

| 操作 | BLK | BLB3 |
|------|-----|------|
| 初始化 | O(n*log n) - MT初始化 | O(1) - 固定密钥 |
| 解密速度 | 快 (简单XOR) | 中等 (RC4较慢) |
| 内存占用 | 4KB (XOR Pad) > 2.5KB (MT状态) | 1.5KB (RC4状态) |

### 6.3 实现难度

**BLK 难度**: ★★★★☆
- 需要实现MT19937_64
- 需要AES-128解密
- 多步骤的Key处理

**BLB3 难度**: ★★★☆☆
- 需要实现修改的AES (复杂)
- 需要RC4实现
- 需要GF(256)算术

---

## 附录

### A.1 常见错误与排查

**错误**:
```
InvalidOperationException: Wrong key size
```

**原因**: Key大小不是4096字节或未正确跳过填充

**解决**:
```python
# 确保跳过两倍大小的Key
offset += key_size
offset += key_size  # 跳过填充
```

### A.2 调试技巧

```python
def debug_blk_parsing(data: bytes):
    """调试BLK文件解析"""
    
    offset = 0
    null_pos = data.find(b'\x00')
    signature = data[:null_pos]
    print(f"Signature: {signature!r}")
    
    offset = null_pos + 1
    key_size = struct.unpack('<I', data[offset:offset+4])[0]
    print(f"Key Size: 0x{key_size:X}")
    
    offset += 4
    offset += key_size
    offset += key_size
    
    seed_size = struct.unpack('<H', data[offset:offset+2])[0]
    print(f"Seed Size: 0x{seed_size:X}")
```

### A.3 参考资源

- AnimeStudio GitHub: https://github.com/YuukiPS/AnimeStudio
- Mersenne Twister: http://www.math.sci.hiroshima-u.ac.jp/m-mat/MT/emt64.html
- AES标准: FIPS 197
- RC4: https://en.wikipedia.org/wiki/RC4

---

## 版本历史

| 版本 | 日期 | 更改 |
|------|------|------|
| 1.0 | 2026-05-23 | 初始版本 |

---

**报告完成于**: 2026年5月23日  
**分析范围**: AnimeStudio v1.x  
**适用游戏**: 原神(GI)、崩坏3(BH3)
