# Báo cáo cá nhân — Phạm Trần Thanh Lâm

**Họ và tên:** Phạm Trần Thanh Lâm  
**Vai trò:** Monitoring / Docs Owner  
**Độ dài:** ~500 từ 

---

## 1. Phụ trách

Dưới vai trò Monitoring / Docs Owner của nhóm, mình chịu trách nhiệm chính ở 2 mảng là hệ thống giám sát tính tươi của dữ liệu (Data Freshness) và hệ thống tài liệu quy trình (Documentation). 

Cụ thể, mình đã tiến hành code trực tiếp file scripts `monitoring/freshness_check.py` để đánh giá SLA. Ở mảng tài liệu, mình phụ trách triển khai các chuẩn hợp đồng dữ liệu tại `docs/data_contract.md`, cẩm nang xử lý sự cố `docs/runbook.md`, form đánh giá `quality_report_template.md` và chịu trách nhiệm chính thống nhất file `reports/group_report.md`. Mình cũng phối hợp chặt chẽ cùng bạn Embed Owner thông qua manifest report và tệp `cleaned_csv` để đảm bảo vector db luôn nạp đúng bản dữ liệu mới nhất.

**Bằng chứng:** Các commit liên quan đến docs và `freshness_check.py` trong repo, bao gồm commit `387ecd3` (feat: add lab 10 processing artifacts).

---

## 2. Quyết định kỹ thuật: Giám sát Freshness & Tối ưu Alerting

- **Monitoring Freshness SLA:** Thay vì để tính năng check freshness làm sụp đổ toàn bộ đường ống dẫn dữ liệu (halt pipeline) mỗi khi dữ liệu đến trễ, mình quyết định thiết lập SLA theo ngưỡng mềm (24 giờ). Hệ thống sẽ phân giải format ISO từ `latest_exported_at` hoặc `run_timestamp` trong tệp Manifest JSON và đối chiếu với thời gian UTC hiện tại (`now()`). 
    - Nếu quá 24h, sẽ emit cảnh báo `FAIL` để team Data Engineer nhận biết độ trễ. 
    - Nếu data source thiếu hoàn toàn metadata về thời gian, mình quyết định để script trả về `WARN`. Quyết định này giúp quy trình ETL không bị gián đoạn (chống crash) mà vẫn để lại vết log cho team điều tra nguyên nhân.
- **Data Documentation:** Trong báo cáo nhóm, mình chủ động lưu lại các trường hợp kịch bản cố tình "thử nghiệm nhúng dữ liệu lỗi" (`inject-bad`) của team để làm bằng chứng cho hệ quả của việc không dọn dẹp Document.

---

## 3. Sự cố / Anomaly: Trục trặc Extract Metadata mất thời gian

**Phát hiện và Fix:** 
Trong một số lần xuất file thử nghiệm `inject-bad`, mình nhận ra dữ liệu upstream hoàn toàn không đính kèm cột thời gian `exported_at`, làm chuỗi text trở thành chuỗi rỗng. Nếu cứ đưa thẳng chuỗi này vào hàm parse datetime của Python (`datetime.fromisoformat`), chương trình sẽ văng warning runtime error và làm pipeline sập ngay tại bước 5 (Manifest & Freshness).

Để khắc phục, mình đã bọc hàm an toàn `parse_iso(str(ts_raw))` để đón bắt lỗi (catch error) này, ép script trả về state an toàn `WARN` kèm theo chi tiết dict báo hiệu gãy logic: `{"reason": "no_timestamp_in_manifest"}` giúp Ingestion Owner đối chiếu lỗi. Ngoài ra, việc log chi tiết biến số `age_hours` vào tệp manifest hỗ trợ đội ngũ dễ dàng đối chiếu lượng thời gian bị trôi qua trước khi quá hạn SLA.

---

## 4. Bằng chứng Before/After

Sự hiển hiện của hệ thống Monitoring và Manifest Pipeline:
- **Manifest Audit:** Giờ đây ở file `manifests/manifest_*.json`, phần `"quarantine_reasons"` đã giúp mình log đầy đủ `"missing_effective_date": 1` và `"chunk_too_long": 1` qua đó chứng minh quá trình kiểm thử Data Quality đang hoạt động rất tốt (thay vì chỉ log text khó search như trước đây).
- **Quality Alert:** Khi chạy lệnh test inject (với flag bypass kiểm tra chất lượng):
    - *Trước đó:* File pipeline fail và không ghi đè vào Chroma, file CSV (`eval/before_after_eval.csv`) cũng không có kết quả dơ để kiểm thử.
    - *Sau đó:* Với bộ test Bypass có chủ đích, query truy xuất `hits_forbidden=yes` cho vấn đề hoàn tiền 14 ngày đã lên. Việc này giúp việc báo cáo lại rủi ro trong tài liệu minh bạch và sinh động hơn hẳn!

---

## 5. Cải tiến nếu có thêm 2 giờ

- **Xây dựng Alerting qua Webhook:** Mình sẽ code bổ sung module gọi webhook để bắn trực tiếp cảnh báo `{"status": "FAIL"}` từ `freshness_check.py` sang kênh MS Teams hoặc Slack của team Data Ops thay vì phải mở file log mỗi ngày.
- **Tự động đo thời gian Extract:** Thay vì chờ file CSV cung cấp cột `exported_at` (có nguy cơ bị giả mạo), mình sẽ lấy thời khắc file CDC từ Database đổ vào Data Lake bằng cách móc vào metadata storage hay API bên ngoài để quy trình chống giả mạo timestamp.
