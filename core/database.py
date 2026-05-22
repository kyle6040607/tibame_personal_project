import pyodbc


def get_connection():
    return pyodbc.connect(
        "DRIVER={ODBC Driver 18 for SQL Server};"
        "SERVER=localhost\\SQLEXPRESS;"
        "DATABASE=local_llm_notebook;"
        "Trusted_Connection=yes;"
        "TrustServerCertificate=yes;"
    )