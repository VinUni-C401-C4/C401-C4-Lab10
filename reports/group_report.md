# Báo Cáo Nhóm — Lab Day 10: Data Pipeline & Data Observability

**Tên nhóm:** Antigravity Team
**Thành viên:**
| Tên | Vai trò (Day 10) | Email |
|-----|------------------|-------|
| Phạm Hữu Hoàng Hiệp | Ingestion / Raw Owner | 2A202600415 |
| Đặng Tiến Dũng | Cleaning & Quality Owner | 2A202600024 |
| Phạm Việt Cường | Embed & Idempotency Owner | 2A202600420 |
| Phạm Trần Thanh Lâm | Monitoring / Docs Owner | 2A202600270 |

**Ngày nộp:** 15/04/2026
**Repo:** C401-C4-Lab10
**Độ dài khuyến nghị:** 600–1000 từ

---

> **Nộp tại:** `reports/group_report.md`  
> **Deadline commit:** xem `SCORING.md` (code/trace sớm; report có thể muộn hơn nếu được phép).  
> Phải có **run_id**, **đường dẫn artifact**, và **bằng chứng before/after** (CSV eval hoặc screenshot).

---

## 1. Pipeline tổng quan (150–200 từ)

> Nguồn raw là gì (CSV mẫu / export thật)? Chuỗi lệnh chạy end-to-end? `run_id` lấy ở đâu trong log?

**Tóm tắt luồng:**

Nguồn raw là file CSV xuất từ hệ thống catalog nội bộ (`data/raw/policy_export_dirty.csv`), chứa các bản ghi văn bản lỗi, nhiễu và cả những thông tin chính sách bị cũ. 
Pipeline chạy qua 5 bước chính: 
1. **Ingest**: Nạp dữ liệu thô.
2. **Clean**: Làm sạch, sửa đổi nội dung và cách ly (quarantine) các dòng lỗi (ví dụ như vi phạm allowlist, quá dài, lỗi date).
3. **Validate**: Chạy bộ test Data Expectations, đưa ra mức cảnh báo `warn` hay dừng `halt`.
4. **Embed**: Gọi SentenceTransformers nhúng dữ liệu đã sạch, upsert vào cơ sở dữ liệu vector ChromaDB và loại bỏ (prune) các bản ghi cũ.
5. **Manifest**: Xuất manifest file chứa metadata chạy và kiểm tra tính tươi (freshness) SLA.
Tham số `run_id` được tự động tạo từ timestamp UTC hoặc do ta đưa vào thông qua `--run-id`. Chuỗi này dùng cho các thư mục snapshot và có thể lấy ở những dòng đầu tiên của file log (VD: `run_id=2026-04-15T09-47Z` nằm trong thư mục `artifacts/logs/run_*.log`).

**Lệnh chạy một dòng (copy từ README thực tế của nhóm):**

`python etl_pipeline.py run` (chạy bình thường trơn tru) hoặc để bypass debug:
`python etl_pipeline.py run --run-id inject-bad --no-refund-fix --skip-validate`

---

## 2. Cleaning & expectation (150–200 từ)

> Baseline đã có nhiều rule (allowlist, ngày ISO, HR stale, refund, dedupe…). Nhóm thêm **≥3 rule mới** + **≥2 expectation mới**. Khai báo expectation nào **halt**.

### 2a. Bảng metric_impact (bắt buộc — chống trivial)

| Rule / Expectation mới (tên ngắn) | Trước (số liệu) | Sau / khi inject (số liệu) | Chứng cứ (log / CSV / commit) |
|-----------------------------------|------------------|-----------------------------|-------------------------------|
| Quarantine chunks quá 200 ký tự | Pass vào Db | 1 dòng bị cách ly do vượt ký tự | log: `quarantine_reason[chunk_too_long]=1` |
| Fix chính sách thai sản cũ (18->6) | Bị giữ nguyên policy sai | Được override ghi đè thành 6 tháng | Code: rule fix `stale_leave_policy` |
| Exp: hr_leave_no_stale_10d_annual | - | 0 violations (severity: halt) | log: `expectation[hr_leave_no_stale_10d_annual] OK` |
| Exp: chunk_min_length_8 | - | 0 short_chunks (severity: warn) | log: `expectation[chunk_min_length_8] OK` |

**Rule chính (baseline + mở rộng):**

- Nhóm duy trì baseline và mở rộng tính năng sửa văn bản tĩnh: nếu gặp điều kiện chính sách thai sản (leave_policy) bị lạc hậu ghi là "18 tháng", hệ thống sẽ regex / format lại về "6 tháng". 
- Bổ sung quy tắc phòng thủ để cách ly rác văn bản (chunk vượt quá chiều dài `_MAX_CHUNK_LEN`). 
- Xóa bỏ document out-of-date khỏi Vector Database dựa theo `effective_date`.

**Ví dụ 1 lần expectation fail (nếu có) và cách xử lý:**

Khi expectation thiết lập phát hiện thông tin refund cũ ("14 ngày làm việc") thì sẽ trigger cảnh báo với severity `halt` (dừng quá trình). Trong trường hợp tắt cờ auto-fix `--no-refund-fix`, pipeline sẽ ngừng hoạt động, không cập nhật lên ChromaDB và cảnh báo Data Quality rớt thê thảm (`violations=1`). Để xử lý chúng, nhóm đưa rule thay thế văn bản `14 ngày làm việc` thành `7 ngày làm việc` vào lớp Clean, giúp expectation vượt qua an toàn trên data sạch.

---

## 3. Before / after ảnh hưởng retrieval hoặc agent (200–250 từ)

> Bắt buộc: inject corruption (Sprint 3) — mô tả + dẫn `artifacts/eval/…` hoặc log.

**Kịch bản inject:**

Để mô phỏng hậu quả của dữ liệu sai lệch, nhóm can thiệp trực tiếp với các flag chạy tắt: `python etl_pipeline.py run --run-id inject-bad --no-refund-fix --skip-validate`. Thao tác đó ngăn chặn sửa điều kiện "14 ngày" và cố tình vi phạm `run_expectations` để nhúng thẳng file bẩn vào ChromaDB. Kết quả là Retrieval Agent query sẽ kéo nhầm chính sách lỗi. 
Khi chạy công cụ test lấy Top-K từ vector DB (`eval_retrieval.py --out artifacts/eval/eval_sprint3_before_inject.csv`), field `hits_forbidden` đối với query `q_refund_window` đã cho ra output là `yes` - nghĩa là bot đã khuyên cho phép hoàn tiền trong vòng 14 ngày. Hệ thống tư vấn sai hoàn toàn so với công ty yêu cầu.

**Kết quả định lượng (từ CSV / bảng):**

Khi sửa file và xoá bỏ cờ inject, dữ liệu rác (14 ngày lỗi thời) được Clean và loại bỏ khỏi CSDL Vector:
- `eval_sprint3_after_fix.csv` (Khỏe mạnh): Đối với query hoàn tiền, agent phản hồi với preview hợp lí (`contains_expected=yes`), và cột `hits_forbidden` trở thành `no`. 
- Data pipeline được bảo vệ, Idempotency Database phát huy năng lực prune, thanh tẩy đi vector dơ.

---

## 4. Freshness & monitoring (100–150 từ)

> SLA bạn chọn, ý nghĩa PASS/WARN/FAIL trên manifest mẫu.

SLA mặc định của nhóm là **24 giờ** kể từ lúc làm tươi hệ thống (Data source export timestamp).
Ý nghĩa báo hiệu cho Data Observability dựa trên log chạy freshness:
- **PASS**: Manifest có trường `latest_exported_at` hợp quy định ISO và chưa quá 24 tiếng. Nguồn dữ liệu mới mẻ, RAG cung cấp câu trả lời uy tín.
- **WARN**: Dòng timestamp nạp lên bị trống hoặc lỗi logic dị biệt (`invalid-date`). Không nghiêm trọng đủ để sập quy trình, nhưng cần developer xem lại Data Extractor phía upstream.
- **FAIL**: File manifest quá cũ - ngày export nhỏ hơn rất nhiều so với thời gian hiện tại - SLA Fail. Dữ liệu đã chết, cần báo ngay lập tức vào slack engineer để tìm nguyên do tại sao job ingestion không chạy.

---

## 5. Liên hệ Day 09 (50–100 từ)

> Dữ liệu sau embed có phục vụ lại multi-agent Day 09 không? Nếu có, mô tả tích hợp; nếu không, giải thích vì sao tách collection.

Chắc chắn có. Dữ liệu Vector ở lab này (Data Platform / Ingestion) nhắm trực tiếp đến collection `day10_kb` dùng cho Agent ở Day 09. Các tác vụ Clean & Rule chặn dữ liệu Stale (như nghỉ thai sản cũ, refund cũ) đóng vai trò lá chắn, giúp Retriever Agent Day 09 không phải tốn sức filter, và loại bỏ hoàn toàn rủi ro RAG LLM Halucination thông tin chính sách, bảo vệ trực tiếp trải nghiệm người hỏi.

---

## 6. Rủi ro còn lại & việc chưa làm

- Lớp Validate hiện tại là script custom tay. Trong điều kiện Production lớn, cần thay bằng Deequ hoặc dbt expectations để mở rộng nhanh hàng trăm luật với template.
- Script đang ingest bằng cách chạy thủ công `csv`. Cần Setup Apache Airflow/Prefect cho quy trình Automation định kỳ vào 0:00 hằng ngày và thông báo lỗi thẳng lên Slack Channel.
- Kiểm tra tính fresh chưa gắt gao. Cần triển khai các Metrics giám sát drift model và đẩy thẳng logging vào Grafana.
