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

`rwlocker` ise **Shared (Paylaşımlı)** okuma mantığına dayanır. Yazar kilitleri dışlayıcıyken, okuyucu kilitleri aynı anda binlerce thread veya task'ın birbirini engellemeden veriye erişmesine izin verir.  Özellikle GIL'in (Global Interpreter Lock) serbest bırakıldığı I/O (Ağ/Disk/Veritabanı) işlemlerinde sistemin gerçek potansiyelini ortaya çıkarır.

### 🚀 Peki ya Condition (Durum) Değişkenleri?
Standart kütüphanedeki `Condition` yapıları, `notify_all()` çağrıldığında bekleyen tüm thread/task'ları O(N) zaman karmaşıklığıyla (tek tek tarayarak) uyandırır. Bu durum, yüzlerce okuyucunun aynı anda uyandığı senaryolarda işlemciyi kilitleyen **"Önbellek İzdihamı" (Cache Stampede)** yaratır. `rwlocker`, tamamen `deque` (Thread) ve `dict` (Asyncio) tabanlı kuyruk mimarisiyle çalışır. Bekleyen görevleri işletim sistemini veya event-loop'u bloklamadan saf **O(1) zaman karmaşıklığında** uyandırarak izdihamları mimari seviyede yok eder.

### ✨ Temel Özellikler

* **Hem Thread Hem Asyncio Desteği:** Aynı API mantığıyla hem standart işletim sistemi thread'lerini (`rwlocker.thread_rwlock`) hem de event-loop tabanlı task'ları (`rwlocker.async_rwlock`) yönetebilirsiniz.
* **Akıllı Proxy Mimarisi (Smart Proxy Architecture):** `.read` ve `.write` proxy'leri ile `with` ve `async with` context manager'larını sezgisel olarak kullanma imkanı.
* **Atomik Derece Düşürme (Downgrading):** Yazma kilidini tamamen serbest bırakmadan, araya başka bir yazar girmesine izin vermeden anında Okuma kilidine (`downgrade()`) düşürebilme özelliği.
* **Güvenli İç İçe Geçme (Safe Reentrancy):** Aynı thread veya task'ın, Deadlock'a (ölümcül kilitlenme) sebep olmadan tekrar tekrar yazma kilidi alabilmesi için O(1) bellek işaretçisi (memory pointer) takibi.
* **Saf O(1) Durum Değişkenleri (Pure O(1) Conditions):** Standart `Condition` yapılarının aksine `notify_all()` çağrılarında bekleme listesini tek tek taramaz (O(N) tarama maliyetini atlar). Özelleştirilmiş C-seviyesi mikro-kuyruk mimarisi sayesinde binlerce görevi "Önbellek İzdihamı" (Cache Stampede) yaratmadan ve CPU'yu boğmadan anında uyandırır.
* **Asenkron İptal Güvenliği (Cancellation Safety & Shielding):** `asyncio` ortamındaki görev iptallerine (`CancelledError`) karşı tam direnç. Bir görev kilit beklerken veya `Condition.wait()` içindeyken iptal edilirse, sistem durumu asla bozulmaz. Kilit güvenle geri alınır, "zombi" bekleyiciler oluşmaz ve bekleme kuyrukları temiz kalır.
* **%100 Tak-Çalıştır (Drop-in Replacement):** Gelişmiş kilitlerinizi (`RWLockFair` vb.) ve durum değişkenlerinizi (`RWCondition` vb.) hiçbir kod değişikliği yapmadan standart `threading.Lock`, `asyncio.Lock`, `threading.Condition` veya `asyncio.Condition` bekleyen üçüncü parti kütüphanelere (SQLAlchemy, requests, FastAPI vb.) doğrudan aktarabilirsiniz. Standart API çağrıları (örn. `lock.acquire()`, `cond.wait()`) otomatik ve güvenli bir şekilde `.write` (dışlayıcı) proxy'sine yönlendirilir.
* **"Happy Path" Performans İzolasyonu:** Kilit ve kuyruk uyanmalarında O(N) maliyetli çöp temizleme işlemlerini tamamen bypass eden yeni nesil mimari. İşletim sistemi kesintilerine (OS-Interrupt) ve zaman aşımlarına (timeout) karşı tam koruma sağlarken, başarılı uyanma işlemlerini sıfır CPU ek yükü ile tamamlar.
* **Standart Adaptörler (Standard Adapters):** Bağımlılık enjeksiyonu (Dependency Injection) süreçlerinde aynı mimari imzayı (`.read` ve `.write`) korumak istediğiniz ancak gelişmiş kilit stratejilerine ihtiyaç duymadığınız durumlar için standart sarmalayıcılar içerir.
    * *Kilit Adaptörleri:* `Lock` (Thread), `AsyncLock` (Asyncio)
    * *Condition Adaptörleri:* `Condition` (Thread), `AsyncCondition` (Asyncio)

### 🛡️ Kilit Stratejileri

Sisteminizin darboğaz profiline göre doğru kilit stratejisini seçebilirsiniz. Her stratejinin, iç içe geçmeye (reentrancy) izin veren bir `ReentrantWriter` versiyonu bulunur.

| Strateji Türü | Sınıf Adı (Thread / Async) | Açıklama | Ne Zaman Kullanılır? |
| --- | --- | --- | --- |
| **Yazar Öncelikli** | `RWLockWrite` / `AsyncRWLockWrite` | Bekleyen bir yazar varsa, yeni okuyucuların girmesini yasaklar. Yazar açlığını (starvation) önler. | Okuma yoğun sistemlerde yazarların ezilmesini engellemek için. |
| **Okur Öncelikli** | `RWLockRead` / `AsyncRWLockRead` | Yazarlar beklese bile yeni okuyucuları sürekli içeri alır. Maksimum paralellik sağlar. | Yazma işlemlerinin çok nadir veya önemsiz olduğu önbellek (cache) yapılarında. |
| **Okuyucu-Faz Adil** | `RWLockReaderPhaseFair` / `AsyncRWLockReaderPhaseFair` | Okuyucu ve yazar fazları arasında geçiş yapar, ancak açık bir okuyucu fazı başladıktan sonra geç gelen okuyucular da daha yüksek okuma throughput'u için o faza katılabilir. | Her okuyucu grubunu tamamen dondurmadan, sınırlı adalet ile yüksek okuma verimi istediğinizde. |
| **Adil (Fair)** | `RWLockFair` / `AsyncRWLockFair` | Her okuyucu fazının üyeliğini faz başında dondurur; böylece geç gelen okuyucular sıradaki yazarı kesemez. İki tarafın da aç kalmasını engeller ve yazar gecikmesini daha deterministik hale getirir. | Yüksek frekanslı (MAVLink, WebSocket vb.) çift yönlü trafiklerde ve yazar gecikmesinin öngörülebilir olması gerektiğinde. |
> 💡 **Condition Uyumluluğu (Condition Compatibility):** Kütüphanedeki `RWCondition` ve `AsyncRWCondition` sınıfları, yukarıdaki tüm kilit stratejilerini içine alacak şekilde (Dependency Injection) tasarlanmıştır. Sisteminize en uygun kilidi seçip, onu O(1) hızında bir durum makinesine dönüştürebilirsiniz.
<br/>

## ⚙️ Mimari Sınırlamalar

Geliştiricilerin bu kütüphaneyi kullanırken bilmesi gereken mühendislik gerçekleri:

1. **CPU-Bound vs I/O-Bound Gerçeği:**
`rwlocker`, gücünü Python'un GIL (Global Interpreter Lock) mekanizmasının serbest bırakıldığı anlardan (Ağ istekleri, Veritabanı sorguları, Dosya okuma/yazma vb.) alır. Eğer `time.sleep()` içermeyen, sadece ağır matematik hesaplamaları (CPU-Bound) yapan işlemler için kilit arıyorsanız, GIL sebebiyle gerçek paralellik elde edemezsiniz ve C-tabanlı olan standart `threading.Lock` bir miktar daha hızlı çalışacaktır. **RWLock'un savaş alanı I/O işlemleridir.**
2. **Circular References (Döngüsel Referanslar):**
Kilit sınıfları, akıllı proxy nesneleri (`.read` ve `.write`) oluştururken döngüsel bir referans grafiği (Lock -> Proxy -> Lock) kurar. Bu tasarım bilerek seçilmiştir. Bellek temizliği (Garbage Collection) `__del__` ile değil, Python'un Cyclic GC motoru tarafından güvenle halledilir.
3. **Strict Nested Write Locks:**
`ReentrantWriter` varyantlarında sadece "Yazma (Write)" kilitleri iç içe geçirilebilir (nested). Yazar, okuyucu kilidi almak istiyorsa bunu zımni (implicit) olarak yapamaz, açıkça `.downgrade()` metodunu çağırmak zorundadır. Bu, deadlock'ları mimari seviyede engellemek için alınmış kesin bir karardır.
4. **Adaletin Bedeli (The Cost of Fairness):**
Eğer `Fair` (Adil) stratejisini kullanıyorsanız, sistem kimsenin aç kalmamasını (No Starvation) garanti altına almak için okuyucu ve yazarlar arasında katı bir sıraya dayalı bağlam değişimi (context switch) yapar. Özellikle **`RWCondition` (Durum Değişkeni)** kullanımlarında ve yazma yoğun (write-heavy) senaryolarda, bu adil sırayı koruma çabası, hiçbir kuralı olmayan standart C-tabanlı `Condition` nesnesine göre belirli bir yavaşlamaya sebep olur (Benchmark'larda Fair'nun 0.50x çıkmasının sebebi budur). Bu bir hata veya optimizasyon eksikliği değil, "adaleti" sağlamak için ödenmesi gereken mühendislik bedelidir.
5. **Condition Bellek Maliyeti (Memory vs CPU Trade-off):**
Standart `threading.Condition` arka planda basit bir C seviyesi sayaç tutarken; `rwlocker`, O(1) hızında uyanma garantisi verebilmek için bekleyen her bir task/thread için bellekte minik bir `Lock` veya `asyncio.Future` objesi saklar. Bu, CPU darboğazlarını (Cache Stampede) tamamen çözer ancak on binlerce görevin beklediği ekstrem durumlarda RAM üzerinde ufak bir bellek ayak izi (memory footprint) oluşturur.
6. **Tak-Çalıştır (Drop-in) Güvenlik Varsayımı (Drop-in Security Assumption):**
Kilit nesnelerini `.read` veya `.write` proxy'lerini belirtmeden, doğrudan standart bir kilit gibi kullanırsanız (örneğin `with lock:` veya `await cond.wait()`), sistem geriye dönük uyumluluk ve mutlak veri güvenliği sağlamak adına otomatik olarak **Yazma (Exclusive/Write)** kilidini alır. Bu, dış kütüphanelerin veriyi bozmasını engellemek için kurulan "Secure by Default" (Varsayılan Olarak Güvenli) bir yaklaşımdır.

<br/>

## 📊 Performans ve Benchmark Sonuçları

Aşağıdaki benchmark sonuçları, Python'un GIL (Global Interpreter Lock) mekanizmasının serbest bırakıldığı veya bağlam değiştirildiği Ağ ve Veritabanı I/O işlemlerinde `rwlocker`'ın gerçek potansiyelini göstermektedir.

**🖥️ Test Ortamı:** Tüm testler **Intel Core i7-12700H (2.4GHz)** işlemci ve **EndeavourOS (Arch tabanlı Linux)** işletim sistemi üzerinde, **Python 3.14.3** ve deneysel **Free-Threading (3.14.3t)** yorumlayıcıları kullanılarak gerçekleştirilmiştir.

**🧪 Test Metodolojisi:** Hata payını sıfıra indirmek ve mutlak hassasiyet sağlamak için, okuyucu ve yazar (reader/writer) olarak belirtilen tüm birimler (thread veya async task) önceden oluşturulur ve bir senkronizasyon `Event` (Olay) bariyerinde bekletilir. Olay tetiklendiği an hepsi aynı anda koşturulur. İş yükleri, gerçek ağ/veritabanı gecikmelerini simüle etmek için art arda 10 iterasyon boyunca katı bir şekilde `time.sleep(0.001)` veya `asyncio.sleep(0.001)` işlemi uygulayan `IOBoundScenario` üzerinden test edilmiştir.

### 1. Okuma-Yazma Kilidi (RWLock) Karşılaştırmaları

Standart kilitler, sadece veri okuyor olsalar bile thread'leri tek bir sıraya girmeye zorlar. `rwlocker` ise eşzamanlı okuma erişimini serbest bırakır.

**Senkron (Thread) RWLock Performansı:**
Read-Heavy (Okuma Yoğun) senaryolarda standart C tabanlı kilitler sistemi boğarken, `rwlocker` **~35 kata kadar hız artışı** sağlar. Paralelliğin doğası gereği mümkün olmadığı Write-Heavy (Yazma Yoğun) iş yüklerinde bile, sıfır tahsisli (zero-allocation) yapısı sayesinde standart kilide denktir.
<p align="center">
  <img src="./figures/sync_rwlock.svg" alt="Sync RWLock Benchmark" width="100%"/>
</p>
<br>

**Asenkron (Asyncio) RWLock Performansı:**
Asenkron görevler tek bir event-loop üzerinde eşzamanlı çalıştığı için, yorumlayıcı modları (GIL açık/kapalı) sonuçları önemli ölçüde değiştirmez. Bu nedenle asenkron metriklerinde en yüksek performans gösteren ortam referans alınmıştır. Burada `rwlocker`, binlerce okuyucu görevinin aynı anda I/O beklemesine izin vererek **~30 kat daha yüksek işlem hacmi** (throughput) elde eder.
<p align="center">
  <img src="./figures/async_rwlock.svg" alt="Async RWLock Benchmark" width="100%"/>
</p>
<br>

### 2. Durum Değişkeni (RWCondition) Karşılaştırmaları

Standart `Condition` değişkenleri, yayın (`notify_all`) sırasında uyuyan tüm thread/task'ları tek tek tarayarak `O(N)` zaman harcar ve devasa işlemci (CPU) kilitlenmelerine ("Önbellek İzdihamlarına") neden olur. `rwlocker`, saf `O(1)` kuyruklama mimarisi ile bunu tamamen ortadan kaldırır.

**Senkron (Thread) RWCondition Performansı:**
100 uyuyan okuyucu aynı anda uyandırıldığında, `rwlocker` işletim sistemini kilitlemeden onları anında işler. Bu mimari sıçrama, standart kütüphanedeki `threading.Condition`'a kıyasla **~45 kata kadar hızlanma** ile sonuçlanır.
<p align="center">
  <img src="./figures/sync_rwcondition.svg" alt="Sync RWCondition Benchmark" width="100%"/>
</p>
<br>

**Asenkron (Asyncio) RWCondition Performansı:**
Olay güdümlü (event-driven) önbellek sistemlerinde, bekleyen yüzlerce web isteğini aynı anda uyandırmak büyük bir darboğazdır. `AsyncRWCondition`, standart asyncio kısıtlamalarını tamamen atlayarak devasa uyanma senaryolarında **~45 kat daha yüksek işlem hacmine** ulaşır ve event-loop'un donmasını kesin olarak engeller.
<p align="center">
  <img src="./figures/async_rwcondition.svg" alt="Async RWCondition Benchmark" width="100%"/>
</p>
<br>

*(Not: Tüm kilit, adaptör ve condition sınıfları; reentrancy, deadlock, timeout, OS kesintileri, O(N) kaçakları ve cancellation safety senaryolarını kapsayan devasa **412 farklı birim testinden (unit tests)** 0 hata ile geçmiş ve tüm bu test paketi yalnızca **15.7 saniyede** tamamlanmıştır.)*

<br/>

## 🚀 Başlangıç

### 🛠️ Bağımlılıklar

* Dış bağımlılık bulunmamaktadır.
* Sadece Python Standart Kütüphanesi (`threading`, `asyncio`, `typing`, `collections`).
* Python 3.9+ ile tam uyumlu.

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

Süresi dolan bir veriyi binlerce task aynı anda veri tabanından çekmeye çalışırsa DB çöker. `AsyncRWCondition` ile 1 task veriyi güncellerken, diğer 999 task CPU'yu boğmadan (O(1) hızında) güvenle uyutulur ve ardından tek seferde uyandırılır.

```python
import asyncio
from rwlocker.async_rwlock import AsyncRWLockRead, AsyncRWCondition

class GlobalConfigCache:
    def __init__(self):
        # Okuma çok yoğun olduğu için Read-Pref kilidi kullanıyoruz
        self._cond = AsyncRWCondition(AsyncRWLockRead())
        self._config = {}
        self._is_refreshing = False

    async def get_config(self) -> dict:
        """Binlerce concurrent request tarafından çağrılır."""
        async with self._cond.read:
            # Eğer DB'den güncelleme yapılıyorsa, DB'ye saldırmak yerine uyuyarak bekle.
            # wait_for metodu Spurious Wakeup (yanlış uyanma) durumlarını otomatik çözer.
            await self._cond.read.wait_for(lambda: not self._is_refreshing)
            return self._config

    async def force_refresh_from_db(self) -> None:
        """Webhook ile tetiklendiğinde tek başına çalışır."""
        async with self._cond.write:
            self._is_refreshing = True
            
            await asyncio.sleep(0.5) # Yavaş Veritabanı sorgusu simülasyonu
            self._config = {"theme": "dark", "version": 2}
            self._is_refreshing = False
            
            # Bekleyen BİNLERCE okuyucu task'ı O(1) hızında uyandır. İzdiham yok!
            self._cond.write.notify_all()
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
        with self._cond.read:
            # Kuyrukta iş yoksa güvenle bekle
            self._cond.read.wait_for(lambda: len(self._queue) > 0)
            job = self._queue.popleft()

        # Kilidi bıraktıktan SONRA ağır işlemi gerçekleştir.
        print(f"İşleniyor: {job}")

```

#### 7. %100 Tak-Çalıştır (Drop-in Replacement) Uyumluluğu

Standart bir `threading.Lock` veya `asyncio.Lock` bekleyen mevcut (legacy) kodlarınızı veya üçüncü parti kütüphanelerinizi değiştirmeden `rwlocker` gücünü sisteminize enjekte edin.

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

> ⚠️ **Önemli Geliştirici Notu:** `rwlocker` mimarisi *deadlock*, *OS-Interrupts (İşletim Sistemi Kesintileri)* ve *reentrancy* senaryolarına karşı son derece hassastır. Lütfen PR açmadan önce projedeki **412+ birim testinin (unit tests) tamamının firesiz geçtiğinden** ve kodunuzun **Python 3.9+** standartlarıyla uyumlu olduğundan emin olun.


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
