-- Local LLM Notebook - SQL Server Schema
-- 執行環境：SQL Server (LocalDB / SQLEXPRESS)
-- 建立資料庫後，在該資料庫下執行此腳本

-- =============================================
-- 1. 文件群組
-- =============================================
CREATE TABLE document_groups (
    id          INT IDENTITY(1,1) PRIMARY KEY,
    name        NVARCHAR(100)  NOT NULL,
    description NVARCHAR(500)  NOT NULL DEFAULT ''
);

-- =============================================
-- 2. 使用者
-- =============================================
CREATE TABLE users (
    id       INT IDENTITY(1,1) PRIMARY KEY,
    username NVARCHAR(100) NOT NULL UNIQUE,
    password NVARCHAR(300) NOT NULL,          -- pbkdf2:sha256:{32-char salt}:{64-char hex key} ≈ 111 chars
    role     NVARCHAR(20)  NOT NULL DEFAULT 'user'  -- 'admin' | 'user'
);

-- =============================================
-- 3. 文件主檔
-- =============================================
CREATE TABLE documents (
    id        INT IDENTITY(1,1) PRIMARY KEY,
    title     NVARCHAR(300)  NOT NULL,
    filename  NVARCHAR(300)  NOT NULL,
    content   NVARCHAR(MAX)  NOT NULL,        -- 原始全文
    group_id  INT            NOT NULL REFERENCES document_groups(id),
    file_hash NVARCHAR(64)   NOT NULL UNIQUE  -- SHA-256，防止重複上傳
);

-- =============================================
-- 4. 文件 Chunks
-- =============================================
CREATE TABLE document_chunks (
    id          INT IDENTITY(1,1) PRIMARY KEY,
    document_id INT           NOT NULL REFERENCES documents(id),
    chunk_index INT           NOT NULL,       -- 段落編號（從 1 開始）
    chunk_text  NVARCHAR(MAX) NOT NULL
);

CREATE INDEX idx_chunks_document ON document_chunks(document_id);

-- =============================================
-- 範例資料（選用）
-- =============================================
-- INSERT INTO document_groups (name, description) VALUES (N'Python 教材', N'Python 基礎與進階講義');
-- INSERT INTO users (username, password, role) VALUES (N'admin', N'admin123', N'admin');
-- INSERT INTO users (username, password, role) VALUES (N'user1',  N'user123',  N'user');
