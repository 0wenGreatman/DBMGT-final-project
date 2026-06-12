# TASK6.md — Optional Extension Bonus

## Extension Summary

本次 Task 6 延伸功能新增「修改個人資料」功能。使用者登入 TransitFlow 後，可以在右上角點選 `Edit Profile`，查看目前儲存在 PostgreSQL 的電話與出生日期，修改任一欄位後按下 `Save profile` 儲存。儲存成功後，編輯區塊會自動收起，使用者不需要再按 `Cancel`。

此功能屬於 database-backed UI extension，因為它不只是更改畫面樣式，而是新增一個登入後的帳戶管理互動流程，並透過新的資料庫 query function 更新 `user_profiles` 資料表。

本功能沒有修改 `skeleton/agent.py`。使用者透過 Gradio UI 直接操作，不需要經過 LLM tool-calling。

## Files Modified or Added

| File | Status | Task 6 Changes |
|------|--------|----------------|
| `TASK6.md` | Added | 說明 Task 6 延伸功能、修改檔案、function、table、SQL 範例與測試證據。 |
| `databases/relational/schema.sql` | Modified | 在 `user_profiles` 新增資料完整性限制：`chk_email_format`、`chk_phone_format`、`chk_dob_past`。 |
| `databases/relational/queries.py` | Modified | 新增 `update_user_profile()`，負責驗證並更新使用者個人資料。 |
| `skeleton/ui.py` | Modified | 新增 `Edit Profile` 按鈕、Profile panel、欄位變更偵測、儲存流程與成功後自動收起面板。 |

每個 modified file 皆已在檔案前段加入 `# TASK 6 EXTENSION:` 標記，方便 TA 定位延伸功能程式碼。

## Motivation

原本 TransitFlow 已支援登入、註冊、訂票與查詢功能，但登入後使用者無法直接查看或修改自己的聯絡資訊。雖然 `user_profiles` 已保存 `phone` 與 `date_of_birth`，這些資料原本沒有被 UI 清楚呈現，也沒有提供使用者更新的互動方式。

本延伸功能讓使用者可以自行維護個人資料，補足帳戶管理流程，也讓 PostgreSQL 中既有的 profile 欄位能被實際使用。

## Database Changes

本功能沒有新增新的 table。`phone` 與 `date_of_birth` 是使用者個人資料管理所需的基本欄位；Task 6 的資料庫延伸重點是針對 profile 資料新增三個 `CHECK` constraints，讓 email、phone、date of birth 在資料庫層就能維持格式與合理性。

```sql
CREATE TABLE user_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(50) UNIQUE NOT NULL,
    first_name VARCHAR(50) NOT NULL,
    surname VARCHAR(50) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    phone VARCHAR(50) NOT NULL,
    date_of_birth DATE NOT NULL,
    registered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    deleted_at TIMESTAMPTZ,

    -- TASK 6 EXTENSION: Keep account lookup data reliable by rejecting invalid email formats at the database layer.
    CONSTRAINT chk_email_format CHECK (email ~* '^[A-Za-z0-9._+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]+$'),
    -- TASK 6 EXTENSION: Keep UI profile updates consistent with valid phone input before accepting writes.
    CONSTRAINT chk_phone_format CHECK (phone ~ '^[0-9\+\-\(\)\s]{7,20}$'),
    -- TASK 6 EXTENSION: Prevent impossible profile data such as future dates of birth.
    CONSTRAINT chk_dob_past CHECK (date_of_birth <= CURRENT_DATE)
);
```

### Table Used

| Table | Columns Used | Purpose |
|-------|--------------|---------|
| `user_profiles` | `email`, `phone`, `date_of_birth`, `deleted_at` | 用目前登入者 email 找到 profile，並更新可編輯欄位。 |

### Constraints Used

| Constraint | Purpose |
|------------|---------|
| `chk_email_format` | 限制 email 必須符合基本 email 格式，確保登入與 profile lookup 使用的帳號識別值可靠。 |
| `chk_phone_format` | 限制電話只能包含數字、空白、`+`、`-`、括號，長度為 7 到 20 字元，避免 UI 寫入不合理電話格式。 |
| `chk_dob_past` | 限制 `date_of_birth <= CURRENT_DATE`，避免使用者儲存未來出生日期。 |

## New Database Operation

### `databases/relational/queries.py`

#### `update_user_profile(user_email, phone, date_of_birth)`

新增的資料庫操作，用來更新目前登入使用者的個人資料。

具體行為：

- 使用 `user_profiles.email` 找到目前登入使用者。
- 只允許更新 `user_profiles.phone` 與 `user_profiles.date_of_birth`。
- 更新前先檢查使用者是否已登入。
- 更新前先檢查電話格式，與資料庫的 `chk_phone_format` 保持一致。
- 更新前先檢查日期格式必須為 `YYYY-MM-DD`。
- 更新前先檢查出生日期不可晚於今天，與資料庫的 `chk_dob_past` 保持一致。
- 使用 `SELECT ... FOR UPDATE` 鎖定該使用者 row，避免同時儲存造成資料覆蓋。
- 若送出的值與資料庫目前值相同，回傳 `changed=False` 並避免執行不必要的 `UPDATE`。
- 更新成功後回傳最新 profile 欄位，供 UI 同步畫面狀態。

## UI Design Decisions

### `skeleton/ui.py`

新增的 UI functions：

- `open_profile_panel(current_user)`：登入後讀取目前使用者 profile，將 `phone` 與 `date_of_birth` 顯示在輸入欄位中。
- `on_profile_change(phone, date_of_birth, original_profile)`：偵測任一欄位是否有變更；只有資料有變更時才啟用 `Save profile`。
- `save_profile(current_user, phone, date_of_birth, original_profile)`：呼叫 `update_user_profile()` 儲存資料；成功後自動收起 Profile panel。

UI 設計重點：

- `Edit Profile` 按鈕只會在登入後顯示。
- Profile panel 沿用原本 Gradio UI 的簡潔風格，避免破壞既有 login/register/chat layout。
- 使用者一打開 panel 就能看到目前資料庫中的預設值。
- 任一欄位有變更即可儲存。
- 沒有變更時不會執行資料庫更新。
- 更新失敗時 panel 保持開啟，方便使用者修正錯誤。
- 更新成功後 panel 自動收起，流程更直覺。

## Example SQL Queries

### 1. 查看目前使用者個人資料

```sql
SELECT user_id, email, phone, date_of_birth
FROM user_profiles
WHERE email = 'alice.tan@email.com'
  AND deleted_at IS NULL;
```

Expected output:

```text
user_id | email               | phone       | date_of_birth
RU01    | alice.tan@email.com | 07912340101 | 1990-03-14
```

### 2. 更新使用者電話與出生日期

```sql
UPDATE user_profiles
SET phone = '07999998888',
    date_of_birth = '1990-03-14'
WHERE email = 'alice.tan@email.com'
  AND deleted_at IS NULL
RETURNING user_id, email, phone, date_of_birth;
```

Expected output:

```text
user_id | email               | phone       | date_of_birth
RU01    | alice.tan@email.com | 07999998888 | 1990-03-14
```

## Testing Evidence

已執行以下程式檢查：

```bash
python -B -m py_compile skeleton/ui.py databases/relational/queries.py
git diff --check -- skeleton/ui.py databases/relational/queries.py
```

已驗證的功能行為：

- 登入後會顯示 `Edit Profile` 按鈕。
- 點擊 `Edit Profile` 後會載入目前使用者的 `phone` 與 `date_of_birth`。
- 修改 `phone` 後可以儲存。
- 修改 `date_of_birth` 後可以儲存。
- 任一欄位有變更時，`Save profile` 才會啟用。
- 沒有變更時不執行資料庫更新，回傳 `changed=False`。
- 錯誤電話格式會被拒絕。
- 錯誤日期格式會被拒絕。
- 未來日期會被拒絕。
- 儲存成功後 Profile panel 會自動收起。
- 登出後 Profile panel 會被隱藏。
- 原本 login、register、forgot password、chat flow 不受影響。

## Notes for TA Review

- Extension marker：每個 modified file 前段皆有 `# TASK 6 EXTENSION:`。
- Database table：`user_profiles`
- Schema constraints：`chk_email_format`、`chk_phone_format`、`chk_dob_past`
- New database function：`update_user_profile()`
- UI functions：`open_profile_panel()`、`on_profile_change()`、`save_profile()`
- Modified files：`databases/relational/schema.sql`、`databases/relational/queries.py`、`skeleton/ui.py`
- Added file：`TASK6.md`
