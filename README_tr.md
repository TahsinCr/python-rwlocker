[![Contributors][contributors-shield]][contributors-url]
[![Forks][forks-shield]][forks-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]
[![MIT License][license-shield]][license-url]
[![LinkedIn][linkedin-shield]][linkedin-url]

[Türkçe][lang-tr-url] | [English][lang-en-url] | [Русский][lang-ru-url]



<!-- About -->
<div align="center">


<h3 align="center">Python RWLocker</h3>

<p align="center">

Gelişmiş, Yüksek Performanslı ve Durum Makinesi (State-Machine) Tabanlı Senkron/Asenkron Okuma-Yazma Kilitleri (Read-Write Locks).

[Changelog][changelog-url] · [Report Bug][issues-url] · [Request Feature][issues-url]
 
</p>

</div>

<br/>

## 📋 Proje Hakkında

### 🚀 Neden RWLocker?

Python'daki standart kilitler (`Lock`, `RLock`) **Exclusive (Dışlayıcı)** kilitlerdir. Kapıya 100 tane okuyucu (örneğin veritabanından veri çeken thread'ler) gelse bile, bu işlemleri tek tek sırayla yapmak zorundadırlar.

`rwlocker` ise **Shared (Paylaşımlı)** okuma mantığına dayanır. Yazar kilitleri dışlayıcıyken, okuyucu kilitleri kritik bölümleri paylaşımlı erişime uygunsa birden fazla thread veya task'ın eşzamanlı erişmesine izin verir.  Paylaşımlı kritik bölümler I/O beklerken veya başka şekilde kontrolü bırakırken throughput artabilir; her iş yükü için hız garantisi yoktur.

### 🚀 Peki ya Condition (Durum) Değişkenleri?
`rwlocker` condition bekleyenlerini `collections.deque` kuyruklarında tutar. Kuyruğa ekleme ve FIFO çıkarma amortize O(1); N bekleyeni bildirmek her biri sinyallenmek zorunda olduğu için O(N), zaman aşımı/iptal sonrası belirli bir bekleyeni kuyruktan çıkarmak da O(N) olabilir.

### ✨ Temel Özellikler

* **Hem Thread Hem Asyncio Desteği:** Çalışma zamanına uygun senkron (`rwlocker.thread_rwlock`) ve asenkron (`rwlocker.async_rwlock`) arayüzleri kullanabilirsiniz.
* **Akıllı Proxy Mimarisi (Smart Proxy Architecture):** `.read` ve `.write` proxy'leri ile `with` ve `async with` context manager'larını sezgisel olarak kullanma imkanı.
* **Atomik Derece Düşürme (Downgrading):** Yazma kilidini tamamen serbest bırakmadan, araya başka bir yazar girmesine izin vermeden anında Okuma kilidine (`downgrade()`) düşürebilme özelliği.
* **Yazar Reentrancy'si:** `ReentrantWriter` varyantları, kilidin sahibi olan thread veya task'ın iç içe yazma kilitleri ve bir okuma kilidi almasına izin verir; diğer okuyucular `.downgrade()` paylaşımlı erişimi açtıktan sonra katılabilir.
* **Condition Bekleme Kuyrukları:** Bekleyenler FIFO deque yapısında tutulur. Normal ekleme/çıkarma amortize O(1); tüm bekleyenleri bildirme ve iptal edilen bekleyeni kuyruktan çıkarma O(N) olabilir.
* **Asenkron İptal Temizliği:** İptal edilen task kuyruktan çıkarılır; condition bekleyişi iptal hatası yayılmadan önce ilişkili kilidi yeniden alır.
* **Kilit Tarzı Arayüz:** Doğrudan kilit işlemleri dışlayıcı `.write` proxy’sini kullanır. Standart kilitlerle imzalar ve gözlenebilir davranış her durumda aynı değildir; entegrasyon uyumluluğunu kontrol edin.
* **Çekişmesiz Hızlı Yol:** Çekişme yokken waiter nesnesi oluşturulmaz; çekişmeli bekleme ve bildirim yine Python ve scheduler işi gerektirir.
* **Standart Adaptörler:** Gelişmiş RWLock zamanlama stratejilerine ihtiyaç duymayan Dependency Injection akışları için aynı üst düzey `.read` ve `.write` erişim biçimini sunan kilit ve condition sarmalayıcıları içerir.
    * *Kilit Adaptörleri:* `Lock` (Thread), `AsyncLock` (Asyncio)
    * *Condition Adaptörleri:* `Condition` (Thread), `AsyncCondition` (Asyncio)

### 🛡️ Kilit Stratejileri

Sisteminizin darboğaz profiline göre doğru kilit stratejisini seçebilirsiniz. Her stratejinin, iç içe geçmeye (reentrancy) izin veren bir `ReentrantWriter` versiyonu bulunur.

| Strateji Türü | Sınıf Adı (Thread / Async) | Açıklama | Ne Zaman Kullanılır? |
| --- | --- | --- | --- |
| **Yazar Öncelikli** | `RWLockWrite` / `AsyncRWLockWrite` | Bekleyen bir yazar varsa, yeni okuyucuların girmesini yasaklar. Yazar açlığını (starvation) önler. | Okuma yoğun sistemlerde yazarların ezilmesini engellemek için. |
| **Okur Öncelikli** | `RWLockRead` / `AsyncRWLockRead` | Yazarlar beklese bile yeni okuyucuları sürekli içeri alır. Maksimum paralellik sağlar. | Yazma işlemlerinin çok nadir veya önemsiz olduğu önbellek (cache) yapılarında. |
| **Okuyucu-Faz Adil** | `RWLockReaderPhaseFair` / `AsyncRWLockReaderPhaseFair` | Okuyucu ve yazar fazları arasında geçiş yapar, ancak açık bir okuyucu fazı başladıktan sonra geç gelen okuyucular da daha yüksek okuma throughput'u için o faza katılabilir. | Her okuyucu grubunu tamamen dondurmadan, sınırlı adalet ile yüksek okuma verimi istediğinizde. |
| **Adil (Fair)** | `RWLockFair` / `AsyncRWLockFair` | Her okuyucu fazının üyeliğini faz başında dondurur; böylece geç gelen okuyucular sıradaki yazarı kesemez. Kilit sahipleri ilerlediği sürece aç kalma riskini azaltmak üzere tasarlanmıştır. | Sıralı yazar erişiminin önemli olduğu çift yönlü trafiklerde. |
> 💡 **Condition Uyumluluğu:** `RWCondition` ve `AsyncRWCondition` yukarıdaki kilit stratejilerini kabul eder. Stratejiyi okuyucu/yazıcı zamanlama özelliklerine göre seçin.
<br/>

## ⚙️ Mimari Sınırlamalar

Geliştiricilerin bu kütüphaneyi kullanırken bilmesi gereken mühendislik gerçekleri:

1. **CPU-Bound vs I/O-Bound Gerçeği:**
`rwlocker`, gücünü Python'un GIL (Global Interpreter Lock) mekanizmasının serbest bırakıldığı anlardan (Ağ istekleri, Veritabanı sorguları, Dosya okuma/yazma vb.) alır. Eğer `time.sleep()` içermeyen, sadece ağır matematik hesaplamaları (CPU-Bound) yapan işlemler için kilit arıyorsanız, GIL sebebiyle gerçek paralellik elde edemezsiniz ve C-tabanlı olan standart `threading.Lock` daha düşük edinme maliyetine sahip olabilir. Bu kilitler, okuyucu bölümlerinin I/O veya kontrolü bırakan başka işlemler sırasında çakışabildiği durumlarda daha kullanışlıdır.
2. **Circular References (Döngüsel Referanslar):**
Kilit sınıfları, akıllı proxy nesneleri (`.read` ve `.write`) oluştururken döngüsel bir referans grafiği (Lock -> Proxy -> Lock) kurar. Bu tasarım bilerek seçilmiştir. Bellek temizliği (Garbage Collection) `__del__` ile değil, Python'un Cyclic GC motoru tarafından güvenle halledilir.
3. **Strict Nested Write Locks:**
`ReentrantWriter` varyantlarında aynı thread/task iç içe yazma kilitleri alabilir ve yazarken ayrıca okuma kilidi edinebilir. Diğer okuyucuların katılması için `.downgrade()` ile paylaşımlı erişim açılmalıdır.
4. **Adaletin Bedeli (The Cost of Fairness):**
 `Fair` stratejisi, katılımcılar ilerlemeye devam ederken aç kalma riskini azaltmak için bekleyen okuyucu ve yazarları fazlar hâlinde sıraya koyar. Bu sıralama bazı iş yüklerinde throughput’u düşürebilir. Kaydedilen condition iş yükünde Fair, dışlayıcı kilit kullanan standart `threading.Condition` temel çizgisinden yavaştı; bu karşılaştırma farklı kilit semantiğini içerir ve fairness maliyetini tek başına ölçmez.
5. **Condition Bellek Maliyeti (Memory vs CPU Trade-off):**
`rwlocker` her bekleyen thread/task için bir waiter nesnesi tutar. `notify_all()` her waiter’ı sinyaller ve O(N) sürer; belirli bir waiter’ı iptal/zaman aşımında kaldırma da O(N) olabilir. Bellek kullanımı bekleyen sayısıyla artar.
6. **Dışlayıcı Varsayılan:**
Doğrudan kilit işlemleri (ör. `with lock:`) dışlayıcı `.write` proxy’sini kullanır. Bu bir eşzamanlılık varsayılanıdır, güvenlik sınırı değildir; erişim modu önemliyse `.read` veya `.write` kullanın.

<br/>

## 📊 Performans ve Benchmark Sonuçları

Aşağıdaki grafikler, ağ/veritabanı benzeri I/O iş yüklerinin uçtan uca sonuçlarını gösterir. Tam iş yüklerini karşılaştırırlar; kilit edinme veya bildirim maliyetini tek başına ölçmezler.

**🖥️ Test Ortamı:** Tüm testler **Intel Core i7-12700H (2.4GHz)** işlemci ve **EndeavourOS (Arch tabanlı Linux)** işletim sistemi üzerinde, **Python 3.14.3** ve deneysel **Free-Threading (3.14.3t)** yorumlayıcıları kullanılarak gerçekleştirilmiştir.

**🧪 Test Metodolojisi:** Ölçüm başlamadan önce worker’lar oluşturulur ve bir Event/bariyerle serbest bırakılır. I/O senaryosu her işlemde 1 ms uyur ve 10 iterasyon çalıştırır. Sonuçlar scheduler, interpreter ve makine yükünden etkilenir; sıfır hata payı vaat etmez.

### 1. Okuma-Yazma Kilidi (RWLock) Karşılaştırmaları

Standart kilitler, sadece veri okuyor olsalar bile thread'leri tek bir sıraya girmeye zorlar. `rwlocker` ise eşzamanlı okuma erişimini serbest bırakır.

**Senkron (Thread) RWLock Performansı:**
Kaydedilmiş read-heavy workload verisinde paylaşımlı okuyucular, standart dışlayıcı kilitle serileştirilen okuyuculardan daha kısa sürede tamamlandı (ölçülen çalışmada en çok ~35x). Bu, farklı kilitleme semantiğinin toplam iş yükü süresidir; primitive edinme hızı değildir. Write-heavy sonuçlar da yalnızca o workload için geçerlidir.
<p align="center">
  <img src="./figures/sync_rwlock.svg" alt="Sync RWLock Benchmark" width="100%"/>
</p>
<br>

**Asenkron (Asyncio) RWLock Performansı:**
Bu benchmarkta asenkron görevler tek bir event-loop üzerinde çalışır. Grafikler, yalnızca en yüksek sonucu seçmek yerine mevcut yorumlayıcı ortamlarının tümünü gösterir. Read-heavy throughput, birden çok okuyucunun eşzamanlı I/O bekleyebilmesini yansıtır.
<p align="center">
  <img src="./figures/async_rwlock.svg" alt="Async RWLock Benchmark" width="100%"/>
</p>
<br>

### 2. Durum Değişkeni (RWCondition) Karşılaştırmaları

Condition benchmark’ları paylaşımlı okuma, predicate kontrolleri, scheduling ve yapay I/O dahil uçtan uca iş yükü throughput’unu ölçer; tek başına `notify_all()` maliyetini ölçmez. Her waiter ayrı sinyallendiğinden `notify_all()` O(N)’dir.

**Senkron (Thread) RWCondition Performansı:**
Kaydedilmiş ~45x sonuç RWCondition iş yükünün tamamını dışlayıcı kilit kullanan `threading.Condition` ile karşılaştırır; `notify_all()` çağrısının 45x hızlı olduğu anlamına gelmez.
<p align="center">
  <img src="./figures/sync_rwcondition.svg" alt="Sync RWCondition Benchmark" width="100%"/>
</p>
<br>

**Asenkron (Asyncio) RWCondition Performansı:**
Asenkron condition sonucu da tek başına bildirim maliyetini değil, uçtan uca iş yükünü karşılaştırır. Event-loop her bekleyeni işlemeye devam eder.
<p align="center">
  <img src="./figures/async_rwcondition.svg" alt="Async RWCondition Benchmark" width="100%"/>
</p>
<br>

Testler kilit stratejileri, condition değişkenleri, timeout, reentrancy ve cancellation akışlarını kapsar. Testlerin geçmesi yararlı regresyon kanıtıdır, ancak her olası schedule için doğruluk ispatı değildir.

<br/>

## 🚀 Başlangıç

### 🛠️ Bağımlılıklar

* Çalışma zamanı bağımlılığı yoktur.
* Benchmark grafikleri için isteğe bağlı: `pip install rwlocker[benchmark]`.
* Sadece Python Standart Kütüphanesi (`threading`, `asyncio`, `typing`, `collections`).
* Python 3.9–3.14 desteklenir; bu sürümler CI test matrisinde yer alır.

### 📦 Kurulum

Kütüphanenin dış hiçbir bağımlılığı yoktur, doğrudan Python'un çekirdek kütüphaneleriyle çalışır.

1. Depoyu klonla
    ```sh
    git clone https://github.com/TahsinCr/python-rwlocker.git
    ```

2. PIP aracılığıyla kurun
    ```sh
    pip install rwlocker
    ```

<br/>

### 💻 Kullanım Örnekleri

#### 1. Yüksek Eşzamanlı Bellek İçi Önbellek (Read-Heavy)

Binlerce request alan bir web sunucusunda, okuyucuların birbirini beklemesini engeller.

```python
import threading
import time
from typing import Any, Dict, Optional
from rwlocker.thread_rwlock import RWLockRead

class InMemoryCache:
    def __init__(self):
        self._lock = RWLockRead()
        self._cache: Dict[str, Any] = {}

    def get(self, key: str) -> Optional[Any]:
        # Okuyucular birbirini asla bloklamaz, maksimum verim sağlar!
        with self._lock.read:
            time.sleep(0.01) # Ağ veya Serileştirme (I/O) simülasyonu
            return self._cache.get(key)

    def set(self, key: str, value: Any) -> None:
        # Özel yazma kilidi alır. Yeni okuyucuları güvenle duraklatır.
        with self._lock.write:
            self._cache[key] = value

# KULLANIM
cache = InMemoryCache()
cache.set("status", "ONLINE")

# Bu 50 thread aynı anda, beklemeden okuma yapabilir.
threads = [threading.Thread(target=cache.get, args=("status",)) for _ in range(50)]
for t in threads: t.start()

```

#### 2. Finansal Kayıtlarda Atomik Derece Düşürme (Downgrading)

Veriyi güncelledikten (Write) hemen sonra, araya başka bir yazar (başka bir işlem) sızmadan aynı veriyi okuyup denetlemek (Read) için mükemmeldir.

```python
import uuid
from rwlocker.thread_rwlock import RWLockWriteReentrantWriter

class TransactionLedger:
    def __init__(self):
        self._lock = RWLockWriteReentrantWriter()
        self._balance = 1000.0

    def process_payment(self, amount: float):
        self._lock.write.acquire()
        try:
            # 1. FAZ: Dışlayıcı Yazma (Bakiyeyi güncelle)
            self._balance += amount
            
            # ATOMİK DOWNGRADE: Yazma Kilidi -> Okuma Kilidi'ne düşürülür.
            # Bekleyen okuyucular içeri alınır, ama diğer YAZARLAR kesinlikle bloklanır.
            self._lock.write.downgrade()
            
            # 2. FAZ: Paylaşımlı Okuma (Ağ üzerinden diğer servislere bildir)
            self._dispatch_audit_event(self._balance)
            
        finally:
            # Downgrade yaptığımız için artık READ kilidini bırakmalıyız.
            self._lock.read.release()

    def _dispatch_audit_event(self, balance: float):
        print(f"Denetim Raporu İletildi. Yeni Bakiye: {balance}")

```

#### 3. JWT Token Yenileme (Thundering Herd Çözümü)

Süresi dolan bir token'ı yenilemek için aynı anda uyanan yüzlerce task'ın (Thundering Herd izdihamı) auth sunucusunu çökertmesini önler.

```python
import asyncio
from rwlocker.async_rwlock import AsyncRWLockWrite

class AuthTokenManager:
    def __init__(self):
        self._lock = AsyncRWLockWrite()
        self._token = "valid_token"
        self._is_expired = False

    async def get_valid_token(self) -> str:
        # Hızlı Yol: Token geçerliyse 500 task burayı beklemeden, aynı anda geçer.
        async with self._lock.read:
            if not self._is_expired:
                return self._token
                
        # Yavaş Yol: Token süresi dolmuş. Yazma kilidi al.
        async with self._lock.write:
            # Çift kontrol (Double-checked locking): Biz kilidi beklerken 
            # başka bir task içeri girip token'ı yenilemiş olabilir.
            if self._is_expired:
                print("Token yenileniyor...")
                await asyncio.sleep(0.5)  # API İsteği
                self._token = "new_valid_token"
                self._is_expired = False
                
            return self._token

```

#### 4. Yüksek Frekanslı Telemetri (Adil Dağıtım)

Sensörden saniyede 100 kere veri geliyor (Yazma), ve 200 adet WebSocket bu veriyi okuyor (Okuma). Fair mimarisi iki tarafın da kilitlenmesini engeller.

```python
import asyncio
from typing import Dict
from rwlocker.async_rwlock import AsyncRWLockFair

class TelemetryDispatcher:
    def __init__(self):
        # Fair (Adil Kilit), okuma ve yazma yoğunluğunun birbirini boğmasını engeller.
        self._lock = AsyncRWLockFair()
        self._state = {"alt": 0.0, "lat": 0.0, "lon": 0.0}

    async def ingest_sensor_data(self, new_data: Dict[str, float]):
        """Yüksek frekanslı UDP yayınından gelen veriyi yazar."""
        async with self._lock.write:
            self._state.update(new_data)
            await asyncio.sleep(0.001)

    async def broadcast_to_clients(self):
        """Onlarca websocket istemcisine paralel olarak veriyi okur."""
        async with self._lock.read:
            # Kilidi en kısa sürede bırakmak için durumun hızlı bir kopyasını al
            current_state = self._state.copy()
            
        # Kilit serbestken, yavaş ağ I/O işlemlerini gerçekleştir
        await self._network_send(current_state)

    async def _network_send(self, data):
        await asyncio.sleep(0.05) # Ağ gecikmesi simülasyonu

```

#### 5. Olay Güdümlü Önbellek Yenileme (Thundering Herd Koruması)

Bu örnekte condition waiter’ları kuyruk üzerinden bekler; notify_all her bekleyeni sinyaller ve iş yükünün kalan süresi scheduler’a bağlıdır.

```python
import asyncio
from rwlocker.async_rwlock import AsyncRWLockRead, AsyncRWCondition

class GlobalConfigCache:
    def __init__(self):
        # Okuma çok yoğun olduğu için Read-Pref kilidi kullanıyoruz
        self._cond = AsyncRWCondition(AsyncRWLockRead())
        self._config = {"theme": "light", "version": 1}
        self._is_refreshing = False

    async def get_config(self) -> dict:
        """Binlerce concurrent request tarafından çağrılır."""
        async with self._cond.read:
            # Eğer DB'den güncelleme yapılıyorsa, DB'ye saldırmak yerine uyuyarak bekle.
            # wait_for metodu Spurious Wakeup (yanlış uyanma) durumlarını otomatik çözer.
            await self._cond.read.wait_for(lambda: not self._is_refreshing)
            return dict(self._config)

    async def force_refresh_from_db(self) -> None:
        async with self._cond.write:
            await self._cond.write.wait_for(lambda: not self._is_refreshing)
            self._is_refreshing = True

        try:
            # Simulate slow external I/O without holding the lock.
            await asyncio.sleep(0.5)
            async with self._cond.write:
                self._config = {"theme": "dark", "version": self._config["version"] + 1}
                self._is_refreshing = False
                # Signals each queued waiter (O(N)).
                self._cond.write.notify_all()
        except BaseException:
            async with self._cond.write:
                if self._is_refreshing:
                    self._is_refreshing = False
                    self._cond.write.notify_all()
            raise
```

#### 6. İsabetli İş Kuyruğu (Thread Condition & Hedefli Uyandırma)

Sisteme 3 adet yeni iş geldiğinde, boştaki 50 adet worker thread'in hepsini uyandırmak ("Thundering Herd" problemi) yerine, sadece `notify(n=3)` diyerek isabetli uyandırma yapar.

```python
from collections import deque
import threading
from rwlocker.thread_rwlock import RWLockFair, RWCondition

class ImageProcessingQueue:
    def __init__(self):
        # Üretici ve Tüketicilerin birbirini ezmemesi için adil Fair stratejisi
        self._cond = RWCondition(RWLockFair())
        self._queue = deque()

    def add_jobs(self, jobs: list[str]):
        """Üretici: Kuyruğa yeni işler ekler."""
        with self._cond.write:
            self._queue.extend(jobs)
            
            # AKILLI SİNYAL: Kaç iş geldiyse, sadece o kadar Thread'i uyandır.
            # Sistemdeki diğer uyuyan Thread'ler boşuna CPU harcamaz.
            self._cond.write.notify(n=len(jobs))

    def consume_job(self):
        """Tüketici: İş gelene kadar uyur, gelince alır."""
        with self._cond.write:
            # Kuyrukta iş yoksa güvenle bekle
            self._cond.write.wait_for(lambda: len(self._queue) > 0)
            job = self._queue.popleft()

        # Kilidi bıraktıktan SONRA ağır işlemi gerçekleştir.
        print(f"İşleniyor: {job}")

```

#### 7. Kilit Tarzı Arayüz Uyumluluğu

Doğrudan kilit metotları dışlayıcı `.write` proxy'sine yönelir. Standart kilit veya condition sınıfları için yazılmış koda vermeden önce metot imzalarını ve gözlenebilir davranışı denetleyin; `.read` ve `.write` modları açıkça seçer.

```python
import threading
from rwlocker.thread_rwlock import RWLockFair, Lock

# Senaryo: Üçüncü parti bir fonksiyon standart threading.Lock bekliyor
def third_party_worker(standard_lock: threading.Lock, data: list):
    # Dış kütüphane ".write" veya ".read" proxy'lerini bilmez.
    # Doğrudan "with lock:" kullanır.
    with standard_lock:
        data.append("Processed")
        print("Standart API ile kilit alındı!")

# 1. YÖNTEM: Gelişmiş bir RWLock nesnesini doğrudan içeri verebilirsiniz!
# RWLockFair, bu çağrıları algılar ve güvenli olduğu için otomatik 
# olarak .write (exclusive) moduna geçer.
advanced_lock = RWLockFair()
third_party_worker(advanced_lock, [])

# 2. YÖNTEM: Sadece standart kilit davranışına ihtiyacınız varsa, 
# aynı yapıya sahip standart adaptörleri kullanabilirsiniz.
simple_adapter_lock = Lock()
third_party_worker(simple_adapter_lock, [])
```

*Daha fazla örnek için lütfen [examples][examples-url] klasörüne göz atın.*

Önerilen özelliklerin (ve bilinen sorunların) tam listesi için [açık sorunlara][issues-url] bakın.

<br/>

## 🤝 Katkıda Bulunma (Contributing)

Açık kaynak topluluğu, bu tür düşük seviyeli (low-level) ve yüksek performanslı kütüphanelerin sınırlarını zorlamak için en mükemmel yerdir. `rwlocker`'ı daha hızlı, daha güvenli veya daha yetenekli hale getirecek her türlü katkınız bizim için çok değerlidir!

Özellikle aşağıdaki konulardaki katkılarınızı sabırsızlıkla bekliyoruz:
* ⚡ **Performans Optimizasyonları:** Kilitlenme (overhead) maliyetlerini daha da düşürecek algoritmik yaklaşımlar.
* 🏗️ **Farklı Senaryolar Üzerine Geliştirmeler:** Kilit motorlarının farklı senaryolar için optimize edilmiş varyantlarının oluşturulması ve geliştirilmesi.
* 🐛 **Uç Durum (Edge-Case) Testleri:** Deadlock veya starvation (açlık) senaryolarını tespit edecek yeni ve zorlayıcı birim testleri.

Eğer harika bir fikriniz veya çözümünüz varsa, lütfen aşağıdaki adımları izleyerek bir **Pull Request (PR)** oluşturun. Ayrıca yeni bir özellik önermek için "enhancement" etiketiyle bir Issue da açabilirsiniz.

Projeyi faydalı bulduysanız sağ üstten bir **Yıldız (⭐)** vermeyi unutmayın. Desteğiniz için teşekkürler!

### 🛠️ Katkı Adımları

1. Projeyi kendi hesabınıza **Fork**'layın.

2. Yeni bir özellik dalı (branch) oluşturun:
    ```sh
    git checkout -b feature/HarikaBirOzellik
    ```

3. Yaptığınız değişiklikleri **Commit**'leyin (Açıklayıcı mesajlar kullanmaya özen gösterin):
    ```sh
    git commit -m 'feat: AsyncRWLock için O(1) maliyetli yeni bir optimizasyon eklendi'

    ```


4. Değişiklikleri kendi dalınıza **Push**'layın:
    ```sh
    git push origin feature/HarikaBirOzellik

    ```

5. Bu repoya gelerek bir **Pull Request (Çekme İsteği)** açın.

> ⚠️ **Önemli Geliştirici Notu:** `rwlocker` mimarisi *deadlock*, *OS-Interrupts (İşletim Sistemi Kesintileri)* ve *reentrancy* senaryolarına karşı son derece hassastır. PR açmadan önce CI matrisindeki desteklenen Python sürümlerinde test paketini çalıştırın ve eşzamanlılık değişikliklerini farklı zamanlama akışlarına karşı gözden geçirin.


<br/>

## 🙏 Teşekkür ve Lisans

Bu proje **MIT Lisansı** altında tamamen açık kaynaklıdır ([License][license-url]).

Testlerin ve benchmark mimarilerinin geliştirilmesinde, en derin Python C-API gerçekleriyle yüzleşmemizi sağlayan tüm Python açık kaynak topluluğuna teşekkürler.

* **PyPI:** [RWLocker on PyPI][pypi-project-url]
* **Kaynak Kod:** [Tahsincr/python-rwlocker][project-url]

Herhangi bir hata (bug) bulursanız veya mimari bir katkıda bulunmak isterseniz GitHub üzerinden Issue açmaktan veya Pull Request göndermekten çekinmeyin!

<br/>

## 📫 İletişim

X: [@TahsinCrs][x-url]

Linkedin: [@TahsinCr][linkedin-url]

Email: TahsinCrs@gmail.com


<!-- IMAGES URL -->

[contributors-shield]: https://img.shields.io/github/contributors/TahsinCr/python-rwlocker.svg?style=for-the-badge

[forks-shield]: https://img.shields.io/github/forks/TahsinCr/python-rwlocker.svg?style=for-the-badge

[stars-shield]: https://img.shields.io/github/stars/TahsinCr/python-rwlocker.svg?style=for-the-badge

[issues-shield]: https://img.shields.io/github/issues/TahsinCr/python-rwlocker.svg?style=for-the-badge

[license-shield]: https://img.shields.io/github/license/TahsinCr/python-rwlocker.svg?style=for-the-badge

[linkedin-shield]: https://img.shields.io/badge/-LinkedIn-black.svg?style=for-the-badge&logo=linkedin&colorB=555



<!-- Github Project URL -->

[project-url]: https://github.com/TahsinCr/python-rwlocker

[pypi-project-url]: https://pypi.org/project/rwlocker

[contributors-url]: https://github.com/TahsinCr/python-rwlocker/graphs/contributors

[stars-url]: https://github.com/TahsinCr/python-rwlocker/stargazers

[forks-url]: https://github.com/TahsinCr/python-rwlocker/network/members

[issues-url]: https://github.com/TahsinCr/python-rwlocker/issues

[examples-url]: https://github.com/TahsinCr/python-rwlocker/tree/main/examples

[license-url]: https://github.com/TahsinCr/python-rwlocker/blob/main/LICENSE

[changelog-url]:https://github.com/TahsinCr/python-rwlocker/blob/main/CHANGELOG.md



<!-- Contacts URL -->

[linkedin-url]: https://linkedin.com/in/TahsinCr

[x-url]: https://twitter.com/TahsinCrs



<!-- File URL -->

[lang-tr-url]: https://github.com/TahsinCr/python-rwlocker/blob/main/README_tr.md

[lang-en-url]: https://github.com/TahsinCr/python-rwlocker/blob/main/README.md

[lang-ru-url]: https://github.com/TahsinCr/python-rwlocker/blob/main/README_ru.md
