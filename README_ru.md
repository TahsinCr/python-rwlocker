[![Contributors][contributors-shield]][contributors-url]
[![Forks][forks-shield]][forks-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]
[![MIT License][license-shield]][license-url]
[![LinkedIn][linkedin-shield]][linkedin-url]

[Русский][lang-ru-url] | [English][lang-en-url] | [Türkçe][lang-tr-url]



<!-- About -->
<div align="center">


<h3 align="center">Python RWLocker</h3>

<p align="center">

Продвинутые, высокопроизводительные синхронные/асинхронные блокировки чтения-записи (Read-Write Locks) на основе конечных автоматов.

[Changelog][changelog-url] · [Report Bug][issues-url] · [Request Feature][issues-url]
 
</p>

</div>

<br/>

## 📋 О проекте

### 🚀 Почему RWLocker?

Стандартные блокировки в Python (`Lock`, `RLock`) являются **Эксклюзивными (Exclusive)**. Даже если к ним обратятся 100 читателей (например, потоков, извлекающих данные из базы данных), они будут вынуждены выполнять эти операции последовательно, один за другим.

В свою очередь, `rwlocker` основан на логике **Совместного (Shared)** чтения. В то время как блокировки писателей эксклюзивны, блокировки читателей позволяют нескольким потокам или задачам обращаться к данным одновременно, если критическая секция допускает совместный доступ. Это может повысить пропускную способность, когда общие критические секции ожидают I/O или иным образом уступают управление; ускорение не гарантируется для каждой нагрузки.

### 🚀 А как насчет условных переменных (Condition)?
`rwlocker` хранит ожидающих в очередях `collections.deque`. Добавление и извлечение FIFO амортизированно O(1); уведомление N ожидающих занимает O(N), поскольку сигнал получает каждый из них. Удаление отдельного ожидающего при тайм-ауте или отмене также может занять O(N).

### ✨ Основные возможности

* **Поддержка как Thread, так и Asyncio:** Вы можете управлять как стандартными потоками ОС (`rwlocker.thread_rwlock`), так и задачами на основе цикла событий (`rwlocker.async_rwlock`), используя соответствующие синхронные и асинхронные интерфейсы.
* **Архитектура умных прокси (Smart Proxy Architecture):** Интуитивно понятное использование контекстных менеджеров `with` и `async с` через прокси `.read` и `.write`.
* **Атомарное понижение уровня (Downgrading):** Возможность мгновенно понизить блокировку Записи до блокировки Чтения (`downgrade()`), не освобождая блокировку полностью и не позволяя другим писателям вмешаться.
* **Реентерабельность записи:** Варианты `ReentrantWriter` позволяют потоку или задаче-владельцу повторно захватывать блокировку записи и захватывать блокировку чтения; остальные читатели могут присоединиться после вызова `.downgrade()`.
* **Очереди ожидания Condition:** Обычное добавление и извлечение FIFO амортизированно O(1); уведомление всех ожидающих и удаление отдельного отмененного ожидающего могут занимать O(N). `Condition.wait()` требует ровно одного захвата блокировки; вложенная глубина вызывает `RuntimeError`, поскольку она не сохраняется и не восстанавливается.
* **Очистка при асинхронной отмене:** Отмененная задача удаляет свой waiter из очереди; ожидание condition повторно захватывает связанную блокировку перед распространением отмены.
* **Интерфейс блокировки:** Прямые операции используют эксклюзивный прокси `.write`. Сигнатуры и наблюдаемое поведение не полностью совпадают со стандартными блокировками; совместимость интеграции следует проверять.
* **Быстрый путь без конкуренции:** При отсутствии конкуренции объект waiter не создается; ожидания и уведомления при конкуренции требуют работы Python и планировщика.
* **Стандартные адаптеры (Standard Adapters):** Включает стандартные обертки для процессов внедрения зависимостей (Dependency Injection), когда вы хотите сохранить ту же архитектурную сигнатуру (`.read` и `.write`), но не нуждаетесь в сложных стратегиях блокировки.
    * *Адаптеры блокировок:* `Lock` (Thread), `AsyncLock` (Asyncio)
    * *Адаптеры Condition:* `Condition` (Thread), `AsyncCondition` (Asyncio)

### 🛡️ Стратегии блокировок

Вы можете выбрать правильную стратегию блокировки в зависимости от профиля узких мест вашей системы. У каждой стратегии есть вариант `ReentrantWriter`, который допускает реентерабельность.

| Тип стратегии | Имя класса (Thread / Async) | Описание | Когда использовать? |
| --- | --- | --- | --- |
| **Приоритет писателей** | `RWLockWrite` / `AsyncRWLockWrite` | Запрещает доступ новым читателям, если есть ожидающий писатель. Отдает приоритет ожидающим писателям и может снизить риск их голодания, пока они продолжают получать время выполнения. | Чтобы писатели не задыхались в системах с интенсивным чтением. |
| **Приоритет читателей** | `RWLockRead` / `AsyncRWLockRead` | Постоянно впускает новых читателей, даже если писатели ждут. Обеспечивает максимальный параллелизм. | В структурах кэширования, где операции записи очень редки или некритичны. |
| **Справедливая по фазам чтения** | `RWLockReaderPhaseFair` / `AsyncRWLockReaderPhaseFair` | Переключается между фазами чтения и записи, но читатели, пришедшие после открытия фазы чтения, все еще могут присоединиться к ней ради более высокой пропускной способности чтения. | Когда нужна ограниченная справедливость без полного замораживания каждой читательской группы. |
| **Справедливая (Fair)** | `RWLockFair` / `AsyncRWLockFair` | Фиксирует состав каждой фазы чтения в момент ее открытия, поэтому поздние читатели не могут вклиниться перед уже ожидающим писателем. Снижает риск голодания, если владельцы блокировки продолжают работу. | Для двунаправленного трафика, где важен упорядоченный доступ писателей. |
> 💡 **Совместимость с Condition:** `RWCondition` и `AsyncRWCondition` принимают описанные стратегии блокировок. Выбирайте стратегию по поведению планирования читателей и писателей.
<br/>

## ⚙️ Архитектурные ограничения

Инженерные факты, которые необходимо знать разработчикам при использовании этой библиотеки:

1. **Реальность CPU-Bound и I/O-Bound:**
`rwlocker` черпает свою мощь из моментов, когда Python снимает GIL (Global Interpreter Lock) (Сетевые запросы, запросы к БД, файловый ввод-вывод и т.д.). Если вы ищете блокировку для чисто тяжелых математических вычислений (CPU-Bound), которые не используют уступки I/O вроде `time.sleep()`, вы не достигнете истинного параллелизма из-за GIL, и стандартный `threading.Lock` может иметь меньшие затраты на захват. **Истинное поле битвы RWLock — это операции ввода-вывода (I/O).**
2. **Циклические ссылки (Circular References):**
Классы блокировок создают граф циклических ссылок (Lock -> Proxy -> Lock) при создании смарт-прокси-объектов (`.read` и `.write`). Такой дизайн используется преднамеренно. Очистка памяти (Garbage Collection) безопасно выполняется механизмом циклической сборки мусора Python, а не через `__del__`.
3. **Строго вложенные блокировки записи:**
В вариантах `ReentrantWriter` владелец может повторно захватывать блокировку записи и дополнительно получить блокировку чтения. Другие читатели смогут присоединиться после вызова `.downgrade()`, открывающего совместный доступ. Текущий читатель может повторно захватить `.read`, даже если ожидают писатели; попытка захватить `.write`, удерживая `.read`, вызывает `RuntimeError`, предотвращая взаимную блокировку.
4. **Цена справедливости (The Cost of Fairness):**
Стратегия `Fair` распределяет ожидающих читателей и писателей по фазам, чтобы снизить риск голодания при условии, что участники продолжают работу. Такой порядок может снизить пропускную способность некоторых сценариев. В записанном condition workload вариант Fair оказался медленнее стандартного `threading.Condition` с эксклюзивной блокировкой; сравнение включает разные семантики и не измеряет отдельно накладные расходы fairness.
5. **Компромисс памяти и CPU для Condition (Memory vs CPU Trade-off):**
`rwlocker` хранит объект waiter для каждого ожидающего потока или задачи. `notify_all()` сигнализирует каждого ожидающего и занимает O(N); удаление отдельного waiter при отмене или тайм-ауте также может занять O(N). Память растет вместе с числом ожидающих. `Condition.wait()` требует ровно одного захвата; вложенные захваты вызывают `RuntimeError`.
6. **Эксклюзивный режим по умолчанию:**
Прямые операции (например, `with lock:`) используют эксклюзивный прокси `.write`. Это поведение синхронизации, а не граница безопасности; явно выбирайте `.read` или `.write`, когда режим доступа важен.

<br/>

## 📊 Результаты производительности и бенчмарков

Графики ниже показывают сквозные результаты I/O-нагрузок, имитирующих работу с сетью и базой данных. Они сравнивают нагрузку целиком и не измеряют отдельно стоимость захвата блокировки или уведомления.

**🖥️ Тестовая среда:** Все тесты выполнялись на процессоре **Intel Core i7-12700H (2.4GHz)** под управлением **EndeavourOS (Linux на базе Arch)**, с использованием интерпретаторов **Python 3.14.3** и экспериментального **Free-Threading (3.14.3t)**.

**🧪 Методология тестирования:** Рабочие потоки создаются до замера и запускаются барьером/Event. I/O сценарий выполняет 10 итераций с задержкой 1 мс на операцию. Результаты зависят от планировщика, интерпретатора и нагрузки машины; нулевая погрешность не гарантируется.

### 1. Сравнение блокировок чтения-записи (RWLock)

Стандартные блокировки вынуждают потоки выстраиваться в одну очередь, даже если они только читают данные. `rwlocker` открывает одновременный доступ на чтение.

**Производительность синхронного (Thread) RWLock:**
В записанных результатах read-heavy workload совместные читатели завершили работу быстрее, чем при сериализации стандартной эксклюзивной блокировкой (до ~35x в измеренном запуске). Это время выполнения всего workload при разных семантиках блокировок, а не скорость примитива acquire. Результаты write-heavy относятся только к этому workload.
<p align="center">
  <img src="./figures/sync_rwlock.svg" alt="Sync RWLock Benchmark" width="100%"/>
</p>
<br>

**Производительность асинхронного (Asyncio) RWLock:**
В этом benchmark асинхронные задачи выполняются в одном цикле событий. Графики показывают все доступные режимы интерпретатора, а не только лучший результат. Пропускная способность при интенсивном чтении отражает возможность нескольких читателей одновременно ожидать I/O.
<p align="center">
  <img src="./figures/async_rwlock.svg" alt="Async RWLock Benchmark" width="100%"/>
</p>
<br>

### 2. Сравнение условных переменных (RWCondition)

Тесты Condition измеряют пропускную способность всего workload, включая совместное чтение, проверки predicate, планирование и искусственный I/O; они не измеряют отдельно стоимость `notify_all()`. Каждый waiter получает сигнал, поэтому операция имеет сложность O(N).

**Производительность синхронного (Thread) RWCondition:**
Записанный результат ~45x сравнивает весь workload RWCondition с `threading.Condition`, использующим эксклюзивную блокировку; он не означает, что сам вызов `notify_all()` в 45 раз быстрее.
<p align="center">
  <img src="./figures/sync_rwcondition.svg" alt="Sync RWCondition Benchmark" width="100%"/>
</p>
<br>

**Производительность асинхронного (Asyncio) RWCondition:**
Асинхронный результат также сравнивает workload целиком и не измеряет отдельно стоимость уведомления. Цикл событий по-прежнему обрабатывает каждого ожидающего.
<p align="center">
  <img src="./figures/async_rwcondition.svg" alt="Async RWCondition Benchmark" width="100%"/>
</p>
<br>

Тесты охватывают стратегии блокировок, condition, тайм-ауты, реентерабельность и отмену. Успешные тесты полезны для регрессий, но не доказывают корректность при каждом возможном расписании.

<br/>

## 🚀 Начало работы

### 🛠️ Зависимости

* Нет зависимостей во время выполнения.
* Для построения графиков бенчмарков: `pip install rwlocker[benchmark]`.
* Только стандартная библиотека Python (`threading`, `asyncio`, `typing`, `collections`).
* Поддерживаются Python 3.9–3.14; эти версии входят в матрицу CI-тестов.

### 📦 Установка

Библиотека не имеет внешних зависимостей и работает напрямую с базовыми библиотеками Python.

1. Клонировать репозиторий
    ```sh
    git clone https://github.com/TahsinCr/python-rwlocker.git
    ```

2. Установить через PIP
    ```sh
    pip install rwlocker
    ```

<br/>

### 💻 Примеры использования

#### 1. Кэш в памяти с высокой конкурентностью (Read-Heavy)

Позволяет независимым читателям одновременно выполнять работу в веб-серверном сценарии.

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
        # Читатели НИКОГДА не блокируют друг друга, максимизируя пропускную способность!
        with self._lock.read:
            time.sleep(0.01) # Симуляция сети или сериализации (I/O)
            return self._cache.get(key)

    def set(self, key: str, value: Any) -> None:
        # Захватывает эксклюзивную блокировку записи. Безопасно приостанавливает новых читателей.
        with self._lock.write:
            self._cache[key] = value

# ИСПОЛЬЗОВАНИЕ
cache = InMemoryCache()
cache.set("status", "ONLINE")

# Эти 50 потоков могут читать одновременно без ожидания.
threads = [threading.Thread(target=cache.get, args=("status",)) for _ in range(50)]
for t in threads: t.start()

```

#### 2. Атомарное понижение состояния (Downgrading) в финансовых реестрах

Идеально подходит для обновления данных (Write) и немедленного чтения/аудита тех же данных (Read) без возможности вмешательства другого писателя.

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
            # ФАЗА 1: Эксклюзивная запись (Обновление баланса)
            self._balance += amount
            
            # АТОМАРНЫЙ DOWNGRADE: Блокировка записи понижается до блокировки чтения.
            # Ожидающие читатели допускаются, но другие ПИСАТЕЛИ строго блокируются.
            self._lock.write.downgrade()
            
            # ФАЗА 2: Совместное чтение (Трансляция другим сервисам по сети)
            self._dispatch_audit_event(self._balance)
            
        finally:
            # Поскольку мы понизили уровень, теперь мы должны освободить блокировку READ.
            self._lock.read.release()

    def _dispatch_audit_event(self, balance: float):
        print(f"Аудиторский отчет отправлен. Новый баланс: {balance}")

```

#### 3. Обновление токена JWT (Решение проблемы Thundering Herd)

Предотвращает падение сервера авторизации из-за одновременного пробуждения сотен задач для обновления истекшего токена (Thundering Herd).

```python
import asyncio
from rwlocker.async_rwlock import AsyncRWLockWrite

class AuthTokenManager:
    def __init__(self):
        self._lock = AsyncRWLockWrite()
        self._token = "valid_token"
        self._is_expired = False

    async def get_valid_token(self) -> str:
        # Быстрый путь: Если токен действителен, 500 задач проходят здесь одновременно без ожидания.
        async with self._lock.read:
            if not self._is_expired:
                return self._token
                
        # Медленный путь: Срок действия токена истек. Захват блокировки записи.
        async with self._lock.write:
            # Блокировка с двойной проверкой: Пока мы ждали блокировку, 
            # другая задача могла войти и обновить токен.
            if self._is_expired:
                print("Обновление токена...")
                await asyncio.sleep(0.5)  # API запрос
                self._token = "new_valid_token"
                self._is_expired = False
                
            return self._token

```

#### 4. Высокочастотная телеметрия (Справедливое распределение)

Данные поступают от датчика 100 раз в секунду (Write), а 200 веб-сокетов читают эти данные (Read). Архитектура Fair призвана снизить риск голодания, пока владельцы блокировки продолжают работу.

```python
import asyncio
from typing import Dict
from rwlocker.async_rwlock import AsyncRWLockFair

class TelemetryDispatcher:
    def __init__(self):
        # Fair распределяет ожидающих читателей и писателей по фазам, пока владельцы блокировки продолжают работу.
        self._lock = AsyncRWLockFair()
        self._state = {"alt": 0.0, "lat": 0.0, "lon": 0.0}

    async def ingest_sensor_data(self, new_data: Dict[str, float]):
        """Записывает входящие данные из высокочастотного UDP-потока."""
        async with self._lock.write:
            self._state.update(new_data)
            await asyncio.sleep(0.001)

    async def broadcast_to_clients(self):
        """Читает данные параллельно для десятков websocket-клиентов."""
        async with self._lock.read:
            # Безопасно скопировать состояние для минимизации времени удержания блокировки
            current_state = self._state.copy()
            
        # Выполнять медленные сетевые I/O операции, пока блокировка снята
        await self._network_send(current_state)

    async def _network_send(self, data):
        await asyncio.sleep(0.05) # Симуляция сетевой задержки

```

#### 5. Обновление кэша на основе событий (Thundering Herd Protection)

В этом примере condition ожидающие используют очередь; notify_all сигнализирует каждого из них, а время выполнения зависит от планировщика.

```python
import asyncio
from rwlocker.async_rwlock import AsyncRWLockRead, AsyncRWCondition

class GlobalConfigCache:
    def __init__(self):
        # Мы используем блокировку Read-Pref, потому что чтение очень интенсивно
        self._cond = AsyncRWCondition(AsyncRWLockRead())
        self._config = {"theme": "light", "version": 1}
        self._is_refreshing = False

    async def get_config(self) -> dict:
        """Вызывается конкурентными запросами."""
        async with self._cond.read:
            # Если выполняется обновление БД, безопасно спать и ждать, вместо того чтобы бомбардировать БД.
            # Метод wait_for автоматически обрабатывает сценарии ложных пробуждений (Spurious Wakeup).
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


#### 6. Точная очередь заданий (Thread Condition & Targeted Wake-up)

Когда в систему поступают 3 новых задания, вместо пробуждения всех 50 простаивающих рабочих потоков (проблема "Thundering Herd"), выполняется целевое пробуждение вызовом только `notify(n=3)`.

```python
from collections import deque
import threading
from rwlocker.thread_rwlock import RWLockFair, RWCondition

class ImageProcessingQueue:
    def __init__(self):
        # Стратегия Fair для планирования ожидающих производителей и потребителей по фазам
        self._cond = RWCondition(RWLockFair())
        self._queue = deque()

    def add_jobs(self, jobs: list[str]):
        """Производитель (Producer): Добавляет новые задания в очередь."""
        with self._cond.write:
            self._queue.extend(jobs)
            
            # УМНЫЙ СИГНАЛ: Пробудить столько потоков, сколько поступило новых заданий.
            # Остальные спящие потоки в системе не будут тратить такты CPU.
            self._cond.write.notify(n=len(jobs))

    def consume_job(self):
        """Потребитель (Consumer): Спит, пока не появится задание, затем забирает его."""
        with self._cond.write:
            # Безопасно ожидать, если в очереди нет заданий
            self._cond.write.wait_for(lambda: len(self._queue) > 0)
            job = self._queue.popleft()

        # Выполнить тяжелую обработку ПОСЛЕ снятия блокировки.
        print(f"Обработка: {job}")

```

#### 7. Совместимость с интерфейсом блокировки

Прямые методы блокировки перенаправляются на эксклюзивный прокси `.write`. Перед передачей объекта коду, написанному для стандартных блокировок или condition, проверьте сигнатуры и наблюдаемое поведение; режимы `.read` и `.write` выбираются явно.

```python
import threading
from rwlocker.thread_rwlock import RWLockFair, Lock

# Сценарий: Сторонняя функция ожидает стандартный threading.Lock
def third_party_worker(standard_lock: threading.Lock, data: list):
    # Внешняя библиотека не знает о прокси ".write" или ".read".
    # Она напрямую использует "with lock:".
    with standard_lock:
        data.append("Processed")
        print("Блокировка захвачена через стандартный API!")

# МЕТОД 1: Вы можете передать продвинутый объект RWLock напрямую!
# RWLockFair обнаруживает эти вызовы и автоматически переключается в 
# режим .write (эксклюзивный), поскольку это самое безопасное допущение.
advanced_lock = RWLockFair()
third_party_worker(advanced_lock, [])

# МЕТОД 2: Если вам нужно только стандартное поведение блокировки, 
# вы можете использовать стандартные адаптеры с той же сигнатурой.
simple_adapter_lock = Lock()
third_party_worker(simple_adapter_lock, [])
```

*Для дополнительных примеров, пожалуйста, загляните в директорию [examples][examples-url].*

Полный список предлагаемых функций (и известных проблем) смотрите в разделе [открытых проблем (issues)][issues-url].

<br/>

## 🤝 Вклад в проект (Contributing)

Сообщество open-source — это идеальное место для расширения границ таких низкоуровневых высокопроизводительных библиотек. Любой ваш вклад, который сделает `rwlocker` быстрее, безопаснее или функциональнее, очень ценится!

Мы особенно ждем вашего вклада в следующих областях:

* ⚡ **Оптимизация производительности:** Алгоритмические подходы, которые еще больше снизят накладные расходы (overhead).
* 🏗️ **Специфичные для сценариев улучшения:** Создание и разработка вариантов механизмов блокировки, оптимизированных под различные сценарии.
* 🐛 **Тестирование крайних случаев (Edge-Case):** Новые и строгие модульные тесты для обнаружения сценариев взаимных блокировок (deadlock) или голодания (starvation).

Если у вас есть отличная идея или решение, пожалуйста, выполните следующие шаги для создания **Pull Request (PR)**. Вы также можете открыть Issue с тегом "enhancement", чтобы предложить новую функцию.

Не забудьте поставить проекту **Звезду (⭐)** в правом верхнем углу, если он оказался вам полезен. Спасибо за поддержку!

### 🛠️ Шаги для внесения вклада

1. Сделайте **Fork** проекта в свой аккаунт.
2. Создайте свою ветку (Feature Branch):
```sh
git checkout -b feature/AmazingFeature

```


3. Сделайте **Commit** ваших изменений (Старайтесь использовать описательные сообщения):
```sh
git commit -m 'feat: Добавлена новая оптимизация с затратами O(1) для AsyncRWLock'

```


4. Отправьте изменения в ветку (**Push**):
```sh
git push origin feature/AmazingFeature

```


5. Откройте **Pull Request** в этом репозитории.

> ⚠️ **Важное примечание для разработчиков:** Архитектура `rwlocker` крайне чувствительна к сценариям *deadlock*, *прерываниям ОС (OS-Interrupts)* и *реентерабельности*. Перед PR запустите тесты на поддерживаемых версиях Python из CI и проверьте сценарии с разным порядком выполнения потоков и задач.

<br/>

## 🙏 Благодарности и Лицензия

Этот проект полностью с открытым исходным кодом под **лицензией MIT** ([License][license-url]).

Спасибо всему open-source сообществу Python за то, что помогли нам столкнуться с самыми глубокими реалиями Python C-API во время разработки архитектур тестирования и бенчмарков.

* **PyPI:** [RWLocker на PyPI][pypi-project-url]
* **Исходный код:** [Tahsincr/python-rwlocker][project-url]

Если вы найдете какие-либо ошибки или захотите внести архитектурный вклад, не стесняйтесь открыть Issue или отправить Pull Request на GitHub!

<br/>


## 📫 Контакты

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
