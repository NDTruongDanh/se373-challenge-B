## **Memory, Context Engineering & Prompt Caching**

MSc. Ngô Ngọc Đăng Khoa

1

> 01 Problems

## MEMORY, CONTEXT & CACHING AGENDA

- 02 Persistent memory

- 03 Compaction và Code Mode
  - Prompt caching và model switching

04

## **<mark>Problems</mark>**

Remember: điều gì phải còn khi sang session mới?

1

Manage: context chứa gì Reuse: phần tính toán nào sau hàng trăm tool call? dùng lại được qua hàng trăm LLM call?

2

3

3

## **Từ đế agent loop n agent harness**

Agent loop là lõi điều phối; harness là hệ thống vận hành xung quanh lõi đó.

4

## **M** **<mark>t tình huố</mark> ề** **<mark>ộ</mark> ng kéo dài nhi u ngày**

☕ Ngày 1: thống nhất stack PostgreSQL, TypeScript và quy ước API

☕ Ngày 2: sửa authentication, thử ba cách, hai cách thất bại

☕ Ngày 3: user yêu cầu tiếp tục trên một session mới

☕ Hàng trăm file và log đã được đọc trong quá trình làm

Là người xây dựng harness, bạn giữ lại gì và đưa gì vào LLM?

5

PHẦN I

**Persistent memory**

Memory không phải một transcript chat vô hạn.

## **LLM: stateless, agent: stateful**

Một lần gọi API chỉ thấy dữ liệu của request hiện tại.

☕ Harness quyết định lưu thông tin nào ☕ Harness quyết định truy xuất thông tin nào ☕ Harness quyết định đưa lại gì vào request kế tiếp

7

Trả lời câu hỏi Thành phần Ví dụ State Đang làm đến đâu? current_step=run_tests History Đã có tương tác gì? User và tool messages Memory Điều gì cần nhớ? Project dùng PostgreSQL Context LLM thấy gì lúc này? Rules, memory đã chọn và task Memory được lưu trên ổ đĩa không tự nhiên xuất hiện trong context: cần bước retrieval và injection .

8

## **<mark>Phân loạ</mark> i memory**

Session memory: mục tiêu, tiến độ, lỗi chưa xử lý, bước kế tiếp

Persistent memory: sở thích user, quy ước project, quyết định, bài học

Instructions và policies: rules bắt buộc, có phạm vi và độ ưu tiên riêng

Không phải dòng chat nào cũng là memory.

9

## **Case study: AGENTS.md và MEMORY.md**

File

project/AGENTS.md ~/.claude/AGENTS.md

MEMORY.md

Vai trò

Quy ước project Hướng dẫn theo user

Index ngắn

Index nhỏ luôn được nạp; chi tiết chỉ nạp khi cần.

Nhồi tất cả memory mỗi lượt: contextbloatquay lại

memory/auth.md memory/preferences.md

Chi tiết authentication

Sở thích lập trình

10

## **Memory lifecycle**

Memory cần chính sách ghi, đọc, sửa và quên.

<!-- Start of picture text -->

use J Decide<br>Ohare<br>=<br>Retrieve Write<br>f NY<br>ca{8+ © @@.<br>pote | Update Forget Expire 3<br><!-- End of picture text -->

11

## **Memory sai và l** **<mark>ỗi thờ</mark> i**

Memory cần giải quyết xung đột, không chỉ append.

### Hai session

### Lựa chọn nào hợp lý?

- ☕ Session 1: "Authentication sử dụng JWT."
  - ☕ Giữ cả hai như quy định hiện hành

  - ☕ Xóa hoàn toàn dấu vết JWT

- ☕ Session 2: "Chuyển sang session cookie."

- ☕ Đánh dấu JWT đãbịthay thế, lưu nguồn và thời điểm

12

## **Memory curation**

Mẫu kiến trúc

Markdown instructions

Memory tools

Progressive disclosure File-system, searchable memory

Out-of-band curation

Đặc điểm Đơn giản, dễ bắt đầu

Agent quyết định lúc nào đọc, ghi

Đọc index trước, load chi tiết sau

Tổ chức và truy xuất linh hoạt

Phân tích nhiều session để cập nhật memory

13

## **Challenge A: persistent memory**

Mục tiêu: agent nhớ được quy ước dự án qua nhiều session, và cập nhật khi quy ước thay đổi.

☕ Có thể dùng lại agent đã có

- ☕ Chứng minh 1: session mới vẫn dùng đúng quy ước đã thống nhất

☕ Chứng minh 2: quy ước đổi thì các session sau dùng quy ước mới

Timebox: 30 phút.

14

## **Challenge A: persistent memory Gợi ý**

- ☕ Lưu ở đâu: file Markdown, JSON hay SQLite là đủ?

- ☕ Ai ghi: agent tự gọi tool ghi memory, hay harness tự trích từ hội thoại?

- ☕ Khi nào nạp: memory vào context lúc mở session hay khi cần mới tìm?

- ☕ Khi quy ước đổi: xem lại slide Memory sai và lỗi thời

- ☕ Kiểm chứng: in ra phần memory đã được inject vào context

15

## **<mark>So sánh thiết kế memory</mark>**

| Thiết kế             | Điểm mạnh           | Đổi lại                                |
| -------------------- | ------------------- | -------------------------------------- |
| JSON, Markdown       | Dễ làm, dễ kiểm tra | Khó tìm kiếm và xử lý xung đột khi lớn |
| SQLite và metadata   | Truy vấn, update rõ | Cần schema và migration                |
| Vector retrieval     | Tìm theo ngữ nghĩa  | Chi phí embedding, false matches       |
| Index và topic files | Lazy load, dễ đọc   | Phải giữ index chính xác               |

16

### PHẦN II

# **Giữ context nhỏ n gọ**

## **<mark>Context window</mark>**

Context window là working set, không phải kho dữ liệu vô hạn.

- ☕ Gồm instructions, memory đã chọn, history, tool results, dữ liệu retrieve

- ☕ Phải chừa chỗ cho output của model

- ☕ Nhiều dữ liệu hơn khôngđồng nghĩa quyết định tốt hơn

18

## **Tool-output bloat**

Raw output có thể được archive, không cần nằm mãi trong active context.

Raw output đã nhận

Agent thực sự cần

- ☕ read_file : 2.000 dòng
  - ☕ 3 test đang lỗi

- ☕ run_tests : 7.000 dòng
  - ☕ Nguyên nhân khả dĩ

- ☕ grep : 1.500 dòng, cộng log

- retry lặp lại

- ☕ Các file liên quan

- ☕ Thử nghiệm kế tiếp

19

## **Compaction**

☕ Mục tiêu khôngphảikể lại mọi điều đã xảy ra ☕ Mục tiêu là thu thập đủ thông tin cho hành động tiếp theo ☕ Agent phải tiếp tục công việc một cách chính xác

Compaction là checkpoint, không phải bản recap của chat.

20

## **Compaction toolbox**

| Kỹ thuật              | Cách làm                       | Rủi ro                  |
| --------------------- | ------------------------------ | ----------------------- |
| Truncation            | Bỏ messages cũ                 | Mất ràng buộc           |
| Tool-output pruning   | Loại log thô hoặc trùng lặp    | Bỏ sót bằng chứng       |
| Summary               | LLM rút gọn history            | Hallucinate, bỏ sót     |
| Structured checkpoint | Lưu state theo schema          | Thiếu trường quan trọng |
| Incremental summary   | Nén từng giai đoạn             | Lỗi tích lũy            |
| Selective keep/drop   | Giữ nguyên các đoạn quan trọng | Chọn nhầm đoạn          |

21

## **Structured checkpoint**

goal: Fix refresh-token race condition current_state: handler implemented; test failing constraints: keep API backward compatible findings:

- failure occurs during concurrent refresh failed_attempts: - increasing token TTL did not help files: [auth.ts, session.ts, auth.test.ts] next_action: inspect locking around refresh

☕ Kiểm chứng checkpoint bằng cách cho agent tiếp tục task khác

22

## **Selective compaction**

Phần nào cần giữ trong context window KEEP: quyết định thiết kế, TRUNCATE: output test lỗi chưa giải quyết, yêu dài rút còn vài dòng lỗi cầu bắt buộc chính

2

1

DROP: log trùng, thử nghiệm thất bại đã kết luận, dữ liệu dễ tái tạo 3

23

## **Jev và System One Model**

Giữ chính xác khi cần; nén khi có thể; loại khi an toàn.

24

## **<mark>Thờ</mark> i đi** **<mark>ể m compact</mark>**

Context utilization vượt ngưỡng an toàn Tool outputs và history lặp lại quá nhiều Kết thúc một milestone, cần checkpoint

Trước khi cold-start lại một context rất lớn

Không đợi context đầy hẳn rồi mới compact.

25

## **Compaction pipeline**

Compaction có thể xem như một controlled reboot của working context.

<!-- Start of picture text -->

CA» Gs”| ed .(2,<br>Observe Prune Build Reinject Resume and<br>token budget redundant structured rules / skills / validate next<br>tool output checkpoint plan action<br><!-- End of picture text -->

26

Code Mode

## **<mark>Code Mode</mark>**

1

Viết: Model trả tool call run_code kèm chương trình.

2

Chạy: Runtime chạy chương trình, chương trình gọi tools.

3

Nhận: Model chỉ nhận kết quả đã xử lý.

28

## **Native tool calling và Code Mode**

Các tool vẫn giữ nguyên; điểm khác là chương trình quyết định chuỗi lời gọi tool thay cho LLM.

Native tool calling Code Mode LLM trả tool call read_file LLM trả tool call run_code Tool output trả về LLM Code nhận tool output LLM yêu cầu file tiếp theo Code tự lặp và aggregate LLM xử lý raw results LLM nhận findings

29

## **<mark>Ví d Code Mode ụ</mark>**

const files = await tools.list_files("src/\*_/_.ts"); const hits = []; for (const path of files) { const content = await tools.read_file(path); const count = (content.match(/TODO/g) ?? []).length; if (count) hits.push({ path, count });

} return hits.sort((a, b) ?> b.count - a.count).slice(0, 5);

☕ 100 file được đọc trong runtime, chỉ 5 findings đi vào LLM ☕ tools.\* là SDK minh họa; LLM biết API qua tài liệu hoặc discovery

30

## **<mark>Runtime của Code Mode</mark>**

Chạy code trong runtime riêng chưaphảisandbox bảo mật; vẫn phải giới hạn quyền truy cập.

☕ Production: sandbox, permission check, timeout, resource limit

31

## **Challenge B: context management**

Mục tiêu: giữ context nhỏ gọn mà agent vẫn làm đúng việc.

Timebox: 30 phút, 15 phút mỗi bài.

- B1: Compact

### B2: Code Mode

- ☕ Session dài được compact

- ☕ Agent vẫn nhớ lỗi đang điều tra, cách đã thử, bước tiếp

- ☕ Agent trả lời câu hỏi trên nhiều file log

- ☕ Raw log khôngđi vào context

32

## **Challenge B: context management**

### **Gợi ý**

### B1: Compact

- B2: Code Mode

- ☕ Tạo session dài có log lớn để thử
  - ☕ Có tool chạy lệnh: code chạy ở đâu?

- ☕ Khi nào kích hoạt compact?
  - ☕ Script chỉ in kết quả cuối

- ☕ Giữ gì, bỏ gì: xem Selective compaction

- ☕ Đo input tokens qua usage

33

## **Compaction và Code Mode**

| Hai kỹ thu | ật bổ sung cho nhau, không đối | lập.                       |
| ---------- | ------------------------------ | -------------------------- |
| Tiêu chí   | Compaction                     | Code Mode                  |
| Thời điểm  | Sau khi dữ liệu tích lũy       | Khi chạy tools             |
| Mục tiêu   | Rút gọn working context        | Tránh intermediate outputs |
| Rủi ro     | Mất state, constraints         | Code lỗi, quyền truy cập   |
| Kết hợp    | Checkpoint cho long session    | Giảm tốc độ context growth |

34

PHẦN III

# **Prompt caching và model switching**

## **Prompt caching và response caching**

Prompt caching khôngphảiresponse caching.

Response cache: trả lại answer cũ gặp lại câu hỏi cũ

Prompt cache: dùng lại tính toán của input khi prefix trùng khớp

36

## **<mark>KV cache</mark>**

Cached tokens vẫn nằm trong input context; chỉ rẻ và nhanh hơn khi cache hit.

37

## **ă Input cost t ng theo history**

| Lượt gọi<br>Input tokens |
| ------------------------ |
| Turn 1<br>51k            |
| Turn 2<br>55k            |
| Turn 3<br>59k            |
| Turn 10<br>87k           |

Input mỗi request tăng ; tổng input qua . request tăng ☕ Giả định: mỗi turn thêm lượng history gần nhưcốđịnh

38

## **<mark>Prefix cache invalidation</mark>**

Thay đổi rất sớm trong prefix có thể làm mất reuse cache ở phần phía sau.

<!-- Start of picture text -->

Y/ GooD )= > Be BAD )<<br>Stable@ sta|Ze@ . newEB . © ? |e | £ =,<br>system tools history request time= 20:14 ci ate cre history<br>@ |Z ) © ||] eE<br>systemstable stabletools history; requestnew time=20:15; : Sie eave history<br>39<br><!-- End of picture text -->

## **Thói quen thân thi** **<mark>ện với cache</mark>**

☕ Static prefix, dynamic suffix

- ☕ Giữ tool definitions ổn định khi có thể

- ☕ Ưu tiên append-only history trong giai đoạn cần reuse ☕ Đo cached_tokens , cache write và cache read, khôngđoán

40

## **Warm cache, cold cache và TTL**

Warm: prefix có khả năng còn được tái sử dụng

Cold: prefix không còn được tái sử dụng theo chính sách hiện hành

TTL: thời hạn hoặc điều kiện provider duy trì cache

Không có TTL hay chính sách write/read chung cho mọi model.

41

## **Keep cache warm**

Keep-alive request vẫn tính phí, và không chắc gia hạn được toàn bộ cache.

42

## **Compaction và cache prefix**

Compaction có thể phá cache prefix.

- ☕ Option 1: giữ history 50k cached tokens

- ☕ Option 2: compact còn 12k tokens, nhưng prefix thay đổi

- ☕ Request kế tiếp: phương án nào rẻ hơn?

- ☕ Tính cả cache read/write, compaction call, output và các lượt sau

43

## **ản đ** **<mark>ầu tư</mark> Cache warming là kho**

☕ Chi phí keep-alive xảy ra ngay bâygiờ

- ☕ Lợi ích chỉ có nếu có request sau và cache reuse thành công

☕ Câu hỏi: expected benefit có lớn hơn keep-alive cost?

Cache warming là đầu tư cho reuse trong tương lai.

44

## **Công thức expected savings**

☕ Cộng thêm: phí cache write, output, TTL policy, latency, quality

45

## **Warm-cache affinity và model flexibility**

So sánh model bằng tổng chi phí để đạt cùng chất lượng, không chỉ bằng giá trên bảng giá.

### Model A

### Model B

- ☕ Đắt hơn
  - ☕ Rẻ hơn

- ☕ Đang có 50k cached tokens

- ☕ Chưa có cache cho context này

- ☕ Đổi sang B phải prefill lại toàn bộ context

46

## **<mark>Ba chiến lư</mark> c ợ**

| Chọn chiến lược có c | hi phí kỳ vọng thấp nhất, miễn | đạt chất lượng và độ trễ.  |
| -------------------- | ------------------------------ | -------------------------- |
| Strategy             | Việc thực hiện                 | Đổi lại                    |
| A: Warm A            | Keep-alive, dùng lại prefix A  | Phí keep-alive             |
| B: Cold và Compact   | Compact rồi dùng A hoặc B      | Phí compact, mất thông tin |
| C: Switch B          | Đổi model, prefill lại từ đầu  | Chất lượng của B           |

47

## **Dữ liệu mô ph** **<mark>ỏng</mark>**

| USD / 1M tokens        | Model A | Model B |
| ---------------------- | ------- | ------- |
| Input                  | 5.00    | 1.00    |
| Cached input           | 0.50    | 0.10    |
| Output                 | 20.00   | 5.00    |
| Cached prefix hiện tại | 50k     | 0       |

Next request: 2k input mới và 1k output

48

## **<mark>Tính thử m ột request</mark>**

Chưa tính phí keep-alive, compaction, retry hoặc latency.

: keep-alive phải rẻ hơn mức này mới có lời cho một lượt.

A: warm, cache hit

### B: cold

49

## **Challenge C: cache-aware model router**

Mục tiêu: chọn warm, compact hoặc switch cho request kế tiếp với chi phí kỳ vọng thấp nhất.

- ☕ Dùng bảng giá ở slide Dữ liệu mô phỏng, khôngcần gọi API

- ☕ Kịch bản: user quay lại sau 3 phút, sau 7 phút, 60% quay lại trong 10 phút

- ☕ Chứng minh: quyết định cho từng kịch bản và khi nào quyết định đổi

Timebox: 30 phút.

50

## **Challenge C: cache-aware model router**

### **Gợi ý**

- ☕ Viết chi phí kỳ vọng của từng chiến lược theo các tham số

- ☕ Thời gian chờ vượt TTL: cần bao nhiêu lần keep-alive?

- ☕ Bắt đầu từ slide Tính thử một request: đã có chi phí A warm, B cold

- ☕ Đổi xác suất quay lại và retry rate để tìm điểm đổi quyết định

51

## **Q & A**

52
