-- Migration v2: 使用者群組權限綁定 + 對話記錄持久化
-- 在已存在的資料庫上執行此腳本

-- =============================================
-- 5. 使用者群組權限對應表
-- =============================================
CREATE TABLE user_group_permissions (
    id       INT IDENTITY(1,1) PRIMARY KEY,
    user_id  INT NOT NULL REFERENCES users(id)           ON DELETE CASCADE,
    group_id INT NOT NULL REFERENCES document_groups(id) ON DELETE CASCADE,
    CONSTRAINT uq_user_group UNIQUE (user_id, group_id)
);

CREATE INDEX idx_ugp_user  ON user_group_permissions(user_id);
CREATE INDEX idx_ugp_group ON user_group_permissions(group_id);

-- =============================================
-- 6. 對話記錄持久化
-- =============================================
CREATE TABLE chat_history (
    id         INT IDENTITY(1,1) PRIMARY KEY,
    user_id    INT           NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    username   NVARCHAR(100) NOT NULL,
    question   NVARCHAR(MAX) NOT NULL,
    answer     NVARCHAR(MAX) NOT NULL,
    group_ids  NVARCHAR(500) NOT NULL DEFAULT '',   -- 逗號分隔的 group_id 清單
    created_at DATETIME      NOT NULL DEFAULT GETDATE()
);

CREATE INDEX idx_chat_history_user    ON chat_history(user_id);
CREATE INDEX idx_chat_history_created ON chat_history(created_at);
